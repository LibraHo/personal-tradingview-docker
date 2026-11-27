"""Separate TLS-only trading gateway. Run one worker; never expose it over plain HTTP."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .broker_provider import broker_config
from .trading import TradeEngine, TradeError

ROOT = Path(os.getenv('TRADING_DATA_DIR', '/trade-data'))
COOKIE = '__Host-nmt-session'


def digest_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: SecretStr
    setup_code: SecretStr | None = None


class Unlock(BaseModel):
    acc_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$')
    password: SecretStr
    confirm: str


class Commit(BaseModel):
    preview_id: str = Field(max_length=128)
    operation_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')


def create_app(data_dir=None, broker=None):
    root = Path(data_dir or ROOT)
    root.mkdir(parents=True, exist_ok=True)
    auth_file = root / 'auth.json'
    bootstrap_file = root / 'setup-code.txt'
    if not auth_file.exists() and not bootstrap_file.exists():
        fd = os.open(str(bootstrap_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(32))
    config = broker_config(broker)
    broker_root = config.trading_directory(root)
    engine = TradeEngine(broker_root / 'trading.sqlite3', config=config)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='trade-broker')
    gate = asyncio.Semaphore(1)
    auth_lock = asyncio.Lock()
    sessions = {}
    attempts = deque()

    async def rpc(method, *args):
        if 'trading' not in config.capabilities and method not in {'state', 'accounts', 'lock', 'preferences', 'journal'}:
            raise HTTPException(503, '当前未启用券商交易接口')
        try:
            await asyncio.wait_for(gate.acquire(), timeout=.2)
        except asyncio.TimeoutError:
            raise HTTPException(503, '上一项券商操作仍在处理，请稍后刷新；不要重复下单')
        if getattr(app.state, 'opend_restarting', False) and method not in {'lock', 'state', 'preferences'}:
            gate.release()
            raise HTTPException(503, 'OpenD 正在重启登录，请在连接面板确认恢复后再操作')
        future = asyncio.get_running_loop().run_in_executor(executor, getattr(engine, method), *args)
        try:
            return await asyncio.wait_for(asyncio.shield(future), 15)
        except asyncio.TimeoutError:
            raise HTTPException(504, '券商响应超时。若刚提交订单，请核对操作流水，系统不会自动重发。')
        except TradeError as exc:
            raise HTTPException(400, str(exc))
        except Exception:
            raise HTTPException(503, '券商暂不可用，请检查登录和网络；已提交操作请到流水核对')
        finally:
            if future.done():
                gate.release()
            else:
                def done(f):
                    try:
                        f.exception()
                    except BaseException:
                        pass
                    gate.release()
                future.add_done_callback(done)

    async def maintenance():
        while True:
            await asyncio.sleep(5)
            if 'trading' in config.capabilities:
                try:
                    await rpc('tick')
                except HTTPException:
                    pass
            expired = [k for k, v in sessions.items() if v['expires'] <= time.time()]
            for key in expired:
                sessions.pop(key, None)

    @asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(maintenance()), asyncio.create_task(strategy_poll())]
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await rpc('lock')
        except Exception:
            pass
        executor.shutdown(wait=False)

    app = FastAPI(title='NAS Market Trading', docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessions

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic error objects include input values: never reflect credentials.
        return JSONResponse({'detail': '请求字段或格式不正确'}, status_code=422)

    @app.middleware('http')
    async def security(request: Request, call_next):
        if request.url.scheme != 'https':
            return JSONResponse({'detail': '交易页面必须使用 HTTPS'}, status_code=426)
        try:
            length = int(request.headers.get('content-length', '0') or 0)
        except ValueError:
            return JSONResponse({'detail': '请求长度无效'}, status_code=400)
        body_limit = 524288 if request.url.path.startswith(('/api/market/review/', '/api/v1/review/')) else 32768
        if length > body_limit:
            return JSONResponse({'detail': '请求过大'}, status_code=413)
        drawing_agent = request.url.path.startswith('/api/drawings/')
        market_agent = request.url.path.startswith('/api/v1/')
        if drawing_agent:
            from .drawing_api import authenticate
            try:
                authenticate(request)
            except HTTPException as exc:
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        if not drawing_agent and not market_agent and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            origin = request.headers.get('origin', '')
            if origin != f'https://{request.headers.get("host", "")}' or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': '请从交易页面发起操作'}, status_code=403)
        public = request.url.path in {'/api/trade/auth', '/api/trade/login', '/api/trade/setup', '/health'}
        public = public or (request.url.path == '/api/market/settings/theme' and request.method in {'GET', 'PUT'})
        if request.url.path.startswith('/api/') and not public and not drawing_agent and not market_agent:
            token = request.cookies.get(COOKIE, '')
            key = hashlib.sha256(token.encode()).hexdigest()
            session = sessions.get(key)
            if not session or session['expires'] <= time.time():
                return JSONResponse({'detail': '请先登录交易平台'}, status_code=401)
            request.state.owner = key
            if request.method not in {'GET', 'HEAD'} and not hmac.compare_digest(
                    request.headers.get('x-csrf-token', ''), session['csrf']):
                return JSONResponse({'detail': '登录状态已变化，请刷新页面'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
        return response

    def login_response():
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()
        # Only one operator session: re-login invalidates old browser credentials.
        sessions.clear()
        sessions[key] = {'csrf': csrf, 'expires': time.time() + 8 * 3600}
        response = JSONResponse({'authenticated': True, 'csrf': csrf})
        response.set_cookie(COOKIE, token, max_age=8 * 3600, secure=True, httponly=True,
                            samesite='strict', path='/')
        return response

    def throttle():
        now = time.time()
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, '登录尝试过多，请 5 分钟后再试')
        attempts.append(now)

    @app.get('/health')
    def health():
        return {'ok': True}

    @app.get('/api/trade/auth')
    def auth(request: Request):
        key = hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest()
        session = sessions.get(key)
        valid = session and session['expires'] > time.time()
        return {'setup_required': not auth_file.exists(), 'authenticated': bool(valid),
                'csrf': session['csrf'] if valid else None}

    @app.get('/api/trade/drawing-token')
    def drawing_access(request: Request):
        from .drawing_api import drawing_token
        return {'token': drawing_token(), 'base_url': str(request.base_url).rstrip('/'), 'scope': 'drawings_only'}

    @app.post('/api/trade/setup')
    async def setup(body: Credentials):
        async with auth_lock:
            throttle()
            if auth_file.exists():
                raise HTTPException(409, '平台已初始化，请使用平台密码登录')
            code = body.setup_code.get_secret_value() if body.setup_code else ''
            if not bootstrap_file.exists() or not hmac.compare_digest(code, bootstrap_file.read_text().strip()):
                raise HTTPException(403, '初始化码不正确')
            password = body.password.get_secret_value()
            if len(password) < 12 or len(password) > 256:
                raise HTTPException(400, '平台密码须为 12 至 256 个字符；请与交易密码分开设置')
            salt = secrets.token_hex(16)
            hashed = await asyncio.to_thread(digest_password, password, salt)
            fd = os.open(str(auth_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump({'salt': salt, 'hash': hashed}, f)
            bootstrap_file.unlink()
            attempts.clear()
            return login_response()

    @app.post('/api/trade/login')
    async def login(body: Credentials):
        async with auth_lock:
            throttle()
            if not auth_file.exists():
                raise HTTPException(409, '请先初始化交易平台')
            cfg = json.loads(auth_file.read_text())
            password = body.password.get_secret_value()
            if len(password) > 256:
                raise HTTPException(400, '平台密码不正确')
            hashed = await asyncio.to_thread(digest_password, password, cfg['salt'])
            if not hmac.compare_digest(hashed, cfg['hash']):
                raise HTTPException(403, '平台密码不正确')
            # Clear any previous real grant before replacing the login session.
            await rpc('lock')
            app.state.strategies.disarm_all()
            attempts.clear()
            return login_response()

    @app.post('/api/trade/logout')
    async def logout(request: Request):
        sessions.pop(request.state.owner, None)
        app.state.strategies.disarm_all()
        try:
            await rpc('lock')
            note = '已退出并锁定交易'
        except HTTPException:
            note = '已退出平台；券商锁定尚未确认，请在券商端检查'
        response = JSONResponse({'message': note})
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
        return response

    @app.get('/api/trade/state')
    async def state(request: Request):
        return await rpc('state', request.state.owner)

    @app.get('/api/trade/accounts')
    async def accounts():
        return {'accounts': await rpc('accounts')}

    @app.get('/api/trade/snapshot')
    async def snapshot(acc_id: str, env: str):
        return await rpc('snapshot', acc_id, env)

    @app.get('/api/trade/quote')
    async def quote(code: str):
        return await rpc('quote', code)

    @app.get('/api/trade/options')
    async def options(code: str, expiry: str = ''):
        return await rpc('option_chain', code.upper(), expiry)

    @app.get('/api/trade/options/nearest')
    async def nearest(code: str, expiry: str, direction: str):
        return await rpc('nearest_option', code.upper(), expiry, direction)

    @app.get('/api/trade/options/size')
    async def option_size(acc_id: str, env: str, code: str, side: str, fraction: str, price: float):
        return await rpc('option_size', acc_id, env, code.upper(), side, fraction, price)

    @app.post('/api/trade/unlock')
    async def unlock(body: Unlock, request: Request):
        if config.source_id == 'opend' and (not body.acc_id.isdecimal() or len(body.acc_id) > 25):
            raise HTTPException(422, 'OpenD 账号格式无效')
        if body.confirm != 'UNLOCK REAL':
            raise HTTPException(400, '请确认本次实盘账号')
        return await rpc('unlock', request.state.owner, body.acc_id, body.password.get_secret_value())

    @app.post('/api/trade/lock')
    async def lock():
        app.state.strategies.disarm_all()
        return await rpc('lock')

    @app.post('/api/trade/preview')
    async def preview(body: dict, request: Request):
        return await rpc('preview', request.state.owner, body)

    @app.post('/api/trade/commit')
    async def commit(body: Commit, request: Request):
        return await rpc('commit', request.state.owner, body.preview_id, body.operation_id)

    @app.get('/api/trade/journal')
    async def journal(acc_id: str, env: str):
        rows = await rpc('journal', acc_id, env)
        return {'operations': [{k: v for k, v in r.items() if k != 'owner'} for r in rows]}

    @app.post('/api/trade/reconcile')
    async def reconcile(body: dict):
        return await rpc('reconcile', str(body.get('operation_id', '')))

    @app.post('/api/trade/acknowledge')
    async def acknowledge(body: dict):
        return await rpc('acknowledge_unknown', str(body.get('operation_id', '')), str(body.get('confirmation', '')))

    @app.get('/api/trade/presets')
    async def presets():
        return await rpc('preferences')

    @app.post('/api/trade/protection/resume')
    async def resume_protection(body: dict, request: Request):
        return await rpc('resume_protection', request.state.owner, str(body.get('id', '')))

    @app.put('/api/trade/presets')
    async def save_presets(body: dict):
        return await rpc('preferences', body)

    from .api_management import install as install_api_management
    install_api_management(app)

    from .chart_gateway import register_chart_gateway
    register_chart_gateway(app, sessions, COOKIE)

    from .strategy_api import register_strategy_api
    strategy_poll=register_strategy_api(app,broker_root,sessions,rpc)

    if config.source_id == 'opend':
        from .opend_login_api import register_opend_login
        register_opend_login(app, root, gate)

    static = Path(__file__).parent / 'static'
    if (static / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')

    @app.get('/{path:path}')
    def frontend(path: str):
        if path.startswith('api/'):
            raise HTTPException(404, '接口不存在')
        if not path:
            return RedirectResponse('/trade')
        return FileResponse(static / 'index.html')

    return app


app = create_app()
