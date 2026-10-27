"""元素角色验证测试（真实 Playwright + 本地测试页面）。

覆盖任务书 8.1 的 9 类场景：
1. 正确的用户名输入框；
2. name="login" / id="login" 出现在**按钮**上的情况；
3. 密码框被误认为用户名候选的情况；
4. type="text" 但实际是密码字段的特殊页面；
5. 同一选择器匹配多个元素；
6. 隐藏、禁用、不可编辑的输入框；
7. iframe 中的登录表单；
8. 页面重新渲染导致元素引用失效；
9. 正确用户名、密码、验证码和登录按钮分别位于不同元素。
10. 密码候选被当成登录按钮（串用防线）；
11. Element UI 风格账号框（class 与密码框共用 + autocomplete=current-password）；
12. 账号框字段名与密码冲突，但页面上存在独立密码框（页面级消歧）；
13. 账号框字段名与密码冲突且页面无独立密码框（应报告歧义）；
14. 仅样式类名带密码词（弱证据不应否决账号框）；
15. 离线的角色证据分级矩阵（不启动浏览器）。

核心断言：错误角色的元素不会被填写，也不会被当成登录按钮点击。
所有页面均为本地测试服务器提供的受控页面，不访问任何真实设备。

运行： python tests/test_element_roles.py
"""

import asyncio
import os
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

from appcore import browser as browser_mod                 # noqa: E402
from appcore.element_roles import (                        # noqa: E402
    ROLE_BUTTON,
    ROLE_CAPTCHA,
    ROLE_PASSWORD,
    ROLE_USERNAME,
    inspect_role,
)
from test_server import LoginHandler, TestServer            # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def _states(result):
    """取出候选执行记录里的状态集合"""
    return [entry.get('state') for entry in (result.get('entries') or [])]


async def _open(context, url):
    page = await context.new_page()
    await browser_mod.navigate(page, url)
    return page


