import os,tempfile,time,unittest,types,sys
from pathlib import Path
from unittest.mock import patch,MagicMock
from fastapi.testclient import TestClient
from app import main as market

class SymbolSearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(market,'DB',str(Path(self.tmp.name)/'market.sqlite3'));self.db.start();market.init_db();self.bridge=market.Bridge();self.bridge.rate_limit=MagicMock();self.ctx=MagicMock();self.bridge.ensure=MagicMock(return_value=self.ctx);self.sdk=patch.dict(sys.modules,{'moomoo':types.SimpleNamespace(RET_OK=0)});self.sdk.start()
 def tearDown(self):self.sdk.stop();self.db.stop();self.tmp.cleanup()
 def frame(self,rows):
  frame=MagicMock();frame.to_dict.return_value=rows;return frame
 def test_cn_name_code_partial_and_persisted_directory(self):
  self.ctx.get_stock_basicinfo.side_effect=[(0,self.frame([{'code':'SH.600519','name':'贵州茅台'},{'code':'SH.600584','name':'长电科技'},{'code':'SH.900901','name':'B股不应进入A股目录'}])),(0,self.frame([{'code':'SZ.000001','name':'平安银行'}]))]
  self.assertEqual(self.bridge.search_symbols('茅台')['results'][0],{'symbol':'SH.600519','name':'贵州茅台'})
  self.assertEqual(self.bridge.search_symbols('600584')['results'][0]['name'],'长电科技')
  self.assertEqual(self.bridge.search_symbols('平安')['results'][0]['symbol'],'SZ.000001')
  self.assertEqual(self.bridge.search_symbols('%')['results'],[])
  self.assertEqual(self.ctx.get_stock_basicinfo.call_count,2)
  restarted=market.Bridge();restarted.ensure=MagicMock(side_effect=AssertionError('fresh cache must not call OpenD'))
  self.assertEqual(restarted.search_symbols('贵州 茅台')['results'][0]['symbol'],'SH.600519')
 def test_failure_preserves_known_names_and_limits_retries(self):
  with market.connect_db() as db:db.execute('INSERT INTO symbol_names VALUES(?,?,?)',('SH.600519','贵州茅台',time.time()))
  self.ctx.get_stock_basicinfo.side_effect=RuntimeError('offline')
  result=self.bridge.search_symbols('茅台');self.assertEqual(result['results'][0]['name'],'贵州茅台');self.assertTrue(result['stale']);self.bridge.search_symbols('茅台');self.assertEqual(self.ctx.get_stock_basicinfo.call_count,2)
 def test_api_validation_and_market_filter(self):
  client=TestClient(market.app)
  with patch.object(market.bridge,'search_symbols',return_value={'results':[],'stale':False}):
   self.assertEqual(client.get('/api/symbols/search?q=茅台&market=CN').status_code,200)
   self.assertEqual(client.get('/api/symbols/search?q=茅台&market=BAD').status_code,400)
   self.assertEqual(client.get('/api/symbols/search?q='+'a'*50).status_code,400)
