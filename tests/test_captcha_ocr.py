"""验证码自动识别模块单元测试（tests/test_captcha_ocr.py）。

用假的 ddddocr 模块驱动，不需要真实安装 OCR 引擎，也不访问浏览器。

覆盖：
1. 识别结果长度校验（必须恰好 4 位）
2. 字符集校验（非法字符整条作废，不得删除后凑长度）
3. 大小写归一化（必须在校验通过之后做）
4. 低置信度拒绝
5. set_ranges 必须收到字符串（整数语义完全不同）
6. 引擎异常兜底（返回空结果且不抛异常）
7. ddddocr 不可用时的可用性判断
8. 多变体结果合并（取置信度更高者）

运行： python tests/test_captcha_ocr.py
"""

import base64
import io
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 控制台编码兼容（Windows GBK 控制台无法输出 ✓ 等字符）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from appcore import config as app_config                    # noqa: E402
from appcore.captcha_ocr import CaptchaRecognizer, DEFAULT_CHARSET  # noqa: E402

RESULTS = []

# 1x1 透明 PNG（base64），用于「Pillow 不可用」时的兜底
_TINY_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                 "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return ok


# ============ 假的 ddddocr ============
class _FakeOcr:
    """模拟 ddddocr.DdddOcr，记录调用参数以便断言。"""

    instances = []

    def __init__(self, show_ad=False, beta=False):
        _FakeOcr.instances.append(self)
        self.show_ad = show_ad
        self.beta = beta
        self.filter_colors = None
        self.charset_range = None
        self.results = []
        self.default = ('', 0.0)
        self.raise_on_classify = False
        self.calls = 0

    def set_ranges(self, charset_range):
        self.charset_range = charset_range

    def classification(self, img, png_fix=False, probability=False,
                       color_filter_colors=None, **kwargs):
        self.calls += 1
        self.filter_colors = color_filter_colors
        if self.raise_on_classify:
            raise RuntimeError('mock classify failure')
        if self.results:
            index = min(self.calls - 1, len(self.results) - 1)
            text, confidence = self.results[index]
        else:
            text, confidence = self.default
        return {'text': text, 'confidence': confidence,
                'probabilities': [], 'charset': self.charset_range}


def _install_fake_ddddocr():
    """把假的 ddddocr 装进 sys.modules，并返回模块对象。"""
    module = types.ModuleType('ddddocr')
    module.DdddOcr = _FakeOcr
    try:
        import importlib.machinery
        module.__spec__ = importlib.machinery.ModuleSpec('ddddocr', None)
    except Exception:
        pass
    sys.modules['ddddocr'] = module
    _FakeOcr.instances = []
    return module


def _remove_ddddocr():
    """让 ddddocr 表现为「未安装」。"""
    sys.modules['ddddocr'] = None


def _restore_ddddocr():
    sys.modules.pop('ddddocr', None)


def _png_bytes():
    """构造一张最小的合法 PNG（用于预处理变体）。"""
    try:
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('L', (40, 16), 255).save(buffer, format='PNG')
        return buffer.getvalue()
    except Exception:
        return base64.b64decode(_TINY_PNG_B64)


def _fresh_recognizer(**kwargs):
    """创建一个绑定假引擎的识别器（跳过懒加载）。"""
    options = {'min_confidence': 0.5}
    options.update(kwargs)
    recognizer = CaptchaRecognizer(**options)
    fake = _FakeOcr()
    # 标准模型与 beta 模型都指向同一个假引擎，便于断言调用参数
    recognizer._engines = {'std': fake, 'beta': fake}
    recognizer._engine_failed = False
    return recognizer, fake


# ============ 用例 ============
def test_available():
    """ddddocr 未安装时 is_available() 必须返回 False。"""
    _remove_ddddocr()
    try:
        available = CaptchaRecognizer().is_available()
    finally:
        _restore_ddddocr()
    check("ddddocr 未安装时 is_available() 为 False", available is False,
          f"is_available()={available}")


