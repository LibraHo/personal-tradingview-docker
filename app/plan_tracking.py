"""Record only explicitly enabled, closed regular-session candles."""
import asyncio
import json
import logging
import math
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone

from . import ledger
from .plan_daily import LOOKBACK, ZONES, session
from .plan_follow import defense_value
from .indicators import calculate

LOG = logging.getLogger(__name__)


def slots(market, period, calendar):
    """Exchange session intervals; a shortened final candle closes at the session boundary."""
    result, groups = [], {}
    for day,kind in sorted(calendar.items()):
        if kind not in ('WHOLE','MORNING','AFTERNOON'):
            continue
        start,end = (int(x) for x in session(market,day,kind))
        if period in ('1w','1mo'):
            key = date.fromisoformat(day).isocalendar()[:2] if period=='1w' else day[:7]
            groups[key] = (groups.get(key,(start,))[0],end,day)
        elif period=='1d' or (market=='CN' and period=='240m'):
            result.append((start,end,day))
        else:
            spans = [(start,end)]
            if market=='CN' and kind=='WHOLE':
                spans = [(start,start+7200),(end-7200,end)]
            width = int(period[:-1])*60
            for a,b in spans:
                result.extend((s,min(s+width,b),day) for s in range(a,b,width))
    return list(groups.values()) if groups else result


def label_key(period, market, day, stamp):
    if period=='1w':
        return date.fromisoformat(day).isocalendar()[:2]
    if period=='1mo':
        return day[:7]
    return day if period=='1d' or (market=='CN' and period=='240m') else stamp


class Series:
    def __init__(self, market, period, grid, rows, mode):
        self.ends, self.bars, self.by_end = [], [], {}
        self.cache = {}
        self.indicators = {}
        self.grid_ends = [s[1] for s in grid]
        grid_close_times = set(self.grid_ends)
        closes = {label_key(period,market,d,a):b for a,b,d in grid}
        for r in sorted(rows,key=lambda item:item['time']):
            key = label_key(period,market,r['trade_date'],r['time'])
            end_label = r.get('bar_label') == 'end' and period.endswith('m') and not (market == 'CN' and period == '240m')
            if end_label:
                end = r['time'] if r['time'] in grid_close_times else None
            else:
                end = closes.get(key)
            if end is not None:
                self.by_end[end] = r
            elif r['trade_date'] < grid[0][2]:
                # Pre-calendar warm-up precedes every evaluation in the tracking window.
                end = r['time']
            elif mode!='regular' and period.endswith('m') and r.get('session')!='regular':
                if mode=='extended' and r.get('session')=='overnight':
                    continue
                end = r['time'] if end_label else r['time']+int(period[:-1])*60
            else:
                continue
            self.ends.append(end)
            self.bars.append(r)

    def level(self, version, stamp):
        count = bisect_right(self.ends,stamp)
        expected = bisect_right(self.grid_ends,stamp)
        if not count or not expected or self.grid_ends[expected-1] not in self.by_end:
            return None
        rule = version['details']['risk']['defense_reference']
        c = rule.get('condition')
        if c and c['source'] in ('SMA','EMA','BOLL','VWAP','BBI'):
            key = (c['source'],ledger.dump(c['params']),c['line'])
            if key not in self.indicators:
                self.indicators[key] = calculate(self.bars,c['source'],c['params'],
                                                 reset=c['params'].get('reset','session')).get(c['line'],[])
            values = self.indicators[key]
            value = values[count-1] if count<=len(values) else None
            return round(value,8) if value is not None and value>0 and math.isfinite(value) else None
        key = version['id'],version['revision'],count
        if key not in self.cache:
            self.cache[key] = defense_value(version,self.bars[:count])
        return self.cache[key]


def observe(market, version, slot, period, series, reference, previous):
    start,end,day = slot
    details = version['details']
    rule = (details.get('risk') or {}).get('defense_reference')
    target = (details.get('levels') or {}).get('take_profit')
    effective = datetime.fromisoformat(version['updated_at']).timestamp()
    full = effective <= start
    stop = version.get('stop') if full else None
    final_stop = version.get('stop')
    candle = series.by_end.get(end) if series else None
    if rule:
        final_stop = reference.level(version,end) if reference else None
        if full and previous and previous>=effective:
            stop = reference.level(version,start) if reference else None
    valid = candle and all(isinstance(candle.get(k),(int,float)) and math.isfinite(candle[k]) and candle[k]>0
                           for k in ('high','low','close')) and candle['low']<=candle['close']<=candle['high']
    high,low,close = (candle[k] for k in ('high','low','close')) if valid else (None,None,None)
    buy = version['side']=='BUY'
    error = None
    if not valid:
        error = '缺少已收盘的有效行情'
    elif rule and (final_stop is None or (full and stop is None)):
        error = '跟随点位数据不足'
    return dict(day=day,period=period,revision=version['revision'],symbol=version['symbol'],side=version['side'],
                open_time=start,close_time=end,session='regular',full_session=full,dynamic=bool(rule),reference=rule,
                low=low,high=high,close=close,open_stop=stop,close_stop=final_stop,take_profit=target,
                change=round(final_stop-stop,8) if final_stop is not None and stop is not None else None,
                stop_hit=(low<=stop if buy else high>=stop) if valid and full and stop is not None else None,
                profit_hit=(high>=target if buy else low<=target) if valid and full and target is not None else None,
                error=error,updated_at=ledger.now())


