import { Plus, Trash2 } from 'lucide-react';
import type { Indicator } from './indicators';
import { periodNames, type PlanPeriod } from './tradeBookClient';
import AdvancedParameters from './AdvancedParameters';
import {
  conditionLabel,
  newPlanCondition,
  planSources,
  type PlanCondition,
  type PlanConditions,
  type PlanEstimate,
  type PlanSource,
} from './tradePlanAnalysis';

type Props = {
  label: string;
  group: PlanConditions;
  period: PlanPeriod;
  exit?: boolean;
  indicators: Indicator[];
  estimates: Record<string, PlanEstimate>;
  onChange: (group: PlanConditions) => void;
  onPrice: (price: number, label: string) => void;
};

export default function PlanConditionsEditor({
  label,
  group,
  period,
  exit = false,
  indicators,
  estimates,
  onChange,
  onPrice,
}: Props) {
  const patch = (id: string, values: Partial<PlanCondition>) =>
    onChange({
      ...group,
      items: group.items.map((item) => (item.id === id ? { ...item, ...values } : item)),
    });
  return (
    <section className="plan-section">
      <div className="plan-section-heading">
        <h3>{label}</h3>
        <select
          aria-label={label + '组合方式'}
          value={group.join}
          onChange={(e) => onChange({ ...group, join: e.target.value as 'all' | 'any' })}
        >
          <option value="all">全部满足</option>
          <option value="any">任一满足</option>
        </select>
      </div>
      {group.items.map((condition, index) => {
        const estimate = estimates[condition.id];
        const name = `${label}条件 ${index + 1}`;
        const priceBased = !['SIXPULSE', 'MACD', 'RSI', 'PRICE'].includes(condition.source);
        return (
          <div className="plan-condition-row" key={condition.id}>
            <div className="plan-condition-fields">
              <label>
                指标
                <select
                  aria-label={name + '指标'}
                  value={condition.source}
                  onChange={(e) =>
                    patch(condition.id, {
                      ...newPlanCondition(e.target.value as PlanSource, condition.period, exit, indicators),
                      id: condition.id,
                    })
                  }
                >
                  {Object.entries(planSources).map(([key, title]) => (
                    <option key={key} value={key}>
                      {title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                周期
                <select
                  aria-label={name + '周期'}
                  value={condition.period}
                  onChange={(e) => patch(condition.id, { period: e.target.value as PlanPeriod })}
                >
                  {Object.entries(periodNames).map(([key, title]) => (
                    <option key={key} value={key}>
                      {title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                条件
                <select
                  aria-label={name + '判断'}
                  value={condition.signal}
                  onChange={(e) => patch(condition.id, { signal: e.target.value as PlanCondition['signal'] })}
                >
                  {condition.source === 'SIXPULSE' ? (
                    <>
                      <option value="reds">红数至少</option>
                      <option value="greens">绿数至少</option>
                    </>
                  ) : condition.source === 'MACD' ? (
                    <>
                      <option value="bullish">DIF ≥ DEA</option>
                      <option value="bearish">DIF ≤ DEA</option>
                    </>
                  ) : (
                    <>
                      <option value="above">{priceBased ? '站上' : '大于等于'}</option>
                      <option value="below">{priceBased ? '跌破' : '小于等于'}</option>
                    </>
                  )}
                </select>
              </label>
              <button
                type="button"
                className="plan-remove"
                aria-label={'删除' + name}
                onClick={() =>
                  onChange({ ...group, items: group.items.filter((item) => item.id !== condition.id) })
                }
              >
                <Trash2 size={15} />
              </button>
              {condition.source === 'SIXPULSE' && (
                <label>
                  数量
                  <select
                    aria-label={name + '红绿数量'}
                    value={condition.threshold}
                    onChange={(e) => patch(condition.id, { threshold: Number(e.target.value) })}
                  >
                    {[1, 2, 3, 4, 5, 6].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {['RSI', 'PRICE'].includes(condition.source) && (
                <label>
                  阈值
                  <input
                    aria-label={name + '阈值'}
                    type="number"
                    required
                    min={condition.source === 'RSI' ? 0.01 : 0.00000001}
                    max={condition.source === 'RSI' ? 99.99 : undefined}
                    step="any"
                    value={condition.threshold || ''}
                    onChange={(e) => patch(condition.id, { threshold: Number(e.target.value) })}
                  />
                </label>
              )}
              {condition.source === 'BOLL' && (
                <label>
                  轨道
                  <select
                    aria-label={name + '布林轨道'}
                    value={condition.line}
                    onChange={(e) => patch(condition.id, { line: e.target.value as PlanCondition['line'] })}
                  >
                    <option value="upper">上轨</option>
                    <option value="mid">中轨</option>
                    <option value="lower">下轨</option>
                  </select>
                </label>
              )}
              <label className="plan-confirmation">
                确认
                <select
                  aria-label={name + '确认方式'}
                  value={condition.confirmation}
                  onChange={(e) => patch(condition.id, { confirmation: e.target.value as 'close' | 'live' })}
                >
                  <option value="close">收线确认</option>
                  <option value="live">盘中观察</option>
                </select>
              </label>
            </div>
            <div className="plan-condition-result">
              <span>
                {estimate
                  ? estimate.met === null
                    ? estimate.note
                    : estimate.met
                      ? '当前试算满足'
                      : '当前试算未满足'
                  : '等待行情'}
              </span>
              {estimate?.price != null && (
                <button type="button" onClick={() => onPrice(estimate.price!, conditionLabel(condition))}>
                  {exit ? '设为防守位' : '设为入场参考'} {estimate.price.toFixed(2)}
                </button>
              )}
              {estimate && estimate.met !== null && estimate.price === null && <small>{estimate.note}</small>}
            </div>
            {condition.source !== 'PRICE' && (
              <details className="plan-condition-parameters">
                <summary>计算参数</summary>
                {condition.source === 'SIXPULSE' ? (
                  <AdvancedParameters
                    name="SIXPULSE"
                    params={JSON.stringify(condition.params)}
                    onChange={(value) => patch(condition.id, { params: JSON.parse(value) })}
                  />
                ) : condition.source === 'BBI' ? (
                  <label>
                    BBI 周期
                    <input
                      aria-label={name + 'BBI周期'}
                      defaultValue={(condition.params.periods as number[]).join(',')}
                      onBlur={(e) => {
                        const periods = e.target.value
                          .split(/[,，\s]+/)
                          .filter(Boolean)
                          .map(Number);
                        if (
                          periods.length &&
                          periods.length <= 12 &&
                          periods.every((value) => Number.isInteger(value) && value > 0 && value <= 2000)
                        )
                          patch(condition.id, { params: { periods } });
                        else e.target.value = (condition.params.periods as number[]).join(',');
                      }}
                    />
                  </label>
                ) : condition.source === 'VWAP' ? (
                  <label>
                    重置
                    <select
                      value={String(condition.params.reset)}
                      onChange={(e) => patch(condition.id, { params: { reset: e.target.value } })}
                    >
                      <option value="session">每个交易时段</option>
                      <option value="day">每个交易日</option>
                      <option value="never">已加载历史</option>
                    </select>
                  </label>
                ) : (
                  <div className="plan-parameter-fields">
                    {Object.entries(condition.params).map(([key, value]) => (
                      <label key={key}>
                        {{ period: '周期', stddev: '标准差倍数', fast: '快线', slow: '慢线', signal: '信号' }[
                          key
                        ] || key}
                        <input
                          aria-label={name + '参数' + key}
                          type="number"
                          required
                          min={key === 'stddev' ? 0.01 : 1}
                          max={2000}
                          step={key === 'stddev' ? 'any' : 1}
                          value={Number(value) || ''}
                          onChange={(e) =>
                            patch(condition.id, {
                              params: { ...condition.params, [key]: Number(e.target.value) },
                            })
                          }
                        />
                      </label>
                    ))}
                  </div>
                )}
              </details>
            )}
          </div>
        );
      })}
      <button
        type="button"
        className="plan-add"
        disabled={group.items.length >= 12}
        onClick={() =>
          onChange({
            ...group,
            items: [...group.items, newPlanCondition('SIXPULSE', period, exit, indicators)],
          })
        }
      >
        <Plus size={14} />
        添加{label.includes('入场') ? '入场' : '出场'}条件
      </button>
    </section>
  );
}
