import{lazy,Suspense,useEffect,useMemo,useRef,useState}from'react';
import{createRoot}from'react-dom/client';
import{createPortal}from'react-dom';
import{trendExtension,drawingTimeCoordinate}from'./TrendExtensions';
import{drawingTimeAtX,moveTrendEndpoint,hitTestTrendEndpoint,type TimeSample}from'./trendGeometry';
import type{PointerEvent as ReactPointerEvent}from'react';
import{backfillHistory,marketDateWindow}from'./historyTools';
import{createChart,CandlestickSeries,HistogramSeries,LineSeries,TickMarkType,type IChartApi,type ISeriesApi,type Time,type UTCTimestamp}from'lightweight-charts';
import{Activity,Plus,Settings2,Trash2,Save,LayoutGrid,Wifi,WifiOff,RotateCw,Minus}from'lucide-react';
import{type Bar,type Indicator,compute,indicatorPane}from'./indicators';
import{formula}from'./formula';
import './style.css';
import TradeTerminal from './TradeTerminal';
import {secureChart,setChartCsrf} from './secureChart';
import DepthPanel,{type DepthLevel} from './DepthPanel';
import CachePanel from './CachePanel';
import StockSearch from './StockSearch';
import {resetChartViewport,resetPriceScales,markViewportReady} from './chartViewport';
import SettingsPanel,{type SettingsTab} from './SettingsPanel';
import IndicatorParameters,{indicatorLabels,indicatorDefaults} from './IndicatorParameters';
import {visibleExtremeLabels} from './VisibleExtremes';
import {sessionBackground} from './SessionBackground';
import {macdHistogramColor,volumeColor,selectedColor,indicatorDefaultColor} from './histogramColors';
import IndicatorAppearance from './IndicatorAppearance';
import DrawingsPanel from './DrawingsPanel';
import {fibPrices,drawingStyle,normalizeDrawingRecords,drawingsForPeriod,updateDrawingRecords,newDrawingId,hitTestDrawing,type FibDrawing,type HorizontalDrawing,type TrendDrawing,type DrawingSelection} from './drawingTools';
const StrategyPanel=lazy(()=>import('./StrategyPanel'));
type Mode='all'|'extended'|'regular';type Period='1m'|'5m'|'15m'|'30m'|'60m'|'1d'|'1w'|'1mo';
type Tile={symbol:string;period:Period};
type StockQuote={symbol:string;name:string;price:number|null;change_percent:number|null;pre_price:number|null;pre_change_percent:number|null;after_price:number|null;after_change_percent:number|null;overnight_price:number|null;overnight_change_percent:number|null;update_time:string};
const percent=(value:number|null)=>value===null?'—':`${value>0?'+':''}${value.toFixed(2)}%`;
const priceText=(value:number|null,market:'US'|'CN')=>value===null?'—':`${market==='US'?'$':'¥'}${value.toFixed(2)}`;
const mergeBars=(older:Bar[],newer:Bar[])=>[...new Map([...older,...newer].map(bar=>[bar.time,bar])).values()].sort((a,b)=>a.time-b.time);
type TrendPoint={time:number;price:number};
const periods:Period[]=['1m','5m','15m','30m','60m','1d','1w','1mo'];
const isLongPeriod=(p:string)=>['1d','1w','1mo'].includes(p);
const periodLabel=(p:string)=>({ '1d':'日线','1w':'周线','1mo':'月线'} as Record<string,string>)[p]||p;
const names=['EMA','SMA','VWAP','BBI','BOLL','ATR','MACD','DMI','RSI','VOLUME'];
const chartSlots=[0,1,2,3];
const pythonExample='fast = EMA(C, PARAMS["fast"])\nslow = EMA(C, PARAMS["slow"])\nmacd = fast - slow\nsignal = EMA(macd, PARAMS["signal"])\nresult = {"MACD": macd, "Signal": signal, "Histogram": macd - signal}';
const appliesTo=(indicator:Indicator,index:number,period:Period)=>indicator.visible&&
  (!Array.isArray(indicator.charts)||indicator.charts.includes(index))&&
  (!Array.isArray(indicator.periods)||indicator.periods.includes(period));

function IndicatorScope({indicator,onChange}:{indicator:Indicator;onChange:(patch:Partial<Indicator>)=>void}){
  const charts=Array.isArray(indicator.charts)?indicator.charts:chartSlots;
  const selectedPeriods=Array.isArray(indicator.periods)?indicator.periods:periods;
  const toggleChart=(index:number)=>onChange({charts:charts.includes(index)?charts.filter(x=>x!==index):chartSlots.filter(x=>x===index||charts.includes(x))});
  const togglePeriod=(period:Period)=>onChange({periods:selectedPeriods.includes(period)?selectedPeriods.filter(x=>x!==period):periods.filter(x=>x===period||selectedPeriods.includes(x))});
  return <div className="indicator-scope">
    <div className="scope-line"><span>适用图</span><div className="scope-chips"><button type="button" className={charts.length===4?'chosen':''} onClick={()=>onChange({charts:[...chartSlots]})}>全部</button>{chartSlots.map(i=><button type="button" key={i} aria-label={`${indicator.title||indicator.name} 图 ${i+1}`} aria-pressed={charts.includes(i)} className={charts.includes(i)?'chosen':''} onClick={()=>toggleChart(i)}>图 {i+1}</button>)}</div></div>
    <div className="scope-line"><span>周期</span><div className="scope-chips"><button type="button" className={selectedPeriods.length===periods.length?'chosen':''} onClick={()=>onChange({periods:[...periods]})}>全部</button>{periods.map(period=><button type="button" key={period} aria-label={`${indicator.title||indicator.name} ${period}`} aria-pressed={selectedPeriods.includes(period)} className={selectedPeriods.includes(period)?'chosen':''} onClick={()=>togglePeriod(period)}>{periodLabel(period)}</button>)}</div></div>
  </div>;
}

