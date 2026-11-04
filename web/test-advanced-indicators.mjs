import {moduleUrl} from './test-load-ts.mjs';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const {compute,indicatorPane}=await import(moduleUrl('indicators'));
const {advancedCatalog,advancedDefaults,advancedParams}=await import(moduleUrl('advancedCatalog'));
const rows=Array.from({length:240},(_,i)=>{const c=100+i*.1+Math.sin(i/4)*5;return {time:i,open:c-.2,high:c+1,low:c-1,close:c,volume:i%7?100+i:0,session:'regular',trade_date:'2026-11-05',session_date:'2026-11-05:regular'}});
const datasets=[rows,rows.slice(0,1),[],rows.map(b=>({...b,open:100.1,high:100.1,low:100.1,close:100.1,volume:0}))];
const cases=Object.keys(advancedCatalog).flatMap(name=>datasets.flatMap((_,dataset)=>[{},...('period'in advancedDefaults[name]?[{period:1},{period:5},{period:2000}]:[{}])].map(params=>({name,params,dataset}))));
const expected=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c','import sys,json;from app.indicators import calculate;x=json.load(sys.stdin);print(json.dumps([calculate(x["datasets"][t["dataset"]],t["name"],t["params"]) for t in x["cases"]]))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify({datasets,cases}),encoding:'utf8',maxBuffer:16*1024*1024}));
for(let t=0;t<cases.length;t++){
 const {name,params,dataset}=cases[t],data=datasets[dataset],actual=compute(data,name,JSON.stringify(params));
 assert.deepEqual(Object.keys(actual),Object.keys(expected[t]),name);
 for(const [key,arr] of Object.entries(actual)){assert.equal(arr.length,data.length);arr.forEach((x,i)=>{const y=expected[t][key][i];if(x===null||y===null)assert.equal(x,y,`${name} ${key} ${i} warmup`);else assert.ok(Number.isFinite(x)&&Math.abs(x-y)<1e-8*Math.max(1,Math.abs(y)),`${name} ${key} ${i}: ${x} vs ${y}`)})}
 const prefix=compute(data.slice(0,100),name,JSON.stringify(params));for(const key of Object.keys(actual))assert.deepEqual(prefix[key],actual[key].slice(0,100),name+' no lookahead');
}
for(const [name,item] of Object.entries(advancedCatalog)){
 assert.equal(indicatorPane({name}),item.pane);
 for(const f of item.fields)for(const invalid of [null,'3',true,-1,0,Infinity,NaN,2001])assert.throws(()=>advancedParams(name,{[f.key]:invalid}),`${name} ${f.key}`);
}
const supertrend=compute(rows,'SUPERTREND','{}');assert.ok(supertrend.direction.includes(1)&&supertrend.direction.includes(-1));
assert.equal(compute(rows,'SAR','{}').main[0],null);
console.log(`${Object.keys(advancedCatalog).length} indicators: ${cases.length} full frontend/backend parity cases; warmup, flat/empty, invalid parameters, pane defaults and no lookahead passed`);
