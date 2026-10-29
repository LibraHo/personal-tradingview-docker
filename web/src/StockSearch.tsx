import {useEffect,useId,useState} from 'react';
type Result={symbol:string;name:string};
export default function StockSearch({market,query,onQuery,onView,onAdd}:{market:'US'|'CN';query:string;onQuery:(value:string)=>void;onView:(symbol?:string,name?:string)=>void;onAdd:(symbol?:string,name?:string)=>void}){
 const [results,setResults]=useState<Result[]>([]),[open,setOpen]=useState(false),[loading,setLoading]=useState(false),[message,setMessage]=useState(''),[selected,setSelected]=useState(0),[composing,setComposing]=useState(false);
 const id=useId(),cn=market==='CN';
 useEffect(()=>{setResults([]);setSelected(0);setMessage('');if(!cn||!query.trim()||composing){setLoading(false);return}
  let stopped=false;const controller=new AbortController();setLoading(true);
  const timer=setTimeout(async()=>{try{const r=await fetch('/api/symbols/search?market=CN&q='+encodeURIComponent(query.trim()));const data=await r.json();if(!r.ok)throw Error();if(!stopped){setResults(Array.isArray(data.results)?data.results:[]);setMessage(data.message||'')}}catch{if(!stopped)setMessage('名称搜索暂不可用，可直接输入股票代码。')}finally{if(!stopped)setLoading(false)}},300);
  return()=>{stopped=true;clearTimeout(timer);controller.abort()};
 },[query,cn,composing]);
 useEffect(()=>{if(open)document.getElementById(`${id}-${selected}`)?.scrollIntoView({block:'nearest',inline:'nearest'})},[selected,open,results,id]);
 const choose=(result:Result)=>{onView(result.symbol,result.name);setOpen(false);setResults([])};
 const submit=(add=false)=>{if(!query.trim())return;if(!cn||/^(?:(?:SH|SZ)\.)?\d{6}$/i.test(query.trim())){(add?onAdd:onView)();setOpen(false)}else if(results.length&&!loading){const r=results[selected]||results[0];if(add){onAdd(r.symbol,r.name);setOpen(false)}else choose(r);}else{setOpen(true);setMessage(loading?'正在搜索名称…':'请选择搜索结果，或输入股票代码。')}};
 return <div className="stock-search" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setOpen(false)}}>
  <div className="add-symbol"><input role="combobox" aria-label="股票名称或代码" aria-autocomplete="list" aria-expanded={cn&&open&&Boolean(query.trim())} aria-controls={id} aria-activedescendant={cn&&open&&results[selected]?`${id}-${selected}`:undefined} maxLength={32} value={query} onChange={e=>{onQuery(e.target.value);setOpen(true)}} onFocus={()=>setOpen(true)} onCompositionStart={()=>setComposing(true)} onCompositionEnd={()=>setComposing(false)} onKeyDown={e=>{if(e.nativeEvent.isComposing||composing)return;if(e.key==='ArrowDown'&&cn){e.preventDefault();setOpen(true);setSelected(i=>Math.min(results.length-1,Math.max(0,i+1)))}else if(e.key==='ArrowUp'&&cn){e.preventDefault();setSelected(i=>Math.max(0,i-1))}else if(e.key==='Escape'){setOpen(false)}else if(e.key==='Enter'){e.preventDefault();submit()}}} placeholder={cn?'名称或代码，如 茅台 / 600519':'搜索美股代码，如 AAPL'}/><button title="只查看行情，不加入自选" onClick={()=>submit()}>查看</button><button title="加入当前分组" aria-label="加入当前分组" onClick={()=>submit(true)}>＋</button></div>
  {cn&&open&&Boolean(query.trim())&&<div className="stock-search-results" id={id} role="listbox" aria-label="A 股搜索结果">
   {loading&&<p role="status">正在搜索名称…</p>}
   {!loading&&results.map((r,i)=><button key={r.symbol} id={`${id}-${i}`} role="option" aria-selected={i===selected} className={i===selected?'highlighted':''} onMouseDown={e=>e.preventDefault()} onMouseEnter={()=>setSelected(i)} onClick={()=>choose(r)}><strong>{r.name}</strong><span>{r.symbol}</span></button>)}
   {!loading&&!results.length&&<p role="status">{message||'未找到匹配股票，可尝试完整名称或六位代码。'}</p>}
   {!loading&&results.length>0&&message&&<p>{message}</p>}
  </div>}
 </div>;
}
