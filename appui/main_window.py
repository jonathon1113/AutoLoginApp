"""主窗口界面（PyQt6 原生控件 + 全局样式表）。

界面布局、功能入口、按钮、菜单、交互方式与原项目保持一致；
仅把浏览器操作改为通过后台任务 + Playwright 执行，
并把视觉样式统一到 appui/theme.py 定义的设计规范。
"""

import ctypes
import datetime
import os
import subprocess
import time

from encrypt import no_window_kwargs

from PyQt6.QtCore import QEvent, QSize, Qt, QThreadPool, QTimer, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFontMetrics, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from appui.ui_kit import (
    BodyLabel,
    CaptionLabel,
    DeviceItemDelegate,
    GhostPushButton,
    InfoBar,
    InfoBarPosition,
    LogItemDelegate,
    MessageBox,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ROLE_LOG_LEVEL,
    ScrollArea,
    StrongBodyLabel,
    TitleLabel,
    ToolPushButton,
    divider,
    make_badge,
)
from appui.theme import (
    BORDER,
    DANGER,
    PRIMARY,
    PRIMARY_BORDER,
    PRIMARY_LIGHT,
    SUCCESS,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    apply_theme,
    base_font,
)

from appcore import devices as device_store
from appcore.automation import get_loop
from appcore.browser import BrowserManager, BrowserService
from appcore.config import (
    APP_DIR,
    APP_NAME,
    APP_VERSION,
    CONFIG_FILE,
    EXCEL_TEMPLATE_FILE,
    TEMPLATE_DIR,
    resolve_icon_path,
)
from appcore.logdb import log_db
from appcore.logging_utils import Logger, log_exception
from appcore.tasks import (
    BrowserWindowTask,
    CloseBrowsersTask,
    GenerateTemplateTask,
    GroupLoginTask,
    ImportExcelTask,
    LoadDevicesTask,
    QuickLoginTask,
)
from appcore.templates import (TemplateManager, evaluate_save_template_request,
                               suggest_template_name)

# ========== 设备分组卡片布局规则 ==========
# - 窗口足够宽时每行最多 4 个分组卡片；
# - 窗口变窄时按可用宽度自动减少列数，避免卡片过窄导致标题/按钮裁切；
# - 卡片宽度在可用空间内均分，保持统一的间距与内边距。
GROUP_COLUMNS_MAX = 4
GROUP_CARD_MIN_WIDTH = 118     # 单个分组卡片的最小宽度（低于此值不再增加列数）
GROUP_CARD_MAX_WIDTH = 320     # 单个分组卡片的最大宽度
GROUP_CARD_SPACING = 10        # 卡片之间的水平间距

# 日志级别对应的前景色
_LOG_LEVEL_COLORS = {
    "info": TEXT_PRIMARY,
    "success": SUCCESS,
    "warning": WARNING,
    "error": DANGER,
}


def _clear_layout(layout):
    """递归清空布局（刷新分组卡片时使用）"""
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()
        elif child.layout():
            _clear_layout(child.layout())


