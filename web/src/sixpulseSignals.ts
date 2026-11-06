import {sixPulseRows} from './sixpulse';
export function signalSettings(input:Record<string,unknown>){
 const enabled=Object.hasOwn(input,'enabled')?input.enabled:[...sixPulseRows];
 if(!Array.isArray(enabled)||!enabled.length||enabled.some(x=>typeof x!=='string'||!(sixPulseRows as readonly string[]).includes(x))||new Set(enabled).size!==enabled.length)throw Error('请勾选至少一项不重复的六脉指标');
 const n=enabled.length,enter=Object.hasOwn(input,'enterReds')?input.enterReds:Math.min(5,n),leave=Object.hasOwn(input,'exitGreens')?input.exitGreens:Math.min(3,n);
 if([enter,leave].some(x=>typeof x!=='number'||!Number.isInteger(x)||x<1||x>n))throw Error(`提示门槛须为 1–${n} 的整数`);
 if((enter as number)+(leave as number)<=n)throw Error('上车红数 + 下车绿数须大于参与指标数，避免同根冲突');
 const confirm=Object.hasOwn(input,'confirm')?input.confirm:'next_bar';if(typeof confirm!=='string'||!['next_bar','live'].includes(confirm))throw Error('确认方式不正确');
 return {enabled:enabled as string[],enter:enter as number,leave:leave as number,confirm};
}
export function signalValues(values:Record<string,(number|null)[]>,input:Record<string,unknown>){
 const {enabled,enter,leave,confirm}=signalSettings(input),reds:(number|null)[]=[],greens:(number|null)[]=[],entry:(number|null)[]=[],exit:(number|null)[]=[],states:(number|null)[]=[];let holding=false;
 values.MACD.forEach((_,i)=>{const valid=enabled.every(name=>values[name][i]!==null),r=valid?enabled.reduce((s,name)=>s+values[name][i]!,0):null,g=r===null?null:enabled.length-r;reds.push(r);greens.push(g);
  if(r===null||g===null||(confirm==='next_bar'&&i===values.MACD.length-1)){entry.push(null);exit.push(null);states.push(null);return}
  let buy=0,sell=0;if(!holding&&r>=enter){holding=true;buy=1}else if(holding&&g>=leave){holding=false;sell=1}entry.push(buy);exit.push(sell);states.push(Number(holding));
 });return {...values,SCORE:reds,REDS:reds,GREENS:greens,ENTRY:entry,EXIT:exit,STATE:states};
}
