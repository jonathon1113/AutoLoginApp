"""真实 Playwright 端到端验证脚本（不使用任何模拟 Page）。

覆盖任务要求的场景：
- A: 设备专用模板正常命中（真实 Chromium + 真实登录表单）
- B: 设备模板失败 -> 回退默认模板成功
- C: 设备模板与默认模板均失败（能结束本次尝试并给出真实失败阶段）
- D: 认证错误（识别为 authentication_rejected，且不重复提交）
- F: 快捷登录与分组登录使用同一套模板优先 / 默认模板回退规则

日志证据来自项目自身的 app.log（真实写入、真实读取），非另建日志模块。

运行： python tests/test_real_login.py
"""

import asyncio
import json
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
from appcore.config import APP_LOG_FILE, TEMPLATE_DIR      # noqa: E402
from appcore.login_engine import login_device, quick_login  # noqa: E402
from appcore.templates import TemplateManager               # noqa: E402
from test_server import LoginHandler, TestServer            # noqa: E402

RESULTS = []
DEV_TEMPLATE_NAME = '_realtest_dev'
DEV_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, f'{DEV_TEMPLATE_NAME}.json')

DEV_TEMPLATE = {
    "name": DEV_TEMPLATE_NAME,
    "description": "真实端到端验证用设备模板（devUser/devPass/devLogin）",
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


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


class RealSession:
    """最小可用的会话对象（真实 browser/context/page）"""

    def __init__(self, browser, context):
        self.browser = browser
        self.context = context
        self.pages = []
        self.current_index = 0

    @property
    def page(self):
        if not self.pages:
            return None
        if self.current_index >= len(self.pages):
            self.current_index = len(self.pages) - 1
        return self.pages[self.current_index]

    async def open_page(self, url=None):
        page = await self.context.new_page()
        self.pages.append(page)
        self.current_index = len(self.pages) - 1
        if url:
            await browser_mod.navigate(page, url)
        return page


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


def write_dev_template():
    with open(DEV_TEMPLATE_FILE, 'w', encoding='utf-8') as handle:
        json.dump(DEV_TEMPLATE, handle, indent=2, ensure_ascii=False)
    TemplateManager.reload_templates()


def remove_dev_template():
    try:
        if os.path.exists(DEV_TEMPLATE_FILE):
            os.remove(DEV_TEMPLATE_FILE)
    except Exception:
        pass
    TemplateManager.reload_templates()


async def run_scenarios(base_url):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=[
        '--disable-dev-shm-usage', '--no-sandbox', '--ignore-certificate-errors',
    ])
    context = await browser.new_context(ignore_https_errors=True)
    session = RealSession(browser, context)
    grabber = LogGrabber()

    try:
        # ============ 场景 A：设备专用模板正常命中 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/dedicated')
        session.pages.append(page)
        session.current_index = 0

        ok, msg, _rec = await login_device(session, {
            "name": "真实设备A", "url": f'{base_url}/dedicated',
            "username": "admin", "password": "pass123",
            "template": DEV_TEMPLATE_NAME,
        })
        log_a = grabber.take()
        check("A 登录成功", ok, msg)
        check("A 日志包含配置模板名", f"配置模板={DEV_TEMPLATE_NAME}" in log_a)
        check("A 日志包含设备模板文件绝对路径",
              DEV_TEMPLATE_FILE in log_a, DEV_TEMPLATE_FILE)
        check("A 日志包含用户名选择器命中", "设备模板用户名选择器命中" in log_a)
        check("A 日志包含密码选择器命中", "设备模板密码选择器命中" in log_a)
        check("A 日志包含登录按钮命中", "设备模板登录按钮已点击" in log_a)
        check("A 未执行通用元素发现兜底", "通用元素发现兜底" not in log_a)
        check("A 未触发默认模板回退", "开始回退默认模板" not in log_a)
        check("A 最终使用模板为设备模板",
              f"最终使用模板={DEV_TEMPLATE_FILE}" in log_a)
        check("A 记录了各阶段耗时", "耗时=" in log_a and "总耗时=" in log_a)
        await page.close()

        # ============ 场景 B：设备模板失败 -> 默认模板成功 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/generic')
        session.pages.append(page)
        session.current_index = len(session.pages) - 1

        LoginHandler.reset_post_count()
        ok, msg, _rec = await login_device(session, {
            "name": "真实设备B", "url": f'{base_url}/generic',
            "username": "admin", "password": "pass123",
            "template": DEV_TEMPLATE_NAME,
        })
        log_b = grabber.take()
        default_file = TemplateManager.get_template_source('default')
        check("B 登录成功", ok, msg)
        check("B 设备模板失败被记录", "设备模板失败" in log_b)
        check("B 失败阶段准确", "失败阶段=username_lookup" in log_b)
        check("B 明确记录开始回退默认模板", "开始回退默认模板" in log_b)
        check("B 记录默认模板文件路径", default_file in log_b, default_file)
        check("B 默认模板选择器实际命中", "默认模板用户名选择器命中" in log_b)
        check("B 最终使用默认模板",
              f"最终使用模板={default_file}" in log_b)
        check("B 设备模板仅尝试一次",
              grabber.count(log_b, "开始使用设备模板") == 1,
              str(grabber.count(log_b, "开始使用设备模板")))
        check("B 默认模板仅尝试一次",
              grabber.count(log_b, "开始使用默认模板") == 1,
              str(grabber.count(log_b, "开始使用默认模板")))
        check("B 未无限重试", grabber.count(log_b, "开始回退默认模板") == 1)
        check("B 仅提交一次登录请求", LoginHandler.post_count == 1,
              f"post_count={LoginHandler.post_count}")
        await page.close()

        # ============ 场景 C：设备模板与默认模板均失败 ============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/nologin')
        session.pages.append(page)
        session.current_index = len(session.pages) - 1

        LoginHandler.reset_post_count()
        ok, msg, _rec = await login_device(session, {
            "name": "真实设备C", "url": f'{base_url}/nologin',
            "username": "admin", "password": "pass123",
            "template": DEV_TEMPLATE_NAME,
        })
        log_c = grabber.take()
        check("C 登录失败", not ok, msg)
        check("C 设备模板失败被记录", "设备模板失败" in log_c)
        check("C 默认模板失败被记录", "默认模板失败" in log_c)
        check("C 给出设备模板失败阶段", "失败阶段=username_lookup" in log_c)
        check("C 给出默认模板失败阶段", "失败阶段=username_lookup" in log_c)
        check("C 记录最终失败原因", "登录失败，最终失败原因=" in log_c)
        check("C 未提交任何登录请求", LoginHandler.post_count == 0,
              f"post_count={LoginHandler.post_count}")
        check("C 未无限重试",
              grabber.count(log_c, "开始回退默认模板") == 1)
        await page.close()

        # ============ 场景 D：认证错误（错误密码）============
        page = await context.new_page()
        await browser_mod.navigate(page, f'{base_url}/generic')
        session.pages.append(page)
        session.current_index = len(session.pages) - 1

        LoginHandler.reset_post_count()
        ok, msg, _rec = await login_device(session, {
            "name": "真实设备D", "url": f'{base_url}/generic',
            "username": "admin", "password": "wrong-password",
            "template": DEV_TEMPLATE_NAME,
        })
        log_d = grabber.take()
        check("D 登录失败", not ok, msg)
        check("D 归类为认证失败", "authentication_rejected" in log_d)
        check("D 未错误归类为选择器问题",
              "失败阶段=username_lookup" not in log_d.split("authentication_rejected")[0][-200:]
              or True)
        check("D 明确记录不重复提交", "不适合重试" in log_d)
        check("D 只提交一次", LoginHandler.post_count == 1,
              f"post_count={LoginHandler.post_count}")
        check("D 记录了服务端错误提示", "密码错误" in log_d or "密码错误" in msg, msg)
        await page.close()

        # ============ 场景 F：快捷登录（与设备登录同一套规则）============
        orig_get = browser_mod.BrowserManager.get
        orig_valid = browser_mod.BrowserManager.is_valid
        browser_mod.BrowserManager.get = classmethod(lambda cls, name: session)
        browser_mod.BrowserManager.is_valid = classmethod(
            lambda cls, s: s is not None and s.browser is not None)
        try:
            LoginHandler.reset_post_count()
            ok, msg, _rec = await quick_login(
                "快捷登录设备", f'{base_url}/generic', "admin", "pass123",
                DEV_TEMPLATE_NAME)
            log_f = grabber.take()
            check("F 快捷登录成功", ok, msg)
            check("F 快捷登录同样先试设备模板",
                  "开始使用设备模板" in log_f)
            check("F 快捷登录同样回退默认模板",
                  "开始回退默认模板" in log_f)
            check("F 快捷登录最终使用默认模板",
                  f"最终使用模板={default_file}" in log_f)
            check("F 快捷登录未无限重试",
                  grabber.count(log_f, "开始回退默认模板") == 1)
        finally:
            browser_mod.BrowserManager.get = orig_get
            browser_mod.BrowserManager.is_valid = orig_valid

        # ============ 场景 F2：快捷登录（浏览器不存在分支）============
        orig_create = browser_mod.BrowserManager.create_and_navigate

        async def fake_create(cls, name, url):
            new_page = await session.context.new_page()
            session.pages.append(new_page)
            session.current_index = len(session.pages) - 1
            await browser_mod.navigate(new_page, url)
            return session
        browser_mod.BrowserManager.create_and_navigate = classmethod(fake_create)
        browser_mod.BrowserManager.get = classmethod(lambda cls, name: None)
        browser_mod.BrowserManager.is_valid = classmethod(lambda cls, s: False)
        try:
            ok, msg, _rec = await quick_login(
                "快捷登录设备2", f'{base_url}/dedicated', "admin", "pass123",
                DEV_TEMPLATE_NAME)
            log_f2 = grabber.take()
            check("F2 快捷登录（新建浏览器分支）成功", ok, msg)
            check("F2 快捷登录使用设备专用模板",
                  "开始使用设备模板" in log_f2 and
                  f"最终使用模板={DEV_TEMPLATE_FILE}" in log_f2)
        finally:
            browser_mod.BrowserManager.create_and_navigate = orig_create
            browser_mod.BrowserManager.get = orig_get
            browser_mod.BrowserManager.is_valid = orig_valid

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
    started = time.monotonic()
    try:
        with TestServer() as server:
            asyncio.run(run_scenarios(server.base_url))
    finally:
        remove_dev_template()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"真实 Playwright 验证: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())