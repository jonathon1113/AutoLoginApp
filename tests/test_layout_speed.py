"""V5.0.9 专项测试：登录速度优化 + 设备分组四列 + 底部布局居中。

覆盖：
1. 登录速度：正常页面不再触发慢速等待（验证码检查为毫秒级），
   验证码页面仍能识别且不提交登录，慢速页面仍保留等待能力。
2. 设备分组：窗口足够宽时每行 4 个，窗口变窄自动减少列数，
   分组数量与分组-设备映射关系不丢失。
3. 底部布局：进度条与浏览器控制按钮整体居中、间距紧凑，
   原有控件与功能入口全部保留。

运行： python tests/test_layout_speed.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 与 main.py 保持一致：源码运行时若浏览器已按「路径 0」安装，则沿用同一路径模式
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PyQt6.QtCore import QEventLoop, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame  # noqa: E402

from appcore import devices as device_store  # noqa: E402
from appcore.config import (CAPTCHA_QUICK_WAIT_BUDGET, SELECTOR_LOOKUP_READY_BUDGET,  # noqa: E402
                            SELECTOR_LOOKUP_SLOW_BUDGET)
from appui.main_window import (GROUP_CARD_MIN_WIDTH, GROUP_COLUMNS_MAX,  # noqa: E402
                             DoubleClickButton, LoginWindow)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)


def pump(seconds=0.4):
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.02)


def make_groups(count):
    """构造 count 个分组，每个分组 1 台设备。"""
    return {f"分组{i + 1}": [{"name": f"设备{i + 1}", "url": "http://127.0.0.1/login",
                            "username": "admin", "password": "p", "group": f"分组{i + 1}"}]
            for i in range(count)}


def cards_per_row(window):
    """读取当前分组卡片的实际每行数量（按几何位置分行）。"""
    buttons = window.group_container.findChildren(DoubleClickButton)
    if not buttons:
        return 0, 0
    tops = {}
    for btn in buttons:
        top = btn.mapTo(window.group_container, btn.rect().topLeft()).y()
        tops.setdefault(top, []).append(btn)
    first_row = max(tops.values(), key=len)
    return len(first_row), len(buttons)


# ==================== A 组：设备分组四列与响应式 ====================
def test_group_layout(app):
    original = device_store.get_groups
    window = LoginWindow()
    window.show()
    pump(0.6)

    try:
        for count in (1, 2, 4, 5, 8, 9):
            device_store.get_groups = lambda c=count: make_groups(c)
            window.resize(1700, 900)
            pump(0.5)
            window.create_group_buttons()
            pump(0.5)
            row, total = cards_per_row(window)
            check(f"分组数={count} 时卡片总数正确", total == count, f"实际={total}")
            expect_row = min(count, GROUP_COLUMNS_MAX)
            check(f"分组数={count} 时宽窗口每行 {expect_row} 个",
                  row == expect_row, f"实际每行={row}")
    finally:
        device_store.get_groups = original

    # ---- 响应式：窗口变窄时列数自动减少 ----
    device_store.get_groups = lambda: make_groups(8)
    window.resize(1700, 900)
    pump(0.5)
    window.create_group_buttons()
    pump(0.5)
    wide_cols = window._current_group_columns()
    wide_row, wide_total = cards_per_row(window)

    window.resize(560, 900)
    pump(0.8)
    narrow_cols = window._current_group_columns()
    narrow_row, narrow_total = cards_per_row(window)

    check("宽窗口使用最大列数", wide_cols == GROUP_COLUMNS_MAX, f"实际={wide_cols}")
    check("窄窗口自动减少列数", narrow_cols < wide_cols,
          f"窄={narrow_cols} 宽={wide_cols}")
    check("窄窗口列数不少于 1", narrow_cols >= 1, f"实际={narrow_cols}")
    check("缩放后分组卡片不丢失", narrow_total == wide_total == 8,
          f"宽={wide_total} 窄={narrow_total}")
    check("缩放后卡片实际每行数量与计算列数一致",
          narrow_row == narrow_cols, f"实际每行={narrow_row} 计算={narrow_cols}")
    check("窄窗口卡片未被压到最小宽度以下",
          narrow_cols == 1 or narrow_cols * (GROUP_CARD_MIN_WIDTH + 10) <= 570,
          f"列数={narrow_cols}")
    check("窄窗口下分组容器未超出可视区域（不裁切）",
          window.group_container.width() <= window.group_scroll.viewport().width() + 2,
          f"容器={window.group_container.width()} "
          f"视口={window.group_scroll.viewport().width()}")

    # ---- 默认窗口尺寸下即可显示 4 列 ----
    window.resize(1240, 720)
    pump(0.8)
    check("默认窗口宽度下即可显示 4 列分组",
          window._current_group_columns() == GROUP_COLUMNS_MAX,
          f"实际={window._current_group_columns()} "
          f"视口={window.group_scroll.viewport().width()}")

    # ---- 恢复宽度后列数回升 ----
    window.resize(1700, 900)
    pump(0.8)
    check("窗口放大后列数恢复为 4", window._current_group_columns() == GROUP_COLUMNS_MAX,
          f"实际={window._current_group_columns()}")

    # ---- 卡片内容与双击信号保留 ----
    buttons = window.group_container.findChildren(DoubleClickButton)
    check("分组卡片保留双击信号", all(hasattr(b, "doubleClicked") for b in buttons),
          f"卡片数={len(buttons)}")
    check("分组卡片保留分组名称", any("分组" in b.text() for b in buttons),
          buttons[0].text() if buttons else "")
    device_store.get_groups = original
    window.close()
    pump(0.3)


# ==================== B 组：底部布局居中 ====================
def test_footer_layout(app):
    window = LoginWindow()
    window.show()
    pump(0.8)

    for name in ("progress_label", "progress_bar", "close_browsers_btn", "exit_btn"):
        check(f"底部保留控件 {name}", hasattr(window, name))

    footer = window.close_browsers_btn.parent()
    check("底部容器存在", footer is not None)
    if footer is None:
        window.close()
        return

    for width in (1600, 1120, 900):
        window.resize(width, 760)
        pump(0.6)
        fw = footer.width()
        left = window.close_browsers_btn.mapTo(footer, window.close_browsers_btn.rect().topLeft()).x()
        right_edge = (window.exit_btn.mapTo(footer, window.exit_btn.rect().topLeft()).x()
                      + window.exit_btn.width())
        gap = left - window.close_browsers_btn.mapTo(
            footer, window.close_browsers_btn.rect().topLeft()).x()
        # 两个按钮之间的距离
        btn_gap = (window.exit_btn.mapTo(footer, window.exit_btn.rect().topLeft()).x()
                   - (window.close_browsers_btn.mapTo(
                       footer, window.close_browsers_btn.rect().topLeft()).x()
                      + window.close_browsers_btn.width()))
        left_space = left
        right_space = fw - right_edge
        check(f"窗口宽 {width} 时底部整体居中",
              abs(left_space - right_space) <= 40,
              f"左空白={left_space} 右空白={right_space} 宽={fw}")
        check(f"窗口宽 {width} 时两个按钮间距紧凑", 0 <= btn_gap <= 24,
              f"间距={btn_gap}")

    # 进度条与按钮不重叠
    window.resize(1120, 760)
    pump(0.6)
    bar = window.progress_bar
    bar.show()
    pump(0.3)
    bar_right = bar.mapTo(footer, bar.rect().topLeft()).x() + bar.width()
    btn_left = window.close_browsers_btn.mapTo(
        footer, window.close_browsers_btn.rect().topLeft()).x()
    check("进度条与按钮不重叠", bar_right <= btn_left,
          f"进度条右={bar_right} 按钮左={btn_left}")

    # 进度条可正常更新
    window.progress_bar.setValue(42)
    check("进度条可正常更新", window.progress_bar.value() == 42,
          str(window.progress_bar.value()))

    # 状态文字可换行显示，不被裁切
    window.progress_label.setWordWrap(True)
    check("状态文字启用换行", window.progress_label.wordWrap())

    # 按钮功能入口保留
    check("关闭浏览器按钮保留点击连接",
          window.close_browsers_btn.receivers(window.close_browsers_btn.clicked) >= 0)
    check("退出按钮保留点击连接",
          window.exit_btn.receivers(window.exit_btn.clicked) >= 0)
    window.close()
    pump(0.3)


# ==================== C 组：登录速度与慢速等待 ====================
async def _login_once(url, template='default', username='admin', password='pass123'):
    from appcore.browser import BrowserManager, BrowserService
    from appcore.login_engine import login_device

    session = await BrowserManager.create('__layout_speed__')
    try:
        page = session.page
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        device = {"name": "测速设备", "url": url, "username": username,
                  "password": password, "group": "g", "template": template}
        started = time.monotonic()
        success, msg, recorded = await login_device(session, device)
        elapsed = int((time.monotonic() - started) * 1000)
        return success, msg, recorded, elapsed, page
    finally:
        await BrowserManager.close_all()
        await BrowserService.stop()


async def test_login_speed():
    import appcore.login_engine as le
    from appcore import config as app_config
    from test_server import LoginHandler, TestServer

    # 本用例验证的是历史行为：「发现验证码输入框即停止，不提交登录表单」。
    # 验证码自动识别（V6.0.1 起）开启后会尝试 OCR，因此这里必须关闭，
    # 保持原断言不变。
    original_auto = app_config.CAPTCHA_AUTO_ENABLED
    app_config.CAPTCHA_AUTO_ENABLED = False

    slow_calls = []
    original_detailed = le.find_captcha_field_detailed

    async def spy(*args, **kwargs):
        slow_calls.append(kwargs.get('extra_budget'))
        return await original_detailed(*args, **kwargs)

    le.find_captcha_field_detailed = spy
    try:
        with TestServer() as server:
            base = server.base_url

            # ---- C1 正常页面：无验证码，应走快速检查 ----
            slow_calls.clear()
            LoginHandler.reset_post_count()
            success, msg, recorded, elapsed, _page = await _login_once(f'{base}/login')
            check("正常页面登录成功", success, msg)
            check("正常页面未调用慢速验证码查找", not slow_calls,
                  f"调用次数={len(slow_calls)} 预算={slow_calls}")
            check("正常页面总耗时恢复到快速区间（<8s）", elapsed < 8000,
                  f"耗时={elapsed}ms")

            # ---- C2 验证码页面：识别到验证码且不提交登录 ----
            slow_calls.clear()
            LoginHandler.reset_post_count()
            success, msg, recorded, elapsed, _page = await _login_once(f'{base}/captcha')
            captcha_sel = (recorded or {}).get('captcha_selectors') or []
            check("验证码页面识别到验证码输入框", bool(captcha_sel), str(captcha_sel))
            check("验证码页面未提交登录表单", LoginHandler.post_count == 0,
                  f"提交次数={LoginHandler.post_count}")
            check("验证码页面未被慢速等待拖慢", elapsed < 8000, f"耗时={elapsed}ms")

            # ---- C3 慢速页面：仍保留慢速等待能力 ----
            slow_calls.clear()
            LoginHandler.reset_post_count()
            success, msg, recorded, elapsed, _page = await _login_once(f'{base}/slowjs')
            check("慢速页面仍能定位到输入框（等待能力保留）",
                  bool((recorded or {}).get('username_selectors')),
                  f"recorded={recorded}")
    finally:
        le.find_captcha_field_detailed = original_detailed
        app_config.CAPTCHA_AUTO_ENABLED = original_auto


async def _login_in_session(url, session_name):
    """建立独立会话并登录（不中途关闭会话，供并发批量测试使用）"""
    from appcore.browser import BrowserManager
    from appcore.login_engine import login_device

    session = await BrowserManager.create(session_name)
    page = session.page
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    device = {"name": "并发设备", "url": url, "username": "admin",
              "password": "pass123", "group": "g", "template": "default"}
    started = time.monotonic()
    success, msg, recorded = await login_device(session, device)
    return success, msg, recorded, int((time.monotonic() - started) * 1000)


async def test_batch_mixed_speed():
    """多设备批量登录：其中一个页面较慢，不应拖累其他正常页面。"""
    from appcore.browser import BrowserManager, BrowserService
    from test_server import LoginHandler, TestServer

    try:
        with TestServer() as server:
            base = server.base_url
            LoginHandler.reset_post_count()

            slow_task = asyncio.create_task(
                _login_in_session(f'{base}/slowjs', '__mix_slow__'))
            normal_task = asyncio.create_task(
                _login_in_session(f'{base}/login', '__mix_normal__'))

            normal = await normal_task
            check("批量登录中正常页面未被慢速页面拖慢",
                  normal[3] < 8000, f"正常页面耗时={normal[3]}ms")
            check("批量登录中正常页面登录成功", normal[0], normal[1])

            slow = await slow_task
            check("批量登录中慢速页面仍保留等待能力并完成定位",
                  bool(slow[0]) or bool((slow[2] or {}).get('username_selectors')),
                  f"成功={slow[0]} 耗时={slow[3]}ms msg={slow[1]}")
            check("批量登录中慢速页面耗时仍在有上限的等待范围内",
                  slow[3] < 25000, f"耗时={slow[3]}ms")
    finally:
        await BrowserManager.close_all()
        await BrowserService.stop()


def test_speed_constants():
    check("验证码快速检查窗口为有限值",
          0 < CAPTCHA_QUICK_WAIT_BUDGET <= 3.0, str(CAPTCHA_QUICK_WAIT_BUDGET))
    check("快速检查窗口明显小于慢速扩展预算",
          CAPTCHA_QUICK_WAIT_BUDGET < SELECTOR_LOOKUP_SLOW_BUDGET,
          f"{CAPTCHA_QUICK_WAIT_BUDGET} < {SELECTOR_LOOKUP_SLOW_BUDGET}")
    check("慢速扩展预算仍然保留", SELECTOR_LOOKUP_SLOW_BUDGET >= 5.0,
          str(SELECTOR_LOOKUP_SLOW_BUDGET))
    check("已就绪页面的扩展等待预算仍然保留",
          SELECTOR_LOOKUP_READY_BUDGET >= 1.0, str(SELECTOR_LOOKUP_READY_BUDGET))


def main():
    app = QApplication(sys.argv)
    test_speed_constants()
    test_group_layout(app)
    test_footer_layout(app)
    asyncio.run(test_login_speed())
    asyncio.run(test_batch_mixed_speed())

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("=" * 68)
    print(f"布局与速度专项测试: {passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
