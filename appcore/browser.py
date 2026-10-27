"""Playwright 浏览器管理层。

职责划分：
- BrowserService：持有 Playwright 实例（必须在自动化线程内创建/销毁）。
- BrowserSession：一个浏览器会话，对应原项目中的一个 Chrome 实例（一个分组一个窗口）。
- BrowserManager：会话注册表，负责创建 / 查询 / 关闭。
- BrowserHelper：元素定位与通用页面操作封装（Locator + 自动等待）。

会话隔离规则与原项目保持一致：
- 每个分组使用独立的 Browser + BrowserContext（独立 Cookie/缓存）。
- 同一分组内的多台设备使用同一个 Browser 的多个标签页（Page）。
"""

import asyncio
import threading
import time

from playwright.async_api import (
    async_playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from .config import (
    BROWSER_LAUNCH_ARGS,
    BROWSER_START_MAXIMIZED,
    CAPTCHA_LOOKUP_BUDGET,
    CAPTCHA_QUICK_STABLE_ROUNDS,
    CAPTCHA_QUICK_WAIT_BUDGET,
    SELECTOR_FRAME_BUDGET,
    SELECTOR_LOOKUP_BUDGET,
    SELECTOR_LOOKUP_READY_BUDGET,
    SELECTOR_LOOKUP_SLOW_BUDGET,
    SELECTOR_SCAN_INTERVAL,
    SELECTOR_SLOW_MAX_ROUNDS,
    SELECTOR_STABLE_ROUNDS,
    TIMEOUT_CLICK,
    TIMEOUT_ELEMENT,
    TIMEOUT_FILL,
    TIMEOUT_HIDDEN_WAIT,
    TIMEOUT_PAGE,
    TIMEOUT_SELECTOR,
    TIMEOUT_SELECTOR_PROBE,
    TIMEOUT_VISIBLE,
)
from .logging_utils import Logger, log_exception
from .element_roles import (
    ROLE_BUTTON,
    ROLE_CAPTCHA,
    ROLE_PASSWORD,
    ROLE_USERNAME,
    format_role_diagnostics,
    inspect_element,
    inspect_role,
)
from .templates import (
    CAPTCHA_SELECTORS,
    PASSWORD_SELECTORS,
    TemplateManager,
    USERNAME_SELECTORS,
)

# 快捷登录专用会话名
QUICK_SESSION = "__quick__"


# ============ 选择器转换 ============
def _escape_attr(value):
    """转义属性选择器中的引号"""
    return str(value).replace('"', '\\"')


def to_locator(page, by, value):
    """把原 Selenium 选择器 (by, value) 转换为 Playwright Locator。

    支持：NAME / ID / XPATH / CLASS_NAME / CSS_SELECTOR / TAG_NAME / LINK_TEXT
    """
    if value is None:
        return None

    kind = (by or '').upper()
    val = _escape_attr(value)

    if kind == 'NAME':
        return page.locator(f'[name="{val}"]')
    if kind == 'ID':
        return page.locator(f'[id="{val}"]')
    if kind == 'CLASS_NAME':
        return page.locator(f'[class~="{val}"]')
    if kind == 'XPATH':
        return page.locator(f'xpath={value}')
    if kind in ('CSS_SELECTOR', 'CSS'):
        return page.locator(str(value))
    if kind == 'TAG_NAME':
        return page.locator(str(value))
    if kind == 'LINK_TEXT':
        return page.get_by_text(str(value), exact=True)
    return None


# ============ Playwright 实例 ============
class BrowserService:
    """持有 Playwright 驱动实例（仅在自动化线程内使用）"""

    _playwright = None

    @classmethod
    async def get(cls):
        """获取（必要时启动）Playwright 实例"""
        if cls._playwright is None:
            cls._playwright = await async_playwright().start()
        return cls._playwright

    @classmethod
    async def stop(cls):
        """停止 Playwright 实例并释放驱动进程"""
        if cls._playwright is not None:
            try:
                await cls._playwright.stop()
            except Exception as e:
                log_exception(e, "停止 Playwright")
            finally:
                cls._playwright = None


# ============ 浏览器会话 ============
class BrowserSession:
    """一个浏览器会话（一个 Browser + 一个 Context + 若干标签页）"""

    def __init__(self, name):
        self.name = name
        self.browser = None
        self.context = None
        self.pages = []
        self.current_index = 0
        # 窗口状态：normal / maximized
        # 启动参数 --start-maximized 会让窗口以最大化方式打开，
        # 因此初始状态与实际启动方式保持一致，避免界面状态显示错误。
        self.window_state = 'maximized' if BROWSER_START_MAXIMIZED else 'normal'

    @property
    def page(self):
        """当前标签页"""
        if not self.pages:
            return None
        if self.current_index >= len(self.pages):
            self.current_index = len(self.pages) - 1
        return self.pages[self.current_index]

    @property
    def page_count(self):
        return len(self.pages)

    async def open_page(self, url=None):
        """新建标签页并切换过去（等价于原 window.open + switch_to_last_tab）"""
        if self.context is None:
            return None
        page = await self.context.new_page()
        self.pages.append(page)
        self.current_index = len(self.pages) - 1
        if url:
            await navigate(page, url)
        return page

    async def switch_to(self, index):
        """切换到指定索引的标签页"""
        if 0 <= index < len(self.pages):
            self.current_index = index
            return self.pages[index]
        return None

    async def select_first_tab(self):
        """选中本实例的第一个可用标签页（并将其激活到前台）。

        「浏览器实例」= 一个 Chromium 窗口；「标签页」= 该窗口内的 Page。
        Playwright 的 Page 对象与用户看到的 Chromium 标签页是同一个对象，
        真正切换用户可见的标签页需要调用 bring_to_front()，
        仅修改 current_index 只能改变程序内部的「当前页」。

        规则：
        - 只处理本实例的标签页，不影响其它实例；
        - 按当前实际的标签页顺序取第一个未关闭的标签页；
        - 实例没有有效标签页时安全返回 None，不抛异常。
        """
        for index, page in enumerate(self.pages):
            if page is None:
                continue
            try:
                if page.is_closed():
                    continue
            except Exception:
                continue
            self.current_index = index
            try:
                await page.bring_to_front()
            except Exception as e:
                # 激活失败（窗口已最小化/浏览器断开等）不影响选中的结果
                log_exception(e, f"激活第一个标签页 {self.name}")
            return page
        return None

    async def set_window_state(self, state='maximized'):
        """设置浏览器窗口状态（maximized / normal）。

        使用 Chromium 的 CDP 接口调整窗口：
        - maximized：窗口最大化，页面视口随屏幕可用区域变大；
        - normal   ：还原为普通窗口（可随时再次最大化，不会进入无法退出的全屏）。

        返回 (是否成功, 说明文字)。
        """
        if self.context is None or not self.pages:
            return False, '没有可用的浏览器窗口'
        page = self.pages[0]
        try:
            if page.is_closed():
                return False, '标签页已关闭'
        except Exception:
            return False, '标签页状态未知'

        try:
            cdp = await self.context.new_cdp_session(page)
        except Exception as e:
            log_exception(e, "创建 CDP 会话")
            return False, '当前浏览器不支持窗口状态调整'

        try:
            info = await cdp.send('Browser.getWindowForTarget')
            window_id = info.get('windowId')
            if not window_id:
                return False, '未取得窗口句柄'
            await cdp.send('Browser.setWindowBounds', {
                'windowId': window_id,
                'bounds': {'windowState': state},
            })
            self.window_state = state
            return True, '已最大化' if state == 'maximized' else '已还原'
        except Exception as e:
            log_exception(e, f"设置窗口状态 {state}")
            return False, f'设置窗口状态失败: {e}'
        finally:
            try:
                await cdp.detach()
            except Exception:
                pass

    async def close(self):
        """关闭会话（关闭所有标签页 -> 关闭上下文 -> 关闭浏览器）"""
        for page in list(self.pages):
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass
        self.pages = []

        if self.context is not None:
            try:
                await self.context.close()
            except Exception as e:
                log_exception(e, f"关闭上下文 {self.name}")
            self.context = None

        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception as e:
                log_exception(e, f"关闭浏览器 {self.name}")
            self.browser = None


# ============ 会话管理 ============
class BrowserManager:
    """浏览器会话注册表"""

    _sessions = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, name):
        """获取会话"""
        with cls._lock:
            return cls._sessions.get(name)

    @classmethod
    def session_count(cls):
        """当前打开的会话数量（线程安全）"""
        with cls._lock:
            return len(cls._sessions)

    @classmethod
    def session_names(cls):
        """当前打开的会话名称（线程安全）"""
        with cls._lock:
            return list(cls._sessions.keys())

    @classmethod
    def is_valid(cls, session):
        """检查会话是否仍然可用"""
        if session is None or session.browser is None:
            return False
        try:
            if not session.browser.is_connected():
                return False
        except Exception:
            return False
        page = session.page
        if page is not None:
            try:
                if page.is_closed():
                    return False
            except Exception:
                return False
        return True

    @classmethod
    async def create(cls, name):
        """创建一个新的浏览器会话"""
        # 先关闭同名旧会话，避免资源泄漏
        await cls.close_group(name)

        playwright = await BrowserService.get()
        browser = await playwright.chromium.launch(
            headless=False,
            slow_mo=100,
            args=BROWSER_LAUNCH_ARGS,
        )
        # ignore_https_errors 等价于原 Selenium 的 --ignore-certificate-errors
        # no_viewport=True：关闭 Playwright 的固定视口模拟（默认 1280x720），
        #   让页面视口跟随真实窗口尺寸，窗口放大时页面内容随之自适应。
        context = await browser.new_context(ignore_https_errors=True,
                                            no_viewport=True)
        page = await context.new_page()

        session = BrowserSession(name)
        session.browser = browser
        session.context = context
        session.pages.append(page)

        with cls._lock:
            cls._sessions[name] = session

        Logger.info(f"创建浏览器实例: {name if name != QUICK_SESSION else '快捷登录'}")
        return session

    @classmethod
    async def create_and_navigate(cls, name, url):
        """创建浏览器会话并立即打开目标页面（避免出现空白页）"""
        session = await cls.create(name)
        if session is not None and session.page is not None:
            await navigate(session.page, url)
            Logger.info(f"创建浏览器并打开: {url}")
        return session

    @classmethod
    async def close_group(cls, name):
        """关闭指定会话"""
        with cls._lock:
            session = cls._sessions.pop(name, None)
        if session is not None:
            await session.close()
            Logger.info(f"关闭分组浏览器: {name}")
            return True
        return False

    @classmethod
    async def close_all(cls):
        """关闭全部会话"""
        with cls._lock:
            sessions = list(cls._sessions.values())
            cls._sessions.clear()
        for session in sessions:
            try:
                await session.close()
            except Exception as e:
                log_exception(e, f"关闭会话 {session.name}")
        Logger.info("关闭所有浏览器")


