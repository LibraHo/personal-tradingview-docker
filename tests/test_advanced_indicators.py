import math
import unittest
from app.indicators import calculate
from app.advanced_indicators import DEFAULTS, rma


def rows(close):
    return [dict(time=i, open=c-.25, high=c+1, low=c-1, close=c, volume=i+1) for i, c in enumerate(close)]


class AdvancedIndicatorTests(unittest.TestCase):
    def test_kdj_recurrence_and_seed(self):
        result = calculate(rows([10, 12, 11, 14]), 'KDJ', dict(period=3))
        self.assertEqual(result['k'], [None, None, 50, 60])
        self.assertAlmostEqual(result['d'][-1], 160/3)
        self.assertAlmostEqual(result['j'][-1], 220/3)

    def test_mfi_signed_money_flow(self):
        result = calculate(rows([10, 12, 11]), 'MFI', dict(period=2))['main']
        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[2], 100*24/57)
        self.assertEqual(calculate(rows([1, 2, 3]), 'MFI', dict(period=2))['main'][-1], 100)
        self.assertEqual(calculate(rows([3, 2, 1]), 'MFI', dict(period=2))['main'][-1], 0)

    def test_stochastic_rsi_uses_wilder_smoothing(self):
        result = calculate(rows([10, 12, 11, 14, 13]), 'STOCHRSI', dict(rsiPeriod=2, period=2, smoothK=1, smoothD=1))
        self.assertEqual(result['k'][:3], [None]*3)
        self.assertAlmostEqual(result['k'][3], 100)
        self.assertAlmostEqual(result['k'][4], 0)
        self.assertEqual(result['d'], result['k'])
        self.assertEqual(rma([None, 2, 4, 8], 2), [None, None, 3, 5.5])

    def test_supertrend_hand_computed_reversals(self):
        result = calculate(rows([10, 12, 11, 14, 13, 8, 7, 13]), 'SUPERTREND', dict(period=2, multiplier=1))
        self.assertEqual(result['direction'], [None, -1, -1, 1, 1, -1, -1, 1])
        self.assertEqual(result['main'], [None, 14.5, 13.25, 10.875, 10.875, 12.28125, 10.140625, 7.9296875])

    def test_sar_clamping_and_reversals(self):
        result = calculate(rows([10, 11, 12, 13, 14, 8, 7, 15]), 'SAR')['main']
        expected = [None, 9, 9, 9.16, 9.4504, 15, 15, 6]
        for x, y in zip(result, expected):
            if y is None: self.assertIsNone(x)
            else: self.assertAlmostEqual(x, y)

    def test_sar_tradingview_crossing_precedes_non_reversal_clamp(self):
        # TradingView public algorithm: project, test strict penetration, then
        # clamp only if no reversal. Other SAR variants reverse this order.
        data = [dict(high=10, low=8, close=9), dict(high=11, low=9, close=10),
                dict(high=11, low=8.01, close=10)]
        self.assertEqual(calculate(data, 'SAR')['main'], [None, 8, 11])

    def test_keltner_atr_and_ema_lengths_are_independent(self):
        result = calculate(rows([10, 12, 11]), 'KC', dict(period=2, atrPeriod=2, multiplier=2))
        self.assertIsNone(result['upper'][0])
        self.assertAlmostEqual(result['mid'][2], 100/9)
        self.assertAlmostEqual(result['upper'][2], 100/9+4.5)
        self.assertAlmostEqual(result['lower'][2], 100/9-4.5)

    def test_hull_against_direct_weighted_windows(self):
        def reference(v, n):
            return [None if i<n-1 or any(x is None for x in v[i-n+1:i+1]) else sum((j+1)*x for j, x in enumerate(v[i-n+1:i+1]))/(n*(n+1)/2) for i in range(len(v))]
        close = [100+math.sin(i)+i*.1 for i in range(100)]
        for n in (1, 2, 9, 21):
            a, b = reference(close, max(1, n//2)), reference(close, n)
            expected = reference([None if y is None else 2*x-y for x, y in zip(a, b)], max(1, int(math.sqrt(n)+.5)))
            actual = calculate(rows(close), 'HMA', dict(period=n))['main']
            for x, y in zip(actual, expected):
                if y is None: self.assertIsNone(x)
                else: self.assertAlmostEqual(x, y, places=8)

    def test_dema_tema_trix_and_ppo(self):
        data = rows([10, 12, 11])
        self.assertAlmostEqual(calculate(data, 'DEMA', dict(period=2))['main'][1], 106/9)
        self.assertAlmostEqual(calculate(data, 'TEMA', dict(period=2))['main'][1], 322/27)
        self.assertEqual(calculate(data, 'TRIX', dict(period=1, signal=1))['main'][:2], [None, 20])
        ppo = calculate(data, 'PPO', dict(fast=1, slow=2, signal=1))
        self.assertAlmostEqual(ppo['main'][1], 100/17)
        self.assertEqual(ppo['hist'], [0, 0, 0])

    def test_ao_and_bias(self):
        data = rows([10, 12, 11])
        self.assertEqual(calculate(data, 'AO', dict(fast=2, slow=3))['hist'], [None, None, .5])
        self.assertEqual(calculate(data, 'BIAS', dict(period=3))['main'], [None, None, 0])

    def test_adl_cho_pvt_bop(self):
        data = [dict(open=10, high=12, low=8, close=12, volume=10), dict(open=11, high=12, low=8, close=8, volume=20)]
        self.assertEqual(calculate(data, 'ADL')['main'], [10, -10])
        self.assertAlmostEqual(calculate(data, 'CHO', dict(fast=1, slow=2))['main'][1], -20/3)
        self.assertAlmostEqual(calculate(data, 'PVT')['main'][1], -20/3)
        self.assertEqual(calculate(data, 'BOP')['main'], [.5, -.75])

    def test_bollinger_derivatives(self):
        data = rows([1, 2, 3]); sd = math.sqrt(2/3)
        self.assertAlmostEqual(calculate(data, 'BBW', dict(period=3))['main'][2], 200*sd)
        self.assertAlmostEqual(calculate(data, 'BBP', dict(period=3))['main'][2], .5+1/(4*sd))
        flat = [dict(open=100.1, high=100.1, low=100.1, close=100.1, volume=0)]*100
        self.assertTrue(all(x is None for x in calculate(flat, 'BBP')['main']))

    def test_aroon_full_lookback_and_latest_tie(self):
        self.assertEqual(calculate(rows([1, 2, 3, 4]), 'AROON', dict(period=3)), dict(up=[None]*3+[100], down=[None]*3+[0]))
        self.assertEqual(calculate(rows([4]*4), 'AROON', dict(period=3)), dict(up=[None]*3+[100], down=[None]*3+[100]))

    def test_all_empty_single_flat_zero_volume_and_validation(self):
        for name, defaults in DEFAULTS.items():
            with self.subTest(name=name):
                for data in ([], rows([10]), rows([0]*100), [dict(open=100.1, close=100.1, high=100.1, low=100.1, volume=0)]*100):
                    for values in calculate(data, name).values():
                        self.assertEqual(len(values), len(data))
                        self.assertTrue(all(x is None or math.isfinite(x) for x in values))
                for key in defaults:
                    for invalid in (None, '3', True, -1, 0, 2001, math.inf, math.nan):
                        with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                            calculate([], name, {key: invalid})
        for name in ('PPO', 'AO', 'CHO'):
            with self.assertRaises(ValueError): calculate([], name, dict(fast=20, slow=10))
        with self.assertRaises(ValueError): calculate([], 'SAR', dict(start=.3, maximum=.2))

    def test_parameter_container_must_be_object(self):
        for value in ([], [1], 'bad', 20, True):
            with self.assertRaises(ValueError): calculate([], 'KDJ', value)

    def test_no_lookahead_and_partial_bar_corrections(self):
        data = rows([100+i*.1+5*math.sin(i/5) for i in range(150)])
        for name in DEFAULTS:
            with self.subTest(name=name):
                full = calculate(data, name)
                for length in (1, 2, 30, 75, 149):
                    self.assertEqual(calculate(data[:length], name), {k: v[:length] for k, v in full.items()})
                corrected = data[:-1]+[dict(data[-1], high=data[-1]['high']+5, close=data[-1]['high']+4, volume=999)]
                self.assertEqual({k: v[:-1] for k, v in calculate(corrected, name).items()}, {k: v[:-1] for k, v in full.items()})


if __name__ == '__main__': unittest.main()
