#!/bin/bash
# 一条命令跑完全部检查。任一失败即整体失败。
cd "$(dirname "$0")"
# 库正在重建时不跑 —— 这时候的红不代表任何东西(见 tools/rebuild.sh 开头的互斥标记)
if [ -f backend/.rebuilding ] && kill -0 "$(cat backend/.rebuilding)" 2>/dev/null; then
  echo "⏸  库正在重建(pid $(cat backend/.rebuilding)),这时候跑出来的红不代表任何东西 —— 等它跑完再跑"
  exit 3
fi
FAIL=0; BAD=0; CRASH=0
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
# ⚠️ **「判定不过」和「根本没跑完」要分开数。**
# 2026-09-24:我自己 grep 输出里的「❌」来判断门禁绿不绿,而 gate_test 崩在
# TypeError 上 —— **崩溃不打印那个字**,于是「0 个 ❌」被我读成了全绿,
# 是并行会话发消息才知道是红的。
# 崩了和判定不过,下一步完全不同:一个是「这条检查压根没验过」,
# 一个是「验了,不合格」。收尾行把两个数分开报。
# ⚠️⚠️ **每条检查都有一道墙** —— 2026-10-09 加的,因为挂住**看起来不像红**。
#
# 那天 `agent/trace_check.py` 里一条没加锚点的前瞻正则变成了 O(n²),
# 跟着 `backend/api.py` 长到 28.8 万字之后要跑约 3 小时。
# CI 上的表现:主门禁这个 job 跑到 20 分钟撞上 `timeout-minutes: 20`,
# 列表里显示一条 **`cancelled`**。
#
# > **一条「挂住被掐」的 `cancelled`,和一条「新 push 把旧 run 掐掉」的 `cancelled`,
# > 在 run 列表上长得一模一样** —— 于是它连着挂了 4 次都没人当成红。
# > 我自己也是核了「被掐的时刻有没有新 push」才分清的。
#
# 所以超时要在**这里**变成一条明确的红,而不是指望外层 job 的墙。
# 并且它归到**「崩了 / 没验过」**那一类,不是「判定不过」——
# 它确实一个字都没验,和「验了不合格」下一步完全不同。
#
# 墙定在 600 秒:现存最慢的一条也远低于它,所以**只有真挂住才会撞上**。
# 要调用 `CHK_TIMEOUT=900 ./check.sh`(别为了让某条过去而放宽,先问它为什么慢)。
# ⚠️ 这台机器**没有 `timeout(1)`**(macOS 不带,也没装 coreutils),所以用 python3 当看门狗。
# ⚠️ bash 的变量名**只能是 ASCII** —— 写 `每条超时=600` 会当成命令去执行。
#    (这是中文标识符第 5 次咬人,前 4 次在工具 schema 的属性名上。)
CHK_TIMEOUT=${CHK_TIMEOUT:-600}
run(){ printf "\n\033[1m▸ %s\033[0m\n" "$1"; shift
  local rc=0
  python3 -c 'import subprocess, sys
try:
    sys.exit(subprocess.run(sys.argv[2:], timeout=int(sys.argv[1])).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)' "$CHK_TIMEOUT" "$@" > /tmp/chk.out 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    tail -3 /tmp/chk.out | awk '{print "  " $0}'
  elif [ "$rc" -eq 124 ]; then
    FAIL=1; CRASH=$((CRASH + 1)); awk '{print "  " $0}' /tmp/chk.out
    printf "  \033[31m✗ 超过 %s 秒没跑完,被掐了(这条检查没验过)\033[0m\n" "$CHK_TIMEOUT"
  else
    FAIL=1; awk '{print "  " $0}' /tmp/chk.out
    if grep -qE 'Traceback \(most recent call last\)|^[A-Za-z]*Error:|command not found|No such file' /tmp/chk.out; then
      CRASH=$((CRASH + 1)); printf "  \033[31m✗ 崩了(这条检查没验过)\033[0m\n"
    else
      BAD=$((BAD + 1)); printf "  \033[31m✗ 失败\033[0m\n"
    fi
  fi }
