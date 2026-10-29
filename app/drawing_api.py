"""Scoped chart-object API. No broker or trading dependencies."""
import copy
import hmac
import json
import math
import os
import re
import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

FIELDS = ('drawings', 'trends', 'fibos', 'drawingsHidden')
KINDS = {'horizontal': 'drawings', 'trend': 'trends', 'fib': 'fibos'}
PERIODS = {'1m', '5m', '15m', '30m', '60m', '1d', '1w', '1mo'}
SYMBOL = re.compile(r'^(US\.[A-Z0-9.]{1,12}|(?:SH|SZ)\.\d{6})$')
IDENTIFIER = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def token_file():
    return Path(os.getenv('DRAWING_API_TOKEN_FILE', str(Path(os.getenv('DB_PATH', '/data/market.sqlite3')).parent / 'drawing-api-token.txt')))


def drawing_token():
    configured = os.getenv('DRAWING_API_TOKEN', '')
    if configured:
        return configured if len(configured) >= 32 else ''
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as handle:
            handle.write(secrets.token_urlsafe(40))
    value = path.read_text().strip()
    return value if len(value) >= 32 else ''


def authenticate(request: Request):
    expected = drawing_token()
    if not expected or not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + expected):
        raise HTTPException(401, '需要有效的画线 API Token')


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def clean_object(raw, kind, identifier, strict=False):
    defaults = dict(color={'horizontal': '#c6d6e7', 'trend': '#e3b76b', 'fib': '#739dde'}[kind],
                    lineWidth=2 if kind == 'trend' else 1, lineStyle=0 if kind == 'trend' else 2, visible=True)
    allowed = set(defaults) | {'id', 'timeframeScope'} | ({'price'} if kind == 'horizontal' else {'points', 'extend'} if kind == 'trend' else {'points', 'levels', 'levelColors'})
    if not isinstance(raw, dict) or (strict and set(raw) - allowed):
        raise ValueError('画线字段不正确')
    result = {'id': identifier}
    timeframe_scope = raw.get('timeframeScope','current')
    if strict and timeframe_scope not in ('current','all'):
        raise ValueError('周期显示范围须为 current 或 all')
    result['timeframeScope'] = 'all' if timeframe_scope == 'all' else 'current'
    for name, fallback in defaults.items():
        value = raw.get(name, fallback)
        valid = bool(COLOR.fullmatch(value)) if name == 'color' and isinstance(value, str) else isinstance(value, bool) if name == 'visible' else type(value) is int and value in ([1, 2, 3, 4] if name == 'lineWidth' else [0, 1, 2]) if name in ('lineWidth', 'lineStyle') else False
        if strict and not valid:
            raise ValueError('画线颜色、粗细、线型或显隐格式不正确')
        result[name] = value if valid else fallback
    if kind == 'horizontal':
        if not finite(raw.get('price')) or raw['price'] <= 0:
            raise ValueError('价格必须大于零')
        result['price'] = raw['price']
    else:
        points = raw.get('points')
        if not isinstance(points, list) or len(points) != 2 or any(not isinstance(p, dict) or not finite(p.get('time')) or not 0 < p['time'] <= 4102444800 or not finite(p.get('price')) or p['price'] <= 0 for p in points) or points[0]['time'] == points[1]['time']:
            raise ValueError('需要两个时间不同、价格大于零的端点，time 使用 Unix 秒')
        result['points'] = [{name: p[name] for name in ('time', 'price')} for p in points]
        if kind == 'trend':
            extend = raw.get('extend', 'none')
            if strict and extend not in ('none', 'left', 'right', 'both'):
                raise ValueError('延长方向不正确')
            result['extend'] = extend if extend in ('none', 'left', 'right', 'both') else 'none'
        else:
            if 'levels' in raw:
                levels = raw['levels']
                if not isinstance(levels, list) or len(levels) > 32 or any(not finite(r) or not 0 <= r <= 4.236 for r in levels):
                    raise ValueError('比例须为 0–4.236 的数值，最多 32 条')
                result['levels'] = list(dict.fromkeys(levels))
            colors = raw.get('levelColors', {})
            if not isinstance(colors, dict) or len(colors) > 64:
                raise ValueError('比例颜色格式不正确')
            result['levelColors'] = {}
            for ratio, color in colors.items():
                try:
                    number = float(ratio)
                    valid = math.isfinite(number) and 0 <= number <= 4.236 and isinstance(color, str) and COLOR.fullmatch(color)
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    if strict:
                        raise ValueError('比例颜色格式不正确')
                    continue
                result['levelColors'][str(int(number)) if number.is_integer() else str(number)] = color
    return result


