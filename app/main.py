from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .market_data import (CAPABILITIES, MarketRoutes, DisabledFeed, RoutedStreams, QuotePermissionError, market_of)
from .broker_provider import broker_config
from .indicators import calculate, check_inputs
from .python_indicator_worker import validate_code, validate_inputs
from .opend_market import PERIODS, OpenDMarket, frame_to_bars, opend_kline, period_from_push, push_matches, subscription_key
from . import drawing_api
from .stock_search import maintain_directory
from .opening_range import range_times, select_opening_range

ET = ZoneInfo('America/New_York')
CN_TZ = ZoneInfo('Asia/Shanghai')
DB = os.getenv('DB_PATH', '/data/market.sqlite3')
MAX_STREAMS = int(os.getenv('MAX_ACTIVE_STREAMS', '32'))
REFRESH = int(os.getenv('HISTORY_REFRESH_SECONDS', '120'))
DEFAULT_DAYS = int(os.getenv('HISTORY_DAYS', '5'))
HISTORY_LOOKBACK_DAYS = max(30, int(os.getenv('HISTORY_LOOKBACK_DAYS', '3650')))
BROWSED_CACHE_DAYS = max(1, int(os.getenv('BROWSED_CACHE_DAYS', '7')))
RETENTION_DAYS = max(1, int(os.getenv('CACHE_RETENTION_DAYS', '30')))
DAILY_HISTORY_DAYS = max(1, int(os.getenv('DAILY_HISTORY_DAYS', '730')))
DAILY_RETENTION_DAYS = max(DAILY_HISTORY_DAYS, int(os.getenv('DAILY_CACHE_RETENTION_DAYS', '1825')))
SYMBOL_RE = re.compile(r'^(?:US\.[A-Z0-9.]{1,12}|(?:SH|SZ)\.(?:[0-9]{6}|(?:BK|LIST)[0-9]{1,10}))$')
LONG_PERIODS = {'1d','1w','1mo'}
WEEKLY_HISTORY_DAYS = max(1,int(os.getenv('WEEKLY_HISTORY_DAYS','1825')))
MONTHLY_HISTORY_DAYS = max(1,int(os.getenv('MONTHLY_HISTORY_DAYS','3650')))
LONG_RETENTION_DAYS = max(DAILY_RETENTION_DAYS,WEEKLY_HISTORY_DAYS,MONTHLY_HISTORY_DAYS,int(os.getenv('LONG_CACHE_RETENTION_DAYS','3650')))

# Cover the 20 prior sessions even around extended exchange holidays.
CN_VOLUME_HISTORY_DAYS = 60

def default_history_days(period, symbol=''):
    if symbol.startswith(('SH.', 'SZ.')) and period in ('60m', '120m'):
        return max(DEFAULT_DAYS, CN_VOLUME_HISTORY_DAYS)
    if symbol.startswith(('SH.', 'SZ.')) and period == '240m':
        return DAILY_HISTORY_DAYS
    if period in {'120m', '240m'}:
        return min(RETENTION_DAYS, max(DEFAULT_DAYS, 30))
    return {'1d':DAILY_HISTORY_DAYS,'1w':WEEKLY_HISTORY_DAYS,'1mo':MONTHLY_HISTORY_DAYS}.get(period,DEFAULT_DAYS)

def retention_days(period, symbol=''):
    if symbol.startswith(('SH.', 'SZ.')) and period in ('60m', '120m'):
        return max(RETENTION_DAYS, CN_VOLUME_HISTORY_DAYS)
    if symbol.startswith(('SH.', 'SZ.')) and period == '240m':
        return DAILY_RETENTION_DAYS
    return LONG_RETENTION_DAYS if period in {'1w','1mo'} else DAILY_RETENTION_DAYS if period=='1d' else RETENTION_DAYS

MODES = {'all', 'extended', 'regular'}
listeners: dict[tuple[str, str, str], set[asyncio.Queue]] = {}
last_fetch: dict[tuple[str, str, str, str], float] = {}
fetch_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
history_failures: dict[tuple[str, str, str, str], tuple[float, str, str]] = {}
python_slots = asyncio.Semaphore(1)
strategy_leases = {}
loop = None


@contextmanager
def connect_db():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as db:
        # Keep unversioned history readable for recovery. Its push basis is unknown.
        db.execute('BEGIN IMMEDIATE')
        for table in ('bars', 'cache_sync', 'history_windows'):
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            if columns and 'scope' not in columns:
                db.execute(f'ALTER TABLE {table} RENAME TO legacy_{table}')
        for statement in CACHE_SCHEMA.split(';'):
            if statement.strip():
                db.execute(statement)
        if 'origin' not in {row[1] for row in db.execute('PRAGMA table_info(bars)')}:
            db.execute('ALTER TABLE bars ADD COLUMN origin TEXT')


