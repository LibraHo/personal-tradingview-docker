# 第二批常用指标与验证说明

新增 20 个内置指标，总计 41 个内置项；原公式/Python 自定义指标继续保留。在「设置 → 指标管理」添加、调整参数和颜色，图表工具栏「指标」可直接开关。新指标不自动加入现有图表，避免挤占看盘区域；所有新项沿用原有图表/周期范围和自动保存。

## 指标目录与默认值

| 指标 | 默认位置 | 默认参数与约定 |
|---|---|---|
| KDJ | 副图 | 9/3/3；RSV 后按 1/N 递归平滑，K/D 初始 50，J=3K−2D |
| MFI 资金流量 | 副图 | 14；典型价涨跌决定正负资金流，0–100 |
| KC Keltner 通道 | 主图 | EMA20 ± 2×ATR10，ATR 使用 Wilder 平滑 |
| Supertrend 超级趋势 | 主图 | Wilder ATR10、倍数3；最终上下边界决定方向 |
| SAR 抛物线转向 | 主图圆点 | 初始0.02、步长0.02、上限0.2 |
| Stoch RSI | 副图 | Wilder RSI14、随机窗口14、K/D 3/3；按0–100显示 |
| HMA Hull均线 | 主图 | 21；半周期向下取整，根号周期四舍五入 |
| DEMA 双重指数均线 | 主图 | 20；2×一级EMA−二级EMA |
| TEMA 三重指数均线 | 主图 | 20；3×一级EMA−3×二级EMA+三级EMA |
| TRIX | 副图 | 三级EMA15的单根变化率（%），信号EMA9 |
| PPO | 副图 | EMA12/26差÷EMA26×100，信号EMA9及差值柱 |
| AO | 副图柱 | 中间价(H+L)/2的SMA5−SMA34，按相邻柱升降着色 |
| BIAS 乖离率 | 副图 | 6；(收盘−SMA)/SMA×100，可添加多实例 |
| ADL 累积派发 | 副图 | 收盘在高低区间内的相对位置×成交量，逐根累计 |
| CHO 蔡金振荡 | 副图 | ADL的EMA3−EMA10 |
| PVT 价量趋势 | 副图 | 累计单根收盘变化率×成交量 |
| BOP 多空力量 | 副图 | (收盘−开盘)/(最高−最低) |
| BBW 布林带宽 | 副图 | SMA20、总体标准差2倍；带宽÷中轨×100 |
| %B 布林位置 | 副图 | 同上；(收盘−下轨)/(上轨−下轨)，0–1标度，可越界 |
| Aroon | 副图 | 25；检索当前及前25根，相同极值取最近一根 |

Supertrend 的方向输出为 `direction`（1=上行，−1=下行），该输出仅供只读 API 使用，不画到价格轴。网页使用一条按方向变色的连续趋势线，反转处连接前后值；上涨/下跌颜色可分别设置。SAR 使用圆点而非连线。PPO 柱沿用 MACD 深浅四色规则；AO 柱使用上升/下降两色。

## 初始化、数据与限制

- KDJ 在完整 RSV 窗口后开始，K/D以50起步；窗口高低相同时 RSV=50。Stoch RSI 使用独立的标准 Wilder RSI：N个价格变化的均值作为初始涨跌均值，之后按1/N平滑；RSI平价时50，RSI随机窗口无跨度时不输出。
- 新 KC/Supertrend 使用完整 N 根真实波幅的均值作为 ATR 初始值，再按1/N平滑。Supertrend 首个有效 ATR 点初始化为下行，后续按最终边界翻转。这里的 Wilder 平滑与旧版内置 ATR/RSI 的 EMA 平滑约定不同；本次不改动原指标或交易策略计算，避免改变已有行为。
- SAR 第一根无值，第二根按两根收盘涨跌确定方向，用第一根低/高作为初始 SAR；之后先推进，再检查穿越和反转（遵循TradingView公开顺序，并为8.06穿越8.01而反转的边界样例添加回归），未反转时限制在前两根低/高之外。跳空反转时将旧极值与当前高/低比较，保证反转点位在当前价格范围外。
- DEMA/TEMA/TRIX/PPO/CHO 的 EMA 从第一项有效输入开始递推，与已有 EMA 的种子约定一致。加载更多历史会改变靠近初始化处的数值，不能据此声称与其他平台逐点完全一致。
- MFI 需要 N 个相邻价格变化；正负方向资金流都为0时无值，只有正流时100，只有负流时0。ADL、PVT 累计起点随已加载历史改变；PVT前收盘为0的点无值且不累计。BOP/ADL平价K线贡献记0。零分母、窗口不足不伪造数值。
- 每个窗口按选中周期和交易时段的 K 线根数计，滚动/递归指标跨日连续。盘前/盘后/夜盘开关会改变计算输入；未收线 K 线会随价格改变。计算不使用未来K线，无按盈利结果回填历史的逻辑。
- 图表与只读 `/api/indicators` 同时支持这些名称；没有新增订阅、后台任务、数据库或运行时依赖。没有扩大自动交易策略白名单，也没有测试或提交真实订单。

