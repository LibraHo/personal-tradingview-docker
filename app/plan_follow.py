"""Daily closing value for the defense rules selectable in TradingPlanEditor."""
import math
from functools import lru_cache

from .indicators import calculate
from .sixpulse import DEFAULTS, smooth, calculate_sixpulse as compute_six


def six_boundary(bars, condition):
    """Find the nearest qualifying cent at a six-vote transition (same piecewise roots as the chart)."""
    p = {**DEFAULTS, **condition['params']}
    history, last = bars[:-1], bars[-1]
    if len(bars) < max(p[k] for k in ('kdjPeriod', 'lwrPeriod', 'bbi1', 'bbi2', 'bbi3', 'bbi4')) or len(history) < 2:
        return None
    values = compute_six(history, p)
    close = [b['close'] for b in history]
    changes = [None] + [b-a for a, b in zip(close, close[1:])]
    magnitude = [None if x is None else abs(x) for x in changes]
    up = [None if x is None else max(0, x) for x in changes]

    def advance(old, value, n, exponential=False):
        if value is None:
            return None
        if old is None:
            return value
        return old + (value-old)*(2/(n+1) if exponential else 1/n)

    fast, slow = [smooth(close, p[k], True)[-1] for k in ('fast', 'slow')]
    rsi = [(n, smooth(up, n)[-1], smooth(magnitude, n)[-1]) for n in (p['rsiFast'], p['rsiSlow'])]
    momentum = []
    for n, m in [(p['mtmFast'], p['mtmFastSmooth']), (p['mtmSlow'], p['mtmSlowSmooth'])]:
        a, b = smooth(changes, n, True), smooth(magnitude, n, True)
        momentum.append((n, m, a[-1], b[-1], smooth(a, m, True)[-1], smooth(b, m, True)[-1]))
    bounds = [(min(b['low'] for b in bars[-n:]), max(b['high'] for b in bars[-n:]))
              for n in (p['kdjPeriod'], p['lwrPeriod'])]
    means = [(n, sum(close[-(n-1):]) if n > 1 else 0) for n in (p['bbi1'], p['bbi2'], p['bbi3'], p['bbi4'])]
    def cross(pair):
        (a,b),(c,d) = pair
        return a*d-c*b if b and d else None

    def margins(price):
        delta = price-close[-1]
        diff = advance(fast, price, p['fast'], True)-advance(slow, price, p['slow'], True)
        macd = diff-advance(values['DEA'][-1], diff, p['signal'], True)
        oscillators = []
        for (low, high), neg, a, b, n, m in zip(bounds, (False, True), ('K','LWR1'), ('D','LWR2'),
                                                  ('smoothK','lwrSmooth1'), ('smoothD','lwrSmooth2')):
            low, high = min(low, price), max(high, price)
            width = high-low
            first = advance(values[a][-1], 100*(price-(high if neg else low))/width, p[n]) if width else None
            second = advance(values[b][-1], first, p[m])
            oscillators.append(None if first is None else (first-second)*width)
        rs = cross([(advance(a,max(0,delta),n), advance(b,abs(delta),n)) for n,a,b in rsi])
        mt = cross([(advance(c,advance(a,delta,n,True),m,True), advance(d,advance(b,abs(delta),n,True),m,True))
                    for n,m,a,b,c,d in momentum])
        return [macd,*oscillators,rs,mt,price-sum((total+price)/n for n,total in means)/4]

    points = sorted({0,close[-1],last['low'],last['high'],*(v for pair in bounds for v in pair)})
    candidates = set()
    def add(value):
        i = math.floor(value*100)
        candidates.update(range(max(1,i-2),i+3))
    for i,left in enumerate(points):
        add(left)
        right = points[i+1] if i+1 < len(points) else left+max(1,last['close'])
        x,y = left+(right-left)/4,left+3*(right-left)/4
        for a,b in zip(margins(x),margins(y)):
            if a is None or b is None or abs(b-a) <= 1e-12*max(abs(a),abs(b),1e-15):
                continue
            root = x-a*(y-x)/(b-a)
            if root >= left-.01 and (i+1 == len(points) or root <= right+.01):
                add(root)
    @lru_cache(None)
    def matches(i):
        m = margins(i/100)
        if i <= 0 or None in m:
            return None
        return sum((v>0) == (condition['signal']=='reds') for v in m) >= condition['threshold']
    valid = [i for i in candidates if matches(i) and (matches(i-1) is False or matches(i+1) is False)]
    return min(valid, key=lambda i:(abs(i/100-last['close']),i))/100 if valid else None


def defense_value(plan, bars):
    risk = (plan.get('details') or {}).get('risk') or {}
    rule = risk.get('defense_reference')
    if not rule:
        return plan.get('stop')
    if not bars:
        return None
    c = rule.get('condition')
    if c and c['source'] == 'SIXPULSE':
        value = six_boundary(bars,c)
    elif c and c['source'] in ('SMA','EMA','BOLL','VWAP','BBI'):
        values = calculate(bars,c['source'],c['params'],reset=c['params'].get('reset','session'))
        value = values.get(c['line'],[None])[-1]
    elif rule['label'] == '前 20 根低点' and len(bars)>=21:
        value = min(b['low'] for b in bars[-21:-1])
    elif rule['label'] == '入场参考 − 2×ATR14' and len(bars)>=14:
        atr = calculate(bars,'ATR',{'period':14})['main'][-1]
        value = (risk.get('entry_price') or bars[-1]['close'])-2*atr
    else:
        return None
    return round(value,8) if value is not None and math.isfinite(value) and value>0 else None

