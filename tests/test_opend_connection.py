import unittest
from unittest.mock import MagicMock
from app.opend_connection import connect_quote_context


class ConnectionTests(unittest.TestCase):
    def test_timeout_closes_context_and_next_attempt_can_succeed(self):
        failed=MagicMock();failed.get_sync_conn_id.return_value=0
        ready=MagicMock();ready.get_sync_conn_id.return_value=123
        factory=MagicMock(side_effect=[failed,ready])
        with self.assertRaisesRegex(RuntimeError,'连接超时'):
            connect_quote_context(factory,timeout=0,host='127.0.0.1',port=11111)
        failed.close.assert_called_once()
        result=connect_quote_context(factory,timeout=0,host='127.0.0.1',port=11111)
        self.assertIs(result,ready)
        ready.close.assert_not_called()
        self.assertTrue(factory.call_args.kwargs['is_async_connect'])

    def test_readiness_error_also_closes_context(self):
        context=MagicMock();context.get_sync_conn_id.side_effect=RuntimeError('transport failed')
        with self.assertRaisesRegex(RuntimeError,'transport failed'):
            connect_quote_context(lambda **kwargs:context,timeout=0)
        context.close.assert_called_once()
