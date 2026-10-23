import unittest

class WatchlistImportTests(unittest.TestCase):
    def test_splits_mixed_group_and_preserves_local_groups(self):
        from app.main import merge_moomoo_groups
        workspace = {'activeMarket': 'CN', 'markets': {
            'US': {'groups': [{'id': 'featured', 'name': '精选', 'symbols': ['US.SNDK']},
                              {'id': 'local', 'name': '本地', 'symbols': ['US.AAPL']}]},
            'CN': {'groups': [{'id': 'featured', 'name': '精选', 'symbols': ['SH.600519']}]}}}
        remote = [{'name': '混合', 'kind': 'CUSTOM',
                   'symbols': ['US.NVDA', 'SH.600519', 'SZ.000001', 'HK.00700']}]
        result, summary = merge_moomoo_groups(workspace, remote)
        self.assertEqual(result['activeMarket'], 'CN')
        self.assertEqual(result['markets']['US']['groups'][1]['symbols'], ['US.AAPL'])
        self.assertEqual(result['markets']['US']['groups'][2]['symbols'], ['US.NVDA'])
        self.assertEqual(result['markets']['CN']['groups'][1]['symbols'], ['SH.600519', 'SZ.000001'])
        self.assertEqual(summary['unsupported_symbols'], 1)
        again, _ = merge_moomoo_groups(result, remote)
        self.assertEqual(len(again['markets']['US']['groups']), 3)


if __name__ == '__main__':
    unittest.main()
