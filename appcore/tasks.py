"""后台任务（QRunnable）。

所有浏览器相关任务都在线程池线程中运行，并把 Playwright 协程投递到自动化线程执行，
因此界面主线程不会被浏览器操作阻塞。
"""

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from .automation import get_loop
from .browser import BrowserManager
from .devices import load_devices
from .excel_io import import_devices_from_excel
from .login_engine import (generate_template_for_device, login_group, quick_login)
from .logging_utils import log_exception


def _safe_emit(owner, signal_name, *args, **kwargs):
    """在 QRunnable 线程中安全地发射信号。

    窗口关闭时 QApplication 与信号对象可能已被销毁，此时连
    `owner.signals.loaded` 这个属性访问本身就会抛出 RuntimeError；
    而 QRunnable 线程中未捕获的 Python 异常会让 PyQt6 直接 abort
    整个进程（表现为闪退）。

    因此这里把「取信号对象」与「发射信号」都放在 try 内，
    统一兜底并写入日志：

    - 真实的业务异常仍在各自的 except 分支中处理并上报，不会被吞掉；
    - 仅“目标对象已销毁”这一类关闭时序异常被降级为日志。

    用法：_safe_emit(self, 'loaded', devices)
    """
    try:
        signal = getattr(owner.signals, signal_name)
        signal.emit(*args, **kwargs)
    except RuntimeError as exc:
        log_exception(exc, "任务信号发射（目标对象可能已销毁）")
    except AttributeError as exc:
        log_exception(exc, f"任务信号 {signal_name} 不存在")


def _safe_call(callback, *args, **kwargs):
    """在 QRunnable 线程中安全地调用回调（回调通常是窗口槽函数）。"""
    try:
        callback(*args, **kwargs)
    except RuntimeError as exc:
        log_exception(exc, "任务回调调用（目标对象可能已销毁）")


class LoginSignals(QObject):
    """登录任务信号"""
    finished = pyqtSignal(str, int, int)        # msg, current, total
    # success, message, recorded_selectors, template_name（设备配置的模板名）
    quick_finished = pyqtSignal(bool, str, object, str)
    # 原项目此处为 pyqtSignal(str, str)，与实际发射的 dict 不匹配导致保存模板失败，已修正
    # device_name, recorded_selectors, template_name
    template_recorded = pyqtSignal(str, object, str)


class LoadDevicesSignals(QObject):
    """设备加载信号"""
    loaded = pyqtSignal(dict)   # devices_by_group
    error = pyqtSignal(str)     # error message


class LoadDevicesTask(QRunnable):
    """后台加载设备任务"""

    def __init__(self):
        super().__init__()
        self.signals = LoadDevicesSignals()

    def run(self):
        try:
            devices = load_devices()
            _safe_emit(self, 'loaded', devices)
        except Exception as e:
            _safe_emit(self, 'error', str(e))


class ImportExcelSignals(QObject):
    """Excel 导入信号"""
    progress = pyqtSignal(str)   # 阶段提示
    finished = pyqtSignal(dict)  # 导入结果
    error = pyqtSignal(str)      # 失败原因


class ImportExcelTask(QRunnable):
    """后台 Excel 导入任务。

    线程边界（重要）：
    - 工作线程只做**数据处理**：读文件、解析、校验、加密写盘；
    - **绝不创建、修改或删除任何界面控件**；
    - 界面更新（状态提示、列表刷新、结果弹窗）一律通过信号回到主线程；
    - 窗口关闭时信号发射异常由 _safe_emit 兜底，不会让进程 abort。
    """

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.signals = ImportExcelSignals()

    def run(self):
        try:
            result = import_devices_from_excel(
                self.file_path,
                progress=lambda text: _safe_emit(self, 'progress', text))
            _safe_emit(self, 'finished', result)
        except Exception as e:
            log_exception(e, "Excel 导入")
            _safe_emit(self, 'error', str(e))


class QuickLoginTask(QRunnable):
    """快捷登录任务"""

    def __init__(self, name, url, username, password, template_name="default"):
        super().__init__()
        self.name = name
        self.url = url
        self.username = username
        self.password = password
        self.template_name = template_name
        self.signals = LoginSignals()

    def run(self):
        try:
            loop = get_loop()
            success, message, recorded = loop.submit(
                quick_login(self.name, self.url, self.username, self.password, self.template_name)
            )
            _safe_emit(self, 'quick_finished', success, message, recorded,
                       self.template_name)
        except Exception as e:
            log_exception(e, f"快捷登录 {self.name}")
            _safe_emit(self, 'quick_finished', False, f"✗ {self.name}: {str(e)[:50]}",
                       None, self.template_name)


