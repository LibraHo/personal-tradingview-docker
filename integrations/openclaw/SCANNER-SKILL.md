---
name: nas-market-scanner
description: Read existing NAS scan results first, track durable queued jobs and manage scheduled market scans when requested. No trading operations.
---

# NAS Market 扫描与监控

使用本目录 scan.py，通过可信 Docker 内网 http://market:8000/api/v1 访问 NAS Market。凭证从 ~/.openclaw/credentials/nas-market-scan-token 读取，只放在 Authorization 请求头。不要输出凭证或把凭证放入 URL。

## 用户要求扫描时，先提交，再按编号查询

用户明确要求执行扫描时，先用 python3 scan.py run <方案编号> 提交，持久保存 job_id、request_id、提交时间、参数和下次查询时间。按 retry_after_seconds 稍后 python3 scan.py job <任务编号>，完成后 python3 scan.py job <任务编号> --full。不要在一次问答中长时间轮询，也不要在查询期间再次提交。普通提交默认复用 24 小时结果；明确要求刷新时用 --force。定时任务按既定每轮刷新策略执行，不能把旧结果当新一轮扫描。

用户仅询问已有扫描结果时，python3 scan.py results <方案编号> 为只读查询，不启动扫描。

- ready=true 时注明扫描开始/完成时间、结果年龄和确认状态；fresh=false 时说明结果过期。
- status=partial 表示已结束但有失败项，要报告失败数量与原因，不得表述为没有信号。
- queued/running/pausing/cancelling 时报告任务编号、进度、排队位置和当前阶段，稍后查询原编号。
- paused 需要明确继续才推进；failed/interrupted/cancelled 如实报告。
- submission_unconfirmed 时保留 request_id；只读续查可 GET /api/v1/requests/{request_id} 找回已接受的 job_id。404 表示当前尚未查到回执，不创建任务。需要重试提交时仅由原提交入口沿用该 request_id，不另建方案或新请求编号。

## 完整扫描记录

新任务保存 scope_snapshot 和 execution_plan：当时纳入、未纳入、缺失和为空的分组及代码名单；全部条件、左右指标、输出线、参数默认值、倍数、偏移、条件周期和历史窗口。source 为 browser（页面人工）、api（API）或 monitor（NAS 定时监控）。API 来源不能据此直接推断是人工还是某个定时脚本。旧任务未记录的信息要明确标为未知，不用当前分组或当前默认参数补写历史。

## 提交后查询同一任务

python3 scan.py run <方案编号> 会迅速返回任务编号，NAS 后台完成名单解析和扫描。单次网络请求默认最多等待 15 秒。

同一方案默认复用 24 小时内的已完成结果。reuse_seconds 可在 API 请求中配置。需要刷新时显式使用 --force；正在执行或暂停的相同参数任务仍会复用。

同一次用户意图及网络重试应保留相同 --request-id。客户端会把未确认提交的请求编号保存在本地，重试复用该编号。submission_unconfirmed 只是没有拿到回执，不能据此另建方案、反复强制提交或宣称扫描失败。

- python3 scan.py jobs --market CN 查询任务历史。
- python3 scan.py job <任务编号> 读取进度、时间和参数。
- python3 scan.py job <任务编号> --full 读取全部逐标的记录。
- python3 scan.py pause <任务编号> 暂停任务。
- python3 scan.py resume <任务编号> 从已完成位置继续，并重新排队。
- python3 scan.py cancel <任务编号> 取消任务。

排队任务可立即暂停或取消。执行中的任务会先返回 pausing/cancelling，当前数据请求结束后停止。暂停的任务不占执行队列，后续任务继续。多个不同任务按提交顺序串行执行。所有任务都持久记录参数快照、创建/开始/完成时间、操作时间和已完成标的。

不要在一次问答中一直等待扫描完成或使用无限 poll 代替任务查询。未完成时如实说明进度，下一次继续查询原任务编号；读取进度和结果都不需要再次提交扫描。

## 按用户配置预扫描

通过 POST /monitors 配置现有方案。interval_seconds 控制间隔，schedule 可设置每日固定时间、时区和星期。用户指定何时扫描后再创建/更新相应配置。详细字段和例子见项目 docs/SCANNER-API.md。

已有监控可用 PUT /monitors/<编号> 修改指定字段，其余字段保留。例如 {"interval_seconds":1800,"schedule":null} 切换为每 30 分钟；{"schedule":{"kind":"daily","times":["09:35","14:50"],"timezone":"Asia/Shanghai","weekdays":[0,1,2,3,4]}} 设置每日时点。可用 enabled=false 保存配置草稿，再按用户给定的时间和启用状态提交。更新 body 显式包含 plan_id 时采用该方案的当前版本，已提交任务保留原参数快照。

GET /plans/<方案编号>/results 可以直接读取定时任务的产出，包含新鲜度和未完成状态。既有监控固定创建时的方案版本，使用 GET /monitors 核对 plan_version；方案更新后须明确配置采用新版本。

新方案默认 live=true，包含当前未收线 K 线。盘中结果明确标注 preview，收盘结果标注 confirmed。当前预览允许使用同一时点可见的未完成高周期，历史决策仍按原时点完成状态对齐。

## 事件与权限

python3 scan.py events 增量读取事件，包含盘中预览与收盘确认；只要确认事件时增加 --confirmed-only。不同消费者使用独立 --cursor-file。已有事件游标不会删除服务端事件。

客户端只输出文案。只有得到明确通知授权和接收目标，才使用通知渠道发送。生产投递使用 event_id 和持久 outbox 去重，投递成功后推进游标。不要提交交易订单。

## 自定义时间条件

不要把所有需求都转换成“刚达到”：`eq/gte/gt` 表示持续状态，`reach/cross_above/cross_below` 表示变化。`Rule.offset=1` 是条件周期的上一根；`Operand.offset` 是单个指标取过去的值。历史条件按原决策时点的完成周期对齐；当前预览使用当时可见的数据，再应用偏移。

- 六红第2、3根：`left={"name":"SIXPULSE","line":"REDS"},op="eq",right={"name":"NUMBER","value":6},temporal="streak",min_count=2,max_count=3`。
- 短暂至少三绿1根后恢复六红：AND 今日 REDS=6；offset=1 的 GREENS>=3，temporal=streak、min_count=max_count=1；offset=2 的 REDS=6，temporal=streak、min_count=3、max_count=null。
- 六红并不保证价格上涨。若要求涨幅，另加 `PRICE.close > PRICE.close(offset=20,scale=1.05)` 等明确条件，参数按用户需求配置。
- 任意指标可用 temporal=current/all/any/count/streak；window 为历史窗口根数，min_count/max_count 为次数或连续根数边界；方案 lookback 是寻找命中的决策根数，意义不同。
- 监控 event_mode 默认 on_enter（进入条件时一次）。用户要求第2、第3天都通知时用 each_bar（每根满足各一次）；重试不改变 event_id。已有监控固定原规则版本，不要静默改动。

全部接口与凭证管理页面：`https://192.168.101.103:8443/chart?view=api`，由用户使用现有平台密码登录。不要把管理员 token 放入前端或代理消息。
