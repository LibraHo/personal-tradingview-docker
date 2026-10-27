import {useEffect,useRef,useState} from 'react';

type Row=Record<string,any>;
export const isOptionCode=(code:string)=>/^US\.[A-Z][A-Z0-9.]{0,11}\d{6}[CP]\d{1,10}$/.test(code);
const money=(v:any)=>v==null?'—':`$${Number(v).toFixed(2)}`;

export default function OptionsPanel({api,underlying,positions,quantities,canTrade,busy,quick,onOrder,onSaveQuantities,onSelectionChange}:
 {api:(path:string)=>Promise<any>;underlying:string;positions:Row[];quantities:number[];canTrade:boolean;busy:boolean;quick:boolean;
 onOrder:(body:Row)=>void;onSaveQuantities:(values:number[])=>Promise<void>;onSelectionChange:()=>void}){
 const [stock,setStock]=useState(underlying),[dates,setDates]=useState<string[]>([]),[expiry,setExpiry]=useState('');
 const [contracts,setContracts]=useState<Row[]>([]),[direction,setDirection]=useState('CALL'),[code,setCode]=useState('');
 const [quote,setQuote]=useState<Row|null>(null),[limit,setLimit]=useState(''),[qty,setQty]=useState(1);
 const [loading,setLoading]=useState(false),[error,setError]=useState(''),[editing,setEditing]=useState(false),[draft,setDraft]=useState('');
 const sequence=useRef(0),chainSequence=useRef(0),stockSequence=useRef(0);
 const holdings=positions.filter(p=>isOptionCode(p.code));
 const position=holdings.find(p=>p.code===code),available=Math.floor(Number(position?.can_sell_qty)||0);
 const validQuote=quote?.code===code&&quote?.stock_type==='OPTION';
 const multiplier=validQuote?Number(quote.option_contract_multiplier):0;
 const ready=canTrade&&!busy&&!loading&&validQuote&&Number(limit)>0&&Number.isInteger(qty)&&qty>0;
 useEffect(()=>{setStock(underlying);setDates([]);setExpiry('');setContracts([]);setCode('');setQuote(null);setLimit('');sequence.current++;chainSequence.current++;stockSequence.current++;setLoading(false)},[underlying]);
 useEffect(()=>()=>{sequence.current++;chainSequence.current++;stockSequence.current++},[]);
 const choose=async(value:string)=>{
  onSelectionChange();
  const token=++sequence.current;setCode(value);setQuote(null);setLimit('');setError('');
  if(!value){setLoading(false);return}setLoading(true);
  try{const q=await api('quote?code='+encodeURIComponent(value));if(token===sequence.current)setQuote(q)}
  catch(e){if(token===sequence.current)setError(String(e instanceof Error?e.message:e))}
  finally{if(token===sequence.current)setLoading(false)}
 };
 const loadDates=async()=>{
  const token=++stockSequence.current;chainSequence.current++;void choose('');setDates([]);setExpiry('');setContracts([]);setError('');
  try{const r=await api('options?code='+encodeURIComponent(stock.toUpperCase()));if(token===stockSequence.current)setDates(r.expirations)}
  catch(e){if(token===stockSequence.current)setError(String(e instanceof Error?e.message:e))}
 };
 const loadChain=async(date:string)=>{
  const token=++chainSequence.current;setExpiry(date);setContracts([]);void choose('');
  if(!date)return;
  try{const r=await api('options?code='+encodeURIComponent(stock.toUpperCase())+'&expiry='+date);if(token===chainSequence.current)setContracts(r.contracts)}
  catch(e){if(token===chainSequence.current)setError(String(e instanceof Error?e.message:e))}
 };
 const send=(side:string,count:number,close=false)=>onOrder({action:'PLACE',code,side,qty:count,price:Number(limit),
  order_type:'NORMAL',session:'RTH',time_in_force:'DAY',...(close?{close_position:true}:{})});
 return <section className="trade-card option-panel" aria-label="期权快捷交易"><fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}>
  <div className="trade-card-title"><h2>期权快捷交易 <small>单腿 Call / Put</small></h2><span className="trade-pill">{quick?'快捷模式 · 直接提交':'提交前预览'}</span></div>
  <div className="trade-ticket-grid"><label>标的股票<div className="trade-inline"><input aria-label="期权标的" value={stock} onChange={e=>{stockSequence.current++;chainSequence.current++;void choose('');setStock(e.target.value.toUpperCase());setDates([]);setContracts([]);setExpiry('')}}/><button disabled={busy} onClick={()=>void loadDates()}>读取到期日</button></div></label>
   <label>到期日<select aria-label="期权到期日" value={expiry} onChange={e=>void loadChain(e.target.value)}><option value="">选择到期日</option>{dates.map(d=><option key={d}>{d}</option>)}</select></label>
   <label>方向<select aria-label="期权方向" value={direction} onChange={e=>{setDirection(e.target.value);void choose('')}}><option value="CALL">Call · 看涨</option><option value="PUT">Put · 看跌</option></select></label>
   <label>行权价 / 合约<select aria-label="期权合约" value={code} onChange={e=>void choose(e.target.value)}><option value="">选择具体合约</option>{contracts.filter(c=>c.option_type===direction).sort((a,b)=>a.strike_price-b.strike_price).map(c=><option key={c.code} value={c.code}>{money(c.strike_price)} · {c.code}{c.option_standard_type&&c.option_standard_type!=='STANDARD'?' · 非标准':''}</option>)}</select></label>
  </div>
  {!!holdings.length&&<div className="trade-row-actions">{holdings.map(p=><button key={p.code} disabled={busy} onClick={()=>void choose(p.code)}>持仓 · {p.code} · {p.qty} 张</button>)}</div>}
  {code&&<p className="trade-small">已选：<strong>{code}</strong>{validQuote&&<> · {quote.option_type} · 到期 {quote.strike_time} · 行权价 {money(quote.option_strike_price)} · 合约乘数 {multiplier||'未知'}</>}</p>}
  {loading&&<p>正在读取合约快照…</p>}
  {validQuote&&<div className="trade-quote"><strong>最新 {money(quote.last_price)}</strong><span>买一 {money(quote.bid_price)} / 卖一 {money(quote.ask_price)} · 快照 {quote.update_time}（美东）</span><div className="trade-row-actions"><button disabled={busy||!(Number(quote.bid_price)>0)} onClick={()=>setLimit(String(quote.bid_price))}>用买一价</button><button disabled={busy||!(Number(quote.ask_price)>0)} onClick={()=>setLimit(String(quote.ask_price))}>用卖一价</button><button disabled={busy||loading} onClick={()=>void choose(code)}>刷新快照并清空限价</button></div></div>}
  <div className="trade-ticket-grid"><label>期权数量（张）<input aria-label="期权张数" type="number" min="1" step="1" value={qty} onChange={e=>setQty(Number(e.target.value))}/></label><label>每股权利金限价（USD）<input aria-label="期权限价" type="number" min="0.01" step="0.01" value={limit} onChange={e=>setLimit(e.target.value)}/></label></div>
  <div className="trade-row-actions">{quantities.map(n=><button key={n} onClick={()=>setQty(n)}>{n} 张</button>)}<button onClick={()=>{setDraft(quantities.join(','));setEditing(!editing)}}>自定义张数快捷键</button></div>
  {editing&&<div className="trade-inline"><input aria-label="期权快捷张数" value={draft} onChange={e=>setDraft(e.target.value)}/><button disabled={busy} onClick={async()=>{try{await onSaveQuantities(draft.split(',').map(Number));setEditing(false);setError('')}catch(e){setError(String(e instanceof Error?e.message:e))}}}>保存</button></div>}
  <div className="trade-order-info"><span>权利金估算 · 不含费用</span><strong>{validQuote&&multiplier>0&&Number(limit)>0?money(qty*Number(limit)*multiplier):'—'}</strong></div>
  <div className="trade-row-actions"><button className="trade-buy" disabled={!ready} onClick={()=>send('BUY',qty)}>买入 {qty} 张</button><button className="trade-sell" disabled={!ready||available<qty} onClick={()=>send('SELL',qty)}>卖出 {qty} 张</button><button disabled={!ready||available<2} onClick={()=>send('SELL',Math.floor(available/2))}>卖出可卖一半</button><button className="trade-sell" disabled={!ready||!position||Number(position.qty)!==available||available<1} onClick={()=>send('SELL',Number(position?.qty),true)}>期权全部平仓</button></div>
  <p className="trade-small">仅 RTH / DAY 标准股票及 ETF 期权限价单；数量单位是张。卖出只减已有多头，不卖空、不自动行权；本版暂未开放期权止损和组合单。限价由你确认，快照可能延迟，权限及成交以券商为准。实盘须先手动解锁。</p>
  {error&&<div role="alert" className="trade-error">{error}</div>}
 </fieldset></section>;
}

