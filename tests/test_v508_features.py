"""V5.0.6 专项回归测试（本次问题修复 + 新增需求）。

覆盖范围：
- A 黑框（wmic.exe / 用户看到的 "vimc.exe"）：无控制台启动、进程级缓存、
  密钥派生结果不变、发货代码中不存在其它外部进程调用。
- B 五组真实登录页面 HTML 样例（q-input / form.userID / UserName+UserPasswd /
  loginName+password+checkCode / Ant Design+Angular）的识别规则。
- C 验证码页面的模板生成与保存（生成模板时绝不自动提交登录）。
- D 慢速加载页面的分阶段等待与重试（含 iframe、失败分类、并发不互相阻塞）。
- E 每个浏览器实例登录完成后选中该实例的第一个标签页。
- F 浏览器页面尺寸随窗口调整（no_viewport + 窗口最大化/还原）。

除 A 组（纯静态/单元）与 F 组的 CDP 调用参数校验外，均使用真实 Playwright
Chromium + 本地测试服务器（tests/test_server.py）构造的页面，不使用模拟 Page。

运行： python tests/test_v508_features.py
"""

import asyncio
import hashlib
import inspect
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright          # noqa: E402

import encrypt                                             # noqa: E402
from appcore import browser as browser_mod                 # noqa: E402
from appcore.config import (BROWSER_LAUNCH_ARGS,           # noqa: E402
                            BROWSER_START_MAXIMIZED,
                            SELECTOR_LOOKUP_BUDGET,
                            SELECTOR_LOOKUP_SLOW_BUDGET)
from appcore.login_engine import (LoginContext,            # noqa: E402
                                   generate_template_only, quick_login)
from appcore.templates import (CAPTCHA_SELECTORS,         # noqa: E402
                                DEFAULT_TEMPLATE, LOGIN_BUTTON_SELECTORS,
                                PASSWORD_SELECTORS, USERNAME_SELECTORS,
                                validate_template)
from test_server import LoginHandler, TestServer            # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


# =============================================================================
# A 组：黑框（wmic.exe）修复
# =============================================================================
def scan_process_spawners():
    """扫描发货代码中所有实际启动外部进程的调用点。

    范围只包含 GUI 程序实际会加载的模块（appcore / appui / 根目录脚本），
    不包含 tests/ 下的开发脚本。
    返回 [(相对路径, 行号, 该调用点及其后续若干行)]。
    """
    files = []
    for folder in ('appcore', 'appui'):
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                if name.endswith('.py'):
                    files.append(os.path.join(dirpath, name))
    for name in ('encrypt.py', 'import_excel.py', 'login_batch.py',
                 'login_gui.py', 'login_gui_pyqt6.py'):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            files.append(path)

    # 只匹配「真正启动进程」的调用点，不匹配单纯的 import
    pattern = re.compile(
        r'subprocess\.(run|Popen|call|check_call|check_output)\s*\('
        r'|\bos\.(system|popen)\s*\('
        r'|\bQProcess\s*\(')
    hits = []
    for path in files:
        try:
            with open(path, encoding='utf-8', errors='replace') as handle:
                lines = handle.readlines()
        except Exception:
            continue
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            window = ''.join(lines[index:index + 10])
            hits.append((os.path.relpath(path, ROOT), index + 1, window))
    return hits


