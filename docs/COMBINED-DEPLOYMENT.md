# 一个应用容器运行看盘与交易

启用交易时，`docker-compose.trade.yml` 现在覆盖已有 `market` 服务，不再新建 `trading` 服务。最终为原有 OpenD 加一个 `nas-market-market-1` 应用容器。

```sh
docker compose -f docker-compose.yml -f docker-compose.trade.yml up -d --build market
```

先按 TRADING.md 准备 TLS 证书和 trade-data。仅需要看盘时仍可单独使用基础 Compose。

## 保留的数据和入口

- `data/market.sqlite3`：K 线、工作区、自选、指标模板和盘口参数。
- `trade-data/auth.json`：原平台密码派生值；不重新初始化密码。
- `trade-data/trading.sqlite3`：订单操作及成交后止损跟进。
- `trade-data/strategies.sqlite3`：自定义策略、处理游标、事件。
- `trade-tls`：原 TLS 证书及密钥，继续只读挂载。
- HTTP 8088 看盘、HTTPS 8443 `/chart` 和 `/trade` 保持原地址。OpenD 不重启、不复制。

两个 Uvicorn 进程由轻量 Python 启动器管理：任一进程意外退出，另一进程也关闭，让 Docker 自动重启整个应用。容器启用 init 回收子进程；双服务健康检查同时检查 HTTP 和 HTTPS。合并后统一内存上限 640MiB、1.5CPU，实际用量取决于行情和策略；减少容器数量不代表进程内存减半。

内部行情地址显式设为 `http://127.0.0.1:8000`，策略监控和 HTTPS 行情代理在同容器内访问。实盘认证、CSRF、手动解锁、授权到期和不保存交易密码等规则保持生效。

## 从旧版两个应用容器迁移

1. 确认没有等待跟进的买入止损任务；备份两个 Compose 文件、认证文件和 SQLite（使用 SQLite backup 处理 WAL）。
2. 保留旧 market 镜像作为回滚标签；构建新 market 镜像。
3. 停止旧 `nas-market-trading-1` 释放 8443 端口，再移除该旧容器，不删除数据目录或卷。
4. 使用合并 Compose 启动 market；检查两端口、认证、数据库、自定义策略和真实 OpenD 行情。
5. 更新会使登录和交易授权失效，需要用户重新登录及手动解锁；已送达券商的订单按券商规则继续有效。策略信号监控保留，自动执行授权不恢复。

不要同时启动旧 trading 和合并 market，它们会争用 8443 端口及同一交易数据库。旧容器删除仅影响运行实例，持久数据仍在原目录。

## 回滚

恢复备份的 `docker-compose.trade.yml`，将 `nas-market-market:before-combined` 重新标为 `nas-market-market:latest`，再用旧 Compose 启动 market 和 trading。需要先停止合并 market 以释放端口；保留旧 `nas-market-trading` 镜像，避免没有回滚镜像。认证、证书和数据库路径不变。

本轮迁移在 NAS 项目目录 `backups/combined-*` 留有旧 Compose、认证及数据库备份。备份含敏感认证资料，不能上传 GitHub 或公开分享。
