"""全量回归测试运行器。

依次运行 tests/ 下的全部测试文件，汇总每个文件的通过 / 失败数，
输出写入 tests/test_report.txt（UTF-8）并回显摘要。

用法：
    python tests/run_all.py

退出码：全部通过为 0，存在失败为 1。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, "tests")
REPORT = os.path.join(TESTS_DIR, "test_report.txt")

TEST_FILES = [
    "test_captcha_ocr.py",
    "test_captcha_flow.py",
    "test_captcha_real_ocr.py",
    "test_selector_lookup.py",
    "test_template_policy.py",
    "test_templates.py",
    "test_engine.py",
    "test_v508_features.py",
    "test_layout_speed.py",
    "test_real_login.py",
    "test_real_devices.py",
    "test_element_roles.py",
    "test_lookup_stats.py",
    "test_config_refresh.py",
    "test_excel_import.py",
    "test_gui.py",
    "test_ui_theme.py",
    "test_exit_safety.py",
    "test_bump_version.py",
]


def main():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"

    total_pass = 0
    total_fail = 0
    failed_files = []

    lines = []
    for name in TEST_FILES:
        path = os.path.join(TESTS_DIR, name)
        if not os.path.exists(path):
            lines.append(f"### {name}: MISSING")
            failed_files.append(name)
            continue
        proc = subprocess.run(
            [sys.executable, path],
            cwd=ROOT, env=env, capture_output=True,
        )
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        pass_n = out.count("[PASS]") + out.count("[OK]")
        fail_n = out.count("[FAIL]")
        # 统计文件自带的汇总行
        summary = ""
        for line in out.splitlines():
            if "测试结果" in line or "通过" in line and "失败" in line:
                summary = line.strip()
        if summary:
            m = re.search(r"(\d+)\s*通过.*?(\d+)\s*失败", summary)
            if m:
                pass_n = int(m.group(1))
                fail_n = int(m.group(2))
        total_pass += pass_n
        total_fail += fail_n
        status = "OK" if proc.returncode == 0 and fail_n == 0 else "FAILED"
        if status != "OK":
            failed_files.append(name)
            lines.append(f"### {name}: {status} rc={proc.returncode}")
            lines.append(out[-4000:])
            lines.append(err[-2000:])
        else:
            lines.append(f"### {name}: OK  pass={pass_n} fail={fail_n}  {summary}")
        print(f"{status:6s} {name:28s} pass={pass_n:4d} fail={fail_n:3d}  {summary}")

    lines.append("")
    lines.append(f"TOTAL: {total_pass} passed / {total_fail} failed")
    lines.append("FAILED FILES: " + (", ".join(failed_files) if failed_files else "none"))

    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print("")
    print(f"TOTAL: {total_pass} passed / {total_fail} failed")
    print("FAILED FILES: " + (", ".join(failed_files) if failed_files else "none"))
    return 1 if failed_files else 0


if __name__ == "__main__":
    sys.exit(main())
