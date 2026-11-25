"""验证码自动识别 —— 真实 OCR 端到端测试（tests/test_captcha_real_ocr.py）。

与 test_captcha_flow.py 的区别：本文件**不替换 OCR 引擎**，
直接使用真实的 ddddocr（本地 ONNX 模型，离线）跑完整闭环：

    真实页面（/captcha_ocr，服务端生成 4 位数字+字母验证码 + 干扰线 + 噪点）
      -> 定位验证码图片 -> 截图 -> 真实 ddddocr 识别 -> 填写 -> 提交 -> 判定结果

因为 /captcha_ocr 页面**必须**通过验证码才能登录成功，
所以「登录成功」本身就证明了「真实 OCR + 自动填写 + 自动提交 + 失败重试」
整条链路是通的。

未安装 ddddocr 时本文件整体跳过（不影响其它测试）。

运行： python tests/test_captcha_real_ocr.py
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

from appcore import config as app_config              # noqa: E402
from appcore import login_engine as le                # noqa: E402
from appcore.automation import get_loop               # noqa: E402
from appcore.browser import BrowserManager, BrowserService  # noqa: E402
from appcore.captcha_ocr import recognizer            # noqa: E402
from appcore.templates import DEFAULT_TEMPLATE, TemplateManager  # noqa: E402
from tests.test_server import LoginHandler, TestServer  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return ok


async def _attempt(page):
    """跑一次完整尝试（使用真实 OCR 引擎）。"""
    TemplateManager.start_recording()
    ctx = le.LoginContext('真实OCR设备', le.ENTRY_SINGLE)
    return await le._run_template_attempt(page, DEFAULT_TEMPLATE,
                                          '默认模板', ctx, 'admin', 'pass123')


async def run_all():
    if not recognizer.is_available():
        print("[SKIP] 未安装 ddddocr，跳过真实 OCR 端到端测试"
              "（pip install ddddocr onnxruntime Pillow）")
        return RESULTS

    rounds = 3
    try:
        with TestServer() as server:
            base = server.base_url
            session = await BrowserManager.create("__captcha_real__")
            try:
                for index in range(1, rounds + 1):
                    LoginHandler.reset_post_count()
                    LoginHandler.reset_captcha()
                    await session.open_page(f"{base}/captcha_ocr")
                    outcome = await _attempt(session.page)
                    attempts = outcome.get('captcha_attempts', 0)
                    ok = (outcome.get('reason') == 'ok'
                          and outcome.get('ok')
                          and '/dashboard' in (session.page.url or ''))
                    check(f"第 {index} 轮：真实 OCR 自动登录成功", ok,
                          f"reason={outcome.get('reason')} "
                          f"尝试次数={attempts} "
                          f"detail={outcome.get('detail')} "
                          f"url={session.page.url}")
                    check(f"第 {index} 轮：确实经过验证码识别流程", attempts >= 1,
                          f"attempts={attempts}")
            finally:
                await BrowserManager.close_all()
    except Exception as e:
        traceback.print_exc()
        check("真实 OCR 端到端测试", False, f"异常: {e}")

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
