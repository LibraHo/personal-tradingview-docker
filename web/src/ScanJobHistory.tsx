export const jobStatusLabels:Record<string,string> = {
  queued:'排队中', running:'扫描中', pausing:'正在暂停', paused:'已暂停',
  cancelling:'正在取消', cancelled:'已取消', completed:'扫描完成',
  partial:'部分完成', failed:'执行失败', interrupted:'服务中断',
};
export const jobPhaseLabels:Record<string,string> = {
  queued:'等待执行', resolving_scope:'正在确认扫描名单', loading:'读取行情',
  evaluating:'计算条件', paused:'已暂停', cancelled:'已取消', finished:'已结束', failed:'执行失败',
};
const formatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit',
  hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false,
});
export const formatScanTime = (value?:number) => value ? formatter.format(new Date(value*1000)) : '—';
type Job = Record<string,any>;
export const scanSourceText=(job:Job)=>job.source==='monitor'||job.monitor_id?'NAS 定时监控':job.source==='browser'?'页面人工提交':job.source==='api'?'API 提交':'历史来源未记录';
type Control = (id:string, action:'pause'|'resume'|'cancel')=>void;

export function JobControls({job,busy,onControl}:{job:Job;busy:boolean;onControl:Control}) {
  const pause = ['queued','running'].includes(job.status);
  const resume = ['paused','interrupted'].includes(job.status);
  const cancel = ['queued','running','pausing','paused'].includes(job.status);
  return <div className="scan-job-actions" role="group" aria-label="任务操作">
    {pause&&<button disabled={busy} onClick={()=>onControl(job.id,'pause')}>暂停任务</button>}
    {resume&&<button disabled={busy} onClick={()=>onControl(job.id,'resume')}>继续任务</button>}
    {cancel&&<button disabled={busy} onClick={()=>onControl(job.id,'cancel')}>取消任务</button>}
  </div>;
}

export default function ScanJobHistory({jobs,selectedId,busy,onSelect,onControl,hasMore,isOlder,onOlder,onLatest}:{
  jobs:Job[];selectedId?:string;busy:boolean;hasMore:boolean;isOlder:boolean;onOlder:()=>void;onLatest:()=>void;onSelect:(id:string)=>void;onControl:Control;
}) {
  return <section className="scan-job-history" aria-label="扫描任务记录">
    <h3>扫描记录 <small>北京时间 · 本页 {jobs.length} 次</small></h3>
    {!jobs.length?<p>还没有扫描任务。提交后会在这里记录时间、进度和参数。</p>:
      <div className="scan-job-history-table"><table>
        <thead><tr><th>方案 / 任务</th><th>触发来源 / 范围 / 条件</th><th>状态 / 进度</th><th>创建 / 开始</th><th>完成时间</th><th>操作</th></tr></thead>
        <tbody>{jobs.map(job=><tr key={job.id} className={selectedId===job.id?'selected':''}>
          <td><button className="scan-job-link" disabled={busy} onClick={()=>onSelect(job.id)}>{job.plan_name||'扫描任务'}</button>
            <small>{job.market==='CN'?'A 股':job.market==='US'?'美股':'跨市场'} · {job.live?'含未收线':'仅收线'} · v{job.plan_version||1}</small>
            <small className="scan-job-id">{job.id}</small></td>
          <td><strong>{scanSourceText(job)}</strong><small>{job.scope_summary?.selected_groups?.join('、')||'分组详情见任务记录'}</small><small>{job.condition_count??'—'} 条条件 · 点击方案查看完整参数</small>{!!job.scope_summary?.missing_groups?.length&&<small>有指定分组缺失</small>}</td>
          <td><strong>{jobStatusLabels[job.status]||job.status}</strong>
            <small>{job.total?job.done+' / '+job.total:job.status==='cancelled'?'未开始':'名单待确认'}{job.queue_position?' · 排队第 '+job.queue_position+' 位':''}</small>
            <small>{job.current_symbol||''} {job.current_period||''}</small></td>
          <td>{formatScanTime(job.created)}<small>开始 {formatScanTime(job.started)}</small></td>
          <td>{formatScanTime(job.finished)}</td>
          <td><JobControls job={job} busy={busy} onControl={onControl}/></td>
        </tr>)}</tbody>
      </table></div>}
    {(hasMore||isOlder)&&<div className="scan-job-actions"><button disabled={busy||!isOlder} onClick={onLatest}>最新记录</button><button disabled={busy||!hasMore} onClick={onOlder}>更早记录</button></div>}
  </section>;
}
