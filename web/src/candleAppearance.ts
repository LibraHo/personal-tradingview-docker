import type {CandlestickSeriesOptions} from 'lightweight-charts';
export type CandleAppearance={style:'solid'|'hollow-up'|'hollow';upColor:string;downColor:string;wickUpColor:string;wickDownColor:string;borderUpColor:string;borderDownColor:string;showWicks:boolean;showBorders:boolean};
const green='#45caa6',red='#ed6b7d';
export function defaultCandleAppearance(market:'US'|'CN'):CandleAppearance{
 const upColor=market==='CN'?red:green,downColor=market==='CN'?green:red;
 return {style:'solid',upColor,downColor,wickUpColor:upColor,wickDownColor:downColor,borderUpColor:upColor,borderDownColor:downColor,showWicks:true,showBorders:false};
}
export function normalizeCandleAppearance(raw:unknown,market:'US'|'CN'):CandleAppearance{
 const value=raw&&typeof raw==='object'&&!Array.isArray(raw)?raw as Record<string,unknown>:{},result=defaultCandleAppearance(market);
 for(const field of ['upColor','downColor','wickUpColor','wickDownColor','borderUpColor','borderDownColor'] as const)if(typeof value[field]==='string'&&/^#[0-9a-f]{6}$/i.test(value[field] as string))result[field]=value[field] as string;
 if(['solid','hollow-up','hollow'].includes(String(value.style)))result.style=value.style as CandleAppearance['style'];
 for(const field of ['showWicks','showBorders'] as const)if(typeof value[field]==='boolean')result[field]=value[field] as boolean;
 return result;
}
export function candleBodyColor(open:number,close:number,appearance:CandleAppearance){
 return appearance.style==='hollow'||appearance.style==='hollow-up'&&close>=open?'transparent':close>=open?appearance.upColor:appearance.downColor;
}
export function candleSeriesOptions(appearance:CandleAppearance):Partial<CandlestickSeriesOptions>{
 const {upColor,downColor,wickUpColor,wickDownColor,borderUpColor,borderDownColor}=appearance;
 return {upColor,downColor,wickUpColor,wickDownColor,borderUpColor,borderDownColor,borderVisible:appearance.style!=='solid'||appearance.showBorders,wickVisible:appearance.showWicks};
}
export function volumePalette(appearance:CandleAppearance,custom?:Record<string,string>){
 const valid=(value:unknown)=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
 return {...custom,volumeUp:valid(custom?.volumeUp)?custom!.volumeUp:appearance.upColor,volumeDown:valid(custom?.volumeDown)?custom!.volumeDown:appearance.downColor};
}
