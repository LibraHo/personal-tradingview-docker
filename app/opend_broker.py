"""OpenD SDK adapter for trading and read-only account archives."""
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .broker_provider import ArchiveError, BrokerRejected, BrokerUncertain, TradeError, STOCK_SYMBOL, OPTION_SYMBOL, SYMBOL
from .ledger import OPTION, SYMBOL as LEDGER_SYMBOL

ET = ZoneInfo('America/New_York')


def instrument(row):
    code = row.get('code') or ''
    match = OPTION.fullmatch(code)
    if match:
        root, expiry, right, strike = match.groups()
        try:
            day = date.fromisoformat('20' + expiry[:2] + '-' + expiry[2:4] + '-' + expiry[4:])
        except ValueError as exc:
            raise ArchiveError('期权合约到期日无法识别') from exc
        owner = row.get('stock_owner') or root
        if not re.fullmatch(LEDGER_SYMBOL['US'], owner) or int(strike) == 0:
            raise ArchiveError('期权标的或行权价无法识别')
        return dict(kind='option', symbol=owner, code=code, expiry=day.isoformat(),
                    strike=int(strike) / 1000, right=right)
    if not re.fullmatch(LEDGER_SYMBOL['US'], code):
        raise ArchiveError('券商返回了无法识别的美股证券代码')
    return dict(kind='stock', symbol=code, code=code)


