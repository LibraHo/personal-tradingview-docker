"""Read-only contract selection and whole-contract cash/position sizing."""
import math
import os
import time
from decimal import Decimal, ROUND_FLOOR


class OptionToolsMixin:
    def nearest_option(self, code, expiry, direction):
        from .trading import TradeError, STOCK_SYMBOL, number
        if not STOCK_SYMBOL.fullmatch(code) or direction not in {'CALL','PUT'} or not expiry:
            raise TradeError('请先选择正股、到期日和 Call / Put')
        quote=self.quote(code)
        if quote.get('stock_type') not in {'STOCK','ETF'}:
            raise TradeError('当前仅支持股票和 ETF 的期权')
        basis=float(number(quote.get('last_price'),'正股价格'))
        rows=self.option_chain(code,expiry)['contracts']
        rows=[r for r in rows if r.get('option_type')==direction and r.get('option_standard_type')=='STANDARD'
              and isinstance(r.get('strike_price'),(int,float)) and math.isfinite(r['strike_price']) and r['strike_price']>0]
        if not rows:
            raise TradeError('该到期日没有可用的标准合约')
        contract=min(rows,key=lambda r:(abs(r['strike_price']-basis),r['strike_price'],r['code']))
        return dict(contract=contract,underlying_price=basis,update_time=quote.get('update_time'),market_state=quote.get('market_state'))

    def option_size(self, acc, env, code, side, fraction, limit):
        from .trading import TradeError, number
        denominators={'1/4':4,'1/3':3,'1/2':2,'1':1}
        if fraction not in denominators or side not in {'BUY','SELL'}:
            raise TradeError('仓位比例仅支持 1/4、1/3、半仓和全仓')
        order=self.normalize(dict(acc_id=acc,env=env,code=code,side=side,order_type='NORMAL',qty=1,price=limit,session='RTH',time_in_force='DAY'))
        if order.get('security_type')!='OPTION':
            raise TradeError('该测算只用于期权')
        unit=Decimal(str(order['price']))*order['multiplier']
        result=dict(fraction=fraction,side=side,price=order['price'],code=code,fee_reserve=0,cash_basis=0,budget=0)
        if side=='BUY':
            funds=self.broker.funds(acc,env)
            if not funds:
                raise TradeError('未返回美元现金，无法测算仓位')
            raw=funds[0].get('usd_cash')
            cash=number(raw if raw is not None else funds[0].get('cash'),'美元现金',positive=False)
            if cash<=0:
                raise TradeError('美元现金不足，不使用融资或其他币种购买期权')
            reserve=max(Decimal(0),number(os.getenv('TRADING_OPTION_FEE_RESERVE_USD','5'),'费用预留',positive=False))
            budget=min(cash/denominators[fraction],Decimal(str(self.max_notional)))
            qty=int(max(Decimal(0),budget-reserve)//unit)
            cap=self.broker.capacity(order)
            cash_qty=int(number(cap.get('max_cash_buy') or 0,'券商现金购买能力',positive=False).to_integral_value(rounding=ROUND_FLOOR))
            qty=min(qty,cash_qty,self.max_shares)
            result.update(cash_basis=float(cash),budget=float(budget),fee_reserve=float(reserve),broker_max_cash_contracts=cash_qty)
        else:
            position=next((p for p in self.broker.positions(acc,env) if p['code']==code),None)
            if not position or position.get('position_side')=='SHORT' or float(position.get('qty') or 0)<=0:
                raise TradeError('没有可卖出的多头期权')
            available=max(0,int(number(position.get('can_sell_qty') or 0,'可卖张数',positive=False)))
            qty=available//denominators[fraction]
            qty=min(qty,self.max_shares,int(Decimal(str(self.max_notional))//unit))
            result.update(available=available)
        if qty<1:
            raise TradeError('该仓位比例不足一张，或现金/单笔上限不足；不会向上凑单')
        return dict(result,qty=qty,estimate=float(unit*qty),as_of=time.time())