def test_black_window():
    # A1 / A2：subprocess 必须以「不弹控制台」的方式启动
    kwargs = encrypt.no_window_kwargs()
    if os.name == 'nt':
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        check("A1 外部进程使用 CREATE_NO_WINDOW 启动",
              kwargs.get('creationflags') == creationflags and creationflags != 0,
              f"creationflags={kwargs.get('creationflags')}")
        startupinfo = kwargs.get('startupinfo')
        ok = (startupinfo is not None
              and (startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW)
              and startupinfo.wShowWindow == subprocess.SW_HIDE)
        check("A2 外部进程窗口以隐藏方式启动", ok,
              f"dwFlags={getattr(startupinfo, 'dwFlags', None)}")
    else:
        check("A1 非 Windows 平台无需附加参数（跳过）", kwargs == {}, str(kwargs))
        check("A2 非 Windows 平台无需附加参数（跳过）", True)

    # A3：wmic 只能被启动一次（进程级缓存）
    encrypt.reset_machine_key_cache()
    before = encrypt.get_wmic_call_count()
    for _ in range(5):
        encrypt.get_machine_key()
    after = encrypt.get_wmic_call_count()
    check("A3 连续读取密钥只启动一次 wmic", (after - before) <= 1,
          f"本次进程累计 wmic 调用={after}")

    # A4：批量加解密（导入 / 刷新配置时每台设备都会调用）不再重复拉起 wmic
    before = encrypt.get_wmic_call_count()
    for i in range(30):
        text = encrypt.simple_encrypt(f'user-{i}')
        decrypt_ok = encrypt.simple_decrypt(text) == f'user-{i}'
        if not decrypt_ok:
            break
    after = encrypt.get_wmic_call_count()
    check("A4 批量加解密过程中不再启动新的 wmic", (after - before) <= 1,
          f"30 次加解密新增 wmic 调用={after - before}")
    check("A5 加解密往返数据一致", decrypt_ok)

    # A6：密钥派生结果必须与历史实现逐字节一致（历史 devices.json 仍可解密）
    parts = [os.environ.get('COMPUTERNAME', ''), os.environ.get('USERNAME', '')]
    serial = encrypt._read_baseboard_serial()
    if serial:
        parts.append(serial)
    legacy = hashlib.sha256(
        ('|'.join(parts) + '|LoginApp_Secure_Key_2024').encode('utf-8')).digest()
    check("A6 密钥派生结果与历史实现完全一致",
          legacy == encrypt.get_machine_key())

    # A7：发货代码中不得存在第三个外部进程调用点
    hits = scan_process_spawners()
    call_sites = [f'{f}:{n}' for f, n, _ in hits]
    check("A7 发货代码中的外部进程调用点已全部收敛",
          len(hits) <= 2, '; '.join(call_sites))

    # A8：每一个外部进程调用点都必须带无窗口参数
    missing = [f'{f}:{n}' for f, n, window in hits
               if 'no_window_kwargs' not in window
               and 'creationflags' not in window]
    check("A8 所有外部进程调用点均带无窗口参数", not missing,
          '; '.join(missing))
    check("A9 无窗口参数函数为项目统一入口",
          callable(getattr(encrypt, 'no_window_kwargs', None)) and
          getattr(encrypt, '_no_window_kwargs', None) is
          getattr(encrypt, 'no_window_kwargs', None))


# =============================================================================
# 通用工具
# =============================================================================
async def describe(locator):
    """读取元素特征（只读属性，不修改页面 DOM）"""
    if locator is None:
        return {}
    try:
        return await locator.evaluate(
            "el => ({tag: el.tagName || '', id: el.id || '', name: el.name || '',"
            " type: el.type || '', value: el.value || '',"
            " placeholder: el.getAttribute('placeholder') || '',"
            " cls: el.getAttribute('class') || '',"
            " hasNzButton: el.hasAttribute('nz-button'),"
            " hasFormControlName: el.hasAttribute('formcontrolname'),"
            " text: (el.innerText || '').trim(),"
            " html: el.outerHTML || ''})"
        )
    except Exception:
        return {}


async def locate(page, selectors, key, extra_budget=None):
    return await browser_mod.find_by_selectors_detailed(
        page, selectors, key, budget=SELECTOR_LOOKUP_BUDGET,
        extra_budget=extra_budget)


class _TrackedPage:
    """包装真实 Page，记录 bring_to_front 调用次数"""

    def __init__(self, page):
        self._page = page
        self.bring_to_front_calls = 0

    def is_closed(self):
        try:
            return self._page.is_closed()
        except Exception:
            return True

    async def bring_to_front(self):
        self.bring_to_front_calls += 1
        await self._page.bring_to_front()


