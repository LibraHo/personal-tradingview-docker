# NAS Market 交易计划的 Agent 接入研究

## 已实现的一键填表

图表和交易档案中的交易计划编辑器共用「一键填表」。A 股在「入场条件」选择指标或打板。按钮只补草稿空项，最终由用户点保存。未配置网关时使用本地条件和结构价位；配置后，文字字段交给现有 OpenClaw Agent，数值字段仍使用表内数据。打板模式填写首封、回封和炸板文字，保留空指标列表。

在 market 服务端配置 `OPENCLAW_BASE_URL`（网关私网地址，可带 /v1）和 `OPENCLAW_GATEWAY_TOKEN`。可选 `OPENCLAW_AGENT_ID`，省略时使用该网关的默认 Agent。网关需启用 Chat Completions。只有点击时且存在空白文字字段才访问网关；网关超时、鉴权失败或内容无效时保留草稿。接口接收 POST /api/review/ledger/autofill?market=CN 或相应鉴权 API 路径。旧的手动 JSON 导入仍可用。

在安全看盘入口进入「设置 → AI 助手」，可选「服务端默认」「关闭 AI」或「OpenClaw」。全局配置由安全入口 GET / PUT /api/trade/agent-settings 管理，交易计划填表读取同一份配置。选择 OpenClaw 后填写网关 URL、凭证和可选的 Agent ID。凭证由 HTTPS 后端保存在服务端数据库，读取设置只返回是否已设置凭证。保存设置不会访问网关。「DeepSeek 直连」预留为不可选项。通过 OpenClaw 使用的模型沿用对应 Agent 的配置。

点击填表后显示等待条和已等秒数。展开「填表记录」可查询当前标的最近 30 次请求和失败原因，重试会产生新的编号。服务端 API 为 GET /api/v1/review/ledger/autofill/history?market=CN，可选 symbol 或 request_id。超出等待时间且服务端还没有完成记录时显示「结果待核对」。提交未得到确认的请求在本浏览器保留记录，查询时优先展示服务器结果。

## 原接入研究（含可选扩展）

在交易计划编辑器提供「让 Agent 完善草稿」。NAS Market 只接一个私网 OpenClaw Gateway，在网关里为计划分析配置专用 Agent。通过同一个入口可选择已配置的 DeepSeek 模型或 Codex 运行时。发布前需在目标 NAS 核验 OpenClaw 版本、可用插件、网关地址、鉴权和模型可用性。本次验证范围为本地源代码、Codex CLI 帮助及官方协议。

项目已有两个可复用入口。TradingPlanEditor.tsx 支持生成任务、导入 JSON 和检查标的、打板模式、价格与风险字段。integrations/openclaw/review 下的客户端支持 OpenClaw 主动读取和修订 NAS Market 中的计划。「页面发起分析并收到建议」需要增加反方向的任务调用。

| 方案 | 运行方式 | 适用条件 |
| --- | --- | --- |
| OpenClaw Gateway | NAS Market 后端向私网网关的 POST /v1/chat/completions 提交请求，用预配置的 Agent ID 指定计划助手 | 首选。集中维护凭证、模型选择和工具权限 |
| DeepSeek 直连 | 后端调用 Chat Completions，要求 JSON 输出，并校验返回字段 | 只需整理草稿、希望独立于 OpenClaw 时可用 |
| Codex | 支持相应插件的网关可通过 Codex app-server 执行；另一个选择是在已授权的执行节点运行 codex exec 并指定输出 Schema | 对输出格式有较强要求时可选。执行节点需有可用的 Codex 安装与登录 |

OpenClaw 的 Chat Completions 入口默认关闭。启用后，网关凭证具有操作员权限，适合保存在私网服务端；由后端固定可选 Agent，专用 Agent 仅获得完成草稿分析所需的数据与工具。DeepSeek 的 JSON 模式仍可能返回空白内容。Codex 支持通过 --output-schema 限制非交互运行的最终输出。[OpenClaw Gateway](https://docs.openclaw.ai/gateway/openai-http-api) · [OpenClaw 的 DeepSeek 配置](https://docs.openclaw.ai/providers/deepseek) · [OpenClaw Codex 运行时](https://docs.openclaw.ai/plugins/codex-harness) · [Codex 非交互执行](https://developers.openai.com/codex/noninteractive) · [DeepSeek JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)

## 编辑器交互

1. 管理员配置后端连接，在设置页手动测试。配置为空时页面显示「未配置」，打开页面、刷新行情、后台记录点位均不发起 Agent 请求。
2. 用户点击「分析当前草稿」。提交当前未保存的文字、市场、标的、策略类型、周期、自动识别的价位和时间，以及可选的近期跟踪摘要。配置云端模型时，页面在提交前显示接收方和数据范围。
3. 后端保存任务编号、草稿指纹、计划版本、选择的 Agent 及行情时间。耗时任务返回任务编号，关闭页面后可以按编号取结果。相同请求编号复用原任务，避免双击重复生成。
4. 返回按字段列出的「原文、建议、依据、待确认项」。首版允许建议入场说明、退出说明、风险说明和备注。已有结构点位、跟随规则、实际触及结果作为只读依据；打板计划继续使用封板、回封和失效条件。
5. 用户逐项采纳后填入当前草稿，再通过原有保存流程产生计划新版本。生成过程中被用户改过的字段单独提示冲突。未保存的新计划也支持分析。

## 任务失败与验收

| 情况 | 后端及页面行为 |
| --- | --- |
| 配置为空、凭证失效、指定模型不可用 | 显示具体原因和配置入口，等待人工处理 |
| 限流、服务暂时不可用 | 显示任务状态；尊重 Retry-After，限制重试次数，同一时间仅运行一份任务 |
| 已发送请求后超时、进程重启 | 保存「结果待确认」或「已中断」。优先按供应方任务编号找回结果；无法恢复时由用户决定是否重新生成，避免重复调用计费 |
| 返回空内容、无效 JSON、字段越界或标的不符 | 服务端与前端都校验。保留原草稿，提示哪些字段有问题，允许重新生成 |
| 生成期间发生修订、行情更新或另一设备保存 | 显示建议依据的版本和行情时间；合并前比对草稿指纹，保存时沿用 revision 冲突检查 |
| 行情缺失，或日汇总中有 K 线待确认 | 附上数据状态及缺失时段，建议里将相应结论列为待确认 |

建议首轮用合成计划验证三个完整场景：无配置时零次外部请求；有配置时点击一次得到可逐项采纳的建议；网关超时或返回错误后草稿仍可编辑。每个启用的模型都应在目标 NAS 上通过「提交 → 返回 → 校验 → 采纳 → 保存」验证。

