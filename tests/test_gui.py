"""PyQt6 界面层功能测试。

覆盖：
1. 主窗口创建、标题与原有图标加载
2. 后台加载设备数据、分组按钮生成与双击触发分组登录
3. 设备列表加载、搜索过滤、双击触发快捷登录
4. 登录日志写入与清除
5. 关闭所有浏览器
6. 退出时的浏览器与后台任务清理
7. 菜单/快捷键入口可用性

使用本地模拟登录服务器，因此不依赖真实设备与内网环境；
设备数据通过替换加载函数注入，不会读写真实的 devices.json。

运行： python tests/test_gui.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from PyQt6.QtCore import QEventLoop          # noqa: E402
from PyQt6.QtWidgets import QApplication          # noqa: E402

from appcore import tasks as app_tasks         # noqa: E402
from appcore.browser import QUICK_SESSION, BrowserManager       # noqa: E402
from appcore.config import APP_NAME, APP_VERSION, LOG_DB_FILE         # noqa: E402
from appui.main_window import DoubleClickButton, LoginWindow  # noqa: E402
from tests.test_server import TestServer         # noqa: E402

RESULTS = []


def fetch_log_rows():
    """读取登录日志数据库的原始行（timestamp, device_name, url, status, message）"""
    import sqlite3

    conn = sqlite3.connect(LOG_DB_FILE)
    try:
        rows = conn.execute(
            "SELECT timestamp, device_name, url, status, message FROM login_logs "
            "ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
    return rows


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)


def wait_until(predicate, timeout=120, interval=0.2):
    """在 GUI 事件循环中等待条件成立"""
    app = QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        if predicate():
            return True
        time.sleep(interval)
    return False


def pump_events(seconds):
    """持续处理 GUI 事件若干秒"""
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.05)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} {APP_VERSION}")

    server = TestServer()
    server.__enter__()
    base = server.base_url

    good = {"name": "设备A", "url": f"{base}/login", "username": "admin",
            "password": "pass123", "group": "测试组", "template": "default"}
    bad = {"name": "设备B", "url": f"{base}/login", "username": "admin",
           "password": "wrong", "group": "测试组", "template": "default"}

    # 用测试数据替换真实 devices.json 的加载结果（不修改真实配置文件）
    app_tasks.load_devices = lambda: {"测试组": [good, bad]}

    window = LoginWindow()
    window.show()

    # 模板保存对话框为模态弹窗，测试中改为记录调用，避免阻塞事件循环
    saved_templates = []
    window._show_save_template_dialog = (
        lambda recorded, name, template_name='': saved_templates.append(
            (name, template_name, recorded)))

    # ---- 1. 窗口与图标 ----
    check("主窗口标题", window.windowTitle() == f"{APP_NAME} {APP_VERSION}", window.windowTitle())
    icon_ok = not window.windowIcon().isNull()
    check("窗口图标加载(ico/app.ico)", icon_ok, "图标为空" if not icon_ok else "图标已加载")

    # ---- 2. 菜单与快捷键入口 ----
    menu = window.menuBar()
    menu_texts = [a.text() for a in menu.actions()]
    check("菜单栏存在且有菜单项", len(menu_texts) > 0, " / ".join(menu_texts))

    # ---- 3. 设备数据后台加载 ----
    loaded = wait_until(lambda: window.devices_loaded, timeout=30)
    check("后台加载设备数据", loaded, f"分组数={len(window.group_combo) - 1}")
    check("分组下拉框含全部与分组", window.group_combo.count() == 2,
          f"条目={[window.group_combo.itemText(i) for i in range(window.group_combo.count())]}")

    # ---- 4. 分组按钮 ----
    buttons = window.group_container.findChildren(DoubleClickButton)
    check("分组按钮生成", len(buttons) == 1, f"按钮数={len(buttons)}")
    check("分组按钮双击信号", hasattr(buttons[0], 'doubleClicked') if buttons else False)
    if buttons:
        check("分组按钮显示设备数量", "2台" in buttons[0].text(), buttons[0].text())

    # ---- 5. 设备列表 ----
    window.update_device_list("全部")
    app.processEvents()
    check("设备列表加载", window.device_list.count() == 2, f"条目数={window.device_list.count()}")

    window.search_input.setText("设备A")
    app.processEvents()
    filtered = window.device_list.count() == 1
    window.search_input.setText("")
    app.processEvents()
    check("设备列表搜索过滤", filtered, "输入'设备A'后剩余条目")

    # ---- 6. 双击分组按钮 -> 分组登录 ----
    if buttons:
        buttons[0].doubleClicked.emit()
        done = wait_until(lambda: "成功" in window.progress_label.text(), timeout=240)
        text = window.progress_label.text()
        check("分组双击登录(后台执行)", done, text)
        check("分组登录结果统计", "1/2 成功" in text, text)
        # 设备已配置可用模板（default）时，不得再提示新建模板
        check("已有模板时不再提示保存模板", len(saved_templates) == 0,
              f"回调次数={len(saved_templates)}")

        # 分组登录的单设备记录：设备名/URL/状态必须正确写入数据库
        rows = fetch_log_rows()
        by_device = {r[1]: r for r in rows if r[1] in ("设备A", "设备B")}
        check("分组登录数据库含两台设备记录", len(by_device) == 2,
              f"设备记录={sorted(by_device)}")
        if "设备A" in by_device:
            row = by_device["设备A"]
            check("成功设备状态记为成功", row[3] == "成功", f"status={row[3]}")
            check("成功设备URL已记录", row[2] == good["url"], f"url={row[2]}")
        if "设备B" in by_device:
            row = by_device["设备B"]
            check("失败设备状态记为失败", row[3] == "失败", f"status={row[3]}")
            check("失败设备URL已记录", row[2] == bad["url"], f"url={row[2]}")

    # ---- 7. 双击设备列表项 -> 快捷登录 ----
    window.device_list.setCurrentRow(0)
    item = window.device_list.item(0)
    window.on_device_double_clicked(item)
    done = wait_until(lambda: "登录完成" in window.progress_label.text(), timeout=240)
    check("设备列表双击快捷登录", done, window.progress_label.text())
    quick_session = BrowserManager.get(QUICK_SESSION)
    check("快捷登录复用浏览器并新建标签页",
          quick_session is not None and quick_session.page_count >= 1,
          f"标签页数={quick_session.page_count if quick_session else 0}")

    # ---- 8. 日志 ----
    log_count = window.log_text.count()
    check("登录日志写入界面", log_count > 0, f"日志条数={log_count}")
    window.on_clear_log()
    check("清除日志", window.log_text.count() == 0, f"剩余={window.log_text.count()}")

    # ---- 9. 关闭所有浏览器 ----
    window.on_close_all_browsers()
    closed = wait_until(lambda: BrowserManager.session_count() == 0, timeout=90)
    check("关闭所有浏览器", closed, f"剩余会话={BrowserManager.session_count()}")

    # ---- 10. 退出清理 ----
    window.on_exit()
    pump_events(5)
    check("退出后无残留浏览器会话", BrowserManager.session_count() == 0,
          f"剩余会话={BrowserManager.session_count()}")

    # 让 Qt 在解释器退出前完成正常的对象销毁顺序（详见 test_ui_theme.py）
    try:
        window.deleteLater()
        app.processEvents()
    except RuntimeError:
        pass

    server.__exit__(None, None, None)
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
