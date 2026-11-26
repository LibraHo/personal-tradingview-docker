import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.depth import DepthFeed
from app.market_flow import option_profile


class MarketFlowTests(unittest.TestCase):
    def test_profile_groups_strikes_and_preserves_missing_sides(self):
        chain = [
            {'code': 'US.C1', 'strike_price': 100, 'option_type': 'CALL'},
            {'code': 'US.P1', 'strike_price': 100, 'option_type': 'PUT'},
            {'code': 'US.C2', 'strike_price': 101, 'option_type': 'CALL'},
        ]
        ctx = SimpleNamespace(
            get_option_chain=lambda *a, **kw: (0, SimpleNamespace(to_dict=lambda _: chain)),
            get_market_snapshot=lambda codes: (0, SimpleNamespace(to_dict=lambda _: [
                {'code': 'US.C1', 'volume': 20}, {'code': 'US.P1', 'volume': 0}
            ])),
        )
        self.assertEqual(option_profile(ctx, 'US.SPY', '2026-11-09', lambda: None), [
            {'strike': 100, 'call': 20, 'put': 0},
            {'strike': 101, 'call': None, 'put': None},
        ])


    def test_ticker_feed_uses_rth_and_releases_its_subscription(self):
        sdk = SimpleNamespace(RET_OK=0, SubType=SimpleNamespace(TICKER='ticker'),
                              Session=SimpleNamespace(RTH='rth'))
        records = SimpleNamespace(to_dict=lambda _: [
            {'sequence': 9007199254740993, 'time': '2026-11-09 09:30:00.000',
             'price': 100, 'volume': 10, 'ticker_direction': 'BUY'}
        ])
        ctx = Mock()
        ctx.subscribe.return_value = (0, '')
        ctx.get_rt_ticker.return_value = (0, records)
        ctx.unsubscribe.return_value = (0, '')
        feed = DepthFeed('TICKER')
        feed.ctx = ctx
        with patch.dict(sys.modules, {'moomoo': sdk}):
            with patch('app.depth.time.monotonic', return_value=10):
                self.assertEqual(feed.read_ticks('US.SPY')[0]['sequence'], '9007199254740993')
                feed.read_ticks('US.SPY')
            with patch('app.depth.time.monotonic', return_value=80):
                feed.cleanup()
        ctx.subscribe.assert_called_once_with(['US.SPY'], ['ticker'], subscribe_push=False, session='rth')
        ctx.get_rt_ticker.assert_called_once_with('US.SPY', num=1000)
        ctx.unsubscribe.assert_called_once_with(['US.SPY'], ['ticker'])
        ctx.close.assert_called_once()
