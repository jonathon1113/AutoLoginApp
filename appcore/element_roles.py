"""登录表单元素的角色验证。

「选择器命中了某个元素」与「这个元素确实是用户名字段」不是同一件事：
`input[id="login"]` 这类规则完全可能命中登录按钮、隐藏域、密码框或验证码框。
本模块在命中之后补一次角色判定，把不适合的元素挡在「填写 / 点击」之前，
并给出可以写进日志的原因。

设计原则（与项目既有约定一致）：
- 结构性问题一律否决：标签、type、可见性、启用状态、可编辑性、隐藏域；
- 语义问题只做否定式否决 + 多匹配消歧，不做「必须有某个属性才认定」的正向强判定，
  避免把属性不标准的合法用户名框误杀；
- 密码框可能是 type="text"，因此密码角色不能只看 type 属性，
  必须结合 id / name / class / placeholder / style 综合判断；
- 只读取属性，不修改页面 DOM。
"""

import re

# ============ 角色 ============
ROLE_USERNAME = 'username'
ROLE_PASSWORD = 'password'
ROLE_CAPTCHA = 'captcha'
ROLE_BUTTON = 'button'

# ============ 判定结论 ============
ACCEPT = 'accept'
REJECT = 'reject'
AMBIGUOUS = 'ambiguous'

# 单个候选最多检查多少个匹配元素（避免宽泛选择器导致无上限的属性读取）
MAX_INSPECT = 10

# 可作为文本输入容器的标签
_INPUT_TAGS = ('input', 'textarea')

# 可用于「文本输入」角色的 type 取值
_TEXTUAL_TYPES = ('', 'text', 'email', 'tel', 'url')

# 明确不能作为文本输入 / 按钮之外的控件
_NON_TEXT_TYPES = (
    'password', 'submit', 'button', 'image', 'reset', 'hidden',
    'checkbox', 'radio', 'file', 'range', 'color', 'search',
    'date', 'datetime-local', 'month', 'week', 'time', 'number',
)

# 按钮型 input 的 type
_BUTTON_INPUT_TYPES = ('submit', 'button', 'image')

# ============ 关键词 ============
_USERNAME_TOKENS = (
    'username', 'user_name', 'userid', 'user', 'account', 'loginname',
    'login_name', 'loginuser', 'devusername', 'loginacct',
)
_USERNAME_CN = ('用户名', '账号', '帐号', '邮箱', '登陆名', '登录名')

_PASSWORD_TOKENS = (
    'password', 'passwd', 'pwd', 'pass', 'passwrd', 'userpass', 'pwdconfirm',
)
_PASSWORD_CN = ('密码', '口令')

# ============ 角色证据分级 ============
# 角色判定不能只看「某个字符串里有没有 pass」：
# 样式类名（如 el-input__inner、password-field）和浏览器自动填充标记
# （autocomplete=current-password）经常被框架复制到同一个表单里的多个
# 输入框上。若把这类线索与 placeholder / name 这类「元素自身语义」
# 等权处理，就会把真正的账号输入框误判成密码框
# （实测：type=text、placeholder=账号 的账号框被判为 looks_like_password）。
#
# 因此按来源分级：
#   强：元素自身写明了「这是密码」（placeholder 写着密码、CSS 密码点显示）
#   中：字段名带密码语义（name=password、id=pwd）
#   弱：只是样式类名或浏览器自动填充标记，可能与账号框共用
_PASSWORD_EVIDENCE_STRONG = 2.0
_PASSWORD_EVIDENCE_MID = 1.0
_PASSWORD_EVIDENCE_WEAK = 0.5

# 用户名证据同样分级
_USERNAME_EVIDENCE_STRONG = 2.0
_USERNAME_EVIDENCE_MID = 1.0

_CAPTCHA_TOKENS = (
    'captcha', 'kapkey', 'validatecode', 'checkcode', 'verifycode',
    'securitycode', 'authcode', 'vcode', 'imgcode', 'img_code',
)
_CAPTCHA_CN = ('验证码', '校验码', '图形码', '动态码', '短信码')

