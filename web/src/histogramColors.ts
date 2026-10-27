/** Signed MACD histogram: light colours indicate shrinking magnitude. */
export function selectedColor(colors:Record<string,string>|undefined,key:string,fallback:string):string {
 const value=colors?.[key];return value&&/^#[0-9a-f]{6}$/i.test(value)?value:fallback;
}
export function indicatorDefaultColor(name:string,label:string,index=0):string {
 const colors=['#74a9ff','#ffc86d','#9e89fa','#65d6bb','#f58291','#d3dce9'];
 const base:Record<string,number>={EMA:0,SMA:1,VWAP:2,BBI:3,BOLL:4,ATR:5,MACD:0,DMI:3,RSI:1,VOLUME:3};
 const line:Record<string,number>={main:0,macd:0,signal:1,hist:2,mid:0,upper:1,lower:2,plus_di:0,minus_di:1,adx:2,volume:0,average:1};
 return colors[((base[name]||0)+(line[label.toLowerCase()]??index))%colors.length];
}
export function macdHistogramColor(value:number, previous:number|null|undefined,colors?:Record<string,string>):string {
 const prior=previous!=null&&Number.isFinite(previous)?previous:null;
 if(value>=0)return prior!==null&&prior>=0&&value<prior?selectedColor(colors,'positiveWeak','#B2DFDB'):selectedColor(colors,'positiveStrong','#26A69A');
 return prior!==null&&prior<0&&value>prior?selectedColor(colors,'negativeWeak','#FFCDD2'):selectedColor(colors,'negativeStrong','#FF5252');
}

/** Match each volume column to its candle, including an unchanged close. */
export function volumeColor(open:number, close:number,colors?:Record<string,string>):string {
 return close>=open?selectedColor(colors,'volumeUp','#45caa6'):selectedColor(colors,'volumeDown','#ed6b7d');
}
