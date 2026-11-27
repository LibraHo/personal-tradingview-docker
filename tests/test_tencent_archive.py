import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from app.tencent_archive import CN, TencentArchive, factory


class TencentArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.feed = TencentArchive(self.directory)
        self.row = ['2026-11-16', '10.45', '10.78', '10.78', '10.39', '964157']

    def save(self, name='sh600000', **data):
        (self.directory / (name + '.json')).write_text(json.dumps(data), encoding='utf-8')

    def fetch(self, symbol='SH.600000', days=1):
        return self.feed.fetch_bars((symbol,'1d','regular'), days, date(2026,11,16), 'none')

    def test_overlapping_raw_pages_and_source_price_order(self):
        earlier = ['2026-11-13', *self.row[1:]]
        self.save(raw=[[earlier, self.row], [self.row]], qfq=[['unused']])
        result = self.fetch()
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual([row[k] for k in ('open','high','low','close','volume','turnover')],
                         [10.45, 10.78, 10.39, 10.78, 96415700, None])
        self.assertEqual(datetime.fromtimestamp(row['time'],CN).isoformat(),'2026-11-16T00:00:00+08:00')
        self.assertEqual(self.feed.history_status('SH.600000')['archive_as_of'], '2026-11-16')
        self.assertTrue(self.feed.history_status('SH.600000')['stale'])

    def test_star_board_volume_is_shares_and_missing_volume_remains_null(self):
        self.save('sh688006',raw=[[self.row]])
        self.assertEqual(self.fetch('SH.688006')[0]['volume'],964157)
        self.save('sz000001',raw=[[[*self.row[:5],None]]])
        self.assertIsNone(self.fetch('SZ.000001')[0]['volume'])

    def test_rejects_bad_overlap_and_adjusted_only_files(self):
        self.save(raw=[[self.row], [[*self.row[:5], '531']]])
        with self.assertRaisesRegex(ValueError, '重叠'):
            self.fetch()
        self.save(qfq=[[self.row]])
        with self.assertRaisesRegex(ValueError, '不复权'):
            self.fetch()
        self.assertIsNone(self.feed.history_status('SH.600000')['archive_as_of'])

    def test_rejects_non_archive_instruments_and_modes(self):
        for key,basis in [(('SH.000001','1d','regular'),'none'),
                          (('US.AAPL','1d','regular'),'none'),
                          (('SH.600000','1d','regular'),'qfq'),
                          (('SH.600000','1w','regular'),'none'),
                          (('SH.600000','1d','extended'),'none')]:
            with self.assertRaises(ValueError):
                self.feed.fetch_bars(key,1,date(2026,11,16),basis)
        with self.assertRaisesRegex(ValueError, '没有'):
            self.fetch()

    def test_factory_loads_configured_directory(self):
        with patch.dict('os.environ',{'TENCENT_ARCHIVE_DIR':str(self.directory)}):
            self.assertEqual(factory().directory,self.directory)

    def test_chart_displays_archive_date_and_retains_cache_when_file_is_unavailable(self):
        from fastapi.testclient import TestClient
        from app import main
        from app.market_data import MarketData
        day = datetime.now(CN).date().isoformat()
        self.save(raw=[[[day, *self.row[1:]]]])
        feed = MarketData(self.feed, 'none', main.save_bars)
        params = {'symbol':'SH.600000', 'period':'1d', 'mode':'regular', 'days':10}
        with patch.object(main,'DB',str(self.directory/'test.sqlite3')), patch.object(main,'market_data',feed):
            main.init_db()
            client = TestClient(main.app)
            self.addCleanup(client.close)
            response = client.get('/api/bars', params={**params,'refresh':True})
            self.assertEqual(response.status_code,200,response.text)
            result = response.json()
            self.assertEqual((result['archive_as_of'],result['stale'],result['provider']), (day,True,'tencent_archive'))
            self.assertEqual(result['bars'][-1]['volume'],96415700)
            (self.directory/'sh600000.json').unlink()
            cached = client.get('/api/bars', params={**params,'prefer_cache':True}).json()
            self.assertTrue(cached['stale'])
            self.assertIsNone(cached['archive_as_of'])
            self.assertIn('没有',cached['history_notice'])
            self.assertEqual(cached['bars'][-1]['close'],10.78)
