import asyncio
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

temp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = os.path.join(temp.name, 'test.sqlite3')
from app import main as market
market.DB = os.environ['DB_PATH']


def sample(ts, close):
    return {'time': ts, 'open': close, 'high': close + 1, 'low': close - 1,
            'close': close, 'volume': 10, 'turnover': 100}


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        market.init_db()

    def test_duplicate_bar_is_corrected(self):
        key = ('US.SNDK', '5m', 'all')
        ts = int(datetime.now(ZoneInfo('America/New_York')).timestamp())
        market.save_bars(key, [sample(ts, 10)])
        market.save_bars(key, [sample(ts, 12)])
        rows = market.read_bars(key, 1, 10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['close'], 12)

    def test_overnight_trade_date_rolls_forward(self):
        et = ZoneInfo('America/New_York')
        before = int(datetime(2026, 10, 21, 21, tzinfo=et).timestamp())
        after = int(datetime(2026, 10, 22, 1, tzinfo=et).timestamp())
        self.assertEqual(market.session_fields(before), ('overnight', '2026-10-21', '2026-10-22'))
        self.assertEqual(market.session_fields(after), ('overnight', '2026-10-22', '2026-10-22'))

    def test_a_share_uses_beijing_time_and_regular_session(self):
        self.assertEqual(market.validate('sh.600519', '5m', 'regular'), ('SH.600519', '5m', 'regular'))
        with self.assertRaises(ValueError):
            market.validate('SH.600519', '5m', 'all')
        frame = types.SimpleNamespace(to_dict=lambda kind: [{
            'time_key': '2026-10-22 09:35:00', 'open': 1, 'high': 2,
            'low': 1, 'close': 2, 'volume': 100, 'turnover': 200,
        }])
        bar = market.frame_to_bars(frame, 'SH.600519')[0]
        self.assertEqual(datetime.fromtimestamp(bar['time'], market.CN_TZ).hour, 9)
        self.assertEqual(market.session_fields(bar['time'], 'SH.600519'),
                         ('regular', '2026-10-22', '2026-10-22'))

    def test_daily_cache_is_retained_longer_than_intraday(self):
        old = int((datetime.now(market.ET) - timedelta(days=60)).timestamp())
        daily = ('US.SNXX', '1d', 'regular')
        intraday = ('US.SNXX', '5m', 'all')
        market.save_bars(daily, [sample(old, 10)])
        market.save_bars(intraday, [sample(old, 10)])
        market.prune_cache()
        self.assertEqual(len(market.read_bars(daily, 90, 10)), 1)
        self.assertEqual(len(market.read_bars(intraday, 90, 10)), 0)


class PushTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_quotes_use_opend_session_fields_and_cache(self):
        fake = types.SimpleNamespace(RET_OK=0)
        class Context:
            calls = 0
            def get_market_snapshot(self, symbols):
                self.calls += 1
                self_symbols = symbols
                return 0, types.SimpleNamespace(to_dict=lambda kind: [
                    {'code': self_symbols[0], 'name': 'Sample', 'last_price': 102,
                     'prev_close_price': 100, 'after_price': 104,
                     'after_change_rate': 1.96, 'overnight_price': float('nan'),
                     'update_time': '2026-10-22 16:05:00'}])
        ctx = Context()
        bridge = market.Bridge()
        with patch.dict(sys.modules, {'moomoo': fake}), patch.object(bridge, 'ensure', return_value=ctx):
            first, stale = bridge.snapshots(['US.SNDK'])
            second, _ = bridge.snapshots(['US.SNDK'])
        self.assertFalse(stale)
        self.assertEqual(ctx.calls, 1)
        self.assertEqual(first, second)
        self.assertEqual(first[0]['change_percent'], 2.0)
        self.assertEqual(first[0]['after_change_percent'], 1.96)
        self.assertIsNone(first[0]['overnight_price'])

    async def test_daily_loads_two_years_then_refreshes_recent_days(self):
        key = ('US.SNDQ', '1d', 'regular')
        market.last_fetch.pop(key, None)
        market.fetched_days.pop(key, None)
        with patch.object(market.bridge, 'history', return_value=0) as history:
            await market.bars(*key)
            self.assertEqual(history.call_args.args, (key, market.DAILY_HISTORY_DAYS))
            market.last_fetch[key] = 0
            await market.bars(*key)
            self.assertEqual(history.call_args.args, (key, 2))

    async def test_push_updates_cache_and_queue(self):
        market.init_db()
        key = ('US.SNXX', '1m', 'all')
        queue = asyncio.Queue(maxsize=10)
        market.listeners[key] = {queue}
        ts = int(datetime.now(ZoneInfo('America/New_York')).timestamp())
        await market.publish(key, [sample(ts, 20)])
        await market.publish(key, [sample(ts, 21)])
        self.assertEqual((await queue.get())['bar']['close'], 20)
        self.assertEqual((await queue.get())['bar']['close'], 21)
        self.assertEqual(market.read_bars(key, 1, 10)[0]['close'], 21)
        market.listeners.pop(key)

    async def test_failed_subscription_can_retry(self):
        fake = types.SimpleNamespace(SubType=types.SimpleNamespace(K_1M=1),
                                     Session=types.SimpleNamespace(ALL=3), RET_OK=0)
        class Context:
            count = 0
            def subscribe(self, *args, **kwargs):
                self.count += 1
                return (1, 'disconnected') if self.count == 1 else (0, None)
            def close(self):
                pass
        ctx = Context()
        bridge = market.Bridge()
        with patch.dict(sys.modules, {'moomoo': fake}), patch.object(bridge, 'ensure', return_value=ctx):
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                bridge.subscribe(('US.SNDK', '1m', 'all'))
            self.assertFalse(bridge.active)
            bridge.subscribe(('US.SNDK', '1m', 'all'))
            self.assertIn(('US.SNDK', '1m', 'all'), bridge.active)


if __name__ == '__main__':
    unittest.main()
