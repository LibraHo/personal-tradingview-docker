import {useEffect, useRef, useState} from 'react';
import {periodNames} from './tradeBookClient';
import type {AnalysisChart} from './MarketAnalysis';
import {fibPrices, type DrawingPoint, type FibDrawing, type HorizontalDrawing, type TrendDrawing} from './drawingTools';
import {FibonacciLevels, type Retracement} from './FibonacciLevels';
import {marketAnalysisRequest} from './marketAnalysisClient';
import './analysis-drawings.css';

const focusNames = {levels:'附近支撑 / 压力',range:'震荡 / 成交密集带',strokes:'缠论参考笔',fibonacci:'斐波那契回撤与扩展'};
type Focus = keyof typeof focusNames;
type Line = {id:string;kind:'horizontal'|'trend'|'fib';points:DrawingPoint[];levels?:number[]};
type Proposal = {id:string;label:string;evidence:string;lines:Line[];fibonacci?:Retracement};
type Result = {proposals:Proposal[];trace:[number,number][];stale:boolean;evaluated:number};
export type AnalysisDrawingBatch = {horizontal:HorizontalDrawing[];trends:TrendDrawing[];fibos:FibDrawing[]};
const colors:Record<string,string> = {
  resistance:'#ef9474',support:'#4ac6a1',consolidation:'#72a8ed','volume-band':'#af94da','swing-strokes':'#e7b85d',
};
const price = (value:number)=>value.toLocaleString('zh-CN',{maximumFractionDigits:6});

function Preview({trace,proposals}:{trace:Result['trace'];proposals:Proposal[]}) {
  if (!trace.length) return null;
  const width=480, height=128, pad=10;
  const prices=trace.map(([,close])=>close).concat(proposals.flatMap(p=>p.lines.flatMap(l=>l.kind==='fib'?fibPrices(l).map(level=>level.price):l.points.map(a=>a.price))));
  const hi=Math.max(...prices), lo=Math.min(...prices);
  const x=(i:number)=>pad+i*(width-2*pad)/Math.max(trace.length-1,1);
  const y=(v:number)=>hi===lo?height/2:pad+(hi-v)*(height-2*pad)/(hi-lo);
  const path=trace.map(([,v],i)=>x(i)+','+y(v)).join(' ');
  return <svg className="analysis-drawing-preview" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="收盘走势和所选候选线预览">
    <polyline points={path} fill="none" stroke="currentColor" opacity=".65" strokeWidth="1.4"/>
    {proposals.flatMap(p=>p.lines.map(line=>{
      const [a,b]=line.points;
      if(line.kind==='fib') return <g key={line.id}>{fibPrices(line).map(level=>
        <line key={level.ratio} x1={pad} x2={width-pad} y1={y(level.price)} y2={y(level.price)} stroke={level.color} strokeDasharray="5 3"/>
      )}</g>;
      const horizontal=line.kind==='horizontal';
      return <line key={p.id+line.id} x1={horizontal?pad:x(trace.findIndex(([t])=>t===a.time))}
        y1={y(a.price)} x2={horizontal?width-pad:x(trace.findIndex(([t])=>t===b.time))}
        y2={y(horizontal?a.price:b.price)} stroke={colors[p.id]||'#72a8ed'} strokeWidth="2" strokeDasharray={horizontal?'5 3':undefined}/>;
    }))}
  </svg>;
}

function batchFor(proposals:Proposal[]):AnalysisDrawingBatch {
  const batch:AnalysisDrawingBatch={horizontal:[],trends:[],fibos:[]};
  const ids=new Set<string>();
  for(const proposal of proposals) for(const line of proposal.lines){
    if(ids.has(line.id)) continue;
    ids.add(line.id);
    const color=colors[proposal.id];
    if(line.kind==='horizontal') batch.horizontal.push({id:line.id,color,price:line.points[0].price,lineStyle:2,timeframeScope:'current'});
    else if(line.kind==='fib') batch.fibos.push({id:line.id,points:line.points,levels:line.levels,timeframeScope:'current'});
    else batch.trends.push({id:line.id,color,points:line.points,lineWidth:2,extend:'none',timeframeScope:'current'});
  }
  return batch;
}

