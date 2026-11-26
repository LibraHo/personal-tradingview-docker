import unittest
from app.indicators import calculate


class MSIGM8Tests(unittest.TestCase):
    def signals(self, histogram, closes=None, valid=8, buffer=.0003):
        from app.msigm8 import signals_from_histogram
        bars = [dict(open=c, high=max(102, c), low=min(100, c), close=c, volume=1)
                for c in (closes or [101] * len(histogram))]
        return signals_from_histogram(bars, histogram, valid, buffer)

    def test_registered_main_indicator_and_flat_bars(self):
        bars = [dict(open=100, high=101, low=99, close=100, volume=1) for _ in range(15)]
        result = calculate(bars, 'MSIGM8')
        self.assertEqual(result['BUY_SIGNAL'], [0] * 15)
        self.assertEqual(result['SELL_SIGNAL'], [0] * 15)
        self.assertEqual(result['BUY'], [0] * 15)
        self.assertEqual(result['SELL_LEVEL'], [None] * 15)

    def test_buffer_and_first_trigger_only(self):
        v = self.signals([0, 2, 1, .8, .6, .4], [101, 101, 100.01, 99.98, 99.96, 99.9])
        self.assertEqual(v['SELL_TURN'], [0, 0, 1, 0, 0, 0])
        self.assertEqual(v['SELL_LEVEL'], [None, None, 100, 100, 100, 100])
        self.assertEqual(v['SELL'], [0, 0, 0, 0, 1, 1])
        self.assertEqual(v['SELL_SIGNAL'], [0, 0, 0, 0, 1, 0])
        self.assertEqual(v['SELL_START'][4], 1)
        self.assertEqual(v['SELL_MARKER'][4], 102 + (102 - 99.96) * .25)

    def test_turn_bar_bypasses_buffer_and_buy_is_symmetric(self):
        v = self.signals([0, 2, 1, .5], [101, 101, 99.99, 99.98])
        self.assertEqual(v['SELL_SIGNAL'], [0, 0, 1, 0])
        v = self.signals([0, -2, -1, -.5], [101, 101, 102.01, 102.02])
        self.assertEqual(v['BUY_SIGNAL'], [0, 0, 1, 0])
        self.assertEqual(v['BUY_START'][2], 1)
        self.assertEqual(v['BUY_LEVEL'][2], 102)

    def test_expiry_includes_turn_bar_and_raw_trigger_remains(self):
        v = self.signals([0, 2, 1, .8, .6, .4], [101, 101, 101, 101, 101, 99], valid=3)
        self.assertEqual(v['SELL_SIGNAL'], [0] * 6)
        self.assertEqual(v['SELL'][-1], 1)
        v = self.signals([0, 2, 1, .8, .6], [101, 101, 101, 101, 99], valid=3)
        self.assertEqual(v['SELL_SIGNAL'][-1], 1)

    def test_expansion_cancels_old_setup_new_turn_resets(self):
        v = self.signals([0, 2, 1, 2.5, 3, 2], [101, 101, 101, 99, 101, 99])
        self.assertEqual(v['SELL'][3], 1)
        self.assertEqual(v['SELL_SIGNAL'][3], 0)
        self.assertEqual(v['SELL_SIGNAL'][5], 1)
        self.assertEqual(v['SELL_START'][5], 4)

    def test_strict_turn_no_turn_on_plateau_and_zero_buffer(self):
        v = self.signals([0, 2, 2, 1], [101, 101, 99, 99], buffer=0)
        self.assertEqual(v['SELL_TURN'], [0] * 4)
        self.assertEqual(v['SELL_SIGNAL'], [0] * 4)

    def test_buy_sell_mirror_and_equal_price_does_not_break(self):
        from app.msigm8 import signals_from_histogram
        hist = [0, 2, 1, .8, .6, .4]
        bars = [dict(open=c, high=102, low=min(100, c), close=c) for c in [101, 101, 100, 99.98, 99.96, 99.9]]
        mirrored = [dict(open=200-b['open'], close=200-b['close'], high=200-b['low'], low=200-b['high']) for b in bars]
        sell = signals_from_histogram(bars, hist, 8, 0)
        buy = signals_from_histogram(mirrored, [-x for x in hist], 8, 0)
        self.assertEqual(sell['SELL_SIGNAL'], buy['BUY_SIGNAL'])
        self.assertEqual(sell['SELL'], buy['BUY'])
        self.assertEqual(sell['SELL'][2], 0)

    def test_against_vector_formula_reference(self):
        import math
        import random
        random.seed(813)
        bars = []
        for i in range(500):
            c = 100 + 5*math.sin(i/5) + random.uniform(-2, 2)
            bars.append(dict(open=c, high=c+.3, low=c-.3, close=c, volume=1))
        for settings in ({}, {'validBars':1, 'bufferRate':0}, {'validBars':12, 'bufferRate':.002}):
            actual = calculate(bars, 'MSIGM8', settings)
            hist = actual['MACDH']
            def barslast(flags):
                return [i-max((j for j in range(i+1) if flags[j]), default=-1000000) for i in range(len(flags))]
            def valuewhen(flags, values):
                return [next((values[j] for j in range(i, -1, -1) if flags[j]), None) for i in range(len(flags))]
            for side in ('SELL', 'BUY'):
                sell = side == 'SELL'
                turn = [i>=2 and (hist[i-2]<hist[i-1]>hist[i] if sell else hist[i-2]>hist[i-1]<hist[i]) for i in range(len(bars))]
                level = valuewhen(turn, [None]+[b['low' if sell else 'high'] for b in bars[:-1]])
                peak = valuewhen(turn, [None]+hist[:-1])
                age = barslast(turn)
                expand = [p is not None and (h>p if sell else h<p) for h,p in zip(hist,peak)]
                expand_age = barslast(expand)
                trigger = []
                for i, b in enumerate(bars):
                    c = b['close']; p = level[i]; buffer = c*settings.get('bufferRate', .0003)
                    trigger.append(p is not None and ((c<p-buffer if sell else c>p+buffer) or (turn[i] and (c<p if sell else c>p))))
                previous_age = barslast([False]+trigger[:-1])
                signal = [int(t and a+1<=settings.get('validBars',8) and a<ea and a<=pa) for t,a,ea,pa in zip(trigger,age,expand_age,previous_age)]
                self.assertEqual(actual[side], list(map(int, trigger)))
                self.assertEqual(actual[side+'_SIGNAL'], signal)
                self.assertGreater(sum(signal), 0)

    def test_validation_empty_and_prefix_stability(self):
        self.assertTrue(all(v == [] for v in calculate([], 'MSIGM8').values()))
        for p in ({'fast':26}, {'validBars':0}, {'validBars':1.5}, {'bufferRate':-1},
                  {'bufferRate':True}, {'bufferRate':float('nan')}, {'signal':None}):
            with self.subTest(p=p), self.assertRaises(ValueError):
                calculate([], 'MSIGM8', p)
        calculate([], 'MSIGM8', {'bufferRate':0})
        import math
        bars = [dict(open=100, high=105, low=95, close=100 + 4*math.sin(i/4), volume=1) for i in range(150)]
        whole = calculate(bars, 'MSIGM8')
        for n in (1, 2, 3, 40, 90):
            prefix = calculate(bars[:n], 'MSIGM8')
            for key in whole:
                self.assertEqual(prefix[key], whole[key][:n], key)


if __name__ == '__main__':
    unittest.main()
