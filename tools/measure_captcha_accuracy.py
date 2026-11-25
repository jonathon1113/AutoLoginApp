r"""验证码识别准确率实测工具。

用法：
    python tools\measure_captcha_accuracy.py <图片目录> [真值文件]

- 图片目录：内含 01.png / 1.jpg / *.png 等验证码截图；
- 真值文件：每行一个验证码（顺序与目录内文件名排序一致），
             省略时表示「不评估准确率，只打印识别结果」。

输出：样本数、top-1 准确率、平均置信度、低置信度被拒数量、逐字符准确率。

离线运行：只依赖本地的 ddddocr / onnxruntime / Pillow，不联网。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appcore.captcha_ocr import recognizer  # noqa: E402

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')


def collect_images(folder):
    """按文件名排序收集图片路径。"""
    if not os.path.isdir(folder):
        raise SystemExit(f"目录不存在: {folder}")
    names = [name for name in os.listdir(folder)
              if name.lower().endswith(IMAGE_EXTENSIONS)]
    names.sort()
    return [os.path.join(folder, name) for name in names]


def read_truth(path):
    """读取真值文件，返回去掉空行的列表。"""
    if not path:
        return []
    with open(path, 'r', encoding='utf-8-sig') as handle:
        return [line.strip() for line in handle if line.strip()]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder = argv[1]
    truth_path = argv[2] if len(argv) > 2 else ''
    truth = read_truth(truth_path)

    images = collect_images(folder)
    if not images:
        print("目录中没有找到图片")
        return 1
    if truth and len(truth) != len(images):
        print(f"真值条数({len(truth)})与图片数量({len(images)})不一致，"
              f"无法计算准确率")
        return 1

    if not recognizer.is_available():
        print("未安装 ddddocr，无法实测。请先安装："
              "pip install ddddocr onnxruntime Pillow")
        return 1

    hits = 0
    char_total = 0
    char_hits = 0
    confidences = []
    rejected = 0
    total = len(images)

    for index, path in enumerate(images):
        with open(path, 'rb') as handle:
            data = handle.read()
        text, confidence = recognizer.recognize(data)
        confidences.append(confidence)
        if not text:
            rejected += 1
        if truth:
            expected = truth[index]
            if text and text.upper() == expected.upper():
                hits += 1
            char_total += len(expected)
            char_hits += sum(1 for a, b in zip(text.upper(), expected.upper())
                             if a == b)
        print(f"{os.path.basename(path):24s} 识别={text or '(无效)':10s} "
              f"置信度={confidence:.2f}"
              + (f" 真值={truth[index]}" if truth else ""))

    print("")
    print(f"样本数: {total}")
    if truth:
        print(f"top-1 准确率: {hits / total * 100:.2f}%  ({hits}/{total})")
        if char_total:
            print(f"按字符准确率: {char_hits / char_total * 100:.2f}%")
    if confidences:
        average = sum(confidences) / len(confidences)
        print(f"平均置信度: {average:.3f}")
    print(f"低置信度被拒(返回空结果): {rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
