"""User-operated US trading. No agent entry point and no automatic trade retries."""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import sqlite3
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from .protection import ProtectionMixin, stop_config, stop_prices
from .option_tools import OptionToolsMixin


class TradeError(Exception):
    pass


class BrokerRejected(TradeError):
    pass


class BrokerUncertain(Exception):
    pass


ACTIVE = {'UNSUBMITTED', 'WAITING_SUBMIT', 'SUBMITTING', 'SUBMITTED', 'FILLED_PART',
          'CANCELLING_PART', 'CANCELLING_ALL', 'DISABLED'}
TYPES = {'NORMAL', 'MARKET', 'STOP', 'STOP_LIMIT', 'TRAILING_STOP', 'TRAILING_STOP_LIMIT'}
STOCK_SYMBOL = re.compile(r'^US\.[A-Z][A-Z0-9.]{0,11}$')
OPTION_SYMBOL = re.compile(r'^US\.[A-Z][A-Z0-9.]{0,11}\d{6}[CP]\d{1,10}$')
SYMBOL = re.compile(r'^US\.(?:[A-Z][A-Z0-9.]{0,11}|[A-Z][A-Z0-9.]{0,11}\d{6}[CP]\d{1,10})$')


def number(value, name, positive=True):
    if isinstance(value, bool):
        raise TradeError(f'{name}须为有效数字')
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise TradeError(f'{name}须为有效数字')
    if not n.is_finite() or abs(n) > 100000000 or (positive and n <= 0):
        raise TradeError(f'{name}超出允许范围')
    return n


def price(value, name='价格'):
    n = number(value, name)
    step = Decimal('.01') if n >= 1 else Decimal('.0001')
    if n != n.quantize(step):
        raise TradeError(f'{name}精度不正确：1 美元及以上最多两位小数，否则最多四位')
    return float(n)


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


