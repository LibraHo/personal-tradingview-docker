import type {ISeriesPrimitive,Time,SeriesAttachedParameter,UTCTimestamp} from 'lightweight-charts';
import type {Bar} from './indicators';
import {selectedColor} from './histogramColors';

export function msigm8Drawings(bars:Bar[],values:Record<string,(number|null)[]>,colors?:Record<string,string>){
 const segments:{from:number;to:number;price:number;color:string}[]=[],markers:{index:number;time:number;price:number;text:string;color:string}[]=[];
 bars.forEach((bar,i)=>{for(const side of ['SELL','BUY']){
  if(values[side+'_SIGNAL'][i]!==1)continue;
  const sell=side==='SELL',start=values[side+'_START'][i],level=values[side+'_LEVEL'][i],price=values[side+'_MARKER'][i];
  if(start!==null&&Number.isInteger(start)&&start>=0&&start<i&&level!==null)segments.push({from:bars[start].time,to:bar.time,price:level,color:selectedColor(colors,sell?'sellLine':'buyLine',sell?'#f08080':'#00c8ff')});
  if(price!==null)markers.push({index:i,time:bar.time,price,text:sell?'↓':'↑',color:selectedColor(colors,sell?'sellArrow':'buyArrow',sell?'#ff2d2d':'#00d25a')});
 }});return {segments,markers};
}

/** Price-coordinate arrows and finite pivot-to-signal lines; diagnostics stay hidden. */
export function msigm8Overlay(bars:Bar[],values:Record<string,(number|null)[]>,colors?:Record<string,string>):ISeriesPrimitive<Time>{
 let attached:SeriesAttachedParameter<Time>|null=null;
 const {segments,markers}=msigm8Drawings(bars,values,colors);
 const view={zOrder:()=>'top' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached)return;const {chart,series}=attached,scale=chart.timeScale();
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   ctx.save();ctx.beginPath();ctx.rect(0,0,mediaSize.width,mediaSize.height);ctx.clip();ctx.lineWidth=1.5;ctx.setLineDash([]);
   for(const line of segments){const x=scale.timeToCoordinate(line.from as UTCTimestamp),end=scale.timeToCoordinate(line.to as UTCTimestamp),y=series.priceToCoordinate(line.price);if(x===null||end===null||y===null||end<0||x>mediaSize.width)continue;ctx.strokeStyle=line.color;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(end,y);ctx.stroke()}
   ctx.font='bold 20px system-ui';ctx.textAlign='center';ctx.textBaseline='middle';
   for(const marker of markers){const x=scale.timeToCoordinate(marker.time as UTCTimestamp),y=series.priceToCoordinate(marker.price);if(x===null||y===null||x<0||x>mediaSize.width)continue;ctx.fillStyle=marker.color;ctx.fillText(marker.text,x,y)}
   ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.requestUpdate()},detached:()=>{attached=null},paneViews:()=>[view],autoscaleInfo:(from,to)=>{
  const visible=markers.filter(m=>m.index>=from&&m.index<=to);if(!visible.length)return null;
  return {priceRange:{minValue:Math.min(...visible.map(m=>m.price)),maxValue:Math.max(...visible.map(m=>m.price))}};
 }};
}
