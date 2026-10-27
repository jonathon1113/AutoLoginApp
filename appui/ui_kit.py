"""界面基础组件库（基于 PyQt6 原生控件 + 全局样式表）。

本模块替代原项目使用的 QFluentWidgets，提供主窗口与对话框所需的同等能力：
- 文本标签、按钮、卡片、滚动区、进度条（保留原有类名，调用方无感）
- InfoBar / MessageBox（接口与原用法保持一致，便于测试替身替换）
- 设备列表与日志列表的自绘委托（卡片式排版 + 级别配色）

选择原生控件的原因：
1. 可完全按 design token 控制视觉，不受第三方组件库主题约束；
2. 不再引入 numpy / scipy / Pillow 等重依赖（见 appui/theme.py 顶部说明）；
3. 保持全部原有功能入口与信号槽连接方式不变。
"""

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    BORDER,
    BORDER_LIGHT,
    DANGER,
    DANGER_BORDER,
    DANGER_LIGHT,
    FONT_SIZE_BASE,
    FONT_SIZE_SMALL,
    INFO,
    INFO_LIGHT,
    PRIMARY,
    PRIMARY_BORDER,
    PRIMARY_LIGHT,
    SUCCESS,
    SUCCESS_BORDER,
    SUCCESS_LIGHT,
    TEXT_PLACEHOLDER,
    TEXT_PRIMARY,
    TEXT_REGULAR,
    TEXT_SECONDARY,
    WARNING,
    WARNING_BORDER,
    WARNING_LIGHT,
    base_font,
)

# 日志级别在列表项中保存的位置（UserRole 已被设备信息占用）
ROLE_LOG_LEVEL = Qt.ItemDataRole.UserRole + 1


# ====================================================================
# 基础控件
# ====================================================================
class _ThemedLabel(QLabel):
    """带统一样式标识的标签基类"""

    object_name = ""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        if self.object_name:
            self.setObjectName(self.object_name)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


class TitleLabel(_ThemedLabel):
    """应用主标题"""

    object_name = "appTitle"


class StrongBodyLabel(_ThemedLabel):
    """区块标题"""

    object_name = "sectionTitle"


class BodyLabel(_ThemedLabel):
    """正文标签"""


class CaptionLabel(_ThemedLabel):
    """辅助说明文字"""

    object_name = "sectionHint"


class FieldLabel(_ThemedLabel):
    """表单字段名"""

    object_name = "fieldLabel"


