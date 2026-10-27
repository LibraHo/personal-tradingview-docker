import {useEffect,useRef,useState} from 'react';

type Row=Record<string,any>;
export const isOptionCode=(code:string)=>/^US\.[A-Z][A-Z0-9.]{0,11}\d{6}[CP]\d{1,10}$/.test(code);
const money=(v:any)=>v==null?'—':`$${Number(v).toFixed(2)}`;
const cents=(v:number)=>Math.floor(v*100+1e-8)/100;
const ratios=[['1/4','1/4 仓'],['1/3','1/3 仓'],['1/2','半仓'],['1','全仓']];

export default function OptionsPanel({api,underlying,positions,quantities,canTrade,busy,quick,onOrder,onSaveQuantities,onSelectionChange,account,env}:
 {api:(path:string)=>Promise<any>;underlying:string;positions:Row[];quantities:number[];canTrade:boolean;busy:boolean;quick:boolean;
 onOrder:(body:Row)=>void;onSaveQuantities:(values:number[])=>Promise<void>;onSelectionChange:()=>void;account:string;env:string}){
 const [stock,setStock]=useState(underlying),[dates,setDates]=useState<string[]>([]),[expiry,setExpiry]=useState('');
 const [contracts,setContracts]=useState<Row[]>([]),[direction,setDirection]=useState('CALL'),[code,setCode]=useState('');
 const [quote,setQuote]=useState<Row|null>(null),[limit,setLimit]=useState(''),[qty,setQty]=useState(1),[side,setSide]=useState('BUY');
 const [loading,setLoading]=useState(false),[error,setError]=useState(''),[editing,setEditing]=useState(false),[draft,setDraft]=useState('');
 const [fraction,setFraction]=useState(''),[sizing,setSizing]=useState<Row|null>(null),[sizingLoading,setSizingLoading]=useState(false),[nearest,setNearest]=useState<Row|null>(null);
 const [stopPrice,setStopPrice]=useState(''),[stopMode,setStopMode]=useState('STOP_LIMIT'),[tolerance,setTolerance]=useState('0.05');
 const sequence=useRef(0),chainSequence=useRef(0),stockSequence=useRef(0),sizeSequence=useRef(0);
 const holdings=positions.filter(p=>isOptionCode(p.code));
 const position=holdings.find(p=>p.code===code),available=Math.floor(Number(position?.can_sell_qty)||0);
 const validQuote=quote?.code===code&&quote?.stock_type==='OPTION',multiplier=validQuote?Number(quote.option_contract_multiplier):0;
 const ready=canTrade&&!busy&&!loading&&!sizingLoading&&validQuote&&Number(limit)>0&&Number.isInteger(qty)&&qty>0&&(!fraction||!!sizing);
 const stopRequested=stopPrice.trim()!=='';
 const stopLimit=cents(Number(stopPrice)-Number(tolerance)),stopValid=Number.isFinite(Number(stopPrice))&&Number(stopPrice)>0&&Number(stopPrice)===cents(Number(stopPrice))&&(stopMode==='STOP'||(Number.isFinite(Number(tolerance))&&Number(tolerance)>=0&&Number(tolerance)===cents(Number(tolerance))&&stopLimit>0));
 const invalidate=()=>{onSelectionChange()};
 const clear=()=>{sequence.current++;chainSequence.current++;stockSequence.current++;sizeSequence.current++;setDates([]);setExpiry('');setContracts([]);setCode('');setQuote(null);setLimit('');setStopPrice('');setFraction('');setSizing(null);setNearest(null);setLoading(false);setSizingLoading(false)};
 useEffect(()=>{setStock(underlying);clear()},[underlying]);
 useEffect(()=>()=>{sequence.current++;chainSequence.current++;stockSequence.current++;sizeSequence.current++},[]);
 const choose=async(value:string,fill=false)=>{
  invalidate();const token=++sequence.current;setCode(value);setQuote(null);setLimit('');setStopPrice('');setError('');
  if(!value){setLoading(false);return}setLoading(true);
  try{const q=await api('quote?code='+encodeURIComponent(value));if(token===sequence.current){setQuote(q);if(fill){const price=Number(side==='BUY'?q.ask_price:q.bid_price);if(price>0)setLimit(price.toFixed(2))}}}
  catch(e){if(token===sequence.current)setError(String(e instanceof Error?e.message:e))}
  finally{if(token===sequence.current)setLoading(false)}
 };
 const loadDates=async()=>{
  const token=++stockSequence.current;chainSequence.current++;void choose('');setDates([]);setExpiry('');setContracts([]);setNearest(null);setError('');
  try{const r=await api('options?code='+encodeURIComponent(stock.toUpperCase()));if(token===stockSequence.current)setDates(r.expirations)}
  catch(e){if(token===stockSequence.current)setError(String(e instanceof Error?e.message:e))}
 };
 const loadChain=async(date:string)=>{
  const token=++chainSequence.current;setExpiry(date);setContracts([]);setNearest(null);void choose('');if(!date)return;
  try{const r=await api('options?code='+encodeURIComponent(stock.toUpperCase())+'&expiry='+date);if(token===chainSequence.current)setContracts(r.contracts)}
  catch(e){if(token===chainSequence.current)setError(String(e instanceof Error?e.message:e))}
 };
 const chooseNearest=async(type:string)=>{
  const token=++chainSequence.current;invalidate();setDirection(type);setLoading(true);setError('');
  try{const r=await api('options/nearest?'+new URLSearchParams({code:stock,expiry,direction:type}));if(token!==chainSequence.current)return;setNearest(r);await choose(r.contract.code,true)}
  catch(e){if(token===chainSequence.current){setError(String(e instanceof Error?e.message:e));setLoading(false)}}
 };
 useEffect(()=>{
  const token=++sizeSequence.current;setSizing(null);setSizingLoading(false);
  if(!fraction||!account||!validQuote||!(Number(limit)>0))return;
  setSizingLoading(true);let cancelled=false;
  const timer=setTimeout(async()=>{try{const r=await api('options/size?'+new URLSearchParams({acc_id:account,env,code,side,fraction,price:limit}));if(!cancelled&&token===sizeSequence.current){setSizing(r);setQty(r.qty);setError('')}}catch(e){if(!cancelled&&token===sizeSequence.current){setQty(0);setError(String(e instanceof Error?e.message:e))}}finally{if(!cancelled&&token===sizeSequence.current)setSizingLoading(false)}},250);
  return()=>{cancelled=true;clearTimeout(timer)};
 },[fraction,account,env,code,side,limit,validQuote]);
 const send=(action:string,count:number,close=false)=>{
  const body:Row={action:'PLACE',code,side:action,qty:count,price:Number(limit),order_type:'NORMAL',session:'RTH',time_in_force:'DAY',...(close?{close_position:true}:{})};
  if(action==='BUY'&&stopRequested){if(!stopValid){setError('止损价须大于零且最多两位小数；容限不得导致卖出限价不大于零');return}if(env!=='REAL'){setError('模拟账户不支持止损，请清空止损价或切换实盘');return}body.protection={name:'期权快捷止损',percent:2.5,mode:stopMode,tolerance:Number(tolerance),trigger_price:Number(stopPrice)}}
  onOrder(body);
 };
 const changeLimit=(value:string)=>{invalidate();setLimit(value)};
 return <section className="trade-card option-panel" aria-label="期权快捷交易"><fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}>
  <div className="trade-card-title"><h2>期权下单</h2><span className="trade-pill">RTH · DAY · {quick?'直接提交':'先预览'}</span></div>
  <div className="option-step"><span className="step-number">1</span><h3>选择合约</h3></div>
  <div className="trade-ticket-grid"><label>标的股票<div className="trade-inline"><input aria-label="期权标的" value={stock} onChange={e=>{invalidate();clear();setStock(e.target.value.toUpperCase())}}/><button disabled={busy||loading} onClick={()=>void loadDates()}>读取到期日</button></div></label>
   <label>到期日<select aria-label="期权到期日" value={expiry} disabled={loading} onChange={e=>void loadChain(e.target.value)}><option value="">选择到期日</option>{dates.map(d=><option key={d}>{d}</option>)}</select></label></div>
  <div className="trade-row-actions option-nearest"><button disabled={!expiry||loading} onClick={()=>void chooseNearest('CALL')}>最近 Call</button><button disabled={!expiry||loading} onClick={()=>void chooseNearest('PUT')}>最近 Put</button><small>{nearest?`正股 ${money(nearest.underlying_price)} · ${nearest.update_time}（美东）`:'按正股现价选最近行权价；先选择到期日'}</small></div>
  <details className="option-manual"><summary>手动选择行权价</summary><div className="trade-ticket-grid"><label>方向<select aria-label="期权方向" value={direction} disabled={loading} onChange={e=>{setDirection(e.target.value);void choose('')}}><option value="CALL">Call · 看涨</option><option value="PUT">Put · 看跌</option></select></label><label>行权价 / 合约<select aria-label="期权合约" value={code} disabled={loading} onChange={e=>void choose(e.target.value,true)}><option value="">选择具体合约</option>{contracts.filter(c=>c.option_type===direction).sort((a,b)=>a.strike_price-b.strike_price).map(c=><option key={c.code} value={c.code}>{money(c.strike_price)} · {c.code}{c.option_standard_type&&c.option_standard_type!=='STANDARD'?' · 非标准':''}</option>)}</select></label></div></details>
  {!!holdings.length&&<details className="option-manual"><summary>从期权持仓选择 · {holdings.length}</summary><div className="trade-row-actions">{holdings.map(p=><button key={p.code} disabled={loading} onClick={()=>void choose(p.code,true)}>{p.code} · {p.qty} 张</button>)}</div></details>}
  {loading&&<p role="status">正在读取合约…</p>}
  {code&&<div className="option-selected"><strong>{code}</strong>{validQuote&&<span>{quote.option_type} · {quote.strike_time} · 行权价 {money(quote.option_strike_price)} · ×{multiplier||'未知'}</span>}</div>}
  <div className="option-trade-grid"><div className="option-sizing-block"><div className="option-step"><span className="step-number">2</span><h3>仓位与限价</h3></div>
  <div className="option-side" role="group" aria-label="期权买卖方向"><button aria-pressed={side==='BUY'} className="trade-buy" onClick={()=>{invalidate();setSide('BUY');setFraction('')}}>买入</button><button aria-pressed={side==='SELL'} className="trade-sell" onClick={()=>{invalidate();setSide('SELL');setFraction('')}}>卖出已有多头</button></div>
  <div className="trade-ticket-grid"><label>每股权利金限价（USD）<input aria-label="期权限价" type="number" min="0.01" step="0.01" value={limit} onChange={e=>changeLimit(e.target.value)}/></label><label>期权数量（张）<input aria-label="期权张数" type="number" min="1" step="1" value={qty} onChange={e=>{invalidate();setFraction('');setQty(Number(e.target.value))}}/></label></div>
  <div className="trade-row-actions">{validQuote&&<><button disabled={!(Number(quote.bid_price)>0)} onClick={()=>changeLimit(Number(quote.bid_price).toFixed(2))}>用买一价</button><button disabled={!(Number(quote.bid_price)>0&&Number(quote.ask_price)>0)} onClick={()=>changeLimit(((Number(quote.bid_price)+Number(quote.ask_price))/2).toFixed(2))}>中间价</button><button disabled={!(Number(quote.ask_price)>0)} onClick={()=>changeLimit(Number(quote.ask_price).toFixed(2))}>用卖一价</button><button onClick={()=>void choose(code)}>刷新快照并清空限价</button></>}<button disabled={Number(limit)<=.01} onClick={()=>changeLimit(Math.max(.01,Number(limit)-.01).toFixed(2))}>− $0.01</button><button onClick={()=>changeLimit((Number(limit)+.01).toFixed(2))}>＋ $0.01</button></div>
  {validQuote&&<p className="trade-small">买一 {money(quote.bid_price)} / 卖一 {money(quote.ask_price)} · 最新 {money(quote.last_price)} · {quote.update_time}（美东快照）</p>}
  <label className="option-ratio-label">{side==='BUY'?'买入 · 美元现金比例':'卖出 · 当前可卖持仓比例'}</label><div className="option-ratios">{ratios.map(([v,label])=><button key={v} aria-pressed={fraction===v} disabled={!validQuote||!(Number(limit)>0)||!account||loading} onClick={()=>{invalidate();setFraction(v)}}>{label}</button>)}</div>
  {sizingLoading&&<p role="status">正在按券商现金 / 可卖数量测算…</p>}{sizing&&<p className="trade-small">{side==='BUY'?`美元现金 ${money(sizing.cash_basis)} · 本次预算上限 ${money(sizing.budget)} · 费用预留 ${money(sizing.fee_reserve)}`:`可卖 ${sizing.available} 张`} → {sizing.qty} 张，整张向下取整。单笔限额仍适用。</p>}
  <details className="option-manual"><summary>固定张数快捷键</summary><div className="trade-row-actions">{quantities.map(n=><button key={n} onClick={()=>{invalidate();setFraction('');setQty(n)}}>{n} 张</button>)}<button onClick={()=>{setDraft(quantities.join(','));setEditing(!editing)}}>自定义张数快捷键</button></div>{editing&&<div className="trade-inline"><input aria-label="期权快捷张数" value={draft} onChange={e=>setDraft(e.target.value)}/><button onClick={async()=>{try{await onSaveQuantities(draft.split(',').map(Number));setEditing(false);setError('')}catch(e){setError(String(e instanceof Error?e.message:e))}}}>保存</button></div>}</details>
  </div><div className="option-stop-block"><div className="option-step"><span className="step-number">3</span><h3>止损保护 <small>可选 · 实盘</small></h3></div>
  <div className="trade-ticket-grid"><label>止损触发价<input aria-label="期权止损价" type="number" min="0.01" step="0.01" value={stopPrice} disabled={env!=='REAL'} onChange={e=>{invalidate();setStopPrice(e.target.value)}}/></label><label>止损方式<select aria-label="期权止损方式" value={stopMode} disabled={env!=='REAL'} onChange={e=>{invalidate();setStopMode(e.target.value)}}><option value="STOP_LIMIT">止损限价 · 可设容限</option><option value="STOP">止损市价 · 可能滑点</option></select></label>{stopMode==='STOP_LIMIT'&&<label>触发价以下容限（USD）<input aria-label="期权止损容限" type="number" min="0" step="0.01" value={tolerance} disabled={env!=='REAL'} onChange={e=>{invalidate();setTolerance(e.target.value)}}/></label>}</div>
  <div className="trade-row-actions">{[2.5,5,10].map(pct=><button key={pct} disabled={env!=='REAL'||!(Number(side==='BUY'?limit:position?.cost_price)>0)} onClick={()=>{invalidate();setStopPrice(cents(Number(side==='BUY'?limit:position?.cost_price)*(1-pct/100)).toFixed(2))}}>-{pct}%</button>)}<button onClick={()=>{invalidate();setStopPrice('')}}>清空止损</button><button disabled={!canTrade||env!=='REAL'||!validQuote||!stopValid||qty<1||qty>available||loading||sizingLoading} onClick={()=>onOrder({action:'PLACE',code,side:'SELL',qty,order_type:stopMode,aux_price:Number(stopPrice),price:stopMode==='STOP_LIMIT'?stopLimit:0,session:'RTH',time_in_force:'DAY'})}>给已有持仓挂止损</button></div>
  <p className="trade-small">{env!=='REAL'?'模拟账户不支持期权止损。':Number(stopPrice)>0?`触发 ${money(stopPrice)}${stopMode==='STOP_LIMIT'?` → 卖出限价 ${money(stopLimit)}`:' → 市价卖出'}；RTH / DAY。买入附带止损由 NAS 成交后补挂，存在未保护时间。`:'可输入固定触发价，或按买入限价 / 持仓成本快速填写比例。'}</p>
  </div></div>{stopRequested&&!stopValid&&<p role="alert" className="trade-error">止损价须大于零且最多两位小数；容限不得使卖出限价不大于零。请修正或明确清空止损。</p>}<div className="option-order-footer"><div><span>权利金估算 · 不含费用</span><strong>{validQuote&&multiplier>0&&Number(limit)>0?money(qty*Number(limit)*multiplier):'—'}</strong></div><div className="trade-row-actions"><button className={side==='BUY'?'trade-buy':'trade-sell'} disabled={!ready||(side==='SELL'&&available<qty)||(side==='BUY'&&stopRequested&&(!stopValid||env!=='REAL'))} onClick={()=>send(side,qty)}>{side==='BUY'?`买入 ${qty} 张${stopRequested?' ＋ 成交后止损':''}`:`卖出 ${qty} 张`}</button>{position&&<button className="trade-sell" disabled={!ready||Number(position.qty)!==available||available<1} onClick={()=>send('SELL',Number(position.qty),true)}>期权全部平仓</button>}</div></div>
  <details className="option-manual"><summary>交易与止损说明</summary><p className="trade-small">仅标准股票 / ETF 单腿期权，RTH / DAY。限价不保证成交，快照不等于可执行报价。止损市价可能滑点，止损限价跌穿限价可能无法成交。买入成交后止损约每 5 秒跟进，锁定、退出、重启或解锁到期会暂停；已受理券商订单按自身规则继续。组合单、指数、调整合约和裸卖暂不开放。不自动行权。</p></details>
  {error&&<div role="alert" className="trade-error">{error}</div>}
 </fieldset></section>;
}
