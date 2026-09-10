# 业务覆盖对账

> 三层覆盖各算各的分母,全部自动扫出来。
> 唯一需要人给的是「哪些表属于哪个业务面」——**而漏归类会红**。

| 业务面 | 有数据的表 | 有工具读得到 | 被评测要求调的工具 | 智能体看不见的表 |
|---|---:|---:|---:|---|
| 客户与账户 | 6 | 3 | 3/9 | consent、phone_alias、member_bind |
| 会员与营销 | 6 | 1 | 0/1 | level_cfg、points_log、invite_code、activity_cost、tag |
| 订单与支付 | 7 | 7 | 0/6 | — |
| 商品与库存 | 14 | 9 | 1/14 | category、stock_log、craft_bom、pattern_bom、scheme |
| 量体与成长 | 6 | 3 | 0/5 | measure_tpl、tpl_item、growth_forecast |
| 工坊与排产 | 5 | 5 | 1/6 | — |
| 门店与人员 | 6 | 2 | 0/4 | shop、appointment、followup、approval |
| 内容与页面 | 5 | 1 | 0/1 | content、page、page_block、sys_code |
| 系统与日志 | 4 | 0 | 0/— | op_log、download_task、truth、sqlite_sequence |

**合计:59 张有数据的表,31 张有工具读得到(52%)**

## 口径限制(免得被当成精确值)

- 第三层是**下界**:有些评测题故意不要求调工具,这里数不到。
- 工具→表 靠读 SQL,读不到动态拼出来的表名。
- 「有工具读得到」不等于「答得对」——那是评测的事,不是这张表的事。
