import {useEffect,useState} from 'react';
import {ArrowLeft,BookOpen,Search} from 'lucide-react';
import {indicatorLabels} from './IndicatorParameters';
import {searchIndicators} from './indicatorSearch';
import {tdxAvailable} from './tdxIndicators';
import {IndicatorGuideContent} from './IndicatorGuide';
import './indicator-library.css';

const featured=['SIXPULSE_SIGNAL','SIXPULSE','FULAI','HAOYUNLAI_WAVE','MSIGM8'];
const names=[...featured,...Object.keys(indicatorLabels).filter(n=>!featured.includes(n)&&(tdxAvailable(n,'CN')||tdxAvailable(n,'US')))];
const fromHash=()=>names.find(n=>'#'+n===location.hash)||featured[0];

export default function IndicatorLibrary(){
 const [query,setQuery]=useState(''),[selected,select]=useState(fromHash);
 const matches=searchIndicators(names,indicatorLabels,query);
 const current=matches.includes(selected)?selected:matches[0];
 useEffect(()=>{
  document.title='指标说明 · NAS Market';
  const sync=()=>{select(fromHash());setQuery('')};
  window.addEventListener('hashchange',sync);
  return ()=>window.removeEventListener('hashchange',sync);
 },[]);
 function choose(name:string){
  if(location.hash!=='#'+name)history.pushState(null,'','#'+name);
  select(name);
  document.querySelector('.guide-reading')?.scrollTo(0,0);
 }
 return <main className="guide-library">
  <header><h1><BookOpen aria-hidden="true"/>指标说明</h1><a href={location.pathname}><ArrowLeft size={16}/>返回图表</a></header>
  <div className="guide-columns"><aside aria-label="指标目录">
   <label className="guide-query"><Search size={16}/><input type="search" aria-label="搜索指标说明" placeholder="搜索指标，如六脉、福来、MACD" value={query} onChange={e=>setQuery(e.target.value)}/></label>
   <nav aria-label="指标列表">{matches.map(name=><button type="button" key={name} aria-current={name===current?'page':undefined} onClick={()=>choose(name)}>{indicatorLabels[name]}</button>)}</nav>
   {matches.length>0&&<select className="guide-mobile-select" aria-label="选择指标教程" value={current} onChange={e=>choose(e.target.value)}>{matches.map(n=><option key={n} value={n}>{indicatorLabels[n]}</option>)}</select>}
  </aside>
  <article key={current} className="guide-reading">{current?<><h2>{indicatorLabels[current]}</h2><IndicatorGuideContent name={current}/></>:<><h2>没有找到匹配的指标</h2><button type="button" onClick={()=>setQuery('')}>清除搜索</button></>}</article></div>
 </main>;
}
