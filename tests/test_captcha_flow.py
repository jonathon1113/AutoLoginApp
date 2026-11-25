"""验证码自动识别闭环测试（tests/test_captcha_flow.py）。

用本地模拟服务器的 /captcha_ocr 页面（4 位数字+大小写字母图片验证码，
服务端不区分大小写）验证「识别 -> 填写 -> 提交 -> 失败刷新重试」的完整闭环。

OCR 引擎用假实现替换（避免依赖真实 ddddocr 与外部验证码样本），
但走的仍是真实的 Playwright 页面定位、截图、填写、提交与结果判定链路。

覆盖：
1. 识别正确 -> 自动登录成功
2. OCR 首次返回错误值 -> 服务端提示「验证码错误」-> 自动刷新并重试 -> 第 2 次成功
3. OCR 返回非法字符 -> 不提交，直接刷新
4. 置信度低于阈值 -> 不提交，直接刷新
5. ddddocr 不可用 -> 完全退回旧行为（不提交、提示「需要验证码」）
6. 无验证码页面 -> 不触发图片查找
7. 模板保存后包含 captcha_image_selectors，二次登录命中模板来源

运行： python tests/test_captcha_flow.py
"""

import asyncio
import os
import re
import sys
import tempfile
import time
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

from appcore import captcha_cache
from appcore import config as app_config            # noqa: E402
from appcore import login_engine as le              # noqa: E402
from appcore import templates as templates_mod      # noqa: E402
from appcore.automation import get_loop             # noqa: E402
from appcore.browser import BrowserManager, BrowserService  # noqa: E402
from appcore.templates import DEFAULT_TEMPLATE, TemplateManager  # noqa: E402
from tests.test_server import LoginHandler, TestServer  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return ok


class FakeRecognizer:
    """假 OCR 引擎。

    script 为依次返回的 (文本, 置信度) 列表；文本为 None 时表示
    「返回服务端当前生效的验证码」（用小写返回，顺便验证不区分大小写）。

    对外契约与真实 CaptchaRecognizer 保持一致：
    长度 / 字符集不合法、或置信度低于阈值时，一律返回空文本
    （真实识别器是在 recognize() 内部完成这些校验的）。
    """

    _PATTERN = re.compile(r'^[0-9A-Za-z]{4}$')

    def __init__(self, script=None, available=True):
        self.script = list(script or [])
        self.available = available
        self.calls = 0

    def is_available(self):
        return self.available

    def recognize(self, png_bytes, variant=None):
        self.calls += 1
        if self.script:
            index = min(self.calls - 1, len(self.script) - 1)
            text, confidence = self.script[index]
        else:
            text, confidence = None, 0.93
        if text is None:
            text = getattr(LoginHandler, 'current_captcha_code', '') or ''
            # 故意用小写：服务端不区分大小写，必须仍然通过
            text = text.lower()
        if not self._PATTERN.match(text or ''):
            return '', confidence
        if confidence < app_config.CAPTCHA_OCR_MIN_CONFIDENCE:
            return '', confidence
        return text, confidence


async def _attempt(page, template=None, username='admin', password='pass123',
                   label='默认模板'):
    """跑一次完整的模板尝试，返回 outcome（含 detail / captcha_attempts）。"""
    TemplateManager.start_recording()
    ctx = le.LoginContext('验证码测试设备', le.ENTRY_SINGLE)
    return await le._run_template_attempt(page, template or DEFAULT_TEMPLATE,
                                          label, ctx, username, password)


def _pillow_available():
    """测试页需要 Pillow 生成验证码图片；缺失时无法运行本用例集。"""
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


