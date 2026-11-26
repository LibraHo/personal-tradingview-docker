import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ChartNoAxesCombined, Check, Copy, RefreshCw, Save, WandSparkles, Zap } from 'lucide-react';
import type { Bar, Indicator } from './indicators';
import type { ReviewMarket } from './reviewClient';
import {
  displayTime,
  ledgerRequest,
  ledgerSymbol,
  periodNames,
  requestId,
  statusNames,
  type Plan,
  type PlanPeriod,
  type RecordTarget,
} from './tradeBookClient';
import {
  conditionLabel,
  followedDefense,
  emptyPlanLevels,
  estimatePlanCondition,
  newPlanDetails,
  planReferencePrices,
  planRiskValues,
  planPrice,
  displayPlanPrice,
  structureLabels,
  structureReferences,
  planSources,
  type PlanCondition,
  type PlanDetails,
  type PlanEstimate,
  type PlanRisk,
  type PlanLevels,
} from './tradePlanAnalysis';
import FillHistory, {recordDeliveryError} from './FillHistory';
import PlanConditionsEditor from './PlanConditionsEditor';
import './trade-plans.css';

type Draft = {
  symbol: string;
  period: PlanPeriod;
  side: 'BUY' | 'SELL';
  status: Plan['status'];
  size: string;
  stop: number | null;
  details: PlanDetails;
};
type Props = {
  market: ReviewMarket;
  symbol: string;
  period?: PlanPeriod;
  mode?: PlanDetails['mode'];
  indicators?: Indicator[];
  initialBars?: Bar[];
  limitUp?: boolean;
  plan?: Plan;
  onSaved: (target: RecordTarget) => void;
  onCancel: () => void;
  onBusyChange?: (busy: boolean) => void;
};
const noIndicators: Indicator[] = [];
const noBars: Bar[] = [];
const optionalNumber = (value: string) => (value === '' ? null : Number(value));
const amount = (value: number | null) =>
  value === null
    ? '待定'
    : value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 });

