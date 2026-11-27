"""Read-only market radar using the existing OpenD connection and SQLite cache."""
import asyncio
import json
import math
import re
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo

BOARD = re.compile(r'^(?:SH|SZ|US)\.(?:BK|LIST)[0-9]{1,10}$')
SYMBOL = re.compile(r'^(?:US\.[A-Z0-9.]{1,12}|(?:SH|SZ)\.(?:[0-9]{6}|(?:BK|LIST)[0-9]{1,10}))$')
US_SECTORS = (
    ('XLK', '信息技术'), ('XLF', '金融'), ('XLE', '能源'), ('XLV', '医疗保健'),
    ('XLI', '工业'), ('XLY', '可选消费'), ('XLP', '必需消费'), ('XLC', '通信服务'),
    ('XLB', '原材料'), ('XLRE', '房地产'), ('XLU', '公用事业'),
)


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def distribution_summary(data):
    """Keep limit buckets separate: the upstream may also include them in ranges."""
    bins = []
    up = down = flat = 0
    limits = {'limit_up': None, 'limit_down': None}
    for row in data.get('range_list', []):
        count = finite(row.get('stock_count'))
        if count is None or count < 0:
            continue
        kind = str(row.get('type', ''))
        left, right = finite(row.get('left_border')), finite(row.get('right_border'))
        count = int(count)
        if kind in ('RISE_LIMIT', 'FALL_LIMIT'):
            limits['limit_up' if kind == 'RISE_LIMIT' else 'limit_down'] = count
            continue
        if kind == 'POSITIVE_INFINITY':
            label = f'>{left:g}%' if left is not None else '大幅上涨'
            up += count
        elif kind == 'NEGATIVE_INFINITY':
            label = f'<{right:g}%' if right is not None else '大幅下跌'
            down += count
        elif kind == 'NORMAL_RANGE' and left is not None and right is not None:
            label = '平盘' if left == right == 0 else f'{left:g}% ～ {right:g}%'
            if left == right == 0:
                flat += count
            elif left >= 0 and right > 0:
                up += count
            elif left < 0 and right <= 0:
                down += count
            else:
                # An interval crossing zero cannot be assigned to either side.
                bins.append({'label': label, 'count': count, 'side': 'unknown'})
                continue
        else:
            continue
        side = 'flat' if left == right == 0 and kind == 'NORMAL_RANGE' else 'up' if kind == 'POSITIVE_INFINITY' or (kind == 'NORMAL_RANGE' and left >= 0) else 'down'
        bins.append({'label': label, 'count': count, 'side': side})
    if not bins:
        raise ValueError('数据源未返回可用的涨跌分布')
    total = sum(row['count'] for row in bins)
    classified = up + down + flat
    return {'bins': bins, 'up': up, 'down': down, 'flat': flat, 'total': total,
            'up_ratio': round(up / classified * 100, 2) if classified else None,
            'net_advances': up - down, **limits,
            'scope': str(data.get('plate') or ''), 'unclassified': total - classified}


