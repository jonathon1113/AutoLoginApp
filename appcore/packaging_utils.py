"""打包辅助：补齐 Qt6 在目标机上加载所需的运行库。

背景
----
PyInstaller 只收集「依赖分析真正检测到」的二进制。实践中有两类 DLL 会漏：

1. **VC++ 运行库**（msvcp140*.dll / vcruntime140*.dll / concrt140.dll /
   vccorlib140.dll）。
   构建机装了 VC++ 运行库，所以源码运行、打包后本机运行都正常；
   换一台没装运行库的机器，`Qt6Gui.dll` 找不到 `msvcp140_2.dll` 等依赖，
   报 `ImportError: DLL load failed while importing QtGui: 找不到指定的模块`。
   PyQt6 的 `Qt6\\bin` 目录里其实自带了一整套运行库，直接把它们打进去即可。

2. **Windows 自带的 ICU**（icu.dll）。
   `Qt6Core.dll` 依赖 `icuuc.dll`，而 Windows 上的 `icuuc.dll` 只是一个
   36KB 的**转发 DLL**（542 个导出全部转发给 `icu.dll`）。
   `icu.dll` 是 Windows 10 1903 / Windows 11 才自带的组件；
   Windows 10 1809、Server 2019 等没有，于是同样报「找不到指定的模块」。
   把 `icu.dll` 随包带上是唯一稳妥的做法。

本模块只做「列出需要额外打包的文件」，不修改任何系统文件。
"""

import os

# VC++ 运行库：PyQt6\Qt6\bin 里自带整套，直接收集
_VC_RUNTIME_PATTERNS = ('msvcp140', 'vcruntime140', 'concrt140', 'vccorlib140')

# Windows 自带 ICU：icuuc.dll 是转发 DLL，实现与数据在 icu.dll 里
_ICU_DLL_NAMES = ('icu.dll', 'icuin.dll')


def _qt_bin_dir():
    """返回当前环境里 PyQt6 的 Qt6\\bin 目录（取不到时返回空串）。"""
    try:
        import PyQt6
    except Exception:
        return ''
    return os.path.join(os.path.dirname(os.path.abspath(PyQt6.__file__)),
                        'Qt6', 'bin')


def _system32_dir():
    return os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                        'System32')


def find_runtime_binaries():
    """列出需要**显式**打包的运行库。

    返回 [(dest, src, 'BINARY'), ...]：
    - VC++ 运行库同时放到 EXE 根目录与 `PyQt6\\Qt6\\bin\\`，
      保证 Qt6Core.dll / Qt6Gui.dll 及其插件在任何加载顺序下都能找到；
    - `icu.dll` / `icuin.dll` 从 System32 取（Windows 自带，随包带上后
      不再依赖目标机系统版本）。
    """
    entries = []
    qt_bin = _qt_bin_dir()
    if qt_bin and os.path.isdir(qt_bin):
        for name in sorted(os.listdir(qt_bin)):
            low = name.lower()
            if not low.endswith('.dll'):
                continue
            if not any(pat in low for pat in _VC_RUNTIME_PATTERNS):
                continue
            src = os.path.join(qt_bin, name)
            entries.append((os.path.join('PyQt6', 'Qt6', 'bin', name),
                            src, 'BINARY'))
            entries.append((name, src, 'BINARY'))

    system32 = _system32_dir()
    for name in _ICU_DLL_NAMES:
        src = os.path.join(system32, name)
        if not os.path.exists(src):
            continue
        entries.append((name, src, 'BINARY'))
        if qt_bin:
            entries.append((os.path.join('PyQt6', 'Qt6', 'bin', name),
                            src, 'BINARY'))
    return entries


def merge_binaries(binaries, extra):
    """把 extra 合并进 binaries，按目标路径（小写）去重，已有的优先。"""
    seen = set()
    merged = []
    for entry in list(binaries) + list(extra):
        key = str(entry[0]).replace('/', '\\').lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return merged
