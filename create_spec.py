# -*- coding: utf-8 -*-
"""生成 PyInstaller spec 文件与 Windows 版本资源文件（Playwright 版本）。

与 build.bat 中的命令行参数保持一致，两种构建方式等价：
    pyinstaller -F main.py ...
    pyinstaller 批量登录工具V<版本>.spec

版本号统一来源于 appcore/config.py 的 APP_VERSION，
因此本脚本生成的 EXE 名称、spec 文件名、EXE 文件版本资源始终一致。

注意：必须先执行
    set PLAYWRIGHT_BROWSERS_PATH=0
    playwright install chromium
浏览器才会安装到 site-packages\\playwright\\driver\\package\\.local-browsers，
并被 collect_all('playwright') 一并收集进 EXE。

体积优化分四类独立开关，便于逐项验证与回退（详见 OPTIMIZE_* 说明）：
    OPTIMIZE_DEPS        A: 排除运行时用不到的重依赖（numpy/scipy/PIL/lxml 等）
    OPTIMIZE_PLAYWRIGHT  B: 剔除有头模式下不会被调用的 headless_shell / ffmpeg
    OPTIMIZE_QT          C: 精简 Qt 翻译文件与未使用的 PyQt6 模块
    OPTIMIZE_CHROMIUM    D: 精简 Chromium 非中英文语言包、运行时不会加载的辅助
                           EXE、Playwright 驱动的 TypeScript 声明与不可达的
                           Qt 模块 DLL
所有优化均不改变运行逻辑：被排除的模块在源码中没有任何 import 路径。

模块级 API：
    build_spec_content(entry, exe_name, console=False)  生成 spec 文件内容
    write_spec(...) / write_version_info(...)           落盘
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from appcore.config import APP_NAME, APP_VERSION, APP_VERSION_INFO  # noqa: E402

script_dir = Path(__file__).parent.resolve()
exe_name = f"批量登录工具V{APP_VERSION}"
spec_file = script_dir / f'{exe_name}.spec'
version_file = script_dir / 'version_info.txt'

# ====================================================================
# 体积优化配置
# ====================================================================

# ---- A: 排除运行时用不到的重依赖 ----
# 说明：
#   qfluentwidgets 已在 V5.0.7 中整体移除（界面改用原生 PyQt6 + QSS），
#   其顶层依赖 acrylic_label -> common.image_utils 会连带引入 numpy/scipy/Pillow，
#   图表组件会引入 pandas/matplotlib；这些在当前程序中没有任何调用路径。
#   lxml 对 openpyxl 是可选依赖（缺失时自动回退 xml.etree），Excel 读写不受影响。
#   其余为项目从未使用的其它 Qt 绑定与桌面绑定。
EXCLUDES_DEPS = [
    'qfluentwidgets',
    'numpy', 'scipy', 'PIL', 'pandas', 'matplotlib',
    'lxml',
    'PySide2', 'PySide6', 'shiboken2', 'shiboken6',
    'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
    'tkinter',
]

# ---- C: 未使用的 PyQt6 模块（项目仅用到 Core / Gui / Widgets）----
EXCLUDES_QT = [
    'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DCore', 'PyQt6.Qt3DExtras', 'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic', 'PyQt6.Qt3DRender', 'PyQt6.QtBluetooth', 'PyQt6.QtCharts',
    'PyQt6.QtDataVisualization', 'PyQt6.QtDBus', 'PyQt6.QtDesigner', 'PyQt6.QtGraphs',
    'PyQt6.QtGraphsWidgets', 'PyQt6.QtHelp', 'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets', 'PyQt6.QtNetworkAuth', 'PyQt6.QtNfc',
    'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
    'PyQt6.QtPositioning', 'PyQt6.QtPrintSupport', 'PyQt6.QtQml', 'PyQt6.QtQuick',
    'PyQt6.QtQuick3D', 'PyQt6.QtQuickWidgets', 'PyQt6.QtRemoteObjects',
    'PyQt6.QtScxml', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort', 'PyQt6.QtSpatialAudio',
    'PyQt6.QtSql', 'PyQt6.QtStateMachine', 'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest', 'PyQt6.QtTextToSpeech', 'PyQt6.QtUiTools', 'PyQt6.QtVirtualKeyboard',
    'PyQt6.QtWebChannel', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineQuick',
    'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebSockets', 'PyQt6.QtXml',
]

# ---- C: 保留的 Qt 翻译文件（其余语言运行时不会被加载）----
KEEP_TRANSLATIONS = ('qtbase_zh_CN.qm', 'qtbase_en.qm', 'qtbase.qm')

# ---- B: Playwright 中有头模式不会被调用的浏览器组件 ----
# appcore/browser.py 固定使用 headless=False（可见窗口），
# 因此 chromium_headless_shell（无头壳）不会被加载；
# 程序未启用 record_video，因此 ffmpeg 也不会被调用。
UNUSED_BROWSER_PATTERNS = ('chromium_headless_shell', 'ffmpeg')

# ---- D: Chromium 内置资源与 Playwright 驱动冗余文件精简 ----
# 依据：对打包产物做依赖分析（PE 静态导入表 + Chromium 运行时加载路径）后，
# 确认下列文件在本程序的有头自动化场景下「运行时不会被加载」：
#
# 1) locales\*.pak（220 个 / 约 43MB）
#    Chromium 只加载与 UI 语言匹配的一个 .pak，缺失时自动回退到 en-US。
#    本程序为简体中文界面，保留 zh-CN / en-US / en-GB 即可。
# 2) 下列辅助 EXE（约 23MB）均不属于浏览器运行时加载路径：
#    setup.exe                    Chromium 安装器（仅安装时使用）
#    chrome_pwa_launcher.exe      PWA 快捷方式启动器（仅创建快捷方式时使用）
#    notification_helper.exe      Windows 通知助手（本程序不用通知）
#    elevated_tracing_service.exe ETW 跟踪服务（本程序不开跟踪）
#    elevation_service.exe        提权辅助（仅 Chrome 自身代理配置流程使用）
#    chrome_proxy.exe             代理辅助（Windows 版走系统代理，不加载）
# 3) Chromium 数据目录 MEIPreload / IwaKeyDistribution
#    分别为 IE 迁移预载与 Windows IWA 密钥分发，本程序不使用。
# 4) playwright\driver\package\types\  TypeScript 类型声明，运行时从不加载。
#
# 明确不动的部分（属于「必需」或存在动态加载风险，一律保留）：
#    chrome.dll / chrome.exe / resources.pak / icudtl.dat / D3DCompiler_47.dll
#    dxcompiler.dll / vk_swiftshader.dll / hyphen-data / lib\*.js / node.exe
#    Qt6 的 opengl32sw.dll 等全部运行库与插件
CHROMIUM_KEEP_LOCALES = ('zh-cn.pak', 'en-us.pak', 'en-gb.pak')
CHROMIUM_DROP_FILES = (
    'setup.exe',
    'chrome_pwa_launcher.exe',
    'notification_helper.exe',
    'elevated_tracing_service.exe',
    'elevation_service.exe',
    'chrome_proxy.exe',
)
CHROMIUM_DROP_DIRS = ('/meipload/', '/iwakeydistribution/')
CHROMIUM_DROP_PATHS = ('/driver/package/types/',)
# Qt6 模块 DLL：PyQt6.QtPdf 已在 EXCLUDES_QT 中排除，包内不存在 QtPdf.pyd，
# 且依赖分析确认 Qt6Core/Gui/Widgets/Network/Svg 均未静态导入 Qt6Pdf.dll，
# 即该 DLL 在本程序中不可达。
QT_DROP_DLLS = ('qt6pdf.dll',)


def _flag(name, default=True):
    """读取环境变量开关：PYI_OPT_DEPS / PYI_OPT_PLAYWRIGHT / PYI_OPT_QT / PYI_OPT_CHROMIUM"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ('0', 'false', 'no', 'off')


