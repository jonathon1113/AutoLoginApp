"""Excel 设备模板生成 / 导入工具（命令行版）。

与图形界面共用 appcore 中的加密与配置逻辑，命令行参数保持不变：
- python import_excel.py create   生成 Excel 模板
- python import_excel.py import   从 Excel 导入生成 devices.json
- python import_excel.py          交互式选择
"""

import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from appcore.config import CONFIG_FILE, EXCEL_TEMPLATE_FILE  # noqa: E402
from appcore.excel_io import ExcelImportError, import_devices_from_excel  # noqa: E402
from appcore.logging_utils import Logger                     # noqa: E402


def create_excel_template():
    """创建 Excel 模板"""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "设备列表"

    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 40
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 22
    ws.column_dimensions['E'].width = 15
    ws.column_dimensions['F'].width = 20

    header_font = Font(bold=True, color="FFFFFF", size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")

    headers = ["设备名称", "登录地址(URL)", "用户名", "密码", "分组", "模板"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    # 示例行一律使用**虚构的**占位数据（保留地址为 RFC 5737 / RFC 2606
    # 专用测试网段与域名），避免真实凭据随源码或模板文件泄露。
    # 用户拿到模板后直接覆盖这几行即可。
    example_data = [
        ["示例设备A", "http://192.0.2.10:8080/login", "demo_user", "demo_password", "A组-虚拟化", "default"],
        ["示例设备B", "https://example.com/login", "demo_admin", "demo_password", "A组-虚拟化", "proxmox"],
        ["示例设备C", "https://device.example.com/login", "demo_user", "demo_password", "B组-网关设备", "huawei"],
        ["示例设备D", "https://portal.example.org/login", "demo_user", "demo_password", "C组-云服务", "default"],
        ["示例设备E", "https://console.example.net/login", "demo_user", "demo_password", "D组-其他", "default"],
    ]
    for row_idx, row_data in enumerate(example_data, 2):
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    ws.freeze_panes = "A2"

    ws.cell(row=8, column=1, value="=== 使用说明 ===").font = Font(bold=True)
    ws.cell(row=9, column=1, value="1. 设备名称：用于标识设备，可自定义")
    ws.cell(row=10, column=1, value="2. 登录地址：完整的HTTP/HTTPS地址")
    ws.cell(row=11, column=1, value="3. 用户名/密码：登录凭据")
    ws.cell(row=12, column=1, value="4. 分组：设备所属分组，用于界面分类显示")
    ws.cell(row=13, column=1, value="5. 模板：登录页面定位器名称，留空或default使用默认定位器")
    ws.cell(row=14, column=1, value="6. 保存Excel后运行: python import_excel.py import")

    wb.save(EXCEL_TEMPLATE_FILE)
    print(f"[OK] Excel template created: {EXCEL_TEMPLATE_FILE}")
    return True


def excel_to_json(file_path=None):
    """从 Excel 导入数据生成 devices.json

    解析与校验逻辑与图形界面共用 appcore.excel_io（同一套表头识别、
    同样的逐行校验与错误报告），避免两份实现出现行为差异。
    """
    file_path = file_path or EXCEL_TEMPLATE_FILE
    if not os.path.exists(file_path):
        print(f"[X] Excel file not found: {file_path}")
        print("Run: python import_excel.py create   to create template")
        return False

    try:
        result = import_devices_from_excel(file_path)
    except ExcelImportError as e:
        print(f"[X] {e}")
        return False

    devices = result['devices']
    print("[OK] Sensitive data encrypted")

    groups = {}
    for d in devices:
        g = d.get('group', '默认')
        groups[g] = groups.get(g, 0) + 1

    for item in result.get('errors') or []:
        print(f"[!] 第 {item['row']} 行未通过校验：{item['reason']}")
    for item in result.get('duplicates') or []:
        rows = "、".join(str(r) for r in item['rows'])
        print(f"[!] 登录地址重复（已全部保留）：{item['url']}（第 {rows} 行）")

    print(f"[OK] devices.json generated: {len(devices)} devices -> {CONFIG_FILE}")
    print(f"     Groups: {', '.join([f'{k}({v})' for k, v in groups.items()])}")
    return True


def main():
    args = sys.argv[1:]
    if args and args[0] == "import":
        target = args[1] if len(args) > 1 else None
        ok = excel_to_json(target)
    elif args and args[0] == "create":
        ok = create_excel_template()
    else:
        print("批量登录工具 - Excel 配置")
        print("  create   生成 Excel 模板")
        print("  import   从 Excel 导入数据生成 devices.json")
        ok = create_excel_template()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