# ============ 页面通用操作 ============
async def navigate(page, url, timeout=None):
    """打开 URL（等待 DOM 就绪，不阻塞在 load 事件上）"""
    timeout = timeout or TIMEOUT_PAGE
    started = time.monotonic()
    Logger.info(f"页面开始导航：{url}")
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
        Logger.info(f"页面 DOM 就绪：{url}，"
                    f"耗时={int((time.monotonic() - started) * 1000)}ms")
    except PlaywrightTimeoutError:
        Logger.warning(f"页面加载超时(继续处理): {url}")
    except PlaywrightError as e:
        log_exception(e, f"打开页面 {url}")
        raise


async def wait_page_loaded(page, timeout=None, require_complete=True):
    """等待页面就绪。

    require_complete=True  : 等待 document.readyState === 'complete'（等价原实现）。
    require_complete=False : 仅等待 DOM 离开 loading 状态（可交互），
                             页面其余资源继续在后台加载。表单定位只需要 DOM 可用，
                             因此登录流程先用此模式，避免慢页面额外等待数秒。
    """
    timeout = timeout or TIMEOUT_PAGE
    script = ("document.readyState === 'complete'" if require_complete
              else "document.readyState !== 'loading'")
    try:
        await page.wait_for_function(script, timeout=timeout * 1000)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False


# 过于宽泛的选择器（可能匹配页面任意文本框）：等待其出现的收益很低，
# 因此只给极短的复查窗口，避免慢速候选拖慢整轮登录。
_BROAD_SELECTOR_MARKERS = ('*', '//input', '//button', 'text"]', 'type="text"',
                            "type='text'", 'contains(')


def _probe_window(by, value, probe_timeout):
    """根据选择器的精确程度决定“元素不存在时”的复查窗口。"""
    window = probe_timeout if probe_timeout is not None else TIMEOUT_SELECTOR_PROBE
    kind = (by or '').upper()
    if kind in ('ID', 'NAME'):
        # 精确属性选择器：值得给完整复查窗口
        return window
    text = str(value or '')
    if any(marker in text for marker in _BROAD_SELECTOR_MARKERS):
        return min(window, 0.15)
    return min(window, 0.3)


async def probe_locator(page, by, value, probe_timeout=None):
    """快速探测元素当前状态，避免对不存在的选择器做秒级等待。

    返回 (state, locator)：
      'found'   元素存在且当前可见
      'hidden'  元素存在但不可见（可能稍后才显示）
      'absent'  元素不存在（已在复查窗口内复查过一次）
      'invalid' 选择器非法或定位方式不受支持
    """
    if not value:
        return 'invalid', None

    try:
        locator = to_locator(page, by, value)
    except Exception:
        return 'invalid', None
    if locator is None:
        return 'invalid', None

    try:
        # count() 立即返回当前匹配数量，不等待
        count = await locator.count()
    except Exception:
        # CSS / XPath 语法非法时 Playwright 会在此抛错
        return 'invalid', None

    if not count:
        # 动态渲染页面可能稍后才出现，给一次极短的复查机会
        deadline = time.monotonic() + _probe_window(by, value, probe_timeout)
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            try:
                count = await locator.count()
            except Exception:
                return 'invalid', None
            if count:
                break
        if not count:
            return 'absent', None

    first = locator.first
    try:
        visible = await first.is_visible()
    except Exception:
        visible = False
    return ('found' if visible else 'hidden'), (first if visible else None)


async def wait_visible(page, by, value, timeout=None):
    """等待元素可见并返回 Locator（不可见时返回 None）"""
    timeout = timeout or TIMEOUT_ELEMENT
    locator = to_locator(page, by, value)
    if locator is None:
        return None
    try:
        first = locator.first
        await first.wait_for(state='visible', timeout=timeout * 1000)
        return first
    except PlaywrightTimeoutError:
        return None
    except Exception as e:
        log_exception(e, f"wait_visible: {by}={value}")
        return None


async def wait_visible_all(page, by, value, timeout=None):
    """等待元素可见，返回 (完整匹配集合, 匹配数量)。

    与 wait_visible 的区别：这里保留全部匹配元素，使角色校验可以判断
    “是否多匹配”并做消歧，避免直接对第一个匹配元素执行填写 / 点击。
    不可见时返回 (None, 0)。
    """
    timeout = timeout or TIMEOUT_ELEMENT
    locator = to_locator(page, by, value)
    if locator is None:
        return None, 0
    try:
        await locator.first.wait_for(state='visible', timeout=timeout * 1000)
    except PlaywrightTimeoutError:
        return None, 0
    except Exception as e:
        log_exception(e, f"wait_visible_all: {by}={value}")
        return None, 0
    try:
        count = await locator.count()
    except Exception:
        count = 1
    return locator, count


async def wait_element(page, by, value, timeout=None):
    """等待元素出现（不要求可见）"""
    timeout = timeout or TIMEOUT_ELEMENT
    locator = to_locator(page, by, value)
    if locator is None:
        return None
    try:
        first = locator.first
        await first.wait_for(state='attached', timeout=timeout * 1000)
        return first
    except PlaywrightTimeoutError:
        return None
    except Exception as e:
        log_exception(e, f"wait_element: {by}={value}")
        return None


async def wait_clickable(page, by, value, timeout=None):
    """等待元素可点击"""
    timeout = timeout or TIMEOUT_CLICK
    locator = to_locator(page, by, value)
    if locator is None:
        return None
    try:
        first = locator.first
        await first.wait_for(state='visible', timeout=timeout * 1000)
        return first
    except PlaywrightTimeoutError:
        return None
    except Exception as e:
        log_exception(e, f"wait_clickable: {by}={value}")
        return None


async def click(page, by, value, timeout=None):
    """点击元素"""
    element = await wait_clickable(page, by, value, timeout)
    if element is None:
        return False
    try:
        await element.click(timeout=(timeout or TIMEOUT_CLICK) * 1000)
        return True
    except Exception as e:
        log_exception(e, f"click element: {by}={value}")
        return False


async def _is_detached(target):
    """判断元素引用是否已脱离 DOM（页面重新渲染导致）。

    返回 True 表示「引用还在手上，但元素已经不是原来那个了」。

    注意：ElementHandle 已分离时，is_visible() 会安静地返回 False，
    若只依赖可见性判断，这类失败会被误报成 not_visible，
    从而错过「重新定位后重试」的机会。
    """
    if target is None:
        return False
    try:
        connected = await target.evaluate('el => !!(el && el.isConnected)')
    except Exception as e:
        message = str(e).lower()
        if 'not attached' in message or 'no longer attached' in message or \
                'detached' in message or 'target closed' in message or \
                'has been closed' in message:
            return True
        # Locator 解析不到元素时是超时异常，不代表引用失效
        return False
    return connected is False


async def _fill_with_timeout(locator, value):
    """带超时地填写文本。

    优先使用带 timeout 参数的接口（避免不可编辑元素把流程挂到默认超时），
    若当前 Locator 实现不支持 timeout 参数则退回普通调用。
    """
    try:
        await locator.fill(value, timeout=TIMEOUT_FILL * 1000)
    except TypeError:
        await locator.fill(value)