function IndicatorSettings({indicator,onPatch,onDelete}:{indicator:Indicator;onPatch:(patch:Partial<Indicator>)=>void;onDelete:()=>void}){
  const [newInputName,setNewInputName]=useState(''),[validationError,setValidationError]=useState('');
  let settings:any={code:'',inputs:{}};
  if(indicator.name==='PYTHON')try{settings=JSON.parse(indicator.params)}catch{}
  const pythonCode=String(settings.code||''),pythonInputs:Record<string,number>=settings.inputs&&typeof settings.inputs==='object'?settings.inputs:{};
  const patchPython=(next:any)=>onPatch({params:JSON.stringify({...settings,...next})});
  useEffect(()=>{if(indicator.name!=='PYTHON')return;
    let cancelled=false;const timer=window.setTimeout(async()=>{
      try{const r=await fetch('/api/python-indicator/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:pythonCode,inputs:pythonInputs})});const data=await r.json();if(!cancelled)setValidationError(r.ok?'':data.detail||'Python 代码检查失败')}
      catch(e){if(!cancelled)setValidationError(String(e))}
    },500);
    return()=>{cancelled=true;clearTimeout(timer)};
  },[indicator.name,indicator.params]);
  const addInput=()=>{const name=newInputName.trim();if(!/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(name)||name in pythonInputs){setValidationError('参数名须以字母开头，且不能重复');return}patchPython({inputs:{...pythonInputs,[name]:1}});setNewInputName('')};
  return <div className="indicator-card">
    <div className="indicator-row"><label><input type="checkbox" checked={indicator.visible} onChange={e=>onPatch({visible:e.target.checked})}/><strong>{indicator.title||indicator.name}</strong></label>{indicator.name==='PYTHON'?<span className="indicator-language">Python</span>:<span className="indicator-language">{indicatorLabels[indicator.name]?.split(' · ')[1]||indicator.name}</span>}<button className="icon-button" title={`删除 ${indicator.title||indicator.name}`} onClick={onDelete}><Trash2 size={15}/></button></div>
    {indicator.name==='PYTHON'&&<><textarea className="python-code" aria-label={`${indicator.title||indicator.name} Python 代码`} value={pythonCode} spellCheck={false} onChange={e=>patchPython({code:e.target.value})}/><div className="python-inputs"><strong>可调参数</strong>{Object.entries(pythonInputs).map(([name,value])=><label key={`${name}:${value}`}>{name}<input aria-label={`${indicator.title||indicator.name} ${name}`} type="number" step="any" defaultValue={value} onBlur={e=>{const next=Number(e.target.value);if(!e.target.value||!Number.isFinite(next)){e.target.value=String(value);setValidationError(`${name} 须为数字`);return}patchPython({inputs:{...pythonInputs,[name]:next}})}}/><button title={`删除参数 ${name}`} onClick={()=>{const inputs={...pythonInputs};delete inputs[name];patchPython({inputs})}}>×</button></label>)}<div className="python-add-input"><input aria-label="新增参数名" placeholder="新增参数名" value={newInputName} onChange={e=>setNewInputName(e.target.value)} onKeyDown={e=>e.key==='Enter'&&addInput()}/><button onClick={addInput}>添加参数</button></div><small>代码中用 PARAMS["fast"] 读取参数；修改数值后离开输入框即生效。</small></div>{validationError&&<div className="side-error">{validationError}</div>}</>}
    {indicator.name!=='PYTHON'&&<IndicatorParameters indicator={indicator} onChange={params=>onPatch({params})}/>}
    <label className="indicator-pane-control">绘制位置<select aria-label={`${indicator.title||indicator.name} 绘制位置`} value={indicatorPane(indicator)} onChange={e=>onPatch({pane:e.target.value as 'main'|'separate'})}><option value="main">主图叠加</option><option value="separate">独立副图</option></select><span className="indicator-pane-badge">{indicatorPane(indicator)==='main'?'主图指标':'副图指标'}</span></label>
    <IndicatorAppearance indicator={indicator} onChange={onPatch}/>
    <details className="indicator-scope-details"><summary>适用图与周期</summary><IndicatorScope indicator={indicator} onChange={onPatch}/></details>
  </div>;
}
const toTime=(n:number)=>n as UTCTimestamp;
const etClock=new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const etDay=new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',month:'2-digit',day:'2-digit'});
const etFull=new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const cnClock=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const cnDay=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'});
const cnFull=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const chartGroup=new Map<number,{chart:IChartApi;candle:ISeriesApi<'Candlestick'>;ready:boolean;suppressSyncUntil:number}>();
let syncingCharts=false;
function ChartPane({drawingHost,index,tile,mode,indicators,active,onActivate,drawings,onDraw:commitHorizontal,trends,onTrend:commitTrends,fibos,onFibos:commitFibos,drawingsHidden,onDrawingsHidden,version,stockName,depthSettingsOpen,settingsHost}:{drawingHost:HTMLDivElement|null;index:number;tile:Tile;mode:Mode;indicators:Indicator[];active:boolean;onActivate:()=>void;drawings:HorizontalDrawing[];onDraw:(v:HorizontalDrawing[])=>void;trends:TrendDrawing[];onTrend:(v:TrendDrawing[])=>void;fibos:FibDrawing[];onFibos:(v:FibDrawing[])=>void;drawingsHidden:boolean;onDrawingsHidden:(value:boolean)=>void;version:number;stockName?:string;depthSettingsOpen:boolean;settingsHost:HTMLDivElement|null}){
 const [depthLines,setDepthLines]=useState<DepthLevel[]>([]),[depthStatus,setDepthStatus]=useState({enabled:false,ready:false}),[depthToggle,setDepthToggle]=useState(0);
 const [drawingIssue,setDrawingIssue]=useState('');
 const acceptDrawingRows=(rows:{id?:string;timeframeScope?:'current'|'all'}[])=>{if(rows.filter(row=>!row.id?.startsWith('@')||row.timeframeScope!=='all').length>100){setDrawingIssue('当前周期该类型画线已达 100 个，请先删除部分对象');return false}setDrawingIssue('');return true};
 const onDraw=(rows:HorizontalDrawing[])=>{if(acceptDrawingRows(rows))commitHorizontal(rows)};
 const onTrend=(rows:TrendDrawing[])=>{if(acceptDrawingRows(rows))commitTrends(rows)};
 const onFibos=(rows:FibDrawing[])=>{if(acceptDrawingRows(rows))commitFibos(rows)};

 const [dateTarget,setDateTarget]=useState(''),[historyNotice,setHistoryNotice]=useState('');
 const [showExtremes,setShowExtremes]=useState(()=>{try{return localStorage.getItem('chart-visible-extremes')!=='off'}catch{return true}});

 const updateViewport=useRef<(range:any)=>void>(()=>{});
 const box=useRef<HTMLDivElement>(null),chartRef=useRef<IChartApi|null>(null),candleRef=useRef<ISeriesApi<'Candlestick'>|null>(null),fittedKey=useRef('');
 type DragState={id:string;index:number;pointerId:number;original:TrendDrawing;draft:TrendDrawing;samples:TimeSample[];step:number;spacing:number;scroll:any;scale:any;autoScale:boolean;start:{x:number;y:number};moved:boolean};
 const trendVisuals=useRef(new Map<string,ReturnType<typeof trendExtension>>()),dragState=useRef<DragState|null>(null),cancelDrag=useRef<()=>void>(()=>{}),suppressDrawingClick=useRef(0);
 const [draggingTrend,setDraggingTrend]=useState(false),[hoveredHandle,setHoveredHandle]=useState(false);
 const [drawingUndo,setDrawingUndo]=useState<{horizontal:HorizontalDrawing[];trends:TrendDrawing[];fibos:FibDrawing[];hidden:boolean}|null>(null);
 const [selectedDrawing,setSelectedDrawing]=useState<DrawingSelection|null>(null),[hoveredDrawing,setHoveredDrawing]=useState<DrawingSelection|null>(null),[editorRequest,setEditorRequest]=useState(0);
 const drawingHover=useRef<(p:any)=>void>(()=>{});
 const drawingLabel=(selection:DrawingSelection)=>{const items=selection.kind==='horizontal'?drawings:selection.kind==='trend'?trends:fibos;return `${({horizontal:'水平线',trend:'趋势线',fib:'斐波那契'})[selection.kind]} ${items.findIndex(v=>v.id===selection.id)+1}`};
 const record=()=>setDrawingUndo({horizontal:drawings,trends,fibos,hidden:drawingsHidden});
 const saveHorizontal=(v:HorizontalDrawing[])=>{record();onDraw(v)};const saveTrends=(v:TrendDrawing[])=>{record();onTrend(v)};const saveFibos=(v:FibDrawing[])=>{record();onFibos(v)};
 const toggleAllDrawings=(hidden:boolean)=>{record();onDrawingsHidden(hidden);if(hidden)setSelectedDrawing(null)};
 const deleteSelectedDrawing=()=>{if(!selectedDrawing)return;const {kind,id}=selectedDrawing;if(kind==='horizontal')saveHorizontal(drawings.filter(v=>v.id!==id));else if(kind==='trend')saveTrends(trends.filter(v=>v.id!==id));else saveFibos(fibos.filter(v=>v.id!==id));setSelectedDrawing(null)};
 const [bars,setBars]=useState<Bar[]>([]),[loadedKey,setLoadedKey]=useState(''),[error,setError]=useState(''),[formulaError,setFormulaError]=useState(''),[stale,setStale]=useState(false),[live,setLive]=useState(false),[draw,setDraw]=useState<'off'|'horizontal'|'trend'|'fib'>('off'),[trendStart,setTrendStart]=useState<TrendPoint|null>(null);
 const [pythonResults,setPythonResults]=useState<Record<string,{time:number[];values:Record<string,(number|null)[]>}>>({}),[pythonError,setPythonError]=useState('');
 const lastPythonRun=useRef({key:'',time:0});
 const [historyCursor,setHistoryCursor]=useState<number|null>(null),[hasMore,setHasMore]=useState(true),[loadingOlder,setLoadingOlder]=useState(false),[historyError,setHistoryError]=useState('');
 const historicView=useRef(false);
 const historyInteraction=useRef(false),olderBusy=useRef(false),liveRef=useRef(false),pendingHistoryJump=useRef<{from:number;to:number}|null>(null);
 const key=`${tile.symbol}:${tile.period}:${mode}`;
 const currentKey=useRef(key);currentKey.current=key;const historyGeneration=useRef(0);
 const activeIndicators=useMemo(()=>indicators.filter(ind=>appliesTo(ind,index,tile.period)),[indicators,index,tile.period]);
 const isUS=tile.symbol.startsWith('US.');
 const chartName=!isUS&&stockName&&/[\u3400-\u9fff]/.test(stockName)?stockName:tile.symbol.replace('US.','');
 const displayTime=isUS?{clock:etClock,day:etDay,full:etFull}:{clock:cnClock,day:cnDay,full:cnFull};
 useEffect(()=>{let stop=false,ws:WebSocket|null=null,timer:number|undefined,initialized=false,openedOnce=false,retryDelay=5000;
  const group=chartGroup.get(index);if(group&&loadedKey!==key){group.ready=false;group.suppressSyncUntil=Infinity}pendingHistoryJump.current=null;
  historyGeneration.current++;historicView.current=false;historyInteraction.current=false;olderBusy.current=false;setLoadingOlder(false);setHistoryCursor(null);setHasMore(true);setHistoryError('');
  const load=async(force=false)=>{try{const r=await fetch(`/api/bars?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}${force?'&refresh=true':''}`);const data=await r.json();if(!r.ok)throw Error(data.detail);if(!stop&&!historicView.current){const wasInitialized=initialized;initialized=true;setBars(old=>wasInitialized?mergeBars(old,data.bars):data.bars);if(!wasInitialized)setHistoryCursor(data.bars[0]?.time||null);setLoadedKey(key);setStale(data.stale);setError(data.error||'')}}catch(e){if(!stop)setError(String(e))}};
  const open=()=>{if(stop)return;ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/${secureChart?'market/':''}stream?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}`);ws.onopen=()=>{setLive(false);liveRef.current=false};ws.onmessage=e=>{if(stop||currentKey.current!==key)return;const msg=JSON.parse(e.data);if(msg.type==='status'&&msg.connected){setLive(true);liveRef.current=true;retryDelay=5000;if(openedOnce)load(true);openedOnce=true}if(msg.type==='heartbeat'){setLive(!!msg.connected);liveRef.current=!!msg.connected}if(msg.type==='bar'&&!historicView.current)setBars(old=>mergeBars(old,[msg.bar]));if(msg.type==='error'){setError(msg.message);setLive(false);liveRef.current=false;if(msg.code==='permission_denied'){retryDelay=300000;setStale(true)}}};ws.onclose=()=>{setLive(false);liveRef.current=false;if(!stop)timer=window.setTimeout(open,retryDelay)}};
  const returnLive=(event:Event)=>{if((event as CustomEvent).detail!==index)return;historyGeneration.current++;historyInteraction.current=false;olderBusy.current=false;setLoadingOlder(false);initialized=false;historicView.current=false;pendingHistoryJump.current=null;fittedKey.current='';setHasMore(true);setHistoryError('');load(true)};window.addEventListener('market-return-live',returnLive);
  load(version>0).then(open);
  const poll=window.setInterval(()=>{if(document.visibilityState==='visible'&&(isLongPeriod(tile.period)||!liveRef.current))load(true)},300000);
  return()=>{window.removeEventListener('market-return-live',returnLive);historyGeneration.current++;stop=true;clearTimeout(timer);clearInterval(poll);ws?.close()}
 },[key,version]);
 const requestOlder=async(jumpToOlder=false,target?:{from:number;to:number})=>{
  if(olderBusy.current||historyCursor===null||loadedKey!==key)return;
  if(!hasMore&&target===undefined)return;
  olderBusy.current=true;setLoadingOlder(true);setHistoryError('');setHistoryNotice('');
  const requestKey=key,requestGeneration=historyGeneration.current;const stopped=()=>currentKey.current!==requestKey||historyGeneration.current!==requestGeneration;
  try{
   const result=await backfillHistory({before:historyCursor,target:target?.to,stopped,
    fetchPage:async before=>{const r=await fetch(`/api/bars/older?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}&before=${before}`);const data=await r.json();if(!r.ok)throw Error(data.detail||'加载历史 K 线失败');return data},
    onPage:data=>{if(data.bars.length){if(jumpToOlder&&target===undefined){pendingHistoryJump.current={from:data.bars[0].time,to:historyCursor};historyInteraction.current=false}setBars(old=>mergeBars(old,data.bars))}setHistoryCursor(data.next_before);setHasMore(Boolean(data.has_more));}
   });
   if(result.cancelled)return;
   setHistoryCursor(result.before);setHasMore(result.hasMore);
   if(target!==undefined){if(result.before<=target.to)pendingHistoryJump.current=target;setHistoryNotice(result.before>target.to?'已到行情可获取或缓存保留范围；目标日期尚未覆盖':'已定位目标日期');setBars(old=>[...old]);}
  }catch(e){if(!stopped())setHistoryError(String(e))}finally{if(!stopped()){olderBusy.current=false;setLoadingOlder(false)}}
 };
 const jumpToDate=async()=>{
  const target=marketDateWindow(dateTarget,isUS);if(!target||olderBusy.current||loadedKey!==key)return;
  const requestKey=key,generation=historyGeneration.current;const stopped=()=>currentKey.current!==requestKey||generation!==historyGeneration.current;
  historyInteraction.current=false;olderBusy.current=true;setLoadingOlder(true);setHistoryError('');setHistoryNotice('正在读取目标日期…');
  try{const start=target.from-7*86400,end=Math.min(target.to+86400,Math.floor(Date.now()/1000));
   const response=await fetch(`/api/bars/window?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}&start=${start}&end=${end}`);const data=await response.json();if(!response.ok)throw Error(data.detail||'目标日期加载失败');if(stopped())return;
   if(!data.bars.length){setHistoryNotice('该日期附近没有行情：可能为休市、未上市或数据源不提供');return}
   // Keep a contiguous window: merging a distant date into today's bars hides the unrequested gap.
   historicView.current=true;pendingHistoryJump.current=target;setHistoryCursor(data.bars[0].time);setHasMore(true);setBars(data.bars);setHistoryNotice('已载入目标日期；点击实时可回到最新行情');
  }catch(e){if(!stopped())setHistoryError(String(e))}finally{if(!stopped()){olderBusy.current=false;setLoadingOlder(false)}}
 };

 useEffect(()=>{const chart=chartRef.current;if(!chart)return;
  const onRange=(range:any)=>{if(historyInteraction.current&&!historyError&&range&&range.from<35&&hasMore&&!loadingOlder&&historyCursor!==null)void requestOlder()};
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
  // Recheck after each batch, including empty weekends; no new gesture is required.
  const timer=window.setTimeout(()=>onRange(chart.timeScale().getVisibleLogicalRange()),250);
  return()=>{clearTimeout(timer);chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange)};
 },[key,historyCursor,hasMore,loadingOlder,loadedKey,historyError]);
 const filtered=useMemo(()=>bars.filter(x=>mode==='all'||x.session!=='overnight').filter(x=>mode!=='regular'||x.session==='regular'),[bars,mode]);
 updateViewport.current=()=>{};
 useEffect(()=>{const candle=candleRef.current;if(!candle||!isUS||isLongPeriod(tile.period)||mode==='regular')return;const primitive=sessionBackground(filtered);candle.attachPrimitive(primitive);return()=>{if(candleRef.current===candle)candle.detachPrimitive(primitive)}},[filtered,key,isUS,mode,tile.period]);
 useEffect(()=>{const candle=candleRef.current;if(!candle||!showExtremes)return;const primitive=visibleExtremeLabels(filtered);candle.attachPrimitive(primitive);return()=>{if(candleRef.current===candle)candle.detachPrimitive(primitive)}},[showExtremes,filtered,key]);
const barTimes=useMemo(()=>filtered.map(b=>b.time),[filtered]);
 const drawingStep=({'1m':60,'5m':300,'15m':900,'30m':1800,'60m':3600,'1d':86400,'1w':604800,'1mo':2592000} as Record<Period,number>)[tile.period];
 const timeToDrawingX=(time:number)=>chartRef.current?drawingTimeCoordinate(chartRef.current,time,barTimes,drawingStep):null;
 const pythonIndicators=useMemo(()=>activeIndicators.filter(ind=>ind.name==='PYTHON'),[activeIndicators]);
 const latestPythonBar=filtered.at(-1);
 const pythonFingerprint=latestPythonBar?`${filtered.length}:${latestPythonBar.time}:${latestPythonBar.high}:${latestPythonBar.low}:${latestPythonBar.close}:${latestPythonBar.volume}`:'';
 const pythonCodeKey=pythonIndicators.map(ind=>`${ind.id}:${ind.params}`).join('|');
 useEffect(()=>{
  const runKey=`${key}:${pythonCodeKey}`;
  if(lastPythonRun.current.key!==runKey)lastPythonRun.current={key:runKey,time:0};
  if(!pythonIndicators.length||!filtered.length||loadedKey!==key){setPythonResults({});setPythonError('');return}
  let stopped=false;const controller=new AbortController();
  const delay=Math.max(350,10000-(Date.now()-lastPythonRun.current.time));
  const timer=window.setTimeout(async()=>{
   lastPythonRun.current.time=Date.now();
   const results=await Promise.all(pythonIndicators.map(async ind=>{
    try{
     const settings=JSON.parse(ind.params),code=String(settings.code||''),inputs=settings.inputs||{};
     const response=await fetch('/api/python-indicator',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:tile.symbol,period:tile.period,mode:isLongPeriod(tile.period)?'regular':mode,code,inputs}),signal:controller.signal});
     const data=await response.json();if(!response.ok)throw Error(data.detail||'Python 指标计算失败');
     return {id:ind.id,data};
    }catch(e){return {id:ind.id,error:String(e)}}
   }));
   if(stopped)return;
   setPythonResults(Object.fromEntries(results.filter(x=>'data'in x).map(x=>[x.id,x.data])));
   setPythonError(results.find(x=>'error'in x)?.error||'');
  },delay);
  return()=>{stopped=true;clearTimeout(timer);controller.abort()};
 },[key,loadedKey,pythonIndicators,pythonCodeKey,pythonFingerprint]);
 useEffect(()=>{if(!box.current)return;const chart=createChart(box.current,{autoSize:true,layout:{background:{color:'#0e1624'},textColor:'#9aa9be',fontFamily:'Inter, system-ui, sans-serif',fontSize:11,panes:{separatorColor:'#263449',enableResize:true}},grid:{vertLines:{color:'#1c283a'},horzLines:{color:'#1c283a'}},crosshair:{vertLine:{color:'#6c829d'},horzLine:{color:'#6c829d'}},rightPriceScale:{borderColor:'#263449'},localization:{timeFormatter:(time:Time)=>typeof time==='number'?displayTime.full.format(time*1000):String(time)},timeScale:{borderColor:'#263449',timeVisible:true,secondsVisible:false,tickMarkFormatter:(time:Time,kind:TickMarkType)=>typeof time==='number'?(kind<=TickMarkType.DayOfMonth?displayTime.day.format(time*1000):displayTime.clock.format(time*1000)):null},handleScroll:true,handleScale:true});chartRef.current=chart;const candle=chart.addSeries(CandlestickSeries,{upColor:'#45caa6',downColor:'#ed6b7d',borderVisible:false,wickUpColor:'#45caa6',wickDownColor:'#ed6b7d'});candleRef.current=candle;chartGroup.set(index,{chart,candle,ready:false,suppressSyncUntil:Infinity});
  const cross=(p:any)=>{if(syncingCharts)return;drawingHover.current(p);syncingCharts=true;for(const[id,target]of chartGroup){if(id===index)continue;if(p.time&&p.point){const source=p.seriesData.get(candle) as {close:number}|undefined;target.chart.setCrosshairPosition(source?.close||0,p.time,target.candle)}else target.chart.clearCrosshairPosition()}syncingCharts=false};
  const range=(r:any)=>{updateViewport.current(r);const source=chartGroup.get(index);if(syncingCharts||!r||!source?.ready||!historyInteraction.current||performance.now()<source.suppressSyncUntil)return;syncingCharts=true;try{for(const[id,target]of chartGroup){if(id!==index&&target.ready){target.suppressSyncUntil=performance.now()+350;try{target.chart.timeScale().setVisibleRange(r)}catch{}}}}finally{syncingCharts=false}};
  chart.subscribeCrosshairMove(cross);chart.timeScale().subscribeVisibleTimeRangeChange(range);
  return()=>{chart.unsubscribeCrosshairMove(cross);chart.timeScale().unsubscribeVisibleTimeRangeChange(range);chartGroup.delete(index);chart.remove();chartRef.current=null;candleRef.current=null}},[index]);
 useEffect(()=>{const chart=chartRef.current,candle=candleRef.current;if(!chart||!candle||loadedKey!==key)return;const data=filtered.map(x=>({time:toTime(x.time),open:x.open,high:x.high,low:x.low,close:x.close}));candle.setData(data);const series:ISeriesApi<any>[]=[];const lines:any[]=[];const primitives:ReturnType<typeof trendExtension>[]=[];const sessionPrimitives:{series:ISeriesApi<any>;primitive:ReturnType<typeof sessionBackground>}[]=[];
  if(!drawingsHidden){
   for(const item of drawings){const style=drawingStyle(item,'horizontal');if(!style.visible)continue;const selected=selectedDrawing?.kind==='horizontal'&&selectedDrawing.id===item.id;lines.push(candle.createPriceLine({price:item.price,color:style.color,lineWidth:(selected?Math.min(4,style.lineWidth+2):style.lineWidth) as 1|2|3|4,lineStyle:style.lineStyle,axisLabelVisible:true,title:`${selected?'✓ ':''}水平线 ${drawings.indexOf(item)+1}`}))}
   for(const trend of trends){const style=drawingStyle(trend,'trend');if(!style.visible||trend.points.length!==2)continue;const selected=selectedDrawing?.kind==='trend'&&selectedDrawing.id===trend.id;const shown=dragState.current?.id===trend.id?dragState.current.draft:trend;const primitive=trendExtension(shown,selected,time=>drawingTimeCoordinate(chart,time,barTimes,drawingStep));candle.attachPrimitive(primitive);primitives.push(primitive);trendVisuals.current.set(trend.id,primitive)}
   for(const fib of fibos){const style=drawingStyle(fib,'fib');if(!style.visible)continue;const selected=selectedDrawing?.kind==='fib'&&selectedDrawing.id===fib.id;for(const level of fibPrices(fib))lines.push(candle.createPriceLine({price:level.price,color:level.color,lineWidth:(selected?Math.min(4,style.lineWidth+2):style.lineWidth) as 1|2|3|4,lineStyle:style.lineStyle,axisLabelVisible:[0,.5,.618,1].includes(level.ratio),title:`${selected?'✓ ':''}Fib ${fibos.indexOf(fib)+1} ${(level.ratio*100).toFixed(1)}%`}))}
  }
  let pane=1;let indicatorIssue='';for(const ind of activeIndicators){let values:Record<string,(number|null)[]>;try{
   if(ind.name==='PYTHON'){
    const result=pythonResults[ind.id];if(!result)continue;
    const times=new Map(result.time.map((time,i)=>[time,i]));
    values=Object.fromEntries(Object.entries(result.values).map(([name,row])=>[name,filtered.map(bar=>{const i=times.get(bar.time);return i===undefined?null:row[i]??null})]));
   }else values=compute(filtered,ind.name,ind.params);
  }catch(e){indicatorIssue=`${ind.title||ind.name}: ${String(e)}`;continue}const overlay=indicatorPane(ind)==='main';const target=overlay?0:pane++;
   Object.entries(values).forEach(([label,arr],idx)=>{if(ind.name==='ATR'&&label.startsWith('stop_'))return;const isHist=label==='hist'||label==='volume';const s=chart.addSeries(isHist?HistogramSeries:LineSeries,{color:selectedColor(ind.colors,label,indicatorDefaultColor(ind.name,label,idx)),lineWidth:2,priceFormat:ind.name==='VOLUME'?{type:'volume'}:{type:'price',precision:3,minMove:0.001},lastValueVisible:idx===0,priceLineVisible:false,title:ind.title?`${ind.title} ${label}`:/^(EMA|MA)[0-9]+$/.test(label)?label:label==='main'&&['EMA','SMA'].includes(ind.name)?`${ind.name==='SMA'?'MA':'EMA'}${JSON.parse(ind.params).period||14}`:`${ind.name} ${label}`},target);if(target>0&&idx===0&&isUS&&mode!=='regular'&&!isLongPeriod(tile.period)){const primitive=sessionBackground(filtered);s.attachPrimitive(primitive);sessionPrimitives.push({series:s,primitive})}s.setData(arr.flatMap((value,i)=>value===null||!Number.isFinite(value)?[]:[{time:toTime(filtered[i].time),value,...(ind.name==='MACD'&&label==='hist'?{color:macdHistogramColor(value,arr[i-1],ind.colors)}:ind.name==='VOLUME'&&label==='volume'?{color:volumeColor(filtered[i].open,filtered[i].close,ind.colors)}:{})}]));series.push(s)})
  }
  setFormulaError(indicatorIssue);
  const entry=chartGroup.get(index);if(entry)markViewportReady(entry,data.length>0,performance.now());
  if(data.length&&fittedKey.current!==key){historyInteraction.current=false;if(entry)entry.suppressSyncUntil=performance.now()+350;resetChartViewport(chart,data.length);fittedKey.current=key}
  if(pendingHistoryJump.current){historyInteraction.current=false;if(entry)entry.suppressSyncUntil=performance.now()+350;resetPriceScales(chart);const jump=pendingHistoryJump.current;pendingHistoryJump.current=null;chart.timeScale().setVisibleRange({from:toTime(jump.from),to:toTime(jump.to)})}
  return()=>{if(chartRef.current!==chart)return;for(const {series,primitive} of sessionPrimitives)series.detachPrimitive(primitive);for(const primitive of primitives)candle.detachPrimitive(primitive);trendVisuals.current.clear();for(const line of lines)candle.removePriceLine(line);for(const s of series)chart.removeSeries(s)}
 },[filtered,activeIndicators,pythonResults,drawings,trends,fibos,drawingsHidden,selectedDrawing,key,loadedKey]);
 useEffect(()=>{if(!selectedDrawing)return;const rows=selectedDrawing.kind==='horizontal'?drawings:selectedDrawing.kind==='trend'?trends:fibos;if(!rows.some(row=>row.id===selectedDrawing.id))setSelectedDrawing(null)},[drawings,trends,fibos,selectedDrawing]);
 useEffect(()=>{setDrawingIssue('');setDraw('off');setTrendStart(null);setDrawingUndo(null);setSelectedDrawing(null);setHoveredDrawing(null);setDateTarget('');setHistoryNotice('')},[key]);
 useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){cancelDrag.current();setDraw('off');setTrendStart(null);setSelectedDrawing(null);setHoveredDrawing(null)}};window.addEventListener('keydown',escape);return()=>window.removeEventListener('keydown',escape)},[]);
 const findDrawing=(p:any)=>{const candle=candleRef.current,chart=chartRef.current;return !candle||!chart||!p.point||drawingsHidden||(p.paneIndex!==undefined&&p.paneIndex!==0)?null:hitTestDrawing(p.point,drawings,trends,fibos,v=>candle.priceToCoordinate(v),timeToDrawingX)};
 drawingHover.current=(p:any)=>{const next=draw==='off'?findDrawing(p):null;setHoveredDrawing(old=>old?.id===next?.id&&old?.kind===next?.kind?old:next)};
 const drawingClick=useRef<(p:any)=>void>(()=>{}),drawingPointerStart=useRef<{x:number;y:number}|null>(null);
 drawingClick.current=(p:any)=>{
  const candle=candleRef.current,chart=chartRef.current;if(performance.now()<suppressDrawingClick.current||dragState.current||!candle||!chart||!p.point||(p.paneIndex!==undefined&&p.paneIndex!==0))return;
  if(draw==='off'){setSelectedDrawing(findDrawing(p));return}
  if(p.point.x<0||p.point.x>chart.timeScale().width()||p.point.y<0||p.point.y>chart.panes()[0].getHeight())return;
  const price=candle.coordinateToPrice(p.point.y);if(price===null||Number(price)<=0)return;const drawPrice=Number(Number(price).toFixed(Number(price)>=1?2:4));
  if(draw==='horizontal'){record();onDraw([...drawings,{id:newDrawingId(),price:drawPrice,...drawingStyle({},'horizontal')}]);setDraw('off')}
  else{const samples=barTimes.flatMap(time=>{const x=chart.timeScale().timeToCoordinate(toTime(time));return x===null?[]:[{time,x}]});const time=typeof p.time==='number'?p.time:drawingTimeAtX(p.point.x,samples,drawingStep,chart.timeScale().options().barSpacing);if(time===null)return;const point={time,price:drawPrice};if(!trendStart)setTrendStart(point);else if(point.time!==trendStart.time){record();if(draw==='fib')onFibos([...fibos,{id:newDrawingId(),points:[trendStart,point],...drawingStyle({},'fib')}]);else{const id=newDrawingId();onTrend([...trends,{id,points:[trendStart,point],extend:'none' as const,...drawingStyle({},'trend')}]);setSelectedDrawing({kind:'trend',id})}setTrendStart(null);setDraw('off')}}
 };
 useEffect(()=>{const chart=chartRef.current;if(!chart)return;const handler=(p:any)=>drawingClick.current(p);chart.subscribeClick(handler);return()=>chart.unsubscribeClick(handler)},[index]);
 useEffect(()=>{const candle=candleRef.current,chart=chartRef.current;if(!candle)return;const lines=depthLines.map(l=>candle.createPriceLine({price:l.price,color:l.side==='buy'?'#42d4a3':'#ff718b',lineWidth:2,lineStyle:l.cached?2:0,axisLabelVisible:true,title:`${l.cached?'缓存':'当前'}挂${l.side==='buy'?'买':'卖'} ${new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(l.qty)}股`}));return()=>{if(chartRef.current===chart)for(const line of lines)candle.removePriceLine(line)}},[depthLines,key]);
 const stopTrendDrag=(commit:boolean)=>{
  const state=dragState.current;if(!state)return;dragState.current=null;suppressDrawingClick.current=performance.now()+350;
  const chart=chartRef.current;if(chart){chart.applyOptions({handleScroll:state.scroll,handleScale:state.scale});chart.priceScale('right').applyOptions({autoScale:state.autoScale});}
  if(box.current?.hasPointerCapture(state.pointerId))box.current.releasePointerCapture(state.pointerId);
  setDraggingTrend(false);setHoveredHandle(false);
  if(commit&&state.moved&&JSON.stringify(state.draft.points)!==JSON.stringify(state.original.points)){record();onTrend(trends.map(line=>line.id===state.id?{...line,points:state.draft.points}:line))}
  else trendVisuals.current.get(state.id)?.updateDrawing(state.original);
 };
 cancelDrag.current=()=>stopTrendDrag(false);
 useEffect(()=>{const cancel=()=>cancelDrag.current();window.addEventListener('blur',cancel);return()=>{window.removeEventListener('blur',cancel);cancel()}},[]);
 useEffect(()=>()=>cancelDrag.current(),[key]);
 useEffect(()=>{if(drawingsHidden||draw!=='off'||selectedDrawing?.kind!=='trend'||selectedDrawing.id!==dragState.current?.id)cancelDrag.current()},[drawingsHidden,draw,selectedDrawing?.id]);
 const selectedTrend=selectedDrawing?.kind==='trend'?trends.find(v=>v.id===selectedDrawing.id&&v.visible!==false):undefined;
 const pointerPoint=(event:ReactPointerEvent<HTMLDivElement>)=>{const rect=event.currentTarget.getBoundingClientRect();return {x:event.clientX-rect.left,y:event.clientY-rect.top}};
 const startTrendDrag=(event:ReactPointerEvent<HTMLDivElement>)=>{
  if(event.button===0)drawingPointerStart.current={x:event.clientX,y:event.clientY};
  if(event.button!==0||draw!=='off'||drawingsHidden||!selectedTrend||dragState.current)return;
  const chart=chartRef.current,candle=candleRef.current;if(!chart||!candle)return;
  const point=pointerPoint(event),height=chart.panes()[0]?.getHeight()||0,width=chart.timeScale().width();if(point.x<0||point.x>width||point.y<0||point.y>height)return;
  const index=hitTestTrendEndpoint(point,selectedTrend,v=>candle.priceToCoordinate(v),timeToDrawingX);if(index===null)return;
  const samples=barTimes.flatMap(time=>{const x=chart.timeScale().timeToCoordinate(toTime(time));return x===null?[]:[{time,x}]});if(!samples.length)return;
  event.preventDefault();event.stopPropagation();onActivate();historyInteraction.current=false;
  const options=chart.options();dragState.current={id:selectedTrend.id,index,pointerId:event.pointerId,original:selectedTrend,draft:selectedTrend,samples,step:drawingStep,spacing:chart.timeScale().options().barSpacing,scroll:JSON.parse(JSON.stringify(options.handleScroll)),scale:JSON.parse(JSON.stringify(options.handleScale)),autoScale:chart.priceScale('right').options().autoScale,start:point,moved:false};
  chart.applyOptions({handleScroll:false,handleScale:false});chart.priceScale('right').applyOptions({autoScale:false});event.currentTarget.setPointerCapture(event.pointerId);setDraggingTrend(true);
 };
 const moveTrendDrag=(event:ReactPointerEvent<HTMLDivElement>)=>{
  const state=dragState.current,chart=chartRef.current,candle=candleRef.current,point=pointerPoint(event);
  if(!state){setHoveredHandle(Boolean(selectedTrend&&draw==='off'&&!drawingsHidden&&candle&&chart&&point.x>=0&&point.x<=chart.timeScale().width()&&point.y>=0&&point.y<(chart.panes()[0]?.getHeight()||0)&&hitTestTrendEndpoint(point,selectedTrend,v=>candle.priceToCoordinate(v),timeToDrawingX)!==null));return}
  if(event.pointerId!==state.pointerId||!chart||!candle)return;event.preventDefault();event.stopPropagation();
  const x=Math.max(0,Math.min(chart.timeScale().width()-1,point.x)),y=Math.max(0,Math.min((chart.panes()[0]?.getHeight()||1)-1,point.y));
  const time=drawingTimeAtX(x,state.samples,state.step,state.spacing),raw=candle.coordinateToPrice(y);if(time===null||raw===null)return;
  const price=Number(Number(raw).toFixed(Number(raw)>=1?2:4));state.draft=moveTrendEndpoint(state.original,state.index,{time,price});state.moved=state.moved||Math.hypot(point.x-state.start.x,point.y-state.start.y)>2;trendVisuals.current.get(state.id)?.updateDrawing(state.draft);
 };
 const endTrendDrag=(event:ReactPointerEvent<HTMLDivElement>,commit:boolean)=>{if(dragState.current?.pointerId!==event.pointerId)return;event.preventDefault();event.stopPropagation();stopTrendDrag(commit)};
 const createDrawingFromClick=(event:React.MouseEvent<HTMLDivElement>)=>{if(draw==='off')return;event.preventDefault();event.stopPropagation();const start=drawingPointerStart.current;if(start&&Math.hypot(event.clientX-start.x,event.clientY-start.y)>5)return;const rect=event.currentTarget.getBoundingClientRect();drawingClick.current({point:{x:event.clientX-rect.left,y:event.clientY-rect.top},paneIndex:0})};
 const last=filtered.at(-1),previous=filtered.at(-2),change=last&&previous?(last.close-previous.close)/previous.close*100:0;
 const resetView=()=>{const chart=chartRef.current;if(!chart||loadedKey!==key)return;historyInteraction.current=false;const entry=chartGroup.get(index);if(entry)entry.suppressSyncUntil=performance.now()+350;resetChartViewport(chart,filtered.length)};
 const tools=<><div className="chart-tools"><span>{draw!=='off'?(draw==='horizontal'?'在主图选择水平线价格':trendStart?'在主图选择另一横向位置作为终点 · Esc 取消':'在主图选择起点 · Esc 取消'):isUS?(isLongPeriod(tile.period)?'常规时段':mode==='all'?'24H 全时段':mode==='extended'?'盘前 · 常规 · 盘后':'常规时段'):'A 股常规时段'} · {isUS?'美东':'北京'}时间</span><div className="drawing-toolbar" role="toolbar" aria-label="画图工具"><label className="chart-date">日期<input type="date" aria-label="定位日期" value={dateTarget} onChange={e=>setDateTarget(e.target.value)}/></label><button disabled={!dateTarget||loadingOlder} onClick={jumpToDate}>{loadingOlder?'补载中…':'前往'}</button><button onClick={()=>{historicView.current=false;setHistoryNotice('');setDateTarget('');window.dispatchEvent(new CustomEvent('market-return-live',{detail:index}))}}>实时</button><button aria-label="重置视图" title="恢复适量近期 K 线，并自动适配各图价格轴" disabled={loadedKey!==key||!filtered.length} onClick={resetView}>重置视图</button><button aria-pressed={showExtremes} onClick={()=>{const next=!showExtremes;setShowExtremes(next);try{localStorage.setItem('chart-visible-extremes',next?'on':'off')}catch{}}}>区间高低</button>{isUS&&<button aria-label="挂档密集线" aria-pressed={depthStatus.enabled} disabled={!depthStatus.ready} title="点击开关；金额、股数等阈值在右上角设置中调整" onClick={()=>setDepthToggle(n=>n+1)}>挂档密集线{depthStatus.enabled?' · 开':' · 关'}</button>}<button aria-pressed={draw==='off'} onClick={()=>{setDraw('off');setTrendStart(null)}}>选择 / 编辑</button><button aria-pressed={draw==='horizontal'} onClick={()=>{onDrawingsHidden(false);setSelectedDrawing(null);setTrendStart(null);setDraw(draw==='horizontal'?'off':'horizontal')}}>水平线</button><button aria-pressed={draw==='trend'} onClick={()=>{onDrawingsHidden(false);setSelectedDrawing(null);setTrendStart(null);setDraw(draw==='trend'?'off':'trend')}}>趋势线</button><button aria-pressed={draw==='fib'} onClick={()=>{onDrawingsHidden(false);setSelectedDrawing(null);setTrendStart(null);setDraw(draw==='fib'?'off':'fib')}}>斐波那契</button>{draw!=='off'&&<button onClick={()=>{setDraw('off');setTrendStart(null)}}>取消绘制</button>}<button disabled={!drawingUndo} onClick={()=>{if(!drawingUndo)return;onDraw(drawingUndo.horizontal);onTrend(drawingUndo.trends);onFibos(drawingUndo.fibos);onDrawingsHidden(drawingUndo.hidden);setSelectedDrawing(null);setDrawingUndo(null)}}>撤销</button><button aria-pressed={drawingsHidden} title="整体隐藏不改变单个对象的显隐设置" onClick={()=>toggleAllDrawings(!drawingsHidden)}>{drawingsHidden?'全部显示':'全部隐藏'}</button><DrawingsPanel hidden={drawingsHidden} onHidden={toggleAllDrawings} selected={selectedDrawing} onSelect={setSelectedDrawing} editorRequest={editorRequest} horizontal={drawings} trends={trends} fibos={fibos} onHorizontal={saveHorizontal} onTrends={saveTrends} onFibos={saveFibos}/></div></div><div className="drawing-interaction-row">{selectedDrawing?<div className="drawing-selection-actions" role="toolbar" aria-label="选中画线操作"><strong>已选：{drawingLabel(selectedDrawing)}</strong>{selectedDrawing.kind==='trend'&&<span className="trend-drag-help">{draggingTrend?'正在拖动 · 松开保存 · Esc 取消':'拖动两端圆点可调整长度与角度'}</span>}<button onClick={()=>setEditorRequest(n=>n+1)}>编辑样式</button><button aria-label="删除选中画线" onClick={deleteSelectedDrawing}>删除此对象</button><button onClick={()=>setSelectedDrawing(null)}>取消选择</button></div>:<div className="drawing-interaction-help" role="status">{draw!=='off'?(draw==='horizontal'?'绘制水平线：在主图点击目标价格':trendStart?'已选起点，请点击另一横向位置完成绘制 · Esc 取消':'绘制：先点击起点，再点击另一横向位置作为终点 · Esc 取消'):drawingsHidden?'画线已隐藏，点击“全部显示”恢复':hoveredDrawing?`可选：${drawingLabel(hoveredDrawing)} · 点击打开编辑`:'选择模式：靠近自己画的线，出现手形后点击；也可打开“画线管理”'}</div>}</div></>;
 return <div className={`chart-card ${active?'selected':''}`} onMouseDown={onActivate}><div className="chart-head"><div>{active&&<span className="current-chart-tag">当前图</span>}<strong>{chartName}</strong><span className="chart-symbol-code">{tile.symbol}</span><span className="market-tag">{isUS?"美股":`${tile.symbol} · 沪深 A 股`} · {periodLabel(tile.period)}</span>{stale&&<span className="warning">NAS 缓存 · 未同步最新行情</span>}</div><div className="quote"><strong className={change>=0?'up':'down'}>{last?.close.toFixed(2)||'—'}</strong><span className={change>=0?'up':'down'}>{change>=0?'+':''}{change.toFixed(2)}%</span><span title={live?'OpenD 实时订阅成功':'实时行情未连接；可能正在重试或等待权限'}>{live?<Wifi size={14} className="up"/>:<WifiOff size={14} className="down"/>}</span></div></div>{active&&drawingHost&&createPortal(tools,drawingHost)}{isUS&&<DepthPanel symbol={tile.symbol} onLines={setDepthLines} open={depthSettingsOpen} settingsHost={settingsHost} toggleRequest={depthToggle} onStateChange={setDepthStatus}/>}
{(drawingIssue||error||formulaError||pythonError)&&<div className="chart-error">{drawingIssue||error||formulaError||pythonError}</div>}<div className={`chart-canvas ${draw!=='off'?'drawing-mode':hoveredDrawing?'drawing-hit':''} ${draggingTrend?'trend-dragging':hoveredHandle?'trend-handle-hover':''}`} ref={box} onClickCapture={createDrawingFromClick} onPointerDownCapture={startTrendDrag} onPointerMoveCapture={moveTrendDrag} onPointerUpCapture={e=>endTrendDrag(e,true)} onPointerCancelCapture={e=>endTrendDrag(e,false)} onLostPointerCapture={()=>{if(dragState.current)cancelDrag.current()}} onPointerLeave={()=>{setHoveredDrawing(null);setHoveredHandle(false)}} onPointerDown={()=>{historyInteraction.current=true}} onWheel={()=>{historyInteraction.current=true}}/><div className="chart-foot"><span>NAS 缓存 · {filtered.length} 根 K 线{live?' · 实时更新中':''}</span><button className="older-button" disabled={!hasMore||loadingOlder||historyCursor===null} onClick={()=>void requestOlder(true)}>{loadingOlder?'加载中…':hasMore?'← 更早 K 线':'已到历史保留范围'}</button><span>{historyError||historyNotice||`OHLC ${last?`${last.open.toFixed(2)} / ${last.high.toFixed(2)} / ${last.low.toFixed(2)} / ${last.close.toFixed(2)}`:'—'}`}</span></div></div>
}
type Market = 'US' | 'CN';
type WatchGroup = {id:string; name:string; symbols:string[]};
type MarketWorkspace = {
  groups:WatchGroup[]; selectedGroupId:string; layout:number; mode:Mode; tiles:Tile[];
  indicators:Indicator[]; drawings:Record<string,HorizontalDrawing[]>; trends:Record<string,TrendDrawing[]>;fibos:Record<string,FibDrawing[]>;drawingsHidden:Record<string,boolean>;
};
type WorkspaceV2 = {activeMarket:Market; markets:Record<Market,MarketWorkspace>};

const baseIndicators:Indicator[] = [
  {id:'volume',name:'VOLUME',params:'{"period":20}',visible:true},
  {id:'vwap',name:'VWAP',params:'{"reset":"session"}',visible:true},
  {id:'macd',name:'MACD',params:'{"fast":12,"slow":26,"signal":9}',visible:true},
  {id:'bbi',name:'BBI',params:'{"periods":[3,6,12,24]}',visible:true},
];
const freshMarket = (market:Market):MarketWorkspace => ({
  groups:[{id:'featured',name:'精选',symbols:market==='US'?['US.SNDK','US.SNXX','US.SNDQ']:[]}],
  selectedGroupId:'featured',layout:1,mode:market==='US'?'all':'regular',
  tiles:market==='US'?
    [{symbol:'US.SNDK',period:'5m'},{symbol:'US.SNXX',period:'15m'},{symbol:'US.SNDQ',period:'60m'},{symbol:'US.SNDK',period:'1m'}]:
    [{symbol:'SH.600519',period:'5m'},{symbol:'SZ.000001',period:'15m'},{symbol:'SH.600519',period:'60m'},{symbol:'SZ.000001',period:'1m'}],
  indicators:baseIndicators.map(x=>({...x})),drawings:{},trends:{},fibos:{},drawingsHidden:{},
});
const initialV2:WorkspaceV2={activeMarket:'US',markets:{US:freshMarket('US'),CN:freshMarket('CN')}};
const belongs=(symbol:string,market:Market)=>market==='US'?symbol.startsWith('US.'):/^(SH|SZ)\./.test(symbol);

function restoreMarket(raw:any,market:Market):MarketWorkspace {
  const base=freshMarket(market);
  const legacySymbols=Array.isArray(raw?.symbols)?raw.symbols.filter((s:unknown)=>typeof s==='string'&&belongs(s,market)):null;
  const supplied=Array.isArray(raw?.groups)?raw.groups.filter((g:any)=>g&&typeof g.id==='string'&&typeof g.name==='string').map((g:any)=>({
    id:g.id,name:g.id==='featured'?'精选':g.name.slice(0,24),
    symbols:Array.isArray(g.symbols)?[...new Set<string>(g.symbols.filter((s:unknown)=>typeof s==='string'&&belongs(s,market)))]:[],
  })):[];
  const groups:WatchGroup[]=supplied.length?supplied:[{id:'featured',name:'精选',symbols:legacySymbols||base.groups[0].symbols}];
  if(!groups.some(g=>g.id==='featured'))groups.unshift({id:'featured',name:'精选',symbols:legacySymbols||[]});
  const tiles=Array.isArray(raw?.tiles)?raw.tiles.filter((t:any)=>t&&typeof t.symbol==='string'&&belongs(t.symbol,market)&&periods.includes(t.period)).slice(0,4):[];
  return {
    ...base,groups,selectedGroupId:groups.some(g=>g.id===raw?.selectedGroupId)?raw.selectedGroupId:'featured',
    layout:[1,2,4].includes(raw?.layout)?raw.layout:1,
    mode:market==='CN'?'regular':(['all','extended','regular'].includes(raw?.mode)?raw.mode:base.mode),
    tiles:tiles.length?tiles:base.tiles,
    indicators:Array.isArray(raw?.indicators)?raw.indicators.map((ind:Indicator)=>Array.isArray(ind.periods)&&ind.periods.length===6&&['1m','5m','15m','30m','60m','1d'].every(p=>ind.periods!.includes(p))?{...ind,periods:[...periods]}:ind):base.indicators,
    drawings:normalizeDrawingRecords(raw?.drawings,'horizontal'),
    trends:normalizeDrawingRecords(raw?.trends,'trend'),
    fibos:normalizeDrawingRecords(raw?.fibos,'fib'),
    drawingsHidden:raw?.drawingsHidden&&typeof raw.drawingsHidden==='object'?raw.drawingsHidden:{},
  };
}
function restoreWorkspace(raw:any):WorkspaceV2 {
  return {
    activeMarket:raw?.activeMarket==='CN'?'CN':'US',
    markets:{US:restoreMarket(raw?.markets?.US||raw,'US'),CN:restoreMarket(raw?.markets?.CN,'CN')},
  };
}

function mergeRemoteDrawings(current:WorkspaceV2,raw:any):WorkspaceV2{
 if(!raw?.markets)return current;
 const markets={...current.markets};
 for(const market of ['US','CN'] as Market[]){const value=raw.markets[market];if(!value)continue;markets[market]={...markets[market],drawings:normalizeDrawingRecords(value.drawings,'horizontal'),trends:normalizeDrawingRecords(value.trends,'trend'),fibos:normalizeDrawingRecords(value.fibos,'fib'),drawingsHidden:value.drawingsHidden||{}}}
 return {...current,markets};
}
function App({onSessionEnd}:{onSessionEnd?:()=>void}={}){
  const [showStrategies,setShowStrategies]=useState(new URLSearchParams(location.search).get('strategy')==='1');
  const [manageGroups,setManageGroups]=useState(false);
  const groupRail=useRef<HTMLDivElement>(null);
  const [tradeDock,setTradeDock]=useState(secureChart&&new URLSearchParams(location.search).has('symbol'));
  const [dockProduct,setDockProduct]=useState<'stocks'|'options'>(new URLSearchParams(location.search).get('intent')==='options'?'options':'stocks');
  const [dockSymbol,setDockSymbol]=useState(new URLSearchParams(location.search).get('symbol')||'US.SNDK');
  const [settingsTab,setSettingsTab]=useState<SettingsTab|null>(null),[settingsHost,setSettingsHost]=useState<HTMLDivElement|null>(null);
 const [drawingHost,setDrawingHost]=useState<HTMLDivElement|null>(null);
 const [watchCollapsed,setWatchCollapsed]=useState(()=>{try{return localStorage.getItem('chart-watch-collapsed')==='yes'}catch{return false}});
 const toggleWatch=()=>{if(matchMedia('(max-width:700px)').matches){setMobileWatchOpen(v=>!v);return}setWatchCollapsed(v=>{try{localStorage.setItem('chart-watch-collapsed',v?'no':'yes')}catch{}return !v})};
  const [mobileWatchOpen,setMobileWatchOpen]=useState(false);
  const [stockNames,setStockNames]=useState<Record<string,string>>({});
  const [tradingUrl,setTradingUrl]=useState(`https://${location.hostname}:8443/trade`);
  useEffect(()=>{fetch('/api/trading-config').then(r=>r.json()).then(c=>{if(c.url?.startsWith('https://'))setTradingUrl(c.url)}).catch(()=>{})},[]);
  const openTrading=(symbol:string,action='overview')=>{if(secureChart){if(action==='strategy')setShowStrategies(v=>!v);else{setDockSymbol(symbol);setDockProduct(action==='options'?'options':'stocks');setTradeDock(true)}return}const url=new URL(tradingUrl);url.pathname='/chart';url.searchParams.set('symbol',symbol);url.searchParams.set('intent',action);if(action==='strategy')url.searchParams.set('strategy','1');location.assign(url.toString())};
  const [state,setState]=useState<WorkspaceV2>(initialV2),[ready,setReady]=useState(false),[active,setActive]=useState(0);
  const drawingRevision=useRef(0),currentWorkspace=useRef(state),lastSavedWorkspace=useRef(''),workspaceSaving=useRef(false),saveQueue=useRef(Promise.resolve()),syncMounted=useRef(true);
 currentWorkspace.current=state;
 const [drawingSyncNotice,setDrawingSyncNotice]=useState(''),[workspaceRetry,setWorkspaceRetry]=useState(0);const saveRetryCount=useRef(0),saveRetryTimer=useRef<number|undefined>(undefined);
 useEffect(()=>()=>{syncMounted.current=false;clearTimeout(saveRetryTimer.current)},[]);
 const [newSymbol,setNewSymbol]=useState(''),[symbolError,setSymbolError]=useState('');
  const [newGroupName,setNewGroupName]=useState(''),[groupError,setGroupError]=useState('');
  const [importingGroups,setImportingGroups]=useState(false),[importMessage,setImportMessage]=useState('');
  const [editingGroup,setEditingGroup]=useState(''),[groupDraft,setGroupDraft]=useState('');
  const [newIndicator,setNewIndicator]=useState('EMA'),[newIndicatorPane,setNewIndicatorPane]=useState<'main'|'separate'>('main'),[refresh,setRefresh]=useState(0),[status,setStatus]=useState<any>({});
  const [templates,setTemplates]=useState<Record<string,Indicator[]>>({}),[templateName,setTemplateName]=useState('');
  const [customName,setCustomName]=useState(''),[customFormula,setCustomFormula]=useState('EMA(C,12)-EMA(C,26)'),[customInputs,setCustomInputs]=useState('{"fast":12,"slow":26,"signal":9}'),[customLanguage,setCustomLanguage]=useState<'formula'|'python'>('formula'),[customPane,setCustomPane]=useState<'main'|'separate'>('separate'),[customError,setCustomError]=useState('');
  const [quotes,setQuotes]=useState<Record<string,StockQuote>>({}),[quotesStale,setQuotesStale]=useState(false),[quoteError,setQuoteError]=useState('');
  const market=state.activeMarket,ws=state.markets[market];
  const lastExtendedMode=useRef<Mode>('all');if(market==='US'&&ws.mode!=='regular')lastExtendedMode.current=ws.mode;
  const selectedGroup=ws.groups.find(g=>g.id===ws.selectedGroupId)||ws.groups[0];
  const featured=ws.groups.find(g=>g.id==='featured')!;
  const current=ws.tiles[active]||ws.tiles[0];
  const drawingViews=useMemo(()=>ws.tiles.map(tile=>({horizontal:drawingsForPeriod(ws.drawings,tile.symbol,tile.period),trends:drawingsForPeriod(ws.trends,tile.symbol,tile.period),fibos:drawingsForPeriod(ws.fibos,tile.symbol,tile.period)})),[ws.drawings,ws.trends,ws.fibos,ws.tiles]);
  const quoteSymbols=selectedGroup.symbols.join(',');
  useEffect(()=>{if(!ready||market!=='CN'||!quoteSymbols)return;let stopped=false;const chunks=selectedGroup.symbols.reduce<string[][]>((all,s,i)=>{if(i%100===0)all.push([]);all[all.length-1].push(s);return all},[]);Promise.all(chunks.map(chunk=>fetch('/api/symbols/names?symbols='+encodeURIComponent(chunk.join(','))).then(r=>r.json()))).then(rows=>{if(!stopped)setStockNames(old=>({...old,...Object.assign({},...rows.map(r=>r.names||{}))}))}).catch(()=>{});return()=>{stopped=true}},[ready,market,quoteSymbols]);

  useEffect(()=>{
    setQuotes({});setQuotesStale(false);setQuoteError('');
    if(!ready||!quoteSymbols)return;
    let cancelled=false;
    const load=()=>{
      if(document.visibilityState!=='visible')return;
      const chunks=selectedGroup.symbols.reduce<string[][]>((all,s,i)=>{if(i%100===0)all.push([]);all[all.length-1].push(s);return all},[]);
      Promise.all(chunks.map(async chunk=>{
        const r=await fetch(`/api/quotes?symbols=${encodeURIComponent(chunk.join(','))}`);
        if(!r.ok)throw Error((await r.json()).detail||'快照不可用');
        return r.json();
      }))
        .then(data=>{if(!cancelled){setQuotes(Object.fromEntries(data.flatMap(x=>x.quotes as StockQuote[]).map((q:StockQuote)=>[q.symbol,q])));setQuotesStale(data.some(x=>x.stale));setQuoteError('')}})
        .catch(e=>{if(!cancelled)setQuoteError(String(e.message||e))});
    };
    load();
    const timer=setInterval(load,20000);
    document.addEventListener('visibilitychange',load);
    return()=>{cancelled=true;clearInterval(timer);document.removeEventListener('visibilitychange',load)};
  },[ready,market,selectedGroup.id,quoteSymbols]);

  useEffect(()=>{
    Promise.all([fetch('/api/settings/workspace').then(r=>r.json()),fetch('/api/settings/templates').then(r=>r.json())])
      .then(([a,b])=>{drawingRevision.current=Number(a.drawing_revision)||0;setState(restoreWorkspace(a.value));setTemplates(b.value||{});setReady(true)})
      .catch(()=>setReady(true));
    const loadStatus=()=>fetch('/api/status').then(r=>r.json()).then(setStatus).catch(()=>{});
    loadStatus();
    const t=setInterval(loadStatus,5000);
    return()=>clearInterval(t);
  },[]);
  useEffect(()=>{
    clearTimeout(saveRetryTimer.current);if(!ready||JSON.stringify(state)===lastSavedWorkspace.current)return;
    const snapshot=state,payload=JSON.stringify(state);
    const timer=setTimeout(()=>{saveQueue.current=saveQueue.current.catch(()=>{}).then(async()=>{
      if(!syncMounted.current||currentWorkspace.current!==snapshot)return;
      workspaceSaving.current=true;
      try{
        const response=await fetch('/api/settings/workspace',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:snapshot,drawing_revision:drawingRevision.current})});
        const data=await response.json();if(!response.ok)throw Error(data.detail||'工作区保存失败');if(!syncMounted.current)return;
        saveRetryCount.current=0;if(Number.isInteger(data.drawing_revision))drawingRevision.current=data.drawing_revision;
        if(data.drawings_conflict&&data.value){const next=mergeRemoteDrawings(currentWorkspace.current,data.value);lastSavedWorkspace.current=JSON.stringify(mergeRemoteDrawings(snapshot,data.value));setState(next);setDrawingSyncNotice('画线已被外部更新，已保留远端版本；本次修改请重新操作。')}
        else{lastSavedWorkspace.current=payload;setDrawingSyncNotice('')}
      }catch(e){if(syncMounted.current){setDrawingSyncNotice(String(e));saveRetryCount.current++;if(saveRetryCount.current<=5)saveRetryTimer.current=window.setTimeout(()=>setWorkspaceRetry(v=>v+1),Math.min(30000,1000*2**saveRetryCount.current))}}finally{workspaceSaving.current=false}
    })},700);
    return()=>clearTimeout(timer);
  },[state,ready,workspaceRetry]);
  useEffect(()=>{
    if(!ready)return;let stopped=false,busy=false;
    const idle=()=>!workspaceSaving.current&&JSON.stringify(currentWorkspace.current)===lastSavedWorkspace.current&&!document.querySelector('.trend-dragging');
    const poll=async()=>{if(stopped||busy||document.hidden||!idle())return;busy=true;const snapshot=currentWorkspace.current;
      try{const r=await fetch('/api/settings/workspace?drawings_only=true&since='+drawingRevision.current);if(!r.ok)return;const data=await r.json();if(!stopped&&idle()&&currentWorkspace.current===snapshot&&data.changed&&Number.isInteger(data.drawing_revision)&&data.drawing_revision>drawingRevision.current){const next=mergeRemoteDrawings(snapshot,data.value);drawingRevision.current=data.drawing_revision;lastSavedWorkspace.current=JSON.stringify(next);setState(next)}}catch{}finally{busy=false}
    };
    const timer=setInterval(poll,3000);document.addEventListener('visibilitychange',poll);return()=>{stopped=true;clearInterval(timer);document.removeEventListener('visibilitychange',poll)};
  },[ready]);
  const updateMarket=(fn:(w:MarketWorkspace)=>MarketWorkspace)=>setState(old=>({...old,markets:{...old.markets,[old.activeMarket]:fn(old.markets[old.activeMarket])}}));
  const importGroups=async()=>{
    setImportingGroups(true);setImportMessage('');
    try{
      const r=await fetch('/api/watchlists/import-moomoo',{method:'POST'});
      const data=await r.json();
      if(!r.ok)throw Error(data.detail||'读取失败');
      setState(restoreWorkspace(data.value));
      setImportMessage(`已导入：美股 ${data.summary.US.groups} 组 / ${data.summary.US.symbols} 只，A 股 ${data.summary.CN.groups} 组 / ${data.summary.CN.symbols} 只`);
    }catch(e:any){setImportMessage(String(e.message||e))}
    finally{setImportingGroups(false)}
  };
  const switchMarket=(next:Market)=>{setState(old=>({...old,activeMarket:next}));setActive(0);setNewSymbol('');setSymbolError('')};
  const selectGroup=(id:string)=>{
    updateMarket(w=>{const g=w.groups.find(x=>x.id===id);return g?{...w,selectedGroupId:id,tiles:w.tiles.map((t,i)=>g.symbols.length?{...t,symbol:g.symbols[i%g.symbols.length]}:t)}:w});
    setActive(0);
  };
  const normalizeSymbol=(input:string)=>{
    let s=input.trim().toUpperCase();
    if(market==='US')s=s.startsWith('US.')?s:`US.${s}`;
    else if(/^\d{6}$/.test(s))s= /^[569]/.test(s)?`SH.${s}`:`SZ.${s}`;
    return belongs(s,market)&&(market==='US'?/^US\.[A-Z0-9.]{1,12}$/.test(s):/^(SH|SZ)\.\d{6}$/.test(s))?s:null;
  };
  const viewSymbol=(candidate=newSymbol,name?:string)=>{
    const symbol=normalizeSymbol(candidate);if(!symbol){setSymbolError(market==='US'?'请输入 AAPL 或 US.AAPL':'请输入 SH.600519 或 SZ.000001');return}
    if(name)setStockNames(old=>({...old,[symbol]:name}));
    updateMarket(w=>({...w,tiles:w.tiles.map((t,i)=>i===active?{...t,symbol}:t)}));setNewSymbol('');setSymbolError('');
  };
  const addSymbol=(candidate=newSymbol,name?:string)=>{
    const s=normalizeSymbol(candidate);
    if(!s){setSymbolError(market==='US'?'请输入 AAPL 或 US.AAPL':'请输入 SH.600519 或 SZ.000001');return}
    if(name)setStockNames(old=>({...old,[s]:name}));
    updateMarket(w=>({...w,
      groups:w.groups.map(g=>g.id===w.selectedGroupId?{...g,symbols:[...new Set([...g.symbols,s])]}:g),
      tiles:w.tiles.map((t,i)=>i===active||!w.groups.find(g=>g.id===w.selectedGroupId)?.symbols.length?{...t,symbol:s}:t),
    }));
    setNewSymbol('');setSymbolError('');
  };
  const removeSymbol=(symbol:string)=>updateMarket(w=>{
    const group=w.groups.find(g=>g.id===w.selectedGroupId),remaining=(group?.symbols||[]).filter(s=>s!==symbol);
    return {...w,groups:w.groups.map(g=>g.id===w.selectedGroupId?{...g,symbols:remaining}:g),
      tiles:w.tiles.map(t=>t.symbol===symbol&&remaining[0]?{...t,symbol:remaining[0]}:t)};
  });
  const toggleFeatured=(symbol:string)=>updateMarket(w=>{
    const g=w.groups.find(x=>x.id==='featured')!;
    const remaining=g.symbols.filter(s=>s!==symbol);
    return {...w,groups:w.groups.map(x=>x.id==='featured'?{...x,symbols:g.symbols.includes(symbol)?remaining:[...g.symbols,symbol]}:x),
      tiles:w.selectedGroupId==='featured'&&g.symbols.includes(symbol)?w.tiles.map(t=>t.symbol===symbol&&remaining[0]?{...t,symbol:remaining[0]}:t):w.tiles};
  });
  const addGroup=()=>{
    const name=newGroupName.trim().slice(0,24);
    if(!name||ws.groups.some(g=>g.name.toLowerCase()===name.toLowerCase())){setGroupError('请输入不重复的分组名称');return}
    const id=`g-${Date.now()}-${Math.random().toString(36).slice(2,6)}`;
    updateMarket(w=>({...w,groups:[...w.groups,{id,name,symbols:[]}],selectedGroupId:id}));
    setActive(0);setNewGroupName('');setGroupError('');
  };
  const renameGroup=()=>{
    const name=groupDraft.trim().slice(0,24);
    if(!name||ws.groups.some(g=>g.id!==editingGroup&&g.name.toLowerCase()===name.toLowerCase())){setGroupError('请输入不重复的分组名称');return}
    updateMarket(w=>({...w,groups:w.groups.map(g=>g.id===editingGroup?{...g,name}:g)}));
    setEditingGroup('');setGroupError('');
  };
  const deleteGroup=(id:string)=>{
    if(id==='featured'||!window.confirm('删除这个分组？分组内的股票不会从其他分组移除。'))return;
    updateMarket(w=>{const featuredSymbols=w.groups.find(g=>g.id==='featured')?.symbols||[];return {...w,groups:w.groups.filter(g=>g.id!==id),selectedGroupId:w.selectedGroupId===id?'featured':w.selectedGroupId,
      tiles:w.selectedGroupId===id&&featuredSymbols.length?w.tiles.map((t,i)=>({...t,symbol:featuredSymbols[i%featuredSymbols.length]})):w.tiles}});
    setActive(0);
  };
  const setTile=(patch:Partial<Tile>)=>updateMarket(w=>({...w,tiles:w.tiles.map((t,i)=>i===active?{...t,...patch}:t)}));
  const addCustom=async()=>{try{
    if(!customName.trim())throw Error('请填写指标名称');
    let inputs:Record<string,number>={};
    if(customLanguage==='python'){
      try{inputs=JSON.parse(customInputs)}catch{throw Error('参数应为 JSON 对象，例如 {"fast":12,"slow":26,"signal":9}')}
      const response=await fetch('/api/python-indicator/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:customFormula,inputs})});
      if(!response.ok)throw Error((await response.json()).detail||'Python 代码不受支持');
    }else formula(customFormula);
    updateMarket(w=>({...w,indicators:[...w.indicators,{id:`i-${Date.now()}-${Math.random().toString(36).slice(2)}`,name:customLanguage==='python'?'PYTHON':'CUSTOM',title:customName.trim(),pane:customPane,params:JSON.stringify(customLanguage==='python'?{code:customFormula.trim(),inputs}:{formula:customFormula.trim()}),visible:true}]}));
    setCustomError('');setCustomName('');
  }catch(e){setCustomError(String(e))}};
  const saveTemplate=()=>{if(!templateName.trim())return;const next={...templates,[templateName.trim()]:ws.indicators};setTemplates(next);fetch('/api/settings/templates',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:next})});setTemplateName('')};
  const patchIndicator=(id:string,patch:Partial<Indicator>)=>updateMarket(w=>({...w,indicators:w.indicators.map(ind=>ind.id===id?{...ind,...patch}:ind)}));
  const selectCustomLanguage=(next:'formula'|'python')=>{
    if(next===customLanguage)return;
    if(next==='python'&&customFormula==='EMA(C,12)-EMA(C,26)')setCustomFormula(pythonExample);
    if(next==='formula'&&customFormula===pythonExample)setCustomFormula('EMA(C,12)-EMA(C,26)');
    setCustomLanguage(next);setCustomError('');
  };

  const indicatorSettings=<div className="indicator-panel"><div className="settings-section-heading"><h3>主图与副图指标</h3><p>主图指标叠加在 K 线上；副图指标使用独立面板。各指标可调整位置。</p></div><div className="add-indicator"><select value={newIndicator} onChange={e=>{setNewIndicator(e.target.value);setNewIndicatorPane(indicatorPane({name:e.target.value}))}}>{names.map(n=><option key={n} value={n}>{indicatorLabels[n]||n}</option>)}</select><select aria-label="新指标绘制位置" value={newIndicatorPane} onChange={e=>setNewIndicatorPane(e.target.value as 'main'|'separate')}><option value="main">主图叠加</option><option value="separate">独立副图</option></select><button className="primary" onClick={()=>updateMarket(w=>({...w,indicators:[...w.indicators,{id:`i-${Date.now()}-${Math.random().toString(36).slice(2)}`,name:newIndicator,pane:newIndicatorPane,params:JSON.stringify(indicatorDefaults[newIndicator]||{}),visible:true}]}))}><Plus size={14}/> 添加指标</button></div><div className="indicator-list">{(['main','separate'] as const).map(pane=><section className="indicator-pane-group" key={pane}><h3>{pane==='main'?'主图叠加指标':'独立副图指标'} <small>{ws.indicators.filter(ind=>indicatorPane(ind)===pane).length}</small></h3>{ws.indicators.filter(ind=>indicatorPane(ind)===pane).map(ind=><IndicatorSettings key={ind.id} indicator={ind} onPatch={patch=>patchIndicator(ind.id,patch)} onDelete={()=>updateMarket(w=>({...w,indicators:w.indicators.filter(x=>x.id!==ind.id)}))}/>)}{!ws.indicators.some(ind=>indicatorPane(ind)===pane)&&<p className="settings-empty">暂无此类指标，可从上方添加。</p>}</section>)}</div><div className="custom-editor"><h3>新建自定义指标</h3>
  <div className="custom-language" role="tablist" aria-label="自定义指标语言"><button role="tab" aria-selected={customLanguage==='formula'} className={customLanguage==='formula'?'chosen':''} onClick={()=>selectCustomLanguage('formula')}>简易公式</button><button role="tab" aria-selected={customLanguage==='python'} className={customLanguage==='python'?'chosen':''} onClick={()=>selectCustomLanguage('python')}>Python</button></div>
  <input placeholder="名称，如双均线差" value={customName} onChange={e=>setCustomName(e.target.value)}/>
  <textarea aria-label={customLanguage==='python'?'Python 指标代码':'指标公式'} value={customFormula} onChange={e=>setCustomFormula(e.target.value)} spellCheck={false}/>
  {customLanguage==='python'&&<label className="custom-inputs-label">参数默认值（JSON）<input aria-label="Python 参数默认值" value={customInputs} onChange={e=>setCustomInputs(e.target.value)} spellCheck={false}/></label>}
  <div className="custom-options"><select value={customPane} onChange={e=>setCustomPane(e.target.value as 'main'|'separate')}><option value="separate">独立副图</option><option value="main">叠加主图</option></select><button onClick={addCustom}><Plus size={14}/> 添加</button></div>
  <small>{customLanguage==='python'?'Python：示例用 PARAMS["fast"] 等读取可调参数；支持 O/H/L/C/V、SMA、EMA、REF、HHV、LLV、math 和 statistics。添加后可直接调整参数数值；语法错误显示在此，运行错误显示在图表。':'简易公式：支持 O/H/L/C/V、SMA、EMA、REF、HHV、LLV、ABS、MAX、MIN 和四则运算。'}</small>
  {customError&&<p className="custom-error">{customError}</p>}
