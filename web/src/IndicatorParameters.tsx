import {useState} from 'react';
import type {Indicator} from './indicators';

export const indicatorLabels:Record<string,string>={EMA:'EMA · 指数移动平均线',SMA:'MA · 简单移动平均线',MACD:'MACD · 平滑异同移动平均',VWAP:'VWAP · 成交量加权均价',BBI:'BBI · 多空均线',BOLL:'BOLL · 布林带',ATR:'ATR · 平均真实波幅',DMI:'DMI / ADX · 趋向指标',RSI:'RSI · 相对强弱',VOLUME:'成交量 / 量均线'};
export const indicatorDefaults:Record<string,Record<string,unknown>>={EMA:{periods:[5,10,20]},SMA:{periods:[5,10,20]},MACD:{fast:12,slow:26,signal:9},VWAP:{reset:'session'},BBI:{periods:[3,6,12,24]},BOLL:{period:20,stddev:2},ATR:{period:14,multiplier:2},DMI:{period:14},RSI:{period:14},VOLUME:{period:20}};
export default function IndicatorParameters({indicator,onChange}:{indicator:Indicator;onChange:(params:string)=>void}){
 const [issue,setIssue]=useState('');
 let parsed:Record<string,any>={};try{parsed=JSON.parse(indicator.params)}catch{/* Keep malformed legacy input repairable below. */}
 const p:Record<string,any>={...indicatorDefaults[indicator.name],period:14,...parsed};
 const patch=(key:string,value:unknown)=>{onChange(JSON.stringify({...parsed,[key]:value}));setIssue('')};
 const numeric=(key:string,label:string,fallback:number,step='1')=><label key={key}>{label}<input aria-label={`${indicator.name} ${label}`} type="number" min={step==='1'?1:0.01} max={key==='multiplier'||key==='stddev'?100:2000} step={step} key={String(p[key])} defaultValue={p[key]??fallback} onBlur={e=>{const value=Number(e.target.value);if(!e.target.value||!Number.isFinite(value)||value<=0||value>2000||(step==='1'&&!Number.isInteger(value))){setIssue(`${label}请输入有效正数`);return}if(indicator.name==='MACD'&&((key==='fast'&&value>=Number(p.slow))||(key==='slow'&&value<=Number(p.fast)))){setIssue('MACD 慢线周期须大于快线周期');return}patch(key,value)}}/></label>;
 const list=['EMA','SMA','BBI'].includes(indicator.name);
 const values=parsed.periods??(parsed.period?[parsed.period]:p.periods);
 return <div className="indicator-parameters">
  <small>{indicatorLabels[indicator.name]||indicator.name}{indicator.name==='EMA'?'：近期价格权重更高，周期以当前图表 K 线根数计。':indicator.name==='SMA'?'：最近 N 根收盘价的算术平均。':''}</small>
  {list?<><label>均线周期（逗号分隔）<input aria-label={`${indicator.name} 均线周期`} key={JSON.stringify(values)} defaultValue={values?.join(',')} placeholder="5,10,20" onBlur={e=>{const parts=e.target.value.split(/[,，\s]+/).filter(Boolean),nums=parts.map(Number);if(!nums.length||nums.length>12||nums.some(n=>!Number.isInteger(n)||n<1||n>2000)){setIssue('请输入 1–2000 的整数周期，最多 12 条');return}const next:Record<string,any>={...parsed,periods:[...new Set(nums)]};delete next.period;onChange(JSON.stringify(next));setIssue('')}}/></label>{indicator.name!=='BBI'&&<div className="scope-chips">{[[5,10,20],[5,10,20,60],[12,26]].map(v=><button key={v.join()} onClick={()=>{const next:Record<string,any>={...parsed,periods:v};delete next.period;onChange(JSON.stringify(next));setIssue('')}}>{v.join(' / ')}</button>)}</div>}</>:indicator.name==='MACD'?<div className="parameter-grid">{numeric('fast','快线周期',12)}{numeric('slow','慢线周期',26)}{numeric('signal','信号周期',9)}</div>:indicator.name==='VWAP'?<label>重置边界<select aria-label="VWAP 重置边界" value={p.reset} onChange={e=>patch('reset',e.target.value)}><option value="session">每个交易时段</option><option value="day">每个交易日</option><option value="never">不重置</option></select></label>:indicator.name!=='CUSTOM'&&<div className="parameter-grid">{numeric('period','计算周期',14)}{indicator.name==='BOLL'&&numeric('stddev','标准差倍数',2,'0.1')}{indicator.name==='ATR'&&numeric('multiplier','止损倍数',2,'0.1')}</div>}
  {issue&&<div role="alert" className="side-error">{issue}</div>}
  <details><summary>高级参数（JSON）</summary><input className="params" aria-label={`${indicator.name} 高级参数`} value={indicator.params} onChange={e=>onChange(e.target.value)} spellCheck={false}/></details>
 </div>;
}
