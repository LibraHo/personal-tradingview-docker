# 东方财富量化接入核查 · 2026-10-26

结论：存在官方自动交易接口，但应区分量化终端、EMT 实盘柜台接口与 Choice 数据接口。当前项目未接入东方财富，未申请账户或调用其交易接口。

## 可确认的官方能力

### 东方财富量化终端 / 东财掘金

官方帮助文档提供 Python 策略开发、回测、仿真、实盘、行情订阅、持仓和订单管理。交易 API 包括 order_volume、order_value、按目标仓位交易及撤单等。终端指引明确运行于本地 Windows，支持外部 Python IDE；不能把 SDK 可被外部调用解释为无需终端的 NAS Linux 直连。

- [终端指引](https://emt.18.cn/api/quant-help/guide/guide.html)
- [Python 交易接口](https://emt.18.cn/api/quant-help/python/python_trade_api.html)
- [订阅接口](https://emquant.18.cn/help/doc/python/python_subscribe.html)

若此通道适用于用户账户，可由常开 Windows 终端承担执行网关，NAS 保留网页、缓存和策略编辑。NAS 内新增 Windows 虚拟机与轻量目标冲突，暂不部署。

### EMT 极速交易 API

官方下载页列出 Windows/Linux 64 位 SDK、沪深 A 股/创业板/科创板/ETF/可转债/融资融券等业务及测试申请。对纯 Linux NAS 的部署方向比 Windows 终端更合适，但实际 CPU 架构、依赖、SDK 语言绑定和实盘授权仍需确认。

- [官方下载页](https://emt.eastmoneysec.com/down)
- [官方行情接入仿真测试指南](https://emt.18.cn/article/article-info/123025592)
- [官方 API 类型文档](https://emt.eastmoneysec.com/docs/EMT_API/emt__api__data__type_8h.html)

仿真指南明确其部分 L1/L2 测试行情为历史回放，只验证接收解析，不能用来证明实时策略收益。申请到测试账号不等于账户已获实盘交易许可。

### Choice / EmQuantAPI

官方提供数据、资讯、选股、组合管理，且有 Linux 配置说明。porder 位于组合管理接口，不能据此认定能给普通证券实盘账户报单。A 股自动交易应核实对应交易通道，而非仅取得 Choice 数据 token。

- [Choice Python 接口说明](https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.html)

## 未确认项

公开官方页面尚不足以确认普通个人账户的统一开通门槛、收费、资产要求、柜台迁移要求、程序化交易相关办理、IP/设备限制及 Linux CPU 架构支持。不采用网络营销文章中互相矛盾的资金门槛。

向东方财富官方客服/客户经理核实：个人 A 股账户能否申请 EMT Linux 64 位实盘接口；测试与实盘权限分别如何申请；费用/资产要求；是否需转入专用柜台；是否允许家庭 NAS 长期接入；是否有官方 Python SDK 及对应架构。

## 与当前项目的关系

可以在获准后增加 A 股执行适配层，复用网页策略编辑、监控记录、订单核对与授权流程。需要另外实现 A 股股票/ETF 数量规则、持仓可卖校验、交易时段和柜台状态映射；不能把美股执行逻辑直接照搬。

当前 NAS 此平台相关容器只有 moomoo-opend、nas-market-market-1、nas-market-trading-1。策略监控在现有 trading 服务中运行，没有新增独立量化容器。此处研究也没有部署东方财富服务。

## 官方申请入口

进入 [业务申请页面](https://emt.18.cn/business)，登录后选择“交易终端与服务 → API 测试申请”。该入口说明为东财自研柜台 EMT API 接口测试申请；掘金测试申请是另一项产品。SDK 在 [官方下载页](https://emt.eastmoneysec.com/down)。

测试后若需实盘，联系官方客服 95357 或客户经理确认个人账户资格、资产/收费、专用柜台、Linux 架构支持及程序化交易业务办理。公开页面未给出统一个人实盘门槛，不代替用户提交申请或发送资料。

后续已按用户要求将 market 与 trading 合并为一个应用容器，原 OpenD 保留；详情见 COMBINED-DEPLOYMENT.md。
