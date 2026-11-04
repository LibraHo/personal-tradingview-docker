import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from app import main as market
from app.opening_range import range_times, select_opening_range


class OpeningRangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=patch.object(market,'DB',str(Path(self.tmp.name)/'db.sqlite3'));self.db.start()
        market.init_db();market.fetch_locks.clear()
    def tearDown(self):self.db.stop();self.tmp.cleanup()
    def stamp(self,symbol,clock):
        return int(datetime.fromisoformat('2026-11-04T'+clock).replace(tzinfo=ZoneInfo('America/New_York' if symbol.startswith('US.') else 'Asia/Shanghai')).timestamp())
    def test_uses_exact_first_five_bar_excludes_premarket_and_next_bar(self):
        for symbol in ('US.AAPL','SH.000001'):
            times=range_times(symbol,'2026-11-04')
            rows=[dict(time=self.stamp(symbol,t),high=h,low=l) for t,h,l in [('09:25',999,1),('09:35',105,95),('09:40',200,20)]]
            result=select_opening_range(rows,symbol,times)
            self.assertEqual((result['high'],result['low']),(105,95))
            self.assertIsNone(select_opening_range(rows[:1]+rows[2:],symbol,times))
    def test_no_source_request_before_five_minutes_finish(self):
        now=self.stamp('US.AAPL','09:34:59')
        with patch.object(market.time,'time',return_value=now),patch.object(market.bridge,'opening_five') as fetch:
            result=asyncio.run(market.opening_range('US.AAPL','2026-11-04'))
            self.assertEqual(result['status'],'forming');fetch.assert_not_called()
    def test_confirmed_range_cached_and_survives_next_request(self):
        now=self.stamp('US.AAPL','10:00')
        rows=[dict(time=self.stamp('US.AAPL','09:35'),high=105,low=95)]
        with patch.object(market.time,'time',return_value=now),patch.object(market.bridge,'opening_five',return_value=rows) as fetch:
            for _ in range(2):
                result=asyncio.run(market.opening_range('US.AAPL','2026-11-04'))
                self.assertEqual(result['status'],'ready');self.assertEqual(result['high'],105)
            self.assertEqual(fetch.call_count,1)
    def test_dst_and_day_boundary(self):
        winter=range_times('US.AAPL','2026-11-04');summer=range_times('US.AAPL','2026-10-30')
        self.assertEqual(datetime.fromtimestamp(winter['confirmed_at'],ZoneInfo('UTC')).hour,14)
        self.assertEqual(datetime.fromtimestamp(summer['confirmed_at'],ZoneInfo('UTC')).hour,13)
        self.assertGreater(winter['day_end'],winter['regular_end'])

    def test_empty_day_is_cached_and_old_range_not_reused_for_next_day(self):
        now=self.stamp('US.AAPL','10:00')
        with patch.object(market.time,'time',return_value=now),patch.object(market.bridge,'opening_five',return_value=[]) as fetch:
            for _ in range(2):self.assertEqual(asyncio.run(market.opening_range('US.AAPL','2026-11-04'))['status'],'missing')
            self.assertEqual(fetch.call_count,1)

    def test_fetch_failure_keeps_only_same_day_cached_levels(self):
        now=self.stamp('US.AAPL','10:00')
        rows=[dict(time=self.stamp('US.AAPL','09:35'),high=105,low=95)]
        with patch.object(market.time,'time',return_value=now),patch.object(market.bridge,'opening_five',return_value=rows):
            asyncio.run(market.opening_range('US.AAPL','2026-11-04'))
        with patch.object(market.time,'time',return_value=now+1000),patch.object(market.bridge,'opening_five',side_effect=RuntimeError('offline')):
            result=asyncio.run(market.opening_range('US.AAPL','2026-11-04'))
            self.assertTrue(result['stale']);self.assertEqual(result['high'],105)
            with self.assertRaises(market.HTTPException):asyncio.run(market.opening_range('SH.000001','2026-11-04'))

    def test_first_bar_delayed_after_open_retries_after_thirty_seconds(self):
        now=self.stamp('US.AAPL','09:35:02')
        rows=[dict(time=self.stamp('US.AAPL','09:35'),high=105,low=95)]
        with patch.object(market.time,'time',return_value=now),patch.object(market.bridge,'opening_five',return_value=[]):
            self.assertEqual(asyncio.run(market.opening_range('US.AAPL','2026-11-04'))['status'],'missing')
        with patch.object(market.time,'time',return_value=now+31),patch.object(market.bridge,'opening_five',return_value=rows) as fetch:
            result=asyncio.run(market.opening_range('US.AAPL','2026-11-04'))
            self.assertEqual(result['status'],'ready');self.assertEqual(result['high'],105)
            self.assertEqual(fetch.call_count,1)
