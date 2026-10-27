"""Excel 导入功能测试（数据层 + 后台任务 + 界面响应性）。

覆盖任务书要求的场景：
1. 约 100 台设备的正常 XLSX 导入；
2. 多工作表导入（当前实现只读取**活动工作表**，这里记录既有行为）；
3. 空文件、没有有效设备数据的文件；
4. 字段缺失、格式错误的数据；
5. 存在重复设备的数据；
6. 导入过程中窗口是否仍能正常响应（事件循环最大延迟实测）；
7. 导入完成后设备数量、分组、字段内容与配置持久化是否正确；
8. 导入失败时能否恢复界面状态并显示具体错误。

所有测试都使用**独立临时配置**（临时目录下的 devices.json），
不会读写用户真实的设备配置文件。

运行： python tests/test_excel_import.py
"""

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from PyQt6.QtCore import QEventLoop, QThreadPool, QTimer   # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog   # noqa: E402

from appcore import devices as device_store              # noqa: E402
from appcore.excel_io import (                            # noqa: E402
    ExcelImportError,
    import_devices_from_excel,
    parse_excel_devices,
)

RESULTS = []

# 界面「未响应」的判定阈值：Windows 在主线程无响应约 5 秒后才会提示，
# 这里取更严格的 300ms —— 只要事件循环的最大延迟在阈值内，
# 说明导入期间界面随时可以响应用户操作。
UI_LAG_LIMIT_MS = 300


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


# ============ 测试数据构造 ============
# 标准列顺序：rows 里的每一列与这里一一对应
STANDARD_ORDER = ["设备名称", "登录地址(URL)", "用户名", "密码", "分组", "模板"]


