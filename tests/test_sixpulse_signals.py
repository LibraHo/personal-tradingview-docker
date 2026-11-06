import unittest
from app.sixpulse import ROWS, signal_values, signal_settings
from app.indicators import calculate


def votes(red_counts):
    return {name:[None if n is None else int(j<n) for n in red_counts] for j,name in enumerate(ROWS)}


class SixPulseSignalTests(unittest.TestCase):
    def test_hysteresis_alternates_without_repeating(self):
        v=signal_values(votes([4,5,6,4,3,2,5,5]),{'confirm':'live'})
        self.assertEqual(v['ENTRY'],[0,1,0,0,0,0,1,0])
        self.assertEqual(v['EXIT'],[0,0,0,0,1,0,0,0])
        self.assertEqual(v['STATE'],[0,1,1,1,0,0,1,1])

    def test_next_bar_confirmation_uses_no_future_prices(self):
        v=signal_values(votes([4,5]),{})
        self.assertEqual(v['ENTRY'],[0,None])
        for future in (0,6,None):
            more=signal_values(votes([4,5,future]),{})
            self.assertEqual(more['ENTRY'],[0,1,None])
            self.assertEqual(more['EXIT'],[0,0,None])

    def test_rsi_can_be_excluded_even_when_missing(self):
        rows=votes([6,6,0]);rows['RSI']=[None,None,None]
        enabled=[name for name in ROWS if name!='RSI']
        actual=signal_values(rows,{'enabled':enabled,'confirm':'live'})
        self.assertEqual(actual['REDS'],[5,5,0])
        self.assertEqual(actual['ENTRY'],[1,0,0])
        self.assertEqual(actual['EXIT'],[0,0,1])
        self.assertEqual(signal_values(rows,{'confirm':'live'})['ENTRY'],[None,None,None])

    def test_thresholds_are_configurable_and_missing_is_not_exit(self):
        v=signal_values(votes([3,4,None,5,2,6]),{'enterReds':4,'exitGreens':4,'confirm':'live'})
        self.assertEqual(v['ENTRY'],[0,1,None,0,0,1])
        self.assertEqual(v['EXIT'],[0,0,None,0,1,0])

    def test_invalid_or_conflicting_inputs_rejected(self):
        for cfg in ({'enabled':[]},{'enabled':['RSI','RSI']},{'enabled':['UNKNOWN']},{'enabled':None},
                    {'enterReds':0},{'enterReds':7},{'enterReds':3,'exitGreens':3},
                    {'enterReds':None},{'exitGreens':True},{'confirm':None},{'confirm':['live']}):
            with self.subTest(cfg=cfg),self.assertRaises(ValueError):signal_settings(cfg)

    def test_main_and_pane_parameters_are_independent(self):
        bars=[dict(open=10,high=20,low=5,close=10+i%7,volume=1) for i in range(40)]
        pane=calculate(bars,'SIXPULSE',{'fast':8})
        main=calculate(bars,'SIXPULSE_SIGNAL',{'fast':7,'enabled':['MACD'],'enterReds':1,'exitGreens':1})
        self.assertNotEqual(pane['DIFF'],main['DIFF'])
        self.assertEqual(main['SCORE'],main['MACD'])
        self.assertIsNone(main['ENTRY'][-1])
        self.assertEqual(pane,calculate(bars,'SIXPULSE',{'fast':8}))


if __name__=='__main__':unittest.main()
