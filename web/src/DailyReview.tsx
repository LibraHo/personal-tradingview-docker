import {useEffect,useRef,useState,type ReactNode} from 'react';
import {BookOpen,Check,ChevronLeft,ChevronRight,Download,Plus,Save,Target} from 'lucide-react';
import {acknowledgeReviewDraft,collectReviewMentions,readReviewDraft,marketToday,normalizeReviewSymbol,reviewMentions,reviewRequest,shiftDay,type DailyDraft,type DailyEntry,type Discipline,type ReviewDashboard,type ReviewMarket,type WeeklyDraft,type WeeklyEntry} from './reviewClient';
import './daily-review.css';
import TradeBook from './TradeBook';
import type {RecordTarget} from './tradeBookClient';
import {CitationPicker,CitationLinks,citations,openCitation} from './LedgerReferences';

type Props={market:ReviewMarket;currentSymbol:string;names:Record<string,string>;onMarketChange:(market:ReviewMarket)=>void;onOpen:(symbol:string,name:string)=>void};
const blankDaily:DailyDraft={revision:0,traded:true,violations:[],symbols:[],context:'',reason:'',lesson:'',plan:''};
const newDraftId=()=>Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
const draftOwner=newDraftId();

function useDraft<T extends {revision:number}>(storageKey:string,initial:T){
 const [loaded]=useState(()=>{try{return readReviewDraft<T>(localStorage.getItem(storageKey))}catch{return null}});
 const [lineage]=useState(()=>loaded?.owner===draftOwner&&loaded.lineage?loaded.lineage:newDraftId());
 const [value,setValue]=useState<T>(loaded&&(!loaded.saved||loaded.value.revision>initial.revision)?loaded.value:initial),[dirty,setDirty]=useState(!!loaded&&!loaded.saved),[storageIssue,setStorageIssue]=useState('');
 const change=(next:T)=>{let updated=next;try{const stored=readReviewDraft<T>(localStorage.getItem(storageKey));if(stored?.owner===draftOwner&&stored.lineage===lineage&&stored.value.revision>next.revision)updated={...next,revision:stored.value.revision};localStorage.setItem(storageKey,JSON.stringify({version:1,value:updated,saved:false,owner:draftOwner,lineage}));setStorageIssue('')}catch{setStorageIssue('此浏览器无法保留草稿，请在离开前保存。')}setValue(updated);setDirty(true)};
 const saved=(snapshot:T,revision:number)=>{try{const result=acknowledgeReviewDraft(localStorage.getItem(storageKey),snapshot,revision,draftOwner,lineage);localStorage.setItem(storageKey,JSON.stringify(result))}catch{}setValue({...snapshot,revision});setDirty(false)};
 useEffect(()=>{try{const stored=readReviewDraft<T>(localStorage.getItem(storageKey));if(stored?.saved&&stored.value.revision<=initial.revision)localStorage.removeItem(storageKey)}catch{}},[storageKey,initial.revision]);
 const clear=()=>{try{localStorage.removeItem(storageKey)}catch{}setDirty(false)};
 const reset=()=>{if(dirty&&!window.confirm('放弃当前未保存的草稿，载入已保存的内容？'))return false;clear();setValue(initial);return true};
 return {value,change,dirty,saved,reset,restored:!!loaded&&!loaded.saved,storageIssue,stale:value.revision!==initial.revision};
}

function ReviewTextPreview({text,market,names,onOpen}:{text:string;market:ReviewMarket;names:Record<string,string>;onOpen:Props['onOpen']}){
 const parts:ReactNode[]=[];
 let offset=0;
 const mentions=[
  ...reviewMentions(text,market).map(m=>({...m,button:<button key={m.index} type="button" className="review-inline-symbol" title={m.symbol} onClick={()=>onOpen(m.symbol,m.name||names[m.symbol]||m.symbol)}>{m.name||names[m.symbol]||m.symbol}</button>})),
  ...citations(text).map(m=>({...m,button:<button key={m.index} type="button" className="review-inline-symbol" onClick={()=>openCitation(market,m.kind,m.id)}>{m.label}</button>})),
 ].sort((a,b)=>a.index-b.index);
 for(const mention of mentions){
  parts.push(text.slice(offset,mention.index));
  parts.push(mention.button);
  offset=mention.index+mention.length;
 }
 parts.push(text.slice(offset));
 return <div className="review-text-preview">{text?parts:'还没有填写内容。'}</div>;
}

