# NAS Market 扫描、监控与 OpenClaw API

入口：内网看盘 `http://192.168.101.103:8088`；已有 HTTPS 图表 `https://192.168.101.103:8443/chart`。
OpenClaw 已有可信 Docker 网络使用 `http://market:8000/api/v1`；HTTPS 入口同样支持 `/api/v1`，需信任现有 NAS CA，不应关闭证书校验。
没有新增公网端口或修改防火墙。现有 8088 内网浏览器入口沿用原访问方式；机器调用必须使用版本化接口的独立 token。

## 身份与权限

所有 `/api/v1/*` 请求须 `Authorization: Bearer <token>`。禁止 URL token。
`read` 允许 GET，`manage` 允许扫描/监控管理；`tokens` 才能管理 token。无交易权限。
NAS 上管理员凭证保存在 `data/scan-admin-token.txt`，OpenClaw 凭证保存在其 `~/.openclaw/credentials/nas-market-scan-token`（0600）。凭证不在前端、示例源码或本报告中。

`GET /tokens` 列出不含密钥的 token 元数据；`POST /tokens` 接收 `{"name":"consumer","scopes":["read"]}`，只在创建响应返回密钥；`DELETE /tokens/{id}` 立即撤销。

OpenAPI：`http://192.168.101.103:8088/openapi.json`，交互文档 `/docs`。其中 OpenClaw market API 分组使用 HTTP Bearer 安全定义。

## 接口

| 路径（相对 /api/v1） | 方法与用途 |
| --- | --- |
| `/markets` | GET 市场、实际支持分类、复权和时段 |
| `/sectors?market=CN&kind=industry&q=` | GET 动态目录；industry/concept 为 SDK 完整列表，无分页参数 |
| `/sectors/heatmap?market=US&kind=theme&page=` | GET 热力图，按 next_page 继续直到空，包含 total；不得只取首100项 |
| `/sectors/members?symbol=SH.LIST0002` | GET 去重成分及来源、抓取时间、失效状态 |
| `/bars?symbol=US.AAPL&period=1d` | GET 与图表相同数据及 close_time/confirmed |
| `/quotes?symbols=US.SPY,US.RSP` | GET 快照 |
| `/emotion?market=CN` | GET 全市场涨跌分布及定义；symbol 可指定板块 |
| `/emotion/analytics?market=US` | GET 启动/轮询扩展统计，返回 status/done/total/result；refresh=true 重新统计 |
| `/watchlists` | GET 关注列表与分组 |
| `/plans`、`/plans/{id}` | GET/POST、GET/PUT/DELETE 扫描方案；编辑递增 version |
| `/plans/{id}/copy`、`/plans/{id}/run` | POST 复制、提交后台扫描 |
| `/jobs`、`/jobs/{id}` | GET 最近任务、进度/结果/失败项 |
| `/jobs/{id}/cancel` | POST 取消（当前上游请求返回后停止） |
| `/monitors`、`/monitors/{id}` | GET/POST、GET 持久监控 |
| `/monitors/{id}/start`、`/monitors/{id}/pause` | POST 启动/暂停后续扫描；可另行取消正在执行的 job |
| `/events?after=0&limit=100` | GET 增量事件；过滤 monitor_id/symbol/market/period/plan_id/confirmation；next_cursor/has_more |
| `/health` | GET 行情连接、调度器、最后成功扫描、监控异常 |

## 通用条件

```json
{
  "name":"日线刚变六红",
  "scope":{"kind":"all"},
  "periods":["1d"], "join":"all", "lookback":1, "live":true,
  "rules":[{
    "left":{"name":"SIXPULSE","line":"REDS","params":{}},
    "op":"reach", "right":{"name":"NUMBER","value":6}
  }]
}
```

范围：all、groups（groups 是如 US:featured 的 ID 数组）、favorites、symbols（symbols 数组）、members（板块 symbols 数组）。跨分组去重并保留所属分组。指定 symbols 是自定义标的篮子，不制造篮子指数。

