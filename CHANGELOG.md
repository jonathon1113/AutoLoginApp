# 更新日志（CHANGELOG）

本文件是项目**版本号的唯一发布记录**。当前发布版本：**5.0.11**。

---

## 版本管理约定

### 1. 唯一版本来源

当前版本号定义在 **`appcore/config.py`**：

```python
APP_NAME = "批量自动化登录工具"
APP_VERSION = "5.0.11"
APP_VERSION_INFO = (5, 0, 11, 2)
```

以下位置全部从该来源派生，**不允许**再单独写死版本号：

| 位置 | 取值方式 |
|------|----------|
| 窗口标题 | `appui/main_window.py` → `f"{APP_NAME} {APP_VERSION}"` |
| 界面标题标签 | `appui/main_window.py` → `f"批量自动化登录{APP_VERSION}"` |
| 关于窗口 | `appui/main_window.py` → `f"版本：{APP_VERSION}"` |
| 应用名 | `main.py` → `app.setApplicationName(f"{APP_NAME} {APP_VERSION}")` |
| EXE 文件名 | `build.bat` / `create_spec.py` → `批量登录工具V{APP_VERSION}` |
| EXE 文件属性版本资源 | `version_info.txt`（由 `create_spec.py` 依据 `APP_VERSION` 生成） |
| 打包脚本读取 | `get_version.py`（供 `build.bat` 取值） |

### 2. 递增规则

- 本次修复后的版本：**5.0.11**
- 下一次正式打包发布：**5.0.12**
- 再下一次正式打包发布：**5.0.13**
- 即：**正式发布按补丁号连续递增，不跳号**。
- 若某次发布功能变更规模较大，可按实际发布计划改为 `5.1.0` / `6.0.0`，但必须在本文件中明确记录，
  **不得擅自跳号**。

### 3. 何时递增

- **只有**在确实开始准备一次新的正式打包发布时，才把 `APP_VERSION` 递增到下一个补丁号。
- 开发调试、重复打包、自动化测试、代码合并等日常操作**不得**改动 `APP_VERSION`。
- 程序**不会**在每次启动时自动增加版本号。

### 4. 发布前检查清单

每次正式发布前必须逐项确认：

- [ ] `appcore/config.py` 的 `APP_VERSION` / `APP_VERSION_INFO` 已更新
- [ ] 界面标题、标题标签、关于窗口显示新版本（均取自常量，无需额外改动）
- [ ] 执行 `python create_spec.py` 重新生成 `.spec` 与 `version_info.txt`
- [ ] 执行 `build.bat` 完成打包
- [ ] 核对 EXE 属性（文件版本 / 产品版本）与新版本号一致
- [ ] 在本文件中新增该版本的记录，列出主要修改内容
- [ ] 同步 `README.md`、`docs/兼容性清单.md`、`docs/测试报告.md`、`docs/变更说明.md` 中的当前版本描述

---

## 5.0.11 — 修复 Excel 导入界面未响应 + 用户名选择器被角色校验误判为密码框（2026-10-27）

### 修复：导入 100 台设备后界面长时间「未响应」

**根因（基于实际代码与耗时实测，不是按数据量推断）**

旧版 `on_import_excel()` 在 **Qt 主线程里同步完成全部工作**，其中
`encrypt_devices()` 对 200 个字段各做一次 PBKDF2-HMAC-SHA256（50000 轮，约 65ms/字段）：

| 阶段 | 耗时 | 占比 |
|------|------|------|
| `openpyxl.load_workbook()` | 31 ms | 0.2% |
| 逐格 `ws.cell()` 遍历 + 校验 | ~0 ms | ~0% |
| **`encrypt_devices()`** | **13 110 ms** | **99.7%** |
| **主线程阻塞合计** | **13 141 ms** | 100% |

Windows 在主线程无响应约 5 秒后即弹「未响应」，13.1 秒必然触发。

**已排除的怀疑项**：核查 `update_device_list()` 为一次性 clear + 逐项 add、
`create_group_buttons()` 按分组创建卡片，**不存在「每台设备刷新一次」的问题**；
Excel 解析实测仅 32 ms，也不是瓶颈。

**修复**

- 新增 `appcore/excel_io.py`：**纯数据层**（不 import 任何 Qt），负责表头映射、
  必需列校验、`iter_rows(values_only=True)` 流式读取、逐行校验与重复地址收集。
- 新增 `appcore/tasks.py::ImportExcelTask(QRunnable)`：工作线程只做
  「读文件 → 解析 → 校验 → 加密 → 写盘」，**绝不触碰任何界面控件**；
  界面更新全部经 `ImportExcelSignals` 的 queued connection 回到主线程。
- `appui/main_window.py::on_import_excel()` 改为启动后台任务后立即返回（实测 0 ms）。
- `encrypt.py::encrypt_devices()` 改为 `ThreadPoolExecutor` 并行
  （PBKDF2 在 OpenSSL 实现中释放 GIL）：**13 187 ms → 4 437 ms（2.97×）**。
  **未改迭代数与密文格式**，历史 `devices.json` 仍可正常解密。
- `appcore/devices.py::save_devices()` 改为「临时文件 + `os.fsync` + `os.replace`」原子写入，
  导入中途失败不会损坏既有设备配置。
- 复用已有的 `stat_label` / `progress_label` / `progress_bar` 提供阶段反馈
  （正在读取 → 正在校验并加密 N 台 → 已写入 N 台），失败时恢复界面并显示**具体原因**。
