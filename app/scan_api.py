"""Versioned, scoped agent API and same-origin browser scan controls."""
import asyncio
import hashlib
import json
import secrets
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from .scan_service import JobConflict, dump, uid


class Operand(BaseModel):
    name: str
    line: str = ''
    params: dict[str,float] = Field(default_factory=dict)
    value: float = 6
    scale: float = 1
    offset: int = Field(default=0,ge=0,le=250)

class Rule(BaseModel):
    name: str = Field(default="",max_length=100)
    left: Operand
    op: str
    right: Operand
    period: str | None = None
    offset: int = Field(default=0,ge=0,le=250)
    temporal: str = "current"
    window: int = Field(default=1,ge=1,le=250)
    min_count: int = Field(default=1,ge=1,le=250)
    max_count: int | None = Field(default=None,ge=1,le=250)

class Plan(BaseModel):
    name: str = Field(default='新扫描方案',max_length=100)
    rules: list[Rule] = Field(min_length=1,max_length=12)
    periods: list[str] = Field(default=['1d'],min_length=1,max_length=10)
    join: str = 'all'
    lookback: int = Field(default=1,ge=1,le=50)
    live: bool = True
    scope: dict = Field(default_factory=lambda:{'kind':'all'})

class RunRequest(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    force: bool = False
    reuse_seconds: int = Field(default=86400, ge=0, le=604800)


class LimitBoardStock(BaseModel):
    symbol: str
    name: str | None = None
    industry: str | None = None
    price: float | None = None
    change: float | None = Field(default=None, description='涨跌幅，%')
    streak: int | None = Field(default=None, description='连续涨停交易日数')
    reopen_count: int | None = None
    first_seal: int | None = Field(default=None, description='首次封板，北京时间 HHMMSS 数字')
    last_seal: int | None = Field(default=None, description='最近封板，北京时间 HHMMSS 数字')
    sealed_funds: float | None = Field(default=None, description='封单金额，元')
    turnover_amount: float | None = Field(default=None, description='当日成交额，元')
    turnover_pct: float | None = Field(default=None, description='换手率，%')
    float_market_cap: float | None = Field(default=None, description='流通市值，元')
    seal_to_turnover_pct: float | None = Field(default=None, description='封单金额占成交额的百分比')
    seal_to_float_pct: float | None = Field(default=None, description='封单金额占流通市值的百分比')


class LimitBoardSnapshot(BaseModel):
    trade_date: str
    dates: list[str]
    sealed: list[LimitBoardStock]
    broken: list[LimitBoardStock]
    updated: float = Field(description='抓取时间，Unix 秒')
    stale: bool
    source: str
    error: str | None = None


class Monitor(BaseModel):
    plan_id: str
    name: str = '后台监控'
    interval_seconds: int = Field(default=120,ge=30,le=86400)
    follow_watchlists: bool = True
    backfill: bool = False
    trading_only: bool = True
    enabled: bool = True
    event_mode: str = "on_enter"
    schedule: dict | None = None

API_SCOPES = {'read', 'manage', 'tokens', 'review:read', 'review:write'}
bearer = HTTPBearer(auto_error=False)


def token_scopes(db_factory, credential):
    if not credential:
        raise HTTPException(401, '需要 Bearer API token', headers={'WWW-Authenticate': 'Bearer'})
    digest = hashlib.sha256(credential.credentials.encode()).hexdigest()
    with db_factory() as db:
        row = db.execute('SELECT scopes FROM scan_tokens WHERE digest=? AND revoked=0', (digest,)).fetchone()
    if not row:
        raise HTTPException(401, 'Token 无效或已撤销', headers={'WWW-Authenticate': 'Bearer'})
    return json.loads(row[0])


def issue_token(db_factory, name, scopes):
    if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or s not in API_SCOPES for s in scopes):
        raise ValueError('权限无效')
    scopes = list(dict.fromkeys(scopes))
    token=secrets.token_urlsafe(40); ident=uid()
    with db_factory() as db:
        db.execute('INSERT INTO scan_tokens VALUES(?,?,?,?,?,0)',(ident,hashlib.sha256(token.encode()).hexdigest(),name,dump(scopes),time.time()))
    return {'id':ident,'token':token,'scopes':scopes}

