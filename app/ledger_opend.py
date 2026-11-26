"""Read-only US account import. Runs in the single-worker market service."""
import asyncio
import logging
import math
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .ledger import OPTION, SYMBOL, ingest_opend
from .trading import BrokerRejected, OpenDBroker


ET = ZoneInfo('America/New_York')
INTERVAL = 300
# OpenD allows ten history requests per thirty seconds per account.
REQUEST_GAP = 4
log = logging.getLogger(__name__)


class ImportIssue(Exception):
    """A diagnostic suitable for a review client."""


class WorkerStopping(Exception):
    """Keep the durable range for replay on restart."""


def instrument(row):
    code = row.get('code') or ''
    match = OPTION.fullmatch(code)
    if match:
        root, expiry, right, strike = match.groups()
        try:
            day = date.fromisoformat('20' + expiry[:2] + '-' + expiry[2:4] + '-' + expiry[4:])
        except ValueError as exc:
            raise ImportIssue('期权合约到期日无法识别') from exc
        owner = row.get('stock_owner') or root
        if not re.fullmatch(SYMBOL['US'], owner) or int(strike) == 0:
            raise ImportIssue('期权标的或行权价无法识别')
        return dict(kind='option', symbol=owner, code=code, expiry=day.isoformat(),
                    strike=int(strike) / 1000, right=right)
    if not re.fullmatch(SYMBOL['US'], code):
        raise ImportIssue('券商返回了无法识别的美股证券代码')
    return dict(kind='stock', symbol=code, code=code)