class TradeEngine(ProtectionMixin, OptionToolsMixin):
    """All methods run on one dedicated thread; SQLite is also a crash journal."""
    def __init__(self, path, broker=None):
        self.broker = broker or OpenDBroker()
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.grant = None
        self.previews = {}
        self.rates = deque()
        self.unlock_attempts = deque()
        self.max_notional = float(os.getenv('TRADING_MAX_ORDER_USD', '10000'))
        self.max_shares = int(os.getenv('TRADING_MAX_SHARES', '1000'))
        self.last_activity = time.time()
        self.account_cache = (0, [])
        self.quote_cache = {}
        self.option_chain_cache = {}
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, owner TEXT, '
                       'kind TEXT, payload TEXT, state TEXT, result TEXT, created REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)')
            db.execute("UPDATE operations SET state='UNKNOWN' WHERE state='SENDING'")
        self.init_protection()

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def accounts(self):
        self.last_activity = time.time()
        stamp, rows = self.account_cache
        if time.time() - stamp > 15:
            rows = self.broker.accounts()
            self.account_cache = (time.time(), rows)
        return rows

    def account(self, acc, env):
        match = next((r for r in self.accounts() if str(r['acc_id']) == str(acc)
                      and r['trd_env'] == env), None)
        if not match:
            raise TradeError('账号与交易环境不匹配，或账号没有美股权限')
        return match

    def unlock(self, owner, acc, password):
        self.account(acc, 'REAL')
        now = time.time()
        while self.unlock_attempts and now - self.unlock_attempts[0] > 60:
            self.unlock_attempts.popleft()
        if len(self.unlock_attempts) >= 3:
            raise TradeError('解锁尝试过多，请一分钟后再试')
        self.unlock_attempts.append(now)
        self.broker.unlock(password)
        self.grant = {'owner': owner, 'acc_id': str(acc), 'expires': time.time() + 900,
                      'generation': self.broker.generation}
        return {'expires': self.grant['expires']}

    def lock(self):
        self.pause_protections('交易已锁定，后续成交不会自动挂止损；请核对未成交买单并手动处理或解锁后恢复')
        had_grant = self.grant is not None
        self.grant = None
        self.previews.clear()
        if had_grant:
            self.broker.unlock(lock=True)
        return {'locked': True}

    def authorize(self, owner, acc, env):
        self.account(acc, env)
        if env == 'REAL':
            g = self.grant
            if not g or g['owner'] != owner or g['acc_id'] != str(acc) or g['expires'] <= time.time() \
                    or g['generation'] != self.broker.generation:
                raise TradeError('实盘已锁定，请先在本页面解锁此账号')

    def tick(self):
        if self.grant and self.grant['expires'] <= time.time():
            self.lock()
        self.previews = {k: v for k, v in self.previews.items() if v['expires'] > time.time()}
        self.protection_tick()
        if not self.grant and time.time() - self.last_activity > 120:
            self.broker.close()
            self.account_cache = (0, [])

    def state(self, owner):
        self.last_activity = time.time()
        g = self.grant
        return {'real_enabled': True, 'unlock': {k:v for k,v in g.items() if k != 'owner'} if g and g['owner'] == owner else None,
                'max_notional': self.max_notional, 'max_shares': self.max_shares,
                'server_time': time.time()}

    def snapshot(self, acc, env):
        self.account(acc, env)
        return {'positions': self.broker.positions(acc, env), 'orders': self.broker.orders(acc, env),
                'funds': self.broker.funds(acc, env), 'as_of': time.time(),
                'protections': [{k:v for k,v in p.items() if k != 'owner'} for p in self.protections(acc, env)]}

    def quote(self, code):
        self.last_activity = time.time()
        stamp, q = self.quote_cache.get(code, (0, None))
        if time.time() - stamp > 3:
            q = self.broker.quote(code)
            self.quote_cache[code] = (time.time(), q)
        return q

    def option_chain(self, code, expiry=''):
        self.last_activity = time.time()
        key = (code, expiry)
        stamp, result = self.option_chain_cache.get(key, (0, None))
        if time.time()-stamp > 300:
            result = self.broker.option_chain(code, expiry)
            if len(self.option_chain_cache) >= 32:
                self.option_chain_cache.clear()
            self.option_chain_cache[key] = (time.time(), result)
        return result

    def normalize(self, data):
        acc, env = str(data.get('acc_id', '')), data.get('env')
        self.account(acc, env)
        code = str(data.get('code', '')).upper()
        if not SYMBOL.fullmatch(code):
            raise TradeError('请输入有效的美股股票、ETF 或期权合约代码')
        side, kind = data.get('side'), data.get('order_type')
        if side not in {'BUY', 'SELL'} or kind not in TYPES:
            raise TradeError('不支持此买卖方向或订单类型')
        qty = number(data.get('qty'), '股数')
        if qty != int(qty) or qty > self.max_shares:
            raise TradeError(f'仅支持整股，单笔不超过 {self.max_shares} 股')
        session, tif = data.get('session', 'RTH'), data.get('time_in_force', 'DAY')
        if session not in {'RTH', 'ETH', 'OVERNIGHT', 'ALL'} or tif not in {'DAY', 'GTC'}:
            raise TradeError('交易时段或有效期不正确')
        if env == 'SIMULATE' and (kind not in {'NORMAL', 'MARKET'} or session != 'RTH' or tif != 'DAY'):
            raise TradeError('模拟交易第一版仅支持常规时段、当日有效的限价/市价单')
        if session != 'RTH' and kind != 'NORMAL':
            raise TradeError('盘前盘后及夜盘仅开放限价单；止损只开放常规时段')
        if kind not in {'NORMAL', 'MARKET'} and side != 'SELL':
            raise TradeError('第一版条件单仅用于卖出已有多头持仓')
        out = dict(acc_id=acc, env=env, code=code, side=side, order_type=kind, qty=int(qty),
                   session=session, time_in_force=tif, price=0)
        if data.get('close_position'):
            if side != 'SELL' or kind not in {'NORMAL', 'MARKET'}:
                raise TradeError('平仓仅支持卖出限价单或市价单')
            out['close_position'] = True
        q = self.quote(code)
        is_option = q.get('stock_type') == 'OPTION' or bool(OPTION_SYMBOL.fullmatch(code))
        multiplier = 1
        if is_option:
            if kind not in {'NORMAL','STOP','STOP_LIMIT'} or session != 'RTH' or tif != 'DAY':
                raise TradeError('期权仅开放 RTH / DAY 单腿限价及实盘多头止损')
            if q.get('stock_type') != 'OPTION' or not q.get('option_valid'):
                raise TradeError('无法确认期权合约信息')
            if q.get('option_standard_type') != 'STANDARD':
                raise TradeError('无法确认标准合约，暂不开放调整合约')
            # Fail closed for adjusted, index or unknown deliverables. No assumed x100.
            if any(number(q.get(k), '期权合约乘数') != 100 for k in
                   ('option_contract_size', 'option_contract_multiplier', 'lot_size')):
                raise TradeError('仅开放标准 100 股交割的股票/ETF 期权；合约乘数不匹配')
            try:
                expired = datetime.strptime(q['strike_time'], '%Y-%m-%d').date() < datetime.now(ZoneInfo('America/New_York')).date()
            except (KeyError, TypeError, ValueError):
                raise TradeError('无法确认期权到期日')
            if expired:
                raise TradeError('期权合约已到期')
            multiplier = 100
            out.update(security_type='OPTION', multiplier=multiplier, option_type=q.get('option_type'),
                       expiry=q['strike_time'], strike_price=q.get('option_strike_price'), underlying=q.get('stock_owner'))
        current = float(number(q.get('last_price'), '行情价格'))
        if kind == 'MARKET':
            if q.get('market_state') != 'AFTERNOON':
                raise TradeError('当前不在美股常规交易时段，禁止提交市价单')
            try:
                dt = datetime.fromisoformat(str(q['update_time'])).replace(tzinfo=ZoneInfo('America/New_York'))
                age = time.time() - dt.timestamp()
            except (ValueError, KeyError, TypeError):
                age = 999
            if age < -2 or age > 5:
                raise TradeError('快照超过 5 秒，市价单暂不可用；请使用明确价格的限价单')
        # Validate security type even for manual limit orders. Snapshot age is shown in UI;
        # it is never represented as executable bid/ask.
        if kind in {'NORMAL', 'STOP_LIMIT', 'TRAILING_STOP_LIMIT'}:
            out['price'] = price(data.get('price')) if kind != 'TRAILING_STOP_LIMIT' else 0
        if kind in {'STOP', 'STOP_LIMIT'}:
            out['aux_price'] = price(data.get('aux_price'), '触发价')
            if out['aux_price'] >= current:
                raise TradeError('卖出止损触发价须低于最新快照价格')
            if kind == 'STOP_LIMIT' and out['price'] > out['aux_price']:
                raise TradeError('卖出止损限价不得高于触发价')
        if kind in {'TRAILING_STOP', 'TRAILING_STOP_LIMIT'}:
            out['trail_type'] = data.get('trail_type', 'PERCENTAGE')
            if out['trail_type'] not in {'PRICE', 'PERCENTAGE'}:
                raise TradeError('移动止损类型不正确')
            out['trail_value'] = float(number(data.get('trail_value'), '移动距离'))
            if out['trail_type'] == 'PERCENTAGE' and out['trail_value'] >= 100:
                raise TradeError('移动止损百分比必须小于 100')
            if out['trail_type'] == 'PERCENTAGE' and Decimal(str(out['trail_value'])) != Decimal(str(out['trail_value'])).quantize(Decimal('.01')):
                raise TradeError('移动止损百分比最多两位小数')
            if out['trail_type'] == 'PRICE' and out['trail_value'] >= current:
                raise TradeError('移动止损金额须低于当前价格')
            if out['trail_type'] == 'PRICE' and Decimal(str(out['trail_value'])) != Decimal(str(out['trail_value'])).quantize(Decimal('.0001')):
                raise TradeError('移动止损金额最多四位小数')
            if kind == 'TRAILING_STOP_LIMIT':
                out['trail_spread'] = price(data.get('trail_spread'), '限价偏移')
                if Decimal(str(out['trail_spread'])) != Decimal(str(out['trail_spread'])).quantize(Decimal('.001')):
                    raise TradeError('限价偏移最多三位小数')
        out['reference_price'] = out['price'] if kind == 'NORMAL' else current
        if is_option:
            for field in ('price','aux_price'):
                if field in out and Decimal(str(out[field])) != Decimal(str(out[field])).quantize(Decimal('.01')):
                    raise TradeError('美股期权价格最多两位小数')
        out['estimate'] = round(out['reference_price'] * out['qty'] * multiplier, 2)
        if out['estimate'] > self.max_notional:
            raise TradeError(f'单笔估算金额超过 ${self.max_notional:g} 上限')
        if data.get('protection') is not None:
            if env != 'REAL' or side != 'BUY' or kind not in {'NORMAL', 'MARKET'} or session != 'RTH' or tif != 'DAY':
                raise TradeError('成交后自动止损仅支持实盘、常规时段、当日有效的买入单')
            if q.get('market_state') != 'AFTERNOON':
                raise TradeError('请在美股常规交易时段提交带自动止损的买单')
            out['protection'] = stop_config(data['protection'])
            if is_option:
                out['protection']['option']=True
                tolerance=Decimal(str(out['protection']['tolerance']))
                if tolerance!=tolerance.quantize(Decimal('.01')):
                    raise TradeError('期权止损容限最多两位小数')
            trigger,_=stop_prices(out['reference_price'], out['protection'])
            if is_option and trigger>=min(current,out['reference_price']):
                raise TradeError('期权止损触发价须低于最新快照和买入限价')
        return out

    def check_capacity(self, order, existing=None):
        acc, env = order['acc_id'], order['env']
        cap = self.broker.capacity(order, existing['order_id'] if existing else None)
        remaining = order['qty'] - (float(existing.get('dealt_qty', 0)) if existing else 0)
        if remaining <= 0:
            raise TradeError('订单数量须大于已成交数量')
        if order['side'] == 'BUY':
            if (order['qty'] if existing else remaining) > float(cap.get('max_cash_buy') or 0):
                raise TradeError('现金购买能力不足；第一版不启用融资买入')
        else:
            pos = next((p for p in self.broker.positions(acc, env) if p['code'] == order['code']), None)
            if not pos or float(pos.get('qty') or 0) <= 0 or pos.get('position_side') == 'SHORT':
                raise TradeError('没有可卖出的多头持仓；第一版不允许做空')
            available = float(pos.get('can_sell_qty') or 0)
            if order.get('close_position'):
                if existing or float(pos['qty']) != order['qty']:
                    raise TradeError('持仓数量已变化或含碎股，请重新打开平仓面板')
                if available < float(pos['qty']):
                    raise TradeError('已有卖单或止损占用持仓，不能完整平仓；请先在订单中处理并确认撤单完成')
                pending_buys = [r for r in self.broker.orders(acc, env) if r.get('code') == order['code']
                                and r.get('trd_side') == 'BUY' and r.get('order_status') in ACTIVE]
                if pending_buys:
                    raise TradeError('该股仍有未结束的买单，可能继续增加持仓；请先撤销并确认买单结束')
            if existing:
                available += max(0, float(existing['qty']) - float(existing.get('dealt_qty', 0)))
            if remaining > available or (order['qty'] if existing else remaining) > float(cap.get('max_position_sell') or 0):
                raise TradeError('可卖数量不足，已有卖单/止损单可能占用了持仓；请先检查订单')

    def find_order(self, acc, env, order_id):
        rows = self.broker.orders(acc, env)
        order = next((r for r in rows if str(r['order_id']) == str(order_id)), None)
        if not order or not SYMBOL.fullmatch(str(order.get('code', ''))):
            raise TradeError('找不到该账号的美股订单')
        if order.get('order_status') not in ACTIVE:
            raise TradeError('订单已结束或状态不允许操作')
        return order

    def preview(self, owner, data):
        kind = data.get('action', 'PLACE')
        if kind not in {'PLACE', 'MODIFY', 'CANCEL'}:
            raise TradeError('不支持的操作')
        acc, env = str(data.get('acc_id', '')), data.get('env')
        self.authorize(owner, acc, env)
        existing = None
        if kind == 'PLACE':
            order = self.normalize(data)
        else:
            existing = self.find_order(acc, env, data.get('order_id'))
            if kind == 'CANCEL':
                order = dict(acc_id=acc, env=env, order_id=str(existing['order_id']),
                             code=existing['code'], side=existing['trd_side'], qty=existing['qty'],
                             price=existing['price'], order_type=existing['order_type'])
            else:
                if existing['order_type'] not in {'NORMAL', 'STOP', 'STOP_LIMIT'}:
                    raise TradeError('第一版只支持限价及固定止损改单；其他类型请撤单后重设')
                session = existing.get('session')
                if session not in {'RTH', 'ETH', 'OVERNIGHT', 'ALL'}:
                    raise TradeError('无法确认原订单交易时段，请在 moomoo 客户端修改')
                order = self.normalize({**data, 'code': existing['code'], 'side': existing['trd_side'],
                    'order_type': existing['order_type'], 'session': session,
                    'time_in_force': existing.get('time_in_force', 'DAY')})
                order['order_id'] = str(existing['order_id'])
                if 'protection' in order:
                    raise TradeError('已有订单不能通过改单追加自动止损方案')
        if kind != 'CANCEL':
            self.check_capacity(order, existing)
        token = secrets.token_urlsafe(24)
        item = dict(owner=owner, expires=time.time() + 20, action=kind, order=order,
                    original=existing, preview_id=token)
        self.previews[token] = item
        return {k: v for k, v in item.items() if k not in {'owner', 'original'}}

    def operation(self, op_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM operations WHERE id=?', (op_id,)).fetchone()
        if not row:
            return None
        return {**dict(row), 'payload': json.loads(row['payload']),
                'result': json.loads(row['result']) if row['result'] else None}

    def journal(self, acc, env):
        self.account(acc, env)
        with self.db() as db:
            rows = db.execute("SELECT id FROM operations ORDER BY (state IN ('UNKNOWN','SENDING')) DESC, created DESC LIMIT 100").fetchall()
        return [r for x in rows if (r := self.operation(x['id']))['payload']['acc_id'] == str(acc)
                and r['payload']['env'] == env]

    def rate(self):
        now = time.monotonic()
        while self.rates and now - self.rates[0] >= 30:
            self.rates.popleft()
        if len(self.rates) >= 12:
            raise TradeError('操作过于频繁，请稍后再试；已为券商限频预留余量')
        if self.rates and now - self.rates[-1] < .05:
            time.sleep(.05)
        self.rates.append(time.monotonic())

    def commit(self, owner, preview_id, op_id, strategy_arm=None):
        if not re.fullmatch(r'[a-f0-9-]{32,36}', op_id):
            raise TradeError('操作编号无效')
        previous = self.operation(op_id)
        if previous:
            if previous['owner'] != owner:
                raise TradeError('此操作属于另一登录会话')
            return previous
        preview = self.previews.get(preview_id)
        if not preview or preview['owner'] != owner or preview['expires'] <= time.time():
            raise TradeError('预览已过期，请重新核对订单')
        order, kind = preview['order'], preview['action']
        self.authorize(owner, order['acc_id'], order['env'])
        with self.db() as db:
            pending = db.execute("SELECT payload FROM operations WHERE state IN ('UNKNOWN','SENDING')").fetchall()
        unknown = [p for row in pending if (p := json.loads(row['payload']))['acc_id'] == order['acc_id'] and p['env'] == order['env']]
        if unknown:
            raise TradeError('此账号有结果待核对的操作，请先核对流水，避免重复下单')
        existing = None
        if kind != 'PLACE':
            existing = self.find_order(order['acc_id'], order['env'], order['order_id'])
            old = preview['original']
            if any(existing.get(k) != old.get(k) for k in ('qty', 'price', 'aux_price', 'order_type', 'trd_side')):
                raise TradeError('订单已被修改，请重新预览')
        if kind != 'CANCEL':
            # Re-evaluate prices, symbol type and limits at the actual point of submission.
            self.quote_cache.pop(order['code'], None)
            checked = self.normalize(order)
            if order['order_type'] == 'MARKET' and abs(checked['reference_price'] / order['reference_price'] - 1) > .01:
                raise TradeError('市价参考价格变化超过 1%，请重新预览')
            order = {**order, **checked}
            self.check_capacity(order, existing)
        # Expiration and grants are checked again after all remote reads.
        self.authorize(owner, order['acc_id'], order['env'])
        if preview['expires'] <= time.time():
            raise TradeError('校验耗时较长，预览已过期，请重新预览')
        if strategy_arm is not None and (strategy_arm.get('cancelled') or strategy_arm['expires']<=time.time()):
            raise TradeError('策略授权已取消或到期，未提交')
        self.rate()
        if strategy_arm is not None and (strategy_arm.get('cancelled') or strategy_arm['expires']<=time.time()):
            raise TradeError('策略授权已取消或到期，未提交')
        with self.db() as db:
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?)',
                       (op_id, owner, kind, json.dumps(order), 'SENDING', None, time.time()))
            self.create_protection(op_id, owner, order, db)
        self.previews.pop(preview_id, None)
        try:
            result = self.broker.place(order, 'NMT:' + op_id) if kind == 'PLACE' else self.broker.modify(order, kind == 'CANCEL')
            state = 'ACCEPTED'
        except BrokerRejected as exc:
            state, result = 'REJECTED', {'message': str(exc)}
        except BrokerUncertain as exc:
            state, result = 'UNKNOWN', {'message': f'OpenD 未明确确认：{exc}。请核对券商订单，不会自动重发。'}
        except Exception:
            state, result = 'UNKNOWN', {'message': '连接异常，结果待核对。系统不会自动重发此操作。'}
        with self.db() as db:
            db.execute('UPDATE operations SET state=?,result=? WHERE id=?', (state, json.dumps(result), op_id))
        return self.operation(op_id)

    def reconcile(self, op_id):
        op = self.operation(op_id)
        if not op:
            raise TradeError('找不到操作流水')
        order = op['payload']
        self.account(order['acc_id'], order['env'])
        rows = self.broker.orders(order['acc_id'], order['env'])
        match = None
        if op['kind'] == 'PLACE':
            match = next((r for r in rows if r.get('remark') == 'NMT:' + op_id), None)
        else:
            r = next((r for r in rows if str(r['order_id']) == order['order_id']), None)
            if r:
                if op['kind'] == 'CANCEL' and r.get('order_status') in {'CANCELLED_ALL', 'CANCELLED_PART', 'FILLED_ALL'}:
                    match = r
                if op['kind'] == 'MODIFY' and all(float(r.get(k) or 0) == float(order.get(k) or 0)
                        for k in ('qty', 'price', 'aux_price')):
                    match = r
        if match and op['state'] in {'UNKNOWN', 'SENDING'}:
            with self.db() as db:
                db.execute("UPDATE operations SET state='RECONCILED',result=? WHERE id=?", (json.dumps([match]), op_id))
        return self.operation(op_id)

    def acknowledge_unknown(self, op_id, confirmation):
        op = self.operation(op_id)
        if not op or op['state'] != 'UNKNOWN' or time.time() - op['created'] < 60:
            raise TradeError('请至少等待一分钟并先核对券商订单')
        if confirmation != f'已在moomoo核对 {op_id}':
            raise TradeError('请完整输入核对确认文字')
        with self.db() as db:
            db.execute("UPDATE operations SET state='MANUALLY_REVIEWED' WHERE id=?", (op_id,))
        return self.operation(op_id)

    def strategy_authorize(self, owner, acc, env):
        self.authorize(owner, acc, env)
        return {'expires': self.grant['expires'] if env == 'REAL' else time.time()+600}

    def strategy_execute(self, owner, config, side, signal, arm):
        from .strategy_execution import execute_strategy
        return execute_strategy(self, owner, config, side, signal, arm)

    def preferences(self, value=None):
        if value is not None:
            if not isinstance(value.get('quantities'), list) or not isinstance(value.get('stops'), list):
                raise TradeError('快捷设置格式不正确')
            quantities = [float(number(n, '快捷股数')) for n in value['quantities']]
            stops = [float(number(n, '止损比例')) for n in value['stops']]
            if not 1 <= len(quantities) <= 6 or not 1 <= len(stops) <= 5 or any(n != int(n) or n > self.max_shares for n in quantities) or any(n >= 100 for n in stops):
                raise TradeError('快捷数量或比例超出范围')
            templates = value.get('templates', [])
            if not isinstance(templates, list) or len(templates) > 8:
                raise TradeError('最多保存八个命名方案')
            validated = []
            for item in templates:
                config = stop_config(item)
                qty = number(item.get('qty'), '方案股数')
                if qty != int(qty) or qty > self.max_shares:
                    raise TradeError('方案股数须为允许范围内的整股')
                validated.append({**config, 'qty': int(qty)})
            option_quantities = value.get('option_quantities', self.preferences().get('option_quantities', [1, 2, 5]))
            if not isinstance(option_quantities, list) or not 1 <= len(option_quantities) <= 6:
                raise TradeError('期权快捷数量须为 1 至 6 个正整数')
            option_quantities = [float(number(n, '期权张数')) for n in option_quantities]
            if any(n != int(n) or n > min(self.max_shares, 100) for n in option_quantities):
                raise TradeError('期权快捷张数超出允许范围')
            value = dict(quantities=quantities, stops=stops, templates=validated, option_quantities=option_quantities)
        with self.db() as db:
            if value is not None:
                encoded = json.dumps(value)
                if len(encoded) > 12000:
                    raise TradeError('快捷设置过大')
                db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', ('presets', encoded))
            row = db.execute('SELECT value FROM preferences WHERE key=?', ('presets',)).fetchone()
        result = json.loads(row[0]) if row else {'quantities': [10, 50, 100], 'stops': [1, 2.5, 3]}
        result.setdefault('option_quantities', [1, 2, 5])
        result.setdefault('templates', [dict(name='开盘 10 股 · 2.5% 止损', qty=10, percent=2.5, mode='STOP', tolerance=0)])
        return result