async def input_text_detailed(locator, text, clear_first=True):
    """安全输入文本，并返回失败原因（供登录引擎定位真实失败点）。

    返回 (ok, reason)：
      ok=True  填写成功
      ok=False 时 reason 为：
        element_none        元素为空
        not_editable        元素不可编辑（readonly / contenteditable=false）
        not_enabled         元素被禁用
        not_visible         元素当前不可见
        element_detached    元素引用已失效（页面重新渲染）
        fill_failed         fill 调用抛出其它异常
    """
    if locator is None:
        return False, 'element_none'
    if await _is_detached(locator):
        return False, 'element_detached'
    try:
        visible = True
        try:
            visible = bool(await locator.is_visible())
        except Exception:
            visible = True
        if not visible:
            return False, 'not_visible'
        try:
            enabled = bool(await locator.is_enabled())
        except Exception:
            enabled = True
        if not enabled:
            return False, 'not_enabled'
        try:
            readonly = await locator.get_attribute('readonly')
        except Exception:
            readonly = None
        # readonly 是布尔属性：存在时 get_attribute 返回空字符串，
        # 因此必须用「不为 None」判断，不能用真值判断（否则只读元素会被
        # 当成可编辑，fill 会一直重试到默认超时）。
        if readonly is not None:
            return False, 'not_editable'
        if clear_first:
            await _fill_with_timeout(locator, "")
        await _fill_with_timeout(locator, text)
        return True, ''
    except Exception as e:
        message = str(e).lower()
        if 'detached' in message or 'no longer attached' in message or \
                'not an element' in message or 'element is not attached' in message:
            log_exception(e, "input text")
            return False, 'element_detached'
        if 'not editable' in message or 'readonly' in message:
            log_exception(e, "input text")
            return False, 'not_editable'
        if 'disabled' in message:
            log_exception(e, "input text")
            return False, 'not_enabled'
        if 'not visible' in message or 'hidden' in message:
            log_exception(e, "input text")
            return False, 'not_visible'
        log_exception(e, "input text")
        return False, 'fill_failed'


async def input_text(locator, text, clear_first=True):
    """安全输入文本（等价于原 clear + send_keys）"""
    ok, _reason = await input_text_detailed(locator, text, clear_first=clear_first)
    return ok


async def iterate_locators(locator, limit=None):
    """遍历 Locator 集合，返回可见且可用的元素列表"""
    result = []
    try:
        count = await locator.count()
        if limit:
            count = min(count, limit)
        for i in range(count):
            item = locator.nth(i)
            try:
                if await item.is_visible() and await item.is_enabled():
                    result.append(item)
            except Exception:
                continue
    except Exception as e:
        log_exception(e, "iterate_locators")
    return result


async def get_attribute(locator, name, default=""):
    """读取元素属性"""
    try:
        value = await locator.get_attribute(name)
        return value if value is not None else default
    except Exception:
        return default


# ============ SSL 证书警告页 ============
async def handle_ssl(page):
    """处理 SSL 证书警告页面（Chromium 的 interstitial 页面）"""
    try:
        content = await page.content()
    except Exception:
        return False

    lowered = content.lower()
    if "您的连接不是私密连接" not in content and "your connection is not private" not in lowered:
        return False

    for text in ['高级', 'Advanced', '继续', 'Proceed']:
        try:
            button = page.get_by_text(text, exact=False).first
            if await button.is_visible(timeout=2000):
                await button.click(timeout=TIMEOUT_CLICK * 1000)
                await wait_page_loaded(page, 5)
                return True
        except Exception:
            continue
    return False


# ============ 表单元素查找 ============
# 候选查找过程中的状态（同时用于逐候选诊断日志）
STATE_FOUND = 'found'
STATE_HIDDEN = 'hidden'
STATE_ABSENT = 'absent'
STATE_INVALID = 'invalid'
STATE_ERROR = 'error'
STATE_EMPTY = 'empty'
STATE_NOT_EXECUTED = 'not_executed'
STATE_ROLE_MISMATCH = 'role_mismatch'
STATE_DUPLICATE = 'duplicate'

_STATE_LABEL = {
    STATE_FOUND: '命中',
    STATE_HIDDEN: '存在但不可见',
    STATE_ABSENT: '未命中',
    STATE_INVALID: '选择器语法无效',
    STATE_ERROR: '查询异常',
    STATE_EMPTY: '候选内容为空',
    STATE_NOT_EXECUTED: '未执行',
    STATE_ROLE_MISMATCH: '角色不符',
    STATE_DUPLICATE: '重复候选',
}

# 统计页面表单控件的脚本（一次 evaluate 即可判断表单是否已渲染）
_FORM_CONTROL_JS = "() => document.querySelectorAll('input, textarea, select').length"

# 读取页面就绪状态（区分「还在加载」与「已加载完成但表单尚未渲染」）
_READY_STATE_JS = "() => document.readyState"


async def get_page_ready_state(page):
    """返回页面就绪状态。

    complete     页面已完全加载（含全部子资源）
    interactive  DOM 已就绪，页面仍在加载剩余资源（异步渲染页面的典型状态）
    loading      仍在解析文档
    unavailable  页面不可访问（已关闭 / 导航失败 / 执行异常）
    """
    try:
        state = await page.evaluate(_READY_STATE_JS)
    except Exception:
        return 'unavailable'
    state = str(state or '').strip().lower()
    if state in ('complete', 'interactive', 'loading'):
        return state
    return 'unavailable'


async def quick_check_locator(page, by, value):
    """单次存在性检查：不等待、不复查。

    返回 (state, locator, count)：
      'found'   元素存在且当前可见
      'hidden'  元素存在但当前不可见
      'absent'  元素不存在
      'invalid' 选择器语法非法或定位方式不受支持
      'error'   查询过程出现其它异常

    注意：locator 返回的是**完整匹配集合**（不是 .first），
    count 为实际匹配数量。角色校验需要据此判断“是否多匹配”并做消歧，
    若这里只返回 .first，多匹配消歧会失效，查找引擎会对第一个匹配元素
    直接执行填写 / 点击。只需要单个元素时由调用方自行取 .first。
    """
    if not value:
        return STATE_INVALID, None, 0

    try:
        locator = to_locator(page, by, value)
    except Exception:
        return STATE_INVALID, None, 0
    if locator is None:
        return STATE_INVALID, None, 0

    try:
        count = await locator.count()
    except Exception as e:
        text = str(e).lower()
        if any(word in text for word in ('syntax', 'unexpected token',
                                         'invalid selector', 'not a valid')):
            return STATE_INVALID, None, 0
        log_exception(e, f"quick_check_locator: {by}={value}")
        return STATE_ERROR, None, 0

    if not count:
        return STATE_ABSENT, None, 0

    try:
        visible = await locator.first.is_visible()
    except Exception:
        visible = False
    return (STATE_FOUND if visible else STATE_HIDDEN), locator, count


async def count_form_controls(page):
    """统计页面（含子 frame）中的表单控件数量。"""
    total = 0
    try:
        total = int(await page.evaluate(_FORM_CONTROL_JS) or 0)
    except Exception:
        total = 0
    try:
        frames = [f for f in page.frames if f != page.main_frame]
    except Exception:
        frames = []
    for frame in frames:
        try:
            total += int(await frame.evaluate(_FORM_CONTROL_JS) or 0)
        except Exception:
            continue
    return total


def _role_diagnostics_text(role, count, verdict):
    """拼出角色校验失败的诊断文本（只含非敏感属性，不含任何表单值）。"""
    elements = format_role_diagnostics(verdict.get('elements') or [])
    return (f"目标角色={role or '未指定'} 匹配数={count} "
            f"拒绝原因={verdict.get('reason') or ''} "
            f"元素={elements or '未取到属性'}")


def _format_candidate_log(stage, entry):
    """把单个候选的诊断记录格式化为一行日志。"""
    parts = [
        "[选择器查找]",
        f"阶段={stage or 'unknown'}",
        f"候选={entry.get('index')}/{entry.get('total')}",
        f"selector={entry.get('by')}={entry.get('value')}",
        f"结果={_STATE_LABEL.get(entry.get('state'), entry.get('state'))}",
        f"耗时={entry.get('ms')}ms",
        f"剩余预算={entry.get('remaining_ms')}ms",
    ]
    if entry.get('note'):
        parts.append(f"说明={entry['note']}")
    if entry.get('role_diagnostics'):
        parts.append(f"角色诊断={entry['role_diagnostics']}")
    return ' '.join(parts)


