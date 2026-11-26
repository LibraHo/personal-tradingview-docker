import {createSeriesMarkers,CandlestickSeries,HistogramSeries,LineSeries,LineStyle,type IChartApi,type ISeriesApi,type SeriesMarker,type Time,type UTCTimestamp} from 'lightweight-charts';
import {tdxCatalog} from './tdxIndicators';
import type {Bar,Indicator} from './indicators';

export const resonanceColors={below:'#269d87',neutral:'#8795a8',strong:'#d5a746',buy:'#ff5269'};

/** Render only declared visual lines; boolean scan outputs must not distort price axes. */
export function drawTdx(chart:IChartApi,bars:Bar[],ind:Indicator,values:Record<string,(number|null)[]>,pane:number,series:ISeriesApi<any>[],markers:SeriesMarker<Time>[],cleanup:(()=>void)[]=[]){
 const item=tdxCatalog[ind.name];if(!item)return false;
 if(ind.name==='FULAI'){
  const s=chart.addSeries(CandlestickSeries,{lastValueVisible:false,priceLineVisible:false,wickVisible:false,borderVisible:false,title:'福来K线提示'},pane);
  const colors:Record<string,string>={'1':'#ef5350','-1':'#26a69a','-2':'#2685bb','3':'#ff7777','4':'#e040fb','5':'#eeee33'};
  s.setData(bars.map((b,i)=>{const color=colors[String(values['K线状态'][i])],time=b.time as UTCTimestamp;return color?{time,open:b.open,close:b.close,high:b.high,low:b.low,color,wickColor:color,borderColor:color}:{time}}));series.push(s);
 }
 for(const [key,style] of Object.entries(item.plots)){
  const hist=['relative-volume','hist','band','control','resonance-deviation'].includes(style.kind);
  const threshold=style.kind==='resonance-threshold',reference=threshold||style.kind==='resonance-zero';
  const s=chart.addSeries(hist?HistogramSeries:LineSeries,{color:ind.colors?.[key]||style.color,lineWidth:reference||style.kind==='dotted'?1:2,lineStyle:threshold?LineStyle.Dashed:style.kind==='dotted'?LineStyle.Dotted:LineStyle.Solid,
   ...(ind.name==='CHIEF_RESONANCE_PANE'?{priceFormat:{type:'percent' as const,precision:1,minMove:.1}}:{}),
   lastValueVisible:style.kind==='relative-volume',priceLineVisible:false,title:style.label||`${item.label.split(' · ')[0]} ${key}`},pane);
  s.setData(values[key].map((v,i)=>{
   const time=bars[i].time as UTCTimestamp;if(v===null||!Number.isFinite(v))return {time};
   let color=ind.colors?.[key]||style.color,value=v;
   if(style.kind==='band'){value=95;color=({'-1':'#26a69a','0':'#546e7a','1':'#fdd835','2':'#ef5350','3':'#f48fb1','4':'#e040fb'} as Record<string,string>)[String(v)]}
   if(style.kind==='trend')color=v>=(values[key][i-1]??v)?'#e040fb':'#26a69a';
   if(style.kind==='fuline')color=v>(values['B2均线'][i]??v)?'#ef5350':'#26a69a';
   if(style.kind==='control')color=v<0?'#26a69a':v>(values[key][i-1]??v)?'#ef5350':'#fdd835';
   if(style.kind==='resonance-deviation')color=values['共振'][i]===1?resonanceColors.buy:v>5?resonanceColors.strong:v<0?resonanceColors.below:color;
   return {time,value,color};
  }));
  if(style.kind==='relative-volume')s.createPriceLine({price:1,color:'#8495a7',lineWidth:1,lineStyle:LineStyle.Dashed,axisLabelVisible:true,title:'1 倍'});
  if(style.kind==='band')s.applyOptions({base:94});
  series.push(s);
 }
 const localMarkers:SeriesMarker<Time>[]=[];
 const lastTime=bars.at(-1)?.time;
 let lastPending=true;
 if(lastTime!==undefined&&item.period==='120m'&&item.market==='CN'){
  const localSeconds=(lastTime+8*3600)%86400;
  const closeSeconds=localSeconds<12*3600?11.5*3600:15*3600;
  lastPending=Date.now()/1000<lastTime-localSeconds+closeSeconds;
 }
 for(const [key,signal] of Object.entries(item.signals))for(let i=0;i<bars.length;i++)if(values[key][i]===1){
  localMarkers.push({time:bars[i].time as UTCTimestamp,position:signal.down?'aboveBar':'belowBar',shape:signal.shape||(signal.down?'arrowDown':'arrowUp'),color:ind.colors?.[key]||signal.color,text:signal.text?`${signal.text}${i===bars.length-1&&lastPending?'（待确认）':''}`:undefined,size:signal.shape==='circle'?.7:1,id:`${ind.id}:${key}:${bars[i].time}`});
 }
 if(pane===0)markers.push(...localMarkers);
 else if(localMarkers.length){
  // Signals belong to this indicator pane, never to the main price candle.
  const anchor=chart.addSeries(LineSeries,{visible:true,lineVisible:false,pointMarkersVisible:false,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false},pane);
  const reference=values['趋势']||values[Object.keys(item.plots)[0]];
  const fallback=ind.name==='CHIEF_RESONANCE_PANE'?0:24;
  anchor.setData(bars.map((b,i)=>({time:b.time as UTCTimestamp,value:reference?.[i]??fallback})));
  series.push(anchor);
  const plugin=createSeriesMarkers(anchor,localMarkers.sort((a,b)=>Number(a.time)-Number(b.time)),{autoScale:true});
  cleanup.push(()=>plugin.detach());
 }

 return true;
}