CACHE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS bars(scope TEXT NOT NULL, symbol TEXT, period TEXT, mode TEXT, time INTEGER,
          open REAL, high REAL, low REAL, close REAL, volume REAL, turnover REAL, extra_fields TEXT, origin TEXT,
          PRIMARY KEY(scope,symbol,period,mode,time));
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cache_sync(scope TEXT NOT NULL,symbol TEXT, period TEXT, mode TEXT,
          requested_days INTEGER, last_success REAL, PRIMARY KEY(scope,symbol,period,mode));
        CREATE TABLE IF NOT EXISTS history_windows(scope TEXT NOT NULL,symbol TEXT, period TEXT, mode TEXT,
          start INTEGER, end INTEGER, checked REAL, PRIMARY KEY(scope,symbol,period,mode,start,end));
        CREATE TABLE IF NOT EXISTS symbol_names(symbol TEXT PRIMARY KEY, name TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS symbol_kinds(symbol TEXT PRIMARY KEY, kind TEXT NOT NULL);
        """


def prune_cache():
    now = datetime.now(ET)
    intraday_cutoff = int((now - timedelta(days=RETENTION_DAYS)).timestamp())
    daily_cutoff = int((now - timedelta(days=DAILY_RETENTION_DAYS)).timestamp())
    with connect_db() as db:
        # Adjusted snapshots from earlier sessions are superseded by a fresh fetch.
        old = str((now - timedelta(days=2)).date())
        for table in ('bars', 'history_windows', 'cache_sync'):
            db.execute(f"DELETE FROM {table} WHERE substr(scope,-10) GLOB '????-??-??' AND substr(scope,-10) < ?", (old,))
        db.execute("DELETE FROM history_windows WHERE checked < ?", (time.time()-BROWSED_CACHE_DAYS*86400,))
        db.execute("DELETE FROM bars WHERE period NOT IN ('1d','1w','1mo') AND NOT (period='240m' AND (symbol GLOB 'SH.*' OR symbol GLOB 'SZ.*')) AND time < ? AND (period NOT IN ('60m','120m') OR NOT (symbol GLOB 'SH.*' OR symbol GLOB 'SZ.*') OR time < ?) AND NOT EXISTS (SELECT 1 FROM history_windows w WHERE w.scope=bars.scope AND w.symbol=bars.symbol AND w.period=bars.period AND w.mode=bars.mode AND bars.time BETWEEN w.start AND w.end)", (intraday_cutoff, int((now-timedelta(days=CN_VOLUME_HISTORY_DAYS)).timestamp())))
        long_cutoff=int((now-timedelta(days=LONG_RETENTION_DAYS)).timestamp())
        db.execute("DELETE FROM bars WHERE period IN ('1w','1mo') AND time < ?", (long_cutoff,))
        db.execute("DELETE FROM bars WHERE (period = '1d' OR (period='240m' AND (symbol GLOB 'SH.*' OR symbol GLOB 'SZ.*'))) AND time < ?", (daily_cutoff,))


def validate(symbol, period, mode):
    symbol = symbol.upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError('股票代码应为 US.AAPL、SH.600519 或 SZ.000001 格式')
    if period not in PERIODS or mode not in MODES:
        raise ValueError('不支持的周期或时段')
    if (period in LONG_PERIODS or not symbol.startswith('US.')) and mode != 'regular':
        raise ValueError('A 股和日 / 周 / 月线请选择常规时段')
    return symbol, period, mode


def session_fields(ts, symbol='US.AAPL'):
    if not symbol.startswith('US.'):
        day = str(datetime.fromtimestamp(ts, CN_TZ).date())
        return 'regular', day, day
    dt = datetime.fromtimestamp(ts, ET)
    minute = dt.hour * 60 + dt.minute
    if minute < 240 or minute >= 1200:
        session = 'overnight'
    elif minute < 570:
        session = 'pre'
    elif minute < 960:
        session = 'regular'
    else:
        session = 'post'
    trade = dt.date() + (timedelta(days=1) if minute >= 1200 else timedelta())
    return session, str(dt.date()), str(trade)


def row_to_bar(row):
    d = dict(row)
    extra = d.pop('extra_fields', None)
    if extra:
        d['fields'] = json.loads(extra)
    scope = d.pop('scope', None) or scope_for(d['symbol'])
    sources, d['adjustment'], _ = scope.split('/')
    d['provider'] = d.pop('origin', None) or d.get('provider') or sources.split('~')[0]
    d['session'], d['calendar_date'], d['trade_date'] = session_fields(d['time'], d['symbol'])
    if d['period'] in LONG_PERIODS:
        d['session'] = 'regular'
    d['session_date'] = d['trade_date'] + ':' + d['session']
    return d


def save_bars(key, bars):
    if not bars:
        return
    scope = scope_for(key[0])
    with connect_db() as db:
        db.executemany('''INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(scope,symbol,period,mode,time) DO UPDATE SET
            open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
            volume=excluded.volume,turnover=excluded.turnover,extra_fields=excluded.extra_fields,origin=excluded.origin''',
            [(scope, *key, b['time'], b['open'], b['high'], b['low'], b['close'], b['volume'], b['turnover'],
              json.dumps(b['fields'], allow_nan=False) if b.get('fields') else None, b.get('provider') or scope.split('/')[0].split('~')[0]) for b in bars])


def read_bars(key, days, limit):
    since = int((datetime.now(ET) - timedelta(days=days)).timestamp())
    with connect_db() as db:
        rows = db.execute('SELECT * FROM bars WHERE scope=? AND symbol=? AND period=? AND mode=? AND time>=? ORDER BY time DESC LIMIT ?', (scope_for(key[0]), *key, since, limit)).fetchall()
    return [row_to_bar(r) for r in reversed(rows)]


def sync_state(key):
    with connect_db() as db:
        row = db.execute('SELECT requested_days,last_success FROM cache_sync WHERE scope=? AND symbol=? AND period=? AND mode=?', (scope_for(key[0]), *key)).fetchone()
        latest = db.execute('SELECT MAX(time) FROM bars WHERE scope=? AND symbol=? AND period=? AND mode=?', (scope_for(key[0]), *key)).fetchone()[0]
    return (int(row[0]), float(row[1]), latest) if row else (0, 0, latest)


def refresh_span(key, days, known_days=0, latest=None, last_success=0):
    # Existing caches survive migration; do not redownload their old bars to warm RAM.
    # A small overlap corrects the latest, still-changing candles after reconnects.
    if known_days and days > known_days:
        return days
    if latest is None and not known_days:
        return days
    reference = latest if latest is not None else last_success
    zone = ET if key[0].startswith('US.') else CN_TZ
    missing = (datetime.now(zone).date() - datetime.fromtimestamp(reference, zone).date()).days + 2
    return min(days, max(2, missing))


def save_sync_state(key, days):
    with connect_db() as db:
        db.execute('INSERT INTO cache_sync VALUES(?,?,?,?,?,?) ON CONFLICT(scope,symbol,period,mode) DO UPDATE SET '
                   'requested_days=MAX(requested_days,excluded.requested_days),last_success=excluded.last_success',
                   (scope_for(key[0]), *key, days, time.time()))


def read_bars_before(key, before, limit):
    cutoff = int(time.time()) - HISTORY_LOOKBACK_DAYS*86400
    with connect_db() as db:
        rows = db.execute('SELECT * FROM bars WHERE scope=? AND symbol=? AND period=? AND mode=? AND time<? AND time>=? ORDER BY time DESC LIMIT ?',
                          (scope_for(key[0]), *key, before, cutoff, limit)).fetchall()
    return [row_to_bar(r) for r in reversed(rows)]


def run_python_indicator(code, bars, inputs=None):
    import ast
    if any(isinstance(node, ast.Name) and node.id == 'V' for node in ast.walk(validate_code(code))):
        check_inputs(bars, 'Python 指标', ['volume'])
    payload = {'code': code, 'inputs': validate_inputs(inputs if inputs is not None else {}), 'bars': [{field: bar[field] for field in
        ('time', 'open', 'high', 'low', 'close', 'volume', 'session', 'trade_date')} for bar in bars]}
    worker = Path(__file__).with_name('python_indicator_worker.py')
    def limit_resources():
        import resource
        memory = 128 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-S', str(worker)], input=json.dumps(payload),
            text=True, capture_output=True, timeout=3,
            env={'PYTHONIOENCODING': 'utf-8'}, cwd='/',
            preexec_fn=limit_resources if os.name == 'posix' else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Python 指标运行超时（3 秒）') from exc
    if result.returncode != 0:
        raise ValueError('Python 指标进程异常或达到资源限制')
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError('Python 指标未返回有效结果') from exc
    if 'error' in data:
        raise ValueError(data['error'])
    return data


def stream_error(key, message):
    if loop:
        loop.call_soon_threadsafe(notify_stream, key, {'type':'error','message':message})


def Bridge():
    return OpenDMarket(connect_db, listeners, stream_error)


def on_provider_bars(key, bars):
    if loop is not None:
        asyncio.run_coroutine_threadsafe(publish(key, bars), loop)


from .radar import bind_opend_radar
from .market_analytics import EastmoneyLimits
bridge = Bridge()
opend_radar = bind_opend_radar(bridge, connect_db)
market_data = MarketRoutes(os.getenv('MARKET_DATA_PROVIDER','opend'), os.getenv('MARKET_DATA_ADJUSTMENT','qfq').lower(),
                           json.loads(os.getenv('MARKET_DATA_ROUTES','{}')),
                           {'opend':bridge,'disabled':DisabledFeed(),'eastmoney':EastmoneyLimits()}, save_bars)
streams = RoutedStreams(market_data, on_provider_bars, listeners, MAX_STREAMS)
_scope = ContextVar('market_cache_scope', default=None)


def scope_for(symbol):
    pinned = _scope.get()
    if pinned is not None:
        return pinned
    meta = market_data.metadata(symbol)
    basis = meta['adjustment']
    identity = meta['provider']
    if meta['live_supported'] and meta['live_provider'] != identity:
        identity += '~' + meta['live_provider']
    revision = (str(datetime.now(ET if symbol.upper().startswith('US.') else CN_TZ).date())
                if basis == 'qfq' else 'stable')
    return f'{identity}/{basis}/{revision}'


def scoped(function):
    @wraps(function)
    async def call(*args, **kwargs):
        first = args[0] if args else kwargs.get('symbol') or kwargs['key']
        symbol = first[0] if isinstance(first, tuple) else first
        try:
            scope = scope_for(symbol)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        token = _scope.set(scope)
        try:
            result = await function(*args, **kwargs)
            if isinstance(result, dict):
                result.update(market_data.metadata(symbol), series_revision=scope)
                if 'bars' in result:
                    feed = market_data.for_market(symbol)
                    history_status = getattr(feed.provider, 'history_status', None)
                    if history_status:
                        try:
                            info = await asyncio.to_thread(history_status, symbol.upper())
                            result['stale'] = bool(result.get('stale') or info.get('stale'))
                            for field in ('archive_as_of', 'history_notice'):
                                if field in info:
                                    result[field] = info[field]
                        except Exception:
                            result.update(stale=True, history_notice=f'{feed.provider.source_id} 无法确认历史数据更新时间')
            return result
        finally:
            _scope.reset(token)
    return call


@scoped
async def publish(key, bars):
    if key[2] != 'all' and key[1] not in LONG_PERIODS:
        bars = [b for b in bars if session_fields(b['time'], key[0])[0] == 'regular' or
                (key[2] == 'extended' and session_fields(b['time'], key[0])[0] in ('pre', 'post'))]
    origin = market_data.for_market(key[0], 'live').provider.source_id
    bars = [{**bar, 'provider':origin} for bar in bars]
    await asyncio.to_thread(save_bars, key, bars)
    for bar in bars:
        item = {'type': 'bar', 'series_revision': scope_for(key[0]), 'bar': row_to_bar(dict(symbol=key[0], period=key[1], mode=key[2], **bar))}
        notify_stream(key, item)


def notify_stream(key, item):
    for queue in tuple(listeners.get(key, ())):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(item)


def stream_connected(key):
    return streams.connected(key)


async def maintenance():
    previous_prune = 0.0
    while True:
        await asyncio.sleep(20)
        try:
            for key,(queue,until) in list(strategy_leases.items()):
                if until < time.monotonic():
                    listeners.get(key,set()).discard(queue)
                    strategy_leases.pop(key,None)
            if time.monotonic() - previous_prune > 86400:
                await asyncio.to_thread(prune_cache)
                previous_prune = time.monotonic()
            await asyncio.to_thread(streams.unsubscribe_unused)
            for provider in market_data.configured_providers():
                cleanup = getattr(provider, 'cleanup', None)
                if cleanup:
                    await asyncio.to_thread(cleanup)
            for key in list(listeners):
                try:
                    if not listeners[key]:
                        continue
                    reconnect = not stream_connected(key)
                    if reconnect and market_data.metadata(key[0])['live_supported']:
                        await asyncio.to_thread(streams.subscribe, key)
                    if reconnect or time.monotonic() - last_fetch.get(cache_key(key), 0) > max(REFRESH, 600):
                        days = default_history_days(key[1], key[0])
                        await refresh_history(key, days, force=True)
                except QuotePermissionError:
                    continue
                except Exception as exc:
                    streams.last_error = str(exc)
        except Exception as exc:
            streams.last_error = str(exc)


@asynccontextmanager
async def lifespan(app):
    global loop
    init_db()
    drawing_api.drawing_token()
    loop = asyncio.get_running_loop()
    # The chart already authorized this request. Reuse its own bar service even
    # when an external identity proxy requires headers on incoming HTTP calls.
    from . import market_analysis
    def read_analysis_bars(params):
        future = asyncio.run_coroutine_threadsafe(bars(**params), loop)
        try:
            return future.result(timeout=45)
        except TimeoutError:
            future.cancel()
            raise
    market_analysis.local_bar_reader = read_analysis_bars
    task = asyncio.create_task(maintenance())
    await scan_service.start()
    from .notifications import Notifications
    notification_task = asyncio.create_task(Notifications(connect_db).run())
    from .ledger_broker import run as sync_trade_archive
    archive_task = asyncio.create_task(sync_trade_archive(connect_db))
    from .plan_daily import run as run_plan_daily
    plan_daily_task = asyncio.create_task(run_plan_daily(connect_db, scan_service.calendar, actual_price_bars))
    directory_stop = asyncio.Event()
    directory_markets = {m for m in ('CN','US') if market_data.for_market(m,'search_symbols').provider is bridge}
    directory_task = (asyncio.create_task(maintain_directory(bridge, connect_db, directory_stop, Bridge, directory_markets))
                      if directory_markets else None)
    try:
        yield
    finally:
        market_analysis.local_bar_reader = None
        directory_stop.set()
        if directory_task:
            await directory_task
        plan_daily_task.cancel()
        archive_task.cancel()
        await asyncio.gather(archive_task, plan_daily_task, return_exceptions=True)
        await scan_service.stop()
        notification_task.cancel()
        await asyncio.gather(notification_task, return_exceptions=True)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(streams.close)
        for provider in market_data.configured_providers():
            close = getattr(provider, 'close', None)
            if close:
                await asyncio.to_thread(close)
        loop = None


app = FastAPI(title='NAS Market', lifespan=lifespan)


@app.middleware('http')
async def auth(request: Request, call_next):
    if (request.url.path.startswith(('/api/scanner/', '/api/review/', '/api/market-analysis/')) or request.url.path=='/api/settings/theme') and request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        fetch_site=request.headers.get('sec-fetch-site')
        different_origin=origin and origin!=str(request.base_url).rstrip('/')
        # Browser metadata describes the public origin even when a proxy rewrites the URL.
        if fetch_site=='cross-site' or (different_origin and fetch_site!='same-origin'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'请从 NAS Market 页面发起操作'},status_code=403)
    if request.url.path.startswith('/api/drawings/'):
        from fastapi.responses import JSONResponse
        try:
            drawing_api.authenticate(request)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': '请求长度无效'}, status_code=400)
        if length > 32768:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': '请求过大'}, status_code=413)
    header = os.getenv('TRUSTED_USER_HEADER', '')
    if header and not request.headers.get(header) and not request.url.path.startswith(('/api/drawings/', '/api/v1/')):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': '登录后访问'}, status_code=401)
    return await call_next(request)


@app.get('/api/status')
def status(market: str = 'US'):
    if market not in ('US', 'CN'):
        raise HTTPException(400,'市场须为 US 或 CN')
    selected = market_data.for_market(market)
    methods = {'history':'fetch_bars', 'live':'subscribe_bars'}
    capabilities = {}
    for capability in CAPABILITIES:
        provider = market_data.for_market(market, capability).provider
        capabilities[capability] = callable(getattr(provider, methods.get(capability, capability), None))
    meta = market_data.metadata(market)
    capabilities['live'] = meta['live_supported']
    return {**meta, 'capabilities':capabilities, 'routes':market_data.route_identities(),
            'opend_configured': bridge in market_data.configured_providers() or broker_config().source_id == 'opend',
            'opend_connected': bridge.ctx is not None, 'last_error': streams.last_error or getattr(selected.provider,'last_error',None),
            'active_streams': len(streams.active), 'max_streams': MAX_STREAMS,
            'permission_errors': {k:v for k,v in bridge.permission_errors.items()
                                  if v['until'] > time.time() and market_data.for_market(k).provider is bridge}}


@app.post('/api/quote/retry')
def retry_quote(symbol: str):
    if not SYMBOL_RE.fullmatch(symbol.upper()):
        raise HTTPException(400, '股票代码无效')
    for cap in ('history','live','snapshots'):
        provider = market_data.for_market(symbol.upper(),cap).provider
        retry = getattr(provider,'retry',None)
        if retry:
            retry(symbol.upper())
    return {'ok': True}


@app.get('/api/cache/status')
def cache_status(symbol: str | None = None):
    if symbol is not None and not SYMBOL_RE.fullmatch(symbol.upper()):
        raise HTTPException(400, '股票代码无效')
    with connect_db() as db:
        total = db.execute('SELECT COUNT(*) FROM bars').fetchone()[0]
        rows = db.execute('SELECT symbol,period,mode,COUNT(*) AS count,MIN(time) AS oldest,MAX(time) AS newest '
                          'FROM bars WHERE scope=? AND symbol=? GROUP BY symbol,period,mode', (scope_for(symbol),symbol.upper())).fetchall() if symbol else []
    size = sum(p.stat().st_size for p in [Path(DB), Path(DB+'-wal')] if p.exists())
    return {'storage': 'NAS SQLite', 'total_bars': total, 'bytes': size,
            'intraday_retention_days': RETENTION_DAYS, 'daily_retention_days': DAILY_RETENTION_DAYS, 'long_retention_days': LONG_RETENTION_DAYS,
            'series': [dict(row) for row in rows]}


@app.get('/api/trading-config')
def trading_config():
    url = os.getenv('TRADING_URL', '')
    return {'url': url if url.startswith('https://') else None}


@app.get('/api/depth')
def depth(symbol: str):
    symbol = symbol.upper()
    if not re.fullmatch(r'US\.[A-Z][A-Z0-9.]{0,11}', symbol):
        raise HTTPException(400, '盘口密集线目前只支持美股')
    try:
        return market_data.for_market(symbol,'depth').feature('depth')(symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(503, '盘口连接异常；旧盘口线已停用')


@app.get('/api/order-flow')
def order_flow(symbol: str):
    symbol = symbol.upper()
    if not re.fullmatch(r'US\.[A-Z][A-Z0-9.]{0,11}', symbol):
        raise HTTPException(400, '逐笔面板目前只支持美股')
    try:
        return {'ticks': market_data.for_market(symbol,'ticks').feature('ticks')(symbol)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(503, '逐笔行情连接异常')


@app.get('/api/option-profile')
def option_volume_profile(symbol: str, expiry: str = ''):
    symbol = symbol.upper()
    if not re.fullmatch(r'US\.[A-Z][A-Z0-9.]{0,11}', symbol):
        raise HTTPException(400, '请输入美股或 ETF 代码')
    if expiry:
        try:
            if datetime.strptime(expiry, '%Y-%m-%d').date().isoformat() != expiry:
                raise ValueError
        except ValueError:
            raise HTTPException(400, '到期日格式应为 YYYY-MM-DD')
    try:
        return market_data.for_market(symbol,'option_profile').feature('option_profile')(symbol, expiry)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(503, '期权行情连接异常')


@app.get('/api/symbols/search')
def search_symbols(q: str = '', market: str = 'CN', limit: int = 12):
    if market not in ('CN', 'US') or len(q) > 32 or not 1 <= limit <= 20:
        raise HTTPException(400, '请选择沪深或美股市场，关键词最多 32 字，最多返回 20 项')
    if not q.strip():
        return {'results': [], 'stale': False, 'source': 'nas_cache'}
    try:
        return market_data.for_market(market, 'search_symbols').feature('search_symbols')(q, limit, market)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get('/api/symbols/names')
async def symbol_names(symbols: str, prefer_cache: bool = False):
    codes = list(dict.fromkeys(s.strip().upper() for s in symbols.split(',') if s.strip()))
    if not codes or len(codes) > 100 or any(not SYMBOL_RE.fullmatch(code) for code in codes):
        raise HTTPException(400, '股票代码无效，单次最多一百只')
    names = {}
    missing = []
    for feed, group in market_data.batches(codes, 'names'):
        cached = getattr(feed.provider, 'cached_names', None)
        if prefer_cache and cached:
            found, absent = await asyncio.to_thread(cached, group)
        else:
            reader = getattr(feed.provider, 'names', None)
            found = await asyncio.to_thread(reader, group) if reader else {}
            absent = [symbol for symbol in group if symbol not in found]
        names.update(found)
        missing.extend(absent)
    return {'names':names, 'missing':missing} if prefer_cache or missing else {'names':names}


@app.get('/api/chips/summary')
def chip_summary(market: str, offset: int = 0, limit: int = 20):
    if market not in ('CN', 'US') or offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(400, '筹码查询需要 US 或 CN，分页数量为 1 至 100')
    feed = market_data.for_market(market, 'chip_summary')
    try:
        read = feed.feature('chip_summary')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        page = read(market, offset, limit)
        return {**page, 'provider': feed.provider.source_id, 'market': market,
                'offset': offset, 'limit': limit, 'kind': 'snapshot'}
    except Exception as exc:
        raise HTTPException(502, f'{feed.provider.source_id} 筹码查询失败：{exc}') from exc


@app.get('/api/quotes')
async def quotes(symbols: str):
    codes = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    if not codes or len(codes) > 100 or any(not SYMBOL_RE.fullmatch(s) for s in codes):
        raise HTTPException(400, '请输入 1 至 100 个有效股票代码')
    try:
        data, stale = await asyncio.to_thread(market_data.snapshots, codes)
        providers = {market_of(code):market_data.for_market(code,'snapshots').provider.source_id for code in codes}
        return {'quotes':data, 'stale':stale, 'providers':providers,
                'provider':next(iter(providers.values())) if len(set(providers.values())) == 1 else 'mixed', 'adjustment':'none'}
    except Exception as exc:
        raise HTTPException(503, f'报价快照不可用：{exc}')


def cache_key(key):
    return (scope_for(key[0]), *key)


def history_needs_refresh(key, days, known, success):
    age = time.monotonic()-last_fetch[cache_key(key)] if cache_key(key) in last_fetch else time.time()-success
    return not known or age > REFRESH or days > known


@scoped
async def refresh_history(key, days, force=False):
    started = time.monotonic()
    async with fetch_locks.setdefault(key, asyncio.Lock()):
        known, success, latest = await asyncio.to_thread(sync_state, key)
        if not history_needs_refresh(key, days, known, success):
            if not force or last_fetch.get(cache_key(key), 0) >= started:
                return None
        failure = history_failures.get(cache_key(key))
        if failure and failure[0] > started - 15 and (not force or failure[0] >= started):
            return failure
        try:
            span = refresh_span(key, days, known, latest, success) if known else days
            await asyncio.to_thread(market_data.history, key, span)
        except Exception as exc:
            now = time.monotonic()
            for old in [k for k, entry in history_failures.items() if entry[0] <= now - 15]:
                del history_failures[old]
            code = 'permission_denied' if isinstance(exc, QuotePermissionError) else 'quote_unavailable'
            history_failures[cache_key(key)] = (now, code, str(exc))
            return history_failures[cache_key(key)]
        await asyncio.to_thread(save_sync_state, key, days)
        last_fetch[cache_key(key)] = time.monotonic()
        history_failures.pop(cache_key(key), None)
        return None


async def actual_price_bars(*args, **kwargs):
    # Plan levels and execution deviation limits are denominated in actual prices.
    with market_data.for_market(args[0] if args else kwargs['symbol']).using_adjustment('none'):
        return await bars(*args, **kwargs)


@app.get('/api/bars')
async def bars_response(symbol: str, period: str = '5m', mode: str = 'all', days: int | None = None,
                        limit: int = 5000, refresh: bool = False, prefer_cache: bool = False):
    result = await bars(symbol, period, mode, days, limit, refresh, prefer_cache)
    return await asyncio.to_thread(JSONResponse, result)


@scoped
async def bars(symbol: str, period: str = '5m', mode: str = 'all', days: int | None = None, limit: int = 5000,
               refresh: bool = False, prefer_cache: bool = False):
    try:
        key = validate(symbol, period, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if days is None:
        days = default_history_days(period, symbol)
    days = min(max(days, 1), retention_days(period, symbol))
    limit = min(max(limit, 1), 10000)
    if prefer_cache:
        known, success, _ = await asyncio.to_thread(sync_state, key)
        cached = await asyncio.to_thread(read_bars, key, days, limit)
        if cached:
            stale = refresh or history_needs_refresh(key, days, known, success)
            failure = history_failures.get(cache_key(key))
            if stale and not refresh and failure and failure[0] > time.monotonic() - 15:
                return {'bars': cached, 'stale': True, 'error': failure[2], 'error_code': failure[1],
                        'source': 'nas_cache', 'last_success': success}
            return {'bars': cached, 'stale': stale, 'revalidate': stale, 'source': 'nas_cache',
                    'last_success': success}
    failure = await refresh_history(key, days, refresh)
    rows = await asyncio.to_thread(read_bars, key, days, limit)
    if failure:
        if not rows:
            raise HTTPException(503, f'{market_data.for_market(symbol).provider.source_id} 行情不可用：{failure[2]}')
        return {'bars': rows, 'stale': True, 'error': failure[2], 'error_code': failure[1], 'source': 'nas_cache'}
    return {'bars': rows, 'stale': False, 'source': 'nas_cache'}


def remember_history_window(key, start, end):
    with connect_db() as db:
        db.execute('INSERT OR REPLACE INTO history_windows VALUES(?,?,?,?,?,?,?)', (scope_for(key[0]),*key,start,end,time.time()))


@app.get('/api/bars/window')
@scoped
async def bars_window(symbol: str, period: str, mode: str, start: int, end: int):
    try:
        key = validate(symbol, period, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if start >= end or end-start > 31*86400 or end > time.time()+86400 or start < time.time()-max(HISTORY_LOOKBACK_DAYS,retention_days(period, symbol))*86400:
        raise HTTPException(400, '日期范围无效或超出可配置的历史查询范围')
    async with fetch_locks.setdefault(key, asyncio.Lock()):
        with connect_db() as db:
            covered = db.execute('SELECT 1 FROM history_windows WHERE scope=? AND symbol=? AND period=? AND mode=? AND start<=? AND end>=? AND checked>?', (scope_for(key[0]),*key,start,end,time.time()-86400)).fetchone()
        if not covered:
            zone = ET if key[0].startswith('US.') else CN_TZ
            first = datetime.fromtimestamp(start,zone).date()
            last = datetime.fromtimestamp(end,zone).date()
            try:
                await asyncio.to_thread(market_data.history,key,(last-first).days+1,last)
            except Exception as exc:
                raise HTTPException(503,f'目标日期行情暂不可用：{exc}')
            remember_history_window(key,start,end)
        with connect_db() as db:
            rows=db.execute('SELECT * FROM bars WHERE scope=? AND symbol=? AND period=? AND mode=? AND time>=? AND time<=? ORDER BY time',(scope_for(key[0]),*key,start,end)).fetchall()
        return {'bars':[row_to_bar(row) for row in rows]}


@app.get('/api/bars/older')
@scoped
async def older_bars(symbol: str, period: str, mode: str, before: int, limit: int = 1000):
    try:
        key = validate(symbol, period, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if before <= 0 or before > int(time.time()) + 86400:
        raise HTTPException(400, '无效的历史时间')
    limit = min(max(limit, 1), 2000)
    cutoff = int(time.time()) - max(HISTORY_LOOKBACK_DAYS,retention_days(period, symbol))*86400
    if before <= cutoff:
        return {'bars': [], 'next_before': before, 'has_more': False}
    lock = fetch_locks.setdefault(key, asyncio.Lock())
    async with lock:
        # An isolated old date window is not proof that the gap before the
        # current viewport was fetched. Reuse only verified adjacent coverage.
        with connect_db() as db:
            coverage=db.execute('SELECT start FROM history_windows WHERE scope=? AND symbol=? AND period=? AND mode=? AND start<? AND end>=? AND checked>? ORDER BY start LIMIT 1',(scope_for(key[0]),*key,before,before-1,time.time()-86400)).fetchone()
        if coverage:
            cached=await asyncio.to_thread(read_bars_before,key,before,limit)
            cached=[b for b in cached if b['time']>=coverage['start']]
            cursor=cached[0]['time'] if cached else max(cutoff,coverage['start'])
            return {'bars':cached,'next_before':cursor,'has_more':cursor>cutoff}
        zone = ET if key[0].startswith('US.') else CN_TZ
        end_date = datetime.fromtimestamp(before, zone).date()
        window_days = 1825 if period == '1mo' else 730 if period == '1w' else 365 if period == '1d' else 3 if period == '1m' else 10 if period == '5m' else 21 if period == '15m' else 35
        start_date = end_date - timedelta(days=window_days)
        try:
            await asyncio.to_thread(market_data.history, key, window_days, end_date)
        except Exception as exc:
            raise HTTPException(503, f'历史 K 线暂不可用：{exc}')
        remember_history_window(key, int(datetime.combine(start_date, datetime.min.time(), zone).timestamp()), before)
        result = await asyncio.to_thread(read_bars_before, key, before, limit)
        window_start=int(datetime.combine(start_date,datetime.min.time(),zone).timestamp())
        result=[b for b in result if b['time']>=window_start]
        next_before = result[0]['time'] if result else int(datetime.combine(start_date, datetime.min.time(), zone).timestamp())
        return {'bars': result, 'next_before': next_before, 'has_more': next_before > cutoff}


@app.get('/api/indicators')
async def indicators(symbol: str, period: str, mode: str, name: str, params: str = '{}', reset: str = 'session', days: int | None = None):
    response = await bars(symbol, period, mode, days)
    try:
        check_inputs(response['bars'], name.upper())
        values = calculate(response['bars'], name.upper(), json.loads(params), reset)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))
    return {'time': [b['time'] for b in response['bars']], 'values': values, 'stale': response['stale']}


@app.get('/api/opening-range')
@scoped
async def opening_range(symbol: str, date: str | None = None):
    try:
        symbol=validate(symbol,'5m','regular')[0]
        zone=ET if symbol.startswith('US.') else CN_TZ
        today=datetime.fromtimestamp(time.time(),zone).date()
        day=date or str(today)
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError('日期格式应为 YYYY-MM-DD')
        times=range_times(symbol,day)
        if times['open_at']>time.time()+86400 or times['open_at']<time.time()-HISTORY_LOOKBACK_DAYS*86400:
            raise ValueError('日期超出可查询范围')
    except ValueError as exc:raise HTTPException(400,str(exc))
    if time.time()<times['confirmed_at']+2:
        return {**times,'symbol':symbol,'status':'forming','message':'等待常规开盘后5分钟收线'}
    cache_key=f'opening-range.{scope_for(symbol)}.{symbol}.{day}'
    async with fetch_locks.setdefault((symbol,'opening-range',day),asyncio.Lock()):
        with connect_db() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(cache_key,)).fetchone()
        cached=json.loads(row[0]) if row else None
        label=getattr(market_data.for_market(symbol).provider,'bar_label',os.getenv('OPENING_RANGE_BAR_LABEL','end'))
        ttl=30 if cached and cached.get('status')=='missing' and day==str(today) else 900
        if cached and cached.get('label')==label and time.time()-cached.get('checked',0)<ttl:
            return {**cached,'source':'nas_cache','stale':False}
        try:
            rows=await asyncio.to_thread(market_data.opening_five,symbol,day)
            result=select_opening_range(rows,symbol,times,label)
        except Exception as exc:
            if cached and cached.get('status')=='ready' and cached.get('label')==label:
                return {**cached,'source':'nas_cache','stale':True,'error':str(exc)}
            raise HTTPException(503,f'开盘5分钟行情暂不可用：{exc}')
        result=result or {**times,'symbol':symbol,'status':'missing','message':'当天尚未取得开盘5分钟行情，休市日不画线'}
        result.update(checked=time.time(),label=label)
        with connect_db() as db:
            db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (cache_key,json.dumps(result)))
        return {**result,'source':market_data.for_market(symbol).provider.source_id,'stale':False}


class PythonIndicatorRequest(BaseModel):
    symbol: str = ''
    period: str = '5m'
    mode: str = 'all'
    code: str
    inputs: dict = Field(default_factory=dict)


def python_validation_error(exc):
    return f'第 {exc.lineno} 行：{exc.msg}' if isinstance(exc, SyntaxError) else str(exc)


@app.post('/api/python-indicator/validate')
def validate_python_indicator(request: PythonIndicatorRequest):
    try:
        validate_code(request.code)
        validate_inputs(request.inputs)
    except (SyntaxError, ValueError) as exc:
        raise HTTPException(400, python_validation_error(exc))
    return {'ok': True}


@app.post('/api/python-indicator')
async def python_indicator(request: PythonIndicatorRequest):
    try:
        key = validate(request.symbol, request.period, request.mode)
        validate_code(request.code)
        validate_inputs(request.inputs)
    except (SyntaxError, ValueError) as exc:
        raise HTTPException(400, python_validation_error(exc))
    days = default_history_days(key[1], key[0])
    bars_data = await asyncio.to_thread(read_bars, key, days, 5000)
    if not bars_data:
        raise HTTPException(409, '请先加载该图表的 K 线')
    try:
        async with python_slots:
            return await asyncio.to_thread(run_python_indicator, request.code, bars_data, request.inputs)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class Setting(BaseModel):
    value: object
    drawing_revision: int | None = None
    initialize: bool = False


class StrategyEvaluation(BaseModel):
    config: dict
    lease: bool = False


@app.post('/api/strategy/evaluate')
async def strategy_evaluate(request: StrategyEvaluation):
    from .strategy_rules import validate_strategy, evaluate
    try:
        config=validate_strategy(request.config)
        key=validate(config['symbol'],config['period'],config['mode'])
        metadata = market_data.metadata(key[0])
        if request.lease and metadata['live_supported']:
            if key not in strategy_leases and len(strategy_leases)>=8:
                raise ValueError('策略行情最多使用 8 组股票/周期订阅')
            q=strategy_leases.get(key,(asyncio.Queue(maxsize=1),0))[0]
            listeners.setdefault(key,set()).add(q)
            strategy_leases[key]=(q,time.monotonic()+75)
            try:
                await asyncio.to_thread(streams.subscribe,key)
            except Exception:
                listeners.get(key,set()).discard(q);strategy_leases.pop(key,None)
                raise
        response=await bars(key[0],key[1],key[2],RETENTION_DAYS,limit=5000)
        def compute():
            return evaluate(config,response['bars'],python_runner=run_python_indicator)
        async with python_slots:
            result=await asyncio.to_thread(compute)
        result['stale']=response['stale']
        result['evaluated_at']=time.time()
        result['live']=stream_connected(key)
        result.update(metadata)
        if request.lease and (result['buy'] or result['sell']) and metadata['adjustment'] != 'none':
            result['execution_close'] = None
            if 'none' in market_data.for_market(key[0]).provider.adjustments:
                try:
                    actual = await actual_price_bars(*key, days=3, limit=100)
                except HTTPException as exc:
                    result['execution_issue'] = str(exc.detail)
                else:
                    if not actual['stale']:
                        result['execution_close'] = next((b['close'] for b in reversed(actual['bars'])
                                                          if b['time'] == result['bar_time']), None)
        return result
    except (ValueError,SyntaxError,TypeError) as exc:
        raise HTTPException(400,python_validation_error(exc))
    except QuotePermissionError as exc:
        raise HTTPException(403,str(exc))
    except RuntimeError as exc:
        raise HTTPException(503,str(exc))


def merge_watchlists(workspace, remote_groups, provider='opend', selected_markets=('US','CN')):
    workspace = workspace if isinstance(workspace, dict) else {}
    if not isinstance(workspace.get('markets'), dict):
        workspace = {'activeMarket': 'US', 'markets': {'US': workspace, 'CN': {}}}
    markets = workspace['markets']
    summary = {'US': {'groups': 0, 'symbols': 0}, 'CN': {'groups': 0, 'symbols': 0},
               'unsupported_symbols': 0}
    for market in ('US', 'CN'):
        current = markets.get(market)
        if not isinstance(current, dict):
            current = {}
        groups = current.get('groups')
        if not isinstance(groups, list):
            groups = []
        if not groups:
            defaults = os.getenv('DEFAULT_SYMBOLS', 'US.SNDK,US.SNXX,US.SNDQ').split(',') if market == 'US' else []
            groups = [{'id': 'featured', 'name': '精选', 'symbols': defaults}]
        current['groups'] = groups
        markets[market] = current
    prefix = 'moomoo' if provider == 'opend' else 'feed-' + provider
    for remote in remote_groups:
        valid = [s for s in remote['symbols'] if SYMBOL_RE.fullmatch(s)]
        summary['unsupported_symbols'] += len(remote['symbols']) - len(valid)
        for market, codes in (('US', [s for s in valid if s.startswith('US.')]),
                              ('CN', [s for s in valid if s.startswith(('SH.', 'SZ.'))])):
            if market not in selected_markets:
                continue
            groups = markets[market]['groups']
            group_id = prefix + '-' + hashlib.sha256((remote['kind'] + ':' + remote['name']).encode()).hexdigest()[:16]
            existing = next((g for g in groups if isinstance(g, dict) and g.get('id') == group_id), None)
            if existing is None:
                if not codes:
                    continue
                name = remote['name'][:24]
                if any(isinstance(g, dict) and g.get('name') == name for g in groups):
                    name = (remote['name'][:15] + ' · ' + provider)[:24]
                existing = {'id': group_id, 'name': name, 'symbols': []}
                groups.append(existing)
            existing['symbols'] = list(dict.fromkeys(codes))
            summary[market]['groups'] += 1
            summary[market]['symbols'] += len(existing['symbols'])
    return workspace, summary


merge_moomoo_groups = merge_watchlists


@app.post('/api/watchlists/import-moomoo', include_in_schema=False)
@app.post('/api/watchlists/import')
async def import_watchlists(market: str | None = None):
    if market is not None and market not in ('US','CN'):
        raise HTTPException(400,'市场须为 US 或 CN')
    selected = (market,) if market else ('US','CN')
    by_source = {}
    for m in selected:
        feed = market_data.for_market(m, 'watchlists')
        by_source.setdefault(feed.provider.source_id, (feed, []))[1].append(m)
    imports = []
    for provider, (feed, markets) in by_source.items():
        try:
            remote = await asyncio.to_thread(feed.feature('watchlists'))
            if not isinstance(remote, list):
                raise ValueError('自选分组须为列表')
            for group in remote:
                if (not isinstance(group, dict) or not isinstance(group.get('name'), str) or not isinstance(group.get('kind'), str)
                        or not isinstance(group.get('symbols'), list) or not all(isinstance(s, str) for s in group['symbols'])):
                    raise ValueError('自选分组格式无效')
            imports.append((provider, markets, remote))
        except ValueError as exc:
            raise HTTPException(422,str(exc))
        except Exception as exc:
            raise HTTPException(502,f'读取 {provider} 自选分组失败：{exc}')
    with connect_db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM settings WHERE key='workspace'").fetchone()
        workspace = json.loads(row['value']) if row else {}
        summary = {'US':{'groups':0,'symbols':0},'CN':{'groups':0,'symbols':0},'unsupported_symbols':0}
        for provider, markets, remote in imports:
            workspace, part = merge_watchlists(workspace, remote, provider, markets)
            for m in markets:
                summary[m] = part[m]
            summary['unsupported_symbols'] += part['unsupported_symbols']
        payload = json.dumps(workspace, ensure_ascii=False)
        if len(payload) > 100_000:
            raise HTTPException(413, '自选分组超出工作区容量')
        db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   ('workspace', payload))
    return {'value': workspace, 'summary': summary, 'remote_groups':sum(len(rows) for _,_,rows in imports), 'providers':list(by_source)}


@app.get('/api/settings/{key}')
def get_setting(key: str, drawings_only: bool = False, since: int = -1):
    if key not in ('workspace', 'templates', 'theme') and not re.fullmatch(r'depth-US\.[A-Z][A-Z0-9.]{0,11}', key):
        raise HTTPException(404)
    with connect_db() as db:
        if key == 'workspace':
            db.execute('BEGIN')
            if drawings_only and since == drawing_api.drawing_revision(db):
                return {'drawing_revision': since, 'changed': False}
            value, revision = drawing_api.load_workspace(db)
            if drawings_only:
                return {'drawing_revision': revision, 'changed': since != revision, **({'value': drawing_api.drawing_view(value)} if since != revision else {})}
            return {'value': value, 'drawing_revision': revision}
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if key == 'theme':
        return JSONResponse({'value': json.loads(row['value']) if row else None},
                            headers={'Cache-Control': 'no-store'})
    if row:
        return {'value': json.loads(row['value'])}
    return {'value': {'symbols': os.getenv('DEFAULT_SYMBOLS', 'US.SNDK,US.SNXX,US.SNDQ').split(','), 'layout': 1} if key == 'workspace' else {}}


@app.put('/api/settings/{key}')
def put_setting(key: str, setting: Setting):
    if key not in ('workspace', 'templates', 'theme') and not re.fullmatch(r'depth-US\.[A-Z][A-Z0-9.]{0,11}', key):
        raise HTTPException(404)
    if key == 'theme':
        if setting.value not in ('dark', 'light'):
            raise HTTPException(422, '主题须为 dark 或 light')
        with connect_db() as db:
            payload = json.dumps(setting.value)
            if setting.initialize:
                db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (key, payload))
            else:
                db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, payload))
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return {'value': json.loads(row['value'])}
    if key == 'workspace':
        if not isinstance(setting.value, dict):
            raise HTTPException(422, '工作区应为对象')
        with connect_db() as db:
            return drawing_api.save_browser_workspace(db, setting.value, setting.drawing_revision)
    if key.startswith('depth-'):
        v = setting.value
        if not isinstance(v, dict) or not isinstance(v.get('enabled'), bool) or not isinstance(v.get('cached'), bool):
            raise HTTPException(400, '盘口设置格式不正确')
        for field in ('amount', 'qty'):
            n = v.get(field)
            if isinstance(n, bool) or not isinstance(n, (float, int)) or not math.isfinite(n) or not 0 <= n <= 1e12:
                raise HTTPException(400, '盘口金额和股数须为有效非负数')
        if isinstance(v.get('count'), bool) or v.get('count') not in {1, 2, 3, 5, 8}:
            raise HTTPException(400, '盘口每边条数不正确')
        setting.value = {field: v[field] for field in ('enabled','cached','amount','qty','count')}
    payload = json.dumps(setting.value)
    if len(payload) > 100_000:
        raise HTTPException(413, '设置过大')
    with connect_db() as db:
        db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, payload))
    return {'ok': True}


@app.websocket('/api/stream')
async def stream(ws: WebSocket):
    header = os.getenv('TRUSTED_USER_HEADER', '')
    if header and not ws.headers.get(header):
        await ws.close(code=1008)
        return
    try:
        key = validate(ws.query_params.get('symbol', ''), ws.query_params.get('period', ''), ws.query_params.get('mode', 'all'))
    except ValueError:
        await ws.close(code=1008)
        return
    await ws.accept()
    meta = market_data.metadata(key[0])
    if not meta['live_supported']:
        await ws.send_json({'type': 'status', 'connected': False, **meta})
        await ws.close(code=1000)
        return
    q = asyncio.Queue(maxsize=10)
    listeners.setdefault(key, set()).add(q)
    try:
        await asyncio.to_thread(streams.subscribe, key)
        await ws.send_json({'type': 'status', 'connected': True, **meta})
        while True:
            try:
                await ws.send_json(await asyncio.wait_for(q.get(), timeout=25))
            except asyncio.TimeoutError:
                await ws.send_json({'type': 'heartbeat', 'connected': stream_connected(key)})
    except WebSocketDisconnect:
        pass
    except QuotePermissionError as exc:
        await ws.send_json({'type': 'error', 'code': 'permission_denied', 'message': str(exc), 'retry_after': 300})
        await ws.close(code=1008)
    except Exception as exc:
        await ws.send_json({'type': 'error', 'message': str(exc)})
    finally:
        listeners.get(key, set()).discard(q)


drawing_api.install(app, connect_db)

from .market_analysis import install as install_market_analysis
install_market_analysis(app, connect_db, path='/api/market-analysis', synchronous=False)

from .review import install as install_review
install_review(app, connect_db)

from .radar import install as install_radar
radar_service = install_radar(app, bridge, connect_db, external=market_data, opend_radar=opend_radar)
from .scan_service import ScanService
from .scan_api import install as install_scan
scan_service = ScanService(sys.modules[__name__], radar_service)
install_scan(app, scan_service)

STATIC = Path(__file__).parent / 'static'
if STATIC.exists():
    app.mount('/assets', StaticFiles(directory=STATIC / 'assets'), name='assets')

@app.get('/{path:path}')
def frontend(path: str):
    if not STATIC.exists():
        raise HTTPException(404, '前端尚未构建')
    if path.rstrip('/') == 'chart':
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        return HTMLResponse(html.replace('<html ', '<html data-market-entry="public" ', 1),
                            headers={'Cache-Control':'no-store, max-age=0'})
    return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-store, max-age=0'})
