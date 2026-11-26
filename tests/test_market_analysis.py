import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import market_analysis
from app.agent_settings import install as install_settings
from app.api_management import token_db


class MarketAnalysisTests(unittest.TestCase):
    path = '/api/trade/market-analysis'
    chart = {'symbol': 'US.AAPL', 'period': '1m', 'mode': 'extended'}

    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        path = str(Path(tmp) / 'market.sqlite3')
        sqlite3.connect(path).close()
        self.enterContext(patch.dict('os.environ', DB_PATH=path, OPENCLAW_BASE_URL='http://localhost',
                                     OPENCLAW_GATEWAY_TOKEN='test', OPENCLAW_AGENT_ID=''))
        app = FastAPI()
        install_settings(app, token_db)
        market_analysis.install(app, token_db)
        self.client = self.enterContext(TestClient(app))
        self.bars = self.enterContext(patch.object(market_analysis, 'recent_bars'))
        self.agent = self.enterContext(patch.object(market_analysis, 'complete', return_value='测试解读'))

    def test_effective_settings_gate_both_operations(self):
        options = self.client.get(self.path, params=self.chart).json()
        self.assertTrue(options['enabled'])
        self.assertEqual(options['defaults'], ['60m', '1d'])
        self.client.put('/api/trade/agent-settings', json={'provider':'local'}).raise_for_status()
        self.assertFalse(self.client.get(self.path, params=self.chart).json()['enabled'])
        self.assertEqual(self.client.post(self.path, json=self.chart).status_code, 409)
        self.bars.assert_not_called()
        self.agent.assert_not_called()

    def test_defaults_follow_market_and_period(self):
        for symbol, period, defaults in [
                ('US.AAPL', '60m', ['1d', '1w']), ('SH.600519', '240m', ['1w', '1mo']),
                ('US.AAPL', '1d', ['1w', '1mo']), ('US.AAPL', '1w', ['1mo']),
                ('US.AAPL', '1mo', [])]:
            with self.subTest(symbol=symbol, period=period):
                options = self.client.get(self.path, params=dict(symbol=symbol, period=period)).json()
                self.assertEqual(options['defaults'], defaults)

    def test_payload_and_partial_coverage(self):
        def fetch(symbol, period, mode, limit):
            if period == '1d':
                raise OSError('offline')
            rows = [dict(time=i, open=100, high=102, low=99, close=101, volume=i*10,
                         session='overnight' if i==100 else 'regular') for i in range(101)]
            return {'bars': rows, 'stale': period == '60m'}
        self.bars.side_effect = fetch
        response = self.client.post(self.path, json=self.chart)
        response.raise_for_status()
        context = self.agent.call_args.args[-1]
        self.assertEqual(context['columns'], ('time','open','high','low','close','volume'))
        primary, hour, daily = context['frames']
        self.assertEqual(primary['bars'][-1], [99,100,102,99,101,990])
        self.assertEqual(hour['mode'], 'extended')
        self.assertEqual(daily['mode'], 'regular')
        self.assertEqual(daily['bars'], [])
        coverage = response.json()['coverage']
        self.assertEqual([f['count'] for f in coverage], [79,39,0])
        self.assertTrue(coverage[1]['stale'])
        self.assertTrue(coverage[2]['issue'])
        self.assertEqual(coverage[0]['last'], 99)

    def test_primary_required_and_references_validated(self):
        chart = dict(symbol='SH.600519', period='1d', mode='all')
        for refs in [['1d'], ['5m'], ['1w','1w']]:
            self.assertEqual(self.client.post(self.path,json={**chart,'references':refs}).status_code,422)
        self.bars.assert_not_called()
        self.bars.return_value = {'bars': []}
        self.assertEqual(self.client.post(self.path,json={**chart,'references':[]}).status_code,503)
        self.bars.assert_called_once_with('SH.600519','1d','regular',80)
        self.agent.assert_not_called()
