import type {ISeriesPrimitive, Time, SeriesAttachedParameter, UTCTimestamp} from 'lightweight-charts';
import type {Bar} from './indicators';
import {advancedParams} from './advancedCatalog';
import {selectedColor} from './histogramColors';
import {sixPulsePriceLevels} from './sixpulseLevels';

export function sixPulseLevelsOverlay(bars: Bar[], input: Record<string, unknown>, tick: number,
  colors?: Record<string, string>): ISeriesPrimitive<Time> {
  let attached: SeriesAttachedParameter<Time> | null = null;
  const params = advancedParams('SIXPULSE_SIGNAL', input)!;
  const levels = sixPulsePriceLevels(bars, params, tick);
  const current = bars[bars.length - 1];
  const digits = Math.max(2, Math.round(-Math.log10(tick)));
  const view = {zOrder: () => 'top' as const, renderer: () => ({draw: (target: any) => {
    if (!attached || !current || !levels.length) return;
    const {chart, series} = attached;
    const x = chart.timeScale().timeToCoordinate(current.time as UTCTimestamp);
    if (x === null) return;
    target.useMediaCoordinateSpace(({context: ctx, mediaSize}: {
      context: CanvasRenderingContext2D; mediaSize: {width: number; height: number};
    }) => {
      const {width, height} = mediaSize;
      if (x < 0 || x > width) return;
      const labels = levels.flatMap(level => {
        const y = series.priceToCoordinate(level.price);
        return y === null || y < 8 || y > height - 8 ? [] : [{level, y: Number(y)}];
      })
        .sort((a, b) => a.y - b.y);
      if (!labels.length) return;
      const gap = 16;
      const positions = labels.map(item => item.y);
      for (let i = 1; i < positions.length; i++) positions[i] = Math.max(positions[i], positions[i - 1] + gap);
      const shift = positions.reduce((sum, y, i) => sum + y - labels[i].y, 0) / positions.length;
      for (let i = 0; i < positions.length; i++) positions[i] -= shift;
      const overflow = Math.max(0, positions[positions.length - 1] - (height - 10));
      for (let i = 0; i < positions.length; i++) positions[i] -= overflow;
      for (let i = positions.length - 2; i >= 0; i--) positions[i] = Math.min(positions[i], positions[i + 1] - gap);
      const underflow = Math.max(0, 10 - positions[0]);
      for (let i = 0; i < positions.length; i++) positions[i] += underflow;
      const background = chart.options().layout.background;
      const backgroundColor = 'color' in background ? background.color : background.topColor;
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip();
      ctx.setLineDash([]);
      for (let i = 0; i < labels.length; i++) {
        const {level, y} = labels[i];
        const labelY = positions[i];
        const emphasized = level.emphasis.length > 0;
        const color = selectedColor(colors, level.red ? 'entry' : 'exit', level.red ? '#ef5350' : '#26a69a');
        const text = `${level.names.join('/')} ${level.red ? '红' : '绿'} ${level.price.toFixed(digits)}${emphasized ? ' · ' + level.emphasis.join('/') : ''}`.trim();
        ctx.font = `${emphasized ? '600' : '400'} 11px system-ui`;
        const textWidth = ctx.measureText(text).width;
        const clearance = Math.ceil(chart.timeScale().options().barSpacing / 2) + 3;
        const offset = clearance + 16;
        const right = width - x >= offset + textWidth + 4 || width - x >= x;
        const direction = right ? 1 : -1;
        const tickStart = x + direction * clearance;
        const tickEnd = tickStart + direction * 12;
        const textX = right ? x + offset : x - offset - textWidth;
        const anchor = right ? textX - 3 : textX + textWidth + 3;
        // The tick stays at the actual price. Only the label moves to avoid collisions.
        ctx.lineWidth = emphasized ? 2.5 : 1;
        ctx.strokeStyle = color;
        ctx.beginPath(); ctx.moveTo(tickStart, y); ctx.lineTo(tickEnd, y); ctx.stroke();
        ctx.lineWidth = .7; ctx.globalAlpha = .65;
        ctx.beginPath(); ctx.moveTo(tickEnd, y); ctx.lineTo(anchor, labelY); ctx.stroke();
        ctx.globalAlpha = .92; ctx.fillStyle = backgroundColor;
        ctx.fillRect(textX - 2, labelY - 7, textWidth + 4, 14);
        ctx.globalAlpha = 1; ctx.fillStyle = color;
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(text, textX, labelY);
      }
      ctx.restore();
    });
  }})};
  return {attached: value => {attached = value; value.requestUpdate();}, detached: () => {attached = null;}, paneViews: () => [view]};
}
