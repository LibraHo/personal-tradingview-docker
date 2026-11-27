import time
import unittest
from threading import Event
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.analysis_jobs import AnalysisJobs
from app.market_analysis import install
from app.api_management import token_db
from app import main as chart_app


class AnalysisJobTests(unittest.TestCase):
    def test_capacity_errors_and_result_expiry(self):
        jobs = AnalysisJobs()
        release = Event()
        def work(value):
            release.wait(2)
            return value
        try:
            ids = [jobs.submit(work, i)['id'] for i in range(2)]
            self.assertNotEqual(*ids)
            self.assertIn(b'running', jobs.result(ids[0]).body)
            with self.assertRaises(HTTPException) as full:
                jobs.submit(work, 3)
            self.assertEqual(full.exception.status_code, 429)
            release.set()
            jobs.executor.shutdown(wait=True)
            self.assertIn(b'"result":0', jobs.result(ids[0]).body)
            with patch('app.analysis_jobs.monotonic', return_value=time.monotonic()+601):
                with self.assertRaises(HTTPException) as gone:
                    jobs.result(ids[0])
                self.assertEqual(gone.exception.status_code,404)
        finally:
            release.set()
            jobs.executor.shutdown(wait=True)

    def test_public_api_honors_chart_access_and_proxy_origin(self):
        client = TestClient(chart_app.app)
        path = '/api/market-analysis/jobs'
        with patch.dict('os.environ', {'TRUSTED_USER_HEADER':'x-test-user'}):
            self.assertEqual(client.get('/api/market-analysis?symbol=US.AAPL&period=1d').status_code,401)
            blocked = client.post(path,json={},headers={'origin':'https://elsewhere.example','sec-fetch-site':'cross-site','x-test-user':'viewer'})
            self.assertEqual(blocked.status_code,403)
            response = client.post(path,json={},headers={'origin':'https://remote.example','sec-fetch-site':'same-origin','x-test-user':'viewer'})
            self.assertEqual(response.status_code,422)
            page=client.get('/chart',headers={'x-test-user':'viewer'})
            self.assertIn('data-market-entry="public"',page.text)
        # The ordinary market port exposes only the bounded analysis operation.
        urls=chart_app.app.openapi()['paths']
        self.assertIn(path, urls)
        self.assertNotIn('/api/trade/agent-settings',urls)
        self.assertNotIn('post',urls['/api/market-analysis'])

    def test_job_failure_reaches_same_origin_client(self):
        app = FastAPI()
        install(app,token_db,path='/api/market-analysis',synchronous=False)
        client = TestClient(app)
        with patch('app.market_analysis.transaction',side_effect=HTTPException(503,'供应商不可用')):
            response=client.post('/api/market-analysis/jobs',json={'symbol':'US.AAPL','period':'1m'})
            self.assertEqual(response.status_code,202)
            path='/api/market-analysis/jobs/'+response.json()['id']
            for _ in range(100):
                result=client.get(path)
                if result.json()['state']!='running':
                    break
                time.sleep(.01)
            self.assertEqual(result.json(),{'state':'failed','message':'供应商不可用'})
            self.assertEqual(result.headers['cache-control'],'no-store')
