import type {IChartApi} from 'lightweight-charts';

/** Keep candles readable regardless of the amount of history in the cache. */
export function recentLogicalRange(total:number,width:number){
 if(!Number.isFinite(total)||total<=0)return null;
 const capacity=Math.max(40,Math.min(160,Math.round((width>0?width:960)/8)));
 return {from:Math.max(0,total-capacity),to:total-1+6};
}
export function resetPriceScales(chart:IChartApi){
 for(const pane of chart.panes())pane.priceScale('right').applyOptions({autoScale:true,mode:0,scaleMargins:{top:.12,bottom:.12}});
}
export function markViewportReady(state:{ready:boolean;suppressSyncUntil:number},ready:boolean,now:number){
 if(ready&&(!state.ready||!Number.isFinite(state.suppressSyncUntil)))state.suppressSyncUntil=now+350;
 state.ready=ready;
}
export function resetChartViewport(chart:IChartApi,total:number){
 const scale=chart.timeScale(),range=recentLogicalRange(total,scale.width());if(!range)return;
 resetPriceScales(chart);
 scale.applyOptions({rightOffset:6,minBarSpacing:2});
 scale.setVisibleLogicalRange(range);
}
