"""Authenticated, same-origin forwarding to the separate read-only chart service."""
import asyncio
import hashlib
import os
import re
import time
import urllib.error
import urllib.request

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import Response
from .drawing_api import authenticate as authenticate_drawing


def register_chart_gateway(app, sessions, cookie):
    upstream = os.getenv('MARKET_INTERNAL_URL', 'http://market:8000').rstrip('/')
    @app.get('/api/drawings/{path:path}')
    @app.post('/api/drawings/{path:path}')
    @app.patch('/api/drawings/{path:path}')
    @app.delete('/api/drawings/{path:path}')
    @app.put('/api/drawings/{path:path}')
    async def drawing_proxy(path: str, request: Request):
        authenticate_drawing(request)
        allowed_drawing = {'capabilities': {'GET'}, 'objects': {'GET', 'POST'}, 'visibility': {'PUT'}}
        methods = {'PATCH', 'DELETE'} if re.fullmatch(r'objects/[A-Za-z0-9_.:-]{1,128}', path) else allowed_drawing.get(path, set())
        if request.method not in methods:
            raise HTTPException(404, '画线接口不存在')
        body = await request.body()
        if len(body) > 32768:
            raise HTTPException(413, '请求过大')
        url = upstream + '/api/drawings/' + path + ('?' + request.url.query if request.url.query else '')
        def forward_drawing():
            headers = {'Content-Type': 'application/json', 'Authorization': request.headers['authorization']}
            if request.headers.get('if-match'):
                headers['If-Match'] = request.headers['if-match']
            req = urllib.request.Request(url, data=body if request.method != 'GET' else None, method=request.method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
        try:
            status, payload = await asyncio.to_thread(forward_drawing)
        except (OSError, urllib.error.URLError):
            raise HTTPException(503, '画线服务暂不可用')
        return Response(payload, status_code=status, media_type='application/json')

    allowed = {
        'GET': {'status', 'cache/status', 'trading-config', 'depth', 'symbols/names', 'symbols/search',
                'quotes', 'order-flow', 'option-profile', 'bars', 'bars/older', 'bars/window', 'indicators', 'opening-range',
                'radar/catalog', 'radar/members', 'radar/heatmap', 'radar/emotion', 'radar/analytics', 'radar/limit-up'},
        'POST': {'quote/retry', 'python-indicator/validate', 'python-indicator', 'watchlists/import-moomoo', 'strategy/evaluate'},
    }

    @app.patch('/api/v1/review/days/{day}')
    async def review_patch_proxy(day: str, request: Request):
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day):
            raise HTTPException(404, '复盘接口不存在')
        return await agent_proxy('review/days/' + day, request)

    @app.get('/api/v1/{path:path}')
    @app.post('/api/v1/{path:path}')
    @app.put('/api/v1/{path:path}')
    @app.delete('/api/v1/{path:path}')
    async def agent_proxy(path: str, request: Request):
        body = await request.body()
        is_review = path.startswith('review/')
        if len(body) > (524288 if is_review else 32768):
            raise HTTPException(413, '请求过大')
        def forward_agent():
            headers={'Content-Type':'application/json','Authorization':request.headers.get('authorization','')}
            if request.headers.get('idempotency-key'):
                headers['Idempotency-Key']=request.headers['idempotency-key']
            req=urllib.request.Request(upstream+'/api/v1/'+path+('?' + request.url.query if request.url.query else ''),
                data=body if request.method!='GET' else None,method=request.method,headers=headers)
            try:
                with urllib.request.urlopen(req,timeout=180) as r:return r.status,r.read()
            except urllib.error.HTTPError as e:return e.code,e.read()
        try: status,payload=await asyncio.to_thread(forward_agent)
        except (OSError,urllib.error.URLError):
            raise HTTPException(503, '复盘服务暂不可用' if is_review else '扫描服务暂不可用')
        headers = {'WWW-Authenticate': 'Bearer'} if status == 401 and is_review else None
        return Response(payload,status_code=status,media_type='application/json',headers=headers)

    @app.get('/api/market/{path:path}')
    @app.post('/api/market/{path:path}')
    @app.put('/api/market/{path:path}')
    @app.delete('/api/market/{path:path}')
    async def market_proxy(path: str, request: Request):
        setting = re.fullmatch(r'settings/(?:workspace|templates|theme|depth-US\.[A-Z][A-Z0-9.]{0,11})', path)
        scanner = re.fullmatch(r'scanner/(?:watchlists|scope-preview|plans|jobs|monitors|events|health)(?:/[a-f0-9]{32}(?:/(?:copy|run|results|cancel|start|pause|resume))?)?',path)
        review_methods = {'review/dashboard': {'GET'}, 'review/export': {'GET'}, 'review/rules': {'POST'}}
        ledger_routes = {
            'GET': r'autofill/history|book|backlinks|opend|(?:plans|fills)/[a-f0-9]{32}|plans/[a-f0-9]{32}/(?:daily|bars)',
            'POST': r'autofill|plans|fills|positions|reconcile|opend/sync',
            'PUT': r'plans/[a-f0-9]{32}(?:/fills/[a-f0-9]{32})?|fills/[a-f0-9]{32}/review',
            'DELETE': r'plans/[a-f0-9]{32}(?:/fills/[a-f0-9]{32})?',
        }
        ledger_path = path.removeprefix('review/ledger/')
        ledger = path.startswith('review/ledger/') and re.fullmatch(ledger_routes.get(request.method, r'(?!)'), ledger_path)
        review = ledger or request.method in review_methods.get(path, set()) or (
            request.method == 'PUT' and re.fullmatch(r'review/(?:rules/[a-z0-9-]{1,64}|(?:days|weeks)/[0-9]{4}-[0-9]{2}-[0-9]{2})', path))
        if path not in allowed.get(request.method, set()) and not scanner and not review and not (setting and request.method in {'GET', 'PUT'}):
            raise HTTPException(404, '行情接口不存在')
        body = await request.body()
        if len(body) > (524288 if review else 32768):
            raise HTTPException(413, '请求过大')
        url = upstream + '/api/' + path + ('?' + request.url.query if request.url.query else '')

        def forward():
            headers={'Content-Type':'application/json'}
            if request.headers.get('idempotency-key'):
                headers['Idempotency-Key']=request.headers['idempotency-key']
            req = urllib.request.Request(url, data=body if request.method != 'GET' else None,
                                         method=request.method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=225 if ledger_path=='autofill' else 30) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
        try:
            status, payload = await asyncio.to_thread(forward)
        except (OSError, urllib.error.URLError):
            raise HTTPException(503, '行情服务暂不可用')
        return Response(payload, status_code=status, media_type='application/json')

    @app.websocket('/api/market/stream')
    async def market_stream(ws: WebSocket):
        key = hashlib.sha256(ws.cookies.get(cookie, '').encode()).hexdigest()
        session = sessions.get(key)
        if (ws.url.scheme != 'wss' or ws.headers.get('origin') != 'https://' + ws.headers.get('host', '')
                or not session or session['expires'] <= time.time()):
            await ws.close(code=1008)
            return
        await ws.accept()
        from websockets.legacy.client import connect
        url = upstream.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
        url += '/api/stream?' + ws.url.query
        try:
            async with connect(url, open_timeout=10, max_size=2**20) as source:
                async def downstream():
                    async for message in source:
                        if key not in sessions or session['expires'] <= time.time():
                            return
                        await ws.send_text(message)
                async def disconnected():
                    while True:
                        if (await ws.receive())['type'] == 'websocket.disconnect':
                            return
                tasks = [asyncio.create_task(downstream()), asyncio.create_task(disconnected())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
        finally:
            try:
                await ws.close(code=1001)
            except RuntimeError:
                pass
