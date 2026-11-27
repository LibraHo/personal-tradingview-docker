# 通用 HTTP 消息推送

入口：`https://<NAS地址>:8443/chart?settings=notifications`，或「设置 → 消息推送」，需登录。

每渠道填写：名称、完整 HTTP/HTTPS 请求地址、JSON/表单格式、标题与正文字段名、每日请求上限。可以配置请求头、附加字符串字段和响应成功字段。不预设服务商，也不安装服务商 SDK。使用 POST 请求，消息体为一层字段；暂不支持嵌套消息模板。

地址和请求头可能含密钥，服务端保存，读取只返回 has_url/has_headers。编辑留空沿用；换地址时必须重新填写已有请求头，或用 {} 清空。附加字段属于可回读普通配置，敏感鉴权应放在地址或请求头。

不填成功字段时按 HTTP 2xx 判定接收成功；填写 code / data.code 等字段后还要与配置成功值匹配。true/false 不区分大小写。坏回执或缺字段标记 unknown。禁止重定向，不在日志中输出完整地址、请求头或接收端错误正文。

选择监控及盘中预览/收盘确认，保存并启用。任务频率仍在「扫描与监控」配置；通知只消费已有事件，不建立实时行情订阅。空列表不接收任何监控。只处理启用或调整接收范围后的新信号，不补历史。保存不会发送，手动测试使用已保存地址并计入额度。

每日请求上限按北京时间重置，测试和重试共用预算，到限留至次日。多个渠道可能共享服务商账户额度；本地限额不是账户余额。每渠道请求最小间隔2秒。图表链接可能需要家庭网络。

状态：pending 等待、sending 请求中、accepted 接收端成功响应、retry 重试、failed 失败、unknown 需核对、cancelled 已取消。超时不盲目重发；明确拒绝最多请求三次。accepted 不代表已读。停用、删除或更改接收范围取消旧待发消息，已发出的请求无法撤回。

接口仅注册在 HTTPS 服务，复用会话、同源与 CSRF：

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/api/trade/notifications` | GET | 脱敏渠道、监控和最近100条记录 |
| `/api/trade/notifications/channels` | POST | 创建 |
| `/api/trade/notifications/channels/{id}` | PUT / DELETE | 更新/删除 |
| `/api/trade/notifications/channels/{id}/test` | POST | 排队测试 |

字段：name、url（SecretStr，留空沿用）、headers（秘密字典，null沿用/{}清空）、format（json/form）、title_field、body_field、extra_fields（普通字符串字典）、success_field、success_value、enabled、monitor_ids、confirmation（confirmed/preview/all）、daily_limit（1–1000）。HTTP入口的未知地址可能返回前端HTML，这不表示通知API在HTTP注册。

接 Server酱时，根据其文档填写完整发送地址、表单格式、title/desp字段和code=0成功条件；这些值由用户填写，产品代码没有服务商适配器或预设地址。
