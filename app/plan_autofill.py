"""Generate a form patch on explicit request. This endpoint never writes a plan."""
import re
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException, Query
from pydantic import Field

from .agent_client import complete
from .analysis_drawings import fibonacci_for_frame
from .agent_settings import active_config
from .market_analysis import Chart, COLUMNS, SYMBOL, reference_periods, sample
from .ledger import Input, Market, Note, PlanDetails, PlanPeriod, Positive, validate_symbol


class FormDraft(Input):
    request_id: str = Field(default_factory=lambda:uuid.uuid4().hex, pattern='^[a-f0-9]{32}$')
    symbol: str = Field(max_length=32)
    period: PlanPeriod
    side: Literal['BUY', 'SELL']
    details: PlanDetails
    size: str = Field(default='', max_length=2000)
    stop: Positive | None = None
    last_close: Positive | None = None


class Suggestions(Input):
    title: str = Field(default='', max_length=100)
    entry_note: Note = ''
    exit_note: Note = ''
    risk_note: Note = ''


def agent_text(url, token, agent_id, facts, blanks):
    prompt = ('你在填写 NAS Market 的单份交易计划草稿。只根据给定数据，以中文简明描述待观察的条件。'
              '只回答 JSON 对象，仅填写 blanks 中的文本字段。title 是短标题，entry_note 是入场条件，'
              'exit_note 是退出或放弃条件，risk_note 是风险说明。打板只写首封、回封与炸板等文字条件。'
              'news 表示新闻驱动，只填写待核实的消息和确认条件。other 表示自定义入场，具体触发条件留给用户填写。'
              'period 是唯一主周期；不同周期的指标条件仅作明确标注的独立触发条件。'
              '按行情列顺序读取各周期样本；最后一根可能未收盘。区分主周期判断和高周期确认，注明缺失或过期数据。'
              '遵守 settlement 约束，区分当日新增仓位和已有可卖仓位。'
              '数据不足则写待确认的观察条件。不要编造行情、封单、账户资金或成交。不要调用工具或执行外部动作。')
    content = complete(url, token, agent_id, prompt, {'facts':facts,'blanks':blanks})
    try:
        if content.startswith('```'):
            content = re.sub(r'^\x60{3}(?:json)?\s*|\s*\x60{3}$','',content,flags=re.I)
        result = Suggestions.model_validate_json(content).model_dump()
        if not any(result[k] for k in blanks):
            raise ValueError()
        return {k:result[k] for k in blanks if result[k]}
    except (ValueError,IndexError,KeyError,TypeError,AttributeError):
        raise HTTPException(502,'OpenClaw 返回的填表内容无效，草稿已保留')


def condition_summary(group):
    labels = []
    for item in group.items:
        if item.source=='SIXPULSE':
            signal = f'至少 {item.threshold:g} ' + ('红' if item.signal=='reds' else '绿')
        elif item.source=='MACD':
            signal = 'DIF ≥ DEA' if item.signal=='bullish' else 'DIF ≤ DEA'
        elif item.source in ('RSI','PRICE'):
            signal = ('≥ ' if item.signal=='above' else '≤ ')+f'{item.threshold:g}'
        else:
            line = {'mid':'中轨','upper':'上轨','lower':'下轨','main':''}[item.line]
            signal = ('价格站上' if item.signal=='above' else '价格跌破')+(line or '该线')
        label = {'SIXPULSE':'六脉','PRICE':'价格'}.get(item.source,item.source)
        labels.append(f'{item.period} {label} {signal}')
    return ('，且' if group.join=='all' else '，或').join(labels)


