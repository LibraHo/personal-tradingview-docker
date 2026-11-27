import {chartSignalMarkers} from './chartSignalMarkers';
import {macdDivergences,macdStructure} from './macdStructure';
import IndicatorLibrary from './IndicatorLibrary';
import {drawTdx,resonanceColors} from './tdxChart';
import {tdxCatalog,tdxAvailable,isChiefResonance} from './tdxIndicators';
import ApiManagement from './ApiManagement';
import ScannerPanel from './ScannerPanel';
import MarketRadar, {type RadarItem} from './MarketRadar';
import IndicatorPicker from './IndicatorPicker';
import {msigm8Overlay} from './msigm8Overlay';
import {advancedCatalog} from './advancedCatalog';
import QuickIndicators from './QuickIndicators';
import {openingRangeLines,type OpeningRangeData} from './OpeningRange';
import{lazy,Suspense,useEffect,useMemo,useRef,useState}from'react';
import{createRoot}from'react-dom/client';
import{createPortal}from'react-dom';
import{trendExtension,drawingTimeCoordinate}from'./TrendExtensions';
import{drawingTimeAtX,moveTrendEndpoint,hitTestTrendEndpoint,type TimeSample}from'./trendGeometry';
import type{PointerEvent as ReactPointerEvent}from'react';
import{backfillHistory,marketDateWindow}from'./historyTools';
import{type SeriesMarker,createChart,CandlestickSeries,HistogramSeries,LineSeries,CrosshairMode,TickMarkType,type IChartApi,type ISeriesApi,type MouseEventParams,type Time,type UTCTimestamp}from'lightweight-charts';
import './analysis-tool.css';
import{Activity,BookOpen,Sparkles,Plus,Settings2,Trash2,Save,LayoutGrid,Wifi,WifiOff,RotateCw,Minus}from'lucide-react';
import {inputIssue} from './indicatorInputs';
import{type Bar,type Indicator,compute,indicatorPane}from'./indicators';
import{formula}from'./formula';
import './style.css';
import './workspace-navigation.css';
import {ThemeProvider,ThemeToggle,useTheme} from './Theme';
import TradeTerminal from './TradeTerminal';
import {secureChart,setChartCsrf} from './secureChart';
import MarketFlowPanel from './MarketFlowPanel';
import DepthPanel,{type DepthLevel} from './DepthPanel';
import CachePanel from './CachePanel';
import StockSearch from './StockSearch';
import {resetChartViewport,resetPriceScales,markViewportReady} from './chartViewport';
import SettingsPanel,{type SettingsTab} from './SettingsPanel';
import AgentSettings from './AgentSettings';
import NotificationSettings from './NotificationSettings';
import OpenDPanel from './OpenDPanel';
import ChipSummary from './ChipSummary';
import CandleSettings from './CandleSettings';
import {defaultCandleAppearance,normalizeCandleAppearance,candleSeriesOptions,candleBodyColor,volumePalette,type CandleAppearance} from './candleAppearance';
import type {CSSProperties} from 'react';
import {sixPulsePanel} from './sixpulsePanel';
import {sixPulseLevelsOverlay} from './sixpulseLevelsOverlay';
import IndicatorParameters,{indicatorLabels,indicatorDefaults} from './IndicatorParameters';
import {visibleExtremeLabels} from './VisibleExtremes';
import {sessionBackground} from './SessionBackground';
import {macdHistogramColor,volumeColor,selectedColor,indicatorDefaultColor} from './histogramColors';
import IndicatorAppearance from './IndicatorAppearance';
import DrawingsPanel from './DrawingsPanel';
import ChartMenu from './ChartMenu';
import './chart-toolbar.css';
import {measureLine} from './MeasureLine';
import {measureNames,measurePoints,type MeasureDrawing,type MeasureAxis,fibPrices,drawingStyle,normalizeDrawingRecords,drawingsForPeriod,updateDrawingRecords,newDrawingId,hitTestDrawing,type FibDrawing,type HorizontalDrawing,type TrendDrawing,type DrawingSelection} from './drawingTools';
import {useBackgroundReport,type OpenReport} from './useBackgroundReport';
import type {AnalysisChart} from './MarketAnalysis';
import type {AnalysisDrawingBatch} from './AnalysisDrawings';
import {flushSync} from 'react-dom';
const MarketAnalysis=lazy(()=>import('./MarketAnalysis'));
const StrategyPanel=lazy(()=>import('./StrategyPanel'));
const DailyReview=lazy(()=>import('./DailyReview'));
const ChartPlanDialog=lazy(()=>import('./ChartPlanDialog'));
type Mode='all'|'extended'|'regular';type Period='1m'|'5m'|'15m'|'30m'|'60m'|'120m'|'240m'|'1d'|'1w'|'1mo';
type Tile={symbol:string;period:Period};
type StockQuote={symbol:string;name:string;price:number|null;change_percent:number|null;pre_price:number|null;pre_change_percent:number|null;after_price:number|null;after_change_percent:number|null;overnight_price:number|null;overnight_change_percent:number|null;update_time:string};
const percent=(value:number|null)=>value===null?'—':`${value>0?'+':''}${value.toFixed(2)}%`;
const priceText=(value:number|null,market:'US'|'CN')=>value===null?'—':`${market==='US'?'$':'¥'}${value.toFixed(2)}`;
const mergeBars=(older:Bar[],newer:Bar[])=>[...new Map([...older,...newer].map(bar=>[bar.time,bar])).values()].sort((a,b)=>a.time-b.time);
type TrendPoint={time:number;price:number};
const defaultPinnedPeriods:Period[]=['5m','15m','60m','1d','1w'];
const periods:Period[]=['1m','5m','15m','30m','60m','120m','240m','1d','1w','1mo'];
const isLongPeriod=(p:string)=>['1d','1w','1mo'].includes(p);
const periodLabel=(p:string)=>({ '120m':'2小时','240m':'4小时','1d':'日线','1w':'周线','1mo':'月线'} as Record<string,string>)[p]||p;

function PeriodSwitcher({current,onSelect}:{current:Period;onSelect:(period:Period)=>void}){
 const [pinned,setPinned]=useState<Period[]>(()=>{
  try{
   const saved=JSON.parse(localStorage.getItem('chart-pinned-periods')??'null');
   if(Array.isArray(saved))return periods.filter(p=>saved.includes(p));
  }catch{}
  return defaultPinnedPeriods;
 });
 const togglePin=(period:Period)=>{
  const next=periods.filter(p=>p===period?!pinned.includes(p):pinned.includes(p));
  setPinned(next);
  try{localStorage.setItem('chart-pinned-periods',JSON.stringify(next))}catch{}
 };
 return <div className="toolbar-section period-switch" role="group" aria-label="K 线周期">
  {pinned.map(p=><button type="button" key={p} aria-pressed={current===p} className={current===p?'on':''} onClick={()=>onSelect(p)}>{periodLabel(p)}</button>)}
  <ChartMenu label={pinned.includes(current)?'更多周期':`更多周期 · ${periodLabel(current)}`} active={!pinned.includes(current)}>
   <div className="period-menu-heading"><span>切换周期</span><span>常驻</span></div>
   {periods.map(p=><div className="period-menu-row" key={p}>
    <button type="button" aria-pressed={current===p} onClick={()=>onSelect(p)}>{periodLabel(p)}</button>
    <label title={`常驻 ${periodLabel(p)}`}><input type="checkbox" aria-label={`常驻 ${periodLabel(p)}`} checked={pinned.includes(p)} onChange={()=>togglePin(p)}/></label>
   </div>)}
  </ChartMenu>
 </div>;
}

const names=['ORB5','EMA','SMA','VWAP','BBI','BOLL','ATR','MACD','DMI','RSI','VOLUME','WMA','VWMA','DC','STOCH','CCI','WR','ROC','MOM','OBV','CMF',...Object.keys(advancedCatalog)];
const chartSlots=[0,1,2,3];
const pythonExample='fast = EMA(C, PARAMS["fast"])\nslow = EMA(C, PARAMS["slow"])\nmacd = fast - slow\nsignal = EMA(macd, PARAMS["signal"])\nresult = {"MACD": macd, "Signal": signal, "Histogram": macd - signal}';
const appliesTo=(indicator:Indicator,index:number,period:Period)=>indicator.visible&&
  (!Array.isArray(indicator.charts)||indicator.charts.includes(index))&&
  (tdxCatalog[indicator.name]?.period===undefined
    ?(!Array.isArray(indicator.periods)||indicator.periods.includes(period))
    :tdxCatalog[indicator.name].period===period);

function IndicatorScope({indicator,onChange}:{indicator:Indicator;onChange:(patch:Partial<Indicator>)=>void}){
  const charts=Array.isArray(indicator.charts)?indicator.charts:chartSlots;
  const selectedPeriods=Array.isArray(indicator.periods)?indicator.periods:periods;
  const fixedPeriod=tdxCatalog[indicator.name]?.period;
  const toggleChart=(index:number)=>onChange({charts:charts.includes(index)?charts.filter(x=>x!==index):chartSlots.filter(x=>x===index||charts.includes(x))});
  const togglePeriod=(period:Period)=>onChange({periods:selectedPeriods.includes(period)?selectedPeriods.filter(x=>x!==period):periods.filter(x=>x===period||selectedPeriods.includes(x))});
  return <div className="indicator-scope">
    <div className="scope-line"><span>适用图</span><div className="scope-chips"><button type="button" className={charts.length===4?'chosen':''} onClick={()=>onChange({charts:[...chartSlots]})}>全部</button>{chartSlots.map(i=><button type="button" key={i} aria-label={`${indicator.title||indicator.name} 图 ${i+1}`} aria-pressed={charts.includes(i)} className={charts.includes(i)?'chosen':''} onClick={()=>toggleChart(i)}>图 {i+1}</button>)}</div></div>
    <div className="scope-line"><span>周期</span>{fixedPeriod?<strong>{periodLabel(fixedPeriod)}</strong>:<div className="scope-chips"><button type="button" className={selectedPeriods.length===periods.length?'chosen':''} onClick={()=>onChange({periods:[...periods]})}>全部</button>{periods.map(period=><button type="button" key={period} aria-label={`${indicator.title||indicator.name} ${period}`} aria-pressed={selectedPeriods.includes(period)} className={selectedPeriods.includes(period)?'chosen':''} onClick={()=>togglePeriod(period)}>{periodLabel(period)}</button>)}</div>}</div>
  </div>;
}

function IndicatorSettings({indicator,onPatch,onDelete}:{indicator:Indicator;onPatch:(patch:Partial<Indicator>)=>void;onDelete:()=>void}){
  const [newInputName,setNewInputName]=useState(''),[validationError,setValidationError]=useState('');
  const [expanded,setExpanded]=useState(false);
  const displayName=indicator.title||indicatorLabels[indicator.name]||indicator.name;
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
    <div className="indicator-row"><label><input type="checkbox" checked={indicator.visible} onChange={e=>onPatch({visible:e.target.checked})}/><strong>{displayName}</strong></label>{indicator.name==='PYTHON'?<span className="indicator-language">Python</span>:<span className="indicator-language">{indicatorPane(indicator)==='main'?'主图':'副图'}</span>}<button type="button" className="indicator-configure" aria-label={`设置 ${displayName}`} aria-expanded={expanded} aria-controls={`indicator-settings-${indicator.id}`} onClick={()=>setExpanded(!expanded)}>{expanded?'收起':'设置'}</button><button className="icon-button" title={`删除 ${displayName}`} onClick={onDelete}><Trash2 size={15}/></button></div>
    {expanded&&<div className="indicator-card-options" id={`indicator-settings-${indicator.id}`}>
    {indicator.name==='PYTHON'&&<><textarea className="python-code" aria-label={`${displayName} Python 代码`} value={pythonCode} spellCheck={false} onChange={e=>patchPython({code:e.target.value})}/><div className="python-inputs"><strong>可调参数</strong>{Object.entries(pythonInputs).map(([name,value])=><label key={`${name}:${value}`}>{name}<input aria-label={`${displayName} ${name}`} type="number" step="any" defaultValue={value} onBlur={e=>{const next=Number(e.target.value);if(!e.target.value||!Number.isFinite(next)){e.target.value=String(value);setValidationError(`${name} 须为数字`);return}patchPython({inputs:{...pythonInputs,[name]:next}})}}/><button title={`删除参数 ${name}`} onClick={()=>{const inputs={...pythonInputs};delete inputs[name];patchPython({inputs})}}>×</button></label>)}<div className="python-add-input"><input aria-label="新增参数名" placeholder="新增参数名" value={newInputName} onChange={e=>setNewInputName(e.target.value)} onKeyDown={e=>e.key==='Enter'&&addInput()}/><button onClick={addInput}>添加参数</button></div><small>代码中用 PARAMS["fast"] 读取参数；修改数值后离开输入框即生效。</small></div>{validationError&&<div className="side-error">{validationError}</div>}</>}
    {indicator.name!=='PYTHON'&&<IndicatorParameters indicator={indicator} onChange={params=>onPatch({params})}/>}
    <label className="indicator-pane-control">绘制位置<select aria-label={`${displayName} 绘制位置`} value={indicatorPane(indicator)} disabled={!!tdxCatalog[indicator.name]||['ORB5','SIXPULSE','SIXPULSE_SIGNAL','MSIGM8'].includes(indicator.name)} onChange={e=>onPatch({pane:e.target.value as 'main'|'separate'})}><option value="main">主图叠加</option><option value="separate">独立副图</option></select><span className="indicator-pane-badge">{indicatorPane(indicator)==='main'?'主图指标':'副图指标'}</span></label>
    <IndicatorAppearance indicator={indicator} onChange={onPatch}/>
    <details className="indicator-scope-details"><summary>适用图与周期</summary><IndicatorScope indicator={indicator} onChange={onPatch}/></details>
    </div>}
  </div>;
}
const toTime=(n:number)=>n as UTCTimestamp;
const etClock=new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const etDay=new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',month:'2-digit',day:'2-digit'});
const etFull=new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const cnClock=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const cnDay=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'});
const cnFull=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const chartGroup=new Map<number,{chart:IChartApi;candle:ISeriesApi<'Candlestick'>;ready:boolean;suppressSyncUntil:number;showFreeCrosshair:(x:number|null)=>void;freeCrosshair:HTMLDivElement}>();
let syncingCharts=false;
type DrawingCopy =
 | {kind:'horizontal';item:HorizontalDrawing}
 | {kind:'trend';item:TrendDrawing}
 | {kind:'fib';item:FibDrawing}
 | {kind:'measure';item:MeasureDrawing};