- 新增 `_excel_importing` 标志位，导入中重复触发被拒绝；窗口关闭时等导入写盘完成再退出。

**顺带修正的两处静默缺陷**

- 表头缺 URL 列时，旧实现所有列默认索引都是 1，会**静默把第 1 列当成 URL**
  产出完全错误的数据 → 现在明确报错并列出实际读到的表头。
- 表格中间有一行空 URL 时，旧实现 `break`，**后续所有设备被静默丢弃** → 现在跳过并记录。

**实测对比**

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 导入 100 台总耗时 | 13 141 ms | 4 500 ms |
| 主线程阻塞 | 13 141 ms | ≈ 0 ms |
| **UI 事件循环最大延迟** | **13 141 ms** | **32 ms**（阈值 300 ms） |
| 导入期间定时器触发次数 | 0 | 786 |

### 修复：用户名选择器被角色校验误判为密码框（`looks_like_password`）

**根因**

旧版 `_password_evidence()` 把 **class 名、autocomplete 等权**处理：

```python
tokens, text = _tokens(info.get('id'), info.get('name'),
                       info.get('cls'),          # ← 类名与占位符同权
                       info.get('placeholder'), info.get('aria'))
if _has_token(tokens, _PASSWORD_TOKENS) or _has_cn(text, _PASSWORD_CN):
    return 2                                    # ← 2 = 硬性否决
```

且 `_username_evidence()` **不检查 class**，判定不对称。
于是只要账号框**自身**携带 `class="...password..."`、`autocomplete="current-password"`、
`name=password`、`id=pwd`、`aria-label=密码` 中任一线索，
`placeholder="账号"` 这条账号语义**无法抵消**，直接被判 `looks_like_password`。
此外原实现**没有任何页面级判据**，无法利用「页面上另有独立 `type=password` 输入框」。

**修复：证据分级 + 冲突消歧**

- 密码证据分三级：强 2.0（placeholder/aria 写着密码、CSS `-webkit-text-security`）、
  中 1.0（name/id 精确密码词）、弱 0.5（**class 名、autocomplete 自动填充标记**）。
- 用户名证据同样分级（强 2.0 / 中 1.0），**class 不参与**。
- 密码证据 ≥ 中且同时有强用户名证据 → 判为**证据冲突**（AMBIGUOUS），
  用页面上下文消歧：同一文档内**存在独立 `type=password` 输入框** → 判定真密码框另有其物，
  当前文本框按账号处理；**不存在 → 报歧义，绝不盲填**。
- 仅弱证据 → 放行但记录 `weak_password_signal(...)` 提示。
- 结构性否决（标签 / type / 隐藏 / 只读 / 禁用 / 不可见）、验证码语义优先、
  登录按钮反向否决等原有防线**全部保留**，未削弱任何校验。

**新增非敏感诊断日志**

角色校验失败时输出：目标角色、匹配数、拒绝原因、元素实际 `tag/type/id/name/class/
placeholder/autocomplete/aria`、可见性、密码证据分值与**命中来源**、
用户名证据分值与命中来源、以及最终处置（继续下一个候选 / 报告歧义 / 终止查找）。
**不记录任何表单值**（无账号、密码、验证码）。

### 新增

- `appcore/excel_io.py`：Excel 解析纯数据层（GUI 与命令行共用）。
- `appcore/tasks.py::ImportExcelSignals` / `ImportExcelTask`：后台导入任务。
- `tests/test_excel_import.py`：38 项断言（数据层 9 组 + 后台任务与界面响应性 +
  同步对照 + GUI 集成 16 项）。
- `tests/test_element_roles.py` 场景 11~15：4 个本地复现页 + 12 组离线矩阵（24 项）。
- `tests/test_server.py`：4 个角色复现页面常量。

### 验证结果

- 全量回归：**16 个测试文件 780 通过 / 0 失败**（`FAILED FILES: none`）；
  上一版基线 713 通过 / 0 失败，新增 71 项，**原有测试一项未改**。
- 角色识别：账号框（`type=text` + `placeholder=账号` + 共用 `el-input__inner` 类名 +
  `autocomplete=current-password`）**可被正常识别并填写**；
  同页真密码框仍被 username 角色拒绝、被 password 角色命中。
- 详见 `docs/交付报告_V5.0.11.md`、`docs/测试报告.md`（第七部分）。

### 公开发布整理（GitHub 开源发布）

为把项目发布到 GitHub，本次一并完成了仓库整理（**不包含任何业务逻辑变更**）：

