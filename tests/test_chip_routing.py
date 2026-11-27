import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import main
from app.market_data import DisabledFeed, MarketRoutes, normalize_bar
from app.scan_engine import evaluate
from tests.test_market_data import PriceFeed


KEY = ('US.TEST', '5m', 'all')


def histogram(key, basis, stamp):
    return dict(symbol=key[0], period=key[1], mode=key[2], adjustment=basis, time=stamp,
                levels=[[110, 10], [95, 34], [80, 51], [100, 5]])


class ChipHistory(PriceFeed):
    historical_chips = True
    source_id = 'chip_history'

    def fetch_bars(self, key, days, end_date, adjustment):
        bars = super().fetch_bars(key, days, end_date, adjustment)
        for i, bar in enumerate(bars):
            price = 110 if i == len(bars)-1 else 100
            bar.update(open=price, high=price, low=price, close=price,
                       chip_distribution=histogram(key, adjustment, bar['time']))
        return bars


class Summary:
    source_id = 'summary_only'

    def chip_summary(self, market, offset, limit):
        return {'total':2, 'rows':[{'symbol':'US.TEST','profit_ratio':0,'interval_overlap':None}]}


class ChipRoutingTests(unittest.TestCase):
    def test_histogram_requires_matching_series_and_valid_shares(self):
        stamp = 1800000000
        raw = dict(time=stamp,open=100,high=100,low=100,close=100)
        points = histogram(KEY, 'none', stamp)
        row = {**raw, 'chip_distribution':points}
        self.assertEqual(normalize_bar(row,KEY,'none')['fields'], {'chip_winner_95':0.51,'chip_cost_85':95})
        for bad in [dict(mode='regular'), dict(period='1d'), dict(symbol='US.OTHER'),
                    dict(adjustment='qfq'), dict(time=stamp-300), dict(levels=[]),
                    dict(levels=[[80,1],[95,-1]]), dict(levels=[[80,0]])]:
            r = normalize_bar({**row, 'chip_distribution':{**points,**bad}}, KEY,'none')
            self.assertEqual(r['fields'],{})
            self.assertEqual(r['close'],100)
        empty = normalize_bar({**raw,'fields':{'chip_winner_95':1.4,'chip_cost_85':0}}, KEY,'none')
        self.assertEqual(empty['fields'],{'chip_winner_95':None,'chip_cost_85':None})

    def test_http_and_scanner_use_historical_inputs_separately_from_snapshot_route(self):
        pts, summary = ChipHistory(), Summary()
        feeds = {'opend':main.bridge,'disabled':DisabledFeed(),'eastmoney':DisabledFeed(),
                 'prices':pts, 'summary':summary}
        router = MarketRoutes('disabled','none',{'US':{'history':'prices','chip_summary':'summary'}},feeds,main.save_bars)
        with tempfile.TemporaryDirectory() as directory, patch.object(main,'DB',str(Path(directory)/'test.db')), patch.object(main,'market_data',router), patch.object(main,'last_fetch',{}), patch.object(main,'history_failures',{}):
            main.init_db()
            client = TestClient(main.app)
            self.addCleanup(client.close)
            query = dict(zip(('symbol','period','mode'), KEY))
            meta = client.get('/api/status?market=US').json()
            self.assertEqual(meta['routes']['US']['chip_summary'],'summary_only')
            self.assertTrue(meta['capabilities']['chip_summary'] and meta['historical_chips'])
            self.assertFalse(client.get('/api/status?market=CN').json()['historical_chips'])
            page = client.get('/api/chips/summary?market=US&limit=1').json()
            self.assertEqual((page['kind'],page['rows'][0]['profit_ratio'],page['rows'][0]['interval_overlap']),('snapshot',0,None))
            self.assertEqual(client.get('/api/chips/summary?market=CN').status_code,422)
            self.assertEqual(client.get('/api/chips/summary?market=US&offset=-1').status_code,400)
            bars = client.get('/api/bars',params=query).json()['bars']
            values = client.get('/api/indicators',params={**query,'name':'INSTITUTION_TREND'}).json()['values']
            self.assertAlmostEqual(values['机构高度控盘'][-1], 4)
            plan = {'periods':['5m'],'live':False,'rules':[{'left':{'name':'INSTITUTION_TREND','line':'机构高度控盘'},
                    'op':'gt','right':{'name':'NUMBER','value':3}}]}
            results = evaluate({'5m':[{**r,'confirmed':True,'close_time':r['time']+300} for r in bars]},plan,'5m')
            self.assertTrue(results[-1]['match'])
            incomplete = MarketRoutes('disabled','none',{'US':{'history':'ordinary','chip_summary':'summary'}},
                                      {**feeds,'ordinary':PriceFeed()},main.save_bars)
            with patch.object(main,'market_data',incomplete):
                response = client.get('/api/indicators',params={**query,'name':'INSTITUTION_TREND'})
                self.assertEqual(response.status_code,400)
                self.assertIn('逐根历史',response.json()['detail'])
