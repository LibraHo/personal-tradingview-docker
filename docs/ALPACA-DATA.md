# Alpaca 美股行情

适配器入口为 `app.alpaca_data:factory`。它通过 HTTP 读取美股历史 K 线、最新成交快照、交易日历、证券目录和账户自选分组。图表使用定时刷新。与其他源组合时按能力和市场配置，见[行情源与复权](../README.md#行情源与复权)。

## 配置

| 服务端环境变量 | 用途 |
| --- | --- |
| `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY` | 对应 Alpaca 账户的 API 凭证 |
| `ALPACA_DATA_FEED` | 默认 `iex`，仅覆盖 IEX 交易所。`sip` 提供全美综合行情，最近数据取决于账户订阅权限 |
| `ALPACA_ACCOUNT_ENV` | 默认 `paper`。使用实盘账户的凭证时设为 `live`；此项选择交易日历、证券目录和自选的只读服务地址 |
| `ALPACA_OVERNIGHT` | 默认 `false`。有 Blue Ocean ATS 权限时可设为 `true`，启用包含夜盘的全时段历史 |

将 `MARKET_DATA_PROVIDER=app.alpaca_data:factory` 作为全局配置时，行情范围为美股。也可只将美股历史路由到此适配器。数据集标识包含 `iex` 或 `sip`，开启夜盘后另带 `_boats`。每种组合独立缓存。[Alpaca 历史行情与权限](https://docs.alpaca.markets/us/docs/market-data-faq)

## 数据口径

- 历史 `none` 使用 Alpaca 的 `raw`，`qfq` 使用 `all`，即供应商对历史拆并股、现金分红与公司分拆的调整。拆并股也会调整成交量。具体因子取自 Alpaca，与 OpenD 的前复权分别缓存。`hfq` 不可用。证券更名沿用 Alpaca 的当前日期代码映射；历史区间可包含该公司旧代码的记录。`asof` 控制证券代码映射，历史截止日期限制返回的成交日期，两者都不提供指定日期版本的复权因子。[历史 K 线](https://docs.alpaca.markets/us/reference/stockbars)
- 支持 1、5、15、30、60、120、240 分钟和日、周、月线。按纽约时区和市场日历过滤分钟数据，半日市在实际收盘时刻结束盘中区间。日、周、月线从常规时段分钟数据汇总，时间戳为区间起点。近期未收线的周期可随刷新更新。历史日历缺失、权限不足或分页失败时，接口会返回原因。[Alpaca K 线构造说明](https://docs.alpaca.markets/us/docs/market-data-faq) · [美股日历](https://docs.alpaca.markets/us/reference/legacycalendar)
- 常规时段和延长时段使用 IEX 或 SIP 能提供的成交记录。全时段另使用 BOATS 的美东时间 20:00 至次日 04:00 数据。账户须拥有请求所用 feed 的权限，权限错误会直接显示。[历史行情 feed](https://docs.alpaca.markets/us/reference/stockbars)
- 成交量以股计，Alpaca K 线没有直接提供成交额，适配器保留空值。需要成交额的指标会提示缺少输入。最新快照取所选日间 feed 的最近成交价、时间和名义涨跌幅，涨跌幅用该成交日期之前最近一个快照日线收盘价计算。盘前、盘后及夜盘独立报价字段留空。[快照接口](https://docs.alpaca.markets/us/reference/stocksnapshots-1)
- 证券目录限美股资产，自选分组手动导入，均从与凭证匹配的 paper 或 live 账户读取。此适配器不承担券商交易、盘口、逐笔、期权或板块能力。[自选接口](https://docs.alpaca.markets/us/reference/getwatchlists-1)
