"""Durable, market-separated trading journals and discipline reviews."""
import calendar
import json
import re
import time
import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from .scan_api import bearer, token_scopes
from . import ledger, ledger_broker

Market = Literal['CN', 'US']
DEFAULT_RULES = ['下单前写好交易计划', '控制单笔风险与总仓位', '按计划止损，不随意扩大止损',
                 '不追涨杀跌，不情绪化下单', '只做符合策略的机会', '不因亏损而加倍下注']
SYMBOL_PATTERNS = {'CN': r'(?:SH|SZ)\.[0-9]{6}', 'US': r'US\.[A-Z0-9.]{1,12}'}
MENTION_PATTERNS = {market: re.compile(r'\[\[(' + pattern + r')(?:\|([^\[\]|\r\n]{1,80}))?\]\]', re.I | re.ASCII)
                    for market, pattern in SYMBOL_PATTERNS.items()}

LEDGER_MENTION = re.compile(r'\[\[(plan|fill):([a-f0-9]{32})(?:\|([^\[\]|\r\n]{1,160}))?\]\]')


def update_references(db, market, journal_kind, day, texts):
    references = {}
    for text in texts:
        for match in LEDGER_MENTION.finditer(text):
            references[(match[1], match[2])] = match[3] or ''
    db.execute('DELETE FROM review_ledger_refs WHERE market=? AND journal_kind=? AND day=?',
               (market, journal_kind, day))
    for kind, ident in references:
        if not ledger.reference_exists(db, market, kind, ident):
            raise HTTPException(422, '引用的计划或成交不在当前市场，请重新选择')
        db.execute('INSERT INTO review_ledger_refs VALUES(?,?,?,?,?)', (market, journal_kind, day, kind, ident))
    return [{'kind': kind, 'id': ident, 'label': label} for (kind, ident), label in references.items()]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RuleCreate(Input):
    title: str = Field(min_length=1, max_length=120)


class RuleUpdate(RuleCreate):
    active: bool
    revision: int = Field(ge=1)


class RelatedSymbol(Input):
    symbol: str = Field(min_length=1, max_length=24)
    name: str = Field(default='', max_length=80)
    note: str = Field(default='', max_length=2000)


class DailyInput(Input):
    revision: int = Field(default=0, ge=0)
    traded: bool
    violations: list[str] = Field(default_factory=list, max_length=100)
    symbols: list[RelatedSymbol] = Field(default_factory=list, max_length=50)
    context: str = Field(default='', max_length=5000)
    reason: str = Field(default='', max_length=5000)
    lesson: str = Field(default='', max_length=5000)
    plan: str = Field(default='', max_length=5000)


class WeeklyInput(Input):
    revision: int = Field(default=0, ge=0)
    focus_rule_id: str = Field(default='', max_length=64)
    action: str = Field(default='', max_length=5000)
    summary: str = Field(default='', max_length=5000)


class DailyPatch(DailyInput):
    revision: int = Field(ge=0)
    traded: bool = True


class DailyReplace(DailyInput):
    revision: int = Field(ge=0)


class WeeklyReplace(WeeklyInput):
    revision: int = Field(ge=0)


def parse_day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        if not 2000 <= parsed.year <= 2099:
            raise ValueError()
        return parsed
    except ValueError:
        raise HTTPException(422, '日期须为 2000 至 2099 年间有效的 YYYY-MM-DD')


def week_start(day):
    return day - timedelta(days=day.weekday())


def decode(row):
    return json.loads(row['value']) if row else None


def day_with_mentions(entry):
    if entry is None:
        return None
    names = {}
    pattern = MENTION_PATTERNS[entry['market']]
    for field in ('context', 'reason', 'lesson', 'plan'):
        for match in pattern.finditer(entry[field]):
            code, name = match[1].upper(), (match[2] or '').strip()
            if not names.get(code):
                names[code] = name
    return {**entry, 'mentioned_symbols': [{'symbol': code, 'name': name} for code, name in names.items()]}


def rule_dict(row):
    return {**dict(row), 'active': bool(row['active'])}


