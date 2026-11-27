import {lazy, Suspense, useEffect, useMemo, useState} from 'react';
import type {RadarItem} from './MarketRadar';
import './limit-board.css';

const PlanDialog=lazy(()=>import('./ChartPlanDialog'));
type Stock = RadarItem & {price:number|null;streak:number|null;reopen_count:number|null;industry:string|null;
  first_seal:number|null;last_seal:number|null;sealed_funds:number|null;
  turnover_amount:number|null;turnover_pct:number|null;float_market_cap:number|null;
  seal_to_turnover_pct:number|null;seal_to_float_pct:number|null};
type Snapshot = {trade_date:string;dates:string[];sealed:Stock[];broken:Stock[];source:string;updated:number;stale:boolean;error?:string};
const groups = {sealed:'全部封板',first:'首封未开',resealed:'回封',broken:'炸板'};
type Group = keyof typeof groups;
function clock(value:number|null){
  if(!value) return '—';
  const t=String(value).padStart(6,'0');
  return /^([01]\d|2[0-3])([0-5]\d){2}$/.test(t)?[t.slice(0,2),t.slice(2,4),t.slice(4)].join(':'):'—';
}
function funds(n:number|null) {
  if(n==null)return '—';
  return n>=1e8?(n/1e8).toFixed(2)+' 亿':(n/1e4).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 万';
}
export default function LimitBoard({refresh,onOpen}:{refresh:number;onOpen:(item:RadarItem)=>void}){
  const [day,setDay]=useState(''),[data,setData]=useState<Snapshot|null>(null);
  const [dates,setDates]=useState<string[]>([]),[busy,setBusy]=useState(true),[error,setError]=useState('');
  const [group,setGroup]=useState<Group>('sealed'),[query,setQuery]=useState(''),[level,setLevel]=useState('all');
  const [plan,setPlan]=useState<Stock|null>(null);
  useEffect(()=>{
    const ctl=new AbortController();
    setBusy(true);setError('');
    async function load(){
      const res=await fetch('/api/radar/limit-up'+(day?'?day='+encodeURIComponent(day):''),{signal:ctl.signal,cache:'no-store'});
      const result=await res.json();
      if(!res.ok)throw Error(result.detail||'读取打板行情失败');
      if(!ctl.signal.aborted){setData(result);setDates(result.dates)}
    }
    void load().catch(e=>{if(!ctl.signal.aborted)setError(e.message)}).finally(()=>{if(!ctl.signal.aborted)setBusy(false)});
    return ()=>ctl.abort();
  },[day,refresh]);
  const rows=useMemo(()=>{
    if(!data)return [];
    const items=group==='broken'?data.broken:data.sealed;
    const q=query.trim().toLowerCase();
    return items.filter(s=>{
      if(group==='first'&&s.reopen_count!==0)return false;
      if(group==='resealed'&&!(s.reopen_count!=null&&s.reopen_count>0))return false;
      if(group!=='broken'&&level==='first'&&s.streak!==1)return false;
      if(group!=='broken'&&level==='multi'&&!(s.streak!=null&&s.streak>=2))return false;
      return [s.name,s.symbol,s.industry].some(v=>v?.toLowerCase().includes(q));
    }).sort((a,b)=>(b.streak??0)-(a.streak??0)||(a.first_seal||999999)-(b.first_seal||999999)||a.symbol.localeCompare(b.symbol));
  },[data,group,level,query]);
  const total=data?data.sealed.length+data.broken.length:0;
  const missingReopens=data?.sealed.filter(r=>r.reopen_count==null).length||0;
  const missingStreaks=data?.sealed.filter(r=>r.streak==null).length||0;
  const resealed=missingReopens?'—':data?.sealed.filter(r=>r.reopen_count!=null&&r.reopen_count>0).length;
  return <section className="limit-board" aria-label="沪深打板行情">
    <div className="lb-heading"><div><h3>打板行情</h3><p>沪深 A 股 · {data?.source||'涨停池、炸板池'}</p></div>
      <label>交易日 <select aria-label="打板交易日" value={day} onChange={e=>{setDay(e.target.value);setData(null)}}>
        <option value="">最新交易日</option>{dates.map(d=><option key={d}>{d}</option>)}</select></label>
    </div>
    {busy&&<p role="status">正在读取行情…</p>}
    {error&&<p className="radar-warning" role="alert">{data?'刷新失败，保留上次快照。':''}{error}</p>}
    {data&&<>
      <p className="radar-meta">行情日期 {data.trade_date} · 抓取 {new Date(data.updated*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（北京时间）</p>
      {data.stale&&<p role="alert" className="radar-warning">上游更新失败，正在显示该交易日缓存。{data.error}</p>}
      {missingReopens>0&&<p className="radar-warning">有 {missingReopens} 只股票缺少开板次数，回封总数暂不可用。首封和回封筛选只显示有开板记录的股票。</p>}
      {missingStreaks>0&&<p className="radar-warning">有 {missingStreaks} 只股票缺少连板天数，按连板高度筛选时会跳过这些股票。</p>}
      <div className="lb-metrics">{[['封板',data.sealed.length],['其中回封',resealed],['炸板',data.broken.length],['封板率',total?(100*data.sealed.length/total).toFixed(1)+'%':'—']].map(([label,value])=>
        <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
      <div className="lb-filters"><div className="lb-groups" aria-label="封板状态">{(Object.keys(groups) as Group[]).map(k=>
        <button key={k} type="button" aria-pressed={group===k} onClick={()=>setGroup(k)}>{groups[k]}</button>)}</div>
        {group!=='broken'&&<select aria-label="连板高度" value={level} onChange={e=>setLevel(e.target.value)}><option value="all">全部高度</option><option value="first">首板</option><option value="multi">连板（2 板及以上）</option></select>}
        <input aria-label="搜索打板股票" placeholder="名称、代码或行业" value={query} onChange={e=>setQuery(e.target.value)}/>
      </div>
      <div className="radar-table"><table aria-label="打板股票明细"><thead><tr>{['股票','封板状态','连板','现价','首封时间','最近封板','开板次数','封单金额','封单 / 成交额','封单 / 流通市值','换手率','行业','操作'].map(h=><th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map(s=><tr key={s.symbol}>
          <td><button className="radar-name" onClick={()=>onOpen({...s,name:s.name||s.symbol})}>{s.name||s.symbol}</button><small>{s.symbol}</small></td>
          <td>{group==='broken'?'炸板':s.reopen_count==null?'封板':s.reopen_count>0?'回封':'首封未开'}</td>
          <td>{s.streak!=null?s.streak+' 板':'—'}</td><td>{s.price?.toFixed(2)??'—'}</td><td>{clock(s.first_seal)}</td><td>{clock(s.last_seal)}</td>
          <td>{s.reopen_count??'—'}</td><td>{funds(s.sealed_funds)}</td>
          {[s.seal_to_turnover_pct,s.seal_to_float_pct,s.turnover_pct].map((v,i)=><td key={i}>{v==null?'—':v.toFixed(2)+'%'}</td>)}<td>{s.industry||'—'}</td>
          <td><button type="button" onClick={()=>setPlan(s)}>建打板计划</button></td></tr>)}</tbody></table></div>
      <p className="radar-meta">{rows.length?rows.length+' 只股票':'当前筛选没有匹配股票'} · 回封为当前封板且有开板记录；炸板为盘中触板、当前未封住。封板率按两池去重计算。</p>
    </>}
    {plan&&<Suspense fallback={<p role="status">正在打开打板计划…</p>}><PlanDialog market="CN" symbol={plan.symbol} stockName={plan.name}
      period="1d" mode="regular" bars={[]} indicators={[]} limitUp onClose={()=>setPlan(null)}/></Suspense>}
  </section>;
}
