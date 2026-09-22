#!/bin/bash
# 一条命令跑完全部检查。任一失败即整体失败。
cd "$(dirname "$0")"
# 库正在重建时不跑 —— 这时候的红不代表任何东西(见 tools/rebuild.sh 开头的互斥标记)
if [ -f backend/.rebuilding ] && kill -0 "$(cat backend/.rebuilding)" 2>/dev/null; then
  echo "⏸  库正在重建(pid $(cat backend/.rebuilding)),这时候跑出来的红不代表任何东西 —— 等它跑完再跑"
  exit 3
fi
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
# ⚠️ **缩进用 awk 不用 sed。** macOS 自带的是 BSD sed,
# 在 LANG=zh_CN.UTF-8 下处理某些中文输出会**断言失败直接 abort**:
#
#     Assertion failed: (advance > 0), function substitute, file process.c, line 462
#     ./check.sh: line 23: 21292 Abort trap: 6   | sed 's/^/  /'
#
# 2026-09-20 两个会话各撞到一次。危险的半边在**失败分支** ——
# 那里 sed 负责打印失败详情,它一崩就只剩一行「✗ 失败」,
# **一个字的原因都没有**,而 FAIL=1 照样置上了。
# 于是「查不出为什么红」会被当成「这条检查坏了」。
#
# awk 输出逐字一致(验过),而且喂它二进制垃圾也不崩。
run(){ printf "\n\033[1m▸ %s\033[0m\n" "$1"; shift
  if "$@" > /tmp/chk.out 2>&1; then
    tail -3 /tmp/chk.out | awk '{print "  " $0}'
  else
    FAIL=1; awk '{print "  " $0}' /tmp/chk.out; printf "  \033[31m✗ 失败\033[0m\n"
  fi }
