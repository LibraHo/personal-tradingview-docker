---
name: nas-market-review
description: 使用已有 NAS Market 复盘 API 记录 A 股与美股交易计划、正股／期权成交、持仓截图、逐笔心得和日周复盘，查询 OpenD 同步状态和双向引用。
---

# NAS Market 每日复盘

用户要求记录、更新或同步一篇真实交易复盘时，使用 `python3 {baseDir}/review.py` 写入 NAS Market。在用户要求起草、修改文案或举例时，先按其要求处理文本。用户只读查询时使用读取命令。

需要通过 OpenClaw 执行时，优先使用 `openclaw_direct.gateway_exec`（如果提供），调用上述客户端。该客户端只对 NAS Market 的固定 Docker 内网地址 `http://market:8000` 直连。遇到 502 时先用它执行 `rules --market CN` 或 `rules --market US` 诊断，避免把其他网络工具的失败当成复盘服务故障。

1. 从用户内容识别市场和日期。A 股用 `CN`、北京时间，美股用 `US`、美东日期。两个市场都有记录时分别同步。用户只说今天时，可省略 `--day`。市场、日期确实无法判断时再询问。
2. 使用 `rules --market CN`（或 `US`）读取纪律，选取 `active: true` 的项目。仅将用户明确说违反的纪律匹配成 `violations` ID 数组。用户未提供时省略字段，明确没有违规才传 `[]`。匹配不确定时可保留原文到 `reason` 并向用户说明。避免自行创建或停用纪律。
3. 日记写进 `context`（复盘正文），涉及几只股票就按正文需要分段。把标的引用放在对应的句子或段落里，格式为 `[[代码|名称]]` 或 `[[代码]]`。例如 `[[SH.600519|贵州茅台]] 等回踩。\n\n[[SZ.000001|平安银行]] 继续观察。` 美股写法如 `[[US.AAPL|苹果]]`。有单独的违规原因、心得或改进动作时，分别用 `reason`、`lesson`、`plan`。只有需要独立标的备注时才写 `symbols` 数组。读出的 `mentioned_symbols` 来自正文引用，供查询使用。
4. 执行 `sync-day --market CN --day 2026-11-18`（使用实际市场、日期），通过标准输入提供 UTF-8 JSON。追加复盘段落或修改某只股票的段落时，先用 `day` 读取 `context` 和 `revision`，保留其他段，调用时加 `--revision` 并传入刚读取的版本。若追加 `violations` 或独立 `symbols` 备注，也要先读取、合并去重。省略的字段会保留现值。
5. 收到成功结果后告知用户同步的市场、日期与页面入口。若返回 409，读取最新版，核对冲突字段，避免重试覆盖。401、403 或连接失败表示还没有完成同步。

读取命令还有 `dashboard`、`days`、`week` 和 `export`。用户主动要求修改交易纪律或保存每周总结时，使用同目录 `review.py` 的 `call(path, market, method, body)`，先读取当前版本。纪律新增 `POST rules`，编辑或停用 `PUT rules/{id}`，周总结使用 `PUT weeks/{day}`，提交 `revision`、`focus_rule_id`、`action` 和 `summary`。

凭证从 `~/.openclaw/credentials/nas-market-review-token` 文件读取，权限为 `review:read` 和 `review:write`。不要读取给用户看、打印、放入链接或发给其他服务。NAS Market 页面入口为 `http://192.168.101.103:8088/?view=review`。

## 交易档案

以下命令沿用同一个 `review.py`、API 和 token，每次均指定 `--market CN` 或 `--market US`。写入命令通过标准输入接收 UTF-8 JSON。读写成功以 API 回执为准；保留返回的档案 ID。以下字段示例中的价格、代码和时间仅用于说明格式。

成交截图有本地附件时，逐行使用 `add-fill --image 原附件路径 --row 1`（下一行填 2），或者传附件的 `--image-sha256`。客户端从原图、账户和行号生成稳定请求编号；同一附件在另一条消息里重发也能识别。行号取自原图顺序，重复打开时保持一致。不同截图间重叠的成交优先按券商成交编号核对。截图没有编号且无法确认是同一笔时，先查询已归档明细再核对。

