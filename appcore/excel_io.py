"""Excel 设备表解析（纯数据层，不依赖 Qt）。

GUI 导入（appui/main_window.py）与命令行导入（import_excel.py）共用本模块，
避免两份解析逻辑各自演化、行为不一致。

职责边界（决定了本模块可以安全地放到后台线程里执行）：
- 本模块只负责「读文件 -> 解析 -> 校验 -> 返回设备列表」，
  **不写盘、不碰任何界面控件**；
- 写盘由 appcore.devices.save_devices 负责；
- 界面更新由调用方在主线程完成。

与历史行为保持一致的部分：
- 识别同一套表头别名（并补充了若干常见别名）；
- 设备名称为空时用「设备<行号>」补齐；
- 分组 / 模板为空时不写入该字段；
- 第一行是表头；
- 只读取**活动工作表**（与历史实现一致，不擅自扩展为多表导入）。

与历史实现修正的部分：
- 历史实现里所有列的默认索引都是 1，表头缺列时会**静默把第 1 列
  当成 URL**，产出完全错误的数据。现在缺必需列会直接报错并说明缺哪一列。
- 历史实现遇到第一个空 URL 就 `break`，表格中间有一行空 URL 时，
  后面所有设备都会被静默丢弃。现在空行被跳过并记录原因。
- 历史实现不做任何字段格式校验。现在 URL 格式不合法会被记录并跳过，
  并在导入结果中报告，不会静默写入垃圾数据。
"""

import os

# 表头别名 -> 字段名。匹配方式为「规范化后精确等于」，
# 与历史实现一致（避免把「密码确认」之类的列误认成密码列）。
COLUMN_ALIASES = {
    'name': ("设备名称", "名称", "设备名"),
    'url': ("登录地址(URL)", "URL", "地址", "登录地址", "链接地址"),
    'username': ("用户名", "用户", "帐号", "账号"),
    'password': ("密码",),
    'group': ("分组", "组", "设备分组"),
    'template': ("模板", "定位器", "模板名"),
}

# 必需列：缺了就无法确定设备
REQUIRED_COLUMNS = ('url',)

# 允许的登录地址协议
_ALLOWED_URL_PREFIXES = ('http://', 'https://')


class ExcelImportError(Exception):
    """导入过程中的可预期错误（文件不可读、表头不符等）。

    与程序缺陷区分开：这类错误直接把原因展示给用户。
    """


def _norm_header(value):
    """表头规范化：去空白、去 BOM、全角括号转半角"""
    text = str(value or '').strip().replace('﻿', '')
    return text.replace('（', '(').replace('）', ')')


