import {useState} from 'react';
import {advancedCatalog,advancedParams} from './advancedCatalog';
export default function AdvancedParameters({name,params,onChange}:{name:string;params:string;onChange:(value:string)=>void}){
 const [issue,setIssue]=useState('');
 const item=advancedCatalog[name];let current:Record<string,unknown>={};try{const p=JSON.parse(params);if(p&&typeof p==='object'&&!Array.isArray(p))current=p}catch{/* Advanced JSON editor remains available. */}
 return <><p>{item.description}</p><div className="parameter-grid">{item.fields.map(f=><label key={f.key}>{f.label}<input type="number" aria-label={`${name} ${f.label}`} key={`${f.key}:${String(current[f.key]??f.value)}`} defaultValue={Number(current[f.key]??f.value)} min={f.step ? .001 : 1} max={f.max??2000} step={f.step??1} onBlur={e=>{try{if(!e.target.value)throw Error('请输入有效数值');const next={...current,[f.key]:Number(e.target.value)};advancedParams(name,next);onChange(JSON.stringify(next));setIssue('')}catch(error){setIssue(String(error).replace(/^Error: /,''))}}}/></label>)}</div>{!item.fields.length&&<small>无周期参数；直接使用已加载的 K 线。</small>}{issue&&<div role="alert" className="side-error">{issue}</div>}</>;
}