run "数据层 · truth 表隔离"   python3 backend/selftest.py
run "写入口身份闸 · 没登录不许改业务数据(打 HTTP 层)" python3 backend/authgate_check.py
run "员工登录 · 5 条自测" python3 backend/auth.py
run "路由 · handler 必须真的存在" python3 backend/route_check.py
run "只读入口冒烟 · 54 个入口真跑一遍(handler 存在≠跑得起来)" python3 backend/page_smoke_check.py
run "写接口冒烟 · 在库的副本上真写一遍(返回 ok≠写进去了)" python3 backend/write_smoke_check.py
run "产品文档 · 写死的数字和代码对账(文档变假时不会报错)" python3 tools/doc_numbers_check.py
run "写接口 · 往返(临时副本上跑,不碰真库)" python3 backend/write_check.py
run "业务写入规则 · 11 条触发覆盖" python3 backend/writerule_check.py
run "边界审计 · 每条保证真的攻击一次" python3 backend/boundary_audit.py
# chat 接管理后台那份 RAG 这条桥(2026-10-08 接的,业务拍的第 ④ 步)。
# ⚠️ 盯三件**坏了不报错**的事:退路悄悄长回来 / 岗位→角色的映射被改大 /
# 管它的那条规矩(TL64)被改软。零 IO,不调模型、不发请求,所以能进门禁。
run "chat→RAG 这条桥 · 退路 / 角色映射 / TL64 三件不许被改软" \
    python3 backend/rag_bridge_check.py
# 2026-09-26:booking.py 用机器时钟写 schedule.assigned_at,而世界停在别的日子;
# 平移把它一天一天往未来推 —— **这个 bug 不会自愈**,而 C4 抓到的只是症状。
# 这条抓原因:写「已发生的事」那几列的地方,必须用 backend/worldclock.py。
run "世界时钟 · 写已发生的事不许用机器时钟(4 条咬合)" python3 backend/worldclock_check.py
run "提示词 · 单一源头与按工具装配" python3 tools/prompts_check.py
# ⚠️ 这一条不只验「文件里有没有」,它验**「现在跑着的 SCHEMAS 里到底有没有」** ——
# 也就是 `api.py` 末尾那一行接线还在不在。
# 数据在文件里而没人读它,就是「声明了而没生效」,而那种状态**看起来一切正常**。
# 它还会报出「有多少条评测题的题面进了提示词」(业务 10-03 知情后拍的「全拼进去」)——
# **代价被接受了,不等于代价可以看不见**:拿这份说明跑的评测,报分要带上那个数。
run "工具模型说明 · 三样真的拼进了模型读到的那段吗(以及多少条题面进了提示词)" \
    python3 backend/工具模型说明.py
