import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowUpRight,Check,ChevronRight,Plus,RefreshCw,Search} from 'lucide-react';
import type {ReviewMarket} from './reviewClient';
import PlanDailyHistory from './PlanDailyHistory';
import {displayPlanPrice} from './tradePlanAnalysis';
import {EntryForm,ExecutionForm,PlanForm,PlanSummary} from './TradeBookForms';
import {description,displayTime,ledgerRequest,ledgerSymbol,periodNames,sideNames,sourceName,statusNames,unit,type Backlink,type BookPage,type Fill,type Holding,type Plan,type RecordTarget,type SyncStatus} from './tradeBookClient';
import './trade-book.css';

type Area='plans'|'fills'|'positions';
type Props={market:ReviewMarket;currentSymbol:string;target:RecordTarget|null;onJournal:(kind:'day'|'week',day:string)=>void};
type Selected={kind:'plan';record:Plan}|{kind:'fill';record:Fill};
const sectionNames={plans:'交易计划',fills:'成交档案',positions:'当前持仓'};
const emptyBook:BookPage={plans:[],fills:[],positions:[],accounts:[],next_offset:null};

function FillTitle({fill}:{fill:Fill}){
 return <><strong>{description(fill)}</strong><span>{sideNames[fill.side]||fill.side} {fill.qty} {unit(fill)} @ {fill.price}</span></>;
}
function BrokerSync({onChange}:{onChange:()=>void}){
 const [status,setStatus]=useState<SyncStatus|null>(null),[error,setError]=useState(''),[pending,setPending]=useState(false),[poll,setPoll]=useState(0);
 const last=useRef<string|null|undefined>(undefined),onChangeRef=useRef(onChange);
 onChangeRef.current=onChange;
 const active=status?.state==='queued'||status?.state==='running';
 useEffect(()=>{
  const controller=new AbortController();
  async function load(){
   try{
    const result=await ledgerRequest<SyncStatus>('US','broker','GET',undefined,controller.signal);
    if(controller.signal.aborted)return;
    if(last.current!==undefined&&result.last_success!==last.current)onChangeRef.current();
    last.current=result.last_success??null;setStatus(result);setError('');
   }catch(e){if(!controller.signal.aborted)setError((e as Error).message)}
  }
  void load();const timer=window.setInterval(()=>{if(!document.hidden)void load()},active?2500:15000);
  return()=>{controller.abort();clearInterval(timer)};
 },[poll,active]);
 async function sync(){
  setPending(true);setError('');
  try{await ledgerRequest('US','broker/sync','POST');setStatus(old=>({...old,accounts:old?.accounts||[],interval_seconds:old?.interval_seconds||300,state:'queued'}));setPoll(n=>n+1)}
  catch(e){setError((e as Error).message)}finally{setPending(false)}
 }
 return <div className="book-sync"><div><strong>{status?.provider==='opend'?'OpenD':status?.provider==='disabled'?'券商':status?.provider||'券商'} 自动同步</strong><small>{status?.message||({disabled:'当前未启用券商账户归档',idle:'等待首次同步',queued:'已加入同步队列',running:'正在读取券商记录',ready:'最近一次同步完成',error:'同步失败'}[status?.state||'idle'])}
  {status?.last_success&&' · '+displayTime('US',status.last_success)+' 美东'}</small>{error&&<small role="alert" className="book-warning">{error}</small>}</div>
  <button type="button" onClick={sync} disabled={status?.state==='disabled'||pending||active}><RefreshCw size={14}/>{pending||active?'同步中…':'立即同步'}</button></div>;
}

