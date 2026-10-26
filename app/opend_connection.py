"""Avoid the SDK's indefinitely blocking synchronous quote constructor."""
import os
import time


def connect_quote_context(factory, timeout=None, **kwargs):
    seconds=max(1,min(float(os.getenv('OPEND_CONNECT_TIMEOUT_SECONDS','8')),30)) if timeout is None else timeout
    context=factory(is_async_connect=True,**kwargs)
    deadline=time.monotonic()+seconds
    try:
        while True:
            if context.get_sync_conn_id():return context
            if time.monotonic()>=deadline:
                raise RuntimeError('OpenD 连接超时，请检查 OpenD 是否已登录；登录后可重试，无需重启看盘服务')
            time.sleep(.1)
    except Exception:
        try:context.close()
        except Exception:pass
        raise
