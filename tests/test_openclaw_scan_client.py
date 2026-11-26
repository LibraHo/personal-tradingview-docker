import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec=importlib.util.spec_from_file_location('scan_client',Path(__file__).parents[1]/'integrations/openclaw/scan.py')
client=importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

class ScanClientTests(unittest.TestCase):
    def test_network_retry_keeps_the_original_request_id(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'NAS_MARKET_SCAN_STATE_DIR':directory}):
            with patch.object(client,'call',side_effect=urllib.error.URLError('timeout')) as call:
                unknown=client.run_plan('plan')
                self.assertEqual(unknown['status'],'submission_unconfirmed')
                first=call.call_args.args[2]['request_id']
            with patch.object(client,'call',return_value={'id':'job','status':'queued'}) as call:
                received=client.run_plan('plan')
                self.assertEqual(call.call_args.args[2]['request_id'],first)
                self.assertEqual(received['request_id'],first)
            self.assertEqual(list(Path(directory).glob('*.json')),[])

    def test_http_failure_is_reported_as_known_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'NAS_MARKET_SCAN_STATE_DIR':directory}):
            error=urllib.error.HTTPError('http://market',422,'Invalid request',{},io.BytesIO())
            with patch.object(client,'call',side_effect=error),self.assertRaises(urllib.error.HTTPError):
                client.run_plan('plan')
            self.assertEqual(list(Path(directory).glob('*.json')),[])

    def test_read_results_does_not_submit_or_wait(self):
        with patch.object(sys,'argv',['scan.py','results','plan']),patch.object(client,'call',return_value={'ready':False,'status':'running','job_id':'job'}) as call,patch('sys.stdout',new_callable=io.StringIO) as output:
            client.main()
        call.assert_called_once_with('plans/plan/results?max_age_seconds=86400')
        self.assertEqual(json.loads(output.getvalue())['job_id'],'job')

if __name__=='__main__':
    unittest.main()
