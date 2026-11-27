"""Real HTTP transport over loopback. Fixtures use no vendor credentials."""
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app.alpaca_data import AlpacaData, ET, factory


def bar(clock, price, volume=30, day='2024-11-29'):
    return dict(t=f'{day}T{clock}:00-05:00', o=price, h=price+1, l=price-1,
                c=price+.5, v=volume, vw=price+.1)


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Stub(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path)
                params = {k:v[0] for k,v in parse_qs(path.query).items()}
                self.server.requests.append((path.path, params, self.headers.get('APCA-API-KEY-ID')))
                status, data = self.server.reply(path.path, params)
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.feed = AlpacaData('fixture-key', 'fixture-secret')
        self.feed.data_url = self.feed.reference_url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.server.requests = []
        self.server.reply = self.reply
        self.bar_pages = [([bar('09:00',99),bar('09:30',10),bar('10:00',12)], 'page-2'),
                          ([bar('12:30',20),bar('13:00',99)],None)]
        self.sessions = [{'date':'2024-11-29','open':'09:30','close':'13:00'}]

    def reply(self, path, params):
        if path == '/v2/calendar':
            return 200, self.sessions
        if path == '/v2/stocks/bars':
            rows, next_token = self.bar_pages[int(bool(params.get('page_token')))]
            return 200, {'bars':{'BRK.B':rows},'next_page_token':next_token}
        raise AssertionError(path)

    def test_regular_hour_uses_open_and_early_close_and_all_pages(self):
        bars = self.feed.fetch_bars(('US.BRK.B','60m','regular'),0,date(2024,11,29),'qfq')
        self.assertEqual([datetime.fromtimestamp(r['time'],ET).time() for r in bars], [time(9,30),time(12,30)])
        self.assertEqual([bars[0][k] for k in ('open','high','low','close','volume','turnover')],
                         [10,13,9,12.5,60,None])
        self.assertTrue(all(r[2]=='fixture-key' for r in self.server.requests))
        reqs = [p for path,p,_ in self.server.requests if path.endswith('bars')]
        self.assertEqual([r.get('page_token') for r in reqs],[None,'page-2'])
        self.assertEqual((reqs[0]['symbols'],reqs[0]['feed'],reqs[0]['adjustment'],reqs[0]['timeframe']),
                         ('BRK.B','iex','all','30Min'))

    def test_extended_resets_buckets_at_half_day_close_and_preserves_missing_volume(self):
        self.bar_pages = [([bar('09:00',5),bar('09:30',10),bar('10:00',20,None),bar('13:00',30)],None)]
        result = self.feed.fetch_bars(('US.BRK.B','120m','extended'),0,date(2024,11,29),'none')
        self.assertEqual([r['open'] for r in result],[5,10,30])
        self.assertIsNone(result[1]['volume'])
        self.assertEqual(datetime.fromtimestamp(result[2]['time'],ET).time(),time(13))
        self.assertEqual(self.server.requests[-1][1]['adjustment'],'raw')

    def test_long_periods_align_start_respect_cutoff_and_exclude_extended(self):
        for period, start, end, label in [('1d','2024-11-29','2024-11-29',29),
                                          ('1w','2024-11-25','2024-11-29',25),
                                          ('1mo','2024-11-01','2024-11-29',1)]:
            bars = self.feed.fetch_bars(('US.BRK.B',period,'regular'),0,date(2024,11,29),'none')
            self.assertEqual(len(bars),1)
            self.assertEqual((bars[0]['high'],bars[0]['close'],bars[0]['volume']),(21,20.5,90))
            self.assertEqual(datetime.fromtimestamp(bars[0]['time'],ET).date().day,label)
            request = self.server.requests[-1][1]
            self.assertEqual((request['start'][:10],request['end'][:10]),(start,end))

    def test_snapshot_batch_uses_latest_prior_session_in_premarket(self):
        self.server.reply = lambda path,params: (200,{'AAPL':{
            'latestTrade':{'p':120,'t':'2024-11-29T08:01:00-05:00'},
            'dailyBar':{'t':'2024-11-27T00:00:00-05:00','c':100},
            'prevDailyBar':{'t':'2024-11-26T00:00:00-05:00','c':80}},
            'BRK.B':{}})
        rows, stale = self.feed.snapshots(['US.AAPL','US.BRK.B'])
        self.assertFalse(stale)
        self.assertAlmostEqual(rows[0]['change_percent'],20)
        self.assertEqual(rows[0]['update_time'],'2024-11-29T08:01:00-05:00')
        self.assertIsNone(rows[1]['price'])
        self.assertEqual(self.server.requests[-1][1]['symbols'],'AAPL,BRK.B')

    def test_unsupported_requests_and_permissions_never_substitute_another_feed(self):
        for key,basis in [(('SH.600519','1d','regular'),'none'),(('US.AAPL','1d','regular'),'hfq'),
                          (('US.AAPL','5m','all'),'qfq')]:
            with self.assertRaises(ValueError):
                self.feed.fetch_bars(key,0,date(2024,11,29),basis)
        self.assertEqual(self.server.requests,[])
        for code,detail in [(403,'权限'),(429,'限额')]:
            self.server.reply = lambda path,params: (code,{'message':'sensitive vendor echo'})
            with self.assertRaisesRegex(ValueError,detail) as error:
                self.feed.snapshots(['US.AAPL'])
            self.assertNotIn('sensitive',str(error.exception))

    def test_overnight_daytime_are_disjoint_and_session_uses_next_trading_day(self):
        self.feed.overnight = True
        def reply(path, params):
            if path == '/v2/calendar':
                return 200,self.sessions
            rows = [bar('09:30',20), bar('20:00',80)] if params['feed']=='iex' else [
                bar('20:00',10,day='2024-11-28'),bar('02:00',15),bar('09:30',90),bar('20:00',80)]
            return 200,{'bars':{'BRK.B':rows},'next_page_token':None}
        self.server.reply=reply
        rows = self.feed.fetch_bars(('US.BRK.B','5m','all'),1,date(2024,11,29),'none')
        self.assertEqual([r['open'] for r in rows],[10,15,20])
        self.assertEqual([p['feed'] for path,p,_ in self.server.requests if path.endswith('bars')],['iex','boats'])

    def test_incomplete_fetch_raises_on_repeated_token(self):
        self.bar_pages=[([], 'again'),([], 'again')]
        with self.assertRaisesRegex(ValueError,'分页'):
            self.feed.fetch_bars(('US.BRK.B','1m','regular'),0,date(2024,11,29),'none')

    def test_scanner_calendar_maps_real_opening_and_early_close(self):
        with patch('app.alpaca_data.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2024,11,30,tzinfo=ET)
            self.sessions.append({'date':'2024-11-27','open':'09:30','close':'16:00'})
            self.assertEqual(self.feed.trading_days('US.BRK.B'),
                             {'2024-11-27':'WHOLE', '2024-11-29':'MORNING'})

    def test_directory_and_watchlist_use_read_only_reference_endpoints(self):
        ident='8324259f-fe62-41af-9be8-0420642197ad'
        fixtures={
            '/v2/assets':[{'symbol':'AAPL','name':'Apple Inc.'}],
            '/v2/watchlists':[{'id':ident,'name':'My list'}],
            '/v2/watchlists/'+ident:{'assets':[{'symbol':'AAPL','class':'us_equity'}, {'symbol':'BTC/USD','class':'crypto'}]}}
        self.server.reply=lambda path,params:(200,fixtures[path])
        self.assertEqual(self.feed.names(['US.AAPL']),{'US.AAPL':'Apple Inc.'})
        self.assertEqual(self.feed.search_symbols('apple',5,'US')['results'][0]['symbol'],'US.AAPL')
        from fastapi.testclient import TestClient
        from app import main
        from app.market_data import DisabledFeed, MarketRoutes
        routes = MarketRoutes('disabled', 'none', {'CN': {'limit_pool':'disabled'}, 'US': {'watchlists': 'alpaca'}},
                              {'opend': main.bridge, 'disabled': DisabledFeed(), 'alpaca': self.feed}, main.save_bars)
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, 'DB', str(Path(tmp) / 'watch.sqlite3')), patch.object(main, 'market_data', routes):
            main.init_db()
            client = TestClient(main.app)
            try:
                response = client.post('/api/watchlists/import', params={'market':'US'})
            finally:
                client.close()
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result['providers'],['alpaca_iex'])
            self.assertEqual(result['value']['markets']['US']['groups'][-1]['symbols'],['US.AAPL'])
        self.assertEqual([p for p,_,_ in self.server.requests],list(fixtures))

    def test_factory_reads_explicit_settings_and_names_cache_by_entitled_feed(self):
        with patch.dict('os.environ',{'APCA_API_KEY_ID':'fixture','APCA_API_SECRET_KEY':'fixture',
                                      'ALPACA_DATA_FEED':'sip','ALPACA_OVERNIGHT':'true','ALPACA_ACCOUNT_ENV':'live'}):
            adapter=factory()
        self.assertEqual(adapter.source_id,'alpaca_sip_boats')
        self.assertEqual(adapter.reference_url,'https://api.alpaca.markets')
        self.assertFalse(adapter.live_adjustments)
