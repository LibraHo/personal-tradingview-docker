import {useEffect,useMemo,useRef,useState} from 'react';
import './market-radar.css';
import LimitBoard from './LimitBoard';
import MarketAnalytics from './MarketAnalytics';

export type RadarItem={symbol:string;name:string;instrument?:string;change?:number|null;turnover?:number|null;up?:number|null;down?:number|null;flat?:number|null;leader?:string};
type Emotion={source?:string;provider?:string;up:number;down:number;flat:number;total:number;up_ratio:number|null;net_advances:number;limit_up:number|null;limit_down:number|null;scope:string;definition?:string;coverage_note?:string;time_note?:string;updated:number;stale:boolean;error?:string;bins:{label:string;count:number;side:string}[]};
type Props={market:'US'|'CN';view:'radar'|'emotion';emotionBoard:RadarItem|null;onShowEmotion:(item:RadarItem|null)=>void;favorites:string[];onFavorite:(item:RadarItem)=>void;onOpen:(item:RadarItem)=>void;onScan:(name:string,items:RadarItem[])=>void};
const types:Record<string,string>={industry:'行业板块',concept:'概念题材',theme:'主题板块',etf:'11 行业 ETF'};
const percent=(value:number|null|undefined)=>value==null?'—':`${value>0?'+':''}${value.toFixed(2)}%`;
const amount=(value:number|null|undefined)=>value==null?'—':value>=1e8?`${(value/1e8).toFixed(2)} 亿`:`${(value/1e4).toFixed(1)} 万`;
async function read(path:string,signal:AbortSignal){
  const response=await fetch('/api/'+path,{signal});
  const data=await response.json();if(!response.ok)throw Error(data.detail||'数据请求失败');return data;
}
export default function MarketRadar({market,view,emotionBoard,onShowEmotion,favorites,onFavorite,onOpen,onScan}:Props){
  const [boardTab,setBoardTab]=useState(false);
  const showBoard=market==='CN'&&view==='radar'&&boardTab;
  const [kind,setKind]=useState('industry'),[query,setQuery]=useState('');
  const [items,setItems]=useState<RadarItem[]>([]),[picked,setPicked]=useState<string[]>([]),[sort,setSort]=useState('change');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[refresh,setRefresh]=useState(0);
  const [sources,setSources]=useState<string[]>([]);
  const [updated,setUpdated]=useState<number|null>(null),[emotion,setEmotion]=useState<Emotion|null>(null),[emotionError,setEmotionError]=useState('');
  const [memberOf,setMemberOf]=useState<RadarItem|null>(null),[members,setMembers]=useState<RadarItem[]>([]),[memberError,setMemberError]=useState(''),[memberBusy,setMemberBusy]=useState(false);
  const selectedEmotion=emotionBoard?.symbol||'';
  const membersDialog=useRef<HTMLDialogElement>(null);
  const membersRequest=useRef<AbortController|null>(null);
  const favoriteSet=useMemo(()=>new Set(favorites),[favorites]);
  useEffect(()=>()=>membersRequest.current?.abort(),[]);
  useEffect(()=>{
    if(memberOf)membersDialog.current?.showModal();
  },[memberOf]);
  useEffect(()=>{
    if(view!=='emotion')return;
    const controller=new AbortController();setEmotion(null);setEmotionError('');
    read('radar/emotion?'+new URLSearchParams({market,symbol:selectedEmotion}),controller.signal)
      .then(setEmotion).catch(e=>{if(!controller.signal.aborted)setEmotionError(e.message)});
    return ()=>controller.abort();
  },[market,view,selectedEmotion,refresh]);
  useEffect(()=>{
    if(view!=='radar'||showBoard)return;
    const controller=new AbortController();setSources([]);setItems([]);setPicked([]);setError('');setNotice('');setUpdated(null);setBusy(true);
    async function load(){
      let rows:RadarItem[]=[];
      const showSource=(label:string,source:string|undefined)=>{
        if(source&&!controller.signal.aborted)setSources(current=>[...new Set([...current,label+' '+source])]);
      };
      try{
        if(kind!=='theme'){
          const data=await read('radar/catalog?'+new URLSearchParams({market,kind}),controller.signal);
          showSource('目录',data.source||data.provider);
          rows=data.rows;setItems(rows);setUpdated(data.updated);
          if(data.stale)setNotice('目录为缓存：'+(data.error||'上游暂不可用'));
        }
        if(kind==='etf'){
          const data=await read('quotes?'+new URLSearchParams({symbols:rows.map(r=>r.symbol).join(',')}),controller.signal);
          showSource('报价',data.provider||data.quotes?.[0]?.provider);
          const quotes=new Map<string,any>(data.quotes.map((r:any)=>[r.symbol,r]));
          setItems(rows.map(r=>({...r,change:quotes.get(r.symbol)?.change_percent})));
          setUpdated(Date.now()/1000);if(data.stale)setNotice('ETF 行情为缓存');
        }else if(kind!=='other'){
          let page='';const seen=new Set<string>();
          do{
            const data=await read('radar/heatmap?'+new URLSearchParams({market,kind,page}),controller.signal);
            showSource('热力图',data.source||data.provider);
            const map=new Map(rows.map(r=>[r.symbol,r]));
            for(const item of data.rows)map.set(item.symbol,{...map.get(item.symbol),...item,instrument:'板块指数'});
            rows=[...map.values()];setItems(rows);setUpdated(data.updated);
            if(data.stale)setNotice('热力图为缓存：'+(data.error||'上游暂不可用'));
            page=data.next_page||'';
            if(page&&seen.has(page))throw Error('数据源重复返回分页游标，已保留收到的板块');
            seen.add(page);
          }while(page&&!controller.signal.aborted);
        }
      }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:String(e))}
      finally{if(!controller.signal.aborted)setBusy(false)}
    }
    load();return ()=>controller.abort();
  },[market,view,kind,refresh,showBoard]);
  const visible=useMemo(()=>items.filter(r=>(r.name+' '+r.symbol).toLowerCase().includes(query.toLowerCase())).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'zh'):sort==='changeAsc'?((a.change??Infinity)-(b.change??Infinity)):((b[sort as 'change'|'turnover']??-Infinity)-(a[sort as 'change'|'turnover']??-Infinity))),[items,query,sort]);
  async function showMembers(item:RadarItem){
    membersRequest.current?.abort();const controller=new AbortController();membersRequest.current=controller;
    setMemberOf(item);setMembers([]);setMemberError('');setMemberBusy(true);
    try{const data=await read('radar/members?'+new URLSearchParams({symbol:item.symbol}),controller.signal);if(controller.signal.aborted)return;setMembers(data.rows);if(data.stale)setMemberError('成分名单为缓存：'+(data.error||''))}
    catch(e){if(!controller.signal.aborted)setMemberError(e instanceof Error?e.message:String(e))}
    finally{if(!controller.signal.aborted)setMemberBusy(false)}
  }
  function closeMembers(){
    membersRequest.current?.abort();
    setMemberOf(null);
  }
  return <section className="market-radar" aria-label={view==='radar'?'板块雷达':'市场情绪'}>
    <header className="radar-header"><div><span>{market==='CN'?'沪深 A 股':'美股'}市场</span><h2>{view==='radar'?'板块雷达':'市场情绪'}</h2></div><button disabled={view==='radar'&&!showBoard&&busy} onClick={()=>setRefresh(n=>n+1)}>刷新</button></header>
    {market==='CN'&&view==='radar'&&<div className="lb-nav" aria-label="板块雷达栏目">
      <button aria-pressed={!showBoard} onClick={()=>setBoardTab(false)}>板块排行</button>
      <button aria-pressed={showBoard} onClick={()=>setBoardTab(true)}>打板行情</button>
    </div>}
    {showBoard?<LimitBoard refresh={refresh} onOpen={onOpen}/>:view==='radar'?<>
      <div className="radar-toolbar"><label>分类<select value={kind} onChange={e=>{setKind(e.target.value);setMemberOf(null)}}>{Object.entries(types).filter(([key])=>market==='US'||!['etf','theme'].includes(key)).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><input aria-label="搜索板块" placeholder="搜索名称或代码" value={query} onChange={e=>setQuery(e.target.value)}/><label>排序<select value={sort} onChange={e=>setSort(e.target.value)}><option value="change">涨幅优先</option><option value="changeAsc">跌幅优先</option><option value="turnover">成交额优先</option><option value="name">名称</option></select></label></div>
      <div className="radar-toolbar"><span>{visible.length} / {items.length} 个{busy?' · 加载中…':''}</span><button disabled={!visible.length} onClick={()=>setPicked(visible.map(r=>r.symbol))}>全选当前结果</button><button disabled={!picked.length} onClick={()=>setPicked([])}>清空选择</button><button disabled={!picked.length} onClick={()=>onScan(types[kind],items.filter(r=>picked.includes(r.symbol)))}>扫描已选（{picked.length}）</button></div>
      {error&&<p className="radar-error" role="alert">{error}</p>}{notice&&<p className="radar-warning">{notice}</p>}
      <p className="radar-meta">{sources.join(' · ')}{updated?` · 抓取 ${new Date(updated*1000).toLocaleString()}`:''}</p>
      <div className="radar-table"><table><thead><tr><th>选择</th><th>板块 / 题材</th><th>涨跌幅</th><th>成交额</th><th>上涨 / 下跌 / 平盘</th><th>领涨股</th><th>操作</th></tr></thead><tbody>{visible.map(item=><tr key={item.symbol}><td><input aria-label={`选择 ${item.name}`} type="checkbox" checked={picked.includes(item.symbol)} onChange={e=>setPicked(list=>e.target.checked?[...list,item.symbol]:list.filter(s=>s!==item.symbol))}/></td><td><button className="radar-name" onClick={()=>onOpen(item)}>{item.name}</button><small>{item.symbol}</small></td><td className={(item.change??0)>=0?'radar-up':'radar-down'}>{percent(item.change)}</td><td>{amount(item.turnover)}</td><td>{item.up??'—'} / {item.down??'—'} / {item.flat??'—'}</td><td>{item.leader?<button onClick={()=>onOpen({symbol:item.leader!,name:item.leader!})}>{item.leader}</button>:'—'}</td><td><div className="radar-actions"><button aria-label={`收藏 ${item.name}`} onClick={()=>onFavorite(item)}>{favoriteSet.has(item.symbol)?'★ 已关注':'☆ 关注'}</button>{kind!=='etf'&&<button onClick={()=>showMembers(item)}>成分股</button>}<button onClick={()=>onScan(item.name,[item])}>扫描</button></div></td></tr>)}</tbody></table></div>
      {!busy&&!items.length&&!error&&<p>数据源暂未提供这一分类的板块。</p>}
      {memberOf&&<dialog ref={membersDialog} className="radar-members-dialog" aria-labelledby="radar-members-title" onCancel={closeMembers} onClose={closeMembers} onClick={e=>{if(e.target===e.currentTarget)closeMembers()}}>
        <div className="radar-members-content">
          <header className="radar-header"><h3 id="radar-members-title">{memberOf.name} · 成分股{!memberBusy&&!memberError?`（${members.length}）`:''}</h3><button autoFocus onClick={closeMembers} aria-label="关闭成分股">关闭</button></header>
          <div className="radar-toolbar"><button disabled={!members.length||memberBusy} onClick={()=>onScan(memberOf.name+'成分股',members)}>扫描全部成分股</button><button onClick={()=>{closeMembers();onShowEmotion(memberOf)}}>查看板块情绪</button></div>
          {memberBusy&&<p role="status">正在读取成分股…</p>}
          {memberError&&<div className="radar-warning" role="alert">{memberError} <button onClick={()=>showMembers(memberOf)}>重试</button></div>}
          {!memberBusy&&!memberError&&!members.length&&<p role="status">数据源暂未提供这个板块的成分股。</p>}
          <div className="radar-member-list" aria-busy={memberBusy}>{members.map(item=><span key={item.symbol}><button onClick={()=>onOpen(item)}>{item.name} <small>{item.symbol}</small></button><button onClick={()=>onFavorite(item)}>关注</button><button onClick={()=>onScan(item.name,[item])}>扫描</button></span>)}</div>
        </div>
      </dialog>}
    </>:<>
      <div className="radar-toolbar"><h3>{emotionBoard?.name||'全市场'}涨跌分布</h3>{selectedEmotion&&<button onClick={()=>onShowEmotion(null)}>返回全市场</button>}</div>
      {emotionError?<p className="radar-error" role="alert">{emotionError}</p>:!emotion?<p role="status">正在读取市场情绪…</p>:<>
        {emotion.stale&&<p className="radar-warning">正在显示缓存 · {emotion.error}</p>}
        <div className="emotion-cards">{[['上涨家数',emotion.up],['下跌家数',emotion.down],['平盘家数',emotion.flat],['上涨占比',emotion.up_ratio==null?'—':emotion.up_ratio.toFixed(1)+'%'],['涨跌家数差',emotion.net_advances],...(market==='CN'?[['涨停',emotion.limit_up??'—'],['跌停',emotion.limit_down??'—']]:[])].map(([label,value])=><article key={String(label)}><span>{label}</span><strong>{value}</strong></article>)}</div>
        <div className="emotion-distribution" aria-label="涨跌分布图">{emotion.bins.map((bin,i)=><div className="emotion-bin" key={i}><span>{bin.label}</span><div><i className={'bin-'+bin.side} style={{width:`${Math.max(0,bin.count/Math.max(1,...emotion.bins.map(b=>b.count))*100)}%`}}/></div><b>{bin.count}</b></div>)}</div>
        <p className="radar-meta">{emotion.source||emotion.provider||'涨跌分布'} · 范围 {emotion.scope||market} · 抓取 {new Date(emotion.updated*1000).toLocaleString()}。上涨占比按可分类区间计算；涨跌停按数据源单列，未重复加进区间总数。{emotion.coverage_note} {emotion.time_note}</p>
      </>}
      <MarketAnalytics market={market} onOpen={onOpen}/>
    </>}
  </section>;
}
