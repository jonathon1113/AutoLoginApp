"""Playwright 登录引擎功能测试。

针对本地模拟登录服务器逐项验证：
1. 浏览器有头启动（headless=False / slow_mo=100）
2. 单设备登录成功
3. 登录失败（错误提示识别）
4. 表单未找到
5. 验证码检测
6. 分组批量登录（多标签页）
7. 快捷登录（复用浏览器 + 新标签页）
8. 模板选择器录制
9. 选择器转换
10. SSL 证书告警处理
11. 浏览器关闭与资源清理

所有 Playwright 操作均在自动化线程内执行（与应用运行方式一致）。

运行： python tests/test_engine.py
"""

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 与 main.py 保持一致：源码运行时若浏览器已按「路径 0」安装，则沿用同一路径模式
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

# 控制台编码兼容（Windows GBK 控制台无法输出 ✓ 等字符）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from appcore import config as app_config                    # noqa: E402
from appcore.automation import get_loop                     # noqa: E402
from appcore.browser import (                                # noqa: E402
    QUICK_SESSION,
    BrowserManager,
    BrowserService,
    handle_ssl,
    to_locator,
)
from appcore.devices import set_groups                       # noqa: E402
from appcore.login_engine import login_device, login_group, quick_login  # noqa: E402
from appcore.templates import TemplateManager                # noqa: E402
from tests.test_server import TestServer                     # noqa: E402

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


async def check(name, func):
    try:
        ok, detail = await func()
    except Exception as e:
        traceback.print_exc()
        ok, detail = False, f"异常: {e}"
    record(name, ok, detail)
    return ok


async def run_all():
    with TestServer() as server:
        base = server.base_url
        good = {"name": "设备A", "url": f"{base}/login", "username": "admin",
                "password": "pass123", "group": "测试组", "template": "default"}
        bad = {"name": "设备B", "url": f"{base}/login", "username": "admin",
               "password": "wrong", "group": "测试组", "template": "default"}
        captcha = {"name": "设备C", "url": f"{base}/captcha", "username": "admin",
                   "password": "pass123", "group": "测试组", "template": "default"}

        set_groups({"测试组": [good, bad, captcha]})

        # ---- 1. 浏览器有头启动 ----
        session = await BrowserManager.create("__test__")
        record("浏览器有头启动(headless=False)", session is not None,
               f"Chromium 版本 {session.browser.version}" if session else "启动失败")

        # ---- 2. 单设备登录成功 ----
        async def t_login_ok():
            await session.open_page(f"{base}/login")
            success, msg, _ = await login_device(session, good)
            return success and "OK" in msg, msg
        await check("单设备登录成功", t_login_ok)

        # ---- 3. 登录失败识别 ----
        async def t_login_fail():
            await session.open_page(f"{base}/login")
            success, msg, _ = await login_device(session, bad)
            return (not success) and ("密码错误" in msg or "失败" in msg), msg
        await check("登录失败(错误提示识别)", t_login_fail)

        # ---- 4. 表单未找到 ----
        async def t_no_form():
            await session.open_page(f"{base}/nologin")
            success, msg, _ = await login_device(session, good)
            return (not success) and "Form not found" in msg, msg
        await check("表单未找到", t_no_form)

        # ---- 4b. 已登录检测 ----
        async def t_already_logged():
            await session.open_page(f"{base}/dashboard")
            success, msg, _ = await login_device(session, good)
            return success and "已登录" in msg, msg
        await check("已登录检测(跳过已登录设备)", t_already_logged)

        # ---- 5. 验证码检测 ----
        # 关闭验证码自动识别：保持「发现验证码即停止、不提交」的历史行为，
        # 原断言不变（自动识别由 tests/test_captcha_flow.py 单独覆盖）。
        async def t_captcha():
            original_auto = app_config.CAPTCHA_AUTO_ENABLED
            app_config.CAPTCHA_AUTO_ENABLED = False
            try:
                await session.open_page(f"{base}/captcha")
                success, msg, _ = await login_device(session, captcha)
            finally:
                app_config.CAPTCHA_AUTO_ENABLED = original_auto
            # V6.0.1 起不再统一回「已完成」，而是如实给出「需要验证码」
            return success and ("已完成" in msg or "需要验证码" in msg), msg
        await check("验证码检测", t_captcha)

        # ---- 6. 模板选择器录制 ----
        async def t_record():
            await session.open_page(f"{base}/login")
            TemplateManager.start_recording()
            success, msg, recorded = await login_device(session, good)
            has_user = bool(recorded and recorded.get('username_selectors'))
            has_pwd = bool(recorded and recorded.get('password_selectors'))
            return success and has_user and has_pwd, f"录制结果: {recorded}"
        await check("模板选择器录制", t_record)

        # ---- 7. 分组批量登录（多标签页）----
        async def t_group():
            results, recorded = await login_group("测试组", lambda m, c, t: None)
            ok = len(results) == 3 and results[0][0] is True and results[1][0] is False
            group_session = BrowserManager.get("测试组")
            pages = group_session.page_count if group_session else 0
            return ok and pages == 3, f"结果={results}, 标签页数={pages}"
        await check("分组批量登录(多标签页)", t_group)

        # ---- 7b. 分组登录完成后自动切换到第一个标签页 ----
        async def t_group_tab():
            group_session = BrowserManager.get("测试组")
            idx = group_session.current_index if group_session else -1
            return idx == 0, f"current_index={idx}（应为 0，即第一个标签页）"
        await check("分组登录完成后自动切换到第一个标签页", t_group_tab)

        # ---- 8. 快捷登录 ----
        async def t_quick():
            success, msg, _ = await quick_login("快捷设备", f"{base}/login", "admin", "pass123")
            success2, msg2, _ = await quick_login("快捷设备2", f"{base}/login", "admin", "pass123")
            quick_session = BrowserManager.get(QUICK_SESSION)
            pages = quick_session.page_count if quick_session else 0
            return success and success2 and pages == 2, f"{msg} / {msg2} / 标签页={pages}"
        await check("快捷登录(复用浏览器+新标签页)", t_quick)

        # ---- 8b. 快捷登录完成后保持当前标签页，不切换到第一个标签页 ----
        async def t_quick_tab():
            quick_session = BrowserManager.get(QUICK_SESSION)
            idx = quick_session.current_index if quick_session else -1
            count = quick_session.page_count if quick_session else 0
            return count >= 2 and idx == count - 1, (
                f"current_index={idx} 标签页数={count}（应停在最后登录的标签页，不回到 0）")
        await check("快捷登录完成后不再切换到第一个标签页", t_quick_tab)

        # ---- 9. 选择器转换 ----
        async def t_selector():
            page = session.page
            loc = to_locator(page, 'ID', 'username')
            count = await loc.count() if loc is not None else -1
            return loc is not None and count >= 0, f"ID 选择器转换 -> {loc}"
        await check("Selenium选择器->Playwright Locator 转换", t_selector)

        # ---- 10. SSL 处理 ----
        async def t_ssl():
            return (await handle_ssl(session.page)) is False, "普通页面返回 False"
        await check("SSL 证书告警处理", t_ssl)

        # ---- 11. 关闭浏览器 ----
        async def t_close():
            await BrowserManager.close_all()
            return BrowserManager.session_count() == 0, f"剩余会话 {BrowserManager.session_count()}"
        await check("关闭所有浏览器", t_close)

    await BrowserService.stop()
    return RESULTS


def report():
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"测试结果: {passed} 通过 / {failed} 失败")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    loop = get_loop()
    loop.submit(run_all(), timeout=600)
    loop.shutdown()
    sys.exit(report())
