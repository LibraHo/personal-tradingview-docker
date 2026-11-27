import {useEffect, useState} from 'react';

type Row = {symbol: string; profit_ratio: number | null; interval_overlap: number | null};
type Page = {rows: Row[]; total: number; provider: string};
const PAGE_SIZE = 20;
const percent = (value: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? (value * 100).toFixed(2) + '%' : '—';

export default function ChipSummary({market}: {market: 'CN' | 'US'}) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setPage(null);
    setError('');
    async function read() {
      const response = await fetch('/api/chips/summary?market=' + market + '&offset=' + offset + '&limit=' + PAGE_SIZE,
        {signal: controller.signal});
      const data = await response.json();
      if (!response.ok) throw Error(data.detail || '读取筹码快照失败');
      if (!controller.signal.aborted) setPage(data);
    }
    void read().catch(err => {if (!controller.signal.aborted) setError(String(err.message || err))});
    return () => controller.abort();
  }, [market, open, offset, attempt]);

  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{market === 'CN' ? '沪深' : '美股'}筹码汇总快照</summary>
    {error ? <p role="alert">{error} <button onClick={() => setAttempt(n => n + 1)}>重试</button></p>
      : !page ? <p role="status">读取中…</p>
      : <><p>{page.provider} · 当前快照，仅用于查看当次查询结果。</p>
        {page.rows.length ? <table><thead><tr><th>证券</th><th>获利比例</th><th>筹码区间重合度</th></tr></thead>
          <tbody>{page.rows.map(row => <tr key={row.symbol}><td>{row.symbol}</td>
            <td>{percent(row.profit_ratio)}</td><td>{percent(row.interval_overlap)}</td></tr>)}</tbody></table>
          : <p>当前页没有筹码记录</p>}
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
        <button disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button>
      </>}
  </details>;
}
