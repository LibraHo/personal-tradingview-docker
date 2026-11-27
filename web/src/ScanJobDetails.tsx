import {catalog,operators,type Rule,type Operand} from './scanner';
import {formatScanTime,scanSourceText} from './ScanJobHistory';

const period=(value:string)=>({'1d':'日线','1w':'周线','1mo':'月线'}[value]||value?.replace('m',' 分钟'));
const lines:Record<string,string>={main:'数值',REDS:'红灯数',GREENS:'绿灯数',close:'收盘价',open:'开盘价',high:'最高价',low:'最低价',volume:'成交量',average:'均量',macd:'DIF',signal:'DEA',hist:'柱值',upper:'上轨',mid:'中轨',lower:'下轨'};
function OperandRecord({value,recorded}:{value:Operand&{formula_revision?:string};recorded:boolean}){
 return <div className="scan-audit-operand"><strong>{value.name==='NUMBER'?`固定数值 ${value.value}`:catalog[value.name]?.label||value.name}</strong>
  <span>{value.name}{value.name!=='NUMBER'?` · 输出 ${lines[value.line]||value.line}（${value.line}）`:''} · 取值偏移 {value.offset??0} 根 · 倍数 {value.scale??1}</span>
  {Object.keys(value.params||{}).length>0?<div className="scan-audit-params">{Object.entries(value.params).map(([key,n])=><span key={key}>{key} = {n}</span>)}</div>:
   <span>{['NUMBER','PRICE'].includes(value.name)?'无指标周期参数':value.formula_revision?'使用固定公式参数':recorded?'无可调参数':'旧任务未保存展开的默认参数'}</span>}
  {value.formula_revision&&<small>公式版本 {value.formula_revision.slice(0,12)}</small>}
 </div>;
}