class Radar:
    def __init__(self, bridge, connect_db):
        self.bridge = bridge
        self.connect_db = connect_db
        self.last_call = 0.0

    def cached(self, key, ttl, fetch, *, lock=None):
        # Serialize cache refreshes on the shared quote connection.
        with (self.bridge.lock if lock is None else lock):
            with self.connect_db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS radar_cache (key TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL)')
                row = db.execute('SELECT updated,payload FROM radar_cache WHERE key=?', (key,)).fetchone()
            if row and time.time() - row[0] < ttl:
                return {**json.loads(row[1]), 'updated': row[0], 'stale': False}
            try:
                result = fetch()
                updated = time.time()
                with self.connect_db() as db:
                    db.execute('INSERT OR REPLACE INTO radar_cache VALUES(?,?,?)', (key, updated, json.dumps(result, allow_nan=False)))
                return {**result, 'updated': updated, 'stale': False}
            except Exception as exc:
                if row:
                    return {**json.loads(row[1]), 'updated': row[0], 'stale': True, 'error': str(exc)}
                raise

    def call(self, method, **kwargs):
        from moomoo import RET_OK
        # Plate-list/member endpoints permit ten requests per thirty seconds.
        delay = 3.1 - (time.monotonic() - self.last_call)
        if delay > 0:
            time.sleep(delay)
        self.bridge.rate_limit()
        self.last_call = time.monotonic()
        callback = getattr(self.bridge.ensure(), method, None)
        if callback is None:
            raise ValueError(f'当前 OpenD SDK 不提供 {method}，需升级 SDK 和 OpenD 后使用')
        result = callback(**kwargs)
        if result[0] != RET_OK:
            raise ValueError(str(result[1]))
        return result[1:]

    @staticmethod
    def market(market):
        from moomoo import Market
        if market not in ('CN', 'US'):
            raise ValueError('市场须为 CN 或 US')
        return Market.SH if market == 'CN' else Market.US

    def catalog(self, market, kind):
        if kind == 'etf':
            if market != 'US':
                raise ValueError('行业 ETF 列表适用于美股')
            return {'rows': [{'symbol': 'US.' + code, 'name': name, 'kind': 'etf', 'instrument': '行业 ETF'} for code, name in US_SECTORS],
                    'source': 'State Street 行业 ETF / OpenD 行情', 'updated': None, 'stale': False}
        if kind not in ('industry', 'concept', 'other'):
            raise ValueError('不支持的板块分类')
        def fetch():
            from moomoo import Plate
            plate = {'industry': Plate.INDUSTRY, 'concept': Plate.CONCEPT, 'other': Plate.OTHER}[kind]
            frame, = self.call('get_plate_list', market=self.market(market), plate_class=plate)
            rows = {str(r['code']): {'symbol': str(r['code']), 'name': str(r['plate_name']), 'kind': kind, 'instrument': '板块指数'}
                    for r in frame.to_dict('records') if BOARD.fullmatch(str(r.get('code', '')))}
            return {'rows': list(rows.values()), 'source': 'OpenD 板块目录'}
        return self.cached(f'catalog:{market}:{kind}', 21600, fetch)

    def members(self, symbol):
        if not BOARD.fullmatch(symbol):
            raise ValueError('请选择板块指数查看成分股')
        def fetch():
            frame, = self.call('get_plate_stock', plate_code=symbol)
            rows = {str(r['code']): {'symbol': str(r['code']), 'name': str(r.get('stock_name') or '')}
                    for r in frame.to_dict('records') if SYMBOL.fullmatch(str(r.get('code', '')))}
            return {'rows': list(rows.values()), 'source': 'OpenD 板块成分'}
        return self.cached('members:' + symbol, 21600, fetch)

    def heatmap(self, market, kind, page):
        if kind not in ('industry', 'concept', 'theme') or len(page) > 2048:
            raise ValueError('热力图参数无效')
        def fetch():
            from moomoo import HeatMapPlateType
            plate_type = getattr(HeatMapPlateType, kind.upper())
            frame, next_page, total = self.call('get_heat_map_data', market=self.market(market),
                                              plate_type=plate_type, count=100, page=page or None)
            rows = []
            for r in frame.to_dict('records'):
                symbol = str(r.get('plate', ''))
                if not BOARD.fullmatch(symbol):
                    continue
                rows.append({'symbol': symbol, 'name': str(r.get('plate_name') or symbol),
                             'change': finite(r.get('change_rate')), 'turnover': finite(r.get('turnover')),
                             'up': finite(r.get('rise_count')), 'down': finite(r.get('fall_count')),
                             'flat': finite(r.get('equal_count')), 'leader': str(r.get('leader_stock') or '')})
            return {'rows': rows, 'next_page': str(next_page or ''), 'total': int(total), 'source': 'OpenD 板块热力图'}
        return self.cached(f'heatmap:{market}:{kind}:{page}', 60, fetch)

    def emotion(self, market, symbol=''):
        if market not in ('CN', 'US'):
            raise ValueError('市场须为 CN 或 US')
        if symbol and not BOARD.fullmatch(symbol):
            raise ValueError('板块代码无效')
        def fetch():
            scope = symbol
            kwargs = {'security': scope} if scope else {'market': self.market(market)}
            data, = self.call('get_rise_fall_distribution', **kwargs)
            return {**distribution_summary(data), 'source': 'OpenD 涨跌分布',
                    'definition': '非涨跌停分布区间求和；涨跌停单列，不再次相加。平盘可能包含停牌及无成交标的，上游未区分。',
                    'coverage': None, 'coverage_note': '上游未返回独立应有标的总数，无法核实覆盖率；美股包含数据源全市场证券，非仅普通股。',
                    'trade_date': None, 'data_time': None,
                    'time_note': '上游未提供行情时间戳；updated 仅为成功抓取时间，不能视为交易日期'}
        return self.cached(f'emotion:{market}:{symbol}', 60, fetch)


    def trading_days(self, symbol):
        market = 'US' if symbol.startswith('US.') else 'CN'
        today = datetime.now(ZoneInfo('America/New_York' if market == 'US' else 'Asia/Shanghai')).date()

        def fetch():
            # TradeDateMarket uses CN, unlike the OpenD plate API.
            rows, = self.call('request_trading_days', market=market,
                              start=str(today-timedelta(days=100)), end=str(today+timedelta(days=40)))
            return {'days': {r['time']: r['trade_date_type'] for r in rows}}

        result = self.cached(f'calendar:{market}:{today}', 21600, fetch)
        if result.get('stale'):
            raise ValueError('交易日历失效：' + result.get('error', ''))
        return result['days']


