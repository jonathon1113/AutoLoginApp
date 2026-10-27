"""测试用本地模拟登录服务器。

提供以下页面：
- /login      登录表单（用户名/密码/登录按钮）
- /do_login   处理登录：用户名 admin + 密码 pass123 成功，其余返回错误提示
- /dashboard  登录成功后的页面
- /captcha    带验证码输入框的登录页
- /slow       响应较慢的页面（用于超时/等待测试）
- /dedicated  专用选择器页面（id=devUser/devPass/devLogin，通用模板无法命中）
- /generic    通用登录页面（name=username/password，通用模板可命中）
- /nologin    标题像登录页但没有任何表单
- /slowjs     DOM 先出来、输入框由 JS 延迟渲染的页面
- /frame      登录表单位于 iframe 中的页面
- /sample/*   五组真实登录页面 HTML 样例（q-input / form.userID /
              UserName+UserPasswd / loginName+password+checkCode / Ant Design+Angular）
"""

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

DASHBOARD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>控制台</title></head>
<body><h1>控制台</h1><p id="welcome">欢迎回来</p></body></html>
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

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _send(self, body, status=200):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/login'):
            self._send(LOGIN_PAGE)
        elif path == '/captcha':
            self._send(CAPTCHA_PAGE)
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

    @classmethod
    def reset_post_count(cls):
        cls.post_count = 0


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
