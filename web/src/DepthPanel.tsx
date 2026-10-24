import {useEffect,useState} from 'react';

export type DepthLevel={side:'buy'|'sell';price:number;qty:number;amount:number;cached?:boolean};
type Settings={enabled:boolean;amount:number;qty:number;count:number;cached:boolean};
const defaults:Settings={enabled:false,amount:100000,qty:0,count:3,cached:false};
const compact=(n:number)=>new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n);

export default function DepthPanel({symbol,onLines}:{symbol:string;onLines:(lines:DepthLevel[])=>void}){
 const [settings,setSettings]=useState<Settings>(()=>{try{return {...defaults,...JSON.parse(localStorage.getItem('depth-settings:'+symbol)||'{}')}}catch{return defaults}});
 const [data,setData]=useState<any>(null),[error,setError]=useState('');
 const [hidden,setHidden]=useState(document.hidden);
 useEffect(()=>{try{localStorage.setItem('depth-settings:'+symbol,JSON.stringify(settings))}catch{}},[settings,symbol]);
 useEffect(()=>{const change=()=>setHidden(document.hidden);document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change)},[]);
 useEffect(()=>{
  setData(null);setError('');if(!settings.enabled||hidden)return;
  let stopped=false,timer:ReturnType<typeof setTimeout>,controller:AbortController;
  const read=async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),12000);
   try{const response=await fetch('/api/depth?symbol='+encodeURIComponent(symbol),{signal:controller.signal});const result=await response.json();if(!response.ok)throw Error(result.detail||'盘口读取失败');if(!stopped){setData(result);setError('')}}
   catch(e){if(!stopped){setData(null);setError(e instanceof Error?e.message:String(e))}}
   finally{clearTimeout(timeout);if(!stopped)timer=setTimeout(read,2000)}
  };void read();return()=>{stopped=true;clearTimeout(timer);controller?.abort()};
 },[symbol,settings.enabled,hidden]);
 const chosen:DepthLevel[]=settings.enabled&&!hidden&&data&&(data.active||settings.cached)?(['buy','sell'] as const).flatMap(side=>(data.levels as DepthLevel[]).filter(l=>l.side===side&&l.amount>=settings.amount&&l.qty>=settings.qty).sort((a,b)=>b.amount-a.amount).slice(0,Math.min(8,Math.max(1,settings.count))).map(l=>({...l,cached:!data.active}))):[];
 const signature=JSON.stringify(chosen);
 useEffect(()=>{onLines(JSON.parse(signature));return()=>onLines([])},[signature,onLines]);
 const patch=(v:Partial<Settings>)=>setSettings(s=>({...s,...v}));
 return <section className="depth-panel"><label className="depth-toggle"><input type="checkbox" checked={settings.enabled} onChange={e=>patch({enabled:e.target.checked})}/>60 档 · 挂单密集线</label>{settings.enabled&&<>
  <div className="depth-controls"><label>最低金额 USD<input aria-label={symbol+' 盘口最低金额'} type="number" min="0" value={settings.amount} onChange={e=>patch({amount:Math.max(0,Number(e.target.value)||0)})}/></label><label>最低股数<input type="number" min="0" value={settings.qty} onChange={e=>patch({qty:Math.max(0,Number(e.target.value)||0)})}/></label><label>每边条数<select value={settings.count} onChange={e=>patch({count:Number(e.target.value)})}>{[1,2,3,5,8].map(n=><option key={n}>{n}</option>)}</select></label><label className="depth-toggle"><input type="checkbox" checked={settings.cached} onChange={e=>patch({cached:e.target.checked})}/>休市显示缓存</label></div>
  <p className="depth-note">{error?'读取失败，已清除旧线：'+error:hidden?'页面隐藏，已暂停读取':data?`${data.active?'当前时段盘口':'休市 / 时段未确认，属于缓存'} · 买 ${data.bid_count} / 卖 ${data.ask_count} 档 · 读取 ${new Date(data.read_at*1000).toLocaleTimeString('zh-CN',{hour12:false})}`:'正在读取盘口…'}</p>
  {data&&<small className="depth-note">行情源时间{data.source_time_bid||data.source_time_ask?'：'+(data.source_time_bid||data.source_time_ask):'未提供；读取时间不等于行情更新时间'}。合计挂单可撤销，不代表单笔机构单或确定的支撑阻力。</small>}
  <div className="depth-levels">{chosen.map(l=><span key={l.side+':'+l.price} className={l.side==='buy'?'depth-buy':'depth-sell'}>{l.cached?'缓存 ':''}{l.side==='buy'?'买':'卖'} {l.price.toFixed(l.price>=1?2:4)} · {compact(l.qty)} 股 · ${compact(l.amount)}</span>)}</div>{data?.active&&!chosen.length&&!error&&<small className="depth-note">没有达到筛选条件的价位，可以降低金额或股数门槛。</small>}
 </>}</section>;
}