def as_workspace(raw):
    value = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    if not isinstance(value.get('markets'), dict):
        value = {'activeMarket': 'US', 'markets': {'US': value, 'CN': {}}}
    for market in ('US', 'CN'):
        if not isinstance(value['markets'].get(market), dict):
            value['markets'][market] = {}
    return value


def drawing_view(raw):
    workspace = as_workspace(raw)
    view = {'markets': {}}
    for market in ('US', 'CN'):
        source = workspace['markets'][market]
        target = {name: {} for name in FIELDS}
        for kind, field in KINDS.items():
            records = source.get(field, {})
            if not isinstance(records, dict):
                continue
            for key, rows in records.items():
                if not isinstance(rows, list):
                    continue
                cleaned = []
                for index, row in enumerate(rows[:100]):
                    raw_row = {'price': row} if kind == 'horizontal' and finite(row) else {'points': row} if isinstance(row, list) else row
                    identifier = raw_row.get('id') if isinstance(raw_row, dict) else None
                    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or any(r['id'] == identifier for r in cleaned):
                        identifier = f'{kind}-{key}-{index}'
                    try:
                        cleaned.append(clean_object(raw_row, kind, identifier))
                    except (ValueError, TypeError):
                        continue
                target[field][key] = cleaned
        hidden = source.get('drawingsHidden', {})
        if isinstance(hidden, dict):
            target['drawingsHidden'] = {key: bool(value) for key, value in hidden.items()}
        view['markets'][market] = target
    return view


def merge_drawings(workspace, source):
    result = as_workspace(workspace)
    view = drawing_view(source)
    for market in ('US', 'CN'):
        result['markets'][market].update(view['markets'][market])
    return result


def load_workspace(db):
    row = db.execute("SELECT value FROM settings WHERE key='workspace'").fetchone()
    workspace = json.loads(row[0]) if row else {'symbols': os.getenv('DEFAULT_SYMBOLS', 'US.SNDK,US.SNXX,US.SNDQ').split(','), 'layout': 1}
    revision = db.execute("SELECT value FROM settings WHERE key='drawing_revision'").fetchone()
    return workspace, int(revision[0]) if revision else 0


