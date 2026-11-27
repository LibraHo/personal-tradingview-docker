"""Read-only scanner uses the chart's Python indicator implementation."""
import bisect
import math
import time
from .indicators import calculate, check_inputs
from .tdx_indicators import SPEC as TDX_SPEC

PERIODS = {'1m','5m','15m','30m','60m','120m','240m','1d','1w','1mo'}
LINES = {'PRICE':['close','open','high','low','volume'], 'NUMBER':[],
 'SMA':['main'],'EMA':['main'],'SIXPULSE':['REDS','GREENS','MACD','KDJ','RSI','LWR','BBI','MTM'],
 'MACD':['macd','signal','hist'],'RSI':['main'],'BOLL':['upper','mid','lower'],
 'VOLUME':['volume','average'],'DMI':['plus_di','minus_di','adx'],'ATR':['main']}
OPS = {'gt','gte','lt','lte','eq','cross_above','cross_below','reach','fall','enter_eq','rise_eq','fall_eq'}
LINES.update({name: [key for key, value in item['outputs'].items() if value is not None]
              for name, item in TDX_SPEC['indicators'].items()})


def validate_plan(p):
    if not isinstance(p, dict): raise ValueError('方案须为对象')
    if p.get('scope',{}).get('market') not in (None,'US','CN'):raise ValueError('市场须为 US 或 CN')
    if not 1 <= len(p.get('rules', [])) <= 12: raise ValueError('需要 1–12 个条件')
    if not p.get('periods') or any(x not in PERIODS for x in p['periods']): raise ValueError('周期无效')
    if p.get('join','all') not in ('all','any'): raise ValueError('组合无效')
    if type(p.get('lookback',1)) is not int or not 1 <= p.get('lookback',1) <= 50: raise ValueError('回看须为 1–50')
    for r in p['rules']:
        if r.get('op') not in OPS: raise ValueError('比较方式无效')
        if r.get('period') and r['period'] not in PERIODS: raise ValueError('条件周期无效')
        for key, default, low, high in [('offset',0,0,250),('window',1,1,250),('min_count',1,1,250)]:
            if type(r.get(key,default)) is not int or not low<=r.get(key,default)<=high: raise ValueError('历史条件参数无效')
        if r.get('temporal','current') not in ('current','all','any','count','streak'): raise ValueError('历史条件类型无效')
        maximum=r.get('max_count')
        if maximum is not None and (type(maximum) is not int or not r.get('min_count',1)<=maximum<=250): raise ValueError('次数上限无效')
        if r.get('temporal')=='count' and r.get('min_count',1)>r.get('window',1): raise ValueError('次数不能超过窗口')
        for o in (r.get('left',{}),r.get('right',{})):
            if type(o.get('offset',0)) is not int or not 0<=o.get('offset',0)<=250: raise ValueError('指标历史偏移无效')
            if o.get('name') not in LINES: raise ValueError('指标无效')
            if o['name'] != 'NUMBER' and o.get('line') not in LINES[o['name']]: raise ValueError('输出线无效')
            item = TDX_SPEC['indicators'].get(o['name'], {})
            market, period = item.get('market'), item.get('period')
            if market and p.get('scope', {}).get('market') not in (None, market):
                raise ValueError(item['label'] + '仅适用于沪深A股')
            if period and any(value != period for value in ([r['period']] if r.get('period') else p['periods'])):
                label = {'60m':'1小时','120m':'2小时','1d':'日线'}.get(period, period)
                raise ValueError(item['label'] + '仅适用于' + label + '周期')
            for k,v in o.get('params',{}).items():
                if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or not 0<v<=500 or (k!='stddev' and int(v)!=v): raise ValueError('指标参数无效')
            if o['name']=='NUMBER' and (not isinstance(o.get('value'),(int,float)) or not math.isfinite(o['value'])): raise ValueError('数值无效')
            if not isinstance(o.get('scale',1),(int,float)) or not math.isfinite(o.get('scale',1)) or abs(o.get('scale',1))>100000: raise ValueError('倍数无效')
    return p


def series(bars, o):
    name, line = o['name'], o.get('line')
    defaults={'SMA':20,'EMA':20,'RSI':14,'BOLL':20,'VOLUME':20,'DMI':14,'ATR':14}
    params={**({'period':defaults[name]} if name in defaults else {}),**o.get('params',{})}
    if name == 'PRICE' and line == 'volume':
        check_inputs(bars, name, ['volume'])
    else:
        check_inputs(bars, name)
    if name == 'NUMBER': result = [o['value']]*len(bars)
    elif name == 'PRICE': result = [b[line] for b in bars]
    else:
        values = calculate(bars, name, params)
        if name == 'SIXPULSE' and line in ('REDS','GREENS'):
            result = [None if x is None else x if line=='REDS' else 6-x for x in values['SCORE']]
        else: result = values[line]
    scale = o.get('scale',1)
    warmup=int(params.get('period',1)) if name in defaults else 1
    if name=='MACD':warmup=int(params.get('slow',26))+int(params.get('signal',9))
    if name=='DMI':warmup*=2
    values=[v*scale if i>=warmup-1 and v is not None and math.isfinite(v) else None for i,v in enumerate(result)]
    offset=o.get('offset',0)
    return [values[i-offset] if i>=offset else None for i in range(len(values))]


