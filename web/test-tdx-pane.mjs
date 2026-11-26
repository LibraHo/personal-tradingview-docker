import ts from 'typescript';import fs from 'node:fs';import assert from 'node:assert/strict';
const spec=JSON.parse(fs.readFileSync('app/tdx_formulas.json','utf8'));
let src=fs.readFileSync('web/src/tdxChart.ts','utf8').replace(/^import .*$/gm,'');
src=`const CandlestickSeries='candle',HistogramSeries='hist',LineSeries='line';const tdxCatalog=${JSON.stringify(spec.indicators)};const createSeriesMarkers=(series,markers)=>{globalThis.calls.push({pane:series.pane,markers});return {detach(){}}};`+src;
const js=ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {drawTdx}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
globalThis.calls=[];const chart={addSeries:(kind,options,pane)=>({pane,setData(){},applyOptions(){}})};
for(const name of ['RED_GREEN_SWING','YAOGU_BUY','YAOGU_TRACK','FULAI']){
 const item=spec.indicators[name],values=Object.fromEntries(Object.keys(item.outputs).map(k=>[k,[1,1]])),main=[],series=[],cleanup=[];
 const pane=item.pane==='main'?0:1;
 drawTdx(chart,[{time:1,open:1,close:1,high:2,low:0},{time:2,open:1,close:1,high:2,low:0}],{name,id:name},values,pane,series,main,cleanup);
 if(pane){assert.equal(main.length,0);assert.equal(globalThis.calls.at(-1).pane,1);assert.equal(cleanup.length,1)}else assert.ok(main.length>0);
}
console.log('Signal placement: subchart signals stay in subchart; Fulai stays on main chart');
