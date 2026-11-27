"""Persistent plans, broker fills and account position snapshots for the trading journal."""
import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator


Market = Literal['CN', 'US']
Side = Literal['BUY', 'SELL', 'SELL_SHORT', 'BUY_BACK']
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Finite = Annotated[float, Field(allow_inf_nan=False)]
SYMBOL = {'CN': r'(?:SH|SZ|BJ)\.[0-9]{6}', 'US': r'US\.[A-Z][A-Z0-9.\-]{0,15}'}
OPTION = re.compile(r'(US\.[A-Z][A-Z0-9.\-]*?)(\d{6})([CP])(\d{1,10})')


def fail(detail, status=422):
    raise HTTPException(status, detail)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def now():
    return stamp(datetime.now(timezone.utc))


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode('utf8')).hexdigest()


def validate_symbol(symbol, market):
    if not re.fullmatch(SYMBOL[market], symbol) or (market == 'US' and OPTION.fullmatch(symbol)):
        fail('请填写当前市场的标的代码')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)


PlanPeriod = Literal['1m', '5m', '15m', '30m', '60m', '120m', '240m', '1d', '1w', '1mo']
Note = Annotated[str, StringConstraints(max_length=5000)]


class PlanCondition(Input):
    id: Key
    source: Literal['SIXPULSE', 'BOLL', 'SMA', 'EMA', 'BBI', 'VWAP', 'MACD', 'RSI', 'PRICE']
    period: PlanPeriod
    signal: Literal['reds', 'greens', 'above', 'below', 'bullish', 'bearish']
    line: Literal['main', 'upper', 'mid', 'lower'] = 'main'
    threshold: float = Field(default=6, ge=0, allow_inf_nan=False)
    params: dict[str, Any] = Field(default_factory=dict, max_length=24)
    confirmation: Literal['close', 'live'] = 'close'

    @model_validator(mode='after')
    def valid_indicator_condition(self):
        from .sixpulse import DEFAULTS
        allowed = {'SIXPULSE': set(DEFAULTS), 'BOLL': {'period', 'stddev'}, 'SMA': {'period'},
                   'EMA': {'period'}, 'BBI': {'periods'}, 'VWAP': {'reset'},
                   'MACD': {'fast', 'slow', 'signal'}, 'RSI': {'period'}, 'PRICE': set()}
        signals = ('reds', 'greens') if self.source == 'SIXPULSE' else ('bullish', 'bearish') if self.source == 'MACD' else ('above', 'below')
        if self.signal not in signals or set(self.params) - allowed[self.source]:
            raise ValueError('指标、条件或参数不匹配')
        if self.source == 'SIXPULSE' and (self.threshold != int(self.threshold) or not 1 <= self.threshold <= 6):
            raise ValueError('六脉红绿数须为 1–6 的整数')
        if self.source == 'RSI' and not 0 < self.threshold < 100:
            raise ValueError('RSI 阈值须在 0–100 之间')
        if self.source == 'PRICE' and self.threshold <= 0:
            raise ValueError('价格条件须大于零')
        if self.source == 'BOLL' and self.line not in ('upper', 'mid', 'lower'):
            raise ValueError('请选择布林上轨、中轨或下轨')
        for key, value in self.params.items():
            if key == 'reset':
                if value not in ('session', 'day', 'never'):
                    raise ValueError('VWAP 重置方式无效')
            elif key == 'periods':
                if not isinstance(value, list) or not 1 <= len(value) <= 12 or any(type(n) is not int or not 1 <= n <= 2000 for n in value):
                    raise ValueError('BBI 周期须为 1–2000 的整数')
            elif type(value) not in (int, float) or not 0 < value <= 2000 or (key != 'stddev' and int(value) != value):
                raise ValueError('指标周期或倍数无效')
        if self.source == 'SIXPULSE':
            from .advanced_indicators import parameters
            self.params = parameters('SIXPULSE', self.params)
        if self.source == 'MACD' and self.params.get('fast', 12) >= self.params.get('slow', 26):
            raise ValueError('MACD 慢线周期须大于快线周期')
        defaults = {'BOLL': {'period': 20, 'stddev': 2}, 'SMA': {'period': 20}, 'EMA': {'period': 20},
                    'BBI': {'periods': [3, 6, 12, 24]}, 'VWAP': {'reset': 'session'},
                    'MACD': {'fast': 12, 'slow': 26, 'signal': 9}, 'RSI': {'period': 14}}
        self.params = {**defaults.get(self.source, {}), **self.params}
        return self


class PlanConditions(Input):
    join: Literal['all', 'any'] = 'all'
    items: list[PlanCondition] = Field(default_factory=list, max_length=12)


class DefenseReference(Input):
    condition: PlanCondition | None = None
    period: PlanPeriod
    label: Annotated[str, StringConstraints(min_length=1, max_length=160)]


class PlanRisk(Input):
    defense_reference: DefenseReference | None = None
    entry_price: Positive | None = None
    qty: Positive | None = None
    budget: Positive | None = None
    max_position_percent: float | None = Field(default=None, gt=0, le=100)
    defense_source: Annotated[str, StringConstraints(max_length=200)] = '手动填写'
    note: Note = ''


