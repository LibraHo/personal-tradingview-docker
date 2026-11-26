import unittest
from unittest.mock import AsyncMock

from fastapi import Request
from fastapi.responses import JSONResponse

from app import main as market


class ScannerOriginTests(unittest.IsolatedAsyncioTestCase):
    async def preview(self, headers):
        request = Request({
            'type': 'http',
            'method': 'POST',
            'path': '/api/scanner/scope-preview',
            'scheme': 'http',
            'server': ('testserver', 80),
            'query_string': b'',
            'headers': [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        })
        call_next = AsyncMock(return_value=JSONResponse({'ok': True}))
        return await market.auth(request, call_next)

    async def test_proxy_preserves_browser_same_origin_metadata(self):
        response = await self.preview({
            'Origin': 'https://remote-access-8088.zconnect.cn',
            'Sec-Fetch-Site': 'same-origin',
        })
        self.assertEqual(response.status_code, 200, response.body)

    async def test_lan_origin_without_fetch_metadata(self):
        response = await self.preview({'Origin': 'http://testserver'})
        self.assertEqual(response.status_code, 200, response.body)

    async def test_cross_origin_requests_remain_rejected(self):
        for site in ('cross-site', 'same-site', 'none', ''):
            with self.subTest(site=site):
                response = await self.preview({
                    'Origin': 'https://other.example',
                    'Sec-Fetch-Site': site,
                })
                self.assertEqual(response.status_code, 403, response.body)


if __name__ == '__main__':
    unittest.main()
