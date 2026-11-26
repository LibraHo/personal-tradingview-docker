import sqlite3
import tempfile
import unittest
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.review import install


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/market.sqlite3'

        @contextmanager
        def connect():
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

        self.app = FastAPI()
        self.connect = connect
        install(self.app, connect)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def dashboard(self, market='CN', day='2026-11-18'):
        r = self.client.get('/api/review/dashboard', params={'market': market, 'day': day})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def save(self, day='2026-11-18', market='CN', **patch):
        return self.client.put('/api/review/days/' + day, params={'market': market}, json={
            'revision': 0, 'traded': True, 'violations': [], 'symbols': [],
            'context': '', 'reason': '', 'lesson': '', 'plan': '', **patch})

    def test_defaults_and_market_isolation(self):
        cn, us = self.dashboard(), self.dashboard('US')
        self.assertGreaterEqual(len(cn['rules']), 4)
        self.assertTrue(set(r['id'] for r in cn['rules']).isdisjoint(r['id'] for r in us['rules']))
        self.assertIsNone(cn['entry'])
        rule = cn['rules'][0]
        r = self.save(violations=[rule['id']], symbols=[{'symbol': 'SH.600519', 'name': '贵州茅台', 'note': '追高'}])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.dashboard('US')['entry'])
        self.assertEqual(self.save(market='US', violations=[rule['id']]).status_code, 422)

    def test_revisions_and_restart_persistence(self):
        r = self.save(lesson='等待确认')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['revision'], 1)
        self.assertEqual(self.save(lesson='stale').status_code, 409)
        r = self.save(revision=1, lesson='执行计划')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.dashboard()['entry']['lesson'], '执行计划')
        second = FastAPI()
        # A second client still reads the same durable database.
        from app.review import install
        install(second, self.connect)
        with TestClient(second) as client:
            self.assertEqual(client.get('/api/review/dashboard?market=CN&day=2026-11-18').json()['entry']['revision'], 2)

    def test_rule_lifecycle_preserves_snapshots_and_weekly_counts(self):
        r = self.client.post('/api/review/rules?market=CN', json={'title': '不冲动追涨'})
        self.assertEqual(r.status_code, 200, r.text)
        rule = r.json()
        self.assertEqual(self.save(violations=[rule['id'], rule['id']]).status_code, 200)
        changed = self.client.put('/api/review/rules/' + rule['id'] + '?market=CN', json={'title': '等待回踩', 'active': False, 'revision': rule['revision']})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(self.dashboard()['entry']['violations'][0]['title'], '不冲动追涨')
        self.assertEqual(len(self.dashboard()['entry']['violations']), 1)
        self.assertEqual(self.dashboard()['stats']['ranking'][0]['count'], 1)
        self.assertEqual(self.save(revision=1, violations=[rule['id']], lesson='保留历史违规').status_code, 200)
        self.assertEqual(self.save(day='2026-11-19', violations=[rule['id']]).status_code, 422)

    def test_week_boundaries_no_trade_and_previous_week(self):
        rule = self.dashboard()['rules'][0]['id']
        for day, kwargs in [('2026-11-09', {'violations': [rule]}), ('2026-11-15', {'violations': [rule]}),
                            ('2026-11-16', {'violations': [rule]}), ('2026-11-18', {'traded': False})]:
            self.assertEqual(self.save(day=day, **kwargs).status_code, 200)
        d = self.dashboard()
        self.assertEqual((d['week_start'], d['week_end']), ('2026-11-16', '2026-11-22'))
        self.assertEqual((d['stats']['reviewed_days'], d['stats']['trading_days'], d['stats']['clean_days']), (2, 1, 1))
        self.assertEqual(d['stats']['ranking'][0]['previous_count'], 2)
        self.assertEqual(self.dashboard(day='2026-11-15')['week_start'], '2026-11-09')
        self.assertEqual(len(d['history']), 4)

    def test_weekly_focus_and_validation(self):
        rule = self.dashboard()['rules'][0]['id']
        r = self.client.put('/api/review/weeks/2026-11-18?market=CN', json={
            'revision': 0, 'focus_rule_id': rule, 'action': '下单前读计划', 'summary': '减少冲动'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.dashboard()['weekly']['action'], '下单前读计划')
        self.assertEqual(self.dashboard('US')['weekly']['action'], '')
        self.assertEqual(self.dashboard(day='2026-11-23')['previous_weekly']['action'], '下单前读计划')
        self.assertEqual(self.client.put('/api/review/weeks/2026-11-16?market=CN', json={
            'revision': 0, 'focus_rule_id': rule, 'action': '', 'summary': ''}).status_code, 409)
        for market, symbol in [('CN', 'US.AAPL'), ('US', 'SH.600519'), ('CN', 'BAD')]:
            self.assertEqual(self.save(market=market, symbols=[{'symbol': symbol}]).status_code, 422)
        self.assertEqual(self.save(day='2026-02-30').status_code, 422)
        self.assertEqual(self.save(day='9999-12-31').status_code, 422)
        self.assertEqual(self.client.get('/api/review/dashboard?market=HK&day=2026-11-18').status_code, 422)
        self.assertEqual(self.client.post('/api/review/rules?market=CN', json={'title': '   '}).status_code, 422)
        export = self.client.get('/api/review/export?market=CN')
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.json()['market'], 'CN')

    def test_multiple_inline_symbols_roundtrip_without_replacing_existing_notes(self):
        diary = '[[SH.600519|贵州茅台]] 等回踩。\n\n[[SZ.000001|平安银行]] 观察。'
        saved = self.save(context=diary, lesson='[[sh.600519]] 重复提到；[[US.AAPL]] 属于另一市场。',
            symbols=[{'symbol': 'SH.600519', 'note': '原有独立备注'}])
        self.assertEqual(saved.status_code, 200, saved.text)
        entry = self.dashboard()['entry']
        self.assertEqual(entry['context'], diary)
        self.assertEqual(entry['mentioned_symbols'], [{'symbol': 'SH.600519', 'name': '贵州茅台'},
                                                        {'symbol': 'SZ.000001', 'name': '平安银行'}])
        self.assertEqual(entry['symbols'][0]['note'], '原有独立备注')
        self.assertEqual(self.dashboard()['history'][0]['symbol_count'], 2)
        self.assertEqual(self.save(revision=1, context='[[SZ.000001]] 继续观察').json()['mentioned_symbols'],
                         [{'symbol': 'SZ.000001', 'name': ''}])
        us = self.save(market='US', context='[[US.AAPL|Apple]] 和 [[US.BRK.B]]。')
        self.assertEqual([item['symbol'] for item in us.json()['mentioned_symbols']], ['US.AAPL', 'US.BRK.B'])

    def test_main_registration_and_cross_origin_guard(self):
        from unittest.mock import patch
        from app import main
        with patch.object(main, 'DB', self.path):
            client = TestClient(main.app)
            self.assertEqual(client.get('/api/review/dashboard?market=US&day=2026-11-18').status_code, 200)
            self.assertEqual(client.post('/api/review/rules?market=CN', headers={'Origin': 'https://other.test'}, json={'title': '禁止跨站写入'}).status_code, 403)
            self.assertEqual(client.post('/api/review/rules?market=CN', headers={'Sec-Fetch-Site': 'cross-site'}, json={'title': '禁止跨站写入'}).status_code, 403)

    def test_agent_sync_uses_scoped_tokens_and_preserves_unmentioned_fields(self):
        from app.scan_api import issue_token
        with self.connect() as db:
            db.execute('CREATE TABLE scan_tokens(id TEXT PRIMARY KEY, digest TEXT UNIQUE, name TEXT, scopes TEXT, created REAL, revoked INTEGER DEFAULT 0)')
        def headers(scopes):
            return {'Authorization': 'Bearer ' + issue_token(self.connect, 'test', scopes)['token']}

        api = '/api/v1/review'
        dashboard = api + '/dashboard?market=CN&day=2026-11-18'
        day = api + '/days/2026-11-18?market=CN'
        read = headers(['review:read'])
        write = headers(['review:read', 'review:write'])
        self.assertEqual(self.client.get(dashboard).status_code, 401)
        self.assertEqual(self.client.get(dashboard, headers=headers(['read', 'manage'])).status_code, 403)
        self.assertEqual(self.client.patch(day, headers=read, json={'revision': 0, 'lesson': '同步'}).status_code, 403)
        self.assertEqual(self.client.get(day, headers=read).status_code, 404)
        rule = self.client.post(api + '/rules?market=CN', headers=write, json={'title': '先写计划'}).json()
        first = self.client.patch(day, headers=write, json={'revision': 0, 'traded': False,
            'violations': [rule['id']], 'symbols': [{'symbol': 'SH.600519', 'note': '观察'}], 'lesson': '等待'} )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.dashboard()['stats']['ranking'][0]['id'], rule['id'])
        updated = self.client.patch(day, headers=write, json={'revision': 1, 'plan': '跟进'})
        self.assertEqual(updated.status_code, 200, updated.text)
        entry = self.client.get(day, headers=read).json()
        self.assertEqual((entry['revision'], entry['lesson'], entry['plan'], entry['traded']), (2, '等待', '跟进', False))
        self.assertEqual(entry['symbols'][0]['note'], '观察')
        self.assertEqual(self.client.patch(day, headers=write, json={'revision': 1, 'lesson': '覆盖'}).status_code, 409)
        self.assertEqual(self.client.patch(day, headers=write, json={'plan': '遗漏版本'}).status_code, 422)
        self.assertEqual(self.client.get(api+'/days?market=CN&limit=1', headers=read).json()['items'][0]['day'], '2026-11-18')
        self.assertEqual(self.client.put(api+'/weeks/2026-11-18?market=CN', headers=write,
            json={'revision': 0, 'focus_rule_id': rule['id'], 'action': '推迟下单'}).status_code, 200)
        self.assertEqual(self.client.get(api+'/weeks/2026-11-18?market=CN', headers=read).json()['weekly']['action'], '推迟下单')
        with self.connect() as db:
            db.execute('UPDATE scan_tokens SET revoked=1')
        self.assertEqual(self.client.get(dashboard, headers=read).status_code, 401)


if __name__ == '__main__':
    unittest.main()
