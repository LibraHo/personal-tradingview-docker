"""User supplied TongdaXin formulas, evaluated from a shared, data-only graph.

No orders, network calls or dynamic code evaluation. Full-window warmup;
recursive SMA/EMA seed at the first valid observation. Undefined ratios stay null.
"""
import json
import math
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

SPEC = json.loads(Path(__file__).with_name('tdx_formulas.json').read_text(encoding='utf-8'))
NAMES = set(SPEC['indicators'])


def evaluate_graph(bars, nodes):
    size = len(bars)
    values = {k: [b[k] for b in bars] for k in ('open', 'high', 'low', 'close', 'volume')}
    values['turnover'] = [v if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 else None
                          for v in (b.get('turnover') for b in bars)]
    def arg(x):
        return values[x] if isinstance(x, str) else [x] * size
    for key, op, args in nodes:
        a = [arg(x) for x in args]
        out = []
        if op == 'session_volume_ratio':
            history = []
            day_id = None
            clocks = args[2:]
            slots = len(clocks) or 1
            current = [None] * slots
            window = int(args[1])
            for bar, volume in zip(bars, a[0]):
                stamp = bar.get('time')
                if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
                    out.append(None)
                    continue
                day, clock = divmod(int(stamp) + 8 * 3600, 86400)
                if day != day_id:
                    if day_id is not None:
                        history.append(current)
                        history = history[-window:]
                    day_id, current = day, [None] * slots
                if (clocks and clock not in clocks) or volume is None or not math.isfinite(volume) or volume < 0:
                    out.append(None)
                    continue
                slot = clocks.index(clock) if clocks else 0
                previous = [row[slot] for row in history]
                current[slot] = volume
                baseline = sum(previous) / window if len(previous) == window and None not in previous else 0
                out.append(volume / baseline if baseline > 0 else None)
        elif op in ('ma', 'sum', 'hhv', 'llv'):
            n = int(args[1])
            for i in range(size):
                w = a[0][max(0, i-n+1):i+1]
                out.append(None if len(w) != n or any(v is None for v in w) else
                           sum(w)/n if op == 'ma' else sum(w) if op == 'sum' else
                           max(w) if op == 'hhv' else min(w))
        elif op == 'smooth':
            last = None
            for x in a[0]:
                if x is None:
                    out.append(None)
                else:
                    last = x if last is None else last+(x-last)*args[1]
                    out.append(last)
        elif op == 'dma':
            last = None
            for x, weight in zip(*a):
                if x is None or weight is None or not 0 <= weight <= 1:
                    out.append(None)
                else:
                    last = x if last is None else last + (x - last) * weight
                    out.append(last)
        elif op == 'ref':
            n = int(args[1]); out = [a[0][i-n] if i >= n else None for i in range(size)]
        elif op == 'filter':
            until = -1
            for i, x in enumerate(a[0]):
                hit = x is not None and bool(x) and i > until
                if hit: until = i+int(args[1])
                out.append(None if x is None else int(hit))
        elif op == 'latch':
            active = False
            for start, stop in zip(*a):
                active = not stop and (active or bool(start))
                out.append(int(active))
        elif op == 'barscount':
            out = list(range(1, size+1))
        elif op == 'cn_volume':
            out = [b['volume']/100 if re.fullmatch(r'(SH|SZ)\.[036]\d{5}', b.get('symbol','')) else None for b in bars]
        elif op == 'date_gate':
            for b in bars:
                dt=datetime.fromtimestamp(b.get('time',0),timezone(timedelta(hours=8)))
                out.append(int(not (dt.year >= 2099 and dt.month > 2)))
        elif op == 'available':
            out = [int(x is not None) for x in a[0]]
        else:
            for i in range(size):
                xs = [v[i] for v in a]
                if op == 'if':
                    out.append(None if xs[0] is None else xs[1] if xs[0] else xs[2]); continue
                if any(x is None for x in xs): out.append(None); continue
                x = xs[0]; y = xs[1] if len(xs)>1 else 0
                if op == 'cross':
                    out.append(None if not i or a[0][i-1] is None or a[1][i-1] is None else int(a[0][i-1] <= a[1][i-1] and x > y)); continue
                if op == 'div': z = x/y if y else None
                elif op == 'add': z = x+y
                elif op == 'sub': z = x-y
                elif op == 'mul': z = x*y
                elif op == 'max': z = max(xs)
                elif op == 'min': z = min(xs)
                elif op == 'abs': z = abs(x)
                elif op == 'ceil': z = math.ceil(x)
                elif op == 'mod': z = x%y if y else None
                elif op == 'gt': z = int(x>y)
                elif op == 'ge': z = int(x>=y)
                elif op == 'lt': z = int(x<y)
                elif op == 'le': z = int(x<=y)
                elif op == 'eq': z = int(x==y)
                elif op == 'and': z = int(all(xs))
                elif op == 'or': z = int(any(xs))
                elif op == 'not': z = int(not x)
                else: raise ValueError('Unknown formula operation: '+op)
                out.append(z if z is None or math.isfinite(z) else None)
        values[key] = out
    return values


def calculate_tdx(bars, name, params=None):
    if name == 'INSTITUTION_TREND': raise ValueError('机构动向已撤下：筹码数据未具备')
    if name == 'FULAI' and any(not re.match(r'^(SH|SZ)\.[036]\d{5}$', b.get('symbol', '')) for b in bars):
        raise ValueError('福来仅支持沪深A股')
    if name not in NAMES: return None
    item = SPEC['indicators'][name]
    symbol_pattern = item.get('symbolPattern')
    period = item.get('period')
    if any((symbol_pattern and b.get('symbol') and not re.fullmatch(symbol_pattern, b['symbol']))
           or (period and b.get('period') and b['period'] != period) for b in bars):
        return {key: [None] * len(bars) for key in item['outputs']}
    needed = set(item['outputs'].values())
    nodes = []
    for node in reversed(SPEC['nodes']):
        if node[0] in needed:
            nodes.append(node)
            needed.update(x for x in node[2] if isinstance(x, str))
    values = evaluate_graph(bars, list(reversed(nodes)))
    return {k: values[v] if isinstance(v, str) else [v]*len(bars) for k, v in item['outputs'].items()}