def finite(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = math.nan
    if isinstance(value, bool) or not math.isfinite(number):
        raise ImportIssue('券商返回的' + label + '无效')
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
        raise ImportIssue('券商成交编号缺失或精度不明确')
    status = row.get('status')
    result = dict(broker_id=str(ident), broker_status=status)
    if status == 'CANCELLED':
        return result
    if status not in {'OK', 'CHANGED'}:
        raise ImportIssue('出现无法归档的券商成交状态')
    if row.get('trd_side') not in {'BUY', 'BUY_BACK', 'SELL', 'SELL_SHORT'}:
        raise ImportIssue('券商成交方向无法识别')
    try:
        raw_time = str(row.get('create_time'))
        # OpenD returns variable precision; Python 3.10 accepts only 3 or 6 fractional digits.
        raw_time = re.sub(r'(?<=\d:\d\d)\.(\d+)(?=Z|[+-]|$)',
                          lambda m: '.' + m[1][:6].ljust(6, '0'), raw_time)
        at = datetime.fromisoformat(raw_time.removesuffix('Z') + ('+00:00' if raw_time.endswith('Z') else ''))
    except ValueError as exc:
        raise ImportIssue('券商成交时间无效') from exc
    if at.tzinfo is None:
        at = at.replace(tzinfo=ET)
    return {**result, **instrument(row), 'at': at.isoformat(), 'side': row['trd_side'],
            'price': finite(row.get('price'), '成交价格'), 'qty': finite(row.get('qty'), '成交数量')}


def schema(db):
    # This table is created after the singleton, in the same initialization transaction.
    # Reading status while prices or an import are being written needs no writer lock.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_opend_accounts'").fetchone():
        return
    db.execute('''CREATE TABLE IF NOT EXISTS ledger_opend_sync (
        singleton INTEGER PRIMARY KEY, state TEXT NOT NULL, message TEXT NOT NULL,
        last_success TEXT, range_start TEXT, range_end TEXT)''')
    db.execute('''INSERT OR IGNORE INTO ledger_opend_sync(singleton,state,message)
                  VALUES(1,'idle','等待 OpenD 同步')''')
    db.execute('''CREATE TABLE IF NOT EXISTS ledger_opend_accounts (
        account TEXT PRIMARY KEY, through TEXT, as_of TEXT NOT NULL)''')


def diagnostic(exc):
    if isinstance(exc, ImportIssue):
        return str(exc)
    if isinstance(exc, BrokerRejected):
        return 'OpenD 未接受查询，请检查登录、账户权限或查询频率'
    if isinstance(exc, (ValueError, HTTPException)):
        return '券商数据未通过归档校验，请核对券商记录'
    if isinstance(exc, sqlite3.Error):
        return '归档数据库暂时无法读写'
    return 'OpenD 连接或归档失败，请检查服务状态'


class Sync:
    def __init__(self, connect_db, broker_factory=OpenDBroker, ingest=ingest_opend):
        self.connect_db = connect_db
        self.broker_factory = broker_factory
        self.ingest = ingest
        self.wake = asyncio.Event()

    @contextmanager
    def connect(self):
        with self.connect_db() as db:
            db.execute('PRAGMA busy_timeout=30000')
            yield db

    def status(self):
        with self.connect() as db:
            schema(db)
            row = db.execute('SELECT state,message,last_success FROM ledger_opend_sync').fetchone()
            accounts = [dict(r) for r in db.execute(
                'SELECT account,through,as_of FROM ledger_opend_accounts ORDER BY account')]
        return {**dict(row), 'accounts': accounts, 'interval_seconds': INTERVAL}

    def queue(self, start=None, end=None):
        if bool(start) != bool(end) or start and (
                start > end or end > datetime.now(ET).date() or (end-start).days >= 90):
            raise HTTPException(422, '请选择不超过 90 天、截至美东今天的完整起止日期')
        bounds = (str(start), str(end)) if start else (None, None)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            schema(db)
            row = db.execute('SELECT * FROM ledger_opend_sync').fetchone()
            if row['state'] in ('queued', 'running'):
                if start and bounds != (row['range_start'], row['range_end']):
                    raise HTTPException(409, '已有同步任务，请等待完成后再补拉指定日期')
            else:
                db.execute("""UPDATE ledger_opend_sync SET state='queued',message='等待同步',
                              range_start=?,range_end=? WHERE singleton=1""", bounds)
        return self.status()

    def _account(self, broker, account_id, bounds, now, stopping):
        account = 'OpenD:REAL:' + account_id
        with self.connect() as db:
            cursor = db.execute('SELECT through FROM ledger_opend_accounts WHERE account=?', (account,)).fetchone()
        today = now.astimezone(ET).date()
        if bounds:
            start, end = bounds
        else:
            start = date.fromisoformat(cursor['through']) - timedelta(days=2) if cursor and cursor['through'] else today - timedelta(days=89)
            end = today
        positions = [position(row) for row in broker.positions(account_id, 'REAL')]
        stamp = datetime.now(timezone.utc).isoformat()
        while start <= end:
            if stopping.is_set():
                raise WorkerStopping()
            last = min(start + timedelta(days=89), end)
            # The SDK date normalizer accepts whole seconds. Query through the next midnight to
            # cover 23:59:59.xxx and discard that exclusive endpoint for a past date range.
            exclusive_end = last + timedelta(days=1)
            until = now.astimezone(ET).strftime('%Y-%m-%d %H:%M:%S') if last == today else f'{exclusive_end} 00:00:00'
            context = broker.ensure()
            query = dict(acc_id=int(account_id), trd_env='REAL', deal_market='US')
            history = context.history_deal_list_query(**query, start=f'{start} 00:00:00', end=until)
            fills = []
            for row in reversed(broker.unpack(history)):
                if str(row.get('create_time', ''))[:10] != exclusive_end.isoformat():
                    fills.append(fill(row))
            if last == today:
                # The intraday endpoint refreshes directly from the broker; the historical
                # endpoint is newest first, while this one already returns chronological rows.
                live = context.deal_list_query(**query, refresh_cache=True)
                fills.extend(fill(row) for row in broker.unpack(live))
            self.ingest(self.connect, account, stamp, positions, fills)
            # Advancing after commit makes an interrupted import safe to replay. An explicit
            # historical backfill must never jump the automatic cursor over an unseen interval.
            through = None if bounds else last.isoformat()
            with self.connect() as db:
                db.execute('''INSERT INTO ledger_opend_accounts VALUES(?,?,?)
                    ON CONFLICT(account) DO UPDATE SET through=coalesce(excluded.through,through),
                    as_of=excluded.as_of''', (account, through, stamp))
            start = last + timedelta(days=1)
            if start <= end and stopping.wait(REQUEST_GAP):
                raise WorkerStopping()

    def once(self, stopping=None):
        stopping = stopping or threading.Event()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            schema(db)
            row = db.execute('SELECT range_start,range_end FROM ledger_opend_sync').fetchone()
            bounds = tuple(map(date.fromisoformat, row)) if row['range_start'] else None
            db.execute("UPDATE ledger_opend_sync SET state='running',message='正在读取 OpenD 持仓和成交'")
        now = datetime.now(timezone.utc)
        broker = self.broker_factory()
        problems = []
        try:
            accounts = [str(r['acc_id']) for r in broker.accounts() if r['trd_env'] == 'REAL']
            if not accounts:
                raise ImportIssue('OpenD 未返回可读取的美股实盘账户')
            for account_id in dict.fromkeys(accounts):
                try:
                    if stopping.is_set():
                        raise WorkerStopping()
                    self._account(broker, account_id, bounds, now, stopping)
                except WorkerStopping:
                    raise
                except Exception as exc:
                    problems.append('账户尾号 ' + account_id[-4:] + '：' + diagnostic(exc))
                    log.warning('OpenD ledger account sync failed (%s)', type(exc).__name__)
        except WorkerStopping:
            with self.connect() as db:
                db.execute("UPDATE ledger_opend_sync SET state='queued',message='服务重启后继续同步'")
            return
        except Exception as exc:
            problems.append(diagnostic(exc))
            log.warning('OpenD ledger sync failed (%s)', type(exc).__name__)
        finally:
            try:
                broker.close()
            except Exception as exc:
                log.warning('Closing OpenD ledger context failed (%s)', type(exc).__name__)
        with self.connect() as db:
            if problems:
                db.execute("""UPDATE ledger_opend_sync SET state='error',message=?,
                              range_start=NULL,range_end=NULL""", ('；'.join(problems),))
            else:
                db.execute("""UPDATE ledger_opend_sync SET state='ready',message='同步完成',
                              last_success=?,range_start=NULL,range_end=NULL""",
                           (datetime.now(timezone.utc).isoformat(),))


@lru_cache(maxsize=16)
def service(connect_db):
    return Sync(connect_db)


async def run(connect_db):
    worker = service(connect_db)
    worker.wake = asyncio.Event()
    stopping = threading.Event()
    while True:
        worker.wake.clear()
        pending = asyncio.create_task(asyncio.to_thread(worker.once, stopping))
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            stopping.set()
            await pending
            raise
        except (OSError, sqlite3.Error) as exc:
            log.warning('OpenD ledger worker storage unavailable (%s)', type(exc).__name__)
        # Avoid repeatedly hitting the broker when the client requests several refreshes.
        await asyncio.sleep(REQUEST_GAP)
        try:
            await asyncio.wait_for(worker.wake.wait(), INTERVAL - REQUEST_GAP)
        except asyncio.TimeoutError:
            pass


def install(app, agent, connect_db):
    worker = service(connect_db)

    @agent.get('/ledger/opend', summary='读取美股持仓和成交自动同步状态')
    @app.get('/api/review/ledger/opend')
    def sync_status(market: Literal['US'] = 'US'):
        return worker.status()

    @agent.post('/ledger/opend/sync', summary='刷新美股持仓和成交，可按美东日期补拉历史')
    @app.post('/api/review/ledger/opend/sync')
    async def sync_now(market: Literal['US'] = 'US', start: date | None = None, end: date | None = None):
        result = await asyncio.to_thread(worker.queue, start, end)
        if result['state'] == 'queued':
            worker.wake.set()
        return result