async def _lookup_selectors(page, selectors, budget, log=None, stage='',
                            extra_budget=None, delayed_window=True,
                            role='', trusted=False):
    """候选选择器查找核心：快速扫描 + 可见性确认 + 延迟渲染窗口。

    阶段 A（快速扫描）：对每个候选做一次「不等待」的存在性检查（count()），
        命中可见元素立即返回；存在但不可见的转入阶段 B。
    阶段 B（可见性确认）：对已存在但不可见的元素做有限等待。
    阶段 C（延迟渲染窗口）：在剩余预算内轮询页面是否出现表单控件，
        出现后立即回到阶段 A/B 复查候选（覆盖 SPA 延迟渲染）。
    阶段 D（慢速页面扩展等待窗口）：基础预算耗尽仍未命中时，
        按页面就绪状态分级给予额外等待（默认关闭，由调用方显式开启）：
        - 页面仍在加载（loading / interactive）：给予完整扩展预算；
        - 页面已加载完成但仍无表单控件：给予较短的扩展预算（等 JS 渲染）；
        - 页面不可访问：不再等待。
        等待期间持续复查未命中的候选，控件一旦出现立即命中。

    与旧实现的关键差异：旧实现为「每个不存在的候选」单独付出一次
    数百毫秒的复查等待，18 个候选会把 2.5 秒预算在第 7 个候选处耗尽，
    剩余候选从未被执行。新实现中不存在的候选只消耗一次 count()
    （毫秒级），整份候选列表都能在预算内被真正执行。

    role 为目标元素角色（username / password / captcha / button）：
    「命中」之后还要做一次角色校验，角色不符的候选会被拒绝并继续尝试
    下一个候选，避免把登录按钮 / 密码框 / 验证码框当成用户名字段。
    trusted=True 表示候选来自用户模板的显式声明，此时密码角色可以放宽
    「缺少密码特征」的语义要求（兼容 type="text" 的密码框）。

    返回 dict：
      hit / field / by / value / reason / elapsed_ms
      total / unique_total / executed / completed / skipped
      not_executed / not_executed_error / hits / role_rejected
      entries           每个候选的诊断记录
      cost_by_state     各类候选的累计耗时
      budget_exhausted  预算是否被耗尽
      incomplete        是否属于「不完整查找」（存在未执行的候选）
      frames_checked / frame_not_checked
    """
    started = time.monotonic()
    total = len(selectors)
    entries = []
    entry_by_index = {}
    cost_by_state = {}
    executed = 0
    completed = 0
    skipped = 0
    retries = 0
    queries = 0
    role_rejected = 0
    duplicates = 0
    executed_indexes = set()
    hit = None
    hit_locator = None
    matched_hidden = False
    invalid_count = 0
    error_count = 0
    frames_checked = 0
    frame_error = False
    budget_exhausted = False
    pending = []   # 存在但不可见的候选 (index, by, value)
    absent = []    # 不存在的候选 (index, by, value)

    def remaining_ms():
        return max(0, int((budget - (time.monotonic() - started)) * 1000))

    def emit(entry):
        """只输出诊断日志，不新增候选记录"""
        if log:
            try:
                log(_format_candidate_log(stage, entry))
            except Exception:
                pass

    def record(entry):
        entries.append(entry)
        entry_by_index[entry['index']] = entry
        state = entry.get('state')
        cost_by_state[state] = cost_by_state.get(state, 0) + int(entry.get('ms') or 0)
        emit(entry)

    def note(index, text):
        entry = entry_by_index.get(index)
        if entry is not None:
            old = entry.get('note')
            entry['note'] = f"{old}；{text}" if old else text

    def mark_found(index, by, value, phase, ms):
        """把候选标记为命中，并补发一条明确的命中诊断日志"""
        entry = entry_by_index.get(index)
        if entry is None:
            return
        previous_state = entry.get('state')
        if previous_state and previous_state != STATE_FOUND:
            # 之前的耗时归到旧状态上，命中后从旧状态里扣除，避免分类耗时重复统计
            cost_by_state[previous_state] = max(
                0, cost_by_state.get(previous_state, 0) - int(entry.get('ms') or 0))
        entry['state'] = STATE_FOUND
        entry['phase'] = phase
        entry['ms'] = int(entry.get('ms') or 0) + int(ms or 0)
        cost_by_state[STATE_FOUND] = cost_by_state.get(STATE_FOUND, 0) + int(ms or 0)
        emit({'index': entry['index'], 'total': entry['total'],
              'by': by, 'value': value, 'state': STATE_FOUND,
              'ms': int(ms or 0), 'remaining_ms': remaining_ms(),
              'phase': phase, 'note': entry.get('note', '')})

    # ---------- 候选去重 ----------
    # 模板里可能存在重复的 (by, value)（例如同一属性被写成两条规则），
    # 重复候选只执行一次，并在诊断日志中显式标出，避免统计口径混乱。
    candidates = []
    seen_keys = set()
    for raw_index, selector in enumerate(selectors):
        if not isinstance(selector, dict):
            continue
        by = str(selector.get('by', '')).upper()
        value = selector.get('value', '')
        if not value:
            empty_entry = {
                'index': raw_index + 1, 'total': total, 'by': by, 'value': value,
                'state': STATE_EMPTY, 'ms': 0, 'remaining_ms': remaining_ms(),
                'phase': 'scan', 'note': '候选内容为空，已跳过',
            }
            entries.append(empty_entry)
            entry_by_index[empty_entry['index']] = empty_entry
            emit(empty_entry)
            continue
        key = (by, str(value).strip())
        if key in seen_keys:
            duplicates += 1
            duplicate_entry = {
                'index': raw_index + 1, 'total': total, 'by': by, 'value': value,
                'state': STATE_DUPLICATE, 'ms': 0, 'remaining_ms': remaining_ms(),
                'phase': 'dedupe', 'note': '与前面的候选重复，已去重不重复执行',
            }
            entries.append(duplicate_entry)
            entry_by_index[duplicate_entry['index']] = duplicate_entry
            emit(duplicate_entry)
            continue
        seen_keys.add(key)
        candidates.append((raw_index + 1, by, value))
    unique_total = len(candidates)

    async def check_role(locator, count, hint=''):
        """命中后做角色校验（未启用角色校验时直接通过）

        hint 为选择器原文，用于「type=text 的密码框」这类只能靠
        选择器声明来确认角色的场景。
        """
        if not role:
            return {'ok': True, 'field': locator.first if locator else None,
                    'verdict': 'accept', 'reason': '', 'detail': '', 'note': ''}
        return await inspect_role(locator, count, role, trusted=trusted, hint=hint)

    # ---------- 阶段 A：快速存在性扫描 ----------
    for position, (index, by, value) in enumerate(candidates):
        if (time.monotonic() - started) > budget:
            budget_exhausted = True
            for rest_index, rest_by, rest_value in candidates[position:]:
                skipped += 1
                record({'index': rest_index, 'total': total,
                        'by': rest_by, 'value': rest_value,
                        'state': STATE_NOT_EXECUTED, 'ms': 0,
                        'remaining_ms': remaining_ms(), 'phase': 'scan',
                        'note': '剩余预算不足以启动该候选'})
            break

        item_started = time.monotonic()
        state, locator, count = await quick_check_locator(page, by, value)
        queries += 1
        ms = int((time.monotonic() - item_started) * 1000)
        executed += 1
        completed += 1
        executed_indexes.add(index)
        entry = {'index': index, 'total': total, 'by': by, 'value': value,
                 'state': state, 'ms': ms, 'remaining_ms': remaining_ms(),
                 'phase': 'scan'}
        if state == STATE_FOUND:
            verdict = await check_role(locator, count, value)
            if not verdict.get('ok'):
                entry['state'] = STATE_ROLE_MISMATCH
                entry['note'] = ('角色校验未通过：'
                                 + (verdict.get('detail') or verdict.get('reason') or ''))
                # 记录非敏感的元素属性摘要与触发的规则，便于事后定位
                entry['role_diagnostics'] = _role_diagnostics_text(
                    role, count, verdict)
                record(entry)
                role_rejected += 1
                absent.append((index, by, value))
                continue
            entry['note'] = verdict.get('note') or ''
            record(entry)
            hit = (by, value)
            hit_locator = verdict.get('field') or locator
            break
        if state == STATE_HIDDEN:
            entry['note'] = '元素存在但当前不可见'
            record(entry)
            pending.append((index, by, value))
            matched_hidden = True
        elif state == STATE_ABSENT:
            record(entry)
            absent.append((index, by, value))
        elif state == STATE_INVALID:
            entry['note'] = '选择器语法无效'
            record(entry)
            invalid_count += 1
        else:
            entry['note'] = '查询过程异常'
            record(entry)
            error_count += 1

    # ---------- 阶段 B：可见性确认（元素存在但暂时不可见） ----------
    if hit is None and pending:
        for (index, by, value) in pending:
            left = budget - (time.monotonic() - started)
            if left <= 0:
                budget_exhausted = True
                break
            wait_for = max(0.1, min(TIMEOUT_HIDDEN_WAIT, left))
            field, field_count = await wait_visible_all(page, by, value,
                                                        timeout=wait_for)
            if field is not None:
                verdict = await check_role(field, field_count, value)
                if not verdict.get('ok'):
                    role_rejected += 1
                    note(index, '等待可见后角色校验未通过：'
                         + (verdict.get('detail') or verdict.get('reason') or ''))
                    entry = entry_by_index.get(index)
                    if entry is not None:
                        entry['role_diagnostics'] = _role_diagnostics_text(
                            role, field_count, verdict)
                    continue
                hit = (by, value)
                hit_locator = verdict.get('field') or field
                note(index, f'等待可见 {wait_for:.2f}s 后命中')
                mark_found(index, by, value, 'visible_wait', int(wait_for * 1000))
                break
            note(index, f'等待可见 {wait_for:.2f}s 后仍不可见')

    # ---------- 子 frame 覆盖（很多登录页把表单放在 iframe 中） ----------
    # 独立于主文档预算：主文档预算耗尽时也允许在 iframe 内做一次快速扫描。
    if hit is None:
        try:
            frames = [f for f in page.frames if f != page.main_frame]
        except Exception:
            frames = []
        for frame in frames:
            if (time.monotonic() - started) > budget + SELECTOR_FRAME_BUDGET:
                budget_exhausted = True
                frame_error = True
                break
            frames_checked += 1
            frame_url = ''
            try:
                frame_url = getattr(frame, 'url', '') or ''
            except Exception:
                frame_url = ''
            try:
                for index, by, value in candidates:
                    state, locator, count = await quick_check_locator(frame, by, value)
                    queries += 1
                    if index not in executed_indexes:
                        executed += 1
                        completed += 1
                        executed_indexes.add(index)
                    if state == STATE_FOUND:
                        verdict = await check_role(locator, count, value)
                        if not verdict.get('ok'):
                            role_rejected += 1
                            note(index, 'iframe 中角色校验未通过：'
                                 + (verdict.get('detail') or verdict.get('reason') or ''))
                            continue
                        hit = (by, value)
                        hit_locator = verdict.get('field') or locator
                        if index in entry_by_index:
                            # 复用阶段 A 的候选记录，避免同一个候选出现两条日志
                            note(index, f'在 iframe 中命中：{frame_url}')
                            mark_found(index, by, value, 'frame', 0)
                        else:
                            record({'index': index, 'total': total,
                                    'by': by, 'value': value,
                                    'state': STATE_FOUND, 'ms': 0,
                                    'remaining_ms': remaining_ms(), 'phase': 'frame',
                                    'note': f'在 iframe 中命中：{frame_url}'})
                        break
                    if state == STATE_ERROR:
                        frame_error = True
                if hit:
                    break
            except Exception:
                frame_error = True

    # ---------- 阶段 C：延迟渲染窗口（页面级共享预算） ----------
    if hit is None and delayed_window:
        last_controls = -1
        stable_rounds = 0     # 控件数量连续未变化的轮数（用于判定页面已渲染稳定）
        round_no = 0
        while True:
            left = budget - (time.monotonic() - started)
            if left <= 0:
                budget_exhausted = True
                break
            await asyncio.sleep(min(SELECTOR_SCAN_INTERVAL, left))
            left = budget - (time.monotonic() - started)
            if left <= 0:
                budget_exhausted = True
                break
            round_no += 1
            controls = await count_form_controls(page)
            # 控件数量连续未变化 → 页面已渲染稳定，后续只是空转
            if controls == last_controls:
                stable_rounds += 1
            else:
                stable_rounds = 0
            # 节流：控件数量未变化时不必每轮都复查全部候选
            if controls == last_controls and round_no % 4 != 0:
                continue
            last_controls = controls
            if not controls:
                continue

            # 页面已渲染出表单控件：复查此前未命中的候选
            for (index, by, value) in list(absent):
                left = budget - (time.monotonic() - started)
                if left <= 0:
                    budget_exhausted = True
                    break
                retries += 1
                queries += 1
                item_started = time.monotonic()
                state, locator, count = await quick_check_locator(page, by, value)
                if state == STATE_FOUND:
                    verdict = await check_role(locator, count, value)
                    if not verdict.get('ok'):
                        role_rejected += 1
                        note(index, '延迟渲染后角色校验未通过：'
                             + (verdict.get('detail') or verdict.get('reason') or ''))
                        continue
                    hit = (by, value)
                    hit_locator = verdict.get('field') or locator
                    note(index, '延迟渲染后命中')
                    mark_found(index, by, value, 'delayed',
                               int((time.monotonic() - item_started) * 1000))
                    break
                if state == STATE_HIDDEN:
                    matched_hidden = True
                    note(index, '延迟渲染后出现但仍不可见')
            if hit:
                break

            for (index, by, value) in list(pending):
                left = budget - (time.monotonic() - started)
                if left <= 0:
                    budget_exhausted = True
                    break
                field, field_count = await wait_visible_all(
                    page, by, value, timeout=min(0.2, left))
                if field is not None:
                    verdict = await check_role(field, field_count, value)
                    if not verdict.get('ok'):
                        role_rejected += 1
                        note(index, '延迟渲染后角色校验未通过：'
                             + (verdict.get('detail') or verdict.get('reason') or ''))
                        continue
                    hit = (by, value)
                    hit_locator = verdict.get('field') or field
                    note(index, '延迟渲染后变为可见')
                    mark_found(index, by, value, 'delayed_visible', 0)
                    break
            if hit:
                break

            # 页面已渲染稳定（表单控件数量连续多轮未变化）且候选仍不存在：
            # 说明该元素确实不在这个页面上，继续等待只是空转。
            # 提前结束本阶段；若确属慢速页面，仍可由阶段 D 的扩展等待接管。
            if stable_rounds >= SELECTOR_STABLE_ROUNDS:
                note_all = '页面已渲染稳定，候选确实不存在，提前结束延迟渲染窗口'
                for (index, _by, _value) in list(absent):
                    note(index, note_all)
                break

    # ---------- 阶段 D：慢速页面扩展等待窗口 ----------
    # 目的：避免把「页面加载慢 / 异步渲染」误判为「模板不匹配 / 页面不支持」。
    # 规则：
    # - 只在基础预算耗尽且仍未命中时启用（默认关闭，由调用方显式传入 extra_budget）；
    # - 按页面就绪状态分级：仍在加载 -> 完整扩展预算；已加载完成但无控件 -> 较短扩展预算；
    #   页面不可访问 -> 不等待，直接失败；
    # - 等待期间持续复查未命中的候选，表单控件出现即立即命中；
    # - 总耗时仍有上限（基础预算 + 扩展预算），不会无限等待。
    slow_wait_ms = 0
    slow_rounds = 0
    page_state = ''
    if hit is None and extra_budget and extra_budget > 0:
        page_state = await get_page_ready_state(page)
        if page_state == 'unavailable':
            wait_budget = 0.0
        elif page_state in ('loading', 'interactive'):
            wait_budget = float(extra_budget)
        else:
            wait_budget = min(float(extra_budget), SELECTOR_LOOKUP_READY_BUDGET)
        if wait_budget > 0:
            slow_started = time.monotonic()
            deadline = slow_started + wait_budget
            last_controls = -1
            round_no = 0
            while time.monotonic() < deadline and round_no < SELECTOR_SLOW_MAX_ROUNDS:
                await asyncio.sleep(min(SELECTOR_SCAN_INTERVAL,
                                        max(0.0, deadline - time.monotonic())))
                round_no += 1
                controls_now = await count_form_controls(page)
                if controls_now == last_controls and round_no % 2 != 0:
                    continue
                last_controls = controls_now
                if controls_now:
                    for (index, by, value) in list(absent):
                        state, locator, count = await quick_check_locator(page, by, value)
                        retries += 1
                        queries += 1
                        if state == STATE_FOUND:
                            verdict = await check_role(locator, count, value)
                            if not verdict.get('ok'):
                                role_rejected += 1
                                note(index, '慢速页面等待后角色校验未通过：'
                                     + (verdict.get('detail')
                                        or verdict.get('reason') or ''))
                                continue
                            hit = (by, value)
                            hit_locator = verdict.get('field') or locator
                            note(index, '慢速页面等待后命中')
                            mark_found(index, by, value, 'slow_ready', 0)
                            break
                    if hit:
                        break
                    for (index, by, value) in list(pending):
                        field, field_count = await wait_visible_all(
                            page, by, value, timeout=0.2)
                        if field is not None:
                            verdict = await check_role(field, field_count, value)
                            if not verdict.get('ok'):
                                role_rejected += 1
                                note(index, '慢速页面等待后角色校验未通过：'
                                     + (verdict.get('detail') or verdict.get('reason') or ''))
                                continue
                            hit = (by, value)
                            hit_locator = verdict.get('field') or field
                            note(index, '慢速页面等待后变为可见')
                            mark_found(index, by, value, 'slow_visible', 0)
                            break
                    if hit:
                        break
            slow_rounds = round_no
            slow_wait_ms = int((time.monotonic() - slow_started) * 1000)
            if hit:
                Logger.info(
                    f"[选择器查找] 阶段={stage or 'unknown'} 慢速页面等待后命中"
                    f"（页面状态={page_state}，额外等待={slow_wait_ms}ms，"
                    f"轮数={slow_rounds}）")
            else:
                Logger.warning(
                    f"[选择器查找] 阶段={stage or 'unknown'} 慢速页面等待结束仍未命中"
                    f"（页面状态={page_state}，额外等待={slow_wait_ms}ms，"
                    f"轮数={slow_rounds}）")
        else:
            Logger.warning(
                f"[选择器查找] 阶段={stage or 'unknown'} 页面不可访问"
                f"（page_state={page_state}），不再等待")

    # ---------- 失败原因分类 ----------
    controls = 0
    if hit is None:
        controls = await count_form_controls(page)
        if skipped > 0:
            reason = 'budget_exceeded'
        elif role_rejected and role_rejected >= executed:
            # 所有执行过的候选都因为角色不符被拒（如把登录按钮当用户名字段）
            reason = 'role_mismatch'
        elif matched_hidden:
            reason = 'element_not_visible'
        elif invalid_count and invalid_count == executed:
            reason = 'selector_invalid'
        elif error_count:
            reason = 'selector_error'
        elif controls <= 0 and frame_error:
            reason = 'frame_not_checked'
        elif controls <= 0:
            reason = 'page_not_ready'
        else:
            reason = 'selector_not_found'
    else:
        reason = 'ok'

    # ---------- 退出统计 ----------
    # 从未执行过的候选：命中提前退出时属于「因命中而未执行」，
    # 未命中时属于「因异常 / 页面未就绪而未执行」。
    never_executed = max(0, unique_total - len(executed_indexes) - skipped)
    if hit is not None:
        exit_reason = 'hit'
        not_executed = never_executed
        not_executed_error = 0
    else:
        exit_reason = 'budget_exceeded' if budget_exhausted else (
            'no_selectors' if unique_total == 0 else 'exhausted')
        not_executed = 0
        not_executed_error = never_executed

    # 不完整查找：按实际执行情况判断（存在未执行的候选即为不完整）
    incomplete = len(executed_indexes) < unique_total

    return {
        'hit': hit is not None,
        'field': hit_locator,
        'by': hit[0] if hit else '',
        'value': hit[1] if hit else '',
        'reason': reason,
        'exit_reason': exit_reason,
        'elapsed_ms': int((time.monotonic() - started) * 1000),
        'total': total,
        'unique_total': unique_total,
        'executed': executed,
        'completed': completed,
        'hits': 1 if hit is not None else 0,
        'skipped': skipped,
        'not_executed': not_executed,
        'not_executed_error': not_executed_error,
        'duplicates': duplicates,
        'role_rejected': role_rejected,
        'retries': retries,
        'queries': queries,
        'entries': entries,
        'cost_by_state': cost_by_state,
        'budget_exhausted': budget_exhausted,
        'incomplete': incomplete,
        'frames_checked': frames_checked,
        'frame_not_checked': bool(frame_error),
        'controls': controls,
        'slow_wait_ms': slow_wait_ms,
        'slow_rounds': slow_rounds,
        'page_state': page_state,
    }


