# OpenClaw 画线 API

OpenClaw 通过 HTTP 调用 NAS Market，而非控制浏览器或连接交易接口。API 写入现有 SQLite 工作区；打开相同股票及周期的网页约 3 秒内同步。网页关闭时可继续创建对象，下次打开会读取。API 不会触发行情订阅或下单。

## 本 NAS 的连接配置

- HTTPS 基础地址：`https://192.168.101.103:8443`，画线路径为 `/api/drawings/...`。
- 仅 NAS 内部可信网络也可使用 `http://192.168.101.103:8088`。
- Token 自动生成并保存在 NAS 项目目录的 `data/drawing-api-token.txt`，权限为 600。它不是 moomoo 交易密码，也不是网页登录密码。不要上传到 GitHub。
- 也可在 HTTPS 看盘页登录后，点击顶栏“数据与缓存”→“OpenClaw 画线接入”→“查看画线 Token”，再点击“复制 Token”。无需解锁实盘；普通 HTTP 页面不展示密钥。
- 可用 `DRAWING_API_TOKEN_FILE` 改密钥文件位置，或通过私密环境变量 `DRAWING_API_TOKEN` 覆盖（至少 32 字符）。轮换密钥文件后下一次请求即使用新密钥；环境变量覆盖值需重启服务。
- API 采用 `Authorization: Bearer <画线Token>`。HTTPS 自签名证书请将 NAS `trade-tls/cert.pem` 作为信任证书，不建议跳过验证。

提供的客户端只有 Python 标准库依赖：`integrations/openclaw/draw.py`。OpenClaw 需要 Python 3/执行工具权限及到上述地址的网络访问。

在 OpenClaw 容器中准备两个只读文件。例如添加到现有 OpenClaw 服务的挂载（替换实际 NAS 路径；不要新建第二个 OpenClaw 服务）：

```yaml
volumes:
  - /你的NAS目录/nas-market/data/drawing-api-token.txt:/run/secrets/nas_market_drawing_token:ro
  - /你的NAS目录/nas-market/trade-tls/cert.pem:/run/secrets/nas_market_ca.pem:ro
  - /你的NAS目录/nas-market/integrations/openclaw:/opt/nas-market-drawings:ro
environment:
  NAS_MARKET_URL: https://192.168.101.103:8443
  NAS_MARKET_DRAWING_TOKEN_FILE: /run/secrets/nas_market_drawing_token
  NAS_MARKET_CA_FILE: /run/secrets/nas_market_ca.pem
```

确保 OpenClaw 的运行用户可读取密钥挂载；如它使用非 root 用户，使用只对该用户可读的秘密副本，避免把 Token 改为全员可读。将 `integrations/openclaw/SKILL.md` 和 `draw.py` 放入 OpenClaw 实际技能目录（或让 Agent 读取上述目录），按其现有部署方式加载。本文不自动修改或重启 OpenClaw。

首次验证：

```sh
python3 /opt/nas-market-drawings/draw.py capabilities
python3 /opt/nas-market-drawings/draw.py list --symbol US.SNDK --period 5m
```

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/drawings/capabilities` | 类型、周期、限制及版本 |
| GET | `/api/drawings/objects?symbol=US.SNDK&period=5m` | 查询对象、revision、整体显隐；筛选参数可省略 |
| POST | `/api/drawings/objects` | 新增水平线、趋势线、fib |
| PATCH | `/api/drawings/objects/{id}?symbol=US.SNDK&period=5m&kind=horizontal` | 修改指定对象 |
| DELETE | 同上 | 删除指定对象 |
| PUT | `/api/drawings/visibility` | 当前股票和周期的整体隐藏/显示 |

POST JSON 示例：

```json
{"symbol":"US.SNDK","period":"5m","kind":"horizontal","id":"agent-sndk-level-130","price":130,"color":"#ef5350","lineWidth":2,"lineStyle":2,"visible":true}
```

趋势线：

```json
{"symbol":"US.SNDK","period":"5m","kind":"trend","id":"agent-sndk-trend","points":[{"time":1793107800,"price":120},{"time":1793111400,"price":125}],"extend":"right","color":"#e3b76b"}
```

斐波那契：

```json
{"symbol":"US.SNDK","period":"5m","kind":"fib","id":"agent-sndk-fib","points":[{"time":1793107800,"price":120},{"time":1793111400,"price":130}],"levels":[0,0.382,0.5,0.618,1,1.272,1.618],"levelColors":{"0.618":"#00cc88","1.618":"#aa77ff"}}
```

上述端点仅为接口格式示例，不是行情分析或建议价位。时间单位是 Unix **秒**，不是毫秒。周期为 `1m/5m/15m/30m/60m/1d/1w/1mo`。A 股使用 `SH.600584`、`SZ.000001` 等代码。`lineWidth` 为 1–4；`lineStyle` 为实线 0、点线 1、虚线 2。单对象 `visible:false` 隐藏自身，整体 `hidden:true` 保留各对象原有显隐。

PATCH 只传需要改动的字段；不能改变 id、股票、周期或类型。PUT visibility 的 JSON 为 `{"symbol":"US.SNDK","period":"5m","hidden":false}`。

每类每图最多 100 个对象，fib 最多 32 条比例（0–4.236）；工作区仍受 100 KB 容量限制。建议 Agent 创建稳定 id 以便重试；同 id 同内容返回原对象，不产生重复。可在修改请求中带 `If-Match: <revision>`；客户端对应 `--revision`。发生并发时返回 409，先重新查询再决定。

Web 保存使用画线版本检查，旧页面不会覆盖较新的 API 图形。如果同时编辑发生冲突，页面保留远端画线并提示重新操作。后台代理不能用画线 Token 访问交易接口、修改自选分组或读取交易密码。

客户端不会输出 Token。连接失败时先检查网络、只读秘密文件权限和 CA 证书；401 表示 Token 不匹配，409 表示对象或版本冲突，422 表示字段不正确。
