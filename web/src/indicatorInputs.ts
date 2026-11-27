import requirements from '../../app/indicator_inputs.json';
import type {Bar} from './indicators';

type Requirements = {fields: string[]; adjustment?: string; providers?: string[]};
const inputs = requirements as Record<string, Requirements>;
const labels: Record<string,string> = {volume: '成交量（股）', turnover: '成交额', chip_winner_95:'逐根历史 WINNER(0.95×收盘价)', chip_cost_85:'逐根历史 COST(85)'};

export function inputIssue(bars: Bar[], name: string, params: string) {
  if (!bars.length) return '';
  let fields = inputs[name]?.fields ?? [];
  if (name === 'CUSTOM' && /\b(V|VOL|VOLUME)\b/i.test(JSON.parse(params).formula ?? '')) fields = ['volume'];
  const requirement = inputs[name];
  if (requirement?.providers && bars.some(bar=>!requirement.providers!.includes(bar.provider ?? '')))
    return '需要行情源 ' + requirement.providers.join('、');
  if (requirement?.adjustment && bars[0].adjustment && bars[0].adjustment !== requirement.adjustment)
    return '需要' + ({none:'不复权',qfq:'前复权',hfq:'后复权'} as Record<string,string>)[requirement.adjustment] + '价格';
  for (const field of fields) {
    const missing = bars.filter(bar => !Number.isFinite(field==='volume'||field==='turnover'?bar[field]:bar.fields?.[field])).length;
    if (missing) return '所需的' + (labels[field] ?? field) + '缺失，影响 ' + missing + ' 根 K 线';
  }
  return '';
}
