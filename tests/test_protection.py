import os
import tempfile
import unittest
import uuid

from app.trading import TradeEngine, TradeError
from app.protection import stop_prices
from test_trading import FakeBroker


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = FakeBroker()
        self.path = os.path.join(self.tmp.name, 'trade.sqlite3')
        self.engine = TradeEngine(self.path, self.broker)
        self.acc = '987654321987654321'
        self.engine.unlock('owner', self.acc, 'test-only')
        self.config = dict(name='开盘测试', percent=2.5, mode='STOP_LIMIT', tolerance=.2)
        self.order = dict(acc_id=self.acc, env='REAL', code='US.SNDK', side='BUY', order_type='NORMAL',
                          qty=10, price=100, session='RTH', time_in_force='DAY', protection=self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def buy(self):
        preview = self.engine.preview('owner', self.order)
        op = self.engine.commit('owner', preview['preview_id'], str(uuid.uuid4()))
        return op['id']

    def fill(self, qty, avg=100, terminal=False):
        self.broker.rows[0].update(dealt_qty=qty, dealt_avg_price=avg,
                                 order_status='FILLED_ALL' if terminal else 'FILLED_PART')

    def test_prices_are_trigger_minus_dollar_tolerance(self):
        self.assertEqual(stop_prices(100, self.config), (97.5, 97.3))
        with self.assertRaises(TradeError):
            stop_prices(.1, self.config)

    def test_partial_fills_only_protect_new_quantity_once(self):
        self.buy()
        self.engine.tick()
        self.assertEqual(len(self.broker.rows), 1)
        self.fill(4)
        self.engine.tick()
        self.assertEqual(self.broker.calls[-1][1]['qty'], 4)
        self.assertEqual(self.broker.calls[-1][1]['aux_price'], 97.5)
        self.assertEqual(self.broker.calls[-1][1]['price'], 97.3)
        self.engine.tick()
        self.engine.tick()
        self.assertEqual(len(self.broker.rows), 2)
        self.fill(10, 99.4, True)  # Remaining 6 shares filled at 99.
        self.engine.tick()
        self.assertEqual(self.broker.calls[-1][1]['qty'], 6)
        self.assertEqual(self.broker.calls[-1][1]['aux_price'], 96.52)
        self.engine.tick()
        p = self.engine.protections()[0]
        self.assertEqual((p['state'], p['covered']), ('COMPLETE', 10))
        self.assertEqual(len(self.broker.rows), 3)

    def test_lost_stop_response_never_retried_and_can_reconcile(self):
        plan_id = self.buy()
        self.fill(10, terminal=True)
        self.broker.fail = True
        self.engine.tick()
        p = self.engine.protections()[0]
        self.assertEqual(p['state'], 'PAUSED')
        for _ in range(3):
            self.engine.tick()
        self.assertEqual(len(self.broker.rows), 2)
        self.engine.reconcile(p['pending']['id'])
        self.engine.resume_protection('owner', plan_id)
        self.engine.tick()
        self.assertEqual(self.engine.protections()[0]['state'], 'COMPLETE')
        self.assertEqual(len(self.broker.rows), 2)

    def test_restart_and_lock_pause_without_saving_password(self):
        plan_id = self.buy()
        self.fill(10, terminal=True)
        restarted = TradeEngine(self.path, self.broker)
        restarted.tick()
        self.assertEqual(restarted.protections()[0]['state'], 'PAUSED')
        self.assertEqual(len(self.broker.rows), 1)
        with self.assertRaises(TradeError):
            restarted.resume_protection('owner', plan_id)
        restarted.unlock('new-owner', self.acc, 'test-only')
        restarted.resume_protection('new-owner', plan_id)
        restarted.tick()
        self.assertEqual(len(self.broker.rows), 2)
        restarted.lock()
        self.assertEqual(restarted.protections()[0]['state'], 'PAUSED')

    def test_gap_below_trigger_pauses_no_silent_market_fallback(self):
        self.buy()
        self.fill(10, avg=110, terminal=True)
        self.engine.tick()
        self.assertEqual(self.engine.protections()[0]['state'], 'PAUSED')
        self.assertEqual(len(self.broker.rows), 1)

    def test_cancelled_parent_partial_fill_gets_stop(self):
        self.buy()
        self.fill(3)
        self.broker.rows[0]['order_status'] = 'CANCELLED_PART'
        self.engine.tick()
        self.engine.tick()
        self.assertEqual(self.engine.protections()[0]['covered'], 3)
        self.assertEqual(self.engine.protections()[0]['state'], 'COMPLETE')

    def test_failed_stop_does_not_count_as_protected(self):
        self.buy()
        self.fill(10, terminal=True)
        self.engine.tick()
        self.broker.rows[1]['order_status'] = 'FAILED'
        self.engine.tick()
        p = self.engine.protections()[0]
        self.assertEqual((p['state'], p['covered']), ('PAUSED', 0))

    def test_rejects_extended_hours_and_simulated_attached_stops(self):
        for change in ({'session': 'ALL'}, {'time_in_force': 'GTC'},
                       {'env': 'SIMULATE', 'acc_id': '123456789123456789'}):
            with self.assertRaises(TradeError):
                self.engine.preview('owner', {**self.order, **change})

    def test_changed_stop_is_not_credited(self):
        self.buy()
        self.fill(10, terminal=True)
        self.engine.tick()
        self.broker.rows[1]['aux_price'] = 95
        self.engine.tick()
        self.assertEqual(self.engine.protections()[0]['state'], 'PAUSED')
        self.assertEqual(self.engine.protections()[0]['covered'], 0)

    def test_prior_cancelled_stop_pauses_later_fills(self):
        self.buy()
        self.fill(4)
        self.engine.tick()
        self.engine.tick()
        self.broker.rows[1]['order_status'] = 'CANCELLED_ALL'
        self.fill(10, terminal=True)
        self.engine.tick()
        self.assertEqual(self.engine.protections()[0]['state'], 'PAUSED')
        self.assertEqual(len(self.broker.rows), 2)

    def test_named_presets_validation_and_persistence(self):
        value = dict(quantities=[10], stops=[2.5], templates=[{**self.config, 'qty': 10}])
        self.assertEqual(self.engine.preferences(value), value)
        self.assertEqual(TradeEngine(self.path, self.broker).preferences(), value)
        with self.assertRaises(TradeError):
            self.engine.preferences({**value, 'templates': [{**self.config, 'qty': -1}]})


if __name__ == '__main__':
    unittest.main()
