import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from app.strategy_rules import validate_strategy, evaluate
from app.strategy_store import StrategyStore


def config():
    return {'name':'自定义交叉','symbol':'US.SNDK','period':'5m','mode':'regular',
            'sources':[{'id':'fast','name':'EMA','params':{'period':1}},
                       {'id':'slow','name':'SMA','params':{'period':2}}],
            'buy':{'join':'all','conditions':[{'left':'fast:main','op':'cross_above','right':'slow:main'}]},
            'sell':{'join':'all','conditions':[{'left':'fast:main','op':'cross_below','right':'slow:main'}]},
            'execution':{'qty':10,'sell_percent':100,'session':'RTH','offset_percent':0.1,'max_deviation':1,
                         'flat_only':True,'max_executions':1}}


def bars(values, base=10000):
    return [dict(time=base+i*300,open=v,high=v,low=v,close=v,volume=100,
                 session='regular',session_date='2026-10-26:regular',trade_date='2026-10-26')
            for i,v in enumerate(values)]


class RuleTests(unittest.TestCase):
    def test_closed_candles_only_and_cross_once(self):
        cfg=validate_strategy(config())
        rows=bars([3,2,4,1])
        result=evaluate(cfg,rows,now=10904)
        self.assertTrue(result['buy'])
        self.assertFalse(result['sell'])
        self.assertEqual(result['bar_time'],10600)
        self.assertEqual(evaluate(cfg,rows,now=11204)['sell'],True)

    def test_reset_does_not_create_crossover(self):
        rows=bars([3,2,4])
        rows[-1]['session_date']='2026-10-27:regular'
        self.assertFalse(evaluate(validate_strategy(config()),rows,now=11000)['buy'])

    def test_null_warmup_does_not_trigger(self):
        cfg=config();cfg['sources'][1]['params']['period']=100
        result=evaluate(validate_strategy(cfg),bars([1,2,3]),now=11000)
        self.assertFalse(result['buy'])
        self.assertFalse(result['sell'])

    def test_python_output_can_be_condition_source(self):
        cfg=config();cfg['sources']=[{'id':'custom','name':'PYTHON','params':{'code':'result = {"买入": C - EMA(C, 2)}','inputs':{}}}]
        cfg['buy']['conditions']=[{'left':'custom:买入','op':'cross_above','right':0}]
        cfg['sell']['conditions']=[]
        from app.python_indicator_worker import calculate
        result=evaluate(validate_strategy(cfg),bars([3,2,4]),now=11000,
                         python_runner=lambda code,rows,inputs:calculate(code,rows,inputs))
        self.assertTrue(result['buy'])

    def test_invalid_config_and_missing_line_report_errors(self):
        cfg=config();cfg['sources'][0]['params']['period']=1000000
        with self.assertRaises(ValueError):validate_strategy(cfg)
        cfg=config();cfg['buy']['conditions'][0]['left']='fast:missing'
        with self.assertRaisesRegex(ValueError,'输出线'):evaluate(validate_strategy(cfg),bars([1,2,3]),now=11000)

    def test_evaluation_endpoint_leases_share_one_queue(self):
        import asyncio
        from app import main as market
        cfg=config();key=('US.SNDK','5m','regular')
        fake=MagicMock();fake.active={key:1}
        async def cached(*args,**kwargs):return {'bars':bars([3,2,4]),'stale':False}
        with patch.object(market,'bridge',fake),patch.object(market,'bars',cached):
            try:
                request=market.StrategyEvaluation(config=cfg,lease=True)
                asyncio.run(market.strategy_evaluate(request));asyncio.run(market.strategy_evaluate(request))
                self.assertEqual(len(market.listeners[key]),1)
                self.assertIn(key,market.strategy_leases)
            finally:
                queue=market.strategy_leases.pop(key)[0]
                market.listeners[key].discard(queue)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=StrategyStore(self.temp.name+'/strategies.sqlite3')
        self.item=self.store.save(config())

    def tearDown(self):self.temp.cleanup()

    def test_baseline_dedupe_restart_and_skipped_candles(self):
        self.store.start(self.item['id'],True,{'bar_time':10000})
        self.assertFalse(self.store.claim(self.item['id'],10000,False))
        self.assertTrue(self.store.claim(self.item['id'],10300,False))
        self.assertFalse(self.store.claim(self.item['id'],10300,False))
        self.store.arm(self.item['id'],'owner','123','SIMULATE',time.time()+600)
        restarted=StrategyStore(self.temp.name+'/strategies.sqlite3')
        item=restarted.get(self.item['id'])
        self.assertTrue(item['enabled'])
        self.assertIsNone(item['arm'])
        self.assertTrue(restarted.claim(self.item['id'],11200,True))

    def test_save_disarms_and_stops_changed_strategy(self):
        self.store.start(self.item['id'],True,{'bar_time':10000})
        self.store.arm(self.item['id'],'owner','123','SIMULATE',time.time()+600)
        changed=self.store.save({**config(),'id':self.item['id'],'name':'changed'})
        self.assertFalse(changed['enabled'])
        self.assertIsNone(changed['arm'])