async def find_by_selectors_detailed(page, selectors, selector_key, timeout=None,
                                     probe_timeout=None, budget=None, log=None,
                                     stage='', extra_budget=None,
                                     delayed_window=True, role='',
                                     trusted=False):
    """严格按给定的选择器列表查找元素（不执行任何通用回退）。

    按列表顺序逐个尝试，命中第一个即停止。为提速：先用 count() 快速确认
    元素是否存在，确认存在后才等待其可见；不存在的候选只消耗一次毫秒级
    的存在性检查（不再为每个候选单独付出数百毫秒的复查等待）。

    budget 为本轮查找的总耗时上限（秒），超过后不再启动新的候选，
    未执行的候选会逐个记录原因。

    extra_budget 为「慢速页面扩展等待预算」（秒），默认 0（不启用）。
    启用后：基础预算耗尽且仍未命中时，按页面就绪状态分级给予额外等待，
    用于避免把加载慢 / 异步渲染的页面误判为不支持（见 _lookup_selectors 阶段 D）。

    delayed_window 控制是否启用「延迟渲染窗口」（阶段 C）。
    默认 True；快速存在性检查场景可传 False 跳过该窗口，
    避免在候选确实不存在时白白等待。

    role 指定目标元素角色（username / password / captcha / button）。
    命中之后还要做一次角色校验：角色不符的候选会被拒绝，
    查找继续尝试下一个候选（不会把登录按钮当成用户名字段）。
    trusted=True 表示候选来自用户模板的显式声明。

    log 为可选的诊断日志回调（接收一行文本），用于输出逐候选诊断信息。

    返回 dict：
      hit          是否命中
      field        命中的 Locator（未命中时为 None）
      by / value   命中的选择器
      elapsed_ms   本次查找总耗时
      reason       未命中原因：no_selectors / selector_not_found /
                   element_not_visible / selector_invalid / selector_error /
                   budget_exceeded / page_not_ready / frame_not_checked
      tried        每个候选的诊断记录（by/value/state/ms/remaining_ms/phase）
      total        候选总数
      unique_total 去重后的候选数
      executed     实际开始执行的候选数
      completed    执行完成（得出结论）的候选数
      skipped      因预算不足而未执行的候选数
      not_executed 因命中提前退出而未执行的候选数
      cost_by_state 各类候选的累计耗时
      incomplete   存在未执行候选（不完整查找）
    """
    budget = SELECTOR_LOOKUP_BUDGET if budget is None else budget
    lookup = await _lookup_selectors(page, selectors, budget, log=log,
                                     stage=stage or selector_key,
                                     extra_budget=extra_budget,
                                     delayed_window=delayed_window,
                                     role=role, trusted=trusted)
    result = dict(lookup)
    result['tried'] = result['entries']
    if not selectors:
        result['reason'] = 'no_selectors'
        result['elapsed_ms'] = 0
        return result
    if result['hit']:
        TemplateManager.record_selector(selector_key, result['by'], result['value'])
    return result


