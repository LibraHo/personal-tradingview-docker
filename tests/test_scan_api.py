import json
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.scan_api import install, issue_token
from app.scan_service import ScanService

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        self.s=ScanService(SimpleNamespace(connect_db=self.db,status=lambda:{}),None);self.s.init()
        with self.db() as db:
            db.executescript('CREATE TABLE settings(key TEXT,value TEXT);CREATE TABLE symbol_names(symbol TEXT,name TEXT);')
            ws={'markets':{'US':{'groups':[{'id':'a','name':'甲','symbols':['US.AAPL']},{'id':'b','name':'乙','symbols':['US.AAPL','US.MSFT']}]}}}
            db.execute('INSERT INTO settings VALUES(?,?)',('workspace',json.dumps(ws)))
        self.app=FastAPI();install(self.app,self.s);self.client=TestClient(self.app)
        self.read=issue_token(self.db,'read',['read']);self.admin=issue_token(self.db,'admin',['read','manage','tokens'])
    def tearDown(self):self.client.close();self.tmp.cleanup()
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def headers(self,t):return {'Authorization':'Bearer '+t['token']}
    def test_markets_and_bars_use_per_market_price_and_live_sources(self):
        from unittest.mock import AsyncMock, Mock, patch
        sources = {'US': {'history':'equities', 'live':'stream', 'adjustment':'none', 'calendar':'sessions'},
                   'CN': {'history':'cn_bars', 'live':'cn_bars', 'adjustment':'qfq', 'calendar':'sessions'}}
        rows = [{'provider':'equities','adjustment':'none'}, {'provider':'stream','adjustment':'none'}]
        headers = self.headers(self.read)
        with patch.object(self.s, 'market_sources', side_effect=lambda market=None: sources if not market else {market:sources[market]}), \
             patch.object(self.s, 'load', new=AsyncMock(return_value=rows)):
            markets = self.client.get('/api/v1/markets',headers=headers).json()
            self.assertEqual(markets['adjustment'],'MIXED')
            self.assertEqual(markets['market_sources'],sources)
            bars = self.client.get('/api/v1/bars',params={'symbol':'US.AAPL'},headers=headers).json()
            self.assertEqual(bars['source'],'equities')
            self.assertEqual(bars['bar_providers'],['equities','stream'])
            self.assertEqual(bars['adjustment'],'NONE')
        self.s.radar = SimpleNamespace(members=Mock(side_effect=ValueError('boards 不提供板块成分')))
        response = self.client.get('/api/v1/sectors/members',params={'symbol':'SH.BK001'},headers=headers)
        self.assertEqual(response.status_code,422)
        self.assertIn('boards',response.json()['detail'])
    def test_limit_board_read_contract_matches_browser(self):
        from datetime import date, timedelta
        from unittest.mock import patch
        from app.radar import Radar
        import io

        self.s.radar=Radar(None,self.db)
        day=(date.today()-timedelta(days=1)).isoformat()
        def fixture(request, timeout):
            sealed='getTopicZTPool' in request.full_url
            item={'m':1,'c':'600001' if sealed else '600002','n':'样本','p':12345,'amount':200,
                  'ltsz':400,'hs':3.2,'fund':10 if sealed else None}
            return io.BytesIO(json.dumps({'rc':0,'data':{'qdate':day.replace('-',''),'tc':1,'pool':[item]}}).encode())
        path='/api/v1/limit-up'
        self.assertEqual(self.client.get(path).status_code,401)
        with patch.object(self.s.calendar,'days',return_value=[day]), patch('app.market_analytics.urllib.request.urlopen',side_effect=fixture):
            data=self.client.get(path,headers=self.headers(self.read)).json()
            self.assertEqual(data,self.client.get('/api/radar/limit-up',params={'day':day}).json())
            self.assertEqual(data['sealed'][0]['seal_to_turnover_pct'],5)
            self.assertEqual(data['sealed'][0]['seal_to_float_pct'],2.5)
            self.assertIsNone(data['broken'][0]['seal_to_turnover_pct'])
            self.assertEqual(self.client.get(path,params={'day':'2100-01-01'},headers=self.headers(self.read)).status_code,422)
        self.assertIn('LimitBoardStock',self.app.openapi()['components']['schemas'])
    def test_slow_job_history_keeps_other_requests_responsive(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch

        started = threading.Event()
        released = threading.Event()
        responsive = []

        def slow_history(*args):
            started.set()
            responsive.append(released.wait(3))
            return []

        @self.app.get('/test-shared-setting')
        async def shared_setting():
            released.set()
            return {'value': 'light'}

        with patch.object(self.s, 'job_summaries', side_effect=slow_history):
            with TestClient(self.app) as client, ThreadPoolExecutor(max_workers=1) as worker:
                pending = worker.submit(client.get, '/api/scanner/jobs?limit=50')
                try:
                    self.assertTrue(started.wait(3))
                    self.assertEqual(client.get('/test-shared-setting').json(), {'value': 'light'})
                    self.assertEqual(pending.result(timeout=3).status_code, 200)
                finally:
                    released.set()
        self.assertEqual(responsive, [True], 'Job history blocked the event loop')

    def test_job_history_uses_index_and_preserves_legacy_order(self):
        for ident, created in [('older', 100), ('newer', 200), ('tied', 200)]:
            self.s.put('jobs', {'id': ident, 'status': 'completed', 'created': created})
        self.s.put('jobs', {'id': 'legacy', 'status': 'completed'})
        statements = []
        original_db = self.s.db

        @contextmanager
        def traced_db():
            with original_db() as db:
                db.set_trace_callback(statements.append)
                yield db

        self.s.db = traced_db
        try:
            items = self.s.job_summaries(limit=2)
        finally:
            self.s.db = original_db
        self.assertEqual([item['id'] for item in items], ['legacy', 'tied'])
        query = next(statement for statement in statements if statement.startswith('SELECT payload FROM scan_job_history'))
        with self.db() as db:
            plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + query)]
        self.assertFalse(any('USE TEMP B-TREE' in detail for detail in plan), plan)
        following = self.s.job_summaries(cursor='200:tied')
        self.assertEqual([item['id'] for item in following], ['newer', 'older'])

    def test_read_only_request_lookup_recovers_an_unconfirmed_receipt(self):
        from unittest.mock import AsyncMock, patch
        h=self.headers(self.admin)
        saved=self.client.post('/api/v1/plans',headers=h,json={'rules':[{'left':{'name':'PRICE','line':'close'},'op':'gt','right':{'name':'NUMBER','value':10}}]}).json()
        with patch.object(self.s,'execute',new=AsyncMock()):
            submitted=self.client.post('/api/v1/plans/'+saved['id']+'/run',headers=h,json={'request_id':'lookup-intent'}).json()
            recovered=self.client.get('/api/v1/requests/lookup-intent',headers=self.headers(self.read))
            self.assertEqual(recovered.status_code,200,recovered.text)
            self.assertEqual(recovered.json()['job_id'],submitted['id'])
            self.assertEqual(len(self.s.list('jobs')),1)
            self.assertEqual(self.client.get('/api/v1/requests/not-submitted',headers=h).status_code,404)
            self.assertEqual(len(self.s.list('jobs')),1)

    def test_auth_scopes_revoke(self):
        self.assertEqual(self.client.get('/api/v1/watchlists').status_code,401)
        self.assertEqual(self.client.get('/api/v1/watchlists',headers=self.headers(self.read)).status_code,200)
        self.assertEqual(self.client.post('/api/v1/tokens',headers=self.headers(self.read),json={}).status_code,403)
        self.assertEqual(self.client.delete('/api/v1/tokens/'+self.read['id'],headers=self.headers(self.admin)).status_code,200)
        self.assertEqual(self.client.get('/api/v1/watchlists',headers=self.headers(self.read)).status_code,401)
    def test_named_transition_rule_persists_and_copies(self):
        h=self.headers(self.admin)
        for op in ['cross_below','fall','enter_eq','rise_eq','fall_eq']:
            p={'name':'命名条件验收','rules':[{'name':'从上方降到三','left':{'name':'SIXPULSE','line':'GREENS'},'op':op,'right':{'name':'NUMBER','value':3}}]}
            saved=self.client.post('/api/v1/plans',headers=h,json=p)
            self.assertEqual(saved.status_code,200,saved.text)
            ident=saved.json()['id']
            self.assertEqual(self.client.get('/api/v1/plans/'+ident,headers=h).json()['rules'][0]['name'],'从上方降到三')
            copied=self.client.post('/api/v1/plans/'+ident+'/copy',headers=h).json()
            self.assertEqual(copied['rules'][0]['op'],op)
            self.assertEqual(copied['rules'][0]['name'],'从上方降到三')

    def test_crud_and_version_pinning(self):
        h=self.headers(self.admin);p={'rules':[{'left':{'name':'PRICE','line':'close'},'op':'gt','right':{'name':'NUMBER','value':10}}]}
        r=self.client.post('/api/v1/plans',headers=h,json=p);self.assertEqual(r.status_code,200,r.text);ident=r.json()['id']
        m=self.client.post('/api/v1/monitors',headers=h,json={'plan_id':ident,'enabled':False});self.assertEqual(m.status_code,200,m.text)
        self.assertEqual(self.client.put('/api/v1/plans/'+ident,headers=h,json=p).json()['version'],2)
        self.assertEqual(self.s.get('monitors',m.json()['id'])['plan_version'],1)
    def test_history_fields_roundtrip_and_monitor_policy(self):
        h=self.headers(self.admin)
        p={'rules':[{'left':{'name':'PRICE','line':'close','offset':1},'op':'gt','right':{'name':'NUMBER','value':10},'offset':2,'temporal':'streak','window':5,'min_count':2,'max_count':3}]}
        r=self.client.post('/api/v1/plans',headers=h,json=p);self.assertEqual(r.status_code,200,r.text)
        saved=r.json();rule=saved['rules'][0]
        self.assertEqual((rule['offset'],rule['left']['offset'],rule['min_count'],rule['max_count']),(2,1,2,3))
        m=self.client.post('/api/v1/monitors',headers=h,json={'plan_id':saved['id'],'enabled':False,'event_mode':'each_bar'})
        self.assertEqual(m.json()['event_mode'],'each_bar')
        self.assertEqual(self.client.post('/api/v1/monitors',headers=h,json={'plan_id':saved['id'],'event_mode':'invalid'}).status_code,422)

    def test_scope_dedup(self):
        import asyncio
        rows=asyncio.run(self.s.resolve({'kind':'all'}))
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['groups'],['甲','乙'])

    def seed_markets(self):
        ws={'markets':{'US':{'groups':[{'id':'us','name':'美股组','symbols':['US.AAPL','SH.600519']},{'id':'radar-favorites','name':'关注板块','symbols':['US.LIST20077']}]},'CN':{'groups':[{'id':'cn','name':'A股组','symbols':['SH.600519','SZ.000001']},{'id':'radar-favorites','name':'关注板块','symbols':['SH.LIST0002']}]}}}
        with self.db() as db:db.execute("UPDATE settings SET value=? WHERE key='workspace'",(json.dumps(ws),))

    def test_market_scope_is_enforced_on_backend_and_legacy_preserved(self):
        import asyncio
        self.seed_markets()
        us=asyncio.run(self.s.resolve({'kind':'all','market':'US'}))
        cn=asyncio.run(self.s.resolve({'kind':'all','market':'CN'}))
        self.assertEqual({r['symbol'] for r in us},{'US.AAPL','US.LIST20077'})
        self.assertEqual({r['symbol'] for r in cn},{'SH.600519','SZ.000001','SH.LIST0002'})
        self.assertEqual(len(asyncio.run(self.s.resolve({'kind':'all'}))),5)
        self.assertEqual([r['symbol'] for r in asyncio.run(self.s.resolve({'kind':'favorites','market':'US'}))],['US.LIST20077'])
        with self.assertRaisesRegex(ValueError,'当前市场'):
            asyncio.run(self.s.resolve({'kind':'symbols','market':'CN','symbols':['US.AAPL']}))
        with self.assertRaisesRegex(ValueError,'为空'):
            asyncio.run(self.s.resolve({'kind':'groups','market':'CN','groups':['US:us']}))

    def test_market_preview_watchlists_and_job_metadata(self):
        self.seed_markets();h=self.headers(self.admin)
        w=self.client.get('/api/v1/watchlists?market=CN',headers=h)
        self.assertEqual({g['market'] for g in w.json()['groups']},{'CN'})
        preview=self.client.post('/api/v1/scope-preview',headers=h,json={'kind':'groups','market':'CN','groups':['CN:cn']})
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['total'],2)
        self.assertEqual({r['symbol'] for r in preview.json()['rows']},{'SH.600519','SZ.000001'})
        self.assertEqual(self.client.post('/api/v1/scope-preview',headers=h,json={'kind':'all','market':'HK'}).status_code,422)
        self.s.put('jobs',{'id':'job','status':'running','plan':{'scope':{'kind':'all','market':'US'}}})
        self.assertEqual(self.client.get('/api/v1/jobs',headers=h).json()['items'][0]['market'],'US')

    def test_market_member_expansion_dedup_and_cross_market_rejection(self):
        import asyncio
        from unittest.mock import Mock
        self.seed_markets()
        self.s.radar=SimpleNamespace(members=Mock(return_value={'rows':[{'symbol':'SH.600519','name':'茅台'},{'symbol':'SH.600519','name':'茅台'}]}))
        rows=asyncio.run(self.s.resolve({'kind':'members','market':'CN','symbols':['SH.LIST0002','SH.LIST0003']}))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['groups'],['SH.LIST0002','SH.LIST0003'])
        self.s.radar.members.reset_mock()
        with self.assertRaisesRegex(ValueError,'当前市场'):
            asyncio.run(self.s.resolve({'kind':'members','market':'CN','symbols':['US.LIST20077']}))
        self.s.radar.members.assert_not_called()

    def test_async_job_api_controls_idempotency_and_ready_state(self):
        from unittest.mock import AsyncMock, patch
        h=self.headers(self.admin)
        body={'scope':{'kind':'symbols','market':'US','symbols':['US.AAPL']},
              'rules':[{'left':{'name':'PRICE','line':'close'},'op':'gt','right':{'name':'NUMBER','value':10}}]}
        saved=self.client.post('/api/v1/plans',headers=h,json=body).json()
        self.assertTrue(saved['live'])
        endpoint='/api/v1/plans/'+saved['id']+'/run'
        with patch.object(self.s,'execute',new=AsyncMock()):
            started=self.client.post(endpoint,headers={**h,'Idempotency-Key':'intent-1'})
            self.assertEqual(started.status_code,202,started.text)
            job=started.json()
            repeated=self.client.post(endpoint,headers=h,json={'request_id':'intent-1'}).json()
            self.assertEqual(job['id'],repeated['id'])
            self.assertTrue(repeated['reused'])
            progress=self.client.get('/api/v1/jobs/'+job['id']+'?summary=true',headers=h).json()
            self.assertNotIn('results',progress)
            pending=self.client.get('/api/v1/plans/'+saved['id']+'/results',headers=h).json()
            self.assertFalse(pending['ready'])
            self.assertEqual(pending['job_id'],job['id'])
            root='/api/v1/jobs/'+job['id']
            self.assertEqual(self.client.post(root+'/pause',headers=h).json()['status'],'paused')
            self.assertEqual(self.client.post(root+'/resume',headers=h).json()['status'],'queued')
            self.assertEqual(self.client.post(root+'/cancel',headers=h).json()['status'],'cancelled')
            self.assertEqual(self.client.get('/api/v1/jobs?market=US&limit=10',headers=h).json()['items'][0]['id'],job['id'])
        schedule={'kind':'daily','times':['15:10'],'timezone':'Asia/Shanghai','weekdays':[0,1,2,3,4]}
        monitor=self.client.post('/api/v1/monitors',headers=h,json={'plan_id':saved['id'],'enabled':False,'schedule':schedule})
        self.assertEqual(monitor.status_code,200,monitor.text)
        self.assertEqual(monitor.json()['schedule'],schedule)
        ident=monitor.json()['id']
        changed=self.client.put('/api/v1/monitors/'+ident,headers=h,json={'interval_seconds':1800,'schedule':None})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertFalse(changed.json()['enabled'])
        self.assertEqual(changed.json()['interval_seconds'],1800)
        self.assertIsNone(changed.json()['schedule'])
        self.assertEqual(len(self.s.list('monitors')),1)

        bad=self.client.post('/api/v1/monitors',headers=h,json={'plan_id':saved['id'],'enabled':False,'schedule':{'kind':'daily','times':['26:00']}})
        self.assertEqual(bad.status_code,422,bad.text)

    def test_scope_preview_uses_cached_names_without_waiting_for_opend(self):
        from unittest.mock import Mock
        self.s.main.bridge=type('Bridge',(),{'names':Mock(side_effect=AssertionError('network lookup'))})()
        result=self.client.post('/api/scanner/scope-preview',json={'kind':'all','market':'US'})
        self.assertEqual(result.status_code,200,result.text)
        self.s.main.bridge.names.assert_not_called()

    def test_job_history_pagination_keeps_equal_time_records(self):
        h=self.headers(self.admin)
        for index in range(3):
            self.s.put('jobs',{'id':str(index).zfill(32),'status':'completed','created':2000,
                'finished':2001,'done':1,'total':1,'results':[],'plan':{'name':'history','scope':{'market':'CN'}}})
        first=self.client.get('/api/v1/jobs?limit=2',headers=h).json()
        self.assertTrue(first['has_more'])
        following=self.client.get('/api/v1/jobs',headers=h,params={'limit':2,'cursor':first['next_cursor']}).json()
        ids=[item['id'] for item in first['items']+following['items']]
        self.assertEqual(len(set(ids)),3)
        self.assertFalse(following['has_more'])

    def test_health_tracks_finish_time_after_resuming_an_older_job(self):
        for ident,created,finished in [('old',2000,5000),('new',3000,4000)]:
            self.s.put('jobs',{'id':ident,'status':'completed','created':created,'finished':finished})
        result=self.client.get('/api/v1/health',headers=self.headers(self.read)).json()
        self.assertEqual(result['last_successful_scan'],5000)

    def test_sector_name_from_source_catalog(self):
        with self.db() as db:
            db.execute('CREATE TABLE radar_cache(key TEXT,payload TEXT)')
            db.execute('INSERT INTO radar_cache VALUES(?,?)',('catalog:US:concept',json.dumps({'rows':[{'symbol':'US.LIST20077','name':'半导体精选'}]})))
        self.assertEqual(self.s.watchlists()['names']['US.LIST20077'],'半导体精选')

if __name__=='__main__':unittest.main()
