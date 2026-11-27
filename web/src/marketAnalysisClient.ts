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

export async function marketAnalysisRequest<T>(body:unknown,signal:AbortSignal):Promise<T> {
  const headers:Record<string,string>={'Content-Type':'application/json'};
  if(secureChart) headers['X-CSRF-Token']=getChartCsrf();
  const {id}=await responseData<{id:string}>(await fetch(analysisPath+'/jobs',{
    method:'POST',signal,headers,body:JSON.stringify(body),
  }));
  const path=analysisPath+'/jobs/'+encodeURIComponent(id);
  let failures=0;
  for (;;) {
    await pause(signal,1200);
    let response:Response;
    try {
      response=await fetch(path,{signal,cache:'no-store'});
    } catch(error) {
      if(signal.aborted || ++failures>=4) throw error;
      continue;
    }
    if([502,503,504].includes(response.status) && ++failures<4) continue;
    const job=await responseData<{state:'running'|'done'|'failed';result:T;message?:string}>(response);
    failures=0;
    if(job.state==='done') return job.result;
    if(job.state!=='running') throw Error(job.message||'分析失败，请重试。');
  }
}
