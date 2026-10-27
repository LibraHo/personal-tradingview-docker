export type DrawingPoint={time:number;price:number};
export type FibDrawing={points:DrawingPoint[];levels?:number[];color?:string};
export const DEFAULT_FIB_LEVELS=[0,.236,.382,.5,.618,.786,1];
export function fibPrices(drawing:FibDrawing){
 if(!Array.isArray(drawing.points)||drawing.points.length!==2||drawing.points.some(p=>!p||!Number.isFinite(p.price)||!Number.isFinite(p.time))||drawing.points[0].time===drawing.points[1].time)return [];
 const [a,b]=drawing.points;
 return (drawing.levels||DEFAULT_FIB_LEVELS).filter(r=>Number.isFinite(r)&&r>=0&&r<=4.236).map(r=>({ratio:r,price:b.price+(a.price-b.price)*r}));
}
