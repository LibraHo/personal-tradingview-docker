import {useEffect,useState} from 'react';
import {mergeFlow,type Flow,type Tick} from './marketFlow';
import './market-flow.css';

type ProfileRow = {strike:number;call:number|null;put:number|null};
const amount = (n:number|null) => n === null ? '—' : n.toLocaleString('en-US');
const price = (n:number) => n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6});

async function read<T>(path:string, params:Record<string,string>, signal:AbortSignal):Promise<T>{
 const response = await fetch('/api/'+path+'?'+new URLSearchParams(params),{signal,cache:'no-store'});
 if (!response.ok) {
  const result = await response.json().catch(()=>null);
  throw Error(typeof result?.detail === 'string' ? result.detail : '行情读取失败');
 }
 return response.json();
}

function OptionsVolume({symbol}:{symbol:string}){
 const [dates,setDates] = useState<string[]>([]);
 const [expiry,setExpiry] = useState('');
 const [profile,setProfile] = useState<{expiry:string;rows:ProfileRow[]}>();
 const [datesError,setDatesError] = useState('');
 const [datesLoaded,setDatesLoaded] = useState(false);
 const [error,setError] = useState('');
 const [refresh,setRefresh] = useState(0);

 useEffect(()=>{
  const controller = new AbortController();
  read<{expirations:string[]}>('option-profile',{symbol},controller.signal).then(result=>{
   if (controller.signal.aborted) return;
   setDatesLoaded(true);
   setDates(result.expirations);
   setExpiry(result.expirations[0] ?? '');
  }).catch(e=>{if (!controller.signal.aborted) setDatesError(e.message)});
  return ()=>controller.abort();
 },[symbol]);
 useEffect(()=>{
  if (!expiry) return;
  const controller = new AbortController();
  read<{rows:ProfileRow[]}>('option-profile',{symbol,expiry},controller.signal).then(result=>{
   if (!controller.signal.aborted) setProfile({expiry,rows:result.rows});
  }).catch(e=>{if (!controller.signal.aborted) setError(e.message)});
  return ()=>controller.abort();
 },[symbol,expiry,refresh]);

 const rows = profile?.expiry === expiry ? profile.rows : [];
 const max = rows.reduce((n,row)=>Math.max(n,row.call ?? 0,row.put ?? 0),1);
 return <>
  <label>到期日 <select value={expiry} onChange={e=>{setError('');setExpiry(e.target.value)}}>
   {!dates.length && <option value="">暂无到期日</option>}
   {dates.map(date=><option key={date}>{date}</option>)}
  </select></label>
  <button disabled={!expiry} onClick={()=>{setError('');setProfile(undefined);setRefresh(n=>n+1)}}>刷新</button>
  <p>当日合约成交量（张） · — 表示未取得数据</p>
  {(datesError||error) && <p role="alert">{datesError||error}</p>}
  {!datesError&&!error&&!rows.length && <p role="status">{datesLoaded&&!dates.length?'该标的暂无可用到期日':!profile||profile.expiry!==expiry?'等待行情…':'该到期日暂无合约'}</p>}
  {!!rows.length && <div className="market-flow-scroll"><table>
   <thead><tr><th>Call</th><th>行权价</th><th>Put</th></tr></thead>
   <tbody>{rows.map(row=><tr key={row.strike}>
    <td className="flow-buy" style={{'--fill':100*(row.call??0)/max+'%'} as React.CSSProperties}>{amount(row.call)}</td>
    <th scope="row">{price(row.strike)}</th>
    <td className="flow-sell" style={{'--fill':100*(row.put??0)/max+'%'} as React.CSSProperties}>{amount(row.put)}</td>
   </tr>)}</tbody>
  </table></div>}
 </>;
}