# =============================================================================
# B 组：五组真实登录页面 HTML 样例
# =============================================================================
SAMPLE_CASES = [
    {
        'name': '第1组 q-input',
        'path': '/sample/qinput',
        'username': {'placeholder': '请输入用户名', 'type': 'text'},
        'password': {'placeholder': '请输入密码', 'type': 'password'},
        'captcha': {'placeholder': '请输入图片验证码'},
        'button': {'tag': 'BUTTON'},
    },
    {
        'name': '第2组 form.userID',
        'path': '/sample/formuserid',
        'username': {'id': 'form.userID', 'name': 'loginName'},
        'password': {'id': 'form.password', 'name': 'password'},
        'captcha': {'id': 'form.validateCode', 'name': 'checkCode'},
        'button': {'tag': 'BUTTON'},
    },
    {
        'name': '第3组 UserName/UserPasswd',
        'path': '/sample/userpasswd',
        'username': {'id': 'UserName', 'name': 'UserName'},
        'password': {'id': 'UserPasswd', 'name': 'UserPasswd'},
        'captcha': None,
        'button': {'tag': 'INPUT', 'value': 'Login'},
    },
    {
        'name': '第4组 loginName/password/checkCode',
        'path': '/sample/loginnamepwd',
        'username': {'id': 'loginName', 'name': 'loginName'},
        'password': {'id': 'password', 'name': 'password', 'type': 'text'},
        'captcha': {'id': 'checkCode', 'name': 'checkCode'},
        'button': {'tag': 'BUTTON'},
    },
    {
        'name': '第5组 Ant Design/Angular',
        'path': '/sample/angular',
        'username': {'placeholder': '用户名', 'hasFormControlName': True},
        'password': {'id': 'password', 'type': 'password'},
        'captcha': None,
        'button': {'tag': 'BUTTON', 'hasNzButton': True},
    },
]


def matches(actual, expected):
    """按期望特征逐项校验命中元素"""
    if not actual:
        return False, '未命中任何元素'
    for key, value in expected.items():
        if actual.get(key) != value:
            return False, f'{key} 期望={value} 实际={actual.get(key)!r}'
    return True, ''