OPTIMIZE_DEPS = _flag('PYI_OPT_DEPS')
OPTIMIZE_PLAYWRIGHT = _flag('PYI_OPT_PLAYWRIGHT')
OPTIMIZE_QT = _flag('PYI_OPT_QT')
OPTIMIZE_CHROMIUM = _flag('PYI_OPT_CHROMIUM')


def build_spec_content(entry='main.py', out_name=None, console=False):
    """生成 spec 文件内容。

    entry   : 入口脚本（相对项目根）
    out_name: EXE 名称；默认使用 批量登录工具V<版本>
    console : 是否保留控制台窗口（打包态自检用 True）
    """
    out_name = out_name or exe_name
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

# 以 spec 文件所在目录为基准，避免依赖当前工作目录
ROOT = SPECPATH


def _abs(*parts):
    return os.path.join(ROOT, *parts)


# ------------------------------------------------------------------
# Playwright 的 Node 驱动与 .local-browsers 内的 Chromium 必须整体收集，
# 否则打包后的 EXE 运行时无法定位浏览器。
# ------------------------------------------------------------------
tmp_ret = collect_all('playwright')

# ------------------------------------------------------------------
# 资源文件。
# 说明：devices.json / devices_template.xlsx 属于**运行期生成的用户数据**
# （内含真实设备地址与加密后的凭据），已在 .gitignore 中排除，
# 因此从 GitHub 全新克隆后这两个文件并不存在。
# 这里做存在性判断：缺文件就跳过，避免 PyInstaller 报
# "Unable to find ... when adding binary or data files" 而中断打包；
# 首次运行时程序会自动重新生成它们，功能不受影响。
# ------------------------------------------------------------------
datas = [(_abs('ico', 'app.ico'), 'ico')]
for _optional in ('devices_template.xlsx', 'devices.json'):
    _optional_path = _abs(_optional)
    if os.path.exists(_optional_path):
        datas.append((_optional_path, '.'))
    else:
        print('[spec] 可选文件不存在，已跳过：{{}}（首次运行时由程序自动生成）'.format(_optional))
