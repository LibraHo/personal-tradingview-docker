# OpenD 能力核验与筹码结论修正

2026-11-16，按用户要求只核查已有OpenD数据；Web API授权验证已停止。本次未更新线上指标或更改服务。

NAS安装的moomoo SDK版本10.10.7008。OpenQuoteContext存在166个公开可调用成员（包含连接/内部生命周期方法，并非166个业务API）。公开Qot协议文件302个。行情、K线、盘口、逐笔、资金流、板块、财报、机构持股、空头数据、期权、选股V2及指标计算入口均存在；存在接口不等于账户有权限或每个市场都有数据。

## 筹码：确实有汇总数据

此前只检查独立chip/winner/cost接口名称，结论不充分。SDK的FeaturedProperty定义CHIPS_PROFIT_RATIO=5101、CHIPS_INTERVAL_COINCIDENCE=5102。通过get_stock_screen + add_retrieve_featured能够读取。

实际在原OpenD连接下，CN和US各取市值排序前5个样本，两个字段均返回dval。例：工商银行601398：获利比例1.0、重合度0.7647；建设银行601939：0.9932、0.7931；AAPL：0.9914、0.6787；NVDA：0.0476、0.7189；MSFT：0.8182、0.8579。显示百分比时乘100；不得再次除以源码注释的倍率。上游结果未附筹码计算时刻，不能声称是指定收盘日的数据，也不能将快照回填历史。

实机SDK的StockScreenQuery/_dict_to_pb仍调用新protobuf已删除的FieldDescriptor.label。验证进程内将重复字段判断替换为is_repeated，并同时修正旧类引用的解析函数；未改site-packages或线上进程。正式接入必须以兼容层加测试解决，不应随意升级全局依赖。

## 仍未具备的精确公式输入

这两个汇总字段不是完整价位分布。原式需要WINNER(C*0.95)及COST(85)：当前价获利比例无法确定当前价95%处的累计筹码；重合度也不是85%分位成本。即使当前价获利比例可作为后一条件的近似检验，也受严格不等号、边界筹码以及两家算法差异影响，不能宣称精确等价。当前接口未验证有历史快照、任意价位累计比例或成本分位输出，get_indicator_list('筹码')实测为空。

## 官方依据

- OpenD行情总览：https://openapi.futunn.com/futu-api-doc/quote/overview.html
- 选股V2与特色属性：https://openapi.futunn.com/futu-api-doc/quote/get-stock-screen.html
- 资金分布为订单大小的流入流出，不是成本筹码：https://openapi.futunn.com/futu-api-doc/quote/get-capital-distribution.html

Web API另有完整直方图文档，但用户明确以OpenD为数据来源，本次不接入、不要求另行授权。

后续兼容性工作应按市场、产品、周期、字段和权限分别标记；已验证A/US样本可用的两项筹码汇总不应被标为A股专属。未验证范围、缺字段、未接入功能需独立于false/0信号呈现。兼容性改造尚未部署。

## Moomoo Web API 核查补充

官方 Web API 概览（https://open.futunn.com/zh-hk/api/overview）明确列出 Moomoo US/SG/AU/MY/CA/JP 券商的 WebAPI 交易覆盖；费用页也列出这些券商。这证明平台支持范围包含 Moomoo，但不证明当前用户账号已完成 OAuth 或拥有筹码接口权限。

完整分布官方入口为 https://webapi.futunn.com/api/v1.0/quote/{symbol}/chip-distribution ，提供 histogram 的 price/volume、timestamp，可用于计算富途模型下的 WINNER/COST。文档注明主要覆盖 A 股；US 示例不能证明美股实际有值。Web API 使用独立 OAuth/API Key；未取得本账号有效授权，因此完整分布的账号级 A/US 实测未完成。不得把未验证写成不支持，或要求用户更换现有 OpenD 行情来源。

复核此前已获取的390条指标语言记录，成本相关只有 CYC 成本均线，未发现 WINNER/COST/筹码分布指标入口。本次再次 SSH 核查完成，SDK 源码命中仍为两项筹码汇总字段。can_send_proto(9070) 返回 True，但这只是本地发送检查，未实际请求或解码完整筹码数据，不能据此证明 OpenD 支持 Web API 文档中的 cmd 9070。get_global_state 成功但未返回名称含 version 的字段，未确认网关版本。

## 再次 A 股实测

通过现有 Moomoo OpenD get_stock_screen 查询 CN 市场，工商银行、建设银行、农业银行均返回获利比例及重合度。分别不传、传95、传85作为 first_custom_param 进行对照，结果见 .audit/compat-release/opend-cn-params-probe.txt；参数是探索性对照，未被官方定义为价位或分位，不能用其返回冒充 WINNER(0.95C)/COST85。

进一步检查 can_send_proto 源码：除初始化外只检查连接状态为 READY，不检查协议是否支持。因此其 True 完全不是9070业务能力证据。现有SDK未找到完整筹码的协议封装，未发送未经定义的9070报文；WebAPI cmd编号不能直接当OpenD协议编号使用。
