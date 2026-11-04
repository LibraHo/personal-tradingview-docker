import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Activity,X} from 'lucide-react';
import {indicatorPane,type Indicator} from './indicators';
import {indicatorLabels} from './IndicatorParameters';

function scopeReason(i:Indicator,index:number,period:string,symbol:string){
 if(Array.isArray(i.charts)&&!i.charts.includes(index))return '未用于此图';
 if(Array.isArray(i.periods)&&!i.periods.includes(period))return '未用于此周期';
 if(i.name==='ORB5'&&(['1d','1w','1mo'].includes(period)||(!symbol.startsWith('US.')&&period==='240m')))return '仅用于日内图';
 return '';
}
function description(i:Indicator){try{const p=JSON.parse(i.params);if(p.periods)return p.periods.join(' / ');if(i.name==='MACD')return `${p.fast??12} / ${p.slow??26} / ${p.signal??9}`;if(i.name==='STOCH')return `${p.period??14} / ${p.smoothK??3} / ${p.smoothD??3}`;return p.period?`${p.period} 周期`:''}catch{return '参数待修正'}}
export default function QuickIndicators({indicators,index,period,symbol,onToggle}:{indicators:Indicator[];index:number;period:string;symbol:string;onToggle:(id:string,visible:boolean)=>void}){
 const [open,setOpen]=useState(false),[pos,setPos]=useState({left:8,top:80,maxHeight:500});
 const button=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null),id=useId();
 useEffect(()=>{setOpen(false)},[index,period,symbol]);
 useEffect(()=>{
  if(!open)return;
  const place=()=>{const r=button.current?.getBoundingClientRect();if(r){const top=Math.min(r.bottom+8,window.innerHeight-160);setPos({left:Math.max(8,Math.min(r.left,window.innerWidth-352)),top,maxHeight:Math.max(140,window.innerHeight-top-12)})}};
  const outside=(e:PointerEvent)=>{if(!panel.current?.contains(e.target as Node)&&!button.current?.contains(e.target as Node))setOpen(false)};
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setOpen(false);button.current?.focus()}};
  place();panel.current?.querySelector<HTMLButtonElement>('button')?.focus();
  document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true)};
 },[open]);
 const count=indicators.filter(i=>i.visible&&!scopeReason(i,index,period,symbol)).length;
 return <><button ref={button} className="quick-indicator-trigger" aria-label="指标快捷开关" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>setOpen(v=>!v)}><Activity size={13}/> 指标 <small>{count}</small></button>{open&&createPortal(<div ref={panel} id={id} className="quick-indicator-panel" role="dialog" aria-label="指标快捷开关" style={pos}>
  <header><strong>指标快捷开关</strong><button aria-label="关闭指标快捷开关" onClick={()=>{setOpen(false);button.current?.focus()}}><X size={16}/></button></header>
  <p>开关会保存，并应用于该指标已选的图表与周期。</p>
  {(['main','separate'] as const).map(pane=>{const items=indicators.filter(i=>indicatorPane(i)===pane);return items.length>0&&<section key={pane}><h4>{pane==='main'?'主图叠加':'独立副图'}</h4>{items.map((i,n)=>{const reason=scopeReason(i,index,period,symbol);return <label key={i.id} className={reason?'unavailable':''}><span><strong>{i.title||indicatorLabels[i.name]||i.name}{items.some((x,j)=>j!==n&&x.name===i.name)&&` · ${n+1}`}</strong><small>{reason||description(i)||'按已保存参数显示'}</small></span><input type="checkbox" aria-label={`${i.title||i.name} ${i.id} 显示`} checked={i.visible&&!reason} disabled={!!reason} onChange={e=>onToggle(i.id,e.target.checked)}/></label>})}</section>})}
  {!indicators.length&&<p className="quick-indicator-empty">尚未添加指标。</p>}
  <footer>添加指标、参数与配色：右上角「设置 → 指标管理」</footer>
 </div>,document.body)}</>;
}