def compare(a,b,op,j):
    if j<0: return None
    x,y=a[j],b[j]
    if x is None or y is None: return None
    if op in ('cross_above','cross_below','reach','fall','enter_eq','rise_eq','fall_eq'):
        if j==0 or a[j-1] is None or b[j-1] is None: return None
        px,py=a[j-1],b[j-1]
        return {'cross_above':lambda:px<=py and x>y,'cross_below':lambda:px>=py and x<y,'reach':lambda:px<py and x>=y,'fall':lambda:px>py and x<=y,'enter_eq':lambda:px!=py and x==y,'rise_eq':lambda:px<py and x==y,'fall_eq':lambda:px>py and x==y}[op]()
    return {'gt':lambda:x>y,'gte':lambda:x>=y,'lt':lambda:x<y,'lte':lambda:x<=y,'eq':lambda:x==y}[op]()


def temporal_check(states,j,r):
    mode=r.get('temporal','current')
    if j<0 or states[j] is None: return False,False,{}
    if mode=='current':return states[j],True,{}
    minimum,maximum=r.get('min_count',1),r.get('max_count')
    if mode=='streak':
        n=0;k=j
        while k>=0 and states[k] is True:n+=1;k-=1
        exact=k>=0 and states[k] is False
        evidence={'streak':n,'streak_exact':exact}
        # A known lower bound proves >=N; an upper bound needs a known start.
        if not exact and n<minimum:return False,False,evidence
        if maximum is not None and not exact and n<=maximum:return False,False,evidence
        return n>=minimum and (maximum is None or n<=maximum),True,evidence
    window=r.get('window',1)
    values=states[max(0,j-window+1):j+1]
    if len(values)!=window or any(v is None for v in values):return False,False,{'window':window}
    count=sum(values)
    ok=count==window if mode=='all' else count>0 if mode=='any' else count>=minimum and (maximum is None or count<=maximum)
    return ok,True,{'count':count,'window':window}



def evaluate(data, plan, period, history_limit=None):
    """Evaluate each decision using only candles available at that instant."""
    validate_plan(plan)
    live = plan.get('live',True)
    base = data[period]
    decisions = [i for i,b in enumerate(base) if live or b['confirmed']]
    if not decisions: raise ValueError('无已完成 K 线')
    sources = []
    for rule in plan['rules']:
        rp = rule.get('period') or period
        rows = data[rp]
        a,b=series(rows,rule['left']),series(rows,rule['right'])
        sources.append((rule,rp,rows,a,b,[b['close_time'] for b in rows],[compare(a,b,rule['op'],j) for j in range(len(rows))],[row['time'] for row in rows]))
    results=[]
    for idx in decisions[-(history_limit or plan.get('lookback',1)):]:
        decision = base[idx]['close_time']
        preview = live and not base[idx]['confirmed']
        cutoff = min(decision, time.time()) if preview else decision
        checks=[]
        for r,rp,rows,a,b,ends,states,starts in sources:
            j = idx if rp==period else bisect.bisect_right(ends,cutoff)-1
            if rp!=period:
                while j>=0 and not rows[j]['confirmed']: j-=1
                if preview:
                    # Only the current preview may see an unfinished higher period.
                    # Historical decisions retain their original close-time boundary.
                    candidate = bisect.bisect_right(starts, cutoff)-1
                    if candidate>=0 and not rows[candidate]['confirmed']:
                        j = candidate
            j-=r.get('offset',0)
            x,y = (a[j],b[j]) if j>=0 else (None,None)
            px,py = (a[j-1],b[j-1]) if j>0 else (None,None)
            ok,valid,evidence=temporal_check(states,j,r)
            checks.append({'ok':ok,'valid':valid,'left':x,'right':y,'previous_left':px,'previous_right':py,'period':rp,'time':rows[j]['time'] if j>=0 else None,'offset':r.get('offset',0),'temporal':r.get('temporal','current'),'name':r.get('name',''),'left_time':rows[j-r['left'].get('offset',0)]['time'] if j>=r['left'].get('offset',0) else None,'right_time':rows[j-r['right'].get('offset',0)]['time'] if j>=r['right'].get('offset',0) else None,**evidence})
        # Missing inputs never produce a valid scan, including OR plans.
        if not all(c['valid'] for c in checks):
            results.append({'match':False,'valid':False,'time':base[idx]['time'],'close_time':decision,'checks':checks,'confirmed':base[idx]['confirmed']})
            continue
        match = all(c['ok'] for c in checks) if plan.get('join','all')=='all' else any(c['ok'] for c in checks)
        results.append({'match':match,'valid':True,'time':base[idx]['time'],'close_time':decision,'checks':checks,'confirmed':base[idx]['confirmed']})
    if not results or not results[-1]['valid']:
        missing = []
        for index, check in enumerate(results[-1]['checks'] if results else []):
            if not check['valid']:
                rule = plan['rules'][index]
                operands = ' / '.join(value['name'] + '.' + value.get('line', '') for value in (rule['left'], rule['right']) if value['name'] != 'NUMBER')
                missing.append((rule.get('name') or '条件 '+str(index+1)) + '（' + operands + ' · ' + check['period'] + '）')
        raise ValueError('指标预热数据不足或数据缺失' + ('：'+'；'.join(missing) if missing else ''))
    return results