function DailyEditor({data,market,currentSymbol,names,onOpen,onSaved,onReload}:{data:ReviewDashboard;market:ReviewMarket;currentSymbol:string;names:Record<string,string>;onOpen:Props['onOpen'];onSaved:()=>void;onReload:()=>void}){
 const initial:DailyDraft=data.entry?{revision:data.entry.revision,traded:data.entry.traded,violations:data.entry.violations.map(v=>v.id),symbols:data.entry.symbols,context:data.entry.context,reason:data.entry.reason,lesson:data.entry.lesson,plan:data.entry.plan}:blankDaily;
 const draft=useDraft(`nas-review:daily:${market}:${data.day}`,initial),value=draft.value;
 const [saving,setSaving]=useState(false),[error,setError]=useState(''),[symbol,setSymbol]=useState(''),[name,setName]=useState('');
 const [preview,setPreview]=useState(false);
 const bodyInput=useRef<HTMLTextAreaElement>(null);
 const patch=(next:Partial<DailyDraft>)=>draft.change({...value,...next});
 const mentioned=collectReviewMentions(value,market);
 const symbolCount=new Set([...mentioned,...value.symbols].map(item=>item.symbol)).size;
 const existingTitles=new Map(data.entry?.violations.map(v=>[v.id,v.title])||[]);
 const displayed=data.rules.filter(r=>r.active||value.violations.includes(r.id));
 async function save(){setSaving(true);setError('');try{const result=await reviewRequest<DailyEntry>(`days/${data.day}?market=${market}`,{method:'PUT',body:JSON.stringify(value)});draft.saved(value,result.revision);onSaved()}catch(e){setError(String(e instanceof Error?e.message:e))}finally{setSaving(false)}}
 function addSymbol(raw:string,suggestedName=''){
  try{const code=normalizeReviewSymbol(raw,market);if(value.symbols.some(s=>s.symbol===code))throw Error('这个标的已经添加');if(value.symbols.length>=50)throw Error('每天最多关联 50 个标的');patch({symbols:[...value.symbols,{symbol:code,name:suggestedName||names[code]||'',note:''}]});setSymbol('');setName('');setError('')}catch(e){setError((e as Error).message)}
 }
 function insertMention(raw:string,suggestedName=''){
  try{
   const code=normalizeReviewSymbol(raw,market);
   const label=(suggestedName||names[code]||'').replace(/[\[\]|\r\n]/g,'').trim().slice(0,80);
   const input=bodyInput.current;
   const start=input?.selectionStart??value.context.length;
   const end=input?.selectionEnd??start;
   const before=value.context.slice(0,start),after=value.context.slice(end);
   const prefix=before&&!/\s$/.test(before)?' ':'';
   const reference=`${prefix}[[${code}${label?'|'+label:''}]] `;
   const context=before+reference+after;
   if(context.length>5000)throw Error('复盘正文已接近 5000 字，请缩短正文后再插入');
   patch({context});setPreview(false);setSymbol('');setName('');setError('');
   requestAnimationFrame(()=>{bodyInput.current?.focus();bodyInput.current?.setSelectionRange(start+reference.length,start+reference.length)});
  }catch(e){setError((e as Error).message)}
 }
 return <div className="review-daily-layout" data-review-editing={saving||draft.dirty||!!symbol||!!name}><div className="review-editor">
  <div className="review-card-heading"><div><span className="review-eyebrow">DAILY JOURNAL</span><h2>把交易过程记下来</h2></div><span className={`review-badge ${draft.dirty?'pending':''}`}>{draft.dirty?'有未保存的草稿':data.entry?'已保存':'尚未复盘'}</span></div>
  {(draft.restored&&draft.dirty||draft.storageIssue)&&<p className="review-note" role="status">{draft.storageIssue||'已恢复此日期的未保存草稿。'}</p>}
  {draft.stale&&<p className="review-error" role="alert">草稿基于旧版本，请先复制需要保留的内容，再载入已保存版本核对。</p>}
  <fieldset disabled={saving} className="review-fields">
   <div className="review-traded" role="group" aria-label="当日交易状态"><button type="button" aria-pressed={value.traded} onClick={()=>patch({traded:true})}>有交易</button><button type="button" aria-pressed={!value.traded} onClick={()=>patch({traded:false})}>无交易 / 观察日</button><span>空仓等待也值得记录</span></div>
   <div className="review-body-field">
    <div className="review-section-heading"><h3>复盘正文</h3><button type="button" aria-pressed={preview} onClick={()=>setPreview(!preview)}>{preview?'继续编辑':'预览正文'}</button></div>
    {preview?<ReviewTextPreview text={value.context} market={market} names={names} onOpen={onOpen}/>:<textarea ref={bodyInput} aria-label="复盘正文" maxLength={5000} rows={6} placeholder={market==='CN'?'[[SH.600519|贵州茅台]] 今天等到了回踩。':'[[US.AAPL|苹果]] 今天等到了回踩。'} value={value.context} onChange={e=>patch({context:e.target.value})}/>}
    <p className="review-muted">在正文中用 <code>[[代码|名称]]</code> 引用标的，名称可省略。同一篇可以引用多只股票。</p>
    <CitationPicker market={market} onInsert={ref=>{
      const start=bodyInput.current?.selectionStart??value.context.length,end=bodyInput.current?.selectionEnd??start;
      const text=value.context.slice(0,start)+ref+' '+value.context.slice(end);
      if(text.length>5000){setError('正文已达字数上限，请缩短后再引用');return}
      patch({context:text});setPreview(false);setError('');
      requestAnimationFrame(()=>{bodyInput.current?.focus();bodyInput.current?.setSelectionRange(start+ref.length+1,start+ref.length+1)});
    }}/>
    <CitationLinks market={market} text={[value.context,value.reason,value.lesson,value.plan].join('\n')}/>
   </div>
   <section className="review-discipline-check"><div className="review-section-heading"><h3>今天违反了哪些纪律？</h3><span>{value.violations.length} 项</span></div><p className="review-muted">仅勾选违反的项目。没有勾选，表示本次复盘未记录违规。</p>
    <div className="review-checklist">{displayed.map(rule=><label key={rule.id} className={value.violations.includes(rule.id)?'violated':''}><input type="checkbox" checked={value.violations.includes(rule.id)} onChange={e=>patch({violations:e.target.checked?[...value.violations,rule.id]:value.violations.filter(id=>id!==rule.id)})}/><span>{existingTitles.get(rule.id)||rule.title}{!rule.active&&<small>已停用 · 历史记录</small>}</span></label>)}</div>
    {!displayed.length&&<p className="review-empty">还没有启用的纪律，可以在“纪律管理”中添加。</p>}
   </section>
   <label className="review-label">违规原因 / 触发场景<textarea rows={3} maxLength={5000} placeholder="当时为什么偏离计划？什么信号可以提前提醒自己？" value={value.reason} onChange={e=>patch({reason:e.target.value})}/></label>
   <div className="review-two-fields"><label className="review-label">做得好的事与复盘心得<textarea maxLength={5000} rows={4} placeholder="哪些决定值得重复？今天学到了什么？" value={value.lesson} onChange={e=>patch({lesson:e.target.value})}/></label><label className="review-label">下次的具体改进<textarea maxLength={5000} rows={4} placeholder="写一个可执行动作，例如：下单前检查止损和仓位。" value={value.plan} onChange={e=>patch({plan:e.target.value})}/></label></div>
  </fieldset>
  {error&&<p className="review-error" role="alert">{error}</p>}
  <div className="review-save-row"><span>{data.entry?`上次保存 ${new Date(data.entry.updated*1000).toLocaleString('zh-CN')}`:'记录会保存到 NAS，可随时回来修改。'}</span><button disabled={saving} onClick={()=>{if(draft.reset())onReload()}}>载入已保存版本</button><button className="review-primary" disabled={saving||draft.stale} onClick={save}><Save size={15}/>{saving?'保存中…':'保存当日复盘'}</button></div>
 </div><div className="review-related">
  {data.weekly.focus_rule_id&&<div className="review-focus-card"><Target size={19}/><span>本周重点纪律</span><strong>{data.weekly.focus_title}</strong><p>{data.weekly.action||'去每周总结写下具体行动。'}</p></div>}
  <div className="review-card-heading"><h2>复盘涉及的标的</h2><span className="review-muted">{symbolCount} 只</span></div>
  <fieldset disabled={saving} className="review-fields">
   <div className="review-add-symbol"><input aria-label="复盘标的代码" value={symbol} maxLength={24} placeholder={market==='CN'?'600519 / SH.600519':'AAPL / US.AAPL'} onChange={e=>setSymbol(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();insertMention(symbol,name)}}}/><input aria-label="复盘标的名称" value={name} maxLength={80} placeholder="名称（可选）" onChange={e=>setName(e.target.value)}/><button disabled={!symbol.trim()} onClick={()=>insertMention(symbol,name)}><Plus size={14}/>插入正文</button></div>
   <button className="review-current-symbol" disabled={!currentSymbol} onClick={()=>insertMention(currentSymbol)}>＋ 引用当前图表 {currentSymbol}</button>
   {mentioned.length>0&&<div className="review-mention-index" aria-label="正文引用的标的">{mentioned.map(item=>{const label=item.name||names[item.symbol]||item.symbol;return <button key={item.symbol} type="button" title={item.symbol} onClick={()=>onOpen(item.symbol,label)}>{label}</button>})}</div>}
   <details className="review-symbol-notes" open={value.symbols.length>0||undefined}>
    <summary>独立标的备注</summary>
    <button disabled={!symbol.trim()} onClick={()=>addSymbol(symbol,name)}>给输入的标的添加独立备注</button>
    <div className="review-symbol-list">{value.symbols.map((item,index)=><article key={item.symbol}><div><button className="review-symbol-link" onClick={()=>onOpen(item.symbol,item.name||item.symbol)} title="打开该标的图表"><strong>{item.name||item.symbol}</strong><code>{item.symbol}</code></button><button aria-label={`移除 ${item.symbol}`} onClick={()=>patch({symbols:value.symbols.filter(s=>s.symbol!==item.symbol)})}>×</button></div><textarea aria-label={`${item.symbol} 复盘备注`} maxLength={2000} rows={3} placeholder="买入/卖出理由、执行问题、后续观察……" value={item.note} onChange={e=>patch({symbols:value.symbols.map((s,i)=>i===index?{...s,note:e.target.value}:s)})}/></article>)}</div>
   </details>
  </fieldset>
 </div></div>;
}

