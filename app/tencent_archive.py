"""Read Tencent unadjusted daily stock bars from the fetch.py JSON archive."""
import json
import math
import os
import re
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


CN = ZoneInfo('Asia/Shanghai')
STOCK = re.compile(r'(?:SH\.(?:60[0135]|688)|SZ\.(?:00[0123]|30[01]))[0-9]{3}')


@lru_cache(maxsize=16)
def _read(path, modified_ns, size):
    # File version arguments invalidate both history and the per-symbol coverage date.
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or not isinstance(payload.get('raw'), list):
        raise ValueError('腾讯归档缺少 raw 不复权日线')
    by_day = {}
    for page in payload['raw']:
        if not isinstance(page, list):
            raise ValueError('腾讯归档日线分页格式无效')
        for row in page:
            if not isinstance(row, list) or len(row) < 6:
                raise ValueError('腾讯归档日线字段不完整')
            day = date.fromisoformat(row[0])
            opening, close, high, low = (float(v) for v in row[1:5])
            if (not all(math.isfinite(v) for v in (opening, close, high, low))
                    or not 0 < low <= min(opening, close) <= max(opening, close) <= high):
                raise ValueError(f'腾讯归档 {day} 价格无效')
            volume = None if row[5] in (None, '') else float(row[5])
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                raise ValueError(f'腾讯归档 {day} 成交量无效')
            item = (opening, high, low, close, volume)
            if day in by_day and by_day[day] != item:
                raise ValueError(f'腾讯归档 {day} 分页重叠的日线不一致')
            by_day[day] = item
    if not by_day:
        raise ValueError('腾讯归档缺少不复权日线记录')
    return tuple(sorted(by_day.items()))


class TencentArchive:
    source_id = 'tencent_archive'
    adjustments = ('none',)
    live_adjustments = ()
    bar_label = 'start'

    def __init__(self, directory):
        self.directory = Path(directory)

    def _rows(self, symbol):
        if not STOCK.fullmatch(symbol):
            raise ValueError('腾讯归档仅覆盖沪深主板、科创板和创业板样本股票')
        path = self.directory / (symbol.lower().replace('.', '') + '.json')
        try:
            info = path.stat()
            return _read(path, info.st_mtime_ns, info.st_size)
        except FileNotFoundError:
            raise ValueError(f'腾讯归档中没有 {symbol} 的日线文件') from None
        except OSError:
            raise ValueError(f'腾讯归档无法读取 {symbol} 的日线文件') from None
        except (TypeError, OverflowError, IndexError, KeyError):
            raise ValueError(f'腾讯归档 {symbol} 日线格式无效') from None

    def history_status(self, symbol):
        try:
            last, _ = self._rows(symbol)[-1]
        except ValueError as exc:
            return {'stale': True, 'archive_as_of': None, 'history_notice': str(exc)}
        return {'stale': True, 'archive_as_of': last.isoformat(),
                'history_notice': f'腾讯离线归档截至 {last.isoformat()}，仅提供历史日线'}

    def fetch_bars(self, key, days, end_date, adjustment):
        symbol, period, mode = key
        if adjustment != 'none':
            raise ValueError('腾讯归档仅提供不复权日线')
        if (period, mode) != ('1d', 'regular'):
            raise ValueError('腾讯归档仅提供常规时段日线')
        end = end_date or datetime.now(CN).date()
        start = end - timedelta(days=days)
        multiplier = 1 if symbol.startswith('SH.688') else 100
        bars = []
        for day, (opening, high, low, close, volume) in self._rows(symbol):
            if start <= day <= end:
                bars.append({'time': int(datetime.combine(day, time.min, CN).timestamp()),
                             'open': opening, 'high': high, 'low': low, 'close': close,
                             'volume': volume * multiplier if volume is not None else None,
                             'turnover': None})
        return bars


def factory():
    directory = os.getenv('TENCENT_ARCHIVE_DIR')
    if not directory:
        raise ValueError('腾讯归档需要配置 TENCENT_ARCHIVE_DIR')
    return TencentArchive(directory)