def autofill(market:Market,body:FormDraft,config):
    validate_symbol(body.symbol,market)
    d,risk = body.details,body.details.risk
    board = d.strategy=='limit_up'
    if board and market!='CN':
        raise HTTPException(422,'打板条件仅适用于 A 股')
    original = {'title':d.title,'entry_note':d.entry_note,'exit_note':d.exit_note,'risk_note':risk.note}
    blanks = [k for k,v in original.items() if not v.strip()]
    provider,url,token,agent = config
    if bool(url)!=bool(token):
        raise HTTPException(503,'OpenClaw 配置不完整，请同时设置网关地址和凭证')
    source = 'local'
    coverage = []
    settlement = ''
    if market == 'CN':
        if re.fullmatch(r'(?:SH\.(?:60|68)\d{4}|SZ\.(?:00|30)\d{4}|BJ\.\d{6})', body.symbol):
            settlement = '普通 A 股实行 T+1。当日买入的股票最早下一交易日可卖；盘中退出仅适用于已有可卖数量。'
        else:
            settlement = '请核对该品种的回转交易规则及已有可卖数量。普通 A 股当日新买股份最早下一交易日可卖，部分 ETF 支持当日回转。'
    last_close = body.last_close
    frames = []
    if blanks and provider == 'openclaw':
        if not SYMBOL.fullmatch(body.symbol):
            raise HTTPException(422, '当前行情源不支持这个标的的 K 线')
        chart = Chart(symbol=body.symbol, period=body.period, mode=d.mode)
        _, higher = reference_periods(chart)
        frames = [sample(chart, chart.period, 80)]
        if not frames[0]['bars']:
            raise HTTPException(503, '计划主周期暂无有效 K 线，请刷新行情后重试')
        frames.extend(sample(chart, period, 40) for period in higher)
        coverage = [{'period':frame['period'], 'mode':frame['mode'], 'count':len(frame['bars']),
                     'last':frame['bars'][-1][0] if frame['bars'] else None,
                     'stale':frame['stale'], 'issue':frame.get('issue')} for frame in frames]
        last_close = frames[0]['bars'][-1][COLUMNS.index('close')]
    patch = {}
    entry = risk.entry_price
    if not board and entry is None and last_close is not None:
        entry = patch['entry_price'] = round(last_close,8)
    stop,target = body.stop,d.levels.take_profit
    if entry and not board:
        levels = [('前低',d.levels.previous_low),('平台下沿',d.levels.platform_low),
                  ('前高',d.levels.previous_high),('平台上沿',d.levels.platform_high)]
        buy = body.side=='BUY'
        supports = [(abs(v-entry),name,v) for name,v in levels if v and (v<entry if buy else v>entry)]
        targets = [(abs(v-entry),v) for _,v in levels if v and (v>entry if buy else v<entry)]
        if stop is None and not risk.defense_reference and supports:
            _,defense_label,stop = min(supports)
            patch.update(stop=stop,defense_source=defense_label+' · 固定价')
        if target is None and targets:
            _,target = min(targets)
            patch['take_profit'] = target
    if not body.size and risk.qty:
        patch['size'] = f'计划 {risk.qty:g} 股'
    if frames:
        # Only enumerated identifiers and numeric facts enter the existing operator agent.
        def conditions(group):
            return {'join':group.join,'items':[c.model_dump(exclude={'id'}) for c in group.items]}
        facts = {'symbol':body.symbol,'market':market,'period':body.period,'side':body.side,'strategy':d.strategy,
                 'entry':conditions(d.entry),'exit':conditions(d.exit),'levels':d.levels.model_dump(),
                 'settlement':settlement, 'ohlcv_columns':COLUMNS, 'frames':frames,
                 'fibonacci':fibonacci_for_frame(frames[0]),
                 'timezone':'Asia/Shanghai' if market=='CN' else 'America/New_York',
                 'entry_price':entry,'stop':stop,'take_profit':target,'last_close':last_close}
        patch.update(agent_text(url,token,agent or 'default',facts,blanks))
        source = 'openclaw'
    elif blanks:
        text = {'title':f'{body.symbol} · {body.period} '+('打板计划' if board else '交易计划'),
                'entry_note':('核对消息来源、发布时间和公告原文，确认与标的相关后再评估入场。' if d.strategy=='news' else
                              '待填写自定义触发条件及确认方式。' if d.strategy=='other' else
                              '首封时核对封单和板块跟随；若已炸板，等回封再评估。' if board else
                              '观察'+condition_summary(d.entry)+'。' if d.entry.items else '触发条件待确认，确认前保持观察。'),
                'exit_note':('回封失败或封单持续减弱时放弃排板；已成交部分按可卖时段复核退出条件。' if board
                             else '出现'+condition_summary(d.exit)+'时复核退出安排。' if d.exit.items else '退出条件待确认。'),
                'risk_note':('记录开板次数、回封时间和次日流动性，排板时考虑无法成交或撤单的情况。' if board
                             else '留意跳空越过防守位的情况，成交价可能与计划点位有差异。')}
        if not board and entry:
            text['entry_note'] += f' 入场参考 {entry:g}。'
        if not board and stop:
            text['exit_note'] += f' 防守参考 {stop:g}。'
        if not board and target:
            text['exit_note'] += f' 止盈参考 {target:g}。'
        patch.update({k:text[k] for k in blanks})
    if settlement and 'exit_note' in patch and not any(word in patch['exit_note'] for word in ('T+1','下一交易日','回转交易规则')):
        patch['exit_note'] = patch['exit_note'][:4999-len(settlement)] + ' ' + settlement
    return {'source':source,'fields':patch,'coverage':coverage}


def install(route, connect_db):
    from .ledger import transaction, now, stamp

    @route('autofill', 'POST', '一键填写当前交易计划草稿')
    def fill(market:Market, body:FormDraft):
        ident = body.request_id
        with transaction(connect_db, True) as db:
            config = active_config(db)
            created = db.execute("""INSERT OR IGNORE INTO plan_fill_runs
                (id,market,symbol,provider,started,status,error) VALUES(?,?,?,?,?,'running','')""",
                (ident,market,body.symbol,config[0],now())).rowcount
            if not created:
                raise HTTPException(409,'填表请求编号已存在，请查看填表记录')
        message = ''
        status = 'failed'
        provider = config[0]
        try:
            result = autofill(market,body,config)
            provider = result['source']
            status = 'success'
            return {**result, 'request_id':ident}
        except HTTPException as exc:
            message = str(exc.detail)
            raise HTTPException(exc.status_code, message+' · 请求编号 '+ident) from exc
        except Exception as exc:
            logging.getLogger(__name__).exception('Autofill request %s failed', ident)
            message = '填表服务处理失败'
            raise HTTPException(500,message+' · 请求编号 '+ident) from exc
        finally:
            with transaction(connect_db, True) as db:
                db.execute('UPDATE plan_fill_runs SET status=?,provider=?,finished=?,error=? WHERE id=?',
                           (status,provider,now(),message,ident))

    @route('autofill/history','GET','按标的或请求编号查看填表记录')
    def history(market:Market, symbol:str | None=None, request_id:str | None=Query(None,pattern='^[a-f0-9]{32}$')):
        where = ['market=?']
        args = [market]
        if symbol:
            validate_symbol(symbol,market)
            where.append('symbol=?')
            args.append(symbol)
        if request_id:
            where.append('id=?')
            args.append(request_id)
        with transaction(connect_db) as db:
            rows = db.execute('SELECT * FROM plan_fill_runs WHERE '+' AND '.join(where)+' ORDER BY started DESC LIMIT 30',args)
            items = [dict(row) for row in rows]
        cutoff = stamp(datetime.now(timezone.utc)-timedelta(minutes=4))
        for row in items:
            if row['status']=='running' and row['started']<cutoff:
                row.update(status='unknown',error='服务尚未记录完成结果，可重新查询')
        return {'items':items}
