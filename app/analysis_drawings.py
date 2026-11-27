"""Generate sample-backed chart geometry; the agent can select only candidate IDs."""
import hashlib
import json
from statistics import median

from fastapi import HTTPException


FOCUS = {'levels': '最新价附近、经价格反应验证的支撑位与压力位', 'range': '震荡区间和成交密集带', 'strokes': '按交替分型连接的参考笔',
         'fibonacci': '最近确认波段的斐波那契回撤'}
FIBONACCI_RATIOS = (0, .236, .382, .5, .618, .786, 1)
DRAW_PROMPT = (
    '为用户当前图表挑选有量价依据的画线。只从 candidates 选择符合 focus 的候选，最多 4 项。'
    '对于支撑压力，以 reference_price 为最新价。下方选有反弹证据的支撑，上方选有回落证据的压力。'
    '先看距离和独立测试次数，再看回撤或反弹幅度。可只选一侧，不把刚突破的水平直接当作反向支撑或压力。'
    '仅返回 JSON 对象 {"ids":["候选编号"]}，没有足够依据时返回 {"ids":[]}。'
    '不得修改价格或时间，不生成新坐标，不调用工具。'
)


def point(row, column):
    return {'time': row[0], 'price': row[column]}


def geometry(kind, *anchors):
    shape = {'kind': kind, 'points': list(anchors)}
    digest = hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:20]
    return {'id': 'ai-' + digest, **shape}


def pivots(bars):
    """Require two neighbors on each side and skip ambiguous outside bars."""
    result = []
    for i in range(2, len(bars) - 2):
        around = bars[i-2:i] + bars[i+1:i+3]
        high = bars[i][2] > max(row[2] for row in around)
        low = bars[i][3] < min(row[3] for row in around)
        if high != low:
            result.append((i, 2 if high else 3))
    return result


def level_candidates(bars, reference):
    if len(bars) < 5 or reference <= 0:
        return []
    ranges = [max(row[2], prev[4]) - min(row[3], prev[4]) for prev, row in zip(bars, bars[1:])]
    volatility = median(ranges[-14:])
    if volatility <= 0:
        return []
    band = volatility * .25
    candidates = []
    for side, column, direction, label in [('support',3,1,'附近支撑'), ('resistance',2,-1,'附近压力')]:
        # Orient both cases so that a favorable reaction has a positive sign.
        touches = []
        for i in range(2,len(bars)-2):
            level = bars[i][column]
            distance = direction * (reference - level)
            if not 0 < distance <= 3 * volatility:
                continue
            neighbors = bars[i-2:i] + bars[i+1:i+3]
            if any(direction*(r[column]-level)<0 for r in neighbors):
                continue
            reaction = max(direction*(r[4]-level) for r in bars[i+1:i+3])
            if reaction < .75 * volatility:
                continue
            if any(direction*(r[4]-level)<-band for r in bars[i+1:]):
                continue
            touches.append((i,level,reaction))
        ranked = []
        for i,level,reaction in touches:
            tests = []
            for index,price,_ in touches:
                if abs(price-level)<=band and (not tests or index-tests[-1]>=3):
                    tests.append(index)
            distance = abs(reference-level)/volatility
            ranked.append((distance / (1 + .35*min(len(tests)-1,3)), -i, i, level, reaction, len(tests)))
        if ranked:
            _,_,i,level,reaction,count = min(ranked)
            candidates.append({'id':side,'label':label,
                'evidence':f'参考价 {reference:g}，相距 {abs(reference-level)/reference:.2%}。附近有 {count} 次独立测试，'
                           f'该次测试后两根内收盘反应幅度为 {reaction:g}。',
                'lines':[geometry('horizontal', point(bars[i],column))]})
    return candidates


def range_candidates(bars):
    if len(bars) < 12:
        return []
    groups = []
    # Most recent qualifying consolidation. Both boundaries require repeated tests.
    for end in range(len(bars), max(11, len(bars)-20), -1):
        window = bars[end-12:end]
        top = max(window, key=lambda x: x[2])
        bottom = min(window, key=lambda x: x[3])
        width = top[2] - bottom[3]
        if width <= 0 or width / bottom[3] > 0.08:
            continue
        hits_top = sum(top[2] - r[2] <= width * .12 for r in window)
        hits_bottom = sum(r[3] - bottom[3] <= width * .12 for r in window)
        if min(hits_top, hits_bottom) >= 2:
            groups.append({'id': 'consolidation', 'label': '震荡区间',
                           'evidence': f'连续 12 根的振幅为 {width / bottom[3]:.1%}，上沿有 {hits_top} 次、下沿有 {hits_bottom} 次触及。',
                           'lines': [geometry('horizontal', point(top, 2)), geometry('horizontal', point(bottom, 3))]})
            break

    # Allocate each candle's entire volume to its typical price. This is a proxy,
    # not tick-level volume at price. Boundaries are observed closes of that bin.
    low = min(r[3] for r in bars)
    high = max(r[2] for r in bars)
    volume = sum(r[5] or 0 for r in bars)
    if high > low and volume > 0:
        buckets = [[] for _ in range(8)]
        for r in bars:
            typical = (r[2] + r[3] + r[4]) / 3
            buckets[min(7, int(8 * (typical-low)/(high-low)))].append(r)
        dense = max(buckets, key=lambda b: sum(r[5] or 0 for r in b))
        share = sum(r[5] or 0 for r in dense) / volume
        if len(dense) >= 3 and share >= .25:
            # Representative actual closes, restricted to the selected price interval.
            index = buckets.index(dense)
            lo = low + (high-low) * index / 8
            hi = low + (high-low) * (index+1) / 8
            anchors = [r for r in dense if lo <= r[4] <= hi]
            if len(anchors) >= 2:
                bottom, top = min(anchors, key=lambda r:r[4]), max(anchors, key=lambda r:r[4])
                if top[4] > bottom[4]:
                    groups.append({'id':'volume-band','label':'成交密集带（估算）',
                                   'evidence':f'按 K 线典型价分为 8 档，此档占成交量 {share:.0%}。边界取档内实际收盘价，属于非逐笔估算。',
                                   'lines':[geometry('horizontal', point(bottom,4)),geometry('horizontal', point(top,4))]})
    return groups


