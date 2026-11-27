"""Durable, channel-independent delivery of scanner events. No market subscriptions."""
import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo


class Rejected(Exception):
    """The provider explicitly rejected this request (safe to retry)."""


def send_webhook(credentials, message, config):
    payload = {**config.get('extra_fields', {}), config['title_field']:message['title'], config['body_field']:message['body']}
    if config['format']=='form':
        data = urllib.parse.urlencode(payload).encode()
        content_type = 'application/x-www-form-urlencoded; charset=utf-8'
    else:
        data = json.dumps(payload, ensure_ascii=False).encode()
        content_type = 'application/json; charset=utf-8'
    request = urllib.request.Request(credentials['url'], data=data, method='POST',
                                     headers={**credentials['headers'], 'Content-Type':content_type})
    # URLs and headers may contain credentials. Never redirect or log them.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=15) as response:
        if not config['success_field']:
            return
        result = json.loads(response.read(65536))
    for key in config['success_field'].split('.'):
        if not isinstance(result,dict) or key not in result:
            raise ValueError('missing acknowledgement field')
        result = result[key]
    if str(result).lower() != config['success_value'].lower():
        raise Rejected('响应字段与配置的成功值不符')


def format_event(event):
    confirmation = '收盘确认' if event.get('confirmation') == 'confirmed' else '盘中预览'
    title = f"NAS Market · {event.get('symbol', '')} · {confirmation}"[:100]
    def stamp(value):
        try:
            return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError, OverflowError, OSError):
            return str(value or '—')[:100]
    body = (f"### {event.get('name') or event.get('symbol', '')}\n\n"
            f"标的：{event.get('symbol', '')} · 周期：{event.get('period', '')}\n\n"
            f"状态：{confirmation}\n\nK 线时间（北京时间）：{stamp(event.get('time'))}\n\n"
            f"检测时间（北京时间）：{stamp(event.get('detected_at'))}\n\n"
            f"监控：{event.get('monitor_name') or event.get('monitor_id', '')}\n\n"
            f"事件：{event.get('event_id', '')}")
    link = event.get('chart_url', '')
    if isinstance(link, str) and link.startswith('https://'):
        body += f'\n\n图表：{link}\n\n图表地址可能需要连接家庭网络。'
    return {'title':title, 'body':body[:12000]}


