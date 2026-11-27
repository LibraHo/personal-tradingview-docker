import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {ChartNoAxesCombined, ChevronRight, History, LoaderCircle, PencilRuler, Sparkles, X} from 'lucide-react';
import {analysisPath, readArchive} from './marketAnalysisClient';
import AnalysisDrawings, {type AnalysisDrawingBatch} from './AnalysisDrawings';
import type {OpenReport, Report} from './useBackgroundReport';
import {periodNames, type PlanPeriod} from './tradeBookClient';
import './market-analysis.css';

type Mode = 'regular' | 'extended' | 'all';
export type AnalysisChart = {symbol:string; period:PlanPeriod; mode:Mode};
type Options = {enabled:boolean; higher:PlanPeriod[]; defaults:PlanPeriod[]};
type ArchiveRow = AnalysisChart & {id:string; started:string; completed:string};
type ArchivePage = {reports:ArchiveRow[]; next:number|null};
const stamp = (value:string)=>new Date(value).toLocaleString('zh-CN',{hour12:false});

function ReportHistory({onOpen}:{onOpen:(item:OpenReport)=>void}) {
  const [rows,setRows]=useState<ArchiveRow[]>([]);
  const [next,setNext]=useState<number|null>(null);
  const [cursor,setCursor]=useState<number|null>(null);
  const [busy,setBusy]=useState(true),[error,setError]=useState('');
  const [attempt,retry]=useState(0);
  const selection=useRef<AbortController|null>(null);
  useEffect(()=>()=>selection.current?.abort(),[]);
  useEffect(()=>{
    const control=new AbortController();
    setBusy(true);setError('');
    readArchive<ArchivePage>(cursor?'?before='+cursor:'',control.signal).then(page=>{
      if(!control.signal.aborted){setRows(old=>cursor?[...old,...page.reports]:page.reports);setNext(page.next)}
    }).catch(e=>{if(!control.signal.aborted)setError(e.message)}).finally(()=>{if(!control.signal.aborted)setBusy(false)});
    return ()=>control.abort();
  },[cursor,attempt]);
  async function open(row:ArchiveRow) {
    selection.current?.abort();
    const control=new AbortController();selection.current=control;setError('');
    try {
      const result=await readArchive<Report>('/'+encodeURIComponent(row.id),control.signal);
      if(!control.signal.aborted) onOpen({chart:{symbol:row.symbol,period:row.period,mode:row.mode},result});
    } catch(e){if(!control.signal.aborted)setError((e as Error).message)}
  }
  return <section className="analysis-card" aria-label="分析归档"><h3>分析记录</h3>
    {rows.length>0&&<ul className="report-archive">{rows.map(row=><li key={row.id}>
      <button type="button" onClick={()=>void open(row)}><strong>{row.symbol} · {periodNames[row.period]}</strong>
        <span>{sessions[row.mode]} · <time dateTime={row.completed}>{stamp(row.completed)}</time></span><ChevronRight size={15} aria-hidden="true"/></button></li>)}</ul>}
    {busy&&<p role="status">正在读取归档…</p>}
    {!busy&&!error&&!rows.length&&<p>本浏览器还没有已完成的分析。</p>}
    {error&&<p role="alert">{error} <button onClick={()=>retry(n=>n+1)}>重试</button></p>}
    {next&&!busy&&<button onClick={()=>setCursor(next)}>更早的分析</button>}
  </section>;
}

const sessions = {regular:'常规时段', extended:'盘前、常规及盘后', all:'全时段'};

async function read<T>(response:Response):Promise<T> {
  if (response.status===401) throw Error('登录已过期，请刷新页面重新登录。');
  if (!response.ok) {
    const data = await response.json().catch(()=>({}));
    throw Error(typeof data.detail==='string' ? data.detail : '读取失败，请重试。');
  }
  return response.json();
}

