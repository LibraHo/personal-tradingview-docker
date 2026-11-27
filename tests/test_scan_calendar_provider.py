import unittest
from types import SimpleNamespace
from app.radar import Radar

class CalendarProviderTests(unittest.TestCase):
    def test_cn_uses_trade_date_market_not_quote_market(self):
        calls=[]
        def call(name,**kw):
            calls.append((name,kw));return ([{'time':'2026-11-16','trade_date_type':'WHOLE'}],)
        radar=SimpleNamespace(call=call,cached=lambda key,ttl,fn:fn())
        self.assertEqual(Radar.trading_days(radar, 'SH.600000')['2026-11-16'],'WHOLE')
        self.assertEqual(calls[0][1]['market'],'CN')
