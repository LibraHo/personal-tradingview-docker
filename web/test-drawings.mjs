import ts from 'typescript';import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const js=ts.transpileModule(readFileSync(new URL('./src/drawingTools.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {fibPrices}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const levels=fibPrices({points:[{time:1,price:100},{time:2,price:200}]});
assert.equal(levels.find(x=>x.ratio===0).price,200);assert.equal(levels.find(x=>x.ratio===1).price,100);assert.equal(levels.find(x=>x.ratio===.618).price,138.2);
assert.equal(fibPrices({points:[{time:1,price:200},{time:2,price:100}]}).find(x=>x.ratio===.5).price,150);
assert.deepEqual(fibPrices({points:[{time:1,price:1},{time:1,price:2}]}),[]);
console.log('Fibonacci: ascending, descending, endpoints, retracement and invalid anchors passed');
