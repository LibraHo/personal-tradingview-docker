import {useEffect, useId, useRef, useState} from 'react';

type Result = {symbol:string; name:string; kind:'stock'|'index'|'etf'};
type Props = {
  market:'US'|'CN'; query:string; onQuery:(value:string)=>void;
  onView:(symbol?:string,name?:string)=>void; onAdd:(symbol?:string,name?:string)=>void;
};

export default function StockSearch({market,query,onQuery,onView,onAdd}:Props) {
  const [results,setResults]=useState<Result[]>([]);
  const [open,setOpen]=useState(false), [loading,setLoading]=useState(false);
  const [message,setMessage]=useState(''), [selected,setSelected]=useState(0);
  const [composing,setComposing]=useState(false);
  const navigated=useRef(false);
  const cache=useRef(new Map<string,{results:Result[];expires:number}>());
  const id=useId(), cn=market==='CN', expanded=open&&Boolean(query.trim());
  const example=cn?'SH.000001':'US.AAPL';

  useEffect(()=>{
    const keyword=query.replace(/\s/g,'').toLowerCase();
    if(!open||!keyword||composing){setLoading(false);return}
    const key=market+'/'+keyword;
    const hit=cache.current.get(key);
    setMessage('');
    if(hit&&hit.expires>Date.now()){setResults(hit.results);setLoading(false);return}
    const controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    setLoading(true);
    const search=async()=>{
      try {
        const params=new URLSearchParams({market,q:keyword});
        const response=await fetch('/api/symbols/search?'+params,{signal:controller.signal});
        if(!response.ok)throw Error();
        const data=await response.json();
        if(controller.signal.aborted)return;
        const rows:Result[]=Array.isArray(data.results)?data.results:[];
        setResults(rows);
        setSelected(i=>Math.max(0,Math.min(i,rows.length-1)));
        setMessage(data.message||'');
        if(data.refreshing)timer=setTimeout(search,1000);
        if(!data.stale){
          if(cache.current.size>=64)cache.current.delete(cache.current.keys().next().value!);
          cache.current.set(key,{results:rows,expires:Date.now()+60000});
        }
      } catch {
        if(!controller.signal.aborted)setMessage('名称搜索暂不可用，可直接输入完整代码。');
      } finally {
        if(!controller.signal.aborted)setLoading(false);
      }
    };
    timer=setTimeout(search,100);
    return ()=>{controller.abort();clearTimeout(timer)};
  },[query,market,composing,open]);

  useEffect(()=>{
    if(open)document.getElementById(`${id}-${selected}`)?.scrollIntoView({block:'nearest',inline:'nearest'});
  },[selected,open,results,id]);

  function submit(add=false){
    const input=query.trim().toUpperCase();
    if(!input)return;
    const action=add?onAdd:onView;
    const row=!loading?results[selected]:undefined;
    const fullCode=cn?/^(SH|SZ)\.\d{6}$/.test(input):/^US\.[A-Z0-9.]{1,12}$/.test(input);
    const bareTicker=!cn&&/^[A-Z0-9.]{1,12}$/.test(input);
    const nameMatch=row?.name.toUpperCase().includes(input);
    if(row&&!fullCode&&(!bareTicker||navigated.current||row.symbol==='US.'+input||nameMatch)){
      action(row.symbol,row.name);
    } else if(fullCode||bareTicker){
      action();
    } else {
      setOpen(true);
      setMessage(loading?'正在搜索…':`请从结果中选择，或输入完整代码，如 ${example}。`);
      return;
    }
    setOpen(false);
  }

  return <div className="stock-search" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setOpen(false)}}>
    <div className="add-symbol">
      <input role="combobox" aria-label="证券名称或代码" aria-autocomplete="list" aria-expanded={expanded}
        aria-controls={id} aria-activedescendant={expanded&&results[selected]?`${id}-${selected}`:undefined}
        maxLength={32} value={query} placeholder={cn?'股票、指数或 ETF 名称 / 代码':'美股名称或代码，如 AAPL'}
        onChange={e=>{
          setResults([]);setSelected(0);navigated.current=false;setMessage('');
          setLoading(Boolean(e.target.value.trim()));onQuery(e.target.value);setOpen(true);
        }}
        onFocus={()=>setOpen(true)} onCompositionStart={()=>setComposing(true)} onCompositionEnd={()=>setComposing(false)}
        onKeyDown={e=>{
          if(e.nativeEvent.isComposing||composing)return;
          if(e.key==='ArrowDown'||e.key==='ArrowUp'){
            e.preventDefault();setOpen(true);navigated.current=true;
            const delta=e.key==='ArrowDown'?1:-1;
            setSelected(i=>Math.max(0,Math.min(results.length-1,i+delta)));
          } else if(e.key==='Escape'){setOpen(false)}
          else if(e.key==='Enter'){e.preventDefault();submit()}
        }}/>
      <button title="只查看行情，不加入自选" onClick={()=>submit()}>查看</button>
      <button title="加入当前分组" aria-label="加入当前分组" onClick={()=>submit(true)}>＋</button>
    </div>
    {expanded&&<div className="stock-search-results" id={id} role="listbox" aria-label="证券搜索结果">
      {loading&&<p role="status">正在搜索…</p>}
      {!loading&&results.map((r,i)=><button key={r.symbol} id={`${id}-${i}`} role="option"
        aria-selected={i===selected} className={i===selected?'highlighted':''} onMouseDown={e=>e.preventDefault()}
        onMouseEnter={()=>setSelected(i)} onClick={()=>{onView(r.symbol,r.name);setOpen(false)}}>
        <strong>{r.name}</strong><span>{r.symbol} · {r.kind==='etf'?'ETF':r.kind==='index'?'指数':'股票'}</span>
      </button>)}
      {!loading&&(message||!results.length)&&<p role="status">{message||`未找到匹配证券，可输入完整代码，如 ${example}。`}</p>}
    </div>}
  </div>;
}