| 项目 | 内容 |
|------|------|
| 许可证 | 新增 `LICENSE`（Apache License 2.0） |
| 依赖清单 | 新增 `requirements.txt`（3 个运行期依赖）/ `requirements-dev.txt`（额外含 pyinstaller） |
| 忽略规则 | 新增 `.gitignore`：排除 `devices*.json` / `devices*.xlsx` / `*.log` / `login_logs.db` / 构建产物 / 旧版 ChromeDriver |
| README | 重写 `README.md`（GitHub 版：徽章 / 特性 / 功能矩阵 / 快速开始），并新增英文版 `README.en.md` |
| 贡献指南 | 新增 `CONTRIBUTING.md`（分层红线、线程规则、测试要求、提交规范、敏感信息红线） |
| 凭据清理 | 清除源码中硬编码的真实凭据（`import_excel.py` / `appui/main_window.py` / `encrypt.py`），统一改为 RFC 5737 / RFC 2606 保留示例 |
| 文档脱敏 | 文档与源码中的真实内网地址、真实设备名、第三方生产站点地址统一脱敏 |
| 截图重制 | 新增 `tools/make_screenshots.py`（offscreen 无头渲染 + 自动脱敏），重新生成 `docs/screenshots/V5.0.11_*.png`，替代含真实内网地址的旧截图 |
| 打包容错 | `create_spec.py` 对 `devices.json` / `devices_template.xlsx` 做存在性判断，**全新克隆后可直接打包** |
| 测试适配 | `tests/test_real_devices.py` 在缺少本地 `devices.json` 时**优雅跳过**（原先会抛 `FileNotFoundError`）；`tests/test_selector_lookup.py` 场景 F 对不可达的外部站点标记为「测试受限」 |
| 版本槽位 | `bump_version.py` 的 `DOC_SLOTS` 改为对齐新版 README（旧的 9 条字面量已随 README 重写失效），并新增 `README.en.md` 的 5 条英文槽位，中英文版本号随升版自动同步 |

> **回归基线由 784 调整为 780**，两部分构成：
>
> 1. **−6**：场景 F 原先对两个第三方站点各做 4 项断言；脱敏后站点地址改为
>    RFC 2606 保留域名，公开环境下不可达，按「测试受限」如实标记并跳过后续
>    3 项/站点（共 6 项）；
> 2. **+2**：README 重写后重新对齐版本槽位机制，新增 `README.en.md` 的
>    槽位唯一命中校验与往返还原校验各 1 项。
>
> **没有任何一项测试被删除或弱化**，被跳过的只是依赖外部站点可达性的断言。

---

## 5.0.9 — 登录速度优化、设备分组四列与底部居中（2026-10-26）

### 修复：正常页面登录被「验证码检查」拖慢约 10 秒

**根因**（`appcore/login_engine.py` + `appcore/browser.py`）

- 验证码查找分「模板候选 → 内置 `CAPTCHA_SELECTORS`」**两轮串行**执行，
  而旧实现给**每一轮**各发一份完整的 `extra_budget`（`SELECTOR_LOOKUP_SLOW_BUDGET=8.0`），
  两轮等待时间**成倍累加**（实测单次验证码检查 9327ms = 3094ms + 3062ms + 扩展预算）。
- “确认页面上没有验证码” 被当作**强制阻塞步骤**，
  即使页面根本没有验证码，也必须等完整个扩展预算才能提交登录。

**修复**

- `find_captcha_field_detailed()` 引入**共享预算池** `pool`：
  第一轮用掉多少（`slow_wait_ms`），第二轮只能用 `max(0.0, pool - used_extra)`，不再各自拿满。
- 慢速页面的扩展等待收敛为 `SELECTOR_LOOKUP_READY_BUDGET=3.0`（并新增 `delayed_window=False`
  参数贯穿 `browser.py`），不再无条件申请 8s 扩展预算。
- 新增 `CAPTCHA_QUICK_STABLE_ROUNDS=2`：快速检查需**连续 2 轮表单控件数量稳定**才判定“无验证码”，
  避免刚渲染一半就误判。
- **分级策略**：页面已就绪（`complete`）→ 快速检查（`find_captcha_field_quick`）；
  页面未就绪（`loading` / `interactive`）→ 才进入有上限的扩展等待。
  日志新增「验证码检查结束：耗时=…，页面状态=…，慢速等待=是/否」。

**实测对比**（本地模拟服务器 + 真实 Chromium）

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| 正常页（无验证码）整次登录 | 19093ms | **1297~1672ms** |
| 正常页验证码检查 | 约 10s | 437~796ms |
| 慢速页（`/slowjs`）验证码检查 | 9327ms | **3311~3406ms** |
| 慢速页整次登录 | 13078ms | **6969~7125ms** |
| 批量并发时慢页对正常页的影响 | 正常页被同步拖慢 | 正常页不受影响（并发实测） |

**未削弱的原有能力**（全部保留并继续生效）

- 慢速页面等待机制（页面未就绪等待 / 延迟渲染输入框检测 / iframe 检查 / 选择器扫描预算）；
- 失败原因分类：`budget_exceeded` / `page_not_ready` / `frame_not_checked` / `selector_error`；
- 逐候选诊断日志与查找汇总日志；
- **验证码模板生成流程绝不自动提交登录**（`generate_template_only()` 只识别、不填写、不点击、不提交）；
- 未引入任何固定 `sleep` 代替页面状态判断。

### 变更：设备分组每行最多 4 张（响应式）

- `GROUP_COLUMNS_MAX = 4`；列数由**滚动区域视口宽度**实时计算
  （`usable = 视口宽 - 6`，`cols = (usable + 间距) // (卡片最小宽 + 间距)`），并限制在 `1~4`。
- **修复自反馈死循环**：旧实现用**容器自身宽度**反推列数，而容器位于
  `setWidgetResizable(True)` 的 `QScrollArea` 内，宽度被自身 `minimumSizeHint`
  （4×132+3×10+18=576）撑大 → 列数越多容器越宽 → 列数更多；
  窗口缩小时列数不减少且卡片被裁切（实测：窄 355px 仍为 4 列）。
