import math
import unittest
from datetime import datetime, timedelta, timezone
from app.indicators import calculate
from app.tdx_indicators import NAMES, SPEC, evaluate_graph
from app.scan_engine import evaluate, validate_plan


def rows(n=450, period='1d'):
    # Shanghai close timestamps, beginning on a Monday and skipping weekends.
    slots = {'1d': (54000,), '120m': (41400, 54000), '60m': (37800, 41400, 50400, 54000)}[period]
    first_midnight = int(datetime(2025, 1, 6, tzinfo=timezone(timedelta(hours=8))).timestamp())
    result = []
    for i in range(n):
        session, slot = divmod(i, len(slots))
        day = session // 5 * 7 + session % 5
        timestamp = first_midnight + day * 86400 + slots[slot]
        opening = 100 + math.sin(i / 9) * 12
        close = opening + math.sin(i) * 2
        volume = 10000 + i
        result.append(dict(symbol='SZ.000001', period=period, time=timestamp, close_time=timestamp,
                           confirmed=True, open=opening, close=close, high=opening+16, low=opening-15,
                           volume=volume, turnover=(opening+close)/2*volume,
                           fields={'chip_winner_95': (i % 11) / 10,
                                   'chip_cost_85': close * (1 + .05 * math.sin(i / 7))}))
    return result


