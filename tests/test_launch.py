import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LauncherTests(unittest.TestCase):
    def test_failed_service_stops_its_sibling(self):
        with tempfile.TemporaryDirectory() as folder:
            stopped=Path(folder)/'stopped'
            child='import signal,time,pathlib; signal.signal(signal.SIGTERM,lambda *a:(pathlib.Path('+repr(str(stopped))+').write_text("stopped"),exit(0))); time.sleep(10)'
            script='from app.launch import run; import sys; sys.exit(run('+repr([
                [sys.executable,'-c',child],
                [sys.executable,'-c','import time; time.sleep(.5); raise SystemExit(7)']
            ])+',shutdown_timeout=1))'
            result=subprocess.run([sys.executable,'-c',script],timeout=8,capture_output=True)
            self.assertEqual(result.returncode,7,result.stderr.decode(errors='replace'))
            if os.name!='nt':self.assertTrue(stopped.exists())
