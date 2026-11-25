"""登录引擎：单设备登录、分组批量登录、快捷登录。

与原项目的差异（均为向 Playwright 迁移所必需或提升正确性）：
- 固定延时（time.sleep）全部替换为 Playwright 自动等待 / 状态等待。
- 登录结果由真实页面状态判定（原实现为"点击登录即视为成功"）。
"""

import asyncio
import threading
import time

from . import config as app_config
from . import devices as device_store
from .browser import (
    QUICK_SESSION,
    BrowserManager,
    captcha_image_fingerprint,
    capture_captcha_image,
    click_login_button_detailed,
    find_by_selectors_detailed,
    find_captcha_field_detailed,
    find_captcha_field_quick,
    find_captcha_image,
    find_password_field,
    find_username_field,
    get_page_ready_state,
    handle_ssl,
    input_text,
    input_text_detailed,
    navigate,
    probe_locator,
    wait_page_loaded,
)
from . import captcha_cache
from .captcha_ocr import recognizer
from .config import (GENERIC_DISCOVERY_BUDGET, LOGIN_RESULT_TIMEOUT,
                     SELECTOR_LOOKUP_BUDGET, SELECTOR_LOOKUP_READY_BUDGET,
                     SELECTOR_LOOKUP_SLOW_BUDGET, TEMPLATE_ATTEMPT_BUDGET)
from .element_roles import (ROLE_BUTTON, ROLE_CAPTCHA, ROLE_PASSWORD,
                             ROLE_USERNAME)
from .logging_utils import Logger, log_exception
from .templates import (DEFAULT_TEMPLATE, LOGIN_BUTTON_SELECTORS, PASSWORD_SELECTORS,
                         TemplateManager, USERNAME_SELECTORS)

# 明确的登录失败提示关键词（仅在页面上可见时才会被采纳）
ERROR_KEYWORDS = [
    '密码错误', '登陆失败', '登录失败', '用户名或密码', '账号密码错误', '用户不存在',
    '验证失败', '认证失败', 'login failed', 'incorrect password', 'wrong password',
    'invalid credentials', 'invalid username', 'access denied', 'authentication failed',
]

# 明确的「验证码错误」提示关键词。
# 只有这些提示才允许自动刷新重试；出现账号 / 密码错误时必须立即停止，
# 防止连续错误导致账号被锁定。
CAPTCHA_ERROR_KEYWORDS = [
    '验证码错误', '验证码不正确', '验证码有误', '验证码已失效', '验证码已过期',
    '验证码无效', '校验码错误', '图形码错误', '请重新输入验证码', '验证码不匹配',
    '验证码验证失败', 'invalid captcha', 'incorrect captcha', 'captcha is invalid',
    'captcha error', 'wrong captcha',
    # 会话/CSRF 失效：刷新验证码后重试即可（不区分大小写时会被归为验证码错误）
    '页面已过期',
]

# 验证码刷新链接上可能出现的文字
CAPTCHA_REFRESH_LINK_KEYWORDS = [
    '换一张', '刷新', '看不清', '点击刷新', '重新获取', '获取验证码',
    '换验证码', '重新加载',
]

# 登录成功的页面特征（用于「表单提交后 URL 不变」的站点）
SUCCESS_KEYWORDS = [
    '欢迎', '登录成功', '登陆成功', '退出登录', '退出登陆', '注销',
    'welcome', 'logout', 'sign out', 'signed in',
]

# 提示框类容器（优先在这些容器中查找错误信息，避免误判正文）
ALERT_SELECTORS = [
    '[class*="error"]', '[class*="alert"]', '[class*="message"]',
    '[class*="toast"]', '[class*="tips"]', '[class*="tip"]', '[role="alert"]',
]

# ============ 登录失败分类（写入日志，便于定位真实原因）============
FAIL_USERNAME_NOT_FOUND = 'username_selector_not_found'
FAIL_PASSWORD_NOT_FOUND = 'password_selector_not_found'
FAIL_BUTTON_NOT_FOUND = 'login_button_not_found'
FAIL_SELECTOR_INVALID = 'selector_invalid'
FAIL_ELEMENT_NOT_VISIBLE = 'element_not_visible'
FAIL_FORM_NOT_FOUND = 'form_not_found'
FAIL_FORM_FILL = 'form_fill_failed'
FAIL_SUBMIT = 'submit_failed'
FAIL_AUTH_REJECTED = 'authentication_rejected'
FAIL_CAPTCHA = 'captcha_required'
FAIL_UNKNOWN = 'unknown_login_failure'
# 查找阶段的细分失败原因（不得统一归为 form_not_found）
FAIL_BUDGET_EXCEEDED = 'budget_exceeded'
FAIL_PAGE_NOT_READY = 'page_not_ready'
FAIL_FRAME_NOT_CHECKED = 'frame_not_checked'
FAIL_SELECTOR_ERROR = 'selector_error'
# 选择器命中了元素，但元素角色与目标字段不符（如把登录按钮当成用户名字段）
FAIL_ROLE_MISMATCH = 'role_mismatch'

# 失败阶段
STAGE_USERNAME = 'username_lookup'
STAGE_PASSWORD = 'password_lookup'
STAGE_FILL = 'form_fill'
STAGE_BUTTON = 'login_button'
STAGE_RESULT = 'login_result'

# 这些原因属于「表单定位失败」，尚未向服务器提交，可用默认模板重试一次；
# 认证类失败（密码错误/验证码）重试无意义且可能造成副作用，一律不重试。
RETRYABLE_REASONS = {
    FAIL_USERNAME_NOT_FOUND, FAIL_PASSWORD_NOT_FOUND, FAIL_BUTTON_NOT_FOUND,
    FAIL_SELECTOR_INVALID, FAIL_ELEMENT_NOT_VISIBLE, FAIL_FORM_NOT_FOUND,
    FAIL_BUDGET_EXCEEDED, FAIL_PAGE_NOT_READY, FAIL_FRAME_NOT_CHECKED,
    FAIL_SELECTOR_ERROR, FAIL_ROLE_MISMATCH,
}


async def _detect_error_by_keywords(page, keywords):
    """在页面上查找包含指定关键词的可见提示文本，返回文本或 None。

    先查提示框类容器（避免误判正文），再查页面正文。
    """
    if not keywords:
        return None
    # 1) 优先检查提示框类元素
    try:
        for selector in ALERT_SELECTORS:
            locator = page.locator(selector)
            count = await locator.count()
            for i in range(min(count, 10)):
                item = locator.nth(i)
                try:
                    if not await item.is_visible():
                        continue
                    text = (await item.inner_text()).strip()
                except Exception:
                    continue
                if not text:
                    continue
                for keyword in keywords:
                    if keyword.lower() in text.lower():
                        return text.replace('\n', ' ')[:60]
    except Exception:
        pass

    # 2) 再检查页面正文
    try:
        body_text = await page.locator('body').inner_text(timeout=3000)
    except Exception:
        return None
    for keyword in keywords:
        if keyword.lower() in body_text.lower():
            for line in body_text.splitlines():
                if keyword.lower() in line.lower():
                    return line.strip()[:60]
    return None


async def _detect_login_error(page):
    """检测页面上可见的登录失败提示，返回提示文本或 None"""
    return await _detect_error_by_keywords(page, ERROR_KEYWORDS)


async def _detect_login_success(page):
    """检测页面上是否已出现「登录成功」的特征（URL 不变也能判定成功）。"""
    try:
        body_text = await page.locator('body').inner_text(timeout=2000)
    except Exception:
        return None
    if not body_text:
        return None
    lowered = body_text.lower()
    for keyword in SUCCESS_KEYWORDS:
        if keyword.lower() in lowered:
            for line in body_text.splitlines():
                if keyword.lower() in line.lower():
                    return line.strip()[:60]
    return None


async def _detect_captcha_error(page):
    """检测页面上可见的「验证码错误」提示，返回提示文本或 None。

    只有这里识别到的提示才允许「刷新验证码后重试」；
    账号 / 密码错误必须立即停止。
    """
    return await _detect_error_by_keywords(page, CAPTCHA_ERROR_KEYWORDS)


async def _looks_logged_in(page, target_url):
    """判断页面是否已经不是登录页（已登录检测）"""
    # 0) 页面已出现「欢迎 / 退出登录」等成功特征 -> 直接判定已登录。
    #    必须放在 URL 判断之前：很多站点的登录页地址本身含 "login"
    #    （如 captcha_login.php），登录成功后 URL 不变，只看 URL 会误判。
    try:
        if await _detect_login_success(page):
            return True
    except Exception:
        pass
    # 页面仍然存在密码输入框 -> 仍停留在登录表单上，不算已登录
    try:
        state, _locator = await probe_locator(page, 'CSS_SELECTOR',
                                              "input[type='password']", 0.2)
        if state in ('found', 'hidden'):
            return False
    except Exception:
        pass

    try:
        title = (await page.title()) or ""
    except Exception:
        title = ""

    try:
        current_url = (page.url or "").lower()
    except Exception:
        current_url = ""

    login_keywords = ["登录", "登陆", "login", "sign in", "signin"]
    title_lower = title.lower()

    # 地址仍属于登录类页面 -> 不算已登录（表单缺失时应报“Form not found”）
    if any(kw in current_url for kw in login_keywords):
        return False

    if title and not any(kw in title_lower for kw in login_keywords):
        return True

    if target_url and target_url.lower() not in current_url and current_url != 'about:blank':
        return True

    return False


async def _wait_login_result(page, pwd_field, original_url, timeout=None,
                              detectors=None):
    """等待并判定登录结果。

    返回 (confirmed, message)：
    - confirmed=True  表示登录已确认（表单消失或页面已跳转）
    - confirmed=False 且 message 含错误提示，表示登录明确失败
    - confirmed=False 且 message 为"未确认"，表示超时且表单仍存在

    timeout   等待上限（秒），默认 LOGIN_RESULT_TIMEOUT
    detectors 错误提示检测器列表（按顺序检查），默认只查登录失败提示。
              验证码模式会传入 [_detect_captcha_error, _detect_login_error]，
              保证「验证码错误」优先于「账号密码错误」被识别。
    """
    deadline = time.monotonic() + (LOGIN_RESULT_TIMEOUT if timeout is None
                                    else float(timeout))
    checks = list(detectors) if detectors else [_detect_login_error]

    while time.monotonic() < deadline:
        # 先看是否已经出现成功特征（覆盖「表单提交后 URL 不变」的站点）
        try:
            success_hint = await _detect_login_success(page)
            if success_hint:
                return True, "登录成功"
        except Exception:
            pass
        for detect in checks:
            error = await detect(page)
            if error:
                return False, error

        if pwd_field is not None:
            try:
                if not await pwd_field.is_visible():
                    return True, "登录成功"
            except Exception:
                # 页面已跳走，定位器失效，视为登录成功
                return True, "登录成功"

        try:
            if page.url != original_url:
                return True, "登录成功"
        except Exception:
            return True, "登录成功"

        await asyncio.sleep(0.4)

    return False, "未确认登录结果(登录表单仍存在)"


