"""批量自动化登录脚本（命令行版，基于 Playwright）。

- 单浏览器多标签页（与原项目行为一致）
- 浏览器保持打开，手动关闭后脚本退出
- 配置来源：devices.json（自动解密）

用法： python login_batch.py
"""

import asyncio
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from appcore.automation import get_loop          # noqa: E402
from appcore.browser import BrowserManager, BrowserService  # noqa: E402
from appcore.devices import load_devices         # noqa: E402
from appcore.login_engine import login_device     # noqa: E402


def flatten_devices(groups):
    """把分组结构展开为设备列表"""
    devices = []
    for _, items in groups.items():
        devices.extend(items)
    return devices


async def run_batch():
    groups = load_devices()
    devices = flatten_devices(groups)
    if not devices:
        print("没有找到设备配置（devices.json）")
        return 1

    print(f"\n{'=' * 60}")
    print(f"Multi-Tab Login - {len(devices)} devices")
    print(f"{'=' * 60}\n")

    session = await BrowserManager.create("batch")
    if session is None:
        print("浏览器启动失败")
        return 1

    results = []
    for i, device in enumerate(devices):
        name = device.get("name", device["url"])
        print(f"[{i + 1}/{len(devices)}] {name}")
        try:
            if i == 0:
                await session.page.goto(device["url"], wait_until='domcontentloaded')
            else:
                await session.open_page(device["url"])
        except Exception as e:
            print(f"  [FAIL] 打开页面失败: {str(e)[:60]}")
            results.append((name, False))
            continue

        success, msg, _ = await login_device(session, device)
        print(f"  [{'OK' if success else 'FAIL'}] {msg}")
        results.append((name, success))

    print(f"\n{'=' * 60}")
    print("Results:")
    print("-" * 60)
    for index, device in enumerate(devices):
        page = session.pages[index] if index < len(session.pages) else None
        title = ""
        if page is not None:
            try:
                title = (await page.title())[:35]
            except Exception:
                title = "..."
        state = "OK" if index < len(results) and results[index][1] else "FAIL"
        print(f"  Tab {index + 1}: {device.get('name', device['url'])} | {state} | {title}")

    print("-" * 60)
    print(f"{'=' * 60}")
    print("Browser is open. Close it manually when done.")
    print("Script is waiting...")

    # 等待用户手动关闭浏览器
    while BrowserManager.is_valid(session):
        await asyncio.sleep(2)

    print("Exit.")
    return 0


def main():
    loop = get_loop()
    try:
        return loop.submit(run_batch(), timeout=3600)
    finally:
        loop.shutdown(cleanup_coro=BrowserService.stop(), timeout=20)


if __name__ == "__main__":
    sys.exit(main())
