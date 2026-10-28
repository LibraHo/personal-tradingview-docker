"""On-demand, persisted A-share name directory from the existing OpenD."""
import re
import time

A_SHARE = re.compile(r'^(?:SH\.6\d{5}|SZ\.[03]\d{5})$')


def search_cn_symbols(bridge, connect_db, query, limit=12):
    from moomoo import RET_OK
    query = ''.join(query.split())
    if not query:
        return {'results': [], 'stale': False, 'source': 'nas_cache'}
    stale = False
    with bridge.lock:
        attempts = getattr(bridge, '_symbol_directory_attempts', {})
        bridge._symbol_directory_attempts = attempts
        now = time.time()
        for market in ('SH', 'SZ'):
            key = 'symbol_directory.' + market
            with connect_db() as db:
                row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            try:
                updated = float(row[0]) if row else 0
            except (TypeError, ValueError):
                updated = 0
            if now - updated < 7 * 86400:
                continue
            if now - attempts.get(market, 0) < 300:
                stale = True
                continue
            attempts[market] = now
            try:
                bridge.rate_limit()
                ret, frame = bridge.ensure().get_stock_basicinfo(market=market)
                if ret != RET_OK:
                    raise RuntimeError('静态目录暂不可用')
                rows = [(str(r['code']), str(r['name']).strip(), now) for r in frame.to_dict('records')
                        if A_SHARE.fullmatch(str(r.get('code', ''))) and str(r.get('name') or '').strip()]
                if not rows:
                    raise RuntimeError('静态目录未返回 A 股名称')
                with connect_db() as db:
                    db.executemany('INSERT OR REPLACE INTO symbol_names VALUES(?,?,?)', rows)
                    db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(now)))
                bridge.last_activity = time.monotonic()
            except Exception:
                stale = True
        escaped = query.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        pattern = '%' + escaped + '%'
        with connect_db() as db:
            rows = db.execute("SELECT symbol,name FROM symbol_names WHERE (symbol GLOB 'SH.6[0-9][0-9][0-9][0-9][0-9]' OR symbol GLOB 'SZ.[03][0-9][0-9][0-9][0-9][0-9]') "
                              "AND (symbol LIKE ? ESCAPE '!' OR replace(name,' ','') LIKE ? ESCAPE '!') "
                              "ORDER BY CASE WHEN replace(name,' ','')=? OR symbol=? OR substr(symbol,4)=? THEN 0 ELSE 1 END,symbol LIMIT ?",
                              (pattern, pattern, query, query.upper(), query, min(20, max(1, limit)))).fetchall()
    return {'results': [dict(row) for row in rows], 'stale': stale, 'source': 'nas_cache',
            'message': '股票目录暂未完整更新，正在搜索 NAS 已有名称；稍后可重试。' if stale else ''}
