"""测试用本地模拟登录服务器。

提供以下页面：
- /login      登录表单（用户名/密码/登录按钮）
- /do_login   处理登录：用户名 admin + 密码 pass123 成功，其余返回错误提示
- /dashboard  登录成功后的页面
- /captcha    带验证码输入框的登录页
- /captcha_ocr 带图片验证码的登录页（4 位数字+大小写字母，服务端不区分大小写）
- /slow       响应较慢的页面（用于超时/等待测试）
- /dedicated  专用选择器页面（id=devUser/devPass/devLogin，通用模板无法命中）
- /generic    通用登录页面（name=username/password，通用模板可命中）
- /nologin    标题像登录页但没有任何表单
- /slowjs     DOM 先出来、输入框由 JS 延迟渲染的页面
- /frame      登录表单位于 iframe 中的页面
- /sample/*   五组真实登录页面 HTML 样例（q-input / form.userID /
              UserName+UserPasswd / loginName+password+checkCode / Ant Design+Angular）
"""

import io
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

LOGIN_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>设备登录</title></head>
<body>
  <h1>设备登录</h1>
  <form id="loginForm" method="POST" action="/do_login">
    <input type="text" id="username" name="username" placeholder="请输入用户名">
    <input type="password" id="password" name="password" placeholder="请输入密码">
    <button type="submit" id="loginBtn">登录</button>
  </form>
</body></html>
"""

CAPTCHA_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>验证码登录</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" id="username" name="username" placeholder="用户名">
    <input type="password" id="password" name="password" placeholder="密码">
    <input type="text" id="captcha" name="captcha" placeholder="验证码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# ============ 验证码错误后「清空账号密码」的页面 ============
CAPTCHA_CLEAR_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>验证码错误清空表单</title></head>
<body>
  <h1>验证码错误清空表单</h1>
  {error_block}
  <form method="POST" action="/do_login_clear">
    <input type="text" id="username" name="username" placeholder="用户名"
           value="{username}">
    <input type="password" id="password" name="password" placeholder="密码"
           value="{password}">
    <input type="text" id="captcha" name="captcha" placeholder="验证码">
    <img id="captchaImg" alt="验证码" src="/captcha_clear_img">
    <button type="submit" id="loginBtn">登录</button>
  </form>
</body></html>
"""


# ============ 「怪异占位符 + check-code 图片」页面 ============
# 用户反馈：这个页面在加入验证码识别之前能登录，之后账号/密码/验证码框都定位不到。
# 注意占位符是随机串（K5 / 114 / 2iEb4），不是「用户名/密码/验证码」。
WEIRD_PLACEHOLDER_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>怪异占位符登录</title></head>
<body>
  <form method="POST" action="/do_login_weird">
    <input tabindex="1" type="text" autocomplete="off" placeholder="K5"
           name="username" class="el-input_inner">
    <input tabindex="2" type="password" autocomplete="off" placeholder="114"
           name="password" class="el-input inner">
    <input tabindex="3" type="text" autocomplete="off" placeholder="2iEb4"
           name="captcha" class="el-input_inner">
    <img data-v-198e4561="" draggable="false"
         src="/captcha_weird_img" alt="Ab4" class="check-code">
    <button type="submit">登录</button>
  </form>
</body></html>
"""


# ============ 内联 SVG 验证码页面（el-input / vue 风格）============
CAPTCHA_SVG_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SVG 验证码登录</title></head>
<body>
  <h1>SVG 验证码登录</h1>
  {error_block}
  <form method="POST" action="/do_login_svg">
    <input type="text" id="username" name="username" placeholder="用户名">
    <input type="password" id="password" name="password" placeholder="密码">
    <div class="code-content" data-v-9574f9a0>
      <svg xmlns="http://www.w3.org/2000/svg" width="150" height="50"
           viewBox="0 0 150 50">
        <rect width="100%" height="100%" fill="#ffffff"/>
        {glyphs}
      </svg>
    </div>
    <input class="el-input__inner" id="captcha" name="captcha" type="text"
           autocomplete="off" placeholder="验证码">
    <button class="el-button" type="submit" id="loginBtn">登录</button>
  </form>
</body></html>
"""


