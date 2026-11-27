"""On-demand multi-timeframe chart analysis for the authenticated chart."""
import json
import math
import os
from datetime import datetime, timezone
from typing import Literal, get_args
from urllib import parse, request

from fastapi import Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from .analysis_drawings import drawing_proposals, fibonacci_for_frame
from .analysis_archive import ReportArchive, timestamp
from .agent_client import complete
from .agent_settings import active_config
from .ledger import Input, PlanPeriod, transaction
from .radar import SYMBOL


PERIODS = get_args(PlanPeriod)
LONG = {'1d', '1w', '1mo'}
local_bar_reader = None
COLUMNS = ('time', 'open', 'high', 'low', 'close', 'volume')
PROMPT = (
    '以中文分析给定标的最新盘面，主周期是 primary。仅根据所附各周期 OHLCV 数据，'
    '先概括主周期走势和成交量变化，再结合较高周期说明趋势一致或分歧、关键价位和后续观察条件。'
    '引用具体周期、价量或时间作为依据。同周期、可比时段内比较成交量，不直接比较不同周期总量。'
    '每组最后一根可能尚未收盘，其成交量可能不完整。时间戳为 UTC 秒，按给定时区解释。'
    '文字分析只讨论量价、结构和观察条件，不计算或讨论斐波那契回撤、扩展。'
    '标明缺失周期、过期缓存和样本不足对结论的影响，不编造行情，不调用工具。使用简短中文段落。'
)


class Chart(Input):
    symbol: str = Field(pattern=SYMBOL.pattern, max_length=32)
    period: PlanPeriod
    mode: Literal['regular', 'extended', 'all'] = 'regular'


class AnalysisRequest(Chart):
    drawing_focus: Literal['levels', 'range', 'strokes', 'fibonacci'] | None = None
    extensions: Literal['auto','always','off'] = 'auto'
    references: list[PlanPeriod] | None = Field(default=None, max_length=3)


def reference_periods(chart):
    cn = not chart.symbol.startswith('US.')
    # Mainland 240m is backed by the native daily candle.
    primary = '1d' if cn and chart.period == '240m' else chart.period
    higher = list(PERIODS[PERIODS.index(primary) + 1:])
    if cn and '240m' in higher:
        higher.remove('240m')
    anchors = ['60m', '1d', '1w', '1mo']
    return higher, [period for period in anchors if period in higher][:2]


def recent_bars(symbol, period, mode, limit):
    base = os.getenv('MARKET_INTERNAL_URL', 'http://market:8000').rstrip('/')
    if period == '1mo':
        days = (limit + 1) * 31
    elif period == '1w':
        days = (limit + 1) * 7
    else:
        session_minutes = 390 if symbol.startswith('US.') else 240
        bars_per_session = 1 if period == '1d' else math.ceil(session_minutes / int(period[:-1]))
        days = math.ceil(limit / bars_per_session * 7 / 5) + 5
    params = dict(symbol=symbol, period=period, mode=mode, limit=limit, days=days)
    if local_bar_reader is not None:
        return local_bar_reader(params)
    query = parse.urlencode(params)
    with request.urlopen(base + '/api/bars?' + query, timeout=45) as response:
        return json.load(response)


def sample(chart, period, limit):
    mode = 'regular' if period in LONG or not chart.symbol.startswith('US.') else chart.mode
    item = {'period': period, 'mode': mode, 'bars': [], 'stale': False}
    try:
        data = recent_bars(chart.symbol, period, mode, limit)
        for bar in data['bars'][-limit:]:
            if period not in LONG and (mode == 'regular' and bar['session'] != 'regular'
                                       or mode == 'extended' and bar['session'] == 'overnight'):
                continue
            row = [bar[k] for k in COLUMNS]
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in row):
                item['bars'].append(row)
        item['stale'] = bool(data.get('stale'))
    except (OSError, ValueError, KeyError, TypeError, HTTPException):
        item['issue'] = '行情读取失败'
    if not item['bars'] and 'issue' not in item:
        item['issue'] = '暂无有效 K 线'
    return item