def install(app, service):
    from .market_analytics import Analytics
    analytics=Analytics(service)
    def authorize(request:Request, credential:HTTPAuthorizationCredentials|None=Depends(bearer)):
        scopes=token_scopes(service.db, credential);needed='read' if request.method=='GET' else 'manage'
        if '/tokens' in request.url.path:needed='tokens'
        if needed not in scopes: raise HTTPException(403,'Token 缺少 '+needed+' 权限')

    api=APIRouter(prefix='/api/v1',dependencies=[Depends(authorize)],tags=['OpenClaw market API'])
    browser=APIRouter(prefix='/api/scanner',tags=['Scanner browser'])
    def both(path,methods):
        def register(fn):
            api.add_api_route(path,fn,methods=methods)
            browser.add_api_route(path,fn,methods=methods)
            return fn
        return register

    async def invoke(fn,*args):
        try:
            value=fn(*args)
            return await value if __import__('inspect').isawaitable(value) else value
        except JobConflict as e: raise HTTPException(409,str(e)) from e
        except KeyError as e: raise HTTPException(404,'记录不存在') from e
        except ValueError as e: raise HTTPException(422,str(e)) from e

    @both('/watchlists',['GET'])
    async def watchlists(market:str|None=None):return await invoke(service.watchlists,market)

    @both('/scope-preview',['POST'])
    async def scope_preview(body:dict):
        rows=await invoke(service.resolve,body,True)
        return {'rows':rows,'total':len(rows),'market':body.get('market')}

    @both('/plans',['GET'])
    def plans():return {'items':service.list('plans')}

    @both('/plans',['POST'])
    async def create_plan(body:Plan):return await invoke(service.plan,body.model_dump())

    @both('/plans/{ident}',['GET'])
    async def get_plan(ident:str):return await invoke(service.get,'plans',ident)

    @both('/plans/{ident}',['PUT'])
    async def update_plan(ident:str,body:Plan):return await invoke(service.plan,body.model_dump(),ident)

    @both('/plans/{ident}',['DELETE'])
    def delete_plan(ident:str):
        with service.db() as db:db.execute('DELETE FROM scan_plans WHERE id=?',(ident,))
        return {'ok':True,'note':'既有监控保留创建时的方案版本'}

    @both('/plans/{ident}/copy',['POST'])
    async def copy_plan(ident:str):
        p=await invoke(service.get,'plans',ident);p['name']=p.get('name','')+' 副本'
        return await invoke(service.plan,p)

    @both('/plans/{ident}/run',['POST'])
    async def run(ident:str, request:Request, response:Response, body:RunRequest|None=None,
                  idempotency_key:str|None=Header(default=None)):
        options = (body or RunRequest()).model_dump()
        if idempotency_key:
            if options['request_id'] and options['request_id'] != idempotency_key:
                raise HTTPException(409, '请求头与请求体的幂等编号不一致')
            options['request_id'] = idempotency_key
        plan = await invoke(service.get, 'plans', ident)
        job = await invoke(service.submit, plan, None, options['request_id'], options['force'],
                           options['reuse_seconds'], 'browser' if '/api/scanner/' in request.url.path else 'api')
        response.status_code = 200 if job['complete'] or job['status'] == 'paused' else 202
        if job.get('retry_after_seconds'):
            response.headers['Retry-After'] = str(job['retry_after_seconds'])
        return job

    @both('/plans/{ident}/results',['GET'])
    async def plan_results(ident:str, max_age_seconds:int=Query(default=86400,ge=0,le=604800)):
        return await invoke(service.plan_results, await invoke(service.get, 'plans', ident), max_age_seconds)

    @both('/jobs',['GET'])
    async def jobs(market:str='', plan_id:str='', status:str='', limit:int=Query(default=100,ge=1,le=100),
                   cursor:str|None=Query(default=None,max_length=256)):
        if market not in ('', 'CN', 'US'):
            raise HTTPException(422, '市场须为 CN 或 US')
        rows=await invoke(asyncio.to_thread, service.job_summaries, market, plan_id, status, limit+1, cursor)
        items=rows[:limit]
        next_cursor=None
        if len(rows)>limit and items:
            last=items[-1]
            next_cursor=str(last.get('created',last['updated']))+':'+last['id']
        return {'items':items,'has_more':len(rows)>limit,'next_cursor':next_cursor}

    @api.get('/requests/{request_id}')
    async def request_receipt(request_id:str):
        if not 1 <= len(request_id) <= 128:
            raise HTTPException(422, '请求编号长度无效')
        def lookup():
            with service.db() as db:
                row=db.execute('SELECT job_id FROM scan_requests WHERE request_id=?',(request_id,)).fetchone()
            if not row:
                raise KeyError(request_id)
            value=service.job_view(row[0])
            return {key:item for key,item in value.items() if key not in ('results','targets','monitor_snapshot','scope_snapshot')}
        return await invoke(asyncio.to_thread, lookup)

    @both('/jobs/{ident}',['GET'])
    async def job(ident:str, summary:bool=False):
        value = await invoke(asyncio.to_thread, service.job_view, ident)
        if summary:
            value = {key: item for key, item in value.items() if key not in ('results', 'targets', 'monitor_snapshot', 'scope_snapshot')}
        return value

    @both('/jobs/{ident}/retry',['POST'])
    async def retry(ident:str, request:Request, response:Response):
        job = await invoke(service.retry, ident, 'browser' if '/api/scanner/' in request.url.path else 'api')
        response.status_code = 200 if job['complete'] else 202
        if job.get('retry_after_seconds'):
            response.headers['Retry-After'] = str(job['retry_after_seconds'])
        return job

    @both('/jobs/{ident}/cancel',['POST'])
    async def cancel(ident:str):
        return await invoke(service.control, ident, 'cancel')

    @both('/jobs/{ident}/pause',['POST'])
    async def pause(ident:str):
        return await invoke(service.control, ident, 'pause')

    @both('/jobs/{ident}/resume',['POST'])
    async def resume(ident:str):
        return await invoke(service.control, ident, 'resume')

    @both('/monitors',['GET'])
    def monitors():return {'items':service.list('monitors')}

    @both('/monitors',['POST'])
    async def monitor(body:Monitor):return await invoke(service.create_monitor,body.model_dump())

    @both('/monitors/{ident}',['GET'])
    async def get_monitor(ident:str):return await invoke(service.get,'monitors',ident)

    @both('/monitors/{ident}',['PUT'])
    async def update_monitor(ident:str, body:dict):
        unknown=set(body)-set(Monitor.model_fields)
        if unknown:
            raise HTTPException(422, '未知监控配置字段：'+','.join(sorted(unknown)))
        current=await invoke(service.get,'monitors',ident)
        values={key:current[key] for key in Monitor.model_fields if key in current}
        values.update(body)
        try:
            validated=Monitor(**values).model_dump()
        except ValueError as error:
            raise HTTPException(422,str(error)) from error
        return await invoke(service.update_monitor,ident,validated,set(body))

    @both('/monitors/{ident}/{action}',['POST'])
    async def monitor_action(ident:str,action:str):
        if action not in ('start','pause'):raise HTTPException(422,'操作须为 start 或 pause')
        m=await invoke(service.get,'monitors',ident);m['enabled']=action=='start';m['next_run']=0
        m['force_run']=action=='start'
        return service.put('monitors',m)

    @both('/events',['GET'])
    def events(after:int=0,limit:int=100,monitor_id:str='',symbol:str='',confirmation:str='',market:str='',period:str='',plan_id:str=''):
        if after<0 or not 1<=limit<=500:raise HTTPException(422,'分页无效')
        clauses=['cursor>?'];params=[after]
        for k,v in [('monitor_id',monitor_id),('symbol',symbol)]:
            if v:clauses.append(k+'=?');params.append(v)
        for k,v in [('market',market),('period',period),('plan_id',plan_id)]:
            if v:clauses.append("json_extract(payload,'$."+k+"')=?");params.append(v)
        if confirmation:
            if confirmation not in ('confirmed','preview'):raise HTTPException(422,'确认状态无效')
            clauses.append("json_extract(payload,'$.confirmation')=?");params.append(confirmation)
        with service.db() as db:
            rows=db.execute('SELECT cursor,payload FROM scan_events WHERE '+' AND '.join(clauses)+' ORDER BY cursor LIMIT ?',(*params,limit+1)).fetchall()
        items=[{**json.loads(r[1]),'cursor':r[0]} for r in rows[:limit]]
        return {'items':items,'next_cursor':items[-1]['cursor'] if items else after,'has_more':len(rows)>limit}

    @both('/health',['GET'])
    def health():
        monitors=service.list('monitors')
        with service.db() as db:
            last=db.execute("SELECT MAX(json_extract(payload,'$.finished')) FROM scan_jobs WHERE json_extract(payload,'$.status')='completed'").fetchone()[0]
        return {**service.main.status(),'scheduler_running':service.worker is not None and not service.worker.done(),
            'last_successful_scan':last or 0,
            'monitor_count':len(monitors),'errors':[{'id':m['id'],'error':m['last_error']} for m in monitors if m.get('last_error')]}

    @api.get('/markets')
    def markets():
        sources = service.market_sources()
        adjustments = {row['adjustment'].upper() for row in sources.values()}
        return {'markets':['CN','US'], 'categories':{'CN':['industry','concept'],'US':['industry','concept','theme','etf']},
                'market_sources':sources, 'session':'regular',
                'adjustment':next(iter(adjustments)) if len(adjustments) == 1 else 'MIXED' if adjustments else None}

    async def radar_query(method, *args):
        try:
            return await asyncio.to_thread(method, *args)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, RuntimeError, ImportError) as exc:
            raise HTTPException(503, str(exc)) from exc

    @api.get('/sectors')
    async def sectors(market:str='CN',kind:str='industry',page:str='',q:str=''):
        if kind == 'theme':
            r = await radar_query(service.radar.heatmap, market, kind, page)
        else:
            r = await radar_query(service.radar.catalog, market, kind)
        if q:r={**r,'rows':[x for x in r['rows'] if q.lower() in (x['name']+' '+x['symbol']).lower()]}
        return r

    @api.get('/sectors/heatmap')
    async def heatmap(market:str='CN',kind:str='industry',page:str=''):
        return await radar_query(service.radar.heatmap, market, kind, page)

    @api.get('/sectors/members')
    async def members(symbol:str):
        return await radar_query(service.radar.members, symbol)

    @api.get('/emotion')
    async def emotion(market:str='CN',symbol:str=''):
        return await radar_query(service.radar.emotion, market, symbol)

    @api.get('/limit-up', summary='沪深 A 股打板行情', response_model=LimitBoardSnapshot, response_model_exclude_unset=True)
    @app.get('/api/radar/limit-up', summary='沪深 A 股打板行情', response_model=LimitBoardSnapshot, response_model_exclude_unset=True)
    async def limit_board(day:str|None=Query(default=None, description='最近五个交易日之一，格式 YYYY-MM-DD，默认最新交易日')):
        """返回去重的封板和炸板名单。行情缺失字段为 null；上游失败时，可用的同日缓存会标记 stale 并附 error。"""
        try:
            return await __import__('asyncio').to_thread(analytics.limit_board,day)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise HTTPException(422 if str(exc)=='请选择最近五个交易日' else 503,str(exc)) from exc

    @api.get('/emotion/analytics')
    @app.get('/api/radar/analytics')
    async def emotion_analytics(market:str='CN',refresh:bool=False):return await invoke(analytics.get,market,refresh)

    @api.get('/bars')
    async def bars(symbol:str, period:str='1d'):
        rows = await invoke(service.load, symbol, period)
        market = 'US' if symbol.upper().startswith('US.') else 'CN'
        route = service.market_sources(market).get(market, {})
        last = rows[-1] if rows else {}
        basis = last.get('adjustment') or route.get('adjustment')
        providers = sorted({row['provider'] for row in rows if row.get('provider')})
        return {'bars':rows, 'source':route.get('history') or last.get('provider'), 'bar_providers':providers,
                'adjustment':basis.upper() if basis else None, 'session':'regular', 'market_sources':route}

    @api.get('/quotes')
    async def quotes(symbols:str):return await service.main.quotes(symbols)

    @api.get('/tokens')
    def tokens():
        with service.db() as db:return {'items':[dict(r) for r in db.execute('SELECT id,name,scopes,created,revoked FROM scan_tokens')]}

    @api.post('/tokens')
    def token(body:dict):
        try:return issue_token(service.db,str(body.get('name','API'))[:100],body.get('scopes',['read']))
        except ValueError as e:raise HTTPException(422,str(e))

    @api.delete('/tokens/{ident}')
    def revoke(ident:str):
        with service.db() as db:db.execute('UPDATE scan_tokens SET revoked=1 WHERE id=?',(ident,))
        return {'ok':True}

    app.include_router(api);app.include_router(browser)