def test_normalize_case():
    """区分大小写时原样提交；不区分时可统一转大写。"""
    recognizer, fake = _fresh_recognizer(case_sensitive=True)
    fake.default = ('ab3d', 0.91)
    text, confidence = recognizer.recognize(_png_bytes())
    check("区分大小写时原样提交（不改大小写）", text == 'ab3d',
          f"text={text!r} conf={confidence:.2f}")
    check("识别成功时返回识别置信度", abs(confidence - 0.91) < 1e-6,
          f"conf={confidence:.2f}")

    recognizer, fake = _fresh_recognizer(case_sensitive=False)
    fake.default = ('ab3d', 0.91)
    text, _conf = recognizer.recognize(_png_bytes())
    check("不区分大小写时可统一转大写", text == 'AB3D', f"text={text!r}")


def test_length_validation():
    """长度不是 4 位必须整条作废。"""
    for wrong in ('AB3', 'AB3DE', ''):
        recognizer, fake = _fresh_recognizer()
        fake.default = (wrong, 0.95)
        text, _conf = recognizer.recognize(_png_bytes())
        check(f"长度非法（{wrong!r}）时整条作废", text == '', f"text={text!r}")


def test_charset_validation():
    """含非法字符必须整条作废，且不得删除非法字符后凑长度。"""
    for wrong in ('AB3D中', 'AB-D', 'AB3 ', '汉字'):
        recognizer, fake = _fresh_recognizer()
        fake.default = (wrong, 0.95)
        text, _conf = recognizer.recognize(_png_bytes())
        check(f"字符集非法（{wrong!r}）时整条作废", text == '', f"text={text!r}")


def test_low_confidence():
    """置信度低于阈值必须拒绝（不提交）。"""
    recognizer, fake = _fresh_recognizer(min_confidence=0.5)
    fake.default = ('ab3d', 0.31)
    text, confidence = recognizer.recognize(_png_bytes())
    check("置信度低于阈值时拒绝识别结果", text == '', f"text={text!r}")
    check("置信度不足时仍返回原始置信度（便于日志排查）",
          abs(confidence - 0.31) < 1e-6, f"conf={confidence:.2f}")


def test_set_ranges_receives_string():
    """set_ranges 必须收到显式字符串（整数语义完全不同）。"""
    recognizer, fake = _fresh_recognizer()
    fake.default = ('ab3d', 0.9)
    recognizer.recognize(_png_bytes())
    charset = fake.charset_range
    check("set_ranges 收到的是字符串而不是整数",
          isinstance(charset, str), f"type={type(charset).__name__}")
    check("set_ranges 收到完整 62 字符集",
          isinstance(charset, str) and len(charset) == 62,
          f"len={len(charset) if isinstance(charset, str) else 'n/a'}")
    check("set_ranges 字符集包含全部数字与大小写字母",
          isinstance(charset, str) and set(DEFAULT_CHARSET).issubset(set(charset)),
          f"charset={charset!r}")


def test_exception_fallback():
    """引擎异常必须被吞掉，返回空结果且不抛异常。"""
    recognizer, fake = _fresh_recognizer()
    fake.raise_on_classify = True
    try:
        text, confidence = recognizer.recognize(_png_bytes())
        ok = text == '' and confidence == 0.0
    except Exception as e:
        ok = False
        text, confidence = 'raised', str(e)
    check("识别异常被兜底（不抛出、不中断登录流程）", ok,
          f"text={text!r} conf={confidence!r}")


def test_empty_image():
    """空图片输入必须返回空结果。"""
    recognizer, fake = _fresh_recognizer()
    text, confidence = recognizer.recognize(b'')
    check("空图片返回空结果", text == '' and confidence == 0.0,
          f"text={text!r} conf={confidence!r}")


def test_multi_variant_merge():
    """多变体结果不一致时取置信度更高的那个。"""
    recognizer, fake = _fresh_recognizer(min_confidence=0.1)
    variants = recognizer._variants_spec()
    fake.results = [('ab3d', 0.60), ('xy9z', 0.90)]
    text, confidence = recognizer.recognize(_png_bytes())
    if len(variants) >= 2:
        expected, expected_conf = 'xy9z', 0.90
    else:
        expected, expected_conf = 'ab3d', 0.60
    check("多变体结果不一致时取置信度更高者",
          text == expected and abs(confidence - expected_conf) < 1e-6,
          f"变体数={len(variants)} text={text!r} conf={confidence:.2f}")


