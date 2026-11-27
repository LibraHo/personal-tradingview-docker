"""Short-lived results for chart clients behind reverse proxies."""
from concurrent.futures import ThreadPoolExecutor
import logging
import secrets
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class AnalysisJobs:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chart-analysis')
        self.lock = Lock()
        self.records = {}

    def submit(self, analyze, body):
        with self.lock:
            now = monotonic()
            self.records = {key: job for key, job in self.records.items() if job['expires'] > now}
            if sum(job['state'] == 'running' for job in self.records.values()) >= 2:
                raise HTTPException(429, '已有两个分析正在进行，请稍后再试')
            if len(self.records) >= 64:
                oldest = next(key for key, job in self.records.items() if job['state'] != 'running')
                del self.records[oldest]
            key = secrets.token_urlsafe(24)
            self.records[key] = {'state':'running', 'expires':float('inf')}
            self.executor.submit(self._run, key, analyze, body)
        return {'id':key}

    def _run(self, key, analyze, body):
        try:
            result = {'state':'done', 'result':analyze(body)}
        except HTTPException as exc:
            result = {'state':'failed', 'message':str(exc.detail)}
        except Exception:
            logging.getLogger(__name__).exception('Market analysis failed')
            result = {'state':'failed', 'message':'分析服务暂时不可用，请重试'}
        with self.lock:
            self.records[key] = {**result, 'expires':monotonic()+600}

    def result(self, key):
        with self.lock:
            job = self.records.get(key)
            if not job or job['expires'] <= monotonic():
                raise HTTPException(404, '本次分析已过期，请重新分析')
            data = {k:v for k,v in job.items() if k!='expires'}
        return JSONResponse(data, headers={'Cache-Control':'no-store'})
