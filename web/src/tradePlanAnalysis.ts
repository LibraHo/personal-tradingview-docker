import { compute, type Bar, type Indicator } from './indicators';
import { advancedParams } from './advancedCatalog';
import { prepareSixPulsePrice, sixPulsePriceLevels } from './sixpulseLevels';
import { sixPulseRows } from './sixpulse';
import { periodNames, requestId, type PlanPeriod } from './tradeBookClient';

export const planSources = {
  SIXPULSE: '六脉共振',
  BOLL: '布林带',
  SMA: 'MA 均线',
  EMA: 'EMA 均线',
  BBI: 'BBI',
  VWAP: 'VWAP',
  MACD: 'MACD',
  RSI: 'RSI',
  PRICE: '指定价格',
};
export type PlanSource = keyof typeof planSources;
export type PlanCondition = {
  id: string;
  source: PlanSource;
  period: PlanPeriod;
  signal: 'reds' | 'greens' | 'above' | 'below' | 'bullish' | 'bearish';
  threshold: number;
  line: 'main' | 'upper' | 'mid' | 'lower';
  params: Record<string, unknown>;
  confirmation: 'close' | 'live';
};
export type PlanConditions = { join: 'all' | 'any'; items: PlanCondition[] };
export type PlanRisk = {
  entry_price: number | null;
  qty: number | null;
  budget: number | null;
  max_position_percent: number | null;
  defense_source: string;
  defense_reference?: { period: PlanPeriod; label: string; condition?: PlanCondition | null } | null;
  note: string;
};
export type PlanReference = { label: string; price: number; period: PlanPeriod; bar_time: number };
export type PlanLevels = {
  previous_high: number | null; previous_low: number | null;
  platform_high: number | null; platform_low: number | null;
  gap_up: number | null; gap_down: number | null; take_profit: number | null;
};
export const emptyPlanLevels: PlanLevels = {
  previous_high: null, previous_low: null, platform_high: null, platform_low: null,
  gap_up: null, gap_down: null, take_profit: null,
};
export type PlanDetails = {
  version: 1;
  strategy?: 'indicator' | 'limit_up';
  tracking_period?: PlanPeriod | null;
  structure_mode?: 'auto' | 'manual';
  title: string;
  entry: PlanConditions;
  exit: PlanConditions;
  entry_note: string;
  exit_note: string;
  notes: string;
  risk: PlanRisk;
  levels?: PlanLevels;
  mode: 'regular' | 'extended' | 'all';
  references: PlanReference[];
  author: 'manual' | 'agent';
};
export type PlanEstimate = {
  price: number | null;
  value: number | null;
  met: boolean | null;
  bar_time: number;
  note: string;
};

export function newPlanCondition(
  source: PlanSource,
  period: PlanPeriod,
  exit = false,
  indicators: Indicator[] = [],
): PlanCondition {
  const inherited = indicators.find(
    (item) => item.name === source || (source === 'SIXPULSE' && item.name === 'SIXPULSE_SIGNAL'),
  );
  let original: Record<string, any> = {};
  try {
    original = JSON.parse(inherited?.params || '{}');
  } catch {
    /* Defaults also support a partially edited chart indicator. */
  }
  if (!original || typeof original !== 'object' || Array.isArray(original)) original = {};
  const params: Record<string, unknown> = {};
  if (source === 'SIXPULSE') {
    try {
      Object.assign(params, advancedParams('SIXPULSE', original));
    } catch {
      Object.assign(params, advancedParams('SIXPULSE', {}));
    }
  }
  if (['SMA', 'EMA'].includes(source))
    params.period = original.period ?? (original.periods?.includes(20) ? 20 : original.periods?.[0]) ?? 20;
  if (source === 'BOLL')
    Object.assign(params, { period: original.period ?? 20, stddev: original.stddev ?? 2 });
  if (source === 'BBI') params.periods = original.periods ?? [3, 6, 12, 24];
  if (source === 'VWAP') params.reset = original.reset ?? 'session';
  if (source === 'RSI') params.period = original.period ?? 14;
  if (source === 'MACD')
    Object.assign(params, {
      fast: original.fast ?? 12,
      slow: original.slow ?? 26,
      signal: original.signal ?? 9,
    });
  return {
    id: requestId(),
    source,
    period,
    signal:
      source === 'SIXPULSE'
        ? exit
          ? 'greens'
          : 'reds'
        : source === 'MACD'
          ? exit
            ? 'bearish'
            : 'bullish'
          : exit
            ? 'below'
            : 'above',
    threshold: source === 'SIXPULSE' ? (exit ? 3 : 6) : source === 'RSI' ? 50 : 0,
    line: source === 'BOLL' ? 'mid' : 'main',
    params,
    confirmation: 'close',
  };
}

