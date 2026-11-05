# OpenD 网页连接与登录

桌面看盘页点击右上角 **OpenD 状态**，或进入 **设置 → OpenD 连接**。普通 HTTP 页面只提供跳转到 HTTPS 看盘页的入口，账号、密码和验证码必须在 HTTPS 页面输入，并先通过 NAS Market 的平台密码认证。

登录按 OpenD 当前提示分步进行：账号 → 登录密码 → 必要时手机或图形验证码。手机账号使用 `+区号 手机号`（例如 `+86 你的手机号`）；也可使用 moomoo ID 或邮箱。这里输入的是登录密码，交易密码仍在交易解锁界面输入。适配器默认回答“不记住密码”，不保存账号、密码或验证码。登录失败可刷新状态、重试验证码，或展开“重新开始登录”。

面板显示的是 OpenD 登录进程状态；实际行情连接由原有页顶状态显示。关闭面板停止轮询，未增加后台行情订阅。NAS 重启后 OpenD 容器自动启动到登录提示，再从这里手动登录即可。

## 部署

1. 保留现有 OpenD 的 `/app`、`/root` 挂载、RSA 配置和 Docker 网络。此适配器已针对 moomoo OpenD 10.11.7108 命令行版验证，其他版本的提示格式可能需要适配。
2. 把 `integrations/opend_login/supervisor.py` 复制到 OpenD Compose 目录的 `login-adapter/supervisor.py`；把该目录下的 `compose.opend-login.yml` 复制为 `compose.login.yml`。如现有 OpenD 服务名不是 `opend`，调整 overlay 的服务名。
3. 在 OpenD 目录创建 `login-runtime`，权限设为 700。两个 Compose 项目的 `.env` 都配置同一个绝对路径，例如 `OPEND_LOGIN_SHARED_DIR=/volume1/docker/moomoo-opend/login-runtime`。目录与 socket 默认仅容器运行用户 root 可访问；采用其他 UID 的部署需协调两端权限，不要改为全员可写。
4. OpenD 使用原 Compose 加 overlay 启动：`docker compose -f compose.yaml -f compose.login.yml up -d --no-build opend`。首次会重建原容器并要求再次登录。
5. Market 使用 `docker compose -f docker-compose.yml -f docker-compose.trade.yml -f docker-compose.opend-login.yml up -d --build market`。沿用现有 HTTPS 证书和平台密码。

两个 overlay 均为可选项。只增加现有 OpenD 内的标准库适配器进程，不新增常驻容器，不开放 Telnet，不把 Docker socket 挂载给 Market。适配器的原始控制台输出不会转发至浏览器或 Docker 日志；官方 OpenD 自身日志仍存于原 home 挂载，应保持其目录私有。

## 接口和保护

- `GET /api/trade/opend/status`：固定登录阶段、提示、版本、阶段 revision。
- `GET /api/trade/opend/captcha`：当前验证码图片（受目录、格式与大小限制）。
- `POST /api/trade/opend/input`：固定动作 `account/password/sms/captcha/request_sms/request_captcha/restart`，携带最新 revision；无通用命令执行能力。
- 全部沿用 HTTPS、平台会话和 Origin/CSRF 校验，绘图 API Token 无权调用。请求最大 4 KB，输入不允许换行与控制字符。
- “重新开始登录”仅对未完成/异常阶段开放。交易解锁、启用策略、待补挂止损或状态未明的订单会阻止重启。实际子进程更换完成前保护持续生效，浏览器关闭不会提前释放保护。无法确认结果时暂停券商操作，刷新状态确认新进程后恢复。
- 短信验证码每分钟最多请求一次，不自动重发登录请求。

## 回退

保留改动前的 Compose 与 home 状态。停止 OpenD 后去掉 `compose.login.yml` overlay，并使用原 Compose 强制重建原服务；Market 去掉 `docker-compose.opend-login.yml` 即可停用入口的后端适配器。不要删除 home、Device.dat、API RSA 密钥或行情缓存。

官方参考：[命令行 OpenD](https://openapi.moomoo.com/moomoo-api-doc/opend/opend-cmd.html)、[运维命令与验证码频率](https://openapi.moomoo.com/moomoo-api-doc/opend/opend-operate.html)。
