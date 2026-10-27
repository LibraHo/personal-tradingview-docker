import {useState} from 'react';
import {compute,type Indicator} from './indicators';
import {selectedColor,indicatorDefaultColor} from './histogramColors';
export default function IndicatorAppearance({indicator,onChange}:{indicator:Indicator;onChange:(value:Partial<Indicator>)=>void}){
 const [line,setLine]=useState('');let keys:string[]=[];
 try{if(indicator.name==='PYTHON'){const code=JSON.parse(indicator.params).code||'';keys=[...code.matchAll(/["']([^"'\n]{1,64})["']\s*:/g)].map((x:RegExpMatchArray)=>x[1])}else keys=Object.keys(compute([],indicator.name,indicator.params))}catch{/* Parameter errors are shown by the indicator editor. */}
 keys=[...new Set([...keys,...Object.keys(indicator.colors||{})])].filter(k=>!['hist','volume','stop_long','stop_short','positiveStrong','positiveWeak','negativeStrong','negativeWeak','volumeUp','volumeDown'].includes(k));
 const fields=keys.map((key,i)=>({key,label:key==='main'?'主线':key==='average'?'量均线':key,color:indicatorDefaultColor(indicator.name,key,i)}));
 if(indicator.name==='MACD')fields.push(...[{key:'positiveStrong',label:'正值增强 · 深绿',color:'#26A69A'},{key:'positiveWeak',label:'正值缩小 · 浅绿',color:'#B2DFDB'},{key:'negativeStrong',label:'负值增强 · 深红',color:'#FF5252'},{key:'negativeWeak',label:'负值缩小 · 浅红',color:'#FFCDD2'}]);
 if(indicator.name==='VOLUME')fields.push({key:'volumeUp',label:'上涨成交量',color:'#45caa6'},{key:'volumeDown',label:'下跌成交量',color:'#ed6b7d'});
 const patch=(key:string,color:string)=>onChange({colors:{...indicator.colors,[key]:color}});
 return <details className="indicator-appearance"><summary>线条与配色 · 可单独调整</summary><div className="indicator-colors">{fields.map(f=><label key={f.key}><input type="color" aria-label={`${indicator.title||indicator.name} ${f.label} 颜色`} value={selectedColor(indicator.colors,f.key,f.color)} onChange={e=>patch(f.key,e.target.value)}/><span>{f.label}</span></label>)}</div>{indicator.name==='PYTHON'&&<div className="indicator-color-add"><input aria-label="自定义输出线名称" value={line} maxLength={64} placeholder="Python result 中的线名" onChange={e=>setLine(e.target.value)}/><button disabled={!line.trim()} onClick={()=>{patch(line.trim(),'#74a9ff');setLine('')}}>添加配色</button></div>}<button onClick={()=>onChange({colors:{}})}>恢复默认配色</button></details>;
}
