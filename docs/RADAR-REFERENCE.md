# 参考源码核对与实现选择

2026-11-16 通过 Git 获取 https://github.com/jundizhou/easy-stock ，HEAD `7b0b1904b2deca02a6ffcc666c02579d7446ef56`。
核对入口：backend/docs/architecture.md、backend/internal/httpapi/server.go、internal/sector/{radar,theme_index}.go、internal/narrative/narrative.go、internal/httpapi/{limit_up_ladder,market_emotion}.go、internal/providers/eastmoney/limit_up.go、internal/providers/tencent/us_sector.go。

最新 LICENSE 仍是 PolyForm Noncommercial 1.0.0，副本保存在 EASY-STOCK-LICENSE.txt。
Required Notice: Copyright (c) 2026 jundizhou. Commercial use of easy-stock requires prior written permission from the copyright holder.

参考项目行业/题材融合与涨停池是不同 provider，历史/盘中缓存保留来源与失效状态；自建题材映射不等于可交易板块指数。部分东方财富 push2 接口需要 Electron 会话桥，不适合直接把整个桌面 Go 后端部署为本 NAS 的依赖。美股行业实现采用11个 SPDR ETF 代理，不能移用 A 股涨停体系。

本次采用现有 Python/FastAPI 内独立适配，未引入 Go/Electron 服务或复制整个模块。板块与指数K线使用已验证 OpenD；涨停相关补充使用东方财富公开数据端点。图表计算复用既有 Python 指标，并沿用前后端数值一致性测试。

真实源核对：OpenD 10.10.7008 的 SH 与 SZ 涨跌分布均返回 SH.LIST3000005；直接把该代码作为 security 请求反而报未知股票，因此按市场查询。交易日历使用 TradeDateMarket.CN，与行情的 Market.SH 不同。东方财富历史池 qdate 返回最新可用日而非请求日：2026-11-13 池中的 SZ.001358=26.64、SZ.300528=17.99 已与 OpenD 当日日线收盘核对。
