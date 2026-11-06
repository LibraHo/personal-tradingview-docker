import type {ISeriesPrimitive,Time,SeriesAttachedParameter,UTCTimestamp,MouseEventParams} from 'lightweight-charts';
import type {Bar} from './indicators';
import {sixPulseRows} from './sixpulse';
import {selectedColor} from './histogramColors';

/** Six fixed rows; numeric diagnostics and SCORE never distort the pane scale. */
export function sixPulsePanel(bars:Bar[],values:Record<string,(number|null)[]>,colors?:Record<string,string>):ISeriesPrimitive<Time>{
 let attached:SeriesAttachedParameter<Time>|null=null,hover:number|null=null;
 const indices=new Map(bars.map((b,i)=>[b.time,i]));
 const up=selectedColor(colors,'up','#ef5350'),down=selectedColor(colors,'down','#26a69a');
 const cross=(p:MouseEventParams<Time>)=>{hover=typeof p.time==='number'?(indices.get(p.time)??null):null;attached?.requestUpdate()};
 const view={zOrder:()=>'top' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached)return;const {chart,series}=attached,scale=chart.timeScale(),range=scale.getVisibleLogicalRange();if(!range)return;
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   const w=mediaSize.width,h=mediaSize.height,spacing=scale.options().barSpacing;
   const from=Math.max(0,Math.floor(range.from)-1),to=Math.min(bars.length-1,Math.ceil(range.to)+1);
   const stride=Math.max(1,Math.ceil(7/spacing));
   ctx.save();ctx.beginPath();ctx.rect(0,0,w,h);ctx.clip();
   const ys=sixPulseRows.map((_,j)=>series.priceToCoordinate(j+1));
   const gap=ys[0]!==null&&ys[1]!==null?Math.abs(ys[1]!-ys[0]!):12;
   const radius=Math.max(1.5,Math.min(4.5,gap*.28,spacing*stride*.38));
   for(let i=from;i<=to;i++){
    if(i%stride!==0&&i!==hover&&i!==bars.length-1)continue;
    const x=scale.timeToCoordinate(bars[i].time as UTCTimestamp);if(x===null||x<56||x>w+radius)continue;
    sixPulseRows.forEach((name,j)=>{const y=ys[j],v=values[name][i];if(y===null||y<25||y>h-3)return;
     if(v===null){ctx.fillStyle='#66758a';ctx.fillRect(x-1,y-1,2,2);return}
     const direction=v===1?-1:1;ctx.fillStyle=v===1?up:down;ctx.beginPath();
     ctx.moveTo(x,y+direction*radius);ctx.lineTo(x-radius,y-direction*radius*.35);ctx.lineTo(x-radius*.35,y-direction*radius*.35);
     ctx.lineTo(x-radius*.35,y-direction*radius);ctx.lineTo(x+radius*.35,y-direction*radius);ctx.lineTo(x+radius*.35,y-direction*radius*.35);
     ctx.lineTo(x+radius,y-direction*radius*.35);ctx.closePath();ctx.fill();
    });
   }
   ctx.fillStyle='#0e1624';ctx.fillRect(0,0,w,24);ctx.fillRect(0,24,54,Math.max(0,h-24));
   ctx.font='11px system-ui';ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillStyle='#aebdd1';
   sixPulseRows.forEach((name,j)=>{const y=ys[j];if(y!==null&&y>=25&&y<h-3)ctx.fillText(name,5,y)});
   const i=hover??bars.length-1,score=values.SCORE[i],caption=score===null||score===undefined?'数据不足':`${score}/6`;
   ctx.fillStyle='#d6e2f2';ctx.fillText(`六脉神剑 · ${hover===null?'最新':'光标'}共振 ${caption}`,7,12);
   ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.chart.subscribeCrosshairMove(cross);p.requestUpdate()},detached:()=>{attached?.chart.unsubscribeCrosshairMove(cross);attached=null},paneViews:()=>[view]};
}
