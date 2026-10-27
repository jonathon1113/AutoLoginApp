# -*- coding: utf-8 -*-
"""版本号递增 / 同步工具：一条命令完成「改版本号 → 重新生成全部打包文件」。

背景
----
本项目的版本号**唯一来源**是 ``appcore/config.py`` 的 ``APP_VERSION``：

- ``create_spec.py`` 依据它生成 ``批量登录工具V<版本>.spec`` 与 ``version_info.txt``；
- ``build.bat`` 依据它调用 PyInstaller，产物落在 ``dist\\批量登录工具V<版本>.exe``；
- ``get_version.py`` 供打包脚本取值。

也就是说**打包链上的所有地址本来就是自动派生的**，唯一需要人工改动的是
``APP_VERSION`` 这一个常量。本脚本把这一步也自动化。

用法
----
    python bump_version.py            # 补丁号 +1（5.0.9 -> 5.0.10）
    python bump_version.py 5.0.10     # 切换到指定版本号
    python bump_version.py --docs     # 同时同步文档中的「当前版本」描述
    python bump_version.py --show     # 只查看当前版本与派生地址，不做任何修改
    python bump_version.py --dry-run  # 试运行：只报告将要改动的内容，不写盘

原则
----
1. 只改 ``appcore/config.py`` 一个常量；spec 与 version_info 一律由
   ``create_spec.py`` 重新生成，杜绝手改多处导致版本漂移；
2. 递增**必须显式触发**（本脚本或 ``build.bat bump``），日常重复打包不改变版本号，
   符合 ``CHANGELOG.md``《版本管理约定》；
3. 文档只按**明确的槽位清单**同步「当前版本」描述，历史版本记录一律不动；
   每一处改动都逐行打印，便于人工复核；
4. 无法自动化的内容（新版本的变更说明 / 测试记录正文）在结尾明确列出。
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
CONFIG_FILE = ROOT / 'appcore' / 'config.py'
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')

# 输出统一走 UTF-8（与项目内其他脚本一致），避免管道重定向时按 GBK 解码乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ----------------------------------------------------------------------
# 文档中的「当前版本」槽位清单
#   (文件, 前缀, 后缀, 槽位类型[, 禁止前缀])
#   槽位类型：
#     current  -> 当前版本号         -> 新版本号
#     next     -> 下一次发布版本号   -> 新版本号的下一个补丁
#     next2    -> 再下一次发布版本号 -> 新版本号的第二个补丁
#     tuple    -> 当前版本元组       -> 新版本元组
#   只收录「描述当前版本」的槽位；历史版本记录、章节编号一律不收录。
#
#   定位方式为「前缀 + 版本号正则 + 后缀」而不是硬编码版本号文本，
#   这样升版、降版都能正确重算，文档与代码漂移时也能自愈。
#
#   安全阀：
#     1) 前缀必须足够精确，保证该槽位在文件中**只出现一次**；
#        命中多次时脚本跳过并报告，绝不批量改写（防止误改历史版本记录）；
#     2) 「禁止前缀」用于区分包含关系，例如 CHANGELOG 的
#        「下一次正式打包发布」与「再下一次正式打包发布」。
# ----------------------------------------------------------------------
DOC_SLOTS = [
    # ---- README.md（中文）----
    # 注意：截图文件名、交付报告名等**历史引用**不是「当前版本」描述，
    #       一律不收录，否则升版时会指向不存在的文件。
    ('README.md', 'dist/批量登录工具V', '.exe', 'current'),
    ('README.md', r'dist\批量登录工具V', '.exe', 'current'),
    ('README.md', '产品版本 = ', '', 'current'),
    ('README.md', '**版本**：', '　|　**作者**', 'current'),
    ('README.md', '下一次正式发布默认递增为 ', '', 'next'),
    # ---- README.en.md（英文，与中文版保持同步）----
    ('README.en.md', 'dist/批量登录工具V', '.exe', 'current'),
    ('README.en.md', r'dist\批量登录工具V', '.exe', 'current'),
    ('README.en.md', 'ProductVersion = ', '', 'current'),
    ('README.en.md', '**Version**: ', ' · **Author**', 'current'),
    ('README.en.md', 'Next release defaults to ', '', 'next'),
    # ---- 技术文档.md ----
    ('技术文档.md', 'pyinstaller "批量登录工具V', '.spec"', 'current'),
    ('技术文档.md', '--name "批量登录工具V', '"', 'current'),
    ('技术文档.md', '（当前 ', '）', 'current'),
    # ---- CHANGELOG.md ----
    ('CHANGELOG.md', '当前发布版本：**', '**', 'current'),
    ('CHANGELOG.md', 'APP_VERSION = "', '"', 'current'),
    ('CHANGELOG.md', 'APP_VERSION_INFO = (', ')', 'tuple'),
    ('CHANGELOG.md', '本次修复后的版本：**', '**', 'current'),
    ('CHANGELOG.md', '下一次正式打包发布：**', '**', 'next', '再'),
    ('CHANGELOG.md', '再下一次正式打包发布：**', '**', 'next2'),
]

VERSION_PATTERN = r'\d+\.\d+\.\d+'
TUPLE_PATTERN = r'\d+,\s*\d+,\s*\d+,\s*\d+'

# 需要人工补充、无法自动化的内容
MANUAL_TASKS = [
    'CHANGELOG.md：新增该版本的发布记录小节（写清本次改了什么）',
    'docs/变更说明.md：新增该版本的小节（§ 编号顺延）',
    'docs/兼容性清单.md：新增该版本的兼容性小节（§ 编号顺延）',
    'docs/测试报告.md：新增该版本的专项测试记录（写实际执行输出）',
    'docs/screenshots/：如需实拍截图，按 V<版本>_<场景>.png 命名归档',
]


def _read(path):
    """按字节读入并解码，返回字符串（保留原有换行符）。"""
    return path.read_bytes().decode('utf-8')


def _write(path, text):
    """按字节写回（保留原有换行符与无 BOM 状态）。"""
    path.write_bytes(text.encode('utf-8'))


def _parts(version):
    nums = [int(p) for p in version.split('.')]
    while len(nums) < 3:
        nums.append(0)
    return nums[:3]


def _current_revision():
    """读取 appcore/config.py 中 APP_VERSION_INFO 的第 4 位（修订号）。

    修订号由维护者手动维护（同一个 5.0.x 下的第几次构建），
    递增版本号时必须**原样保留**：
    否则「升版 -> 降版」无法逐字还原 config.py，
    且用户已发布的版本资源（EXE 文件属性）会被静默改写。
    """
    text = _read(CONFIG_FILE)
    match = re.search(r'APP_VERSION_INFO\s*=\s*\(\s*([^)]*)\)', text)
    if not match:
        return 0
    parts = [p.strip() for p in match.group(1).split(',') if p.strip()]
    if len(parts) >= 4:
        try:
            return int(parts[3])
        except ValueError:
            return 0
    return 0


def _tuple_text(version, revision=None):
    """版本元组文本：major, minor, patch, revision。

    revision 缺省时取 appcore/config.py 中现有的修订号（保持不变）。
    """
    rev = _current_revision() if revision is None else revision
    return ', '.join(str(n) for n in _parts(version)) + ', %d' % rev


def current_version():
    text = _read(CONFIG_FILE)
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise SystemExit('ERROR: 未在 appcore/config.py 中找到 APP_VERSION')
    return match.group(1)


def next_version(version):
    nums = _parts(version)
    nums[2] += 1
    return '.'.join(str(n) for n in nums)


def update_config(old, new):
    """把 appcore/config.py 的版本常量改成新版本（只动该常量与递增规则注释）。"""
    text = _read(CONFIG_FILE)

    text, n1 = re.subn(
        r'(APP_VERSION\s*=\s*)["\'][^"\']+["\']',
        lambda m: '%s"%s"' % (m.group(1), new), text, count=1)
    if n1 != 1:
        raise SystemExit('ERROR: appcore/config.py 中未找到唯一的 APP_VERSION 赋值')

    text, n2 = re.subn(
        r'(APP_VERSION_INFO\s*=\s*)\([^)]*\)',
        lambda m: '%s(%s)' % (m.group(1), _tuple_text(new)), text, count=1)
    if n2 != 1:
        raise SystemExit('ERROR: appcore/config.py 中未找到唯一的 APP_VERSION_INFO 赋值')

    text, _ = re.subn(
        r'# 递增规则：正式发布按补丁号递增（[^）]*）',
        # 注释以**新版本**为链头，与升降版方向无关，
        # 否则降版会把注释写成乱序链（5.0.11 -> 5.0.10 -> 5.0.11），
        # 导致「升版 -> 降版」无法逐字还原 config.py。
        lambda m: '# 递增规则：正式发布按补丁号递增（%s -> %s -> %s ...）'
                  % (new, next_version(new), next_version(next_version(new))), text, count=1)

    _write(CONFIG_FILE, text)


def regenerate_packaging():
    """重新生成 spec 与 version_info.txt（由 create_spec.py 派生，不手改）。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    # 必须在 config.py 写盘之后才导入，确保读到的是新版本号
    import create_spec
    spec_path = create_spec.write_spec(create_spec.build_spec_content())
    version_path = create_spec.write_version_info()
    return Path(spec_path).name, Path(version_path).name


