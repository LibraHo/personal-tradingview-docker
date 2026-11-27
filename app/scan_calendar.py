"""Regular-session boundaries calculated from the selected market calendar."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time


class TradingCalendar:
    def __init__(self, radar):
        self.radar = radar

    def days(self, symbol):
        return self.radar.trading_days(symbol)


def close_time(stamp, symbol, period, days):
    us = symbol.startswith('US.')
    dt = datetime.fromtimestamp(stamp, ZoneInfo('America/New_York' if us else 'Asia/Shanghai'))
    day = dt.date()
    if period in ('1w', '1mo'):
        end = day + timedelta(days=6-day.weekday()) if period == '1w' else (day.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        start = day-timedelta(days=day.weekday()) if period == '1w' else day.replace(day=1)
        choices = sorted(d for d in days if str(start) <= d <= str(end))
        if not choices:
            raise ValueError('周期交易日历缺失')
        day = datetime.fromisoformat(choices[-1]).date()
    kind = days.get(str(day))
    if kind not in ('WHOLE', 'MORNING', 'AFTERNOON'):
        raise ValueError('交易日历缺失或非交易日：'+str(day))
    end = datetime.combine(day, datetime.min.time(), dt.tzinfo).replace(hour=(13 if kind == 'MORNING' else 16) if us else 15)
    if period in ('1d', '1w', '1mo') or (not us and period == '240m'):
        return end.timestamp()
    # Canonical scanner timestamps identify the beginning of an intraday candle.
    end = min(end, dt+timedelta(minutes=int(period[:-1])))
    if not us and dt.hour < 12:
        end = min(end, dt.replace(hour=11, minute=30, second=0))
    return end.timestamp()


def annotate(bars, symbol, period, days, now=None):
    now = time.time() if now is None else now
    output = []
    for i, bar in enumerate(bars):
        try:
            end = close_time(bar['time'], symbol, period, days)
        except ValueError:
            if i+1 == len(bars):
                raise
            end = bars[i+1]['time']
        output.append({**bar, 'close_time': end, 'confirmed': end <= now})
    return output


def expected_day(symbol, days, now=None):
    now = time.time() if now is None else now
    eligible = []
    for day in days:
        dt = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo('America/New_York' if symbol.startswith('US.') else 'Asia/Shanghai'))
        if close_time(dt.timestamp(), symbol, '1d', days)+120 <= now:
            eligible.append(day)
    return max(eligible) if eligible else None


def latest_intraday_close(symbol, period, days, now=None):
    now=time.time() if now is None else now
    us=symbol.startswith('US.')
    dt=datetime.fromtimestamp(now,ZoneInfo('America/New_York' if us else 'Asia/Shanghai'))
    if str(dt.date()) not in days:return None
    opening=dt.replace(hour=9,minute=30,second=0,microsecond=0)
    end=dt.replace(hour=(13 if days[str(dt.date())]=='MORNING' else 16) if us else 15,minute=0,second=0,microsecond=0)
    cutoff=min(dt,end)
    if not us:
        if dt.hour>=13:opening=opening.replace(hour=13,minute=0)
        else:cutoff=min(cutoff,dt.replace(hour=11,minute=30,second=0,microsecond=0))
    if cutoff<opening:return None
    seconds=int(period[:-1])*60
    if cutoff==end:return end.timestamp()
    intervals = int((cutoff-opening).total_seconds()//seconds)
    if not intervals:
        return opening.replace(hour=11, minute=30).timestamp() if not us and opening.hour == 13 else None
    return opening.timestamp()+intervals*seconds