async def _wait_captcha_result(page, pwd_field, original_url, timeout=None):
    """验证码模式下的结果等待。

    超时使用 CAPTCHA_RESULT_TIMEOUT（默认 6 秒），比普通登录短，
    避免批量登录被验证码流程拖慢。
    """
    return await _wait_login_result(
        page, pwd_field, original_url,
        timeout=(app_config.CAPTCHA_RESULT_TIMEOUT if timeout is None
                 else timeout),
        detectors=[_detect_captcha_error, _detect_login_error])


# ============ 登录上下文与模板解析 ============
# 登录入口标识：所有入口共用同一套日志逻辑，避免不同入口字段不一致
ENTRY_SINGLE = '单设备登录'
ENTRY_GROUP = '分组批量登录'
ENTRY_QUICK = '快捷登录'
ENTRY_TEMPLATE = '生成模板'

_task_counter = 0
_task_lock = threading.Lock()


def _next_task_id():
    """生成全局递增的登录任务ID（用于把同一次登录的多条日志串联起来）"""
    global _task_counter
    with _task_lock:
        _task_counter += 1
        return f"L{_task_counter}"


class LoginContext:
    """一次登录任务的上下文（设备名称 / 登录入口 / 任务ID）。

    - 所有登录入口共用同一套日志格式；
    - 任务ID用于把同一次登录的各阶段日志关联起来，多设备并发时可正确区分。
    """

    __slots__ = ('device', 'entry', 'task_id')

    def __init__(self, device, entry, task_id=None):
        self.device = device
        self.entry = entry
        self.task_id = task_id or _next_task_id()

    def log(self, message):
        """给日志消息加上设备与任务标识"""
        return f"设备={self.device} 任务={self.task_id}：{message}"


def _safe_selector(by, value, limit=60):
    """选择器摘要（截断，避免日志过长；不含任何密码内容）"""
    text = f"{by}={value}" if by else str(value)
    if len(text) > limit:
        text = text[:limit] + '...'
    return text


def _template_counts(template):
    """返回模板中三类选择器的数量"""
    t = template or {}
    return (len(t.get('username_selectors', []) or []),
            len(t.get('password_selectors', []) or []),
            len(t.get('login_button_selectors', []) or []))


def _get_default_template():
    """获取默认模板。

    优先使用磁盘上的 templates/default.json（用户可维护），
    磁盘不存在时才使用内置常量，并返回实际文件路径。
    """
    template = TemplateManager.get_template('default')
    path = TemplateManager.get_template_source('default')
    if template is None:
        return DEFAULT_TEMPLATE, '内置默认模板'
    return template, path or '内置默认模板'


def _resolve_template(ctx, template_name):
    """根据设备配置解析本次登录要使用的模板。

    返回 dict（严格区分「配置的模板」与「实际加载的模板」）：
    - config_name   设备配置中的模板名（去空白后的原始值）
    - name          实际解析出来、将要执行的模板名
    - source        模板来源：'设备模板' / '默认模板' / '内置默认模板'
    - path          实际读取的模板文件绝对路径（未读取成功时为空）
    - template      模板数据
    - loaded        是否按配置成功加载到模板
    - failed_name   加载失败时的配置模板名
    - failed_path   加载失败时的模板文件路径（文件存在但无法加载时非空）
    - reason        未按配置加载时的原因说明
    """
    config_name = str(template_name or '').strip()

    if not config_name or config_name.lower() == 'default':
        template, path = _get_default_template()
        return {
            'config_name': config_name,
            'name': 'default',
            'source': '默认模板',
            'path': path,
            'template': template,
            'loaded': True,
            'failed_name': '',
            'failed_path': '',
            'reason': '',
        }

    state = TemplateManager.inspect_template(config_name)
    if state['loadable']:
        return {
            'config_name': config_name,
            'name': state['name'],
            'source': '设备模板',
            'path': state['path'],
            'template': state['template'],
            'loaded': True,
            'failed_name': '',
            'failed_path': '',
            'reason': '',
        }

    # 配置的模板没能加载：记录具体原因（区分“不存在”与“文件损坏”），改用默认模板
    template, path = _get_default_template()
    return {
        'config_name': config_name,
        'name': 'default',
        'source': '默认模板',
        'path': path,
        'template': template,
        'loaded': False,
        'failed_name': config_name,
        'failed_path': state.get('path', ''),
        'reason': state.get('reason', '模板不存在或未通过校验'),
    }


def _final_template_label(outcome):
    """取出本次登录最终使用的模板名（用于界面结果行与提示文案）"""
    return outcome.get('final_template_name') or '-'


def _result_text(outcome):
    """把一次尝试的结果转换为可读结论（成功 / 失败 / 无法确认）"""
    if outcome.get('ok'):
        return '登录成功'
    detail = str(outcome.get('detail', '') or '')
    if '未确认' in detail:
        return f"无法确认登录结果（{detail}）"
    return f"登录失败（原因={outcome.get('reason', '')}）"


def _log_login_summary(ctx, summary):
    """输出统一格式的登录汇总日志。

    一条日志即可看清：配置了什么模板、实际执行了哪个模板、是否发生回退、
    最终结果是什么、各阶段耗时多少。
    """
    executed = summary.get('executed_names') or []
    if isinstance(executed, str):
        executed = [executed]
    executed_name = ' -> '.join([str(x) for x in executed if x]) or '(无)'

    fields = [
        ('设备', ctx.device),
        ('任务', ctx.task_id),
        ('入口', ctx.entry),
        ('配置模板', summary.get('config_name') or '(未指定)'),
        ('实际执行模板', executed_name),
        ('模板文件', summary.get('executed_path') or '(无)'),
        ('设备模板执行', summary.get('device_result') or '未执行'),
        ('默认模板回退', summary.get('fallback') or '否'),
        ('默认模板执行', summary.get('default_result') or '未执行'),
    ]
    if summary.get('fallback_path'):
        fields.append(('回退模板文件', summary['fallback_path']))
    if summary.get('fallback_reason'):
        fields.append(('回退原因', summary['fallback_reason']))
    if summary.get('failed_path'):
        fields.append(('失败模板文件', summary['failed_path']))
    fields.extend([
        ('最终结果', summary.get('result') or '未知'),
        ('最终使用模板', summary.get('final_name') or '(无)'),
        ('最终模板文件', summary.get('final_path') or '(无)'),
        ('模板查找耗时', f"{summary.get('resolve_ms', 0)}ms"),
        ('表单填写耗时', f"{summary.get('fill_ms', 0)}ms"),
        ('按钮操作耗时', f"{summary.get('button_ms', 0)}ms"),
        ('总耗时', f"{summary.get('total_ms', 0)}ms"),
    ])

    message = "[LOGIN_SUMMARY]\n" + '\n'.join([f"{k}={v}" for k, v in fields])
    if summary.get('success'):
        Logger.success(message)
    elif summary.get('result', '').startswith('无法确认'):
        Logger.warning(message)
    else:
        Logger.error(message)
    return message


def _describe_failure(kind, result):
    """把选择器查找结果转换为 (阶段, 原因分类, 中文说明)

    失败原因不得统一归为 form_not_found：预算耗尽 / 页面未就绪 /
    未覆盖 iframe / 选择器异常均有各自的分类。
    """
    stage = STAGE_USERNAME if kind == 'username' else STAGE_PASSWORD
    reason = FAIL_USERNAME_NOT_FOUND if kind == 'username' else FAIL_PASSWORD_NOT_FOUND
    label = '用户名' if kind == 'username' else '密码'

    state = result.get('reason')
    total = result.get('total', 0)
    executed = result.get('executed', 0)
    skipped = result.get('skipped', 0)
    incomplete = result.get('incomplete')

    if state == 'no_selectors':
        return stage, FAIL_FORM_NOT_FOUND, f"Form not found：{label}选择器未配置"
    if state == 'budget_exceeded':
        return (stage, FAIL_BUDGET_EXCEEDED,
                f"Form not found：{label}查找超出耗时预算，"
                f"已执行 {executed}/{total} 个候选，剩余 {skipped} 个候选未执行")
    if state == 'element_not_visible':
        return (stage, FAIL_ELEMENT_NOT_VISIBLE,
                f"Form not found：{label}元素存在但不可见"
                f"（已执行 {executed}/{total} 个候选）")
    if state == 'selector_invalid':
        return (stage, FAIL_SELECTOR_INVALID,
                f"Form not found：{label}选择器语法无效"
                f"（已执行 {executed}/{total} 个候选）")
    if state == 'selector_error':
        return (stage, FAIL_SELECTOR_ERROR,
                f"Form not found：{label}选择器查询异常"
                f"（已执行 {executed}/{total} 个候选）")
    if state == 'role_mismatch':
        rejected = result.get('role_rejected', 0)
        return (stage, FAIL_ROLE_MISMATCH,
                f"Form not found：{label}选择器命中了 {rejected} 个元素，"
                f"但元素角色与目标字段不符（如把登录按钮 / 密码框当成{label}框）"
                f"（已执行 {executed}/{total} 个候选）")
    if state == 'page_not_ready':
        return (stage, FAIL_PAGE_NOT_READY,
                f"Form not found：页面尚未渲染出{label}输入框"
                f"（已执行 {executed}/{total} 个候选）")
    if state == 'frame_not_checked':
        return (stage, FAIL_FRAME_NOT_CHECKED,
                f"Form not found：页面存在 iframe 但未能覆盖其内部"
                f"（已执行 {executed}/{total} 个候选）")
    suffix = "，本次为不完整查找（延迟渲染窗口用尽预算）" if incomplete else ""
    return (stage, reason,
            f"Form not found：所有{label}选择器均未命中"
            f"（已执行 {executed}/{total} 个候选）{suffix}")


# 填写失败的真实原因（不得统一笼统归为「填写失败」）
_FILL_FAILURE_TEXT = {
    'element_none': '未定位到可填写的元素',
    'not_visible': '元素当前不可见',
    'not_enabled': '元素处于禁用状态',
    'not_editable': '元素不可编辑（readonly）',
    'element_detached': '元素引用已失效（页面重新渲染），重新定位后仍未成功',
    'fill_failed': '填写动作抛出异常',
}


def _describe_fill_failure(label, reason):
    """把填写失败原因转换为可读说明（保留真实原因）"""
    text = _FILL_FAILURE_TEXT.get(reason or '', '未知原因')
    return f'{label}输入失败：{text}'


def _is_auth_error(detail):
    """判断失败详情是否为服务端明确拒绝认证"""
    if not detail:
        return False
    text = detail.lower()
    return any(keyword.lower() in text for keyword in ERROR_KEYWORDS)


async def _still_on_login_page(page):
    """确认页面仍处于登录表单上（可安全地重新定位表单）"""
    try:
        url = (page.url or '').lower()
    except Exception:
        url = ''
    if any(key in url for key in ('login', 'signin', 'logon')):
        return True
    state, _locator = await probe_locator(page, 'CSS_SELECTOR',
                                          "input[type='password']", 0.2)
    return state in ('found', 'hidden')