async def find_by_selectors(page, selectors, selector_key, timeout=None):
    """按给定的选择器列表查找元素（不执行任何通用回退）。

    返回 Locator 或 None（模板内选择器全部失效）。保留本函数以兼容旧调用。
    """
    result = await find_by_selectors_detailed(page, selectors, selector_key, timeout=timeout)
    return result['field'] if result['hit'] else None


async def find_element_by_template(page, template, selector_key, timeout=None):
    """根据模板选择器查找元素，并记录成功使用的选择器。

    兼容入口：先按模板选择器查找，模板选择器全部失效时才回退到通用发现逻辑。
    新代码请直接使用 find_by_selectors() 以便区分「模板命中」与「通用回退」。
    """
    timeout = timeout or TIMEOUT_SELECTOR
    selectors = (template or {}).get(selector_key, [])

    field = await find_by_selectors(page, selectors, selector_key, timeout=timeout)
    if field is not None:
        return field

    # 模板选择器都失败，使用后备查找方式
    if selector_key == 'password_selectors':
        return await find_password_field(page)
    if selector_key == 'username_selectors':
        return await find_username_field(page)

    return None


async def find_login_button_by_selectors_detailed(page, selectors, timeout=None,
                                                  budget=None, log=None, stage=''):
    """按模板中的登录按钮选择器查找并点击按钮，返回结构化结果。

    返回 dict：
      hit          是否成功点击
      by / value   命中的选择器
      elapsed_ms   耗时
      reason       未命中原因：no_selectors / selector_not_found /
                   element_not_visible / element_not_enabled / selector_invalid /
                   selector_error / budget_exceeded / page_not_ready /
                   frame_not_checked / submit_failed
      skipped      因超出耗时预算而未尝试的候选数
      total / executed / completed / incomplete
    """
    budget = SELECTOR_LOOKUP_BUDGET if budget is None else budget
    timeout = timeout or TIMEOUT_SELECTOR

    if not selectors:
        return {'hit': False, 'by': '', 'value': '', 'elapsed_ms': 0,
                'reason': 'no_selectors', 'tried': [], 'skipped': 0,
                'field': None, 'total': 0, 'unique_total': 0, 'executed': 0,
                'completed': 0, 'hits': 0, 'not_executed': 0,
                'not_executed_error': 0, 'duplicates': 0, 'role_rejected': 0,
                'exit_reason': 'no_selectors', 'incomplete': False,
                'budget_exhausted': False}

    lookup = await _lookup_selectors(page, selectors, budget, log=log,
                                     stage=stage or 'login_button',
                                     role=ROLE_BUTTON)
    result = {
        'hit': False,
        'by': lookup['by'],
        'value': lookup['value'],
        'elapsed_ms': lookup['elapsed_ms'],
        'reason': lookup['reason'],
        'exit_reason': lookup['exit_reason'],
        'tried': lookup['entries'],
        'skipped': lookup['skipped'],
        'field': lookup['field'],
        'total': lookup['total'],
        'unique_total': lookup['unique_total'],
        'executed': lookup['executed'],
        'completed': lookup['completed'],
        'hits': lookup['hits'],
        'not_executed': lookup['not_executed'],
        'not_executed_error': lookup['not_executed_error'],
        'duplicates': lookup['duplicates'],
        'role_rejected': lookup['role_rejected'],
        'incomplete': lookup['incomplete'],
        'budget_exhausted': lookup['budget_exhausted'],
    }

    if not lookup['hit']:
        return result

    button = lookup['field']
    try:
        enabled = await button.is_enabled()
    except Exception:
        enabled = True
    if not enabled:
        result['reason'] = 'element_not_enabled'
        return result

    try:
        await button.click(timeout=timeout * 1000)
    except Exception as e:
        log_exception(e, f"find_login_button_by_selectors: {lookup['by']}={lookup['value']}")
        result['reason'] = 'submit_failed'
        return result

    result['hit'] = True
    result['reason'] = 'ok'
    TemplateManager.record_selector('login_button_selectors', lookup['by'], lookup['value'])
    return result


async def find_login_button_by_selectors(page, selectors, timeout=None):
    """按模板中的登录按钮选择器查找并点击按钮。

    返回 True 表示点击成功；False 表示模板选择器全部失效（调用方应回退到通用逻辑）。
    """
    result = await find_login_button_by_selectors_detailed(page, selectors, timeout=timeout)
    return result['hit']


async def find_password_field(page, budget=None):
    """查找密码输入框（通用发现逻辑，命中时记录实际生效的选择器）

    先按内置候选规则查找（与默认模板共用同一套规则），
    未命中时再走原有的启发式回退。
    budget 为本次通用发现的总耗时上限（秒），超过后立即放弃。
    """
    deadline = time.monotonic() + (1.5 if budget is None else budget)
    result = await find_by_selectors_detailed(
        page, list(PASSWORD_SELECTORS), 'password_selectors',
        budget=max(0.1, deadline - time.monotonic()),
        role=ROLE_PASSWORD)
    if result['hit']:
        return result['field']

    for by, sel in [('NAME', 'password'), ('NAME', 'pwd'),
                     ('ID', 'password'), ('ID', 'pwd'),
                     ('ID', 'platcontent')]:
        if time.monotonic() > deadline:
            return None
        state, locator = await probe_locator(page, by, sel, TIMEOUT_SELECTOR_PROBE)
        if state == 'found':
            TemplateManager.record_selector('password_selectors', by, sel)
            return locator
        if state == 'hidden':
            field = await wait_visible(page, by, sel, timeout=TIMEOUT_VISIBLE)
            if field is not None:
                TemplateManager.record_selector('password_selectors', by, sel)
                return field

    # CSS 选择器
    css = "input[type='password']"
    for field in await iterate_locators(page.locator(css)):
        TemplateManager.record_selector('password_selectors', 'CSS_SELECTOR', css)
        return field

    # 遍历 input 标签（部分站点用样式伪装密码框）
    inputs = await iterate_locators(page.locator('input'))
    for inp in inputs:
        style = (await get_attribute(inp, 'style')).lower()
        if 'webkit-text-security' in style:
            return inp
        cls = (await get_attribute(inp, 'class')).lower()
        if 'qinput' in cls or 'q-input' in cls:
            ph = (await get_attribute(inp, 'placeholder')).lower()
            if '密码' in ph or 'pwd' in ph:
                return inp

    return None