# ⚠️ **仓库里的 hook ≠ 真正在跑的那份。** 2026-10-04 栽了一次,而且栽得很像成功:
# 修了 `tools/hooks/push-then-ci.mjs`、补了四条自测、22/22 全绿、提交推送 ——
# **而真正在喊话的是 `~/.claude/hooks/` 下 9 月 17 日的一份拷贝。**
# 一个改了而没生效的 hook,和一个生效了的,在它打出的那句提示上长得一模一样。
# 四份里三份现在内容一样 —— **正因为它们一样,才看不出这个机制会漂。**
run "hook 同步 · 改了仓库那份不等于它生效了" python3 tools/hook_sync_check.py
# 「页面上的旋钮不许是假的」—— 每个旋钮声明的落点必须真的被后端读到。
# 假旋钮(界面能拧、后端不读)比没有这个功能糟:拖动它什么都不变,而人会以为自己在调。
run "调参旋钮 · 落点真接上了、只许收窄不许放宽(5 条咬合)" python3 agent/knobs_check.py
# 2026-09-25 真踩到:三个读接口写进了 do_POST,而页面用 GET 取 ——
# **浏览器里整块功能加载不出来,而后端和所有静态检查都正常**。
# 「路由写错处理器」和「路由压根没写」,在 do_GET 里看起来一模一样。
run "页面 fetch 的地址 · 后端接得住,而且在对的那个处理器里(2 条咬合)" python3 agentsite/fetch_route_check.py
run "上下文注入 · 有没有两处在管同一件事(打架时贴着用户消息的那处会赢)" python3 tools/context_conflict_check.py
run "生命周期口径 · 自测" python3 knowledge/lifecycle.py
run "会员生命周期 · 14 条边界标注对账" python3 backend/member_check.py
run "预约派单 · 逐例标真值(派错和派对长得一样)" python3 backend/booking_check.py
run "促活判断 · 逐例标真值 + 覆盖报告(没有样本不叫通过)" python3 backend/revive_check.py
run "流失预警取数 · 列名/只读/转发对账 + 覆盖报告(没有样本不叫通过)" python3 backend/slipping_check.py
run "简体闸 · 业务数据一律简体(外来文本进来前先查)" python3 backend/simplified.py
run "商机判断 · 24 条逐字稿(造的对话·纯规则版·只许升不许降)" python3 backend/opportunity_check.py
run "商机对象 · 指回通话、和方案互指、两种终态分得开、诉求指得回原话" python3 backend/opportunity_obj_check.py
run "商机提醒进顾问待办 · 规则只提示、选结论才改、满足了才记偏好、作废的偏好不再推" python3 backend/opportunity_task_check.py
run "商机研判判分器 · 24 条对照(原话只认客户说的、指向真在库里且归这位客户、不给成单概率)" python3 agent/oppo_eval_judgetest.py
run "录音接进流程 · 双声道按声道分、单声道模型分(答歪整通标未分)、失败落库、上传核门店" python3 backend/call_flow_check.py
run "录音同意 · 不能撤回所以界面没有撤回入口、不进 consent 表、每通录音记着依据(业务 D9)" python3 backend/recording_terms_check.py
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
run "报价口径 · 报价是事件不是状态、算错了作废不改(31 条自测)" python3 knowledge/quote.py
run "报价写口 · 五样缺一不许落库、报两次两行、作废留痕(库副本)" python3 backend/quote_write_check.py
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
run "运营 SOP · 生成的和现在的口径对得上(下单 / 开裁 / 判责 / 铁律)" python3 tools/make_sop.py --check
# 营销 SOP:八节各自对着一个口径模块(生命周期/促活/挽回/预约/活动/归因/渠道/价格)。
# ⚠️ 它和运营 SOP 同一个机制 —— **改了口径不重新生成就红**,并指出第几行起不一样。
# 而 `--check` 不只比字符串:还验节数=8 和几个必含项 ——
# 一份被整体清空又重新生成的**空 SOP 也能「对得上」**。
run "营销 SOP · 生成的和现在的口径对得上(八节 · 最值钱的是「不该做什么」那一段)" \
    python3 tools/make_mkt_sop.py --check
# ⚠️ **数据够不够是现查的,不写进 SOP** —— 2026-10-05 CI 红过一次:
# SOP 里写着「预约覆盖 72%」(本机造数之后),而 CI 从零建库算出来是 0%。
# > 一份「按本机库生成」的 SOP,和一份「按 CI 从零建的库生成」的,
# > **在那份 md 上长得一模一样** —— 而那几个数不同。
# 而那个数**本来就不该在那儿**:它是演示库的数,不是真实业务的。
# 这一条**只报状态,不拦门禁**(数据够不够是业务进度,不是代码错误)。
run "营销数据体检 · 那几类触点够不够(只报状态,永不拦)" \
    python3 tools/mkt_data_health.py
run "竞品与行业 · 每条有日期、过期会自己说、真有人引用" python3 backend/competitor_check.py
run "知识库扩容 · 每条详解说得出回答了什么问题、有出处、不漏进工艺表" python3 backend/kb_depth_check.py
run "咬合记录 · 最贵的那一步不许只在脑子里" python3 tools/bite_check.py

