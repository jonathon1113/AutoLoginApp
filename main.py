"""批量自动化登录工具 - 程序入口（PyQt6 + Playwright）。

启动流程：
1. 初始化模板目录与默认模板
2. 设置 Playwright 浏览器路径（与打包流程保持一致：PLAYWRIGHT_BROWSERS_PATH=0）
3. 创建 PyQt6 应用并显示主窗口
"""

import os
import sys
import time

# 高DPI支持
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

# 打包为单文件 EXE 后，Playwright 浏览器随包内置在 driver/package/.local-browsers，
# 必须让驱动节点在运行时也使用同一路径模式（与打包时的 PLAYWRIGHT_BROWSERS_PATH=0 保持一致）。
# 源码运行时：若本地已按“路径 0”安装过浏览器则沿用，否则使用 Playwright 默认安装位置。
def _configure_playwright_browsers_path():
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if getattr(sys, 'frozen', False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
        return
    try:
        import pathlib

        import playwright

        local_browsers = (pathlib.Path(playwright.__file__).parent
                          / "driver" / "package" / ".local-browsers")
        if local_browsers.exists() and any(local_browsers.iterdir()):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    except Exception:
        pass


_configure_playwright_browsers_path()

# 保证项目根目录在 sys.path 中（源码运行时用于导入 encrypt / icon_data）
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from appcore.config import APP_NAME, APP_VERSION, resolve_icon_path
from appcore.logging_utils import Logger
from appcore.templates import TemplateManager
from appui.main_window import LoginWindow


def main():
    started = time.perf_counter()

    def stage(label, since):
        now = time.perf_counter()
        Logger.info(f"[启动耗时] {label}: {int((now - since) * 1000)}ms")
        return now

    # 初始化模板：确保模板目录存在、缺失的默认模板文件被创建（不覆盖用户已改文件），
    # 然后从磁盘加载全部模板。
    mark = stage("准备（导入已完成）", started)
    TemplateManager.create_default_template_files()
    mark = stage("模板目录初始化 / 补齐", mark)
    TemplateManager.load_templates()
    mark = stage("模板加载与校验", mark)
    load_errors = TemplateManager.get_load_errors()
    if load_errors:
        Logger.warning(f"有 {len(load_errors)} 个模板文件存在问题，详见日志")
    Logger.info(
        f"模板目录: {TemplateManager.get_template_dir()}，"
        f"可用模板: {', '.join(TemplateManager.list_templates()) or '无'}"
    )

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} {APP_VERSION}")
    app.setOrganizationName("LoginApp")
    mark = stage("创建 QApplication", mark)

    icon_path = resolve_icon_path()
    if icon_path and os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 创建并显示窗口
    window = LoginWindow()
    mark = stage("主窗口初始化", mark)
    window.show()
    mark = stage("主窗口显示", mark)

    Logger.info(f"[启动耗时] 总计: {int((time.perf_counter() - started) * 1000)}ms")
    Logger.info(f"{APP_NAME} {APP_VERSION} 启动")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
