import {moduleUrl} from './test-load-ts.mjs';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const {compute,indicatorPane}=await import(moduleUrl('indicators'));
const {advancedCatalog,advancedDefaults,advancedParams}=await import(moduleUrl('advancedCatalog'));
const {tdxCatalog}=await import(moduleUrl('tdxIndicators'));
function fixture(period){
 const slots={'1d':[54000],'120m':[41400,54000],'60m':[37800,41400,50400,54000]}[period];
 return Array.from({length:240},(_,i)=>{
  const session=Math.floor(i/slots.length),day=Math.floor(session/5)*7+session%5;
  const time=Date.UTC(2025,0,6)/1000-8*3600+day*86400+slots[i%slots.length];
  const date=new Date((time+8*3600)*1000).toISOString().slice(0,10);
  const c=100+i*.1+Math.sin(i/4)*5,volume=i%7?100+i:0;
  return {symbol:'SZ.000001',period,time,open:c-.2,high:c+1,low:c-1,close:c,volume,
   turnover:(c-.08)*volume,fields:{chip_winner_95:(i%11)/10,chip_cost_85:c*(1+.05*Math.sin(i/7))},
   session:'regular',trade_date:date,session_date:date+':regular'};
 });
}
const periods=['1d','60m','120m'],datasets=periods.flatMap(period=>{
 const rows=fixture(period);
 return [rows,rows.slice(0,1),[],rows.map(b=>({...b,open:100.1,high:100.1,low:100.1,close:100.1,volume:0,turnover:0}))];
});
const rows=datasets[0];
const cases=Object.keys(advancedCatalog).flatMap(name=>{
 const period=tdxCatalog[name]?.period||'1d',base=periods.indexOf(period)*4;
 assert.ok(base>=0,'fixture for '+period);
 const params='period'in advancedDefaults[name]?[{},{period:1},{period:5},{period:2000}]:[{}];
 return [0,1,2,3].flatMap(i=>params.map(p=>({name,params:p,dataset:base+i})));
});
const expected=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c','import sys,json;from app.indicators import calculate;x=json.load(sys.stdin);print(json.dumps([calculate(x["datasets"][t["dataset"]],t["name"],t["params"]) for t in x["cases"]]))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify({datasets,cases}),encoding:'utf8',maxBuffer:16*1024*1024}));
for(let t=0;t<cases.length;t++){
 const {name,params,dataset}=cases[t],data=datasets[dataset],actual=compute(data,name,JSON.stringify(params));
 assert.deepEqual(Object.keys(actual),Object.keys(expected[t]),name);
 if(name.endsWith('RVOL')&&dataset%4===0)assert.ok(Object.values(actual).flat().some(v=>v!==null&&v>0),name+' has a matching session baseline');
 for(const [key,arr] of Object.entries(actual)){assert.equal(arr.length,data.length);arr.forEach((x,i)=>{const y=expected[t][key][i];if(x===null||y===null)assert.equal(x,y,`${name} ${key} ${i} warmup`);else assert.ok(Number.isFinite(x)&&Math.abs(x-y)<1e-8*Math.max(1,Math.abs(y)),`${name} ${key} ${i}: ${x} vs ${y}`)})}
 const prefix=compute(data.slice(0,100),name,JSON.stringify(params));for(const key of Object.keys(actual)){const confirmedLast=name==='SIXPULSE_SIGNAL'&&['ENTRY','EXIT','STATE'].includes(key),size=confirmedLast?Math.max(0,prefix[key].length-1):prefix[key].length;assert.deepEqual(prefix[key].slice(0,size),actual[key].slice(0,size),name+' no future prices');if(confirmedLast&&prefix[key].length)assert.equal(prefix[key].at(-1),null)}
}
for(const [name,item] of Object.entries(advancedCatalog)){
 assert.equal(indicatorPane({name}),item.pane);
 for(const f of item.fields)for(const invalid of [null,'3',true,-1,...(f.min===0?[]:[0]),Infinity,NaN,2001])assert.throws(()=>advancedParams(name,{[f.key]:invalid}),`${name} ${f.key}`);
}
const supertrend=compute(rows,'SUPERTREND','{}');assert.ok(supertrend.direction.includes(1)&&supertrend.direction.includes(-1));
assert.equal(compute(rows,'SAR','{}').main[0],null);
console.log(`${Object.keys(advancedCatalog).length} indicators: ${cases.length} full frontend/backend parity cases; warmup, flat/empty, invalid parameters, pane defaults and no lookahead passed`);
