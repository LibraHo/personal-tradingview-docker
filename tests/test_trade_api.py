import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch, MagicMock, AsyncMock
import time
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

    def test_notification_settings_require_https_session_and_csrf(self):
        path='/api/trade/notifications'
        self.assertEqual(self.client.get('http://testserver'+path).status_code,426)
        self.assertEqual(self.client.get(path).status_code,401)
        self.setup_account()
        self.assertEqual(self.client.post(path+'/channels',headers=self.origin,json={}).status_code,403)
        self.assertEqual(self.client.post(path+'/channels',headers={**self.headers,'Origin':'https://evil.test'},json={}).status_code,403)

    def test_api_management_requires_session_and_csrf_and_revokes(self):
        import sqlite3
        path=str(Path(self.tmp.name)/'market.sqlite3')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE scan_tokens(id TEXT PRIMARY KEY,digest TEXT,name TEXT,scopes TEXT,created REAL,revoked INTEGER)')
        db.close()
        prefix='/api/trade/api-management'
        self.assertEqual(self.client.get(prefix+'/tokens').status_code,401)
        self.setup_account()
        with patch.dict(os.environ,{'DB_PATH':path}),patch('app.api_management.market_schema',return_value={'paths':{'/api/v1/events':{'get':{'summary':'Events'}}}}):
            inv=self.client.get(prefix+'/inventory');self.assertEqual(inv.status_code,200,inv.text)
            self.assertTrue(any(r['path']=='/api/v1/events' and r['auth']=='Bearer · read' for r in inv.json()['items']))
            self.assertTrue(any(r['path']=='/api/trade/preview' for r in inv.json()['items']))
            self.assertEqual(self.client.post(prefix+'/tokens',headers=self.origin,json={'name':'test'}).status_code,403)
            self.assertEqual(self.client.post(prefix+'/tokens',headers=self.headers,json={'name':'test','scopes':['trade']}).status_code,422)
            created=self.client.post(prefix+'/tokens',headers=self.headers,json={'name':'test','scopes':['read']})
            self.assertEqual(created.status_code,200,created.text);token=created.json()
            listed=self.client.get(prefix+'/tokens');self.assertNotIn(token['token'],listed.text);self.assertNotIn('digest',listed.text)
            self.assertEqual(listed.json()['items'][0]['scopes'],['read'])
            self.assertEqual(self.client.delete(prefix+'/tokens/'+token['id'],headers=self.headers).status_code,200)
            self.assertEqual(self.client.get(prefix+'/tokens').json()['items'][0]['revoked'],1)
            with sqlite3.connect(path) as db:self.assertNotEqual(db.execute('SELECT digest FROM scan_tokens').fetchone()[0],token['token'])
            db.close()
            with patch('app.api_management.market_schema',side_effect=OSError('offline')):
                degraded=self.client.get(prefix+'/inventory').json()
                self.assertEqual(len(degraded['errors']),1);self.assertTrue(degraded['items'])

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

    def test_chart_gateway_auth_allowlist_and_no_credentials_forwarded(self):
        self.assertEqual(self.client.get('/api/market/status').status_code, 401)
        self.setup_account()
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status = 200
        reply.read.return_value = b'{"connected":true}'
        with patch('app.chart_gateway.urllib.request.urlopen', return_value=reply) as forward:
            r = self.client.get('/api/market/status')
            self.assertEqual(r.status_code, 200)
            req = forward.call_args.args[0]
            self.assertEqual(req.full_url, 'http://market:8000/api/status')
            self.assertNotIn('Cookie', req.headers)
            self.assertNotIn('X-csrf-token', req.headers)
            self.assertEqual(self.client.get('/api/market/trade/commit').status_code, 404)
            self.assertEqual(forward.call_count, 1)
            self.assertEqual(self.client.get('/api/market/opening-range?symbol=US.AAPL').status_code,200)
            self.assertTrue(forward.call_args.args[0].full_url.endswith('/api/opening-range?symbol=US.AAPL'))
            self.assertNotIn('Cookie',forward.call_args.args[0].headers)
            self.assertEqual(self.client.post('/api/market/scanner/scope-preview',headers=self.origin,json={'kind':'all','market':'CN'}).status_code,403)
            self.assertEqual(self.client.post('/api/market/scanner/scope-preview',headers=self.headers,json={'kind':'all','market':'CN'}).status_code,200)
            self.assertTrue(forward.call_args.args[0].full_url.endswith('/api/scanner/scope-preview'))
            self.assertEqual(json.loads(forward.call_args.args[0].data)['market'],'CN')
        self.assertEqual(self.client.put('/api/market/settings/workspace', headers=self.origin, json={'value':{}}).status_code, 403)
        self.assertFalse(self.broker.rows)

    def test_review_gateway_authentication_and_methods(self):
        self.assertEqual(self.client.get('/api/market/review/dashboard?market=CN&day=2026-11-18').status_code, 401)
        self.setup_account()
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status = 200
        reply.read.return_value = b'{}'
        with patch('app.chart_gateway.urllib.request.urlopen', return_value=reply) as forward:
            self.assertEqual(self.client.get('/api/market/review/dashboard?market=CN&day=2026-11-18').status_code, 200)
            self.assertTrue(forward.call_args.args[0].full_url.endswith('/api/review/dashboard?market=CN&day=2026-11-18'))
            for path, method in [('rules', 'POST'), ('rules/cn-default-0', 'PUT'), ('days/2026-11-18', 'PUT'), ('weeks/2026-11-16', 'PUT')]:
                self.assertEqual(self.client.request(method, '/api/market/review/'+path+'?market=CN', headers=self.origin, json={}).status_code, 403)
                self.assertEqual(self.client.request(method, '/api/market/review/'+path+'?market=CN', headers=self.headers, json={}).status_code, 200)
            self.assertEqual(self.client.delete('/api/market/review/days/2026-11-18', headers=self.headers).status_code, 404)
            self.assertEqual(self.client.post('/api/market/review/export', headers=self.headers, json={}).status_code, 404)
            ident = 'a'*32
            ledger = '/api/market/review/ledger/'
            for method,path in [('get','book'), ('get','fills/'+ident), ('get','backlinks'),
                                ('post','positions'), ('post','reconcile'), ('post','opend/sync'),
                                ('put','plans/'+ident), ('put','plans/'+ident+'/fills/'+ident),
                                ('delete','plans/'+ident), ('delete','plans/'+ident+'/fills/'+ident),
                                ('put','fills/'+ident+'/review')]:
                url = ledger+path+'?market=US'
                if method != 'get':
                    self.assertEqual(self.client.request(method,url,headers=self.origin).status_code,403)
                self.assertEqual(self.client.request(method,url,headers=self.headers).status_code,200)
            self.assertEqual(self.client.post(ledger+'book',headers=self.headers).status_code,404)
            large = {'context': '复盘内容' * 6000}
            self.assertEqual(self.client.put('/api/market/review/days/2026-11-18?market=CN', headers=self.headers, json=large).status_code, 200)
            self.assertEqual(self.client.put('/api/market/settings/workspace', headers=self.headers, json=large).status_code, 413)
        self.assertFalse(self.broker.rows)

    def test_agent_review_patch_forwards_bearer_without_browser_session(self):
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status = 200
        reply.read.return_value = b'{}'
        with patch('app.chart_gateway.urllib.request.urlopen', return_value=reply) as forward:
            path = '/api/v1/review/days/2026-11-18?market=CN'
            response = self.client.patch(path, headers={'Authorization': 'Bearer test-only'},
                json={'revision': 0, 'lesson': '同步内容' * 3000})
            self.assertEqual(response.status_code, 200, response.text)
            request = forward.call_args.args[0]
            self.assertEqual(request.method, 'PATCH')
            self.assertEqual(request.full_url, 'http://market:8000' + path)
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-only')
            self.assertNotIn('Cookie', request.headers)

    def test_shared_theme_is_available_on_the_login_page(self):
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status = 200
        reply.read.return_value = b'{"value":"light"}'
        with patch('app.chart_gateway.urllib.request.urlopen', return_value=reply) as forward:
            self.assertEqual(self.client.get('/api/market/settings/theme').json()['value'], 'light')
            saved = self.client.put('/api/market/settings/theme', headers=self.origin, json={'value': 'light'})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(forward.call_args.args[0].full_url.endswith('/api/settings/theme'))
            self.assertEqual(self.client.put('/api/market/settings/theme', headers={'Origin': 'https://other.example'},
                                             json={'value': 'dark'}).status_code, 403)
        self.assertEqual(self.client.get('/api/market/settings/workspace').status_code, 401)
        self.assertEqual(self.client.get('/api/trade/accounts').status_code, 401)

    def test_scanner_gateway_keeps_the_idempotency_key(self):
        reply=MagicMock()
        reply.__enter__.return_value=reply
        reply.status=202
        reply.read.return_value=b'{"id":"job","status":"queued"}'
        with patch('app.chart_gateway.urllib.request.urlopen',return_value=reply) as forward:
            response=self.client.post('/api/v1/plans/'+'a'*32+'/run',
                headers={'Authorization':'Bearer temporary','Idempotency-Key':'intent-1'},json={'force':True})
            self.assertEqual(response.status_code,202,response.text)
            self.assertEqual(forward.call_args.args[0].get_header('Idempotency-key'),'intent-1')
            self.setup_account()
            for path in ['scanner/jobs/'+'a'*32+'/pause','scanner/jobs/'+'a'*32+'/resume']:
                response=self.client.post('/api/market/'+path,headers=self.headers)
                self.assertEqual(response.status_code,202,response.text)
            self.assertEqual(self.client.get('/api/market/scanner/plans/'+'a'*32+'/results').status_code,202)

    def test_drawing_agent_is_scoped_and_needs_no_trade_session(self):
        token = 'drawing-agent-test-token-longer-than-32'
        headers = {'Authorization': 'Bearer ' + token}
        reply = MagicMock();reply.__enter__.return_value = reply;reply.status = 200;reply.read.return_value = b'{"created":true}'
        with patch.dict(os.environ, {'DRAWING_API_TOKEN':token}), patch('app.chart_gateway.urllib.request.urlopen', return_value=reply) as forward:
            self.assertEqual(self.client.get('/api/drawings/capabilities').status_code,401)
            self.assertEqual(self.client.post('/api/drawings/objects',headers=headers,json={'price':130}).status_code,200)
            req = forward.call_args.args[0]
            self.assertEqual(req.full_url,'http://market:8000/api/drawings/objects')
            self.assertNotIn('Cookie',req.headers)
            self.assertEqual(self.client.get('/api/trade/accounts',headers=headers).status_code,401)
            self.assertEqual(self.client.post('/api/trade/commit',headers=headers,json={}).status_code,403)
            self.assertEqual(self.client.post('/api/drawings/trade/commit',headers=headers,json={}).status_code,404)
            self.assertEqual(forward.call_count,1)
        self.assertFalse(self.broker.rows)

    def test_drawing_token_visible_only_to_authenticated_browser(self):
        token='test-drawing-secret-at-least-32-characters'
        with patch.dict(os.environ, {'DRAWING_API_TOKEN':token}):
            self.assertEqual(self.client.get('/api/trade/drawing-token').status_code,401)
            self.assertEqual(self.client.get('/api/trade/drawing-token',headers={'Authorization':'Bearer '+token}).status_code,401)
            self.setup_account()
            response=self.client.get('/api/trade/drawing-token')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['token'],token)
            self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertFalse(self.broker.rows)

    def test_chart_websocket_rejects_missing_session(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/market/stream?symbol=US.SNDK', headers={'Origin':'https://testserver'}):
                pass

    def test_chart_websocket_forwards_readonly_stream(self):
        import asyncio
        from contextlib import asynccontextmanager
        self.setup_account()

        class Source:
            async def __aiter__(self):
                yield '{"type":"status","connected":true}'
                await asyncio.sleep(30)

        @asynccontextmanager
        async def connect(url, **kwargs):
            self.assertTrue(url.startswith('ws://market:8000/api/stream?'))
            yield Source()

        with patch('websockets.legacy.client.connect', connect):
            with self.client.websocket_connect('wss://testserver/api/market/stream?symbol=US.SNDK',
                                                headers={'Origin':'https://testserver'}) as ws:
                self.assertTrue(ws.receive_json()['connected'])
        self.assertFalse(self.broker.rows)

    def strategy_fixture(self):
        from test_strategies import config
        cfg=config();cfg['execution']['flat_only']=False
        self.setup_account()
        stamp=int(time.time())-600
        result={'bar_time':stamp,'bar_end':stamp+300,'buy':False,'sell':False,'close':100,'stale':False,'live':True}
        mock=AsyncMock(return_value=result)
        patched=patch('app.strategy_api.market_evaluate',mock);patched.start();self.addCleanup(patched.stop)
        saved=self.client.post('/api/trade/strategies/save',headers=self.headers,json=cfg)
        self.assertEqual(saved.status_code,200,saved.text)
        sid=saved.json()['id']
        started=self.client.post('/api/trade/strategies/start',headers=self.headers,json={'id':sid,'enabled':True})
        self.assertEqual(started.status_code,200,started.text)
        return sid,mock,result

    def test_strategy_signal_only_then_armed_executes_once(self):
        sid,mock,result=self.strategy_fixture()
        next_result={**result,'bar_time':result['bar_time']+300,'bar_end':int(time.time()),'buy':True}
        mock.return_value=next_result
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.assertFalse(self.broker.rows)
        arm=self.client.post('/api/trade/strategies/arm',headers=self.headers,json={
            'id':sid,'acc_id':'123456789123456789','env':'SIMULATE','confirm':'ARM STRATEGY'})
        self.assertEqual(arm.status_code,200,arm.text)
        self.assertFalse(self.broker.rows)
        mock.return_value={**next_result,'bar_time':next_result['bar_time']+300,'bar_end':int(time.time())}
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.assertEqual(len(self.broker.rows),1)
        self.assertIsNone(self.app.state.strategies.get(sid)['arm'])

    def test_strategy_real_arm_requires_unlock_and_stop_cancels_arm(self):
        sid,_,_=self.strategy_fixture()
        armed=self.client.post('/api/trade/strategies/arm',headers=self.headers,json={
            'id':sid,'acc_id':'987654321987654321','env':'REAL','confirm':'ARM STRATEGY'})
        self.assertEqual(armed.status_code,400)
        self.assertFalse(self.broker.rows)
        self.client.post('/api/trade/strategies/arm',headers=self.headers,json={
            'id':sid,'acc_id':'123456789123456789','env':'SIMULATE','confirm':'ARM STRATEGY'})
        pending_arm=self.app.state.strategies.arms[sid]
        self.client.post('/api/trade/strategies/start',headers=self.headers,json={'id':sid,'enabled':False})
        self.assertTrue(pending_arm['cancelled'])

    def test_strategy_unknown_order_is_not_retried(self):
        sid,mock,result=self.strategy_fixture()
        self.client.post('/api/trade/strategies/arm',headers=self.headers,json={
            'id':sid,'acc_id':'123456789123456789','env':'SIMULATE','confirm':'ARM STRATEGY'})
        self.broker.fail=True
        mock.return_value={**result,'bar_time':result['bar_time']+300,'bar_end':int(time.time()),'buy':True}
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.assertEqual(len(self.broker.rows),1)
        self.assertIsNone(self.app.state.strategies.get(sid)['arm'])
        events=self.app.state.strategies.events(sid)
        self.assertTrue(any(e['kind']=='ORDER' and e['detail']['state']=='UNKNOWN' for e in events))

    def test_strategy_gap_and_conflicting_signals_never_trade(self):
        sid,mock,result=self.strategy_fixture()
        mock.return_value={**result,'bar_time':result['bar_time']+900,'bar_end':int(time.time()),'buy':True}
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.assertEqual(self.app.state.strategies.events(sid)[0]['kind'],'SKIPPED')
        mock.return_value={**result,'bar_time':result['bar_time']+1200,'bar_end':int(time.time()),'buy':True,'sell':True}
        self.client.portal.call(self.app.state.strategy_poll_once)
        self.assertEqual(self.app.state.strategies.events(sid)[0]['kind'],'CONFLICT')
        self.assertFalse(self.broker.rows)

    def test_strategy_stale_quote_and_revoked_arm_do_not_place(self):
        from test_strategies import config
        cfg=config();cfg['execution']['flat_only']=False
        owner='test-only';acc='123456789123456789'
        arm={'acc_id':acc,'env':'SIMULATE','expires':time.time()+600}
        self.broker.timestamp='2000-01-01 00:00:00'
        with self.assertRaisesRegex(Exception,'15 秒'):
            self.app.state.engine.strategy_execute(owner,cfg,'BUY',{'close':100},arm)
        self.broker.timestamp=__import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')
        self.app.state.engine.quote_cache.clear()
        with self.assertRaisesRegex(Exception,'授权已取消'):
            self.app.state.engine.strategy_execute(owner,cfg,'BUY',{'close':100},{**arm,'cancelled':True})
        self.assertFalse(self.broker.rows)


if __name__ == '__main__':
    unittest.main()
