"""US session-aligned 2h/4h candles from the OpenD 60-minute feed."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


def is_us_hour(symbol, period):
    return symbol.startswith('US.') and period in {'120m', '240m'}


def hour_bucket(stamp, period):
    dt = datetime.fromtimestamp(stamp, ET)
    minutes = dt.hour * 60 + dt.minute
    anchor = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if minutes < 240:
        anchor = (anchor - timedelta(days=1)).replace(hour=20)
    elif minutes < 570:
        anchor = anchor.replace(hour=4)
    elif minutes < 960:
        anchor = anchor.replace(hour=9, minute=30)
    elif minutes < 1200:
        anchor = anchor.replace(hour=16)
    else:
        anchor = anchor.replace(hour=20)
    duration = int(period[:-1]) * 60
    start = int(anchor.timestamp())
    return start + (int(stamp) - start) // duration * duration


def aggregate_hours(bars, period):
    result = {}
    # A push corrects the same source bar, rather than adding its volume again.
    unique = {bar['time']: bar for bar in bars}
    for stamp, bar in sorted(unique.items()):
        bucket = hour_bucket(stamp, period)
        if bucket not in result:
            result[bucket] = {k: bar[k] for k in ('open', 'high', 'low', 'close', 'volume', 'turnover')}
            result[bucket]['time'] = bucket
        else:
            item = result[bucket]
            item.update(high=max(item['high'], bar['high']), low=min(item['low'], bar['low']),
                        close=bar['close'], volume=item['volume'] + bar['volume'],
                        turnover=item['turnover'] + bar['turnover'])
    return list(result.values())
