import random
import unittest

from app.indicators import calculate
from app.scan_engine import evaluate, validate_plan


NAME = 'HAOYUNLAI_WAVE'


def rows(count=600):
    randomizer = random.Random(1)
    close = 100.
    bars = []
    for i in range(count):
        opening = close
        close = max(20., close + randomizer.gauss(0, 1.8))
        bars.append(dict(
            time=i, close_time=i+1, confirmed=True, volume=1000,
            symbol='SH.600519', period='120m', open=opening, close=close,
            high=max(opening, close)+randomizer.random(),
            low=min(opening, close)-randomizer.random(),
        ))
    return bars


def plan(period='120m', market='CN'):
    return dict(periods=[period], scope=dict(market=market), lookback=1, live=False,
                rules=[dict(left=dict(name=NAME, line='转强确认'),
                            right=dict(name='NUMBER', value=1), op='eq')])


class HaoyunlaiWaveTests(unittest.TestCase):
    def test_matches_research_and_only_removes_a_confirmed_wave_once(self):
        values = calculate(rows(), NAME)
        for key, expected in (
            ('抄底预警', [129, 174, 192, 238, 278, 300, 354, 374, 462, 535, 576]),
            ('转强确认', [281, 357, 465, 579]),
            ('破位移出', [287, 362, 481, 585]),
        ):
            self.assertEqual([i for i, v in enumerate(values[key]) if v == 1], expected)
        self.assertEqual(values['波段有效'][281:288], [1, 1, 1, 1, 1, 1, 0])
        self.assertEqual(values['波段有效'][288:357], [0]*69)

    def test_chart_and_confirmed_scan_use_the_same_signal(self):
        bars = rows(282)
        scan_plan = validate_plan(plan())
        self.assertTrue(evaluate({'120m': bars}, scan_plan, '120m')[-1]['match'])
        bars[-1]['confirmed'] = False
        self.assertFalse(evaluate({'120m': bars}, scan_plan, '120m')[-1]['match'])
        self.assertEqual(calculate(bars, NAME)['转强确认'][-1], 1)

    def test_restricts_markets_and_period(self):
        invalid = ({'symbol': 'US.AAPL'}, {'symbol': 'SZ.399001'},
                   {'symbol': 'SH.000001'})
        for override in invalid:
            result = calculate([{**x, **override} for x in rows(30)], NAME)
            self.assertTrue(all(v == [None]*30 for v in result.values()))
        for period in ('5m', '60m', '120m', '1d', '1w'):
            validate_plan(plan(period=period))
            self.assertEqual(calculate([{**x, 'period': period} for x in rows()], NAME), calculate(rows(), NAME))
        for wrong in (plan(market='US'),):
            with self.assertRaisesRegex(ValueError, '好运来'):
                validate_plan(wrong)
