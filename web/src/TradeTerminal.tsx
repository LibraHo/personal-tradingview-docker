import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,LockKeyhole,ShieldCheck,RefreshCw,LogOut,Settings2,ArrowUpRight,ArrowDownRight} from 'lucide-react';
import './trading.css';

type Row=Record<string,any>;
type Preview={preview_id:string;expires:number;action:string;order:Row};
const orderNames:Record<string,string>={NORMAL:'限价',MARKET:'市价',STOP:'止损市价',STOP_LIMIT:'止损限价',TRAILING_STOP:'移动止损市价',TRAILING_STOP_LIMIT:'移动止损限价'};
const stateNames:Record<string,string>={UNSUBMITTED:'未提交',WAITING_SUBMIT:'等待提交',SUBMITTING:'提交中',SUBMITTED:'已提交',FILLED_PART:'部分成交',FILLED_ALL:'全部成交',CANCELLED_ALL:'已撤单',CANCELLED_PART:'部分撤单',FAILED:'失败',DISABLED:'未激活',DELETED:'已删除',CANCELLING_ALL:'撤单中',CANCELLING_PART:'撤单中'};
const opNames:Record<string,string>={SENDING:'发送中',ACCEPTED:'接口已受理',REJECTED:'已拒绝',UNKNOWN:'结果待核对',RECONCILED:'已核对',MANUALLY_REVIEWED:'人工已核对'};
const activeStates=['UNSUBMITTED','WAITING_SUBMIT','SUBMITTING','SUBMITTED','FILLED_PART','CANCELLING_PART','CANCELLING_ALL','DISABLED'];
const money=(v:any)=>v==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(Number(v));
const roundPrice=(v:number)=>Number(v.toFixed(v>=1?2:4));
const clock=(v:number)=>new Date(v*1000).toLocaleTimeString('zh-CN',{hour12:false});

