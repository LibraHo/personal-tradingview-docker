"""Private, bounded login adapter for an existing command-line OpenD container.

No Docker API, shell endpoint, raw terminal output, or credential persistence.
"""
import base64
import codecs
from collections import deque
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socketserver
import stat
import subprocess
import threading
import time

ERRORS = {
    'network': 'OpenD 登录遇到网络异常，请检查旁路由或代理线路后重试。',
    'password': 'OpenD 提示账号或密码不正确，请重新输入。',
    'verification': '验证码不正确或已失效，请重新获取。',
    'login': 'OpenD 登录未完成，请重新开始登录或检查券商端提示。',
    'stopped': 'OpenD 进程已停止，请检查容器状态。',
}
EVENTS = re.compile(
    r'(?P<account>请输入账号|Please (?:enter|input) (?:your )?(?:account|login account))'
    r'|(?P<password>请输入密码|Please (?:enter|input) (?:your )?password)'
    r'|(?P<remember>请选择是否记住密码|Please choose whether to remember the password)'
    r'|(?P<sms>需要手机验证码|Need phone verification code|Phone verification code is required)'
    r'|(?P<captcha>需要图形验证码|Need (?:picture|image) verification code)'
    r'|(?P<ready>登录成功|Login success(?:ful)?)'
    r'|(?P<error>登录失败|Login fail(?:ed|ure)?|网络库内部异常|密码不正确|密码错误|验证码错误)', re.I)

class RestartNotStarted(ValueError):
    pass


class LoginState:
    def __init__(self):
        self.lock = threading.RLock()
        self.stage = 'starting'
        self.revision = secrets.token_urlsafe(24)
        self.changed_at = time.time()
        self.error = ''
        self.version = ''
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.attempts = deque()
        self.password_attempts = deque()
        self.last_sms = -1000.0
        self.picture = None
        self.challenge = None
        self.process_generation = 0
        self.instance_id = secrets.token_urlsafe(24)

    def change(self, stage):
        self.stage = stage
        self.revision = secrets.token_urlsafe(24)
        self.changed_at = time.time()

    def feed(self, data):
        """Return whether OpenD asked the remember-password question (answer N)."""
        with self.lock:
            self.buffer = (self.buffer + self.decoder.decode(data))[-8192:]
            version = re.search(r'\b(10\.\d{1,2}\.\d{4})\b', self.buffer)
            if version:
                self.version = version.group(1)
            pic = re.search(r'(?:图形验证码已下载到|(?:Image|Picture) verification code.*?downloaded to)\s*[:：]?\s*([^\r\n]+\.(?:png|jpg|jpeg|bmp))', self.buffer, re.I)
            if pic:
                self.picture = pic.group(1).strip().strip('"\'')
            events = list(EVENTS.finditer(self.buffer))
            remember = False
            for event in events:
                kind = event.lastgroup
                if kind == 'remember':
                    self.change('waiting')
                    remember = True
                elif kind == 'error':
                    text = self.buffer
                    self.error = ('network' if '网络库内部异常' in text else
                                  'password' if '密码错误' in text or '密码不正确' in text else
                                  'verification' if '验证码错误' in text else 'login')
                    self.change(self.challenge if self.error == 'verification' and self.challenge else 'error')
                else:
                    self.change(kind)
                    if kind in {'sms', 'captcha'}:
                        self.challenge = kind
                    elif kind in {'account', 'ready'}:
                        self.challenge = None
                    if kind == 'ready':
                        self.error = ''
                        self.picture = None
            if events:
                self.buffer = self.buffer[events[-1].end():]
            return remember

    def snapshot(self):
        with self.lock:
            return {'available': True, 'stage': self.stage, 'revision': self.revision,
                    'version': self.version, 'changed_at': self.changed_at, 'process_generation': self.process_generation,
                    'instance_id': self.instance_id,
                    'message': ERRORS.get(self.error, ''),
                    'retry_allowed': self.stage in {'error', 'account', 'password', 'sms', 'captcha'}
                        or (self.stage == 'waiting' and time.time() - self.changed_at > 30)}

    def prepare(self, action, revision, value=''):
        """Caller holds lock across prepare + write. Never return a command from user text."""
        if not isinstance(revision, str) or not secrets.compare_digest(revision, self.revision):
            raise ValueError('页面状态已变化，请刷新后再操作')
        try:
            valid_text = isinstance(value, str) and len(value.encode('utf-8')) <= 512
        except UnicodeError:
            valid_text = False
        if not valid_text or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('输入中不能包含换行或控制字符')
        now = time.monotonic()
        while self.attempts and now - self.attempts[0] > 60:
            self.attempts.popleft()
        if len(self.attempts) >= 20:
            raise ValueError('操作过于频繁，请一分钟后重试')
        wire = None
        if action == 'account' and self.stage == 'account':
            if not re.fullmatch(r'(?:\+\d{1,4} \d{4,18}|[A-Za-z0-9][A-Za-z0-9@._+\-]{2,127})', value):
                raise ValueError('请输入 moomoo ID、邮箱或“+区号 手机号”')
            wire = value
        elif action == 'password' and self.stage == 'password':
            if not value:
                raise ValueError('请输入登录密码')
            while self.password_attempts and now - self.password_attempts[0] > 3600:
                self.password_attempts.popleft()
            if len(self.password_attempts) >= 10:
                raise ValueError('登录尝试过多，请稍后重试')
            self.password_attempts.append(now)
            wire = value
        elif action in {'sms', 'captcha'} and self.stage == action:
            if not re.fullmatch(r'[0-9]{4,8}' if action == 'sms' else r'[A-Za-z0-9]{3,12}', value):
                raise ValueError('验证码格式不正确')
            wire = ('input_phone_verify_code' if action == 'sms' else 'input_pic_verify_code') + ' -code=' + value
        elif action == 'request_sms' and self.stage == 'sms':
            if now - self.last_sms < 60:
                raise ValueError('验证码每分钟只能请求一次，请稍后再试')
            self.last_sms = now
            wire = 'req_phone_verify_code'
        elif action == 'request_captcha' and self.stage == 'captcha':
            wire = 'req_pic_verify_code'
        if wire is None:
            raise ValueError('此操作不适用于当前登录阶段')
        self.attempts.append(now)
        self.error = ''
        self.buffer = ''
        self.change(self.stage if action.startswith('request_') else 'waiting')
        return (wire + '\n').encode('utf-8')

    def captcha(self):
        if self.stage != 'captcha' or not self.picture:
            return {'image': None}
        path = Path(self.picture).resolve()
        if not any(path.is_relative_to(root) for root in (Path('/app'), Path('/root/.com.moomoo.OpenD'))):
            return {'image': None}
        try:
            with path.open('rb') as source:
                data = source.read(262145)
            if len(data) > 262144:
                return {'image': None}
            mime = ('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
                    'image/jpeg' if data.startswith(b'\xff\xd8\xff') else
                    'image/bmp' if data.startswith(b'BM') else None)
            return {'image': 'data:' + mime + ';base64,' + base64.b64encode(data).decode() if mime else None}
        except OSError:
            return {'image': None}


