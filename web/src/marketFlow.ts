export type Tick = {
 sequence: string;
 time: string;
 price: number;
 volume: number;
 direction: string;
};
type Level = {price: number; buy: number; sell: number; neutral: number};
type Bar = {time: string; delta: number; cvd: number; levels: Level[]};
export type Flow = {start: string; last: Tick; cvd: number; bars: Bar[]; gap: boolean};

export function mergeFlow(previous: Flow|null, snapshot: Tick[]): Flow|null {
 const ticks = snapshot.filter(tick => /^\d+$/.test(tick.sequence) &&
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(tick.time))
  .sort((a,b) => a.time.slice(0,10).localeCompare(b.time.slice(0,10)) ||
   (BigInt(a.sequence) < BigInt(b.sequence) ? -1 : BigInt(a.sequence) > BigInt(b.sequence) ? 1 : 0));
 if (!ticks.length) return previous;
 const date = ticks[ticks.length-1].time.slice(0,10);
 if (previous && date < previous.last.time.slice(0,10)) return previous;
 const current = ticks.filter(t => t.time.startsWith(date));
 const sameDay = previous?.last.time.startsWith(date) ? previous : null;
 const lastSequence = sameDay ? BigInt(sameDay.last.sequence) : -1n;
 const fresh = current.filter(t => BigInt(t.sequence) > lastSequence);
 if (!fresh.length) return previous;
 const gap = !!sameDay && !current.some(t => t.sequence === sameDay.last.sequence);
 const base = gap ? null : sameDay;
 let cvd = base?.cvd ?? 0;
 let last = base?.last;
 const bars = base?.bars.slice() ?? [];
 const changed = new Map<string, {bar: Bar; prices: Map<number, Level>}>();
 for (const tick of fresh) {
  if (last?.sequence === tick.sequence) continue;
  const time = tick.time.slice(0,16);
  let entry = changed.get(time);
  if (!entry) {
   const index = bars.findIndex(bar => bar.time === time);
   const existing = bars[index];
   const bar = existing ? {...existing, levels: existing.levels.map(level => ({...level}))}
    : {time, delta: 0, cvd, levels: []};
   entry = {bar, prices: new Map(bar.levels.map(level => [level.price,level]))};
   changed.set(time, entry);
   if (index < 0) bars.push(bar);
   else bars[index] = bar;
  }
  const {bar, prices} = entry;
  let level = prices.get(tick.price);
  if (!level) {
   level = {price: tick.price, buy: 0, sell: 0, neutral: 0};
   prices.set(tick.price, level);
   bar.levels.push(level);
  }
  const side = tick.direction === 'BUY' ? 'buy' : tick.direction === 'SELL' ? 'sell' : 'neutral';
  const delta = side === 'buy' ? tick.volume : side === 'sell' ? -tick.volume : 0;
  level[side] += tick.volume;
  bar.delta += delta;
  cvd += delta;
  last = tick;
 }
 let running = cvd - bars.reduce((sum, bar) => sum + bar.delta, 0);
 const ordered = bars.sort((a,b) => a.time.localeCompare(b.time)).map(bar => {
  running += bar.delta;
  return {...bar, cvd: running};
 });
 return {start: base?.start ?? fresh[0].time, last: last!, cvd, bars: ordered.slice(-390), gap: gap || !!base?.gap};
}
