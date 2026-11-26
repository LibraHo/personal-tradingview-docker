import {useEffect, useState} from 'react';
import {displayPlanPrice} from './tradePlanAnalysis';
import type {ReviewMarket} from './reviewClient';
import {displayTime,ledgerRequest,periodNames,type PlanPeriod} from './tradeBookClient';

type Day = {
  day:string; revision:number; high:number; low:number; close:number;
  open_stop:number|null; close_stop:number|null; change:number|null; take_profit:number|null;
  stop_hit:boolean|null; profit_hit:boolean|null; full_session:boolean; dynamic:boolean; incomplete_count?:number;
};
type History = {items:Day[];next_before:string|null;status:{expected_day:string|null;error:string|null}|null};
const hit = (value:boolean|null, price:number|null, partial:boolean) =>
  value === true ? '已触及' : value === false ? '未触及' : partial || price!==null ? '待确认' : '无点位';

type Candle = Day & {period:PlanPeriod;close_time:number;error:string|null;next_retry:number|null};
function CandleHistory({market,id}:{market:ReviewMarket;id:string}) {
  const [rows,setRows]=useState<Candle[]>([]),[next,setNext]=useState<number|null>(null);
  const [cursor,setCursor]=useState(0),[retry,setRetry]=useState(0),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  useEffect(()=>{
    const ctl=new AbortController();
    setLoading(true);setError('');
    ledgerRequest<{items:Candle[];next_before:number|null}>(market,`plans/${id}/bars?limit=30${cursor?'&before='+cursor:''}`,'GET',undefined,ctl.signal)
      .then(data=>{if(!ctl.signal.aborted){setRows(prior=>cursor?[...prior,...data.items]:data.items);setNext(data.next_before)}})
      .catch(e=>{if(!ctl.signal.aborted)setError(e.message)}).finally(()=>{if(!ctl.signal.aborted)setLoading(false)});
    return ()=>ctl.abort();
  },[market,id,cursor,retry]);
  return <section><h4>K 线收盘记录</h4>
    {rows.length>0 && <div className="book-table"><table><thead><tr>{['收盘时间','周期','本根防守','收盘防守','止损 / 止盈','状态'].map(s=><th key={s}>{s}</th>)}</tr></thead>
      <tbody>{rows.map(r=><tr key={r.close_time}><td>{displayTime(market,new Date(r.close_time*1000).toISOString())}</td><td>{periodNames[r.period]}</td>
      <td>{displayPlanPrice(r.open_stop)}</td><td>{displayPlanPrice(r.close_stop)}</td><td>{hit(r.stop_hit,r.open_stop,!r.full_session||!!r.error)} / {hit(r.profit_hit,r.take_profit,!r.full_session||!!r.error)}</td>
      <td>{r.error || '已记录'}{r.next_retry && <small>下次重试 {displayTime(market,new Date(r.next_retry*1000).toISOString())}</small>}</td></tr>)}</tbody></table></div>}
    {loading && <p>读取中…</p>}{error && <p role="alert">{error} <button onClick={()=>setRetry(n=>n+1)}>重试</button></p>}
    {!loading && !error && !rows.length && <p>暂无已收盘的跟踪记录。</p>}
    {next && <button disabled={loading} onClick={()=>setCursor(next)}>更早的 K 线</button>}
  </section>;
}
export default function PlanDailyHistory({market,id,period}:{market:ReviewMarket;id:string;period?:PlanPeriod|null}) {
  const [showBars,setShowBars]=useState(false);
  const [history,setHistory]=useState<History|null>(null);
  const [before,setBefore]=useState('');
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setError('');setLoading(true);
    ledgerRequest<History>(market,`plans/${id}/daily?limit=30${before?'&before='+before:''}`,'GET',undefined,controller.signal)
      .then(result=>{
        if(!controller.signal.aborted)setHistory(prior=>{
          const rows=new Map((before ? prior?.items || [] : []).map(row=>[row.day,row]));
          result.items.forEach(row=>rows.set(row.day,row));
          return {...result,items:[...rows.values()]};
        });
      })
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)});
    return ()=>controller.abort();
  },[market,id,before,retry]);
  return <section><h3>每日点位跟踪</h3>
    <p className="review-muted">{period ? `按${periodNames[period]}收盘记录。每根使用当时已生效的防守位判断触及。` : '后台跟踪已关闭，历史记录仍可查看。'}</p>
    <button onClick={()=>setShowBars(v=>!v)} aria-expanded={showBars}>查看 K 线明细</button>
    {showBars && <CandleHistory market={market} id={id}/>}
    {error && <p role="alert">{error} <button onClick={()=>setRetry(n=>n+1)}>重试</button></p>}
    {history?.status?.error && <p role="status">{history.status.error}</p>}
    {!!history?.items.length && <div className="book-table"><table>
      <thead><tr>{['交易日','盘初防守','收盘防守','点位变化','止盈位','最低 / 最高','收盘价','止损','止盈'].map(label=><th key={label}>{label}</th>)}</tr></thead>
      <tbody>{history.items.map(r=><tr key={r.day}><td>{r.day}<small>版本 {r.revision}{r.full_session?'':' · 盘中生效'}{r.incomplete_count ? ` · ${r.incomplete_count} 根待确认` : ''}</small></td>
        <td>{displayPlanPrice(r.open_stop)}</td><td>{displayPlanPrice(r.close_stop)}</td><td>{r.change!=null && r.change>0 ? '+' : ''}{displayPlanPrice(r.change)}</td>
        <td>{displayPlanPrice(r.take_profit)}</td><td>{displayPlanPrice(r.low)} / {displayPlanPrice(r.high)}</td><td>{displayPlanPrice(r.close)}</td>
        <td>{hit(r.stop_hit,r.open_stop,!r.full_session||!!r.incomplete_count)}</td><td>{hit(r.profit_hit,r.take_profit,!r.full_session||!!r.incomplete_count)}</td></tr>)}</tbody>
    </table></div>}
    {loading && <p role="status">读取跟踪记录…</p>}
    {!loading && !error && !history?.items.length && <p>暂无每日汇总。</p>}
    {history?.next_before && <button disabled={loading} onClick={()=>setBefore(history.next_before!)}>更早记录</button>}
  </section>;
}