def svg_glyphs(code):
    """把 4 位验证码渲染成 SVG <text> 元素（模拟站点用 <path> 的写法）。"""
    parts = []
    for index, char in enumerate(code):
        parts.append(
            '<text x="%d" y="38" font-size="30" font-family="Arial" '
            'fill="#73635a">%s</text>' % (10 + index * 35, char))
    return ''.join(parts)


DASHBOARD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>控制台</title></head>
<body><h1>控制台</h1><p id="welcome">欢迎回来</p></body></html>
"""

# ============ 图片验证码（4 位数字 + 大小写字母）============
# 服务端不区分大小写：form["captcha"].upper() == CODE.upper()
CAPTCHA_CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 生成验证码图片时使用的字体候选（Windows 自带字体优先）
_CAPTCHA_FONT_PATHS = (
    r'C:\Windows\Fonts\arialbd.ttf',
    r'C:\Windows\Fonts\arial.ttf',
    r'C:\Windows\Fonts\consola.ttf',
    r'C:\Windows\Fonts\couriernew.ttf',
)


def _captcha_font(size):
    """取一个可用的验证码字体（找不到 TrueType 时退回 Pillow 默认字体）。"""
    from PIL import ImageFont
    for path in _CAPTCHA_FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_captcha_png(code, width=120, height=40):
    """生成带干扰线与噪点的验证码图片（PNG 字节）。

    不依赖任何外部资源，纯 Pillow 绘制。
    """
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(image)

    # 干扰线 1~3 条
    for _ in range(random.randint(1, 3)):
        color = (random.randint(120, 220), random.randint(120, 220),
                 random.randint(120, 220))
        draw.line([(random.randint(0, width), random.randint(0, height)),
                   (random.randint(0, width), random.randint(0, height))],
                  fill=color, width=random.randint(1, 2))

    # 少量噪点
    for _ in range(random.randint(20, 60)):
        draw.point((random.randint(0, width - 1), random.randint(0, height - 1)),
                   fill=(random.randint(0, 255), random.randint(0, 255),
                         random.randint(0, 255)))

    # 字符（轻微旋转 + 随机位置）
    step = max(8, width // (len(code) + 1))
    for index, char in enumerate(code):
        font = _captcha_font(random.randint(22, 28))
        char_image = Image.new('RGBA', (step, height), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_image)
        char_draw.text((2, 4), char, font=font,
                       fill=(random.randint(0, 90), random.randint(0, 90),
                             random.randint(0, 90)))
        try:
            char_image = char_image.rotate(random.uniform(-18, 18), expand=True,
                                           resample=Image.BICUBIC)
        except Exception:
            pass
        image.paste(char_image,
                    (index * step + random.randint(0, 4), random.randint(0, 6)),
                    char_image)

    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def random_captcha_code():
    """生成一个 4 位「数字 + 大小写字母」验证码。"""
    return ''.join(random.choice(CAPTCHA_CHARSET) for _ in range(4))


# 带图片验证码的登录页：点击图片即刷新验证码
CAPTCHA_OCR_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>图形验证码登录</title></head>
<body>
  <h1>图形验证码登录</h1>
  {error_block}
  <form method="POST" action="/do_login_captcha">
    <input type="text" id="username" name="username" placeholder="用户名">
    <input type="password" id="password" name="password" placeholder="密码">
    <div class="captcha-row">
      <img id="captchaImg" alt="验证码" title="点击刷新验证码"
           src="/captcha_ocr_img?t={token}"
           onclick="this.src='/captcha_ocr_img?t={token}&amp;r=' + Date.now();">
      <input type="text" id="captcha" name="captcha" placeholder="验证码">
    </div>
    <button type="submit" id="loginBtn">登录</button>
  </form>
</body></html>
"""


# 设备专用模板页面：元素 id 为专有值，通用模板的 name/id 候选均无法命中
DEDICATED_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>专用模板登录</title></head>
<body>
  <h1>专用模板登录</h1>
  <form method="POST" action="/do_login">
    <input type="text" id="devUser" name="devUserName" placeholder="设备账号">
    <input type="password" id="devPass" name="devPassWord" placeholder="设备密码">
    <button type="button" id="devLogin" onclick="document.getElementById('devUser').form.submit()">提交</button>
  </form>