async def scenario_samples(context, base_url):
    for case in SAMPLE_CASES:
        page = await context.new_page()
        await browser_mod.navigate(page, f"{base_url}{case['path']}")
        await browser_mod.wait_page_loaded(page, 10, require_complete=False)

        user_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
        user_info = await describe(user_result.get('field'))
        ok, detail = matches(user_info, case['username'])
        check(f"B 用户名识别正确（{case['name']}）", user_result['hit'] and ok,
              detail or f"selector={user_result.get('value')}")

        pwd_result = await locate(page, PASSWORD_SELECTORS, 'password_selectors')
        pwd_info = await describe(pwd_result.get('field'))
        ok, detail = matches(pwd_info, case['password'])
        check(f"B 密码识别正确（{case['name']}）", pwd_result['hit'] and ok,
              detail or f"selector={pwd_result.get('value')}")

        # 用户名与密码必须是两个不同的元素（type=text 的密码框不得被当成用户名）
        if user_info and pwd_info:
            distinct = user_info.get('html') != pwd_info.get('html')
        else:
            distinct = False
        check(f"B 用户名与密码定位到不同元素（{case['name']}）", distinct)

        if case.get('captcha'):
            cap_result = await browser_mod.find_captcha_field_detailed(
                page, None, extra_budget=SELECTOR_LOOKUP_SLOW_BUDGET)
            cap_info = await describe(cap_result.get('field'))
            ok, detail = matches(cap_info, case['captcha'])
            check(f"B 验证码识别正确（{case['name']}）", cap_result['hit'] and ok,
                  detail or f"selector={cap_result.get('value')}")
            if cap_info and user_info:
                check(f"B 验证码与用户名是不同元素（{case['name']}）",
                      cap_info.get('html') != user_info.get('html'))
        else:
            cap_result = await browser_mod.find_captcha_field_detailed(
                page, None, extra_budget=SELECTOR_LOOKUP_SLOW_BUDGET)
            check(f"B 无验证码页面不误判（{case['name']}）", not cap_result['hit'],
                  f"reason={cap_result.get('reason')}")

        btn_result = await locate(page, LOGIN_BUTTON_SELECTORS, 'login_button_selectors')
        btn_info = await describe(btn_result.get('field'))
        ok, detail = matches(btn_info, case['button'])
        check(f"B 登录按钮识别正确（{case['name']}）", btn_result['hit'] and ok,
              detail or f"selector={btn_result.get('value')}")

        await page.close()

    # 第 1 组：三个输入框共享 .q-input__inner，必须被区分成三个不同元素
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/sample/qinput")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    user_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    pwd_result = await locate(page, PASSWORD_SELECTORS, 'password_selectors')
    cap_result = await browser_mod.find_captcha_field_detailed(page, None)
    infos = [await describe(user_result.get('field')),
             await describe(pwd_result.get('field')),
             await describe(cap_result.get('field'))]
    htmls = [i.get('html') for i in infos if i]
    check("B 共享 class 的三个输入框被区分为三个不同元素",
          len(htmls) == 3 and len(set(htmls)) == 3, str(len(set(htmls))))
    check("B 三个输入框均使用 q-input__inner（验证确实共享 class）",
          all('q-input__inner' in (h or '') for h in htmls))
    await page.close()

    # 第 4 组：密码框实际为 type=text，不得被识别成用户名
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/sample/loginnamepwd")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    user_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    user_info = await describe(user_result.get('field'))
    check("B type=text 的密码框未被误判为用户名",
          user_info.get('id') == 'loginName' and user_info.get('type') == 'text',
          f"实际命中 id={user_info.get('id')!r}")
    pwd_result = await locate(page, PASSWORD_SELECTORS, 'password_selectors')
    pwd_info = await describe(pwd_result.get('field'))
    check("B type=text 的密码框被正确识别为密码框",
          pwd_info.get('id') == 'password' and pwd_info.get('type') == 'text',
          f"实际命中 id={pwd_info.get('id')!r}")
    await page.close()

    # 第 5 组：Angular 动态 class 变化不影响定位
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/sample/angular")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    user_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    user_info = await describe(user_result.get('field'))
    check("B Angular 用户名不依赖动态 class 命中",
          user_result['hit'] and user_info.get('hasFormControlName') is True,
          f"selector={user_result.get('value')}")
    btn_result = await locate(page, LOGIN_BUTTON_SELECTORS, 'login_button_selectors')
    btn_info = await describe(btn_result.get('field'))
    text = (btn_info.get('text') or '').replace(' ', '')
    check("B Angular 登录按钮文本空白归一化后命中",
          btn_result['hit'] and '登录' in text, f"text={btn_info.get('text')!r}")
    await page.close()

    # 诊断信息：每个候选选择器都要有命中/未命中记录
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/sample/qinput")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    entries = result.get('entries') or []
    states = {e.get('state') for e in entries}
    check("B 逐候选选择器均有诊断记录",
          len(entries) > 0 and ('found' in states),
          f"候选={len(entries)} 状态={sorted(states)}")
    await page.close()


