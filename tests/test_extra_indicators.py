import math
import unittest
from app.indicators import calculate
from app.extra_indicators import DEFAULTS


def bars(closes):
    return [dict(close=c, high=c+1, low=c-1, volume=i+1) for i, c in enumerate(closes)]


class ExtraIndicatorTests(unittest.TestCase):
    def setUp(self):
        self.rows = bars([10, 12, 11, 14, 13, 15])

    def test_weighted_averages(self):
        w = calculate(self.rows, 'WMA', {'period': 3})['main']
        self.assertEqual(w[:2], [None, None])
        self.assertAlmostEqual(w[2], 67/6)
        self.assertAlmostEqual(w[3], 76/6)
        self.assertAlmostEqual(calculate(self.rows, 'VWMA', {'period': 3})['main'][3], 113/9)

    def test_channel_and_oscillators(self):
        channel = calculate(self.rows, 'DC', {'period': 3})
        self.assertEqual([channel[k][2] for k in ('upper', 'mid', 'lower')], [13, 11, 9])
        self.assertEqual(calculate(self.rows, 'WR', {'period': 3})['main'][2], -50)
        stoch = calculate(self.rows, 'STOCH', {'period': 3, 'smoothK': 2, 'smoothD': 2})
        self.assertEqual(stoch['k'][:3], [None]*3)
        self.assertEqual(stoch['k'][3], 65)
        self.assertEqual(stoch['d'][4], 67.5)
        self.assertEqual(calculate(self.rows, 'CCI', {'period': 3})['main'][2], 0)
        self.assertAlmostEqual(calculate(self.rows, 'CCI', {'period': 3})['main'][3], 100)

    def test_volume_and_momentum(self):
        self.assertEqual(calculate(self.rows, 'OBV')['main'], [0, 2, -1, 3, -2, 4])
        flat = bars([10, 10, 9])
        self.assertEqual(calculate(flat, 'OBV')['main'], [0, 0, -3])
        self.assertEqual(calculate(self.rows, 'MOM', {'period': 3})['main'], [None]*3+[4, 1, 4])
        self.assertAlmostEqual(calculate(self.rows, 'ROC', {'period': 3})['main'][3], 40)
        rows = [dict(high=12, low=10, close=12, volume=1), dict(high=12, low=10, close=10, volume=3)]
        self.assertEqual(calculate(rows, 'CMF', {'period': 2})['main'], [None, -0.5])

    def test_degenerate_data_has_no_infinity(self):
        rows = [dict(high=0, low=0, close=0, volume=0)]*10
        for name in DEFAULTS:
            with self.subTest(name=name):
                values = calculate(rows, name, {'period': 3})
                for arr in values.values():
                    self.assertEqual(len(arr), 10)
                    self.assertTrue(all(x is None or math.isfinite(x) for x in arr))
                self.assertTrue(all(not arr for arr in calculate([], name).values()))
        for name in ('VWMA', 'CMF', 'WR', 'STOCH', 'ROC'):
            self.assertTrue(all(x is None for arr in calculate(rows, name, {'period': 3}).values() for x in arr))

    def test_decimal_flat_cci_has_no_spurious_signal(self):
        rows = [dict(high=100.1, low=100.1, close=100.1, volume=1)]*100
        self.assertEqual(calculate(rows, 'CCI')['main'], [None]*19+[0]*81)

    def test_validation_and_warmup(self):
        for name in DEFAULTS:
            for invalid in (0, -2, 1.5, 2001, True, '20', None, float('inf'), float('nan')):
                with self.subTest(name=name, invalid=invalid), self.assertRaises(ValueError):
                    calculate(self.rows, name, {'period': invalid})
        with self.assertRaises(ValueError):
            calculate(self.rows, 'STOCH', {'smoothK': 0})
        self.assertEqual(calculate(self.rows, 'DC')['upper'], [None]*6)

    def test_no_future_leak_and_current_bar_correction(self):
        rows = bars([100+i*.3+math.sin(i)*5 for i in range(80)])
        for name in DEFAULTS:
            with self.subTest(name=name):
                full = calculate(rows, name)
                prefix = calculate(rows[:60], name)
                self.assertEqual(prefix, {k: v[:60] for k, v in full.items()})
                corrected = rows[:-1]+[dict(rows[-1], close=rows[-1]['high'], volume=999)]
                after = calculate(corrected, name)
                self.assertEqual({k: v[:-1] for k, v in full.items()}, {k: v[:-1] for k, v in after.items()})


if __name__ == '__main__':
    unittest.main()
