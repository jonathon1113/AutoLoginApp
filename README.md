<div align="center">
  <img src="docs/screenshots/V5.0.11_主窗口.png" alt="批量自动化登录工具 主界面" width="880">
  <br><br>
  <b>批量自动化登录工具</b><br>
  多设备分组批量 Web 登录 · 智能表单识别 · 可维护登录模板
</div>


<div align="center">

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.11.0-41CD52?logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![Playwright](https://img.shields.io/badge/Playwright-1.64.1-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![openpyxl](https://img.shields.io/badge/openpyxl-3.1.5-217346?logo=openpyxl&logoColor=white)](https://pypi.org/project/openpyxl/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-780-passed-brightgreen.svg)](#-测试)

</div>

<div align="center">

[English](README.en.md) · [更新日志](CHANGELOG.md) · [贡献指南](CONTRIBUTING.md) ·
[兼容性清单](docs/兼容性清单.md) · [测试报告](docs/测试报告.md) · [项目介绍](docs/项目介绍.md)

</div>

---

## 这是什么

一个面向 **运维 / 设备管理** 场景的 Windows 桌面工具：把一份 Excel 设备表导入程序，
按分组**一键批量登录**一堆设备的 Web 管理后台。

它解决的不是「怎么点一次登录按钮」，而是这些真实痛点：

- 一次要登几十台设备，每台后台的表单结构都不一样；
- 登录后还要人工确认结果，不能只看「点了提交就算成功」；
- 设备账号密码不能明文躺在硬盘上；
- 批量操作时界面必须**全程可点**，不能转圈几十秒。

> **浏览器内核：Playwright（Chromium，有头模式）**，不依赖 Selenium / ChromeDriver。
> 浏览器保持可见，人工随时可以接管；退出程序自动回收全部浏览器进程。
>
> **环境依赖：将Chromium内核通过二进制的方式打包到exe文件**，任何win环境都可正常运行。(没有浏览器及版本要求都是在包中)
>
> **缺点**：无法识别验证码，需要手动输入。不打算支持处win的其他环境。（其他系统后期源码开源可以自行打包测试）

---

## ✨ 特点

### 1. 分组批量登录，每个分组一个独立浏览器

分组卡片**双击即登录该组全部设备**。每个分组使用独立的 Chromium 窗口，
Cookie / 缓存 / 会话完全隔离，组与组之间互不污染。

### 2. 智能表单识别：基于「角色证据」而不是猜 CSS 类名

程序把页面上的输入框按 **用户名 / 密码 / 验证码 / 登录按钮** 四类角色分类，
每一类都由多项证据共同判定（`type` / `name` / `id` / `placeholder` / `autocomplete` /
`aria-label` / 样式 / 可见性 / 可编辑性），并对证据**分级加权**：

| 证据强度 | 典型来源 |
|---------|---------|
| 强（2.0） | `placeholder`/`aria` 含「密码 / 账号」等语义词、`-webkit-text-security` 样式 |
| 中（1.0） | `name`/`id` 精确命中 `password` / `username` 等词元 |
| 弱（0.5） | `class` 含密码词、`autocomplete=current-password` |

这样既不会把 `placeholder="账号"` 的输入框因为一个通用类名（如 `el-input__inner`）
就误判成密码框，也不会把真正的密码框放行。当证据冲突（同时像账号又像密码）时，
程序会**查页面上是否还存在独立的密码框**来消歧；仍然无法判定就**如实报歧义**，
而不是盲目填第一个输入框。

### 3. 可维护的登录模板系统

模板是 `templates/*.json` 纯文本文件，**程序不会覆盖用户手工维护的内容**。
三种维护语义严格区分，不允许把「追加」做成「覆盖」：

| 操作 | 语义 |
|------|------|
| 追加当前选择器到默认模板 | 只增加新选择器，默认模板原有内容一个不动 |
| 合并指定模板到默认模板 | 与指定模板取并集（去重），默认模板原有内容一个不动 |
| 用内置版本替换默认模板 | 整体覆盖，**必须由用户明确确认** |

设备配置了模板名时 → **先用模板定位**，模板失效才**回退到通用智能识别**。

### 4. 有界等待 + 逐候选诊断

选择器查找有**时间预算**，命中即停，绝不空转。失败时给出的不是一句
「Form not found」，而是：

```
阶段=username_lookup 候选=3/23 selector=CSS_SELECTOR=input[type="email"]
结果=未命中 耗时=12ms 剩余预算=2484ms
```

配合「角色诊断」段（目标角色、匹配数量、实际元素标签、type/name/id/placeholder/
autocomplete 等**非敏感属性**、触发了哪条规则、拒绝的具体原因），
排查「为什么这台设备登不上」不再靠猜。

### 5. 后台任务，界面全程不卡

Excel 导入的读文件、解析、校验、**PBKDF2 加密写盘**全部在后台线程执行，
主线程只负责界面更新（信号槽回到主线程），**工作线程绝不碰任何界面控件**。

实测（100 台设备、4 核机器）：主线程阻塞从 **13.1 秒降到 0 秒**，
事件循环最大延迟 **32ms**（Windows 判定「未响应」的阈值是 5 秒）。

加密本身也做了并行化：PBKDF2 在 OpenSSL 实现中会释放 GIL，
4 核机器上 **13.2 秒 → 4.4 秒（2.97×）**，密文格式完全不变。

### 6. 凭据加密存储

用户名 / 密码使用 **PBKDF2-HMAC-SHA256（50000 轮）+ 独立随机盐** 加密，
密钥与机器相关。配置写入采用「临时文件 + 原子替换」，
导入中途失败**不会损坏**原有配置。

### 7. 真实结果校验

登录成功与否由**页面真实状态**判定（登录后跳转、出现用户信息、错误提示消失等），
不是「点了按钮就算成功」。

### 8. 打包成单文件 EXE

PyInstaller 单文件打包，**Chromium 与 Node 驱动内置**，
目标机器不需要装 Python、不需要装浏览器、不需要 ChromeDriver。

---

## 🧩 功能一览

| 分类 | 功能 | 说明 |
|------|------|------|
| **设备管理** | Excel 批量导入 | 6 列模板；支持多工作表、中文/英文别名表头、重复设备检查、逐行错误汇总 |
| | 模板生成 | 菜单一键生成带示例行的 `devices_template.xlsx` |
| | 分组管理 | 按分组组织设备，分组卡片**双击即批量登录** |
| | 单设备快捷登录 | 双击设备列表项，或选中后点「登录选中设备」 |
| | 搜索与筛选 | 分组下拉筛选 + 按 IP / 名称关键字搜索 |
| | 配置持久化 | `devices.json` 加密存储，原子写入，刷新失败自动回滚到上一份有效配置 |
| **登录能力** | 分组批量登录 | 单浏览器多标签页；每个分组一个独立浏览器窗口 |
| | 模板优先 + 回退 | 设备配置模板 → 失效回退通用智能识别 |
| | 智能表单识别 | 四类角色证据分级判定 + 页面级消歧 |
| | 查找预算 | 有界等待、命中即停、提前终止并给出精确原因 |
| | 逐候选诊断日志 | 候选序号、选择器、结果、耗时、剩余预算、角色诊断 |
| | 验证码处理 | 检测验证码字段 → 定位并高亮 → 等待人工输入 → 自动提交 |
| | HTTPS 支持 | 忽略证书告警 + 处理「高级 → 继续」 interstitial |
| | 已登录检测 | 自动跳过已经登录的设备 |
| | 登录结果校验 | 由页面真实状态判定成功 / 失败 |
| | 登录日志 | SQLite 持久化，界面按时间 / 级别 / 设备 / 消息分区着色 |
| **模板系统** | 模板录制 | 登录成功后可把本次成功使用的选择器保存为模板 |
| | 模板维护 | 追加 / 合并 / 替换三种语义严格区分 |
| | 模板管理 | 重新加载模板 + 一键打开模板目录 |
| | 内置模板 | `default` / `proxmox` / `huawei` |
| **界面** | 浅色主题 | 原生 PyQt6 控件 + 全局 QSS 设计令牌（颜色 / 字体 / 间距） |
| | 分组卡片 | 每行最多 4 张，窗口变窄自动减列 |
| | 进度与反馈 | 状态栏 / 进度条 / InfoBar 提示条，失败必给具体原因 |
| | 后台任务 | Excel 导入、设备加载不阻塞 UI |
| **工程化** | 命令行批量登录 | `login_batch.py`，单浏览器多标签页 |
| | Excel 工具 | `import_excel.py create/import` |
| | 单文件 EXE | `build.bat` → `dist/批量登录工具V5.0.11.exe` |
| | 自动化测试 | 780 项回归测试，内置模拟登录服务器，**不依赖真实设备** |
| | 截图生成 | `tools/make_screenshots.py`，offscreen 无头渲染，自动脱敏 |

---

## 🚀 快速开始

### 1. 环境要求

- Windows 10 / 11（macOS、Linux 源码亦可运行，但打包脚本仅适配 Windows）
- Python **3.9+**（开发与测试使用 3.11.9）

### 2. 安装依赖

```bat
pip install -r requirements.txt
```

> 运行期第三方依赖**只有 3 个**（PyQt6 / Playwright / openpyxl），其余全是标准库。

首次使用需要把 Chromium 装到 Playwright 期望的位置（与打包流程保持同一套路径解析逻辑）：

```bat
set PLAYWRIGHT_BROWSERS_PATH=0
playwright install chromium
```

### 3. 运行

```bat
python main.py
```

### 4. 第一次使用

1. 菜单 **文件 → 创建Excel模板**，生成 `devices_template.xlsx`
2. 用 Excel 填写设备信息（模板里已有 5 行虚构示例，直接覆盖即可）
3. 菜单 **文件 → 从Excel导入**，选择刚填好的表 → 左侧出现分组卡片
4. **双击分组卡片**，即可批量登录该组设备

---

## 📖 使用说明

### Excel 模板格式（6 列）

| 设备名称 | 登录地址(URL) | 用户名 | 密码 | 分组 | 模板 |
|---------|-------------|-------|-----|-----|-----|
| 示例设备A | http://192.0.2.10:8080/login | demo_user | demo_password | A组-虚拟化 | default |
| 示例设备B | https://example.com/login | demo_admin | demo_password | A组-虚拟化 | proxmox |

- **登录地址**是唯一必需列，表头支持中文别名（如「登录地址」「URL」「地址」），
  缺列会**明确报错**而不是静默产出错误数据；
- 「模板」列可留空，留空表示使用通用智能识别；
- 导入完成后密码以密文写入 `devices.json`，**不会**留在 Excel 以外的明文文件里。

### 菜单

| 菜单 | 项 | 功能 |
|-----|----|------|
| 文件 | 创建Excel模板 | 生成 `devices_template.xlsx` |
| 文件 | 从Excel导入 | 选择 Excel 并生成（加密的）`devices.json` |
| 文件 | 退出 | 关闭所有浏览器并退出 |
| 工具 | 刷新配置 | 重新读取 `devices.json` 与模板，失败自动回滚 |
| 工具 | 关闭所有浏览器 | 关闭全部已打开的浏览器 |
| 工具 | 生成登录模板（不登录） | 只识别表单并记录选择器，不提交登录 |
| 工具 | 保存登录模板 | 保存本次录制到的选择器 |
| 工具 | 管理模板文件 | 重新加载模板 + 打开 `templates` 目录 |
| 工具 | 默认模板 ▸ | 追加 / 合并 / 替换默认模板 |
| 窗口 | 浏览器窗口最大化 / 还原 | 切换浏览器窗口显示状态 |
| 帮助 | 使用说明 | 操作指南 |
| 帮助 | 关于 | 版本信息 |

### 快捷操作

| 操作 | 入口 |
|-----|------|
| 分组批量登录 | **双击**左侧分组卡片 |
| 单设备快捷登录 | 双击右侧设备列表项，或选中后点「登录选中设备」 |
| 关闭全部浏览器 | 底部「关闭所有浏览器」/ 工具菜单 |
| 关闭并退出 | 底部「关闭浏览器并退出」/ 文件菜单「退出」 |

---

## 🗂 项目结构

```
Login_app-V2/
├── main.py                       # 程序入口（PyQt6 界面 + Playwright 引擎）
├── appcore/                      # 核心逻辑层（与界面解耦）
│   ├── config.py                 # 路径、超时常量、浏览器启动参数、图标解析
│   ├── logging_utils.py          # 日志输出（app.log / error.log）
│   ├── logdb.py                  # 登录日志 SQLite 存储
│   ├── templates.py              # 登录模板（选择器）管理与录制
│   ├── devices.py                # 设备配置加载 / 分组 / 加密保存
│   ├── excel_io.py               # Excel 解析与导入（纯数据层，不依赖 Qt）
│   ├── element_roles.py          # 表单角色识别（用户名/密码/验证码/按钮）
│   ├── automation.py             # 自动化线程（asyncio 事件循环）封装
│   ├── browser.py                # Playwright 浏览器/会话/页面操作层
│   ├── login_engine.py           # 单设备 / 分组 / 快捷登录流程
│   └── tasks.py                  # QRunnable 后台任务（信号槽）
├── appui/
│   ├── theme.py                  # 界面设计规范（颜色/字体/间距令牌 + 全局 QSS）
│   ├── ui_kit.py                 # 原生 PyQt6 组件库（标签/按钮/卡片/InfoBar/MessageBox/列表委托）
│   └── main_window.py            # PyQt6 主窗口
├── tests/                        # 自动化测试（模拟登录服务器 + run_all.py 统一运行器）
├── tools/make_screenshots.py     # 界面截图生成（offscreen 无头渲染，自动脱敏）
├── docs/                         # 兼容性清单 / 测试报告 / 变更说明 / 交付报告 / 截图
├── templates/*.json              # 登录模板（default / proxmox / huawei）
├── login_batch.py                # 命令行批量登录（单浏览器多标签页）
├── import_excel.py               # 命令行 Excel 模板生成 / 导入
├── encrypt.py                    # 设备敏感信息加解密（机器相关密钥）
├── icon_data.py                  # 内嵌图标兜底（base64 ICO）
├── ico/app.ico                   # 应用图标
├── create_spec.py                # 生成 PyInstaller .spec 文件
├── bump_version.py               # 版本号统一管理（唯一来源 appcore/config.py）
├── build.bat                     # Windows 打包脚本
├── requirements.txt              # 运行期依赖
├── requirements-dev.txt          # 开发 / 打包依赖
├── README.md / README.en.md      # 中文 / 英文说明
├── CONTRIBUTING.md               # 贡献指南（开发环境 / 代码约定 / 提交规范）
├── CHANGELOG.md                  # 更新日志
├── LICENSE                       # Apache License 2.0
└── .gitignore                    # Git 忽略规则（排除凭据与构建产物）
```

---

## 📦 打包为单文件 EXE（Windows）

```bat
build.bat
```

脚本会先生成 `.spec` 与 `version_info.txt`，再执行 PyInstaller，产物：

```
dist\批量登录工具V5.0.11.exe    ← 双击直接运行，无需 Python 环境
```

| 派生产物 | 说明 |
|---------|------|
| `version_info.txt` | 写入 EXE 文件属性：文件版本 / 产品版本 = 5.0.11 |

体积优化开关（只剔除运行时**确认未使用**的组件）：

| 环境变量 | 效果 |
|---------|------|
| `PYI_OPT_DEPS=0` | 保留 numpy / scipy / Pillow / lxml / pandas / matplotlib |
| `PYI_OPT_PLAYWRIGHT=0` | 保留 `chromium_headless_shell` 与 `ffmpeg` |
| `PYI_OPT_QT=0` | 保留全部 Qt 翻译文件与未使用的 PyQt6 模块 |

> 完整 Chromium（`chrome-win64`）是离线运行的前提，任何情况下都不会被剔除。

**注意事项**

1. EXE 运行时会在**自身所在目录**生成 / 读取 `devices.json`、`devices_template.xlsx`、
   `login_logs.db`、`app.log`；
2. 首次启动需解压内置浏览器与运行时（约 600MB），耗时较长属正常现象；
3. **切换电脑后需要重新导入 Excel**（加密密钥与机器相关）；
4. 浏览器为**有头模式**，可人工接管；退出程序自动回收全部浏览器进程。

---

## 🧪 测试

```bat
python tests/run_all.py        :: 全量回归测试（16 个测试文件，自动汇总）
```

单独运行：

```bat
python tests/test_engine.py           :: 登录引擎功能测试（本地模拟登录服务器）
python tests/test_selector_lookup.py  :: 选择器查找预算与逐候选诊断
python tests/test_element_roles.py    :: 表单角色识别矩阵
python tests/test_excel_import.py     :: Excel 导入（后台线程 / UI 响应性）
python tests/test_gui.py              :: PyQt6 界面功能测试
python tests/test_ui_theme.py         :: 界面设计规范 / 组件替身
python tests/test_template_policy.py  :: 模板优先级与回退策略
python tests/test_templates.py        :: 模板生成 / 验证 / 保存 / 覆盖确认
python tests/test_real_login.py       :: 真实 Playwright 端到端验证
```

测试使用**内置模拟登录服务器**（`tests/test_server.py`），**不依赖真实设备与内网环境**，
因此可以在 CI / 贡献者机器上直接跑。当前基线：**780 项通过 / 0 项失败**。

> 真实执行结果见 [`docs/测试报告.md`](docs/测试报告.md)。

---

## 🔐 安全与隐私

- 用户名 / 密码使用**机器相关密钥**加密（PBKDF2-HMAC-SHA256，50000 轮，独立随机盐）；
- 加密数据只能在**同一台电脑**上解密，切换电脑后需重新导入 Excel；
- **本仓库不包含任何真实凭据、真实内网地址或真实设备配置**：
  - `devices*.json` / `devices*.xlsx` / `*.log` / `login_logs.db` 已在 `.gitignore` 中排除；
  - 源码示例统一使用 RFC 5737 / RFC 2606 保留地址（`192.0.2.x` / `198.51.100.x` / `example.com`）；
  - 文档与截图中的内网地址、第三方站点地址已做脱敏；
- 诊断日志只输出**非敏感属性**（标签 / type / name / id / placeholder / autocomplete），
  **不输出任何账号、密码或验证码内容**。

---

## 已知bug

**现在**：每当启用1个实例，系统会生产一条登录失败4625日志。

**原因**：**这不是 Playwright 的 bug，也不是 Selenium 遗留问题，也不是项目主动调用凭据 API**；它是 **Chromium 上游回归 × Playwright 的临时 profile 策略 × 项目的高频浏览器创建** 三者叠加的结果。

**解决**：等官方更新再升级内置chrom二进制版本。



## ❓ 常见问题

| 现象 | 原因 | 处理 |
|-----|------|------|
| 启动报 `Executable doesn't exist ... chromium` | 浏览器未安装到期望路径 | `set PLAYWRIGHT_BROWSERS_PATH=0` + `playwright install chromium` |
| 提示找不到浏览器（EXE） | 打包时未加 `--collect-all playwright` | 用 `build.bat` 重新打包 |
| EXE 首次启动很慢 | 需要解压内置 Chromium | 属正常现象，等待即可 |
| 登录提示「Form not found」 | 页面结构与模板不匹配 | 用「工具 → 保存登录模板」重新录制选择器 |
| 登录提示「密码错误」 | 凭据错误或页面真实报错 | 检查 `devices.json` 中的账号密码；诊断日志会给出具体拒绝原因 |
| 需要验证码 | 页面存在验证码字段 | 程序会定位并高亮，等待人工输入后提交 |
| HTTPS 证书告警 | 站点证书不受信 | 已内置忽略证书策略；若仍出现，程序会尝试点击「高级 → 继续」 |
| 切换电脑后无法解密 | 密钥与机器相关 | 重新用 Excel 导入设备数据 |
| 界面显示「未响应」 | — | V5.0.11 起导入已完全后台化；若仍复现请附日志反馈 |

---

## 🤝 贡献

欢迎提交 Issue 与 PR。开始之前请阅读 **[CONTRIBUTING.md](CONTRIBUTING.md)**，
其中包含开发环境搭建、代码规范、测试要求与提交规范。

---

## 📄 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源。

目前源码还在测试中，测试好发布。

```
Copyright 2026 Jonathon
```

---

## 📚 相关文档

| 文档 | 内容 |
|------|------|
| [`docs/兼容性清单.md`](docs/兼容性清单.md) | 原有功能 / 参数 / 配置兼容性逐项对照 |
| [`docs/测试报告.md`](docs/测试报告.md) | 七阶段测试的真实执行结果 |
| [`docs/变更说明.md`](docs/变更说明.md) | 各版本的主要变更与删除的无用代码 |
| [`docs/交付报告_V5.0.11.md`](docs/交付报告_V5.0.11.md) | Excel 导入未响应 + 角色误判的完整交付报告（根因 / 实测耗时 / 线程边界） |
| [`docs/模板维护说明.md`](docs/模板维护说明.md) | 模板文件格式与维护指引 |
| [`docs/screenshots/`](docs/screenshots) | 界面实拍截图（脱敏数据生成） |
| [`技术文档.md`](技术文档.md) | 新架构实现详解 |
| [`CHANGELOG.md`](CHANGELOG.md) | 完整更新日志 |

---

**版本**：5.0.11　|　**作者**：Jonathon　|　**版本号唯一来源**：`appcore/config.py` 的 `APP_VERSION`　|　下一次正式发布默认递增为 5.0.12
