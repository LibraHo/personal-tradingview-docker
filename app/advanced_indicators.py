"""Common indicators, explicitly seeded and based only on past/current OHLCV."""
import math
from .extra_indicators import average, rolling_sum, extreme
from .sixpulse import DEFAULTS as SIXPULSE_DEFAULTS, calculate_sixpulse, signal_settings, signal_values

DEFAULTS = {
    'SIXPULSE': SIXPULSE_DEFAULTS, 'SIXPULSE_SIGNAL': SIXPULSE_DEFAULTS,
    'KDJ': dict(period=9, smoothK=3, smoothD=3), 'MFI': dict(period=14),
    'KC': dict(period=20, atrPeriod=10, multiplier=2), 'SUPERTREND': dict(period=10, multiplier=3),
    'SAR': dict(start=.02, increment=.02, maximum=.2),
    'STOCHRSI': dict(rsiPeriod=14, period=14, smoothK=3, smoothD=3),
    'HMA': dict(period=21), 'DEMA': dict(period=20), 'TEMA': dict(period=20),
    'TRIX': dict(period=15, signal=9), 'PPO': dict(fast=12, slow=26, signal=9),
    'AO': dict(fast=5, slow=34), 'BIAS': dict(period=6), 'ADL': {},
    'CHO': dict(fast=3, slow=10), 'PVT': {}, 'BOP': {},
    'BBW': dict(period=20, stddev=2), 'BBP': dict(period=20, stddev=2), 'AROON': dict(period=25),
}


def parameters(name, inputs):
    if name not in DEFAULTS:
        return None
    if not isinstance(inputs, dict):
        raise ValueError('指标参数须为对象')
    result = {}
    for key, fallback in DEFAULTS[name].items():
        value = inputs.get(key, fallback)
        fractional = key in ('multiplier', 'stddev', 'start', 'increment', 'maximum')
        limit = 1 if name == 'SAR' else 100 if fractional else 2000
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= limit or (not fractional and int(value) != value):
            raise ValueError(f'{key} 参数无效（须为正数，最大 {limit}）')
        result[key] = value if fractional else int(value)
    if 'fast' in result and result['fast'] >= result['slow']:
        raise ValueError('慢线周期须大于快线周期')
    if name in ('SIXPULSE', 'SIXPULSE_SIGNAL') and (result['rsiFast'] >= result['rsiSlow'] or result['mtmFast'] >= result['mtmSlow']):
        raise ValueError('RSI、MTM 慢线周期须大于快线周期')
    if name == 'SAR' and (result['start'] > result['maximum'] or result['increment'] > result['maximum']):
        raise ValueError('初始加速和步长不得大于最大加速')
    if name == 'SIXPULSE_SIGNAL':signal_settings(inputs)
    return result


def ema(values, n):
    result, last = [], None
    for value in values:
        if value is None:
            result.append(None)
            continue
        last = value if last is None else last+(value-last)*2/(n+1)
        result.append(last)
    return result


def rma(values, n):
    result, last, total, count = [], None, 0, 0
    for value in values:
        if value is None:
            last, total, count = None, 0, 0
            result.append(None)
            continue
        if last is None:
            total += value
            count += 1
            if count < n:
                result.append(None)
                continue
            last = total/n
        else:
            last += (value-last)/n
        result.append(last)
    return result


def wma(values, n):
    result, total, weighted, valid = [], 0, 0, 0
    for i, value in enumerate(values):
        weighted += (i+1 if i < n else n)*(value or 0)
        if i >= n:
            weighted -= total
        total += (value or 0) - ((values[i-n] or 0) if i >= n else 0)
        valid += int(value is not None) - (int(values[i-n] is not None) if i >= n else 0)
        result.append(weighted/(n*(n+1)/2) if i >= n-1 and valid == n else None)
    return result


