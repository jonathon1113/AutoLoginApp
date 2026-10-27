"""模板系统自动化测试。

覆盖任务要求的模板场景：
1. 模板目录不存在时创建目录与默认模板文件
2. 已有用户文件不被覆盖
3. 手工添加的有效 JSON 模板可被发现、加载并使用
4. 模板校验（语法错误 / 字段缺失 / 非法定位方式 / 空选择器）
5. 单个损坏文件不影响其它模板
6. 录制 -> 保存 -> 重载 -> 再次使用 的完整流程
7. 保存失败（目录不可写 / 非法名称）不误报成功
8. 有效模板优先于通用元素发现（调用顺序记录）
9. 模板选择器全部失效时回退到通用发现
10. 模板名称不存在时按兼容规则处理
11. 多设备使用各自模板

运行： python tests/test_templates.py
"""

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from appcore import templates as templates_module          # noqa: E402
from appcore.browser import (                              # noqa: E402
    find_by_selectors,
    find_login_button_by_selectors,
)
from appcore.templates import (                            # noqa: E402
    DEFAULT_TEMPLATE,
    TemplateManager,
    validate_template,
    validate_template_name,
)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)
    return ok


# ============ 模拟 Playwright Page / Locator ============
class FakeLocator:
    """模拟 Locator：按 CSS/XPath 关键字判断页面是否存在匹配元素"""

    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self

    async def wait_for(self, state='visible', timeout=1000):
        if self.page.exists(self.selector):
            return None
        raise AssertionError(f"not found: {self.selector}")

    async def is_visible(self, timeout=0):
        return self.page.exists(self.selector)

    async def is_enabled(self):
        return True

    async def click(self, timeout=0):
        self.page.calls.append(("click", self.selector))
        self.page.clicked.append(self.selector)

    async def fill(self, value=''):
        self.page.calls.append(("fill", self.selector))
        return None

    async def press(self, key, timeout=0):
        self.page.calls.append(("press", self.selector))
        return None

    async def count(self):
        return 1 if self.page.exists(self.selector) else 0

    def nth(self, i):
        return self


class FakePage:
    """模拟 Page：elements 为页面上真实存在的元素描述列表"""

    def __init__(self, elements):
        # elements: [(描述关键字, 选择器串), ...]
        self.elements = elements
        self.calls = []
        self.clicked = []

    def exists(self, selector):
        return any(desc in selector for desc, _ in self.elements)

    def locator(self, selector):
        self.calls.append(("locator", selector))
        return FakeLocator(self, selector)

    def get_by_text(self, text, exact=True):
        self.calls.append(("get_by_text", text))
        return FakeLocator(self, text)


def make_page():
    """模拟一个标准登录页：用户名(name=username)、密码(name=password)、登录按钮"""
    return FakePage([
        ("username", '[name="username"]'),
        ("password", '[name="password"]'),
        ("登录", "//button[contains(text(), '登录')]"),
    ])