# =============================================================================
# C 组：验证码页面的模板生成（不自动提交登录）
# =============================================================================
async def scenario_captcha_template(context, base_url):
    for path, label in (('/captcha', '普通验证码页'),
                        ('/sample/qinput', 'q-input 图片验证码页')):
        page = await context.new_page()
        await browser_mod.navigate(page, f"{base_url}{path}")
        await browser_mod.wait_page_loaded(page, 10, require_complete=False)

        LoginHandler.reset_post_count()
        ctx = LoginContext(f'验证码模板测试-{label}', '生成模板')
        result = await generate_template_only(page, DEFAULT_TEMPLATE, ctx)

        check(f"C 模板生成成功（{label}）", result.get('ok'), result.get('detail', ''))
        recorded = result.get('recorded') or {}
        check(f"C 记录了用户名选择器（{label}）",
              bool(recorded.get('username_selectors')))
        check(f"C 记录了密码选择器（{label}）",
              bool(recorded.get('password_selectors')))
        check(f"C 记录了验证码选择器（{label}）",
              bool(recorded.get('captcha_selectors')))
        check(f"C 记录了登录按钮选择器（{label}）",
              bool(recorded.get('login_button_selectors')))
        check(f"C 生成模板过程中未提交登录表单（{label}）",
              LoginHandler.post_count == 0,
              f"post_count={LoginHandler.post_count}")

        # 录制的选择器必须能通过模板校验（即可直接保存）
        errors, _warnings, normalized = validate_template({
            'name': '_v508_captcha_test',
            'username_selectors': recorded.get('username_selectors', []),
            'password_selectors': recorded.get('password_selectors', []),
            'login_button_selectors': recorded.get('login_button_selectors', []),
            'captcha_selectors': recorded.get('captcha_selectors', []),
        }, source='v508-test')
        check(f"C 录制的选择器可直接保存为模板（{label}）", not errors,
              '; '.join(errors[:2]))
        check(f"C 保存后的模板保留验证码字段（{label}）",
              bool(normalized.get('captcha_selectors')))

        # 录制的验证码选择器必须指向验证码框本身
        cap_selectors = recorded.get('captcha_selectors') or []
        if cap_selectors:
            cap_result = await browser_mod.find_by_selectors_detailed(
                page, cap_selectors, 'captcha_selectors',
                budget=SELECTOR_LOOKUP_BUDGET)
            cap_info = await describe(cap_result.get('field'))
            user_result = await locate(page, recorded.get('username_selectors') or [],
                                       'username_selectors')
            user_info = await describe(user_result.get('field'))
            check(f"C 录制的验证码选择器指向验证码框（{label}）",
                  cap_result['hit'] and cap_info.get('html') != user_info.get('html'),
                  f"placeholder={cap_info.get('placeholder')!r}")
        await page.close()

    # 模板生成失败时必须给出明确原因（而不是笼统的「无法使用」）
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/nologin")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    LoginHandler.reset_post_count()
    ctx = LoginContext('验证码模板测试-无表单', '生成模板')
    result = await generate_template_only(page, DEFAULT_TEMPLATE, ctx)
    check("C 无表单页面模板生成失败并给出明确原因",
          not result.get('ok') and result.get('reason') == 'username_selector_not_found',
          f"reason={result.get('reason')}")
    check("C 模板生成失败时同样未提交登录",
          LoginHandler.post_count == 0, f"post_count={LoginHandler.post_count}")
    await page.close()