def _log_lookup_summary(ctx, label, result, level='warning'):
    """输出查找阶段的汇总日志。

    必须区分：原始候选总数 / 去重后候选数 / 实际开始执行数 / 执行完成数 /
    命中数 / 因命中提前退出而未执行数 / 因预算不足未执行数 /
    因异常或页面未就绪未执行数 / 各类候选累计耗时 / 最终退出原因。
    """
    total = result.get('total', 0)
    unique_total = result.get('unique_total', total)
    executed = result.get('executed', 0)
    completed = result.get('completed', 0)
    hits = result.get('hits', 1 if result.get('hit') else 0)
    skipped = result.get('skipped', 0)
    not_executed = result.get('not_executed', 0)
    not_executed_error = result.get('not_executed_error', 0)
    duplicates = result.get('duplicates', 0)
    role_rejected = result.get('role_rejected', 0)
    exit_reason = result.get('exit_reason') or result.get('reason') or ''
    cost = result.get('cost_by_state') or {}
    cost_text = '，'.join(f"{state}={ms}ms" for state, ms in sorted(cost.items())) or '无'
    # 慢速页面等待的诊断信息（实际等待时间 / 复查轮数 / 页面就绪状态）
    slow_ms = int(result.get('slow_wait_ms', 0) or 0)
    slow_rounds = int(result.get('slow_rounds', 0) or 0)
    page_state = result.get('page_state', '') or ''
    slow_text = ''
    if slow_ms or slow_rounds:
        slow_text = (f"，慢速页面额外等待={slow_ms}ms，"
                     f"复查轮数={slow_rounds}，页面状态={page_state or '未检测'}")
    dedupe_text = f"，重复候选={duplicates}" if duplicates else ""
    role_text = f"，角色不符被拒={role_rejected}" if role_rejected else ""
    message = ctx.log(
        f"[选择器查找汇总] {label}：原始候选总数={total}，"
        f"去重后候选数={unique_total}，实际开始执行={executed}，"
        f"执行完成={completed}，命中数={hits}，"
        f"因命中提前退出未执行={not_executed}，"
        f"因预算不足未执行={skipped}，"
        f"因异常或页面未就绪未执行={not_executed_error}{dedupe_text}{role_text}，"
        f"分类累计耗时={cost_text}，退出原因={exit_reason}，"
        f"不完整查找={'是' if result.get('incomplete') else '否'}{slow_text}")
    getattr(Logger, level)(message)


async def _locate_and_fill(page, template, label, ctx, username, password,
                            extra_budget=None):
    """用指定模板定位用户名/密码框并填写表单（不提交）。

    extra_budget 为「慢速页面扩展等待预算」（秒）：
    - None：使用配置中的 SELECTOR_LOOKUP_SLOW_BUDGET（默认行为）；
    - 0   ：不启用扩展等待（保持旧行为）。
    基础预算耗尽且仍未命中时，会按页面就绪状态分级给予额外等待，
    避免把「页面加载慢 / 异步渲染」误判为「模板不匹配 / 页面不支持」。

    返回 dict：ok / stage / reason / detail / user_field / pwd_field /
              elapsed_ms / locate_ms / fill_ms
    """
    started = time.monotonic()
    slow_budget = SELECTOR_LOOKUP_SLOW_BUDGET if extra_budget is None else extra_budget
    result = {'ok': False, 'stage': '', 'reason': '', 'detail': '',
              'user_field': None, 'pwd_field': None, 'elapsed_ms': 0,
              'locate_ms': 0, 'fill_ms': 0, 'slow_wait_ms': 0}

    def lookup_log(message):
        """逐候选诊断日志（带设备与任务标识）"""
        Logger.info(ctx.log(message))

    user_result = await find_by_selectors_detailed(
        page, template.get('username_selectors', []), 'username_selectors',
        budget=SELECTOR_LOOKUP_BUDGET, log=lookup_log, stage=STAGE_USERNAME,
        extra_budget=slow_budget, role=ROLE_USERNAME, trusted=True)
    if user_result['hit']:
        Logger.info(ctx.log(f"{label}用户名选择器命中，"
                            f"selector={_safe_selector(user_result['by'], user_result['value'])}，"
                            f"耗时={user_result['elapsed_ms']}ms"))
        _log_lookup_summary(ctx, f"{label}用户名", user_result, level='info')
    else:
        stage, reason, detail = _describe_failure('username', user_result)
        Logger.warning(ctx.log(f"{label}用户名选择器未命中（{detail}），"
                               f"耗时={user_result['elapsed_ms']}ms"))
        _log_lookup_summary(ctx, f"{label}用户名", user_result)
        result.update(stage=stage, reason=reason, detail=detail,
                      elapsed_ms=int((time.monotonic() - started) * 1000),
                      locate_ms=int((time.monotonic() - started) * 1000))
        return result

    # 密码查找沿用「剩余」的慢速预算，避免单个设备累计等待过长
    used_slow = float(user_result.get('slow_wait_ms', 0) or 0) / 1000.0
    pwd_result = await find_by_selectors_detailed(
        page, template.get('password_selectors', []), 'password_selectors',
        budget=SELECTOR_LOOKUP_BUDGET, log=lookup_log, stage=STAGE_PASSWORD,
        extra_budget=max(0.0, slow_budget - used_slow),
        role=ROLE_PASSWORD, trusted=True)
    if pwd_result['hit']:
        Logger.info(ctx.log(f"{label}密码选择器命中，"
                            f"selector={_safe_selector(pwd_result['by'], pwd_result['value'])}，"
                            f"耗时={pwd_result['elapsed_ms']}ms"))
        _log_lookup_summary(ctx, f"{label}密码", pwd_result, level='info')
    else:
        stage, reason, detail = _describe_failure('password', pwd_result)
        Logger.warning(ctx.log(f"{label}密码选择器未命中（{detail}），"
                               f"耗时={pwd_result['elapsed_ms']}ms"))
        _log_lookup_summary(ctx, f"{label}密码", pwd_result)
        result.update(stage=stage, reason=reason, detail=detail,
                      elapsed_ms=int((time.monotonic() - started) * 1000),
                      locate_ms=int((time.monotonic() - started) * 1000))
        return result

    locate_ms = int((time.monotonic() - started) * 1000)
    fill_started = time.monotonic()

    # ---- 用户名填写 ----
    user_field = user_result['field']
    filled, fill_reason = await input_text_detailed(user_field, username)
    if not filled and fill_reason == 'element_detached':
        # 页面重新渲染导致元素引用失效：重新定位一次再填
        Logger.warning(ctx.log(
            f"{label}用户名元素引用已失效（页面重新渲染），重新定位后重试"))
        retry = await find_by_selectors_detailed(
            page, template.get('username_selectors', []), 'username_selectors',
            budget=SELECTOR_LOOKUP_BUDGET, log=lookup_log, stage=STAGE_USERNAME,
            extra_budget=0, role=ROLE_USERNAME, trusted=True)
        if retry['hit']:
            user_field = retry['field']
            filled, fill_reason = await input_text_detailed(user_field, username)
    if not filled:
        detail = _describe_fill_failure('用户名', fill_reason)
        Logger.warning(ctx.log(f"{label}{detail}"))
        result.update(stage=STAGE_FILL, reason=FAIL_FORM_FILL, detail=detail,
                      elapsed_ms=int((time.monotonic() - started) * 1000),
                      locate_ms=locate_ms)
        return result

    # ---- 密码填写 ----
    pwd_field = pwd_result['field']
    filled, fill_reason = await input_text_detailed(pwd_field, password)
    if not filled and fill_reason == 'element_detached':
        Logger.warning(ctx.log(
            f"{label}密码元素引用已失效（页面重新渲染），重新定位后重试"))
        retry = await find_by_selectors_detailed(
            page, template.get('password_selectors', []), 'password_selectors',
            budget=SELECTOR_LOOKUP_BUDGET, log=lookup_log, stage=STAGE_PASSWORD,
            extra_budget=0, role=ROLE_PASSWORD, trusted=True)
        if retry['hit']:
            pwd_field = retry['field']
            filled, fill_reason = await input_text_detailed(pwd_field, password)
    if not filled:
        detail = _describe_fill_failure('密码', fill_reason)
        Logger.warning(ctx.log(f"{label}{detail}"))
        result.update(stage=STAGE_FILL, reason=FAIL_FORM_FILL, detail=detail,
                      elapsed_ms=int((time.monotonic() - started) * 1000),
                      locate_ms=locate_ms)
        return result

    fill_ms = int((time.monotonic() - fill_started) * 1000)
    Logger.info(ctx.log(f"{label}表单填充完成，耗时={fill_ms}ms"))
    result.update(ok=True, user_field=user_field,
                  pwd_field=pwd_field,
                  elapsed_ms=int((time.monotonic() - started) * 1000),
                  locate_ms=locate_ms, fill_ms=fill_ms,
                  slow_wait_ms=int(user_result.get('slow_wait_ms', 0) or 0)
                  + int(pwd_result.get('slow_wait_ms', 0) or 0))
    return result


async def _submit_login(page, template, label, ctx, pwd_field,
                        enter_field=None, method='auto'):
    """提交登录表单。返回 dict。

    method='auto'（默认）：优先在最后一个输入框里**按回车**提交。
        绝大多数站点（实测约 90%）在输入框按回车即可登录；
        而登录按钮有时是 <a> 或受 JS 事件约束，点击未必生效。
        回车若无反应，由调用方回退到点击登录按钮（method='button'）。
    method='enter'：只按回车。
    method='button'：只点击登录按钮（模板按钮选择器优先）。
    """
    result = {'ok': False, 'stage': STAGE_BUTTON, 'reason': '', 'detail': '',
              'original_url': '', 'button_ms': 0, 'method': ''}

    selectors = template.get('login_button_selectors', []) or []
    original_url = page.url

    if method in ('auto', 'enter') and enter_field is not None:
        enter_started = time.monotonic()
        try:
            await enter_field.press('Enter', timeout=3000)
            result['method'] = 'enter'
            result['button_ms'] = int((time.monotonic() - enter_started) * 1000)
            result.update(ok=True, original_url=original_url)
            Logger.info(ctx.log(f"{label}已用回车提交登录表单"))
            return result
        except Exception as e:
            Logger.info(ctx.log(
                f"{label}回车提交失败（{str(e)[:50]}），回退点击登录按钮"))
            result['method'] = ''

    button_started = time.monotonic()
    clicked, info = await click_login_button_detailed(
        page, pwd_field, selectors or None,
        log=lambda message: Logger.info(ctx.log(message)))
    button_ms = int((time.monotonic() - button_started) * 1000)
    if clicked:
        source = {'template': '模板', 'generic': '通用发现', 'enter': '回车提交'}.get(
            info.get('source'), info.get('source'))
        Logger.info(ctx.log(f"{label}登录按钮已点击"
                            f"（来源={source}，"
                            f"selector={_safe_selector(info.get('by'), info.get('value'))}），"
                            f"耗时={info.get('elapsed_ms')}ms"))
        result.update(ok=True, original_url=original_url, button_ms=button_ms,
                      method='button')
        return result

    Logger.warning(ctx.log(f"{label}未找到登录按钮"
                           f"（原因={info.get('reason')}），耗时={info.get('elapsed_ms')}ms"))
    result.update(reason=FAIL_BUTTON_NOT_FOUND, detail='所有登录按钮选择器均未命中',
                  button_ms=button_ms)
    return result