</body></html>
"""

# 通用登录页面：符合默认模板的常见 name=username / name=password 结构
GENERIC_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>通用登录</title></head>
<body>
  <h1>通用登录</h1>
  <form method="POST" action="/do_login">
    <input type="text" id="username" name="username" placeholder="请输入用户名">
    <input type="password" id="password" name="password" placeholder="请输入密码">
    <button type="submit" id="loginBtn">登录</button>
  </form>
</body></html>
"""

# 标题像登录页但没有表单（用于验证“表单未找到”）
NO_FORM_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>用户登录</title></head>
<body><h1>用户登录</h1><p>页面加载中，请稍候</p></body></html>
"""

# ============ 慢速渲染页面（DOM 先出来，输入框由 JS 延迟插入）============
SLOW_JS_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>慢速渲染登录</title></head>
<body>
  <h1>慢速渲染登录</h1>
  <div id="placeholder">表单加载中...</div>
  <script>
    setTimeout(function () {
      var html = '<form method="POST" action="/do_login">' +
        '<input type="text" id="username" name="username" placeholder="请输入用户名">' +
        '<input type="password" id="password" name="password" placeholder="请输入密码">' +
        '<button type="submit" id="loginBtn">登录</button></form>';
      document.getElementById('placeholder').outerHTML = html;
    }, 3000);
  </script>
</body></html>
"""

# ============ 表单在 iframe 中的页面 ============
FRAME_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>iframe 登录</title></head>
<body>
  <h1>iframe 登录</h1>
  <iframe src="/login" width="420" height="320" title="login-frame"></iframe>
</body></html>
"""

# ============ 五组真实登录页面 HTML 样例 ============
# 第 1 组：q-input 登录页（用户名/密码/图片验证码共享 .q-input__inner）
SAMPLE_QINPUT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>q-input 登录</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" autocomplete="off" placeholder="请输入用户名" class="q-input__inner">
    <input type="password" autocomplete="off" placeholder="请输入密码" class="q-input__inner">
    <input type="text" autocomplete="off" placeholder="请输入图片验证码" class="q-input__inner">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 第 2 组：form.userID 登录页（ID 中含点号，内联 style 易变）
SAMPLE_FORM_USERID_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>form.userID 登录</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" id="form.userID" name="loginName" key="loginName" class="username" style="background-color: rgba(2,12,29,0.25); color: #fff; border: 1px solid #6d85a9;" placeholder="请输入用户名">
    <input type="password" name="password" key="password" id="form.password" style="background-color: rgba(2,12,29,0.25); color: #fff; border: 1px solid #6d85a9;" class="password" placeholder="请输入密码">
    <input type="text" id="form.validateCode" style="background-color: rgba(2,12,29,0.25); color: #fff; border: 1px solid #6d85a9;" name="checkCode" maxlength="4" class="kapkey" placeholder="验证码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 第 3 组：UserName / UserPasswd 登录页（登录按钮为 type=button）
SAMPLE_USERPASSWD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>UserName 登录</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" value="" name="UserName" id="UserName" autocomplete="off" placeholder="Username">
    <input type="password" value="" name="UserPasswd" id="UserPasswd" onkeypress="keypress(event)" autocomplete="off" placeholder="Password">
    <input type="button" value="Login" class="submit" onclick="handleLogin()">
  </form>
  <script>function handleLogin(){ document.getElementById('UserName').form.submit(); }</script>
</body></html>
"""

# 第 4 组：loginName / password / checkCode 登录页（密码框实际为 type=text）
SAMPLE_LOGINNAME_PWD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>loginName 登录</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" id="loginName" name="loginName" class="username" placeholder="用户名">
    <input type="text" id="password" name="password" class="password" onfocus="typeChange();" onkeydown="typeChange();" placeholder="请输入密码">
    <input type="text" id="checkCode" name="checkCode" class="kapkey" placeholder="验证码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 第 5 组：Ant Design / Angular 登录页（_ngcontent / ng-tns 等 class 会变化）
