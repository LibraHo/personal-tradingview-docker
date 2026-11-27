import type {Bar} from './indicators';

export function nineTurnCounts(bars:Pick<Bar,'close'>[]){
 const up=Array<number|null>(bars.length).fill(null);
 const down=Array<number|null>(bars.length).fill(null);
 for(let i=4;i<bars.length;i++){
  const current=bars[i].close,prior=bars[i-4].close;
  if(!Number.isFinite(current)||!Number.isFinite(prior)||current===prior)continue;
  const side=current>prior?up:down;
  side[i]=(side[i-1]??0)%9+1;
 }
 return {'上涨计数':up,'下跌计数':down};
}

// Only completed groups and the still-forming tail receive chart labels.
// The underlying per-bar counts remain available as they were known at the time.
export function nineTurnLabels(counts:(number|null)[]){
 const labels:{index:number;count:number}[]=[];
 counts.forEach((count,index)=>{
  if(count===null||count<6||(count!==9&&index!==counts.length-1))return;
  for(let n=1;n<=count;n++)labels.push({index:index-count+n,count:n});
 });
 return labels;
}
