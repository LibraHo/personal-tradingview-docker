import {formula} from './formula';
export type Bar = {time:number;open:number;high:number;low:number;close:number;volume:number;session:string;trade_date:string;session_date:string};
export type Indicator = {id:string;name:string;params:string;visible:boolean;title?:string;pane?:'main'|'separate'};
const sma=(v:(number|null)[],n:number)=>(v.map((_,i)=>i>=n-1&&v.slice(i-n+1,i+1).every(x=>x!==null)?v.slice(i-n+1,i+1).reduce<number>((a,b)=>a+(b||0),0)/n:null));
const ema=(v:(number|null)[],n:number)=>{let last:number|null=null;return v.map(x=>{if(x===null)return null;last=last===null?x:last+(x-last)*2/(n+1);return last})};
export function compute(b:Bar[],name:string,params:string):Record<string,(number|null)[]>{
  let p:Record<string,any>={};try{p=JSON.parse(params)}catch{return {error:[]}}
  const c=b.map(x=>x.close), h=b.map(x=>x.high), l=b.map(x=>x.low),v=b.map(x=>x.volume),n=Math.max(1,Number(p.period)||14);
  if(name==='CUSTOM')return {main:formula(String(p.formula||''))(b)};
  if(name==='SMA')return {main:sma(c,n)};
  if(name==='EMA')return {main:ema(c,n)};
  if(name==='BBI'){const a=(p.periods||[3,6,12,24]).map((x:number)=>sma(c,Math.max(1,x))) as (number|null)[][];return {main:c.map((_,i)=>a.every(row=>row[i]!==null)?a.reduce((sum,row)=>sum+(row[i]||0),0)/a.length:null)}}
  if(name==='MACD'){const f=ema(c,Number(p.fast)||12),s=ema(c,Number(p.slow)||26),m=c.map((_,i)=>(f[i]||0)-(s[i]||0)),signal=ema(m,Number(p.signal)||9);return {macd:m,signal,hist:m.map((x,i)=>x-(signal[i]||0))}}
  if(name==='BOLL'){const mid=sma(c,n),scale=Number(p.stddev)||2;return {mid,upper:c.map((_,i)=>i<n-1?null:(mid[i]||0)+scale*Math.sqrt(c.slice(i-n+1,i+1).reduce((a,x)=>a+(x-(mid[i]||0))**2,0)/n)),lower:c.map((_,i)=>i<n-1?null:(mid[i]||0)-scale*Math.sqrt(c.slice(i-n+1,i+1).reduce((a,x)=>a+(x-(mid[i]||0))**2,0)/n))}}
  if(name==='RSI'){const gain=ema(c.map((x,i)=>i?Math.max(0,x-c[i-1]):0),n),loss=ema(c.map((x,i)=>i?Math.max(0,c[i-1]-x):0),n);return {main:c.map((_,i)=>loss[i]?100-100/(1+(gain[i]||0)/(loss[i]||1)):100)}}
  if(name==='VWAP'){let pv=0,vol=0,previous='';return {main:b.map(x=>{const key=p.reset==='never'?'all':p.reset==='day'?x.trade_date:x.session_date;if(key!==previous){pv=0;vol=0}previous=key;pv+=(x.high+x.low+x.close)/3*x.volume;vol+=x.volume;return vol?pv/vol:null})}}
  if(name==='VOLUME')return {volume:v,average:sma(v,n)};
  const tr=b.map((x,i)=>i?Math.max(x.high-x.low,Math.abs(x.high-c[i-1]),Math.abs(x.low-c[i-1])):x.high-x.low),atr=ema(tr,n);
  if(name==='ATR'){const k=Number(p.multiplier)||2;return {main:atr,stop_long:c.map((x,i)=>x-k*(atr[i]||0)),stop_short:c.map((x,i)=>x+k*(atr[i]||0))}}
  if(name==='DMI'){const plus=ema(b.map((_,i)=>i&&h[i]-h[i-1]>l[i-1]-l[i]&&h[i]>h[i-1]?h[i]-h[i-1]:0),n),minus=ema(b.map((_,i)=>i&&l[i-1]-l[i]>h[i]-h[i-1]&&l[i]<l[i-1]?l[i-1]-l[i]:0),n),pd=c.map((_,i)=>atr[i]?100*(plus[i]||0)/(atr[i]||1):0),md=c.map((_,i)=>atr[i]?100*(minus[i]||0)/(atr[i]||1):0);return {plus_di:pd,minus_di:md,adx:ema(pd.map((x,i)=>x+md[i]?100*Math.abs(x-md[i])/(x+md[i]):0),n)}}
  return {};
}
