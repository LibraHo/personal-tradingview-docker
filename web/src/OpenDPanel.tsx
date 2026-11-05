import {useEffect,useRef,useState} from 'react';
import {LockKeyhole,RefreshCw,CheckCircle2,PlugZap} from 'lucide-react';
import {secureChart} from './secureChart';
import './opend.css';

type Status={available:boolean;stage:string;revision:string;version:string;message:string;retry_allowed:boolean};
const labels:Record<string,string>={starting:'OpenD 正在启动',account:'输入 moomoo 账号',password:'输入登录密码',waiting:'正在处理登录',sms:'验证手机验证码',captcha:'验证图形验证码',ready:'OpenD 已登录',error:'登录未完成',unavailable:'登录服务未就绪'};
const fields:Record<string,{label:string;hint:string;button:string}>={account:{label:'moomoo 账号',hint:'moomoo ID、邮箱，或 +区号 手机号',button:'下一步'},password:{label:'moomoo 登录密码',hint:'输入登录密码，不是交易密码',button:'登录'},sms:{label:'手机验证码',hint:'输入收到的验证码',button:'验证'},captcha:{label:'图形验证码',hint:'输入图片中的字符',button:'验证'}};
export default function OpenDPanel({tradingUrl,onReady}:{tradingUrl:string;onReady:()=>void}){
 const [status,setStatus]=useState<Status|null>(null),[value,setValue]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[picture,setPicture]=useState<string|null>(null),[notice,setNotice]=useState('');
 const live=useRef(true),csrf=useRef(''),revision=useRef(''),requestBusy=useRef(false),previousStage=useRef(''),readyCallback=useRef(onReady),input=useRef<HTMLInputElement>(null),epoch=useRef(0),sending=useRef(false);
 readyCallback.current=onReady;
 const read=async()=>{
  if(!secureChart||requestBusy.current||sending.current)return;
  const currentEpoch=epoch.current;
  requestBusy.current=true;
  try{
   const r=await fetch('/api/trade/opend/status',{cache:'no-store'});const s=await r.json();
   if(!r.ok)throw Error(r.status===401?'平台登录已过期，请刷新页面后登录。':s.detail||'无法读取连接状态');
   if(!live.current||currentEpoch!==epoch.current)return;
   if(revision.current!==s.revision){setValue('');revision.current=s.revision}
   setStatus(s);
   if(s.stage==='ready'&&previousStage.current!=='ready')readyCallback.current();
   previousStage.current=s.stage;
   if(s.stage==='captcha'){
    const p=await fetch('/api/trade/opend/captcha',{cache:'no-store'});
    if(p.ok){const body=await p.json();if(live.current&&currentEpoch===epoch.current)setPicture(body.image||null)}
   }else setPicture(null);
  }catch(e){if(live.current&&currentEpoch===epoch.current)setError(e instanceof Error?e.message:'连接检查失败')}
  finally{requestBusy.current=false}
 };
 useEffect(()=>{
  live.current=true;
  if(secureChart){fetch('/api/trade/auth').then(r=>r.json()).then(a=>{if(live.current)csrf.current=a.csrf||''}).catch(()=>{});void read()}
  const timer=secureChart?setInterval(()=>{if(!document.hidden)void read()},2000):undefined;
  return()=>{live.current=false;clearInterval(timer);csrf.current=''};
 },[]);
 useEffect(()=>{if(status&&fields[status.stage])input.current?.focus()},[status?.stage]);
 const send=async(action:string)=>{
  if(sending.current||!status)return;
  sending.current=true;epoch.current++;
  setBusy(true);setError('');setNotice('');
  const entered=value;setValue('');
  try{
   const r=await fetch('/api/trade/opend/input',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.current},body:JSON.stringify({action,revision:status.revision,value:entered})});
   const data=await r.json();if(!r.ok)throw Error(data.detail||'登录操作未完成');
   if(live.current){setStatus(data);revision.current=data.revision;if(action==='request_sms')setNotice('验证码请求已发送，请等待 OpenD 验证结果。')}
  }catch(e){if(live.current)setError(e instanceof Error?e.message:'请求失败，请刷新状态后重试')}
  finally{sending.current=false;if(live.current){setBusy(false);void read()}}
 };
 if(!secureChart){const url=new URL(tradingUrl);url.pathname='/chart';url.search='?settings=connection';return <section className="opend-panel"><div className="opend-heading"><LockKeyhole/><div><h3>安全连接 OpenD</h3><p>请进入 HTTPS 看盘页，使用平台密码登录后管理 OpenD。</p></div></div><a className="opend-primary" href={url.toString()}>打开安全登录页面</a><p className="opend-muted">账号和密码只在加密页面输入。</p></section>}
 const field=status?fields[status.stage]:undefined;
 return <section className="opend-panel" aria-label="OpenD 连接与登录"><div className="opend-heading">{status?.stage==='ready'?<CheckCircle2 className="opend-ok"/>:<PlugZap/>}<div><h3>OpenD 连接</h3><p>登录现有 moomoo OpenD，恢复行情服务。</p></div><button type="button" aria-label="刷新 OpenD 状态" onClick={()=>{setError('');void read()}} disabled={busy}><RefreshCw size={16}/></button></div>
  <div className={'opend-status '+(status?.stage==='ready'?'is-ready':'')} role="status"><strong>{status?labels[status.stage]||'正在读取状态':'正在读取状态…'}</strong>{status?.version&&<span>v{status.version}</span>}</div>
  {status?.message&&<p className="opend-warning">{status.message}</p>}{error&&<p role="alert" className="opend-warning">{error}</p>}{notice&&<p role="status" className="opend-muted">{notice}</p>}
  {field&&<form autoComplete="off" onSubmit={e=>{e.preventDefault();void send(status!.stage)}}><label htmlFor="opend-login-input">{field.label}</label>{status?.stage==='captcha'&&(picture?<img className="opend-captcha" src={picture} alt="OpenD 图形验证码"/>:<p className="opend-muted">图片尚未就绪，请点击获取图形验证码。</p>)}<input ref={input} id="opend-login-input" key={status?.stage} aria-label={field.label} type={status?.stage==='password'?'password':'text'} inputMode={status?.stage==='sms'?'numeric':'text'} autoComplete={status?.stage==='password'?'new-password':'off'} spellCheck={false} maxLength={status?.stage==='password'?256:128} value={value} onChange={e=>setValue(e.target.value)} placeholder={field.hint} disabled={busy}/><div className="opend-actions"><button className="opend-primary" type="submit" disabled={busy||!value.trim()||!csrf.current}>{busy?'提交中…':field.button}</button>{status?.stage==='sms'&&<button type="button" disabled={busy} onClick={()=>void send('request_sms')}>发送手机验证码</button>}{status?.stage==='captcha'&&<button type="button" disabled={busy} onClick={()=>void send('request_captcha')}>获取图形验证码</button>}</div></form>}
  {status?.stage==='ready'&&<p className="opend-success">登录完成。行情会在打开图表时按需连接；交易仍需单独解锁。</p>}
  {status?.retry_allowed&&<details className="opend-retry"><summary>重新开始登录</summary><p>将重启 OpenD 登录进程。存在运行中的策略、待处理订单或待补挂止损时，系统会阻止重启。</p><button type="button" disabled={busy} onClick={()=>void send('restart')}>重启 OpenD 并重新登录</button></details>}
  <footer><LockKeyhole size={14}/><span>手动登录 · 平台不保存账号、密码或验证码。此处显示登录进程状态，实际行情连接以页顶状态为准。</span></footer>
 </section>;
}
