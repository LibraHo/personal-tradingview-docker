"""Read-only US equities adapter using Alpaca stock data and reference endpoints."""
import json
import os
import re
import threading
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID
from zoneinfo import ZoneInfo

from .market_data import finite_number, normalize_bar


ET = ZoneInfo('America/New_York')
TICKER = re.compile(r'[A-Z][A-Z0-9.]{0,11}')
ADJUST = {'none': 'raw', 'qfq': 'all'}
PERIOD_MINUTES = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '60m': 60, '120m': 120, '240m': 240}
LONG = {'1d', '1w', '1mo'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ticker(symbol):
    market, _, code = symbol.partition('.')
    if market != 'US' or not TICKER.fullmatch(code):
        raise ValueError('Alpaca 仅提供美股行情，证券代码应为 US.AAPL 等格式')
    return code


def local_time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Alpaca 行情时间缺少时区')
    return parsed.astimezone(ET)


def period_start(day, period):
    if period == '1w':
        return day - timedelta(days=day.weekday())
    if period == '1mo':
        return day.replace(day=1)
    return day


def bucket_time(stamp, period, mode, sessions, overnight_feed):
    day = stamp.date()
    wall = stamp.time()
    night = wall >= time(20) or wall < time(4)
    if night != overnight_feed:
        return None
    session_day = day + timedelta(days=1) if wall >= time(20) else day
    hours = sessions.get(session_day)
    if not hours:
        return None
    opening, closing = hours
    if opening <= wall < closing:
        anchor = datetime.combine(day, opening, ET)
    elif mode == 'regular':
        return None
    elif night:
        prior = day if wall >= time(20) else day - timedelta(days=1)
        anchor = datetime.combine(prior, time(20), ET)
    else:
        anchor = datetime.combine(day, time(4) if wall < opening else closing, ET)
    if period in LONG:
        first = period_start(day, period)
        return int(datetime.combine(first, time.min, ET).timestamp())
    seconds = PERIOD_MINUTES[period] * 60
    start = int(anchor.timestamp())
    return start + (int(stamp.timestamp()) - start) // seconds * seconds


class AlpacaData:
    adjustments = ('none', 'qfq')
    live_adjustments = ()
    bar_label = 'start'

    def __init__(self, key, secret, *, feed='iex', overnight=False, paper=True):
        if not key or not secret:
            raise ValueError('Alpaca 行情需要配置 APCA_API_KEY_ID 和 APCA_API_SECRET_KEY')
        if feed not in {'iex', 'sip'}:
            raise ValueError('ALPACA_DATA_FEED 须为 iex 或 sip')
        self.source_id = 'alpaca_' + feed + ('_boats' if overnight else '')
        self.feed, self.overnight = feed, overnight
        self.data_url = 'https://data.alpaca.markets'
        self.reference_url = 'https://paper-api.alpaca.markets' if paper else 'https://api.alpaca.markets'
        self._headers = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret, 'Accept': 'application/json'}
        self._http = build_opener(NoRedirect())
        self._assets_lock = threading.Lock()
        self._assets_day = None
        self._assets = {}

    def _get(self, base, path, params=None):
        url = base + path
        if params:
            url += '?' + urlencode(params)
        try:
            with self._http.open(Request(url, headers=self._headers), timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            detail = {401:'凭证无效', 403:'请检查凭证及所选行情 feed 的订阅权限',
                      429:'已达到请求限额，请稍后刷新'}.get(status, '请求失败')
            raise ValueError(f'Alpaca {path} HTTP {status}，{detail}') from None
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError('Alpaca 行情服务暂不可达') from exc

    @lru_cache(maxsize=32)
    def _calendar_year(self, year, checked_on):
        rows = self._get(self.reference_url, '/v2/calendar', {
            'start': f'{year}-01-01', 'end': f'{year}-12-31'})
        sessions = {date.fromisoformat(row['date']): (time.fromisoformat(row['open']), time.fromisoformat(row['close']))
                    for row in rows}
        if not sessions:
            raise ValueError(f'Alpaca 交易日历未覆盖 {year} 年')
        return sessions

    def _sessions(self, start, end):
        today = datetime.now(ET).date()
        sessions = {}
        for year in range(start.year, end.year + 1):
            sessions.update(self._calendar_year(year, today))
        return sessions

    def trading_days(self, symbol):
        ticker(symbol)
        today = datetime.now(ET).date()
        start, end = today - timedelta(days=100), today + timedelta(days=40)
        days = {}
        for day, hours in self._sessions(start, end).items():
            if start <= day <= end:
                if hours not in ((time(9,30), time(16)), (time(9,30), time(13))):
                    raise ValueError(f'Alpaca 交易日历 {day} 的时段无法映射至扫描器')
                days[day.isoformat()] = 'WHOLE' if hours[1] == time(16) else 'MORNING'
        return days

    def _bars(self, code, start, end, minutes, basis, feed):
        params = {'symbols': code, 'start': start.isoformat(), 'end': end.isoformat(), 'timeframe': f'{minutes}Min',
                  'feed': feed, 'adjustment': ADJUST[basis], 'limit': 10000, 'sort': 'asc'}
        tokens = set()
        last_time = None
        while True:
            response = self._get(self.data_url, '/v2/stocks/bars', params)
            bars = response['bars'] or {}
            if not isinstance(bars, dict) or set(bars) - {code}:
                raise ValueError('Alpaca K 线响应证券不符')
            for row in bars.get(code, []):
                stamp = local_time(row['t'])
                if last_time is not None and stamp <= last_time:
                    raise ValueError('Alpaca K 线时间重复或乱序')
                if not start <= stamp <= end:
                    raise ValueError('Alpaca K 线超出请求范围')
                last_time = stamp
                yield stamp, row
            token = response.get('next_page_token')
            if not token:
                return
            if token in tokens:
                raise ValueError('Alpaca 返回了重复的分页令牌')
            tokens.add(token)
            params['page_token'] = token

    def fetch_bars(self, key, days, end_date, adjustment):
        symbol, period, mode = key
        code = ticker(symbol)
        if adjustment not in ADJUST or period not in PERIOD_MINUTES and period not in LONG:
            raise ValueError('Alpaca 不支持此周期或价格复权口径')
        if mode not in ('regular', 'extended', 'all') or period in LONG and mode != 'regular':
            raise ValueError('日周月线使用常规时段，分钟线支持常规、延长和全时段')
        if mode == 'all' and not self.overnight:
            raise ValueError('Alpaca 全时段需要 BOATS 夜盘权限和 ALPACA_OVERNIGHT=true；可选择常规或延长时段')
        now = datetime.now(ET)
        day = end_date or now.date()
        start_day = period_start(day - timedelta(days=days), period)
        start = datetime.combine(start_day, time.min, ET)
        end = min(datetime.combine(day, time(23,59,59), ET), now)
        if end < start:
            return []
        sessions = self._sessions(start_day, end.date() + timedelta(days=int(mode == 'all')))
        minutes = min(30, PERIOD_MINUTES.get(period, 30))
        candles = {}
        feeds = (self.feed, 'boats') if mode == 'all' else (self.feed,)
        for feed in feeds:
            for stamp, row in self._bars(code, start, end, minutes, adjustment, feed):
                bucket = bucket_time(stamp, period, mode, sessions, feed == 'boats')
                if bucket is None:
                    continue
                incoming = normalize_bar({'time':bucket, 'open':row['o'], 'high':row['h'], 'low':row['l'],
                                          'close':row['c'], 'volume':row.get('v')})
                current = candles.get(bucket)
                if current is None:
                    candles[bucket] = incoming
                else:
                    current['high'] = max(current['high'], incoming['high'])
                    current['low'] = min(current['low'], incoming['low'])
                    current['close'] = incoming['close']
                    a, b = current['volume'], incoming['volume']
                    current['volume'] = None if a is None or b is None else a + b
        return [candles[t] for t in sorted(candles)]

    def snapshots(self, symbols):
        if not symbols:
            return [], False
        codes = {ticker(symbol): symbol for symbol in symbols}
        data = self._get(self.data_url, '/v2/stocks/snapshots', {'symbols':','.join(codes), 'feed':self.feed})
        result = []
        for code, snapshot in data.items():
            if code not in codes:
                raise ValueError('Alpaca 报价返回了未请求的证券')
            trade = snapshot.get('latestTrade') or {}
            stamp = local_time(trade['t']) if trade.get('t') else None
            price = finite_number(trade.get('p')) if trade.get('u') not in ('incorrect','canceled') else None
            closes = []
            for name in ('dailyBar', 'prevDailyBar'):
                bar = snapshot.get(name) or {}
                close = finite_number(bar.get('c'))
                if stamp and close and bar.get('t'):
                    day = local_time(bar['t']).date()
                    if day < stamp.date():
                        closes.append((day, close))
            previous = max(closes)[1] if closes else None
            result.append({'symbol':codes[code], 'price':price,
                           'change_percent':100*(price / previous - 1) if price is not None and previous else None,
                           'update_time':stamp.isoformat() if stamp else None})
        return result, False

    def _directory(self):
        today = datetime.now(ET).date()
        with self._assets_lock:
            if self._assets_day != today:
                rows = self._get(self.reference_url, '/v2/assets', {'asset_class':'us_equity', 'status':'active'})
                self._assets = {'US.'+r['symbol']:r['name'] for r in rows if TICKER.fullmatch(r['symbol']) and r.get('name')}
                self._assets_day = today
            return self._assets

    def names(self, symbols):
        available = self._directory()
        return {s:available[s] for s in symbols if s in available}

    def search_symbols(self, query, limit, market):
        if market != 'US':
            raise ValueError('Alpaca 证券目录仅覆盖美股')
        q = query.casefold().removeprefix('us.')
        rows = [(symbol, name) for symbol, name in self._directory().items()
                if q in symbol[3:].casefold() or q in name.casefold()]
        rows.sort(key=lambda r: (r[0][3:].casefold() != q, not r[0][3:].casefold().startswith(q), r[0]))
        return {'results':[{'symbol':s,'name':n,'kind':'us_equity'} for s,n in rows[:limit]],
                'source':self.source_id, 'stale':False}

    def watchlists(self):
        groups = []
        for item in self._get(self.reference_url, '/v2/watchlists'):
            ident = str(UUID(item['id']))
            watchlist = self._get(self.reference_url, '/v2/watchlists/' + ident)
            codes = ['US.'+a['symbol'] for a in watchlist['assets']
                     if a['class'] == 'us_equity' and TICKER.fullmatch(a['symbol'])]
            groups.append({'id':ident, 'name':item['name'], 'kind':'CUSTOM', 'symbols':codes})
        return groups


def factory():
    paper = os.getenv('ALPACA_ACCOUNT_ENV', 'paper').lower()
    night = os.getenv('ALPACA_OVERNIGHT', 'false').lower()
    if paper not in ('paper', 'live') or night not in ('true', 'false'):
        raise ValueError('ALPACA_ACCOUNT_ENV 须为 paper/live；ALPACA_OVERNIGHT 须为 true/false')
    return AlpacaData(os.getenv('APCA_API_KEY_ID'), os.getenv('APCA_API_SECRET_KEY'),
                      feed=os.getenv('ALPACA_DATA_FEED','iex').lower(), overnight=night=='true', paper=paper=='paper')
