import {useEffect,useState} from 'react';
import {getChartCsrf,secureChart} from './secureChart';
import './notification-settings.css';

type Channel={id:string;name:string;enabled:boolean;has_url:boolean;has_headers:boolean;monitor_ids:string[];confirmation:string;daily_limit:number;format:string;title_field:string;body_field:string;success_field:string;success_value:string;extra_fields:Record<string,string>};
type Monitor={id:string;name:string;enabled:boolean;interval_seconds:number;schedule:unknown};
type RecordItem={id:string;channel_id:string;event_id:string;status:string;attempts:number;created:number;error:string};
type State={channels:Channel[];monitors:Monitor[];records:RecordItem[]};
const empty=():Channel=>({id:'',name:'通知渠道',enabled:false,has_url:false,has_headers:false,monitor_ids:[],confirmation:'confirmed',daily_limit:100,format:'json',title_field:'title',body_field:'body',success_field:'',success_value:'',extra_fields:{}});
const base='/api/trade/notifications';
const labels:Record<string,string>={pending:'等待发送',sending:'正在发送',accepted:'接收端已接收',retry:'等待重试',failed:'发送失败',unknown:'结果待核对',cancelled:'已取消'};

export default function NotificationSettings({secureUrl}:{secureUrl:string}){
 const [state,setState]=useState<State|null>(null),[edit,setEdit]=useState<Channel>(empty),[url,setUrl]=useState(''),[headers,setHeaders]=useState(''),[extra,setExtra]=useState('{}');
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[error,setError]=useState('');
 const secure=location.protocol==='https:'&&secureChart;
 async function request(path='',method='GET',body?:unknown){
  const r=await fetch(base+path,{method,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':getChartCsrf()},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok)throw Error(r.status===401?'登录已过期，请重新登录。':typeof data.detail==='string'?data.detail:'请求失败，请重新读取核对。');
  return data;
 }
 async function load(){const next=await request();setState(next)}
 useEffect(()=>{if(secure)void load().catch(e=>setError(e.message))},[secure]);
 async function action(fn:()=>Promise<void>){if(busy)return;setBusy(true);setNotice('');setError('');try{await fn()}catch(e){setError(e instanceof SyntaxError?'请求头和附加字段必须是有效的 JSON 对象。':e instanceof TypeError?'未收到服务器确认，请重新读取核对结果。':(e as Error).message)}finally{setBusy(false)}}
 function choose(c:Channel){setEdit({...c,monitor_ids:[...c.monitor_ids]});setUrl('');setHeaders('');setExtra(JSON.stringify(c.extra_fields||{},null,2));setNotice('');setError('')}
 async function save(){
  const {id,has_url,has_headers,...body}=edit;
  const saved=await request('/channels'+(id?'/'+id:''),id?'PUT':'POST',{...body,url:url||null,headers:headers.trim()?JSON.parse(headers):null,extra_fields:JSON.parse(extra)});
  setUrl('');setHeaders('');setEdit(saved);await load();setNotice('已保存。新增或调整接收范围后，仅处理保存后的新信号。');
 }
 return <section className="notification-settings"><h3>消息推送</h3><p>按监控任务设定的时间检查行情，命中条件后发送通知。检查频率在「扫描与监控」里配置。</p>
 {!secure?<p><a href={secureUrl}>打开 HTTPS 通知设置</a>，登录后管理渠道与凭证。</p>:<>
 <div className="notification-actions"><button disabled={busy} onClick={()=>choose(empty())}>新增渠道</button><button disabled={busy} onClick={()=>void action(load)}>重新读取 / 刷新记录</button></div>
 {state&&<><div className="notification-channels">{state.channels.map(c=><button key={c.id} aria-pressed={edit.id===c.id} disabled={busy} onClick={()=>choose(c)}>{c.name} · {c.enabled?'已启用':'已停用'}</button>)}</div>
 <form onSubmit={e=>{e.preventDefault();void action(save)}}><fieldset disabled={busy}>
 <legend>{edit.id?'编辑通知渠道':'新增通知渠道'}</legend>
 <div className="notification-fields"><label>渠道名称<input required maxLength={80} value={edit.name} onChange={e=>setEdit({...edit,name:e.target.value})}/></label>

 <label>请求地址<input type="url" autoComplete="off" required={!edit.has_url} maxLength={4096} placeholder={edit.has_url?'地址已保存 · 留空沿用':'填写完整 HTTP / HTTPS 地址'} value={url} onChange={e=>setUrl(e.target.value)}/></label><label>请求格式<select value={edit.format} onChange={e=>setEdit({...edit,format:e.target.value})}><option value="json">JSON</option><option value="form">表单（URL 编码）</option></select></label><label>标题字段名<input required value={edit.title_field} onChange={e=>setEdit({...edit,title_field:e.target.value})}/></label><label>正文字段名<input required value={edit.body_field} onChange={e=>setEdit({...edit,body_field:e.target.value})}/></label>
 <label>信号状态<select value={edit.confirmation} onChange={e=>setEdit({...edit,confirmation:e.target.value})}><option value="confirmed">仅收盘确认</option><option value="preview">仅盘中预览</option><option value="all">盘中预览与收盘确认</option></select></label>
 <label>每天最多请求次数<input type="number" required min={1} max={1000} value={edit.daily_limit} onChange={e=>setEdit({...edit,daily_limit:Number(e.target.value)})}/></label></div>
 <p className="notification-hint">测试和重试也计入此上限；达到后待发消息留至次日。同一接收服务的账户额度可能由多个渠道共用。</p>
 <details><summary>请求头、附加字段与成功条件</summary><div className="notification-fields"><label>请求头（JSON 对象）<textarea autoComplete="off" rows={3} placeholder={edit.has_headers?'已保存 · 留空沿用，填写 {} 清空':'例如 {"Authorization":"Bearer …"}'} value={headers} onChange={e=>setHeaders(e.target.value)}/></label><label>附加请求字段（JSON 对象）<textarea rows={3} value={extra} onChange={e=>setExtra(e.target.value)}/></label><label>响应成功字段（可留空）<input placeholder="例如 code 或 data.code" value={edit.success_field} onChange={e=>setEdit({...edit,success_field:e.target.value})}/></label><label>字段成功值<input placeholder="例如 0" value={edit.success_value} onChange={e=>setEdit({...edit,success_value:e.target.value})}/></label></div><p className="notification-hint">使用 POST 请求。未填写响应字段时，以 HTTP 2xx 判定接收成功；填写后还会核对 JSON 响应中的字段值。地址和请求头保存后不回显；修改地址时请重新填写请求头或填空 JSON 对象清空。</p></details><fieldset><legend>接收这些监控的信号</legend>{state.monitors.length?state.monitors.map(m=><label className="notification-check" key={m.id}><input type="checkbox" checked={edit.monitor_ids.includes(m.id)} onChange={e=>setEdit({...edit,monitor_ids:e.target.checked?[...edit.monitor_ids,m.id]:edit.monitor_ids.filter(id=>id!==m.id)})}/>{m.name} · {m.enabled?'运行中':'已暂停'}{!m.schedule&&` · 间隔 ${m.interval_seconds} 秒`}</label>):<p>还没有监控，请先在「扫描与监控」创建任务。</p>}</fieldset>
 <label className="notification-check"><input type="checkbox" checked={edit.enabled} onChange={e=>setEdit({...edit,enabled:e.target.checked})}/>启用此渠道的监控通知</label>
 {!edit.monitor_ids.length&&<p className="notification-hint">未选择监控时，只可发送手动测试消息。</p>}
 <div className="notification-actions"><button type="submit">{busy?'处理中…':'保存渠道'}</button>{edit.id&&<><button type="button" onClick={()=>void action(async()=>{await request('/channels/'+edit.id+'/test','POST',{});await load();setNotice('测试消息已排队，请稍后刷新记录并核对接收端。测试使用服务端已保存的配置。')})}>发送测试消息</button><button type="button" onClick={()=>{if(window.confirm('删除此渠道并取消待发消息？'))void action(async()=>{await request('/channels/'+edit.id,'DELETE');choose(empty());await load();setNotice('渠道已删除。')})}}>删除渠道</button></>}</div>
 </fieldset></form>
 <p className="notification-hint">保存不会发送测试消息。接收端接收成功不等于用户已读；结果待核对时请查看接收端记录。</p>
 <h4>最近投递记录</h4><div className="notification-records">{state.records.length?state.records.map(r=><article key={r.id}><strong>{state.channels.find(c=>c.id===r.channel_id)?.name||'已删除渠道'} · {labels[r.status]||r.status}</strong><small>{new Date(r.created*1000).toLocaleString('zh-CN')} · 请求 {r.attempts} 次 · {r.event_id.startsWith('test:')?'测试消息':r.event_id}</small>{r.error&&<p>{r.error}</p>}</article>):<p>暂无投递记录。</p>}</div>
 </>}
 </>}{notice&&<p role="status">{notice}</p>}{error&&<p role="alert">{error}</p>}</section>;
}
