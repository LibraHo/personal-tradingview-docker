"""Post-close observations for journal plans. Never places or modifies an order."""
import asyncio
import logging
import json
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import ledger
from .plan_follow import defense_value

LOG = logging.getLogger(__name__)
ZONES = {'CN': ZoneInfo('Asia/Shanghai'), 'US': ZoneInfo('America/New_York')}
LOOKBACK = 30


def session(market, day, kind):
    zone = ZONES[market]
    opening = time(9,30) if kind != 'AFTERNOON' else time(13)
    closing = (time(11,30) if kind=='MORNING' else time(15)) if market=='CN' else time(13 if kind=='MORNING' else 16)
    d = date.fromisoformat(day)
    return tuple(datetime.combine(d,t,zone).timestamp() for t in (opening,closing))


def reference_slice(rows, period, market, days, day):
    """Use completed candles through the regular-session close; reject a stale final period."""
    cutoff = session(market,day,days[day])[1]
    def bucket(d):
        if period == '1w':
            return date.fromisoformat(d).isocalendar()[:2]
        if period == '1mo':
            return d[:7]
        return d
    if period in ('1w','1mo'):
        # Determine completion from the full calendar, including future sessions.
        ends = {}
        for d in sorted(days):
            ends[bucket(d)] = d
        expected = max((d for d in ends.values() if d <= day),default=None)
        subset = [b for b in rows if ends.get(bucket(b['trade_date']),b['trade_date'])<=day]
        return subset if expected and subset and bucket(subset[-1]['trade_date'])==bucket(expected) else []
    if period=='1d' or (market=='CN' and period=='240m'):
        subset = [b for b in rows if b['trade_date']<=day]
        return subset if subset and subset[-1]['trade_date']==day else []
    span = int(period[:-1])*60
    subset = [b for b in rows if b['time'] < cutoff and
              (b.get('mode','regular')=='regular' or b['time']+span<=cutoff)]
    if not subset or subset[-1]['trade_date']!=day or subset[-1]['time']+span < cutoff:
        return []
    return subset


def observation(plan, market, day, days, daily, refs, previous, prior_record=None):
    opening,closing = session(market,day,days[day])
    effective = datetime.fromisoformat(plan['updated_at']).timestamp()
    details = plan.get('details') or {}
    rule = (details.get('risk') or {}).get('defense_reference')
    target = (details.get('levels') or {}).get('take_profit')
    stop = close_stop = plan.get('stop')
    if rule:
        period = rule['period']
        close_stop = defense_value(plan,reference_slice(refs,period,market,days,day))
        if previous and effective <= session(market,previous,days[previous])[1]:
            if prior_record and prior_record['revision']==plan['revision'] and prior_record['close_stop'] is not None:
                stop = prior_record['close_stop']
            else:
                stop = defense_value(plan,reference_slice(refs,period,market,days,previous))
    full_session = effective <= opening
    if not full_session:
        stop = None
    low,high = daily['low'],daily['high']
    buy = plan['side']=='BUY'
    stop_hit = (low<=stop if buy else high>=stop) if full_session and stop is not None else None
    target_hit = (high>=target if buy else low<=target) if full_session and target is not None else None
    return dict(day=day,revision=plan['revision'],symbol=plan['symbol'],side=plan['side'],
                session='regular',close_time=int(closing),open_stop=stop,close_stop=close_stop,
                take_profit=target,low=low,high=high,close=daily['close'],stop_hit=stop_hit,
                profit_hit=target_hit,full_session=full_session,dynamic=bool(rule),
                change=round(close_stop-stop,8) if close_stop is not None and stop is not None else None,
                reference=rule,updated_at=ledger.now())


def store_day(connect,market,ident,record,expected_revision):
    with ledger.transaction(connect,True) as db:
        if not db.execute('SELECT 1 FROM ledger_plans WHERE market=? AND id=? AND revision=?',
                          (market,ident,expected_revision)).fetchone():
            return
        prior = db.execute('SELECT value FROM ledger_plan_daily WHERE market=? AND id=? AND day=?',
                           (market,ident,record['day'])).fetchone()
        if prior:
            saved = json.loads(prior[0])
            if saved['revision']==record['revision']:
                for key in ('open_stop','close_stop','stop_hit'):
                    if record[key] is None:
                        record[key] = saved[key]
                if record['close_stop'] is not None and record['open_stop'] is not None:
                    record['change'] = round(record['close_stop']-record['open_stop'],8)
        db.execute('INSERT OR REPLACE INTO ledger_plan_daily VALUES(?,?,?,?)',
                   (market,ident,record['day'],ledger.dump(record)))


