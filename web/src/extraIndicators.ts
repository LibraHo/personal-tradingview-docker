import type {Bar} from './indicators';
type Values=(number|null)[];
export const extraDefaults:Record<string,Record<string,number>>={WMA:{period:20},VWMA:{period:20},DC:{period:20},STOCH:{period:14,smoothK:3,smoothD:3},CCI:{period:20},WR:{period:14},ROC:{period:9},MOM:{period:10},OBV:{},CMF:{period:20}};
export function period(p:Record<string,unknown>,key:string,fallback:number){const n=Object.hasOwn(p,key)?p[key]:fallback;if(typeof n!=='number'||!Number.isInteger(n)||n<1||n>2000)throw Error(`${key} 须为 1–2000 的整数`);return n}
export function sum(v:Values,n:number):Values{let total=0,valid=0;return v.map((x,i)=>{if(x!==null){total+=x;valid++}if(i>=n&&v[i-n]!==null){total-=v[i-n]!;valid--}return i>=n-1&&valid===n?total:null})}
export function average(v:Values,n:number):Values{return sum(v,n).map(x=>x===null?null:x/n)}
export function extreme(v:number[],n:number,high:boolean):Values{const q:number[]=[];let head=0;return v.map((x,i)=>{while(q.length>head&&(high?v[q[q.length-1]]<=x:v[q[q.length-1]]>=x))q.pop();q.push(i);while(q[head]<=i-n)head++;return i>=n-1?v[q[head]]:null})}
/** Rolling windows use only the current/past bars. Null means insufficient or undefined data. */
export function computeExtra(b:Bar[],name:string,p:Record<string,unknown>):Record<string,Values>|null{
 if(!Object.hasOwn(extraDefaults,name))return null;
 const c=b.map(x=>x.close),v=b.map(x=>x.volume),n=period(p,'period',extraDefaults[name].period??14);
 if(name==='OBV'){let total=0;return {main:c.map((x,i)=>{if(i)total+=Math.sign(x-c[i-1])*v[i];return total})}}
 if(name==='WMA'){let total=0,weighted=0;return {main:c.map((x,i)=>{weighted+=(i<n?i+1:n)*x;if(i>=n)weighted-=total;total+=x-(i>=n?c[i-n]:0);return i>=n-1?weighted/(n*(n+1)/2):null})}}
 if(name==='VWMA'){const sv=sum(v,n),pv=sum(c.map((x,i)=>x*v[i]),n);return {main:pv.map((x,i)=>x===null||!sv[i]?null:x/sv[i]!)}}
 if(name==='ROC'||name==='MOM')return {main:c.map((x,i)=>i<n?null:name==='MOM'?x-c[i-n]:c[i-n]===0?null:100*(x-c[i-n])/c[i-n])};
 if(name==='CCI'){const tp=b.map(x=>(x.high+x.low+x.close)/3),ma=average(tp,n);return {main:tp.map((x,i)=>{if(ma[i]===null)return null;let deviation=0;for(let j=i-n+1;j<=i;j++)deviation+=Math.abs(tp[j]-ma[i]!);return deviation/n<=Number.EPSILON*Math.max(1,Math.abs(x),Math.abs(ma[i]!))*8?0:(x-ma[i]!)/(0.015*deviation/n)})}}
 if(name==='CMF'){const sv=sum(v,n),flow=sum(b.map(x=>x.high===x.low?0:(2*x.close-x.high-x.low)/(x.high-x.low)*x.volume),n);return {main:flow.map((x,i)=>x===null||!sv[i]?null:x/sv[i]!)}}
 const high=extreme(b.map(x=>x.high),n,true),low=extreme(b.map(x=>x.low),n,false);
 if(name==='DC')return {upper:high,mid:high.map((x,i)=>x===null?null:(x+low[i]!)/2),lower:low};
 if(name==='WR')return {main:c.map((x,i)=>high[i]===null||high[i]===low[i]?null:-100*(high[i]!-x)/(high[i]!-low[i]!))};
 const raw=c.map((x,i)=>high[i]===null||high[i]===low[i]?null:100*(x-low[i]!)/(high[i]!-low[i]!));
 const k=average(raw,period(p,'smoothK',3)),d=average(k,period(p,'smoothD',3));return {k,d};
}
