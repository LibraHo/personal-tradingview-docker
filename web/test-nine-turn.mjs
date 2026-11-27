import assert from 'node:assert/strict';
import {loadTS} from './test-load-ts.mjs';

const {nineTurnCounts,nineTurnLabels}=await loadTS('nineTurn');
const bars=closes=>closes.map(close=>({close}));
const rising=Array.from({length:22},(_,i)=>10+i);
const nums=(prices,side)=>nineTurnLabels(nineTurnCounts(bars(prices))[side]).map(label=>label.count);
const seq=n=>Array.from({length:n},(_,i)=>i+1);

assert.deepEqual(nums(rising.slice(0,9),'上涨计数'),[]);
assert.deepEqual(nums(rising.slice(0,10),'上涨计数'),seq(6));
assert.deepEqual(nums(rising.slice(0,12),'上涨计数'),seq(8));
assert.deepEqual(nums([...rising.slice(0,12),rising[8]],'上涨计数'),[]);
assert.deepEqual(nums([...rising.slice(0,13),0],'上涨计数'),seq(9));
assert.deepEqual(nums(rising,'上涨计数'),[...seq(9),...seq(9)]);
assert.deepEqual(nums([...rising].reverse(),'下跌计数'),[...seq(9),...seq(9)]);
const flip=nineTurnCounts(bars([...rising.slice(0,12),1,1,1]));
assert.deepEqual(flip['下跌计数'].slice(-3),[1,2,3]);
assert.deepEqual(nineTurnLabels(flip['上涨计数']),[]);
assert.deepEqual(nineTurnLabels(nineTurnCounts(bars(rising.slice(0,13)))['上涨计数']).map(l=>l.index),seq(9).map(n=>n+3));
console.log('NINE warmup, provisional labels, equality, reversals, completion and consecutive groups passed');
