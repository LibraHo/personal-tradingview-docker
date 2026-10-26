"""Run the chart and TLS trading services in one container, with shared fate."""
import os
import signal
import subprocess
import sys
import threading


def commands():
    return [
        [sys.executable,'-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000','--workers','1'],
        [sys.executable,'-m','uvicorn','app.trade_api:app','--host','0.0.0.0','--port','8443','--workers','1',
         '--no-proxy-headers','--ssl-keyfile',os.getenv('TRADING_TLS_KEY','/tls/key.pem'),
         '--ssl-certfile',os.getenv('TRADING_TLS_CERT','/tls/cert.pem'),'--no-access-log'],
    ]


def run(service_commands=None,shutdown_timeout=25):
    stop=threading.Event();children=[];result=0;previous={}
    def stopping(signum,frame):stop.set()
    for sig in (signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,stopping)
    try:
        for command in service_commands or commands():children.append(subprocess.Popen(command))
        while not stop.wait(.2):
            exited=next((p.returncode for p in children if p.poll() is not None),None)
            if exited is not None:
                result=exited if exited>0 else 1
                break
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=shutdown_timeout)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        for sig,handler in previous.items():signal.signal(sig,handler)
    return result


if __name__=='__main__':sys.exit(run())
