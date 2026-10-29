import unittest
from app.indicators import calculate


def bar(i, close, volume=1, session='regular', date='2026-10-22'):
    return {'time': i, 'open': close, 'high': close + 1, 'low': close - 1,
            'close': close, 'volume': volume, 'trade_date': date,
            'session_date': date + ':' + session}


class IndicatorTests(unittest.TestCase):
    def test_multiple_ma_and_ema_periods(self):
        rows = [bar(i, i+1) for i in range(30)]
        self.assertEqual(list(calculate(rows, 'EMA', {'periods':[5,10,20]})), ['EMA5','EMA10','EMA20'])
        self.assertEqual(list(calculate(rows, 'EMA', {})), ['EMA5','EMA10','EMA20'])
        self.assertEqual(calculate(rows, 'SMA', {'periods':[5,10,20]})['MA5'][4], 3)
        with self.assertRaises(ValueError):
            calculate(rows, 'EMA', {'periods':[0,10]})

    def test_vwap_resets_at_session_boundary(self):
        rows = [bar(1, 10), bar(2, 20), bar(3, 30, session='post')]
        self.assertEqual(calculate(rows, 'VWAP')['main'], [10, 15, 30])
        self.assertEqual(calculate(rows, 'VWAP', reset='never')['main'], [10, 15, 20])

    def test_macd_and_atr_lengths(self):
        rows = [bar(i, 100 + i) for i in range(40)]
        self.assertEqual(len(calculate(rows, 'MACD')['hist']), 40)
        self.assertEqual(len(calculate(rows, 'ATR')['stop_long']), 40)
        self.assertTrue(all(x >= 0 for x in calculate(rows, 'ATR')['main']))

    def test_sma_window_and_bbi(self):
        rows = [bar(i, i + 1) for i in range(5)]
        self.assertEqual(calculate(rows, 'SMA', {'period': 3})['main'], [None, None, 2, 3, 4])
        self.assertEqual(calculate(rows, 'BBI', {'periods': [2, 3]})['main'][-1], 4.25)


if __name__ == '__main__':
    unittest.main()
