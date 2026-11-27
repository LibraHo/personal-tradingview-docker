export type DrawingPoint={time:number;price:number};
export type DrawingKind='horizontal'|'trend'|'fib'|'measure';
export type MeasureAxis='horizontal'|'vertical';
export type MeasureDrawing=DrawingStyle&{id:string;axis:MeasureAxis;points:[DrawingPoint,DrawingPoint]};
export const measureNames={horizontal:'水平测量',vertical:'垂直测量'};

export function measurePoints(axis:MeasureAxis,start:DrawingPoint,end:DrawingPoint):MeasureDrawing['points'] {
 return [start,axis==='horizontal'?{time:end.time,price:start.price}:{time:start.time,price:end.price}];
}

export function measureLabel(line:MeasureDrawing,times:readonly number[]):string {
 const [start,end]=line.points;
 if(line.axis==='vertical'){
  const delta=end.price-start.price;
  const sign=delta>0?'+':'';
  const precision=Math.min(start.price,end.price)<1?4:2;
  return `价差 ${sign}${delta.toFixed(precision)}（${sign}${(100*delta/start.price).toFixed(2)}%）`;
 }
 let seconds=Math.abs(end.time-start.time);
 const duration:string[]=[];
 for(const [unit,size] of [['天',86400],['小时',3600],['分',60],['秒',1]] as const){
  const amount=Math.floor(seconds/size);
  if(amount)duration.push(amount+unit);
  seconds%=size;
 }
 const a=times.indexOf(start.time),b=times.indexOf(end.time);
 return (duration.join('')||'0秒')+(a>=0&&b>=0?` · 相隔 ${Math.abs(b-a)} 根 K 线`:'');
}
export type DrawingStyle={color?:string;lineWidth?:1|2|3|4;lineStyle?:0|1|2;visible?:boolean;timeframeScope?:'current'|'all'};
export type HorizontalDrawing=DrawingStyle&{id:string;price:number};
export type TrendDrawing=DrawingStyle&{id:string;points:DrawingPoint[];extend?:'none'|'left'|'right'|'both'};
export type FibDrawing=DrawingStyle&{id?:string;points:DrawingPoint[];levels?:number[];levelColors?:Record<string,string>};
export type DrawingSelection={kind:DrawingKind;id:string};
export function newDrawingId(){return `d-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`}
export function drawingStyle(raw:DrawingStyle,kind:DrawingKind){
 const solid=kind==='trend'||kind==='measure';
 const fallback={color:kind==='horizontal'?'#c6d6e7':kind==='trend'?'#e3b76b':kind==='measure'?'#40bba8':'#739dde',lineWidth:(solid?2:1) as 1|2|3|4,lineStyle:(solid?0:2) as 0|1|2};
 return {color:typeof raw.color==='string'&&/^#[0-9a-f]{6}$/i.test(raw.color)?raw.color:fallback.color,
  lineWidth:([1,2,3,4].includes(Number(raw.lineWidth))?Number(raw.lineWidth):fallback.lineWidth) as 1|2|3|4,
  lineStyle:([0,1,2].includes(Number(raw.lineStyle))&&raw.lineStyle!=null?Number(raw.lineStyle):fallback.lineStyle) as 0|1|2,visible:raw.visible!==false,timeframeScope:raw.timeframeScope==='all'?'all' as const:'current' as const};
}
/** Shared objects keep their source bucket. View IDs prevent same-ID collisions between periods. */
export function drawingsForPeriod<T extends DrawingStyle&{id?:string}>(records:Record<string,T[]>,symbol:string,period:string):T[]{
 const key=`${symbol}:${period}`;
 return [...(records[key]||[]),...Object.entries(records).flatMap(([source,rows])=>source!==key&&source.startsWith(symbol+':')?rows.filter(row=>row.timeframeScope==='all').map(row=>({...row,id:`@${source}@${row.id}`})):[])];
}
export function updateDrawingRecords<T extends DrawingStyle&{id?:string}>(records:Record<string,T[]>,symbol:string,period:string,rows:T[]):Record<string,T[]>{
 const key=`${symbol}:${period}`,result=Object.fromEntries(Object.entries(records).map(([k,v])=>[k,[...v]]));
 const origin=(id:string|undefined)=>{const match=id?.match(/^@(.+:(?:1m|5m|15m|30m|60m|120m|240m|1d|1w|1mo))@(.+)$/);return match&&match[1].startsWith(symbol+':')?{key:match[1],id:match[2]}:{key,id}};
 for(const row of drawingsForPeriod(records,symbol,period)){const source=origin(row.id);result[source.key]=(result[source.key]||[]).filter(x=>x.id!==source.id)}
 for(const row of rows){
  const source=origin(row.id),target=row.timeframeScope==='all'?source.key:key,bucket=result[target]||(result[target]=[]);
  let id=source.id;for(let n=1;bucket.some(x=>x.id===id);n++)id=`${(source.id||'drawing').slice(0,110)}-moved-${n}`;
  bucket.push({...row,id});
 }
 for(const [bucket,items] of Object.entries(result)){const order=new Map((records[bucket]||[]).map((row,i)=>[row.id,i]));items.sort((a,b)=>(order.get(a.id)??Number.MAX_SAFE_INTEGER)-(order.get(b.id)??Number.MAX_SAFE_INTEGER))}
 // Never trim an aggregated view: that would delete shared source objects.
 if(Object.values(result).some(bucket=>bucket.length>100))return records;
 return result;
}
export function normalizeDrawingRecords(value:unknown,kind:'horizontal'):Record<string,HorizontalDrawing[]>;
export function normalizeDrawingRecords(value:unknown,kind:'trend'):Record<string,TrendDrawing[]>;
export function normalizeDrawingRecords(value:unknown,kind:'fib'):Record<string,FibDrawing[]>;
export function normalizeDrawingRecords(value:unknown,kind:'measure'):Record<string,MeasureDrawing[]>;
export function normalizeDrawingRecords(value:unknown,kind:DrawingKind):Record<string,any[]> {
 if(!value||typeof value!=='object'||Array.isArray(value))return {};
 return Object.fromEntries(Object.entries(value).filter(([,v])=>Array.isArray(v)).map(([key,items])=>{
  const ids=new Set<string>();
  const rows=(items as any[]).slice(0,100).flatMap<HorizontalDrawing|TrendDrawing|FibDrawing>((item,i)=>{
   const raw=item&&typeof item==='object'&&!Array.isArray(item)?item:{};
   let id=typeof raw.id==='string'&&raw.id.length<=128&&raw.id?raw.id:`${kind}-${key}-${i}`;
   if(ids.has(id))id=`${kind}-${key}-${i}`;ids.add(id);
   const base={id,...drawingStyle(raw,kind)};
   if(kind==='horizontal'){
    const price=typeof item==='number'?item:raw.price;
    return Number.isFinite(price)&&price>0?[{...base,price}]:[];
   }
   const points=Array.isArray(item)?item:raw.points;
   if(!Array.isArray(points)||points.length!==2||points.some(p=>!p||!Number.isFinite(p.time)||!Number.isFinite(p.price)||p.price<=0))return [];
   const clean=points.map(p=>({time:p.time,price:p.price}));
   if(kind==='measure'){
    const [a,b]=clean;
    if(raw.axis==='vertical'?a.time!==b.time||a.price===b.price:raw.axis!=='horizontal'||a.time===b.time||a.price!==b.price)return [];
    return [{...base,axis:raw.axis,points:clean}];
   }
   if(points[0].time===points[1].time)return [];
   return [{...base,points:clean,...(kind==='trend'?{extend:['left','right','both'].includes(raw.extend)?raw.extend:'none'}:{}),...(kind==='fib'?{...(Array.isArray(raw.levels)?{levels:raw.levels.filter((r:unknown)=>typeof r==='number'&&Number.isFinite(r)&&r>=0&&r<=4.236)}:{}),levelColors:normalizeLevelColors(raw.levelColors)}:{})}];
  });return [key,rows];
 }));
}
export const DEFAULT_FIB_LEVELS=[0,.236,.382,.5,.618,.786,1];
function normalizeLevelColors(value:unknown):Record<string,string>{
 if(!value||typeof value!=='object'||Array.isArray(value))return {};
 return Object.fromEntries(Object.entries(value).filter(([ratio,color])=>ratio.trim()!==''&&Number.isFinite(Number(ratio))&&Number(ratio)>=0&&Number(ratio)<=4.236&&typeof color==='string'&&/^#[0-9a-f]{6}$/i.test(color)).map(([ratio,color])=>[String(Number(ratio)),color as string]));
}
export function fibPrices(drawing:FibDrawing){
 if(!Array.isArray(drawing.points)||drawing.points.length!==2||drawing.points.some(p=>!p||!Number.isFinite(p.price)||!Number.isFinite(p.time))||drawing.points[0].time===drawing.points[1].time)return [];
 const [a,b]=drawing.points;
 const colors=normalizeLevelColors(drawing.levelColors),fallback=drawingStyle(drawing,'fib').color;
 return (drawing.levels||DEFAULT_FIB_LEVELS).filter(r=>Number.isFinite(r)&&r>=0&&r<=4.236).map(r=>({ratio:r,price:b.price+(a.price-b.price)*r,color:colors[String(r)]||fallback}));
}
export function hitTestDrawing(point:{x:number;y:number},horizontal:HorizontalDrawing[],trends:TrendDrawing[],fibos:FibDrawing[],priceToY:(price:number)=>number|null,timeToX:(time:number)=>number|null,measures:MeasureDrawing[]=[]):DrawingSelection|null {
 const hits:(DrawingSelection&{distance:number})[]=[];
 for(const line of measures){
  if(line.visible===false)continue;
  const [a,b]=line.points;
  const x1=timeToX(a.time),x2=timeToX(b.time),y1=priceToY(a.price),y2=priceToY(b.price);
  if(x1===null||x2===null||y1===null||y2===null)continue;
  const dx=Math.max(0,Math.min(x1,x2)-point.x,point.x-Math.max(x1,x2));
  const dy=Math.max(0,Math.min(y1,y2)-point.y,point.y-Math.max(y1,y2));
  const distance=Math.hypot(dx,dy);
  if(distance<=10)hits.push({kind:'measure',id:line.id,distance});
 }
 const horizontalHit=(price:number,kind:DrawingKind,id:string)=>{const y=priceToY(price);if(y!==null&&Number.isFinite(y)&&Math.abs(y-point.y)<=10)hits.push({kind,id,distance:Math.abs(y-point.y)})};
 for(const line of horizontal)if(line.visible!==false)horizontalHit(line.price,'horizontal',line.id);
 for(const line of trends){
  if(line.visible===false||line.points.length!==2)continue;
  const [a,b]=[...line.points].sort((a,b)=>a.time-b.time),x1=timeToX(a.time),x2=timeToX(b.time),y1=priceToY(a.price),y2=priceToY(b.price);
  if(x1===null||x2===null||y1===null||y2===null)continue;
  const dx=x2-x1,dy=y2-y1,length=dx*dx+dy*dy;if(!length)continue;
  const projection=((point.x-x1)*dx+(point.y-y1)*dy)/length;
  const t=Math.max(line.extend==='left'||line.extend==='both'?-Infinity:0,Math.min(line.extend==='right'||line.extend==='both'?Infinity:1,projection));
  const distance=Math.hypot(point.x-(x1+t*dx),point.y-(y1+t*dy));
  if(distance<=10)hits.push({kind:'trend',id:line.id,distance});
 }
 for(const fib of fibos)if(fib.visible!==false&&fib.id)for(const level of fibPrices(fib))horizontalHit(level.price,'fib',fib.id);
 hits.sort((a,b)=>a.distance-b.distance);return hits.length?{kind:hits[0].kind,id:hits[0].id}:null;
}
