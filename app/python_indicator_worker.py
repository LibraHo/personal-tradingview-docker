"""Restricted, short-lived Python worker for user-authored chart indicators."""
from __future__ import annotations

import ast
import json
import math
import re
import statistics
import sys

MAX_CODE = 4000
MAX_NODES = 500
MAX_LINES = 8
MAX_INPUTS = 20
SAFE_MODULES = {
    'math': {'sqrt', 'log', 'log10', 'exp', 'floor', 'ceil', 'fabs', 'isfinite', 'sin', 'cos', 'tan'},
    'statistics': {'mean', 'fmean', 'median', 'pstdev', 'stdev'},
}
SAFE_CALLS = {'abs', 'min', 'max', 'sum', 'len', 'range', 'enumerate',
              'zip', 'round', 'float', 'int', 'list', 'SMA', 'EMA', 'REF',
              'HHV', 'LLV'}
ALLOWED = {
    ast.Module, ast.Assign, ast.AugAssign, ast.Expr, ast.For, ast.If,
    ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Pass, ast.Break,
    ast.Continue, ast.Name, ast.Load, ast.Store, ast.Constant, ast.BinOp,
    ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call, ast.keyword, ast.Subscript,
    ast.Slice, ast.List, ast.Tuple, ast.Dict, ast.ListComp, ast.comprehension,
    ast.IfExp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Pow, ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
    ast.Import, ast.ImportFrom, ast.alias, ast.Attribute,
}


def validate_code(source: str):
    if not source.strip() or len(source) > MAX_CODE:
        raise ValueError('Python 指标代码须为 1–4000 个字符')
    tree = ast.parse(source, mode='exec')
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ValueError('Python 指标代码过于复杂')
    module_aliases = {}
    imported_calls = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in SAFE_MODULES:
                    raise ValueError('只能导入 math 或 statistics')
                module_aliases[alias.asname or alias.name] = alias.name
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in SAFE_MODULES:
                raise ValueError('只能从 math 或 statistics 导入函数')
            for alias in node.names:
                if alias.name not in SAFE_MODULES[node.module]:
                    raise ValueError(f'不支持导入的函数：{alias.name}')
                imported_calls.add(alias.asname or alias.name)
    callable_names = SAFE_CALLS | imported_calls | {node.name for node in nodes if isinstance(node, ast.FunctionDef)}
    call_attributes = {id(node.func) for node in nodes if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for node in nodes:
        if type(node) not in ALLOWED:
            raise ValueError(f'不支持的 Python 语法：{type(node).__name__}')
        if isinstance(node, ast.Name) and node.id.startswith('_'):
            raise ValueError('变量名不能以下划线开头')
        if isinstance(node, ast.alias) and node.asname and node.asname.startswith('_'):
            raise ValueError('导入别名不能以下划线开头')
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith('_'):
                raise ValueError('函数名不能以下划线开头')
            if node.decorator_list or node.returns or getattr(node, 'type_params', []):
                raise ValueError('不支持函数装饰器或类型注解')
        if isinstance(node, ast.arg) and (node.arg.startswith('_') or node.annotation):
            raise ValueError('参数名不能以下划线开头，也不能使用类型注解')
        if isinstance(node, ast.Attribute):
            if id(node) not in call_attributes or not isinstance(node.value, ast.Name) or node.attr not in SAFE_MODULES.get(module_aliases.get(node.value.id, ''), set()):
                raise ValueError('只能调用 math 或 statistics 中允许的函数')
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in callable_names:
                continue
            if isinstance(node.func, ast.Attribute):
                continue
            raise ValueError('只能调用内置计算函数或自己定义的函数')
    return tree


def validate_inputs(inputs):
    if not isinstance(inputs, dict) or len(inputs) > MAX_INPUTS:
        raise ValueError('参数须为不超过 20 项的 JSON 对象')
    for name, value in inputs.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', name):
            raise ValueError('参数名须以字母开头，只能使用字母、数字和下划线')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1_000_000:
            raise ValueError(f'参数 {name} 须为有限数字，绝对值不超过 100 万')
    return inputs


class Series:
    def __init__(self, values):
        self.values = list(values)

    def __len__(self):
        return len(self.values)

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, index):
        value = self.values[index]
        return Series(value) if isinstance(index, slice) else value

    def _operation(self, other, fn, reverse=False):
        right = other.values if isinstance(other, Series) else [other] * len(self)
        if len(right) != len(self):
            raise ValueError('序列长度不一致')
        out = []
        for left, value in zip(self.values, right):
            try:
                out.append(None if left is None or value is None else fn(value, left) if reverse else fn(left, value))
            except (ArithmeticError, ValueError, OverflowError):
                out.append(None)
        return Series(out)

    def __add__(self, other): return self._operation(other, lambda a, b: a + b)
    def __radd__(self, other): return self.__add__(other)
    def __sub__(self, other): return self._operation(other, lambda a, b: a - b)
    def __rsub__(self, other): return self._operation(other, lambda a, b: a - b, True)
    def __mul__(self, other): return self._operation(other, lambda a, b: a * b)
    def __rmul__(self, other): return self.__mul__(other)
    def __truediv__(self, other): return self._operation(other, lambda a, b: a / b)
    def __rtruediv__(self, other): return self._operation(other, lambda a, b: a / b, True)
    def __neg__(self): return Series(None if x is None else -x for x in self)


