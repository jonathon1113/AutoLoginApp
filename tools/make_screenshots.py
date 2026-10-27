# -*- coding: utf-8 -*-
"""生成 README / docs 使用的界面截图（脱敏数据，不含任何真实设备信息）。

用法::

    python tools/make_screenshots.py

要点：
1. 使用 Qt 的 ``offscreen`` 平台，**无需真实显示器**，CI 也能跑；
2. 设备数据全部为**虚构示例**（RFC 5737 保留网段 / RFC 2606 保留域名），
   截图里不会出现任何真实内网地址、设备名或凭据；
3. 产物写入 ``docs/screenshots/``，文件名带版本号。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '0')

from PyQt6.QtGui import QFont, QFontDatabase     # noqa: E402
from PyQt6.QtWidgets import QApplication          # noqa: E402

from appcore.config import APP_VERSION              # noqa: E402

OUT_DIR = os.path.join(ROOT, 'docs', 'screenshots')

# Qt 的 offscreen 平台**不接入系统字体库**（字体族数量为 0），
# 中文会渲染成方块。这里显式把 Windows 中文字体注册进应用字体库。
_FONT_FILES = (
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\simsun.ttc',
    r'C:\Windows\Fonts\segoeui.ttf',
)


def _bootstrap_fonts(app):
    """注册中文字体并设为应用默认字体（offscreen 必需）。"""
    for path in _FONT_FILES:
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    font = QFont()
    font.setFamilies(['Microsoft YaHei UI', 'Microsoft YaHei', 'SimHei', 'SimSun'])
    font.setPointSizeF(9.5)
    app.setFont(font)
    print('已注册字体族数：%d' % len(QFontDatabase.families()))

# ---------------------------------------------------------------- 虚构设备数据
SAMPLE_DEVICES = {
    'A组-虚拟化': [
        {'name': '示例虚拟化主机 01', 'url': 'http://192.0.2.10:8006/login',
         'group': 'A组-虚拟化', 'template': 'proxmox'},
        {'name': '示例虚拟化主机 02', 'url': 'http://192.0.2.11:8006/login',
         'group': 'A组-虚拟化', 'template': 'proxmox'},
    ],
    'B组-网关设备': [
        {'name': '示例网关设备', 'url': 'https://192.0.2.20:8443/login',
         'group': 'B组-网关设备', 'template': 'huawei'},
    ],
    'C组-云服务': [
        {'name': '示例云服务控制台', 'url': 'https://console.example.com/login',
         'group': 'C组-云服务', 'template': 'default'},
        {'name': '示例对象存储', 'url': 'https://storage.example.com/login',
         'group': 'C组-云服务', 'template': 'default'},
    ],
}

SAMPLE_LOGS = [
    ('INFO', '已加载 3 个分组，共 5 台设备'),
    ('INFO', '示例虚拟化主机 01：配置模板=proxmox'),
    ('INFO', '示例虚拟化主机 01：设备模板用户名选择器命中，耗时=14ms'),
    ('SUCCESS', '示例虚拟化主机 01：登录成功，总耗时=93ms'),
    ('WARNING', '示例网关设备：页面存在验证码字段，等待人工确认'),
]


def _patch_device_loader():
    """把设备加载替换为虚构数据，避免真实 devices.json 进入截图。"""
    import appcore.devices as devices_mod
    import appcore.tasks as tasks_mod

    def _fake_load():
        return {g: list(ds) for g, ds in SAMPLE_DEVICES.items()}

    devices_mod.load_devices = _fake_load
    if hasattr(tasks_mod, 'load_devices'):
        tasks_mod.load_devices = _fake_load


def _save(widget, filename):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)
    if not widget.grab().save(path, 'PNG'):
        raise RuntimeError('截图保存失败：%s' % path)
    print('已生成 %s' % os.path.relpath(path, ROOT).replace(os.sep, '/'))


def _capture_dialog(app, win, kind, filename):
    """弹出一个对话框并截图（不真正阻塞）。"""
    from PyQt6.QtWidgets import QDialog

    from appui.ui_kit import MessageBox

    captured = []

    def _fake_exec(self):
        captured.append(self)
        return 0

    original_exec = QDialog.exec
    QDialog.exec = _fake_exec
    try:
        if kind == 'help':
            win.show_help()
        elif kind == 'about':
            win.show_about()
        else:
            box = MessageBox(
                '登录结果',
                '示例网关设备：登录失败\n\n'
                '默认模板用户名选择器未命中（Form not found）\n'
                '用户名查找超出耗时预算，剩余 11 个候选未尝试\n'
                '候选总数=23，实际开始执行=7，执行完成=7，'
                '因预算不足未执行=16\n'
                '分类累计耗时=absent=2734ms，退出原因=budget_exceeded，'
                '不完整查找=是',
                win)
            box.set_icon('error')
            box.yesButton.setText('确定')
            box.show()
            captured.append(box)
        app.processEvents()
        if not captured:
            raise RuntimeError('未捕获到对话框：%s' % kind)
        dialog = captured[-1]
        dialog.show()
        app.processEvents()
        _save(dialog, filename)
        dialog.close()
    finally:
        QDialog.exec = original_exec


def main():
    app = QApplication(sys.argv)
    _bootstrap_fonts(app)
    _patch_device_loader()

    from appui.main_window import LoginWindow
    from appui.ui_kit import InfoBar

    win = LoginWindow()
    win.resize(1180, 720)
    win.show()
    app.processEvents()

    # 注入虚构设备并刷新界面
    win.on_devices_loaded(SAMPLE_DEVICES)
    app.processEvents()

    for level, text in SAMPLE_LOGS:
        win.log_text.addItem(text)
    app.processEvents()

    tag = 'V%s' % APP_VERSION
    _save(win, '%s_主窗口.png' % tag)

    # 设备列表（右侧设备列表控件）
    win.device_list.setFixedHeight(220)
    app.processEvents()
    _save(win.device_list, '%s_设备列表.png' % tag)

    # 日志区
    win.log_text.setFixedHeight(150)
    app.processEvents()
    _save(win.log_text, '%s_日志区.png' % tag)

    # 消息条
    InfoBar.success(title='导入完成', content='已导入 5 台设备（示例数据）',
                   position='top', duration=0, parent=win)
    app.processEvents()
    _save(win, '%s_消息条.png' % tag)

    # 对话框
    _capture_dialog(app, win, 'help', '%s_对话框_超长帮助.png' % tag)
    _capture_dialog(app, win, 'about', '%s_对话框_短文本.png' % tag)
    _capture_dialog(app, win, 'result', '%s_对话框_长文本.png' % tag)

    win.close()
    app.processEvents()


if __name__ == '__main__':
    main()