async def _click_refresh_link(page):
    """尝试点击「换一张 / 刷新 / 看不清」等刷新链接。返回是否点击成功。"""
    try:
        handle = await page.evaluate_handle(
            """(keywords) => {
                const nodes = document.querySelectorAll(
                    'a, span, div, button, i, em, label, td, li');
                for (const el of nodes) {
                    const text = (el.textContent || '').trim();
                    if (!text || text.length > 20) continue;
                    let matched = false;
                    for (const kw of keywords) {
                        if (text.indexOf(kw) >= 0) { matched = true; break; }
                    }
                    if (!matched) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    return el;
                }
                return null;
            }""", CAPTCHA_REFRESH_LINK_KEYWORDS)
    except Exception:
        return False
    try:
        element = handle.as_element() if handle is not None else None
        if element is None:
            return False
        await element.click(timeout=2000)
        return True
    except Exception:
        return False


async def _refresh_captcha(page, img, captcha, template=None, label='',
                           ctx=None, pwd_field=None):
    """刷新验证码图片，并重新定位验证码输入框。

    步骤：
    1. 点击验证码图片本身（多数站点点击图片即刷新）；
    2. 等待 CAPTCHA_REFRESH_WAIT；
    3. 重新截图与旧图比较；字节未变化时尝试点击「换一张 / 刷新 / 看不清」链接；
    4. 重新定位验证码输入框（页面可能已重绘）并清空。

    刷新失败不抛异常，只记录日志后继续下一轮。
    """
    log = ctx.log if ctx is not None else (lambda message: message)
    element = img.get('element') if isinstance(img, dict) else None
    previous = img.get('screenshot') if isinstance(img, dict) else None

    try:
        if element is not None:
            await element.scroll_into_view_if_needed(timeout=1000)
    except Exception:
        pass

    try:
        if element is not None:
            await element.click(timeout=2000)
            Logger.info(log(f"{label}已点击验证码图片，尝试刷新"))
    except Exception as e:
        Logger.info(log(f"{label}点击验证码图片未生效（{str(e)[:60]}）"))

    await asyncio.sleep(app_config.CAPTCHA_REFRESH_WAIT)

    # 校验图片是否真的刷新了：重新截图与旧图比较
    changed = True
    try:
        if element is not None:
            current = await element.screenshot(type='png', timeout=3000)
            changed = bool(previous is None or current != previous)
    except Exception:
        changed = True

    if not changed:
        if await _click_refresh_link(page):
            Logger.info(log(f"{label}已点击「换一张 / 刷新」链接"))
            await asyncio.sleep(app_config.CAPTCHA_REFRESH_WAIT)
        else:
            Logger.info(log(f"{label}未找到刷新链接，验证码图片可能未更新"))

    # 重新定位验证码输入框（页面可能已重绘），并清空内容
    if template is not None:
        try:
            found = await find_captcha_field_quick(
                page, template.get('captcha_selectors') or None,
                exclude_fields=[pwd_field] if pwd_field is not None else None)
            if found.get('hit'):
                captcha['field'] = found['field']
        except Exception:
            pass

    try:
        if captcha.get('field') is not None:
            await captcha['field'].fill('', timeout=2000)
    except Exception:
        pass


async def _diagnose_form(page):
    """收集页面上输入框的摘要，用于排查「找不到登录表单」。"""
    try:
        data = await page.evaluate("""() => {
            const items = [];
            const nodes = document.querySelectorAll(
                'input, textarea, [contenteditable="true"]');
            nodes.forEach((el, i) => {
                if (i >= 12) return;
                const visible = !!(el.offsetWidth || el.offsetHeight
                                   || el.getClientRects().length);
                items.push('type=' + (el.type || '') +
                           ' name=' + (el.name || '') +
                           ' id=' + (el.id || '') +
                           ' ph=' + (el.placeholder || '') +
                           ' vis=' + (visible ? '1' : '0'));
            });
            return {count: items.length, items: items,
                    frames: window.frames.length,
                    title: document.title, url: location.href};
        }""")
    except Exception:
        return ''
    if not isinstance(data, dict):
        return ''
    return ('inputs=%d frames=%d title=%s url=%s %s'
            % (data.get('count', 0), data.get('frames', 0),
               str(data.get('title', ''))[:30], str(data.get('url', ''))[:60],
               ' | '.join(data.get('items') or [])))[:400]


async def _ensure_credentials_filled(page, template, user_field, pwd_field,
                                     username, password, label, ctx):
    """确保用户名/密码已经正确写入（页面可能被清空或重绘）。

    有些站点在「验证码错误」后会把整个表单清空（账号密码一起没），
    也有站点在验证码框获得焦点时重置表单。因此每次提交前都重填一次并校验，
    填不进去时先重新定位字段再试一次。

    返回 (user_field, pwd_field, ok)。
    """
    pairs = (
        ('用户名', 'username_selectors', username),
        ('密码', 'password_selectors', password),
    )
    for name, selector_key, value in pairs:
        field = user_field if selector_key == 'username_selectors' else pwd_field
        ok, reason = ((await input_text_detailed(field, value))
                      if field is not None else (False, 'element_none'))
        if not ok:
            try:
                found = await find_by_selectors_detailed(
                    page, list(template.get(selector_key) or []), selector_key,
                    budget=SELECTOR_LOOKUP_BUDGET)
            except Exception:
                found = {}
            if found.get('hit'):
                field = found['field']
                ok, reason = await input_text_detailed(field, value)
        if selector_key == 'username_selectors':
            user_field = field
        else:
            pwd_field = field
        if not ok:
            Logger.warning(ctx.log(f"{label}重新填写{name}失败：{reason}"))
            return user_field, pwd_field, False
    return user_field, pwd_field, True


async def _activate_captcha_field(field, wait=0.8):
    """点击（聚焦）验证码输入框。

    有些站点在验证码输入框**获得焦点时就会刷新验证码**（例如 H3C 网络设备
    WebUI：点击 #vldcode 会把验证码图片的 src 换成带时间戳的新地址）。
    必须先触发这次刷新、再截图识别，否则识别到的是旧码，提交必然失败。
    """
    if field is None:
        return
    try:
        await field.click(timeout=2000)
    except Exception:
        pass
    if wait > 0:
        await asyncio.sleep(wait)


async def _solve_captcha_and_submit(page, template, label, ctx, captcha,
                                    pwd_field, user_field=None,
                                    username='', password=''):
    """自动识别验证码并提交登录。

    流程（最多 CAPTCHA_OCR_MAX_ATTEMPTS 次）：
        定位验证码图片 -> 截图 -> OCR -> 校验 -> 填写 -> 提交 -> 判定结果
        - 识别失败（非法字符 / 低置信度）：刷新图片后重试，不提交；
        - 服务端提示「验证码错误」：刷新图片后重试；
        - 服务端提示账号 / 密码错误：立即停止，不重试；
        - 登录成功：结束。

    返回 dict：ok / detail / attempts / last_text

    user_field / username / password：
        每次提交前都要**重新填写**用户名与密码。服务端在验证码错误后
        通常会重新渲染整个登录表单，用户名 / 密码输入框会被清空；
        若不重新填写，第二次提交会带着空账号，被服务端判为「密码错误」
        而中断重试（这是真实场景下踩到的坑）。
    """
    result = {'ok': False, 'detail': '', 'attempts': 0, 'last_text': ''}
    max_attempts = max(1, int(app_config.CAPTCHA_OCR_MAX_ATTEMPTS))
    budget = float(app_config.CAPTCHA_ATTEMPT_BUDGET)
    image_selectors = list(template.get('captcha_image_selectors') or [])
    field = captcha.get('field')
    started_at = time.monotonic()

    for attempt in range(1, max_attempts + 1):
        # 时间预算：单次识别成功率不高（困难验证码约 15%），靠「多次独立重试」
        # 累积成功率。在预算内尽量多试几次，比死磕单次识别更有效。
        if time.monotonic() - started_at > budget:
            Logger.info(ctx.log(
                f"{label}验证码自动识别已达到时间预算 "
                f"{budget:.0f} 秒（已尝试 {attempt - 1} 次），停止重试"))
            break
        result['attempts'] = attempt

        # 先激活验证码输入框：部分站点在「获得焦点」时会刷新验证码，
        # 必须先触发刷新再截图，否则识别的是旧码。
        await _activate_captcha_field(captcha.get('field'))

        image = await find_captcha_image(
            page, field, image_selectors or None,
            log=lambda message: Logger.info(ctx.log(message)))
        if not image.get('hit'):
            result['detail'] = '验证码图片未找到'
            Logger.warning(ctx.log(
                f"{label}未找到验证码图片，自动识别中止"
                f"（已尝试 {attempt}/{max_attempts}）"))
            return result

        # 截图前先滚动到可见位置（保证截到的是完整的验证码图片）
        try:
            await image['element'].scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass

        try:
            # 用 canvas 取原始像素：元素截图会把 CSS 边框一起截进来，
            # 那圈灰边会让 OCR 完全读不出字符。
            png = await capture_captcha_image(image['element'], timeout=3000)
            if not png:
                raise RuntimeError('验证码图片取像素失败')
        except Exception as e:
            result['detail'] = '验证码图片截图失败'
            Logger.warning(ctx.log(
                f"{label}验证码图片截图失败（{str(e)[:60]}），刷新后重试"))
            await _refresh_captcha(page, image, captcha, template, label, ctx,
                                   pwd_field)
            field = captcha.get('field')
            continue

        # 记住本次截图，供刷新后比较是否真的换了新图
        image['screenshot'] = png

        # OCR 必须放在线程里执行，否则会阻塞 Playwright 事件循环，
        # 导致同一批次的其它设备全部卡住。
        #
        # 同一张图跑**全部预处理变体**，取其中最可信的合法结果。
        #
        # 实测：单用原始图约 3%~7%，加上「去彩色干扰掩膜 + 放大」变体后
        # 约 15%（约 3 倍提升）；多变体对简单验证码同样稳定。
        variant = None
        try:
            text, confidence = await asyncio.to_thread(recognizer.recognize,
                                                       png, variant)
        except TypeError:
            # 兼容不支持 variant 参数的识别器实现
            try:
                text, confidence = await asyncio.to_thread(recognizer.recognize,
                                                           png)
            except Exception as e:
                text, confidence = '', 0.0
                Logger.warning(ctx.log(f"{label}验证码识别异常：{str(e)[:80]}"))
        except Exception as e:
            text, confidence = '', 0.0
            Logger.warning(ctx.log(f"{label}验证码识别异常：{str(e)[:80]}"))

        if not text:
            Logger.info(ctx.log(
                f"{label}验证码识别结果无效"
                f"（置信度={confidence:.2f}，尝试 {attempt}/{max_attempts}），"
                f"刷新后重试"))
            result['last_text'] = ''
            await _refresh_captcha(page, image, captcha, template, label, ctx,
                                   pwd_field)
            field = captcha.get('field')
            continue

        Logger.info(ctx.log(
            f"{label}验证码识别：'{text}'（置信度={confidence:.2f}，"
            f"尝试 {attempt}/{max_attempts}）"))

        # 提交前重新填写用户名与密码并校验：
        # 服务端在验证码错误后可能清空整个表单，也可能点击验证码框时重置表单。
        user_field, pwd_field, creds_ok = await _ensure_credentials_filled(
            page, template, user_field, pwd_field, username, password,
            label, ctx)
        if not creds_ok:
            result['detail'] = '账号/密码无法填写（页面可能已被清空或重绘）'
            Logger.warning(ctx.log(f"{label}{result['detail']}"))
            return result

        # 填写前后比对验证码图片指纹：若填写过程中验证码又被刷新了
        # （部分站点在输入框获得焦点时刷新），必须重新识别并重新填写，
        # 否则提交的是旧码。
        fingerprint_before = await captcha_image_fingerprint(image.get('element'))
        filled, reason = await input_text_detailed(field, text)
        if not filled:
            result['detail'] = _describe_fill_failure('验证码', reason)
            Logger.warning(ctx.log(f"{label}{result['detail']}"))
            return result
        fingerprint_after = await captcha_image_fingerprint(image.get('element'))
        if (fingerprint_before and fingerprint_after
                and fingerprint_before != fingerprint_after):
            Logger.info(ctx.log(f"{label}填写过程中验证码发生刷新，重新识别"))
            try:
                fresh_png = await capture_captcha_image(image['element'],
                                                        timeout=3000)
                fresh_text, fresh_conf = await asyncio.to_thread(
                    recognizer.recognize, fresh_png, variant)
            except Exception:
                fresh_text = ''
            if fresh_text:
                text = fresh_text
                filled, reason = await input_text_detailed(field, text)
                if not filled:
                    result['detail'] = _describe_fill_failure('验证码', reason)
                    Logger.warning(ctx.log(f"{label}{result['detail']}"))
                    return result
                Logger.info(ctx.log(
                    f"{label}验证码重新识别：'{text}'（置信度={fresh_conf:.2f}）"))
        result['last_text'] = text

        # 提交：优先在验证码输入框按回车（多数站点回车即可登录）。
        # 若回车没有任何反应（既没成功也没报错），再回退到点击登录按钮。
        submit = await _submit_login(page, template, label, ctx, pwd_field,
                                    enter_field=field, method='auto')
        if not submit.get('ok'):
            result['detail'] = '登录提交失败'
            return result

        confirmed, detail = await _wait_captcha_result(
            page, pwd_field, submit.get('original_url'),
            timeout=1.5 if submit.get('method') == 'enter' else None)
        if not confirmed and submit.get('method') == 'enter':
            captcha_failed = await _detect_captcha_error(page)
            auth_failed = await _detect_login_error(page)
            if not captcha_failed and not auth_failed:
                # 回车没有触发登录 -> 回退到点击登录按钮
                Logger.info(ctx.log(f"{label}回车未触发登录，回退到点击登录按钮"))
                submit = await _submit_login(page, template, label, ctx, pwd_field,
                                            method='button')
                if not submit.get('ok'):
                    result['detail'] = '登录按钮点击失败'
                    return result
                confirmed, detail = await _wait_captcha_result(
                    page, pwd_field, submit.get('original_url'))
        if confirmed:
            result['ok'] = True
            result['detail'] = '登录成功'
            return result

        if await _detect_captcha_error(page):
            Logger.info(ctx.log(
                f"{label}服务端提示验证码错误，刷新后重试"
                f"（尝试 {attempt}/{max_attempts}）"))
            await _refresh_captcha(page, image, captcha, template, label, ctx,
                                   pwd_field)
            field = captcha.get('field')
            continue

        if _is_auth_error(detail):
            result['detail'] = '账号或密码错误（不重试）'
            Logger.warning(ctx.log(f"{label}{result['detail']}"))
            return result

        result['detail'] = f'登录结果未确认：{detail}'
        return result

    result['detail'] = (f'验证码自动识别失败（已尝试 {result["attempts"]} 次）'
                        if result['attempts'] else '验证码自动识别失败')
    Logger.warning(ctx.log(f"{label}{result['detail']}"))
    # 失败退出前清空验证码框，避免把上一条错误验证码留在界面上
    try:
        if captcha.get('field') is not None:
            await captcha['field'].fill('', timeout=1500)
    except Exception:
        pass
    return result



