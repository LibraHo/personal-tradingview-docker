import type {Bar} from './indicators';
type Values=Record<string,(number|null)[]>;

/** Causal trigger/signal calculation; only the rendered line starts one bar back. */
export function msigm8Signals(bars:Bar[],histogram:number[],validBars:number,bufferRate:number):Values{
 const names=['SELL_TURN','BUY_TURN','SELL_LEVEL','BUY_LEVEL','SELL_AGE','BUY_AGE','SELL_SIGNAL','BUY_SIGNAL','SELL_START','BUY_START','SELL_MARKER','BUY_MARKER','BUY','SELL'];
 const out:Values=Object.fromEntries(names.map(name=>[name,[]]));
 const state=Object.fromEntries(['SELL','BUY'].map(side=>[side,{turn:-1,level:null as number|null,peak:null as number|null,expanded:-1,triggered:-1}]));
 bars.forEach((bar,i)=>{for(const side of ['SELL','BUY']){
  const sell=side==='SELL',s=state[side];
  const turn=i>=2&&(sell?histogram[i-2]<histogram[i-1]&&histogram[i-1]>histogram[i]:histogram[i-2]>histogram[i-1]&&histogram[i-1]<histogram[i]);
  if(turn){s.turn=i;s.level=bars[i-1][sell?'low':'high'];s.peak=histogram[i-1]}
  const age=s.turn>=0?i-s.turn:null;
  if(s.peak!==null&&(sell?histogram[i]>s.peak:histogram[i]<s.peak))s.expanded=i;
  const buffer=bar.close*bufferRate;
  const trigger=s.level!==null&&((sell?bar.close<s.level-buffer:bar.close>s.level+buffer)||(turn&&(sell?bar.close<s.level:bar.close>s.level)));
  const signal=trigger&&age!==null&&age+1<=validBars&&s.turn>s.expanded&&s.triggered<s.turn;
  out[side+'_TURN'].push(Number(turn));out[side+'_LEVEL'].push(s.level);out[side+'_AGE'].push(age);
  out[side+'_SIGNAL'].push(Number(signal));out[side+'_START'].push(signal?s.turn-1:null);
  const pad=(bar.high-bar.low)*.25;out[side+'_MARKER'].push(signal?(sell?bar.high+pad:bar.low-pad):null);
  out[side].push(Number(trigger));if(trigger)s.triggered=i;
 }});return out;
}

export function computeMSIGM8(bars:Bar[],p:Record<string,number>):Values{
 const ema=(v:number[],n:number)=>{let last:number|undefined;return v.map(x=>{last=last===undefined?x:last+(x-last)*2/(n+1);return last})};
 const c=bars.map(b=>b.close),fast=ema(c,p.fast),slow=ema(c,p.slow),dif=c.map((_,i)=>fast[i]-slow[i]),dea=ema(dif,p.signal),hist=dif.map((x,i)=>(x-dea[i])*2);
 return {DIF:dif,DEA:dea,MACDH:hist,...msigm8Signals(bars,hist,p.validBars,p.bufferRate)};
}
