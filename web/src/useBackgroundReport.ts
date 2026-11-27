import {useEffect,useRef,useState} from 'react';
import {submitAnalysis,waitAnalysis} from './marketAnalysisClient';
import type {AnalysisChart} from './MarketAnalysis';
import type {PlanPeriod} from './tradeBookClient';

export type Report = {
  analysis:string; started:string; completed:string;
  coverage:{period:PlanPeriod;mode:AnalysisChart['mode'];count:number;last:number|null;stale:boolean;issue:string|null}[];
};
export type OpenReport = {chart:AnalysisChart; result?:Report; error?:string};
type Pending = {id:string; chart:AnalysisChart};
const pendingKey='market-chart-pending-report';

function restore():Pending|null {
  try {
    const value=JSON.parse(sessionStorage.getItem(pendingKey)||'null');
    return typeof value?.id==='string' && value.chart?.symbol ? value:null;
  } catch {return null}
}

export function useBackgroundReport(onFinished:(item:OpenReport)=>void) {
  const [pending,setPending]=useState<Pending|null>(restore);
  const [submitting,setSubmitting]=useState(false);
  const busy=useRef(false);
  const finished=useRef(onFinished);
  finished.current=onFinished;
  useEffect(()=>{
    if(!pending) return;
    const controller=new AbortController();
    async function monitor(task:Pending) {
      let item:OpenReport;
      try {
        item={chart:task.chart,result:await waitAnalysis<Report>(task.id,controller.signal,true)};
      } catch(error) {
        if(controller.signal.aborted) return;
        item={chart:task.chart,error:(error as Error).message};
      }
      if(controller.signal.aborted) return;
      try {sessionStorage.removeItem(pendingKey)} catch {}
      setPending(null);
      finished.current(item);
    }
    void monitor(pending);
    return ()=>controller.abort();
  },[pending]);
  async function start(chart:AnalysisChart,references:PlanPeriod[]) {
    if(busy.current || pending) return;
    busy.current=true;setSubmitting(true);
    try {
      const id=await submitAnalysis({...chart,references},undefined,true);
      const task={id,chart};
      try {sessionStorage.setItem(pendingKey,JSON.stringify(task))} catch {}
      setPending(task);
    } catch(error) {
      finished.current({chart,error:(error as Error).message});
    } finally {busy.current=false;setSubmitting(false)}
  }
  return {start,busy:submitting || !!pending};
}
