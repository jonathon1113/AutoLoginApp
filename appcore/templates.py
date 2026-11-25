"""登录模板管理器。

模板文件格式（templates/*.json）：
{
  "name": "模板名",
  "description": "描述",
  "username_selectors":   [{"by": "ID", "value": "username"}],
  "password_selectors":   [...],
  "login_button_selectors":[...]
}

by 取值沿用原 Selenium 语义：NAME / ID / XPATH / CLASS_NAME / CSS_SELECTOR / TAG_NAME，
另兼容小写别名 css / xpath / id / name / class_name / tag_name / link_text。
由 browser.to_locator() 转换为 Playwright Locator，因此历史模板文件无需修改。

加载与维护规则：
- 模板目录固定为「可写数据目录」下的 templates/（EXE 同目录 / 源码根目录），
  绝不使用 PyInstaller 的 _MEIPASS 只读解包目录，保证用户可手工增删改模板。
- 磁盘上不存在默认模板文件时才创建，已存在的（含用户手工改过的）一律保留。
- 单个模板文件损坏/校验失败只影响该文件，其余模板照常可用。
"""

import json
import os
import re
import tempfile
import threading

from .config import TEMPLATE_DIR
from .element_roles import static_role_risk
from .logging_utils import Logger

# 模板必须包含的选择器字段
TEMPLATE_FIELDS = ('username_selectors', 'password_selectors', 'login_button_selectors')

# 模板的可选选择器字段（存在即生效，缺失不报错、不告警）
# captcha_selectors：验证码输入框的定位规则。验证码页面的模板必须能保存它，
# 否则同一台设备下次登录时又要重新识别验证码框。
# captcha_image_selectors：验证码「图片」的定位规则（新增可选字段）。
# 自动识别验证码时需要先定位图片再截图 OCR；把它存进模板可以让第二次
# 登录直接命中模板来源，避免每次都重新做语义查找 / 几何兜底。
# 历史模板没有该字段时静默补空列表，不得产生告警刷屏。
OPTIONAL_TEMPLATE_FIELDS = ('captcha_selectors', 'captcha_image_selectors')

# 全部会被校验 / 归一化 / 比较 / 保存的字段
ALL_TEMPLATE_FIELDS = TEMPLATE_FIELDS + OPTIONAL_TEMPLATE_FIELDS

# 支持的定位方式（统一大写），值为归一化后的标准名称
SUPPORTED_BY = {
    'NAME': 'NAME',
    'ID': 'ID',
    'XPATH': 'XPATH',
    'CLASS_NAME': 'CLASS_NAME',
    'CSS_SELECTOR': 'CSS_SELECTOR',
    'CSS': 'CSS_SELECTOR',
    'TAG_NAME': 'TAG_NAME',
    'LINK_TEXT': 'LINK_TEXT',
}

# 模板名称中的非法字符（与 Windows 文件名规则一致）
INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')

MAX_TEMPLATE_NAME_LEN = 64

# ============ 内置候选选择器规则 ============
# 这些规则同时服务于：
#   1) 内置默认模板（DEFAULT_TEMPLATE）；
#   2) 无模板时的通用元素发现（appcore/browser.py）。
# 编排原则：
# - 原有规则全部保留，不删除任何已生效的选择器；
# - 新规则按「可靠性高、歧义低」插入到对应位置，不做全局固定选择器；
# - 多个输入框共享同一 class 时，用 type / placeholder / name / id 组合消歧；
# - 密码框可能实际是 type="text"，因此不能只依赖 type=password；
# - ID 中含点号（如 form.userID）时用属性选择器，避免点号被当成 class 分隔符；
# - 不使用易随构建/运行状态变化的属性（如 Angular 的 _ngcontent-* / ng-tns-* /
#   ng-star-inserted / ng-dirty / ng-valid）作为首选定位条件。

USERNAME_SELECTORS = [
    # 高可信度优先：autocomplete / type=email / name / id 这类精确属性放前面。
    {'by': 'CSS_SELECTOR', 'value': 'input[autocomplete="username"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[type="email"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="username"]'},
    {'by': 'NAME', 'value': 'username'},
    {'by': 'ID', 'value': 'username'},
    {'by': 'CSS_SELECTOR', 'value': 'input[autocomplete="email"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="email"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id="email"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="user"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="userName"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id="user"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="account"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id="account"]'},
    # q-input 登录页：用户名 / 密码 / 验证码三个框共享 .q-input__inner，
    # 必须用 type + placeholder 组合消歧，不能只看 class。
    {'by': 'CSS_SELECTOR',
     'value': 'input.q-input__inner[type="text"][placeholder="请输入用户名"]'},
    {'by': 'CSS_SELECTOR',
     'value': 'input.q-input__inner[placeholder="请输入用户名"]'},
    {'by': 'CSS_SELECTOR',
     'value': 'input.q-input__inner[placeholder="用户名"]'},
    # form.userID 登录页：ID 中含点号，用属性选择器 / ID 方式定位。
    {'by': 'CSS_SELECTOR', 'value': 'input[id="form.userID"]'},
    {'by': 'ID', 'value': 'form.userID'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="loginName"]'},
    {'by': 'CSS_SELECTOR',
     'value': 'input.username[placeholder="请输入用户名"]'},
    # UserName / UserPasswd 登录页
    {'by': 'CSS_SELECTOR', 'value': 'input#UserName'},
    {'by': 'NAME', 'value': 'UserName'},
    # loginName 登录页
    {'by': 'CSS_SELECTOR', 'value': 'input#loginName'},
    {'by': 'NAME', 'value': 'loginName'},
    # Ant Design / Angular 登录页：formcontrolname 是稳定的语义属性。
    {'by': 'CSS_SELECTOR', 'value': 'input[formcontrolname="username"]'},
    # 宽泛的 placeholder / XPath 兜底放最后。
    {'by': 'CSS_SELECTOR', 'value': 'input[placeholder="用户名"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[placeholder="请输入用户名"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[placeholder="账号"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[placeholder="邮箱"]'},
    {'by': 'XPATH', 'value': "//input[contains(@placeholder, '邮箱')]"},
    {'by': 'XPATH', 'value': "//input[contains(@placeholder, '用户')]"},
    {'by': 'XPATH', 'value': "//input[contains(@id, 'username')]"},
    # 低优先级规则：login 语义含糊（页面上的「login」更可能是登录按钮或
    # 登录操作控件），因此放在所有语义明确的规则之后、宽泛兜底之前。
    # 命中后仍会经过元素角色校验：按钮 / 密码框 / 验证码框会被直接拒绝。
    {'by': 'CSS_SELECTOR', 'value': 'input[name="login"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id="login"]'},
    {'by': 'XPATH', 'value': "//input[@type='text']"},
]

