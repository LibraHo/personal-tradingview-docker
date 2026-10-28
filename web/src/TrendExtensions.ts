import type {IChartApi,ISeriesPrimitive,Time,SeriesAttachedParameter,UTCTimestamp} from 'lightweight-charts';
import {drawingStyle,type TrendDrawing} from './drawingTools';
import {projectDrawingTime} from './trendGeometry';

export function drawingTimeCoordinate(chart:IChartApi,time:number,times:number[],step:number):number|null{
 const scale=chart.timeScale(),exact=scale.timeToCoordinate(time as UTCTimestamp);if(exact!==null)return exact;
 if(!times.length)return null;
 let lo=0,hi=times.length-1;while(hi-lo>1){const mid=(lo+hi)>>1;if(times[mid]<=time)lo=mid;else hi=mid}
 const indices=time<times[0]?[0]:time>times[times.length-1]?[times.length-1]:[lo,hi];
 const samples=indices.flatMap(i=>{const x=scale.timeToCoordinate(times[i] as UTCTimestamp);return x===null?[]:[{time:times[i],x}]});
 return projectDrawingTime(time,samples,step,scale.options().barSpacing);
}

/** Draw rays in chart coordinates, so they extend to the viewport without inventing candles. */
export function trendExtension(initial:TrendDrawing,selected:boolean,timeToX?:(time:number)=>number|null):ISeriesPrimitive<Time>&{updateDrawing:(line:TrendDrawing)=>void}{
 let attached:SeriesAttachedParameter<Time>|null=null;
 let line=initial;
 const view={zOrder:()=>'top' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached)return;
  const [a,b]=[...line.points].sort((a,b)=>a.time-b.time),{chart,series}=attached;
  const x1=timeToX?timeToX(a.time):chart.timeScale().timeToCoordinate(a.time as UTCTimestamp),x2=timeToX?timeToX(b.time):chart.timeScale().timeToCoordinate(b.time as UTCTimestamp),y1=series.priceToCoordinate(a.price),y2=series.priceToCoordinate(b.price);
  if(x1===null||x2===null||y1===null||y2===null||x1===x2)return;
  const style=drawingStyle(line,'trend');
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   const slope=(y2-y1)/(x2-x1),y=(x:number)=>y1+(x-x1)*slope;
   ctx.save();ctx.beginPath();ctx.rect(0,0,mediaSize.width,mediaSize.height);ctx.clip();ctx.strokeStyle=style.color;ctx.lineWidth=selected?Math.min(4,style.lineWidth+2):style.lineWidth;
   ctx.setLineDash(style.lineStyle===1?[1,3]:style.lineStyle===2?[6,4]:[]);ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);
   if(line.extend==='left'||line.extend==='both'){ctx.moveTo(0,y(0));ctx.lineTo(x1,y1)}
   if(line.extend==='right'||line.extend==='both'){ctx.moveTo(x2,y2);ctx.lineTo(mediaSize.width,y(mediaSize.width))}
   ctx.stroke();
   if(selected){ctx.setLineDash([]);ctx.lineWidth=2;for(const [x,y] of [[x1,y1],[x2,y2]]){ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.fillStyle='#0e1624';ctx.fill();ctx.strokeStyle='#d6e9ff';ctx.stroke()}}
   ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.requestUpdate()},detached:()=>{attached=null},paneViews:()=>[view],updateDrawing:next=>{line=next;attached?.requestUpdate()}};
}
