import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import main as market
from app import stock_search as directory


class SymbolSearchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for override in (patch.object(market, 'DB', str(Path(temp.name) / 'market.sqlite3')),
                         patch.dict(sys.modules, {'moomoo': types.SimpleNamespace(RET_OK=0)})):
            override.start()
            self.addCleanup(override.stop)
        market.init_db()
        self.bridge = market.Bridge()
        self.bridge.rate_limit = MagicMock()
        self.ctx = MagicMock()
        self.bridge.ensure = MagicMock(return_value=self.ctx)
        self.listings = {
            ('SH', 'STOCK'): [('SH.600519', '贵州茅台'), ('SH.600584', '长电科技'), ('SH.900901', 'B股')],
            ('SZ', 'STOCK'): [('SZ.000001', '平安银行')],
            ('SH', 'IDX'): [('SH.000001', '上证指数'), ('SH.000300', '沪深300')],
            ('SZ', 'IDX'): [('SZ.399001', '深证成指')],
            ('SH', 'ETF'): [('SH.560780', '半导设备')],
            ('SZ', 'ETF'): [('SZ.159516', '半导体设备材料ETF'), ('SZ.159999', '测试行业精选ETF')],
            ('US', 'STOCK'): [('US.AAPL', '苹果'), ('US.BRK.B', 'Berkshire Hathaway')],
            ('US', 'ETF'): [('US.SMH', 'VanEck Semiconductor ETF')],
        }

        def basic(market, stock_type):
            frame = MagicMock()
            frame.to_dict.return_value = [dict(code=code, name=name) for code, name in self.listings[market, stock_type]]
            return 0, frame
        self.ctx.get_stock_basicinfo.side_effect = basic

    async def update_once(self, connection_factory=None):
        # Complete exactly one scheduled check, without waiting five minutes.
        class OneCheck(asyncio.Event):
            async def wait(self):
                self.set()
                return True
        await directory.maintain_directory(self.bridge, market.connect_db, OneCheck(), connection_factory)

    def test_background_refresh_has_its_own_quote_session(self):
        session = market.Bridge()
        session.ctx = self.ctx
        session.rate_limit = MagicMock()
        with self.bridge.lock:
            asyncio.run(self.update_once(lambda: session))
        self.bridge.ensure.assert_not_called()
        self.ctx.close.assert_called_once()
        self.assertEqual(self.search('AAPL','US')[0]['symbol'], 'US.AAPL')

    def search(self, query, market_code='CN'):
        return self.bridge.search_symbols(query, market=market_code)['results']

    def test_stock_index_and_persisted_names(self):
        asyncio.run(self.update_once())
        self.assertEqual(self.search('茅台')[0], dict(symbol='SH.600519', name='贵州茅台', kind='stock'))
        self.assertEqual(self.search('600584')[0]['name'], '长电科技')
        self.assertEqual(self.search('平安')[0]['symbol'], 'SZ.000001')
        for query in ('%', '_', '900901'):
            self.assertEqual(self.search(query), [])
        self.assertEqual({row['symbol'] for row in self.search('000001')}, {'SH.000001', 'SZ.000001'})
        self.assertEqual(self.search('sh.000001')[0]['kind'], 'index')
        self.bridge = market.Bridge()
        self.bridge.ensure = MagicMock(side_effect=AssertionError('fresh directory should be reused'))
        asyncio.run(self.update_once())
        self.bridge.ensure.assert_not_called()
        self.assertEqual(self.search('贵州 茅台')[0]['symbol'], 'SH.600519')
        self.assertEqual(self.search('沪深')[0]['symbol'], 'SH.000300')

    def test_etf_names_and_codes(self):
        self.assertTrue(self.search('半导体设备ETF'))
        asyncio.run(self.update_once())
        for query in ('半导体设备ETF', '半导体设备 etf', '560780', 'sh.560780'):
            self.assertIn(('SH.560780', 'etf'), [(r['symbol'], r['kind']) for r in self.search(query)])
        self.assertEqual(self.search('测试行业ETF')[0]['symbol'], 'SZ.159999')
        self.assertEqual(self.search('159516')[0]['kind'], 'etf')
        self.assertEqual(len(self.search('ETF')), 3)

    def test_cached_search_does_not_wait_for_quote_lock(self):
        with market.connect_db() as db:
            db.execute('INSERT INTO symbol_names VALUES(?,?,?)', ('SH.600519', '贵州茅台', time.time()))
        with ThreadPoolExecutor(1) as pool:
            with self.bridge.lock:
                future = pool.submit(self.search, '茅台')
                self.assertEqual(future.result(timeout=1)[0]['symbol'], 'SH.600519')
        self.bridge.ensure.assert_not_called()

    def test_expired_directory_updates_retries_and_removes_old_members(self):
        asyncio.run(self.update_once())
        key = 'symbol_directory.SZ.ETF'
        with market.connect_db() as db:
            db.execute('UPDATE settings SET value=? WHERE key=?', (str(time.time()-90000), key))
        basic = self.ctx.get_stock_basicinfo
        normal = basic.side_effect
        basic.reset_mock()
        basic.side_effect = RuntimeError('offline')
        with self.assertLogs(directory.LOG, level='WARNING'):
            asyncio.run(self.update_once())
        self.assertTrue(self.bridge.search_symbols('159999')['stale'])
        self.assertEqual(self.search('159999')[0]['kind'], 'etf')
        basic.assert_called_once_with(market='SZ', stock_type='ETF')
        basic.side_effect = normal
        self.listings['SZ', 'ETF'] = [('SZ.159888', '测试更新ETF')]
        asyncio.run(self.update_once())
        self.assertFalse(self.bridge.search_symbols('159888')['stale'])
        self.assertEqual(self.search('159888')[0]['kind'], 'etf')
        self.assertEqual(self.search('159999'), [])
        self.assertEqual(self.search('159516'), [])

    def test_us_directory_and_api_validation(self):
        asyncio.run(self.update_once())
        with patch.object(market, 'bridge', self.bridge):
            client = TestClient(market.app)
            for query, symbol in [('苹果','US.AAPL'), ('aaPl','US.AAPL'), ('Semiconductor','US.SMH'),
                                  ('us.brk.b','US.BRK.B'), ('Berkshire Hathaway','US.BRK.B')]:
                response = client.get('/api/symbols/search', params={'market':'US','q':query})
                self.assertEqual(response.json()['results'][0]['symbol'], symbol)
            self.assertEqual(self.search('ETF', 'US')[0]['kind'], 'etf')
            self.assertEqual(self.search('AAPL'), [])
            self.assertEqual(self.search('半导体设备', 'US'), [])
            for params in ({'market':'BAD','q':'x'}, {'q':'a'*50}, {'q':'x','limit':21}):
                self.assertEqual(client.get('/api/symbols/search', params=params).status_code, 400)
