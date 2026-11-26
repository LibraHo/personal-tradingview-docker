"""Durable scan jobs, versioned plans, monitoring and incremental signal events."""
import asyncio
import hashlib
import json
import time
import uuid
import os
from contextlib import contextmanager
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .scan_engine import validate_plan, evaluate
from .scan_calendar import TradingCalendar, annotate, expected_day, latest_intraday_close, close_time
from .radar import SYMBOL, BOARD
from .scan_audit import execution_plan, scope_snapshot, scope_summary, job_summary


def dump(value): return json.dumps(value, ensure_ascii=False, allow_nan=False)
def uid(): return uuid.uuid4().hex


ACTIVE_STATUSES = ('queued', 'running', 'pausing', 'cancelling')
TERMINAL_STATUSES = ('completed', 'partial', 'cancelled', 'failed', 'interrupted')
PROGRESS_FIELDS = ('phase', 'phase_started_at', 'current_symbol', 'current_period', 'done', 'matched_count', 'updated')


class JobConflict(ValueError):
    pass


def validate_schedule(schedule):
    if schedule is None:
        return None
    if not isinstance(schedule, dict) or schedule.get('kind') != 'daily':
        raise ValueError('定时配置 kind 须为 daily')
    times = schedule.get('times', [])
    if not isinstance(times, list) or not 1 <= len(times) <= 24:
        raise ValueError('每天须设置 1–24 个扫描时间')
    import re
    if any(not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value) for value in times):
        raise ValueError('扫描时间格式须为 HH:MM')
    weekdays = schedule.get('weekdays', [0, 1, 2, 3, 4])
    if not isinstance(weekdays, list) or not weekdays or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays):
        raise ValueError('weekdays 使用 0（周一）至 6（周日）')
    timezone = schedule.get('timezone', 'Asia/Shanghai')
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError('定时时区无效')
    return {'kind': 'daily', 'times': sorted(set(times)), 'weekdays': sorted(set(weekdays)), 'timezone': timezone}


def schedule_slot(schedule, now, upcoming=False):
    zone = ZoneInfo(schedule['timezone'])
    local = datetime.fromtimestamp(now, zone)
    days = range(8) if upcoming else [0]
    for offset in days:
        day = local + timedelta(days=offset)
        if day.weekday() not in schedule['weekdays']:
            continue
        slots = [day.replace(hour=int(value[:2]), minute=int(value[3:]), second=0, microsecond=0).timestamp()
                 for value in schedule['times']]
        candidates = [value for value in slots if value > now] if upcoming else [value for value in slots if value <= now]
        if candidates:
            return min(candidates) if upcoming else max(candidates)
    return None


