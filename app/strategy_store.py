"""Small durable monitor registry. Trading arms deliberately live only in RAM."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .strategy_rules import validate_strategy


class StrategyStore:
    def __init__(self,path):
        self.path=str(path);self.arms={}
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY,config TEXT,enabled INTEGER,last_bar INTEGER,status TEXT,revision INTEGER,updated REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS strategy_events(id INTEGER PRIMARY KEY AUTOINCREMENT,strategy_id TEXT,created REAL,kind TEXT,message TEXT,detail TEXT)')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def revoke(self,sid):
        arm=self.arms.pop(sid,None)
        if arm:arm["cancelled"]=True

    def disarm_all(self):
        for sid in list(self.arms):self.disarm(sid)

    def get(self,sid):
        with self.db() as db:r=db.execute('SELECT * FROM strategies WHERE id=?',(sid,)).fetchone()
        if not r:raise ValueError('策略不存在')
        arm=self.arms.get(sid)
        if arm and arm['expires']<=time.time():self.revoke(sid);arm=None
        return {**dict(r),'enabled':bool(r['enabled']),'config':json.loads(r['config']),
                'arm':{k:v for k,v in arm.items() if k!='owner'} if arm else None}

    def list(self):
        with self.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM strategies ORDER BY updated DESC')]
        return [self.get(sid) for sid in ids]

    def save(self,raw):
        cfg=validate_strategy(raw)
        sid=raw.get('id')
        if sid:self.get(sid)
        else:
            if len(self.list())>=16:raise ValueError('最多保存 16 个策略')
            sid=uuid.uuid4().hex
        self.revoke(sid)
        with self.db() as db:
            db.execute('INSERT INTO strategies VALUES(?,?,0,0,?,1,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config,enabled=0,last_bar=0,status=excluded.status,revision=revision+1,updated=excluded.updated',
                       (sid,json.dumps(cfg,ensure_ascii=False),'已保存 · 未监控',time.time()))
        return self.get(sid)

    def start(self,sid,enabled,baseline=None):
        self.get(sid);self.revoke(sid)
        if enabled and sum(x['enabled'] for x in self.list() if x['id']!=sid)>=8:raise ValueError('最多同时运行 8 个监控')
        with self.db() as db:
            db.execute('UPDATE strategies SET enabled=?,last_bar=?,status=?,revision=revision+1,updated=? WHERE id=?',
                       (int(enabled),baseline['bar_time'] if enabled and baseline else 0,'监控中 · 仅记录信号' if enabled else '已暂停',time.time(),sid))
        return self.get(sid)

    def delete(self,sid):
        self.get(sid);self.revoke(sid)
        with self.db() as db:
            db.execute('DELETE FROM strategies WHERE id=?',(sid,));db.execute('DELETE FROM strategy_events WHERE strategy_id=?',(sid,))

    def event(self,sid,kind,message,detail=None):
        with self.db() as db:
            db.execute('INSERT INTO strategy_events(strategy_id,created,kind,message,detail) VALUES(?,?,?,?,?)',
                       (sid,time.time(),kind,message,json.dumps(detail or {},ensure_ascii=False)))
            db.execute('DELETE FROM strategy_events WHERE id NOT IN (SELECT id FROM strategy_events ORDER BY id DESC LIMIT 1000)')
            db.execute('UPDATE strategies SET status=? WHERE id=?',(message,sid))

    def events(self,sid):
        self.get(sid)
        with self.db() as db:rows=db.execute('SELECT * FROM strategy_events WHERE strategy_id=? ORDER BY id DESC LIMIT 50',(sid,)).fetchall()
        return [{**dict(r),'detail':json.loads(r['detail'])} for r in rows]

    def claim(self,sid,bar_time,missed=False,revision=None):
        with self.db() as db:
            sql='UPDATE strategies SET last_bar=? WHERE id=? AND enabled=1 AND last_bar<?'
            args=[bar_time,sid,bar_time]
            if revision is not None:sql+=' AND revision=?';args.append(revision)
            changed=db.execute(sql,args).rowcount
        if changed and missed:self.event(sid,'SKIPPED','已跳过断线期间的历史信号，不补单',{'bar_time':bar_time})
        return bool(changed)

    def arm(self,sid,owner,acc,env,expires):
        if not self.get(sid)['enabled']:raise ValueError('请先启动监控')
        self.arms[sid]={'owner':owner,'acc_id':acc,'env':env,'expires':expires,'executions':0}
        self.event(sid,'ARMED','已启用限时自动执行；关闭网页仍继续，至授权到期')

    def disarm(self,sid):
        self.get(sid);self.revoke(sid);self.event(sid,'DISARMED','自动执行已关闭，继续仅监控')