function OrderFlow({symbol,tab}:{symbol:string;tab:'cvd'|'footprint'}){
 const [flow,setFlow] = useState<Flow|null>(null);
 const [error,setError] = useState('');
 const [minute,setMinute] = useState('');
 useEffect(()=>{
  let timer:ReturnType<typeof setTimeout>;
  let controller:AbortController;
  let stopped=false;
  const poll = async()=>{
   if (!document.hidden) {
    controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),10000);
    try {
     const data=await read<{ticks:Tick[]}>('order-flow',{symbol},controller.signal);
     if (!stopped) {setFlow(old=>mergeFlow(old,data.ticks));setError('')}
    } catch(e) {
     if (!stopped) setError(e instanceof Error ? e.message : '逐笔行情读取失败');
    } finally {clearTimeout(timeout)}
   }
   if (!stopped) timer=setTimeout(poll,1000);
  };
  void poll();
  return ()=>{stopped=true;clearTimeout(timer);controller?.abort()};
 },[symbol]);

 if (!flow) return <p role={error?'alert':'status'}>{error||'等待常规时段逐笔成交…'}</p>;
 const bars=flow.bars;
 const selected=bars.find(bar=>bar.time===minute) ?? bars[bars.length-1];
 const levels=[...selected.levels].sort((a,b)=>b.price-a.price);
 const poc=levels.reduce((best,level)=>level.buy+level.sell+level.neutral>best.buy+best.sell+best.neutral?level:best,levels[0]);
 const min=Math.min(0,...bars.map(bar=>bar.cvd));
 const max=Math.max(0,...bars.map(bar=>bar.cvd));
 const minutes=(bar:typeof bars[number])=>Number(bar.time.slice(11,13))*60+Number(bar.time.slice(14,16));
 const minuteOffsets=bars.map(bar=>minutes(bar)-minutes(bars[0]));
 const points=bars.map((bar,i)=>[10+580*minuteOffsets[i]/Math.max(1,minuteOffsets[minuteOffsets.length-1]),110-100*(bar.cvd-min)/Math.max(1,max-min)]);
 return <>
  <p>美东常规时段 · 累计起点 {flow.start} · 最后一笔 {flow.last.time}</p>
  {flow.gap && <p role="status">近期逐笔出现数据缺口，已从可见成交重新累计。</p>}
  {error && <p role="alert">更新暂停，保留上次结果。{error}</p>}
  {tab==='cvd'? <>
   <p><strong>CVD {amount(flow.cvd)}</strong> 股</p>
   <svg viewBox="0 0 600 120" role="img" aria-label="累计成交量差走势" className="flow-chart">
    <line x1="10" x2="590" y1={110+100*min/Math.max(1,max-min)} y2={110+100*min/Math.max(1,max-min)} stroke="currentColor" opacity=".35"/>
    <polyline points={points.map(point=>point.join(',')).join(' ')} fill="none" stroke="#3da5ee" strokeWidth="2"/>
    {points.length===1&&<circle cx={points[0][0]} cy={points[0][1]} r="4" fill="#3da5ee"/>}
   </svg>
  </>:<>
   <label>1 分钟足迹 <select value={minute===selected.time?minute:''} onChange={e=>setMinute(e.target.value)}>
    <option value="">最新一分钟</option>
    {[...bars].reverse().map(bar=><option key={bar.time} value={bar.time}>{bar.time.slice(11)}</option>)}
   </select></label>
   <p>Delta {amount(selected.delta)} 股 · POC {price(poc.price)}</p>
   <div className="market-flow-scroll"><table>
    <thead><tr><th>价位</th><th>买量</th><th>卖量</th><th>未分类</th><th>Delta</th></tr></thead>
    <tbody>{levels.map(level=><tr key={level.price} className={level===poc?'flow-poc':undefined}>
     <th scope="row">{price(level.price)}</th><td>{amount(level.buy)}</td><td>{amount(level.sell)}</td>
     <td>{amount(level.neutral)}</td><td>{amount(level.buy-level.sell)}</td>
    </tr>)}</tbody>
   </table></div>
  </>}
 </>;
}

export default function MarketFlowPanel({symbol}:{symbol:string}){
 const [open,setOpen] = useState(false);
 const [tab,setTab] = useState<'ovp'|'cvd'|'footprint'>('ovp');
 return <details className="market-flow" onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary>订单流与期权成交量</summary>
  {open&&<div className="market-flow-body">
   <div className="flow-tabs" aria-label="指标">
    {(['ovp','cvd','footprint'] as const).map((item,i)=><button key={item} aria-pressed={tab===item} onClick={()=>setTab(item)}>
     {['期权成交量 OVP','累计成交量差 CVD','成交量足迹'][i]}
    </button>)}
   </div>
   {tab==='ovp'?<OptionsVolume symbol={symbol}/>:<OrderFlow symbol={symbol} tab={tab}/>}
  </div>}
 </details>;
}