function WeeklyReview({data,market,onDate,onSaved,onReload}:{data:ReviewDashboard;market:ReviewMarket;onDate:(day:string)=>void;onSaved:()=>void;onReload:()=>void}){
 const initial:WeeklyDraft={revision:data.weekly.revision,focus_rule_id:data.weekly.focus_rule_id,action:data.weekly.action,summary:data.weekly.summary};
 const draft=useDraft(`nas-review:weekly:${market}:${data.week_start}`,initial),value=draft.value;
 const [saving,setSaving]=useState(false),[error,setError]=useState('');
 const patch=(next:Partial<WeeklyDraft>)=>draft.change({...value,...next});
 async function save(){setSaving(true);setError('');try{const result=await reviewRequest<WeeklyEntry>(`weeks/${data.week_start}?market=${market}`,{method:'PUT',body:JSON.stringify(value)});draft.saved(value,result.revision);onSaved()}catch(e){setError((e as Error).message)}finally{setSaving(false)}}
 const stats=data.stats,maxCount=Math.max(1,...stats.ranking.map(r=>r.count));
 return <div className="review-weekly" data-review-editing={saving||draft.dirty}><div className="review-week-range"><div><span className="review-eyebrow">WEEKLY REFLECTION</span><h2>{data.week_start} — {data.week_end}</h2></div><div><button aria-label="上一周" onClick={()=>onDate(shiftDay(data.week_start,-7))}><ChevronLeft size={16}/>上一周</button><button aria-label="下一周" onClick={()=>onDate(shiftDay(data.week_start,7))}>下一周<ChevronRight size={16}/></button></div></div>
  <div className="review-stat-grid">{[[stats.reviewed_days,'已复盘天数'],[stats.trading_days,'有交易天数'],[stats.clean_days,'未记录违规天数'],[stats.violation_days,'出现违规天数']].map(([count,label])=><div key={label}><strong>{count}</strong><span>{label}</span></div>)}</div>
  <p className="review-muted">按周一至周日统计，仅包含已保存的复盘；同一纪律每天最多计 1 次。上周已复盘 {stats.previous_reviewed_days} 天，比较时请同时考虑样本天数。</p>
  <div className="review-week-columns"><section className="review-ranking"><div className="review-section-heading"><h3>反复出现的问题</h3><span>本周 / 上周</span></div>{stats.ranking.length?stats.ranking.map((rule,index)=><div className="review-ranking-row" key={rule.id}><span>{String(index+1).padStart(2,'0')}</span><div><strong>{rule.title}</strong><div className="review-bar-track"><i style={{width:`${rule.count/maxCount*100}%`}}/></div></div><b>{rule.count}<small> / {rule.previous_count}</small></b><button disabled={saving} onClick={()=>patch({focus_rule_id:rule.id})} title="将此纪律设为本周重点"><Target size={15}/></button></div>):<div className="review-empty">{stats.reviewed_days?'本周尚未记录违规，继续保持。':'本周还没有复盘，先记录一天再回看。'}</div>}</section>
   <section className="review-week-form"><h3><Target size={17}/> 这周只抓住一个改进</h3>{draft.dirty&&<p className="review-note">{draft.restored?'已恢复每周总结草稿，尚未保存。':'每周总结有未保存修改。'}</p>}{draft.storageIssue&&<p role="status" className="review-error">{draft.storageIssue}</p>}{draft.stale&&<p className="review-error">草稿基于旧版本，请核对后载入已保存版本。</p>}
    <fieldset className="review-fields" disabled={saving}>{data.previous_weekly?.focus_rule_id&&<button onClick={()=>patch({focus_rule_id:data.previous_weekly!.focus_rule_id,action:data.previous_weekly!.action})}>沿用上周重点与行动</button>}<label className="review-label">本周重点纪律<select value={value.focus_rule_id} onChange={e=>patch({focus_rule_id:e.target.value})}><option value="">选择一条持续练习的纪律</option>{data.rules.map(r=><option key={r.id} value={r.id}>{r.title}{r.active?'':'（已停用）'}</option>)}</select></label>
    <label className="review-label">具体行动<textarea maxLength={5000} rows={3} placeholder="例如：每次下单前，把止损价和风险金额写下来。" value={value.action} onChange={e=>patch({action:e.target.value})}/></label><label className="review-label">本周总结<textarea maxLength={5000} rows={5} placeholder="哪些问题反复出现？改进动作有没有执行？下周继续练习什么？" value={value.summary} onChange={e=>patch({summary:e.target.value})}/></label></fieldset>
    <fieldset className="review-fields" disabled={saving}><CitationPicker market={market} onInsert={ref=>{
      const summary=[value.summary,ref].filter(Boolean).join('\n');
      if(summary.length>5000){setError('周总结已达字数上限，请缩短后再引用');return}
      patch({summary});setError('');
    }}/><CitationLinks market={market} text={value.action+'\n'+value.summary}/></fieldset>
    {error&&<p className="review-error" role="alert">{error}</p>}<div className="review-save-row"><button disabled={saving} onClick={()=>{if(draft.reset())onReload()}}>载入已保存版本</button><button className="review-primary" disabled={saving||draft.stale} onClick={save}><Save size={15}/>{saving?'保存中…':'保存每周总结'}</button></div>
   </section></div>
 </div>;
}

