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


def register_chart_gateway(app, sessions, cookie):
    upstream = os.getenv('MARKET_INTERNAL_URL', 'http://market:8000').rstrip('/')
    allowed = {
        'GET': {'status', 'cache/status', 'trading-config', 'depth', 'symbols/names',
                'quotes', 'bars', 'bars/older', 'indicators'},
        'POST': {'quote/retry', 'python-indicator/validate', 'python-indicator', 'watchlists/import-moomoo', 'strategy/evaluate'},
    }

    @app.api_route('/api/market/{path:path}', methods=['GET', 'POST', 'PUT'])
    async def market_proxy(path: str, request: Request):
        setting = re.fullmatch(r'settings/(?:workspace|templates|depth-US\.[A-Z][A-Z0-9.]{0,11})', path)
        if path not in allowed.get(request.method, set()) and not (setting and request.method in {'GET', 'PUT'}):
            raise HTTPException(404, '行情接口不存在')
        body = await request.body()
        if len(body) > 32768:
            raise HTTPException(413, '请求过大')
        url = upstream + '/api/' + path + ('?' + request.url.query if request.url.query else '')

        def forward():
            req = urllib.request.Request(url, data=body if request.method != 'GET' else None,
                                         method=request.method, headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
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
