import asyncio
from datetime import datetime, timezone
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import ledger, plan_daily


CN = dict(symbol='SH.600519', code='SH.600519', kind='stock')
US = dict(symbol='US.AAPL', code='US.AAPL261120C150000', kind='option',
          expiry='2026-11-20', strike=150, right='C')
AT = '2026-11-19T14:12:05-05:00'


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

        @contextmanager
        def connect():
            db = sqlite3.connect(self.dir.name + '/ledger.db')
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()
        self.connect = connect
        app = FastAPI()
        router = APIRouter(prefix='/api/v1/review')
        ledger.install(app, router, connect)
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def call(self, path, body=None, method=None, market='CN', status=200):
        r = self.client.request(method or ('GET' if body is None else 'POST'), '/api/review/ledger/' + path,
                                params={'market': market}, json=body)
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def test_plan_freezes_at_execution_and_skips_unexecuted(self):
        plan = dict(symbol=CN['symbol'], period='15m', side='BUY', trigger='回踩', size='目标仓位 10%', stop=1300)
        with patch('app.ledger.now', return_value='2026-11-19T01:00:00.000000+00:00'):
            first = self.call('plans', {**plan, 'request_id': '08'})
            self.assertEqual(self.call('plans', {**plan, 'request_id': '08'})['id'], first['id'])
        path = 'plans/' + first['id']
        with patch('app.ledger.now', return_value='2026-11-20T03:00:00.000000+00:00'):
            self.call(path, {**plan, 'stop': 1400, 'revision': 1, 'status': 'closed'}, 'PUT')
        self.call(path, {**plan, 'revision': 1}, 'PUT', status=409)
        fill = dict(**CN, account='A', at=AT, qty=10, price=1500, side='BUY', request_id='f1', plan_id=first['id'])
        record = self.call('fills', fill)
        self.assertEqual(record['plan_snapshot']['stop'], 1300)
        self.assertEqual(self.call(path)['fill_ids'], [record['id']])
        self.assertEqual(self.call('fills', fill)['id'], record['id'])
        self.call('fills', {**fill, 'qty': 11}, status=409)
        self.call('fills', {**fill, 'request_id': 'f2', 'at': '2026-11-18T19:00:00+08:00'}, status=422)
        self.call('fills', {**fill, 'request_id': 'f3', 'at': '2026-11-22T19:00:00+08:00'}, status=422)
        self.call(path, market='US', status=404)
        self.assertEqual(len(self.call(path)['history']), 2)

    def test_structured_chart_plan_draft_and_legacy_agent_update(self):
        condition = dict(id='entry', source='SIXPULSE', period='1d', signal='reds', threshold=6,
                         params={}, confirmation='close')
        details = dict(version=1, title='跨周期计划', entry=dict(join='all', items=[condition]),
                       exit=dict(join='any', items=[dict(condition, id='exit', period='15m', signal='greens', threshold=3)]),
                       entry_note='保留我的入场理由', exit_note='手动观察出场', notes='待 Agent 补充',
                       risk=dict(budget=1000, max_position_percent=15, note='防守价尚待确定'))
        body = dict(symbol='SH.600398', period='60m', side='BUY', trigger='日线六红', status='draft',
                    stop=None, size='', details=details, request_id='chart-plan')
        first = self.call('plans', body)
        self.assertIsNone(first['stop'])
        self.assertEqual(first['details']['entry']['items'][0]['threshold'], 6)
        self.assertEqual(first['details']['exit']['items'][0]['period'], '15m')
        self.assertEqual(self.call('plans', body)['id'], first['id'])
        legacy = dict(symbol=body['symbol'], period='1m', side='BUY', trigger='Agent 补充文字',
                      size='先观察', stop=5.8, status='active', revision=1, request_id='legacy-plan-edit')
        second = self.call('plans/' + first['id'], legacy, 'PUT')
        self.assertEqual(second['details']['entry'], first['details']['entry'])
        self.assertEqual(second['details']['exit'], first['details']['exit'])
        self.assertEqual(second['details']['entry_note'], 'Agent 补充文字')
        self.assertEqual(second['history'][0]['details']['entry_note'], '保留我的入场理由')
        self.assertEqual(self.call('plans/' + first['id'], legacy, 'PUT')['revision'], 2)

    def test_plan_levels_link_unlink_and_delete(self):
        levels = dict(previous_high=1600, previous_low=1200, platform_high=1550,
                      platform_low=1350, gap_up=1450, gap_down=1300, take_profit=1800)
        base = dict(symbol=CN['symbol'], period='1d', side='BUY', trigger='突破平台', status='active',
                    details={'levels': levels}, request_id='level-plan')
        with patch('app.ledger.now', return_value='2026-11-19T01:00:00.000000+00:00'):
            plan = self.call('plans', base)
        path = 'plans/' + plan['id']
        self.assertEqual(self.call(path)['details']['levels'], levels)
        fill = self.call('fills', dict(**CN, account='A', at=AT, qty=10, price=1500,
                                       side='BUY', request_id='unlinked'))
        link = path + '/fills/' + fill['id']
        linked = self.call(link, {'revision': fill['revision']}, 'PUT')
        self.assertEqual(linked['plan_id'], plan['id'])
        self.assertEqual(linked['plan_snapshot']['details']['levels']['take_profit'], 1800)
        self.assertEqual(self.call(path)['fill_ids'], [fill['id']])
        self.call(link, {'revision': fill['revision']}, 'PUT', status=409)
        self.call(path, method='DELETE', status=409)
        unlinked = self.call(link, {'revision': linked['revision']}, 'DELETE')
        self.assertIsNone(unlinked['plan_id'])
        self.assertIsNone(unlinked['plan_snapshot'])
        self.assertEqual(self.call(path)['fill_ids'], [])
        self.assertTrue(self.call(path, method='DELETE')['deleted'])
        self.call(path, status=404)
        self.assertNotIn(plan['id'], [p['id'] for p in self.call('book')['plans']])

    def test_synced_fill_retrospective_link_and_correction(self):
        trade = {**US, 'at': AT, 'qty': 1, 'price': 1.5, 'side': 'BUY', 'broker_id': 'retro'}
        self.sync([trade])
        fill = self.call('book', market='US')['fills'][0]
        with patch('app.ledger.now', return_value='2026-11-21T01:00:00.000000+00:00'):
            plan = self.call('plans', dict(symbol=US['symbol'], period='1d', side='BUY',
                             trigger='观察', request_id='later'), market='US')
        path = 'plans/' + plan['id']
        link = path + '/fills/' + fill['id']
        linked = self.call(link, {'revision': fill['revision']}, 'PUT', 'US')
        self.assertIsNone(linked['plan_snapshot'])
        self.sync([{**trade, 'price': 1.6, 'broker_status': 'CHANGED'}])
        linked = self.call('fills/' + fill['id'], market='US')
        self.assertEqual(linked['plan_id'], plan['id'])
        self.assertIsNone(linked['plan_snapshot'])
        self.call(path, method='DELETE', market='US', status=409)
        self.call(link, {'revision': linked['revision']}, 'DELETE', 'US')
        self.call(path, method='DELETE', market='US')

    def test_limit_up_plan_accepts_text_and_rejects_indicators(self):
        body = dict(symbol=CN['symbol'], period='1d', side='BUY', trigger='回封', request_id='board',
                    details={'strategy': 'limit_up', 'entry_note': '观察回封', 'structure_mode': 'auto'})
        saved = self.call('plans', body)
        self.assertEqual(saved['details']['entry']['items'], [])
        body['details']['entry'] = {'items': [dict(id='x', source='SIXPULSE', period='1d', signal='reds')]}
        self.call('plans', body, status=422)

    def test_text_entry_strategies_round_trip_with_indicator_exits(self):
        condition = dict(id='exit', source='PRICE', period='1d', signal='below', threshold=10)
        for market, symbol in [('CN', CN['symbol']), ('US', US['symbol'])]:
            for strategy, note in [('news', '等待公司公告确认'), ('other', '观察自定义条件')]:
                with self.subTest(market=market, strategy=strategy):
                    details = dict(strategy=strategy, entry_note=note, exit={'items': [condition]})
                    body = dict(symbol=symbol, period='1d', side='BUY', trigger=note, details=details,
                                request_id=f'{market}-{strategy}')
                    saved = self.call('plans', body, market=market)
                    stored = self.call('plans/' + saved['id'], market=market)['details']
                    self.assertEqual((stored['strategy'], stored['entry_note']), (strategy, note))
                    self.assertEqual(stored['exit']['items'][0]['id'], 'exit')
                    details['entry'] = {'items': [dict(condition, id='entry')]}
                    self.call('plans', body, market=market, status=422)

    def test_daily_worker_applies_prior_close_and_retries_missing_bars(self):
        days = {'2026-11-20':'WHOLE', '2026-11-23':'WHOLE', '2026-11-24':'WHOLE'}
        class Calendar:
            def days(self, symbol):
                return days
        clock = datetime(2026,11,24,8,tzinfo=timezone.utc)
        condition = dict(id='avg', source='SMA', signal='above', period='1d', line='main', params={'period':1})
        risk = dict(defense_reference={'period':'1d','label':'MA 均线1 · 当前线位','condition':condition})
        body = dict(symbol=CN['symbol'], period='1d', side='BUY', trigger='等回踩', stop=8, request_id='daily-test',
                    details={'tracking_period':'1d','risk':risk,'levels':{'take_profit':15}})
        with patch('app.ledger.now',return_value='2026-11-22T01:00:00+00:00'):
            plan = self.call('plans',body)
        path = 'plans/'+plan['id']+'/daily'
        rows = [dict(time=0,trade_date=d,session='regular',open=c,close=c,high=h,low=l,volume=100)
                for d,c,h,l in [('2026-11-20',7,8,6),('2026-11-23',10,16,8)]]
        async def quotes(*args,**kwargs):
            return {'bars':rows}
        def run():
            asyncio.run(plan_daily.sweep(self.connect,Calendar(),quotes,clock))
        run()
        result = self.call(path)
        first, = result['items']
        self.assertEqual(self.call('plans/'+plan['id'])['latest_daily'],first)
        self.assertEqual((first['day'],first['open_stop'],first['close_stop'],first['stop_hit'],first['profit_hit']),
                         ('2026-11-23',8,10,True,True))
        self.assertIn('缺少日线',result['status']['error'])
        rows.append(dict(time=1,trade_date='2026-11-24',session='regular',open=12,close=14,high=14,low=11,volume=100))
        run()
        run()
        result = self.call(path)
        self.assertIsNone(result['status']['error'])
        latest,unchanged = result['items']
        self.assertEqual(first,unchanged)
        self.assertEqual((latest['open_stop'],latest['close_stop'],latest['change'],latest['stop_hit'],latest['profit_hit']),
                         (10,14,4,False,False))
        agent = self.client.get('/api/v1/review/ledger/'+path,params={'market':'CN','limit':1})
        self.assertEqual(agent.json()['next_before'],latest['day'])
        self.assertEqual(self.client.get('/api/review/ledger/'+path,params={'market':'CN','before':latest['day']}).json()['items'],[first])
        self.call('plans/'+plan['id'],method='DELETE')
        self.call(path,status=404)

    def test_opt_in_candle_checks_deduplicate_retry_and_summarize(self):
        from app.plan_tracking import Tracker, slots
        days = {'2026-11-20':'WHOLE','2026-11-23':'WHOLE','2026-11-24':'WHOLE'}
        class Calendar:
            calls = 0
            def days(self, symbol):
                self.calls += 1
                return days
        calendar = Calendar()
        intervals = [v for v in slots('CN','15m',days) if v[2]=='2026-11-23']
        self.assertEqual(len(intervals),16)
        candles = [dict(time=a,trade_date=d,session='regular',open=10,low=9,high=11,close=10,volume=100)
                   for a,b,d in intervals]
        fail = False
        requests = []
        async def quotes(symbol,period,mode,**kwargs):
            requests.append(period)
            if fail:
                raise ValueError('offline')
            return {'bars':candles}
        tracker = Tracker(self.connect,calendar,quotes)
        def run(ts):
            asyncio.run(tracker.sweep(datetime.fromtimestamp(ts,timezone.utc)))
        body = dict(symbol=CN['symbol'],period='15m',side='BUY',trigger='观察',stop=9,status='active',request_id='disabled')
        with patch('app.ledger.now',return_value='2026-11-23T01:29:00+00:00'):
            disabled = self.call('plans',body)
            run(intervals[0][1]+10)
            self.assertEqual((requests,calendar.calls),([],0))
            risk = {'defense_reference':{'period':'15m','label':'MA','condition':dict(id='c',source='SMA',period='15m',
                       signal='above',line='main',params={'period':1})}}
            configured = {**body,'details':{'tracking_period':'15m','risk':risk,'levels':{'take_profit':12}}}
            plan = self.call('plans',{**configured,'request_id':'enabled'})
            self.call('plans',{**configured,'request_id':'enabled-again'})
        path='plans/'+plan['id']
        run(intervals[0][0]+300)
        self.assertEqual(requests,[])
        run(intervals[0][1]+10)
        run(intervals[0][1]+40)
        bar, = self.call(path+'/bars')['items']
        self.assertEqual(requests,['15m'])
        self.assertEqual((bar['open_stop'],bar['close_stop'],bar['stop_hit']),(9,10,True))
        fail = True
        run(intervals[1][1]+10)
        failed = self.call(path)['latest_bar']
        self.assertIsNone(failed['stop_hit'])
        self.assertIsNotNone(failed['next_retry'])
        run(intervals[1][1]+60)
        self.assertEqual(len(requests),2)
        fail = False
        run(failed['next_retry']+1)
        recovered = self.call(path)['latest_bar']
        self.assertEqual((recovered['attempts'],recovered['error'],recovered['open_stop']),(2,None,10))
        self.assertEqual(len(self.call(path+'/bars')['items']),2)
        run(intervals[-1][1]+10)
        self.assertEqual(self.call(path+'/daily')['items'][0]['bar_count'],16)
        self.assertEqual(len(self.call(path+'/bars')['items']),16)
        self.assertEqual(self.call('plans/'+disabled['id']+'/bars')['items'],[])

    def test_daily_tracker_checks_once_on_failure_and_after_restart(self):
        from app.plan_tracking import Tracker
        days = {'2026-11-23':'WHOLE','2026-11-24':'WHOLE'}
        class Calendar:
            def days(self,symbol): return days
        calls = []
        async def quotes(*args,**kwargs):
            calls.append(args)
            return {'stale':True,'bars':[]}
        with patch('app.ledger.now',return_value='2026-11-23T01:00:00+00:00'):
            p=self.call('plans',dict(symbol=CN['symbol'],period='1d',side='BUY',trigger='观察',request_id='daily',
                                      details={'tracking_period':'1d'}))
        for hour in (6,7,10,13):
            tracker=Tracker(self.connect,Calendar(),quotes)
            asyncio.run(tracker.sweep(datetime(2026,11,23,hour,1,tzinfo=timezone.utc)))
        self.assertEqual(len(calls),1)
        bar, = self.call('plans/'+p['id']+'/bars')['items']
        self.assertEqual(bar['attempts'],1)
        self.assertIsNone(bar['profit_hit'])
        self.assertGreater(bar['next_retry'],bar['close_time']+23*3600)

    def test_intraday_revision_and_half_day(self):
        day = '2026-11-27'
        days = {day:'MORNING'}
        start, end = plan_daily.session('US',day,'MORNING')
        self.assertEqual(end-start,3.5*3600)
        plan = dict(symbol=US['symbol'],side='SELL',stop=13,revision=2,
                    updated_at=datetime.fromtimestamp(start+60,timezone.utc).isoformat(),
                    details={'levels':{'take_profit':9}})
        bar = dict(high=14,low=8,close=10)
        obs = plan_daily.observation(plan,'US',day,days,bar,[],None)
        self.assertEqual((obs['stop_hit'],obs['profit_hit'],obs['open_stop'],obs['close_stop']),(None,None,None,13))
        plan['updated_at']=datetime.fromtimestamp(start-60,timezone.utc).isoformat()
        obs = plan_daily.observation(plan,'US',day,days,bar,[],None)
        self.assertEqual((obs['stop_hit'],obs['profit_hit']),(True,True))

    def test_one_click_autofill_local_without_gateway_and_preserves_fields(self):
        draft = dict(symbol=CN['symbol'],period='1d',side='BUY',last_close=20,
                     details={'title':'保留标题','entry_note':'我的理由','levels':{'previous_low':18,'platform_low':19,'previous_high':22}})
        with patch.dict('os.environ',{'OPENCLAW_BASE_URL':'','OPENCLAW_GATEWAY_TOKEN':''}), patch('app.plan_autofill.agent_text') as agent:
            result = self.call('autofill',draft)
            self.assertEqual(result['source'],'local')
            f = result['fields']
            self.assertEqual((f['entry_price'],f['stop'],f['take_profit']),(20,19,22))
            self.assertNotIn('title',f)
            self.assertNotIn('entry_note',f)
            board = self.call('autofill',{**draft,'details':{'strategy':'limit_up'}})['fields']
            self.assertIn('回封',board['entry_note'])
            self.assertIn('排板',board['exit_note'])
            self.assertNotIn('entry_price',board)
            self.assertNotIn('stop',board)
            agent.assert_not_called()
        self.assertEqual(self.call('book')['plans'],[])

    @staticmethod
    def quote_frame(chart, period, limit):
        return {'period':period,'mode':'regular','stale':period=='1w',
                'bars':[[1700000000+n,19,21,18,20,100+n] for n in range(limit)]}

    def test_one_click_existing_agent_and_invalid_response(self):
        import io
        import json
        from unittest.mock import Mock
        draft = dict(symbol=CN['symbol'],period='1d',side='BUY',details={'strategy':'limit_up','entry_note':'我的文字'})
        mock = Mock()
        def respond(req,timeout):
            payload=json.loads(req.data)
            self.assertEqual(payload['model'],'openclaw/default')
            self.assertEqual(req.full_url,'http://localhost:18789/v1/chat/completions')
            self.assertNotIn('我的文字',payload['messages'][1]['content'])
            facts=json.loads(payload['messages'][1]['content'])['facts']
            self.assertEqual(facts['period'], '1d')
            self.assertEqual(facts['last_close'],20)
            self.assertEqual([f['period'] for f in facts['frames']], ['1d','1w','1mo'])
            self.assertEqual([len(f['bars']) for f in facts['frames']], [80,40,40])
            self.assertEqual(facts['ohlcv_columns'][-1], 'volume')
            self.assertIn('T+1', facts['settlement'])
            msg={'title':'回封观察','exit_note':'炸板后撤单','risk_note':'观察流动性'}
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(msg)}}]}).encode())
        mock.open.side_effect=respond
        env={'OPENCLAW_BASE_URL':'http://localhost:18789','OPENCLAW_GATEWAY_TOKEN':'unit-test','OPENCLAW_AGENT_ID':''}
        with patch.dict('os.environ',env),patch('app.plan_autofill.sample',side_effect=self.quote_frame),patch('app.agent_client.request.build_opener',return_value=mock):
            result=self.call('autofill',draft)
            self.assertEqual(result['source'],'openclaw')
            self.assertNotIn('entry_note',result['fields'])
            self.assertEqual(result['fields']['title'],'回封观察')
            self.assertIn('T+1',result['fields']['exit_note'])
            self.assertTrue(result['coverage'][1]['stale'])
            self.assertEqual(result['coverage'][0]['count'],80)
            mock.open.side_effect=lambda *args,**kw:io.BytesIO(b'{}')
            self.call('autofill',draft,status=502)
        self.assertEqual(self.call('book')['plans'],[])

    def test_minute_fill_context_and_missing_primary(self):
        env={'OPENCLAW_BASE_URL':'http://localhost','OPENCLAW_GATEWAY_TOKEN':'unit-test'}
        draft=dict(symbol='SH.510300',period='1m',side='BUY',details={})
        with patch.dict('os.environ',env),patch('app.plan_autofill.sample',side_effect=self.quote_frame),patch('app.plan_autofill.agent_text',return_value={'risk_note':'观察'}) as agent:
            result=self.call('autofill',draft)
            facts=agent.call_args.args[3]
            self.assertEqual([f['period'] for f in result['coverage']], ['1m','60m','1d'])
            self.assertIn('核对该品种',facts['settlement'])
        with patch.dict('os.environ',env),patch('app.plan_autofill.sample',return_value={'bars':[]}),patch('app.plan_autofill.agent_text') as agent:
            self.call('autofill',draft,status=503)
            agent.assert_not_called()

    def test_fill_provider_settings_and_failure_history(self):
        from app.plan_agent_settings import install
        install(self.client.app, self.connect)
        path = '/api/trade/agent-settings'
        config = {'provider':'openclaw','url':'http://localhost:18789','token':'saved-secret','agent':'existing'}
        self.assertEqual(self.client.put(path,json=config).status_code,200)
        self.assertNotIn('saved-secret',self.client.get(path).text)
        self.assertEqual(self.client.get('/api/trade/plan-agent').json(),self.client.get(path).json())
        self.assertEqual(self.client.put(path,json={**config,'url':'http://another-host','token':None}).status_code,422)
        draft = dict(request_id='a'*32,symbol=CN['symbol'],period='1d',side='BUY',details={})
        with patch('app.plan_autofill.sample',side_effect=self.quote_frame),patch('app.plan_autofill.agent_text',side_effect=HTTPException(503,'网关超时')) as agent:
            response = self.call('autofill',draft,status=503)
            self.assertIn(draft['request_id'],response['detail'])
            self.call('autofill',draft,status=409)
            agent.assert_called_once()
            self.assertEqual(agent.call_args.args[:3],('http://localhost:18789','saved-secret','existing'))
        row, = self.call('autofill/history')['items']
        self.assertEqual((row['status'],row['provider'],row['error'],row['id']),('failed','openclaw','网关超时',draft['request_id']))
        self.assertTrue(row['finished'])
        self.assertEqual(self.call('autofill/history',market='US')['items'],[])
        self.assertEqual(self.client.put(path,json={'provider':'local'}).status_code,200)
        with patch('app.plan_autofill.agent_text') as agent:
            self.call('autofill',{**draft,'request_id':'b'*32})
            agent.assert_not_called()
        self.assertEqual(self.call('autofill/history')['items'][0]['status'],'success')
        self.assertEqual(self.client.put(path,json={**config,'token':None}).status_code,200)

    def test_invalid_plan_levels(self):
        base = dict(symbol=CN['symbol'], period='1d', side='BUY', trigger='观察', request_id='bad-level')
        self.call('plans', {**base, 'details': {'levels': {'take_profit': -1}}}, status=422)
        self.call('plans', {**base, 'details': {'levels': {'platform_high': 10, 'platform_low': 11}}}, status=422)

    def test_structured_plan_agent_endpoint_and_invalid_conditions(self):
        base = dict(symbol='US.AAPL', period='1w', side='BUY', trigger='周线条件', status='draft', request_id='agent-plan')
        details = dict(entry=dict(items=[dict(id='a', source='SIXPULSE', period='1w', signal='reds')]),
                       exit=dict(items=[dict(id='b', source='SIXPULSE', period='1d', signal='greens', threshold=6)]), author='agent')
        result = self.client.post('/api/v1/review/ledger/plans?market=US', json={**base, 'details': details})
        self.assertEqual(result.status_code, 200, result.text)
        saved = result.json()
        self.assertEqual(saved['details']['exit']['items'][0]['threshold'], 6)
        self.assertEqual(saved['details']['entry']['items'][0]['threshold'], 6)
        self.assertEqual(saved['details']['author'], 'agent')
        for bad in [dict(source='PYTHON'), dict(threshold=3.5), dict(threshold=7), dict(signal='above'),
                    dict(params={'code': 'arbitrary'}), dict(params={'fast': 0}), dict(period='2d')]:
            invalid = {**details, 'entry': {'items': [{**details['entry']['items'][0], **bad}]}}
            self.call('plans', {**base, 'details': invalid}, market='US', status=422)

    def test_old_plan_retry_digest_survives_optional_details(self):
        original = dict(symbol='SH.600519', period='15m', side='BUY', trigger='旧计划', size='100 股', stop=1300.0, status='active')
        with self.connect() as db:
            ledger.schema(db)
            ledger.remember(db, 'CN', 'plan', 'old-client', original, 'f' * 32)
            value = {**original, 'id': 'f' * 32, 'market': 'CN', 'revision': 1,
                     'created_at': AT, 'updated_at': AT}
            db.execute('INSERT INTO ledger_plans VALUES(?,?,?,?,?,?)', ('CN', 'f' * 32, original['symbol'], 1, AT, ledger.dump(value)))
        record = self.call('plans', {**original, 'request_id': 'old-client'})
        self.assertEqual(record['id'], 'f' * 32)

    def test_screenshots_do_not_create_fills_or_erase_hidden_holdings(self):
        other = {**CN, 'code': 'SZ.000001', 'symbol': 'SZ.000001'}
        def submit(as_of, complete, rows, status=200, account='证券'):
            return self.call('positions', dict(account=account, as_of=as_of, complete=complete, rows=rows), status=status)
        first, later, latest = ('2026-11-19T10:00:00+08:00', '2026-11-19T10:10:00+08:00', '2026-11-20T10:00:00+08:00')
        submit(first, True, [{**CN, 'qty': 100}, {**other, 'qty': 80}])
        submit(first, True, [{**CN, 'qty': 25}], account='另一账户')
        submit(later, False, [{**CN, 'qty': 50}])
        submit(later, False, [{**CN, 'qty': 50}])
        replay = submit(first, True, [{**other, 'qty': 80}, {**CN, 'qty': 100}])
        self.assertEqual(replay['status'], 'already_imported')
        submit(later, False, [{**CN, 'qty': 60}], 409)
        submit(first, True, [], 409)
        book = self.call('book')
        self.assertEqual(sorted(p['qty'] for p in book['positions']), [25, 50, 80])
        self.assertEqual(book['fills'], [])
        submit(latest, True, [])
        self.assertEqual([p['qty'] for p in self.call('book')['positions']], [25])

    def us_fill(self, req, **more):
        return {**US, 'account': 'OpenD:REAL:123', 'at': AT, 'qty': 1, 'price': 1.5,
                'side': 'BUY', 'request_id': req, 'manual_confirm': True, **more}

    def sync(self, rows, stamp=AT, positions=None):
        return ledger.ingest_opend(self.connect, 'OpenD:REAL:123', stamp, positions or [], rows)

    def test_broker_idempotence_manual_reconciliation_and_reference_stability(self):
        self.call('fills', self.us_fill('m', manual_confirm=False), market='US', status=422)
        manual = self.call('fills', self.us_fill('m'), market='US')
        detail = 'fills/' + manual['id']
        self.call(detail+'/review', dict(revision=1, execution='无事前计划', quality='良好', note='快速平仓'), 'PUT', 'US')
        trade = {**US, 'at': AT, 'qty': 1, 'price': 1.5, 'side': 'BUY', 'broker_id': '12345678909876543210'}
        self.assertEqual(self.sync([trade])['inserted'], 1)
        broker = self.call(detail, market='US')['candidate_ids'][0]
        match = dict(manual_id=manual['id'], opend_id=broker)
        self.assertEqual(self.call('reconcile', match, market='US')['id'], manual['id'])
        self.call('reconcile', match, market='US')
        self.assertEqual(self.sync([trade])['unchanged'], 1)
        for ident in (manual['id'], broker):
            result = self.call('fills/' + ident, market='US')
            self.assertEqual((result['id'], result['review']['note'], result['broker_id']),
                             (manual['id'], '快速平仓', trade['broker_id']))
        self.sync([{**trade, 'price': 1.6, 'broker_status': 'CHANGED'}])
        self.sync([trade])
        self.assertEqual(self.call(detail, market='US')['price'], 1.6)
        self.sync([{'broker_id': trade['broker_id'], 'broker_status': 'CANCELLED'}])
        self.sync([trade])
        archive = self.call('book', market='US')['fills']
        self.assertEqual(len(archive), 1)
        self.assertEqual((archive[0]['price'], archive[0]['broker_status'], archive[0]['aliases']), (1.6, 'CANCELLED', [broker]))
        self.assertEqual(self.call('fills', self.us_fill('m'), market='US')['id'], manual['id'])

    def test_positions_and_fills_import_atomically(self):
        trade = {**US, 'at': AT, 'qty': 1, 'price': 1.5, 'side': 'BUY', 'broker_id': 'x'}
        with self.assertRaises(HTTPException):
            self.sync([trade, {**trade, 'strike': 100}], positions=[{**US, 'qty': -1}])
        book = self.call('book', market='US')
        self.assertEqual((book['fills'], book['positions'], book['accounts']), ([], [], []))
        self.sync([trade], positions=[{**US, 'qty': -1, 'cost': 0}])
        self.assertEqual(self.call('book', market='US')['positions'][0]['qty'], -1)

    def test_same_minute_partial_fills_stay_separate_group_review_is_atomic(self):
        first, second, foreign = [self.call('fills', self.us_fill(n, account=acc), market='US') for n, acc in (
            ('one', 'a'), ('two', 'a'), ('three', 'b'))]
        url = f"fills/{first['id']}/review"
        review = dict(execution='按计划', quality='良好', note='分两次执行', revision=1)
        self.call(url, {**review, 'group_ids': [second['id'], foreign['id']]}, 'PUT', 'US', status=422)
        self.assertIsNone(self.call('fills/'+second['id'], market='US')['review'])
        self.call(url, {**review, 'group_ids': [second['id']]}, 'PUT', 'US')
        self.assertEqual(self.call('fills/'+second['id'], market='US')['review']['group_ids'], [first['id']])
        self.call(url, {**review, 'group_ids': [], 'revision': 2}, 'PUT', 'US')
        self.assertEqual(self.call('fills/'+second['id'], market='US')['review']['group_ids'], [])
        self.assertEqual(len(self.call('book', market='US')['fills']), 3)

    def test_concurrent_retries_leave_one_record(self):
        payload = self.us_fill('same-retry')
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.call('fills', payload, market='US')['id'], range(8)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.call('book', market='US')['fills']), 1)

    def test_archive_reader_does_not_reserve_writer_lock(self):
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
        self.call('book')
        with ledger.transaction(self.connect) as reader:
            self.assertEqual(ledger.get_book(reader, 'US')['fills'], [])
            self.call('fills', self.us_fill('write-while-reading'), market='US')
            self.assertEqual(ledger.get_book(reader, 'US')['fills'], [])
        self.assertEqual(len(self.call('book', market='US')['fills']), 1)

    def test_reconcile_group_members_preserves_text_and_updates_all_backlinks(self):
        manual, peer = [self.call('fills', self.us_fill(n), market='US') for n in ('duplicate', 'other-fill')]
        trade = {**US, 'at': AT, 'qty': 1, 'price': 1.5, 'side': 'BUY', 'broker_id': 'real'}
        self.sync([trade])
        broker = self.call('fills/'+manual['id'], market='US')['candidate_ids'][0]
        review = dict(revision=1, execution='按计划', quality='良好', note='一笔复盘三条记录',
                      group_ids=[broker, peer['id']])
        self.call('fills/'+manual['id']+'/review', review, 'PUT', 'US')
        merged = self.call('reconcile', dict(manual_id=manual['id'], opend_id=broker), market='US')
        self.assertEqual(merged['review']['group_ids'], [peer['id']])
        other = self.call('fills/'+peer['id'], market='US')
        self.assertEqual(other['review']['group_ids'], [manual['id']])
        stale = {**review, 'revision': merged['revision'], 'group_ids': [], 'group_revisions': {peer['id']: 1}}
        self.call('fills/'+manual['id']+'/review', stale, 'PUT', 'US', status=409)
        self.assertEqual(self.call('fills/'+peer['id'], market='US')['review'], other['review'])
        self.call('fills/'+broker+'/review', {**stale, 'group_revisions': {peer['id']: other['revision']}}, 'PUT', 'US')
        self.assertEqual(self.call('fills/'+peer['id'], market='US')['review']['group_ids'], [])