type DrawingClipboard={symbol:string;copy:DrawingCopy;count:number}|null;

function ChartPane({dateHost,drawingClipboard,setDrawingClipboard,streamHost,drawingHost,onAnalysis,index,tile,mode,appearance,snapCrosshairTime,indicators,onIndicatorToggle,active,onActivate,drawings,onDraw:commitHorizontal,trends,onTrend:commitTrends,fibos,onFibos:commitFibos,measures,onMeasures,drawingsHidden,onDrawingsHidden,version,stockName,depthHost}:{dateHost:HTMLDivElement|null;drawingClipboard:DrawingClipboard;setDrawingClipboard:(clip:DrawingClipboard)=>void;streamHost:HTMLSpanElement|null;drawingHost:HTMLDivElement|null;onAnalysis:(tile:Tile,mode:Mode)=>void;index:number;tile:Tile;mode:Mode;appearance:CandleAppearance;snapCrosshairTime:boolean;indicators:Indicator[];onIndicatorToggle:(id:string,visible:boolean)=>void;active:boolean;onActivate:()=>void;drawings:HorizontalDrawing[];onDraw:(v:HorizontalDrawing[])=>void;trends:TrendDrawing[];onTrend:(v:TrendDrawing[])=>void;fibos:FibDrawing[];onFibos:(v:FibDrawing[])=>void;measures:MeasureDrawing[];onMeasures:(v:MeasureDrawing[])=>void;drawingsHidden:boolean;onDrawingsHidden:(value:boolean)=>void;version:number;stockName?:string;depthHost:HTMLDivElement|null}){
 const theme=useTheme();
 const [depthLines,setDepthLines]=useState<DepthLevel[]>([]);
 const [hoverTime,setHoverTime]=useState<number|null>(null);
 const [drawingIssue,setDrawingIssue]=useState('');
 const [showPlan,setShowPlan]=useState(false);
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
 const [drawingUndo,setDrawingUndo]=useState<{horizontal:HorizontalDrawing[];trends:TrendDrawing[];fibos:FibDrawing[];measures:MeasureDrawing[];hidden:boolean}|null>(null);
 const [selectedDrawing,setSelectedDrawing]=useState<DrawingSelection|null>(null),[hoveredDrawing,setHoveredDrawing]=useState<DrawingSelection|null>(null),[editorRequest,setEditorRequest]=useState(0);
 const drawingHover=useRef<(p:any)=>void>(()=>{});
 const drawingLabel=(selection:DrawingSelection)=>{if(selection.kind==='measure'){const i=measures.findIndex(v=>v.id===selection.id);return i<0?'测量线':measureNames[measures[i].axis]+' '+(i+1)}const items=selection.kind==='horizontal'?drawings:selection.kind==='trend'?trends:fibos;return `${({horizontal:'水平线',trend:'趋势线',fib:'斐波那契'})[selection.kind]} ${items.findIndex(v=>v.id===selection.id)+1}`};
 const record=()=>setDrawingUndo({horizontal:drawings,trends,fibos,measures,hidden:drawingsHidden});
 const saveHorizontal=(v:HorizontalDrawing[])=>{record();onDraw(v)};const saveTrends=(v:TrendDrawing[])=>{record();onTrend(v)};const saveFibos=(v:FibDrawing[])=>{record();onFibos(v)};
 const saveMeasures=(rows:MeasureDrawing[])=>{if(acceptDrawingRows(rows)){record();onMeasures(rows)}};
 const toggleAllDrawings=(hidden:boolean)=>{record();onDrawingsHidden(hidden);if(hidden)setSelectedDrawing(null)};
 const deleteSelectedDrawing=()=>{if(!selectedDrawing)return;const {kind,id}=selectedDrawing;if(kind==='horizontal')saveHorizontal(drawings.filter(v=>v.id!==id));else if(kind==='trend')saveTrends(trends.filter(v=>v.id!==id));else if(kind==='measure')saveMeasures(measures.filter(v=>v.id!==id));else saveFibos(fibos.filter(v=>v.id!==id));setSelectedDrawing(null)};
 const [bars,setBars]=useState<Bar[]>([]),[loadedKey,setLoadedKey]=useState(''),[error,setError]=useState(''),[formulaError,setFormulaError]=useState(''),[stale,setStale]=useState(false),[live,setLive]=useState(false),[draw,setDraw]=useState<'off'|'horizontal'|'trend'|'fib'|'measureTime'|'measurePrice'>('off'),[trendStart,setTrendStart]=useState<TrendPoint|null>(null);
 const measureAxis:MeasureAxis|null=draw==='measureTime'?'horizontal':draw==='measurePrice'?'vertical':null;
 const measurePreview=useRef<ReturnType<typeof measureLine>|null>(null);
 const [pythonResults,setPythonResults]=useState<Record<string,{time:number[];values:Record<string,(number|null)[]>}>>({}),[pythonError,setPythonError]=useState('');
 const lastPythonRun=useRef({key:'',time:0});
 const volumeSeries=useRef<{series:ISeriesApi<any>;colors?:Record<string,string>}[]>([]);
 const [historyCursor,setHistoryCursor]=useState<number|null>(null),[hasMore,setHasMore]=useState(true),[loadingOlder,setLoadingOlder]=useState(false),[historyError,setHistoryError]=useState('');
 const historicView=useRef(false);
 const historyInteraction=useRef(false),olderBusy=useRef(false),liveRef=useRef(false),pendingHistoryJump=useRef<{from:number;to:number}|null>(null);
 const key=`${tile.symbol}:${tile.period}:${mode}`;
 const currentKey=useRef(key);currentKey.current=key;const historyGeneration=useRef(0);
 const activeIndicators=useMemo(()=>indicators.filter(ind=>tdxAvailable(ind.name,tile.symbol)&&appliesTo(ind,index,tile.period)),[indicators,index,tile.period,tile.symbol]);
 const isUS=tile.symbol.startsWith('US.');
 const openingEnabled=activeIndicators.some(ind=>ind.name==='ORB5')&&!isLongPeriod(tile.period)&&(isUS||tile.period!=='240m');
 const [openingStyleError,setOpeningStyleError]=useState('');
 const [opening,setOpening]=useState<{key:string;data:OpeningRangeData|null;error:string}>({key:'',data:null,error:''});
 useEffect(()=>{
  if(!openingEnabled||loadedKey!==key)return;
  let stopped=false,busy=false,timer:number|undefined;const controller=new AbortController();
  const load=async()=>{if(busy)return;if(document.visibilityState==='hidden'){timer=window.setTimeout(()=>void load(),30000);return}busy=true;let delay=30000;try{
   const response=await fetch('/api/opening-range?symbol='+encodeURIComponent(tile.symbol),{signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.detail||'开盘高低线读取失败');
   if(data.status==='forming')delay=Math.min(30000,Math.max(1000,data.confirmed_at*1000+2200-Date.now()));
   if(!stopped)setOpening({key,data,error:data.stale?('开盘高低线使用缓存：'+(data.error||'')):''});
  }catch(e){if(!stopped)setOpening(old=>({key,data:old.key===key?old.data:null,error:String(e)}))}finally{busy=false;if(!stopped)timer=window.setTimeout(()=>void load(),delay)}};
  void load();
  return()=>{stopped=true;controller.abort();clearTimeout(timer)};
 },[openingEnabled,loadedKey,key]);
 const chartName=!isUS&&stockName&&/[\u3400-\u9fff]/.test(stockName)?stockName:tile.symbol.replace('US.','');
 const displayTime=isUS?{clock:etClock,day:etDay,full:etFull}:{clock:cnClock,day:cnDay,full:cnFull};
 const previousRefresh=useRef(version);
 const seriesRevision=useRef('');
 const priceBasis=bars[0]?.adjustment;
 const [feed,setFeed]=useState({description:'',basis:'',notice:''});
 const [cacheSyncTime,setCacheSyncTime]=useState(0);
 useEffect(()=>{let stop=false,ws:WebSocket|null=null,timer:number|undefined,initialized=false,openedOnce=false,retryDelay=5000;
  const group=chartGroup.get(index);if(group&&loadedKey!==key){group.ready=false;group.suppressSyncUntil=Infinity}pendingHistoryJump.current=null;
  historyGeneration.current++;historicView.current=false;historyInteraction.current=false;olderBusy.current=false;setLoadingOlder(false);setHistoryCursor(null);setHasMore(true);setHistoryError('');
  const controller=new AbortController();
  let liveSupported=true;
  seriesRevision.current='';
  setFeed({description:'',basis:'',notice:''});
  const barsUrl=`/api/bars?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}`;
  let requestId=0;
  let pushedDuringLoad:Map<number,Bar>|null=null;
  const load=async(force=false,preferCache=false)=>{
   const id=++requestId;
   const pushes=new Map<number,Bar>();
   pushedDuringLoad=pushes;
   const read=async(cacheFirst:boolean)=>{
    const response=await fetch(barsUrl+(force?'&refresh=true':'')+(cacheFirst?'&prefer_cache=true':''),{signal:controller.signal});
    const data=await response.json();
    if(!response.ok)throw Error(data.detail||'读取 K 线失败');
    if(stop||id!==requestId||historicView.current)return false;
    const changed=!!seriesRevision.current&&seriesRevision.current!==data.series_revision;
    const first=!initialized||changed;
    if(changed){
      pushes.clear();historyGeneration.current++;olderBusy.current=false;
      setLoadingOlder(false);setHasMore(true);setHistoryError('');
    }
    seriesRevision.current=data.series_revision||'';
    liveSupported=data.live_supported!==false;
    setFeed({description:[data.provider,data.adjustment_label,data.history_notice,liveSupported&&data.live_provider!==data.provider?'实时 '+data.live_provider:'',liveSupported?'':(data.live_reason||'')+' · 定时刷新'].filter(Boolean).join(' · '),basis:data.adjustment_label||'',notice:data.history_notice||''});
    initialized=true;
    const incoming=pushes.size?mergeBars(data.bars,[...pushes.values()]):data.bars;
    setBars(old=>first?incoming:mergeBars(old,incoming));
    if(first)setHistoryCursor(data.bars[0]?.time||null);
    setLoadedKey(key);setStale(data.stale);setError(data.error||'');
    if(cacheFirst||data.last_success)setCacheSyncTime(data.last_success||0);
    return data.revalidate===true;
   };
   try{
    const revalidate=await read(preferCache);
    if(preferCache&&!stop&&!ws)open();
    if(revalidate&&!stop&&id===requestId)await read(false);
   }catch(e){if(!stop&&id===requestId)setError(String(e))}
   finally{if(pushedDuringLoad===pushes)pushedDuringLoad=null}
  };
  const open=()=>{if(stop||!liveSupported)return;ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/${secureChart?'market/':''}stream?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}`);ws.onopen=()=>{setLive(false);liveRef.current=false};ws.onmessage=e=>{if(stop||currentKey.current!==key)return;const msg=JSON.parse(e.data);if(msg.type==='status'&&msg.live_supported===false){liveSupported=false;setLive(false);return}if(msg.type==='status'&&msg.connected){setLive(true);liveRef.current=true;retryDelay=5000;if(openedOnce)load(true);openedOnce=true}if(msg.type==='heartbeat'){setLive(!!msg.connected);liveRef.current=!!msg.connected}if(msg.type==='bar'&&!historicView.current){if(msg.series_revision&&msg.series_revision!==seriesRevision.current){if(!pushedDuringLoad)void load(true);return}pushedDuringLoad?.set(msg.bar.time,msg.bar);setBars(old=>mergeBars(old,[msg.bar]))}if(msg.type==='error'){setError(msg.message);setLive(false);liveRef.current=false;if(msg.code==='permission_denied'){retryDelay=300000;setStale(true)}}};ws.onclose=()=>{if(stop)return;setLive(false);liveRef.current=false;if(liveSupported)timer=window.setTimeout(open,retryDelay)}};
  const returnLive=(event:Event)=>{if((event as CustomEvent).detail!==index)return;historyGeneration.current++;historyInteraction.current=false;olderBusy.current=false;setLoadingOlder(false);initialized=false;historicView.current=false;pendingHistoryJump.current=null;fittedKey.current='';setHasMore(true);setHistoryError('');load(true)};window.addEventListener('market-return-live',returnLive);
  const force=previousRefresh.current!==version;
  previousRefresh.current=version;
  void load(force,true).then(()=>{if(!stop&&!ws)open()});
  const poll=window.setInterval(()=>{if(document.visibilityState==='visible'&&(isLongPeriod(tile.period)||!liveRef.current))load(true)},300000);
  return()=>{window.removeEventListener('market-return-live',returnLive);historyGeneration.current++;stop=true;controller.abort();clearTimeout(timer);clearInterval(poll);ws?.close()}
 },[key,version]);
 const requestOlder=async(jumpToOlder=false,target?:{from:number;to:number})=>{
  if(olderBusy.current||historyCursor===null||loadedKey!==key)return;
  if(!hasMore&&target===undefined)return;
  olderBusy.current=true;setLoadingOlder(true);setHistoryError('');setHistoryNotice('');
  const requestKey=key,requestGeneration=historyGeneration.current;const stopped=()=>currentKey.current!==requestKey||historyGeneration.current!==requestGeneration;
  try{
   const result=await backfillHistory({before:historyCursor,target:target?.to,stopped,
    fetchPage:async before=>{const r=await fetch(`/api/bars/older?symbol=${encodeURIComponent(tile.symbol)}&period=${tile.period}&mode=${isLongPeriod(tile.period)?'regular':mode}&before=${before}`);const data=await r.json();if(!r.ok)throw Error(data.detail||'加载历史 K 线失败');if(data.series_revision!==seriesRevision.current)throw Error('行情来源或复权基准已更新，请返回实时图表重新加载');return data},
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
   if(data.series_revision!==seriesRevision.current){setHistoryNotice('行情来源或复权基准已更新，请返回实时图表重新加载');return}
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
 const resonanceName=activeIndicators.find(ind=>isChiefResonance(ind.name))?.name;
 const resonanceValues=useMemo(()=>resonanceName&&loadedKey===key&&!inputIssue(filtered,resonanceName,'{}')?compute(filtered,resonanceName,'{}'):null,[resonanceName,loadedKey,key,filtered]);
 const resonanceIndex=resonanceValues?.['共振'].lastIndexOf(1)??-1;
 const resonanceBar=filtered[resonanceIndex];
 const resonanceUnavailable=indicators.some(ind=>isChiefResonance(ind.name)&&appliesTo(ind,index,tile.period)&&!tdxAvailable(ind.name,tile.symbol));
 updateViewport.current=()=>{};
 useEffect(()=>{const candle=candleRef.current;if(!candle||!isUS||isLongPeriod(tile.period)||mode==='regular')return;const primitive=sessionBackground(filtered);candle.attachPrimitive(primitive);return()=>{if(candleRef.current===candle)candle.detachPrimitive(primitive)}},[filtered,key,isUS,mode,tile.period]);
 useEffect(()=>{const candle=candleRef.current;if(!candle||!showExtremes)return;const primitive=visibleExtremeLabels(filtered);candle.attachPrimitive(primitive);return()=>{if(candleRef.current===candle)candle.detachPrimitive(primitive)}},[showExtremes,filtered,key]);
const barTimes=useMemo(()=>filtered.map(b=>b.time),[filtered]);
 const drawingStep=tile.symbol.startsWith('US.')||tile.period!=='240m'?({'1m':60,'5m':300,'15m':900,'30m':1800,'60m':3600,'120m':7200,'240m':14400,'1d':86400,'1w':604800,'1mo':2592000} as Record<Period,number>)[tile.period]:86400;
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
 useEffect(()=>{if(!box.current)return;const chart=createChart(box.current,{autoSize:true,layout:{fontFamily:'Inter, system-ui, sans-serif',fontSize:11,panes:{enableResize:true}},localization:{timeFormatter:(time:Time)=>typeof time==='number'?displayTime.full.format(time*1000):String(time)},timeScale:{timeVisible:true,secondsVisible:false,tickMarkFormatter:(time:Time,kind:TickMarkType)=>typeof time==='number'?(kind<=TickMarkType.DayOfMonth?displayTime.day.format(time*1000):displayTime.clock.format(time*1000)):null},handleScroll:true,handleScale:true});chartRef.current=chart;const candle=chart.addSeries(CandlestickSeries,candleSeriesOptions(appearance));candleRef.current=candle;const freeCrosshair=document.createElement('div');
  freeCrosshair.className='chart-free-crosshair';
  freeCrosshair.hidden=true;
  freeCrosshair.setAttribute('aria-hidden','true');
  chart.chartElement().append(freeCrosshair);
  const showFreeCrosshair=(x:number|null)=>{
   const scale=chart.timeScale();
   freeCrosshair.hidden=x===null||x<0||x>=scale.width()||chart.options().crosshair.vertLine.visible;
   if(x!==null&&!freeCrosshair.hidden){
    freeCrosshair.style.left=`${chart.priceScale('left').width()+x}px`;
    freeCrosshair.style.bottom=`${scale.height()}px`;
   }
  };
  chartGroup.set(index,{chart,candle,ready:false,suppressSyncUntil:Infinity,showFreeCrosshair,freeCrosshair});
  const cross=(p:MouseEventParams<Time>)=>{
   if(syncingCharts)return;
   setHoverTime(p.point && typeof p.time==='number' && p.seriesData.has(candle) ? p.time : null);
   showFreeCrosshair(p.point?.x??null);
   drawingHover.current(p);
   syncingCharts=true;
   try{
    for(const [id,target] of chartGroup){
     if(id===index)continue;
     const x=p.time===undefined?null:target.chart.timeScale().timeToCoordinate(p.time);
     const price=p.point&&target.ready?target.candle.coordinateToPrice(p.point.y):null;
     if(price!==null&&x!==null&&p.time!==undefined){
      target.chart.setCrosshairPosition(price,p.time,target.candle);
      target.showFreeCrosshair(x);
     }else{
      target.chart.clearCrosshairPosition();
      target.showFreeCrosshair(null);
     }
    }
   }finally{syncingCharts=false}
  };
  const range=(r:any)=>{updateViewport.current(r);const source=chartGroup.get(index);if(syncingCharts||!r||!source?.ready||!historyInteraction.current||performance.now()<source.suppressSyncUntil)return;syncingCharts=true;try{for(const[id,target]of chartGroup){if(id!==index&&target.ready){target.suppressSyncUntil=performance.now()+350;try{target.chart.timeScale().setVisibleRange(r)}catch{}}}}finally{syncingCharts=false}};
  chart.subscribeCrosshairMove(cross);chart.timeScale().subscribeVisibleTimeRangeChange(range);
  return()=>{chart.unsubscribeCrosshairMove(cross);chart.timeScale().unsubscribeVisibleTimeRangeChange(range);chartGroup.delete(index);chart.remove();chartRef.current=null;candleRef.current=null}},[index]);
 useEffect(()=>{
  const light=theme==='light', chart=chartRef.current;
  const entry=chartGroup.get(index);
  if(!chart||!entry)return;
  const axis=light?'#c6d2e1':'#263449';
  const grid=light?'#e7edf5':'#1c283a';
  const crosshair=light?'#61758c':'#6c829d';
  entry.freeCrosshair.hidden=true;
  entry.freeCrosshair.style.borderColor=crosshair;
  chart.applyOptions({
   layout:{background:{color:light?'#ffffff':'#0e1624'},textColor:light?'#41566f':'#9aa9be',panes:{separatorColor:axis}},
   grid:{vertLines:{color:grid},horzLines:{color:grid}},
   crosshair:{mode:CrosshairMode.Normal,vertLine:{color:crosshair,visible:snapCrosshairTime,labelVisible:snapCrosshairTime},horzLine:{color:crosshair}},
   rightPriceScale:{borderColor:axis},
   timeScale:{borderColor:axis},
  });
 },[theme,index,snapCrosshairTime]);
 useEffect(()=>{const candle=candleRef.current;if(!candle)return;candle.applyOptions(candleSeriesOptions(appearance));if(loadedKey!==key)return;candle.setData(filtered.map(x=>({time:toTime(x.time),open:x.open,high:x.high,low:x.low,close:x.close,color:candleBodyColor(x.open,x.close,appearance)})));for(const item of volumeSeries.current){const colors=volumePalette(appearance,item.colors);item.series.setData(filtered.map(x=>({time:toTime(x.time),value:x.volume??undefined,color:volumeColor(x.open,x.close,colors)})))}},[appearance,filtered,key,loadedKey]);
 useEffect(()=>{const chart=chartRef.current,candle=candleRef.current;if(!chart||!candle||loadedKey!==key)return;const data=filtered;const series:ISeriesApi<any>[]=[];const lines:any[]=[];const primitives:ReturnType<typeof trendExtension>[]=[];const signalMarkers:SeriesMarker<Time>[]=[];const macdMarkers:ReturnType<typeof chartSignalMarkers>[]=[];const tdxCleanup:(()=>void)[]=[];const msigPrimitives:ReturnType<typeof msigm8Overlay>[]=[];const sixPrimitives:{series:ISeriesApi<any>;primitive:ReturnType<typeof sixPulsePanel>}[]=[];const sessionPrimitives:{series:ISeriesApi<any>;primitive:ReturnType<typeof sessionBackground>}[]=[];
  const levelPrimitives:ReturnType<typeof sixPulseLevelsOverlay>[]=[];
  if(!drawingsHidden){
   for(const item of drawings){const style=drawingStyle(item,'horizontal');if(!style.visible)continue;const selected=selectedDrawing?.kind==='horizontal'&&selectedDrawing.id===item.id;lines.push(candle.createPriceLine({price:item.price,color:style.color,lineWidth:(selected?Math.min(4,style.lineWidth+2):style.lineWidth) as 1|2|3|4,lineStyle:style.lineStyle,axisLabelVisible:true,title:`${selected?'✓ ':''}水平线 ${drawings.indexOf(item)+1}`}))}
   for(const trend of trends){const style=drawingStyle(trend,'trend');if(!style.visible||trend.points.length!==2)continue;const selected=selectedDrawing?.kind==='trend'&&selectedDrawing.id===trend.id;const shown=dragState.current?.id===trend.id?dragState.current.draft:trend;const primitive=trendExtension(shown,selected,time=>drawingTimeCoordinate(chart,time,barTimes,drawingStep));candle.attachPrimitive(primitive);primitives.push(primitive);trendVisuals.current.set(trend.id,primitive)}
   for(const fib of fibos){const style=drawingStyle(fib,'fib');if(!style.visible)continue;const selected=selectedDrawing?.kind==='fib'&&selectedDrawing.id===fib.id;for(const level of fibPrices(fib))lines.push(candle.createPriceLine({price:level.price,color:level.color,lineWidth:(selected?Math.min(4,style.lineWidth+2):style.lineWidth) as 1|2|3|4,lineStyle:style.lineStyle,axisLabelVisible:[0,.5,.618,1].includes(level.ratio),title:`${selected?'✓ ':''}Fib ${fibos.indexOf(fib)+1} ${(level.ratio*100).toFixed(1)}%`}))}
  }
  let pane=1;let indicatorIssue='';for(const ind of activeIndicators){let values:Record<string,(number|null)[]>;try{
   if(ind.name==='ORB5')continue;
   const issue=inputIssue(filtered,ind.name,ind.params);
   if(issue)throw Error(issue);
   if(ind.name==='PYTHON'){
    const result=pythonResults[ind.id];if(!result)continue;
    const times=new Map(result.time.map((time,i)=>[time,i]));
    values=Object.fromEntries(Object.entries(result.values).map(([name,row])=>[name,filtered.map(bar=>{const i=times.get(bar.time);return i===undefined?null:row[i]??null})]));
   }else values=ind.name===resonanceName&&resonanceValues?resonanceValues:compute(filtered,ind.name,ind.params);
  }catch(e){indicatorIssue+=[indicatorIssue?'；':'',ind.title||ind.name,'：',e instanceof Error?e.message:String(e)].join('');continue}const overlay=indicatorPane(ind)==='main';const target=overlay?0:pane++;const effectiveColors=ind.name==='VOLUME'?volumePalette(appearance,ind.colors):ind.colors;
   if(drawTdx(chart,filtered,ind,values,target,series,signalMarkers,tdxCleanup))continue;
   if(ind.name==='MSIGM8'){const primitive=msigm8Overlay(filtered,values,ind.colors);candle.attachPrimitive(primitive);msigPrimitives.push(primitive);continue}
   if(ind.name==='SIXPULSE_SIGNAL'){
    const input=JSON.parse(ind.params);
    if(input.showLevels!==false){const primitive=sixPulseLevelsOverlay(filtered,input,candle.options().priceFormat.minMove,ind.colors);candle.attachPrimitive(primitive);levelPrimitives.push(primitive)}
    for(let i=0;i<filtered.length;i++)for(const side of ['ENTRY','EXIT'] as const)if(values[side][i]===1){const entry=side==='ENTRY';signalMarkers.push({time:toTime(filtered[i].time),position:entry?'belowBar':'aboveBar',shape:entry?'arrowUp':'arrowDown',color:selectedColor(ind.colors,entry?'entry':'exit',entry?'#ef5350':'#26a69a'),id:`${ind.id}:${side}:${filtered[i].time}`})}
    continue;
   }
   if(ind.name==='SIXPULSE'){
    const s=chart.addSeries(LineSeries,{lineVisible:false,crosshairMarkerVisible:false,lastValueVisible:false,priceLineVisible:false,autoscaleInfoProvider:()=>({priceRange:{minValue:-.7,maxValue:8}}),priceFormat:{type:'custom',minMove:1,formatter:()=>''}},target);
    s.setData(filtered.map(b=>({time:toTime(b.time),value:3.5})));s.priceScale().applyOptions({autoScale:true,scaleMargins:{top:.04,bottom:.04}});
    const primitive=sixPulsePanel(filtered,values,ind.colors);s.attachPrimitive(primitive);sixPrimitives.push({series:s,primitive});series.push(s);continue;
   }
   const macdParams=ind.name==='MACD'?JSON.parse(ind.params||'{}'):null;
   const showStructure=macdParams!=null&&macdParams.structureHints!==false;
   const plotted=showStructure?{...values,hist:values.hist.map(v=>v===null?null:v*2)}:values;
   Object.entries(plotted).forEach(([label,arr],idx)=>{if((ind.name==='ATR'&&label.startsWith('stop_'))||(ind.name==='SUPERTREND'&&label==='direction'))return;const isHist=label==='hist'||label==='volume';const s=chart.addSeries(isHist?HistogramSeries:LineSeries,{color:selectedColor(ind.colors,label,indicatorDefaultColor(ind.name,label,idx)),lineWidth:2,...(ind.name==='SAR'?{lineVisible:false,pointMarkersVisible:true,pointMarkersRadius:2}:{}),priceFormat:['VOLUME','OBV','ADL','PVT','CHO'].includes(ind.name)?{type:'volume'}:{type:'price',precision:3,minMove:0.001},lastValueVisible:idx===0,priceLineVisible:false,title:showStructure?`${ind.title||'定量结构'} ${({macd:'DIF',signal:'DEA',hist:'MACD'} as Record<string,string>)[label]||label}`:ind.title?`${ind.title} ${label}`:/^(EMA|MA)[0-9]+$/.test(label)?label:label==='main'&&['EMA','SMA','WMA','VWMA'].includes(ind.name)?`${ind.name==='SMA'?'MA':ind.name}${JSON.parse(ind.params).period||(['WMA','VWMA'].includes(ind.name)?20:14)}`:`${ind.name} ${label}`},target);if(ind.name==='VOLUME'&&label==='volume')volumeSeries.current.push({series:s,colors:ind.colors});if(target>0&&idx===0&&isUS&&mode!=='regular'&&!isLongPeriod(tile.period)){const primitive=sessionBackground(filtered);s.attachPrimitive(primitive);sessionPrimitives.push({series:s,primitive})}s.setData(arr.flatMap((value,i)=>value===null||!Number.isFinite(value)?[]:[{time:toTime(filtered[i].time),value,...(['MACD','PPO'].includes(ind.name)&&label==='hist'?{color:macdHistogramColor(value,arr[i-1],ind.colors)}:ind.name==='SUPERTREND'?{color:selectedColor(ind.colors,values.direction[i]===1?'up':'down',values.direction[i]===1?'#26a69a':'#ef5350')}:ind.name==='AO'?{color:selectedColor(ind.colors,value>=(arr[i-1]??value)?'rising':'falling',value>=(arr[i-1]??value)?'#26a69a':'#ef5350')}:ind.name==='VOLUME'&&label==='volume'?{color:volumeColor(filtered[i].open,filtered[i].close,effectiveColors)}:{})}]));
    if(macdParams&&label==='macd'&&(showStructure||macdParams.divergences===true)){
     const events=[...(showStructure?macdStructure(filtered,values.macd,values.hist):[]),...(macdParams.divergences===true?macdDivergences(filtered,values.macd):[])].sort((a,b)=>a.index-b.index);
     const light=theme==='light';
     const colors={divergence:light?'#2555a5':'#96bdff',dull:light?'#806100':'#f0cb60',formed:light?'#9b287d':'#f698dd',cleared:light?'#16705a':'#67d6a2'};
     const markers=events.map(({index:i,side,state}):SeriesMarker<Time>=>({
      time:toTime(filtered[i].time),position:side==='top'?'aboveBar':'belowBar',shape:'circle',size:.55,
      color:colors[state],text:macdParams.structureLabels===false?undefined:(side==='top'?'顶':'底')+({dull:'钝化',formed:'结构形成',cleared:'钝化消失',divergence:'背离'})[state],
     }));
     macdMarkers.push(chartSignalMarkers(chart,s,markers));
    }
    series.push(s)})
  }
  signalMarkers.sort((a,b)=>Number(a.time)-Number(b.time));
  const signalPlugin=signalMarkers.length?chartSignalMarkers(chart,candle,signalMarkers):null;
  setFormulaError(indicatorIssue);
  const entry=chartGroup.get(index);if(entry)markViewportReady(entry,data.length>0,performance.now());
  if(data.length&&fittedKey.current!==key){historyInteraction.current=false;if(entry)entry.suppressSyncUntil=performance.now()+350;resetChartViewport(chart,data.length);fittedKey.current=key}
  if(pendingHistoryJump.current){historyInteraction.current=false;if(entry)entry.suppressSyncUntil=performance.now()+350;resetPriceScales(chart);const jump=pendingHistoryJump.current;pendingHistoryJump.current=null;chart.timeScale().setVisibleRange({from:toTime(jump.from),to:toTime(jump.to)})}
  return()=>{if(chartRef.current!==chart)return;volumeSeries.current=[];signalPlugin?.detach();for(const plugin of macdMarkers)plugin.detach();for(const cleanup of tdxCleanup)cleanup();for(const primitive of msigPrimitives)candle.detachPrimitive(primitive);for(const primitive of levelPrimitives)candle.detachPrimitive(primitive);for(const {series,primitive} of sixPrimitives)series.detachPrimitive(primitive);for(const {series,primitive} of sessionPrimitives)series.detachPrimitive(primitive);for(const primitive of primitives)candle.detachPrimitive(primitive);trendVisuals.current.clear();for(const line of lines)candle.removePriceLine(line);for(const s of series)chart.removeSeries(s)}
 },[filtered,activeIndicators,pythonResults,drawings,trends,fibos,drawingsHidden,selectedDrawing,key,loadedKey,resonanceName,resonanceValues,theme]);
 useEffect(()=>{
  const chart=chartRef.current,candle=candleRef.current;if(!chart||!candle||loadedKey!==key||!openingEnabled)return;
  const primitives:ReturnType<typeof openingRangeLines>[]=[];let issue='';
  if(opening.key===key&&opening.data?.status==='ready')for(const ind of activeIndicators.filter(ind=>ind.name==='ORB5'))try{
   const primitive=openingRangeLines(opening.data,ind.params,ind.colors,time=>drawingTimeCoordinate(chart,time,barTimes,drawingStep));
   candle.attachPrimitive(primitive);primitives.push(primitive);
  }catch(e){issue=String(e)}
  setOpeningStyleError(issue);
  return()=>{if(chartRef.current===chart)for(const primitive of primitives)candle.detachPrimitive(primitive)};
 },[filtered,activeIndicators,opening,key,loadedKey,openingEnabled]);
 useEffect(()=>{
  const chart=chartRef.current,candle=candleRef.current;
  if(!chart||!candle||loadedKey!==key||drawingsHidden)return;
  const overlays=measures.filter(line=>line.visible!==false).map(line=>measureLine(line,selectedDrawing?.kind==='measure'&&line.id===selectedDrawing.id,timeToDrawingX,barTimes));
  if(trendStart&&measureAxis){
   measurePreview.current=measureLine({id:'draft',axis:measureAxis,points:[trendStart,trendStart]},false,timeToDrawingX,barTimes);
   overlays.push(measurePreview.current);
  }
  for(const overlay of overlays)candle.attachPrimitive(overlay);
  return ()=>{measurePreview.current=null;if(chartRef.current===chart)for(const overlay of overlays)candle.detachPrimitive(overlay)};
 },[measures,selectedDrawing,trendStart,measureAxis,drawingsHidden,barTimes,drawingStep,loadedKey,key]);
 useEffect(()=>{if(!selectedDrawing)return;const rows=selectedDrawing.kind==='horizontal'?drawings:selectedDrawing.kind==='trend'?trends:selectedDrawing.kind==='measure'?measures:fibos;if(!rows.some(row=>row.id===selectedDrawing.id))setSelectedDrawing(null)},[drawings,trends,fibos,measures,selectedDrawing]);
 useEffect(()=>{setHoverTime(null);setDrawingIssue('');setDraw('off');setTrendStart(null);setDrawingUndo(null);setSelectedDrawing(null);setHoveredDrawing(null);setDateTarget('');setHistoryNotice('')},[key]);
 useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){cancelDrag.current();setDraw('off');setTrendStart(null);setSelectedDrawing(null);setHoveredDrawing(null)}};window.addEventListener('keydown',escape);return()=>window.removeEventListener('keydown',escape)},[]);
 const findDrawing=(p:any)=>{const candle=candleRef.current,chart=chartRef.current;return !candle||!chart||!p.point||drawingsHidden||(p.paneIndex!==undefined&&p.paneIndex!==0)?null:hitTestDrawing(p.point,drawings,trends,fibos,v=>candle.priceToCoordinate(v),timeToDrawingX,measures)};
 const measurePointAt=(point:{x:number;y:number})=>{
  const chart=chartRef.current,candle=candleRef.current;
  if(!chart||!candle||!barTimes.length||loadedKey!==key)return null;
  const logical=chart.timeScale().coordinateToLogical(point.x),price=candle.coordinateToPrice(point.y);
  if(logical===null||price===null||price<=0)return null;
  const index=Math.round(logical),last=barTimes.length-1;
  const time=barTimes[index]??(index<0?barTimes[0]+index*drawingStep:barTimes[last]+(index-last)*drawingStep);
  const rounded=Number(price.toFixed(price>=1?2:4));
  return time>0&&time<=4102444800&&rounded>0?{time,price:rounded}:null;
 };
 drawingHover.current=(p:any)=>{
  if(measurePreview.current&&measureAxis&&trendStart&&p.point&&(p.paneIndex??0)===0){
   const end=measurePointAt(p.point);
   if(end)measurePreview.current.update(measurePoints(measureAxis,trendStart,end));
  }
  const next=draw==='off'?findDrawing(p):null;setHoveredDrawing(old=>old?.id===next?.id&&old?.kind===next?.kind?old:next)};
 const drawingClick=useRef<(p:any)=>void>(()=>{}),drawingPointerStart=useRef<{x:number;y:number}|null>(null);
 drawingClick.current=(p:any)=>{
  const candle=candleRef.current,chart=chartRef.current;if(performance.now()<suppressDrawingClick.current||dragState.current||!candle||!chart||!p.point||(p.paneIndex!==undefined&&p.paneIndex!==0))return;
  if(draw==='off'){setSelectedDrawing(findDrawing(p));return}
  if(p.point.x<0||p.point.x>chart.timeScale().width()||p.point.y<0||p.point.y>chart.panes()[0].getHeight())return;
  if(measureAxis){
   const end=measurePointAt(p.point);if(!end)return;
   if(!trendStart){setTrendStart(end);return}
   const points=measurePoints(measureAxis,trendStart,end);
   if(points[0].time===points[1].time&&points[0].price===points[1].price)return;
   const id=newDrawingId();saveMeasures([...measures,{id,axis:measureAxis,points,...drawingStyle({},'measure')}]);setSelectedDrawing({kind:'measure',id});
   setTrendStart(null);setDraw('off');return;
  }
  const price=candle.coordinateToPrice(p.point.y);if(price===null||Number(price)<=0)return;const drawPrice=Number(Number(price).toFixed(Number(price)>=1?2:4));
  if(draw==='horizontal'){const id=newDrawingId();saveHorizontal([...drawings,{id,price:drawPrice,...drawingStyle({},'horizontal')}]);setSelectedDrawing({kind:'horizontal',id});setDraw('off')}
  else{const samples=barTimes.flatMap(time=>{const x=chart.timeScale().timeToCoordinate(toTime(time));return x===null?[]:[{time,x}]});const time=typeof p.time==='number'?p.time:drawingTimeAtX(p.point.x,samples,drawingStep,chart.timeScale().options().barSpacing);if(time===null)return;const point={time,price:drawPrice};if(!trendStart)setTrendStart(point);else if(point.time!==trendStart.time){record();if(draw==='fib'){const id=newDrawingId();onFibos([...fibos,{id,points:[trendStart,point],...drawingStyle({},'fib')}]);setSelectedDrawing({kind:'fib',id})}else{const id=newDrawingId();onTrend([...trends,{id,points:[trendStart,point],extend:'none' as const,...drawingStyle({},'trend')}]);setSelectedDrawing({kind:'trend',id})}setTrendStart(null);setDraw('off')}}
 };
 useEffect(()=>{const chart=chartRef.current;if(!chart)return;const handler=(p:any)=>drawingClick.current(p);chart.subscribeClick(handler);return()=>chart.unsubscribeClick(handler)},[index]);
 useEffect(()=>{const candle=candleRef.current,chart=chartRef.current;if(!candle||priceBasis==='hfq')return;const lines=depthLines.map(l=>candle.createPriceLine({price:l.price,color:l.side==='buy'?'#42d4a3':'#ff718b',lineWidth:2,lineStyle:l.cached?2:0,axisLabelVisible:true,title:`${l.cached?'缓存':'当前'}挂${l.side==='buy'?'买':'卖'} ${new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(l.qty)}股`}));return()=>{if(chartRef.current===chart)for(const line of lines)candle.removePriceLine(line)}},[depthLines,key,priceBasis]);
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
 const last=loadedKey===key?filtered.at(-1):undefined,previous=filtered.at(-2),change=last&&previous&&previous.close>0?(last.close-previous.close)/previous.close*100:null;
 const hoverIndex=hoverTime===null?-1:barTimes.indexOf(hoverTime);
 const quoteIndex=hoverIndex>=0?hoverIndex:filtered.length-1;
 const quoteBar=loadedKey===key?filtered[quoteIndex]:undefined;
 const priorClose=filtered[quoteIndex-1]?.close;
 const quoteChange=quoteBar && priorClose>0 ? (quoteBar.close-priorClose)/priorClose*100 : null;
 const hint=draw==='off'?'':draw==='horizontal'?'点击价格':!trendStart?'点击起点':'点击终点';
 const candleReadout=<div className="candle-readout" role="group" aria-label={hoverIndex>=0?'所指 K 线行情':'最新 K 线行情'}>

  {quoteBar&&<time>{quoteBar.trade_date}{!isLongPeriod(tile.period)&&' '+displayTime.clock.format(quoteBar.time*1000)}</time>}
  <span>开 <b>{quoteBar?.open.toFixed(2)??'—'}</b></span>
  <span>高 <b>{quoteBar?.high.toFixed(2)??'—'}</b></span>
  <span>低 <b>{quoteBar?.low.toFixed(2)??'—'}</b></span>
  <span>收 <b>{quoteBar?.close.toFixed(2)??'—'}</b></span>
  <span title="相对上一根 K 线收盘价的涨跌幅">涨跌幅 <b style={{color:quoteChange?quoteChange>0?appearance.upColor:appearance.downColor:undefined}}>{quoteChange===null?'—':`${quoteChange>0?'+':''}${quoteChange.toFixed(2)}%`}</b></span>
  {hint&&<span role="status" className="draw-instruction">{hint} · Esc 取消</span>}
 </div>;
 const resetView=()=>{const chart=chartRef.current;if(!chart||loadedKey!==key)return;historyInteraction.current=false;const entry=chartGroup.get(index);if(entry)entry.suppressSyncUntil=performance.now()+350;resetChartViewport(chart,filtered.length)};
 const locateResonance=()=>{
  if(!resonanceBar||loadedKey!==key)return;
  const from=Math.max(0,resonanceIndex-25);
  historyInteraction.current=true;
  chartRef.current?.timeScale().setVisibleLogicalRange({from,to:Math.min(filtered.length+3,Math.max(resonanceIndex+10,from+35))});
 };
 const resonanceInfo=resonanceUnavailable?<div className="chart-resonance-info">主力共振仅用于个股价量分析，此标的暂不显示。</div>:resonanceName?<div className="chart-resonance-info" aria-label="主力共振图例">
  <strong>主力共振</strong>
  {activeIndicators.some(ind=>ind.name==='CHIEF_RESONANCE')&&<span><i style={{background:resonanceColors.strong}}/>金线＝动能 · 金点＝放量突破</span>}
  {activeIndicators.some(ind=>ind.name==='CHIEF_RESONANCE_PANE')&&<>
   <span><i style={{background:resonanceColors.below}}/>低于 0%</span><span><i style={{background:resonanceColors.neutral}}/>0–5%</span><span><i style={{background:resonanceColors.strong}}/>超过 5%</span>
  </>}
  <span><i style={{background:resonanceColors.buy}}/>共振买点</span>
  {resonanceBar?<button type="button" onClick={locateResonance}>定位最近买点 · {resonanceBar.trade_date}{!isLongPeriod(tile.period)&&` ${((isUS?etClock:cnClock).format(resonanceBar.time*1000))}`}</button>:<span>{resonanceValues?.['共振'].includes(0)?'已载入 K 线暂无共振':'等待有效量价数据'}</span>}
 </div>:null;
 const toolsList={off:'选择',horizontal:'水平线',trend:'趋势线',fib:'斐波那契',measureTime:'水平测量',measurePrice:'垂直测量'} as const;
 const startTool=(tool:typeof draw)=>{
  setDraw(tool);setTrendStart(null);setSelectedDrawing(null);
  if(tool!=='off')onDrawingsHidden(false);
 };
 const currentCopy=():DrawingCopy|null=>{
  if(!selectedDrawing)return null;
  const {kind,id}=selectedDrawing;
  switch(kind){
   case 'horizontal':{const item=drawings.find(v=>v.id===id);return item?{kind,item}:null}
   case 'trend':{const item=trends.find(v=>v.id===id);return item?{kind,item}:null}
   case 'fib':{const item=fibos.find(v=>v.id===id);return item?{kind,item}:null}
   case 'measure':{const item=measures.find(v=>v.id===id);return item?{kind,item}:null}
  }
 };
 const copyDrawing=()=>{
  const copy=currentCopy();
  if(!copy)return false;
  setDrawingClipboard({symbol:tile.symbol,copy:structuredClone(copy),count:0});
  return true;
 };
 const pasteDrawing=()=>{
  const clip=drawingClipboard,candle=candleRef.current;
  if(!clip||clip.symbol!==tile.symbol||!candle||loadedKey!==key)return false;
  const {copy}=clip,id=newDrawingId();
  const targetRows={horizontal:drawings,trend:trends,fib:fibos,measure:measures}[copy.kind];
  if(!acceptDrawingRows([...targetRows,{id}]))return false;
  const reference=copy.kind==='horizontal'?copy.item.price:copy.item.points[0].price;
  const y=candle.priceToCoordinate(reference);
  const next=y===null?null:candle.coordinateToPrice(y-12);
  const offset=(next===null?reference*.005:next-reference)*(clip.count+1);
  const shift=(p:TrendPoint)=>({...p,price:p.price+offset});
  switch(copy.kind){
   case 'horizontal':{const rows=[...drawings,{...copy.item,id,price:reference+offset}];saveHorizontal(rows);break}
   case 'trend':{const rows=[...trends,{...copy.item,id,points:copy.item.points.map(shift)}];saveTrends(rows);break}
   case 'fib':{const rows=[...fibos,{...copy.item,id,points:copy.item.points.map(shift)}];saveFibos(rows);break}
   case 'measure':{const points:[TrendPoint,TrendPoint]=[shift(copy.item.points[0]),shift(copy.item.points[1])];const rows=[...measures,{...copy.item,id,points}];saveMeasures(rows);break}
  }
  setDrawingClipboard({...clip,count:clip.count+1});onDrawingsHidden(false);setDraw('off');setSelectedDrawing({kind:copy.kind,id});return true;
 };
 const undoDrawing=()=>{
  if(!drawingUndo)return;
  onDraw(drawingUndo.horizontal);onTrend(drawingUndo.trends);onFibos(drawingUndo.fibos);
  onMeasures(drawingUndo.measures);onDrawingsHidden(drawingUndo.hidden);setSelectedDrawing(null);setDrawingUndo(null);
 };
 const onDrawingKey=(e:React.KeyboardEvent)=>{
  const target=e.target as HTMLElement;
  if(!active||e.defaultPrevented||e.altKey||e.shiftKey||e.nativeEvent.isComposing||target.closest('input,textarea,select,[contenteditable]:not([contenteditable=false]),[role=dialog]'))return;
  if(e.ctrlKey||e.metaKey){
   if(window.getSelection()?.toString())return;
   const key=e.key.toLowerCase();
   if((key==='c'&&copyDrawing())||(key==='v'&&!e.repeat&&pasteDrawing()))e.preventDefault();
  }else if(selectedDrawing&&(e.key==='Delete'||e.key==='Backspace')){
   e.preventDefault();if(!e.repeat)deleteSelectedDrawing();
  }
 };

 const dateControl=<form className="chart-date-jump" aria-label="历史日期定位" onSubmit={e=>{e.preventDefault();if(dateTarget&&!loadingOlder)void jumpToDate()}}>
  <input type="date" aria-label="定位日期" value={dateTarget} onChange={e=>setDateTarget(e.target.value)}/>
  <button type="submit" disabled={!dateTarget||loadingOlder||loadedKey!==key}>{loadingOlder?'定位中':'定位'}</button>
 </form>;
 const tools=<div className="compact-chart-tools" role="toolbar" aria-label="图表工具">
  <ChartMenu label={draw==='off'?'画线':toolsList[draw]} active={draw!=='off'}>
   {(Object.keys(toolsList) as (keyof typeof toolsList)[]).map(tool=><button key={tool} aria-pressed={draw===tool} onClick={()=>startTool(tool)}>{toolsList[tool]}</button>)}
   <hr/>
   <button disabled={!selectedDrawing} onClick={()=>setEditorRequest(n=>n+1)}>编辑选中画线</button>
   <button disabled={!selectedDrawing} onClick={copyDrawing}>复制 <kbd>Ctrl+C</kbd></button>
   <button disabled={drawingClipboard?.symbol!==tile.symbol} onClick={pasteDrawing}>粘贴 <kbd>Ctrl+V</kbd></button>
   <button disabled={!selectedDrawing} onClick={deleteSelectedDrawing}>删除 <kbd>Del</kbd></button>
   <button disabled={!drawingUndo} onClick={undoDrawing}>撤销</button>
  </ChartMenu>
  <DrawingsPanel hidden={drawingsHidden} onHidden={toggleAllDrawings} selected={selectedDrawing} onSelect={setSelectedDrawing} editorRequest={editorRequest} measures={measures} onMeasures={saveMeasures} barTimes={barTimes} horizontal={drawings} trends={trends} fibos={fibos} onHorizontal={saveHorizontal} onTrends={saveTrends} onFibos={saveFibos}/>
  <QuickIndicators indicators={indicators} index={index} period={tile.period} symbol={tile.symbol} onToggle={onIndicatorToggle}/>
  <ChartMenu label="视图">
   <button onClick={()=>{historicView.current=false;setHistoryNotice('');setDateTarget('');window.dispatchEvent(new CustomEvent('market-return-live',{detail:index}))}}>返回实时</button>
   <button disabled={loadedKey!==key||!filtered.length} onClick={resetView}>重置视图</button>
   <button aria-pressed={showExtremes} onClick={()=>{const value=!showExtremes;setShowExtremes(value);try{localStorage.setItem('chart-visible-extremes',value?'on':'off')}catch{}}}>区间高低</button>
  </ChartMenu>
  <button type="button" onClick={()=>setShowPlan(true)}>交易计划</button>
  <button type="button" className="chart-analysis-tool" aria-haspopup="dialog" onClick={()=>onAnalysis(tile,mode)}><Sparkles size={14}/>AI分析</button>
 </div>;
 return <div className={`chart-card ${active?'selected':''}`} tabIndex={0} onFocus={onActivate} onKeyDown={onDrawingKey} onMouseDown={e=>{onActivate();if(box.current?.contains(e.target as Node))e.currentTarget.focus({preventScroll:true})}}><div className="chart-head">
  <div className="instrument-summary">
   <div className="instrument-name"><strong>{chartName}</strong>{chartName!==tile.symbol&&chartName!==tile.symbol.replace('US.','')&&<span>{tile.symbol}</span>}</div>
   <div className="instrument-meta" title={feed.description}>
    <span>{isUS?'美股':'沪深 A 股'}</span><span>{periodLabel(tile.period)}</span>{feed.basis&&<span>{feed.basis}</span>}
    {active&&<span className="multi-chart-active">当前图</span>}
   </div>
   {feed.notice&&<small className="instrument-notice">{feed.notice}</small>}
   {stale&&<span className="warning">NAS 缓存 · 未同步最新行情{cacheSyncTime>0?' · 上次同步 '+new Date(cacheSyncTime*1000).toLocaleString('zh-CN'):''}</span>}
  </div><div className="quote"><strong className={change===null?'':change>=0?'up':'down'}>{last?.close.toFixed(2)||'—'}</strong><span className={change===null?'':change>=0?'up':'down'}>{change===null?'—':(change>0?'+':'')+change.toFixed(2)+'%'}</span></div></div>{active&&dateHost&&createPortal(dateControl,dateHost)}{active&&drawingHost&&createPortal(tools,drawingHost)}{active&&streamHost&&createPortal(<span id="active-chart-stream" className="stream-link" role="img" aria-label={live?'图表行情已连接':'图表行情未实时连接'} title={live?'实时订阅成功':'实时行情未连接；可能正在重试或等待权限'}>{live?<Wifi size={14} className="up"/>:<WifiOff size={14} className="down"/>}</span>,streamHost)}{active&&isUS&&<MarketFlowPanel key={tile.symbol} symbol={tile.symbol}/>}{isUS&&priceBasis==='hfq'&&depthLines.length>0&&<span className="warning">盘口使用实际报价，后复权图隐藏盘口价格线</span>}{isUS&&<DepthPanel symbol={tile.symbol} onLines={setDepthLines} settingsHost={depthHost}/>}
{showPlan&&<Suspense fallback={<p role="status">正在打开交易计划…</p>}><ChartPlanDialog market={isUS?'US':'CN'} symbol={tile.symbol} period={tile.period} mode={mode} indicators={activeIndicators} bars={filtered} stockName={stockName} onClose={()=>setShowPlan(false)}/></Suspense>}{resonanceInfo}{(drawingIssue||error||formulaError||pythonError||(openingEnabled&&(openingStyleError||(opening.key===key&&opening.error))))&&<div className="chart-error">{[drawingIssue,error,formulaError,pythonError,openingEnabled&&(openingStyleError||opening.error)].filter(Boolean).join('；')}</div>}{candleReadout}<div title={hint?`${toolsList[draw]} · ${hint} · Esc 取消`:selectedDrawing?`已选 ${drawingLabel(selectedDrawing)}`:undefined} className={`chart-canvas ${draw!=='off'?'drawing-mode':hoveredDrawing?'drawing-hit':''} ${draggingTrend?'trend-dragging':hoveredHandle?'trend-handle-hover':''}`} ref={box} style={activeIndicators.some(ind=>tdxCatalog[ind.name])?{height:320+150*activeIndicators.filter(ind=>indicatorPane(ind)==='separate').length,minHeight:320+150*activeIndicators.filter(ind=>indicatorPane(ind)==='separate').length}:undefined} onClickCapture={createDrawingFromClick} onPointerDownCapture={startTrendDrag} onPointerMoveCapture={moveTrendDrag} onPointerUpCapture={e=>endTrendDrag(e,true)} onPointerCancelCapture={e=>endTrendDrag(e,false)} onLostPointerCapture={()=>{if(dragState.current)cancelDrag.current()}} onPointerLeave={()=>{setHoverTime(null);setHoveredDrawing(null);setHoveredHandle(false)}} onPointerDown={()=>{historyInteraction.current=true}} onWheel={()=>{historyInteraction.current=true}}/><div className="chart-foot"><span>NAS 缓存 · {filtered.length} 根 K 线{live?' · 实时更新中':''}</span><button className="older-button" disabled={!hasMore||loadingOlder||historyCursor===null} onClick={()=>void requestOlder(true)}>{loadingOlder?'加载中…':hasMore?'← 更早 K 线':'已到历史保留范围'}</button><span>{historyError||historyNotice||(openingEnabled&&opening.key===key&&opening.data?.message)}</span></div></div>
}
type Market = 'US' | 'CN';
type WatchGroup = {id:string; name:string; symbols:string[]};
type MarketWorkspace = {
  chartAppearance:CandleAppearance;groups:WatchGroup[]; selectedGroupId:string; layout:number; mode:Mode; tiles:Tile[];
  indicators:Indicator[]; drawings:Record<string,HorizontalDrawing[]>; trends:Record<string,TrendDrawing[]>;fibos:Record<string,FibDrawing[]>;measures:Record<string,MeasureDrawing[]>;drawingsHidden:Record<string,boolean>;
};
type WorkspaceV2 = {activeMarket:Market; markets:Record<Market,MarketWorkspace>};

const baseIndicators:Indicator[] = [
  {id:'volume',name:'VOLUME',params:'{"period":20}',visible:true},
  {id:'vwap',name:'VWAP',params:'{"reset":"session"}',visible:true},
  {id:'macd',name:'MACD',params:'{"fast":12,"slow":26,"signal":9}',visible:true},
  {id:'bbi',name:'BBI',params:'{"periods":[3,6,12,24]}',visible:true},
];
const freshMarket = (market:Market):MarketWorkspace => ({
  chartAppearance:defaultCandleAppearance(market),
  groups:[{id:'featured',name:'精选',symbols:market==='US'?['US.SNDK','US.SNXX','US.SNDQ']:[]}],
  selectedGroupId:'featured',layout:1,mode:market==='US'?'all':'regular',
  tiles:market==='US'?
    [{symbol:'US.SNDK',period:'5m'},{symbol:'US.SNXX',period:'15m'},{symbol:'US.SNDQ',period:'60m'},{symbol:'US.SNDK',period:'1m'}]:
    [{symbol:'SH.600519',period:'5m'},{symbol:'SZ.000001',period:'15m'},{symbol:'SH.600519',period:'60m'},{symbol:'SZ.000001',period:'1m'}],
  indicators:baseIndicators.map(x=>({...x})),drawings:{},trends:{},fibos:{},measures:{},drawingsHidden:{},
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
    ...base,chartAppearance:normalizeCandleAppearance(raw?.chartAppearance,market),groups,selectedGroupId:groups.some(g=>g.id===raw?.selectedGroupId)?raw.selectedGroupId:'featured',
    layout:[1,2,4].includes(raw?.layout)?raw.layout:1,
    mode:market==='CN'?'regular':(['all','extended','regular'].includes(raw?.mode)?raw.mode:base.mode),
    tiles:tiles.length?tiles:base.tiles,
    indicators:Array.isArray(raw?.indicators)?raw.indicators.filter((ind:Indicator)=>tdxAvailable(ind.name,market)).map((ind:Indicator)=>Array.isArray(ind.periods)&&((ind.periods.length===6&&['1m','5m','15m','30m','60m','1d'].every(p=>ind.periods!.includes(p)))||(ind.periods.length===8&&['1m','5m','15m','30m','60m','1d','1w','1mo'].every(p=>ind.periods!.includes(p))))?{...ind,periods:[...periods]}:ind):base.indicators,
    drawings:normalizeDrawingRecords(raw?.drawings,'horizontal'),
    trends:normalizeDrawingRecords(raw?.trends,'trend'),
    fibos:normalizeDrawingRecords(raw?.fibos,'fib'),
    measures:normalizeDrawingRecords(raw?.measures,'measure'),
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
 for(const market of ['US','CN'] as Market[]){const value=raw.markets[market];if(!value)continue;markets[market]={...markets[market],drawings:normalizeDrawingRecords(value.drawings,'horizontal'),trends:normalizeDrawingRecords(value.trends,'trend'),fibos:normalizeDrawingRecords(value.fibos,'fib'),measures:normalizeDrawingRecords(value.measures,'measure'),drawingsHidden:value.drawingsHidden||{}}}
 return {...current,markets};
}
function App({onSessionEnd}:{onSessionEnd?:()=>void}={}){
  const [workspaceView,setWorkspaceView]=useState<'chart'|'radar'|'emotion'|'scanner'|'api'|'review'>(()=>{const view=new URLSearchParams(location.search).get('view');return view==='review'?'review':view==='api'?'api':'chart'});
  const showReview=workspaceView==='review',showApi=workspaceView==='api',showScanner=workspaceView==='scanner',showRadar=workspaceView==='radar'||workspaceView==='emotion';
  const [emotionBoard,setEmotionBoard]=useState<RadarItem|null>(null);
  const [scanSelection,setScanSelection]=useState<{id:string;name:string;symbols:string[]}|null>(null);
  const [showStrategies,setShowStrategies]=useState(new URLSearchParams(location.search).get('strategy')==='1');
  const [manageGroups,setManageGroups]=useState(false);
  const groupRail=useRef<HTMLDivElement>(null);
  const [tradeDock,setTradeDock]=useState(secureChart&&new URLSearchParams(location.search).has('symbol')&&new URLSearchParams(location.search).has('intent'));
  const [dockRequest,setDockRequest]=useState<{product:'stocks'|'options'}>(()=>({product:new URLSearchParams(location.search).get('intent')==='options'?'options':'stocks'}));
  const [dockSymbol,setDockSymbol]=useState(new URLSearchParams(location.search).get('symbol')||'US.SNDK');
  const tradeDockRef=useRef<HTMLElement>(null);
  useEffect(()=>{if(tradeDock)tradeDockRef.current?.scrollIntoView({block:'start'})},[tradeDock,dockRequest]);
  const [appearanceMarket,setAppearanceMarket]=useState<Market>('US');
  const [settingsTab,setSettingsTab]=useState<SettingsTab|null>(()=>{
    const tab=new URLSearchParams(location.search).get('settings');
    if (tab==='agents'||tab==='plans') return 'agents';
    return tab==='notifications'?'notifications':tab==='connection'?'connection':null;
  }),[depthHost,setDepthHost]=useState<HTMLDivElement|null>(null);
 const [drawingClipboard,setDrawingClipboard]=useState<DrawingClipboard>(null);
 const [streamHost,setStreamHost]=useState<HTMLSpanElement|null>(null);
 const [dateHost,setDateHost]=useState<HTMLDivElement|null>(null);
 const [drawingHost,setDrawingHost]=useState<HTMLDivElement|null>(null);
  const [snapCrosshairTime,setSnapCrosshairTime]=useState(()=>{
    try{return localStorage.getItem('chart-snap-crosshair-time-v2')!=='off'}catch{return true}
  });
  const changeCrosshairSnap=(enabled:boolean)=>{
    setSnapCrosshairTime(enabled);
    try{localStorage.setItem('chart-snap-crosshair-time-v2',enabled?'on':'off')}catch{}
  };
 const [watchCollapsed,setWatchCollapsed]=useState(()=>{try{return localStorage.getItem('chart-watch-collapsed')==='yes'}catch{return false}});
 const toggleWatch=()=>{if(matchMedia('(max-width:700px)').matches){setMobileWatchOpen(v=>!v);return}setWatchCollapsed(v=>{try{localStorage.setItem('chart-watch-collapsed',v?'no':'yes')}catch{}return !v})};
  const [mobileWatchOpen,setMobileWatchOpen]=useState(false);
  const [stockNames,setStockNames]=useState<Record<string,string>>({});
  const [tradingUrl,setTradingUrl]=useState(`https://${location.hostname}:8443/trade`);
  useEffect(()=>{fetch('/api/trading-config').then(r=>r.json()).then(c=>{if(c.url?.startsWith('https://'))setTradingUrl(c.url)}).catch(()=>{})},[]);
  const openTrading=(symbol:string,action='overview')=>{if(secureChart){if(action==='strategy')setShowStrategies(v=>!v);else{setDockSymbol(symbol);setDockRequest({product:action==='options'?'options':'stocks'});setTradeDock(true)}return}const url=new URL(tradingUrl);url.pathname='/chart';url.searchParams.set('symbol',symbol);url.searchParams.set('intent',action);if(action==='strategy')url.searchParams.set('strategy','1');location.assign(url.toString())};
  const [state,setState]=useState<WorkspaceV2>(initialV2),[ready,setReady]=useState(false),[active,setActive]=useState(0);
  const [loadError,setLoadError]=useState('');
  const [loadAttempt,setLoadAttempt]=useState(0);
  const [templatesReady,setTemplatesReady]=useState(false);
  const [templateError,setTemplateError]=useState(false);
  const [templateAttempt,setTemplateAttempt]=useState(0);
  const [savedScanGroups,setSavedScanGroups]=useState<Record<Market,string>>({US:'',CN:''});
  const [analysisChart,setAnalysisChart]=useState<AnalysisChart|null>(null);
  const [openedReport,setOpenedReport]=useState<OpenReport|null>(null);
  function showReport(report:OpenReport) {
    setOpenedReport(report);
    setAnalysisChart(report.chart);
  }
  const backgroundReport=useBackgroundReport(showReport);
  function openAnalysis(tile:Tile,mode:Mode){
    const chart:AnalysisChart={...tile,mode:tile.symbol.startsWith('US.')&&!isLongPeriod(tile.period)?mode:'regular'};
    setOpenedReport(null);setAnalysisChart(chart);
  }
  function applyAnalysisDrawings(batch:AnalysisDrawingBatch) {
    if (!analysisChart) return;
    const {symbol,period}=analysisChart;
    const market:Market=symbol.startsWith('US.')?'US':'CN';
    const key=symbol+':'+period;
    let full=false;
    flushSync(()=>setState(previous=>{
      const workspace=previous.markets[market];
      const append=<T extends {id?:string}>(existing:T[], suggestions:T[])=>{
        const ids=new Set(existing.map(line=>line.id));
        return [...existing,...suggestions.filter(line=>!ids.has(line.id))];
      };
      const horizontal=append(workspace.drawings[key]||[],batch.horizontal);
      const trends=append(workspace.trends[key]||[],batch.trends);
      const fibos=append(workspace.fibos[key]||[],batch.fibos);
      full=horizontal.length>100 || trends.length>100 || fibos.length>100;
      if(full) return previous;
      return {...previous,markets:{...previous.markets,[market]:{...workspace,
        drawings:{...workspace.drawings,[key]:horizontal},trends:{...workspace.trends,[key]:trends},
        fibos:{...workspace.fibos,[key]:fibos},
        drawingsHidden:{...workspace.drawingsHidden,[key]:false},
      }}};
    }));
    if(full) throw Error('当前周期的画线已达容量上限，请在画线管理中整理后再添加。');
  }
  const chartLinkApplied=useRef(false);
  useEffect(()=>{
    if(!ready||chartLinkApplied.current)return;
    chartLinkApplied.current=true;
    const query=new URLSearchParams(location.search),symbol=query.get('symbol')||'',period=query.get('period')||'1d';
    if(/^(US\.[A-Z0-9.]{1,12}|(?:SH|SZ)\.(?:\d{6}|(?:BK|LIST)\d{1,10}))$/.test(symbol)&&['1m','5m','15m','30m','60m','120m','240m','1d','1w','1mo'].includes(period)){
      const analysis=query.get('analysis')==='1';
      const session=query.get('mode');
      const mode=analysis&&symbol.startsWith('US.')&&!isLongPeriod(period)&&(session==='all'||session==='extended')?session:'regular';
      openRadar({symbol,name:symbol},period as Period,mode);
      if(analysis){
        setAnalysisChart({symbol,period:period as Period,mode});
        const url=new URL(location.href);url.searchParams.delete('analysis');history.replaceState(null,'',url);
      }
    }
  },[ready]);
  function openRadar(item:RadarItem,period:Period='1d',mode:Mode='regular'){
    const target:Market=item.symbol.startsWith('US.')?'US':'CN';
    setPreviewSymbol(item.symbol);
    setStockNames(names=>({...names,[item.symbol]:item.name}));
    setState(previous=>({...previous,activeMarket:target,markets:{...previous.markets,[target]:{...previous.markets[target],mode,tiles:previous.markets[target].tiles.map((tile,index)=>index===0?{...tile,symbol:item.symbol,period}:tile)}}}));
    setActive(0);setWorkspaceView('chart');
  }
  function favoriteRadar(item:RadarItem){
    const target:Market=item.symbol.startsWith('US.')?'US':'CN';
    setStockNames(names=>({...names,[item.symbol]:item.name}));
    setState(previous=>{
      const workspace=previous.markets[target];
      const existing=workspace.groups.find(group=>group.id==='radar-favorites');
      const symbols=existing?.symbols||[];
      const group={id:'radar-favorites',name:'关注板块',symbols:symbols.includes(item.symbol)?symbols.filter(code=>code!==item.symbol):[...symbols,item.symbol]};
      return {...previous,markets:{...previous.markets,[target]:{...workspace,groups:existing?workspace.groups.map(value=>value.id===group.id?group:value):[...workspace.groups,group]}}};
    });
  }
  function scanRadar(name:string,items:RadarItem[]){
    setStockNames(names=>({...names,...Object.fromEntries(items.map(item=>[item.symbol,item.name]))}));
    setScanSelection({id:'radar-selection-'+Date.now(),name,symbols:items.map(item=>item.symbol)});
    setWorkspaceView('scanner');
  }
  const drawingRevision=useRef(0),currentWorkspace=useRef(state),lastSavedWorkspace=useRef(''),workspaceSaving=useRef(false),saveQueue=useRef(Promise.resolve()),syncMounted=useRef(true);
 currentWorkspace.current=state;
 const [drawingSyncNotice,setDrawingSyncNotice]=useState(''),[workspaceRetry,setWorkspaceRetry]=useState(0);const saveRetryCount=useRef(0),saveRetryTimer=useRef<number|undefined>(undefined);
 useEffect(()=>()=>{syncMounted.current=false;clearTimeout(saveRetryTimer.current)},[]);
 const [newSymbol,setNewSymbol]=useState(''),[symbolError,setSymbolError]=useState(''),[previewSymbol,setPreviewSymbol]=useState<string|null>(null);
  const [newGroupName,setNewGroupName]=useState(''),[groupError,setGroupError]=useState('');
  const [importingGroups,setImportingGroups]=useState(false),[importMessage,setImportMessage]=useState('');
  const [editingGroup,setEditingGroup]=useState(''),[groupDraft,setGroupDraft]=useState('');
  const [newIndicator,setNewIndicator]=useState('EMA'),[newIndicatorPane,setNewIndicatorPane]=useState<'main'|'separate'>('main'),[refresh,setRefresh]=useState(0),[status,setStatus]=useState<any>({});
  const [templates,setTemplates]=useState<Record<string,Indicator[]>>({}),[templateName,setTemplateName]=useState('');
  const [customName,setCustomName]=useState(''),[customFormula,setCustomFormula]=useState('EMA(C,12)-EMA(C,26)'),[customInputs,setCustomInputs]=useState('{"fast":12,"slow":26,"signal":9}'),[customLanguage,setCustomLanguage]=useState<'formula'|'python'>('formula'),[customPane,setCustomPane]=useState<'main'|'separate'>('separate'),[customError,setCustomError]=useState('');
  const [quotes,setQuotes]=useState<Record<string,StockQuote>>({}),[quotesStale,setQuotesStale]=useState(false),[quoteError,setQuoteError]=useState('');
  const market=state.activeMarket,ws=state.markets[market];

  const selectedGroup=ws.groups.find(g=>g.id===ws.selectedGroupId)||ws.groups[0];
  const featured=ws.groups.find(g=>g.id==='featured')!;
  const current=ws.tiles[active]||ws.tiles[0];
  const drawingViews=useMemo(()=>ws.tiles.map(tile=>({horizontal:drawingsForPeriod(ws.drawings,tile.symbol,tile.period),trends:drawingsForPeriod(ws.trends,tile.symbol,tile.period),fibos:drawingsForPeriod(ws.fibos,tile.symbol,tile.period),measures:drawingsForPeriod(ws.measures,tile.symbol,tile.period)})),[ws.drawings,ws.trends,ws.fibos,ws.measures,ws.tiles]);
  const quoteSymbols=selectedGroup.symbols.join(',');
  useEffect(()=>{
    if(!ready||market!=='CN'||!quoteSymbols)return;
    const controller=new AbortController();
    const read=async(codes:string[],preferCache:boolean)=>{
      const r=await fetch('/api/symbols/names?symbols='+encodeURIComponent(codes.join(','))+(preferCache?'&prefer_cache=true':''),{signal:controller.signal});
      if(!r.ok)throw Error('名称读取失败');
      const data=await r.json();
      if(!controller.signal.aborted)setStockNames(old=>({...old,...data.names}));
      return data.missing as string[]|undefined;
    };
    const symbols=quoteSymbols.split(',');
    for(let i=0;i<symbols.length;i+=100){
      void read(symbols.slice(i,i+100),true).then(missing=>{
        if(missing?.length&&!controller.signal.aborted)return read(missing,false);
      }).catch(()=>{});
    }
    return ()=>controller.abort();
  },[ready,market,quoteSymbols]);

  useEffect(()=>{
    setQuotes({});setQuotesStale(false);setQuoteError('');
    if(!ready||!quoteSymbols)return;
    let cancelled=false,busy=false;
    const controller=new AbortController();
    const load=()=>{
      if(busy||document.visibilityState!=='visible')return;
      busy=true;
      const chunks=selectedGroup.symbols.reduce<string[][]>((all,s,i)=>{if(i%100===0)all.push([]);all[all.length-1].push(s);return all},[]);
      Promise.all(chunks.map(async chunk=>{
        const r=await fetch(`/api/quotes?symbols=${encodeURIComponent(chunk.join(','))}`,{signal:controller.signal});
        if(!r.ok)throw Error((await r.json()).detail||'快照不可用');
        return r.json();
      }))
        .then(data=>{if(!cancelled){setQuotes(Object.fromEntries(data.flatMap(x=>x.quotes as StockQuote[]).map((q:StockQuote)=>[q.symbol,q])));setQuotesStale(data.some(x=>x.stale));setQuoteError('')}})
        .catch(e=>{if(!cancelled)setQuoteError(String(e.message||e))}).finally(()=>{busy=false});
    };
    load();
    const timer=setInterval(load,20000);
    document.addEventListener('visibilitychange',load);
    return()=>{cancelled=true;controller.abort();clearInterval(timer);document.removeEventListener('visibilitychange',load)};
  },[ready,market,selectedGroup.id,quoteSymbols]);

  useEffect(()=>{
    const controller=new AbortController();
    setLoadError('');
    fetch('/api/settings/workspace',{signal:controller.signal}).then(async r=>{
      if(!r.ok)throw Error('工作区读取失败');
      const data=await r.json();
      if(!data.value||typeof data.value!=='object'||Array.isArray(data.value))throw Error('工作区数据无效');
      if(controller.signal.aborted)return;
      const restored=restoreWorkspace(data.value);
      drawingRevision.current=Number(data.drawing_revision)||0;
      const groups={US:JSON.stringify(restored.markets.US.groups),CN:JSON.stringify(restored.markets.CN.groups)};
      const groupsOnDisk=data.value.markets;
      if(JSON.stringify(groupsOnDisk?.US?.groups)===groups.US&&JSON.stringify(groupsOnDisk?.CN?.groups)===groups.CN){
        lastSavedWorkspace.current=JSON.stringify(restored);
        setSavedScanGroups(groups);
      }
      setState(restored);setReady(true);
    }).catch(()=>{if(!controller.signal.aborted)setLoadError('工作区读取失败，请重试。')});
    return ()=>controller.abort();
  },[loadAttempt]);
  useEffect(()=>{
    const controller=new AbortController();
    setTemplateError(false);
    fetch('/api/settings/templates',{signal:controller.signal}).then(async r=>{
      if(!r.ok)throw Error('模板读取失败');
      const data=await r.json();
      if(!data.value||typeof data.value!=='object'||Array.isArray(data.value))throw Error('模板数据无效');
      if(!controller.signal.aborted){setTemplates(data.value);setTemplatesReady(true)}
    }).catch(()=>{if(!controller.signal.aborted)setTemplateError(true)});
    return ()=>controller.abort();
  },[templateAttempt]);
  useEffect(()=>{
    let stopped=false;
    const loadStatus=()=>fetch('/api/status?market='+market).then(r=>r.json()).then(s=>{if(!stopped)setStatus(s)}).catch(()=>{});
    loadStatus();
    const t=setInterval(loadStatus,5000);
    return()=>{stopped=true;clearInterval(t)};
  },[market]);
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
        const US=JSON.stringify(snapshot.markets.US.groups),CN=JSON.stringify(snapshot.markets.CN.groups);
        setSavedScanGroups(old=>old.US===US&&old.CN===CN?old:{US,CN});
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
      const r=await fetch('/api/watchlists/import?market='+market,{method:'POST'});
      const data=await r.json();
      if(!r.ok)throw Error(data.detail||'读取失败');
      setState(restoreWorkspace(data.value));
      setImportMessage(`已导入：美股 ${data.summary.US.groups} 组 / ${data.summary.US.symbols} 只，A 股 ${data.summary.CN.groups} 组 / ${data.summary.CN.symbols} 只`);
    }catch(e:any){setImportMessage(String(e.message||e))}
    finally{setImportingGroups(false)}
  };
  const switchMarket=(next:Market)=>{
    setScanSelection(null);
    if(next===market)return;
    setState(old=>{
      const target=old.markets[next];
      const group=target.groups.find(g=>g.id===target.selectedGroupId)||target.groups[0];
      const primary=target.tiles[0];
      const symbol=group.symbols.includes(primary.symbol)?primary.symbol:group.symbols[0]||freshMarket(next).tiles[0].symbol;
      const workspace=symbol===primary.symbol?target:{...target,tiles:[{...primary,symbol},...target.tiles.slice(1)]};
      return {...old,activeMarket:next,markets:{...old.markets,[next]:workspace}};
    });
    setActive(0);setNewSymbol('');setSymbolError('');setPreviewSymbol(null);
  };
  const selectGroup=(id:string)=>{
    updateMarket(w=>{const g=w.groups.find(x=>x.id===id);return g?{...w,selectedGroupId:id,tiles:w.tiles.map((t,i)=>g.symbols.length?{...t,symbol:g.symbols[i%g.symbols.length]}:t)}:w});
    setActive(0);
  };
  const normalizeSymbol=(input:string)=>{
    let s=input.trim().toUpperCase();
    if(market==='US')s=s.startsWith('US.')?s:`US.${s}`;
    // Bare CN codes must be resolved by the directory: 000001 is ambiguous.
    return belongs(s,market)&&(market==='US'?/^US\.[A-Z0-9.]{1,12}$/.test(s):/^(SH|SZ)\.(?:\d{6}|(?:BK|LIST)\d{1,10})$/.test(s))?s:null;
  };
  const viewSymbol=(candidate=newSymbol,name?:string)=>{
    const symbol=normalizeSymbol(candidate);if(!symbol){setSymbolError(market==='US'?'请输入 AAPL 或 US.AAPL':'请输入 SH.600519 或 SZ.000001');return}
    if(name)setStockNames(old=>({...old,[symbol]:name}));
    setPreviewSymbol(symbol);
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
  const saveTemplate=()=>{if(!templatesReady||!templateName.trim())return;const next={...templates,[templateName.trim()]:ws.indicators};setTemplates(next);fetch('/api/settings/templates',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:next})});setTemplateName('')};
  const patchIndicator=(id:string,patch:Partial<Indicator>)=>updateMarket(w=>({...w,indicators:w.indicators.map(ind=>ind.id===id?{...ind,...patch}:ind)}));
  const selectCustomLanguage=(next:'formula'|'python')=>{
    if(next===customLanguage)return;
    if(next==='python'&&customFormula==='EMA(C,12)-EMA(C,26)')setCustomFormula(pythonExample);
    if(next==='formula'&&customFormula===pythonExample)setCustomFormula('EMA(C,12)-EMA(C,26)');
    setCustomLanguage(next);setCustomError('');
  };

  const hasDepthIndicator=Boolean(current?.symbol.startsWith('US.'));
  const indicatorSettings=<div className="indicator-panel"><div className="settings-section-heading"><h3>主图与副图指标</h3><p>搜索并添加指标；下方可开关显示，点击“设置”调整参数。</p></div><IndicatorPicker onConfigureDepth={hasDepthIndicator?()=>{
    const options=depthHost?.querySelector('details');
    if(options){options.open=true;options.querySelector('summary')?.focus()}
  }:undefined} marketLabel={market==='CN'?'A 股':'美股'} names={names.filter(name=>tdxAvailable(name,market)&&(name!=='INSTITUTION_TREND'||status.historical_chips===true))} value={newIndicator} pane={newIndicatorPane} onSelect={name=>{setNewIndicator(name);setNewIndicatorPane(indicatorPane({name}))}} onPaneChange={setNewIndicatorPane} onAdd={(name,pane)=>updateMarket(w=>({...w,indicators:[...w.indicators,{id:`i-${Date.now()}-${Math.random().toString(36).slice(2)}`,name,title:name==='MSIGM8'?'MACD突破':undefined,pane,params:JSON.stringify(indicatorDefaults[name]||{}),visible:true}]}))}/><div className="indicator-list">{(['main','separate'] as const).map(pane=><section className="indicator-pane-group" key={pane}><h3>{pane==='main'?'主图叠加指标':'独立副图指标'} <small>{ws.indicators.filter(ind=>indicatorPane(ind)===pane).length+Number(pane==='main'&&hasDepthIndicator)}</small></h3>
  {pane==='main'&&hasDepthIndicator&&<div ref={setDepthHost}/>}
  {ws.indicators.filter(ind=>indicatorPane(ind)===pane).map(ind=><IndicatorSettings key={ind.id} indicator={ind} onPatch={patch=>patchIndicator(ind.id,patch)} onDelete={()=>updateMarket(w=>({...w,indicators:w.indicators.filter(x=>x.id!==ind.id)}))}/>)}{!(pane==='main'&&hasDepthIndicator)&&!ws.indicators.some(ind=>indicatorPane(ind)===pane)&&<p className="settings-empty">暂无此类指标，可从上方添加。</p>}</section>)}</div><details className="indicator-advanced-tools"><summary>自定义指标与模板</summary><div className="custom-editor"><h3>新建自定义指标</h3>
  <div className="custom-language" role="tablist" aria-label="自定义指标语言"><button role="tab" aria-selected={customLanguage==='formula'} className={customLanguage==='formula'?'chosen':''} onClick={()=>selectCustomLanguage('formula')}>简易公式</button><button role="tab" aria-selected={customLanguage==='python'} className={customLanguage==='python'?'chosen':''} onClick={()=>selectCustomLanguage('python')}>Python</button></div>
  <input placeholder="名称，如双均线差" value={customName} onChange={e=>setCustomName(e.target.value)}/>
  <textarea aria-label={customLanguage==='python'?'Python 指标代码':'指标公式'} value={customFormula} onChange={e=>setCustomFormula(e.target.value)} spellCheck={false}/>
  {customLanguage==='python'&&<label className="custom-inputs-label">参数默认值（JSON）<input aria-label="Python 参数默认值" value={customInputs} onChange={e=>setCustomInputs(e.target.value)} spellCheck={false}/></label>}
  <div className="custom-options"><select value={customPane} onChange={e=>setCustomPane(e.target.value as 'main'|'separate')}><option value="separate">独立副图</option><option value="main">叠加主图</option></select><button onClick={addCustom}><Plus size={14}/> 添加</button></div>
  <small>{customLanguage==='python'?'Python：示例用 PARAMS["fast"] 等读取可调参数；支持 O/H/L/C/V、SMA、EMA、REF、HHV、LLV、math 和 statistics。添加后可直接调整参数数值；语法错误显示在此，运行错误显示在图表。':'简易公式：支持 O/H/L/C/V、SMA、EMA、REF、HHV、LLV、ABS、MAX、MIN 和四则运算。'}</small>
  {customError&&<p className="custom-error">{customError}</p>}
