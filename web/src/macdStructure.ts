export type MacdStructureEvent = {
 index:number;
 side:'top'|'bottom';
 state:'dull'|'formed'|'cleared';
};
type Side = MacdStructureEvent['side'];
// Bottoms use negated values so both sides can compare peaks in the same direction.
type Peak = {price:number; dif:number};
type Wave = Peak & {side:Side; bars:number; formed:boolean};

function twoDigits(value:number){
 if(value===0)return 0;
 const step=10**(Math.floor(Math.log10(Math.abs(value)))-1);
 return Math.sign(value)*Math.floor(Math.abs(value)/step+1e-10)*step;
}

/** Public-rule approximation. Histogram sign delimits waves, and the first
 * partial wave after a gap cannot be used as a reference. No lookahead. */
export function macdStructure(bars:readonly {close:number}[],dif:readonly (number|null)[],hist:readonly (number|null)[]):MacdStructureEvent[]{
 const events:MacdStructureEvent[]=[];
 let wave:Wave|undefined,first=true,previousDif:number|undefined;
 const references:Record<Side,Peak[]>={top:[],bottom:[]};
 const pending:Partial<Record<Side,number>>={};
 for(let i=0;i<bars.length;i++){
  const d=dif[i],h=hist[i],close=bars[i].close;
  if(d==null||h==null||![d,h,close].every(Number.isFinite)){
   wave=undefined;first=true;previousDif=undefined;
   references.top=[];references.bottom=[];delete pending.top;delete pending.bottom;
   continue;
  }
  const value=twoDigits(d);
  const side=h>0?'top':h<0?'bottom':wave?.side;
  if(!side){previousDif=value;continue}
  const sign=side==='top'?1:-1,price=sign*close,level=sign*value;
  if(!wave||wave.side!==side){
   if(wave){
    if(!first)references[wave.side]=[wave,...references[wave.side]].slice(0,2);
    first=false;
   }
   wave={side,price,dif:level,bars:0,formed:false};
  }
  wave.price=Math.max(wave.price,price);
  wave.dif=Math.max(wave.dif,level);
  if(h!==0)wave.bars++;
  // A confirmed structure stays in history. A renewed move toward the
  // reference peak can start a separate dulling episode in the same wave.
  const resumed=previousDif!==undefined&&level>sign*previousDif;
  const wasPending=pending[side]!==undefined;
  if(wave.bars>=2&&(!wave.formed||resumed)){
   for(const ref of references[side]){
    if(price>ref.price&&wave.dif<=ref.dif){
     pending[side]=Math.max(pending[side]??-Infinity,ref.dif);
    }
   }
  }
  if(!wasPending&&pending[side]!==undefined){
   events.push({index:i,side,state:'dull'});
   wave.formed=false;
  }
  for(const direction of ['top','bottom'] as const){
   const ref=pending[direction];
   if(ref===undefined||previousDif===undefined)continue;
   if(direction===side&&!wasPending)continue;
   const polarity=direction==='top'?1:-1;
   const cleared=polarity*value>ref;
   const turned=polarity*value<polarity*previousDif;
   if(!cleared&&!turned)continue;
   events.push({index:i,side:direction,state:cleared?'cleared':'formed'});
   if(direction===side)wave.formed=!cleared;
   delete pending[direction];
  }
  previousDif=value;
 }
 return events;
}

/** Regular divergence between successive joint price/DIF pivots. Emit on
 * the second following bar, when both sides of the newer pivot are known. */
export function macdDivergences(bars:readonly {high:number;low:number}[],dif:readonly (number|null)[]){
 const events:{index:number;side:Side;state:'divergence'}[]=[];
 const previous:Partial<Record<Side,Peak>>={};
 let valid=0;
 for(let i=0;i<bars.length;i++){
  if(dif[i]==null||!Number.isFinite(dif[i])||!Number.isFinite(bars[i].high)||!Number.isFinite(bars[i].low)){
   valid=0;delete previous.top;delete previous.bottom;continue;
  }
  if(++valid<5)continue;
  const pivot=i-2,neighbors=[pivot-2,pivot-1,pivot+1,pivot+2];
  for(const side of ['top','bottom'] as const){
   const key=side==='top'?'high':'low',sign=side==='top'?1:-1;
   const price=sign*bars[pivot][key],level=sign*dif[pivot]!;
   if(!neighbors.every(n=>price>sign*bars[n][key]&&level>sign*dif[n]!))continue;
   const ref=previous[side];
   if(ref&&price>ref.price&&level<ref.dif)events.push({index:i,side,state:'divergence'});
   previous[side]={price,dif:level};
  }
 }
 return events;
}
