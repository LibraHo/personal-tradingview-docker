import {useEffect,useState} from 'react';

export type ScanGroup={id:string;name:string;symbols:string[]};
type Board={symbol:string;name:string;instrument?:string};
type Props={market:'US'|'CN';groups:ScanGroup[];scope:string;setScope:(s:string)=>void;chosen:string[];setChosen:(s:string[])=>void;explicit:string;setExplicit:(s:string)=>void};
export default function ScanScopePicker({market,groups,scope,setScope,chosen,setChosen,explicit,setExplicit}:Props){
 const [kind,setKind]=useState('industry'),[query,setQuery]=useState(''),[page,setPage]=useState(0);
 const [boards,setBoards]=useState<Board[]>([]),[known,setKnown]=useState<Record<string,string>>({}),[loading,setLoading]=useState(false),[error,setError]=useState(''),[meta,setMeta]=useState('');
 const boardMode=scope==='members'||scope==='sectors';
 const picked=explicit.split(/[,，\s]+/).filter(Boolean);
 useEffect(()=>{
  if(!boardMode)return;
  const c=new AbortController();setBoards([]);setLoading(true);setError('');setMeta('');setPage(0);
  fetch('/api/radar/catalog?'+new URLSearchParams({market,kind}),{signal:c.signal}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.detail||'板块目录读取失败');return v}).then(v=>{
   setBoards(v.rows);setKnown(n=>({...n,...Object.fromEntries(v.rows.map((r:Board)=>[r.symbol,r.name]))}));
   setMeta(`${v.source||v.provider||'板块目录'}${v.updated?' · 更新 '+new Date(v.updated*1000).toLocaleString():''}`);
   if(v.stale)setError('当前为缓存目录：'+(v.error||'数据源暂不可用'));
  }).catch(e=>{if(!c.signal.aborted)setError(e.message)}).finally(()=>{if(!c.signal.aborted)setLoading(false)});
  return()=>c.abort();
 },[market,kind,boardMode]);
 const filtered=boards.filter(b=>(b.name+' '+b.symbol).toLowerCase().includes(query.toLowerCase()));
 const activeGroups=scope==='all'?groups.map(g=>g.id):chosen;
 function chooseSource(next:string){
  if((next==='members'||next==='sectors')&&!boardMode)setExplicit('');
  if(next==='symbols'&&boardMode)setExplicit('');
  if(next==='members'&&kind==='etf')setKind('industry');
  setScope(next);
 }
 return <section className="scan-source" aria-label="扫描名单选择">
  <div className="scan-source-heading"><h3>从哪里找</h3><span>{market==='CN'?'沪深 A 股':'美股'} · 直接读取你的列表</span></div>
  <div className="scan-source-tabs" role="group" aria-label="扫描来源">
   <button type="button" aria-pressed={scope==='all'||scope==='groups'} onClick={()=>chooseSource('all')}>我的关注列表</button>
   <button type="button" aria-pressed={scope==='members'} onClick={()=>chooseSource('members')}>板块成分股</button>
   <button type="button" aria-pressed={scope==='sectors'} onClick={()=>chooseSource('sectors')}>板块指数 / ETF</button>
   <button type="button" aria-pressed={scope==='favorites'} onClick={()=>chooseSource('favorites')}>关注的板块</button>
   <button type="button" aria-pressed={scope==='symbols'} onClick={()=>chooseSource('symbols')}>指定标的</button>
  </div>
  {(scope==='all'||scope==='groups')&&<>
   <div className="scan-source-tools"><span>{scope==='all'?'全部分组，重复标的只扫一次':`已选 ${chosen.length} 个分组`}</span><button type="button" onClick={()=>{setScope('all');setChosen([])}}>全选</button><button type="button" onClick={()=>{setScope('groups');setChosen([])}}>清空</button></div>
   <div className="scan-group-grid">{groups.map(g=><label className={activeGroups.includes(g.id)?'selected':''} key={g.id}><input type="checkbox" checked={activeGroups.includes(g.id)} onChange={e=>{setChosen(e.target.checked?[...new Set([...activeGroups,g.id])]:activeGroups.filter(id=>id!==g.id));setScope('groups')}}/><span>{g.name}</span><small>{new Set(g.symbols).size}</small></label>)}</div>
   {!groups.length&&<p>这个市场还没有关注分组，请先在自选列表添加。</p>}
  </>}
  {boardMode&&<>
   <div className="scan-board-filters"><select aria-label="板块分类" value={kind} onChange={e=>{setKind(e.target.value);setPage(0)}}><option value="industry">行业</option><option value="concept">概念 / 题材</option><option value="other">其他板块</option>{market==='US'&&scope==='sectors'&&<option value="etf">11 行业 ETF</option>}</select><input aria-label="扫描板块搜索" placeholder="搜索板块名称或代码" value={query} onChange={e=>{setQuery(e.target.value);setPage(0)}}/></div>
   {picked.length>0&&<div className="scan-picked">{picked.map(symbol=><button type="button" key={symbol} onClick={()=>setExplicit(picked.filter(s=>s!==symbol).join(','))}>{known[symbol]||symbol} ×</button>)}<button type="button" onClick={()=>setExplicit('')}>清空</button></div>}
   {loading?<p role="status">正在读取{market==='CN'?'A 股':'美股'}板块目录…</p>:<>
    <div className="scan-board-grid">{filtered.slice(page*40,(page+1)*40).map(b=><label key={b.symbol} className={picked.includes(b.symbol)?'selected':''}><input type="checkbox" checked={picked.includes(b.symbol)} onChange={e=>setExplicit((e.target.checked?[...new Set([...picked,b.symbol])]:picked.filter(s=>s!==b.symbol)).join(','))}/><span>{b.name}<small>{b.symbol} · {b.instrument||'板块指数'}</small></span></label>)}</div>
    {!filtered.length&&!error&&<p>没有找到符合搜索条件的板块。</p>}
    <div className="scan-source-tools"><span>{filtered.length} 个板块 · 已选 {picked.length} 个</span><button type="button" disabled={page===0} onClick={()=>setPage(p=>p-1)}>上一页</button><span>{page+1} / {Math.max(1,Math.ceil(filtered.length/40))}</span><button type="button" disabled={(page+1)*40>=filtered.length} onClick={()=>setPage(p=>p+1)}>下一页</button></div>
   </>}
   {error&&<p role="alert">{error}</p>}<small className="scan-source-meta">{meta}{scope==='members'?' · 扫描所选板块的全部成分股，自动去重':' · 扫描板块指数或 ETF 本身'}</small>
  </>}
  {scope==='favorites'&&<p>读取当前市场“关注板块”分组中的标的，具体名单显示在下方。</p>}
  {scope==='symbols'&&<label className="scan-explicit">股票或指数代码<input aria-label="标的代码" placeholder={market==='US'?'US.AAPL, US.MSFT':'SH.600519, SZ.000001'} value={explicit} onChange={e=>setExplicit(e.target.value)}/></label>}
 </section>;
}