def test_variant_selection():
    """指定 variant 时只跑该变体（重试轮换用）。"""
    recognizer, fake = _fresh_recognizer(min_confidence=0.1)
    specs = recognizer._variants_spec()
    fake.results = [('ab3d', 0.80)]
    text, _conf = recognizer.recognize(_png_bytes(), variant=1)
    check("指定 variant 时只跑该变体", text == 'ab3d', f"text={text!r}")
    check("变体数量可枚举", len(specs) >= 3, f"变体数={len(specs)}")
    check("轮换变体不会越界",
          recognizer.variant_count() == len(specs),
          f"{recognizer.variant_count()} == {len(specs)}")


def test_config_constants():
    """配置常量必须符合需求说明。"""
    check("验证码长度固定为 4", app_config.CAPTCHA_OCR_LENGTH == 4,
          str(app_config.CAPTCHA_OCR_LENGTH))
    check("字符集为 62 个数字+大小写字母",
          len(app_config.CAPTCHA_OCR_CHARSET) == 62,
          str(len(app_config.CAPTCHA_OCR_CHARSET)))
    check("最大尝试次数为实测调优后的 30（含首次）",
          app_config.CAPTCHA_OCR_MAX_ATTEMPTS == 30,
          str(app_config.CAPTCHA_OCR_MAX_ATTEMPTS))
    check("验证码模式有独立的时间预算",
          app_config.CAPTCHA_ATTEMPT_BUDGET > app_config.TEMPLATE_ATTEMPT_BUDGET,
          f"{app_config.CAPTCHA_ATTEMPT_BUDGET} > "
          f"{app_config.TEMPLATE_ATTEMPT_BUDGET}")
    check("验证码模式预算大于普通模板预算",
          app_config.CAPTCHA_ATTEMPT_BUDGET > app_config.TEMPLATE_ATTEMPT_BUDGET,
          f"{app_config.CAPTCHA_ATTEMPT_BUDGET} > "
          f"{app_config.TEMPLATE_ATTEMPT_BUDGET}")
    check("自动识别总开关默认开启", app_config.CAPTCHA_AUTO_ENABLED is True,
          str(app_config.CAPTCHA_AUTO_ENABLED))
    check("默认原样提交识别结果（区分大小写）",
          app_config.CAPTCHA_OCR_CASE_SENSITIVE is True,
          str(app_config.CAPTCHA_OCR_CASE_SENSITIVE))
    # 实测：颜色过滤会把字符抗锯齿边缘一起抹掉，反而降低准确率，故默认关闭
    check("默认启用 beta 模型、关闭颜色过滤",
          app_config.CAPTCHA_OCR_BETA is True
          and app_config.CAPTCHA_OCR_COLOR_FILTER is False,
          f"beta={app_config.CAPTCHA_OCR_BETA} "
          f"color_filter={app_config.CAPTCHA_OCR_COLOR_FILTER}")


def test_lazy_load_and_isolation():
    """引擎必须懒加载；重复调用复用同一个引擎。"""
    _install_fake_ddddocr()
    try:
        first = CaptchaRecognizer()
        check("未识别前不创建引擎（懒加载）", not first._engines,
              f"engines={first._engines!r}")
        first._engine_failed = False
        engine = first._ensure_engine()
        check("首次识别时创建引擎", engine is not None, f"engine={engine!r}")
        check("引擎被缓存复用", first._ensure_engine() is engine, "")
        check("标准模型与 beta 模型使用独立引擎实例",
              first._ensure_engine(beta=False) is not engine, "")
    finally:
        _restore_ddddocr()


def main():
    test_available()
    test_normalize_case()
    test_length_validation()
    test_charset_validation()
    test_low_confidence()
    test_set_ranges_receives_string()
    test_exception_fallback()
    test_empty_image()
    test_multi_variant_merge()
    test_variant_selection()
    test_config_constants()
    test_lazy_load_and_isolation()

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
    sys.exit(main())
