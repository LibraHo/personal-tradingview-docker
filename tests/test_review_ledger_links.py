import sqlite3
import tempfile
import unittest
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.review import install


class LedgerCitationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        @contextmanager
        def connect():
            db = sqlite3.connect(self.tmp.name + '/ledger.db')
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

        app = FastAPI()
        self.connect = connect
        install(app, connect)
        self.client = TestClient(app)
        self.base = '/api/review/'
        result = self.client.post(self.base + 'ledger/plans?market=CN', json={
            'symbol': 'SH.600519', 'request_id': 'citation-test-plan', 'period': '15m',
            'side': 'BUY', 'trigger': '站稳后介入', 'size': '目标仓位 10%', 'stop': 100, 'status': 'active',
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.ident = result.json()['id']
        self.marker = f'[[plan:{self.ident}|15 分钟计划]]'

    def save(self, market, text, revision=0):
        return self.client.put(self.base + 'days/2026-11-20?market=' + market,
                               json={'context': text, 'traded': True, 'revision': revision})

    def backlinks(self):
        return self.client.get(self.base + 'ledger/backlinks',
                               params={'market': 'CN', 'kind': 'plan', 'id': self.ident}).json()['items']

    def test_daily_weekly_backlinks_and_edits_are_atomic(self):
        self.assertEqual(self.save('CN', self.marker * 2).json()['references'],
                         [{'kind': 'plan', 'id': self.ident, 'label': '15 分钟计划'}])
        self.assertEqual(self.save('US', self.marker).status_code, 422)
        self.assertEqual(self.save('CN', '', 0).status_code, 409)
        unknown = f'[[plan:{"0" * 32}]]'
        self.assertEqual(self.save('CN', unknown, 1).status_code, 422)
        self.assertEqual(self.backlinks(), [{'kind': 'day', 'day': '2026-11-20'}])
        week = self.client.put(self.base + 'weeks/2026-11-20?market=CN', json={'summary': self.marker})
        self.assertEqual(week.status_code, 200, week.text)
        self.assertEqual(self.save('CN', '仅保留正文', 1).status_code, 200)
        self.assertEqual(self.backlinks(), [{'kind': 'week', 'day': '2026-11-16'}])
        exported = self.client.get(self.base + 'export?market=CN').json()
        self.assertEqual(exported['ledger']['plans'][0]['id'], self.ident)
        self.assertEqual(exported['weeks'][0]['summary'], self.marker)
        self.assertEqual(self.client.get('/api/v1/review/ledger/book?market=CN').status_code, 401)

    def test_merge_preserves_references_to_both_original_ids(self):
        from app.ledger import ingest_opend
        fields = {'kind':'stock', 'symbol':'US.AAPL', 'code':'US.AAPL', 'qty':2, 'price':125,
                  'side':'BUY', 'at':'2026-10-30T10:31:05-04:00'}
        account = 'OpenD:REAL:fixture'
        result = self.client.post(self.base+'ledger/fills?market=US', json={
            **fields, 'account':account, 'request_id':'manual-us-fill', 'manual_confirm':True})
        manual = result.json()['id']
        ingest_opend(self.connect, account, '2026-10-30T11:00:00-04:00', [], [{**fields,'broker_id':'fixture-deal'}])
        book = self.client.get(self.base+'ledger/book?market=US').json()
        broker = next(f['id'] for f in book['fills'] if f['source']=='opend')
        self.assertEqual(self.save('US', f'[[fill:{manual}]]').status_code, 200)
        response = self.client.put(self.base+'weeks/2026-11-20?market=US', json={'summary':f'[[fill:{broker}]]'})
        self.assertEqual(response.status_code, 200)
        merged = self.client.post(self.base+'ledger/reconcile?market=US', json={'manual_id':manual,'opend_id':broker})
        self.assertEqual(merged.status_code, 200, merged.text)
        for ident in (manual,broker):
            links = self.client.get(self.base+'ledger/backlinks', params={'market':'US','kind':'fill','id':ident})
            self.assertEqual({item['kind'] for item in links.json()['items']}, {'day','week'})

    def test_agent_uses_existing_scopes(self):
        from app.scan_api import issue_token
        with self.connect() as db:
            db.execute('CREATE TABLE scan_tokens(id TEXT PRIMARY KEY,digest TEXT UNIQUE,name TEXT,scopes TEXT,created REAL,revoked INTEGER DEFAULT 0)')
        auth = lambda scopes: {'Authorization':'Bearer '+issue_token(self.connect,'fixture',scopes)['token']}
        base = '/api/v1/review/ledger/'
        book = base+'book?market=CN'
        self.assertEqual(self.client.get(book, headers=auth(['read'])).status_code,403)
        self.assertEqual(self.client.get(book, headers=auth(['review:read'])).json()['plans'][0]['id'], self.ident)
        payload={'account':'fixture','as_of':'2026-11-20T15:00:00+08:00','complete':True,'rows':[]}
        self.assertEqual(self.client.post(base+'positions?market=CN',headers=auth(['review:read']),json=payload).status_code,403)
        self.assertEqual(self.client.post(base+'positions?market=CN',headers=auth(['review:write']),json=payload).status_code,200)
