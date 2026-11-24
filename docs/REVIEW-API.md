# 每日复盘 API

基础地址为 `https://192.168.101.103:8443/api/v1/review`。NAS 中现有可信容器网络可使用 `http://market:8000/api/v1/review`。每个请求包含 `Authorization: Bearer <token>`，带请求体时使用 `Content-Type: application/json`。在 HTTPS 入口的「API 管理」可以签发、撤销复盘凭证并下载 OpenAPI。`review:read` 用于查询，`review:write` 用于写入。OpenClaw 同步通常需要两项。

每个请求指定 `market=CN` 或 `market=US`。日期采用 `YYYY-MM-DD`，A 股按北京时间，美股按美东日期。周一至周日为一周，周接口可传当周任一天。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /dashboard?market=CN&day=2026-11-18` | 当天日记、纪律、周统计、历史索引和上周重点 |
| `GET /rules?market=CN&active=true` | 查询纪律及版本，`active` 可省略 |
| `POST /rules?market=CN` | 新增纪律，提交 `title` |
| `PUT /rules/{id}?market=CN` | 提交 `title`、`active`、`revision`，用于改名、启停 |
| `GET /days?market=CN` | 按日倒序分页，支持 `start`、`end`、`before`、`limit` |
| `GET /days/{day}?market=CN` | 读取单天完整记录及当前版本。没有记录返回 404 |
| `PATCH /days/{day}?market=CN` | 新建或部分更新，保留未提交字段 |
| `PUT /days/{day}?market=CN` | 用提交的完整内容替换日记 |
| `GET /weeks/{day}?market=CN` | 读取当周总结、违规统计和上周重点 |
| `PUT /weeks/{day}?market=CN` | 保存周总结，可填 `focus_rule_id`、`action`、`summary` |
| `GET /export?market=CN` | 导出该市场全部纪律、日记和周总结 |

列表响应的 `items` 包含记录。首选传 `next_before` 作为下一页 `before`，返回 `null` 表示读完。`limit` 默认 20，范围是 1 到 100。`start`、`end` 包含边界，`before` 不包含该日。

日记可写字段为 `traded`、`context`（复盘正文）、`reason`、`lesson`、`plan`、`violations` 和 `symbols`。在正文里用 `[[SH.600519|贵州茅台]]`、`[[SZ.000001]]`、`[[US.AAPL|苹果]]` 引用标的。一篇可包含多个引用和多段内容。日记响应中的 `mentioned_symbols` 按出现顺序列出本市场引用，自动去重，供读取。正文引用随文字变更而更新。

`violations` 写入纪律 ID 数组，读出带名称快照的对象。独立标的备注仍可通过 `symbols` 写入，例如 `[{"symbol":"SH.600519","name":"贵州茅台","note":"观察回踩"}]`。PATCH 省略字段会保留现值，数组按整体替换。追加段落时先读取正文和 `revision`，保留其他段落后提交。

每日或每周创建时传 `revision: 0`。更新前读取保存版本并提交对应 `revision`。成功响应返回新的 `revision`。例如 `PATCH /days/2026-11-18?market=CN` 可提交以下内容。

```json
{"revision":0,"traded":true,"context":"[[SH.600519|贵州茅台]] 等回踩。\n\n[[SZ.000001|平安银行]] 继续观察。"}
```

版本变化会返回 409。遇到冲突或写入超时，先重新读取现值并核对是否已经同步，再决定是否重试。401 表示凭证缺失、无效或已撤销，403 表示缺少权限，422 表示字段或格式无效。写入不会调用交易服务。

## 交易档案

以下路径接在原有 `/api/v1/review` 后，沿用 `review:read` 和 `review:write`。浏览器在「每日复盘 → 交易档案」使用相同记录。持仓、交易和导出沿用现有复盘入口的可信内网访问范围；HTTPS 图表入口继续使用登录会话。

| 方法与路径 | 用途 |
|---|---|
| `GET /ledger/book` | 按市场查询。可按正股代码 `symbol` 筛选，包含其期权。计划和成交用 `limit`、`offset`、`next_offset` 分页；持仓按账户和证券列出 |
| `POST /ledger/plans`、`GET/PUT/DELETE /ledger/plans/{id}` | 创建、查询、修订及删除计划；详情含历次版本和关联成交 ID。有关联成交或复盘引用时删除返回 409 |
| `PUT/DELETE /ledger/plans/{id}/fills/{fill_id}` | 关联或解除已有成交。请求体传成交的 `revision`；关联时验证标的、方向、成交时间与当时生效的计划版本，成功后返回更新的成交 |
| `POST /ledger/fills`、`GET /ledger/fills/{id}` | 手动补录、导入成交或查询原始记录；美股补录需 `manual_confirm: true` |
| `PUT /ledger/fills/{id}/review` | 保存执行情况、质量、心得及计划关联。用 `group_ids` 合并复盘同账户、同标的的分笔，`group_revisions` 传入已核对的其他成交版本 |
| `POST /ledger/positions` | 导入完整账户持仓或局部截图，保留来源与记录时间；完整空列表表示已确认空仓 |
| `GET /ledger/opend`、`POST /ledger/opend/sync` | 查美股实盘同步状态、请求刷新或按 `start`、`end` 补拉历史。返回排队状态后可继续查询结果 |
| `POST /ledger/reconcile` | 传入 `manual_id` 和 `opend_id` 核对同一笔成交，原 ID 仍可用于引用 |
| `GET /ledger/backlinks` | 传入 `kind=plan` 或 `kind=fill` 及 `id`，读取引用它的日记与周总结 |

所有创建计划或成交的请求应指定稳定的 `request_id`。复盘正文用 `[[plan:32位档案ID|简称]]` 或 `[[fill:32位档案ID|简称]]` 引用档案。保存时校验市场并更新反向引用。导出格式第 2 版在原有字段上增加 `ledger`，包含计划历史、成交及其复盘、当前持仓和账号快照时间。完整请求示例见 [OpenClaw 交易档案说明](../integrations/openclaw/review/SKILL.md)。


## 图表中的结构化交易计划

A 股、美股图表工具栏提供「创建交易计划」，沿用 `/ledger/plans` 的创建、修订、查询和历史版本接口。周期支持 `1m`、`5m`、`15m`、`30m`、`60m`、`120m`、`240m`、`1d`、`1w`、`1mo`。每个入场和出场条件可分别选择周期。状态新增 `draft`，仓位和防守价尚待完善时可传 `size:""`、`stop:null`。

`details` 保存结构化条件、自由文字、风险安排及行情参考快照。`details.levels` 可保存 `previous_high`、`previous_low`、`platform_high`、`platform_low`、`gap_up`、`gap_down`、`take_profit`，均为可选正数价格。界面支持生成给 Agent 的任务和导入 Agent 返回的 JSON 草稿。现有 OpenClaw `add-plan`、`update-plan` 客户端可原样提交该字段，`request_id`、`revision` 的使用方式沿用现有约定。

```json
{
  "symbol": "SH.600398",
  "period": "1d",
  "side": "BUY",
  "status": "draft",
  "trigger": "日线六红，结合手写理由观察",
  "size": "",
  "stop": null,
  "request_id": "消息编号-plan-1",
  "details": {
    "version": 1,
    "title": "日线共振、分钟线防守",
    "mode": "regular",
    "author": "agent",
    "entry": {
      "join": "all",
      "items": [{"id":"entry-1","source":"SIXPULSE","period":"1d","signal":"reds","threshold":6,"params":{},"confirmation":"close"}]
    },
    "exit": {
      "join": "any",
      "items": [{"id":"exit-1","source":"SIXPULSE","period":"15m","signal":"greens","threshold":3,"params":{},"confirmation":"close"}]
    },
    "entry_note": "保留用户自己的入场理由",
    "exit_note": "记录减仓、退出等安排",
    "risk": {"entry_price":null,"qty":null,"budget":null,"max_position_percent":null,"defense_source":"待确定","note":"待完善风险考虑"},
    "notes": "其他判断和依据",
    "references": []
  }
}
```

条件支持 `SIXPULSE`、`BOLL`、`SMA`、`EMA`、`BBI`、`VWAP`、`MACD`、`RSI`、`PRICE`。六脉使用 `reds`、`greens` 和 1–6 的 `threshold`；MACD 使用 `bullish`、`bearish` 比较 DIF 与 DEA；其他来源使用 `above`、`below`。布林需填写 `line:"upper"`、`"mid"` 或 `"lower"`，RSI 和指定价格通过 `threshold` 设置阈值。`confirmation` 可选 `close` 或 `live`。各条件的 `id` 在整份计划内保持唯一。

参数在保存时补齐并记录为快照。`references` 的每项为 `label`、`price`、`period`、`bar_time`，其中 `bar_time` 是该参考值使用的 K 线时间戳。六脉及选定条件的试算价固定已完成 K 线，当前试算收盘价可以扩展已出现的最高、最低价；均线、布林的当前线位另行标记。跨周期参考分别计算，防守价由用户点选或填写，保存后的 `stop` 为当次选定价格。

旧客户端省略 `details` 修订计划时，系统保留已有结构化内容；同时修改 `trigger` 会更新入场补充文字。显式传入 `details:null` 可清除结构化内容。历次版本与成交时的计划快照保留各自的原值。