export default function TradeTerminal(){
 const [auth,setAuth]=useState<Row|null>(null),[password,setPassword]=useState(''),[setup,setSetup]=useState('');
 const [accounts,setAccounts]=useState<Row[]>([]),[account,setAccount]=useState(''),[state,setState]=useState<Row>({});
 const [snapshot,setSnapshot]=useState<Row>({positions:[],orders:[],funds:[]}),[journal,setJournal]=useState<Row[]>([]);
 const [symbol,setSymbol]=useState(()=>new URLSearchParams(location.search).get('symbol')||'US.SNDK');
 const [quote,setQuote]=useState<Row|null>(null),[qty,setQty]=useState('10'),[limit,setLimit]=useState(''),[trigger,setTrigger]=useState('');
 const [kind,setKind]=useState('NORMAL'),[session,setSession]=useState('RTH'),[tif,setTif]=useState('DAY');
 const [trail,setTrail]=useState('2'),[trailType,setTrailType]=useState('PERCENTAGE'),[spread,setSpread]=useState('0.05');
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[quick,setQuick]=useState(false);
 const [preview,setPreview]=useState<Preview|null>(null),[unlockOpen,setUnlockOpen]=useState(false),[tradePassword,setTradePassword]=useState('');
 const [unlockConfirm,setUnlockConfirm]=useState(false),[tab,setTab]=useState('positions'),[editing,setEditing]=useState<Row|null>(null);
 const [prefs,setPrefs]=useState({quantities:[10,50,100],stops:[1,2,3]}),[prefsOpen,setPrefsOpen]=useState(false);
 const [qtyText,setQtyText]=useState('10,50,100'),[stopText,setStopText]=useState('1,2,3'),[now,setNow]=useState(Date.now()/1000);
 const csrf=useRef(''),actionBusy=useRef(false),refreshBusy=useRef(false),accountRef=useRef(account),authRef=useRef(false);
 accountRef.current=account;authRef.current=!!auth?.authenticated;
 const acc=accounts.find(a=>a.acc_id===account),env=acc?.trd_env||'SIMULATE';
 const unlocked=env==='REAL'&&state.unlock?.acc_id===account&&state.unlock.expires>now;
 const canTrade=!!acc&&(env==='SIMULATE'||unlocked),funds=snapshot.funds?.[0]||{};
 const blocked=journal.some(j=>['UNKNOWN','SENDING'].includes(j.state));
 const api=async(path:string,body?:any,method='POST')=>{
  const response=await fetch('/api/trade/'+path,{method:body===undefined?'GET':method,credentials:'same-origin',
   headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf.current},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok){if(response.status===401){setAuth({authenticated:false});setQuick(false)}throw Error(data.detail||'请求失败')}
  return data;
 };
 const perform=async(fn:()=>Promise<void>)=>{
  if(actionBusy.current)return;actionBusy.current=true;setBusy(true);setError('');setNotice('');
  try{const deadline=Date.now()+16000;while(refreshBusy.current&&Date.now()<deadline)await new Promise(r=>setTimeout(r,50));if(refreshBusy.current)throw Error('账户刷新仍在进行，请稍后操作');await fn()}catch(e){setError(String(e instanceof Error?e.message:e))}finally{actionBusy.current=false;setBusy(false)}
 };
 useEffect(()=>{
  const fragment=new URLSearchParams(location.hash.slice(1));setSetup(fragment.get('setup')||'');
  if(location.hash)history.replaceState(null,'',location.pathname+location.search);
  api('auth').then(a=>{setAuth(a);csrf.current=a.csrf||''}).catch(e=>setError(e.message));
  const tick=setInterval(()=>setNow(Date.now()/1000),1000);return()=>clearInterval(tick);
 },[]);
 const loadAccounts=async()=>{
  const r=await api('accounts');setAccounts(r.accounts);
  setAccount(old=>r.accounts.some((a:Row)=>a.acc_id===old)?old:r.accounts.find((a:Row)=>a.trd_env==='SIMULATE')?.acc_id||'');
 };
 useEffect(()=>{if(auth?.authenticated){perform(async()=>{
  await loadAccounts();const p=await api('presets');
  if(Array.isArray(p.quantities)&&Array.isArray(p.stops)){setPrefs(p);setQtyText(p.quantities.join(','));setStopText(p.stops.join(','))}
 })}},[auth?.authenticated]);
 const refresh=async()=>{
  if(refreshBusy.current||actionBusy.current||!authRef.current)return;
  refreshBusy.current=true;const expected=accountRef.current;
  try{
   const s=await api('state');setState(s);
   const selected=accounts.find(a=>a.acc_id===expected);
   if(selected){
    const query=`acc_id=${encodeURIComponent(expected)}&env=${selected.trd_env}`;
    const snap=await api('snapshot?'+query);const j=await api('journal?'+query);
    if(accountRef.current===expected){setSnapshot(snap);setJournal(j.operations)}
   }
  }catch(e){setError(String(e instanceof Error?e.message:e))}finally{refreshBusy.current=false}
 };
 useEffect(()=>{
  setQuick(false);setPreview(null);setSnapshot({positions:[],orders:[],funds:[]});setJournal([]);setEditing(null);
  setKind('NORMAL');setSession('RTH');setTif('DAY');
  void refresh();
  const timer=setInterval(()=>{if(!document.hidden)void refresh()},6000);
  const visibility=()=>{if(document.hidden)setQuick(false);else void refresh()};document.addEventListener('visibilitychange',visibility);
  return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',visibility)};
 },[account,accounts,auth?.authenticated]);
 useEffect(()=>{if(!canTrade)setQuick(false)},[canTrade]);
 useEffect(()=>{setQuote(null);setPreview(null)},[symbol]);
 const readQuote=()=>perform(async()=>{
  const code=symbol.toUpperCase().startsWith('US.')?symbol.toUpperCase():'US.'+symbol.toUpperCase();
  if(code!==symbol)setSymbol(code);
  const q=await api('quote?code='+encodeURIComponent(code));setQuote(q);
  if(!limit)setLimit(String(q.last_price));
 });
 const login=()=>perform(async()=>{
  const a=await api(auth?.setup_required?'setup':'login',{password,setup_code:setup||undefined});
  setPassword('');setSetup('');csrf.current=a.csrf;setAuth(a);
 });
 const execute=async(p:Preview)=>{
  const operation_id=crypto.randomUUID();setPreview(null);
  const r=await api('commit',{preview_id:p.preview_id,operation_id});
  setNotice(`${opNames[r.state]||r.state} · ${r.payload.code} · ${r.kind==='CANCEL'?'撤单':r.kind==='MODIFY'?'改单':'下单'}。成交状态请查看订单。`);
  if(r.state==='UNKNOWN')setError('结果待核对：不要重复下单。请在操作流水核对券商记录。');
  setTab('orders');setEditing(null);
 };
 const requestOrder=(body:Row)=>perform(async()=>{
  const p=await api('preview',{...body,acc_id:account,env});
  if(quick)await execute(p);else setPreview(p);
 });
 const order=(side:string)=>requestOrder({action:editing?'MODIFY':'PLACE',order_id:editing?.order_id,
  code:symbol,side,order_type:kind,qty:Number(qty),price:Number(limit),aux_price:Number(trigger),
  session,time_in_force:tif,trail_type:trailType,trail_value:Number(trail),trail_spread:Number(spread)});
 const usePosition=(p:Row,fraction:number)=>requestOrder({action:'PLACE',code:p.code,side:'SELL',order_type:'NORMAL',
  qty:Math.floor(Number(p.can_sell_qty)*fraction),price:roundPrice(Number(p.nominal_price)),
  session:env==='SIMULATE'?'RTH':session,time_in_force:env==='SIMULATE'?'DAY':tif});
 const stopPosition=(p:Row,percent:number)=>requestOrder({action:'PLACE',code:p.code,side:'SELL',order_type:'STOP',
  qty:Math.floor(Number(p.can_sell_qty)),aux_price:roundPrice(Number(p.nominal_price)*(1-percent/100)),session:'RTH',time_in_force:'GTC'});
 const modify=(o:Row)=>{
  setSymbol(o.code);setEditing(o);setQty(String(o.qty));setLimit(String(o.price));setTrigger(String(o.aux_price||''));setKind(o.order_type);setSession(o.session);setTif(o.time_in_force||'DAY');
 };
 const savePrefs=()=>perform(async()=>{
  const quantities=qtyText.split(',').map(Number),stops=stopText.split(',').map(Number);
  if(quantities.length>6||stops.length>5||quantities.some(n=>!Number.isInteger(n)||n<1||n>state.max_shares)||stops.some(n=>!Number.isFinite(n)||n<=0||n>=100))throw Error('股数须为有效整股，止损比例须介于 0 和 100；最多 6 个股数和 5 个比例');
  await api('presets',{quantities,stops},'PUT');setPrefs({quantities,stops});setPrefsOpen(false);setNotice('快捷设置已保存到 NAS');
 });
 const logout=()=>perform(async()=>{const r=await api('logout',{});setAuth({authenticated:false});setQuick(false);setState({});setNotice(r.message)});

 if(!auth?.authenticated)return <div className="trade-terminal trade-login"><div className="trade-login-card">
  <div className="trade-brand"><ShieldCheck size={25}/><span>NAS MARKET <b>TRADE</b></span></div>
  <h1>{auth?.setup_required?'设置交易平台':'登录交易平台'}</h1>
  <p>连接你的 OpenD，在浏览器中管理美股持仓和订单。</p>
  <div className="trade-lock-note"><LockKeyhole size={17}/>平台密码与 moomoo 交易密码分开。登录平台不会解锁实盘。</div>
  {auth?.setup_required&&<label>一次性初始化码<input aria-label="一次性初始化码" type="password" value={setup} onChange={e=>setSetup(e.target.value)} autoComplete="off"/></label>}
  <form onSubmit={e=>{e.preventDefault();void login()}}><label>{auth?.setup_required?'设置平台密码（至少 12 个字符）':'平台密码'}<input aria-label="平台密码" type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete={auth?.setup_required?'new-password':'current-password'}/></label>
  <button className="trade-primary" disabled={busy||!auth} type="submit">{busy?'正在验证…':auth?.setup_required?'设置并进入':'登录'}</button></form>
  {error&&<div role="alert" className="trade-error">{error}</div>}{notice&&<div className="trade-notice">{notice}</div>}
  <small>使用 HTTPS 加密连接。交易密码只在实盘解锁时输入，不保存到 NAS。</small>
 </div></div>;

 return <div className="trade-terminal">
  <header className="trade-header"><div className="trade-brand"><ShieldCheck size={24}/><span>NAS MARKET <b>TRADE</b></span></div>
   <div className="trade-header-actions"><a href={`${location.protocol}//${location.hostname}:8088`} onClick={e=>{e.preventDefault();window.open(`http://${location.hostname}:8088`,'_blank','noopener')}}><ArrowLeft size={15}/> 看盘</a><button onClick={()=>void refresh()} disabled={busy}><RefreshCw size={15}/> 刷新</button><button onClick={()=>void logout()} disabled={busy}><LogOut size={15}/> 退出</button></div></header>
  <div className="trade-shell"><section className="trade-intro"><div><div className="trade-eyebrow">US EQUITIES · EXECUTION DESK</div><h1>美股交易台</h1><p>持仓、订单和快捷操作，在一个页面完成。</p></div><div className={`trade-env ${env==='REAL'?'real':'paper'}`}>{acc?(env==='REAL'?'实盘账户':'模拟账户'):'请选择账户'}<small>{env==='REAL'?(unlocked?`已解锁 · ${Math.max(0,Math.ceil((state.unlock.expires-now)/60))} 分钟`:'交易已锁定'):'不使用真实资金'}</small></div></section>
   {error&&<div role="alert" className="trade-error">{error}<button onClick={()=>setError('')}>×</button></div>}
   {notice&&<div role="status" className="trade-notice">{notice}</div>}
   {blocked&&<div className="trade-error">存在结果待核对的操作，已暂停此账号的新操作。请查看“操作流水”。</div>}
   <div className="trade-top-grid"><section className="trade-card trade-account"><h2>账户与权限</h2>
    <label>交易账户<select aria-label="交易账户" value={account} onChange={e=>setAccount(e.target.value)} disabled={busy}><option value="">选择账户</option>{accounts.map(a=><option key={a.acc_id} value={a.acc_id}>{a.trd_env==='REAL'?'实盘':'模拟'} · 尾号 {a.acc_id.slice(-4)} · {a.acc_type}</option>)}</select></label>
    {!accounts.length&&<p className="trade-muted">未读取到美股账户。请检查 OpenD 登录及券商配置。<button onClick={()=>void perform(loadAccounts)}>重新读取</button></p>}
    <div className="trade-balance"><span>账户净资产 · USD</span><strong>{money(funds.total_assets)}</strong></div><div className="trade-metrics"><div><span>现金</span><b>{money(funds.cash)}</b></div><div><span>证券市值</span><b>{money(funds.market_val)}</b></div></div>
    <div className="trade-limit">单笔上限 {money(state.max_notional)} / {state.max_shares||'—'} 股<br/>第一版：整股、现金买入、卖出已有多头持仓</div>
    {env==='REAL'&&<button className={unlocked?'trade-secondary':'trade-primary'} disabled={busy||!account} onClick={()=>unlocked?void perform(async()=>{await api('lock',{});setState({...state,unlock:null});setQuick(false);setNotice('交易已锁定；券商已接受的订单继续按其规则有效')}):setUnlockOpen(true)}><LockKeyhole size={16}/>{unlocked?'立即锁定交易':'解锁实盘 · 15 分钟'}</button>}
    <label className={`trade-quick ${quick?'armed':''}`}><input type="checkbox" checked={quick} disabled={!canTrade||busy||blocked} onChange={e=>setQuick(e.target.checked)}/><span>快捷模式<small>开启后，买卖与止损按钮直接提交；切换账户或隐藏页面后关闭。</small></span></label>
   </section>
   <section className="trade-card trade-ticket"><div className="trade-card-title"><h2>{editing?'修改已有订单':'下单面板'}</h2>{editing?<button onClick={()=>setEditing(null)}>取消编辑</button>:<span className="trade-pill">{quick?'快捷直达':'提交前预览'}</span>}</div>
    <div className="trade-ticket-grid"><label>股票代码<div className="trade-inline"><input aria-label="交易股票" value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} disabled={!!editing}/><button onClick={()=>void readQuote()} disabled={busy}>行情</button></div></label><label>订单类型<select aria-label="订单类型" value={kind} disabled={!!editing} onChange={e=>setKind(e.target.value)}>{Object.entries(orderNames).filter(([k])=>env==='REAL'||['NORMAL','MARKET'].includes(k)).map(([k,n])=><option key={k} value={k}>{n}</option>)}</select></label></div>
    <div className="trade-quote">{quote?<><strong>{quote.name} · {money(quote.last_price)}</strong><span>快照 {quote.update_time}（美东）· 非买卖盘报价</span></>:<span>输入 US.股票代码，点击“行情”查看快照。限价由你填写。</span>}</div>
    <div className="trade-ticket-grid"><label>数量（股）<input aria-label="下单股数" type="number" min="1" step="1" value={qty} onChange={e=>setQty(e.target.value)}/></label>
     {['NORMAL','STOP_LIMIT'].includes(kind)&&<label>限价（USD）<input aria-label="限价" type="number" step="0.01" min="0" value={limit} onChange={e=>setLimit(e.target.value)}/></label>}
     {['STOP','STOP_LIMIT'].includes(kind)&&<label>触发价（USD）<input aria-label="止损触发价" type="number" step="0.01" value={trigger} onChange={e=>setTrigger(e.target.value)}/></label>}
     {kind.startsWith('TRAILING')&&<><label>移动距离<input aria-label="移动距离" type="number" step="0.01" value={trail} onChange={e=>setTrail(e.target.value)}/></label><label>距离单位<select value={trailType} onChange={e=>setTrailType(e.target.value)}><option value="PERCENTAGE">百分比 %</option><option value="PRICE">美元</option></select></label>{kind==='TRAILING_STOP_LIMIT'&&<label>限价偏移<input aria-label="限价偏移" type="number" step="0.01" value={spread} onChange={e=>setSpread(e.target.value)}/></label>}</>}
    </div><div className="trade-presets">{prefs.quantities.map(n=><button key={n} onClick={()=>setQty(String(n))}>{n} 股</button>)}<button title="管理快捷设置" onClick={()=>setPrefsOpen(true)}><Settings2 size={14}/></button></div>
    <div className="trade-ticket-grid"><label>交易时段<select aria-label="交易时段" value={session} disabled={!!editing||kind!=='NORMAL'||env==='SIMULATE'} onChange={e=>setSession(e.target.value)}><option value="RTH">常规时段 RTH</option><option value="ETH">盘前 + 盘中 + 盘后</option><option value="OVERNIGHT">仅夜盘</option><option value="ALL">24 小时</option></select></label><label>有效期<select aria-label="有效期" value={tif} disabled={!!editing||env==='SIMULATE'} onChange={e=>setTif(e.target.value)}><option value="DAY">当日 DAY</option><option value="GTC">撤销前有效 GTC</option></select></label></div>
    <div className="trade-order-info"><span>{kind==='NORMAL'?'限价金额':'估算金额'}</span><strong>{Number(qty)>0&&Number(limit||quote?.last_price)>0?money(Number(qty)*Number(limit||quote?.last_price)):'—'}</strong></div>
    <div className="trade-buy-sell">{editing?<button className="trade-primary" disabled={busy||!canTrade||blocked} onClick={()=>void order(editing.trd_side)}>预览／提交改单</button>:<><button className="trade-buy" disabled={busy||!canTrade||blocked||!['NORMAL','MARKET'].includes(kind)} onClick={()=>void order('BUY')}><ArrowUpRight size={17}/>买入</button><button className="trade-sell" disabled={busy||!canTrade||blocked} onClick={()=>void order('SELL')}><ArrowDownRight size={17}/>{kind==='NORMAL'||kind==='MARKET'?'卖出':'设置卖出止损'}</button></>}</div>
    <p className="trade-small">{kind==='NORMAL'?'限价单不保证成交。夜盘及全时段只开放限价单。':kind==='MARKET'?'市价单存在滑点；行情快照超过 5 秒时禁止提交。':'止损仅在常规时段使用。止损市价单可能滑点，止损限价单可能不成交。'} 买入不会自动附带止损。</p>
   </section></div>
   <section className="trade-card trade-ledger"><div className="trade-card-title"><div className="trade-tabs" role="tablist" aria-label="交易数据">{[['positions','持仓'],['orders','订单'],['journal','操作流水']].map(([k,n])=><button role="tab" aria-selected={tab===k} className={tab===k?'active':''} key={k} onClick={()=>setTab(k)}>{n}<span>{k==='positions'?snapshot.positions.length:k==='orders'?snapshot.orders.length:journal.length}</span></button>)}</div><small>{snapshot.as_of?'更新于 '+clock(snapshot.as_of):'等待账户数据'}</small></div>
    <div className="trade-table-wrap">{tab==='positions'?<table><thead><tr><th>股票</th><th>持仓 / 可卖</th><th>成本 / 现价</th><th>浮动盈亏</th><th>按现价限价卖出</th><th>设置止损 · 按现价距离</th></tr></thead><tbody>{snapshot.positions.map((p:Row)=><tr key={p.code}><td><strong>{p.code}</strong><small>{p.stock_name}</small></td><td>{p.qty} / {p.can_sell_qty}</td><td>{money(p.cost_price_valid?p.cost_price:null)}<small>{money(p.nominal_price)}</small></td><td className={Number(p.pl_val)>=0?'trade-up':'trade-down'}>{p.pl_val_valid?money(p.pl_val):'—'}</td><td><div className="trade-row-actions">{[.25,.5,1].map(n=><button key={n} disabled={Number(p.can_sell_qty)<1||busy||!canTrade||blocked} onClick={()=>void usePosition(p,n)}>{n===1?'全部':n*100+'%'}</button>)}</div></td><td><div className="trade-row-actions">{prefs.stops.map(n=><button key={n} disabled={env!=='REAL'||!unlocked||busy||blocked||Number(p.can_sell_qty)<1} onClick={()=>void stopPosition(p,n)}>-{n}%</button>)}</div><small>{env==='REAL'?'GTC · 常规时段 · 可卖数量':'模拟环境不开放止损单'}</small></td></tr>)}</tbody></table>:tab==='orders'?<table><thead><tr><th>股票 / 订单号</th><th>方向 / 类型</th><th>数量 / 已成交</th><th>价格 / 触发</th><th>券商状态</th><th>操作</th></tr></thead><tbody>{snapshot.orders.map((o:Row)=><tr key={o.order_id}><td><strong>{o.code}</strong><small>{o.order_id}</small></td><td className={o.trd_side==='BUY'?'trade-up':'trade-down'}>{o.trd_side==='BUY'?'买入':'卖出'}<small>{orderNames[o.order_type]||o.order_type}</small></td><td>{o.qty} / {o.dealt_qty}</td><td>{o.price?money(o.price):'市价'}<small>{o.aux_price?'触发 '+money(o.aux_price):o.trail_value?'跟随 '+o.trail_value:''}</small></td><td>{stateNames[o.order_status]||o.order_status}<small>{o.last_err_msg||''}</small></td><td><div className="trade-row-actions"><button disabled={!activeStates.includes(o.order_status)||busy||!canTrade||blocked||!['NORMAL','STOP','STOP_LIMIT'].includes(o.order_type)} onClick={()=>modify(o)}>修改</button><button disabled={!activeStates.includes(o.order_status)||busy||!canTrade||blocked} onClick={()=>void requestOrder({action:'CANCEL',order_id:o.order_id})}>撤单</button></div></td></tr>)}</tbody></table>:<table><thead><tr><th>时间 / 操作编号</th><th>操作</th><th>结果</th><th>核对</th></tr></thead><tbody>{journal.map(j=><tr key={j.id}><td>{clock(j.created)}<small>{j.id}</small></td><td>{j.payload.code} · {j.kind==='PLACE'?'下单':j.kind==='MODIFY'?'改单':'撤单'}<small>{j.payload.side} · {j.payload.qty} 股</small></td><td className={j.state==='UNKNOWN'?'trade-down':''}>{opNames[j.state]||j.state}<small>{j.result?.message||''}</small></td><td>{['UNKNOWN','SENDING'].includes(j.state)&&<div className="trade-row-actions"><button disabled={busy} onClick={()=>void perform(async()=>{const r=await api('reconcile',{operation_id:j.id});setNotice(r.state==='UNKNOWN'?'券商记录尚未匹配，请在 moomoo 核查；不要重复下单':'已找到券商记录')})}>核对券商</button><button disabled={busy||now-j.created<60} onClick={()=>{const confirmation=prompt(`请先在 moomoo 核对订单。此操作仅解除阻塞，不会重发订单。\n输入：已在moomoo核对 ${j.id}`);if(confirmation)void perform(async()=>{await api('acknowledge',{operation_id:j.id,confirmation});setNotice('已记录人工核对，不会重发原操作')})}}>人工核对</button></div>}</td></tr>)}</tbody></table>}</div>
    {((tab==='positions'&&!snapshot.positions.length)||(tab==='orders'&&!snapshot.orders.length)||(tab==='journal'&&!journal.length))&&<div className="trade-empty">{account?'暂无记录':'选择账户后显示数据'}</div>}
   </section><footer className="trade-footer">券商持仓和订单是最终依据 · 页面关闭后，已接受订单继续有效 · 未提供无人值守策略或 OCO 联动</footer>
  </div>
  {preview&&<div className="trade-modal-backdrop"><section className="trade-modal" role="dialog" aria-modal="true" aria-label="核对订单"><h2>核对{preview.action==='CANCEL'?'撤单':preview.action==='MODIFY'?'改单':'订单'}</h2><div className={`trade-env ${env==='REAL'?'real':'paper'}`}>{env==='REAL'?'实盘 · 真实资金':'模拟交易'} · 尾号 {account.slice(-4)}</div><dl>{[['股票',preview.order.code],['方向',preview.order.side==='BUY'?'买入':'卖出'],['数量',preview.order.qty+' 股'],['类型',orderNames[preview.order.order_type]],['价格',preview.order.price?money(preview.order.price):'按订单类型成交'],['触发价',preview.order.aux_price?money(preview.order.aux_price):'—'],['时段',preview.order.session||'沿用原单'],['有效期',preview.order.time_in_force||'沿用原单']].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl><p className="trade-small">{preview.order.order_type!=='NORMAL'?'止损、市价和移动止损均不保证成交价格。':''} 确认后提交至券商，提交成功不代表已成交。</p><div className="trade-modal-actions"><button onClick={()=>setPreview(null)} disabled={busy}>返回修改</button><button className="trade-primary" disabled={busy||now>=preview.expires} onClick={()=>void perform(()=>execute(preview))}>{now>=preview.expires?'预览已过期':busy?'正在提交…':`确认提交 · ${Math.ceil(preview.expires-now)} 秒`}</button></div></section></div>}
  {unlockOpen&&<div className="trade-modal-backdrop"><form className="trade-modal" role="dialog" aria-modal="true" aria-label="解锁实盘" onSubmit={e=>{e.preventDefault();void perform(async()=>{const password=tradePassword;setTradePassword('');const r=await api('unlock',{acc_id:account,password,confirm:unlockConfirm?'UNLOCK REAL':''});setState({...state,unlock:{acc_id:account,expires:r.expires}});setUnlockOpen(false);setUnlockConfirm(false);setNotice('当前账号已解锁，15 分钟后失效')})}}><h2>解锁实盘交易</h2><p>账号尾号 {account.slice(-4)} · 本次解锁最长 15 分钟</p><label>moomoo 交易密码<input aria-label="moomoo 交易密码" type="password" autoComplete="off" value={tradePassword} onChange={e=>setTradePassword(e.target.value)}/></label><label className="trade-checkbox"><input type="checkbox" checked={unlockConfirm} onChange={e=>setUnlockConfirm(e.target.checked)}/>我确认此账号为实盘，操作将使用真实资金。</label><p className="trade-small">密码仅用于本次解锁，不保存。OpenD 解锁同时影响连接它的其他程序。退出或到期会尝试重新锁定 OpenD。</p><div className="trade-modal-actions"><button type="button" onClick={()=>{setUnlockOpen(false);setTradePassword('')}}>取消</button><button className="trade-primary" disabled={busy||!unlockConfirm||!tradePassword}>解锁实盘</button></div>{error&&<div className="trade-error">{error}</div>}</form></div>}
  {prefsOpen&&<div className="trade-modal-backdrop"><section className="trade-modal" role="dialog" aria-modal="true" aria-label="快捷设置"><h2>快捷设置</h2><label>股数按钮（逗号分隔）<input value={qtyText} onChange={e=>setQtyText(e.target.value)}/></label><label>止损距离 %（逗号分隔）<input value={stopText} onChange={e=>setStopText(e.target.value)}/></label><p className="trade-small">持仓止损按钮以该行现价计算触发价，数量为整股可卖数量。支持常规时段、GTC 止损市价单。</p><div className="trade-modal-actions"><button onClick={()=>setPrefsOpen(false)}>取消</button><button className="trade-primary" disabled={busy} onClick={()=>void savePrefs()}>保存设置</button></div></section></div>}
 </div>;
}
