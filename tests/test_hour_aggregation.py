import unittest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from app.hour_bars import aggregate_hours, hour_bucket
from app import main as market

ET = ZoneInfo('America/New_York')
def bar(clock, close=2, day='2026-11-03'):
    return dict(time=int(datetime.fromisoformat(day+'T'+clock).replace(tzinfo=ET).timestamp()),
                open=1, high=close+1, low=.5, close=close, volume=10, turnover=20)

class HourAggregationTests(unittest.TestCase):
    def test_two_and_four_hours_from_regular_open(self):
        source=[bar('09:30',2),bar('10:30',3),bar('11:30',4),bar('12:30',5)]
        two=aggregate_hours(source,'120m');four=aggregate_hours(source,'240m')
        self.assertEqual(len(two),2);self.assertEqual(len(four),1)
        self.assertEqual(four[0],dict(time=source[0]['time'],open=1,high=6,low=.5,close=5,volume=40,turnover=80))
    def test_sessions_and_days_never_merge(self):
        source=[bar('08:00'),bar('09:00'),bar('09:30'),bar('15:30'),bar('16:00'),bar('20:00'),bar('00:00',day='2026-11-04')]
        result=aggregate_hours(source,'240m')
        self.assertEqual(len(result),6)
        self.assertEqual(result[0]['volume'],20)
        self.assertEqual(result[1]['time'],bar('09:30')['time'])
    def test_updates_replace_source_candle_and_dont_double_volume(self):
        source=[bar('09:30',2),bar('10:30',3),bar('10:30',4)]
        result=aggregate_hours(source,'120m')
        self.assertEqual(result[0]['volume'],20)
        self.assertEqual(result[0]['close'],4)
    def test_timezone_dst_anchor_tracks_market_open(self):
        for day in ('2026-10-30','2026-11-03'):
            start=bar('09:30',day=day)['time']
            self.assertEqual(hour_bucket(bar('10:30',day=day)['time'],'240m'),start)


class HourPushTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_rebuilds_full_bucket_from_cached_source_and_corrects(self):
        key=('US.AAPL','120m','regular');source=('US.AAPL','60m','regular')
        with tempfile.TemporaryDirectory() as root, patch.object(market,'DB',str(Path(root)/'db.sqlite3')):
            market.init_db();market.save_bars(source,[bar('09:30',2),bar('10:30',3)])
            queue=asyncio.Queue(maxsize=10);market.listeners[key]={queue}
            try:
                for close in (4,5):
                    await market.publish(key,[bar('10:30',close)])
                    item=await queue.get()
                    self.assertEqual(item['bar']['volume'],20)
                    self.assertEqual(item['bar']['close'],close)
                    self.assertEqual(item['bar']['time'],bar('09:30')['time'])
                with market.connect_db() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM bars WHERE period='120m'").fetchone()[0],1)
            finally:market.listeners.pop(key,None)