export default function AnalysisDrawings({chart,onApply}:{chart:AnalysisChart;onApply:(batch:AnalysisDrawingBatch)=>void}){
  const [extensions,setExtensions]=useState('auto');
  const [focus,setFocus]=useState<Focus>('levels');
  const [result,setResult]=useState<Result|null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [notice,setNotice]=useState(''), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const pending=useRef<AbortController|null>(null);
  useEffect(()=>()=>pending.current?.abort(),[]);
  async function generate(){
    if(pending.current) return;
    const controller=new AbortController();
    pending.current=controller;setBusy(true);setResult(null);setError('');setNotice('');
    try {
      const data=await marketAnalysisRequest<Result>({...chart,drawing_focus:focus,extensions,references:[]},controller.signal);
      if(!controller.signal.aborted){setResult(data);setSelected(data.proposals.map(p=>p.id))}
    } catch(e){if(!controller.signal.aborted)setError((e as Error).message)}
    finally{pending.current=null;if(!controller.signal.aborted)setBusy(false)}
  }
  const checked=result?.proposals.filter(p=>selected.includes(p.id))||[];
  return <div className="analysis-drawings">
    <div className="analysis-card">
    <fieldset className="analysis-choices" disabled={busy}><legend>画线类型</legend>{(Object.keys(focusNames) as Focus[]).map(k=>
      <label key={k}><input type="radio" name="analysis-focus" checked={focus===k} onChange={()=>{setFocus(k);setResult(null);setError('');setNotice('')}}/>{focusNames[k]}</label>)}</fieldset>
    {focus==='fibonacci'&&<label className="analysis-select">顺势扩展
      <select aria-label="顺势扩展" disabled={busy} value={extensions} onChange={e=>{setExtensions(e.target.value);setResult(null);setNotice('')}}>
        <option value="auto">自动 · 收盘突破波段终点时显示</option><option value="always">包含扩展线</option><option value="off">仅回撤线</option>
      </select></label>}
    <p>使用{periodNames[chart.period]}已完成的 K 线生成候选，勾选后添加到当前周期。</p>
    <button className="analysis-run" type="button" disabled={busy} onClick={()=>void generate()}>{busy?'正在生成候选…':'生成画线建议'}</button>
    </div>
    {error&&<p role="alert">{error}</p>}
    {result&&<section className="analysis-card" aria-label="画线预览"><h3>候选预览 <small>{result.trace.length} 根已完成 K 线{result.stale?' · 缓存未同步':''}</small></h3>
      {!!result.proposals.length&&<><Preview trace={result.trace} proposals={checked}/>
        <ul className="analysis-proposals">{result.proposals.map(p=><li key={p.id}>
          <label><input type="checkbox" checked={selected.includes(p.id)} onChange={e=>{setSelected(e.target.checked?[...selected,p.id]:selected.filter(id=>id!==p.id));setNotice('')}}/>
            <strong>{p.label}</strong><span>{p.lines.length===1&&p.lines[0].kind==='horizontal'?price(p.lines[0].points[0].price):p.lines[0].kind==='horizontal'?p.lines.map(l=>l.points[0].price).sort((a,b)=>a-b).map(price).join(' – '):p.fibonacci?p.fibonacci.levels.length+' 档':p.lines.length+' 段'}</span></label>
          <small>{p.evidence}</small>
          {p.fibonacci&&<FibonacciLevels value={p.fibonacci} symbol={chart.symbol} period={chart.period}/>}</li>)}</ul>
        <button className="analysis-run" type="button" disabled={!checked.length||!!notice} onClick={()=>{
          try{onApply(batchFor(checked));setError('');setNotice('已添加到当前周期，可在「画线管理」中调整。')}
          catch(e){setError((e as Error).message)}
        }}>添加所选画线</button> {notice&&<p role="status">{notice}</p>}</>}
      {!result.proposals.length&&<p>{result.evaluated?'AI 判断本次候选依据不足。':'这段行情没有形成所选结构。'}</p>}
    </section>}
  </div>;
}