class PlanLevels(Input):
    previous_high: Positive | None = None
    previous_low: Positive | None = None
    platform_high: Positive | None = None
    platform_low: Positive | None = None
    gap_up: Positive | None = None
    gap_down: Positive | None = None
    take_profit: Positive | None = None

    @model_validator(mode='after')
    def ordered_ranges(self):
        if self.platform_high is not None and self.platform_low is not None and self.platform_high < self.platform_low:
            raise ValueError('前期平台上沿不能低于下沿')
        return self


class PlanReference(Input):
    label: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    price: Positive
    period: PlanPeriod
    bar_time: int = Field(ge=0)


class PlanDetails(Input):
    tracking_period: PlanPeriod | None = None
    strategy: Literal['indicator', 'limit_up', 'news', 'other'] = 'indicator'
    structure_mode: Literal['manual', 'auto'] = 'manual'
    version: Literal[1] = 1
    title: Annotated[str, StringConstraints(max_length=100)] = ''
    entry: PlanConditions = Field(default_factory=PlanConditions)
    exit: PlanConditions = Field(default_factory=PlanConditions)
    entry_note: Note = ''
    exit_note: Note = ''
    notes: Note = ''
    risk: PlanRisk = Field(default_factory=PlanRisk)
    levels: PlanLevels = Field(default_factory=PlanLevels)
    mode: Literal['regular', 'extended', 'all'] = 'regular'
    references: list[PlanReference] = Field(default_factory=list, max_length=30)
    author: Literal['manual', 'agent'] = 'manual'

    @model_validator(mode='after')
    def unique_condition_ids(self):
        if self.strategy == 'limit_up' and (self.entry.items or self.exit.items or self.risk.defense_reference):
            raise ValueError('打板计划使用封板与回封条件')
        if self.strategy in ('news', 'other') and self.entry.items:
            raise ValueError('新闻驱动和其他入场方式使用文字触发条件')
        identifiers = [item.id for item in self.entry.items + self.exit.items]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError('每个入场和出场条件须使用独立编号')
        return self


class Plan(Input):
    symbol: Key
    period: PlanPeriod
    side: Literal['BUY', 'SELL']
    trigger: Text
    size: Annotated[str, StringConstraints(max_length=2000)] = ''
    stop: Positive | None = None
    status: Literal['draft', 'active', 'closed', 'skipped'] = 'active'
    details: PlanDetails | None = None


class NewPlan(Plan):
    request_id: Key


class UpdatePlan(Plan):
    revision: int = Field(ge=1)
    request_id: Key | None = None


class Instrument(Input):
    symbol: Key
    code: Key
    kind: Literal['stock', 'option']
    expiry: date | None = None
    strike: Positive | None = None
    right: Literal['C', 'P'] | None = None

    def check(self, market):
        validate_symbol(self.symbol, market)
        if self.kind == 'stock':
            if self.code != self.symbol or any(v is not None for v in (self.expiry, self.strike, self.right)):
                fail('正股代码须与标的相同，且不能带期权字段')
            return
        if self.expiry is None or self.strike is None or self.right is None or self.code == self.symbol:
            fail('期权须提供独立合约代码、到期日、行权价和认购/认沽')
        if market == 'US':
            parsed = OPTION.fullmatch(self.code)
            adjusted_root = parsed and re.fullmatch(re.escape(self.symbol) + r'[0-9]*', parsed[1])
            if not adjusted_root or parsed[2] != self.expiry.strftime('%y%m%d') or parsed[3] != self.right or int(parsed[4])/1000 != self.strike:
                fail('期权合约代码与标的、到期日、行权价或方向不一致')
        elif not re.fullmatch(r'(SH|SZ)\.[0-9]{8}', self.code):
            fail('A 股期权代码格式应为 SH. 或 SZ. 加八位合约代码')


class Trade(Instrument):
    at: AwareDatetime
    side: Side
    qty: Positive
    price: Positive

    @model_validator(mode='after')
    def contract_quantity(self):
        if self.kind == 'option' and not self.qty.is_integer():
            raise ValueError('期权数量须为整数张')
        return self


class Fill(Trade):
    account: Key
    broker_id: Key | None = None
    request_id: Key
    manual_confirm: bool = False
    plan_id: str | None = Field(default=None, max_length=32)
    source: Literal['manual', 'screenshot'] = 'manual'


class BrokerFill(Trade):
    broker_id: Key
    broker_status: Literal['OK', 'CHANGED'] = 'OK'


class Cancelled(Input):
    broker_id: Key


class Position(Instrument):
    qty: Finite
    cost: Finite | None = None

    @model_validator(mode='after')
    def contract_quantity(self):
        if self.kind == 'option' and not self.qty.is_integer():
            raise ValueError('期权持仓须为整数张')
        return self


class Snapshot(Input):
    account: Key
    as_of: AwareDatetime
    complete: bool
    rows: list[Position] = Field(max_length=5000)
    source: Literal['manual', 'screenshot'] = 'screenshot'


class TradeReview(Input):
    revision: int = Field(ge=1)
    plan_id: str | None = Field(default=None, max_length=32)
    execution: Text
    quality: Text
    note: str = Field(default='', max_length=5000)
    group_ids: list[Key] = Field(default_factory=list, max_length=100)
    group_revisions: dict[Key, int] = Field(default_factory=dict, max_length=100)


class Reconcile(Input):
    manual_id: Key
    broker_fill_id: Key

    @model_validator(mode='before')
    @classmethod
    def legacy_field(cls, value):
        if isinstance(value, dict) and 'opend_id' in value and 'broker_fill_id' not in value:
            return {**{key: item for key, item in value.items() if key != 'opend_id'},
                    'broker_fill_id': value['opend_id']}
        return value