指标：PRICE、NUMBER、SMA、EMA、SIXPULSE、MACD、RSI、BOLL、VOLUME、DMI、ATR；各自输出线和参数可选。operand.scale 可对输出乘倍数，例如成交量 > VOLUME.average × 2。
操作：gt/gte/lt/lte/eq/cross_above/cross_below/reach。reach 要求前一根小于阈值、当前达到阈值；持续六红不会重复触发。
每条 rule.period 可指定不同周期。例如决策 periods=["1d"]，第一个 rule.period="1w" 比较 close>SMA20，第二个日线 MA10 cross_above MA20。历史决策只使用该时点已完成的高周期 K 线；当前盘中预览可以使用同一时点可见的未完成高周期。

## 调度与事件语义

创建监控：`POST /monitors`，字段 plan_id、interval_seconds（30–86400）、follow_watchlists、trading_only、backfill、enabled。
新方案默认包含未收线 K 线，使用常规时段行情，跟随关注列表，启用后识别新事件，不回填。首次建监控可显式 backfill=true 回填最近50根。监控固定创建时方案版本；编辑方案不会暗中改变运行中的监控。

调度器每5秒检查到期任务；批次串行，复用行情缓存与限速。交易日历来自 OpenD 的 TradeDateMarket，处理夏令时、美国半日市及 A 股午休。允许收盘后10分钟完成最终确认，首次运行与长时间断线恢复可在盘外执行。实际周期受标的数、上游限速、重试和队列影响，不保证30秒内遍历全部关注标的。

确认按该根 K 线的完成时间判断，不再等待下一根出现。盘中预览和收盘确认分别标记，每根 K 线每种确认状态最多一个稳定事件。监控检查点、事件和状态保存于 NAS SQLite；重试/重启不会重复创建同一事件。离开条件后在后续 K 线重新满足会有新事件。恢复会检查当前可用历史，检查点超出缓存历史窗口会报错，不宣称已完整补跑。

增量读取不删除事件，每个消费者自行保存游标。事件包含稳定 event_id、监控和方案版本、股票/市场/周期、K线及检测时间、条件数值、确认状态、来源、数据时间、分组、HTTPS图表地址。delayed 表示相对收线延迟发现。

`integrations/openclaw/scan.py` 为可运行示例：health、watchlists、create-six-red、events、poll。已安装到 OpenClaw `~/.openclaw/workspace/skills/nas-market-scanner`。示例只输出文案，不向任何人发送消息。生产通知应使用持久 outbox，投递成功后推进游标，接收方以 event_id 去重；单靠 HTTP 轮询不能保证外部消息系统的 exactly-once。

## 数据口径与限制

- OpenD 的沪/深市场分布返回同一个全 A 股范围，仅取一次。涨跌停区间不重复计入家数。其分布接口不提供行情时间或独立证券总数，因此 trade_date/data_time/coverage 明确为 null，抓取时间另列。平盘可能包括停牌/无成交；不能视作纯活跃普通股宽度。
- A股梯队/炸板/晋级来自东方财富各池，逐页读取并去重，按请求交易日及上游最新可用日期分别记录。涨停制度由上游池判定，不拿统一10%阈值推断 ST/创业板/科创板。炸板率分母是去重炸板与封板并集，昨日反馈只纳入今日有效快照。两家来源的数量可能不同，不能混用分母。
- 美股 MA20/MA50/新高新低统计明确使用 NAS 关注样本，非全市场或标普500。新高新低为前252根日线收盘极值，使用不复权数据，拆股等公司行动可能影响结果；窗口不足单独缩小分母。行业扩散使用11行业 ETF，SPY/RSP 是代理比较，不伪称板块指数。
- US .IXIC/.SOX 当前 OpenD 返回“不支持美股指数”，保留为失败，不替换成 ETF 或零值。
- A股没有独立 theme 热力图，使用完整 concept 概念题材目录；OpenD OTHER 不能作为目录查询参数。美股 theme 有27类，其中包含ETF类别，应按数据源实际含义理解。
- 扫描无数据、指标预热不足、过期缓存、停牌导致缺少应有K线均作为失败，不算命中。当前扫描与图表一致使用常规时段、不复权；盘前/盘后扫描尚未开放。
- 本次没有发送外部通知，没有提交任何交易订单。


## API 管理页面与历史条件（2026-11-16 更新）

