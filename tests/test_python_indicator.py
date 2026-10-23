import unittest

from app.main import run_python_indicator
from app.python_indicator_worker import calculate, validate_code


def sample_bars():
    return [
        {'time': i, 'open': float(i), 'high': float(i + 1), 'low': float(i - 1),
         'close': float(i + 1), 'volume': 10.0, 'session': 'regular',
         'trade_date': '2026-10-23'}
        for i in range(1, 6)
    ]


class PythonIndicatorTests(unittest.TestCase):
    def test_multiline_multiseries_and_ema(self):
        code = 'fast = EMA(C, 2)\nslow = SMA(C, 3)\nresult = {"fast": fast, "slow": slow}'
        output = calculate(code, sample_bars())
        self.assertEqual(output['time'], [1, 2, 3, 4, 5])
        self.assertEqual(output['values']['slow'], [None, None, 3.0, 4.0, 5.0])
        self.assertEqual(len(output['values']['fast']), 5)

    def test_python_list_comprehension(self):
        output = calculate('result = [C[i] - O[i] for i in range(len(C))]', sample_bars())
        self.assertEqual(output['values']['main'], [1.0] * 5)

    def test_blocks_imports_and_attribute_access(self):
        for code in ('import os\nresult=C', 'result = C.__class__',
                     'result = open("/etc/passwd")', 'while True: pass'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_code(code)

    def test_worker_process_returns_matching_series(self):
        output = run_python_indicator('result = C - O', sample_bars())
        self.assertEqual(output['values']['main'], [1.0] * 5)


if __name__ == '__main__':
    unittest.main()
