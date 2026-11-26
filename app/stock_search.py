"""Local symbol search with periodically refreshed OpenD directories."""
import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

LOG = logging.getLogger(__name__)
MAX_AGE = 86400
CHECK_INTERVAL = 300
A_SHARE = re.compile(r'(?:SH\.6\d{5}|SZ\.[03]\d{5})')
US_SYMBOL = re.compile(r'US\.[A-Z0-9.]{1,12}')
DIRECTORIES = {
    'symbol_directory.' + exchange + suffix: (exchange, stock_type, kind)
    for exchange in ('SH', 'SZ', 'US')
    for stock_type, kind, suffix in (('STOCK', 'stock', ''), ('ETF', 'etf', '.ETF'), ('IDX', 'index', '.IDX'))
    if exchange != 'US' or kind != 'index'
}


def fresh_directories(db):
    return {row[0] for row in db.execute(
        "SELECT key FROM settings WHERE key GLOB 'symbol_directory.*' AND CAST(value AS REAL)>?",
        (time.time() - MAX_AGE,))}


def refresh_directory(bridge, connect_db, key):
    from moomoo import RET_OK
    exchange, stock_type, kind = DIRECTORIES[key]
    with bridge.lock:
        bridge.rate_limit()
        status, frame = bridge.ensure().get_stock_basicinfo(market=exchange, stock_type=stock_type)
        bridge.last_activity = time.monotonic()
    if status != RET_OK:
        raise RuntimeError('证券目录请求失败')
    now = time.time()
    rows = []
    pattern = US_SYMBOL if exchange == 'US' else (
        A_SHARE if kind == 'stock' else re.compile(r'(?:SH|SZ)\.\d{6}'))
    for entry in frame.to_dict('records'):
        code = str(entry.get('code', ''))
        name = str(entry.get('name') or '').strip()
        if (name and code.startswith(exchange + '.') and pattern.fullmatch(code)
                and not entry.get('delisting', False)):
            rows.append((code, name, now))
    if not rows:
        raise ValueError('证券目录为空')
    with connect_db() as db:
        # Replace this membership atomically, retaining names used by saved watchlists.
        db.execute("UPDATE symbol_kinds SET kind='inactive' WHERE symbol GLOB ? AND kind=?",
                   (exchange + '.*', kind))
        db.executemany('INSERT OR REPLACE INTO symbol_names VALUES(?,?,?)', rows)
        db.executemany('INSERT OR REPLACE INTO symbol_kinds VALUES(?,?)',
                       [(code, kind) for code, _, _ in rows])
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, str(now)))


async def maintain_directory(bridge, connect_db, stop, connection_factory=None):
    def pending():
        with connect_db() as db:
            fresh = fresh_directories(db)
        return [key for key in DIRECTORIES if key not in fresh]

    def refresh_pending():
        keys = pending()
        if not keys:
            return
        session = connection_factory() if connection_factory else bridge
        bridge.refreshing_directories = frozenset(keys)
        try:
            for key in keys:
                if stop.is_set():
                    break
                try:
                    refresh_directory(session, connect_db, key)
                except Exception as exc:
                    LOG.warning('Could not update %s: %s', key, exc)
                bridge.refreshing_directories = bridge.refreshing_directories - {key}
        finally:
            bridge.refreshing_directories = frozenset()
            if connection_factory and session.ctx:
                session.ctx.close()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='securities-directory') as worker:
        while not stop.is_set():
            try:
                await asyncio.get_running_loop().run_in_executor(worker, refresh_pending)
            except Exception:
                LOG.exception('Could not check securities directories')
            try:
                await asyncio.wait_for(stop.wait(), timeout=CHECK_INTERVAL)
            except asyncio.TimeoutError:
                pass


def search_directory(bridge, connect_db, query, limit=12, market='CN'):
    query = ''.join(query.split()).lower()
    # Some ETF names insert words like 材料 between the theme and the ETF suffix.
    topic = query[:-3] if query.endswith('etf') else None
    fuzzy_topic = None
    if topic and re.fullmatch(r'[\u3400-\u9fff]{2,}', topic):
        fuzzy_topic = '%' + '%'.join(topic) + '%'
    if market == 'US':
        scope = "n.symbol GLOB 'US.*' AND (k.kind IS NULL OR k.kind IN ('stock','etf'))"
    else:
        scope = """(n.symbol GLOB 'SH.*' OR n.symbol GLOB 'SZ.*') AND (
            k.kind IN ('stock','index','etf') OR (k.kind IS NULL AND (
            n.symbol GLOB 'SH.6[0-9][0-9][0-9][0-9][0-9]' OR
            n.symbol GLOB 'SZ.[03][0-9][0-9][0-9][0-9][0-9]')))"""
    with connect_db() as db:
        fresh = fresh_directories(db)
        pending = {key for key, (exchange, _, _) in DIRECTORIES.items()
                   if (exchange == 'US') == (market == 'US') and key not in fresh}
        # Official exchange short names for feeds that only supply a trading abbreviation.
        # SSE fund 560780 and the SZSE filing for fund 159516 on 2026-07-29.
        rows = db.execute(f"""
            WITH aliases(symbol,name) AS (VALUES
                ('SH.560780','半导体设备ETF广发'), ('SZ.159516','半导体设备ETF国泰')
            ), names AS (
                SELECT n.symbol,n.name,coalesce(k.kind,'stock') kind,0 priority
                FROM symbol_names n LEFT JOIN symbol_kinds k USING(symbol) WHERE {scope}
                UNION ALL SELECT a.symbol,a.name,'etf',1 FROM aliases a
                LEFT JOIN symbol_kinds k USING(symbol)
                WHERE :market='CN' AND coalesce(k.kind,'etf')='etf'
            ), normalized AS (
                SELECT *,lower(replace(name,' ','')) short_name,lower(symbol) code FROM names
            )
                SELECT symbol,name,kind FROM normalized
                WHERE instr(code,:q) OR instr(short_name,:q) OR
                      (kind='etf' AND (instr(short_name,:topic) OR short_name LIKE :fuzzy))
                ORDER BY CASE
                    WHEN code=:q OR substr(code,4)=:q THEN 0
                    WHEN short_name=:q THEN 1
                    WHEN instr(substr(code,4),:q)=1 OR instr(short_name,:q)=1 THEN 2
                    WHEN instr(short_name,:q) OR instr(code,:q) THEN 3
                    WHEN kind='etf' AND instr(short_name,:topic) THEN 4
                    ELSE 5
                END,symbol,priority LIMIT :fetch_limit
            """, dict(q=query, topic=topic, fuzzy=fuzzy_topic, market=market,
                      fetch_limit=limit + 2 if query else 0)).fetchall()
    # Only the two exchange aliases can duplicate a symbol in the ranked results.
    matches = {}
    for row in rows:
        matches.setdefault(row['symbol'], dict(row))
    refreshing = bool(pending & bridge.refreshing_directories)
    message = ('正在更新证券目录，已显示本地匹配结果。' if refreshing else
               '证券目录暂未完整更新，已搜索本地名称。' if pending else '')
    return {'results': list(matches.values())[:limit], 'stale': bool(pending),
            'refreshing': refreshing, 'source': 'nas_cache', 'message': message}