async def run_all():
    if not _pillow_available():
        print("[SKIP] 未安装 Pillow，无法生成验证码图片，"
              "跳过验证码闭环测试（pip install Pillow）")
        return RESULTS

    original_recognizer = le.recognizer
    temp_dir = tempfile.mkdtemp(prefix='captcha_tpl_')
    original_template_dir = templates_mod.TEMPLATE_DIR
    templates_mod.TEMPLATE_DIR = temp_dir
    original_cache_file = captcha_cache.CACHE_FILE
    original_cache_data = captcha_cache._cache
    captcha_cache.CACHE_FILE = os.path.join(temp_dir, 'captcha_absent.json')
    captcha_cache._cache = None

    try:
        with TestServer() as server:
            base = server.base_url
            session = await BrowserManager.create("__captcha_test__")

            # ---------- 1. 识别正确 -> 自动登录成功 ----------
            async def t_success():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                fake = FakeRecognizer()
                le.recognizer = fake
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                ok = (outcome['ok'] and outcome['reason'] == 'ok'
                      and '自动通过验证码' in (outcome.get('detail') or ''))
                check("1 识别正确时自动登录成功", ok,
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')} "
                      f"attempts={outcome.get('captcha_attempts')}")
                check("1b 首次即成功（只尝试 1 次）",
                      outcome.get('captcha_attempts') == 1,
                      str(outcome.get('captcha_attempts')))
                check("1c 提交次数为 1", LoginHandler.post_count == 1,
                      f"提交次数={LoginHandler.post_count}")
                check("1d 最终跳转到 /dashboard",
                      '/dashboard' in (session.page.url or ''),
                      session.page.url)

            # ---------- 2. 首次识别错误 -> 刷新重试后成功 ----------
            async def t_retry():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                # 第 1 次返回错误值，第 2 次返回服务端当前验证码
                fake = FakeRecognizer(script=[('ZZZZ', 0.91), (None, 0.93)])
                le.recognizer = fake
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                # 注意：outcome['ok'] 在验证码失败时也是 True（保留旧语义：
                # 模板已生成），因此必须用 reason == 'ok' 判断登录成功。
                check("2 识别错误后自动刷新重试并成功",
                      outcome.get('reason') == 'ok'
                      and outcome.get('captcha_attempts') == 2,
                      f"reason={outcome.get('reason')} "
                      f"attempts={outcome.get('captcha_attempts')} "
                      f"detail={outcome.get('detail')}")
                check("2b 两次提交（错误 + 正确）",
                      LoginHandler.post_count == 2,
                      f"提交次数={LoginHandler.post_count}")

            # ---------- 3. 非法字符 -> 不提交 ----------
            async def t_invalid():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                fake = FakeRecognizer(script=[('AB3', 0.91)])
                le.recognizer = fake
                # 压缩时间预算：本用例只需验证「不提交」，不必跑满整个预算
                old_budget = app_config.CAPTCHA_ATTEMPT_BUDGET
                app_config.CAPTCHA_ATTEMPT_BUDGET = 4
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                    app_config.CAPTCHA_ATTEMPT_BUDGET = old_budget
                check("3 非法识别结果不提交登录表单",
                      LoginHandler.post_count == 0,
                      f"提交次数={LoginHandler.post_count}")
                check("3b 非法识别结果最终判为验证码失败",
                      outcome.get('reason') == le.FAIL_CAPTCHA,
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')}")
                check("3c 尝试次数不超过上限",
                      0 < outcome.get('captcha_attempts', 0)
                      <= app_config.CAPTCHA_OCR_MAX_ATTEMPTS,
                      str(outcome.get('captcha_attempts')))
                check("3d 达到时间预算后停止重试",
                      outcome.get('captcha_attempts', 0)
                      < app_config.CAPTCHA_OCR_MAX_ATTEMPTS,
                      f"attempts={outcome.get('captcha_attempts')}")

            # ---------- 4. 低置信度 -> 不提交 ----------
            async def t_low_confidence():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                fake = FakeRecognizer(script=[(None, 0.10)])
                le.recognizer = fake
                old_budget = app_config.CAPTCHA_ATTEMPT_BUDGET
                app_config.CAPTCHA_ATTEMPT_BUDGET = 4
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                    app_config.CAPTCHA_ATTEMPT_BUDGET = old_budget
                check("4 低置信度不提交登录表单",
                      LoginHandler.post_count == 0,
                      f"提交次数={LoginHandler.post_count}")
                check("4b 低置信度最终判为验证码失败",
                      outcome.get('reason') == le.FAIL_CAPTCHA,
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')}")

            # ---------- 5. ddddocr 不可用 -> 退回旧行为 ----------
            async def t_unavailable():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                fake = FakeRecognizer(available=False)
                le.recognizer = fake
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                check("5 OCR 不可用时不提交登录表单",
                      LoginHandler.post_count == 0,
                      f"提交次数={LoginHandler.post_count}")
                check("5b OCR 不可用时提示「需要验证码」",
                      outcome.get('reason') == le.FAIL_CAPTCHA
                      and outcome.get('detail') == '需要验证码',
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')}")

            # ---------- 6. 无验证码页面 -> 不触发图片查找 ----------
            async def t_no_captcha():
                LoginHandler.reset_post_count()
                calls = []
                original_find = le.find_captcha_image

                async def spy(*args, **kwargs):
                    calls.append(kwargs.get('selectors')
                                 or (args[2] if len(args) > 2 else None))
                    return await original_find(*args, **kwargs)

                le.find_captcha_image = spy
                try:
                    await session.open_page(f"{base}/login")
                    outcome = await _attempt(session.page)
                finally:
                    le.find_captcha_image = original_find
                check("6 无验证码页面不查找验证码图片", not calls,
                      f"查找次数={len(calls)}")
                check("6b 无验证码页面正常登录成功",
                      outcome.get('ok') and outcome.get('reason') == 'ok',
                      f"reason={outcome.get('reason')}")

            # ---------- 7. 模板保存后命中模板来源 ----------
            async def t_template_source():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                fake = FakeRecognizer()
                le.recognizer = fake
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer

                recorded = TemplateManager.get_last_recorded() or {}
                image_selectors = recorded.get('captcha_image_selectors') or []
                check("7 录制结果包含 captcha_image_selectors",
                      bool(image_selectors), str(image_selectors))
                if not image_selectors:
                    return

                template = {
                    'name': 'captcha_ocr_test',
                    'username_selectors': recorded.get('username_selectors', []),
                    'password_selectors': recorded.get('password_selectors', []),
                    'login_button_selectors':
                        recorded.get('login_button_selectors', []),
                    'captcha_selectors': recorded.get('captcha_selectors', []),
                    'captcha_image_selectors': image_selectors,
                }

                seen = []
                original_find = le.find_captcha_image

                async def spy(page, captcha_field=None, selectors=None, **kwargs):
                    result = await original_find(page, captcha_field, selectors,
                                                **kwargs)
                    seen.append((selectors, result.get('source')))
                    return result

                le.find_captcha_image = spy
                try:
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page, template)
                finally:
                    le.find_captcha_image = original_find

                check("7b 二次登录使用模板中的验证码图片选择器",
                      bool(seen) and bool(seen[0][0]),
                      f"selectors={seen[0][0] if seen else None}")
                check("7c 二次登录的验证码图片来源为模板",
                      bool(seen) and seen[0][1] == 'template',
                      f"source={seen[0][1] if seen else None}")
                check("7d 二次登录仍然成功",
                      outcome.get('ok') and outcome.get('reason') == 'ok',
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')}")

            # ---------- 8. 内联 SVG 验证码（el-input 风格页面）----------
            async def t_svg():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                fake = FakeRecognizer()
                le.recognizer = fake
                try:
                    await session.open_page(f"{base}/captcha_svg")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                recorded = TemplateManager.get_last_recorded() or {}
                check("8 内联 SVG 验证码能定位并登录成功",
                      outcome.get('reason') == 'ok',
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')}")
                check("8b SVG 验证码图片选择器已录制",
                      bool(recorded.get('captcha_image_selectors')),
                      str(recorded.get('captcha_image_selectors')))
                check("8c SVG 页面提交次数为 1",
                      LoginHandler.post_count == 1,
                      f"提交次数={LoginHandler.post_count}")

            # ---------- 9. 验证码错误后站点清空账号密码 ----------
            async def t_clear_form():
                LoginHandler.reset_post_count()
                LoginHandler.reset_captcha()
                # 第 1 次给错误验证码（触发服务端清空表单），第 2 次给正确码
                fake = FakeRecognizer(script=[('ZZZZ', 0.91), (None, 0.95)])
                le.recognizer = fake
                try:
                    await session.open_page(f"{base}/captcha_clear")
                    outcome = await _attempt(session.page)
                finally:
                    le.recognizer = original_recognizer
                check("9 表单被清空后能自动重填账号密码并登录成功",
                      outcome.get('reason') == 'ok',
                      f"reason={outcome.get('reason')} "
                      f"detail={outcome.get('detail')} "
                      f"attempts={outcome.get('captcha_attempts')}")
                check("9b 共提交 2 次（先错后对）",
                      LoginHandler.post_count == 2,
                      f"提交次数={LoginHandler.post_count}")

            # ---------- 10. 模板声明无验证码 -> 跳过验证码查找 ----------
            async def t_skip_no_captcha():
                template = {
                    'name': 'no_captcha_tpl',
                    'username_selectors': [{'by': 'CSS_SELECTOR',
                                            'value': 'input[name="username"]'}],
                    'password_selectors': [{'by': 'CSS_SELECTOR',
                                            'value': 'input[type="password"]'}],
                    'login_button_selectors': [{'by': 'CSS_SELECTOR',
                                                'value': 'button[type="submit"]'}],
                    'captcha_selectors': [],
                    'captcha_image_selectors': [],
                }
                LoginHandler.reset_post_count()
                await session.open_page(f"{base}/login")
                started = time.monotonic()
                outcome = await _attempt(session.page, template,
                                         label='设备模板')
                elapsed = int((time.monotonic() - started) * 1000)
                check("10 模板声明无验证码时跳过验证码查找",
                      outcome.get('reason') == 'ok'
                      and outcome.get('captcha_ms') == 0,
                      f"reason={outcome.get('reason')} "
                      f"captcha_ms={outcome.get('captcha_ms')} 总耗时={elapsed}ms")

            for name, func in (
                    ("1 识别正确自动登录", t_success),
                    ("2 错误后刷新重试", t_retry),
                    ("3 非法字符不提交", t_invalid),
                    ("4 低置信度不提交", t_low_confidence),
                    ("5 OCR 不可用退回旧行为", t_unavailable),
                    ("6 无验证码页面", t_no_captcha),
                    ("7 模板来源命中", t_template_source),
                    ("8 内联 SVG 验证码", t_svg),
                    ("9 表单清空后重填", t_clear_form),
                    ("10 无验证码模板跳过", t_skip_no_captcha),
            ):
                try:
                    await func()
                except Exception as e:
                    traceback.print_exc()
                    check(name, False, f"异常: {e}")

            await BrowserManager.close_all()
    finally:
        le.recognizer = original_recognizer
        templates_mod.TEMPLATE_DIR = original_template_dir
        captcha_cache.CACHE_FILE = original_cache_file
        captcha_cache._cache = original_cache_data

    await BrowserService.stop()
    return RESULTS


def report():
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("")
    print("=" * 60)
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