# =============================================================================
# D 组：慢速加载页面的分阶段等待与重试
# =============================================================================
async def scenario_slow_page(context, base_url):
    # D1：不开启扩展预算时不应无限等待
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/slowjs")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    fast_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    check("D1 未开启扩展预算时不会无限等待",
          not fast_result['hit'] and
          fast_result['elapsed_ms'] < (SELECTOR_LOOKUP_BUDGET + 3) * 1000,
          f"耗时={fast_result['elapsed_ms']}ms")
    check("D2 未命中时给出明确失败原因",
          fast_result['reason'] in ('page_not_ready', 'selector_not_found',
                                    'budget_exceeded'),
          f"reason={fast_result['reason']}")
    await page.close()

    # D3：开启扩展预算后，慢速渲染的表单能够被命中
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/slowjs")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    slow_result = await locate(page, USERNAME_SELECTORS, 'username_selectors',
                               extra_budget=SELECTOR_LOOKUP_SLOW_BUDGET)
    check("D3 慢速渲染页面在扩展预算内命中", slow_result['hit'],
          f"耗时={slow_result['elapsed_ms']}ms reason={slow_result['reason']}")
    check("D4 记录了慢速等待诊断信息",
          slow_result.get('slow_wait_ms', 0) > 0 and bool(slow_result.get('page_state')),
          f"slow_wait_ms={slow_result.get('slow_wait_ms')} "
          f"page_state={slow_result.get('page_state')} "
          f"rounds={slow_result.get('slow_rounds')}")
    check("D5 慢速等待总耗时仍有上限",
          slow_result['elapsed_ms'] <
          (SELECTOR_LOOKUP_BUDGET + SELECTOR_LOOKUP_SLOW_BUDGET + 3) * 1000,
          f"耗时={slow_result['elapsed_ms']}ms")
    await page.close()

    # D6：表单位于 iframe 中时也能命中
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/frame")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    for _ in range(50):
        try:
            if len(page.frames) > 1:
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)
    frame_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    check("D6 iframe 中的登录表单可被命中", frame_result['hit'],
          f"reason={frame_result['reason']}")
    check("D7 记录了 iframe 检查数量",
          frame_result.get('frames_checked', 0) >= 1,
          f"frames_checked={frame_result.get('frames_checked')}")
    await page.close()

    # D8：页面始终没有表单时，失败原因必须准确
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/nologin")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    none_result = await locate(page, USERNAME_SELECTORS, 'username_selectors')
    check("D8 元素始终不存在时给出准确失败原因",
          not none_result['hit'] and
          none_result['reason'] in ('page_not_ready', 'selector_not_found'),
          f"reason={none_result['reason']}")
    check("D9 元素不存在时未无限等待",
          none_result['elapsed_ms'] < (SELECTOR_LOOKUP_BUDGET + 3) * 1000,
          f"耗时={none_result['elapsed_ms']}ms")
    await page.close()

    # D10：一个慢速设备不得阻塞其它设备的批量任务
    slow_page = await context.new_page()
    fast_page = await context.new_page()
    await browser_mod.navigate(slow_page, f"{base_url}/slowjs")
    await browser_mod.navigate(fast_page, f"{base_url}/generic")
    await browser_mod.wait_page_loaded(fast_page, 10, require_complete=False)
    started = time.monotonic()
    slow_task = asyncio.ensure_future(
        locate(slow_page, USERNAME_SELECTORS, 'username_selectors',
               extra_budget=SELECTOR_LOOKUP_SLOW_BUDGET))
    fast_task = asyncio.ensure_future(
        locate(fast_page, USERNAME_SELECTORS, 'username_selectors'))
    fast_result = await fast_task
    fast_elapsed = time.monotonic() - started
    check("D10 慢速设备不阻塞其它设备", fast_result['hit'] and fast_elapsed < 2.0,
          f"正常设备耗时={fast_elapsed:.2f}s")
    slow_result = await slow_task
    check("D11 并发时慢速设备仍能正常完成", slow_result['hit'],
          f"reason={slow_result['reason']}")
    await slow_page.close()
    await fast_page.close()


