"""校验打包产物 PYZ 中是否确实包含本轮修复的关键代码。

用法（项目根目录执行）：
    python verify_pyz.py

EXE 名称取自 appcore/config.py 的 APP_VERSION，不需要手工改路径。

匹配方式采用「子串包含」：源码里的相邻字符串字面量会在编译期被合并成
一个常量（例如 "xxx" "（线程名=%s）" -> "xxx（线程名=%s）"），
精确等值匹配会漏判，必须按子串判断。
"""
import os
import re
import types

from PyInstaller.archive.readers import CArchiveReader

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "appcore", "config.py")


def current_version():
    text = open(CONFIG_FILE, encoding="utf-8").read()
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise SystemExit("ERROR: 未在 appcore/config.py 中找到 APP_VERSION")
    return match.group(1)


def collect_strings(code, out):
    """递归收集 code 对象里出现的全部字符串常量（含嵌套函数体）。"""
    for key in code.co_names:
        out.add(key)
    for key in code.co_varnames:
        out.add(key)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            collect_strings(const, out)
        elif isinstance(const, str):
            out.add(const)
        elif isinstance(const, (tuple, frozenset)):
            for item in const:
                if isinstance(item, str):
                    out.add(item)
    return out


def has(texts, needle):
    """子串包含判断（覆盖编译期合并后的常量）。"""
    return any(needle in text for text in texts)


CHECKS = [
    ("appcore.templates", (
        "_collect_role_risks", "strict_roles", "check_roles",
        "append_selectors_to_default", "replace_default_template",
        "merge_template_into_default", "write_default_template",
        "_repair_preset_template", "static_role_risk",
        "存在与字段角色冲突的选择器", "默认模板角色映射提示")),
    ("appcore.browser", (
        "_is_detached", "_fill_with_timeout", "wait_visible_all",
        "quick_check_locator", "element_detached")),
    ("appcore.element_roles", (
        "static_role_risk", "inspect_role", "ambiguous_match",
        "looks_like_password", "role_mismatch")),
    ("appui.main_window", (
        "on_append_to_default_template", "on_merge_into_default_template",
        "on_replace_default_template", "on_refresh")),
    ("appcore.automation", (
        "自动化线程未在 10s 内退出", "保留线程引用以避免退出期强杀")),
]


def main():
    version = current_version()
    exe = os.path.join(ROOT, "dist", "批量登录工具V%s.exe" % version)
    if not os.path.exists(exe):
        raise SystemExit("ERROR: 找不到产物 %s（请先打包）" % exe)

    print("产物:", exe, os.path.getsize(exe), "字节")
    reader = CArchiveReader(exe)
    pyz = reader.open_embedded_archive("PYZ.pyz")

    missing = []
    for module, needles in CHECKS:
        texts = collect_strings(pyz.extract(module), set())
        for needle in needles:
            ok = has(texts, needle)
            if not ok:
                missing.append((module, needle))
            print("  %-24s %-42s %s" % (module, needle, ok))

    print()
    if missing:
        print("缺失项:", missing)
        return 1
    print("全部关键代码均已包含在产物中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())