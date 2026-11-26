import assert from 'node:assert/strict';
import {loadTS} from './test-load-ts.mjs';
const {computeSixPulse, sixPulseRows} = await loadTS('sixpulse');
const {prepareSixPulsePrice, sixPulsePriceLevels} = await loadTS('sixpulseLevels');
const {advancedParams} = await loadTS('advancedCatalog');

const makeBars = (size, flat = false) => Array.from({length: size}, (_, i) => {
  const close = flat ? 6 : 6 + Math.sin(i * .37) * .7 + Math.cos(i * .11) * .2;
  return {time: i + 1, open: close - .03, close, high: close + .08, low: close - .09,
    volume: 100, session: 'regular', trade_date: '2026-11-20', session_date: 'regular'};
});
const configs = [{}, {fast: 2, slow: 6, signal: 3, kdjPeriod: 3, lwrPeriod: 4, rsiFast: 2, rsiSlow: 5},
  {signal: 1, smoothK: 1, smoothD: 1, lwrSmooth1: 1, lwrSmooth2: 1},
  {bbi1: 1, bbi2: 2, bbi3: 3, bbi4: 4, kdjPeriod: 1, lwrPeriod: 1}];
let checks = 0;
for (const input of configs) {
  const params = advancedParams('SIXPULSE_SIGNAL', input);
  for (const bars of [makeBars(90), makeBars(45, true), makeBars(9), makeBars(2)]) {
    const prepared = prepareSixPulsePrice(bars, params);
    const original = structuredClone(bars);
    const atPrice = price => {
      const last = bars.at(-1);
      const data = [...bars.slice(0, -1), {...last, close: price, high: Math.max(last.high, price), low: Math.min(last.low, price)}];
      const result = computeSixPulse(data, params);
      return Object.fromEntries(sixPulseRows.map(name => [name, result[name].at(-1)]));
    };
    for (let index = 100; index <= 1200; index += 7) {
      const price = index / 100;
      assert.deepEqual(prepared.evaluate(price).votes, atPrice(price), `latest-bar parity at ${price}`);
      checks++;
    }
    const levels = sixPulsePriceLevels(bars, params, .01);
    for (const level of levels) {
      const votes = atPrice(level.price);
      const neighbors = [level.price - .01, level.price + .01].filter(price => price > 0).map(atPrice);
      for (const name of level.names) {
        assert.equal(votes[name], Number(level.red), `${name} at ${level.price}`);
        assert.ok(neighbors.some(other => other[name] === Number(!level.red)), `${name} boundary at ${level.price}`);
      }
      for (const label of level.emphasis) {
        const target = label === '六红' ? 1 : 0, required = label === '六红' ? 6 : 3;
        const count = sample => sixPulseRows.every(name => sample[name] !== null) ? sixPulseRows.filter(name => sample[name] === target).length : null;
        assert.ok(count(votes) >= required, `${label} at ${level.price}`);
        assert.ok(neighbors.some(other => count(other) !== null && count(other) < required), `${label} boundary`);
      }
    }
    if (bars.length >= 24) {
      const current = atPrice(bars.at(-1).close);
      // Brute-force the nearby price grid independently of the root solver.
      for (const name of sixPulseRows) {
        if (current[name] === null) continue;
        let expected = null;
        for (let index = 200; index <= 1000; index++) {
          const price = index / 100;
          if (atPrice(price)[name] === current[name]) continue;
          if (expected === null || Math.abs(price - bars.at(-1).close) < Math.abs(expected - bars.at(-1).close)) expected = price;
        }
        const found = levels.filter(level => level.names.includes(name) && level.red !== Boolean(current[name]))
          .sort((a,b) => Math.abs(a.price-bars.at(-1).close)-Math.abs(b.price-bars.at(-1).close))[0];
        if (expected !== null) assert.equal(found?.price, expected, `${name} nearest reverse price`);
      }
    }
    assert.deepEqual(bars, original, 'trial prices must preserve the input candles');
  }
}
assert.deepEqual(sixPulsePriceLevels([], advancedParams('SIXPULSE_SIGNAL', {}), .01), []);
assert.deepEqual(sixPulsePriceLevels(makeBars(40), advancedParams('SIXPULSE_SIGNAL', {}), 0), []);
console.log(`SixPulse levels passed ${checks} full-formula comparisons, price-grid boundaries, warmup, flat prices and custom smoothing`);