def install(app, connect_db, path='/api/trade/market-analysis', synchronous=True):

    def config():
        with transaction(connect_db) as db:
            return active_config(db)

    @app.get(path, summary='查看盘面分析可用状态和参考周期')
    def options(symbol: str, period: PlanPeriod):
        if not SYMBOL.fullmatch(symbol):
            raise HTTPException(422, '无效的图表标的')
        higher, defaults = reference_periods(Chart(symbol=symbol, period=period))
        provider, url, token, _ = config()
        return {'enabled': provider == 'openclaw' and bool(url and token),
                'higher': higher, 'defaults': defaults}

    @app.get(path + '/fibonacci', summary='计算指定周期最近确认波段的斐波那契回撤')
    def fibonacci(symbol: str, period: PlanPeriod, mode: Literal['regular','extended','all'] = 'regular'):
        if not SYMBOL.fullmatch(symbol):
            raise HTTPException(422, '无效的图表标的')
        frame = sample(Chart(symbol=symbol, period=period, mode=mode), period, 80)
        if not frame['bars']:
            raise HTTPException(503, frame['issue'])
        return {'fibonacci': fibonacci_for_frame(frame), 'stale': frame['stale']}

    def analyze(body: AnalysisRequest):
        provider, url, token, agent = config()
        if provider != 'openclaw' or not (url and token):
            raise HTTPException(409, '请先在设置中启用并配置 AI 助手')
        higher, defaults = reference_periods(body)
        refs = defaults if body.references is None else body.references
        if len(set(refs)) != len(refs) or any(p not in higher for p in refs):
            raise HTTPException(422, '请选择不同的更高周期')
        primary = sample(body, body.period, 80)
        if not primary['bars']:
            raise HTTPException(503, '主周期' + primary['issue'] + '，请稍后重试')
        frames = [primary] + [sample(body, p, 40) for p in higher if p in refs]
        context = {'symbol': body.symbol, 'primary': body.period, 'columns': COLUMNS,
                   'as_of': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                   'timezone': 'America/New_York' if body.symbol.startswith('US.') else 'Asia/Shanghai',
                   'frames': frames}
        if body.drawing_focus:
            return drawing_proposals(context, body.drawing_focus,
                                     lambda prompt, facts: complete(url, token, agent or 'default', prompt, facts), body.extensions)
        report = complete(url, token, agent or 'default', PROMPT, context)
        coverage = [{'period': f['period'], 'mode': f['mode'], 'count': len(f['bars']),
                     'last': f['bars'][-1][0] if f['bars'] else None, 'stale': f['stale'],
                     'issue': f.get('issue')} for f in frames]
        return {'analysis': report, 'coverage': coverage}

    # Keep the original authenticated API for existing callers. Browser jobs also
    # work through remote-access proxies with short response timeouts.
    if synchronous:
        app.post(path, summary='使用当前 AI 助手分析多周期量价数据')(analyze)
    from .analysis_jobs import AnalysisJobs
    jobs = AnalysisJobs()
    archive = ReportArchive(connect_db)
    archive_key = Header(alias='X-Analysis-Archive', pattern=r'^[a-f0-9]{64}$')

    @app.get(path + '/archive', summary='按完成时间查看分析归档')
    def history(owner: str = archive_key, before: int = Query(2**63-1, ge=1, le=2**63-1)):
        return JSONResponse(archive.page(owner, before), headers={'Cache-Control':'private, no-store'})

    @app.get(path + '/archive/{job_id}', summary='打开已归档的分析')
    def archived(job_id: str, owner: str = archive_key):
        result = archive.get(owner, job_id)
        if result is None:
            raise HTTPException(404, '没有找到这份归档')
        return JSONResponse(result, headers={'Cache-Control':'private, no-store'})

    @app.post(path + '/jobs', status_code=202, summary='开始盘面分析')
    def submit(body: AnalysisRequest, owner: str | None = Header(None, alias='X-Analysis-Archive', pattern=r'^[a-f0-9]{64}$')):
        if owner and not body.drawing_focus:
            started = timestamp()
            return jobs.submit(analyze, body, lambda key, result: archive.save(owner, key, body, started, result))
        return jobs.submit(analyze, body)

    @app.get(path + '/jobs/{job_id}', summary='读取本次盘面分析')
    def poll(job_id: str):
        return jobs.result(job_id)