class PlanFillLink(Input):
    revision: int = Field(ge=1)


DDL = (
    '''CREATE TABLE IF NOT EXISTS ledger_plans(
        market TEXT NOT NULL,id TEXT NOT NULL,symbol TEXT NOT NULL,revision INTEGER NOT NULL,
        effective TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(market,id,revision))''',
    'CREATE INDEX IF NOT EXISTS ledger_plan_symbol ON ledger_plans(market,symbol,id,revision)',
    '''CREATE TABLE IF NOT EXISTS ledger_fills(
        id TEXT PRIMARY KEY,market TEXT NOT NULL,account TEXT NOT NULL,symbol TEXT NOT NULL,
        code TEXT NOT NULL,at TEXT NOT NULL,broker_id TEXT,value TEXT NOT NULL,alias_of TEXT,
        UNIQUE(market,account,broker_id))''',
    'CREATE INDEX IF NOT EXISTS ledger_fill_symbol ON ledger_fills(market,symbol,at)',
    'CREATE INDEX IF NOT EXISTS ledger_fill_time ON ledger_fills(market,at DESC,id) WHERE alias_of IS NULL',
    'CREATE INDEX IF NOT EXISTS ledger_fill_match ON ledger_fills(market,account,code,at)',
    'CREATE INDEX IF NOT EXISTS ledger_fill_alias ON ledger_fills(market,alias_of) WHERE alias_of IS NOT NULL',
    '''CREATE TABLE IF NOT EXISTS ledger_requests(
        market TEXT NOT NULL,kind TEXT NOT NULL,request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
        record_id TEXT NOT NULL,PRIMARY KEY(market,kind,request_id))''',
    '''CREATE TABLE IF NOT EXISTS ledger_cancelled(
        account TEXT NOT NULL,broker_id TEXT NOT NULL,PRIMARY KEY(account,broker_id))''',
    '''CREATE TABLE IF NOT EXISTS ledger_accounts(
        market TEXT NOT NULL,account TEXT NOT NULL,as_of TEXT NOT NULL,complete INTEGER NOT NULL,
        source TEXT NOT NULL,PRIMARY KEY(market,account))''',
    '''CREATE TABLE IF NOT EXISTS ledger_positions(
        market TEXT NOT NULL,account TEXT NOT NULL,code TEXT NOT NULL,symbol TEXT NOT NULL,
        as_of TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(market,account,code))''',
    '''CREATE TABLE IF NOT EXISTS ledger_snapshot_receipts(
        market TEXT NOT NULL, account TEXT NOT NULL, fingerprint TEXT NOT NULL,
        result TEXT NOT NULL, PRIMARY KEY(market,account,fingerprint))''',
    '''CREATE TABLE IF NOT EXISTS ledger_plan_daily(
        market TEXT NOT NULL,id TEXT NOT NULL,day TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(market,id,day))''',
    '''CREATE TABLE IF NOT EXISTS ledger_plan_daily_status(
        market TEXT NOT NULL,id TEXT NOT NULL,expected_day TEXT,checked_at TEXT NOT NULL,error TEXT,PRIMARY KEY(market,id))''',
    '''CREATE TABLE IF NOT EXISTS ledger_plan_bars(
        market TEXT NOT NULL,id TEXT NOT NULL,end INTEGER NOT NULL,day TEXT NOT NULL,
        retry_at INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(market,id,end))''',
    '''CREATE TABLE IF NOT EXISTS plan_fill_settings(
        id INTEGER PRIMARY KEY CHECK(id=1),provider TEXT NOT NULL,url TEXT NOT NULL,token TEXT NOT NULL,agent TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS plan_fill_runs(
        id TEXT PRIMARY KEY,market TEXT NOT NULL,symbol TEXT NOT NULL,provider TEXT NOT NULL,
        started TEXT NOT NULL,finished TEXT,status TEXT NOT NULL,error TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS plan_fill_runs_symbol ON plan_fill_runs(market,symbol,started DESC)',
    # Last migration statement. Readers probe this index without reserving a SQLite writer lock.
    'CREATE INDEX IF NOT EXISTS ledger_position_symbol ON ledger_positions(market,symbol,account,code)',
)


def schema(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='plan_fill_runs_symbol'").fetchone():
        return
    # Execute statements separately: executescript implicitly commits an enclosing transaction.
    for sql in DDL:
        db.execute(sql)


@contextmanager
def transaction(connect_db, write=False):
    with connect_db() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db


def resolve_fill_id(db, market, ident):
    row = db.execute('SELECT COALESCE(alias_of,id) FROM ledger_fills WHERE market=? AND id=?', (market, ident)).fetchone()
    return row[0] if row else None


def reference_ids(db, market, kind, ident):
    if kind == 'plan':
        found = db.execute('SELECT 1 FROM ledger_plans WHERE market=? AND id=? LIMIT 1', (market, ident)).fetchone()
        return [ident] if found else []
    if kind != 'fill':
        return []
    canonical = resolve_fill_id(db, market, ident)
    if canonical is None:
        return []
    aliases = db.execute('SELECT id FROM ledger_fills WHERE market=? AND alias_of=? ORDER BY id', (market, canonical))
    return [canonical, *(row[0] for row in aliases)]


def reference_exists(db, market, kind, ident):
    return bool(reference_ids(db, market, kind, ident))


def plan_record(db, market, ident):
    rows = db.execute('SELECT value FROM ledger_plans WHERE market=? AND id=? ORDER BY revision', (market, ident))
    versions = [json.loads(row[0]) for row in rows]
    if not versions:
        fail('计划不存在', 404)
    return {**versions[-1], 'history': versions}


def snapshot_plan(db, market, ident, symbol, at, side, *, review_link=False):
    if not ident:
        return None
    plan = plan_record(db, market, ident)
    if plan['symbol'] != symbol:
        fail('计划与成交的标的不一致')
    if plan['side'] != ('SELL' if side.startswith('SELL') else 'BUY'):
        fail('计划与成交的方向不符')
    eligible = [v for v in plan['history'] if v['updated_at'] <= at]
    if review_link and (not eligible or eligible[-1]['status'] != 'active'):
        return None
    if not eligible:
        fail('这笔成交发生时计划尚未建立，请按计划外交易复盘')
    active = eligible[-1]
    if active['status'] != 'active':
        fail('成交时该计划未生效或方向不符')
    return active


def request_record(db, market, kind, key, value):
    fingerprint = digest(value)
    row = db.execute('SELECT fingerprint,record_id FROM ledger_requests WHERE market=? AND kind=? AND request_id=?',
                     (market, kind, key)).fetchone()
    if row and row[0] != fingerprint:
        fail('相同请求编号已用于不同内容', 409)
    return row[1] if row else None


def remember(db, market, kind, key, value, ident):
    db.execute('INSERT INTO ledger_requests VALUES(?,?,?,?,?)', (market, kind, key, digest(value), ident))


def fill_data(db, market, ident):
    canonical = resolve_fill_id(db, market, ident)
    if canonical is None:
        fail('成交不存在', 404)
    return json.loads(db.execute('SELECT value FROM ledger_fills WHERE id=?', (canonical,)).fetchone()[0])


def write_fill(db, fill):
    db.execute('''INSERT INTO ledger_fills(id,market,account,symbol,code,at,broker_id,value) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET account=excluded.account,symbol=excluded.symbol,code=excluded.code,
        at=excluded.at,broker_id=excluded.broker_id,value=excluded.value''',
        (fill['id'], fill['market'], fill['account'], fill['symbol'], fill['code'], fill['at'], fill.get('broker_id'), dump(fill)))


def trade_fields(raw):
    fields = {k: getattr(raw, k) for k in Trade.model_fields}
    fields['expiry'] = raw.expiry.isoformat() if raw.expiry else None
    fields['at'] = stamp(raw.at)
    return fields


def new_fill(db, market, account, fields, source, broker_id, plan_id=None):
    result = {**fields, 'id': uuid.uuid4().hex, 'market': market, 'account': account,
              'broker_id': broker_id, 'source': source, 'broker_status': 'OK', 'revision': 1,
              'plan_id': plan_id or None, 'plan_snapshot': snapshot_plan(db, market, plan_id, fields['symbol'], fields['at'], fields['side']),
              'review': None}
    write_fill(db, result)
    return result


def save_manual(db, market, body):
    body.check(market)
    if market == 'US' and not body.manual_confirm:
        fail('美股成交由券商同步，明确补录时请传 manual_confirm=true')
    fields = trade_fields(body)
    payload = {**fields, 'account': body.account, 'broker_id': body.broker_id, 'plan_id': body.plan_id, 'source': body.source}
    old_id = request_record(db, market, 'fill', body.request_id, payload)
    if old_id:
        return fill_data(db, market, old_id)
    existing = db.execute('SELECT value FROM ledger_fills WHERE market=? AND account=? AND broker_id=?',
                          (market, body.account, body.broker_id)).fetchone()
    if existing:
        result = json.loads(existing[0])
        if any(result[k] != v for k, v in fields.items()) or (body.plan_id and result['plan_id'] != body.plan_id):
            fail('此账户的成交编号已存在，但明细不同，请核对', 409)
    else:
        if market == 'US' and body.broker_id and db.execute('SELECT 1 FROM ledger_cancelled WHERE account=? AND broker_id=?',
                                                             (body.account, body.broker_id)).fetchone():
            fail('此券商成交编号已撤销，请先核对记录', 409)
        result = new_fill(db, market, body.account, fields, body.source, body.broker_id, body.plan_id)
    remember(db, market, 'fill', body.request_id, payload, result['id'])
    return result


def broker_source(source):
    return source == 'opend' or source.startswith('broker:')


def candidate_pair(manual, imported):
    if broker_source(manual['source']) or not broker_source(imported['source']) or manual.get('broker_id') or imported['broker_status'] == 'CANCELLED':
        return False
    keys = ('market', 'account', 'code', 'symbol', 'side', 'qty', 'price', 'expiry', 'strike', 'right')
    if any(manual[k] != imported[k] for k in keys):
        return False
    delta = datetime.fromisoformat(manual['at']) - datetime.fromisoformat(imported['at'])
    return abs(delta.total_seconds()) < 60


def fill_view(db, fill):
    # The range is indexed and keeps densely traded accounts from scanning all prior deals.
    at = datetime.fromisoformat(fill['at'])
    hits = db.execute('''SELECT value FROM ledger_fills WHERE market=? AND account=? AND code=?
        AND at BETWEEN ? AND ? AND id<>? AND alias_of IS NULL''', (fill['market'], fill['account'], fill['code'],
        stamp(at-timedelta(minutes=1)), stamp(at+timedelta(minutes=1)), fill['id']))
    candidates = []
    if fill['market'] == 'US':
        for row in hits:
            item = json.loads(row[0])
            if candidate_pair(fill, item) or candidate_pair(item, fill):
                candidates.append(item['id'])
    aliases = reference_ids(db, fill['market'], 'fill', fill['id'])[1:]
    return {**fill, 'candidate_ids': candidates, 'aliases': aliases}


def save_snapshot(db, market, body, source):
    as_of = stamp(body.as_of)
    account = body.account
    rows = {}
    for item in body.rows:
        item.check(market)
        if item.code in rows:
            fail('同一份持仓截图中合约代码重复')
        rows[item.code] = {**item.model_dump(mode='json'), 'account': account, 'as_of': as_of, 'source': source}
    fingerprint = None
    if not broker_source(source):
        fingerprint = digest([as_of, body.complete, source, rows])
        receipt = db.execute('SELECT result FROM ledger_snapshot_receipts WHERE market=? AND account=? AND fingerprint=?',
                             (market, account, fingerprint)).fetchone()
        if receipt:
            return {**json.loads(receipt[0]), 'status': 'already_imported'}
    previous = db.execute('SELECT * FROM ledger_accounts WHERE market=? AND account=?', (market, account)).fetchone()
    if previous and previous['as_of'] > as_of:
        if broker_source(source):
            return {'status': 'older_snapshot', 'as_of': previous['as_of']}
        fail('该账户已有更新的持仓记录，请核对截图时间', 409)
    same_stamp = previous and previous['as_of'] == as_of
    if same_stamp:
        known = {r['code']: json.loads(r['value']) for r in db.execute(
            'SELECT code,value FROM ledger_positions WHERE market=? AND account=? AND as_of=?', (market, account, as_of))}
        for code, item in rows.items():
            if (code in known and item != known[code]) or (previous['complete'] and item['qty'] and code not in known):
                fail('相同时间的持仓记录存在差异，请核对', 409)
        if body.complete and any(code not in rows and item['qty'] for code, item in known.items()):
            fail('同一时刻的完整与局部记录不一致', 409)
    if body.complete:
        db.execute('DELETE FROM ledger_positions WHERE market=? AND account=?', (market, account))
    for code, row in rows.items():
        # Retain explicit zeroes internally so conflicting screenshots at the same timestamp are detected.
        db.execute('INSERT OR REPLACE INTO ledger_positions VALUES(?,?,?,?,?,?)',
                   (market, account, code, row['symbol'], as_of, dump(row)))
    complete = body.complete or bool(same_stamp and previous['complete'])
    db.execute('INSERT OR REPLACE INTO ledger_accounts VALUES(?,?,?,?,?)', (market, account, as_of, complete, source))
    result = {'status': 'ok', 'account': account, 'as_of': as_of, 'complete': complete, 'rows': len(rows)}
    if fingerprint:
        db.execute('INSERT INTO ledger_snapshot_receipts VALUES(?,?,?,?)', (market, account, fingerprint, dump(result)))
    return result


def ingest_opend(connect_db, account, as_of, rows, fills):
    return ingest_broker(connect_db, account, as_of, rows, fills, provider='opend')


def ingest_broker(connect_db, account, as_of, rows, fills, *, provider):
    source = 'opend' if provider == 'opend' else 'broker:' + provider
    snapshot = Snapshot(account=account, as_of=as_of, complete=True, rows=rows)
    counts = {'inserted': 0, 'updated': 0, 'unchanged': 0}
    with transaction(connect_db, True) as db:
        positions = save_snapshot(db, 'US', snapshot, source)
        for raw in fills:
            cancelled = raw.get('broker_status') == 'CANCELLED'
            if cancelled:
                broker_id = Cancelled(broker_id=raw.get('broker_id')).broker_id
                db.execute('INSERT OR IGNORE INTO ledger_cancelled VALUES(?,?)', (account, broker_id))
            else:
                broker = BrokerFill.model_validate(raw)
                broker.check('US')
                broker_id = broker.broker_id
                if db.execute('SELECT 1 FROM ledger_cancelled WHERE account=? AND broker_id=?', (account, broker_id)).fetchone():
                    counts['unchanged'] += 1
                    continue
            row = db.execute("SELECT value FROM ledger_fills WHERE market='US' AND account=? AND broker_id=?", (account, broker_id)).fetchone()
            if not row and cancelled:
                counts['unchanged'] += 1
                continue
            if not row:
                item = new_fill(db, 'US', account, trade_fields(broker), source, broker_id)
                if broker.broker_status != 'OK':
                    write_fill(db, {**item, 'broker_status': broker.broker_status})
                counts['inserted'] += 1
                continue
            old = json.loads(row[0])
            if not cancelled and old['broker_status'] == 'CHANGED' and broker.broker_status == 'OK':
                counts['unchanged'] += 1
                continue
            corrected = {'broker_status': 'CANCELLED'} if cancelled else {**trade_fields(broker), 'broker_status': broker.broker_status}
            updated = {**old, **corrected, 'source': source}
            if updated != old:
                if old['plan_id']:
                    try:
                        updated['plan_snapshot'] = snapshot_plan(db, 'US', old['plan_id'], updated['symbol'], updated['at'], updated['side'], review_link=True)
                    except HTTPException:
                        updated['plan_id'] = updated['plan_snapshot'] = None
                write_fill(db, {**updated, 'revision': old['revision'] + 1})
                counts['updated'] += 1
            else:
                counts['unchanged'] += 1
    return {**counts, 'positions': positions, 'status': 'ok'}


def get_book(db, market, symbol=None, limit=None, offset=0):
    where, params = 'market=?', [market]
    if symbol:
        validate_symbol(symbol, market)
        where += ' AND symbol=?'
        params.append(symbol)
    page, page_args = (' LIMIT ? OFFSET ?', [limit + 1, offset]) if limit is not None else ('', [])
    plans = db.execute(f'SELECT id,MAX(effective) last FROM ledger_plans WHERE {where} GROUP BY id ORDER BY last DESC,id' + page,
                       [*params, *page_args]).fetchall()
    fills = db.execute(f'SELECT value FROM ledger_fills WHERE {where} AND alias_of IS NULL ORDER BY at DESC,id' + page,
                       [*params, *page_args]).fetchall()
    positions = [json.loads(r[0]) for r in db.execute(
        f'SELECT value FROM ledger_positions WHERE {where} AND json_extract(value,\'$.qty\')<>0 ORDER BY account,code', params)]
    accounts = [{**dict(r), 'complete': bool(r['complete'])} for r in db.execute(
        'SELECT account,as_of,complete,source FROM ledger_accounts WHERE market=? ORDER BY account', (market,))]
    more = limit is not None and (len(plans) > limit or len(fills) > limit)
    return {'plans': [plan_record(db, market, r[0]) for r in plans[:limit]],
            'fills': [fill_view(db, json.loads(r[0])) for r in fills[:limit]],
            'positions': positions, 'accounts': accounts, 'next_offset': offset + limit if more else None}


def export_book(db, market):
    schema(db)
    return get_book(db, market)


def save_plan(db, market, ident, body):
    validate_symbol(body.symbol, market)
    fields = body.model_dump(exclude={'request_id', 'revision'})
    if 'details' not in body.model_fields_set:
        fields.pop('details')
    if body.details:
        if body.details.strategy == 'limit_up' and market != 'CN':
            fail('打板计划仅适用于 A 股')
        # Preserve request fingerprints produced by earlier clients.
        for key in ('strategy', 'structure_mode','tracking_period'):
            if key not in body.details.model_fields_set:
                fields['details'].pop(key)
        if 'defense_reference' not in body.details.risk.model_fields_set:
            fields['details']['risk'].pop('defense_reference')
    if ident:
        update_input = {**fields, 'revision': body.revision, 'id': ident}
        if body.request_id and request_record(db, market, 'plan-edit', body.request_id, update_input):
            return plan_record(db, market, ident)
        prior = plan_record(db, market, ident)
        if prior['revision'] != body.revision:
            fail('交易计划已更新，请读取最新版本', 409)
        if prior['symbol'] != body.symbol or prior['side'] != body.side:
            fail('修改计划不能变更标的或交易方向')
        revision, created = body.revision + 1, prior['created_at']
        if body.request_id:
            remember(db, market, 'plan-edit', body.request_id, update_input, ident)
        if 'details' not in body.model_fields_set and 'details' in prior:
            fields['details'] = prior['details']
            if fields['details'] and body.trigger != prior['trigger']:
                fields['details'] = {**fields['details'], 'entry_note': body.trigger}
    else:
        prior_id = request_record(db, market, 'plan', body.request_id, fields)
        if prior_id:
            return plan_record(db, market, prior_id)
        ident, revision, created = uuid.uuid4().hex, 1, now()
        remember(db, market, 'plan', body.request_id, fields, ident)
    effective = created if revision == 1 else now()
    plan = {**fields, 'id': ident, 'market': market, 'revision': revision, 'created_at': created, 'updated_at': effective}
    db.execute('INSERT INTO ledger_plans VALUES(?,?,?,?,?,?)', (market, ident, body.symbol, revision, effective, dump(plan)))
    return plan_record(db, market, ident)


def delete_plan(db, market, ident):
    plan_record(db, market, ident)
    linked = db.execute("SELECT 1 FROM ledger_fills WHERE market=? AND alias_of IS NULL AND json_extract(value,'$.plan_id')=? LIMIT 1", (market, ident)).fetchone()
    if linked:
        fail('计划已关联成交，请先解除关联', 409)
    # Daily and weekly journal references are stored in the same SQLite database.
    refs_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_ledger_refs'").fetchone()
    if refs_table and db.execute("SELECT 1 FROM review_ledger_refs WHERE market=? AND kind='plan' AND record_id=? LIMIT 1", (market, ident)).fetchone():
        fail('计划已被复盘引用，请先移除引用', 409)
    db.execute('DELETE FROM ledger_plan_bars WHERE market=? AND id=?',(market,ident))
    db.execute('DELETE FROM ledger_plan_daily WHERE market=? AND id=?', (market, ident))
    db.execute('DELETE FROM ledger_plan_daily_status WHERE market=? AND id=?', (market, ident))
    db.execute('DELETE FROM ledger_plans WHERE market=? AND id=?', (market, ident))
    db.execute("DELETE FROM ledger_requests WHERE market=? AND kind IN ('plan','plan-edit') AND record_id=?", (market, ident))
    return {'deleted': True, 'id': ident}


def link_plan_fill(db, market, plan_id, fill_id, body, unlink=False):
    plan_record(db, market, plan_id)
    fill = fill_data(db, market, fill_id)
    if fill['revision'] != body.revision:
        fail('成交已更新，请读取最新版本', 409)
    if unlink:
        if fill.get('plan_id') != plan_id:
            fail('该成交没有关联此计划', 409)
        fill['plan_id'] = None
        fill['plan_snapshot'] = None
    else:
        if fill.get('broker_status') == 'CANCELLED':
            fail('成交已撤销')
        if fill.get('plan_id') not in (None, plan_id):
            fail('成交已关联其他计划，请先解除关联', 409)
        fill['plan_snapshot'] = snapshot_plan(db, market, plan_id, fill['symbol'], fill['at'], fill['side'], review_link=True)
        fill['plan_id'] = plan_id
    fill['revision'] += 1
    write_fill(db, fill)
    return fill_view(db, fill)


def save_review(db, market, ident, body):
    primary = fill_data(db, market, ident)
    if body.revision != primary['revision']:
        fail('成交或复盘已更新，请读取最新版本', 409)
    if 'plan_id' in body.model_fields_set:
        primary['plan_snapshot'] = snapshot_plan(db, market, body.plan_id, primary['symbol'], primary['at'], primary['side'], review_link=True)
        primary['plan_id'] = body.plan_id or None
    requested = body.group_ids if 'group_ids' in body.model_fields_set else (primary['review'] or {}).get('group_ids', [])
    peers = {item['id']: item for item in (fill_data(db, market, gid) for gid in requested)}
    peers.pop(primary['id'], None)
    previous_ids = {resolve_fill_id(db, market, gid) for gid in (primary['review'] or {}).get('group_ids', [])}
    previous_ids.discard(primary['id'])
    group = {primary['id']: primary, **peers}
    for peer_id, peer in peers.items():
        if peer['account'] != primary['account'] or peer['symbol'] != primary['symbol']:
            fail('合并复盘只支持同账户、同标的的成交')
        expected = body.group_revisions.get(peer_id)
        if expected is not None and peer['revision'] != expected:
            fail('选中的成交已更新，请刷新后核对', 409)
        if peer['review'] and peer_id not in previous_ids:
            if peer['review']['group_ids'] or expected is None:
                fail('选中的成交已有复盘，请先核对其版本及分组', 409)
    for removed in previous_ids - peers.keys():
        peer = fill_data(db, market, removed)
        if removed in body.group_revisions and peer['revision'] != body.group_revisions[removed]:
            fail('移出分组的成交已更新，请刷新后核对', 409)
        if peer['review']:
            peer['review'] = {**peer['review'], 'group_ids': []}
            peer['revision'] += 1
            write_fill(db, peer)
    text = body.model_dump(include={'execution', 'quality', 'note'})
    for peer_id, peer in group.items():
        peer['review'] = {**text, 'group_ids': [gid for gid in group if gid != peer_id]}
        peer['revision'] += 1
        write_fill(db, peer)
    return fill_view(db, primary)


def reconcile(db, market, body):
    if market != 'US':
        fail('此操作仅用于核对美股券商成交')
    manual = fill_data(db, market, body.manual_id)
    broker = fill_data(db, market, body.broker_fill_id)
    if manual['id'] == broker['id']:
        if body.manual_id == body.broker_fill_id:
            fail('请分别选择手工记录与券商记录')
        return fill_view(db, manual)
    if not candidate_pair(manual, broker):
        fail('成交记录未匹配，请核对账户、合约、方向、数量、价格及时间', 409)
    peer_groups = []
    for row in (manual, broker):
        review = row['review'] or {}
        ids = {resolve_fill_id(db, market, gid) for gid in review.get('group_ids', [])}
        peer_groups.append(ids - {manual['id'], broker['id']})
    if manual['review'] and broker['review']:
        if any(manual['review'][k] != broker['review'][k] for k in ('execution', 'quality', 'note')):
            fail('两条记录已有不同复盘，请核对并处理后合并', 409)
        if all(peer_groups) and peer_groups[0] != peer_groups[1]:
            fail('两条记录位于不同的复盘组，请先核对分组', 409)
    if manual['plan_id'] and broker['plan_id'] and manual['plan_id'] != broker['plan_id']:
        fail('两条记录关联的计划不同，请核对', 409)
    plan_id = manual['plan_id'] or broker['plan_id']
    merged = {**broker, 'id': manual['id'], 'plan_id': plan_id,
              'plan_snapshot': snapshot_plan(db, market, plan_id, broker['symbol'], broker['at'], broker['side'], review_link=True),
              'review': manual['review'] or broker['review'], 'revision': max(manual['revision'], broker['revision'])+1}
    # Keep the losing ID addressable for all old plan/diary references.
    db.execute('UPDATE ledger_fills SET alias_of=?,broker_id=NULL WHERE id=?', (manual['id'], broker['id']))
    if merged['review']:
        peer_ids = peer_groups[0] | peer_groups[1]
        merged['review'] = {**merged['review'], 'group_ids': sorted(peer_ids)}
        for pid in peer_ids:
            peer = fill_data(db, market, pid)
            peer['review']['group_ids'] = sorted((peer_ids | {merged['id']}) - {pid})
            peer['revision'] += 1
            write_fill(db, peer)
    write_fill(db, merged)
    return fill_view(db, merged)


def install(app, agent, connect_db):
    def route(path, method, summary):
        def register(handler):
            agent.add_api_route('/ledger/' + path, handler, methods=[method], summary=summary)
            app.add_api_route('/api/review/ledger/' + path, handler, methods=[method], summary=summary)
            return handler
        return register

    from .plan_autofill import install as install_autofill
    install_autofill(route, connect_db)

    @route('book', 'GET', '按标的查询交易计划、成交及持仓')
    def book(market: Market, symbol: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
        with transaction(connect_db) as db:
            return get_book(db, market, symbol, limit, offset)

    @route('plans', 'POST', '创建事前交易计划')
    def create_plan(market: Market, body: NewPlan):
        with transaction(connect_db, True) as db:
            return save_plan(db, market, None, body)

    @route('plans/{ident}', 'PUT', '保存交易计划的新版本')
    def edit_plan(market: Market, ident: str, body: UpdatePlan):
        with transaction(connect_db, True) as db:
            return save_plan(db, market, ident, body)

    @route('plans/{ident}', 'GET', '读取计划历次版本与关联成交')
    def get_plan(market: Market, ident: str):
        with transaction(connect_db) as db:
            record = plan_record(db, market, ident)
            links = db.execute('''SELECT id FROM ledger_fills WHERE market=? AND symbol=? AND alias_of IS NULL
                AND json_extract(value,'$.plan_id')=? ORDER BY at,id''', (market, record['symbol'], ident))
            latest = db.execute('SELECT value FROM ledger_plan_daily WHERE market=? AND id=? ORDER BY day DESC LIMIT 1',
                                (market, ident)).fetchone()
            candle = db.execute('SELECT value FROM ledger_plan_bars WHERE market=? AND id=? ORDER BY end DESC LIMIT 1',
                                (market,ident)).fetchone()
            return {**record,'latest_bar':json.loads(candle[0]) if candle else None, 'fill_ids': [row[0] for row in links], 'latest_daily': json.loads(latest[0]) if latest else None}

    @route('plans/{ident}/bars', 'GET', '按所选周期读取已收盘的点位记录和失败状态')
    def get_bar_history(market: Market, ident: str, before: int | None = Query(None, gt=0), limit: int = Query(30,ge=1,le=365)):
        with transaction(connect_db) as db:
            plan_record(db,market,ident)
            rows = db.execute('SELECT value FROM ledger_plan_bars WHERE market=? AND id=? AND end<? ORDER BY end DESC LIMIT ?',
                              (market,ident,before or 2**62,limit+1)).fetchall()
            items = [json.loads(r[0]) for r in rows[:limit]]
            return {'items':items,'next_before':items[-1]['close_time'] if len(rows)>limit else None}

    @route('plans/{ident}/daily', 'GET', '查询收盘跟随点位及止损止盈触及历史')
    def get_daily(market: Market, ident: str, before: date | None = None, limit: int = Query(30, ge=1, le=365)):
        with transaction(connect_db) as db:
            plan_record(db, market, ident)
            rows = db.execute('''SELECT value FROM ledger_plan_daily WHERE market=? AND id=? AND day<?
                ORDER BY day DESC LIMIT ?''', (market, ident, str(before or date.max), limit+1)).fetchall()
            items = [json.loads(r[0]) for r in rows[:limit]]
            status = db.execute('SELECT expected_day,checked_at,error FROM ledger_plan_daily_status WHERE market=? AND id=?',
                                (market, ident)).fetchone()
            return {'items':items, 'next_before':items[-1]['day'] if len(rows)>limit else None,
                    'status':dict(status) if status else None}

    @route('plans/{ident}', 'DELETE', '删除未被成交或复盘引用的交易计划')
    def remove_plan(market: Market, ident: str):
        with transaction(connect_db, True) as db:
            return delete_plan(db, market, ident)

    @route('plans/{ident}/fills/{fill_id}', 'PUT', '关联已有成交与事前交易计划')
    def attach_fill(market: Market, ident: str, fill_id: str, body: PlanFillLink):
        with transaction(connect_db, True) as db:
            return link_plan_fill(db, market, ident, fill_id, body)

    @route('plans/{ident}/fills/{fill_id}', 'DELETE', '解除成交与交易计划关联')
    def detach_fill(market: Market, ident: str, fill_id: str, body: PlanFillLink):
        with transaction(connect_db, True) as db:
            return link_plan_fill(db, market, ident, fill_id, body, True)

    @route('fills', 'POST', '手动添加或导入截图中的成交')
    def create_fill(market: Market, body: Fill):
        with transaction(connect_db, True) as db:
            return fill_view(db, save_manual(db, market, body))

    @route('fills/{ident}', 'GET', '读取成交、事前计划版本及复盘')
    def get_fill(market: Market, ident: str):
        with transaction(connect_db) as db:
            return fill_view(db, fill_data(db, market, ident))

    @route('positions', 'POST', '同步完整或局部账户持仓截图')
    def positions(market: Market, body: Snapshot):
        with transaction(connect_db, True) as db:
            return save_snapshot(db, market, body, body.source)

    @route('fills/{ident}/review', 'PUT', '保存逐笔或分组成交复盘')
    def review_fill(market: Market, ident: str, body: TradeReview):
        with transaction(connect_db, True) as db:
            return save_review(db, market, ident, body)

    @route('reconcile', 'POST', '核对手工补录与券商成交并保留原引用')
    def reconcile_fills(market: Market, body: Reconcile):
        with transaction(connect_db, True) as db:
            return reconcile(db, market, body)
