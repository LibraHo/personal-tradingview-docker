import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as market


class ThemeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = patch.object(market, 'DB', str(Path(self.directory.name) / 'market.sqlite3'))
        self.database.start()
        market.init_db()
        self.client = TestClient(market.app)
        self.headers = {
            'Origin': 'https://remote-access-8088.zconnect.cn',
            'Sec-Fetch-Site': 'same-origin',
        }

    def tearDown(self):
        self.client.close()
        self.database.stop()
        self.directory.cleanup()

    def save(self, value, **options):
        return self.client.put('/api/settings/theme', headers=self.headers,
                               json={'value': value, **options})

    def test_theme_is_shared_and_survives_new_browser_session(self):
        self.assertIsNone(self.client.get('/api/settings/theme').json()['value'])
        response = self.save('light')
        self.assertEqual(response.status_code, 200, response.text)
        another_browser = TestClient(market.app)
        try:
            result = another_browser.get('/api/settings/theme')
            self.assertEqual(result.json()['value'], 'light')
            self.assertEqual(result.headers['cache-control'], 'no-store')
        finally:
            another_browser.close()

    def test_initializing_another_origin_keeps_the_saved_theme(self):
        self.assertEqual(self.save('light', initialize=True).json()['value'], 'light')
        self.assertEqual(self.save('dark', initialize=True).json()['value'], 'light')
        self.assertEqual(self.save('dark').json()['value'], 'dark')

    def test_invalid_and_cross_site_writes_preserve_theme(self):
        self.save('light')
        for invalid in ('blue', {}, None, True):
            with self.subTest(value=invalid):
                self.assertEqual(self.save(invalid).status_code, 422)
        rejected = self.client.put('/api/settings/theme', json={'value': 'dark'},
                                   headers={'Origin': 'https://other.example',
                                            'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(self.client.get('/api/settings/theme').json()['value'], 'light')


if __name__ == '__main__':
    unittest.main()
