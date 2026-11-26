import {useEffect,useState} from 'react';
const pct=(v:any)=>typeof v==='number'?(v*100).toFixed(1)+'%':'—';
export default function MarketAnalytics({market,onOpen}:{market:string;onOpen:(x:{symbol:string;name:string})=>void}){
 const [state,setState]=useState<any>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 useEffect(()=>{let cancelled=false;let timer:number;async function poll(first=false){try{const r=await fetch('/api/radar/analytics?market='+market+(first&&refresh?'&refresh=true':''));const data=await r.json();if(!r.ok)throw Error(data.detail||'统计请求失败');if(cancelled)return;setState(data);if(data.status==='running')timer=window.setTimeout(()=>void poll(),2500)}catch(e){if(!cancelled)setError(String(e))}}setState(null);setError('');void poll(true);return()=>{cancelled=true;clearTimeout(timer)}},[market,refresh]);
 const r=state?.result;
 return <section><h3>{market==='CN'?'涨停梯队 · 晋级 · 昨日反馈':'自选样本宽度 · 行业扩散'}</h3><button disabled={state?.status==='running'} onClick={()=>setRefresh(x=>x+1)}>刷新扩展统计</button>{error&&<p role="alert">{error}</p>}{state?.status==='running'&&<p role="status">后台统计 {state.done}/{state.total}，关闭页面仍继续。</p>}{state?.error&&<p role="alert">{state.error}</p>}
 {r&&<><p>{r.scope} · 交易日 {r.trade_date||'未知'} · 抓取 {new Date(state.updated*1000).toLocaleString()}</p><p>{r.definition||r.coverage_note}</p>
 {market==='CN'?<><div className="emotion-cards">{[['涨停池',r.pools.up.rows?.length],['跌停池',r.pools.down.rows?.length],['炸板',r.broken_count],['炸板率',pct(r.broken_rate)],['最高连板',r.max_streak]].map(([k,v])=><article key={k}><span>{k}</span><strong>{v??'—'}</strong></article>)}</div>
 {Object.entries(r.pools).map(([k,v]:[string,any])=><p key={k}>{k} · {v.error||v.source} · {v.trade_date} · 覆盖 {pct(v.coverage)}{v.stale?' · 缓存过期':''}</p>)}
 {(r.levels||[]).map((l:any)=><div key={l.level}><h4>{l.level} 连板 · {l.count} 只</h4><div className="radar-member-list">{l.stocks.map((s:any)=><button key={s.symbol} onClick={()=>onOpen(s)}>{s.name} {s.symbol}</button>)}</div></div>)}
 <h4>连板晋级（{r.previous_trade_date} → {r.trade_date}）</h4>{(r.promotion||[]).map((p:any)=><p key={p.from}>{p.from} → {p.to} 板：{p.success}/{p.denominator}，{pct(p.rate)}</p>)}
 <h4>昨日涨停 / 强势股今日反馈</h4>{Object.entries(r.feedback).map(([k,v]:[string,any])=><p key={k}>{k==='previous'?'昨日涨停':'昨日强势'}：{v.error||`平均涨跌 ${v.average_change?.toFixed(2)??'—'}% · 上涨占比 ${pct(v.up_ratio)} · 分母 ${v.denominator}/${v.expected} · 覆盖 ${pct(v.coverage)}`}<small>{v.definition}</small></p>)}</>:<>
 <p>样本有效 {r.denominator}/{r.expected} · 覆盖 {pct(r.coverage)} · 数据失败 {r.failures.length}</p><div className="emotion-cards">{[['站上 MA20',pct(r.above_ma20_ratio)],['站上 MA50',pct(r.above_ma50_ratio)],['252日收盘新高',r.new_high],['252日收盘新低',r.new_low],['上涨占比',pct(r.up_ratio)]].map(([k,v])=><article key={k}><span>{k}</span><strong>{v}</strong></article>)}</div><p>新高/新低有效分母 {r.high_low_denominator} · 行业上涨 {r.industry_diffusion.up}/{r.industry_diffusion.denominator}</p>
 <div className="radar-member-list">{r.proxies.map((p:any)=><button key={p.symbol} onClick={()=>onOpen(p)}>{p.name} · {p.error||`${p.change.toFixed(2)}%`}</button>)}</div><details><summary>样本与失败明细</summary>{r.rows.map((x:any)=><p key={x.symbol}>{x.symbol} · {x.change.toFixed(2)}%</p>)}{r.failures.map((x:any)=><p key={x.symbol}>{x.symbol}：{x.error}</p>)}</details></>}
 </>}
 </section>;
}