# 执行上限的落点对账(规格「工具调用上限与防循环监控」P0-A)。
# ⚠️ 这一条红的时候,**红的通常不是代码,是那张登记表过期了** ——
# 而「规格里写的现状」和「现在真实的现状」在那张表上长得一模一样。
# ⚠️ **这一条 2026-10-04 才挪进来,而它该在这儿很久了。**
# `alembic check` 原来只装在 `管理后台/Makefile` 的 `make test` 里,
# 而我跑的是 `make contract` + `./check.sh` —— 两个都不含它。
# 后果这个仓库吃过三次(两次记在那个 Makefile 的注释里,第三次是 10-04 的我):
# 手工把约束写进迁移、没登记进 `models._额外唯一`,**本地全绿、CI 两次红**。
# > **一条判据装在一个我从来没跑过的目标里,等于没装。**
# > 而「本地没跑过」和「跑过并通过」,在那份本地绿报告上长得一模一样。
run "契约和库一致吗(手工写进迁移的约束,模型里漏声明会被安静删掉)" \
    python3 管理后台/tools/alembic_sync_check.py
# ⚠️ **2026-10-04 加,补的是一个没人看的洞。**
# 我往契约加了三条端点、重跑 gen_openapi,OpenAPI 从 101 涨到 103 条 ——
# 而代码里一个路由都还没写,**没有任何东西会发现这件事**:
# spec_coverage 验的全是契约内部自洽(最新 / 有权限 / 幂等落成 header)。
# > 一份声称有 103 条路径的 OpenAPI,和一个真提供 103 条路径的服务,
# > **在那份文档上长得一模一样** —— 而调用方照着打会拿到 404。
# (澜绣那侧早有一条「路由 · handler 必须真的存在」,这边一直没有对等的。)
run "契约端点 · 代码里真有那个路由吗(文档说有而实际 404,文档和契约都是绿的)" \
    python3 管理后台/tools/route_exists_check.py
# ⚠️ **2026-10-06 加,因为它咬到了:CI 红在 `cd6c4fa` 上。**
# 我给 `execution_runs` 加了两列(改的是契约),而**契约文档是从契约生成的** ——
# 改了源没重跑生成器,那份 md 停在上一版。
# > 一份「和契约一致」的契约文档,和一份「还是上一版」的,
# > **在那份 md 上长得一模一样** —— 而读它的人会按旧的那份理解这张表。
#
# ⚠️ 而更该记的是**为什么本地没拦住**:上面第 189 行那句注释提到了
# `spec_coverage`,于是我 `grep -c spec_coverage check.sh` 得到 1、以为它在门禁里。
# > 一行「提到某个检查」的注释,和一行**真跑它**的 run,
# > **在 grep 的计数上长得一模一样。**
# 这是这个项目第三次栽在「我写了检查 ≠ 检查在跑」上
# (`.pyc` 那次 · 43 条对抗测试那次 · 这次),所以把它搬进来。
# **它不需要数据库**,所以放在这儿没有外部依赖。
# ⚠️ **它要 `管理后台/.venv`(sqlalchemy)**,而 CI 的 check job 不装那个 venv ——
# 2026-10-06 我搬它进来时写死了 venv 路径,CI 当场崩在
# `No such file or directory`。而我本机有那个 venv,所以**本地全绿**。
# > 一条「在有 venv 的机器上跑得过」的检查,和一条「到处都跑得过」的,
# > **在我本机那个绿勾上长得一模一样。**
# 旁边两条(alembic / 路由)早就处理过同一件事:**没有就报「不适用,不是通过」**。
# ⚠️ 判在**外面**,不在脚本里包 try —— 它在 import 阶段就会炸,
# 而包进 try 之后「这台机器没装 venv」和「import 写错了」就再也分不开了。
if [ -x ./管理后台/.venv/bin/python ]; then
  run "契约内部自洽 · 契约文档是最新的 / 端点有权限 / 幂等落成 header" \
      ./管理后台/.venv/bin/python 管理后台/tools/spec_coverage.py