class ScanService:
    def __init__(self, main, radar):
        self.main, self.db, self.radar = main, main.connect_db, radar
        self.calendar = TradingCalendar(radar)
        self.tasks = set()
        self.worker = None
        self.serial = asyncio.Lock()
        self.runners = {}

    def init(self):
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS scan_plans(id TEXT PRIMARY KEY, version INTEGER, payload TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS scan_jobs(id TEXT PRIMARY KEY, payload TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS scan_monitors(id TEXT PRIMARY KEY, payload TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS scan_events(cursor INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, monitor_id TEXT, symbol TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS scan_checkpoints(monitor_id TEXT, symbol TEXT, period TEXT, payload TEXT, PRIMARY KEY(monitor_id,symbol,period));
            CREATE TABLE IF NOT EXISTS scan_tokens(id TEXT PRIMARY KEY, digest TEXT UNIQUE, name TEXT, scopes TEXT, created REAL, revoked INTEGER DEFAULT 0);
            ''')
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS scan_job_history(id TEXT PRIMARY KEY, created REAL, queued REAL, status TEXT, market TEXT, plan_id TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS scan_job_pending_results(job_id TEXT, position INTEGER, payload TEXT NOT NULL,
                PRIMARY KEY(job_id,position));
            CREATE INDEX IF NOT EXISTS scan_job_history_created ON scan_job_history(created DESC,id DESC);
            CREATE INDEX IF NOT EXISTS scan_job_history_queue ON scan_job_history(status,queued,id);
            CREATE TABLE IF NOT EXISTS scan_requests(request_id TEXT PRIMARY KEY, fingerprint TEXT, job_id TEXT, created REAL);
            CREATE INDEX IF NOT EXISTS scan_jobs_status ON scan_jobs(json_extract(payload,'$.status'));
            CREATE INDEX IF NOT EXISTS scan_jobs_finished ON scan_jobs(json_extract(payload,'$.status'),json_extract(payload,'$.finished'));
            CREATE INDEX IF NOT EXISTS scan_jobs_created ON scan_jobs(json_extract(payload,'$.created') DESC);
            CREATE INDEX IF NOT EXISTS scan_jobs_history_order ON scan_jobs(coalesce(json_extract(payload,'$.created'),updated) DESC,id DESC);
            CREATE INDEX IF NOT EXISTS scan_jobs_fingerprint ON scan_jobs(json_extract(payload,'$.fingerprint'));
            """)
            active = db.execute("SELECT id FROM scan_jobs WHERE json_extract(payload,'$.status') IN ('running','pausing','cancelling')").fetchall()
            legacy = db.execute("SELECT id,json_extract(payload,'$.plan') FROM scan_jobs WHERE json_extract(payload,'$.fingerprint') IS NULL AND json_extract(payload,'$.plan') IS NOT NULL").fetchall()
        for row in active:
            job = self.get('jobs', row[0])
            if job['status'] in ('pausing', 'cancelling'):
                job.update(status='paused' if job['status']=='pausing' else 'cancelled',
                           phase='paused' if job['status']=='pausing' else 'cancelled',
                           finished=None if job['status']=='pausing' else time.time())
                self.put('jobs', job)
                continue
            job.update(status='interrupted', phase='interrupted', finished=time.time(), recoverable=True,
                       error='服务重启，任务已中断；可继续完成剩余标的')
            self.put('jobs', job)
            if job.get('monitor_id'):
                try:
                    monitor = self.get('monitors', job['monitor_id'])
                except KeyError:
                    continue
                monitor.update(last_status='interrupted', next_run=0, force_run=True)
                self.put('monitors', monitor)
        # Commit historical fingerprints together to avoid a disk sync per job at startup.
        migrations = [(self.fingerprint(json.loads(snapshot)), ident) for ident, snapshot in legacy]
        if migrations:
            with self.db() as db:
                db.executemany("UPDATE scan_jobs SET payload=json_set(payload,'$.fingerprint',?) WHERE id=?", migrations)

        # Build compact legacy history once; polling must not parse every full result payload.
        with self.db() as db:
            missing = db.execute("SELECT j.payload FROM scan_jobs j LEFT JOIN scan_job_history h ON h.id=j.id WHERE h.id IS NULL").fetchall()
            for row in missing:
                self.store_job_summary(db, json.loads(row[0]))

    @staticmethod
    def store_job_summary(db, job):
        value = job_summary(job)
        created = job.get('created', job.get('updated', time.time()))
        db.execute('INSERT OR REPLACE INTO scan_job_history VALUES(?,?,?,?,?,?,?)',
                   (job['id'], created, job.get('queued_at', created), job['status'], value['market'],
                    job.get('plan', {}).get('id'), dump(value)))

    def list(self, kind):
        with self.db() as db:
            if kind == 'jobs':
                db.execute('BEGIN')
                return [self.read_job(db, r[0]) for r in db.execute(
                    "SELECT id FROM scan_job_history ORDER BY json_extract(payload,'$.updated') DESC")]
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM scan_'+kind+' ORDER BY updated DESC')]

    @staticmethod
    def read_job(db, ident):
        row = db.execute('''SELECT j.payload,h.payload FROM scan_jobs j LEFT JOIN scan_job_history h ON h.id=j.id
                            WHERE j.id=?''', (ident,)).fetchone()
        if not row:
            raise KeyError(ident)
        job = json.loads(row[0])
        progress = json.loads(row[1]) if row[1] else {}
        job.update({key: progress[key] for key in PROGRESS_FIELDS if key in progress})
        for (payload,) in db.execute('SELECT payload FROM scan_job_pending_results WHERE job_id=? ORDER BY position', (ident,)):
            result = json.loads(payload)
            job['results'].append(result)
            if result['status'] == 'failed':
                job['failures'].append(result)
        return job

    def get(self, kind, ident):
        with self.db() as db:
            if kind == 'jobs':
                db.execute('BEGIN')
                return self.read_job(db, ident)
            row=db.execute('SELECT payload FROM scan_'+kind+' WHERE id=?',(ident,)).fetchone()
        if not row: raise KeyError(ident)
        return json.loads(row[0])

    def put(self, kind, value):
        value['updated']=time.time()
        with self.db() as db:
            if kind=='plans':
                db.execute('INSERT OR REPLACE INTO scan_plans VALUES(?,?,?,?)',(value['id'],value['version'],dump(value),value['updated']))
            else: db.execute('INSERT OR REPLACE INTO scan_'+kind+' VALUES(?,?,?)',(value['id'],dump(value),value['updated']))
            if kind=='jobs':
                # A lifecycle transition checkpoints the full job, including pending results.
                db.execute('DELETE FROM scan_job_pending_results WHERE job_id=?', (value['id'],))
                self.store_job_summary(db, value)
        return value

    def save_progress(self, job, result=None):
        job['updated'] = time.time()
        progress = {key: job[key] for key in PROGRESS_FIELDS}
        progress['failure_count'] = len(job['failures'])
        with self.db() as db:
            if result is not None:
                db.execute('INSERT INTO scan_job_pending_results VALUES(?,?,?)',
                           (job['id'], job['done'], dump(result)))
            db.execute("UPDATE scan_job_history SET payload=json_patch(payload, ?) WHERE id=? AND status='running'",
                       (dump(progress), job['id']))

    @contextmanager
    def scan_phase(self, job, phase, symbol, period):
        job.update(phase=phase, current_symbol=symbol, current_period=period, phase_started_at=time.time())
        # Publish a slow operation while it is in flight. Fast operations already
        # publish progress when the result is committed.
        timer = asyncio.get_running_loop().call_later(0.25, self.save_progress, job)
        try:
            yield
        finally:
            timer.cancel()

    def plan(self, p, ident=None):
        validate_plan(p)
        version=self.get('plans',ident)['version']+1 if ident else 1
        return self.put('plans',{**p,'id':ident or uid(),'version':version})

    def watchlists(self, market=None):
        if market is not None and market not in ("US","CN"):raise ValueError("市场须为 US 或 CN")
        requested_market=market
        with self.db() as db:
            row=db.execute("SELECT value FROM settings WHERE key='workspace'").fetchone()
            names={r[0]:r[1] for r in db.execute('SELECT symbol,name FROM symbol_names')}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='radar_cache'").fetchone():
                for cached in db.execute("SELECT payload FROM radar_cache WHERE key LIKE 'catalog:%'"):
                    for item in json.loads(cached[0]).get('rows',[]):
                        if item.get('name'):names.setdefault(item['symbol'],item['name'])
        ws=json.loads(row[0]) if row else {}
        groups=[]
        for market,v in ws.get('markets',{'US':ws}).items():
            if requested_market and market!=requested_market:continue
            for g in v.get('groups',[]):
                groups.append({**g,'id':market+':'+g['id'],'market':market})
        return {'groups':groups,'names':names}

    async def resolve(self, scope, cached_names_only=False, snapshot=None):
        market=scope.get('market')
        watch=self.watchlists(market); groups=snapshot['selected_groups'] if snapshot else watch['groups']; result={}
        def in_market(code):return not market or (code.startswith('US.') if market=='US' else code.startswith(('SH.','SZ.')))
        def add(code,group='',name=''):
            if not SYMBOL.fullmatch(code): raise ValueError('标的代码无效：'+code)
            if not in_market(code):return
            r=result.setdefault(code,{'symbol':code,'name':name or watch['names'].get(code,code),'groups':[]})
            if group and group not in r['groups']: r['groups'].append(group)
        kind=scope.get('kind','all')
        if kind in ('all','groups','favorites'):
            for g in groups:
                if kind=='groups' and g['id'] not in scope.get('groups',[]): continue
                if kind=='favorites' and not g['id'].endswith(':radar-favorites'): continue
                for code in g.get('symbols',[]): add(code,g['name'])
        elif kind=='symbols':
            for code in scope.get('symbols',[]):
                if not in_market(code):raise ValueError('所选代码不属于当前市场：'+code)
                add(code)
                for g in groups:
                    if code in g.get('symbols',[]): add(code,g['name'])
        elif kind=='members':
            for board in scope.get('symbols',[]):
                if not in_market(board):raise ValueError('所选板块不属于当前市场：'+board)
                members=await asyncio.to_thread(self.radar.members,board)
                if members.get('stale'): raise ValueError('板块成分目录过期')
                for r in members['rows']: add(r['symbol'],board,r['name'])
        else: raise ValueError('扫描范围无效')
        if not result: raise ValueError('扫描范围为空')
        if len(result)>10000: raise ValueError('扫描范围超过 10000')
        if cached_names_only:
            return list(result.values())
        bridge=getattr(self.main,'bridge',None)
        missing=[code for code,r in result.items() if r['name']==code]
        if bridge:
            for start in range(0,len(missing),100):
                names=await asyncio.to_thread(bridge.names,missing[start:start+100])
                for code,name in names.items():
                    if code in result:result[code]['name']=name
        return list(result.values())

    def launch(self,coro):
        t=asyncio.create_task(coro); self.tasks.add(t); t.add_done_callback(self.tasks.discard)
        return t

    def fingerprint(self, plan):
        scope = json.loads(dump(plan.get('scope', {'kind': 'all'})))
        for field in ('groups', 'symbols'):
            if field in scope:
                scope[field] = sorted(set(scope[field]))
        scope.pop('selection', None)
        scope_version = None
        if scope.get('kind', 'all') in ('all', 'groups', 'favorites'):
            with self.db() as db:
                row = db.execute("SELECT value FROM settings WHERE key='workspace'").fetchone()
            workspace = json.loads(row[0]) if row else {}
            markets = workspace.get('markets', {'US': workspace})
            selected = []
            for market, value in markets.items():
                if scope.get('market') and scope['market'] != market:
                    continue
                for group in value.get('groups', []):
                    ident = market + ':' + group['id']
                    if scope.get('kind') == 'groups' and ident not in scope.get('groups', []):
                        continue
                    if scope.get('kind') == 'favorites' and group['id'] != 'radar-favorites':
                        continue
                    selected.extend(group.get('symbols', []))
            scope_version = sorted(set(selected))
        rules = []
        for rule in plan['rules']:
            normalized = {key: value for key, value in rule.items() if key != 'name'}
            for key, default in [('period', None), ('offset', 0), ('temporal', 'current'),
                                 ('window', 1), ('min_count', 1), ('max_count', None)]:
                normalized.setdefault(key, default)
            for side in ('left', 'right'):
                normalized[side] = {'line': '', 'params': {}, 'value': 6, 'scale': 1, 'offset': 0, **rule[side]}
            rules.append(normalized)
        content = {'rules': rules, 'scope': scope, 'scope_version': scope_version,
                   'periods': sorted(set(plan['periods'])), 'join': plan.get('join', 'all'),
                   'lookback': plan.get('lookback', 1), 'live': plan.get('live', True)}
        return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def job_view(self, job, reused=False, reuse_reason=None, queue_positions=None):
        value = dict(self.get('jobs', job) if isinstance(job, str) else job)
        total, done = value.get('total', 0), value.get('done', 0)
        value.update(job_id=value['id'], complete=value['status'] in TERMINAL_STATUSES,
                     ready=value['status'] in ('completed', 'partial'),
                     progress_percent=round(100 * done / total, 1) if total else None,
                     elapsed_seconds=max(0, round((value.get('finished') or time.time()) - value.get('created', time.time()))),
                     failure_count=len(value['failures']) if 'failures' in value else value.get('failure_count', 0), reused=reused, reuse_reason=reuse_reason,
                     retry_after_seconds=5 if value['status'] in ACTIVE_STATUSES else None,
                     needs_action=value['status'] in ('paused', 'failed', 'interrupted'),
                     queue_position=None)
        if value['status'] == 'queued':
            if queue_positions is None:
                with self.db() as db:
                    queued = db.execute("SELECT id FROM scan_job_history WHERE status='queued' ORDER BY queued,id").fetchall()
                queue_positions = {row[0]: index + 1 for index, row in enumerate(queued)}
            value['queue_position'] = queue_positions.get(value['id'])
        return value

    def job_summaries(self, market='', plan_id='', status='', limit=100, cursor=None):
        clauses, parameters = [], []
        for key, value in [('market', market), ('plan_id', plan_id), ('status', status)]:
            if value:
                clauses.append(key+'=?')
                parameters.append(value)
        if cursor:
            try:
                stamp, ident = cursor.rsplit(':', 1)
                stamp = float(stamp)
                if not __import__('math').isfinite(stamp) or stamp < 0 or not 1 <= len(ident) <= 128:
                    raise ValueError()
            except (ValueError, AttributeError):
                raise ValueError('任务历史游标无效')
            clauses.append('(created<? OR (created=? AND id<?))')
            parameters.extend([stamp, stamp, ident])
        query = 'SELECT payload FROM scan_job_history'
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY created DESC,id DESC LIMIT ?'
        with self.db() as db:
            rows = db.execute(query, (*parameters, limit)).fetchall()
            queued = db.execute("SELECT id FROM scan_job_history WHERE status='queued' ORDER BY queued,id").fetchall()
        positions = {row[0]: index + 1 for index, row in enumerate(queued)}
        return [self.job_view(json.loads(row[0]), queue_positions=positions) for row in rows]

    def plan_results(self, plan, max_age_seconds=86400):
        fingerprint = self.fingerprint(plan)
        with self.db() as db:
            row = db.execute("SELECT id FROM scan_jobs WHERE json_extract(payload,'$.fingerprint')=? OR (json_extract(payload,'$.plan.id')=? AND json_extract(payload,'$.plan.version')=? AND json_extract(payload,'$.monitor_snapshot.follow_watchlists')=0) ORDER BY json_extract(payload,'$.created') DESC LIMIT 1", (fingerprint, plan['id'], plan.get('version'))).fetchone()
        if not row:
            return {'status': 'not_started', 'ready': False, 'fresh': False, 'job_id': None,
                    'plan_id': plan['id'], 'plan_version': plan.get('version'), 'retry_after_seconds': None}
        job = self.job_view(row[0])
        age = max(0, time.time() - job['finished']) if job.get('finished') else None
        return {**job, 'fresh': bool(job['ready'] and age is not None and age <= max_age_seconds),
                'age_seconds': round(age) if age is not None else None,
                'results': [value for value in job.get('results', []) if value.get('status') == 'matched'],
                'result_complete': job['status'] == 'completed',
                'requested_plan_id': plan['id'], 'requested_plan_version': plan.get('version')}

    def queue_job(self, ident, monitor=None):
        previous = self.runners.get(ident)
        if previous and not previous.done():
            return
        job = self.get('jobs', ident)
        task = self.launch(self.execute(job, None, job.get('monitor_snapshot') or monitor))
        self.runners[ident] = task
        def finished(completed):
            if self.runners.get(ident) is completed:
                self.runners.pop(ident, None)
        task.add_done_callback(finished)

    async def retry(self, ident, source):
        parent = self.get('jobs', ident)
        if parent['status'] not in ('failed', 'partial'):
            raise JobConflict('仅执行失败或部分完成的任务可以重试')
        return await self.submit(parent['plan'], source=source, force=True, parent=parent)

    async def submit(self, p, monitor=None, request_id=None, force=False, reuse_seconds=86400, source='api', parent=None):
        validate_plan(p)
        fingerprint = self.fingerprint(p) if not parent else 'retry:' + parent['id']
        if parent:
            request_id = 'retry:' + parent['id']
        monitor_id = monitor['id'] if monitor else None
        now = time.time()
        if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128):
            raise ValueError('request_id 长度须为 1–128')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint,job_id FROM scan_requests WHERE request_id=?', (request_id,)).fetchone() if request_id else None
            if row:
                if row[0] != fingerprint:
                    raise JobConflict('同一 request_id 已用于不同扫描参数')
                return self.job_view(row[1], True, 'request_id')
            row = db.execute("""SELECT id FROM scan_jobs WHERE json_extract(payload,'$.fingerprint')=?
                AND (json_extract(payload,'$.monitor_id') IS ? OR (? IS NULL AND json_extract(payload,'$.monitor_snapshot.follow_watchlists')=1))
                AND json_extract(payload,'$.status') IN ('queued','running','pausing','paused','cancelling')
                ORDER BY json_extract(payload,'$.created') LIMIT 1""", (fingerprint, monitor_id, monitor_id)).fetchone()
            reason = 'active_job'
            if not row and not force and not monitor and reuse_seconds > 0:
                row = db.execute("""SELECT id FROM scan_jobs WHERE json_extract(payload,'$.fingerprint')=?
                    AND json_extract(payload,'$.status') IN ('completed','partial')
                    AND (json_extract(payload,'$.monitor_id') IS NULL OR json_extract(payload,'$.monitor_snapshot.follow_watchlists')=1)
                    AND json_extract(payload,'$.finished')>=? ORDER BY json_extract(payload,'$.finished') DESC LIMIT 1""",
                    (fingerprint, now - reuse_seconds)).fetchone()
                reason = 'fresh_result'
            if row:
                ident = row[0]
                if request_id:
                    db.execute('INSERT INTO scan_requests VALUES(?,?,?,?)', (request_id, fingerprint, ident, now))
                reused = True
            else:
                ident = uid()
                workspace_row = db.execute("SELECT value FROM settings WHERE key='workspace'").fetchone()
                workspace = json.loads(workspace_row[0]) if workspace_row else {}
                snapshot = scope_snapshot(p.get('scope', {'kind':'all'}), workspace, monitor if monitor and not monitor.get('follow_watchlists', True) else None)
                job = {'id': ident, 'plan': json.loads(dump(p)), 'monitor_id': monitor_id,
                       'execution_plan': execution_plan(p), 'audit_version': 1,
                       'scope_snapshot': snapshot, 'scope_summary': scope_summary(snapshot),
                       'fingerprint': fingerprint, 'status': 'queued', 'phase': 'queued',
                       'source': 'monitor' if monitor else source, 'created': now, 'queued_at': now,
                       'monitor_snapshot': json.loads(dump(monitor)) if monitor else None,
                       'started': None, 'finished': None, 'total': 0, 'done': 0, 'results': [],
                       'failures': [], 'matched_count': 0, 'controls': [], 'updated': now}
                if parent:
                    job.update(retry_of=parent['id'], execution_plan=parent.get('execution_plan') or job['execution_plan'])
                    for key in ('scope_snapshot','scope_summary','targets'):
                        if key in parent:
                            job[key] = parent[key]
                    successful = {(r['symbol'],r['period']) for r in parent.get('results',[]) if r['status'] != 'failed'}
                    if job.get('targets'):
                        original_periods = parent.get('retry_periods', {})
                        remaining = {t['symbol']:[period for period in original_periods.get(t['symbol'],p['periods']) if (t['symbol'],period) not in successful] for t in job['targets']}
                        job['targets'] = [t for t in job['targets'] if remaining[t['symbol']]]
                        job['retry_periods'] = remaining
                db.execute('INSERT INTO scan_jobs(id,payload,updated) VALUES(?,?,?)', (ident, dump(job), now))
                self.store_job_summary(db, job)
                if request_id:
                    db.execute('INSERT INTO scan_requests VALUES(?,?,?,?)', (request_id, fingerprint, ident, now))
                reused = False
        if not reused:
            self.queue_job(ident, monitor)
        return self.job_view(ident, reused, reason if reused else None)

    async def control(self, ident, action):
        job = self.get('jobs', ident)
        state = job['status']
        now = time.time()
        if action not in ('pause', 'resume', 'cancel'):
            raise ValueError('操作须为 pause、resume 或 cancel')
        if action == 'resume':
            if state in ('queued', 'running'):
                return self.job_view(job)
            if state not in ('paused', 'interrupted', 'pausing'):
                raise JobConflict('只有暂停或中断的任务可以继续')
            if state == 'pausing':
                job['status'] = 'running'
            else:
                job.update(status='queued', phase='queued', queued_at=now, finished=None, error=None)
        elif action == 'pause':
            if state in ('paused', 'pausing'):
                return self.job_view(job)
            if state not in ('queued', 'running'):
                raise JobConflict('当前任务不能暂停')
            job['status'] = 'paused' if state == 'queued' else 'pausing'
            if job['status'] == 'paused':
                job.update(phase='paused', paused_at=now)
        else:
            if state in TERMINAL_STATUSES:
                return self.job_view(job)
            job['status'] = 'cancelling' if state in ('running', 'pausing', 'cancelling') else 'cancelled'
            if job['status'] == 'cancelled':
                job.update(phase='cancelled', finished=now)
        job.setdefault('controls', []).append({'action': action, 'time': now})
        self.put('jobs', job)
        if job['status'] == 'cancelled' and job.get('monitor_id'):
            self.finish_monitor(job)
        task = self.runners.get(ident)
        if job['status'] in ('paused', 'cancelled') and task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if action == 'resume' and job['status'] == 'queued':
            monitor = self.get('monitors', job['monitor_id']) if job.get('monitor_id') else None
            self.queue_job(ident, monitor)
        return self.job_view(ident)

    def halt_requested(self, job):
        with self.db() as db:
            state, controls = db.execute("SELECT status,json_extract(payload,'$.controls') FROM scan_job_history WHERE id=?",
                                         (job['id'],)).fetchone()
        job['controls'] = json.loads(controls) if controls else []
        if state in ('paused', 'cancelled', 'interrupted'):
            return True
        if state == 'pausing':
            job.update(status='paused', phase='paused', paused_at=time.time())
        elif state == 'cancelling':
            job.update(status='cancelled', phase='cancelled', finished=time.time())
        else:
            return False
        self.put('jobs', job)
        return True

    async def load(self, symbol, period, live=False):
        # Same endpoint, unadjusted prices, history window and regular sessions as charts.
        payload=None
        days=await asyncio.to_thread(self.calendar.days,symbol)
        tz=ZoneInfo('America/New_York' if symbol.startswith('US.') else 'Asia/Shanghai')
        stamp=time.time()
        now=datetime.fromtimestamp(stamp,tz);kind=days.get(str(now.date()))
        opened=now.replace(hour=9,minute=30,second=0,microsecond=0).timestamp()
        ended=close_time(now.timestamp(),symbol,'1d',days) if kind else 0
        outside=not kind or stamp<opened or stamp>=ended+120
        intraday = period.endswith('m') and not (not symbol.startswith('US.') and period=='240m')
        required_close=None
        cached_success=None
        if hasattr(self.main,'read_bars') and (outside or (not live and period not in ('1w','1mo'))):
            expected=expected_day(symbol,days,stamp)
            if expected:
                required_close=close_time(datetime.fromisoformat(expected).replace(tzinfo=tz).timestamp(),symbol,'1d',days)
            if not outside and intraday:
                required_close=latest_intraday_close(symbol,period,days,stamp) or required_close
            elif not outside and stamp>=ended:
                required_close=ended
        if required_close is not None:
            key=(symbol,period,'regular')
            known,success,_=await asyncio.to_thread(self.main.sync_state,key)
            needed=self.main.default_history_days(period,symbol)
            if success>=required_close and known>=needed:
                cached=await asyncio.to_thread(self.main.read_bars,key,needed,10000)
                # The tail may also contain the current, unfinished candle.
                if cached and (outside or any(
                    str(datetime.fromtimestamp(b['time'],tz).date()) in days
                    and close_time(b['time'],symbol,period,days)==required_close for b in reversed(cached[-2:])
                )):
                    payload={'bars':cached,'stale':False}
                    cached_success=success
        for attempt in range(2):
            if payload is not None:break
            try:
                payload=await self.main.bars(symbol,period,'regular',None,10000,False)
                if payload.get('stale'): raise ValueError('行情过期：'+payload.get('error',''))
                break
            except Exception:
                payload=None
                if attempt: raise
                await asyncio.sleep(3.2)
        bars=payload['bars']
        if not bars: raise ValueError('没有历史 K 线')
        if any(not all(isinstance(b.get(k),(int,float)) and __import__('math').isfinite(b[k]) for k in ('open','high','low','close','volume')) for b in bars): raise ValueError('行情包含无效数值')
        result=annotate(bars,symbol,period,days)
        # A cache obtained before the close cannot confirm a candle merely because
        # wall clock time crossed its boundary. Fetch the final OHLC first.
        completed=[b for b in result if b['confirmed']]
        if completed:
            success=cached_success
            if success is None:
                _,success,_=await asyncio.to_thread(self.main.sync_state,(symbol,period,'regular'))
            if success<completed[-1]['close_time']:
                final=await self.main.bars(symbol,period,'regular',None,10000,True)
                if final.get('stale'):raise ValueError('收盘后刷新失败，不能确认缓存 K 线')
                result=annotate(final['bars'],symbol,period,days)
        expected=expected_day(symbol,days)
        last_day=str(datetime.fromtimestamp(result[-1]['time'],tz).date())
        # Weekly/monthly bar labels may be period starts. Compare their close date.
        if period in ('1w','1mo'): last_day=str(datetime.fromtimestamp(result[-1]['close_time'],tz).date())
        if expected and last_day<expected: raise ValueError('行情未覆盖最近完成交易日 '+expected+'（停牌或缺失）')
        if intraday:
            required=latest_intraday_close(symbol,period,days,time.time()-120)
            preview = (live and kind and symbol.startswith(('SH.', 'SZ.')) and period == '120m'
                       and ((9,30) <= (now.hour,now.minute) < (11,30) or 13 <= now.hour < 15))
            start = now.replace(hour=13 if now.hour >= 13 else 9, minute=0 if now.hour >= 13 else 30,
                                second=0, microsecond=0).timestamp() if preview else None
            def missing(rows):
                return (not rows or (required and rows[-1]['close_time'] < required)
                        or (not live and required and not any(
                            b['confirmed'] and b['close_time'] >= required for b in reversed(rows)))
                        or (start and rows[-1]['time'] < start))
            if missing(result):
                refreshed = await self.main.bars(symbol,period,'regular',None,10000,True)
                if refreshed.get('stale'):
                    raise ValueError('重新读取行情失败：'+str(refreshed.get('error') or '数据源返回过期行情'))
                result = annotate(refreshed['bars'],symbol,period,days)
                if missing(result):
                    def label(stamp):
                        return datetime.fromtimestamp(stamp,tz).isoformat(timespec='minutes') if stamp else '无'
                    raise ValueError(f"重新读取后 K 线仍未覆盖扫描时间；应有已收线至 {label(required)}，"
                                     f"要求盘中起点 {label(start)}，实际最新起点 {label(result[-1]['time'] if result else None)}，"
                                     f"实际该根结束时间 {label(result[-1]['close_time'] if result else None)}")
        return result

    async def execute(self, j, targets, monitor):
        try:
            async with self.serial:
                if self.halt_requested(j):
                    return
                j = self.get('jobs', j['id'])
                j.update(status='running', started=j.get('started') or time.time(), phase='resolving_scope',
                         phase_started_at=time.time(), finished=None)
                self.put('jobs', j)
                p = j.get('execution_plan') or j['plan']
                targets = j.get('targets') or (monitor or {}).get('targets') or targets
                if targets is None:
                    targets = await self.resolve(p.get('scope', {'kind': 'all'}), cached_names_only=True, **({'snapshot':j['scope_snapshot']} if j.get('scope_snapshot', {}).get('basis')=='submission_watchlists' else {}))
                    if j['results']:
                        known = {target['symbol'] for target in targets}
                        for result in j['results']:
                            if result['symbol'] not in known:
                                targets.append({key:result[key] for key in ('symbol','name','groups') if key in result})
                                known.add(result['symbol'])
                        j['scope_recovered'] = True
                periods_by_symbol = j.get('retry_periods', {})
                j.update(targets=targets, total=sum(len(periods_by_symbol.get(t['symbol'], p['periods'])) for t in targets))
                if monitor and not monitor.get('follow_watchlists', True) and not monitor.get('targets'):
                    current_monitor = self.get('monitors', monitor['id'])
                    current_monitor['targets'] = targets
                    if j.get('scope_snapshot'):
                        current_monitor['scope_snapshot'] = j['scope_snapshot']
                    self.put('monitors', current_monitor)
                    monitor['targets'] = targets
                if self.halt_requested(j):
                    return
                self.put('jobs', j)
                completed = {(row['symbol'], row['period']) for row in j['results']}
                for target in targets:
                    symbol = target['symbol']
                    remaining = [period for period in periods_by_symbol.get(symbol,p['periods']) if (symbol, period) not in completed]
                    if not remaining:
                        continue
                    data, errors = {}, {}
                    needed = list(dict.fromkeys(remaining + [rule['period'] for rule in p['rules'] if rule.get('period')]))
                    for period in needed:
                        try:
                            with self.scan_phase(j, 'loading', symbol, period):
                                data[period] = await self.load(symbol, period, live=p.get('live', True))
                        except Exception as error:
                            errors[period] = str(getattr(error, 'detail', error))
                        if self.halt_requested(j):
                            return
                    for period in remaining:
                        row = {**target, 'period': period, 'market': 'US' if symbol.startswith('US.') else 'CN'}
                        try:
                            required = set([period] + [rule['period'] for rule in p['rules'] if rule.get('period')])
                            failures = [key + ': ' + value for key, value in errors.items() if key in required]
                            if failures:
                                raise ValueError('; '.join(failures))
                            evaluation_plan = {**p, 'lookback': 50 if monitor else p.get('lookback', 1)}
                            with self.scan_phase(j, 'evaluating', symbol, period):
                                values = await asyncio.to_thread(evaluate, data, evaluation_plan, period,
                                                                 len(data[period]) if monitor else None)
                            if self.halt_requested(j):
                                return
                            found = [value for value in values[-p.get('lookback', 1):] if value['match']]
                            value = found[-1] if found else values[-1]
                            row.update(value, status='matched' if value['match'] else 'unmatched',
                                       source='OpenD / NAS cache', data_time=data[period][-1]['time'], detected_at=time.time())
                            if monitor:
                                self.record(monitor, p, row, values)
                        except Exception as error:
                            if self.halt_requested(j):
                                return
                            row.update(status='failed', error=str(error), detected_at=time.time())
                            j['failures'].append(row)
                        j['results'].append(row)
                        j['done'] += 1
                        j['matched_count'] = j.get('matched_count', 0) + int(row['status'] == 'matched')
                        self.save_progress(j, row)
                if self.halt_requested(j):
                    return
                j.update(status='partial' if j['failures'] else 'completed', phase='finished',
                         finished=time.time(), current_symbol=None, current_period=None)
                self.put('jobs', j)
        except asyncio.CancelledError:
            current = self.get('jobs', j['id'])
            if current['status'] in ('pausing', 'cancelling'):
                self.halt_requested(current)
            elif current['status'] not in ('queued', 'paused', 'cancelled'):
                current.update(status='interrupted', phase='interrupted', finished=time.time(), recoverable=True,
                               error='服务关闭；可继续完成剩余标的')
                self.put('jobs', current)
            raise
        except Exception as error:
            current = self.get('jobs', j['id'])
            if current['status'] in ('pausing', 'cancelling'):
                self.halt_requested(current)
            else:
                current.update(status='failed', phase='failed', finished=time.time(), error=str(error))
                self.put('jobs', current)
        finally:
            if monitor:
                self.finish_monitor(self.get('jobs', j['id']))

    def finish_monitor(self, job):
        current = self.get('monitors', job['monitor_id'])
        current.update(last_job=job['id'], last_run=time.time(), last_status=job['status'],
                       last_error=job.get('error') or (str(len(job.get('failures', []))) + ' 个标的数据失败' if job.get('failures') else None))
        if job['status'] == 'completed':
            current['last_success'] = time.time()
        current['next_run'] = schedule_slot(current['schedule'], time.time(), upcoming=True) if current.get('schedule') else time.time() + current['interval_seconds']
        self.put('monitors', current)

    def record(self,m,p,row,values):
        """Checkpoint and unique event insertion commit together; retries are idempotent."""
        with self.db() as db:
            old=db.execute('SELECT payload FROM scan_checkpoints WHERE monitor_id=? AND symbol=? AND period=?',(m['id'],row['symbol'],row['period'])).fetchone()
            state=json.loads(old[0]) if old else {'time':0,'matched':False,'confirmed':False}
            if state.get('plan_id', p['id']) != p['id'] or state.get('plan_version', p['version']) != p['version']:
                old=None
                state={'time':0,'matched':False,'confirmed':False}
            if old and values[0]['time']>state['time'] and state['time']:
                # Expose bounded recovery rather than silently claiming full backfill.
                raise ValueError('恢复检查点早于当前可用历史窗口；存在信号缺口，需要补充历史数据后重试')
            if not old and m.get('backfill'):values=values[-50:]
            for v in values:
                if not v['valid'] or v['time']<state['time']: continue
                if v['time']==state['time'] and state.get('confirmed'): continue
                after_activation=v['close_time']>=m['activated_at']
                eligible=m.get('backfill',False) or after_activation
                new_match=v['match'] and (not state['matched'] or (m.get('event_mode')=='each_bar' and v['time']>state['time']) or (v['time']==state['time'] and v['confirmed'] and not state.get('confirmed')))
                if eligible and new_match:
                    identity=f"{m['id']}:{p['id']}:{p['version']}:{row['symbol']}:{row['period']}:{v['time']}:{v['confirmed']}"
                    eid=hashlib.sha256(identity.encode()).hexdigest()
                    public=urlsplit(os.getenv('TRADING_URL','https://192.168.101.103:8443'))
                    event={**row,**v,'event_id':eid,'monitor_id':m['id'],'plan_id':p['id'],'plan_version':p['version'],
                        'conditions':p['rules'],'detected_at':time.time(),'confirmation':'confirmed' if v['confirmed'] else 'preview',
                        'delivery_kind':'delayed' if time.time()-v['close_time']>max(m['interval_seconds']*2,180) else 'realtime',
                        'chart_url':public.scheme+'://'+public.netloc+'/chart?symbol='+row['symbol']+'&period='+row['period']}
                    db.execute('INSERT OR IGNORE INTO scan_events(event_id,monitor_id,symbol,payload) VALUES(?,?,?,?)',(eid,m['id'],row['symbol'],dump(event)))
                state={'time':v['time'],'matched':v['match'],'confirmed':v['confirmed'],'plan_id':p['id'],'plan_version':p['version']}
            db.execute('INSERT OR REPLACE INTO scan_checkpoints VALUES(?,?,?,?)',(m['id'],row['symbol'],row['period'],dump(state)))

    async def create_monitor(self, body):
        p=self.get('plans',body['plan_id'])
        interval=body.get('interval_seconds',120)
        schedule=validate_schedule(body.get('schedule'))
        if type(interval) is not int or not 30<=interval<=86400: raise ValueError('扫描间隔须为 30–86400 秒')
        if body.get('event_mode','on_enter') not in ('on_enter','each_bar'):raise ValueError('事件模式无效')
        m={'event_mode':body.get('event_mode','on_enter'),'id':uid(),'plan_id':p['id'],'plan_version':p['version'],'plan':p,'name':body.get('name',p.get('name','监控')),
            'interval_seconds':interval,'follow_watchlists':body.get('follow_watchlists',True),'backfill':body.get('backfill',False),
            'schedule':schedule,'trading_only':body.get('trading_only',True),'enabled':body.get('enabled',True),'activated_at':time.time(),'next_run':0}
        # Frozen scopes are captured by the first background task, so configuration stays fast.
        return self.put('monitors',m)

    def update_monitor(self, ident, body, changed):
        monitor = self.get('monitors', ident)
        snapshot = monitor['plan']
        if 'plan_id' in changed:
            snapshot = self.get('plans', body['plan_id'])
        body['schedule'] = validate_schedule(body.get('schedule'))
        reset_targets = 'plan_id' in changed or monitor.get('follow_watchlists', True) != body['follow_watchlists']
        monitor.update(body)
        monitor.update(plan=snapshot, plan_id=snapshot['id'], plan_version=snapshot['version'])
        if reset_targets:
            monitor.pop('targets', None)
            monitor.pop('scope_snapshot', None)
        if 'plan_id' in changed:
            monitor['activated_at'] = time.time()
            with self.db() as db:
                db.execute('DELETE FROM scan_checkpoints WHERE monitor_id=?', (ident,))
        if changed & {'schedule', 'interval_seconds', 'plan_id', 'trading_only'}:
            monitor['next_run'] = 0
            monitor.pop('last_schedule_slot', None)
        return self.put('monitors', monitor)

    async def monitor_due(self, monitor, now):
        if monitor.get('force_run'):
            return True, None
        schedule = monitor.get('schedule')
        slot = schedule_slot(schedule, now) if schedule else None
        if schedule and (slot is None or slot <= monitor.get('last_schedule_slot', 0)):
            return False, None
        if not monitor.get('trading_only', True):
            return True, slot
        scope = monitor['plan'].get('scope', {})
        markets = [scope['market']] if scope.get('market') else ['CN', 'US']
        for market in markets:
            symbol = 'US.SPY' if market == 'US' else 'SH.600000'
            days = await asyncio.to_thread(self.calendar.days, symbol)
            local = datetime.fromtimestamp(slot if slot is not None else now,
                                           ZoneInfo('America/New_York' if market == 'US' else 'Asia/Shanghai'))
            kind = days.get(str(local.date()))
            if schedule:
                if kind:
                    return True, slot
                continue
            minute = local.hour * 60 + local.minute
            end = (780 if kind == 'MORNING' else 960) if market == 'US' else 900
            if kind and 570 <= minute <= end + 10 and (market == 'US' or not 700 <= minute < 780):
                return True, None
        recovery = not monitor.get('last_run') or now - monitor['last_run'] >= 86400 or monitor.get('last_status') == 'interrupted'
        return (recovery and not schedule), slot

    async def schedule(self):
        while True:
            try:
                with self.db() as db:
                    active = {row[0] for row in db.execute("SELECT json_extract(payload,'$.monitor_id') FROM scan_jobs WHERE json_extract(payload,'$.status') IN ('running','queued','pausing','paused','cancelling')")}
                for monitor in self.list('monitors'):
                    now = time.time()
                    if not monitor['enabled'] or monitor['id'] in active or monitor.get('next_run', 0) > now:
                        continue
                    try:
                        due, slot = await self.monitor_due(monitor, now)
                        if not due:
                            continue
                        job = await self.submit(monitor['plan'], monitor)
                        monitor.update(force_run=False, last_job=job['id'])
                        if slot is not None:
                            monitor['last_schedule_slot'] = slot
                        self.put('monitors', monitor)
                    except Exception as error:
                        monitor.update(last_error=str(error), last_status='failed',
                                       next_run=time.time() + monitor['interval_seconds'])
                        self.put('monitors', monitor)
            except asyncio.CancelledError:
                raise
            except Exception:
                __import__('logging').exception('Scanner scheduler failed')
            await asyncio.sleep(5)

    async def start(self):
        self.init()
        with self.db() as db:
            recovery = db.execute("SELECT payload FROM scan_jobs WHERE json_extract(payload,'$.status')='interrupted' AND updated>=?", (time.time()-600,)).fetchall()
        for row in recovery:
            job = json.loads(row[0])
            if not job.get('recoverable') and not str(job.get('error', '')).startswith(('服务关闭', '服务重启')):
                continue
            job.update(status='queued', phase='queued', finished=None, error=None)
            job.setdefault('controls', []).append({'action':'resume','time':time.time(),'reason':'service_restart'})
            self.put('jobs', job)
            if job.get('monitor_id'):
                monitor = self.get('monitors', job['monitor_id'])
                monitor['force_run'] = False
                self.put('monitors', monitor)
        with self.db() as db:
            queued = db.execute("SELECT id,json_extract(payload,'$.monitor_id') FROM scan_jobs WHERE json_extract(payload,'$.status')='queued' ORDER BY coalesce(json_extract(payload,'$.queued_at'),json_extract(payload,'$.created')),id").fetchall()
        for ident, monitor_id in queued:
            monitor = self.get('monitors', monitor_id) if monitor_id else None
            self.queue_job(ident, monitor)
        self.worker = asyncio.create_task(self.schedule())

    async def stop(self):
        if self.worker:self.worker.cancel()
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*self.tasks,*([self.worker] if self.worker else []),return_exceptions=True)
