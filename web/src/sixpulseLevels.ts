import type {Bar} from './indicators';
import {computeSixPulse, sixPulseRows, smooth} from './sixpulse';

type Value = number | null;
type Row = typeof sixPulseRows[number];
export type SixPulsePriceLevel = {
  price: number;
  red: boolean;
  names: string[];
  emphasis: string[];
};

function latest(values: Value[]): Value {
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] !== null) return values[i];
  }
  return null;
}

const next = (previous: Value, value: Value, period: number, exponential = false) =>
  smooth([previous, value], period, exponential)[1];
const divide = (numerator: Value, denominator: Value): Value =>
  numerator === null || denominator === null || denominator === 0 ? null : 100 * numerator / denominator;

/** Freeze completed bars. A trial close can extend, but cannot erase, today's high/low. */
export function prepareSixPulsePrice(bars: Bar[], p: Record<string, number>) {
  if (bars.length < 2) return null;
  const current = bars[bars.length - 1];
  const history = bars.slice(0, -1);
  const close = history.map(bar => bar.close);
  const previousClose = close[close.length - 1];
  const previous = computeSixPulse(history, p);
  const fast = latest(smooth(close, p.fast, true));
  const slow = latest(smooth(close, p.slow, true));
  const change = close.map((value, i) => i === 0 ? null : value - close[i - 1]);
  const up = change.map(value => value === null ? null : Math.max(value, 0));
  const absolute = change.map(value => value === null ? null : Math.abs(value));
  const rsiState = [p.rsiFast, p.rsiSlow].map(period => ({
    period, up: latest(smooth(up, period)), absolute: latest(smooth(absolute, period)),
  }));
  const momentumState = [[p.mtmFast, p.mtmFastSmooth], [p.mtmSlow, p.mtmSlowSmooth]].map(([period, second]) => {
    const signed = smooth(change, period, true);
    const magnitude = smooth(absolute, period, true);
    return {period, second, signed: latest(signed), magnitude: latest(magnitude),
      signedSecond: latest(smooth(signed, second, true)), magnitudeSecond: latest(smooth(magnitude, second, true))};
  });
  const bounds = (period: number) => {
    if (bars.length < period) return null;
    const window = bars.slice(-period);
    return {high: Math.max(...window.map(bar => bar.high)), low: Math.min(...window.map(bar => bar.low))};
  };
  const kdjBounds = bounds(p.kdjPeriod);
  const lwrBounds = bounds(p.lwrPeriod);
  const means = [p.bbi1, p.bbi2, p.bbi3, p.bbi4].map(period => ({
    period,
    total: close.reduce((total, value, i) => i >= period ? total + value - close[i - period] : total + value, 0),
    expired: close.length >= period ? close[close.length - period] : 0,
  }));
  const breakpoints = [...new Set([0, previousClose, current.low, current.high,
    ...[kdjBounds, lwrBounds].flatMap(value => value ? [value.low, value.high] : []),
  ])].filter(Number.isFinite).sort((a, b) => a - b);

  const evaluate = (price: number) => {
    const diff = next(fast, price, p.fast, true)! - next(slow, price, p.slow, true)!;
    const dea = next(latest(previous.DEA), diff, p.signal, true)!;
    const stochastic = (range: ReturnType<typeof bounds>, negative = false) => {
      if (!range) return {value: null, width: 0};
      const high = Math.max(range.high, price), low = Math.min(range.low, price);
      return {value: divide(negative ? price - high : price - low, high - low), width: high - low};
    };
    const rawK = stochastic(kdjBounds);
    const k = next(latest(previous.K), rawK.value, p.smoothK);
    const d = next(latest(previous.D), k, p.smoothD);
    const delta = price - previousClose;
    const rsi = rsiState.map(state => ({
      numerator: next(state.up, Math.max(delta, 0), state.period)!,
      denominator: next(state.absolute, Math.abs(delta), state.period)!,
    }));
    const rawLwr = stochastic(lwrBounds, true);
    const lwr1 = next(latest(previous.LWR1), rawLwr.value, p.lwrSmooth1);
    const lwr2 = next(latest(previous.LWR2), lwr1, p.lwrSmooth2);
    const bbi = bars.length < Math.max(p.bbi1, p.bbi2, p.bbi3, p.bbi4) ? null :
      means.reduce((sum, mean) => sum + (mean.total + price - mean.expired) / mean.period, 0) / 4;
    const momentum = momentumState.map(state => ({
      numerator: next(state.signedSecond, next(state.signed, delta, state.period, true), state.second, true)!,
      denominator: next(state.magnitudeSecond, next(state.magnitude, Math.abs(delta), state.period, true), state.second, true)!,
    }));
    const pairs: [Value, Value][] = [[diff, dea], [k, d], rsi.map(v => divide(v.numerator, v.denominator)) as [Value, Value],
      [lwr1, lwr2], [price, bbi], momentum.map(v => divide(v.numerator, v.denominator)) as [Value, Value]];
    const votes = Object.fromEntries(sixPulseRows.map((name, i) => {
      const [a, b] = pairs[i];
      return [name, a === null || b === null ? null : Number(a > b)];
    })) as Record<Row, Value>;
    // Clearing the positive denominators leaves affine expressions within each
    // high/low/previous-close interval, including RSI and double-smoothed MTM.
    const cross = (values: {numerator: number; denominator: number}[]) =>
      values[0].numerator * values[1].denominator - values[1].numerator * values[0].denominator;
    const margins: Record<Row, Value> = {MACD: diff - dea, KDJ: k === null || d === null ? null : (k - d) * rawK.width,
      RSI: votes.RSI === null ? null : cross(rsi), LWR: lwr1 === null || lwr2 === null ? null : (lwr1 - lwr2) * rawLwr.width,
      BBI: bbi === null ? null : price - bbi, MTM: votes.MTM === null ? null : cross(momentum)};
    return {votes, margins};
  };
  return {evaluate, breakpoints};
}