datas += tmp_ret[0]
binaries = tmp_ret[1]
hiddenimports = tmp_ret[2] + [
    'encrypt', 'icon_data', 'openpyxl',
    'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
    'sqlite3',
]

# ------------------------------------------------------------------
# 体积优化 B：剔除有头模式下不会被调用的浏览器组件
# （顶层预过滤 + Analysis 之后过滤，后者才真正生效）
# ------------------------------------------------------------------
OPTIMIZE_PLAYWRIGHT = {OPTIMIZE_PLAYWRIGHT}
UNUSED_BROWSER_PATTERNS = {UNUSED_BROWSER_PATTERNS!r}


def _is_unused_browser(entry):
    norm = str(entry[0]).replace('\\\\', '/').lower()
    return any(p in norm for p in UNUSED_BROWSER_PATTERNS)


def _filter_browser(entries):
    kept, dropped = [], []
    for entry in entries:
        if _is_unused_browser(entry):
            dropped.append(entry[0])
        else:
            kept.append(entry)
    return kept, dropped


if OPTIMIZE_PLAYWRIGHT:
    datas, dropped_data = _filter_browser(datas)
    binaries, dropped_bin = _filter_browser(binaries)
    print('[spec] 优化B：预过滤未使用的浏览器组件 {{}} 项'.format(len(dropped_data) + len(dropped_bin)))

# ------------------------------------------------------------------
# 体积优化 D：精简 Chromium 内置资源与 Playwright 驱动冗余文件
# （顶层预过滤 + Analysis 之后过滤，后者才真正生效）
# ------------------------------------------------------------------
OPTIMIZE_CHROMIUM = {OPTIMIZE_CHROMIUM}
CHROMIUM_KEEP_LOCALES = {CHROMIUM_KEEP_LOCALES!r}
CHROMIUM_DROP_FILES = {CHROMIUM_DROP_FILES!r}
CHROMIUM_DROP_DIRS = {CHROMIUM_DROP_DIRS!r}
CHROMIUM_DROP_PATHS = {CHROMIUM_DROP_PATHS!r}
QT_DROP_DLLS = {QT_DROP_DLLS!r}


def _is_unused_chromium_resource(entry):
    norm = str(entry[0]).replace('\\\\', '/').lower()
    base = norm.rsplit('/', 1)[-1]
    # 1) 非中英文的界面语言包（Chromium 缺失时自动回退到 en-US）
    if '/locales/' in norm and base.endswith('.pak'):
        return base not in CHROMIUM_KEEP_LOCALES
    # 2) 运行时不会加载的辅助 EXE
    if base in CHROMIUM_DROP_FILES:
        return True
    # 3) 本程序不用的 Chromium 数据目录
    if any(d in norm for d in CHROMIUM_DROP_DIRS):
        return True
    # 4) Playwright 驱动的 TypeScript 类型声明
    if any(p in norm for p in CHROMIUM_DROP_PATHS):
        return True
    # 5) 依赖分析确认不可达的 Qt 模块 DLL
    if base in QT_DROP_DLLS:
        return True
    return False