def _slot_value(kind, new):
    """按槽位类型计算该槽位应该写入的版本文本。"""
    if kind == 'current':
        return new
    if kind == 'next':
        return next_version(new)
    if kind == 'next2':
        return next_version(next_version(new))
    if kind == 'tuple':
        return _tuple_text(new)
    raise ValueError('未知的槽位类型: %s' % kind)


def _slot_patterns():
    """编译所有槽位的正则，返回 (文件, 前缀, 后缀, 类型, pattern) 列表。"""
    items = []
    for slot in DOC_SLOTS:
        rel, prefix, suffix, kind = slot[0], slot[1], slot[2], slot[3]
        guard = slot[4] if len(slot) > 4 else None
        body = TUPLE_PATTERN if kind == 'tuple' else VERSION_PATTERN
        src = re.escape(prefix) + '(' + body + ')' + re.escape(suffix)
        if guard:
            src = '(?<!' + re.escape(guard) + ')' + src
        items.append((rel, prefix, suffix, kind, re.compile(src)))
    return items


def sync_docs(old, new, dry_run=False):
    """按槽位清单同步文档中的「当前版本」描述。

    返回 (改动列表, 未命中列表, 命中多次列表)。
    命中多次的槽位会被跳过并单独报告，避免误改历史版本记录。
    """
    changed, missing, ambiguous = [], [], []
    for rel, prefix, suffix, kind, pattern in _slot_patterns():
        path = ROOT / rel
        label = '%s<版本号>%s' % (prefix, suffix)
        if not path.exists():
            missing.append((rel, label))
            continue
        text = _read(path)
        matches = pattern.findall(text)
        if not matches:
            missing.append((rel, label))
            continue
        if len(matches) > 1:
            ambiguous.append((rel, label, len(matches)))
            continue
        new_value = _slot_value(kind, new)
        if not dry_run:
            _write(path, pattern.sub(
                lambda _m: prefix + new_value + suffix, text))
        changed.append((rel, 1,
                        '%s%s%s' % (prefix, matches[0], suffix),
                        '%s%s%s' % (prefix, new_value, suffix)))
    return changed, missing, ambiguous


