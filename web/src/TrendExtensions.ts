import type {ISeriesPrimitive,Time,SeriesAttachedParameter,UTCTimestamp} from 'lightweight-charts';
import {drawingStyle,type TrendDrawing} from './drawingTools';

/** Draw rays in chart coordinates, so they extend to the viewport without inventing candles. */
export function trendExtension(line:TrendDrawing,selected:boolean):ISeriesPrimitive<Time>{
 let attached:SeriesAttachedParameter<Time>|null=null;
 const view={zOrder:()=>'top' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached||!line.extend||line.extend==='none')return;
  const [a,b]=[...line.points].sort((a,b)=>a.time-b.time),{chart,series}=attached;
  const x1=chart.timeScale().timeToCoordinate(a.time as UTCTimestamp),x2=chart.timeScale().timeToCoordinate(b.time as UTCTimestamp),y1=series.priceToCoordinate(a.price),y2=series.priceToCoordinate(b.price);
  if(x1===null||x2===null||y1===null||y2===null||x1===x2)return;
  const style=drawingStyle(line,'trend');
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   const slope=(y2-y1)/(x2-x1),y=(x:number)=>y1+(x-x1)*slope;
   ctx.save();ctx.beginPath();ctx.rect(0,0,mediaSize.width,mediaSize.height);ctx.clip();ctx.strokeStyle=style.color;ctx.lineWidth=selected?Math.min(4,style.lineWidth+2):style.lineWidth;
   ctx.setLineDash(style.lineStyle===1?[1,3]:style.lineStyle===2?[6,4]:[]);ctx.beginPath();
   if(line.extend==='left'||line.extend==='both'){ctx.moveTo(0,y(0));ctx.lineTo(x1,y1)}
   if(line.extend==='right'||line.extend==='both'){ctx.moveTo(x2,y2);ctx.lineTo(mediaSize.width,y(mediaSize.width))}
   ctx.stroke();ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.requestUpdate()},detached:()=>{attached=null},paneViews:()=>[view]};
}
