"""Read-only, source-isolated account archives for the US ledger."""
import asyncio
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import HTTPException

from .broker_provider import ArchiveError, BrokerRejected, broker_config
from .ledger import ingest_broker

ET = ZoneInfo('America/New_York')
INTERVAL = 300
REQUEST_GAP = 4
log = logging.getLogger(__name__)


class WorkerStopping(Exception):
    """Keep the durable range for replay on restart."""


def schema(db, provider):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_broker_sync'").fetchone()
    if exists and db.execute('SELECT 1 FROM ledger_broker_sync WHERE provider=?', (provider,)).fetchone():
        return
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    db.execute("""CREATE TABLE IF NOT EXISTS ledger_broker_sync(
        provider TEXT PRIMARY KEY, state TEXT NOT NULL, message TEXT NOT NULL,
        last_success TEXT, range_start TEXT, range_end TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS ledger_broker_accounts(
        provider TEXT NOT NULL, account TEXT NOT NULL, through TEXT, as_of TEXT NOT NULL,
        PRIMARY KEY(provider,account))""")
    if provider == 'opend' and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_opend_sync'").fetchone():
        db.execute("""INSERT OR IGNORE INTO ledger_broker_sync
            SELECT 'opend',state,message,last_success,range_start,range_end FROM ledger_opend_sync WHERE singleton=1""")
        db.execute("""INSERT OR IGNORE INTO ledger_broker_accounts
            SELECT 'opend', account, through, as_of FROM ledger_opend_accounts""")
    db.execute("INSERT OR IGNORE INTO ledger_broker_sync(provider,state,message) VALUES(?,'idle','等待券商同步')", (provider,))


def diagnostic(exc):
    if isinstance(exc, ArchiveError):
        return str(exc)
    if isinstance(exc, BrokerRejected):
        return '券商未接受查询，请检查登录、账户权限或查询频率'
    if isinstance(exc, (ValueError, HTTPException)):
        return '券商数据未通过归档校验，请核对券商记录'
    if isinstance(exc, sqlite3.Error):
        return '归档数据库暂时无法读写'
    return '券商连接或归档失败，请检查服务状态'