- 卡片 `DoubleClickButton.minimumSizeHint()` 固定为 `QSize(110, 62)`，长分组名不再撑宽布局。
- 重排前用 `QLayout.takeAt()` + `deleteLater()` 清理旧布局，并加 `_relayouting` 递归保护；
  新增 `eventFilter()` 监听视口 `Resize`（覆盖拖动分隔条场景）。
- 实测：视口 791 / 594 / 447 / 355 px → 4 / 4 / 3 / 2 列，容器宽度恒等于视口宽度（零裁切、零重叠）。

### 变更：底部进度条与浏览器控制按钮整体居中

- 底部改为 `addStretch(1) + footer_content + addStretch(1)` 结构，
  不使用超大 `addStretch()` / 固定宽度 / 空白占位控件把元素推向两侧；
- `progress_bar` 最小宽度 220px（最大 420px），进度文案自动换行；
- 实测：1400px 窗口左右空白 485/485，900px 窗口左右空白 237/235（视觉居中，按钮间距 8px）。
- 「关闭所有浏览器」「关闭浏览器并退出」等按钮及其行为**全部保留**。

### 新增

- `tests/test_layout_speed.py`：54 项断言（分组四列与响应式 / 底部居中 / 登录速度与慢速等待 / 配置常量），
  含“批量登录中慢页面不会拖慢其它正常页面”的并发用例。

### 验证结果

- 全量回归：**10 个测试文件 453 通过 / 0 失败**（`FAILED FILES: none`）。
- 打包：`批量登录工具V5.0.9.spec` + `version_info.txt` 重新生成（文件版本 / 产品版本 = 5.0.9）。

---

## 5.0.8 — 浏览器黑框与窗口尺寸、验证码模板生成、慢速页面等待（2026-10-26）

### 修复：浏览器启动出现黑框（控制台窗口）

- 冻结态启动外部进程会弹出黑色控制台窗口（用户看到 `vimc.exe`）。
- 修复：改为**无控制台启动**（`CREATE_NO_WINDOW`），并引入进程级缓存；
  密钥派生结果保持不变，发货代码中不存在其它外部进程调用。

### 修复：浏览器窗口尺寸与页面尺寸不随窗口变化

- 历史版本浏览器以固定小尺寸打开，且 Playwright 默认把视口模拟为固定 1280x720，
  导致“放大窗口后页面尺寸仍不变化”。
- 修复：上下文使用 `no_viewport=True`（页面视口跟随真实窗口），
  并新增开关 `BROWSER_START_MAXIMIZED`（默认 `--start-maximized`），可随时关闭。

### 新增：验证码页面的模板生成（生成时绝不自动提交登录）

- 新增 `generate_template_only()`：只在当前登录页识别用户名 / 密码 / 验证码字段并录制，
  **不填写、不点击、不提交**；
- 保存流程与回退规则保持不变。

### 修复：慢速页面等待与失败原因细分

- 页面未就绪等待、延迟渲染输入框检测、iframe 内检查、选择器扫描预算；
- 失败原因分类：`budget_exceeded` / `page_not_ready` / `frame_not_checked` / `selector_error`；
- 诊断预算与逐候选诊断日志、查找结果汇总；
- 登录完成后切回**首个标签页**。

### 新增：五组真实登录页面的识别规则回归

- `tests/test_v508_features.py` 覆盖 q-input / form.userID / UserName+UserPasswd /
  loginName+password+checkCode / Ant Design+Angular 五组真实 HTML 样例的识别规则。

### 打包

- 打包体积优化继续推进（Chromium 资源精简等），EXE 体积降至约 247 MB。

---

## 5.0.7 — 界面全面美化与安全打包优化（2026-10-26）

本版本只调整**界面层**与**打包配置**，不改变任何登录流程、业务判断、数据结构与失败分类。

### 新增：统一设计规范与组件库

| 文件 | 用途 |
|------|------|
| `appui/theme.py` | 新增。设计令牌的唯一来源：颜色 / 字体 / 圆角 / 间距令牌 + 全局 QSS 样式表 + `apply_theme()` |
| `appui/ui_kit.py` | 新增。原生 PyQt6 组件替身：标签 / 按钮 / 卡片 / 滚动区 / 进度条 / `InfoBar` / `MessageBox` + 设备列表与日志列表自绘委托 |
| `tests/test_ui_theme.py` | 新增。界面专项回归测试（33 项断言） |

### 变更：移除 QFluentWidgets，改用原生 PyQt6 + QSS

- 审查结论：QFluentWidgets 在本项目只提供基础控件，而其顶层依赖
  `components.widgets.acrylic_label → common.image_utils` 会连带引入 numpy / scipy / Pillow，
  图表组件会引入 pandas / matplotlib —— 这些在程序中没有任何调用路径。
- 改为 `PyQt6` 原生控件 + 全局样式表后，类名与调用接口保持不变（`InfoBar` / `MessageBox` 等），
  `tests/test_template_policy.py` 中的替身（`FakeMessageBox` / `FakeInfoBar`）仍然有效。
- 主题由 `Theme.AUTO` 改为固定浅色主题，不跟随系统深色模式。

### 变更：主窗口布局重构（功能入口一个不少）

