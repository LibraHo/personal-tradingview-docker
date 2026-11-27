"""OpenD adapter for normalized market data and live subscriptions."""
import math
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .depth import DepthFeed
from .hour_bars import aggregate_hours, hour_bucket, is_us_hour
from .market_flow import option_profile, quote_result
from .opend_connection import connect_quote_context
from .opend_chips import ChipPages, request_page
from .market_data import QuotePermissionError, normalize_bar
from .stock_search import search_directory

ET = ZoneInfo('America/New_York')
CN_TZ = ZoneInfo('Asia/Shanghai')
HOST = os.getenv('OPEND_HOST','host.docker.internal')
PORT = int(os.getenv('OPEND_PORT','11111'))
MAX_STREAMS = int(os.getenv('MAX_ACTIVE_STREAMS','32'))
MODES = {'all':'ALL','extended':'ETH','regular':'RTH'}
PERIODS = {'1m': 'K_1M', '5m': 'K_5M', '15m': 'K_15M', '30m': 'K_30M', '60m': 'K_60M', '120m': 'K_120M', '240m': 'K_240M', '1d': 'K_DAY', '1w': 'K_WEEK', '1mo': 'K_MON'}
LONG_PERIODS = {'1d','1w','1mo'}


def opend_kline(symbol, period):
    # Current OpenD returns two half-day candles for CN K_240M.
    # Four trading hours in CN therefore use the native daily candle.
    if is_us_hour(symbol, period):
        return 'K_60M'
    return 'K_DAY' if symbol.startswith(('SH.', 'SZ.')) and period == '240m' else PERIODS[period]


def subscription_key(key):
    return key[0], opend_kline(key[0], key[1])


def push_matches(key, symbol, period):
    return key[0] == symbol and opend_kline(key[0], key[1]) == PERIODS[period]


def period_from_push(value):
    label=str(value).replace('K_','').lower()
    return label if label in PERIODS else {'day':'1d','week':'1w','mon':'1mo'}.get(label)

def frame_to_bars(frame, symbol):
    result = []
    zone = ET if symbol.startswith('US.') else CN_TZ
    for record in frame.to_dict('records'):
        dt = datetime.strptime(str(record['time_key']), '%Y-%m-%d %H:%M:%S').replace(tzinfo=zone)
        result.append(normalize_bar({**record, 'time': int(dt.timestamp())}))
    return result


