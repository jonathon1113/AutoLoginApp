"""模板使用日志与「保存模板提示」修复的自动化验证（任务书场景 A~F）。

测试环境（明确说明，不混淆）：
- 页面：本地模拟登录服务器 tests/test_server.py（不是真实设备）
- 浏览器：真实 Chromium（Playwright，headless=True）
- 日志证据：项目自身的 app.log（真实写入、真实读取）

覆盖场景：
- A: 已有设备模板正常命中（模板名/绝对路径/选择器命中/最终模板 + 不提示保存）
- B: 设备模板失败 -> 回退默认模板成功（回退原因/默认模板路径/最终模板 + 不提示保存）
- C: 模板文件存在但内容损坏（记录解析失败而非“不存在”，且不覆盖损坏文件）
- D: 模板库中没有对应模板（记录查找目录与缺失原因，走既有回退规则）
- E: 已有模板需要更新（区分新建/更新，覆盖前确认，取消后文件内容不变）
- F: 普通登录 / 快捷登录 / 分组批量登录三种入口的日志一致性与并发可区分性

运行： python tests/test_template_policy.py
"""

import asyncio
import json
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright            # noqa: E402

from appcore import browser as browser_mod                   # noqa: E402
from appcore.config import APP_LOG_FILE, TEMPLATE_DIR       # noqa: E402
from appcore.devices import set_groups                      # noqa: E402
from appcore.login_engine import (login_device, login_group,  # noqa: E402
                                  quick_login)
from appcore.templates import (TemplateManager,             # noqa: E402
                               evaluate_save_template_request)
from test_server import LoginHandler, TestServer            # noqa: E402

RESULTS = []

DEV_TEMPLATE_NAME = '_pol_dev'
DEV_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, f'{DEV_TEMPLATE_NAME}.json')
BROKEN_TEMPLATE_NAME = '_pol_broken'
BROKEN_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, f'{BROKEN_TEMPLATE_NAME}.json')
MISSING_TEMPLATE_NAME = '_pol_missing'
UPDATE_TEMPLATE_NAME = '_pol_update'
UPDATE_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, f'{UPDATE_TEMPLATE_NAME}.json')

DEV_TEMPLATE = {
    "name": DEV_TEMPLATE_NAME,
    "description": "自动化验证用设备模板（devUser/devPass/devLogin）",
    "username_selectors": [
        {"by": "ID", "value": "devUser"},
        {"by": "NAME", "value": "devUserName"},
    ],
    "password_selectors": [
        {"by": "ID", "value": "devPass"},
        {"by": "NAME", "value": "devPassWord"},
    ],
    "login_button_selectors": [
        {"by": "ID", "value": "devLogin"},
        {"by": "XPATH", "value": "//button[@id='devLogin']"},
    ],
}

# 故意写坏的 JSON（数组未闭合）-> 解析失败，但文件确实存在
BROKEN_CONTENT = ('{\n  "name": "_pol_broken",\n'
                  '  "username_selectors": [\n'
                  '    {"by": "ID", "value": "broken"\n')


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


class Session:
    """最小可用会话（真实 browser/context/page）"""

    def __init__(self, context, page=None):
        self.context = context
        self.pages = []
        self.current_index = 0
        self._page = page
        if page is not None:
            self.pages.append(page)

    @property
    def page(self):
        if self._page is None and self.pages:
            self._page = self.pages[self.current_index]
        return self._page

    @property
    def page_count(self):
        return len(self.pages)

    async def open_page(self, url=None):
        page = await self.context.new_page()
        self.pages.append(page)
        self.current_index = len(self.pages) - 1
        self._page = page
        if url:
            await browser_mod.navigate(page, url)
        return page

    async def switch_to(self, index):
        if 0 <= index < len(self.pages):
            self.current_index = index
            self._page = self.pages[index]
        return self._page


