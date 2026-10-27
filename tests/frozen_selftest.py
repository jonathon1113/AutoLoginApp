"""打包态（PyInstaller 冻结环境）自检入口。

用于验证 Playwright 的 Node 驱动与 Chromium 在 EXE 中是否可用：
1. 以 headless=False / slow_mo=100 启动 Chromium
2. 打开本地模拟登录页
3. 填写用户名/密码并提交
4. 校验是否跳转到 /dashboard（登录成功）

用法：
    set SELFTEST_URL=http://127.0.0.1:8765/login
    python tests/frozen_selftest.py
结果写入 selftest_result.txt（便于 EXE 冻结态读取）。
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appcore.browser import BrowserManager, BrowserService  # noqa: E402
from appcore.config import get_app_dir                   # noqa: E402
from appcore.login_engine import login_device              # noqa: E402

# 结果文件写到可写数据目录：源码运行时为项目根，打包运行时为 EXE 同目录
# （冻结环境下 __file__ 位于临时解压目录，不能作为结果落盘位置）。
RESULT_FILE = os.path.join(get_app_dir(), 'selftest_result.txt')


def write(text):
    with open(RESULT_FILE, 'w', encoding='utf-8') as f:
        f.write(text)


async def main():
    url = os.environ.get('SELFTEST_URL', 'http://127.0.0.1:8765/login')
    lines = []

    session = await BrowserManager.create('__selftest__')
    if session is None:
        write('FAIL 浏览器启动失败')
        print('FAIL 浏览器启动失败')
        return 1

    version = session.browser.version
    lines.append(f'PASS 浏览器启动成功 Chromium {version}')
    print(lines[-1], flush=True)

    page = session.page
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    await asyncio.sleep(1)

    device = {"name": "自检设备", "url": url, "username": "admin",
              "password": "pass123", "group": "自检组", "template": "default"}
    success, msg, _ = await login_device(session, device)
    lines.append(('PASS' if success else 'FAIL') + f' 登录流程: {msg}')
    print(lines[-1], flush=True)

    current = page.url
    ok_url = current.endswith('/dashboard')
    lines.append(('PASS' if ok_url else 'FAIL') + f' 登录后URL: {current}')
    print(lines[-1], flush=True)

    await BrowserManager.close_all()
    await BrowserService.stop()

    write('\n'.join(lines))
    return 0 if (success and ok_url) else 1


if __name__ == '__main__':
    try:
        code = asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        write(f'FAIL 异常: {e}')
        code = 1
    sys.exit(code)
