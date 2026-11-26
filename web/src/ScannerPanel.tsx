import {useEffect,useRef,useState} from 'react';
import {catalog,operators,operand,defaultRule,type Operand,type Rule} from './scanner';
import {tdxCatalog} from './tdxIndicators';
import './scanner.css';
import ScanScopePicker from './ScanScopePicker';
import ScanJobDetails from './ScanJobDetails';
import ScanJobHistory,{JobControls,jobStatusLabels,jobPhaseLabels,formatScanTime} from './ScanJobHistory';
type Group={id:string;name:string;symbols:string[]};
const periods=['1m','5m','15m','30m','60m','120m','240m','1d','1w','1mo'];
const labels:Record<string,string>={main:'数值',REDS:'红灯数',GREENS:'绿灯数',close:'收盘价',open:'开盘价',high:'最高价',low:'最低价',volume:'成交量',average:'平均成交量',macd:'DIF',signal:'DEA',hist:'柱值',upper:'上轨',mid:'中轨',lower:'下轨'};
const periodName=(p:string)=>({'1d':'日线','1w':'周线','1mo':'月线'}[p]||p.replace('m',' 分钟'));
function operandText(o:Operand){
 const base=o.name==='NUMBER'?String(o.value):`${catalog[o.name]?.label.split(' · ')[0]||o.name} · ${labels[o.line]||o.line}`;
 return `${o.offset?`${o.offset}根前的 `:''}${base}${o.scale&&o.scale!==1?` × ${o.scale}`:''}`;
}
function ruleText(r:Rule){
 const mode=r.temporal||'current';
 const timing=r.offset===1?'上一根':r.offset?`${r.offset}根前`:'当前';
 const range=r.max_count===r.min_count?`恰好 ${r.min_count}`:r.max_count?`${r.min_count??1}–${r.max_count}`:`至少 ${r.min_count??1}`;
 const history=mode==='streak'?(r.max_count?`，连续第 ${r.max_count===r.min_count?r.min_count:range} 根`:`，已连续至少 ${r.min_count??1} 根`):mode==='all'?`，最近 ${r.window??1} 根每根满足`:mode==='any'?`，最近 ${r.window??1} 根至少一次`:mode==='count'?`，最近 ${r.window??1} 根满足 ${range} 次`:'';
 const simpleRed=r.left.name==='SIXPULSE'&&r.left.line==='REDS'&&!r.left.offset&&(r.left.scale??1)===1&&r.right.name==='NUMBER'&&r.right.value===6&&(r.right.scale??1)===1&&!r.right.offset&&['eq','reach'].includes(r.op);
 const condition=simpleRed?(r.op==='reach'?'刚变六红':'六红'):`${operandText(r.left)} ${operators[r.op]||r.op} ${operandText(r.right)}`;
 return `${r.period?periodName(r.period)+' · ':''}${timing}：${condition}${history}`;
}
async function api(path:string,method='GET',body?:unknown,signal?:AbortSignal){const r=await fetch('/api/scanner/'+path,{method,signal,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:JSON.stringify(v.detail));return v}
function availableInMarket(name:string,market:'CN'|'US'){
 return !tdxCatalog[name]?.market||tdxCatalog[name].market===market;
}
function OperandEditor({value,onChange,market,label}:{value:Operand;onChange:(v:Operand)=>void;market:'CN'|'US';label:string}){
  return <div className="scan-operand">
    <label>{label}<select aria-label={label} value={value.name} onChange={e=>onChange(operand(e.target.value))}>{Object.entries(catalog).filter(([key])=>availableInMarket(key,market)).map(([key,item])=><option key={key} value={key}>{item.label}</option>)}</select></label>
    {value.name==='NUMBER'?<label className="scan-threshold">比较数值<input aria-label="比较数值" type="number" value={value.value} onChange={e=>onChange({...value,value:Number(e.target.value)})}/></label>:<label>输出线<select aria-label="指标输出" value={value.line} onChange={e=>onChange({...value,line:e.target.value})}>{catalog[value.name].lines.map(line=><option key={line} value={line}>{labels[line]||line}</option>)}</select></label>}
    <details className="scan-operand-extra"><summary>历史取值与参数{value.offset?` · ${value.offset}根前`:''}{value.scale!==undefined&&value.scale!==1?` · ×${value.scale}`:''}</summary>
    {value.name!=='NUMBER'&&<label>取值偏移（0＝当前，非比较阈值）<input aria-label="指标偏移" type="number" min="0" max="250" value={value.offset??0} onChange={e=>onChange({...value,offset:Number(e.target.value)})}/></label>}
    <label>输出倍数<input aria-label="输出倍数" type="number" step="0.1" value={value.scale??1} onChange={e=>onChange({...value,scale:Number(e.target.value)})}/></label>
    {Object.entries(value.params).map(([key,n])=><label key={key}>{key}<input aria-label={key} type="number" min="1" max="500" value={n} onChange={e=>onChange({...value,params:{...value.params,[key]:Number(e.target.value)}})}/></label>)}
    </details>
  </div>;
}
function ruleHint(r:Rule){
 const hints:Record<string,string>={rise_eq:'前一根 < 阈值，本根 = 阈值；阈值为 3 时，仅从下方升到 3，2→4 不算。',fall_eq:'前一根 > 阈值，本根 = 阈值；阈值为 3 时，仅从上方降到 3，4→2 不算。',cross_above:'前一根 ≤ 阈值，本根 > 阈值；2→3 不算超过 3，3→4 才算。',cross_below:'前一根 ≥ 阈值，本根 < 阈值；4→3 不算小于 3，3→2 才算。',reach:'前一根 < 阈值，本根 ≥ 阈值；阈值为 3 时，2→3、2→4 都算。',fall:'前一根 > 阈值，本根 ≤ 阈值；阈值为 3 时，4→3、4→2 都算。',enter_eq:'前一根 ≠ 阈值，本根 = 阈值；阈值为 3 时，2→3、4→3 算，3→3 不算。',eq:'只判断相等，可持续满足，不要求刚发生变化。',lt:'只判断当前小于，可持续满足，不要求刚发生变化。',lte:'只判断当前小于等于，可持续满足，不要求刚发生变化。',gt:'只判断当前大于，可持续满足，不要求刚发生变化。',gte:'只判断当前大于等于，可持续满足，不要求刚发生变化。'};
 const six=r.left.name==='SIXPULSE'&&['REDS','GREENS'].includes(r.left.line)&&!r.left.offset&&(r.left.scale??1)===1&&r.right.name==='NUMBER'&&(r.right.scale??1)===1;
 const allowed=six&&['lt','lte','eq','gt','gte'].includes(r.op)?Array.from({length:7},(_,v)=>v).filter(v=>({lt:v<r.right.value,lte:v<=r.right.value,eq:v===r.right.value,gt:v>r.right.value,gte:v>=r.right.value}[r.op])):null;
 return (hints[r.op]||'')+(allowed?` 当前允许的${labels[r.left.line]}：${allowed.length?allowed.join('、'):'无'}。`:'');
}
function checkText(c:any,r:Rule|undefined,i:number){
 const n=(v:any)=>typeof v==='number'?String(Number(v.toFixed(3))):'—';
 if(!r)return `${i+1}: ${n(c.left)} / ${n(c.right)}`;
 const symbols:Record<string,string>={gt:'>',gte:'≥',lt:'<',lte:'≤',eq:'=',cross_above:'>',cross_below:'<',reach:'≥',fall:'≤',enter_eq:'=',rise_eq:'=',fall_eq:'='};
 const change=['cross_above','cross_below','reach','fall','enter_eq','rise_eq','fall_eq'].includes(r.op);
 const date=(v:any)=>v?new Date(v*1000).toLocaleString():'';
 return `${r.name||'条件 '+(i+1)}：${operandText(r.left)} ${n(c.left)} ${symbols[r.op]||r.op} ${r.right.name==='NUMBER'?'':operandText(r.right)+' '}${n(c.right)}${change?`；前一根 ${n(c.previous_left)}（比较值 ${n(c.previous_right)}）`:''}；${c.ok?'满足':'不满足'}${c.left_time?`；取值 ${date(c.left_time)}`:''}${c.streak!==undefined?`；连续${c.streak_exact?'':'至少'}${c.streak}根`:''}${c.count!==undefined?`；${c.window}根中${c.count}次`:''}`;
}
function HistoryEditor({rule:r,onChange}:{rule:Rule;onChange:(r:Rule)=>void}){
 const mode=r.temporal||'current';
 return <div className="scan-controls scan-history"><label>条件在几根前结束<input aria-label="条件偏移" type="number" min="0" max="250" value={r.offset??0} onChange={e=>onChange({...r,offset:Number(e.target.value)})}/></label>
 <label>满足方式<select aria-label="满足方式" value={mode} onChange={e=>onChange({...r,temporal:e.target.value})}><option value="current">该根满足（可持续）</option><option value="streak">连续满足第几根</option><option value="all">窗口内每根满足</option><option value="any">窗口内至少一根满足</option><option value="count">窗口内满足次数</option></select></label>
 {['all','any','count'].includes(mode)&&<label>窗口根数<input type="number" min="1" max="250" value={r.window??1} onChange={e=>onChange({...r,window:Number(e.target.value)})}/></label>}
 {['streak','count'].includes(mode)&&<><label>{mode==='streak'?'连续至少几根':'至少几次'}<input type="number" min="1" max="250" value={r.min_count??1} onChange={e=>onChange({...r,min_count:Number(e.target.value)})}/></label><label>最多（留空不限）<input type="number" min="1" max="250" value={r.max_count??''} onChange={e=>onChange({...r,max_count:e.target.value===''?null:Number(e.target.value)})}/></label></>}
 </div>
}
export default function ScannerPanel({market,groups:inputGroups,savedGroups,onOpen,initialScope,names={}}:{market:'US'|'CN';groups:Group[];savedGroups:string;onOpen:(symbol:string,period:string)=>void;onClose:()=>void;initialScope?:string;names?:Record<string,string>}){
 const marketName=market==='US'?'美股':'沪深 A 股';
 const belongs=(symbol:string)=>market==='US'?symbol.startsWith('US.'):symbol.startsWith('SH.')||symbol.startsWith('SZ.');
 const groups=inputGroups.map(g=>({...g,symbols:g.symbols.filter(belongs)}));
 const [rules,setRules]=useState<Rule[]>([defaultRule()]),[join,setJoin]=useState('all'),[selected,setSelected]=useState(['1d']);
 const [scope,setScope]=useState(initialScope?'groups':'all'),[chosen,setChosen]=useState<string[]>(initialScope?[initialScope]:[]),[explicit,setExplicit]=useState('');
 const [lookback,setLookback]=useState(1),[live,setLive]=useState(true),[name,setName]=useState('刚变六红'),[id,setId]=useState('');
 const [plans,setPlans]=useState<any[]>([]),[monitors,setMonitors]=useState<any[]>([]),[job,setJob]=useState<any>(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
 const [history,setHistory]=useState<any[]>([]);
 const [historyCursor,setHistoryCursor]=useState<string|null>(null),[nextHistoryCursor,setNextHistoryCursor]=useState<string|null>(null);
 const actionBusy=useRef(false),pendingRun=useRef<{key:string;id:string}|null>(null);
 const [advanced,setAdvanced]=useState(false),[preset,setPreset]=useState('reach');
 const [preview,setPreview]=useState<{key:string;rows:any[];loading:boolean;error:string}>({key:'',rows:[],loading:true,error:''});
 const [previewQuery,setPreviewQuery]=useState('');
 const [previewAttempt,setPreviewAttempt]=useState(0);
 const resultsRef=useRef<HTMLElement|null>(null);
 useEffect(()=>{if(job?.id)resultsRef.current?.scrollIntoView({behavior:'smooth',block:'start'})},[job?.id]);
 const [eventMode,setEventMode]=useState('on_enter');
 const [interval,setIntervalValue]=useState(120),[follow,setFollow]=useState(true),[tradingOnly,setTradingOnly]=useState(true),[backfill,setBackfill]=useState(false);
 const refresh=async()=>{
  const [plansResponse,monitorsResponse,jobsResponse]=await Promise.all([api('plans'),api('monitors'),api('jobs?limit=50'+(historyCursor?'&cursor='+encodeURIComponent(historyCursor):''))]);
  setPlans(plansResponse.items);setMonitors(monitorsResponse.items);
  const visible=jobsResponse.items.filter((item:any)=>!item.market||item.market===market);
  setHistory(visible);setNextHistoryCursor(jobsResponse.next_cursor||null);return visible;
 };
 const action=async(fn:()=>Promise<void>)=>{
  if(actionBusy.current)return;
  actionBusy.current=true;setBusy(true);
  try{await fn()}catch(e){setMessage(String(e instanceof Error?e.message:e))}
  finally{actionBusy.current=false;setBusy(false)}
 };
 useEffect(()=>{
  let active=true;
  void refresh().then(items=>{
   const latest=items.find((item:any)=>['queued','running','pausing','paused','cancelling'].includes(item.status))||items[0];
   if(latest)api('jobs/'+latest.id).then(value=>{if(active)setJob(value)}).catch(e=>{if(active)setMessage(e.message)});
  }).catch(e=>setMessage(e.message));
  return()=>{active=false};
 },[historyCursor]);
 useEffect(()=>{
  let active=true;
  const timer=window.setInterval(()=>{
   if(job&&['queued','running','pausing','cancelling'].includes(job.status)){
    api('jobs/'+job.id).then(value=>{if(active)setJob(value)}).catch(e=>{if(active)setMessage(e.message)});
   }
   void refresh().catch(()=>{});
  },2500);
  return()=>{active=false;clearInterval(timer)};
 },[job?.id,job?.status,historyCursor]);
 const controlJob=(ident:string,operation:'pause'|'resume'|'cancel')=>void action(async()=>{
  const changed=await api('jobs/'+ident+'/'+operation,'POST');
  if(job?.id===ident)setJob(changed);
  setMessage(changed.status==='pausing'?'正在暂停，当前数据请求结束后停止。':changed.status==='cancelling'?'正在取消，当前数据请求结束后停止。':jobStatusLabels[changed.status]||changed.status);
  await refresh();
 });
 async function startScan(force=false){
  const key=JSON.stringify({plan:body(),force,groups:groups.map(group=>({id:group.id,symbols:group.symbols}))});
  if(pendingRun.current?.key!==key)pendingRun.current={key,id:crypto.getRandomValues(new Uint32Array(4)).join('-')};
  const saved=await save();
  const submitted=await api('plans/'+saved.id+'/run','POST',{request_id:pendingRun.current.id,force});
  pendingRun.current=null;setJob(submitted);
  setMessage(submitted.reused?(submitted.reuse_reason==='fresh_result'?'已复用已有结果；需要更新行情时点击“重新扫描”。':'已找到相同任务，继续跟踪原任务。'):'后台任务已创建，可查看进度、暂停或取消。');
  await refresh();
 }

 function body(){
  let target:any={kind:scope};
  if(scope==='groups'){
   const transient=groups.filter(g=>chosen.includes(g.id)&&g.id.startsWith('radar-selection-'));
   target=transient.length?{kind:'symbols',symbols:[...new Set(groups.filter(g=>chosen.includes(g.id)).flatMap(g=>g.symbols))]}:{kind:'groups',groups:chosen};
  }
  if(['symbols','members','sectors'].includes(scope))target={kind:scope==='sectors'?'symbols':scope,symbols:explicit.split(/[,，\s]+/).filter(Boolean).map(s=>s.toUpperCase()),...(scope==='sectors'?{selection:'sectors'}:{})};
  target.market=market;
  return {name,rules,join,periods:selected,lookback,live,scope:target};
 }
 async function save(copy=false){
  const saved=await api('plans'+(id&&!copy?'/'+id:''),id&&!copy?'PUT':'POST',body());
  setId(saved.id);setPlans(old=>old.some(item=>item.id===saved.id)?old.map(item=>item.id===saved.id?saved:item):[saved,...old]);
  setMessage('方案已保存到 NAS · 版本 '+saved.version);return saved;
 }

 function load(p:any){
  const old=!p.scope?.market;setPreset('custom');setId(old?'':p.id);setName(p.name);setRules(p.rules);setJoin(p.join);setSelected(p.periods);setLookback(p.lookback);setLive(p.live??true);
  setScope(p.scope.selection==='sectors'?'sectors':p.scope.kind);setChosen((p.scope.groups||[]).filter((g:string)=>g.startsWith(market+':')));setExplicit((p.scope.symbols||[]).filter(belongs).join(','));
  if(old)setMessage(`已按${marketName}载入旧方案副本，原方案和监控不变。`);
 }
 const scopeKey=JSON.stringify(body().scope);
 const previewKey=JSON.stringify([scopeKey,['all','groups','favorites'].includes(scope)?savedGroups:'',previewAttempt]);
 useEffect(()=>{
  const controller=new AbortController(),target=JSON.parse(scopeKey);
  const empty=target.kind==='groups'&&!target.groups?.length||['symbols','members'].includes(target.kind)&&!target.symbols?.length;
  setPreview({key:previewKey,rows:[],loading:!empty,error:''});
  if(empty)return()=>controller.abort();
  const timer=window.setTimeout(()=>{api('scope-preview','POST',target,controller.signal).then(v=>{if(!controller.signal.aborted)setPreview({key:previewKey,rows:v.rows,loading:false,error:''})}).catch(e=>{if(!controller.signal.aborted)setPreview({key:previewKey,rows:[],loading:false,error:e.message})})},250);
  return()=>{controller.abort();clearTimeout(timer)};
 },[scopeKey,previewKey]);
 const waitingForScope=preview.loading||preview.key!==previewKey;
 const scopeGroups=groups.filter(group=>scope==='all'||scope==='groups'&&chosen.includes(group.id)||scope==='favorites'&&group.id.endsWith(':radar-favorites'));
 const scopeReady=['all','groups','favorites'].includes(scope)?scopeGroups.some(group=>group.symbols.length>0):explicit.split(/[,，\s]+/).some(Boolean);
 const planReady=scopeReady&&rules.length>0&&selected.length>0;
 const planMarket=(p:any)=>{
  if(p?.scope?.market)return p.scope.market;
  const codes=p?.scope?.symbols||[],ids=p?.scope?.groups||[];
  if(codes.length&&codes.every((c:string)=>c.startsWith('US.'))||ids.length&&ids.every((c:string)=>c.startsWith('US:')))return 'US';
  if(codes.length&&codes.every((c:string)=>c.startsWith('SH.')||c.startsWith('SZ.'))||ids.length&&ids.every((c:string)=>c.startsWith('CN:')))return 'CN';
  return 'mixed';
 };
 const currentMonitors=monitors.filter(m=>planMarket(m.plan)===market),legacyMonitors=monitors.filter(m=>planMarket(m.plan)==='mixed');
 const formulaPresets:Record<string,string>={YAOGU_BUY:'买入',YAOGU_START:'启动',YAOGU_TRACK:'追踪',CHIEF_RESONANCE:'共振',HAOYUNLAI_WAVE:'转强确认'};
 function template(kind:string){
   setPreset(kind);
   const red=():Rule=>({...defaultRule(),op:'eq'});
   setId('');setJoin('all');
   const formulaLine=formulaPresets[kind];
   if(formulaLine){
    setRules([{left:{...operand(kind),line:formulaLine},op:'eq',right:{...operand('NUMBER'),value:1}}]);
    setName(kind==='CHIEF_RESONANCE'?'主力共振':catalog[kind].label);

    const period=tdxCatalog[kind]?.period;
    if(period){setSelected([period]);setLookback(1)}
   }
   if(kind==='reach'){setRules([defaultRule()]);setName('刚变六红')}
   if(kind==='green3'||kind==='green3plus'){setRules([{name:kind==='green3'?'刚变三绿':'刚达到至少三绿',left:{...operand('SIXPULSE'),line:'GREENS'},op:kind==='green3'?'enter_eq':'reach',right:{...operand('NUMBER'),value:3}}]);setName(kind==='green3'?'刚变三绿（恰好三个）':'刚达到至少三绿')}
   if(kind==='state'){setRules([red()]);setName('当前六红（持续满足）')}
   if(kind==='streak'){setRules([{...red(),temporal:'streak',min_count:2,max_count:3}]);setName('连续六红第 2–3 根')}
   if(kind==='return'){const green=operand('SIXPULSE');green.line='GREENS';setRules([red(),{left:green,op:'gte',right:{...operand('NUMBER'),value:3},offset:1,temporal:'streak',min_count:1,max_count:1},{...red(),offset:2,temporal:'streak',min_count:3,max_count:null}]);setName('六红至少 3 根 → 三绿 1 根 → 六红')}
   setMessage('已填入可编辑条件，尚未保存；已有监控不变。');
 }
 const rows=(job?.results||[]).filter((r:any)=>r.status==='matched'&&r.match&&r.valid!==false&&belongs(r.symbol));
 const visiblePlans=plans.filter(p=>!p.scope?.market||p.scope.market===market);
 const running=job&&['queued','running','pausing','cancelling'].includes(job.status);
 const statusLabel=jobStatusLabels;
 return <section className="scanner-panel scan-simple" aria-label="条件扫描器">
 <header><div><h2>{marketName}条件扫描</h2><p>点选你的关注分组或板块，结果只列出命中。</p></div><label className="scan-saved">我的方案<select aria-label="已保存方案" value={id} onChange={e=>{const p=plans.find(p=>p.id===e.target.value);if(p)load(p);else{setId('');setPreset('custom')}}}><option value="">新方案</option>{visiblePlans.map(p=><option key={p.id} value={p.id}>{p.name}{!p.scope?.market?'（旧方案副本）':''}</option>)}</select></label></header>
 <fieldset disabled={busy}>
 <div className="scan-market-switch" aria-label="当前扫描市场"><strong>{marketName}</strong><span>跟随左侧市场 · 仅扫描{marketName}标的</span></div>
 <ScanScopePicker market={market} groups={groups} scope={scope} setScope={setScope} chosen={chosen} setChosen={setChosen} explicit={explicit} setExplicit={setExplicit}/>
 <div className="scan-scope-preview" aria-live="polite">{waitingForScope?<p>正在读取实际扫描名单…</p>:preview.error?<><p role="alert">{preview.error}</p><button type="button" onClick={()=>setPreviewAttempt(n=>n+1)}>重试读取名单</button></>:!preview.rows.length?<p>请先选择含标的的分组、板块，或输入标的代码。</p>:<details><summary>将扫描 <strong>{preview.rows.length}</strong> 个{marketName}标的 · 查看名单</summary><input aria-label="搜索扫描名单" placeholder="搜索名称或代码" value={previewQuery} onChange={e=>setPreviewQuery(e.target.value)}/><div className="scan-preview-list">{preview.rows.filter(r=>(r.name+' '+r.symbol).toLowerCase().includes(previewQuery.toLowerCase())).map(r=><div key={r.symbol}><span>{names[r.symbol]||r.name}</span><small>{r.symbol} · {r.groups.join('、')}</small></div>)}</div></details>}</div>
 <div className="scan-basics scan-condition-basics">
 <label><span>想找什么</span><select aria-label="常用条件" value={preset} onChange={e=>{if(e.target.value==='custom'){setPreset('custom');setAdvanced(true)}else template(e.target.value)}}><option value="reach">刚变六红</option><option value="green3">刚变三绿（恰好三个）</option><option value="green3plus">刚达到至少三绿</option><option value="state">现在是六红</option><option value="streak">六红第 2–3 根</option><option value="return">短暂三绿后恢复六红</option>{Object.keys(formulaPresets).filter(k=>availableInMarket(k,market)).map(k=><option key={k} value={k}>{k==='HAOYUNLAI_WAVE'?'好运来 · 转强确认':catalog[k].label.split(' · ')[0]}</option>)}<option value="custom">自定义条件 / 已保存方案</option></select></label>
 <label><span>看哪个周期</span><select aria-label="扫描周期" value={selected.length===1?selected[0]:'multi'} onChange={e=>{if(e.target.value==='multi')setAdvanced(true);else setSelected([e.target.value])}}>{periods.map(p=><option key={p} value={p}>{periodName(p)}</option>)}<option value="multi">选择多个周期…</option></select></label></div>
 <div className="scan-summary"><strong>当前条件{rules.length>1?` · ${join==='all'?'全部满足':'任一满足'}`:''}</strong><ul>{rules.map((r,i)=><li key={i}>{r.name&&<strong>{r.name}： </strong>}{ruleText(r)}<small>{ruleHint(r)}</small></li>)}</ul><small>{selected.map(periodName).join('、')||'尚未选择周期'} · {live?'盘中预览':'收盘确认'} · {lookback===1?'只看最新一根':`最近 ${lookback} 根内命中`}</small></div>
 <details className="scan-fold scan-custom" open={advanced} onToggle={e=>setAdvanced(e.currentTarget.open)}><summary>编辑条件与更多设置 <span>指标、参数、历史组合、多周期</span></summary><div onChange={()=>setPreset('custom')}>
 <p>每个条件都能改。日线的一根代表一个交易日；“刚达到”看变化，“等于”可持续满足。</p>
 <div className="scan-controls"><label>条件组合<select value={join} onChange={e=>setJoin(e.target.value)}><option value="all">全部满足</option><option value="any">任一满足</option></select></label><label>最近几根内命中<input type="number" min="1" max="50" value={lookback} onChange={e=>setLookback(Number(e.target.value))}/></label><label><input type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)}/>包含盘中预览</label></div>
 <div className="scan-periods">{periods.map(p=><label key={p}><input type="checkbox" checked={selected.includes(p)} onChange={e=>setSelected(v=>e.target.checked?[...v,p]:v.filter(x=>x!==p))}/>{periodName(p)}</label>)}</div>
 {rules.map((r,i)=><div className="scan-rule" key={i}>
  <label className="scan-rule-name">条件 {i+1} 名称<input aria-label="条件名称" maxLength={100} placeholder="例如：绿灯刚降到三以下" value={r.name||''} onChange={e=>setRules(v=>v.map((x,j)=>j===i?{...x,name:e.target.value}:x))}/></label>
  <div className="scan-rule-settings">
   <label>条件周期<select aria-label="条件周期" value={r.period||''} onChange={e=>setRules(v=>v.map((x,j)=>j===i?{...x,period:e.target.value||undefined}:x))}><option value="">跟随决策周期</option>{periods.map(p=><option key={p} value={p}>{periodName(p)}</option>)}</select></label>
   <label>比较方式<select aria-label="比较方式" value={r.op} onChange={e=>setRules(v=>v.map((x,j)=>j===i?{...x,op:e.target.value}:x))}>{Object.entries(operators).map(([op,label])=><option key={op} value={op}>{label}</option>)}</select></label>
  </div>
  <div className="scan-rule-operands">
   <OperandEditor label="左侧指标" market={market} value={r.left} onChange={left=>setRules(v=>v.map((x,j)=>j===i?{...x,left}:x))}/>
   <OperandEditor label="比较目标" market={market} value={r.right} onChange={right=>setRules(v=>v.map((x,j)=>j===i?{...x,right}:x))}/>
  </div>
  <p className="scan-rule-hint">{ruleHint(r)}</p>
  <HistoryEditor rule={r} onChange={rule=>setRules(v=>v.map((x,j)=>j===i?rule:x))}/>
  <div className="scan-rule-actions"><button disabled={rules.length>=12} onClick={()=>setRules(v=>[...v,structuredClone(r)])}>复制条件</button><button onClick={()=>setRules(v=>v.filter((_,j)=>j!==i))}>删除</button></div>
 </div>)}
 <button disabled={rules.length>=12} onClick={()=>{setPreset('custom');setRules(v=>[...v,defaultRule()])}}>添加条件</button></div></details>
 <div className="scan-start"><button className="scan-primary" disabled={!planReady} onClick={()=>void action(()=>startScan())}>开始扫描</button><button disabled={!scopeReady||busy} onClick={()=>void action(()=>startScan(true))}>重新扫描</button><span>{waitingForScope?'正在核对扫描名单…':!scopeReady?'请先确认上方的扫描名单。':!rules.length?'请添加至少一个条件。':!selected.length?'请至少选择一个周期。':'由 NAS 执行，关掉页面也能继续。'}</span></div>
 <details className="scan-fold" open><summary>保存这套条件</summary><label>方案名称<input value={name} onChange={e=>setName(e.target.value)}/></label> <div className="scan-actions"><button onClick={()=>void action(async()=>{await save()})}>保存方案</button><button onClick={()=>void action(async()=>{await save(true)})}>另存副本</button><button disabled={!id} onClick={()=>void action(async()=>{await api('plans/'+id,'DELETE');setId('');await refresh()})}>删除方案</button></div>
</details>
 <details className="scan-fold"><summary>自动盯盘 <span>让 NAS 持续扫描这套条件</span></summary> <p>第二、第三根都要通知时，选择“每根满足的 K 线各一次”。编辑方案不自动修改已有监控；新建监控会固定本次保存的版本。</p><div className="scan-controls"><label>事件生成<select value={eventMode} onChange={e=>setEventMode(e.target.value)}><option value="on_enter">从不满足变为满足时</option><option value="each_bar">每根满足的 K 线各一次</option></select></label><label>扫描间隔（秒）<input type="number" min="30" value={interval} onChange={e=>setIntervalValue(Number(e.target.value))}/></label><label><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>跟随关注列表变更</label><label><input type="checkbox" checked={tradingOnly} onChange={e=>setTradingOnly(e.target.checked)}/>仅交易时段及收盘后确认</label><label><input type="checkbox" checked={backfill} onChange={e=>setBackfill(e.target.checked)}/>回填最近 50 根历史事件</label><button disabled={!planReady} onClick={()=>void action(async()=>{const p=await save();await api('monitors','POST',{plan_id:p.id,name,interval_seconds:interval,follow_watchlists:follow,trading_only:tradingOnly,backfill,event_mode:eventMode});setMessage('监控已启动，默认仅记录启用后的新信号');await refresh()})}>创建并启动监控</button></div></details></fieldset>

 <p role="status">{message}</p>
 {job&&<section ref={resultsRef} className="scan-results" aria-label="扫描命中结果">
  <header><div><h3>{marketName} · 命中 {rows.length} 个</h3><p>{job.plan?.name} · {statusLabel[job.status]||job.status} · {job.total?'已检查 '+job.done+' / '+job.total:'尚未读取名单'}{job.failures?.length?' · '+job.failures.length+' 个暂无法判断':''}</p></div><JobControls job={job} busy={busy} onControl={controlJob}/></header>
  <div className="scan-job-progress">
   <div><strong>{job.queue_position?'排队第 '+job.queue_position+' 位':jobPhaseLabels[job.phase]||statusLabel[job.status]}</strong><span>{job.current_symbol} {job.current_period?periodName(job.current_period):''}</span><span>{job.progress_percent!=null?job.progress_percent+'%':''}</span></div>
   <progress aria-label="扫描进度" value={job.done||0} max={job.total||1}/>
   <dl><div><dt>创建</dt><dd>{formatScanTime(job.created)}</dd></div><div><dt>开始</dt><dd>{formatScanTime(job.started)}</dd></div><div><dt>完成</dt><dd>{formatScanTime(job.finished)}</dd></div><div><dt>扫描模式</dt><dd>{job.plan?.live?'包含未收线 K 线':'仅收线 K 线'}</dd></div></dl>
   <small className="scan-job-id">任务 {job.id} · {job.source==='monitor'||job.monitor_id?'定时监控':job.source==='browser'?'页面提交':job.source==='api'?'API 提交':'历史任务'}</small>
   {!!job.controls?.length&&<details><summary>任务操作记录</summary>{job.controls.map((entry:any,index:number)=><p key={index}>{entry.action==='pause'?'暂停':entry.action==='resume'?'继续':'取消'} · {formatScanTime(entry.time)}</p>)}</details>}
  </div>
  <ScanJobDetails job={job}/>
  {rows.length>0?<div className="scan-table"><table><thead><tr><th>名称 / 代码</th><th>周期 / 所属分组</th><th>触发时间</th><th>命中条件</th></tr></thead><tbody>{rows.map((r:any)=><tr key={r.symbol+r.period}><td><button onClick={()=>onOpen(r.symbol,r.period)}>{names[r.symbol]||r.name||r.symbol}</button><small>{r.symbol}</small></td><td>{periodName(r.period)}<small>{r.groups?.join('、')}</small></td><td>{new Date(r.time*1000).toLocaleString()}<small>{r.confirmed?'收盘确认':'盘中预览'}</small></td><td>{(r.checks||[]).map((c:any,i:number)=><div className="scan-check" key={i}>{checkText(c,job.plan?.rules?.[i],i)}</div>)}</td></tr>)}</tbody></table></div>:<div className="scan-result-empty">{running?'任务尚未完成，命中结果会陆续显示。':job.status==='paused'?'任务已暂停，点击“继续任务”完成剩余标的。':job.status==='cancelled'?'扫描已取消，已完成部分没有命中。':job.status==='failed'||job.status==='interrupted'?'本次扫描未正常完成，请查看下方原因。':job.failures?.length?'已完成部分暂无命中；另有标的数据异常。':'本次没有找到符合条件的标的。'}</div>}
  {job.error&&<p role="alert">{job.error}</p>}
  {job.failures?.length>0&&<details className="scan-failures"><summary>{job.failures.length} 项未能判断 · 查看失败原因</summary>{job.failures.map((r:any)=><p key={r.symbol+r.period}>{r.symbol} · {periodName(r.period)}{r.detected_at?' · '+formatScanTime(r.detected_at):''}：{r.error}</p>)}</details>}
  {job.retry_of&&<p>重试来源任务：{job.retry_of}</p>}
  {['partial','failed'].includes(job.status)&&<button disabled={busy} onClick={()=>void action(async()=>{setJob(await api('jobs/'+job.id+'/retry','POST'));await refresh()})}>按当前行情重试未完成项</button>}
 </section>}
 <ScanJobHistory jobs={history} selectedId={job?.id} busy={busy} hasMore={!!nextHistoryCursor} isOlder={!!historyCursor} onOlder={()=>setHistoryCursor(nextHistoryCursor)} onLatest={()=>setHistoryCursor(null)} onSelect={ident=>void action(async()=>setJob(await api('jobs/'+ident)))} onControl={controlJob}/>
 <details className="scan-fold"><summary>我的后台监控 · {currentMonitors.filter(m=>m.enabled).length} 个运行中{currentMonitors.some(m=>m.last_error)&&" · 有任务需要检查"}</summary>{currentMonitors.map(m=><div className="scan-controls" key={m.id}><strong>{m.name}</strong><span>v{m.plan_version} · {m.event_mode==='each_bar'?'每根命中一次':'进入条件时一次'} · {m.enabled?'运行':'暂停'} · {m.last_status||'等待首次扫描'} · {m.last_error||''}</span><span>{m.last_run?'上次 '+new Date(m.last_run*1000).toLocaleString():''}</span><button onClick={()=>void action(async()=>{await api('monitors/'+m.id+'/'+(m.enabled?'pause':'start'),'POST');await refresh()})}>{m.enabled?'暂停':'启动'}</button></div>)}
 </details>
 {legacyMonitors.length>0&&<details className="scan-fold"><summary>旧的跨市场监控 · {legacyMonitors.length} 个</summary><p>这些既有任务按原方案扫描两个市场，与上面的{marketName}扫描分开。可暂停后分别创建 A 股、美股监控。</p>{legacyMonitors.map(m=><div className="scan-controls" key={m.id}><strong>{m.name}</strong><span>{m.enabled?'运行中':'已暂停'} · 跨市场{m.last_error?' · '+m.last_error:''}</span><button onClick={()=>void action(async()=>{await api('monitors/'+m.id+'/'+(m.enabled?'pause':'start'),'POST');await refresh()})}>{m.enabled?'暂停':'启动'}</button></div>)}</details>}
 </section>;
}