def init_schema(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='review_ledger_target'").fetchone():
        # The default rules for both markets are seeded in one transaction.
        if db.execute("SELECT 1 FROM review_rules WHERE id='us-default-0'").fetchone():
            return
    db.executescript('''
        CREATE TABLE IF NOT EXISTS review_rules(
            id TEXT PRIMARY KEY, market TEXT NOT NULL, title TEXT NOT NULL,
            active INTEGER NOT NULL, revision INTEGER NOT NULL, created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS review_rules_market ON review_rules(market, created);
        CREATE TABLE IF NOT EXISTS review_days(
            market TEXT NOT NULL, day TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(market, day));
        CREATE TABLE IF NOT EXISTS review_weeks(
            market TEXT NOT NULL, week TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(market, week));
        CREATE TABLE IF NOT EXISTS review_ledger_refs(
            market TEXT NOT NULL, journal_kind TEXT NOT NULL, day TEXT NOT NULL,
            kind TEXT NOT NULL, record_id TEXT NOT NULL,
            PRIMARY KEY(market,journal_kind,day,kind,record_id));
        CREATE INDEX IF NOT EXISTS review_ledger_target ON review_ledger_refs(market,kind,record_id);
    ''')
    for market in ('CN', 'US'):
        for i, title in enumerate(DEFAULT_RULES):
            db.execute('INSERT OR IGNORE INTO review_rules VALUES(?,?,?,?,?,?)',
                       (f'{market.lower()}-default-{i}', market, title, 1, 1, i))
    db.commit()


def revision_check(old, revision):
    if (old['revision'] if old else 0) != revision:
        raise HTTPException(409, '这条记录已在其他页面更新。当前草稿已保留，请重新读取后核对。')


def install(app: FastAPI, connect_db):
    def authorize(request: Request, credential: HTTPAuthorizationCredentials | None = Depends(bearer)):
        scope = 'review:read' if request.method == 'GET' else 'review:write'
        if scope not in token_scopes(connect_db, credential):
            raise HTTPException(403, 'Token 缺少 ' + scope + ' 权限')

    agent = APIRouter(prefix='/api/v1/review', tags=['每日复盘 API'], dependencies=[Depends(authorize)])
    ledger.install(app, agent, connect_db)
    ledger_broker.install(app, agent, connect_db)

    @agent.get('/ledger/backlinks', summary='查找引用计划或成交的每日及每周复盘')
    @app.get('/api/review/ledger/backlinks')
    def backlinks(market: Market, kind: Literal['plan', 'fill'], id: str = Query(pattern='^[a-f0-9]{32}$')):
        with connect_db() as db:
            init_schema(db)
            ledger.schema(db)
            if not ledger.reference_exists(db, market, kind, id):
                raise HTTPException(404, '未找到交易档案')
            ids = ledger.reference_ids(db, market, kind, id)
            placeholders = ','.join('?' for _ in ids)
            rows = db.execute(f'''SELECT DISTINCT journal_kind AS kind, day FROM review_ledger_refs
                WHERE market=? AND kind=? AND record_id IN ({placeholders}) ORDER BY day DESC,kind''',
                (market, kind, *ids))
            return {'items': [dict(row) for row in rows]}
    # Schema is initialized on access so existing databases upgrade without an external migration.
    def prepare(db, write=False):
        init_schema(db)
        if write:
            ledger.schema(db)
            db.execute('BEGIN IMMEDIATE')

    def rules(db, market):
        return [rule_dict(r) for r in db.execute(
            'SELECT * FROM review_rules WHERE market=? ORDER BY created,id', (market,))]

    def values(db, table, market, start, end):
        key = 'day' if table == 'review_days' else 'week'
        projection = day_with_mentions if table == 'review_days' else lambda entry: entry
        return [projection(decode(r)) for r in db.execute(
            f'SELECT value FROM {table} WHERE market=? AND {key} BETWEEN ? AND ? ORDER BY {key}',
            (market, start, end))]

    @agent.get('/dashboard', summary='读取每日复盘、每周统计和历史索引')
    @app.get('/api/review/dashboard')
    def dashboard(market: Market, day: str):
        selected = parse_day(day)
        start = week_start(selected)
        end = start + timedelta(days=6)
        with connect_db() as db:
            prepare(db)
            all_rules = rules(db, market)
            entry = day_with_mentions(decode(db.execute('SELECT value FROM review_days WHERE market=? AND day=?', (market, day)).fetchone()))
            weekly = decode(db.execute('SELECT value FROM review_weeks WHERE market=? AND week=?', (market, start.isoformat())).fetchone())
            previous_weekly = decode(db.execute('SELECT value FROM review_weeks WHERE market=? AND week=?', (market, (start-timedelta(days=7)).isoformat())).fetchone())
            current = values(db, 'review_days', market, start.isoformat(), end.isoformat())
            previous = values(db, 'review_days', market, (start-timedelta(days=7)).isoformat(), (start-timedelta(days=1)).isoformat())
            history = values(db, 'review_days', market, selected.replace(day=1).isoformat(), selected.replace(day=calendar.monthrange(selected.year, selected.month)[1]).isoformat())
        counts, previous_counts, labels = {}, {}, {r['id']: r['title'] for r in all_rules}
        for records, result in ((previous, previous_counts), (current, counts)):
            for record in records:
                for violation in record['violations']:
                    rid = violation['id']
                    result[rid] = result.get(rid, 0) + 1
                    labels.setdefault(rid, violation['title'])
        ranking = [{'id': rid, 'title': labels[rid], 'count': counts.get(rid, 0),
                    'previous_count': previous_counts.get(rid, 0)} for rid in counts.keys() | previous_counts.keys()]
        ranking.sort(key=lambda r: (-r['count'], -r['previous_count'], r['id']))
        return {'market': market, 'day': day, 'rules': all_rules, 'entry': entry,
                'week_start': start.isoformat(), 'week_end': end.isoformat(), 'previous_weekly': previous_weekly,
                'weekly': weekly or {'market': market, 'week': start.isoformat(), 'revision': 0,
                    'focus_rule_id': '', 'focus_title': '', 'action': '', 'summary': ''},
                'stats': {'reviewed_days': len(current), 'trading_days': sum(r['traded'] for r in current),
                    'clean_days': sum(not r['violations'] for r in current),
                    'violation_days': sum(bool(r['violations']) for r in current),
                    'previous_reviewed_days': len(previous), 'ranking': ranking},
                'history': [{'day': r['day'], 'traded': r['traded'], 'violation_count': len(r['violations']),
                             'symbol_count': len({s['symbol'] for s in r['symbols'] + r['mentioned_symbols']}),
                             'lesson': r['lesson']} for r in reversed(history)]}

    @agent.get('/rules', summary='列出交易纪律及其版本、启停状态')
    def list_rules(market: Market, active: bool | None = None):
        with connect_db() as db:
            prepare(db)
            items = rules(db, market)
        return {'items': [r for r in items if active is None or r['active'] == active]}

    @agent.post('/rules', summary='新增交易纪律')
    @app.post('/api/review/rules')
    def add_rule(market: Market, body: RuleCreate):
        title = body.title.strip()
        if not title:
            raise HTTPException(422, '请输入交易纪律')
        with connect_db() as db:
            prepare(db, True)
            existing = rules(db, market)
            if any(r['title'] == title for r in existing):
                raise HTTPException(409, '已有同名纪律，可在管理中重新启用')
            if len(existing) >= 100:
                raise HTTPException(422, '每个市场最多保存 100 条纪律')
            result = {'id': uuid.uuid4().hex, 'market': market, 'title': title,
                      'active': True, 'revision': 1, 'created': time.time()}
            db.execute('INSERT INTO review_rules VALUES(:id,:market,:title,:active,:revision,:created)', result)
        return result

    @agent.put('/rules/{rule_id}', summary='修改纪律名称、停用或重新启用')
    @app.put('/api/review/rules/{rule_id}')
    def update_rule(rule_id: str, market: Market, body: RuleUpdate):
        title = body.title.strip()
        if not title:
            raise HTTPException(422, '请输入交易纪律')
        with connect_db() as db:
            prepare(db, True)
            old = db.execute('SELECT * FROM review_rules WHERE id=? AND market=?', (rule_id, market)).fetchone()
            if not old:
                raise HTTPException(404, '纪律不存在')
            revision_check(old, body.revision)
            if any(r['title'] == title and r['id'] != rule_id for r in rules(db, market)):
                raise HTTPException(409, '已有同名纪律')
            db.execute('UPDATE review_rules SET title=?,active=?,revision=revision+1 WHERE id=?', (title, body.active, rule_id))
            return rule_dict(db.execute('SELECT * FROM review_rules WHERE id=?', (rule_id,)).fetchone())

    def write_day(day: str, market: Market, body: DailyInput, partial=False):
        parse_day(day)
        with connect_db() as db:
            prepare(db, True)
            old = decode(db.execute('SELECT value FROM review_days WHERE market=? AND day=?', (market, day)).fetchone())
            revision_check(old, body.revision)
            if partial:
                previous = {key: old[key] for key in DailyInput.model_fields if key != 'violations'} if old else {'traded': True}
                if old:
                    previous['violations'] = [v['id'] for v in old['violations']]
                body = DailyInput.model_validate({**previous, **body.model_dump(exclude_unset=True)})
            catalog = {r['id']: r for r in rules(db, market)}
            snapshots = {v['id']: v for v in old['violations']} if old else {}
            violations = []
            for rid in dict.fromkeys(body.violations):
                rule = catalog.get(rid)
                if not rule or (not rule['active'] and rid not in snapshots):
                    raise HTTPException(422, '勾选的纪律已停用或不属于当前市场，请核对')
                violations.append(snapshots.get(rid) or {'id': rid, 'title': rule['title']})
            symbols, seen = [], set()
            for item in body.symbols:
                code = item.symbol.strip().upper()
                if not re.fullmatch(SYMBOL_PATTERNS[market], code):
                    raise HTTPException(422, '标的代码不属于当前市场或格式不正确')
                if code in seen:
                    raise HTTPException(422, '关联标的不能重复')
                seen.add(code)
                symbols.append({**item.model_dump(), 'symbol': code, 'name': item.name.strip()})
            result = {**body.model_dump(), 'market': market, 'day': day, 'violations': violations,
                      'symbols': symbols, 'revision': body.revision+1, 'updated': time.time()}
            result['references'] = update_references(db, market, 'day', day,
                (result[key] for key in ('context', 'reason', 'lesson', 'plan')))
            db.execute('INSERT INTO review_days VALUES(?,?,?) ON CONFLICT(market,day) DO UPDATE SET value=excluded.value',
                       (market, day, json.dumps(result, ensure_ascii=False)))
        return day_with_mentions(result)

    @app.put('/api/review/days/{day}')
    def save_day(day: str, market: Market, body: DailyInput):
        return write_day(day, market, body)

    @agent.put('/days/{day}', summary='用完整内容创建或替换当日复盘')
    def replace_day(day: str, market: Market, body: DailyReplace):
        return write_day(day, market, body)

    @agent.patch('/days/{day}', summary='创建复盘或只更新提供的字段')
    def patch_day(day: str, market: Market, body: DailyPatch):
        if not body.model_fields_set - {'revision'}:
            raise HTTPException(422, '请提供至少一个复盘字段')
        return write_day(day, market, body, partial=True)

    @agent.get('/days/{day}', summary='读取单日复盘及其版本')
    def get_day(day: str, market: Market):
        parse_day(day)
        with connect_db() as db:
            prepare(db)
            entry = decode(db.execute('SELECT value FROM review_days WHERE market=? AND day=?', (market, day)).fetchone())
        if entry is None:
            raise HTTPException(404, '此日期尚未复盘')
        return day_with_mentions(entry)

    @agent.get('/days', summary='按日期倒序分页读取复盘')
    def list_days(market: Market, start: str | None = None, end: str | None = None,
                  before: str | None = None, limit: int = Query(20, ge=1, le=100)):
        for value in (start, end, before):
            if value is not None:
                parse_day(value)
        if start and end and start > end:
            raise HTTPException(422, '起始日期不能晚于结束日期')
        with connect_db() as db:
            prepare(db)
            rows = db.execute('''SELECT value FROM review_days WHERE market=? AND day BETWEEN ? AND ?
                AND day < ? ORDER BY day DESC LIMIT ?''',
                (market, start or '2000-01-01', end or '2099-12-31', before or '2100-01-01', limit + 1)).fetchall()
        items = [day_with_mentions(decode(row)) for row in rows[:limit]]
        return {'items': items, 'next_before': items[-1]['day'] if len(rows) > limit else None}

    @app.put('/api/review/weeks/{day}')
    def save_week(day: str, market: Market, body: WeeklyInput):
        start = week_start(parse_day(day)).isoformat()
        with connect_db() as db:
            prepare(db, True)
            old = decode(db.execute('SELECT value FROM review_weeks WHERE market=? AND week=?', (market, start)).fetchone())
            revision_check(old, body.revision)
            title = ''
            if body.focus_rule_id:
                rule = db.execute('SELECT * FROM review_rules WHERE market=? AND id=?', (market, body.focus_rule_id)).fetchone()
                if not rule:
                    raise HTTPException(422, '重点纪律不属于当前市场')
                title = old['focus_title'] if old and old['focus_rule_id'] == body.focus_rule_id else rule['title']
            result = {**body.model_dump(), 'market': market, 'week': start, 'focus_title': title,
                      'revision': body.revision+1, 'updated': time.time()}
            result['references'] = update_references(db, market, 'week', start, (body.action, body.summary))
            db.execute('INSERT INTO review_weeks VALUES(?,?,?) ON CONFLICT(market,week) DO UPDATE SET value=excluded.value',
                       (market, start, json.dumps(result, ensure_ascii=False)))
        return result

    @agent.get('/weeks/{day}', summary='读取该日期所属周的总结及违规统计')
    def get_week(day: str, market: Market):
        result = dashboard(market, day)
        return {key: result[key] for key in ('market', 'week_start', 'week_end', 'weekly', 'previous_weekly', 'stats')}

    @agent.put('/weeks/{day}', summary='保存重点纪律、行动和周总结')
    def replace_week(day: str, market: Market, body: WeeklyReplace):
        return save_week(day, market, body)

    @agent.get('/export', summary='导出当前市场全部已保存的复盘数据')
    @app.get('/api/review/export')
    def export(market: Market):
        with connect_db() as db:
            prepare(db)
            ledger.schema(db)
            db.execute('BEGIN')
            return {'version': 2, 'market': market, 'exported_at': time.time(), 'rules': rules(db, market),
                    'ledger': ledger.export_book(db, market),
                    'days': values(db, 'review_days', market, '0001-01-01', '9999-12-31'),
                    'weeks': values(db, 'review_weeks', market, '0001-01-01', '9999-12-31')}

    app.include_router(agent)
