import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.ledger_opend import ET, Sync, fill, install, position, service
from app.trading import BrokerRejected


class Broker:
    def __init__(self):
        self.calls = []
        self.today_calls = []
        self.today_deals = []
        self.deals = []
        self.holdings = []
        self.fail_next = False
        self.closed = 0

    def accounts(self):
        return [{'acc_id': '1234567890123456789', 'trd_env': 'REAL'},
                {'acc_id': '2', 'trd_env': 'SIMULATE'}]

    def positions(self, acc, env):
        assert acc == '1234567890123456789' and env == 'REAL'
        return self.holdings

    def ensure(self):
        return self

    def history_deal_list_query(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_next:
            self.fail_next = False
            raise BrokerRejected('fixture')
        return self.deals

    def unpack(self, result):
        return result

    def deal_list_query(self, **kwargs):
        self.today_calls.append(kwargs)
        return self.today_deals

    def close(self):
        self.closed += 1


class OpenDLedgerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name, 'ledger.db')

        @contextmanager
        def connect():
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

        self.connect = connect
        self.broker = Broker()
        self.sync = Sync(connect, lambda: self.broker)
        self.raw = dict(deal_id='9007199254740993', status='OK', code='US.BRK.B261218C500500',
                        create_time='2026-07-02 09:31:01.321', qty=2, price=3.41, trd_side='SELL_SHORT')

    def test_variable_precision_broker_timestamp(self):
        for fraction, micros in [('1',100000), ('42',420000), ('0321',32100), ('123456',123456)]:
            deal = fill({**self.raw, 'create_time':'2026-07-02 09:31:01.' + fraction})
            self.assertEqual(datetime.fromisoformat(deal['at']).microsecond, micros)

    def test_status_remains_readable_during_a_write(self):
        self.assertEqual(self.sync.status()['state'], 'idle')
        with self.connect() as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('BEGIN IMMEDIATE')
            self.assertEqual(self.sync.status()['state'], 'idle')

    def test_readonly_roundtrip_ids_corrections_positions_and_replay(self):
        self.broker.deals = [self.raw]
        self.broker.holdings = [dict(code=self.raw['code'], position_side='SHORT', qty=2,
                                     cost_price_valid=True, cost_price=4.2, average_cost=3.41)]
        self.sync.once()
        self.sync.once()
        self.assertEqual(self.sync.status()['state'], 'ready')
        self.assertEqual(self.broker.closed, 2)
        self.assertEqual(len(self.broker.calls), 2)
        self.assertEqual(self.broker.calls[0]['acc_id'], 1234567890123456789)
        self.assertEqual(self.broker.calls[0]['deal_market'], 'US')
        with self.connect() as db:
            rows = list(db.execute('SELECT value FROM ledger_fills'))
            self.assertEqual(len(rows), 1)
            saved = json.loads(rows[0][0])
            self.assertEqual((saved['side'], saved['broker_id'], saved['symbol'], saved['strike'], saved['kind']),
                             ('SELL_SHORT', self.raw['deal_id'], 'US.BRK.B', 500.5, 'option'))
            self.assertEqual(saved['at'], '2026-07-02T13:31:01.321000+00:00')
            self.assertEqual(saved['account'], 'OpenD:REAL:1234567890123456789')
            holding = json.loads(db.execute('SELECT value FROM ledger_positions').fetchone()[0])
            self.assertEqual((holding['qty'], holding['cost']), (-2, 3.41))
        self.broker.deals = [{**self.raw, 'status': 'CHANGED', 'qty': 1}]
        self.sync.once()
        self.broker.deals = [{'deal_id': self.raw['deal_id'], 'status': 'CANCELLED'}]
        self.broker.holdings = []
        self.sync.once()
        self.broker.deals = [self.raw]
        self.sync.once()
        with self.connect() as db:
            final = json.loads(db.execute('SELECT value FROM ledger_fills').fetchone()[0])
            self.assertEqual((final['id'], final['qty'], final['broker_status']), (saved['id'], 1, 'CANCELLED'))
            self.assertEqual(db.execute('SELECT count(*) FROM ledger_positions').fetchone()[0], 0)

    def test_failure_preserves_cursor_snapshot_and_retries_gap_on_restart(self):
        self.sync.once()
        with self.connect() as db:
            old = (datetime.now(ET).date() - timedelta(days=102)).isoformat()
            db.execute('UPDATE ledger_opend_accounts SET through=?', (old,))
        self.broker.fail_next = True
        self.sync.once()
        status = self.sync.status()
        self.assertEqual((status['state'], status['accounts'][0]['through']), ('error', old))
        self.assertNotIn('fixture', status['message'])
        restarted = Sync(self.connect, lambda: self.broker)
        with patch('app.ledger_opend.REQUEST_GAP', 0):
            restarted.once()
        self.assertEqual(restarted.status()['state'], 'ready')
        first, second = self.broker.calls[-2:]
        self.assertEqual(date.fromisoformat(first['start'][:10]), date.fromisoformat(old)-timedelta(days=2))
        self.assertEqual(second['start'], first['end'])

    def test_explicit_backfill_is_durable_and_leaves_automatic_cursor(self):
        self.sync.once()
        before = self.sync.status()['accounts'][0]['through']
        self.sync.queue(date(2025, 6, 1), date(2025, 6, 2))
        Sync(self.connect, lambda: self.broker).once()
        self.assertEqual(self.broker.calls[-1]['start'], '2025-06-01 00:00:00')
        self.assertEqual(self.broker.calls[-1]['end'], '2025-06-03 00:00:00')
        self.assertEqual(self.sync.status()['accounts'][0]['through'], before)

    def test_only_explicit_complete_data_advances_cursor(self):
        self.broker.deals = [dict(self.raw, status='UNEXPECTED')]
        self.sync.once()
        self.assertEqual(self.sync.status()['state'], 'error')
        self.assertEqual(self.sync.status()['accounts'], [])
        self.assertTrue(self.broker.closed)
        with self.assertRaisesRegex(Exception, '精度'):
            fill(dict(self.raw, deal_id=1.0))
        self.assertNotIn('cost', position(dict(code='US.MU', qty=5, cost_price=0, cost_price_valid=False)))

    def test_today_and_history_can_overlap_or_report_intraday_only_fills(self):
        self.broker.deals = [self.raw]
        extra = dict(self.raw, deal_id='9007199254740994')
        self.broker.today_deals = [self.raw, extra, dict(extra, status='CHANGED', price=2.01)]
        self.sync.once()
        self.assertEqual(self.broker.today_calls[0], dict(acc_id=1234567890123456789, trd_env='REAL',
                                                         deal_market='US', refresh_cache=True))
        with self.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT value FROM ledger_fills ORDER BY broker_id')]
            self.assertEqual(len(rows), 2)
            self.assertEqual((rows[1]['price'], rows[1]['broker_status']), (2.01, 'CHANGED'))

    def test_bad_account_does_not_prevent_other_real_account_from_saving(self):
        ordinary_positions = self.broker.positions
        def positions(acc, env):
            if acc == '99':
                raise BrokerRejected('unavailable')
            return ordinary_positions(acc, env)
        self.broker.positions = positions
        real = self.broker.accounts()[0]
        self.broker.accounts = lambda: [{'acc_id': '99', 'trd_env': 'REAL'}, real]
        self.broker.today_deals = [self.raw]
        self.sync.once()
        status = self.sync.status()
        self.assertEqual(status['state'], 'error')
        self.assertIn('99', status['message'])
        self.assertEqual([row['account'] for row in status['accounts']], ['OpenD:REAL:'+real['acc_id']])

    def test_shutdown_during_backfill_finishes_one_atomic_chunk_then_resumes(self):
        self.sync.once()
        with self.connect() as db:
            old = (datetime.now(ET).date()-timedelta(days=120)).isoformat()
            db.execute('UPDATE ledger_opend_accounts SET through=?', (old,))
        stop = threading.Event()
        history = self.broker.history_deal_list_query
        def interrupted(**kwargs):
            stop.set()
            return history(**kwargs)
        self.broker.history_deal_list_query = interrupted
        self.broker.deals = [self.raw]
        self.sync.once(stop)
        status = self.sync.status()
        self.assertEqual(status['state'], 'queued')
        self.assertGreater(status['accounts'][0]['through'], old)
        self.assertLess(status['accounts'][0]['through'], datetime.now(ET).date().isoformat())
        self.broker.history_deal_list_query = history
        Sync(self.connect, lambda: self.broker).once()
        self.assertEqual(self.sync.status()['state'], 'ready')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ledger_fills').fetchone()[0], 1)

    def test_queue_endpoints_validate_bounds_and_coalesce(self):
        app = FastAPI()
        agent = APIRouter(prefix='/api/v1/review')
        install(app, agent, self.connect)
        app.include_router(agent)
        client = TestClient(app)
        api = '/api/v1/review/ledger/opend'
        self.assertEqual(client.get(api).json()['state'], 'idle')
        self.assertEqual(client.post(api+'/sync?market=CN').status_code, 422)
        self.assertEqual(client.post(api+'/sync?start=2025-11-01').status_code, 422)
        self.assertEqual(client.post(api+'/sync?start=2024-01-01&end=2025-01-01').status_code, 422)
        request = '?start=2025-11-01&end=2025-11-01'
        self.assertEqual(client.post(api+'/sync'+request).json()['state'], 'queued')
        self.assertEqual(client.post('/api/review/ledger/opend/sync'+request).status_code, 200)
        self.assertEqual(client.post(api+'/sync?start=2025-11-02&end=2025-11-02').status_code, 409)
        self.assertEqual(service(self.connect).status()['state'], 'queued')