def _captcha_cache_key(template, label, page):
    """「模板 + 页面」缓存键（用于记住该页面无验证码）。"""
    try:
        url = page.url
    except Exception:
        url = ''
    return captcha_cache.make_key(label, (template or {}).get('name'), url)


def _captcha_skip_reason(template, label, cache_key):
    """判断是否可以跳过验证码查找；返回原因（不跳过时返回空串）。

    只在「设备模板」上启用：
      1) 模板显式声明无验证码（captcha_selectors 与
         captcha_image_selectors 都是空列表）；
      2) 之前已确认过「该模板 + 该页面无验证码」（持久化缓存）。
    默认模板仍按内置规则检查，避免漏掉验证码。
    """
    if label != '设备模板':
        return ''
    tpl = template or {}
    selectors = tpl.get('captcha_selectors')
    image_selectors = tpl.get('captcha_image_selectors')
    if (app_config.CAPTCHA_SKIP_WHEN_TEMPLATE_EMPTY
            and isinstance(selectors, list) and not selectors
            and isinstance(image_selectors, list) and not image_selectors):
        return '模板声明无验证码'
    if (app_config.CAPTCHA_ABSENT_CACHE_ENABLED
            and captcha_cache.is_absent(cache_key)):
        return '该模板+页面已确认无验证码（缓存）'
    return ''


async def _solve_captcha_if_hit(page, template, label, ctx, captcha, locate,
                                username, password, outcome, started):
    """验证码命中时执行「自动识别」或「人工兜底」。未命中返回 None。"""
    if not captcha or not captcha.get('hit'):
        return None

    if app_config.CAPTCHA_AUTO_ENABLED and recognizer.is_available():
        solved = await _solve_captcha_and_submit(
            page, template, label, ctx, captcha, locate.get('pwd_field'),
            user_field=locate.get('user_field'), username=username,
            password=password)
        outcome['recorded'] = TemplateManager.finish_recording()
        outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        outcome['captcha_attempts'] = solved.get('attempts', 0)
        outcome['captcha'] = {
            'source': captcha.get('source', ''),
            'by': captcha.get('by', ''),
            'value': captcha.get('value', ''),
        }
        if solved.get('ok'):
            outcome.update(ok=True, stage=STAGE_RESULT, reason='ok',
                           detail='登录成功（已自动通过验证码）')
        else:
            # 保留「模板已生成但未登录成功」的旧语义，界面仍可提示保存模板
            outcome.update(ok=True, stage=STAGE_FILL, reason=FAIL_CAPTCHA,
                           detail=solved.get('detail') or '验证码自动识别失败',
                           safe_to_retry=False)
        if outcome['elapsed_ms'] > app_config.CAPTCHA_ATTEMPT_BUDGET * 1000:
            Logger.warning(ctx.log(
                f"{label}本次带验证码尝试耗时 {outcome['elapsed_ms']}ms "
                f"已超过单次尝试上限 "
                f"{app_config.CAPTCHA_ATTEMPT_BUDGET * 1000}ms"))
        return outcome

    # ===== 原人工兜底分支保持完全不变 =====
    try:
        await captcha['field'].click(timeout=3000)
        await captcha['field'].fill("")
    except Exception:
        pass
    outcome['recorded'] = TemplateManager.finish_recording()
    outcome['ok'] = True
    outcome['stage'] = STAGE_FILL
    outcome['reason'] = FAIL_CAPTCHA
    outcome['detail'] = '需要验证码'
    outcome['safe_to_retry'] = False
    outcome['captcha'] = {
        'source': captcha.get('source', ''),
        'by': captcha.get('by', ''),
        'value': captcha.get('value', ''),
    }
    outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    Logger.warning(ctx.log(
        f"需要验证码（{label}）：已定位验证码输入框"
        f"（来源={captcha.get('source')}，"
        f"selector={_safe_selector(captcha.get('by'), captcha.get('value'))}），"
        f"本次不提交登录表单；模板选择器已录制，可直接保存为模板"))
    return outcome


