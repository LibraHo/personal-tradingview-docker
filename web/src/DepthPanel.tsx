import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';

export type DepthLevel={side:'buy'|'sell';price:number;qty:number;amount:number;cached?:boolean};
type Settings={enabled:boolean;amount:number;qty:number;count:number;cached:boolean};
const defaults:Settings={enabled:false,amount:100000,qty:0,count:3,cached:false};
const compact=(n:number)=>new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n);

export default function DepthPanel({symbol,onLines,open,onClose}:{symbol:string;onLines:(lines:DepthLevel[])=>void;open:boolean;onClose:()=>void}){
 const dialog=useRef<HTMLDivElement>(null);
 const instance=useRef(Symbol());
 useEffect(()=>{const changed=(event:Event)=>{const d=(event as CustomEvent).detail;if(d.symbol===symbol&&d.owner!==instance.current)setSettings(d.settings)};window.addEventListener("depth-settings-change",changed);return()=>window.removeEventListener("depth-settings-change",changed)},[symbol]);
 useEffect(()=>{if(!open)return;const previous=document.activeElement as HTMLElement|null;dialog.current?.querySelector('button')?.focus();return()=>previous?.focus()},[open]);
 const [settings,setSettings]=useState<Settings>(()=>{try{return {...defaults,...JSON.parse(localStorage.getItem('depth-settings:'+symbol)||'{}')}}catch{return defaults}});
 const [ready,setReady]=useState(false),[dirty,setDirty]=useState(false),[saved,setSaved]=useState('读取设置…');
 const [data,setData]=useState<any>(null),[error,setError]=useState('');
 const [hidden,setHidden]=useState(document.hidden);
 useEffect(()=>{let cancelled=false;fetch('/api/settings/depth-'+encodeURIComponent(symbol)).then(r=>{if(!r.ok)throw Error();return r.json()}).then(r=>{if(!cancelled){if(r.value&&Object.keys(r.value).length)setSettings(v=>({...v,...r.value}));setSaved('设置保存在 NAS')}}).catch(()=>{if(!cancelled)setSaved('暂用本机设置，NAS 设置读取失败')}).finally(()=>{if(!cancelled)setReady(true)});return()=>{cancelled=true}},[symbol]);
 useEffect(()=>{if(!ready||!dirty)return;let cancelled=false;const timer=setTimeout(async()=>{try{const r=await fetch('/api/settings/depth-'+encodeURIComponent(symbol),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:settings})});if(!r.ok)throw Error();if(!cancelled){setSaved('已保存到 NAS');setDirty(false)}}catch{if(!cancelled)setSaved('NAS 保存失败；本机仍保留设置')}},600);return()=>{cancelled=true;clearTimeout(timer)}},[settings,dirty,ready,symbol]);
 useEffect(()=>{try{localStorage.setItem('depth-settings:'+symbol,JSON.stringify(settings))}catch{}},[settings,symbol]);
 useEffect(()=>{const change=()=>setHidden(document.hidden);document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change)},[]);
 useEffect(()=>{
  setData(null);setError('');if(!ready||!settings.enabled||hidden)return;
  let stopped=false,timer:ReturnType<typeof setTimeout>,controller:AbortController;
  const read=async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),12000);
   try{const response=await fetch('/api/depth?symbol='+encodeURIComponent(symbol),{signal:controller.signal});const result=await response.json();if(!response.ok)throw Error(result.detail||'盘口读取失败');if(!stopped){setData(result);setError('')}}
   catch(e){if(!stopped){setData(null);setError(e instanceof Error?e.message:String(e))}}
   finally{clearTimeout(timeout);if(!stopped)timer=setTimeout(read,2000)}
  };void read();return()=>{stopped=true;clearTimeout(timer);controller?.abort()};
 },[symbol,settings.enabled,hidden,ready]);
 const chosen:DepthLevel[]=settings.enabled&&!hidden&&data&&(data.active||settings.cached)?(['buy','sell'] as const).flatMap(side=>(data.levels as DepthLevel[]).filter(l=>l.side===side&&l.amount>=settings.amount&&l.qty>=settings.qty).sort((a,b)=>b.amount-a.amount).slice(0,Math.min(8,Math.max(1,settings.count))).map(l=>({...l,cached:!data.active}))):[];
 const signature=JSON.stringify(chosen);
 useEffect(()=>{onLines(JSON.parse(signature));return()=>onLines([])},[signature,onLines]);
 const patch=(v:Partial<Settings>)=>{const next={...settings,...v};setSettings(next);setDirty(true);setSaved('正在保存…');window.dispatchEvent(new CustomEvent('depth-settings-change',{detail:{symbol,settings:next,owner:instance.current}}))};
 if(!open)return null;
 return createPortal(<div className="cache-backdrop"><div ref={dialog} className="cache-dialog depth-settings-dialog" role="dialog" aria-modal="true" aria-label="设置 · 盘口挂单线" onKeyDown={e=>{if(e.key==='Escape')onClose();if(e.key==='Tab'){const nodes=dialog.current?.querySelectorAll<HTMLElement>('button,input,select');if(nodes?.length){const first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}}}><div className="cache-title"><div><h2>设置 · 盘口挂单线</h2><p>{symbol} · 按股票保存，对该股票的图表生效</p></div><button onClick={onClose} aria-label="关闭盘口设置">关闭</button></div><section className="depth-panel"><label className="depth-toggle"><input type="checkbox" disabled={!ready} checked={settings.enabled} onChange={e=>patch({enabled:e.target.checked})}/>60 档 · 挂单密集线</label><span className="depth-save-status" role="status">{saved}</span>{settings.enabled&&<>
  <div className="depth-controls"><label>最低金额 USD<input aria-label={symbol+' 盘口最低金额'} type="number" min="0" value={settings.amount} onChange={e=>patch({amount:Math.max(0,Number(e.target.value)||0)})}/></label><label>最低股数<input aria-label={symbol+' 盘口最低股数'} type="number" min="0" value={settings.qty} onChange={e=>patch({qty:Math.max(0,Number(e.target.value)||0)})}/></label><label>每边条数<select aria-label={symbol+' 盘口每边条数'} value={settings.count} onChange={e=>patch({count:Number(e.target.value)})}>{[1,2,3,5,8].map(n=><option key={n}>{n}</option>)}</select></label><label className="depth-toggle"><input type="checkbox" checked={settings.cached} onChange={e=>patch({cached:e.target.checked})}/>休市显示缓存</label></div>
  <p className="depth-note">{error?'读取失败，已清除旧线：'+error:hidden?'页面隐藏，已暂停读取':data?`${data.active?'当前时段盘口':'休市 / 时段未确认，属于缓存'} · 买 ${data.bid_count} / 卖 ${data.ask_count} 档 · 读取 ${new Date(data.read_at*1000).toLocaleTimeString('zh-CN',{hour12:false})}`:'正在读取盘口…'}</p>
  {data&&<small className="depth-note">行情源时间{data.source_time_bid||data.source_time_ask?'：'+(data.source_time_bid||data.source_time_ask):'未提供；读取时间不等于行情更新时间'}。合计挂单可撤销，不代表单笔机构单或确定的支撑阻力。</small>}
  <div className="depth-levels">{chosen.map(l=><span key={l.side+':'+l.price} className={l.side==='buy'?'depth-buy':'depth-sell'}>{l.cached?'缓存 ':''}{l.side==='buy'?'买':'卖'} {l.price.toFixed(l.price>=1?2:4)} · {compact(l.qty)} 股 · ${compact(l.amount)}</span>)}</div>{data?.active&&!chosen.length&&!error&&<small className="depth-note">没有达到筛选条件的价位，可以降低金额或股数门槛。</small>}
 </>}</section></div></div>,document.body);
}
