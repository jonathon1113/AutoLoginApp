@echo off
rem 切换控制台代码页为 UTF-8，确保中文提示不乱码。
rem 本文件必须保存为「UTF-8 无 BOM」+ CRLF：cmd.exe 不会剥离 .bat 的 BOM，
rem 带 BOM 时首行 @echo off 会失效；无 BOM 时由 chcp 65001 切换后中文正常。
chcp 65001 >nul
title 批量登录工具 - 打包脚本 (Playwright)

rem ================================================================
rem   批量登录工具 - Windows 打包脚本
rem   基础流程（任务书指定）:
rem       set PLAYWRIGHT_BROWSERS_PATH=0
rem       playwright install chromium
rem       pyinstaller -F main.py
rem   在基础流程之上补充了运行所必需的参数（见下方注释）。
rem   版本号统一取自 appcore\config.py 的 APP_VERSION，
rem   EXE 名称与 EXE 文件属性版本资源均由该版本号生成。
rem ================================================================

cd /d "%~dp0"
echo 工作目录: %CD%
echo.

rem ---------------------------------------------------------------
rem 0) 选择 Python 解释器
rem ---------------------------------------------------------------
set PYTHON=python
if exist "C:\Software\python311\python.exe" set PYTHON=C:\Software\python311\python.exe

rem ---------------------------------------------------------------
rem 0.1) 可选参数：版本号处理（显式操作）
rem     build.bat          : 使用当前版本号打包（默认；重复打包不改变版本号）
rem     build.bat bump     : 先把补丁号 +1（5.0.9 -> 5.0.10），再打包
rem     build.bat 5.0.10   : 先切换到指定版本号，再打包
rem     递增由 bump_version.py 完成：改 appcore\config.py 的 APP_VERSION，
rem     并重新生成 批量登录工具V<版本>.spec 与 version_info.txt。
rem     日常重复打包请直接用 build.bat，避免版本号被意外递增。
rem ---------------------------------------------------------------
set "VERSION_ARG=%~1"
if /i "%VERSION_ARG%"=="bump" (
    echo [版本] 递增版本号（补丁号 +1）...
    %PYTHON% bump_version.py
    if errorlevel 1 (
        echo   ERROR: 版本号递增失败
        pause
        exit /b 1
    )
) else if not "%VERSION_ARG%"=="" (
    echo [版本] 切换到指定版本号: %VERSION_ARG%
    %PYTHON% bump_version.py %VERSION_ARG%
    if errorlevel 1 (
        echo   ERROR: 版本号切换失败
        pause
        exit /b 1
    )
)

rem ---------------------------------------------------------------
rem 0.2) 读取统一版本号（appcore\config.py 的 APP_VERSION）。
rem     先把版本号写入临时文件，再用 for /f 读取该文件；
rem     不用 for /f 直接捕获命令输出，避免在部分环境下取不到值而导致
rem     EXE 名称退化为「批量登录工具V0.0.0.exe」。
rem ---------------------------------------------------------------
set APPVER=0.0.0
set "VERFILE=%TEMP%\login_app_ver_%RANDOM%.tmp"
%PYTHON% get_version.py > "%VERFILE%" 2>nul
for /f "usebackq delims=" %%v in ("%VERFILE%") do set "APPVER=%%v"
del /q "%VERFILE%" >nul 2>nul
if "%APPVER%"=="0.0.0" (
    echo   ERROR: 读取版本号失败，请先手动执行 python get_version.py 检查
    pause
    exit /b 1
)
echo [版本] %APPVER%
echo.

echo [步骤 1/5] 检查依赖...
%PYTHON% -m pip show playwright >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 playwright...
    %PYTHON% -m pip install playwright -q
)
%PYTHON% -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 PyInstaller...
    %PYTHON% -m pip install pyinstaller -q
)
%PYTHON% -m pip show openpyxl >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 openpyxl...
    %PYTHON% -m pip install openpyxl -q
)
rem 验证码自动识别依赖（纯离线 OCR：本地 ONNX 模型，不联网）。
rem 缺失时程序会自动退回「人工处理验证码」的历史行为，不会崩溃。
%PYTHON% -m pip show ddddocr >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 ddddocr...
    %PYTHON% -m pip install ddddocr -q
)
%PYTHON% -m pip show onnxruntime >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 onnxruntime...
    %PYTHON% -m pip install onnxruntime -q
)
%PYTHON% -m pip show Pillow >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 Pillow...
    %PYTHON% -m pip install Pillow -q
)
echo   OK 依赖检查完成
echo.

