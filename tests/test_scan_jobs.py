import asyncio
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo

from app.scan_service import ScanService

def plan(symbols=None):
    return {'id':'plan','version':1,'name':'queue test','periods':['1d'],'live':True,'lookback':1,
            'scope':{'kind':'symbols','market':'US','symbols':symbols or ['US.AAPL']},
            'rules':[{'left':{'name':'PRICE','line':'close'},'op':'gt',
                      'right':{'name':'NUMBER','value':10}}]}

def candles():
    return [{'time':100,'close_time':200,'confirmed':False,'open':12,'high':13,'low':11,'close':12,'volume':100}]

class ScanJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/'market.sqlite3'
        self.service=ScanService(SimpleNamespace(connect_db=self.db),None)
        self.service.init()
        with self.db() as db:
            db.executescript('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE symbol_names(symbol TEXT,name TEXT);')
        async def resolve(scope, **options):
            return [{'symbol':symbol,'name':symbol,'groups':[]} for symbol in scope['symbols']]
        self.service.resolve=AsyncMock(side_effect=resolve)
        self.service.load=AsyncMock(return_value=candles())

    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path,timeout=10)
        connection.row_factory=sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def asyncTearDown(self):
        await self.service.stop()
        self.directory.cleanup()

    async def state(self,ident,status):
        for attempt in range(150):
            job=self.service.get('jobs',ident)
            if job['status']==status:
                return job
            await asyncio.sleep(.01)
        self.fail('Expected '+status+', got '+job['status']+' '+str(job.get('error')))

    async def test_retry_preserves_history_and_only_rechecks_failed_pairs(self):
        config = plan()
        config['periods'] = ['1d','1w']
        self.service.load.side_effect = [candles(), ValueError('missing weekly candle')]
        first = await self.service.submit(config)
        parent = await self.state(first['id'], 'partial')
        self.assertIn('missing weekly candle', parent['failures'][0]['error'])
        self.service.load.side_effect = None
        child = await self.service.retry(parent['id'], 'api')
        result = await self.state(child['id'], 'completed')
        self.assertEqual([r['period'] for r in result['results']], ['1w'])
        self.assertEqual(result['retry_of'], parent['id'])
        self.assertEqual((await self.service.retry(parent['id'], 'api'))['id'], child['id'])
        self.assertEqual(self.service.get('jobs',parent['id'])['failures'],parent['failures'])

    async def test_afternoon_120m_last_confirmed_close(self):
        from app.scan_calendar import latest_intraday_close
        now = datetime(2026,11,23,14,30,tzinfo=ZoneInfo('Asia/Shanghai'))
        latest = latest_intraday_close('SH.600000','120m',{'2026-11-23':'WHOLE'},now.timestamp())
        self.assertEqual(latest,now.replace(hour=11,minute=30).timestamp())

    async def test_audit_freezes_selected_excluded_missing_groups_and_full_parameters(self):
        workspace={'markets':{'US':{'groups':[
            {'id':'a','name':'科技组','symbols':['US.AAPL']},
            {'id':'b','name':'金融组','symbols':['US.JPM']},
            {'id':'empty','name':'空组','symbols':[]}]}}}
        with self.db() as db:
            db.execute("INSERT INTO settings VALUES('workspace',?)",(json.dumps(workspace),))
        target=plan()
        target['scope']={'kind':'groups','market':'US','groups':['US:a','US:empty','US:missing']}
        target['rules'][0]['left']={'name':'MACD','line':'macd','params':{'fast':8}}
        job=await self.service.submit(target,source='browser')
        await self.service.control(job['id'],'pause')
        audit=self.service.get('jobs',job['id'])
        snapshot=audit['scope_snapshot']
        self.assertEqual([g['name'] for g in snapshot['selected_groups']],['科技组','空组'])
        self.assertEqual([g['name'] for g in snapshot['excluded_groups']],['金融组'])
        self.assertEqual(snapshot['missing_groups'],['US:missing'])
        self.assertEqual(snapshot['empty_groups'],['US:empty'])
        self.assertEqual(snapshot['selected_groups'][0]['symbols'],['US.AAPL'])
        self.assertEqual(audit['execution_plan']['rules'][0]['left']['params'],{'fast':8,'slow':26,'signal':9})
        workspace['markets']['US']['groups'][0].update(name='后来改名',symbols=['US.MSFT'])
        with self.db() as db:
            db.execute("UPDATE settings SET value=? WHERE key='workspace'",(json.dumps(workspace),))
        self.assertEqual(self.service.get('jobs',job['id'])['scope_snapshot'],snapshot)
        listing=self.service.job_summaries()[0]
        self.assertEqual(listing['source'],'browser')
        self.assertEqual(listing['condition_count'],1)
        self.assertEqual(listing['scope_summary']['selected_groups'],['科技组','空组'])
        self.assertNotIn('execution_plan',listing)

    async def test_queued_group_scope_uses_submission_members_even_after_watchlist_changes(self):
        workspace={'markets':{'US':{'groups':[{'id':'a','name':'原分组','symbols':['US.AAPL']}]}}}
        with self.db() as db:
            db.execute("INSERT INTO settings VALUES('workspace',?)",(json.dumps(workspace),))
        target=plan();target['scope']={'kind':'all','market':'US'}
        job=await self.service.submit(target)
        await self.service.control(job['id'],'pause')
        workspace['markets']['US']['groups'][0]['symbols']=['US.MSFT']
        with self.db() as db:
            db.execute("UPDATE settings SET value=? WHERE key='workspace'",(json.dumps(workspace),))
        from app.scan_service import ScanService
        self.service.resolve=ScanService.resolve.__get__(self.service)
        await self.service.control(job['id'],'resume')
        await self.state(job['id'],'completed')
        self.assertEqual(self.service.load.call_args_list[0].args[0],'US.AAPL')

    async def test_history_backfills_legacy_jobs_and_refreshes_after_controls(self):
        legacy=plan()
        with self.db() as db:
            db.execute("INSERT INTO scan_jobs VALUES(?,?,?)",('legacy',json.dumps({'id':'legacy','status':'completed','created':10,'plan':legacy,'results':[]}),11))
        self.service.init()
        with self.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM scan_job_history WHERE id='legacy'").fetchone()[0],1)
        job=await self.service.submit(plan())
        await self.service.control(job['id'],'pause')
        rows=self.service.job_summaries()
        self.assertEqual(rows[0]['status'],'paused')
        self.assertEqual(rows[-1]['id'],'legacy')
        self.assertEqual(rows[-1]['condition_count'],1)

    async def test_submit_returns_before_slow_scope_and_keeps_snapshot(self):
        release=asyncio.Event()
        async def slow(scope, **options):
            await release.wait()
            return [{'symbol':'US.AAPL','name':'Apple','groups':[]}]
        self.service.resolve.side_effect=slow
        original=plan()
        job=await asyncio.wait_for(self.service.submit(original),timeout=.15)
        original['rules'][0]['right']['value']=999
        self.assertEqual(job['status'],'queued')
        self.assertEqual(self.service.get('jobs',job['id'])['plan']['rules'][0]['right']['value'],10)
        release.set()
        finished=await self.state(job['id'],'completed')
        self.assertEqual(finished['done'],1)
        self.assertGreaterEqual(finished['finished'],finished['started'])

    async def test_idempotency_active_reuse_and_cached_result(self):
        first=await self.service.submit(plan(),request_id='user-intent-1')
        second=await self.service.submit(plan(),request_id='user-intent-1')
        self.assertEqual(first['id'],second['id'])
        self.assertTrue(second['reused'])
        active=await self.service.submit(plan(),force=True)
        self.assertEqual(active['id'],first['id'])
        await self.state(first['id'],'completed')
        cached=await self.service.submit(plan())
        self.assertEqual(cached['id'],first['id'])
        self.assertEqual(cached['reuse_reason'],'fresh_result')
        await self.service.submit(plan(['US.MSFT']),request_id='different-intent')
        with self.assertRaises(ValueError):
            await self.service.submit(plan(['US.MSFT']),request_id='user-intent-1')
        fresh=await self.service.submit(plan(),force=True)
        self.assertNotEqual(fresh['id'],first['id'])

    async def test_api_reuses_the_active_following_monitor_task(self):
        configuration=plan()
        monitor=self.service.put('monitors',{'id':'monitor','plan':configuration,'enabled':False,
            'follow_watchlists':True,'interval_seconds':120,'activated_at':0})
        monitored=await self.service.submit(configuration,monitor)
        requested=await self.service.submit(configuration,force=True)
        self.assertEqual(monitored['id'],requested['id'])
        self.assertTrue(requested['reused'])

    async def test_fifo_queue_and_paused_job_does_not_block_others(self):
        release=asyncio.Event()
        order=[]
        async def load(symbol,period,live):
            order.append(symbol)
            if symbol=='US.AAPL':
                await release.wait()
            return candles()
        self.service.load.side_effect=load
        first=await self.service.submit(plan())
        await self.state(first['id'],'running')
        second=await self.service.submit(plan(['US.MSFT']))
        paused=await self.service.control(second['id'],'pause')
        self.assertEqual(paused['status'],'paused')
        third=await self.service.submit(plan(['US.NVDA']))
        self.assertEqual(self.service.job_view(third['id'])['queue_position'],1)
        release.set()
        await self.state(third['id'],'completed')
        self.assertEqual(self.service.get('jobs',second['id'])['status'],'paused')
        await self.service.control(second['id'],'resume')
        await self.state(second['id'],'completed')
        self.assertEqual(order,['US.AAPL','US.NVDA','US.MSFT'])

    async def test_running_pause_resume_keeps_completed_items_and_cancel(self):
        entered=asyncio.Event()
        release=asyncio.Event()
        order=[]
        async def load(symbol,period,live):
            order.append(symbol)
            if symbol=='US.MSFT' and not release.is_set():
                entered.set()
                await release.wait()
            return candles()
        self.service.load.side_effect=load
        job=await self.service.submit(plan(['US.AAPL','US.MSFT']))
        await asyncio.wait_for(entered.wait(),2)
        self.assertEqual(self.service.get('jobs',job['id'])['done'],1)
        self.assertEqual((await self.service.control(job['id'],'pause'))['status'],'pausing')
        release.set()
        await self.state(job['id'],'paused')
        await self.service.control(job['id'],'resume')
        done=await self.state(job['id'],'completed')
        self.assertEqual(done['done'],2)
        self.assertEqual(order.count('US.AAPL'),1)
        cancelled=await self.service.submit(plan(['US.TSLA']))
        self.assertEqual((await self.service.control(cancelled['id'],'cancel'))['status'],'cancelled')
        self.assertIsNotNone(self.service.get('jobs',cancelled['id'])['finished'])

    async def test_restart_recovers_the_same_jobs_and_preserves_fifo(self):
        release=asyncio.Event()
        async def blocked(symbol,period,live):
            await release.wait()
            return candles()
        self.service.load.side_effect=blocked
        first=await self.service.submit(plan())
        await self.state(first['id'],'running')
        second=await self.service.submit(plan(['US.MSFT']))
        await self.service.stop()
        self.assertEqual(self.service.get('jobs',second['id'])['status'],'queued')
        previous=self.service
        self.service=ScanService(previous.main,None)
        self.service.resolve=previous.resolve
        self.service.load=AsyncMock(return_value=candles())
        await self.service.start()
        await self.state(second['id'],'completed')
        await self.state(first['id'],'completed')
        self.assertEqual(len(self.service.list('jobs')),2)
        self.assertEqual([call.args[0] for call in self.service.load.call_args_list],['US.AAPL','US.MSFT'])

    async def test_restart_recovers_committed_progress_before_final_checkpoint(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def load(symbol, period, live):
            if symbol == 'US.AAPL':
                raise ValueError('missing')
            entered.set()
            await release.wait()
            return candles()
        self.service.load.side_effect = load
        job = await self.service.submit(plan(['US.AAPL', 'US.MSFT']))
        ident = job['id']
        runner = self.service.runners[ident]
        await asyncio.wait_for(entered.wait(), 2)
        with self.db() as db:
            base = json.loads(db.execute('SELECT payload FROM scan_jobs WHERE id=?', (ident,)).fetchone()[0])
            self.assertEqual(base['results'], [])
        self.assertEqual(self.service.job_summaries()[0]['failure_count'], 1)
        # Startup after process loss sees only the committed database.
        recovered = ScanService(self.service.main, None)
        recovered.init()
        interrupted = recovered.get('jobs', ident)
        self.assertEqual((interrupted['status'], interrupted['done']), ('interrupted', 1))
        self.assertEqual(interrupted['results'], interrupted['failures'])
        release.set()
        await runner
        recovered.load = AsyncMock(return_value=candles())
        await recovered.control(ident, 'resume')
        await recovered.runners[ident]
        final = recovered.get('jobs', ident)
        self.assertEqual((final['status'], final['done']), ('partial', 2))
        self.assertEqual([row['symbol'] for row in final['results']], ['US.AAPL', 'US.MSFT'])
        recovered.load.assert_awaited_once_with('US.MSFT', '1d', live=True)

    async def test_results_readiness_and_watchlist_change_invalidates_cache(self):
        target=plan()
        first=await self.service.submit(target)
        pending=self.service.plan_results(target)
        self.assertFalse(pending['ready'])
        self.assertEqual(pending['job_id'],first['id'])
        await self.state(first['id'],'completed')
        result=self.service.plan_results(target)
        self.assertTrue(result['ready'])
        self.assertTrue(result['fresh'])
        self.assertEqual(len(result['results']),1)
        changed=copy.deepcopy(target)
        changed['rules'][0]['right']['value']=30
        self.assertEqual(self.service.plan_results(changed)['status'],'not_started')
        summary=self.service.job_summaries()[0]
        self.assertNotIn('results',summary)
        self.assertIn('created',summary)
        self.assertIn('progress_percent',summary)

class AuditFailureTests(unittest.TestCase):
    def test_missing_indicator_names_the_condition_output_and_period(self):
        from app.scan_engine import evaluate
        configuration=plan()
        configuration['rules'][0]['left']={'name':'SMA','line':'main','params':{'period':20}}
        with self.assertRaisesRegex(ValueError,'SMA.main.*1d'):
            evaluate({'1d':candles()},configuration,'1d')

class ScheduleTests(unittest.TestCase):
    def test_daily_slots_validate_timezone_and_weekdays(self):
        from app.scan_service import validate_schedule, schedule_slot
        schedule=validate_schedule({'kind':'daily','times':['15:10','09:35'],'timezone':'Asia/Shanghai'})
        now=datetime(2026,11,19,15,11,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        self.assertEqual(datetime.fromtimestamp(schedule_slot(schedule,now),ZoneInfo('Asia/Shanghai')).strftime('%H:%M'),'15:10')
        self.assertGreater(schedule_slot(schedule,now,upcoming=True),now)
        for invalid in ({'kind':'daily','times':['25:00']},{'kind':'daily','times':['15:10'],'timezone':'Bad/Timezone'}):
            with self.assertRaises(ValueError):
                validate_schedule(invalid)

    def test_schedule_market_date_uses_the_selected_timezone(self):
        from app.scan_service import validate_schedule
        service=ScanService(SimpleNamespace(connect_db=None),None)
        service.calendar=SimpleNamespace(days=lambda symbol:{'2026-11-18':'WHOLE'})
        now=datetime(2026,11,19,6,1,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        monitor={'plan':plan(),'trading_only':True,'schedule':validate_schedule(
            {'kind':'daily','times':['06:00'],'timezone':'Asia/Shanghai','weekdays':[1,2,3,4,5]})}
        due,slot=asyncio.run(service.monitor_due(monitor,now))
        self.assertTrue(due)
        monitor['last_schedule_slot']=slot
        self.assertFalse(asyncio.run(service.monitor_due(monitor,now))[0])

if __name__=='__main__':
    unittest.main()
