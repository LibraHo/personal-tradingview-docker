#!/usr/bin/env python3
"""Standard-library client for NAS Market drawing objects. Never submits trades."""
import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['capabilities', 'list', 'create', 'update', 'delete', 'visibility'])
    parser.add_argument('--symbol')
    parser.add_argument('--period', choices=['1m','5m','15m','30m','60m','1d','1w','1mo'])
    parser.add_argument('--kind', choices=['horizontal','trend','fib'])
    parser.add_argument('--id')
    parser.add_argument('--json', help='JSON object, or @path/to/file.json; create fields exclude symbol/period/kind')
    parser.add_argument('--revision', type=int, help='Optional revision for If-Match conflict protection')
    args = parser.parse_args()
    try:
        token = os.getenv('NAS_MARKET_DRAWING_TOKEN')
        if not token:
            token = Path(os.getenv('NAS_MARKET_DRAWING_TOKEN_FILE', '/run/secrets/nas_market_drawing_token')).read_text().strip()
        base = os.getenv('NAS_MARKET_URL', 'https://192.168.101.103:8443').rstrip('/')
        if urllib.parse.urlsplit(base).scheme not in ('http', 'https'):
            raise ValueError('NAS_MARKET_URL must be http:// or https://')
        body = None
        if args.json:
            body = json.loads(Path(args.json[1:]).read_text(encoding='utf-8') if args.json.startswith('@') else args.json)
            if not isinstance(body, dict):
                raise ValueError('--json must contain a JSON object')
        path, method = '/api/drawings/capabilities', 'GET'
        query = {k: v for k, v in {'symbol': args.symbol, 'period': args.period}.items() if v}
        if args.command != 'capabilities':
            path = '/api/drawings/objects'
            if args.command == 'list':
                if query:
                    path += '?' + urllib.parse.urlencode(query)
            elif args.command in ('create', 'visibility'):
                if not args.symbol or not args.period or body is None:
                    raise ValueError('symbol, period and --json are required')
                body.update(query)
                if args.command == 'create':
                    if not args.kind:
                        raise ValueError('--kind is required')
                    body['kind'] = args.kind
                    if args.id:
                        body['id'] = args.id
                    method = 'POST'
                else:
                    path, method = '/api/drawings/visibility', 'PUT'
            else:
                if not args.id or not args.symbol or not args.period or not args.kind:
                    raise ValueError('id, symbol, period and kind are required')
                query['kind'] = args.kind
                path += '/' + urllib.parse.quote(args.id, safe='') + '?' + urllib.parse.urlencode(query)
                method = 'PATCH' if args.command == 'update' else 'DELETE'
                if method == 'PATCH' and body is None:
                    raise ValueError('--json is required')
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        if args.revision is not None:
            headers['If-Match'] = str(args.revision)
        payload = json.dumps(body, allow_nan=False).encode() if body is not None else None
        request = urllib.request.Request(base + path, data=payload, method=method, headers=headers)
        context = ssl.create_default_context(cafile=os.getenv('NAS_MARKET_CA_FILE') or None)
        with urllib.request.urlopen(request, context=context, timeout=15) as response:
            print(json.dumps(json.load(response), ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        print('Drawing API HTTP ' + str(exc.code) + ': ' + exc.read(4096).decode(errors='replace'), file=sys.stderr)
        return 1
    except (OSError, ValueError, urllib.error.URLError):
        print('Drawing API connection/configuration failed. Check URL, token file, CA certificate and JSON fields.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
