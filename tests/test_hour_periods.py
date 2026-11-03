import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock
import sys
import types
import time
from app import main as market
from app import drawing_api


class HourPeriodTests(unittest.TestCase):
    def test_native_periods_and_cn_four_hour_daily_source(self):
        for period, kind in [('120m', 'K_120M'), ('240m', 'K_240M')]:
            self.assertEqual(market.PERIODS.get(period), kind)
            self.assertEqual(market.validate('US.AAPL', period, 'all'), ('US.AAPL', period, 'all'))
            self.assertIn(period, drawing_api.PERIODS)
            self.assertEqual(market.period_from_push(kind), period)
            self.assertEqual(market.opend_kline('US.AAPL', period), 'K_60M')
        self.assertEqual(market.opend_kline('SH.000001', '240m'), 'K_DAY')
        self.assertEqual(market.opend_kline('SZ.000001', '240m'), 'K_DAY')
        self.assertEqual(market.opend_kline('SH.000001', '120m'), 'K_120M')
        with self.assertRaises(ValueError):
            market.validate('SH.000001', '240m', 'all')

    def test_cn_four_hour_and_daily_share_subscription_identity(self):
        cn4 = ('SH.000001', '240m', 'regular')
        day = ('SH.000001', '1d', 'regular')
        self.assertEqual(market.subscription_key(cn4), market.subscription_key(day))
        self.assertNotEqual(market.subscription_key(('US.AAPL', '240m', 'all')),
                            market.subscription_key(('US.AAPL', '1d', 'regular')))

    def test_native_push_routes_to_alias_and_correct_period_only(self):
        self.assertTrue(market.push_matches(('SH.000001', '240m', 'regular'), 'SH.000001', '1d'))
        self.assertTrue(market.push_matches(('US.AAPL', '240m', 'all'), 'US.AAPL', '60m'))
        self.assertFalse(market.push_matches(('US.AAPL', '240m', 'all'), 'US.AAPL', '1d'))
        self.assertFalse(market.push_matches(('SH.000001', '240m', 'regular'), 'SZ.000001', '1d'))

    def test_cache_periods_remain_separate(self):
        with tempfile.TemporaryDirectory() as root, patch.object(market, 'DB', str(Path(root) / 'cache.sqlite3')):
            market.init_db()
            row = dict(time=1700000000, open=1, high=2, low=1, close=2, volume=10, turnover=15)
            for period in ('120m', '240m', '1d'):
                market.save_bars(('SH.000001', period, 'regular'), [row])
            with market.connect_db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM bars').fetchone()[0], 3)

    def test_cn_four_hour_daily_cache_lifetime(self):
        self.assertEqual(market.default_history_days('240m', 'SH.000001'), market.DAILY_HISTORY_DAYS)
        self.assertEqual(market.retention_days('240m', 'SH.000001'), market.DAILY_RETENTION_DAYS)
        with tempfile.TemporaryDirectory() as root, patch.object(market, 'DB', str(Path(root) / 'cache.sqlite3')):
            market.init_db()
            row = dict(time=int(time.time())-60*86400, open=1, high=2, low=1, close=2, volume=10, turnover=15)
            market.save_bars(('SH.000001', '240m', 'regular'), [row])
            market.save_bars(('US.AAPL', '240m', 'all'), [row])
            market.prune_cache()
            self.assertEqual(len(market.read_bars(('SH.000001', '240m', 'regular'), 100, 10)), 1)
            self.assertEqual(market.read_bars(('US.AAPL', '240m', 'all'), 100, 10), [])

    def test_history_and_subscription_use_real_source_and_unsubscribe_once(self):
        sdk = types.SimpleNamespace(RET_OK=0,
            KLType=types.SimpleNamespace(K_DAY='day', K_120M='two', K_240M='four', K_60M='hour'),
            SubType=types.SimpleNamespace(K_DAY='day', K_120M='two', K_240M='four', K_60M='hour'),
            AuType=types.SimpleNamespace(NONE=0), Session=types.SimpleNamespace(NONE=0, ALL=3))
        frame = MagicMock();frame.to_dict.return_value=[]
        ctx = MagicMock();ctx.request_history_kline.return_value=(0,frame,None)
        ctx.subscribe.return_value=(0,None);ctx.unsubscribe.return_value=(0,None)
        bridge=market.Bridge();bridge.ctx=ctx;bridge.rate_limit=MagicMock()
        with patch.dict(sys.modules, {'moomoo':sdk}), patch.object(market, 'save_bars'):
            for symbol, period, mode, kind in [('SH.000001','240m','regular','day'),
                    ('SH.000001','120m','regular','two'), ('US.AAPL','240m','all','hour')]:
                bridge.history((symbol,period,mode),2)
                self.assertEqual(ctx.request_history_kline.call_args.kwargs['ktype'],kind)
            a=('SH.000001','240m','regular');b=('SH.000001','1d','regular')
            bridge.subscribe(a);bridge.subscribe(b)
            self.assertEqual(ctx.subscribe.call_count,1)
            self.assertEqual(ctx.subscribe.call_args.args[1],['day'])
            bridge.active={a:time.monotonic()-70,b:time.monotonic()-70}
            bridge.unsubscribe_unused()
            self.assertEqual(ctx.unsubscribe.call_count,1)
            self.assertEqual(ctx.unsubscribe.call_args.args[1],['day'])
            self.assertFalse(bridge.active)