async def run_scenarios(context, base_url):
    # ============ 场景 1：正确的用户名输入框 ============
    page = await _open(context, f'{base_url}/generic')
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'NAME', 'value': 'username'}], 'username_selectors',
        budget=5, role=ROLE_USERNAME, trusted=True)
    check("1 用户名输入框被角色校验接受", result['hit'] and result['field'] is not None,
          f"reason={result.get('reason')}")
    ok, reason = await browser_mod.input_text_detailed(result['field'], 'admin')
    check("1 用户名可实际填写", ok, reason)
    if ok:
        value = await result['field'].input_value()
        check("1 填写内容正确", value == 'admin', value)
    await page.close()

    # ============ 场景 2：login 语义出现在按钮上 ============
    page = await _open(context, f'{base_url}/roles/loginattr')
    LoginHandler.reset_post_count()
    for selector in ({'by': 'CSS_SELECTOR', 'value': 'input[name="login"]'},
                     {'by': 'CSS_SELECTOR', 'value': 'input[id="login"]'}):
        result = await browser_mod.find_by_selectors_detailed(
            page, [selector], 'username_selectors',
            budget=5, role=ROLE_USERNAME, trusted=True)
        check(f"2 {selector['value']} 命中按钮时被拒绝",
              not result['hit'] and result.get('role_rejected', 0) > 0,
              f"hit={result['hit']} role_rejected={result.get('role_rejected')}")
        check(f"2 {selector['value']} 记录了角色不符状态",
              'role_mismatch' in _states(result), str(_states(result)))
    # 该按钮绝不能被当成用户名填写
    check("2 按钮未被填入用户名", LoginHandler.post_count == 0,
          f"post_count={LoginHandler.post_count}")
    await page.close()

    # ============ 场景 3：密码框被误认为用户名候选 ============
    page = await _open(context, f'{base_url}/generic')
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("3 密码框不能作用户名字段", not result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    check("3 密码框被记为角色不符",
          result.get('role_rejected', 0) > 0, str(result.get('role_rejected')))
    # 反向：密码角色应能接受它
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}],
        'password_selectors', budget=5, role=ROLE_PASSWORD, trusted=True)
    check("3 同一选择器在密码角色下可命中", result['hit'],
          f"reason={result.get('reason')}")
    await page.close()

    # ============ 场景 4：type=text 的密码字段 ============
    page = await _open(context, f'{base_url}/roles/textpassword')
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#password'}],
        'password_selectors', budget=5, role=ROLE_PASSWORD, trusted=True)
    check("4 type=text 的密码框按密码角色命中", result['hit'],
          f"reason={result.get('reason')}")
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#password'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("4 type=text 的密码框不能作用户名", not result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    await page.close()

    # ============ 场景 5：同一选择器匹配多个元素 ============
    page = await _open(context, f'{base_url}/roles/multi')
    locator = page.locator('input[name="username"]')
    count = await locator.count()
    verdict = await inspect_role(locator, count, ROLE_USERNAME, trusted=True)
    check("5 多匹配被识别为歧义",
          verdict['verdict'] == 'ambiguous' and verdict['reason'] == 'ambiguous_match',
          f"verdict={verdict['verdict']} reason={verdict['reason']} matched={count}")
    check("5 歧义时不给出发写元素", verdict['field'] is None)
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[name="username"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("5 多匹配时不会直接取第一个填写", not result['hit'],
          f"hit={result['hit']}")
    await page.close()

    # ============ 场景 6：隐藏 / 禁用 / 只读输入框 ============
    page = await _open(context, f'{base_url}/roles/disabled')
    for selector, expect in (
            ({'by': 'CSS_SELECTOR', 'value': 'input[type="hidden"]'},
             ('hidden_element', 'input_type_hidden')),
            ({'by': 'CSS_SELECTOR', 'value': 'input[disabled]'}, ('disabled_element',)),
            ({'by': 'CSS_SELECTOR', 'value': 'input[readonly]'}, ('readonly_element',)),
    ):
        verdict = await inspect_role(page.locator(selector['value']), 1,
                                     ROLE_USERNAME, trusted=True)
        check(f"6 {selector['value']} 被拒绝（{'/'.join(expect)}）",
              (not verdict['ok']) and verdict['reason'] in expect,
              f"reason={verdict['reason']}")
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[name="username"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("6 同名的隐藏/禁用/只读元素整体不可用", not result['hit'],
          f"hit={result['hit']} role_rejected={result.get('role_rejected')}")
    # 真正的可见用户名框仍应可用
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#visibleUser'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("6 可见用户名框不受影响", result['hit'],
          f"reason={result.get('reason')}")
    await page.close()

    # ============ 场景 7：iframe 中的登录表单 ============
    page = await _open(context, f'{base_url}/frame')
    await asyncio.sleep(0.6)
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#username'}],
        'username_selectors', budget=6, role=ROLE_USERNAME, trusted=True)
    check("7 iframe 内的用户名框被命中", result['hit'],
          f"reason={result.get('reason')} frames_checked={result.get('frames_checked')}")
    check("7 记录了已检查的 frame 数量", result.get('frames_checked', 0) >= 1,
          str(result.get('frames_checked')))
    if result['hit']:
        ok, reason = await browser_mod.input_text_detailed(result['field'], 'admin')
        check("7 iframe 内可实际填写", ok, reason)
    await page.close()

    # ============ 场景 8：页面重新渲染导致元素引用失效 ============
    page = await _open(context, f'{base_url}/roles/rerender')
    locator = page.locator('input#username')
    handle = await locator.element_handle()
    await asyncio.sleep(1.2)          # 页面已重建表单 -> 旧引用失效
    ok, reason = await browser_mod.input_text_detailed(handle, 'admin')
    check("8 失效引用被识别为 element_detached",
          (not ok) and reason == 'element_detached', f"ok={ok} reason={reason}")
    # 重新定位后应能正常填写
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#username'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    ok, reason = await browser_mod.input_text_detailed(result['field'], 'admin')
    check("8 重新定位后可正常填写", ok, reason)
    await page.close()

    # ============ 场景 9：四类字段分别位于不同元素 ============
    page = await _open(context, f'{base_url}/roles/separate')
    user = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#userAccount'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("9 用户名字段独立命中", user['hit'], f"reason={user.get('reason')}")

    pwd = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#userSecret'}],
        'password_selectors', budget=5, role=ROLE_PASSWORD, trusted=True)
    check("9 密码字段独立命中", pwd['hit'], f"reason={pwd.get('reason')}")

    captcha = await browser_mod.find_captcha_field_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input#verifyCode'}],
        budget=5, extra_budget=0)
    check("9 验证码字段独立命中", captcha['hit'],
          f"reason={captcha.get('reason')} source={captcha.get('source')}")

    # 登录按钮：用户名 / 密码 / 验证码的候选都不能被当成按钮
    for selector in ({'by': 'CSS_SELECTOR', 'value': 'input#userAccount'},
                     {'by': 'CSS_SELECTOR', 'value': 'input#userSecret'}):
        result = await browser_mod.find_login_button_by_selectors_detailed(
            page, [selector], budget=5)
        check(f"9 {selector['value']} 不能被当成登录按钮",
              not result['hit'] and result.get('role_rejected', 0) > 0,
              f"hit={result['hit']} role_rejected={result.get('role_rejected')}")

    LoginHandler.reset_post_count()
    result = await browser_mod.find_login_button_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'button#doLogin'}], budget=5)
    check("9 真正的登录按钮可命中并点击", result['hit'],
          f"reason={result.get('reason')}")
    check("9 登录按钮只提交了一次", LoginHandler.post_count == 1,
          f"post_count={LoginHandler.post_count}")
    await page.close()

    # ============ 场景 10：密码候选被当成登录按钮（串用防线）============
    page = await _open(context, f'{base_url}/generic')
    LoginHandler.reset_post_count()
    result = await browser_mod.find_login_button_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}], budget=5)
    check("10 input[type=password] 不能被当成登录按钮",
          not result['hit'], f"hit={result['hit']} reason={result.get('reason')}")
    check("10 未因此触发任何提交", LoginHandler.post_count == 0,
          f"post_count={LoginHandler.post_count}")
    await page.close()


