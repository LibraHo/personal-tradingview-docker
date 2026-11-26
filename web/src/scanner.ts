import {compute, type Bar} from './indicators';
import {tdxCatalog} from './tdxIndicators';

export type Operand = {name:string; line:string; params:Record<string,number>; value:number; scale?:number; offset?:number};
export type Rule = {name?:string; left:Operand; op:string; right:Operand; period?:string; offset?:number; temporal?:string; window?:number; min_count?:number; max_count?:number|null};
export const catalog:Record<string,{label:string; lines:string[]; params:Record<string,number>}> = {
  PRICE:{label:'价格 / 成交量',lines:['close','open','high','low','volume'],params:{}},
  NUMBER:{label:'固定数值',lines:[],params:{}},
  SMA:{label:'MA 均线',lines:['main'],params:{period:20}},
  EMA:{label:'EMA 指数均线',lines:['main'],params:{period:20}},
  SIXPULSE:{label:'六脉',lines:['REDS','GREENS','MACD','KDJ','RSI','LWR','BBI','MTM'],params:{fast:8,slow:13,signal:5,kdjPeriod:8,smoothK:3,smoothD:3,rsiFast:5,rsiSlow:13,lwrPeriod:13,lwrSmooth1:3,lwrSmooth2:3,bbi1:3,bbi2:6,bbi3:12,bbi4:24,mtmFast:5,mtmFastSmooth:3,mtmSlow:13,mtmSlowSmooth:8}},
  MACD:{label:'MACD',lines:['macd','signal','hist'],params:{fast:12,slow:26,signal:9}},
  RSI:{label:'RSI',lines:['main'],params:{period:14}},
  BOLL:{label:'布林带',lines:['upper','mid','lower'],params:{period:20,stddev:2}},
  VOLUME:{label:'成交量',lines:['volume','average'],params:{period:20}},
  DMI:{label:'DMI / ADX',lines:['plus_di','minus_di','adx'],params:{period:14}},
  ATR:{label:'ATR',lines:['main'],params:{period:14}},
};
Object.assign(catalog,Object.fromEntries(Object.entries(tdxCatalog).map(([name,item])=>[name,{label:item.label,lines:Object.keys(item.outputs).filter(k=>item.outputs[k]!==null),params:{}}])));
export const operators:Record<string,string>={gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于',eq:'等于',cross_above:'刚大于（上穿）',cross_below:'刚小于（下穿）',reach:'刚达到或超过',fall:'刚降至或低于',enter_eq:'刚等于（任一方向）',rise_eq:'刚从下方升至等于',fall_eq:'刚从上方降至等于'};
export function operand(name:string):Operand{return {name,line:catalog[name].lines[0]||'',params:{...catalog[name].params},value:6}}
export function defaultRule():Rule{return {left:operand('SIXPULSE'),op:'reach',right:operand('NUMBER')}}
export function scanBars(bars:Bar[],rules:Rule[],join:string,lookback:number,live:boolean){
  if(!rules.length)throw Error('请添加条件');
  const cache=new Map<string,(number|null)[]>();
  const series=(o:Operand)=>{
    const key=JSON.stringify(o);
    if(cache.has(key))return cache.get(key)!;
    if(!catalog[o.name]||Object.entries(o.params).some(([key,n])=>!Number.isFinite(n)||n<=0||n>500||(key!=='stddev'&&!Number.isInteger(n))))throw Error('周期参数须为 1–500 的整数，标准差倍数须为正数');
    let values:(number|null)[];
    if(o.name==='NUMBER'){
      if(!Number.isFinite(o.value))throw Error('比较数值无效');
      values=bars.map(()=>o.value);
    }else if(o.name==='PRICE')values=bars.map(b=>Number(b[o.line as keyof Bar]));
    else{
      const result=compute(bars,o.name,JSON.stringify(o.params));
      values=o.name==='SIXPULSE'&&['REDS','GREENS'].includes(o.line)?result.SCORE.map(v=>v===null?null:o.line==='REDS'?v:6-v):result[o.line];
      if(!values)throw Error('指标输出不存在');
    }
    cache.set(key,values);return values;
  };
  const sources=rules.map(r=>({rule:r,a:series(r.left),b:series(r.right)}));
  // A following candle confirms completion, including daily/weekly sessions.
  const end=bars.length-(live?1:2);
  if(end<1)throw Error('完整 K 线不足');
  let available=false;
  for(let i=end;i>=Math.max(1,end-lookback+1);i--){
    const checks=sources.map(({rule,a,b})=>{
      const x=a[i],y=b[i],px=a[i-1],py=b[i-1];
      const crossing=['cross_above','cross_below','reach','fall','enter_eq','rise_eq','fall_eq'].includes(rule.op);
      if(x==null||y==null||!Number.isFinite(x)||!Number.isFinite(y)||(crossing&&(px==null||py==null)))return {ok:false,valid:false,left:x,right:y};
      const matches:Record<string,boolean>={gt:x>y,gte:x>=y,lt:x<y,lte:x<=y,eq:x===y,cross_above:px!<=py!&&x>y,cross_below:px!>=py!&&x<y,reach:px!<py!&&x>=y,fall:px!>py!&&x<=y,enter_eq:px!==py&&x===y,rise_eq:px!<py!&&x===y,fall_eq:px!>py!&&x===y};
      return {ok:matches[rule.op]===true,valid:true,left:x,right:y};
    });
    const valid=join==='all'?checks.every(c=>c.valid):checks.some(c=>c.valid);
    available ||= valid;
    if(valid&&(join==='all'?checks.every(c=>c.ok):checks.some(c=>c.ok)))return {match:true,time:bars[i].time,checks};
  }
  if(!available)throw Error('指标预热数据不足');
  return {match:false,time:bars[end].time,checks:[]};
}
