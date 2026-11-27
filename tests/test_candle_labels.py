import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import main
from app.hour_bars import aggregate_hours
from app.plan_tracking import Series, slots
from app.scan_calendar import annotate
from app.strategy_rules import evaluate, validate_strategy
from test_strategies import config


def stamp(clock, market='US'):
    zone = 'America/New_York' if market == 'US' else 'Asia/Shanghai'
    return int(datetime.fromisoformat('2026-11-27T' + clock).replace(tzinfo=ZoneInfo(zone)).timestamp())


def candle(clock, market='US'):
    return dict(time=stamp(clock, market), open=1, high=2, low=1, close=2, volume=10, turnover=15)


class CandleTimeTests(unittest.TestCase):
    def test_end_label_uses_the_last_candle_in_short_and_split_sessions(self):
        for market, symbol, period, day_type, closing, opening in [
            ('US', 'US.AAPL', '60m', 'MORNING', '13:00', '12:30'),
            ('CN', 'SH.600000', '120m', 'WHOLE', '11:30', '09:30'),
            ('CN', 'SH.600000', '120m', 'WHOLE', '15:00', '13:00'),
            ('US', 'US.AAPL', '5m', 'WHOLE', '09:35', '09:30'),
        ]:
            with self.subTest(market=market, closing=closing):
                day = {'2026-11-27': day_type}
                end = stamp(closing, market)
                raw = {**candle(closing, market), 'bar_label':'end', 'trade_date':'2026-11-27'}
                row = annotate([raw], symbol, period, day, now=end)[0]
                self.assertEqual((row['open_time'], row['close_time'], row['confirmed']),
                                 (stamp(opening, market), end, True))
                self.assertFalse(annotate([raw], symbol, period, day, now=end-1)[0]['confirmed'])
                self.assertEqual(Series(market, period, slots(market, period, day), [raw], 'regular').by_end[end], raw)
                initial = {**raw, 'bar_label':'start', 'time':stamp(opening, market)}
                self.assertEqual(annotate([initial], symbol, period, day, now=end)[0]['close_time'], end)
                self.assertEqual(Series(market, period, slots(market, period, day), [initial], 'regular').by_end[end], initial)

    def test_strategy_signal_uses_same_bar_for_both_labels(self):
        strategy = validate_strategy(config())
        starts = [dict(candle(t), close=v, session_date='2026-11-27:regular', bar_label='start')
                  for t, v in [('09:30',3),('09:35',2),('09:40',4),('09:45',1)]]
        ends = [{**b, 'time':b['time']+300, 'bar_label':'end'} for b in starts]
        a,b = [evaluate(strategy, data, now=stamp('09:45')+3) for data in (starts,ends)]
        self.assertTrue(a['buy'] and b['buy'])
        self.assertEqual((a['bar_end'], b['bar_end']), (stamp('09:45'), stamp('09:45')))

    def test_end_label_native_hours_aggregate_into_start_labelled_buckets(self):
        labels = ('10:30','11:30','12:30','13:30','14:30','15:30','16:00')
        bars = [candle(label) for label in labels]
        four = aggregate_hours(bars,'240m','end')
        two = aggregate_hours(bars,'120m','end')
        self.assertEqual([(r['time'],r['volume']) for r in four], [(stamp('09:30'),40),(stamp('13:30'),30)])
        self.assertEqual([r['time'] for r in two], [stamp(t) for t in ('09:30','11:30','13:30','15:30')])

    def test_stream_and_cache_agree_on_session_and_labels(self):
        key = ('US.TEST','5m','regular')
        with tempfile.TemporaryDirectory() as folder, patch.object(main,'DB',str(Path(folder)/'bars.db')):
            main.init_db()
            queue = asyncio.Queue()
            with patch.dict(main.listeners, {key:{queue}}):
                asyncio.run(main.publish(key, [candle('09:30'),candle('16:00')]))
            item = queue.get_nowait()['bar']
            self.assertTrue(queue.empty())
            self.assertEqual((item['bar_label'],item['time'],item['session']), ('end',stamp('16:00'),'regular'))
            with main.connect_db() as db:
                (row,) = db.execute('SELECT * FROM bars').fetchall()
            self.assertEqual(main.row_to_bar(row), item)
            base = main.scope_for('US.TEST','5m')
            self.assertNotEqual(main.scope_for('US.TEST','240m'), base)
            self.assertEqual(main.market_data.for_market('US.TEST').time_label('US.TEST','240m'), 'start')
            with main.connect_db() as db:
                db.execute('UPDATE bars SET period=?',('240m',))
                db.execute('INSERT INTO cache_sync VALUES(?,?,?,?,?,?)',(base,'US.TEST','240m','regular',5,1))
            self.assertEqual(main.sync_state(('US.TEST','240m','regular')), (0,0,None))
