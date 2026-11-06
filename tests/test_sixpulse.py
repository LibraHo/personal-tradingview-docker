import math
import unittest
from app.indicators import calculate
from app.sixpulse import ROWS, smooth


def rows(close):
    return [dict(time=i, open=x, high=x+1, low=x-1, close=x, volume=100) for i, x in enumerate(close)]


class SixPulseTests(unittest.TestCase):
    def test_recursive_sma_is_not_simple_ma_or_ema(self):
        self.assertEqual(smooth([None, 2, 4, 0], 2), [None, 2, 3, 1.5])
        self.assertNotEqual(smooth([2, 4, 0], 2), smooth([2, 4, 0], 2, True))

    def test_hand_computed_rsi_kdj_and_lwr(self):
        r = calculate(rows([10, 12, 11]), 'SIXPULSE', dict(kdjPeriod=2, lwrPeriod=2, rsiFast=2, rsiSlow=3))
        self.assertEqual(r['K'][:2], [None, 75])
        self.assertAlmostEqual(r['K'][2], 550/9)
        self.assertAlmostEqual(r['D'][2], 1900/27)
        self.assertAlmostEqual(r['LWR1'][2], -350/9)
        self.assertAlmostEqual(r['LWR2'][2], -800/27)
        self.assertEqual(r['RSI1'][1], 100)
        self.assertAlmostEqual(r['RSI1'][2], 200/3)
        self.assertAlmostEqual(r['RSI2'][2], 80)
        self.assertEqual(r['RSI'], [None, 0, 0])

    def test_bbi_waits_for_all_four_windows(self):
        r = calculate(rows(list(range(1, 31))), 'SIXPULSE')
        self.assertEqual(r['BBI'][:23], [None]*23)
        self.assertEqual(r['BBI_VALUE'][23], (23+21.5+18.5+12.5)/4)
        self.assertEqual(r['BBI'][23], 1)

    def test_flat_and_zero_denominators_are_unknown_not_bearish(self):
        data = [dict(open=10, high=10, low=10, close=10, volume=0)]*60
        r = calculate(data, 'SIXPULSE')
        for name in ('KDJ', 'RSI', 'LWR', 'MTM', 'SCORE'):
            self.assertEqual(r[name], [None]*60)
        self.assertEqual(r['MACD'], [0]*60)
        self.assertEqual(r['BBI'][-1], 0)

    def test_scores_match_comparisons_and_prefixes_do_not_repaint(self):
        data = rows([100+i*.04+5*math.sin(i/4) for i in range(300)])
        r = calculate(data, 'SIXPULSE')
        pairs = [('DIFF','DEA'),('K','D'),('RSI1','RSI2'),('LWR1','LWR2'),(None,'BBI_VALUE'),('MMS','MMM')]
        for i, bar in enumerate(data):
            for name, (left, right) in zip(ROWS, pairs):
                a, b = r[left][i] if left else bar['close'], r[right][i]
                self.assertEqual(r[name][i], None if a is None or b is None else int(a>b))
            signals = [r[name][i] for name in ROWS]
            self.assertEqual(r['SCORE'][i], None if None in signals else sum(signals))
        for size in (0, 1, 20, 150):
            prefix = calculate(data[:size], 'SIXPULSE')
            for name in r:self.assertEqual(prefix[name], r[name][:size])
        changed = [dict(b) for b in data];changed[-1]['close']+=5;changed[-1]['high']+=5
        live = calculate(changed, 'SIXPULSE')
        for name in r:self.assertEqual(live[name][:-1], r[name][:-1])
        self.assertNotEqual(live['DIFF'][-1], r['DIFF'][-1])

    def test_parameters_change_results_and_invalid_pairs_fail(self):
        data=rows([10,12,11,14,13]*10)
        self.assertNotEqual(calculate(data,'SIXPULSE')['RSI1'],calculate(data,'SIXPULSE',{'rsiFast':2})['RSI1'])
        for p in ({'fast':13},{'rsiFast':13},{'mtmFast':13},{'bbi1':0},{'smoothK':True},{'bbi4':'24'}):
            with self.assertRaises(ValueError):calculate(data,'SIXPULSE',p)


if __name__=='__main__':unittest.main()
