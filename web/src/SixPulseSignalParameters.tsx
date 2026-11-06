import {useState} from 'react';
import {sixPulseRows} from './sixpulse';
import {signalSettings} from './sixpulseSignals';
import './sixpulse.css';
export default function SixPulseSignalParameters({params,onChange}:{params:string;onChange:(s:string)=>void}){
 const [issue,setIssue]=useState('');let input:Record<string,unknown>={};try{input=JSON.parse(params)||{}}catch{}
 let cfg;try{cfg=signalSettings(input)}catch{cfg=signalSettings({})}
 const patch=(next:Record<string,unknown>)=>{try{const merged={...input,...next};signalSettings(merged);onChange(JSON.stringify(merged));setIssue('')}catch(e){setIssue(String(e).replace(/^Error: /,''))}};
 const toggle=(name:string)=>{const enabled=cfg.enabled.includes(name)?cfg.enabled.filter(x=>x!==name):[...cfg.enabled,name];if(!enabled.length){setIssue('至少保留一项指标');return}
  const enter=Math.min(cfg.enter,enabled.length),leave=Math.min(enabled.length,Math.max(cfg.leave,enabled.length-enter+1));patch({enabled,enterReds:enter,exitGreens:leave});
 };
 return <div className="indicator-parameters"><strong>上下车提示规则</strong><p>只计算已勾选项；可以不看 RSI。改变参与项时，门槛会自动调整到有效范围。</p><div className="sixpulse-votes">{sixPulseRows.map(name=><label key={name}><input type="checkbox" aria-label={`六脉主图 参与 ${name}`} checked={cfg.enabled.includes(name)} onChange={()=>toggle(name)}/>{name}</label>)}</div><div className="parameter-grid">
  {([['enterReds','上车至少几红',cfg.enter],['exitGreens','下车至少几绿',cfg.leave]] as const).map(([key,label,value])=><label key={key}>{label}<input type="number" aria-label={label} key={`${key}:${value}:${cfg.enabled.length}`} min={1} max={cfg.enabled.length} step={1} defaultValue={value} onBlur={e=>{if(!e.target.value){setIssue('请输入门槛');return}patch({[key]:Number(e.target.value)})}}/></label>)}
  <label>确认方式<select aria-label="六脉主图确认方式" value={String(cfg.confirm)} onChange={e=>patch({confirm:e.target.value})}><option value="next_bar">下一根出现后确认</option><option value="live">盘中实时（可能变化）</option></select></label></div>
  <small>共 {cfg.enabled.length} 项参与：上车 ≥{cfg.enter} 红，下车 ≥{cfg.leave} 绿。交替提示，不重复刷屏；这是图表状态，不读取实际持仓，也不会下单。</small>{issue&&<div role="alert" className="side-error">{issue}</div>}
 </div>;
}