async def run_conflict_scenarios(context, base_url):
    # ============ 场景 11：Element UI 风格账号框（弱密码信号）============
    # 账号框与密码框共用 class=el-input__inner，账号框还带着
    # autocomplete=current-password。旧实现把这些线索与
    # placeholder=密码 等权处理，直接把账号框判成 looks_like_password。
    page = await _open(context, f'{base_url}/roles/elinput')
    account_selector = 'input.el-input__inner[type="text"][placeholder="账号"]'
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': account_selector}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("11 Element UI 账号框不被误判为密码框", result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    if result['hit']:
        ok, reason = await browser_mod.input_text_detailed(result['field'], 'admin')
        check("11 账号框可实际填写", ok, reason)
    # 反向：同一页面的真密码框仍必须被拒绝
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("11 同页真密码框仍不能作用户名", not result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}],
        'password_selectors', budget=5, role=ROLE_PASSWORD, trusted=True)
    check("11 同页真密码框在密码角色下可命中", result['hit'],
          f"reason={result.get('reason')}")
    await page.close()

    # ============ 场景 12：字段名冲突 + 页面存在独立密码框 ============
    # 账号框自身带 name=password（中等密码证据），但页面上另有独立的
    # type=password 密码框：真正的密码框另有其物，应按账号处理。
    page = await _open(context, f'{base_url}/roles/nameconflict')
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR',
                 'value': 'input[name="password"][type="text"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("12 字段名冲突时靠页面上下文消歧放行账号框", result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    await page.close()

    # ============ 场景 13：字段名冲突但页面没有独立密码框 ============
    # 无法区分账号框与密码框：应报告歧义，而不是盲目填写。
    page = await _open(context, f'{base_url}/roles/nameconflict_nopwd')
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[name="password"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("13 无独立密码框时报告歧义而不是盲填", not result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    check("13 歧义原因被明确记录",
          result.get('reason') == 'role_conflict'
          or 'role_conflict' in str(result.get('entries')),
          f"reason={result.get('reason')}")
    await page.close()

    # ============ 场景 14：仅样式类名带密码词（弱证据）============
    page = await _open(context, f'{base_url}/roles/weakonly')
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="text"]'}],
        'username_selectors', budget=5, role=ROLE_USERNAME, trusted=True)
    check("14 仅 class 含密码词不否决账号框", result['hit'],
          f"hit={result['hit']} reason={result.get('reason')}")
    result = await browser_mod.find_by_selectors_detailed(
        page, [{'by': 'CSS_SELECTOR', 'value': 'input[type="password"]'}],
        'password_selectors', budget=5, role=ROLE_PASSWORD, trusted=True)
    check("14 弱证据页面里的真密码框仍可命中", result['hit'],
          f"reason={result.get('reason')}")
    await page.close()


