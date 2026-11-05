import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('opend_login_supervisor', Path(__file__).parents[1] / 'integrations/opend_login/supervisor.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LoginStateTests(unittest.TestCase):
    def test_native_login_errors_across_every_split(self):
        for message, expected in [('登录失败,账号密码不齐全', 'incomplete'),
                                  ('登录失败,网络异常，请稍后再试', 'network')]:
            wire = message.encode()
            for split in range(len(wire) + 1):
                state = module.LoginState()
                state.feed(wire[:split]);state.feed(wire[split:])
                self.assertEqual(state.error, expected, (message, split))
                self.assertEqual(state.stage, 'error')

    def test_split_unicode_prompts_and_password_not_retained(self):
        state = module.LoginState()
        for byte in 'OpenD 10.11.7108\n请输入账号：'.encode():
            state.feed(bytes([byte]))
        self.assertEqual(state.stage, 'account')
        self.assertEqual(state.version, '10.11.7108')
        revision = state.revision
        self.assertEqual(state.prepare('account', revision, '+86 12345678901'), b'+86 12345678901\n')
        with self.assertRaises(ValueError):
            state.prepare('account', revision, '12345')
        state.feed('请输入密码：'.encode())
        self.assertEqual(state.prepare('password', state.revision, 'secret-value'), b'secret-value\n')
        self.assertNotIn('secret-value', repr(vars(state)))
        self.assertTrue(state.feed('请选择是否记住密码（Y代表记住，N代表不记住）'.encode()))
        state.feed('登录成功'.encode())
        self.assertEqual(state.stage, 'ready')
        self.assertFalse(state.snapshot()['retry_allowed'])

    def test_arbitrary_commands_controls_and_wrong_stages_rejected(self):
        for value in ('root\nexit', 'abc\rrelogin', 'abc\x03', 'abc\x7f', '\ud800', 'a'*513):
            state = module.LoginState();state.change('password')
            with self.assertRaises(ValueError) as error:
                state.prepare('password', state.revision, value)
            self.assertNotIn(value, str(error.exception))
        state = module.LoginState();state.change('account')
        for action, value in [('shell','exit'),('account','exit -x=1'),('password','secret')]:
            with self.assertRaises(ValueError):
                state.prepare(action, state.revision, value)

    def test_verification_retries_and_sms_cooldown(self):
        state = module.LoginState();state.feed('需要手机验证码'.encode())
        self.assertEqual(state.prepare('request_sms',state.revision),b'req_phone_verify_code\n')
        with self.assertRaises(ValueError):state.prepare('request_sms',state.revision)
        self.assertEqual(state.prepare('sms',state.revision,'123456'),b'input_phone_verify_code -code=123456\n')
        state.feed('手机验证码错误'.encode())
        self.assertEqual(state.stage,'sms')
        self.assertIn('验证码',state.snapshot()['message'])

    def test_raw_output_not_exposed_and_buffer_bounded(self):
        state = module.LoginState();state.feed(('private-info'*10000).encode())
        self.assertLessEqual(len(state.buffer),8192)
        self.assertNotIn('private-info',json.dumps(state.snapshot()))
        state.feed('登录失败,网络库内部异常; unrelated-account'.encode())
        self.assertEqual(state.error,'network')
        self.assertNotIn('unrelated-account',json.dumps(state.snapshot()))

    def test_english_prompts(self):
        state = module.LoginState()
        state.feed(b'Please enter your account');self.assertEqual(state.stage,'account')
        state.feed(b'Please enter password');self.assertEqual(state.stage,'password')
        self.assertTrue(state.feed(b'Please choose whether to remember the password'))
        state.feed(b'Login successful');self.assertEqual(state.stage,'ready')

    def test_worker_failure_stops_supervisor(self):
        s=module.Supervisor(['/app/OpenD'])
        with patch.object(s,'_run_child',side_effect=RuntimeError('secret internal detail')):
            s.run_child()
        self.assertTrue(s.stop.is_set());self.assertEqual(s.state.stage,'error')
        self.assertNotIn('secret internal detail',json.dumps(s.state.snapshot()))

    def test_image_cannot_read_arbitrary_paths(self):
        s=module.LoginState();s.change('captcha');s.picture='/etc/shadow'
        self.assertIsNone(s.captcha()['image'])


from test_trade_api import TradeApiTests


class OpenDLoginApiTests(TradeApiTests):
    def test_login_api_auth_csrf_and_drawing_token_isolation(self):
        endpoint='/api/trade/opend/status'
        self.assertEqual(self.client.get(endpoint).status_code,401)
        self.assertEqual(self.client.get('http://testserver'+endpoint).status_code,426)
        self.assertEqual(self.client.get(endpoint,headers={'Authorization':'Bearer drawing-token'}).status_code,401)
        self.setup_account()
        body={'action':'password','revision':'a'*32,'value':'secret-value'}
        with patch('app.opend_login_api.exchange',return_value={'stage':'waiting'}) as bridge:
            self.assertEqual(self.client.post('/api/trade/opend/input',headers=self.origin,json=body).status_code,403)
            self.assertEqual(self.client.post('/api/trade/opend/input',headers={**self.headers,'Origin':'https://evil.test'},json=body).status_code,403)
            self.assertEqual(self.client.post('/api/trade/opend/input',headers=self.headers,json=body).status_code,200)
            self.assertEqual(bridge.call_count,1)
        self.assertFalse(self.broker.rows)

    def test_invalid_credentials_never_reflected(self):
        self.setup_account()
        for body in [{'action':'shell','revision':'a'*32,'value':'SECRET-VALUE'},
                     {'action':'password','revision':'a'*32,'value':'SECRET-VALUE\nexit'},
                     {'action':'password','revision':'a'*32,'value':'SECRET-VALUE','extra':True}]:
            r=self.client.post('/api/trade/opend/input',headers=self.headers,json=body)
            self.assertEqual(r.status_code,422);self.assertNotIn('SECRET-VALUE',r.text)
        r=self.client.post('/api/trade/opend/input',headers=self.headers,content=b'x'*5000)
        self.assertEqual(r.status_code,413)

    def test_restart_rejects_unlocked_platform(self):
        self.setup_account();self.app.state.engine.grant={'owner':'test'}
        with patch('app.opend_login_api.exchange') as bridge:
            r=self.client.post('/api/trade/opend/input',headers=self.headers,json={'action':'restart','revision':'a'*32})
            self.assertEqual(r.status_code,409);bridge.assert_not_called()
        self.app.state.engine.grant=None

    def test_unavailable_is_visible_without_raw_details(self):
        self.setup_account()
        with patch.dict('os.environ',{'OPEND_LOGIN_SOCKET':''}):
            r=self.client.get('/api/trade/opend/status')
            self.assertEqual(r.status_code,200);self.assertFalse(r.json()['available'])
