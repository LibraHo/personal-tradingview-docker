import type {ISeriesPrimitive,Time,SeriesAttachedParameter,UTCTimestamp} from 'lightweight-charts';
import {visibleExtremes} from './historyTools';
import type {Bar} from './indicators';

/** Short leaders at the visible candles, with no price-axis lines or autoscale changes. */
export function visibleExtremeLabels(bars:Bar[]):ISeriesPrimitive<Time>{
 let attached:SeriesAttachedParameter<Time>|null=null;
 const view={zOrder:()=>'top' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached)return;const {chart,series}=attached,range=chart.timeScale().getVisibleRange();
  if(!range||typeof range.from!=='number'||typeof range.to!=='number')return;
  const extremes=visibleExtremes(bars,range.from,range.to);if(!extremes)return;
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   ctx.save();ctx.font='11px system-ui';ctx.textBaseline='middle';
   for(const high of [true,false]){
    const price=high?extremes.high:extremes.low,bar=bars.find(b=>b.time>=Number(range.from)&&b.time<=Number(range.to)&&(high?b.high:b.low)===price);if(!bar)continue;
    const x=chart.timeScale().timeToCoordinate(bar.time as UTCTimestamp),y=series.priceToCoordinate(price);if(x===null||y===null)continue;
    const text=price.toFixed(price<1?4:2),width=ctx.measureText(text).width;
    const dir=x+width+34<mediaSize.width?1:-1,dy=high?-15:15,labelY=Math.max(9,Math.min(mediaSize.height-9,y+dy));
    ctx.strokeStyle=high?'#d9b36b':'#8cb5dc';ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=1;ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dir*10,labelY);ctx.lineTo(x+dir*22,labelY);ctx.stroke();
    ctx.textAlign=dir===1?'left':'right';ctx.fillText(text,x+dir*26,labelY);
   }ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.requestUpdate()},detached:()=>{attached=null},paneViews:()=>[view]};
}