function RelatedJournals({market,target,onJournal}:{market:ReviewMarket;target:RecordTarget;onJournal:Props['onJournal']}){
 const [items,setItems]=useState<Backlink[]|null>(null),[error,setError]=useState('');
 useEffect(()=>{
  const ctl=new AbortController();setItems(null);setError('');
  ledgerRequest<{items:Backlink[]}>(market,`backlinks?kind=${target.kind}&id=${encodeURIComponent(target.id)}`,'GET',undefined,ctl.signal)
   .then(result=>{if(!ctl.signal.aborted)setItems(result.items)}).catch(e=>{if(!ctl.signal.aborted)setError((e as Error).message)});
  return()=>ctl.abort();
 },[market,target.id,target.kind]);
 return <div className="book-relations"><h3>引用这条记录的复盘</h3>{error?<p className="review-error" role="alert">{error}</p>:items?.length?
  items.map(item=><button key={item.kind+item.day} onClick={()=>onJournal(item.kind,item.day)}>{item.day} · {item.kind==='day'?'每日记录':'每周总结'}<ArrowUpRight size={13}/></button>):
  <p className="review-muted">{items?'暂无引用':'读取中…'}</p>}</div>;
}
function Candidate({market,fill,id,onSaved}:{market:ReviewMarket;fill:Fill;id:string;onSaved:(target:RecordTarget)=>void}){
 const [other,setOther]=useState<Fill|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{const ctl=new AbortController();
  ledgerRequest<Fill>(market,'fills/'+encodeURIComponent(id),'GET',undefined,ctl.signal).then(result=>{if(!ctl.signal.aborted)setOther(result)}).catch(e=>{if(!ctl.signal.aborted)setError((e as Error).message)});
  return()=>ctl.abort();
 },[market,id]);
 async function merge(){
  if(!other)return;
  setBusy(true);setError('');
  try{
   const imported=fill.source==='opend'||fill.source.startsWith('broker:');
   const result=await ledgerRequest<Fill>(market,'reconcile','POST',{manual_id:imported?other.id:fill.id,broker_fill_id:imported?fill.id:other.id});
   onSaved({kind:'fill',id:result.id,symbol:result.symbol});
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <div className="book-candidate">{other&&<><div><FillTitle fill={other}/><small>{displayTime(market,other.at)} · {sourceName(other.source)} · {other.account} · {other.broker_id||'无券商编号'}</small></div>
  <button onClick={()=>void merge()} disabled={busy}>{busy?'合并中…':'确认是同一笔，合并'}</button></>}
  {error&&<p role="alert" className="review-error">{error}</p>}</div>;
}
function HoldingRow({holding,market}:{holding:Holding;market:ReviewMarket}){
 return <tr><td><strong>{description(holding)}</strong>{holding.kind==='option'&&<small>{holding.code}</small>}</td><td>{holding.account}</td><td>{holding.qty} {unit(holding)}</td><td>{holding.cost??'—'}</td><td>{sourceName(holding.source)}<small>{displayTime(market,holding.as_of)}</small></td></tr>;
}
function PlanFillManager({market,plan,onChange,openRecord}:{market:ReviewMarket;plan:Plan;onChange:()=>void;openRecord:(target:RecordTarget)=>void}){
 const [fills,setFills]=useState<Fill[]>([]),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [loading,setLoading]=useState(true);
 useEffect(()=>{
  const ctl=new AbortController();
  setFills([]);setSelected('');setError('');setLoading(true);
  async function load(){
   const found=new Map<string,Fill>();
   let offset:number|null=0;
   do {
    const page:BookPage=await ledgerRequest(market,`book?symbol=${encodeURIComponent(plan.symbol)}&limit=200&offset=${offset}`,'GET',undefined,ctl.signal);
    for(const row of page.fills)found.set(row.id,row);
    offset=page.next_offset;
   } while(offset!==null&&!ctl.signal.aborted);
   if(!ctl.signal.aborted)setFills([...found.values()]);
  }
  void load().catch(e=>{if(!ctl.signal.aborted)setError((e as Error).message)})
   .finally(()=>{if(!ctl.signal.aborted)setLoading(false)});
  return()=>ctl.abort();
 },[market,plan.id,plan.symbol,plan.fill_ids]);
 const candidates=fills.filter(f=>!f.plan_id&&f.broker_status!=='CANCELLED'&&
  (f.side.startsWith('SELL')?'SELL':'BUY')===plan.side);
 async function change(fill:Fill,unlink:boolean){setBusy(true);setError('');
  try{await ledgerRequest(market,`plans/${plan.id}/fills/${fill.id}`,unlink?'DELETE':'PUT',{revision:fill.revision});onChange()}
  catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <section className="book-plan-fills"><h3>关联成交</h3>
  <div className="book-links">{plan.fill_ids?.length?plan.fill_ids.map(id=>{
   const f=fills.find(row=>row.id===id);
   return <span className="book-plan-fill" key={id}><button onClick={()=>openRecord({kind:'fill',id})}>{f?`${displayTime(market,f.at)} · ${f.qty}${unit(f)} @ ${f.price}`:'成交 '+id.slice(-8)}<ArrowUpRight size={13}/></button>
    {f&&<button disabled={busy} onClick={()=>void change(f,true)}>解除关联</button>}</span>;
  }):<span className="review-muted">尚未关联成交</span>}</div>
  <div className="book-plan-link"><select aria-label="选择要关联的成交" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">选择同标的、同方向的未关联成交</option>
   {candidates.map(f=><option key={f.id} value={f.id}>{displayTime(market,f.at)} · {sideNames[f.side]} {f.qty}{unit(f)} @ {f.price} · {f.account} · {sourceName(f.source)}</option>)}</select>
   <button disabled={busy||!selected} onClick={()=>{const f=candidates.find(row=>row.id===selected);if(f)void change(f,false)}}>关联成交</button></div>
  <p className="review-muted">{loading?'正在读取同标的成交…':!candidates.length?'暂无同方向、未关联且未撤销的成交。':'成交时计划尚未生效的，可以补关联用于复盘。'}</p>
  {error&&<p role="alert" className="review-error">{error}</p>}
 </section>;
}
function mergeRows<T extends {id:string}>(existing:T[],page:T[]){
 const rows=new Map(existing.map(r=>[r.id,r]));
 page.forEach(r=>rows.set(r.id,r));return [...rows.values()];
}
export default function TradeBook({market,currentSymbol,target,onJournal}:Props){
 const [area,setArea]=useState<Area>(market==='CN'?'plans':'fills'),[selection,select]=useState<RecordTarget|null>(target);
 const [detail,setDetail]=useState<Selected|null>(null),[detailError,setDetailError]=useState(''),[form,setForm]=useState<'plan'|'fill'|'holding'|'review'|null>(null);
 const [book,setBook]=useState<BookPage>(emptyBook),[error,setError]=useState(''),[notice,setNotice]=useState(''),[loading,setLoading]=useState(false);
 const [planBusy,setPlanBusy]=useState(false);
 const [offset,setOffset]=useState(0),[reload,setReload]=useState(0),[search,setSearch]=useState(''),[symbol,setSymbol]=useState(''),[asset,setAsset]=useState('all');
 function refresh(){setOffset(0);setReload(n=>n+1)}
 function openRecord(next:RecordTarget){
  setArea(next.kind==='plan'?'plans':'fills');setForm(null);setDetail(null);select(next);setNotice('');
 }
 useEffect(()=>{if(target)openRecord(target)},[target]);
 useEffect(()=>{
  const ctl=new AbortController();setLoading(true);setError('');
  const query=new URLSearchParams({limit:'100',offset:String(offset)});
  if(symbol)query.set('symbol',symbol);
  ledgerRequest<BookPage>(market,'book?'+query,'GET',undefined,ctl.signal).then(page=>{
   if(ctl.signal.aborted)return;
   setBook(prev=>offset?{...page,plans:mergeRows(prev.plans,page.plans),fills:mergeRows(prev.fills,page.fills)}:page);
  }).catch(e=>{if(!ctl.signal.aborted)setError((e as Error).message)}).finally(()=>{if(!ctl.signal.aborted)setLoading(false)});
  return()=>ctl.abort();
 },[market,reload,offset,symbol]);
 useEffect(()=>{
  if(!selection){setDetail(null);setDetailError('');return}
  const ctl=new AbortController();setDetailError('');
  const path=(selection.kind==='plan'?'plans/':'fills/')+encodeURIComponent(selection.id);
  async function load(){
   try{
    const row=selection!.kind==='plan'?{kind:'plan' as const,record:await ledgerRequest<Plan>(market,path,'GET',undefined,ctl.signal)}:{kind:'fill' as const,record:await ledgerRequest<Fill>(market,path,'GET',undefined,ctl.signal)};
    if(!ctl.signal.aborted)setDetail(row);
   }catch(e){if(!ctl.signal.aborted)setDetailError((e as Error).message)}
  }
  void load();return()=>ctl.abort();
 },[market,selection,reload]);
 function saved(next?:RecordTarget){
  setForm(null);if(next)openRecord(next);setNotice('已保存到 NAS');refresh();
 }
 async function removePlan(plan:Plan){
  if(!window.confirm(`删除 ${plan.symbol} 的交易计划及全部版本？`))return;
  setPlanBusy(true);setDetailError('');
  try{await ledgerRequest(market,`plans/${plan.id}`,'DELETE');select(null);setDetail(null);setNotice('交易计划已删除');refresh()}
  catch(e){setDetailError((e as Error).message)}finally{setPlanBusy(false)}
 }
 function switchArea(next:Area){
  setArea(next);setForm(null);select(null);setDetail(null);setNotice('');
 }
 function newEntry(){
  select(null);setDetail(null);setNotice('');setForm(area==='plans'?'plan':area==='fills'?'fill':'holding');
 }
 const accountNames=[...new Set([...(book.accounts||[]).map(a=>a.account),...book.fills.map(f=>f.account)])];
 const plan=detail?.kind==='plan'?detail.record:undefined, fill=detail?.kind==='fill'?detail.record:undefined;
 const visibleFills=book.fills.filter(f=>asset==='all'||f.kind===asset);
 const visiblePositions=book.positions.filter(h=>asset==='all'||h.kind===asset);
 const isDetail=Boolean(selection);
 const defaultSymbol=symbol||((market==='US')===currentSymbol.startsWith('US.')?currentSymbol:'');
 return <section className="book-panel" aria-label="交易档案" data-review-editing={form?'true':undefined}>
  <header className="book-header"><div><h2>交易档案</h2><span className="review-muted">{market==='CN'?'A 股 · 北京时间 · 人民币':'美股 · 美东时间 · 美元'}</span></div>
   <button type="button" onClick={refresh} disabled={loading}><RefreshCw size={14}/>刷新档案</button></header>
  <nav className="book-areas" aria-label="档案内容">{(Object.keys(sectionNames) as Area[]).map(k=><button key={k} aria-pressed={area===k} onClick={()=>switchArea(k)}>{sectionNames[k]}</button>)}</nav>
  {market==='US'&&<BrokerSync onChange={refresh}/>}
  {notice&&<p role="status" className="review-success"><Check size={14}/>{notice}</p>}
  {error&&<p role="alert" className="review-error">{error}</p>}
  {!isDetail&&!form&&<>
   <div className="book-toolbar"><form onSubmit={e=>{
    e.preventDefault();const raw=search.trim().toUpperCase();
    try{const code=raw?ledgerSymbol(raw,market):'';setBook(emptyBook);setSymbol(code);refresh()}
    catch(e){setError((e as Error).message)}
   }}><input aria-label="按标的代码筛选档案" value={search} onChange={e=>setSearch(e.target.value)} placeholder={market==='CN'?'标的代码，如 600519':'标的代码，如 AAPL'}/><button aria-label="查询标的"><Search size={15}/></button>
    {symbol&&<button type="button" onClick={()=>{setSearch('');setSymbol('');setBook(emptyBook);refresh()}}>全部标的</button>}</form>
    {area!=='plans'&&<select aria-label="筛选证券类型" value={asset} onChange={e=>setAsset(e.target.value)}><option value="all">正股和期权</option><option value="stock">正股 / ETF</option><option value="option">期权</option></select>}
    <button className="review-primary" onClick={newEntry}><Plus size={15}/>{area==='plans'?'新建计划':area==='fills'?'手动补录成交':'手动更新持仓'}</button>
   </div>
   {area==='plans'&&<div className="book-rows">{book.plans.map(p=><button key={p.id} className="book-list-row" onClick={()=>openRecord({kind:'plan',id:p.id,symbol:p.symbol})}>
    <span><strong>{p.symbol}</strong><small>{periodNames[p.period]} · {sideNames[p.side]} · {displayTime(market,p.updated_at)}</small></span>
    <span>{p.details?.title||p.trigger}<small>仓位 {p.size||'待定'} · 防守 {p.stop==null?'待定':displayPlanPrice(p.stop)}</small></span><span>{statusNames[p.status]}</span><ChevronRight size={15}/></button>)}</div>}
   {area==='fills'&&<div className="book-rows">{visibleFills.map(f=><button key={f.id} className="book-list-row" onClick={()=>openRecord({kind:'fill',id:f.id,symbol:f.symbol})}>
    <span><strong>{description(f)}</strong><small>{displayTime(market,f.at)} · {f.account}</small></span>
    <span>{sideNames[f.side]||f.side} {f.qty} {unit(f)} @ {f.price}<small>{sourceName(f.source)}{f.candidate_ids?.length?' · 有待核对成交':''}</small></span>
    <span>{f.broker_status==='CANCELLED'?'券商已撤销':f.review?'已复盘':'待复盘'}</span><ChevronRight size={15}/></button>)}</div>}
   {area==='positions'&&<>
    {visiblePositions.length>0&&<div className="book-table"><table><thead><tr><th>股票 / 合约</th><th>账户</th><th>数量</th><th>成本</th><th>来源 / 时间</th></tr></thead><tbody>{visiblePositions.map(p=><HoldingRow key={p.account+'|'+p.code} market={market} holding={p}/>)}</tbody></table></div>}
    {book.accounts?.map(a=><small className="book-snapshot" key={a.account}>{a.account} · {a.complete?'完整持仓':'局部持仓更新'} · {displayTime(market,a.as_of)}</small>)}
   </>}
   {!error&&!loading&&((area==='plans'&&!book.plans.length)||(area==='fills'&&!visibleFills.length)||(area==='positions'&&!visiblePositions.length))&&<p className="review-empty">{symbol?'此标的暂无对应记录':area==='plans'?'暂无交易计划':area==='fills'?'暂无对应成交':'暂无对应持仓'}</p>}
   {loading&&<p role="status" className="review-loading">正在读取档案…</p>}
   {area!=='positions'&&book.next_offset!=null&&<button disabled={loading} onClick={()=>setOffset(book.next_offset!)}>加载更多</button>}
  </>}
  {isDetail&&<div className="book-actions"><button onClick={()=>switchArea(area)}><ArrowLeft size={14}/>返回{sectionNames[area]}</button></div>}
  {detailError&&isDetail&&<p className="review-error" role="alert">{detailError}</p>}
  {isDetail&&!detail&&!detailError&&<p className="review-loading" role="status">读取记录…</p>}
  {plan&&!form&&<article className="book-detail">
   <header><div><h3>{plan.symbol} · {sideNames[plan.side]}计划</h3><small>{periodNames[plan.period]} · {statusNames[plan.status]} · 制定于 {displayTime(market,plan.created_at)}</small></div><div className="book-plan-actions"><button onClick={()=>setForm('plan')}>修订计划</button><button disabled={planBusy} onClick={()=>void removePlan(plan)}>删除计划</button></div></header>
   <PlanSummary plan={plan}/>
   <PlanDailyHistory key={market+plan.id+reload} market={market} id={plan.id} period={plan.details?.tracking_period}/>
   {plan.history?.length>0&&<details><summary>计划版本（{plan.history.length}）</summary>{plan.history.map(v=><section className="book-version" key={v.revision}><strong>版本 {v.revision} · {displayTime(market,v.updated_at)}</strong><PlanSummary plan={v}/></section>)}</details>}
   <PlanFillManager market={market} plan={plan} onChange={refresh} openRecord={openRecord}/>
  </article>}
  {fill&&!form&&<article className="book-detail">
   <header><div><h3>{description(fill)}</h3><small>{displayTime(market,fill.at)} · {sourceName(fill.source)} · {fill.account}</small></div><button className="review-primary" onClick={()=>setForm('review')}>{fill.review?'修改复盘':'写逐笔复盘'}</button></header>
   <dl className="book-metrics"><div><dt>方向 / 数量</dt><dd>{sideNames[fill.side]||fill.side} {fill.qty} {unit(fill)}</dd></div><div><dt>成交价</dt><dd>{fill.price}</dd></div><div><dt>券商成交编号</dt><dd>{fill.broker_id||'待补充'}</dd></div>
    {fill.kind==='option'&&<div><dt>合约代码</dt><dd>{fill.code}</dd></div>}{fill.broker_status&&fill.broker_status!=='OK'&&<div><dt>券商状态</dt><dd>{fill.broker_status==='CANCELLED'?'券商已撤销':fill.broker_status==='CHANGED'?'券商已更正':fill.broker_status}</dd></div>}</dl>
   <h3>成交时的交易计划</h3>{fill.plan_snapshot?<PlanSummary plan={fill.plan_snapshot}/>:<p className="review-muted">{fill.plan_id?'复盘补关联 · 成交时没有生效的计划版本':'未关联计划'}</p>}
   {fill.plan_id&&<button onClick={()=>openRecord({kind:'plan',id:fill.plan_id!})}>查看完整计划<ArrowUpRight size={13}/></button>}
   {fill.review&&<><h3>逐笔复盘</h3><dl className="book-metrics"><div><dt>计划执行</dt><dd>{fill.review.execution}</dd></div><div><dt>执行质量</dt><dd>{fill.review.quality}</dd></div></dl><p className="book-note">{fill.review.note}</p>
    {fill.review.group_ids?.filter(id=>id!==fill.id).map(id=><button key={id} onClick={()=>openRecord({kind:'fill',id})}>同组成交 {id.slice(-8)}<ArrowUpRight size={13}/></button>)}</>}
   {fill.candidate_ids?.length>0&&<section><h3>可能重复的成交</h3>{fill.candidate_ids.map(id=><Candidate key={id} market={market} fill={fill} id={id} onSaved={saved}/>)}</section>}
  </article>}
  {selection&&detail&&!form&&<RelatedJournals market={market} target={selection} onJournal={onJournal}/>}
  {form==='plan'&&<PlanForm key={plan?.id||'new-plan'} market={market} plan={plan} symbol={defaultSymbol} onCancel={()=>setForm(null)} onSaved={saved}/>}
  {(form==='fill'||form==='holding')&&<EntryForm key={form} market={market} mode={form} accounts={accountNames} plans={book.plans} symbol={defaultSymbol} onCancel={()=>setForm(null)} onSaved={saved}/>}
  {form==='review'&&fill&&<ExecutionForm key={fill.id} market={market} fill={fill} plans={book.plans} fills={book.fills} onCancel={()=>setForm(null)} onSaved={saved}/>}
 </section>;
}
