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

# ============ 验证码自动识别（图片验证码 OCR）============
# 开关：是否自动识别并填写「数字 + 大小写字母」图片验证码。
#
# 关闭时（或 ddddocr 未安装时）行为与历史版本完全一致：
# 检测到验证码输入框即停止，不提交登录表单，交由人工处理。
#
# 运行期可在界面（快捷登录面板的「自动识别验证码」复选框）切换，
# 因此本项必须通过模块属性访问（appcore.config.CAPTCHA_AUTO_ENABLED），
# 不要在其它模块里用 from .config import CAPTCHA_AUTO_ENABLED 提前绑定。
CAPTCHA_AUTO_ENABLED = True

# 字符集：0-9 + a-z + A-Z（ddddocr 的 set_ranges 必须传字符串，
# 传整数会被解释为「默认字符集前 N+1 个字符」，语义完全不同）
CAPTCHA_OCR_CHARSET = ("0123456789"
                       "abcdefghijklmnopqrstuvwxyz"
                       "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# 验证码固定长度（本项目已确认的验证码特征）
CAPTCHA_OCR_LENGTH = 4

# 是否区分大小写。
#
# True（默认）= 识别结果**原样提交**，不改变大小写。
#   - 对「区分大小写」的站点：必须原样提交，否则统一转大写会把正确答案改错；
#   - 对「不区分大小写」的站点：原样提交同样能通过。
#   => 原样提交对两类站点都安全，统一转大写只会在区分大小写的站点上出错。
# False = 校验通过后按 CAPTCHA_OCR_NORMALIZE_TO 统一大小写
#   （仅当确认站点不区分大小写、且 OCR 的大小写判断不稳定时才需要）。
CAPTCHA_OCR_CASE_SENSITIVE = True
CAPTCHA_OCR_NORMALIZE_TO = "upper"        # upper / lower（仅上面为 False 时生效）

# 使用 ddddocr 的 beta 模型：对「小字号 + 彩色干扰线」的验证码明显更好
# （实测：默认模型 4 位合法输出率 10%~20%，beta 模型 55%~67%）
CAPTCHA_OCR_BETA = True

# 使用 ddddocr 内置的颜色过滤：去掉彩色干扰线（红/蓝/绿/黄/橙/紫/青）
#
# 实测（真实站点 test.my.cn，每轮全新会话、单次提交）：
#   关闭颜色过滤：每轮 4 次尝试成功率约 17%；
#   开启颜色过滤：0%（过滤会把字符的抗锯齿边缘一起抹掉，笔画变细反而更难识别）。
# 因此默认**关闭**；只有在干扰线颜色鲜艳、字符为纯黑且较粗时才建议开启。
CAPTCHA_OCR_COLOR_FILTER = False

# 置信度下限：低于该值视为识别失败（刷新后重试，不提交）
CAPTCHA_OCR_MIN_CONFIDENCE = 0.5

# 轻度预处理与多变体识别（干扰线 / 噪点场景）
CAPTCHA_OCR_PREPROCESS = True
CAPTCHA_OCR_MULTI_PASS = True

# 自动识别最大尝试次数（含首次）
#
# 实测（真实站点 test.my.cn，区分大小写）：加入「去彩色干扰掩膜」预处理后，
# 单次成功率约 15%。困难验证码靠「多次独立重试」累积成功率：
#   10 次约 80%，20 次约 96%，30 次约 99%。
# 实际能试多少次由 CAPTCHA_ATTEMPT_BUDGET（时间预算）兜底，
# 每次尝试约 2~3 秒。
CAPTCHA_OCR_MAX_ATTEMPTS = 30

# 可选增强：启用 OpenCV 颜色过滤（需额外安装 opencv-python-headless，默认关闭）
CAPTCHA_OCR_USE_OPENCV = False

# 查找验证码图片的预算（秒）
CAPTCHA_IMAGE_LOOKUP_BUDGET = 3.0

# 点击刷新后等待图片更新的时间（秒）
CAPTCHA_REFRESH_WAIT = 0.8

# 每次提交后等待登录结果的时间（秒），比普通登录短，避免拖慢批量任务
CAPTCHA_RESULT_TIMEOUT = 6

# 带验证码重试的单次尝试总预算（秒）。
# 注意：验证码自动模式下最多会重试 CAPTCHA_OCR_MAX_ATTEMPTS 次，
# 必须使用独立的 60 秒预算；沿用 TEMPLATE_ATTEMPT_BUDGET(20) 必然超时告警。
CAPTCHA_ATTEMPT_BUDGET = 60

# ---- 验证码查找「跳过」优化 ----
# 设备模板里 captcha_selectors 为空时，视为该页面「本来就没有验证码」，
# 直接跳过验证码查找（不再把模板候选 + 内置候选几十个选择器查一遍）。
# 注意：只对「设备模板」生效；默认模板仍按内置规则检查。
CAPTCHA_SKIP_WHEN_TEMPLATE_EMPTY = True

# 把「该模板 + 该页面无验证码」的结论持久化（captcha_absent.json），
# 下次登录同一模板/页面直接跳过查找。若之后服务端提示验证码错误，
# 会自动清掉该记录并重新完整查找，不会因缓存永久失效。
CAPTCHA_ABSENT_CACHE_ENABLED = True

# 通用元素发现兜底时，单个字段（用户名 / 密码）的查找耗时上限（秒）
GENERIC_DISCOVERY_BUDGET = 1.0

# 登录结果确认等待时间（Playwright 自动等待之外的业务等待）
LOGIN_RESULT_TIMEOUT = 12

APP_NAME = "批量自动化登录工具"

# ============ 统一版本来源 ============
# 项目当前发布版本。GUI 标题、关于窗口、打包 EXE 名称与文件版本资源
# 均从本处读取，避免多处维护导致版本不一致。
# 递增规则：正式发布按补丁号递增（6.0.6 -> 6.0.7 -> 6.0.8 ...），
# 详见根目录 CHANGELOG.md。开发/调试/重复打包不得修改本值。
APP_VERSION = "6.0.6"
APP_VERSION_INFO = (6, 0, 6, 2)

# 项目主页（开源仓库地址）：显示在「帮助 → 关于」中，方便用户找到源码、
# 文档与新版本。**纯展示用常量**，不参与任何逻辑判断。
PROJECT_URL = "https://github.com/jonathon1113/AutoLoginApp"


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