# 「确认密码」类字段：多密码框时需要排除
_CONFIRM_TOKENS = ('confirm', 'confirmpwd', 'repeat', 'again', 'reenter', 'repassword')
_CONFIRM_CN = ('确认密码', '重复密码', '再次输入')

# 登录按钮文字
_BUTTON_TEXT = ('登录', '登陆', '登入', 'sign in', 'signin', 'log in', 'login', 'submit')

# 按钮样式类名特征
_BUTTON_CLASS = ('btn', 'button', 'login', 'submit')

_TOKEN_SPLIT = re.compile(r'[^\w\u4e00-\u9fff]+', re.UNICODE)

# 读取元素特征的脚本（一次 evaluate 取全部属性，避免多次往返）
_ELEMENT_INFO_JS = """
el => {
    const attr = (n) => (el.getAttribute ? (el.getAttribute(n) || '') : '');
    let type = '';
    try { type = (el.type || attr('type') || '').toLowerCase(); } catch (e) { type = ''; }
    return {
        tag: (el.tagName || '').toLowerCase(),
        type: type,
        id: el.id || '',
        name: attr('name'),
        cls: attr('class'),
        placeholder: attr('placeholder'),
        autocomplete: attr('autocomplete').toLowerCase(),
        aria: attr('aria-label'),
        role: attr('role').toLowerCase(),
        style: attr('style').toLowerCase(),
        text: (el.textContent || '').trim(),
        readonly: !!(el.readOnly || attr('readonly') !== ''),
        disabled: !!(el.disabled || attr('disabled') !== ''),
        hidden: !!el.hidden,
        contenteditable: attr('contenteditable').toLowerCase()
    };
}
"""


def _tokens(*values):
    """把属性值拆成小写词元（用于精确的英文特征匹配）"""
    text = ' '.join(str(v or '') for v in values).lower()
    parts = [part for part in _TOKEN_SPLIT.split(text) if part]
    return parts, text


def _has_token(tokens, wanted):
    """词元是否命中给定集合（精确匹配，避免 compass 之类的误判）"""
    return any(token in wanted for token in tokens)


def _has_cn(text, words):
    """中文特征按子串匹配"""
    return any(word in text for word in words)


def _hint_has_password(hint):
    """选择器原文是否声明了密码语义。

    用于「type=text 的密码框」：元素属性可能没有任何密码线索，
    但用户写下的选择器（如 //input[@type='text' and @id='password']）
    已经明确指向密码字段。
    """
    if not hint:
        return False
    tokens, text = _tokens(hint)
    if _has_token(tokens, _PASSWORD_TOKENS):
        return True
    return _has_cn(text, _PASSWORD_CN)


def _effective_type(info):
    """取得元素的有效 type（textarea 视为文本框；input 缺省 type 即 text）"""
    tag = info.get('tag', '')
    raw = (info.get('type') or '').strip()
    if tag == 'textarea':
        return 'text'
    if tag == 'input':
        return raw or 'text'
    return raw


def _haystack(info):
    """参与语义判断的属性集合"""
    return ' '.join([
        str(info.get('id') or ''),
        str(info.get('name') or ''),
        str(info.get('cls') or ''),
        str(info.get('placeholder') or ''),
        str(info.get('aria') or ''),
    ])