class OpenDMarket:
    source_id = 'opend'
    adjustments = ('none', 'qfq', 'hfq')
    live_adjustments = ('qfq',)

    bar_label = os.getenv('OPENING_RANGE_BAR_LABEL', 'end')
    bar_profiles = {'qfq':'opend-qfq-v1', 'none':'opend-raw-v1', 'hfq':'opend-hfq-v1'}

    def cache_revision(self, symbol, period):
        return f'hours2-{self.bar_label}' if is_us_hour(symbol, period) else ''

    def time_label(self, symbol, period):
        return 'start' if is_us_hour(symbol, period) else self.bar_label

    def __init__(self, connect_db, listeners, on_error=None):
        self.connect_db = connect_db
        self.listeners = listeners
        self.on_error = on_error
        self.sinks = {}
        self.hours_lock = threading.RLock()
        self.native_hours = {}
        self.depth_feed = DepthFeed()
        self.ticker_feed = DepthFeed('TICKER')
        self.ctx = None
        self.lock = threading.RLock()
        self.refreshing_directories = frozenset()
        self.active: dict[tuple[str, str, str], float] = {}
        self.last_error = None
        self.last_request = 0.0
        self.last_activity = time.monotonic()
        self.snapshot_cache: dict[tuple[str, ...], tuple[float, list[dict]]] = {}
        self.permission_errors = {}
        self.live_sessions = {}
        self.basis_errors = set()
        self.chip_pages = ChipPages()

    def chip_summary(self, market, offset, limit):
        def fetch(market, offset, limit):
            with self.lock:
                self.rate_limit()
                page = request_page(self.ensure(), market, offset, limit)
                self.last_activity = time.monotonic()
                return page
        return self.chip_pages.get(market, offset, limit, fetch)

    @staticmethod
    def permission_market(symbol):
        return 'CN' if symbol.startswith(('SH.', 'SZ.')) else symbol.split('.')[0]

    def check_permission(self, symbol):
        market = self.permission_market(symbol)
        error = self.permission_errors.get(market)
        if error and error['until'] > time.time():
            raise QuotePermissionError(error['message'])
        self.permission_errors.pop(market, None)

    def raise_quote_error(self, symbol, error):
        message = str(error)
        if '无权限' in message or 'permission' in message.lower() or 'no quote right' in message.lower():
            market = self.permission_market(symbol)
            hint = ('OpenD 当前没有 A 股行情权限，已保留 NAS 缓存；请检查 OpenD 行情授权及登录网络地区。'
                    if market == 'CN' else 'OpenD 当前没有该市场的行情权限，已保留 NAS 缓存。')
            self.permission_errors[market] = {'until': time.time()+300, 'message': hint, 'detail': message}
            raise QuotePermissionError(hint)
        raise RuntimeError(message)

    def rate_limit(self):
        delay = 0.52 - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()

    def ensure(self):
        if self.ctx is not None:
            return self.ctx
        from moomoo import OpenQuoteContext, CurKlineHandlerBase, RET_OK, SysConfig
        rsa_file = os.getenv('OPEND_RSA_FILE', '')
        if rsa_file:
            SysConfig.enable_proto_encrypt(True)
            SysConfig.set_init_rsa_file(rsa_file)
        bridge = self
        class Handler(CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK:
                    for (symbol, kind), frame in data.groupby(['code', 'k_type']):
                        period = period_from_push(kind)
                        if not period:
                            continue
                        keys = [key for key in list(bridge.active) if push_matches(key, symbol, period)]
                        if rsp_pb.s2c.rehabType != 1:
                            bridge.basis_errors.update(keys)
                            bridge.last_error = '推送复权口径不一致，已暂停推送并改用历史刷新'
                            for key in keys:
                                if bridge.on_error:
                                    bridge.on_error(key, bridge.last_error)
                            continue
                        bridge.basis_errors.difference_update(keys)
                        bars = frame_to_bars(frame, symbol)
                        for key in keys:
                            sink = bridge.sinks.get(key)
                            if sink is not None:
                                sink(bridge.live_rows(key, bars))
                return ret, data
        self.ctx = connect_quote_context(OpenQuoteContext,host=HOST,port=PORT,is_encrypt=bool(rsa_file))
        self.ctx.set_handler(Handler())
        self.last_error = None
        return self.ctx

    def reset(self, message):
        self.last_error = str(message)
        if self.ctx:
            try:
                self.ctx.close()
            except Exception:
                pass
        self.ctx = None
        self.active.clear()
        self.live_sessions.clear()
        self.basis_errors.clear()

    def fetch_bars(self, key, days, end_date, adjustment):
        from moomoo import KLType, AuType, Session, RET_OK
        with self.lock:
            self.check_permission(key[0])
            try:
                ctx = self.ensure()
                end = end_date or datetime.now(ET if key[0].startswith('US.') else CN_TZ).date()
                start = end - timedelta(days=days)
                kwargs = dict(code=key[0], start=str(start), end=str(end), ktype=getattr(KLType, opend_kline(key[0], key[1])),
                              autype=getattr(AuType, adjustment.upper()), max_count=1000, session=Session.NONE if key[1] in LONG_PERIODS or not key[0].startswith('US.') else getattr(Session, MODES[key[2]]))
                all_bars, page = [], None
                while True:
                    self.rate_limit()
                    ret, data, page = ctx.request_history_kline(**kwargs, page_req_key=page)
                    if ret != RET_OK:
                        self.raise_quote_error(key[0], data)
                    all_bars.extend(frame_to_bars(data, key[0]))
                    if page is None:
                        break
                if is_us_hour(key[0], key[1]):
                    # Retain the in-progress native candles for the next 2h/4h push.
                    if key in self.sinks and end_date is None and adjustment == 'qfq':
                        self.remember_hours(key, all_bars)
                    all_bars = aggregate_hours(all_bars, key[1], self.bar_label)
                self.last_activity = time.monotonic()
                return all_bars
            except QuotePermissionError:
                raise
            except Exception as exc:
                self.reset(exc)
                raise

    def snapshots(self, symbols):
        from moomoo import RET_OK
        key = tuple(sorted(set(symbols)))
        with self.lock:
            cached = self.snapshot_cache.get(key)
            if cached and time.monotonic() - cached[0] < 15:
                return cached[1], False
            try:
                ctx = self.ensure()
                self.rate_limit()
                ret, data = ctx.get_market_snapshot(list(key))
                if ret != RET_OK:
                    raise RuntimeError(str(data))
                def number(row, field):
                    value = row.get(field)
                    try:
                        value = float(value)
                        return value if math.isfinite(value) else None
                    except (TypeError, ValueError):
                        return None
                items = []
                for row in data.to_dict('records'):
                    price = number(row, 'last_price')
                    previous = number(row, 'prev_close_price')
                    items.append({
                        'symbol': str(row['code']), 'name': str(row.get('name') or ''),
                        'price': price,
                        'change_percent': round((price / previous - 1) * 100, 2) if price is not None and previous and previous > 0 else None,
                        'pre_price': number(row, 'pre_price'), 'pre_change_percent': number(row, 'pre_change_rate'),
                        'after_price': number(row, 'after_price'), 'after_change_percent': number(row, 'after_change_rate'),
                        'overnight_price': number(row, 'overnight_price'), 'overnight_change_percent': number(row, 'overnight_change_rate'),
                        'update_time': str(row.get('update_time') or ''),
                    })
                self.snapshot_cache[key] = (time.monotonic(), items)
                self.last_activity = time.monotonic()
                return items, False
            except Exception as exc:
                self.last_error = str(exc)
                if cached:
                    return cached[1], True
                raise

    def depth(self, symbol):
        return self.depth_feed.read(symbol)

    def ticks(self, symbol):
        return self.ticker_feed.read_ticks(symbol)

    def option_profile(self, symbol, expiry):
        with self.lock:
            ctx = self.ensure()
            if expiry:
                return {'rows': option_profile(ctx, symbol, expiry, self.rate_limit)}
            self.rate_limit()
            rows = quote_result(ctx.get_option_expiration_date(symbol))
            today = datetime.now(ET).date().isoformat()
            return {'expirations': sorted({r['strike_time'] for r in rows if r['strike_time'] >= today})}

    def search_symbols(self, query, limit=12, market='CN'):
        return search_directory(self, self.connect_db, query, limit, market)

    def cached_names(self, symbols):
        with self.connect_db() as db:
            rows = db.execute('SELECT * FROM symbol_names WHERE symbol IN ('+','.join('?' for _ in symbols)+')', symbols)
            cached = {row['symbol']: row for row in rows}
        cutoff = time.time() - 86400
        missing = [s for s in symbols if s not in cached or cached[s]['updated'] < cutoff]
        return {s: row['name'] for s, row in cached.items()}, missing

    def names(self, symbols):
        result, missing = self.cached_names(symbols)
        if not missing:
            return result
        from moomoo import RET_OK
        with self.lock:
            # Another request may have populated these names while this one waited.
            found, missing = self.cached_names(missing)
            result.update(found)
            for market in ('SH', 'SZ', 'US'):
                codes = [code for code in missing if code.startswith(market+'.')]
                if not codes:
                    continue
                try:
                    self.rate_limit()
                    ret, frame = self.ensure().get_stock_basicinfo(market=market, code_list=codes)
                    if ret != RET_OK:
                        continue
                    rows = [(str(r['code']), str(r.get('name') or ''), time.time()) for r in frame.to_dict('records') if r.get('name')]
                    with self.connect_db() as db:
                        db.executemany('INSERT OR REPLACE INTO symbol_names VALUES(?,?,?)', rows)
                    result.update({code:name for code,name,_ in rows})
                    self.last_activity = time.monotonic()
                except Exception:
                    continue
            return result

    def watchlists(self):
        from moomoo import RET_OK, UserSecurityGroupType
        with self.lock:
            ctx = self.ensure()
            self.rate_limit()
            ret, data = ctx.get_user_security_group(UserSecurityGroupType.ALL)
            if ret != RET_OK:
                raise RuntimeError(str(data))
            groups = []
            for row in data.to_dict('records'):
                name, kind = str(row['group_name']), str(row['group_type'])
                # Market-wide system categories are not personal watchlists.
                if kind != 'CUSTOM' and name != 'Favorites':
                    continue
                # The OpenD watchlist endpoint has a stricter request quota.
                time.sleep(max(0, 3.2 - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                ret, stocks = ctx.get_user_security(name)
                if ret != RET_OK:
                    raise RuntimeError(f'{name}: {stocks}')
                codes = list(dict.fromkeys(str(item['code']) for item in stocks.to_dict('records')))
                groups.append({'name': name, 'kind': kind, 'symbols': codes})
            self.last_activity = time.monotonic()
            return groups

    def subscribe(self, key):
        from moomoo import SubType, Session, RET_OK
        with self.lock:
            self.check_permission(key[0])
            if key in self.active:
                return
            if len(self.active) >= MAX_STREAMS:
                raise RuntimeError('实时订阅已达到本服务配置的上限')
            rank={'regular':0,'extended':1,'all':2}
            prior=self.live_sessions.get(subscription_key(key))
            if prior is not None and rank[prior]>=rank[key[2]]:
                self.active[key]=time.monotonic()
                self.last_activity=time.monotonic()
                return
            try:
                ctx = self.ensure()
                self.rate_limit()
                session = Session.NONE if not key[0].startswith('US.') or key[1] in LONG_PERIODS else getattr(Session, MODES[key[2]])
                ret, error = ctx.subscribe([key[0]], [getattr(SubType, opend_kline(key[0], key[1]))], session=session, subscribe_push=True)
                if ret != RET_OK:
                    self.raise_quote_error(key[0], error)
                self.active[key] = time.monotonic()
                self.live_sessions[subscription_key(key)]=key[2]
                self.last_activity = time.monotonic()
            except QuotePermissionError:
                raise
            except Exception as exc:
                self.reset(exc)
                raise

    def unsubscribe_unused(self):
        if not self.active:
            return
        from moomoo import SubType
        with self.lock:
            for key, start in list(self.active.items()):
                if self.listeners.get(key) or time.monotonic()-start < 65:
                    continue
                if any(other!=key and subscription_key(other)==subscription_key(key) for other in self.active):
                    self.active.pop(key,None)
                    continue
                try:
                    self.rate_limit()
                    ret, error = self.ctx.unsubscribe([key[0]], [getattr(SubType, opend_kline(key[0], key[1]))])
                    if ret != 0:
                        raise RuntimeError(str(error))
                except Exception as exc:
                    self.reset(exc)
                    break
                self.active.pop(key, None)
                self.live_sessions.pop(subscription_key(key),None)
                self.last_activity = time.monotonic()

    def close_if_idle(self):
        with self.lock:
            if self.ctx is not None and not self.active and time.monotonic()-self.last_activity > 15:
                self.ctx.close()
                self.ctx = None



    def remember_hours(self, key, bars):
        # Only the open bucket and its predecessors are needed for a native push.
        with self.hours_lock:
            series = self.native_hours.setdefault(key, {})
            series.update((bar['time'], bar) for bar in bars[-12:])
            for stamp in sorted(series)[:-12]:
                del series[stamp]
            return list(series.values())

    def live_rows(self, key, bars):
        if not is_us_hour(*key[:2]):
            return bars
        native = self.remember_hours(key, bars)
        touched = {hour_bucket(bar['time'], key[1], self.bar_label) for bar in bars}
        return [b for b in aggregate_hours(native, key[1], self.bar_label) if b['time'] in touched]

    def subscribe_bars(self, key, adjustment, emit):
        if adjustment not in self.live_adjustments:
            raise ValueError('OpenD 实时 K 线需要前复权')
        with self.lock:
            self.sinks[key] = emit
            try:
                if is_us_hour(*key[:2]):
                    self.fetch_bars(key, 2, None, adjustment)
                self.subscribe(key)
            except Exception:
                self.sinks.pop(key, None)
                raise

        def cancel():
            with self.lock:
                self.sinks.pop(key, None)
                with self.hours_lock:
                    self.native_hours.pop(key, None)
                self.unsubscribe_unused()
        return cancel

    def is_subscribed(self, key):
        return key in self.active

    def stream_healthy(self, key):
        return key in self.active and key not in self.basis_errors

    def retry(self, symbol):
        with self.lock:
            self.permission_errors.pop(self.permission_market(symbol), None)

    def cleanup(self):
        self.depth_feed.cleanup()
        self.ticker_feed.cleanup()
        self.close_if_idle()

    def close(self):
        self.depth_feed.close()
        self.ticker_feed.close()
        with self.lock:
            if self.ctx:
                self.ctx.close()
                self.ctx = None
            self.active.clear()
            self.live_sessions.clear()
            self.sinks.clear()
            with self.hours_lock:
                self.native_hours.clear()
