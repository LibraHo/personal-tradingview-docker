import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from app.opend_login_api import register_opend_login, ensure_restart_safe, BridgeRejected


class RestartGuards(unittest.TestCase):
    def test_each_outstanding_activity_blocks_restart(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            app=SimpleNamespace(state=SimpleNamespace(engine=SimpleNamespace(grant=None)))
            with closing(sqlite3.connect(root/'trading.sqlite3')) as db, db:
                db.executescript('CREATE TABLE operations(state TEXT); CREATE TABLE protection(data TEXT);')
            with closing(sqlite3.connect(root/'strategies.sqlite3')) as db, db:db.execute('CREATE TABLE strategies(enabled INTEGER)')
            ensure_restart_safe(app,root)
            cases=[('trading.sqlite3','operations',"INSERT INTO operations VALUES ('SENDING')"),
                   ('trading.sqlite3','operations',"INSERT INTO operations VALUES ('UNKNOWN')"),
                   ('trading.sqlite3','protection',"INSERT INTO protection VALUES ('{\"state\":\"WAITING\"}')"),
                   ('strategies.sqlite3','strategies','INSERT INTO strategies VALUES (1)')]
            for filename,table,sql in cases:
                with closing(sqlite3.connect(root/filename)) as db, db:db.execute(sql)
                with self.assertRaises(HTTPException) as caught:ensure_restart_safe(app,root)
                self.assertEqual(caught.exception.status_code,409)
                with closing(sqlite3.connect(root/filename)) as db, db:db.execute('DELETE FROM '+table)


class RestartLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app=FastAPI();self.app.state.engine=SimpleNamespace(grant=None)
        self.gate=asyncio.Semaphore(1)
        register_opend_login(self.app,Path('/unused'),self.gate)
        self.submit=next(r.endpoint for r in self.app.routes if r.path=='/api/trade/opend/input')
        self.status=next(r.endpoint for r in self.app.routes if r.path=='/api/trade/opend/status')
        self.before={'stage':'error','revision':'a'*32,'process_generation':3,'instance_id':'old','retry_allowed':True}
        self.after={**self.before,'stage':'account','process_generation':4,'revision':'b'*32}

    def request(self):
        class Request:
            async def stream(self):yield json.dumps({'action':'restart','revision':'a'*32}).encode()
        return Request()

    async def test_cancelled_browser_does_not_release_gate(self):
        started=threading.Event();finish=threading.Event()
        def exchange(body):
            if body['action']=='status':return self.before
            started.set();finish.wait(3);return self.after
        with patch('app.opend_login_api.exchange',side_effect=exchange),patch('app.opend_login_api.ensure_restart_safe'):
            request=asyncio.create_task(self.submit(self.request()))
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            self.assertTrue(self.gate.locked());self.assertTrue(self.app.state.opend_restarting)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):await request
            self.assertTrue(self.gate.locked());self.assertTrue(self.app.state.opend_restarting)
            finish.set();await self.app.state.opend_restart_task
            self.assertFalse(self.gate.locked());self.assertFalse(self.app.state.opend_restarting)

    async def test_explicit_not_started_releases_flag(self):
        def exchange(body):
            if body['action']=='status':return self.before
            raise BridgeRejected('状态已变化',not_started=True)
        with patch('app.opend_login_api.exchange',side_effect=exchange),patch('app.opend_login_api.ensure_restart_safe'):
            with self.assertRaises(HTTPException):await self.submit(self.request())
        self.assertFalse(self.gate.locked());self.assertFalse(self.app.state.opend_restarting)

    async def test_uncertain_restart_stays_blocked_until_new_instance(self):
        def exchange(body):
            if body['action']=='status':return self.before
            raise HTTPException(503,'连接中断')
        with patch('app.opend_login_api.exchange',side_effect=exchange),patch('app.opend_login_api.ensure_restart_safe'):
            with self.assertRaises(HTTPException):await self.submit(self.request())
        self.assertFalse(self.gate.locked());self.assertTrue(self.app.state.opend_restarting)
        with patch('app.opend_login_api.exchange',return_value=self.before):await self.status()
        self.assertTrue(self.app.state.opend_restarting)
        with patch('app.opend_login_api.exchange',return_value={**self.after,'instance_id':'new','process_generation':1}):await self.status()
        self.assertFalse(self.app.state.opend_restarting)

    async def test_early_starting_ack_does_not_unblock(self):
        with patch('app.opend_login_api.exchange',side_effect=[self.before,{**self.after,'stage':'starting'}]),patch('app.opend_login_api.ensure_restart_safe'):
            with self.assertRaises(HTTPException):await self.submit(self.request())
        self.assertTrue(self.app.state.opend_restarting)

    async def test_busy_trade_gate_rejects_without_calling_bridge(self):
        await self.gate.acquire()
        with patch('app.opend_login_api.exchange') as bridge:
            with self.assertRaises(HTTPException):await self.submit(self.request())
            bridge.assert_not_called()
        self.gate.release()