def _username_score(info):
    """用户名证据打分（越高越可信），同时返回命中的证据来源。

    与密码证据对称地分级：字段名 / placeholder 这类「元素自身语义」
    属于强证据；autocomplete / type=email 属于一般证据。
    class 名不参与判定（很多框架的账号框类名与密码框完全相同）。
    """
    sources = []
    score = 0.0

    tokens, text = _tokens(info.get('id'), info.get('name'),
                           info.get('placeholder'), info.get('aria'))
    if _has_token(tokens, _USERNAME_TOKENS):
        score += _USERNAME_EVIDENCE_STRONG
        sources.append('name/id 含用户名词')
    elif _has_cn(text, _USERNAME_CN):
        score += _USERNAME_EVIDENCE_STRONG
        sources.append('placeholder/aria 含用户名词')

    autocomplete = (info.get('autocomplete') or '').lower()
    if autocomplete in ('username', 'email') or _effective_type(info) == 'email':
        score += _USERNAME_EVIDENCE_MID
        sources.append('autocomplete=%s' % (autocomplete or 'email'))

    return score, sources


def _password_score(info):
    """密码证据打分（越高越可信），同时返回命中的证据来源。

    分级理由见 _PASSWORD_EVIDENCE_STRONG 处的说明：
    class 名与浏览器自动填充标记只能算弱证据，不能单独把一个
    type=text 的可见输入框判成密码框。
    """
    sources = []
    score = 0.0

    # 强证据 1：placeholder / aria-label 直接写着「密码 / 口令」
    cn_text = ' '.join([str(info.get('placeholder') or ''),
                         str(info.get('aria') or '')])
    if _has_cn(cn_text, _PASSWORD_CN):
        score += _PASSWORD_EVIDENCE_STRONG
        sources.append('placeholder/aria 含密码词')

    # 强证据 2：-webkit-text-security（内容按密码点显示，实质就是密码框）
    if 'webkit-text-security' in (info.get('style') or ''):
        score += _PASSWORD_EVIDENCE_STRONG
        sources.append('style 含 -webkit-text-security')

    # 中证据：name / id 的精确词元命中（name=password、id=pwd 等）
    field_tokens, _ = _tokens(info.get('id'), info.get('name'))
    if _has_token(field_tokens, _PASSWORD_TOKENS):
        score += _PASSWORD_EVIDENCE_MID
        sources.append('name/id 含密码词')

    # 弱证据：class 只是样式名，框架常把同一个类名同时用在账号框和密码框上
    cls_tokens, _ = _tokens(info.get('cls'))
    if _has_token(cls_tokens, _PASSWORD_TOKENS):
        score += _PASSWORD_EVIDENCE_WEAK
        sources.append('class 含密码词')

    # 弱证据：浏览器自动填充标记，可能被框架复制到同表单的其它输入框
    autocomplete = (info.get('autocomplete') or '').lower()
    if autocomplete in ('current-password', 'new-password'):
        score += _PASSWORD_EVIDENCE_WEAK
        sources.append('autocomplete=%s' % autocomplete)

    return score, sources


def _username_evidence(info):
    """用户名正向证据强度：2=明确，1=一般，0=无线索（兼容旧调用）"""
    score, _sources = _username_score(info)
    if score >= _USERNAME_EVIDENCE_STRONG:
        return 2
    if score > 0:
        return 1
    return 0


def _password_evidence(info):
    """密码正向证据强度：2=强证据，1=中/弱证据，0=无线索（兼容旧调用）

    与旧实现的差别：弱证据（class 名 / 浏览器自动填充标记）现在单独记为 1，
    不再与「元素自身写明是密码」的强证据混为一谈。
    """
    score, _sources = _password_score(info)
    if score >= _PASSWORD_EVIDENCE_STRONG:
        return 2
    if score > 0:
        return 1
    return 0


def _captcha_evidence(info):
    """验证码正向证据强度"""
    tokens, text = _tokens(info.get('id'), info.get('name'), info.get('cls'),
                           info.get('placeholder'), info.get('aria'))
    if _has_token(tokens, _CAPTCHA_TOKENS) or _has_cn(text, _CAPTCHA_CN):
        return 2
    return 0


def _is_confirm_field(info):
    """是否为「确认密码」类的二次输入框"""
    tokens, text = _tokens(info.get('id'), info.get('name'), info.get('placeholder'))
    return _has_token(tokens, _CONFIRM_TOKENS) or _has_cn(text, _CONFIRM_CN)