class LogGrabber:
    """读取 app.log 增量（真实日志文件）"""

    def __init__(self):
        self.offset = os.path.getsize(APP_LOG_FILE) if os.path.exists(APP_LOG_FILE) else 0

    def take(self):
        if not os.path.exists(APP_LOG_FILE):
            return ''
        with open(APP_LOG_FILE, 'r', encoding='utf-8', errors='replace') as handle:
            handle.seek(self.offset)
            text = handle.read()
        self.offset += len(text.encode('utf-8'))
        return text

    @staticmethod
    def count(text, needle):
        return text.count(needle)


def file_state(path):
    """返回模板文件的 (是否存在, 内容)"""
    if not os.path.exists(path):
        return False, None
    with open(path, 'rb') as handle:
        return True, handle.read()


def write_dev_template():
    with open(DEV_TEMPLATE_FILE, 'w', encoding='utf-8') as handle:
        json.dump(DEV_TEMPLATE, handle, indent=2, ensure_ascii=False)


def write_broken_template():
    with open(BROKEN_TEMPLATE_FILE, 'w', encoding='utf-8') as handle:
        handle.write(BROKEN_CONTENT)


def write_update_template():
    data = {
        "name": UPDATE_TEMPLATE_NAME,
        "description": "用于验证「已有模板更新」流程",
        "username_selectors": [{"by": "ID", "value": "oldUser"}],
        "password_selectors": [{"by": "ID", "value": "oldPass"}],
        "login_button_selectors": [{"by": "ID", "value": "oldLogin"}],
    }
    with open(UPDATE_TEMPLATE_FILE, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def remove_test_templates():
    for path in (DEV_TEMPLATE_FILE, BROKEN_TEMPLATE_FILE, UPDATE_TEMPLATE_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    TemplateManager.reload_templates()


# ============ 界面提示的替身（模态弹窗无法在测试中自动交互）============
class FakeMessageBox:
    """替代 qfluentwidgets.MessageBox，记录弹窗是否被触发"""

    calls = []
    answer = True

    def __init__(self, title, content, parent=None):
        FakeMessageBox.calls.append({'title': title, 'content': content})
        self.yesButton = types.SimpleNamespace(setText=lambda text: None)
        self.cancelButton = types.SimpleNamespace(setText=lambda text: None)

    def exec(self):
        return FakeMessageBox.answer


class FakeInfoBar:
    """替代 InfoBar（避免测试中创建界面控件）"""

    calls = []

    @staticmethod
    def success(**kwargs):
        FakeInfoBar.calls.append(('success', kwargs.get('title', '')))

    @staticmethod
    def error(**kwargs):
        FakeInfoBar.calls.append(('error', kwargs.get('title', '')))

    @staticmethod
    def warning(**kwargs):
        FakeInfoBar.calls.append(('warning', kwargs.get('title', '')))

    @staticmethod
    def info(**kwargs):
        FakeInfoBar.calls.append(('info', kwargs.get('title', '')))


class FakeInputDialog:
    """替代 QInputDialog"""

    text = ''
    ok = True

    @staticmethod
    def getText(parent, title, label, text=''):
        return FakeInputDialog.text, FakeInputDialog.ok


def load_gui_module():
    """导入界面模块并替换掉模态弹窗（返回模块对象）"""
    import appui.main_window as mw
    mw.MessageBox = FakeMessageBox
    mw.InfoBar = FakeInfoBar
    mw.QInputDialog = FakeInputDialog
    return mw


def fake_window(mw):
    """构造一个只包含模板保存逻辑的窗口替身"""
    window = types.SimpleNamespace()
    window._confirm_overwrite_template = \
        mw.LoginWindow._confirm_overwrite_template.__get__(window)
    window._show_save_template_dialog = \
        mw.LoginWindow._show_save_template_dialog.__get__(window)
    window._maybe_save_template = \
        mw.LoginWindow._maybe_save_template.__get__(window)
    return window


def run_save_dialog(mw, recorded, device_name, template_name=''):
    """触发界面的保存模板流程，返回是否真的弹出了提示"""
    FakeMessageBox.calls = []
    window = fake_window(mw)
    window._maybe_save_template(recorded, device_name, template_name)
    return len(FakeMessageBox.calls) > 0


# ============ 场景执行 ============
async def run_scenarios(base_url):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=[
        '--disable-dev-shm-usage', '--no-sandbox', '--ignore-certificate-errors',
    ])
    context = await browser.new_context(ignore_https_errors=True)
    session = Session(context)
    grabber = LogGrabber()

    try:
        # ============ 场景 A：已有设备模板正常命中 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/dedicated')
        session.pages.append(page)
        session._page = page

        before_exists, before_content = file_state(DEV_TEMPLATE_FILE)
        ok, msg, recorded = await login_device(session, {
            "name": "设备A", "url": f'{base_url}/dedicated',
            "username": "admin", "password": "pass123",
            "template": DEV_TEMPLATE_NAME,
        })
        log_a = grabber.take()
        after_exists, after_content = file_state(DEV_TEMPLATE_FILE)

        check("A 登录成功", ok, msg)
        check("A 汇总日志存在", "[LOGIN_SUMMARY]" in log_a)
        check("A 记录配置模板名", "配置模板=" + DEV_TEMPLATE_NAME in log_a)
        check("A 记录实际执行模板名", f"实际执行模板={DEV_TEMPLATE_NAME}" in log_a)
        check("A 记录模板文件绝对路径", DEV_TEMPLATE_FILE in log_a, DEV_TEMPLATE_FILE)
        check("A 记录用户名选择器命中", "设备模板用户名选择器命中" in log_a)
        check("A 记录密码选择器命中", "设备模板密码选择器命中" in log_a)
        check("A 记录登录按钮命中", "设备模板登录按钮已点击" in log_a)
        check("A 未触发默认模板回退", "默认模板回退=否" in log_a)
        check("A 设备模板执行=成功", "设备模板执行=成功" in log_a)
        check("A 最终使用模板为设备模板", "最终使用模板=" + DEV_TEMPLATE_NAME in log_a)
        check("A 最终结果为登录成功", "最终结果=登录成功" in log_a)
        check("A 记录各阶段耗时",
              "模板查找耗时=" in log_a and "表单填写耗时=" in log_a
              and "按钮操作耗时=" in log_a and "总耗时=" in log_a)
        check("A 未触发通用元素发现兜底", "通用元素发现兜底" not in log_a)

        # 保存提示：已有模板时不得再提示新建
        mw = load_gui_module()
        decision = evaluate_save_template_request(DEV_TEMPLATE_NAME, recorded, "设备A")
        check("A 判断结果为不提示保存", decision['need_prompt'] is False,
              decision['reason'])
        prompted = run_save_dialog(mw, recorded, "设备A", DEV_TEMPLATE_NAME)
        check("A 未弹出保存模板提示", not prompted)
        check("A 模板文件未被修改",
              before_exists == after_exists and before_content == after_content)
        await page.close()

        # ============ 场景 B：设备模板失败 -> 默认模板成功 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/generic')
        session.pages.append(page)
        session._page = page

        LoginHandler.reset_post_count()
        before_exists, before_content = file_state(DEV_TEMPLATE_FILE)
        ok, msg, recorded = await login_device(session, {
            "name": "设备B", "url": f'{base_url}/generic',
            "username": "admin", "password": "pass123",
            "template": DEV_TEMPLATE_NAME,
        })
        log_b = grabber.take()
        after_exists, after_content = file_state(DEV_TEMPLATE_FILE)
        default_file = TemplateManager.get_template_source('default')

        check("B 登录成功", ok, msg)
        check("B 设备模板执行失败被记录", "设备模板执行=失败" in log_b)
        check("B 记录失败阶段", "失败阶段=username_lookup" in log_b)
        check("B 记录开始回退默认模板", "开始回退默认模板" in log_b)
        check("B 记录回退原因", "回退原因=username_selector_not_found" in log_b)
        check("B 记录回退模板文件路径", default_file in log_b, default_file)
        check("B 默认模板执行成功", "默认模板执行=成功" in log_b)
        check("B 实际执行模板体现回退链",
              f"实际执行模板={DEV_TEMPLATE_NAME} -> default" in log_b)
        check("B 最终使用模板为 default", "最终使用模板=default" in log_b)
        check("B 最终结果为登录成功", "最终结果=登录成功" in log_b)
        check("B 仅提交一次登录请求", LoginHandler.post_count == 1,
              f"post_count={LoginHandler.post_count}")

        decision = evaluate_save_template_request(DEV_TEMPLATE_NAME, recorded, "设备B")
        check("B 判断结果为不提示保存", decision['need_prompt'] is False,
              decision['reason'])
        prompted = run_save_dialog(mw, recorded, "设备B", DEV_TEMPLATE_NAME)
        check("B 未弹出保存模板提示", not prompted)
        check("B 模板文件未被修改",
              before_exists == after_exists and before_content == after_content)
        await page.close()

        # ============ 场景 C：模板文件存在但内容损坏 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/generic')
        session.pages.append(page)
        session._page = page

        before_exists, before_content = file_state(BROKEN_TEMPLATE_FILE)
        ok, msg, recorded = await login_device(session, {
            "name": "设备C", "url": f'{base_url}/generic',
            "username": "admin", "password": "pass123",
            "template": BROKEN_TEMPLATE_NAME,
        })
        log_c = grabber.take()
        after_exists, after_content = file_state(BROKEN_TEMPLATE_FILE)

        check("C 记录模板加载失败", "模板加载失败" in log_c)
        check("C 记录 JSON 解析失败原因", "模板文件解析失败" in log_c)
        check("C 记录损坏文件路径", BROKEN_TEMPLATE_FILE in log_c, BROKEN_TEMPLATE_FILE)
        check("C 未把损坏文件记成不存在", "模板文件=(未找到)" not in log_c)
        check("C 记录查找目录", "查找目录=" in log_c)
        check("C 按回退规则使用默认模板", "最终使用模板=default" in log_c)
        check("C 最终结果为登录成功", "最终结果=登录成功" in log_c)

        decision = evaluate_save_template_request(BROKEN_TEMPLATE_NAME, recorded,
                                                  "设备C")
        check("C 判断结果为不提示新建", decision['need_prompt'] is False,
              decision['reason'])
        check("C 明确区分「存在但损坏」",
              decision['state'] is not None and decision['state']['exists']
              and not decision['state']['loadable'])
        prompted = run_save_dialog(mw, recorded, "设备C", BROKEN_TEMPLATE_NAME)
        check("C 未弹出保存模板提示", not prompted)
        check("C 损坏文件未被覆盖",
              before_exists == after_exists and before_content == after_content)
        await page.close()

        # ============ 场景 D：模板库中没有对应模板 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/generic')
        session.pages.append(page)
        session._page = page

        check("D 前置条件：模板不存在",
              not os.path.exists(os.path.join(TEMPLATE_DIR,
                                              f'{MISSING_TEMPLATE_NAME}.json')))
        ok, msg, recorded = await login_device(session, {
            "name": "设备D", "url": f'{base_url}/generic',
            "username": "admin", "password": "pass123",
            "template": MISSING_TEMPLATE_NAME,
        })
        log_d = grabber.take()
        check("D 记录模板加载失败", "模板加载失败" in log_d)
        check("D 记录查找目录", "查找目录=" in log_d)
        check("D 记录文件未找到", "模板文件=(未找到)" in log_d)
        check("D 记录缺失原因", "不存在" in log_d)
        check("D 按既有规则回退默认模板", "最终使用模板=default" in log_d)

        decision = evaluate_save_template_request(MISSING_TEMPLATE_NAME, recorded,
                                                  "设备D")
        check("D 允许提示保存新模板", decision['need_prompt'] is True,
              decision['reason'])
        check("D 新建目标为配置中的模板名",
              decision['target_name'] == MISSING_TEMPLATE_NAME,
              decision['target_name'])

        # 用户取消 -> 不得写入模板文件
        FakeMessageBox.answer = False
        prompted = run_save_dialog(mw, recorded, "设备D", MISSING_TEMPLATE_NAME)
        FakeMessageBox.answer = True
        check("D 缺失模板时弹出保存提示", prompted)
        check("D 用户取消后未创建模板文件",
              not os.path.exists(os.path.join(TEMPLATE_DIR,
                                              f'{MISSING_TEMPLATE_NAME}.json')))
        await page.close()

        # ============ 场景 E：已有模板需要更新（区分新建 / 更新）============
        # 使用一套不被模板库中任何模板覆盖的选择器，确保走“更新已有模板”分支
        recorded_update = {
            'username_selectors': [{'by': 'ID', 'value': 'updUser'}],
            'password_selectors': [{'by': 'ID', 'value': 'updPass'}],
            'login_button_selectors': [{'by': 'ID', 'value': 'updLogin'}],
        }
        before_exists, before_content = file_state(UPDATE_TEMPLATE_FILE)

        decision = evaluate_save_template_request('', recorded_update,
                                                  UPDATE_TEMPLATE_NAME)
        check("E 已有同名模板时进入更新模式", decision['mode'] == 'update',
              f"mode={decision['mode']} target={decision['target_name']}")

        # 用户取消更新 -> 原模板文件内容保持不变
        FakeMessageBox.answer = False
        prompted = run_save_dialog(mw, recorded_update, UPDATE_TEMPLATE_NAME, '')
        FakeMessageBox.answer = True
        after_exists, after_content = file_state(UPDATE_TEMPLATE_FILE)
        check("E 更新前有明确确认弹窗", prompted)
        check("E 用户取消后模板文件内容不变",
              before_exists == after_exists and before_content == after_content)

        # 用户确认更新 -> 模板被更新
        prompted = run_save_dialog(mw, recorded_update, UPDATE_TEMPLATE_NAME, '')
        after_exists, after_content = file_state(UPDATE_TEMPLATE_FILE)
        check("E 确认后模板被更新", prompted and after_content != before_content)
        with open(UPDATE_TEMPLATE_FILE, 'r', encoding='utf-8') as handle:
            updated = json.load(handle)
        check("E 更新后内容为本次录制的选择器",
              updated['username_selectors'] == recorded_update['username_selectors'],
              str(updated.get('username_selectors')))

        # 新建与更新必须区分开
        decision_create = evaluate_save_template_request('__pol_brand_new__',
                                                         recorded_update, "全新设备")
        check("E 不存在的模板走新建模式", decision_create['mode'] == 'create',
              f"mode={decision_create['mode']}")

        # ============ 场景 F：三种登录入口一致性 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/dedicated')
        session.pages.append(page)
        session._page = page

        device_f = {
            "name": "设备F", "url": f'{base_url}/dedicated',
            "username": "admin", "password": "pass123",
            "template": DEV_TEMPLATE_NAME,
        }

        # F1 普通登录（单设备登录）
        ok, msg, recorded_f = await login_device(session, device_f)
        log_f1 = grabber.take()
        check("F 普通登录成功", ok, msg)
        check("F 普通登录有汇总日志", "[LOGIN_SUMMARY]" in log_f1)
        check("F 普通登录入口标识正确", "入口=单设备登录" in log_f1)
        check("F 普通登录最终模板正确",
              "最终使用模板=" + DEV_TEMPLATE_NAME in log_f1)

        # F2 快捷登录
        orig_get = browser_mod.BrowserManager.get
        orig_valid = browser_mod.BrowserManager.is_valid
        browser_mod.BrowserManager.get = classmethod(lambda cls, name: session)
        browser_mod.BrowserManager.is_valid = classmethod(
            lambda cls, s: s is not None and s.context is not None)
        try:
            ok, msg, recorded_f2 = await quick_login(
                "设备F", f'{base_url}/dedicated', "admin", "pass123",
                DEV_TEMPLATE_NAME)
            log_f2 = grabber.take()
            check("F 快捷登录成功", ok, msg)
            check("F 快捷登录有汇总日志", "[LOGIN_SUMMARY]" in log_f2)
            check("F 快捷登录入口标识正确", "入口=快捷登录" in log_f2)
            check("F 快捷登录最终模板正确",
                  "最终使用模板=" + DEV_TEMPLATE_NAME in log_f2)
        finally:
            browser_mod.BrowserManager.get = orig_get
            browser_mod.BrowserManager.is_valid = orig_valid

        # F3 分组批量登录
        set_groups({"策略测试组": [dict(device_f)]})
        orig_create = browser_mod.BrowserManager.create
        orig_close = browser_mod.BrowserManager.close_group

        async def fake_create(cls, name, url=None):
            return session
        browser_mod.BrowserManager.create = classmethod(fake_create)
        browser_mod.BrowserManager.close_group = classmethod(
            lambda cls, name: asyncio.sleep(0))
        try:
            results, candidates = await login_group("策略测试组",
                                                     lambda m, c, t: None)
            log_f3 = grabber.take()
            check("F 分组登录成功", results and results[0][0] is True, str(results))
            check("F 分组登录有汇总日志", "[LOGIN_SUMMARY]" in log_f3)
            check("F 分组登录入口标识正确", "入口=分组批量登录" in log_f3)
            check("F 分组登录最终模板正确",
                  "最终使用模板=" + DEV_TEMPLATE_NAME in log_f3)
            check("F 分组登录返回带设备名与模板名的录制候选",
                  candidates and candidates[0]['device'] == "设备F"
                  and candidates[0]['template'] == DEV_TEMPLATE_NAME,
                  str(candidates))
        finally:
            browser_mod.BrowserManager.create = orig_create
            browser_mod.BrowserManager.close_group = orig_close

        # F4 三个入口的最终模板必须一致，且都不得提示保存
        finals = []
        for text in (log_f1, log_f2, log_f3):
            line = [l for l in text.splitlines() if l.startswith('最终使用模板=')]
            finals.append(line[0] if line else '')
        check("F 三种入口最终模板一致", len(set(finals)) == 1 and finals[0],
              str(finals))

        for recorded_item, label in ((recorded_f, '普通'), (recorded_f2, '快捷')):
            decision = evaluate_save_template_request(DEV_TEMPLATE_NAME,
                                                      recorded_item, "设备F")
            check(f"F {label}入口不提示保存", decision['need_prompt'] is False,
                  decision['reason'])
        prompted = run_save_dialog(mw, recorded_f, "设备F", DEV_TEMPLATE_NAME)
        check("F 分组入口不提示保存", not prompted)

        # F5 多设备并发时日志可区分
        page_a = await context.new_page()
        await browser_mod.navigate(page_a, f'{base_url}/dedicated')
        page_b = await context.new_page()
        await browser_mod.navigate(page_b, f'{base_url}/dedicated')
        session_a = Session(context, page_a)
        session_b = Session(context, page_b)

        dev_a = dict(device_f, name="并发设备A")
        dev_b = dict(device_f, name="并发设备B")
        await asyncio.gather(
            login_device(session_a, dev_a),
            login_device(session_b, dev_b),
        )
        log_f5 = grabber.take()
        task_ids = set()
        for line in log_f5.splitlines():
            if line.startswith('任务='):
                task_ids.add(line.strip())
        check("F 并发登录产生不同任务ID", len(task_ids) >= 2, str(sorted(task_ids)))
        check("F 并发日志可区分设备",
              "设备=并发设备A" in log_f5 and "设备=并发设备B" in log_f5)
        check("F 并发登录均记录汇总日志",
              log_f5.count('[LOGIN_SUMMARY]') == 2,
              str(log_f5.count('[LOGIN_SUMMARY]')))

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
    write_dev_template()
    write_broken_template()
    write_update_template()
    TemplateManager.reload_templates()
    started = time.monotonic()
    try:
        with TestServer() as server:
            asyncio.run(run_scenarios(server.base_url))
    finally:
        remove_test_templates()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"模板策略验证: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
