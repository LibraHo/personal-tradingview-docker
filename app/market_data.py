"""Canonical market-data contract. Adapters translate vendor symbols, times and units."""
import json
import math
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from importlib import import_module
from typing import Protocol

ADJUSTMENTS = {'none': '不复权', 'qfq': '前复权', 'hfq': '后复权'}


FEATURE_LABELS = {'snapshots':'报价快照','depth':'盘口深度','ticks':'逐笔成交',
                  'option_profile':'期权成交分布','search_symbols':'证券搜索','catalog':'板块目录',
                  'members':'板块成分','heatmap':'板块热力图','emotion':'涨跌分布','trading_days':'交易日历','watchlists':'自选分组','fetch_bars':'历史 K 线','limit_pool':'涨跌停池','chip_summary':'筹码汇总快照'}


class QuotePermissionError(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    source_id: str
    adjustments: tuple[str, ...]
    live_adjustments: tuple[str, ...]

    def fetch_bars(self, key: tuple[str, str, str], days: int,
                   end_date: date | None, adjustment: str) -> list[dict]:
        """UTC seconds, OHLC, volume in shares and turnover in quote currency."""
        ...

    def snapshots(self, symbols: list[str]) -> tuple[list[dict], bool]:
        """Actual quoted prices, keyed by canonical symbol, and a stale flag."""
        ...


def finite_number(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def optional_number(value):
    number = finite_number(value)
    return number if number is not None and number >= 0 else None


def historical_chip_fields(distribution, key, adjustment, timestamp, close):
    """Convert a matched, discrete price/share histogram into per-bar formula inputs."""
    if not isinstance(distribution, dict) or key is None:
        return {}
    if ((distribution.get('symbol'), distribution.get('period'), distribution.get('mode')) != key
            or distribution.get('time') != timestamp or distribution.get('adjustment') != adjustment):
        return {}
    levels = distribution.get('levels')
    if not isinstance(levels, list) or not levels:
        return {}
    prices = []
    for point in levels:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            return {}
        price, shares = point
        if (type(price) not in (float, int) or not math.isfinite(price) or price <= 0
                or type(shares) is not int or shares < 0):
            return {}
        prices.append((price, shares))
    total = sum(shares for _, shares in prices)
    if total == 0:
        return {}
    threshold = Decimal(str(close)) * Decimal('0.95')
    profitable = sum(shares for price, shares in prices if Decimal(str(price)) < threshold)
    cumulative = 0
    for price, shares in sorted(prices):
        cumulative += shares
        if cumulative * 100 >= 85 * total:
            return {'chip_winner_95': profitable / total, 'chip_cost_85': price}


def normalize_bar(row, key=None, adjustment=None):
    bar = {field: float(row[field]) for field in ('open', 'high', 'low', 'close')}
    if not all(math.isfinite(x) for x in bar.values()):
        raise ValueError('行情源返回了无效 OHLC 价格')
    stamp = row['time']
    if not isinstance(stamp, int) or not 0 < stamp < 10000000000:
        raise ValueError('K 线时间须为 UTC Unix 秒')
    fields = {}
    for name, value in row.get('fields', {}).items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name):
            raise ValueError('扩展行情字段名无效')
        fields[name] = value if type(value) in (float, int) and math.isfinite(value) else None
    if 'chip_distribution' in row:
        for field in ('chip_winner_95', 'chip_cost_85'):
            fields.pop(field, None)
        fields.update(historical_chip_fields(row['chip_distribution'], key, adjustment, stamp, bar['close']))
    winner = fields.get('chip_winner_95')
    cost = fields.get('chip_cost_85')
    if winner is not None and not 0 <= winner <= 1:
        fields['chip_winner_95'] = None
    if cost is not None and cost <= 0:
        fields['chip_cost_85'] = None
    return dict(bar, time=stamp, fields=fields, volume=optional_number(row.get('volume')),
                turnover=optional_number(row.get('turnover')))


class MarketData:
    def __init__(self, provider: MarketDataProvider, adjustment, save, *, history=True):
        if not re.fullmatch(r'[a-z0-9_-]{1,64}', provider.source_id):
            raise ValueError('行情源需要稳定的 source_id')
        if adjustment not in ADJUSTMENTS or history and adjustment not in getattr(provider, 'adjustments', ()):
            raise ValueError(f'{provider.source_id} 不支持复权口径 {adjustment}')
        self.provider = provider
        self._adjustment = ContextVar('price_adjustment', default=adjustment)
        self.save = save

    @property
    def adjustment(self):
        return self._adjustment.get()

    @contextmanager
    def using_adjustment(self, basis):
        if basis not in self.provider.adjustments:
            raise ValueError(f'{self.provider.source_id} 不支持{ADJUSTMENTS[basis]}')
        token = self._adjustment.set(basis)
        try:
            yield
        finally:
            self._adjustment.reset(token)

    def time_label(self, symbol, period):
        if not period.endswith('m') or (period == '240m' and not symbol.startswith('US.')):
            return 'date'
        per_series = getattr(self.provider, 'time_label', None)
        if per_series:
            return per_series(symbol, period)
        return getattr(self.provider, 'bar_label', 'start')

    def feature(self, name):
        method = getattr(self.provider, name, None)
        if not callable(method):
            raise ValueError(f'行情源 {self.provider.source_id} 未提供{FEATURE_LABELS.get(name, name)}')
        return method

    @property
    def live(self):
        return self.adjustment in getattr(self.provider, 'live_adjustments', ())

    def for_market(self, symbol_or_market, capability='history'):
        return self

    def metadata(self, symbol=None, period=None):
        return {'provider': self.provider.source_id, 'live_provider': self.provider.source_id, 'adjustment': self.adjustment,
                'adjustment_label': ADJUSTMENTS[self.adjustment], 'live_supported': self.live,
                'historical_chips': getattr(self.provider, 'historical_chips', False) is True}

    def history(self, key, days, end_date=None):
        rows = self.feature('fetch_bars')(key, days, end_date, self.adjustment)
        bars = [normalize_bar(row, key, self.adjustment) for row in rows]
        self.save(key, bars)
        return len(bars)

    def opening_five(self, symbol, day):
        key = (symbol, '5m', 'regular')
        return [normalize_bar(row, key, self.adjustment) for row in self.feature('fetch_bars')(
            key, 0, date.fromisoformat(day), self.adjustment)]

    def snapshots(self, symbols):
        rows, stale = self.feature('snapshots')(symbols)
        requested = set(symbols)
        result = []
        for row in rows:
            symbol = row.get('symbol')
            if symbol not in requested:
                raise ValueError('行情快照返回的证券代码与请求不符')
            quote = {'symbol': symbol, 'name': str(row.get('name') or ''),
                     'update_time': str(row.get('update_time') or '')}
            for field in ('price', 'change_percent', 'pre_price', 'pre_change_percent',
                          'after_price', 'after_change_percent', 'overnight_price', 'overnight_change_percent'):
                quote[field] = finite_number(row.get(field))
            result.append({**quote, 'provider':self.provider.source_id})
        return result, stale


def load_provider(setting, opend):
    if setting == 'opend':
        return opend
    module, sep, factory = setting.partition(':')
    if not sep:
        raise ValueError('MARKET_DATA_PROVIDER 须为 opend 或 module:factory')
    return getattr(import_module(module), factory)()

CAPABILITIES = ('history', 'live', 'snapshots', 'search_symbols', 'names', 'depth', 'ticks',
                'option_profile', 'catalog', 'members', 'heatmap', 'emotion', 'trading_days',
                'limit_pool', 'watchlists', 'chip_summary')


class DisabledFeed:
    source_id = 'disabled'
    adjustments = tuple(ADJUSTMENTS)
    live_adjustments = ()


def market_of(value):
    value = value.upper()
    if value == 'US' or value.startswith('US.'):
        return 'US'
    if value == 'CN' or value.startswith(('SH.', 'SZ.')):
        return 'CN'
    raise ValueError(f'无法确定行情市场 {value}')


class MarketRoutes:
    """Resolve each read before crossing a vendor boundary, including mixed-market batches."""
    def __init__(self, default, basis, config, builtins, save):
        if not isinstance(config, dict) or set(config) - {'*', 'US', 'CN'}:
            raise ValueError('MARKET_DATA_ROUTES 只接受 *, US, CN')
        for entry in config.values():
            if not isinstance(entry, dict) or set(entry) - {*CAPABILITIES, 'default', 'adjustment'}:
                raise ValueError('行情路由包含未知能力')
        self.routes = {}
        providers = {}
        identifiers = {}
        def resolve(setting):
            if not isinstance(setting, str) or not setting:
                raise ValueError('行情路由需要数据源名称或 module:factory')
            if setting not in providers:
                instance = builtins[setting] if setting in builtins else load_provider(setting, builtins['opend'])
                if instance.source_id in identifiers and identifiers[instance.source_id] is not instance:
                    raise ValueError(f'数据源标识重复：{instance.source_id}')
                identifiers[instance.source_id] = providers[setting] = instance
            return providers[setting]

        for market in ('US','CN'):
            settings = {**config.get('*', {}), **config.get(market, {})}
            base = settings.get('default', default)
            adjustment = settings.get('adjustment', basis)
            routes = {}
            for cap in CAPABILITIES:
                provider = resolve(settings.get(cap, base))
                if cap == 'limit_pool' and market == 'CN' and cap not in settings and not callable(getattr(provider, cap, None)):
                    provider = builtins['eastmoney']
                routes[cap] = MarketData(provider, adjustment, save, history=cap == 'history')
            self.routes[market] = routes

    def for_market(self, symbol_or_market, capability='history'):
        return self.routes[market_of(symbol_or_market)][capability]

    def configured_providers(self):
        providers = {}
        for routes in self.routes.values():
            for feed in routes.values():
                providers[feed.provider.source_id] = feed.provider
        return list(providers.values())

    def route_identities(self):
        return {market:{cap: feed.provider.source_id for cap,feed in routes.items()}
                for market,routes in self.routes.items()}

    @property
    def identity(self):
        identities = self.route_identities()
        for market in identities:
            identities[market]['adjustment'] = self.for_market(market).adjustment
        return json.dumps(identities, sort_keys=True, separators=(',',':'))

    def metadata(self, symbol, period=None):
        market = market_of(symbol)
        history = self.for_market(market)
        live = self.for_market(market, 'live')
        h, l = history.provider, live.provider
        basis = history.adjustment
        enabled = basis in getattr(l, 'live_adjustments', ()) and callable(getattr(l, 'subscribe_bars', None))
        reason = '' if enabled else f'{l.source_id} 未提供{ADJUSTMENTS[basis]}推送'
        if enabled and h is not l:
            hp = getattr(h, 'bar_profiles', {}).get(basis)
            lp = getattr(l, 'bar_profiles', {}).get(basis)
            if (not hp or hp != lp or getattr(h, 'bar_label', None) not in ('start', 'end')
                    or h.bar_label != getattr(l, 'bar_label', None)
                    or period and history.time_label(symbol, period) != live.time_label(symbol, period)):
                enabled = False
                reason = '历史与实时源的 K 线时间、复权或量价口径未确认兼容'
        return {**history.metadata(), 'live_provider':l.source_id,
                'live_supported':enabled, 'live_reason':reason}

    def history(self, key, days, end_date=None):
        return self.for_market(key[0]).history(key, days, end_date)

    def opening_five(self, symbol, day):
        return self.for_market(symbol).opening_five(symbol, day)

    def batches(self, symbols, capability):
        groups = {}
        for symbol in dict.fromkeys(symbols):
            feed = self.for_market(symbol, capability)
            groups.setdefault(feed.provider.source_id, []).append(symbol)
        return [(self.for_market(codes[0], capability), codes) for codes in groups.values()]

    def snapshots(self, symbols):
        rows, stale = {}, False
        for feed, codes in self.batches(symbols, 'snapshots'):
            batch, old = feed.snapshots(codes)
            rows.update((row['symbol'], row) for row in batch)
            stale |= old
        return [rows[s] for s in dict.fromkeys(symbols) if s in rows], stale


class ProviderStreams:
    """One vendor subscription per logical series, shared by all chart listeners."""
    def __init__(self, market, publish, listeners, limit):
        self.market, self.publish = market, publish
        self.listeners, self.limit = listeners, limit
        self.active = {}
        self.lock = threading.RLock()

    def subscribe(self, key):
        with self.lock:
            if not self.market.live:
                raise ValueError('当前行情源与复权口径只支持历史刷新')
            if key in self.active:
                subscribed = getattr(self.market.provider, 'is_subscribed', None)
                if subscribed is None or subscribed(key):
                    return
                cancel, _ = self.active.pop(key)
                cancel()
            if len(self.active) >= self.limit:
                raise ValueError('实时订阅已达到上限')
            basis = self.market.adjustment
            cancel = self.market.feature('subscribe_bars')(
                key, basis, lambda rows: self.publish(key, [normalize_bar(r, key, basis) for r in rows]))
            self.active[key] = (cancel, time.monotonic())

    def unsubscribe_unused(self):
        with self.lock:
            for key, (cancel, started) in list(self.active.items()):
                if not self.listeners.get(key) and time.monotonic() - started >= 65:
                    cancel()
                    del self.active[key]

    def close(self):
        with self.lock:
            for key, (cancel, _) in list(self.active.items()):
                cancel()
                del self.active[key]

class RoutedStreams:
    def __init__(self, routes, publish, listeners, limit):
        self.routes, self.limit = routes, limit
        self.lock = threading.RLock()
        self.last_error = None
        self.managers = {market:ProviderStreams(routes.for_market(market,'live'), publish, listeners, limit)
                         for market in ('US','CN')}

    @property
    def active(self):
        with self.lock:
            return {key for manager in self.managers.values() for key in manager.active}

    def connected(self, key):
        with self.lock:
            manager = self.managers[market_of(key[0])]
            healthy = getattr(manager.market.provider, 'stream_healthy', None)
            return key in manager.active and (healthy is None or healthy(key))

    def subscribe(self, key):
        with self.lock:
            meta = self.routes.metadata(*key[:2])
            if not meta['live_supported']:
                raise ValueError(meta['live_reason'])
            if key not in self.active and len(self.active) >= self.limit:
                raise ValueError('实时订阅已达到上限')
            self.managers[market_of(key[0])].subscribe(key)

    def unsubscribe_unused(self):
        with self.lock:
            for manager in self.managers.values():
                manager.unsubscribe_unused()

    def close(self):
        with self.lock:
            for manager in self.managers.values():
                manager.close()
