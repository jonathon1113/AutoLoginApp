"""独立运行的本地模拟登录服务器（用于 EXE 实测）。

用法： python tests/run_mock_server.py [端口]
默认端口 8765，启动后前台阻塞，Ctrl+C 退出。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_server import TestServer  # noqa: E402


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = TestServer(port=port)
    server.__enter__()
    print(f"mock login server: {server.base_url}  (login page: {server.base_url}/login)")
    print(f"username=admin password=pass123")
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        server.__exit__(None, None, None)


if __name__ == "__main__":
    main()