export function newPlanDetails(
  period: PlanPeriod,
  mode: PlanDetails['mode'] = 'regular',
  indicators: Indicator[] = [],
): PlanDetails {
  return {
    version: 1,
    strategy: 'indicator',
    structure_mode: 'auto',
    title: '',
    entry: { join: 'all', items: [newPlanCondition('SIXPULSE', period, false, indicators)] },
    exit: { join: 'any', items: [newPlanCondition('SIXPULSE', period, true, indicators)] },
    entry_note: '',
    exit_note: '',
    notes: '',
    mode,
    references: [],
    levels: {...emptyPlanLevels},
    author: 'manual',
    risk: {
      entry_price: null,
      qty: null,
      budget: null,
      max_position_percent: null,
      defense_source: '手动填写',
      note: '',
    },
  };
}

export function conditionLabel(condition: PlanCondition): string {
  const prefix = periodNames[condition.period] + ' · ';
  if (condition.source === 'SIXPULSE')
    return prefix + `六脉至少 ${condition.threshold} ${condition.signal === 'reds' ? '红' : '绿'}`;
  if (condition.source === 'MACD')
    return prefix + `MACD ${condition.signal === 'bullish' ? 'DIF ≥ DEA' : 'DIF ≤ DEA'}`;
  if (condition.source === 'RSI')
    return (
      prefix +
      `RSI${condition.params.period || 14} ${condition.signal === 'above' ? '≥' : '≤'} ${condition.threshold}`
    );
  if (condition.source === 'PRICE')
    return prefix + `价格 ${condition.signal === 'above' ? '≥' : '≤'} ${condition.threshold}`;
  const band =
    condition.source === 'BOLL'
      ? { upper: '上轨', mid: '中轨', lower: '下轨', main: '' }[condition.line]
      : '';
  const period = ['SMA', 'EMA'].includes(condition.source) ? String(condition.params.period || 20) : '';
  return (
    prefix +
    `${condition.signal === 'above' ? '站上' : '跌破'} ${planSources[condition.source]}${period}${band}`
  );
}

function latestValue(values: Record<string, (number | null)[]>, line: string): number | null {
  const value = values[line]?.at(-1);
  return value != null && Number.isFinite(value) ? value : null;
}