function RuleRow({rule,market,onSaved}:{rule:Discipline;market:ReviewMarket;onSaved:()=>void}){
 const [title,setTitle]=useState(rule.title),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function save(active:boolean){setBusy(true);setError('');try{await reviewRequest(`rules/${rule.id}?market=${market}`,{method:'PUT',body:JSON.stringify({title,active,revision:rule.revision})});onSaved()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <div className={`review-rule-row ${rule.active?'':'inactive'}`}><span className="review-badge">{rule.active?'使用中':'已停用'}</span><input aria-label={`纪律名称 ${rule.title}`} maxLength={120} value={title} onChange={e=>setTitle(e.target.value)} disabled={busy}/><button disabled={busy||!title.trim()||title.trim()===rule.title} onClick={()=>save(rule.active)}>保存名称</button><button disabled={busy} onClick={()=>save(!rule.active)}>{rule.active?'停用':'重新启用'}</button>{error&&<p role="alert" className="review-error">{error}</p>}</div>;
}

function RulesManager({data,market,onSaved}:{data:ReviewDashboard;market:ReviewMarket;onSaved:()=>void}){
 const [title,setTitle]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function add(){setBusy(true);setError('');try{await reviewRequest(`rules?market=${market}`,{method:'POST',body:JSON.stringify({title})});setTitle('');onSaved()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <section className="review-rules"><span className="review-eyebrow">YOUR TRADING RULES</span><h2>{market==='CN'?'A 股':'美股'}交易纪律</h2><p className="review-muted">可以从预设纪律开始，也可以换成自己的表达。改名或停用不会修改过去已保存的复盘。</p><div className="review-new-rule"><input aria-label="新增交易纪律" value={title} maxLength={120} placeholder="写一条可执行、可以检查的交易纪律……" disabled={busy} onChange={e=>setTitle(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing&&title.trim())void add()}}/><button className="review-primary" disabled={busy||!title.trim()} onClick={add}><Plus size={15}/>{busy?'添加中…':'添加纪律'}</button></div>{error&&<p className="review-error" role="alert">{error}</p>}<div className="review-rules-list">{data.rules.map(rule=><RuleRow key={`${rule.id}:${rule.revision}`} rule={rule} market={market} onSaved={onSaved}/>)}</div></section>;
}

export default function DailyReview({market,currentSymbol,names,onMarketChange,onOpen}:Props){
 const section=useRef<HTMLElement>(null);
 const [day,setDay]=useState(()=>marketToday(market)),[tab,setTab]=useState<'daily'|'weekly'|'history'|'rules'|'ledger'>(()=>new URLSearchParams(location.search).get('section')==='ledger'?'ledger':'daily');
 useEffect(()=>{
  const url=new URL(location.href);
  if(tab==='ledger')url.searchParams.set('section','ledger');else url.searchParams.delete('section');
  if(url.href!==location.href)window.history.replaceState(window.history.state,'',url);
 },[tab]);
 const [bookTarget,setBookTarget]=useState<RecordTarget|null>(null);
 useEffect(()=>{
  function openRecord(event:Event){
   const ref=(event as CustomEvent<RecordTarget & {market:ReviewMarket}>).detail;
   if(ref?.market===market&&(ref.kind==='plan'||ref.kind==='fill')&&ref.id){setBookTarget({...ref});setTab('ledger')}
  }
  window.addEventListener('nas-ledger-open',openRecord);return()=>window.removeEventListener('nas-ledger-open',openRecord);
 },[market]);
 const [data,setData]=useState<ReviewDashboard|null>(null),[error,setError]=useState(''),[reload,setReload]=useState(0),[loading,setLoading]=useState(false),[notice,setNotice]=useState(''),[exporting,setExporting]=useState(false);
 const refresh=()=>{setNotice('已保存到 NAS');setReload(n=>n+1)};
 useEffect(()=>{
  const controller=new AbortController();
  let pending=false;
  const editing=()=>Boolean(section.current?.querySelector('[data-review-editing="true"], .review-rules'));
  async function load(background=false){
   if(pending||(background&&(document.hidden||editing())))return;
   pending=true;
   if(!background){setLoading(true);setError('')}
   try{
    const result=await reviewRequest<ReviewDashboard>(`dashboard?market=${market}&day=${day}`,{signal:controller.signal,cache:'no-store'});
    if(!controller.signal.aborted&&(!background||!editing()))setData(result);
   }catch(e){if(!controller.signal.aborted&&!background)setError((e as Error).message)}
   finally{pending=false;if(!controller.signal.aborted&&!background)setLoading(false)}
  }
  void load();
  const sync=()=>void load(true);
  const timer=window.setInterval(sync,20000);
  window.addEventListener('focus',sync);
  return()=>{controller.abort();window.clearInterval(timer);window.removeEventListener('focus',sync)};
 },[market,day,reload]);
 useEffect(()=>{setNotice('')},[day,tab]);
 async function exportRecords(){setExporting(true);try{const result=await reviewRequest(`export?market=${market}`);const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`${market}-交易复盘-${marketToday(market)}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setNotice('已导出全部已保存记录（不包含草稿）')}catch(e){setError((e as Error).message)}finally{setExporting(false)}}
 const current=data?.day===day?data:null;
 return <section ref={section} className="daily-review" aria-label="每日复盘"><div className="review-page-header"><div className="review-page-title"><span className="review-title-icon"><BookOpen size={23}/></span><div><span className="review-eyebrow">TRADING JOURNAL</span><h1>每日复盘</h1><p>记录每一次偏离，让改进有迹可循。</p></div></div><button disabled={exporting} onClick={exportRecords}><Download size={15}/>{exporting?'导出中…':'导出记录'}</button></div>
  <div className="review-controls"><div className="review-market-switch" role="group" aria-label="复盘市场"><button aria-pressed={market==='CN'} onClick={()=>onMarketChange('CN')}>A 股</button><button aria-pressed={market==='US'} onClick={()=>onMarketChange('US')}>美股</button></div>{tab!=='ledger'&&<><div className="review-date-picker"><button aria-label="前一天" onClick={()=>setDay(shiftDay(day,-1))}><ChevronLeft size={16}/></button><input aria-label="复盘日期" type="date" min="2000-01-01" max="2099-12-31" value={day} onChange={e=>{if(/^\d{4}-\d{2}-\d{2}$/.test(e.target.value)&&e.target.validity.valid)setDay(e.target.value)}}/><button aria-label="后一天" onClick={()=>setDay(shiftDay(day,1))}><ChevronRight size={16}/></button><button onClick={()=>setDay(marketToday(market))}>今天</button></div><span className="review-timezone">{market==='CN'?'按北京时间记录':'按美东日期记录'} · 支持补录</span></>}</div>
  <nav className="review-tabs" aria-label="复盘内容">{([['daily','每日记录'],['ledger','交易档案'],['weekly','每周总结'],['history','历史回看'],['rules','纪律管理']] as const).map(([id,label])=><button key={id} aria-pressed={tab===id} onClick={()=>{if(id==='ledger')setBookTarget(null);setTab(id)}}>{label}</button>)}</nav>
  {notice&&<p className="review-success" role="status"><Check size={15}/>{notice}</p>}{error&&<div className="review-error" role="alert">{error}<button onClick={()=>setReload(n=>n+1)}>重新读取</button></div>}
  {tab==='ledger'&&<TradeBook key={market} market={market} currentSymbol={currentSymbol} target={bookTarget} onJournal={(kind,date)=>{setDay(date);setTab(kind==='day'?'daily':'weekly')}}/>}
  {loading&&tab!=='ledger'&&<p className="review-loading" role="status">正在读取复盘…</p>}
  {current&&<div className="review-content" aria-busy={loading}>
   {tab==='daily'&&<DailyEditor key={`${day}:${current.entry?.revision||0}`} data={current} market={market} currentSymbol={currentSymbol} names={names} onOpen={onOpen} onSaved={refresh} onReload={()=>{setNotice('');setReload(n=>n+1)}}/>}
   {tab==='weekly'&&<WeeklyReview key={`${current.week_start}:${current.weekly.revision}`} data={current} market={market} onDate={setDay} onSaved={refresh} onReload={()=>{setNotice('');setReload(n=>n+1)}}/>}
   {tab==='rules'&&<RulesManager data={current} market={market} onSaved={refresh}/>}
   {tab==='history'&&<section className="review-history"><div className="review-section-heading"><div><span className="review-eyebrow">PAST ENTRIES</span><h2>{day.slice(0,7)} 的复盘记录</h2></div><div className="review-month-nav"><button aria-label="上个月" onClick={()=>setDay(shiftDay(day.slice(0,7)+'-01',-1))}>上个月</button><button aria-label="下个月" onClick={()=>{const next=new Date(day+'T12:00:00Z');next.setUTCDate(1);next.setUTCMonth(next.getUTCMonth()+1);setDay(next.toISOString().slice(0,10))}}>下个月</button></div></div>{current.history.length?<div className="review-history-list">{current.history.map(entry=><button key={entry.day} onClick={()=>{setDay(entry.day);setTab('daily')}}><strong>{entry.day}</strong><span>{entry.traded?'有交易':'观察日'}</span><span className={entry.violation_count?'review-history-warning':''}>{entry.violation_count?`${entry.violation_count} 项违规`:'未记录违规'}</span><small>{entry.symbol_count} 个标的</small><p>{entry.lesson||'查看这天的复盘'}</p><ChevronRight size={17}/></button>)}</div>:<div className="review-empty">这个月还没有保存的复盘。<button onClick={()=>setTab('daily')}>记录选中日期</button></div>}</section>}
  </div>}
 </section>;
}