def summarize(rows):
    rows.sort(key=lambda r:r['close_time'])
    first,last = rows[0],rows[-1]
    valid = [r for r in rows if r['close'] is not None]
    def hits(field):
        values = [r[field] for r in rows]
        return True if True in values else None if None in values else False
    start,finish = first['open_stop'],last['close_stop']
    return {**last,'bar_count':len(rows),'incomplete_count':sum(bool(r['error']) for r in rows),
            'full_session':all(r['full_session'] for r in rows),
            'stop_hit':hits('stop_hit'),'profit_hit':hits('profit_hit'),
            'open_stop':start,'change':round(finish-start,8) if start is not None and finish is not None else None,
            'high':max((r['high'] for r in valid),default=None),'low':min((r['low'] for r in valid),default=None)}


def persist(connect, market, plan, rows, calendar, now):
    if not rows:
        return
    ident = plan['id']
    with ledger.transaction(connect,True) as db:
        current = db.execute('SELECT max(revision) FROM ledger_plans WHERE market=? AND id=?',(market,ident)).fetchone()[0]
        if current!=plan['revision']:
            return
        for row in rows:
            db.execute('INSERT OR REPLACE INTO ledger_plan_bars VALUES(?,?,?,?,?,?)',
                       (market,ident,row['close_time'],row['day'],row['next_retry'] or 0,ledger.dump(row)))
        for day in sorted({r['day'] for r in rows}):
            if now<session(market,day,calendar[day])[1]:
                continue
            history = [json.loads(r[0]) for r in db.execute('SELECT value FROM ledger_plan_bars WHERE market=? AND id=? AND day=?',
                                                            (market,ident,day))]
            if all(r['period'] in ('1w','1mo') for r in history):
                continue
            daily = summarize(history)
            db.execute('INSERT OR REPLACE INTO ledger_plan_daily VALUES(?,?,?,?)',(market,ident,day,ledger.dump(daily)))


def enabled_plans(connect):
    with ledger.transaction(connect) as db:
        rows = db.execute("""SELECT market,id FROM ledger_plans p WHERE
            revision=(SELECT max(revision) FROM ledger_plans WHERE id=p.id AND market=p.market)
            AND json_extract(value,'$.status')='active' AND json_extract(value,'$.details.tracking_period') IS NOT NULL""")
        return [(m,ledger.plan_record(db,m,i)) for m,i in rows]