export default function TradingPlanEditor({
  market,
  symbol,
  period = '1d',
  mode = 'regular',
  indicators = noIndicators,
  initialBars = noBars,
  limitUp = false,
  plan,
  onSaved,
  onCancel,
  onBusyChange,
}: Props) {
  const storageKey = `market-plan-draft-v1:${market}:${plan?.id || symbol + ':' + period + (limitUp ? ':limit-up' : '')}`;
  const [initial] = useState(() => {
    const details = plan?.details
      ? structuredClone(plan.details)
      : newPlanDetails(plan?.period || period, market === 'CN' ? 'regular' : mode, indicators);
    if (!plan && limitUp && market==='CN') {
      details.strategy='limit_up';
      details.entry.items=[];details.exit.items=[];
    }
    if (plan && !plan.details) {
      details.entry.items = [];
      details.exit.items = [];
      details.entry_note = plan.trigger;
    }
    if (!plan && initialBars.length) details.risk.entry_price = initialBars.at(-1)!.close;
    const value: Draft = {
      symbol: plan?.symbol || symbol,
      period: plan?.period || period,
      side: plan?.side || 'BUY',
      status: plan?.status || 'draft',
      size: plan?.size || '',
      stop: plan?.stop == null ? null : planPrice(plan.stop),
      details,
    };
    try {
      const cached = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (
        cached?.version === 1 &&
        cached.revision === (plan?.revision || 0) &&
        cached.value?.symbol === value.symbol &&
        cached.value.details?.version === 1
      )
        return {
          value: cached.value as Draft,
          key: String(cached.request_id || requestId()),
          restored: true,
        };
    } catch {
      /* Saving to NAS remains available when browser storage is unavailable. */
    }
    return { value, key: requestId(), restored: false };
  });
  const [draft, setDraft] = useState(initial.value),
    [dirty, setDirty] = useState(initial.restored),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(''),
    [notice, setNotice] = useState(initial.restored ? '已恢复本地草稿，尚未保存到 NAS。' : '');
  const [referencePeriod, setReferencePeriod] = useState<PlanPeriod>(initial.value.period),
    [refresh, setRefresh] = useState(0);
  const [editingStop, setEditingStop] = useState(false);
  const [filling, setFilling] = useState(false);
  const [fillStarted,setFillStarted] = useState(0), [elapsed,setElapsed] = useState(0);
  const [fillRevision,setFillRevision] = useState(0), [fillFailure,setFillFailure] = useState('');
  useEffect(()=>{
    if(!filling) return;
    const timer = window.setInterval(()=>setElapsed(Math.floor((Date.now()-fillStarted)/1000)),1000);
    return ()=>window.clearInterval(timer);
  },[filling,fillStarted]);
  const fillRequest = useRef<AbortController | null>(null);
  useEffect(()=>()=>fillRequest.current?.abort(),[]);
  const [agentText, setAgentText] = useState(''),
    [agentInput, setAgentInput] = useState('');
  const [data, setData] = useState<{
    key: string;
    bars: Partial<Record<PlanPeriod, Bar[]>>;
    issues: Partial<Record<PlanPeriod, string>>;
    loading: boolean;
  }>({ key: '', bars: {}, issues: {}, loading: true });
  const initialContext = useRef({ bars: initialBars, period, symbol, mode });
  const details = draft.details;
  const board = details.strategy === 'limit_up';
  const autoStructure = details.structure_mode === 'auto';
  const following = details.risk.defense_reference;
  const indicatorGroups = useRef({entry: details.entry, exit: details.exit});
  const patch = (values: Partial<Draft>) => {
    setDraft((previous) => ({ ...previous, ...values }));
    setDirty(true);
    setError('');
  };
  const patchDetails = (values: Partial<PlanDetails>) => patch({ details: { ...details, ...values } });
  const patchRisk = (values: Partial<PlanRisk>) => patchDetails({ risk: { ...details.risk, ...values } });
  const patchLevels = (values: Partial<PlanLevels>) => patchDetails({ levels: { ...emptyPlanLevels, ...details.levels, ...values } });
  let canonical = '';
  try {
    canonical = ledgerSymbol(draft.symbol, market);
  } catch {
    /* A partially typed symbol is not a request. */
  }
  const requestedPeriods = [
    ...new Set([
      draft.period, referencePeriod, ...(following ? [following.period] : []),
      ...details.entry.items.map((item) => item.period),
      ...details.exit.items.map((item) => item.period),
    ]),
  ]
    .sort()
    .join(',');
  const dataKey = canonical + ':' + details.mode;

  useEffect(() => {
    if (!dirty) return;
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({ version: 1, revision: plan?.revision || 0, request_id: initial.key, value: draft }),
      );
    } catch {
      setNotice('本地草稿暂时无法保存，请使用下方按钮保存到 NAS。');
    }
  }, [draft, dirty, storageKey, plan?.revision, initial.key]);
  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);
  useEffect(() => {
    if (!canonical) {
      setData({ key: dataKey, bars: {}, issues: {}, loading: false });
      return;
    }
    const controller = new AbortController();
    setData((previous) => ({ ...previous, key: previous.key, loading: true }));
    async function load() {
      const bars: Partial<Record<PlanPeriod, Bar[]>> = {},
        issues: Partial<Record<PlanPeriod, string>> = {};
      await Promise.all(
        requestedPeriods.split(',').map(async (value) => {
          const selected = value as PlanPeriod;
          const context = initialContext.current;
          if (
            refresh === 0 &&
            context.symbol === canonical &&
            context.period === selected &&
            context.bars.length &&
            context.mode === details.mode
          ) {
            bars[selected] = context.bars;
            return;
          }
          const selectedMode = ['1d', '1w', '1mo'].includes(selected) ? 'regular' : details.mode;
          try {
            const response = await fetch(
              `/api/bars?symbol=${encodeURIComponent(canonical)}&period=${selected}&mode=${selectedMode}${refresh > 0 ? '&refresh=true' : ''}`,
              { signal: controller.signal },
            );
            const result = await response.json();
            if (!response.ok) throw Error(result.detail || '行情读取失败');
            bars[selected] = (result.bars as Bar[])
              .filter((bar) => selectedMode === 'all' || bar.session !== 'overnight')
              .filter((bar) => selectedMode !== 'regular' || bar.session === 'regular');
            if (result.stale) issues[selected] = '使用缓存行情';
          } catch (cause) {
            if (!controller.signal.aborted) issues[selected] = (cause as Error).message;
          }
        }),
      );
      if (!controller.signal.aborted) setData({ key: dataKey, bars, issues, loading: false });
    }
    void load();
    return () => controller.abort();
  }, [canonical, dataKey, requestedPeriods, details.mode, refresh]);
  const estimates = useMemo(() => {
    const output: Record<string, PlanEstimate> = {};
    if (data.key !== dataKey) return output;
    for (const condition of [...details.entry.items, ...details.exit.items]) {
      const bars = data.bars[condition.period];
      if (!bars) continue;
      try {
        output[condition.id] = estimatePlanCondition(bars, condition);
      } catch (cause) {
        output[condition.id] = {
          price: null,
          value: null,
          met: null,
          bar_time: bars.at(-1)?.time || 0,
          note: (cause as Error).message,
        };
      }
    }
    return output;
  }, [data, dataKey, details.entry, details.exit]);
  const references = useMemo(() => {
    if (board || data.key !== dataKey) return [];
    try {
      return planReferencePrices(
        data.bars[referencePeriod] || [],
        referencePeriod,
        details.risk.entry_price,
        indicators,
      );
    } catch {
      return [];
    }
  }, [board, data, dataKey, referencePeriod, details.risk.entry_price, indicators]);
  const structure = useMemo(() => structureReferences(data.key === dataKey ? data.bars[draft.period] || [] : [], draft.period),
    [data, dataKey, draft.period]);
  const levels = { ...emptyPlanLevels, ...details.levels };
  if (autoStructure) {
    for (const key of Object.keys(structureLabels) as (keyof typeof structureLabels)[])
      levels[key] = structure.find(row => row.label === structureLabels[key])?.price ?? null;
  }
  const followedPrice = useMemo(() => {
    if (!following || data.key !== dataKey) return null;
    return followedDefense(data.bars[following.period] || [], following, details.risk.entry_price);
  }, [data, dataKey, following, details.risk.entry_price]);
  const stop = following ? followedPrice : draft.stop == null ? null : planPrice(draft.stop);
  const risk = planRiskValues(details.risk.entry_price, stop, details.risk.qty, details.risk.budget);
  const useDefense = (price: number, label: string, track?: PlanRisk['defense_reference']) =>
    patch({ stop: planPrice(price), details: { ...details, risk: { ...details.risk, defense_source: label, defense_reference: track || null } } });
  const priorContext = plan?.symbol === canonical && plan.period === draft.period && plan.details?.mode === details.mode;
  const snapshotReferences = !board && !references.length && priorContext
    ? details.references.filter(row => row.period === referencePeriod && !Object.values(structureLabels).includes(row.label))
    : references.map(({condition: _condition, ...row}) => row);
  const snapshotDetails = { ...details, levels, references: [...snapshotReferences, ...(autoStructure ? structure : [])] };
  function changeStrategy(next: 'indicator' | 'limit_up') {
    if (next === 'limit_up') {
      indicatorGroups.current = {entry: details.entry, exit: details.exit};
      patch({stop, details: {...details, strategy: next, entry: {...details.entry, items: []},
        exit: {...details.exit, items: []}, risk: {...details.risk, defense_source: following ? '固定价' : details.risk.defense_source, defense_reference: null}}});
    } else patchDetails({strategy: next, ...indicatorGroups.current});
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || fillRequest.current) return;
    setBusy(true);
    setError('');
    try {
      if (following && stop === null) throw Error('跟随的防守位暂无行情，请刷新或改为固定价。');
      if (autoStructure && !data.bars[draft.period]?.length && plan?.details?.structure_mode === 'auto')
        throw Error('计划周期行情未就绪，请刷新后保存，或切换为手动保留原价位。');
      const names = details.entry.items.map(conditionLabel);
      const trigger =
        [names.join(details.entry.join === 'all' ? '，且 ' : '，或 '), details.entry_note]
          .filter(Boolean)
          .join('\n') || '待补充入场理由';
      const result = await ledgerRequest<Plan>(
        market,
        plan ? 'plans/' + plan.id : 'plans',
        plan ? 'PUT' : 'POST',
        {
          symbol: ledgerSymbol(draft.symbol, market),
          period: draft.period,
          side: draft.side,
          status: draft.status,
          size: draft.size,
          stop,
          trigger: trigger.slice(0, 2000),
          details: snapshotDetails,
          request_id: initial.key,
          ...(plan ? { revision: plan.revision } : {}),
        },
      );
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey) || 'null');
        if (stored?.request_id === initial.key) localStorage.removeItem(storageKey);
      } catch {
        /* The saved server record is authoritative. */
      }
      setDirty(false);
      onSaved({ kind: 'plan', id: result.id, symbol: result.symbol });
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function fillForm() {
    if (fillRequest.current || busy || !canonical) return;
    const controller = new AbortController();
    fillRequest.current = controller;
    const id = requestId();
    const deadline = window.setTimeout(()=>controller.abort('timeout'),90000);
    const started = Date.now();
    setFillStarted(started);setElapsed(0);setFillFailure('');
    setFilling(true);setNotice('');setError('');
    type Fields = Partial<Record<'title'|'entry_note'|'exit_note'|'risk_note'|'size'|'defense_source',string>
      & Record<'entry_price'|'stop'|'take_profit',number>>;
    try {
      const last = data.key === dataKey && !data.issues[draft.period] ? data.bars[draft.period]?.at(-1) : null;
      const result = await ledgerRequest<{source:'local'|'openclaw';fields:Fields}>(market,'autofill','POST',
        {request_id:id,symbol:canonical,period:draft.period,side:draft.side,size:draft.size,stop,details:snapshotDetails,last_close:last?.close ?? null},
        controller.signal);
      if (controller.signal.aborted) return;
      const f = result.fields;
      if (!Object.keys(f).length) {
        setNotice('现有内容已保留，暂无可补填的空项。');
        return;
      }
      patch({
        size: draft.size || f.size || '', stop: following ? draft.stop : draft.stop ?? f.stop ?? null,
        details: {...details,
          title: details.title || f.title || '', entry_note: details.entry_note || f.entry_note || '',
          exit_note: details.exit_note || f.exit_note || '',
          levels:{...emptyPlanLevels,...details.levels,take_profit:details.levels?.take_profit ?? f.take_profit ?? null},
          risk:{...details.risk,note:details.risk.note || f.risk_note || '',
            entry_price:details.risk.entry_price ?? f.entry_price ?? null,
            defense_source: f.stop!=null && draft.stop==null && !following ? f.defense_source || '固定价' : details.risk.defense_source},
          author: result.source === 'openclaw' ? 'agent' : details.author}
      });
      const labels:Record<string,string>={title:'名称',entry_note:'入场条件',exit_note:'出场条件',risk_note:'风险说明',
        entry_price:'入场参考价',stop:'防守价',take_profit:'止盈位',size:'仓位安排'};
      setNotice((result.source==='openclaw'?'OpenClaw':'本地规则')+'已填入'+Object.keys(f).map(k=>labels[k]).filter(Boolean).join('、')+'。请核对后保存。');
    } catch (cause) {
      if (!controller.signal.aborted || controller.signal.reason==='timeout') {
        const reason = controller.signal.reason==='timeout'?'等待响应超时，请查看填表记录核对结果':(cause as Error).message;
        if(!reason.includes(id)) recordDeliveryError(market,canonical,id,started,reason);
        setFillFailure(reason.includes(id)?reason:reason+' · 请求编号 '+id);
      }
    } finally {
      window.clearTimeout(deadline);
      if (!controller.signal.aborted || controller.signal.reason==='timeout') {
        setFilling(false);setFillRevision(n=>n+1);
      }
      fillRequest.current=null;
    }
  }

  async function copyForAgent() {
    const text = `请帮我完善${market === 'CN' ? 'A 股' : '美股'} ${draft.symbol} 的交易计划，保留我已写的理由，补充入场、出场和风险考虑。${board ? '这是打板计划，保留空指标列表，围绕首封、回封和炸板描述观察条件。' : ''}请返回 JSON 草稿，字段沿用下面的 details、size、stop，供我粘贴到交易计划编辑器。数值与指标来源请写在 notes 中。\n${JSON.stringify({ symbol: draft.symbol, period: draft.period, side: draft.side, size: draft.size, stop, details: snapshotDetails, ...(plan ? { id: plan.id, revision: plan.revision } : {}) }, null, 2)}`;
    setAgentText(text);
    try {
      await navigator.clipboard.writeText(text);
      setNotice('已复制给 Agent 的任务和当前草稿。');
    } catch {
      setNotice('任务说明已生成，可在下方选中文字复制。');
    }
  }
  function importAgent() {
    try {
      const input = JSON.parse(
        agentInput
          .trim()
          .replace(/^```(?:json)?\s*/, '')
          .replace(/\s*```$/, ''),
      );
      if (input.symbol && ledgerSymbol(input.symbol, market) !== ledgerSymbol(draft.symbol, market))
        throw Error('草稿标的与当前计划不同，请先核对。');
      const value = input.details ?? input;
      if (value.version !== 1) throw Error('请粘贴包含 version 为 1 的 details 草稿。');
      const normalized = {
        ...newPlanDetails(draft.period, details.mode, indicators),
        ...value,
        risk: { ...details.risk, ...value.risk },
        levels: { ...emptyPlanLevels, ...details.levels, ...value.levels },
        author: 'agent' as const,
        strategy: details.strategy || 'indicator',
        structure_mode: details.structure_mode || 'manual',
        tracking_period: details.tracking_period || null,
      };
      if (board && (normalized.entry?.items?.length || normalized.exit?.items?.length))
        throw Error('打板计划请使用文字条件，清空指标列表。');
      normalized.risk.defense_reference = details.risk.defense_reference || null;
      for (const group of [normalized.entry, normalized.exit]) {
        if (!['all', 'any'].includes(group?.join) || !Array.isArray(group.items) || group.items.length > 12)
          throw Error('草稿的条件列表格式不正确。');
        group.items = group.items.map((item: PlanCondition) => {
          if (
            !Object.hasOwn(planSources, item.source) ||
            !Object.hasOwn(periodNames, item.period) ||
            !item.params ||
            Array.isArray(item.params) ||
            typeof item.params !== 'object'
          )
            throw Error('草稿的指标或周期无效。');
          const defaults = newPlanConditionForImport(item);
          return defaults;
        });
      }
      for (const field of ['title', 'entry_note', 'exit_note', 'notes'])
        if (typeof normalized[field as keyof PlanDetails] !== 'string')
          throw Error('草稿的文字字段格式不正确。');
      if (
        typeof normalized.risk.note !== 'string' ||
        typeof normalized.risk.defense_source !== 'string' ||
        !['regular', 'extended', 'all'].includes(normalized.mode) ||
        !Array.isArray(normalized.references)
      )
        throw Error('草稿的风险说明或行情时段无效。');
      for (const field of ['entry_price', 'qty', 'budget', 'max_position_percent'] as const) {
        const number = normalized.risk[field];
        if (number !== null && (typeof number !== 'number' || !Number.isFinite(number) || number <= 0))
          throw Error('草稿的风险数值无效。');
      }
      if (normalized.risk.max_position_percent !== null && normalized.risk.max_position_percent > 100)
        throw Error('仓位上限不能超过 100%。');
      for (const number of Object.values(normalized.levels))
        if (number !== null && (typeof number !== 'number' || !Number.isFinite(number) || number <= 0))
          throw Error('草稿的关键价位无效。');
      if (normalized.levels.platform_high !== null && normalized.levels.platform_low !== null &&
          normalized.levels.platform_high < normalized.levels.platform_low)
        throw Error('前期平台上沿不能低于下沿。');
      if (
        input.stop != null &&
        (typeof input.stop !== 'number' || !Number.isFinite(input.stop) || input.stop <= 0)
      )
        throw Error('草稿的防守价无效。');
      patch({
        details: normalized,
        ...(Object.hasOwn(input, 'stop') ? { stop: input.stop } : {}),
        ...(typeof input.size === 'string' ? { size: input.size } : {}),
      });
      setNotice('已填入 Agent 草稿，可以继续修改后保存。');
    } catch (cause) {
      setError((cause as Error).message);
    }
  }
  function newPlanConditionForImport(item: PlanCondition): PlanCondition {
    if (
      !['reds', 'greens', 'above', 'below', 'bullish', 'bearish'].includes(item.signal) ||
      !Number.isFinite(item.threshold) ||
      !['main', 'upper', 'mid', 'lower'].includes(item.line) ||
      !['close', 'live'].includes(item.confirmation)
    )
      throw Error('草稿的指标条件格式不正确。');
    if (
      item.source === 'BBI' &&
      (!Array.isArray(item.params.periods) ||
        item.params.periods.some((value) => !Number.isInteger(value) || value <= 0))
    )
      throw Error('BBI 周期格式不正确。');
    const signals =
      item.source === 'SIXPULSE'
        ? ['reds', 'greens']
        : item.source === 'MACD'
          ? ['bullish', 'bearish']
          : ['above', 'below'];
    if (
      !signals.includes(item.signal) ||
      (item.source === 'SIXPULSE' &&
        (!Number.isInteger(item.threshold) || item.threshold < 1 || item.threshold > 6))
    )
      throw Error('草稿的指标与判断方式不匹配。');
    return { ...item, id: requestId() };
  }

  return (
    <form className="trade-plan-editor" onSubmit={save}>
      <fieldset disabled={busy || filling} className="plan-editor-fields">
        <div className="plan-basics">
          <label className="plan-title-field">
            计划名称
            <input
              aria-label="交易计划名称"
              maxLength={100}
              value={details.title}
              placeholder="例如：日线共振后的回踩机会"
              onChange={(e) => patchDetails({ title: e.target.value })}
            />
          </label>
          <label>
            标的
            <input
              aria-label="计划标的"
              required
              readOnly={!!plan}
              value={draft.symbol}
              onChange={(e) => patch({ symbol: e.target.value.toUpperCase() })}
            />
          </label>
          <label>
            计划周期
            <select
              aria-label="计划周期"
              value={draft.period}
              onChange={(e) => patch({ period: e.target.value as PlanPeriod })}
            >
              {Object.entries(periodNames).map(([key, title]) => (
                <option key={key} value={key}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>
            方向
            <select
              aria-label="计划方向"
              disabled={!!plan}
              value={draft.side}
              onChange={(e) => patch({ side: e.target.value as 'BUY' | 'SELL' })}
            >
              <option value="BUY">买入</option>
              <option value="SELL">卖出</option>
            </select>
          </label>
          <label>
            状态
            <select
              aria-label="计划状态"
              value={draft.status}
              onChange={(e) => patch({ status: e.target.value as Plan['status'] })}
            >
              {Object.entries(statusNames).map(([key, title]) => (
                <option key={key} value={key}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>后台跟踪
            <select aria-label="后台跟踪周期" value={details.tracking_period || ''}
              onChange={e=>patchDetails({tracking_period:(e.target.value || null) as PlanPeriod | null})}>
              <option value="">关闭</option>
              {Object.entries(periodNames).map(([key,title])=><option key={key} value={key}>{title}收盘</option>)}
            </select>
          </label>
          {market === 'US' && (
            <label>
              行情时段
              <select
                aria-label="计划行情时段"
                value={details.mode}
                onChange={(e) => patchDetails({ mode: e.target.value as PlanDetails['mode'] })}
              >
                <option value="regular">常规</option>
                <option value="extended">盘前、常规、盘后</option>
                <option value="all">全时段</option>
              </select>
            </label>
          )}
        </div>
        {details.tracking_period && <p className="plan-help">状态为「进行中」时，在{periodNames[details.tracking_period]}收盘后记录。日汇总复用跟踪记录。跟随防守价沿用所选来源周期。</p>}
        <div className={board ? "plan-editor-columns plan-board-layout" : "plan-editor-columns"}>
          <div className="plan-main-fields">
            <section className="plan-entry-panel" aria-label="入场条件">
              <div className="plan-entry-heading">
                <h3>入场条件</h3>
                <button type="button" className="plan-fill-button" onClick={()=>void fillForm()}
                  disabled={!canonical || data.loading} title={!canonical ? '请先填写标的' : '只补空项，核对后保存'}>
                  <WandSparkles size={16} aria-hidden="true"/>{filling ? '正在填表…' : '一键填表'}
                </button>
              </div>
              {filling && <div className="plan-fill-progress">
                <span role="status">正在等待填表结果</span><span>{elapsed} 秒</span>
                <progress aria-label="等待填表结果"/>
              </div>}
              {fillFailure && <div className="plan-fill-error" role="alert">{fillFailure}</div>}
              {market === 'CN' && <fieldset className="plan-entry-mode" aria-label="入场条件">
                <label>
                  <input type="radio" name="entry-strategy" checked={!board} onChange={()=>changeStrategy('indicator')}/>
                  <span><ChartNoAxesCombined aria-hidden="true" size={17}/>指标条件</span>
                </label>
                <label>
                  <input type="radio" name="entry-strategy" checked={board} onChange={()=>changeStrategy('limit_up')}/>
                  <span><Zap aria-hidden="true" size={17}/>打板（首封 / 回封）</span>
                </label>
              </fieldset>}
              <div className={board ? 'plan-board-notes' : 'plan-indicator-notes'}>
            {!board && <PlanConditionsEditor
              label="入场理由"
              group={details.entry}
              period={draft.period}
              indicators={indicators}
              estimates={estimates}
              onChange={(entry) => patchDetails({ entry })}
              onPrice={(price) => patchRisk({ entry_price: price })}
            />}
            <label className="plan-note-field">
              {board ? '首封 / 回封参与条件' : '入场理由补充'}
              <textarea
                aria-label={board ? '首封 / 回封参与条件' : '入场理由补充'}
                maxLength={5000}
                rows={3}
                placeholder={board ? "首封还是回封？记录封板时间、开板次数、板块跟随等要求。" : "写下你为什么想做这笔交易，也可以只写文字理由。"}
                value={details.entry_note}
                onChange={(e) => patchDetails({ entry_note: e.target.value })}
              />
            </label>
            {!board && <PlanConditionsEditor
              label="出场条件"
              group={details.exit}
              period={draft.period}
              exit
              indicators={indicators}
              estimates={estimates}
              onChange={(exit) => patchDetails({ exit })}
              onPrice={useDefense}
            />}
            <label className="plan-note-field">
              {board ? '炸板、放弃与退出条件' : '出场补充'}
              <textarea
                aria-label={board ? '炸板、放弃与退出条件' : '出场条件补充'}
                maxLength={5000}
                rows={2}
                placeholder={board ? "记录放弃排板、炸板后及次日的处理条件。" : "例如：先减仓一半，剩余部分跟随均线。"}
                value={details.exit_note}
                onChange={(e) => patchDetails({ exit_note: e.target.value })}
              />
            </label>
              </div>
            {canonical && <FillHistory key={market+canonical} market={market} symbol={canonical} revision={fillRevision}/>}
            </section>
            <section className="plan-section">
              <div className="plan-section-heading plan-levels-heading"><h3>关键价位与止盈</h3>
                {board && <button type="button" aria-label="刷新计划参考行情" title="刷新计划参考行情"
                  disabled={data.loading || !canonical} onClick={() => setRefresh(v=>v+1)}><RefreshCw size={15}/></button>}
                <label><input type="checkbox" checked={autoStructure}
                onChange={e => patchDetails({structure_mode: e.target.checked ? 'auto' : 'manual', levels:
                  !e.target.checked && !structure.length ? details.levels : levels})}/>自动识别前高、前低和平台</label></div>
              {board && data.loading && <p role="status" className="plan-help">正在读取参考行情…</p>}
              {board && Object.entries(data.issues).map(([key,message])=><p key={key} className="plan-data-issue">{periodNames[key as PlanPeriod]} · {message}</p>)}
              {autoStructure && <p className="plan-help">{periodNames[draft.period]} · 最近 60 根历史 K 线，排除末根。前高前低各需左右两根确认。平台取最近连续 12 根、振幅不超过 8%、上下沿各触及至少两次的区间。</p>}
              <div className="plan-risk-fields">
                {([
                  ['previous_high', '前高'], ['previous_low', '前低'],
                  ['platform_high', '前期平台上沿'], ['platform_low', '前期平台下沿'],
                  ['gap_up', '前期向上缺口'], ['gap_down', '前期向下缺口'],
                  ['take_profit', '止盈位'],
                ] as [keyof PlanLevels, string][]).map(([key, label]) => {
                  const point = autoStructure && structure.find(row => row.label === structureLabels[key as keyof typeof structureLabels]);
                  return <label key={key}>{label}
                  {point && <small>{displayTime(market, new Date(point.bar_time * 1000).toISOString())}</small>}
                  <input aria-label={label} type="number" min="0.00000001" step="any"
                    readOnly={autoStructure && key in structureLabels}
                    placeholder={autoStructure && key in structureLabels ? (data.loading ? '读取行情中' : '未识别') : undefined}
                    value={levels[key] ?? ''}
                    onChange={e => patchLevels({[key]: optionalNumber(e.target.value)})}/>
                </label>})}
              </div>
            </section>
            <section className="plan-section">
              <div className="plan-section-heading">
                <h3>风险与防守</h3>
                <small>{market === 'CN' ? '金额单位为人民币' : '金额单位为美元'}</small>
              </div>
              <div className="plan-risk-fields">
                <label>
                  入场参考价
                  <input
                    aria-label="入场参考价"
                    type="number"
                    min="0.00000001"
                    step="any"
                    value={details.risk.entry_price ?? ''}
                    onChange={(e) => patchRisk({ entry_price: optionalNumber(e.target.value) })}
                  />
                </label>
                <label>
                  防守价
                  <input
                    aria-label="计划防守价"
                    type="number"
                    min="0.00000001"
                    step="any"
                    value={stop == null ? '' : editingStop && !following ? stop : displayPlanPrice(stop)}
                    onBlur={()=>setEditingStop(false)}
                    readOnly={!!following}
                    onChange={(e) => {
                      setEditingStop(true);
                      patch({
                        stop: optionalNumber(e.target.value),
                        details: { ...details, risk: { ...details.risk, defense_source: '手动填写', defense_reference: null } },
                      });
                    }}
                  />
                </label>
                <label>
                  计划股数
                  <input
                    aria-label="计划股数"
                    type="number"
                    min="0.00000001"
                    step="any"
                    value={details.risk.qty ?? ''}
                    onChange={(e) => patchRisk({ qty: optionalNumber(e.target.value) })}
                  />
                </label>
                <label>
                  单笔风险预算
                  <input
                    aria-label="单笔风险预算"
                    type="number"
                    min="0.00000001"
                    step="any"
                    value={details.risk.budget ?? ''}
                    onChange={(e) => patchRisk({ budget: optionalNumber(e.target.value) })}
                  />
                </label>
                <label>
                  仓位上限 %
                  <input
                    aria-label="计划仓位上限"
                    type="number"
                    min="0.01"
                    max={100}
                    step="any"
                    value={details.risk.max_position_percent ?? ''}
                    onChange={(e) => patchRisk({ max_position_percent: optionalNumber(e.target.value) })}
                  />
                </label>
                <label>
                  仓位安排
                  <input
                    aria-label="计划仓位安排"
                    maxLength={2000}
                    value={draft.size}
                    placeholder="例如：先买一半，回踩后再补"
                    onChange={(e) => patch({ size: e.target.value })}
                  />
                </label>
              </div>
              <p className="plan-help">防守位来源 · {details.risk.defense_source}{following && <> · 刷新行情时重算
                <button type="button" onClick={() => patch({stop: stop ?? draft.stop, details: {...details,
                  risk: {...details.risk, defense_source: '固定价', defense_reference: null}}})}>改为固定价</button></>}</p>
              <div className={'plan-risk-summary' + (risk.overBudget ? ' over-budget' : '')}>
                <span>
                  每股价差 <b>{amount(risk.perShare)}</b>
                </span>
                <span>
                  价差比例 <b>{risk.percent === null ? '待定' : risk.percent.toFixed(2) + '%'}</b>
                </span>
                <span>
                  按计划股数估算亏损 <b>{amount(risk.loss)}</b>
                </span>
                {risk.overBudget && <strong>超过风险预算</strong>}
              </div>
              {stop !== null &&
                details.risk.entry_price !== null &&
                stop >= details.risk.entry_price && (
                  <p className="plan-help">当前防守价不低于入场参考价，请结合买卖方向核对风险安排。</p>
                )}
              <label className="plan-note-field">
                风险考虑
                <textarea
                  aria-label="计划风险考虑"
                  maxLength={5000}
                  rows={3}
                  placeholder="可以写跳空、财报、隔夜、流动性，以及触发防守后准备怎么处理。"
                  value={details.risk.note}
                  onChange={(e) => patchRisk({ note: e.target.value })}
                />
              </label>
            </section>
            <label className="plan-note-field">
              其他想法
              <textarea
                aria-label="计划其他想法"
                maxLength={5000}
                rows={3}
                placeholder="保留自己的判断、待确认事项或 Agent 的分析。"
                value={details.notes}
                onChange={(e) => patchDetails({ notes: e.target.value })}
              />
            </label>
            <details className="plan-agent">
              <summary>手动导入 Agent 草稿</summary>
              <p className="plan-help">可把任务复制到 OpenClaw、Codex 或 DeepSeek，再将返回的 JSON 填入草稿。</p>
              <button type="button" onClick={() => void copyForAgent()}>
                <Copy size={14} />
                生成并复制任务
              </button>
              {agentText && <textarea aria-label="给Agent的任务" readOnly rows={5} value={agentText} />}
              <textarea
                aria-label="Agent计划草稿"
                rows={4}
                placeholder="粘贴 Agent 返回的 JSON"
                value={agentInput}
                onChange={(e) => setAgentInput(e.target.value)}
              />
              <button type="button" disabled={!agentInput.trim()} onClick={importAgent}>
                填入 Agent 草稿
              </button>
            </details>
          </div>
          {!board && <section className="plan-reference-panel" aria-label="价位参考">
            <div className="plan-section-heading">
              <h3>价位参考</h3>
              <button
                type="button"
                aria-label="刷新计划参考行情"
                disabled={data.loading || !canonical}
                onClick={() => setRefresh((value) => value + 1)}
              >
                <RefreshCw size={14} />
              </button>
            </div>
            <label>
              参考周期
              <select
                aria-label="价位参考周期"
                value={referencePeriod}
                onChange={(e) => setReferencePeriod(e.target.value as PlanPeriod)}
              >
                {Object.entries(periodNames).map(([key, title]) => (
                  <option key={key} value={key}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
            <p className="plan-help">
              固定价保留选定数值。跟随价在打开编辑器或刷新时重算，保存修订时记录本次点位。
            </p>
            {data.loading && (
              <p role="status" className="plan-help">
                正在读取参考行情…
              </p>
            )}
            {Object.entries(data.issues).map(([key, message]) => (
              <p key={key} className="plan-data-issue">
                {periodNames[key as PlanPeriod]} · {message}
              </p>
            ))}
            {references.map((row) => (
              <div className="plan-reference-row" key={row.label}>
                <div>
                  <span>{row.label}</span>
                  <strong>{displayPlanPrice(row.price)}</strong>
                </div>
                <button
                  type="button"
                  onClick={() => useDefense(row.price, periodNames[row.period] + ' · ' + row.label)}
                >
                  设为固定防守位
                </button>
                <button type="button" onClick={() => useDefense(row.price, periodNames[row.period] + ' · ' + row.label,
                  {period: row.period, label: row.label, condition: row.condition})}>跟随此价位</button>
              </div>
            ))}
            {!board && !references.length && !data.loading && (
              <p className="plan-help">暂时没有可计算的参考价位，仍可手动填写计划。</p>
            )}
            {references[0] && (
              <p className="plan-help">
                行情 K 线时间
                <br />
                {displayTime(market, new Date(references[0].bar_time * 1000).toISOString())}
              </p>
            )}
          </section>}
        </div>
      </fieldset>
      {notice && (
        <p role="status" className="plan-notice">
          <Check size={14} />
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="plan-error">
          {error}
        </p>
      )}
      <div className="plan-save-bar">
        <span>{dirty ? '本地草稿 · 保存后同步到 NAS' : '可先保存草稿，之后继续完善'}</span>
        <button type="button" disabled={busy} onClick={onCancel}>
          关闭
        </button>
        <button type="submit" className="plan-primary" disabled={busy || filling || ((autoStructure || !!following) && data.loading)}>
          <Save size={15} />
          {busy ? '保存中…' : '保存计划'}
        </button>
      </div>
    </form>
  );
}
