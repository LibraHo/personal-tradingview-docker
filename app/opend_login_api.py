"""TLS gateway to the narrowly scoped, private OpenD login adapter."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from typing import Literal


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['account', 'password', 'sms', 'captcha', 'request_sms', 'request_captcha', 'restart']
    revision: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    value: SecretStr = SecretStr('')


class BridgeRejected(HTTPException):
    def __init__(self, message, not_started=False):
        super().__init__(409, message)
        self.not_started = not_started


def exchange(body):
    path = os.getenv('OPEND_LOGIN_SOCKET', '')
    if not path:
        raise HTTPException(503, '此部署尚未启用 OpenD 网页登录适配器')
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(20 if body.get('action') == 'restart' else 3)
            try:
                connection.connect(path)
            except OSError:
                if body.get('action') == 'restart':
                    raise BridgeRejected('登录适配器未连接，未执行重启，请稍后重试', not_started=True) from None
                raise
            connection.sendall((json.dumps(body, ensure_ascii=True) + '\n').encode())
            chunks, length = [], 0
            while True:
                chunk = connection.recv(8192)
                if not chunk:
                    raise OSError('Incomplete adapter response')
                chunks.append(chunk)
                length += len(chunk)
                if length > 400000:
                    raise OSError('Adapter response too large')
                if b'\n' in chunk:
                    break
            result = json.loads(b''.join(chunks).split(b'\n', 1)[0])
    except (OSError, ValueError):
        raise HTTPException(503, 'OpenD 登录适配器暂不可用，请检查 OpenD 容器是否运行') from None
    if result.get('ok') is not True:
        raise BridgeRejected(result.get('message', '登录状态已变化，请刷新后再试'),
                             result.get('code') == 'restart_not_started')
    return result['data']


def ensure_restart_safe(app, root):
    # An unlock grant is local state and must not survive an OpenD restart.
    if app.state.engine.grant:
        raise HTTPException(409, '请先锁定交易，再重启 OpenD 登录')
    try:
        for name in ('trading.sqlite3', 'strategies.sqlite3'):
            path = Path(root) / name
            if not path.is_file():
                raise ValueError('Missing activity database')
            with closing(sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True, timeout=2)) as db:
                if name == 'trading.sqlite3':
                    inflight = db.execute("SELECT COUNT(*) FROM operations WHERE state IN ('SENDING','UNKNOWN')").fetchone()[0]
                    waiting = any(json.loads(row[0]).get('state') == 'WAITING' for row in db.execute('SELECT data FROM protection'))
                    if inflight or waiting:
                        raise HTTPException(409, '仍有待处理订单或待补挂止损，请先处理后再重启 OpenD')
                elif db.execute('SELECT COUNT(*) FROM strategies WHERE enabled=1').fetchone()[0]:
                    raise HTTPException(409, '请先停用监控策略，再重启 OpenD 登录')
    except (sqlite3.Error, ValueError, OSError):
        raise HTTPException(409, '暂时无法确认交易任务状态，未执行 OpenD 重启') from None


def register_opend_login(app, root, trade_gate):
    guard = asyncio.Lock()
    app.state.opend_restarting = False
    app.state.opend_restart_generation = -1
    app.state.opend_restart_instance = ''
    app.state.opend_restart_task = None

    def recovered(result):
        return ((result.get('process_generation', -1) > app.state.opend_restart_generation
                 or (bool(result.get('instance_id')) and result['instance_id'] != app.state.opend_restart_instance))
                and result.get('stage') in {'account', 'password', 'sms', 'captcha', 'ready'})

    @app.get('/api/trade/opend/status')
    async def status():
        try:
            result = await asyncio.to_thread(exchange, {'action': 'status'})
            task = app.state.opend_restart_task
            if app.state.opend_restarting and (task is None or task.done()) and recovered(result):
                app.state.opend_restarting = False
            return result
        except HTTPException as exc:
            return {'available': False, 'stage': 'unavailable', 'revision': '', 'version': '',
                    'message': exc.detail, 'retry_allowed': False}

    @app.get('/api/trade/opend/captcha')
    async def captcha():
        return await asyncio.to_thread(exchange, {'action': 'captcha_image'})

    @app.post('/api/trade/opend/input')
    async def submit(request: Request):
        raw = bytearray()
        async for block in request.stream():
            if len(raw) + len(block) > 4096:
                raise HTTPException(413, '登录请求过大')
            raw.extend(block)
        try:
            body = LoginInput.model_validate_json(raw)
            value = body.value.get_secret_value()
            if len(value.encode()) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError()
        except (ValidationError, ValueError, UnicodeError):
            raise HTTPException(422, '登录字段或格式不正确，请勿输入换行或控制字符') from None
        finally:
            raw.clear()
        async with guard:
            if body.action == 'restart':
                if app.state.engine.grant:
                    raise HTTPException(409, '请先锁定交易，再重启 OpenD 登录')
                if app.state.opend_restarting:
                    raise HTTPException(409, 'OpenD 重启尚未确认完成，请先刷新状态')
                # Serialize with broker submissions and strategy operations.
                try:
                    await asyncio.wait_for(trade_gate.acquire(), timeout=.2)
                except asyncio.TimeoutError:
                    raise HTTPException(409, '券商操作仍在进行，请稍后再试')
                try:
                    previous = await asyncio.to_thread(exchange, {'action': 'status'})
                    if previous.get('revision') != body.revision or not previous.get('retry_allowed'):
                        raise HTTPException(409, '登录状态已变化，请先刷新状态')
                    ensure_restart_safe(app, root)
                    app.state.opend_restart_generation = previous.get('process_generation', -1)
                    app.state.opend_restart_instance = previous.get('instance_id', '')
                    app.state.opend_restarting = True
                except BaseException:
                    trade_gate.release()
                    raise
                async def restart():
                    try:
                        result = await asyncio.to_thread(exchange, {'action': 'restart', 'revision': body.revision})
                        if recovered(result):
                            app.state.opend_restarting = False
                        else:
                            raise HTTPException(409, 'OpenD 重启尚未确认完成，交易入口保持暂停；请刷新连接状态')
                        return result
                    except BridgeRejected as exc:
                        if exc.not_started:
                            app.state.opend_restarting = False
                        raise
                    finally:
                        trade_gate.release()
                task = asyncio.create_task(restart())
                app.state.opend_restart_task = task
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                # A browser closing must not release the broker gate while restart is running.
                return await asyncio.shield(task)
            return await asyncio.to_thread(exchange, {'action': body.action, 'revision': body.revision, 'value': value})