async def find_username_field(page, budget=None):
    """查找用户名输入框（通用发现逻辑，命中时记录实际生效的选择器）

    先按内置候选规则查找（与默认模板共用同一套规则），
    未命中时再走原有的启发式回退。
    budget 为本次通用发现的总耗时上限（秒），超过后立即放弃。
    """
    deadline = time.monotonic() + (1.5 if budget is None else budget)

    # 去掉最后的宽泛兜底（//input[@type='text']）：它不唯一，
    # 命中后不应被当成可保存的模板选择器。
    candidates = [s for s in USERNAME_SELECTORS
                  if not (s.get('by') == 'XPATH'
                          and s.get('value') == "//input[@type='text']")]
    result = await find_by_selectors_detailed(
        page, candidates, 'username_selectors',
        budget=max(0.1, deadline - time.monotonic()),
        role=ROLE_USERNAME)
    if result['hit']:
        return result['field']

    for by, sel in [('NAME', 'username'), ('NAME', 'user'),
                     ('NAME', 'name'), ('ID', 'username'), ('ID', 'user')]:
        if time.monotonic() > deadline:
            return None
        state, locator = await probe_locator(page, by, sel, TIMEOUT_SELECTOR_PROBE)
        if state == 'found':
            TemplateManager.record_selector('username_selectors', by, sel)
            return locator
        if state == 'hidden':
            field = await wait_visible(page, by, sel, timeout=TIMEOUT_VISIBLE)
            if field is not None:
                TemplateManager.record_selector('username_selectors', by, sel)
                return field

    inputs = await iterate_locators(page.locator('input'))

    # 通过 placeholder 查找
    for inp in inputs:
        ph = (await get_attribute(inp, 'placeholder')).lower()
        inp_type = (await get_attribute(inp, 'type', 'text')) or 'text'
        if inp_type == 'text' and any(k in ph for k in
                                      ['邮箱', '账号', '手机', 'user', 'account', '用户名']):
            placeholder = await get_attribute(inp, 'placeholder')
            if placeholder:
                css = f"input[placeholder='{placeholder}']"
                TemplateManager.record_selector('username_selectors', 'CSS_SELECTOR', css)
            return inp

    # 其他查找方式
    for inp in inputs:
        cls = (await get_attribute(inp, 'class')).lower()
        ph = (await get_attribute(inp, 'placeholder')).lower()
        if 'q-input' in cls or 'qinput' in cls:
            return inp
        if '用户名' in ph:
            placeholder = await get_attribute(inp, 'placeholder')
            if placeholder:
                css = f"input[placeholder='{placeholder}']"
                TemplateManager.record_selector('username_selectors', 'CSS_SELECTOR', css)
            return inp

    # 第一个可见的 text 类型 input（不唯一，不记录为模板选择器）
    for inp in inputs:
        inp_type = (await get_attribute(inp, 'type', 'text')) or 'text'
        if inp_type == 'text':
            verdict = await inspect_element(inp, ROLE_USERNAME)
            if verdict.get('ok'):
                return inp

    return None


# 验证码输入框的强特征关键词（命中即认定为验证码框）
_CAPTCHA_STRONG_KEYWORDS = (
    '验证码', '校验码', '图形码', '动态码', '短信码',
    'captcha', 'kapkey', 'validatecode', 'checkcode', 'verifycode',
    'securitycode', 'authcode',
)
# 弱特征关键词：需要配合「不是密码框」的条件才生效
_CAPTCHA_WEAK_KEYWORDS = ('code',)


def _looks_like_password_field(id_attr, name_attr, class_attr, placeholder):
    """判断某个输入框是否更像密码框（用于验证码消歧）"""
    haystack = ' '.join([id_attr or '', name_attr or '', class_attr or '',
                         placeholder or '']).lower()
    if any(k in haystack for k in ('passwd', 'password', 'pwd', 'pass')):
        # 「密码」本身含「码」字，不能被验证码弱特征命中
        if not any(k in haystack for k in ('验证码', '校验码', '图形码')):
            return True
    return False


def _looks_like_username_field(id_attr, name_attr, class_attr, placeholder):
    """判断某个输入框是否更像用户名框（用于验证码消歧）"""
    haystack = ' '.join([id_attr or '', name_attr or '', class_attr or '',
                         placeholder or '']).lower()
    if any(k in haystack for k in ('username', 'userid', 'user_name', 'loginname',
                                  'login_name', '账号', '帐号', '用户名', '邮箱', 'email')):
        return True
    return False


async def _input_signature(locator):
    """取输入框的特征签名（用于排除已确认的用户名/密码框）。

    只读取属性，不修改页面 DOM。
    """
    try:
        return await locator.evaluate(
            "el => [el.tagName || '', el.id || '', el.name || '',"
            " el.getAttribute('class') || '', el.getAttribute('placeholder') || '',"
            " el.getAttribute('type') || ''].join('|')")
    except Exception:
        return ''


async def find_captcha_field_detailed(page, selectors=None, budget=None, log=None,
                                       extra_budget=None, exclude_fields=None,
                                       delayed_window=True):
    """查找验证码输入框（模板优先 -> 内置规则 -> 关键词启发式）。

    约束：
    - 只定位，不填写、不点击验证码；
    - 命中后记录选择器（供模板保存）；
    - 未命中时给出明确原因与逐候选诊断信息；
    - 不会把用户名 / 密码输入框误判为验证码框
      （exclude_fields 中已确认的字段会被排除）；
    - extra_budget 为慢速页面的扩展等待预算（秒），默认不启用；
    - delayed_window=False 时不再额外开启「延迟渲染窗口」，
      等待完全由扩展预算（阶段 D）接管，避免两段等待叠加。

    返回 dict：hit / field / by / value / reason / source / entries
    """
    budget = CAPTCHA_LOOKUP_BUDGET if budget is None else budget
    # 扩展等待预算在「模板候选」与「内置候选」两轮之间共享。
    # 旧实现里两轮各自获得一份完整的 extra_budget，等待时间成倍累加
    # （慢速页面上实测 2 轮 × 3 秒 ≈ 6~10 秒）；现在第二轮只能使用
    # 第一轮没用完的部分，整个验证码检查的扩展等待被 pool 统一封顶。
    pool = float(extra_budget or 0)
    used_extra = 0.0

    # 已确认的用户名/密码框：记录特征签名，避免被误判为验证码框
    excluded = set()
    for field in (exclude_fields or []):
        signature = await _input_signature(field)
        if signature:
            excluded.add(signature)

    # 1) 模板中的验证码选择器优先
    if selectors:
        result = await find_by_selectors_detailed(
            page, list(selectors), 'captcha_selectors', budget=budget,
            log=log, stage='captcha_lookup', extra_budget=pool,
            delayed_window=delayed_window, role=ROLE_CAPTCHA)
        if result['hit']:
            return {'hit': True, 'field': result['field'], 'by': result['by'],
                    'value': result['value'], 'reason': 'ok', 'source': 'template',
                    'entries': result.get('entries', [])}
        used_extra = float(result.get('slow_wait_ms', 0) or 0) / 1000.0

    # 2) 内置验证码候选规则（只使用剩余的扩展等待预算）
    result = await find_by_selectors_detailed(
        page, list(CAPTCHA_SELECTORS), 'captcha_selectors', budget=budget,
        log=log, stage='captcha_lookup', extra_budget=max(0.0, pool - used_extra),
        delayed_window=delayed_window, role=ROLE_CAPTCHA)
    if result['hit']:
        return {'hit': True, 'field': result['field'], 'by': result['by'],
                'value': result['value'], 'reason': 'ok', 'source': 'builtin',
                'entries': result.get('entries', [])}

    # 3) 关键词启发式（排除密码框 / 用户名框 / 已确认的字段）
    keyword_hit = await _captcha_keyword_probe(page, excluded)
    if keyword_hit:
        return keyword_hit

    return {'hit': False, 'field': None, 'by': '', 'value': '',
            'reason': 'captcha_not_found', 'source': '', 'entries': []}


