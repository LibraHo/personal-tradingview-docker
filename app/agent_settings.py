"""Shared AI provider configuration. The original storage is retained for existing installations."""
import os
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import Field, SecretStr

from .ledger import Input, transaction


class ProviderSetting(Input):
    provider: Literal['server','local','openclaw']
    url: str = Field(default='', max_length=2000)
    agent: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,80}$')
    token: SecretStr | None = Field(default=None, max_length=8192)


def active_config(db):
    row = db.execute('SELECT provider,url,token,agent FROM plan_fill_settings WHERE id=1').fetchone()
    if row and row[0]=='openclaw':
        return tuple(row)
    if row and row[0]=='local':
        return ('local','','','')
    url = os.getenv('OPENCLAW_BASE_URL','').strip()
    token = os.getenv('OPENCLAW_GATEWAY_TOKEN','').strip()
    return ('openclaw' if url or token else 'local', url, token, os.getenv('OPENCLAW_AGENT_ID','').strip())


def install(app, connect_db):
    path = '/api/trade/agent-settings'

    @app.get('/api/trade/plan-agent', include_in_schema=False)
    @app.get(path, summary='读取全局 AI 助手配置')
    def read():
        with transaction(connect_db) as db:
            row = db.execute('SELECT provider,url,agent,length(token)>0 AS has_token FROM plan_fill_settings WHERE id=1').fetchone()
            return dict(row) if row else {'provider':'server','url':'','agent':'','has_token':False}

    @app.put('/api/trade/plan-agent', include_in_schema=False)
    @app.put(path, summary='保存全局 AI 助手配置')
    def save(body:ProviderSetting):
        with transaction(connect_db,True) as db:
            previous = db.execute('SELECT url,token,agent FROM plan_fill_settings WHERE id=1').fetchone()
            url,token,agent = tuple(previous) if previous else ('','','')
            if body.provider=='openclaw':
                url = body.url.rstrip('/')
                try:
                    parsed = urlsplit(url)
                    valid = parsed.scheme in ('http','https') and parsed.hostname and not (
                        parsed.username or parsed.password or parsed.query or parsed.fragment)
                    _ = parsed.port
                except ValueError:
                    valid = False
                if not valid:
                    raise HTTPException(422,'请填写有效的 OpenClaw 网关地址')
                token = body.token.get_secret_value().strip() if body.token else ''
                if not token:
                    token = previous[1] if previous and previous[0]==url else ''
                if not token or not token.isascii() or any(ord(c)<33 or ord(c)>126 for c in token):
                    raise HTTPException(422,'请为此网关填写有效的凭证')
                agent = body.agent
            db.execute('INSERT OR REPLACE INTO plan_fill_settings VALUES(1,?,?,?,?)',(body.provider,url,token,agent))
        return {'saved':True}
