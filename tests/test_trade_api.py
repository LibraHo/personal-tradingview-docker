import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from test_trading import FakeBroker

_module_temp = tempfile.TemporaryDirectory()
os.environ['TRADING_DATA_DIR'] = _module_temp.name
from app.trade_api import create_app, COOKIE


class TradeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = FakeBroker()
        self.app = create_app(self.tmp.name, self.broker)
        self.client = TestClient(self.app, base_url='https://testserver')
        self.client.__enter__()
        self.origin = {'Origin': 'https://testserver'}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def setup_account(self):
        code = Path(self.tmp.name, 'setup-code.txt').read_text()
        r = self.client.post('/api/trade/setup', headers=self.origin,
            json={'password': 'test-platform-password', 'setup_code': code})
        self.assertEqual(r.status_code, 200, r.text)
        self.headers = {**self.origin, 'X-CSRF-Token': r.json()['csrf']}
        return r

    def test_https_authentication_cookie_and_csrf(self):
        self.assertEqual(self.client.get('http://testserver/api/trade/auth').status_code, 426)
        self.assertEqual(self.client.get('/api/trade/accounts').status_code, 401)
        r = self.setup_account()
        cookie = r.headers['set-cookie']
        self.assertIn('Secure', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertEqual(self.client.get('/api/trade/accounts').status_code, 200)
        self.assertEqual(self.client.post('/api/trade/lock', headers=self.origin, json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/trade/lock', headers={**self.headers,'Origin':'https://evil.test'}, json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/trade/lock', headers=self.headers, json={}).status_code, 200)

    def test_one_time_setup_stores_only_password_derivation(self):
        self.setup_account()
        stored = Path(self.tmp.name, 'auth.json').read_text()
        self.assertNotIn('test-platform-password', stored)
        self.assertEqual(set(json.loads(stored)), {'salt', 'hash'})
        self.assertFalse(Path(self.tmp.name, 'setup-code.txt').exists())
        self.assertEqual(self.client.post('/api/trade/setup', headers=self.origin,
            json={'password':'test-platform-password','setup_code':'anything'}).status_code, 409)

    def test_preview_confirm_workflow_and_no_side_effect_before_confirmation(self):
        self.setup_account()
        order = dict(acc_id='123456789123456789', env='SIMULATE', code='US.SNDK',
            side='BUY', order_type='NORMAL', qty=10, price=100, session='RTH', time_in_force='DAY')
        r = self.client.post('/api/trade/preview', headers=self.headers, json=order)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(self.broker.rows)
        body = {'preview_id':r.json()['preview_id'], 'operation_id':str(uuid.uuid4())}
        result = self.client.post('/api/trade/commit',headers=self.headers,json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.client.post('/api/trade/commit',headers=self.headers,json=body)
        self.assertEqual(len(self.broker.rows), 1)
        self.assertEqual(result.json()['result'][0]['order_id'],'900000000000000000')

    def test_secret_validation_is_not_reflected(self):
        self.setup_account()
        response = self.client.post('/api/trade/unlock', headers=self.headers,
            json={'acc_id':'invalid','password':'very-sensitive-password','confirm':'UNLOCK REAL'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('very-sensitive-password', response.text)

    def test_logout_revokes_session(self):
        self.setup_account()
        r = self.client.post('/api/trade/logout', headers=self.headers, json={})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/trade/accounts').status_code,401)


if __name__ == '__main__':
    unittest.main()