def _button_text_hit(info):
    """按钮文字是否像登录按钮"""
    text = re.sub(r'\s+', '', str(info.get('text') or '')).lower()
    if not text:
        return False
    return any(word.replace(' ', '') in text for word in _BUTTON_TEXT)


def _button_class_hit(info):
    """按钮样式类名是否像按钮"""
    cls = str(info.get('cls') or '').lower()
    return any(word in cls for word in _BUTTON_CLASS)


# ============ 各角色的判定 ============
def _judge_username(info, visible, trusted=False, hint=''):
    """判定一个元素能否作为用户名字段。

    返回 (verdict, reason, score)；verdict 为 ACCEPT / REJECT。
    """
    tag = info.get('tag', '')
    if tag not in _INPUT_TAGS:
        return REJECT, 'not_text_input', 0
    if info.get('hidden'):
        return REJECT, 'hidden_element', 0

    etype = _effective_type(info)
    if etype == 'password':
        return REJECT, 'is_password_field', 0
    if etype in _NON_TEXT_TYPES:
        return REJECT, f'input_type_{etype}', 0

    if info.get('readonly'):
        return REJECT, 'readonly_element', 0
    if info.get('disabled'):
        return REJECT, 'disabled_element', 0
    if not visible:
        return REJECT, 'not_visible', 0

    # 语义否决：更像验证码框（先于密码判定，避免验证码框被当作用户名）
    if _captcha_evidence(info) >= 2:
        return REJECT, 'looks_like_captcha', 0

    # 语义否决：更像密码框。
    # 按证据分级处理，避免把「样式类名里带 pass」或「浏览器自动填充标记」
    # 当成与 placeholder=密码 同等的证据：
    #  - 强/中密码证据 + 强用户名证据 -> 证据冲突，不能武断定性，
    #    交由 inspect_role 结合页面上是否存在独立密码框做消歧；
    #  - 强/中密码证据且无强用户名证据 -> 拒绝；
    #  - 仅弱证据 -> 不足以否决可见可编辑的文本框，但记录诊断来源。
    pw_score, pw_sources = _password_score(info)
    user_score, _user_sources = _username_score(info)
    if pw_score >= _PASSWORD_EVIDENCE_MID:
        if user_score >= _USERNAME_EVIDENCE_STRONG:
            return AMBIGUOUS, 'role_conflict', 0
        return REJECT, 'looks_like_password', 0
    if pw_score > 0:
        return (ACCEPT, 'weak_password_signal(%s)' % ','.join(pw_sources),
                user_score)

    return ACCEPT, '', user_score


def _judge_password(info, visible, trusted=False, hint=''):
    """判定一个元素能否作为密码字段。

    trusted=True 表示该候选来自用户模板的显式声明：此时即使
    type="text" 且元素本身没有密码特征，只要**选择器本身**声明了密码语义
    （如 //input[@type='text' and @id='password']），也按模板声明采信
    （并给出提示），以兼容「密码框实际是 type=text」的设备。
    选择器本身没有任何密码语义时仍然拒绝，避免把普通文本框当密码框。
    """
    tag = info.get('tag', '')
    if tag not in _INPUT_TAGS:
        return REJECT, 'not_text_input', 0
    if info.get('hidden'):
        return REJECT, 'hidden_element', 0

    etype = _effective_type(info)
    if etype == 'password':
        return ACCEPT, '', 3
    if etype in _NON_TEXT_TYPES:
        return REJECT, f'input_type_{etype}', 0

    if info.get('readonly'):
        return REJECT, 'readonly_element', 0
    if info.get('disabled'):
        return REJECT, 'disabled_element', 0
    if not visible:
        return REJECT, 'not_visible', 0

    # 密码证据分级：强证据（placeholder 写着密码 / CSS 密码点显示）与
    # 中证据（name=password、id=pwd）都足以认定这是密码框；
    # 弱证据（class 名 / 浏览器自动填充标记）不足以单独认定。
    pw_score, _pw_sources = _password_score(info)
    user_score, _user_sources = _username_score(info)
    if pw_score >= _PASSWORD_EVIDENCE_STRONG:
        # 明确带有密码特征，但同时带有强用户名特征时证据冲突，需进一步确认
        if user_score >= _USERNAME_EVIDENCE_STRONG and not _is_confirm_field(info):
            return AMBIGUOUS, 'role_conflict', 0
        return ACCEPT, '', 2

    if pw_score >= _PASSWORD_EVIDENCE_MID:
        if user_score >= _USERNAME_EVIDENCE_STRONG and not _is_confirm_field(info):
            return AMBIGUOUS, 'role_conflict', 0
        return ACCEPT, '', 2

    if user_score >= _USERNAME_EVIDENCE_STRONG:
        return REJECT, 'looks_like_username', 0

    if trusted:
        # 模板显式声明：仅当选择器本身也声明了密码语义时才采信
        if _hint_has_password(hint):
            return ACCEPT, 'password_role_by_template_declaration', 1
        return REJECT, 'no_password_evidence', 0
    return REJECT, 'no_password_evidence', 0


