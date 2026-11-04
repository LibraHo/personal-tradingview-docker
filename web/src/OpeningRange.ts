import type {ISeriesPrimitive,Time,SeriesAttachedParameter} from 'lightweight-charts';

export type OpeningRangeData={status:string;symbol:string;date:string;confirmed_at:number;regular_end:number;day_end:number;high?:number;low?:number;stale?:boolean;message?:string;error?:string};
export function openingRangeOptions(params:string){
 const p=JSON.parse(params);if(!p||typeof p!=='object'||Array.isArray(p))throw Error('开盘高低线参数无效');
 const width=p.lineWidth??2,style=p.lineStyle??2;
 if(!Number.isInteger(width)||width<1||width>4||![0,1,2].includes(style))throw Error('线宽须为1–4，样式须为0/1/2');
 if(p.extend!==undefined&&!['day','regular'].includes(p.extend))throw Error('延伸范围无效');
 return {width,style,extend:p.extend||'day',showHigh:p.showHigh!==false,showLow:p.showLow!==false,showLabels:p.showLabels!==false};
}

/** Finite, current-day lines, never a chart-wide price line or a new time-scale point. */
export function openingRangeLines(data:OpeningRangeData,params:string,colors:Record<string,string>|undefined,timeToX:(time:number)=>number|null):ISeriesPrimitive<Time>{
 const options=openingRangeOptions(params);let attached:SeriesAttachedParameter<Time>|null=null;
 const color=(key:string,fallback:string)=>/^#[0-9a-f]{6}$/i.test(colors?.[key]||'')?colors![key]:fallback;
 const view={zOrder:()=>'top' as const,renderer:()=>({draw:(target:any)=>{
  if(!attached||data.status!=='ready')return;
  const start=timeToX(data.confirmed_at),end=timeToX(options.extend==='regular'?data.regular_end:data.day_end);
  if(start===null||end===null||end<=start)return;
  target.useMediaCoordinateSpace(({context:ctx,mediaSize}:{context:CanvasRenderingContext2D;mediaSize:{width:number;height:number}})=>{
   const left=Math.max(0,start),right=Math.min(mediaSize.width,end);if(right<=left)return;
   ctx.save();ctx.beginPath();ctx.rect(0,0,mediaSize.width,mediaSize.height);ctx.clip();ctx.lineWidth=options.width;ctx.font='11px system-ui';ctx.textAlign='right';
   for(const high of [true,false]){
    if(high?!options.showHigh:!options.showLow)continue;
    const price=high?data.high:data.low;if(price===undefined||!Number.isFinite(price))continue;
    const y=attached!.series.priceToCoordinate(price);if(y===null||y<0||y>mediaSize.height)continue;
    ctx.strokeStyle=ctx.fillStyle=color(high?'high':'low',high?'#ffc86d':'#74a9ff');
    ctx.setLineDash(options.style===1?[1,3]:options.style===2?[6,4]:[]);ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
    if(options.showLabels&&right-left>90){ctx.setLineDash([]);ctx.fillText(`开盘5分${high?'高':'低'} ${price.toFixed(price<1?4:2)}`,right-5,Math.max(12,Math.min(mediaSize.height-3,y+(high?-5:14))))}
   }ctx.restore();
  });
 }})};
 return {attached:p=>{attached=p;p.requestUpdate()},detached:()=>{attached=null},paneViews:()=>[view]};
}
