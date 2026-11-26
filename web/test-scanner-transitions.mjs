import assert from 'node:assert/strict';
import {loadTS} from './test-load-ts.mjs';
const {scanBars,operand}=await loadTS('scanner');
const definitions={cross_above:(p,c)=>p<=3&&c>3,cross_below:(p,c)=>p>=3&&c<3,reach:(p,c)=>p<3&&c>=3,fall:(p,c)=>p>3&&c<=3,enter_eq:(p,c)=>p!==3&&c===3,rise_eq:(p,c)=>p<3&&c===3,fall_eq:(p,c)=>p>3&&c===3};
for(const [op,expected] of Object.entries(definitions))for(let p=0;p<=6;p++)for(let c=0;c<=6;c++){
 const bars=[p,c].map((close,i)=>({time:i*86400,open:close,high:close,low:close,close,volume:100}));
 const r={left:operand('PRICE'),op,right:{...operand('NUMBER'),value:3}};
 assert.equal(scanBars(bars,[r],'all',1,true).match,expected(p,c),`${op}: ${p} -> ${c}`);
}
console.log('343 transition boundary cases passed');