</div><div className="template"><h3>指标模板</h3>{templateError&&<button onClick={()=>setTemplateAttempt(n=>n+1)}>模板读取失败，重试</button>}<div className="template-save"><input placeholder="模板名称" value={templateName} onChange={e=>setTemplateName(e.target.value)}/><button disabled={!templatesReady} onClick={saveTemplate}><Save size={14}/> 保存</button></div>{Object.entries(templates).map(([name,value])=><button className="template-item" key={name} onClick={()=>updateMarket(w=>({...w,indicators:value}))}>{name} <span>{value.length} 项</span></button>)}</div></details></div>;
  if(!ready)return <main className="trade-login" role="status">{loadError||'正在读取工作区…'}{loadError&&<button onClick={()=>setLoadAttempt(n=>n+1)}>重新读取</button>}</main>;
  return <div style={{'--market-up':ws.chartAppearance.upColor,'--market-down':ws.chartAppearance.downColor} as CSSProperties} className={`shell chart-workspace ${watchCollapsed?'watch-collapsed':''}`}>
    <header><div className="brand"><div className="brand-mark"><Activity size={20}/></div><div><strong>NAS MARKET</strong><small>私人多市场看盘终端</small></div></div>
      <div className="current-instrument" aria-label="当前查看股票"><span>当前查看</span><strong title={stockNames[current.symbol]||quotes[current.symbol]?.name||current.symbol}>{stockNames[current.symbol]||quotes[current.symbol]?.name||current.symbol.replace('US.','')}</strong><code>{current.symbol}</code><small>图 {active+1} · {periodLabel(current.period)}</small></div>
      <nav className="market-navigation" aria-label="工作区视图">
        <select className="workspace-view-select" aria-label="切换工作区" value={workspaceView} onChange={e=>{setWorkspaceView(e.target.value as typeof workspaceView);if(e.target.value==='scanner')setScanSelection(null);if(e.target.value==='emotion')setEmotionBoard(null)}}>
          <option value="chart">图表</option><option value="radar">板块雷达</option><option value="emotion">市场情绪</option><option value="scanner">条件扫描</option><option value="review">每日复盘</option><option value="api">API 管理</option>
        </select>
        <button aria-pressed={workspaceView==='chart'} onClick={()=>setWorkspaceView('chart')}>图表</button>
        <button aria-pressed={workspaceView==='radar'} onClick={()=>setWorkspaceView('radar')}>板块雷达</button>
        <button aria-pressed={workspaceView==='emotion'} onClick={()=>{setEmotionBoard(null);setWorkspaceView('emotion')}}>市场情绪</button>
        <button aria-pressed={showScanner} onClick={()=>{setScanSelection(null);setWorkspaceView('scanner')}}>条件扫描</button>
        <button aria-pressed={showReview} onClick={()=>setWorkspaceView('review')}>每日复盘</button>
        <button aria-pressed={showApi} onClick={()=>setWorkspaceView('api')}>API 管理</button>
      </nav>
      <div className="workspace-actions"><a className="guide-library-link" href="?view=indicator-guide" target="_blank" rel="noopener" aria-label="指标说明" title="指标说明"><BookOpen size={15} aria-hidden="true"/><span>指标说明</span></a><button className="secondary" aria-label="设置" disabled={!ready} onClick={()=>setSettingsTab('indicators')}><Settings2 size={16}/> 设置</button><div className="layout-picker"><LayoutGrid size={15}/>{[1,2,4].map(n=><button key={n} className={ws.layout===n?'chosen':''} onClick={()=>{setActive(i=>Math.min(i,n-1));updateMarket(w=>({...w,layout:n,tiles:Array.from({length:Math.max(n,w.tiles.length)},(_,i)=>w.tiles[i]||{symbol:w.tiles[0]?.symbol||'US.SNDK',period:(["5m","15m","60m","1d"] as Period[])[i]})}))}}>{n}</button>)}</div></div><div className="header-right"><button className="watch-toggle" aria-label="切换自选侧栏" aria-expanded={!watchCollapsed} onClick={toggleWatch}>自选</button><button className="connection" aria-label="OpenD 连接与登录" aria-describedby="active-chart-stream" title="OpenD 连接与当前图行情订阅" onClick={()=>setSettingsTab('connection')}>{status.opend_connected?<><span className="dot green"/> OpenD 已连接</>:status.last_error?<><span className="dot red"/> OpenD 连接异常</>:<><span className="dot idle"/> OpenD 按需连接</>}<span className="header-stream-host" ref={setStreamHost}/></button><ThemeToggle/><button className="icon-button" aria-label="刷新行情" title="刷新行情" onClick={()=>setRefresh(x=>x+1)}><RotateCw size={17}/></button></div>
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
          <button className="moomoo-import" onClick={importGroups} disabled={importingGroups||status.capabilities?.watchlists===false} title={status.capabilities?.watchlists===false?'当前数据源未提供自选分组':undefined}>{importingGroups?'正在同步…':'从 '+(status.routes?.[market]?.watchlists||'行情源')+' 同步分组'}</button>
          {importMessage&&<div className="quote-notice" title={importMessage}>{importMessage}</div>}
          {groupError&&<div className="side-error">{groupError}</div>}
        </div>}
        <div className="group-label selected-label">股票 · {selectedGroup.name} <span>{selectedGroup.symbols.length}</span></div>
        {quoteError&&<div className="quote-notice" title={quoteError}>报价暂不可用，图表仍可查看</div>}
        {quotesStale&&<div className="quote-notice">报价为上次缓存数据</div>}
        {!selectedGroup.symbols.includes(current.symbol)&&(selectedGroup.symbols.length>0||previewSymbol===current.symbol)&&<div className="preview-instrument" aria-label="临时查看股票"><span>正在查看 · 未加入当前分组</span><strong>{stockNames[current.symbol]||quotes[current.symbol]?.name||current.symbol.replace('US.','')}</strong><div><code>{current.symbol}</code><button onClick={()=>addSymbol(current.symbol,stockNames[current.symbol]||quotes[current.symbol]?.name)}>＋ 加入本组</button></div></div>}
        <div className="symbol-list" role="region" aria-label="自选股票列表" tabIndex={0}>{selectedGroup.symbols.map(s=><div key={s} className={`symbol ${current?.symbol===s?'active':''}`}>
          <button className="stock-select" onClick={()=>{setTile({symbol:s});setMobileWatchOpen(false)}} title={quotes[s]?.update_time?`报价更新：${quotes[s].update_time}`:s}>
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
      <div className="side-bottom"><div className="resource"><span>实时订阅</span><strong>{status.active_streams||0} / {status.max_streams||32}</strong></div><p>行情来源：{status.provider||'加载中'}。美股交易使用独立 HTTPS 入口。</p></div>
    </aside><main className={showRadar||showScanner||showApi||showReview?"workspace-panel-view":undefined}>

      {showApi&&<ApiManagement/>}
      {showReview&&ready&&<Suspense fallback={<p role="status">正在打开每日复盘…</p>}><DailyReview key={market} market={market} currentSymbol={current.symbol} names={stockNames} onMarketChange={switchMarket} onOpen={(symbol,name)=>openRadar({symbol,name})}/></Suspense>}
      {showRadar&&<MarketRadar key={market} market={market} view={workspaceView==='emotion'?'emotion':'radar'} emotionBoard={emotionBoard&&(emotionBoard.symbol.startsWith('US.')?'US':'CN')===market?emotionBoard:null} onShowEmotion={item=>{setEmotionBoard(item);setWorkspaceView('emotion')}} favorites={ws.groups.filter(g=>g.id==='radar-favorites').flatMap(g=>g.symbols)} onFavorite={favoriteRadar} onOpen={openRadar} onScan={scanRadar}/>}
      {showScanner&&<ScannerPanel key={market+":"+(scanSelection?.id||'watchlists')} market={market} groups={[...ws.groups.map(g=>({...g,id:market+":"+g.id})),...(scanSelection?[scanSelection]:[])]} savedGroups={savedScanGroups[market]} initialScope={scanSelection?.id} names={stockNames} onClose={()=>setWorkspaceView('chart')} onOpen={(symbol,period)=>openRadar({symbol,name:stockNames[symbol]||symbol},period as Period)}/>}
      <div className="chart-view" hidden={showRadar||showScanner||showApi||showReview}>



      {market==='CN'&&status.permission_errors?.CN&&<div className="market-permission-note" role="status"><strong>A 股实时行情权限不足</strong><span>继续显示 NAS 已有历史数据。请在 OpenD 检查 A 股行情授权及登录网络地区；moomoo App 的权限不一定等同于 API。</span><button onClick={async()=>{await fetch('/api/quote/retry?symbol='+encodeURIComponent(current?.symbol||'SH.600584'),{method:'POST'});setRefresh(x=>x+1)}}>已检查权限，重试</button></div>}
      <div className="toolbar chart-command-bar">
       <PeriodSwitcher current={current.period} onSelect={period=>setTile({period})}/>
       <div className="chart-date-host" ref={setDateHost}/>
       <div className="toolbar-section market-session">{market==='US'?<select aria-label="图表交易时段" title="美东时间" disabled={isLongPeriod(current.period)} value={isLongPeriod(current.period)?'regular':ws.mode} onChange={e=>updateMarket(w=>({...w,mode:e.target.value as Mode}))}>
        <option value="all">24H 全时段</option><option value="extended">盘前盘后</option><option value="regular">常规时段</option>
       </select>:<small title="沪深常规交易时段">北京时间</small>}</div>
       <div className="workspace-drawing-host" ref={setDrawingHost}/>
      </div>
      {drawingSyncNotice&&<div className="drawing-sync-notice" role="status">{drawingSyncNotice}<button onClick={()=>{saveRetryCount.current=0;lastSavedWorkspace.current='';setWorkspaceRetry(v=>v+1)}}>重试保存</button><button onClick={()=>setDrawingSyncNotice('')}>知道了</button></div>}{workspaceView==='chart'&&(ws.tiles.some(t=>Boolean(t.symbol))?<div className={`charts-grid cols-${ws.layout}`}>{ws.tiles.slice(0,ws.layout).map((tile,i)=><ChartPane dateHost={dateHost} drawingClipboard={drawingClipboard} setDrawingClipboard={setDrawingClipboard} streamHost={streamHost} drawingHost={drawingHost} onAnalysis={openAnalysis} key={`${market}-${i}-${tile.symbol}`} index={i} tile={tile} mode={ws.mode} appearance={ws.chartAppearance} snapCrosshairTime={snapCrosshairTime} indicators={ws.indicators} onIndicatorToggle={(id,visible)=>patchIndicator(id,{visible})} active={active===i} onActivate={()=>setActive(i)} drawings={drawingViews[i].horizontal} onDraw={v=>updateMarket(w=>({...w,drawings:updateDrawingRecords(w.drawings,tile.symbol,tile.period,v)}))} trends={drawingViews[i].trends} onTrend={v=>updateMarket(w=>({...w,trends:updateDrawingRecords(w.trends,tile.symbol,tile.period,v)}))} fibos={drawingViews[i].fibos} onFibos={v=>updateMarket(w=>({...w,fibos:updateDrawingRecords(w.fibos,tile.symbol,tile.period,v)}))} measures={drawingViews[i].measures} onMeasures={v=>updateMarket(w=>({...w,measures:updateDrawingRecords(w.measures,tile.symbol,tile.period,v)}))} drawingsHidden={ws.drawingsHidden[`${tile.symbol}:${tile.period}`]===true} onDrawingsHidden={value=>updateMarket(w=>({...w,drawingsHidden:{...w.drawingsHidden,[`${tile.symbol}:${tile.period}`]:value}}))} version={refresh} stockName={stockNames[tile.symbol]||quotes[tile.symbol]?.name} depthHost={active===i?depthHost:null}/>)}</div>:
        <div className="empty-watchlist"><strong>{selectedGroup.name}还是空的</strong><p>在左侧输入股票代码，就能开始看盘。</p><small>{market==='US'?'示例：AAPL、US.SNDK':'示例：SH.600519、SZ.000001'}</small></div>)}
      {market==='US'&&!/^US\.(BK|LIST)\d+$/.test(current?.symbol||'')&&<div className="market-trade-strip"><div><strong>{current?.symbol||'US.SNDK'}</strong><span>当前图表 · 快捷交易</span></div><div className="market-trade-buttons"><button className="buy" onClick={()=>openTrading(current?.symbol||'US.SNDK','buy')}>买入</button><button className="close" onClick={()=>openTrading(current?.symbol||'US.SNDK','close')}>平仓</button><button className="stop" onClick={()=>openTrading(current?.symbol||'US.SNDK','stop')}>设置止损</button><button onClick={()=>openTrading(current?.symbol||'US.SNDK','options')}>期权</button><button className="strategy-entry" onClick={()=>openTrading(current?.symbol||'US.SNDK','strategy')}>自定义策略</button></div><small>图内交易面板 · 自定义快捷方案 · 实盘需解锁</small></div>}
      {market==='US'&&secureChart&&showStrategies&&<Suspense fallback={<p>正在打开策略编辑器…</p>}><StrategyPanel symbol={current?.symbol||'US.SNDK'} period={current?.period||'5m'} mode={ws.mode} indicators={ws.indicators} onClose={()=>setShowStrategies(false)} onOpenTrading={()=>openTrading(current?.symbol||'US.SNDK','overview')}/></Suspense>}
      {market==='CN'&&<div className="market-trade-strip market-trade-readonly"><strong>A 股 · 看盘模式</strong><small>当前平台未开放 A 股交易</small></div>}
    {market==='US'&&secureChart&&tradeDock&&<section ref={tradeDockRef} className="chart-trade-dock" aria-label="图内交易面板"><div className="chart-trade-dock-head"><strong>快捷交易</strong><button onClick={()=>setDockSymbol(current?.symbol||dockSymbol)} disabled={market!=='US'}>带入当前图表</button><button onClick={()=>setTradeDock(false)} aria-label="关闭图内交易">×</button></div><TradeTerminal embedded productRequest={dockRequest} chartSymbol={dockSymbol} onSessionEnd={onSessionEnd}/></section>}

      </div>
    </main></div>

    {backgroundReport.busy&&!analysisChart&&<div className="background-report-status" role="status">AI分析进行中，完成后自动打开报告</div>}
    {analysisChart&&<Suspense fallback={<p role="status">正在打开AI分析…</p>}><MarketAnalysis key={[analysisChart.symbol,analysisChart.period,analysisChart.mode].join(':')} chart={analysisChart}
      busy={backgroundReport.busy} opened={openedReport} onOpen={showReport}
      onStart={refs=>{setOpenedReport(null);void backgroundReport.start(analysisChart,refs)}} onApply={applyAnalysisDrawings} onClose={()=>setAnalysisChart(null)} onSettings={()=>{setAnalysisChart(null);setSettingsTab('agents')}}/></Suspense>}
    {workspaceView!=='chart'&&hasDepthIndicator&&depthHost&&<DepthPanel key={current.symbol} symbol={current.symbol} settingsHost={depthHost}/>}
    {settingsTab&&<SettingsPanel tab={settingsTab} onTab={tab=>{if(tab==='appearance')setAppearanceMarket(market);setSettingsTab(tab)}} onClose={()=>setSettingsTab(null)}>{settingsTab==='notifications'?<NotificationSettings secureUrl={new URL('/chart?settings=notifications',secureChart?location.origin:tradingUrl).href}/>:settingsTab==='agents'?<AgentSettings secureUrl={new URL('/chart?settings=agents',secureChart?location.origin:tradingUrl).href}/>:settingsTab==='connection'?<><p>{market==='US'?'美股':'沪深'}历史行情 {status.routes?.[market]?.history} · 报价 {status.routes?.[market]?.snapshots} · 实时 {status.routes?.[market]?.live}</p>{status.historical_chips===false&&<p>机构动向需要逐根历史筹码；当前历史源未声明提供这项数据。</p>}{status.capabilities?.chip_summary&&<ChipSummary key={market} market={market}/>}{status.opend_configured&&<OpenDPanel tradingUrl={tradingUrl} onReady={()=>setRefresh(v=>v+1)}/>}</>:settingsTab==='appearance'?<CandleSettings snapCrosshairTime={snapCrosshairTime} onCrosshairSnapChange={changeCrosshairSnap} market={appearanceMarket} onMarket={setAppearanceMarket} appearance={state.markets[appearanceMarket].chartAppearance} onChange={patch=>setState(old=>({...old,markets:{...old.markets,[appearanceMarket]:{...old.markets[appearanceMarket],chartAppearance:{...old.markets[appearanceMarket].chartAppearance,...patch}}}}))}/>:settingsTab==='indicators'?indicatorSettings:<CachePanel embedded symbol={current?.symbol} onClose={()=>setSettingsTab(null)}/>}</SettingsPanel>}

  </div>;
}
function SecureChart(){
 const [auth,setAuth]=useState<boolean|null>(null);
 useEffect(()=>{fetch('/api/trade/auth').then(r=>r.json()).then(a=>{setChartCsrf(a.csrf||'');setAuth(!!a.authenticated)}).catch(()=>setAuth(false))},[]);
 if(auth===null)return <div className="trade-login">正在检查交易平台登录状态…</div>;
 return auth?<App onSessionEnd={()=>{setChartCsrf('');setAuth(false)}}/>:<TradeTerminal onAuthenticated={token=>{setChartCsrf(token);setAuth(true)}}/>;
}
createRoot(document.getElementById('root')!).render(<ThemeProvider>{new URLSearchParams(location.search).get('view')==='indicator-guide'?<IndicatorLibrary/>:location.pathname.startsWith('/trade')?<TradeTerminal/>:secureChart?<SecureChart/>:<App/>}</ThemeProvider>);