export default function ScanJobDetails({job}:{job:Record<string,any>}){
 const plan=job.execution_plan||job.plan,snapshot=job.scope_snapshot;
 if(!plan)return <p>此历史任务未保存条件快照。</p>;
 const targetGroups=[...new Set<string>((job.targets||job.results||[]).flatMap((row:any)=>row.groups||[]))];
 const basisLabels:Record<string,string>={qfq:'前复权',none:'不复权',hfq:'后复权'};
 const [legacyProvider,legacyBasis]=String(job.market_feed||'').split('/');
 const historySources=Object.entries(job.market_sources||{}).map(([market,route]:[string,any])=>{
  const live=route.live_supported===false?' · '+(route.live_reason||'推送不可用'):
    route.live&&route.live!==route.history?' · 推送 '+route.live:'';
  return (market==='US'?'美股':'沪深')+' '+route.history+' · '+(basisLabels[route.adjustment]||route.adjustment)+live+' · 日历 '+route.calendar;
 });
 const feedLabel=historySources.join('；')||(basisLabels[legacyBasis]?legacyProvider+' · '+basisLabels[legacyBasis]:'历史任务未记录口径');
 const selected=snapshot?.selected_groups||[];
 const empty=new Set(snapshot?.empty_groups||[]);
 const exportRecord=()=>{
  const data={job_id:job.id,source:job.source,market_feed:job.market_feed,market_sources:job.market_sources,monitor_id:job.monitor_id,created:job.created,started:job.started,finished:job.finished,status:job.status,
   plan:job.plan,execution_plan:job.execution_plan,scope_snapshot:snapshot,targets:job.targets,failures:job.failures,controls:job.controls};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=`scan-${job.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 return <section className="scan-audit" aria-label="本次扫描完整记录">
  <header><div><h4>本次扫描完整记录</h4><p>保存本次任务使用的条件与范围，修改上方编辑器不会改写这里。</p></div><button onClick={exportRecord}>导出本次记录</button></header>
  <dl className="scan-audit-overview"><div><dt>触发来源</dt><dd>{scanSourceText(job)}{job.monitor_snapshot?.name?` · ${job.monitor_snapshot.name}`:''}</dd></div>
   <div><dt>方案</dt><dd>{plan.name||'未命名'} · v{plan.version||1}</dd></div><div><dt>决策周期</dt><dd>{plan.periods?.map(period).join('、')}</dd></div>
   <div><dt>条件组合</dt><dd>{plan.join==='any'?'任意一条满足（OR）':'全部条件满足（AND）'} · 最近 {plan.lookback??1} 根寻找命中</dd></div>
   <div><dt>行情口径</dt><dd>{plan.live?'包含当前未收线 K 线':'仅已收线 K 线'} · 常规时段 · {feedLabel}</dd></div>
  </dl>
  <div className="scan-audit-scope"><h5>当时的扫描范围</h5>
   <p>{({all:'全部关注分组',groups:'指定分组',favorites:'关注板块',symbols:'指定代码',members:'指定板块成分'} as Record<string,string>)[plan.scope?.kind||'all']} · {snapshot?`快照 ${formatScanTime(snapshot.captured_at)}`:'历史任务未保存分组快照'}</p>
   {snapshot?.basis==='submission_watchlists'?<>
    <p><strong>纳入分组：</strong>{selected.length?selected.map((g:any)=>`${g.name}（${g.symbol_count} 个${empty.has(g.id)?'，空组':''}）`).join('、'):'无；按指定代码或板块扫描'}</p>
    <p><strong>未纳入分组：</strong>{snapshot.excluded_groups?.map((g:any)=>g.name).join('、')||'无'}</p>
    <p className={snapshot.missing_groups?.length?'scan-audit-warning':''}><strong>找不到的指定分组：</strong>{snapshot.missing_groups?.join('、')||'无'}</p>
    <p className={empty.size?'scan-audit-warning':''}><strong>空分组：</strong>{selected.filter((g:any)=>empty.has(g.id)).map((g:any)=>g.name).join('、')||'无'}</p>
    {selected.length>0&&<details><summary>查看每组当时的代码名单</summary>{selected.map((g:any)=><p key={g.id}><strong>{g.name} · {g.id}</strong><br/>{g.symbols.join('、')||'空组'}</p>)}</details>}
   </>:<p>历史任务没有保存可核验的纳入／排除分组快照，无法从当前分组反推。{targetGroups.length?`已执行标的记录的所属分组：${targetGroups.join('、')}。`:''}{snapshot?.target_groups?.length?`固定名单所属分组：${snapshot.target_groups.join('、')}。`:''}</p>}
   {plan.scope?.groups?.length>0&&<p>指定分组编号：{plan.scope.groups.join('、')}</p>}
   {plan.scope?.symbols?.length>0&&<p>指定代码：{plan.scope.symbols.join('、')}</p>}
  </div>
  <h5>全部条件与指标参数 · {plan.rules?.length||0} 条</h5>
  {plan.rules?.map((r:Rule,i:number)=><article className="scan-audit-rule" key={i}><h5>条件 {i+1}{r.name?` · ${r.name}`:''}</h5>
   <p><strong>{operators[r.op]||r.op}</strong> · {r.period?period(r.period):'跟随决策周期'} · 条件在 {r.offset??0} 根前结束</p>
   <div className="scan-audit-operands"><div><small>左侧指标／数值</small><OperandRecord value={r.left} recorded={!!job.execution_plan}/></div><div><small>右侧指标／比较值</small><OperandRecord value={r.right} recorded={!!job.execution_plan}/></div></div>
   <p>满足方式：{({current:'该根满足（可持续）',streak:'连续满足',all:'窗口内每根满足',any:'窗口内至少一次',count:'窗口内满足次数'} as Record<string,string>)[r.temporal||'current']}
    {['all','any','count'].includes(r.temporal||'')?` · 窗口 ${r.window??1} 根`:''}{['streak','count'].includes(r.temporal||'')?` · 下限 ${r.min_count??1}，上限 ${r.max_count??'不限'}`:''}</p>
  </article>)}
 </section>;
}
