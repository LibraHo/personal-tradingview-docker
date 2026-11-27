import {inputIssue} from './indicatorInputs';
import spec from '../../app/tdx_formulas.json';
import type {Bar} from './indicators';
type V=(number|null)[];
type Node=[string,string,(string|number|null)[]];
export type TdxEntry={label:string;pane:'main'|'separate';description:string;source?:string;symbolPattern?:string;market?:'CN'|'US';period?:string;outputs:Record<string,string|null>;plots:Record<string,{kind:string;color:string;label?:string}>;signals:Record<string,{text:string;color:string;down?:boolean;shape?:'circle'}>};
export const tdxCatalog=spec.indicators as unknown as Record<string,TdxEntry>;
export const fixedPeriodLabel=(period:string)=>({'60m':'1小时','120m':'2小时','1d':'日线'} as Record<string,string>)[period]||period;
export function tdxAvailable(name:string,marketOrSymbol:string){
 if(name==='FULAI')return marketOrSymbol==='CN'||/^(SH|SZ)\.[036]\d{5}$/.test(marketOrSymbol);
 const item=tdxCatalog[name];
 if(marketOrSymbol==='CN'||marketOrSymbol==='US')return !item?.market||item.market===marketOrSymbol;
 return !item?.symbolPattern||new RegExp(item.symbolPattern).test(marketOrSymbol);
}
export const isChiefResonance=(name:string)=>name==='CHIEF_RESONANCE'||name==='CHIEF_RESONANCE_PANE';
export function computeTdx(b:Bar[],name:string):Record<string,V>|null{
 if(name==='INSTITUTION_TREND'){
  const issue=inputIssue(b,name,'{}');
  if(issue)throw Error(issue);
 }
 if(name==='FULAI'&&b.some(x=>!tdxAvailable(name,(x as Bar&{symbol?:string}).symbol||'')))throw Error('福来仅支持沪深A股');
 const item=tdxCatalog[name];if(!item)return null;
 if(b.some((bar:Bar&{symbol?:string;period?:string})=>
  (bar.symbol&&!tdxAvailable(name,bar.symbol))||(item.period&&bar.period&&bar.period!==item.period)
 ))return Object.fromEntries(Object.keys(item.outputs).map(key=>[key,b.map(()=>null)]));
 const nodes=spec.nodes as Node[],needed=new Set(Object.values(item.outputs));
 const selected:Node[]=[];for(let i=nodes.length-1;i>=0;i--){const node=nodes[i];if(needed.has(node[0])){selected.push(node);for(const x of node[2])if(typeof x==='string')needed.add(x)}}
 const values:Record<string,V>=Object.fromEntries(['open','high','low','close','volume'].map(k=>[k,b.map(x=>x[k as keyof Bar] as number)]));
 values.turnover=b.map(({turnover})=>typeof turnover==='number'&&Number.isFinite(turnover)&&turnover>0?turnover:null);
 if(name==='INSTITUTION_TREND'){
  for(const field of ['chip_winner_95','chip_cost_85'])values[field]=b.map(bar=>bar.fields?.[field]??null);
 }
 const arg=(x:string|number|null):V=>typeof x==='string'?values[x]:b.map(()=>x);
 for(const [key,op,args] of selected.reverse()){
  const a=args.map(arg);let out:V=[];
  if(op==='session_volume_ratio'){
   const history:V[]=[];
   const window=Number(args[1]);
   const clocks=args.slice(2).map(Number);
   const slots=clocks.length||1;
   let dayId:number|undefined, current:V=Array(slots).fill(null);
   out=b.map((bar,i)=>{
    const local=bar.time+8*3600, day=Math.floor(local/86400), clock=local%86400;
    if(day!==dayId){
     if(dayId!==undefined){history.push(current);if(history.length>window)history.shift()}
     dayId=day;current=Array(slots).fill(null);
    }
    const volume=a[0][i];
    const slot=clocks.length?clocks.indexOf(clock):0;
    if(slot<0||volume===null||!Number.isFinite(volume)||volume<0)return null;
    current[slot]=volume;
    if(history.length<window||history.some(row=>row[slot]===null))return null;
    const baseline=history.reduce((sum,row)=>sum+row[slot]!,0)/window;
    return baseline>0?volume/baseline:null;
   });
  }
  else if(['ma','sum','hhv','llv'].includes(op)){
   const n=Number(args[1]);
   out=b.map((_,i)=>{
    const window=a[0].slice(Math.max(0,i-n+1),i+1);
    if(window.length!==n||window.some(x=>x===null))return null;
    const valid=window as number[];
    if(op==='hhv')return Math.max(...valid);
    if(op==='llv')return Math.min(...valid);
    const sum=valid.reduce((total,x)=>total+x,0);
    return op==='ma'?sum/n:sum;
   });
  }
  else if(op==='smooth'){let last:number|null=null;out=a[0].map(x=>{if(x===null)return null;last=last===null?x:last+(x-last)*Number(args[1]);return last})}
  else if(op==='dma'){
   let last:number|null=null;
   out=a[0].map((x,i)=>{
    const weight=a[1][i];
    if(x===null||weight===null||weight<0||weight>1)return null;
    last=last===null?x:last+(x-last)*weight;
    return last;
   });
  }
  else if(op==='ref'){const n=Number(args[1]);out=b.map((_,i)=>i>=n?a[0][i-n]:null)}
  else if(op==='filter'){let until=-1;out=a[0].map((x,i)=>{const hit=x!==null&&!!x&&i>until;if(hit)until=i+Number(args[1]);return x===null?null:Number(hit)})}
  else if(op==='latch'){
   let active=false;
   out=a[0].map((start,i)=>{
    if(a[1][i])active=false;
    else if(start)active=true;
    return Number(active);
   });
  }
  else if(op==='barscount')out=b.map((_,i)=>i+1);
  else if(op==='cn_volume')out=b.map(x=>/^(SH|SZ)\.[036]\d{5}$/.test((x as Bar&{symbol?:string}).symbol||'')&& x.volume !== null?x.volume/100:null);
  else if(op==='date_gate')out=b.map(x=>{const d=new Date(((x.time||0)+28800)*1000);return Number(!(d.getUTCFullYear()>=2099&&d.getUTCMonth()>=2))});
  else if(op==='available')out=a[0].map(x=>Number(x!==null));
  else out=b.map((_,i)=>{const xs=a.map(v=>v[i]);if(op==='if')return xs[0]===null?null:xs[0]?xs[1]:xs[2];if(xs.some(x=>x===null))return null;const x=xs[0]!,y=xs[1]??0;let z:number|null;
   switch(op){case'cross':return !i||a[0][i-1]===null||a[1][i-1]===null?null:Number(a[0][i-1]!<=a[1][i-1]!&&x>y);
    case'div':z=y?x/y:null;break;case'add':z=x+y;break;case'sub':z=x-y;break;case'mul':z=x*y;break;
    case'max':z=Math.max(...xs as number[]);break;case'min':z=Math.min(...xs as number[]);break;case'abs':z=Math.abs(x);break;case'ceil':z=Math.ceil(x);break;case'mod':z=y?x%y:null;break;
    case'gt':z=Number(x>y);break;case'ge':z=Number(x>=y);break;case'lt':z=Number(x<y);break;case'le':z=Number(x<=y);break;case'eq':z=Number(x===y);break;
    case'and':z=Number(xs.every(Boolean));break;case'or':z=Number(xs.some(Boolean));break;case'not':z=Number(!x);break;default:throw Error('未知公式运算 '+op)}return z!==null&&!Number.isFinite(z)?null:z;
  });values[key]=out;
 }
 return Object.fromEntries(Object.entries(item.outputs).map(([k,v])=>[k,v===null?b.map(()=>null):values[v]]));
}