- 顶部：应用图标 + 标题 + 版本徽标 + 统计徽标 + 刷新配置 / 使用说明 / 关于。
- 左侧：设备分组卡片区（每行 3 张卡片，双击登录，双击/单击/右键行为不变）。
- 右侧：快捷登录 + 设备列表（卡片式委托，含名称 / URL / 模板 / 分组标签）+ 登录日志区。
- 底部：进度标签 + 进度条 + 关闭所有浏览器 / 关闭浏览器并退出，并新增 `QStatusBar` 状态栏。
- 日志保留全部诊断明细，新增按级别着色（成功 / 警告 / 错误）与条数统计，清理、复制、筛选能力不变。

### 修复：启动后设备列表为空（V5.0.6 遗留缺陷）

- 原因：分组下拉框初始化时使用 `blockSignals(True)`，导致 `currentTextChanged` 不触发，
  设备列表从未填充。
- 修复：`on_devices_loaded` 中主动调用 `update_device_list()` 刷新设备列表。

### 优化：打包体积（只剔除运行时确认未使用的组件）

| 类别 | 内容 | 依据 |
|------|------|------|
| A | 排除 numpy / scipy / Pillow / lxml / pandas / matplotlib | 源码中无任何 import 路径；lxml 对 openpyxl 是可选依赖（自动回退 xml.etree） |
| B | 剔除 `chromium_headless_shell` 与 `ffmpeg` | 生产代码 `appcore/browser.py` 固定 `headless=False`，不启用 `record_video`；实测在两者缺失时生产路径 12/12 通过 |
| C | 精简非中英文 Qt 翻译文件与未使用的 PyQt6 模块 | 项目只使用 QtCore / QtGui / QtWidgets，其余模块无 import 路径 |

- 打包改为统一走 `create_spec.py` 生成的 spec（`excludes` 与资源过滤只在 spec 中生效），
  spec 内所有路径以 `SPECPATH` 为基准，不依赖当前工作目录。
- 每一类优化可通过环境变量单独关闭，便于逐项验证与回退：
  `PYI_OPT_DEPS` / `PYI_OPT_PLAYWRIGHT` / `PYI_OPT_QT`。

**实测体积对比**（每次只开启一类优化，均记录体积与回归结果）：

| 轮次 | 启用项 | EXE 大小 | CArchive 条目 | 该轮回归 |
|------|--------|----------|--------------|----------|
| 基线（5.0.6） | 无 | 463.2 MB（485,661,006 字节） | 2037 | 306/0 |
| 第 1 轮 | A | 391.5 MB | 972 | 306/0 + EXE 冒烟 |
| 第 2 轮 | A+B | 272.4 MB | 677 | 306/0 + 源码态移除组件实测 |
| 第 3 轮（交付） | A+B+C | **270.6 MB（283,765,543 字节）** | **583** | 306/0 + EXE 冒烟 + 冻结态自检 |

累计 **463.2 MB → 270.6 MB，减少 192.6 MB（−41.6%）**。
其中 `chromium_headless_shell` 277.44 MB（291 项）与 `ffmpeg` 3.84 MB（4 项）已完全剔除（残留 0 项），
完整 Chromium `chrome-win64` 436.43 MB 按要求**原样保留**。

### 测试

- 自动化测试：306 通过 / 0 失败（新增 33 项界面专项断言）。
- 冻结态自检（与交付 spec 同源打包）：`PASS 浏览器启动成功 Chromium 156.0.8078.4`、
  `PASS 登录流程: OK（模板=default）`、`PASS 登录后URL: .../dashboard`。
- 详见 `docs/测试报告.md`（第五部分）。

---

## 5.0.6 — 选择器查找提前终止修复：逐候选诊断、预算语义重定义与失败原因细分（2026-10-25）

### 修复：默认模板选择器查找提前终止，剩余候选从未被执行

**根因（`appcore/browser.py` 的 `find_by_selectors_detailed()` 与 `probe_locator()`）**

旧实现对**每一个候选**调用 `probe_locator()`，而 `probe_locator()` 在元素不存在时会进入
「复查窗口」轮询：ID / NAME 类候选等满 `TIMEOUT_SELECTOR_PROBE=0.5s`，普通 CSS / XPath 候选
等 `0.3s`，宽泛选择器等 `0.15s`。也就是说，**每一个不存在的候选都要付出数百毫秒**，
而真正的存在性判断（`locator.count()`）本身只需 1~30 毫秒。

18 个用户名候选的前 7 个累计等待 2.75s（实测 375 / 515 / 531 / 343 / 328 / 390 / 343ms），
在第 7 个候选之后超出 `SELECTOR_LOOKUP_BUDGET=2.5s`，循环在第 8 个候选之前 `break`，
**剩余 11 个候选从未被执行**。这与线上日志完全一致：

```
默认模板用户名选择器未命中（Form not found：用户名查找超出耗时预算，剩余 11 个候选未尝试），耗时=2813ms
```

真正能命中的候选 `input[type="email"]` 排在第 11 位，因此永远走不到。
两个真实站点（site-a.example.com、site-b.example.com）正是这种「邮箱型登录框」页面。

**修复：两阶段查找（快速扫描 + 延迟渲染窗口）**

- **阶段 A 快速扫描**：新增 `quick_check_locator()`，对每个候选只做一次**不等待**的
  `count()` 存在性检查；命中可见元素立即返回。不存在的候选只消耗 0~31ms，
  整份候选列表都能在预算内被真正执行。
