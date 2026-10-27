"""全局配置、路径与超时常量。

路径规则（兼容 PyInstaller 单文件模式）：
- APP_DIR      可写数据目录（EXE 同目录 / 源码根目录）：devices.json、日志、模板、Excel。
- RESOURCE_DIR 只读资源目录（打包后为 sys._MEIPASS 解压目录）：随包发布的图标等。
"""

import os
import sys

# appcore 包的上一级即项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_app_dir():
    """获取可写数据目录（兼容打包后的 EXE）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return _PROJECT_ROOT


def get_resource_dir():
    """获取随包资源目录（PyInstaller 单文件模式下为解压目录）"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', get_app_dir())
    return _PROJECT_ROOT


APP_DIR = get_app_dir()
RESOURCE_DIR = get_resource_dir()

CONFIG_FILE = os.path.join(APP_DIR, "devices.json")
LOG_DB_FILE = os.path.join(APP_DIR, "login_logs.db")
APP_LOG_FILE = os.path.join(APP_DIR, "app.log")
ERROR_LOG_FILE = os.path.join(APP_DIR, "error.log")
TEMPLATE_DIR = os.path.join(APP_DIR, "templates")
EXCEL_TEMPLATE_FILE = os.path.join(APP_DIR, "devices_template.xlsx")

# ============ 浏览器启动参数 ============
# 浏览器窗口启动时是否最大化。
# 背景：历史版本浏览器窗口以固定小尺寸打开，且 Playwright 默认把页面视口
# 模拟为固定 1280x720，导致「放大窗口页面尺寸仍不变化」。
# 修复：1) 上下文使用 no_viewport=True，页面视口跟随真实窗口尺寸；
#      2) 窗口默认最大化（--start-maximized），充分利用屏幕空间。
# 该行为可随时通过本开关关闭，不影响其它启动参数。
BROWSER_START_MAXIMIZED = True

# 迁移自原 Selenium 的 ChromeOptions，语义保持一致
BROWSER_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--ignore-certificate-errors",
    "--ignore-ssl-errors",
    "--disable-web-security",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
    # 降低自动化特征，减少目标站点对自动化驱动的拦截
    "--disable-blink-features=AutomationControlled",
]

if BROWSER_START_MAXIMIZED:
    BROWSER_LAUNCH_ARGS.append("--start-maximized")

# ============ 超时常量（沿用原项目取值）============
TIMEOUT_PAGE_LOAD = 2      # 页面加载等待（秒）
TIMEOUT_INPUT_DELAY = 0.3  # 原输入间隔延时，Playwright 自动等待后不再使用
TIMEOUT_TAB_SWITCH = 1      # 标签页切换等待（秒）
TIMEOUT_CAPTCHA = 2         # 验证码等待（秒）
TIMEOUT_LOGIN_WAIT = 2      # 登录后等待（秒）

TIMEOUT_PAGE = 10           # 页面就绪等待
TIMEOUT_ELEMENT = 5         # 元素等待
TIMEOUT_CLICK = 3           # 点击等待
TIMEOUT_FILL = 3            # 填写等待（避免不可编辑元素把流程挂到默认超时）
TIMEOUT_NEW_WINDOW = 5      # 新窗口/标签页等待
TIMEOUT_SELECTOR = 3        # 已确认存在的元素，等待其可见的超时

# 选择器快速探测：元素不存在时只做一次极短复查后立即判定失败，
# 避免对每个候选选择器都消耗数秒等待（这是登录缓慢的主要来源）。
TIMEOUT_SELECTOR_PROBE = 0.5  # 元素不存在时的短暂复查窗口（秒）
TIMEOUT_VISIBLE = 2           # 元素已存在但当前不可见时，等待其可见的超时（秒）
# 元素存在但当前不可见时的快速等待上限（秒）。
# 页面常同时存在一个隐藏的同名 input（如 type=hidden 的 #password）
# 与真正的密码框，长时间等待隐藏元素会白白吃掉查找预算。
TIMEOUT_HIDDEN_WAIT = 0.8

# 单类选择器（用户名 / 密码 / 登录按钮）的查找总耗时上限（秒）。
# 该预算是「整个查找阶段」的上限，用于防止在没有登录表单的页面上无限等待，
# 不是「每个候选」的等待上限：候选的逐个存在性检查是毫秒级的，
# 整份候选列表都会在预算内被真正执行；预算只用于「延迟渲染等待窗口」。
SELECTOR_LOOKUP_BUDGET = 2.5