def bind_opend_radar(bridge, connect_db):
    radar = Radar(bridge, connect_db)
    for feature in ('catalog', 'members', 'heatmap', 'emotion', 'trading_days'):
        setattr(bridge, feature, getattr(radar, feature))
    return radar


def select_feed(feed, market, capability):
    """A single MarketData is also a valid configuration for embedded callers."""
    return feed.for_market(market, capability) if hasattr(feed, 'for_market') else feed


def save_labels(connect_db, source, capability, labels):
    if not labels:
        return
    with connect_db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS scan_symbol_labels(source TEXT, capability TEXT, '
                   'symbol TEXT, name TEXT, PRIMARY KEY(source,capability,symbol))')
        db.executemany('INSERT OR REPLACE INTO scan_symbol_labels VALUES(?,?,?,?)',
                       ((source, capability, symbol, name) for symbol, name in labels.items() if name))


class ProviderRadar:
    def __init__(self, cache, market_data):
        self.cache, self.market_data = cache, market_data

    def cached(self, key, *args, **kwargs):
        # Auxiliary analytics already include the actual contributing provider in their keys.
        return self.cache.cached(key, *args, **kwargs)

    def request(self, capability, scope, *args):
        feed = select_feed(self.market_data, scope, capability)
        result = feed.feature(capability)(scope, *args)
        return {**result, 'provider': feed.provider.source_id, 'source': result.get('source') or feed.provider.source_id}

    def catalog(self, market, kind):
        result = self.request('catalog', market, kind)
        if result['provider'] != 'opend' and not result.get('stale'):
            save_labels(self.cache.connect_db, result['provider'], 'catalog',
                        {row['symbol']: row.get('name') for row in result['rows']})
        return result

    def members(self, symbol):
        return self.request('members', symbol)

    def heatmap(self, market, kind, page):
        return self.request('heatmap', market, kind, page)

    def emotion(self, market, symbol=''):
        return self.request('emotion', market, symbol)

    def trading_days(self, symbol):
        return select_feed(self.market_data, symbol, 'trading_days').feature('trading_days')(symbol)


def install(app, bridge, connect_db, external=None, opend_radar=None):
    from fastapi import HTTPException
    radar = opend_radar or bind_opend_radar(bridge, connect_db)
    if external is not None:
        radar = ProviderRadar(radar, external)

    async def invoke(callback, *args):
        try:
            return await asyncio.to_thread(callback, *args)
        except (ValueError, ImportError, AttributeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f'板块数据暂不可用：{exc}') from exc

    @app.get('/api/radar/catalog')
    async def catalog(market: str = 'CN', kind: str = 'industry'):
        return await invoke(radar.catalog, market, kind)

    @app.get('/api/radar/members')
    async def members(symbol: str):
        return await invoke(radar.members, symbol)

    @app.get('/api/radar/heatmap')
    async def heatmap(market: str = 'CN', kind: str = 'industry', page: str = ''):
        return await invoke(radar.heatmap, market, kind, page)

    @app.get('/api/radar/emotion')
    async def emotion(market: str = 'CN', symbol: str = ''):
        return await invoke(radar.emotion, market, symbol)
    return radar
