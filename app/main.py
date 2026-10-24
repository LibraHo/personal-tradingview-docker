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
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .indicators import calculate
from .python_indicator_worker import validate_code, validate_inputs
from .depth import DepthFeed

depth_feed = DepthFeed()


async def depth_maintenance():
    while True:
        await asyncio.sleep(10)
        try:
            await asyncio.to_thread(depth_feed.cleanup)
        except Exception:
            pass

ET = ZoneInfo('America/New_York')
CN_TZ = ZoneInfo('Asia/Shanghai')
DB = os.getenv('DB_PATH', '/data/market.sqlite3')
HOST = os.getenv('OPEND_HOST', 'host.docker.internal')
PORT = int(os.getenv('OPEND_PORT', '11111'))
MAX_STREAMS = int(os.getenv('MAX_ACTIVE_STREAMS', '32'))
REFRESH = int(os.getenv('HISTORY_REFRESH_SECONDS', '120'))
DEFAULT_DAYS = int(os.getenv('HISTORY_DAYS', '5'))
RETENTION_DAYS = max(1, int(os.getenv('CACHE_RETENTION_DAYS', '30')))
DAILY_HISTORY_DAYS = max(1, int(os.getenv('DAILY_HISTORY_DAYS', '730')))
DAILY_RETENTION_DAYS = max(DAILY_HISTORY_DAYS, int(os.getenv('DAILY_CACHE_RETENTION_DAYS', '1825')))
SYMBOL_RE = re.compile(r'^(?:US\.[A-Z0-9.]{1,12}|(?:SH|SZ)\.[0-9]{6})$')
PERIODS = {'1m': 'K_1M', '5m': 'K_5M', '15m': 'K_15M', '30m': 'K_30M', '60m': 'K_60M', '1d': 'K_DAY'}
MODES = {'all': 'ALL', 'extended': 'ETH', 'regular': 'RTH'}
listeners: dict[tuple[str, str, str], set[asyncio.Queue]] = {}
last_fetch: dict[tuple[str, str, str], float] = {}
fetched_days: dict[tuple[str, str, str], int] = {}
fetch_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
python_slots = asyncio.Semaphore(1)
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
        db.executescript('''
        CREATE TABLE IF NOT EXISTS bars(symbol TEXT, period TEXT, mode TEXT, time INTEGER,
          open REAL, high REAL, low REAL, close REAL, volume REAL, turnover REAL,
          PRIMARY KEY(symbol,period,mode,time));
        CREATE INDEX IF NOT EXISTS bars_lookup ON bars(symbol,period,mode,time);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')


def prune_cache():
    now = datetime.now(ET)
    intraday_cutoff = int((now - timedelta(days=RETENTION_DAYS)).timestamp())
    daily_cutoff = int((now - timedelta(days=DAILY_RETENTION_DAYS)).timestamp())
    with connect_db() as db:
        db.execute("DELETE FROM bars WHERE period != '1d' AND time < ?", (intraday_cutoff,))
        db.execute("DELETE FROM bars WHERE period = '1d' AND time < ?", (daily_cutoff,))


def validate(symbol, period, mode):
    symbol = symbol.upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError('股票代码应为 US.AAPL、SH.600519 或 SZ.000001 格式')
    if period not in PERIODS or mode not in MODES:
        raise ValueError('不支持的周期或时段')
    if (period == '1d' or not symbol.startswith('US.')) and mode != 'regular':
        raise ValueError('A 股和日线请选择常规时段')
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
    d['session'], d['calendar_date'], d['trade_date'] = session_fields(d['time'], d['symbol'])
    if d['period'] == '1d':
        d['session'] = 'regular'
    d['session_date'] = d['trade_date'] + ':' + d['session']
    return d


def save_bars(key, bars):
    if not bars:
        return
    with connect_db() as db:
        db.executemany('''INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,period,mode,time) DO UPDATE SET
            open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
            volume=excluded.volume,turnover=excluded.turnover''',
            [(key[0], key[1], key[2], b['time'], b['open'], b['high'], b['low'], b['close'], b['volume'], b['turnover']) for b in bars])


def read_bars(key, days, limit):
    since = int((datetime.now(ET) - timedelta(days=days)).timestamp())
    with connect_db() as db:
        rows = db.execute('SELECT * FROM bars WHERE symbol=? AND period=? AND mode=? AND time>=? ORDER BY time DESC LIMIT ?', (*key, since, limit)).fetchall()
    return [row_to_bar(r) for r in reversed(rows)]


def read_bars_before(key, before, limit):
    retention = DAILY_RETENTION_DAYS if key[1] == '1d' else RETENTION_DAYS
    cutoff = int((datetime.now(ET) - timedelta(days=retention)).timestamp())
    with connect_db() as db:
        rows = db.execute('SELECT * FROM bars WHERE symbol=? AND period=? AND mode=? AND time<? AND time>=? ORDER BY time DESC LIMIT ?',
                          (*key, before, cutoff, limit)).fetchall()
    return [row_to_bar(r) for r in reversed(rows)]


def frame_to_bars(frame, symbol):
    result = []
    zone = ET if symbol.startswith('US.') else CN_TZ
    for record in frame.to_dict('records'):
        dt = datetime.strptime(str(record['time_key']), '%Y-%m-%d %H:%M:%S').replace(tzinfo=zone)
        result.append({'time': int(dt.timestamp()), 'open': float(record['open']), 'high': float(record['high']),
                       'low': float(record['low']), 'close': float(record['close']),
                       'volume': float(record.get('volume') or 0), 'turnover': float(record.get('turnover') or 0)})
    return result


def run_python_indicator(code, bars, inputs=None):
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


class Bridge:
    def __init__(self):
        self.ctx = None
        self.lock = threading.RLock()
        self.active: dict[tuple[str, str, str], float] = {}
        self.last_error = None
        self.last_request = 0.0
        self.last_activity = time.monotonic()
        self.snapshot_cache: dict[tuple[str, ...], tuple[float, list[dict]]] = {}

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
                if ret == RET_OK and loop:
                    for record in data.to_dict('records'):
                        label = str(record.get('k_type', '')).replace('K_', '').lower()
                        period = label if label in PERIODS else {'day': '1d'}.get(label)
                        if not period:
                            continue
                        symbol = str(record['code'])
                        for key in list(bridge.active):
                            if key[:2] == (symbol, period):
                                bars = frame_to_bars(data[data['code'] == symbol], symbol)
                                loop.call_soon_threadsafe(asyncio.create_task, publish(key, bars))
                return ret, data
        self.ctx = OpenQuoteContext(host=HOST, port=PORT, is_encrypt=bool(rsa_file))
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

    def history(self, key, days, end_date=None):
        from moomoo import KLType, AuType, Session, RET_OK
        with self.lock:
            try:
                ctx = self.ensure()
                end = end_date or datetime.now(ET if key[0].startswith('US.') else CN_TZ).date()
                start = end - timedelta(days=days)
                kwargs = dict(code=key[0], start=str(start), end=str(end), ktype=getattr(KLType, PERIODS[key[1]]),
                              autype=AuType.NONE, max_count=1000, session=Session.NONE if key[1] == '1d' or not key[0].startswith('US.') else getattr(Session, MODES[key[2]]))
                all_bars, page = [], None
                while True:
                    self.rate_limit()
                    ret, data, page = ctx.request_history_kline(**kwargs, page_req_key=page)
                    if ret != RET_OK:
                        raise RuntimeError(str(data))
                    all_bars.extend(frame_to_bars(data, key[0]))
                    if page is None:
                        break
                save_bars(key, all_bars)
                self.last_activity = time.monotonic()
                return len(all_bars)
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

    def user_watchlists(self):
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
            if key in self.active:
                return
            if len(self.active) >= MAX_STREAMS:
                raise RuntimeError('实时订阅已达到本服务配置的上限')
            try:
                ctx = self.ensure()
                self.rate_limit()
                session = Session.NONE if not key[0].startswith('US.') or key[1] == '1d' else getattr(Session, MODES[key[2]])
                ret, error = ctx.subscribe([key[0]], [getattr(SubType, PERIODS[key[1]])], session=session, subscribe_push=True)
                if ret != RET_OK:
                    raise RuntimeError(str(error))
                self.active[key] = time.monotonic()
                self.last_activity = time.monotonic()
            except Exception as exc:
                self.reset(exc)
                raise

    def unsubscribe_unused(self):
        from moomoo import SubType
        with self.lock:
            for key, start in list(self.active.items()):
                if listeners.get(key) or time.monotonic()-start < 65:
                    continue
                try:
                    self.rate_limit()
                    ret, error = self.ctx.unsubscribe([key[0]], [getattr(SubType, PERIODS[key[1]])])
                    if ret != 0:
                        raise RuntimeError(str(error))
                except Exception as exc:
                    self.reset(exc)
                    break
                self.active.pop(key, None)
                self.last_activity = time.monotonic()

    def close_if_idle(self):
        with self.lock:
            if self.ctx is not None and not self.active and not any(listeners.values()) and time.monotonic()-self.last_activity > 15:
                self.ctx.close()
                self.ctx = None


bridge = Bridge()


async def publish(key, bars):
    if key[2] != 'all':
        bars = [b for b in bars if session_fields(b['time'], key[0])[0] == 'regular' or
                (key[2] == 'extended' and session_fields(b['time'], key[0])[0] in ('pre', 'post'))]
    await asyncio.to_thread(save_bars, key, bars)
    for bar in bars:
        item = {'type': 'bar', 'bar': row_to_bar(dict(symbol=key[0], period=key[1], mode=key[2], **bar))}
        for q in tuple(listeners.get(key, ())):
            if q.full():
                q.get_nowait()
            q.put_nowait(item)


async def maintenance():
    previous_prune = 0.0
    while True:
        await asyncio.sleep(20)
        try:
            if time.monotonic() - previous_prune > 86400:
                await asyncio.to_thread(prune_cache)
                previous_prune = time.monotonic()
            await asyncio.to_thread(bridge.unsubscribe_unused)
            await asyncio.to_thread(bridge.close_if_idle)
            for key in list(listeners):
                if listeners[key] and key not in bridge.active:
                    await asyncio.to_thread(bridge.subscribe, key)
                    await asyncio.to_thread(bridge.history, key, 2)
                    last_fetch[key] = time.monotonic()
                elif listeners[key] and time.monotonic() - last_fetch.get(key, 0) > max(REFRESH, 600):
                    await asyncio.to_thread(bridge.history, key, 2)
                    last_fetch[key] = time.monotonic()
        except Exception as exc:
            bridge.last_error = str(exc)


@asynccontextmanager
async def lifespan(app):
    global loop
    init_db()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(maintenance())
    depth_task = asyncio.create_task(depth_maintenance())
    yield
    task.cancel()
    depth_task.cancel()
    await asyncio.to_thread(depth_feed.close)
    if bridge.ctx:
        await asyncio.to_thread(bridge.ctx.close)


app = FastAPI(title='NAS Market', lifespan=lifespan)


@app.middleware('http')
async def auth(request: Request, call_next):
    header = os.getenv('TRUSTED_USER_HEADER', '')
    if header and not request.headers.get(header):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': '登录后访问'}, status_code=401)
    return await call_next(request)


@app.get('/api/status')
def status():
    return {'opend_connected': bridge.ctx is not None, 'last_error': bridge.last_error,
            'active_streams': len(bridge.active), 'max_streams': MAX_STREAMS}


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
        return depth_feed.read(symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(503, '盘口连接异常，请检查 OpenD；旧盘口线已停用')


@app.get('/api/quotes')
async def quotes(symbols: str):
    codes = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    if not codes or len(codes) > 100 or any(not SYMBOL_RE.fullmatch(s) for s in codes):
        raise HTTPException(400, '请输入 1 至 100 个有效股票代码')
    try:
        data, stale = await asyncio.to_thread(bridge.snapshots, codes)
        return {'quotes': data, 'stale': stale}
    except Exception as exc:
        raise HTTPException(503, f'OpenD 快照不可用：{exc}')


@app.get('/api/bars')
async def bars(symbol: str, period: str = '5m', mode: str = 'all', days: int | None = None, limit: int = 5000, refresh: bool = False):
    try:
        key = validate(symbol, period, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if days is None:
        days = DAILY_HISTORY_DAYS if period == '1d' else DEFAULT_DAYS
    days = min(max(days, 1), DAILY_RETENTION_DAYS if period == '1d' else RETENTION_DAYS)
    limit = min(max(limit, 1), 10000)
    lock = fetch_locks.setdefault(key, asyncio.Lock())
    async with lock:
        if refresh or time.monotonic()-last_fetch.get(key, 0) > REFRESH or days > fetched_days.get(key, 0):
            try:
                refresh_days = days if days > fetched_days.get(key, 0) else min(days, 2)
                await asyncio.to_thread(bridge.history, key, refresh_days)
                last_fetch[key] = time.monotonic()
                fetched_days[key] = max(days, fetched_days.get(key, 0))
            except Exception as exc:
                cached = await asyncio.to_thread(read_bars, key, days, limit)
                if not cached:
                    raise HTTPException(503, f'OpenD 行情不可用：{exc}')
                return {'bars': cached, 'stale': True, 'error': str(exc)}
    return {'bars': await asyncio.to_thread(read_bars, key, days, limit), 'stale': False}


@app.get('/api/bars/older')
async def older_bars(symbol: str, period: str, mode: str, before: int, limit: int = 1000):
    try:
        key = validate(symbol, period, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if before <= 0 or before > int(time.time()) + 86400:
        raise HTTPException(400, '无效的历史时间')
    limit = min(max(limit, 1), 2000)
    retention = DAILY_RETENTION_DAYS if period == '1d' else RETENTION_DAYS
    cutoff = int((datetime.now(ET) - timedelta(days=retention)).timestamp())
    if before <= cutoff:
        return {'bars': [], 'next_before': before, 'has_more': False}
    lock = fetch_locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = await asyncio.to_thread(read_bars_before, key, before, limit)
        if cached:
            return {'bars': cached, 'next_before': cached[0]['time'], 'has_more': cached[0]['time'] > cutoff}
        zone = ET if key[0].startswith('US.') else CN_TZ
        end_date = datetime.fromtimestamp(before, zone).date()
        window_days = 365 if period == '1d' else 3 if period == '1m' else 10 if period == '5m' else 21 if period == '15m' else 35
        start_date = end_date - timedelta(days=window_days)
        try:
            await asyncio.to_thread(bridge.history, key, window_days, end_date)
        except Exception as exc:
            raise HTTPException(503, f'历史 K 线暂不可用：{exc}')
        result = await asyncio.to_thread(read_bars_before, key, before, limit)
        next_before = result[0]['time'] if result else int(datetime.combine(start_date, datetime.min.time(), zone).timestamp())
        return {'bars': result, 'next_before': next_before, 'has_more': next_before > cutoff}


@app.get('/api/indicators')
async def indicators(symbol: str, period: str, mode: str, name: str, params: str = '{}', reset: str = 'session', days: int | None = None):
    response = await bars(symbol, period, mode, days)
    try:
        values = calculate(response['bars'], name.upper(), json.loads(params), reset)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))
    return {'time': [b['time'] for b in response['bars']], 'values': values, 'stale': response['stale']}


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
    days = DAILY_HISTORY_DAYS if key[1] == '1d' else DEFAULT_DAYS
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


def merge_moomoo_groups(workspace, remote_groups):
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
    for remote in remote_groups:
        valid = [s for s in remote['symbols'] if SYMBOL_RE.fullmatch(s)]
        summary['unsupported_symbols'] += len(remote['symbols']) - len(valid)
        for market, codes in (('US', [s for s in valid if s.startswith('US.')]),
                              ('CN', [s for s in valid if s.startswith(('SH.', 'SZ.'))])):
            if not codes:
                continue
            groups = markets[market]['groups']
            group_id = 'moomoo-' + hashlib.sha256((remote['kind'] + ':' + remote['name']).encode()).hexdigest()[:16]
            existing = next((g for g in groups if isinstance(g, dict) and g.get('id') == group_id), None)
            if existing is None:
                name = remote['name'][:24]
                if any(isinstance(g, dict) and g.get('name') == name for g in groups):
                    name = (remote['name'][:15] + ' · moomoo')[:24]
                existing = {'id': group_id, 'name': name, 'symbols': []}
                groups.append(existing)
            existing['symbols'] = list(dict.fromkeys(codes))
            summary[market]['groups'] += 1
            summary[market]['symbols'] += len(existing['symbols'])
    return workspace, summary


@app.post('/api/watchlists/import-moomoo')
async def import_moomoo_watchlists():
    try:
        remote = await asyncio.to_thread(bridge.user_watchlists)
    except Exception as exc:
        raise HTTPException(502, f'读取 moomoo 自选分组失败：{exc}')
    with connect_db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM settings WHERE key='workspace'").fetchone()
        raw = json.loads(row['value']) if row else {}
        workspace, summary = merge_moomoo_groups(raw, remote)
        payload = json.dumps(workspace, ensure_ascii=False)
        if len(payload) > 100_000:
            raise HTTPException(413, '自选分组超出工作区容量')
        db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   ('workspace', payload))
    return {'value': workspace, 'summary': summary, 'remote_groups': len(remote)}


@app.get('/api/settings/{key}')
def get_setting(key: str):
    if key not in ('workspace', 'templates'):
        raise HTTPException(404)
    with connect_db() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if row:
        return {'value': json.loads(row['value'])}
    return {'value': {'symbols': os.getenv('DEFAULT_SYMBOLS', 'US.SNDK,US.SNXX,US.SNDQ').split(','), 'layout': 1} if key == 'workspace' else {}}


@app.put('/api/settings/{key}')
def put_setting(key: str, setting: Setting):
    if key not in ('workspace', 'templates'):
        raise HTTPException(404)
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
    q = asyncio.Queue(maxsize=10)
    listeners.setdefault(key, set()).add(q)
    try:
        await asyncio.to_thread(bridge.subscribe, key)
        await ws.send_json({'type': 'status', 'connected': True})
        while True:
            try:
                await ws.send_json(await asyncio.wait_for(q.get(), timeout=25))
            except asyncio.TimeoutError:
                await ws.send_json({'type': 'heartbeat', 'connected': key in bridge.active})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await ws.send_json({'type': 'error', 'message': str(exc)})
    finally:
        listeners.get(key, set()).discard(q)


STATIC = Path(__file__).parent / 'static'
if STATIC.exists():
    app.mount('/assets', StaticFiles(directory=STATIC / 'assets'), name='assets')

@app.get('/{path:path}')
def frontend(path: str):
    if not STATIC.exists():
        raise HTTPException(404, '前端尚未构建')
    return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-store, max-age=0'})