def _text(value):
    """单元格取值转成去除首尾空白的文本（None -> 空串）"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _has_content(row):
    """整行是否完全没有内容"""
    for value in row:
        if value is not None and str(value).strip() != '':
            return True
    return False


def match_columns(header_row):
    """把表头行映射成列索引。

    返回 (mapping, missing)：
      mapping  {字段名: 列下标}
      missing  缺失的必需字段名列表
    """
    normalized = [_norm_header(cell) for cell in (header_row or [])]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for index, text in enumerate(normalized):
            if text and text in aliases:
                mapping[field] = index
                break
    missing = [field for field in REQUIRED_COLUMNS if field not in mapping]
    return mapping, missing


def parse_excel_devices(file_path):
    """解析 Excel 设备表，返回设备列表与逐行校验结果。

    返回 dict：
      devices     有效设备列表（字段与 devices.json 一致）
      errors      被跳过的行 [{row, name, reason}]
      duplicates  重复的登录地址 [{url, rows, names}]
      sheet       实际读取的工作表名
      total_rows  扫描到的数据行数（不含表头）
    """
    import openpyxl

    if not file_path or not os.path.exists(file_path):
        raise ExcelImportError(f"文件不存在：{file_path}")

    try:
        # data_only=True：读取公式的计算结果而不是公式本身
        workbook = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as exc:
        raise ExcelImportError(
            f"无法读取 Excel 文件（{os.path.basename(file_path)}）：{exc}")

    try:
        worksheet = workbook.active
        if worksheet is None:
            raise ExcelImportError("Excel 文件中没有可用的工作表")

        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            raise ExcelImportError("Excel 文件是空的（没有任何行）")

        mapping, missing = match_columns(rows[0])
        if missing:
            wanted = "、".join(COLUMN_ALIASES[field][0] for field in missing)
            found = "、".join(_text(cell) for cell in rows[0] if _text(cell))
            raise ExcelImportError(
                f"表头缺少必需列「{wanted}」"
                f"（实际读到的表头：{found or '空'}）。"
                f"请确认第 1 行是表头行，且包含"
                f"「{COLUMN_ALIASES['url'][0]}」列。")

        col_name = mapping.get('name')
        col_url = mapping['url']
        col_username = mapping.get('username')
        col_password = mapping.get('password')
        col_group = mapping.get('group')
        col_template = mapping.get('template')

        def cell(row, index):
            if index is None or index >= len(row):
                return None
            return row[index]

        devices = []
        errors = []
        seen = {}

        for row_number, row in enumerate(rows[1:], start=2):
            if not _has_content(row):
                # 表格尾部的空行很常见，直接跳过
                continue

            url = _text(cell(row, col_url))
            if not url:
                errors.append({
                    'row': row_number,
                    'name': _text(cell(row, col_name)),
                    'reason': '缺少登录地址',
                })
                continue
            if not url.lower().startswith(_ALLOWED_URL_PREFIXES):
                errors.append({
                    'row': row_number,
                    'name': _text(cell(row, col_name)),
                    'reason': f'登录地址格式不正确（{url}），应以 http:// 或 https:// 开头',
                })
                continue

            name = _text(cell(row, col_name)) or f"设备{row_number - 1}"
            device = {
                'name': name,
                'url': url,
                'username': _text(cell(row, col_username)),
                'password': _text(cell(row, col_password)),
            }
            group = _text(cell(row, col_group))
            if group:
                device['group'] = group
            template = _text(cell(row, col_template))
            if template:
                device['template'] = template
            devices.append(device)

            key = url.lower()
            if key in seen:
                seen[key].append((row_number, name))
            else:
                seen[key] = [(row_number, name)]

        duplicates = [
            {'url': url, 'rows': [row for row, _ in items],
             'names': [name for _, name in items]}
            for url, items in seen.items() if len(items) > 1
        ]

        return {
            'devices': devices,
            'errors': errors,
            'duplicates': duplicates,
            'sheet': getattr(worksheet, 'title', '') or '',
            'total_rows': max(0, len(rows) - 1),
        }
    finally:
        try:
            workbook.close()
        except Exception:
            pass


def import_devices_from_excel(file_path, progress=None):
    """解析并保存 Excel 设备表。

    只做数据处理（读文件、解析、校验、加密写盘），不触碰任何界面控件，
    因此可以安全地在后台线程中调用。progress 用于回报阶段进度。

    返回 dict（与 parse_excel_devices 的字段合并，另加 ok/count/saved）。
    """
    from .devices import save_devices

    def report(text):
        if progress is None:
            return
        try:
            progress(text)
        except Exception:
            pass

    report("正在读取 Excel 文件...")
    parsed = parse_excel_devices(file_path)

    count = len(parsed['devices'])
    if count == 0:
        detail = '；'.join(
            f"第 {item['row']} 行：{item['reason']}"
            for item in parsed['errors'][:5])
        if parsed['errors']:
            raise ExcelImportError(
                f"没有可导入的有效设备（{len(parsed['errors'])} 行未通过校验）。"
                f"{detail}")
        raise ExcelImportError("未找到设备数据，请检查 Excel 文件内容")

    report(f"正在校验并加密 {count} 台设备...")
    encrypted = save_devices(parsed['devices'])
    report(f"已写入 {len(encrypted)} 台设备")

    result = dict(parsed)
    result.update({
        'ok': True,
        'count': count,
        'saved': len(encrypted),
        'file_path': file_path,
    })
    return result