class _ThemedButton(QPushButton):
    """按钮基类：统一光标与尺寸策略（宽度按内容自适应，不被布局拉伸）"""

    object_name = ""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        if self.object_name:
            self.setObjectName(self.object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class PushButton(_ThemedButton):
    """普通（中性）按钮"""

    object_name = "secondaryButton"


class PrimaryPushButton(_ThemedButton):
    """主要操作按钮"""

    object_name = "primaryButton"


class DangerPushButton(_ThemedButton):
    """危险操作按钮"""

    object_name = "dangerButton"


class GhostPushButton(_ThemedButton):
    """头部栏使用的低干扰按钮"""

    object_name = "ghostButton"


class ToolPushButton(_ThemedButton):
    """区块内的小型工具按钮"""

    object_name = "toolButton"


class SimpleCardWidget(QFrame):
    """白色内容卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")


class CardWidget(SimpleCardWidget):
    """白色内容卡片（保留原类名）"""


class ScrollArea(QScrollArea):
    """无边框滚动区"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)


class ProgressBar(QProgressBar):
    """细条形进度条"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setRange(0, 100)


# ====================================================================
# 顶部提示条（InfoBar）
# ====================================================================
class InfoBarPosition:
    """提示条位置常量（与原 InfoBarPosition 兼容）"""

    TOP = "top"
    BOTTOM = "bottom"
    TOP_RIGHT = "top-right"
    BOTTOM_RIGHT = "bottom-right"
    LEFT = "left"
    RIGHT = "right"


_LEVEL_STYLE = {
    "success": (SUCCESS, SUCCESS_LIGHT, SUCCESS_BORDER),
    "warning": (WARNING, WARNING_LIGHT, WARNING_BORDER),
    "error": (DANGER, DANGER_LIGHT, DANGER_BORDER),
    "info": (PRIMARY, PRIMARY_LIGHT, PRIMARY_BORDER),
}

_LEVEL_SYMBOL = {"success": "✓", "warning": "!", "error": "✕", "info": "i"}


class _InfoBarWidget(QFrame):
    """提示条实体：浮在主界面顶部，不占用布局空间"""

    def __init__(self, level, title, content, closable, parent=None):
        super().__init__(parent)
        self.setObjectName("infoBar")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        accent, bg, border = _LEVEL_STYLE.get(level, _LEVEL_STYLE["info"])
        self.setStyleSheet(
            f"QFrame#infoBar {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(8)

        indicator = QLabel(self)
        indicator.setFixedSize(4, 4)
        indicator.setStyleSheet(f"background: {accent}; border-radius: 2px;")
        layout.addWidget(indicator, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)

        if title:
            title_label = QLabel(str(title), self)
            title_label.setObjectName("infoBarTitle")
            title_label.setWordWrap(True)
            text_box.addWidget(title_label)

        if content:
            content_label = QLabel(str(content), self)
            content_label.setObjectName("infoBarContent")
            content_label.setWordWrap(True)
            content_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            text_box.addWidget(content_label)

        layout.addLayout(text_box, 1)

        self.close_button = None
        if closable:
            self.close_button = QPushButton("✕", self)
            self.close_button.setObjectName("infoBarClose")
            self.close_button.setFixedSize(20, 20)
            self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.close_button.clicked.connect(self.close)
            layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

        self._host = None
        self._position = InfoBarPosition.TOP

    def attach(self, host, position=InfoBarPosition.TOP):
        """挂载到宿主窗口并定位"""
        self._host = host
        self._position = position
        host.installEventFilter(self)
        self.setParent(host)
        self.adjustSize()
        self.show()
        self.raise_()
        self._reposition()
        QTimer.singleShot(0, self._reposition)

    def eventFilter(self, watched, event):
        if watched is self._host and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self._reposition()
        return super().eventFilter(watched, event)

    def _reposition(self):
        host = self._host
        if host is None:
            return
        width = min(520, max(260, host.width() - 60))
        self.setFixedWidth(width)
        height = self.sizeHint().height()
        if self._position == InfoBarPosition.BOTTOM:
            y = max(0, host.height() - height - 16)
        else:
            y = 14 + self._header_offset()
        x = max(0, (host.width() - width) // 2)
        self.setGeometry(x, y, width, height)
        self.raise_()

    def _header_offset(self):
        """提示条需要避开的顶部标题栏高度"""
        if self._host is None:
            return 0
        header = self._host.findChild(QFrame, "headerBar")
        if header is not None and header.isVisible():
            return header.height() + 6
        return 0


class InfoBar:
    """轻量提示条（静态调用，接口与原 qfluentwidgets.InfoBar 一致）"""

    @staticmethod
    def success(**kwargs):
        return InfoBar._show("success", **kwargs)

    @staticmethod
    def error(**kwargs):
        return InfoBar._show("error", **kwargs)

    @staticmethod
    def warning(**kwargs):
        return InfoBar._show("warning", **kwargs)

    @staticmethod
    def info(**kwargs):
        return InfoBar._show("info", **kwargs)

    @staticmethod
    def _show(level, title="", content="", orient=None, isClosable=True,
              position=InfoBarPosition.TOP, duration=5000, parent=None):
        host = parent if parent is not None else QApplication.activeWindow()
        if host is None:
            return None
        # 主窗口的中央部件才是内容区，避免提示条压住菜单栏
        if hasattr(host, "centralWidget"):
            central = host.centralWidget()
            if central is not None:
                host = central
        bar = _InfoBarWidget(level, title, content, isClosable)
        bar.attach(host, position)
        if duration:
            QTimer.singleShot(int(duration), bar.close)
        return bar


# ====================================================================
# 对话框（MessageBox）
# ====================================================================
class MessageBox(QDialog):
    """模态确认/提示对话框。

    - 标题、图标、正文分区排版；
    - 正文使用 QTextBrowser，长文本自动换行并可滚动，保证完整可读；
    - yesButton / cancelButton 暴露给调用方改写按钮文字；
    - exec() 返回 True 表示「确定」，False 表示「取消」。
    """

    _ICON_STYLE = {
        "info": (PRIMARY, PRIMARY_LIGHT, "i"),
        "question": (PRIMARY, PRIMARY_LIGHT, "?"),
        "warning": (WARNING, WARNING_LIGHT, "!"),
        "error": (DANGER, DANGER_LIGHT, "✕"),
        "success": (SUCCESS, SUCCESS_LIGHT, "✓"),
    }

    DIALOG_WIDTH = 560          # 对话框宽度
    TEXT_WIDTH = 500            # 正文可用宽度（对话框宽 - 边距 - 正文框内边距），略窄以防截断
    TEXT_PADDING = 16           # 正文框内边距 + 边框 + 余量
    MIN_TEXT_HEIGHT = 48        # 正文区最小高度
    MAX_TEXT_HEIGHT = 320       # 正文区最大高度，超出部分内部滚动
    CHROME_HEIGHT = 124         # 标题区 + 按钮区 + 各段间距合计高度

    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(str(title))
        self.setModal(True)
        self.setMinimumWidth(self.DIALOG_WIDTH)
        self._raw_content = str(content)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 0)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(28, 28)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        accent, bg, symbol = self._ICON_STYLE["info"]
        self.icon_label.setText(symbol)
        self.icon_label.setStyleSheet(
            f"background: {bg}; color: {accent}; border-radius: 14px;"
            f" font-weight: 600; font-size: {FONT_SIZE_BASE + 1}pt;"
        )
        head.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)

        self.title_label = QLabel(str(title), self)
        self.title_label.setObjectName("messageBoxTitle")
        self.title_label.setWordWrap(True)
        head.addWidget(self.title_label, 1)
        root.addLayout(head)

        self.content_text = QTextBrowser(self)
        self.content_text.setObjectName("messageBoxText")
        self.content_text.setOpenExternalLinks(False)
        self.content_text.setText(self._raw_content)
        # 正文高度由内容决定，不参与布局拉伸（避免短文本时下方出现大片空白）
        root.addWidget(self.content_text, 0)

        footer = QFrame(self)
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 10, 20, 12)
        footer_layout.addStretch()

        self.cancelButton = QPushButton("取消", self)
        self.cancelButton.setObjectName("secondaryButton")
        self.cancelButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancelButton.clicked.connect(self.reject)

        self.yesButton = QPushButton("确定", self)
        self.yesButton.setObjectName("primaryButton")
        self.yesButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.yesButton.setDefault(True)
        self.yesButton.clicked.connect(self.accept)

        footer_layout.addWidget(self.cancelButton)
        footer_layout.addWidget(self.yesButton)
        root.addWidget(footer)

        self._fit_size()

    def _measure_text_height(self, width):
        """测量正文在给定宽度下所需的真实高度。

        不能直接读取 QTextBrowser 自身的 document：控件尚未完成布局时视口宽度
        只有约 100px，测出的高度会明显偏大（正文区出现大片空白）。
        这里用相同字体、相同文档边距新建独立文档单独测量，结果稳定可复现。
        """
        source = self.content_text.document()
        doc = QTextDocument()
        doc.setDefaultFont(source.defaultFont())
        doc.setDocumentMargin(source.documentMargin())
        doc.setPlainText(self._raw_content)
        doc.setTextWidth(width)
        return int(doc.size().height())

    def _fit_size(self):
        """按正文长度自适应高度（超长时正文区内部滚动）"""
        height = self._measure_text_height(self.TEXT_WIDTH) + self.TEXT_PADDING
        visible = max(self.MIN_TEXT_HEIGHT, min(height, self.MAX_TEXT_HEIGHT))
        self.content_text.setFixedHeight(visible)
        self.resize(self.DIALOG_WIDTH, self.CHROME_HEIGHT + visible)

    def set_icon(self, kind="info"):
        """切换图标类型（info / question / warning / error / success）"""
        accent, bg, symbol = self._ICON_STYLE.get(kind, self._ICON_STYLE["info"])
        self.icon_label.setText(symbol)
        self.icon_label.setStyleSheet(
            f"background: {bg}; color: {accent}; border-radius: 14px;"
            f" font-weight: 600; font-size: {FONT_SIZE_BASE + 1}pt;"
        )

    def exec(self):
        """返回 True 表示用户点击「确定」"""
        return super().exec() == QDialog.DialogCode.Accepted


# ====================================================================
# 列表自绘委托
# ====================================================================
def _draw_chip(painter, rect, text, bg, fg, font):
    """绘制右侧小标签（返回标签左边缘 x 坐标）"""
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(text) + 14
    height = metrics.height() + 4
    chip = rect.__class__(rect.right() - width + 1, rect.top() + 4, width, height)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(bg))
    painter.drawRoundedRect(chip, 3, 3)
    painter.setPen(QColor(fg))
    painter.setFont(font)
    painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
    return chip.left()


class DeviceItemDelegate(QStyledItemDelegate):
    """设备列表项：名称 + 地址（+ 模板）+ 右侧分组标签"""

    ROW_HEIGHT = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name_font = base_font(10, bold=True)
        self._meta_font = base_font(FONT_SIZE_SMALL)
        self._chip_font = base_font(FONT_SIZE_SMALL)

    def sizeHint(self, option, index):
        return QSize(240, self.ROW_HEIGHT)

    def paint(self, painter, option, index):
        device = index.data(Qt.ItemDataRole.UserRole) or {}
        name = str(device.get("name", "") or "")
        url = str(device.get("url", "") or "")
        group = str(device.get("group", "") or "")
        template = str(device.get("template", "") or "")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect.adjusted(0, 0, -1, 0)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PRIMARY_LIGHT))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
            painter.setBrush(QColor(PRIMARY))
            painter.drawRoundedRect(2, 4, 3, rect.height() - 8, 1, 1)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F7F8FA"))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)

        text_left = rect.left() + 12
        text_right = rect.right() - 10

        # 右侧分组标签
        if group:
            metrics = QFontMetrics(self._chip_font)
            chip_width = metrics.horizontalAdvance(group) + 14
            chip_rect = rect.__class__(text_right - chip_width, rect.top() + 9,
                                      chip_width, metrics.height() + 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(INFO_LIGHT))
            painter.drawRoundedRect(chip_rect, 3, 3)
            painter.setPen(QColor(TEXT_SECONDARY))
            painter.setFont(self._chip_font)
            painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, group)
            text_right = chip_rect.left() - 8

        # 设备名称
        painter.setFont(self._name_font)
        painter.setPen(QColor(TEXT_PRIMARY))
        name_rect = rect.__class__(text_left, rect.top() + 3,
                                   max(20, text_right - text_left), 18)
        name_metrics = QFontMetrics(self._name_font)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         name_metrics.elidedText(name, Qt.TextElideMode.ElideRight,
                                                 name_rect.width()))

        # 地址（+ 模板）
        meta = url
        if template and template.lower() != "default":
            meta = f"{url}  ·  模板: {template}" if meta else f"模板: {template}"
        painter.setFont(self._meta_font)
        painter.setPen(QColor(TEXT_SECONDARY))
        meta_rect = rect.__class__(text_left, rect.top() + 21,
                                   max(20, text_right - text_left), 16)
        meta_metrics = QFontMetrics(self._meta_font)
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         meta_metrics.elidedText(meta, Qt.TextElideMode.ElideMiddle,
                                                 meta_rect.width()))
        painter.restore()


class LogItemDelegate(QStyledItemDelegate):
    """日志列表项：左侧时间戳 + 右侧按级别着色的正文（自动换行）"""

    TIMESTAMP_WIDTH = 78

    def __init__(self, parent=None):
        super().__init__(parent)
        self._time_font = base_font(FONT_SIZE_SMALL)
        self._body_font = base_font(FONT_SIZE_BASE)

    _LEVEL_COLORS = {
        "success": SUCCESS,
        "warning": WARNING,
        "error": DANGER,
        "info": TEXT_REGULAR,
    }

    def _split(self, text):
        text = str(text or "")
        if text.startswith("[") and "] " in text:
            end = text.index("]")
            return text[1:end], text[end + 2:]
        return "", text

    def _document(self, body, width, color):
        doc = QTextDocument()
        doc.setDefaultFont(self._body_font)
        doc.setTextWidth(max(40, width))
        doc.setHtml(f'<span style="color:{color};">{body}</span>')
        return doc

    def sizeHint(self, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        _stamp, body = self._split(text)
        width = max(60, option.rect.width() - self.TIMESTAMP_WIDTH - 18)
        doc = self._document(body, width, TEXT_REGULAR)
        return QSize(option.rect.width(), int(doc.size().height()) + 10)

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        level = index.data(ROLE_LOG_LEVEL) or "info"
        color = self._LEVEL_COLORS.get(level, TEXT_REGULAR)
        stamp, body = self._split(text)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PRIMARY_LIGHT))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F7F8FA"))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)

        text_left = rect.left() + 8
        if stamp:
            painter.setFont(self._time_font)
            painter.setPen(QColor(TEXT_SECONDARY))
            stamp_rect = rect.__class__(text_left, rect.top() + 4, self.TIMESTAMP_WIDTH - 10, 16)
            painter.drawText(stamp_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             stamp)

        body_left = text_left + self.TIMESTAMP_WIDTH - 10
        body_width = max(40, rect.right() - body_left - 10)
        doc = self._document(body, body_width, color)
        painter.translate(body_left, rect.top() + 3)
        doc.drawContents(painter)
        painter.restore()


# ====================================================================
# 便捷工具
# ====================================================================
def make_badge(text, object_name="statChip", parent=None):
    """创建一个带背景的小圆角标签（标题栏的版本号 / 统计信息）"""
    label = QLabel(text, parent)
    label.setObjectName(object_name)
    label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def divider(vertical=True, parent=None):
    """细分隔线"""
    line = QFrame(parent)
    if vertical:
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
    else:
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
    line.setStyleSheet(f"color: {BORDER_LIGHT};")
    return line


def set_list_viewport(list_widget):
    """列表统一使用 Qt 默认滚动行为 + 去掉外框"""
    view = list_widget.viewport()
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    list_widget.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
    list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    return list_widget


__all__ = [
    "BodyLabel", "CaptionLabel", "CardWidget", "DangerPushButton", "FieldLabel",
    "GhostPushButton", "InfoBar", "InfoBarPosition", "MessageBox", "PrimaryPushButton",
    "ProgressBar", "PushButton", "ROLE_LOG_LEVEL", "ScrollArea", "SimpleCardWidget",
    "StrongBodyLabel", "TitleLabel", "ToolPushButton", "DeviceItemDelegate",
    "LogItemDelegate", "base_font", "divider", "make_badge", "set_list_viewport",
]