SAMPLE_ANGULAR_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Angular 登录</title></head>
<body>
  <form>
    <input _ngcontent-ng-c2805263466="" type="text" nzsize="large" placeholder="用户名" nz-input="" formcontrolname="username" class="ant-input ng-tns-c3931633203-1 ant-input-lg ant-input-stepperless ng-dirty ng-valid ant-input-status-success ng-touched">
    <input nz-input="" type="password" id="password" autofocus="" class="ant-input ng-dirty ng-valid ant-input-status-success ant-input-stepperless ng-star-inserted ng-touched">
    <button _ngcontent-ng-c2805263466="" nzsize="large" nz-button="" class="ant-btn mrg-t-48 ant-btn-primary ant-btn-lg"><!----><span class="ng-star-inserted">登 录</span></button>
  </form>
</body></html>
"""

SAMPLE_PAGES = {
    '/sample/qinput': SAMPLE_QINPUT_PAGE,
    '/sample/formuserid': SAMPLE_FORM_USERID_PAGE,
    '/sample/userpasswd': SAMPLE_USERPASSWD_PAGE,
    '/sample/loginnamepwd': SAMPLE_LOGINNAME_PWD_PAGE,
    '/sample/angular': SAMPLE_ANGULAR_PAGE,
}


# ============ 元素角色验证专用页面 ============
# 1) login 语义出现在按钮上：name=login 与 id=login 都指向 type=button
ROLE_LOGIN_ATTR_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>login 属性在按钮上</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" id="username" name="username" placeholder="请输入用户名">
    <input type="password" id="password" name="password" placeholder="请输入密码">
    <input type="button" id="login" name="login" value="登录">
  </form>
</body></html>
"""

# 2) 密码框实际是 type=text（靠 id/name/class/placeholder 体现密码语义）
ROLE_TEXT_PASSWORD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>type=text 的密码框</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" id="username" name="username" placeholder="用户名">
    <input type="text" id="password" name="password" class="password" placeholder="请输入密码">
    <button type="submit" id="loginBtn">登录</button>
  </form>
</body></html>
"""

# 3) 同名多元素：两个都像用户名字段（用于验证歧义报告）
ROLE_MULTI_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>同名多元素</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" name="username" placeholder="用户名">
    <input type="text" name="username" placeholder="请输入账号">
    <input type="password" name="password" placeholder="请输入密码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 4) 隐藏 / 禁用 / 只读输入框
ROLE_DISABLED_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>隐藏与禁用输入框</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="hidden" name="username" value="hidden-user">
    <input type="text" name="username" placeholder="用户名" disabled>
    <input type="text" name="username" placeholder="用户名" readonly>
    <input type="text" id="visibleUser" name="visibleuser" placeholder="请输入用户名">
    <input type="password" name="password" placeholder="请输入密码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 5) 页面重新渲染：0.8 秒后重建整个表单 -> 旧的元素引用失效
ROLE_RERENDER_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>重新渲染</title></head>
<body>
  <div id="host"></div>
  <script>
    var html = '<form method="POST" action="/do_login">' +
      '<input type="text" id="username" name="username" placeholder="请输入用户名">' +
      '<input type="password" id="password" name="password" placeholder="请输入密码">' +
      '<button type="submit" id="loginBtn">登录</button></form>';
    document.getElementById('host').innerHTML = html;
    setTimeout(function () { document.getElementById('host').innerHTML = html; }, 800);
  </script>
</body></html>
"""

# 6) 用户名 / 密码 / 验证码 / 登录按钮分别位于不同元素
ROLE_SEPARATE_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>四类字段分离</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" id="userAccount" name="userAccount" placeholder="请输入登录账号">
    <input type="password" id="userSecret" name="userSecret" placeholder="请输入登录口令">
    <input type="text" id="verifyCode" name="verifyCode" placeholder="请输入图形验证码">
    <button type="submit" id="doLogin">登 录</button>
  </form>
