# NAS Market

轻量级、只读的美股与 A 股网页看盘终端。当前实时行情源是已有的 moomoo OpenD；服务不连接交易接口，也不提供模拟行情。Web 端使用 Lightweight Charts 5、React；服务端使用 FastAPI、WebSocket 与 SQLite。

## 官方能力与边界

| 项目 | 结论 |
| --- | --- |
| 全时段历史 K 线 | `request_history_kline(..., session=Session.ALL)`；仅美股、60 分钟及以下，OpenD 至少 9.2.4207。日线仅提供常规时段视图。 |
| A 股历史与实时 K 线 | 使用 `SH.600519`、`SZ.000001` 格式，按北京时间解析；请求使用 `Session.NONE`。A 股不使用美股的 `Session.ALL`；行情权限取决于 OpenD 登录账号。 |
| 全时段实时 K 线 | `subscribe(..., session=Session.ALL)`；仅支持 K 线、分时与逐笔等相应订阅类型。隔夜行情需美股 LV1 或更高权限。 |
| 单独隔夜 K 线 | `Session.OVERNIGHT` 不能用于历史 K 线或实时订阅；本项目从 `ALL` 数据中按美东时间筛选。 |
| 权限 | OpenAPI 行情权限可能与 moomoo App 不同。若权限不足，接口返回真实错误。某些证券可能没有隔夜交易或对应数据。 |
| 额度 | 订阅每只股票每种数据类型占 1 个额度；官方列出的基础订阅额度为 100，具体账号可能不同。历史 K 线配额按过去 7 天请求过的不同股票计算，不按周期重复计数。 |
| 频率 | 官方建议请求间隔至少 0.5 秒；服务对历史分页延迟 0.52 秒，缓存避免重复查询。 |
| 自选报价 | `get_market_snapshot` 可批量获取价格、昨收，以及美股盘前、盘后和隔夜独立价格与涨跌幅字段。只有 OpenD 实际返回数值时网页才显示对应标签；数值与实时性仍受账号权限及证券交易情况限制。 |

