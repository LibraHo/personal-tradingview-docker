"""MSIGM8: Mai MACD SHORT formula. Signals use past/current bars only.

DRAWLINE starts at the preceding pivot candle, once the turn is known.
BUY/SELL preserve the unfiltered *_TRIGGER outputs in the supplied formula.
"""
DEFAULTS = dict(fast=12, slow=26, signal=9, validBars=8, bufferRate=.0003)


def signals_from_histogram(bars, histogram, valid_bars, buffer_rate):
    names = ('SELL_TURN', 'BUY_TURN', 'SELL_LEVEL', 'BUY_LEVEL', 'SELL_AGE', 'BUY_AGE',
             'SELL_SIGNAL', 'BUY_SIGNAL', 'SELL_START', 'BUY_START',
             'SELL_MARKER', 'BUY_MARKER', 'BUY', 'SELL')
    out = {name: [] for name in names}
    state = {side: dict(turn=-1, level=None, peak=None, expanded=-1, triggered=-1)
             for side in ('SELL', 'BUY')}
    for i, bar in enumerate(bars):
        for side in ('SELL', 'BUY'):
            sell = side == 'SELL'
            s = state[side]
            turn = i >= 2 and (histogram[i-2] < histogram[i-1] > histogram[i] if sell
                              else histogram[i-2] > histogram[i-1] < histogram[i])
            if turn:
                s.update(turn=i, level=bars[i-1]['low' if sell else 'high'], peak=histogram[i-1])
            age = i - s['turn'] if s['turn'] >= 0 else None
            expanded = s['peak'] is not None and (histogram[i] > s['peak'] if sell else histogram[i] < s['peak'])
            if expanded:
                s['expanded'] = i
            close, level = bar['close'], s['level']
            buffer = close * buffer_rate
            trigger = level is not None and ((close < level-buffer if sell else close > level+buffer)
                                            or (turn and (close < level if sell else close > level)))
            # BARSLAST(REF(trigger,1)) counts from the bar after the previous trigger.
            signal = (trigger and age+1 <= valid_bars and s['turn'] > s['expanded']
                      and s['triggered'] < s['turn'])
            out[side+'_TURN'].append(int(turn))
            out[side+'_LEVEL'].append(level)
            out[side+'_AGE'].append(age)
            out[side+'_SIGNAL'].append(int(signal))
            out[side+'_START'].append(s['turn']-1 if signal else None)
            pad = (bar['high']-bar['low']) * .25
            out[side+'_MARKER'].append((bar['high']+pad if sell else bar['low']-pad) if signal else None)
            out[side].append(int(trigger))
            if trigger:
                s['triggered'] = i
    return out


def calculate_msigm8(bars, p):
    def ema(values, n):
        last = None
        out = []
        for value in values:
            last = value if last is None else last+(value-last)*2/(n+1)
            out.append(last)
        return out
    close = [bar['close'] for bar in bars]
    dif = [a-b for a, b in zip(ema(close, p['fast']), ema(close, p['slow']))]
    dea = ema(dif, p['signal'])
    histogram = [(a-b)*2 for a, b in zip(dif, dea)]
    return dict(DIF=dif, DEA=dea, MACDH=histogram,
                **signals_from_histogram(bars, histogram, p['validBars'], p['bufferRate']))
