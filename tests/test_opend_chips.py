import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.opend_chips import ChipPages, chip_page, fill_request
from app.opend_market import OpenDMarket


class Message(SimpleNamespace):
    def HasField(self, name):
        return name in vars(self)


class Messages(list):
    def add(self):
        item = Message(simpleFieldQuery=Message(screenValueList=[]),
                       basicProperty=Message(), featuredProperty=Message())
        self.append(item)
        return item


def field(field_type, name, value_type, **data):
    return Message(**{field_type+'PropertyResult':Message(property=Message(name=name),valueType=value_type,**data)})


class OpenDChipTests(unittest.TestCase):
    def test_request_page_fields_match_3252(self):
        c2s = Message(filterList=Messages(),retrieveList=Messages(),sort=Message(simpleProperty=Message()))
        fill_request(Message(c2s=c2s),'CN',100,50)
        self.assertEqual((c2s.pageFrom,c2s.pageCount),(100,50))
        self.assertEqual(vars(c2s.filterList[0].simpleFieldQuery),{'simpleField':1,'screenValueList':[3]})
        self.assertEqual((c2s.sort.direction,c2s.sort.simpleProperty.name),(2,2301))
        self.assertEqual([c2s.retrieveList[0].basicProperty.name,
                          *(r.featuredProperty.name for r in c2s.retrieveList[1:])],[1101,5101,5102])

    def test_response_preserves_known_zero_missing_and_canonical_markets(self):
        stock = lambda code, *fields: Message(results=[field('basic',1101,1,sval=code),*fields])
        rows = [stock('601398',field('featured',5101,4,dval=0.0),field('featured',5102,4,dval=.7647)),
                stock('000001',field('featured',5101,4),field('featured',5102,2,ival=0)),
                stock('920001'), stock('600000',field('featured',5101,4,dval=float('nan')))]
        response = Message(retType=0,s2c=Message(allCount=5315,dataList=rows))
        ret, _, data = chip_page(response,'CN')
        self.assertEqual(ret,0)
        self.assertEqual(data['total'],5315)
        self.assertEqual(data['rows'],[
            {'symbol':'SH.601398','profit_ratio':0.0,'interval_overlap':.7647},
            {'symbol':'SZ.000001','profit_ratio':None,'interval_overlap':None},
            {'symbol':'SH.600000','profit_ratio':None,'interval_overlap':None}])
        response.s2c.dataList = [stock('BRK.B',field('featured',5101,4,dval=1.0))]
        self.assertEqual(chip_page(response,'US')[2]['rows'][0]['symbol'],'US.BRK.B')
        self.assertEqual(chip_page(Message(retType=-1,retMsg='未授权'),'US'),(-1,'未授权',None))
        self.assertEqual(chip_page(Message(retType=0),'US')[0],-1)

    def test_market_method_warms_bounded_pages_and_does_not_cache_errors(self):
        adapter = OpenDMarket(None,{})
        adapter.ensure = Mock()
        adapter.rate_limit = Mock()
        page = {'total':5315,'rows':[]}
        with patch('app.opend_market.request_page',side_effect=[RuntimeError('quota'),page,page]) as fetch:
            with self.assertRaisesRegex(RuntimeError,'quota'):
                adapter.chip_summary('CN',0,200)
            self.assertEqual(adapter.chip_summary('CN',0,200),page)
            self.assertEqual(adapter.chip_summary('CN',0,200),page)
            self.assertEqual(adapter.chip_summary('CN',200,200),page)
            self.assertEqual(fetch.call_count,3)

    def test_rate_budget_on_uncached_pages_shared_between_markets(self):
        cache = ChipPages()
        fetch = Mock(return_value={'total':0,'rows':[]})
        with patch('app.opend_chips.time.monotonic',return_value=100) as clock:
            for i in range(10):
                cache.get('US',i,1,fetch)
            cache.get('US',0,1,fetch)
            with self.assertRaisesRegex(RuntimeError,'限额'):
                cache.get('CN',0,10,fetch)
            clock.return_value = 130
            cache.get('CN',0,10,fetch)
            clock.return_value = 161
            cache.get('US',0,1,fetch)
            self.assertEqual(fetch.call_count,12)
        for args in [('HK',0,10),('CN',-1,10),('US',0,201)]:
            with self.assertRaises(ValueError):
                cache.get(*args,fetch)