async def _run_template_attempt(page, template, label, ctx, username, password):
    """用指定模板完成一次完整尝试：定位 → 填写 → 提交 → 结果判定。"""
    started = time.monotonic()
    outcome = {
        'ok': False, 'stage': '', 'reason': '', 'detail': '',
        'elapsed_ms': 0, 'safe_to_retry': True,
        'recorded': None, 'template_label': label,
        'locate_ms': 0, 'fill_ms': 0, 'button_ms': 0, 'captcha_ms': 0,
    }

    locate = await _locate_and_fill(page, template, label, ctx, username, password)
    if not locate['ok']:
        # SPA / 慢页面：表单常常在首屏之后才渲染，等一会儿再完整找一次
        Logger.info(ctx.log(f"{label}首次未定位到登录表单，等待 2 秒后重试定位"))
        await asyncio.sleep(2.0)
        locate = await _locate_and_fill(page, template, label, ctx,
                                        username, password)
    outcome['locate_ms'] = locate.get('locate_ms', 0)
    outcome['fill_ms'] = locate.get('fill_ms', 0)
    if not locate['ok']:
        diagnosis = await _diagnose_form(page)
        if diagnosis:
            Logger.warning(ctx.log(f"{label}表单诊断：{diagnosis}"))
        outcome.update(stage=locate['stage'], reason=locate['reason'],
                       detail=locate['detail'])
        outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        return outcome

    # 验证码：需要人工处理，不能自动重试；本阶段绝不提交登录表单。
    # 验证码输入框同样属于「模板元素」：识别成功后会被记录进模板，
    # 使验证码页面也能正常生成并保存登录模板。
    #
    # 验证码检查采用分级策略，避免正常页面被无谓拖慢：
    # - 慢速页面（表单定位阶段已消耗慢速等待预算，或页面尚未就绪）
    #   → 保留原有的慢速页面扩展等待能力；
    # - 正常页面（页面已就绪、表单可交互）
    #   → 只做快速存在性检查（毫秒级），确认没有验证码后立即提交登录。
    captcha_started = time.monotonic()
    slow_used_ms = int(locate.get('slow_wait_ms', 0) or 0)
    try:
        page_state = await get_page_ready_state(page)
    except Exception:
        page_state = 'unknown'
    slow_page = slow_used_ms > 0 or page_state in ('loading', 'interactive')
    captcha_log = lambda message: Logger.info(ctx.log(message))

    # 有些页面本来就没有验证码：设备模板把 captcha_selectors 存成空列表，
    # 或者之前已确认过「该模板+该页面无验证码」。这两种情况直接跳过查找，
    # 不再把「模板候选 + 内置候选」几十个选择器空跑一遍。
    cache_key = _captcha_cache_key(template, label, page)
    skip_reason = _captcha_skip_reason(template, label, cache_key)
    if skip_reason:
        captcha = {'hit': False, 'field': None, 'by': '', 'value': '',
                   'reason': 'skipped', 'source': ''}
        outcome['captcha_ms'] = 0
        Logger.info(ctx.log(f"{label}跳过验证码查找（{skip_reason}），耗时=0ms"))
    else:
        if slow_page:
            # 慢速页面：允许为「延迟出现的验证码」保留一段有上限的等待。
            # 该扩展预算在「模板候选 / 内置候选」两轮之间共享，基础扫描预算
            # 与普通阶段一致，避免两轮等待叠加成十几秒（实测曾达 9.3 秒）。
            captcha = await find_captcha_field_detailed(
                page, template.get('captcha_selectors') or None,
                budget=SELECTOR_LOOKUP_BUDGET,
                extra_budget=SELECTOR_LOOKUP_READY_BUDGET,
                exclude_fields=[locate.get('user_field'),
                                locate.get('pwd_field')],
                delayed_window=False,
                log=captcha_log)
        else:
            captcha = await find_captcha_field_quick(
                page, template.get('captcha_selectors') or None,
                exclude_fields=[locate.get('user_field'),
                                locate.get('pwd_field')],
                log=captcha_log)
        captcha_ms = int((time.monotonic() - captcha_started) * 1000)
        outcome['captcha_ms'] = captcha_ms
        Logger.info(ctx.log(
            f"{label}验证码检查结束："
            f"{'发现验证码输入框' if captcha['hit'] else '未发现验证码输入框'}，"
            f"耗时={captcha_ms}ms，页面状态={page_state}，"
            f"慢速等待={'是（页面尚未就绪）' if slow_page else '否（页面已就绪，快速检查）'}"))
    solved_outcome = await _solve_captcha_if_hit(
        page, template, label, ctx, captcha, locate, username, password,
        outcome, started)
    if solved_outcome is not None:
        return solved_outcome

    submit = await _submit_login(page, template, label, ctx, locate['pwd_field'])
    outcome['button_ms'] = submit.get('button_ms', 0)
    if not submit['ok']:
        outcome.update(stage=submit['stage'], reason=submit['reason'],
                       detail=submit['detail'])
        outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        return outcome

    confirmed, detail = await _wait_login_result(page, locate['pwd_field'],
                                                  submit['original_url'])
    outcome['recorded'] = TemplateManager.finish_recording()
    outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    if outcome['elapsed_ms'] > TEMPLATE_ATTEMPT_BUDGET * 1000:
        Logger.warning(ctx.log(f"{label}本次尝试耗时 "
                               f"{outcome['elapsed_ms']}ms 已超过单次模板尝试上限 "
                               f"{TEMPLATE_ATTEMPT_BUDGET * 1000}ms"))

    if confirmed:
        # 真正查找过验证码且确认没有 + 登录成功 -> 记住这个结论，
        # 下次同一模板/页面直接跳过验证码查找。
        if (not skip_reason and not captcha.get('hit')
                and app_config.CAPTCHA_ABSENT_CACHE_ENABLED):
            if captcha_cache.mark_absent(cache_key):
                Logger.info(ctx.log(
                    f"{label}已记住「该模板+页面无验证码」，"
                    f"下次登录将跳过验证码查找"))
        outcome['ok'] = True
        outcome['stage'] = STAGE_RESULT
        outcome['reason'] = 'ok'
        outcome['detail'] = '登录成功'
        return outcome

    # 跳过验证码查找后，服务端仍然提示验证码错误 -> 说明页面其实有验证码，
    # 立刻清掉「无验证码」记录并重新完整查找一次（自我修复，避免缓存永久失效）。
    if (skip_reason and detail
            and any(word in str(detail).lower() for word in
                    ('验证码', 'captcha', '校验码', '图形码'))):
        captcha_cache.clear(cache_key)
        Logger.warning(ctx.log(
            f"{label}跳过验证码查找后服务端仍提示验证码错误，"
            f"已清除「无验证码」记录并重新查找验证码"))
        retry_captcha = await find_captcha_field_quick(
            page, None,
            exclude_fields=[locate.get('user_field'), locate.get('pwd_field')])
        if retry_captcha.get('hit'):
            solved_outcome = await _solve_captcha_if_hit(
                page, template, label, ctx, retry_captcha, locate,
                username, password, outcome, started)
            if solved_outcome is not None:
                return solved_outcome

    outcome['stage'] = STAGE_RESULT
    outcome['reason'] = FAIL_AUTH_REJECTED if _is_auth_error(detail) else FAIL_UNKNOWN
    outcome['detail'] = detail
    outcome['safe_to_retry'] = False
    return outcome


