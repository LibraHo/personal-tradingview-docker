#!/usr/bin/env python3
"""Bounded NAS Market requests and durable scan job controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def call(path, method='GET', body=None, request_id=None):
    base = os.environ.get('NAS_MARKET_API_URL', 'http://market:8000').rstrip('/')
    secret = Path(os.environ.get('NAS_MARKET_SCAN_TOKEN_FILE',
                  str(Path.home() / '.openclaw/credentials/nas-market-scan-token'))).read_text().strip()
    context = ssl.create_default_context(cafile=os.environ.get('NAS_MARKET_CA_FILE') or None)
    headers = {'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'}
    if request_id:
        headers['Idempotency-Key'] = request_id
    request = urllib.request.Request(base + '/api/v1/' + path, method=method,
              data=json.dumps(body).encode() if body is not None else None, headers=headers)
    timeout = max(1, min(60, float(os.environ.get('NAS_MARKET_API_TIMEOUT_SECONDS', '15'))))
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.load(response)



def clear_pending_request(path, ident):
    try:
        if json.loads(path.read_text()).get('request_id') == ident:
            path.unlink()
    except FileNotFoundError:
        pass

def run_plan(plan_id, force=False, reuse_seconds=86400, request_id=None):
    directory = Path(os.environ.get('NAS_MARKET_SCAN_STATE_DIR',
                     str(Path.home() / '.openclaw/nas-market-scan-requests')))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (hashlib.sha256(plan_id.encode()).hexdigest() + '.json')
    try:
        pending = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        pending = {}
    options = {'force': force, 'reuse_seconds': reuse_seconds}
    reusable = pending.get('options') == options
    ident = request_id or (pending.get('request_id') if reusable else None) or uuid.uuid4().hex
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps({'request_id': ident, 'options': options}))
    os.replace(temporary, path)
    try:
        job = call('plans/' + urllib.parse.quote(plan_id, safe='') + '/run', 'POST',
                   {'request_id': ident, **options}, request_id=ident)
    except urllib.error.HTTPError:
        clear_pending_request(path, ident)
        raise
    except (urllib.error.URLError, TimeoutError):
        return {'status': 'submission_unconfirmed', 'ready': False, 'plan_id': plan_id,
                'request_id': ident, 'retry_after_seconds': 5,
                'message': '提交回执尚未确认；再次运行本命令会复用同一请求编号，不要另建方案或任务。'}
    clear_pending_request(path, ident)
    return {**job, 'request_id': ident}


def create():
    name = 'OpenClaw 刚变六红'
    plans = call('plans')['items']
    existing = next((plan for plan in plans if plan.get('name') == name and plan.get('live') is True), None)
    if existing is None:
        existing = call('plans', 'POST', {
            'name': name, 'scope': {'kind': 'all'}, 'periods': ['1d'], 'lookback': 1, 'live': True,
            'rules': [{'left': {'name': 'SIXPULSE', 'line': 'REDS'}, 'op': 'reach',
                       'right': {'name': 'NUMBER', 'value': 6}}]})
    monitors = call('monitors')['items']
    monitor = next((item for item in monitors if item['plan_id'] == existing['id'] and item.get('plan_version') == existing['version']), None)
    if monitor is not None:
        return monitor
    return call('monitors', 'POST', {'plan_id': existing['id'], 'name': '全部关注列表 · 刚变六红',
                'interval_seconds': 120, 'follow_watchlists': True, 'backfill': False, 'trading_only': True})


def consume(cursor_path, confirmed_only=False):
    path = Path(cursor_path)
    cursor = int(path.read_text()) if path.exists() else 0
    query = {'after': cursor, 'limit': 100}
    if confirmed_only:
        query['confirmation'] = 'confirmed'
    page = call('events?' + urllib.parse.urlencode(query))
    for event in page['items']:
        confirmation = '收盘确认' if event['confirmation'] == 'confirmed' else '盘中预览'
        message = (f"{event.get('name', event['symbol'])}（{event['symbol']}）{event['period']} 出现信号；"
                   f"K线 {event['time']}；{confirmation}；发现方式 {event['delivery_kind']}。图表 {event['chart_url']}")
        print(json.dumps({'event_id': event['event_id'], 'message': message, 'event': event},
                         ensure_ascii=False), flush=True)
    # Production delivery should acknowledge after delivery using a durable outbox.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.next')
    temporary.write_text(str(page['next_cursor']))
    os.replace(temporary, path)
    return len(page['items'])


def main():
    parser = argparse.ArgumentParser(description='读取预扫描结果、提交后台任务和管理任务进度')
    parser.add_argument('command', choices=['health', 'watchlists', 'plans', 'jobs', 'job', 'run',
                        'results', 'pause', 'resume', 'cancel', 'create-six-red', 'events', 'poll'])
    parser.add_argument('id', nargs='?', help='方案编号或任务编号')
    parser.add_argument('--market', choices=['CN', 'US'])
    parser.add_argument('--force', action='store_true', help='显式刷新已完成结果，仍复用正在执行的相同任务')
    parser.add_argument('--request-id', help='同一次提交意图的固定幂等编号')
    parser.add_argument('--reuse-seconds', type=int, default=86400)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--confirmed-only', action='store_true')
    parser.add_argument('--cursor-file', default=str(Path.home() / '.openclaw/nas-market-event-cursor'))
    args = parser.parse_args()
    if args.command in ('job', 'run', 'results', 'pause', 'resume', 'cancel') and not args.id:
        parser.error('该命令需要方案编号或任务编号')
    if args.command in ('events', 'poll'):
        while True:
            consume(args.cursor_file, args.confirmed_only)
            if args.command == 'events':
                return
            time.sleep(15)
    elif args.command == 'create-six-red':
        result = create()
    elif args.command == 'run':
        result = run_plan(args.id, args.force, args.reuse_seconds, args.request_id)
    elif args.command == 'results':
        result = call('plans/' + urllib.parse.quote(args.id, safe='') + '/results?' +
                      urllib.parse.urlencode({'max_age_seconds': args.reuse_seconds}))
    elif args.command == 'job':
        result = call('jobs/' + urllib.parse.quote(args.id, safe='') + ('?summary=true' if not args.full else ''))
    elif args.command in ('pause', 'resume', 'cancel'):
        result = call('jobs/' + urllib.parse.quote(args.id, safe='') + '/' + args.command, 'POST')
    else:
        query = {}
        if args.market:
            query['market'] = args.market
        if args.command == 'jobs' and args.id:
            query['plan_id'] = args.id
        result = call(args.command + ('?' + urllib.parse.urlencode(query) if query else ''))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(4096)).get('detail', 'API 请求失败')
        except (ValueError, AttributeError):
            detail = 'API 请求失败'
        print(json.dumps({'status': 'api_error', 'http_status': error.code, 'message': detail},
                         ensure_ascii=False))
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        print(json.dumps({'status': 'unavailable', 'ready': False,
                          'message': '暂时无法读取 API；请保留任务编号，稍后继续查询。'}, ensure_ascii=False))
        sys.exit(1)