def rsi(close, n):
    gain = rma([max(0, x-close[i-1]) if i else None for i, x in enumerate(close)], n)
    loss = rma([max(0, close[i-1]-x) if i else None for i, x in enumerate(close)], n)
    return [None if g is None else 50 if not g and not l else 100 if not l else 100-100/(1+g/l) for g, l in zip(gain, loss)]


def atr(bars, n):
    return rma([max(b['high']-b['low'], abs(b['high']-bars[i-1]['close']), abs(b['low']-bars[i-1]['close'])) if i else b['high']-b['low'] for i, b in enumerate(bars)], n)


def calculate_advanced(bars, name, inputs):
    p = parameters(name, inputs)
    if p is None:
        return None
    if name in ('SIXPULSE', 'SIXPULSE_SIGNAL'):
        values = calculate_sixpulse(bars, p)
        return signal_values(values, inputs) if name == 'SIXPULSE_SIGNAL' else values
    c, h, l = ([b[key] for b in bars] for key in ('close', 'high', 'low'))
    n = p.get('period')
    if name == 'KDJ':
        hi, lo = extreme(h, n, True), extreme(l, n, False)
        k = d = 50
        ks, ds, js = [], [], []
        for i, x in enumerate(c):
            if hi[i] is None:
                ks.append(None); ds.append(None); js.append(None)
                continue
            raw = 50 if hi[i] == lo[i] else 100*(x-lo[i])/(hi[i]-lo[i])
            k += (raw-k)/p['smoothK']
            d += (k-d)/p['smoothD']
            ks.append(k); ds.append(d); js.append(3*k-2*d)
        return dict(k=ks, d=ds, j=js)
    if name == 'MFI':
        tp = [(b['high']+b['low']+b['close'])/3 for b in bars]
        pos = rolling_sum([x*bars[i]['volume'] if i and x > tp[i-1] else 0 if i else None for i, x in enumerate(tp)], n)
        neg = rolling_sum([x*bars[i]['volume'] if i and x < tp[i-1] else 0 if i else None for i, x in enumerate(tp)], n)
        return {'main': [None if x is None or (not x and not y) else 100 if not y else 100-100/(1+x/y) for x, y in zip(pos, neg)]}
    if name == 'STOCHRSI':
        values = rsi(c, p['rsiPeriod'])
        raw = []
        for i, x in enumerate(values):
            if x is None or i < p['rsiPeriod']+n-1:
                raw.append(None)
                continue
            hi, lo = max(values[i-n+1:i+1]), min(values[i-n+1:i+1])
            raw.append(None if hi == lo else 100*(x-lo)/(hi-lo))
        k = average(raw, p['smoothK'])
        return dict(k=k, d=average(k, p['smoothD']))
    if name == 'HMA':
        half, full = wma(c, max(1, n//2)), wma(c, n)
        return {'main': wma([None if x is None else 2*half[i]-x for i, x in enumerate(full)], max(1, int(math.sqrt(n)+.5)))}
    if name in ('DEMA', 'TEMA', 'TRIX'):
        a = ema(c, n); b = ema(a, n); triple = ema(b, n)
        if name == 'DEMA':
            return {'main': [2*x-y for x, y in zip(a, b)]}
        if name == 'TEMA':
            return {'main': [3*x-3*y+z for x, y, z in zip(a, b, triple)]}
        main = [100*(x-triple[i-1])/triple[i-1] if i and triple[i-1] else None for i, x in enumerate(triple)]
        return dict(main=main, signal=ema(main, p['signal']))
    if name == 'KC':
        mid, a = ema(c, n), atr(bars, p['atrPeriod'])
        return dict(mid=mid, upper=[None if y is None else x+p['multiplier']*y for x, y in zip(mid, a)], lower=[None if y is None else x-p['multiplier']*y for x, y in zip(mid, a)])
    if name == 'SUPERTREND':
        a, main, direction = atr(bars, n), [], []
        upper = lower = 0
        up = ready = False
        for i in range(len(bars)):
            if a[i] is None:
                main.append(None); direction.append(None)
                continue
            bu, bl = (h[i]+l[i])/2+p['multiplier']*a[i], (h[i]+l[i])/2-p['multiplier']*a[i]
            if not ready:
                upper, lower, ready = bu, bl, True
            else:
                upper = bu if bu < upper or c[i-1] > upper else upper
                lower = bl if bl > lower or c[i-1] < lower else lower
                up = not c[i] < lower if up else c[i] > upper
            main.append(lower if up else upper); direction.append(1 if up else -1)
        return dict(main=main, direction=direction)
    if name == 'SAR':
        main = [None]*len(bars)
        if len(bars) < 2:
            return dict(main=main)
        up = c[1] > c[0]
        value, ep, af = (l[0] if up else h[0]), (h[1] if up else l[1]), p['start']
        main[1] = value
        for i in range(2, len(bars)):
            value += af*(ep-value)
            if value > l[i] if up else value < h[i]:
                value = max(ep, h[i]) if up else min(ep, l[i])
                up = not up
                ep, af = (h[i] if up else l[i]), p['start']
            else:
                value = min(value, l[i-1], l[i-2]) if up else max(value, h[i-1], h[i-2])
                if h[i] > ep if up else l[i] < ep:
                    ep = h[i] if up else l[i]
                    af = min(p['maximum'], af+p['increment'])
            main[i] = value
        return dict(main=main)
    if name == 'PPO':
        fast, slow = ema(c, p['fast']), ema(c, p['slow'])
        main = [100*(x-y)/y if y else None for x, y in zip(fast, slow)]
        signal = ema(main, p['signal'])
        return dict(main=main, signal=signal, hist=[None if x is None or y is None else x-y for x, y in zip(main, signal)])
    if name == 'AO':
        median = [(b['high']+b['low'])/2 for b in bars]
        fast, slow = average(median, p['fast']), average(median, p['slow'])
        return {'hist': [None if y is None else x-y for x, y in zip(fast, slow)]}
    if name == 'BIAS':
        return {'main': [100*(x-y)/y if y else None for x, y in zip(c, average(c, n))]}
    if name == 'PVT':
        main, total = [], 0
        for i, x in enumerate(c):
            if not i:
                main.append(0)
                continue
            if not c[i-1]:
                main.append(None)
                continue
            total += (x-c[i-1])/c[i-1]*bars[i]['volume']
            main.append(total)
        return dict(main=main)
    if name == 'BOP':
        return {'main': [0 if b['high'] == b['low'] else (b['close']-b['open'])/(b['high']-b['low']) for b in bars]}
    if name in ('ADL', 'CHO'):
        ad, total = [], 0
        for b in bars:
            total += 0 if b['high'] == b['low'] else (2*b['close']-b['high']-b['low'])/(b['high']-b['low'])*b['volume']
            ad.append(total)
        if name == 'ADL':
            return {'main': ad}
        return {'main': [x-y for x, y in zip(ema(ad, p['fast']), ema(ad, p['slow']))]}
    if name in ('BBW', 'BBP'):
        ma, main = average(c, n), []
        for i, x in enumerate(c):
            if ma[i] is None:
                main.append(None)
                continue
            sd = math.sqrt(sum((v-ma[i])**2 for v in c[i-n+1:i+1])/n)
            span = 2*p['stddev']*sd
            if name == 'BBW':
                main.append(span/ma[i]*100 if ma[i] else None)
            else:
                main.append(None if sd <= 2.220446049250313e-16*max(1, abs(x), abs(ma[i]))*8 else (x-ma[i]+span/2)/span)
        return dict(main=main)
    up, down = [], []
    for i in range(len(bars)):
        if i < n:
            up.append(None); down.append(None)
            continue
        hi = lo = i
        for j in range(i-1, i-n-1, -1):
            if h[j] > h[hi]: hi = j
            if l[j] < l[lo]: lo = j
        up.append(100*(n-i+hi)/n); down.append(100*(n-i+lo)/n)
    return dict(up=up, down=down)
