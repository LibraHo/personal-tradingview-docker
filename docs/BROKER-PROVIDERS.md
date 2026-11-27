# 券商数据与交易接口

行情源提供图表和指标数据。券商接口提供账户持仓、成交和委托，并为下单校验读取该券商的报价和交易能力。在市场服务和 HTTPS 交易网关中配置相同的 `BROKER_PROVIDER`，重启对应进程后生效。

| 配置 | 账户归档与交易 |
| --- | --- |
| 省略或空值 | 单一内置 OpenD 行情源沿用 OpenD 券商。指定其他 `MARKET_DATA_PROVIDER` 或非空 `MARKET_DATA_ROUTES` 后，券商默认为禁用。 |
| `disabled` | 账户同步显示未启用，交易台无法提交券商操作。历史账本仍可查阅。 |
| `opend` | 明确使用 OpenD 券商，可与其他行情源搭配。 |
| `module:factory` | 加载部署环境提供的无参数工厂或类。两个服务均需能导入该模块。 |

工厂在自身声明稳定的 `source_id` 和 `capabilities`。标识以小写字母开头，限小写字母、数字、下划线及连字符，最多 48 位。更换券商或切换到独立的账户数据库时使用新的标识。工厂返回独立实例，连接延迟到实际操作。内置 OpenD 适配器位于 `app/opend_broker.py`，接口定义位于 `app/broker_provider.py`。

## 只读账户与历史成交

实现 `ArchiveBroker`，声明 `capabilities = {'archive'}`，即可启用归档。交易网关不会实例化只读归档工厂。以下是市场归档进程调用的接口。

| 方法 | 返回数据 |
| --- | --- |
| `accounts()` | 可读美股账户列表。`acc_id` 为精确字符串，`trd_env` 为 `REAL` 或 `SIMULATE`，当前账本只同步实盘。 |
| `archive_positions(account)` | 此账户的完整美股持仓。空列表代表确认为空仓。查询失败或仅取到部分分页应抛出异常，以保留原快照。 |
| `archive_fills(account, start, end, as_of)` | 美东交易日闭区间的全部成交，至多 90 天。`as_of` 含 UTC 时区。适配器负责分页、枚举转换和校正记录排序。 |
| `close()` | 关闭该实例的连接。 |

持仓与成交共用 `kind`、`symbol`、`code`。正股示例为 `stock, US.AAPL, US.AAPL`。期权以标的为 `symbol`，独立合约为 `code`，另需 `expiry`、`strike` 和 `right`（C/P）。持仓 `qty` 单位为股或张，空头为负，`cost` 可省略。每条成交另需字符串 `broker_id`、含时区的 `at`、`side`（BUY、SELL、SELL_SHORT、BUY_BACK）、正数 `qty` 与 `price`。价格为当时实际成交美元价格。映射失败可抛 `ArchiveError` 并附带适合页面显示的原因。

`broker_status` 默认为 `OK`。券商更正应返回相同编号及 `CHANGED` 和完整内容。撤销成交只需编号与 `CANCELLED`。系统以来源、账户及成交编号去重，完成提交后才推进该来源的游标。账户键使用 `<source_id>:REAL:<acc_id>`，原 OpenD 账户继续使用 `OpenD:REAL:<acc_id>`。旧 OpenD 游标在首次访问 OpenD 同步时迁移。

读取同步状态使用 `GET /api/review/ledger/broker`，排队刷新使用 `POST /api/review/ledger/broker/sync`，可附加 `start`、`end`。Agent 对应路径位于 `/api/v1/review/ledger/`。原 `opend`、`opend/sync` 路径兼容现有调用，返回当前配置来源。同步状态的 `provider` 提供来源标识。合并成交接受 `manual_id` 与 `broker_fill_id`，旧字段 `opend_id` 仍可读取。

## 交易适配器

实现 `TradingBroker` 并声明 `trading` 能力。支持两种用途的工厂可同时声明 `trading` 和 `archive`。本项目唯一内置的真实交易适配器是 OpenD。

- `accounts, positions, funds, orders` 返回标准字典列表，账户、成交与委托编号保留字符串精度。账户和订单须按传入的账户及实盘/模拟环境隔离。资金以美元计。持仓含 `code, qty, can_sell_qty, position_side`。订单含 `order_id, code, order_type, trd_side, order_status, qty, dealt_qty, price, remark`，修改委托还需保留其交易时段及条件单字段。
- `quote` 返回与请求匹配的 `code, stock_type, last_price, update_time, market_state`。执行用价格是可交易证券的原始报价。支持含偏移量的时间戳，旧 OpenD 本地时间按纽约时间解释。常规交易状态映射为现有交易台枚举 `AFTERNOON`。市价单要求最新快照。期权链结构与合约标准、到期日、合约乘数等字段见内置适配器的 `option_chain` 和 `quote`。无法确认品种、权限或字段时应返回明确的错误。
- `capacity` 返回 `max_cash_buy` 或 `max_position_sell`。适配器应按实际货币、市场及订单类型映射这些限制，缺少能力时由交易台阻止提交。
- `unlock` 对接券商交易授权或锁定。`generation` 每次新建或替换交易连接时递增。实盘预览和提交均检查当前网页会话、账户、授权期限及连接代次。
- `place, modify` 映射已校验的订单，保留 `NMT:<operation_id>` 备注供核对。明确被拒才抛出 `BrokerRejected`。请求可能已抵达券商时抛 `BrokerUncertain`，由操作流水保留待核对状态。异常消息应去除账户凭证。

OpenD 沿用原目录下的交易和策略数据库。其他券商按 `brokers/source-<source_id>/` 隔离交易流水、策略及止损。交易库记录所属券商，并校验身份后才恢复未决操作。平台登录凭证仍属于同一网关。切换供应商前，请通过原券商核对存续委托和保护单，切换后的适配器无法代管原账户。