async def _run_generic_attempt(page, ctx, username, password):
    """通用元素发现兜底（兼容没有完整模板的旧配置）。

    注意：通用发现路径暂不自动处理验证码（本版只做增量），
    需要验证码自动识别的页面请使用模板路径（_run_template_attempt）。
    """
    started = time.monotonic()
    outcome = {'ok': False, 'stage': '', 'reason': '', 'detail': '',
               'elapsed_ms': 0, 'safe_to_retry': False, 'recorded': None,
               'template_label': '通用发现',
               'locate_ms': 0, 'fill_ms': 0, 'button_ms': 0}

    Logger.info(ctx.log("开始通用元素发现兜底"))
    locate_started = time.monotonic()
    user_field = await find_username_field(page, budget=GENERIC_DISCOVERY_BUDGET)
    pwd_field = await find_password_field(page, budget=GENERIC_DISCOVERY_BUDGET)
    outcome['locate_ms'] = int((time.monotonic() - locate_started) * 1000)
    if not user_field or not pwd_field:
        outcome['stage'] = STAGE_PASSWORD if pwd_field is None else STAGE_USERNAME
        outcome['reason'] = FAIL_FORM_NOT_FOUND
        outcome['detail'] = ('当前页面不符合默认模板支持的登录表单结构'
                             '（未找到用户名/密码输入框）')
        outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        Logger.warning(ctx.log("通用发现未定位到完整登录表单，"
                               "当前页面不符合默认模板支持的登录表单结构，"
                               f"耗时={outcome['elapsed_ms']}ms"))
        return outcome

    fill_started = time.monotonic()
    if not await input_text(user_field, username) or \
            not await input_text(pwd_field, password):
        outcome['stage'] = STAGE_FILL
        outcome['reason'] = FAIL_FORM_FILL
        outcome['detail'] = '表单填写失败'
        outcome['fill_ms'] = int((time.monotonic() - fill_started) * 1000)
        outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        return outcome
    outcome['fill_ms'] = int((time.monotonic() - fill_started) * 1000)

    original_url = page.url
    button_started = time.monotonic()
    clicked, info = await click_login_button_detailed(page, pwd_field, None)
    outcome['button_ms'] = int((time.monotonic() - button_started) * 1000)
    if not clicked:
        outcome['stage'] = STAGE_BUTTON
        outcome['reason'] = FAIL_BUTTON_NOT_FOUND
        outcome['detail'] = '未找到登录按钮'
        outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
        return outcome

    confirmed, detail = await _wait_login_result(page, pwd_field, original_url)
    outcome['recorded'] = TemplateManager.finish_recording()
    outcome['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    if confirmed:
        outcome['ok'] = True
        outcome['detail'] = '登录成功'
        return outcome

    outcome['stage'] = STAGE_RESULT
    outcome['reason'] = FAIL_AUTH_REJECTED if _is_auth_error(detail) else FAIL_UNKNOWN
    outcome['detail'] = detail
    return outcome


# ============ 模板生成（只识别，不登录）============
# 模板字段 -> 元素角色：模板生成阶段同样要做角色校验，
# 不能把「元素被定位到」等同于「元素角色识别正确」。
_ROLE_BY_SELECTOR_KEY = {
    'username_selectors': ROLE_USERNAME,
    'password_selectors': ROLE_PASSWORD,
    'captcha_selectors': ROLE_CAPTCHA,
    'login_button_selectors': ROLE_BUTTON,
}


async def _locate_field_for_template(page, selectors, builtin, selector_key,
                                      ctx, label, extra_budget=None):
    """按「模板选择器 -> 内置规则」的顺序定位字段并记录生效的选择器。

    只定位与记录：绝不填写、绝不点击、绝不提交登录表单。
    返回 (field, detail)；field 为 None 表示未命中。
    """
    candidates = []
    seen = set()
    for item in list(selectors or []) + list(builtin or []):
        if not isinstance(item, dict):
            continue
        key = (str(item.get('by', '')).upper(), str(item.get('value', '')))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        candidates.append(item)

    if not candidates:
        Logger.warning(ctx.log(f"{label}没有可用候选选择器"))
        return None, {'reason': 'no_selectors', 'total': 0, 'executed': 0}

    result = await find_by_selectors_detailed(
        page, candidates, selector_key,
        budget=SELECTOR_LOOKUP_BUDGET,
        log=lambda message: Logger.info(ctx.log(message)),
        stage=f'template_{selector_key}',
        extra_budget=extra_budget,
        role=_ROLE_BY_SELECTOR_KEY.get(selector_key, ''),
        trusted=True)
    if result['hit']:
        Logger.info(ctx.log(
            f"{label}已定位，selector={_safe_selector(result['by'], result['value'])}，"
            f"耗时={result['elapsed_ms']}ms"))
        return result['field'], result

    Logger.warning(ctx.log(
        f"{label}未定位（原因={result.get('reason')}），"
        f"已执行 {result.get('executed')}/{result.get('total')} 个候选，"
        f"耗时={result.get('elapsed_ms')}ms"))
    return None, result


async def generate_template_only(page, template, ctx):
    """在当前登录页上生成登录模板（只识别，不填写、不点击、不提交）。

    适用场景：登录页带图片验证码，用户希望先把模板保存下来，
    之后再用保存好的模板正常登录。

    成功判定：用户名与密码输入框都已定位（选择器有效）即认为模板生成成功。
    验证码框是否存在不影响本阶段判定（找不到只做记录，不算失败）。
    """
    started = time.monotonic()
    TemplateManager.start_recording()

    try:
        user_field, user_result = await _locate_field_for_template(
            page, template.get('username_selectors'), USERNAME_SELECTORS,
            'username_selectors', ctx, '用户名输入框',
            extra_budget=SELECTOR_LOOKUP_SLOW_BUDGET)
        if user_field is None:
            TemplateManager.cancel_recording()
            return {'ok': False, 'reason': FAIL_USERNAME_NOT_FOUND,
                    'detail': '未找到用户名输入框，模板生成失败',
                    'recorded': None,
                    'elapsed_ms': int((time.monotonic() - started) * 1000)}

        used_slow = float(user_result.get('slow_wait_ms', 0) or 0) / 1000.0
        pwd_field, _pwd_result = await _locate_field_for_template(
            page, template.get('password_selectors'), PASSWORD_SELECTORS,
            'password_selectors', ctx, '密码输入框',
            extra_budget=max(0.0, SELECTOR_LOOKUP_SLOW_BUDGET - used_slow))
        if pwd_field is None:
            TemplateManager.cancel_recording()
            return {'ok': False, 'reason': FAIL_PASSWORD_NOT_FOUND,
                    'detail': '未找到密码输入框，模板生成失败',
                    'recorded': None,
                    'elapsed_ms': int((time.monotonic() - started) * 1000)}

        # 验证码输入框：可选元素。识别到就记录，识别不到不影响模板生成。
        captcha = await find_captcha_field_detailed(
            page, template.get('captcha_selectors') or None,
            extra_budget=SELECTOR_LOOKUP_SLOW_BUDGET,
            exclude_fields=[user_field, pwd_field],
            log=lambda message: Logger.info(ctx.log(message)))
        if captcha['hit']:
            Logger.info(ctx.log(
                f"验证码输入框已定位（来源={captcha.get('source')}），"
                f"已记录到模板（不填写、不破解）"))
        else:
            Logger.info(ctx.log("未发现验证码输入框（不影响模板生成结果）"))

        # 登录按钮：只定位并记录，绝不点击（避免在模板阶段触发登录）
        await _locate_field_for_template(
            page, template.get('login_button_selectors'), LOGIN_BUTTON_SELECTORS,
            'login_button_selectors', ctx, '登录按钮', extra_budget=0)

        recorded = TemplateManager.finish_recording()
        elapsed = int((time.monotonic() - started) * 1000)
        counts = {
            'username': len((recorded or {}).get('username_selectors') or []),
            'password': len((recorded or {}).get('password_selectors') or []),
            'captcha': len((recorded or {}).get('captcha_selectors') or []),
            'button': len((recorded or {}).get('login_button_selectors') or []),
        }
        Logger.success(ctx.log(
            f"模板生成完成（未提交登录），用户名={counts['username']}，"
            f"密码={counts['password']}，验证码={counts['captcha']}，"
            f"登录按钮={counts['button']}，耗时={elapsed}ms"))
        return {'ok': True, 'reason': 'ok',
                'detail': '模板生成成功（未提交登录）',
                'recorded': recorded, 'elapsed_ms': elapsed}
    except Exception as e:
        log_exception(e, "generate_template_only")
        TemplateManager.cancel_recording()
        return {'ok': False, 'reason': 'exception',
                'detail': f'模板生成异常：{str(e)[:60]}',
                'recorded': None,
                'elapsed_ms': int((time.monotonic() - started) * 1000)}


async def generate_template_for_device(name, url, template_name=''):
    """打开设备登录页并生成登录模板（只识别，不提交登录）。

    返回 (success, message, recorded)。
    """
    ctx = LoginContext(name, ENTRY_TEMPLATE)
    try:
        session = BrowserManager.get(QUICK_SESSION)
        if not BrowserManager.is_valid(session):
            session = await BrowserManager.create_and_navigate(QUICK_SESSION, url)
            if session is None:
                Logger.error(ctx.log("浏览器启动失败"))
                return False, f"✗ {name}: 浏览器启动失败", None
        else:
            page = await session.open_page(url)
            if page is None:
                Logger.error(ctx.log("新标签页打开失败"))
                return False, f"✗ {name}: 新标签页打开失败", None

        page = session.page
        if page is None:
            Logger.error(ctx.log("没有可用的标签页"))
            return False, f"✗ {name}: 没有可用的标签页", None

        await wait_page_loaded(page, 10, require_complete=False)
        await handle_ssl(page)

        resolved = _resolve_template(ctx, template_name)
        template = resolved['template'] or DEFAULT_TEMPLATE

        result = await generate_template_only(page, template, ctx)
        if not result['ok']:
            return False, f"✗ {name}: {result['detail']}", None

        recorded = result.get('recorded') or {}
        return True, (f"✓ {name}: 模板生成成功（未提交登录）"
                      f"｜用户名={len(recorded.get('username_selectors') or [])}，"
                      f"密码={len(recorded.get('password_selectors') or [])}，"
                      f"验证码={len(recorded.get('captcha_selectors') or [])}"), recorded
    except Exception as e:
        log_exception(e, f"generate_template_for_device {name}")
        return False, f"✗ {name}: {str(e)[:50]}", None


async def _login_with_fallback(page, ctx, username, password, template_name,
                               target_url=''):
    """完整登录流程：设备模板 → （失败时）默认模板 → （再失败时）通用发现。

    同一次登录中，设备模板最多尝试一次，默认模板最多回退一次，不存在无限重试。
    无论最终成功、失败还是无法确认，都会输出一条 [LOGIN_SUMMARY] 汇总日志，
    明确记录：配置的模板 / 实际执行的模板 / 是否回退 / 最终结果 / 各阶段耗时。
    """
    total_started = time.monotonic()
    config_name = str(template_name or '').strip()

    Logger.info(ctx.log(
        f"登录开始，入口={ctx.entry}，"
        f"配置模板={config_name or '(未指定)'}，"
        f"目标地址={target_url or '(未提供)'}"))

    resolve_started = time.monotonic()
    resolved = _resolve_template(ctx, template_name)
    resolve_ms = int((time.monotonic() - resolve_started) * 1000)
    Logger.info(ctx.log(
        f"模板解析，实际模板名={resolved['name']}，模板来源={resolved['source']}，"
        f"模板查找耗时={resolve_ms}ms"))

    if resolved['failed_name']:
        Logger.warning(ctx.log(
            f"模板加载失败，配置模板={resolved['failed_name']}，"
            f"查找目录={TemplateManager.get_template_dir()}，"
            f"模板文件={resolved['failed_path'] or '(未找到)'}，"
            f"原因={resolved['reason']}"))
        Logger.info(ctx.log(f"已回退到默认模板，模板文件={resolved['path']}"))
    else:
        Logger.info(ctx.log(f"模板加载成功，模板文件={resolved['path']}"))
        loaded = resolved['template'] or {}
        Logger.info(ctx.log(
            f"模板校验成功，用户名选择器={len(loaded.get('username_selectors') or [])}，"
            f"密码选择器={len(loaded.get('password_selectors') or [])}，"
            f"登录按钮选择器={len(loaded.get('login_button_selectors') or [])}"))

    summary = {
        'config_name': config_name,
        'executed_names': [resolved['name']],
        'executed_path': resolved['path'],
        'resolve_ms': resolve_ms,
        'fill_ms': 0,
        'button_ms': 0,
        'device_result': '未执行',
        'default_result': '未执行',
        'fallback': '否',
        'fallback_path': '',
        'fallback_reason': '',
        'failed_path': resolved['failed_path'],
        'result': '',
        'final_name': '',
        'final_path': '',
        'success': False,
        'total_ms': 0,
    }

    def _finish(result_text, success, final_name='', final_path='', result_obj=None):
        """收敛本次登录的全部结论并输出汇总日志"""
        summary['result'] = result_text
        summary['success'] = success
        summary['final_name'] = final_name
        summary['final_path'] = final_path
        summary['total_ms'] = int((time.monotonic() - total_started) * 1000)
        _log_login_summary(ctx, summary)
        if result_obj is not None:
            result_obj['final_template_name'] = final_name
            result_obj['final_template_path'] = final_path
            result_obj['final_result'] = result_text
        return summary

    uses_device_template = resolved['source'] == '设备模板'
    Logger.info(ctx.log(f"开始使用{resolved['source']}"))

    outcome = await _run_template_attempt(page, resolved['template'],
                                          resolved['source'], ctx,
                                          username, password)
    summary['fill_ms'] += outcome.get('fill_ms', 0)
    summary['button_ms'] += outcome.get('button_ms', 0)

    if outcome['ok']:
        if outcome['reason'] == FAIL_CAPTCHA:
            # 固定文案改为使用 outcome['detail']：
            # 自动识别关闭 / 不可用 -> 「需要验证码」
            # 自动识别失败           -> 「验证码自动识别失败（已尝试 N 次）」
            captcha_detail = outcome.get('detail') or '需要验证码'
            if uses_device_template:
                summary['device_result'] = captcha_detail
            else:
                summary['default_result'] = captcha_detail
            _finish(f'{captcha_detail}，未能确认登录结果', False,
                    resolved['name'], resolved['path'], outcome)
            return outcome
        if uses_device_template:
            summary['device_result'] = '成功'
        else:
            summary['default_result'] = '成功'
        Logger.success(ctx.log(f"登录成功，最终使用模板={resolved['path']}，"
                               f"模板名={resolved['name']}，"
                               f"总耗时={outcome['elapsed_ms']}ms"))
        _finish('登录成功', True, resolved['name'], resolved['path'], outcome)
        return outcome

    # 表单都不在时，先确认是不是已经登录了
    if outcome['stage'] == STAGE_USERNAME and target_url:
        if await _looks_logged_in(page, target_url):
            Logger.info(ctx.log("页面已不是登录页，判定为已登录"))
            outcome['ok'] = True
            outcome['detail'] = '已登录'
            outcome['recorded'] = TemplateManager.finish_recording()
            if uses_device_template:
                summary['device_result'] = '成功（页面已登录）'
            else:
                summary['default_result'] = '成功（页面已登录）'
            _finish('登录成功（页面已不是登录页，判定为已登录）', True,
                    resolved['name'], resolved['path'], outcome)
            return outcome

    if uses_device_template:
        summary['device_result'] = '失败'
    else:
        summary['default_result'] = '失败'
    Logger.warning(ctx.log(f"{resolved['source']}失败"))
    Logger.warning(ctx.log(f"失败阶段={outcome['stage']}，"
                           f"原因={outcome['reason']}，说明={outcome['detail']}"))
    Logger.info(ctx.log(f"{resolved['source']}尝试耗时={outcome['elapsed_ms']}ms"))

    if outcome['reason'] not in RETRYABLE_REASONS:
        Logger.warning(ctx.log(f"失败原因 '{outcome['reason']}' 不适合重试"
                               f"（避免重复提交），结束本次尝试"))
        _finish(_result_text(outcome), False, resolved['name'], resolved['path'],
                outcome)
        return outcome

    # ---- 回退默认模板（仅一次）----
    default_template, default_path = _get_default_template()
    if default_path == resolved['path'] and resolved['source'] == '默认模板':
        Logger.info(ctx.log("当前已是默认模板，不再重复回退"))
        _finish(_result_text(outcome), False, resolved['name'], resolved['path'],
                outcome)
        return outcome

    summary['fallback'] = '是'
    summary['fallback_reason'] = outcome['reason']
    summary['fallback_path'] = default_path
    summary['executed_names'].append('default')
    Logger.info(ctx.log(f"开始回退默认模板，回退原因={outcome['reason']}"))
    Logger.info(ctx.log(f"默认模板文件={default_path}"))
    n_user, n_pwd, n_btn = _template_counts(default_template)
    Logger.info(ctx.log(f"默认模板校验成功，用户名选择器={n_user}，"
                        f"密码选择器={n_pwd}，登录按钮选择器={n_btn}"))
    Logger.info(ctx.log("开始使用默认模板"))

    if not await _still_on_login_page(page):
        Logger.warning(ctx.log("页面已不在登录表单上，放弃默认模板回退"))
        _finish(_result_text(outcome), False, resolved['name'], resolved['path'],
                outcome)
        return outcome

    default_outcome = await _run_template_attempt(page, default_template, '默认模板',
                                                  ctx, username, password)
    summary['fill_ms'] += default_outcome.get('fill_ms', 0)
    summary['button_ms'] += default_outcome.get('button_ms', 0)

    if default_outcome['ok']:
        if default_outcome['reason'] == FAIL_CAPTCHA:
            summary['default_result'] = '需要验证码'
            _finish('需要验证码，未能确认登录结果', False, 'default', default_path,
                    default_outcome)
            return default_outcome
        summary['default_result'] = '成功'
        Logger.success(ctx.log(f"登录成功，最终使用模板={default_path}"
                               f"（已从{resolved['source']}回退），模板名=default，"
                               f"总耗时={default_outcome['elapsed_ms']}ms"))
        _finish('登录成功', True, 'default', default_path, default_outcome)
        return default_outcome

    summary['default_result'] = '失败'
    Logger.warning(ctx.log("默认模板失败"))
    Logger.warning(ctx.log(f"失败阶段={default_outcome['stage']}，"
                           f"原因={default_outcome['reason']}，"
                           f"说明={default_outcome['detail']}"))
    Logger.info(ctx.log(f"默认模板尝试耗时={default_outcome['elapsed_ms']}ms"))

    if default_outcome['reason'] not in RETRYABLE_REASONS:
        Logger.warning(ctx.log(f"默认模板失败原因 "
                               f"'{default_outcome['reason']}' 不适合重试，结束本次尝试"))
        _finish(_result_text(default_outcome), False, 'default', default_path,
                default_outcome)
        return default_outcome

    # ---- 通用发现兜底（兼容无完整模板的旧配置）----
    generic = await _run_generic_attempt(page, ctx, username, password)
    summary['fill_ms'] += generic.get('fill_ms', 0)
    summary['button_ms'] += generic.get('button_ms', 0)
    summary['executed_names'].append('通用元素发现')
    if generic['ok']:
        Logger.success(ctx.log("登录成功，最终使用模板=通用元素发现，"
                               f"总耗时={generic['elapsed_ms']}ms"))
        _finish('登录成功', True, '通用元素发现', '(通用元素发现，无模板文件)',
                generic)
        return generic

    Logger.error(ctx.log(f"登录失败，最终失败原因={generic['reason']}，"
                         f"说明={generic['detail']}"))
    _finish(_result_text(generic), False, '通用元素发现', '(通用元素发现，无模板文件)',
            generic)
    return generic


async def login_device(session, device, entry=ENTRY_SINGLE):
    """登录单个设备（当前标签页）"""
    url = device["url"]
    # 凭据按需解密（devices.json 中为密文，登录该设备时才解密并缓存）
    username, password = device_store.get_device_credentials(device)
    name = device.get("name", url)
    template_name = device.get("template", "") or ""
    ctx = LoginContext(name, entry)

    page = session.page if session is not None else None
    if page is None:
        Logger.error(ctx.log("登录失败，最终失败原因=no_page，没有可用的标签页"))
        _log_login_summary(ctx, {
            'config_name': template_name,
            'executed_names': ['(未开始)'],
            'result': '登录失败（原因=no_page，没有可用的标签页）',
            'success': False,
            'final_name': '', 'final_path': '',
        })
        return False, f"{name}: 没有可用的标签页", None

    # 启动选择器录制
    TemplateManager.start_recording()

    try:
        # 页面只需 DOM 可交互即可定位表单，不再等待全部资源加载完成
        Logger.info(ctx.log(f"{name}: 开始定位登录表单"))
        await wait_page_loaded(page, 10, require_complete=False)
        await handle_ssl(page)

        outcome = await _login_with_fallback(page, ctx, username, password,
                                             template_name, url)

        if outcome['ok']:
            if outcome['reason'] == FAIL_CAPTCHA:
                # 如实反映失败原因（自动识别失败 / 需要验证码），
                # 不再统一显示「已完成」而让人误以为登录成功
                detail = outcome.get('detail') or '需要验证码'
                return True, f"{name}: {detail}", outcome['recorded']
            if outcome['detail'] == '已登录':
                return True, f"{name}: 已登录", outcome['recorded']
            return True, f"{name}: OK（模板={_final_template_label(outcome)}）", \
                outcome['recorded']

        TemplateManager.cancel_recording()
        return False, f"{name}: {outcome['detail']}（模板={_final_template_label(outcome)}）", None

    except Exception as e:
        log_exception(e, f"login_device {name}")
        TemplateManager.cancel_recording()
        Logger.error(ctx.log(f"登录失败，最终失败原因=exception，"
                             f"说明={str(e)[:80]}"))
        _log_login_summary(ctx, {
            'config_name': template_name,
            'executed_names': ['(异常中断)'],
            'result': f"登录异常（{str(e)[:60]}）",
            'success': False,
            'final_name': '', 'final_path': '',
        })
        return False, f"{name}: {str(e)[:50]}", None


async def login_group(group_name, progress_callback):
    """分组批量登录：同一分组共用一个浏览器窗口，每台设备一个标签页

    返回 (每台设备的结果列表, 录制候选列表)；
    录制候选列表中的每一项都带有设备名与该设备配置的模板名，
    供界面判断是否需要提示保存模板（不再用分组名冒充设备名）。
    """
    devices = device_store.get_group_devices(group_name)
    if not devices:
        Logger.warning(f"分组 {group_name} 无设备")
        return [], []

    # 先关闭旧的同分组浏览器
    await BrowserManager.close_group(group_name)
    session = await BrowserManager.create(group_name)
    if session is None:
        Logger.error(f"分组 {group_name} 浏览器创建失败")
        return [], []

    Logger.info(f"开始分组登录: {group_name}, 设备数: {len(devices)}")
    results = []
    recorded_candidates = []

    for i, device in enumerate(devices):
        name = device.get("name", device["url"])
        if progress_callback is not None:
            progress_callback(f"登录: {name}", i + 1, len(devices))

        try:
            nav_started = time.monotonic()
            if i == 0:
                await navigate(session.page, device["url"])
            else:
                await session.open_page(device["url"])
            nav_ms = int((time.monotonic() - nav_started) * 1000)
            Logger.info(f"设备={name}：页面打开耗时={nav_ms}ms，"
                        f"模板={device.get('template') or '(未指定)'}")
        except Exception as e:
            log_exception(e, f"打开设备页面 {name}")
            results.append((False, f"{name}: 页面打开失败"))
            if progress_callback is not None:
                progress_callback(f"✗ {name}: 页面打开失败", i + 1, len(devices))
            continue

        success, msg, recorded = await login_device(session, device,
                                                     entry=ENTRY_GROUP)
        results.append((success, msg))

        # 汇报单台设备的登录结果（带成功/失败标记，供界面判定状态并记录设备信息）
        if progress_callback is not None:
            progress_callback(f"{'✓' if success else '✗'} {msg}", i + 1, len(devices))

        # 记录本次录制的选择器（连同设备名与该设备配置的模板名）
        # 注意：验证码页面的登录未完成，但模板已成功生成，同样需要上报；
        # 失败路径的 recorded 为 None，因此这里不受 success 影响。
        if recorded and any(recorded.values()):
            recorded_candidates.append({
                'device': name,
                'template': device.get('template', '') or '',
                'recorded': recorded,
            })

    # 所有设备登录完成后，选中本实例的第一个标签页并激活到前台
    # （只操作本实例的标签页，不影响其它浏览器实例）
    if results:
        try:
            await session.select_first_tab()
        except Exception as e:
            log_exception(e, f"分组 {group_name} 选中第一个标签页")

    success_count = sum(1 for r in results if r[0])
    Logger.success(f"分组 {group_name} 完成: {success_count}/{len(results)} 成功")
    return results, recorded_candidates


async def quick_login(name, url, username, password, template_name="default"):
    """快捷登录：复用快捷登录浏览器，未打开时新建，已存在则新开标签页

    与分组登录使用完全相同的模板优先与默认模板回退规则，
    日志也走同一套 [LOGIN_SUMMARY] 汇总逻辑。

    快捷登录完成后**不**切换标签页：保持登录所在的标签页，
    不改变用户当前的浏览位置。
    （与分组登录行为不同：分组登录完成后仍会切回该实例的第一个标签页。）
    """
    return await _quick_login_inner(
        name, url, username, password, template_name)


async def _quick_login_inner(name, url, username, password, template_name="default"):
    """快捷登录主体逻辑（不涉及实例级收尾动作）"""
    ctx = LoginContext(name, ENTRY_QUICK)
    TemplateManager.start_recording()

    try:
        session = BrowserManager.get(QUICK_SESSION)
        if not BrowserManager.is_valid(session):
            session = await BrowserManager.create_and_navigate(QUICK_SESSION, url)
            if session is None:
                Logger.error(ctx.log("登录失败，最终失败原因=browser_create_failed，"
                                     "浏览器启动失败"))
                TemplateManager.cancel_recording()
                return False, f"✗ {name}: 浏览器启动失败", None
            await wait_page_loaded(session.page, 10, require_complete=False)
        else:
            # 浏览器已存在，在新标签页中打开
            page = await session.open_page(url)
            if page is None:
                Logger.error(ctx.log("登录失败，最终失败原因=new_tab_failed，"
                                     "新标签页打开失败"))
                TemplateManager.cancel_recording()
                return False, f"✗ {name}: 新标签页打开失败", None
            await wait_page_loaded(page, 10, require_complete=False)

        page = session.page
        await handle_ssl(page)

        outcome = await _login_with_fallback(page, ctx, username, password,
                                             template_name, url)

        if outcome['ok']:
            if outcome['reason'] == FAIL_CAPTCHA:
                # 验证码页面：模板已生成（用户名/密码/验证码选择器已录制），
                # 但登录未成功 —— 两者必须区分，不得混为一谈。
                captcha_detail = outcome.get('detail') or '需要验证码'
                suffix = ('（模板已生成，未提交登录）'
                          if captcha_detail == '需要验证码' else '')
                return False, (f"✗ {name}: {captcha_detail}{suffix}"), \
                    outcome['recorded']
            if outcome['detail'] == '已登录':
                return True, f"✓ {name}: 已登录", outcome['recorded']
            return True, f"✓ {name}: 登录完成（模板={_final_template_label(outcome)}）", \
                outcome['recorded']

        TemplateManager.cancel_recording()
        return False, f"✗ {name}: {outcome['detail']}（模板={_final_template_label(outcome)}）", None

    except Exception as e:
        error_str = str(e)
        if "Target page" in error_str or "closed" in error_str.lower() or \
                "browser has been closed" in error_str.lower():
            log_exception(e, f"快捷登录 {name} - 浏览器连接断开")
            TemplateManager.cancel_recording()
            return False, f"✗ {name}: 浏览器连接断开，请重试", None

        log_exception(e, f"快捷登录 {name}")
        TemplateManager.cancel_recording()
        return False, f"✗ {name}: {error_str[:50]}", None