- 用户说「复盘刚才那笔美股」时，用 `book --market US --symbol US.AAPL` 查询原始正股和期权成交。按账户、完整合约、方向和时间核对。尚未出现时用 `sync-opend --market US` 请求刷新，再用 `opend --market US` 查询状态；同步完成后重读。若多笔仍无法区分，让用户从候选中选择。默认使用已同步记录；仅在用户明确要求补录美股时用 `add-fill --market US --manual`。补拉历史用 `sync-opend --market US --start YYYY-MM-DD --end YYYY-MM-DD`，单次区间最多 90 天。
- 交易前用 `add-plan`。例如 `{"symbol":"SH.600519","period":"15m","side":"BUY","trigger":"回踩后收回前高","size":"交易后目标仓位 10%","stop":1360,"status":"active","details":{"levels":{"previous_high":1500,"previous_low":1300,"platform_high":1480,"platform_low":1380,"gap_up":1450,"gap_down":1350,"take_profit":1650}},"request_id":"用户消息唯一编号-plan-1"}`。`details.levels` 中前高、前低、前期平台上下沿、前期向上／向下缺口和止盈位均为可选正数价格；没有可靠依据时省略，不推测填值。前期平台上沿不能低于下沿。用 `plan --id ID` 读最新版本，修订时用 `update-plan --id ID` 提交计划字段和当前 `revision`。修订请求应保留读出的其他计划字段与 `details`，避免覆盖已有条件、价位和文字。记录仓位单位和止损对应的价格标的。用户说明未触发时可以标记 `skipped`。
- 用户明确要求把已有成交关联到计划时，先用 `plan --id 计划ID` 和 `fill --id 成交ID` 读取最新记录，核对市场、标的、方向、成交时间和计划当时是否生效，再用 `link-plan-fill --market CN --id 计划ID --fill-id 成交ID`，从标准输入传 `{"revision":成交当前版本}`。解除关联用 `unlink-plan-fill` 和同样的参数与请求体。两者返回更新后的成交与新 `revision`；409 时重读核对，不能盲目重试。已有逐笔复盘的正文不因此删除。
- 用户明确要求删除计划时，先用 `plan --id ID` 和 `backlinks --kind plan --id ID` 核对版本、关联成交及日周复盘引用，再使用 `delete-plan --market CN --id ID`。删除会移除该计划的全部版本；有关联成交或复盘引用时 API 返回 409，应先按用户意图处理关联或引用，不能绕过限制。删除命令不读取标准输入。
- A 股成交回报用 `add-fill`。例如 `{"account":"A股主账户","symbol":"SH.600519","code":"SH.600519","kind":"stock","side":"BUY","qty":100,"price":1380,"at":"2026-11-20T10:12:00+08:00","broker_id":"券商成交编号","request_id":"用户消息唯一编号-成交行1"}`。截图导入传 `source:"screenshot"`。有事前计划可传 `plan_id`。期权填写完整合约 `code`、标的 `symbol`、`kind:"option"`、`expiry:"YYYY-MM-DD"`、`strike`、`right:"C"` 或 `"P"`；数量为张。美股时间传实际美东偏移，区分夏令时和冬令时。账号使用与 OpenD 已归档记录相同的账户标识。每次重试沿用原请求编号；分笔成交即使同价同秒也保留各自的真实成交编号。
- A 股持仓截图用 `sync-positions`。例如 `{"account":"A股主账户","as_of":"2026-11-20T15:00:00+08:00","complete":false,"rows":[{"symbol":"SH.600519","code":"SH.600519","kind":"stock","qty":100,"cost":1380}]}`。使用截图时点，核对市场、账户和可读数量；成本读不清可省略。只有明确覆盖该账户全部持仓时才传 `complete:true`；截屏中没有出现的行可能在下一页。成交明细截图按原始行导入成交，持仓变化只更新持仓。截图来源缺少辨别两笔同样成交的依据时先核对，避免换一个请求编号重建记录。
- 查看 `fill --id ID` 后用 `review-fill --id ID` 保存执行情况、交易质量和心得；填写当前 `revision`，可以传 `plan_id`，可用 `group_ids` 关联同一操作的其他成交；`group_revisions` 传入参与或移出的其他成交 ID 和已读版本。记录事实依据，仓位、止损触发顺序无法确定时标记待核对。先看最新复盘，已有内容按用户要求保留。补录与 OpenD 都已存在且属于同一成交，核对账户、合约和券商明细后使用 `reconcile`，传 `{"manual_id":"手工档案ID","opend_id":"OpenD档案ID"}`。保留其他相似分笔。
- 日记正文或周总结中写入 `[[plan:档案ID|计划简称]]`、`[[fill:档案ID|成交简称]]`，用服务端返回的真实 ID 替换占位。可在同一篇中引用多笔成交。追加或移除日记引用时用 `day` 读取最新版，保留其他正文，并通过 `sync-day --revision 当前版本` 写回。周总结用 `week` 读取，再用原有周更新接口保存。反查使用 `backlinks --kind plan --id ID` 或 `backlinks --kind fill --id ID`。移除正文标记并保存，也会同步移除反向引用。
- `book` 按标的返回计划、成交、持仓，分页用 `--limit`、`--offset` 和返回的 `next_offset`；按完整合约查看时核对每行 `code`。断网、版本冲突或同步失败时先查询当前状态，再决定是否重试。

查询计划每日点位、止损和止盈触及记录使用 `plan-daily --market CN --id <计划ID> --limit 30`。有下一页时，以返回的 `next_before` 传入 `--before`。null 表示尚无可判定结果。

逐根收盘记录、失败原因和重试时间用 `plan-bars --market CN --id <计划ID>`。跟踪只在计划显式配置 tracking_period 且为进行中时启用。
