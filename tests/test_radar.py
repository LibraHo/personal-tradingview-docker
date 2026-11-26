import sqlite3
import sys
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from app.radar import BOARD, Radar, distribution_summary


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.bridge = SimpleNamespace(lock=threading.RLock())
        self.radar = Radar(self.bridge, self.connection)

    def tearDown(self):
        self.db.close()

    @contextmanager
    def connection(self):
        with self.db:
            yield self.db

    def test_limit_board_deduplicates_pools_and_keeps_same_day_snapshot(self):
        from app.market_analytics import Analytics
        from datetime import date, timedelta
        prior=(date.today()-timedelta(days=2)).isoformat()
        days={prior:'WHOLE'}
        analytics=Analytics(SimpleNamespace(radar=self.radar,calendar=SimpleNamespace(days=lambda symbol:days)))
        sealed={'symbol':'SH.600000','reopen_count':1,'streak':2}
        broken={'symbol':'SZ.000001','reopen_count':2}
        with patch('app.market_analytics.pool',side_effect=[{'rows':[sealed]},{'rows':[sealed,broken]}]) as fetch:
            first=analytics.limit_board()
            self.assertEqual(first['trade_date'],prior)
            self.assertEqual(first['sealed'],[sealed])
            self.assertEqual(first['broken'],[broken])
            self.assertEqual(analytics.limit_board(prior)['sealed'],[sealed])
            self.assertEqual(fetch.call_count,2)
        with patch('app.radar.time.time',return_value=first['updated']+180),patch('app.market_analytics.pool',side_effect=OSError('offline')):
            cached=analytics.limit_board(prior)
            self.assertTrue(cached['stale'])
            self.assertEqual(cached['broken'],[broken])
        with self.assertRaises(ValueError):
            analytics.limit_board('2100-01-01')

    def test_distribution_keeps_limits_out_of_range_totals(self):
        data = {'plate': 'SH.LIST3000005', 'range_list': [
            {'type': 'NORMAL_RANGE', 'left_border': -3, 'right_border': 0, 'stock_count': 9},
            {'type': 'NORMAL_RANGE', 'left_border': 0, 'right_border': 0, 'stock_count': 2},
            {'type': 'NORMAL_RANGE', 'left_border': 0, 'right_border': 3, 'stock_count': 6},
            {'type': 'POSITIVE_INFINITY', 'left_border': 7, 'right_border': 0, 'stock_count': 3},
            {'type': 'RISE_LIMIT', 'stock_count': 2},
            {'type': 'FALL_LIMIT', 'stock_count': 1},
        ]}
        result = distribution_summary(data)
        self.assertEqual((result['up'], result['down'], result['flat']), (9, 9, 2))
        self.assertEqual(result['total'], 20)
        self.assertEqual(result['up_ratio'], 45)
        self.assertEqual(result['limit_up'], 2)

    def test_missing_and_cross_zero_intervals(self):
        with self.assertRaises(ValueError):
            distribution_summary({'range_list': []})
        result = distribution_summary({'range_list': [
            {'type': 'NORMAL_RANGE', 'left_border': -1, 'right_border': 1, 'stock_count': 3},
            {'type': 'NORMAL_RANGE', 'left_border': 1, 'right_border': 2, 'stock_count': float('nan')},
        ]})
        self.assertEqual(result['unclassified'], 3)
        self.assertIsNone(result['up_ratio'])
        self.assertIsNone(result['limit_up'])

    def test_cache_age_and_upstream_failure(self):
        with patch('app.radar.time.time', return_value=100):
            first = self.radar.cached('x', 60, lambda: {'rows': [1]})
        def failure():
            raise ValueError('offline')
        with patch('app.radar.time.time', return_value=120):
            self.assertFalse(self.radar.cached('x', 60, failure)['stale'])
        with patch('app.radar.time.time', return_value=200):
            stale = self.radar.cached('x', 60, failure)
        self.assertTrue(stale['stale'])
        self.assertEqual(stale['updated'], first['updated'])
        self.assertEqual(stale['rows'], [1])

    def test_catalog_and_members_deduplicate_and_validate(self):
        frame = SimpleNamespace(to_dict=lambda _: [
            {'code': 'SH.BK0001', 'plate_name': '行业'},
            {'code': 'SH.BK0001', 'plate_name': '行业'},
            {'code': '../bad', 'plate_name': 'bad'},
        ])
        sdk = SimpleNamespace(Plate=SimpleNamespace(INDUSTRY=1, CONCEPT=2, OTHER=3), Market=SimpleNamespace(SH='SH', US='US'))
        with patch.dict(sys.modules, {'moomoo': sdk}), patch.object(self.radar, 'call', return_value=(frame,)) as call:
            result = self.radar.catalog('CN', 'industry')
            self.assertEqual(len(result['rows']), 1)
            call.assert_called_once_with('get_plate_list', market='SH', plate_class=1)
        with self.assertRaises(ValueError):
            self.radar.members('US.AAPL')
        self.assertTrue(BOARD.fullmatch('US.LIST20077'))
        self.assertEqual(len(self.radar.catalog('US', 'etf')['rows']), 11)

    def test_heatmap_keeps_pagination_and_missing_values(self):
        sdk = SimpleNamespace(HeatMapPlateType=SimpleNamespace(INDUSTRY=1), Market=SimpleNamespace(SH='SH', US='US'))
        frame = SimpleNamespace(to_dict=lambda _: [{'plate': 'US.LIST2496', 'change_rate': float('nan'), 'plate_name': 'Test'}])
        with patch.dict(sys.modules, {'moomoo': sdk}), patch.object(self.radar, 'call', return_value=(frame, 'next', 101)):
            result = self.radar.heatmap('US', 'industry', '')
        self.assertEqual(result['next_page'], 'next')
        self.assertEqual(result['total'], 101)
        self.assertIsNone(result['rows'][0]['change'])

    def test_cn_emotion_requests_both_shanghai_and_shenzhen(self):
        data = {'range_list': [{'type': 'NORMAL_RANGE', 'left_border': 0, 'right_border': 0, 'stock_count': 2}]}
        with patch.object(self.radar, 'call', return_value=(data,)) as call, patch.object(self.radar,'market',return_value='SH'):
            self.radar.emotion('CN')
        call.assert_called_once_with('get_rise_fall_distribution', market='SH')


if __name__ == '__main__':
    unittest.main()
