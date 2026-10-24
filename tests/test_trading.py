import os
import tempfile
import time
import unittest
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.trading import TradeEngine, TradeError


class FakeBroker:
    generation = 1

    def __init__(self):
        self.calls = []
        self.rows = []
        self.available = 100
        self.cash_qty = 1000
        self.fail = False
        self.closed = False
        self.market_state = 'AFTERNOON'
        self.timestamp = datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')

    def accounts(self):
        return [{'acc_id': '123456789123456789', 'trd_env': 'SIMULATE', 'acc_type': 'CASH', 'trdmarket_auth': ['US']},
                {'acc_id': '987654321987654321', 'trd_env': 'REAL', 'acc_type': 'CASH', 'trdmarket_auth': ['US']}]

    def positions(self, acc, env):
        return [{'code': 'US.SNDK', 'stock_name': 'Sandisk', 'qty': 100, 'can_sell_qty': self.available,
                 'position_side': 'LONG', 'nominal_price': 100, 'cost_price': 90,
                 'cost_price_valid': True, 'pl_val': 1000, 'pl_val_valid': True}]

    def funds(self, acc, env):
        return [{'total_assets': 20000, 'cash': 10000, 'market_val': 10000}]

    def orders(self, acc, env, refresh=True):
        return self.rows

    def capacity(self, order, order_id=None):
        return {'max_cash_buy': self.cash_qty, 'max_position_sell': 1000}

    def quote(self, code):
        return {'code': code, 'name': 'Sandisk', 'last_price': 100, 'update_time': self.timestamp,
                'stock_type': 'STOCK', 'market_state': self.market_state}

    def unlock(self, password=None, lock=False):
        self.calls.append(('lock' if lock else 'unlock',))

    def place(self, order, remark):
        self.calls.append(('place', order.copy()))
        row = dict(order_id=str(900000000000000000 + len(self.rows)), code=order['code'],
                   qty=order['qty'], dealt_qty=0, price=order['price'], trd_side=order['side'],
                   order_type=order['order_type'], order_status='SUBMITTED', session=order['session'],
                   time_in_force=order['time_in_force'], remark=remark)
        self.rows.append(row)
        for key in ('aux_price', 'trail_value', 'trail_type', 'trail_spread'):
            if key in order:
                row[key] = order[key]
        if self.fail:
            raise ConnectionError('response lost after acceptance')
        return [row]

    def modify(self, order, cancel=False):
        self.calls.append(('cancel' if cancel else 'modify', order.copy()))
        row = next(r for r in self.rows if r['order_id'] == order['order_id'])
        if cancel:
            row['order_status'] = 'CANCELLED_ALL'
        else:
            row.update(qty=order['qty'], price=order['price'])
        return [row]

    def close(self):
        self.closed = True


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = FakeBroker()
        self.engine = TradeEngine(os.path.join(self.tmp.name, 'trade.sqlite3'), self.broker)
        self.order = dict(acc_id='123456789123456789', env='SIMULATE', code='US.SNDK',
                          side='BUY', order_type='NORMAL', qty=10, price=100,
                          session='RTH', time_in_force='DAY')

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_commit_is_not_another_order(self):
        p = self.engine.preview('a', self.order)
        key = str(uuid.uuid4())
        first = self.engine.commit('a', p['preview_id'], key)
        second = self.engine.commit('a', p['preview_id'], key)
        self.assertEqual(first, second)
        self.assertEqual(len(self.broker.rows), 1)
        self.assertEqual(first['state'], 'ACCEPTED')

    def test_close_position_rejects_partial_quantity_and_reserved_shares(self):
        close = {**self.order, 'side': 'SELL', 'qty': 100, 'close_position': True}
        with self.assertRaisesRegex(TradeError, '持仓数量'):
            self.engine.preview('a', {**close, 'qty': 50})
        self.broker.available = 50
        with self.assertRaisesRegex(TradeError, '不能完整平仓'):
            self.engine.preview('a', close)

    def test_close_position_rechecks_pending_buy_before_submission(self):
        close = {**self.order, 'side': 'SELL', 'qty': 100, 'close_position': True}
        p = self.engine.preview('a', close)
        self.broker.rows.append(dict(code='US.SNDK', trd_side='BUY', order_status='SUBMITTED'))
        with self.assertRaisesRegex(TradeError, '未结束的买单'):
            self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        self.assertFalse(self.broker.calls)

    def test_full_close_keeps_explicit_limit_and_quantity(self):
        close = {**self.order, 'side': 'SELL', 'qty': 100, 'price': 99.5, 'close_position': True}
        p = self.engine.preview('a', close)
        r = self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        self.assertEqual(r['state'], 'ACCEPTED')
        self.assertEqual(self.broker.calls[-1][1]['qty'], 100)
        self.assertEqual(self.broker.calls[-1][1]['price'], 99.5)

    def test_real_requires_account_bound_unexpired_grant(self):
        real = {**self.order, 'acc_id': '987654321987654321', 'env': 'REAL'}
        with self.assertRaisesRegex(TradeError, '锁定'):
            self.engine.preview('a', real)
        self.engine.unlock('a', real['acc_id'], 'not-a-real-password')
        with self.assertRaisesRegex(TradeError, '锁定'):
            self.engine.preview('b', real)
        p = self.engine.preview('a', real)
        self.engine.grant['expires'] = time.time() - 1
        with self.assertRaisesRegex(TradeError, '锁定'):
            self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        self.assertFalse(self.broker.rows)

    def test_environment_cannot_be_forged(self):
        with self.assertRaisesRegex(TradeError, '环境不匹配'):
            self.engine.preview('a', {**self.order, 'env': 'REAL'})

    def test_capacity_rechecked_at_commit(self):
        p = self.engine.preview('a', self.order)
        self.broker.cash_qty = 0
        with self.assertRaisesRegex(TradeError, '现金'):
            self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        self.assertFalse(self.broker.rows)

    def test_pending_sell_blocks_oversell(self):
        self.broker.available = 5
        with self.assertRaisesRegex(TradeError, '可卖数量'):
            self.engine.preview('a', {**self.order, 'side': 'SELL', 'qty': 10})

    def test_expired_preview_and_cross_session_rejected(self):
        p = self.engine.preview('a', self.order)
        with self.assertRaises(TradeError):
            self.engine.commit('b', p['preview_id'], str(uuid.uuid4()))
        self.engine.previews[p['preview_id']]['expires'] = 0
        with self.assertRaisesRegex(TradeError, '过期'):
            self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))

    def test_unknown_outcome_reconciled_without_resubmitting(self):
        self.broker.fail = True
        p = self.engine.preview('a', self.order)
        key = str(uuid.uuid4())
        result = self.engine.commit('a', p['preview_id'], key)
        self.assertEqual(result['state'], 'UNKNOWN')
        p2 = self.engine.preview('a', self.order)
        with self.assertRaisesRegex(TradeError, '待核对'):
            self.engine.commit('a', p2['preview_id'], str(uuid.uuid4()))
        self.assertEqual(self.engine.reconcile(key)['state'], 'RECONCILED')
        self.assertEqual(len(self.broker.rows), 1)

    def test_restart_keeps_journal_but_loses_grant(self):
        p = self.engine.preview('a', self.order)
        key = str(uuid.uuid4())
        self.engine.commit('a', p['preview_id'], key)
        next_engine = TradeEngine(self.engine.path, self.broker)
        self.assertEqual(next_engine.operation(key)['state'], 'ACCEPTED')
        self.assertIsNone(next_engine.grant)

    def test_stop_rejected_in_overnight_and_paper(self):
        for payload in ({**self.order, 'side': 'SELL', 'order_type': 'STOP', 'aux_price': 90},
                        {**self.order, 'order_type': 'MARKET', 'session': 'ALL'}):
            with self.assertRaises(TradeError):
                self.engine.preview('a', payload)

    def test_fractional_and_nonfinite_prices_rejected(self):
        for patch in ({'qty': 1.1}, {'qty': True}, {'price': float('nan')}, {'price': 100.001}, {'qty': 1001}):
            with self.assertRaises(TradeError):
                self.engine.preview('a', {**self.order, **patch})

    def test_market_requires_fresh_quote(self):
        self.broker.timestamp = '2020-01-01 09:31:00'
        with self.assertRaisesRegex(TradeError, '超过 5 秒'):
            self.engine.preview('a', {**self.order, 'order_type': 'MARKET'})

    def test_quote_is_revalidated_at_commit(self):
        p = self.engine.preview('a', {**self.order, 'order_type': 'MARKET'})
        self.broker.timestamp = '2020-01-01 09:31:00'
        with self.assertRaisesRegex(TradeError, '超过 5 秒'):
            self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        self.assertFalse(self.broker.rows)

    def test_market_rejected_outside_regular_session(self):
        self.broker.market_state = 'AFTER_HOURS_BEGIN'
        with self.assertRaisesRegex(TradeError, '常规交易时段'):
            self.engine.preview('a', {**self.order, 'order_type': 'MARKET'})

    def test_crash_during_send_recovers_unknown(self):
        p = self.engine.preview('a', self.order)
        key = str(uuid.uuid4())
        self.engine.commit('a', p['preview_id'], key)
        with self.engine.db() as db:
            db.execute("UPDATE operations SET state='SENDING' WHERE id=?", (key,))
        recovered = TradeEngine(self.engine.path, self.broker)
        self.assertEqual(recovered.operation(key)['state'], 'UNKNOWN')
        self.assertEqual(recovered.reconcile(key)['state'], 'RECONCILED')
        self.assertEqual(len(self.broker.rows), 1)

    def test_cancel_is_account_checked_and_idempotent(self):
        p = self.engine.preview('a', self.order)
        placed = self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        order_id = placed['result'][0]['order_id']
        cancel = self.engine.preview('a', dict(acc_id=self.order['acc_id'], env='SIMULATE', action='CANCEL', order_id=order_id))
        key = str(uuid.uuid4())
        self.engine.commit('a', cancel['preview_id'], key)
        self.engine.commit('a', cancel['preview_id'], key)
        self.assertEqual(sum(c[0] == 'cancel' for c in self.broker.calls), 1)

    def test_changed_order_requires_new_modify_preview(self):
        p = self.engine.preview('a', self.order)
        placed = self.engine.commit('a', p['preview_id'], str(uuid.uuid4()))
        order_id = placed['result'][0]['order_id']
        edit = self.engine.preview('a', {**self.order, 'action': 'MODIFY', 'order_id': order_id, 'price': 99})
        self.broker.rows[0]['price'] = 98
        # The production broker creates separate records; fake must too for this comparison.
        edit_internal = self.engine.previews[edit['preview_id']]
        edit_internal['original'] = {**edit_internal['original'], 'price': 100}
        with self.assertRaisesRegex(TradeError, '已被修改'):
            self.engine.commit('a', edit['preview_id'], str(uuid.uuid4()))

    def test_credentials_never_persisted(self):
        self.engine.unlock('a', '987654321987654321', 'sensitive-test-value')
        with open(self.engine.path, 'rb') as f:
            self.assertNotIn(b'sensitive-test-value', f.read())


if __name__ == '__main__':
    unittest.main()