else
  printf "\n\033[1m▸ %s\033[0m\n" "契约内部自洽 · 契约文档是最新的 / 端点有权限 / 幂等落成 header"
  printf "  ⏸ 没有 ./管理后台/.venv —— **不适用,不是通过**(这台机器没装那个 venv;CI 的 admin-e2e job 里有)\n"
fi
# ⚠️ **2026-10-04 加,因为用户在「加资料」页上撞到了它。**
# 一行反引号把模板字符串截断,紧跟的 `.md` 变成**模板标签调用** ——
# 而「字符串不是函数」只在运行时炸。整页渲染不出来,
# 用户连文件选择框都看不到,所以「加资料一直报错」根本没走到上传那三步。
# > **一段语法完全合法而一跑就炸的代码,和一段正确的,
# > 在语法检查器眼里长得一模一样。**
# `js_check.py` 修前修后都绿;而真跑的那一半(js_smoke)要起服务、进不了门禁。
# 这一条把「真跑」做成**不依赖外部状态**的:接口全打桩,只验跑得起来。
run "页面函数 · 每个都真跑一遍(语法合法而一跑就炸,语法检查看不见)" \
    node 管理后台/tools/page_render_check.js
run "执行上限 · 每条现在到底在哪儿执行(填得进去而没人读的上限最毒)" \
    python3 管理后台/tools/exec_limits_report.py
run "执行上限清单 · 五种状态各判对了吗(21 条自测)" \
    python3 管理后台/tools/exec_limits_report.py --selftest
