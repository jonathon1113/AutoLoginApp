"""界面设计规范（设计令牌 + 全局样式表）。

本模块是整个应用视觉风格的唯一来源：
- COLORS / FONTS / RADIUS / SPACING 定义设计令牌；
- build_stylesheet() 由令牌拼装出全局 QSS；
- apply_theme() 把字体与样式表应用到 QApplication。

设计原则：浅色主题、弱装饰、信息层级清晰、适合长时间运维使用。
所有主窗口、对话框、菜单、状态栏共用同一套令牌，避免各页面各写一套样式。
"""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

# ============ 颜色令牌 ============
PRIMARY = "#409EFF"
PRIMARY_HOVER = "#66B1FF"
PRIMARY_PRESSED = "#3A8EE6"
PRIMARY_LIGHT = "#ECF5FF"
PRIMARY_BORDER = "#D9ECFF"
PRIMARY_DISABLED = "#A0CFFF"

SUCCESS = "#67C23A"
SUCCESS_LIGHT = "#F0F9EB"
SUCCESS_BORDER = "#E1F3D8"

WARNING = "#E6A23C"
WARNING_LIGHT = "#FDF6EC"
WARNING_BORDER = "#FAECD8"

DANGER = "#F56C6C"
DANGER_LIGHT = "#FEF0F0"
DANGER_BORDER = "#FDE2E2"

INFO = "#909399"
INFO_LIGHT = "#F4F4F5"

TEXT_PRIMARY = "#303133"
TEXT_REGULAR = "#606266"
TEXT_SECONDARY = "#909399"
TEXT_PLACEHOLDER = "#C0C4CC"

BORDER = "#E4E7ED"
BORDER_LIGHT = "#EBEEF5"
BORDER_STRONG = "#DCDFE6"

BG_APP = "#F5F7FA"
BG_PANEL = "#FFFFFF"
BG_HOVER = "#F5F7FA"
BG_READONLY = "#FAFAFA"

# ============ 字体令牌 ============
FONT_FAMILY = "Microsoft YaHei UI"
# 字体回退链：优先使用界面更精致的微软雅黑 UI，缺失时依次回退到其它中文字体，
# 避免在缺少微软雅黑的系统上出现方块字
FONT_FALLBACKS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun")
FONT_SIZE_BASE = 9.5      # 正文
FONT_SIZE_SMALL = 8.5     # 辅助文字
FONT_SIZE_SECTION = 10.5  # 区块标题
FONT_SIZE_TITLE = 15      # 应用标题

# ============ 圆角与间距 ============
RADIUS_SMALL = "4px"
RADIUS = "6px"
RADIUS_PILL = "11px"

SPACING_XS = "4px"
SPACING_SM = "8px"
SPACING_MD = "12px"
SPACING_LG = "16px"
SPACING_XL = "20px"


