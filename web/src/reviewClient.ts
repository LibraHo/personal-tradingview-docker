export type ReviewMarket='CN'|'US';
export type Discipline={id:string;market:ReviewMarket;title:string;active:boolean;revision:number};
export type ReviewSymbol={symbol:string;name:string;note:string};
export type MentionedSymbol=Pick<ReviewSymbol,'symbol'|'name'>;
export type DailyDraft={revision:number;traded:boolean;violations:string[];symbols:ReviewSymbol[];context:string;reason:string;lesson:string;plan:string};
export type DailyEntry=Omit<DailyDraft,'violations'>&{day:string;updated:number;violations:{id:string;title:string}[];mentioned_symbols?:MentionedSymbol[]};
export type WeeklyDraft={revision:number;focus_rule_id:string;action:string;summary:string};
export type WeeklyEntry=WeeklyDraft&{week:string;focus_title:string};
export type ReviewDashboard={market:ReviewMarket;day:string;rules:Discipline[];entry:DailyEntry|null;week_start:string;week_end:string;weekly:WeeklyEntry;previous_weekly:WeeklyEntry|null;
 stats:{reviewed_days:number;trading_days:number;clean_days:number;violation_days:number;previous_reviewed_days:number;ranking:{id:string;title:string;count:number;previous_count:number}[]};
 history:{day:string;traded:boolean;violation_count:number;symbol_count:number;lesson:string}[]};

export function marketToday(market:ReviewMarket,now=new Date()){
 const parts=new Intl.DateTimeFormat('en-US',{timeZone:market==='CN'?'Asia/Shanghai':'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
 const get=(type:string)=>parts.find(p=>p.type===type)!.value;
 return `${get('year')}-${get('month')}-${get('day')}`;
}
export function shiftDay(day:string,offset:number){const date=new Date(day+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+offset);return date.toISOString().slice(0,10)}
export function normalizeReviewSymbol(raw:string,market:ReviewMarket){
 let code=raw.trim().toUpperCase();
 if(market==='US'&&/^(SH|SZ)\./.test(code))throw Error('此处只能关联美股标的');
 if(market==='CN'&&/^\d{6}$/.test(code))code=(code.startsWith('6')?'SH.':'SZ.')+code;
 if(market==='US'&&!code.startsWith('US.'))code='US.'+code;
 if(!(market==='US'?/^US\.[A-Z0-9.]{1,12}$/:/^(SH|SZ)\.\d{6}$/).test(code))throw Error(market==='CN'?'请输入 A 股代码，如 SH.600519 或 SZ.000001':'请输入美股代码，如 AAPL；类别股请使用点号，如 BRK.B');
 return code;
}

export function reviewMentions(text:string, market:ReviewMarket){
 const code=market==='CN'?'(?:SH|SZ)\\.[0-9]{6}':'US\\.[A-Z0-9.]{1,12}';
 const pattern=new RegExp('\\[\\[('+code+')(?:\\|([^\\[\\]|\\r\\n]{1,80}))?\\]\\]','gi');
 return Array.from(text.matchAll(pattern),match=>({
  symbol:match[1].toUpperCase(),name:match[2]?.trim()||'',index:match.index,length:match[0].length,
 }));
}

export function collectReviewMentions(fields:DailyDraft,market:ReviewMarket){
 const items=new Map<string,MentionedSymbol>();
 for(const value of [fields.context,fields.reason,fields.lesson,fields.plan]){
  for(const {symbol,name} of reviewMentions(value,market)){
   if(!items.get(symbol)?.name)items.set(symbol,{symbol,name});
  }
 }
 return [...items.values()];
}
export type StoredReviewDraft<T>={version:1;value:T;saved?:boolean;owner?:string;lineage?:string};
export function readReviewDraft<T extends {revision:number}>(raw:string|null):StoredReviewDraft<T>|null{
 try{const parsed=JSON.parse(raw||'null');return parsed?.version===1&&parsed.value&&typeof parsed.value.revision==='number'?parsed:null}catch{return null}
}
export function acknowledgeReviewDraft<T extends {revision:number}>(raw:string|null,snapshot:T,revision:number,owner:string,lineage:string):StoredReviewDraft<T>{
 const latest=readReviewDraft<T>(raw);
 if(latest&&(latest.owner!==owner||latest.lineage!==lineage))return latest;
 // A save finishing in an unmounted editor must preserve edits made in its replacement.
 if(latest&&JSON.stringify(latest.value)!==JSON.stringify(snapshot)){
  if(latest.value.revision===snapshot.revision)return {version:1,value:{...latest.value,revision},saved:false,owner,lineage};
  return latest;
 }
 // Keep a saved receipt until fresh server data arrives, including during navigation.
 return {version:1,value:{...snapshot,revision},saved:true,owner,lineage};
}
export async function reviewRequest<T>(path:string,init?:RequestInit):Promise<T>{
 const response=await fetch('/api/review/'+path,{...init,headers:{'Content-Type':'application/json',...init?.headers}});
 const data=await response.json().catch(()=>null);
 if(!response.ok)throw Error(typeof data?.detail==='string'?data.detail:response.status===422?'请检查填写内容和长度':`读取或保存失败（${response.status}），请重试`);
 return data;
}