def swing_anchors(bars, turns):
    chain = []
    for i, column in turns:
        if not chain:
            chain.append((i, column))
            continue
        previous, kind = chain[-1]
        if column == kind:
            if (column == 2 and bars[i][2] >= bars[previous][2]) or (column == 3 and bars[i][3] <= bars[previous][3]):
                chain[-1] = i, column
        elif i - previous >= 4 and ((column == 2 and bars[i][2] > bars[previous][3])
                                     or (column == 3 and bars[i][3] < bars[previous][2])):
            chain.append((i, column))
    return [point(bars[i], col) for i,col in chain[-7:]]


def stroke_candidates(bars, turns):
    anchors = swing_anchors(bars, turns)
    if len(anchors) < 2:
        return []
    return [{'id':'swing-strokes','label':'缠论参考笔（简化）',
             'evidence':'相邻顶底分型至少相隔 4 根，连接交替高低点。仅作分型辅助，未做包含关系处理。',
             'lines':[geometry('trend', a, b) for a,b in zip(anchors,anchors[1:])]}]


def confirmed_bars(frame):
    # The market service may still be updating its final candle.
    return [r for r in frame['bars'][-80:-1] if r[0] > 0 and r[2] >= max(r[1],r[4]) >= r[3] > 0
            and min(r[1],r[4]) >= r[3] and (r[5] is None or r[5] >= 0)]


def retracement(bars, turns):
    anchors = swing_anchors(bars, turns)
    if len(anchors) < 2:
        return None
    start, end = anchors[-2:]
    levels = [{'ratio': ratio, 'price': end['price'] + (start['price'] - end['price']) * ratio}
              for ratio in FIBONACCI_RATIOS]
    delta = end['price'] - start['price']
    direction = 1 if delta > 0 else -1
    follow = [row for row in bars if row[0] > end['time']]
    intact = all(direction*(row[4]-start['price']) >= 0 for row in follow)
    breakout = bool(follow) and direction*(follow[-1][4]-end['price']) > 0
    projections = [{'ratio':r, 'price':start['price']+delta*r} for r in (1.272,1.618)
                   if start['price']+delta*r > 0]
    return {'points': [start, end], 'levels': levels, 'extensions': projections,
            'extend_by_default': bool(projections and intact and breakout)}


def fibonacci_for_frame(frame):
    bars = confirmed_bars(frame)
    return retracement(bars, pivots(bars))


def drawing_proposals(context, focus, ask, extensions='auto'):
    frame = context['frames'][0]
    bars = confirmed_bars(frame)
    turns = pivots(bars)
    if focus == 'levels':
        reference = next((r[4] for r in reversed(frame['bars']) if r[4] > 0), 0)
        context = {**context, 'reference_price':reference}
        candidates = level_candidates(bars, reference)
    elif focus == 'strokes':
        candidates = stroke_candidates(bars, turns)
    elif focus == 'fibonacci':
        fib = retracement(bars, turns)
        candidates = [{'id': 'fibonacci', 'label': '斐波那契回撤',
                       'evidence': '取最近一段已确认的交替高低点，按波段终点向起点计算回撤。',
                       'fibonacci': fib, 'lines': [geometry('fib', *fib['points'])]}] if fib else []
        if fib and fib['extensions'] and (extensions=='always' or extensions=='auto' and fib['extend_by_default']):
            # Native grids measure back from their second anchor. Reverse the anchors for a forward projection.
            line = geometry('fib', *reversed(fib['points']))
            line['id'] += '-ext'
            line['levels'] = [v['ratio'] for v in fib['extensions']]
            candidates.append({'id':'fib-extension', 'label':'顺势扩展',
                'evidence':'最近已收盘 K 线突破波段终点，按原方向投射。' if fib['extend_by_default'] else '手动包含，按原波段幅度沿趋势投射。',
                'fibonacci':{**fib,'levels':fib['extensions']}, 'lines':[line]})
    else:
        candidates = range_candidates(bars)
    selected = []
    if focus == 'fibonacci':
        # An explicit retracement request has precisely one mathematically defined grid.
        selected = candidates
    elif candidates:
        answer = ask(DRAW_PROMPT, {**context,'focus':FOCUS[focus],'candidates':candidates})
        try:
            clean = answer.strip()
            if clean.startswith('```') and clean.endswith('```'):
                clean = clean.split('\n',1)[1].rsplit('```',1)[0].strip()
            ids = json.loads(clean)['ids']
            allowed = {c['id'] for c in candidates}
            if not isinstance(ids,list) or len(ids)>4 or any(type(i) is not str or i not in allowed for i in ids):
                raise ValueError()
        except (ValueError, TypeError, IndexError, KeyError):
            raise HTTPException(502, 'AI 未返回有效的候选编号，请重新生成')
        selected = [c for c in candidates if c['id'] in ids]
    return {'proposals':selected, 'trace':[[r[0],r[4]] for r in bars],
            'stale':frame['stale'], 'evaluated':len(candidates)}
