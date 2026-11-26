import asyncio
from contextlib import contextmanager
from datetime import datetime
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch
from app.scan_calendar import close_time, annotate
from app.scan_engine import evaluate
from app.scan_service import ScanService
from app.market_analytics import ladder


def stamp(day,hour=0,minute=0,us=False):
    return datetime.fromisoformat(day).replace(hour=hour,minute=minute,tzinfo=ZoneInfo('America/New_York' if us else 'Asia/Shanghai')).timestamp()
def operand(name='PRICE',line='close',value=10):return {'name':name,'line':line,'params':{},'value':value}
def plan(op='reach'):
    return {'id':'p','version':1,'rules':[{'left':operand(),'op':op,'right':operand('NUMBER',value=10)}],'periods':['1d'],'lookback':1}
def bars(values):return [dict(time=i*100,close_time=(i+1)*100,confirmed=True,open=x,high=x+1,low=x-1,close=x,volume=100) for i,x in enumerate(values)]

class CalendarTests(unittest.TestCase):
    def test_cn_close_without_next_bar_and_lunch(self):
        days={'2026-11-16':'WHOLE'}
        self.assertEqual(close_time(stamp('2026-11-16',11), 'SH.600000','60m',days),stamp('2026-11-16',11,30))
        b=[{'time':stamp('2026-11-16')}]
        self.assertFalse(annotate(b,'SH.600000','1d',days,stamp('2026-11-16',14,59))[0]['confirmed'])
        self.assertTrue(annotate(b,'SH.600000','1d',days,stamp('2026-11-16',15))[0]['confirmed'])
    def test_us_dst_early_close_and_holiday_week(self):
        days={'2026-11-25':'WHOLE','2026-11-27':'MORNING','2026-07-01':'WHOLE'}
        self.assertEqual(close_time(stamp('2026-11-27',us=True),'US.AAPL','1d',days),stamp('2026-11-27',13,us=True))
        self.assertEqual(close_time(stamp('2026-11-23',us=True),'US.AAPL','1w',days),stamp('2026-11-27',13,us=True))
        self.assertEqual(datetime.fromtimestamp(close_time(stamp('2026-07-01',us=True),'US.AAPL','1d',days),ZoneInfo('UTC')).hour,20)
        self.assertEqual(datetime.fromtimestamp(close_time(stamp('2026-11-25',us=True),'US.AAPL','1d',days),ZoneInfo('UTC')).hour,21)

class EngineTests(unittest.TestCase):
    def test_transition_boundaries_exhaustive(self):
        from app.scan_engine import compare
        definitions = {
            'cross_above':lambda p,c:p<=3 and c>3,
            'cross_below':lambda p,c:p>=3 and c<3,
            'reach':lambda p,c:p<3 and c>=3,
            'fall':lambda p,c:p>3 and c<=3,
            'enter_eq':lambda p,c:p!=3 and c==3,
            'rise_eq':lambda p,c:p<3 and c==3,
            'fall_eq':lambda p,c:p>3 and c==3,
        }
        for op,expected in definitions.items():
            for previous in range(7):
                for current in range(7):
                    with self.subTest(op=op,previous=previous,current=current):
                        self.assertEqual(compare([previous,current],[3,3],op,1),expected(previous,current))
            self.assertIsNone(compare([None,3],[3,3],op,1))
            self.assertIsNone(compare([3],[3],op,0))

    def test_named_rule_and_actual_operand_dates(self):
        p=plan('lte');p['rules'][0].update(name='历史绿灯阈值')
        p['rules'][0]['left']['offset']=3
        p['rules'][0]['right']['value']=3
        result=evaluate({'1d':bars([4,6,1,2])},p,'1d')[-1]
        self.assertFalse(result['match'])
        self.assertEqual(result['checks'][0]['left'],4)
        self.assertEqual(result['checks'][0]['left_time'],0)
        self.assertEqual(result['checks'][0]['name'],'历史绿灯阈值')
        p['rules'][0]['left']['offset']=0
        self.assertTrue(evaluate({'1d':bars([4,6,1,2])},p,'1d')[-1]['match'])
        self.assertTrue(evaluate({'1d':bars([4,6,1,0])},p,'1d')[-1]['match'])

    def test_first_threshold_not_repeated(self):
        self.assertTrue(evaluate({'1d':bars([9,10])},plan(),'1d')[-1]['match'])
        self.assertFalse(evaluate({'1d':bars([9,10,11])},plan(),'1d')[-1]['match'])
        self.assertTrue(evaluate({'1d':bars([9,10,9,10])},plan(),'1d')[-1]['match'])
    def test_cross_timeframe_no_future(self):
        p=plan('gt');p['rules'][0]['period']='1w'
        weekly=bars([11,9]);weekly[0]['close_time']=200;weekly[1]['close_time']=400
        self.assertTrue(evaluate({'1d':bars([1,2,3]),'1w':weekly},p,'1d')[-1]['match'])
        self.assertFalse(evaluate({'1d':bars([1,2,3,4]),'1w':weekly},p,'1d')[-1]['match'])
    def test_missing_not_valid_even_or(self):
        p=plan();p['join']='any';p['rules'].append({'left':{'name':'SMA','line':'main','params':{'period':20}},'op':'gt','right':operand('NUMBER',value=1)})
        with self.assertRaisesRegex(ValueError,'不足'):evaluate({'1d':bars([9,11])},p,'1d')
    def test_volume_multiplier(self):
        p=plan('gt');p['rules'][0]={'left':operand('PRICE','volume'),'op':'gt','right':{'name':'VOLUME','line':'average','params':{'period':2},'scale':1.5}}
        b=bars([9,11]);b[-1]['volume']=400
        self.assertTrue(evaluate({'1d':b},p,'1d')[-1]['match'])

    def test_recursive_indicator_seed_is_not_sufficient_history(self):
        p=plan('gt');p['rules'][0]['left']={'name':'EMA','line':'main','params':{'period':20}}
        with self.assertRaisesRegex(ValueError,'不足'):evaluate({'1d':bars([9,11,12])},p,'1d')