- **阶段 B 可见性确认**：对「存在但不可见」的候选做有限等待（`TIMEOUT_HIDDEN_WAIT=0.8s`）。
- **阶段 C 延迟渲染窗口**：在剩余预算内轮询页面是否出现表单控件
  （新增 `SELECTOR_SCAN_INTERVAL=0.15s`），出现后立即复查候选。
  这是**页面级共享预算**，不再是「每个候选各等一次」；控件数量未变化时按 4 轮节流复查。
- **子 frame 覆盖**：主文档未命中时在 iframe 内做一次快速扫描
  （独立预算 `SELECTOR_FRAME_BUDGET=0.8s`）。
- **预算语义重定义**：`SELECTOR_LOOKUP_BUDGET` 仍为 **2.5s（未调大）**，但它限制的是
  「整个查找阶段」而不是「每个候选」；预算不足时剩余候选逐个记录「未执行」及原因，
  不再静默跳过，也不再伪装成「所有候选都已查找失败」。

### 新增：逐候选诊断日志与查找汇总

- 每个候选输出一行诊断日志（`[选择器查找]`）：候选序号 / 总数、选择器、结果
  （命中 / 未命中 / 存在但不可见 / 语法无效 / 查询异常 / 未执行）、耗时、剩余预算、未执行原因。
- 每次查找输出一条汇总（`[选择器查找汇总]`）：候选总数、实际开始执行数、执行完成数、
  因预算不足未执行数、各类候选累计耗时、实际退出原因、是否为不完整查找。
- 登录引擎把逐候选日志与汇总接入统一的任务 ID 日志（`设备=… 任务=…`），三个登录入口一致。

### 修复：失败原因被统一吞成 `form_not_found`

`_describe_failure()` 之前把 `budget_exceeded` 直接转成 `form_not_found`，真实原因在日志中丢失。
现按实际原因分类：`selector_not_found` / `budget_exceeded` / `element_not_visible` /
`selector_invalid` / `selector_error` / `page_not_ready` / `frame_not_checked`；
新增常量 `FAIL_BUDGET_EXCEEDED` / `FAIL_PAGE_NOT_READY` / `FAIL_FRAME_NOT_CHECKED` /
`FAIL_SELECTOR_ERROR`（均属可重试原因）。预算耗尽时明确标注「本次为不完整查找」。

### 优化：默认模板选择器

`templates/default.json` 按「高可信度优先」重排并补齐邮箱型登录页：
用户名候选 18 → 23（新增 `input[type="email"]`、`input[autocomplete="email"]`、
`input[name="email"]`、`input[id="email"]`、`//input[contains(@placeholder,'邮箱')]`），
密码候选补 `input[autocomplete="current-password"]` 并前移，
按钮候选补 `Sign In` 大小写变体。

### 实测对比（同一页面、同一候选表）

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| 实际执行候选数（18 候选） | 7 / 18 | 18 / 18 |
| 因预算不足未执行的候选数 | 11 | 0 |
| 单个未命中候选耗时 | 327~531ms | 0~31ms |
| 候选检查累计耗时 | 约 2750ms | 约 60~120ms |
| site-a 用户名查找 | 2750ms，未命中 | 45ms，命中 `input[type="email"]` |
| site-b 用户名查找 | 2719ms，未命中 | 1094ms，命中 `input[type="email"]`（Vue 延迟渲染） |

真实站点登录（凭据仅在内存中使用，未写入任何配置文件）：site-a、site-b **均登录成功**。

### 修复：内置默认模板常量与磁盘模板漂移

