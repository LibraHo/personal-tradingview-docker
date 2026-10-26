"""Bounded declarative conditions; strategy code never receives broker access."""
import copy
import json
import math
import re
import time

from .indicators import calculate
from .python_indicator_worker import validate_code, validate_inputs

PERIOD_SECONDS={'1m':60,'5m':300,'15m':900,'30m':1800,'60m':3600}
BUILTINS={'EMA','SMA','VWAP','BBI','MACD','RSI','BOLL','ATR','DMI','VOLUME'}
OPS={'cross_above','cross_below','gt','gte','lt','lte','eq'}


def number(value, minimum, maximum, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError(label+'超出允许范围')
    return value


def validate_strategy(raw):
    if not isinstance(raw,dict) or len(json.dumps(raw))>24000:
        raise ValueError('策略配置须为不超过 24KB 的对象')
    c=copy.deepcopy(raw)
    name=c.get('name','')
    if not isinstance(name,str) or not 1<=len(name.strip())<=50:raise ValueError('请输入 1–50 字策略名称')
    if not re.fullmatch(r'US\.[A-Z][A-Z0-9.]{0,11}',str(c.get('symbol',''))):raise ValueError('第一版策略仅支持美股')
    if c.get('period') not in PERIOD_SECONDS:raise ValueError('策略周期支持 1/5/15/30/60 分钟')
    if c.get('mode') not in {'regular','extended','all'}:raise ValueError('行情时段不正确')
    sources=c.get('sources')
    if not isinstance(sources,list) or not 1<=len(sources)<=8:raise ValueError('每个策略使用 1–8 个指标源')
    ids=set()
    for source in sources:
        if not isinstance(source,dict):raise ValueError('指标源须为对象')
        sid=source.get('id','')
        if not isinstance(sid,str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,24}',sid) or sid in ids:raise ValueError('指标源 ID 重复或格式不正确')
        ids.add(sid)
        name=source.get('name');p=source.setdefault('params',{})
        if not isinstance(p,dict):raise ValueError('指标参数须为对象')
        if name=='PYTHON':
            if not isinstance(p.get('code'),str):raise ValueError('请输入 Python 指标代码')
            validate_code(p.get('code',''));validate_inputs(p.get('inputs',{}))
        elif name in BUILTINS:
            for key in ('period','fast','slow','signal'):
                if key in p:
                    number(p[key],1,500,'指标周期')
                    if int(p[key])!=p[key]:raise ValueError('指标周期须为整数')
            if 'periods' in p:
                if not isinstance(p['periods'],list) or not 1<=len(p['periods'])<=8:raise ValueError('BBI 周期须为 1–8 项')
                for n in p['periods']:
                    number(n,1,500,'BBI 周期')
                    if int(n)!=n:raise ValueError('BBI 周期须为整数')
            for key in ('stddev','multiplier'):
                if key in p:number(p[key],0,100,key)
            if p.get('reset','session') not in {'session','day','never'}:raise ValueError('VWAP 重置方式不正确')
        else:raise ValueError('支持内置指标和 Python 指标源')
    def reference(value):
        if not isinstance(value,str):raise ValueError('条件左侧须为指标输出线')
        if value in {'close','open','high','low','volume'}:return
        if not isinstance(value,str) or ':' not in value or value.split(':',1)[0] not in ids:raise ValueError('条件引用了不存在的指标源')
    for side in ('buy','sell'):
        group=c.get(side,{})
        if not isinstance(group,dict) or group.get('join','all') not in {'all','any'}:raise ValueError('条件组合方式不正确')
        conditions=group.setdefault('conditions',[])
        if not isinstance(conditions,list) or len(conditions)>8:raise ValueError('每个方向最多 8 个条件')
        for rule in conditions:
            if not isinstance(rule,dict):raise ValueError('条件须为对象')
            reference(rule.get('left'))
            if rule.get('op') not in OPS:raise ValueError('条件运算不支持')
            r=rule.get('right')
            if isinstance(r,str):reference(r)
            else:number(r,-1e12,1e12,'比较数值')
        c[side]=group
    if not c['buy']['conditions'] and not c['sell']['conditions']:raise ValueError('至少配置一个买入或卖出条件')
    e=c.setdefault('execution',{})
    if not isinstance(e,dict):raise ValueError('执行参数须为对象')
    defaults={'qty':10,'sell_percent':100,'session':'RTH','offset_percent':0.1,'max_deviation':1,'flat_only':True,'max_executions':1}
    e={**defaults,**e}
    number(e['qty'],1,100000,'股数');number(e['sell_percent'],1,100,'卖出比例')
    number(e['offset_percent'],0,2,'限价偏移');number(e['max_deviation'],0.01,5,'价格偏离上限')
    number(e['max_executions'],1,10,'每次授权执行次数')
    if int(e['qty'])!=e['qty'] or int(e['max_executions'])!=e['max_executions']:raise ValueError('股数和执行次数须为整数')
    if not isinstance(e['flat_only'],bool):raise ValueError('空仓限制格式不正确')
    if e['session'] not in {'RTH','ETH','OVERNIGHT','ALL'}:raise ValueError('订单时段不正确')
    if e.get('protection'):
        from .protection import stop_config
        if e['session']!='RTH':raise ValueError('成交后止损方案只支持 RTH')
        try:e['protection']=stop_config(e['protection'])
        except Exception as exc:raise ValueError(str(exc)) from exc
    c['execution']=e
    if not isinstance(c.get('cross_session',False),bool):raise ValueError('跨时段开关格式不正确')
    return {k:c[k] for k in ('name','symbol','period','mode','sources','buy','sell','execution')}|{'cross_session':c.get('cross_session',False)}


def evaluate(config,bars,now=None,python_runner=None):
    now=time.time() if now is None else now
    duration=PERIOD_SECONDS[config['period']]
    closed=[b for b in bars if b['time']+duration+3<=now]
    if len(closed)<2:raise ValueError('至少需要两根已完成 K 线；等待收线或加载更多历史')
    series={field:[b[field] for b in closed] for field in ('close','open','high','low','volume')}
    for source in config['sources']:
        p=source.get('params',{})
        if source['name']=='PYTHON':
            if python_runner is None:raise ValueError('Python 计算器不可用')
            values=python_runner(p['code'],closed,p.get('inputs',{}))['values']
        else:values=calculate(closed,source['name'],p,p.get('reset','session'))
        for label,values_list in values.items():series[source['id']+':'+label]=values_list
    def value(ref,index):
        if isinstance(ref,(int,float)):return ref
        if ref not in series:raise ValueError('找不到指标输出线：'+str(ref))
        return series[ref][index]
    evidence={}
    def test(rule):
        a,b=value(rule['left'],-1),value(rule['right'],-1)
        evidence[rule['left']]=a
        if isinstance(rule['right'],str):evidence[rule['right']]=b
        if a is None or b is None:return False
        op=rule['op']
        if op.startswith('cross_'):
            if not config.get('cross_session') and closed[-1].get('session_date')!=closed[-2].get('session_date'):return False
            pa,pb=value(rule['left'],-2),value(rule['right'],-2)
            if pa is None or pb is None:return False
            return pa<=pb and a>b if op=='cross_above' else pa>=pb and a<b
        return {'gt':a>b,'gte':a>=b,'lt':a<b,'lte':a<=b,'eq':a==b}[op]
    result={}
    for side in ('buy','sell'):
        g=config[side];checks=[test(r) for r in g['conditions']]
        result[side]=bool(checks) and (all(checks) if g.get('join','all')=='all' else any(checks))
    return {**result,'bar_time':closed[-1]['time'],'bar_end':closed[-1]['time']+duration,
            'close':closed[-1]['close'],'closed_count':len(closed),'series':list(series),
            'latest_values':{k:v[-1] for k,v in series.items()},'evidence':evidence}