run "数据层 · truth 表隔离"   python3 backend/selftest.py
run "写入口身份闸 · 没登录不许改业务数据(打 HTTP 层)" python3 backend/authgate_check.py
run "员工登录 · 5 条自测" python3 backend/auth.py
run "路由 · handler 必须真的存在" python3 backend/route_check.py
run "只读入口冒烟 · 50 个入口真跑一遍(handler 存在≠跑得起来)" python3 backend/page_smoke_check.py
run "写接口冒烟 · 在库的副本上真写一遍(返回 ok≠写进去了)" python3 backend/write_smoke_check.py
run "产品文档 · 写死的数字和代码对账(文档变假时不会报错)" python3 tools/doc_numbers_check.py
run "写接口 · 往返(临时副本上跑,不碰真库)" python3 backend/write_check.py
run "业务写入规则 · 11 条触发覆盖" python3 backend/writerule_check.py
run "边界审计 · 每条保证真的攻击一次" python3 backend/boundary_audit.py
run "提示词 · 单一源头与按工具装配" python3 tools/prompts_check.py
run "生命周期口径 · 自测" python3 knowledge/lifecycle.py
run "会员生命周期 · 14 条边界标注对账" python3 backend/member_check.py
run "预约派单 · 逐例标真值(派错和派对长得一样)" python3 backend/booking_check.py
run "促活判断 · 逐例标真值 + 覆盖报告(没有样本不叫通过)" python3 backend/revive_check.py
run "简体闸 · 业务数据一律简体(外来文本进来前先查)" python3 backend/simplified.py
run "商机判断 · 24 条逐字稿(造的对话·纯规则版·只许升不许降)" python3 backend/opportunity_check.py
run "排班 · 五种状态逐例标真值(没排班和休息长得一样)" python3 backend/roster_check.py
run "客户归属 · 「有顾问」≠「有人管」(只查不改)" python3 backend/ownership_check.py
run "成交归因 · 收入分成必须=100,影响力分成可以超(规则相反)" python3 backend/credit_check.py
run "表的来路 · 每张表都要能从 rebuild.sh 建出来(本地有≠CI有)" python3 tools/table_origin_check.py
run "订单↔预约链路 · 空值要说清是哪一种空" python3 backend/link_check.py
run "客户旅程 · 触点归一 + W 型归因(算法跑得通≠算得准)" python3 backend/touchpoint_check.py
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
run "售后与维保 · 业务硬规则(库允许≠业务允许)" python3 backend/aftersale_rule_check.py
run "换货 · 五条规则(走审批/要寄回/同渠道/差价多退少补)" python3 backend/exchange_check.py
run "受欢迎与易损 · 性质检查(相对指标不标真值)" python3 backend/popularity_check.py
run "同意分档与撤回 · 一档不顶另一档,撤回真的走一遍" python3 backend/consent_check.py
run "订单状态 · 定制品与标品两套状态必须分开" python3 backend/order_status_check.py
run "演示数据集 · 形状(退款对得上 / 占比 / 面料有差异 / 汇总对得上 / 不是整数)" python3 backend/dataset_check.py
run "打版库(每个版型都出得了图 / 图上的数就是库里的数 / 页面指对版型)" python3 backend/draft_check.py
run "重建可复现(SQL 不许 RANDOM / 造数据要设种子 / 不拿机器的今天当基准)" python3 tools/determinism_check.py
run "同名字段必须同义(一个列名在几张表里存的是同一种东西)" python3 backend/samekey_check.py
run "种下的规律 · 登记和代码对得上(种进去的不许被当成发现)" python3 fakedata/planted.py
run "角色与登录身份 · 每个 agent 角色都得有人进得来" python3 backend/role_check.py
# 版师是第一个「有写工具,但只有一个」的角色 —— 它特有的两种失败
# (给多了 / 给死了)在界面上长得一模一样,所以两个方向都得测。
# 要 venv 的解释器:这条检查 import sdk 取角色工具清单,不手抄一份。
run "推档 · 1237 条尺码要核的是 12 条档差" python3 backend/grading_check.py
run "版师角色 · 写工具只有改占比和开裁两个,而且真的得能改" ./agentsite/.venv/bin/python backend/pattern_role_check.py
run "会话归属 · 续聊不能续别人的(身份判得对也挡不住换历史)" python3 agentsite/sessions_check.py
run "花费闸 · 阈值够聊几轮 + 撞线说不说得清" ./agentsite/.venv/bin/python agentsite/budget_check.py
run "成本口径 · 项目算的钱要和官方计费规则对得上(期望值手抄官方价,不从价目表现算)" ./agentsite/.venv/bin/python agentsite/cost_check.py
run "写工具的闸 · 逐例(拦错和不拦都不可见)" ./agentsite/.venv/bin/python agentsite/gate_test.py
run "技能形状 · 该有的段落齐不齐" ./agentsite/.venv/bin/python agentsite/skill_shape.py
run "工具路由用例 · 点名的工具真的挂着(改了名就永远被跳过)" ./agentsite/.venv/bin/python agentsite/tool_eval.py --check
run "读不读得出效果 · 判据本身要能被测" ./agentsite/.venv/bin/python agentsite/evalnoise_test.py
run "能力清单 · 声明/文件/白名单三边一致" ./agentsite/.venv/bin/python agentsite/manifest.py
run "RFM 评分 · 自测" python3 knowledge/rfm.py
run "RFM 评分 · 五条性质" python3 backend/rfm_check.py
run "交接文档 · 四段必填是否齐全" python3 tools/make_handoff.py --check
run "intent · 待办都点了名,「做完了」的判据真的在" python3 tools/intent_check.py
run "咬合记录 · 最贵的那一步不许只在脑子里" python3 tools/bite_check.py
run "截断的报告要说「还有几条」(只许少不许多)" python3 tools/truncation_check.py
run "门禁外的检查多久没跑了(只报状态,永不拦)" python3 tools/runlog_check.py
run "评测轮次 · 调模型的评测不许只跑一轮(只许少不许多)" python3 agent/rounds_check.py
run "部分覆盖 · 跑一部分题不许覆盖完整基线(只许少不许多)" python3 agent/partial_write_check.py
run "轮次报告 · 单轮/抖动/可比,四种情形都说对话" python3 agent/rounds.py
run "仓库自洽 · 工作区绿不等于仓库里那一版绿" python3 tools/repo_consistency_check.py
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
run "纹样口径 · 名字/面料/工艺推导,补子不许猜" python3 knowledge/motif.py
run "用户生命周期 · 着装人/家庭/同意/过期量体" python3 backend/lifecycle_check.py
run "数据规范 · 身份/关联/覆盖(对照 数据规范.md)" python3 backend/spec_check.py
run "假数据工厂 · 推断/生成/闸门/灌回滚(24 项)" python3 fakedata/selftest.py
run "假数据工厂 · 行级稳定(同一批键换个顺序,值必须一样)" python3 fakedata/stable.py
run "假数据工厂 · 跨进程/跨日期可复现(换台机器换一天,数据一样)" python3 fakedata/repro.py
run "假数据工厂 · 交付物锚定咬合(三条都咬得动)" python3 fakedata/anchor.py 自测
run "交付物锚定 · 被外面消费过的值没被挪动" python3 fakedata/anchor.py 验 --db backend/lanxiu.db
run "交付图清单咬合(缺了/变了/多了 三条都咬得动)" python3 tools/delivered_images.py 自测
run "交付图清单 · 图不进版本库,指纹进(这台机器没图就明说)" python3 tools/delivered_images.py 验
run "假数据工厂 · 跨字段一致咬合(三条都咬得动)" python3 fakedata/agree.py --自测
run "假数据工厂 · 同类还有几处(咬合)" python3 fakedata/samekind.py 自测
run "跨字段一致 · 同一个事实的几个落点不打架(不许投票)" python3 fakedata/agree.py --db backend/lanxiu.db
run "演示数据命名 · 方案名只许「定制款·工艺·年月」,不带人名" python3 fakedata/naming.py
# ⚠️ 出处**对不对**是另一件事,由 tools/verify_sources.py 核(要联网,
#    所以不进这里 —— 依赖外部状态的检查放进门禁会变成随机拦路)。
#    **加知识、改出处之后手动跑一次。**
run "字典表 · 枚举表说的和数据里真有的,得是同一批" python3 backend/syscode_check.py
run "顾问写入 · 写了名字列就必须一起写工号" python3 backend/advisor_write_check.py
run "顾问名字 · 页面上那一栏有名字,而且对得上" python3 backend/advisor_name_check.py
run "来源等级 · 声称可溯源的得真溯得了源" python3 backend/source_check.py
run "库存预警 · 算不出可售天数的不许算出一个数来" python3 backend/stock_check.py
run "量体口径 · 按次登记、订单以绑定的下单量体为准、缺项不拼" python3 knowledge/measure.py
run "量体录入写口 · 权限 / 同意 / 校验 / 下单量体绑定(在库副本上跑)" python3 backend/measure_write_check.py
run "白坯试衣 · 「没走流程」和「走了没拿到确认」不许混成一个" python3 backend/muslin_check.py
run "白坯试衣写口 · 开裁那道闸会拦、后台改状态也绕不过、签字撤不掉(在库副本上跑)" python3 backend/fitting_write_check.py
run "多渠道对比 · 数算得对,而这张表不能用来比渠道" python3 backend/channel_check.py
run "评测来路 · 哪家跑的、同一版跑两次差多少" python3 tools/eval_provenance_check.py
run "判据词表 · 声称有备选,就得验过一条备选" python3 tools/vocab_check.py
run "钉死的锚点 · 抓同源谬误(手抄不现算)" python3 knowledge/pinned_check.py
run "产能排期 · 工种/一人一机/产能缺口" python3 knowledge/capacity.py
run "工期推算 · 并行链路/除不动/婚礼倒推" python3 knowledge/leadtime.py
run "回答体检 · 人造用例(正反各半)" python3 agentsite/guards_test.py
run "「当前方案」注入 · 列清单不算取过" ./agentsite/.venv/bin/python agentsite/scheme_hook_test.py
run "Skill 与配置面 · 设置源放开后的锁" ./agentsite/.venv/bin/python agentsite/skills_check.py
run "中文否定与子串 · 29 条(十次踩过的坑)" python3 agent/textmatch.py
run "判分器自测 · 18 条人造用例" python3 agent/chat_eval_judgetest.py
run "工具评测判分器 · 21 条对照用例" python3 agent/tool_eval_judgetest.py
run "成长评测判分器 · 22 条对照用例" python3 agent/growth_eval_judgetest.py
run "识图判分器 · 13 条对照用例" python3 agent/vision_eval_judgetest.py
run "判责判分器 · 14 条对照用例" python3 agent/liability_eval_judgetest.py
run "白坯试衣判分器 · 库状态看开没开裁 / 签没签,措辞只查两处结构" python3 agent/fitting_eval_judgetest.py
run "评测判据 · 点名的工具必须在架上" python3 tools/judge_tool_names_check.py
run "指代推进判分器 · 15 条对照用例" python3 agent/scheme_eval_judgetest.py
run "指代推进 · 四类场景库里都挑得出样本" python3 agent/scheme_eval.py
run "运维侧判分器 · 对照用例(含库存预警、白坯试衣)" python3 agent/ops_eval_judgetest.py
run "复盘与漏斗判分器 · 31 条对照用例" python3 agent/report_eval_judgetest.py
run "会员与审批判分器 · 30 条对照用例" python3 agent/member_eval_judgetest.py
run "工匠与财务判分器 · 27 条对照用例" python3 agent/role_eval_judgetest.py
run "版师判分器 · 38 条对照用例" python3 agent/pattern_eval_judgetest.py
run "野外巡检 · 指纹粒度与行为观测" python3 agent/wild_run.py --selftest
run "野外语料 · 多样性(够多≠够杂)" python3 agent/wild_corpus.py --selftest
run "提交闸 · 退出码不许被吞(22 条咬合)" node tools/hooks/commit-gate-exitcode.mjs --selftest
run "CI 提醒 · 报的是现在红绿不是历史(18 条咬合)" node tools/hooks/push-then-ci.mjs --selftest
run "工具还是技能 · 新增工具时问一句该由谁判断(8 条)" node tools/hooks/tool-or-skill.mjs --selftest
run "链路口径 · 「没接上」和「没记过」是两件事(21 条自测)" python3 knowledge/linkage.py
run "旅程口径 · 一次量体是一次触点(16 条自测)" python3 knowledge/journey.py
run "归因口径 · 两种分成的校验方向相反(26 条自测)" python3 knowledge/attribution.py
run "排班口径 · 查不到记录只能表示「还没排」(18 条自测)" python3 knowledge/shift.py
run "促活口径 · 时间相对他自己,没由头不进名单(25 条自测)" python3 knowledge/reactivate.py
run "商机口径 · 分清是谁说的,别枚举中文说法(19 条自测)" python3 knowledge/oppo.py
run "归属口径 · 分开只因为下一步不同(15 条自测)" python3 knowledge/owner.py
run "评测指纹 · 行数没变但内容改了,指纹也得变(7 条自测)" python3 agent/fingerprint.py --selftest
run "首次启动 · 建出来的库要和在用的库一样全(5 条咬合)" python3 backend/initpath_check.py
run "交接门禁 · 过 80% 不许收工;交接在项目根、会话在子目录也要找得到;照提示提前刷了要放行(18 条)" node tools/hooks/handoff-gate.mjs --selftest
printf "\n%s\n" "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then printf "\033[32m✅ 全部检查通过\033[0m\n"; else printf "\033[31m❌ 存在失败项\033[0m\n"; fi
exit $FAIL
