import contextlib
import http.server
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from integrations.openclaw import scan
from integrations.openclaw.review import review


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path)
        status, headers, body = self.server.reply
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@contextlib.contextmanager
def server(status, body, headers=None):
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as service:
        service.paths = []
        service.reply = status, headers or {}, body
        worker = threading.Thread(target=service.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        try:
            yield service
        finally:
            service.shutdown()
            worker.join()


class OpenClawMarketProxyTests(unittest.TestCase):
    def test_default_market_origin_uses_direct_connection_under_proxy_injection(self):
        with server(200, b'{"ok":true}') as market, server(502, b'Secret egress proxy refused the request.') as proxy:
            with self.gateway_environment(market, proxy):
                self.assertEqual(review.call('rules', 'CN'), {'ok': True})
                self.assertEqual(scan.call('health'), {'ok': True})
            self.assertEqual(market.paths, ['/api/v1/review/rules?market=CN', '/api/v1/health'])
            self.assertEqual(proxy.paths, [])

    def test_other_origin_still_uses_its_configured_proxy(self):
        with server(200, b'{}') as market, server(502, b'proxy response') as proxy:
            with self.gateway_environment(market, proxy, base='http://other.internal:8000'):
                for call in (lambda: review.call('rules', 'CN'), lambda: scan.call('health')):
                    with self.assertRaises(HTTPError) as error:
                        call()
                    self.assertEqual(error.exception.code, 502)
                    error.exception.close()
            self.assertEqual(market.paths, [])
            self.assertEqual(len(proxy.paths), 2)

    def test_direct_connection_does_not_follow_redirects_with_credential(self):
        with server(302, b'', {'Location': 'http://other.internal:8000/redirect'}) as market, server(502, b'proxy response') as proxy:
            with self.gateway_environment(market, proxy):
                for call in (lambda: review.call('rules', 'CN'), lambda: scan.call('health')):
                    with self.assertRaises(HTTPError) as error:
                        call()
                    self.assertEqual(error.exception.code, 302)
                    error.exception.close()
            self.assertEqual(proxy.paths, [])

    @contextlib.contextmanager
    def gateway_environment(self, market, proxy, base='http://market:8000'):
        original = socket.create_connection

        def connect(address, *args, **kwargs):
            return original(market.server_address if address == ('market', 8000) else address, *args, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'test-token'
            token.write_text('fixture-not-a-real-credential')
            variables = {
                'http_proxy': f'http://127.0.0.1:{proxy.server_port}',
                'no_proxy': '',
                'NAS_MARKET_API_URL': base,
                'NAS_MARKET_REVIEW_TOKEN_FILE': str(token),
                'NAS_MARKET_SCAN_TOKEN_FILE': str(token),
            }
            with patch.dict(os.environ, variables), patch('socket.create_connection', side_effect=connect):
                yield