def report(connect,market,ident,expected,error):
    with ledger.transaction(connect,True) as db:
        if db.execute('SELECT 1 FROM ledger_plans WHERE market=? AND id=?',(market,ident)).fetchone():
            db.execute('INSERT OR REPLACE INTO ledger_plan_daily_status VALUES(?,?,?,?,?)',
                       (market,ident,expected,ledger.now(),error))


async def sweep(connect, calendar, load_bars, clock=None, *, long_only=False):
    now = clock or datetime.now(timezone.utc)
    calendars, cache = {}, {}
    async def history(symbol,period,mode):
        key = symbol,period,mode
        if key not in cache:
            window = {} if period in ('1d','1w','1mo','240m','120m','60m') else {'days': LOOKBACK+10}
            response = await load_bars(symbol,period,mode,limit=10000,refresh=True,**window)
            if response.get('stale') or response.get('revalidate'):
                raise ValueError('行情尚未更新，等待重试')
            cache[key] = sorted(response['bars'],key=lambda b:b['time'])
        return cache[key]
    from .plan_tracking import enabled_plans
    for market,plan in await asyncio.to_thread(enabled_plans,connect):
        versions = plan['history']
        if long_only and (plan.get('details') or {}).get('tracking_period') not in ('1w','1mo'):
            continue
        ident,symbol = plan['id'],plan['symbol']
        expected = None
        try:
            if market not in calendars:
                calendars[market] = await asyncio.to_thread(calendar.days,symbol)
            days = calendars[market]
            ordered = sorted(d for d,k in days.items() if k in ('WHOLE','MORNING','AFTERNOON'))
            today = now.astimezone(ZONES[market]).date()
            stamps = [datetime.fromisoformat(v['updated_at']).timestamp() for v in versions]
            with ledger.transaction(connect) as db:
                complete = {r[0] for r in db.execute("""SELECT day FROM ledger_plan_daily WHERE market=? AND id=?
                    AND (json_extract(value,'$.dynamic')=0 OR
                    (json_extract(value,'$.close_stop') IS NOT NULL AND (json_extract(value,'$.open_stop') IS NOT NULL OR json_extract(value,'$.full_session')=0)))""",(market,ident))}
            missing = []
            for i,day in enumerate(ordered):
                if not today-timedelta(days=LOOKBACK) <= date.fromisoformat(day) <= today:
                    continue
                end = session(market,day,days[day])[1]
                index = bisect_right(stamps,end)-1
                if now.timestamp()<end+600 or index<0 or versions[index]['status']!='active':
                    continue
                track = (versions[index].get('details') or {}).get('tracking_period')
                if not track or (long_only and track not in ('1w','1mo')):
                    continue
                expected = day
                if day not in complete:
                    missing.append((day,versions[index],ordered[i-1] if i else None))
            if not missing:
                continue
            daily = {b['trade_date']:b for b in await history(symbol,'1d','regular')}
            issues = []
            for day,version,previous in missing:
                if day not in daily:
                    issues.append(day+' 缺少日线')
                    continue
                details = version.get('details') or {}
                rule = (details.get('risk') or {}).get('defense_reference')
                refs = []
                if rule:
                    period = rule['period']
                    mode = 'regular' if market=='CN' or period in ('1d','1w','1mo') else details.get('mode','regular')
                    try:
                        refs = await history(symbol,period,mode)
                    except Exception:
                        refs = []
                    refs = [b for b in refs if mode=='all' or b.get('session')=='regular' or
                            (mode=='extended' and b.get('session') in ('pre','post'))]
                with ledger.transaction(connect) as db:
                    prior = db.execute('SELECT value FROM ledger_plan_daily WHERE market=? AND id=? AND day=?',
                                       (market,ident,previous)).fetchone()
                row = await asyncio.to_thread(observation,version,market,day,days,daily[day],refs,previous,
                                              json.loads(prior[0]) if prior else None)
                await asyncio.to_thread(store_day,connect,market,ident,row,plan['revision'])
                if rule and (row['close_stop'] is None or (row['full_session'] and row['open_stop'] is None)):
                    issues.append(day+' 跟随点位待确认')
            report(connect,market,ident,expected,'、'.join(issues) or None)
        except Exception as exc:
            LOG.warning('Plan daily check %s failed (%s)',ident,type(exc).__name__)
            report(connect,market,ident,expected,'行情或交易日历暂不可用，等待重试')


async def run(connect,calendar,load_bars):
    from .plan_tracking import Tracker
    tracker = Tracker(connect,calendar,load_bars)
    loop = asyncio.get_running_loop()
    next_long = 0
    while True:
        try:
            await tracker.sweep()
            if loop.time()>=next_long:
                await sweep(connect,calendar,load_bars,long_only=True)
                next_long = loop.time()+1800
        except Exception:
            LOG.exception('Plan tracking worker failed')
        await asyncio.sleep(60)
