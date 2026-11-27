"""Exercise the normal chart API with a provider that has prices but no volume."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from app import main
from app.indicators import INPUTS, check_inputs
from app.market_data import MarketData, ProviderStreams, load_provider
from app.hour_bars import aggregate_hours
from app.scan_engine import series


class PriceFeed:
    source_id = 'test_prices'
    adjustments = ('none', 'qfq')
    live_adjustments = ()

    def fetch_bars(self, key, days, end_date, adjustment):
        price = 20 if adjustment == 'qfq' else 40
        stamp = int(time.time()) // 300 * 300
        return [dict(time=stamp-300*i, open=price, high=price+1, low=price-1, close=price,
                     fields={'net_flow': -4}) for i in reversed(range(35))]

    def snapshots(self, symbols):
        return [{'symbol': symbol, 'price': 40} for symbol in symbols], False


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / 'test.db'
        for name, value in [('DB',str(self.db)), ('last_fetch',{}), ('fetch_locks',{}),
                            ('history_failures',{})]:
            swap = patch.object(main, name, value)
            swap.start()
            self.addCleanup(swap.stop)
        self.provider = load_provider(__name__ + ':PriceFeed', main.bridge)
        self.feed = MarketData(self.provider, 'qfq', main.save_bars)
        swap = patch.object(main,'market_data',self.feed)
        swap.start()
        self.addCleanup(swap.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.query = {'symbol':'US.TEST','period':'5m','mode':'all'}

    def test_old_cache_is_preserved_and_never_relabelled(self):
        with main.connect_db() as db:
            db.execute('CREATE TABLE bars(symbol TEXT, close REAL)')
            db.execute("INSERT INTO bars VALUES('US.TEST', 100)")
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)')
            db.execute("INSERT INTO settings VALUES('workspace', 'saved')")
        main.init_db()
        main.init_db()
        with main.connect_db() as db:
            self.assertEqual(db.execute('SELECT close FROM legacy_bars').fetchone()[0], 100)
            self.assertEqual(db.execute('SELECT count(*) FROM bars').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT value FROM settings').fetchone()[0], 'saved')

    def test_http_and_websocket_on_history_only_feed(self):
        main.init_db()
        data = self.client.get('/api/bars',params=self.query).json()
        self.assertEqual((data['provider'],data['adjustment']), ('test_prices','qfq'))
        self.assertFalse(data['live_supported'])
        row = data['bars'][-1]
        self.assertIsNone(row['volume'])
        self.assertEqual(row['fields']['net_flow'], -4)
        with patch.dict(INPUTS, {'TEST': {'fields':['net_flow'], 'providers':['test_prices']}}):
            check_inputs([row], 'TEST')
            with self.assertRaisesRegex(ValueError,'需要行情源'):
                check_inputs([{**row,'provider':'other'}], 'TEST')
        for name, status in [('MACD',200), ('VWAP',400)]:
            result = self.client.get('/api/indicators',params={**self.query,'name':name})
            self.assertEqual(result.status_code,status,result.text)
            if name == 'VWAP':
                self.assertIn('成交量',result.json()['detail'])
        with self.assertRaisesRegex(ValueError,'成交量'):
            series(data['bars'], {'name':'PRICE','line':'volume'})
        with self.client.websocket_connect('/api/stream?symbol=US.TEST&period=5m&mode=all') as ws:
            self.assertFalse(ws.receive_json()['connected'])
        quote = self.client.get('/api/quotes',params={'symbols':'US.TEST'}).json()
        self.assertEqual((quote['quotes'][0]['price'], quote['adjustment']), (40,'none'))
        self.assertIn('盘口深度',self.client.get('/api/depth',params={'symbol':'US.TEST'}).json()['detail'])

    def test_actual_prices_for_plans_do_not_change_chart_or_its_cache(self):
        main.init_db()
        async def read_both():
            return await asyncio.gather(main.bars(**self.query), main.actual_price_bars(**self.query))
        chart, actual = asyncio.run(read_both())
        self.assertEqual((chart['adjustment'], chart['bars'][-1]['close']), ('qfq',20))
        self.assertEqual((actual['adjustment'], actual['bars'][-1]['close']), ('none',40))
        self.assertEqual(main.read_bars(tuple(self.query.values()),1,1)[0]['close'],20)

    def test_cache_coverage_isolated_by_source_basis_and_revision(self):
        main.init_db()
        key = tuple(self.query.values())
        asyncio.run(main.bars(*key))
        main.remember_history_window(key, 1, 2)
        for ident,basis in [('test_prices','none'),('other_prices','qfq')]:
            other = PriceFeed()
            other.source_id = ident
            with patch.object(main,'market_data',MarketData(other,basis,main.save_bars)):
                self.assertEqual(main.read_bars(key,1,10), [])
                self.assertEqual(main.sync_state(key), (0,0,None))
                result = asyncio.run(main.bars(*key))
                self.assertEqual(result['bars'][-1]['close'], 40 if basis=='none' else 20)
        token = main._scope.set('test_prices/qfq/2000-01-01')
        try:
            self.assertEqual(main.read_bars(key,1,10), [])
        finally:
            main._scope.reset(token)

    def test_missing_measure_propagates_through_aggregation_and_real_zero_survives(self):
        row = self.provider.fetch_bars(None,0,None,'qfq')[-1]
        row.update(time=1800000000, volume=0, turnover=0)
        result = aggregate_hours([row, dict(row,time=row['time']+1,volume=None)],'120m')[0]
        self.assertIsNone(result['volume'])
        self.assertEqual(result['turnover'],0)

    def test_opend_push_checks_wire_basis_before_writing(self):
        main.init_db()
        key = ('US.TEST','5m','all')
        bridge = main.Bridge()
        bridge.active[key] = 1
        bridge.sinks[key] = lambda rows: main.on_provider_bars(key, rows)
        feed = MarketData(bridge, 'qfq', main.save_bars)
        frame = Mock()
        frame.groupby.return_value = [(('US.TEST','K_5M'),frame)]
        frame.to_dict.return_value = [dict(time_key='2026-11-26 10:00:00', open=10,high=12,low=9,close=11)]
        class Handler:
            def on_recv_rsp(self, pb):
                return 0, frame
        sdk = SimpleNamespace(CurKlineHandlerBase=Handler, RET_OK=0, OpenQuoteContext=Mock(), SysConfig=Mock())
        async def receive():
            queue = asyncio.Queue()
            with patch.dict(sys.modules, {'moomoo':sdk}), patch.object(main,'market_data',feed), patch.object(
                main,'loop',asyncio.get_running_loop()), patch('app.opend_market.connect_quote_context') as factory, patch.dict(
                main.listeners,{key:{queue}}):
                bridge.ensure()
                handler = factory.return_value.set_handler.call_args.args[0]
                handler.on_recv_rsp(SimpleNamespace(s2c=SimpleNamespace(rehabType=0)))
                self.assertEqual((await asyncio.wait_for(queue.get(),1))['type'],'error')
                with main.connect_db() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM bars').fetchone()[0],0)
                handler.on_recv_rsp(SimpleNamespace(s2c=SimpleNamespace(rehabType=1)))
                message = await asyncio.wait_for(queue.get(),1)
                self.assertEqual((message['type'],message['bar']['adjustment']),('bar','qfq'))
        asyncio.run(receive())

    def test_optional_stream_can_publish_and_release_a_subscription(self):
        key = tuple(self.query.values())
        seen, closed = [], []
        def subscribe(key, adjustment, emit):
            emit(self.provider.fetch_bars(key,1,None,adjustment))
            return lambda: closed.append(key)
        self.provider.live_adjustments = ('qfq',)
        self.provider.subscribe_bars = subscribe
        streams = ProviderStreams(self.feed, lambda key,rows: seen.append(rows), {}, 1)
        streams.subscribe(key)
        streams.subscribe(key)
        self.assertEqual(len(seen),1)
        self.assertIsNone(seen[0][0]['volume'])
        streams.close()
        self.assertEqual(closed,[key])