</body></html>
"""

# 7) Element UI 风格登录页：账号框与密码框**共用同一个 class**
#    （el-input__inner），且账号框被浏览器/框架标成了
#    autocomplete=current-password。
#    这正是「type=text、placeholder=账号 的账号框被判成
#    looks_like_password」的现场形态：旧实现把 class 与
#    autocomplete 与 placeholder 等权处理。
ROLE_ELINPUT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Element UI 风格登录</title></head>
<body>
  <form method="POST" action="/do_login">
    <div class="el-form-item">
      <label class="el-form-item__label">账号</label>
      <div class="el-input">
        <input type="text" autocomplete="current-password" placeholder="账号" class="el-input__inner">
      </div>
    </div>
    <div class="el-form-item">
      <label class="el-form-item__label">密码</label>
      <div class="el-input">
        <input type="password" autocomplete="new-password" placeholder="密码" class="el-input__inner">
      </div>
    </div>
    <button type="submit" class="el-button el-button--primary">登 录</button>
  </form>
</body></html>
"""

# 8) 账号框自身带密码字段名（name=password），但页面上另有独立的
#    type=password 密码框：元素级证据冲突，需靠页面上下文消歧。
ROLE_NAME_CONFLICT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>字段名冲突</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" name="password" placeholder="账号" class="el-input__inner">
    <input type="password" name="pwd" placeholder="密码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 9) 同样带密码字段名，但页面上**没有**独立的密码框：
#    无法区分账号框与密码框，应报告歧义而不是盲目填写。
ROLE_NAME_CONFLICT_NOPWD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>字段名冲突（无独立密码框）</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" name="password" placeholder="账号" class="el-input__inner">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

# 10) 弱证据：只有样式 class 名里带 password 词（框架常用样式名），
#     元素本身没有任何密码语义。
ROLE_WEAK_SIGNAL_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>弱密码信号</title></head>
<body>
  <form method="POST" action="/do_login">
    <input type="text" class="password-field" placeholder="请输入账号">
    <input type="password" class="password-field" placeholder="请输入密码">
    <button type="submit">登录</button>
  </form>
