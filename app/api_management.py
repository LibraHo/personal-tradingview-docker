"""Operator-only API inventory and scoped token administration.

Installed only on the HTTPS application, behind its session and CSRF middleware.
No master credential is forwarded to the browser.
"""
import json
import os
import sqlite3
import urllib.request
from contextlib import contextmanager
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .scan_api import API_SCOPES, issue_token


@contextmanager
def token_db():
    path = os.getenv('DB_PATH', '/data/market.sqlite3')
    db = sqlite3.connect('file:' + path + '?mode=rw', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def market_schema():
    url = os.getenv('MARKET_INTERNAL_URL', 'http://market:8000').rstrip('/')
    with urllib.request.urlopen(url + '/openapi.json', timeout=10) as response:
        return json.load(response)


class TokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default=['read'], min_length=1, max_length=len(API_SCOPES))


def install(app):
    from .agent_settings import install as install_agent_settings
    from .market_analysis import install as install_market_analysis
    install_agent_settings(app, token_db)
    install_market_analysis(app, token_db)
    prefix = '/api/trade/api-management'

    @app.get(prefix + '/inventory', tags=['API management'])
    def inventory():
        errors = []
        schemas = {'https': app.openapi()}
        try:
            schemas['market'] = market_schema()
        except (OSError, ValueError) as exc:
            errors.append('行情接口目录加载失败：' + type(exc).__name__)
        items = []
        for source, schema in schemas.items():
            for path, methods in schema.get('paths', {}).items():
                if not path.startswith('/api/') and path != '/health':
                    continue
                for method, operation in methods.items():
                    if method not in {'get','post','put','patch','delete','head','options'}:
                        continue
                    if path.startswith('/api/v1/review/'):
                        auth = 'Bearer · ' + ('review:read' if method == 'get' else 'review:write')
                        category = 'OpenClaw / 每日复盘'
                    elif path.startswith('/api/v1/'):
                        auth = 'Bearer · ' + ('tokens' if '/tokens' in path else 'read' if method == 'get' else 'manage')
                        category = 'OpenClaw / 数据与扫描'
                    elif path.startswith('/api/drawings/'):
                        auth, category = '独立画线 Bearer', '画线'
                    elif source == 'https':
                        public = path in {'/health','/api/trade/auth','/api/trade/login','/api/trade/setup'}
                        auth = '公开入口 / 登录流程' if public else 'HTTPS 登录会话' + (' + CSRF' if method not in {'get','head'} else '')
                        category = 'API 管理' if path.startswith(prefix) else '交易与安全入口'
                    else:
                        auth, category = '可信内网浏览器接口；HTTPS 入口需登录', '行情与浏览器工作区'
                    items.append({'source':source,'path':path,'method':method.upper(),
                        'category':category,'auth':auth,'summary':operation.get('summary',''),
                        'description':operation.get('description',''),'operation':operation})
        return {'items':items, 'schemas':schemas, 'errors':errors,
                'websockets':[{'path':'/api/stream','source':'market','auth':'可信内网行情推送'},
                              {'path':'/api/market/stream','source':'https','auth':'HTTPS 登录会话'}]}

    @app.get(prefix + '/tokens', tags=['API management'])
    def tokens():
        try:
            with token_db() as db:
                rows = db.execute('SELECT id,name,scopes,created,revoked FROM scan_tokens ORDER BY created DESC').fetchall()
            return {'items':[{**dict(r),'scopes':json.loads(r['scopes'])} for r in rows]}
        except sqlite3.Error:
            raise HTTPException(503, 'API 凭证库暂不可用')

    @app.post(prefix + '/tokens', tags=['API management'])
    def create(body: TokenRequest):
        try:
            return issue_token(token_db, body.name.strip() or 'API', body.scopes)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except sqlite3.Error:
            raise HTTPException(503, 'API 凭证库暂不可用')

    @app.delete(prefix + '/tokens/{ident}', tags=['API management'])
    def revoke(ident: str):
        try:
            with token_db() as db:
                result = db.execute('UPDATE scan_tokens SET revoked=1 WHERE id=?', (ident,))
                if not result.rowcount:
                    raise HTTPException(404, '凭证不存在')
            return {'ok':True}
        except sqlite3.Error:
            raise HTTPException(503, 'API 凭证库暂不可用')