def base_font(size=FONT_SIZE_BASE, bold=False):
    """构造统一字体的 QFont"""
    font = QFont()
    font.setFamilies(list(FONT_FALLBACKS))
    font.setPointSizeF(size)
    if bold:
        font.setWeight(QFont.Weight.Bold)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def build_stylesheet():
    """由设计令牌拼装全局样式表"""
    return f"""
/* ============ 基础 ============ */
QWidget {{
    font-family: "{FONT_FAMILY}";
    color: {TEXT_REGULAR};
}}
QMainWindow, QWidget#mainInterface {{
    background: {BG_APP};
}}
QToolTip {{
    background: {TEXT_PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: {RADIUS_SMALL};
    padding: 4px 8px;
}}

/* ============ 头部栏 ============ */
QFrame#headerBar {{
    background: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}
QLabel#appTitle {{
    font-size: {FONT_SIZE_TITLE}pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#appVersion {{
    font-size: {FONT_SIZE_SMALL}pt;
    color: {PRIMARY};
    background: {PRIMARY_LIGHT};
    border: 1px solid {PRIMARY_BORDER};
    border-radius: {RADIUS_PILL};
    padding: 2px 9px;
}}
QLabel#statChip {{
    font-size: {FONT_SIZE_BASE}pt;
    color: {TEXT_REGULAR};
    background: {BG_APP};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PILL};
    padding: 4px 12px;
}}
QLabel#headerDivider {{
    background: {BORDER};
    max-width: 1px;
    min-width: 1px;
}}

/* ============ 面板与区块 ============ */
QFrame#panel {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
}}
QFrame#footerBar {{
    background: {BG_PANEL};
    border-top: 1px solid {BORDER};
}}
QLabel#sectionTitle {{
    font-size: {FONT_SIZE_SECTION}pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#sectionHint {{
    font-size: {FONT_SIZE_SMALL}pt;
    color: {TEXT_SECONDARY};
}}
QLabel#fieldLabel {{
    color: {TEXT_REGULAR};
}}
QLabel#progressText {{
    color: {TEXT_REGULAR};
}}
QLabel#statusHint {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_SMALL}pt;
}}

/* ============ 按钮 ============ */
QPushButton {{
    background: {BG_PANEL};
    color: {TEXT_REGULAR};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_SMALL};
    padding: 6px 16px;
    font-size: {FONT_SIZE_BASE}pt;
    min-height: 18px;
}}
QPushButton:hover {{
    color: {PRIMARY};
    border-color: {PRIMARY};
    background: {PRIMARY_LIGHT};
}}
QPushButton:pressed {{
    background: {PRIMARY_BORDER};
}}
QPushButton:disabled {{
    color: {TEXT_PLACEHOLDER};
    border-color: {BORDER};
    background: {BG_APP};
}}
QPushButton#primaryButton {{
    background: {PRIMARY};
    color: #FFFFFF;
    border: 1px solid {PRIMARY};
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background: {PRIMARY_HOVER};
    border-color: {PRIMARY_HOVER};
    color: #FFFFFF;
}}
QPushButton#primaryButton:pressed {{
    background: {PRIMARY_PRESSED};
    border-color: {PRIMARY_PRESSED};
}}
QPushButton#primaryButton:disabled {{
    background: {PRIMARY_DISABLED};
    border-color: {PRIMARY_DISABLED};
    color: #FFFFFF;
}}
QPushButton#dangerButton {{
    color: {DANGER};
    border-color: {DANGER_BORDER};
    background: {DANGER_LIGHT};
}}
QPushButton#dangerButton:hover {{
    background: {DANGER};
    border-color: {DANGER};
    color: #FFFFFF;
}}
QPushButton#ghostButton {{
    background: transparent;
    border: 1px solid transparent;
    color: {TEXT_REGULAR};
    padding: 6px 12px;
}}
QPushButton#ghostButton:hover {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
    border-color: {PRIMARY_BORDER};
}}
QPushButton#toolButton {{
    background: transparent;
    border: 1px solid transparent;
    color: {TEXT_SECONDARY};
    padding: 4px 10px;
    font-size: {FONT_SIZE_SMALL}pt;
}}
QPushButton#toolButton:hover {{
    background: {BG_HOVER};
    color: {PRIMARY};
    border-color: {BORDER};
}}

/* ============ 分组卡片 ============ */
QPushButton#groupCard {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px;
}}
QPushButton#groupCard:hover {{
    border-color: {PRIMARY};
    background: {PRIMARY_LIGHT};
}}
QPushButton#groupCard:pressed {{
    background: {PRIMARY_BORDER};
}}

/* ============ 输入控件 ============ */
QLineEdit, QComboBox, QSpinBox {{
    background: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_SMALL};
    padding: 5px 8px;
    selection-background-color: {PRIMARY};
    selection-color: #FFFFFF;
    min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {PRIMARY};
}}
QLineEdit::placeholder {{
    color: {TEXT_PLACEHOLDER};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox QAbstractItemView {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SMALL};
    selection-background-color: {PRIMARY_LIGHT};
    selection-color: {PRIMARY};
    outline: none;
    padding: 2px;
}}
QComboBox QAbstractItemView::item {{
    padding: 5px 8px;
    min-height: 20px;
}}

/* ============ 复选框 ============ */
QCheckBox {{
    color: {TEXT_SECONDARY};
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
    background: {BG_PANEL};
}}
QCheckBox::indicator:hover {{
    border-color: {PRIMARY};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}

/* ============ 列表 ============ */
QListWidget {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SMALL};
    outline: none;
}}
QListWidget::item {{
    border: none;
    padding: 0px;
}}
QListWidget::item:hover {{
    background: {BG_HOVER};
}}
QListWidget::item:selected {{
    background: {PRIMARY_LIGHT};
    color: {TEXT_PRIMARY};
}}

/* ============ 进度条 ============ */
QProgressBar {{
    background: {BORDER_LIGHT};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: {TEXT_SECONDARY};
}}
QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 3px;
}}

/* ============ 菜单栏与菜单 ============ */
QMenuBar {{
    background: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 12px;
    border-radius: {RADIUS_SMALL};
    margin: 1px 2px;
}}
QMenuBar::item:selected {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
}}
QMenu {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SMALL};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: {RADIUS_SMALL};
    margin: 1px 2px;
}}
QMenu::item:selected {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER_LIGHT};
    margin: 4px 8px;
}}

/* ============ 分割条 ============ */
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:horizontal {{
    width: 8px;
}}
QSplitter::handle:vertical {{
    height: 8px;
}}
QSplitter::handle:hover {{
    background: {PRIMARY_LIGHT};
}}

/* ============ 滚动条 ============ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: #C8CDD6;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #A8B0BC;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: #C8CDD6;
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #A8B0BC;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
    border: none;
    background: transparent;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ============ 状态栏 ============ */
QStatusBar {{
    background: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_SECONDARY};
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_SMALL}pt;
    padding: 0px 6px;
}}

/* ============ 提示条（InfoBar）============ */
QFrame#infoBar {{
    border-radius: {RADIUS_SMALL};
    border: 1px solid {BORDER};
    background: {BG_PANEL};
}}
QLabel#infoBarTitle {{
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#infoBarContent {{
    color: {TEXT_REGULAR};
}}
QPushButton#infoBarClose {{
    background: transparent;
    border: none;
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_SMALL}pt;
    padding: 0px 4px;
}}
QPushButton#infoBarClose:hover {{
    color: {TEXT_PRIMARY};
    background: transparent;
    border: none;
}}

/* ============ 对话框 ============ */
QDialog {{
    background: {BG_PANEL};
}}
QLabel#messageBoxTitle {{
    font-size: {FONT_SIZE_SECTION}pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#messageBoxContent {{
    color: {TEXT_REGULAR};
}}
QTextBrowser#messageBoxText {{
    background: {BG_READONLY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SMALL};
    color: {TEXT_REGULAR};
    padding: 6px;
}}
QFrame#dialogFooter {{
    background: {BG_APP};
    border-top: 1px solid {BORDER};
}}
"""


def apply_theme(app=None):
    """把统一字体与样式表应用到应用（QApplication 或当前实例）"""
    app = app or QApplication.instance()
    if app is None:
        return None
    app.setFont(base_font())
    app.setStyleSheet(build_stylesheet())
    return app