`appcore/templates.py::DEFAULT_TEMPLATE` 是 EXE 首次启动时写入 `EXE 同目录 templates\`
的默认模板来源；它此前仍为旧的 18 个候选，与 `templates/default.json`（23 个）不一致，
导致 EXE 首次运行时生成的默认模板缺少邮箱型候选。现已同步为同一份 23 个候选，
并新增 `tests/test_templates.py::test_builtin_default_template_matches_disk` 断言两者一致。

### 新增

- `tests/test_selector_lookup.py`：场景 A~F 自动化测试 **44 项断言全部通过**
  （首个候选未命中后续命中 / 慢查询下的预算消耗与未执行标记 / 全部未命中 /
  预算耗尽 / 延迟渲染 / 两个真实站点），另含失败原因细分与 iframe 覆盖断言。

### 验证结果

- 自动化：`test_selector_lookup` 44、`test_template_policy` 78、`test_real_login` 42、
  `test_templates` 61、`test_engine` 12、`test_gui` 24、`test_real_devices` 12，
  合计 **273 通过 / 0 失败**（全部 `exit code = 0`）。

---

## 5.0.5 — 模板使用汇总日志、已有模板不再重复提示保存（2026-10-25）

### 修复：登录日志无法确认「实际使用的模板」

- **根因**：`_login_with_fallback()` 只有分散的单点日志，没有最终汇总；
  `_resolve_template()` 只返回「设备模板 / 默认模板」二值标签，丢失了原始模板名；
  失败与提前退出分支完全没有模板信息；各入口没有统一的入口标识与任务 ID；
  耗时未分段采集。因此日志里只能看到「配置了什么模板」，看不出「最终用了哪个模板」。
- **新增 `LoginContext`**：携带设备名、登录入口（单设备登录 / 快捷登录 / 分组批量登录）
  与全局递增任务 ID（`L1`、`L2`…），同一次登录的全部日志用同一任务 ID 串联，
  多设备并发时可区分。
- **`_resolve_template()` 改为返回结构化结果**：区分「配置的模板」「成功加载的模板」
  「实际执行的模板」，并保留失败时的真实文件路径与失败原因（不存在 / JSON 损坏 / 校验失败）。
- **新增 `[LOGIN_SUMMARY]` 汇总日志**：每次登录（含成功、失败、无法确认、验证码、已登录、异常）
  都输出一条汇总，包含设备、入口、配置模板、实际执行模板、模板文件绝对路径、
  设备模板执行结果、是否回退、回退原因、回退模板文件、最终结果、最终使用模板，
  以及模板查找 / 表单填写 / 按钮操作 / 总耗时（均为实际采集值，非写死）。
- **三个登录入口统一走同一套日志逻辑**：`login_device()` / `quick_login()` / `login_group()`
  均汇入 `_login_with_fallback()`，字段完全一致；界面结果行附带 `（模板=xxx）`。
- 模板绝对路径记录的是**实际读取的**文件路径，不再使用拼接出来但未访问的路径；
  日志不包含密码、Cookie、Token 等敏感信息。

### 修复：模板库已有模板仍提示保存

- **根因**：保存模板弹窗的「相似模板」判定用列表全等比较
  （`t.get('username_selectors') == recorded.get('username_selectors')`），
  几乎恒为 False，导致每次登录都弹窗；且该判断**完全不看设备配置中的 `template` 字段**，
  模板命中时同样会产出录制数据，因此即使用设备模板登录成功也照样弹窗；
  分组登录路径传入的还是分组名而非设备名。
- **模板状态五分离**：`appcore/templates.py` 新增 `inspect_template()`，
  分别给出「是否存在 / 是否可加载 / 加载失败类型 / 失败原因 / 真实路径」，
  模板文件存在但 JSON 损坏不再被当成「模板不存在」。
- **统一保存判断** `evaluate_save_template_request()`：各入口共用同一套规则——
  已配置可用模板 → 不提示；模板存在但损坏 → 记录具体原因，不提示也不覆盖用户文件；
  配置的模板确实不存在 → 允许提示新建；未指定模板且现有模板已覆盖本次选择器 → 不提示。
- **区分新建与更新**：目标模板已存在时进入「更新 / 覆盖确认」流程（不是伪装成新建），
  用户取消则磁盘文件保持不变。
- **分组登录逐台上报**：按设备名 + 该设备配置的模板名分别判断，不再用分组名冒充设备名。

### 新增

- `tests/test_template_policy.py`：场景 A~F 自动化测试（真实 Chromium headless + 本地模拟登录页面），
  78 项断言全部通过，覆盖模板正常命中、默认模板回退、模板文件损坏、模板缺失、
  已有模板更新、三个登录入口一致性与多设备并发日志区分。

### 修复：打包脚本 build.bat

- **中文乱码**：原文件为 GBK(ANSI) 编码，在 UTF-8 编辑器中整篇乱码。
  改为 **UTF-8 无 BOM + CRLF**，并在首行后加 `chcp 65001 >nul`，
  兼顾编辑器可读性与 cmd 控制台中文显示。
  （实测：**带 BOM 的 .bat 会被 cmd.exe 视为首行多一个字符，导致 `@echo off` 失效**，因此必须无 BOM。）
- **版本号读取退化为 0.0.0**：`for /f` 直接捕获命令输出在部分环境下取不到值，
  导致 EXE 被命名为 `批量登录工具V0.0.0.exe`。
  改为「先写临时文件、再由 `for /f` 读文件」，并加入读取失败即报错退出的保护。

---

## 5.0.4 — 模板真实生效、失败原因日志、默认模板回退与登录提速（2026-10-25）

### 修复：模板执行链的真实缺陷

- **设备模板选择器与真实 DOM 不符**：实测华为防火墙密码框真实 `id/name=platcontent`（页面上另有 `type=hidden` 的 `#password`，导致命中隐藏元素并耗尽查找预算）；Proxmox 登录按钮是 ExtJS 的 `<a class="x-btn">Login</a>`，既非 `<button>` 也非 `type=submit`。两个预置模板已按实测 DOM 修正。
- **XPath 文本匹配失效**：按钮文本匹配由 `contains(text(), …)` 改为 `contains(., …)`（ExtJS / Ant Design 将文字放在子 `span` 内，`text()` 只取直接文本节点，匹配不到）。
- **预置模板无法升级**：新增 `LEGACY_PRESET_SELECTORS` 白名单与 `_repair_preset_template()` 二分逻辑——磁盘预置模板未被用户改动 → 整体升级为内置版本（`upgrade`）；含内置没有的选择器 → 判定用户维护 → 仅补齐缺失字段（`fill`），不覆盖用户数据。
- **已登录判定过于宽松**：`_looks_logged_in()` 之前仅凭 URL 不同就判定「已登录」，现补充「页面仍存在密码输入框则不算已登录」。
- **回退默认模板缺日志**：补充「默认模板校验成功…」与「开始使用默认模板」等关键日志，便于核验回退真实发生。

### 修复：登录缓慢

