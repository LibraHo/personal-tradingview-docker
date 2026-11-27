import assert from 'node:assert/strict';
import {loadTS} from './test-load-ts.mjs';
const {compute}=await loadTS('indicators');
const {followedDefense,planPrice,displayPlanPrice,structureReferences,newPlanCondition,newPlanDetails,estimatePlanCondition,planReferencePrices,planRiskValues}=await loadTS('tradePlanAnalysis');
const bars=Array.from({length:100},(_,i)=>{
  const close=6+Math.sin(i*.3)*.8+i*.002;
  return {time:i+1,open:close-.05,close,high:close+.15,low:close-.15,volume:100+i,
    session:'regular',trade_date:'2026-11-20',session_date:'2026-11-20:regular'};
});
const original=structuredClone(bars),last=bars.at(-1);
// Friday to Monday is one chart interval. Both closes use the line at their own candle.
const trendBars=[1,2,5,6].map((time,i)=>({...last,time,close:[10,11,11.5,13.5][i]}));
const trend={...newPlanCondition('TREND','1d'),params:{time1:1,price1:10,time2:2,price2:11}};
assert.equal(estimatePlanCondition(trendBars,trend).price,13);
assert.equal(estimatePlanCondition(trendBars,trend).met,true);
const crossedEarlier=trendBars.map((b,i)=>i===2?{...b,close:12.5}:b);
assert.equal(estimatePlanCondition(crossedEarlier,trend).met,false);
const breakdown=crossedEarlier.map((b,i)=>i===3?{...b,close:12.5}:b);
assert.equal(estimatePlanCondition(breakdown,{...trend,signal:'below'}).met,true);
assert.equal(estimatePlanCondition(trendBars.map((b,i)=>i===3?{...b,close:13}:b),trend).met,false);
assert.equal(estimatePlanCondition(trendBars.slice(1),trend).met,null);
assert.equal(estimatePlanCondition(trendBars,{...trend,params:{}}).met,null);
const trial=price=>[...bars.slice(0,-1),{...last,close:price,high:Math.max(last.high,price),low:Math.min(last.low,price)}];
const conditionMet=(condition,price)=>{
  if(condition.source==='PRICE')return condition.signal==='above'?price>=condition.threshold:price<=condition.threshold;
  const values=compute(trial(price),condition.source,JSON.stringify(condition.params));
  if(condition.source==='SIXPULSE'){
    const reds=values.SCORE.at(-1),count=condition.signal==='reds'?reds:6-reds;
    return count>=condition.threshold;
  }
  let difference;
  if(condition.source==='MACD')difference=values.macd.at(-1)-values.signal.at(-1);
  else if(condition.source==='RSI')difference=values.main.at(-1)-condition.threshold;
  else difference=price-values[condition.line].at(-1);
  return ['above','bullish'].includes(condition.signal)?difference>=0:difference<=0;
};
const cases=[];
for(const source of ['SMA','EMA','BBI','VWAP','MACD','RSI','PRICE']){
  for(const exit of [false,true]){
    const condition=newPlanCondition(source,'1d',exit);
    if(source==='PRICE')condition.threshold=6;
    cases.push(condition);
  }
}
for(const line of ['upper','mid','lower']){
  for(const exit of [false,true])cases.push({...newPlanCondition('BOLL','1d',exit),line});
}
for(const signal of ['reds','greens'])for(let threshold=1;threshold<=6;threshold++){
  cases.push({...newPlanCondition('SIXPULSE','15m'),signal,threshold});
}
let boundaries=0;
for(const condition of cases){
  const result=estimatePlanCondition(bars,condition);
  assert.equal(result.met,conditionMet(condition,last.close));
  if(result.price!==null){
    assert.ok(conditionMet(condition,result.price),JSON.stringify(condition));
    assert.ok([-.01,.01].some(offset=>!conditionMet(condition,Number((result.price+offset).toPrecision(14)))),`${condition.source} tick boundary`);
    boundaries++;
  }
}
assert.ok(boundaries>=25,`expected boundaries, got ${boundaries}`);
const defaults=newPlanDetails('1w');
assert.equal(defaults.entry.items[0].period,'1w');
assert.equal(defaults.exit.items[0].threshold,3);
const inherited=newPlanCondition('EMA','1d',false,[{id:'chart',name:'EMA',params:'{"periods":[5,20,60]}',visible:true}]);
assert.deepEqual(inherited.params,{period:20});
const invalid=newPlanCondition('SIXPULSE','1d',false,[{id:'chart',name:'SIXPULSE',params:'null',visible:true}]);
assert.equal(invalid.params.fast,8);
assert.equal(estimatePlanCondition([],newPlanCondition('SIXPULSE','1d')).met,null);
const references=planReferencePrices(bars,'1d',6.5);
assert.ok(references.some(row=>row.label==='前 20 根低点'));
assert.ok(references.some(row=>row.label.includes('ATR')));
assert.ok(references.some(row=>row.label.includes('六绿')));
assert.ok(references.every(row=>row.bar_time===last.time&&row.period==='1d'));
assert.deepEqual(planRiskValues(null,null,null,null),{perShare:null,loss:null,percent:null,overBudget:false});
assert.equal(planRiskValues(10,9,200,100).overBudget,true);
assert.equal(planRiskValues(10,11,200,100).loss,null);
assert.deepEqual(bars,original);
console.log(`Trading plans passed ${cases.length} conditions and ${boundaries} full-formula price boundaries, chart parameters, risk and references`);

assert.equal(planPrice(41.057500000000005),41.0575);
for(const [value,expected] of [[3.555555555,'3.5556'],[41.057500000000005,'41.0575'],[100,'100'],[0,'0'],[null,'—'],[0.00000001,'0.00000001']])
  assert.equal(displayPlanPrice(value),expected);
const shelf = Array.from({length:24},(_,i)=>{
  const close=[100,101,103,101,100,99][i%6];
  return {...last,time:i+1,close,high:close+0.5,low:close-0.5};
});
const current={...last,time:25,high:999,low:1};
const structure=structureReferences([...shelf,current],'1d');
for(const [label,price] of [['前高',103.5],['前低',98.5],['震荡平台上沿',103.5],['震荡平台下沿',98.5]])
  assert.ok(structure.some(r=>r.label===label&&r.price===price&&r.bar_time<25));
assert.deepEqual(structureReferences(shelf.slice(0,4),'1d'),[]);
assert.deepEqual(structureReferences(shelf.map((b,i)=>({...b,high:100+i,low:99+i})),'1d'),[]);

const ema7 = planReferencePrices(bars,'1d',null,[{id:'ema',name:'EMA',params:'{"period":7}',visible:true}])
  .find(row=>row.condition?.source==='EMA');
assert.equal(ema7.condition.params.period,7);
assert.equal(followedDefense(bars,ema7,null),ema7.price);
