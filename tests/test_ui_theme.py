"""界面层专项测试（V5.0.7 界面改造回归）。

覆盖：
1. 设计规范（颜色令牌 / 字体 / 全局样式表）可用且生效
2. 主窗口关键控件全部存在，且保持原有对象名与交互入口
3. 分组卡片：数量、每行布局规则、双击信号
4. 设备列表：加载、搜索过滤、卡片式委托渲染所需数据
5. 日志区：级别判定、级别着色、清空
6. 状态栏与顶部信息条
7. 组件库：InfoBar / MessageBox 接口与原用法兼容

本文件不依赖真实设备与内网环境，设备数据通过替换加载函数注入，
不会读写真实的 devices.json。

运行： python tests/test_ui_theme.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PyQt6.QtCore import QEventLoop, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from appcore import tasks as app_tasks  # noqa: E402
from appcore.config import APP_VERSION  # noqa: E402
from appui import theme  # noqa: E402
from appui.main_window import (GROUP_COLUMNS_MAX, DoubleClickButton,  # noqa: E402
                             LoginWindow)
from appui.ui_kit import (  # noqa: E402
    DeviceItemDelegate,
    InfoBar,
    LogItemDelegate,
    MessageBox,
    ROLE_LOG_LEVEL,
)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)


def pump(seconds=0.3):
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.02)


def main():
    app = QApplication(sys.argv)

    # ---- 1. 设计规范 ----
    check("主色令牌为 #409EFF", theme.PRIMARY.upper() == "#409EFF", theme.PRIMARY)
    check("成功/警告/错误色令牌",
          theme.SUCCESS.upper() == "#67C23A" and theme.WARNING.upper() == "#E6A23C"
          and theme.DANGER.upper() == "#F56C6C",
          f"{theme.SUCCESS}/{theme.WARNING}/{theme.DANGER}")
    check("背景色令牌（主背景/内容面板）",
          theme.BG_APP.upper() == "#F5F7FA" and theme.BG_PANEL.upper() == "#FFFFFF",
          f"{theme.BG_APP}/{theme.BG_PANEL}")
    sheet = theme.build_stylesheet()
    check("全局样式表非空且包含主色", bool(sheet) and theme.PRIMARY in sheet,
          f"长度={len(sheet)}")
    check("全局样式表包含主窗口背景", "mainInterface" in sheet)

    # ---- 2. 构造窗口（注入测试设备数据） ----
    good = {"name": "设备A", "url": "http://192.0.2.11/login", "username": "admin",
            "password": "pass", "group": "测试组", "template": "default"}
    bad = {"name": "设备B名称非常长用于测试省略", "url": "http://192.0.2.12:5666/login",
           "username": "admin", "password": "wrong", "group": "测试组"}
    app_tasks.load_devices = lambda: {"测试组": [good, bad]}

    window = LoginWindow()
    window.show()
    pump(1.0)

    check("窗口标题保持原格式", window.windowTitle().endswith(APP_VERSION), window.windowTitle())
    check("窗口图标仍可加载", not window.windowIcon().isNull())
    check("全局样式表已应用到应用", bool(app.styleSheet()), f"长度={len(app.styleSheet())}")
    check("应用字体已统一", app.font().family() == theme.FONT_FAMILY,
          f"{app.font().family()} {app.font().pointSizeF()}pt")

    # ---- 3. 关键控件仍然存在（原有功能入口一个不少）----
    required = [
        "stat_label", "group_container", "group_layout", "group_combo", "search_input",
        "filter_btn", "device_list", "quick_login_btn", "log_text", "clear_log_btn",
        "progress_label", "progress_bar", "close_browsers_btn", "exit_btn",
        "status_label", "session_label", "log_count_label",
        "refresh_btn", "help_btn", "about_btn",
    ]
    missing = [name for name in required if not hasattr(window, name)]
    check("主窗口关键控件齐全", not missing, f"缺失={missing}")

    check("菜单栏入口保留", len(window.menuBar().actions()) > 0,
          " / ".join(a.text() for a in window.menuBar().actions()))
    check("状态栏存在", window.statusBar() is not None)
    check("状态栏显示浏览器会话数", "浏览器会话" in window.session_label.text(),
          window.session_label.text())

    # ---- 4. 分组卡片 ----
    buttons = window.group_container.findChildren(DoubleClickButton)
    check("分组卡片已生成", len(buttons) == 1, f"卡片数={len(buttons)}")
    if buttons:
        check("分组卡片显示设备数量", "2台" in buttons[0].text(), buttons[0].text())
        check("分组卡片具备双击信号", hasattr(buttons[0], "doubleClicked"))
    check("每行分组卡片最大数量规则为 4", GROUP_COLUMNS_MAX == 4, str(GROUP_COLUMNS_MAX))
    check("分组列数随可用宽度自适应",
          1 <= window._current_group_columns() <= GROUP_COLUMNS_MAX,
          f"当前列数={window._current_group_columns()}")

    # ---- 5. 设备列表 ----
    window.update_device_list("全部")
    app.processEvents()
    check("设备列表加载", window.device_list.count() == 2,
          f"条目数={window.device_list.count()}")
    check("设备列表使用卡片式委托",
          isinstance(window.device_list.itemDelegate(), DeviceItemDelegate))
    item = window.device_list.item(0)
    device = item.data(Qt.ItemDataRole.UserRole) if item else None
    check("设备条目保留原始设备数据", bool(device) and "name" in device,
          str(device.get("name") if device else None))
    check("设备条目保留分组信息用于展示", bool(device) and device.get("group") == "测试组",
          str(device.get("group") if device else None))

    window.search_input.setText("设备A")
    app.processEvents()
    filtered = window.device_list.count() == 1
    window.search_input.setText("")
    app.processEvents()
    check("设备列表搜索过滤", filtered, "输入'设备A'后剩余条目")

    # ---- 6. 日志区 ----
    check("日志列表使用级别着色委托",
          isinstance(window.log_text.itemDelegate(), LogItemDelegate))
    window.add_log("✓ 设备A: 登录成功", "设备A", "http://x", True)
    window.add_log("✗ 设备B: 登录失败", "设备B", "http://y", False)
    window.add_log("请注意验证码", "设备A", "http://x", True)
    check("日志已写入界面", window.log_text.count() >= 3,
          f"条数={window.log_text.count()}")
    levels = [window.log_text.item(i).data(ROLE_LOG_LEVEL)
              for i in range(window.log_text.count())]
    check("日志级别区分成功/失败/警告",
          "success" in levels and "error" in levels and "warning" in levels,
          str(levels))
    check("日志条数统计已更新", "条" in window.log_count_label.text(),
          window.log_count_label.text())
    window.on_clear_log()
    check("清除日志", window.log_text.count() == 0, f"剩余={window.log_text.count()}")

    # ---- 7. 组件库：MessageBox / InfoBar ----
    box = MessageBox("测试标题", "第一行\n第二行\n第三行")
    check("MessageBox 提供 yesButton/cancelButton",
          hasattr(box, "yesButton") and hasattr(box, "cancelButton"))
    check("MessageBox 正文可换行展示",
          box.content_text.toPlainText().count("\n") == 2,
          repr(box.content_text.toPlainText()))
    box.yesButton.setText("更新")
    check("MessageBox 按钮文字可改写", box.yesButton.text() == "更新")
    box.deleteLater()

    bar = InfoBar.success(title="成功", content="操作已完成", parent=window, duration=800)
    check("InfoBar 可创建并挂载", bar is not None and bar.isVisible())
    if bar is not None:
        from PyQt6.QtWidgets import QLabel
        texts = [lb.text() for lb in bar.findChildren(QLabel)]
        check("InfoBar 记录了标题与正文",
              any("成功" in t for t in texts) and any("操作已完成" in t for t in texts),
              str(texts))
        bar.close()

    # ---- 8. 退出清理 ----
    window.on_exit()
    pump(1.0)
    check("退出流程可正常执行", True)

    # 让 Qt 在解释器退出前完成正常的对象销毁顺序：
    # 窗口若晚于 QApplication 被析构，退出期会偶发 0xC0000005 访问冲突。
    try:
        window.deleteLater()
        app.processEvents()
    except RuntimeError:
        pass

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