在顶部选择 **API 管理**，或访问 `https://192.168.101.103:8443/chart?view=api`，使用现有平台密码登录。HTTP 页面仅提供安全入口链接。
页面汇总行情服务和 HTTPS 服务实际 OpenAPI，支持搜索、分类、查看参数/请求体/响应及下载两个 schema；另列 WebSocket。目录加载失败会显示错误，不会冒充完整目录。
凭证默认只读，可选择 `manage` 和 `tokens`；创建时仅显示一次新密钥，列表不包含密钥或哈希。撤销立即生效。现有管理员凭证和 OpenClaw 凭证不会自动更换。画线沿用原独立凭证，交易接口沿用网页登录与 CSRF。
浏览器管理接口 `/api/trade/api-management/inventory`、`/tokens`、`/tokens/{id}` 仅在 HTTPS 服务注册，受现有登录和写入 CSRF 保护。页面不提供交易请求执行器。

所有指标条件均可使用以下字段（不是六脉专用）：

| 字段 | 定义 |
| --- | --- |
| `Rule.offset` | 条件结束位置距对齐决策根几根，0 当前、1 上一根，0–250 |
| `Operand.offset` | 单个指标输出再向前取几根，0–250；可比较当前价格与历史价格乘指定倍数 |
| `temporal=current` | 在结束位置满足比较即可；`eq/gte` 等可持续满足，`reach/cross_*` 为变化条件 |
| `temporal=streak` | 结束位置连续满足根数在 `min_count` 与可选 `max_count` 之间，包含两端 |
| `temporal=all/any/count` | 截至结束位置的最近 `window` 根全部/至少一次/指定次数满足 |
| `min_count/max_count` | 连续根数或窗口次数的下限/上限；上限 null 表示不限 |
| `window` | 历史窗口 1–250 根；不是方案的 `lookback` |

方案 `lookback` 在最近几根决策中寻找命中；上述历史条件在每个决策时点单独计算，跨周期先按当时已完成 K 线对齐，再应用偏移。日线根数指交易日。数据不足、缺失或连续段起点无法证明时，不产生有效命中；无上限的连续条件可以凭已知下界证明满足。

例：六红第二、第三根：`left=SIXPULSE.REDS, op=eq, right=NUMBER(6), temporal=streak, min_count=2, max_count=3`。
例：短暂三绿恢复六红，AND 三条：今天红灯数=6；上一根绿灯数>=3且连续恰好1根；上两根红灯数=6且连续至少3根。界面提供可编辑示例；六红不代表价格必然上涨，需另加价格条件，例如 `PRICE.close > PRICE.close(offset=20,scale=1.05)`，表示较20根前上涨超过5%。

监控 `event_mode` 默认 `on_enter`（从不满足变为满足），可设 `each_bar`（每根满足的 K 线各一次）。若想第二、第三天都通知，使用连续2–3根条件并选 `each_bar`。同根轮询、重试和重启不重复产生同一状态事件；盘中预览与收盘确认有独立事件状态。已有监控仍固定原方案版本，编辑方案不自动改变运行中的监控。


## 异步任务、时间记录与结果复用（2026-11-19）

POST /api/v1/plans/{id}/run 先持久创建任务，再在后台解析名单和读取行情。新任务通常返回 HTTP 202 和 job_id，不等待股票名称或板块成分接口完成。保留原 id、plan、status、done、total 字段。

请求体可省略，也可传 {"request_id":"同一次请求的固定编号","force":false,"reuse_seconds":86400}。Idempotency-Key 请求头与 request_id 等效，两者同时提供时须相同。相同编号重试始终返回同一任务；编号被用于不同参数时返回 409。参数相同且正在排队、执行或暂停时复用该任务。默认复用过去 24 小时内 completed/partial 结果，force=true 或 reuse_seconds=0 可显式刷新已结束结果。监控按自身配置产生新轮次，不受手动扫描的默认复用窗口限制。

GET /api/v1/plans/{id}/results 读取已有结果，不触发扫描。返回 ready、fresh、status、job_id、age_seconds、result_complete、retry_after_seconds、参数快照、命中和失败记录。max_age_seconds 默认 86400，可由调用方指定。partial 已结束但不完整，ready=true、result_complete=false。queued/running 等状态 ready=false；暂停任务 needs_action=true，不会自行继续。