run "截断的报告要说「还有几条」(只许少不许多)" python3 tools/truncation_check.py
run "INSERT 要写具名列 —— 列数恰好相等而顺序错了是不报错的(位置参数只许少不许多)" python3 tools/insert_shape_check.py
run "门禁外的检查多久没跑了(只报状态,永不拦)" python3 tools/runlog_check.py
run "评测轮次 · 调模型的评测不许只跑一轮(只许少不许多)" python3 agent/rounds_check.py
run "部分覆盖 · 跑一部分题不许覆盖完整基线(只许少不许多)" python3 agent/partial_write_check.py
run "轮次报告 · 单轮/抖动/可比,四种情形都说对话" python3 agent/rounds.py
run "仓库自洽 · 工作区绿不等于仓库里那一版绿" python3 tools/repo_consistency_check.py
run "评测题面 · 有指代就得有编号,或写明是故意的" python3 tools/case_check.py
run "改动影响面 · 警示段落找不着就是正则漏了" python3 tools/impact.py --selftest
run "评测夹具 · 写死了对象就得声明前提,而前提得成立" python3 tools/fixture_check.py
run "状态流转引擎 · 17 个用例" python3 backend/fsm.py
run "写入校验规则 · 11 个用例" python3 backend/rules.py
run "控件审计 · 死控件检查"    python3 backend/ui_audit.py
run "页面内联 JS · 语法(两个站都扫)" python3 agentsite/js_check.py
run "前端 · 引用的元素必须存在" python3 agentsite/ref_check.py
run "聊天查订单 · 卡片那头:每张卡片逐条复核 + 总数不是卡片数(41 条)" python3 tools/chat_order_cards_check.py
run "聊天查订单 · 弹窗那头:越权要拦 + 商品/图/定制内容(46 条)" python3 backend/chat_order_check.py
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
run "树状记录仪 · 自测(抹凭据/截断/排树/孤儿不丢)" python3 agent/spans.py --selftest
run "树状记录仪结构 · 接没接上、树是不是树、凭据没进日志(8 条咬合)" python3 agent/spans_check.py
run "实验对比 · 先判对比成不成立再给分(题号字段各套不同/换模型拒收)" python3 agent/compare.py --selftest
run "页面骨架 · 一块放错父容器,框架正常但内容被顶出可视区(2 条咬合)" python3 agentsite/layout_check.py
run "导航 · 每个页面都有入口,而且入口只有一个来源(2 条咬合)" python3 agentsite/nav_check.py
run "自有工坊报工判分器 · 15 条人造对照(话说得漂亮但手动了照样挂)" python3 agent/workshop_eval_judgetest.py
run "AI 调控中心 · 没做的模块不给假入口;咨询详情五段齐(21 条自测)" python3 agentsite/aihub.py --selftest
run "提示词候选 · 不指定就用源头、找不到就抛、没验证不许采纳(7 条自测)" python3 tools/prompt_candidate.py --selftest
run "演示世界的日期 · 世界跟着真实日期走,库说的和数据实际的要对得上(4 条咬合)" python3 tools/shift_world.py --check
# ⚠️ 上面那条判的是**数据**落后了没有,而它要落后 **14 天**才判红 ——
# 也就是说每日平移那个定时任务挂了之后,**两周内没有任何信号**,
# 而这两周里每个人都以为世界在跟着真实日期走。
# 下面这条判的是**任务本身还在不在跑**,而且把两种失败分开:
# 「装了却没在跑」去修任务,「在跑但每次失败」去看日志。
# ⚠️ **没装不算红** —— CI 和别人的机器上本来就没有这个任务,
# 而一条永远红的检查和一条永远绿的检查一样没用。
run "每日平移的定时任务还在不在跑(没装不算红;装了却不跑、跑了但没成功过都算红)" python3 tools/cron_health_check.py
run "完成日不许在未来 · 旅程排到今天之后的单要挪回来" python3 tools/clamp_future_done.py
run "知识库 · 与 craft 表一致"  python3 knowledge/check_kb.py
run "相容矩阵 · 2025 格推导/对账/落库" python3 knowledge/derive_combo.py
run "版型库与 BOM · 推档/裁片/物料对账" python3 knowledge/derive_pattern.py
run "量体推荐 · 三档判定/放松量/齐胸特例" python3 knowledge/fitting.py
run "成长推算 · 百分位/靶身高/复量周期" python3 knowledge/growth.py
run "纹样口径 · 名字/面料/工艺推导,补子不许猜" python3 knowledge/motif.py
run "用户生命周期 · 着装人/家庭/同意/过期量体" python3 backend/lifecycle_check.py
run "数据规范 · 身份/关联/覆盖(对照 数据规范.md)" python3 backend/spec_check.py
run "订单摊得开 · 没人越过上限、无单客户不许变多(棘轮)" python3 backend/order_spread_check.py
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
run "下单口径 · 逐件判下单量体(没有 / 早于开单 / 缺项不可以,判不了不当可以)" python3 knowledge/order_place.py
run "下单写口 · 开单停待确认、没量不许确认、后台绕不过、确认即付款(在库副本上跑)" python3 backend/order_write_check.py
run "工厂回传口径 · 重复只记一次、来早了暂存、未来/倒挂拒收、该催(判不了不推)" python3 knowledge/factory_feed.py
run "工厂回传写口 · 生产和发货只认回传、乱序能放行、后台推不动、该催的都在(在库副本上跑)" python3 backend/factory_inbox_check.py
run "白坯试衣 · 「没走流程」和「走了没拿到确认」不许混成一个" python3 backend/muslin_check.py
run "白坯试衣写口 · 开裁那道闸会拦、后台改状态也绕不过、签字撤不掉(在库副本上跑)" python3 backend/fitting_write_check.py
run "交付签收口径 · 6 位码只认一单用一次、追认满 15 天要理由、不合身判责不默认顾客" python3 knowledge/pickup.py
run "未来记录回挪 · 自测(签收在未来也算、分钟粒度不许早于下单、在办的单不动)" python3 tools/clamp_future_done.py --selftest
run "交付签收写口 · 码核验才签收、不合身订单不动、完成要顾客确认或追认(在库副本上跑)" python3 backend/pickup_write_check.py
run "报修口径 · 店长判完、顾客同意才开工" python3 knowledge/repair.py
run "供应商 · 两类质量不合成一个分/自己做的工艺不许挂供应商/不是一个SKU一家(14 条)" python3 backend/supplier_check.py
run "评价口径 · 没签收不许评、≤3 星算差评自动进待处理清单(44 条自测)" python3 knowledge/rating.py
run "毛利口径 · 缺一项就算不出、毛利率和覆盖率绑着报(24 条自测)" python3 knowledge/margin.py
run "评价写口 · 闸读签收记录不读订单状态、差评自动进 task 清单(库副本)" python3 backend/rating_write_check.py
run "评价造数 · 门店差距/趋势/不静默夹逼(合成夹具自证)" python3 tools/backfill_rating.py --selftest
run "评价数据 · 没签收就评/差评没进清单/两处状态打架(9 条判据在合成夹具上自证)" python3 backend/rating_check.py
run "判读回流上报 · 词表归一/trace 挂不上要说出来/外部trace 别现编(18 条)" python3 agent/feedback_report_check.py
run "用量上报 · 供应商拼法/是mock不默认/写不进去也不抛(15 条)" python3 agent/usage_report_check.py
run "评价概况(看的那一头)· 口径承诺的两个切分工具真给了、趋势不拿残月当起点(14 条)" python3 backend/rating_view_check.py
run "评价判分器 · 25 条对照(星级不是衣服质量/不换算满意度/不给人排序)" python3 agent/rating_eval_judgetest.py
run "报修写口 · 哪一件不猜、店长判责、同意要凭据、回店输码才完成(在库副本上跑)" python3 backend/repair_write_check.py
run "多渠道对比 · 数算得对,而这张表不能用来比渠道" python3 backend/channel_check.py
run "评测来路 · 哪家跑的、同一版跑两次差多少" python3 tools/eval_provenance_check.py
run "评测来路章 · 章上的供应商和真正发请求的是同一家" ./agentsite/.venv/bin/python tools/evalrec_provider_check.py
run "提示词里的数 · 体检认它算出处,所以它得在知识库里找得到" ./agentsite/.venv/bin/python tools/prompt_numbers_check.py
run "按月查 · 某月进入休眠的客户 / 某月的订单(期望值另用 SQL 算)" python3 backend/month_query_check.py
run "判据词表 · 声称有备选,就得验过一条备选" python3 tools/vocab_check.py
run "钉死的锚点 · 抓同源谬误(手抄不现算)" python3 knowledge/pinned_check.py
run "产能排期 · 工种/一人一机/产能缺口" python3 knowledge/capacity.py
run "工期推算 · 并行链路/除不动/婚礼倒推" python3 knowledge/leadtime.py
run "回答体检 · 人造用例(正反各半)" python3 agentsite/guards_test.py
run "「当前方案」注入 · 列清单不算取过" ./agentsite/.venv/bin/python agentsite/scheme_hook_test.py
run "Skill 与配置面 · 设置源放开后的锁" ./agentsite/.venv/bin/python agentsite/skills_check.py
run "工具收窄落到 MCP 那一层 · 真起服务读回、空集合不扩成全部、提示词按生效工具装(外部审阅 4.3)" ./agentsite/.venv/bin/python agentsite/tool_scope_check.py
run "每一份候选答案都检查 · 修正后通过 / 未通过 / 未检查 / 不完整分开,未通过的不当正式答复交(外部审阅 4.1)" ./agentsite/.venv/bin/python agentsite/delivery_check.py
run "会话的业务状态跨请求恢复 · 只恢复跨轮的、先核归属和权限、方案被删不带回、并发不覆盖(外部审阅 4.2)" ./agentsite/.venv/bin/python agentsite/session_state_check.py
run "中文否定与子串 · 29 条(十次踩过的坑)" python3 agent/textmatch.py
run "判分器自测 · 人造用例(两个方向)" python3 agent/chat_eval_judgetest.py
run "工具选择判分器 · 20 条对照(「全部必需都在」不是「至少一个」)" python3 agent/select_eval_judgetest.py
run "工具筛选准入线 · 23 条(线随走不走缓存漂 8 倍,所以不许写死)" python3 agent/tool_select_judgetest.py
run "工厂回传判分器 · 37 条对照(写好那天起就没进过门禁,10-03 补)" python3 agent/factory_eval_judgetest.py
run "自测都进了门禁 · 没注册的自测和不存在的自测在绿勾上长得一样" python3 tools/selftest_registry_check.py
run "工具评测判分器 · 21 条对照用例" python3 agent/tool_eval_judgetest.py
run "成长评测判分器 · 22 条对照用例" python3 agent/growth_eval_judgetest.py
run "识图判分器 · 13 条对照用例" python3 agent/vision_eval_judgetest.py
run "判责判分器 · 17 条对照用例" python3 agent/liability_eval_judgetest.py
run "白坯试衣判分器 · 库状态看开没开裁 / 签没签,措辞只查两处结构" python3 agent/fitting_eval_judgetest.py
run "量体录入判分器 · 库状态看写了哪几行 / 值 / 谁量的 / 绑没绑,措辞只查问没问" python3 agent/measure_eval_judgetest.py
run "交付签收判分器 · 库状态看订单状态 / 码试错次数 / 到店 / 取件方式,措辞只查问没问" python3 agent/pickup_eval_judgetest.py
run "下单判分器 · 库状态看开出的单 / 单的状态 / 旧量体改没改绑,措辞只查问给谁做" python3 agent/order_eval_judgetest.py
run "报修判分器 · 库状态看新单 / 返修单状态 / 判责有没有被写上,措辞只查问没问" python3 agent/repair_eval_judgetest.py
run "评测判据 · 点名的工具必须在架上" python3 tools/judge_tool_names_check.py
run "指代推进判分器 · 15 条对照用例" python3 agent/scheme_eval_judgetest.py
run "指代推进 · 四类场景库里都挑得出样本" python3 agent/scheme_eval.py
run "运维侧判分器 · 对照用例(含库存预警、白坯试衣)" python3 agent/ops_eval_judgetest.py
run "复盘与漏斗判分器 · 31 条对照用例" python3 agent/report_eval_judgetest.py
run "会员与审批判分器 · 30 条对照用例" python3 agent/member_eval_judgetest.py
run "销售话术判分器 · 25 条对照用例(含判官抄不回原话就不算数)" python3 agent/talk_eval_judgetest.py
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
run "订单范围口径 · 顾问那一档是并集,三档之外不兜底(36 条自测)" python3 knowledge/order_scope.py
run "流失预警口径 · 八档不是一条线、预警不等于名单(74 条自测)" python3 knowledge/churn.py
run "商机口径 · 分清是谁说的,别枚举中文说法(19 条自测)" python3 knowledge/oppo.py
run "归属口径 · 分开只因为下一步不同(15 条自测)" python3 knowledge/owner.py
run "评测指纹 · 行数没变但内容改了,指纹也得变(7 条自测)" python3 agent/fingerprint.py --selftest
run "首次启动 · 建出来的库要和在用的库一样全(5 条咬合)" python3 backend/initpath_check.py
run "交接门禁 · 过 80% 不许收工;交接在项目根、会话在子目录也要找得到;照提示提前刷了要放行(18 条)" node tools/hooks/handoff-gate.mjs --selftest
printf "\n%s\n" "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then printf "\033[32m✅ 全部检查通过\033[0m\n"
else
  printf "\033[31m❌ 判定不过 %d 条 · 崩了 %d 条\033[0m\n" "$BAD" "$CRASH"
  [ "$CRASH" -gt 0 ] && printf "   \033[31m崩了的那几条**一条都没验过**\033[0m —— 和「验了不合格」不是一回事,先修崩的\n"
  printf "   ⚠️ **判绿看退出码,别数输出里的 ❌** —— 崩溃 / 超时 / 没跑到底,这三种都不打印那个字\n"
fi
exit $FAIL
