/** Signed MACD histogram: light colours indicate shrinking magnitude. */
export function macdHistogramColor(value:number, previous:number|null|undefined):string {
 const prior=previous!=null&&Number.isFinite(previous)?previous:null;
 if(value>=0)return prior!==null&&prior>=0&&value<prior?'#B2DFDB':'#26A69A';
 return prior!==null&&prior<0&&value>prior?'#FFCDD2':'#FF5252';
}

/** Match each volume column to its candle, including an unchanged close. */
export function volumeColor(open:number, close:number):string {
 return close>=open?'#45caa6':'#ed6b7d';
}
