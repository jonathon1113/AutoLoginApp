"""验证码「已知无验证码」缓存。

用途
----
有些登录页本来就没有验证码，但模板里可能残留着旧的 captcha_selectors，
于是每次登录都要把「模板候选 + 内置候选」几十个选择器全部查一遍。

这里把「某模板 + 某页面 = 无验证码」的结论持久化到
`APP_DIR/captcha_absent.json`，下次登录同一模板/页面时直接跳过查找。

安全兜底
--------
若某次跳过之后服务端仍然提示「验证码错误」，说明页面其实有验证码：
调用方会 `clear()` 掉该条目并重新完整查找一次，因此不会因为缓存而永久失效。
"""

import json
import os
import threading
from urllib.parse import urlsplit, urlunsplit

from .config import APP_DIR

CACHE_FILE = os.path.join(APP_DIR, 'captcha_absent.json')

_lock = threading.Lock()
_cache = None


def normalize_url(url):
    """去掉查询串与锚点，避免每次登录 URL 上的时间戳导致缓存失效。"""
    try:
        parts = urlsplit(str(url or ''))
    except Exception:
        return str(url or '')
    path = (parts.path or '/').rstrip('/') or '/'
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, '', ''))


def make_key(template_label, template_name, url):
    return '%s|%s|%s' % (template_label or '', template_name or '',
                         normalize_url(url))


def _load():
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(CACHE_FILE, encoding='utf-8') as handle:
            data = json.load(handle)
        _cache = set(str(item) for item in (data or []))
    except Exception:
        _cache = set()
    return _cache


def _save():
    try:
        directory = os.path.dirname(CACHE_FILE) or '.'
        tmp = os.path.join(directory, '.captcha_absent.tmp')
        with open(tmp, 'w', encoding='utf-8') as handle:
            json.dump(sorted(_cache or []), handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def is_absent(key):
    with _lock:
        return key in _load()


def mark_absent(key):
    """记录「该模板+页面无验证码」。返回是否新增。"""
    with _lock:
        cache = _load()
        if key in cache:
            return False
        cache.add(key)
        _save()
        return True


def clear(key):
    """删除某条缓存（页面后来又有验证码时使用）。返回是否存在过。"""
    with _lock:
        cache = _load()
        if key not in cache:
            return False
        cache.discard(key)
        _save()
        return True
