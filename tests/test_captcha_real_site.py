"""真实验证码站点端到端测试（tests/test_captcha_real_site.py）。

用**真实浏览器 + 真实 OCR 引擎**驱动一个真实站点，验证整条链路：
    打开登录页 -> 定位验证码图片 -> 截图 -> 真实 ddddocr 识别
    -> 填写 -> 提交 -> 判定结果 -> 失败自动刷新重试

站点地址通过环境变量 CAPTCHA_TEST_URL 指定（默认见下方）；
默认站点需要网络（内网/测试环境），无网络时本用例自动跳过。

运行： python tests/test_captcha_real_site.py
"""

import asyncio
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from appcore import config as app_config            # noqa: E402
from appcore import login_engine as le              # noqa: E402
from appcore.automation import get_loop             # noqa: E402
from appcore.browser import BrowserManager, BrowserService  # noqa: E402
from appcore.captcha_ocr import recognizer          # noqa: E402
from appcore.templates import DEFAULT_TEMPLATE, TemplateManager  # noqa: E402

# 真实测试站点（可用环境变量覆盖）
SITE_URL = os.environ.get('CAPTCHA_TEST_URL',
                           'http://test.my.cn/captcha_login.php')
SITE_USER = os.environ.get('CAPTCHA_TEST_USER', 'admin')
SITE_PASSWORD = os.environ.get('CAPTCHA_TEST_PASSWORD', 'admin')
ROUNDS = int(os.environ.get('CAPTCHA_TEST_ROUNDS', '10'))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return ok


async def _attempt(page):
    TemplateManager.start_recording()
    ctx = le.LoginContext('真实站点设备', le.ENTRY_SINGLE)
    return await le._run_template_attempt(page, DEFAULT_TEMPLATE,
                                          '默认模板', ctx, SITE_USER, SITE_PASSWORD)


async def run_all():
    if not recognizer.is_available():
        print("[SKIP] 未安装 ddddocr，跳过真实站点测试")
        return RESULTS

    session = await BrowserManager.create("__captcha_site__")
    success = 0
    details = []
    try:
        for index in range(1, ROUNDS + 1):
            started = time.monotonic()
            try:
                await session.open_page(SITE_URL)
                outcome = await _attempt(session.page)
            except Exception as e:
                traceback.print_exc()
                details.append(f"第{index}轮异常: {e}")
                continue
            ok = outcome.get('reason') == 'ok'
            success += 1 if ok else 0
            details.append(
                f"第{index}轮: {'成功' if ok else '失败'} "
                f"尝试次数={outcome.get('captcha_attempts', 0)} "
                f"耗时={int((time.monotonic() - started) * 1000)}ms "
                f"说明={outcome.get('detail')}")
            print("  " + details[-1], flush=True)
    finally:
        await BrowserManager.close_all()

    rate = success / ROUNDS * 100 if ROUNDS else 0
    check(f"真实站点（{SITE_URL}）自动登录成功率 >= 20%", rate >= 20,
          f"{success}/{ROUNDS} = {rate:.1f}%")
    check("真实站点至少成功 1 次", success >= 1,
          f"{success}/{ROUNDS}")
    for line in details:
        print("  - " + line)

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
    loop.submit(run_all(), timeout=900)
    loop.shutdown()
    sys.exit(report())
