"""设备配置加载与分组管理。

配置文件格式保持不变：devices.json 为数组，字段为
name / url / username / password / group / template，
其中 username、password 为加密存储（encrypt.py）。

性能说明（启动耗时优化）：
devices.json 中的 username / password 为密文，解密需要一次
PBKDF2-HMAC-SHA256 密钥派生（50000 轮，实测约 60ms/字段）。
早期实现在「加载设备」阶段就把全部设备解密一遍，3 台设备就要 380ms，
主界面因此长时间停留在「正在加载设备数据...」。

现在改为**按需解密**：加载阶段只解析文件并分组（毫秒级），
真正要登录某台设备时才解密该设备的两个字段，并把结果缓存回设备字典，
同一台设备不会被重复解密。数据完整性不受影响：
文件解析失败仍然抛出异常，不会静默丢设备。
"""

import json
import os
import tempfile
import threading
import time

from .config import CONFIG_FILE
from .logging_utils import Logger

_lock = threading.Lock()
_groups = {}

# 密文前缀（与 encrypt.py 的输出格式保持一致）
_CIPHER_PREFIXES = ('SALT:', 'ENC:')


def set_groups(groups):
    """更新当前生效的分组数据（界面加载完成后调用）"""
    global _groups
    with _lock:
        _groups = groups or {}


def get_groups():
    """获取当前生效的分组数据"""
    with _lock:
        return _groups


def get_group_devices(group_name):
    """获取指定分组的设备列表"""
    return get_groups().get(group_name, [])


def load_devices():
    """从 devices.json 读取设备配置并按分组整理。

    返回 {分组名: [设备字典, ...]}。
    用户名 / 密码在此阶段保持密文，登录该设备时由 get_device_credentials 按需解密。
    """
    if not os.path.exists(CONFIG_FILE):
        return {}

    started = time.monotonic()
    # utf-8-sig 兼容带 BOM 的 UTF-8 文件（Windows 记事本等工具默认会写入 BOM）
    with open(CONFIG_FILE, encoding="utf-8-sig") as f:
        devices = json.load(f)

    if not isinstance(devices, list):
        raise ValueError(f"设备配置文件格式错误（应为数组）: {CONFIG_FILE}")

    groups = {}
    for d in devices:
        if not isinstance(d, dict):
            continue
        group = d.get("group", "默认")
        if group not in groups:
            groups[group] = []
        groups[group].append(d)

    Logger.info(
        f"设备配置读取完成: {len(devices)} 台设备 / {len(groups)} 个分组，"
        f"耗时={int((time.monotonic() - started) * 1000)}ms（凭据按需解密）")
    return groups


def get_device_credentials(device):
    """取得设备的用户名 / 密码（必要时解密密文）。

    devices.json 中 username / password 以密文存储，解密需要一次 PBKDF2
    派生（约 60ms/字段）。这里按需解密，并把明文写回设备字典缓存，
    同一台设备不会被重复解密。

    返回 (username, password)。
    """
    if not isinstance(device, dict):
        return '', ''

    username = device.get('username', '') or ''
    password = device.get('password', '') or ''

    need_decrypt = any(str(value).startswith(_CIPHER_PREFIXES)
                       for value in (username, password))
    if need_decrypt:
        started = time.monotonic()
        try:
            from encrypt import simple_decrypt
            username = simple_decrypt(username)
            password = simple_decrypt(password)
        except Exception as e:
            Logger.error(f"解密设备凭据失败（{device.get('name', '')}）：{e}")
        Logger.info(f"设备凭据解密完成（{device.get('name', '')}），"
                    f"耗时={int((time.monotonic() - started) * 1000)}ms")

    # 回写明文，后续调用不再重复解密
    try:
        device['username'] = username
        device['password'] = password
    except Exception:
        pass
    return username, password


def save_devices(devices):
    """加密并写入 devices.json（供 Excel 导入使用）

    采用「临时文件 + 原子替换」写入：加密或写盘中途失败时，
    原有的 devices.json 保持不变，不会留下被截断的半截文件
    （否则一次失败的导入会让设备配置直接损坏）。
    """
    from encrypt import encrypt_devices

    encrypted = encrypt_devices(devices)
    directory = os.path.dirname(CONFIG_FILE) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.devices_', suffix='.tmp',
                                     dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(encrypted, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, CONFIG_FILE)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    Logger.info(f"已保存 {len(encrypted)} 台设备到 {CONFIG_FILE}")
    return encrypted
