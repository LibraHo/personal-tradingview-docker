import ts from 'typescript';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const js=ts.transpileModule(readFileSync(new URL('./src/extraIndicators.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {computeExtra,extraDefaults}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const bars=Array.from({length:160},(_,i)=>{const c=100+i*.3+Math.sin(i)*5;return {time:i,open:c-.2,high:c+1,low:c-1,close:c,volume:i%7?100+i:0}});
const cases=Object.keys(extraDefaults).flatMap(name=>[{}, {period:1,smoothK:1,smoothD:1},{period:5,smoothK:2,smoothD:3},{period:2000}].map(params=>({name,params})));
const backend=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c','import sys,json;from app.indicators import calculate;x=json.load(sys.stdin);print(json.dumps([calculate(x["bars"],t["name"],t["params"]) for t in x["cases"]]))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify({bars,cases}),encoding:'utf8'}));
for(let t=0;t<cases.length;t++){
 const {name,params}=cases[t],a=computeExtra(bars,name,params),b=backend[t];
 assert.deepEqual(Object.keys(a),Object.keys(b));
 for(const key of Object.keys(a)){assert.equal(a[key].length,bars.length);a[key].forEach((x,i)=>{if(x===null||b[key][i]===null)assert.equal(x,b[key][i],`${name} ${key} warmup ${i}`);else assert.ok(Math.abs(x-b[key][i])<1e-8,`${name} ${key} parity ${i}`)})}
 const prefix=computeExtra(bars.slice(0,100),name,params);for(const key of Object.keys(a))assert.deepEqual(prefix[key],a[key].slice(0,100));
}
for(const name of Object.keys(extraDefaults)){
 for(const period of [0,-1,1.5,2001,true,'20',null,Infinity,NaN])assert.throws(()=>computeExtra(bars,name,{period}));
 for(const arr of Object.values(computeExtra([],name,{})))assert.deepEqual(arr,[]);
}
assert.deepEqual(computeExtra([10,12,11,14].map((close,i)=>({close,high:close+1,low:close-1,volume:i+1})),'OBV',{}).main,[0,2,-1,3]);
assert.equal(computeExtra(bars,'NOT_BUILTIN',{}),null);
assert.deepEqual(computeExtra(Array.from({length:100},()=>({close:100.1,high:100.1,low:100.1,volume:1})),'CCI',{}).main,[...Array(19).fill(null),...Array(81).fill(0)]);
console.log('10 indicators: 40 cross-language cases, warmup, no lookahead, empty input and invalid parameters passed');
