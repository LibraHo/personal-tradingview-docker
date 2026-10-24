"""On-demand US book snapshots. No trading context, no overnight recording."""
import math
import os
import threading
import time


def levels(book):
    result = []
    for key, side in [('Bid', 'buy'), ('Ask', 'sell')]:
        grouped = {}
        for row in book.get(key, [])[:60]:
            try:
                price, qty = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty <= 0:
                continue
            grouped[price] = grouped.get(price, 0) + qty
        result.extend(dict(side=side, price=p, qty=q, amount=round(p*q, 2)) for p, q in grouped.items())
    return result


class DepthFeed:
    def __init__(self):
        self.lock = threading.Lock()
        self.ctx = None
        self.subscriptions = {}
        self.cache = {}
        self.states = {}

    def ensure(self):
        if self.ctx is None:
            import moomoo as mm
            rsa = os.getenv('OPEND_RSA_FILE', '')
            if rsa:
                mm.SysConfig.enable_proto_encrypt(True)
                mm.SysConfig.set_init_rsa_file(rsa)
            self.ctx = mm.OpenQuoteContext(host=os.getenv('OPEND_HOST', 'host.docker.internal'),
                port=int(os.getenv('OPEND_PORT', '11111')), is_encrypt=bool(rsa))
        return self.ctx

    def read(self, symbol):
        import moomoo as mm
        with self.lock:
            now = time.monotonic()
            ctx = self.ensure()
            if symbol not in self.subscriptions:
                if len(self.subscriptions) >= 4:
                    raise ValueError('最多同时订阅四只股票的盘口，关闭其他盘口后约一分钟释放额度')
                ret, data = ctx.subscribe([symbol], [mm.SubType.ORDER_BOOK], subscribe_push=False,
                                          session=mm.Session.ALL)
                if ret != mm.RET_OK:
                    raise ValueError('盘口订阅失败：' + str(data)[:220])
                self.subscriptions[symbol] = [now, now]
            self.subscriptions[symbol][1] = now
            if symbol in self.cache and now-self.cache[symbol][0] < 2:
                return self.cache[symbol][1]
            try:
                ret, book = ctx.get_order_book(symbol, num=60)
                if ret != mm.RET_OK:
                    raise ValueError('盘口读取失败：' + str(book)[:220])
                stamp, state = self.states.get(symbol, (0, 'UNKNOWN'))
                if now-stamp > 10:
                    ret, data = ctx.get_market_state([symbol])
                    state = str(data.iloc[0]['market_state']) if ret == mm.RET_OK and len(data) else 'UNKNOWN'
                    self.states[symbol] = (now, state)
                data = dict(symbol=symbol, levels=levels(book), market_state=state,
                    active=state in {'AFTERNOON', 'PRE_MARKET_BEGIN', 'AFTER_HOURS_BEGIN', 'OVERNIGHT'},
                    read_at=time.time(), bid_count=len(book.get('Bid', [])), ask_count=len(book.get('Ask', [])),
                    source_time_bid=book.get('svr_recv_time_bid') or None,
                    source_time_ask=book.get('svr_recv_time_ask') or None)
                self.cache[symbol] = (now, data)
                return data
            except Exception:
                self.cache.pop(symbol, None)
                raise

    def cleanup(self):
        import moomoo as mm
        with self.lock:
            now = time.monotonic()
            for symbol, (start, used) in list(self.subscriptions.items()):
                if now-start >= 65 and now-used >= 65:
                    ret, _ = self.ctx.unsubscribe([symbol], [mm.SubType.ORDER_BOOK])
                    if ret == mm.RET_OK:
                        self.subscriptions.pop(symbol, None)
                        self.cache.pop(symbol, None)
                        self.states.pop(symbol, None)
            if self.ctx is not None and not self.subscriptions:
                self.ctx.close()
                self.ctx = None

    def close(self):
        with self.lock:
            if self.ctx is not None:
                self.ctx.close()
            self.ctx = None
            self.subscriptions.clear()
            self.cache.clear()
            self.states.clear()
