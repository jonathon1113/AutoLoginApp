"""版本号自动化测试：bump_version.py 与 build.bat 的版本同步能力。

覆盖：
1. 唯一版本来源：appcore/config.py 的 APP_VERSION / APP_VERSION_INFO 自洽。
2. 派生文件：spec 文件名、version_info.txt 与 APP_VERSION 完全一致。
3. 文档槽位：README / 技术文档 / CHANGELOG 的「当前版本」描述唯一命中且与代码一致。
4. 往返幂等：升版再降版后，文档与 config.py 逐字还原。
5. 历史保护：往返过程中 5.0.0~5.0.8 的历史版本引用逐字不被篡改。
6. build.bat：支持 bump / 指定版本参数，且符合 UTF-8 无 BOM + CRLF 规范。

运行： python tests/test_bump_version.py
"""

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOCS = ["README.md", "README.en.md", "技术文档.md", "CHANGELOG.md",
        "docs/变更说明.md", "docs/兼容性清单.md", "docs/测试报告.md"]
HIST_RE = re.compile(r"5\.0\.[0-8]")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)


def digest(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_bump(*args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bump_version.py"), *args],
        cwd=str(ROOT), capture_output=True, env=env,
    )
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def hist_lines():
    """所有含历史版本号的行，作为「历史记录不可篡改」的基准。"""
    out = {}
    for rel in DOCS:
        path = ROOT / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HIST_RE.search(line):
                out[f"{rel}:{i}"] = line
    return out


def current_version():
    text = (ROOT / "appcore" / "config.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else ""


def doc_state():
    return {rel: digest(ROOT / rel) for rel in DOCS if (ROOT / rel).exists()}


# ==================== A 组：唯一版本来源与派生文件 ====================
def test_version_source():
    version = current_version()
    check("appcore/config.py 中存在 APP_VERSION", bool(version), version)

    text = (ROOT / "appcore" / "config.py").read_text(encoding="utf-8")
    match = re.search(r"APP_VERSION_INFO\s*=\s*\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", text)
    check("APP_VERSION_INFO 存在且可解析", match is not None)
    if match and version:
        parts = version.split(".")
        check("APP_VERSION_INFO 与 APP_VERSION 一致",
              [int(x) for x in parts] == [int(match.group(i)) for i in (1, 2, 3)],
              f"{version} vs {match.group(0)}")

    check("bump_version.py 存在于项目根目录", (ROOT / "bump_version.py").exists())
    check("get_version.py 读取到的版本与 APP_VERSION 一致",
          subprocess.run([sys.executable, str(ROOT / "get_version.py")],
                         cwd=str(ROOT), capture_output=True)
          .stdout.decode("utf-8", "replace").strip() == version)


def test_derived_files():
    version = current_version()
    spec = ROOT / f"批量登录工具V{version}.spec"
    check(f"spec 文件名与 APP_VERSION 一致（{spec.name}）", spec.exists())
    if spec.exists():
        text = spec.read_text(encoding="utf-8")
        check("spec 内 EXE 名称与 APP_VERSION 一致",
              f"name='批量登录工具V{version}'" in text)
        check("spec 引用 version_info.txt 作为版本资源",
              "version=" in text and "version_info.txt" in text)

    vi = ROOT / "version_info.txt"
    check("version_info.txt 存在", vi.exists())
    if vi.exists():
        text = vi.read_text(encoding="utf-8")
        check("version_info.txt 的 FileVersion 与 APP_VERSION 一致",
              f"StringStruct('FileVersion', '{version}')" in text)
        check("version_info.txt 的 ProductVersion 与 APP_VERSION 一致",
              f"StringStruct('ProductVersion', '{version}')" in text)
        check("version_info.txt 的 InternalName 与 APP_VERSION 一致",
              f"StringStruct('InternalName', '批量登录工具V{version}')" in text)
        check("version_info.txt 的 OriginalFilename 与 APP_VERSION 一致",
              f"StringStruct('OriginalFilename', '批量登录工具V{version}.exe')" in text)


# ==================== B 组：文档槽位唯一命中且一致 ====================
def test_doc_slots():
    code, out, err = run_bump("--show")
    check("bump_version.py --show 执行成功", code == 0, err.strip()[:120])
    check("--show 输出包含当前版本号", current_version() in out)
    check("--show 输出包含派生产物地址",
          f"dist\\批量登录工具V{current_version()}.exe" in out)

    check("--show 的文档一致性检查无「未找到」", "[未找到]" not in out,
          out[out.find("[未找到]"):][:120] if "[未找到]" in out else "")
    check("--show 的文档一致性检查无「命中多次」", "[命中" not in out,
          out[out.find("[命中"):][:120] if "[命中" in out else "")
    check("--show 的文档一致性检查全部为「一致」", "[不一致]" not in out,
          out[out.find("[不一致]"):][:120] if "[不一致]" in out else "")

    # 槽位必须在各文档中唯一命中，避免误改历史版本记录
    sys.path.insert(0, str(ROOT))
    import bump_version  # noqa: E402

    for rel, prefix, suffix, kind, pattern in bump_version._slot_patterns():
        path = ROOT / rel
        hits = pattern.findall(path.read_text(encoding="utf-8")) if path.exists() else []
        check(f"槽位唯一命中：{rel} {prefix}<版本号>{suffix}",
              len(hits) == 1, f"命中 {len(hits)} 次")


# ==================== C 组：往返幂等与历史保护 ====================
# 往返测试必须在**临时工作副本**中执行：
# 直接在项目目录里做升版/降版会改写用户的 README / CHANGELOG / config.py，
# 违反「测试不得污染真实用户数据」的约定（任务书 8.3）。
WORKSPACE_FILES = (
    "bump_version.py", "create_spec.py", "README.md", "README.en.md",
    "技术文档.md", "CHANGELOG.md", "build.bat",
)


def make_workspace():
    """把版本工具链与相关文档复制到临时目录，返回工作目录路径。"""
    work = pathlib.Path(tempfile.mkdtemp(prefix="bump_ws_"))
    for rel in WORKSPACE_FILES:
        src = ROOT / rel
        if src.exists():
            shutil.copy2(src, work / rel)
    appcore_src = ROOT / "appcore"
    if appcore_src.is_dir():
        shutil.copytree(appcore_src, work / "appcore",
                        ignore=shutil.ignore_patterns("__pycache__"))
    docs_src = ROOT / "docs"
    if docs_src.is_dir():
        shutil.copytree(docs_src, work / "docs",
                        ignore=shutil.ignore_patterns("__pycache__"))
    return work


def run_bump_in(work, *args):
    """在指定工作副本中执行 bump_version.py。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(work / "bump_version.py"), *args],
        cwd=str(work), capture_output=True, env=env,
    )
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def version_of(root):
    text = (root / "appcore" / "config.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else ""


def state_of(root):
    """工作副本中各文档的指纹 + 历史版本行 + config.py 内容。"""
    docs = {rel: digest(root / rel) for rel in DOCS if (root / rel).exists()}
    hist = {}
    for rel in DOCS:
        path = root / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HIST_RE.search(line):
                hist[f"{rel}:{i}"] = line
    config = (root / "appcore" / "config.py").read_text(encoding="utf-8")
    return docs, hist, config


def test_roundtrip():
    version = current_version()
    # 真实项目文件在测试前后必须逐字不变（测试不得污染用户数据）
    real_before = state_of(ROOT)

    work = make_workspace()
    try:
        base_docs, base_hist, base_config = state_of(work)

        code, out, err = run_bump_in(work, "--docs")
        check("升版执行成功", code == 0, err.strip()[:120])
        new_version = version_of(work)
        check("补丁号已递增", new_version != version, f"{version} -> {new_version}")
        check("递增后 spec 文件已生成",
              (work / f"批量登录工具V{new_version}.spec").exists())
        vi = (work / "version_info.txt").read_text(encoding="utf-8")
        check("递增后 version_info.txt 同步",
              f"StringStruct('FileVersion', '{new_version}')" in vi)

        code, out, err = run_bump_in(work, version, "--docs")
        check("降版执行成功", code == 0, err.strip()[:120])

        now_docs, now_hist, now_config = state_of(work)
        now_version = version_of(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    check("往返后版本号已还原", now_version == version, now_version)
    for rel, digest_value in base_docs.items():
        check(f"往返后逐字还原：{rel}", now_docs.get(rel) == digest_value)
    check("往返后 config.py 逐字还原", now_config == base_config)

    changed = [k for k, line in base_hist.items()
               if now_hist.get(k) != line]
    check("历史版本引用逐字未被篡改", not changed,
          f"{len(base_hist)} 条基准，{len(changed)} 条被改：{changed[:3]}")

    real_after = state_of(ROOT)
    check("测试未污染真实项目文件", real_after == real_before,
          "版本往返不应改动项目目录中的任何文件")


# ==================== D 组：build.bat 规范与参数支持 ====================
def test_build_bat():
    bat = ROOT / "build.bat"
    check("build.bat 存在", bat.exists())
    if not bat.exists():
        return
    data = bat.read_bytes()
    check("build.bat 无 BOM", not data.startswith(b"\xef\xbb\xbf"))
    text = data.decode("utf-8")
    crlf = data.count(b"\r\n")
    bare_lf = data.count(b"\n") - crlf
    check("build.bat 使用 CRLF 换行", crlf > 0 and bare_lf == 0,
          f"crlf={crlf} bare_lf={bare_lf}")
    check("build.bat 支持 bump 参数", "bump_version.py" in text and '"bump"' in text)
    check("build.bat 支持指定版本号参数", "bump_version.py %VERSION_ARG%" in text)
    check("build.bat 默认不改变版本号（无参数即不递增）",
          'set "VERSION_ARG=%~1"' in text)
    check("build.bat 仍从 get_version.py 取值",
          "get_version.py" in text and "APPVER" in text)


def main():
    test_version_source()
    test_derived_files()
    test_doc_slots()
    test_roundtrip()
    test_build_bat()

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("=" * 68)
    print(f"版本号自动化测试: {passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