rem ---------------------------------------------------------------
rem 1) 安装 Playwright Chromium
rem    PLAYWRIGHT_BROWSERS_PATH=0 表示浏览器安装到
rem    site-packages\playwright\driver\package\.local-browsers，
rem    打包时随 Playwright 一起收集进 EXE，运行时路径模式保持一致。
rem ---------------------------------------------------------------
echo [步骤 2/5] 安装 Playwright Chromium (有头模式所需)...
echo --------------------------------------------------
set PLAYWRIGHT_BROWSERS_PATH=0
playwright install chromium
if %errorlevel% neq 0 (
    echo   playwright 命令不可用，改用 %PYTHON% -m playwright ...
    %PYTHON% -m playwright install chromium
)
if %errorlevel% neq 0 (
    echo   ERROR: Playwright Chromium 安装失败
    pause
    exit /b 1
)
echo   OK Chromium 已安装
echo.

rem ---------------------------------------------------------------
rem 2) 清理旧的构建产物
rem ---------------------------------------------------------------
echo [步骤 3/5] 清理 build / dist...
echo --------------------------------------------------
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
echo   OK 清理完成
echo.

rem ---------------------------------------------------------------
rem 3) 生成 spec 与 Windows 版本资源（版本号取自 appcore\config.py）
rem ---------------------------------------------------------------
echo [步骤 4/5] 生成 spec 与版本资源...
echo --------------------------------------------------
%PYTHON% create_spec.py
if %errorlevel% neq 0 (
    echo   ERROR: 生成 spec 失败
    pause
    exit /b 1
)
echo   OK spec 与 version_info.txt 已生成
echo.

rem ---------------------------------------------------------------
rem 4) 打包
rem    V5.0.7 起统一使用 create_spec.py 生成的 spec 文件打包，
rem    以便应用其中的 excludes（未使用的重依赖）与 Playwright / Qt
rem    资源过滤；spec 内所有路径均以 SPECPATH 为基准，不依赖当前目录。
rem
rem    基础命令: pyinstaller -F main.py
rem    追加参数说明（等价的命令行方式，仅供参考，不再使用）:
rem      --name                 : 批量登录工具V<统一版本号>
rem      --version-file          : 写入 EXE 文件属性(文件版本/产品版本)
rem      --collect-all playwright : 收集 Playwright 的 Node 驱动与
rem                                 .local-browsers 内的 Chromium，
rem                                 否则 EXE 运行时找不到浏览器。
rem      --icon / --add-data      : 保留原项目图标 ico\app.ico
rem      --windowed               : 与原项目一致（无控制台窗口）
rem      --hidden-import          : encrypt / icon_data / openpyxl 等
rem                                 动态导入模块
rem    注: templates\ 目录不随包内置，用户模板始终位于 EXE 同目录的
rem        可写 templates\ 中（由程序首次启动时按需初始化）。
rem ---------------------------------------------------------------
echo [步骤 5/5] 执行 PyInstaller 打包 (可能需要数分钟)...
echo ---------------------------------------------------

where pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    set PYINSTALLER=%PYTHON% -m PyInstaller
) else (
    set PYINSTALLER=pyinstaller
)

%PYINSTALLER% "批量登录工具V%APPVER%.spec"

if %errorlevel% neq 0 (
    echo.
    echo   ERROR: 打包失败
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   打包完成!
echo ================================================================
echo.
echo   EXE: dist\批量登录工具V%APPVER%.exe
echo.
echo   说明:
echo     1. Playwright 的 Chromium 已随 EXE 内置（PLAYWRIGHT_BROWSERS_PATH=0）
echo     2. 首次启动会解压内置浏览器，耗时较长属正常现象
echo     3. devices.json / login_logs.db / app.log 等读写在 EXE 同目录
echo     4. 图标沿用原项目 ico\app.ico
echo     5. 模板目录为 EXE 同目录的 templates\（可写），不随包内置
echo     6. 验证码自动识别：ddddocr 模型与 onnxruntime DLL 已随包内置，
echo        运行时完全离线；EXE 体积因此增加约 100~150MB
echo     7. 打包体积优化（仅剔除运行时确认未使用的依赖与资源）：
echo        A 未使用的重依赖（numpy/scipy/PIL/lxml/pandas/matplotlib）
echo        B 有头模式不调用的 headless_shell 与 ffmpeg
echo        C 非中英文的 Qt 翻译文件与未使用的 PyQt6 模块
echo        D Chromium 非中英文语言包、运行时不会加载的辅助 EXE、
echo          Playwright 驱动的 TypeScript 声明与不可达的 Qt 模块 DLL
echo        （每项优化均有独立开关：PYI_OPT_DEPS / PYI_OPT_PLAYWRIGHT /
echo          PYI_OPT_QT / PYI_OPT_CHROMIUM，设 0 可单独回退）
echo.
pause
