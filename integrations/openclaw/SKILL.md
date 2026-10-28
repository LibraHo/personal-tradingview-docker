---
name: nas-market-drawings
description: Use the user's NAS Market API to create and manage chart lines and Fibonacci objects. Drawing only; no trading access.
---

# NAS Market 画线

当用户明确要求在 NAS 看盘平台画线、标注价位、修改趋势线或斐波那契时使用。需要执行 Python 3 的工具能力及到 NAS 的网络访问。此 API 不连接 OpenD、不读取交易密码、不提供下单能力。

配置环境变量：`NAS_MARKET_URL`、文件模式的 `NAS_MARKET_DRAWING_TOKEN_FILE`、HTTPS 私有证书时的 `NAS_MARKET_CA_FILE`。凭证通过受保护运行环境或操作者配置的私密文件读取，不在消息、日志、命令行参数或示例中输出 Token。不需要 moomoo 密码或交易平台密码。

如果用户已通过 OpenClaw 遮罩输入保存为 protected secret，则优先沿用该保护，不把它导出成文件。使用 OpenClaw 的 `gateway_exec` 路径继承 `NAS_MARKET_DRAWING_TOKEN` 的受保护占位符；Codex 原生 shell 不会自动获得它。需要已通过人工审核的网关出站代理及正确的目标主机绑定。未启用时保持阻断，不用明文或关闭 TLS 验证绕过。代理本身也必须信任 NAS 的证书，客户端信任成功不代表代理上游成功。

`python3 <skill目录>/draw.py diagnose` 只检查不带凭证的直连 TLS 和匿名接口 401，不读取 Token、不创建画线。正常命令保留网关注入的代理 CA（SSL_CERT_FILE），并叠加 NAS CA。也可在脚本旁放置仅含 `url`、`ca_file` 的 `connection.json`，不要在该文件存放 Token。

先运行 `python3 <skill目录>/draw.py capabilities` 检查连接，再通过 `list --symbol US.SNDK --period 5m` 查看当前对象及 revision。股票、周期、价格和端点必须来自用户要求或已确认的数据；不清楚的关键参数先询问，不虚构价位。修改/删除已有对象时先列出并匹配 id，保留其他对象。

创建使用稳定且独特的 id，例如 `agent-sndk-5m-resistance-130`。相同 id 和相同内容重试不会重复创建；同 id 内容不同会返回 409，应改用 update。需要防并发覆盖时传 `--revision`；409 后重新 list 核对，不盲目覆盖。

示例（仅在用户要求时执行）：

```sh
python3 <skill目录>/draw.py create --symbol US.SNDK --period 5m --kind horizontal --id agent-sndk-5m-level-130 --json '{"price":130,"color":"#ef5350","lineWidth":2,"lineStyle":2}'
python3 <skill目录>/draw.py update --symbol US.SNDK --period 5m --kind horizontal --id agent-sndk-5m-level-130 --json '{"price":131}'
python3 <skill目录>/draw.py visibility --symbol US.SNDK --period 5m --json '{"hidden":true}'
```

趋势线/fib 的 `points` 必须是两个 `{time:Unix秒,price:正数}`，时间不能相同。趋势线 `extend` 可为 none/left/right/both。fib `levels` 可包含 1.272、1.618 等 0–4.236 比例，`levelColors` 按字符串比例设色，例如 `{"0.618":"#00cc88","1.618":"#aa77ff"}`。

不写整个工作区设置，不调用交易接口，不修改自选分组或指标模板。返回成功后说明股票、周期、图形和价位；网页打开相同股票和周期时约 3 秒内同步，网页关闭时也会保留到 NAS。A 股使用 SH./SZ. 前缀，显示时切换到 A 股工作区。
