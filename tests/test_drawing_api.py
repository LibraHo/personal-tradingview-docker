import os,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main as market

class DrawingApiTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(market,'DB',str(Path(self.tmp.name)/'market.sqlite3'));self.db.start();self.env=patch.dict(os.environ,{'DRAWING_API_TOKEN':'test-drawing-token-that-is-long-enough'});self.env.start();market.init_db();self.client=TestClient(market.app);self.auth={'Authorization':'Bearer test-drawing-token-that-is-long-enough'}
 def tearDown(self):self.env.stop();self.db.stop();self.tmp.cleanup()
 def create(self,kind='horizontal',**kwargs):
  return self.client.post('/api/drawings/objects',headers=self.auth,json={'symbol':'US.SNDK','period':'5m','kind':kind,**({'price':130} if kind=='horizontal' else {'points':[{'time':1700000000,'price':120},{'time':1700000300,'price':130}]}),**kwargs})
 def test_token_and_crud_all_tools(self):
  self.assertEqual(self.client.get('/api/drawings/capabilities').status_code,401)
  self.assertEqual(self.client.get('/api/drawings/capabilities',headers=self.auth).status_code,200)
  for kind in ['horizontal','trend','fib']:
   r=self.create(kind,color='#ff0000',id='agent-'+kind);self.assertEqual(r.status_code,201,r.text)
   url='/api/drawings/objects/agent-'+kind+'?symbol=US.SNDK&period=5m&kind='+kind
   r=self.client.patch(url,headers=self.auth,json={'visible':False});self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['object']['visible'])
   self.assertEqual(self.client.delete(url,headers=self.auth).status_code,200)
  self.assertEqual(self.client.get('/api/drawings/objects?symbol=US.SNDK&period=5m',headers=self.auth).json()['objects'],[])
 def test_token_is_independent_of_trusted_browser_header(self):
  with patch.dict(os.environ, {'TRUSTED_USER_HEADER':'X-Logged-In-User'}):
   self.assertEqual(self.client.get('/api/drawings/capabilities',headers=self.auth).status_code,200)
   self.assertEqual(self.client.get('/api/settings/workspace').status_code,401)
 def test_idempotency_validation_and_revision(self):
  r=self.create(id='agent-one');rev=r.json()['revision'];self.assertEqual(self.create(id='agent-one').status_code,200)
  self.assertEqual(self.create(id='agent-one',price=140).status_code,409)
  self.assertEqual(self.create(price=-5).status_code,422)
  self.assertEqual(self.create('trend',points=[{'time':1,'price':1},{'time':1,'price':2}]).status_code,422)
  self.assertEqual(self.create('fib',levels=[1,1.618],levelColors={'1.618':'#00ff00'}).status_code,201)
  self.assertEqual(self.client.put('/api/drawings/visibility',headers={**self.auth,'If-Match':str(rev)},json={'symbol':'US.SNDK','period':'5m','hidden':True}).status_code,409)
 def test_old_workspace_cannot_overwrite_agent_drawings(self):
  initial=self.client.get('/api/settings/workspace').json()
  self.create(id='agent-new')
  r=self.client.put('/api/settings/workspace',json={'value':initial['value'],'drawing_revision':initial['drawing_revision']});self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['drawings_conflict'])
  objects=self.client.get('/api/drawings/objects',headers=self.auth).json()['objects'];self.assertEqual(objects[0]['id'],'agent-new')
  rev=r.json()['drawing_revision'];self.assertFalse(self.client.get('/api/settings/workspace?drawings_only=true&since='+str(rev)).json()['changed'])
 def test_browser_and_agent_share_storage(self):
  self.create(id='agent-base');value=self.client.get('/api/settings/workspace').json();workspace=value['value'];workspace['markets']['US']['drawings']['US.SNDK:5m'][0]['price']=150
  r=self.client.put('/api/settings/workspace',json={'value':workspace,'drawing_revision':value['drawing_revision']});self.assertFalse(r.json()['drawings_conflict'])
  self.assertEqual(self.client.get('/api/drawings/objects',headers=self.auth).json()['objects'][0]['price'],150)
  self.client.put('/api/drawings/visibility',headers=self.auth,json={'symbol':'US.SNDK','period':'5m','hidden':True})
  self.assertTrue(self.client.get('/api/settings/workspace?drawings_only=true').json()['value']['markets']['US']['drawingsHidden']['US.SNDK:5m'])
