import assert from 'node:assert/strict';
import {loadTS} from './test-load-ts.mjs';
const {macdStructure}=await loadTS('macdStructure');

function check(prices,dif,hist,expected){
 for(const side of ['top','bottom']){
  const sign=side==='top'?1:-1;
  const bars=prices.map(close=>({close:200+sign*close}));
  const values=dif.map(value=>value===null?null:sign*value);
  const histogram=hist.map(value=>sign*value);
  const events=expected.map(([index,state])=>({index,side,state}));
  for(let count=1;count<=prices.length;count++){
   assert.deepEqual(macdStructure(bars.slice(0,count),values.slice(0,count),histogram.slice(0,count)),events.filter(event=>event.index<count));
  }
 }
}
const prices=[100,120,125,100,99,126,128,127];
const dif=[-1,15,18,-3,-4,9,14,13];
const hist=[-1,3,1,-3,-2,1,2,1];
check(prices,dif,hist,[[6,'dull'],[7,'formed']]);
check(prices,[...dif.slice(0,7),19],hist,[[6,'dull'],[7,'cleared']]);
check(prices,[...dif.slice(0,5),18,19,20],hist,[]);
check([100,120,125,100,99,122,123,124],dif,hist,[]);
check(prices,[...dif.slice(0,6),14.98,14.90],hist,[[6,'dull']]);
check(prices,[...dif.slice(0,4),null,...dif.slice(5)],hist,[]);
// Two successive dips and recoveries within a single histogram wave.
check([...prices,130,126,129,132],[...dif,15,14,16,19],[...hist,1,1,1,1],
 [[6,'dull'],[7,'formed'],[8,'dull'],[9,'formed'],[10,'dull'],[11,'cleared']]);
// The third wave clears the adjacent DIF peak, while the older peak still qualifies.
check([90,125,128,100,95,112,118,97,100,129,130,133,134],
 [-1,25,30,-4,-3,15,18,-1,-1,15,16,19,17],
 [-1,1,1,-1,-1,1,1,-1,-1,1,1,1,1],[[10,'dull'],[12,'formed']]);
// In the author's precision example 106 to 102 is flat. A change to 99 is a turn.
check([...prices,126],[-1,115,120,-3,-4,105,106,102,99],[...hist,1],[[6,'dull'],[8,'formed']]);
console.log('PASS mirrored peaks, one- and two-wave references, repeated episodes, minimum bars, precision, gaps and prefix stability.');

const {macdDivergences}=await loadTS('macdStructure');
for(const [side,sign] of [['top',1],['bottom',-1]]){
 const bars=[1,2,6,3,1,2,8,2,1].map(v=>({high:50+sign*v+1,low:50+sign*v-1}));
 const values=[0,1,5,2,0,1,4,2,0].map(v=>sign*v);
 const event={index:8,side,state:'divergence'};
 for(let n=1;n<=9;n++)assert.deepEqual(macdDivergences(bars.slice(0,n),values.slice(0,n)),n<9?[]:[event]);
 const equal=[...values];equal[6]=values[2];
 assert.deepEqual(macdDivergences(bars,equal),[]);
 const gap=[...values];gap[4]=null;
 assert.deepEqual(macdDivergences(bars,gap),[]);
}
console.log('PASS regular bullish/bearish divergence, equal peaks, missing DIF and signal timing.');
