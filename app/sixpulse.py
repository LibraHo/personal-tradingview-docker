"""SixPulse from the user's Mai formula; explicit startup/missing-data rules.

SMA(X,N,1) is recursive with the first valid observation as seed. MA/HHV/
LLV require a full window. Undefined ratios stay None, never bearish signals.
This is a formula port, not a general Mai interpreter or verified moomoo clone.
"""
from .extra_indicators import average, extreme

DEFAULTS = dict(fast=8, slow=13, signal=5, kdjPeriod=8, smoothK=3,
                smoothD=3, rsiFast=5, rsiSlow=13, lwrPeriod=13,
                lwrSmooth1=3, lwrSmooth2=3, bbi1=3, bbi2=6, bbi3=12,
                bbi4=24, mtmFast=5, mtmFastSmooth=3, mtmSlow=13, mtmSlowSmooth=8)
ROWS = ('MACD', 'KDJ', 'RSI', 'LWR', 'BBI', 'MTM')


def smooth(values, n, exponential=False):
    last, out = None, []
    alpha = 2/(n+1) if exponential else 1/n
    for x in values:
        if x is None:
            out.append(None)
            continue
        last = x if last is None else last+(x-last)*alpha
        out.append(last)
    return out


def ratio(a, b, scale=100):
    return [None if x is None or y is None or y == 0 else scale*x/y for x, y in zip(a, b)]


def calculate_sixpulse(bars, p):
    c, h, l = ([b[k] for b in bars] for k in ('close', 'high', 'low'))
    fast, slow = smooth(c, p['fast'], True), smooth(c, p['slow'], True)
    diff = [x-y for x, y in zip(fast, slow)]
    dea = smooth(diff, p['signal'], True)
    def stochastic(n, negative=False):
        hi, lo = extreme(h, n, True), extreme(l, n, False)
        numerator = [None if a is None else x-a if negative else x-b
                     for x, a, b in zip(c, hi, lo)]
        return ratio(numerator, [None if a is None else a-b for a, b in zip(hi, lo)])
    k = smooth(stochastic(p['kdjPeriod']), p['smoothK'])
    d = smooth(k, p['smoothD'])
    change = [None if i == 0 else x-c[i-1] for i, x in enumerate(c)]
    up = [None if x is None else max(x, 0) for x in change]
    absolute = [None if x is None else abs(x) for x in change]
    def rsi(n):
        return ratio(smooth(up, n), smooth(absolute, n))
    rsi1, rsi2 = rsi(p['rsiFast']), rsi(p['rsiSlow'])
    lwr1 = smooth(stochastic(p['lwrPeriod'], True), p['lwrSmooth1'])
    lwr2 = smooth(lwr1, p['lwrSmooth2'])
    means = [average(c, p[f'bbi{i}']) for i in range(1, 5)]
    bbi = [None if any(row[i] is None for row in means) else sum(row[i] for row in means)/4 for i in range(len(c))]
    def momentum(n, m):
        return ratio(smooth(smooth(change, n, True), m, True),
                     smooth(smooth(absolute, n, True), m, True))
    mms, mmm = momentum(p['mtmFast'], p['mtmFastSmooth']), momentum(p['mtmSlow'], p['mtmSlowSmooth'])
    pairs = ((diff, dea), (k, d), (rsi1, rsi2), (lwr1, lwr2), (c, bbi), (mms, mmm))
    out = {name: [None if x is None or y is None else int(x > y) for x, y in zip(a, b)] for name, (a, b) in zip(ROWS, pairs)}
    out['SCORE'] = [None if any(out[name][i] is None for name in ROWS) else sum(out[name][i] for name in ROWS) for i in range(len(c))]
    # Numeric diagnostics are API outputs, not additional plotted curves (NODRAW).
    out.update(DIFF=diff, DEA=dea, K=k, D=d, RSI1=rsi1, RSI2=rsi2,
               LWR1=lwr1, LWR2=lwr2, BBI_VALUE=bbi, MMS=mms, MMM=mmm)
    return out
