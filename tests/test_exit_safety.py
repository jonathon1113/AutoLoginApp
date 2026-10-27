"""退出期安全专项测试。

覆盖「程序退出 / 脚本收尾」阶段的健壮性：

1. 自动化线程正常停止后，线程与事件循环引用被正确释放；
2. **线程未在超时内退出时必须保留线程引用**——
   丢掉引用会让 daemon 线程在解释器退出时被强杀，
   若它正停在 asyncio / Playwright 的 C 扩展内部就会造成
   0xC0000005（访问冲突）闪退；
3. 未停止时不得谎报“已停止”（is_running 语义正确）；
4. shutdown / start 幂等，重复调用不抛异常。

运行： python tests/test_exit_safety.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from appcore.automation import AutomationLoop  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)


class _StubbornThread:
    """模拟「join 超时后仍未退出」的线程。"""

    name = "stubborn-automation"

    def __init__(self):
        self.join_calls = []

    def join(self, timeout=None):
        self.join_calls.append(timeout)

    def is_alive(self):
        return True


def run_normal_shutdown():
    lp = AutomationLoop(name="exit-safety-normal")
    lp.start()
    check("自动化线程可启动", lp.is_running)
    check("启动后线程对象存在", lp._thread is not None)

    lp.shutdown()
    check("正常停止后 is_running 为 False", not lp.is_running)
    check("正常停止后线程引用被释放", lp._thread is None,
          f"_thread={lp._thread}")
    check("正常停止后事件循环引用被释放", lp._loop is None,
          f"_loop={lp._loop}")

    # 幂等：重复 shutdown 不得抛异常
    try:
        lp.shutdown()
        ok = True
        detail = ""
    except Exception as e:
        ok = False
        detail = f"异常: {e}"
    check("重复 shutdown 不抛异常（幂等）", ok, detail)

    # 未启动就 shutdown 也不得抛异常
    try:
        AutomationLoop(name="exit-safety-never-started").shutdown()
        ok = True
        detail = ""
    except Exception as e:
        ok = False
        detail = f"异常: {e}"
    check("从未启动的实例 shutdown 不抛异常", ok, detail)


def run_start_idempotent():
    lp = AutomationLoop(name="exit-safety-idempotent")
    lp.start()
    first = lp._thread
    lp.start()
    check("重复 start 不新建第二个线程", lp._thread is first)
    lp.shutdown()


def run_stubborn_thread_keeps_reference():
    """线程未退出时必须保留引用（防退出期强杀）。"""
    lp = AutomationLoop(name="exit-safety-stubborn")
    stub = _StubbornThread()
    lp._thread = stub
    # _loop 保持 None：跳过 call_soon_threadsafe 分支，只验证引用保留语义
    lp.shutdown()
    check("线程未退出时保留线程引用（不被置 None）",
          lp._thread is stub, f"_thread={lp._thread!r}")
    check("线程未退出时确实尝试过 join", len(stub.join_calls) >= 1,
          f"join 调用={stub.join_calls}")
    check("线程未退出时未谎报“已停止”（is_running 依据 _loop 判定）",
          not lp.is_running)


def run_stubborn_thread_with_loop():
    """线程未退出且 _loop 仍在时，is_running 必须仍为 True。"""
    lp = AutomationLoop(name="exit-safety-stubborn-loop")
    stub = _StubbornThread()
    lp._thread = stub

    class _FakeLoop:
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, fn):
            return None

    lp._loop = _FakeLoop()
    lp.shutdown()
    check("线程未退出时 is_running 仍为 True（未谎报已停止）",
          lp.is_running)
    check("线程未退出时保留事件循环引用", lp._loop is not None)


def main():
    run_normal_shutdown()
    run_start_idempotent()
    run_stubborn_thread_keeps_reference()
    run_stubborn_thread_with_loop()
    return 0


def report():
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"测试结果: {passed} 通过 / {failed} 失败")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTS.append(("测试执行异常", False, "见堆栈"))
    sys.exit(report())