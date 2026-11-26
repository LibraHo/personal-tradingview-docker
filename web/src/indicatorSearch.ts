const aliases:Record<string,string>={
 HOURLY_RVOL:'量比 一小时 1小时 60分钟 同时段 放量 RVOL',
 DAILY_RVOL:'量比 日量比 全天 日均量 相对成交量 RVOL',
 HALFDAY_RVOL:'量比 同时段相对成交量 上午 下午 半日放量 RVOL',
 MSIGM8:'MACD SHORT MAI MACD突破',
 SIXPULSE:'六脉副图 六脉神剑 六项共振 Mai',
 SIXPULSE_SIGNAL:'六脉主图 六脉神剑 上下车 Mai',
 CHIEF_RESONANCE:'主升吸筹共振 主图 共振买点',
 CHIEF_RESONANCE_PANE:'主升吸筹共振 副图 共振买点',
 HAOYUNLAI_WAVE:'好运来 抄底王 抄底预警 转强确认 破位移出 2小时 120分钟',
 ORB5:'开盘区间 开盘高低线',VOLUME:'成交量 量能',SMA:'MA 简单均线',EMA:'指数均线',
};
export function searchIndicators(names:string[],labels:Record<string,string>,query:string):string[]{
 const terms=query.trim().toLowerCase().split(/\s+/).filter(Boolean);
 return names.filter(name=>{const text=`${name} ${labels[name]||''} ${aliases[name]||''}`.toLowerCase();return terms.every(term=>text.includes(term))});
}
