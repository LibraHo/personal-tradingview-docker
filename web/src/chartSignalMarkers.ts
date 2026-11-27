import {createSeriesMarkers,type IChartApi,type ISeriesApi,type MouseEventParams,type SeriesMarker,type Time} from 'lightweight-charts';

/** Keep every symbol. Give text at the crosshair first choice of horizontal space. */
export function chartSignalMarkers(chart:IChartApi,series:ISeriesApi<any>,markers:SeriesMarker<Time>[]){
 const hidden=markers.map(marker=>marker.text?{...marker,text:undefined}:marker);
 const plugin=createSeriesMarkers(series,hidden,{autoScale:true});
 if(!markers.some(marker=>marker.text))return plugin;
 const scale=chart.timeScale(),ctx=document.createElement('canvas').getContext('2d')!;
 const {fontSize,fontFamily}=chart.options().layout;
 ctx.font=fontSize+'px '+fontFamily;
 const labels=markers.flatMap((marker,index)=>marker.text?[{index,time:marker.time,half:ctx.measureText(marker.text).width/2+3}]:[]);
 const times=new Set(labels.map(label=>label.time));
 let hover:Time|undefined,frame=0,previous=new Set<number>();
 function layout(){
  frame=0;
  const chosen=new Set<number>();
  const width=scale.width();
  const visible=labels.flatMap(label=>{
   const x=scale.timeToCoordinate(label.time);
   return x!==null&&x>=0&&x<=width?[{...label,left:x-label.half,right:x+label.half}]:[];
  });
  const focus=visible.filter(label=>label.time===hover);
  const focusLeft=Math.min(...focus.map(label=>label.left)),focusRight=Math.max(...focus.map(label=>label.right));
  for(const label of focus)chosen.add(label.index);
  let nextLeft=Infinity,groupTime:Time|undefined,groupRightLimit=Infinity;
  for(let i=visible.length-1;i>=0;i--){
   const label=visible[i];
   if(label.time===hover)continue;
   if(label.time!==groupTime){groupTime=label.time;groupRightLimit=nextLeft}
   if(label.right>groupRightLimit||(label.right>focusLeft&&label.left<focusRight))continue;
   // The chart stacks simultaneous events on the same bar vertically.
   chosen.add(label.index);nextLeft=Math.min(nextLeft,label.left);
  }
  if(chosen.size===previous.size&&[...chosen].every(index=>previous.has(index)))return;
  previous=chosen;
  plugin.setMarkers(hidden.map((marker,index)=>chosen.has(index)?markers[index]:marker));
 }
 function schedule(){if(!frame)frame=requestAnimationFrame(layout)}
 function cross(event:MouseEventParams<Time>){
  const next=event.time!==undefined&&times.has(event.time)?event.time:undefined;
  if(next!==hover){hover=next;schedule()}
 }
 scale.subscribeVisibleLogicalRangeChange(schedule);
 scale.subscribeSizeChange(schedule);
 chart.subscribeCrosshairMove(cross);
 schedule();
 return {detach(){
  cancelAnimationFrame(frame);
  chart.unsubscribeCrosshairMove(cross);
  scale.unsubscribeVisibleLogicalRangeChange(schedule);
  scale.unsubscribeSizeChange(schedule);
  plugin.detach();
 }};
}
