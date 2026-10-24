import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from app import main as market


class PersistentCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(market, 'DB', str(Path(self.tmp.name) / 'cache.sqlite3'))
        self.db_patch.start()
        market.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_restart_reuses_persisted_window_and_covers_offline_gap(self):
        key = ('US.SNDK', '1d', 'all')
        stamp = int(time.time()) - 10 * 86400
        market.save_bars(key, [dict(time=stamp, open=1, high=1, low=1, close=1, volume=1, turnover=1)])
        market.save_sync_state(key, 730)
        days, last, latest = market.sync_state(key)
        self.assertEqual(days, 730)
        span = market.refresh_span(key, 730, days, latest, last)
        self.assertGreaterEqual(span, 11)
        self.assertLessEqual(span, 13)
        self.assertEqual(market.refresh_span(key, 1000, days, latest, last), 1000)

    def test_permission_denial_preserves_other_market_context(self):
        bridge = market.Bridge()
        ctx = object()
        bridge.ctx = ctx
        with self.assertRaises(market.QuotePermissionError):
            bridge.raise_quote_error('SH.600584', '无权限订阅SH.600584的行情')
        self.assertIs(bridge.ctx, ctx)
        with self.assertRaises(market.QuotePermissionError):
            bridge.check_permission('SZ.000001')
        bridge.check_permission('US.SNDK')

    def test_depth_settings_roundtrip_and_reject_bad_values(self):
        value = dict(enabled=False, cached=True, amount=100000, qty=100, count=3)
        market.put_setting('depth-US.SNDK', market.Setting(value=value))
        self.assertEqual(market.get_setting('depth-US.SNDK')['value'], value)
        for invalid in (dict(value, amount=float('nan')), dict(value, count=True)):
            with self.assertRaises(market.HTTPException):
                market.put_setting('depth-US.SNDK', market.Setting(value=invalid))
