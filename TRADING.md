# 网页交易平台

这是使用现有 moomoo OpenD 的真实交易接口实现，不会使用模拟报价替代正式接口。
自动化测试使用注入的 FakeBroker，与 NAS 或任何券商账户隔离。生产入口没有测试开关。

## 第一版功能

- 美股股票/ETF：账户选择、资金、持仓、可卖数量、订单及操作流水。
- 整股、现金买入和卖出已有多头持仓；不开放融资、做空、期权或 A 股下单。
- 限价、市价、卖出止损市价/限价、移动止损市价/限价。
- 预设股数，按可卖数量的 25% / 50% / 全部提交限价卖出。
- 持仓按现价距离设置 1% / 2% / 3% 止损，比例和股数按钮可以自定义。
- 固定限价/止损订单修改，当前订单逐笔撤单。
- 默认每次预览后确认；用户主动开启“快捷模式”后，按钮直接提交。
- 模拟环境默认选择，实盘必须单独解锁当前账号，最长 15 分钟。

第一版的“持仓止损”是成交后的独立操作，买单不会自动带止损。未实现原子
Bracket/OCO、双卖单联动、无人值守策略、自动追价或买卖盘一键定价。
限价由用户明确设置；持仓比例卖出使用显示的持仓现价作为限价，不能保证成交。
页面关闭后，券商已经接受的订单继续按其订单规则有效。

## 部署

保持原 `docker-compose.yml` 的看盘服务不变，新增可选交易容器。
在 NAS 项目目录准备证书及一次性初始化码：

```sh
python3 scripts/prepare-trading.py --host 192.168.101.103
docker compose -f docker-compose.yml -f docker-compose.trade.yml up -d --build
```

`.env` 增加：

```ini
TRADING_BIND=0.0.0.0
TRADING_PORT=8443
TRADING_SECURITY_FIRM=N/A
TRADING_MAX_ORDER_USD=10000
TRADING_MAX_SHARES=1000
TRADING_URL=https://192.168.101.103:8443/trade
```

`N/A` 由 OpenD 选择其账号券商。若账号列表为空，根据实际开户券商指定
`FUTUINC`（美国）、`FUTUSG`（新加坡）等 SDK SecurityFirm 值。
不要同时运行多个交易 worker 或多个交易网关实例；订单串行锁和会话在进程内。

证书准备脚本生成 IP/DNS SAN 的自签名证书，输出 SHA256 指纹；它不是公共 CA 证书。
首次浏览器访问必须核对 NAS 证书并建立信任，不能把关闭证书验证作为生产方案。
若使用已有可信域名证书，将匹配该域名的证书和私钥放到
`trade-tls/cert.pem`、`trade-tls/key.pem`，再重启 trading 服务。
脚本不会自动覆盖证书，不改动或重启 OpenD。

看盘页的“交易台”按钮打开 `.env` 中的 HTTPS 地址。极空间远程入口需要单独添加
此 HTTPS 服务；原 8088 的 HTTP 入口只提供看盘功能。
反向代理必须连接 HTTPS 上游并验证上游证书、保留浏览器原始 Host，例如 Nginx
`proxy_set_header Host $http_host`。浏览器 Origin 与 Host 必须相同；不信任任何
任意来源注入的 X-Forwarded-Proto 或 X-Remote-User。公司侧极空间转发需实测。

## 首次登录

1. 访问 HTTPS `/trade`。本机 NAS 管理员读取 `trade-data/setup-code.txt`，仅在网页输入。
   也可在本机打开带 `#setup=初始化码` 的链接；前端立即删除地址栏片段，服务端不接收该 URL 片段。
2. 设置独立的平台密码，至少 12 个字符。初始化码使用后从 NAS 删除。
3. 平台密码采用随机盐 PBKDF2-SHA256（600000 次）保存，不保存明文。
4. 选择模拟账号。实盘需要你在网页输入 moomoo **交易密码**，并确认实际账户。
5. 交易密码及 MD5 不入库、不写环境变量、不进入日志或浏览器存储。

`trade-data` 包含平台密码派生值、订单流水及偏好；应限制权限并备份。
`trade-tls` 包含 HTTPS 私钥。两者均已从 Git 忽略。
不要把交易密码发给聊天、Agent 或 Telegram。

## 订单规则与恢复

- SDK 每次明确传入真实 acc_id 和环境，并核对账号的 US 权限。
- 单笔股数和估算金额上限在后端执行。金额上限不是市价成交金额保证；市价可能滑点。
- 市价单要求 OpenD 确认处于常规交易时段，且快照不超过 5 秒；预览后参考价格变化超过 1% 时要求重新预览。
- 预览有效期 20 秒。提交时重新检查购买能力、可卖数量、价格和账号授权。
- 实盘条件单第一版仅开放 RTH；ETH / OVERNIGHT / ALL 仅限价。
- 模拟环境仅 NORMAL / MARKET、DAY / RTH；不能用模拟盘证明实盘止损已经验收。
- 操作编号在联系券商前持久化；同一编号不重复发送。SDK 结果不明确时标为 UNKNOWN。
- UNKNOWN 会阻止此账号继续提交。点击“核对券商”按 remark 或订单状态核对；不会自动重发。
- 若接口报错但无法匹配记录，至少等一分钟，先在 moomoo 核实，再完整输入流水编号进行人工核对。
  人工核对只解除阻塞，不会提交、重发或撤销任何订单。
- 撤单和改单返回成功仅表示接口受理，应继续查看券商订单最终状态。
- 关闭网页后不再轮询账户；无解锁会话时，闲置约 2 分钟释放 OpenD 连接。
- 实盘授权到期或退出时尝试锁定 OpenD。网络中断时不能保证 OpenD 端已锁定，但网关拒绝新交易。
- OpenD 解锁为全局效果，其他持有连接密钥的程序也可能交易；必须限制 OpenD 网络和 RSA 密钥访问。

## 验证

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
cd web
npm ci
npm run build
```

自动化测试覆盖身份认证、HTTPS/CSRF、账号环境、授权超时、预览确认、幂等、
超卖/融资拦截、重复订单核对及恢复。真实部署仅只读检查了账户、持仓、资金和订单。
首次实盘下单、真实部分成交、撤改单以及止损触发仍需用户自行验收，不由开发工具代下单。

官方接口：[解锁](https://openapi.moomoo.com/moomoo-api-doc/en/trade/unlock.html)、
[下单](https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html)、
[改单撤单](https://openapi.moomoo.com/moomoo-api-doc/en/trade/modify-order.html)、
[持仓](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-position-list.html)。
