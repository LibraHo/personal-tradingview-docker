import {useEffect,useRef,useState} from 'react';

export default function CachePanel({symbol,onClose}:{symbol?:string;onClose:()=>void}){
 const [data,setData]=useState<any>(null),[error,setError]=useState('');
 const box=useRef<HTMLDivElement>(null);
 useEffect(()=>{const before=document.activeElement as HTMLElement|null;box.current?.querySelector('button')?.focus();let stopped=false;
  fetch('/api/cache/status'+(symbol?'?symbol='+encodeURIComponent(symbol):'')).then(async r=>{if(!r.ok)throw Error('缓存信息暂不可用');return r.json()}).then(d=>{if(!stopped)setData(d)}).catch(e=>{if(!stopped)setError(e.message)});
  return()=>{stopped=true;before?.focus()};
 },[symbol]);
 const date=(v:number)=>new Date(v*1000).toLocaleDateString('zh-CN',{timeZone:symbol?.startsWith('US.')?'America/New_York':'Asia/Shanghai'});
 return <div className="cache-backdrop"><div className="cache-dialog" ref={box} role="dialog" aria-modal="true" aria-labelledby="cache-title" onKeyDown={e=>{if(e.key==='Escape')onClose();if(e.key==='Tab'){const nodes=box.current?.querySelectorAll<HTMLElement>('button,a[href],input,select');if(nodes?.length){const first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}}}>
  <div className="cache-title"><h2 id="cache-title">数据与缓存</h2><button aria-label="关闭缓存信息" onClick={onClose}>关闭</button></div>
  <p>行情保存在 NAS 的 SQLite 数据库，不依赖公司电脑的浏览器缓存。关闭网页或重启 NAS 后仍然保留。</p>
  {error?<div role="alert">{error}</div>:!data?<p role="status">正在读取 NAS 缓存…</p>:<>
   <div className="cache-summary"><div><strong>{Number(data.total_bars).toLocaleString()}</strong><span>已保存 K 线</span></div><div><strong>{(data.bytes/1024/1024).toFixed(1)} MiB</strong><span>数据库及写入日志</span></div><div><strong>{data.intraday_retention_days} 天 / {data.daily_retention_days} 天</strong><span>日内 / 日线保留范围</span></div></div>
   <h3>{symbol} · 已有数据</h3><div className="cache-table"><table><thead><tr><th>周期</th><th>时段</th><th>根数</th><th>最早</th><th>最新</th></tr></thead><tbody>{data.series.map((r:any)=><tr key={r.period+r.mode}><td>{r.period}</td><td>{({all:'全时段',extended:'盘前盘后及盘中',regular:'常规'} as Record<string,string>)[r.mode]||r.mode}</td><td>{r.count}</td><td>{date(r.oldest)}</td><td>{date(r.newest)}</td></tr>)}</tbody></table>{!data.series.length&&<p>该股票还没有本地 K 线，需要行情权限才能首次下载。</p>}</div>
   <p className="cache-explanation">再次打开优先复用已有 K 线，按最新缓存日期补齐缺口，并重读少量近期数据校正未结束 K 线。拖动到更早日期时先查本地，再请求缺少的历史。</p>
   <p className="cache-explanation">盘口深度是短期内存快照，不写入历史数据库。图表、指标模板与盘口参数保存在 NAS；实时行情权限失效时，缓存可以继续看，但不会变成实时数据。</p>
  </>}
 </div></div>;
}
