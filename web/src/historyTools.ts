import type {Bar} from './indicators';
type Page={bars:Bar[];next_before:number;has_more:boolean};
export async function backfillHistory({before,target,fetchPage,onPage,stopped,maxPages=120}:{before:number;target?:number;fetchPage:(before:number)=>Promise<Page>;onPage:(page:Page)=>void;stopped:()=>boolean;maxPages?:number}){
 let cursor=before,hasMore=true,pages=0;
 while(pages<maxPages){
  const page=await fetchPage(cursor);
  if(stopped())return {before:cursor,hasMore,cancelled:true};
  const next=Number(page.next_before);
  hasMore=Boolean(page.has_more)&&Number.isFinite(next)&&next>0&&next<cursor;
  onPage(page);pages++;
  if(Number.isFinite(next)&&next>0&&next<cursor)cursor=next;
  if(!hasMore||target===undefined||cursor<=target)break;
 }
 return {before:cursor,hasMore,cancelled:false};
}
export function visibleExtremes(bars:Pick<Bar,'time'|'high'|'low'>[],from:number,to:number){
 let high=-Infinity,low=Infinity,count=0;
 for(const bar of bars)if(bar.time>=from&&bar.time<=to){high=Math.max(high,bar.high);low=Math.min(low,bar.low);count++}
 return count?{high,low,count}:null;
}
/** Only actual wick endpoints inside BOTH visible axes are candidates. */
export function visiblePriceVertices(bars:Pick<Bar,'time'|'high'|'low'>[],from:number,to:number,priceA:number,priceB:number){
 const lower=Math.min(priceA,priceB),upper=Math.max(priceA,priceB);
 let high:{time:number;price:number}|null=null,low:{time:number;price:number}|null=null;
 for(const bar of bars){
  if(bar.time<from||bar.time>to)continue;
  if(Number.isFinite(bar.high)&&bar.high>=lower&&bar.high<=upper&&(!high||bar.high>high.price))high={time:bar.time,price:bar.high};
  if(Number.isFinite(bar.low)&&bar.low>=lower&&bar.low<=upper&&(!low||bar.low<low.price))low={time:bar.time,price:bar.low};
 }
 return {high,low};
}
export function marketDateWindow(date:string,isUS:boolean){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date))return null;
 const utc=Date.parse(date+'T00:00:00Z');if(!Number.isFinite(utc))return null;
 const format=new Intl.DateTimeFormat('en-GB',{timeZone:isUS?'America/New_York':'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
 const midnight=(value:number)=>{let candidate=value;for(let i=0;i<4;i++){const parts=Object.fromEntries(format.formatToParts(candidate).map(p=>[p.type,p.value]));const rendered=Date.UTC(+parts.year,+parts.month-1,+parts.day,+parts.hour,+parts.minute,+parts.second);const delta=rendered-value;if(!delta)break;candidate-=delta}return candidate/1000};
 return {from:midnight(utc),to:midnight(utc+86400000)-1};
}