def finite(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = math.nan
    if isinstance(value, bool) or not math.isfinite(number):
        raise ArchiveError('券商返回的' + label + '无效')
    return number


def position(row):
    result = instrument(row)
    qty = finite(row.get('qty'), '持仓数量')
    result['qty'] = -abs(qty) if row.get('position_side') == 'SHORT' else qty
    if row.get('average_cost') is not None:
        result['cost'] = finite(row['average_cost'], '持仓成本')
    elif row.get('cost_price_valid'):
        result['cost'] = finite(row.get('cost_price'), '持仓成本')
    return result


def fill(row):
    ident = row.get('deal_id')
    if isinstance(ident, bool) or not isinstance(ident, (int, str)) or not str(ident).strip():
        raise ArchiveError('券商成交编号缺失或精度不明确')
    status = row.get('status')
    result = dict(broker_id=str(ident), broker_status=status)
    if status == 'CANCELLED':
        return result
    if status not in {'OK', 'CHANGED'}:
        raise ArchiveError('出现无法归档的券商成交状态')
    if row.get('trd_side') not in {'BUY', 'BUY_BACK', 'SELL', 'SELL_SHORT'}:
        raise ArchiveError('券商成交方向无法识别')
    try:
        raw_time = str(row.get('create_time'))
        # OpenD returns variable precision; Python 3.10 accepts only 3 or 6 fractional digits.
        raw_time = re.sub(r'(?<=\d:\d\d)\.(\d+)(?=Z|[+-]|$)',
                          lambda m: '.' + m[1][:6].ljust(6, '0'), raw_time)
        at = datetime.fromisoformat(raw_time.removesuffix('Z') + ('+00:00' if raw_time.endswith('Z') else ''))
    except ValueError as exc:
        raise ArchiveError('券商成交时间无效') from exc
    if at.tzinfo is None:
        at = at.replace(tzinfo=ET)
    return {**result, **instrument(row), 'at': at.isoformat(), 'side': row['trd_side'],
            'price': finite(row.get('price'), '成交价格'), 'qty': finite(row.get('qty'), '成交数量')}


def records(frame):
    """Preserve large broker IDs as strings (JavaScript numbers are not safe)."""
    rows = frame.to_dict('records')
    result = []
    for row in rows:
        out = {}
        for key, value in row.items():
            if key in {'acc_id', 'order_id', 'position_id'}:
                out[key] = str(value)
            elif hasattr(value, 'item'):
                value = value.item()
                out[key] = None if isinstance(value, float) and not math.isfinite(value) else value
            elif isinstance(value, float) and not math.isfinite(value):
                out[key] = None
            elif isinstance(value, (str, int, float, bool, list)) or value is None:
                out[key] = value
            else:
                out[key] = str(value)
        result.append(out)
    return result


class OpenDBroker:
    source_id = 'opend'
    capabilities = {'trading', 'archive'}

    def __init__(self):
        self.ctx = None
        self.quote_ctx = None
        self.generation = 0
        self.security_types = {}
        self.option_metadata = {}

    def ensure(self):
        if self.ctx is None:
            import moomoo as mm
            rsa = os.getenv('OPEND_RSA_FILE', '')
            if rsa:
                mm.SysConfig.enable_proto_encrypt(True)
                mm.SysConfig.set_init_rsa_file(rsa)
            self.ctx = mm.OpenSecTradeContext(
                filter_trdmarket=mm.TrdMarket.US,
                host=os.getenv('OPEND_HOST', 'moomoo-opend'),
                port=int(os.getenv('OPEND_PORT', '11111')), is_encrypt=bool(rsa),
                security_firm=os.getenv('TRADING_SECURITY_FIRM', 'N/A'))
            self.generation += 1
        return self.ctx

    @staticmethod
    def unpack(response):
        ret, data = response
        if ret != 0:
            raise BrokerRejected(str(data)[:600])
        return records(data)

    def accounts(self):
        rows = self.unpack(self.ensure().get_acc_list())
        return [r for r in rows if 'US' in str(r.get('trdmarket_auth', ''))
                and r.get('trd_env') in {'REAL', 'SIMULATE'} and r.get('sim_acc_type') != 'FUTURES']

    def positions(self, acc, env):
        return self.unpack(self.ensure().position_list_query(
            position_market='US', acc_id=int(acc), trd_env=env, refresh_cache=True))

    def archive_positions(self, account):
        return [position(row) for row in self.positions(account, 'REAL')]

    def archive_fills(self, account, start, end, as_of):
        # Include fractional seconds up to the exclusive next midnight.
        local_now = as_of.astimezone(ET)
        next_day = end + timedelta(days=1)
        until = local_now.strftime('%Y-%m-%d %H:%M:%S') if end == local_now.date() else f'{next_day} 00:00:00'
        query = dict(acc_id=int(account), trd_env='REAL', deal_market='US')
        ctx = self.ensure()
        history = ctx.history_deal_list_query(**query, start=f'{start} 00:00:00', end=until)
        fills = [fill(row) for row in reversed(self.unpack(history))
                 if str(row.get('create_time', ''))[:10] != next_day.isoformat()]
        if end == local_now.date():
            fills.extend(fill(row) for row in self.unpack(ctx.deal_list_query(**query, refresh_cache=True)))
        return fills

    def funds(self, acc, env):
        return self.unpack(self.ensure().accinfo_query(acc_id=int(acc), trd_env=env, currency='USD'))

    def orders(self, acc, env, refresh=True):
        return self.unpack(self.ensure().order_list_query(
            order_market='US', acc_id=int(acc), trd_env=env, refresh_cache=refresh))

    def capacity(self, order, order_id=None):
        rows = self.unpack(self.ensure().acctradinginfo_query(
            order_type=order['order_type'], code=order['code'], price=order['reference_price'],
            acc_id=int(order['acc_id']), trd_env=order['env'], session=order['session'],
            order_id=order_id))
        if not rows:
            raise TradeError('券商没有返回可交易数量')
        return rows[0]

    def unlock(self, password=None, lock=False):
        ret, _ = self.ensure().unlock_trade(password=password, is_unlock=not lock)
        if ret != 0:
            # Never reflect SDK errors from credential-bearing requests.
            raise TradeError('交易解锁/锁定失败，请检查密码、账号状态及券商令牌限制')

    def ensure_quote(self):
        if self.quote_ctx is None:
            import moomoo as mm
            from .opend_connection import connect_quote_context
            self.ensure()
            self.quote_ctx = connect_quote_context(mm.OpenQuoteContext, host=os.getenv('OPEND_HOST', 'moomoo-opend'),
                port=int(os.getenv('OPEND_PORT', '11111')), is_encrypt=bool(os.getenv('OPEND_RSA_FILE')))
        return self.quote_ctx

    def option_chain(self, symbol, expiry=''):
        if not STOCK_SYMBOL.fullmatch(symbol) or OPTION_SYMBOL.fullmatch(symbol):
            raise TradeError('请输入美股正股或 ETF 代码')
        ctx = self.ensure_quote()
        if not expiry:
            rows = self.unpack(ctx.get_option_expiration_date(symbol))
            return {'expirations': sorted({r['strike_time'] for r in rows}), 'contracts': []}
        try:
            datetime.strptime(expiry, '%Y-%m-%d')
        except ValueError:
            raise TradeError('到期日格式应为 YYYY-MM-DD')
        stamp, rows = self.option_metadata.get((symbol, expiry), (0, None))
        if time.time()-stamp > 300:
            rows = self.unpack(ctx.get_option_chain(symbol, start=expiry, end=expiry))
            if len(self.option_metadata) >= 32:
                self.option_metadata.clear()
            self.option_metadata[(symbol, expiry)] = (time.time(), rows)
        keys = ('code', 'name', 'option_type', 'strike_price', 'strike_time', 'lot_size', 'option_standard_type')
        return {'expirations': [expiry], 'contracts': [{k:r.get(k) for k in keys} for r in rows]}

    def quote(self, symbol):
        if not SYMBOL.fullmatch(symbol):
            raise TradeError('请输入美股股票、ETF 或期权合约代码')
        self.ensure_quote()
        rows = self.unpack(self.quote_ctx.get_market_snapshot([symbol]))
        if not rows:
            raise TradeError('没有行情数据')
        r = rows[0]
        if r.get('option_valid'):
            self.security_types[symbol] = 'OPTION'
            owner = str(r.get('stock_owner') or '')
            if not STOCK_SYMBOL.fullmatch(owner):
                raise TradeError('无法确认期权标的')
            if owner not in self.security_types:
                basic = self.unpack(self.quote_ctx.get_stock_basicinfo(market='US', code_list=[owner]))
                self.security_types[owner] = basic[0].get('stock_type') if basic else None
            if self.security_types[owner] not in {'STOCK', 'ETF'}:
                raise TradeError('当前仅开放股票和 ETF 期权，不支持指数期权')
            chain = self.option_chain(owner, str(r.get('strike_time') or ''))
            contract = next((c for c in chain['contracts'] if c['code'] == symbol), {})
            r['option_standard_type'] = contract.get('option_standard_type')
        elif symbol not in self.security_types:
            basic = self.unpack(self.quote_ctx.get_stock_basicinfo(market='US', code_list=[symbol]))
            self.security_types[symbol] = basic[0].get('stock_type') if basic else None
        if self.security_types[symbol] not in {'STOCK', 'ETF', 'OPTION'}:
            raise TradeError('仅支持美股股票、ETF 和标准股票/ETF 单腿期权')
        r['stock_type'] = self.security_types[symbol]
        states = self.unpack(self.quote_ctx.get_market_state([symbol]))
        r['market_state'] = states[0].get('market_state') if states else None
        return {k: r.get(k) for k in ('code', 'name', 'last_price', 'update_time', 'stock_type', 'market_state',
            'option_valid', 'lot_size', 'option_contract_size', 'option_contract_multiplier',
            'option_type', 'stock_owner', 'strike_time', 'option_strike_price', 'bid_price', 'ask_price', 'option_standard_type')}

    def place(self, order, remark):
        kwargs = dict(price=order.get('price', 0), qty=order['qty'], code=order['code'],
                      trd_side=order['side'], order_type=order['order_type'],
                      trd_env=order['env'], acc_id=int(order['acc_id']),
                      time_in_force=order['time_in_force'], session=order['session'], remark=remark)
        for key in ('aux_price', 'trail_type', 'trail_value', 'trail_spread'):
            if key in order:
                kwargs[key] = order[key]
        ret, data = self.ensure().place_order(**kwargs)
        if ret != 0:
            # The SDK collapses transport failures and broker errors into RET_ERROR.
            # Never assume a RET_ERROR proves that no order reached the broker.
            raise BrokerUncertain(str(data)[:400])
        return records(data)

    def modify(self, order, cancel=False):
        kwargs = dict(modify_order_op='CANCEL' if cancel else 'NORMAL',
                      order_id=order['order_id'], qty=order.get('qty', 0), price=order.get('price', 0),
                      acc_id=int(order['acc_id']), trd_env=order['env'])
        if not cancel:
            for key in ('aux_price', 'trail_type', 'trail_value', 'trail_spread'):
                if key in order:
                    kwargs[key] = order[key]
        ret, data = self.ensure().modify_order(**kwargs)
        if ret != 0:
            raise BrokerUncertain(str(data)[:400])
        return records(data)

    def close(self):
        for ctx in (self.ctx, self.quote_ctx):
            if ctx is not None:
                ctx.close()
        self.ctx = self.quote_ctx = None
