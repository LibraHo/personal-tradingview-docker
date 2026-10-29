import ts from 'typescript';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const load=async file=>{
 let source=readFileSync(new URL(file,import.meta.url),'utf8');
 source=source.replace("import {formula} from './formula';",'const formula=()=>()=>[];');
 return import('data:text/javascript;base64,'+Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString('base64'));
};
const {compute}=await load('./src/indicators.ts');
const bars=Array.from({length:30},(_,i)=>({close:i+1}));
assert.deepEqual(Object.keys(compute(bars,'EMA','{"periods":[5,10,20]}')),['EMA5','EMA10','EMA20']);
assert.equal(compute(bars,'SMA','{"periods":[5,10,20]}').MA5[4],3);
assert.equal(compute(bars,'EMA','{"period":7}').main.length,30,'legacy single period remains compatible');
assert.throws(()=>compute(bars,'EMA','{"periods":[0,10]}'),/周期/);
console.log('Multiple EMA/MA periods, numeric output, legacy compatibility and invalid parameters passed');
