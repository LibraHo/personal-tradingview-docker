"""Additional OHLCV indicators. Full-window warmup; no lookahead or market calls."""
from collections import deque

DEFAULTS = {'WMA': 20, 'VWMA': 20, 'DC': 20, 'STOCH': 14, 'CCI': 20,
            'WR': 14, 'ROC': 9, 'MOM': 10, 'OBV': 14, 'CMF': 20}


def period(params, key, default):
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 2000 or int(value) != value:
        raise ValueError(f'{key} 须为 1–2000 的整数')
    return int(value)


def rolling_sum(values, n):
    total = valid = 0
    result = []
    for i, value in enumerate(values):
        if value is not None:
            total += value
            valid += 1
        if i >= n and values[i-n] is not None:
            total -= values[i-n]
            valid -= 1
        result.append(total if i >= n-1 and valid == n else None)
    return result


def average(values, n):
    return [None if x is None else x/n for x in rolling_sum(values, n)]


def extreme(values, n, high):
    queue, result = deque(), []
    for i, value in enumerate(values):
        while queue and (values[queue[-1]] <= value if high else values[queue[-1]] >= value):
            queue.pop()
        queue.append(i)
        while queue[0] <= i-n:
            queue.popleft()
        result.append(values[queue[0]] if i >= n-1 else None)
    return result


def calculate_extra(bars, name, params):
    if name not in DEFAULTS:
        return None
    close = [b['close'] for b in bars]
    volume = [b['volume'] for b in bars]
    n = period(params, 'period', DEFAULTS[name])
    if name == 'OBV':
        total, result = 0, []
        for i, value in enumerate(close):
            if i:
                total += (1 if value > close[i-1] else -1 if value < close[i-1] else 0) * volume[i]
            result.append(total)
        return {'main': result}
    if name == 'WMA':
        total = weighted = 0
        result = []
        for i, value in enumerate(close):
            weighted += (i+1 if i < n else n)*value
            if i >= n:
                weighted -= total
            total += value - (close[i-n] if i >= n else 0)
            result.append(weighted/(n*(n+1)/2) if i >= n-1 else None)
        return {'main': result}
    if name == 'VWMA':
        pv = rolling_sum([c*v for c, v in zip(close, volume)], n)
        sv = rolling_sum(volume, n)
        return {'main': [None if x is None or not v else x/v for x, v in zip(pv, sv)]}
    if name in ('ROC', 'MOM'):
        return {'main': [None if i < n else value-close[i-n] if name == 'MOM' else
                         100*(value-close[i-n])/close[i-n] if close[i-n] else None
                         for i, value in enumerate(close)]}
    if name == 'CCI':
        tp = [(b['high']+b['low']+b['close'])/3 for b in bars]
        means, result = average(tp, n), []
        for i, value in enumerate(tp):
            if means[i] is None:
                result.append(None)
                continue
            deviation = sum(abs(x-means[i]) for x in tp[i-n+1:i+1])/n
            # Decimal prices can leave roundoff despite a constant window.
            tolerance = 2.220446049250313e-16 * max(1, abs(value), abs(means[i])) * 8
            result.append((value-means[i])/(0.015*deviation) if deviation > tolerance else 0)
        return {'main': result}
    if name == 'CMF':
        flow = rolling_sum([0 if b['high'] == b['low'] else
                            (2*b['close']-b['high']-b['low'])/(b['high']-b['low'])*b['volume'] for b in bars], n)
        sv = rolling_sum(volume, n)
        return {'main': [None if x is None or not v else x/v for x, v in zip(flow, sv)]}
    high = extreme([b['high'] for b in bars], n, True)
    low = extreme([b['low'] for b in bars], n, False)
    if name == 'DC':
        return {'upper': high, 'mid': [None if h is None else (h+l)/2 for h, l in zip(high, low)], 'lower': low}
    if name == 'WR':
        return {'main': [None if h is None or h == l else -100*(h-c)/(h-l) for c, h, l in zip(close, high, low)]}
    raw = [None if h is None or h == l else 100*(c-l)/(h-l) for c, h, l in zip(close, high, low)]
    k = average(raw, period(params, 'smoothK', 3))
    return {'k': k, 'd': average(k, period(params, 'smoothD', 3))}