def series(value):
    return value if isinstance(value, Series) else Series(value)


def window(values, period, operation):
    values = series(values)
    period = int(period)
    if period < 1 or period > 500:
        raise ValueError('周期须为 1–500')
    out = []
    for index in range(len(values)):
        sample = values.values[max(0, index - period + 1):index + 1]
        out.append(operation(sample) if len(sample) == period and all(x is not None for x in sample) else None)
    return Series(out)


def sma(values, period): return window(values, period, lambda sample: sum(sample) / len(sample))
def hhv(values, period): return window(values, period, max)
def llv(values, period): return window(values, period, min)


def ema(values, period):
    values = series(values)
    period = int(period)
    if period < 1 or period > 500:
        raise ValueError('周期须为 1–500')
    previous = None
    out = []
    for value in values:
        previous = previous if value is None else value if previous is None else previous + (value - previous) * 2 / (period + 1)
        out.append(previous if value is not None else None)
    return Series(out)


def ref(values, period):
    values = series(values)
    period = int(period)
    if period < 1 or period > 500:
        raise ValueError('周期须为 1–500')
    return Series([None] * period + values.values[:-period])


def normalize(value, length):
    values = value.values if isinstance(value, Series) else value
    if not isinstance(values, (list, tuple)) or len(values) != length:
        raise ValueError(f'每条输出序列必须与 K 线长度一致（{length}）')
    result = []
    for item in values:
        if item is None:
            result.append(None)
            continue
        if isinstance(item, bool):
            item = int(item)
        if not isinstance(item, (int, float)):
            raise ValueError('指标输出只能是数字或 None')
        number = float(item)
        result.append(number if math.isfinite(number) else None)
    return result


def calculate(source, bars, inputs=None):
    tree = validate_code(source)
    inputs = validate_inputs(inputs if inputs is not None else {})
    if not bars or len(bars) > 5000:
        raise ValueError('请先加载 1–5000 根 K 线')
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in SAFE_MODULES:
            raise ImportError('只能导入 math 或 statistics')
        return {'math': math, 'statistics': statistics}[name]
    namespace = {'__builtins__': {'__import__': safe_import}, 'abs': abs, 'min': min, 'max': max,
                 'sum': sum, 'len': len, 'range': range, 'enumerate': enumerate,
                 'zip': zip, 'round': round, 'float': float, 'int': int,
                 'list': list, 'SMA': sma, 'EMA': ema, 'REF': ref,
                 'HHV': hhv, 'LLV': llv}
    for symbol, field in [('O', 'open'), ('H', 'high'), ('L', 'low'), ('C', 'close'), ('V', 'volume')]:
        namespace[symbol] = Series(bar[field] for bar in bars)
    namespace['TIME'] = tuple(bar['time'] for bar in bars)
    namespace['SESSION'] = tuple(bar['session'] for bar in bars)
    namespace['TRADE_DATE'] = tuple(bar['trade_date'] for bar in bars)
    namespace['PARAMS'] = inputs
    exec(compile(tree, '<python-indicator>', 'exec'), namespace, namespace)
    output = namespace.get('result')
    if output is None:
        raise ValueError('请把指标输出赋给 result')
    output = output if isinstance(output, dict) else {'main': output}
    if not output or len(output) > MAX_LINES:
        raise ValueError('请输出 1–8 条指标线')
    values = {}
    for name, data in output.items():
        if not isinstance(name, str) or not re.fullmatch(r'[\w\u4e00-\u9fff -]{1,32}', name):
            raise ValueError('指标线名称须为 1–32 个字母、数字或汉字')
        values[name] = normalize(data, len(bars))
    return {'time': [bar['time'] for bar in bars], 'values': values}


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        print(json.dumps(calculate(request['code'], request['bars'], request.get('inputs', {})), separators=(',', ':')))
    except Exception as exc:
        print(json.dumps({'error': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False))
