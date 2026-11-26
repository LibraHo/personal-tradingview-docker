import {useEffect, useState} from 'react';
import {ledgerRequest} from './tradeBookClient';
import type {ReviewMarket} from './reviewClient';

type Run = {id:string;started:string;finished:string|null;status:'running'|'failed'|'success'|'unknown';provider:string;error:string};
const states = {running:'处理中',failed:'失败',success:'已完成',unknown:'结果待核对'};

function browserKey(market:ReviewMarket,symbol:string){return 'plan-fill-errors:'+market+':'+symbol}
function browserErrors(market:ReviewMarket,symbol:string):Run[]{
  try {return JSON.parse(localStorage.getItem(browserKey(market,symbol))||'[]')} catch{return []}
}
export function recordDeliveryError(market:ReviewMarket,symbol:string,id:string,started:number,error:string){
  const run:Run = {id,started:new Date(started).toISOString(),finished:null,status:'unknown',provider:'browser',error};
  try {localStorage.setItem(browserKey(market,symbol),JSON.stringify([run,...browserErrors(market,symbol)].slice(0,30)))} catch{}
}

export default function FillHistory({market,symbol,revision}:{market:ReviewMarket;symbol:string;revision:number}) {
  const [open,setOpen] = useState(false), [refresh,setRefresh] = useState(0);
  const [rows,setRows] = useState<Run[]>([]), [notice,setNotice] = useState('');
  useEffect(()=>{
    if(!open) return;
    const controller = new AbortController();
    setRows([]);setNotice('读取中…');
    const local = browserErrors(market,symbol);
    ledgerRequest<{items:Run[]}>(market,'autofill/history?symbol='+encodeURIComponent(symbol),'GET',undefined,controller.signal)
      .then(({items})=>{
        if(controller.signal.aborted) return;
        const received = new Set(items.map(row=>row.id));
        const merged = [...items,...local.filter(row=>!received.has(row.id))].sort((a,b)=>b.started.localeCompare(a.started));
        setRows(merged.slice(0,30));setNotice(merged.length?'':'暂无填表记录');
      })
      .catch(error=>{if(!controller.signal.aborted){setRows(local);setNotice('服务器记录暂不可用 · '+error.message)}});
    return ()=>controller.abort();
  },[open,market,symbol,revision,refresh]);
  return <details className="plan-fill-history" onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary>填表记录</summary>
    {open&&<><button type="button" onClick={()=>setRefresh(n=>n+1)}>刷新记录</button>
      {notice&&<p role="status">{notice}</p>}<ol>{rows.map(row=><li key={row.id}>
        <strong>{states[row.status]}</strong> · {row.provider==='browser'?'浏览器记录':row.provider==='openclaw'?'OpenClaw':'本地规则'} · {new Date(row.started).toLocaleString('zh-CN')}
        {row.error&&<div>{row.error}</div>}<small>请求编号 <code>{row.id}</code></small>
      </li>)}</ol></>}
  </details>;
}