export default function MarketAnalysis({chart,onClose,onSettings,onApply,busy,onStart,opened,onOpen}:{
  busy:boolean; onStart:(refs:PlanPeriod[])=>void; opened:OpenReport|null; onOpen:(item:OpenReport)=>void;
  chart:AnalysisChart; onClose:()=>void; onSettings:()=>void; onApply:(batch:AnalysisDrawingBatch)=>void;
}) {
  const [view,setView] = useState<'analysis'|'drawings'|'history'>('analysis');
  const dialog = useRef<HTMLDialogElement>(null);

  const [options,setOptions] = useState<Options|null>(null);
  const [refs,setRefs] = useState<PlanPeriod[]>([]);
  const [attempt,setAttempt] = useState(0);

  const [error,setError] = useState('');
  const result=opened?.result;
  useEffect(()=>{if(opened)setView('analysis')},[opened]);
  const us = chart.symbol.startsWith('US.');
  const time = new Intl.DateTimeFormat('zh-CN',{timeZone:us?'America/New_York':'Asia/Shanghai',dateStyle:'short',timeStyle:'short'});
  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    return ()=>{element?.close()};
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    setError('');
    fetch(analysisPath+'?'+new URLSearchParams({symbol:chart.symbol,period:chart.period}),{signal:controller.signal})
      .then(read<Options>).then(data=>{if(!controller.signal.aborted){setOptions(data);setRefs(data.defaults)} })
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return ()=>controller.abort();
  },[chart.symbol,chart.period,attempt]);
  return createPortal(<dialog className="market-analysis" ref={dialog} aria-labelledby="analysis-title"
    onCancel={e=>{e.preventDefault();onClose()}} onKeyDown={e=>e.stopPropagation()}>
    <header><span className="analysis-mark"><Sparkles size={19} aria-hidden="true"/></span><div><h2 id="analysis-title">AI 盘面分析</h2><p>{chart.symbol} · {periodNames[chart.period]} · {sessions[chart.mode]}</p></div>
      <button type="button" aria-label="关闭盘面分析" onClick={onClose}><X size={18}/></button></header>

      <div className="analysis-mode" role="group" aria-label="AI 功能">
        <button type="button" aria-pressed={view==='analysis'} onClick={()=>setView('analysis')}><ChartNoAxesCombined size={15} aria-hidden="true"/>盘面解读</button>
        <button type="button" aria-pressed={view==='drawings'} onClick={()=>setView('drawings')}><PencilRuler size={15} aria-hidden="true"/>AI 画线</button>
        <button type="button" aria-pressed={view==='history'} onClick={()=>setView('history')}><History size={15}/>归档</button>
      </div>
      <div className="analysis-body">
      {!options && !error && view!=='history' && <p role="status">正在读取 AI 配置…</p>}
      {view==='history'&&<ReportHistory onOpen={item=>{setView('analysis');onOpen(item)}}/>}
      {options && (options.enabled ? <>
      <div hidden={view!=='drawings'}><AnalysisDrawings key={chart.symbol+chart.period+chart.mode} chart={chart} onApply={onApply}/></div>
      {view==='analysis'&&<div className="analysis-card">
      {options.higher.length>0 && <fieldset className="analysis-choices" disabled={busy}><legend>参考周期 <small>最多 3 个</small></legend>
        {options.higher.map(p=><label key={p}><input type="checkbox" checked={refs.includes(p)}
          disabled={!refs.includes(p)&&refs.length>=3} onChange={e=>{
            setRefs(e.target.checked?[...refs,p]:refs.filter(x=>x!==p));setError('');
          }}/>{periodNames[p]}</label>)}</fieldset>}
      <p>使用最新量价数据，主周期最多 80 根{refs.length>0?'，每个参考周期最多 40 根':''}。</p>
      <div className="analysis-actions">
        <button type="button" className="analysis-run" disabled={busy} onClick={()=>onStart(refs)}>
          {busy?<LoaderCircle className="analysis-spinner" size={15} aria-hidden="true"/>:<Sparkles size={15} aria-hidden="true"/>}
          {busy?'正在分析…':result?'重新分析':'开始分析'}
        </button>
        {busy&&<button type="button" onClick={onClose}>返回看盘</button>}
      </div>
      {busy&&<p className="analysis-hint" role="status">分析进行中。可以在此等候，或返回看盘，完成后会自动打开报告。</p>}
      </div>}
    </> : view!=='history'&&<p>启用 AI 助手后即可分析当前图表。 <button onClick={onSettings}>打开 AI 助手设置</button></p>)}
    {view==='analysis' && (error||opened?.error) && <p role="alert">{error||opened?.error} {!options && <button onClick={()=>setAttempt(a=>a+1)}>重试</button>}</p>}
    {view==='analysis' && result && <section className="analysis-card" aria-label="分析结果">
      <h3>盘面解读</h3><p className="report-time">开始 {stamp(result.started)} · 完成 {stamp(result.completed)}</p>
      <div className="analysis-text">{result.analysis}</div>
      <details className="analysis-samples"><summary>行情样本 <small>{us?'美东时间':'北京时间'}</small></summary>
      <ul>{result.coverage.map(f=><li key={f.period}><strong>{periodNames[f.period]}</strong> · {sessions[f.mode]} · {f.count} 根
        {f.last!==null && ' · '+time.format(f.last*1000)} {f.stale && <b>缓存未同步</b>} {f.issue}</li>)}</ul></details>
    </section>}
    </div>
  </dialog>,document.body);
}
