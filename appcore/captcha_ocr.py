"""验证码自动识别模块（纯离线，无任何联网依赖）。

职责：把登录页上的「数字 + 大小写字母」图片验证码截图识别成 4 位文本。

设计要点（务必保持，详见需求说明 3.1）：
1. 懒加载：首次 recognize() 时才 import ddddocr 并创建引擎（约 1~2 秒），
   绝不能在程序启动或 UI 线程里初始化；
2. 线程安全：ddddocr 引擎不是线程安全的，所有 set_ranges + classification
   必须放在同一个 threading.Lock 内；
3. 字符集必须用「显式字符串」传给 set_ranges：
   ddddocr 1.6.x 的整数语义是「默认字符集前 N+1 个字符」，
   传整数会得到完全错误的结果；
4. 结果必须同时满足「长度正确 + 字符集正确 + 置信度达标」才可使用，
   非法字符不允许删除后凑长度，整条作废；
5. 大小写：默认**原样提交**（既兼容区分大小写的站点，也兼容不区分的站点；
   统一转大写只会在「区分大小写」的站点上把正确答案改错）；
6. 任何异常都必须被吞掉并返回 ("", 0.0)，绝不中断登录流程。

实测（真实验证码站点，彩色干扰线 + 小字号衬线字体）：
- 默认模型整图识别：4 位合法输出率仅 10%~20%；
- beta 模型：4 位合法输出率 55%~67%；
- 叠加 ddddocr 内置「颜色过滤」（去掉彩色干扰线）后明显提升；
- 因此本模块按「多个识别变体」组织，重试时轮换变体，覆盖不同失效模式。
"""

import io
import re
import threading

from .config import (CAPTCHA_OCR_BETA, CAPTCHA_OCR_CASE_SENSITIVE,
                     CAPTCHA_OCR_CHARSET, CAPTCHA_OCR_COLOR_FILTER,
                     CAPTCHA_OCR_LENGTH, CAPTCHA_OCR_MIN_CONFIDENCE,
                     CAPTCHA_OCR_MULTI_PASS, CAPTCHA_OCR_NORMALIZE_TO,
                     CAPTCHA_OCR_PREPROCESS)
from .logging_utils import Logger