def store_workspace(db, workspace, revision):
    payload = json.dumps(workspace, ensure_ascii=False, allow_nan=False)
    if len(payload.encode()) > 100000:
        raise HTTPException(413, '工作区设置过大')
    db.execute("INSERT INTO settings VALUES('workspace',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (payload,))
    db.execute("INSERT INTO settings VALUES('drawing_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(revision),))


def save_browser_workspace(db, value, expected):
    db.execute('BEGIN IMMEDIATE')
    existing, revision = load_workspace(db)
    conflict = expected != revision and (revision > 0 or expected is not None)
    result = merge_drawings(value, existing if conflict else value)
    if drawing_view(result) != drawing_view(existing):
        revision += 1
    store_workspace(db, result, revision)
    return {'ok': True, 'value': result, 'drawing_revision': revision, 'drawings_conflict': conflict}


def scope(symbol, period):
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or not isinstance(period, str) or period not in PERIODS:
        raise HTTPException(422, '请指定有效股票及周期')
    return ('US' if symbol.startswith('US.') else 'CN'), f'{symbol}:{period}'


def check_revision(request, revision):
    expected = request.headers.get('if-match')
    if expected is not None and expected.strip('"') != str(revision):
        raise HTTPException(409, '画线已更新，请重新读取后重试')


def install(app, connect_db):
    router = APIRouter(prefix='/api/drawings', dependencies=[Depends(authenticate)])

    @router.get('/capabilities')
    def capabilities():
        return {'version': 1, 'kinds': list(KINDS), 'periods': sorted(PERIODS), 'timeframe_scopes':['current','all'], 'time_unit': 'unix_seconds', 'trade_access': False, 'limits': {'objects_per_kind_and_chart': 100, 'fib_levels': 32}, 'auth': 'Bearer drawing token'}

    @router.get('/objects')
    def list_objects(symbol: str | None = None, period: str | None = None):
        if symbol is not None and not SYMBOL.fullmatch(symbol) or period is not None and period not in PERIODS:
            raise HTTPException(422, '股票或周期无效')
        with connect_db() as db:
            workspace, revision = load_workspace(db)
        view = drawing_view(workspace)
        objects = []
        for values in view['markets'].values():
            for kind, field in KINDS.items():
                for key, rows in values[field].items():
                    code, _, interval = key.rpartition(':')
                    if symbol is None or symbol == code:
                        objects.extend(dict(row, symbol=code, period=interval, kind=kind) for row in rows if period is None or period == interval or row.get('timeframeScope')=='all')
        return {'revision': revision, 'objects': objects, 'visibility': {market: value['drawingsHidden'] for market, value in view['markets'].items()}}

    @router.post('/objects')
    def create_object(request: Request, body: dict):
        if set(body) - {'symbol', 'period', 'kind', 'id', 'price', 'points', 'color', 'lineWidth', 'lineStyle', 'visible', 'extend', 'levels', 'levelColors', 'timeframeScope'}:
            raise HTTPException(422, '存在不支持的画线字段')
        kind = body.get('kind')
        if not isinstance(kind, str) or kind not in KINDS:
            raise HTTPException(422, '不支持的画线类型')
        market, key = scope(body.get('symbol'), body.get('period'))
        identifier = body.get('id', 'agent-' + uuid.uuid4().hex)
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise HTTPException(422, '画线 id 格式不正确')
        try:
            obj = clean_object({k: v for k, v in body.items() if k not in ('symbol', 'period', 'kind')}, kind, identifier, True)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        with connect_db() as db:
            db.execute('BEGIN IMMEDIATE');workspace, revision = load_workspace(db);check_revision(request, revision)
            workspace = merge_drawings(workspace, workspace)
            rows = workspace['markets'][market][KINDS[kind]].setdefault(key, [])
            old = next((row for row in rows if row['id'] == identifier), None)
            if old:
                if old != obj:
                    raise HTTPException(409, '同名 id 已存在且内容不同，请使用修改接口')
                return {'object': obj, 'revision': revision, 'created': False}
            if len(rows) >= 100:
                raise HTTPException(409, '该类型画线已达上限')
            rows.append(obj);revision += 1;store_workspace(db, workspace, revision)
        return JSONResponse({'object': obj, 'revision': revision, 'created': True}, status_code=201)

    @router.api_route('/objects/{identifier}', methods=['PATCH', 'DELETE'])
    def change_object(identifier: str, request: Request, symbol: str, period: str, kind: str, body: dict | None = None):
        market, key = scope(symbol, period)
        if kind not in KINDS:
            raise HTTPException(422, '不支持的画线类型')
        with connect_db() as db:
            db.execute('BEGIN IMMEDIATE');workspace, revision = load_workspace(db);check_revision(request, revision)
            workspace = merge_drawings(workspace, workspace)
            rows = workspace['markets'][market][KINDS[kind]].get(key, [])
            index = next((i for i, row in enumerate(rows) if row['id'] == identifier), None)
            if index is None:
                raise HTTPException(404, '画线不存在')
            obj = rows[index]
            if request.method == 'DELETE':
                rows.pop(index)
            else:
                if body is None or 'id' in body:
                    raise HTTPException(422, '修改内容不正确，不能更改 id')
                try:
                    obj = clean_object(dict(obj, **body), kind, identifier, True)
                except ValueError as exc:
                    raise HTTPException(422, str(exc))
                rows[index] = obj
            revision += 1;store_workspace(db, workspace, revision)
        return {'object': obj, 'revision': revision, 'deleted': request.method == 'DELETE'}

    @router.put('/visibility')
    def visibility(request: Request, body: dict):
        if set(body) != {'symbol', 'period', 'hidden'} or not isinstance(body.get('hidden'), bool):
            raise HTTPException(422, '需要 symbol、period、hidden 布尔值')
        market, key = scope(body.get('symbol'), body.get('period'))
        with connect_db() as db:
            db.execute('BEGIN IMMEDIATE');workspace, revision = load_workspace(db);check_revision(request, revision)
            workspace = merge_drawings(workspace, workspace);workspace['markets'][market]['drawingsHidden'][key] = body['hidden'];revision += 1;store_workspace(db, workspace, revision)
        return {'hidden': body['hidden'], 'revision': revision}

    app.include_router(router)
