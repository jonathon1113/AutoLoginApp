# -*- coding: utf-8 -*-
"""读取项目统一版本号（供 build.bat 等脚本调用）。

版本来源：appcore/config.py 的 APP_VERSION。
输出示例：5.0.3
"""
import re
import sys
from pathlib import Path

config_file = Path(__file__).parent.resolve() / 'appcore' / 'config.py'
text = config_file.read_text(encoding='utf-8')
match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
if not match:
    print('0.0.0', file=sys.stderr)
    sys.exit(1)
print(match.group(1))