def _judge_captcha(info, visible, trusted=False, hint=''):
    """判定一个元素能否作为验证码字段"""
    tag = info.get('tag', '')
    if tag not in _INPUT_TAGS:
        return REJECT, 'not_text_input', 0
    if info.get('hidden'):
        return REJECT, 'hidden_element', 0

    etype = _effective_type(info)
    if etype == 'password':
        return REJECT, 'is_password_field', 0
    if etype in _NON_TEXT_TYPES:
        return REJECT, f'input_type_{etype}', 0

    if info.get('disabled'):
        return REJECT, 'disabled_element', 0
    if not visible:
        return REJECT, 'not_visible', 0

    # 密码证据达到「中」及以上时不能当验证码框（弱证据不否决：
    # 很多框架的输入框类名在账号框与验证码框上完全相同）
    if _password_score(info)[0] >= _PASSWORD_EVIDENCE_MID:
        return REJECT, 'looks_like_password', 0

    return ACCEPT, '', _captcha_evidence(info)


def _judge_button(info, visible, trusted=False, hint=''):
    """判定一个元素能否作为登录按钮。

    这是「登录按钮候选与用户名候选串用」的关键防线：
    命中普通输入框（type=text/password）一律否决。
    """
    tag = info.get('tag', '')
    if tag in ('input', 'textarea'):
        etype = _effective_type(info)
        if etype in _BUTTON_INPUT_TYPES:
            if info.get('disabled'):
                return REJECT, 'disabled_element', 0
            if not visible:
                return REJECT, 'not_visible', 0
            return ACCEPT, '', 2
        # 普通输入框不是按钮
        return REJECT, f'input_type_{etype or "text"}', 0

    if tag == 'button':
        etype = _effective_type(info)
        if etype == 'reset':
            return REJECT, 'input_type_reset', 0
        if info.get('disabled'):
            return REJECT, 'disabled_element', 0
        if not visible:
            return REJECT, 'not_visible', 0
        return ACCEPT, '', 2

    role = info.get('role') or ''
    if role == 'button':
        if info.get('disabled'):
            return REJECT, 'disabled_element', 0
        if not visible:
            return REJECT, 'not_visible', 0
        return ACCEPT, '', 2

    # a / div / span 等非原生按钮：必须有按钮类名或登录文字作为证据
    if tag in ('a', 'div', 'span', 'i', 'em', 'p', 'label'):
        if _button_text_hit(info) or _button_class_hit(info):
            if info.get('disabled'):
                return REJECT, 'disabled_element', 0
            if not visible:
                return REJECT, 'not_visible', 0
            return ACCEPT, '', 1

    return REJECT, f'not_a_button_tag_{tag or "unknown"}', 0