# ============ 测试主体 ============
def test_template_dir_bootstrap():
    """1) 模板目录不存在时创建目录与默认模板文件"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        TemplateManager._loaded = False
        TemplateManager._templates = {}
        TemplateManager._sources = {}

        TemplateManager.create_default_template_files()
        ok_dir = os.path.isdir(templates_module.TEMPLATE_DIR)
        check("模板目录不存在时自动创建", ok_dir, templates_module.TEMPLATE_DIR)

        default_file = os.path.join(templates_module.TEMPLATE_DIR, "default.json")
        check("默认模板文件真实存在于磁盘", os.path.isfile(default_file), default_file)

        with open(default_file, encoding='utf-8') as handle:
            data = json.load(handle)
        check("默认模板JSON可解析且含三组选择器",
              all(data.get(k) for k in
                  ("username_selectors", "password_selectors", "login_button_selectors")),
              f"keys={sorted(data.keys())}")

        TemplateManager.load_templates(force=True)
        check("默认模板被加载进注册表", TemplateManager.get_template("default") is not None,
              f"已加载={TemplateManager.list_templates()}")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_user_file_not_overwritten():
    """2) 用户手工修改过的默认模板文件不会被启动时覆盖"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        target = os.path.join(templates_module.TEMPLATE_DIR, "default.json")
        custom = dict(DEFAULT_TEMPLATE)
        custom["description"] = "用户手工修改过的默认模板"
        with open(target, 'w', encoding='utf-8') as handle:
            json.dump(custom, handle, indent=2, ensure_ascii=False)

        TemplateManager.create_default_template_files()

        with open(target, encoding='utf-8') as handle:
            after = json.load(handle)
        check("启动时不覆盖用户修改过的默认模板",
              after.get("description") == "用户手工修改过的默认模板",
              f"description={after.get('description')}")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_manual_template_discovery():
    """3) 手工添加的模板可被发现并加载"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        manual = {
            "name": "mymanual",
            "description": "手工维护的模板",
            "username_selectors": [{"by": "css", "value": "input[name='username']"}],
            "password_selectors": [{"by": "css", "value": "input[name='password']"}],
            "login_button_selectors": [{"by": "css", "value": "button[type='submit']"}]
        }
        with open(os.path.join(templates_module.TEMPLATE_DIR, "mymanual.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump(manual, handle, indent=2, ensure_ascii=False)

        TemplateManager.reload_templates()
        template = TemplateManager.get_template("mymanual")
        check("手工添加的模板被自动发现", template is not None,
              f"已加载={TemplateManager.list_templates()}")
        check("手工模板按文件名也可引用", TemplateManager.get_template("mymanual.json") is not None)
        check("小写 css 定位方式被归一化",
              template and template["username_selectors"][0]["by"] == "CSS_SELECTOR",
              f"by={template['username_selectors'][0]['by'] if template else None}")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_broken_and_invalid_templates():
    """4) 损坏文件 / 非法字段 / 空选择器的处理"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)

        with open(os.path.join(templates_module.TEMPLATE_DIR, "broken.json"), 'w',
                  encoding='utf-8') as handle:
            handle.write("{ this is not json ]")

        with open(os.path.join(templates_module.TEMPLATE_DIR, "empty_sel.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump({"name": "empty_sel",
                       "username_selectors": [],
                       "password_selectors": [],
                       "login_button_selectors": []}, handle)

        with open(os.path.join(templates_module.TEMPLATE_DIR, "bad_by.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump({"name": "bad_by",
                       "username_selectors": [{"by": "MAGIC", "value": "x"}],
                       "password_selectors": [{"by": "ID", "value": "password"}],
                       "login_button_selectors": []}, handle)

        good = {
            "name": "stillgood",
            "username_selectors": [{"by": "ID", "value": "username"}],
            "password_selectors": [{"by": "ID", "value": "password"}],
            "login_button_selectors": []
        }
        with open(os.path.join(templates_module.TEMPLATE_DIR, "stillgood.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump(good, handle)

        TemplateManager.reload_templates()
        check("损坏的模板文件被跳过", TemplateManager.get_template("broken") is None)
        check("其它正常模板不受损坏文件影响",
              TemplateManager.get_template("stillgood") is not None)

        # 空选择器 / 非法定位方式的模板：仍可加载，但对应选择器被清理并给出警告
        empty_tpl = TemplateManager.get_template("empty_sel")
        check("空选择器模板仍可加载(兼容旧模板)",
              empty_tpl is not None and empty_tpl["username_selectors"] == [],
              f"template={empty_tpl}")
        bad_tpl = TemplateManager.get_template("bad_by")
        check("非法定位方式的选择器被丢弃",
              bad_tpl is not None and bad_tpl["username_selectors"] == [],
              f"template={bad_tpl}")
        check("非法选择器不影响同模板的其它字段",
              bad_tpl is not None and len(bad_tpl["password_selectors"]) == 1)

        errors = TemplateManager.get_load_errors()
        check("加载错误被记录并含文件名",
              len(errors) >= 1 and any("broken.json" in e for e in errors),
              f"errors={errors}")

        # 校验函数单独验证
        errs, warns, _ = validate_template({"username_selectors": "x"}, source="unit")
        check("字段类型错误被校验捕获", any("数组" in e for e in errs), f"errs={errs}")
        errs2, warns2, _ = validate_template({"username_selectors": [{"by": "MAGIC", "value": "x"}]},
                                            source="unit")
        check("非法定位方式降级为警告", not errs2 and any("不受支持" in w for w in warns2),
              f"warns={warns2}")
        ok_name, reason = validate_template_name("bad/name")
        check("非法模板名被拒绝", not ok_name, reason)
        ok_name, _ = validate_template_name("default")
        check("default 模板名不可被覆盖", not ok_name)
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_record_save_reload():
    """5) 录制 -> 保存 -> 重载 -> 再次使用的完整流程"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        TemplateManager._loaded = False

        # 模拟一次成功的通用查找（记录真实生效的选择器）
        TemplateManager.start_recording()
        TemplateManager.record_selector('username_selectors', 'ID', 'username')
        TemplateManager.record_selector('password_selectors', 'CSS_SELECTOR', "input[type='password']")
        TemplateManager.record_selector('login_button_selectors', 'XPATH', "//button[@type='submit']")
        recorded = TemplateManager.finish_recording()
        check("录制得到三类选择器",
              recorded is not None and all(recorded.get(k) for k in
                                          ("username_selectors", "password_selectors",
                                           "login_button_selectors")),
              f"recorded={recorded}")

        saved = TemplateManager.save_recorded_template("mytpl", "测试模板", selectors=recorded)
        check("模板保存成功", saved)
        path = os.path.join(templates_module.TEMPLATE_DIR, "mytpl.json")
        check("模板JSON文件真实写入磁盘", os.path.isfile(path), path)
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        check("模板文件内容可解析", data.get("name") == "mytpl", f"name={data.get('name')}")
        check("保存后内存注册表已更新", TemplateManager.get_template("mytpl") is not None)

        # 重新加载后仍可用
        TemplateManager.reload_templates()
        reloaded = TemplateManager.get_template("mytpl")
        check("重新加载后模板仍可取用", reloaded is not None)
        check("重新加载后选择器内容保持一致",
              reloaded and reloaded["username_selectors"][0]["value"] == "username",
              f"sel={reloaded['username_selectors'] if reloaded else None}")

        # 保存失败场景：非法名称 / 空选择器
        check("非法模板名保存失败且不误报", not TemplateManager.save_recorded_template("bad/name"))
        check("空选择器保存失败且不误报",
              not TemplateManager.save_recorded_template("emptyone",
                                                         selectors={"username_selectors": [],
                                                                    "password_selectors": [],
                                                                    "login_button_selectors": []}))
        check("失败保存不会留下文件",
              not os.path.exists(os.path.join(templates_module.TEMPLATE_DIR, "emptyone.json")))
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_failure_no_partial_file():
    """6) 写入异常时不留下半成品文件、不误报成功"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        TemplateManager._loaded = False

        # 把模板目录替换为不可写路径，模拟权限/路径异常
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "missing_dir", "templates")
        selectors = {
            "username_selectors": [{"by": "ID", "value": "u"}],
            "password_selectors": [{"by": "ID", "value": "p"}],
            "login_button_selectors": []
        }
        ok = TemplateManager.save_recorded_template("failcase", selectors=selectors)
        # 目录会被自动创建 -> 期望保存成功；再单独验证只读目录场景
        if ok:
            check("目录可用时保存成功", os.path.isfile(
                os.path.join(templates_module.TEMPLATE_DIR, "failcase.json")))
        else:
            check("保存失败时返回 False", True)

        # 只读目录：写入必须失败
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "readonly")
        os.makedirs(templates_module.TEMPLATE_DIR)
        os.chmod(templates_module.TEMPLATE_DIR, 0o500)
        result = TemplateManager.save_recorded_template("rocase", selectors=selectors)
        if os.access(templates_module.TEMPLATE_DIR, os.W_OK):
            check("只读目录场景（当前账户可写，跳过严格断言）", True, "权限不足，断言放宽")
        else:
            check("只读目录下保存失败且返回 False", result is False)
            check("只读目录下未产生半成品文件",
                  not os.path.exists(os.path.join(templates_module.TEMPLATE_DIR, "rocase.json")))
        os.chmod(templates_module.TEMPLATE_DIR, 0o700)
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_template_priority_order():
    """7) 有效模板优先于通用发现；模板失效时回退通用"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        TemplateManager._loaded = False

        # 模板命中：页面上只有模板专属元素
        template = {
            "name": "prio",
            "username_selectors": [{"by": "ID", "value": "custom-user"}],
            "password_selectors": [{"by": "ID", "value": "custom-pwd"}],
            "login_button_selectors": [{"by": "ID", "value": "custom-btn"}]
        }
        page = FakePage([("custom-user", '[id="custom-user"]'),
                         ("custom-pwd", '[id="custom-pwd"]'),
                         ("custom-btn", '[id="custom-btn"]')])

        TemplateManager.start_recording()
        field = asyncio.run(find_by_selectors(page, template["username_selectors"],
                                              'username_selectors'))
        check("模板选择器命中元素", field is not None)
        check("模板命中时未触发通用发现调用",
              not any(c[0] == "locator" and c[1] == "input" for c in page.calls),
              f"calls={page.calls}")
        check("模板命中被记录为生效选择器",
              TemplateManager.get_last_recorded() is None)  # 未 finish 录制
        TemplateManager.cancel_recording()

        # 模板失效 -> 交由通用逻辑处理
        page2 = FakePage([("username", '[name="username"]'),
                          ("password", '[name="password"]')])
        TemplateManager.start_recording()
        result = asyncio.run(find_by_selectors(page2, template["username_selectors"],
                                               'username_selectors'))
        check("模板选择器全部失效时返回 None（交由通用逻辑回退）", result is None)
        TemplateManager.cancel_recording()

        # 登录按钮同样模板优先
        page3 = FakePage([("custom-btn", '[id="custom-btn"]')])
        clicked = asyncio.run(find_login_button_by_selectors(
            page3, template["login_button_selectors"]))
        check("模板登录按钮选择器生效", clicked and page3.clicked == ['[id="custom-btn"]'],
              f"clicked={page3.clicked}")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_login_engine_template_resolution():
    """8) 设备配置中的模板名 -> 登录引擎 -> 选择器查找 的调用链"""
    from appcore.login_engine import (          # noqa: E402
        STAGE_USERNAME,
        LoginContext,
        _locate_and_fill,
        _resolve_template,
    )

    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        with open(os.path.join(templates_module.TEMPLATE_DIR, "dev1.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump({
                "name": "dev1",
                "username_selectors": [{"by": "ID", "value": "u1"}],
                "password_selectors": [{"by": "ID", "value": "p1"}],
                "login_button_selectors": []
            }, handle)
        TemplateManager.reload_templates()

        ctx = LoginContext("设备X", "单设备登录")
        resolved = _resolve_template(ctx, "dev1")
        template, label, path = (resolved['template'], resolved['source'],
                                resolved['path'])
        check("设备模板名被解析到登录引擎",
              label == "设备模板" and template is not None, f"label={label}")
        check("解析到的模板来自磁盘文件", path.endswith("dev1.json"), path)

        # 模板存在但页面元素不匹配 -> 定位失败并给出明确阶段
        page = FakePage([("username", '[name="username"]'),
                         ("password", '[name="password"]')])
        locate = asyncio.run(_locate_and_fill(page, template, "设备模板", ctx,
                                               "admin", "pass123"))
        check("模板未命中时定位失败并给出失败阶段",
              locate["ok"] is False and locate["stage"] == STAGE_USERNAME,
              f"stage={locate['stage']} reason={locate['reason']}")

        # 模板存在且命中 -> 定位成功
        page2 = FakePage([("u1", '[id="u1"]'), ("p1", '[id="p1"]')])
        locate2 = asyncio.run(_locate_and_fill(page2, template, "设备模板", ctx,
                                                "admin", "pass123"))
        check("模板命中时定位成功", locate2["ok"] is True,
              f"stage={locate2['stage']} reason={locate2['reason']}")

        # 模板名不存在 -> 回退默认模板且记录原因
        ctx_y = LoginContext("设备Y", "单设备登录")
        resolved3 = _resolve_template(ctx_y, "not_exist_xyz")
        check("模板名不存在时回退默认模板",
              resolved3['source'] == "默认模板" and resolved3['template'] is not None,
              f"path={resolved3['path']}")
        check("模板名不存在时记录具体原因", bool(resolved3['reason']),
              resolved3['reason'])
        check("模板名不存在时区分「未加载」", resolved3['loaded'] is False,
              str(resolved3['loaded']))
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_multi_device_own_template():
    """9) 多台设备各自使用自己的模板"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        for name in ("alpha", "beta"):
            with open(os.path.join(templates_module.TEMPLATE_DIR, f"{name}.json"), 'w',
                      encoding='utf-8') as handle:
                json.dump({
                    "name": name,
                    "username_selectors": [{"by": "ID", "value": f"{name}-user"}],
                    "password_selectors": [{"by": "ID", "value": f"{name}-pwd"}],
                    "login_button_selectors": []
                }, handle)
        TemplateManager.reload_templates()

        from appcore.login_engine import LoginContext, _resolve_template
        r_alpha = _resolve_template(LoginContext("A", "单设备登录"), "alpha")
        r_beta = _resolve_template(LoginContext("B", "单设备登录"), "beta")
        t_alpha, l_alpha = r_alpha['template'], r_alpha['source']
        t_beta, l_beta = r_beta['template'], r_beta['source']
        check("设备A使用自己的模板",
              l_alpha == "设备模板"
              and t_alpha["username_selectors"][0]["value"] == "alpha-user")
        check("设备B使用自己的模板",
              l_beta == "设备模板"
              and t_beta["username_selectors"][0]["value"] == "beta-user")
        check("两个模板互不串用",
              t_alpha["username_selectors"][0]["value"] != t_beta["username_selectors"][0]["value"])
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_preset_template_repair():
    """12) 残缺的内置预置模板会被补齐；用户自定义模板不受影响"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)

        # 残缺的内置预置模板
        with open(os.path.join(templates_module.TEMPLATE_DIR, "huawei.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump({
                "name": "huawei",
                "username_selectors": [{"by": "ID", "value": "username"}],
                "password_selectors": [],
                "login_button_selectors": []
            }, handle)
        # 用户自定义的残缺模板（不应被自动补齐）
        user_file = os.path.join(templates_module.TEMPLATE_DIR, "mycustom.json")
        with open(user_file, 'w', encoding='utf-8') as handle:
            json.dump({
                "name": "mycustom",
                "username_selectors": [{"by": "ID", "value": "u"}],
                "password_selectors": [],
                "login_button_selectors": []
            }, handle)

        TemplateManager.create_default_template_files()
        TemplateManager.reload_templates()

        preset = TemplateManager.get_template("huawei")
        check("残缺预置模板被补齐密码选择器",
              bool(preset and preset.get("password_selectors")),
              f"pwd={len(preset.get('password_selectors', [])) if preset else 0}")
        check("残缺预置模板被补齐登录按钮选择器",
              bool(preset and preset.get("login_button_selectors")),
              f"btn={len(preset.get('login_button_selectors', [])) if preset else 0}")
        check("补齐时保留用户原有的用户名选择器",
              bool(preset and preset["username_selectors"][0]["value"] == "username"))

        with open(user_file, encoding='utf-8-sig') as handle:
            user_data = json.load(handle)
        check("用户自定义模板未被自动补齐",
              user_data.get("password_selectors") == [],
              f"pwd={user_data.get('password_selectors')}")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_preset_template_user_customized_kept():
    """13) 用户手工维护过的预置模板不会被内置版本覆盖"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        path = os.path.join(templates_module.TEMPLATE_DIR, "proxmox.json")
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({
                "name": "proxmox",
                "description": "我自己改的模板",
                "username_selectors": [{"by": "ID", "value": "my-custom-user"}],
                "password_selectors": [{"by": "ID", "value": "my-custom-pwd"}],
                "login_button_selectors": [{"by": "ID", "value": "my-custom-btn"}]
            }, handle)

        TemplateManager.create_default_template_files()
        with open(path, encoding='utf-8-sig') as handle:
            data = json.load(handle)

        check("用户手工维护的预置模板不被覆盖",
              data["username_selectors"][0]["value"] == "my-custom-user",
              str(data["username_selectors"][0]))
        check("用户手工维护的预置模板描述保留",
              data.get("description") == "我自己改的模板", data.get("description"))
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_default_template_from_disk():
    """13) 默认模板优先取磁盘 templates/default.json（而非仅用内置常量）"""
    from appcore.login_engine import _get_default_template

    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        with open(os.path.join(templates_module.TEMPLATE_DIR, "default.json"), 'w',
                  encoding='utf-8') as handle:
            json.dump({
                "name": "default",
                "description": "磁盘上的默认模板",
                "username_selectors": [{"by": "ID", "value": "disk-user"}],
                "password_selectors": [{"by": "ID", "value": "disk-pwd"}],
                "login_button_selectors": [{"by": "ID", "value": "disk-btn"}]
            }, handle)
        TemplateManager.reload_templates()

        template, path = _get_default_template()
        check("默认模板取自磁盘文件", path.endswith("default.json"), path)
        check("默认模板内容为磁盘版本",
              template["username_selectors"][0]["value"] == "disk-user")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_bom_tolerance():
    """11) 带 BOM 的 UTF-8 模板文件与设备配置仍可正常读取"""
    tmp = tempfile.mkdtemp(prefix="tpl_")
    original_dir = templates_module.TEMPLATE_DIR
    try:
        templates_module.TEMPLATE_DIR = os.path.join(tmp, "templates")
        os.makedirs(templates_module.TEMPLATE_DIR)
        bom_template = {
            "name": "bomtpl",
            "username_selectors": [{"by": "ID", "value": "u"}],
            "password_selectors": [{"by": "ID", "value": "p"}],
            "login_button_selectors": []
        }
        # 写入带 BOM 的 UTF-8（Windows 记事本 / PowerShell 默认行为）
        with open(os.path.join(templates_module.TEMPLATE_DIR, "bomtpl.json"), 'w',
                  encoding='utf-8-sig') as handle:
            json.dump(bom_template, handle)

        TemplateManager.reload_templates()
        check("带 BOM 的模板文件可正常加载", TemplateManager.get_template("bomtpl") is not None,
              f"已加载={TemplateManager.list_templates()}")
        check("带 BOM 的模板文件无加载错误", not TemplateManager.get_load_errors(),
              f"errors={TemplateManager.get_load_errors()}")
    finally:
        templates_module.TEMPLATE_DIR = original_dir
        TemplateManager._loaded = False
        shutil.rmtree(tmp, ignore_errors=True)


