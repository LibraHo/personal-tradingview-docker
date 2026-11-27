import type {ISeriesPrimitive,SeriesAttachedParameter,Time} from 'lightweight-charts';
import {drawingStyle,measureLabel,type MeasureDrawing} from './drawingTools';

export function measureLine(initial:MeasureDrawing,selected:boolean,timeToX:(time:number)=>number|null,times:number[]){
 let attached:SeriesAttachedParameter<Time>|null=null;
 let line=initial,label=measureLabel(line,times);
 const style=drawingStyle(line,'measure');
 const primitive:ISeriesPrimitive<Time>={
  attached(p){attached=p;p.requestUpdate()},
  detached(){attached=null},
  paneViews:()=>[{zOrder:()=>'top',renderer:()=>({draw(target){
   if(!attached)return;
   const {chart,series}=attached,[a,b]=line.points;
   const x1=timeToX(a.time),x2=timeToX(b.time),y1=series.priceToCoordinate(a.price),y2=series.priceToCoordinate(b.price);
   if(x1===null||x2===null||y1===null||y2===null)return;
   target.useMediaCoordinateSpace(({context:ctx,mediaSize:{width,height}})=>{
    if(Math.max(x1,x2)<0||Math.min(x1,x2)>width||Math.max(y1,y2)<0||Math.min(y1,y2)>height)return;
    ctx.save();
    ctx.strokeStyle=style.color;
    ctx.lineWidth=style.lineWidth+(selected?1:0);
    ctx.setLineDash(style.lineStyle===1?[1,3]:style.lineStyle===2?[6,4]:[]);
    ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();
    ctx.setLineDash([]);ctx.beginPath();
    const horizontal=line.axis==='horizontal',dx=horizontal?0:5,dy=horizontal?5:0;
    for(const [x,y] of [[x1,y1],[x2,y2]]){
     ctx.moveTo(x-dx,y-dy);ctx.lineTo(x+dx,y+dy);
    }
    ctx.stroke();
    ctx.font='12px system-ui, sans-serif';
    const w=ctx.measureText(label).width+12;
    const x=Math.max(0,Math.min(width-w,horizontal?(x1+x2-w)/2:x1+8));
    const y=Math.max(0,Math.min(height-20,horizontal?y1-24:(y1+y2)/2-10));
    const {background,textColor}=chart.options().layout;
    ctx.fillStyle='color' in background?background.color:background.topColor;
    ctx.fillRect(x,y,w,20);ctx.fillStyle=textColor;ctx.textBaseline='middle';ctx.fillText(label,x+6,y+10);
    ctx.restore();
   });
  }})}]
 };
 return Object.assign(primitive,{update(points:MeasureDrawing['points']){
  line={...line,points};label=measureLabel(line,times);attached?.requestUpdate();
 }});
}
