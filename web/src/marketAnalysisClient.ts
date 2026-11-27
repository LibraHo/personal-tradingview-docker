import {getChartCsrf,secureChart} from './secureChart';

export const analysisPath = secureChart ? '/api/trade/market-analysis' : '/api/market-analysis';

async function responseData<T>(response:Response):Promise<T> {
  const data = await response.json().catch(()=>null);
  if (!response.ok || !data) {
    throw Error(typeof data?.detail==='string' ? data.detail :
      response.status===401 ? '请在当前看盘入口重新登录。' : '未收到分析服务的有效响应，请重试。');
  }
  return data as T;
}

function pause(signal:AbortSignal,ms:number) {
  return new Promise<void>((resolve,reject)=>{
    signal.throwIfAborted();
    const stop=()=>{window.clearTimeout(timer);reject(signal.reason)};
    const timer=window.setTimeout(()=>{signal.removeEventListener('abort',stop);resolve()},ms);
    signal.addEventListener('abort',stop,{once:true});
  });
}

export function archiveHeaders() {
  const name='market-analysis-archive-key';
  let key=localStorage.getItem(name);
  if (!key || !/^[a-f0-9]{64}$/.test(key)) {
    key=Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');
    localStorage.setItem(name,key);
  }
  return {'X-Analysis-Archive':key};
}

export async function submitAnalysis(body:unknown,signal?:AbortSignal,archive=false) {
  const headers:Record<string,string>={'Content-Type':'application/json'};
  if(archive) Object.assign(headers,archiveHeaders());
  if(secureChart) headers['X-CSRF-Token']=getChartCsrf();
  const {id}=await responseData<{id:string}>(await fetch(analysisPath+'/jobs',{
    method:'POST',signal,headers,body:JSON.stringify(body),
  }));
  return id;
}

export async function readArchive<T>(suffix:string,signal?:AbortSignal) {
  return responseData<T>(await fetch(analysisPath+'/archive'+suffix,{headers:archiveHeaders(),cache:'no-store',signal}));
}

export async function waitAnalysis<T>(id:string,signal:AbortSignal,archived=false):Promise<T> {
  const path=analysisPath+'/jobs/'+encodeURIComponent(id);
  let failures=0;
  for (;;) {
    await pause(signal,1200);
    let response:Response;
    try {
      response=await fetch(path,{signal,cache:'no-store'});
    } catch(error) {
      if(signal.aborted || (!archived && ++failures>=4)) throw error;
      continue;
    }
    if([502,503,504].includes(response.status) && (archived || ++failures<4)) continue;
    if(archived && response.status===404) return readArchive<T>('/'+encodeURIComponent(id),signal);
    const job=await responseData<{state:'running'|'done'|'failed';result:T;message?:string}>(response);
    failures=0;
    if(job.state==='done') return job.result;
    if(job.state!=='running') throw Error(job.message||'分析失败，请重试。');
  }
}

export async function marketAnalysisRequest<T>(body:unknown,signal:AbortSignal):Promise<T> {
  return waitAnalysis<T>(await submitAnalysis(body,signal),signal);
}