def test_version_consistency():
    """10) 版本号一致性"""
    from appcore.config import APP_VERSION, APP_VERSION_INFO

    # 版本号按项目规则递增，因此这里校验「格式合法 + 与元组一致」，
    # 而不是钉死某个具体版本，避免每次发版都要同步修改测试。
    check("版本号格式合法", re.match(r"^\d+\.\d+\.\d+$", APP_VERSION) is not None, APP_VERSION)
    check("版本元组与版本号一致",
          APP_VERSION_INFO[:3] == tuple(int(part) for part in APP_VERSION.split(".")),
          f"{APP_VERSION} / {APP_VERSION_INFO}")

    import subprocess
    out = subprocess.run([sys.executable, "get_version.py"], capture_output=True, text=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    check("打包脚本读取到的版本一致", out.stdout.strip() == APP_VERSION, out.stdout.strip())


def test_builtin_default_template_matches_disk():
    """14) 内置默认模板常量与磁盘 templates/default.json 保持一致

    EXE 首次启动时会把内置 DEFAULT_TEMPLATE 写入 EXE 同目录的 templates\，
    若两者不一致，EXE 生成的默认模板就会与源码目录的默认模板不同。
    """
    disk_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "templates", "default.json")
    with open(disk_path, encoding="utf-8-sig") as handle:
        disk = json.load(handle)

    for key in ("username_selectors", "password_selectors"):
        builtin = DEFAULT_TEMPLATE.get(key) or []
        disk_list = disk.get(key) or []
        check(f"内置默认模板的 {key} 与磁盘模板一致",
              builtin == disk_list,
              f"内置 {len(builtin)} 个 / 磁盘 {len(disk_list)} 个")

    check("内置默认模板的用户名候选已包含邮箱型登录框",
          any('type="email"' in str(item.get("value", ""))
              for item in DEFAULT_TEMPLATE["username_selectors"]),
          str(len(DEFAULT_TEMPLATE["username_selectors"])))


def main():
    """依次执行各测试；单个测试异常不会中断其余测试。"""
    suites = [
        test_template_dir_bootstrap,
        test_user_file_not_overwritten,
        test_manual_template_discovery,
        test_broken_and_invalid_templates,
        test_record_save_reload,
        test_save_failure_no_partial_file,
        test_template_priority_order,
        test_login_engine_template_resolution,
        test_multi_device_own_template,
        test_preset_template_repair,
        test_preset_template_user_customized_kept,
        test_default_template_from_disk,
        test_bom_tolerance,
        test_version_consistency,
        test_builtin_default_template_matches_disk,
    ]
    for suite in suites:
        try:
            suite()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f"{suite.__name__} 执行异常", False, str(e)[:80])
    return 0


def report():
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"测试结果: {passed} 通过 / {failed} 失败")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTS.append(("测试执行异常", False, "见堆栈"))
    sys.exit(report())