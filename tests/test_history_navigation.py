import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from app import main as market


class HistoryNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(market, 'DB', str(Path(self.tmp.name) / 'cache.sqlite3'))
        self.db_patch.start()
        market.init_db()
        market.fetch_locks.clear()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_old_intraday_cache_is_readable_beyond_rolling_retention(self):
        stamp = int(time.time()) - 90 * 86400
        key = ('US.AAPL', '15m', 'all')
        market.save_bars(key, [dict(time=stamp, open=1, high=2, low=1, close=2, volume=5, turnover=8)])
        self.assertEqual(len(market.read_bars_before(key, stamp+1, 100)), 1)

    def test_date_window_fetches_old_date_then_reuses_cache(self):
        stamp = int(time.time()) - 90 * 86400
        def history(key, days, end_date=None):
            market.save_bars(key, [dict(time=stamp, open=1, high=2, low=1, close=2, volume=5, turnover=8)])
        with patch.object(market.bridge, 'history', side_effect=history) as fetch:
            for _ in range(2):
                result = asyncio.run(market.bars_window('US.AAPL', '15m', 'all', stamp-3600, stamp+3600))
                self.assertEqual(len(result['bars']), 1)
            self.assertEqual(fetch.call_count, 1)
        market.prune_cache()
        self.assertEqual(len(market.read_bars_before(('US.AAPL','15m','all'),stamp+1,100)),1)

    def test_invalid_window_does_not_contact_opend(self):
        stamp=int(time.time())-90*86400
        with patch.object(market.bridge,'history') as fetch:
            with self.assertRaises(market.HTTPException):
                asyncio.run(market.bars_window('US.AAPL','15m','all',stamp,stamp+32*86400))
            fetch.assert_not_called()

    def test_failed_fetch_is_not_saved_as_successful_coverage(self):
        stamp=int(time.time())-90*86400
        with patch.object(market.bridge,'history',side_effect=RuntimeError('disconnected')):
            with self.assertRaises(market.HTTPException):
                asyncio.run(market.bars_window('US.AAPL','15m','all',stamp-3600,stamp+3600))
        with market.connect_db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM history_windows').fetchone()[0],0)

    def test_backfill_does_not_jump_over_gap_to_distant_cached_window(self):
        now=int(time.time());before=now-30*86400;far=now-90*86400;near=before-86400
        key=('US.AAPL','15m','all')
        row=lambda stamp:dict(time=stamp,open=1,high=2,low=1,close=2,volume=5,turnover=8)
        market.save_bars(key,[row(far)])
        market.remember_history_window(key,far-86400,far+86400)
        with patch.object(market.bridge,'history',side_effect=lambda *a:market.save_bars(key,[row(near)])) as fetch:
            result=asyncio.run(market.older_bars(*key,before))
            self.assertEqual([b['time'] for b in result['bars']],[near])
            fetch.assert_called_once()
            # The verified remainder of the same adjacent window is reusable,
            # but distant cached rows must still not leak into this page.
            result=asyncio.run(market.older_bars(*key,near))
            self.assertEqual(result['bars'],[])
            self.assertLess(result['next_before'],near)
            self.assertEqual(fetch.call_count,1)