</div><div className="template"><h3>指标模板</h3><div className="template-save"><input placeholder="模板名称" value={templateName} onChange={e=>setTemplateName(e.target.value)}/><button onClick={saveTemplate}><Save size={14}/> 保存</button></div>{Object.entries(templates).map(([name,value])=><button className="template-item" key={name} onClick={()=>updateMarket(w=>({...w,indicators:value}))}>{name} <span>{value.length} 项</span></button>)}</div></div>;
  return <div className={`shell chart-workspace ${watchCollapsed?'watch-collapsed':''}`}>
    <header><div className="brand"><div className="brand-mark"><Activity size={20}/></div><div><strong>NAS MARKET</strong><small>私人多市场看盘终端</small></div></div>
      <div className="current-instrument" aria-label="当前查看股票"><span>当前查看</span><strong title={stockNames[current.symbol]||quotes[current.symbol]?.name||current.symbol}>{stockNames[current.symbol]||quotes[current.symbol]?.name||current.symbol.replace('US.','')}</strong><code>{current.symbol}</code><small>图 {active+1} · {periodLabel(current.period)}</small></div>
      <div className="workspace-actions"><button className="secondary" aria-label="设置" onClick={()=>setSettingsTab('indicators')}><Settings2 size={16}/> 设置</button><div className="layout-picker"><LayoutGrid size={15}/>{[1,2,4].map(n=><button key={n} className={ws.layout===n?'chosen':''} onClick={()=>{setActive(i=>Math.min(i,n-1));updateMarket(w=>({...w,layout:n,tiles:Array.from({length:Math.max(n,w.tiles.length)},(_,i)=>w.tiles[i]||{symbol:w.tiles[0]?.symbol||'US.SNDK',period:(["5m","15m","60m","1d"] as Period[])[i]})}))}}>{n}</button>)}</div></div><div className="header-right"><button className="watch-toggle" aria-label="切换自选侧栏" aria-expanded={!watchCollapsed} onClick={toggleWatch}>自选</button><span className="connection">{status.opend_connected?<><span className="dot green"/> OpenD 已连接</>:status.last_error?<><span className="dot red"/> OpenD 连接异常</>:<><span className="dot idle"/> OpenD 按需连接</>}</span><button className="icon-button" title="刷新行情" onClick={()=>setRefresh(x=>x+1)}><RotateCw size={17}/></button></div>
    </header>
    <div className="app-body"><aside className={mobileWatchOpen?'mobile-open':''}>
      <div className="side-title"><span>自选行情</span><span className="side-title-caption">WATCHLIST</span></div>
      <div className="market-tabs" role="tablist" aria-label="市场">
        <button role="tab" aria-selected={market==='US'} className={market==='US'?'on':''} onClick={()=>switchMarket('US')}>美股</button>
        <button role="tab" aria-selected={market==='CN'} className={market==='CN'?'on':''} onClick={()=>switchMarket('CN')}>A 股</button>
      </div>
      <div className="side-group">
        <div className="group-heading"><span>我的分组 <small>{ws.groups.length}</small></span><div><button aria-label="向左滚动分组" onClick={()=>groupRail.current?.scrollBy({left:-200,behavior:'smooth'})}>‹</button><button aria-label="向右滚动分组" onClick={()=>groupRail.current?.scrollBy({left:200,behavior:'smooth'})}>›</button><button className={manageGroups?'active':''} aria-expanded={manageGroups} onClick={()=>setManageGroups(v=>!v)}>管理</button></div></div>
        <div className="watch-groups" ref={groupRail} role="tablist" aria-label="自选分组">{ws.groups.map(g=><button key={g.id} role="tab" aria-selected={g.id===selectedGroup.id} className={`group-chip ${g.id===selectedGroup.id?'active':''}`} title={g.name} onClick={e=>{selectGroup(g.id);setEditingGroup('');e.currentTarget.scrollIntoView({block:'nearest',inline:'nearest',behavior:'smooth'})}}>{g.id==='featured'&&<span className="group-star">★</span>}<span>{g.name.replace(/^(美股|A股|A 股)\s*[|｜]\s*/, '')}</span><small>{g.symbols.length}</small></button>)}</div>
        {manageGroups&&<div className="group-manager">
          <div className="group-manager-current"><span>{selectedGroup.name}</span>{selectedGroup.id!=='featured'&&<div><button onClick={()=>{setEditingGroup(selectedGroup.id);setGroupDraft(selectedGroup.name)}}>重命名</button><button onClick={()=>deleteGroup(selectedGroup.id)}>删除</button></div>}</div>
          {editingGroup===selectedGroup.id&&<input className="group-edit" aria-label="分组名称" value={groupDraft} autoFocus onChange={e=>setGroupDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')renameGroup();if(e.key==='Escape')setEditingGroup('')}} onBlur={renameGroup}/>}
          <div className="add-group"><input aria-label="新分组名称" value={newGroupName} onChange={e=>setNewGroupName(e.target.value)} onKeyDown={e=>e.key==='Enter'&&addGroup()} placeholder="新建分组"/><button title="创建分组" onClick={addGroup}><Plus size={15}/></button></div>
          <button className="moomoo-import" onClick={importGroups} disabled={importingGroups}>{importingGroups?'正在同步…':'从 moomoo 同步分组'}</button>
          {importMessage&&<div className="quote-notice" title={importMessage}>{importMessage}</div>}
          {groupError&&<div className="side-error">{groupError}</div>}
        </div>}
        <div className="group-label selected-label">股票 · {selectedGroup.name} <span>{selectedGroup.symbols.length}</span></div>
        {quoteError&&<div className="quote-notice" title={quoteError}>报价暂不可用，图表仍可查看</div>}
        {quotesStale&&<div className="quote-notice">报价为上次缓存数据</div>}
        {!selectedGroup.symbols.includes(current.symbol)&&<div className="preview-instrument" aria-label="临时查看股票"><span>正在查看 · 未加入当前分组</span><strong>{stockNames[current.symbol]||quotes[current.symbol]?.name||current.symbol.replace('US.','')}</strong><div><code>{current.symbol}</code><button onClick={()=>addSymbol(current.symbol,stockNames[current.symbol]||quotes[current.symbol]?.name)}>＋ 加入本组</button></div></div>}
        <div className="symbol-list" role="region" aria-label="自选股票列表" tabIndex={0}>{selectedGroup.symbols.map(s=><div key={s} className={`symbol ${current?.symbol===s?'active':''}`}>
          <button className="stock-select" onClick={()=>{setTile({symbol:s});setMobileWatchOpen(false)}} title={quotes[s]?.update_time?`OpenD 更新：${quotes[s].update_time}`:s}>
            <span className="symbol-icon">{s.split('.')[1].slice(0,1)}</span>
            <span className="stock-main"><span className="stock-top"><strong>{market==='CN'&&(stockNames[s]||quotes[s]?.name)&&/[\u3400-\u9fff]/.test(stockNames[s]||quotes[s].name)?stockNames[s]||quotes[s].name:s.split('.')[1]}</strong><b>{priceText(quotes[s]?.price??null,market)}</b></span>
              <span className="stock-middle"><small>{market==='CN'?s:quotes[s]?.name||s}</small><em className={quotes[s]?.change_percent==null?'flat':quotes[s].change_percent!>=0?'positive':'negative'}>{percent(quotes[s]?.change_percent??null)}</em></span>
              {market==='US'&&<span className="stock-sessions">{quotes[s]?.after_price!=null&&quotes[s].after_price!>0&&<span>盘后 <em className={quotes[s].after_change_percent!=null&&quotes[s].after_change_percent!<0?'negative':'positive'}>{percent(quotes[s].after_change_percent)}</em></span>}{quotes[s]?.overnight_price!=null&&quotes[s].overnight_price!>0&&<span>夜盘 <em className={quotes[s].overnight_change_percent!=null&&quotes[s].overnight_change_percent!<0?'negative':'positive'}>{percent(quotes[s].overnight_change_percent)}</em></span>}</span>}
            </span>
          </button>
          <span className="stock-actions"><button className={`favorite ${featured.symbols.includes(s)?'on':''}`} title={featured.symbols.includes(s)?'从精选移除':'加入精选'} onClick={()=>toggleFeatured(s)}>★</button><button className="remove" title="从当前分组移除" onClick={()=>removeSymbol(s)}><Minus size={13}/></button></span>
        </div>)}</div>
        <StockSearch key={market} market={market} query={newSymbol} onQuery={value=>{setNewSymbol(value);setSymbolError('')}} onView={viewSymbol} onAdd={addSymbol}/>
        {symbolError&&<div className="side-error">{symbolError}</div>}
      </div>
      <div className="side-bottom"><div className="resource"><span>实时订阅</span><strong>{status.active_streams||0} / {status.max_streams||32}</strong></div><p>行情由本机 OpenD 提供。美股交易使用独立 HTTPS 入口。</p></div>
    </aside><main>


      {market==='CN'&&status.permission_errors?.CN&&<div className="market-permission-note" role="status"><strong>A 股实时行情权限不足</strong><span>继续显示 NAS 已有历史数据。请在 OpenD 检查 A 股行情授权及登录网络地区；moomoo App 的权限不一定等同于 API。</span><button onClick={async()=>{await fetch('/api/quote/retry?symbol='+encodeURIComponent(current?.symbol||'SH.600584'),{method:'POST'});setRefresh(x=>x+1)}}>已检查权限，重试</button></div>}
      <div className="toolbar"><div className="toolbar-section"><span>周期</span>{periods.map(p=><button key={p} className={current?.period===p?'on':''} onClick={()=>setTile({period:p})}>{periodLabel(p)}</button>)}</div><div className="toolbar-line"/><div className="toolbar-section"><span>时段</span>{market==='US'?<><button className={!isLongPeriod(current?.period||'5m')&&ws.mode!=='regular'?'on':''} aria-label="扩展时段" aria-pressed={!isLongPeriod(current?.period||'5m')&&ws.mode!=='regular'} disabled={isLongPeriod(current?.period||'5m')} title="开关盘前/盘后；右侧可选择是否包括隔夜，重新开启恢复上次范围" onClick={()=>updateMarket(w=>({...w,mode:w.mode==='regular'?lastExtendedMode.current:'regular'}))}>扩展时段</button><select aria-label="图表交易时段" disabled={isLongPeriod(current?.period||'5m')} value={isLongPeriod(current?.period||'5m')?'regular':ws.mode} onChange={e=>updateMarket(w=>({...w,mode:e.target.value as Mode}))}><option value="all">24H 全时段</option><option value="extended">盘前 + 常规 + 盘后</option><option value="regular">仅常规</option></select>{!isLongPeriod(current?.period||'5m')&&ws.mode!=='regular'&&<span className="session-legend" aria-label="扩展时段背景图例"><i className="pre"/>盘前<i className="post"/>盘后{ws.mode==='all'&&<><i className="overnight"/>隔夜</>}</span>}</>:<span className="cn-session">沪深常规时段 · 北京时间</span>}</div><div className="toolbar-end">{ws.indicators.filter(i=>current&&appliesTo(i,active,current.period)).length} 个指标用于当前图</div></div>
      {drawingSyncNotice&&<div className="drawing-sync-notice" role="status">{drawingSyncNotice}<button onClick={()=>{saveRetryCount.current=0;lastSavedWorkspace.current='';setWorkspaceRetry(v=>v+1)}}>重试保存</button><button onClick={()=>setDrawingSyncNotice('')}>知道了</button></div>}<div className="workspace-drawing-host" ref={setDrawingHost}/>{ws.tiles.some(t=>Boolean(t.symbol))?<div className={`charts-grid cols-${ws.layout}`}>{ws.tiles.slice(0,ws.layout).map((tile,i)=><ChartPane drawingHost={drawingHost} key={`${market}-${i}-${tile.symbol}`} index={i} tile={tile} mode={ws.mode} indicators={ws.indicators} active={active===i} onActivate={()=>setActive(i)} drawings={drawingViews[i].horizontal} onDraw={v=>updateMarket(w=>({...w,drawings:updateDrawingRecords(w.drawings,tile.symbol,tile.period,v)}))} trends={drawingViews[i].trends} onTrend={v=>updateMarket(w=>({...w,trends:updateDrawingRecords(w.trends,tile.symbol,tile.period,v)}))} fibos={drawingViews[i].fibos} onFibos={v=>updateMarket(w=>({...w,fibos:updateDrawingRecords(w.fibos,tile.symbol,tile.period,v)}))} drawingsHidden={ws.drawingsHidden[`${tile.symbol}:${tile.period}`]===true} onDrawingsHidden={value=>updateMarket(w=>({...w,drawingsHidden:{...w.drawingsHidden,[`${tile.symbol}:${tile.period}`]:value}}))} version={refresh} stockName={stockNames[tile.symbol]||quotes[tile.symbol]?.name} depthSettingsOpen={settingsTab==='depth'&&active===i} settingsHost={settingsHost}/>)}</div>:
        <div className="empty-watchlist"><strong>{selectedGroup.name}还是空的</strong><p>在左侧输入股票代码，就能开始看盘。</p><small>{market==='US'?'示例：AAPL、US.SNDK':'示例：SH.600519、SZ.000001'}</small></div>}
      {market==='US'&&<div className="market-trade-strip"><div><strong>{current?.symbol||'US.SNDK'}</strong><span>当前图表 · 快捷交易</span></div><div className="market-trade-buttons"><button className="buy" onClick={()=>openTrading(current?.symbol||'US.SNDK','buy')}>买入</button><button className="close" onClick={()=>openTrading(current?.symbol||'US.SNDK','close')}>平仓</button><button className="stop" onClick={()=>openTrading(current?.symbol||'US.SNDK','stop')}>设置止损</button><button onClick={()=>openTrading(current?.symbol||'US.SNDK','options')}>期权</button><button className="strategy-entry" onClick={()=>openTrading(current?.symbol||'US.SNDK','strategy')}>自定义策略</button></div><small>图内交易面板 · 自定义快捷方案 · 实盘需解锁</small></div>}
      {market==='US'&&secureChart&&showStrategies&&<Suspense fallback={<p>正在打开策略编辑器…</p>}><StrategyPanel symbol={current?.symbol||'US.SNDK'} period={current?.period||'5m'} mode={ws.mode} indicators={ws.indicators} onClose={()=>setShowStrategies(false)} onOpenTrading={()=>openTrading(current?.symbol||'US.SNDK','overview')}/></Suspense>}
      {market==='CN'&&<div className="market-trade-strip market-trade-readonly"><strong>A 股 · 看盘模式</strong><small>当前平台未开放 A 股交易</small></div>}
    {market==='US'&&secureChart&&tradeDock&&<section className="chart-trade-dock" aria-label="图内交易面板"><div className="chart-trade-dock-head"><strong>快捷交易</strong><button onClick={()=>setDockSymbol(current?.symbol||dockSymbol)} disabled={market!=='US'}>带入当前图表</button><button onClick={()=>setTradeDock(false)} aria-label="关闭图内交易">×</button></div><TradeTerminal embedded product={dockProduct} chartSymbol={dockSymbol} onSessionEnd={onSessionEnd}/></section>}

    </main></div>

    {settingsTab&&<SettingsPanel tab={settingsTab} onTab={setSettingsTab} onClose={()=>setSettingsTab(null)} onContentHost={setSettingsHost}>{settingsTab==='indicators'?indicatorSettings:settingsTab==='cache'?<CachePanel embedded symbol={current?.symbol} onClose={()=>setSettingsTab(null)}/>:market==='CN'?<p>A 股暂不支持美股盘口密集线。</p>:<p className="settings-depth-caption">{current.symbol} · 参数按股票保存；工具栏“挂档密集线”可直接开关。</p>}</SettingsPanel>}

  </div>;
}
function SecureChart(){
 const [auth,setAuth]=useState<boolean|null>(null);
 useEffect(()=>{fetch('/api/trade/auth').then(r=>r.json()).then(a=>{setChartCsrf(a.csrf||'');setAuth(!!a.authenticated)}).catch(()=>setAuth(false))},[]);
 if(auth===null)return <div className="trade-login">正在检查交易平台登录状态…</div>;
 return auth?<App onSessionEnd={()=>{setChartCsrf('');setAuth(false)}}/>:<TradeTerminal onAuthenticated={token=>{setChartCsrf(token);setAuth(true)}}/>;
}
createRoot(document.getElementById('root')!).render(location.pathname.startsWith('/trade')?<TradeTerminal/>:secureChart?<SecureChart/>:<App/>);
