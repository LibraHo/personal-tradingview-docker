import {useEffect, useState} from 'react';

import {Bot, Cable, Check, ChevronRight, ClipboardList, LockKeyhole, Power, Server} from 'lucide-react';
import './agent-settings.css';
import {getChartCsrf,secureChart} from './secureChart';

type Provider = 'server' | 'local' | 'openclaw';
type Settings = {provider:Provider; url:string; agent:string; has_token:boolean};
const modes = [
  {id:'openclaw', label:'OpenClaw', icon:Cable},
  {id:'server', label:'服务端默认', icon:Server},
  {id:'local', label:'关闭 AI', icon:Power},
] as const;
const path = '/api/trade/agent-settings';

export default function AgentSettings({secureUrl}:{secureUrl:string}) {
  const [config,setConfig] = useState<Settings|null>(null);
  const [token,setToken] = useState('');
  const [busy,setBusy] = useState(false), [notice,setNotice] = useState('');
  const [retry,setRetry] = useState(0), [needsLogin,setNeedsLogin] = useState(false);
  const secure = location.protocol==='https:' && secureChart;
  useEffect(()=>{
    if(!secure) return;
    const controller = new AbortController();
    async function load(){
      const response = await fetch(path,{signal:controller.signal,cache:'no-store'});
      if(response.status===401){setNeedsLogin(true);throw Error('登录已过期，请重新登录后继续配置。')}
      if(!response.ok) throw Error('读取 AI 助手配置失败（'+response.status+'）');
      const data = await response.json();
      if(!controller.signal.aborted){setConfig(data);setNotice('');}
    }
    void load().catch(e=>{if(!controller.signal.aborted)setNotice(e instanceof TypeError?'无法连接当前 NAS 的设置接口，请重新读取。':e.message)});
    return ()=>controller.abort();
  },[secure,retry]);
  async function save(){
    if(!config || busy) return;
    setBusy(true);setNotice('');
    try {
      const response = await fetch(path,{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':getChartCsrf()},
        body:JSON.stringify(config.provider==='openclaw'?{provider:config.provider,url:config.url,agent:config.agent,token:token||null}:{provider:config.provider})});
      const data = await response.json();
      if(response.status===401){setNeedsLogin(true);throw Error('登录已过期，请重新登录后继续配置。')}
      if(!response.ok) throw Error(typeof data.detail==='string'?data.detail:'保存设置失败');
      setToken('');
      const saved = await fetch(path,{cache:'no-store'});
      if(!saved.ok) throw Error('配置已提交，重新读取失败，请刷新核对。');
      setConfig(await saved.json());
      setNotice('已保存，下一次调用将使用这份配置。');
    } catch(e){setNotice(e instanceof TypeError?'未收到服务器确认，请重新打开设置核对保存结果。':(e as Error).message)} finally{setBusy(false)}
  }
  const edit = (patch:Partial<Settings>) => {
    if(config) setConfig({...config,...patch});
    setNotice('');
  };
  return <section className="ai-settings" aria-labelledby="ai-settings-title">
    <div className="ai-settings-title">
      <span className="ai-symbol"><Bot size={23} aria-hidden="true"/></span>
      <div><h3 id="ai-settings-title">AI 助手</h3><p>NAS Market 可以调用你配置的 Agent，Agent 也可以通过授权 API 操作 NAS Market。</p></div>
    </div>
    {!secure ? <div className="ai-access"><LockKeyhole size={19} aria-hidden="true"/>
      <div><strong>连接管理</strong><p>登录安全看盘入口后，可以选择服务并管理凭证。</p></div>
      <a className="ai-action" href={secureUrl}>管理连接 <ChevronRight size={15}/></a>
    </div> : config ? <form onSubmit={e=>{e.preventDefault();void save()}}>
      <fieldset disabled={busy||needsLogin} className="ai-card">
        <div className="ai-card-head"><h4>连接方式</h4></div>
        <div className="ai-card-body">
          <div className="ai-modes" role="radiogroup" aria-label="连接方式">
            {modes.map(({id,label,icon:Icon})=><label key={id} className="ai-mode">
              <input type="radio" name="ai-provider" checked={config.provider===id} onChange={()=>edit({provider:id})}/>
              <span><Icon size={16}/>{label}<i aria-hidden="true">{config.provider===id&&<Check size={11}/>}</i></span>
            </label>)}
          </div>
          {config.provider==='openclaw'?<div className="ai-fields">
            <label>网关地址<input required type="url" value={config.url} placeholder="http://openclaw-gateway:18789" onChange={e=>edit({url:e.target.value})}/></label>
            <label>Agent ID<input value={config.agent} placeholder="留空使用默认 Agent" onChange={e=>edit({agent:e.target.value})}/></label>
            <label>网关凭证<input type="password" value={token} autoComplete="new-password" placeholder={config.has_token?'已配置 · 原地址留空可沿用':'输入网关凭证'} onChange={e=>{setToken(e.target.value);setNotice('')}}/></label>
          </div>:<p className="ai-description">{config.provider==='server'?'使用 NAS 服务端配置的 Agent。未配置时，交易计划使用本地规则。':'所有接入功能均停止调用外部 Agent，交易计划可继续使用本地规则。'}</p>}
        </div>
        <div className="ai-card-foot"><small>DeepSeek 直连已预留</small><button className="ai-action" type="submit">{busy?'正在保存…':'保存配置'}</button></div>
      </fieldset>
    </form> : !notice&&<p role="status">正在读取配置…</p>}
    {notice&&<p className="ai-notice" role="status">{notice}</p>}
    {needsLogin?<a href={secureUrl}>重新登录并返回 AI 助手设置</a>:secure&&!config&&notice&&<button type="button" onClick={()=>{setNotice('');setRetry(n=>n+1)}}>重新读取</button>}
    <div className="ai-usage"><Bot size={19} aria-hidden="true"/><div><h4>AI 盘面分析</h4><p>在图表工具栏选择参考周期，结合 K 线和成交量解读当前标的。</p></div></div>
    <div className="ai-usage"><Cable size={19} aria-hidden="true"/><div><h4>Agent 调用平台</h4><p>在「API 管理」查看接口和所需权限。外部 Agent 可读取行情、执行扫描、更新复盘；画线使用独立的画线凭证。</p></div></div>
    <div className="ai-usage"><ClipboardList size={19} aria-hidden="true"/><div>
      <h4>交易计划 · 一键填表</h4><p>点击时起草入场、退出和风险说明。核对后保存计划。</p>
    </div></div>
  </section>;
}
