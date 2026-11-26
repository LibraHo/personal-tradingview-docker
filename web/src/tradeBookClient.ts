import {reviewRequest, type ReviewMarket} from './reviewClient';
import type {PlanDetails} from './tradePlanAnalysis';

export type Side='BUY'|'SELL'|'SELL_SHORT'|'BUY_BACK';
export type PlanVersion={
 id:string; symbol:string; period:PlanPeriod; side:'BUY'|'SELL';
 trigger:string; size:string; stop:number|null; status:'draft'|'active'|'skipped'|'closed'; details?:PlanDetails|null;
 revision:number; updated_at:string;
};
export type Plan=PlanVersion & {created_at:string; history:PlanVersion[];fill_ids?:string[]};
export type Instrument={kind:'stock'|'option';code:string;symbol:string;expiry?:string;strike?:number;right?:'C'|'P'};
export type FillReview={execution:string;quality:string;note:string;group_ids:string[]};
export type Fill=Instrument & {
 id:string; at:string; side:Side; qty:number; price:number; account:string;
 source:string; broker_id?:string; broker_status?:string; review:FillReview|null;
 revision:number; plan_id?:string; plan_snapshot?:PlanVersion|null; candidate_ids:string[]; aliases?:string[];
};
export type Holding=Instrument & {qty:number;cost?:number|null;account:string;as_of:string;source:string};
export type Account={account:string;as_of:string;complete:boolean;source:string};
export type BookPage={plans:Plan[];fills:Fill[];positions:Holding[];accounts:Account[];next_offset:number|null};
export type RecordTarget={kind:'plan'|'fill';id:string;symbol?:string};
export type Backlink={kind:'day'|'week';day:string};
export type SyncStatus={state:'idle'|'queued'|'running'|'ready'|'error';last_success?:string|null;message?:string;accounts:{account:string;through?:string;as_of?:string}[];interval_seconds:number};

export const sideNames:Record<string,string>={BUY:'买入',SELL:'卖出',SELL_SHORT:'卖空',BUY_BACK:'买入平仓'};
export const periodNames={ '1m':'1 分钟','5m':'5 分钟','15m':'15 分钟','30m':'30 分钟','60m':'1 小时','120m':'2 小时','240m':'4 小时','1d':'日线','1w':'周线','1mo':'月线' };
export type PlanPeriod=keyof typeof periodNames;
export const statusNames={draft:'草稿',active:'进行中',skipped:'未交易',closed:'已结束'};
export const sourceNames:Record<string,string>={manual:'手动录入',opend:'OpenD',screenshot:'截图同步',agent:'Agent'};
export function ledgerSymbol(raw:string,market:ReviewMarket){
 let code=raw.trim().toUpperCase();
 if(market==='CN'){
  if(/^\d{6}$/.test(code)){
   const exchange=/^(?:[48]|92)/.test(code)?'BJ':/^[569]/.test(code)?'SH':'SZ';
   code=exchange+'.'+code;
  }
  if(!/^(SH|SZ|BJ)\.\d{6}$/.test(code))throw Error('请输入六位股票代码或带交易所的代码，例如 SH.510050。');
 }else{
  if(!code.startsWith('US.'))code='US.'+code;
  if(!/^US\.[A-Z][A-Z0-9.\-]{0,15}$/.test(code)||/\d{6}[CP]\d+$/.test(code))throw Error('请输入美股标的代码，例如 US.AAPL。');
 }
 return code;
}
export function unit(item:Instrument){return item.kind==='option'?'张':'股'}
export function description(item:Instrument){
 return item.kind==='option'?`${item.symbol} · ${item.expiry} · ${item.strike} ${item.right==='C'?'看涨':'看跌'}`:item.symbol;
}
export function requestId(){
 return Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
}
export function ledgerRequest<T>(market:ReviewMarket,path:string,method='GET',body?:unknown,signal?:AbortSignal){
 const delimiter=path.includes('?')?'&':'?';
 return reviewRequest<T>('ledger/'+path+delimiter+'market='+market,{method,body:body===undefined?undefined:JSON.stringify(body),signal,cache:'no-store'});
}
export function zone(market:ReviewMarket){return market==='US'?'America/New_York':'Asia/Shanghai'}
export function localStamp(market:ReviewMarket,date=new Date()){
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:zone(market),year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(date);
 const part=(type:string)=>parts.find(p=>p.type===type)?.value;
 return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}:${part('second')}`;
}
export function displayTime(market:ReviewMarket,at?:string|null){
 if(!at)return '—';
 const date=new Date(at);
 return Number.isFinite(date.valueOf())?localStamp(market,date).replace('T',' '):'—';
}
export function absoluteTime(market:ReviewMarket,wall:string){
 const normalized=wall.length===16?wall+':00':wall;
 const offsets=market==='CN'?['+08:00']:['-04:00','-05:00'];
 const matches=offsets.map(offset=>new Date(normalized+offset)).filter(date=>Number.isFinite(date.valueOf())&&localStamp(market,date)===normalized);
 if(matches.length!==1)throw Error('此市场时间无效或处于夏令时重复时段，请核对成交时间和时区。');
 return matches[0].toISOString();
}