/** Nearest opposite-colour price for each row, plus the six-red/three-green boundaries. */
export function sixPulsePriceLevels(bars: Bar[], p: Record<string, number>, tick: number,
  targets: readonly (readonly [boolean, number, string])[] = [[true, 6, '六红'], [false, 3, '三绿']]): SixPulsePriceLevel[] {
  const prepared = prepareSixPulsePrice(bars, p);
  if (!prepared || !Number.isFinite(tick) || tick <= 0) return [];
  const {evaluate, breakpoints} = prepared;
  const current = bars[bars.length - 1].close;
  const currentVotes = evaluate(current).votes;
  const candidates = new Set<number>();
  const add = (price: number) => {
    const index = Math.floor(price / tick);
    if (!Number.isSafeInteger(index)) return;
    for (let offset = -2; offset <= 2; offset++) if (index + offset > 0) candidates.add(index + offset);
  };
  for (const point of breakpoints) add(point);
  for (let i = 0; i < breakpoints.length; i++) {
    const left = breakpoints[i], right = breakpoints[i + 1] ?? left + Math.max(1, current);
    const x = left + (right - left) / 4, y = left + (right - left) * 3 / 4;
    const a = evaluate(x).margins, b = evaluate(y).margins;
    for (const name of sixPulseRows) {
      if (a[name] === null || b[name] === null) continue;
      const difference = b[name]! - a[name]!;
      if (Math.abs(difference) <= 1e-12 * Math.max(Math.abs(a[name]!), Math.abs(b[name]!), 1e-15)) continue;
      const root = x - a[name]! * (y - x) / difference;
      if (root >= left - tick && (i === breakpoints.length - 1 || root <= right + tick)) add(root);
    }
  }
  const priceAt = (index: number) => Number((index * tick).toPrecision(14));
  const samples = new Map<number, Record<Row, Value>>();
  const sample = (index: number) => {
    let votes = samples.get(index);
    if (!votes) {votes = evaluate(priceAt(index)).votes; samples.set(index, votes);}
    return votes;
  };
  const levels: SixPulsePriceLevel[] = [];
  const append = (index: number, red: boolean, name: string, emphasis = false) => {
    const price = priceAt(index);
    let level = levels.find(item => item.price === price && item.red === red);
    if (!level) {level = {price, red, names: [], emphasis: []}; levels.push(level);}
    const labels = emphasis ? level.emphasis : level.names;
    if (!labels.includes(name)) labels.push(name);
  };
  const indices = [...candidates];
  const nearest = (matches: number[]) => matches.sort((a, b) => Math.abs(priceAt(a) - current) - Math.abs(priceAt(b) - current))[0];
  for (const name of sixPulseRows) {
    if (currentVotes[name] === null) continue;
    const target = 1 - currentVotes[name]!;
    const matches = indices.filter(index => sample(index)[name] === target &&
      [index - 1, index + 1].some(neighbor => neighbor > 0 && sample(neighbor)[name] === currentVotes[name]));
    const index = nearest(matches);
    if (index !== undefined) append(index, target === 1, name);
  }
  const count = (votes: Record<Row, Value>, target: number) =>
    sixPulseRows.every(name => votes[name] !== null) ? sixPulseRows.filter(name => votes[name] === target).length : null;
  for (const [red, required, label] of targets) {
    const matches = indices.filter(index => {
      const total = count(sample(index), Number(red));
      return total !== null && total >= required && [index - 1, index + 1].some(neighbor => {
        if (neighbor <= 0) return false;
        const adjacent = count(sample(neighbor), Number(red));
        return adjacent !== null && adjacent < required;
      });
    });
    const index = nearest(matches);
    if (index !== undefined) {
      append(index, red, label, true);
      const votes = sample(index);
      for (const neighbor of [index - 1, index + 1]) {
        if (neighbor <= 0) continue;
        const adjacent = sample(neighbor);
        const total = count(adjacent, Number(red));
        if (total !== null && total < required) {
          for (const name of sixPulseRows) if (votes[name] !== adjacent[name]) append(index, red, name);
        }
      }
    }
  }
  return levels.sort((a, b) => b.price - a.price);
}