# 慢速页面的「扩展等待预算」（秒）。
# 仅当基础预算耗尽、且页面仍未渲染出任何表单控件时启用：
# 说明页面可能还在加载（慢速网络 / 异步渲染），
# 此时额外等待这么久再判定「元素未找到」，避免把慢页面误判为不支持。
# 基础预算 + 扩展预算 = 单类选择器的总上限，仍然是有界的，不会无限等待。
SELECTOR_LOOKUP_SLOW_BUDGET = 8.0

# 页面已加载完成（readyState=complete）但仍没有表单控件时的扩展等待上限（秒）。
# 这种情况多为 SPA 在 load 之后才渲染表单，给一个较短的窗口即可；
# 避免对「根本不是登录页」的设备造成长时间等待。
SELECTOR_LOOKUP_READY_BUDGET = 3.0

# 慢速等待窗口内的最大复查轮数（与扩展预算共同约束总耗时）
SELECTOR_SLOW_MAX_ROUNDS = 40

# 「延迟渲染窗口」中判定页面已渲染稳定的连续轮数。
# 表单控件数量连续这么多轮没有变化，说明页面已经渲染完成，
# 此时候选元素确实不存在，继续等待只是空转，应提前结束该窗口。
SELECTOR_STABLE_ROUNDS = 4

# 验证码输入框的查找预算（秒）：验证码框常比用户名/密码框晚渲染，
# 需要独立的时间窗口，但仍为有限值。
CAPTCHA_LOOKUP_BUDGET = 6.0

# 验证码输入框的「快速存在性检查」窗口（秒）。
#
# 用于正常登录流程：当用户名 / 密码已定位成功、页面已就绪且可交互时，
# 只需要快速确认页面上是否存在需要人工填写的验证码输入框。
# 该窗口不叠加慢速页面的扩展等待预算（extra_budget=0），
# 因此正常页面不会再因为「确认没有验证码」而白白等待数秒。
#
# 等待窗口并非固定 sleep：只有在检测到页面表单控件数量仍在变化
# （即页面还在渲染、验证码框可能马上出现）时才会继续等待；
# 页面控件数量一旦稳定，立即结束检查并继续提交登录。
CAPTCHA_QUICK_WAIT_BUDGET = 1.2

# 验证码快速检查中，判定「页面表单控件数量已稳定」的连续轮数。
# 连续这么多轮控件数量都没有变化，才认为页面确实不再渲染新控件；
# 轮数太少可能漏掉延迟出现的验证码框，轮数太多又会拖慢正常页面。
CAPTCHA_QUICK_STABLE_ROUNDS = 2

# 延迟渲染等待窗口的轮询间隔（秒）：页面级共享预算，不是每个候选各等一次。
SELECTOR_SCAN_INTERVAL = 0.15

# 子 frame（iframe）内快速扫描的独立预算上限（秒）
SELECTOR_FRAME_BUDGET = 0.8

# 单次模板尝试（定位 + 填写 + 提交 + 结果判定）的总耗时上限（秒）
TEMPLATE_ATTEMPT_BUDGET = 20

# 通用元素发现兜底时，单个字段（用户名 / 密码）的查找耗时上限（秒）
GENERIC_DISCOVERY_BUDGET = 1.0

# 登录结果确认等待时间（Playwright 自动等待之外的业务等待）
LOGIN_RESULT_TIMEOUT = 12

APP_NAME = "批量自动化登录工具"

# ============ 统一版本来源 ============
# 项目当前发布版本。GUI 标题、关于窗口、打包 EXE 名称与文件版本资源
# 均从本处读取，避免多处维护导致版本不一致。
# 递增规则：正式发布按补丁号递增（5.0.11 -> 5.0.12 -> 5.0.13 ...），
# 详见根目录 CHANGELOG.md。开发/调试/重复打包不得修改本值。
APP_VERSION = "5.0.11"
APP_VERSION_INFO = (5, 0, 11, 2)


def resolve_icon_path():
    """获取应用图标路径。

    优先级：随包资源目录(ico/app.ico) -> 数据目录(ico/app.ico) -> 内嵌图标(icon_data)。
    源码运行与 PyInstaller 单文件运行均能正确显示原有图标。
    """
    for base in (RESOURCE_DIR, APP_DIR):
        path = os.path.join(base, 'ico', 'app.ico')
        if os.path.exists(path):
            return path
    try:
        from icon_data import get_icon_path
        return get_icon_path()
    except Exception:
        return None