文档：[订阅](https://openapi.moomoo.com/moomoo-api-doc/en/quote/sub.html)、[历史 K 线](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html)、[市场快照](https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-market-snapshot.html)、[实时回调](https://openapi.moomoo.com/moomoo-api-doc/en/quote/update-kl.html)、[权限与额度](https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html)、[股票代码与时段](https://openapi.moomoo.com/moomoo-api-doc/en/qa/quote.html)。A 股 OpenAPI 行情权限可能因账户和 OpenD 登录地区而不可用，网页会显示真实错误。

## 部署

1. 确认 OpenD 已登录，版本至少 9.2.4207；确认 NAS 容器可访问 OpenD TCP 端口。例如 OpenD 在 `moomoo-opend_default` Docker 网络中，本项目可用容器名 `moomoo-opend:11111` 连接，无须公开 OpenD 端口。本项目只部署看盘网页，不会启动第二个 OpenD。
2. 在本目录复制 `.env.example` 为 `.env`，按实际 Docker 网络、容器名、端口和 RSA 私钥路径调整 `OPEND_NETWORK`、`OPEND_HOST`、`OPEND_PORT`、`OPEND_RSA_SOURCE`。Compose 将已有的私钥只读挂载进看盘容器；私钥不要提交到仓库。
3. 执行 `docker compose up -d --build`。局域网使用时可设置 `WEB_BIND=0.0.0.0`，然后访问 `http://<NAS局域网IP>:8088`。OpenD 本身仍只在 Docker 网络或宿主机回环地址可见。
4. 如通过极空间远程访问，在登录后的入口中添加 `http://<NAS局域网IP>:8088`。外层认证与 HTTPS 由远程访问服务提供；应用的 8088 端口在家庭局域网内仍是 HTTP，默认无独立密码。不要在路由器上将 8088 转发到公网。
5. `/api/status` 可查看 OpenD 连接及订阅数量；初次访问图表才会连 OpenD。若极空间远程访问不代理 WebSocket，历史图表可用，但实时推送需要另设支持 WebSocket 的 HTTPS 反向代理。

如果只在 NAS 本机的反向代理后使用，可把 `WEB_BIND` 改回 `127.0.0.1`。配置文件可设置缓存目录、默认自选股、活动订阅上限与历史天数。

Compose 默认使用 `Dockerfile.nas`，复用本机已有的 `moomoo-opend:local` Python 镜像与 SDK；新容器的入口已覆盖，只启动 FastAPI，不启动第二个 OpenD。`Dockerfile` 是可移植版本；没有该本地镜像时，把 Compose 的 `dockerfile` 改成 `Dockerfile`。

## 功能与交互

- 自选股快速切换、1/2/4 图、每图独立周期；选中图后顶部周期按钮作用于该图。
- 美股和 A 股为两个独立工作区，各自保存图表布局、周期、指标、自选分组和“精选”组。可创建、重命名、删除分组，在当前分组添加或移除股票；星标可快速加入或移出精选。旧版美股自选会迁入美股精选组。
- 左侧按“工作区切换 → 自选分组 → 组内股票”排列。股票行展示 OpenD 快照当前价、相对昨收涨跌幅、美股盘后及隔夜涨跌幅（若有）。当前分组每 20 秒批量刷新一次；浏览器页签隐藏时暂停刷新，关闭网页后不再请求快照。后端对相同股票组合做 15 秒缓存。
- 1m、5m、15m、30m、60m、日线；全时段、盘前+盘中+盘后、常规时段筛选。
- A 股支持同样的 K 线周期，但只显示常规交易时段；时间轴使用北京时间。美股继续使用美东时间和原有时段选择。
- 日线默认读取最近 730 天，可通过 `DAILY_HISTORY_DAYS` 调整；分钟线默认读取最近 5 天，可通过 `HISTORY_DAYS` 调整。历史范围由 OpenD 权限、股票上市日期及可提供的数据决定。
- MACD、VWAP、BBI、ATR、DMI/ADX、EMA、SMA、BOLL、RSI、成交量与均量；指标无限数量，参数用 JSON 编辑，模板存 SQLite。例：MACD `{"fast":12,"slow":26,"signal":9}`，VWAP `{"reset":"session"}` 或 `day` / `never`。
- 在“指标管理”中，每个指标可分别选择适用的图 1–4 和周期 1m、5m、15m、30m、60m、日线；两个条件同时满足才绘制。已有指标没有范围配置时默认用于所有图和周期，已有工作区与模板可继续使用。范围随工作区和指标模板保存到 NAS SQLite。
- 自定义指标可选“简易公式”或“Python”。Python 模式提供 `O/H/L/C/V` 价格与成交量序列、`TIME/SESSION/TRADE_DATE` 元数据，以及 `SMA/EMA/REF/HHV/LLV` 函数。把一条序列或最多 8 条序列组成的字典赋给 `result`；编辑后可保存进指标模板，并同样选择主图/副图及适用图、周期。示例见下方。Python 代码在独立进程按需计算，限制 4000 字符、500 个语法节点、5000 根 K 线、128 MB 内存及 3 秒运行时间；不支持 `import`、属性访问、文件/网络操作或第三方包。它是受限的 Python 指标环境，不是通用 Python 控制台。
- 可画水平价格线和两点趋势线并持久化。多图可同步时间轴与十字光标；不同股票价格轴不共用尺度，十字光标的横向价格值仅作参考。现版本应视为首个可用版本，而非与 TradingView 功能完全对等。
- 当前 K 线通过 OpenD 回调写入缓存和 WebSocket；同时间戳用 SQLite 主键覆盖，处理校正与重复推送。浏览器断线 5 秒重连；后端每 20 秒检查订阅并重新订阅，每 10 分钟重新拉取最近两天用于修正缺口。最近历史默认 2 分钟以内不重复请求。非交易时段或无成交时不会生成虚假 K 线。

## 数据与 API

| 接口 | 用途 |
| --- | --- |
| `GET /api/bars?symbol=US.SNDK&period=5m&mode=all&days=5` | 历史数据与缓存状态；日线使用 `period=1d&mode=regular`，省略 `days` 时默认 730 天 |
| `GET /api/bars?symbol=SH.600519&period=5m&mode=regular` | A 股历史 K 线；深市使用 `SZ.000001` 格式 |
| `GET /api/indicators?symbol=US.SNDK&period=5m&mode=all&name=MACD&params={...}` | 服务端指标计算 |
| `WS /api/stream?symbol=US.SNDK&period=5m&mode=all` | 实时 K 线与连接心跳 |
| `GET /api/status` | OpenD 状态、订阅数量 |
| `POST /api/python-indicator/validate` | 检查自定义 Python 指标语法及可用函数 |
| `POST /api/python-indicator` | 按当前图表的 SQLite K 线计算 Python 指标，不重复请求 OpenD |
| `GET /api/quotes?symbols=US.SNDK,US.SNXX` | 批量股票快照，最多 100 只；价格、涨跌幅和可用的盘前/盘后/夜盘字段 |
| `GET/PUT /api/settings/workspace`、`templates` | 保存布局、自选与模板 |

`bars` 表以 `(symbol, period, mode, time)` 为主键；时间是 UTC Unix 秒。美股按美东时间解析，隔夜 20:00 至次日 04:00 归入次交易日；A 股按北京时间解析，VWAP 默认按交易日重置，午间休市不另起一日。MACD/EMA 默认连续跨时段计算，但先按选择的时段过滤数据，切换时段后重算。无交易时段没有补零 K 线。时区转换由 IANA 数据处理。

Python 指标示例（在“指标管理 → 新建自定义指标 → Python”粘贴，选择主图或副图）：

```python
fast = EMA(C, 12)
slow = EMA(C, 26)
diff = fast - slow
signal = EMA(diff, 9)
result = {"MACD": diff, "Signal": signal, "Histogram": diff - signal}
```

输出每条线必须与当前 K 线根数相同；没有数值的位置用 `None`。网页打开且图表有数据时才计算，实时 K 线更新时最多约 10 秒重算一次。Python 指标只读取本地 SQLite 中已有的 K 线，不连接交易接口。

## 备用数据源

目前 OpenD 不可用时，网页可显示本地 SQLite 的最近缓存并标注“缓存数据”；不会把其他供应商数据悄悄混入指标。可选的免费历史数据候选有 [yfinance](https://ranaroussi.github.io/yfinance/)（美股等，非 Yahoo 官方 SDK；盘中历史有时间范围限制）和 [AKShare](https://github.com/akfamily/akshare)（A 股历史与近期分钟线，依赖第三方网页接口）。它们适合以后做**显式标注来源的历史补充**，都不能保证替代 OpenD 的美股 24/5 实时推送。需要稳定、合规的实时备份时，应按实际行情权限评估有许可的服务。

## 资源预算

这是容量预估，需在实际 NAS 上量测：单进程容器建议预留 **200–384 MB RAM**、**1 vCPU**；静止浏览器时 CPU 通常很低，初次加载历史与页面绘制时会短时升高。每根 K 线 SQLite 记录约 100–250 字节（含索引与 WAL 的粗估）；3 股票 × 5 周期 × 5 天若平均 2,000 根/组合，约 3–8 MB，实际隔夜数据密度和缓存保留时间会改变占用。日线每只股票约数百根，两年通常只增加少量缓存。服务端只广播 K 线更新，网络用量取决于订阅数与推送频率。`MAX_ACTIVE_STREAMS=32` 为本服务的资源保护上限，并非 moomoo 账号额度；实际订阅仍受 OpenD 额度和行情权限限制。默认每日清理 30 天前的分钟线和 1825 天前的日线，分别由 `CACHE_RETENTION_DAYS`、`DAILY_CACHE_RETENTION_DAYS` 调整；SQLite 文件不会立刻缩小，需停服务后执行维护压缩。

## 开发顺序

1. 已实现：OpenD 历史和实时接入、缓存、只读图表、指标、布局、自选与 HTTPS 部署路径。
2. 下一步：真实 NAS 与账号权限验收，包括 SNDK/SNXX/SNDQ 是否各自有隔夜数据；细化不同股票间的十字光标价格标示。
3. 后续：按月归档缓存、图形化指标参数编辑、精细的订阅合并与多用户配置隔离。

## 验收

本机：`python -m unittest discover -s tests -v`，`cd web && npm ci && npm run build`。真实 OpenD 验收需在 NAS 上对有行情权限的股票检查：历史全时段跨 20:00/04:00 数据、实时重复 K 线覆盖、关闭 OpenD 后重启并观察 `/api/status` 与图表恢复。没有真实 OpenD 时无法声称这些集成场景已经通过。
