"""配置刷新与默认模板维护测试。

覆盖任务书 8.3 的场景：
- 修改 devices.json 并刷新；
- 修改默认模板并刷新；
- 修改设备专属模板并刷新；
- 新增模板并刷新；
- 删除模板并刷新；
- 使用无效 JSON 刷新，确认旧配置得到保护；
- 追加选择器后「重启」，确认修改保留；
- 验证默认模板和设备模板不会相互覆盖。

所有用例都在独立的临时目录中运行（临时 devices.json + 临时 templates/），
不会读写用户真实的数据文件。

运行： python tests/test_config_refresh.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from PyQt6.QtCore import QEventLoop          # noqa: E402
from PyQt6.QtGui import QAction             # noqa: E402
from PyQt6.QtWidgets import QApplication     # noqa: E402

from appcore import devices as device_store   # noqa: E402
from appcore import templates as templates_mod        # noqa: E402
from appcore.templates import TemplateManager          # noqa: E402
from appui import main_window as main_window_mod      # noqa: E402
from appui.main_window import LoginWindow              # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def wait_until(predicate, timeout=30, interval=0.05):
    app = QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        if predicate():
            return True
        time.sleep(interval)
    return False


DEFAULT_TEMPLATE = {
    "name": "default",
    "description": "默认模板",
    "username_selectors": [
        {"by": "CSS_SELECTOR", "value": "input[name=\"username\"]"},
    ],
    "password_selectors": [
        {"by": "CSS_SELECTOR", "value": "input[type=\"password\"]"},
    ],
    "login_button_selectors": [
        {"by": "CSS_SELECTOR", "value": "button[type=\"submit\"]"},
    ],
    "captcha_selectors": [],
}

DEV_TEMPLATE = {
    "name": "dev1",
    "description": "设备专属模板",
    "username_selectors": [
        {"by": "ID", "value": "devUser"},
    ],
    "password_selectors": [
        {"by": "ID", "value": "devPass"},
    ],
    "login_button_selectors": [
        {"by": "ID", "value": "devLogin"},
    ],
    "captcha_selectors": [],
}

DEVICES_V1 = [
    {"name": "设备A", "url": "http://192.0.2.31", "username": "a", "password": "p",
     "group": "A组", "template": "dev1"},
    {"name": "设备B", "url": "http://192.0.2.32", "username": "b", "password": "p",
     "group": "A组", "template": ""},
]

DEVICES_V2 = [
    {"name": "设备A", "url": "http://192.0.2.31", "username": "a", "password": "p",
     "group": "A组", "template": "dev1"},
    {"name": "设备C", "url": "http://192.0.2.33", "username": "c", "password": "p",
     "group": "B组", "template": ""},
    {"name": "设备D", "url": "http://192.0.2.34", "username": "d", "password": "p",
     "group": "B组", "template": ""},
]


class TempEnv:
    """把设备配置与模板目录指向临时目录，避免污染真实用户数据"""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='loginapp_cfg_')
        self.template_dir = os.path.join(self.root, 'templates')
        os.makedirs(self.template_dir, exist_ok=True)
        self.config_file = os.path.join(self.root, 'devices.json')
        self._saved = []

    def __enter__(self):
        self._saved = [
            (device_store, 'CONFIG_FILE', device_store.CONFIG_FILE),
            (templates_mod, 'TEMPLATE_DIR', templates_mod.TEMPLATE_DIR),
            (main_window_mod, 'CONFIG_FILE', main_window_mod.CONFIG_FILE),
            (main_window_mod, 'TEMPLATE_DIR', main_window_mod.TEMPLATE_DIR),
        ]
        device_store.CONFIG_FILE = self.config_file
        templates_mod.TEMPLATE_DIR = self.template_dir
        main_window_mod.CONFIG_FILE = self.config_file
        main_window_mod.TEMPLATE_DIR = self.template_dir
        return self

    def __exit__(self, *exc):
        for module, name, value in self._saved:
            setattr(module, name, value)
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    # ---------- 文件写入辅助 ----------
    def write_devices(self, devices):
        with open(self.config_file, 'w', encoding='utf-8') as handle:
            json.dump(devices, handle, indent=2, ensure_ascii=False)

    def write_raw_devices(self, text):
        with open(self.config_file, 'w', encoding='utf-8') as handle:
            handle.write(text)

    def write_template(self, filename, data):
        with open(os.path.join(self.template_dir, filename), 'w',
                  encoding='utf-8') as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    def write_raw_template(self, filename, text):
        with open(os.path.join(self.template_dir, filename), 'w',
                  encoding='utf-8') as handle:
            handle.write(text)

    def read_template(self, filename):
        with open(os.path.join(self.template_dir, filename), 'r',
                  encoding='utf-8-sig') as handle:
            return json.load(handle)

    def template_path(self, filename):
        return os.path.join(self.template_dir, filename)

    def remove_template(self, filename):
        path = self.template_path(filename)
        if os.path.exists(path):
            os.remove(path)


def _username_values(template):
    return [item.get('value') for item in (template or {}).get('username_selectors') or []]


def run_scenarios(env, window):
    # ============ 初始状态 ============
    groups = device_store.get_groups()
    check("初始：设备配置已加载（1 组 2 台）",
          len(groups) == 1 and len(groups.get('A组', [])) == 2,
          f"分组={list(groups.keys())}")
    check("初始：默认模板已加载", TemplateManager.get_template('default') is not None)
    check("初始：设备专属模板已加载", TemplateManager.get_template('dev1') is not None)

    # ============ 场景 1：修改 devices.json 并刷新 ============
    env.write_devices(DEVICES_V2)
    window.on_refresh()
    groups = device_store.get_groups()
    check("1 修改 devices.json 后刷新生效",
          len(groups) == 2 and len(groups.get('B组', [])) == 2,
          f"分组={list(groups.keys())}")
    check("1 界面统计同步更新",
          '2 个分组' in window.stat_label.text(), window.stat_label.text())
    check("1 设备列表已重建", window.device_list.count() == 3,
          str(window.device_list.count()))

    # ============ 场景 2：修改默认模板并刷新 ============
    modified_default = json.loads(json.dumps(DEFAULT_TEMPLATE))
    modified_default['username_selectors'].append(
        {"by": "CSS_SELECTOR", "value": "input[autocomplete=\"username\"]"})
    env.write_template('default.json', modified_default)
    window.on_refresh()
    values = _username_values(TemplateManager.get_template('default'))
    check("2 修改默认模板后刷新生效",
          'input[autocomplete="username"]' in values, str(values))

    # ============ 场景 3：修改设备专属模板并刷新 ============
    modified_dev = json.loads(json.dumps(DEV_TEMPLATE))
    modified_dev['username_selectors'].append({"by": "NAME", "value": "devUserName"})
    env.write_template('dev1.json', modified_dev)
    window.on_refresh()
    dev_values = _username_values(TemplateManager.get_template('dev1'))
    check("3 修改设备专属模板后刷新生效", 'devUserName' in dev_values, str(dev_values))

    # ============ 场景 4：新增模板并刷新 ============
    new_template = json.loads(json.dumps(DEV_TEMPLATE))
    new_template['name'] = 'brandnew'
    env.write_template('brandnew.json', new_template)
    window.on_refresh()
    check("4 新增模板后刷新可见",
          'brandnew' in TemplateManager.list_templates(),
          str(TemplateManager.list_templates()))

    # ============ 场景 5：删除模板并刷新 ============
    env.remove_template('brandnew.json')
    window.on_refresh()
    check("5 删除模板后刷新不可见",
          'brandnew' not in TemplateManager.list_templates(),
          str(TemplateManager.list_templates()))

    # ============ 场景 6：无效 JSON 刷新 -> 旧配置保留 ============
    before_groups = {k: len(v) for k, v in device_store.get_groups().items()}
    before_default = _username_values(TemplateManager.get_template('default'))
    env.write_raw_devices('{ this is not valid json ')
    window.on_refresh()
    after_groups = {k: len(v) for k, v in device_store.get_groups().items()}
    check("6 设备配置非法时保留上一次有效配置", after_groups == before_groups,
          f"之前={before_groups} 之后={after_groups}")
    check("6 刷新失败有明确提示",
          '刷新失败' in window.stat_label.text(), window.stat_label.text())
    check("6 界面未清空（设备列表仍在）", window.device_list.count() == 3,
          str(window.device_list.count()))

    # 设备配置修好后可以再次刷新
    env.write_devices(DEVICES_V2)
    window.on_refresh()
    check("6 修复文件后可再次刷新成功",
          len(device_store.get_groups()) == 2, str(list(device_store.get_groups())))

    # 模板文件非法时同样保留旧配置
    env.write_raw_template('default.json', '{ broken json')
    window.on_refresh()
    check("6 模板非法时保留上一次有效默认模板",
          _username_values(TemplateManager.get_template('default')) == before_default,
          str(_username_values(TemplateManager.get_template('default'))))
    check("6 模板非法时界面提示刷新失败",
          '刷新失败' in window.stat_label.text(), window.stat_label.text())
    env.write_template('default.json', modified_default)
    window.on_refresh()

    # ============ 场景 7：追加选择器后「重启」仍保留 ============
    new_selector = {"by": "CSS_SELECTOR", "value": "input#appended_user"}
    ok, message, detail = TemplateManager.append_selectors_to_default(
        {'username_selectors': [new_selector]})
    check("7 追加选择器成功", ok, message)
    check("7 追加结果给出新增条数",
          (detail.get('added') or {}).get('username_selectors') == 1, str(detail))
    on_disk = env.read_template('default.json')
    check("7 文件中已写入追加的选择器",
          'input#appended_user' in _username_values(on_disk),
          str(_username_values(on_disk)))

    # 模拟重启：模板管理器完全重新读盘
    TemplateManager._loaded = False
    TemplateManager.load_templates(force=True)
    check("7 重启后追加的选择器仍在",
          'input#appended_user' in _username_values(TemplateManager.get_template('default')),
          str(_username_values(TemplateManager.get_template('default'))))
    check("7 重启后原有选择器未被删除",
          'input[name="username"]' in _username_values(TemplateManager.get_template('default')),
          str(_username_values(TemplateManager.get_template('default'))))

    # 追加重复选择器不应重复写入
    ok, message, detail = TemplateManager.append_selectors_to_default(
        {'username_selectors': [new_selector]})
    check("7 重复追加不会重复写入",
          (detail.get('skipped') or {}).get('username_selectors') == 1, str(detail))

    # 角色冲突的选择器不允许写入默认模板
    ok, message, detail = TemplateManager.append_selectors_to_default(
        {'username_selectors': [{"by": "CSS_SELECTOR",
                                "value": "input[type=\"password\"]"}]})
    check("7 角色冲突的选择器被拒绝写入",
          not (detail.get('added') or {}).get('username_selectors')
          and bool(detail.get('rejected')), str(detail))

    # ============ 场景 8：默认模板与设备模板互不覆盖 ============
    dev_before = env.read_template('dev1.json')
    ok, message, detail = TemplateManager.merge_template_into_default('dev1')
    check("8 合并设备模板到默认模板成功", ok, message)
    dev_after = env.read_template('dev1.json')
    check("8 合并不会改写设备专属模板文件", dev_before == dev_after)
    default_values = _username_values(TemplateManager.get_template('default'))
    check("8 合并后默认模板包含双方选择器",
          'devUser' in default_values and 'input#appended_user' in default_values,
          str(default_values))
    check("8 合并后设备模板内容保持不变",
          _username_values(TemplateManager.get_template('dev1'))
          == _username_values(dev_before), str(_username_values(dev_before)))

    # 设备模板被修改时，默认模板不受影响
    default_before = env.read_template('default.json')
    changed_dev = json.loads(json.dumps(dev_before))
    changed_dev['username_selectors'].append({"by": "NAME", "value": "only_in_dev"})
    env.write_template('dev1.json', changed_dev)
    window.on_refresh()
    check("8 修改设备模板不影响默认模板文件",
          env.read_template('default.json') == default_before)
    check("8 修改设备模板后默认模板内容不变",
          'only_in_dev' not in _username_values(TemplateManager.get_template('default')))

    # ============ 附加：默认模板维护入口存在 ============
    for method in ('on_append_to_default_template', 'on_merge_into_default_template',
                   'on_replace_default_template'):
        check(f"附加：界面提供「{method}」入口",
              callable(getattr(window, method, None)))
    actions = [action.text() for action in window.findChildren(QAction)]
    check("附加：菜单中存在「追加当前选择器到默认模板」",
          '追加当前选择器到默认模板' in actions, str(actions))
    check("附加：菜单中存在「合并指定模板到默认模板...」",
          '合并指定模板到默认模板...' in actions, str(actions))
    check("附加：菜单中存在「用内置版本替换默认模板...」",
          '用内置版本替换默认模板...' in actions, str(actions))


def run_role_mapping_scenarios(env, window):
    """模板字段 <-> 元素角色的静态映射校验（任务书 2.3 / 6.2 / 7.1）。

    校验三层行为：
    - 加载期：角色冲突只给警告，不阻断模板使用；
    - 整体替换：角色冲突直接拒绝写入（不破坏原文件）；
    - 追加：只拦“本次新增”的选择器，模板里原有内容不阻塞追加。
    """
    risky = json.loads(json.dumps(DEFAULT_TEMPLATE))
    risky['name'] = 'risky'
    risky['username_selectors'].append({"by": "CSS_SELECTOR",
                                        "value": "input[type=\"password\"]"})

    # ---- 加载期：警告而非致命错误 ----
    env.write_template('risky.json', risky)
    TemplateManager.reload_templates()
    check("9 角色冲突的模板仍可加载（只警告不阻断）",
          TemplateManager.get_template('risky') is not None)
    errors, warnings, _normalized = templates_mod.validate_template(risky)
    check("9 校验结果给出角色冲突警告",
          any('密码框' in w for w in warnings), str(warnings))
    check("9 角色冲突不产生致命错误", not errors, str(errors))
    _e2, w2, _n2 = templates_mod.validate_template(risky, check_roles=False)
    check("9 check_roles=False 可关闭角色检查", not any('密码框' in w for w in w2),
          str(w2))

    # ---- 整体替换：角色冲突必须被拒绝，且不破坏原文件 ----
    before = env.read_template('default.json')
    ok, message = TemplateManager.replace_default_template(risky)
    check("9 整体替换拒绝角色冲突的选择器", not ok, message)
    check("9 拒绝时提示里含具体字段与选择器",
          'username_selectors' in message and 'password' in message, message)
    check("9 拒绝时默认模板文件未被破坏",
          env.read_template('default.json') == before)

    # ---- 整体替换（内置版本）应成功 ----
    ok, message = TemplateManager.replace_default_template()
    check("9 用内置版本整体替换默认模板成功", ok, message)
    built_in_values = _username_values(env.read_template('default.json'))
    check("9 替换后内置用户名候选已落盘",
          'input[autocomplete="username"]' in built_in_values, str(built_in_values))
    check("9 替换后内存与磁盘一致",
          _username_values(TemplateManager.get_template('default')) == built_in_values)

    # ---- 追加：只拦本次新增，模板原有内容不阻塞追加 ----
    mixed = json.loads(json.dumps(DEFAULT_TEMPLATE))
    mixed['username_selectors'].append({"by": "CSS_SELECTOR",
                                        "value": "input[type=\"password\"]"})
    env.write_template('default.json', mixed)
    TemplateManager.reload_templates()
    ok, message, detail = TemplateManager.append_selectors_to_default(
        {'username_selectors': [{"by": "CSS_SELECTOR", "value": "input#added_ok"}]})
    check("9 追加不被模板原有内容中的角色冲突选择器阻塞", ok, message)
    check("9 追加确实写入新选择器",
          (detail.get('added') or {}).get('username_selectors') == 1, str(detail))
    on_disk = _username_values(env.read_template('default.json'))
    check("9 追加后原有选择器仍在（含被警告的那条）",
          'input[type="password"]' in on_disk, str(on_disk))
    check("9 追加后新选择器已落盘", 'input#added_ok' in on_disk, str(on_disk))

    # ---- 密码 / 按钮字段的映射检查 ----
    swapped = json.loads(json.dumps(DEFAULT_TEMPLATE))
    swapped['login_button_selectors'].append({"by": "CSS_SELECTOR",
                                              "value": "input[type=\"password\"]"})
    _e3, w3, _n3 = templates_mod.validate_template(swapped)
    check("9 登录按钮候选里的密码框被识别为角色冲突",
          any('密码框' in w and 'login_button_selectors' in w for w in w3), str(w3))
    swapped['login_button_selectors'] = [{"by": "CSS_SELECTOR",
                                          "value": "input[type=\"text\"]"}]
    _e4, w4, _n4 = templates_mod.validate_template(swapped)
    check("9 登录按钮候选里的普通输入框被识别为角色冲突",
          any('输入框' in w and 'login_button_selectors' in w for w in w4), str(w4))
    captcha_mix = json.loads(json.dumps(DEFAULT_TEMPLATE))
    captcha_mix['username_selectors'].append({"by": "CSS_SELECTOR",
                                              "value": "input[name=\"captcha\"]"})
    _e5, w5, _n5 = templates_mod.validate_template(captcha_mix)
    check("9 用户名候选里的验证码框被识别为角色冲突",
          any('验证码' in w for w in w5), str(w5))
    check("9 正常模板无角色冲突警告",
          not templates_mod.validate_template(DEFAULT_TEMPLATE)[1],
          str(templates_mod.validate_template(DEFAULT_TEMPLATE)[1]))


def run_preset_template_scenarios(env, window):
    """预置模板不得被启动流程反复改写（任务书 6.1）。"""
    # ---- 内置预置模板必须包含全部字段 ----
    # 若内置版本缺某个字段，启动时的“补齐缺失字段”会把用户的预置模板文件改写一次。
    for filename, preset in templates_mod.PRESET_TEMPLATES.items():
        missing = [f for f in templates_mod.ALL_TEMPLATE_FIELDS if f not in preset]
        check(f"10 内置预置模板 {filename} 包含全部字段", not missing, str(missing))

    # ---- 首次创建后，再次启动不得改写 ----
    templates_mod.TemplateManager.create_default_template_files()
    snapshot = {}
    for filename in os.listdir(env.template_dir):
        path = env.template_path(filename)
        with open(path, 'rb') as handle:
            snapshot[filename] = (handle.read(), os.path.getmtime(path))
    time.sleep(0.05)
    templates_mod.TemplateManager.create_default_template_files()
    unchanged = True
    for filename, (data, mtime) in snapshot.items():
        path = env.template_path(filename)
        with open(path, 'rb') as handle:
            same_data = handle.read() == data
        same_mtime = abs(os.path.getmtime(path) - mtime) < 1e-6
        if not (same_data and same_mtime):
            unchanged = False
    check("10 再次启动不写盘（内容与修改时间都不变）", unchanged, str(list(snapshot)))

    # ---- 用户手工修改过的预置模板不被内置版本覆盖 ----
    path = env.template_path('proxmox.json')
    with open(path, 'r', encoding='utf-8-sig') as handle:
        manual = json.load(handle)
    manual['username_selectors'] = list(manual.get('username_selectors') or []) + [
        {"by": "CSS_SELECTOR", "value": "input#manual_keep"}]
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(manual, handle, indent=2, ensure_ascii=False)
    templates_mod.TemplateManager.create_default_template_files()
    with open(path, 'r', encoding='utf-8-sig') as handle:
        after = json.load(handle)
    check("10 用户手工添加的选择器不被内置版本覆盖",
          'input#manual_keep' in [s.get('value') for s in after.get('username_selectors') or []],
          str([s.get('value') for s in after.get('username_selectors') or []]))


def main():
    app = QApplication(sys.argv)
    started = time.monotonic()
    with TempEnv() as env:
        env.write_devices(DEVICES_V1)
        env.write_template('default.json', DEFAULT_TEMPLATE)
        env.write_template('dev1.json', DEV_TEMPLATE)
        TemplateManager.reload_templates()
        device_store.set_groups(device_store.load_devices())

        window = LoginWindow()
        try:
            wait_until(lambda: window.devices_loaded)
            run_scenarios(env, window)
            run_role_mapping_scenarios(env, window)
            run_preset_template_scenarios(env, window)
        finally:
            try:
                window.close()
            except Exception:
                pass

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"配置刷新与默认模板测试: {passed} 通过 / {failed} 失败"
          f"（总耗时 {int((time.monotonic() - started) * 1000)}ms）")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
