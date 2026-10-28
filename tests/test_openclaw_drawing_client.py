import importlib.util,os,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

spec=importlib.util.spec_from_file_location('drawing_client',Path(__file__).parents[1]/'integrations/openclaw/draw.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)

class OpenClawDrawingClientTests(unittest.TestCase):
 def test_adds_nas_ca_without_replacing_gateway_ca_defaults(self):
  context=MagicMock()
  with patch.object(client.ssl,'create_default_context',return_value=context) as create:
   self.assertIs(client.create_tls_context('/public/nas-ca.pem'),context)
   create.assert_called_once_with()
   context.load_verify_locations.assert_called_once_with(cafile='/public/nas-ca.pem')
 def test_default_context_keeps_inherited_ssl_cert_file(self):
  context=MagicMock()
  with patch.object(client.ssl,'create_default_context',return_value=context) as create:
   client.create_tls_context(None);create.assert_called_once_with();context.load_verify_locations.assert_not_called()
 def test_protected_token_refuses_missing_proxy_and_bypass(self):
  with patch.object(client.urllib.request,'getproxies',return_value={}):
   with self.assertRaises(ValueError):client.validate_token_transport('oc-sent-v2.fake.end','https://192.168.101.103:8443')
  with patch.object(client.urllib.request,'getproxies',return_value={'https':'http://openclaw:test-only@127.0.0.1:1234'}),patch.object(client.urllib.request,'proxy_bypass',return_value=True):
   with self.assertRaises(ValueError):client.validate_token_transport('oc-sent-v2.fake.end','https://192.168.101.103:8443')
  with patch.object(client.urllib.request,'getproxies',return_value={'https':'http://proxy.example:1234'}),patch.object(client.urllib.request,'proxy_bypass',return_value=False):
   with self.assertRaises(ValueError):client.validate_token_transport('oc-sent-v2.fake.end','https://192.168.101.103:8443')
  with patch.object(client.urllib.request,'getproxies',return_value={'https':'http://openclaw:test-only@127.0.0.1:1234'}),patch.object(client.urllib.request,'proxy_bypass',return_value=False):
   client.validate_token_transport('oc-sent-v2.fake.end','https://192.168.101.103:8443')
 def test_diagnose_does_not_require_or_retrieve_token(self):
  with patch.dict(os.environ,{},clear=True),patch.object(client.sys,'argv',['draw.py','diagnose']),patch.object(client,'create_tls_context',return_value=object()),patch.object(client,'diagnose') as diagnose:
   self.assertEqual(client.main(),0);diagnose.assert_called_once()
 def test_port_specific_no_proxy_is_rejected(self):
  with patch.dict(os.environ,{'HTTPS_PROXY':'http://openclaw:test-only@127.0.0.1:1234','NO_PROXY':'192.168.101.103:8443'},clear=True):
   with self.assertRaises(ValueError):client.validate_token_transport('oc-sent-v2.fake.end','https://192.168.101.103:8443')