# =============================================================================
# E 组：每个浏览器实例登录完成后选中第一个标签页
# =============================================================================
async def scenario_tabs(context, browser, base_url):
    # E1：单实例多标签页 -> 选中第一个并激活到前台
    session = browser_mod.BrowserSession('标签页测试-1')
    session.browser = browser
    session.context = context
    first = _TrackedPage(await context.new_page())
    await context.new_page()
    await context.new_page()
    session.pages = [first]
    session.pages.extend(list(context.pages)[-2:])
    session.current_index = 2
    result = await session.select_first_tab()
    check("E1 登录后选中该实例的第一个标签页",
          result is not None and session.current_index == 0,
          f"current_index={session.current_index}")
    check("E2 第一个标签页被激活到前台（bring_to_front）",
          first.bring_to_front_calls == 1,
          f"calls={first.bring_to_front_calls}")

    # E3：第一个标签页已关闭时，安全选中下一个可用标签页
    session2 = browser_mod.BrowserSession('标签页测试-2')
    session2.context = context
    closed_page = await context.new_page()
    await closed_page.close()
    live = _TrackedPage(await context.new_page())
    session2.pages = [closed_page, live]
    session2.current_index = 1
    result = await session2.select_first_tab()
    check("E3 跳过已关闭的标签页并选中下一个",
          result is live and session2.current_index == 1,
          f"current_index={session2.current_index}")

    # E4：实例没有有效标签页时安全返回，不抛异常
    session3 = browser_mod.BrowserSession('标签页测试-3')
    session3.context = context
    session3.pages = []
    try:
        result = await session3.select_first_tab()
        check("E4 没有有效标签页时安全返回 None", result is None)
    except Exception as exc:
        check("E4 没有有效标签页时安全返回 None", False, str(exc))

    # E5：多实例互不干扰
    session_a = browser_mod.BrowserSession('实例A')
    session_a.context = context
    session_b = browser_mod.BrowserSession('实例B')
    session_b.context = context
    tab_a = _TrackedPage(await context.new_page())
    tab_b = _TrackedPage(await context.new_page())
    session_a.pages = [tab_a]
    session_b.pages = [tab_b]
    await session_a.select_first_tab()
    await session_b.select_first_tab()
    check("E5 多实例各自选中自己的第一个标签页",
          tab_a.bring_to_front_calls == 1 and tab_b.bring_to_front_calls == 1,
          f"A={tab_a.bring_to_front_calls} B={tab_b.bring_to_front_calls}")

    # E6：快捷登录后同样遵守「选中第一个标签页」
    orig_get = browser_mod.BrowserManager.get
    orig_valid = browser_mod.BrowserManager.is_valid
    quick = browser_mod.BrowserSession('快捷登录实例')
    quick.browser = browser
    quick.context = context
    quick_first = _TrackedPage(await context.new_page())
    quick.pages = [quick_first]
    browser_mod.BrowserManager.get = classmethod(lambda cls, name: quick)
    browser_mod.BrowserManager.is_valid = classmethod(
        lambda cls, s: s is not None and getattr(s, 'browser', None) is not None)
    try:
        LoginHandler.reset_post_count()
        ok, msg, _recorded = await quick_login(
            '快捷登录-标签页', f"{base_url}/generic", 'admin', 'pass123', 'default')
        check("E6 快捷登录成功", ok, msg)
        check("E7 快捷登录后选中该实例的第一个标签页",
              quick.current_index == 0 and quick_first.bring_to_front_calls >= 1,
              f"current_index={quick.current_index} "
              f"calls={quick_first.bring_to_front_calls}")
    finally:
        browser_mod.BrowserManager.get = orig_get
        browser_mod.BrowserManager.is_valid = orig_valid


