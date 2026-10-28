import type {DrawingPoint,TrendDrawing} from './drawingTools';
export type TimeSample={time:number;x:number};
export function projectDrawingTime(time:number,samples:TimeSample[],step:number,spacing:number):number|null{
 if(!samples.length||!Number.isFinite(time))return null;
 const first=samples[0],last=samples[samples.length-1];
 if(time<=first.time)return first.x+(time-first.time)/step*spacing;
 if(time>=last.time)return last.x+(time-last.time)/step*spacing;
 let lo=0,hi=samples.length-1;while(hi-lo>1){const mid=(lo+hi)>>1;if(samples[mid].time<=time)lo=mid;else hi=mid}
 const a=samples[lo],b=samples[hi];return a.x+(b.x-a.x)*(time-a.time)/(b.time-a.time);
}
export function drawingTimeAtX(x:number,samples:TimeSample[],step:number,spacing:number):number|null{
 if(!samples.length||!Number.isFinite(x))return null;
 const first=samples[0],last=samples[samples.length-1];
 if(x<first.x)return Math.max(1,first.time+Math.round((x-first.x)/spacing)*step);
 if(x>last.x)return last.time+Math.round((x-last.x)/spacing)*step;
 let lo=0,hi=samples.length-1;while(hi-lo>1){const mid=(lo+hi)>>1;if(samples[mid].x<=x)lo=mid;else hi=mid}
 return Math.abs(x-samples[lo].x)<=Math.abs(x-samples[hi].x)?samples[lo].time:samples[hi].time;
}
export function moveTrendEndpoint(line:TrendDrawing,index:number,point:DrawingPoint):TrendDrawing{
 if((index!==0&&index!==1)||line.points.length!==2||!Number.isFinite(point.time)||point.time<=0||!Number.isFinite(point.price)||point.price<=0||point.time===line.points[1-index].time)return line;
 return {...line,points:line.points.map((p,i)=>i===index?point:p)};
}
export function hitTestTrendEndpoint(point:{x:number;y:number},line:TrendDrawing,priceToY:(price:number)=>number|null,timeToX:(time:number)=>number|null):number|null{
 let closest:number|null=null,best=12;
 line.points.forEach((p,i)=>{const x=timeToX(p.time),y=priceToY(p.price);if(x===null||y===null)return;const d=Math.hypot(point.x-x,point.y-y);if(d<=best){best=d;closest=i}});return closest;
}
