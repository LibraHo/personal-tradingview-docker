import type {Bar} from './indicators';
import {signalValues} from './sixpulseSignals';
import {computeSixPulse} from './sixpulse';
import {advancedParams} from './advancedCatalog';
import {average,sum,extreme} from './extraIndicators';
type V=(number|null)[];
function ema(v:V,n:number):V{let last:number|null=null;return v.map(x=>{if(x===null)return null;last=last===null?x:last+(x-last)*2/(n+1);return last})}
export function rma(v:V,n:number):V{let last:number|null=null,total=0,count=0;return v.map(x=>{if(x===null){last=null;total=0;count=0;return null}if(last===null){total+=x;count++;if(count<n)return null;last=total/n}else last+=(x-last)/n;return last})}
function wma(v:V,n:number):V{let total=0,weighted=0,valid=0;return v.map((x,i)=>{weighted+=(i<n?i+1:n)*(x??0);if(i>=n)weighted-=total;total+=(x??0)-(i>=n?(v[i-n]??0):0);valid+=Number(x!==null)-(i>=n?Number(v[i-n]!==null):0);return i>=n-1&&valid===n?weighted/(n*(n+1)/2):null})}
function rsi(c:number[],n:number):V{const g=rma(c.map((x,i)=>i?Math.max(0,x-c[i-1]):null),n),l=rma(c.map((x,i)=>i?Math.max(0,c[i-1]-x):null),n);return c.map((_,i)=>g[i]===null?null:!g[i]&&!l[i]?50:!l[i]?100:100-100/(1+g[i]!/l[i]!))}
function atr(b:Bar[],n:number){return rma(b.map((x,i)=>i?Math.max(x.high-x.low,Math.abs(x.high-b[i-1].close),Math.abs(x.low-b[i-1].close)):x.high-x.low),n)}
export function computeAdvanced(b:Bar[],name:string,input:Record<string,unknown>):Record<string,V>|null{
 const p=advancedParams(name,input);if(!p)return null;
 if(name==='SIXPULSE'||name==='SIXPULSE_SIGNAL'){const values=computeSixPulse(b,p);return name==='SIXPULSE_SIGNAL'?signalValues(values,input):values}
 const c=b.map(x=>x.close),h=b.map(x=>x.high),l=b.map(x=>x.low),n=p.period;
 if(name==='KDJ'){const hi=extreme(h,n,true),lo=extreme(l,n,false);let k=50,d=50;const ks:V=[],ds:V=[],js:V=[];c.forEach((x,i)=>{if(hi[i]===null){ks.push(null);ds.push(null);js.push(null);return}const raw=hi[i]===lo[i]?50:100*(x-lo[i]!)/(hi[i]!-lo[i]!);k+=(raw-k)/p.smoothK;d+=(k-d)/p.smoothD;ks.push(k);ds.push(d);js.push(3*k-2*d)});return {k:ks,d:ds,j:js}}
 if(name==='MFI'){const tp=b.map(x=>(x.high+x.low+x.close)/3),pos=sum(tp.map((x,i)=>i?(x>tp[i-1]?x*b[i].volume:0):null),n),neg=sum(tp.map((x,i)=>i?(x<tp[i-1]?x*b[i].volume:0):null),n);return {main:pos.map((x,i)=>x===null?null:!x&&!neg[i]?null:!neg[i]?100:100-100/(1+x/neg[i]!))}}
 if(name==='STOCHRSI'){const values=rsi(c,p.rsiPeriod),raw:V=values.map((x,i)=>{if(x===null||i<p.rsiPeriod+n-1)return null;const window=values.slice(i-n+1,i+1) as number[],hi=Math.max(...window),lo=Math.min(...window);return hi===lo?null:100*(x-lo)/(hi-lo)}),k=average(raw,p.smoothK);return {k,d:average(k,p.smoothD)}}
 if(name==='HMA'){const half=wma(c,Math.max(1,Math.floor(n/2))),full=wma(c,n);return {main:wma(full.map((x,i)=>x===null?null:2*half[i]!-x),Math.max(1,Math.round(Math.sqrt(n))))}}
 if(['DEMA','TEMA','TRIX'].includes(name)){const a=ema(c,n),bb=ema(a,n),cc=ema(bb,n);if(name==='DEMA')return {main:c.map((_,i)=>2*a[i]!-bb[i]!)};if(name==='TEMA')return {main:c.map((_,i)=>3*a[i]!-3*bb[i]!+cc[i]!)};const main=cc.map((x,i)=>!i||!cc[i-1]?null:100*(x!-cc[i-1]!)/cc[i-1]!);return {main,signal:ema(main,p.signal)}}
 if(name==='KC'){const mid=ema(c,n),a=atr(b,p.atrPeriod);return {mid,upper:mid.map((x,i)=>a[i]===null?null:x!+p.multiplier*a[i]!),lower:mid.map((x,i)=>a[i]===null?null:x!-p.multiplier*a[i]!)}}
 if(name==='SUPERTREND'){const a=atr(b,n),main:V=[],direction:V=[];let upper=0,lower=0,up=false,ready=false;for(let i=0;i<b.length;i++){if(a[i]===null){main.push(null);direction.push(null);continue}const bu=(h[i]+l[i])/2+p.multiplier*a[i]!,bl=(h[i]+l[i])/2-p.multiplier*a[i]!;if(!ready){upper=bu;lower=bl;ready=true}else{upper=bu<upper||c[i-1]>upper?bu:upper;lower=bl>lower||c[i-1]<lower?bl:lower;up=up?!(c[i]<lower):c[i]>upper}main.push(up?lower:upper);direction.push(up?1:-1)}return {main,direction}}
 if(name==='SAR'){const main:V=b.map(()=>null);if(b.length<2)return {main};let up=c[1]>c[0],value=up?l[0]:h[0],ep=up?h[1]:l[1],af=p.start;main[1]=value;for(let i=2;i<b.length;i++){value+=af*(ep-value);if(up?value>l[i]:value<h[i]){value=up?Math.max(ep,h[i]):Math.min(ep,l[i]);up=!up;ep=up?h[i]:l[i];af=p.start}else{value=up?Math.min(value,l[i-1],l[i-2]):Math.max(value,h[i-1],h[i-2]);if(up?h[i]>ep:l[i]<ep){ep=up?h[i]:l[i];af=Math.min(p.maximum,af+p.increment)}}main[i]=value}return {main}}
 if(name==='PPO'){const fast=ema(c,p.fast),slow=ema(c,p.slow),main=c.map((_,i)=>!slow[i]?null:100*(fast[i]!-slow[i]!)/slow[i]!),signal=ema(main,p.signal);return {main,signal,hist:main.map((x,i)=>x===null||signal[i]===null?null:x-signal[i]!)}}
 if(name==='AO'){const median=b.map(x=>(x.high+x.low)/2),fast=average(median,p.fast),slow=average(median,p.slow);return {hist:slow.map((x,i)=>x===null?null:fast[i]!-x)}}
 if(name==='BIAS'){const ma=average(c,n);return {main:c.map((x,i)=>!ma[i]?null:100*(x-ma[i]!)/ma[i]!)}}
 if(name==='PVT'){let total=0;return {main:c.map((x,i)=>{if(!i)return 0;if(!c[i-1])return null;total+=(x-c[i-1])/c[i-1]*b[i].volume;return total})}}
 if(name==='BOP')return {main:b.map(x=>x.high===x.low?0:(x.close-x.open)/(x.high-x.low))};
 if(name==='ADL'||name==='CHO'){let total=0;const ad=b.map(x=>{total+=x.high===x.low?0:(2*x.close-x.high-x.low)/(x.high-x.low)*x.volume;return total});if(name==='ADL')return {main:ad};const fast=ema(ad,p.fast),slow=ema(ad,p.slow);return {main:ad.map((_,i)=>fast[i]!-slow[i]!)}}
 if(name==='BBW'||name==='BBP'){const ma=average(c,n);return {main:c.map((x,i)=>{if(ma[i]===null)return null;const sd=Math.sqrt(c.slice(i-n+1,i+1).reduce((s,v)=>s+(v-ma[i]!)**2,0)/n),span=2*p.stddev*sd;if(name==='BBW')return ma[i]?span/ma[i]!*100:null;return sd<=Number.EPSILON*Math.max(1,Math.abs(x),Math.abs(ma[i]!))*8?null:(x-ma[i]!+span/2)/span})}}
 const up:V=[],down:V=[];for(let i=0;i<b.length;i++){if(i<n){up.push(null);down.push(null);continue}let hi=i,lo=i;for(let j=i-1;j>=i-n;j--){if(h[j]>h[hi])hi=j;if(l[j]<l[lo])lo=j}up.push(100*(n-i+hi)/n);down.push(100*(n-i+lo)/n)}return {up,down};
}