class GroupLoginTask(QRunnable):
    """分组批量登录任务"""

    def __init__(self, group_name):
        super().__init__()
        self.group_name = group_name
        self.signals = LoginSignals()

    def run(self):
        try:
            loop = get_loop()

            def progress_callback(msg, current, total):
                _safe_emit(self, 'finished', msg, current, total)

            results, recorded_candidates = loop.submit(
                login_group(self.group_name, progress_callback)
            )

            if results:
                success = [r for r in results if r and r[0]]
                failed = [r for r in results if not (r and r[0])]
                success_count = len(success)
                total = len(results)

                msg = f"✓ {self.group_name}: {success_count}/{total} 成功"
                if failed:
                    failed_names = [r[1].split(':')[0] for r in failed if r]
                    failed_str = ', '.join(failed_names[:3])
                    msg += f" | 失败: {failed_str}"
                    if len(failed) > 3:
                        msg += f"...等{len(failed)}台"

                _safe_emit(self, 'finished', msg, total, total)

                # 登录成功后，逐台设备上报录制到的选择器（连同设备名与配置的模板名），
                # 由界面按统一规则判断是否需要提示保存模板
                for candidate in (recorded_candidates or []):
                    recorded = candidate.get('recorded')
                    if recorded and any(recorded.values()):
                        _safe_emit(
                            self, 'template_recorded',
                            candidate.get('device', ''),
                            recorded,
                            candidate.get('template', ''),
                        )
            else:
                _safe_emit(self, 'finished', f"✗ {self.group_name}: 无设备或登录失败", 0, 0)
        except Exception as e:
            log_exception(e, f"GroupLoginTask {self.group_name}")
            _safe_emit(self, 'finished', f"✗ {self.group_name}: {str(e)[:50]}", 0, 0)


class GenerateTemplateTask(QRunnable):
    """生成登录模板任务（只识别，不填写、不点击、不提交登录）

    用于带图片验证码的登录页面：先把用户名/密码/验证码输入框的选择器
    识别出来并保存为模板，之后再使用该模板正常登录。
    """

    def __init__(self, name, url, template_name=""):
        super().__init__()
        self.name = name
        self.url = url
        self.template_name = template_name
        self.signals = LoginSignals()

    def run(self):
        try:
            loop = get_loop()
            success, message, recorded = loop.submit(
                generate_template_for_device(self.name, self.url, self.template_name)
            )
            _safe_emit(self, 'quick_finished', success, message, recorded,
                       self.template_name)
        except Exception as e:
            log_exception(e, f"生成模板 {self.name}")
            _safe_emit(self, 'quick_finished', False, f"✗ {self.name}: {str(e)[:50]}",
                       None, self.template_name)


class BrowserWindowTask(QRunnable):
    """浏览器窗口最大化 / 还原任务

    使用 Chromium 的 CDP 接口调整窗口（普通最大化，始终可退出，
    不会进入无法退出的全屏状态）；每个会话独立处理，互不影响。
    """

    def __init__(self, state, callback):
        super().__init__()
        self.state = state
        self.callback = callback  # (ok_count, total, message)
        self.signals = LoginSignals()

    def run(self):
        try:
            loop = get_loop()
            loop.submit(self._apply())
        except Exception as e:
            log_exception(e, "调整浏览器窗口")
            _safe_call(self.callback, 0, 0, f"调整浏览器窗口失败：{str(e)[:40]}")

    async def _apply(self):
        names = BrowserManager.session_names()
        ok = 0
        detail = ''
        for name in names:
            session = BrowserManager.get(name)
            if session is None:
                continue
            try:
                success, message = await session.set_window_state(self.state)
            except Exception as e:
                log_exception(e, f"设置窗口状态 {self.state} ({name})")
                success, message = False, str(e)[:60]
            if success:
                ok += 1
            elif not detail:
                detail = message
        _safe_call(self.callback, ok, len(names), detail)


class CloseBrowsersTask(QRunnable):
    """关闭浏览器任务"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback  # (closed, total) -> None

    def run(self):
        try:
            loop = get_loop()
            count = BrowserManager.session_count()
            if count == 0:
                _safe_call(self.callback, 0, 0)
                return
            loop.submit(BrowserManager.close_all())
            _safe_call(self.callback, count, count)
        except Exception as e:
            log_exception(e, "关闭浏览器")
            _safe_call(self.callback, 0, 0)
