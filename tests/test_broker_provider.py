"""Offline contracts for independent execution and archive providers."""
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.broker_provider import BrokerConfig, broker_config
from app.ledger_broker import Sync, run
from app.trading import TradeEngine, TradeError


class ArchiveFixture:
    source_id = 'fixture'
    capabilities = {'archive'}

    def accounts(self):
        return [{'acc_id': 'US-demo', 'trd_env': 'REAL'}]

    def archive_positions(self, account):
        return [dict(symbol='US.AAPL', code='US.AAPL', kind='stock', qty=1)]

    def archive_fills(self, account, start, end, as_of):
        return [dict(broker_id='common', symbol='US.AAPL', code='US.AAPL', kind='stock',
                     at=as_of.isoformat(), qty=1, price=50, side='BUY')]

    def close(self):
        pass


class BrokerProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'ledger.db')
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def test_independent_configuration_and_inactive_worker(self):
        with patch.dict(os.environ, {'MARKET_DATA_PROVIDER':'', 'MARKET_DATA_ROUTES':'', 'BROKER_PROVIDER':''}):
            self.assertEqual(broker_config().source_id, 'opend')
            os.environ['MARKET_DATA_ROUTES'] = '{"US":"other"}'
            self.assertEqual(broker_config().source_id, 'disabled')
            os.environ['MARKET_DATA_PROVIDER'] = 'another:market'
            connect = Mock(side_effect=AssertionError('archive storage opened'))
            inactive = Sync(connect)
            self.assertEqual(inactive.status()['state'], 'disabled')
            with self.assertRaises(HTTPException) as error:
                inactive.queue()
            self.assertEqual(error.exception.status_code, 409)
            asyncio.run(run(connect))
            inactive.once()
            connect.assert_not_called()
            os.environ['BROKER_PROVIDER'] = 'opend'
            self.assertEqual(broker_config().source_id, 'opend')
            os.environ['BROKER_PROVIDER'] = __name__ + ':ArchiveFixture'
            config = broker_config()
            self.assertEqual(config.source_id, 'fixture')
            self.assertEqual(config.capabilities, {'archive'})
            self.assertEqual(config.trading_broker().accounts(), [])

    def test_private_accounts_fills_cursors_and_legacy_migration(self):
        with self.connect() as db:
            db.execute('CREATE TABLE ledger_opend_sync(singleton, state, message, last_success, range_start, range_end)')
            db.execute("INSERT INTO ledger_opend_sync VALUES (1,'ready','done','prior',NULL,NULL)")
            db.execute('CREATE TABLE ledger_opend_accounts(account, through, as_of)')
            db.execute("INSERT INTO ledger_opend_accounts VALUES ('OpenD:REAL:US-demo','2024-01-01','old')")
        for name in ('first', 'second'):
            sync = Sync(self.connect, config=BrokerConfig(name, frozenset({'archive'}), ArchiveFixture))
            self.assertEqual(sync.status()['accounts'], [])
            sync.once()
            row = sync.status()
            self.assertEqual(row['state'], 'ready', row)
            self.assertEqual([a['account'] for a in row['accounts']], [f'{name}:REAL:US-demo'])
        with self.connect() as db:
            fills = [json.loads(row[0]) for row in db.execute('SELECT value FROM ledger_fills')]
            self.assertEqual({f['source'] for f in fills}, {'broker:first', 'broker:second'})
            self.assertEqual([f['broker_id'] for f in fills], ['common', 'common'])
            self.assertEqual(len({f['id'] for f in fills}), 2)
        legacy = Sync(self.connect, config=BrokerConfig('opend', frozenset({'archive'}), ArchiveFixture)).status()
        self.assertEqual(legacy['last_success'], 'prior')
        self.assertEqual(legacy['accounts'][0]['through'], '2024-01-01')

    def test_trading_adapter_checks_instrument_and_buying_power_before_preview(self):
        from test_trading import FakeBroker
        broker = FakeBroker()
        broker.source_id = 'paper'
        broker.capabilities = {'trading'}
        engine = TradeEngine(self.root / 'fixture.db', broker)
        acc = next(row['acc_id'] for row in broker.accounts() if row['trd_env'] == 'SIMULATE')
        ticket = dict(acc_id=acc, env='SIMULATE', code='US.SNDK', side='BUY', order_type='NORMAL',
                      qty=1, price=100, session='RTH', time_in_force='DAY')
        with patch.object(broker, 'quote', return_value={'code':'US.WRONG','stock_type':'STOCK'}):
            with self.assertRaisesRegex(TradeError, '证券代码或类型'):
                engine.preview('owner', ticket)
        engine.quote_cache.clear()
        with patch.object(broker, 'capacity', return_value={'max_cash_buy':float('nan')}):
            with self.assertRaisesRegex(TradeError, '现金购买能力'):
                engine.preview('owner', ticket)
        self.assertFalse(broker.calls)

    def test_journals_strategies_and_management_routes_follow_selected_broker(self):
        with patch.dict(os.environ, {'TRADING_DATA_DIR':str(self.root), 'BROKER_PROVIDER':'disabled'}):
            from app.trade_api import create_app
            disabled = create_app(self.root)
            self.assertFalse(disabled.state.engine.state('owner')['real_enabled'])
            self.assertNotIn('/api/trade/opend/status', [r.path for r in disabled.routes])
            with TestClient(disabled, base_url='https://testserver') as client:
                origin = {'Origin': 'https://testserver'}
                setup = client.post('/api/trade/setup', headers=origin,
                                    json={'password':'test-platform-password',
                                          'setup_code':(self.root/'setup-code.txt').read_text()})
                headers = {**origin, 'X-CSRF-Token':setup.json()['csrf']}
                self.assertEqual(client.get('/api/trade/accounts').json()['accounts'], [])
                self.assertEqual(client.post('/api/trade/preview', headers=headers, json={}).status_code, 503)
            os.environ['BROKER_PROVIDER'] = 'opend'
            legacy = create_app(self.root)
            legacy_engine = legacy.state.engine
            self.assertIn('/api/trade/opend/status', [r.path for r in legacy.routes])
            self.assertEqual(Path(legacy_engine.path).parent, self.root)
            with legacy_engine.db() as db:
                db.execute("INSERT INTO operations VALUES ('existing','owner','PLACE','{}','SENDING',NULL,0)")
            os.environ['BROKER_PROVIDER'] = __name__ + ':ArchiveFixture'
            other = create_app(self.root)
            self.assertEqual(other.state.engine.accounts(), [])
            self.assertIsNone(other.state.engine.operation('existing'))
            self.assertNotEqual(legacy.state.strategies.path, other.state.strategies.path)
            self.assertNotEqual(legacy_engine.path, other.state.engine.path)
            with self.assertRaises(ValueError):
                TradeEngine(legacy_engine.path, config=broker_config())
            with legacy_engine.db() as db:
                self.assertEqual(db.execute("SELECT state FROM operations WHERE id='existing'").fetchone()[0], 'SENDING')