export function estimatePlanCondition(bars: Bar[], condition: PlanCondition, tick = 0.01): PlanEstimate {
  const last = bars.at(-1);
  const empty = { price: null, value: null, met: null, bar_time: last?.time ?? 0, note: '历史数据不足' };
  if (!last) return empty;
  if (condition.source === 'SIXPULSE') {
    const params = advancedParams('SIXPULSE', condition.params)!;
    const prepared = prepareSixPulsePrice(bars, params);
    if (!prepared) return empty;
    const red = condition.signal === 'reds',
      votes = prepared.evaluate(last.close).votes;
    if (sixPulseRows.some((name) => votes[name] === null)) return empty;
    const value = sixPulseRows.filter((name) => votes[name] === Number(red)).length;
    const levels = sixPulsePriceLevels(bars, params, tick, [[red, condition.threshold, '条件']]);
    return {
      price: levels.find((level) => level.emphasis.includes('条件'))?.price ?? null,
      value,
      met: value >= condition.threshold,
      bar_time: last.time,
      note: '当前 K 线转色试算',
    };
  }
  const values =
    condition.source === 'PRICE' ? {} : compute(bars, condition.source, JSON.stringify(condition.params));
  const measure = (price: number): number | null => {
    if (condition.source === 'PRICE') return price - condition.threshold;
    const trial =
      price === last.close
        ? values
        : compute(
            [
              ...bars.slice(0, -1),
              { ...last, close: price, high: Math.max(last.high, price), low: Math.min(last.low, price) },
            ],
            condition.source,
            JSON.stringify(condition.params),
          );
    const value = latestValue(trial, condition.source === 'MACD' ? 'macd' : condition.line);
    if (value === null) return null;
    if (condition.source === 'MACD') {
      const signal = latestValue(trial, 'signal');
      return signal === null ? null : value - signal;
    }
    return condition.source === 'RSI' ? value - condition.threshold : price - value;
  };
  const current = measure(last.close);
  if (current === null) return empty;
  const above = condition.signal === 'above' || condition.signal === 'bullish';
  const matches = (value: number) => (above ? value >= 0 : value <= 0);
  let low = tick,
    high = Math.max(last.close * 2, last.high * 2, tick * 2);
  let left = measure(low),
    right = measure(high);
  if (left === null || right === null) return empty;
  for (let i = 0; i < 8 && Math.sign(left) === Math.sign(right); i++) {
    high *= 2;
    right = measure(high);
    if (right === null) break;
  }
  let price: number | null = null;
  if (right !== null && left !== right && Math.sign(left) !== Math.sign(right)) {
    for (let i = 0; i < 64 && high - low > tick / 1000; i++) {
      const middle = (low + high) / 2,
        value = measure(middle);
      if (value === null) break;
      if (Math.sign(value) === Math.sign(left)) {
        low = middle;
        left = value;
      } else high = middle;
    }
    const index = Math.floor((low + high) / 2 / tick);
    const candidates = [index - 1, index, index + 1, index + 2]
      .filter((i) => i > 0)
      .map((i) => Number((i * tick).toPrecision(14)));
    price =
      candidates.find((candidate) => {
        const value = measure(candidate);
        return (
          value !== null &&
          matches(value) &&
          [-tick, tick].some((offset) => {
            const adjacent = Number((candidate + offset).toPrecision(14)),
              other = adjacent > 0 ? measure(adjacent) : null;
            return other !== null && !matches(other);
          })
        );
      }) ?? null;
  }
  const value =
    condition.source === 'PRICE'
      ? last.close
      : latestValue(values, condition.source === 'MACD' ? 'macd' : condition.line);
  return {
    price,
    value,
    met: matches(current),
    bar_time: last.time,
    note: price === null ? '当前参数下无独立触发价' : '当前 K 线触发试算',
  };
}

// Up to eight decimal places match the editor's supported price precision.
export const planPrice = (value: number) => Number(value.toFixed(8));

// Keep sub-tick values distinguishable while shortening calculated prices on screen.
export function displayPlanPrice(value: number | null | undefined): string {
  if (value == null) return '—';
  const magnitude = Math.abs(value);
  const digits = magnitude > 0 && magnitude < 0.0001 ? Math.min(8, -Math.floor(Math.log10(magnitude)) + 1) : 4;
  const text = value.toFixed(digits).replace(/\.?0+$/, '');
  return text === '-0' ? '0' : text;
}

export const structureLabels = {
  previous_high: '前高', previous_low: '前低',
  platform_high: '震荡平台上沿', platform_low: '震荡平台下沿',
};