class TemporalTests(unittest.TestCase):
    def test_second_third_day_and_reset(self):
        p=plan('gte');p['rules'][0].update(temporal='streak',min_count=2,max_count=3)
        values=evaluate({'1d':bars([9,10,10,10,10,9,10,10])},p,'1d',history_limit=20)
        self.assertEqual([v['match'] for v in values],[False,False,True,True,False,False,False,True])
        self.assertEqual(values[-1]['checks'][0]['streak'],2)
    def test_unknown_run_start_is_not_exact(self):
        p=plan('gte');p['rules'][0].update(temporal='streak',min_count=2,max_count=3)
        with self.assertRaisesRegex(ValueError,'不足'):evaluate({'1d':bars([10,10])},p,'1d')
        p['rules'][0]['max_count']=None
        self.assertTrue(evaluate({'1d':bars([10,10])},p,'1d')[-1]['match'])
        p['rules'][0]['max_count']=3
        self.assertFalse(evaluate({'1d':bars([10]*4)},p,'1d')[-1]['match'])
    def test_brief_pullback_sequence_and_price_offset(self):
        p=plan('gte');red=p['rules'][0]
        p['rules']=[red,{**red,'op':'lt','offset':1,'temporal':'streak','min_count':1,'max_count':1},{**red,'offset':2,'temporal':'streak','min_count':3}]
        self.assertTrue(evaluate({'1d':bars([9,10,11,12,9,10])},p,'1d')[-1]['match'])
        self.assertFalse(evaluate({'1d':bars([9,10,11,12,9,9,10])},p,'1d')[-1]['match'])
        p=plan('gt');p['rules'][0]['right']={**operand(),'offset':2,'scale':1.05}
        self.assertTrue(evaluate({'1d':bars([10,12,11])},p,'1d')[-1]['match'])
    def test_windows_missing_and_timeframe_alignment(self):
        p=plan('gte');p['rules'][0].update(temporal='count',window=3,min_count=2,max_count=2)
        self.assertTrue(evaluate({'1d':bars([10,9,10])},p,'1d')[-1]['match'])
        with self.assertRaisesRegex(ValueError,'不足'):evaluate({'1d':bars([9,10])},p,'1d')
        p['rules'][0].update(temporal='all',period='1w',window=2,offset=1)
        weekly=bars([10,11,9]);weekly[0]['close_time']=100;weekly[1]['close_time']=200;weekly[2]['close_time']=400
        with self.assertRaisesRegex(ValueError,'不足'):evaluate({'1d':bars([1,2,3]),'1w':weekly},p,'1d')
        self.assertTrue(evaluate({'1d':bars([1,2,3,4]),'1w':weekly},p,'1d')[-1]['match'])
    def test_live_default_includes_current_and_unfinished_higher_period(self):
        daily=bars([12,12])
        daily[0].update(time=0,close_time=86400,confirmed=True)
        daily[1].update(time=86400,close_time=172800,confirmed=False)
        weekly=bars([9,12])
        weekly[0].update(time=-500000,close_time=80000,confirmed=True)
        weekly[1].update(time=90000,close_time=604800,confirmed=False)
        p=plan('gt')
        p['lookback']=2
        p['rules'][0]['period']='1w'
        with patch('app.scan_engine.time.time',return_value=100000):
            values=evaluate({'1d':daily,'1w':weekly},p,'1d')
        self.assertEqual([value['match'] for value in values],[False,True])
        self.assertFalse(values[-1]['confirmed'])
        p['live']=False
        self.assertFalse(evaluate({'1d':daily,'1w':weekly},p,'1d')[-1]['match'])

    def test_invalid_temporal_parameters(self):
        for extra in ({'offset':-1},{'temporal':'unknown'},{'min_count':3,'max_count':2},{'window':251}):
            p=plan();p['rules'][0].update(extra)
            with self.assertRaises(ValueError):evaluate({'1d':bars([9,10])},p,'1d')

class FinalCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_cn_afternoon_cache_requires_final_morning_candle_and_full_history(self):
        day='2026-11-16'
        previous, morning, afternoon=bars([8,10,12])
        previous['time']=stamp('2026-11-13',13)
        morning['time']=stamp(day,9,30)
        afternoon['time']=stamp(day,13)
        full=[previous,morning,afternoon]
        cutoff=stamp(day,11,30)
        for label, live, known, success, cached, hit in [
            ('closed', False, 60, cutoff, full, True),
            ('closed morning only', False, 60, cutoff, full[:2], True),
            ('preview', True, 60, cutoff, full, False),
            ('preclose', False, 60, cutoff-1, full, False),
            ('short history', False, 59, cutoff, full, False),
            ('missing morning', False, 60, cutoff, [previous,afternoon], False),
        ]:
            with self.subTest(label=label):
                main=SimpleNamespace(connect_db=None, read_bars=lambda *args:cached,
                    sync_state=lambda key:(known,success,None), default_history_days=lambda *args:60,
                    bars=AsyncMock(return_value={'bars':full,'stale':False}))
                service=ScanService(main,None)
                service.calendar=SimpleNamespace(days=lambda symbol:{'2026-11-13':'WHOLE',day:'WHOLE'})
                with patch('app.scan_service.time.time',return_value=stamp(day,14,30)):
                    rows=await service.load('SH.600000','120m',live=live)
                self.assertEqual(main.bars.await_count == 0,hit)
                self.assertEqual([b['close'] for b in rows if b['confirmed']], [8,10])

    async def test_unfinished_candle_cannot_cover_a_missing_confirmed_candle(self):
        day='2026-11-16'
        previous, afternoon=bars([8,12])
        previous['time']=stamp('2026-11-13',13)
        afternoon['time']=stamp(day,13)
        main=SimpleNamespace(connect_db=None, sync_state=lambda key:(60,stamp(day,14),None),
                             bars=AsyncMock(return_value={'bars':[previous,afternoon],'stale':False}))
        service=ScanService(main,None)
        service.calendar=SimpleNamespace(days=lambda symbol:{'2026-11-13':'WHOLE',day:'WHOLE'})
        with patch('app.scan_service.time.time',return_value=stamp(day,14,30)):
            with self.assertRaisesRegex(ValueError,'仍未覆盖'):
                await service.load('SH.600000','120m',live=False)
        self.assertTrue(main.bars.await_args.args[-1])

    async def test_preclose_cache_must_refresh_before_confirming(self):
        b=bars([10]);b[0]['time']=stamp('2026-11-16')
        main=SimpleNamespace(connect_db=None,bars=AsyncMock(side_effect=[{'bars':b,'stale':False},{'bars':b,'stale':True}]),sync_state=lambda key:(1,0,b[0]['time']))
        service=ScanService(main,None);service.calendar=SimpleNamespace(days=lambda symbol:{'2026-11-16':'WHOLE'})
        with self.assertRaisesRegex(ValueError,'收盘后刷新失败'):
            await service.load('SH.600000','1d')
        self.assertTrue(main.bars.call_args.args[-1])

    async def test_stale_retries_never_become_valid(self):
        main=SimpleNamespace(connect_db=None,bars=AsyncMock(return_value={'bars':bars([10]),'stale':True,'error':'offline'}))
        service=ScanService(main,None);service.calendar=SimpleNamespace(days=lambda symbol:{'2026-11-16':'WHOLE'})
        with patch('app.scan_service.asyncio.sleep',new=AsyncMock()),self.assertRaisesRegex(ValueError,'过期'):
            await service.load('SH.600000','1d')
        self.assertEqual(main.bars.call_count,2)

    async def test_after_close_cache_reuses_final_data(self):
        b=bars([10]);b[0]['time']=stamp('2026-11-16')
        main=SimpleNamespace(connect_db=None,bars=AsyncMock(),sync_state=lambda key:(730,stamp('2026-11-16',16),b[0]['time']),default_history_days=lambda p,s:730,read_bars=lambda *args:b)
        service=ScanService(main,None);service.calendar=SimpleNamespace(days=lambda symbol:{'2026-11-16':'WHOLE'})
        with patch('app.scan_service.time.time',return_value=stamp('2026-11-16',17)):
            r=await service.load('SH.600000','1d')
        self.assertTrue(r[-1]['confirmed']);main.bars.assert_not_called()

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        self.s=ScanService(SimpleNamespace(connect_db=self.db),None);self.s.init()
    def tearDown(self):self.tmp.cleanup()
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def test_restart_dedup_reentry_and_activation(self):
        m={'id':'m','activated_at':250,'interval_seconds':30}
        r={'symbol':'US.AAPL','period':'1d'}
        values=[dict(time=100,close_time=200,match=True,valid=True,confirmed=True),dict(time=200,close_time=300,match=True,valid=True,confirmed=True)]
        self.s.record(m,plan(),r,values)
        with self.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM scan_events').fetchone()[0],0)
        values.extend([dict(time=300,close_time=400,match=False,valid=True,confirmed=True),dict(time=400,close_time=500,match=True,valid=True,confirmed=True)])
        self.s.record(m,plan(),r,values)
        new=ScanService(SimpleNamespace(connect_db=self.db),None);new.init();new.record(m,plan(),r,values)
        with self.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM scan_events').fetchone()[0],1)
    def test_each_bar_events_survive_restart_without_duplicates(self):
        m={'id':'m','activated_at':0,'interval_seconds':30,'event_mode':'each_bar'};r={'symbol':'US.AAPL','period':'1d'}
        values=[dict(time=i*100,close_time=(i+1)*100,match=True,valid=True,confirmed=True) for i in range(1,4)]
        self.s.record(m,plan(),r,values)
        new=ScanService(SimpleNamespace(connect_db=self.db),None);new.init();new.record(m,plan(),r,values)
        with self.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM scan_events').fetchone()[0],3)

    def test_preview_confirmation_distinct(self):
        m={'id':'m','activated_at':0,'interval_seconds':30};r={'symbol':'US.AAPL','period':'1d'}
        v=dict(time=100,close_time=200,match=True,valid=True,confirmed=False)
        self.s.record(m,plan(),r,[v]);self.s.record(m,plan(),r,[{**v,'confirmed':True}])
        with self.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM scan_events').fetchone()[0],2)
    def test_preview_of_the_current_candle_is_visible_after_activation(self):
        monitor={'id':'m','activated_at':250,'interval_seconds':30}
        row={'symbol':'US.AAPL','period':'1d'}
        value={'time':200,'close_time':300,'match':True,'valid':True,'confirmed':False}
        self.s.record(monitor,plan(),row,[value])
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scan_events').fetchone()[0],1)

    def test_interrupted_jobs_recovered(self):
        self.s.put('jobs',{'id':'j','status':'running'});self.s.init()
        self.assertEqual(self.s.get('jobs','j')['status'],'interrupted')

    def test_hard_restart_marks_monitor_for_outside_session_recovery(self):
        self.s.put('monitors',{'id':'m','enabled':True,'last_status':'completed','last_run':999})
        self.s.put('jobs',{'id':'j','status':'running','monitor_id':'m'})
        self.s.init();m=self.s.get('monitors','m')
        self.assertTrue(m['force_run']);self.assertEqual(m['last_status'],'interrupted');self.assertEqual(m['next_run'],0)

class PoolTests(unittest.TestCase):
    def test_denominators_and_promotion(self):
        a=[{'symbol':'a','streak':2},{'symbol':'b','streak':1}]
        p=[{'symbol':'a','streak':1},{'symbol':'c','streak':1}]
        r=ladder(a,p,[{'symbol':'a'},{'symbol':'d'},{'symbol':'d'}])
        self.assertEqual(r['broken_count'],1);self.assertEqual(r['broken_denominator'],3)
        self.assertEqual(r['promotion'][0]['rate'],.5)

if __name__=='__main__':unittest.main()
