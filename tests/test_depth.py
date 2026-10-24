import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.depth import DepthFeed, levels


class DepthTests(unittest.TestCase):
    def test_aggregates_same_price_and_separates_sides(self):
        result = levels({'Bid': [(100, 20), (100, 30), (99, -1), (float('nan'), 10)], 'Ask': [(100, 5)]})
        self.assertEqual(result, [dict(side='buy', price=100, qty=50, amount=5000),
                                  dict(side='sell', price=100, qty=5, amount=500)])

    def test_never_uses_more_than_60_rows_per_side(self):
        self.assertEqual(len(levels({'Bid': [(100+i, 1) for i in range(100)]})), 60)

    def test_reuses_subscription_and_cleans_idle_connection(self):
        calls = []
        sdk = SimpleNamespace(RET_OK=0,SubType=SimpleNamespace(ORDER_BOOK='book'),Session=SimpleNamespace(ALL='all'))
        ctx = SimpleNamespace(
            subscribe=lambda *a, **kw: (calls.append('subscribe') or (0, '')),
            unsubscribe=lambda *a, **kw: (calls.append('unsubscribe') or (0, '')),
            get_order_book=lambda *a, **kw: (0, {'Bid': [(100, 100)], 'Ask': [(101, 200)]}),
            close=lambda: calls.append('close'))
        feed = DepthFeed()
        feed.ctx = ctx
        feed.states['US.SNDK'] = (100, 'CLOSED')
        with patch.dict(sys.modules, {'moomoo':sdk}), patch('app.depth.time.monotonic', return_value=100):
            one = feed.read('US.SNDK')
            self.assertFalse(one['active'])
            self.assertIsNone(one['source_time_bid'])
            self.assertEqual(feed.read('US.SNDK'), one)
            self.assertEqual(calls, ['subscribe'])
        with patch.dict(sys.modules, {'moomoo':sdk}), patch('app.depth.time.monotonic', return_value=170):
            feed.cleanup()
        self.assertEqual(calls, ['subscribe', 'unsubscribe', 'close'])
        self.assertEqual(feed.cache, {})
        self.assertIsNone(feed.ctx)

    def test_live_state_and_subscription_limit(self):
        sdk = SimpleNamespace(RET_OK=0,SubType=SimpleNamespace(ORDER_BOOK='book'),Session=SimpleNamespace(ALL='all'))
        feed = DepthFeed()
        feed.ctx = SimpleNamespace(subscribe=lambda *a, **kw: (0, ''),
            get_order_book=lambda *a, **kw:(0, {'Bid':[(100,1)], 'Ask':[(101,2)]}))
        with patch.dict(sys.modules, {'moomoo':sdk}), patch('app.depth.time.monotonic', return_value=100):
            for symbol in ['US.A','US.B','US.C','US.D']:
                feed.states[symbol] = (100,'AFTERNOON')
                self.assertTrue(feed.read(symbol)['active'])
            with self.assertRaisesRegex(ValueError, '四只'):
                feed.read('US.E')


if __name__ == '__main__':
    unittest.main()