class TdxTests(unittest.TestCase):
    def test_resonance_excludes_index_turnover(self):
        bars = [dict(symbol='SH.000001', open=price, close=price, high=price, low=price,
                     volume=vol, turnover=price * vol)
                for price, vol in [(100, 1000)] * 15 + [(90, 1000), (108, 3000)]]
        for name in ('CHIEF_RESONANCE', 'CHIEF_RESONANCE_PANE'):
            self.assertTrue(all(all(value is None for value in series)
                                for series in calculate(bars, name).values()))
        for bar in bars:
            bar['symbol'] = 'SZ.000001'
        self.assertEqual(calculate(bars, 'CHIEF_RESONANCE')['共振'][-1], 1)

    def test_resonance_uses_turnover_per_share_and_same_bar_breakout(self):
        bars = [dict(symbol='SZ.000001', period='1d', time=i, close_time=i+1, confirmed=True, open=price, close=price, high=price,
                     low=price, volume=volume, turnover=price * volume)
                for i, (price, volume) in enumerate([(100, 1000)] * 15 + [(90, 1000), (108, 3000)])]
        main = calculate(bars, 'CHIEF_RESONANCE')
        self.assertIsNotNone(main)
        pane = calculate(bars, 'CHIEF_RESONANCE_PANE')
        self.assertEqual(main['共振'], pane['共振'])
        self.assertEqual(main['共振'][-2:], [0, 1])
        self.assertAlmostEqual(pane['偏离度'][-1], (108 / (1298 / 13) - 1) * 100)
        self.assertTrue(evaluate({'1d': bars}, self.plan('CHIEF_RESONANCE', '共振'), '1d')[-1]['match'])
        bars[-1]['confirmed'] = False
        self.assertFalse(evaluate({'1d': bars}, self.plan('CHIEF_RESONANCE', '共振'), '1d')[-1]['match'])
        for missing in (0, None, float('nan')):
            bars[-1]['turnover'] = missing
            self.assertIsNone(calculate(bars, 'CHIEF_RESONANCE')['共振'][-1])
        del bars[-1]['turnover']
        self.assertIsNone(calculate(bars, 'CHIEF_RESONANCE')['共振'][-1])

    def test_sma_is_recursive_not_simple_average(self):
        b=[dict(open=x,close=x,high=x,low=x,volume=1) for x in [3,9,0]]
        v=evaluate_graph(b,[['s','smooth',['close',1/3]],['c','cross',['close','s']]])
        self.assertEqual(v['s'],[3,5,10/3])
        self.assertEqual(v['c'],[None,1,0])

    def test_independent_three_signal_reference(self):
        b=rows();c=[x['close'] for x in b]
        def avg(x,n):return [None if i<n-1 or any(t is None for t in x[i-n+1:i+1]) else sum(x[i-n+1:i+1])/n for i in range(len(x))]
        def smooth(x,alpha):
            y=[];last=None
            for t in x:
                if t is None:y.append(None);continue
                last=t if last is None else alpha*t+(1-alpha)*last;y.append(last)
            return y
        r=[];bear=[]
        for i,x in enumerate(c):
            for n,out,inverse in [(19,r,False),(35,bear,True)]:
                if i<n-1:out.append(None);continue
                w=b[i-n+1:i+1];h=max(t['high'] for t in w);l=min(t['low'] for t in w)
                out.append(100*((h-x) if inverse else (x-l))/(h-l))
        k=smooth(r,1/3);d=smooth(k,1/3)
        short=smooth([None if x is None else 3*x-2*d[i] for i,x in enumerate(k)],2/7)
        floating=avg(short,28);bear=avg(bear,3)
        def cross(a,bb,i):return None if i==0 or any(x is None for x in [a[i],bb[i],a[i-1],bb[i-1]]) else int(a[i]>bb[i] and a[i-1]<=bb[i-1])
        actual=calculate(b,'YAOGU_BUY')['买入'];tracking=calculate(b,'YAOGU_TRACK')['追踪']
        for i in range(len(b)):
            cr=cross(short,floating,i)
            self.assertEqual(actual[i],None if cr is None else int(cr and short[i]<36))
            self.assertEqual(tracking[i],cross(floating,bear,i))
        source=avg([(x['low']+x['high']+2*x['close'])/4 for x in b],4)
        high=[None if i<12 else max(source[i-9:i+1]) for i in range(len(b))]
        smoothed=avg(high,3)
        upper=[None if y is None else min(high[i],1.25*y-.25*high[i]) for i,y in enumerate(smoothed)]
        m=avg(c,13);actual=calculate(b,'YAOGU_START')['启动']
        for i in range(len(b)):
            a,z=cross(c,m,i),cross(c,upper,i)
            self.assertEqual(actual[i],None if a is None or z is None else int(a and z))

    def test_no_future_and_no_infinity(self):
        for name in NAMES:
            period = SPEC['indicators'][name].get('period', '1d')
            b = rows(period=period)
            all_values=calculate(b,name);prefix=calculate(b[:200],name)
            if name.endswith('RVOL'):
                self.assertTrue(any(x is not None and x > 0 for values in all_values.values() for x in values), name)
            for key,v in all_values.items():
                self.assertEqual(v[:200],prefix[key]);self.assertEqual(len(v),len(b))
                self.assertTrue(all(x is None or math.isfinite(x) for x in v))
            self.assertTrue(all(x==[] for x in calculate([],name).values()))
            flat = [{**bar, 'open':0, 'close':0, 'high':0, 'low':0, 'volume':0, 'turnover':0} for bar in b[:100]]
            self.assertTrue(all(x is None or math.isfinite(x) for v in calculate(flat,name).values() for x in v))

    def test_missing_chips_are_not_false_signals(self):
        bars = [{**bar, 'fields': {'chip_profit_ratio': 0.99, 'chip_interval_overlap': 0.90}}
                for bar in rows()]
        with self.assertRaisesRegex(ValueError, 'WINNER'):
            calculate(bars, 'INSTITUTION_TREND')
        plan = self.plan('INSTITUTION_TREND', '机构高度控盘')
        with self.assertRaisesRegex(ValueError, 'WINNER'):
            evaluate({'1d': bars}, plan, '1d')
        bars[-1]['fields'] = {'chip_winner_95': 0.7}
        with self.assertRaisesRegex(ValueError, 'COST'):
            calculate(bars[-1:], 'INSTITUTION_TREND')

    @staticmethod
    def plan(name,line):
        return dict(periods=['1d'],live=False,lookback=50,rules=[dict(left=dict(name=name,line=line),op='eq',right=dict(name='NUMBER',value=1))])

    def test_scanner_uses_same_outputs_and_ignores_unconfirmed(self):
        b=rows();b[-1]['confirmed']=False
        for name,line in [('YAOGU_BUY','买入'),('YAOGU_TRACK','追踪'),('YAOGU_START','启动')]:
            actual=calculate(b,name)[line]
            result=evaluate({'1d':b},self.plan(name,line),'1d')
            self.assertEqual(result[-1]['time'],b[-2]['time'])
            expected = {bar['time']: value == 1 for bar, value in zip(b, actual)}
            for x in result:self.assertEqual(x['match'], expected[x['time']])

    def test_institution_is_price_rate(self):
        chip_fields = {'chip_winner_95': 0.51, 'chip_cost_85': 109.9}
        b=[dict(open=100,close=100,high=101,low=99,volume=1,fields=chip_fields)]*30
        v=calculate(b,'INSTITUTION_TREND')
        self.assertEqual(v['控盘'],[None]+[0]*29)
        b=b+[dict(open=100,close=110,high=111,low=99,volume=1,fields=chip_fields)]
        self.assertAlmostEqual(calculate(b,'INSTITUTION_TREND')['控盘'][-1],4)

        values = calculate(b,'INSTITUTION_TREND')
        self.assertAlmostEqual(values['机构高度控盘'][-1], 4)
        self.assertEqual(values['机构试盘'][-1], 5)
        self.assertEqual(values['散户活跃'][-1], 0)
        self.assertEqual(values['散户活跃'][-2], 1)
        for field, limit in [('chip_winner_95', 0.5), ('chip_cost_85', 110)]:
            last = {**b[-1], 'fields': {**chip_fields, field: limit}}
            self.assertEqual(calculate(b[:-1] + [last],'INSTITUTION_TREND')['机构高度控盘'][-1], 0)
