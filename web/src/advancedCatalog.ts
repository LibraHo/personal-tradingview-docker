type Field={key:string;label:string;value:number;step?:number;max?:number};
type Entry={label:string;pane:'main'|'separate';description:string;fields:Field[]};
const length=(value:number,key='period',label='计算周期'):Field=>({key,label,value});
const factor=(value:number,key='multiplier',label='ATR 倍数',max=100):Field=>({key,label,value,step:.01,max});
const pair=(fast:number,slow:number)=>[length(fast,'fast','快线周期'),length(slow,'slow','慢线周期')];
export const advancedCatalog:Record<string,Entry>={
 KDJ:{label:'KDJ · 随机指标',pane:'separate',description:'K、D 按 1/N 递归平滑，初值 50；J=3K−2D，可超过 0–100。',fields:[length(9),length(3,'smoothK','K 平滑周期'),length(3,'smoothD','D 平滑周期')]},
 MFI:{label:'MFI · 资金流量指标',pane:'separate',description:'典型价涨跌结合成交量，范围 0–100；不是账户资金净流入。',fields:[length(14)]},
 KC:{label:'KC · Keltner 通道',pane:'main',description:'收盘价 EMA ± Wilder ATR 倍数，可分别调整均线与 ATR 周期。',fields:[length(20),length(10,'atrPeriod','ATR 周期'),factor(2)]},
 SUPERTREND:{label:'Supertrend · 超级趋势',pane:'main',description:'Wilder ATR 趋势线，收盘越过最终边界时翻转；未收线时会随行情变化。',fields:[length(10),factor(3)]},
 SAR:{label:'SAR · 抛物线转向',pane:'main',description:'以圆点显示追踪价位；第二根确定初始方向，反转时重置加速因子。',fields:[factor(.02,'start','初始加速',1),factor(.02,'increment','加速步长',1),factor(.2,'maximum','最大加速',1)]},
 STOCHRSI:{label:'Stoch RSI · 随机 RSI',pane:'separate',description:'使用 Wilder RSI，再计算随机位置与 K/D 平滑；以 0–100 显示。',fields:[length(14,'rsiPeriod','RSI 周期'),length(14,'period','随机窗口'),length(3,'smoothK','K 平滑周期'),length(3,'smoothD','D 平滑周期')]},
 HMA:{label:'HMA · Hull 均线',pane:'main',description:'WMA(2×WMA(C,N/2)−WMA(C,N),√N)，半周期向下取整，根号周期四舍五入。',fields:[length(21)]},
 DEMA:{label:'DEMA · 双重指数均线',pane:'main',description:'2×EMA(C,N)−EMA(EMA(C,N),N)，减少平滑滞后。',fields:[length(20)]},
 TEMA:{label:'TEMA · 三重指数均线',pane:'main',description:'3×一级 EMA−3×二级 EMA+三级 EMA。',fields:[length(20)]},
 TRIX:{label:'TRIX · 三重平滑动量',pane:'separate',description:'三级 EMA 的单根变化率（%），附带 EMA 信号线。',fields:[length(15),length(9,'signal','信号周期')]},
 PPO:{label:'PPO · 百分比价格振荡',pane:'separate',description:'快慢 EMA 差 / 慢 EMA ×100，含信号线与差值柱。',fields:[...pair(12,26),length(9,'signal','信号周期')]},
 AO:{label:'AO · 动量振荡',pane:'separate',description:'中间价 (H+L)/2 的快慢简单均线差；柱色按相邻值升降。',fields:pair(5,34)},
 BIAS:{label:'BIAS · 乖离率',pane:'separate',description:'(收盘价 / 简单均线−1)×100。',fields:[length(6)]},
 ADL:{label:'ADL · 累积派发线',pane:'separate',description:'累计收盘在高低区间的位置×成交量；起点随加载历史变化。',fields:[]},
 CHO:{label:'CHO · 蔡金振荡',pane:'separate',description:'累积派发线的快慢 EMA 差。',fields:pair(3,10)},
 PVT:{label:'PVT · 价量趋势',pane:'separate',description:'累计收盘变动率×成交量，从已加载第一根的 0 开始。',fields:[]},
 BOP:{label:'BOP · 多空力量',pane:'separate',description:'(收盘−开盘)/(最高−最低)，平价 K 线记 0。',fields:[]},
 BBW:{label:'BBW · 布林带宽',pane:'separate',description:'(布林上轨−下轨)/中轨×100，使用总体标准差。',fields:[length(20),factor(2,'stddev','标准差倍数')]},
 BBP:{label:'%B · 布林位置',pane:'separate',description:'(收盘−下轨)/(上轨−下轨)，下轨为 0，上轨为 1。',fields:[length(20),factor(2,'stddev','标准差倍数')]},
 AROON:{label:'Aroon · 趋势时效',pane:'separate',description:'最近高低点距当前的根数，范围 0–100；相同极值取最近一根。',fields:[length(25)]},
};
export const advancedDefaults=Object.fromEntries(Object.entries(advancedCatalog).map(([name,v])=>[name,Object.fromEntries(v.fields.map(f=>[f.key,f.value]))]));
export function advancedParams(name:string,input:Record<string,unknown>):Record<string,number>|null{
 if(!Object.hasOwn(advancedCatalog,name))return null;
 const result:Record<string,number>={};
 for(const f of advancedCatalog[name].fields){const v=Object.hasOwn(input,f.key)?input[f.key]:f.value;if(typeof v!=='number'||!Number.isFinite(v)||v<=0||v>(f.max??2000)||(!f.step&&!Number.isInteger(v)))throw Error(`${f.label}须为有效${f.step?'正数':'整数'}（≤${f.max??2000}）`);result[f.key]=v}
 if('fast'in result&&result.fast>=result.slow)throw Error('慢线周期须大于快线周期');
 if(name==='SAR'&&(result.start>result.maximum||result.increment>result.maximum))throw Error('初始加速和步长不得大于最大加速');
 return result;
}
