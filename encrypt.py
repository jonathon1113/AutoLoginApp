"""
加密解密模块
- 使用机器相关信息生成密钥
- 带随机盐的概率加密/解密用户名和密码
- 每次加密使用随机盐，相同明文产生不同密文
"""
import hashlib
import os
import sys
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

# 获取程序所在目录
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
KEY_FILE = os.path.join(APP_DIR, ".key")

# ---------------------------------------------------------------------------
# 机器密钥缓存
#
# 历史问题：GUI 程序在「加载设备 / 刷新配置 / 导入 Excel」时会反复启动
# wmic.exe（控制台程序）读取主板序列号，每台设备的用户名、密码各调用一次，
# 于是出现黑色命令行窗口连续闪烁（用户看到的 "vimc.exe" 即 wmic.exe）。
#
# 修复方式（不改变密钥派生结果，历史 devices.json 仍可正常解密）：
# 1. 机器序列号在进程生命周期内不变 -> 进程级缓存，整个进程最多调用一次；
# 2. 以 CREATE_NO_WINDOW + 隐藏窗口的方式启动 wmic，杜绝黑色控制台窗口。
# ---------------------------------------------------------------------------
_MACHINE_KEY_CACHE = None
_MACHINE_KEY_LOCK = threading.Lock()
_WMIC_CALL_COUNT = 0


def no_window_kwargs():
    """构造「不弹出控制台窗口」的 subprocess 参数（仅 Windows 生效）。

    PyInstaller 的 --noconsole / windowed 模式只隐藏**本程序**的控制台，
    无法隐藏被独立启动的外部命令行程序，因此必须显式传入
    CREATE_NO_WINDOW / STARTF_USESHOWWINDOW。

    本函数是项目内统一的外部进程启动参数来源：凡是 GUI 程序需要启动
    外部进程（wmic、资源管理器等），都必须带上这里的参数，
    否则会闪现黑色命令行窗口。
    """
    kwargs = {}
    if os.name != 'nt':
        return kwargs
    import subprocess
    kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = startupinfo
    except Exception:
        pass
    return kwargs


# 兼容旧调用名（内部实现保留别名，避免遗漏的历史调用点失效）
_no_window_kwargs = no_window_kwargs


def _read_baseboard_serial():
    """读取主板序列号，失败返回空字符串。

    保持与历史实现完全一致的取值方式（wmic baseboard get serialnumber
    的最后一行），仅改变进程启动方式并做进程级缓存。
    """
    global _WMIC_CALL_COUNT
    try:
        import subprocess
        _WMIC_CALL_COUNT += 1
        result = subprocess.run(
            ['wmic', 'baseboard', 'get', 'serialnumber'],
            capture_output=True, text=True,
            **_no_window_kwargs()
        )
        if result.returncode == 0:
            serial = result.stdout.strip().split('\n')[-1].strip()
            if serial:
                return serial
    except Exception:
        pass
    return ''


def get_machine_key():
    """获取机器相关的密钥（进程内只计算一次）"""
    global _MACHINE_KEY_CACHE
    with _MACHINE_KEY_LOCK:
        if _MACHINE_KEY_CACHE is not None:
            return _MACHINE_KEY_CACHE

        key_parts = []

        try:
            key_parts.append(os.environ.get('COMPUTERNAME', ''))
        except:
            pass

        try:
            key_parts.append(os.environ.get('USERNAME', ''))
        except:
            pass

        # 主板序列号（进程级缓存 + 无控制台启动）
        serial = _read_baseboard_serial()
        if serial:
            key_parts.append(serial)

        key_string = '|'.join(key_parts) + '|LoginApp_Secure_Key_2024'
        _MACHINE_KEY_CACHE = hashlib.sha256(key_string.encode('utf-8')).digest()
        return _MACHINE_KEY_CACHE


def reset_machine_key_cache():
    """清空机器密钥缓存（仅供测试与诊断使用）"""
    global _MACHINE_KEY_CACHE
    with _MACHINE_KEY_LOCK:
        _MACHINE_KEY_CACHE = None


def get_wmic_call_count():
    """返回本次进程内实际启动 wmic 的次数（用于验证黑框修复效果）"""
    return _WMIC_CALL_COUNT

def _derive_keys(master_key, salt):
    """使用PBKDF2派生出加密密钥和HMAC密钥"""
    derived = hashlib.pbkdf2_hmac('sha256', master_key, salt, iterations=50000, dklen=48)
    return derived[:16], derived[16:32], derived[32:]