async def _captcha_keyword_probe(page, excluded):
    """关键词启发式：从页面的 input 中识别验证码输入框。

    excluded 为已确认字段（用户名框 / 密码框）的特征签名集合，
    用于避免把用户名框、密码框误判为验证码框。

    命中返回 dict，未命中返回 None。只读取属性，不修改页面 DOM。
    """
    try:
        for inp in await iterate_locators(page.locator('input')):
            placeholder = (await get_attribute(inp, 'placeholder')).lower()
            name_attr = (await get_attribute(inp, 'name')).lower()
            id_attr = (await get_attribute(inp, 'id')).lower()
            class_attr = (await get_attribute(inp, 'class')).lower()
            haystack = ' '.join([placeholder, name_attr, id_attr, class_attr])

            if await _input_signature(inp) in excluded:
                continue

            if any(k.lower() in haystack for k in _CAPTCHA_STRONG_KEYWORDS):
                TemplateManager.record_selector('captcha_selectors', 'CSS_SELECTOR',
                                                f"input[placeholder='{placeholder}']"
                                                if placeholder else 'input')
                return {'hit': True, 'field': inp, 'by': 'CSS_SELECTOR',
                        'value': f"input[placeholder='{placeholder}']"
                        if placeholder else 'input',
                        'reason': 'ok', 'source': 'keyword', 'entries': []}

            if _looks_like_password_field(id_attr, name_attr, class_attr, placeholder):
                continue
            if _looks_like_username_field(id_attr, name_attr, class_attr, placeholder):
                continue
            if any(k in haystack for k in _CAPTCHA_WEAK_KEYWORDS):
                TemplateManager.record_selector('captcha_selectors', 'CSS_SELECTOR',
                                                f"input[placeholder='{placeholder}']"
                                                if placeholder else 'input')
                return {'hit': True, 'field': inp, 'by': 'CSS_SELECTOR',
                        'value': f"input[placeholder='{placeholder}']"
                        if placeholder else 'input',
                        'reason': 'ok', 'source': 'keyword', 'entries': []}
    except Exception as e:
        log_exception(e, "find_captcha_field: 遍历输入框")
    return None


async def find_captcha_field_quick(page, selectors=None, budget=None, log=None,
                                   exclude_fields=None, wait_budget=None,
                                   stable_rounds=None):
    """验证码输入框的快速存在性检查（用于正常登录流程）。

    与 find_captcha_field_detailed 的区别：

    - 不启用慢速页面的扩展等待（extra_budget=0）。正常页面只做候选的
      存在性检查（毫秒级），不会为了确认「没有验证码」而白白等待数秒；
    - 未命中时，只在「页面表单控件数量仍在变化」（页面还在渲染、
      验证码框可能马上出现）时，才在有上限的短窗口内继续复查；
      控件数量连续多轮稳定（stable_rounds）才立即返回，避免把慢渲染页面
      误判为「无验证码」而错误提交登录；
    - 慢速页面（页面未就绪）请继续使用
      find_captcha_field_detailed(extra_budget=...)，
      本函数只负责「页面已就绪且可交互」时的快速判定。

    返回 dict：hit / field / by / value / reason / source / entries /
              elapsed_ms / wait_rounds / controls_changed
    """
    started = time.monotonic()
    budget = SELECTOR_LOOKUP_BUDGET if budget is None else budget
    wait_budget = CAPTCHA_QUICK_WAIT_BUDGET if wait_budget is None else wait_budget
    stable_rounds = (CAPTCHA_QUICK_STABLE_ROUNDS if stable_rounds is None
                     else max(1, int(stable_rounds)))
    deadline = started + max(0.0, float(wait_budget))

    # 已确认的用户名/密码框：记录特征签名，避免被误判为验证码框
    excluded = set()
    for field in (exclude_fields or []):
        signature = await _input_signature(field)
        if signature:
            excluded.add(signature)

    async def probe():
        """非阻塞地探测一轮候选（不触发慢速页面扩展等待与延迟渲染窗口）。"""
        if selectors:
            result = await find_by_selectors_detailed(
                page, list(selectors), 'captcha_selectors', budget=budget,
                log=log, stage='captcha_lookup', extra_budget=0,
                delayed_window=False, role=ROLE_CAPTCHA)
            if result['hit']:
                return {'hit': True, 'field': result['field'], 'by': result['by'],
                        'value': result['value'], 'reason': 'ok',
                        'source': 'template',
                        'entries': result.get('entries', [])}

        result = await find_by_selectors_detailed(
            page, list(CAPTCHA_SELECTORS), 'captcha_selectors', budget=budget,
            log=log, stage='captcha_lookup', extra_budget=0,
            delayed_window=False, role=ROLE_CAPTCHA)
        if result['hit']:
            return {'hit': True, 'field': result['field'], 'by': result['by'],
                    'value': result['value'], 'reason': 'ok',
                    'source': 'builtin',
                    'entries': result.get('entries', [])}

        return await _captcha_keyword_probe(page, excluded)

    controls_before = await count_form_controls(page)
    hit = await probe()
    if hit:
        hit['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        hit['wait_rounds'] = 0
        hit['controls_changed'] = False
        return hit

    # 未命中：只有页面仍在渲染（表单控件数量持续变化）才短暂等待
    wait_rounds = 0
    controls_changed = False
    last_controls = controls_before
    while time.monotonic() < deadline and wait_rounds < SELECTOR_SLOW_MAX_ROUNDS:
        await asyncio.sleep(min(SELECTOR_SCAN_INTERVAL,
                                max(0.0, deadline - time.monotonic())))
        wait_rounds += 1
        controls_now = await count_form_controls(page)
        if controls_now == last_controls:
            # 页面控件数量稳定 → 确认没有验证码框，立即返回
            break
        controls_changed = True
        last_controls = controls_now
        hit = await probe()
        if hit:
            break

    if hit:
        hit['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        hit['wait_rounds'] = wait_rounds
        hit['controls_changed'] = controls_changed
        return hit

    return {'hit': False, 'field': None, 'by': '', 'value': '',
            'reason': 'captcha_not_found', 'source': '', 'entries': [],
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'wait_rounds': wait_rounds, 'controls_changed': controls_changed}


async def find_captcha_field(page):
    """查找验证码输入框（兼容入口，只返回 Locator）"""
    result = await find_captcha_field_detailed(page)
    return result['field'] if result['hit'] else None


async def click_login_button_detailed(page, pwd_field, selectors=None, log=None):
    """点击登录按钮（模板优先），返回 (是否点击成功, 详细信息)。

    详细信息包含按钮来源（template / generic / enter）、命中的选择器与耗时，
    供登录引擎记录可核验的日志。
    """
    started = time.monotonic()
    info = {'source': '', 'by': '', 'value': '', 'elapsed_ms': 0, 'reason': ''}

    if selectors:
        result = await find_login_button_by_selectors_detailed(page, selectors, log=log)
        info['by'] = result['by']
        info['value'] = result['value']
        info['reason'] = result['reason']
        if result['hit']:
            info['source'] = 'template'
            info['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            return True, info
        Logger.warning("模板中的登录按钮选择器全部失效，回退到通用登录按钮查找")

    for by, sel in [('XPATH', "//button[contains(., '登录')]"),
                     ('CLASS_NAME', 'submit-button'),
                     ('NAME', 'submit'),
                     ('XPATH', "//button[@type='submit']")]:
        state, locator = await probe_locator(page, by, sel, TIMEOUT_SELECTOR_PROBE)
        if state != 'found':
            continue
        try:
            if not await locator.is_enabled():
                continue
            await locator.click(timeout=TIMEOUT_CLICK * 1000)
            TemplateManager.record_selector('login_button_selectors', by, sel)
            info['source'] = 'generic'
            info['by'] = by
            info['value'] = sel
            info['reason'] = 'ok'
            info['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            return True, info
        except Exception:
            continue

    # 任意包含"登录"文字的按钮
    try:
        for btn in await iterate_locators(page.locator('button')):
            text = (await btn.inner_text()) or ""
            if '登录' in text or '登陆' in text:
                await btn.click(timeout=TIMEOUT_CLICK * 1000)
                info['source'] = 'generic'
                info['by'] = 'TEXT'
                info['value'] = '登录'
                info['reason'] = 'ok'
                info['elapsed_ms'] = int((time.monotonic() - started) * 1000)
                return True, info
    except Exception as e:
        log_exception(e, "click_login_button: 遍历按钮")

    # ExtJS 等框架的登录按钮是 <a class="x-btn">Login</a>（不是 button 元素）
    for xpath in ("//a[contains(@class, 'x-btn') and contains(., 'Login')]",
                  "//a[contains(@class, 'x-btn') and contains(., '登录')]"):
        state, locator = await probe_locator(page, 'XPATH', xpath,
                                             TIMEOUT_SELECTOR_PROBE)
        if state != 'found':
            continue
        try:
            await locator.click(timeout=TIMEOUT_CLICK * 1000)
            TemplateManager.record_selector('login_button_selectors', 'XPATH', xpath)
            info['source'] = 'generic'
            info['by'] = 'XPATH'
            info['value'] = xpath
            info['reason'] = 'ok'
            info['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            return True, info
        except Exception:
            continue

    # 回车提交
    try:
        if pwd_field is not None:
            await pwd_field.press('Enter', timeout=TIMEOUT_CLICK * 1000)
            info['source'] = 'enter'
            info['reason'] = 'ok'
            info['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            return True, info
    except Exception:
        pass

    info['reason'] = 'login_button_not_found'
    info['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    return False, info


async def click_login_button(page, pwd_field, selectors=None):
    """点击登录按钮。

    selectors 不为空时优先按模板中的登录按钮选择器查找（模板优先）；
    模板选择器全部失效后才执行通用发现逻辑。
    """
    clicked, _info = await click_login_button_detailed(page, pwd_field, selectors)
    return clicked


async def safe_close_page(page):
    """安全关闭标签页"""
    try:
        if page is not None and not page.is_closed():
            await page.close()
    except Exception:
        pass