class Tracker:
    def __init__(self, connect, calendar, load_bars):
        self.connect,self.calendar,self.load_bars = connect,calendar,load_bars
        self.calendars,self.calendar_retry = {},{}
        self.next_check = {}
        self.series_cache = {}

    async def sweep(self,clock=None):
        now = clock or datetime.now(timezone.utc)
        grids,feeds = {},{}
        plans = await asyncio.to_thread(enabled_plans,self.connect)
        active_symbols = {p['symbol'] for _,p in plans}
        self.series_cache = {key:value for key,value in self.series_cache.items() if key[0] in active_symbols}
        active_versions = {(p['id'],p['revision']) for _,p in plans}
        self.next_check = {key:value for key,value in self.next_check.items() if key in active_versions}
        for market,plan in plans:
            plan_key = (plan['id'],plan['revision'])
            if self.next_check.get(plan_key,0)>now.timestamp():
                continue
            today = now.astimezone(ZONES[market]).date()
            key = (market,today)
            if now.timestamp()<self.calendar_retry.get(key,0):
                continue
            if key not in self.calendars:
                try:
                    days = await asyncio.to_thread(self.calendar.days,plan['symbol'])
                    if not days:
                        raise ValueError('empty calendar')
                    self.calendars = {k:v for k,v in self.calendars.items() if k[0]!=market}
                    self.calendars[key] = days
                except Exception:
                    self.calendar_retry[key] = now.timestamp()+1800
                    for m,p in plans:
                        if m==market:
                            with ledger.transaction(self.connect,True) as db:
                                db.execute('INSERT OR REPLACE INTO ledger_plan_daily_status VALUES(?,?,?,?,?)',
                                           (m,p['id'],None,ledger.now(),'交易日历不可用，30 分钟后重试'))
                    continue
            days = self.calendars[key]
            def grid(period):
                if (market,period) not in grids:
                    grids[market,period] = slots(market,period,days)
                return grids[market,period]
            async def feed(period,mode,*,retry=False):
                feed_key = plan['symbol'],period,mode
                if feed_key not in feeds:
                    ends = [s[1] for s in grid(period)]
                    index = bisect_right(ends,now.timestamp()-5)-1
                    closed = ends[index] if index>=0 else None
                    cached = self.series_cache.get(feed_key)
                    if not retry and cached and cached[0]==closed:
                        feeds[feed_key] = cached[1]
                        return cached[1]
                    try:
                        response = await self.load_bars(*feed_key,limit=10000,refresh=True)
                        if response.get('stale') or response.get('revalidate'):
                            raise ValueError('stale')
                        feeds[feed_key] = Series(market,period,grid(period),response['bars'],mode)
                        if closed in feeds[feed_key].by_end:
                            self.series_cache[feed_key] = (closed,feeds[feed_key])
                    except Exception:
                        feeds[feed_key] = None
                return feeds[feed_key]
            try:
                await self.check(plan,market,today,now.timestamp(),days,grid,feed)
            except Exception:
                LOG.exception('Failed to track plan %s',plan['id'])

    async def check(self,plan,market,today,now,days,grid,feed):
        versions = plan['history']
        stamps = [datetime.fromisoformat(v['updated_at']).timestamp() for v in versions]
        periods = {(v.get('details') or {}).get('tracking_period') for v in versions if v['status']=='active'}-{None}
        cutoff = str(today-timedelta(days=LOOKBACK))
        with ledger.transaction(self.connect) as db:
            states = {r[0]:(r[1],r[2]) for r in db.execute("""SELECT end,retry_at,json_extract(value,'$.attempts')
                FROM ledger_plan_bars WHERE market=? AND id=? AND day>=?""",(market,plan['id'],cutoff))}
        pending = []
        upcoming = []
        for period in periods:
            prev = None
            for slot in grid(period):
                start,end,day = slot
                previous,prev = prev,end
                if day<cutoff:
                    continue
                idx = bisect_left(stamps,end)-1
                if idx<0:
                    continue
                version = versions[idx]
                if version['status']!='active' or (version.get('details') or {}).get('tracking_period')!=period:
                    continue
                if end+5>now:
                    upcoming.append(end+5)
                    break
                state = states.get(end)
                if state and (not state[0] or state[0]>now):
                    if state[0]:
                        upcoming.append(state[0])
                    continue
                pending.append((slot,period,version,previous,state))
        plan_key = plan['id'],plan['revision']
        if not pending:
            self.next_check[plan_key] = min(upcoming, default=now+86400)
            return
        rows = []
        for slot,period,version,previous,state in sorted(pending,key=lambda p:p[0][1]):
            series = await feed(period,'regular',retry=bool(state))
            details = version['details']
            rule = (details.get('risk') or {}).get('defense_reference')
            ref = None
            if rule:
                ref_period = rule['period']
                mode = 'regular' if market=='CN' or not ref_period.endswith('m') else details.get('mode','regular')
                ref = await feed(ref_period,mode,retry=bool(state))
            row = await asyncio.to_thread(observe,market,version,slot,period,series,ref,previous)
            attempts = 1+(state[1] if state else 0)
            row.update(attempts=attempts,next_retry=None)
            if row['error']:
                delay = (300,1800,7200,86400)[min(attempts-1,3)]
                if period in ('1d','1w','1mo'):
                    # Coalesce failed long-period checks with the next trading day's close.
                    next_sessions = [int(session(market,d,k)[1])+5 for d,k in days.items() if d>str(today)
                                     and k in ('WHOLE','MORNING','AFTERNOON')]
                    delay = max(60,min(next_sessions, default=int(now)+86400)-int(now))
                row['next_retry'] = int(now)+delay
                upcoming.append(row['next_retry'])
            rows.append(row)
        await asyncio.to_thread(persist,self.connect,market,plan,rows,days,now)
        self.next_check[plan_key] = min(upcoming, default=now+86400)
        with ledger.transaction(self.connect,True) as db:
            if db.execute('SELECT 1 FROM ledger_plans WHERE market=? AND id=?',(market,plan['id'])).fetchone():
                db.execute('INSERT OR REPLACE INTO ledger_plan_daily_status VALUES(?,?,?,?,?)',
                           (market,plan['id'],max(r['day'] for r in rows),ledger.now(),None))