_JUDGES = {
    ROLE_USERNAME: _judge_username,
    ROLE_PASSWORD: _judge_password,
    ROLE_CAPTCHA: _judge_captcha,
    ROLE_BUTTON: _judge_button,
}

# 消歧时使用的「强证据」门槛
_STRONG_SCORE = 2


async def _collect_elements(locator, count):
    """读取匹配元素的特征（最多 MAX_INSPECT 个）"""
    limit = max(0, min(int(count or 0), MAX_INSPECT))
    items = []
    for index in range(limit):
        try:
            element = locator.nth(index)
        except Exception:
            continue
        try:
            info = await element.evaluate(_ELEMENT_INFO_JS)
        except Exception:
            info = None
        if not isinstance(info, dict):
            continue
        visible = True
        try:
            visible = bool(await element.is_visible())
        except Exception:
            visible = True
        items.append({'element': element, 'info': info, 'visible': visible})
    return items


async def _count_password_fields(locator):
    """统计元素所在文档内的 type=password 输入框数量（读不到时返回 None）。

    evaluate 在元素自身的文档上下文中执行，因此 iframe 内的元素也能
    正确取到它所属 iframe 文档的结果。
    """
    try:
        count = await locator.first.evaluate(
            "() => document.querySelectorAll('input[type=\"password\"]').length")
        return int(count or 0)
    except Exception:
        return None


async def _resolve_role_conflicts(locator, conflicts, role):
    """用页面上下文消解「证据冲突」。

    场景：某个输入框既带账号语义（placeholder=账号）又带密码语义
    （name=password / autocomplete=current-password）。只看这一个元素
    无法判断它是账号框还是密码框；但如果同一页面里存在**独立的**
    type=password 输入框，真正的密码框就另有其物，当前这个文本框可以
    按账号处理。

    这条规则同时避免了两种极端：
    - 不会因为「表单里存在密码框」就把所有文本输入框判成密码框；
    - 也不会因为「元素上有个 password 字样」就放行一个没有独立密码框
      可供区分的可疑元素。
    """
    if role != ROLE_USERNAME:
        # 密码角色：页面上存在独立密码框恰恰说明当前框不是密码框，
        # 维持拒绝（由调用方按“证据冲突”报告）。
        return []

    password_fields = await _count_password_fields(locator)
    if not password_fields:
        return []

    return [(item, 0, 'conflict_resolved:页面存在独立密码框')
            for item, _reason in conflicts]


def _element_digest(item):
    """元素的非敏感属性摘要（用于角色校验的诊断日志）。

    只包含结构性属性（标签、type、id、name、class、placeholder、
    autocomplete、aria-label）与证据评分，**绝不包含输入框的值**，
    避免把用户名 / 密码 / 验证码写进日志。
    """
    info = item.get('info') or {}
    pw_score, pw_sources = _password_score(info)
    user_score, user_sources = _username_score(info)
    return {
        'tag': info.get('tag', ''),
        'type': info.get('type', ''),
        'id': info.get('id', ''),
        'name': info.get('name', ''),
        'cls': info.get('cls', ''),
        'placeholder': info.get('placeholder', ''),
        'autocomplete': info.get('autocomplete', ''),
        'aria': info.get('aria', ''),
        'visible': bool(item.get('visible')),
        'password_score': pw_score,
        'password_sources': pw_sources,
        'username_score': user_score,
        'username_sources': user_sources,
    }


def format_role_diagnostics(elements):
    """把元素摘要拼成一行诊断文本（不含任何表单值）。"""
    if not elements:
        return ''
    parts = []
    for item in elements:
        parts.append(
            'tag=%s type=%s id=%s name=%s class=%s placeholder=%s '
            'autocomplete=%s aria=%s 可见=%s 密码证据=%.1f(%s) 用户名证据=%.1f(%s)'
            % (item.get('tag', ''), item.get('type', ''), item.get('id', ''),
               item.get('name', ''), item.get('cls', ''),
               item.get('placeholder', ''), item.get('autocomplete', ''),
               item.get('aria', ''),
               '是' if item.get('visible') else '否',
               item.get('password_score', 0),
               ','.join(item.get('password_sources') or []) or '无',
               item.get('username_score', 0),
               ','.join(item.get('username_sources') or []) or '无'))
    return ' | '.join(parts)


