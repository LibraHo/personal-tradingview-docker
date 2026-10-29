import type {ISeriesPrimitive,Time,SeriesAttachedParameter,UTCTimestamp} from 'lightweight-charts';
import type {Bar} from './indicators';

export const sessionColors:Record<string,string>={pre:'rgba(72,129,219,0.13)',post:'rgba(219,161,72,0.12)',overnight:'rgba(155,105,219,0.14)'};
export function sessionSpans(bars:Pick<Bar,'time'|'session'|'session_date'>[],timeToX:(time:number)=>number|null,spacing:number,width:number){
 const spans:{session:string;left:number;right:number}[]=[];let previousDate='',previousIndex=-2;
 bars.forEach((bar,index)=>{
  const x=timeToX(bar.time);if(x===null||!sessionColors[bar.session]||x+spacing/2<=0||x-spacing/2>=width){previousIndex=-2;return}
  const left=Math.max(0,x-spacing/2),right=Math.min(width,x+spacing/2),last=spans.at(-1);
  if(last&&last.session===bar.session&&previousDate===bar.session_date&&previousIndex===index-1)last.right=right;
  else spans.push({session:bar.session,left,right});
  previousDate=bar.session_date;previousIndex=index;
 });return spans;
}

/** Session tint beneath the candles; it does not add bars or affect scaling. */
export function sessionBackground(bars:Bar[]):ISeriesPrimitive<Time>{
 let attached:SeriesAttachedParameter<Time>|null=null;
 const view={zOrder:()=>'bottom' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached)return;const scale=attached.chart.timeScale();
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   const spans=sessionSpans(bars,time=>scale.timeToCoordinate(time as UTCTimestamp),scale.options().barSpacing,mediaSize.width);
   ctx.save();for(const span of spans){ctx.fillStyle=sessionColors[span.session];ctx.fillRect(span.left,0,span.right-span.left,mediaSize.height)}ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.requestUpdate()},detached:()=>{attached=null},paneViews:()=>[view]};
}
