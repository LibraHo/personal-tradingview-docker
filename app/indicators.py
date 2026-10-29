from __future__ import annotations
import math


def sma(values, n):
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        section = values[i - n + 1:i + 1]
        if all(v is not None for v in section):
            out[i] = sum(section) / n
    return out


def ema(values, n):
    out = []
    last = None
    alpha = 2 / (n + 1)
    for value in values:
        if value is None:
            out.append(None)
            continue
        last = value if last is None else alpha * value + (1 - alpha) * last
        out.append(last)
    return out


def calculate(bars, name, params=None, reset='session'):
    p = params or {}
    close = [b['close'] for b in bars]
    high = [b['high'] for b in bars]
    low = [b['low'] for b in bars]
    volume = [b['volume'] for b in bars]
    n = max(1, int(p.get('period', 14)))
    if name in ('EMA', 'SMA'):
        calc = ema if name == 'EMA' else sma
        if 'periods' not in p and 'period' not in p:
            p = dict(p, periods=[5,10,20])
        if 'periods' not in p:
            return {'main': calc(close, n)}
        periods = p['periods']
        if not isinstance(periods,list) or not 1 <= len(periods) <= 12 or any(type(x) is not int or not 1 <= x <= 2000 for x in periods):
            raise ValueError('均线周期须为 1–2000 的整数，最多 12 条')
        label = 'EMA' if name == 'EMA' else 'MA'
        return {f'{label}{period}':calc(close,period) for period in dict.fromkeys(periods)}
    if name == 'BBI':
        periods = [max(1, int(x)) for x in p.get('periods', [3, 6, 12, 24])]
        parts = [sma(close, x) for x in periods]
        return {'main': [sum(x[i] for x in parts) / len(parts) if all(x[i] is not None for x in parts) else None for i in range(len(bars))]}
    if name == 'MACD':
        fast, slow, signal = (max(1, int(p.get(k, d))) for k, d in [('fast', 12), ('slow', 26), ('signal', 9)])
        a, b = ema(close, fast), ema(close, slow)
        dif = [x - y for x, y in zip(a, b)]
        dea = ema(dif, signal)
        return {'macd': dif, 'signal': dea, 'hist': [x - y for x, y in zip(dif, dea)]}
    if name == 'RSI':
        gains = [0] + [max(close[i] - close[i - 1], 0) for i in range(1, len(close))]
        losses = [0] + [max(close[i - 1] - close[i], 0) for i in range(1, len(close))]
        ag, al = ema(gains, n), ema(losses, n)
        return {'main': [100 if l == 0 else 100 - 100 / (1 + g / l) for g, l in zip(ag, al)]}
    if name == 'BOLL':
        mid = sma(close, n)
        scale = float(p.get('stddev', 2))
        sd = [None if i < n - 1 else math.sqrt(sum((v - mid[i]) ** 2 for v in close[i-n+1:i+1]) / n) for i in range(len(close))]
        return {'mid': mid, 'upper': [None if m is None else m + scale*s for m,s in zip(mid,sd)], 'lower': [None if m is None else m - scale*s for m,s in zip(mid,sd)]}
    if name in ('ATR', 'DMI'):
        tr = [high[0] - low[0]] if bars else []
        plus, minus = [0], [0]
        for i in range(1, len(bars)):
            tr.append(max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])))
            up, down = high[i]-high[i-1], low[i-1]-low[i]
            plus.append(up if up > down and up > 0 else 0)
            minus.append(down if down > up and down > 0 else 0)
        atr = ema(tr, n)
        if name == 'ATR':
            multiplier = float(p.get('multiplier', 2))
            return {'main': atr, 'stop_long': [c-multiplier*a for c,a in zip(close,atr)], 'stop_short': [c+multiplier*a for c,a in zip(close,atr)]}
        ep, em = ema(plus,n), ema(minus,n)
        pdi = [100*x/a if a else 0 for x,a in zip(ep,atr)]
        mdi = [100*x/a if a else 0 for x,a in zip(em,atr)]
        dx = [100*abs(x-y)/(x+y) if x+y else 0 for x,y in zip(pdi,mdi)]
        return {'plus_di': pdi, 'minus_di': mdi, 'adx': ema(dx,n)}
    if name == 'VWAP':
        result, pv, vol, previous = [], 0, 0, None
        for bar in bars:
            key = bar.get('trade_date') if reset == 'day' else bar.get('session_date')
            if reset != 'never' and key != previous:
                pv = vol = 0
            previous = key
            pv += ((bar['high'] + bar['low'] + bar['close']) / 3) * bar['volume']
            vol += bar['volume']
            result.append(pv / vol if vol else None)
        return {'main': result}
    if name == 'VOLUME':
        return {'volume': volume, 'average': sma(volume, n)}
    raise ValueError(f'Unsupported indicator: {name}')
