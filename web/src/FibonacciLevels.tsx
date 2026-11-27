import {useEffect, useState} from 'react';
import {analysisPath} from './marketAnalysisClient';
import type {DrawingPoint} from './drawingTools';
import {displayTime, periodNames, type PlanPeriod} from './tradeBookClient';

type Level = {ratio:number; price:number};
export type Retracement = {points:[DrawingPoint, DrawingPoint]; levels:Level[]};
type Actions = {onDefense:(price:number, label:string)=>void; onTarget:(price:number)=>void};
const formatPrice = new Intl.NumberFormat('zh-CN', {maximumFractionDigits:8});
const formatRatio = new Intl.NumberFormat('zh-CN', {style:'percent', maximumFractionDigits:1});

export function FibonacciLevels({value,symbol,period,actions}:{
  value:Retracement; symbol:string; period:PlanPeriod; actions?:Actions;
}) {
  const [start,end] = value.points;
  const market = symbol.startsWith('US.') ? 'US' : 'CN';
  const anchor = (p:DrawingPoint) => displayTime(market,new Date(p.time*1000).toISOString()).slice(0,16)+' · '+formatPrice.format(p.price);
  return <>
    <p className="plan-help">{periodNames[period]} · {end.price>start.price?'上行':'下行'}波段 · {market==='US'?'美东时间':'北京时间'}<br/>
      起点 {anchor(start)}<br/>终点 {anchor(end)}</p>
    {value.levels.map(level=>{
      const ratio = formatRatio.format(level.ratio);
      return <div className="plan-reference-row" key={level.ratio}>
        <div><span>{ratio}{level.ratio===0?'（终点）':level.ratio===1?'（起点）':''}</span> <strong>{formatPrice.format(level.price)}</strong></div>
        {actions&&<>
          <button type="button" onClick={()=>actions.onDefense(level.price,periodNames[period]+' · 斐波那契 '+ratio)}>设为防守</button>
          <button type="button" onClick={()=>actions.onTarget(level.price)}>设为止盈</button>
        </>}
      </div>;
    })}
  </>;
}

export function PlanFibonacci({symbol,period,mode,refresh,actions}:{
  symbol:string; period:PlanPeriod; mode:string; refresh:number; actions:Actions;
}) {
  const [open,setOpen] = useState(false);
  const [result,setResult] = useState<{key:string; fibonacci?:Retracement|null; stale?:boolean; error?:string}>();
  const key = [symbol,period,mode,refresh].join(':');
  useEffect(()=>{
    if (!open || !symbol) return;
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(analysisPath+'/fibonacci?'+new URLSearchParams({symbol,period,mode}),{signal:controller.signal,cache:'no-store'});
        if (!response.ok) throw Error('回撤行情读取失败，可刷新参考行情重试。');
        const data = await response.json();
        if (!controller.signal.aborted) setResult({key,fibonacci:data.fibonacci,stale:data.stale});
      } catch (e) {
        if (!controller.signal.aborted) setResult({key,error:(e as Error).message});
      }
    }
    void load();
    return ()=>controller.abort();
  },[open,symbol,period,mode,key]);
  return <details className="plan-candidate-group" onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary>斐波那契回撤</summary>
    {!symbol ? <p>请先选择标的。</p> : result?.key!==key ? <p role="status">正在读取波段…</p> :
      result.error ? <p role="alert">{result.error}</p> : <>
        {result.stale&&<p>使用缓存行情</p>}
        {result.fibonacci?<FibonacciLevels value={result.fibonacci} symbol={symbol} period={period} actions={actions}/>:
          <p>当前周期还没有确认一段完整波段。</p>}
      </>}
  </details>;
}
