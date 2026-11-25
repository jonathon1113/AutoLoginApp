# 更新日志（CHANGELOG）

本文件是项目**版本号的唯一发布记录**。当前发布版本：**6.0.6**。

---

## 版本管理约定

### 1. 唯一版本来源

当前版本号定义在 **`appcore/config.py`**：

```python
APP_NAME = "批量自动化登录工具"
APP_VERSION = "6.0.6"
APP_VERSION_INFO = (6, 0, 6, 2)
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

- 本次修复后的版本：**6.0.6**
- 下一次正式打包发布：**6.0.7**
- 再下一次正式打包发布：**6.0.8**
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

## 未发布 — 文档与仓库整理（GitHub 开源准备）

> 本节记录**尚未发布**的改动。正式打包发布前按「版本管理约定」把 `APP_VERSION`
> 递增到下一个补丁号（6.0.7），并把本节改为对应版本号。

### 文档：README 精简 + 技术文档归档到 `docs/`

**改动**

- `README.md` / `README.en.md` **大幅精简**：只保留「这是什么、怎么用、怎么打包、
  常见问题、文档索引」，细节描述全部下沉到 `docs/`，适合直接放到 GitHub 首页；
- **新增 `docs/README.md`**：文档总索引（用户文档 / 技术文档 / 交付与测试 三类）；
- **新增 `docs/使用说明.md`**：安装、Excel 模板格式、界面说明、菜单一览、
  验证码处理、常见问题、注意事项；
- **新增 `docs/功能与实现详解.md`**：角色识别算法、查找预算与逐候选诊断、
  后台线程与性能数据、加密、打包、项目结构、功能一览；
- **技术文档归档**：根目录 `技术文档.md` / `技术文档-附录.md` 移动到
  `docs/技术文档.md` / `docs/技术文档-附录.md`；
- `bump_version.py` 的版本槽位与 `tests/test_bump_version.py` 的文档清单
  同步改为 `docs/` 下的新路径（README 只保留「当前版本 / 下一次发布」两个槽位）。

**影响范围**

- 仅文档结构调整，**不涉及任何功能代码改动**；
- 版本一致性检查（`python bump_version.py --show`）与升版往返测试全部通过。


### 工程：`.gitignore` 改为白名单模式，只上传必要文件

**改动**

- `.gitignore` 重写为**白名单**：先用 `*` 忽略仓库里的一切，再逐条放行
  「运行 / 构建 / 文档」真正需要的文件；
- **放行**：源码（`main.py` / `appcore/` / `appui/` / `icon_data.py` / `encrypt.py`）、
  运行资源（`templates/*.json`、`ico/`）、命令行与打包脚本、`requirements*.txt`、
  文档（`README*.md` / `CHANGELOG.md` / `CONTRIBUTING.md` / `LICENSE` / `docs/`）、
  测试（`tests/`）；
- **不放行**：设备凭据与 Excel 数据表、日志、登录数据库、虚拟环境、Python 缓存、
  打包产物（`build/` `dist/` `*.spec` `version_info.txt`）、临时与备份文件；
- 另加一道「安全网」：即使误把敏感文件加进放行清单，第 5 节规则仍会拦下；
- `git rm --cached docs/冻结态自检结果_selftest_result.txt`（生成的自检结果，
  属于产物而非文档）。

**验证**

- `git check-ignore -v` 逐项确认：`devices*.json` / `devices*.xlsx` / `*.log` /
  `login_logs.db` / `*.spec` / `build/` / `dist/` / `.venv/` / `__pycache__/` /
  临时脚本 **全部命中忽略规则**；
- `git add -A --dry-run` 与模拟索引核对：**最终上传 88 个文件 / 约 1.4 MB**
  （其中约 600KB 为 `docs/screenshots/` 截图），无任何凭据、日志或构建产物。


### 修复：4 个测试文件未设置 Playwright 浏览器路径，导致全量回归在部分机器上直接失败

**现象**

`python tests/run_all.py` 中 4 个文件直接失败（rc=1，无任何用例输出）：

```
FAILED test_captcha_flow.py      rc=1
FAILED test_captcha_real_ocr.py  rc=1
FAILED test_engine.py            rc=1
FAILED test_layout_speed.py      rc=1
```

**根因**

这 4 个测试文件启动 Chromium 前没有设置 `PLAYWRIGHT_BROWSERS_PATH=0`，
而本机浏览器是按「路径 0」安装在
`.venv\Lib\site-packages\playwright\driver\package\.local-browsers` 的，
Playwright 于是去默认目录找浏览器：

```
BrowserType.launch: Executable doesn't exist at
C:\Users\ccq\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe
```

**修复**

与 `main.py::_configure_playwright_browsers_path()` 保持一致，在 4 个测试文件中补上：

```python
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
```

**影响范围**

- 仅测试脚本，**不涉及应用功能代码**；
- 修复后全量回归：**857 通过 / 0 失败**（此前为 800 通过 / 4 个文件失败）；
- 已在 `CONTRIBUTING.md` 的「测试要求」中写明该约定，避免以后再踩。

### 文档：贡献指南与全套文档同步到 6.0.6

- `CONTRIBUTING.md`：运行期依赖由「3 个」更新为「6 个」（新增 OCR 三件套），
  版本命令示例更新为 6.0.7，新增 `appcore/` 模块分工表、验证码相关代码放置建议、
  浏览器路径约定、文档目录结构表、`.gitignore` 白名单说明与常见任务速查更新；
- `docs/变更说明.md`：新增 §I（6.0.1 ~ 6.0.6 变更），并更新开头的变更清单；
- `docs/兼容性清单.md`：新增 §13（V6.0.1 ~ V6.0.6 兼容性对照 V5.0.12），
  含用户可见行为变化、配置与数据格式、新增常量、依赖变化与产物地址；
- `docs/测试报告.md`：新增第八部分（6.0.x 专项），记录 **857 通过 / 0 失败**
  的实际执行输出、本次修复的测试环境缺陷与未验证项；
- `docs/技术文档.md`：新增 §4.6（验证码图片定位与 OCR 闭环）、§4.7（无验证码跳过与缓存）、
  §10.5（运行时 DLL 与 OCR 依赖），并更新代码索引；
- `docs/模板维护说明.md`：补充 `captcha_selectors` / `captcha_image_selectors`
  两个字段及「都为空 = 该页面没有验证码」的语义；
- `docs/验证码自动识别说明.md`：适用版本改为 6.0.1 起，
  `CAPTCHA_OCR_CASE_SENSITIVE` 默认值改为 `True`（区分大小写），
  `CAPTCHA_OCR_MAX_ATTEMPTS` 改为 30（双参数兜底），
  补充 `CAPTCHA_OCR_BETA` / `CAPTCHA_SKIP_WHEN_TEMPLATE_EMPTY` /
  `CAPTCHA_ABSENT_CACHE_ENABLED` 三个常量。

---

## 6.0.1 — 图片验证码自动识别闭环首发（离线 OCR）

> 6.0.1 ～ 6.0.6 为开发期连续迭代，下面按**发布批次**归并记录，
> 每一批对应一个已发布的补丁号。

### 新增：图片验证码自动识别闭环

**需求**

登录页出现「数字 + 大小写字母」图片验证码时，自动识别、自动填写、自动提交，
失败自动刷新重试；识别不可用时**完全退回**现有的人工处理行为。

**修改**

- **新增 `appcore/captcha_ocr.py`**：离线 OCR 识别器（ddddocr + onnxruntime）。
  - 懒加载（首次识别时才初始化引擎，不在启动 / UI 线程执行）；
  - 线程安全（`set_ranges` + `classification` 在同一把锁内）；
  - **`set_ranges` 必须传显式字符串**（ddddocr 1.6.x 的整数语义是
    「默认字符集前 N+1 个字符」，传整数会得到完全错误的结果）；
  - 结果必须同时满足「长度恰好 4 位 + 字符集合法 + 置信度达标」才可提交，
    非法字符整条作废（不允许删除后凑长度）；
  - 大小写归一化只在校验通过之后做；
  - 轻度预处理（灰度 + 对比度 + 2 倍放大）与多变体结果合并；
  - 任何异常都被吞掉并返回空结果，绝不中断登录流程。
- **新增 `appcore/config.py` 验证码常量**：开关、字符集、长度、置信度阈值、
  重试次数、图片查找预算、刷新等待、结果等待、带验证码的尝试预算（60 秒）。
- **新增 `appcore/browser.py::find_captcha_image()`**：验证码**图片**定位。
  顺序为「模板选择器 → 语义 CSS 规则 → 几何邻近兜底」；
  遍历验证码输入框所在 frame / 主 frame / 子 frame；
  **不走 `ROLE_CAPTCHA` 角色校验**（该校验会把 `<img>` 判为非法）。
- **改造 `appcore/login_engine.py`**：
  - 新增 `_detect_captcha_error()` / `_wait_captcha_result()`；
  - 新增 `_refresh_captcha()`（点击图片 → 等待 → 字节比对 → 必要时点击
    「换一张 / 刷新」链接 → 重新定位输入框）与
    `_solve_captcha_and_submit()`（识别 → 填写 → 提交 → 判定 → 失败刷新重试）；
  - `_run_template_attempt()` 的验证码分支：开关开启且 ddddocr 可用时走自动闭环，
    否则**保持原有的人工兜底分支完全不变**；
  - 只有「验证码错误」才重试；检测到账号 / 密码错误立即停止；
  - OCR 调用放在 `asyncio.to_thread` 中，避免阻塞 Playwright 事件循环。
- **新增模板可选字段 `captcha_image_selectors`**：保存验证码图片的定位规则；
  历史模板缺该字段时静默补空列表，不产生告警。
- **界面新增开关**：主界面右侧「快捷登录」面板的「自动识别验证码（数字+字母）」
  复选框，绑定 `appcore.config.CAPTCHA_AUTO_ENABLED`，运行期即时生效。
- **依赖与打包**：新增 `ddddocr==1.6.1` / `onnxruntime==1.32.0` / `Pillow==13.0.0`；
  `create_spec.py` 收集 ddddocr 模型与 onnxruntime DLL，并从排除列表中移除
  `numpy` / `PIL`（OCR 运行时依赖它们）；`build.bat` 增加依赖检查。
- **文档**：新增 `docs/验证码自动识别说明.md`（开关位置、参数含义、
  准确率实测方法与调参建议）；新增 `tools/measure_captcha_accuracy.py`。

**影响范围**

- 无验证码的普通页面：耗时不变（验证码检查仍为毫秒级）；
- 自动识别关闭或 ddddocr 未安装：行为与历史版本**完全一致**；
- 未改动选择器查找预算、`RETRYABLE_REASONS`、失败原因枚举与模板既有规则。

**验证**

- 新增 `tests/test_captcha_ocr.py`（26 项，mock ddddocr）：
  长度校验、字符集校验、大小写归一化、低置信度拒绝、`set_ranges` 收到字符串、
  异常兜底、多变体合并、懒加载。
- 新增 `tests/test_captcha_flow.py`（浏览器闭环，OCR 用假实现保证确定性）：
  识别正确自动登录、错误后刷新重试、非法字符不提交、低置信度不提交、
  OCR 不可用退回旧行为、无验证码页面不查找图片、模板来源命中。
- 新增 `tests/test_captcha_real_ocr.py`（**真实 ddddocr 引擎**的端到端测试）：
  直接用本地 ONNX 模型跑「定位图片 -> 截图 -> 识别 -> 填写 -> 提交」全链路，
  3 轮登录全部首次即成功。
- 新增测试页 `/captcha_ocr`（服务端生成 4 位数字+字母验证码，含干扰线与噪点，
  服务端不区分大小写）。
- 旧测试（`test_layout_speed.py` / `test_engine.py`）在验证码用例中关闭
  自动识别，原断言保持不变。


### 真实站点实测与调优（区分大小写站点）

在 `http://test.my.cn/captcha_login.php`（4 位、**区分大小写**、彩色干扰线 +
噪点、小字号衬线字体）上做了真实浏览器 + 真实 ddddocr 的端到端实测，
期间发现并修复了两个真实缺陷：

1. **元素截图把 CSS 边框截进来导致 OCR 完全失效**：
   该站点验证码图片带 `border:1px solid`，`element.screenshot()` 得到 150×49
   的带边图，ddddocr 直接返回空串。改为 `browser.capture_captcha_image()`：
   用 canvas 导出 `<img>` 原始像素（不含边框、不受 CSS 缩放影响、也不会重新
   请求图片换掉验证码），失败时才退回元素截图。
2. **区分大小写站点上"统一转大写"会把正确答案改错**：
   `CAPTCHA_OCR_CASE_SENSITIVE` 默认改为 `True`（原样提交），并新增界面开关
   「验证码区分大小写」。原样提交对区分 / 不区分大小写的站点都安全。

实测结论：

- 失败一次后验证码**立即作废**（服务端重渲染并刷新图片），因此
  「同一张图换大小写重试」不可行，只能刷新换新图重试；
- 单次独立识别成功率约 **15%~20%**（beta 模型、不做颜色过滤）；
- ddddocr 的**颜色过滤会把字符抗锯齿边缘一起抹掉**，实测反而降到 0%，
  故 `CAPTCHA_OCR_COLOR_FILTER` 默认**关闭**；
- 主要误差是**大小写**（如 `sKu4`→`sku4`、`7dZv`→`7dzv`），字符本身通常正确；
- 据此把 `CAPTCHA_OCR_MAX_ATTEMPTS` 调为 **6**，且每次尝试都使用**最优变体**
  （不再轮换到较弱变体，避免浪费重试机会）。


### 修复：两个站点的表单/按钮/验证码定位问题

用户反馈两个站点无法登录，逐个复现后定位并修复：

**1. `https://210.12.41.116:8989/login.html`（H3C 网络设备 WebUI）**

- 表单本身能定位（`#username` / `#password` / `#vldcode`），
  但**登录按钮不是 `<button>`**，而是 `<a id="myButton" class="submit">立刻登录</a>`；
  原来的泛化规则 `ID=login` 命中了页面上**不可见**的 `id="login"` 容器，
  点了个寂寞 → 表现为「登录结果未确认」。
  修复：把 `<a>` / `<div>` 形式的登录按钮规则（`//a[contains(., '立刻登录')]`、
  `//a[contains(., '登录')]`、`//*[@class='submit']` 等）**提到泛化 ID 规则之前**，
  泛化 ID 规则挪到最后。
- 验证码图片 `<img id="myvld" src=".../checknum_creat.php">` 之前只能靠
  「几何邻近兜底」找到（距离 208px），现补充语义规则
  `img[id*="vld" i]` / `img[src*="checknum" i]` / `img[src*="authnum" i]`，
  并补充验证码输入框 `input#vldcode` / `input[name="vldcode"]`。

**2. `https://mingshi8.hbte.com.cn/index.php/Home/Login/login.html`（河北教师教育网）**

- 表单、验证码图片（`img[src*="verify" i]`）、登录按钮（`button[type="submit"]`，
  按钮文字是「提交」不是「登录」）都能定位 ✓；
- 验证码图片 128×40、**深红色**字符、无干扰线，但站点**区分大小写**。
  原先按「最高置信度」在多个预处理变体里选结果，实测会出现
  「原图自信地认错、预处理变体反而正确」的情况
  （真值 `TzK2`：原图给 `tzk2` 置信度 0.98，灰度/掩膜变体给 `TzK2` 才是对的）。
  修复：改为**多数票**（多个变体给同一结果才算可信，置信度仅作平票时的兜底）。
- 另外确认该站验证码**不存在缓存问题**（`Cache-Control: no-store`，每次请求新图）。



---

## 6.0.2 — 真实站点成功率优化与「回车提交」触发

### 修复：「聚焦即刷新验证码」的站点 + 回车提交

用户指出 H3C 设备页有两个特点，实测确认：

**1. 验证码输入框获得焦点时会刷新验证码**

实测（210.12.41.116:8989）：

| 操作 | 验证码图片 |
|------|-----------|
| 初始 | `src=?captcha=1`，图 A |
| **点击输入框** | `src=...&t=1795505217703`，图 B（**变了**） |
| 之后再输入字符 | 不变 |
| 点用户名框 | 不变 |

原来的流程是「先截图识别 → 再填输入框」，而填输入框本身会触发刷新，
等于**提交的是刷新前的旧码**，必然失败。

修复（两道保险）：

- 每次尝试开始时**先激活（点击）验证码输入框**并等待图片加载完成，
  再截图识别；
- 填写前后**比对验证码图片指纹**（canvas 原始像素的 MD5）：若填写过程中
  图片又被刷新，就**自动重新识别并重新填写**。

实测日志：
`填写过程中验证码发生刷新，重新识别` → `验证码重新识别：'66zd'` →
`已用回车提交登录表单` → 服务端返回 **「用户名或密码错误」**
（不是「验证码错误」）—— 说明**验证码已被服务端接受**。

**2. 登录用回车触发，90% 的站点都支持**

原来只点击登录按钮；但 H3C 的按钮是 `<a id="myButton">`，点击未必触发登录。

修复：提交改为**回车优先** —— 在最后一个输入框（验证码框）按回车提交；
若回车没有任何反应（既没成功也没报错），再回退到点击登录按钮。
两种方式都保留，兼容各类站点。


### 优化：改为「时间预算驱动」的重试，端到端成功率 100%

继续排查后确认了两件关键事实：

1. **提交错误后验证码立即作废**（用同一张图穷举 16 种大小写组合，无一命中），
   所以「同图换大小写重试」不可行，每次尝试都是一次全新机会；
2. 该验证码（150×48、衬线小字、约 8 条彩色干扰线交叉、彩色噪点）**已超出
   通用 OCR 的可靠识别范围**：单次约 15%，且 ddddocr 是「自信地认错」
   （置信度 0.95~1.00 但内容错误），靠解码技巧无法补救。

因此把重试改成**时间预算驱动**：

- `CAPTCHA_ATTEMPT_BUDGET = 60` 秒为总预算（单次尝试约 2~3 秒，可试 20~30 次）；
- `CAPTCHA_OCR_MAX_ATTEMPTS = 30` 为次数上限；
- 按单次 15% 估算：10 次约 80%、20 次约 96%、30 次约 99%。

**端到端实测**（真实入口 `login_device`，每轮全新浏览器会话）：
6 轮全部登录成功，单轮 6.5~21.7 秒。

已试过但**无效**的方案（避免重复踩坑，详见 `docs/验证码自动识别说明.md` §8.4）：
ddddocr 内置颜色过滤（0%，反而更差）、`std`/`old` 模型、RapidOCR(PP-OCR) 检测与
仅识别（5%~10%）、形态学连通域切分（字符仅 1~2 像素宽，被线条粘连）、
均分 4 段逐字识别（15%，与整图持平）、放大倍数 3~12 扫描（15% 封顶）、
服务端泄漏排查（未发现）。

**结论与后续**

- 模拟验证码（不区分大小写、干扰适中）上真实 ddddocr top-1 为 **92%**；
- 上述**真实区分大小写站点**上，靠「颜色掩膜预处理 + 预算驱动重试」已能稳定登录
  （实测 6/6）；但单次识别率仍只有约 15%；
- 若该站点要求更高单次识别率，建议用真实样本（≥500 张）自训 4 字符识别模型，
  替换 `CaptchaRecognizer` 的引擎实现（接口已预留）。


### 优化：真实站点成功率提升（去彩色干扰掩膜 + 结果判定）

用户反馈用打包工具登录两个站点均失败，复现后定位并修复了 4 个问题：

1. **预处理升级**：新增「只保留暗且低饱和（黑色字符）像素」的颜色掩膜变体，
   并放大 3 倍、转 RGB 三通道。真实站点单次识别成功率由约 3%~7%
   提升到约 **15%**（约 3 倍），简单验证码仍为 100%；
   变体改为「同一张图依次尝试多个掩膜/灰度变体，取最可信合法结果」。
2. **重试次数**：`CAPTCHA_OCR_MAX_ATTEMPTS` 调整为 **10**
   （实测真实入口 10 轮全部登录成功，单轮 3.6~31 秒）。
3. **成功判定**：新增 `SUCCESS_KEYWORDS`（欢迎 / 登录成功 / 退出登录 / 注销），
   覆盖「表单提交后 URL 不变」的站点；「已登录」检测改为先看页面成功特征
   再看 URL，修复了 URL 含 `login` 时把已登录误判为找不到表单的问题。
4. **结果文案**：验证码自动识别失败时，`login_device` 不再统一回「已完成」，
   而是如实返回「验证码自动识别失败（已尝试 N 次）」/「需要验证码」。

另外补充了常见站点选择器（`input[name="user_code"]`、`确认登录` 按钮等），
并重新打包验证：EXE 正常启动，冻结态下 ddddocr 能加载包内模型并完成识别。



---

## 6.0.3 — 打包产物 / 换机 DLL 缺失彻底修复

### 修复：换一台电脑就报 `找不到指定的模块`（DLL 缺失）—— 彻底解决

**现象**：同一份 EXE，有些电脑正常，个别电脑启动即报：

```
ImportError: DLL load failed while importing QtGui: 找不到指定的模块
```

注意与之前的「找不到指定的**程序**」不同：这次是**模块缺失**（ERROR_MOD_NOT_FOUND）。

**根因**（用 PE 导入表逐层排查）：

1. `Qt6Core.dll` 依赖 `icuuc.dll`，而 Windows 上的 `icuuc.dll` 只是一个
   **36KB 的转发 DLL**（542 个导出全部转发给 `icu.dll`）。
   `icu.dll` 是 **Win10 1903 / Win11 才自带**的组件；
   Win10 1809、Server 2019 等没有它 → 报「找不到指定的模块」。

2. `Qt6Gui.dll` 等还依赖 VC++ 运行库（`msvcp140_2.dll`、
   `msvcp140_atomic_wait.dll` 等）。PyInstaller 只收集「依赖分析检测到的」
   几个，构建机装了 VC++ 运行库所以本机正常；目标机没装就缺 DLL。

**修复**（新增 `appcore/packaging_utils.py`，由 `create_spec.py` 调用）：

- 把 PyQt6 `Qt6\bin` 里自带的**整套 VC++ 运行库**
  （`msvcp140*.dll` / `vcruntime140*.dll` / `concrt140.dll` / `vccorlib140.dll`）
  显式打包，同时放到 EXE 根目录与 `PyQt6\Qt6\bin\`；
- 把 Windows 自带的 **`icu.dll` / `icuin.dll`** 一并打包；
- 按目标路径去重，不重复塞包。

这样 EXE **不再依赖目标机是否安装 VC++ 运行库、是否有 ICU**。


### 修复：打包后启动报 `ImportError: DLL load failed while importing QtGui`

**现象**：打包生成的 EXE 启动即退出，提示
`ImportError: DLL load failed while importing QtGui: 找不到指定的程序`
（procedure not found），源码运行正常。

**根因**（用 PE 导入表 + 构建 TOC 定位）：

1. `Qt6Core.dll` 依赖 `icuuc.dll`。构建机的 PATH 上存在另一套 ICU
   （poppler 自带的 ICU 78），PyInstaller 把它一并打进了 EXE 根目录，
   于是 Windows 优先加载了这个**版本不匹配**的 ICU，Qt6 找不到所需导出函数；
2. 同时还打进了第三方夹带的旧版 `msvcp140.dll` / `vcruntime140.dll` /
   `ucrtbase.dll` / `api-ms-win-*.dll`，进一步加剧加载冲突。

**修复**（`create_spec.py` 新增 `_normalize_runtime_dlls()`，在 Analysis 之后
统一改写 `a.binaries`）：

- `msvcp140*` / `vcruntime140*` / `concrt140` / `vcomp140` →
  改用 **System32** 的系统版本；
- `icuuc` / `icuin` / `icu` → 改用 **System32** 的系统 ICU（ICU 72，
  与 Qt6 匹配）；
- `icudt*` / `ucrtbase` / `api-ms-win-*` → 移除（Win10+ 系统自带）。

**验证**：

- 重新打包后，EXE 启动正常：日志显示「主窗口显示」「批量自动化登录工具 6.0.1 启动」，
  `dist/templates/`、`app.log`、`login_logs.db` 均正常生成；
- 另用最小化打包探针确认，冻结态下 `PyQt6.QtGui` / `QtWidgets` /
  `ddddocr` / `onnxruntime` / `PIL` 全部可导入，且 ddddocr 能从包内
  `ddddocr\common.onnx` 加载模型并完成一次真实识别。



---

## 6.0.4 — 内联 SVG 验证码识别

### 修复：内联 SVG 验证码识别不到（「找不到验证码」）

**现象**：登录页明明有验证码，工具却提示「找不到验证码图片」。

**根因**：该站点的验证码不是 `<img>`，而是**内联 SVG**：

```html
<div class="code-content" data-v-9574f9a0>
  <svg xmlns="http://www.w3.org/2000/svg" width="150" height="50" viewBox="0 0 150 50">
    <rect width="100%" height="100%" fill="#ABCC..." />
    <path fill="#73635a" d="M20.82 49.53..." />
    ...
  </svg>
</div>
```

原来的验证码图片查找只认 `img` / `canvas` / `input[type=image]`，
`<svg>` 从未进入候选，因此必然「找不到」。

**修复**：

1. 语义选择器新增 SVG 规则（`svg[class*="code"]`、
   `[class*="code-content"] svg`、`svg[class*="captcha"]` 等）；
2. 几何邻近兜底把 `svg` 也纳入候选；
3. **取图**：`<svg>` 不能直接 `drawImage`（只接受图片类对象），
   改为「序列化 SVG → data URL → Image → canvas → PNG」光栅化；
4. 深色主题验证码（浅字深底）自动反色成「浅底深字」，提升 OCR 成功率。

**验证**：新增 `/captcha_svg` 测试页（内联 SVG + el-input 风格），
端到端用例通过：验证码图片由语义规则
`[class*="code-content" i] svg` 定位 → 光栅化 → 识别 → 登录成功，
选择器同时被录制进模板。



---

## 6.0.5 — 验证码错误后的表单清空与表单定位

### 修复：验证码错误后表单清空 / 不清空 + 表单定位不到

用户反馈三类现象，逐个修复：

**1. 验证码错误后账号密码被清空**

部分站点在「验证码错误」后会把整个表单清空（账号密码一起没），
原来的重填逻辑只是「尽力填一次」，填失败也只记一条警告就继续提交，
结果用空账号提交，被服务端判成「密码错误」并直接停止重试。

修复：新增 `_ensure_credentials_filled()`——
每次提交前重填账号密码并**校验是否写入成功**；失败时按模板选择器
**重新定位字段**再填；仍失败则明确报「账号/密码无法填写（页面可能已被清空或重绘）」，
不再拿空账号去提交。

**2. 验证码错误后什么都不清空（错误验证码留在框里）**

失败退出前会**清空验证码输入框**，便于人工接手；每轮重试也会先清空再重填。

**3. 账号/密码/验证码框都无法定位**

- 新增「等 2 秒再完整重试一次定位」，覆盖 SPA / 慢页面首屏后才渲染表单的情况；
- 定位失败时输出**表单诊断日志**，例如：
  `表单诊断：inputs=2 frames=0 title=用户登录 url=... [type=text name=username vis=1] ...`
  可直接看出页面上到底有哪些输入框、是否可见、是否在 iframe 里。

顺带验证：用户提供的「随机 placeholder + name=username/password/captcha +
img.check-code」页面，端到端登录成功。



---

## 6.0.6 — 无验证码页面不再重复扫描选择器

### 优化：无验证码页面不再每次空查几十个选择器

**现象**：模板里 `captcha_selectors` 本来就是空的（页面本来没有验证码），
但每次登录仍会把「模板候选 + 内置候选」几十个选择器全部查一遍：

```
[选择器查找] 阶段=captcha_lookup 候选=1/14 ... 候选=14/14
[选择器查找] 阶段=captcha_lookup 候选=1/25 ... 候选=25/25
```

**优化**（新增 `appcore/captcha_cache.py`）：

1. **模板声明无验证码**：设备模板的 `captcha_selectors` 与
   `captcha_image_selectors` **都是空列表**时，视为该页面本来没有验证码，
   **直接跳过验证码查找**（耗时 0ms）；
2. **记住结论**：某次查找确认「该模板 + 该页面无验证码」且登录成功后，
   把结论持久化到 `captcha_absent.json`；下次同一模板/页面直接跳过；
3. **自我修复**：若跳过之后服务端仍提示「验证码错误」，说明页面其实有验证码，
   会自动清掉该缓存并重新完整查找一次，不会因缓存永久失效。

只对**设备模板**生效；默认模板仍按内置规则检查（避免漏掉验证码）。

实测：

| 场景 | 验证码查找耗时 |
|------|----------------|
| 模板声明无验证码（fnos 这类空模板） | **0ms**（跳过） |
| 陈旧模板首次查找 | 约 450ms（并写入缓存） |
| 同一模板/页面第二次登录 | **0ms**（走缓存） |



---

## 5.0.12 — 快捷登录完成后不再自动切回第一个标签页（2026-10-28）

### 变更：快捷登录完成后保持当前标签页

**问题**

快捷登录完成后，`quick_login()` 会调用 `session.select_first_tab()`，
把快捷登录窗口切回第一个标签页，用户原本正在浏览的位置被打断。

**修改**

- `appcore/login_engine.py::quick_login()`：
  移除登录完成后的 `select_first_tab()` 收尾动作，直接返回 `_quick_login_inner()` 的结果。
  登录完成后**保持登录所在的标签页**，不改变用户当前浏览位置。
- **分组登录行为不变**：`login_group()` 仍按原逻辑在全部设备登录完成后
  调用 `session.select_first_tab()` 切回该实例的第一个标签页。

**影响范围**

- 仅涉及登录完成后的标签页收尾动作；
- 登录流程、浏览器创建逻辑、模板选择器、Cookie/会话隔离策略均未改动。

### 验证

- `tests/test_engine.py` 新增两项针对性断言：
  - 「分组登录完成后自动切换到第一个标签页」→ 校验会话 `current_index == 0`；
  - 「快捷登录完成后不再切换到第一个标签页」→ 校验 `current_index` 停在最后登录的标签页，
    且第一个标签页未被 `bring_to_front()` 激活。
- `tests/test_v508_features.py` 的 E7 断言同步改为「快捷登录后保持当前标签页」。

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
相关说明见 `docs/技术文档.md`、`docs/技术文档-附录.md` 与 `docs/兼容性清单.md`。
本次版本升级**未修改**任何历史版本说明，仅新增 5.0.3 / 5.0.4 / 5.0.5 / 5.0.6 记录。
