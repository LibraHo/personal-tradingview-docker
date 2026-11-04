import {loadTS} from './test-load-ts.mjs';
import assert from 'node:assert/strict';
const {compute}=await loadTS('indicators');
const bars=Array.from({length:30},(_,i)=>({close:i+1}));
assert.deepEqual(Object.keys(compute(bars,'EMA','{"periods":[5,10,20]}')),['EMA5','EMA10','EMA20']);
assert.equal(compute(bars,'SMA','{"periods":[5,10,20]}').MA5[4],3);
assert.equal(compute(bars,'EMA','{"period":7}').main.length,30,'legacy single period remains compatible');
assert.throws(()=>compute(bars,'EMA','{"periods":[0,10]}'),/周期/);
console.log('Multiple EMA/MA periods, numeric output, legacy compatibility and invalid parameters passed');
