import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {loadTS} from './test-load-ts.mjs';

const name='HAOYUNLAI_WAVE';
const code=[
 'import json, sys',
 'sys.path.insert(0, "tests")',
 'from app.indicators import calculate',
 'from test_haoyunlai_wave import rows',
 'bars=rows()',
 'print(json.dumps([bars, calculate(bars, "HAOYUNLAI_WAVE")]))',
].join('\n');
const [bars,expected]=JSON.parse(execFileSync(process.env.PYTHON||'python',['-X','utf8','-c',code],{encoding:'utf8'}));
const {computeTdx,tdxAvailable}=await loadTS('tdxIndicators');
const {searchIndicators}=await loadTS('indicatorSearch');
for(const [key,values] of Object.entries(computeTdx(bars,name))){
 assert.equal(values.length,expected[key].length);
 values.forEach((v,i)=>{
  const other=expected[key][i];
  if(v===null||other===null)assert.equal(v,other,`${key} at ${i}`);
  else assert.ok(Math.abs(v-other)<1e-10,`${key} at ${i}`);
 });
}
assert.equal(tdxAvailable(name,'CN'),true);
assert.equal(tdxAvailable(name,'US'),false);
assert.equal(tdxAvailable(name,'SZ.399001'),false);
assert.deepEqual(computeTdx(bars.map(b=>({...b,period:'1d'})),name), computeTdx(bars,name));
assert.deepEqual(searchIndicators([name],{},'好运来 2小时'),[name]);
console.log('Haoyunlai Wave browser/backend parity, symbol scope, period and search passed.');
