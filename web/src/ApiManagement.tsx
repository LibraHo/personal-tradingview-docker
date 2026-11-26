import {useEffect,useState} from 'react';
import DrawingApiPanel from './DrawingApiPanel';
import './api-management.css';

const scopes:Record<string,string>={read:'只读：行情、关注列表、扫描结果与事件',manage:'管理：保存方案、执行扫描、启停监控','review:read':'复盘读取：复盘、计划、成交、持仓与导出','review:write':'复盘写入：复盘、计划、成交、持仓与同步',tokens:'凭证管理：创建和撤销其他 API 凭证'};
export default function ApiManagement(){
 const [inventory,setInventory]=useState<any>(null),[tokens,setTokens]=useState<any[]>([]),[csrf,setCsrf]=useState('');
 const [query,setQuery]=useState(''),[category,setCategory]=useState(''),[name,setName]=useState('OpenClaw 只读'),[permissions,setPermissions]=useState(['read']);
 const [secret,setSecret]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[revokeId,setRevokeId]=useState('');
 const secure=location.protocol==='https:';
 async function request(path:string,method='GET',body?:unknown){
  const r=await fetch('/api/trade/api-management/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const v=await r.json();if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:'请求失败');return v;
 }
 const reloadTokens=async()=>setTokens((await request('tokens')).items);
 async function action(fn:()=>Promise<void>){setBusy(true);setNotice('');try{await fn()}catch(e){setNotice(String(e instanceof Error?e.message:e))}finally{setBusy(false)}}
 useEffect(()=>{if(!secure)return;void action(async()=>{
  const r=await fetch('/api/trade/auth');const auth=await r.json();if(!auth.authenticated)throw Error('请从安全看盘入口登录后管理 API');setCsrf(auth.csrf);
  await Promise.all([request('inventory').then(setInventory),reloadTokens()]);
 });},[]);
 function download(){const blob=new Blob([JSON.stringify(inventory.schemas,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='nas-market-openapi.json';a.click();URL.revokeObjectURL(url)}
 const rows=(inventory?.items||[]).filter((r:any)=>(!category||r.category===category)&&[r.path,r.method,r.summary,r.auth].join(' ').toLowerCase().includes(query.toLowerCase()));
 return <section className="api-management"><h2>API 管理</h2><p>统一查看行情、板块、情绪、扫描、后台事件、画线及交易接口。机器凭证与网页登录分开管理。</p>
 {!secure?<p>凭证管理需要安全登录。<a href={`https://${location.hostname}:8443/chart?view=api`}>打开 HTTPS API 管理</a></p>:<>
 <div className="api-summary"><div><strong>OpenClaw 基础地址</strong><code>{location.origin}/api/v1</code><small>NAS 容器可信内网：http://market:8000/api/v1；Authorization: Bearer &lt;token&gt;</small></div><div><strong>增量读取事件</strong><code>GET /api/v1/events?after=0&amp;limit=100</code><small>保存返回游标，以 event_id 去重；Token 不放入 URL。</small></div></div>
 <h3>API 凭证</h3><p>为 OpenClaw 写复盘启用「复盘读取」和「复盘写入」。复盘入口为 <code>/api/v1/review</code>。凭证管理权限可创建或撤销其他凭证，请仅授予管理客户端。</p>
 <fieldset disabled={busy||!csrf}><label>凭证名称<input maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label><div className="api-permissions">{Object.entries(scopes).map(([key,label])=><label key={key}><input type="checkbox" checked={permissions.includes(key)} onChange={e=>setPermissions(v=>e.target.checked?[...v,key]:v.filter(x=>x!==key))}/>{label}</label>)}</div><button disabled={!name.trim()||!permissions.length} onClick={()=>void action(async()=>{const v=await request('tokens','POST',{name,scopes:permissions});setSecret(v.token);setNotice('新凭证仅在此显示一次，请保存到客户端秘密配置。');await reloadTokens()})}>创建凭证</button></fieldset>
 {secret&&<div className="api-secret"><label>新凭证（仅本次可见）<input readOnly autoComplete="off" type="password" value={secret}/></label><button onClick={()=>void action(async()=>{await navigator.clipboard.writeText(secret);setNotice('已复制新凭证')})}>复制新凭证</button><button onClick={()=>setSecret('')}>已保存，清除显示</button></div>}
 <div className="api-table"><table><thead><tr><th>名称</th><th>权限</th><th>创建时间</th><th>状态 / 操作</th></tr></thead><tbody>{tokens.map(t=><tr key={t.id}><td>{t.name}<small>{t.id}</small></td><td>{t.scopes.join('、')}</td><td>{new Date(t.created*1000).toLocaleString()}</td><td>{t.revoked?'已撤销':revokeId===t.id?<><span>撤销后该客户端立即失去访问权限。</span><button disabled={busy} onClick={()=>void action(async()=>{await request('tokens/'+t.id,'DELETE');setRevokeId('');await reloadTokens();setNotice('凭证已撤销')})}>确认撤销</button><button onClick={()=>setRevokeId('')}>取消</button></>:<button onClick={()=>setRevokeId(t.id)}>撤销</button>}</td></tr>)}</tbody></table></div>
 <DrawingApiPanel/>
 <h3>全部接口目录</h3><p>目录读取两个服务实际注册的 OpenAPI。交易接口只接受网页登录会话，不接受扫描凭证；此页不执行交易请求。代理路径与原始接口分别标明来源。</p>
 <div className="api-filters"><input aria-label="搜索接口" placeholder="搜索路径、方法、说明或权限" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="接口分类" value={category} onChange={e=>setCategory(e.target.value)}><option value="">全部分类</option>{Array.from(new Set<string>((inventory?.items||[]).map((r:any)=>r.category))).map(c=><option key={c}>{c}</option>)}</select><button disabled={!inventory} onClick={download}>下载两个服务的 OpenAPI</button><button disabled={busy} onClick={()=>void action(async()=>setInventory(await request('inventory')))}>刷新目录</button><span>{rows.length} 个接口</span></div>
 {inventory?.errors.map((e:string)=><p role="alert" key={e}>{e}</p>)}
 <div className="api-routes">{rows.map((r:any)=><details key={r.source+r.method+r.path}><summary><b>{r.method}</b> <code>{r.path}</code><span>{r.summary}</span><small>{r.source==='https'?'HTTPS 服务':'行情服务'} · {r.auth}</small></summary><p>{r.description||'参数、请求体和响应定义如下；$ref 对应下方模型定义或下载文件中的 components。'}</p><pre>{JSON.stringify(r.operation,null,2)}</pre></details>)}</div>
 {inventory&&<><h3>实时推送</h3>{inventory.websockets.map((w:any)=><p key={w.path}><code>WebSocket {w.path}</code> · {w.auth}</p>)}<details><summary>数据模型定义（components）</summary><pre>{JSON.stringify(Object.fromEntries(Object.entries(inventory.schemas).map(([key,s]:any)=>[key,s.components])),null,2)}</pre></details></>}
 </>}
 <p role="status">{notice}</p></section>
}
