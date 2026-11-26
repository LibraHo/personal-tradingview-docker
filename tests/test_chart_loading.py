import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main as market


class ChartLoadingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (
            ('DB', str(Path(tmp.name) / 'chart.db')),
            ('last_fetch', {}), ('fetch_locks', {}), ('fetched_days', {}), ('history_failures', {}),
        ):
            replacement = patch.object(market, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        market.init_db()
        self.key = ('US.CACHE', '5m', 'all')
        self.row = dict(time=int(time.time()), open=1, high=2, low=1, close=1, volume=1, turnover=1)

    async def test_cached_chart_can_open_while_another_reader_refreshes(self):
        market.save_bars(self.key, [self.row])
        started, release = threading.Event(), threading.Event()

        def update(key, days):
            started.set()
            if not release.wait(5):
                raise RuntimeError('test did not release refresh')
            market.save_bars(key, [dict(self.row, close=2)])

        with patch.object(market.bridge, 'history', side_effect=update) as history:
            first = asyncio.create_task(market.bars(*self.key))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                preview = await asyncio.wait_for(market.bars(*self.key, prefer_cache=True), 2)
                self.assertTrue(preview['stale'] and preview['revalidate'])
                self.assertEqual(preview['bars'][0]['close'], 1)
                second = asyncio.create_task(market.bars(*self.key))
            finally:
                release.set()
            for response in await asyncio.gather(first, second):
                self.assertFalse(response['stale'])
                self.assertEqual(response['bars'][0]['close'], 2)
            history.assert_called_once()
            fresh = await market.bars(*self.key, prefer_cache=True)
            self.assertFalse(fresh['revalidate'])

    async def test_failed_refresh_backs_off_and_manual_refresh_can_retry(self):
        market.save_bars(self.key, [self.row])
        with patch.object(market.bridge, 'history', side_effect=[RuntimeError('offline'), 1]) as history:
            self.assertEqual((await market.bars(*self.key))['error'], 'offline')
            preview = await market.bars(*self.key, prefer_cache=True)
            self.assertEqual(preview['error'], 'offline')
            self.assertFalse(preview.get('revalidate'))
            self.assertTrue((await market.bars(*self.key))['stale'])
            self.assertFalse((await market.bars(*self.key, refresh=True))['stale'])
            self.assertEqual(history.call_count, 2)

    async def test_empty_cache_uses_upstream_and_propagates_outage(self):
        with patch.object(market.bridge, 'history', side_effect=RuntimeError('offline')):
            with self.assertRaises(market.HTTPException) as caught:
                await market.bars(*self.key, prefer_cache=True)
            self.assertEqual(caught.exception.status_code, 503)

    async def test_local_names_remain_available_while_bridge_is_busy(self):
        with market.connect_db() as db:
            db.execute('INSERT INTO symbol_names VALUES(?,?,?)', ('SH.600519', 'sample', time.time()))
        with market.bridge.lock:
            result = await asyncio.wait_for(market.symbol_names('SH.600519'), 2)
            partial = await asyncio.wait_for(market.symbol_names('SH.600519,SZ.000001', prefer_cache=True), 2)
        self.assertEqual(result['names'], {'SH.600519': 'sample'})
        self.assertEqual(partial, {'names': result['names'], 'missing': ['SZ.000001']})
