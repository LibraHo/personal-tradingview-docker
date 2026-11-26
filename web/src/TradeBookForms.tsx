import {Children,cloneElement,isValidElement,useId,useRef,useState,type FormEvent,type ReactNode} from 'react';
import type {ReviewMarket} from './reviewClient';
import TradingPlanEditor from './TradingPlanEditor';
import {conditionLabel,displayPlanPrice} from './tradePlanAnalysis';
import {absoluteTime,description,displayTime,ledgerRequest,ledgerSymbol,localStamp,periodNames,requestId,sideNames,unit,type Fill,type Plan,type PlanVersion,type RecordTarget} from './tradeBookClient';

type Props={market:ReviewMarket; onSaved:(target?:RecordTarget)=>void; onCancel:()=>void};
type FieldProps={label:string;children:ReactNode;wide?:boolean};
function Field({label,children,wide}:FieldProps){
 const labelId=useId();
 return <label className={'book-field'+(wide?' book-wide':'')}><span id={labelId}>{label}</span>{Children.map(children,child=>
  isValidElement<{'aria-labelledby'?:string}>(child)&&['input','select','textarea'].includes(String(child.type))?cloneElement(child,{'aria-labelledby':labelId}):child)}</label>;
}
function BookForm({title,submitText,children,submit,onCancel}:{
 title:string;submitText:string;children:ReactNode;submit:(form:FormData)=>Promise<void>;onCancel:()=>void;
}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 async function save(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(busy)return;
  const form=new FormData(event.currentTarget);
  setBusy(true);setError('');
  try{await submit(form)}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <form className="book-form" onSubmit={save}>
  <h3>{title}</h3>
  <fieldset disabled={busy}>{children}</fieldset>
  {error&&<p className="review-error" role="alert">{error}</p>}
  <div className="book-actions"><button type="button" disabled={busy} onClick={onCancel}>取消</button>
   <button className="review-primary" disabled={busy}>{busy?'保存中…':submitText}</button></div>
 </form>;
}
const str=(form:FormData,key:string)=>String(form.get(key)??'').trim();
export function PlanSummary({plan}:{plan:PlanVersion}){
 const details=plan.details;
 const entry=details?[details.entry.items.map(conditionLabel).join(details.entry.join==='all'?'，且 ':'，或 '),details.entry_note].filter(Boolean).join('\n'):plan.trigger;
 return <dl className="book-metrics">
  {details?.strategy==='limit_up'&&<div><dt>计划类型</dt><dd>打板计划</dd></div>}
  {details?.title&&<div><dt>计划名称</dt><dd>{details.title}</dd></div>}
  <div><dt>入场理由</dt><dd>{entry||plan.trigger}</dd></div>
  <div><dt>计划仓位</dt><dd>{plan.size||'待定'}</dd></div>
  <div><dt>防守价</dt><dd>{plan.stop==null?'待定':displayPlanPrice(plan.stop)}</dd></div>
  {details?.levels&&Object.entries({previous_high:'前高',previous_low:'前低',platform_high:'前期平台上沿',platform_low:'前期平台下沿',gap_up:'前期向上缺口',gap_down:'前期向下缺口',take_profit:'止盈位'}).map(([key,label])=>
   details.levels?.[key as keyof typeof details.levels]!=null?<div key={key}><dt>{label}</dt><dd>{details.levels[key as keyof typeof details.levels]}</dd></div>:null)}
  {details&&<><div><dt>出场条件</dt><dd>{[details.exit.items.map(conditionLabel).join(details.exit.join==='all'?'，且 ':'，或 '),details.exit_note].filter(Boolean).join('\n')||'待补充'}</dd></div>
   {details.risk.note&&<div><dt>风险考虑</dt><dd>{details.risk.note}</dd></div>}
   <div><dt>防守位来源</dt><dd>{details.risk.defense_source}{details.risk.defense_reference ? " · 保存时的跟随价" : ""}</dd></div>
   {details.risk.budget!==null&&<div><dt>风险预算</dt><dd>{details.risk.budget}</dd></div>}
   {details.notes&&<div><dt>其他想法</dt><dd>{details.notes}</dd></div>}</>}
 </dl>;
}
export function PlanForm({market,plan:loadedPlan,symbol,onSaved,onCancel}:Props & {plan?:Plan;symbol:string}){
 return <TradingPlanEditor market={market} plan={loadedPlan} symbol={symbol} onSaved={onSaved} onCancel={onCancel}/>;
}
export function EntryForm({market,symbol:initialSymbol,mode,accounts,plans,onSaved,onCancel}:Props & {
 symbol:string; mode:'fill'|'holding';accounts:string[];plans:Plan[];
}){
 const [kind,setKind]=useState('stock'),[symbol,setSymbol]=useState(initialSymbol),[key]=useState(requestId);
 const [stamp]=useState(()=>localStamp(market));
 const [selectedPlan,setSelectedPlan]=useState('');
 const isFill=mode==='fill',timezone=market==='CN'?'北京时间':'美东时间';
 let canonical='';try{canonical=ledgerSymbol(symbol,market)}catch{/* partial symbol */}
 async function save(form:FormData){
  const underlying=ledgerSymbol(symbol,market);
  const account=str(form,'account'),at=absoluteTime(market,str(form,'at'));
  const instrument={symbol:underlying,code:kind==='stock'?underlying:str(form,'code').toUpperCase(),kind,
   ...(kind==='option'?{expiry:str(form,'expiry'),strike:Number(str(form,'strike')),right:str(form,'right')}:{})};
  if(!isFill){
   const cost=str(form,'cost');
   await ledgerRequest(market,'positions','POST',{account,as_of:at,complete:false,source:'manual',rows:[{...instrument,qty:Number(str(form,'qty')),...(cost?{cost:Number(cost)}:{})}]});
   onSaved();return;
  }
  const brokerId=str(form,'broker_id');
  const result=await ledgerRequest<Fill>(market,'fills','POST',{...instrument,account,at,qty:Number(str(form,'qty')),
   price:Number(str(form,'price')),side:str(form,'side'),request_id:key,...(brokerId?{broker_id:brokerId}:{}),
   ...(selectedPlan?{plan_id:selectedPlan}:{}),manual_confirm:market==='US'});
  onSaved({kind:'fill',id:result.id,symbol:result.symbol});
 }
 const candidates=plans.filter(plan=>plan.symbol===canonical);
 return <BookForm title={isFill?'手动补录成交':'手动更新一项持仓'} submitText={isFill?'保存手动成交':'保存持仓'} submit={save} onCancel={onCancel}>
  <Field label="账户"><input name="account" required list="book-account-choices" placeholder="输入或选择账户"/><datalist id="book-account-choices">{accounts.map(a=><option key={a} value={a}/>)}</datalist></Field>
  <Field label={`${isFill?'成交':'持仓'}时间（${timezone}）`}><input type="datetime-local" step="1" name="at" required defaultValue={stamp}/></Field>
  <Field label="证券类型"><select value={kind} onChange={e=>setKind(e.target.value)}><option value="stock">正股 / ETF</option><option value="option">期权合约</option></select></Field>
  <Field label={kind==='stock'?'股票代码':'标的股票代码'}><input required value={symbol} onChange={e=>{setSymbol(e.target.value);setSelectedPlan('')}} placeholder={market==='CN'?'SH.510050':'US.AAPL'}/></Field>
  {kind==='option'&&<>
   <Field label="完整合约代码"><input name="code" required placeholder={market==='US'?'US.AAPL270115C200000':'SH.10000001'}/></Field>
   <Field label="到期日"><input type="date" name="expiry" required/></Field>
   <Field label="行权价"><input type="number" name="strike" min="0.00000001" step="any" required/></Field>
   <Field label="期权方向"><select name="right"><option value="C">看涨 Call</option><option value="P">看跌 Put</option></select></Field>
  </>}
  <Field label={`${isFill?'成交':'持仓'}数量（${kind==='stock'?'股':'张'}）`}><input type="number" name="qty" required step={kind==='option'?'1':'any'} min={isFill?'0.00000001':undefined}/></Field>
  {isFill?<>
   <Field label="成交价"><input type="number" name="price" min="0.00000001" step="any" required/></Field>
   <Field label="买卖方向"><select name="side"><option value="BUY">买入</option><option value="SELL">卖出</option>{market==='US'&&<><option value="SELL_SHORT">卖空</option><option value="BUY_BACK">买入平仓</option></>}</select></Field>
   <Field label="券商成交编号（选填）"><input name="broker_id" placeholder="券商成交明细中的编号"/></Field>
   <Field label="关联计划" wide><select value={selectedPlan} onChange={e=>setSelectedPlan(e.target.value)}><option value="">无关联计划</option>{candidates.map(p=><option key={p.id} value={p.id}>{p.symbol} · {periodNames[p.period]} · {p.trigger}</option>)}</select></Field>
  </>:<Field label="持仓成本（选填）"><input type="number" name="cost" step="any"/></Field>}
 </BookForm>;
}
export function ExecutionForm({market,fill:loadedFill,plans,fills,onSaved,onCancel}:Props & {fill:Fill;plans:Plan[];fills:Fill[]}){
 const [fill]=useState(loadedFill);
 const original=fill.review,linked=fill.plan_id||'';
 const [group,setGroup]=useState<string[]>(()=>original?.group_ids.filter(id=>id!==fill.id)||[]);
 const additional=fills.filter(f=>f.id!==fill.id&&f.account===fill.account&&f.symbol===fill.symbol);
 const candidates=plans.filter(p=>p.symbol===fill.symbol&&p.side===(fill.side.startsWith('SELL')?'SELL':'BUY'));
 const selectedVersions=useRef(new Map(fills.map(f=>[f.id,f.revision]))).current;
 async function save(form:FormData){
  await ledgerRequest(market,`fills/${fill.id}/review`,'PUT',{revision:fill.revision,plan_id:str(form,'plan_id')||null,
   execution:str(form,'execution'),quality:str(form,'quality'),note:str(form,'note'),group_ids:group,
   group_revisions:Object.fromEntries([...selectedVersions].filter(([id])=>group.includes(id)||original?.group_ids.includes(id)))});
  onSaved({kind:'fill',id:fill.id,symbol:fill.symbol});
 }
 return <BookForm title="逐笔复盘" submitText="保存复盘" submit={save} onCancel={onCancel}>
  <Field label="关联计划" wide><select name="plan_id" defaultValue={linked}><option value="">无关联计划</option>
   {linked&&!candidates.some(p=>p.id===linked)&&<option value={linked}>当前已关联的计划</option>}
   {candidates.map(p=><option key={p.id} value={p.id}>{periodNames[p.period]} · {sideNames[p.side]} · {p.trigger}</option>)}</select></Field>
  <Field label="计划执行情况"><input required name="execution" list="book-execution" defaultValue={original?.execution} placeholder="按计划、偏离、计划外或待核对"/><datalist id="book-execution">{['按计划执行','部分执行','偏离计划','计划外交易','待核对'].map(v=><option key={v} value={v}/>)}</datalist></Field>
  <Field label="执行质量"><input required name="quality" list="book-quality" defaultValue={original?.quality} placeholder="这次做得怎么样？"/><datalist id="book-quality">{['执行良好','有待改进','待核对'].map(v=><option key={v} value={v}/>)}</datalist></Field>
  <Field label="复盘心得" wide><textarea name="note" rows={3} defaultValue={original?.note}/></Field>
  {(additional.length>0||group.length>0)&&<details className="book-wide"><summary>与其他成交一起复盘（已选 {group.length} 笔）</summary>
   <div className="book-group">{additional.map(f=><label key={f.id}><input type="checkbox" checked={group.includes(f.id)} onChange={e=>{if(e.target.checked)selectedVersions.set(f.id,f.revision);setGroup(prev=>e.target.checked?[...prev,f.id]:prev.filter(id=>id!==f.id))}}/>
    <span>{displayTime(market,f.at)} · {description(f)} · {sideNames[f.side]||f.side} {f.qty}{unit(f)} @ {f.price}</span></label>)}</div></details>}
 </BookForm>;
}
