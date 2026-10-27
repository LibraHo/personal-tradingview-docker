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