PASSWORD_SELECTORS = [
    {'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'},
    {'by': 'NAME', 'value': 'password'},
    {'by': 'ID', 'value': 'password'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="password"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[autocomplete="current-password"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="passwd"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="pwd"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id="passwd"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id="pwd"]'},
    # form.password 登录页：ID 含点号
    {'by': 'CSS_SELECTOR', 'value': 'input[id="form.password"]'},
    {'by': 'ID', 'value': 'form.password'},
    # UserPasswd 登录页
    {'by': 'CSS_SELECTOR', 'value': 'input#UserPasswd'},
    {'by': 'NAME', 'value': 'UserPasswd'},
    # 密码框实际为 type="text" 的页面（不能只依赖 type=password）：
    # 借助 id / name / class / placeholder 消歧，避免把同名文本框误当密码框。
    {'by': 'CSS_SELECTOR', 'value': 'input.password[placeholder="请输入密码"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input.password'},
    {'by': 'XPATH', 'value': "//input[@type='text' and @id='password']"},
    {'by': 'XPATH', 'value': "//input[@type='text' and @name='password']"},
    # Ant Design / Angular 登录页
    {'by': 'CSS_SELECTOR', 'value': 'input#password[type="password"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[placeholder="密码"]'},
    {'by': 'XPATH', 'value': "//input[contains(@placeholder, '密码')]"},
    {'by': 'XPATH', 'value': "//input[contains(@id, 'password')]"},
]

LOGIN_BUTTON_SELECTORS = [
    {'by': 'CSS_SELECTOR', 'value': 'button[type="submit"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[type="submit"]'},
    # type="button" 的登录按钮（不是表单提交按钮），用 value 精确限定。
    {'by': 'CSS_SELECTOR', 'value': 'input[type="button"][value="Login"]'},
    # 用 contains(., ...) 而非 contains(text(), ...)：
    # 很多框架（ExtJS / Ant Design 等）把按钮文字放在子 span 里，
    # text() 只取直接文本节点会匹配不到。
    {'by': 'XPATH', 'value': "//button[contains(., '登录')]"},
    {'by': 'XPATH', 'value': "//button[contains(., '登陆')]"},
    {'by': 'XPATH', 'value': "//button[contains(., 'Sign In')]"},
    {'by': 'XPATH', 'value': "//button[contains(., 'Sign in')]"},
    {'by': 'XPATH', 'value': "//button[contains(., 'Log in')]"},
    {'by': 'XPATH', 'value': "//button[contains(., 'Login')]"},
    # 按钮文字带空格（如“登 录”）时，先做空白归一化再匹配。
    {'by': 'XPATH',
     'value': "//button[contains(normalize-space(.), '登') and "
              "contains(normalize-space(.), '录')]"},
    {'by': 'NAME', 'value': 'submit'},
    {'by': 'CLASS_NAME', 'value': 'submit-button'},
    # Ant Design / Angular 登录按钮：nz-button 是稳定的语义属性。
    {'by': 'CSS_SELECTOR', 'value': 'button[nz-button]'},
    {'by': 'CSS_SELECTOR', 'value': 'button.ant-btn'},
    # ---- <a> / <div> 形式的登录按钮（很多设备管理页如 H3C WebUI 就是
    #      <a id="myButton" class="submit">立刻登录</a>）----
    # 注意：这些规则必须排在泛化的 ID 规则之前，否则会先命中页面上
    # 不可见的 id="login" 容器，点了没反应，表现为「登录结果未确认」。
    {'by': 'XPATH', 'value': "//button[contains(., '确认登录')]"},
    {'by': 'XPATH', 'value': "//a[contains(., '立刻登录')]"},
    {'by': 'XPATH', 'value': "//a[contains(., '确认登录')]"},
    {'by': 'XPATH', 'value': "//a[contains(., '登录')]"},
    {'by': 'XPATH', 'value': "//a[contains(., '登陆')]"},
    {'by': 'XPATH', 'value': "//a[contains(., '提交')]"},
    {'by': 'XPATH', 'value': "//*[@class='submit']"},
    {'by': 'XPATH', "value": "//*[contains(@class, 'submit') and "
                            "(contains(@class, 'btn') or contains(@class, 'button'))]"},
    {'by': 'CSS_SELECTOR', 'value': 'input[type="button"][value*="登录"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[type="submit"][value*="登录"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[type="button"][value*="提交"]'},
    {'by': 'XPATH', "value": "//a[contains(@class, 'login') and contains(., '登录')]"},
    # 泛化的 ID 规则放最后（页面可能存在不可见的同名容器）
    {'by': 'ID', 'value': 'loginBtn'},
    {'by': 'ID', 'value': 'login'},
]

CAPTCHA_SELECTORS = [
    # form.validateCode 登录页（ID 含点号）
    {'by': 'CSS_SELECTOR', 'value': 'input[id="form.validateCode"]'},
    {'by': 'ID', 'value': 'form.validateCode'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="checkCode"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input#checkCode'},
    {'by': 'NAME', 'value': 'checkCode'},
    {'by': 'ID', 'value': 'validateCode'},
    {'by': 'CLASS_NAME', 'value': 'kapkey'},
    # q-input 登录页：验证码与用户名/密码共享 class，必须用 placeholder 消歧。
    {'by': 'CSS_SELECTOR',
     'value': 'input.q-input__inner[placeholder="请输入图片验证码"]'},
    {'by': 'CSS_SELECTOR',
     'value': 'input.q-input__inner[placeholder="请输入验证码"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[placeholder="验证码"]'},
    {'by': 'XPATH', 'value': "//input[contains(@placeholder, '验证码')]"},
    {'by': 'XPATH', 'value': "//input[contains(@id, 'validateCode')]"},
    {'by': 'XPATH', 'value': "//input[contains(@id, 'checkCode')]"},
    {'by': 'XPATH', 'value': "//input[contains(@name, 'checkCode')]"},
    # 常见「验证码」命名（含 laoshuwu 一类站点的 user_code / vcode）
    {'by': 'CSS_SELECTOR', 'value': 'input[name="user_code"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input#user_code'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name*="captcha"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id*="captcha"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name*="vcode"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[id*="vcode"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name*="verify"]'},
    # 网络设备管理页（H3C 等）：input#vldcode / name=vldcode
    {'by': 'CSS_SELECTOR', 'value': 'input#vldcode'},
    {'by': 'CSS_SELECTOR', 'value': 'input[name="vldcode"]'},
    # 通用短名：input[name="code"]
    {'by': 'CSS_SELECTOR', 'value': 'input[name="code"]'},
    {'by': 'CSS_SELECTOR', 'value': 'input#code'},
]


# 默认模板（内置通用选择器）
# 候选按「可靠性高、歧义低」排序（详见上方 USERNAME_SELECTORS 等常量）：
# - 优先语义明确的属性（autocomplete / type / name / id / formcontrolname）；
# - 避免使用过宽的选择器（如裸 input[type=text]）误匹配搜索框；
# - 裸文本框兜底放在最后。
DEFAULT_TEMPLATE = {
    'name': 'default',
    'description': '内置通用登录模板（未指定模板或设备模板失败时回退使用）',
    'username_selectors': list(USERNAME_SELECTORS),
    'password_selectors': list(PASSWORD_SELECTORS),
    'login_button_selectors': list(LOGIN_BUTTON_SELECTORS),
    'captcha_selectors': list(CAPTCHA_SELECTORS),
    # 验证码图片：默认用语义规则（由 browser.find_captcha_image 负责匹配），
    # 这里保存空列表表示「尚未录制具体选择器」。
    'captcha_image_selectors': [],
}

# 预置模板文件内容
PRESET_TEMPLATES = {
    'default.json': DEFAULT_TEMPLATE,
    'proxmox.json': {
        'name': 'proxmox',
        'description': 'Proxmox VE 登录页面',
        'username_selectors': [
            {'by': 'NAME', 'value': 'username'},
            {'by': 'ID', 'value': 'username'},
            {'by': 'CSS_SELECTOR', 'value': 'input[autocomplete="username"]'},
        ],
        'password_selectors': [
            {'by': 'NAME', 'value': 'password'},
            {'by': 'ID', 'value': 'password'},
            {'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'},
        ],
        'login_button_selectors': [
            # 实测 Proxmox VE 的登录按钮是 ExtJS 的 <a class="x-btn">Login</a>，
            # 既不是 <button> 也不是 type=submit，且 id 带序号会变化，只能按文本+样式定位
            {'by': 'XPATH', 'value': "//a[contains(@class, 'x-btn') and contains(., 'Login')]"},
            {'by': 'XPATH', 'value': "//button[contains(., 'Login')]"},
            {'by': 'XPATH', 'value': "//button[contains(., '登录')]"},
            {'by': 'ID', 'value': 'pvploginbtn'},
        ],
        # 与磁盘上的 templates/proxmox.json 保持字段一致（空列表表示该页面无验证码框）。
        # 若内置版本缺这个字段，启动时的“补齐缺失字段”会把用户文件改写一次。
        'captcha_selectors': [],
        'captcha_image_selectors': [],
    },
    'huawei.json': {
        'name': 'huawei',
        'description': '华为防火墙/交换机登录页面',
        'username_selectors': [
            {'by': 'ID', 'value': 'username'},
            {'by': 'NAME', 'value': 'username'},
            {'by': 'XPATH', 'value': "//input[@placeholder='用户名']"},
            {'by': 'CSS_SELECTOR', 'value': 'input[autocomplete="username"]'},
        ],
        'password_selectors': [
            # 实测华为防火墙登录页：真实密码框 id/name 为 platcontent；
            # 页面上另有一个 type=hidden 的 #password（不可见），因此不放在首位。
            {'by': 'ID', 'value': 'platcontent'},
            {'by': 'NAME', 'value': 'platcontent'},
            {'by': 'ID', 'value': 'password'},
            {'by': 'NAME', 'value': 'password'},
            {'by': 'XPATH', 'value': "//input[@placeholder='密码']"},
            {'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'},
        ],
        'login_button_selectors': [
            # 实测华为防火墙登录页：登录按钮为 <button id="btn_login-button">Login</button>
            {'by': 'ID', 'value': 'btn_login-button'},
            {'by': 'XPATH', 'value': "//button[contains(., 'Login')]"},
            {'by': 'XPATH', 'value': "//button[@type='button' and contains(@onclick, 'login')]"},
            {'by': 'ID', 'value': 'loginBtn'},
            {'by': 'CSS_SELECTOR', 'value': 'button[type="submit"]'},
            {'by': 'XPATH', 'value': "//button[contains(., '登录')]"},
        ],
        # 与磁盘上的 templates/huawei.json 保持字段一致（空列表表示该页面无验证码框）。
        'captcha_selectors': [],
        'captcha_image_selectors': [],
    }
}


# 曾在内置预置模板中出现过、但现已移除的选择器。
# 保留用于历史兼容与诊断（判断磁盘模板与内置版本的差异来源）。
LEGACY_PRESET_SELECTORS = {
    ('ID', 'btn_login-button'),
    ('XPATH', "//button[contains(text(), 'Login')]"),
    ('XPATH', "//button[contains(text(), '登录')]"),
    ('XPATH', "//a[contains(@class, 'x-btn') and contains(text(), 'Login')]"),
    ('XPATH', "//input[@id='username']"),
    ('XPATH', "//input[@id='password']"),
}


def _same_selector_list(left, right):
    """两个选择器列表是否逐项完全一致（顺序也要求一致）"""
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        if str(a.get('by', '')).strip().upper() != str(b.get('by', '')).strip().upper():
            return False
        if str(a.get('value', '')).strip() != str(b.get('value', '')).strip():
            return False
    return True


def _same_template_content(left, right):
    """两个模板的内容是否完全一致（字段、顺序、描述都一致）"""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    for field in ALL_TEMPLATE_FIELDS:
        if not _same_selector_list(left.get(field), right.get(field, []) or []):
            return False
    return str(left.get('description', '') or '') == str(right.get('description', '') or '')


def validate_template_name(name):
    """校验模板名称，返回 (是否合法, 错误原因)"""
    if not name or not str(name).strip():
        return False, "模板名称不能为空"
    name = str(name).strip()
    if len(name) > MAX_TEMPLATE_NAME_LEN:
        return False, f"模板名称过长（最多 {MAX_TEMPLATE_NAME_LEN} 个字符）"
    if name in ('.', '..'):
        return False, "模板名称非法"
    if INVALID_NAME_CHARS.search(name):
        return False, "模板名称不能包含 \\ / : * ? \" < > | 等字符"
    if name.lower() == 'default':
        return False, "'default' 是内置模板名，不允许覆盖"
    return True, ""


def _collect_role_risks(data):
    """收集模板中「写法上明显与字段角色冲突」的选择器。

    返回 [(字段, 索引, 选择器值, 风险说明), ...]；没有风险时返回空列表。

    这里只能发现「写法上明显不对」的选择器（例如把 input[type="password"]
    写进用户名候选、或把普通输入框写进登录按钮候选），
    真正的角色判定仍然以页面上的实际元素为准（见 appcore/element_roles.py）。
    """
    risks = []
    if not isinstance(data, dict):
        return risks
    for field in ALL_TEMPLATE_FIELDS:
        items = data.get(field)
        if not isinstance(items, list):
            continue
        for index, selector in enumerate(items):
            if not isinstance(selector, dict):
                continue
            risk = static_role_risk(field, selector)
            if risk:
                risks.append((field, index,
                              str(selector.get('value', '') or '').strip(), risk))
    return risks


def validate_template(data, source='', check_roles=True):
    """校验模板数据结构。

    返回 (致命错误列表, 警告列表, 归一化后的模板数据)。
    - 致命错误：模板无法使用（如内容不是 JSON 对象、字段类型错误），应跳过该文件；
    - 警告：模板仍可加载，但存在缺失字段 / 非法选择器 / 空选择器 /
            字段与元素角色写法冲突等问题，登录时对应部分会自动回退到通用元素发现。

    归一化过程会补齐缺失字段、丢弃非法选择器、把 by 统一为大写标准名。
    check_roles=False 时跳过「字段 <-> 元素角色」的静态映射检查。
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        return ['模板内容必须是 JSON 对象'], [], None

    normalized = dict(data)
    normalized.setdefault('name', '')
    normalized.setdefault('description', '')
    if not isinstance(normalized.get('description'), str):
        normalized['description'] = str(normalized.get('description') or '')

    for key in TEMPLATE_FIELDS:
        if key not in normalized:
            normalized[key] = []
            warnings.append(f"缺少字段 {key}（已按空列表处理）")
        value = normalized[key]
        if not isinstance(value, list):
            errors.append(f"字段 {key} 必须是数组")
            normalized[key] = []
            continue
        cleaned = []
        for index, selector in enumerate(value):
            if not isinstance(selector, dict):
                warnings.append(f"{key}[{index}] 不是对象，已忽略")
                continue
            raw_by = str(selector.get('by', '')).strip()
            by_key = raw_by.upper()
            if by_key not in SUPPORTED_BY:
                warnings.append(
                    f"{key}[{index}] 的定位方式 '{raw_by}' 不受支持，已忽略"
                    f"（可用: {', '.join(sorted(set(SUPPORTED_BY.values())))}）"
                )
                continue
            raw_value = selector.get('value', '')
            if not isinstance(raw_value, str) or not raw_value.strip():
                warnings.append(f"{key}[{index}] 的 value 为空，已忽略")
                continue
            cleaned.append({'by': SUPPORTED_BY[by_key], 'value': raw_value.strip()})
        normalized[key] = cleaned

    # 可选字段：缺失时静默补空列表（历史模板文件不含验证码选择器，不应告警）
    for key in OPTIONAL_TEMPLATE_FIELDS:
        if key not in normalized:
            normalized[key] = []
            continue
        value = normalized[key]
        if not isinstance(value, list):
            warnings.append(f"字段 {key} 必须是数组，已按空列表处理")
            normalized[key] = []
            continue
        cleaned = []
        for index, selector in enumerate(value):
            if not isinstance(selector, dict):
                warnings.append(f"{key}[{index}] 不是对象，已忽略")
                continue
            raw_by = str(selector.get('by', '')).strip()
            by_key = raw_by.upper()
            if by_key not in SUPPORTED_BY:
                warnings.append(
                    f"{key}[{index}] 的定位方式 '{raw_by}' 不受支持，已忽略"
                    f"（可用: {', '.join(sorted(set(SUPPORTED_BY.values())))}）"
                )
                continue
            raw_value = selector.get('value', '')
            if not isinstance(raw_value, str) or not raw_value.strip():
                warnings.append(f"{key}[{index}] 的 value 为空，已忽略")
                continue
            cleaned.append({'by': SUPPORTED_BY[by_key], 'value': raw_value.strip()})
        normalized[key] = cleaned

    if not normalized['username_selectors']:
        warnings.append("username_selectors 为空，使用该模板时将回退到通用用户名框查找")
    if not normalized['password_selectors']:
        warnings.append("password_selectors 为空，使用该模板时将回退到通用密码框查找")

    # 字段 <-> 元素角色的静态映射检查：只提示、不阻断。
    # 「选择器命中了某个元素」不等于「这个元素确实是该角色的字段」，
    # 真正的判定仍然发生在页面上（见 appcore/element_roles.py）。
    if check_roles:
        for field, index, value, risk in _collect_role_risks(normalized):
            warnings.append(f"{field}[{index}] 「{value}」{risk}")

    if source:
        for message in errors:
            Logger.error(f"模板校验失败 [{source}]: {message}")
        for message in warnings:
            Logger.warning(f"模板校验提示 [{source}]: {message}")

    return errors, warnings, normalized


class TemplateManager:
    """登录模板管理器 - 支持自定义定位器"""

    _templates = {}        # 模板名 -> 模板数据
    _sources = {}          # 模板名 -> 来源文件路径
    _errors = []           # 本次加载的错误记录
    _file_errors = {}      # 模板文件名 -> 该文件的加载失败原因（区分“不存在”与“文件损坏”）
    _loaded = False
    _lock = threading.RLock()
    _recordings = {}       # 线程 id -> 录制中的选择器
    _last_recorded = None  # 最近一次完成的录制结果（供界面读取/手动保存）

    # ============ 目录 ============
    @classmethod
    def get_template_dir(cls):
        """获取模板目录（可写数据目录下的 templates/）"""
        return TEMPLATE_DIR

    @classmethod
    def ensure_template_dir(cls):
        """确保模板目录存在，失败时给出明确日志"""
        try:
            if not os.path.isdir(TEMPLATE_DIR):
                os.makedirs(TEMPLATE_DIR, exist_ok=True)
                Logger.info(f"已创建模板目录: {TEMPLATE_DIR}")
            return TEMPLATE_DIR
        except Exception as e:
            Logger.error(f"模板目录不可用 {TEMPLATE_DIR}: {e}")
            return None

    # ============ 加载 ============
    @classmethod
    def load_templates(cls, force=False):
        """加载所有模板文件。

        force=True 时强制重新读取磁盘（用于用户手工修改模板后的重载）。
        单个文件损坏只影响该文件，其余模板照常加载。
        """
        with cls._lock:
            if cls._loaded and not force:
                return cls._templates

            templates = {}
            sources = {}
            errors = []
            file_errors = {}

            template_dir = cls.ensure_template_dir()
            if not template_dir:
                cls._templates = templates
                cls._sources = sources
                cls._errors = [f"模板目录不可用: {TEMPLATE_DIR}"]
                cls._file_errors = {}
                cls._loaded = True
                return templates

            try:
                filenames = sorted(os.listdir(template_dir))
            except Exception as e:
                Logger.error(f"读取模板目录失败 {template_dir}: {e}")
                cls._templates = templates
                cls._sources = sources
                cls._errors = [f"读取模板目录失败: {e}"]
                cls._file_errors = {}
                cls._loaded = True
                return templates

            for filename in filenames:
                if not filename.lower().endswith('.json'):
                    continue
                path = os.path.join(template_dir, filename)
                if not os.path.isfile(path):
                    continue
                try:
                    # utf-8-sig 兼容带 BOM 的 UTF-8 文件（Windows 记事本等工具默认会写入 BOM）
                    with open(path, encoding='utf-8-sig') as handle:
                        data = json.load(handle)
                except Exception as e:
                    message = f"模板文件解析失败 {filename}: {e}"
                    Logger.error(message)
                    errors.append(message)
                    file_errors[filename] = message
                    continue

                errs, warns, normalized = validate_template(data, source=filename)
                if errs:
                    message = f"模板文件不可用 {filename}: {errs[0]}"
                    Logger.error(message)
                    errors.append(message)
                    file_errors[filename] = message
                    continue
                for warn in warns:
                    Logger.warning(f"模板文件提示 {filename}: {warn}")

                stem = filename[:-5]
                template_name = str(normalized.get('name') or stem).strip() or stem
                normalized['name'] = template_name

                # 模板名与文件名分别登记，兼容「设备配置写文件名」与「写 name 字段」两种用法
                for key in (template_name, stem):
                    if key in templates and templates[key] is not normalized:
                        Logger.warning(
                            f"模板名冲突: '{key}' 同时来自 {sources.get(key)} 与 {filename}，"
                            f"以 {filename} 为准"
                        )
                    templates[key] = normalized
                    sources[key] = path

            cls._templates = templates
            cls._sources = sources
            cls._errors = errors
            cls._file_errors = file_errors
            cls._loaded = True

            Logger.info(
                f"模板加载完成: {len(templates)} 个模板（目录 {template_dir}）"
                + (f"，{len(errors)} 个文件存在问题" if errors else "")
            )
            for message in errors:
                Logger.error(message)
            return templates

    @classmethod
    def reload_templates(cls):
        """强制重新加载磁盘上的模板（用户手工修改后调用）"""
        with cls._lock:
            cls._loaded = False
        return cls.load_templates(force=True)

    @classmethod
    def get_load_errors(cls):
        """返回最近一次加载的错误记录"""
        return list(cls._errors)

    @classmethod
    def get_file_errors(cls):
        """返回 {模板文件名: 失败原因}（仅包含确实损坏 / 解析失败的文件）"""
        if not cls._loaded:
            cls.load_templates()
        return dict(cls._file_errors)

    @classmethod
    def snapshot_templates(cls):
        """拍摄当前模板注册表快照。

        用于「刷新配置」失败时回滚：刷新必须先校验新配置再切换，
        校验不通过时保留最后一次有效配置，而不是把界面清空。
        """
        with cls._lock:
            return (dict(cls._templates), dict(cls._sources), list(cls._errors),
                    dict(cls._file_errors))

    @classmethod
    def restore_templates(cls, snapshot):
        """恢复模板注册表快照（配置刷新失败时保留最后一次有效配置）"""
        templates, sources, errors, file_errors = snapshot
        with cls._lock:
            cls._templates = dict(templates)
            cls._sources = dict(sources)
            cls._errors = list(errors)
            cls._file_errors = dict(file_errors)
            cls._loaded = True
        Logger.info("已回滚到上一次有效的模板配置")

    @classmethod
    def list_templates(cls):
        """返回已加载的模板名列表（去重）"""
        if not cls._loaded:
            cls.load_templates()
        seen = []
        for name in cls._templates:
            if name not in seen:
                seen.append(name)
        return seen

    @classmethod
    def get_template_source(cls, template_name):
        """返回模板对应的磁盘文件路径"""
        if not cls._loaded:
            cls.load_templates()
        return cls._sources.get(template_name, '')

    @classmethod
    def template_exists(cls, template_name):
        """模板是否已存在"""
        if not cls._loaded:
            cls.load_templates()
        return template_name in cls._templates

    @classmethod
    def inspect_template(cls, template_name):
        """检查模板状态（存在 / 可加载 / 失败原因）。

        与 get_template 的区别：get_template 只回答「能不能用」，
        inspect_template 额外回答「文件是否存在」「为什么不能用」，
        从而把「模板不存在」与「模板文件存在但损坏」严格区分开。

        返回 dict：
          name        规范化后的模板名（去掉 .json 后缀）
          exists      模板文件是否存在于模板目录
          loadable    是否已成功加载并通过校验
          path        模板文件绝对路径（文件存在时非空）
          template    模板数据（loadable 时有效）
          error_type  '' / 'missing' / 'parse' / 'invalid' / 'builtin'
          reason      不可用时的原因说明
        """
        if not cls._loaded:
            cls.load_templates()

        name = str(template_name or '').strip()
        if name.lower().endswith('.json'):
            name = name[:-5]

        result = {'name': name, 'exists': False, 'loadable': False, 'path': '',
                  'template': None, 'error_type': '', 'reason': ''}
        if not name:
            result['error_type'] = 'missing'
            result['reason'] = '模板名为空'
            return result

        if name.lower() == 'default':
            template = cls._templates.get('default')
            result['exists'] = os.path.exists(os.path.join(TEMPLATE_DIR, 'default.json'))
            result['path'] = cls._sources.get('default', '')
            if template is not None:
                result['loadable'] = True
                result['template'] = template
            else:
                result['error_type'] = 'builtin'
                result['reason'] = '默认模板文件不存在或未通过校验（将使用内置默认模板）'
            return result

        template = cls._templates.get(name)
        if template is not None:
            result['exists'] = True
            result['loadable'] = True
            result['path'] = cls._sources.get(name, '')
            result['template'] = template
            return result

        filename = f'{name}.json'
        path = os.path.join(TEMPLATE_DIR, filename)
        if os.path.exists(path):
            # 文件存在但没有进入注册表 -> 解析失败或校验失败（不是“不存在”）
            result['exists'] = True
            result['path'] = path
            message = cls._file_errors.get(filename, '')
            result['error_type'] = 'parse' if '解析失败' in message else 'invalid'
            result['reason'] = message or f'模板文件存在但未通过加载校验（{filename}）'
            return result

        result['error_type'] = 'missing'
        result['reason'] = f"模板目录 {TEMPLATE_DIR} 中不存在 {filename}"
        return result

    @classmethod
    def template_covers(cls, template_name, recorded):
        """判断模板是否已包含本次录制的全部选择器。

        返回 (是否覆盖, 未被覆盖的选择器描述列表)。

        注意：这里判断的是「包含关系」而不是列表全等——
        录制结果通常只有 1~3 个实际命中的选择器，而模板中可能有十几条候选，
        用全等比较会导致几乎永远不相等，从而反复提示保存模板。
        """
        template = cls.get_template(template_name)
        if not template:
            return False, []

        def _key(selector):
            if not isinstance(selector, dict):
                return None
            return (str(selector.get('by', '')).strip().upper(),
                    str(selector.get('value', '')).strip())

        missing = []
        for field in ALL_TEMPLATE_FIELDS:
            existing = set()
            for selector in (template.get(field) or []):
                key = _key(selector)
                if key:
                    existing.add(key)
            for selector in (recorded or {}).get(field, []) or []:
                key = _key(selector)
                if key is None:
                    continue
                if key not in existing:
                    missing.append(f"{field}: {key[0]}={key[1]}")
        return (not missing), missing

    # ============ 取用 ============
    @classmethod
    def get_template(cls, template_name):
        """获取指定模板。

        返回 None 表示模板不存在（调用方应记录原因并按兼容规则处理，
        绝不静默套用其它模板）。
        """
        if not cls._loaded:
            cls.load_templates()

        if not template_name or not str(template_name).strip():
            return None

        key = str(template_name).strip()
        if key.lower().endswith('.json'):
            # 兼容设备配置中直接写文件名（含 .json）的用法
            key = key[:-5]
        if key.lower() == 'default':
            return cls._templates.get('default', DEFAULT_TEMPLATE)

        return cls._templates.get(key)

    @classmethod
    def get_template_or_default(cls, template_name):
        """获取模板；不存在时记录原因并回退到内置通用模板。"""
        template = cls.get_template(template_name)
        if template is not None:
            return template
        Logger.warning(
            f"模板 '{template_name}' 不存在或不可用，改用内置通用模板(default)"
        )
        return DEFAULT_TEMPLATE

    # ============ 录制 ============
    @classmethod
    def _tid(cls):
        return threading.get_ident()

    @classmethod
    def start_recording(cls):
        """开始记录选择器（按线程隔离，避免并发登录互相覆盖）"""
        with cls._lock:
            cls._recordings[cls._tid()] = {
                'username_selectors': [],
                'password_selectors': [],
                'login_button_selectors': [],
                'captcha_selectors': [],
                # 必须初始化该键，否则 record_selector 会静默丢数据
                'captcha_image_selectors': [],
            }
            cls._last_recorded = None

    @classmethod
    def record_selector(cls, selector_type, by, value):
        """记录一个实际生效的选择器"""
        with cls._lock:
            bucket = cls._recordings.get(cls._tid())
            if bucket is None:
                return
            if selector_type not in bucket:
                bucket[selector_type] = []
            selector = {'by': str(by).upper(), 'value': value}
            if selector not in bucket[selector_type]:
                # 最近命中的排前面，便于下次登录优先尝试
                bucket[selector_type].insert(0, selector)

    @classmethod
    def finish_recording(cls):
        """结束录制并返回本次录制的选择器（无录制内容时返回 None）"""
        with cls._lock:
            bucket = cls._recordings.pop(cls._tid(), None)
            if not bucket:
                return None
            if not any(bucket.values()):
                return None
            cls._last_recorded = bucket
            return bucket

    @classmethod
    def cancel_recording(cls):
        """取消录制"""
        with cls._lock:
            cls._recordings.pop(cls._tid(), None)

    @classmethod
    def get_last_recorded(cls):
        """获取最近一次完成的录制结果（界面线程使用）"""
        with cls._lock:
            if cls._last_recorded:
                return dict(cls._last_recorded)
            return None

    @classmethod
    def set_last_recorded(cls, selectors):
        """设置最近一次录制结果（界面线程手动保存模板时使用）"""
        with cls._lock:
            cls._last_recorded = dict(selectors) if selectors else None

    # ============ 保存 ============
    @classmethod
    def save_recorded_template(cls, template_name, description="", selectors=None):
        """保存录制的选择器为模板文件。

        流程：名称校验 -> 数据校验 -> 原子写入 -> 回读校验 -> 更新内存注册表。
        任一环节失败都返回 False，且不会留下半成品文件。
        """
        with cls._lock:
            if selectors is None:
                selectors = cls.get_last_recorded()
            if not selectors or not any(selectors.values()):
                Logger.error("保存模板失败: 没有可保存的录制选择器")
                return False

            valid, reason = validate_template_name(template_name)
            if not valid:
                Logger.error(f"保存模板失败: {reason}")
                return False
            template_name = str(template_name).strip()

            template_data = {
                'name': template_name,
                'description': description or '',
                'username_selectors': list(selectors.get('username_selectors', [])),
                'password_selectors': list(selectors.get('password_selectors', [])),
                'login_button_selectors': list(selectors.get('login_button_selectors', [])),
                # 验证码选择器：验证码页面的模板必须带上，否则下次还要重新识别
                'captcha_selectors': list(selectors.get('captcha_selectors', [])),
                # 验证码图片选择器：自动识别时用于快速定位验证码图片
                'captcha_image_selectors': list(
                    selectors.get('captcha_image_selectors', []) or []),
            }

            errors, warnings, normalized = validate_template(template_data,
                                                            source=f"{template_name}.json")
            if errors:
                Logger.error(f"保存模板失败: 模板数据校验未通过（{errors[0]}）")
                return False
            if not normalized['username_selectors'] or not normalized['password_selectors']:
                Logger.error("保存模板失败: 用户名/密码选择器不能为空")
                return False

            template_dir = cls.ensure_template_dir()
            if not template_dir:
                Logger.error(f"保存模板失败: 模板目录不可用 {TEMPLATE_DIR}")
                return False

            template_path = os.path.join(template_dir, f"{template_name}.json")
            tmp_path = None
            try:
                # 先写临时文件再原子替换，避免中途失败留下损坏的模板
                fd, tmp_path = tempfile.mkstemp(
                    prefix=f".{template_name}.", suffix=".tmp", dir=template_dir
                )
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    json.dump(normalized, handle, indent=2, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, template_path)
                tmp_path = None
            except Exception as e:
                Logger.error(f"保存模板失败 {template_name}: {e}")
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                return False

            # 回读校验：确认文件确实写入且内容有效后才算保存成功
            try:
                with open(template_path, encoding='utf-8-sig') as handle:
                    reloaded = json.load(handle)
            except Exception as e:
                Logger.error(f"保存模板失败 {template_name}: 回读校验失败 {e}")
                try:
                    os.remove(template_path)
                except Exception:
                    pass
                return False

            re_errors, _re_warnings, re_normalized = validate_template(reloaded,
                                                                        source=template_path)
            if re_errors or not re_normalized['username_selectors'] or \
                    not re_normalized['password_selectors']:
                Logger.error(f"保存模板失败 {template_name}: 回读内容无效")
                try:
                    os.remove(template_path)
                except Exception:
                    pass
                return False

            # 更新内存注册表，后续登录立即可用
            cls._templates[template_name] = re_normalized
            cls._sources[template_name] = template_path
            cls._file_errors.pop(f"{template_name}.json", None)
            cls._loaded = True

            Logger.info(f"模板已保存: {template_path}")
            return True

    # ============ 默认模板文件 ============
    @classmethod
    def _write_template_file(cls, path, data):
        """原子写入模板文件（临时文件 + 替换）"""
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.", suffix=".tmp",
                dir=os.path.dirname(path)
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            tmp_path = None
            return True
        except Exception as e:
            Logger.error(f"写入模板文件失败 {path}: {e}")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False

    @classmethod
    def _repair_preset_template(cls, path, filename, preset):
        """补齐磁盘上残缺的内置预置模板（**不覆盖用户已有内容**）。

        规则（关键：内置模板只在文件缺失时用于初始化）：
        - 文件缺失            -> 由 create_default_template_files 写入内置完整版本；
        - 文件存在            -> **绝不整体覆盖**，只补齐「缺失或为空」的字段；
        - 文件与内置版本完全一致 -> 不做任何写入（避免每次启动无谓改写磁盘）。

        这样用户在默认模板里删除 / 重排 / 新增的选择器都不会被程序覆盖；
        若确实想换成新的内置版本，请使用 replace_default_template()（需用户确认）。

        返回 (修复后的数据, 修复类型)；无需修复时返回 (None, '')。
        修复类型：'fill'（仅补齐缺失字段）
        """
        try:
            with open(path, encoding='utf-8-sig') as handle:
                data = json.load(handle)
        except Exception:
            return None, ''
        if not isinstance(data, dict):
            return None, ''

        merged = dict(data)

        # 与内置版本完全一致 -> 无需写入
        if _same_template_content(merged, preset):
            return None, ''

        # 有任何差异 -> 视为用户手工维护，只补齐缺失 / 为空的字段
        changed = False
        for field in ALL_TEMPLATE_FIELDS:
            # 内置版本本身就没有的字段，不属于“缺失字段”，不得凭空补一个空列表
            # （否则每次首次升级都会改写用户的预置模板文件）。
            if field not in preset:
                continue
            current = merged.get(field)
            if isinstance(current, list) and current:
                continue
            replacement = list(preset.get(field, []) or [])
            # 只有真正发生变化才标记为“已修改”，避免每次启动都重写磁盘文件
            if current != replacement:
                merged[field] = replacement
                changed = True
        if not merged.get('description'):
            description = preset.get('description', '')
            if description:
                merged['description'] = description
                changed = True
        return (merged, 'fill') if changed else (None, '')

    @classmethod
    def create_default_template_files(cls):
        """初始化 / 补齐预置模板文件。

        规则：
        - 文件不存在            -> 写入内置完整版本（唯一一次“内置覆盖磁盘”的场景）；
        - 文件存在              -> **不整体覆盖**，只补齐缺失 / 为空的字段；
        - 文件与内置版本完全一致 -> 不做任何写入；
        - 用户自建的模板（非预置） -> 不做任何修改。
        """
        template_dir = cls.ensure_template_dir()
        if not template_dir:
            return

        for filename, data in PRESET_TEMPLATES.items():
            path = os.path.join(template_dir, filename)
            if not os.path.exists(path):
                if cls._write_template_file(path, data):
                    Logger.info(f"已创建默认模板文件: {path}")
                continue

            # 已存在：只补齐残缺字段，用户维护的内容不动
            repaired, kind = cls._repair_preset_template(path, filename, data)
            if not repaired:
                continue
            if cls._write_template_file(path, repaired):
                Logger.warning(f"预置模板不完整，已补齐缺失字段: {path}")

    # ============ 默认模板（templates/default.json）的编辑 / 追加 / 替换 ============
    # 这里的三个动作语义完全不同，调用方不得混用：
    #   append_selectors_to_default : 只追加新选择器，已有内容一个不动；
    #   merge_template_into_default : 与另一个模板取并集（去重），已有内容一个不动；
    #   replace_default_template     : 整体覆盖（必须先取得用户明确确认）。
    DEFAULT_TEMPLATE_FILE = 'default.json'

    @classmethod
    def get_default_template_path(cls):
        """默认模板文件路径"""
        return os.path.join(TEMPLATE_DIR, cls.DEFAULT_TEMPLATE_FILE)

    @classmethod
    def read_default_template(cls):
        """读取磁盘上的默认模板。

        返回 (data, error)：成功时 error 为空串；失败时 data 为 None。
        读取失败不会修改任何内存状态。
        """
        path = cls.get_default_template_path()
        if not os.path.exists(path):
            return None, f'默认模板文件不存在: {path}'
        try:
            with open(path, encoding='utf-8-sig') as handle:
                data = json.load(handle)
        except Exception as e:
            return None, f'默认模板文件解析失败 {path}: {e}'
        errors, _warnings, normalized = validate_template(data, source=path)
        if errors:
            return None, f'默认模板文件结构无效 {path}: {errors[0]}'
        return normalized, ''

    @classmethod
    def write_default_template(cls, data, strict_roles=False):
        """写入默认模板文件（校验 -> 原子写入 -> 回读校验 -> 刷新内存）。

        仅供「追加 / 合并 / 显式替换」三个明确动作使用，
        启动与刷新流程不会自动调用本方法。

        strict_roles=True 时，「写法上明显与字段角色冲突」的选择器会直接导致
        写入失败（用于整体替换：此时模板里的全部内容都是新写入的）；
        strict_roles=False 时只记录警告（用于追加：模板里原有的、由用户自己
        维护的选择器不应该阻塞「追加新选择器」这个动作）。

        返回 (ok, message)。
        """
        errors, _warnings, normalized = validate_template(data, source='default.json')
        if errors:
            Logger.error(f"默认模板保存失败：{errors[0]}")
            return False, errors[0]

        risks = _collect_role_risks(normalized)
        if risks and strict_roles:
            field, index, value, risk = risks[0]
            message = (f'存在与字段角色冲突的选择器：{field}[{index}]「{value}」{risk}'
                       + (f'（共 {len(risks)} 处）' if len(risks) > 1 else ''))
            Logger.error(f"默认模板保存失败：{message}")
            return False, message
        for field, index, value, risk in risks:
            Logger.warning(f"默认模板角色映射提示：{field}[{index}]「{value}」{risk}")

        path = cls.get_default_template_path()
        if not cls._write_template_file(path, normalized):
            return False, f'写入默认模板失败: {path}'

        # 回读校验：确认磁盘内容确实有效后才更新内存
        try:
            with open(path, encoding='utf-8-sig') as handle:
                reloaded = json.load(handle)
        except Exception as e:
            Logger.error(f"默认模板回读校验失败 {path}: {e}")
            return False, f'默认模板回读校验失败: {e}'
        re_errors, _re_warnings, re_normalized = validate_template(reloaded,
                                                                   source=path)
        if re_errors:
            Logger.error(f"默认模板回读内容无效 {path}: {re_errors[0]}")
            return False, f'默认模板回读内容无效: {re_errors[0]}'

        with cls._lock:
            cls._templates['default'] = re_normalized
            cls._sources['default'] = path
            cls._file_errors.pop(cls.DEFAULT_TEMPLATE_FILE, None)
            cls._loaded = True
        Logger.info(f"默认模板已更新: {path}")
        return True, ''

    @classmethod
    def _filter_risky_selectors(cls, field_key, selectors):
        """过滤掉「写法上明显与目标字段角色冲突」的选择器。

        返回 (可用选择器列表, 被拒绝的说明列表)。
        """
        usable = []
        rejected = []
        for selector in selectors or []:
            if not isinstance(selector, dict):
                continue
            value = str(selector.get('value', '') or '').strip()
            if not value:
                continue
            risk = static_role_risk(field_key, {'by': selector.get('by', ''),
                                                'value': value})
            if risk:
                rejected.append(f"{value}（{risk}）")
                continue
            usable.append({'by': str(selector.get('by', '')).strip().upper(),
                           'value': value})
        return usable, rejected

    @classmethod
    def append_selectors_to_default(cls, selectors, fields=None):
        """向默认模板**追加**选择器（已有选择器一个都不会被删改）。

        selectors: {'username_selectors': [{'by':..., 'value':...}, ...], ...}
        fields:    限定要处理的字段；None 表示全部字段。

        返回 (ok, message, detail)：
          detail = {'added': {字段: 新增条数}, 'skipped': {字段: 重复条数},
                    'rejected': {字段: [被拒绝的选择器说明]}}
        """
        current, error = cls.read_default_template()
        if current is None:
            Logger.error(f"追加默认模板失败：{error}")
            return False, error, {}

        target_fields = [f for f in ALL_TEMPLATE_FIELDS
                         if not fields or f in fields]
        added = {}
        skipped = {}
        rejected = {}
        changed = False

        for field in target_fields:
            incoming = selectors.get(field) if isinstance(selectors, dict) else None
            if not incoming:
                continue
            usable, refused = cls._filter_risky_selectors(field, incoming)
            if refused:
                rejected[field] = refused
                Logger.warning(
                    f"追加默认模板时拒绝了 {len(refused)} 条角色冲突的选择器"
                    f"（字段 {field}）：{'; '.join(refused)}")
            existing = list(current.get(field) or [])
            existing_keys = {(str(item.get('by', '')).upper(),
                             str(item.get('value', '')).strip())
                            for item in existing if isinstance(item, dict)}
            new_items = []
            dup_count = 0
            for item in usable:
                key = (item['by'], item['value'])
                if key in existing_keys:
                    dup_count += 1
                    continue
                existing_keys.add(key)
                new_items.append(item)
            if dup_count:
                skipped[field] = dup_count
            if new_items:
                existing.extend(new_items)
                current[field] = existing
                added[field] = len(new_items)
                changed = True

        if not changed:
            message = '没有需要追加的新选择器（已存在的选择器不会重复写入）'
            Logger.info(f"追加默认模板：{message}")
            return True, message, {'added': added, 'skipped': skipped,
                                   'rejected': rejected}

        ok, message = cls.write_default_template(current)
        if not ok:
            return False, message, {'added': added, 'skipped': skipped,
                                    'rejected': rejected}
        total = sum(added.values())
        message = f'已向默认模板追加 {total} 条选择器'
        Logger.info(message)
        return True, message, {'added': added, 'skipped': skipped,
                               'rejected': rejected}

    @classmethod
    def merge_template_into_default(cls, template_name):
        """把某个模板的选择器**合并**进默认模板（取并集并去重）。

        默认模板中已有的选择器不会被删除或改写。
        返回 (ok, message, detail)。
        """
        if not cls._loaded:
            cls.load_templates()
        source = cls._templates.get(template_name)
        if not source:
            message = f'模板不存在或不可用: {template_name}'
            Logger.error(f"合并默认模板失败：{message}")
            return False, message, {}
        ok, message, detail = cls.append_selectors_to_default(
            {field: source.get(field) or [] for field in ALL_TEMPLATE_FIELDS})
        if ok:
            message = f'已把模板「{template_name}」的选择器合并到默认模板'
        return ok, message, detail

    @classmethod
    def replace_default_template(cls, data=None):
        """用给定数据（缺省为内置版本）**整体替换**默认模板文件。

        该操作会丢弃默认模板中已有的全部内容，
        因此调用方必须先取得用户的明确确认。
        返回 (ok, message)。
        """
        payload = dict(data) if data else dict(DEFAULT_TEMPLATE)
        payload.setdefault('name', 'default')
        # 整体替换：模板内容全部是新写入的，角色冲突必须直接拒绝
        ok, message = cls.write_default_template(payload, strict_roles=True)
        if ok:
            Logger.warning("默认模板已被整体替换为指定版本")
        return ok, message


# ============ 模板保存提示的统一判断规则 ============
def suggest_template_name(device_name):
    """由设备名生成建议的模板名（与旧版规则一致）"""
    name = str(device_name or '').replace(' ', '_').replace('/', '_').replace(':', '_')
    return name[:20] or 'new_template'


def evaluate_save_template_request(configured_template, recorded, device_name=''):
    """统一判断「本次登录是否需要提示用户保存模板」。

    所有登录入口（单设备登录 / 快捷登录 / 分组批量登录）都必须调用本函数，
    保证判断规则完全一致，避免出现「模板库中已有模板却反复提示保存」的问题。

    核心原则（五个判断严格区分，不得混为一谈）：
    - 模板是否存在      -> TemplateManager.inspect_template()['exists']
    - 是否与设备配置匹配 -> configured_template 与设备配置中的 template 字段
    - 是否加载成功      -> TemplateManager.inspect_template()['loadable']
    - 是否执行成功      -> 由登录引擎的 [LOGIN_SUMMARY] 判断（不在本函数内）
    - 是否需要保存      -> 本函数的返回值

    返回 dict：
      need_prompt  是否需要弹出「保存模板」提示
      mode         'none' / 'create' / 'update'
      reason       判断依据（写入日志，便于排查）
      target_name  建议的模板名（need_prompt 为 True 时有效）
      state        设备配置模板的检查结果（inspect_template 的返回值）
    """
    decision = {'need_prompt': False, 'mode': 'none', 'reason': '',
                'target_name': '', 'state': None}

    configured = str(configured_template or '').strip()
    if configured:
        state = TemplateManager.inspect_template(configured)
        decision['state'] = state
        if state['loadable']:
            # 设备已配置可用模板 -> 直接使用，不重复提示保存
            decision['reason'] = (
                f"设备已配置可用模板 '{state['name']}'（{state['path']}），不重复提示保存")
            return decision
        if state['exists']:
            # 文件存在但损坏：记录具体原因，不当作“不存在”，也不覆盖用户文件
            decision['reason'] = (
                f"设备配置的模板 '{state['name']}' 文件存在但不可用"
                f"（{state['reason']}），为避免覆盖用户文件不提示新建")
            return decision
        # 配置引用的模板确实缺失 -> 允许提示保存（目标名沿用配置名）
        decision['need_prompt'] = True
        decision['mode'] = 'create'
        decision['target_name'] = state['name']
        decision['reason'] = (
            f"设备配置的模板 '{state['name']}' 不存在（{state['reason']}），允许提示保存新模板")
        if TemplateManager.template_exists(decision['target_name']):
            decision['mode'] = 'update'
        return decision

    # 未指定模板：只有当本次录制的选择器未被模板库中任何模板覆盖时才提示
    for name in TemplateManager.list_templates():
        covered, _missing = TemplateManager.template_covers(name, recorded)
        if covered:
            decision['reason'] = (
                f"模板库中已有模板 '{name}' 覆盖本次录制的选择器，不重复提示保存")
            return decision

    decision['need_prompt'] = True
    decision['mode'] = 'create'
    decision['target_name'] = suggest_template_name(device_name)
    decision['reason'] = (
        "本次录制的选择器尚未被模板库中任何模板覆盖，允许提示保存新模板")
    if TemplateManager.template_exists(decision['target_name']):
        decision['mode'] = 'update'
    return decision