# =============================================================================
# F 组：浏览器页面尺寸随窗口调整
# =============================================================================
async def scenario_viewport(browser, context, base_url):
    # F1：记录根因 —— Playwright 默认上下文使用固定 1280x720 视口
    default_context = await browser.new_context(ignore_https_errors=True)
    try:
        default_page = await default_context.new_page()
        viewport = default_page.viewport_size
        check("F1 默认上下文的固定视口（页面尺寸不随窗口变化的根因）",
              viewport == {'width': 1280, 'height': 720}, str(viewport))
    finally:
        await default_context.close()

    # F2：项目实际使用的上下文关闭了视口模拟
    source = inspect.getsource(browser_mod.BrowserManager.create)
    check("F2 浏览器上下文使用 no_viewport=True（视口跟随真实窗口）",
          'no_viewport=True' in source)
    check("F3 启动参数包含 --start-maximized（窗口默认最大化）",
          BROWSER_START_MAXIMIZED and '--start-maximized' in BROWSER_LAUNCH_ARGS)

    # F4：no_viewport 下视口跟随窗口尺寸变化
    page = await context.new_page()
    await browser_mod.navigate(page, f"{base_url}/generic")
    await browser_mod.wait_page_loaded(page, 10, require_complete=False)
    check("F4 no_viewport 下 viewport_size 为 None（由窗口决定）",
          page.viewport_size is None, str(page.viewport_size))
    inner_before = await page.evaluate("() => [window.innerWidth, window.innerHeight]")
    resized = False
    try:
        cdp = await context.new_cdp_session(page)
        info = await cdp.send('Browser.getWindowForTarget')
        window_id = info.get('windowId')
        await cdp.send('Browser.setWindowBounds', {
            'windowId': window_id,
            'bounds': {'width': 1500, 'height': 940},
        })
        await asyncio.sleep(0.5)
        inner_after = await page.evaluate("() => [window.innerWidth, window.innerHeight]")
        resized = True
        check("F5 调整窗口尺寸后页面视口随之变化",
              inner_after[0] > inner_before[0],
              f"{inner_before} -> {inner_after}")
    except Exception as exc:
        check("F5 调整窗口尺寸后页面视口随之变化", False,
              f"当前环境不支持窗口尺寸调整: {exc}")
    finally:
        if resized:
            pass

    # F6：窗口最大化 / 还原通过 CDP 完成（不会进入无法退出的全屏）
    class _FakeCDP:
        def __init__(self):
            self.sent = []

        async def send(self, method, params=None):
            self.sent.append((method, params))
            if method == 'Browser.getWindowForTarget':
                return {'windowId': 7}
            return {}

        async def detach(self):
            return None

    class _FakeContext:
        def __init__(self):
            self.cdp = _FakeCDP()

        async def new_cdp_session(self, page):
            return self.cdp

    class _FakePage:
        def is_closed(self):
            return False

    fake_session = browser_mod.BrowserSession('窗口状态测试')
    fake_session.context = _FakeContext()
    fake_session.pages = [_FakePage()]
    ok, message = await fake_session.set_window_state('maximized')
    sent = fake_session.context.cdp.sent
    check("F6 最大化通过 CDP setWindowBounds 完成",
          ok and ('Browser.setWindowBounds',
                  {'windowId': 7, 'bounds': {'windowState': 'maximized'}}) in sent,
          str(sent))
    check("F7 窗口状态被正确记录", fake_session.window_state == 'maximized')
    ok2, _message2 = await fake_session.set_window_state('normal')
    check("F8 可从最大化还原（不会进入无法退出的状态）",
          ok2 and fake_session.window_state == 'normal')
    check("F9 从未使用 fullscreen（全屏不可退出，已避免）",
          all('fullscreen' not in str(params) for _method, params in sent))

    # F10：真实浏览器上调用窗口状态调整不抛异常
    real_session = browser_mod.BrowserSession('真实窗口状态测试')
    real_session.context = context
    real_session.pages = [page]
    try:
        ok3, message3 = await real_session.set_window_state('normal')
        check("F10 真实浏览器窗口状态调整不抛异常", isinstance(ok3, bool), message3)
    except Exception as exc:
        check("F10 真实浏览器窗口状态调整不抛异常", False, str(exc))

    await page.close()


# =============================================================================
# 主流程
# =============================================================================
async def run_browser_scenarios(base_url):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=[
        '--disable-dev-shm-usage', '--no-sandbox', '--ignore-certificate-errors',
    ])
    context = await browser.new_context(ignore_https_errors=True, no_viewport=True)
    try:
        await scenario_samples(context, base_url)
        await scenario_captcha_template(context, base_url)
        await scenario_slow_page(context, base_url)
        await scenario_tabs(context, browser, base_url)
        await scenario_viewport(browser, context, base_url)
    finally:
        try:
            await context.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass
        await playwright.stop()


def main():
    started = time.monotonic()
    print("=" * 68)
    print("V5.0.6 专项回归测试")
    print("=" * 68)

    print("\n--- A 组：黑框（wmic.exe）修复 ---")
    test_black_window()

    print("\n--- B~F 组：真实浏览器端到端 ---")
    try:
        with TestServer() as server:
            asyncio.run(run_browser_scenarios(server.base_url))
    except Exception as exc:
        check("浏览器端到端场景执行", False, f"{type(exc).__name__}: {exc}")

    print("\n" + "=" * 68)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"专项测试: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
