import {useEffect, useState} from 'react';
import {reviewRequest, type ReviewMarket} from './reviewClient';
import './ledger-references.css';

export type RecordKind = 'plan' | 'fill';
type Choice = {id:string; symbol:string; code?:string; period?:string; trigger?:string; side:string; qty?:number; price?:number; at?:string; account?:string};
type Page = {plans:Choice[]; fills:Choice[]; next_offset:number|null};
export const citationPattern = /\[\[(plan|fill):([a-f0-9]{32})(?:\|([^\[\]|\r\n]{1,160}))?\]\]/g;
export function citations(text:string) {
  return Array.from(text.matchAll(citationPattern), m => ({
    index:m.index!, length:m[0].length, kind:m[1] as RecordKind, id:m[2],
    label:m[3] || ((m[1]==='plan'?'计划 ':'成交 ')+m[2].slice(0,8)),
  }));
}
export function openCitation(market:ReviewMarket,kind:RecordKind,id:string) {
  window.dispatchEvent(new CustomEvent('nas-ledger-open',{detail:{market,kind,id}}));
}
export function CitationLinks({market,text}:{market:ReviewMarket;text:string}) {
  const items=new Map(citations(text).map(item=>[item.kind+item.id,item]));
  if(!items.size)return null;
  return <div className="review-mention-index" aria-label="引用的交易档案">{Array.from(items.values(),item=>
    <button type="button" key={item.kind+item.id} onClick={()=>openCitation(market,item.kind,item.id)}>{item.label}</button>)}</div>;
}

export function CitationPicker({market,onInsert}:{market:ReviewMarket;onInsert:(text:string)=>void}) {
  const [open,setOpen]=useState(false),[kind,setKind]=useState<RecordKind>('fill');
  const [search,setSearch]=useState(''),[query,setQuery]=useState(''),[offset,setOffset]=useState(0);
  const [page,setPage]=useState<Page|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  useEffect(()=>{
    if(!open)return;
    const ctl=new AbortController();
    setPage(null);setError('');
    const params=new URLSearchParams({market,limit:'40',offset:String(offset)});
    if(query)params.set('symbol',query);
    reviewRequest<Page>('ledger/book?'+params,{signal:ctl.signal}).then(p=>{if(!ctl.signal.aborted)setPage(p)})
      .catch(e=>{if(!ctl.signal.aborted)setError(e.message)});
    return ()=>ctl.abort();
  },[open,market,query,offset,retry]);
  function describe(item:Choice) {
    if(kind==='plan')return [item.symbol,item.period,item.trigger].filter(Boolean).join(' · ');
    const at=item.at?new Date(item.at).toLocaleString('zh-CN',{timeZone:market==='CN'?'Asia/Shanghai':'America/New_York',hour12:false}):'';
    const side=({BUY:'买入',SELL:'卖出',SELL_SHORT:'卖空',BUY_BACK:'买回'} as Record<string,string>)[item.side]||item.side;
    return [item.code||item.symbol,at,side+' '+item.qty+' @ '+item.price,item.account].filter(Boolean).join(' · ');
  }
  const options=page?.[kind==='plan'?'plans':'fills']||[];
  return <div className="ledger-citation-picker">
    <button type="button" aria-expanded={open} onClick={()=>setOpen(!open)}>{open?'收起引用选择':'引用计划或成交'}</button>
    {open&&<section>
      <div className="review-mention-index">
        <select aria-label="引用类型" value={kind} onChange={e=>{setKind(e.target.value as RecordKind);setOffset(0)}}><option value="fill">成交记录</option><option value="plan">交易计划</option></select>
        <input aria-label="按完整标的代码筛选引用" value={search} placeholder={market==='CN'?'SH.600519':'US.AAPL'} onChange={e=>setSearch(e.target.value)}/>
        <button type="button" onClick={()=>{setQuery(search.trim().toUpperCase());setOffset(0)}}>筛选</button>
      </div>
      {error?<p role="alert">{error} <button type="button" onClick={()=>setRetry(n=>n+1)}>重试</button></p>:!page?<p>正在读取档案…</p>:<>
        <div className="ledger-citation-list">{options.map(item=><button key={item.id} type="button" onClick={()=>{
          const label=((kind==='plan'?'计划 · ':'成交 · ')+describe(item)).replace(/[\[\]|\r\n]/g,' ').slice(0,150);
          onInsert('[['+kind+':'+item.id+'|'+label+']]');setOpen(false);
        }}>{describe(item)}</button>)}</div>
        {!options.length&&<p>本页没有{kind==='plan'?'计划':'成交'}。</p>}
        {(offset>0||page.next_offset!=null)&&<div className="review-mention-index">
          <button type="button" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-40))}>上一页</button>
          <button type="button" disabled={page.next_offset==null} onClick={()=>setOffset(page.next_offset!)}>下一页</button>
        </div>}
      </>}
    </section>}
  </div>;
}
