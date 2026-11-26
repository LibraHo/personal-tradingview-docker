import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, X } from 'lucide-react';
import type { Bar, Indicator } from './indicators';
import type { ReviewMarket } from './reviewClient';
import { periodNames, type PlanPeriod, type RecordTarget } from './tradeBookClient';
import type { PlanDetails } from './tradePlanAnalysis';
import TradingPlanEditor from './TradingPlanEditor';

type Props = {
  market: ReviewMarket;
  symbol: string;
  period: PlanPeriod;
  mode: PlanDetails['mode'];
  indicators: Indicator[];
  bars: Bar[];
  stockName?: string;
  limitUp?: boolean;
  onClose: () => void;
};
export default function ChartPlanDialog({
  market,
  symbol,
  period,
  mode,
  indicators,
  bars,
  stockName,
  limitUp=false,
  onClose,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [saved, setSaved] = useState<RecordTarget | null>(null),
    [busy, setBusy] = useState(false);
  const [context] = useState({ market, symbol, period, mode, indicators, bars, stockName });
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  const archive = new URL(location.href);
  archive.searchParams.set('view', 'review');
  archive.searchParams.set('section', 'ledger');
  return createPortal(
    <dialog
      ref={dialog}
      className="chart-plan-dialog"
      aria-label="创建交易计划"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <header className="chart-plan-heading">
        <div>
          <span>
            {context.market === 'CN' ? 'A 股' : '美股'} · {context.symbol} · {periodNames[context.period]}
          </span>
          <h2>
            {saved ? '计划已保存' : '创建交易计划'}
            {context.stockName && <small>{context.stockName}</small>}
          </h2>
        </div>
        <button type="button" aria-label="关闭交易计划" disabled={busy} onClick={onClose}>
          <X size={19} />
        </button>
      </header>
      {saved ? (
        <div className="chart-plan-saved">
          <Check size={30} />
          <h3>已保存到交易档案</h3>
          <p>可以在「每日复盘 → 交易档案 → 交易计划」继续查看、修订和关联成交。</p>
          <div>
            <button type="button" onClick={onClose}>
              {limitUp ? '返回打板行情' : '返回图表'}
            </button>
            <a href={archive.href}>查看交易档案</a>
          </div>
        </div>
      ) : (
        <TradingPlanEditor
          market={context.market}
          symbol={context.symbol}
          period={context.period}
          mode={context.mode}
          indicators={context.indicators}
          initialBars={context.bars}
          limitUp={limitUp}
          onSaved={(target) => {
            setBusy(false);
            setSaved(target);
          }}
          onCancel={onClose}
          onBusyChange={setBusy}
        />
      )}
    </dialog>,
    document.body,
  );
}
