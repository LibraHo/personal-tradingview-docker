# 常用指标扩展与快捷开关

画图工具栏新增「指标」，按主图、副图列出当前市场已添加的指标，勾选即可显示或隐藏。开关沿用指标的图表和周期范围，自动保存；切换周期、股票时关闭面板，避免误操作。此入口没有参数编辑。未用于当前图表/周期的项目置灰；ORB5 在日/周/月线和 A 股 4 小时（日线）上不可开启。

第一次使用新指标：设置 → 指标管理 → 选择指标 → 添加。设置中仍可调整参数、主副图位置、颜色、适用图表和周期。可添加同名不同参数实例。不会把所有新指标强行放到已有图表上，也不会改变已有模板。

## 新增 10 种

| 指标 | 默认位置/参数 | 计算约定 |
|---|---|---|
| WMA 加权移动平均 | 主图，20 | 收盘价，最旧到最新权重 1…N |
| VWMA 成交量加权移动均线 | 主图，20 | N 根的收盘价×成交量之和 / 成交量之和 |
| DC 唐奇安通道 | 主图，20 | 含当前 K 线的 N 根最高、最低及二者中点 |
| STOCH 随机指标 | 副图，14/3/3 | 收盘价在 N 根高低区间内的位置；K 与 D 使用简单移动平均平滑 |
| CCI 顺势指标 | 副图，20 | 典型价 (H+L+C)/3 与均值的差 / (0.015×平均绝对偏差) |
| WR 威廉指标 | 副图，14 | −100×(N 根最高−收盘)/(N 根最高−N 根最低)，采用 −100…0 标度 |
| ROC 变动率 | 副图，9 | (收盘/N 根前收盘−1)×100，数值单位为百分比 |
| MOM 动量 | 副图，10 | 收盘−N 根前收盘，单位为价格 |
| OBV 能量潮 | 副图，无周期 | 从已加载第一根的 0 开始，按收盘涨跌加减当前成交量，平盘不变 |
| CMF 蔡金资金流 | 副图，20 | N 根 Σ[((2C−H−L)/(H−L))×V] / ΣV，采用 −1…1 标度 |

这些指标使用图表实际选中的交易时段和周期，窗口单位为 K 线根数，不是自然日。滚动指标跨日连续；VWAP 原有按时段/交易日重置保持独立。STOCH 是 K/D 双线随机指标，不是 KDJ。

完整窗口以前不输出；高低差为 0 时 WR/STOCH 不输出；CCI 偏差为 0 时输出 0；CMF 的平价 K 线资金流记 0。VWMA/CMF 的窗口成交量为 0、ROC 分母为 0 时不输出，不制造无穷大。OBV 是累积值，加载更早行情后绝对基准会改变，跨平台比较应使用同一起点。未收线 K 线会跟随行情更新；只使用当前与过去的数据，不读取未来 K 线。

均支持 1–2000 整数周期；新增计算同时用于浏览器与原有只读 `GET /api/indicators` 接口。例如：`/api/indicators?symbol=US.AAPL&period=15m&mode=regular&name=STOCH&params=%7B%22period%22%3A14%2C%22smoothK%22%3A3%2C%22smoothD%22%3A3%7D`。HTTPS 的受保护看盘入口使用现有 `/api/market/indicators` 转发和认证，不新增匿名权限。自动交易策略白名单没有随图表指标扩展。

## 资源与实现

没有新依赖、后台轮询、订阅或外部行情源。浏览器只计算已显示且适用于当前图表的指标；开关不会重新下载 K 线。滑动和、WMA、通道极值为线性复杂度；CCI 平均绝对偏差需要 O(根数×周期)。同时显示很多副图仍会占用浏览器资源和画面空间，可按需开关。

## 官方参考

- [TradingView 常用技术评级指标](https://www.tradingview.com/support/solutions/43000614331-technical-ratings/)
- [WMA](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/wma)、[VWMA](https://www.tradingview.com/support/solutions/43000592293-volume-weighted-moving-average-vwma/)
- [Donchian](https://www.tradingview.com/support/solutions/43000502253-donchian-channels-dc/)、[Stochastic](https://www.tradingview.com/support/solutions/43000502332-stochastic-stoch/)
- [CCI](https://www.tradingview.com/support/solutions/43000502001-commodity-channel-index-cci/)、[Williams %R](https://www.tradingview.com/support/solutions/43000501985-williams-r-r/)
- [ROC](https://www.tradingview.com/support/solutions/43000502343-rate-of-change-roc/)、[OBV](https://www.tradingview.com/support/solutions/43000502593-on-balance-volume-obv/)、[CMF](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/cmf)

依据公开公式自行实现，未复制 TradingView 私有脚本；不声称增加指标会提高胜率。

## 验证

- `python -m unittest discover -s tests`：包括手算数值、平价/零量、参数校验、窗口预热、当前 K 线修正与无未来数据污染。
- `node web/test-extra-indicators.mjs`：40 组 TypeScript/Python 结果对照，10 种指标空输入和无效参数。
- TypeScript 构建、浏览器实际画线颜色/显隐、主副图默认位置、参数保存、周期限制、刷新恢复、开关无额外历史请求。
