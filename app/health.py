"""Loopback-only health check for the combined deployment."""
import ssl
import urllib.request


def check():
    with urllib.request.urlopen('http://127.0.0.1:8000/api/status',timeout=3) as r:
        if r.status!=200:raise RuntimeError('Chart service unhealthy')
    # The NAS certificate is issued for its LAN name/IP rather than loopback.
    with urllib.request.urlopen('https://127.0.0.1:8443/health',context=ssl._create_unverified_context(),timeout=3) as r:
        if r.status!=200:raise RuntimeError('Trading service unhealthy')


if __name__=='__main__':check()
