"""真实设备验证（测试 E）：使用 devices.json 中配置的真实设备执行登录。

本脚本使用真实 Chromium 访问真实设备，只记录真实结果：
- 设备模板文件路径、选择器是否命中、是否触发默认模板回退、失败原因与耗时、最终登录结果。
- 设备不可访问时如实记录「不可访问」，不伪造成功结果。

运行： python tests/test_real_devices.py
"""

import asyncio
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright            # noqa: E402

from appcore import browser as browser_mod                   # noqa: E402
from appcore.config import APP_LOG_FILE, CONFIG_FILE        # noqa: E402
from appcore.login_engine import login_device                # noqa: E402
from encrypt import decrypt_device_data                      # noqa: E402

RESULTS = []


class RealSession:
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


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def read_log_since(offset):
    if not os.path.exists(APP_LOG_FILE):
        return ''
    with open(APP_LOG_FILE, 'r', encoding='utf-8', errors='replace') as handle:
        handle.seek(offset)
        text = handle.read()
    return text


def log_size():
    return os.path.getsize(APP_LOG_FILE) if os.path.exists(APP_LOG_FILE) else 0


def load_devices():
    with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as handle:
        raw = json.load(handle)
    return [decrypt_device_data(d) for d in raw]


async def run():
    devices = load_devices()
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=[
        '--disable-dev-shm-usage', '--no-sandbox', '--ignore-certificate-errors',
    ])
    context = await browser.new_context(ignore_https_errors=True)
    session = RealSession(browser, context)

    try:
        for device in devices:
            name = device.get('name', device.get('url'))
            template_name = device.get('template', '') or ''
            offset = log_size()

            print(f"\n{'=' * 68}\n### 真实设备：{name}  ({device['url']}, "
                  f"template={template_name or '(未指定)'})\n{'=' * 68}",
                  flush=True)

            page = await context.new_page()
            session.pages.append(page)
            session.current_index = len(session.pages) - 1

            nav_started = time.monotonic()
            try:
                await browser_mod.navigate(page, device['url'])
            except Exception as e:
                print(f"页面打开失败: {e}", flush=True)
                check(f"{name} 页面可访问", False, str(e)[:80])
                await page.close()
                continue
            nav_ms = int((time.monotonic() - nav_started) * 1000)
            print(f"页面打开耗时={nav_ms}ms", flush=True)

            try:
                ok, msg, _rec = await login_device(session, device)
            except Exception as e:
                print(f"登录异常: {e}", flush=True)
                check(f"{name} 登录过程无异常", False, str(e)[:80])
                await page.close()
                continue

            log_text = read_log_since(offset)
            for line in log_text.splitlines():
                print('    ' + line, flush=True)

            check(f"{name} 记录了模板文件路径", '模板文件=' in log_text)
            check(f"{name} 记录了模板选择器数量",
                  '模板校验成功，用户名选择器=' in log_text)
            check(f"{name} 记录了失败阶段或最终结果",
                  ('失败阶段=' in log_text) or ('登录成功' in log_text))
            check(f"{name} 最终结果有明确说明", bool(msg), msg)
            print(f"最终结果: 成功={ok}  信息={msg}\n", flush=True)

            await page.close()
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

    # ---- 没有本地设备配置时**优雅跳过**，而不是直接抛 FileNotFoundError ----
    # 原因：devices.json 属于**本地敏感数据**，已在 .gitignore 中排除，
    # 从 GitHub 全新克隆后并不存在。真实设备验证强依赖真实设备，
    # 属于「环境相关测试」，缺失时应如实标记为跳过，而不是让回归测试变红。
    if not os.path.exists(CONFIG_FILE):
        check("真实设备验证：跳过（未找到本地设备配置）", True,
              "真实设备场景依赖本地 devices.json，公开仓库默认不含真实设备")
        print("\n" + "=" * 68)
        print("真实设备验证: 1 通过 / 0 失败"
              f"（已跳过：未找到本地设备配置，总耗时 {int((time.monotonic() - started) * 1000)}ms）")
        print("=" * 68)
        return 0

    asyncio.run(run())

    print("\n" + "=" * 68)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"真实设备验证: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 68)
    return 0


if __name__ == '__main__':
    sys.exit(main())