export function structureReferences(bars: Bar[], period: PlanPeriod): PlanReference[] {
  // Exclude the last (possibly forming) candle. Each pivot needs two later candles.
  const history = bars.slice(-61, -1);
  const result: PlanReference[] = [];
  for (const field of ['high', 'low'] as const) {
    for (let i = history.length - 3; i >= 2; i--) {
      const bar = history[i];
      const neighbors = [history[i-2], history[i-1], history[i+1], history[i+2]];
      if (neighbors.every(other => field === 'high' ? other.high < bar.high : other.low > bar.low)) {
        result.push({ label: field === 'high' ? structureLabels.previous_high : structureLabels.previous_low,
          price: planPrice(bar[field]), period, bar_time: bar.time });
        break;
      }
    }
  }
  // Most recent 12-bar shelf with at least two separate visits to each edge.
  for (let end = history.length; end >= 12; end--) {
    const window = history.slice(end - 12, end);
    const upper = Math.max(...window.map(b => b.high));
    const lower = Math.min(...window.map(b => b.low));
    const width = upper - lower;
    if (lower <= 0 || width <= 0 || width / lower > 0.08) continue;
    const visits = (touches: boolean[]) => touches.filter((hit, i) => hit && !touches[i-1]).length;
    if (visits(window.map(b => b.high >= upper - width * 0.2)) < 2 ||
        visits(window.map(b => b.low <= lower + width * 0.2)) < 2) continue;
    for (const [label, price] of [[structureLabels.platform_high, upper], [structureLabels.platform_low, lower]] as const)
      result.push({label, price: planPrice(price), period, bar_time: window[11].time});
    break;
  }
  return result;
}

export function planReferencePrices(
  bars: Bar[],
  period: PlanPeriod,
  entry: number | null,
  indicators: Indicator[] = [],
): (PlanReference & { condition?: PlanCondition })[] {
  const last = bars.at(-1);
  if (!last) return [];
  const rows: (PlanReference & {condition?: PlanCondition})[] = [];
  const add = (label: string, price: number | null, condition?: PlanCondition) => {
    if (price !== null && Number.isFinite(price) && price > 0)
      rows.push({ label, price: planPrice(price), period, bar_time: last.time, ...(condition && {condition}) });
  };
  for (const [red, required, label] of [
    [true, 6, '六脉六红 · 试算价'],
    [false, 3, '六脉三绿 · 试算价'],
    [false, 6, '六脉六绿 · 试算价'],
  ] as const) {
    const condition = newPlanCondition('SIXPULSE', period, !red, indicators);
    condition.threshold = required;
    add(label, estimatePlanCondition(bars, condition).price, condition);
  }
  const boll = newPlanCondition('BOLL', period, false, indicators);
  const band = compute(bars, 'BOLL', JSON.stringify(boll.params));
  for (const [line, label] of [['upper', '布林上轨'], ['mid', '布林中轨'], ['lower', '布林下轨']] as const)
    add(label + ' · 当前线位', latestValue(band, line), {...boll, line});
  for (const source of ['SMA', 'EMA', 'BBI', 'VWAP'] as const) {
    const condition = newPlanCondition(source, period, false, indicators);
    const label = planSources[source] + (['SMA', 'EMA'].includes(source) ? condition.params.period : '');
    add(label + ' · 当前线位', latestValue(compute(bars, source, JSON.stringify(condition.params)), 'main'), condition);
  }
  if (bars.length >= 21) add('前 20 根低点', Math.min(...bars.slice(-21, -1).map((bar) => bar.low)));
  if (bars.length >= 14) {
    const atr = latestValue(compute(bars, 'ATR', '{"period":14}'), 'main');
    if (atr !== null) add('入场参考 − 2×ATR14', (entry ?? last.close) - 2 * atr);
  }
  return rows;
}

export function followedDefense(bars: Bar[], rule: NonNullable<PlanRisk['defense_reference']>, entry: number | null) {
  if (!bars.length) return null;
  const c = rule.condition;
  if (c) {
    const value = c.source === 'SIXPULSE' ? estimatePlanCondition(bars, c).price :
      latestValue(compute(bars, c.source, JSON.stringify(c.params)), c.line);
    return value === null ? null : planPrice(value);
  }
  return planReferencePrices(bars, rule.period, entry).find(row => row.label === rule.label)?.price ?? null;
}

export function planRiskValues(
  entry: number | null,
  defense: number | null,
  qty: number | null,
  budget: number | null,
) {
  const perShare = entry !== null && defense !== null && entry > defense ? entry - defense : null;
  const loss = perShare !== null && qty !== null ? perShare * qty : null;
  return {
    perShare,
    loss,
    percent: perShare !== null && entry !== null ? (100 * perShare) / entry : null,
    overBudget: loss !== null && budget !== null && loss > budget,
  };
}
