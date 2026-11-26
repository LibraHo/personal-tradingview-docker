"""Shared read-only OpenClaw chat completion client."""
import json
import re
from urllib import error, parse, request

from fastapi import HTTPException


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def complete(url, token, agent_id, prompt, context):
    parsed = parse.urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503,'请检查 OpenClaw 网关地址')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',agent_id):
        raise HTTPException(503,'请检查 OpenClaw Agent ID')
    base = url.rstrip('/')
    endpoint = base + ('/chat/completions' if base.endswith('/v1') else '/v1/chat/completions')
    payload = {'model':'openclaw/'+agent_id,'stream':False,'tool_choice':'none','messages':[
        {'role':'system','content':prompt},
        {'role':'user','content':json.dumps(context, ensure_ascii=False, separators=(',', ':'), allow_nan=False)}]}
    req = request.Request(endpoint,data=json.dumps(payload).encode(),headers={
        'Content-Type':'application/json','Authorization':'Bearer '+token})
    try:
        opener = request.build_opener(request.ProxyHandler({}),NoRedirect())
        with opener.open(req,timeout=75) as response:
            raw = response.read(128*1024+1)
        if len(raw)>128*1024:
            raise ValueError()
        choice = json.loads(raw)['choices'][0]
        if choice.get('finish_reason') not in (None,'stop'):
            raise ValueError()
        content = choice['message']['content'].strip()
        if not content:
            raise ValueError()
        return content
    except error.HTTPError as exc:
        if exc.code in (401,403):
            raise HTTPException(502,'OpenClaw 凭证或权限无效')
        if exc.code==429:
            raise HTTPException(429,'OpenClaw 请求过于频繁，请稍后重试')
        raise HTTPException(502,'OpenClaw 调用失败，请检查网关地址、接口开关和 Agent 配置')
    except (TimeoutError,OSError):
        raise HTTPException(503,'OpenClaw 未及时响应，请稍后重试')
    except (ValueError,IndexError,KeyError,TypeError,AttributeError):
        raise HTTPException(502,'OpenClaw 返回的内容无效')