# 默认字符集：数字 + 小写字母 + 大写字母
DEFAULT_CHARSET = ("0123456789"
                   "abcdefghijklmnopqrstuvwxyz"
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# ddddocr 内置的颜色过滤预设：把这些颜色的干扰线去掉。
# 注意：**不能**包含 black / white / gray —— 那会把黑色字符一起抹掉。
DEFAULT_FILTER_COLORS = ('red', 'blue', 'green', 'yellow',
                         'orange', 'purple', 'cyan')


class CaptchaRecognizer:
    """4 位数字+字母验证码识别器：懒加载、线程安全、纯离线。"""

    def __init__(self, charset=DEFAULT_CHARSET, length=4,
                 case_sensitive=True, min_confidence=0.5,
                 preprocess=True, multi_pass=True,
                 normalize_to='upper', use_opencv=False, beta=True,
                 color_filter=True, filter_colors=None):
        """
        charset          允许出现的字符集合
        length          期望长度（必须整条匹配，不允许裁剪）
        case_sensitive  True=原样提交识别结果（推荐，兼容两类站点）；
                        False=校验通过后按 normalize_to 统一大小写
        min_confidence  置信度下限，低于该值视为识别失败
        preprocess      是否生成灰度 + 对比度增强 + 放大的预处理变体
        multi_pass      是否跑多个变体并合并结果
        normalize_to    归一化方向：'upper' / 'lower'（仅 case_sensitive=False 时生效）
        use_opencv      是否尝试启用 OpenCV 颜色过滤增强（可选依赖，缺失时自动跳过）
        beta            是否使用 ddddocr 的 beta 模型（对干扰强的小字号验证码明显更好）
        color_filter    是否使用 ddddocr 内置颜色过滤（去掉彩色干扰线）
        filter_colors   颜色过滤预设列表（默认去掉红/蓝/绿/黄/橙/紫/青）
        """
        self.charset = str(charset or DEFAULT_CHARSET)
        self.length = int(length or 4)
        self.case_sensitive = bool(case_sensitive)
        self.min_confidence = float(min_confidence)
        self.preprocess = bool(preprocess)
        self.multi_pass = bool(multi_pass)
        self.normalize_to = 'lower' if str(normalize_to).lower() == 'lower' else 'upper'
        self.use_opencv = bool(use_opencv)
        self.beta = bool(beta)
        self.color_filter = bool(color_filter)
        self.filter_colors = list(filter_colors or DEFAULT_FILTER_COLORS)

        self._lock = threading.Lock()
        self._engines = {}
        self._engine_failed = False
        self._pattern = re.compile(r"^[%s]{%d}$" % (re.escape(self.charset),
                                                    self.length))

    # ------------------------------------------------------------------
    # 可用性
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """只检查 ddddocr 是否安装，不初始化模型（不产生任何耗时）。"""
        try:
            import importlib.util
            return importlib.util.find_spec('ddddocr') is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 引擎
    # ------------------------------------------------------------------
    def _ensure_engine(self, beta=None):
        """在锁内创建（并缓存）ddddocr 引擎；失败返回 None。

        beta=True 使用 ddddocr 的 beta 模型：对「小字号 + 彩色干扰线」
        的验证码明显优于默认模型。
        """
        use_beta = self.beta if beta is None else bool(beta)
        key = 'beta' if use_beta else 'std'
        engine = self._engines.get(key)
        if engine is not None:
            return engine
        if self._engine_failed:
            return None
        try:
            import ddddocr
        except Exception as e:
            self._engine_failed = True
            Logger.warning(f"验证码识别不可用：未安装 ddddocr（{str(e)[:80]}）")
            return None
        try:
            try:
                engine = ddddocr.DdddOcr(show_ad=False, beta=use_beta)
            except TypeError:
                # 老版本没有 beta 参数
                engine = ddddocr.DdddOcr(show_ad=False)
            self._engines[key] = engine
            Logger.info(f"验证码识别引擎已就绪（ddddocr，"
                        f"{'beta' if use_beta else '标准'}模型，本地离线）")
        except Exception as e:
            self._engine_failed = True
            Logger.warning(f"验证码识别引擎初始化失败：{str(e)[:120]}")
            engine = None
        return engine

    def warmup(self) -> bool:
        """预热引擎（可选：在后台线程调用，避免首次登录时等待 1~2 秒）。"""
        with self._lock:
            return self._ensure_engine() is not None

    # ------------------------------------------------------------------
    # 识别变体
    # ------------------------------------------------------------------
    def variant_count(self) -> int:
        """可用识别变体数量（重试时按此数量轮换）。"""
        return len(self._variants_spec())

    def _variants_spec(self):
        """变体定义：(名称, beta, 颜色过滤, 模式, 缩放倍数, 参数)。

        顺序即优先级。实测（真实站点 test.my.cn）：
          - 原始图：4 位合法输出约 20%~35%，正确率约 3%~7%；
          - 「去彩色干扰」掩膜 + 3 倍放大：4 位输出约 80%，正确率约 15%
            （约 3 倍提升），且在简单验证码（模拟服务器）上仍为 100%。
        因此掩膜变体排在最前。
        """
        specs = []
        if self.preprocess:
            specs.append(('mask_s70v175_3x', True, False, 'mask', 3,
                          {'smax': 70, 'vmax': 175, 'dark': 140}))
            specs.append(('mask_s40v200_3x', True, False, 'mask', 3,
                          {'smax': 40, 'vmax': 200, 'dark': 140}))
            specs.append(('mask_s55v195_2x', True, False, 'mask', 2,
                          {'smax': 55, 'vmax': 195, 'dark': 140}))
            specs.append(('gray_3x', True, self.color_filter, 'gray', 3, {}))
        specs.append(('raw', True, self.color_filter, 'raw', 1, {}))
        return specs

    def _scale_image(self, png_bytes, scale):
        """灰度 + 自动对比度 + 放大（scale<=1 时原样返回）。

        注意：结论保存为 **RGB** 三通道 —— 实测保存成单通道灰度图会让
        ddddocr 的 4 位合法输出率明显下降。
        """
        if scale <= 1:
            return png_bytes
        try:
            from PIL import Image, ImageOps
            image = Image.open(io.BytesIO(png_bytes)).convert('L')
            image = ImageOps.autocontrast(image)
            image = image.resize((image.width * scale, image.height * scale),
                                 Image.LANCZOS)
            buffer = io.BytesIO()
            image.convert('RGB').save(buffer, format='PNG')
            return buffer.getvalue()
        except Exception as e:
            Logger.debug(f"验证码预处理变体生成失败（忽略）：{str(e)[:80]}")
            return png_bytes

    def _mask_image(self, png_bytes, opts, scale):
        """去掉彩色干扰线与彩点，只保留「暗且低饱和」的字符像素。

        真实站点的干扰线是彩色的（棕/蓝/绿等），字符是黑色：
        在 HSV 空间按「饱和度 < smax 且 亮度 < vmax」保留像素，
        并保底保留「很暗」的像素（避免字符笔画被整片抹掉），
        最后放大成 RGB 三通道图喂给 ddddocr。

        失败（如未安装 opencv）时返回 b''，由调用方回退到灰度变体。
        """
        try:
            import cv2
            import numpy as np
        except Exception:
            return b''
        try:
            smax = int(opts.get('smax', 70))
            vmax = int(opts.get('vmax', 175))
            dark = int(opts.get('dark', 140))
            src = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if src is None:
                return b''
            hsv = cv2.cvtColor(src, cv2.COLOR_BGR2HSV)
            saturation = hsv[:, :, 1]
            value = hsv[:, :, 2]
            keep = ((saturation < smax) & (value < vmax)) | (value < dark)
            binary = np.full(value.shape, 255, np.uint8)
            binary[keep] = 0
            image = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
            if scale > 1:
                image = cv2.resize(
                    image, (image.shape[1] * scale, image.shape[0] * scale),
                    interpolation=cv2.INTER_CUBIC)
            ok, encoded = cv2.imencode('.png', image)
            return encoded.tobytes() if ok else b''
        except Exception as e:
            Logger.debug(f"验证码颜色掩膜生成失败（忽略）：{str(e)[:80]}")
            return b''

    def _variant_images(self, png_bytes, spec):
        """按变体定义产出待识别图片。"""
        _name, _beta, _use_filter, mode, scale, opts = spec
        if mode == 'mask':
            masked = self._mask_image(png_bytes, opts, scale)
            if masked:
                return masked
            return self._scale_image(png_bytes, scale)
        if mode == 'gray':
            return self._scale_image(png_bytes, scale)
        return png_bytes

    # ------------------------------------------------------------------
    # 识别
    # ------------------------------------------------------------------
    def _classify(self, engine, image_bytes, use_filter):
        """调用 ddddocr，返回 (text, confidence)。"""
        kwargs = {'png_fix': True, 'probability': True}
        if use_filter:
            try:
                kwargs['color_filter_colors'] = list(self.filter_colors)
            except Exception:
                pass
        try:
            out = engine.classification(image_bytes, **kwargs)
        except TypeError:
            # 老版本没有 color_filter_colors / probability 参数：退化为无置信度模式
            out = engine.classification(image_bytes, png_fix=True)
            if not isinstance(out, dict):
                return str(out or '').strip(), 1.0
            out = dict(out)
            out.setdefault('confidence', 1.0)
        except Exception:
            raise
        if not isinstance(out, dict):
            return str(out or '').strip(), 1.0
        text = str(out.get('text') or '').strip()
        try:
            confidence = float(out.get('confidence') or 0.0)
        except Exception:
            confidence = 0.0
        return text, confidence

    def recognize(self, png_bytes, variant=None):
        """识别验证码图片。

        参数
          png_bytes  PNG 图片字节（Playwright 的 element.screenshot 结果）
          variant    None=跑全部变体并取最优；整数=只用第 variant 个变体
                     （重试时轮换变体，可覆盖不同的失效模式）

        返回 (文本, 置信度)；识别失败返回 ('', 置信度)，置信度恒 >= 0。

        校验规则（全部满足才返回文本）：
        - 长度恰好等于 self.length；
        - 每一位都在字符集内（正则整条匹配）；
        - 置信度 >= self.min_confidence。
        非法字符不允许「删除后凑长度」，整条作废。
        """
        if not png_bytes:
            return '', 0.0

        specs = self._variants_spec()
        if variant is not None:
            try:
                specs = [specs[int(variant) % len(specs)]]
            except Exception:
                specs = [specs[0]]

        results = []
        with self._lock:
            for spec in specs:
                name, beta, use_filter, _mode, _scale, _opts = spec
                engine = self._ensure_engine(beta)
                if engine is None:
                    return '', 0.0
                try:
                    # 每次识别前重设字符集：防止多模板 / 多设备之间互相污染
                    engine.set_ranges(self.charset)
                except Exception as e:
                    Logger.warning(f"设置验证码字符集失败：{str(e)[:80]}")
                image_bytes = self._variant_images(png_bytes, spec)
                try:
                    text, confidence = self._classify(engine, image_bytes,
                                                      use_filter)
                except Exception as e:
                    Logger.warning(f"验证码识别异常（变体 {name} 已忽略）："
                                   f"{str(e)[:100]}")
                    continue
                if self._pattern.match(text):
                    results.append((text, confidence, name))
                else:
                    Logger.info(f"验证码识别结果非法（变体 {name}，"
                                f"长度/字符集不符）：'{text}'，"
                                f"置信度={confidence:.2f}，本次作废")

        if not results:
            return '', 0.0

        if len(results) > 1:
            texts = {item[0] for item in results}
            if len(texts) > 1:
                Logger.info("验证码多变体识别结果不一致："
                            + " / ".join(f"'{t}'({c:.2f},{n})"
                                         for t, c, n in results)
                            + "，采用多数票")

        # 多数票：多个预处理变体给出同一结果时，说明该结果更可信。
        # 不能只看置信度 —— 实测存在「原图自信地认错、预处理变体反而正确」
        # 的情况（如区分大小写站点：原图 'tzk2' 置信度 0.98 却把 'K' 认成 'k'，
        # 而灰度/掩膜变体的 'TzK2' 才是对的）。
        groups = {}
        for text, conf, _name in results:
            entry = groups.setdefault(text, [0, 0.0])
            entry[0] += 1
            entry[1] = max(entry[1], conf)
        best_text = max(groups.items(),
                        key=lambda kv: (kv[1][0], kv[1][1]))[0]
        best_conf = max((conf for text, conf, _n in results if text == best_text),
                        default=0.0)

        if best_conf < self.min_confidence:
            Logger.info(f"验证码置信度不足（{best_conf:.2f} < "
                        f"{self.min_confidence:.2f}），本次作废")
            return '', best_conf

        return self._normalize(best_text), best_conf

    def _normalize(self, text):
        """按配置决定是否归一化大小写。

        默认（case_sensitive=True）**原样返回**：
        - 对「区分大小写」的站点：必须原样提交；
        - 对「不区分大小写」的站点：原样提交同样可以通过；
        而统一转大写只会在区分大小写的站点上把正确答案改错。
        """
        if self.case_sensitive or not text:
            return text
        return (text.lower() if self.normalize_to == 'lower' else text.upper())


# 模块级单例（登录引擎使用）
recognizer = CaptchaRecognizer(
    charset=CAPTCHA_OCR_CHARSET,
    length=CAPTCHA_OCR_LENGTH,
    case_sensitive=CAPTCHA_OCR_CASE_SENSITIVE,
    min_confidence=CAPTCHA_OCR_MIN_CONFIDENCE,
    preprocess=CAPTCHA_OCR_PREPROCESS,
    multi_pass=CAPTCHA_OCR_MULTI_PASS,
    normalize_to=CAPTCHA_OCR_NORMALIZE_TO,
    beta=CAPTCHA_OCR_BETA,
    color_filter=CAPTCHA_OCR_COLOR_FILTER,
)
