import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


class NotificationTests(unittest.TestCase):
    def setUp(self):
        from app.notifications import Notifications
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db'
        with self.db() as db:
            db.executescript('CREATE TABLE scan_events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,monitor_id TEXT,payload TEXT); CREATE TABLE scan_monitors(id TEXT PRIMARY KEY,payload TEXT);')
            db.execute('INSERT INTO scan_monitors VALUES(?,?)', ('m1', json.dumps({'id':'m1','name':'日线监控','enabled':True})))
        self.service = Notifications(self.db)
        self.service.init()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def channel(self, **changes):
        return self.service.save({'name':'我的微信','url':'https://notify.example.test/send', 'headers':{'Authorization':'Bearer test-token'},
            'format':'form','title_field':'title','body_field':'desp','success_field':'code','success_value':'0',
            'enabled':True,'monitor_ids':['m1'],'confirmation':'confirmed','daily_limit':5, **changes})

    def event(self, ident='e1', confirmation='confirmed', monitor='m1'):
        event = {'event_id':ident,'monitor_id':monitor,'symbol':'US.AAPL','name':'苹果',
                 'period':'1d','time':1700000000,'confirmation':confirmation,'detected_at':1700000001}
        with self.db() as db:
            db.execute('INSERT INTO scan_events(event_id,monitor_id,payload) VALUES(?,?,?)', (ident,monitor,json.dumps(event)))

    def test_future_events_only_and_restart_deduplicates(self):
        self.event('old')
        channel = self.channel()
        self.event('preview', 'preview')
        self.event('other', monitor='another')
        self.event()
        self.service.collect()
        self.service.init()
        self.service.collect()
        records = self.service.records()
        self.assertEqual([(x['event_id'],x['channel_id']) for x in records], [('e1',channel['id'])])
        self.assertNotIn('notify.example.test', json.dumps(self.service.channels()))
        self.assertNotIn('test-token', json.dumps(self.service.channels()))

    def test_api_rejection_retry_and_acknowledgement_are_persisted(self):
        channel = self.channel()
        self.event()
        self.service.collect()
        with patch('urllib.request.OpenerDirector.open', return_value=io.BytesIO(b'{"code":40001}')):
            self.service.deliver_one()
        record = self.service.records()[0]
        self.assertEqual(record['status'], 'retry')
        self.assertEqual(record['attempts'], 1)
        with self.db() as db:
            db.execute('UPDATE notification_outbox SET next_attempt=0')
            db.execute('UPDATE notification_channels SET last_attempt=0')
        self.service.init()
        with patch('urllib.request.OpenerDirector.open', return_value=io.BytesIO(b'{"code":0,"data":{"pushid":"p1"}}')) as send:
            self.service.deliver_one()
        self.assertEqual(self.service.records()[0]['status'], 'accepted')
        self.assertEqual(self.service.records()[0]['attempts'], 2)
        self.assertEqual(send.call_args.args[0].method, 'POST')
        self.assertEqual(send.call_args.args[0].full_url, 'https://notify.example.test/send')
        self.assertEqual(send.call_args.args[0].get_header('Authorization'), 'Bearer test-token')
        self.assertIn('desp=', send.call_args.args[0].data.decode())
        self.service.deliver_one()
        self.assertEqual(self.service.records()[0]['attempts'], 2)

    def test_unknown_transport_outcome_is_not_blindly_retried_or_leaked(self):
        self.channel()
        self.event()
        self.service.collect()
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('https://notify.example.test/send')):
            self.service.deliver_one()
        record = self.service.records()[0]
        self.assertEqual(record['status'], 'unknown')
        self.assertNotIn('notify.example.test', json.dumps(record))

    def test_disable_cancels_pending_and_keeps_secret_when_omitted(self):
        c = self.channel()
        self.event()
        self.service.collect()
        c = self.service.save({**c, 'enabled':False}, c['id'])
        self.assertTrue(c['has_url'])
        self.assertEqual(self.service.records()[0]['status'], 'cancelled')

    def test_daily_limit_and_test_share_persistent_budget(self):
        c = self.channel(daily_limit=1)
        self.service.test(c['id'])
        self.event()
        self.service.collect()
        with patch('urllib.request.OpenerDirector.open', return_value=io.BytesIO(b'{"code":0}')):
            self.service.deliver_one()
            with self.db() as db:
                db.execute('UPDATE notification_channels SET last_attempt=0')
            self.service.deliver_one()
        self.assertEqual([r['status'] for r in self.service.records()].count('accepted'), 1)
        self.assertEqual([r['status'] for r in self.service.records()].count('pending'), 1)

    def test_invalid_channel_or_monitor_rejected(self):
        for change in [{'format':'unknown'}, {'url':'file:///etc/passwd'}, {'monitor_ids':['missing']}]:
            with self.assertRaises(ValueError):
                self.channel(**change)

    def test_custom_json_request_works_against_a_local_http_receiver(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        received=[]
        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path,self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200);self.end_headers();self.wfile.write(b'{"result":{"ok":true}}')
            def log_message(self,*args):
                pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Receiver)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.channel(url=f'http://127.0.0.1:{server.server_port}/hook',format='json',title_field='subject',body_field='content',extra_fields={'room':'alerts'},success_field='result.ok',success_value='true')
            self.event();self.service.collect();self.service.deliver_one()
            self.assertEqual(self.service.records()[0]['status'],'accepted')
            self.assertEqual(received[0][0:2],('/hook','Bearer test-token'))
            self.assertEqual(received[0][2]['room'],'alerts')
            self.assertIn('subject',received[0][2]);self.assertIn('content',received[0][2])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_changed_url_needs_explicit_headers_and_http_success_can_have_empty_body(self):
        c=self.channel()
        with self.assertRaises(ValueError):
            self.service.save({**c,'url':'https://another.example.test/hook'},c['id'])
        c=self.service.save({**c,'url':'https://another.example.test/hook','headers':{},'success_field':''},c['id'])
        self.assertFalse(c['has_headers'])
        self.event();self.service.collect()
        with patch('urllib.request.OpenerDirector.open',return_value=io.BytesIO(b'')):
            self.service.deliver_one()
        self.assertEqual(self.service.records()[0]['status'],'accepted')

    def test_json_configuration_api_keeps_url_and_headers_private(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.notification_api import install
        app=FastAPI();install(app,self.db)
        with TestClient(app) as client:
            response=client.post('/api/trade/notifications/channels',json={'name':'Webhook','url':'https://example.test/private-key','headers':{'Authorization':'Bearer private-token'},'monitor_ids':['m1']})
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn('private-key',response.text);self.assertNotIn('private-token',response.text)
            config=client.get('/api/trade/notifications').json()
            self.assertTrue(config['channels'][0]['has_url'])
            self.assertTrue(config['channels'][0]['has_headers'])
            self.assertNotIn('private-token',json.dumps(config))

    def test_interrupted_request_is_unknown_and_api_read_does_not_reset_active_send(self):
        self.channel()
        self.event()
        self.service.collect()
        with self.db() as db:
            db.execute("UPDATE notification_outbox SET status='sending'")
        self.service.init()
        self.assertEqual(self.service.records()[0]['status'], 'sending')
        self.service.init(recover=True)
        self.assertEqual(self.service.records()[0]['status'], 'unknown')

    def test_configuration_reads_and_test_do_not_fetch_market_data(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.notification_api import install
        app = FastAPI()
        install(app, self.db)
        with TestClient(app) as client:
            c = self.channel()
            response = client.get('/api/trade/notifications')
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('notify.example.test', response.text)
            self.assertNotIn('test-token', response.text)
            response = client.post('/api/trade/notifications/channels/'+c['id']+'/test')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'pending')
            self.assertEqual(client.post('/api/trade/notifications/channels/'+c['id']+'/test').status_code, 422)

    def test_scanner_produced_event_enters_outbox_without_another_market_request(self):
        from app.scan_service import ScanService
        from types import SimpleNamespace
        with self.db() as db:
            db.execute('ALTER TABLE scan_events ADD COLUMN symbol TEXT')
        scanner = ScanService(SimpleNamespace(connect_db=self.db),None)
        scanner.init()
        self.channel()
        monitor={'id':'m1','activated_at':0,'interval_seconds':300}
        plan={'id':'p1','version':1,'rules':[]}
        values=[{'time':1700000000,'close_time':1700000300,'match':True,'valid':True,'confirmed':True}]
        row={'symbol':'US.AAPL','period':'1d'}
        scanner.record(monitor,plan,row,values)
        scanner.record(monitor,plan,row,values)
        self.service.collect()
        with patch('urllib.request.OpenerDirector.open',return_value=io.BytesIO(b'{"code":0}')):
            self.service.deliver_one()
        self.assertEqual(len(self.service.records()),1)
        self.assertEqual(self.service.records()[0]['status'],'accepted')


if __name__ == '__main__':
    unittest.main()
