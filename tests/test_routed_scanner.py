import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.market_data import MarketData
from app.market_analytics import Analytics, EastmoneyLimits, ladder
from app.radar import Radar, ProviderRadar
from app.scan_service import ScanService
from app.tencent_archive import TencentArchive


class Routes:
    def __init__(self):
        self.routes = {}
        self.identity = "configuration-1"

    def add(self, market, name, ident, **methods):
        adapter = SimpleNamespace(source_id=ident, adjustments=('none',), **methods)
        self.routes[market, name] = MarketData(adapter, 'none', None)
        return adapter

    def for_market(self, scope, name):
        market = 'US' if scope == 'US' or scope.startswith('US.') else 'CN'
        return self.routes[market, name]


class RoutedScannerTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name, 'market.db')
        self.routes = Routes()
        self.radar = ProviderRadar(Radar(SimpleNamespace(lock=threading.RLock()), self.connect),
                                   self.routes)
        self.service = ScanService(SimpleNamespace(connect_db=self.connect, market_data=self.routes), self.radar)
        with self.connect() as db:
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)')
            db.execute('CREATE TABLE symbol_names(symbol TEXT PRIMARY KEY, name TEXT)')
        for market in ('CN', 'US'):
            for capability in ('history', 'live', 'names', 'catalog', 'snapshots', 'trading_days', 'limit_pool'):
                self.routes.add(market, capability, market.lower()+'_'+capability)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def test_catalog_calendar_and_bulk_names_are_independent(self):
        cn, us = Mock(return_value={'SH.600000':'浦发银行'}), Mock(return_value={'US.AAPL':'Apple'})
        self.routes.add('CN','names','cn_directory',names=cn)
        self.routes.add('US','names','us_directory',names=us)
        self.routes.add('CN','catalog','boards',catalog=lambda *_: {'rows':[{'symbol':'SH.BK1','name':'银行板块'}]})
        self.routes.add('US','trading_days','sessions',trading_days=lambda _: {'2026-11-27':'MORNING'})
        with self.connect() as db:
            db.execute("INSERT INTO symbol_names VALUES('US.AAPL','wrong old source')")
        self.assertEqual(self.radar.catalog('CN','industry')['source'], 'boards')
        self.assertEqual(self.service.calendar.days('US.AAPL'), {'2026-11-27':'MORNING'})
        codes = ['US.AAPL','SH.600000']
        result = asyncio.run(self.service.resolve({'kind':'symbols','symbols':codes}))
        self.assertEqual([row['name'] for row in result], ['Apple','浦发银行'])
        cn.assert_called_once_with(['SH.600000'])
        us.assert_called_once_with(['US.AAPL'])
        self.assertEqual(self.service.watchlists('CN')['names'], {'SH.BK1':'银行板块', 'SH.600000':'浦发银行'})
        self.routes.add('CN','catalog','other')
        self.routes.add('CN','names','other_names')
        self.assertEqual(self.service.watchlists('CN')['names'], {})
        self.assertEqual(self.service.market_sources('US')['US'],
                         dict(history='us_history',live='us_live',adjustment='none',calendar='sessions'))
        self.assertEqual(self.service.feed_identity(), self.routes.identity)

    def test_analytics_cache_and_snapshot_provenance_follow_each_route(self):
        previous, today = ((date.today()-timedelta(days=i)).isoformat() for i in (3,2))
        self.routes.add('CN','trading_days','calendar',trading_days=lambda _: {previous:'WHOLE',today:'WHOLE'})
        def feed(kind, day):
            return {'trade_date':day, 'rows':[{'symbol':'SH.600000','streak':1}] if kind!='broken' else []}
        self.routes.add('CN','limit_pool','pools',limit_pool=feed)
        def quotes(symbols):
            return [{'symbol':code,'change_percent':2,'update_time':today+' 10:00:00'} for code in symbols],False
        self.routes.add('CN','snapshots','quotes',snapshots=quotes)
        first = Analytics(self.service)
        self.assertEqual(first.limit_board(today)['sealed'][0]['symbol'], 'SH.600000')
        cn = asyncio.run(first.cn({'done': 0}))
        self.assertIn('quotes',cn['source'])
        self.assertEqual(cn['feedback']['previous']['average_change'],2)
        self.routes.add('CN','limit_pool','second',limit_pool=lambda kind,day:{'rows':[]})
        self.assertEqual(Analytics(self.service).limit_board(today)['sealed'],[])
        self.routes.add('CN','limit_pool','unsupported')
        with patch.object(EastmoneyLimits, 'limit_pool', side_effect=AssertionError('unexpected fallback')):
            with self.assertRaisesRegex(ValueError,'unsupported'):
                Analytics(self.service).limit_board(today)

    def test_missing_streak_preserves_independent_statistics(self):
        rows = [{'symbol':'SH.600001', 'streak':2}, {'symbol':'SZ.000001'}]
        previous = [{'symbol':'SH.600001'}, {'symbol':'SZ.000001', 'streak':None}]
        result = ladder(rows, previous, [{'symbol':'SH.600002'}])
        self.assertIsNone(result['max_streak'])
        self.assertEqual(result['promotion'], [])
        self.assertEqual([row['level'] for row in result['levels']], [2])
        self.assertEqual(result['broken_rate'], 1/3)
        self.assertIn('连板天数', ''.join(result['warnings']))

    def test_archive_cannot_confirm_a_scan_from_fresh_local_cache(self):
        archive = TencentArchive(self.path.parent)
        fixture = self.path.parent / 'sh600000.json'
        fixture.write_text(json.dumps({'raw': [[['2026-11-16','10','11','12','9','100']]]}))
        self.routes.routes['CN','history'] = MarketData(archive,'none',None)
        self.service.main.read_bars = Mock()
        self.service.main.sync_state = Mock(return_value=(9999, float('inf'), None))
        self.service.main.bars = Mock()
        with self.assertRaisesRegex(ValueError,'腾讯离线归档截至 2026-11-16'):
            asyncio.run(self.service.load('SH.600000','1d'))
        self.service.main.read_bars.assert_not_called()
        self.service.main.bars.assert_not_called()