## 公式来源

公开公式经自行实现。下列为官方说明，不使用社区脚本中的未经确认买卖规则：

- 富途：[KDJ](https://support.futunn.com/hant/topic149/)、[BIAS](https://support.futunn.com/topic257)。
- TradingView：[Supertrend](https://www.tradingview.com/support/solutions/43000634738-supertrend/)、[SAR](https://www.tradingview.com/support/solutions/43000502597-parabolic-sar-sar/)、[KC](https://www.tradingview.com/support/solutions/43000502266-keltner-channels-kc/)。
- TradingView：[MFI](https://www.tradingview.com/support/solutions/43000502348-money-flow-mfi/)、[Stoch RSI](https://www.tradingview.com/support/solutions/43000502333-stochastic-rsi-stoch-rsi/)、[Aroon](https://www.tradingview.com/support/solutions/43000501801-aroon-indicator/)。
- TradingView：[HMA](https://www.tradingview.com/support/solutions/43000589149-hull-moving-average/)、[DEMA](https://www.tradingview.com/support/solutions/43000589132-double-exponential-moving-average-ema/)、[TEMA](https://www.tradingview.com/support/solutions/43000591346-triple-ema/)。
- TradingView：[TRIX](https://www.tradingview.com/support/solutions/43000502331-trix/)、[PPO](https://www.tradingview.com/support/solutions/43000502346-percentage-price-oscillator-ppo/)、[AO](https://www.tradingview.com/support/solutions/43000501826-awesome-oscillator-ao/)。
- TradingView：[ADL](https://www.tradingview.com/support/solutions/43000501770-accumulation-distribution-adl/)、[CHO](https://www.tradingview.com/support/solutions/43000501979-chaikin-oscillator/)、[PVT](https://www.tradingview.com/support/solutions/43000502345-price-volume-trend-pvt/)、[BOP](https://www.tradingview.com/support/solutions/43000589100-balance-of-power-bop/)。
- TradingView：[BBW](https://www.tradingview.com/support/solutions/43000501972-bollinger-bandwidth-bbw/)、[%B](https://www.tradingview.com/support/solutions/43000501971-bollinger-bands-b-b/)。

## 测试证据与复现

1. `python -m unittest discover -s tests`：166项通过，其中16项新增测试覆盖20种指标。包含手算KDJ/MFI/KC/超级趋势反转/SAR夹限与反转、直接加权窗口验证HMA、常量/零量/空输入、参数错误、截断历史无前视与当前K线校正。
2. `node web/test-advanced-indicators.mjs`：264组完整前端入口与Python入口对照通过（标准、1根、空、平价/零量；多个周期）。上一批40组对照继续通过。两端相同并非独立正确性的证明，所以另保留上面的手算/直接公式样例。
3. 原EMA/MA周期与MACD/成交量配色回归通过；修复测试加载器以支持拆分后的真实模块，不再替换计算依赖。
4. Edge真实图表测试逐个添加20种指标，验证主副图默认位置、选择颜色实际画出、快捷隐藏后消失、WebSocket当前K线更新后仍显示且不重复K线、参数校验、刷新恢复。浏览器测试使用隔离行情夹具，不覆盖实际自选和交易配置。

这些是正确性和功能验证，不是盈利回测。没有提供胜率、收益率或“高胜率”承诺；也未声称已经与券商客户端逐根逐值对齐。