- 新增 **选择器查找总耗时预算** `SELECTOR_LOOKUP_BUDGET=2.5s`、`TEMPLATE_ATTEMPT_BUDGET=20s`、`GENERIC_DISCOVERY_BUDGET=1.0s`、`TIMEOUT_HIDDEN_WAIT=0.8s`。
- 选择器查找改为 **probe 快速探测**（`count()` 立即判定存在性）+ 自适应复查窗口（ID/NAME 用满窗口，宽泛 CSS/XPath 只给 0.15s），取代原先每个候选数秒等待。
- 隐藏元素等待降为 0.8s 且受剩余预算约束（页面常存在同名 hidden input 吃掉预算）。
- 通用发现兜底耗时 5390ms → 2125ms；无表单页面的默认模板回退由约 54s → 2.7s。

### 新增

- `tests/test_real_login.py`：真实 Chromium 端到端验证（模板命中 / 模板失败回退 / 两者均失败 / 认证错误 / 快捷与分组入口一致）。
- `tests/test_real_devices.py`：真实设备验证（读取 `devices.json` 实际登录并核对 `app.log`）。

### 验证结果

- 自动化：`test_engine` 12、`test_templates` 56、`test_gui` 24、`test_real_login` 42 项全部通过。
- 真实设备：fnOS测试机（default.json，1375ms）、Proxmox主控（proxmox.json，921ms）、华为防火墙（huawei.json，453ms）均使用各自设备模板登录成功，未触发回退。

---

## 5.0.3 — 模板系统修复与版本统一（2026-10-25）

### 修复：模板系统

- **默认模板真正落盘**：`templates/default.json` 由程序首次启动时创建（原先仅存在内存常量），
  `proxmox.json` / `huawei.json` 同样按「文件不存在才创建」规则初始化，**绝不覆盖用户已修改的文件**。
- **模板校验**：`validate_template()` 区分「致命错误」（内容不是 JSON 对象、字段类型错误 → 跳过该文件）
  与「警告」（缺失字段 / 非法定位方式 / 空选择器 → 仍可加载，登录时对应部分回退通用查找），
  单个损坏文件不再影响其它模板。
- **模板优先于通用元素发现**：`login_engine` 改为「先模板、后通用」的显式执行路径
  （`find_by_selectors()` → 失败才 `find_username_field()` / `find_password_field()`），
  模板完全命中时不再执行任何通用扫描。
- **登录按钮也纳入模板**：`click_login_button()` 新增 `selectors` 参数，
  优先使用模板的 `login_button_selectors`（此前该字段从未被使用）。
- **模板名不再静默套用**：`get_template()` 找不到模板时返回 `None` 并记录原因，
  由登录引擎显式回退到内置通用模板（此前会静默返回默认模板，掩盖拼写错误）。
- **录制记录真实生效的选择器**：通用查找命中时同样记录选择器，
  修复了「录制的永远是默认模板选择器、保存后无法加速登录」的问题。
- **录制状态按线程隔离**：`TemplateManager` 的录制数据改为按线程隔离 + 最近一次结果槽，
  避免快捷登录与分组登录并发时互相覆盖。
- **保存流程加固**：模板名合法性校验（非法字符 / 路径穿越 / 禁止覆盖 `default`）、
  原子写入（临时文件 + `os.replace`）、写入后回读校验、更新内存注册表；
  任一环节失败都返回 `False` 且不留下半成品文件。
- **同名冲突处理**：界面保存模板时对已存在的同名模板弹出覆盖确认。
- **手工修改可被感知**：「工具 → 管理模板文件」会强制重新加载磁盘模板并显示加载错误。

### 修复：版本号统一

- 全项目版本号统一为 **5.0.3**，并建立单一版本来源（`appcore/config.py`）。
- 修正界面标题标签长期显示旧版本（`V4.6.7`）而窗口标题为 `v4.7.1` 的不一致。
- 新增 Windows EXE 文件属性版本资源（`version_info.txt`，文件版本 / 产品版本 = 5.0.3）。
- 打包脚本 `build.bat` 改为动态读取版本号，EXE 名称与版本资源随版本号自动同步。

### 新增

- `CHANGELOG.md`：本文件（版本约定与发布记录）
- `docs/模板维护说明.md`：模板目录位置、JSON 格式、增删改与验证方法
- `get_version.py`：供打包脚本读取统一版本号
- `version_info.txt`：Windows EXE 版本资源（由 `create_spec.py` 自动生成）
- `tests/test_templates.py`：模板系统 46 项自动化测试

---

## 4.7.1 — Selenium → Playwright 重构（2026-10-25）

- 全量迁移 Selenium → Playwright（`chromium.launch(headless=False, slow_mo=100)`）。
- GUI 保持 PyQt6 + qfluentwidgets，布局、菜单、快捷键、双击交互与原有图标均保留。
- 登录结果改为按页面真实状态判定（原实现为「点击登录即视为成功」）。
- 固定延时 `time.sleep` 全部替换为 Playwright 自动等待 / 页面状态等待。
- 新增 `appcore/` + `appui/` 分层结构、`tests/` 自动化测试与 `build.bat` 打包脚本。
- 修复登录日志落库状态错误（单设备记录一律「失败」、设备名与 URL 为空）。

---

## 更早的历史版本

`4.7.1` 之前的历史版本（v4.6.x 及更早）未在本仓库保留独立的发布记录文件，
相关说明见 `技术文档.md`、`技术文档-附录.md` 与 `docs/兼容性清单.md`。
本次版本升级**未修改**任何历史版本说明，仅新增 5.0.3 / 5.0.4 / 5.0.5 / 5.0.6 记录。