"""Confirmed regular-session opening-five-minute range, independent of chart period."""
import math
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def range_times(symbol, day):
    zone=ZoneInfo('America/New_York' if symbol.startswith('US.') else 'Asia/Shanghai')
    midnight=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=zone)
    return {'date':day, 'open_at':int(midnight.replace(hour=9,minute=30).timestamp()),
            'confirmed_at':int(midnight.replace(hour=9,minute=35).timestamp()),
            'regular_end':int(midnight.replace(hour=16 if symbol.startswith('US.') else 15).timestamp()),
            'day_end':int((midnight+timedelta(days=1)).timestamp())-1}


def select_opening_range(rows, symbol, times):
    # Verified on the deployed OpenD: both CN and US first 5m bars are labelled 09:35.
    # Keep start-labelled installations configurable rather than guessing a later bar.
    label=os.getenv('OPENING_RANGE_BAR_LABEL','end')
    if label not in {'start','end'}:
        raise ValueError('OPENING_RANGE_BAR_LABEL 须为 start 或 end')
    stamp=times['open_at'] if label=='start' else times['confirmed_at']
    row=next((row for row in rows if row['time']==stamp),None)
    if not row:return None
    high,low=float(row['high']),float(row['low'])
    if not math.isfinite(high) or not math.isfinite(low) or low<=0 or high<low:
        raise ValueError('开盘5分钟行情价格无效')
    return {**times,'symbol':symbol,'high':high,'low':low,'source_time':stamp,'status':'ready'}