class DoubleClickButton(QPushButton):
    """支持双击信号的分组卡片按钮。

    自绘外观：第一行为分组名（粗体），第二行为设备数量（次要色），
    长分组名自动省略，避免长文本撑破卡片布局。
    """

    doubleClicked = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("groupCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(110, 62)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._name_font = base_font(10, bold=True)
        self._count_font = base_font(8.5)

    def mouseDoubleClickEvent(self, event):
        event.accept()  # 接受事件，防止传播
        self.doubleClicked.emit()

    def minimumSizeHint(self):
        """卡片的最小尺寸固定，不随分组名长度变化。

        卡片文字为自绘 + 自动省略显示，长分组名不会撑破整行布局，
        否则 4 张卡片会把分组区域撑到超出面板宽度（导致列数无法减少）。
        """
        return QSize(110, 62)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)

        if self.isDown():
            bg, border, name_color = PRIMARY_BORDER, PRIMARY, PRIMARY
        elif self.underMouse():
            bg, border, name_color = PRIMARY_LIGHT, PRIMARY, PRIMARY
        else:
            bg, border, name_color = "#FFFFFF", BORDER, TEXT_PRIMARY

        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 6, 6)

        lines = (self.text() or "").split("\n")
        name = lines[0] if lines else ""
        count = lines[1] if len(lines) > 1 else ""

        name_metrics = QFontMetrics(self._name_font)
        count_metrics = QFontMetrics(self._count_font)
        text_width = max(20, rect.width() - 16)

        name_height = name_metrics.height()
        count_height = count_metrics.height() if count else 0
        gap = 4 if count else 0
        total_height = name_height + gap + count_height
        top = rect.top() + max(6, (rect.height() - total_height) // 2)

        painter.setFont(self._name_font)
        painter.setPen(QColor(name_color))
        name_rect = rect.__class__(rect.left() + 8, top, text_width, name_height)
        painter.drawText(name_rect,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         name_metrics.elidedText(name, Qt.TextElideMode.ElideRight, text_width))

        if count:
            painter.setFont(self._count_font)
            painter.setPen(QColor(TEXT_SECONDARY))
            count_rect = rect.__class__(rect.left() + 8, top + name_height + gap,
                                        text_width, count_height)
            painter.drawText(count_rect,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                             count_metrics.elidedText(count, Qt.TextElideMode.ElideRight,
                                                      text_width))
        painter.end()


class LoginWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        # 设置 App User Model ID (任务栏图标)
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AutoLogin_app")
        except Exception:
            pass

        # 设置主题（统一浅色主题与设计规范）
        apply_theme()

        # 设置窗口属性
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        icon_path = resolve_icon_path()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 初始化线程池
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(10)  # 最多10个并发线程

        # 初始化状态
        self.devices_loaded = False
        self._exiting = False
        self._excel_importing = False

        # 创建主界面（先创建基本UI，不阻塞）
        self.setup_ui()

        # 显示加载中状态
        self.show_loading_state()

        # 后台加载设备数据
        self.start_load_devices()

        # 调整窗口大小
        self.adjust_size()

    # ============ 设备数据 ============
    def show_loading_state(self):
        """显示加载中状态"""
        self.stat_label.setText("正在加载设备数据...")
        self.group_container.setEnabled(False)

    def start_load_devices(self):
        """启动后台加载设备数据"""
        task = LoadDevicesTask()
        task.signals.loaded.connect(self.on_devices_loaded)
        task.signals.error.connect(self.on_devices_load_error)
        self.thread_pool.start(task)

    def on_devices_loaded(self, devices):
        """设备加载完成回调"""
        started = time.monotonic()
        device_store.set_groups(devices)
        self.devices_loaded = True

        # 更新统计信息
        total = sum(len(d) for d in devices.values())
        self.stat_label.setText(f"共 {len(devices)} 个分组，{total} 台设备")

        # 更新分组下拉框
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(["全部"] + sorted(devices.keys()))
        self.group_combo.blockSignals(False)

        # 启用并创建分组按钮
        self.group_container.setEnabled(True)
        self.create_group_buttons()

        # 设备列表随分组数据一起刷新（分组下拉框的变化信号已被屏蔽，需主动刷新）
        self.update_device_list(self.group_combo.currentText())

        elapsed = int((time.monotonic() - started) * 1000)
        Logger.info(f"已加载 {len(devices)} 个分组，共 {total} 台设备"
                    f"（分组与界面构建耗时 {elapsed}ms）")
        self._refresh_status(f"已加载 {len(devices)} 个分组，共 {total} 台设备"
                             f"（耗时 {elapsed}ms）")

    def on_devices_load_error(self, error_msg):
        """设备加载失败回调"""
        self.stat_label.setText("加载设备失败，请检查配置文件")
        self.group_container.setEnabled(True)
        Logger.error(f"加载设备失败: {error_msg}")

    # ============ 界面构建 ============
    def setup_ui(self):
        """创建用户界面"""
        # ========== 顶部标题栏：应用名称、版本号、全局操作与统计信息 ==========
        header = QFrame(self)
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 10, 18, 10)
        header_layout.setSpacing(10)

        icon_label = QLabel(header)
        icon_path = resolve_icon_path()
        if icon_path and os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(26, 26))
        header_layout.addWidget(icon_label)

        title = TitleLabel(APP_NAME, header)
        header_layout.addWidget(title)
        header_layout.addWidget(make_badge(f"V{APP_VERSION}", "appVersion", header))
        header_layout.addSpacing(6)
        header_layout.addWidget(divider(True, header))
        header_layout.addSpacing(6)

        # 统计信息
        groups = device_store.get_groups()
        total = sum(len(d) for d in groups.values())
        self.stat_label = make_badge(f"共 {len(groups)} 个分组，{total} 台设备",
                                     "statChip", header)
        header_layout.addWidget(self.stat_label)

        header_layout.addStretch()

        # 全局操作（低干扰样式，主操作按钮保留在底部）
        self.refresh_btn = GhostPushButton("刷新配置", header)
        self.refresh_btn.clicked.connect(self.on_refresh)
        header_layout.addWidget(self.refresh_btn)

        self.help_btn = GhostPushButton("使用说明", header)
        self.help_btn.clicked.connect(self.show_help)
        header_layout.addWidget(self.help_btn)

        self.about_btn = GhostPushButton("关于", header)
        self.about_btn.clicked.connect(self.show_about)
        header_layout.addWidget(self.about_btn)

        # ========== 左侧面板：设备分组 ==========
        left_panel = QFrame(self)
        left_panel.setObjectName("panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(8)

        left_head = QHBoxLayout()
        left_head.setSpacing(8)
        left_head.addWidget(StrongBodyLabel("设备分组", left_panel))
        left_head.addStretch()
        left_head.addWidget(CaptionLabel("双击分组卡片登录该组全部设备", left_panel))
        left_layout.addLayout(left_head)

        scroll = ScrollArea(left_panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.group_scroll = scroll
        # 视口尺寸变化时（窗口缩放 / 拖动分隔条）重新排列分组卡片
        scroll.viewport().installEventFilter(self)
        self._relayouting = False

        self.group_container = QWidget()
        self.group_layout = QVBoxLayout(self.group_container)
        self.group_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.group_layout.setSpacing(10)
        self._group_columns = 0

        scroll.setWidget(self.group_container)
        left_layout.addWidget(scroll, 1)
        self.create_group_buttons()

        # ========== 右侧面板：快捷登录 + 日志 ==========
        right_panel = QFrame(self)
        right_panel.setObjectName("panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(10)

        quick_title = StrongBodyLabel("快捷登录", right_panel)
        right_layout.addWidget(quick_title)

        # 分组选择
        group_select_layout = QHBoxLayout()
        group_select_layout.setSpacing(8)
        group_select_layout.addWidget(QLabel("分组:", right_panel))
        self.group_combo = QComboBox()
        self.group_combo.addItems(["全部"] + sorted(device_store.get_groups().keys()))
        self.group_combo.currentTextChanged.connect(self.on_group_selected)
        group_select_layout.addWidget(self.group_combo, 1)
        right_layout.addLayout(group_select_layout)

        # 搜索输入
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 IP 或设备名...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        search_layout.addWidget(self.search_input, 1)
        self.filter_btn = PushButton("搜索")
        self.filter_btn.setMaximumWidth(72)
        self.filter_btn.clicked.connect(self.on_search_clicked)
        search_layout.addWidget(self.filter_btn)
        right_layout.addLayout(search_layout)

        # ---------- 设备列表区 ----------
        device_section = QWidget()
        device_section_layout = QVBoxLayout(device_section)
        device_section_layout.setContentsMargins(0, 0, 0, 0)
        device_section_layout.setSpacing(8)

        device_head = QHBoxLayout()
        device_head.addWidget(StrongBodyLabel("设备列表", device_section))
        device_head.addStretch()
        device_head.addWidget(CaptionLabel("双击设备可直接登录", device_section))
        device_section_layout.addLayout(device_head)

        self.device_list = QListWidget()
        self.device_list.setItemDelegate(DeviceItemDelegate(self.device_list))
        self.device_list.setUniformItemSizes(False)
        self.device_list.setWordWrap(False)
        self.device_list.setSpacing(0)
        self.device_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.device_list.setMinimumHeight(120)
        self.device_list.itemDoubleClicked.connect(self.on_device_double_clicked)
        device_section_layout.addWidget(self.device_list, 1)

        # 登录按钮
        self.quick_login_btn = PrimaryPushButton("登录选中设备")
        self.quick_login_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.quick_login_btn.clicked.connect(self.on_quick_login)
        device_section_layout.addWidget(self.quick_login_btn)

        # ---------- 日志区 ----------
        log_section = QWidget()
        log_section_layout = QVBoxLayout(log_section)
        log_section_layout.setContentsMargins(0, 0, 0, 0)
        log_section_layout.setSpacing(8)

        log_head = QHBoxLayout()
        log_head.setSpacing(8)
        log_head.addWidget(StrongBodyLabel("登录日志", log_section))
        log_head.addStretch()
        self.log_count_label = CaptionLabel("", log_section)
        log_head.addWidget(self.log_count_label)
        self.clear_log_btn = ToolPushButton("清除日志", log_section)
        self.clear_log_btn.clicked.connect(self.on_clear_log)
        log_head.addWidget(self.clear_log_btn)
        log_section_layout.addLayout(log_head)

        self.log_text = QListWidget()
        self.log_text.setItemDelegate(LogItemDelegate(self.log_text))
        self.log_text.setMinimumHeight(150)
        self.log_text.setWordWrap(True)
        self.log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_section_layout.addWidget(self.log_text, 1)

        # 设备列表与日志区可用分隔条调整高度
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(device_section)
        right_splitter.addWidget(log_section)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setChildrenCollapsible(False)
        right_layout.addWidget(right_splitter, 1)

        self.update_device_list("全部")
        self.load_logs()

        # ========== 底部：运行状态 + 全局操作 ==========
        footer = QFrame(self)
        footer.setObjectName("footerBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 10, 18, 10)
        footer_layout.setSpacing(12)

        # 底部内容整体居中：两侧使用对称的伸缩空间，
        # 中间是「状态文字 / 进度条 + 浏览器控制按钮」的紧凑组合，
        # 避免进度条被拉伸后把按钮远远推到窗口两侧。
        footer_layout.addStretch(1)

        footer_content = QHBoxLayout()
        footer_content.setSpacing(14)

        # ---- 状态区：状态文字 + 进度条 ----
        status_group = QWidget(footer)
        status_box = QVBoxLayout(status_group)
        status_box.setSpacing(4)
        status_box.setContentsMargins(0, 0, 0, 0)
        self.progress_label = BodyLabel("", status_group)
        self.progress_label.setObjectName("progressText")
        # 状态文字过长时换行显示，而不是被截断
        self.progress_label.setWordWrap(True)
        status_box.addWidget(self.progress_label)

        self.progress_bar = ProgressBar(status_group)
        self.progress_bar.setRange(0, 100)
        # 进度条保持可识别的宽度，又不至于把右侧按钮推得太远
        self.progress_bar.setMinimumWidth(220)
        self.progress_bar.setMaximumWidth(420)
        self.progress_bar.hide()
        status_box.addWidget(self.progress_bar)

        # 状态区宽度上限：保证整体在窗口中紧凑、居中
        status_group.setMaximumWidth(460)
        footer_content.addWidget(status_group, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- 浏览器控制区：按钮紧邻成组，行为保持不变 ----
        buttons_box = QHBoxLayout()
        buttons_box.setSpacing(8)
        buttons_box.setContentsMargins(0, 0, 0, 0)

        self.close_browsers_btn = PushButton("关闭所有浏览器", footer)
        self.close_browsers_btn.clicked.connect(self.on_close_all_browsers)
        buttons_box.addWidget(self.close_browsers_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.exit_btn = PrimaryPushButton("关闭浏览器并退出", footer)
        self.exit_btn.clicked.connect(self.on_exit)
        buttons_box.addWidget(self.exit_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        footer_content.addLayout(buttons_box, 0)

        footer_layout.addLayout(footer_content, 0)
        footer_layout.addStretch(1)

        # ========== 主体区域（左右可拖动调整） ==========
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 3)
        splitter.setChildrenCollapsible(False)
        left_panel.setMinimumWidth(360)
        right_panel.setMinimumWidth(340)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(0)
        body_layout.addWidget(splitter)

        # ========== 主布局 ==========
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(header)
        main_layout.addWidget(body, 1)
        main_layout.addWidget(footer)

        central_widget = QWidget()
        central_widget.setObjectName("mainInterface")
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # 底部状态栏
        self.setup_status_bar()

        # 创建菜单栏
        self.create_menu_bar()

    def setup_status_bar(self):
        """底部状态栏：当前状态、浏览器会话数与版本号"""
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self.status_label = QLabel("就绪")
        bar.addWidget(self.status_label)
        self.session_label = QLabel("")
        bar.addPermanentWidget(self.session_label)
        self._refresh_status()

    def _refresh_status(self, message=None):
        """刷新状态栏内容（运行状态 + 浏览器会话数）"""
        if message is not None and self.status_label is not None:
            self.status_label.setText(message)
        if self.session_label is None:
            return
        try:
            count = BrowserManager.session_count()
        except Exception:
            count = 0
        self.session_label.setText(f"浏览器会话：{count}　|　V{APP_VERSION}")

    def create_menu_bar(self):
        """创建菜单栏"""
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)

        # 文件菜单
        file_menu = QMenu("文件", self)
        menu_bar.addMenu(file_menu)

        create_template_action = QAction("创建Excel模板", self)
        create_template_action.triggered.connect(self.on_create_template)
        file_menu.addAction(create_template_action)

        import_action = QAction("从Excel导入", self)
        import_action.triggered.connect(self.on_import_excel)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.on_exit)
        file_menu.addAction(exit_action)

        # 工具菜单
        tool_menu = QMenu("工具", self)
        menu_bar.addMenu(tool_menu)
        refresh_action = QAction("刷新配置", self)
        refresh_action.triggered.connect(self.on_refresh)
        tool_menu.addAction(refresh_action)

        close_action = QAction("关闭所有浏览器", self)
        close_action.triggered.connect(self.on_close_all_browsers)
        tool_menu.addAction(close_action)

        tool_menu.addSeparator()

        generate_template_action = QAction("生成登录模板（不登录）", self)
        generate_template_action.triggered.connect(self.on_generate_template)
        tool_menu.addAction(generate_template_action)

        save_template_action = QAction("保存登录模板", self)
        save_template_action.triggered.connect(self.on_save_template)
        tool_menu.addAction(save_template_action)

        manage_templates_action = QAction("管理模板文件", self)
        manage_templates_action.triggered.connect(self.on_manage_templates)
        tool_menu.addAction(manage_templates_action)

        tool_menu.addSeparator()

        # 默认模板维护：三种语义严格区分，不允许把「追加」做成「覆盖」
        #   追加 -> 只增加新选择器，默认模板原有内容一个都不动；
        #   合并 -> 与指定模板取并集（去重），默认模板原有内容一个都不动；
        #   替换 -> 整体覆盖，必须由用户明确确认。
        default_template_menu = QMenu("默认模板", self)
        tool_menu.addMenu(default_template_menu)

        append_default_action = QAction("追加当前选择器到默认模板", self)
        append_default_action.triggered.connect(self.on_append_to_default_template)
        default_template_menu.addAction(append_default_action)

        merge_default_action = QAction("合并指定模板到默认模板...", self)
        merge_default_action.triggered.connect(self.on_merge_into_default_template)
        default_template_menu.addAction(merge_default_action)

        replace_default_action = QAction("用内置版本替换默认模板...", self)
        replace_default_action.triggered.connect(self.on_replace_default_template)
        default_template_menu.addAction(replace_default_action)

        # 窗口菜单
        window_menu = QMenu("窗口", self)
        menu_bar.addMenu(window_menu)

        maximize_action = QAction("浏览器窗口最大化 / 还原", self)
        maximize_action.triggered.connect(self.on_toggle_browser_window)
        window_menu.addAction(maximize_action)

        # 帮助菜单
        help_menu = QMenu("帮助", self)
        menu_bar.addMenu(help_menu)
        help_action = QAction("使用说明", self)
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ============ 列表与筛选 ============
    def on_group_selected(self, text):
        """分组选择改变"""
        self.update_device_list(text)

    def on_search_text_changed(self, text):
        """搜索框文本改变时过滤设备列表"""
        search_text = text.strip().lower()
        group_filter = self.group_combo.currentText()
        self.update_device_list(group_filter, search_text)

    def on_search_clicked(self):
        """搜索按钮点击"""
        search_text = self.search_input.text().strip().lower()
        group_filter = self.group_combo.currentText()
        self.update_device_list(group_filter, search_text)

    def update_device_list(self, group_filter, search_text=None):
        """更新设备列表"""
        if search_text is None:
            search_text = self.search_input.text().strip().lower()

        self.device_list.clear()
        groups = device_store.get_groups()

        if group_filter == "全部":
            devices_to_show = []
            for dev_list in groups.values():
                devices_to_show.extend(dev_list)
        else:
            devices_to_show = groups.get(group_filter, [])

        for device in devices_to_show:
            name = device.get("name", "")
            url = device.get("url", "")

            # 搜索过滤
            if search_text and (search_text not in name.lower() and search_text not in url.lower()):
                continue

            item_text = f"{name} ({url})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, device)
            self.device_list.addItem(item)

    # ============ 日志 ============
    def on_clear_log(self):
        """清除日志"""
        log_db.clear_logs()
        self.log_text.clear()

    def add_log(self, message, device_name="", url="", success=True, record_db=True):
        """添加日志

        record_db=False 时只输出到界面，不写入登录日志数据库
        （用于“登录中”等过程性提示）。
        """
        if record_db:
            status = "成功" if success else "失败"
            log_db.add_log(device_name, url, status, message)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        item = QListWidgetItem(log_entry)

        level = self._log_level(message, success)
        item.setData(ROLE_LOG_LEVEL, level)
        item.setForeground(QColor(_LOG_LEVEL_COLORS.get(level, TEXT_PRIMARY)))

        self.log_text.addItem(item)
        self.log_text.scrollToBottom()
        self._update_log_count()

    @staticmethod
    def _log_level(message, success=True):
        """按消息内容与执行结果判定日志级别（info/success/warning/error）"""
        if "验证码" in message or "警告" in message.lower():
            return "warning"
        if not success or "✗" in message or "失败" in message or "错误" in message:
            return "error"
        if "✓" in message or "成功" in message or "完成" in message:
            return "success"
        return "info"

    def _update_log_count(self):
        """更新日志条数显示"""
        if getattr(self, "log_count_label", None) is not None:
            self.log_count_label.setText(f"共 {self.log_text.count()} 条")

    def load_logs(self):
        """加载历史日志"""
        self.log_text.clear()
        logs = log_db.get_recent_logs(50)
        for timestamp, device_name, status, message in reversed(logs):
            log_entry = f"[{timestamp.split(' ')[1]}] {message}"
            item = QListWidgetItem(log_entry)
            level = "error" if status == "失败" else "info"
            item.setData(ROLE_LOG_LEVEL, level)
            item.setForeground(QColor(_LOG_LEVEL_COLORS.get(level, TEXT_PRIMARY)))
            self.log_text.addItem(item)
        self._update_log_count()

    # ============ 快捷登录 ============
    def on_quick_login(self):
        """快捷登录 - 使用线程池执行"""
        selected_items = self.device_list.selectedItems()
        if not selected_items:
            self.progress_label.setText("请先选择要登录的设备")
            return

        device = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if not device:
            self.progress_label.setText("设备信息无效")
            return

        name = device.get("name", "未知设备")
        url = device.get("url", "")
        # 凭据按需解密（devices.json 中为密文，登录时才解密并缓存）
        username, password = device_store.get_device_credentials(device)

        self.progress_label.setText(f"正在登录 {name}...")
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.add_log(f"开始登录: {name}", name, url)

        task = QuickLoginTask(name, url, username, password,
                              device.get("template", "") or "")
        task.signals.quick_finished.connect(self._on_quick_login_finished)
        self.thread_pool.start(task)

    @pyqtSlot(bool, str, object, str)
    def _on_quick_login_finished(self, success, message, recorded, template_name=''):
        """快捷登录完成（主线程）"""
        self.progress_bar.setValue(100)
        self.progress_label.setText(message)
        name = message.split(":")[0].replace("✓ ", "").replace("✗ ", "")

        # 按统一规则判断是否需要提示保存模板（已有模板时不再重复提示）
        # 注意：验证码页面的登录未完成，但模板已成功生成，同样需要提示保存；
        # 失败路径的 recorded 为 None，因此这里不受 success 影响。
        if recorded and any(recorded.values()):
            self._maybe_save_template(recorded, name, template_name)
        self.add_log(message, name, self._find_device_url(name), success)

    def on_device_double_clicked(self, item):
        """双击设备列表项登录"""
        device = item.data(Qt.ItemDataRole.UserRole)
        if device:
            self.on_quick_login()

    # ============ 分组登录 ============
    def _current_group_columns(self):
        """按当前可用宽度计算分组卡片每行数量（1 ~ GROUP_COLUMNS_MAX 列）。

        宽度足够时返回最大列数（4 列）；窗口变窄时自动减少列数，
        保证卡片不会被压得过窄而导致标题或按钮裁切。

        注意：必须使用滚动区域的「视口宽度」，而不是容器自身的宽度。
        容器位于 setWidgetResizable(True) 的滚动区中，其宽度会被自身最小
        尺寸（= 卡片数 × 卡片最小宽度）撑大；若拿容器宽度反推列数，会形成
        「列数越多 → 容器越宽 → 列数更多」的自反馈死循环，
        结果是窗口变窄时列数不减少、卡片还被裁切。
        """
        width = 0
        scroll = getattr(self, 'group_scroll', None)
        if scroll is not None:
            try:
                width = scroll.viewport().width()
            except Exception:
                width = 0
        if width <= 0:
            container = getattr(self, 'group_container', None)
            if container is not None:
                try:
                    width = container.width()
                except Exception:
                    width = 0
        if width <= 0:
            return GROUP_COLUMNS_MAX

        # 预留滚动条与边距
        usable = width - 6
        cols = int((usable + GROUP_CARD_SPACING)
                   // (GROUP_CARD_MIN_WIDTH + GROUP_CARD_SPACING))
        return max(1, min(GROUP_COLUMNS_MAX, cols))

    def _relayout_groups_if_needed(self):
        """可用宽度变化导致列数变化时，重新排列分组卡片。"""
        if getattr(self, 'group_container', None) is None:
            return
        if getattr(self, '_relayouting', False):
            return
        cols = self._current_group_columns()
        if cols == getattr(self, '_group_columns', None):
            return
        self._relayouting = True
        try:
            self.create_group_buttons()
        finally:
            self._relayouting = False

    def eventFilter(self, obj, event):
        """分组区域视口尺寸变化时重新排列卡片。

        监听视口而不是窗口，这样拖动左右分隔条改变左面板宽度时，
        分组列数同样会自适应（仅监听窗口 resize 会在拖动分隔条时失效）。
        """
        viewport = getattr(self, 'group_scroll', None)
        if viewport is not None and obj is viewport.viewport():
            if event.type() == QEvent.Type.Resize:
                self._relayout_groups_if_needed()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_groups_if_needed()

    def create_group_buttons(self):
        """创建分组卡片（按可用宽度决定每行列数，双击登录该组全部设备）"""
        # 清除旧按钮
        while self.group_layout.count():
            item = self.group_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _clear_layout(item.layout())

        max_cols = self._current_group_columns()
        self._group_columns = max_cols

        # 重排期间关闭更新，避免新旧卡片交替显示
        self.group_container.setUpdatesEnabled(False)
        try:
            self._build_group_cards(max_cols)
        finally:
            self.group_container.setUpdatesEnabled(True)

    def _build_group_cards(self, max_cols):
        """按指定列数生成分组卡片（由 create_group_buttons 调用）"""
        row_layout = None
        col = 0

        for g_name, dev_list in sorted(device_store.get_groups().items()):
            if col == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(GROUP_CARD_SPACING)
                self.group_layout.addLayout(row_layout)

            count = len(dev_list)
            btn_text = f"{g_name}\n({count}台)"

            btn = DoubleClickButton(btn_text)  # 使用支持双击的按钮
            btn.setMinimumWidth(GROUP_CARD_MIN_WIDTH)
            btn.setMinimumHeight(62)
            btn.setMaximumWidth(GROUP_CARD_MAX_WIDTH)
            btn.setProperty("group_name", g_name)
            # 使用默认参数捕获当前 g_name 的值
            btn.doubleClicked.connect(lambda gn=g_name: self.on_login_click(gn))

            row_layout.addWidget(btn, 1)
            col += 1

            if col >= max_cols:
                col = 0

        # 填充空白（最后一行不足时用占位块补齐，保持卡片对齐）
        if col > 0 and row_layout is not None:
            for _ in range(max_cols - col):
                spacer = QWidget()
                spacer.setFixedHeight(62)
                spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                row_layout.addWidget(spacer, 1)

    def adjust_size(self):
        """调整窗口大小（按 4 列布局规则估算）"""
        group_count = len(device_store.get_groups())
        if group_count == 0:
            self.resize(1080, 700)
        elif group_count <= GROUP_COLUMNS_MAX:
            # 4 列分组卡片需要足够的横向空间，默认宽度保证一行可放下 4 个
            self.resize(1240, 720)
        elif group_count <= GROUP_COLUMNS_MAX * 3:
            self.resize(1280, 780)
        else:
            rows = (group_count + GROUP_COLUMNS_MAX - 1) // GROUP_COLUMNS_MAX
            height = 560 + rows * 82
            self.resize(1280, min(height, 900))

    def on_login_click(self, group_name):
        """分组登录按钮双击 - 使用线程池"""
        self.progress_label.setText(f"正在登录 {group_name}...")
        self.progress_bar.show()
        self.progress_bar.setValue(0)

        task = GroupLoginTask(group_name)
        task.signals.finished.connect(self._on_progress_updated)
        task.signals.template_recorded.connect(self._on_template_recorded)
        self.thread_pool.start(task)

    @pyqtSlot(str, object, str)
    def _on_template_recorded(self, device_name, recorded, template_name=''):
        """分组登录后录制的模板回调（带设备名与该设备配置的模板名）"""
        self._maybe_save_template(recorded, device_name, template_name)

    def _find_device_url(self, name):
        """按设备名在当前设备列表中查找对应的 URL"""
        if not name:
            return ""
        for devices in device_store.get_groups().values():
            for device in devices:
                if device.get("name") == name:
                    return device.get("url", "")
        return ""

    @pyqtSlot(str, int, int)
    def _on_progress_updated(self, msg, current, total):
        """进度更新信号处理（主线程）"""
        if total > 0:
            value = int(current / total * 100)
            self.progress_bar.setValue(value)
        else:
            self.progress_bar.setValue(100)

        if msg.startswith("登录: "):
            # 过程性提示（正在登录某台设备），不写入数据库
            self.add_log(msg, record_db=False)
        else:
            device_name = msg.lstrip("✓✗ ").split(":")[0].strip()
            url = self._find_device_url(device_name)
            if url:
                # 单台设备的结果行：状态由前缀决定
                success = not msg.startswith("✗")
                self.add_log(msg, device_name, url, success)
            else:
                # 分组汇总行：与原项目一致，按汇总标记记录整体状态
                success = msg.startswith("✓")
                self.add_log(msg, device_name, "", success)
        self.progress_label.setText(msg)
        self._refresh_status()

    @pyqtSlot(str, int, int)
    def update_progress(self, msg, current, total):
        """更新进度"""
        value = int(current / total * 100)
        self.progress_bar.setValue(value)
        self.progress_label.setText(msg)

    # ============ 浏览器关闭与退出 ============
    def on_close_all_browsers(self):
        """关闭所有浏览器 - 使用线程池"""
        count = BrowserManager.session_count()
        if count == 0:
            self.progress_label.setText("没有打开的浏览器")
            return

        self.progress_label.setText(f"正在关闭 {count} 个浏览器...")
        self.add_log(f"关闭 {count} 个浏览器")

        def callback(closed, total):
            self.progress_label.setText(
                f"已关闭 {closed}/{total} 个浏览器" if closed < total else f"已关闭 {closed} 个浏览器"
            )
            self._refresh_status(f"已关闭 {closed} 个浏览器")

        task = CloseBrowsersTask(callback)
        self.thread_pool.start(task)

    # ============ 浏览器窗口 ============
    def on_toggle_browser_window(self):
        """浏览器窗口最大化 / 还原

        使用 Chromium 的普通最大化（不是 F11 全屏），随时可以还原退出；
        每个浏览器会话独立处理，不会影响其它实例。
        """
        count = BrowserManager.session_count()
        if count == 0:
            self.progress_label.setText("没有打开的浏览器")
            return

        # 以第一个会话的当前状态决定本次动作：已最大化 -> 还原，否则最大化
        state = 'maximized'
        for name in BrowserManager.session_names():
            session = BrowserManager.get(name)
            if session is not None:
                state = 'normal' if session.window_state == 'maximized' else 'maximized'
                break

        label = "最大化" if state == 'maximized' else "还原"
        self.progress_label.setText(f"正在{label}浏览器窗口...")

        def callback(ok, total, message):
            if total <= 0:
                self.progress_label.setText("没有打开的浏览器")
                return
            self.progress_label.setText(f"已{label} {ok}/{total} 个浏览器窗口")
            self._refresh_status(f"已{label} {ok}/{total} 个浏览器窗口")
            if message and ok < total:
                InfoBar.warning(
                    title="提示",
                    content=f"部分窗口未能{label}：{message}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=self
                )

        task = BrowserWindowTask(state, callback)
        self.thread_pool.start(task)

    # ============ 生成登录模板（不登录）============
    def on_generate_template(self):
        """为选中的设备生成登录模板（只识别，不填写、不点击、不提交登录）

        适用于带图片验证码的登录页面：先把用户名/密码/验证码输入框的选择器
        识别出来并保存为模板，之后再使用该模板正常登录。
        """
        selected_items = self.device_list.selectedItems()
        if not selected_items:
            self.progress_label.setText("请先选择要生成模板的设备")
            return

        device = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if not device:
            self.progress_label.setText("设备信息无效")
            return

        name = device.get("name", "未知设备")
        url = device.get("url", "")
        if not url:
            self.progress_label.setText("该设备没有配置登录地址")
            return

        self.progress_label.setText(f"正在为 {name} 生成登录模板（不提交登录）...")
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.add_log(f"开始生成登录模板（不提交登录）: {name}", name, url)

        task = GenerateTemplateTask(name, url, device.get("template", "") or "")
        task.signals.quick_finished.connect(self._on_generate_template_finished)
        self.thread_pool.start(task)

    @pyqtSlot(bool, str, object, str)
    def _on_generate_template_finished(self, success, message, recorded, template_name=''):
        """模板生成完成（主线程）"""
        self.progress_bar.setValue(100)
        self.progress_label.setText(message)
        name = message.split(":")[0].replace("✓ ", "").replace("✗ ", "")

        if success and recorded and any(recorded.values()):
            # 用户主动触发生成模板：必须提供保存入口（force=True）
            self._maybe_save_template(recorded, name, template_name, force=True)
        self.add_log(message, name, self._find_device_url(name), success)

    def on_exit(self):
        """退出程序"""
        if self._exiting:
            return
        self._exiting = True
        self.progress_label.setText("正在关闭浏览器并退出...")
        # 交回事件循环后再执行阻塞清理，保证界面不会在关闭过程中无响应
        QTimer.singleShot(0, self._shutdown_and_quit)

    def _shutdown_and_quit(self):
        """关闭浏览器、停止自动化线程后退出程序"""
        try:
            self.thread_pool.waitForDone(3000)
        except Exception:
            pass
        # Excel 导入若正在进行，等它写完再退出：
        # 写盘采用「临时文件 + 原子替换」，提前退出最多留下一个临时文件；
        # 等它完成则能保证设备配置与界面提示一致。
        if getattr(self, '_excel_importing', False):
            try:
                self.thread_pool.waitForDone(30000)
            except Exception:
                pass

        try:
            loop = get_loop()
            loop.shutdown(cleanup_coro=_cleanup_browsers(), timeout=25)
        except Exception as e:
            log_exception(e, "退出清理")

        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.on_exit()
        event.accept()

    # ============ 刷新 ============
    def _required_template_names(self, groups):
        """收集当前设备实际引用的模板名（默认模板始终在内）"""
        names = {'default'}
        for devices in (groups or {}).values():
            for device in devices:
                if not isinstance(device, dict):
                    continue
                template = str(device.get('template', '') or '').strip()
                if template:
                    names.add(template[:-5] if template.lower().endswith('.json')
                              else template)
        return names

    def on_refresh(self):
        """刷新配置：真正重新读取磁盘上的设备配置与模板文件。

        流程（先校验、后切换，绝不先清空再加载）：
        1. 备份当前有效配置（模板注册表 + 设备分组）；
        2. 重新读取磁盘：templates/*.json 与 devices.json；
        3. 校验不通过（JSON 语法错误 / 模板结构无效 / 设备配置损坏）
           -> 回滚到最后一次有效配置，提示具体文件与原因，允许修好后再次刷新；
        4. 全部通过 -> 切换到新配置，并重建设备列表与分组 UI。

        生效范围：只影响刷新之后发起的登录任务。正在执行的登录任务
        继续使用它启动时已解析好的模板与凭据，不会被中途改变。
        """
        started = time.monotonic()
        self.show_loading_state()

        # 备份最后一次有效配置（刷新失败时回滚用）
        template_snapshot = TemplateManager.snapshot_templates()
        old_groups = device_store.get_groups()

        # ---- 1) 重新加载模板（重新读磁盘上的 templates/*.json）----
        TemplateManager.reload_templates()
        template_errors = TemplateManager.get_load_errors()

        # ---- 2) 重新读取设备配置（重新读磁盘上的 devices.json）----
        new_groups = None
        device_error = ''
        try:
            new_groups = device_store.load_devices()
        except Exception as e:
            device_error = f'设备配置读取失败（{CONFIG_FILE}）：{e}'

        # ---- 3) 关键模板是否可用（默认模板 + 设备实际引用的模板）----
        broken = []
        for name in sorted(self._required_template_names(
                new_groups if new_groups is not None else old_groups)):
            state = TemplateManager.inspect_template(name)
            if state['loadable']:
                continue
            # 模板文件不存在（设备配置写错了名字）不算损坏，只提示
            if state['error_type'] == 'missing':
                Logger.warning(
                    f"刷新配置：模板 '{name}' 在模板目录中不存在"
                    f"（{state['reason']}）")
                continue
            broken.append(f"模板 {state['path'] or name}：{state['reason']}")

        # ---- 4) 校验不通过 -> 保留最后一次有效配置 ----
        if device_error or broken:
            TemplateManager.restore_templates(template_snapshot)
            problems = ([device_error] if device_error else []) + broken
            message = '刷新失败，已保留上一次有效配置：\n' + '\n'.join(problems)
            Logger.error(f"刷新配置失败：{'；'.join(problems)}")
            self._show_refresh_error(problems)
            return

        # ---- 5) 校验通过 -> 切换到新配置 ----
        device_store.set_groups(new_groups or {})
        self.devices_loaded = True

        total = sum(len(d) for d in (new_groups or {}).values())
        self.stat_label.setText(f"共 {len(new_groups or {})} 个分组，{total} 台设备")

        # 更新分组下拉框
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(["全部"] + sorted((new_groups or {}).keys()))
        self.group_combo.blockSignals(False)

        self.group_container.setEnabled(True)
        self.create_group_buttons()
        self.update_device_list(self.group_combo.currentText())

        self.progress_label.setText("")
        self.progress_bar.hide()
        elapsed = int((time.monotonic() - started) * 1000)
        text = f"✓ 已刷新：{len(new_groups or {})} 个分组，{total} 台设备"
        self.stat_label.setText(text)
        self._refresh_status(f"{text}（耗时 {elapsed}ms，模板与设备配置均已重新读取）")
        Logger.info(f"刷新配置完成：{len(new_groups or {})} 个分组，{total} 台设备，"
                    f"模板 {len(TemplateManager.list_templates())} 个，耗时={elapsed}ms")
        if template_errors:
            Logger.warning(f"刷新时发现 {len(template_errors)} 个模板文件存在问题："
                           f"{'；'.join(template_errors)}")

    def _show_refresh_error(self, problems):
        """刷新失败提示：说明具体文件与原因，并保留现有数据"""
        detail = '\n'.join(f'• {item}' for item in problems)
        self.stat_label.setText("✗ 刷新失败（已保留上一次有效配置）")
        self.group_container.setEnabled(True)
        self.progress_label.setText("")
        self.progress_bar.hide()
        self._refresh_status(f"刷新失败：{detail}")
        InfoBar.error(
            title="刷新配置失败",
            content=f"以下问题导致刷新未生效，已保留上一次有效配置：\n{detail}\n\n"
                    f"请修复文件后再次点击「刷新配置」。",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=8000,
            parent=self
        )

    # ============ 模板管理 ============
    def _maybe_save_template(self, recorded, device_name, template_name='', force=False):
        """按统一规则判断本次登录是否需要提示保存模板。

        所有登录入口（普通登录 / 快捷登录 / 分组批量登录）都调用本方法，
        判断规则完全一致（appcore.templates.evaluate_save_template_request）：
        - 设备已配置可用模板          -> 直接使用，不提示新建；
        - 设备配置的模板文件存在但损坏 -> 记录具体原因，不提示新建、不覆盖用户文件；
        - 设备配置的模板确实不存在     -> 允许提示保存新模板；
        - 未指定模板且现有模板已覆盖本次选择器 -> 不提示。

        force=True 用于用户主动触发的「生成登录模板」动作：
        此时即使设备已配置可用模板，也提供「更新该模板」的入口，
        但仍然不会覆盖已损坏的用户模板文件。
        """
        if not recorded or not any(recorded.values()):
            return False

        decision = evaluate_save_template_request(template_name, recorded, device_name)
        if not decision['need_prompt'] and not force:
            Logger.info(
                f"模板保存提示跳过：设备={device_name} "
                f"配置模板={template_name or '(未指定)'} 原因={decision['reason']}")
            return False

        Logger.info(
            f"提示保存模板：设备={device_name} 目标模板={decision['target_name']} "
            f"模式={decision['mode']} 原因={decision['reason']}"
            f"{'（用户主动生成模板）' if force else ''}")
        self._show_save_template_dialog(recorded, device_name, template_name, force=force)
        return True

    def _show_save_template_dialog(self, recorded, device_name, template_name='',
                                   force=False):
        """显示保存/更新模板对话框。

        是否需要弹窗由 _maybe_save_template 统一判断（各入口规则一致）；
        本方法只负责交互：新建模板 或 覆盖确认后更新已有模板。

        force=True（用户主动执行「生成登录模板」）：设备已配置可用模板时，
        给出「更新该模板」入口；模板文件已损坏时仍不覆盖用户文件。
        """
        if not recorded or not any(recorded.values()):
            return

        decision = evaluate_save_template_request(template_name, recorded, device_name)
        target_name = decision['target_name']
        mode = decision['mode']

        if not decision['need_prompt']:
            if not force:
                # 理论上不会走到这里（入口已判断），保留防御性处理
                Logger.info(
                    f"模板保存提示跳过：设备={device_name} "
                    f"配置模板={template_name or '(未指定)'} 原因={decision['reason']}")
                return
            state = decision.get('state') or {}
            if state.get('loadable'):
                mode = 'update'
                target_name = state.get('name') or target_name
            elif state.get('exists'):
                # 模板文件存在但损坏：为避免覆盖用户文件，仍然不提示保存
                Logger.info(
                    f"模板保存提示跳过：设备={device_name} "
                    f"配置模板={template_name or '(未指定)'} 原因={decision['reason']}")
                return
            else:
                mode = 'create'
                target_name = target_name or suggest_template_name(device_name)

        if mode == 'update':
            # 已有模板需要更新 -> 明确的覆盖确认（用户取消则不修改磁盘文件）
            w = MessageBox(
                "更新登录模板",
                f"模板 '{target_name}' 已存在。\n\n"
                f"是否用本次登录记录的选择器更新该模板？\n"
                f"（确认后会覆盖模板文件中的选择器）",
                self
            )
            w.yesButton.setText("更新")
            w.cancelButton.setText("取消")
            if not w.exec():
                Logger.info(f"用户取消更新模板 '{target_name}'，模板文件未修改")
                TemplateManager.set_last_recorded(recorded)
                return
            final_name = target_name
        else:
            intro = "已识别出该页面的登录表单（未提交登录）。\n\n" if force else "登录成功！\n\n"
            w = MessageBox(
                "保存登录模板",
                f"{intro}检测到新的登录选择器，是否保存为模板？\n\n"
                f"这可以帮助同类型设备更快登录。",
                self
            )
            if not w.exec():
                Logger.info("用户取消保存模板，模板文件未修改")
                TemplateManager.set_last_recorded(recorded)
                return

            template_name_input, ok = QInputDialog.getText(
                self,
                "保存登录模板",
                f"请输入模板名称:",
                text=target_name
            )
            if not ok or not template_name_input.strip():
                Logger.info("用户未输入模板名称，模板文件未修改")
                TemplateManager.set_last_recorded(recorded)
                return
            final_name = template_name_input.strip()
            if not self._confirm_overwrite_template(final_name):
                Logger.info(f"用户取消覆盖模板 '{final_name}'，模板文件未修改")
                return

        TemplateManager.set_last_recorded(recorded)
        if TemplateManager.save_recorded_template(final_name):
            InfoBar.success(
                title="模板已保存",
                content=f"模板 '{final_name}' 已保存！\n下次登录同类型设备时可使用。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        else:
            InfoBar.error(
                title="保存失败",
                content=f"模板 '{final_name}' 保存失败，请查看日志了解具体原因。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )

    def _confirm_overwrite_template(self, template_name):
        """同名模板已存在时要求用户确认覆盖"""
        if not TemplateManager.template_exists(template_name):
            return True

        w = MessageBox(
            "模板已存在",
            f"模板 '{template_name}' 已存在。\n\n继续保存将覆盖原有模板文件，是否继续？",
            self
        )
        w.yesButton.setText("覆盖")
        w.cancelButton.setText("取消")
        return bool(w.exec())

    def on_save_template(self):
        """保存登录模板 - 打开对话框让用户输入模板名称"""
        recorded = TemplateManager.get_last_recorded()

        if not recorded or not any(recorded.values()):
            InfoBar.warning(
                title="提示",
                content="还没有录制的选择器，请先完成一次成功登录",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        template_name, ok = QInputDialog.getText(
            self,
            "保存登录模板",
            "请输入模板名称（如: proxmox, huawei, pfsense）:\n（同名模板会被覆盖）",
        )

        if ok and template_name.strip():
            template_name = template_name.strip()
            if not self._confirm_overwrite_template(template_name):
                return
            TemplateManager.set_last_recorded(recorded)
            if TemplateManager.save_recorded_template(template_name):
                InfoBar.success(
                    title="完成",
                    content=f"模板 '{template_name}' 已保存到:\n{os.path.join(TEMPLATE_DIR, template_name + '.json')}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
            else:
                InfoBar.error(
                    title="错误",
                    content="保存模板失败，请查看日志了解具体原因",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )

    # ============ 默认模板维护（追加 / 合并 / 整体替换）============
    # 三种操作的语义严格区分：
    #   追加：只写入新选择器，默认模板里已有的选择器一个都不会被删改；
    #   合并：与指定模板取并集（自动去重），默认模板里已有的选择器一个都不会被删改；
    #   替换：整体覆盖默认模板文件，必须先取得用户的明确确认。
    def _show_default_template_result(self, title, ok, message, detail=None):
        """统一展示默认模板操作结果（含新增 / 跳过 / 拒绝明细）"""
        detail = detail or {}
        added = detail.get('added') or {}
        skipped = detail.get('skipped') or {}
        rejected = detail.get('rejected') or {}

        lines = [message]
        if added:
            lines.append("新增：" + "，".join(
                f"{field} {count} 条" for field, count in added.items()))
        if skipped:
            lines.append("已存在（跳过）：" + "，".join(
                f"{field} {count} 条" for field, count in skipped.items()))
        if rejected:
            lines.append("角色冲突未写入：" + "；".join(
                f"{field} -> {', '.join(items)}" for field, items in rejected.items()))
        lines.append(f"默认模板文件：{TemplateManager.get_default_template_path()}")

        if ok:
            InfoBar.success(
                title=title,
                content="\n".join(lines),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )
        else:
            InfoBar.error(
                title=title,
                content="\n".join(lines),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )

    def on_append_to_default_template(self):
        """把当前录制的选择器**追加**到默认模板（已有内容不会被删改）"""
        recorded = TemplateManager.get_last_recorded()
        if not recorded or not any(recorded.values()):
            InfoBar.warning(
                title="提示",
                content="还没有录制的选择器。\n请先完成一次成功登录或执行「生成登录模板」。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        ok, message, detail = TemplateManager.append_selectors_to_default(recorded)
        self._show_default_template_result("追加到默认模板", ok, message, detail)

    def on_merge_into_default_template(self):
        """把指定模板的选择器**合并**进默认模板（取并集，已有内容不会被删改）"""
        templates = TemplateManager.list_templates()
        if not templates:
            InfoBar.warning(
                title="提示",
                content="模板目录中没有可用模板。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
            return

        template_name, ok = QInputDialog.getItem(
            self,
            "合并模板到默认模板",
            "请选择要合并的模板（合并后默认模板原有内容不会被删改）:",
            templates,
            0,
            False
        )
        if not ok or not template_name:
            Logger.info("用户取消合并默认模板，默认模板文件未修改")
            return

        merged, message, detail = TemplateManager.merge_template_into_default(template_name)
        self._show_default_template_result("合并到默认模板", merged, message, detail)

    def on_replace_default_template(self):
        """用内置版本**整体替换**默认模板（必须先取得用户明确确认）"""
        w = MessageBox(
            "替换默认模板",
            "此操作会用内置版本**整体覆盖**默认模板文件。\n\n"
            "默认模板中现有的人工修改（含追加的选择器）将全部丢失。\n"
            "确定要继续吗？",
            self
        )
        w.yesButton.setText("确认替换")
        w.cancelButton.setText("取消")
        if not w.exec():
            Logger.info("用户取消替换默认模板，默认模板文件未修改")
            return

        ok, message = TemplateManager.replace_default_template()
        if ok:
            message = '默认模板已被内置版本整体替换'
        self._show_default_template_result("替换默认模板", ok, message)

    def on_manage_templates(self):
        """管理模板文件 - 重新加载模板并打开模板目录"""
        template_dir = TEMPLATE_DIR
        TemplateManager.ensure_template_dir()

        # 重新加载磁盘上的模板（用户可能手工修改过 JSON）
        TemplateManager.reload_templates()
        templates = TemplateManager.list_templates()
        errors = TemplateManager.get_load_errors()

        if templates:
            template_list = "\n".join([f"  - {t}" for t in templates])
            InfoBar.info(
                title="已加载的模板",
                content=f"模板目录: {template_dir}\n\n{template_list}"
                        + (f"\n\n以下文件存在问题:\n{chr(10).join(errors)}" if errors else ""),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=8000,
                parent=self
            )
        else:
            InfoBar.info(
                title="模板目录",
                content=f"模板目录: {template_dir}\n\n暂无模板文件",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )

        # 打开模板目录
        try:
            os.startfile(template_dir)
        except Exception:
            # 回退方案：以「不弹出控制台窗口」的方式启动资源管理器。
            # GUI 程序里直接 subprocess.Popen 外部程序会闪现黑色命令行窗口，
            # 因此统一复用 encrypt.no_window_kwargs() 的无窗口参数。
            try:
                subprocess.Popen(f'explorer "{template_dir}"', **no_window_kwargs())
            except Exception:
                pass

    # ============ Excel 模板与导入 ============
    def on_create_template(self):
        """创建Excel模板"""
        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment, PatternFill

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "设备列表"
            ws.column_dimensions['A'].width = 15
            ws.column_dimensions['B'].width = 40
            ws.column_dimensions['C'].width = 18
            ws.column_dimensions['D'].width = 22
            ws.column_dimensions['E'].width = 15
            ws.column_dimensions['F'].width = 20

            header_font = Font(bold=True, color="FFFFFF", size=12)
            header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            header_align = Alignment(horizontal="center", vertical="center")

            headers = ["设备名称", "登录地址(URL)", "用户名", "密码", "分组", "模板"]
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

            # 示例行一律使用**虚构的**占位数据（保留地址为 RFC 5737 / RFC 2606
            # 专用测试网段与域名），避免真实凭据随源码或模板文件泄露。
            # 用户拿到模板后直接覆盖这几行即可。
            example_data = [
                ["示例设备A", "http://192.0.2.10:8080/login", "demo_user", "demo_password", "A组-虚拟化", "default"],
                ["示例设备B", "https://example.com/login", "demo_admin", "demo_password", "A组-虚拟化", "proxmox"],
                ["示例设备C", "https://device.example.com/login", "demo_user", "demo_password", "B组-网关设备", "huawei"],
            ]
            for row_idx, row_data in enumerate(example_data, 2):
                for col_idx, value in enumerate(row_data, 1):
                    ws.cell(row=row_idx, column=col_idx, value=value)

            ws.freeze_panes = "A2"

            ws.cell(row=6, column=1, value="=== 使用说明 ===").font = Font(bold=True)
            ws.cell(row=7, column=1, value="1. 在下方表格中填写设备信息")
            ws.cell(row=8, column=1, value="2. 保存后点击'从Excel导入'")
            ws.cell(row=9, column=1, value="3. 用户名密码会自动加密存储")
            ws.cell(row=10, column=1, value="4. 模板列：填写登录页面定位器名称，留空或default使用默认定位器")
            ws.cell(row=11, column=1, value="5. 可在templates目录下创建自定义模板JSON文件")

            wb.save(EXCEL_TEMPLATE_FILE)

            InfoBar.success(
                title="完成",
                content=f"Excel模板已创建:\n{EXCEL_TEMPLATE_FILE}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        except Exception as e:
            InfoBar.error(
                title="错误",
                content=f"创建模板失败:\n{str(e)}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )

    def on_import_excel(self):
        """从 Excel 导入数据。

        导入过程（读文件、解析、校验、加密写盘）全部在**后台线程**执行，
        主线程只负责界面更新：因此导入上百台设备时界面不会未响应
        （历史实现在主线程里做 PBKDF2 加密，100 台设备要卡住约 13 秒）。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择Excel文件",
            APP_DIR,
            "Excel文件 (*.xlsx);;所有文件 (*.*)"
        )
        if not file_path:
            return

        if self._excel_importing:
            InfoBar.warning(
                title="提示",
                content="已有一个 Excel 导入正在进行，请等待它完成",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        self._excel_importing = True
        self._set_excel_import_status("正在导入 Excel 文件...")

        task = ImportExcelTask(file_path)
        task.signals.progress.connect(self._on_excel_import_progress)
        task.signals.finished.connect(self._on_excel_import_finished)
        task.signals.error.connect(self._on_excel_import_failed)
        self.thread_pool.start(task)

    # ---- Excel 导入（后台线程处理数据，界面更新一律回到主线程）----
    def _set_excel_import_status(self, text):
        """更新导入过程中的状态提示（主线程）"""
        self.stat_label.setText(text)
        self.progress_label.setText(text)
        # 不确定进度（忙碌指示）
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self._refresh_status(text)

    def _on_excel_import_progress(self, text):
        """导入阶段进度回调（主线程）"""
        if getattr(self, '_exiting', False):
            return
        self._set_excel_import_status(text)

    def _on_excel_import_finished(self, result):
        """导入完成（主线程）：刷新设备列表并报告结果"""
        self._excel_importing = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.progress_label.setText("")

        if getattr(self, '_exiting', False):
            return

        count = int(result.get('count') or 0)
        errors = result.get('errors') or []
        duplicates = result.get('duplicates') or []
        sheet = result.get('sheet') or ''
        file_name = os.path.basename(result.get('file_path') or '')

        # 刷新设备列表（真正重新读取磁盘上的设备配置）
        self.on_refresh()

        lines = [f"已从 {file_name} 导入 {count} 台设备"]
        if sheet:
            lines.append(f"工作表：{sheet}")
        lines.append("用户名密码已加密存储")
        if errors:
            lines.append(f"跳过 {len(errors)} 行未通过校验：")
            for item in errors[:5]:
                lines.append(f"  第 {item['row']} 行：{item['reason']}")
            if len(errors) > 5:
                lines.append(f"  ...等共 {len(errors)} 行")
        if duplicates:
            lines.append(f"注意：{len(duplicates)} 个登录地址重复（已按原样全部保留）：")
            for item in duplicates[:3]:
                rows = "、".join(str(r) for r in item['rows'])
                lines.append(f"  {item['url']}（第 {rows} 行）")

        content = '\n'.join(lines)
        Logger.info(f"Excel 导入完成：{count} 台设备，"
                    f"跳过 {len(errors)} 行未通过校验，{len(duplicates)} 个重复地址")
        self.stat_label.setText(f"✓ 已导入 {count} 台设备")

        if errors or duplicates:
            InfoBar.warning(
                title="导入完成（有提示）",
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=8000,
                parent=self
            )
        else:
            InfoBar.success(
                title="完成",
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )

    def _on_excel_import_failed(self, message):
        """导入失败（主线程）：恢复界面状态并显示具体原因"""
        self._excel_importing = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.progress_label.setText("")

        if getattr(self, '_exiting', False):
            return

        self.stat_label.setText("✗ 导入失败")
        self._refresh_status(f"导入失败：{message}")
        Logger.error(f"Excel 导入失败：{message}")
        InfoBar.error(
            title="导入失败",
            content=f"{message}\n\n原有设备配置未被修改。",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=8000,
            parent=self
        )

    # ============ 帮助 ============
    def show_help(self):
        """显示帮助"""
        help_text = """【使用说明】

【基本操作】
1. 双击分组按钮登录该组所有设备
2. 浏览器保持打开，可手动操作
3. 点击"关闭浏览器"仅关闭浏览器
4. 点击"关闭并退出"关闭所有并退出

【Excel配置】
1. 点击"创建Excel模板"生成模板
2. 用Excel编辑设备信息
3. 点击"从Excel导入"生成配置文件

【登录模板】
• 模板目录：程序所在目录的 templates\
• 模板为 JSON 纯文本文件，可自行新增/编辑，程序不会覆盖
• 设备配置了模板名时，先用模板定位表单，失效才回退通用识别
• 菜单"工具→管理模板文件"可重新加载模板并打开目录
• 详细说明见 docs/模板维护说明.md

【Playwright配置】
• 首次使用需执行: playwright install chromium
• 浏览器由 Playwright 托管，无需 ChromeDriver
• 浏览器以有头模式运行（headless=False, slow_mo=100）

【注意事项】
• 切换电脑后需重新导入Excel
• 用户名密码已自动加密
• 部分网站需要验证码
• 如登录失败请检查网络"""

        msg = MessageBox("使用说明", help_text, self)
        msg.yesButton.setText("确定")
        msg.cancelButton.hide()
        msg.exec()

    def show_about(self):
        """显示关于"""
        about_text = f"""【关于】

软件名：{APP_NAME}
版本：{APP_VERSION}
作者：Jonathon

功能特点：
• 分组管理设备
• 一键批量登录
• 数据加密存储
• 智能表单识别
• 基于 Playwright 的浏览器自动化
• 可维护的登录模板系统（templates 目录）"""

        msg = MessageBox("关于", about_text, self)
        msg.yesButton.setText("确定")
        msg.cancelButton.hide()
        msg.exec()


async def _cleanup_browsers():
    """退出时清理浏览器与 Playwright 驱动"""
    await BrowserManager.close_all()
    await BrowserService.stop()