class Supervisor:
    def __init__(self, command):
        self.state = LoginState()
        self.command = command
        self.child = None
        self.master = None
        self.slave = None
        self.stop = threading.Event()
        self.restart = threading.Event()
        self.restart_attempts = deque()

    def write(self, data):
        import termios
        # Disable terminal echo before every write. Never forward raw PTY output.
        attrs = termios.tcgetattr(self.slave)
        attrs[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(self.slave, termios.TCSANOW, attrs)
        os.write(self.master, data)

    def request(self, body):
        action = body.get('action')
        if action == 'restart':
            with self.state.lock:
                if not self.state.snapshot()['retry_allowed'] or body.get('revision') != self.state.revision:
                    raise RestartNotStarted('当前阶段不能重启登录，请先刷新状态')
                now = time.monotonic()
                while self.restart_attempts and now - self.restart_attempts[0] > 60:
                    self.restart_attempts.popleft()
                if len(self.restart_attempts) >= 3:
                    raise RestartNotStarted('重启次数过多，请一分钟后再试')
                self.restart_attempts.append(now)
                generation = self.state.process_generation
                self.state.change('starting')
                self.restart.set()
            deadline = time.monotonic() + 16
            while time.monotonic() < deadline and not self.stop.is_set():
                with self.state.lock:
                    if self.state.process_generation > generation and self.state.stage not in {'starting', 'waiting'}:
                        return self.state.snapshot()
                time.sleep(.1)
            raise ValueError('尚未确认 OpenD 重启完成，请刷新状态；交易入口将保持暂停')
        with self.state.lock:
            if action == 'status':
                return self.state.snapshot()
            if action == 'captcha_image':
                return self.state.captcha()
            if not self.child or self.child.poll() is not None:
                raise ValueError('OpenD 未运行，请检查容器状态')
            wire = self.state.prepare(action, body.get('revision'), body.get('value', ''))
            self.write(wire)
            del wire
            return self.state.snapshot()

    def run_child(self):
        try:
            self._run_child()
        except BaseException:
            with self.state.lock:
                self.state.error = 'stopped'
                self.state.change('error')
            self.stop.set()
        finally:
            if self.child and self.child.poll() is None:
                try:
                    os.killpg(self.child.pid, signal.SIGKILL)
                    self.child.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
            for fd in (self.master, self.slave):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _run_child(self):
        import sys
        import pty
        import select
        import termios
        while not self.stop.is_set():
            self.restart.clear()
            with self.state.lock:
                self.state.change('starting')
                self.state.buffer = ''
                self.state.error = ''
                self.state.picture = None
                self.state.decoder.reset()
                self.master, self.slave = pty.openpty()
                attrs = termios.tcgetattr(self.slave)
                attrs[3] &= ~(termios.ECHO | termios.ECHONL)
                termios.tcsetattr(self.slave, termios.TCSANOW, attrs)
                self.child = subprocess.Popen([sys.executable, __file__, '--child', *self.command], stdin=self.slave, stdout=self.slave,
                                              stderr=self.slave, cwd='/app', start_new_session=True)
                self.state.process_generation += 1
            while self.child.poll() is None and not self.stop.is_set() and not self.restart.is_set():
                if select.select([self.master], [], [], .5)[0]:
                    try:
                        block = os.read(self.master, 4096)
                    except OSError:
                        break
                    if not block:
                        break
                    with self.state.lock:
                        if self.state.feed(block):
                            self.write(b'N\n')
            if self.child.poll() is None:
                try:
                    os.killpg(self.child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(self.child.pid, signal.SIGKILL)
                    self.child.wait()
            with self.state.lock:
                os.close(self.master)
                os.close(self.slave)
                self.master = self.slave = None
                if not self.restart.is_set():
                    self.state.error = 'stopped'
                    self.state.change('error')
            if not self.restart.is_set():
                # Let Docker's existing restart policy recover an unexpected exit.
                self.stop.set()


def main():
    import sys
    os.umask(0o077)
    directory = Path(os.getenv('OPEND_LOGIN_DIR', '/run/nas-market-opend'))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / 'login.sock'
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise RuntimeError('Login socket path is not a socket')
        path.unlink()
    supervisor = Supervisor(['/app/OpenD', *sys.argv[1:]])

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(2)
            try:
                raw = self.rfile.readline(4097)
                if len(raw) > 4096 or not raw.endswith(b'\n'):
                    raise ValueError('请求过大或格式不正确')
                body = json.loads(raw)
                if not isinstance(body, dict) or set(body) - {'action', 'revision', 'value'}:
                    raise ValueError('请求字段不正确')
                result = supervisor.request(body)
                reply = {'ok': True, 'data': result}
            except ValueError as exc:
                # Only locally generated messages; JSON parse errors must not reflect input.
                message = '请求格式不正确' if isinstance(exc, json.JSONDecodeError) else str(exc)
                reply = {'ok': False, 'message': message,
                         'code': 'restart_not_started' if isinstance(exc, RestartNotStarted) else 'rejected'}
            except Exception:
                reply = {'ok': False, 'message': 'OpenD 登录适配器暂不可用，请刷新后重试'}
            try:
                self.wfile.write((json.dumps(reply, ensure_ascii=True) + '\n').encode())
            except OSError:
                pass

    server = socketserver.UnixStreamServer(str(path), Handler)
    path.chmod(0o600)
    server.timeout = .5
    thread = threading.Thread(target=supervisor.run_child, daemon=True)
    thread.start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: supervisor.stop.set())
    print('OpenD private login adapter started', flush=True)
    try:
        while not supervisor.stop.is_set():
            server.handle_request()
    finally:
        supervisor.stop.set()
        thread.join(timeout=12)
        server.server_close()
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == '--child':
        import fcntl
        import termios
        # Executed in a fresh Python process/session, never a threaded preexec_fn.
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.execv(sys.argv[2], sys.argv[2:])
    else:
        main()
