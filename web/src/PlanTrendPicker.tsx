import {useEffect, useState} from 'react';
import {drawingsForPeriod, normalizeDrawingRecords, type TrendDrawing} from './drawingTools';
import {validTrendAnchors, type PlanCondition} from './tradePlanAnalysis';
import type {ReviewMarket} from './reviewClient';

export default function PlanTrendPicker({market, symbol, condition, name, onChange}: {
  market:ReviewMarket; symbol:string; condition:PlanCondition; name:string;
  onChange:(params:PlanCondition['params'])=>void;
}) {
  const [records, setRecords] = useState<Record<string,TrendDrawing[]>>({});
  const [status, setStatus] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setStatus('正在读取图上趋势线…');
    fetch('/api/settings/workspace?drawings_only=true',{signal:controller.signal, cache:'no-store'})
      .then(async response => {
        if (!response.ok) throw Error();
        const result = await response.json();
        if (!controller.signal.aborted) {
          setRecords(normalizeDrawingRecords(result.value?.markets?.[market]?.trends, 'trend'));
          setStatus('');
        }
      })
      .catch(() => { if (!controller.signal.aborted) setStatus('读取图上趋势线失败'); });
    return () => controller.abort();
  }, [market, refresh]);
  const key = (p:PlanCondition['params']) => [p.time1,p.price1,p.time2,p.price2].join('/');
  const options = new Map<string,PlanCondition['params']>();
  for (const line of drawingsForPeriod(records,symbol,condition.period)) {
    const [a,b] = [...line.points].sort((left,right) => left.time-right.time);
    if (!a || !b) continue;
    const params = {time1:a.time,price1:a.price,time2:b.time,price2:b.price};
    if (validTrendAnchors(params)) options.set(key(params),params);
  }
  const selected = validTrendAnchors(condition.params) ? key(condition.params) : '';
  if (selected) options.set(selected,condition.params);
  const formatTime = (t:unknown) => new Date(Number(t)*1000).toLocaleString('zh-CN',{
    timeZone:market==='CN'?'Asia/Shanghai':'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',hour12:false,
  });
  return <div className="plan-trend-picker">
    <label>图上趋势线
      <select aria-label={name+'趋势线'} required value={selected}
        onChange={event=>onChange(options.get(event.target.value) ?? {})}>
        <option value="">请选择趋势线</option>
        {Array.from(options,([id,p])=><option key={id} value={id}>
          {formatTime(p.time1)} · {String(p.price1)} → {formatTime(p.time2)} · {String(p.price2)}
        </option>)}
      </select>
    </label>
    <small>{status || (options.size ? '保存两点并向右延伸，按前后两根 K 线的价格判断穿越。' : '请先在此标的的图表上画一条趋势线，然后刷新。')}</small>{' '}
    <button type="button" onClick={()=>setRefresh(v=>v+1)}>刷新趋势线</button>
  </div>;
}
