"""Strategy orders pass through the same broker authorization and risk checks."""
import math
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from .trading import TradeError, ACTIVE


def execute_strategy(engine,owner,config,side,signal,arm):
    acc,env=arm['acc_id'],arm['env']
    engine.authorize(owner,acc,env)
    if arm['expires']<=time.time():raise TradeError('策略交易授权已过期')
    if side not in {'BUY','SELL'}:raise TradeError('信号方向无效')
    code=config['symbol'];e=config['execution']
    orders=engine.broker.orders(acc,env)
    if any(o.get('code')==code and o.get('order_status') in ACTIVE for o in orders):
        raise TradeError('该股票已有未结束订单，请先核对；策略不自动撤单')
    position=next((p for p in engine.broker.positions(acc,env) if p['code']==code),None)
    if side=='BUY' and e['flat_only'] and position and float(position.get('qty') or 0)!=0:
        raise TradeError('策略设为空仓才买，当前已有持仓')
    qty=e['qty'] if side=='BUY' else math.floor(float((position or {}).get('can_sell_qty') or 0)*e['sell_percent']/100)
    if qty<1:raise TradeError('没有符合条件的可卖整股')
    engine.quote_cache.pop(code,None)
    quote=engine.quote(code);last=float(quote['last_price']);basis=float(signal['close'])
    if e['session']!='RTH' or quote.get('market_state')!='AFTERNOON':
        raise TradeError('首版自动策略只在美股常规交易时段提交；其他时段可监控信号')
    try:age=time.time()-datetime.fromisoformat(str(quote['update_time'])).replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
    except (ValueError,KeyError,TypeError):age=999
    if age < -2 or age > 15:raise TradeError('自动策略需要 15 秒内行情快照，已跳过下单')
    if basis<=0 or abs(last/basis-1)*100>e['max_deviation']:raise TradeError('现价偏离信号收盘价，跳过追价')
    raw=last*(1+e['offset_percent']/100*(1 if side=='BUY' else -1))
    step=100 if raw>=1 else 10000
    limit=(math.ceil(raw*step-1e-8) if side=='BUY' else math.floor(raw*step+1e-8))/step
    if abs(limit/basis-1)*100>e['max_deviation']:raise TradeError('限价超出信号价格偏离上限')
    payload=dict(action='PLACE',acc_id=acc,env=env,code=code,side=side,
                 order_type='NORMAL',qty=qty,price=limit,session=e['session'],time_in_force='DAY')
    if side=='BUY' and e.get('protection'):payload['protection']=e['protection']
    preview=engine.preview(owner,payload)
    if arm['expires']<=time.time():raise TradeError('校验期间策略授权到期，未提交')
    return engine.commit(owner,preview['preview_id'],str(uuid.uuid4()),strategy_arm=arm)
