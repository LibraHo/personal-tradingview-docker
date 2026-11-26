import IndicatorGuide from './IndicatorGuide';
import {fixedPeriodLabel,tdxCatalog} from './tdxIndicators';
import {useState} from 'react';
import {Search,Plus} from 'lucide-react';
import {indicatorLabels} from './IndicatorParameters';
import {indicatorPane} from './indicators';
import {searchIndicators} from './indicatorSearch';
import './indicator-picker.css';

type Pane='main'|'separate';
type Props={onConfigureDepth?:()=>void;names:string[];value:string;pane:Pane;marketLabel:string;onSelect:(name:string)=>void;onPaneChange:(pane:Pane)=>void;onAdd:(name:string,pane:Pane)=>void};
const quick=[{name:'MSIGM8',label:'MACD突破'},{name:'SIXPULSE_SIGNAL',label:'六脉 · 主图上下车'},{name:'SIXPULSE',label:'六脉 · 六项共振'}];
export default function IndicatorPicker({names,value,pane,marketLabel,onSelect,onPaneChange,onAdd,onConfigureDepth}:Props){
 const [query,setQuery]=useState(''),[notice,setNotice]=useState(''),[browse,setBrowse]=useState(false);
 const matches=searchIndicators(names,indicatorLabels,query),selected=matches.includes(value)?value:matches[0]||'';
 const depthMatch=Boolean(onConfigureDepth&&searchIndicators(['DEPTH'],{DEPTH:'盘口密集线 盘口挂单密集线 挂档密集线'},query).length);
 const resultCount=matches.length+Number(depthMatch);
 const changeQuery=(next:string)=>{setQuery(next);setNotice('');if(!next.trim())setBrowse(false);const found=searchIndicators(names,indicatorLabels,next);if(found.length&&!found.includes(value))onSelect(found[0])};
 const showResults=!!query.trim()||browse;
 const add=(name:string,target:Pane)=>{
  const formula=tdxCatalog[name];
  target=formula?.pane||target;
  onAdd(name,target);
  setNotice(`已添加「${indicatorLabels[name]||name}」到${marketLabel}${target==='main'?'主图':'副图'}${formula?.period?'，切到'+fixedPeriodLabel(formula.period)+'查看。':''}`);
 };
 return <section className="indicator-picker" aria-label="查找与添加指标">
  <small className="indicator-picker-market">添加到当前市场：{marketLabel}</small>
  <div className="indicator-quick-add"><span>快捷添加</span>{quick.filter(item=>names.includes(item.name)).map(item=><button type="button" key={item.name} aria-label={`快速添加 ${item.label}`} onClick={()=>add(item.name,indicatorPane({name:item.name}))}><Plus size={12}/>{item.label}</button>)}</div>
  <div className="indicator-search"><Search size={16} aria-hidden="true"/><input type="search" aria-label="搜索指标" placeholder="搜索名称或简称，如 MACD、突破、六脉" value={query} onChange={e=>changeQuery(e.target.value)}/>{query&&<button type="button" aria-label="清除指标搜索" onClick={()=>changeQuery('')}>清除</button>}{showResults&&<span role="status">{resultCount} 项</span>}</div>
  {!query.trim()&&<button type="button" className="indicator-browse" aria-expanded={browse} onClick={()=>setBrowse(!browse)}>{browse?'收起指标列表':`浏览全部 ${names.length+Number(!!onConfigureDepth)} 个指标`}</button>}
  {showResults&&<><div className="indicator-search-results" role="group" aria-label="指标搜索结果">{depthMatch&&<button type="button" onClick={onConfigureDepth}><span>盘口密集线</span><small>设置主图指标</small></button>}{matches.map(name=><button type="button" key={name} aria-label={`选择 ${indicatorLabels[name]||name}`} aria-pressed={selected===name} onClick={()=>onSelect(name)}><span>{indicatorLabels[name]||name}</span><small>{indicatorPane({name})==='main'?'主图':'副图'}</small></button>)}</div>
  {matches.length>0&&<div className="add-indicator"><span className="indicator-selected">{selected?`已选：${indicatorLabels[selected]||selected}`:'请选择指标'}</span><select aria-label="新指标绘制位置" disabled={!selected||!!tdxCatalog[selected]||['ORB5','SIXPULSE','SIXPULSE_SIGNAL','MSIGM8'].includes(selected)} value={pane} onChange={e=>onPaneChange(e.target.value as Pane)}><option value="main">主图叠加</option><option value="separate">独立副图</option></select><button type="button" className="primary" disabled={!selected} onClick={()=>selected&&add(selected,pane)}><Plus size={14}/>添加指标</button></div>}</>}
  {showResults&&selected&&<IndicatorGuide key={selected} name={selected}/>}
  {!resultCount&&<p className="indicator-search-empty">没有找到“{query}”，试试中文名称或英文简称。</p>}
  {notice&&<p className="indicator-add-notice" role="status">{notice}</p>}
 </section>;
}
