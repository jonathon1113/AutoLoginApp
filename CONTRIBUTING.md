# 贡献指南

感谢你愿意为「批量自动化登录工具」出力！这是一份**面向第一次接触本项目**的贡献说明，
覆盖环境搭建、代码约定、测试要求、提交流程，以及**几条容易踩坑的硬性规则**。

> 本文档以中文为主；项目本身的中文注释与文档也是主要语言。英文说明见 [`README.en.md`](README.en.md)。

---

## 📋 目录

- [一、开发环境](#一开发环境)
- [二、代码结构与分层约定](#二代码结构与分层约定)
- [三、代码风格](#三代码风格)
- [四、线程与信号槽（最容易踩坑的地方）](#四线程与信号槽最容易踩坑的地方)
- [五、测试要求](#五测试要求)
- [六、版本号与文档同步](#六版本号与文档同步)
- [七、提交信息规范](#七提交信息规范)
- [八、敏感信息红线](#八敏感信息红线)
- [九、常见任务速查](#九常见任务速查)

---

## 一、开发环境

### 1. 准备环境

- Python **3.9+**（本项目开发与测试使用 3.11.9）
- Windows 10 / 11（打包脚本仅适配 Windows；源码可在 macOS / Linux 运行）

```bat
git clone <repo-url>
cd Login_app-V2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
set PLAYWRIGHT_BROWSERS_PATH=0
playwright install chromium
```

### 2. 运行

```bat
python main.py
```

### 3. 依赖说明

| 依赖 | 用途 | 备注 |
|------|------|------|
| `PyQt6` | 图形界面 | 原生控件 + 全局 QSS，**不依赖** qfluentwidgets |
| `playwright` | 浏览器自动化 | Chromium 由 Playwright 托管，无需 ChromeDriver |
| `openpyxl` | Excel 模板与导入 | — |
| `pyinstaller` | 打包 | 仅打包时需要（`requirements-dev.txt`） |

运行期第三方依赖**只有 3 个**，其余全部使用标准库。新增依赖前请先确认它是否真的必要。

---

## 二、代码结构与分层约定

```
appcore/   核心逻辑层：与界面解耦，可脱离 Qt 单独测试
appui/     界面层：只负责展示与交互，不写业务规则
tests/     自动化测试
tools/     开发辅助脚本（截图生成等）
```

### 分层红线

| 规则 | 说明 |
|------|------|
| `appcore` **不得** `import` `appui` | 反向依赖会让核心层无法独立测试 |
| 纯数据层**不得** `import` 任何 Qt 模块 | 例如 `appcore/excel_io.py` 只做解析与校验，不碰界面 |
| `appui` **不得**直接读写配置文件 | 一律通过 `appcore` 的接口（如 `device_store.load_devices()`） |
| 新增界面控件时优先复用 `appui/ui_kit.py` | 不要重复造轮子（`InfoBar` / `MessageBox` / 卡片 / 列表委托…） |
| 新增样式时优先复用 `appui/theme.py` 的令牌 | 颜色 / 字体 / 间距 / 圆角不要写死 |

### 代码放置建议

| 场景 | 放哪里 |
|------|--------|
| 新增一种表单角色的判定规则 | `appcore/element_roles.py` |
| 新增页面操作（点击 / 等待 / iframe 处理） | `appcore/browser.py` |
| 新增登录流程分支 | `appcore/login_engine.py` |
| 新增一种 Excel 表格格式兼容 | `appcore/excel_io.py` 的 `COLUMN_ALIASES` |
| 新增一个耗时后台任务 | `appcore/tasks.py`（`QRunnable` + 信号） |
| 新增界面控件 / 交互 | `appui/main_window.py` |

---

## 三、代码风格

### 基本约定

- **注释与 docstring 使用中文**，说明「为什么这么做」而不是复述代码；
- 函数 / 类顶部写 docstring，格式：

  ```python
  def do_something(self, param):
      """一句话说明作用。

      补充说明：为什么这样实现、边界条件是什么。
      """
  ```

- 命名：模块与函数 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`；
- 私有成员用单下划线前缀（`_helper`），模块内常量集中放在文件顶部；
- 注释统一使用**全角标点**（`，。：；「」`），与既有代码保持一致；
- 单个函数建议不超过 ~60 行；超过时优先拆分职责。

### 不要做的事

- ❌ 不要为了消除报错而**关闭必要的校验机制**；
- ❌ 不要**静默丢弃**数据（导入失败、解析失败必须给出具体原因）；
- ❌ 不要在**无证据支持**的情况下「顺手重构」无关代码；
- ❌ 不要使用 `except Exception: pass` 吞掉异常 —— 至少要 `Logger.error(...)` 并带上上下文。

---

## 四、线程与信号槽（最容易踩坑的地方）

本项目有三种并发场景，**各自的规则不同**：

### 1. 后台任务（`appcore/tasks.py`）

`QRunnable` + `QObject` 信号，**跨线程自动使用队列连接回到主线程**。

```python
class ImportExcelTask(QRunnable):
    def run(self):
        try:
            result = import_devices_from_excel(self.file_path, progress=...)
            _safe_emit(self, 'finished', result)
        except Exception as e:
            log_exception(e, "Excel 导入")
            _safe_emit(self, 'error', str(e))
```

**硬性规则：**

- ✅ 工作线程只做**数据处理**（读文件、解析、校验、加密、写盘）；
- ❌ **绝不在工作线程创建、修改或删除任何界面控件**；
- ✅ 界面更新一律通过**信号**回到主线程；
- ✅ 信号发射统一用 `_safe_emit`，避免窗口关闭时 `RuntimeError` 导致进程 abort。

### 2. Playwright 自动化线程（`appcore/automation.py` / `browser.py`）

Playwright 的异步 API 跑在独立的 asyncio 事件循环里。跨线程调用浏览器必须通过
`BrowserService` 的调度接口，**不要**从任意线程直接 `await page.…`。

### 3. 界面线程

只做：读控件属性 → 调核心层 → 写控件属性。**不要**在界面线程里做：

- 大文件读取 / 解析；
- PBKDF2 之类的密集计算（100 台设备 ≈ 13 秒）；
- 大量控件的逐个创建 / 逐个刷新。

> 界面阻塞的判定不要靠猜，**用耗时日志或事件循环延迟测量**来确认。

---

## 五、测试要求

### 运行全量回归

```bat
python tests/run_all.py
```

当前基线：**780 通过 / 0 失败**。

### 单文件运行

```bat
python tests/test_engine.py
python tests/test_excel_import.py
python tests/test_gui.py
```

### 提交前必须满足

- [ ] `python tests/run_all.py` **全绿**；
- [ ] 新增功能**必须有对应测试**（放在 `tests/` 下，命名 `test_*.py`）；
- [ ] 新增测试文件**必须**注册到 `tests/run_all.py` 的 `TEST_FILES` 列表，否则不会被执行；
- [ ] 修复 bug 时，尽量补一条**能在修复前失败、修复后通过**的回归测试；
- [ ] 涉及界面的测试用 `QT_QPA_PLATFORM=offscreen` 无头运行（见 `tests/test_gui.py`）。

### 测试风格

- 使用标准库 `unittest` 或项目现有的轻量 `check(name, ok, detail)` 断言风格，**不要引入新的第三方测试框架**；
- 测试数据一律使用**虚构值**（RFC 5737 / RFC 2606 保留地址），不要写真实内网地址或凭据；
- 需要真实设备 / 外部站点才能验证的场景，**如实标记为「测试受限」并跳过**，
  不要伪造成功结果，也不要让回归测试因外部依赖变红。

---

## 六、版本号与文档同步

**版本号只有一个来源**：`appcore/config.py` 的 `APP_VERSION`。

```bat
python bump_version.py 5.0.12          :: 递增版本号并重新生成 .spec / version_info.txt
python bump_version.py 5.0.12 --docs   :: 同时同步文档中的版本槽位
python bump_version.py --show          :: 检查各文档版本槽位是否一致
```

版本号变更后，还需要人工补齐以下文档（`bump_version.py` 会提示）：

| 文档 | 需要补充的内容 |
|------|--------------|
| `CHANGELOG.md` | 新版本的发布记录 |
| `docs/变更说明.md` | 本次的主要变更 |
| `docs/兼容性清单.md` | 用户可见行为变化的对照 |
| `docs/测试报告.md` | 本次的测试执行结果 |

> 文档中凡是出现「当前版本」的地方，请使用 `bump_version.py` 管理的槽位，
> 不要手写版本号，以免下次递增时漏改。

---

## 七、提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 风格：

```
<type>(<scope>): <简短描述>

<可选正文：为什么改、怎么改、影响什么>

<可选脚注：Closes #123>
```

常用的 `type`：

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `refactor` | 重构（**不改变行为**） |
| `perf` | 性能优化 |
| `test` | 只改测试 |
| `docs` | 只改文档 |
| `build` | 构建 / 打包相关 |
| `chore` | 杂项（依赖、配置、脚本） |

示例：

```
fix(excel-import): 导入加密改到后台线程，避免界面未响应

100 台设备时 PBKDF2 加密需要约 13 秒，全部发生在主线程，
导致 Windows 判定界面未响应。改为 QRunnable 后台执行，
界面更新通过信号回到主线程。实测事件循环最大延迟 32ms。

Closes #128
```

---

## 八、敏感信息红线

**提交前请确认仓库里没有以下内容：**

| 禁止提交 | 原因 |
|---------|------|
| `devices*.json` / `devices*.xlsx` | 含真实设备地址、用户名与密码（密码可能是**明文**） |
| `*.log` / `login_logs.db` | 含真实设备名、内网 IP、登录轨迹 |
| 源码 / 文档里的真实内网地址 | 用 RFC 5737（`192.0.2.x` / `198.51.100.x`）/ RFC 2606（`example.com`）代替 |
| 源码里的明文凭据 | 示例一律用 `demo_user` / `demo_password` |
| 截图里的真实地址 | 用 `python tools/make_screenshots.py` 重新生成（自动脱敏） |

`.gitignore` 已经排除了上述文件，但**新写的代码与文档仍需人工把关**。

另外，**诊断日志绝不能输出账号、密码或验证码内容** —— 只允许输出
`tag` / `type` / `name` / `id` / `placeholder` / `autocomplete` 等非敏感属性。

---

## 九、常见任务速查

| 我想…… | 怎么做 |
|--------|--------|
| 加一个新选择器策略 | 改 `appcore/element_roles.py` 或 `appcore/templates.py`，并补 `tests/test_element_roles.py` |
| 加一种 Excel 表头别名 | 改 `appcore/excel_io.py` 的 `COLUMN_ALIASES`，补 `tests/test_excel_import.py` |
| 加一个耗时操作 | 参考 `appcore/tasks.py` 的 `ImportExcelTask`，**不要**在界面线程里做 |
| 加一个界面提示 | 用 `appui/ui_kit.py` 的 `InfoBar.success / warning / error` |
| 改配色 / 间距 | 改 `appui/theme.py` 的令牌，**不要**在控件里写死 |
| 换版本号 | `python bump_version.py <版本> --docs`，再补四份文档 |
| 重新生成截图 | `python tools/make_screenshots.py` |
| 打包 | `build.bat` → `dist/批量登录工具V5.0.11.exe` |

---

## 📮 提问

遇到问题欢迎开 Issue，**请附上**：

1. 操作系统与 Python 版本；
2. 复现步骤；
3. `app.log` / `error.log` 中对应的片段（**注意先检查是否含敏感信息**）；
4. 设备页面结构（截图请打码）。

---

感谢你的贡献！🎉
