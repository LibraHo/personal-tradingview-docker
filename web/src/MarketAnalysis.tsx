import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {ChartNoAxesCombined, PencilRuler, Sparkles, X} from 'lucide-react';
import {analysisPath, marketAnalysisRequest} from './marketAnalysisClient';
import AnalysisDrawings, {type AnalysisDrawingBatch} from './AnalysisDrawings';
import {FibonacciLevels, type Retracement} from './FibonacciLevels';
import {periodNames, type PlanPeriod} from './tradeBookClient';
import './market-analysis.css';

type Mode = 'regular' | 'extended' | 'all';
export type AnalysisChart = {symbol:string; period:PlanPeriod; mode:Mode};
type Options = {enabled:boolean; higher:PlanPeriod[]; defaults:PlanPeriod[]};
type Coverage = {period:PlanPeriod; mode:Mode; count:number; last:number|null; stale:boolean; issue:string|null};
type Result = {analysis:string; coverage:Coverage[]; fibonacci?:Retracement|null};

const sessions = {regular:'常规时段', extended:'盘前、常规及盘后', all:'全时段'};

async function read<T>(response:Response):Promise<T> {
  if (response.status===401) throw Error('登录已过期，请刷新页面重新登录。');
  if (!response.ok) {
    const data = await response.json().catch(()=>({}));
    throw Error(typeof data.detail==='string' ? data.detail : '读取失败，请重试。');
  }
  return response.json();
}

export default function MarketAnalysis({chart,onClose,onSettings,onApply}:{
  chart:AnalysisChart; onClose:()=>void; onSettings:()=>void; onApply:(batch:AnalysisDrawingBatch)=>void;
}) {
  const [view,setView] = useState<'analysis'|'drawings'>('analysis');
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef<AbortController|null>(null);
  const [options,setOptions] = useState<Options|null>(null);
  const [refs,setRefs] = useState<PlanPeriod[]>([]);
  const [attempt,setAttempt] = useState(0);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [result,setResult] = useState<Result|null>(null);
  const us = chart.symbol.startsWith('US.');
  const time = new Intl.DateTimeFormat('zh-CN',{timeZone:us?'America/New_York':'Asia/Shanghai',dateStyle:'short',timeStyle:'short'});
  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    return ()=>{element?.close();pending.current?.abort()};
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    setError('');
    fetch(analysisPath+'?'+new URLSearchParams({symbol:chart.symbol,period:chart.period}),{signal:controller.signal})
      .then(read<Options>).then(data=>{if(!controller.signal.aborted){setOptions(data);setRefs(data.defaults)} })
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return ()=>controller.abort();
  },[chart.symbol,chart.period,attempt]);
  async function analyze() {
    if (!options?.enabled || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);setError('');setResult(null);
    try {
      const data = await marketAnalysisRequest<Result>({...chart,references:refs},controller.signal);
      if (!controller.signal.aborted) setResult(data);
    } catch(e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      pending.current=null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return createPortal(<dialog className="market-analysis" ref={dialog} aria-labelledby="analysis-title"
    onCancel={e=>{e.preventDefault();onClose()}} onKeyDown={e=>e.stopPropagation()}>
    <header><span className="analysis-mark"><Sparkles size={19} aria-hidden="true"/></span><div><h2 id="analysis-title">AI 盘面分析</h2><p>{chart.symbol} · {periodNames[chart.period]} · {sessions[chart.mode]}</p></div>
      <button type="button" aria-label="关闭盘面分析" onClick={onClose}><X size={18}/></button></header>
    {!options && !error && <p role="status">正在读取 AI 配置…</p>}
    {options && (options.enabled ? <>
      <div className="analysis-mode" role="group" aria-label="AI 功能">
        <button type="button" aria-pressed={view==='analysis'} onClick={()=>setView('analysis')}><ChartNoAxesCombined size={15} aria-hidden="true"/>盘面解读</button>
        <button type="button" disabled={busy} aria-pressed={view==='drawings'} onClick={()=>setView('drawings')}><PencilRuler size={15} aria-hidden="true"/>AI 画线</button>
      </div>
      <div hidden={view!=='drawings'}><AnalysisDrawings key={chart.symbol+chart.period+chart.mode} chart={chart} onApply={onApply}/></div>
      {view==='analysis'&&<>
      {options.higher.length>0 && <fieldset className="analysis-periods" disabled={busy}><legend>参考周期 <small>最多 3 个</small></legend>
        {options.higher.map(p=><label key={p}><input type="checkbox" checked={refs.includes(p)}
          disabled={!refs.includes(p)&&refs.length>=3} onChange={e=>{
            setRefs(e.target.checked?[...refs,p]:refs.filter(x=>x!==p));setResult(null);setError('');
          }}/>{periodNames[p]}</label>)}</fieldset>}
      <p>使用最新量价数据，主周期最多 80 根{refs.length>0?'，每个参考周期最多 40 根':''}。</p>
      <button type="button" className="analysis-run" disabled={busy} onClick={()=>void analyze()}>{busy?'正在分析…':result?'重新分析':'开始分析'}</button></>}
    </> : <p>启用 AI 助手后即可分析当前图表。 <button onClick={onSettings}>打开 AI 助手设置</button></p>)}
    {view==='analysis' && error && <p role="alert">{error} {!options && <button onClick={()=>setAttempt(a=>a+1)}>重试</button>}</p>}
    {view==='analysis' && result && <section aria-label="分析结果">
      <h3>盘面解读</h3><div className="analysis-text">{result.analysis}</div>
      <details className="analysis-samples"><summary>主周期斐波那契回撤</summary>
        {result.fibonacci?<FibonacciLevels value={result.fibonacci} symbol={chart.symbol} period={chart.period}/>:
          <p>当前周期还没有确认一段完整波段。</p>}</details>
      <details className="analysis-samples"><summary>行情样本 <small>{us?'美东时间':'北京时间'}</small></summary>
      <ul>{result.coverage.map(f=><li key={f.period}><strong>{periodNames[f.period]}</strong> · {sessions[f.mode]} · {f.count} 根
        {f.last!==null && ' · '+time.format(f.last*1000)} {f.stale && <b>缓存未同步</b>} {f.issue}</li>)}</ul></details>
    </section>}
  </dialog>,document.body);
}