async def inspect_role(locator, count, role, trusted=False, hint=''):
    """对命中的候选做角色校验。

    hint 为选择器原文：部分“显式声明”只能靠选择器本身判断
    （例如 type="text" 的密码框：元素属性无线索，但选择器里写着 id='password'）。

    返回 dict：
      ok          是否通过角色校验（可直接用于填写 / 点击）
      field       通过校验的元素（Locator）；未通过时为 None
      verdict     accept / reject / ambiguous
      reason      未通过的原因代码
      detail      人类可读说明（可直接写入日志）
      matched     选择器匹配到的元素总数
      accepted    通过角色校验的元素数
      checked     实际检查的元素数
      note        需要提示但不构成拒绝的原因
    """
    result = {
        'ok': False, 'field': None, 'verdict': REJECT, 'reason': '',
        'detail': '', 'matched': int(count or 0), 'accepted': 0,
        'checked': 0, 'note': '', 'elements': [],
    }
    if not role or role not in _JUDGES:
        result.update(ok=True, field=locator.first if locator else None,
                      verdict=ACCEPT, reason='no_role_check')
        return result

    items = await _collect_elements(locator, count)
    result['checked'] = len(items)
    if not items:
        # 无法读取元素属性（测试替身或页面异常）：不做判定，但明确记录
        result.update(ok=True, field=locator.first if locator else None,
                      verdict=ACCEPT, reason='role_check_unavailable',
                      detail='无法读取元素属性，已跳过角色校验')
        return result

    # 元素属性摘要（不含任何表单值），供失败时的诊断日志使用
    result['elements'] = [_element_digest(item) for item in items]

    judge = _JUDGES[role]
    accepted = []
    conflicts = []
    first_reject = None
    for item in items:
        verdict, reason, score = judge(item['info'], item['visible'], trusted, hint)
        if verdict == ACCEPT:
            accepted.append((item, score, reason))
        elif verdict == AMBIGUOUS:
            # 证据冲突（元素同时带账号语义与密码语义）：先记下来，
            # 稍后用页面上下文消歧，而不是直接当成「角色不符」
            conflicts.append((item, reason))
            if first_reject is None:
                first_reject = reason
        elif first_reject is None:
            first_reject = reason

    # 证据冲突消歧：页面上若存在**独立**的 type=password 输入框，
    # 说明真正的密码框另有其物，当前这个文本框不该被当成密码框
    if conflicts:
        accepted.extend(await _resolve_role_conflicts(locator, conflicts, role))

    result['accepted'] = len(accepted)
    if not accepted:
        reason = first_reject or 'role_mismatch'
        if reason == 'role_conflict':
            detail = (f'元素角色证据冲突（目标角色={role}）：'
                      f'账号语义与密码语义同时存在，且页面上没有独立的密码框'
                      f'可供区分，无法唯一确定')
        else:
            detail = f'元素角色与预期不符（{reason}）'
        result.update(verdict=REJECT, reason=reason, detail=detail)
        return result

    if len(accepted) == 1:
        item, _score, reason = accepted[0]
        result.update(ok=True, field=item['element'], verdict=ACCEPT,
                      note=reason)
        return result

    # 多个元素都通过了角色校验：继续筛选，避免「直接取第一个」
    strong = [entry for entry in accepted if entry[1] >= _STRONG_SCORE]
    if role == ROLE_PASSWORD:
        # 密码框：先排除「确认密码」类的二次输入框
        not_confirm = [entry for entry in strong
                       if not _is_confirm_field(entry[0]['info'])]
        if len(not_confirm) == 1:
            item, _score, reason = not_confirm[0]
            result.update(ok=True, field=item['element'], verdict=ACCEPT,
                          note=reason)
            return result
        if len(not_confirm) > 1:
            strong = not_confirm

    if len(strong) == 1:
        item, _score, reason = strong[0]
        result.update(ok=True, field=item['element'], verdict=ACCEPT,
                      note=reason)
        return result

    result.update(verdict=AMBIGUOUS, reason='ambiguous_match',
                  detail=f'选择器匹配到 {result["matched"]} 个同类元素，'
                         f'无法唯一确定（已通过角色校验 {len(accepted)} 个）')
    return result


