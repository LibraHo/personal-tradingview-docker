"""Operator notification configuration; installed only behind HTTPS session + CSRF."""
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from .notifications import Notifications


class ChannelInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    url: SecretStr | None = Field(default=None, max_length=4096)
    headers: dict[str,SecretStr] | None = None
    format: Literal['json','form'] = 'json'
    title_field: str = Field(default='title', max_length=64)
    body_field: str = Field(default='body', max_length=64)
    success_field: str = Field(default='', max_length=100)
    success_value: str = Field(default='', max_length=100)
    extra_fields: dict[str,str] = Field(default_factory=dict)
    monitor_ids: list[str] = Field(default_factory=list, max_length=100)
    confirmation: Literal['confirmed','preview','all'] = 'confirmed'
    daily_limit: int = Field(default=100, ge=1, le=1000)


def install(app, connect_db):
    service = Notifications(connect_db)
    path = '/api/trade/notifications'

    def ready():
        service.init()
        return service

    def call(fn, *args):
        try:
            return fn(*args)
        except KeyError:
            raise HTTPException(404, '通知渠道不存在')
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get(path, tags=['Notifications'], summary='读取通知渠道、监控和投递记录')
    def read():
        s = ready()
        return {'channels':s.channels(),'monitors':s.monitors(),'records':s.records()}

    def save(body, ident=None):
        data = body.model_dump(exclude={'url','headers'})
        if body.url is not None:
            data['url'] = body.url.get_secret_value()
        if body.headers is not None:
            data['headers'] = {k:v.get_secret_value() for k,v in body.headers.items()}
        return call(ready().save,data,ident)

    @app.post(path+'/channels', tags=['Notifications'], summary='创建通知渠道')
    def create(body:ChannelInput):
        return save(body)

    @app.put(path+'/channels/{ident}', tags=['Notifications'], summary='更新通知渠道；凭证留空沿用')
    def update(ident:str, body:ChannelInput):
        return save(body,ident)

    @app.delete(path+'/channels/{ident}', tags=['Notifications'], summary='删除渠道并取消待投递消息')
    def delete(ident:str):
        call(ready().delete,ident)
        return {'ok':True}

    @app.post(path+'/channels/{ident}/test', tags=['Notifications'], summary='排队发送一条测试通知')
    def test(ident:str):
        return {'id':call(ready().test,ident), 'status':'pending'}
