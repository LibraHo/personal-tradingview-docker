import ts from 'typescript';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('./src/histogramColors.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {macdHistogramColor:color,volumeColor}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
for(const [value,previous,expected] of [
 [2,1,'#26A69A'],[1,2,'#B2DFDB'],[-2,-1,'#FF5252'],[-1,-2,'#FFCDD2'],
 [1,-1,'#26A69A'],[-1,1,'#FF5252'],[1,null,'#26A69A'],[-1,undefined,'#FF5252'],
 [1,1,'#26A69A'],[-1,-1,'#FF5252'],[0,1,'#B2DFDB'],[1,NaN,'#26A69A'],
]) assert.equal(color(value,previous),expected,`${value} after ${previous}`);
console.log('MACD histogram: 12 color cases passed');
assert.equal(volumeColor(10,11),'#45caa6');
assert.equal(volumeColor(10,9),'#ed6b7d');
assert.equal(volumeColor(10,10),'#45caa6');
console.log('Volume: rising, falling and unchanged candles passed');