async def inspect_element(element, role, trusted=False, hint=''):
    """对单个已定位的元素做角色校验（通用发现路径使用）。

    返回 dict：ok / field / verdict / reason / detail / note
    """
    result = {'ok': False, 'field': None, 'verdict': REJECT, 'reason': '',
              'detail': '', 'note': ''}
    if not role or role not in _JUDGES:
        result.update(ok=True, field=element, verdict=ACCEPT,
                      reason='no_role_check')
        return result
    try:
        info = await element.evaluate(_ELEMENT_INFO_JS)
    except Exception:
        info = None
    if not isinstance(info, dict):
        result.update(ok=True, field=element, verdict=ACCEPT,
                      reason='role_check_unavailable',
                      detail='无法读取元素属性，已跳过角色校验')
        return result
    try:
        visible = bool(await element.is_visible())
    except Exception:
        visible = True
    verdict, reason, _score = _JUDGES[role](info, visible, trusted, hint)
    if verdict != ACCEPT:
        result.update(verdict=verdict, reason=reason,
                      detail=f'元素角色与预期不符（{reason}）')
        return result
    result.update(ok=True, field=element, verdict=ACCEPT, note=reason)
    return result


# ============ 离线（不依赖页面）的字段映射风险检查 ============
def static_role_risk(field_key, selector):
    """检查选择器本身是否明显与目标字段角色冲突。

    用于模板校验与保存前的静态检查：这里只能发现「写法上明显不对」的
    选择器（例如把 input[type="password"] 写进登录按钮候选），
    真正的角色判定仍然以页面上的实际元素为准。

    返回风险描述字符串；无风险时返回空串。
    """
    if not isinstance(selector, dict):
        return ''
    value = str(selector.get('value', '') or '').lower()
    if not value:
        return ''

    if field_key == 'username_selectors':
        if 'type="password"' in value or "type='password'" in value:
            return '疑似密码框选择器，不能作用户名字段'
        if 'type="submit"' in value or 'type="button"' in value or \
                'type="hidden"' in value or 'type="image"' in value:
            return '疑似按钮/隐藏域选择器，不能作用户名字段'
        if value.startswith('//button') or value.startswith('button') or \
                'button[' in value:
            return '疑似按钮选择器，不能作用户名字段'
        if any(word in value for word in ('captcha', '验证码', 'checkcode',
                                          'validatecode')):
            return '疑似验证码框选择器，不能作用户名字段'
    elif field_key == 'password_selectors':
        if any(word in value for word in ('captcha', '验证码', 'checkcode',
                                          'validatecode')):
            return '疑似验证码框选择器，不能作密码字段'
        if 'type="submit"' in value or 'type="button"' in value:
            return '疑似按钮选择器，不能作密码字段'
    elif field_key == 'login_button_selectors':
        if 'type="password"' in value or "type='password'" in value:
            return '疑似密码框选择器，不能作登录按钮'
        if 'type="text"' in value or "type='text'" in value:
            return '疑似普通输入框选择器，不能作登录按钮'
        if 'type="hidden"' in value:
            return '疑似隐藏域选择器，不能作登录按钮'
    elif field_key == 'captcha_selectors':
        if 'type="password"' in value or "type='password'" in value:
            return '疑似密码框选择器，不能作验证码字段'
    return ''