GET /api/v1/jobs 支持 market、plan_id、status 和 limit（1–100）过滤。历史按创建时间排序，包含方案名称、版本、创建/开始/完成时间、进度百分比、队列位置、当前阶段、当前标的和周期。GET /jobs/{id}?summary=true 保留参数和进度，省略逐标的结果与名单，适合短请求轮询。

POST /jobs/{id}/pause、/resume、/cancel 分别暂停、继续和取消。正在执行时先返回 pausing/cancelling，当前数据请求返回后停止；排队任务立即生效。继续时跳过已完成的标的/周期并排在待执行队列末尾。controls 记录操作和 UTC 秒时间戳。服务重启保留排队任务，最近因重启中断的任务会沿用原编号恢复；其他 interrupted 任务允许用原编号继续。

新计划默认 live=true；显式 live=false 的历史方案和监控快照继续使用其原配置。盘中预览只使用当前时点已经可见的数据，历史决策继续避免使用未来的未收线高周期数据。

每日定时配置例子如下，schedule.timezone 是 IANA 时区，weekdays 的 0 表示周一、6 表示周日。

```json
{
  "plan_id": "已有方案编号",
  "enabled": false,
  "trading_only": true,
  "schedule": {
    "kind": "daily",
    "times": ["09:35", "14:50"],
    "timezone": "Asia/Shanghai",
    "weekdays": [0, 1, 2, 3, 4]
  }
}
```

每日每个时点只提交一次；错过多个时点时补最近一个时点。trading_only=true 时按方案市场的实际交易日过滤。用户启用配置后，NAS 自行排队预扫描，OpenClaw 使用 results 读取。接口能力更新不会改写现有定时时间或创建新监控。

固定名单监控（follow_watchlists=false）在首个后台任务解析名单时保存 targets 快照，配置接口本身不等待板块目录。任务完成或取消后，下一轮仍按该监控的定时配置计算。

GET /jobs 的响应包含 has_more 和 next_cursor，用 cursor 读取更早历史，即使创建时间相同也不会漏记录。PUT /monitors/{id} 按提供的字段更新定时配置，其他配置保留；显式提供 plan_id 会采用该方案当前版本，已创建任务仍使用原快照。

范围预览和新任务的名单解析优先使用 NAS 名称缓存，缺失名称时保留代码。名称补查不阻塞任务建立。页面在选定有效范围后即可提交任务，名单预览仍可继续加载。


## 完整任务审计（2026-11-20）

新任务提交时保存 scope_snapshot：当时纳入与未纳入的分组名称/编号、每组代码、缺失指定分组、空分组及快照时间。排队任务按该快照解析关注名单，后续编辑分组不会改写原任务范围。固定名单监控继续沿用自身冻结名单。

execution_plan 保存本次实际使用的全部条件和展开后的默认参数，包括输出线、指标周期、倍数、指标/条件偏移、跨周期、历史窗口/次数、AND/OR、lookback、live；固定公式记录版本摘要。原始 plan 也保留。source=browser 表示页面人工提交，api 表示 API 提交，monitor 表示 NAS 调度器触发；API 来源本身不能证明来自哪个人或外部定时脚本。复用任务保留原任务来源和创建时间，不伪造为本次新执行。

历史列表提供 condition_count、scope_summary 和 source；完整快照通过 GET /jobs/{id} 查看。summary=true 省略大名单快照，保留条件和范围摘要。页面可以导出本次记录。旧记录没有保存的分组/默认参数/来源明确标为未记录，不根据当前配置补写。指标数据不足会标明具体条件、指标输出和周期。

任务历史使用独立精简索引保存，避免轮询时重新解析全部逐标的结果；旧任务在首次启动时迁入索引，原始记录保留。

提交回执不明确但已保存 request_id 时，可用只读 GET /api/v1/requests/{request_id} 找回已接受的 job_id 和进度；未曾接受该编号返回404。该接口不创建或重提扫描，适用于只读取结果的续查任务。

