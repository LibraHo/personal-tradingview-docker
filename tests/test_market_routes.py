"""Verify capability routing across actual chart endpoints and provider lifecycle."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.indicators import INPUTS, check_inputs
from app.market_data import DisabledFeed, MarketRoutes, RoutedStreams
from tests.test_market_data import PriceFeed


class RegionalFeed(PriceFeed):
    bar_label = 'start'
    bar_profiles = {'qfq': 'demo-adjustment-with-shares'}

    def __init__(self, source):
        self.source_id = source

    def names(self, symbols):
        return {s: self.source_id for s in symbols}


class StreamFeed(RegionalFeed):
    live_adjustments = ('qfq',)

    def subscribe_bars(self, key, basis, emit):
        self.emit = emit
        return lambda: setattr(self, 'emit', None)


class MarketRouteTests(unittest.TestCase):
    def setUp(self):
        self.us = RegionalFeed('us_history')
        self.cn = RegionalFeed('cn_history')
        self.live = StreamFeed('us_live')
        providers = {p.source_id:p for p in (self.us, self.cn, self.live)}
        providers.update(opend=main.bridge, disabled=DisabledFeed(), eastmoney=DisabledFeed())
        self.router = MarketRoutes('disabled', 'qfq', {
            'US': {'default':'us_history', 'live':'us_live'},
            'CN': {'default':'cn_history', 'adjustment':'none'}}, providers, main.save_bars)
        local = tempfile.TemporaryDirectory()
        self.addCleanup(local.cleanup)
        self.streams = RoutedStreams(self.router, main.on_provider_bars, main.listeners, 2)
        for key, value in dict(DB=str(Path(local.name)/'market.db'), market_data=self.router,
                               streams=self.streams, last_fetch={}, fetch_locks={}, history_failures={}).items():
            swap = patch.object(main, key, value)
            swap.start()
            self.addCleanup(swap.stop)
        main.init_db()
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_mixed_request_uses_market_sources_and_keeps_order(self):
        symbols = 'SZ.000001,US.TEST,SH.600000'
        data = self.client.get('/api/quotes', params={'symbols':symbols}).json()
        self.assertEqual([r['symbol'] for r in data['quotes']], symbols.split(','))
        self.assertEqual([r['provider'] for r in data['quotes']], ['cn_history','us_history','cn_history'])
        names = self.client.get('/api/symbols/names', params={'symbols':symbols}).json()['names']
        self.assertEqual(names, {s:('us_history' if s.startswith('US.') else 'cn_history') for s in symbols.split(',')})
        config = self.client.get('/api/status?market=CN').json()
        self.assertEqual(config['adjustment'], 'none')
        self.assertFalse(config['capabilities']['depth'])

    def test_compatible_push_records_actual_source_and_invalidates_specific_indicator(self):
        key = ('US.TEST','5m','all')
        query = dict(zip(('symbol','period','mode'), key))
        initial = self.client.get('/api/bars',params=query).json()
        self.assertTrue(initial['live_supported'])
        self.assertIn('us_history~us_live', initial['series_revision'])
        with self.client.websocket_connect('/api/stream?symbol=US.TEST&period=5m&mode=all') as ws:
            self.assertTrue(ws.receive_json()['connected'])
            self.assertTrue(self.live.emit)
            with patch.object(main, 'loop', ws.portal.call(asyncio.get_running_loop)):
                self.live.emit([{**initial['bars'][-1], 'close':21}])
            self.assertEqual((message := ws.receive_json())['bar']['provider'], 'us_live')
            self.assertEqual(message['bar']['close'], 21)
        rows = self.client.get('/api/bars',params={**query,'prefer_cache':True}).json()['bars']
        self.assertEqual((rows[-2]['provider'], rows[-1]['provider']), ('us_history','us_live'))
        with patch.dict(INPUTS, {'SOURCE_ONLY':{'providers':['us_history']}}):
            with self.assertRaisesRegex(ValueError,'需要行情源'):
                check_inputs(rows, 'SOURCE_ONLY')
        self.streams.close()
        self.assertIsNone(self.live.emit)

    def test_incompatible_or_unknown_profile_uses_history_and_separate_cache(self):
        mixed = main.scope_for('US.TEST')
        self.live.bar_label = 'end'
        self.assertNotEqual(main.scope_for('US.TEST'), mixed)
        with self.client.websocket_connect('/api/stream?symbol=US.TEST&period=5m&mode=all') as ws:
            reply = ws.receive_json()
            self.assertFalse(reply['connected'])
            self.assertIn('未确认兼容',reply['live_reason'])
        with self.router.for_market('US').using_adjustment('none'):
            self.assertIn('/none/', main.scope_for('US.TEST'))
        self.assertIn('/qfq/', main.scope_for('US.TEST'))


class StandaloneMarketTests(unittest.TestCase):
    def test_boot_read_and_shutdown_without_opend_sdk(self):
        program = """
import sys
attempts = []
class Guard:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'moomoo':
            attempts.append(fullname)
            raise ImportError('unexpected OpenD dependency')
sys.meta_path.insert(0, Guard())
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    config = client.get('/api/status').json()
    assert config['provider'] == 'test_prices' and not config['opend_configured'], config
    bars = client.get('/api/bars?symbol=US.TEST&period=5m&mode=all').json()
    assert bars['bars'] and not bars['live_supported'], bars
assert not attempts, attempts
"""
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'DB_PATH':str(Path(tmp)/'market.db'), 'MARKET_DATA_PROVIDER':'disabled',
                   'BROKER_PROVIDER':'disabled', 'MARKET_DATA_ROUTES':json.dumps({
                       'US':{'history':'tests.test_market_data:PriceFeed'},'CN':{'limit_pool':'disabled'}}),
                   'DRAWING_API_TOKEN':'t'*32, 'TRUSTED_USER_HEADER':''}
            result = subprocess.run([sys.executable,'-c',program], capture_output=True, env=env, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
