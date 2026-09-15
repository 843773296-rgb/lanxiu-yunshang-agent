#!/bin/bash
# 一条命令跑完全部检查。任一失败即整体失败。
cd "$(dirname "$0")"
FAIL=0
# .pyc 缓存的坑,踩过两次,**两次是同一个坑的两半**:
#
#   第一半(不写):咬合测试把某个模块改坏又在**同一秒内**改回来,而文件大小正好没变 ——
#     CPython 判断缓存是否失效看的就是 (源文件 mtime 秒数, 大小),两个都没变就直接用旧的 .pyc。
#     结果检查跑的是被改坏的那一版,红得莫名其妙。
#
#   第二半(不读):上面那行 `PYTHONDONTWRITEBYTECODE=1` 只阻止**写**,不阻止**读**。
#     修好 textmatch.py 的否定作用域之后,上一次留下的旧 .pyc 还在,于是 V2 的文本判分
#     一直是 32/40 —— **源码是对的,跑的是旧字节码**。查了半天差点去怀疑判分逻辑。
#
# 「防止产生」和「防止使用」是两件事。两半都要堵:先清干净,再禁止写。
find . -name __pycache__ -type d -not -path './agentsite/.venv/*' -exec rm -rf {} + 2>/dev/null
export PYTHONDONTWRITEBYTECODE=1
run(){ printf "\n\033[1m▸ %s\033[0m\n" "$1"; shift
  if "$@" > /tmp/chk.out 2>&1; then
    tail -3 /tmp/chk.out | sed 's/^/  /'
  else
    FAIL=1; sed 's/^/  /' /tmp/chk.out; printf "  \033[31m✗ 失败\033[0m\n"
  fi }