def _xor_with_stream(data, stream):
    """XOR 数据与密钥流"""
    result = bytearray(len(data))
    for i in range(len(data)):
        result[i] = data[i] ^ stream[i % len(stream)]
    return bytes(result)

def _generate_keystream(key, nonce, length):
    """生成密钥流（使用CBC-MAC风格的迭代哈希）"""
    stream = bytearray()
    counter = 0
    
    while len(stream) < length:
        # 使用密钥、随机数和计数器生成伪随机字节
        h = hashlib.sha256()
        h.update(key)
        h.update(nonce)
        h.update(counter.to_bytes(4, 'big'))
        stream.extend(h.digest())
        counter += 1
    
    return bytes(stream[:length])

def simple_encrypt(text):
    """
    概率加密 - 使用随机盐和密钥流XOR
    输出格式: SALT:Base64(JSON)
    """
    if not text:
        return text
    
    try:
        master_key = get_machine_key()
        
        # 生成随机盐和nonce
        salt = os.urandom(16)
        nonce = os.urandom(16)
        
        # 派生密钥
        enc_key, mac_key, _ = _derive_keys(master_key, salt)
        
        # 填充到块大小
        block_size = 16
        text_bytes = text.encode('utf-8')
        padded_len = ((len(text_bytes) + block_size - 1) // block_size + 1) * block_size
        padded = text_bytes + os.urandom(padded_len - len(text_bytes))
        
        # 生成密钥流并加密
        keystream = _generate_keystream(enc_key, nonce, len(padded))
        ciphertext = _xor_with_stream(padded, keystream)
        
        # 计算认证标签
        auth_data = salt + nonce + ciphertext
        import hmac
        tag = hmac.new(mac_key, auth_data, hashlib.sha256).digest()[:16]
        
        # 打包
        payload = {
            "salt": base64.b64encode(salt).decode('ascii'),
            "nonce": base64.b64encode(nonce).decode('ascii'),
            "data": base64.b64encode(ciphertext).decode('ascii'),
            "tag": base64.b64encode(tag).decode('ascii'),
            "orig_len": len(text_bytes)
        }
        
        return 'SALT:' + base64.b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    
    except Exception as e:
        print(f"[WARN] Encrypt failed: {e}")
        return _fallback_encrypt(text)

def simple_decrypt(encrypted_text):
    """解密 - 支持SALT:新格式和ENC:旧格式"""
    if not encrypted_text:
        return encrypted_text
    
    if encrypted_text.startswith('SALT:'):
        try:
            payload_b64 = encrypted_text[5:]
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            payload = json.loads(payload_json)
            
            salt = base64.b64decode(payload['salt'])
            nonce = base64.b64decode(payload['nonce'])
            ciphertext = base64.b64decode(payload['data'])
            stored_tag = base64.b64decode(payload['tag'])
            orig_len = payload.get('orig_len', len(ciphertext))
            
            master_key = get_machine_key()
            
            # 重新派生密钥
            enc_key, mac_key, _ = _derive_keys(master_key, salt)
            
            # 验证HMAC
            auth_data = salt + nonce + ciphertext
            import hmac
            expected_tag = hmac.new(mac_key, auth_data, hashlib.sha256).digest()[:16]
            if stored_tag != expected_tag:
                print("[ERROR] HMAC verification failed")
                return encrypted_text
            
            # 解密
            keystream = _generate_keystream(enc_key, nonce, len(ciphertext))
            padded = _xor_with_stream(ciphertext, keystream)
            
            # 移除填充并还原原始长度
            plaintext = padded[:orig_len]
            return plaintext.decode('utf-8')
        
        except Exception as e:
            print(f"[ERROR] Decrypt failed: {e}")
            return encrypted_text
    
    elif encrypted_text.startswith('ENC:'):
        return _fallback_decrypt(encrypted_text)
    
    else:
        return encrypted_text

def _fallback_encrypt(text):
    """回退加密（XOR）"""
    key = get_machine_key()
    text_bytes = text.encode('utf-8')
    key_repeated = (key * ((len(text_bytes) // len(key)) + 1))[:len(text_bytes)]
    encrypted = bytes(a ^ b for a, b in zip(text_bytes, key_repeated))
    return 'ENC:' + base64.b64encode(encrypted).decode('ascii')

def _fallback_decrypt(encrypted_text):
    """回退解密（XOR）"""
    if not encrypted_text.startswith('ENC:'):
        return encrypted_text
    try:
        key = get_machine_key()
        encrypted = base64.b64decode(encrypted_text[4:])
        key_repeated = (key * ((len(encrypted) // len(key)) + 1))[:len(encrypted)]
        decrypted = bytes(a ^ b for a, b in zip(encrypted, key_repeated))
        return decrypted.decode('utf-8')
    except:
        return encrypted_text

def encrypt_device_data(device):
    """加密设备数据"""
    result = device.copy()
    if 'username' in result:
        result['username'] = simple_encrypt(result['username'])
    if 'password' in result:
        result['password'] = simple_encrypt(result['password'])
    return result

def decrypt_device_data(device):
    """解密设备数据"""
    result = device.copy()
    if 'username' in result:
        result['username'] = simple_decrypt(result['username'])
    if 'password' in result:
        result['password'] = simple_decrypt(result['password'])
    return result

def encrypt_devices(devices, workers=None):
    """批量加密设备数据。

    每个字段使用**独立随机盐**加密，字段之间互不影响，因此可以安全地
    并行派生密钥：PBKDF2 在 OpenSSL 实现中会释放 GIL，多线程能真正并行。

    实测 100 台设备（200 个字段）串行约需 13 秒（PBKDF2 50000 轮，
    约 65ms/字段），这是 Excel 导入曾经把界面卡住十几秒的主因；
    并行后耗时大幅缩短，密文格式与串行完全一致（仍为 SALT: 前缀）。
    """
    if not devices:
        return []
    if workers is None:
        workers = min(len(devices), max(1, os.cpu_count() or 2))
    if workers <= 1:
        return [encrypt_device_data(d) for d in devices]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(encrypt_device_data, devices))

def decrypt_devices(devices):
    return [decrypt_device_data(d) for d in devices]

def migrate_old_data():
    """迁移旧格式到新格式"""
    config_file = os.path.join(APP_DIR, "devices.json")
    if not os.path.exists(config_file):
        return False, "File not found"
    
    try:
        with open(config_file, 'r', encoding='utf-8-sig') as f:
            devices = json.load(f)
        
        migrated = 0
        for device in devices:
            for field in ['username', 'password']:
                if field in device and device[field].startswith('ENC:'):
                    old_value = _fallback_decrypt(device[field])
                    device[field] = simple_encrypt(old_value)
                    migrated += 1
        
        if migrated > 0:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(devices, f, ensure_ascii=False, indent=2)
            return True, f"Migrated {migrated} fields"
        return False, "No old format data"
    except Exception as e:
        return False, f"Migration failed: {e}"

# 测试
if __name__ == "__main__":
    print("=== Encrypt Module Test ===")
    
    # 自检用的假密码（仅用于验证加解密往返，**不得**写入任何真实凭据）
    test_password = "demo_password_123"
    
    print(f"\nOriginal: {test_password}")
    
    enc1 = simple_encrypt(test_password)
    print(f"\nEncrypt 1: {enc1[:50]}...")
    
    enc2 = simple_encrypt(test_password)
    print(f"Encrypt 2: {enc2[:50]}...")
    
    enc3 = simple_encrypt(test_password)
    print(f"Encrypt 3: {enc3[:50]}...")
    
    if enc1 != enc2 and enc2 != enc3 and enc1 != enc3:
        print("\n[OK] Different ciphertexts each time")
    else:
        print("\n[FAIL] Same ciphertext")
    
    dec1 = simple_decrypt(enc1)
    dec2 = simple_decrypt(enc2)
    dec3 = simple_decrypt(enc3)
    
    print(f"\nDecrypt 1: {dec1}")
    print(f"Decrypt 2: {dec2}")
    print(f"Decrypt 3: {dec3}")
    
    if dec1 == test_password and dec2 == test_password and dec3 == test_password:
        print("[OK] All decryptions correct")
    else:
        print("[FAIL] Decryption error")
    
    # Test device data
    device = {"name": "Test", "url": "http://test.com", "username": "admin", "password": "Pass123"}
    enc_dev = encrypt_device_data(device)
    dec_dev = decrypt_device_data(enc_dev)
    
    if device['username'] == dec_dev['username'] and device['password'] == dec_dev['password']:
        print("[OK] Device encrypt/decrypt correct")
    else:
        print("[FAIL] Device encryption error")
        print(f"  Expected: {device['username']}, Got: {dec_dev['username']}")
        print(f"  Expected: {device['password']}, Got: {dec_dev['password']}")
    
    # Test old format compatibility
    old = _fallback_encrypt("OldPass")
    new_dec = simple_decrypt(old)
    if new_dec == "OldPass":
        print("[OK] Old format compatible")
    else:
        print("[FAIL] Old format error")
