import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from app import main as market


class LongPeriodTests(unittest.TestCase):
    def test_supported_periods_and_session_rules(self):
        for period,kind in [('1w','K_WEEK'),('1mo','K_MON')]:
            self.assertEqual(market.PERIODS.get(period),kind)
            self.assertEqual(market.validate('US.SNDK',period,'regular'),('US.SNDK',period,'regular'))
            with self.assertRaises(ValueError):market.validate('US.SNDK',period,'all')

    def test_long_bars_survive_intraday_pruning(self):
        with tempfile.TemporaryDirectory() as root,patch.object(market,'DB',str(Path(root)/'test.sqlite3')):
            market.init_db();stamp=int((datetime.now(market.ET)-timedelta(days=400)).timestamp())
            row=dict(time=stamp,open=1,high=2,low=1,close=2,volume=10,turnover=15)
            for period in ('1w','1mo','5m'):market.save_bars(('US.SNDK',period,'regular'),[row])
            market.prune_cache()
            for period in ('1w','1mo'):
                bars=market.read_bars_before(('US.SNDK',period,'regular'),stamp+1,10)
                self.assertEqual(len(bars),1)
                self.assertEqual(bars[0]['session'],'regular')
            self.assertEqual(market.read_bars(('US.SNDK','5m','regular'),500,10),[])

    def test_history_windows_allow_monthly_indicator_warmup(self):
        self.assertGreaterEqual(market.default_history_days('1mo'),3650)
        self.assertGreaterEqual(market.default_history_days('1w'),1825)
        self.assertGreaterEqual(market.retention_days('1mo'),market.default_history_days('1mo'))

    def test_pushed_types_are_normalized(self):
        self.assertEqual(market.period_from_push('K_WEEK'),'1w')
        self.assertEqual(market.period_from_push('K_MON'),'1mo')
        self.assertEqual(market.period_from_push('K_15M'),'15m')