def make_xlsx(path, rows, sheet_title="设备列表", extra_sheets=(),
              headers=None, omit_url_column=False):
    """生成测试用 xlsx。

    rows 为标准 6 列（见 STANDARD_ORDER）；
    headers 为 None 时使用标准 6 列表头；
    omit_url_column=True 时表头里删掉「登录地址(URL)」列（模拟表头缺列）。
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    head = headers if headers is not None else list(STANDARD_ORDER)
    if omit_url_column:
        head = [h for h in head if h != "登录地址(URL)"]

    def fill(sheet, data_rows):
        for index, text in enumerate(head, 1):
            sheet.cell(row=1, column=index, value=text)
        for offset, row in enumerate(data_rows):
            for index, text in enumerate(head, 1):
                if text in STANDARD_ORDER:
                    sheet.cell(row=offset + 2, column=index,
                               value=row[STANDARD_ORDER.index(text)])
                else:
                    sheet.cell(row=offset + 2, column=index, value=None)

    fill(ws, rows)
    for title, data in extra_sheets:
        fill(wb.create_sheet(title), data)

    wb.save(path)
    return path


def standard_rows(count, prefix="设备"):
    """标准设备行：名称 / URL / 用户名 / 密码 / 分组 / 模板"""
    rows = []
    for index in range(1, count + 1):
        rows.append([
            f"{prefix}{index}",
            f"http://198.51.100.{index}:8080/login",
            f"user{index}",
            f"Pwd@{index}xx",
            f"分组{index % 5}",
            "default" if index % 3 == 0 else "",
        ])
    return rows


# ============ 数据层测试 ============
def test_parse_layers(tmpdir):
    print("\n---- 数据层（appcore.excel_io）----", flush=True)

    # ---- 1. 100 台设备 ----
    path = make_xlsx(os.path.join(tmpdir, "d100.xlsx"), standard_rows(100))
    started = time.monotonic()
    parsed = parse_excel_devices(path)
    parse_ms = int((time.monotonic() - started) * 1000)
    devices = parsed['devices']
    check("1 解析 100 台设备", len(devices) == 100,
          f"设备数={len(devices)} 解析耗时={parse_ms}ms")
    check("1 无校验错误", not parsed['errors'],
          f"错误数={len(parsed['errors'])}")
    first = devices[0]
    check("1 字段映射正确",
          first['name'] == "设备1"
          and first['url'] == "http://198.51.100.1:8080/login"
          and first['username'] == "user1"
          and first['password'] == "Pwd@1xx"
          and first['group'] == "分组1",
          json.dumps(first, ensure_ascii=False))
    check("1 模板列按需写入",
          devices[2].get('template') == 'default'
          and 'template' not in devices[0],
          f"设备3={devices[2].get('template')} 设备1={devices[0].get('template')}")
    groups = {}
    for device in devices:
        groups[device.get('group', '默认')] = groups.get(device.get('group', '默认'), 0) + 1
    check("1 分组统计正确", len(groups) == 5 and sum(groups.values()) == 100,
          f"分组数={len(groups)} 合计={sum(groups.values())}")

    # ---- 2. 多工作表：只读取活动工作表（既有行为）----
    path = make_xlsx(os.path.join(tmpdir, "multi.xlsx"), standard_rows(3),
                     extra_sheets=[("其它表", standard_rows(50, "其它"))])
    parsed = parse_excel_devices(path)
    check("2 多工作表只导入活动工作表", len(parsed['devices']) == 3,
          f"设备数={len(parsed['devices'])} 工作表={parsed['sheet']}")

    # ---- 3. 空文件 / 无有效数据 ----
    empty = os.path.join(tmpdir, "empty.xlsx")
    with open(empty, "wb") as handle:
        handle.write(b"")
    try:
        parse_excel_devices(empty)
        check("3 空文件报错", False, "未抛出异常")
    except ExcelImportError as exc:
        check("3 空文件报错且原因明确", "无法读取" in str(exc) or "空" in str(exc),
              str(exc))

    header_only = make_xlsx(os.path.join(tmpdir, "header_only.xlsx"), [])
    parsed = parse_excel_devices(header_only)
    check("3 只有表头时没有设备", not parsed['devices'],
          f"设备数={len(parsed['devices'])}")
    try:
        import_devices_from_excel(header_only)
        check("3 只有表头时导入报错", False, "未抛出异常")
    except ExcelImportError as exc:
        check("3 只有表头时导入报错且原因明确", "未找到设备数据" in str(exc),
              str(exc))

    # ---- 4. 表头缺列 ----
    path = make_xlsx(os.path.join(tmpdir, "nourl.xlsx"), standard_rows(3),
                     omit_url_column=True)
    try:
        parse_excel_devices(path)
        check("4 缺 URL 列时明确报错", False, "未抛出异常")
    except ExcelImportError as exc:
        check("4 缺 URL 列时明确报错", "缺少必需列" in str(exc), str(exc))

    # ---- 5. 无效数据 ----
    bad_rows = [
        ["设备A", "http://192.0.2.21/login", "u", "p", "组1", ""],
        ["设备B", "不是网址", "u", "p", "组1", ""],
        ["设备C", "", "u", "p", "组1", ""],
        ["设备D", "https://192.0.2.24/login", "u", "p", "组1", ""],
    ]
    path = make_xlsx(os.path.join(tmpdir, "bad.xlsx"), bad_rows)
    parsed = parse_excel_devices(path)
    check("5 无效行被跳过且有效行保留", len(parsed['devices']) == 2,
          f"有效={len(parsed['devices'])} 错误={len(parsed['errors'])}")
    check("5 逐行给出具体原因",
          len(parsed['errors']) == 2
          and '格式不正确' in parsed['errors'][0]['reason']
          and '缺少登录地址' in parsed['errors'][1]['reason'],
          " / ".join(f"第{e['row']}行:{e['reason']}" for e in parsed['errors']))

    # ---- 6. 中间空行不再丢弃后续设备 ----
    gap_rows = [
        ["设备A", "http://192.0.2.21/login", "u", "p", "组1", ""],
        ["", "", "", "", "", ""],
        ["设备C", "http://192.0.2.23/login", "u", "p", "组1", ""],
    ]
    path = make_xlsx(os.path.join(tmpdir, "gap.xlsx"), gap_rows)
    parsed = parse_excel_devices(path)
    check("6 中间空行不丢弃后续设备", len(parsed['devices']) == 2,
          f"设备数={len(parsed['devices'])}（历史实现在此会截断为 1 台）")

    # ---- 7. 重复设备 ----
    dup_rows = [
        ["设备A", "http://192.0.2.21/login", "u", "p", "组1", ""],
        ["设备A2", "http://192.0.2.21/login", "u", "p", "组1", ""],
        ["设备B", "http://192.0.2.22/login", "u", "p", "组1", ""],
    ]
    path = make_xlsx(os.path.join(tmpdir, "dup.xlsx"), dup_rows)
    parsed = parse_excel_devices(path)
    check("7 重复地址被报告", len(parsed['duplicates']) == 1,
          f"重复数={len(parsed['duplicates'])}")
    check("7 重复设备按原规则全部保留", len(parsed['devices']) == 3,
          f"设备数={len(parsed['devices'])}（历史规则不去重）")

    # ---- 8. 名称缺失自动命名 ----
    path = make_xlsx(os.path.join(tmpdir, "noname.xlsx"),
                     [["", "http://192.0.2.21/login", "u", "p", "组1", ""]])
    parsed = parse_excel_devices(path)
    check("8 名称缺失自动补齐", parsed['devices'][0]['name'] == "设备1",
          parsed['devices'][0]['name'])

    # ---- 9. 持久化 ----
    config_path = os.path.join(tmpdir, "devices.json")
    device_store.CONFIG_FILE = config_path
    path = make_xlsx(os.path.join(tmpdir, "persist.xlsx"), standard_rows(6))
    result = import_devices_from_excel(path)
    check("9 导入返回设备数正确", result['count'] == 6,
          f"count={result['count']}")
    check("9 配置文件已生成", os.path.exists(config_path), config_path)
    with open(config_path, encoding="utf-8") as handle:
        stored = json.load(handle)
    check("9 落盘设备数正确", len(stored) == 6, f"条数={len(stored)}")
    check("9 凭据以密文存储",
          all(str(item['username']).startswith('SALT:')
              and str(item['password']).startswith('SALT:')
              for item in stored),
          f"样例={str(stored[0]['username'])[:12]}")
    from encrypt import simple_decrypt
    decrypted = [simple_decrypt(item['username']) for item in stored]
    check("9 密文可解密回原文",
          decrypted[0] == "user1" and decrypted[5] == "user6",
          f"首尾={decrypted[0]}/{decrypted[5]}")
    groups = device_store.load_devices()
    check("9 重新读取后分组正确", len(groups) == 5 and sum(
        len(v) for v in groups.values()) == 6,
          f"分组={sorted(groups)}")
    return config_path


# ============ 后台任务与界面响应性 ============
def test_background_import(app, tmpdir, config_path):
    print("\n---- 后台任务与界面响应性 ----", flush=True)
    from appcore.tasks import ImportExcelTask

    device_store.CONFIG_FILE = config_path
    path = make_xlsx(os.path.join(tmpdir, "bg100.xlsx"), standard_rows(100))

    # 事件循环延迟监控：定时器每 5ms 触发一次，记录实际间隔
    lags = []
    state = {'last': time.monotonic(), 'done': False, 'result': None,
             'error': None}

    def on_tick():
        now = time.monotonic()
        lags.append((now - state['last']) * 1000)
        state['last'] = now

    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(on_tick)
    timer.start()

    started = time.monotonic()
    task = ImportExcelTask(path)
    task.signals.finished.connect(
        lambda result: (state.update(result=result), state.update(done=True)))
    task.signals.error.connect(
        lambda message: (state.update(error=message), state.update(done=True)))
    pool = QThreadPool()
    pool.start(task)

    # 主线程持续处理事件（模拟真实界面的事件循环）
    deadline = time.time() + 120
    while not state['done'] and time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.005)
    elapsed = time.monotonic() - started
    timer.stop()
    pool.waitForDone(5000)

    check("10 后台导入 100 台完成", state['done'] and state['error'] is None,
          f"耗时={int(elapsed * 1000)}ms 错误={state['error']}")
    check("10 导入结果设备数正确",
          (state['result'] or {}).get('count') == 100,
          f"count={(state['result'] or {}).get('count')}")
    max_lag = max(lags) if lags else 0
    check("11 导入期间界面事件循环未被阻塞",
          max_lag < UI_LAG_LIMIT_MS,
          f"最大延迟={int(max_lag)}ms（阈值 {UI_LAG_LIMIT_MS}ms，"
          f"采样 {len(lags)} 次）")
    check("11 导入期间定时器持续触发", len(lags) > 50,
          f"触发次数={len(lags)}")
    print(f"     导入总耗时={int(elapsed * 1000)}ms，"
          f"事件循环最大延迟={int(max_lag)}ms", flush=True)
    return elapsed


def test_sync_baseline(tmpdir, config_path):
    print("\n---- 主线程同步对照（量化修复前的问题）----", flush=True)
    device_store.CONFIG_FILE = config_path
    path = make_xlsx(os.path.join(tmpdir, "sync100.xlsx"), standard_rows(100))
    started = time.monotonic()
    import_devices_from_excel(path)
    elapsed = time.monotonic() - started
    check("12 主线程同步导入耗时（对照）", True,
          f"耗时={int(elapsed * 1000)}ms（这段时间内主线程无法处理任何界面事件）")
    return elapsed


# ============ 图形界面集成 ============
def test_gui_import(app, tmpdir, config_path):
    print("\n---- 图形界面集成 ----", flush=True)
    from appcore import tasks as app_tasks
    from appui.main_window import LoginWindow

    device_store.CONFIG_FILE = config_path
    app_tasks.load_devices = lambda: {}

    window = LoginWindow()
    window.show()
    app.processEvents()

    path = make_xlsx(os.path.join(tmpdir, "gui100.xlsx"), standard_rows(100))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))

    started = time.monotonic()
    window.on_import_excel()
    check("13 导入走后台线程（立即返回）",
          time.monotonic() - started < 1.0,
          f"调用耗时={int((time.monotonic() - started) * 1000)}ms")
    check("13 导入期间界面仍可交互", window.isEnabled(),
          "窗口处于可用状态")

    deadline = time.time() + 120
    while window._excel_importing and time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.01)
    app.processEvents()

    check("14 导入完成后设备列表刷新", window.device_list.count() == 100,
          f"列表条目={window.device_list.count()}")
    check("14 状态提示显示导入结果", "已导入" in window.stat_label.text(),
          window.stat_label.text())
    check("14 进度条已隐藏", not window.progress_bar.isVisible(),
          f"progress_bar 可见={window.progress_bar.isVisible()}")
    check("14 进度条范围已恢复", window.progress_bar.maximum() == 100,
          f"maximum={window.progress_bar.maximum()}")
    groups = device_store.get_groups()
    check("14 分组已生效", len(groups) == 5 and sum(
        len(v) for v in groups.values()) == 100,
          f"分组数={len(groups)}")

    # ---- 15. 导入失败：UI 恢复 + 具体原因 ----
    bad_path = os.path.join(tmpdir, "broken.xlsx")
    with open(bad_path, "wb") as handle:
        handle.write(b"not a real xlsx")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (bad_path, ""))
    window.on_import_excel()
    deadline = time.time() + 60
    while window._excel_importing and time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.01)
    app.processEvents()
    check("15 导入失败后状态恢复", not window._excel_importing
          and not window.progress_bar.isVisible(),
          f"importing={window._excel_importing} "
          f"progress可见={window.progress_bar.isVisible()}")
    check("15 导入失败显示具体原因", "失败" in window.stat_label.text(),
          window.stat_label.text())
    check("15 失败后原有设备未被清空", window.device_list.count() == 100,
          f"列表条目={window.device_list.count()}")

    # ---- 16. 重复触发导入被拒绝 ----
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))
    window._excel_importing = True
    window.on_import_excel()
    check("16 导入进行中时拒绝重复触发", window._excel_importing is True,
          "仍处于导入中状态")
    window._excel_importing = False

    window.on_exit()
    for _ in range(40):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.05)
    try:
        window.deleteLater()
        app.processEvents()
    except RuntimeError:
        pass


def main():
    app = QApplication(sys.argv)
    tmpdir = tempfile.mkdtemp(prefix="excel_import_test_")
    try:
        config_path = test_parse_layers(tmpdir)
        test_background_import(app, tmpdir, config_path)
        test_sync_baseline(tmpdir, config_path)
        test_gui_import(app, tmpdir, config_path)
    finally:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
    return 0


def report():
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"Excel 导入测试: {passed} 通过 / {failed} 失败")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTS.append(("测试执行异常", False, "见堆栈"))
    sys.exit(report())