</body></html>
"""

ROLE_PAGES = {
    '/roles/loginattr': ROLE_LOGIN_ATTR_PAGE,
    '/roles/textpassword': ROLE_TEXT_PASSWORD_PAGE,
    '/roles/multi': ROLE_MULTI_PAGE,
    '/roles/disabled': ROLE_DISABLED_PAGE,
    '/roles/rerender': ROLE_RERENDER_PAGE,
    '/roles/separate': ROLE_SEPARATE_PAGE,
    '/roles/elinput': ROLE_ELINPUT_PAGE,
    '/roles/nameconflict': ROLE_NAME_CONFLICT_PAGE,
    '/roles/nameconflict_nopwd': ROLE_NAME_CONFLICT_NOPWD_PAGE,
    '/roles/weakonly': ROLE_WEAK_SIGNAL_PAGE,
}


class LoginHandler(BaseHTTPRequestHandler):
    # 统计登录提交次数（用于验证“不会重复提交”）
    post_count = 0
    # 当前生效的图片验证码（每次请求验证码图片时刷新）
    current_captcha_code = ''
    # 图片令牌 -> 验证码（同一令牌始终返回同一个验证码）
    captcha_codes = {}

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _send(self, body, status=200):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data, content_type='image/png', status=200):
        """发送二进制内容（验证码图片）。"""
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/login'):
            self._send(LOGIN_PAGE)
        elif path == '/captcha':
            self._send(CAPTCHA_PAGE)
        elif path == '/captcha_clear':
            code = random_captcha_code()
            LoginHandler.captcha_codes['clear'] = code
            LoginHandler.current_captcha_code = code
            self._send(CAPTCHA_CLEAR_PAGE.format(error_block='',
                                                 username='',
                                                 password=''))
        elif path == '/captcha_clear_img':
            code = random_captcha_code()
            LoginHandler.captcha_codes['clear_img'] = code
            LoginHandler.current_captcha_code = code
            try:
                png = make_captcha_png(code)
            except Exception:
                self._send('<html><body>no pillow</body></html>', 500)
                return
            self._send_bytes(png, 'image/png')
        elif path == '/weird':
            self._send(WEIRD_PLACEHOLDER_PAGE)
        elif path == '/captcha_weird_img':
            code = random_captcha_code()
            LoginHandler.captcha_codes['weird'] = code
            LoginHandler.current_captcha_code = code
            try:
                png = make_captcha_png(code, width=150, height=40)
            except Exception:
                self._send('<html><body>no pillow</body></html>', 500)
                return
            self._send_bytes(png, 'image/png')
        elif path == '/captcha_svg':
            token = random_captcha_code()
            code = random_captcha_code()
            LoginHandler.captcha_codes[token] = code
            LoginHandler.current_captcha_code = code
            self._send(CAPTCHA_SVG_PAGE.format(error_block='',
                                               glyphs=svg_glyphs(code)))
        elif path == '/captcha_ocr':
            token = random_captcha_code()
            self._send(CAPTCHA_OCR_PAGE.format(error_block='', token=token))
        elif path == '/captcha_ocr_img':
            # 验证码与「图片令牌」绑定：同一令牌重复请求返回同一个验证码，
            # 这样「点击图片刷新」不会让验证码与页面上显示的图片错位
            # （真实站点是每次请求都换码，这里为了测试可重复性做了固定）。
            token = parse_qs(urlparse(self.path).query).get('t', [''])[0]
            code = LoginHandler.captcha_codes.get(token)
            if code is None:
                code = random_captcha_code()
                LoginHandler.captcha_codes[token] = code
            LoginHandler.current_captcha_code = code
            try:
                png = make_captcha_png(code)
            except Exception:
                self._send('<html><body>缺少 Pillow，无法生成验证码图片</body></html>',
                           500)
                return
            self._send_bytes(png, 'image/png')
        elif path == '/dashboard':
            self._send(DASHBOARD_PAGE)
        elif path == '/dedicated':
            self._send(DEDICATED_PAGE)
        elif path == '/generic':
            self._send(GENERIC_PAGE)
        elif path == '/nologin':
            self._send(NO_FORM_PAGE)
        elif path == '/slowjs':
            self._send(SLOW_JS_PAGE)
        elif path == '/frame':
            self._send(FRAME_PAGE)
        elif path in SAMPLE_PAGES:
            self._send(SAMPLE_PAGES[path])
        elif path in ROLE_PAGES:
            self._send(ROLE_PAGES[path])
        elif path == '/slow':
            import time
            time.sleep(8)
            self._send(LOGIN_PAGE)
        else:
            self._send('<html><body>404</body></html>', 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length).decode('utf-8') if length else ''
        form = {k: v[0] for k, v in parse_qs(raw).items()}

        if path == '/do_login_clear':
            LoginHandler.post_count += 1
            account = form.get('username') or ''
            secret = form.get('password') or ''
            code = (form.get('captcha') or '').strip()
            expected = LoginHandler.current_captcha_code or ''
            if account == 'admin' and secret == 'pass123' and \
                    expected and code.upper() == expected.upper():
                self.send_response(302)
                self.send_header('Location', '/dashboard')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            # 模拟站点行为：验证码错误后把账号密码一起清空
            error = '<div class="error-message">验证码错误，请重新输入验证码</div>'
            self._send(CAPTCHA_CLEAR_PAGE.format(error_block=error,
                                                 username='', password=''))
            return

        if path == '/do_login_weird':
            LoginHandler.post_count += 1
            account = form.get('username') or ''
            secret = form.get('password') or ''
            code = (form.get('captcha') or '').strip()
            expected = LoginHandler.current_captcha_code or ''
            if account == 'admin' and secret == 'pass123' and \
                    expected and code.upper() == expected.upper():
                self.send_response(302)
                self.send_header('Location', '/dashboard')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if account != 'admin' or secret != 'pass123':
                msg = '<div class="error-message">密码错误</div>'
            else:
                msg = '<div class="error-message">验证码错误</div>'
            self._send(WEIRD_PLACEHOLDER_PAGE.replace(
                '<form method="POST" action="/do_login_weird">',
                msg + '<form method="POST" action="/do_login_weird">'))
            return

        if path == '/do_login_svg':
            self._handle_svg_login(form)
            return

        if path == '/do_login_captcha':
            self._handle_captcha_login(form)
            return

        if path != '/do_login':
            self._send('<html><body>404</body></html>', 404)
            return

        LoginHandler.post_count += 1
        account = form.get('username') or form.get('devUserName')
        secret = form.get('password') or form.get('devPassWord')
        if account == 'admin' and secret == 'pass123':
            self.send_response(302)
            self.send_header('Location', '/dashboard')
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            self._send(
                '<!DOCTYPE html><html><head><meta charset="utf-8"><title>设备登录</title></head>'
                '<body><h1>设备登录</h1>'
                '<div class="error-message">密码错误，请重新输入</div>'
                '<form method="POST" action="/do_login">'
                '<input type="text" id="username" name="username">'
                '<input type="password" id="password" name="password">'
                '<button type="submit">登录</button></form></body></html>'
            )

    def _handle_svg_login(self, form):
        """SVG 验证码登录（验证码不区分大小写）。"""
        LoginHandler.post_count += 1
        account = form.get('username') or ''
        secret = form.get('password') or ''
        code = (form.get('captcha') or '').strip()
        recent = list(LoginHandler.captcha_codes.values())[-3:]
        valid = {c.upper() for c in recent}
        if account != 'admin' or secret != 'pass123':
            error = '<div class="error-message">密码错误，请重新输入密码</div>'
            token = random_captcha_code()
            new_code = random_captcha_code()
            LoginHandler.captcha_codes[token] = new_code
            LoginHandler.current_captcha_code = new_code
            self._send(CAPTCHA_SVG_PAGE.format(error_block=error,
                                               glyphs=svg_glyphs(new_code)))
            return
        if not valid or code.upper() not in valid:
            error = '<div class="error-message">验证码错误，请重新输入验证码</div>'
            token = random_captcha_code()
            new_code = random_captcha_code()
            LoginHandler.captcha_codes[token] = new_code
            LoginHandler.current_captcha_code = new_code
            self._send(CAPTCHA_SVG_PAGE.format(error_block=error,
                                               glyphs=svg_glyphs(new_code)))
            return
        self.send_response(302)
        self.send_header('Location', '/dashboard')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _handle_captcha_login(self, form):
        """图片验证码登录：验证码不区分大小写，错误时刷新图片并提示。"""
        LoginHandler.post_count += 1
        account = form.get('username') or ''
        secret = form.get('password') or ''
        code = (form.get('captcha') or '').strip()
        expected = LoginHandler.current_captcha_code or ''

        if account != 'admin' or secret != 'pass123':
            error = '<div class="error-message">密码错误，请重新输入密码</div>'
            token = random_captcha_code()
            self._send(CAPTCHA_OCR_PAGE.format(error_block=error, token=token))
            return

        # 容忍「迟到的图片请求」：最近若干个验证码都算有效，
        # 避免测试之间因请求时序产生偶发失败
        recent = list(LoginHandler.captcha_codes.values())[-3:]
        valid = {c.upper() for c in recent}
        if not expected or code.upper() not in valid:
            error = '<div class="error-message">验证码错误，请重新输入验证码</div>'
            token = random_captcha_code()
            self._send(CAPTCHA_OCR_PAGE.format(error_block=error, token=token))
            return

        self.send_response(302)
        self.send_header('Location', '/dashboard')
        self.send_header('Content-Length', '0')
        self.end_headers()

    @classmethod
    def reset_post_count(cls):
        cls.post_count = 0

    @classmethod
    def reset_captcha(cls):
        """重置当前验证码（测试之间互不干扰）。"""
        cls.current_captcha_code = ''
        cls.captcha_codes = {}


class TestServer:
    """在后台线程运行的测试服务器"""

    def __init__(self, port=0):
        self.httpd = HTTPServer(('127.0.0.1', port), LoginHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        return False

    @property
    def base_url(self):
        return f'http://127.0.0.1:{self.port}'