def _info(**kwargs):
    """构造一份元素属性（与页面采集到的字段结构一致）"""
    base = {
        'tag': 'input', 'type': 'text', 'id': '', 'name': '',
        'cls': '', 'placeholder': '', 'autocomplete': '', 'aria': '',
        'role': '', 'style': '', 'text': '',
        'readonly': False, 'disabled': False, 'hidden': False,
        'contenteditable': '',
    }
    base.update(kwargs)
    return base


def run_offline_matrix():
    """离线的角色证据分级矩阵（不启动浏览器，毫秒级完成）。

    覆盖任务书要求的「误判」与「误放行」两个极端：
    - 账号框不能因为 class / autocomplete / 无关上下文被判成密码框；
    - 真密码框、验证码框、按钮仍必须被拦住。
    """
    from appcore import element_roles as er

    cases = [
        ('纯账号框 type=text placeholder=账号',
         _info(type='text', placeholder='账号'), 'accept', 'reject'),
        ('Element UI 账号框（class 与密码框共用）',
         _info(type='text', cls='el-input__inner', placeholder='账号'),
         'accept', 'reject'),
        ('账号框带 autocomplete=current-password',
         _info(type='text', cls='el-input__inner', placeholder='账号',
               autocomplete='current-password'), 'accept', 'reject'),
        ('账号框带 name=password（证据冲突，无页面上下文）',
         _info(type='text', name='password', placeholder='账号'),
         'ambiguous', 'ambiguous'),
        ('仅 class 含密码词（弱证据）',
         _info(type='text', cls='password-field', placeholder='请输入账号'),
         'accept', 'reject'),
        ('真密码框 type=password',
         _info(type='password', placeholder='密码'), 'reject', 'accept'),
        ('type=text 但 placeholder=请输入密码',
         _info(type='text', placeholder='请输入密码'), 'reject', 'accept'),
        ('type=text 但 id=password',
         _info(type='text', id='password'), 'reject', 'accept'),
        ('type=text 且 CSS 密码点显示',
         _info(type='text', style='-webkit-text-security: disc'),
         'reject', 'accept'),
        ('验证码框',
         _info(type='text', placeholder='请输入图形验证码'),
         'reject', 'reject'),
        ('按钮型 input',
         _info(type='submit', value='登录'), 'reject', 'reject'),
        ('隐藏域',
         _info(type='hidden'), 'reject', 'reject'),
    ]

    for label, info, expect_user, expect_pwd in cases:
        user_verdict, user_reason, _s = er._judge_username(info, True)
        pwd_verdict, pwd_reason, _s2 = er._judge_password(info, True)
        check(f"15 矩阵·用户名判定 {label}",
              user_verdict == expect_user,
              f"期望={expect_user} 实际={user_verdict}({user_reason})")
        check(f"15 矩阵·密码判定 {label}",
              pwd_verdict == expect_pwd,
              f"期望={expect_pwd} 实际={pwd_verdict}({pwd_reason})")


async def main():
    started = time.monotonic()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=[
            '--disable-dev-shm-usage', '--no-sandbox', '--ignore-certificate-errors',
        ])
        context = await browser.new_context(ignore_https_errors=True)
        try:
            with TestServer() as server:
                await run_scenarios(context, server.base_url)
                await run_conflict_scenarios(context, server.base_url)
                run_offline_matrix()
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"元素角色验证测试: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