def _filter_chromium(entries):
    kept, dropped = [], []
    for entry in entries:
        if _is_unused_chromium_resource(entry):
            dropped.append(entry[0])
        else:
            kept.append(entry)
    return kept, dropped


if OPTIMIZE_CHROMIUM:
    datas, dropped_data_d = _filter_chromium(datas)
    binaries, dropped_bin_d = _filter_chromium(binaries)
    print('[spec] 优化D：预过滤 Chromium 冗余资源 {{}} 项'.format(len(dropped_data_d) + len(dropped_bin_d)))

# ------------------------------------------------------------------
# 体积优化 A / C：排除未使用的模块
# ------------------------------------------------------------------
excludes = []
if {OPTIMIZE_DEPS}:
    excludes += {EXCLUDES_DEPS!r}
if {OPTIMIZE_QT}:
    excludes += {EXCLUDES_QT!r}
excludes = sorted(set(excludes))

a = Analysis(
    [_abs({entry!r})],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ------------------------------------------------------------------
# 体积优化 B（生效位置）：Analysis 会重新展开目录条目，
# 因此浏览器组件必须在 Analysis 之后、对最终 a.datas / a.binaries 过滤才生效。
# ------------------------------------------------------------------
if OPTIMIZE_PLAYWRIGHT:
    a.datas, dropped_data2 = _filter_browser(a.datas)
    a.binaries, dropped_bin2 = _filter_browser(a.binaries)
    print('[spec] 优化B：剔除未使用的浏览器组件 {{}} 项'.format(len(dropped_data2) + len(dropped_bin2)))

# ------------------------------------------------------------------
# 体积优化 D（生效位置）：Analysis 会重新展开目录条目，
# 因此 Chromium 冗余资源必须在 Analysis 之后、对最终 a.datas / a.binaries 过滤才生效。
# ------------------------------------------------------------------
if OPTIMIZE_CHROMIUM:
    a.datas, dropped_data3 = _filter_chromium(a.datas)
    a.binaries, dropped_bin3 = _filter_chromium(a.binaries)
    print('[spec] 优化D：剔除 Chromium 冗余资源 {{}} 项'.format(len(dropped_data3) + len(dropped_bin3)))

# ------------------------------------------------------------------
# 体积优化 C：精简 Qt 翻译文件（只保留中英文，其余语言运行时不会被加载）
# ------------------------------------------------------------------
KEEP_TRANSLATIONS = {KEEP_TRANSLATIONS!r}


def _filter_translations(entries):
    kept, dropped = [], []
    for entry in entries:
        dest = str(entry[0]).replace('\\\\', '/')
        if '/translations/' in dest and dest.endswith('.qm'):
            name = dest.rsplit('/', 1)[-1]
            if name not in KEEP_TRANSLATIONS:
                dropped.append(name)
                continue
        kept.append(entry)
    return kept, dropped


if {OPTIMIZE_QT}:
    a.datas, dropped_tr = _filter_translations(a.datas)
    print('[spec] 优化C：剔除非中英文 Qt 翻译文件 {{}} 个'.format(len(dropped_tr)))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name={out_name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console={console},
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_abs('ico', 'app.ico'),
    version=_abs('version_info.txt'),
)
"""
    return spec_content


def build_version_content():
    """生成 Windows EXE 文件属性（资源）版本信息内容"""
    return f"""# -*- coding: utf-8 -*-
# Windows EXE 文件属性（资源）版本信息
# 由 create_spec.py 依据 appcore/config.py 的 APP_VERSION 自动生成，请勿手工修改。
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={APP_VERSION_INFO!r},
    prodvers={APP_VERSION_INFO!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Jonathon'),
          StringStruct('FileDescription', '{APP_NAME}'),
          StringStruct('FileVersion', '{APP_VERSION}'),
          StringStruct('InternalName', '{exe_name}'),
          StringStruct('OriginalFilename', '{exe_name}.exe'),
          StringStruct('ProductName', '{APP_NAME}'),
          StringStruct('ProductVersion', '{APP_VERSION}')
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_spec(content, path=None):
    path = Path(path) if path else spec_file
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def write_version_info(path=None):
    path = Path(path) if path else version_file
    with open(path, 'w', encoding='utf-8') as f:
        f.write(build_version_content())
    return path


def main():
    write_spec(build_spec_content())
    write_version_info()
    print('spec 已生成: ' + spec_file.name)
    print('版本资源已生成: ' + version_file.name + f' (版本 {APP_VERSION})')


if __name__ == '__main__':
    main()
