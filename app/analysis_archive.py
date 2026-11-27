"""Durable chart reports scoped to the requesting browser's archive key."""
import hashlib
import json
from datetime import datetime, timezone


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class ReportArchive:
    def __init__(self, connect_db):
        self.connect_db = connect_db

    @staticmethod
    def prepare(db):
        db.execute('''CREATE TABLE IF NOT EXISTS chart_reports (
            seq INTEGER PRIMARY KEY, owner TEXT NOT NULL, job_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL, period TEXT NOT NULL, mode TEXT NOT NULL,
            started TEXT NOT NULL, completed TEXT NOT NULL, report TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS chart_reports_owner ON chart_reports(owner, seq DESC)')

    @staticmethod
    def owner(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def save(self, token, job_id, chart, started, report):
        completed = timestamp()
        result = {**report, 'started': started, 'completed': completed}
        with self.connect_db() as db:
            self.prepare(db)
            db.execute('''INSERT INTO chart_reports(owner, job_id, symbol, period, mode, started, completed, report)
                          VALUES(?,?,?,?,?,?,?,?)''', (self.owner(token), job_id, chart.symbol, chart.period,
                          chart.mode, started, completed, json.dumps(result, ensure_ascii=False)))
        return result

    def page(self, token, before):
        with self.connect_db() as db:
            self.prepare(db)
            rows = db.execute('''SELECT seq,job_id AS id,symbol,period,mode,started,completed FROM chart_reports
                WHERE owner=? AND seq<? ORDER BY seq DESC LIMIT 31''', (self.owner(token), before)).fetchall()
        return {'reports':[dict(r) for r in rows[:30]], 'next':rows[29]['seq'] if len(rows)>30 else None}

    def get(self, token, job_id):
        with self.connect_db() as db:
            self.prepare(db)
            row = db.execute('SELECT report FROM chart_reports WHERE owner=? AND job_id=?',
                             (self.owner(token), job_id)).fetchone()
        return json.loads(row[0]) if row else None
