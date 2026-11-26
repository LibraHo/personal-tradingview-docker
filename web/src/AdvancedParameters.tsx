import {useState} from 'react';
import {advancedCatalog,advancedParams} from './advancedCatalog';
import {tdxCatalog} from './tdxIndicators';
import './sixpulse-parameters.css';

const sixPulseGroups=[
 {name:'MACD',keys:['fast','slow','signal'],labels:['快线','慢线','信号']},
 {name:'KDJ',keys:['kdjPeriod','smoothK','smoothD'],labels:['窗口','K 平滑','D 平滑']},
 {name:'RSI',keys:['rsiFast','rsiSlow'],labels:['快线','慢线']},
 {name:'LWR',keys:['lwrPeriod','lwrSmooth1','lwrSmooth2'],labels:['窗口','一次平滑','二次平滑']},
 {name:'BBI',keys:['bbi1','bbi2','bbi3','bbi4'],labels:['周期 1','周期 2','周期 3','周期 4']},
 {name:'MTM',keys:['mtmFast','mtmFastSmooth','mtmSlow','mtmSlowSmooth'],labels:['快线','快线平滑','慢线','慢线平滑']},
];
export default function AdvancedParameters({name,params,onChange}:{name:string;params:string;onChange:(value:string)=>void}){
 const [issue,setIssue]=useState('');
 const item=advancedCatalog[name];let current:Record<string,unknown>={};try{const p=JSON.parse(params);if(p&&typeof p==='object'&&!Array.isArray(p))current=p}catch{/* Advanced JSON editor remains available. */}
 const source=tdxCatalog[name]?.source;
 const field=(f:typeof item.fields[number],label=f.label)=><label key={f.key}>{label}<input type="number" aria-label={`${name} ${f.label}`} key={`${f.key}:${String(current[f.key]??f.value)}`} defaultValue={Number(current[f.key]??f.value)} min={f.min??(f.step ? .001 : 1)} max={f.max??2000} step={f.step??1} onBlur={e=>{try{if(!e.target.value)throw Error('请输入有效数值');const next={...current,[f.key]:Number(e.target.value)};advancedParams(name,next);onChange(JSON.stringify(next));setIssue('')}catch(error){setIssue(String(error).replace(/^Error: /,''))}}}/></label>;
 const sixPulse=name==='SIXPULSE'||name==='SIXPULSE_SIGNAL';
 const customized=item.fields.some(f=>Number(current[f.key]??f.value)!==f.value);
 if(source)return <><p>{item.description}</p><p><a href={source} target="_blank" rel="noreferrer">查看原始指标说明</a></p></>;
 return <>{sixPulse?<div className="sixpulse-parameters">
  <p className="sixpulse-caption">{name==='SIXPULSE'?'六项指标共同观察多空方向；未收线时信号会变化。':'各项计算周期独立设置，默认使用 Mai 参数。'}</p>
  <details className="sixpulse-calculation"><summary><span>计算参数</span><small>{customized?'已自定义':'Mai 默认'} · 6 组指标</small></summary>
   <div className="sixpulse-parameter-groups">{sixPulseGroups.map(group=><fieldset key={group.name}><legend>{group.name}</legend><div className="sixpulse-fields">{group.keys.map((key,i)=>{const f=item.fields.find(f=>f.key===key);return f?field(f,group.labels[i]):null})}</div></fieldset>)}</div>
  </details>
  <details className="sixpulse-help"><summary>指标说明与计算口径</summary><p>{item.description}</p></details>
 </div>:name==='MSIGM8'?<div className="sixpulse-parameters"><p className="sixpulse-caption">绿箭头买入，红箭头卖出；连线标记突破价位。缓冲比例 0.0003 = 0.03%。</p><div className="parameter-grid">{item.fields.map(f=>field(f))}</div><details className="sixpulse-help"><summary>指标说明与计算口径</summary><p>{item.description}</p></details></div>:<><p>{item.description}</p><div className="parameter-grid">{item.fields.map(f=>field(f))}</div></>}{!item.fields.length&&<small>无周期参数；直接使用已加载的 K 线。</small>}{issue&&<div role="alert" className="side-error">{issue}</div>}</>;
}
