# 美股单腿期权与快捷键

入口：HTTPS 看盘页图表下方，或交易台中的「期权快捷交易」。平台登录和实盘手动解锁沿用现有流程。

1. 填写 `US.SNDK` 等标的，读取到期日。
2. 选择到期日、Call / Put、具体行权价合约。也可点当前账户的期权持仓。
3. 明确填写每股权利金限价，或主动使用快照买一 / 卖一。选择张数。
4. 点击买入、卖出、卖出可卖一半、全部平仓。默认先预览；主动开启快捷模式后直接提交。更换合约或刷新快照会关闭快捷模式并清空限价，更换账户会重置期权选择。

默认张数按钮 1、2、5，可修改并保存到 NAS。与股票的股数按钮分开保存，不覆写股票止损方案。

后端从 OpenD 获取期权信息，识别 `option_valid`，从正股基本信息确认股票 / ETF 标的，并用期权链确认 `option_standard_type=STANDARD`；校验 `option_contract_size`、`option_contract_multiplier`、`lot_size` 均为 100，以及到期日未过期。金额按 `权利金 × 张数 × 合约乘数` 计入原有单笔金额上限，不含费用。缺失乘数时拒绝，绝不默认猜测 100。期权实际最小报价步长、账户等级、现金购买能力、券商受理仍由 OpenD / 券商校验。

当前仅开放标准 100 股交割的股票和 ETF 单腿期权，RTH / DAY 限价。卖出必须有足够的多头可卖张数；禁止卖空。暂不开放组合单、指数期权、调整合约、期权止损、成交后止损和自动行权。股票快捷止损不对期权显示；不能把股票止损方案套到期权上。期权持仓行的比例卖出按整张向下取整。

期权链是静态信息，不代表实时行情权限。到期日与按到期日查询的合约链缓存五分钟，最多 32 组；只为选中的合约读取快照，不订阅整个期权链。快照显示美东时间，不承诺可执行价格。首次接口超时会显示错误，可手动重试，无订单自动重发。

接口（均在原 HTTPS 认证边界内）：

- `GET /api/trade/options?code=US.SNDK`：到期日。
- `GET /api/trade/options?code=US.SNDK&expiry=YYYY-MM-DD`：该到期日静态合约链。
- `GET /api/trade/quote?code=具体合约代码`：选中合约快照及乘数。
- 订单沿用 `preview` → `commit`，幂等流水、解锁有效期及结果未知不重发规则不变。
- `GET/PUT /api/trade/presets` 增加 `option_quantities`，兼容旧设置。

官方依据：

- [期权链](https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-option-chain.html)
- [快照及合约乘数](https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-market-snapshot.html)
- [下单接口：期权数量单位为张](https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html)
- [股票 / 期权账户及模拟交易说明](https://openapi.moomoo.com/moomoo-api-doc/en/qa/trade.html)

2026-10-27 真实 NAS 只读核验：OpenD 已登录，SNDK 返回 21 个到期日，未来十天 1,252 个合约；成功读取具体合约快照，三个乘数字段均为 100。首次查询超时，手动重试成功。另已通过真实 OpenD 模拟账户购买能力查询及订单预览，1 张 × $1 × 100 = $100；仅预览，未提交。未解锁或提交账户订单；93 项后端测试及浏览器的 4 次隔离预览通过（含改单保留原订单），不代表实盘成交或实盘期权权限已通过。

成交量柱按同根 K 线收盘对开盘着色：收盘大于等于开盘为绿，低于开盘为红，与当前 K 线配色一致；量均线保持独立颜色。
