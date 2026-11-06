import type {Bar} from './indicators';
import {average,extreme} from './extraIndicators';
type V=(number|null)[];
export const sixPulseRows=['MACD','KDJ','RSI','LWR','BBI','MTM'] as const;
function smooth(v:V,n:number,exponential=false):V{let last:number|null=null;const alpha=exponential?2/(n+1):1/n;return v.map(x=>{if(x===null)return null;last=last===null?x:last+(x-last)*alpha;return last})}
const ratio=(a:V,b:V):V=>a.map((x,i)=>x===null||b[i]===null||b[i]===0?null:100*x/b[i]!);
/** Mai SMA(X,N,1), first valid seed; undefined values are not down signals. */
export function computeSixPulse(b:Bar[],p:Record<string,number>):Record<string,V>{
 const c=b.map(x=>x.close),h=b.map(x=>x.high),l=b.map(x=>x.low);
 const fast=smooth(c,p.fast,true),slow=smooth(c,p.slow,true),diff=c.map((_,i)=>fast[i]!-slow[i]!),dea=smooth(diff,p.signal,true);
 const stochastic=(n:number,negative=false):V=>{const hi=extreme(h,n,true),lo=extreme(l,n,false);return ratio(c.map((x,i)=>hi[i]===null?null:negative?x-hi[i]!:x-lo[i]!),hi.map((x,i)=>x===null?null:x-lo[i]!))};
 const k=smooth(stochastic(p.kdjPeriod),p.smoothK),d=smooth(k,p.smoothD);
 const change=c.map((x,i)=>i?x-c[i-1]:null),up=change.map(x=>x===null?null:Math.max(x,0)),absolute=change.map(x=>x===null?null:Math.abs(x));
 const rsi=(n:number)=>ratio(smooth(up,n),smooth(absolute,n)),rsi1=rsi(p.rsiFast),rsi2=rsi(p.rsiSlow);
 const lwr1=smooth(stochastic(p.lwrPeriod,true),p.lwrSmooth1),lwr2=smooth(lwr1,p.lwrSmooth2);
 const means=[p.bbi1,p.bbi2,p.bbi3,p.bbi4].map(n=>average(c,n)),bbi=c.map((_,i)=>means.some(row=>row[i]===null)?null:means.reduce((s,row)=>s+row[i]!,0)/4);
 const momentum=(n:number,m:number)=>ratio(smooth(smooth(change,n,true),m,true),smooth(smooth(absolute,n,true),m,true));
 const mms=momentum(p.mtmFast,p.mtmFastSmooth),mmm=momentum(p.mtmSlow,p.mtmSlowSmooth);
 const pairs:[V,V][]=[[diff,dea],[k,d],[rsi1,rsi2],[lwr1,lwr2],[c,bbi],[mms,mmm]];
 const out:Record<string,V>=Object.fromEntries(sixPulseRows.map((name,j)=>[name,pairs[j][0].map((x,i)=>x===null||pairs[j][1][i]===null?null:Number(x>pairs[j][1][i]!))]));
 out.SCORE=c.map((_,i)=>sixPulseRows.some(name=>out[name][i]===null)?null:sixPulseRows.reduce((s,name)=>s+out[name][i]!,0));
 return {...out,DIFF:diff,DEA:dea,K:k,D:d,RSI1:rsi1,RSI2:rsi2,LWR1:lwr1,LWR2:lwr2,BBI_VALUE:bbi,MMS:mms,MMM:mmm};
}
