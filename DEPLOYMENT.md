# 当前部署（2026-10-26）

看盘与 HTTPS 交易已整合到 `nas-market-market-1` 一个应用容器，外接原有 `moomoo-opend`。原 `nas-market-trading-1` 由合并部署替代。访问地址仍是 HTTP 8088 与 HTTPS 8443；账户认证、证书、行情缓存和策略数据库继续沿用原挂载目录。更新使用：

```sh
docker compose -f docker-compose.yml -f docker-compose.trade.yml up -d --build market
```

合并后已验证双端口健康、密码及全部缓存/策略数据保留。2026-10-26 用户完成 OpenD 交互登录后，已确认 qot_logined/trd_logined 为 true，SNDK 实时订阅成功。修复看盘和盘口连接在登录前无限等待的问题：使用 SDK 异步握手，默认 8 秒超时后关闭旧连接并允许重试。

合并部署细节及旧部署迁移见 [COMBINED-DEPLOYMENT.md](docs/COMBINED-DEPLOYMENT.md)。下文保留历史部署记录，不作为当前启动指令。

---

# 这台极空间 NAS 的部署状态（2026-10-24）

## 新增网页交易台

- HTTPS 入口：`https://192.168.101.103:8443/trade`；看盘页新增“交易台”按钮。
- 容器 `nas-market-trading-1`，独立认证、交易数据库、TLS 证书；未改动或重启 OpenD。
- 使用 `docker-compose.yml` 与 `docker-compose.trade.yml` 共同管理。后续更新交易服务使用
  `docker compose -f docker-compose.yml -f docker-compose.trade.yml up -d --build trading`。
- 已验证真实 OpenD 可读取美股实盘/模拟账户、持仓、资金、订单和证券信息。没有提交任何用户账户订单。
- 本地 43 项测试通过；隔离浏览器测试覆盖登录、预览、确认、改单、撤单、止损、快捷卖出和重新锁定。
- 已验证 NAS HTTPS 登录页可打开，未登录账户接口返回 401；浏览器看盘页交易入口可见。
- 两服务健康检查正常。交易服务尚未加载账户时的一次空闲测量为 32.54 MiB / 0.25% CPU；不代表连接账户后的峰值。
- 首次需用户自行设置平台密码，一次性初始化码在 `trade-data/setup-code.txt`，使用后自动删除。
- NAS 自签名证书 SHA256：`CF:1E:41:9C:98:D5:EF:2E:19:E3:80:D3:81:8D:D2:32:9D:EE:4D:76:FF:9C:84:60:18:0E:E6:5C:60:CA:5F:70`。
- 详见 [TRADING.md](TRADING.md)。真实下单、成交、实盘止损触发及公司侧极空间远程入口尚未验收。

## 原看盘服务

- 主机：`Z2Ultra-KL4S`，局域网地址 `192.168.101.103`。
- 项目目录：`/tmp/zfsv3/sata11/18600104924/data/nas-market`。
- Compose 服务：`market`；容器：`nas-market-market-1`；设置了自动重启与健康检查。
- 局域网网页：`http://192.168.101.103:8088`。极空间“远程访问”中使用该地址添加网页入口，名称建议为 `NAS Market`。不要把 8088 在路由器上转发到公网。
- OpenD：经现有 `moomoo-opend_default` Docker 网络连接 `moomoo-opend:11111`。现有 RSA 私钥以只读卷挂载，项目目录和镜像不含私钥内容。原 OpenD 容器未修改。

## 已完成的实际检查

- NAS 容器初次部署时健康状态 `healthy`，重启次数 `0`；实测约 91 MB 内存、1.1% CPU（单次采样，不代表峰值）。
- SNDK 的 5 分钟全时段历史请求返回 576 根 K 线，其中隔夜 192 根；SNXX 与 SNDQ 的 15 分钟请求各返回 192 根，均含隔夜 64 根。数据直接来自 OpenD，没有模拟报价。
- 1 分钟、60 分钟、日线历史请求成功；MACD 接口返回 576 个时间点；WebSocket 收到实时 1 分钟 K 线。
- 浏览器中行情和指标显示正常，四图切回单图没有脚本错误；时间轴按美东时间显示。
- 2026-10-23 修正日线历史范围：SNDK 默认 730 天请求返回 425 根，最早 2025-02-13；将范围扩大至 1825 天结果相同。浏览器切换到日线后显示 425 根且无脚本错误。日线缓存与分钟线分开清理。
- 2026-10-23 增加 A 股和自选分组：NAS OpenD 的 `SH.600519` 历史日线与实时订阅均成功；网页 API 返回 5 分钟历史 K 线及日线，来源为 OpenD 而非缓存。浏览器检查了 A 股图表、精选星标、新建/重命名分组、旧美股自选迁移、跨市场切换、刷新后恢复和 A 股 WebSocket 连接。测试使用拦截的设置接口，没有改动用户真实自选。升级前 SQLite 备份位于同目录的 `data/market-before-multimarket-20261023.sqlite3`。
- 本地 10 项单元测试通过；前端构建通过。

## 极空间入口

从公司浏览器登录极空间，进入“远程访问”或 Docker 容器的网页入口，打开 `NAS Market`。若该容器尚未显示为快捷入口，在极空间“远程访问”中添加 `http://192.168.101.103:8088`。这一项需要在你已登录的极空间账号界面操作；本次无法验证公司侧的极空间登录会话及其是否转发 WebSocket。

网页本身在家庭局域网内使用 HTTP，极空间远程入口的登录与外层 HTTPS 由极空间提供。OpenD 的 API 端口没有暴露到公网或家庭局域网。

## 指标与空闲连接

- 常用指标可在右侧“指标管理”中添加、隐藏、修改参数，并保存模板。自定义公式支持 O/H/L/C/V、SMA、EMA、REF、HHV、LLV、ABS、MAX、MIN 和四则运算；例如 `EMA(C,12)-EMA(C,26)`。可选主图或副图。它是本网页的公式语法，不能直接运行 moomoo Python 指标或 TradingView Pine Script。
- 网页的实时订阅保护上限改为 32，不是 OpenD 账号额度。2026-10-22 查询该 OpenD 时返回总已用 0、剩余 2000；这只是查询时的配额快照，夜盘权限仍由账户决定。
- 关闭网页后 WebSocket 断开；moomoo 要求订阅至少维持 1 分钟，程序在满足这一条件后退订。退订且无浏览器连接后，程序在下一轮空闲检查中关闭到 OpenD 的连接，通常总计约 1–2 分钟。容器的健康检查仅访问自身。程序没有 OpenAI 接口或密钥。

## 日常操作

在 NAS 项目目录运行 `docker compose ps` 查看状态，`docker compose logs --tail 100 market` 查看日志，`docker compose restart market` 重启网页服务。更新本项目后运行 `docker compose up -d --build`。SQLite 数据在同目录的 `data/` 下；分钟线默认保留最近 30 天，日线默认保留最近 1825 天。日线默认读取 730 天历史，实际最早日期取决于 OpenD 返回的数据。