class Notifications:
    def __init__(self, db):
        self.db = db

    def init(self, recover=False):
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS notification_channels(
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, secret TEXT NOT NULL,
                cursor INTEGER NOT NULL, last_attempt REAL NOT NULL DEFAULT 0,
                budget_day TEXT NOT NULL DEFAULT '', budget_used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS notification_outbox(
                id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, event_id TEXT NOT NULL,
                message TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL,
                error TEXT NOT NULL DEFAULT '', UNIQUE(channel_id,event_id));
            CREATE INDEX IF NOT EXISTS notification_due ON notification_outbox(status,next_attempt);
            CREATE INDEX IF NOT EXISTS notification_history ON notification_outbox(created DESC);
            ''')
            # A crash after sending but before committing acknowledgement is ambiguous.
            if recover:
                db.execute("UPDATE notification_outbox SET status='unknown',error='服务中断，无法确认接收端是否接收；请核对后再处理' WHERE status='sending'")
                # Older workers could queue a retry after its subscription changed.
                db.execute("""UPDATE notification_outbox AS o SET status='cancelled',updated=?
                    WHERE o.status='retry' AND o.event_id NOT LIKE 'test:%' AND NOT EXISTS (
                      SELECT 1 FROM notification_channels c JOIN scan_events e ON e.event_id=o.event_id
                      WHERE c.id=o.channel_id AND json_extract(c.payload,'$.enabled')=1
                      AND e.monitor_id IN (SELECT value FROM json_each(c.payload,'$.monitor_ids'))
                      AND json_extract(c.payload,'$.confirmation') IN ('all',json_extract(e.payload,'$.confirmation'))
                    )""", (time.time(),))

    @staticmethod
    def public(row):
        credentials = json.loads(row['secret'])
        payload = json.loads(row['payload'])
        payload.pop('routing_revision', None)
        return {**payload, 'has_url':bool(credentials['url']), 'has_headers':bool(credentials['headers'])}

    def channels(self):
        with self.db() as db:
            return [self.public(r) for r in db.execute('SELECT * FROM notification_channels ORDER BY rowid')]

    def monitors(self):
        with self.db() as db:
            return [{k:v.get(k) for k in ('id','name','enabled','interval_seconds','schedule')}
                    for r in db.execute('SELECT payload FROM scan_monitors') for v in [json.loads(r[0])]]

    def save(self, body, ident=None):
        name = str(body.get('name', '')).strip()
        monitors = body.get('monitor_ids', [])
        confirmation = body.get('confirmation', 'confirmed')
        limit = body.get('daily_limit', 100)
        encoding = body.get('format','json')
        title_field, body_field = body.get('title_field','title'), body.get('body_field','body')
        success_field, success_value = body.get('success_field',''), body.get('success_value','')
        extra_fields = body.get('extra_fields',{})
        if (not name or len(name)>80 or not isinstance(monitors,list) or len(monitors)>100
                or any(not isinstance(v,str) for v in monitors)
                or confirmation not in ('confirmed','preview','all')
                or type(limit) is not int or not 1<=limit<=1000 or type(body.get('enabled',False)) is not bool):
            raise ValueError('通知配置无效')
        if (encoding not in ('json','form') or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',v) for v in (title_field,body_field))
                or title_field==body_field or not isinstance(success_field,str) or len(success_field)>100
                or (success_field and not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*',success_field))
                or not isinstance(success_value,str) or len(success_value)>100
                or not isinstance(extra_fields,dict) or len(extra_fields)>20
                or any(not isinstance(k,str) or len(k)>64 or not isinstance(v,str) or len(v)>2000 for k,v in extra_fields.items())):
            raise ValueError('请求格式、消息字段或成功条件无效')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM notification_channels WHERE id=?', (ident,)).fetchone() if ident else None
            if ident and not previous:
                raise KeyError(ident)
            old_credentials = json.loads(previous['secret']) if previous else {'url':'','headers':{}}
            url = body.get('url') or old_credentials['url']
            headers = body.get('headers') if body.get('headers') is not None else old_credentials['headers']
            try:
                parsed = urllib.parse.urlsplit(url)
                valid = parsed.scheme in ('https','http') and parsed.hostname and not (parsed.username or parsed.password or parsed.fragment)
                _ = parsed.port
                valid = valid and url.isascii() and not any(ord(c)<33 or ord(c)>126 for c in url)
            except (ValueError, TypeError):
                valid = False
            if not valid or len(url)>4096:
                raise ValueError('请填写有效的 HTTP 或 HTTPS 请求地址；中文参数需 URL 编码')
            if (not isinstance(headers,dict) or len(headers)>20 or any(
                    not re.fullmatch(r'[A-Za-z0-9-]{1,80}',k) or not isinstance(v,str) or len(v)>4096
                    or not v.isascii() or any(ord(c)<32 or ord(c)>126 for c in v)
                    or k.lower() in ('host','content-length','connection','transfer-encoding') for k,v in headers.items())):
                raise ValueError('请求头格式无效')
            # Changing destinations must not forward the old destination\'s token.
            if url!=old_credentials['url'] and old_credentials['url'] and body.get('headers') is None and headers:
                raise ValueError('修改地址时请重新填写请求头，或填 {} 清空')
            secret = json.dumps({'url':url,'headers':headers})
            available = {r[0] for r in db.execute('SELECT id FROM scan_monitors')}
            if set(monitors)-available:
                raise ValueError('所选监控已不存在，请重新读取')
            ident = ident or uuid.uuid4().hex
            value = {'id':ident, 'name':name, 'enabled':body.get('enabled',False),
                     'monitor_ids':list(dict.fromkeys(monitors)), 'confirmation':confirmation, 'daily_limit':limit,
                     'format':encoding,'title_field':title_field,'body_field':body_field,
                     'success_field':success_field,'success_value':success_value,'extra_fields':extra_fields}
            cursor = db.execute('SELECT COALESCE(MAX(cursor),0) FROM scan_events').fetchone()[0]
            # Preserve old routing when only display name/limit/credential changes.
            routing = ('enabled','monitor_ids','confirmation')
            old_value = json.loads(previous['payload']) if previous else {}
            changed = previous is not None and any(old_value[k]!=value[k] for k in routing)
            stored = {**value, 'routing_revision':old_value.get('routing_revision', 0) + int(changed)}
            if previous:
                db.execute('UPDATE notification_channels SET payload=?,secret=?,cursor=? WHERE id=?',
                           (json.dumps(stored),secret,cursor if changed else previous['cursor'],ident))
                if changed:
                    db.execute("UPDATE notification_outbox SET status='cancelled',updated=? WHERE channel_id=? AND status IN ('pending','retry')", (time.time(),ident))
            else:
                db.execute('INSERT INTO notification_channels(id,payload,secret,cursor) VALUES(?,?,?,?)', (ident,json.dumps(stored),secret,cursor))
        return {**value, 'has_url':True, 'has_headers':bool(headers)}

    def delete(self, ident):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('DELETE FROM notification_channels WHERE id=?', (ident,)).rowcount:
                raise KeyError(ident)
            db.execute("UPDATE notification_outbox SET status='cancelled',updated=? WHERE channel_id=? AND status IN ('pending','retry')", (time.time(),ident))

    @staticmethod
    def enqueue(db, channel, event_id, message):
        now = time.time()
        ident = uuid.uuid4().hex
        db.execute("INSERT OR IGNORE INTO notification_outbox(id,channel_id,event_id,message,status,created,updated) VALUES(?,?,?,?,'pending',?,?)",
                   (ident,channel,event_id,json.dumps(message,ensure_ascii=False),now,now))
        return ident

    def test(self, ident):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM notification_channels WHERE id=?', (ident,)).fetchone():
                raise KeyError(ident)
            recent = db.execute("SELECT 1 FROM notification_outbox WHERE channel_id=? AND event_id LIKE 'test:%' AND (created>? OR status IN ('pending','retry','sending'))", (ident,time.time()-30)).fetchone()
            if recent:
                raise ValueError('测试已排队或刚刚发送，请稍后查看记录')
            return self.enqueue(db,ident,'test:'+uuid.uuid4().hex,
                                {'title':'NAS Market · 通知测试','body':'这是你在 NAS Market 设置页发起的测试消息。收到后即可启用所选监控的通知。'})

    def collect(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT * FROM notification_channels').fetchall():
                channel = json.loads(row['payload'])
                if not channel['enabled']:
                    continue
                events = db.execute('SELECT cursor,payload FROM scan_events WHERE cursor>? ORDER BY cursor LIMIT 500', (row['cursor'],)).fetchall()
                for event_row in events:
                    event = json.loads(event_row['payload'])
                    if event.get('monitor_id') in channel['monitor_ids'] and channel['confirmation'] in ('all',event.get('confirmation')):
                        self.enqueue(db,channel['id'],event['event_id'],format_event(event))
                if events:
                    db.execute('UPDATE notification_channels SET cursor=? WHERE id=?', (events[-1]['cursor'],channel['id']))

    def deliver_one(self):
        now = time.time()
        day = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai')).date().isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("""SELECT o.*,c.payload,c.secret,c.budget_day,c.budget_used
                FROM notification_outbox o JOIN notification_channels c ON c.id=o.channel_id
                WHERE o.status IN ('pending','retry') AND o.next_attempt<=? AND c.last_attempt<=?
                AND (c.budget_day<>? OR c.budget_used<json_extract(c.payload,'$.daily_limit'))
                AND (json_extract(c.payload,'$.enabled')=1 OR o.event_id LIKE 'test:%')
                ORDER BY o.created LIMIT 1""", (now,now-2,day)).fetchone()
            if row is None:
                return
            channel = json.loads(row['payload'])
            used = row['budget_used'] if row['budget_day']==day else 0
            db.execute("UPDATE notification_outbox SET status='sending',attempts=attempts+1,updated=? WHERE id=?", (now,row['id']))
            db.execute('UPDATE notification_channels SET last_attempt=?,budget_day=?,budget_used=? WHERE id=?', (now,day,used+1,row['channel_id']))
        attempts = row['attempts']+1
        status, error, due = 'accepted', '', 0
        try:
            send_webhook(json.loads(row['secret']),json.loads(row['message']),channel)
        except Rejected as exc:
            status = 'retry' if attempts<3 else 'failed'
            error, due = str(exc), now+60*attempts
        except urllib.error.HTTPError as exc:
            status = 'retry' if attempts<3 and exc.code in (429,502,503,504) else 'failed'
            error, due = '接收端 HTTP 错误（%s）' % exc.code, now+60*attempts
        except Exception:
            # A lost response does not prove a failed send. Avoid duplicate alerts.
            status, error = 'unknown', '请求结果未确认，请在接收端核对；未自动重发'
        with self.db() as db:
            if status == 'retry':
                db.execute('BEGIN IMMEDIATE')
                current = db.execute("SELECT coalesce(json_extract(payload,'$.routing_revision'),0) FROM notification_channels WHERE id=?",
                                     (row['channel_id'],)).fetchone()
                if current is None or current[0] != channel.get('routing_revision',0):
                    status, error, due = 'cancelled', '订阅已更改，已取消重试', 0
            db.execute('UPDATE notification_outbox SET status=?,error=?,next_attempt=?,updated=? WHERE id=?', (status,error,due,time.time(),row['id']))

    def records(self):
        with self.db() as db:
            return [{k:r[k] for k in ('id','channel_id','event_id','status','attempts','created','updated','error')}
                    for r in db.execute('SELECT * FROM notification_outbox ORDER BY created DESC LIMIT 100')]

    async def run(self):
        self.init(recover=True)
        while True:
            try:
                await asyncio.to_thread(self.collect)
                await asyncio.to_thread(self.deliver_one)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.error('Notification worker cycle failed; will retry')
            await asyncio.sleep(2)