def check_docs():
    """检查文档中的「当前版本」描述是否与代码一致（只读）。"""
    version = current_version()
    changed, missing, ambiguous = sync_docs(version, version, dry_run=True)
    print('文档「当前版本」描述一致性：')
    for rel, _cnt, old_s, new_s in changed:
        if old_s == new_s:
            print('  [一致]   %-16s %s' % (rel, old_s))
        else:
            print('  [不一致] %-16s 当前写作 %s，应为 %s' % (rel, old_s, new_s))
    for rel, label in missing:
        print('  [未找到] %-16s %s' % (rel, label))
    for rel, label, n in ambiguous:
        print('  [命中%d次] %-16s %s（需人工确认）' % (n, rel, label))
    return changed, missing, ambiguous


def show_current():
    """打印当前版本与全部派生地址（不修改任何文件）。"""
    version = current_version()
    print('当前版本号: %s' % version)
    print('版本元组  : (%s)' % _tuple_text(version))
    print('')
    print('由 APP_VERSION 自动派生的地址：')
    print('  appcore/config.py            APP_VERSION / APP_VERSION_INFO')
    print('  get_version.py               -> %s' % version)
    print('  批量登录工具V%s.spec' % version)
    print('  version_info.txt             文件版本 / 产品版本 = %s' % version)
    print('  build\\批量登录工具V%s\\' % version)
    print('  dist\\批量登录工具V%s.exe' % version)
    print('')
    print('打包命令：')
    print('  build.bat              使用当前版本号打包（默认，不改版本号）')
    print('  build.bat bump         补丁号 +1 后打包')
    print('  build.bat %-13s 切换到指定版本号后打包' % version)
    print('')
    check_docs()
    return version


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('-')]
    flags = {a for a in argv[1:] if a.startswith('-')}

    if '--show' in flags:
        show_current()
        return 0

    old = current_version()

    # 只同步文档，不改版本号（用于手工改过文档后自愈）
    if '--sync-docs' in flags:
        changed, missing, ambiguous = sync_docs(old, old, dry_run='--dry-run' in flags)
        print('文档同步（目标版本 %s）:' % old)
        for rel, count, old_s, new_s in changed:
            print('  %-16s x%d  %s  ->  %s' % (rel, count, old_s, new_s))
        if missing:
            print('  以下槽位未命中（需人工确认）：')
            for rel, label in missing:
                print('    - %s: %s' % (rel, label))
        if ambiguous:
            print('  以下槽位命中多次，已跳过以免误改历史记录（需人工确认）：')
            for rel, label, n in ambiguous:
                print('    - %s: %s（命中 %d 次）' % (rel, label, n))
        return 0

    if args:
        new = args[0]
        if not VERSION_RE.match(new):
            raise SystemExit('ERROR: 版本号格式非法（应为 x.y.z）：%s' % new)
    else:
        new = next_version(old)

    if new == old:
        print('版本号未变化：%s' % old)
        return 0

    dry_run = '--dry-run' in flags
    with_docs = '--docs' in flags

    print('版本号: %s -> %s%s' % (old, new, '（试运行，不写盘）' if dry_run else ''))
    print('')

    # 1) 唯一来源
    if not dry_run:
        update_config(old, new)
    print('[1/3] appcore/config.py')
    print('      APP_VERSION       -> "%s"' % new)
    print('      APP_VERSION_INFO  -> (%s)' % _tuple_text(new))

    # 2) 打包文件（重新生成）
    if dry_run:
        spec_name = '批量登录工具V%s.spec' % new
        version_name = 'version_info.txt'
    else:
        spec_name, version_name = regenerate_packaging()
    print('[2/3] 打包文件（由 create_spec.py 重新生成）')
    print('      %s' % spec_name)
    print('      %s（文件版本 / 产品版本 = %s）' % (version_name, new))

    # 3) 文档
    if with_docs:
        changed, missing, ambiguous = sync_docs(old, new, dry_run=dry_run)
        print('[3/3] 文档中的「当前版本」描述')
        for rel, count, old_s, new_s in changed:
            print('      %-16s x%d  %s  ->  %s' % (rel, count, old_s, new_s))
        if missing:
            print('      以下槽位未命中（文档可能已与代码漂移，请人工确认）：')
            for rel, label in missing:
                print('        - %s: %s' % (rel, label))
        if ambiguous:
            print('      以下槽位命中多次，已跳过以免误改历史记录，请人工确认：')
            for rel, label, n in ambiguous:
                print('        - %s: %s（命中 %d 次）' % (rel, label, n))
    else:
        print('[3/3] 文档同步：未启用（加 --docs 可同步「当前版本」描述）')

    print('')
    print('仍需人工补充的内容：')
    for task in MANUAL_TASKS:
        print('  - %s' % task)
    print('')
    print('下一步：执行 build.bat 打包（build.bat bump 可在打包前自动递增版本号）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
