#!/usr/bin/env python3
"""NAS Market review client. The credential is read from a private file."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import ssl
import sys
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call(path, market, method='GET', body=None):
    base = os.environ.get('NAS_MARKET_API_URL', 'http://market:8000').rstrip('/')
    default_token = Path.home() / '.openclaw/credentials/nas-market-review-token'
    token = Path(os.environ.get('NAS_MARKET_REVIEW_TOKEN_FILE', str(default_token))).read_text().strip()
    separator = '&' if '?' in path else '?'
    req = Request(f'{base}/api/v1/review/{path}{separator}{urlencode({"market": market})}',
                  data=json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None,
                  method=method, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    if base == 'http://market:8000':
        # The scoped review token is for the NAS service on the shared Docker network.
        connection = build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=30)
    else:
        context = ssl.create_default_context(cafile=os.environ.get('NAS_MARKET_CA_FILE') or None)
        connection = urlopen(req, timeout=30, context=context)
    with connection as response:
        return json.load(response)


def sync_day(market, day, fields, expected_revision=None):
    path = f'days/{day}'
    if not isinstance(fields, dict) or not fields or 'revision' in fields:
        raise ValueError('请提供需要同步的日记字段。版本由客户端读取。')
    if expected_revision is not None:
        return call(path, market, 'PATCH', {'revision': expected_revision, **fields})
    try:
        existing = call(path, market)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        existing = None
    revision = existing['revision'] if existing else 0
    if existing:
        comparable = {**existing, 'violations': [item['id'] for item in existing['violations']]}
        if isinstance(fields.get('symbols'), list) and all(isinstance(item, dict) and 'symbol' in item for item in fields['symbols']):
            fields = {**fields, 'symbols': [{'name': '', 'note': '', **item, 'symbol': str(item['symbol']).strip().upper()} for item in fields['symbols']]}
        if fields.keys() <= {'traded', 'violations', 'symbols', 'context', 'reason', 'lesson', 'plan'} and all(
                comparable[key] == value for key, value in fields.items()):
            return existing
    return call(path, market, 'PATCH', {'revision': revision, **fields})


LEDGER_COMMANDS = {
    'book': ('GET', 'book'), 'plan': ('GET', 'plans/{id}'), 'fill': ('GET', 'fills/{id}'),
    'plan-bars': ('GET', 'plans/{id}/bars'),
    'plan-daily': ('GET', 'plans/{id}/daily'),
    'add-plan': ('POST', 'plans'), 'update-plan': ('PUT', 'plans/{id}'),
    'delete-plan': ('DELETE', 'plans/{id}'),
    'link-plan-fill': ('PUT', 'plans/{id}/fills/{fill_id}'),
    'unlink-plan-fill': ('DELETE', 'plans/{id}/fills/{fill_id}'),
    'add-fill': ('POST', 'fills'), 'review-fill': ('PUT', 'fills/{id}/review'),
    'sync-positions': ('POST', 'positions'), 'reconcile': ('POST', 'reconcile'),
    'backlinks': ('GET', 'backlinks'), 'opend': ('GET', 'opend'), 'sync-opend': ('POST', 'opend/sync'),
}


def ledger_command(args):
    method, route = LEDGER_COMMANDS[args.command]
    params = {}
    if '{id}' in route or args.command == 'backlinks':
        if not re.fullmatch(r'[a-f0-9]{32}', args.id or ''):
            raise ValueError('需要传入档案返回的 --id')
        if '{fill_id}' in route and not re.fullmatch(r'[a-f0-9]{32}', args.fill_id or ''):
            raise ValueError('需要传入成交档案返回的 --fill-id')
        route = route.format(id=args.id, fill_id=args.fill_id)
    if args.command == 'backlinks':
        if not args.kind:
            raise ValueError('请指定 --kind plan 或 --kind fill')
        params.update(kind=args.kind, id=args.id)
    elif args.command in ('plan-daily','plan-bars'):
        params['limit'] = args.limit
        if args.before:
            params['before'] = int(args.before) if args.command=='plan-bars' else date.fromisoformat(args.before).isoformat()
    elif args.command == 'book':
        params.update(limit=args.limit, offset=args.offset)
        if args.symbol:
            params['symbol'] = args.symbol.upper()
    elif args.command in ('sync-opend', 'opend'):
        if args.market != 'US':
            raise ValueError('OpenD 成交同步仅适用于 US')
        if args.command == 'sync-opend' and (args.start or args.end):
            if not (args.start and args.end):
                raise ValueError('请同时提供 --start 和 --end')
            params.update(start=args.start, end=args.end)
    body = None
    if method != 'GET' and args.command not in ('sync-opend', 'delete-plan'):
        if args.command == 'add-fill' and args.market == 'US' and not args.manual:
            raise ValueError('美股默认读取 OpenD。用户明确要求补录时才使用 --manual')
        sys.stdin.reconfigure(encoding='utf-8')
        body = json.load(sys.stdin)
        if not isinstance(body, dict):
            raise ValueError('请通过标准输入传入 JSON 对象')
        if args.command == 'add-fill' and args.market == 'US':
            body['manual_confirm'] = True
        if args.command == 'add-fill' and (args.image or args.image_sha256 or args.row is not None):
            if not (args.image or args.image_sha256) or not args.row or args.row < 1:
                raise ValueError('截图成交需要提供原图或 SHA-256，以及从 1 起计的原图行号')
            if args.image:
                image_digest = hashlib.sha256()
                with Path(args.image).open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        image_digest.update(chunk)
                image_hash = image_digest.hexdigest()
            else:
                image_hash = args.image_sha256.lower()
            if not re.fullmatch('[0-9a-f]{64}', image_hash):
                raise ValueError('截图 SHA-256 格式不正确')
            key = json.dumps([str(body.get('account', '')).strip(), image_hash, args.row],ensure_ascii=False)
            body.update(source='screenshot',request_id='image-'+hashlib.sha256(key.encode()).hexdigest())
    path = 'ledger/' + route + ('?' + urlencode(params) if params else '')
    return call(path, args.market, method, body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('rules', 'dashboard', 'day', 'days', 'week', 'sync-day', 'export', *LEDGER_COMMANDS))
    parser.add_argument('--market', choices=('CN', 'US'), required=True)
    parser.add_argument('--day', help='YYYY-MM-DD in the market timezone')
    parser.add_argument('--revision', type=int, help='Require a previously read revision when appending to an existing list')
    parser.add_argument('--id')
    parser.add_argument('--before', help='Read daily records strictly before YYYY-MM-DD')
    parser.add_argument('--fill-id', help='Existing fill ID for plan association')
    parser.add_argument('--kind', choices=('plan', 'fill'))
    parser.add_argument('--symbol')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--manual', action='store_true', help='User explicitly requested a US manual fill')
    evidence = parser.add_mutually_exclusive_group()
    evidence.add_argument('--image', help='Local attachment path for stable screenshot fill identity')
    evidence.add_argument('--image-sha256', help='SHA-256 of original attachment bytes')
    parser.add_argument('--row', type=int, help='One-based fill row number in the original screenshot')
    args = parser.parse_args()
    day = args.day or datetime.now(ZoneInfo('Asia/Shanghai' if args.market == 'CN' else 'America/New_York')).date().isoformat()
    paths = {'dashboard': 'dashboard?' + urlencode({'day': day}), 'day': f'days/{day}', 'week': f'weeks/{day}'}
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('日期须为 YYYY-MM-DD')
        if args.command in LEDGER_COMMANDS:
            result = ledger_command(args)
        elif args.command == 'sync-day':
            sys.stdin.reconfigure(encoding='utf-8')
            result = sync_day(args.market, day, json.load(sys.stdin), args.revision)
        else:
            result = call(paths.get(args.command, args.command), args.market)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HTTPError as exc:
        try:
            detail = json.load(exc).get('detail')
        except (ValueError, AttributeError):
            detail = '服务器没有返回错误详情'
        print(json.dumps({'status': exc.code, 'detail': detail}, ensure_ascii=False), file=sys.stderr)
    except (OSError, URLError, ValueError) as exc:
        print(json.dumps({'detail': str(exc)}, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
