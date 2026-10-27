import os
import tempfile
import unittest
import uuid
from unittest.mock import patch
from test_trading import FakeBroker
from app.trading import TradeEngine, TradeError


CODE = 'US.SNDK991231C100000'


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = FakeBroker()
        original = self.broker.quote
        self.broker.quote = lambda code: {**original(code), 'stock_type': 'OPTION',
            'last_price': 2.5, 'option_valid': True, 'option_contract_size': 100,
            'option_contract_multiplier': 100, 'lot_size': 100,
            'stock_owner': 'US.SNDK', 'strike_time': '2099-12-31',
            'option_type': 'CALL', 'option_strike_price': 100, 'option_standard_type': 'STANDARD'}
        self.engine = TradeEngine(os.path.join(self.tmp.name, 'trade.sqlite3'), self.broker)
        self.order = dict(acc_id='123456789123456789', env='SIMULATE', code=CODE,
            side='BUY', order_type='NORMAL', qty=2, price=2.5, session='RTH', time_in_force='DAY')

    def tearDown(self):
        self.tmp.cleanup()

    def test_premium_uses_contract_multiplier_not_share_count(self):
        p = self.engine.preview('test', self.order)
        self.assertEqual(p['order']['estimate'], 500)
        self.assertEqual(p['order']['multiplier'], 100)
        self.assertEqual(p['order']['security_type'], 'OPTION')
        self.assertFalse(self.broker.calls)

    def test_option_amount_limit_cannot_be_bypassed(self):
        with self.assertRaisesRegex(TradeError, '单笔估算金额'):
            self.engine.preview('test', {**self.order, 'qty': 41})

    def test_only_rth_day_limit_orders_without_stock_protection(self):
        for extra in [dict(order_type='MARKET'), dict(session='ALL'), dict(time_in_force='GTC'),
                      dict(protection={'percent': 2.5})]:
            with self.subTest(extra=extra), self.assertRaises(TradeError):
                self.engine.normalize({**self.order, **extra})

    def test_unknown_or_adjusted_contracts_fail_closed(self):
        base = self.broker.quote(CODE)
        for extra in [dict(option_contract_size=None), dict(option_contract_size=10),
                      dict(option_contract_multiplier=10), dict(stock_owner='US.SPX'),
                      dict(strike_time='2000-01-01'), dict(option_valid=False), dict(option_standard_type='ADJUSTED')]:
            self.engine.quote_cache.clear()
            self.broker.quote = lambda code, extra=extra: {**base, **extra}
            if extra.get('stock_owner') == 'US.SPX':
                # Missing/zero share deliverable identifies cash-settled/index contracts.
                self.broker.quote = lambda code: {**base, **extra, 'option_contract_size': 0}
            with self.subTest(extra=extra), self.assertRaises(TradeError):
                self.engine.normalize(self.order)

    def test_sell_requires_existing_long_and_available_contracts(self):
        with self.assertRaisesRegex(TradeError, '多头持仓'):
            self.engine.preview('test', {**self.order, 'side': 'SELL'})
        self.broker.positions = lambda *args: [dict(code=CODE, qty=2, can_sell_qty=2, position_side='LONG')]
        self.assertEqual(self.engine.preview('test', {**self.order, 'side': 'SELL', 'close_position': True})['order']['qty'], 2)
        self.broker.positions = lambda *args: [dict(code=CODE, qty=2, can_sell_qty=1, position_side='LONG')]
        with self.assertRaisesRegex(TradeError, '不能完整平仓'):
            self.engine.preview('test', {**self.order, 'side': 'SELL', 'close_position': True})

    def test_option_preferences_are_separate_and_persist(self):
        prefs = self.engine.preferences()
        self.assertEqual(prefs['option_quantities'], [1, 2, 5])
        saved = self.engine.preferences({**prefs, 'option_quantities': [1, 3]})
        self.assertEqual(saved['option_quantities'], [1, 3])
        with self.assertRaises(TradeError):
            self.engine.preferences({**prefs, 'option_quantities': [0, 1.5]})

    def test_option_commit_is_idempotent_and_rechecks_multiplier(self):
        p = self.engine.preview('test', self.order)
        self.broker.quote = lambda code: {'stock_type':'OPTION', 'option_valid':True,
            'option_standard_type':'STANDARD','option_contract_size':10}
        with self.assertRaises(TradeError):
            self.engine.commit('test', p['preview_id'], str(uuid.uuid4()))
        self.assertFalse(self.broker.calls)

    def test_option_order_uses_contract_count_and_real_requires_unlock(self):
        with self.assertRaisesRegex(TradeError, '锁定'):
            self.engine.preview('test', {**self.order, 'acc_id':'987654321987654321', 'env':'REAL'})
        p = self.engine.preview('test', self.order)
        op = str(uuid.uuid4())
        result = self.engine.commit('test', p['preview_id'], op)
        self.assertEqual(self.engine.commit('test', p['preview_id'], op), result)
        self.assertEqual(len(self.broker.calls), 1)
        self.assertEqual(self.broker.calls[0][1]['qty'], 2)
        self.assertEqual(self.broker.calls[0][1]['estimate'], 500)

    def test_stock_preferences_do_not_overwrite_option_shortcuts(self):
        self.engine.preferences({**self.engine.preferences(), 'option_quantities':[1,3]})
        saved = self.engine.preferences({'quantities':[10], 'stops':[2.5], 'templates':[]})
        self.assertEqual(saved['option_quantities'], [1,3])

    def test_cash_fraction_sizes_whole_contracts_with_fee_reserve(self):
        sized=self.engine.option_size(self.order['acc_id'],'SIMULATE',CODE,'BUY','1/4',2.5)
        self.assertEqual(sized['qty'],9)
        self.assertEqual(sized['cash_basis'],10000)
        self.assertLessEqual(sized['estimate']+sized['fee_reserve'],2500)
        with self.assertRaises(TradeError):
            self.engine.option_size(self.order['acc_id'],'SIMULATE',CODE,'BUY','0.9',2.5)
        self.broker.cash_qty=1
        self.assertEqual(self.engine.option_size(self.order['acc_id'],'SIMULATE',CODE,'BUY','1/2',2.5)['qty'],1)

    def test_sell_fraction_uses_available_contracts_and_rounds_down(self):
        self.broker.positions=lambda *args:[dict(code=CODE,qty=20,can_sell_qty=11,position_side='LONG')]
        self.assertEqual(self.engine.option_size(self.order['acc_id'],'SIMULATE',CODE,'SELL','1/4',2.5)['qty'],2)
        self.assertEqual(self.engine.option_size(self.order['acc_id'],'SIMULATE',CODE,'SELL','1/3',2.5)['qty'],3)
        self.broker.positions=lambda *args:[dict(code=CODE,qty=3,can_sell_qty=3,position_side='LONG')]
        self.assertEqual(self.engine.option_size(self.order['acc_id'],'SIMULATE',CODE,'SELL','1/3',2.5)['qty'],1)

    def test_nearest_option_uses_underlying_not_option_price(self):
        old=self.broker.quote
        self.broker.quote=lambda code: {**old(code),'stock_type':'STOCK','last_price':101} if code=='US.SNDK' else old(code)
        self.broker.option_chain=lambda *args:{'contracts':[
            dict(code=CODE,option_type='CALL',strike_price=100,option_standard_type='STANDARD'),
            dict(code='US.SNDK991231C102000',option_type='CALL',strike_price=102,option_standard_type='STANDARD'),
            dict(code='US.SNDK991231P101000',option_type='PUT',strike_price=101,option_standard_type='STANDARD')]}
        selected=self.engine.nearest_option('US.SNDK','2099-12-31','CALL')
        self.assertEqual(selected['contract']['code'],CODE)
        self.assertEqual(selected['underlying_price'],101)

    def test_real_option_stop_and_fixed_post_fill_stop(self):
        acc='987654321987654321';self.engine.unlock('test',acc,'test-only')
        self.broker.positions=lambda *args:[dict(code=CODE,qty=2,can_sell_qty=2,position_side='LONG')]
        stop={**self.order,'acc_id':acc,'env':'REAL','side':'SELL','order_type':'STOP_LIMIT','aux_price':2,'price':1.95}
        self.assertEqual(self.engine.preview('test',stop)['order']['aux_price'],2)
        with self.assertRaises(TradeError):
            self.engine.preview('test',{**stop,'price':1.951})
        buy={**self.order,'acc_id':acc,'env':'REAL','protection':dict(name='期权保护',percent=20,mode='STOP_LIMIT',tolerance=.05,trigger_price=2)}
        p=self.engine.preview('test',buy)
        self.assertTrue(p['order']['protection']['option'])
        result=self.engine.commit('test',p['preview_id'],str(uuid.uuid4()))
        parent=self.broker.rows[-1];parent.update(dealt_qty=2,dealt_avg_price=2.5,order_status='FILLED_ALL')
        self.engine.tick()
        child=self.broker.calls[-1][1]
        self.assertEqual(child['order_type'],'STOP_LIMIT')
        self.assertEqual(child['qty'],2)
        self.assertEqual(child['aux_price'],2)
        self.assertEqual(child['time_in_force'],'DAY')
        self.engine.tick();self.engine.tick()
        self.assertEqual(sum(c[0]=='place' for c in self.broker.calls),2)

    def test_small_option_prices_and_protection_are_cent_precision(self):
        from app.protection import stop_prices
        self.assertEqual(stop_prices(.37,dict(percent=2.5,mode='STOP_LIMIT',tolerance=.05,option=True)),(.36,.31))
        with self.assertRaises(TradeError):
            self.engine.normalize({**self.order,'price':.375})