run "数据层 · truth 表隔离"   python3 backend/selftest.py
run "员工登录 · 5 条自测" python3 backend/auth.py
run "路由 · handler 必须真的存在" python3 backend/route_check.py
run "写接口 · 往返(临时副本上跑,不碰真库)" python3 backend/write_check.py
run "业务写入规则 · 11 条触发覆盖" python3 backend/writerule_check.py
run "边界审计 · 每条保证真的攻击一次" python3 backend/boundary_audit.py
run "提示词 · 单一源头与按工具装配" python3 tools/prompts_check.py
run "生命周期口径 · 自测" python3 knowledge/lifecycle.py
run "会员生命周期 · 14 条边界标注对账" python3 backend/member_check.py
run "预约派单 · 逐例标真值(派错和派对长得一样)" python3 backend/booking_check.py
run "数据隔离 · A 顾问看不到 B 顾问(漏了不会报错)" python3 backend/isolation_check.py
run "月度复盘 · 验性质不逐例标真值(相对指标标真值会过期)" python3 backend/review_check.py
run "预约漏斗 · 嵌套/加总/最窄一环(后一环比前一环多=结构错)" python3 backend/funnel_check.py
run "会员等级/积分/审批 · 边界逐例标真值(差一块钱掉一档是对的)" python3 backend/membership_check.py
run "活动归因与投入产出 · 期外订单不算成交、ROI 用实收" python3 backend/activity_check.py
run "能力管理 · 判据钉两头(中英文各一份,少一边就误报一片)" python3 agentsite/capman_check.py
run "下单前置 · 超期量体不是参考值是无效值(按着装人不按客户)" python3 backend/order_gate_check.py
run "商品与版型 · 性别和量体模板从版型派生(模板错了是量错尺寸)" python3 backend/product_pattern_check.py
run "形制与量体模板 · 模板必须覆盖形制的关键尺寸(漏一项就是没量最敏感的)" python3 backend/xingzhi_check.py
run "待定版型分档 · 47 条对照用例(真值手标)" python3 backend/pattern_grade_check.py
run "商品图 · 每张都渲染得出来,且看得出是不同的衣服" python3 backend/img_check.py
run "工具入参 · 人怎么称呼它,工具就得认得出来" python3 backend/tool_input_check.py
run "资料编辑日志 · 日志要说实话,而且说得出改了什么" python3 backend/edit_log_check.py
run "商品表单 · 显示的字段就得改得了(对照设计稿)" python3 backend/product_form_check.py
run "量体模版 / 测量项 · 改一个被引用的东西是最危险的动作" python3 backend/measure_tpl_check.py
run "分部位可选料 · 部位从裁片归并,报价口径要跟着出" python3 backend/part_check.py
run "订单部位选择 · 什么钱都要有对应的记录" python3 backend/part_choice_check.py
run "裁片用料占比 · 估出来的和版师给的不许长得一样" python3 backend/piece_ratio_check.py
run "方案引用 · 存编码不存名字,而且落到具体版型(否则算不出用料)" python3 backend/scheme_check.py
run "顾问引用 · 名字是被钉住的缓存,不是第二份真相" python3 backend/advisor_ref_check.py
run "角色与登录身份 · 每个 agent 角色都得有人进得来" python3 backend/role_check.py
# 版师是第一个「有写工具,但只有一个」的角色 —— 它特有的两种失败
# (给多了 / 给死了)在界面上长得一模一样,所以两个方向都得测。
# 要 venv 的解释器:这条检查 import sdk 取角色工具清单,不手抄一份。
run "推档 · 1237 条尺码要核的是 12 条档差" python3 backend/grading_check.py
run "版师角色 · 唯一的写工具只能改占比,而且真的得能改" ./agentsite/.venv/bin/python backend/pattern_role_check.py
run "会话归属 · 续聊不能续别人的(身份判得对也挡不住换历史)" python3 agentsite/sessions_check.py
run "花费闸 · 阈值够聊几轮 + 撞线说不说得清" ./agentsite/.venv/bin/python agentsite/budget_check.py
run "写工具的闸 · 逐例(拦错和不拦都不可见)" ./agentsite/.venv/bin/python agentsite/gate_test.py
run "技能形状 · 该有的段落齐不齐" ./agentsite/.venv/bin/python agentsite/skill_shape.py
run "读不读得出效果 · 判据本身要能被测" ./agentsite/.venv/bin/python agentsite/evalnoise_test.py
run "能力清单 · 声明/文件/白名单三边一致" ./agentsite/.venv/bin/python agentsite/manifest.py
run "RFM 评分 · 自测" python3 knowledge/rfm.py
run "RFM 评分 · 五条性质" python3 backend/rfm_check.py
run "交接文档 · 四段必填是否齐全" python3 tools/make_handoff.py --check
run "intent · 待办都点了名,「做完了」的判据真的在" python3 tools/intent_check.py
run "咬合记录 · 最贵的那一步不许只在脑子里" python3 tools/bite_check.py
run "评测题面 · 有指代就得有编号,或写明是故意的" python3 tools/case_check.py
run "改动影响面 · 警示段落找不着就是正则漏了" python3 tools/impact.py --selftest
run "评测夹具 · 写死了对象就得声明前提,而前提得成立" python3 tools/fixture_check.py
run "状态流转引擎 · 17 个用例" python3 backend/fsm.py
run "写入校验规则 · 10 个用例" python3 backend/rules.py
run "控件审计 · 死控件检查"    python3 backend/ui_audit.py
run "页面内联 JS · 语法(两个站都扫)" python3 agentsite/js_check.py
run "前端 · 引用的元素必须存在" python3 agentsite/ref_check.py
run "遮蔽检查 · 局部变量压函数" python3 backend/shadow_check.py
run "商品库 · 不卖矩阵判不可的组合" python3 backend/catalog_check.py
run "会员与订单 · 映射/勾稽/门槛" python3 backend/member_order_check.py
run "运维平台 · 队列/时效/解析/置信度" python3 backend/ops.py
run "售后判责 · 返修判定表/证据不足不硬判" python3 knowledge/liability.py
run "售后判责 · 标注与规则对账/规则覆盖" python3 backend/liability_check.py
run "MCP · 三个服务连通性"      python3 mcp/selftest.py
run "MCP · 通道等价(不调模型)" python3 mcp/parity.py
run "V1 循环 · 离线自测"       python3 agent/offline_test.py
run "V2 工作流 · 40 条工单纯规则(不调模型)" python3 agent/v2.py
run "记录仪覆盖 · 每个调模型的地方都接了" python3 agent/trace_check.py
run "知识库 · 与 craft 表一致"  python3 knowledge/check_kb.py
run "相容矩阵 · 2025 格推导/对账/落库" python3 knowledge/derive_combo.py
run "版型库与 BOM · 推档/裁片/物料对账" python3 knowledge/derive_pattern.py
run "量体推荐 · 三档判定/放松量/齐胸特例" python3 knowledge/fitting.py
run "成长推算 · 百分位/靶身高/复量周期" python3 knowledge/growth.py
run "用户生命周期 · 着装人/家庭/同意/过期量体" python3 backend/lifecycle_check.py
run "数据规范 · 身份/关联/覆盖(对照 数据规范.md)" python3 backend/spec_check.py
run "假数据工厂 · 推断/生成/闸门/灌回滚(24 项)" python3 fakedata/selftest.py
# ⚠️ 出处**对不对**是另一件事,由 tools/verify_sources.py 核(要联网,
#    所以不进这里 —— 依赖外部状态的检查放进门禁会变成随机拦路)。
#    **加知识、改出处之后手动跑一次。**
run "来源等级 · 声称可溯源的得真溯得了源" python3 backend/source_check.py
run "库存预警 · 算不出可售天数的不许算出一个数来" python3 backend/stock_check.py
run "钉死的锚点 · 抓同源谬误(手抄不现算)" python3 knowledge/pinned_check.py
run "产能排期 · 工种/一人一机/产能缺口" python3 knowledge/capacity.py
run "工期推算 · 并行链路/除不动/婚礼倒推" python3 knowledge/leadtime.py
run "回答体检 · 人造用例(正反各半)" python3 agentsite/guards_test.py
run "Skill 与配置面 · 设置源放开后的锁" ./agentsite/.venv/bin/python agentsite/skills_check.py
run "中文否定与子串 · 19 条(八次踩过的坑)" python3 agent/textmatch.py
run "判分器自测 · 18 条人造用例" python3 agent/chat_eval_judgetest.py
run "工具评测判分器 · 21 条对照用例" python3 agent/tool_eval_judgetest.py
run "成长评测判分器 · 22 条对照用例" python3 agent/growth_eval_judgetest.py
run "识图判分器 · 13 条对照用例" python3 agent/vision_eval_judgetest.py
run "判责判分器 · 14 条对照用例" python3 agent/liability_eval_judgetest.py
run "运维侧判分器 · 对照用例(含库存预警 9 条)" python3 agent/ops_eval_judgetest.py
run "复盘与漏斗判分器 · 31 条对照用例" python3 agent/report_eval_judgetest.py
run "会员与审批判分器 · 30 条对照用例" python3 agent/member_eval_judgetest.py
run "工匠与财务判分器 · 27 条对照用例" python3 agent/role_eval_judgetest.py
run "版师判分器 · 38 条对照用例" python3 agent/pattern_eval_judgetest.py
run "野外巡检 · 指纹粒度与行为观测" python3 agent/wild_run.py --selftest
run "野外语料 · 多样性(够多≠够杂)" python3 agent/wild_corpus.py --selftest
printf "\n%s\n" "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then printf "\033[32m✅ 全部检查通过\033[0m\n"; else printf "\033[31m❌ 存在失败项\033[0m\n"; fi
exit $FAIL