class Sync:
    def __init__(self, connect_db, broker_factory=None, ingest=None, *, config=None):
        self.connect_db = connect_db
        self.config = config or broker_config()
        self.provider = self.config.source_id
        self.broker_factory = broker_factory or self.config.factory
        self.ingest = ingest or self.ingest_records
        self.wake = asyncio.Event()

    def ingest_records(self, connect, account, stamp, positions, fills):
        return ingest_broker(connect, account, stamp, positions, fills, provider=self.provider)

    @property
    def enabled(self):
        return 'archive' in self.config.capabilities

    @contextmanager
    def connect(self):
        with self.connect_db() as db:
            db.execute('PRAGMA busy_timeout=30000')
            yield db

    def status(self):
        if not self.enabled:
            return {'provider': self.provider, 'state':'disabled', 'accounts':[], 'interval_seconds':0,
                    'last_success':None, 'message':'当前未启用券商账户归档'}
        with self.connect() as db:
            schema(db, self.provider)
            row = db.execute('SELECT state,message,last_success FROM ledger_broker_sync WHERE provider=?', (self.provider,)).fetchone()
            accounts = [dict(r) for r in db.execute(
                'SELECT account,through,as_of FROM ledger_broker_accounts WHERE provider=? ORDER BY account', (self.provider,))]
        return {**dict(row), 'provider': self.provider, 'accounts': accounts, 'interval_seconds': INTERVAL}

    def queue(self, start=None, end=None):
        if not self.enabled:
            raise HTTPException(409, '当前未启用券商账户归档')
        if bool(start) != bool(end) or start and (
                start > end or end > datetime.now(ET).date() or (end-start).days >= 90):
            raise HTTPException(422, '请选择不超过 90 天、截至美东今天的完整起止日期')
        bounds = (str(start), str(end)) if start else (None, None)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            schema(db, self.provider)
            row = db.execute('SELECT * FROM ledger_broker_sync WHERE provider=?', (self.provider,)).fetchone()
            if row['state'] in ('queued', 'running'):
                if start and bounds != (row['range_start'], row['range_end']):
                    raise HTTPException(409, '已有同步任务，请等待完成后再补拉指定日期')
            else:
                db.execute("""UPDATE ledger_broker_sync SET state='queued',message='等待同步',
                              range_start=?,range_end=? WHERE provider=?""", (*bounds, self.provider))
        return self.status()

    def _account(self, broker, account_id, bounds, now, stopping):
        account = ('OpenD' if self.provider == 'opend' else self.provider) + ':REAL:' + account_id
        with self.connect() as db:
            cursor = db.execute('SELECT through FROM ledger_broker_accounts WHERE provider=? AND account=?', (self.provider,account)).fetchone()
        today = now.astimezone(ET).date()
        if bounds:
            start, end = bounds
        else:
            start = date.fromisoformat(cursor['through']) - timedelta(days=2) if cursor and cursor['through'] else today - timedelta(days=89)
            end = today
        positions = broker.archive_positions(account_id)
        stamp = datetime.now(timezone.utc).isoformat()
        while start <= end:
            if stopping.is_set():
                raise WorkerStopping()
            last = min(start + timedelta(days=89), end)
            fills = broker.archive_fills(account_id, start, last, now)
            self.ingest(self.connect, account, stamp, positions, fills)
            # Advancing after commit makes an interrupted import safe to replay. An explicit
            # historical backfill must never jump the automatic cursor over an unseen interval.
            through = None if bounds else last.isoformat()
            with self.connect() as db:
                db.execute('''INSERT INTO ledger_broker_accounts VALUES(?,?,?,?)
                    ON CONFLICT(provider,account) DO UPDATE SET through=coalesce(excluded.through,through),
                    as_of=excluded.as_of''', (self.provider, account, through, stamp))
            start = last + timedelta(days=1)
            if start <= end and stopping.wait(REQUEST_GAP):
                raise WorkerStopping()

    def once(self, stopping=None):
        if not self.enabled:
            return
        stopping = stopping or threading.Event()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            schema(db, self.provider)
            row = db.execute('SELECT range_start,range_end FROM ledger_broker_sync WHERE provider=?', (self.provider,)).fetchone()
            bounds = tuple(map(date.fromisoformat, row)) if row['range_start'] else None
            db.execute("UPDATE ledger_broker_sync SET state='running',message='正在读取券商持仓和成交' WHERE provider=?", (self.provider,))
        now = datetime.now(timezone.utc)
        broker = None
        problems = []
        try:
            broker = self.broker_factory()
            accounts = [r['acc_id'] for r in broker.accounts() if r['trd_env'] == 'REAL']
            if any(not isinstance(acc, str) or not acc.strip() or acc != acc.strip() for acc in accounts):
                raise ArchiveError('券商账户编号须为完整字符串')
            if not accounts:
                raise ArchiveError('券商未返回可读取的美股实盘账户')
            for account_id in dict.fromkeys(accounts):
                try:
                    if stopping.is_set():
                        raise WorkerStopping()
                    self._account(broker, account_id, bounds, now, stopping)
                except WorkerStopping:
                    raise
                except Exception as exc:
                    problems.append('账户尾号 ' + account_id[-4:] + '：' + diagnostic(exc))
                    log.warning('Broker ledger account sync failed (%s)', type(exc).__name__)
        except WorkerStopping:
            with self.connect() as db:
                db.execute("UPDATE ledger_broker_sync SET state='queued',message='服务重启后继续同步' WHERE provider=?", (self.provider,))
            return
        except Exception as exc:
            problems.append(diagnostic(exc))
            log.warning('Broker ledger sync failed (%s)', type(exc).__name__)
        finally:
            try:
                if broker is not None:
                    broker.close()
            except Exception as exc:
                log.warning('Closing Broker ledger context failed (%s)', type(exc).__name__)
        with self.connect() as db:
            if problems:
                db.execute("""UPDATE ledger_broker_sync SET state='error',message=?,
                              range_start=NULL,range_end=NULL WHERE provider=?""", ('；'.join(problems), self.provider))
            else:
                db.execute("""UPDATE ledger_broker_sync SET state='ready',message='同步完成',
                              last_success=?,range_start=NULL,range_end=NULL WHERE provider=?""",
                           (datetime.now(timezone.utc).isoformat(), self.provider))


@lru_cache(maxsize=16)
def _service(connect_db, config):
    return Sync(connect_db, config=config)


def service(connect_db):
    return _service(connect_db, broker_config())


async def run(connect_db):
    worker = service(connect_db)
    if not worker.enabled:
        return
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
            log.warning('Broker ledger worker storage unavailable (%s)', type(exc).__name__)
        # Avoid repeatedly hitting the broker when the client requests several refreshes.
        await asyncio.sleep(REQUEST_GAP)
        try:
            await asyncio.wait_for(worker.wake.wait(), INTERVAL - REQUEST_GAP)
        except asyncio.TimeoutError:
            pass


def install(app, agent, connect_db):
    worker = service(connect_db)

    @agent.get('/ledger/opend', include_in_schema=False)
    @agent.get('/ledger/broker', summary='读取美股持仓和成交自动同步状态')
    @app.get('/api/review/ledger/opend', include_in_schema=False)
    @app.get('/api/review/ledger/broker')
    def sync_status(market: Literal['US'] = 'US'):
        return worker.status()

    @agent.post('/ledger/opend/sync', include_in_schema=False)
    @agent.post('/ledger/broker/sync', summary='刷新美股持仓和成交，可按美东日期补拉历史')
    @app.post('/api/review/ledger/opend/sync', include_in_schema=False)
    @app.post('/api/review/ledger/broker/sync')
    async def sync_now(market: Literal['US'] = 'US', start: date | None = None, end: date | None = None):
        result = await asyncio.to_thread(worker.queue, start, end)
        if result['state'] == 'queued':
            worker.wake.set()
        return result
