"""打包态（PyInstaller 冻结环境）验收自检入口。

一次运行完成两项验收：
1. 浏览器自检：以有头模式启动内置 Chromium，打开本地模拟登录页，
   完成一次真实登录，验证 Playwright 驱动与浏览器在 EXE 内可用。
2. GUI 自检：创建主窗口并离屏渲染，验证打包内的 Qt 运行库/插件完整，
   且本次新增的菜单入口（生成登录模板 / 浏览器窗口最大化还原）可用。

顺序说明：浏览器自检必须先于 GUI 自检，因为 GUI 自检收尾时会关闭自动化线程，
而浏览器自检依赖该线程。

用法：
    set SELFTEST_URL=http://127.0.0.1:8765/login
    python tests/frozen_acceptance.py
结果写入 selftest_acceptance.txt（位于 EXE 同目录，便于外部读取）。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appcore.config import get_app_dir  # noqa: E402

RESULT_FILE = os.path.join(get_app_dir(), 'selftest_acceptance.txt')


def write(text):
    with open(RESULT_FILE, 'w', encoding='utf-8') as f:
        f.write(text)


def _drain(window, app, timeout_ms=8000):
    """等待窗口的后台线程结束，并让排队的事件得到处理。

    LoginWindow 构造时会启动设备加载线程；若在它结束前销毁窗口，
    线程 emit 到已销毁的信号对象会抛出 RuntimeError。
    """
    try:
        window.thread_pool.waitForDone(timeout_ms)
    except Exception:
        pass
    try:
        app.processEvents()
    except Exception:
        pass


def browser_checks(lines, url):
    """浏览器自检：内置 Chromium 能否启动并完成一次真实登录。"""
    try:
        from appcore.browser import BrowserManager, BrowserService
        from appcore.login_engine import login_device
    except Exception as exc:
        lines.append(f'FAIL 浏览器模块导入失败: {exc}')
        return False

    async def _run():
        session = await BrowserManager.create('__selftest__')
        if session is None:
            lines.append('FAIL 浏览器启动失败')
            await BrowserService.stop()
            return False

        try:
            lines.append(f'PASS 浏览器启动成功 Chromium {session.browser.version}')
        except Exception:
            lines.append('PASS 浏览器启动成功')

        page = session.page
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(1)
        except Exception as exc:
            lines.append(f'FAIL 页面打开失败: {exc}')
            await BrowserManager.close_all()
            await BrowserService.stop()
            return False

        device = {"name": "自检设备", "url": url, "username": "admin",
                  "password": "pass123", "group": "自检组", "template": "default"}
        success, msg, _recorded = await login_device(session, device)
        lines.append(('PASS' if success else 'FAIL') + f' 登录流程: {msg}')

        current = page.url
        ok_url = current.endswith('/dashboard')
        lines.append(('PASS' if ok_url else 'FAIL') + f' 登录后URL: {current}')

        # 视口是否跟随窗口（no_viewport 生效的直观体现）
        try:
            inner = await page.evaluate("() => [window.innerWidth, window.innerHeight]")
            lines.append(f'PASS 页面视口尺寸={inner}')
        except Exception:
            pass

        await BrowserManager.close_all()
        await BrowserService.stop()
        return bool(success and ok_url)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        lines.append(f'FAIL 浏览器自检异常: {exc}')
        return False


def gui_checks(lines):
    """GUI 自检：主窗口能否创建、渲染，以及新增菜单入口是否存在。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:
        lines.append(f'FAIL PyQt6 导入失败: {exc}')
        return False

    app = QApplication.instance() or QApplication([])
    try:
        from appui.main_window import LoginWindow

        window = LoginWindow()
        window.show()
        app.processEvents()
        pixmap = window.grab()
        rendered = (not pixmap.isNull()) and pixmap.width() > 200 and pixmap.height() > 200
        lines.append(('PASS' if rendered else 'FAIL')
                     + f' 主窗口离屏渲染成功 尺寸={pixmap.width()}x{pixmap.height()}')
        _drain(window, app)
        window.close()
        app.processEvents()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        lines.append(f'FAIL 主窗口创建/渲染失败: {exc}')
        return False

    # 本次新增的两个菜单入口必须存在
    try:
        from appui.main_window import LoginWindow

        titles = []
        window2 = LoginWindow()
        for action in window2.menuBar().actions():
            menu = action.menu()
            if menu is None:
                continue
            titles.append(menu.title())
            for sub in menu.actions():
                titles.append(sub.text())
        _drain(window2, app)
        window2.close()
        app.processEvents()
        need = ('生成登录模板（不登录）', '浏览器窗口最大化 / 还原')
        missing = [item for item in need if item not in titles]
        lines.append(('PASS' if not missing else 'FAIL')
                     + f' 新增菜单入口齐备 菜单={titles}')
        return not missing
    except Exception as exc:
        lines.append(f'FAIL 菜单检查失败: {exc}')
        return False


def main():
    url = os.environ.get('SELFTEST_URL', 'http://127.0.0.1:8765/login')
    lines = []

    # 浏览器自检必须在 GUI 自检之前：GUI 自检收尾会关闭自动化线程
    browser_ok = browser_checks(lines, url)
    gui_ok = gui_checks(lines)

    for line in lines:
        print(line, flush=True)
    write('\n'.join(lines))
    return 0 if (gui_ok and browser_ok) else 1


if __name__ == '__main__':
    try:
        code = main()
    except Exception as exc:
        write(f'FAIL 异常: {exc}')
        code = 1
    sys.exit(code)
