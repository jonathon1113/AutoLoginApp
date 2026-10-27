<div align="center">
  <img src="docs/screenshots/V5.0.11_主窗口.png" alt="Main window" width="880">
  <br><br>
  <b>Batch Auto Login</b><br>
  Grouped multi-device web logins · Smart form recognition · Maintainable login templates
</div>

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.11.0-41CD52?logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![Playwright](https://img.shields.io/badge/Playwright-1.64.1-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![openpyxl](https://img.shields.io/badge/openpyxl-3.1.5-217346?logo=openpyxl&logoColor=white)](https://pypi.org/project/openpyxl/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-780-passed-brightgreen.svg)](#-testing)

</div>

<div align="center">

[中文](README.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) ·
[Compatibility](docs/兼容性清单.md) · [Test Report](docs/测试报告.md)

</div>

---

## What is this?

A Windows desktop tool for **operations / device management** teams: import a spreadsheet of
devices, group them, and **log in to many web consoles at once**.

It is not about clicking a login button once. It is about the real pain points:

- Dozens of devices, and every admin console has a different form structure;
- You must confirm the *real* outcome, not just "we clicked submit";
- Device credentials must not sit on disk in plaintext;
- The UI must stay **fully responsive** during bulk operations — no 30-second freeze.

> **Automation core: Playwright (Chromium, headed).** No Selenium / ChromeDriver.
> The browser stays visible so you can take over at any moment; quitting the app
> reclaims every browser process.

---

## ✨ Highlights

### 1. One browser window per group

**Double-click a group card** to log in to every device in that group. Each group gets its
own Chromium window, so cookies / cache / sessions are fully isolated between groups.

### 2. Form recognition driven by *role evidence*, not CSS-class guesswork

Inputs are classified into four roles — **username / password / captcha / submit button** —
and each decision is backed by multiple signals (`type`, `name`, `id`, `placeholder`,
`autocomplete`, `aria-label`, inline style, visibility, editability) with **graded weights**:

| Evidence | Typical source |
|----------|----------------|
| Strong (2.0) | `placeholder` / `aria` containing "password" / "account" semantics, `-webkit-text-security` style |
| Medium (1.0) | `name` / `id` matching an exact `password` / `username` token |
| Weak (0.5) | `class` containing a password word, `autocomplete=current-password` |

So an input with `placeholder="账号"` is no longer rejected just because it carries a
generic class such as `el-input__inner` — while a genuine password box is still refused.
When the evidence conflicts (looks like both an account and a password), the tool checks
whether an **independent password field exists on the page** to disambiguate. If it still
cannot decide, it **reports the ambiguity** instead of blindly filling the first input.

### 3. A maintainable login-template system

Templates are plain-text `templates/*.json` files. **The application never overwrites
hand-maintained content.** Three maintenance semantics are strictly separated — "append"
can never silently turn into "overwrite":

| Operation | Semantics |
|-----------|-----------|
| Append current selectors to the default template | Adds new selectors only; existing content is untouched |
| Merge a template into the default template | Union (deduplicated) with the target; existing content is untouched |
| Replace the default template with the built-in version | Full overwrite — **requires explicit user confirmation** |

When a device names a template, the tool **tries the template first** and only
**falls back to generic recognition** if the template stops working.

### 4. Bounded lookup + per-candidate diagnostics

Selector lookup runs under a **time budget** and stops at the first hit. On failure you
get more than "Form not found":

```
stage=username_lookup candidate=3/23 selector=CSS_SELECTOR=input[type="email"]
result=miss elapsed=12ms remaining_budget=2484ms
```

A dedicated **role-diagnostics** segment adds the target role, match count, actual element
tag, and the non-sensitive attributes (`type` / `name` / `id` / `placeholder` /
`autocomplete`), plus which rule fired and the exact rejection reason.

### 5. Background work — the UI never freezes

Reading the spreadsheet, parsing, validating and the **PBKDF2 encryption** all run on a
background thread; the main thread only updates widgets (via queued signals).
**Worker threads never touch a single widget.**

Measured with 100 devices on a 4-core machine: main-thread blocking dropped from
**13.1 s to 0 s**, and the worst event-loop delay was **32 ms** (Windows declares
"not responding" only after 5 s).

Encryption itself was parallelised too: PBKDF2 releases the GIL inside OpenSSL, so a
4-core machine goes from **13.2 s to 4.4 s (2.97×)** — with an unchanged ciphertext format.

### 6. Encrypted credential storage

Usernames and passwords are encrypted with **PBKDF2-HMAC-SHA256 (50 000 rounds) and a
per-field random salt**, keyed to the machine. Configuration is written with a
"temp file + atomic replace" strategy, so a failed import **cannot corrupt** the
existing configuration.

### 7. Real outcome verification

Success is decided by the **actual page state** (redirect, presence of user info,
disappearance of the error banner) — not "the button was clicked".

### 8. Ship as a single-file EXE

PyInstaller one-file build with **Chromium and the Node driver bundled**.
The target machine needs no Python, no browser and no ChromeDriver.

---

## 🧩 Feature matrix

| Area | Feature | Notes |
|------|---------|-------|
| **Devices** | Excel bulk import | 6-column template; multi-sheet, CN/EN header aliases, duplicate detection, per-row error summary |
| | Template generation | One click creates `devices_template.xlsx` with example rows |
| | Grouping | Devices organised by group; **double-click a card to log in** |
| | Single-device login | Double-click a device row, or select and press "Log in selected" |
| | Search & filter | Group dropdown + keyword search by IP / name |
| | Persistence | `devices.json`, encrypted, atomic write; a failed refresh rolls back to the last valid config |
| **Logging in** | Grouped batch login | Tabs in one browser; one isolated window per group |
| | Template-first with fallback | Device template → generic recognition when it fails |
| | Smart form recognition | Graded role evidence + page-level disambiguation |
| | Lookup budget | Bounded wait, stop on hit, early exit with a precise reason |
| | Per-candidate diagnostics | Candidate index, selector, result, elapsed, remaining budget, role diagnostics |
| | Captcha handling | Detect → locate & highlight → wait for a human → submit |
| | HTTPS | Ignores certificate warnings, handles the "Advanced → Continue" interstitial |
| | Already-logged-in detection | Skips devices that are already authenticated |
| | Result verification | Decided by real page state |
| | Login log | Persisted in SQLite, colourised by time / level / device / message |
| **Templates** | Recording | Capture the selectors that actually worked |
| | Maintenance | Append / merge / replace — three strictly separated semantics |
| | Management | Reload templates + open the templates directory |
| | Built-ins | `default` / `proxmox` / `huawei` |
| **UI** | Light theme | Native PyQt6 widgets + global QSS design tokens |
| | Group cards | Up to 4 per row, fewer columns on narrow windows |
| | Progress & feedback | Status bar / progress bar / InfoBar; failures always state the reason |
| | Background tasks | Excel import and device loading never block the UI |
| **Engineering** | CLI batch login | `login_batch.py` — tabs in a single browser |
| | Excel tool | `import_excel.py create/import` |
| | One-file EXE | `build.bat` → `dist/批量登录工具V5.0.11.exe` |
| | Automated tests | 780 regression checks, bundled mock login server, **no real devices needed** |
| | Screenshot generator | `tools/make_screenshots.py` — headless rendering, auto-redacted |

---

## 🚀 Quick start

### 1. Requirements

- Windows 10 / 11 (the source also runs on macOS/Linux, but the build script is Windows-only)
- Python **3.9+** (developed and tested on 3.11.9)

### 2. Install dependencies

```bat
pip install -r requirements.txt
```

> There are only **three** third-party runtime dependencies (PyQt6 / Playwright / openpyxl);
> everything else is the Python standard library.

Install Chromium where Playwright expects it (same path resolution as the packaged build):

```bat
set PLAYWRIGHT_BROWSERS_PATH=0
playwright install chromium
```

### 3. Run

```bat
python main.py
```

### 4. First run

1. **File → Create Excel template** to generate `devices_template.xlsx`
2. Fill in your devices (the template already ships with 5 fictional example rows)
3. **File → Import from Excel** and pick the file → group cards appear on the left
4. **Double-click a group card** to log in to every device in that group

---

## 📖 Usage

### Excel template layout (6 columns)

| Device name | Login URL | Username | Password | Group | Template |
|-------------|-----------|----------|----------|-------|----------|
| Sample device A | http://192.0.2.10:8080/login | demo_user | demo_password | Group A | default |
| Sample device B | https://example.com/login | demo_admin | demo_password | Group A | proxmox |

- The **login URL is the only required column**; header aliases are supported
  ("登录地址", "URL", "地址", …). A missing column raises an **explicit error**
  instead of silently producing wrong data;
- The "Template" column may be left empty — that means generic recognition;
- After import, passwords are stored encrypted in `devices.json`; no plaintext
  copy is written anywhere else.

### Menus

| Menu | Item | Action |
|------|------|--------|
| File | Create Excel template | Generate `devices_template.xlsx` |
| File | Import from Excel | Pick a sheet and produce an encrypted `devices.json` |
| File | Exit | Close all browsers and quit |
| Tools | Refresh configuration | Re-read `devices.json` and templates; roll back on failure |
| Tools | Close all browsers | Reclaim every open browser |
| Tools | Generate login template (no login) | Detect the form and record selectors without submitting |
| Tools | Save login template | Save the selectors recorded in this session |
| Tools | Manage template files | Reload templates and open the `templates` directory |
| Tools | Default template ▸ | Append / merge / replace the default template |
| Window | Maximize / restore browser window | Toggle browser window display state |
| Help | Instructions | Usage guide |
| Help | About | Version information |

### Shortcuts

| Action | How |
|--------|-----|
| Batch log in a group | **Double-click** a group card on the left |
| Quick log in one device | Double-click a device row, or select it and press "Log in selected" |
| Close all browsers | "Close all browsers" at the bottom / Tools menu |
| Close and quit | "Close browsers and quit" at the bottom / File → Exit |

---

## 🗂 Project layout

```
Login_app-V2/
├── main.py                       # Entry point (PyQt6 UI + Playwright engine)
├── appcore/                      # Core logic layer (UI-agnostic)
│   ├── config.py                 # Paths, timeouts, browser launch args, icon resolution
│   ├── logging_utils.py          # Logging (app.log / error.log)
│   ├── logdb.py                  # SQLite storage for login logs
│   ├── templates.py              # Login template management and recording
│   ├── devices.py                # Device config loading / grouping / encrypted save
│   ├── excel_io.py               # Excel parsing and import (pure data layer, no Qt)
│   ├── element_roles.py          # Form role recognition (username/password/captcha/button)
│   ├── automation.py             # Automation thread (asyncio event loop) wrapper
│   ├── browser.py                # Playwright browser/session/page operations
│   ├── login_engine.py           # Single-device / group / quick login flows
│   └── tasks.py                  # QRunnable background tasks (signals & slots)
├── appui/
│   ├── theme.py                  # Design tokens (color/font/spacing) + global QSS
│   ├── ui_kit.py                 # Native PyQt6 widget kit
│   └── main_window.py            # PyQt6 main window
├── tests/                        # Automated tests (mock login server + run_all.py)
├── tools/make_screenshots.py     # Screenshot generator (headless, auto-redacted)
├── docs/                         # Compatibility / test report / changelog / screenshots
├── templates/*.json              # Login templates (default / proxmox / huawei)
├── login_batch.py                # CLI batch login (tabs in one browser)
├── import_excel.py               # CLI Excel template generation / import
├── encrypt.py                    # Credential encryption (machine-bound key)
├── icon_data.py                  # Embedded icon fallback (base64 ICO)
├── ico/app.ico                   # Application icon
├── create_spec.py                # Generates the PyInstaller .spec file
├── bump_version.py               # Single source of truth for the version number
├── build.bat                     # Windows packaging script
├── requirements.txt              # Runtime dependencies
├── requirements-dev.txt          # Development / packaging dependencies
├── README.md / README.en.md      # Chinese / English documentation
├── CONTRIBUTING.md               # Contribution guide (env / conventions / commit rules)
├── CHANGELOG.md                  # Changelog
├── LICENSE                       # Apache License 2.0
└── .gitignore                    # Git ignore rules (credentials & build artifacts)
```

---

## 📦 Packaging (Windows)

```bat
build.bat
```

The script generates the `.spec` and `version_info.txt`, then runs PyInstaller:

```
dist\批量登录工具V5.0.11.exe    ← double-click and run, no Python needed
```

| Artifact | Notes |
|----------|-------|
| `version_info.txt` | Writes the EXE file properties: file version / ProductVersion = 5.0.11 |

Size-optimisation switches (only components confirmed unused at runtime are dropped):

| Environment variable | Effect |
|----------------------|--------|
| `PYI_OPT_DEPS=0` | Keep numpy / scipy / Pillow / lxml / pandas / matplotlib |
| `PYI_OPT_PLAYWRIGHT=0` | Keep `chromium_headless_shell` and `ffmpeg` |
| `PYI_OPT_QT=0` | Keep all Qt translations and unused PyQt6 modules |

> The full Chromium build (`chrome-win64`) is required for offline use and is never dropped.

**Notes**

1. The EXE creates / reads `devices.json`, `devices_template.xlsx`, `login_logs.db` and
   `app.log` **in its own directory**;
2. The first launch unpacks the bundled browser and runtime (~600 MB) — this takes a while
   and is expected;
3. **Re-import the Excel file after moving to another computer** (the key is machine-bound);
4. The browser runs **headed** and can be taken over manually; quitting the app reclaims
   every browser process.

---

## 🧪 Testing

```bat
python tests/run_all.py        :: full regression suite (16 test files, auto summary)
```

Run a single file:

```bat
python tests/test_engine.py           :: login engine against the bundled mock server
python tests/test_selector_lookup.py  :: lookup budget and per-candidate diagnostics
python tests/test_element_roles.py    :: form-role recognition matrix
python tests/test_excel_import.py     :: Excel import (background thread / UI responsiveness)
python tests/test_gui.py              :: PyQt6 UI behaviour
python tests/test_ui_theme.py         :: design tokens and widget doubles
python tests/test_template_policy.py  :: template priority and fallback
python tests/test_templates.py        :: template generation / validation / save / overwrite
python tests/test_real_login.py       :: real Playwright end-to-end verification
```

The suite uses a **bundled mock login server** (`tests/test_server.py`) and needs **no real
devices or intranet access**, so it runs on CI and on contributor machines.
Current baseline: **780 passed / 0 failed**.

> Real execution output: [`docs/测试报告.md`](docs/测试报告.md).

---

## 🔐 Security & privacy

- Usernames and passwords are encrypted with a **machine-bound key**
  (PBKDF2-HMAC-SHA256, 50 000 rounds, per-field random salt);
- Encrypted data can only be decrypted **on the same computer** — re-import the Excel
  file after switching machines;
- **This repository contains no real credentials, internal addresses or device configs**:
  - `devices*.json` / `devices*.xlsx` / `*.log` / `login_logs.db` are excluded by `.gitignore`;
  - source examples uniformly use RFC 5737 / RFC 2606 reserved addresses
    (`192.0.2.x` / `198.51.100.x` / `example.com`);
  - internal addresses and third-party site addresses in docs and screenshots are redacted;
- Diagnostic logs emit **non-sensitive attributes only** (tag / `type` / `name` / `id` /
  `placeholder` / `autocomplete`) and **never** any account, password or captcha content.

---

## ❓ FAQ

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Executable doesn't exist ... chromium` at startup | Browser not installed where expected | `set PLAYWRIGHT_BROWSERS_PATH=0` + `playwright install chromium` |
| Browser not found (EXE) | Packaged without `--collect-all playwright` | Rebuild with `build.bat` |
| First EXE launch is slow | Unpacks the bundled Chromium | Expected — just wait |
| "Form not found" | Page structure no longer matches the template | Re-record selectors via "Tools → Save login template" |
| "Wrong password" | Bad credentials or a real error banner | Check `devices.json`; the diagnostic log states the exact rejection reason |
| Captcha requested | The page has a captcha field | The tool locates and highlights it, then submits after you type |
| HTTPS certificate warning | Untrusted certificate | Certificate ignoring is built in; the tool also tries "Advanced → Continue" |
| Cannot decrypt after switching computers | The key is machine-bound | Re-import the Excel file |
| UI shows "not responding" | — | Import is fully backgrounded since V5.0.11; please report with logs if it recurs |

---

## 🤝 Contributing

Issues and pull requests are welcome. Please read **[CONTRIBUTING.md](CONTRIBUTING.md)**
first — it covers the dev environment, code conventions, test requirements and the
commit-message format.

---

## 📄 License

Released under the [Apache License 2.0](LICENSE).

```
Copyright 2026 Jonathon
```

---

## 📚 Further reading

| Document | Contents |
|----------|----------|
| [`docs/兼容性清单.md`](docs/兼容性清单.md) | Item-by-item compatibility matrix |
| [`docs/测试报告.md`](docs/测试报告.md) | Real execution results across seven test phases |
| [`docs/变更说明.md`](docs/变更说明.md) | What changed in each release |
| [`docs/交付报告_V5.0.11.md`](docs/交付报告_V5.0.11.md) | Full delivery report for the Excel-import freeze and the role misjudgement (root cause / measured timings / thread boundaries) |
| [`docs/模板维护说明.md`](docs/模板维护说明.md) | Template format and maintenance guide |
| [`docs/screenshots/`](docs/screenshots) | UI screenshots (generated from redacted data) |
| [`技术文档.md`](技术文档.md) | Architecture notes (Chinese) |
| [`CHANGELOG.md`](CHANGELOG.md) | Full changelog |

---

**Version**: 5.0.11 · **Author**: Jonathon · **Single source of truth for the version**:
`APP_VERSION` in `appcore/config.py` · Next release defaults to 5.0.12
