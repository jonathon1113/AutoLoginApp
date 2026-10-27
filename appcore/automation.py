"""Playwright 自动化运行时。

Playwright 的异步对象（Browser / Context / Page）只能在其所属的事件循环线程中创建与使用，
因此这里用一个独立线程承载 asyncio 事件循环：

- GUI 线程只负责界面，永远不会被浏览器操作阻塞；
- 工作线程通过 submit() 把协程投递到自动化线程执行并等待结果；
- 多个分组可并发登录（每个分组独立 Browser，会话隔离规则与原项目一致）。
"""

import asyncio
import threading

from .logging_utils import Logger


class AutomationLoop:
    """在专用线程中运行 asyncio 事件循环"""

    def __init__(self, name="playwright-automation"):
        self._name = name
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._start_error = None
        self._start_lock = threading.Lock()

    # ---------------- 生命周期 ----------------
    def start(self):
        """启动自动化线程（幂等）"""
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(target=self._thread_main, name=self._name, daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout=15):
                raise RuntimeError("自动化线程启动超时")
            if self._start_error is not None:
                raise self._start_error

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    @property
    def is_running(self):
        return self._loop is not None and not self._loop.is_closed()

    # ---------------- 任务投递 ----------------
    def submit(self, coro, timeout=None):
        """在自动化线程执行协程并阻塞等待结果"""
        if not self.is_running:
            raise RuntimeError("自动化线程未启动")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def shutdown(self, cleanup_coro=None, timeout=25):
        """执行清理协程后停止自动化线程"""
        if cleanup_coro is not None and self.is_running:
            try:
                self.submit(cleanup_coro, timeout=timeout)
            except Exception:
                pass

        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass

        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                # 线程没在超时内退出：**绝不能丢掉对它的引用**。
                # 丢掉引用后，解释器退出时这个 daemon 线程会被直接强杀；
                # 若它此刻正停在 asyncio / Playwright 的 C 扩展内部，
                # 强杀就会造成 0xC0000005（访问冲突）闪退，且事后无法复现定位。
                # 这里保留引用并记录告警：既不谎报“已停止”，
                # 也避免线程在退出期被无保护地强杀。
                Logger.warning(
                    "自动化线程未在 10s 内退出，保留线程引用以避免退出期强杀"
                    "（线程名=%s）" % self._thread.name)
                return

        self._loop = None
        self._thread = None
        self._ready.clear()

    def stop(self, timeout=10):
        """仅停止事件循环（不执行清理）"""
        self.shutdown(cleanup_coro=None, timeout=timeout)


# 全局单例
automation_loop = AutomationLoop()


def get_loop():
    """获取（必要时启动）全局自动化循环"""
    if not automation_loop.is_running:
        automation_loop.start()
    return automation_loop
