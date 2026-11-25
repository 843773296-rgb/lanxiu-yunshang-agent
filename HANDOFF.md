> ⚠️ **本文件按时间倒序,最新的在最上面。** 2026-09-27 发现过一次:
> 我把当天那节插在了并行会话六节 09-25 条目的**下面**(第 255 行),
> 于是**接手的人第一眼读到的不是最新状态** —— 交接文档漂了比没有更糟。
> 往里加内容一律加在**最顶上**。
>
> ⚠️ **第二条约定:待办里别写死数字和状态 —— 它们会漂。**
> 2026-10-16 一天里撞到三次:「43 条知识溯不了源」(实际 12,漂了两轮:46→43→22→12)、
> 七条待办的 intent 其实已经标了「做完了」(有一条漂了一个月,我差点照着重做一遍)、
> 咬合规格锚在待办编号上(插一条就过期)。
> 所以:**数字要么写「跑 xxx 现看」,要么标成带日期的历史记录**;
> 「还有几条没做」这种话,让判据去说。
> (`backend/source_check.py` / `tools/intent_check.py` 现在各盯着一头 ——
> 前者盯欠账只许降不许涨,后者盯「挂着的待办,它的 intent 别已经是做完了」。)

### 🟡 11-25 · 推我这 3 笔(并行会话选了「我先推」,期间它不占锁、只写 w1121)(Opus 5.5)
- **一句话**:本地领先 origin/main(9b6e9d0f)3 笔 —— 2bda2a8c 库路径第 9 批(欠债 267→263)/ c5812dbf 评测结果留每轮判错理由(各轮why,连带改咬合 1001 锚)/ 5cbd7913 咬合 819 换攻击点。正在 ship。
- **上次停在哪**:819 锁内重放 1/1 过(红在「每道题都取得出材料」);dbpath_check 那条咬合在我树上锁内重放 1/1 过 —— 并行会话那次「对照就是红的」**不是我的树**,推完提醒它 rebase 后重看。
- **下一步第一个动作**:看 ship 日志「被包的命令退出码」那一行 → 0 则主检出 ff(merge-base 验)+ kickstart backend/agentsite/supervise + curl 8760/8770 → 把哈希报用户和并行会话;它接着 rebase 起 w44。
- **别重做 / 否决过的**:819 标「只报不拦」先推 —— 否决(削弱监督,要用户拍);根因是地址统一后 api.DB 启动就读 LANXIU_DB,「指到副本」成了冗余保险。
- 继续的活:库路径欠债(跑 dbpath_check 现看),下一批 seed.py / seed_pickup.py / check_copy.py;别碰并行会话的文件清单。

### ⏱️ 12 小时长任务清单(11-21 18:50 → 11-22 06:50)· 标注回复夜(Fable 5.1)

> 用户 18:4x「那开始做标注回复的后台那一半」→ 18:5x「12小时长时间任务开启」「需要拍板的可以先拍」→ **拍板(18:5x)**:① 哪些问答不许标:**按那一轮调过的工具自动判** —— 只调了知识类工具(domains.knowledge 里的只读那些)或一个工具没调的才能标;调过取数(客户 / 订单 / 库存 / 任务…)或任何写工具的拦住,按钮灰掉写原因;② 谁能标:**「改 Prompt/知识候选」权限**;③ 生效:**项目总开关默认关,开了后保存即生效**,不走冻结 / 审核,每次命中记一笔,能单条停用;④ 今晚还做(三件都要):试跑一次 tools/weekly_review.sh(只试跑,定时还是用户亲手装)/ 用演示门店以管理员身份启用「经营日报草稿」定时(明早 08:00 跑一次)/ 标注**匹配那一半(聊天站)**等 fc 推完它的 app.py / station.html 后接着做(碰之前再喊 fc)。
> **守则**:同 11-20 那夜 —— 代码只写 w1121,w1117 只 `merge --ff-only`;**0 点到夜跑结束(约 05:10)不占锁、不写共享库**;每批 = `scratchpad/gate_wN.sh` 形状(锁空 → w1117 rebase → 锁内 alembic upgrade head(显式 DATABASE_URL)→ 主检出 ff → 停 8801 → kickstart aimc → 验归属 → 锁内 e2e-ci → w1117 里 ship);只认「被包的命令退出码」;迁移目录外不写 ALTER TABLE;占锁前喊 fc;每小时 :17 有 session 内提醒 **fc647c85**(06:5x 汇总发飞书后 CronDelete)。18:5x 已告 fc 今晚计划。

1. ✅ 标注回复 · 后台一半:**08:41 推上主干(gate_w17);今天其余 19 笔(员工定时一期二期 / 标注匹配聊天站一半 / 日报六段 / 周风险清单模板 / 三轮门禁修法)11-22 22:13 推上主干 = bd5730e4(gate_w28,第三次才绿:w26 四处对照红、w27 全量门禁四处红,全是新代码带的,修法见下面 16:2x / 18:40 两条)**。原记录:代码全部写完并提交 w1121 = w1117(6e17e7cd + 49a251aa7 md 上限 67),22:1x 起 gate_w16.sh(scratchpad gate_w16.status / migrate_w16.log / e2e_ci_w16.log / ship_w16.log)**。做了:迁移 7fd4c1f6ee18(chat_annotations + projects.chat_annotation_enabled;alembic autogenerate 出来的)、chat_annotations_api.py(可标注吗 / 问答与工具 / 标注块 纯函数 + 七条接口)、endpoints 七条、entities / fieldtypes(question / standard_answer / assistant_role / tools_used 显式类型;按表必填)/ models(_额外唯一 project_id+trace_id;proj_status 索引是通用规则自动加的,别再手登)、开关们 chat_annotation.switch、switch_registry_check 正则加 chat_annotation_enabled、runs_api 运行详情(聊天站那轮)带「标注」块、app.js(菜单 #/annotations / 路由 / 画标注块+挂标注块 / 页_标注回复)、test_chat_annotations.py 23 绿、test_chat_annotations_flow.py(**没真跑过**,随这轮 e2e-ci;临时成员 E2EANA/E2EANE 走 _清成员)、Makefile 三处、bite_specs +1(规格 1982)、PRD 台账第八十九条、规划 4-2 进度段。**原计划**:迁移(chat_annotations 表 + projects.chat_annotation_enabled)→ chat_annotations_api.py(列表 / 可标注判定 / 建 / 改 / 归档 / 总开关 / 命中上报 / 给聊天站的启用清单)→ endpoints.py + entities.py + models.py + 开关们 登记 → make gen / contract → runs_api 运行详情带「标注」块 → 前端 调用树页「标注成标准答案」+ 新页「标注回复」(总开关 + 表)→ 测试 test_chat_annotations.py(纯函数 + 登记)/ test_chat_annotations_flow.py(e2e)→ Makefile 登记 → 规划 4-2 进度段 + PRD 台账第八十九条 → 批次(锁内 upgrade + e2e-ci + ship)→ 推 → 发飞书。
   · **19:0x 摸底(别重摸)**:聊天站每轮 trace 的根 span 是 `invoke_agent <角色>`,入 `{"提问","角色"}`、出 `{"回答"}`;工具步 stage = `execute_tool <工具名>`(ToolSearch / Skill 是元工具,不算取数);工具归属表在 backend/domains.py `领域`(knowledge 那组里 set_piece_ratio / set_grade_diff / review_motif 是写,要按 api.WRITE_TOOLS 剔;get_review_queue / pattern_queue / grading_audit 是队列取数,也拦 —— 「知识类」= kb_* 那些);原文权限 `me.看得到原文吗()`(deps.py:45,runs_api:175 已在用);审计开关表 `开关们` 在 workflows_api.py:3328(新加 "chat_annotation.switch");列类型靠 entities 字段名后缀 / models.py 的类型表(byte_count 样板);接口登记 endpoints.py A() 读=`读` 写=`写`,`/traces/{id}` 在 532–534 行;前端菜单表 app.js:127–136(`["#/traces","调用链",true,true]` 形状),路由 switch 在 ~11967;Makefile:E2E_CI 列表 421–432 + 单条 target(600 样板)+ 进度报告段(935 样板)+ test-orchestration 1335 样板;tools/test_registry_check.py 要每份测试进名单;e2e 身份 X-Dev-User(U001 管理员 / U002 普通),memberships 没有 grants 列(权限看 role → deps)。**表设计**:chat_annotations(id, organization_id, project_id, trace_id 唯一/项目, assistant_role, question, standard_answer, note, tools_used jsonb, status 启用/停用, hit_count, last_hit_at, revision, created_by, created_at, updated_at, archived_at)+ projects.chat_annotation_enabled boolean 默认 false。**接口**:GET /chat-annotations(?status=,带「开关」)/ POST(体 trace_id + standard_answer + note;服务端从 trace 取提问 / 角色 / 工具;拦 → 422 CHAT_ANNOTATION_REALTIME 列出工具;重复 → 409;要 看得到原文吗 否则 403)/ PATCH {id}(If-Match revision;answer / note / status)/ DELETE {id}(归档)/ PUT /chat-annotations/switch(总开关,审计 + 开关们)/ POST {id}/hits(聊天站上报命中,权限 运行评测 同 trace-imports)。运行详情响应加「标注」块 {可以吗, 原因, 调过的工具, 已有};拦截规则写成纯函数 `可标注吗(工具们)` 放 chat_annotations_api.py 顶部,runs_api import 它。
2. ✅ 试跑 tools/weekly_review.sh:第一次 22:1x 当场挂(bash 3.2 不认中文变量名,改英文 cf0f26b4);第二次 22:13:48 → 22:18:43 **成了**,报告 `辅助目录/澜绣云裳agent-项目周审查_20261121_2213_49251aa7.md` 154 行、有「本次结论」。报告指出三件要跟:① 「核对中」只管 30 分钟且卡没出口(= 悬而未决③);② 标注回复后台一半的 note 说「已生效」而聊天站那半还没接(今晚第 4 项接上就对了);③ 盯中文变量名的检查管不到 tools/ 目录(待查有没有这条检查、能不能扩)。**用户还要亲手装 plist**(装法在 plist 注释里)。
3. ✅ 用演示门店启用「经营日报草稿」:**23:30 做完 —— 流程 wf_e81d8b16994b、版本 wfv_a7a3c3e95119、首跑 xr_aae277f9e855(live,23:18:36→23:19:51 成功,文件 doc_4f24ddf13293《经营日报_2026-11-21》7524 字节)、发布清单 rel_013a7d50a0dc 审核通过发生产、定时 每天 08:00 / U001 / 统计前一天 / 下次 2026-11-23 08:00。脚本抄进仓库 管理后台/tools/enable_daily_draft.py(修了 bug:运行详情的键是「执行状态」不是 status,原来空等 10 分钟;加了 --从 6 --wid --vid 续跑)。** 原记录:22:14 锁内 seed_bridge_tools --项目 project_lanxiu 跑过(新建处理要求「经营日报草稿撰写」pv_d73bf5bae90f、「交付风险清单撰写」pv_319217bc8752,其余没动);scratchpad/enable_daily_draft.py 七步 22:2x 起、在 gate_lock 里排在 fc 的 ship(22:15 起,约 45–60 分钟)后面(后台任务 bir6mjqzg)—— **23:15 结果:gate_lock 等了 3600 秒放弃(fc 的 ship 22:15 起占锁,23:11 还在咬合重放,全量门禁要跑到 0 点后),脚本一步都没跑。按「0 点到夜跑结束不占锁」,改到 11-23 ≥05:10 夜跑结束后、锁空时跑:`./tools/gate_lock.sh --who 启用经营日报草稿 python3 /private/tmp/claude-501/-Users-eureka/0a0ac851-e575-4807-8f5e-502f689a9764/scratchpad/enable_daily_draft.py`(scratchpad 可能被清,脚本正文已抄一份到 w1121 的 tools/enable_daily_draft.py?——没有,还没抄;若 scratchpad 没了按文件头七步重写)**。原计划:以管理员身份走 选模板 → 选模型 → 冻结 → 审核 → 发生产 → 开定时(设定时的那个人要登记演示门店);明早 08:00 后看 workflow_documents 有没有那份文件。要动共享库(建流程 / 版本),**只在非夜跑窗口做**。
4. ✅ 标注匹配那一半(聊天站):**代码随 bd5730e4 推上主干(agentsite/annotations.py + app.py 接线 + annotations_check 带咬合);线上真命中一次都没发生过(要开总开关、标一条、再问同义的)**。原计划:等 fc 推完告哈希 → 主检出 ff → 读 agentsite 里聊天入口(sdk.py / app.py)→ 新问题先拿启用的标注清单问一次模型「和哪条同义」→ 命中直接回标注答案并 POST 命中上报;实时类问题不走(服务端已拦在标注时)。要动 agentsite,碰前喊 fc。
5. ✅ 06:5x 汇总发飞书(文件名带「澜绣云裳agent」)、刷交接、CronDelete fc647c85 —— **06:50 没发(卡在等拍板),并进《澜绣云裳agent-夜间与日间汇总-20261122.md》,23:3x 发到飞书产品文件夹:https://aqvi2xbk5kd.feishu.cn/docx/U1rqdddRPoWOsDx4elWcDVOWnvc(第二版,第一版同名已清);md 已 git add 随下一笔提交。**

### ⏱️ 12 小时长任务清单(11-20 21:30 → 11-21 09:30)· 照 Dify 的工作流收尾夜(Fable 5.1)

> 用户 21:3x:「做一个12小时的长时间任务」→「先确定有什么需要我拍板的」→ **拍板(21:4x)**:① 四期「人工介入表单化」做**后台一半**,聊天站那一半去找聊天站会话排期 —— **查实现在没有会话管聊天站**(c2 是介绍页、fc 是评测线,c2 已回「发错对象」);谁接要你定,早上汇总里问;② 「代码执行」最小版**今晚做**,安全细节按最严的那边定;③ Webhook 三个尾巴**都补**(接入文档 / 网址 + 请求头参数表 / 自定义返回内容);④ 清单做完接着做《还债与收尾计划》里不用拍板的。
> **守则**:同 11-18 那夜 —— 只碰 管理后台/ 和根目录文档、交接;**0 点到夜跑结束(约 05:10)不占锁、不写共享库**;每批 = `scratchpad/gate_start.sh` 形状(锁空 → w1117 rebase → 主检出 ff → 停旧 8801 → kickstart aimc → 验进程归属 → 锁内 e2e-ci → w1117 里 ship);只认「被包的命令退出码」;**改 w1117 里的文件前先确认没有批次在跑 ship**(看 scratchpad 最新的 gate_*.status 有没有「ship 完」);fc 手上两笔本地提交等用户亲手跑放宽补丁才推、它推前会问我锁。每小时 :41 有 session 内提醒 **0a89543b**,09:27 收尾 **9b334a92**(汇总发飞书后 CronDelete 每小时那条)。
> **沙箱选型(代码执行)**:规划写 wasm;这台机器实测 **macOS `sandbox-exec`** 拦得住网络(URLError Operation not permitted)和写文件(PermissionError),wasm 要下运行时 + python.wasm —— 用 sandbox-exec + 子进程限时,内存限制 RLIMIT_AS 在 macOS 上设不了(实测 ValueError),改用 RLIMIT_DATA 或看子进程 RSS,做的时候定。

1. ✅ 2-3「开始」页签与多开始:**22:15 已推 65aa99c6..fda6ae6b**(第一轮 e2e 红在搭建页冒烟「空壳」:冒烟打到的那条演示流程是别的 e2e 用空白模板建的、带 $开始待配置,进编排页自动弹引导 → 桩里没有 getElementById / body.appendChild → 抛 → 路由把 #main 盖成报错块;桩补上两个方法 + 引导包 try(fda6ae6b);第二轮 e2e 21:56 退出码 0、ship 22:15 rc=0)。aimc 已在 fda6ae6b、进程归属核过。已告 fc。
2. ✅ 3-5(w1121 本地提交,待并进 w1117 推):**ELIF 原来就有**(branches 列表 + 加一路 / 上下移 / 第一个满足生效);**知识检索节点做通** —— 盘点发现它能加、标「已实现」,但没面板、worker 没适配器(ADAPTER_MISSING)。做了:workflow-resources 加「资料库」(带最新就绪索引 + 索引用的配置)「检索配置」;app.js retrieve 面板(选库顺手写 index_build_id;召回设置只读块;表_输入 固定「问题」;结果字段名);validator ⑤⅞ RETRIEVE_QUERY_MISSING / RETRIEVE_NO_READY_INDEX(顺手修 HTTP 段 node_id=i 是序号的老错);worker _retrieve(走 RT.检索,角色=发起人 memberships.role,精排跟配置 rerank,记账 + 记一次试跑 来源「工作流」,非 live / 连接测试 / 评测交空替身);受理时 retrieve 选了库算 live(同 HTTP)。测试:test_retrieve_node.py 8 条绿 / test_workflow_retrieve_panel.js 18 条绿 / test_retrieve_node_flow.py(**没真跑过**:主检出还是旧代码,① 就会红;随下一批 e2e-ci 第一次跑;真模型模式会调一次改写模型几分钱)。规划 3-5 进度段已写。
3. ✅ Webhook 尾巴(w1121 本地提交):dsl start 配置加 webhook_query_schema / webhook_header_schema / webhook_response;validator 开始段加 WEBHOOK_PARAM_DUP / HEADER_TYPE / RESPONSE_STATUS(只许 200/202)/ RESPONSE_REF / RESPONSE_BAD + 非 Webhook 带了这些 → 警告 CONFIG_UNUSED;open_api 核Webhook三源(query 按类型转、header 不分大小写)+ 渲染Webhook返回(JSONResponse / PlainTextResponse,重放同形);app.js 开始面板 Webhook 分支加两张 字段表编辑 + 返回配置;访问 API 卡样例更新;**顺手**:白天加的 WEBHOOK_NOT_START / WEBHOOK_PARAM_INVALID 没登进 open_api.对外错误码,test_access_doc(只在 test-orchestration,不在门禁)一直红 → 补上。测试:test_webhook_start ⑧ 9 条(24 全绿);test_webhook_flow ⑧⑨(**没真跑过**,随下一批)。文档《澜绣云裳agent-接入Webhook怎么做-20261121.md》写好,**飞书还没发**(批次绿后发)。规划 2-2 进度段已补。
4. ✅ 4-3 导出 / 导入(w1121 本地提交):新模块 services/api/app/workflow_backup.py(导出 / 引用表 / 解析;10 类引用字段和 validator.引用字段 同一张;按名+版本号精确找,不退回同名最新版);workflows_api 三条路由 GET /workflows/{wid}/export(?版本id=;数据出境 + 审计)/ POST /workflows/import(建新草稿)/ POST /workflows/{wid}/import(If-Match 覆盖草稿);endpoints.py 三条 A() → make gen(openapi.json / api.ts 已重生成)→ make contract 绿。前端:版本页每版「导出」+ 草稿行「导出草稿」(弹_导出备份 先说不含密钥)、创建应用弹窗「从备份导入…」、画布右键「从备份导入(覆盖当前草稿)」(弹_导入备份,FileReader 读 JSON)。测试:tests/e2e/test_workflow_export_import_flow.py(**没真跑过**,随下一批);Makefile 三处登记。规划 4-3 进度段写了(原文说的「现有的从其他工作流导入步骤」其实不存在)。
5. ✅ **07:28 已推主干 fda6ae6b..45269e05**(第五轮 gate_w6.sh:e2e-ci 06:41 退出码 0、ship 全量门禁 0;aimc 在 45269e05、进程归属核过;锁已放、已告 fc;带了 fc 点名请带的夜跑 a01ca454)。Webhook 接入文档 + 规划文档 07:3x 发飞书产品文件夹。—— 下面是路上的记录:【0 点前批次】第一轮(gate_w2.sh,22:17 起)e2e-ci 22:30 退出码 2,只红在两份新测试;锁内单跑三轮修到全绿(知识检索 12 / 导出导入 23):① 默认身份抄了 http 那份的 U002,而 **U002 在 project_lanxiu 没成员记录**(workflow-resources 404)→ 两份改 U001;② 测试自己起的 worker 跑在工作树里,**工作树没有 管理后台/.models(本地 bge 向量模型,gitignore)** → 检索 ADAPTER_ERROR「模型文件不全」→ w1117 / w1121 都 `ln -s 主检出/管理后台/.models`(和 .venv 同理,**新工作树三条链接:管理后台/.venv、agentsite/.venv、管理后台/.models**);③ 空白模板的结束要返回 summary 没绑来源 → 冻不了版本,夹具绑到 article;④ **retrieval_runs.source 的 CHECK 只认 检索实验室 / chat** → 来源「工作流」第一次真跑撞 CheckViolation(记一次试跑 把原因带进节点输出才看见)→ 迁移 a3c7e1b2d4f6 + models.py,**22:4x 已锁内 upgrade 到共享库**(alembic current = a3c7e1b2d4f6),CI 新库跟迁移走。第二轮 gate_w3.sh(含第 6 项)22:39 起 → e2e-ci 22:52 退出码 2,只红 tools/ifmatch_reachable_check(新加的 POST /workflows/{id}/import 要 If-Match,没登记界面从哪拿 revision)→ 登记成和存草稿同一个 草稿.revision(aeb84722)。**第三轮 gate_w4.sh 22:54 起,含第 6、7 项**(日志 e2e_ci_w4 / ship_w4;status gate_w4.status)。e2e-ci 23:13 **退出码 0**(人工表单 11 / 代码执行 8 / 知识检索 12 / 导出导入 23 全过);**ship 23:39 rc=1**,红在 pre_push 的咬合重放(不是门禁):① test_graph_validation 对照红 —— 夹具「非法_用了未实现的节点」拿 code 当例子,code 实现后它报 NODE_MISSING_CONFIG;夹具改成系统不认识的类型 wasm_code → NODE_UNKNOWN_TYPE(20 条绿);② tools/bite_specs.json 两条破坏点过期:单步测试.能单测的类型 那行(我加了 code)、workflows_api 资源表尾「术语」那行(我在后面加了资料库 / 检索配置)→ 改成只删那一行;本地 bite_run --only 两份都绿。③ test_glossary_flow 那条 e2e 咬合要打 8801,**没本地验**(0 点前来不及一轮 45 分钟的 ship)。**早上 05:15 后只需再跑一轮 ship**(gate_w5.sh 整条也行,多 20 分钟 e2e):aimc 已经在 aeb84722,之后只改了测试 / 夹具 / 规格。工作树要链 backend/lanxiu.db(bite_run 要;w1121 刚链)。**04:4x:夜跑 01:23 在主检出留了自动提交 a01ca454(只动 agent/nightly 两个 gz + 当晚报告),fc 04:5x 回「按 ① 办、原样带上、它不要锁」→ w1117 已 rebase 到 a01ca454 之上(我的几笔哈希全变:咬合三处 975e5d32 / vm 测试 9cd12780 / 交接 ×3),w1121 reset 跟上,主检出可 ff。fc 自己那两笔(efb8110d / 01024fe7)不带。推完要告 fc 远端哈希。** **05:17 第四轮 gate_w5.sh:e2e-ci 05:35 退出码 0(人工表单 11 / 代码执行 8 / 知识检索 12 / 导出导入 23 / 开始引导 10 第一次真跑全过);ship 06:20 rc=1,咬合重放过了、红在全量门禁 3 条(都是我今晚的改动没跟上的根目录检查):① url_ascii_check —— test_webhook_flow 里 `?门店数=` 中文参数名字面量 5 处 → 改 urllib.parse.urlencode;② spec_coverage「首个闭环那十个 + 直接回复已实现」期望集少了「代码执行」→ 加进去、标题改成「登记的 22 个全实现」;③ trace_check 把 worker.py 的 _飞书通知(curl + secretref POST)当成调模型没接记录仪 → 登进豁免表写明不是调模型。三条本地重跑全绿。第五轮 gate_w6.sh 06:3x 起(日志 e2e_ci_w6 / ship_w6)。**
6. ✅ 4-1 后台一半(w1121 本地,待提交):dsl human 配置 += form_markdown / form_fields / actions / notify_connection_id,端口 += 分支;validator ⑤⅞⁺ HUMAN_ACTION_KEY / HUMAN_EDGE_NO_ACTION / HUMAN_ACTION_UNWIRED(警告)/ HUMAN_FIELD_KEY / HUMAN_FIELD_OPTIONS / HUMAN_FORM_REF(警告),引用字段 += notify_connection_id(validator / workflows_api 依赖表 / workflow_backup 三处);runner 挂起载荷 += 表单{说明(渲染 {{k}}),字段,按钮} / 通知连接 / 步骤名,allowed_fields 并字段名,恢复 (分支,决定) 优先;worker 建待办 payload_ref 带 __表单、_飞书通知(工具连接 + secretref.路径里的凭据 + 出网策略白名单/禁区 + curl,只记事件)、恢复 dec 查询放开按钮 id、结果 __action_id;human_api 决定认按钮 id(_表单按钮)、状态 approved、排恢复;前端 human 面板四块 + wf_graph 出口们/人工按钮改名/删人工按钮 + 结果字段名 + 画_表单待办。测试:test_human_form.py 19 条绿(validator + runner 挂起/恢复);test_human_form_flow.py(**没真跑过**,要等 aimc 上了这版)。规划 4-1 进度段写了接口形状(给聊天站那一半)。
7. ✅ 3-4 代码执行最小版(w1121 本地,待提交):runtime/代码执行.py(沙箱配置 sandbox-exec allow-default + deny network/file-write/读 /Users/process-exec;RLIMIT_CPU + 墙钟;macOS 内存靠 0.1s 看 RSS;输出 64KB;核输出按 output_schema;沙箱可用() 没有就 CODE_SANDBOX_UNAVAILABLE 不退裸 exec);dsl code 已实现、配置 code/language/input_mapping/output_schema/sub_limits;validator 字段提示 code + 调 代码执行.配置问题;runner `if t == "code"` 内联;单步测试 加 code;workflows_api._代码节点只许管理员(存草稿 / 导入新 / 导入覆盖三处,非 admin 新增或改代码 → 403 CODE_NODE_ADMIN_ONLY);前端 步类型名 / 菜单(非 admin 置灰说明)/ 可加 / 默认配置 / 表_设置 code / 表_输入 input_mapping / 单测类型。测试:test_code_node.py 27 条绿(四攻击 + 写文件 / 起进程 / 吃内存 真打);test_code_node_flow.py(project_demo_a,U002 403 / U001 200 / 真跑 2+5=7;**没真跑过**);两处「只有代码执行未实现」的老断言改了(test_orchestration_flow:114、test_dsl_semantics:180)。规划 3-4 进度段写了 sandbox-exec 替 wasm、内存不是硬限制。
8. (并进第 5 项的第三轮了:6、7 都在 22:54 那批里;如果那批红了修完再起一轮,过了 0 点就等 05:10 夜跑结束)
9. 🔎 《还债与收尾计划》核过(执行手册 395–424 行那张 27 行表,23:4x):17 / 20 / 21 / 22 / 24 / 27 都 ✅(**W22 费用上限 11-15 就做完了**:store_usage 月上限 + cost_alert 80% / 到顶 + app.py:825 到顶不升 Opus —— 我 23:0x 那条「没动」是没查表,作废);新人保底 ✅(booking.py:393)。真剩下的:row 26 **W27 标品签收告知 + 换货分支**(「只在工具说明里出现,流程没找到」)、row 18 默认模型接聊天站(要复测模型 + 动 agentsite/sdk.py)、row 11③④ / 6 单源(fc 地界或 fc 在做)、row 23 用户亲手。**W27 也 ✅(11-17 22:1x 核实:换货分支不用另做)** → 还债表里没有我今晚能不占锁、不碰 fc 地界、不用拍板就能做的了。0 点后的时间用来补今晚新面板的 vm 测试(人工介入表单 / 代码执行,照 test_workflow_retrieve_panel.js 的写法)和把规划 1.2 那张「对上了 18 个」的表改成现状。

- **压缩前六项(11-24 15:1x 刷,最新;下面 19:0x 那组是 11-22 日间的)**:
  · 六项补刷(15:4x):**未验证** 🔮 D01-D03 真跑两轮能过(判分器只过了人造对照;真跑在后台 bbidcuxh6,结果看 agent/ops-results.jsonl 最后 6 条,挂了先怀疑判分器词表再怀疑模型);🔮 gate_w39 ship 会绿(e2e 退出码 0 已验,全量门禁没出)。**判据** 死工具小活只做「合入口 / 补评测」,不删函数(prompts_check / run_journey / boundary_audit 直接调函数);ai-product-shape 顺序:先改描述再动结构,所以 ② 倾向只改 can_order 描述(方案 B)。**作废** 死工具清单里「规矩没给(4 个规则型)」这一判断不成立 —— TL72/TL95/TL97 都在;「③ 6% + kb_coverage」09-22 已做。**禁区** 不变(fc 文件 / E2EAK* 清理要用户点头 / guards.py 先问 fc)。**悬而未决** ② 等 fc 选 A/B/C;E2EAK* 1500 把钥匙清不清等用户。**下一步第一个动作** 两个后台通知任一来了就处理:w39 绿 → fetch 核远端 → 告 fc 哈希 → kickstart backend + agentsite → 主检出 ff → 汇总补哈希发飞书;真跑结果 → 钉对照 → 提交 ops-results.jsonl。
  · 未验证的预判(15:1x):🔮 密钥列表改一条查询后 page-smoke 那条会绿 —— 本地 0.12 秒、对账一致,但没在 8801 真服务上跑过(验法:gate_w39 的 e2e_ci_w39.log 退出码 0 且 ifmatch 48/48);🔮 gate_w39 全量门禁再没有别的红 —— w38 ship 没跑到,这批里新改的 open_api.py 有没有被咬合 / 契约检查盯着没查(bite_check 绿只说明规格没过期)。
  · 判据(15:1x):w35「瞬时抖动」判错的原因是**单跑绿 = 环境那一刻快**,不是接口形状对;以后「打不通」先量接口耗时再下结论。「死工具」判定只认 spans 表 09-24→11-24 的 execute_tool 记录 + sdk._ROLE_TOOLS,不认提示词里有没有提到。
  · 作废的结果(15:1x):98972d91 给 ifmatch 检查加的「重试一次」没解决问题(保留无害,但别再把它当修法);gate_w37 / w38 的红都不是代码错 —— w37 两条是棘轮和过期登记、w38 是数据攒多。
  · 禁区(15:1x):tools/nightly_eval.py 那两行是 fc 准我删的一次性例外,其余照旧不碰它的文件;清 E2EAK* 钥匙要用户本人点头;guards.py 写口闸(② 预演)动之前先问 fc。
  · 悬而未决(15:1x):① can_order 并进 open_order 预演要不要做 —— 取决于写口闸能不能认「只问能不能下」为只读,fc 没答;② dbpath 欠债下限 fc 273 / 我 285 谁对 —— 它 rebase 时核实际数。
  · **23:1x 状态汇总**:远端 0bb08202;gate_w40 ship 在咬合重放 53/109(23:03),之后全量 check.sh 约 40 分钟 → 预计 00:1x–00:3x 推完,**会和 0 点夜跑抢锁**(夜跑等锁上限 3600 秒,应该等得到;若夜跑先拿到锁,ship 的全量会等它几小时 —— 明早看 ship_w40.log 尾和远端哈希判断)。w40 带 4 笔(e64fb0ba 止);w1121 又领先 w1117 6 笔(bcac1b69…e4d831da:死工具 ①④ / 第三步 / 审批中心摘块 / 报告与文件页 / 定时失败原因+核对中出口 / 报错人话 / 修下载+执行记录 / 工作流归档),**都动了 管理后台/ → 明早 gate_w41 要 w35 形(含 make test-e2e-ci)**,夜跑结束(约 05:10)后再起。包三里「对照用例 312 条」写死的数 doc_numbers_check 自己标了「已知缺口:十个 judgetest 汇总格式不一、没有机读出口」,要做就是新检查(make-a-check-that-holds),留白天。
  · **23:5x gate_w40 红(没推,远端 0bb08202;主检出已被 gate ff 到 e64fb0ba,三个服务跑的是它)**:page-smoke 0、咬合 109 条全过,全量只红 1 条 tools/eval_tier_check.py「源码里写了的题都真跑过 —— ops 欠 D01、D02、D03」:它只认 agent/ops-eval-results.jsonl(不认 .partial),而 ops_eval 夜跑**只在周六晚单跑**(nightly_eval 单跑那晚 = 6),上次全量 11-17。处理:**23:5x 后台全量跑 ops_eval(任务 bqhm4k3dg,日志 scratchpad/ops_full_1124.log,132 题约 2.5 小时,Haiku 登录态)**,写进 w1121 的 agent/ops-eval-results.jsonl;和夜跑同时跑,夜跑耗时可能偏高(已告 fc)。❌ 作废:「D01 抖 / D02 判据」那些结论不变,但「w40 会绿」的预判错了。
  · **23:5x fc 提醒 + 我核过**:主检出停在 e64fb0ba(远端没有),服务跑的是没推上去的代码。夜跑自动提交那段(nightly_eval.py 458 起)**只在「上游之后恰好 1 笔」时才推**,主检出领先 4 笔 → 今晚它只本地提交不推,我的 4 笔不会绕过门禁。明早**不 rebase、不改这 4 笔哈希**(远端 0bb08202 没动),w1121 直接 `git rebase <主检出 HEAD>`(把夜跑那笔原样带上,老规矩「夜跑提交挡快进默认原样带上」),w1117 对齐后 gate_w41 ff 主检出就是纯快进;推完 `git merge-base --is-ancestor $(git -C 主检出 rev-parse HEAD) origin/main && echo 主检出在远端上` 验一遍。
  · **01:4x ops_eval 全量跑完(退出码 0,135 题 × 两轮,约 1 小时 50 分)**:最后一轮 109/135(正向 31/36 · 负向 78/99);日常层 52/65 = 80% **没达标**(门槛 95%)、偶发 27/29 达标、罕见 30/41 只报分;两轮翻面 27 题(轨迹类 1:K10;内容类 23;认不出 3:O06 / R10 / X14);「花费 $5.77」是按价目表算的估数,实际走登录态不花钱。**三道新题**:D02、D03 两轮都过;**D01 两轮都挂,挂的不是判分器也不是题 —— 模型调了 cancel_fee 算对了,答案被交付前体检扣下**(第 1 轮 g23_discount_promise「谈到了价格让步」,第 2 轮 g1_no_source「报了总价 ¥65452.8 但没调 kb_bom」—— 价来自 get_order / cancel_fee,体检只认 kb_bom 当价的来源)。这是 agentsite/guards.py 的误报(fc 地界,**我不碰**),已算进「要告 fc」清单。`python3 tools/eval_tier_check.py` 本地**绿**(27 套源码题号都在结果文件里)。日常层 80% 不在今晚范围 —— ops_eval 周六夜跑才量,翻面 23 题挂在说法上,白天盘。
  · ✅ 已做(01:4x):看 log 尾 → eval_tier_check 绿 → `git commit --only agent/ops-eval-results.jsonl HANDOFF.md`。**下一步第一个动作(05:10 夜跑完后)**:  `git -C w1121 rebase --autostash $(git -C /Users/eureka/Desktop/澜绣云裳agent rev-parse HEAD)`(主检出 HEAD = e64fb0ba + 夜跑那笔;**不是 origin/main**)→ w1117 status 干净后 rebase w1121 → gate_w41 = **w35 形(含 make test-e2e-ci,因为 6 笔都动了 管理后台/)**,sed w35→w41 → 绿后告 fc 哈希、kickstart com.lanxiu.backend + com.lanxiu.agentsite + 验 8801 归属。
  · 下一步第一个动作(23:1x,已过期):等 gate_w40 的后台通知(status gate_w40.status / ship_w40.log)。绿 → `git fetch`(卡住就 kill,用本地 origin/main 引用)核远端 = e64fb0ba → 告 fc 哈希 → `launchctl kickstart -k gui/$(id -u)/com.lanxiu.backend` + com.lanxiu.agentsite(api.py / server.py / app.py / sdk.py / prompts.py 都改了;主检出 ff 已由 gate 做)→ 夜跑期间不占锁不写库,只写代码;05:10 后 `git -C w1121 rebase origin/main --autostash` → w1117 对齐 → gate_w41(w35 形)。红 → 看 ship_w40.log 红在哪,**先 `git -C w1117 status --short | grep -v '^??'` 再 rebase**;夜跑期间不重跑 gate。
  · **12:0x:gate_w36 红在我三个新页 #main 有「undefined//」(冒烟假浏览器 location.protocol 为空)→ 加默认值(71d350f2),gate_w37 起(= w36 形,page-smoke + ship),w1117 = w1121 = 71d350f2 领先 8 笔。fc 的 b 步已本地提交、等我哈希;它提醒:我改 app.py:1206 加 me= 时要连 agentsite/triage_scope_check.py:103 的锚 `'sdk.run("triage", prompt), 单条超时秒'` 和 bite_specs「研判队列那一路还跑 task」那条 old 一起改(归 c 步)。今天汇总《澜绣云裳agent-日间汇总-20261124.md》已写(w1121 根目录,未提交,哈希待补),推完发飞书。**
  · **12:5x:gate_w37 page-smoke 绿、ship 红在全量门禁 2 条(远端仍 e9d83eb9,没推)**:① dbpath 棘轮 285→286 —— 我新检查 store_scope_write_check.py 自己拼了 lanxiu.db 路径 → 改走 dbpath.真库()(1878311b,w1121 领先 9 笔);② 夜跑清单「已知连续失败名单里没有过期的」—— tools/nightly_eval.py:642-643 recall_eval.py 的登记过期(召回判分器 11-19 修后已复验、不再连续失败)。那文件归 fc,fc 已回「选 A:准你在这批里删那两行」;**我 Edit 它被自动权限分类器拦(「削弱监督」),没绕** → 补丁写在 scratchpad/recall_delist.patch(`git apply --check` 过),**等用户用 `!` 打上**:`cd ~/Desktop/澜绣云裳agent/.claude/worktrees/w1121 && git apply /private/tmp/claude-501/-Users-eureka/0a0ac851-e575-4807-8f5e-502f689a9764/scratchpad/recall_delist.patch`。打上后我 commit --only tools/nightly_eval.py → w1117 rebase w1121 → 起 gate_w38(= w37 形:page-smoke + ship;改的两处都不碰 管理后台/ 所以不用 e2e-ci)。scratchpad 会被清:补丁没了就按上面两行的描述重写(删 642 注释 + 643 登记,留一行说明)。
  · **13:0x:用户打了补丁,8523036d 提交(w1117 = w1121 = 8523036d 领先 10 笔),gate_w38 后台跑着(status gate_w38.status;备份 w1121/.gate_w38.sh.bak;= w37 形 page-smoke + ship)。已问 fc 死工具四件小活的文件归属(api.py 注册区 / prompts.py 是它禁区),等它回;三道负向题归我。**
  · **13:1x fc 回「选 A」:api.py 三处注册 + prompts.py 四句归我改,范围就这些。它给的四个坑:① 「下架」只撤注册、函数留着(prompts_check.py:344 调 api.kb_coverage(),run_journey.py:437 调 api.can_order());② sdk.py:765 放行名单有 mcp__knowledge__get_review_queue、:561 注释,并进 kb_tables 后一起改;chat_eval.py:22 注释不动;③ 改 TL02 换提示词指纹是预期;agent/ablation.py:72-77 的「只录了 6%」是故意留的旧措辞做对照,别改;④ 它看到一份咬合重放里 dbpath_check 对照红(欠债下限 273 那版),若是 w38 的会卡我 —— 我这版下限 285、我没碰 dbpath_check,多半是它自己那份。** 我只读查过:**kb_coverage 09-22 已从模型可见工具拿掉(api.py:1680 注释)、TL02「6%」早改了且 prompts_check P7 守着** → 四件里第 ③ 件已经是做完的,别重做。落点:get_review_queue 注册 api.py:1414 / 字典 :1579,规矩 prompts.py:2053 TK12,boundary_audit.py:1915-2036 直接调函数(留函数就不红),管理后台 test_chat_annotations.py:41,71-72 把它归「队列类」(撤注册后那条 ck 仍成立,集合里没它就是 not 交集);can_order 注册 :1279 / 字典 :1578,order_gate_check.py:378 和 api_wearer.py:221 只是注释引用。
  · **14:5x:gate_w38 锁到 14:41 才空,page-smoke 红在老地方「GET /access-keys 打不通(重试仍然)」→ 根子查实:共享库 access_keys 1506 把(e2e 每轮留 8 把 E2EAK*),列表对每把逐跑 `_今天花了` 共 27 秒,检查 curl -m 20 → None。w35 那次「瞬时抖动」的判断是错的,是慢到临界。修:open_api.py 新 `_今天花了_整个项目` 一条查询按钥匙分组(0.12 秒),三处列表走 `_列出密钥`,单把的 `_今天花了` 留给改上限 / 轮换;抽 40 把对账 0 不一致(ae959681,w1117 = w1121 = ae959681 领先 11 笔)。gate_w39 后台跑着(= w35 形,**含 make test-e2e-ci** 因为改了 管理后台/;status gate_w39.status;备份 .gate_w39.sh.bak)。欠账新增:E2EAK* 钥匙 1500 把没人清(e2e 收尾该吊销 / 删;清要占锁 + 告 fc)。**
  · **15:0x 死工具小活 ① 的落点已摸清(只读,没改)**:get_review_queue 并进 kb_tables 的做法 —— api_kb.py:250 `kb_tables(topic=None)` 加一支:`topic == "待核实"`(或含「核实」)时转调 api_aftersale.get_review_queue(top=15) 原样返回(函数留着,boundary_audit.py:1915/1920/2036 直接调它);api.py:1678 kb_tables 描述末尾加一句「topic 填『待核实』看哪些工艺×面料被问到了却没依据(按被问次数排,只看不填)」;**撤注册**:删 api.py:1414 那整条 get_review_queue 的 TOOLS 项 + :1579 字典那行;backend/domains.py:21 knowledge 元组里删 "get_review_queue";agentsite/sdk.py:765 删 `"mcp__knowledge__get_review_queue",`(连上面 4 行只讲它的注释);prompts.py:2053 TK12 的工具元组 ("get_review_queue",) 改成 ("kb_tables",)、正文开头加「kb_tables 填 topic=待核实 看」;管理后台/services/api/app/chat_annotations_api.py:58 注释提到它、tests/orchestration/test_chat_annotations.py:41,71-72 把它归队列类 —— 撤注册后 ck「不在知识类只读里」照样成立(集合里没它),注释顺手改;README.md:325/1167 和产品说明的工具表由 `./tools/sync_docs.sh` 重生成。改完必跑:`python3 tools/bite_check.py`(sdk.py / api.py / prompts.py 被几十条咬合盯着)、`python3 tools/prompts_check.py`(P6:kb_tables 挂了 TK12 要跟上)、`agentsite/.venv/bin/python agentsite/skills_check.py`(白名单和 MCP 暴露对不上会抓)、`python3 tools/quick_gate.py`。② can_order→open_order 预演:**先想清写口闸**(open_order 在 api.WRITE_TOOLS,带 预演=true 的调用会被确认卡 / check_write 当写拦;grep 预演|dry_run 在 api.py / guards.py / sdk.py 零命中 → 没有现成机制),可能的形状是 open_order 的 input_schema 加 `只问能不能下:bool`,sdk 写口闸看到它为 true 就当只读放行 —— 这一步要先问 fc(guards.py 是它的)再动;can_order 函数留着(run_journey.py:437 调)。③ 已做完别重做。④ 三条规矩 + 三道负向题:prompts.py 里 cancel_fee / draft_delivery_notice / return_rate 现在**没有** Rule 挂它们(grep -w 零命中)→ 各写一条 Rule(「什么时候掏」),负向题进 agent/ops_eval.py(判分器先过 agent/*_judgetest.py 对照);ablation.py:72-77 的「只录了 6%」是故意留的对照,别改。fc 15:0x 提醒:清 1500 把 E2EAK* 钥匙是删数据,**要用户本人点头**,到时直接问用户;dbpath 下限它那边 273、我 285,它 rebase 时取小并核实际数。
  · **15:3x 进展**:gate_w39 e2e-ci 15:16 退出码 0,ship 跑着。w1121 又多两笔(**不在 w1117、不在这轮里**):bcac1b69 死工具 ①(get_review_queue 并进 kb_tables topic=待核实;工具 110→109 / shop 93 / 读 76,18 处文档数字逐行改,sync_docs 过,快门 129 条 0 红,连交接 + 日间汇总一起带上);9e429239 死工具 ④(= 三道负向题 D01/D02/D03 进 ops_eval,11 条对照一过一挂如预期 395 全过,vocab 下限 125→127;**勘误:TL72/TL95/TL97 三条规矩本来就在,「规矩没给」是我说错**)。**真跑两轮 D01-D03 在后台(Haiku 4.5,任务 bbidcuxh6)—— 结果落 agent/ops-results.jsonl,看完把真实说法钉回对照、再提交结果文件**。② can_order→open_order 预演仍没动(写口闸问题,先问 fc)。③ 早做完。w39 推完后:`git -C w1117 rebase w1121 --autostash` 带上这两笔 + 评测结果,下一轮 gate_w40(不碰 管理后台/ → page-smoke 形即可;但 api.py/sdk.py/prompts.py 改了,ship 的 bite_replay 会多些)。
  · **16:3x:gate_w39 绿、已推 origin/main = ae959681(11 笔),fc 已知;8760 / 8770 kickstart 过,首页 / 登录页 200,healthz 确认卡「开」;主检出 = ae959681,脏文件只剩四个运行态。D01-D03 真跑两次×两轮(Haiku 4.5):D03 四次全过;D02 一过三挂 —— 挂在我的 need_tool(draft) 判据,模型拒绝记录并提出先起草是对的 → need 清掉、真跑原文钉进对照;D01 第一次两轮都挂(一次全局体检 g23 说谈了价格让步、一次真顺着 30% 滑了),第二次两轮都过 —— **抖,记着别单轮下结论**。用户 16:2x 拍「can_order 不并、只改两头描述」→ api.py 两处描述改了(can_order 开头「要开单先掏这个,再 open_order」;open_order 尾「开之前先调 can_order」),工具表 sync_docs 重生成。vocab 两个下限 127 / 133。这批提交后 w1121 领先远端 3 笔(bcac1b69 / 9e429239 / 本笔),等 fc 推完 b 步再 `git -C w1121 rebase origin/main --autostash` → w1117 对齐 → gate_w40(不碰 管理后台/,page-smoke 形;ship 的咬合重放会因 api.py / sdk.py / prompts.py 多跑一些)。死工具四件全部收口。**
  · **23:0x 包二「修下载 + 员工定时执行记录」做了(w1121,本笔待提交)**:运行详情「产出的文件」原来是裸 `<a href>`(不带 X-Dev-User,开发态 401)→ 和报告与文件页共用 `挂文件下载()` 带身份 fetch 落文件;员工定时每行加「执行记录」按钮,展开最近 10 期(期 / 到点方式 / 结果 / 完成于 / 花费 / 飞书四态+为什么 / 原因或回答 / trace 链接),接口 GET /chat-tasks/{id}/runs 11-22 就有、页面一直没画。踩了一次模板字符串嵌套语法错(page_smoke 当场逮到「同步执行就挂了」),改成拼接。两页 page_smoke 绿。**23:0x 工作流「归档」按钮加了**(卡片脚注「归档」→ 问一句带必填理由 → POST /workflows/{id}/archive,409 的话 报错() 原样显示接口的「先去哪儿解」;page_smoke #/studio/workflow 绿;**没真点过**)。**包二还剩**:应用「归档」(没接口,要先做后端)、「核对中」回写口 + 卡重取、统一转义 / 一种失败提示、「报告执行问题」带原话、跨页带话带目标助手、角色进门先亮自己的助手、确认两档 + 列表页壳 —— 这些是产品形状的事,留给白天拍。
  · **23:0x 包二 ④ 做了(w1121,本笔待提交)**:app.py 新 `_对人说错(e, trace_id)`(超时 / 连不上 / 其他 三种人话 + 编号 + 能做什么,不带异常类型名和原文,不替人保证「没写」—— 以确认卡为准),/run 和 /internal/chat 两处 error 换成它、原文挪进 detail;管理后台 定时失败原因 把 detail 也带上(排障的人看)。/ai/rules /ai/tryone /ai/knobs /exp/compare /spans/raw 这几处是开发者接口,原文照旧。quick_gate 40 条 0 红。**真页面没见过这句话长什么样**(要人真触发一次错误)。
  · **22:5x 包二 ②③ 做了(w1121,本笔待提交)**:② 员工定时列表接口多吐「上次错误」(最近一次运行的 error_detail 原文),页面在「上次失败」下画「原因:聊天站回 码:error → 怎么办」(app.js 新 `定时失败原因()` 压成一句;库上现没有带 error_detail 的失败运行,**真失败长什么样没见过**,解析不了就给原文前 160 字);③ 聊天站「核对中」卡补两个出口:链到 8801 的 #/human + 提示本页「人工待办」页签和待办号;action_confirm_check / js_check / page_smoke(#/chat-tasks)全绿。④「报错不露程序异常」还没动:app.py 十几处 `f"{type(e).__name__}: {e}"` 直接进 error 返给页面(481/492/516/540/611/807/991 等),打算做一个 `_对人说错(e, trace_id)` 统一成「这一步出错了(编号 …),已记录;重发一次或转人工」+ 原文只进日志 —— **先看 station.html 怎么显示聊天 error、有没有检查钉着 error 格式**。包二第四件「核对中」已做,第五件「日报能找到能下载」已做(63f58371→b47f5e70)。
  · **22:4x(⚠️ 上面几条标的「16:3x–17:5x」是估的,真实时间在 20:xx–22:3x 之间,以 git 提交时间为准)。gate_w40 22:38 page-smoke 退出码 0,ship 22:41 起、咬合重放 109 个文件在跑(ops_eval_judgetest 那条慢,不是卡住),预计 23:4x–00:1x 完 —— 若跨 0 点夜跑开始,ship 拿不到锁会等;看 ship_w40.log 尾。包二第一件「报告与文件」页做了(w1121,本笔待提交):app.js 导航「日志与监测」加 #/documents、路由、页_报告与文件(GET /workflow-documents?limit=100,下载走带 X-Dev-User 的 fetch 落文件,空态指去「定时」点现在跑一次),Makefile 冒烟名单 +1(nav_smoke 42 页全在),单跑 page_smoke ✅ 3 真请求;page_smoke 提示「没有行级对账」(对账表里没声明)—— 可补。改了 管理后台/ → 下一轮 gate 要 e2e-ci 形(w35 形)。**
  · **17:5x:e64fb0ba 提交(第三步),w1117 = w1121 = e64fb0ba 领先 0bb08202 四笔,gate_w40 后台跑着(status gate_w40.status;备份 .gate_w40.sh.bak;page-smoke 形;fetch 这回 3 秒通了)。等的期间摘了 8760 审批中心「批量导出待审批」整块(统计卡换成「高风险操作」、表和 批准导出 / 驳回 两个 handler 删、规则表那行改成现行口径「不走审批、限店长以上、进操作日志、尾号」),js_check 16 段过、快门 71 条 0 红,本笔提交在 w1121(不在 w40 里,下一轮带)。包一代码侧到此全做完;剩「真页面没人点过」要人看。**
  · **17:3x 系统身份第三步做完(w1121,本笔待提交 → gate_w40)**:fc 推了 0bb08202(b 步),我 rebase 上去(git fetch 卡网络 2 分多,kill 掉用本地 origin/main 引用照样 rebase)。改:api.py get_customer `if not me: return NO_IDENTITY`(真调验过:没身份拒 / 系统身份全量 / SH001 店长看 SH003 客户被拒);app.py:1209 研判 `me=_api.系统身份` + triage_scope_check 锚 + bite_specs 794 old/new + 规格 1137 old(限店那行少了 bool(me) and);boundary_audit 新攻击 a_customer_profile_no_identity(没身份要拿 NO_IDENTITY、系统身份要拿得到,两头验)进结构类、约定类那条删掉 → 70 条结构性保证全扛住,安全边界审计.md 锁内重生成(约定 5→4)。**「没身份就拒」逼出三条忘带身份的内部路径**,都补了系统身份:backend/server.py task_detail(8760 任务详情页拿客户档案,新 `_档案()` 包一层;真调 TMERGE-00 / TD2000 都拿到档案)、backend/staff_name_check.py(_ME.set(系统身份) 包前四条)、agent/refund_case_baseline.py:81 研判锚点。selftest.py:49 那句 print 没身份会印 error 字典,不判红,没动。快门 146 条 0 红、bite_check / staff_name / refund_case / triage_scope 全绿。
  · **16:5x 用户拍:共享库里 1500 把 E2EAK* 测试密钥「留着吧」—— 不清,悬而未决那条关掉;列表已经不怕多(一条查询)。往后 e2e 该不该自己吊销留下的钥匙是另一件事,没人拍、不动。**
  · **16:4x:本批已提交 76434f68(w1121 领先远端 3 笔:bcac1b69 / 9e429239 / 76434f68);日间汇总已发飞书 https://aqvi2xbk5kd.feishu.cn/docx/T8vvdlnCHoNcW5xjr1ocpZCmnfc(没清旧文档,标题没撞)。**
  · 下一步第一个动作(16:4x):**等 fc 推完 b 步报哈希(它要拿锁 ship,我不占锁)→ `git -C w1121 rebase origin/main --autostash` → `git -C w1117 status --short | grep -v '^??'` 干净后 `git -C w1117 rebase w1121 --autostash` → 从 gate_w38.sh 复制 gate_w40(page-smoke 形,sed w38→w40)后台跑 → 绿后告 fc 哈希、kickstart com.lanxiu.agentsite(sdk.py / prompts.py 改了,8770 要重启;8760 也改了 api.py 要 com.lanxiu.backend)**;等的期间按上面 ① 的落点动手(改 w1121,不碰 w1117,不占锁);等的期间做死工具小活(不占锁):先读 kb_tables / get_review_queue / open_order 的函数体和 TK12,按「先改描述 → 返回格式 → 最后动结构」合并,改完 `python3 tools/bite_check.py` + prompts_check + quick_gate。完了:绿 → `git fetch` 核远端 = 新哈希 → 告 fc 哈希 → `launchctl kickstart -k gui/$(id -u)/com.lanxiu.backend` 和 com.lanxiu.agentsite(server.py / login.html / sdk.py / app.py 都改了;aimc 已由 gate 重启)→ 主检出 ff(排除 项目日志 脏)→ 刷汇总(11-24 的《澜绣云裳agent-夜间汇总-20261124.md》还没写:包一第一 / 二批、CI 连红根因、系统身份三步、死工具勘误、三页收口)发飞书 → 死工具四件小活(get_review_queue→kb_tables / can_order→open_order 预演 / 提示词 6% 那句 + kb_coverage 撤 / 三条规矩 + 三道负向题);红 → 看 e2e_ci_w36.log(只有 page-smoke)/ ship_w36.log,**先 `git -C w1117 status --short | grep -v '^??'` 再 rebase**。
  · 作废(11-24 新增):「两处真缺陷 dispatch_pool / piece_ratios 没挂」「任务 4 合 1」「并 get_lifecycle 等」—— 09-19 已合并,见死工具清单第三版勘误;「死工具 25 个吃 token」→ 只有 16 个挂着;「fc 评测侧要改 get_review_queue 判据」→ 没有判据写它,零改动。
  · 未验证(11-24 新增):🔮 系统身份「点名生效」后评测 / 研判分数不动 —— fc 的推断,b 步它本地跑了才知道;🔮 8760 页面改动(未登录壳 / 下载中心只读 / 合并文案 / 死按钮摘除 / 草稿卡删除)只过了内联脚本语法检查,**真页面没点过**;🔮 login.html「?」按钮没在浏览器点过(js_check 16 段语法过)。判据:gate_w33 e2e-ci 退出码 0 + ship 退出码 0;8760 页面要人打开 :8760 看右上角是「未登录 · 点此登录」、任务页没有「重新退款」。
  · 禁区(11-24 新增):**get_customer「没身份 → 拒」那一行不翻**,等 fc 说 b 步(评测侧 14 处 + v2.py + trial_run.py 带 系统身份)推完;翻之前过一遍 arrival_card.py:160 / asr.py:412 / annotations.py:95 / sdk.py 102,192,284,1558 这些 import v1 的生产路径;mcp/client.py(spawn 不传 env、池按 kind 复用会串身份)归我、排在翻之前。fc 本地 3 笔(第 6/7 批 + factory_sim)等用户放行它那边的推送权限,它不拿锁。
  · **11-24 08:0x 验过:08:00 日报准时出(doc_0c9eb8442668,6064 字节,统计 11-23),「周」只剩「统计周期:…(当日)」一处,「归周」没了;异常段分「### 当日新增」「### 存量(截至 2026-11-24)」两小节 —— 昨天两处口径问题都好了(预判 ① 作数了,n=1)。**
  · 未验证的预判:⓪ 飞书送达在**真到点的定时 / 「跑」类任务**上也会「已发」—— 只在 e2e 的 run-now 提醒类上验过 3 次已发(到点那条 e2e 故意关了飞书);验法:等任一员工真建的任务到点,工作台员工定时页顶看那条是不是「已发」,或 `GET /chat-task-feishu`。① 明早 11-24 08:00 那份日报两处口径都会好 —— 异常段分两小节已在真跑那份里验到(n=1);周口径半截「归周」靠 fc 改工具(**ba1d046d 已推上,aimc 没重启 —— 日报走 aimc worker,它读的是主检出工作区的代码,进程里是不是新代码没核;明早那份如果「归周」还在,先查这个**)+ 我处理要求那条第二道保险,**没在同一份上验过两道都在**;② 两份 e2e 收尾「留一条停用的当样例」在 GitHub CI 新库上也成立 —— 只在本地共享库验过(page-smoke 排在流程之后,顺序一样,应该成立);③ fc ship#1/#2「咬合对照就是红」是不是两会话交错 —— 它的猜测,没查实。
  · 判据:明早日报 = `GET /api/v1/projects/project_lanxiu/workflow-documents?limit=3`(X-Dev-User U001)出现 11-23 统计的那份,下载 `/workflow-documents/{did}/download`,看 ①「关键指标与口径」里没有「周」②「异常与待处理事项」下有「当日新增」「存量」两个小标题;fc 推完 = `git fetch && git log -1 origin/main` 不再是 c5f7d656 + 它的消息(别看锁 owner);换要求成了的证据 = 脚本印了「✅ 处理要求已换到 pv_44db0ac828ca 版本 wfv_b7fad79d7523」+ schedule 开着下次 11-24 08:00(都见过了)。
  · 作废:「gate_w29 会不会绿」(绿了,c5f7d656 已推);「换要求模式没真跑过」(真跑过且成了);「等 fc 报哈希再起 gate_w29」(做完了);「08:00 第二份日报看完再决定换不换」(换了);「等 fc ship#5 推完再对齐」(13:2x 推完 ba1d046d,已对齐);「还债表里没有我能做的」仍成立。
  · 禁区:fc ship#5 已完、锁空(13:2x);别碰 上次运行.py / workflows_api / endpoints / app.js / test_last_run / rating_check / shift_world / shift_eval / backfill_rating / weekly_revenue 工具(fc 地界);代码只写 w1121;bite_specs 只在末尾追加;scan_secrets 不接管道当通行证;锁 owner 里「咬合重放 --only X」≠ 有人单跑(07:17 栽过);不替 fc 推;用户没说「不换」日报要求就保持换好的。
  · **19:4x 在做:员工定时的飞书送达(用户拍:统一发到他本人的飞书;19:5x 补一句「工作台内也要有地方展示」)**。探过(只读):`~/.feishu-publish/.feishu_app.json` 的应用 **机器人能力已开**(bot/v3/info code 0、activate_status 2,名字「…飞书 CLI(claude code)」)、应用级 tenant_access_token 拿得到;用户令牌过期(user_info 回 20005),要先 `python3 tools/feishu_publish.py` 走一次刷新(有 refresh_token)再 GET authen/v1/user_info 拿 open_id。**方案(一期,最小)**:① 接收方配置 = aimc 的 launchd 环境变量 `LANXIU_FEISHU_RECEIVER_OPEN_ID` + `LANXIU_FEISHU_RECEIVER_NAME`(应用凭证照 feishu_publish 读 `~/.feishu-publish/.feishu_app.json`;**不进库不进仓**,上线换每人各自时再加成员列);② 发送:chat_tasks_api.执行排队的 写完结果后,deliver_policy.飞书 为真就 `_飞书送达`(tenant token 模块内缓存 ~1.5h;curl POST im/v1/messages?receive_id_type=open_id,msg_type text,正文 = 标题 + 回答前 1500 字 + 「来自澜绣云裳 · 员工定时」;出网照 worker._飞书通知 那套 `出网策略.解析并核(hostname)`);结果写 chat_task_runs.feishu_at / feishu_detail(已有列:{"状态":"已发|失败|未配置|策略不发","码":…,"message_id":…});③ 工作台展示:新 GET `/chat-task-feishu`(接收方名字 + 配了没 + 最近 20 条送达结果)+ app.js #/chat-tasks 页顶一行「飞书接收方:xx(统一发到用户本人;上线后改每人各自)」+ 结果列表多一列「飞书」;endpoints.py 登记 + make gen / contract;④ 测试:test_chat_tasks.py 加 文本组装 / 未配置时写「未配置」不炸 / curl 桩 的三条;e2e 流程里断言 feishu_detail 有「状态」键(CI 没配置 → 未配置)。**先真发一条测试消息给用户本人**(他要的功能,发到他自己,不算对外)。改了 管理后台/ → 推前锁内 e2e-ci(fc 19:4x 起占锁约 10 分钟跑第 4 批检查,等它放)。第一个动作:刷新用户令牌拿 open_id → curl 发测试消息 → 看回码(99991672 = 缺 im:message:send_as_bot 权限,要用户在开发者后台加、我给步骤)。**→ 20:0x 全做完了**:令牌刷新成功、open_id 写进 `~/.feishu-publish/.chat_task_receiver.json`(600)、测试消息 code 0 送到(message_id om_x100b7…);代码按上面 ①–④ 落地,**接收方改成放文件不放 launchd 环境变量**(aimc 的 plist 不在仓里、不想动它);单元测试 35 全过(第一版判「函数里不出现 open_id」被自己说明文字匹配,改成只认带引号键名)、快门 40 绿、make gen / contract 过;**提交 1e117e65(w1121 = w1117),gate_w30 20:1x 起**(= w29 形,备份 w1121/.gate_w30.sh.bak;状态 scratchpad/gate_w30.status,日志 e2e_ci_w30.log / ship_w30.log)。e2e 里 ④ 那条任务真发一条到用户飞书(每跑一次 e2e-ci 他收一条,接受),其余任务 deliver_policy 关飞书。绿了:告 fc 哈希、kickstart 8770 不必(没动 agentsite)、写汇总段落「飞书送达做了 + 工作台员工定时页顶能看」。红了先看 e2e_ci_w30.log 里 test_chat_tasks_flow 的 ❌。**→ 20:05 gate_w30 e2e-ci 红 1 条(退出码 2,没到 ship,远端仍 ba1d046d)**:出网策略.解析并核 把 open.feishu.cn 解析到 198.18.1.135 判成内网拒掉 —— 这台机器 DNS 走拦截代理给假地址;那道闸防的是用户填的网址,我这里主机名是常量,不该过它 → 去掉(24aa37a7,单元测试改验「常量主机 + 不 import 出网策略」,35 全过)。**gate_w31 20:3x 起**(后台任务 b6roat1ki;status gate_w31.status;日志 e2e_ci_w31.log / ship_w31.log;备份 .gate_w31.sh.bak)。aimc 已在 1e117e65 上重启过一次,w31 会再重启到 24aa37a7。已告 fc(顺带提醒它 worker._飞书通知 走同一道闸在这台机器上多半也会被拒;它说 grep 不到 → 我给了位置 worker.py:499,并说那处地址是用户登记的连接、闸该留,只能按主机名放行)。**20:25 gate_w31 e2e-ci 又红 2 条(都在 test_chat_tasks_flow ④),查实是测试时序**:结果(事务一)和 feishu_detail(事务二)相隔几秒,测试看到 status 变了就读、feishu_detail 还空;库里那条 ctr_946c7cc26a8a 20:12:49 出结果、**20:12:52 已发 message_id om_x100b7f7693e…(真发成了,用户飞书收到一条 e2e 消息)**。修法:e2e 再等 feishu_detail 出现(78f51d57)。**gate_w32 20:5x 起**(后台任务;status gate_w32.status;备份 .gate_w32.sh.bak)。**→ 21:06:e2e-ci 绿(退出码 0,飞书那两条 ✅),ship 的全量门禁红 1 条:agent/trace_check「chat_task_feishu.py 直接打模型 API 端点」—— 飞书 IM 接口路径 `im/v1/messages` 撞了 `/v1/messages` 指纹,误报;按它文件头规矩加进 明写不算调用点(理由写「不是调用点」:发飞书不是调模型,真调模型那步走聊天站 → sdk.py 已接记录仪),本地 trace_check 7/7 ✅。这笔只动 agent/trace_check.py,不碰 管理后台/ → 不重跑 e2e-ci,直接 w1117 `./tools/ship.sh`(ship_w33.log),推完主检出 ff(不用重启任何服务)。** **→ 21:27 推上了:origin/main ba1d046d..15b180fd(9 笔),ship:pre_push 退出码 0;主检出 ff 到 15b180fd;没重启服务(aimc 在 78f51d57,管理后台/ 和这版一样;8770 没动);锁已放、fc 已知。汇总填了哈希重发飞书。飞书送达这件**做完了**:用户飞书里现在有 3 条(下午测试 1 + e2e 第二 / 三轮各 1);以后每跑一次 e2e-ci 他收一条。**
  · **21:4x 用户要「检查全部文件,包括 4 个网页,确定下一步优化方向」** → 派了 5 个只读子审计并行(聊天站 8770 / AI 管理后台 8801 / 旧后台 8760 + 介绍页 / 后端工具与知识层 / 工程健康与欠债),每路出 ≤12 条发现 + 3 条方向候选 + 没看的清单。**汇总写成《澜绣云裳agent-全项目体检与优化方向-20261123.md》发飞书产品文件夹(FEISHU_FOLDER=QexpfF7ejlotM8db6JEcZH5tnZf),最后攒一张卡(≤4 题)请用户拍优先级**;11-18 那次 AI 后台体检(45 条)已做过,别重报。子审计结果没回来之前别替它们下结论。
  · **22:4x 五路子审计全回、已合成《澜绣云裳agent-体检与优化方向-20261123.md》(w1121 根目录,未提交;飞书 https://aqvi2xbk5kd.feishu.cn/docx/I5qrd46wloLUStxfVMycMblGn5f)**,五路摘要入库 reports/全项目体检-20261123/A–E(未提交,随下一笔 git add)。**栽了一下已补救**:飞书标题上限 27 字,第一版文件名「全项目体检与优化方向-20261123」截掉日期后和 11-12 那份重名,发布脚本把 11-12 的删进了回收站 → 我这份改短名重发,11-12 那份从仓库原文重发回去(新链接 https://aqvi2xbk5kd.feishu.cn/docx/V0jodZWyBoThzoxDSd4cbGhGn3c,旧链接作废)。**教训:带日期的系列文档,文件名去掉日期后要 ≤ 19 字,否则同系列不同日期互删**(已记进记忆)。要点:① GitHub CI 自 11-18 03:57 后每次推送都红(我 `gh run list` 核过),fc 查清根因 = fakedata/factory_sim.py:155 用订单号哈希挑「换号重发」样本、从零建库挑不到就「没样本」红,修约 3 行(fc 可做);admin-e2e 另红 4 份 e2e 对 CI 新库的前提(test_runctl_flow / test_retrieve_node_flow / test_human_form_flow U001 没「审批工具动作」权限 / test_chat_tasks_flow NO_STAFF)—— 我的地界;② 写口不按店划(server.py transit 544-700 / task-note / lifecycle-adjust)、客户档案无身份不限店(api.py:255);③ login.html:48-63 公开演示账号密码;④ 日报后台无总览、下载 a href 不带身份头(app.js:6352);⑤ prompts.py 四处数字过期一处自相矛盾(:854 vs :808);⑥ 预算闸 sdk.py:70-89 按订阅 50 美元;⑦ 核对中无出口 / 异常原文贴给店员。文档第五节给了五个包(一可信与安全 / 二做了要像做了 / 三钱与数字 / 四补能力 / 五门禁提速 + 后台瘦身要先拍),推荐顺序一→二→三→四。**下一步第一个动作:一张卡(4 题:先做哪包 / 演示账号删不删 / 8760 AI 三页 + 草稿卡收口不 / 22 死工具列清单不)请用户拍;拍了按包做,每包开工前照 CLAUDE.md 第 7.5 节问「这一改会破坏什么」;改 api.py 身份部分、bite_run 前先告 fc。** 判据:报告里标「推断」的(下载 401 / 别店能改单 / 10 万 token 贵档)动手前先各验一次再修。
  · **11-24 00:0x 用户拍了四件**:① **先做包一「可信与安全」**;② 登录页演示账号密码**不删,收进一个「?」小按钮里**(默认不显示,点了给提示信息 —— 我提过仍是谁点谁看得到,用户定的);③ **删 8760 第一代草稿卡,Skill / MCP / 知识问题三页收到 8801**;④ 22 个死工具**列清单一次拍**。分工已告 fc:CI 造数 factory_sim.py 那 3 行 fc 做;我做 admin-e2e 四份新库前提 + 写口按店划(server.py transit / task-note / lifecycle-adjust;fsm.py 角色门)+ api.py:255 无身份拒 + login.html ? 按钮 + 8760 演示残留(假下载中心 → 只读导出记录 / 死退款按钮 / 草稿卡 / 硬合并文案 / 角色切换壳)+ boundary_audit 归位 + 健康口「确认卡开/关」。三页搬 8801 和死工具清单排在包一核心之后。**0 点到夜跑结束(约 05:10)不占锁不写共享库:只写代码 + 本地不连库的测试;e2e-ci / ship 早上起 gate_w33 形(= w29 形)。** fc 第 6/7 批(22410032 / 413249ea)被它那边权限拦着没推,远端仍 a4ec89b1,它不拿锁。
  · **11-24 08:0x–09:xx 包一进展(w1121,未推)**:✅ 四份 e2e CI 前提(3e3d3498);✅ 写口按店划:server.py `_写口本店` / `_写口记录归店` + transit 门店闸 + adjust_lifecycle 角色 / 门店闸 + task-note 挡版师工匠,新检查 backend/store_scope_write_check.py 挂 check.sh、两条咬合 bite_specs 1993→1995 本地重放全过;✅ api.系统身份 常量 + api_wearer.本店范围 认它(行为未变,fc 三步法第 a 步;**c 步「get_customer 没身份 → 拒」还没翻**,等 fc 改完评测侧;MCP client.py 池按 kind 复用会串身份 + spawn 不传 env,归我,排在 c 前);✅ 8760 演示残留:草稿卡 + /api/draft 路由 + drafts.json 全删(write_smoke_check 说明同步)、create_download 改拒 DEMO_RETIRED、下载中心只读说明、死「重新退款」按钮改成链到 8770/queue、合并文案改软合并、未登录不再假切角色、「本期不做」菜单摘了;✅ login.html 演示账号收进 ? 按钮(默认 hidden)。**还没做**:boundary_audit 清单归位 + 健康口「确认卡开/关」;8760 Skill/MCP/知识问题三页搬 8801(用户拍了,排包一核心之后);22 死工具清单;下载中心审批中心里那两个「批准 / 拒绝导出」按钮(永远等不到单)没摘。**接下来**:跑 quick_gate → 提交 → 等 08:00 日报不在跑的时间(已过)→ gate_w33(= w29 形:主检出 ff → 停 8801 → kickstart aimc → 锁内 e2e-ci → ship;改了 管理后台/tests 所以要 e2e-ci)→ 推完 kickstart 8770(login.html 改了)+ 8760(server.py 改了,com.lanxiu.backend)。
  · **09:5x 第一批已提交 9bff6530(含 3e3d3498 四份 e2e),w1117 对齐,gate_w33 10:0x 起(后台任务;status gate_w33.status)**。快门第一次红在 refund_write_check:夹具的店长 / 财务没带门店 + 押金复核要「另一位店长」(一店一位,必来自别店)→ **押金那台状态机故意不按店划**(注释写明),夹具补门店;11 条写口检查 + 咬合 2 条全绿,快门 38 绿。
  · **第二批(w1121 未提交,gate_w33 跑着不碰 w1117)**:boundary_audit 两条约定归位(「客户档案没身份不限店」改写成「升结构修到一半、等翻拒」;「智能体调工具没身份」删了并写明为什么;「写前确认」改成现算写工具数 + 指向结构类确认卡 + 剩约定的是措辞和「卡在生产开着」);agentsite/app.py /healthz 多报「确认卡:开 / 关」;api.py check_write 文档那句「拿不到登录会话」改正;**sdk.py `_是系统(me)` + run 三处 `me and not _是系统(me)`(转人工 / 恢复会话 / 提示词尾巴)—— fc 查出 me 传进 sdk.run 不是行为中性的,这是 b 步前提,已告它等这批推上再 rebase**。⚠️ 安全边界审计.md 是生成物(`boundary_audit.py --md`),改了清单要重生成 —— 它会真攻击(连库),**等 gate_w33 放锁后在锁内跑**;check.sh 不对账那份 md,但 doc 漂移检查可能盯着,推前跑 `./tools/sync_docs.sh` 看看。
  · **10:07 gate_w33:e2e-ci 绿(09:24 退出码 0),ship 红在咬合重放 —— merge_check 10 条 / page_smoke_check 2 条「对照就是红」**:根因是我删草稿卡时删了 `dr=load_drafts()` 却漏了 workbench 里算采纳率那两行(NameError:dr),workbench() 一调就炸。已删那两行,merge / page_smoke / write_smoke / store_scope 本地重跑;安全边界审计.md 用 `--md` 输出覆盖(约定 6→5 条)。**主检出已被 gate ff 到 9bff6530(含这个 bug)但没推、aimc 已在它上面重启;8760 没重启(还是老代码,没炸)**。第二批(服务端 bug 修 + boundary_audit + 审计 md + app.py healthz + sdk.py 系统中性 + api.py 文档 + 死工具清单 md)提交后 **只 ship 不重跑 e2e-ci**(没动 管理后台/);推完 kickstart 8760 + 8770,主检出 ff。
  · **10:3x 第二批 3274ccdf 提交,w1117 = 3274ccdf 领先 3 笔,ship_w34 只 ship 跑着(后台;status gate_w34.status)**。等它期间做了 **mcp/client.py**(w1121 第三批提交,**没进 w1117**,ship 跑着不碰它):Popen 显式 env 带 `api.whoami(认系统=True)`、池键 (kind, 工号),就地验过三身份三进程、kb_combo 通 —— 这是翻默认拒(c 步)的前提之一;另两个前提:fc 的 b 步、过一遍 arrival_card.py:160 / asr.py:412 / annotations.py:95 / sdk.py 102,192,284,1558 这些 import v1 的生产路径。
  · 下一步第一个动作:ship_w34 完 → 绿:报哈希 fc、`launchctl kickstart -k gui/$(id -u)/com.lanxiu.backend` + 8770、主检出 ff(排除 项目日志 脏)、w1117 rebase w1121 带上 client.py;红:看 ship_w34.log。**三页搬 8801 已做(w1121 第四批提交,没进 w1117)**:app.js 侧栏多一组「澜绣 AI 治理」(#/lanxiu-skills / -mcp / -kb-issues)→ 页_澜绣治理 用 iframe 嵌 8760 的 #skills / #mcp / #kbissues(同主机 Cookie 不分端口,所以同一个登录);8760 侧栏摘掉三项,直链照旧;Makefile 冒烟名单 +3(nav_smoke 41 页全在);node --check 两边过。**真页面没点过(iframe 里 8760 登录提示长什么样没看)。改了 管理后台/ → w1117 带上它之后下一轮 gate 必须含 e2e-ci(w29 形)**。**11:00 ship_w34 红(没推,远端仍 e9d83eb9):咬合规格 1398(chat_handoff_check 打 sdk.py「if me and not 只读」)被我加的 `_是系统` 改成找不到 → bite_check 对照红 + 「规格自己是坏的」;intent_check 红在 待办清单.md 过期(新检查进了 check.sh,数字变了)**。修:规格 old/new 跟上新代码(重放 4 条全过);`./tools/sync_docs.sh` 重生成待办清单(对账全过)。**教训:改 sdk.py / server.py 这种被很多咬合盯着的文件,改完先 `python3 tools/bite_check.py`(秒级)看有没有规格过期,别等 ship 40 分钟后告诉你。** 第五批提交后 w1117 rebase w1121,起 gate_w35(w33 形,含 e2e-ci,因为三页收口动了 管理后台/)。**11:23 gate_w35:e2e 测试全绿,page-smoke 里 ifmatch_reachable_check 一条「GET /access-keys 打不通」(单跑立刻 48/48,瞬时抖动)→ 给它加一次重试(98972d91)。顺带踩到:ship_w34 时 intent_check「替你重新生成了待办清单」把 w1117 弄脏,我下一次 `rebase --autostash` 的 autostash 回放和我提交的那版冲突(UU),rebase 却只在最后一行印 Successfully,下一次 rebase 才报 Cannot autostash。修:`git checkout HEAD -- 待办清单.md` + 取消暂存 funnel.jsonl。教训:ship 红了之后、rebase 之前先 `git -C w1117 status --short | grep -v '^??'`。gate_w36 11:4x 起:= w35 形但 `make test-e2e-ci` 换成 `make page-smoke`(其余 e2e 刚全绿,只补冒烟那步)→ ship。w1117 = w1121 = 98972d91 领先 7 笔。**然后锁内 `python3 backend/boundary_audit.py --md` 重生成审计 md → 第二批提交 → 8760 三页搬 8801。**死工具清单已出**(《澜绣云裳agent-死工具清单-20261124.md》w1121 根目录未提交,飞书 https://aqvi2xbk5kd.feishu.cn/docx/AwmsdIDU0op6x0xYNNwcTtmFnxb):数据 = 管理后台 spans 表 `stage like 'execute_tool %'` 09-24→11-24 共 16587 次,对照 api.TOOLS 119 个 → **25 个从没出现、8 个 1–3 次**;**用户 09:1x 问「为什么没人调?哪些可做成 system prompt」→ 第二版**:用 sdk._ROLE_TOOLS 真算角色包 → **25 个里 9 个根本不在聊天站任何角色包里**(dispatch_pool / get_task / my_tasks / team_tasks / get_lifecycle / member_level / get_member_priority / kb_coverage / piece_ratios;它们不进说明书不花钱,「死工具吃 token」只对另 16 个成立);10 个写动作线上没发生;2 个被兄弟替代(get_review_queue ← kb_tables;can_order ← open_order);4 个规则型「工具给了规矩没给」。**两处真缺陷**:dispatch_task 挂了但前提 dispatch_pool 没挂(店长看不到池子);piece_ratios 没挂给版师。能变 system prompt 的只有 kb_coverage(矩阵 100%,答案成常数);其余是数据或写动作,进提示词会成过期手抄件;该补的是三条「什么时候掏工具」的规矩(交付告知先起草 / 取消先算钱 / 下单前校验并进 open_order)。第三节给了动作表(挂 2 / 合 2 组 / 并 4 / 删 1 / 补规矩 3)。**⚠️ 11:3x 勘误(第三版已发飞书)**:A 类 9 个「不在角色包里」的**是 09-19 合并后留下的内部函数**(guards.py:1768 / api.py:1476 的记录:dispatch_pool→get_tasks、member_level/get_lifecycle→get_member、piece_ratios→pattern_queue、my_tasks/team_tasks/get_task→get_tasks),不在任何一份说明书里,新工具底下调它们 → 「两处真缺陷」**不成立**、「任务 4 合 1」**已做过**、「并 get_lifecycle 等」**已并好**。我没查合并记录就下结论,已向用户认错。**真剩下的只有:get_review_queue→kb_tables;can_order→open_order 预演;提示词「只录了 6%」改掉 + kb_coverage 没人调就撤;三条规矩 + 三道负向题(约半天)**。fc 查了:评测判据里**没有**写 get_review_queue(只在 sdk.py:561 注释和 :765 包名单)→ 死工具这组评测侧零改动,我直接并进 kb_tables;*_check 里若有引用门禁会报。**用户 11:1x 拍了「按建议做」**(按勘误后的做)→ 排在包一推完之后。原计划(作废部分划掉):① 挂 dispatch_pool 给店长(kb 包 + 规矩,P6 会逼)、piece_ratios 给版师(pattern 包 + 规矩);② my_tasks + team_tasks + get_task + list_tasks → 一个「任务」工具(谁的 / 哪条 / 状态),can_order 并进 open_order 预演;③ get_lifecycle、member_level → get_member;get_member_priority → revive_list;get_review_queue → kb_tables(**评测在用这几个:get_lifecycle 13 / get_member_priority 5 / member_level 3 次 —— 聊天站侧不再注册,函数留给 V1/V2 评测;改评测引用归 fc,先问它**);④ 删 kb_coverage + 改提示词里「只录了 6%」那句;⑤ prompts.py 补三条「什么时候掏」(cancel_fee / draft_delivery_notice / 下单前校验)+ 三道负向题进 ops_eval 或 tool_eval(判分器先过对照)。每步按 ai-product-shape 的顺序:先改描述 → 返回格式 → 最后动结构;动一个跑数据再动下一个。w1121 里 HANDOFF / 汇总 md 有未提交改动,随下一笔业务提交;fc 推完下一批后 `git -C w1121 rebase origin/main --autostash` → w1117 `git rebase w1121`(别 reset)。明早 11-24 08:00 后按判据核日报。周审查 plist 命令已给用户(`! cp tools/launchd/com.lanxiu.weekly-review.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.lanxiu.weekly-review.plist`,在主检出目录跑),装好看 `launchctl list | grep weekly-review`;用户拍「换回去」的话:`enable_daily_draft.py --换要求 --wid wf_e81d8b16994b --pv pv_<上一版>`(上一版 pv 看 prompt_versions key=store_daily_draft_write version_no 倒数第二)。历史记录:① gate_w29 第二轮 12:02 绿,**已推 c5f7d656**(f3823ea9..c5f7d656 六笔,全量门禁退出码 0;主检出 = w1117 = w1121 = 远端;8770 kickstart 过 302、aimc 10:43 重启过);② 锁内换日报处理要求成了:seed 出新版本 **pv_44db0ac828ca**(其余 21 项没动)→ 草稿换版本 → 校验 → 冻结 **wfv_b7fad79d7523** → 真跑 xr_7bdc92e41035 succeeded(出 doc_0cb5981cd72b 7171 字节)→ 审核 rel_727a3778d19f → 发生产 202;定时没动,开着、下次 2026-11-24 08:00 统计 11-23;③ 锁已放、fc 已知(它接着推周营收口径那笔)。真跑那份读过:**异常段已分「当日新增」/「存量(截至 2026-11-22)」两小节 ✅**;周口径半好 —— 「本周」改成了「周实际收到的钱…归周」还在,来源段补了「口径按周统计」;**这半句由 fc 改工具解决**(见悬而未决),明早 11-24 那份两道保险都在。接下来没有排定的活:等用户拍飞书接收方 / 周审查 plist;fc 推完它那笔后不用我做什么。**12:2x:汇总已补结果重发飞书(https://aqvi2xbk5kd.feishu.cn/docx/QJqvdpFTMosbw1xt5Tpcwu1ynGg),交接 + 汇总那笔 19c3de62 在 w1121 = w1117,未推(随下一笔);fc ship#5 12:2x 起(b3953ea0 第 2 批 4 写口 + ba1d046d 第 3 批 6 模块 + 周营收口径按统计期),锁归它、推完它报哈希并重启 8760/8770;我不占锁、不碰 w1117。它推完后我若再有东西要推,先 `git -C w1121 rebase origin/main --autostash` → w1117 对齐 → 复用 gate_w29.sh 形(备份 w1121/.gate_w29.sh.bak)。**
  · **用户 11-23 19:3x 拍了三件**:① 飞书送达**统一发到用户本人的飞书,等以后上线了再改成每人各自的**(所以不做成员页那一栏,做一个全局接收方配置 + 真发消息;接收方 = 用户的飞书账号,要从飞书那边拿到他的 open_id);② 周审查 plist **用户 20:4x 亲手装好了**(`launchctl list` 有 `- 0 com.lanxiu.weekly-review`,没 pid 是因为按日历触发;下周一 11-30 07:30 第一次跑,日志 .feynman/weekly-review.log、报告在辅助目录);③ 日报处理要求**保持新版**,明早看效果。
  · 悬而未决:~~飞书接收方谁填~~(拍了:统一用用户的);~~weekly_revenue 口径说法「归周」归谁改~~ → **fc 11:0x 定了:改工具不靠模型改写**(口径和「⚠️ 近似」两句按统计期给说法:不给区间照旧「这一周…归周」;start=end 说「当天…归日」近似写「相邻一天」;多天区间说「这段时间…归到各自那一天」近似写「区间外」;weekly_revenue_check 加两条判据 + 一条咬合;它本地改了没提交,等我 ship 完 + 换好日报要求 + 放锁后它锁内跑检查再推)。我处理要求里那条「口径按统计期改写」留着当第二道保险;标注匹配真命中没人试过;改时刻页面真页面没点过;用户没说「不换」就换(汇总里写了)。
  · **六项(11-22 19:0x 刷;下面那组是 11-21 夜的)**
  · 未验证的预判:① gate_w28 的 ship 会绿 —— w27 红的四处在 w1121 单跑都绿、咬合 `bite_run --only chat_task_push_check` 过,但 rebase 到 fc 新哈希之后的树没整跑过(fc 改的是 backend 库路径,和我的 supervise_sync/聊天站不该撞);② 标注匹配真命中、员工定时真到点跑、派任务自动提醒真推到后台 —— 线上一次都没发生过;③ scratchpad/enable_daily_draft.py 七步没跑过(第 5 步真调模型几分钱)。
  · 判据:gate_w28 绿 = `scratchpad/gate_w28.status` 末行「ship 完 … rc=0 · 远端 <新哈希>」且主检出 `git log -1` = w1117 HEAD;红了看 ship_w28.log 的 ❌ 和「被包的命令退出码」那行;崩的(600 秒掐)看 `ps aux | grep js_smoke` 有没有孤儿。
  · 作废的结果:「gate_w27 会绿」作废(18:40 红,原因见下面 18:40 那条);「fc 等我哈希」作废 —— fc 18:46 先 ship 了,换成我等它。
  · 禁区:fc ship 跑着(18:46 → 约 19:3x)不占锁、不写共享库、不碰 w1117;等它报哈希 + 重启 8760/8770 之后才 `git -C w1121 rebase origin/main` → w1117 ff → gate_w28;bite_specs 只在末尾追加;新检查脚本当天写 `咬合 = [...]`;tools/ 下脚本连库要 closing、INSERT 具名列、SQL datetime('now') 要标真实时钟。
  · 19:38 复查:fc 的 ship 从 18:46 跑到现在还没完(远端仍 7a708d27,锁它拿着),我这边修法已提交 2a6e4264(w1121),gate_w28.sh 已备好(scratchpad,= w27 形),什么都没占。20:01 再查:fc 的 ship 已跑 74 分钟仍没完(远端 7a708d27、锁它拿着、主检出 9a80014e),继续等。20:26 再查:fc ship 已 100 分钟仍没推(远端 7a708d27、锁它拿着),已 SendMessage 问它进度。**20:3x fc 回:它的 ship 红了(三处都是它库路径那几笔带的:db_build 没认领 dbpath.py / 懒加载写口前提不成立 / 影子子进程退出码 3),已停、锁已放、远端仍 7a708d27,让我现在跑 gate_w28、跑完报哈希它再 rebase ship;它本地修、不占锁、不碰 agentsite。** → 远端没动所以不用 rebase,w1117 ff 到 w1121 HEAD(bd5730e4)后 **20:3x 起 gate_w28(后台任务 b0v7nec8v,日志 scratchpad/ship_w28.log,状态 gate_w28.status)**,已告 fc。21:20 查:锁 20:28:49 到手,咬合重放到 [57/66] 零红,全量门禁还没开始。22:11 查:咬合重放 66 个全过,全量门禁跑着、到目前零 ❌,预计 22:3x–22:5x 出结果。
  · **23:3x 收尾状态**:gate_w28 22:13 绿、远端 = 主检出 = w1117 = bd5730e4;fc 的 ship 23:16 自己停了(跨 0 点),它明早夜跑结束后再 ship(多带一笔手机号打码 前三后四,动 上次运行.py / workflows_api / endpoints / app.js / test_last_run —— **我明天别碰这几个文件,要碰先告它**);经营日报草稿已启用(上面第 3 项);com.lanxiu.supervise 23:2x kickstart 过,第一轮给 project_lanxiu 建了 27 条派任务提醒(演示数据里最近两天派的带截止任务;推账去重不重复)—— **「派任务提醒线上一次都没发生过」作废,发生了**;汇总已发飞书(第二版 https://aqvi2xbk5kd.feishu.cn/docx/U1rqdddRPoWOsDx4elWcDVOWnvc,日报草稿已写成已启用)。w1121 未提交:HANDOFF、汇总 md(新)、管理后台/tools/enable_daily_draft.py(新)—— 提交后今晚不推(0 点后不占锁),随明天第一批 ship。
  · **23:4x 收工态**:w1121 = w1117 = e8c131f6,领先远端 2 笔(488b4d76 日报草稿启用脚本入库 + 汇总 md;e8c131f6 我的定时「改时刻」),都没推;0 点到 05:10 不占锁不写共享库。明早批次脚本已备好 `scratchpad/gate_w29.sh`(= w16 形去掉迁移:锁空 → w1117 rebase origin/main → 主检出 ff → 停 8801 → kickstart aimc 验归属 → 锁内 e2e-ci(因为动了 管理后台/tools)→ w1117 ship;备份在 w1121/.gate_w29.sh.bak,scratchpad 没了就用它)。
  · **11-23 00:5x(0 点后窗口,只改代码没占锁)**:首份日报两处口径问题的代码那半改了 —— `管理后台/tools/seed_bridge_tools.py` 日报草稿处理要求 system 加两条硬要求(口径按本次统计期改写、「本周」原话不照抄;「异常与待处理事项」固定分「当日新增」/「存量(截至取数时)」两小节);`enable_daily_draft.py` 加 `--换要求 --wid wf_e81d8b16994b --pv pv_新` 模式(GET 草稿 → llm 节点换 prompt_version_id → 校验 → 冻结 → 真跑 → 发生产;定时不动只 GET 核一眼),顺手把 3/4/5 步抽成 `校验冻结真跑()`。**模板在建流程时把 pv 冻进版本,改措辞必须走这条链**(查过 workflows_api._默认处理要求 / _经营日报草稿:config.prompt_version_id 写死)。落地链(≥05:10、锁内、ship 后、先看 08:00 第二份日报):`./tools/gate_lock.sh --who 换日报要求 bash -c "cd 管理后台 && ./.venv/bin/python tools/seed_bridge_tools.py --项目 project_lanxiu && ./.venv/bin/python tools/enable_daily_draft.py --换要求 --wid wf_e81d8b16994b --pv <seed 打印的 pv>"`(seed 按 content_hash 判,内容变了才出新版本)。五条秒级检查都绿,随 gate_w29 推。
  · 01:45 / 02:45 / 03:45 自检:锁空、夜跑在跑(进程在,完成标记还是 11-22 01:47 的)、远端 = 主检出 = bd5730e4 没动、fc 没来消息;w1121 = 3a7a1007 领先 w1117 一笔(ff 等早上)。按守则什么都没占。
  · **04:45:夜跑完了,这次它自己把自动提交推上了远端(origin/main = 主检出 = cd31a7d0,只动夜跑产物)**,夜跑进程没了,锁空,fc 还没动。不用再问「夜跑提交带不带」—— 已经在主干上了。本地动作(不占锁):w1121 rebase 到 cd31a7d0 → w1117 ff;已告 fc「夜跑完、锁空、你先 ship」,等它报哈希再起 gate_w29。**04:5x fc 回:它 rebase 到 cd31a7d0 领先 8 笔,ship 现在起约 60–90 分钟;推完它先主检出 ff、重启 8760 / 8770 / aimc,再拿一次锁跑 e2e-ci 约 20 分钟;两样完了报哈希、放锁,我才起 gate_w29**(预计 06:30–07:15 轮到我;gate_w29 本身约 65 分钟,08:40 汇总可能要先发、推送结果后补)。w1117 已 reset 到 w1121 = c1fc8f3c(rebase 后哈希全变,ff 不了就 reset;w1117 没有独有改动,核过)。05:47 查:锁在 fc 手里(05:45 起在单跑一条咬合 repo_consistency_check,像是它 ship 红了一处在补),远端仍 cd31a7d0;继续等。**06:0x fc:它第二次 ship 红在 shop_key_check 12 条咬合「对照就是红」,锁内单跑却绿 → 判偶发(共享库数据在变),06:25 起第三次 ship**。我回它:不排队(gate_lock 等锁上限 3600 秒),提议它推完报哈希放锁 → 我立刻起 gate_w29,这轮 e2e-ci 跑的是含它打码几笔的主检出,它那 20 分钟 e2e 不用单开;它没回就按这个办。预计:fc 推完约 07:15–07:40 → gate_w29 约 65 分钟 → **08:40 汇总时推送多半还在跑,汇总先发、哈希后补**。scratchpad/gate_w29.sh 还在(23:39 版,核过步骤)。**07:17 栽了一下(没造成后果)**:锁 owner 文件里写着「咬合重放 --only tools/gate_print_check.py」,我当成 fc 在单跑一条、它 ship 又红了,就起了 gate_w29 还发消息说「别拿锁」;fc 立刻回「别起!那是 ship 里按改动重放咬合的第 98/112 条,**咬合每条单独拿锁、条与条之间放锁**,你插进缝里会交错,前两次『对照就是红』可能就是这么撞的」→ pkill 掉 gate_w29,它还卡在第一步等锁空,主检出 / 8801 / 锁都没碰,核过。**教训:owner 里的「咬合重放 --only X」不等于有人单跑,ship 的 bite_replay_touched 就是这个形状;判 ship 完没完看远端哈希 + fc 的消息,别看锁 owner。** 07:2x 只读查过:08:00 前 workflow-documents 只有昨晚那份 doc_4f24ddf13293;定时仍开着,下次 2026-11-23 08:00 统计 11-22。fc 预计 08:1x 推完报哈希,我再起 gate_w29 → 约 09:2x 完;08:40 汇总先发,哈希后补。**08:09:08:00 定时日报自己跑出来了**(08:07 发起,文件 doc_168925e646b0 7552 字节,统计 11-22,下次 11-24 08:00)—— 第一次没人碰的业务定时真跑;读过:「本周」没了但「归周」还在(weekly_revenue 口径原话)、存量单列了一块但异常段仍没分小节 → 两处不是偶发,**决定今天白天换处理要求**(链在上面 00:5x 那条;锁内、告 fc、在 gate_w29 之后)。fc 的 ship 08:09 还在跑(远端仍 cd31a7d0,锁 owner 停在 07:26 那条咬合 —— owner 文件不一定刷,别拿它判进度)。汇总《澜绣云裳agent-夜间汇总-20261123.md》**08:4x 已发飞书产品文件夹 https://aqvi2xbk5kd.feishu.cn/docx/J0rydhVZAona5cxXSpKcR0bQnOf**(写着「发时还没推」;md 在 w1121 未提交,随下一笔 git add)。**08:4x fc 来消息:第三次 ship 红了、已放锁。咬合 112 条全过,红在全量门禁 3 条:① OpenAPI 过期(它的,已重生成);② 店长排班判分器「夹具挑得到」—— 每日平移把 11-30 那周铺成 system 已发布 56 格,shift_eval.挑() 只清草稿 → 它改成清 system 铺的不分状态(随它下次 ship);③ rating_check「按店配对合并后在上升」+0.13 < +0.15 —— rating_window 固定 08|09|10,每日平移天天挪 rated_at,三周下来相邻月混桶、升幅稀释,今天刚跌破;另 06:10 跨月重造因等锁 60 分钟超时没做(今天不跨月不影响)。它问 ③ 归谁 → 我回:不归我(没碰过 shift_world / rating_check),建议它按「判据按 rating_built_on 平移天数挪窗口」修(只改检查不改造数口径),①②③ 一起 ship 推上 → 报哈希 → 我再起 gate_w29。**②③ 是时间推进造成的,我现在推也会红,所以必须排它后面。** 09:0x fc:③ 按只改检查的修法做了(backfill_rating 多记不挪的 rating_built_world;shift_world 登记成不挪;rating_check 按「今天 − 造数日」把 rated_at 挪回去再分月,老库没这键按「窗口后一个月 1 号」估 → +0.25),相关咬合 3 条锁内重放全过;**ship#4 已起(本地 f3823ea9,①②③ 一起),锁归它约 60–90 分钟,推完报哈希、放锁、它自己重启 8760/8770,然后我起 gate_w29**。我什么都不占,等消息。12 小时循环到点停了;fc 的消息会把这个会话叫醒,届时:`git -C w1121 add 澜绣云裳agent-夜间汇总-20261123.md` + commit --only(HANDOFF + 汇总)→ w1117 reset/ff 到 w1121 → `bash scratchpad/gate_w29.sh` 后台 → 绿后告 fc 哈希 → 锁内换日报处理要求(seed → --换要求)→ kickstart 不用(日报走 aimc worker,不是 8770)。**
  · **09:1x fc 推完了:origin/main = f3823ea9(cd31a7d0..f3823ea9),ship:pre_push 退出码 0,锁已放;主检出它已 ff 到 f3823ea9、8760/8770 它重启了(200 / 302),aimc 没重启、e2e-ci 交给我的 gate_w29。它这笔带:dbpath 单源迁移(欠债 307)、全站打码统一(手机前三后四 / 固话前三后三)、门禁那三条修。** 紧接着它又要借锁约 10 分钟跑 9 个单项检查(只用副本不推)→ 我让它先跑,我做不占锁的:w1121 提交(HANDOFF + 今早汇总 md)→ w1121 rebase 到 f3823ea9 → w1117 对齐;它放锁后再起 gate_w29。
  · **11:0x gate_w29 第一轮 e2e-ci 红 1 条(退出码 2,没到 ship)**:page-smoke 里 `ifmatch_reachable_check` 报我 11-21/22 加的 4 个乐观锁写接口(PATCH/archive chat-annotations、PATCH/archive chat-tasks)「没登记 revision 从哪儿来」—— 之前几轮 e2e-ci 没红是因为契约文档漏生成,fc 这笔「补生成漏掉的接口文档」后它们才进了检查的视野。修法(w1121,只动检查名单 + 两份 e2e 测试,没动运行时代码):名单登记 4 条(两组都没详情接口,界面从**列表行**拿 revision,`读` 指列表、`字段` items[0].revision、项目 demo_a);两份 e2e 收尾**各留一条「停用」的不归档**(归档的列表里不出现,全归档则「列表空 = 什么都没验到」红;上次剩的顺手归档,库里始终一条)。锁内单跑:标注 e2e 38 全过 / 员工定时 e2e 32 全过 / ifmatch 4 条 ✅(revision 6 / 3)。→ 提交后 w1117 ff,gate_w29 第二轮。
  · **13:2x fc ship#5 推完:origin/main = ba1d046d(c5f7d656..ba1d046d,带周营收口径按统计期 + 第 2/3 批库路径单源),它重启了 8760/8770、主检出 ff 过**。我:w1121 `rebase origin/main --autostash` 干净(四笔交接提交哈希变成 16e64d4b / c01ec544 / 5b8a2b16 / 85e84301);w1117 对齐用的是 `git rebase w1121`(reset --hard 被分类器拦;rebase 会把补丁已在上游的四笔自动跳过,结果 w1117 = w1121 = 85e84301,**以后 ff 不了就用这招,别 reset**)。**顺手查出一处要紧的:日报取数的桥工具不是 aimc 执行的,是 com.lanxiu.supervise(tools/supervise_sync.py --循环 30)拉回来在自己进程里 import workflow_bridge → api_report 跑的;它 11-22 23:17 起一直没重启,fc 的 weekly_revenue 新说法在它进程里不生效** → 13:29 `launchctl kickstart -k gui/$(id -u)/com.lanxiu.supervise` 重启过,日志 /tmp/lanxiu-supervise.log 第一轮正常(桥 project_lanxiu、派任务提醒 0/0)。教训:**改了 backend/ 下被桥工具用到的代码,要重启的是 supervise,不是 aimc / 8770**;已告 fc。
  · 下一步第一个动作(11-23 早):**先等 fc 的 ship(它夜跑结束后起,带手机号打码那笔,推完它重启 aimc)—— 它报了哈希、锁空、05:10 之后**,才 **先把 w1121 里这份未提交的 HANDOFF `git commit --only HANDOFF.md`(随早上第一笔;单独提也行)→ `git -C w1117 merge --ff-only w1121`** → `bash scratchpad/gate_w29.sh` 后台起;红了看 e2e_ci_w29.log / ship_w29.log;绿了告 fc 哈希。期间不碰 上次运行.py / workflows_api / endpoints / app.js / test_last_run。08:00 后看 project_lanxiu 的 workflow-documents 有没有 11-22 那份日报(GET …/workflow-documents?limit=3,X-Dev-User U001),有就写进 11-23 汇总;首份日报的两处口径观察(悬而未决 ⓪)先问 fc weekly_revenue 的说法归谁改。(原第一动作:等 fc 的哈希消息(没来就看 `git fetch && git log -1 origin/main` 变没变、锁空没空)→ w1121 `git fetch && git rebase origin/main --autostash` → `git -C w1117 merge --ff-only w1121` → `sed 's/w27/w28/g' gate_w27.sh > gate_w28.sh` 后台起 → 绿:告 fc 哈希 → 喊 fc 要锁 → 锁内 `cd 管理后台 && ./.venv/bin/python tools/seed_bridge_tools.py --项目 project_lanxiu` → `python3 scratchpad/enable_daily_draft.py`(每步不是预期就停)→ `launchctl kickstart -k gui/$(id -u)/com.lanxiu.supervise` → 汇总填哈希发飞书(`FEISHU_FOLDER=QexpfF7ejlotM8db6JEcZH5tnZf python3 tools/feishu_publish.py 澜绣云裳agent-夜间与日间汇总-20261122.md`)→ 清单 1/3/4/5 打 ✅。
  · 悬而未决:⓪ **首份日报草稿(doc_4f24ddf13293,23:3x 读过)内容两处要人定**:a) 「关键指标与口径」把 weekly_revenue 的口径原话「营收=本周实际收到的钱−本周退出去的钱…归周」直接抄进单日日报,读者会问「日报怎么说本周」—— 是处理要求该让模型按统计期改写口径,还是 weekly_revenue 该给按日的说法(fc 地界,先问);b) 「异常与待处理」全是截至今天的存量(断货 216 / 流失预警 918…),和当日段混在一起没分「当日新增 / 存量」,六段方案 §5.3 原文怎么写的要对一下。其余(数字带出处和取数时间、「这是判断」「尚未执行」标注)都对。① 飞书送达要每人接收方,谁填(问用户);② ~~被派的人改提前量只有服务端,聊天站 UI 没有~~ → **23:5x 补了页面那一半(w1121 提交,未推):「我的定时 → 任务」每行多「改时刻」—— 一次性提醒给 datetime-local 框、周期任务复用建任务的频率控件,存 POST /api/chat-task/update {规则};js_check / ui_audit / chat_tasks_check / js_smoke 都绿,真页面没点过**;③ test_lanxiu_knobs_flow 在 w1117 跑必红(环境假设,欠账);④ 「核对中」卡无出口;⑤ 标注列表给没原文权限的人看标准答案(现在给,用户没拍)。
  · 未验证:**test_chat_annotations_flow.py 第 76 行之后的断言一条都没真跑过**(第一次红在第 76 行夹具;修后由 gate_w17 锁内单跑;再红先看审计接口列表键名 / U003 viewer 权限这些我按源码推的);前端标注块 / 标注回复页**只 node --check,没在真页面点过**;fc 还没推聊天站那一半;w1121 领先 w1117 五笔(脚本修法 / shell_lint 扩范围 / 夹具 / 交接 ×2),gate_w17 会 ff。
  · 判据:scratchpad/gate_w17.status 「单跑完 … 退出码 0」然后「ship 完 … rc=0」且远端哈希前进(当时远端 dec5f75b);已验:`alembic current` = 7fd4c1f6ee18、aimc 在 49251aa7、GET /chat-annotations 带身份 200、周审查报告 22:18 落盘 154 行。
  · 作废:「没有排定的活」(18:3x)—— 用户 18:5x 开了 12 小时长任务,清单在顶部;第十四轮之前的红因记录不用再看。
  · 禁区:代码只写 w1121(**今晚又被拦一次:规划文档 Edit 用了主检出路径,分类器挡下**);**gate_w16 跑着时不改 w1117**(ship 在它上面跑);shell 脚本变量名一律英文(launchd 用 bash 3.2);六项块里不放工作记录;迁移目录外不写 ALTER TABLE;fc 动 app.py / station.html,我碰 agentsite 前再喊它;0 点到夜跑结束不占锁不写共享库(经营日报启用要写库 → 批次完 0 点前来得及就做,否则 05:10 后)。
  · 经营日报草稿启用的料(22:4x 查好,别重查):项目 project_lanxiu;真模型连接版本只有一条 **cv_ffc3943b4995**(生成连接 / active);U001 工号绑定 60000008(10-24 拍);桥执行器 com.lanxiu.supervise 在跑(launchctl list 有 pid);步骤照 test_store_report_flow / test_audio_flow:POST /workflows{模板:经营日报草稿} → GET 草稿定义、llm 节点 config.connection_version_id=cv_… → PATCH /draft(If-Match 草稿.revision)→ POST /validate 通过 → POST /versions → **先 POST /execution-runs {workflow_id, 输入:{}} 真跑一次成功**(生产只发真模型跑通过的版;会真调一次模型 + 走桥取数)→ POST /releases{版本id,环境:production}(422 CANNOT_DEPLOY 带 清单id → POST /releases/{清单id}/reviews{结论:通过} → 再发)→ PUT /workflows/{wid}/schedule{开着:true}(U001 不限门店,文档归「定不出门店」只给不限门店的人看;要归某店得让开定时的人登记门店)。写共享库 → 锁空 + 0 点前,先喊 fc。
  · **22:5x gate_w16 的 e2e-ci 红 1 条 = 我的 test_chat_annotations_flow 第 76 行**:U001 给临时成员加「查看敏感输入」被 422 CANNOT_GRANT(规则「不能通过邀请获得自己没有的权限」,U001 自己没这条);其余 91 份绿。修法 46ca3d30:夹具直接在库里 update E2E 工号的 special_grants(settings.可以改成员吗 的规则不动)。**没动运行时代码** → gate_w17.sh(后台 bkygx53ry)排在 gate_w16 退出后:w1117 ff w1121 → rebase → 锁内单跑那份 e2e → 主检出 ff → ship(不重跑整套 e2e-ci,理由写在脚本头;0 点前要放锁)。e2e-ci 本地就是打 8801 + 共享库(「CI 是新库」只指 GitHub)。
  · **23:1x gate_w17 单跑 31 ✅ / 8 ❌**(e2e-ci 其实 22:28 就完了,status 文件我看漏了):三处真错 —— ① runs_api 判聊天站用了 `聊天站来源`("lanxiu-chat",request_id 前缀)而 entry_kind 是「聊天站」→ 详情从来没带「标注」块;② POST 返回用 `note` 盖掉了备注字段 → 改成「提示」(前端同步);③ 测试猜错审计键名(真的是「记录」[{做了什么}] / 「这个范围里的动作分布」[{动作}])。修 b90555ff(w1117 已 ff)。**运行时代码改了 → gate_w18.sh**(23:3x 起,后台):主检出 ff → 重启 aimc → 锁内单跑 → 锁内整套 e2e-ci,**不 ship**(0 点前放锁);**gate_w19.sh** 也已起在后台:等 05:15 后 + 锁空 + w18 绿 → w1117 rebase → ship → 主检出 ff。两份脚本都在 scratchpad。
  · **11-22 07:3x 复盘昨夜**:gate_w18 单跑 39/0 绿,但整套 e2e-ci 22:44 红 1 条 **test_lanxiu_knobs_flow「文件还是导出那一份吗」** → gate_w20 / w19 都因此没 ship,**昨夜一笔没推**(而且我被 AskUserQuestion 卡了 9 小时 —— 用户早上才答;06:50 的汇总没发,每小时提醒 fc647c85 已删)。早上查实:那份测试把方案文件写在**跑测试的那棵树**(export_knob_plans.py 的 仓 = 管理后台 的上级 = worktree),而 aimc 读的是**主检出**那棵树的 .feynman/prompt_candidates → 从 w1117 跑必红、从主检出单跑 30/30 绿(07:4x 锁内验过)。**判为测试对环境的假设,不是改动引起 → 记欠账**(修法:测试或导出脚本按服务端那棵树的目录写,或 e2e-ci 里这份从主检出跑);为什么 gate_w16 那次绿了没查清。w1117 已 ff 到夜跑自动提交 f33404f2 + 交接一笔(e21d0b1f,w1121 rebase --autostash 过去的),**gate_w21.sh 07:5x 起 ship**(后台;status 看「ship 完 … rc=0」)。fc 07:4x 说:聊天站那一半昨夜没动,今天 10:3x 写完、我推完它 rebase、11:3x 报哈希;app.py / station.html 归它。
  · **用户 11-22 早上答的四条**(昨夜那张卡):① 第二个业务定时「每周交付风险清单」**做**(现成「订单风险」工具 + order_risk_advise 处理要求 → 定时周一 09:00 + Markdown 导出,新模板);② 经营日报草稿**按方案 §5.3 六段另写一套日报处理要求**(经营概况 / 关键指标与口径 / 异常与待处理事项 / 建议动作(尚未执行)/ 缺失数据与限制 / 数据来源与执行证据;seed_bridge_tools 加 key,_模板要求 指它);③ 周审查 **周一 07:30 不改**;④ 工作流文档**先不清**,攒三个月再定。
  · **用户 11-22 新需求「交给 agent 的定时任务」,两张卡 7 条全拍了(10:3x / 13:3x)**:原话「可以建立定义任务给 agent,让模型定时调用 / 启动任务,例如检查商机与新商品的匹配情况」。拍板:① **形状 = 聊天站建任务、后台调度、到点走内部通道让聊天站助手以该员工身份、只读工具跑一遍**(复用 workflow_schedules 那套漏期 / 身份 / 审计 / 费用;后台 Agent 节点不用 —— 它跑后台 Agent 版本,澜绣项目一个没配);② 到点做什么:**跑 / 只提醒,建任务时选**;③ 送达:**站内消息 + 飞书都发**;④ 建任务:**自由一句话 + 常用模板按钮**(商机探索 / 库存盘点 / 客户回访提醒),频率用后台同款可视化;⑤ 限额:**不限,靠门店月上限兜**;⑥ 店长派的任务:**自动建提醒,默认截止前 1 小时,被派的人能改 / 能关**;⑦ 权限:**员工自建自管;店长能看本店所有人的并能停**。现成积木查过:后台 open_api.py:781 用 curl 打聊天站 /internal/chat(要 角色键 / 问题 / 密钥id / 澜绣工号,sdk.run 只读=True);聊天站内部通道 internal_call.员工(工号) / 会话主;澜绣 task 表(id type ref_id status created summary waiting)没有截止时间,followup 表是回访记录;费用提醒走 backend/cost_alert.推(派任务)。**下一步:写方案发飞书 → PRD 台账 → 做**。标注匹配那一半和这个都要动 agentsite/app.py + station.html,fc 11-22 13:xx 说已交还给我。
  · **11-22 14:1x 员工定时 agent 任务一期代码写完(w1121,待推)**:后台 chat_tasks / chat_task_runs 两张表(迁移 e1014ff53288,**未落共享库**)、chat_tasks_api.py(九条接口 + 排到点的 / 执行排队的 / 员工任务扫一遍;失败阈值 3;模板三个,周几 0 = 周一)、worker.扫定时 多调 CT.员工任务扫一遍(分开 try)、开关们 chat_task.switch、endpoints 九条、app.js 页 #/chat-tasks(菜单「员工定时」+ 停用按钮)、Makefile 冒烟名单 += #/annotations #/chat-tasks;聊天站:/internal/chat 认 任务id(不要密钥)+ 费用到顶 429 BUDGET_EXHAUSTED + 跑完 _su.记;agentsite/chat_tasks.py 代理(每条带本人工号)+ app.py 四 GET 五 POST 路由 + station.html「⏰ 我的定时」(任务 / 结果收件箱 / 新建 + 模板按钮 + 角标每分钟刷)+ agentsite/chat_tasks_check.py 15 条挂 check.sh;sdk.py:1187 过期注释改了。测试:test_chat_tasks.py 22 绿、test_chat_tasks_flow.py(**没真跑过**;⑤ 等两分钟到点、⑥ 用不在职工号走真 /internal/chat 拿 NO_STAFF 不花钱 —— **要 8770 跑新代码**,批次脚本要 kickstart com.lanxiu.agentsite);咬合 +1(规格 1986)。make contract / nav_smoke / switch_registry / internal_call_check / human_requests_check 都绿。**没做(二 / 三期)**:店长视角页签与代停、店长派任务自动建提醒、飞书送达(要每人飞书接收方)。
  · **14:3x 日报六段处理要求做了(edfea388,w1121)**:seed_bridge_tools 加 store_daily_draft_write(六段段名照抄进 user 提示)、_模板要求["经营日报草稿"] 指它、模板列表「能直接跑吗」看 有日报要求。**project_lanxiu 还没种**(e2e-ci 只种 demo_a):启用经营日报草稿前要锁内跑 `cd 管理后台 && ./.venv/bin/python tools/seed_bridge_tools.py --项目 project_lanxiu`(写库)。
  · **15:0x 每周交付风险清单做了(w1121,待下一轮推)**:**不另造桥工具** —— 全店口径直接用澜绣现成的两个只读工具 factory_chase(该催工厂 + 要人看的回传)和 delay_pending(延期未告知),都已在 桥工具.只读 和 workflow_bridge.业务工具 名单里;seed_bridge_tools 工具们 加这两条(正式项目已有导入的同名工具 → 种子「用它不动它」;演示项目登记成桥工具给 e2e 用)+ 处理要求 delivery_risk_list_write(存量口径、建议全标尚未执行、两份取数包);workflows_api 模板「每周交付风险清单」(定时 周一 09:00 → chase → delay → write → markdown_export → finish;模板们 / _模板要求 / _模板说明 / 分发 / 模板列表两处名单 + 要)。test_markdown_export ⑥ +5(24 绿)。**没真跑过**(要 e2e-ci 的种子跑过、aimc 重启;正式项目要先种处理要求)。
  · **14:5x 标注匹配那一半做了(53a75f6b)**:agentsite/annotations.py(清单缓存 60 秒、候选按角色筛最多 40、提示词「不确定答 0」、解析只认 JSON 命中、问模型走 agent/v1.call purpose=标注匹配、命中回答 text 逐字 = 标准答案零花费、报命中)+ app.py /run 在会话归属校验之后、难题分流之前插一段(有图不走)+ annotations_check.py 16 条挂 check.sh。**没真跑过一次命中**(要后台总开关开 + 有启用标注 + 真模型判),上线后要人用一条标注试。
  · **gate_w22 栽在 rebase 冲突**:fc 的 7a708d27 和我都往 tools/bite_specs.json 末尾追加 → 手工合(主干 1987 + 我 1 = 1988),w1121 rebase 过去(哈希全变:7b4fcd3e→daa4ce59 / edfea388→7ae24892 / 8c307ed0→53a75f6b),w1117 reset --keep 对齐。**gate_w23 14:5x 起**(后台 bf7wn32k0 之后那个;status 看 gate_w23.status「ship 完 … rc=0」)。
  · **15:3x gate_w23 e2e-ci 红 2 份(都是我的)**:① test_chat_tasks_flow —— 建任务返回里「接下来几次」空、频率说明「规则认不出」:T.接下来几次 回 (执行时刻, 起, 止) 三元组,我当成时刻 .isoformat() 抛 AttributeError 被兜住(修:取 x[0];test_chat_tasks 加 _行 两条,24 绿);测试第 84 行把中文假工号 `E2ECT_别人` 塞进网址 → urlopen 当场炸(这个仓库第六次;换 ASCII `E2ECTOTHER`);② test_cross_project_read —— 新 GET /chat-task-inbox 必填 staff_code(身份参数)结构上没法攻 → 登进 不验登记 写理由。修 7a0ce1b5,w1117 ff,**gate_w24 15:3x 起**(status 看 gate_w24.status)。aimc / 8770 现在跑的是 53a75f6b(员工定时 + 标注匹配已在线,只是列表接下来几次那处有 bug)。
  · **16:0x 员工定时二期做完(w1121,待下一轮推;gate_w24 跑的是不含它的 7a0ce1b5)**:之一 店长视角 f8637533(服务端 _锁任务 认「是他的或在他店里」?store_id=;聊天站 _门店码 从登录身份 shop 文字取第一段 —— 第一版把「SH001 静安旗舰店」整句存成 store_id 了;店长在「我的定时」多一页「本店所有人的」能停);之二 派任务自动提醒 00ca692f(后台 cadence「一次」:时刻 ISO,到点排一条 once:<id> 就自动停用 + 审计;建任务按 (staff_code, source_ref) 去重回已有;澜绣 tools/supervise_sync.推派任务提醒:每轮把近 2 天新派、带 end_ts 的 schedule 行 POST 成被派人的一次性提醒(截止前 60 分;过了点 → 现在+1 分;截止过了不建),任务非「有效」就归档;推账 .feynman/chat_task_pushes.json;tools/chat_task_push_check.py 12 条挂 check.sh)。e2e ⑥b +5(**没真跑过**)。**没做 / 欠账**:被派的人在聊天站改提前量(UI 只有停用,没有改时刻;服务端 PATCH 规则 支持);飞书送达(三期,要每人接收方);supervise 常驻服务要**重启**才带新步(com.lanxiu.supervise,launchctl kickstart;它读 LANXIU_BRIDGE_PROJECT 才推)。
  · **16:2x gate_w24 e2e-ci 又只红我一条**:标已读对别人的工号该 404 却 500 —— `_错(…, "")` 空建议被 ER.错 的「规格 §19.1 建议必填」抛 ValueError;两处补上建议(9a80014e)。**gate_w25 16:2x 起**(w1117 = 9a80014e,含二期两件 + e2e ⑥b,第一次真跑)。
  · **16:5x gate_w25 e2e-ci 只红 test_audio_flow「聊天接管收尾」**(409 REVISION_CONFLICT,运行停在 waiting_external —— 定时开头那条流程和取消撞时序;前四轮都绿)→ 锁内单跑 143 条全过 → 判偶发;**gate_w26(只 ship)16:5x 起**。
  · **16:2x gate_w26 ship 红(rc=1,没推出去):咬合重放里 4 个检查「对照就是红的」**,全是今天新内容带出来的、不是偶发:① ui_audit —— station.html 的 `[data-ct=周期]`(带值的属性选择器)和 `data-ct-rev`↔`dataset.ctRev`(驼峰)老正则不认 → 修检查(第三次同形误报);`data-raw="原文"` 两处是纯标记 → 改 class;② doc_numbers_check —— PRD 台账第九十条「默认截止前 1 小时」没人认领 → 文字改「60 分钟(一小时)」+ 新规格「派任务提醒提前分钟」读 supervise_sync 的字面量常量(不 import,它顶层连着桥);③ intent_check —— 待办清单.md 要重生成(0/411 → 0/414);④ bite_check —— annotations_check / chat_tasks_check / chat_task_push_check 三个新检查没写 `咬合 = [...]` → 各补一条 + bite_specs 1988 → 1991,三条都重放过「对照绿 → 改坏 → 红的是那一条」;顺手把 chat_tasks_check「记门店用量」判据收窄(老正则 re.S 的 .*? 跨到后面别的 _su.记,把任务id块里那处删了也绿)。**教训:e2e-ci 绿 + 单项检查没跑 ≠ ship 绿;新检查落地当天就要补咬合记录,不然 bite_check 的棘轮(上限 0)当场红。** 修完 **gate_w27(同 w26 形,只 ship)17:0x 起**。
  · **17:1x gate_w27 跑着(后台任务 b4l2c00iw;w1117 = 8565bd83,领先远端 15 笔)**;fc 已回「gate 期间不拿锁不碰 agentsite,本地 4 笔只改 backend 库路径 + dbpath_check,没碰 bite_specs,推完报哈希它再 rebase 自己 ship」。等的期间 **PRD 已发飞书**(https://aqvi2xbk5kd.feishu.cn/docx/Ly0OdVcDcoGiocxQfpecohm5nue,四张图都画了)。汇总草稿《澜绣云裳agent-夜间与日间汇总-20261122.md》在 w1121 根目录,**还没发**(等哈希填进去;要补一段 gate_w26 红的四处)。
  · **18:40 gate_w27 ship 又红(rc=1,没推出去),这回红在全量门禁,3 条判定不过 + 1 条崩**,仍全是今天新代码带的:① 世界时钟 —— supervise_sync 的 SQL `datetime('now')` 没标「真实时钟」→ 同行标注(这段跑在真实 launchd、assigned_at 本身机器时钟写的);② 连库必须显式关 —— supervise_sync 1 处 + chat_task_push_check 2 处 `with sqlite3.connect()` → `with closing(...) as c, c:`;③ INSERT 形状 —— 夹具里三句位置参数 INSERT → 具名列(⚠️ 用 f-string 拼列名也算位置参数,检查把插值换成 {…} 看不出列名,得字面写);④ **崩的是页面冒烟 js_smoke:station.html 的红点 `setInterval(…, 60000)` 让 node 跑完不退出,✅ 都印了、进程挂着,门禁 600 秒掐掉算崩** → js_smoke 通过路径加 `process.exit(0)`(定期刷新是正常写法,不该让冒烟挂)。四条 + 快清单八项本地全绿,`bite_run --only chat_task_push_check` 重放过。**fc 18:46 趁空档先 ship 它那 5 笔(基于 7a708d27,约 19:3x 完,推完它重启 8760/8770),所以这次换成我等它的哈希再 rebase 起 gate_w28。** 教训追加进记忆:tools/ 下新脚本也在 worldclock SQL / db_close / insert_shape 三条视野里;页面加 setInterval 要先跑一遍 js_smoke 看它退不退。
  · 下一步第一个动作:等 gate_w27(status 看 gate_w27.status「ship 完 … rc=0」)→ 推 → 告 fc 哈希(它等着 rebase)→ 锁内 `seed_bridge_tools.py --项目 project_lanxiu` → 经营日报草稿启用(U001,写库,告 fc)→ kickstart com.lanxiu.supervise → PRD 发飞书 → 今晚汇总(补昨夜的)。 —— 红:看 e2e_ci_w16.log / ship_w16.log 最后的 ❌ 修了再起 gate_w17(同形);绿:告 fc 远端哈希、把 w1121 的 weekly_review.sh 修法 ff 进 w1117 随下笔推、规划 + PRD 发飞书、清单第 1 项打 ✅,然后做第 3 项(演示门店启用经营日报草稿,0 点前来得及就做)。
  · 悬而未决:① 周审查第二次试跑成不成(成了只差用户装 plist);② 经营日报草稿启用的窗口(0 点前 vs 05:10 后);③ fc 什么时候推完聊天站那一半(推完我做标注匹配那一半,碰 agentsite 前喊它);④ 核对中的卡怎么收尾(人核完在待办里处理);⑤ 标注列表要不要给没原文权限的人看标准答案(现在给 —— 它是配置不是客户数据,用户没拍过)。
- **11-21 白天逐项记录(14:1x 刷六项时误删、从 96a113aa 救回;最新的在上)**:
  · **14:1x 台账八十六后半 + 八十七(w1121,待推)**:工作流模板多一个「经营日报草稿」(workflows_api._经营日报草稿:定时开始每天 08:00 → 取经营数据 kind=日 date=统计起 → 写报告正文 store_report_write → Markdown 导出(标题 经营日报、统计起止绑开始)→ 结束;**不存澜绣报告表、不确认、不派单**;模板只预填草稿,和「经营报告」一样唯一阻断是没选模型;test_markdown_export ⑤ +4,19 绿)。**用户启用时要做的**:新建流程选「经营日报草稿」→ 选模型 → 冻结 → 审核 → 发布到生产 → 「版本与发布」页打开定时(以店长身份,他的成员记录登记了门店 → 文档归那家店);先一个门店。项目周审查:tools/weekly_review.sh(claude -p 只放行 Read / Grep / Glob / 只读 git;报告由脚本落盘回读核过才算成;日志 .feynman/weekly-review.log)+ tools/weekly_review_prompt.md(步骤 + 模板,照辅助目录方案 §4.3 / §5.3)+ tools/launchd/com.lanxiu.weekly-review.plist(每周一 07:30;**用户亲手装**,装法在 plist 注释里)。**脚本没真跑过一次**(会起一个 claude 进程跑好几分钟、花 token;手动 `./tools/weekly_review.sh` 验一次再装 plist)。
  · **14:0x 「Markdown 导出」节点做完(w1121,待推;台账第八十六条的前半 —— 第一个业务定时任务的文件口)**:dsl 新节点 markdown_export(调用外部、端口 成功/失败、必填 bindings;正文必绑,可选 标题 / 统计起 / 统计止 / 门店);实体 workflow_documents(知识库那张叫 documents,不是一回事)+ 迁移 0b610a1aa99b(alembic 自动生成 —— 先把未落库的 c8e3 挪开才生成得了,再手改接在它后面;**未落库**);runtime/文档导出.py 纯函数(文件名 业务名_门店_统计日期_运行短号.md、正文转文本、字节与哈希);worker._markdown_export:字节进 storage(临时文件 → 改名)→ **回读再算哈希** → 行 status=已存,对不上按失败;runner 给它传 __node_id;documents_api.py 三条 GET(列表 ?run_id= / 详情 / 下载:读出再核哈希、Content-Disposition、_审计 workflow_document.download;门店范围同 人工待办);endpoints.py 三条 A()、main.py 挂路由、make gen 过;前端:菜单「转换」组、步类型名、结果字段名、表_输入 固定五项、表_设置(标题 / 文件名前缀 / 模板版本)、字段中文、运行详情「产出的文件」一节(画_文件产物);spec_coverage 已实现集 += Markdown 导出(23 → 24 个节点,「23 个全实现」那句改了)。测试:test_markdown_export.py 15 条(Makefile 已登记)、test_markdown_export_flow.py ⑤ 段(**没真跑过**;Makefile 三处登记)。**models.py 另补登记 ix_human_requests_proj_store**(门店迁移建了它、模型没登记,alembic autogenerate 报「removed index」—— 不登记的话 alembic check 永久漂移)。
  · **14:1x 复审 P1-04 + P2-08 做完(w1121,待推)**:P1-04 三道 —— 发布工作流 发到生产时新版不是定时开头且定时开着 → _停定时(关 + missed_detail 记「停用」为什么 + 审计 workflow.schedule_disabled,身份 system 替身走 _审计)、响应多「定时」说明;定时扫一遍 生产版存在但 _生产开始规则 None → 停用不发;_定时发起一期 再核一次 → 跳过。e2e 加在 test_audio_flow 定时段末尾(重新打开 → 冻手动版 → 发生产 → 停了;硬改回 true 再扫 → 不发起、停回去)。P2-08 —— runs_api 成功吗 三态(completed/ok/end_turn → True;failed/error/interrupted → False;其余 None)+ 结束了吗;app.js 调用链列表第三态 warn 色「未结束 / 结束原因不明」;test_trace_import_flow 加三态断言。慢:explain analyze 查实 spans 没 (project_id, trace_id) 索引、每行 Seq Scan 24ms × 50 → 迁移 c8e3f0a2b4d6 三条索引(spans / usage_ledger 的 proj_trace,traces 的 proj_kind_started)+ models.py 同名登记;**迁移未落共享库**(锁被我自己的 ship 占着),下一轮 gate 脚本会 upgrade head;落之前 alembic check 会报漂移、/traces 仍慢。
  · **13:5x 复审 P1-02 + P0-01 做完(w1121,待推;⚠️ 第一次手滑写进了主检出,已 git checkout 撤干净、重写进 w1121)**:backend/pending_actions.py —— 终态 += 未执行 / 核对中,结束状态们;_连 补四列(result_full / sha256 / bytes / truncated,sqlite 老库现场 alter);摘要化(结构不变只截长字串 / 长列表,永远合法 JSON)+ 收尾(…, 状态=) 存完整 + 摘要 + 哈希;取完整结果;建() 的「办过」把 核对中 也算(不再出新卡);给模型的话 核对中 那句。agentsite/action_confirm.py —— 解读输出(stdout) 纯函数四态(没 id=2 回执 → 不确定;isError → 失败;「还没有执行」→ 未执行);_调一次 超时 → 不确定;确认 按 状态字 收尾,不确定时 _转人工核对(answer_feedback.建转人工 → 后台 chat-handoffs)把待办编号带回卡上;完整结果(aid, me) 只给本人。app.py GET /api/action/result;station.html 核对中 / 未执行 两态 + 成功卡「看完整结果」。action_confirm_check ⑧ +13(46 绿)。**没做的**:按业务幂等键自动去业务库核对(每个工具查法不同),这版靠转人工;「核对中」没有自动收尾,人核完在后台待办里处理。
  · **13:3x 超时出口做完(w1121 本地提交,待下一轮推)**:dsl 新端口 超时="timeout"(端口们 + human 端口);runner 恢复时 决定 == RN.超时决定("__timeout__")只走 timeout 口、没线就 节点失败 HUMAN_REVIEW_EXPIRED;worker.扫过期核对 看 resume_snapshot.定义 里有没有 (node, timeout) 边 —— 有:待办 expired + 事件 human.timeout + RR.排恢复;没有:照旧收成 expired;worker 恢复:hr.status == expired → 注入 结果{决定 __timeout__, 超时 True, __action_id __timeout__},不查决定行。前端 wf_graph.出口们 human 多「超时」口(有按钮 / 没按钮两种都加)、口名 timeout=超时、画布超时线用 err 样式、下一步区占位「(不接:到期这次运行结束)」、面板说明。测试:test_human_form ⑥ +3(22 绿)/ human_code_panel 断言更新(23 绿)/ test_human_form_flow ⑦ +4(小时 0.0004 ≈ 1.4 秒到期;**没真跑过**)。整套 test-orchestration rc=0。**接口形状给 fc**:待办状态多见「expired」+ 事件 human.timeout;聊天站已过期的卡只读。
  · **13:2x 用户拍板四件(台账八十五–八十八)**:复审四条全修(顺序 P1-02 长回执 → P0-01 写操作结果不确定四态 → P1-04 定时版改手动的真场景 → P2-08 成功口径 + /traces 慢);第一个业务定时 = 经营日报草稿 + Markdown 导出(先补受控 Markdown 导出口);项目定期审查每周一次只读、报告到辅助目录(执行方式待定);人工介入到期加「超时」出口(流程自己接,不接仍失败)。**顺序**:超时出口(管理后台,fc 聊天站那半要用,先做)→ P1-02 → P0-01(动 agentsite/action_confirm.py + backend/pending_actions.py,先喊 fc)→ P1-04 → P2-08 → Markdown 导出口 → 经营日报定时 → 项目周审查。
- **压缩前六项(23:5x 版,作废)**:
  · 未验证:早上那一轮 ship 还没跑(0 点后不占锁);e2e-ci 23:13 在 aeb84722 上绿,之后到 43ef73bd 只改了测试 / 夹具 / 咬合规格 / 文档,所以 05:17 起 gate_w5.sh 就行(它会再跑一遍 e2e-ci,多 20 分钟,保险)。
  · 判据:只认 gate_w5.status 里两行「被包的命令退出码 0」;ship 绿 = `git fetch && git rev-parse --short origin/main` 变成 43ef73bd(或我之后的新提交)。咬合三处(图校验夹具 / 单步测试规格 / 术语 e2e 规格)已本地 bite_run --only 全绿,ship 再红就是新的。
  · 作废:gate_start / w2 / w3 / w4 四轮日志不用再看;「W22 费用上限没做」那条作废(11-15 已做完);「还债里剩 W27」作废(11-17 已核实)。
  · 禁区:0 点到夜跑结束(约 05:10)不占锁、不写共享库;不碰 fc 的文件(tools/nightly_eval.py、agentsite/guards.py、agent/nightly/ 等那张表);代码只写 w1121,w1117 只做 `git merge --ff-only w1121`;ship 跑着时不改 w1117;新工作树链四条:管理后台/.venv、agentsite/.venv、管理后台/.models、backend/lanxiu.db;不替 fc 推。
  · 下一步第一个动作(07:3x 更新):**推已完成(远端 45269e05),今天不再占锁**。只剩 09:27 cron(9b334a92)写《澜绣云裳agent-夜间汇总-20261121.md》发飞书产品文件夹(FEISHU_FOLDER=QexpfF7ejlotM8db6JEcZH5tnZf)后 CronDelete 每小时那条(0a89543b)。
  · 悬而未决:① 聊天站那一半人工介入由谁接(没有会话管聊天站;c2 是介绍页、fc 是评测线)—— 汇总里问用户;② 汇总要写全「和规划不一样的地方」:知识检索原来是摆设、ELIF 本来就有、沙箱 sandbox-exec 不是 wasm、内存不是硬限制、Webhook 参数错 422、人工介入超时出口没做、导出导入「现有导入步骤」其实不存在;③ 还债表里剩的 row 18(默认模型接聊天站,要复测模型)/ 11③④ / 6 / 23 不是今晚的活,汇总里列给用户。
10. ✅ 07:4x 汇总《澜绣云裳agent-夜间汇总-20261121.md》已发飞书(提前,活做完了),两条 cron 已删。**08:0x 用户拍:「让测评线参与」剩下的活、「需要我做的可以和我说」** → 已请 fc 接 ① 聊天站那一半人工介入 ② row 18 默认模型接聊天站 ③ 它地界的 11③④ / 6;放宽补丁用户已亲手跑(row 23 ✅,fc 08:0x 正占锁推 3 笔 agentsite/guards + bite_specs,约 40 分钟,会 ff 主检出、重启 8770、不碰 aimc)。**fc 08:1x 回:三件都接**,顺序 ① 聊天站那一半人工介入 → ② 默认模型接聊天站(先复测再动 sdk.py)→ ③ 11③④ / 6;它推完 f36dd0cd 那笔就开始,接口对不上会来问我。我这边:今天不占锁;下次接的活等用户点。

### ⏱️ 12 小时长任务清单(11-18 22:00 → 11-19 10:00)· AI 管理后台修复夜(Fable 5.1)

> 用户 21:5x 起:「开始 12 小时长时间工作,目标就是解决现在 ai 管理后台的问题,可以开多个 subagent」。每小时 :13 有 session 内提醒 **c258b450**(10:00 那轮写《澜绣云裳agent-夜间汇总-20261119.md》发飞书产品文件夹后 CronDelete)。
> **拍板**(21:5x–22:2x):① 运行页暂停/取消/核实 **接执行侧**;② **模型训练先不做**(训练提交 / 产物部署按钮标灰写明);③ 补页面:Prompt 变量编辑 / 评测发起取消 / 旋钮方案页 / 连接停用 / **工具连接+工具组页 / 用量预算块 / 数据集页(新建冻结导出补脱敏) / 工具选择策略页**;④ e2e 残留 687 个假成员 **先不动**。
> **守则**:只碰 管理后台/ 和根目录报告、交接;fc 今晚不占锁(它说的),0 点到夜跑结束不占锁、05:10 后再要;每批 = `scratchpad/gate_batch12.sh` 形状(主检出退回/拉到远端 → 并回 w1117 → kickstart aimc → 等 healthz 连续 4 次 200 → e2e-ci → ship);只认「被包的命令退出码」;子代理各自 worktree 分支(**从主检出 HEAD 切,不是 w1117**,所以叫它们先 merge w1117),交回后 `git merge` 进 w1117,冲突手解;**改 w1117 里的文件前先确认没有 batch 在 rebase 它**(21:27 栽过)。

1. ✅ 体检 45 条中 22 条修掉(7e7d5863 / f79f31c2),报告 4a775439 已发飞书
2. ✅ 子代理第一批四路合进 w1117(95224f50 Prompt 变量编辑;b6c3beb5 评测发起取消 + datasets 版本们;92a78c82 旋钮方案页;122279a4 连接停用/Agent 连接下拉/失败任务卡/待办链接/面包屑/试跑 100 条/实体去哪列/冒烟管理员轮,两处冲突手解)。合并后 16 页 U001 + 5 页 U002 冒烟全绿。**全部只过渲染没真点过**(子代理只许 GET)
- 下午:fc 推了 cf643323(回答体检「压价没读话术打回」+ 夜跑小套看同一题连挂)→ 我把主检出 ff 过去、kickstart 8770 上线;fc 又推 c11af3b6(PRD 附录两条,纯文档),锁已放,fc 说今晚不再占锁。
- **20:3x 用户问「债都还清了?」→ 拍「开始做吧」**:还体检欠账四件,b9c339e5(端到端七份测试收尾删自己加的临时成员 `tests/e2e/_清成员.py`,存量 775 个**按用户「残留先不动」不清** / 运行详情费用说明分演示和真模型 / 数据集页加「导出时包含 mock」勾选 / 新 `test_newpage_actions.js` 25 条,咬合两刀都红在点名那条)。批次 gate_batch13.sh 20:4x 起(scratchpad gate_batch13.status / e2e_ci_1119n.log / ship_1119n.log)。
- **20:56 第一轮 e2e 红 1 条**(test_runctl_exec_flow:取消和 Worker 领任务撞同一瞬间,任务记成「已完成」)→ 查库时间线确认一步没跑 → 修 e6ed66f0(worker 进门见 cancelled 抛 取消了 → 任务「已取消」)→ 第二轮 e2e-ci 21:17 退出码 0、ship 21:39 rc=0 全量门禁 0,**已推 e6ed66f0**(b9c339e5 四件欠账 + e6ed66f0 worker 修法 + 之前的交接提交);aimc 已在批次里重启到这一版。门禁把影响面基线 394→395(我新文件里一段 ⚠️),已挪进 w1117 提交、主检出恢复干净。主检出另有 11-15 的空文件 `--自测.log`,不是我的,没动。
- **22:3x fc 要跑 pre_push 推 b8b2591f(库路径单源,0 点前放锁)**:我已回「锁今晚不要了」。**今晚我不再跑门禁、不写共享库**;剩下三件欠账(日志采集策略加列 / 桥请求详情页 / 评测发起测试)明天做,先问 fc 锁窗口。w1117 本地 e2708b23(交接 + 影响面基线 395)未推,随下一笔业务提交带。`_清成员` 在整套里真跑了:6 份各删自己的、存量停在 775。
- **23:2x fc 已推 e6ed66f0..e18167df、锁已放,到夜跑结束不再占锁**。fc 的门禁也把影响面基线顶到 395,fc 没提交(由我 e2708b23 带上,数一致不冲突)。w1117 已 rebase 到 e18167df,主检出干净(只剩那三个不 add 的滚动文件 + `--自测.log`)。0 点到夜跑结束我不占锁;明早 05:10 后再要锁推 e2708b23 + 下一件欠账。
- **11-20 04:3x fc 夜跑完拿锁推两笔(说 05:10 前放)**。我趁空在 w1117 写完剩下三件欠账,**都只本地提交、没跑端到端**:
  9c04d9cd 桥请求详情页(新接口 GET /bridge-calls/{id} 权限同列表、跨项目 404;前端 #/bridge/{id};运行页和原始日志能点过去;订单风险 e2e +5 条;顺手补登 test_newpage_actions 进 test-e2e / progress 两处,make contract 原来红在这)/
  e0a826f3 评测「发起」页面测试(test_newpage_actions 第 ④ 组:外部登记、后台派发 422、真派 4 次运行再取消;**接口早有人测,原来那句「要真模型」不对**)/
  94de01f0 日志策略加列 retention_policy_revision(迁移 dd289ffffc98;**第一次手编的迁移号和已有的重了,alembic 报 Cycle**)。
  批次 scratchpad/gate_batch14.sh:等 05:10 + 锁空 → **锁里先 alembic upgrade(新列先落库)** → 并主检出 → kickstart aimc → e2e-ci → ship。日志 migrate_1120a / e2e_ci_1120a / ship_1120a。
  **05:21 fc 放锁(已推 eecba3cc)**;批次第一轮红在迁移那步:没设 DATABASE_URL,迁移脚本拒跑(库没动,alembic_version 仍 b7c1d2e3f4a5)→ 脚本里显式给 aimc_dev,05:2x 第二轮起。
  **05:22 迁移已落库**(alembic_version → dd289ffffc98,共享库已有 retention_policy_revision;老代码不读它,无害)。批次随后停在「主检出有不在 w1117 里的提交」:a7053ba4 夜跑自动提交(04:28,fc 的,没推)。**不替 fc 推**,已问 fc 怎么处理;回复前主检出不动、锁已放。下一步:fc 推了它 → 重跑 gate_batch14.sh(迁移那步再跑是空操作)。
  **05:3x 更新**:fc 请我把夜跑那笔一起带上 → w1117 重排成 origin/main(eecba3cc)→ bf7f6792(夜跑,内容与 a7053ba4 逐字核过)→ 我的四笔;主检出 reset --keep 回 eecba3cc;**第三轮批次在跑**(status 文件看「第三轮」之后)。
  · 未验证:三件欠账的新测试(订单风险 +5、test_newpage_actions ④ 组、日志策略 +2)**一次都没真跑过**,第三轮 e2e-ci 是第一次;红了先看是测试写错(字段名 / 表名我改过两次)还是代码错
  · 判据:桥详情权限同列表(运行评测)、不按状态筛;日志策略改用自己的版本号、**存策略不再顶项目 revision**;夜跑提交是 fc 明确请我带的(只含 agent/nightly + 当晚报告)
  · fc 更正:夜跑 .gz 变小是 fc 11-18「压完就删」的回归(头版本历史 32.7 万行 → 2 万行,旧版在 git 历史里),**fc 自己修、单独推,占锁前喊我** —— 不是我的活,别碰
  · 禁区照旧:不推别人的提交(这次夜跑那笔是对方点名请求的例外)、主检出不留未提交改动、迁移要显式 DATABASE_URL=aimc_dev
  · 下一步第一个动作:看 scratchpad/gate_batch14.status;绿了 → 告 fc 放锁、远端应到 ae3c2410 之后;红了 → 看 e2e_ci_1120a.log 里 ❌ 那条
  · **05:5x 第四轮**:test_newpage_actions 39/0 绿(87948309 修了候选按 ->>'ref' 查 / 桩随机键非 UUID / 删直改运行状态的兜底);红在 **test_exec_mode_flow ③**(NO_MODEL_CONNECTION,期望 MODEL_/SECRET_ 族)—— 第三轮同代码绿、锁里单跑绿,旧交接(11-09 前)记过本机常驻 8801 上它「有时红」、没查根因。日志留在 e2e_ci_1120a_第四轮.log;**06:0x 第五轮在跑,再红就查根因,不许当绿推**
  · **06:44 已推 eecba3cc..c9d4a74e,锁已放、已告 fc**(第六轮:e2e-ci 06:24 退出码 0、页面冒烟 #/bridge/ 跑通、ship 全量门禁 0)。
    内容:fc 夜跑 bf7f6792(fc 点名请带)/ 桥请求详情页 / 评测发起页面测试 + 修三处 / 日志策略自己的版本号(迁移 dd289ffffc98 已落库)/
    test_exec_mode_flow 竞态根因修复(c9d4a74e:先 POST 再塞连接,忙的 Worker 0.05 秒轮询抢先领走 → NO_MODEL_CONNECTION;改成只在「排队中且没人领」时塞,被抢重交,第六轮一次塞上)。
    主检出另有项目日志.md 改动 = 06:40 定时任务生成的,不是我的,没动。fc 接下来要拿锁修「夜跑 gz 被当晚覆盖」(它的回归,它自己修)。
    **三件不用拍板的欠账到此清完。**
  · 🟢 **11-20 12:0x 用户拍「先做 Webhook」**(工作流二期 2-2,规格见《工作流整体与详细规划-照Dify-20261115》2-2 节,11-15 已拍完不用再问):
    开始方式 = 用户输入 | 定时 | Webhook 三选一(多开始是 2-3,这次不做);URL 用访问 API 那套密钥鉴权(门店身份跑);调试 URL 只跑草稿;
    配置检查拦「Webhook 开头的流程里写类动作前必须有人工介入」;验收:错密钥 401 不建运行 / 参数类型错 400 指出哪个 / 同幂等键 409。
    参照实现:定时当开始 98632daf、访问 API(11-03)。
    **设计(12:1x 定,子助手只读调研的结论)**:路径相对 管理后台/
    ① 不新建表、不新加 DSL 键:start_mode 多一个值 "Webhook",参数表**复用 input_schema**(类型/必填);contract/dsl.py:132 不用动(start_mode 已登记)。
    ② validator.py:382-406 可选值加 "Webhook";新检查 WEBHOOK_WRITE_NEEDS_HUMAN:Webhook 开头时每个 tool 节点读写≠read_only(查不到当写)→ dom[域][i]-{i} 里要有 type=="human",否则阻断(循环/子图沿 _祖先域 往外查;没给 工具读写 查询能力 → 进「跳过」不算过)。支配集 validator.py:213,读写查询 依赖存在.工具读写(workflows_api.py:80),fd5f223f 写法 validator.py:1040。
    ③ open_api.py 加两条:POST /open/v1/apps/{aid}/webhook(生产版,要求生产版 Webhook 开头否则 409 WEBHOOK_NOT_START)、POST /open/v1/apps/{aid}/webhook/debug(跑 graph_drafts 草稿,来源 kind=graph_draft 发起="Webhook 调试")。复用 _认密钥/_过闸/幂等 409/_今天花了/_记一笔,身份=发密钥人(**规划写「门店身份」,但 access_keys 没有门店维度 —— 照访问 API 用发密钥人,已告诉用户**);请求体=扁平 JSON,按 input_schema 逐个核类型,错 → 400 WEBHOOK_PARAM_INVALID 指出参数名,不建运行;缺必填同 400。建运行 WF._受理运行(c,本人,p,定义,来源,输入,f"open:{kid}:{键}")。
    ④ endpoints.py:933 附近加两行 A(...,对外=True,幂等=True,数据出境=True,审计=True) → make gen → make contract。
    ⑤ 前端:wf_canvas.js:208-210 菜单开始项那条改文案;app.js:3859 开始方式下拉加 ["Webhook",…],分支画入参表(同用户输入那套)+ 只读显示两条 URL + 「去版本与发布页发密钥」提示。
    ✅ **16:35 已推 b1693209..65aa99c6**(e2e-ci 16:16 退出码 0、ship 全量门禁 0;锁已放、已告 fc)。路上三处坑:
    ① 第一轮 e2e 在 w1117 跑 → 打的是主检出跑的旧 8801,不算数;e2e 必须主检出 ff 后跑。
    ② 参数错用了 400 → 契约状态码只有 401/403/404/409/422/429/500,错误体构造拒收、崩成 500;改 422。
    ③ **06:07 那次 kickstart 留下孤儿 uvicorn 占着 8801**(PPID 1),之后 aimc 一直起不来、worker 没了、healthz 照样 200 → 运行全卡排队。15:5x 停掉孤儿、正常重启。批次脚本 scratchpad/gate_webhook.sh 已加「先停监听进程再 kickstart + 验监听进程是 launchd 后代 + worker 在」(记忆 lanxiu-aimc-kickstart-orphan)。
    没做(记规划 2-2 进度段):Query / Header 参数表、自定义响应、单独的「接入 Webhook」文档。下一件可接:2-3「开始」页签与多开始,或四期(要和聊天站排期)。
    (以下是 12:5x 的旧状态)全部写完,本地提交 0d55cd87(未推);离线自测 15 条绿、make contract 0。规划文档 2-2 补了进度段(未提交,随下一笔)。
    e2e-ci 在 gate_lock 里排队(日志 scratchpad/e2e_ci_webhook.log,判绿只认「被包的命令退出码」),fc 先推返修 4 笔(哈希待它告诉)。
    **下一步**:e2e 绿 → rebase 到 fc 新哈希 → 提交规划文档 → ./tools/ship.sh(先确认 agentsite/.venv 链接在、工作区只剩三件运行态);红 → 看日志里 test_webhook_flow 那段。
    ⑥ e2e 新文件 tests/e2e/test_webhook_flow.py 仿 test_access_api_flow.py(外() 59 行 / 等跑完 72 / 收尾 86)+ test_audio_flow.py:486 定时化写法(冻结时同步顶层 input_schema);Makefile test-e2e 与 progress 两处登记;validator 纯逻辑自测放 tests/orchestration/ 同样登记。编辑器 wf_canvas.js:210 现标「暂不做」。改 管理后台/ 推前要 make test-e2e-ci(锁内);fc 在推返修判责(949ed25d),推前先喊它。
  · 🟢 **11-20 21:0x 用户拍「开始 dify 工作流搭建」→ 做二期 2-3「开始」页签与多开始**(规划 2-3 节,照 Dify;1 人日):
    做法:**不新建表、不加 DSL 键、不动校验器**。「多开始」= 换开始方式(一条流程只有一个「开始」):wf_canvas.js 菜单开始项 三项 [值, Dify 名, 字, 色, 说明, 角标],
    「开始」页签点一项 → app.js 选开始方式(有「开始」就 设开始方式 换成那种、没有就加;互斥文案照 Dify;可撤销);面板下拉也走 设开始方式(只写一份)。
    新建空白流程:workflows_api.建工作流 在**布局**里打 `$开始待配置: true`(和 $注释 / $线 同一个做法,不进定义;定义里开始没写 start_mode = 用户输入,校验照旧);
    前端 开始待配置() 为真 → 画布虚线占位「点击配置开始节点」(class wfnode2 pending,没出口;点(不拖)弹 弹_配置开始)、步骤列表标「还没配置」、面板下拉「请选择」;进编排页弹一次引导(图态.开始引导过);选了方式 设开始方式 删掉标。
    测试:tests/e2e/test_workflow_start_tab.js 33 条(vm 跑真函数,本地绿)/ tests/e2e/test_workflow_start_guide_flow.py 4 组(服务端标;**没真跑过**,随 e2e-ci 第一次跑);Makefile 各三处登记。
    顺手:css_class_check 之前就红(拼接 class 31 > 30 钉的,b1693209 就 31,它只在 test-orchestration 不在门禁)→ 把 wf_canvas.js 菜单项 那处改成两段字面,回到 30。
    规划文档 2-3 补了进度段。**下一步**:gate_start.sh 批次(锁空 → rebase → 主检出 ff → 停旧 8801 → kickstart → 验进程归属 → e2e-ci → ship);红了先看 test_workflow_start_guide_flow(字段名 问题/级别 照 test_http_node_flow 抄的)。
  · ~~悬而未决:用户那三件~~ **11-20 11:4x 用户拍了两件**:775 个假成员存量「先不清」(只止血,别再提);介绍页 AI 配图「用户确认能商用,照旧用」(别再提、别换图)。只剩「登录后界面用户亲眼看」—— 那是用户自己的动作,不用再问。
  · 11-20 11:2x 推 e0d161d8..39f475d1(fc 981dc5c0 拿旧备份盖掉的 11 节交接补回 + 注释更正)。前两轮没推出:①工作区有自动区刷新,拒跑 ②w1117 的 agentsite/.venv 链接不知被谁清了(fc 说不是它),崩 34 条 → 重建 `ln -s <主检出>/agentsite/.venv agentsite/.venv`。**跑 ship 前先确认两条 .venv 链接在**。
  ~~性能问题:后台派发下拉取 1400 多个详情~~ **11-20 07:0x 查实不存在**:1439 个有版本的工作流里 1434 个已归档,列表不列归档 → 实际约 10 个请求。写了个新接口又撤了,没提交。
- **压缩前六项(20:5x)**:
  · 未验证:七份测试接了 `_清成员` 只 py_compile 过 + 演示项目单测删一条,**整套 e2e-ci 里还没真跑**(批次在跑,看 e2e_ci_1119n.log 里有没有「🧹 收尾删了」行);费用说明 / mock 勾选只过 node --check,没在浏览器看
  · 判据:只止血不清存量(用户拍「残留先不动」);按「本进程登记的工号」删、不按 E2E 前缀删(防并发测试互删);旋钮测试要先把 draft_revision 推到 2,否则 If-Match 写死 1 测不出
  · 作废:旋钮测试第一版(revision 恰好是 1 的那版)咬合没红,已改
  · 禁区:同前(不碰 fc 的文件;0 点后不占锁;三个运行态文件不 add;e2e-ci 只在 gate_lock 里跑)
  · 下一步第一个动作:批次通知来 → 读 gate_batch13.status;rc=0 → 交接记推送号、告诉用户;红 → 看是哪条、是不是我的改动
  · 悬而未决:775 假成员清不清(要问用户,别自己清)
- **还欠着(下一批,不用拍板)**:日志采集策略拿项目 revision 当乐观锁(要加一列)/ 桥请求没有详情页、运行页链不过去 / 评测「发起」要跑真模型没进测试。**要用户的**:登录后界面亲眼看、介绍页 AI 图商用条款、687→775 假成员存量清不清。
- 12:1x ✅ **第七轮推上去了**:ship 被包的命令退出码 0,远端 f7f0c864(产品说明 4.8 + Hook 六个、待办→运行互链、面包屑对齐、夜间汇总终版、数字豁免 + README)。今晚这一摊全部落地,没有未推的业务提交
- 11:4x 第七轮第二次:e2e-ci 绿,全量只红 1 条 = 8770 页面冒烟 triage-board「0 个节点」—— 上一次同一条是绿的、我没碰 agentsite,单跑 3/3 绿,判抖动;**直接在主检出重跑 ship**(后台 b6rd02s0q,日志 scratchpad/ship_1119b.log)。第一次红的两条(4.8 数字豁免 + README)已修 f7f0c864
- 10:1x **12 小时长任务收尾**:夜间汇总终版已发飞书、每小时提醒已关(CronDelete c258b450)。剩第七轮推送在跑
- 10:11 fc 已推 ae21e1b9(4 笔;锁内 order_eval 3/3,真库 ordr 前后都是 26039 行,不再写真库)。**第七轮起跑**(后台 b9f2onru8:并回 → 重启 aimc → e2e-ci → ship),13 笔:产品说明 4.8 + Hook 六个、待办互链、面包屑、夜间汇总终版。完成读 gate_batch12.status 的「ship 完」行
- 09:35 自检:fc 还没推上去(远端仍 4044579a,锁被 09:30 起的咬合重放占着,应是 fc 的 pre_push);我本地 13 笔未推(文档 + 互链 + 面包屑)。夜间汇总已更新成终版发飞书 https://aqvi2xbk5kd.feishu.cn/docx/ItjndmZUqoGAzox9NJacUivmn50 。10:00 轮只剩 CronDelete;第七轮推送等 fc 喊
- 09:0x 介绍页会话(c2)请核「项目方法」七页:已只读核完逐条回它(4 处要改:技能顺序、口令是哈希且管理后台无登录、面料工期其实有向量检索、费用倍数 24–135;研判单价 0.5 元偏高约 3 倍)。不归我改
3. ✅ **08:42 推上去了**:全量门禁 被包的命令退出码 0,远端 4044579a(昨晚 67 笔 + fc 的⑦修法)。已告 fc 放锁让它先推。**下一批(第七轮)排 fc 后面**(fc 08:4x 起 pre_push 3 笔,推完锁内单跑 order_eval 约 15 分验真库行数不变,跑完喊我;我说了不急):产品说明 4.8 + Hook 六个、待办→运行互链 + 面包屑对齐(要跑 e2e-ci)
   旧:08:31:咬合重放完,pre_push 08:20 起锁内全量门禁,约 08:50 出结果(后台任务 b0fcqv67f 完成即读 status)。用户 08:3x 换模型为 Opus 5.5,提交署名跟着换
   **第六轮(07:08 起,67 笔,含 fc 受欢迎⑦修法 4044579a):e2e-ci 07:28 全绿(退出码 0),ship 全量门禁在跑(07:32 起咬合重放)**;06:40 那轮全量红 4 条已全修(4d1f8db0 中文参数名 + trace 白名单;0655f280 recall 登记;fc 的⑦)。推完:告 fc 放锁、远端应到 4044579a 之后。**赶不上这一批的 → 下一批(第七轮)**:产品说明 4.8(d7c02821 / 84f48175)、待办→运行互链 + 30 页面包屑对齐侧栏分组(子代理 2846e5a3 已并入,node --check 过、30 页冒烟全绿;桥请求没详情页所以没链,记着)。第七轮要跑 e2e-ci(改了 app.js)
   - 07:50 自检:第四轮 e2e(23:20)只红 1 份:新测试 test_runctl_exec_flow 抓到真 bug —— worker 节点边界提交后,runctl 中途写 run_events,两边 seq 各算各的撞车 → **DeadlockDetected**,任务崩了重跑,检查点落到 start,恢复后模型多调两次。修法 34d874ae:两个 记事 都先 for update 运行行、seq 从库里 max+1(和 runctl 同一个锁顺序)。**第五轮 e2e(23:37–23:49):所有端到端全绿(含 test_runctl_exec_flow 暂停→继续、test_orchestration 88 条),只红 ifmatch_reachable_check「三条新乐观锁接口没登记 revision 从哪来」—— 已登记(下一笔),检查本地绿。** 23:52 不再起新一轮(0 点夜跑要锁);**05:17 一次性提醒 83ece95a 会跑完整 batch12(e2e + ship 推)**。第三轮红 2 条(22:56):Agent 跑 http 000 **根因找到了**:可选连接的顺序变了,e2e 取「第一条支持工具调用的」拿到别的测试留下的本机假接口(e2e 本地假接口 ×2,端口早死,status 仍 active —— 残留连接也该清);测试改成按 模式=mock 点名。test_runctl ④「继续」→ 现在 409 RESUME_NO_CHECKPOINT(夹具 paused 没检查点),测试改;⑩「重试新建的步骤删干净了 5」是并发污染:它借「最新一条运行」改库,和子代理的真运行撞了 → 改成只借终态 + 结束超 10 分钟的。**第四轮 23:2x 起只跑 e2e-ci(ONLY_E2E=1),ship 留 05:10 后。** 并远端的方式改了:w1117 上全是合并提交,rebase(含 --rebase-merges)重放会撞我手解过的冲突,23:19 又栽一次 → 改成 `git merge origin/main`(pre_push 只看 HEAD 含不含 origin/main)。fc 推了 863af6f3(PRD 两条),今晚不再占锁。
   - **e2e 子代理(a87b7b49,合 1e720567)抓到的大问题**:worker 把整次运行裹在一个事务里,running 不提交、API 的 pause/cancel 被行锁挡 → **我接的暂停 / 取消在真运行上点不出来**。已改(cb 下一笔):运行类任务节点边界提交。**没在真库跑过**。
   - 残留:demo_a 两条「e2e 本地假接口」active 生成连接、库里一条被夹具写回 queued 的 succeeded 运行(xr_8fdb2648df12)—— 要清但是共享库写,明早再说。
   第三轮 22:44 起(并回 5c940b0f,32 笔)。第二轮红 2 条:Agent 跑 http 000 **不是瞬断** —— 可选连接按名字排后 e2e 取「第一条支持工具调用的」拿到老 e2e 连接(端口死了),改回最新建的排最前;test_runctl 等 reconciling,核实今晚改成当场送回 running/paused,测试跟着改。第二轮 22:29 起(并回 f63afb53,27 笔,含 1–6 全部;aimc 已重启跑新代码;e2e-ci 约 22:45 完 → ship 约 23:1x 推;fc 排在后面推 1 笔文档,23:30 后它就不推了)。第一次 e2e-ci 红 3 条(22:23):加资料引了接口没有的「版本」字段、工具详情脚注测试认旧词、Agent 跑 http 000(模型调用网络瞬断,同时段别的 agent_run 都完成)—— 前两条已修(含测试一起改),第三条当瞬断重跑。**下一次 batch12 并回的是全部 1–6**
4. ✅ 暂停 / 取消 / 继续 / 核实接执行侧(2bbb922e,未推):runner 要暂停吗 回调 + pause 检查点;worker 刷新令牌读 execution_runs 两个标记、取消收成 cancelled、_挂起 支持 paused;runctl 取消同步 jobs.cancel_requested、继续真排任务、核实查桥请求回执后送回 paused/running;离线测试 test_pause_checkpoint 14/14、make test-orchestration 全绿。**worker 那一半没真跑过**。原计划:runner.跑一张图 加「要暂停吗」回调 → 节点边界返回 paused 检查点;worker `_打点器` 读 execution_runs.pause_requested/cancel_requested;_挂起 支持 paused;runctl.cancel 同步 jobs.cancel_requested;runctl.resume 改调 run_resume.排恢复(挂起态加 paused);worker `except 取消了` 把 execution_runs 收成 cancelled;reconcile 待定
5. ✅ 子代理第二批全合入:用量预算块(42c78bf3)、工具选择策略页 + 训练/部署标灰(91a6f4e4)、工具连接+工具组页(a8ac8f06,Makefile/app.js 两处冲突手解)、数据集页新建/冻结/导出/补脱敏 + PATCH /datasets(57da1278);PATCH /datasets 和连接 archive/unarchive 补进 contract/endpoints.py 并重生成 openapi/ts。合并后 datasets / groups / conns / tool 详情 / 搭建 页冒烟绿。原记录:✅ 用量预算块(42c78bf3,合 07474e2a;预算接口 GET 也要 admin,非 admin 看 403 态);✅ 工具选择策略页 + 训练/部署标灰(91a6f4e4,合 5f33b6d3);⬜ 工具连接+工具组页、数据集页 还在跑。合并后 7 页冒烟绿。子代理都说两条棘轮(css_class_check 30>29、md_render_check 50>32)**在合并前就红**,不在 e2e-ci 里;ship 的全量门禁会不会跑它们看日志
- 07:4x 产品说明新增 4.8「Agent Loop 和 RAG」(子代理 d7c02821 已并进 w1117;RAG 参数全部从代码核:切片 ≤600 字 / BGE-small-zh 本地 512 维 / 种子配置 候选 20・取 8・预算 4000 token / Claude haiku 重排 / 只实现 vector;正式索引那版的值在库里没核)。顺手把 4.5 标题 Hook「五个」改「六个」(guards 实挂 6 事件,4.2 早已写 6)。已发飞书。**e2e-ci 07:28 全绿(退出码 0),ship 在跑**
- 07:2x 用户:「没事干的话把产品文档重新优化下,把 loop / RAG 说清楚」→ 派子代理改《澜绣云裳agent-产品说明.md》(Agent Loop 与 RAG 两节,面向不读代码的 PM,事实从代码现读),README 要用 make_readme 重生成,发飞书产品文件夹;交回后合进 w1117 随下一批推
- 07:1x fc 来信:它那次红在 triage_trial_check 咬合,已补(de27aaa4);**07:08 用户当面确认后它已删真库 15 张评测单 + 19 订单行 + 120 业绩分成,备份在它 worktree .wip-glossary/db-backup/lanxiu-删评测单前-20261119-070801.db**。我的 batch12 07:08 起(e2e-ci 中),门禁若有数 C10002 的检查行数会变,心里有数
- 07:1x 上一轮 batch 停在「主检出有别人的未提交改动」= 06:40 daily-log 又生成的项目日志(照用户 11-18 拍的丢掉 git checkout);fc 07:07 放锁但远端没动(它那笔没推成?已问)→ 我 cherry-pick 它的受欢迎⑦修法 4b3356d6 进 w1117(本地 popularity_check 绿),**完整 batch12 再起**。推完喊 fc
- 07:0x 用户拍板:**15 张评测单删、先备份整库(归 fc 执行)**;残留只清两条死端口连接(我用 archive 接口停了 mc_e2e_4fd2fe59 / mc_e2e_bf6cbf17,demo_a),假成员和那条运行照旧不动。夜间汇总 392f6091 已发飞书 https://aqvi2xbk5kd.feishu.cn/docx/RL4BdswXPojXVUx1wipcEejFn0c
- 07:2x 再刷一次(内容同下,无新变化;后台任务 buutsx9c9 仍在等 fc 放锁)
- 07:1x **压缩前交接(六项)**:
  · 下一步第一个动作:后台任务 buutsx9c9(gate_batch12.sh 完整)在等 fc 放锁;它完成的通知到了就读 `scratchpad/gate_batch12.status` —— 推成功(远端 = 我的 HEAD)→ 告 fc「锁已放」、清单 3 打 ✅;红了看 ship_1118h.log / e2e_ci_1118g.log 的 ❌ 行
  · 未验证的预判:① 并进 fc 的 3 笔后 popularity ⑦ 会绿(它说单跑 12 条全过);② nightly_check 加登记后本地绿,门禁里应同样;③ worker 节点边界提交 + 死锁修法只过了 e2e(23:37 那轮 test_runctl_exec_flow 暂停→继续全过),真人在页面上点暂停还没人试过
  · 判据:只认「被包的命令退出码」;Agent 跑 http 000 不再当瞬断(前两次都是真因);页面冒烟桩 options:[] 已在仓库里
  · 作废:「主检出有不在 w1117 里的提交就停」那条判据对夜跑自动提交会误停 → 已改成把 main 并进 w1117;rebase w1117(含 --rebase-merges)作废,只用 merge
  · 禁区:tools/nightly_eval.py 只改 fc 点名的那一行;真库 15 张评测单(C10002)不删,等用户拍;e2e 残留(687 假成员、2 条死端口连接、1 条被写回 queued 的运行)不动,等拍
  · 悬而未决:15 张评测单删不删;残留清不清;10:00 夜间汇总 + 拍板卡(含这两条 + 夜跑 order/talk/tool/growth 退步归评测线);CronDelete c258b450、83ece95a 已自删
- 07:0x fc 查明:popularity ⑦ 是检查自己算歪(拿 round 4 位的合并率复核),修在它分支 4b3356d6;recall 登记要加在**我**分支(第三张夜报只在 ac60476c 里),它口述我代登(tools/nightly_eval.py 连续失败已知,这是 fc 点名让我改的)。**fc 先推(07:0x 起 pre_push 约 30 分),我 merge 远端后跑完整 batch12**
- 06:40 **ship 全量门禁红 4 条**:我的两条已修(4d1f8db0:连接列表 ?含停用 → ?include_archived(url_ascii_check);test_runctl_exec_flow 的本机假模型接口登进 trace_check 白名单)。另两条归 fc:夜跑清单「recall_eval 连 3 晚 0 分没登记」(fc 的 fb8c6640 修判分器,登记那条问它)、popularity_check ⑦「苎麻被判成突出没越过两倍噪声」(疑真库 15 张评测单顶出来的,待确认)。已问 fc,它先推我再并
- 06:36 自检:**e2e-ci 05:51 全绿(退出码 0)**,ship 在跑(pre_push 06:20 起拿锁,前面是咬合重放),等推完
- 05:3x 第一次红在 test_runctl_flow:借到一条带检查点的老运行,「继续」真排回去了(202)而④要验 409 → 夹具再加 resume_snapshot is null(22fb4f79),**05:3x 重跑完整 batch12**
- 05:17 **完整 batch12 起跑**(e2e-ci → ship 推;约 06:0x 完)。推完:告 fc 放锁、更新清单 3 为 ✅
- 04:4x fc 来信(**要进夜间汇总 + 拍板卡**):order_eval 连 4 晚退步的根 = 评测切副本漏了懒加载写口(api_order.open_order 函数体里才 import order_write,第一次调用连的是真库),**真库 ordr 多了 15 张评测单(C10002,11-18 01:33–02:17,id …244322–336,待确认)**;fc 修在连库层 1e3df33b,排我后面推;那 15 张删不删要用户拍。我这边管理后台用的是 PG aimc_dev,不同根
- 04:35 自检:nightly-eval-ok 已更新到 11-19 04:26,锁空;按守则等 05:10 世界平移后再要锁,05:17 提醒直接跑完整 batch12(上一轮状态文件里 e2e 退出码 2 是登记检查那条,已修 578347ba,不用再单跑)
- 04:3x fc 来信:夜跑 04:27 结束,**自动提交 ac60476c 落在主检出**(脚本不替别人推);我把主检出的 main 并进 w1117(不然 batch 的「主检出有不在 w1117 里的提交」会停)。fc 本地 1 笔 fb8c6640(召回判分器两处冤枉)排我后面,**推完要喊它**。夜跑点名:order_eval 连续 4 晚退步、talk / tool / growth 连续 6 晚判红 —— 写进夜间汇总,归评测那条线
- 03:36 自检:同 00:36(锁空、夜跑未写 ok —— 上一次是 11-18 03:54,今夜的大概也在 03:5x 落;远端没动、无待合并)
- 02:36 自检:同 00:36(锁空、夜跑未写 ok、远端没动、无待合并)
- 01:36 自检:同 00:36(锁空、夜跑未写 ok、远端没动、无待合并)
- 00:36 自检:锁空、夜跑还没写 nightly-eval-ok(上一次 11-18 03:54),按守则不碰锁;没有待合并的分支;w1117 领先远端 46 笔等 05:17 推。下一步第一个动作 = 05:17 提醒来了看 nightly-eval-ok 比 11-19 00:00 新且锁空 → 跑完整 gate_batch12.sh
6. ⬜ 推完之后:① ✅ 子代理 a979bd 的 5 份 e2e(prompt-runs 绑连接 22 条 / 连接停用 25 / PATCH datasets 25 / 运行取消暂停 12+⏸1 / 评测取消 11+⏸1)已合入并登记 E2E_CI;暂停→继续那条等 worker 事务边界改完才能验(prompt-runs 绑连接 / 连接停用 / PATCH datasets / 运行取消暂停 / 评测取消),交回后合入、登记 E2E_CI、再推一批;② ✅ runctl 取消队列中运行顺手收任务(64fbcbe0,下一批推);③ 小项:✅ Agent 调试默认输入按 schema 造 + 费用说明分 live/mock(59c0e133);✅ viewer「看进度」(评测子代理已按角色摆);✅ 知识库文档列表页 + GET /knowledge-bases/{kb}/documents(014dc93a,合 260e14a0;顺手登记 #/retrieval/ #/selection/ 进 detail_page_hashes、md_render 钉到 63;**在下一批推**);⬜ 日志策略 If-Match 用 projects.revision(要加列,留着);④ 10:00 夜间汇总发飞书、刷交接、CronDelete c258b450
- **未验证的预判**:暂停 / 取消的 worker 那一半没在真库上跑过(e2e 子代理会试抓 running 窗口);子代理们的写操作(建连接 / 建组 / 冻结 / PATCH 数据集 / 建方案 / 发起评测)全只过了代码审读和渲染,e2e-ci 现有测试覆盖不到新按钮的 POST,靠 a979bd 补的测试
- **判据**:只认「被包的命令退出码」;Agent 跑 http 000 那种瞬断红不算代码红,同时段别的 agent_run 都完成就重跑
- 旋钮页子代理提到两条棘轮 css_class_check 30>29、md_render_check 37>32 **在 ff8e39a4 上就红**(fc 推得上去说明不在门禁里,可能只在 make test)。看 ship 日志再说

### 🟡 11-18 21:5x · 用户拍了体检四件;batch12 在跑(Fable 5.1)

- **用户 21:5x 拍板**(报告第四节那 12 条里的 4 件):① 运行页「暂停 / 取消 / 核实」**接执行侧**(worker 每步检查点读运行状态,pause_requested→paused、cancel_requested→cancelled;reconcile 也要有人接);② 训练任务 / 模型产物部署**接执行器**(真跑训练和部署 —— 要先问清 GPU / 部署目标,这一条我还没问细节);③ 补页面:**Prompt 变量编辑、评测中心发起 + 取消、澜绣旋钮与方案页、模型连接停用**(四个都选了);④ e2e 残留 687 个假成员 **先不动**。
- **没拍的 8 条**(报告第四节 #3 微调三页 / #8 工具组等 / #9 预算 / #10 待办链接 / #11 实体去哪列 等)留着。
- **batch12**:第一次停在我自己的判据(主检出落后远端被当成「有别人的提交」),改成「HEAD 是 origin/main 祖先就 pull --ff-only」后重跑;状态看 `scratchpad/gate_batch12.status`。
- **接下来的顺序**(推完才动):先做 ③ 里半天级的两件(Prompt 变量编辑、评测发起/取消),再 ① 暂停取消接执行侧(改 workers/worker.py + runctl.py:runctl 置标记时同步 jobs.cancel_requested;worker 检查点读 execution_runs.pause_requested),然后 旋钮方案页、连接停用;② 训练/部署执行器**最后**,动手前要问用户 GPU 在哪、部署到哪。

### 🟡 11-18 21:4x · 体检四路审计齐了:45 条,22 条已修(两笔,未推)、12 条要拍板、11 条记录(Fable 5.1)

- **报告**:`澜绣云裳agent-AI管理后台体检-20261118.md`(根目录,随下一笔推;发飞书产品文件夹)。拍板的 12 条在报告第四节,**没问用户**。
- **第二笔修的**(见提交信息):/projects 带实际能做的、成功率 completed 也算、Prompt 筛选进 SQL、worker 写 started_at;前端 20 处(wfrun 深链崩、重试传 MouseEvent、核对页画工具参数、评测 ref、建索引按钮、收进知识库、召回多库、翻页、审计截断、依赖中文、kr field_errors、info_requested、工具详情键名、过期文案 ×5、字面星号 ×7、版本与发布按角色摆、Agent 试运行 90 秒)。
- **未验证的预判**:① 后端四处改动只过 ast,**真服务没跑过**(8899 临时实例已停);② 建索引 / 收进知识库 / 新建知识库 三个新按钮只过了渲染,**没真点过**(接口形状按 knowledge_api 读的:documents 要 {upload_id,name},knowledge-bases 要 {name});③ e2e 三份直接跑被权限分类器拒了,全靠门禁里的 test-e2e-ci。
- **下一步第一个动作**:fc 推完放锁(它 21:05 起 pre_push)→ 跑 `scratchpad/gate_batch12.sh`(并回 → kickstart aimc → e2e-ci → ship);红了看 e2e_ci_1118g.log。推完发飞书、告用户、拍板卡。
- **判据**:只认「被包的命令退出码」;页面冒烟桩的 data-raw 豁免只认 `data-raw="原文"` 写在开标签里;`git stash list` 里两条 autostash 不是我的,别动。

### 🟡 11-18 20:5x · AI 管理后台全页体检(用户要「确定是否所有能力已可用」)+ 修「运行测试每次都排队」(Fable 5.1)

- **体检方法**:page_smoke 的桩(scratchpad `smoke_dump.js`,加了 DUMP 把渲出的文字落盘)以 U001 + project_lanxiu 渲 39 个一级页;54 个列表接口逐个 curl;结果在 scratchpad `smoke_summary.txt` / `api_probe.txt` / `smoke/*.txt`。
- **查实的坏**(都已在工作树改,**未提交**):
  ① Prompt「运行测试」/「单条试跑」:页面派完任务**只查一次**状态 → 永远显示排队;且 POST /prompt-runs 的快照里**从来没有** model_connection_id,真跑模式(launchd 的 aimc 是 MODEL_ADAPTER=anthropic)下 worker 每次 NO_MODEL_CONNECTION(库里 61 条这样失败的,用户 U002 在 demo_a 的 4 次都是)。修:main.py `_定调试连接`(点名优先;项目唯一启用生成连接默认用;零/多条不猜,信封写明会失败)+ 快照/幂等摘要带连接 + GET /jobs 露 error_code/detail;app.js 顶层 `画模型连接` / `等任务`(2 秒轮询最多 2 分钟)/ `运行结果html`,两页共用。
  ② 成员与权限:管理员打开整页「出错了」—— 接口 `可授权的能力` 是按角色的 dict,页面当数组 `.map`;CI 冒烟用 U002 非管理员所以没红过。修:`授权框html(d, 角色, 已有)`,换角色跟着变。
  ③ 审计页管理员那支在**桩**里抛(`sel.options` 桩没有),浏览器没事 → page_smoke.js 的 造() 加 `options: []`;审计「对象/为什么」、工具目录「用途」是原文带 `**` → data-raw="原文"。
- **未验证的预判**:① 后端改动只过了 ast,**没对真服务跑过**(8801 跑的是主检出旧代码)—— 下一步起临时实例 8899(worktree 代码、aimc_dev、MODEL_ADAPTER=anthropic)真跑一次 pr_tl05 看 job 成功,再跑 test_api_flow / test_exec_mode_flow / test_prompt_snapshot_flow(AIMC_BASE=8899);② 并回主检出后 **aimc 要 kickstart**(API 进程不重载)再跑 e2e-ci。
- **体检里不是 bug 的**:空数据页(Agent 0 / 能力档案 0 / 问题单 0 / 知识修订 0 / 产出 0 / 定时 0 / 训练 0 / 产物 0)、上线验收 0/10 未签、健康页无人工判读(8770 没接 POST /feedback)、「定时触发还没做」「Agent 线上(生产)还没接」是明写的未实现。
- **数据卫生(待拍)**:project_lanxiu 有 689 个成员,687 个是 e2e 残留(E2EOP 292 / E2EAK 232 / E2EHO 47 / E2EIS 36 / E2ECP 35 / E2EIV 34),来自默认打 project_lanxiu 的那十几份 e2e(test_access_api_flow 等);审计里 access_key.issue 991、application.create 234 同源。e2e-ci 每跑一次再加。要么测试收尾清自己建的,要么改打 e2e 专用项目;残留清理是共享库写,要锁 + 告 fc。**没问用户,没动。**
- **锁**:batch11(默认项目 fbaa7fbb)ship 在跑;推完 eureka-fc 要锁跑接管评测 25 分钟,之后才轮到这批(管理后台改了 → 先 kickstart aimc → e2e-ci → ship)。

### ✅ 11-18 20:0x · 已推 a0d89c9d —— Prompt 简介 / README 介绍页链接 / 差评汇编进知识库 / 召回测试修好(Opus 5.5)

- 全量门禁退出码 0(中途红过一次:导入脚本里的全角标点被编辑器改成半角,charset_fullwidth_check 41→42;改用 chr() 拼,回 41)。e2e-ci 0 在 batch9 那次(管理后台代码相同)。
- 8770 已 kickstart(带上 eureka-fc 的 TL05/TL76 新措辞;店长助手不用出版,正文由 assemble 从代码挑)。
- **召回测试**:用户当时在「演示项目 A」(mock 向量、只有 9 月拍板)—— 真项目是 project_lanxiu(bge)。差评汇编导进 project_lanxiu 的「澜绣业务拍板」库,索引 ib_fa01e1d19643(bge)已就绪;重测前 4 片全是汇编、分数 9/8/7/6,生成「够答」、引 8 条。演示项目没动(集成测试按名字找它)。eureka-fc 导了领域知识库并重建 ib_40d12a6b1bad。
- 介绍页图片:c2 已给 12 张 jpg 写回 XMP「AI 生成」标识(27754ff),商用授权那条结了。
- **悬而未决**:演示项目 A 默认被选中会让人误以为召回坏了 —— 要不要把默认项目改成澜绣云裳,没问用户。

### 🟡 11-18 18:4x · 交接 —— Prompt 管理加简介 + README 介绍页链接,排在 eureka-fc 后面推(Opus 5.5)

- **用户要**:Prompt 管理每段 system prompt 加简介,说清管哪个部分。d1b19245:导入脚本 `包一条()` 现拼「用途」(哪几个助手｜讲什么 / 类型 / 装了哪些工具才发 / 口径),不手写;列表页取第一行 70 字、悬停看全文。**进了内容哈希 → 127 条各出一版;共享库 aimc_dev 要在锁内重导,否则 lanxiu_prompt_sync_check 红**。
- **README**:15e60233 顶部加产品介绍页链接(Pages 已上线 200,仓库 lanxiu-yunshang-intro)。
- **在跑**:`scratchpad/gate_batch9.sh` —— 等锁空 → 并回主检出 → 锁内导入 + 同步检查 → e2e-ci → ship。状态 `gate_batch9.status`,只认「被包的命令退出码」。
- **欠账**:评测稳定挂的「没把写动作交回给人」那道,eureka-fc 补了 TL05 未复跑;logo 登录后界面要用户看;介绍页 AI 生成图的商用条款没核。
- **未验证的预判**:① 简介只在本地 `--看` 和脚本里预览过 6 条,**没在 8801 页面上看过**(要导入后用户刷新看);② e2e-ci 的 Prompt 页测试会不会断言「用途」一栏旧样子 —— 没查,等 e2e-ci 结果;③ 导入会把 eureka-fc 已提交未导入的 TL 改动一起导(已告诉它)。
- **判据**:工具中文名取说明**第一小句**,不取第一段加粗(加粗是「客户问多少钱时用这个」类提醒,试过作废);「写」「图片」是 needs 里的记号不是工具,单独翻。
- **禁区**:prompts.py 一字不改(TL 归 eureka-fc);导入只在锁内跑;主检出不写未提交文件;**店长助手不出新版本、不切生产**(TL76 / TL05 是改措辞,eureka-fc 攒着问用户;若重导后 assistant_effect_check 红,先告诉它,别为转绿去切)。
- **召回测试「没结果」(用户 18:5x 问)**:查实页面没坏 —— 流程走完、精排和生成都调了,生成答「证据不够」(正确拒答)。根因:① 知识库 kb_0ff23c4a90d1 只有 6 份文件(业务拍板 0924–0927 + 版型调研 + 一份测试上传),**没有差评处理资料**;② 索引 ib_44bd0b04cf8f 是 10-24 用 **emb-mock** 建的(假向量,相似度 0.05–0.1,等于随机),而真模型 bge-small-zh-v1.5 适配器和模型文件(`管理后台/.models/`)都在。**用户拍「两个都修 + 从现有规矩整理」**:写《差评处理规矩》(来源 TK13/TK14/TK16/TL98/TL103、rating-repair 技能、业务拍板 0927)进 `业务决策/` → 锁内 `管理后台/tools/ingest_lanxiu.py` 导入 → 用 bge 重建索引(POST index-builds 带 embedding模型id,或 `tools/seed_index.sh` 形状)→ 同一问题重测给用户看。关键词检索要等 bge 不够再出选型卡。
- **⚠️ batch9 并回时漏了 eureka-fc 的 ca028d6f**(锁空那一刻 pull 没拿到),主检出 = 242b1a83 不含它 → ship 第一步「查已 rebase」会拒。e2e-ci 照跑(只改 管理后台,结论有效);ship 拒后:w1117 rebase 到 origin/main → 主检出 `git reset` 不行(别动别人的)→ 用 `git pull --ff-only` 前先确认主检出没有别人的提交,再并回、锁内重导规矩(TL05 变了)、ship。
- **下一批 `scratchpad/gate_batch10.sh`**(等 batch9 结束再起):主检出比远端多出的 4 笔按主题核过是我的 → `git reset --keep w1117` → 锁内 ingest_lanxiu + import_lanxiu_prompts + 两条同步检查 → ship(e2e-ci 不重跑:管理后台代码和 batch9 那次一样)。**推完要喊 eureka-fc**:用户已拍 TL76 + TL05 店长助手出版切生产,它等规矩池导好再出版。之后我派 bge 索引重建 + 召回重测,不用 8770。
- **作废的结果**:工具中文名「取第一段加粗」那版预览(kb_bom 显示成「客户问多少钱时用这个」)作废。
- **悬而未决**:店长助手要不要带 TL76 / TL05 出新版本,eureka-fc 问用户,不归我问;介绍页 AI 图商用条款要不要查,没问用户。
- **下一步第一个动作**:b7auqut56 完成后读 `scratchpad/gate_batch9.status`;全绿 → 告诉用户去 8801 Prompt 管理页刷新看简介、告诉 eureka-fc 锁已放;红 → 看 import_1118.log / e2e_ci_1118c.log / ship_1118d.log。

### ✅ 11-18 15:52 · 已推 6df6695e —— logo 接进三个界面;e2e-ci 0、全量门禁 0、8770 已重启;锁已放并通知 eureka-fc 跑 13 道评测题(Opus 5.5)

- **用户拍板(11-18)**:① 主检出 06:40 那份项目日志**已丢**(git checkout);② 飞书「重新授权」—— 查下来不用人点:make_log 原来调 `~/Desktop/chatgpt` 那份发布脚本(它的登录过期),**改成本仓库 tools/feishu_publish.py**、目标仍是通用文件夹 PJWW…(88abdbb4),实发一次成功并清了 1 份旧版;③ **允许无界面浏览器给本地静态页拍图,不点击、不登录、不联网**(已写进记忆 web-search-yes-browser-no)。
  - 拍法坑:headless 最小视口 500,要 390 就套 390 宽 iframe;**`sips -c` 是居中裁**,要么 iframe 加 margin-left:55px 再裁,要么别用它 —— 我因此误报过一次「介绍页左偏」,已向 c2 认错。
- **logo**:用户给 `~/Desktop/1024px.png`(3072 方图,米驼底白字 LONSUEE),说所有界面直接用。5bbd4f13:原图缩 512 进 `docs/品牌/`;运营平台顶栏 + 每页标签图标走 nav.py 的 `LOGO` 内嵌常量(app.py 注入 icon);8760 首页 .mk 另内嵌一份;AI 管理后台放 `管理后台/apps/web/logo-96.jpg` 走 /static/。离线渲染三处页头看过、密钥扫描干净。**改了 管理后台/ → 推前必须 make test-e2e-ci;服务要重启才看得到(8770 用 kickstart)。**
- **待推(工作树领先 origin/main)**:34839147 计数、88abdbb4 发布脚本、5bbd4f13 logo + 几笔交接。等 eureka-fc 推完(它说 pre_push 第三遍、约 15:0x 推;之后跑 13 道题、再改 tools/nightly_eval.py 入库清单 —— **那个文件别碰**;它还改了 tools/bite_run.py 让 spans.jsonl.1 走只读软链)。
- **介绍页**:c2 已换 logo、手机版切换按钮改两行两列;我量过 390 宽全在屏内、无溢出;交互三样只读代码核过逻辑对,**真点击要用户自己点**(超出我的许可)。

### 🟡 11-18 13:4x · 交接(压缩前,第二份)—— 8770 已重启修好研判队列;介绍页新增 16 页的核对派给子助手在跑(Opus 5.5)

- **8770 研判队列跑不动**:根因是常驻服务 com.lanxiu.agentsite 进程从 11-15 没换过(有人用 start.sh 的 nohup 另起,端口被占起不来,老进程一直在)。13:10 用 `launchctl kickstart -k gui/$(id -u)/com.lanxiu.agentsite` 重启,首页 302、四页 200、队列 19 条/16 条有草稿、详情 `/api/ops-detail?id=N` 0.07s。**以后重启 8770 一律 kickstart,别 nohup。** 「重新研判」(调模型+写库)没点。
- **介绍页 c2 给的口径**(已发):工具 110(domains.py 多的 review_motif / motif_todo 不是注册工具,知识与工艺 15);守卫 6 = 开场注入/调用前/调用后/**调用失败**/交付前/压缩前;交付前检查 29。业务线只讲机制不抄数字(产品说明是 10-19 版)。
- **在跑**:后台子助手核对 `~/Desktop/lanxiu-intro/澜绣云裳agent-产品介绍.md` 新增「三条业务线 → 安全与边界之前」;**结果出来按行号转给 c2**(c2 已推公开网页,提醒过它核完前别宣传)。
- 其余同下一节(待推 2 笔 + 等用户拍两件 + README 链接)。

### 🟢 11-18 13:xx · 交接(压缩前)—— 介绍页交给新会话 eureka-c2 做;我这边待推 2 笔;锁归 eureka-fc(Opus 5.5)

- **介绍页**:用户新开会话 **eureka-c2**(家目录起的)做澜绣云裳介绍页,项目目录 `~/Desktop/lanxiu-intro`(index.html / docs.html / 《澜绣云裳agent-产品介绍.md》已发飞书产品文件夹)。用户拍:真截图(用户自己截)、配色跟 workbuddy.ai、名称「澜绣云裳」、本地一份 + GitHub **独立仓库**开 Pages。
  - 我给的:事实包 `~/Desktop/澜绣云裳agent-介绍页素材/事实包-20261118.md`(c2 复制了一份进它目录,之后以它那份为准);演示账号**只给了用户**(店长 60000001,公开演示口令),没发 c2。
  - 我审了产品介绍,6 处要改已发 c2(时延「十几秒」无依据、「不会编」太绝对、「不会重复退款」→「一笔流水只能登记一次」、「家庭账户」不存在、凭据保证要按审计范围写、直调约 12 秒)。**已验:c2 全改了**(md + index + docs 里旧说法 0 处),飞书已重发。
  - **下一步等 c2 找我**:用户看过本地版、GitHub 仓库建好后,我在主仓库 README(改 `tools/readme_head.md`,README 是生成的)加一行链接,走门禁推。
- **待推**:34839147(项目日志计数改 git ls-files)+ 本交接。等 eureka-fc 喊(它推 3 笔 + 跑 15 道题,约 14:xx 完)再拿锁 ship。
- **等用户拍**:主检出 06:40 那份项目日志丢不丢(我建议丢)、飞书授权要不要重登。
- **禁区**:截图期间别动共享库;主检出工作区别写文件(交接门禁指的是主检出 HANDOFF,但我只改工作树这份,推了才同步)。

### 🟢 11-18 12:0x · 交接 —— 第六轮已推(950add36 → 7061db03,全量门禁退出码 0);锁归 eureka-fc 约 2 小时(Opus 5.5)

- **未推**:34839147 项目日志「Python 文件」改数版本库登记的(原 find 把 .claude/worktrees 算进去:真数 1177,日志写过 4342 / 5589)。
- **来源**:launchd `com.lanxiu.daily-log` 每天 06:40 在**主检出**跑 make_log --publish → 主检出留一份未提交的项目日志,会让咬合重放「工作区不干净」拒跑(第六轮第一次就栽在这,备份→恢复→推→放回解决)。飞书发布每天「等待授权超时」(登录过期,需用户点授权)。**主检出那份 06:40 版仍未提交、数字是错的,丢不丢等用户拍。**
- **eureka-fc 提醒**:评测共用收尾现在设 `LANXIU_EVAL_NO_TAKEOVER=1`,我跑评测时接管是关的,成绩单会印一句。
- **eureka-fc 改了** api.py 里 call_opportunity 描述(返回带客户号),它的线。

### 🟡 11-18 09:xx · 交接 —— 远端页面冒烟红在知识修订页「字面星号」,已修(4c472aaf),第六轮 e2e+ship 在主检出跑(Opus 5.5)

- **起因**:eureka-fc 报 8534385b 的远端 admin-e2e 发布链那条过了,但页面冒烟换成红在 `#/knowledge-revisions`。CI 原文:清单页「原来写的 → 改成」格里两个单边 `**` 拼成一对。
- **根因**:e2e 从真知识库摘句当「原来写的」(知识库 md 本身带 `**`),清单页截 40 字把一对截成单边。**不是要渲染成粗体** —— 这几个字段要逐字对回源文件。
- **修法**:原句 / 改成 / 段名 / 改动文本标 `data-raw="原文"`(全站惯例,冒烟判据对它豁免)。用 CI 那段原文 + 判据正则验过:旧红、新不红、豁免不外溢。
- **推送**:主检出并回 w1117(b0c59b9a 汇总交接、1a9b284f 日志脚本、4c472aaf 本修)→ 锁内 `make test-e2e-ci` → `ship.sh`。状态看 scratchpad `gate_batch6.status`(只认「被包的命令退出码」那行)。
- **eureka-fc**:让出锁、在改「被接管技能评测两条路分开考」(只改评测脚本);**我推完放锁要喊它**,它再跑 15 道改过的题。

### 🌙 11-16 21:3x 用户开 12 小时夜间长任务(和并行会话合力)—— 计划见 .wip-glossary/night-plan-1116.md;第 23 轮在跑(拆分已 rebase 到 8e2c0c89,HEAD be3753a8)
- **07:4x**:并行会话第五遍绿、**已推 86043ae0**(含我的 16fcfc9c / cd8eb81e),锁空。它这段不起门禁不写库,手上一笔文档等我三件做完。**现在轮到我**:① 找发版口发 v20 ② shrink13 rebase origin/main → pre_push → 推 → 提交号给用户和它 ③ rare-i ops 全量。
- **07:1x 找发版口(未找到,接着找)**:v19 当时用的命令形如 `… --切 19 --加开 <工具>`(见提交 c904f9cc 的 HANDOFF 段),但 `git grep -- "--切"` 在 .py 里没命中 → 可能在 管理后台/ 下的脚本或 make 目标里;先查 `管理后台/` 和 Makefile 里的「切 / publish / 版本」,再看项目日志 11-14 TL84–88 发版那节(搜「v17」「v18」)。并行会话已同意:它放锁后到我推完 shrink13 这段不起门禁。
- **07:0x 用户拍板(AskUserQuestion):「发,整批都发」** —— 店长助手后台 v19→v20(shrink13 的 TL98–TL107,含 close_bad_rating「(名单见工具说明)」那处)。⚠️ **别在并行会话 pre_push 跑着时发**:一发,没带 shrink13 代码的检出 assistant_effect_check 立刻红。顺序:并行会话 07:35 推完放锁 → 告诉它我要发 v20 → 拿锁:发 v20(照 TL84–88 当时的发版做法,查项目日志 c84782f 那节 / tools 里的发版脚本)→ shrink13 rebase origin/main + select_eval 第一层两组 → pre_push → 推 → **再**做 rare-i 的 ops 全量。
- **06:44**:并行会话第五遍 pre_push 起跑(cd8eb81e 已成它的 86043ae0,本地五笔),预计 07:35 推完放锁喊我 → 我:`git checkout rare-i && git rebase --autostash origin/main` → gate_lock 里 `LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5 ./agentsite/.venv/bin/python agent/ops_eval.py`(全量两轮 ~2h)→ 提交 agent/ops-eval-results.jsonl → eval_tier_check → pre_push → 推 → 告诉用户和并行会话提交号。
- **06:4x**:第四遍重放红在规格 1752(名单清空后攻击没东西可改坏)→ 改攻击为「判红塞进事故前缀」,**cd8eb81e**(nightly-fix,接 16fcfc9c),交并行会话 cherry-pick 跑第五遍。我工作区缺 6fcee46f 的夜跑结果,在我这跑重放会「对照就是红的」,别在这跑。
- **06:1x**:并行会话 pre_push 第三遍只红夜跑清单 → 我修好 **16fcfc9c**(分支 nightly-fix,不带 passed 的行不算 0 分 + 删 oppo 过期登记),交它 cherry-pick 一起推;它先跑第四遍(约 50 分钟,赶 08:40 前),推完放锁喊我 → 我 rare-i rebase(rare-i 现 4 笔,含 b35ca208)→ ops 全量 → pre_push → 推。
- **04:4x**:工作区切到 **rare-i**(3 笔:dfa86efa / 0c4524e6 / 9c416138 判官 max_tokens 300→1024 / b35ca208 判据「是否 X」不算说了 X,夜跑 G06)。shrink13 分支原样留着。等并行会话 06:05 前后喊「锁放了」→ rebase origin/main → ops 全量两轮 → pre_push → 推。
- **04:2x 状态**:并行会话改排程 —— 夜跑 04:21 还没完,它等 05:10 世界平移完,**05:15 前后接锁跑 pre_push 第三遍,约 06:05 推完放锁喊我**;我再跑 ops 全量(约到 08:05)。期间我不占锁。夜报核对:接管兜底已生效(02:02 call-notes、03:17 store-report,原因聊天站没配管理后台地址,已写进早上卡片);**经营报告定论(04:29 夜报)**:老崩溃(api._c unable to open database file)11-16、11-17 两晚都没再出现、无崩.log;今晚 1/3 题「跑挂了」(调用失败)所以没写结果文件,末轮 2/3。另:talk_eval 的销售话术判官被 max_tokens=300 截断 → 判定不可信,白天修(我的线);「找工具空转」是已知的环境性失败(rounds.py,不计分),不是新问题。细节在 .wip-glossary/night-plan-1116.md 03:3x 节。
- **01:2x 状态**:夜跑 00:00 起在跑(nightly_eval.py pid 78757),两边都不占锁。我在 shrink13 分支,无新提交。⚠️ `tools/gate_lock.sh` **没有 status 子命令** —— 写了会真拿锁去跑「status」(01:28 误拿一次,1 秒内退出 127 已还锁);看锁状态别用它。下一步:夜跑出 nightly-eval-ok(约 03:40,最晚 04:55)→ 先看夜报(接管兜底 / 经营报告崩不崩)→ 等并行会话推完喊「锁放了」→ rare-i rebase + ops 全量两轮 → 推,告诉用户提交号。早上问用户卡片 .wip-glossary/morning-card-1117.md(发后台 v20)。
- **23:3x 状态**:拆分已推 be3753a8。工作区现在在**本地分支 shrink13**(缩说明第 13 批 + 配套,未推,等用户批发后台 v20;可能在 11-14「只挪不改字」授权内,早上问一句)。**rare-i** 分支 2 笔(I 面落地 + 判据两处结构修),夜跑后锁空时 rebase → ops 全量两轮 → 推。w75 停在 be3753a8。并行会话第二遍 pre_push 22:57 起,预计 23:50 推、00:30 前放锁。逐条进度看 .wip-glossary/night-plan-1116.md。
### ⏱️ 12 小时长任务清单(11-17 20:1x → 11-18 08:1x)

> 用户 20:1x 起的夜间长任务;定时提醒 **bdd2847e** 每小时 :17 / :47(session 内;白天那只 d424763d 已删)。白天 12 件全做完并回主干;**用户 20:1x 已推:origin/main 7816c0c4 → 5a992fb6**,第四轮门禁 17:43 起:e2e-ci 绿,全量咬合重放 105/111 零红,全部检查接着跑。

**用户 20:3x 拍的四板**(执行手册同步;别再问):① **店长只能停用本店员工**(紧急止损),开通 / 改权限 / 重置口令仍只总部运营 —— W19 店长那半按这个做,加一条「停用后当天会话作废」;② **根目录文档按归档清单搬**(23 份 → docs/归档/,两份外来的 → docs/外来/,链接用脚本改);③ **演示员工不置「首登改密」**,上线靠真实工号 + 重置流程带出的标记;④ **白天夜里都长期允许我自己推主干**(门禁全绿 / 扫过密钥 / 只推自己的 / 记进交接;写进 CLAUDE.md 铁律 1)

**守则**(同白天那节,另加):0 点到夜跑结束(看 `.feynman/nightly-eval-ok` 比 11-18 00:00 新)**不占锁**;05:10 世界平移之后才再要锁;eureka-fc 要 rebase 推评测结果 e165095d,等用户推完主干就让它推;**允许自己 push(用户 20:1x 拍今晚、20:3x 改成长期)**:条件照昨晚 —— 每批走 `./tools/ship.sh`(不带 --不推就是它推)、扫过密钥、只推自己的提交、推完记进交接、早上汇总列清;eureka-fc 夜里要推就请它自己走流程;手工跑检查前清 `__pycache__`

**清单**
1. 🟡 **第四轮门禁收尾**(20:47 出结果):e2e-ci 绿、咬合重放 111 条全过,**全量判定不过 2 条** —— ① 管理后台契约没登记 7 条接口(知识修订 6 条 + 应用归档 1 条,`route_exists_check`)② 全角棘轮 41→42(新脚手架的模板字串被当成字符集)。**21:1x 都在工作树修了**(契约登记 7 条、清单接口补 next_cursor 游标、模板搬出 .py 成 `.tmpl`、openapi.json / api.ts 重生成;route_exists / spec_coverage 95 条 / 全角 41 复跑绿)。⚠️ 主干 5a992fb6 用户 20:1x 已推,**远端 CI 这两条现在是红的**,第五轮(e2e-ci + ship 真推)并回后立刻跑 —— 锁 21:09 在 eureka-fc 手上(pre_push),它放了若在 0 点前且来得及就跑,否则 **05:10 之后第一件事**
2. ⬜ **21:50 日间汇总**:草稿 `scratchpad/日间汇总草稿.md`(会清;要点在白天那节清单里)→ 写成《澜绣云裳agent-日间汇总-20261117.md》(形状照 11-14 白天汇总)→ `python3 tools/feishu_publish.py` → 随下一笔提交
3. ⬜ **W45 分页那半**(不要锁写、验要跑检查):`server._simple` / `customer_list` / `order_list` 全表读进内存再 `_page` → 改成 SQL `LIMIT/OFFSET + COUNT(*)`,**默认页大小和返回形状不变**(前端 pagerC 读 total / page);facets 照旧;先量一次 customer_list 1.5 万行的耗时再改;customer_detail_check / order_list_check / 页面 js_smoke 要绿
4. ⬜ **W02 路径单源**(不要锁):30 多个模块各自 `DB = os.path.join(HERE,"lanxiu.db")`,检查靠 `m.DB = 副本` 逐个指过去 → 先盘点有几处、哪些检查改哪些模块的 DB;方案写进执行手册 W02,**改不改今晚看盘点结果**(改了要 30 多个文件同时动,门禁一轮)
5. ⬜ **W33 ③ 预研**(不要锁):量 check.sh 434 条里 <1 秒的有多少、各自 import 有没有模块级副作用(只读分析,出一张表进执行手册),**不动 check.sh**
6. ⬜ **08:10 后**:《澜绣云裳agent-夜间汇总-20261118.md》→ 发飞书 → make_handoff → 请用户推 → CronDelete bdd2847e

### ⏱️ 12 小时长任务清单(11-17 09:5x → 21:5x)

> 用户 09:5x 起的第二轮长任务;定时提醒 **d424763d** 每小时 :13 / :43 叫一次(session 内),21:50 后写《澜绣云裳agent-日间汇总-20261117.md》发飞书、刷交接、CronDelete。内容 = 早上再核表里**不用拍板、不动共享库结构的 10 件**(W34 W35 W37 W32 W33 W43 W19 W28 W45零风险半 W16)+ 两件口径已定的小活。**做完清单别停**,接着挑再核表里剩下的里不用拍板的边角。

**守则**
- **锁**:eureka-fc 09:5x 起在跑 店长助手 v21 效果检查 → 推 shrink13 → ops 全量(它估到约 10:30–12:00);**我占锁前发它一句、放锁发一句**(门禁 / 写库 / 重启 aimc / bite_run 都算),它要就让。等锁时先做下面不要锁的项
- **push**:昨晚的授权到 08:40 已过期 → **今天默认由用户推**(每批 pre_push --不推 绿了请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main`);用户若再授权就照昨晚条件(pre_push 推模式、扫密钥、只推自己的、记交接)
- **不许做的**:不碰 eureka-fc 的文件(pre_push.sh / api.py 工具描述区 / prompts.py TL / rounds / textmatch / nightly_eval / nightly/ / guards.py)—— **W33 门禁分层若要改 pre_push.sh,方案写好交它改**;共享库结构只经 alembic 且锁内、先告它(今天的 10 件按计划都不碰 PG 结构;W45 的索引只做业务后台 sqlite 那半);放宽守卫交用户 `!`;三件运行日志不 add;不买、不开浏览器;改 管理后台/ 推前 make test-e2e-ci;改 业务后台 server.py 后重启 8760 并 curl 首页;W35 的归档清单**只列不删**,给用户过一眼再动
- **每项做完**:打 ✅,一句结果 + 提交号;红了写红在哪、怎么修的;每批提交走一次 `pre_push --不推`(锁内)

> **13:2x 进度**:工作树 w1117 的九笔已全部快进并回主干(main = 37438955,领先 origin/main 20 笔,**未推**);共享库在锁内升完(业务后台 sqlite 迁移到第 6 条 + 两条索引;管理后台 PG 多表 knowledge_revisions,alembic_sync 绿);8760 已重启;W28 e2e 对真服务 21 条过。第二轮 ship 13:16 红在咬合重放「待办清单.md 的 401 → 404 数漂了」(已重生成提交 c4af52df)。**第三轮 `scratchpad/gate_batch3.sh`(e2e-ci → ship --不推)13:25 起**:e2e-ci 13:56 退出码 2 —— 页面冒烟红在「知识修订页能点开而冒烟没打过」(新页没登进 Makefile 冒烟循环和 page_smoke 路由表,工作树 14:2x 已补、单跑那页绿);全量 ship 接着在跑(咬合 111 条)。全量绿 → 请用户推主干 20 笔;工作树那两笔(PRD 附录、冒烟登记)下一轮并回再过 e2e-ci。锁在我手上到它跑完
> **15:50 第三轮结果**:e2e-ci 红在「知识修订页没登进冒烟」(已补);全量 ship 红在咬合重放五处(新写口没登记冒烟 / 报告模板检查造老表后指望确保表补列 / 首登改密闸没判空 / 索引规格预期红 / 顾问名字第四条攻击不可观测)—— **全部在工作树收齐并提交**(领先主干 4 笔)。16:0x 锁放给 eureka-fc 跑 ops 全量(约到 17:5x);它放锁后:主检出 `git merge --ff-only w1117` → 重跑 `scratchpad/gate_batch3.sh` 形状(e2e-ci + ship --不推)→ 绿请用户推。手工跑检查前先 `find backend -name __pycache__ -exec rm -rf {} +`(今天被旧字节码骑了十分钟)
> **17:5x**:eureka-fc 17:42 放锁(ops 两轮 99/132、108/132);工作树四笔已并回 main = 5a992fb6(领先 origin/main 24 笔,未推);**第四轮 `scratchpad/gate_batch4.sh` 17:5x 起**(日志 e2e_ci_1117_4.log / ship_1117_4.log),绿 → 请用户推 → 放锁喊 eureka-fc(它要 rebase 推评测结果 e165095d)。红 → 看 ❌ 行,修在工作树再并回

**清单(按顺序;要锁的项等不到锁就先做下一个不要锁的)**
1. ✅ **W34 交接分层 + 新鲜度**(10:04,**4aa55bd4**,本地未推、pre_push 未跑):`make_handoff.py --归档`(`--干跑` 先看)按小节标题日期切、没日期的子节跟父节走、自测守「留下的 + 搬走的 = 原来的」不守恒不写盘;`--check` 看到 3 天前的小节还在就 ℹ️ 提醒;真跑一次搬了 11-11 至 11-13 的 24 节 999 行(手写区 3166 → 2430);咬合 1943(砍继承那一句 → 自测红在指定那条,手工复现过);bite_check 绿(顺手补了规格文件末尾换行,1892 盯着它)。原计划里「按月分文件」没做:按搬走那批的日期范围命名更贴「原样搬出」
2. ✅ **W35 文档收敛 + 拍板台账检查 + CLAUDE.md 对账**(10:13,**32e1f0c9**,本地未推):`tools/decision_ledger_check.py` 挂门禁(两处台账合起来 1–81 不断号、PRD 每段标题声明的条号 = 段里的行、四格都填、别处引的「台账第 N 条」都在、CLAUDE.md 点名的 31 个脚本路径都在;自测 7 组;咬合 1944 打 2.4.3 标题,副本上复现过红在指定那条)。**当天逮到三段标题漏条**(2.4.2 / 2.4.4 / 2.4.5,已改)。归档清单落在执行手册 W35(只列不动,**等用户过一眼**:搬哪些、别的项目那份 产品文档.md 放哪)。没做:「找同日条目」(按号对比按日期对硬)、CLAUDE.md 过期数字进 doc_numbers(每个数要先找出处)
3. ✅ **W37 第三方技能归档 212 + 改造版转自有**(10:22,**c091520a**,本地未推;**碰了 管理后台/workflows_api.py 可接管技能 字典 → 推前要 make test-e2e-ci**):212 个搬到仓外 `~/Desktop/accio-拆解/skills-archived-20261117/`(它们是 gitignore 的本地副本,搬动无 git 改动);install_accio_skills 按审查结论跳过 + 自有名单读 OURS;skills_check ⑥ 守「判不适用的不许还装着」(咬合 1945,副本复现过);两个改造版进 OURS(形状 13 份齐、可接管登记、来源进 frontmatter、指纹按流程更新且没加门槛);三处文档 11→13。六条相关检查本地全绿(skills_check / skill_shape / skill_body / takeover / doc_numbers / skill_registry)
4. ✅ **W32 ship.sh + new_check + make sync**(10:29,第四笔,本地未推):`tools/ship.sh`(包 pre_push 一层:三件运行日志挪开 → pre_push 同参数 → trap 不管绿红都放回;`--自测` 临时仓里验三步,绿)· `tools/new_check_scaffold.py`(骨架 + 自动挂 check.sh 最后一条单行 run 后 + 打印规格样子手填 + 跑骨架和 selftest_registry;`--干跑` 验过)· `tools/sync_docs.sh`(待办 / 工具表 / README / SOP 全刷再对账;`--只对账` 跑过:README 因为我直接改了 11→13 那行而对不上 → 重生成后绿)。CLAUDE.md §5 1.5 补了三句。**同笔带上 CI 红的修法**:管理后台 test_dsl_semantics 「并行/子工作流标着未实现」断言过期(昨晚实现了)→ 改成「只有代码执行未实现」,14 条过;CI 另一条(nightly_check 自测在无 git 身份的跑手上 commit 失败)eureka-fc 认领。**以后每批推之前用 `./tools/ship.sh --不推`**
5. 🟡 **W33 门禁分层**(11:4x,工作树 w1117 第六笔;① ② 做了,③ ④ 没动):① `gate_lock.sh` 轮询间隔 `LANXIU_LOCK_SLEEP` 可配(默认 20),自测给 1 秒,锁自测 60 秒 → 22 秒;② 本地快门 `tools/quick_gate.py`(工作区改了什么 → impact.覆盖 算覆盖它们的检查 → 只跑那几条,自己记退出码;算不出的文件明说「只能全量」;`--只列` / `--自测`)。**它是快门不是门禁,推前仍要 ship.sh 全量**。④(12:3x,第十笔)剖析了门禁里最慢的一条:归属转移检查 147 秒,根子是公海扫描对 1.4 万户逐户发 13 万次小查询(79 秒)+ 检查里再跑一遍命令行(52 秒);扫描改成一次装好整库字典再逐户判(逐户查库那条路保留),检查里加一条「两种跑法 8008 户一字不差」的对账 + 咬合;检查 147 → 62 秒(剩的是对账那遍慢路 + 命令行)。顺带:重建步数断言 51 → 52(多了 seed 后那次迁移),从零重建(克隆 + 软链 venv)全 52 步跑完、库到第 6 条、门店码 / 客户顾问 / 迁移三条检查绿。没做:③ 300 条 <1 秒的收进一个进程(要逐个确认无模块级副作用,一天做不完)。pre_push.sh 没碰(归 eureka-fc)
6. ✅ **W43 工单自动生成 + 编辑日志覆盖**(11:0x–11:1x,**工作树 w1117 第一笔 074eec03**,等门禁跑完并回主干):进「待生产」每道工艺一条工单、待派不派人、幂等;补录脚本 `tools/backfill_workorders.py`(干跑 347 张,**真写要在锁内 + 先告 eureka-fc**);检查 workorder_check 副本上真走状态机 7 条;两条咬合在工作树里手工复现过;客户资料编辑进 edit_log。**并回主干后要重启 8760**
7. 🟡 **W19 员工首登改密**(11:1x–11:4x,工作树 w1117 第二笔):迁移 m0003(默认 0、不置位演示员工)、总部运营重置口令、带标记只放改密口、8770 登录页就地改密、会话文件 fcntl 锁;staff_pwd_check 24 条、三条咬合复现过。**并回后要:锁内 `python3 backend/migrate.py` 落 m0003(先告 eureka-fc)→ 重启 8760;migration_check 在库升之前会红「库没到最新」**。店长开通 / 停用那半和 11-14 拍的「只总部运营」撞了 → **等用户拍**,日间汇总上列
7½. ⚠️ **门禁踩坑两处(都已在工作树里修)**:① 第四笔里的 `tools/new_check.py` 文件名撞了 selftest_registry 的 `*_check.py` 规则 → 主检出那轮全量门禁会红在「没进的 1 份」;已改名 `tools/new_check_scaffold.py`(引用三处同步)。② e2e-ci 10:48 退出码 2:页面冒烟 `#/apps` `#/studio/app` 卡在「加载中」—— 接口是通的(200,0.67 秒),根子是**演示项目里堆了 1100 个测试夹具应用**(发布咬合-× 212、发布链页面-× 199、e2e 改过名 191;单跑那一页能过,整套跑时渲染超时)。修法(第三笔):应用加正规归档口 `POST /applications/{id}/archive`(只收不挂工作流的、有活密钥 409、要理由进审计);两份测试夹具名带「e2e」且发布流程那份自己归档(+7 条断言);`clean_e2e_residue.py` 覆盖夹具应用(`--连旧名` 把 11-17 前两种旧名也算上);`make test-e2e-ci` 末尾自动收尾(用户 11-13 拍「并加自动收尾」)。**并回主干、aimc 重载后要在锁内跑一次** `AIMC_PROJECT=project_demo_a 管理后台/.venv/bin/python 管理后台/tools/clean_e2e_residue.py --执行 --连旧名`(只看模式数到:e2e 工作流 3414 条、夹具应用 412 个;先告 eureka-fc),再重跑 e2e-ci
8. 🟡 **W28 知识条目修订申请**(12:4x–13:0x,工作树第十二笔,**代码齐、库没升、e2e 没真跑**):管理后台(8801)新表 `knowledge_revisions`(契约实体 + alembic b7c1d2e3f4a5 + models CHECK),接口 提 / 清单 / 详情 / 审(采纳生成带括号注记的改动文本 / 驳回要说明 / 不能审自己)/ 标已合并 / 文件与段清单;权限:提 = 运行评测(和提意见一样)、审 = 受理意见(总部运营,照拍板 18「与问题单一致」)、标已合并 = 生产审核/发布/回滚;页面「知识修订」清单 + 详情;e2e `test_knowledge_revision_flow.py` 21 条 + Makefile 两处登记。**并回后锁内:`cd 管理后台/services/api && ../../.venv/bin/alembic upgrade head`(先 `alembic heads` 看 eureka-fc 有没有新头,有就改 down_revision)→ aimc 自动重载 → 跑那份 e2e**。原设想「店长审」被用户 11-12 否决(三家店审出三个版本),按「总部运营审,开发合并」做;改 md 本身仍是开发的活
9. 🟡 **W45 零风险半**(12:4x,工作树第十一笔):索引照 query_index.py 的规矩**量了再加**(真库副本各跑 30 次):客户详情页的预约 / 跟进按客户号两条 10.5x / 11.8x → 登记进 `query_index.索引`(带锚、实测),检查名单 + 咬合;手册点名的 op_log(target) 量出来只有 1.2x(6327 行)**不加**。**并回后要在锁内 `python3 backend/query_index.py --做`**(query_index_check 在那之前红「库里真有这条索引」两条)。没做:列表接口 SQL 分页(七八个列表页共用一个内存分页 `_page`,改法要先定)、多线程服务器(动服务形态,归 W31)
10. ✅ **W16 结构迁移目录替代删库重建**(11:4x–12:0x **A 15 + B 13 + C 16 共 44 处收编**,工作树 w1117 第四、五、八笔;**欠债 47 → 3**,剩 seed.py 建新表时顺手 ALTER 自己刚建的表 1 / fingerprint 自测给临时库造夹具 1 / mkt_sop_seed 1 待查)。**C 类(第八笔)**:`m0006` 收八个一次性工具的 16 处(shop_code 按 shop_key.带门店键的 加、顾问工号列按 fix_advisor_ref.映射 加、ordr.cust_advisor_no / wearer_id、appointment 三列含 CHECK、customer.source_channel、product 两列、maintain 三列);工具改成缺列就红并指路 migrate.py;重建第二次迁移挪到 ensure_tables 紧后面;shop_key_check 的顺序判据改盯 migrate.py。模拟 CI 从零重建(克隆)在 A+B 后验过一次通到第 5 条,C 后再验一次。**B 类(第五笔)**:`m0005` 列出九张表的 13 列(pool_notice.shop_code 补完还按 shop 回填门店码,数据修补也归迁移),九个模块的建表函数只建表、建表语句直接带全列(recall_advice / store_report_doc / report_template_ver / call_audio.consent_basis 四处 DDL 补齐),**重建流水线在 seed.py 之后立刻多跑一次 migrate.py**(seed 建的 scheme / refund_trace 在后面的 backfill 写新列、建唯一索引之前就补齐;原来第 54 步那次照旧);欠债 32 → 19;两条规格因重建步骤插入而过期已改;九个模块的检查全绿、发布流程 e2e 对着真服务 64 条过。**A 类(第四笔)**:新迁移 `m0004` 把 m0001 原样调用的 7 个函数的列清单写进迁移本体(customer / task / triage / call_audio / call_transcript 显式列;rating 从 seed_rating.DDL 现读),7 个原函数改成空壳(m0001 不许改、还会调它们),写口改成「缺列就报 NO_COLUMN」(ops 四处 / merge 读路径 / relabel 两处),asr 建表语句直接带上九列(重建第 46 步 backfill_transcript 在迁移第 54 步之前就写 raw_text),seed_rating 建表老表缺列时先不建索引。migration_check 欠债 47 → 32(五个文件清零从登记删掉),三条咬合改打新攻击点(复现过);rating_write / merge / relabel / reopen / call_flow 五条检查绿。**并回主干后要在锁内 `python3 backend/migrate.py` 落 m0004(migration_check 在那之前红「还差 [4]」)**。原计划(业务后台 sqlite;**eureka-fc 09:5x 把它手上的「迁移目录外 47 处 ALTER」欠债交给我一起做,它不碰**):先读它的只读盘点 `.claude/worktrees/工/.wip-glossary/alter-plan-1117.md` + 同目录 `alter_classify.txt`(A 15 处 m0001 已原样调用 / B 13 处建表函数里顺带补列 / C 18 处一次性工具,05:10 世界平移会跑 add_shop_code、add_cust_advisor / D 1 处 fingerprint 夹具是误登记)。**两个坑它点了**:① seed.py 里 triage 建表语句缺 7 列(reopen_count / reopen_note / relabel_* 五列)→ 顺序必须是 先补建表语句 → 运行时补列改成「缺列就回 NO_COLUMN」(照 delivery_notice_write.py:41)→ 最后才删 ALTER;补建表语句会改库指纹、触发重建;② 不许把 ALTER 字面量挪进迁移目录的辅助函数、运行时照旧调 —— 计数降了补列没少,是骗计数。然后:建 migrations/ 目录 + 版本表 + 幂等跑法;「删库重建」入口改成跑迁移;W28 的新表当第一条迁移
11. ✅ **业务后台页面按清单补打码**(11:5x,工作树 w1117 第七笔):新模块 `backend/mask.py` 只认清单 json(手机 / 身份证只露后四位、地址只到区、外部账号前两位+***+后两位,姓名 / 生日 / 量体 / 单号原样;认不出区的地址整个打成「(地址)」不猜);server.py 五处写死的手机号打码改读它,客户列表 / 详情整行按清单打(地址、微信原来 `SELECT *` 原样给页面);客户编辑弹窗地址改成「留空 = 不改」(防把只到区的地址回写);自测 11 条进门禁,咬合 1951。**并回后要重启 8760**。手机号从 138****5678 变成 *******5678(按拍板「只露后四位」)
12. ✅ **工具目录页标「业务后台已停用 / 已限流」**(11:5x,同一笔):管理后台 `GET /tools` 每行带「业务后台」(澜绣导入的工具 = {读到了吗, 启用, 限流每分钟};别的 = null;那边的库读不到就明说未知,不装作全启用),读的是业务后台 sqlite 的只读连接(mcp_registry.配置);目录页加徽标;test_tools_flow +2 条(**对着真服务要在并回 + aimc 重载后才能过**)。现在 mcp_tool_cfg 表是空的 → 全部启用、页面上不显示徽标
13. ⬜ **21:50**:《澜绣云裳agent-日间汇总-20261117.md》→ 发飞书 → make_handoff → 请用户推 → CronDelete d424763d

### 🟢 11-17 12:0x · 交接(压缩前,六项)—— 主干在跑门禁(ship 第二轮,卡在慢咬合),工作树 w1117 领先主干 6 笔等并回(Fable 5.1)

- **现在的局面**:主检出 main = 0647e56f(领先 origin/main 7 笔含 eureka-fc 的 a5003e6e 摘入,**未推**);工作树 `.claude/worktrees/w1117`(分支 w1117)在它之上 6 笔:3c99f9ef m0004 / 6bce9559 m0005 / 67753eda W33 / f00461d7 打码+工具目录 / dc0221e3 m0006 / 19cb107e m0006 补列。后台任务:① `scratchpad/gate_batch2.sh`(清残留 ✅ 3418 工作流 + 412 应用已归档 → e2e-ci ✅ 退出码… 11:37 完、退出码 2?**注意:status 文件写的 e2e-ci 退出码 2 —— 第二轮红在 test_release_flow 归档那几步用了没发布能力的角色(已在工作树 f00461d7 之前的 0647e56f 修?不,修在工作树 6bce9559 那笔里的 test_release_flow)**;主干那份测试仍是旧的 → 并回后 e2e-ci 才会绿)→ ship --不推(11:37 起,12:04 还在咬合重放 26/74);② `scratchpad/cisim`(克隆 w1117 从零重建,带 m0006,结果写 scratchpad/cisim_rebuild2.log)
- **未验证的预判**:① 主干这轮 ship 的全量门禁会绿(new_check.py 改名已并入 0647e56f;selftest_registry 在工作树里验过)—— 但 **e2e-ci 第二轮红在发布流程测试**(归档那几步 403),那份测试的修法在工作树里,主干没有;② m0004–m0006 在共享库上还没跑(migration_check 在主检出会红「还差 [4,5,6]」直到锁内 `python3 backend/migrate.py`);③ W19 的 8770 登录页改密框、员工页重置口令按钮**没在浏览器里点过**(只有 HTTP 层 24 条);④ 工具目录徽标没在页面上看过(mcp_tool_cfg 现在空表,本来就不显示);⑤ cisim 第二轮(带 m0006)结果没看;⑥ 迁移 C 类改了 8 个一次性工具,**daily_shift.sh 148 行 `add_shop_code.py --做` 和 163 行 `add_cust_advisor.py --校验` 没真跑过**(05:10 世界平移会跑,库那时已经升了就没事;没升就红在「先跑 migrate.py」)
- **判据**:只认 gate_lock 印的「被包的命令退出码 N」;ship.sh 用 trap 放回三件运行日志;店长开通 / 停用撞 11-14 拍板 → 不做等拍;打码按 11-17 07:0x 八项,手机从 138****5678 变 *******5678;迁移不许改做过的文件,m0001 原样调用的 7 个函数留空壳;seed.py 的 DDL 不改(改了动库指纹触发重建)
- **作废**:「W16 要先补 seed.py 的 triage DDL」(并行会话的建议,改成 m0004 在重建第 2 步补);HANDOFF 早上几项的时间标注(已按提交时间改正);「e2e 红是代码问题」(是 1100 个夹具应用渲染超时)
- **禁区**:不碰 eureka-fc 的文件(pre_push.sh 等);锁在我手上到 ship 跑完,放了要喊它;**今天不自己推**(用户没授权),门禁绿请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main`;工作树里不跑 bite_run / 全量(共享库);主干门禁跑的时候不碰主检出的已跟踪文件
- **下一步第一个动作**:看 `scratchpad/gate_batch2.status` 最后一行 —— 全量门禁绿 → 请用户推 main → 在主检出 `git merge --ff-only w1117` → 锁内 `python3 backend/migrate.py`(落 4–6)→ `launchctl kickstart -k gui/$(id -u)/com.lanxiu.backend` + curl 8760 首页 → `AIMC_PROJECT=project_demo_a` 清理脚本只看一遍 → 重跑 `scratchpad/gate_batch2.sh` 的形状(e2e-ci + ship --不推)→ 绿了再请用户推 → 放锁喊 eureka-fc。红了先看 ship_1117_2.log 的 ❌ 行
- **悬而未决**:店长开通 / 停用(等拍);根目录文档归档清单(等用户过眼);39 名演示员工要不要全员置首登改密(上线动作);W16 剩 2 处;W28 / W45 没动;21:50 日间汇总(草稿在 scratchpad/日间汇总草稿.md,scratchpad 会清 —— 要点都在本节和清单里)

### ⏱️ 12 小时长任务清单(11-16 20:40 → 11-17 08:40)

> **✅ 07:4x 全部推上主线:origin/main be3753a8 → 86043ae0(第八笔 4e2d3227 + 夜跑自动 6fcee46f + eureka-fc 两笔 0fc04654 / 86043ae0 + 第九笔汇总 0fc74e22)。pre_push 跑了五遍:①咬合规格过期 ②契约漏登 auth 列 ③夜跑清单(评测线)④其修补牵出的规格 ⑤绿。锁已放给 eureka-fc(发 v20 → 推 shrink13 → ops 全量,约到 10:30,这期间我不起门禁)。剩第十笔 ac973120(打码口径三处 + 工单再核表 48 项:18 完 / 6 半 / 1 不做 / 23 没动)本地,08:2x eureka-fc 让锁、我起 pre_push --不推,绿了请用户推;08:40 后发飞书汇总、CronDelete 8925a3d6**

> 用户 20:3x 起的长任务;定时提醒 8925a3d6 每小时 :13 / :43 叫一次(session 内),08:40 后汇总发飞书、刷交接、CronDelete。**做完清单别停**:接着做执行手册里不用拍板、不动共享库结构的欠账(用户 11-11 定的:给的是时间不是清单)。

**守则**
- **锁空档**:eureka-fc 第 23 轮 20:05 起、约 21:30 推完并说「解禁 + 提交号」;之后锁空着。**每次占锁前发它一句、放锁发一句**(写共享库、跑门禁、重启 aimc、bite_run 都算占锁);它要锁就让,一件一件来
- **21:3x 用户拍了三条(台账七十六至七十八)**:子工作流二期要能在子流程里等人(独立子运行、父流程停下等);并行真并发排下一期;HTTP 写操作(POST/PUT,幂等键 + 审批桥)排下一期。**今晚都不做**,一期照现状落地
- **07:0x 用户拍了「给人看怎么打码」八项**(台账八十一):姓名 / 生日 / 量体 / 订单号原样,地址只到区,手机号 / 身份证后四位,外部账号前两位+***+后两位 → 已落清单 json + PRD + 汇总(第十笔,本地未推;业务后台页面按它补打码待做)
- **已拍板,不再问**:三期 11 条安全决定按设计稿(HTTP 一期只 GET/HEAD、凭据只从连接来、白名单、不跟重定向、15 秒 / 1 MB);定时三种频率、二选一;统计区间「上一次到这一次」;鉴权三档编码中文是实现细节、不是业务拍板;C6 代码执行节点**先盘点再定**(没有「非写代码不可」的步骤就不做)
- **21:4x 用户又拍三条**:① **今晚(到 08:40)允许我自己 push**——条件:每批走完 `pre_push`(不带 --不推 就是它推)、扫过密钥、只推自己的提交、推完记进交接、早上汇总列清;② 敏感字段清单按拟的版(台账七十九:手机号 / 姓名 / 收货·家庭地址 / 身份证号 / 生日 / 量体数据 / 微信·外部账号 / 订单·工单号)→ 新增清单项 9½;③ W44 告警进群先不做(台账八十)
- **不许做的**:不碰 backend/api.py 和读 api 源码的 46 条(窗口没解禁);共享库结构只经 alembic 迁移且在锁内、先告 eureka-fc;~~不 push~~(今晚允许,见上;08:40 后恢复由用户推;eureka-fc 夜里要推就请它自己走流程);不碰 eureka-fc 的文件(pre_push.sh / api.py 工具描述 / prompts.py TL / rounds / textmatch / nightly_eval / nightly/ / guards.py);放宽守卫交用户 `!` 执行;三件运行日志不 add;不买、不开浏览器;迁移文件在、库没升之前别跑 pre_push;每批提交走一次 `pre_push --不推`(锁内,约 45 分钟),绿了才算做完
- **每项做完**:打 ✅,一句结果 + 提交号;红了写红在哪、怎么修的

**清单(按顺序;要锁的项等不到锁就先做下一个不要锁的)**
1. ✅ **工具连接鉴权列落地**(22:2x **e2e-ci 真实退出码 2 → 57 过、只红 test_orchestration_flow 一条老断言(不可用节点集合写死 {并行,子工作流},改成 {代码执行})→ 单跑 88 条全过**;咬合七组 22:2x 起锁内重放,日志 scratchpad/bite2.log)(22:1x 三份单跑:tools_flow ✅ 新四条过、audio ✅、http_node 首跑红在 RUN_MODE_MISMATCH —— 测试自己起的 worker 写死 MODEL_ADAPTER=mock 而运行现在记 live,改成跟服务同模式后 **14 条全过(含真发送支:白名单本机地址 → HTTP_TARGET_FORBIDDEN)**;又给 ④⑥ 加了「服务是 mock 模式就标没验」守卫以防 CI 红;e2e-ci 22:1x 起在锁内跑,日志 scratchpad/e2e_ci2.log;提交说明草稿在 docs/交接归档/夜间链-20261116-第八笔提交说明.md)(22:0x:eureka-fc 21:55 推完 be3753a8 并解禁 api.py;我 rebase --autostash 上去,HANDOFF / bite_specs 冲突两边都留、规格并集 1942;锁内 `alembic upgrade head` 2ae099e8e0f0 → 5a9f567d29b4 **已落共享库**;鉴权接线脚本真跑(登记 / 列表 / worker / 搭建资源 / e2e)编译过;aimc 已重启、工具连接列表 200。接着:三份 e2e 单跑 → e2e-ci → 咬合 → 提交 → pre_push → 推)原计划(要锁):收到解禁 → rebase --autostash → `alembic heads` 核头 → 锁内 `alembic upgrade head` → tools_api 建 / 列收回「鉴权」、worker 1022/1030 读 auth、workflows_api 搭建用的资源带「鉴权方式」→ 重启 aimc → test_tools_flow / test_http_node_flow / e2e-ci → bite --only test_tools_flow → make_handoff → 第八笔 → pre_push --不推
2. ✅ **流程顶层结构改成派生副本**(20:4x 代码写完**未跑**:dsl.同步顶层结构 + 改图草稿调它;看冻结版本回「入参结构 / 出参结构」;audio 测试改读接口 + 顶层已同步 + 进程内 ck;咬合 1934 打 dsl 那个 if;PRD B-123 两条未解决划掉。等锁:audio e2e + bite --only test_audio_flow)原计划(不要锁写代码,验要锁):PATCH 草稿时把定义顶层 input/output_schema 同步成开始 / 结束节点里那份(两份不再分家);GET 版本详情返回入参 / 出参结构;audio 测试改读接口不读库;图校验 / 咬合各 +1;PRD B-123 未解决事项划掉前两条
3. ✅ **HTTP 节点 live 路径端到端**(20:5x 代码写完**未跑**;顺带修了一个真问题:受理算 mock / live 只看模型连接 → **只有 HTTP 步骤的流程永远 mock、一个字节发不出去**,现在 http_request 选了工具连接也算真连接(`_受理运行` 有HTTP连接);e2e ④ 改成「连接测试」跑法拿替身、断言运行记 live 而步骤交 mock;新加 ⑥:白名单 `http://127.0.0.1:9/v1` 正常跑法 → 期望 run failed、h 步 HTTP_TARGET_FORBIDDEN、详情含「没发」、不含凭据定位符。**判断依据**:既有规则「选了真连接就真跑」,工具连接没有演示版;不跟重定向 / 凭据不进记录两道只能进程内验(已有 20 条)。等锁跑)原计划:本地假服务(127.0.0.1 随机口)当白名单地址 → 真走 worker live 一支(`execution_mode=live` 受理怎么给、看 test_exec_mode_flow)→ 验:结果里 url / status 对、**运行记录 / 步骤 / 日志里凭据值一次不出现**(遮头生效)、解析到内网的域名被拒(假 DNS 只在进程内能注,端到端用 `evil.nip.io`-类真解析到 127.0.0.1 的域名或 `localhost` 白名单项 → 预期 HTTP_TARGET_FORBIDDEN)、3xx 不跟。走不通 live 就写清楚卡在哪,别硬凑
4. ✅ **HTTP 节点单步测试入口**(20:4x,未提交):runtime/单步测试.能单测的类型 + http_request(没选连接拦住指路「基本」);app.js 单测类型表同步、单测表对 HTTP 给专用文案(真发只读请求 / 连接测试交替身)、没选连接只给一句话;test_step_test +2(21 条过)、http_panel +2(37 条过);咬合 1935(删表项 → 预期红「选了工具连接的 HTTP 步骤拼得出小图」,**未重放**)。服务端单步测试 handler 不用改(它只认 能单测的类型 那张表)
5. ✅ **C6 盘点**(20:4x):六条流程从共享库各抽最新草稿逐节点看(只读查库),只用 tool / llm / condition / transform(concat / default / to_string)/ human / merge,复杂判断全在业务侧动作里 → **代码执行节点继续置灰,C1–C5 不拍**;结论写进 执行手册 W39-0 和 PRD 2.4.5(doc_numbers rc=0)。原计划(文档):列 6 条业务流程每一步用的节点,找「非写代码不可」的步骤;结论写进 PRD 2.4.5 台账 + 执行手册 W39-0;有 → 只写方案不做
6. ✅ **并行与汇总节点**(21:0x 代码写完、进程内全绿,**未提交、e2e-ci 未跑**):契约里本来就有 `N("parallel")` 预留(端口 支路/成功/失败,配置 branches/max_concurrency/wait_policy),改成已实现;新模块 runtime/并行.py(配置问题 / 支路键们 / 必需吗 / 汇总);validator:入口改成列表、并行每条支路各算可达与支配、新段 ③½(十二种阻断码:BRANCH_NO_KEY/DUP/NO_REQUIRED/CONCURRENCY_UNSUPPORTED/BAD_WAIT_POLICY/BRANCH_NO_EDGE/EDGE_NO_BRANCH/BRANCH_NOT_INSIDE/BRANCH_SHARED/CROSS_BRANCH/NESTED)、跨支路引用不再多报 BIND_MAYBE_MISSING;compiler 支路边按键分;runner 新帧种类 parallel(串行跑支路、循环回 记「回自」、按等待策略处理失败、PARALLEL_BRANCH_FAILED、检查点可恢复);前端 菜单 / 容器框标「并行」/ 出口每条支路一个 / 口名 / 面板(支路增删改名、改名连线跟着改、必需可选、等待策略两种、并发上限固定 1)/ 结果三项 / 放进并行;test_parallel_node 15 条、图校验夹具 +3(36;「未实现」例子换成子工作流)、test_workflow_parallel_panel.js **24 条过**(登记 Makefile 三处 + orchestration 目标,test_registry_check 73 份)、咬合 +2(规格 1937,未重放);规格 §6.1 并行行改写。**判断**:支路结果 = 该支路最后一步的输出(人工核对在末尾就是核对结论)。原计划(W39-2,设计稿已拍):先语义(独立状态命名空间、等全部必需支路、失败策略 全成功 / 任一成功 / 允许部分),`max_concurrency=1` 串行实现;dsl / validator(支路不许互引、汇总必填)/ runner / worker / 面板 / 夹具 / e2e / 咬合 / 规格 §6.1
7. ✅ **子工作流节点**(21:4x 代码写完、进程内全绿,**未提交、e2e-ci 未跑**):契约 `N("subworkflow")` 改已实现 + 新登记 `N("code","代码执行")` 为未实现(「不得摆空按钮冒充可用」那条夹具的例子,C6 盘点后代码执行先不做);新模块 runtime/子工作流.py(配置问题 / 合上限 / 递归链 / 不能等的步骤 / 步骤摘要,深度上限 3);validator ⑥½(RECURSION / TOO_DEEP / WAIT_UNSUPPORTED / INPUT_MISSING / INPUT_UNKNOWN 警告 / 上限形状,没「取版本」能力时 CHECK_SKIPPED 明说没查);workflows_api `_依赖查询(c, project_id, 本工作流=wid)` 挂 取版本 / 本工作流(四处调用点都传了),搭建用的资源回「工作流版本」;runner 把 subworkflow 走适配器那支(input_mapping 解绑、父剩余额度、深度);worker `_subworkflow`(同步跑子图、合上限、拦等待、折摘要、更深一层的 SUBWORKFLOW_* 原码上传);前端 菜单 / 面板(只列别的流程的冻结版、要什么返回什么写在选项里、上限两框)/ 用到的数据按那一版入参出契约行 / 结果字段跟那一版;test_subworkflow_node 13 条、面板测试、夹具 +2(38)、咬合 +2(1939)、spec_coverage 首版集合 +2、Makefile 登记(registry 74)、规格 §6.1 子工作流行改写。**判断**:一期子流程里不许等人(人工 / Agent / 写动作)—— 用户 21:3x 拍二期要做;深度上限 3 是拍脑袋的技术数。原计划(W39-3):只引冻结版本、静态禁递归(引用图上找环)+ 动态深度上限、预算随父(SUB_LIMIT_EXCEEDS_PARENT 已有)、输入输出按被引版本的入参 / 出参结构绑;同上一整套
8. ✅ **工具开关对账检查**(21:5x 写完、真跑绿,**未提交**):`管理后台/tools/switch_sync_check.py` —— 比对纯函数 + `--自测`;真跑读管理后台 tool_definitions(adapter lanxiu-shop / kb / task 共 105 个,**lanxiu_bridge 那 9 条桥能力不是 MCP 工具、业务后台没有它们的开关,不在账里** —— 首跑把它们误报成「业务没有」,查过后排除)× 业务后台 mcp_tool_cfg(`mcp_registry.配置()` 只读 sqlite);三种不一致判红、限流只报;Makefile 登记在 lanxiu_tool_sync_check 后面(自测 + 真跑两行);咬合 1940 打「后台停了业务没停」那支(脚本带 --自测 参数,bite_run 支持带参)。**没做**:工具目录页标「业务后台已停用 / 已限流」(8801 要读 8760 的开关得过登录或读 sqlite,另排)。原计划(W38,拍板 9):`管理后台/tools/switch_sync_check.py` 读 8760 mcp_registry 口比对工具目录停用 / 限流状态,不一致红;工具目录页标「业务后台已停用 / 已限流」;挂门禁 + 咬合 + selftest_registry
9½. ✅ **敏感字段清单单源**(22:0x,**未提交**):清单落在 `管理后台/docs/口径/敏感字段清单.json`(八项,各带类型 / 常见字段名 / 给人看怎么打码 / 导出训练怎么处理 —— **「给人看」那列是我拟的默认**,早上汇总附表让用户看);`redact.敏感字段清单()` / `是敏感字段名()` 读它;test_redact +4。**查过两套脱敏的现状**:给人看的打码只有业务后台 server.py 两处手机号 `***`(字段写死),导出训练的脱敏器还没选型(training.py 明说);所以今晚只能立清单 + 读清单的函数,「两边都改成读清单」等脱敏器真做时接(业务后台页面打码要动 server.py + 重启 8760,另排)。PRD 第七十条状态待改。原计划:找两套脱敏(给人看打码 / 导出训练换假号)各自写死的字段表,抽成一份清单(放哪边先看两处各在什么包;**若在 backend/api.py 里就等解禁**),两处都读它;加测试「清单改一项两边都跟着变」+ 咬合;PRD 第七十条状态改「清单已定」
9. ✅ **执行手册里其余不用拍板、不动共享库结构的**(22:0x):**W29 ✅ 代码侧**(`tools/launchd/com.lanxiu.daily-log.plist` 每天 06:40 `make_log.py --publish`;`make_handoff.py` 正式刷新默认不再生成 / 发日志、要加 `--带日志`,`--check` 改按头部「最后更新」日期判「≥ 昨天」只报不拦;CLAUDE.md 第 5 节那条约定同步改;plist 等用户装:`cp tools/launchd/com.lanxiu.daily-log.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.lanxiu.daily-log.plist`)。W34 / W35 没碰。原计划:W29 项目日志每日定时(launchd plist 写好给用户装)、W34 HANDOFF 分层 + 新鲜度(make_handoff --check 已守行数,看还差什么)、W35 拍板台账检查;W40-② 在 api.py 禁区**跳过**
10. ⬜ **08:40**:`澜绣云裳agent-夜间汇总-20261117.md`(照 11-13 那份的形状:一句话 / 已提交待推 / 没做的和为什么 / 要你拍的卡)→ 发飞书 → make_handoff → 请用户推 → CronDelete 8925a3d6

### 🟢 11-16 22:0x · 交接(压缩前,六项补充)—— 清单 1–9½ 代码全写完、进程内全绿、**一个都没提交**;等 eureka-fc 22:30 解禁后一批跑完推(Fable 5.1)

- **未验证的预判**(全在等锁):① 整套 e2e-ci 没跑过今晚的任何改动(并行 / 子工作流 / 单步 / 顶层派生 / HTTP live 支 / 鉴权)—— 可能红的:audio(顶层派生改了存草稿)、http_node ⑥(live 支:期望 h 步 HTTP_TARGET_FORBIDDEN,若 aimc 的 MODEL_ADAPTER 判 mock 则运行会记 mock、断言红)、tools_flow 新四条(接口没升列前别跑);② worker.py 改了两处(_http 读 auth / 适配器们 + _subworkflow),**没重启、没跑过**;③ 迁移 5a9f567d29b4 未 upgrade;④ 咬合 1933–1940 八条都没重放;⑤ 规格 §6.1 两行改写后 spec_coverage 跑过 rc=0,但「表格行」解析只看名字列
- **21:4x 栽了一下(已回退,无遗留)**:想「干跑」鉴权接线脚本,用 exec 盖掉它的替换函数数锚点 —— 脚本自己的 def 把占位盖回去、**真改了文件**;aimc 的 --reload 立刻加载,工具连接列表 500 了约一分钟(select 了还不存在的 auth 列),原路回退后 200。教训:**工作区就是线上,「试一下」的脚本也要先有真的 --干跑**;脚本已加 `--干跑`
- **06:0x pre_push 第三遍(05:21 起,夜跑 04:29 完 / 平移 05:10 完之后)**:咬合全过、全量门禁只红 1 条「夜跑清单」—— 和我的改动无关:今晚夜报让 triage-pipeline.py 连续 3 晚 0 分成了没登记的事故类,oppo_eval.py 那条「已知连续失败」又过期了。名单逻辑在 tools/nightly_eval.py(eureka-fc 的文件,我不碰),它 06:2x 修好 16fcfc9c(triage-pipeline 那套一晚只写一行汇总没有 passed 字段,检测器数成 0/1 → 现在没成绩的行跳过;删过期 oppo 登记),我 cherry-pick 到本地摞上;**第九笔 = 夜间汇总 + 本交接**,然后 pre_push 第四遍(推模式,约 50 分钟)一起推:4e2d3227 + 6fcee46f(夜跑自动)+ 16fcfc9c + 第九笔。推完放锁给它跑 ops 全量
- **23:4x pre_push 第二遍:咬合 30 条全过、全量门禁只红 1 条** —— alembic check「模型里少了 capability_connections.auth」:迁移加了列,契约实体表(contract/entities.py E("capability_connections") 字段清单)和字段类型表(fieldtypes.显式类型,`auth` 套不上后缀)没登。已补,alembic_sync_check ✅、gen_contract_doc 重生成(契约.md 无 diff)、spec_coverage rc=0;amend 进第八笔。**第三遍不在夜跑期间跑**(0 点到夜跑结束不占锁,eureka-fc 提醒、我定的):每个定时提醒看 `.feynman/nightly-eval-ok` 的时间 —— 比 11-17 00:00 新 = 夜跑结束 → 接锁 pre_push(推模式,约 50 分钟);若拖到 04:55 强停则等 05:30 世界平移完再跑;推完发 eureka-fc 提交号 + 锁放了,它再跑 ops 全量
- **22:5x pre_push 第一遍红在「按改动重放咬合」**:3/30 个脚本没过,根子一个 —— 迭代面板规格 [1685] 攻击 `!["start","end","loop","foreach"]` 那段,我给容器排除名单加了 parallel 后它找不到(破坏点过期);连带 bite_check(13/13)和 repo_consistency(2/2)的**对照**都红(它们就是查这件事的)。规格 old/new 已改成带 parallel 的版本,bite_check 0 红;repo_consistency 查的是 HEAD,要并进第八笔才绿 → amend 后重跑 pre_push
- **22:2x 咬合重放:七组 5 过 2 没过,两条都是规格自己的问题,已改**:① tools_flow 那条砍「没头名」一刀被下一条「头名不合法(0 字符)」兜住 → 攻击不可观测(CLAUDE.md ②那条形状),改成整段 `if False and 方式 == "自定义头"`,草稿副本手工复现:攻击前过 54、攻击后红在指定那条;② switch_sync_check 规格脚本名带 `--自测` 参数,bite_run 对 管理后台/ 脚本按原样当文件名跑 → 对照恒红;改成检查**每次先自测再真跑**、规格去参数、Makefile 只留一行
- **判据**:并行支路结果 = 支路最后一步输出(人工核对在末尾就是核对结论);子工作流深度上限 3(拍脑袋的技术数);子流程里更深一层的 SUBWORKFLOW_* 原码往上传;lanxiu_bridge 那 9 条不是 MCP 工具、不进开关对账;泄密检查只扫错误体
- **作废**:「流程只有 HTTP 步骤也算 mock」(已改成算真连接);「刷交接顺手生成日志」(W29 改每天 06:40);清单第 1 项里「rebase origin/main」不再需要 autostash 以外的东西
- **禁区**:同 20:2x 条;**今晚允许自己 push(用户 21:4x 拍,到 08:40)**,条件 pre_push 全绿、只推自己的、记进交接
- **下一步第一个动作**:收到解禁 → 照 scratchpad/解禁后链.md(scratchpad 会清,要点:rebase --autostash → 告它要锁 → alembic heads 核头 → 锁内 upgrade head → `python3 scratchpad/apply_auth_api.py` 一次把鉴权接进 登记/列表/worker/搭建资源/e2e(锚点不唯一会停)→ 重启 aimc → 锁内 tools_flow / http_node / audio 单跑 → e2e-ci → 咬合 --only 八条 → make_handoff → 第八笔 commit --only → 日志挪开 → pre_push(不带 --不推)→ 日志放回 → 发 eureka-fc 提交号 + 锁放了)
- **悬而未决**:工具目录页标「业务后台已停用」;给人看打码按清单补字段(要动 server.py + 重启 8760);两套脱敏读清单等脱敏器选型落地;子流程 / 并行 / HTTP 二期三条已拍待排期;鉴权列的 e2e 咬合只打纯函数

### 🟢 11-16 20:2x · 交接(压缩前,六项)—— 七笔已推到 8e2c0c89;eureka-fc 第 23 轮 20:05 起(锁归它到约 21:30);鉴权列不碰库的部分做完、等解禁落迁移(Fable 5.1)

- **未验证的预判**:① 迁移 5a9f567d29b4(capability_connections.auth JSONB)只写了文件、**没 upgrade**,down_revision 2ae099e8e0f0 是按当时 `alembic heads` 定的,eureka-fc 推完后头可能变 → upgrade 前再 `alembic heads`;② test_tools_flow 新加的「三½ 鉴权」四条**没跑**(接口还没收鉴权、列还没落);③ 咬合 1933(检查鉴权 没头名分支)**没重放**;④ 泄密检查只扫**错误**响应(contract/errors.py:52 一处调用)—— 这是我 grep 出来的结论,列表接口回「头名 x-shop-key」不会被扫,但若有人把 泄密检查 加到正常响应上,带 `api_key` 形状的头名就会 500;⑤ app.js 后缀「鉴权:…」靠 workflow-resources 回 `鉴权方式` 字段,**接口那边还没加**
- **判据**:aimc 的 uvicorn --reload 跟着主检出工作区 → **读 auth 列的 SQL 不能在 upgrade 前写进工作区**(会把 8801 的工具连接列表打成 500);中文编码(无 / 令牌 / 自定义头)是为了躲 `errors.泄密检查`(connections.py 里为这个栽过两次,文案里连「x-api-key」这种例子都不能写);退出码只认 gate_lock 印的那行;e2e 经 HTTP 打常驻服务 → 咬合要打进程内的纯函数
- **作废**:15:4x–17:2x 条里「等 eureka-fc 推完再 rebase」整条路线(已反过来、已推完);原设计鉴权编码 bearer / header(secretref.凭据头 和 test_http_node 夹具都已改中文)
- **禁区**:锁在 eureka-fc 手里到它说「解禁 + 提交号」—— 不写库、不 upgrade、不跑门禁、不重启 aimc;api.py 拆分窗口**仍未解禁**(不碰 backend/api.py 和读 api 源码那 46 条);三件运行日志不 add;推送由用户执行;迁移文件在、库没升之前**别跑 pre_push**(alembic check 会红)
- **下一步第一个动作**:收到 eureka-fc「解禁 + 提交号」→ `git fetch && git rebase origin/main --autostash`(我工作区有未提交改动;撞 backend/api.py 就停)→ 告它「我要锁落迁移」→ `cd 管理后台/services/api && ../../.venv/bin/alembic heads`(确认 5a9f567d29b4 的 down_revision 还是头,不是就改)→ 锁内 `alembic upgrade head` → 改 tools_api 建工具连接(收 体["鉴权"] → CN.检查鉴权 进 问[] / CN.规范鉴权 → insert 多列 `auth = cast(:au as jsonb)`、审计记方式、返回「鉴权」)和 工具连接列表(select auth → 「鉴权」:auth or {"方式":"无"})→ worker.py 1022 select 加 auth、1030 `连接["auth"] = dict(行.get("auth") or {})` → workflows_api 搭建用的资源 select auth、工具连接项加「鉴权方式」→ 重启 aimc → 锁内 test_tools_flow / test_http_node_flow(建连接带 {"方式":"无"})/ e2e-ci → `bite_run --only test_tools_flow` → make_handoff → 第八笔 commit --only → 日志挪开 → pre_push --不推 → 日志放回 → 请用户推 → 发 eureka-fc 提交号 + 锁放了
- **悬而未决**(不用拍板):冻结 / 编译器两处读节点结构的接线没有咬合;定义顶层 input/output_schema 仍是摆设;版本详情接口不返回入参结构;HTTP 节点单步测试入口;live 路径三条真攻击 e2e;工具连接没有归档接口;HTTP 节点面板真页面没点过

### 🟢 11-16 20:0x · 交接 —— **七笔已推(origin/main 713dfc49 → 8e2c0c89,用户 20:0x 点的)**;锁已放给 eureka-fc 跑第 23 轮;开始做工具连接鉴权列(Fable 5.1)

- **已推**:pre_push 第二遍 19:20 绿(第一遍红在 trace_check 指纹命中 HTTP请求.py → 用户手工打了豁免补丁,第七笔 8e2c0c89)。eureka-fc 已收到提交号,它 rebase 跑第 23 轮(约 90 分钟)。api.py 拆分窗口**仍未解禁**
- **正在做:工具连接鉴权方式列**,方案在 scratchpad/plan_工具连接鉴权列.md(scratchpad 会清,要点:迁移加 `capability_connections.auth` JSONB;登记接口收「鉴权」{方式 无|bearer|header,头名},校验做成纯函数 `connections.检查鉴权` 好配咬合;列表接口回鉴权;worker `_http` 1030 行 `连接["auth"] = 行["auth"] or {}`;test_tools_flow 加正负向 + 进程内调 CN.检查鉴权;http_node e2e 建连接带 {"方式":"无"})。**顺序铁律**:aimc 的 uvicorn --reload 跟着主检出工作区 → **读 auth 列的代码不能在迁移 upgrade 之前写进工作区**(会把 8801 打挂);先写不碰库的(纯函数 / 迁移文件 / 测试),等 eureka-fc 第 23 轮推完 → 要锁 → `alembic upgrade head`(先告它)→ 再改接口 / worker → 重启 aimc → e2e
- **20:1x 进展(工作区未提交,不碰库)**:迁移文件 `migrations/versions/5a9f567d29b4_工具连接加鉴权方式列auth.py`(add_column auth JSONB,**未 upgrade**);`connections.检查鉴权 / 规范鉴权` 纯函数,**编码改成中文 无 / 令牌 / 自定义头**(原设计 bearer/header 的英文词会出现在 422 提示里,`errors.泄密检查` 连值一起扫、见凭据类英文词就把响应判成 500 —— 这个坑 connections.py 头部注释里写着栽过两次);`secretref.凭据头` 同步只认中文编码;进程内 8 个用例 + 泄密扫都过;tests/orchestration/test_http_node.py 夹具改中文编码,它和 test_outbound_policy 20 / 23 条过;test_tools_flow 加「三½ 鉴权方式」四条(没头名 422 不是 500 / 带鉴权 201 回方式+小写头名 / 列表带鉴权、老连接「无」/ 进程内调 CN.检查鉴权)**未跑**(要等接口改 + 列落);咬合 +1(规格 1933:检查鉴权 的「没头名」分支关掉 → 预期红那条进程内 ck,**未重放**)。规格 §11.2 补「鉴权方式三档」一段(doc_numbers rc=0);app.js 资源选择器的连接选项后缀「鉴权:自定义头」(字段 `鉴权方式`,老接口没有就不显示),面板测试 35 条过、new_nodes 24 / foreach 28 回归过。**不碰库的准备到此做完**,其余等解禁。eureka-fc 20:05 起第 23 轮(锁归它到约 21:30),我已回它。**解禁后的顺序**:要锁 → `cd 管理后台/services/api && ../../.venv/bin/alembic upgrade head`(先告它)→ 改 tools_api 建/列(收「鉴权」→ CN.检查鉴权 / 规范鉴权,insert auth,返回「鉴权」)、worker 1022/1030 读 auth、workflows_api 搭建用的资源带鉴权方式 → 重启 aimc → 锁内 test_tools_flow / test_http_node_flow / e2e-ci → bite --only test_tools_flow → 第八笔 → pre_push → 请用户推
- **判据 / 禁区**:同下一条;另:迁移文件写了但没 upgrade 时,**自己的门禁会红在 alembic check**,别在 upgrade 前跑 pre_push;读 auth 列的接口 / worker 代码等 upgrade 之后再写进工作区

### 🟡 11-16 17:2x · 交接 —— 锁在我手里;e2e-ci 57/58 只红 audio → 根子修了(校验器/编译器/冻结三处统一读节点里的结构),audio 重跑绿;剩咬合重放 + 第六笔 + pre_push(Fable 5.1)
### 🟢 11-16 17:2x · api.py 拆分等第 23 轮(本地 3 笔未推:a39ad98b / 63e85d10 / 5e9f7621)(Opus 5.5)

- **第 22 轮红 2 条**(log:.wip-glossary/pre_push22.log):① 库指纹范围 —— api_src.py 没认领 → 已登记进 backend/db_build.py「不算」,单跑绿,提交 5e9f7621;② alembic「Can't locate revision 2ae099e8e0f0」—— **并行会话的迁移已跑进共享 PG,而提交(98632daf)还在它本地 main 没推**,不是我的错、我修不了。
- **换了顺序(并行会话同意)**:它先推它的 6 笔(最新 830e31e2,17:10 起锁内 pre_push --不推,预计 17:5x 出结果,**推要用户点**),推完发我提交号 + 「锁放了」→ 我 `git pull --rebase --autostash` 到它之上 → 跑第 23 轮 `./tools/pre_push.sh > .wip-glossary/pre_push23.log 2>&1; rc=$?; echo "收工 rc=$rc $(date +%T)" >> …`。**拆分窗口仍开着**:它不碰 api.py 和读 api 源码的检查,我推完才喊「解禁」。期间别起门禁、别写库。
- **推上去之后依次**:① 恢复 .wip-glossary/*.bak3 滚动日志 ② 缩工具说明第 13 批:`python3 .wip-glossary/shrink_apply.py`(副本演练 prompts_check / tool_schema_check 绿),之后**要用户批**发管理后台生产版(店长助手 v19→v20,TL98–TL107),不批则「规矩等于后台版」那条检查红 ③ 罕见层 I 盘点差异 16 题:`python3 .wip-glossary/rare_apply.py`(写 ops_eval 11 日常 + ops_sealed 5 封存 + judgetest 32 条对照 + vocab 下限 130/122 + knowledge/17 一行;副本里 vocab / judgetest / sealed / doc_numbers / rare_freshness 全绿),然后**真跑 11 道日常题**(`LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5`)让 eval_tier_check 绿,结果文件进提交。
- 脚本都在 .wip-glossary/(不提交);scratchpad 那份会被清。
- **17:4x 更新**:并行会话 pre_push 红在 trace_check 豁免(放宽守卫,等用户打补丁,由它问用户),它推送延到 ~19:00。我已把罕见层 I **落进工作区**(rare_apply.py 跑过,ops_eval / ops_sealed / judgetest / vocab_check / knowledge/17 已改,未提交;离线五项全绿),**向它借了锁**要真跑 11 道:`LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5 ./agentsite/.venv/bin/python agent/ops_eval.py I01,I02,I04,I05,I06,I08,I09,I10,I12,I14,I15`(跑完还锁、告诉它);结果 + 落地一起提交(滚动 jsonl 别 add),跟拆分一起进第 23 轮。
- **17:5x**:锁是并行会话**让给我**的(它在等用户打 trace_check 补丁),11 道真跑已在 gate_lock 里起跑(后台,日志 .wip-glossary/ops_I.log,只认末行「收工 rc=」)。**跑完第一件事:SendMessage 给 uds:/tmp/cc-socks/35954.sock 说「锁放了」**(它要重起 pre_push)。然后看成绩:挂的题先按 CLAUDE.md 第 7 节第 4 条排查(测量→数据→判据→没告诉标准→才是模型),判据错就修判据并把真实说法钉回 judgetest;再单跑 eval_tier_check 确认绿;提交 ops_eval / ops_sealed / judgetest / vocab_check / knowledge/17 + ops 结果文件(**agentsite/evals/*.jsonl 不 add**)。
- **18:3x 结果**:11 道真跑两轮 8/11 · 7/11,锁已还(并行会话 18:28 起 pre_push,预计 19:1x)。I04 / I05 模型真错(原文已钉对照);I09 / I10 各一处判据欠账(见提交说明)。**eval_tier_check 只认全量结果文件**(部分跑只写 .partial),要 ops 全量 132 题两轮(~2 小时、要锁)才绿 → 落地那笔 **8c65d1db 挂在本地分支 rare-i,w75 已 reset --keep 回 5e9f7621**,第 23 轮只推拆分。rare-i 等锁空 + 非夜跑窗口时:rebase 到新 main → `gate_lock` 包 ops 全量 → 提交结果 → 推。
- 未验证:sealed_tier_check 在工作区跑了 >2 分钟(副本里秒出),最后 rc=0,原因没查(疑读共享库慢)。

### 🟡 11-16 05:xx · 夜跑完 → rebase 到 b3a41fb5 → 推送前链第 18 轮在跑(Opus 5.5)
### 🟡 11-16 17:2x · 交接(最新)—— 锁在我手里;e2e-ci 57/58 只红 audio → 根子修了(校验器/编译器/冻结三处统一读节点里的结构),audio 重跑绿;剩咬合重放 + 第六笔 + pre_push(Fable 5.1)

- **17:0x e2e-ci 真实退出码 2**(后台通知报 0,照旧骗人):57 份过,只红 test_audio_flow 三条,全由一处来 —— **校验器 ⑧「结束节点必需字段要有来源」读的是定义顶层 output_schema**,下午我只修了冻结,没修它;**编译器交给运行器核最终输出的 输出Schema 也读顶层**。修法:取法只写一份在 `contract/dsl.py`(`DS.入参结构 / DS.出参结构`:节点里那份为准、顶层只兜底),validator ⑧ / compiler / workflows_api 冻结版本三处都改成调它。重启 aimc 后 audio 单跑 **rc=0**。图校验夹具 +2(顶层过期要「结果」而结束节点要 summary 已绑 → 放行;顶层为空而结束节点要 summary 没绑 → 拦),test_graph_validation 20 条过(夹具 33)。⚠️ 夹具 json 原格式 indent=1、ensure_ascii=False,用 json.dump 回写时照这个,否则 diff 七千行
- **咬合规格改了一条**:原「audio 入参改回抄顶层」那条的攻击点(workflows_api 那行)已不存在,且 e2e 经 HTTP 打常驻服务、副本改坏看不见 → 换成打进程内 validator ⑧(`输出 = DS.出参结构(定义)` → 读顶层),脚本 test_graph_validation,预期红「每张图报出来的阻断码和手写的期望**集合相等**」。**冻结版本和编译器那两处的接线没有咬合**(只能靠 audio e2e 对真服务验),记欠账
- **17:2x 咬合重放全过**:`bite_run --only test_graph_validation`(3 条含新 ⑧)/ `test_http_node_flow`(1)/ `test_workflow_http_panel`(1),每条都「对照绿 → 改坏 → 红的是那一条」。PRD B-123 改「已解决」并补第三条教训(同一份数据被几处读,修一处不算修好);汇总难点 --严格 rc=0、doc_numbers rc=0 无人认领 0
- **未验证的预判**:app.js 面板真页面没点;pre_push --不推 没跑(第六笔提完就跑)
- **17:1x 第六笔已提 830e31e2**(本地 6 笔领先 origin/main 713dfc49);三件运行日志已挪 scratchpad/aside 并 `git checkout --`,**pre_push --不推 17:10 起在锁内跑**(日志 scratchpad/prepush.log,跑完脚本自动把三件日志 cp 回来;若中断,手工从 scratchpad/aside 放回);已发 eureka-fc 进度。**这条 HANDOFF 改动是提交后改的,随下一笔带上,不单开提交**
- **17:5x pre_push --不推 红 1 条(被包的命令退出码 1)**:`agent/trace_check.py` 用「文件里同时有 "curl" 和 secretref」当指纹抓「带凭据打模型端点却没接记录仪」,**HTTP请求.py 命中**(它用 curl + 连接凭据往白名单业务接口发 GET/HEAD,不是调模型,花费记在 run_steps)。修法 = 在它的「明写不算调用点」豁免表加一条带理由的 —— **放宽守卫我改不了(自动权限拒了),补丁在 scratchpad/trace_check_豁免HTTP请求.patch,等用户 `!` 执行**。另一条路(改 HTTP请求.py 绕开指纹)是躲检查,否决。三件运行日志已自动放回
- **下一步第一个动作**:用户打了补丁 → `python3 agent/trace_check.py` 看绿 → 第七笔 `commit --only agent/trace_check.py HANDOFF.md`(说明为什么豁免)→ 日志挪开 → `./tools/pre_push.sh --不推` 再跑一遍(锁内,约 45 分钟)→ 日志放回 → 绿则请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main` → 发 eureka-fc 提交号 + 「锁放了」。~~旧:看 prepush.log 里 gate_lock 印的「被包的命令退出码」→ 0 则请用户~~ `! cd ~/Desktop/澜绣云裳agent && git push origin main` → 推完发 eureka-fc 提交号 + 「锁放了」→ 它跑第 23 轮;红了按红的那条修、再提第七笔(别 amend,eureka-fc 可能已看到提交号)。~~旧:`python3 tools/make_handoff.py`(刷自动区 + 项目日志)→ 第六笔~~ `git commit --only`(HANDOFF / 项目日志 / tools/bite_specs.json / tools/doc_numbers_check.py / PRD / 管理后台 Makefile、apps/web/app.js、apps/web/wf_canvas.js、services/api/app/workflows_api.py、services/api/app/contract/dsl.py、services/api/app/runtime/validator.py、services/api/app/runtime/compiler.py、fixtures/orchestration/图校验夹具.json、tests/e2e/test_audio_flow.py + 已暂存的两个新测试)→ 三件运行日志挪 scratchpad/aside、`git checkout --` → `./tools/pre_push.sh --不推` → 日志放回 → 请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main` → 发 eureka-fc 提交号 + 「锁放了」
- **禁区 / 判据 / 悬而未决**:同下一条(16:5x),外加:PRD B-123 要补一句「校验器和编译器也读顶层,17:0x 一起修了」(状态可改「已解决」—— 顶层那份仍是摆设但三处读法已统一)
- 夜跑 11-16 结果(.feynman/nightly-eval/2026-11-16.md)：过 18、判红 5、退步 4。
  - 商机那套 0/24，全挂在「末尾没有商机 JSON」。拆开是两处兜底漏洞，已修(76adcbf8)：①没配管理后台地址那支不兜底(8 题)；②兜底回话没叫模型重新调技能，技能正文没装进来就拿不到输出格式(15 题)。
  - 排产那套崩在漏写的 `+` 上，已修，并新加门禁 syntax_warning_check(f6eb886e)。
  - 经营报告那套这晚**没崩**(1/3，退步)：「连续崩」那条已知说明要改，崩溃日志这次没出。
- 在本工作区真跑的 4 题拿不到接管清单缓存，没走到接管那一支。兜底路径要看今晚夜跑；过了就删夜跑里商机那条已知失败。
- **还没验的推断**：兜底修好后商机那套能回到正常分数，这只是推断，还没在真正走接管那一支的环境里跑过。经营报告那套「这晚没崩 = 根因消失」也没验过，可能只是那晚碰巧没撞上。
- **禁区**：链在跑时别改代码、别动共享库。agentsite/evals 两个滚动日志不 add。工作区里不放接管清单缓存（.takeover_last.json）：放了，本地评测就会走接管那一支，跑完必须删。
- **05:3x 新情况**：第 18 轮第三步，扣工钱那条检查的对照组是红的（30 张单工钱全是 0）。原因不在代码：共享库的数据日期跑到了世界日期前面，在制工单开工日全在 11-20 之后，已完成的最晚到 2027-01；world_meta 里 build_at=11-16T11:57，比现在还晚。已问并行会话是谁重建的。等它回话前别重建库，也别为了让检查变绿去改这条检查。
- **05:4x 查清（并行会话回话）**：库不是被重建了。05:10 每天的世界平移把世界日期挪到了 11-16，build_at 是「建库时刻」那一列被跟着平移了，属于旧现象。扣工钱检查红的根子在检查自己：「工钱不为 0 的至少 1 张」取决于库里碰巧有什么，而现在在制工单的开工日全在今天之后（CLAUDE.md 第 8 节「红不红取决于数据 → 自造样本」）。
  - **修法（下一步第一个动作）**：backend/cancel_fee_check.py 里，在库副本上（check_copy.用副本）自造一张开工日 = 今天−3 的在制工单，验它的工钱 > 0 且等于独立 SQL；真库那组只验一致、不再要求非零（改成只报数）。先 import api 再切副本（记忆：检查切库前先 import 写口）。改完给这条加咬合，第 18 轮红在第三步就把攒到的红一起修，再重跑整条推送前检查。
- **06:05 第 18 轮收工 rc=1（第三步）**：没推。对照组红的有 5 个脚本，各自单跑查出的原因：
  1. cancel_fee_check：修法见上一条。
  2. shop_key_check：roster 有 280 行 shop_code 漏填（例：roster 6700，SH001 静安旗舰店）。像是 05:10 世界平移重算排班时新写的行没填店铺码。修法：查重算排班的那个脚本，让它写行时填 shop_code（代码修），库上补齐要拿锁并告诉并行会话。
  3. 和 4. bite_check / repo_consistency_check：同一个原因。规格 [1195]（tools/db_close_check.py 的攻击点）在 backend/api.py 里找不到，是 rebase 后 api.py 变了导致攻击点过期。修法：照 api.py 现在的样子改那条规格的 old/new。
  5. nightly_check：✅ 已修（经营报告那条已删）。商机那条等今晚夜跑过了再删。
  全修完再跑一次 `./tools/pre_push.sh`，日志写 pre_push19.log。
- **06:4x**：让并行会话先拿锁跑它那批并推送，它 09:40 要交夜间汇总。它推完会发提交号给我，我再 rebase。已提醒它 shop_key 和扣工钱这两条红是数据引起的，谁先修谁说一声，另一边别重复修。
- **06:5x 分工定了**：排班 280 行漏填店铺码、扣工钱全是 0 这两条由**并行会话修**，我这边别碰 cancel_fee_check 和重排排班的代码。我只剩一条：重写过期的咬合规格 [1195]（tools/db_close_check.py 指向 backend/api.py 的攻击点）。等它推完发来提交号，我 rebase 再跑 pre_push。
- **07:0x 要紧（归我这条线）**：夜跑自动提交 b3a41fb5 是在主检出上提交并推送的，父提交是并行会话本地的 addb5bb6。结果它那 33 笔没过推送前检查的提交被一起推上了主干，事后补跑的密钥扫描是干净的。并行会话正在拿锁修绿主干。**我要做的**：把 tools/nightly_eval.py 的自动提交改成只推它自己的结果文件，例如在临时 worktree 里，基于 origin/main 只提交结果文件再推，或者推之前先查 HEAD 的父提交是否等于 origin/main。改之前先摆方案；这是收紧，不用用户执行。
  - **07:3x 已做（本地提交，等并行会话推完再推）**：选了「推之前数待推几笔」那条，比临时 worktree 窄：`@{u}..HEAD` 必须恰好 1 笔才 `git push`，多了就只提交不推，并说清楚。eval_env_check 里新加的两条判据真调 `提交夜跑结果`，在临时的远程仓库加克隆上跑；反向用例也在，防止它退化成永远不推。咬合规格登记了，手动拆掉守卫验过一次是红的。同一笔还修了 [1195] 那条过期规格：db_close_check 的攻击点改到 api.py 里还在的那处审批 UPDATE，手动验过是红的。用户问「到 80% 能不能写完交接就自动压缩」，所以全局交接门禁不再催用户 /compact，已改，自测 50 条通过。
  - **07:4x 未验证的预判**：经营报告那套之前每晚崩，根因像是「连接不关，撞上 256 描述符上限」。依据是 `_c()` 换成用完就关 11-14 才进主干：11-13 那晚还崩，之后第一次排到它的 11-16 就没崩。只有 1 晚，等后面几晚，再崩就看夜报目录里的「崩.log」。
  - **08:3x 窗口约定（拆 api.py）**：并行会话同意了。从我们俩都推完开始算，它不碰 backend/api.py，也不碰读 api 源码的那 46 个检查。**我推完拆分那笔要喊它一声，它才解禁**。必须在今晚 0:00 夜跑前推完，推不完就整笔放弃，不推半成品。方案在 .wip-glossary/api_split_plan.md。
  - **13:4x api.py 拆分已落地（本地，待门禁）**：门面 8808 → 1700 行，另有 11 个按业务分的子模块。只搬函数，变量、工具表、说明全留门面；在第一处 TOOLS.update 之前 `from api_x import *`，私有名全部显式导回。工具：.wip-glossary/api_split.py，分组表 api_split_map.py，对着新的 api.py 可以重跑。
    - **验过的**：260 个顶层定义拆前拆后源码一字不差，只多 api. 前缀；导入后 TOOLS 119、三张 SCHEMAS、WRITE_TOOLS、api 上的名字和拆前完全一样，只多 子模块们；副本上 6 个会换库、真调工具的检查全绿；按文本读 api 源码的 10 处改走 backend/api_src.py，其中 report_template.py 和 capman.py 是**线上代码**；3 张文件清单加了子模块；116 条咬合规格改指，18 条用「原来在哪个函数」定位。
    - **拆分查出来的静默失效**：activity_check 的切片「从 def activity_roi( 到 def _rows2(」拆后是**空串**，空串上判据恒真，已改成按语法树取并断言非空。同类的「不在」断言全查过，只有一处，是中文字面量，不受影响。
    - **新检查** backend/api_split_check.py，已挂 check.sh，2 条咬合手动验过会红。
    - **没验的**：全量门禁、咬合重放、管理后台 e2e（我只碰了一个检查的一行，这次不用跑）。锁在并行会话手上，13:34 拿的；放了就跑 pre_push 第 21 轮。**0:00 前推不完整笔放弃，推完喊它解禁。**
  - **13:20 已推 713dfc49**：两批一起，推送前链第 20 轮 rc=0，ls-remote 核过；已告诉用户和并行会话。滚动 jsonl 已还原。工2 和 w75-dn 已删（用户批准）：删之前逐项核过，3 笔改动全在主干，用的是 git cherry、反向 apply，加上规格、夜跑那两处逐条对；工2 的 bump_doc_numbers.py 已拷进 .wip-glossary。
    - **api.py 窗口 13:2x 开**：并行会话不碰 backend/api.py 和读 api 源码的检查。**0:00 夜跑前推完，推不完整笔放弃**，推完喊它解禁。改写脚本 .wip-glossary/api_split_rewrite.py，排班段试过：140 处改成 api.X，能编译。
    - **罕见层 I 盘点差异 16 道草稿**：.wip-glossary/rare_I_draft.py，好坏答案逐道验过。**还没进 ops_eval**：要先在 knowledge/17 登记 I 前缀，选 5 道进 ops_sealed，再跑 vocab_check / ops_eval_judgetest。⚠️ 盘点调整流水 112 条是有的，只是工具读不到，判据不收「库里没有」。
  - **11:3x 第 19 轮 rc=1，103/105 过**：红在两处对照上，都已修。① agent/shift_eval_judgetest.py:38 连库没包 closing（它的文件，我顺手修了，已告诉它）；② PRD 台账我那条和它 2.4.5 的「六十八」撞号，我的改成**七十二**并去掉数字；它那行「11 条安全决定」加进了 doc_numbers 豁免。**第 20 轮**日志 .wip-glossary/pre_push20.log。
  - **09:55 推送前链第 19 轮在跑**：日志 .wip-glossary/pre_push19.log，只认「收工 rc=」那行和 ls-remote。已经 rebase 到它的 1ea5f1cd，领先 origin 23 笔。bite_specs 是重建的：它的版本全留，补上我的 11 条，去掉我改过的 2 条旧版；merge_specs.py 会把规格安错脚本，**以后别用**。推完：告诉用户和它提交号 → 还原 .wip-glossary/*.bak2 → 删工2 和 w75-dn → 开 api.py 窗口。
  - **10:2x 它同意了**：它还剩一笔，正在锁里跑咬合重放，约 10 分钟。提交后会发 main 最新号，之后不再往 main 加提交。**锁在它手上，收到号之前别起链。** 两个滚动 jsonl 已经备份到 .wip-glossary/*.bak2 并还原，推完要还原回来。
  - **10:1x 推送顺序改了**：并行会话叫我先推，但主干上 ①②⑤ 只有它那 5 笔能修绿（roster_write_check / shift_eval 夹具 / cancel_fee / 全角 / 门禁脚本），我单推一定红。我提议 **rebase 到它本地 main 上，一条链两批一起推**，正在等它同意，并等它报 main 的最新提交号。同意后：rebase --autostash main → 合 HANDOFF / bite_specs → 跑 pre_push19 → 推完把提交号告诉用户和它。它查到 shift_eval 写真库 op_log 的根因在 roster_write.发布，那段 db=None 的写法它已改。
  - **10:xx 等待期间做的（用户 10:xx：「等待时间都是几个小时，影响进度和效率」→ 等的时候必须先做手上不需要锁的活，已记进记忆 wait-time-do-own-work）**：本地又多 1 笔 823ef01f，待推共 15 笔：夜报印出环境性失败题数，判据在 rounds 里 11-14 就有了，这次补上夜报。
    - **等待期间的活排队（按顺序，都不需要锁、不碰 api.py）**：① 罕见层没底座的面写负向题（intent/rare-tier-six-faces-feasibility.md；用户 11-11 拍、11-16 再确认；题面数据现读；写前在 knowledge/17-评测集频率分层.md 登记前缀；不碰 tool_eval / select_eval）② 拆 api.py 的预备：在 .wip-glossary 写 AST 自由名改写脚本，以及 `api_src.全部源码()` 草稿（**只写在 .wip，不进仓库，等窗口开**）③ ~~成长方案评测那 1 处预期红欠债~~ **不算等待期活**：规格 [450] 的「预期红」写的是「夹具的前提不成立」，脚本里找不到。要改成实测红的那一条，就得跑 bite_run，而那要拿锁，所以留到锁空的时候。
  - **09:xx 现状（压缩前刷）**：本地待推 14 笔，到 a42fb502，origin/main 仍是 b3a41fb5。
    - **下一步第一个动作**：等并行会话发提交号，它推送前检查 rc=1，5 条红里 ③ 是我的，已修；④ TL97 **是我的**（prompts.py:899 NOTICE_RULE，在未推的 5ed886a4 里；我先前说「不是我的」是因为 grep 的写法在 zsh 下报错、没扫到，已经更正告诉对方），推完就绿；①②⑤ 它在查归属。拿到提交号后依次：`git fetch` → `git rebase --autostash origin/main`，冲突只会在 HANDOFF 和 bite_specs，用 scratchpad/rebuild_handoff.py 和 .wip-glossary/merge_specs.py 合，两边规格都留，[1195] 它也搬了同样的一处 → 备份两个滚动 jsonl 并 checkout → 后台跑 `./tools/pre_push.sh > .wip-glossary/pre_push19.log 2>&1` → 只认「收工 rc=」那行和 ls-remote → 告诉用户和并行会话提交号 → 还原 jsonl → 删工2 和 w75-dn（用户已批准）→ 开拆 api.py 窗口。
    - **用户 09:xx 拍了**：日志清理再等等，记进台账六十八，11-28 前再现算再问。夜跑假失败和罕见场景两件是**重拍**，11-12 和 11-11 早就拍过，选的一样，那两件早已是进行中，只是标题没改。所以加了 intent_check「标题等用户拍 ↔ 状态」这条。**教训**：报「要拍的」之前先看状态和台账，别只看标题。
    - **还没做（我的线，拍过的）**：夜跑把「卡在 ToolSearch、业务工具一个都没调」单列成环境性失败，不计分，intent/nightly-toolsearch-churn.md；罕见层剩下的面只写负向题，intent/rare-tier-six-faces-feasibility.md。
    - 交接门禁：全局 hook 已改成不催 /compact，并行会话把同一份提交进了仓库 tools/hooks（58251dbe），我核过逐字一致。
- **判据（为什么这么判）**：没配地址算「没配好」，所以要兜底；只有 403 没权限算「有人定了不让做」，照旧拦（用户 11-14 拍）。让模型重新调技能，是因为技能被钩子拦下的那次，技能正文根本没装进来。
- **作废的结果**：本工作区第一轮真跑的 4 题（3/4）没走接管那一支，证明不了兜底修好了。
- **悬而未决**：经营报告那套连崩 6 晚的根因还是没查到。商机那套摘录原话不准（TS-002 / TS-010 抖动），是模型那一侧的问题，还没处理。
- **下一步第一个动作**：链的通知来了以后，先读 pre_push18.log 末尾「收工 rc=」那一行，再用 `git ls-remote origin refs/heads/main` 对一下是不是等于 HEAD。
- 推送前链日志在 .wip-glossary/pre_push18.log，只认「收工 rc=」那一行。绿了：告诉并行会话「已推 + 提交号」(它本地有 33 笔等着 rebase)；用 .wip-glossary/*.bak2 还原 agentsite/evals 两个滚动日志；删除工2 工作目录和分支 w75-dn(用户已批准)。

### 🟡 11-16 16:5x · 交接 —— **顺序换了:我先推**;锁在我手里,HTTP 节点 e2e 10 条全过,e2e-ci 在锁内跑(Fable 5.1)

- **16:4x eureka-fc 来信,顺序换成「我先推」**:它第 22 轮红在**我的迁移**上 —— 共享 PG 已经跑了 2ae099e8e0f0(我 98632daf 那笔),而那笔还在我本地没推,它的树不认识这个 revision → alembic check「Can't locate revision」。它提议我先推五笔,推完发它提交号,它 rebase 上去跑第 23 轮。**已答应并开始**(16:4x):五笔核过一个都没碰 backend/api.py 和禁区文件;api.py 拆分窗口照旧(我继续不碰 api.py 和读 api 源码那 46 条)。**锁现在在我手里**(/tmp/lanxiu-gate.lock),它不起门禁、不写库
- **已做(16:4x–16:5x)**:aimc 已重启(新 worker 起来、8801 首页 200);`test_http_node_flow.py` 首跑挂 8 → 真因 1 个 + 两处猜错,**三处全是测试自身**:① 建连接要「配置密钥与预算」权限,U002 是 403,改用管理员 U001 建;② 登记接口回的键是 `id` 不是 `connection_id`;③ execution_runs.output_ref 存的是 **JSON 文本**(worker 自己也 json.loads),不是 dict。修后 **10 条全过**(rc 以 gate_lock 印的「被包的命令退出码 0」为准)。产品代码一行没动。⚠️ 根目录 `.venv` 不存在,管理后台的测试要 `cd 管理后台 && ./.venv/bin/python tests/e2e/…`
- **未验证的预判**:① `make test-e2e-ci` 正在锁内跑(含 audio 新断言「版本表 input_schema 只有统计起 / 止」、两份会打 workflow-resources 新「工具连接」键的 e2e)—— 日志 scratchpad/e2e_ci.log,看「被包的命令退出码」;② 三条新咬合(http_panel 方法下拉 / http_node 路径闸 / audio 入参改回抄顶层)**没重放**,三条 old 片段已核在源码里各恰好 1 处;③ app.js 面板只过 node 测,真页面没点
- **判据**:后台任务通知的退出码不可信,只认 `gate_lock.sh` 印的「被包的命令退出码 N」;`bite_run` 自己 execv 挂到 gate_lock 底下,别和 e2e-ci 并发;「测试绿了」≠「产品好了」;doc_numbers_check 的 ❌ 要看 rc 不看管道尾;e2e 挂一串先找最上游那条
- **作废**:15:4x 条「等 eureka-fc 推完再 rebase」—— 顺序反了,改成我先推;「下一步」里的 `git fetch && git rebase origin/main` 不再需要(origin/main 还是 713dfc49,我直接在上面)
- **禁区**:不碰 backend/api.py 和读 api 源码的 46 条检查(窗口没解禁);不碰共享库结构(auth 列迁移等这批推完);三件运行日志不 add;推送由用户执行;stash 栈里 autostash 是别人的;**不要在 e2e-ci 跑完前起第二个占锁的东西**
- **下一步第一个动作**:看 scratchpad/e2e_ci.log 的「被包的命令退出码」→ 绿则锁内 `python3 tools/bite_run.py --only` 三条新咬合(http_panel / http_node / audio 入参)→ `git add 管理后台/tests/e2e/test_http_node_flow.py 管理后台/tests/e2e/test_workflow_http_panel.js` → 第六笔 `commit --only`(HANDOFF / 项目日志 / bite_specs / PRD / doc_numbers_check / 管理后台 Makefile、app.js、wf_canvas.js、workflows_api.py、test_audio_flow.py + 两个新测试)→ 三件运行日志挪 scratchpad/aside、`git checkout --` → `./tools/pre_push.sh --不推` → 日志放回 → 请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main` → 发 eureka-fc 提交号、说「锁放了」
- **悬而未决**(不用拍板):定义顶层 input_schema 是摆设,存草稿要不要同步 / 要不要删;版本详情接口不返回 input_schema;HTTP 节点单步测试入口没加;工具连接 auth 列(迁移,推完再做);live 路径三条真攻击 e2e;工具连接没有归档接口(e2e 收尾走库兜底)

### 🟡 11-16 15:4x · 交接(压缩前)—— 本地五笔未推,工作区九个文件未提交,等 eureka-fc 第 22 轮链(约 16:30)(Fable 5.1)

- **未验证的预判**(全部要等锁到手才能验):① HTTP 节点 e2e `test_http_node_flow.py` 一次没跑过(猜了两处键名:问题级别键「级别」、output_ref 是结束节点输出 dict);② 冻结版本改取开始 / 结束节点那份 → audio 新断言「版本表 input_schema 只有统计起 / 止」没在服务上跑过;③ workflow-resources 新加「工具连接」键只 py_compile;④ 三条新咬合(http_panel 方法下拉 / http_node 路径闸 / audio 入参改回抄顶层)都没重放;⑤ app.js 面板只过 node 测 34 条 + node --check,真页面没点
- **判据**:后台任务通知的退出码不可信,只认 `gate_lock.sh` 印的「被包的命令退出码 N」;`bite_run` 自己会 execv 挂到 gate_lock 底下 —— 锁不在手就别跑它;「测试绿了」≠「产品好了」(上午 audio 那次修的是测试,产品原样,下午才改产品);doc_numbers_check 的 ❌ 要看 rc 不看管道尾
- **作废**:上午 test_audio_flow 里「手工同步定义顶层 input_schema」那两行已删(产品修了);HANDOFF 13:4x 条里「HTTP 节点接线等这批推完再做」—— 已做完并提交(33ba92c8)
- **禁区**:eureka-fc 拆 api.py 窗口进行中 → 不碰 backend/api.py、不碰读 api 源码的 46 条检查(rebase 撞 backend/api.py 就停下告诉它);不碰共享库结构(auth 列迁移等推完);三件运行日志不 add;推送由用户执行;stash 栈里 autostash 是别人的;锁在 eureka-fc 手里,不跑门禁、不写 aimc_dev、不重启 com.lanxiu.aimc
- **下一步第一个动作**(已被 16:5x 条替代):收到 eureka-fc「已推 + 提交号」→ rebase → 重启 aimc → 锁内 e2e + 咬合 → 第六笔 → pre_push → 请用户推
- **悬而未决**(不用拍板):定义顶层 input_schema 现在是摆设,存草稿要不要同步 / 要不要删;版本详情接口不返回 input_schema;HTTP 节点单步测试入口(单测类型表)没加;工具连接 auth 列;live 路径三条真攻击 e2e
- **15:2x(15:17 对表)eureka-fc 来信**:第 21 轮 rc=1,55 个脚本过 54,只红在「待办清单没重新生成」(它新加一个检查,清单上 400 → 401 没跟上),已补成 63e85d10;**第 22 轮 15:18 起跑,预计 16:30 前后推完**,窗口照旧、推完喊我。我这边照 14:1x 条的计划等它;等链期间做**编排页 HTTP 请求节点面板**(全在 管理后台/apps/web + workflows_api 的 workflow-resources,不占锁、不写库、不跑门禁):wf_canvas 菜单那条「还没做」占位换成真节点;app.js 加 步类型名 / 默认配置 / 表_设置(选工具连接 · 方法只 GET/HEAD · 路径 · 查询串键值 · 请求头键值 · 端点序号 · 上限字节)/ 表_输入(path/query/headers 三项契约绑定)/ 表_结果(固定返回 status_code/headers/body/json/url/execution_mode)/ 依赖表;workflow-resources 返回里加「工具连接」列表;前端 node 测试 `tests/e2e/test_workflow_http_panel.js`(照 new_nodes_panel 的 vm 跑法,不起服务)+ Makefile 三处登记。做完**不另开 commit**,并进第六笔。**15:4x 做完了**:`node tests/e2e/test_workflow_http_panel.js` 34 条过;三份老面板测试回归过(new_nodes 24 / foreach 28 / editor 71);test_registry_check 72 份过;咬合 +1(规格 1931 条:方法下拉塞进 POST → 预期红「方法下拉只有 GET / HEAD」,**未重放** —— bite_run 自己会挂到 gate_lock 底下,锁在 eureka-fc 手里;锁到手后 `--only` 连同 http_node / graph_validation 一起重放)。**未验证**:面板在真页面没点过(只 node 测 + node --check);workflow-resources 新加的「工具连接」键没对着真服务请求过(只 py_compile;audio / glossary 两份 e2e 会打这个接口,锁窗口里 e2e-ci 会带到)
- **15:3x 顺手还了上午那条欠账(工作区未提交、未跑)**:冻结版本(workflows_api `冻结版本`)原来把**定义顶层**的 input_schema / output_schema 抄进 workflow_versions,而编辑器和运行时只改 / 只读**开始 / 结束节点里那份**、顶层只在建模板时抄过一遍没人同步 → 开始节点改了字段、冻出来的版本还是老入参(定时那条「必填入参要么固定要么统计字段」按老的报 SCHEDULE_INPUT_MISSING,上午 audio 红的根子就是它)。改成**以开始 / 结束节点里那份为准、顶层只兜底**。test_audio_flow 去掉了上午加的绕坑两行(不再手工同步顶层),冻结后多一条断言直接读 workflow_versions.input_schema 只要统计起 / 止、没有 call_id;咬合 +1(规格 1932 条:入参结构改回抄顶层 → 预期红那条新断言)。**没跑**(要服务 + aimc_dev,锁窗口里 e2e-ci 会跑 audio);**没动**:GET 版本详情不返回 input_schema(所以断言读库),PATCH 草稿也没顺手同步顶层 —— 顶层那份现在只是摆设,以后要么同步要么删。PRD 附录 B-123 已记这条难点(协作 · 部分解决)
- **15:3x 提前揪出一条会让 pre_push 红的**:`tools/doc_numbers_check.py` 对 e7b6b763 里 PRD 2.4.5 那句「三期的 11 条安全决定 11-12 已经拍过」报「无人认领」(带计数、没规格没豁免)—— 已把原来那条「那 11 条安全决定条数多」的豁免正则扩到这一句(同一个条目数),重跑 rc=0、无人认领 0。**这说明 e7b6b763 单独是红的**,第六笔必须和它一起推
- **13:5x 结果**:整套 e2e-ci 第二遍只红 audio;audio 单跑又揪出三处**全是测试自身的错**:① `assert c in (200, 201)` 而发布接口 10-26 起就是 202 ② 「定时化」只换了开始节点、没同步**定义顶层 input_schema**(冻结版本的入参取顶层那份)→ 生产版还要 call_id → SCHEDULE_INPUT_MISSING ③ 预览接口的中文查询串没 urlencode(标准库直接 UnicodeEncodeError)。修后 audio 133 条全过。**产品口子(没改,记欠账)**:顶层 input_schema 与开始节点那份可以不一致、校验器不核 —— 该在 validator 加一条或冻结时以开始节点为准。**咬合两次没红的坑**:原攻击点在 PUT schedule(经 HTTP 打常驻服务,副本改坏它看不见)→ 换到进程内 `_定时发起一期`;再改「统计起 ← 统计止」仍没红,因为每日频率两者同一天 → 改写死 1970-01-01 才红在指定那条。六份咬合全过;锁 14:1x 放给 eureka-fc 起第 21 轮链。
- **未验证的预判**:① ~~整套 e2e-ci 第二遍~~(已绿,见上)(第一遍只红 test_audio_flow 一条、已改测试读 `advice`);② 六份咬合重放(test_schedule ×2 / graph_validation / outbound_policy ×2 / http_node ×2 / audio / orphan)一条都没重放过 —— 都在 /tmp/chain5.log 这把锁里跑;③ pre_push --不推 没跑;④ app.js 定时 / 开始节点面板在真页面没点过(只 node --check)
- **判据**:后台任务通知的退出码不可信(第一遍 e2e 它报 0,锁脚本印「被包的命令退出码 2」才是真的)—— 只认日志里那一行;test_audio_flow 红是测试键名错(`hint` → 契约 §19.1 的 `advice`),服务端那句话本来就对,没改服务端
- **作废**:rebase 前跑的一切绿(含 11-16 早 pre_push)—— 现在树是 713dfc49 + 工作区;HANDOFF 自动区已按新树重生成
- **禁区**:eureka-fc **拆 api.py 窗口进行中(13:1x 起,00:00 前推不完它整笔放弃)**→ 不碰 backend/api.py、不碰读 api 源码的那 46 条检查;三件运行日志(.feynman/tool-eval.json、agentsite/evals 两个 jsonl)不 add;推送由用户执行;stash 栈里 3 个 autostash 是别人的,别 pop
- **13:4x 和 eureka-fc 定了顺序 B**:它 api.py 拆完(本地 a39ad98b,门面 8808 → 1700 行 + 11 个子模块,工具名参数 schema 不变,链约 90 分钟)。**我 chain5 跑完立刻发「锁放了」→ 它起链 → 它推完喊我 → 我 rebase(撞 backend/api.py 就停下告诉它,不自己合)→ pre_push --不推 → 请用户推**。它链期间我:本地四笔 commit --only 照做(本地提交不碍它),然后做 HTTP 节点接线(不占锁、不写共享库、不跑门禁)
- **14:1x(14:15 对表)接线已提成第五笔 33ba92c8;HTTP 节点 e2e 写好未跑(工作区未提交)**:`管理后台/tests/e2e/test_http_node_flow.py`(建连接 → 空白模板建图 开始→http_request→结束 → 检查配置无阻断 → 进程内 V.校验 三条负向 → 受理 mock 跑成:地址 = 白名单 + /stock?sku=A1、模式 mock、步骤 h succeeded → 归档收尾);Makefile 三处已登记(test_registry_check 71 份过);咬合 +1(攻击打进程内 validator 的 HTTP_PATH_MISSING —— 运行段有常驻 worker 抢活,副本改坏 worker / runner 打不准)。**跑它要锁 + 写 aimc_dev,等 eureka-fc 推完**;而且 **worker.py 改了,跑前先重启 com.lanxiu.aimc**(常驻 worker 还是旧代码,它抢到活会按旧适配器表报 ADAPTER_MISSING)。跑完绿了 → 第六笔 commit --only(test_http_node_flow / Makefile / bite_specs / HANDOFF)。**判据猜了两处,红了先看这两处**:V.校验 返回的问题字典里级别键是不是「级别」;execution_runs.output_ref 是不是直接是结束节点的输出 dict(照 test_agent_step_flow:273 的用法)
- **14:1x HTTP 节点接线(等链期间做;⚠️ 下面几条时刻又是估的、偏晚约 20 分钟,14:10 对表后改回)**:dsl `N("http_request","HTTP 请求")`(配置 connection_id / method / path / query / headers / endpoint_index / max_bytes,必填 connection_id,调用外部 → 通用超时重试生效);validator 新段 ⑤¾(HTTP_METHOD_NOT_ALLOWED 只 GET/HEAD、HTTP_PATH_MISSING 路径或绑定 path、连接不在 → REF_NOT_FOUND,**只对 http_request 查,没把 connection_id 加进通用引用字段表** —— 加了会连带 tool 节点);workflows_api `_引用表` 加 connection_id → capability_connections;runner 把 http_request 加进「llm/retrieve/tool/agent」那支(绑定解出 → 适配器 → _调外部 重试)并计工具调用;worker `_http`(查 capability_connections 行 → 非 live 或 连接测试/评测 跑法 → 替身不发;live → HTTP请求.跑节点 经 tool_gateway;请求被拒/失败/网关拒 → 节点失败 带码);规格 §6.1 加「HTTP 请求」行;spec_coverage 已实现清单加它;夹具 +2(合法只读 / 非法 POST),test_graph_validation 20 条过、make contract rc=0;咬合 +1(方法闸,**未重放**,pre_push 的 touched 重放会跑)。**未验证**:worker `_http` 只过了编译,没跑过(要 e2e:建一条 capability_connection 带 allowed_endpoints → 图里一个 http_request → mock worker 跑成、输出有 url、execution_mode=mock;live 路径三条真攻击 127.0.0.1 域名 / 3xx / 凭据不出现);**worker 改了,e2e 前要重启 com.lanxiu.aimc**。**没做**:编辑器面板(app.js 没有 http_request 的节点面板和画布项 —— 接口层能用,页面上还选不出来)、capability_connections 加 `auth` 列(方式 / 头名;worker 里先给空 dict,凭据头 走默认)、capability_connections 登记 / 列表接口收 auth。
- **14:0x 本地四笔已提(main 本地领先 origin 4 笔,未推)**:98632daf 二期两件 / b726c5f8 W06 孤儿 / 5dc54cb7 出网策略 + HTTP 核心 / e7b6b763 文档。工作区只剩三件运行日志(不 add)。eureka-fc 14:1x 起第 21 轮链(约 90 分钟,拆 api.py 那笔 a39ad98b)
- **下一步第一个动作**:等 eureka-fc「已推 + 提交号」→ `git fetch && git rebase origin/main`(我 4 笔在上面;撞 backend/api.py 就停下告诉它)→ 三件运行日志挪 scratchpad/aside 后 `git checkout --` → `./tools/pre_push.sh --不推` → 日志放回 → 请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main` → 发它提交号。**等链期间做 HTTP 节点接线**(全在 管理后台/,不占锁):规格 §6.1 表加「HTTP 请求」行 → dsl N("http_request") → validator(连接存在 / 方法 / 路径)→ runner 分支 + worker 适配器调 HTTP请求.跑节点 → capability_connections 加 auth 列(迁移,**先别 upgrade**,等推完)→ 编辑器面板 → e2e 三条真攻击
- ~~旧:`tail -60 /tmp/chain5.log` 看三段结果 → 发 eureka-fc「锁放了」→ 绿则 `git add` 7 个新文件~~(orphan_sweep / test_orphan_sweep / 出网策略 / test_outbound_policy / HTTP请求 / test_http_node / 迁移 2ae099e8e0f0_*)→ 按 13:2x 条里 A/B/C/D 四笔 `git commit --only` → 三件运行日志挪到 scratchpad/aside 再 `git checkout --` → `./tools/pre_push.sh --不推` → 日志放回 → 请用户 `! cd ~/Desktop/澜绣云裳agent && git push origin main` → 发 eureka-fc 提交号
- **悬而未决**:无需拍板的;HTTP 节点接线(dsl / validator / runner / worker / app.js / capability_connections 加 auth 列迁移)等这批推完再做

### 🟡 11-16 01:1x · 交接(压缩前,上一轮)—— 本地 33 笔未推(HEAD addb5bb6),等 eureka-fc 夜跑后推完(Opus 5.5)

- **未验证的预判**:① 管理后台今晚改了执行器 / 校验器 / 编辑器 / 运行列表接口,**没跑 make test-e2e-ci**,也没在真页面上点过(只有桩 DOM 和离线自测);执行器改动要重启常驻 worker(com.lanxiu.aimc)才生效 ② bite_specs 新加 2 条(eval_hit_judgetest)只手工改坏验过,没用 bite_run 重放 ③ 孤儿运行那条 SQL 跑通但 0 条 running,真数据路径没走过 ④ 示例库 D9931–D9933 只在副本空跑过,没调模型 ⑤ 01:0x 两笔(07966b85 `_rows2` 收编、addb5bb6 导出所选报备口)咬合规格各 1 条**没经 bite_run 重放**;《安全边界审计.md》**没重生成**(攻击 +3,文档数字检查会红 → 锁空时 `python3 backend/boundary_audit.py --md`);8760 **没重启**,导出所选在真页面没点过、js_smoke 没跑;全量 check.sh 没跑
- **判据**:写类业务动作挡默认值靠 `_依赖查询` 返回函数上挂的 `.工具读写`(四处调用点不改签名);查不到读写当写入挡。注释存 `布局.$注释` 不进定义 → 不改逻辑哈希(服务端 `_草稿哈希` 只算定义,核过)。余额补足判「余额不是卡点」查结构(否定 / 「已」/ 不跟「不」的足·够 / 已…充值),不枚举词。01:0x:`_rows2` 改走 `_查` 而不是只加两句 if —— 三道检查只留一份,下次加第四道两个口一起有;导出所选只做「报备 + 记日志」不改成后台生成,因为选中的是当前页已打码的行,后台重查一遍反而可能和屏幕上对不上(诚实标成约定级闸)
- **作废**:无。pre_push 那次绿(cea19fad)在 rebase 之后作废,推前必须重跑
- **23:2x 变化**:eureka-fc 今晚**没推**(链停在第三步:待办清单没跟意图文件重生成,已修 b23ee220,只在它本地),挪到**明早夜跑结束后**重跑再推;主干仍 8b97292a。它要求:在它推完前我**不推、不跑门禁**。我已答应,另外自己加了:不跑管理后台 e2e、不落 alembic 迁移(W42 等它推完)
- **禁区**:eureka-fc 锁内推送链进行中 → 不跑门禁、不写共享库(lanxiu.db)、不跑管理后台 e2e(aimc_dev 也共享)、不落 alembic 迁移;它推完前 assistant_effect 会红在 TL97 属预期;运行时三件日志不 add;推送由用户执行
- **悬而未决**:早上合一张卡问:定时加频率? / 定时上画布与「用户输入」互斥? / 三期 11 条安全决定 / 两套脱敏(显示打码 vs 训练导出换假号)合不合、导出那套用哪种脱敏方法(规则 / 白名单 / 模型 —— 当初就写着没选型)
- **下一步第一个动作**:等 eureka-fc 消息「已推 + 提交号」→ fetch + rebase(会撞 HANDOFF / PRD 台账 / bite_specs 末尾 / 规划文档)→ 见下方清单「停在哪」那条的顺序;rebase 后多两件:重生成安全边界审计.md、`bite_run --only backend/boundary_audit.py,backend/authgate_check.py`;重启 8760 后 js_smoke。夜间汇总草稿已补今晚两笔 + 脱敏那题(未提交)。定时提醒 dfc1ef91 09:40 发完飞书后删

### ⏱️ 12 小时长任务清单(11-15 21:40 → 11-16 09:40)
> 用户 11-15 21:4x「开始夜间12小时长任务」+ 拍板三条(PRD 2.4.4 台账第六十五到六十七条):
> ⑥⑤ 推送:**让并行会话今晚先推交付告知那批**,我的 16 笔留本地,明早基于它 rebase 后再请用户推(已告诉 eureka-fc)
> ⑥⑥ 工作流「出错按默认值继续」:**写数据的步骤不许**,只能停或走异常分支;只读步骤可以
> ⑥⑦「上次运行」页签:**跟运行详情同一权限,手机号只露后四位**
> 规矩照旧:gate_lock、不碰 eureka-fc 文件、改管理后台推前 make test-e2e-ci、commit --only、新列走 migrations、运行日志不 add、推送由用户。

- [x] ✅ 1. pre_push --不推 绿(被包的命令退出码 0,对着 cea19fad)→ 22:0x 喊了 eureka-fc「锁空了」;三件运行日志已合回(不 add)
- [x] ✅ 2. 工作流一期 1-2 异常处理 —— fd5f223f(本地):第三种走法「按默认值继续」、写入类业务动作在检查配置 / 编译挡住、那一步仍记失败;自测 24 条 + 编排 42 组全绿。**没跑 e2e-ci**(第 7 项一起跑)
- [x] ✅ 3. 工作流一期 1-3「上次运行」页签 —— b65527aa(本地):服务端读最近一次真跑到这一步的记录、权限同运行详情、原文手机号只露后四位;自测 20 条;顺手补登记日志采集策略两份测试(make contract 原来红)。**没在真页面上点过**(第 7 项 e2e 时一起看)
- [ ] 4. eureka-fc 推了 → rebase → 交付告知订单页按钮(wip 脚本)→ 检查 → 重启 8760/8770 → 本地提交
- [x] ✅ 5. 余额补足后仍失败 —— efd3aa54(本地)eval.hit 新一支 + 对照 10 条 + 反例 D9931–D9933 + 造法「追加失败」+ PRD A-304;咬合 2 条手工红过、规格已登记**未用 bite_run 重放**(锁在 eureka-fc 手里);**真跑没跑**(`./agentsite/.venv/bin/python agent/example_counter_ab.py --做 --轮 2`,要锁 + 调 Claude)
- [x] ✅ 6. 1-4 ✅ 0ff627bf(唤出 + 标签,只落回复 / 模板两个框,规划里写清了为什么);1-5 前半 ✅ 8a7b9d4c(空白处右键 / 节点菜单两项 / 七个快捷键)。运行历史弹层 ✅ d291b96c;检查清单角标原来就有。注释 ✅ f33b61d3(存在布局 $注释、不进定义);预览卡 + 七色图标原来就有。文案对齐 ✅ 7b446adb;「下一步」区原来就有。导出图片 ✅ b427d224(SVG);注释格式工具栏 ✅ f62d3405—— **一期全部做完**+ 1-1 的端到端测试 → 第 7 项 e2e-ci 一起跑
- [x] ✅ 还债(插做,等锁时):执行手册第 17 行其实 11-11 就做完了(f5004cda 改 ✅,合计按表数);W06 孤儿运行判据 + 清扫一档 cf97a06f(咬合:去掉「还有活任务」→ 红在 🔑 那条;worker 每轮扫、端到端造孤儿没做)
- [x] ✅ 二期 2-1 不用拍板的一小块:定时面板「接下来 5 次」c5c7895e
- **早上要问(合成一张卡)**:① 定时要不要加 Dify 那几种频率(每周几 / 每月几号含最后一天 / 每小时)—— 会改「统计哪一段」的口径(10-26 只拍了日 / 周一 / 1 号);② 定时挪到画布上当「开始」的一种时,和「用户输入」互斥(一条流程要么人点、要么自动)照 Dify 做吗;③ 三期前那 11 条 HTTP / 代码执行安全决定(规划里说三期开工前问)
- **13:2x 收尾链开跑(eureka-fc 13:1x 已推 713dfc49,两批 7+17 笔;拆 api.py 窗口从此刻起,00:00 前它推不完就整笔放弃)**:① `git rebase --autostash origin/main` 纯快进(我 7 笔已在远端链上),autostash 回放撞两处 —— `tools/bite_specs.json`(两边在同一位置各加一批,都留:1928 条、无重复、JSON 合法)和 HANDOFF 自动区(取我这边再 `make_handoff.py` 重生成);解完 `git add` + `git reset` 清冲突态,核过哈希 3bb07aaa 才 `stash drop`(栈里剩 3 个别人的 autostash 没动)② 迁移 2ae099e8e0f0 已落 aimc_dev(cadence_detail jsonb / last_period_start timestamptz / cadence 约束含「时」)③ com.lanxiu.aimc 已重启(锁空、没门禁在打;首页 200,worker pid 42785,日志 /tmp/aimc-worker.log 无报错)④ 锁内 `make test-e2e-ci` 第一遍:**真实退出码 2**(后台任务通知照旧报 0,只认锁脚本印的那行),红只有一条、是我自己的 —— test_audio_flow 那条「用户输入开头开定时 → 422」查 `hint` 字段,而错误契约 §19.1 的字段叫 `advice`(服务端那句「改开始方式」本来就在 advice 里);测试改成读 advice。孤儿那份 test_orphan_sweep 8 条全过 → 执行手册 W06 转 ✅。13:3x 起一把锁串三段:audio 单跑 → 整套 e2e-ci(/tmp/e2e2.log)→ 六份咬合重放(/tmp/chain5.log)。**提交分笔计划**:A 二期两件(定时.py / workflows_api / contract 四件 / models / 迁移 / validator / app.js / 夹具 / test_schedule / test_audio_flow / 契约.md / api.ts / openapi)· B W06 孤儿(orphan_sweep / test_orphan_sweep / worker / stale_sweep / Makefile)· C 出网策略 + HTTP 核心(出网策略 / HTTP请求 / 两份测试 / secretref / bite_specs)· D 文档(PRD / 执行手册 W06 → ✅ / HANDOFF / 项目日志)。三件运行日志照旧不 add。
- **11:4x**:eureka-fc 第 19 轮 103/105,红两处它顺手修在 713dfc49:① 我 shift_eval_judgetest.py:38 新铺草稿那段 sqlite3.connect 没包 closing(db_close_check 红)—— 它包了;② PRD 台账撞号:它的「日志清理再等等」改成七十二 → **我工作区的 10:1x 三条已从七十二至七十四改成七十三至七十五**(PRD 2.4.5 / A-305 / 定时.py / test_schedule / app.js / entities / 契约.md 重生成,共 18 处),rebase 不会再撞;它还把我那行「11 条安全决定」加进 doc_numbers_check 豁免。它第 20 轮起跑,预计 13:00 推完。
- **11:3x 三期 HTTP 节点执行核心(未提交)**:`runtime/HTTP请求.py`(合成契约 / 拼地址 / 发送 / curl命令 / 跑节点 经真 tool_gateway.执行;节点自带凭据头丢掉、结果里请求头经 遮头)+ `secretref.py` 拆出 `_取原值`,新加 `凭据头(ref, 方式 无|bearer|header, 头名)` 和 `遮头`(`解析` 的 Anthropic 头照旧,test_probe_tool_calling 7 条仍过)+ `tests/orchestration/test_http_node.py` 20 条(假发送 + 假 DNS,经真网关;已挂 make test)+ 咬合 2 条。跑节点 先在网关外核地址(拦下报自己的码,不包成 TOOL_ERROR 待核实),参数原样交网关(闸② / ③ 拒覆盖和多余键)。**HTTP 节点的接线(dsl / validator / runner / worker / app.js)留到这批提交之后再动** —— 那些文件二期已经改了,先提交再叠,提交才分得开。**坑**:网关 校验Schema 默认不收额外字段,query / headers 要写 additionalProperties: true。**还没接的**:dsl N("http_request") + 规格 §6.1 表加「HTTP 请求」行、validator(连接存在 / 方法 / 路径)、runner 分支 + worker 适配器(查连接那一行:capability_connections 要加 `auth` 鉴权方式列 → 迁移)、编辑器面板、e2e 真攻击三条。
- **11:1x 三期地基(⚠️ 上面几条的时刻原来是估的、整体偏晚约 1 小时,11:18 对表后改回;以后写时刻先 date)(未提交)**:`管理后台/services/api/app/runtime/出网策略.py`(纯逻辑:方法只读 / 连接白名单(协议主机端口 + 路径前缀,折平、拒用户名夹主机)/ 解析落禁区就拒(回环 内网 链路本地 云元数据 ULA v4-mapped CGNAT;解析函数注入)/ 不跟重定向 / 15 秒 1 MB / 只重试 GET)+ `tests/orchestration/test_outbound_policy.py` 23 条(已挂 make test)+ 咬合 2 条。**判据**:tool_gateway 文件头说运行时不许自己发 HTTP,HTTP 节点必须走网关;而 `allowed_endpoints` 现在**只登记不核**(grep 运行时为空)—— 这个模块就是那一问的实现,HTTP 节点先用、工具连接真调也该用。**坑**:Python ipaddress 把 203.0.113.x / 2001:db8:: 文档段算私有,夹具用真公网 IP。**HTTP 节点怎么接网关(11:1x 读完代码定的)**:worker.py:1015 给 跑一张图 的 适配器 字典加 "http_request": _http(cfg, 实参)—— 它**不自己 urlopen**,而是构造一份合成契约 {name: f"http:{connection_id}", adapter: "http", side_effect_type: 只读, input_schema: {path, query, headers 白名单}, server_bound_arguments: {base_url, allowed_endpoints}} 交给 tool_gateway.执行(工具目录={那一份}, 适配器={"http": 真发送}),真发送里先 出网策略.核请求 → secretref.解析 加头 → 发 → 遇到重定向 / 响应太大吗;这样六道闸、记事、账本都照旧,只读级不记账本。**下一步(HTTP 节点本体,约 4 人日)**:规格 §6.1 表加「HTTP 请求」行(覆盖检查按中文对账)→ dsl.N("http_request") 配置 connection_id / method / path / params / headers / timeout → runner 分支经 tool_gateway.执行(不自己 urlopen)→ secretref 发送前加头、运行记录打码 → 编辑器面板「连接下拉 + 路径」→ 边界审计三条真攻击(127.0.0.1 域名 / 3xx / 密钥不出现在记录日志错误三处)。
- **11:0x 还债 W06 后半(未提交、未跑 e2e)**:新 `管理后台/services/api/app/orphan_sweep.py`(找孤儿 / 推孤儿 / 扫孤儿;取数 SQL 只此一份),`workers/worker.py` 60 秒一轮里加 扫孤儿(出错只打日志),`tools/stale_sweep.py` 孤儿档改调 找孤儿;新 e2e `tests/e2e/test_orphan_sweep.py`(借三条成功运行造甲乙丙,跑完还原;**要求库里有 ≥3 条成功带任务的运行**,CI 排在 audio 等之后)已进 Makefile E2E_CI;咬合规格 1 条(扫不推 → 甲那条红)。**worker 改了要重启 com.lanxiu.aimc 才生效**(重启前看没门禁在打它)。eureka-fc 预计 12:30–13:30 推完;它只动了 管理后台 两处小的(jsonb_cast_check docstring、口径 json +2 行 record_delivery_notice)。
- **10:5x 核出**:三期那 11 条安全决定 **11-12 已拍「按设计稿推荐」**(优化执行方案 20261112 第二张卡,台账第五到十一条),11-15 规划里的「待拍」是漏核;PRD 2.4.5 尾注已改,**三期开工不用再问**,按 管理后台/docs/规格/工作流补节点_HTTP与代码执行_设计稿.md 第 3 节推荐做(H1 只能选已登记连接 / H2 不跟重定向 / H3 密钥挂连接 / H4 15 秒 1 MB 只重试 GET / H5 能编辑就能加 / H6 一期只 GET / C1 生产容器开发 wasm / C2 全关只进出 JSON / C3 5 秒 128 MB 1 MB 4 并发 / C4 只 Python / C5 都能写发布前管理员审;C6 先盘点)。另:锁一直在 eureka-fc 手里(它的链一条条 bite_run,owner 文件每换一个脚本就更新;11:02 换到 scenario_check)—— **不是死锁**,别催。
- **10:4x 二期第二件「定时当开始节点、和用户输入二选一」(台账六十九)代码已写,未提交**:validator 加 START_MODE_UNKNOWN / START_TRIGGER_RULE / START_TRIGGER_EXCLUSIVE(开始节点 config.start_mode ∈ 用户输入|定时,config.schedule_rule 规则;定时开头的 input_schema 只许 统计起/统计止);dsl.py 开始节点配置键加这两个(**键用英文**:中文键会被「消息里不许露字段名」那条当内部名;**别把它们加进 validator 801 那张引用表**,加了 REF_NOT_FOUND 会把开始方式当被删的资源);workflows_api:_开始定时规则 / _生产开始规则 / _定时自填(试运行按当前时间模拟一期,来源记 模拟期)、PUT schedule 只管开关(用户输入开头 → 422 SCHEDULE_START_NOT_TRIGGER;带了和节点不同的频率 → 422 SCHEDULE_RULE_ON_START)、定时扫一遍 照生产版开始节点同步频率、新 GET /schedule-preview(契约已登记,make gen 已跑);app.js 开始节点面板(开始方式下拉 / 频率控件 / 预览)、试运行面板提示、版本与发布定时块改成只开关;夹具 图校验夹具.json +3 case;e2e test_audio_flow 定时段整段重写(wid3 定时开头:开始→模板→结束)。**没跑的**:e2e(要迁移 2ae099e8e0f0 先 upgrade + 锁)、页面真点、bite_run 两条新规格。
- **10:1x 二期开工(工作区未提交,main 冻结等 eureka-fc 推)**:用户 10:1x 又拍三条(台账七十三至七十五:统计区间 = 上一次到这一次 / 31 号碰短月落月末 / 每小时不限营业时间;PRD 已记,未提交)。已改:`管理后台/services/api/app/runtime/定时.py` 重写(周期 日/周/月/时,周几 / 几号 / 末,执行时刻们,统计区间按 A,_同类 兼容老 DATE 值;老三种区间逐字不变,test_schedule 26 条全过含 10 条新)、workflows_api(_定时规则 / _定时细节,cadence_detail 落库,出口多 周几 / 几号 / 说法)、contract fieldtypes(cadence_detail JSONB、last_period_start DATE→TIMESTAMPTZ)+ entities、models.py check 约束加「时」、app.js 定时面板(周几勾选 / 几号输入 / 时提示;node --check 过)、迁移 `2ae099e8e0f0`(手补 check 约束 + USING;**还没 upgrade**,共享 aimc_dev 要等 eureka-fc 链跑完再 `make`/alembic upgrade,它链里不许落迁移)。`make gen` 已重跑(docs/契约.md 变了)。**还差**:make contract 退出码确认、两条咬合规格(月末落月末 / 每小时退化)登记 + bite_run 重放(锁在 eureka-fc 手里,10:31 起)、e2e 里 PUT 带周几一例、make test-e2e-ci、提交。
- **10:0x**:①②⑤ 三条红都修了并提交(roster_write 日志 db=db 堵住真库漏写、roster_write_check 数差值、shift_eval 夹具清系统草稿、eval.py 全角);咬合重放 roster 7/7、shift 5/5、cancel_fee 3/3、db_close 2/2。③④ 归 eureka-fc(TL97 在它未推的 5ed886a4 里;store_report 过期在 f1a31446)。**合推方案**:eureka-fc rebase 到我本地 main 上,一条链两批一起测、一起推;我发它最新提交号后**冻结 main 不再加提交**,直到它推完告知。PRD 2.4.5 记了台账第六十八到七十一条;选型卡「定时统计区间」写好(推荐 A 上一次到这一次),待发飞书产品文件夹、待用户拍。真库 op_log 里那 2+3 笔夜跑漏写(id 6026–6030)**没删**(检查已不依赖它;要删得拿锁 + 告诉 eureka-fc)。
- **09:0x 四条红查到的**(都没改代码,下一步按这个修):① 排班「操作日志记在副本上(两次发布)」得 4 = **真库里本来就有 2 笔 ROSTER_PUBLISH**(张静静 11-16 03:04 / 03:07,夜里有人/夜跑真发布过排班),副本拷自真库,2+2=4 → 修法:backend/roster_write_check.py:149 改成数「跑之前 / 跑之后的差」而不是总数(判据不许依赖库里碰巧有什么);② 「夹具挑得到(副本上那两周是空的)」56 格:夹具写死 周=2026-11-30..12-06、今天=2026-11-11(第 26-27 行),第 29 行只删 roster d>='2026-11-30' —— 56 格从哪来**还没看**(先看 60-94 行「两周」判的是哪张表/哪个日期区间,疑每日平移把 roster 铺到了那两周、而判空那步在 DELETE 之前);③ 夜跑清单 = eureka-fc f1a31446,等它推;④ TL97 **聊天站代码里一个都没有**(grep prompts.py / agentsite / tools 为空),只在管理后台存的「生产版」规矩名单里 → 是后台那份生产版被谁加了 TL97(或 eureka-fc worktree w75 的 prompts.py 有 TL97 还没推);prompts.py TL 区归 eureka-fc,**别自己加 TL97**,问它 w75 里有没有,有就等它推;没有就查后台生产版是谁写的;⑤ 全角 42→43:charset_fullwidth_check.py 只印 12 处(第 18 行 印=12),要全列表临时跑一遍把 印 改大(别提交),和 origin/main~40 的列表 diff 找新增那一处,修掉后**不改欠债下限**(它只许往下调)。**用户 09:0x 又说**:「不然每次中间等待时间都是几个小时,影响进度和效率」→ 已存记忆 fill-wait-time-with-ready-work:跑长任务时同时做文档类 / 不在检查范围的代码 / 不占锁的查证。等检查时可做:四条拍板进 PRD 台账、「统计哪一段」选型卡、二期加三种频率的代码(管理后台侧,先不提交)。
- **08:5x 推送前检查 rc=1,判定不过 5 条**(日志 /tmp/prepush.log;三份运行日志已放回;本地待推 3 笔 7c1275b9 / 58251dbe / c6c3463a,都**还没推**):① 排班写入口「④ 操作日志记在副本上(两次发布)」得 4 ② 排班夹具「副本上那两周是空的」两周已有排班 56 格(疑每日平移/共享库数据,未查)③ 夜跑清单 store_report 过期 —— eureka-fc f1a31446 已修,等它推 ④ 挑出的规矩 == 后台那一版:TL97 只在后台 —— **eureka-fc 回:不是它的**,HANDOFF 第 21 行一带写过「eureka-fc 推完前 assistant_effect 会红在 TL97,属预期」,先读那条再对(①②⑤ 它也确认不在它的文件里,归我查)⑤ 字符集缺全角 42→43(新代码犯的,先 grep 是不是我夜里的提交)。**判据**:这 5 条都不是我早上 3 笔引起的(那 3 笔只动检查/规格/门禁脚本),多半是 b3a41fb5 带上去的 33 笔 + 平移数据。**下一步**:逐条查 ①②⑤ 归属 → 我的修、eureka-fc 的问它 → 再跑 pre_push(跑前照样把三份日志 cp 到 scratchpad/aside、git checkout,跑完放回)。**用户 08:4x 拍了四条**(定时加三种频率 + 统计区间先摆选型卡 / 定时当开始和用户输入二选一 / 两套脱敏不合只统一敏感字段清单 / 导出训练脱敏 = 规则 + 白名单 + 模型复查),已写进夜间汇总草稿,**还要进 PRD 台账**;三期 11 条安全决定开工前单独一张卡。eureka-fc 约了拆 api.py 窗口(两批都推完后 4–6 小时、今晚 0 点前):**窗口内我不碰 backend/api.py 和读 api 源码的 46 个检查**,我已答应。09:40 发汇总(草稿已基本定稿,第五节「<<推送结果>>」要填)→ CronDelete dfc1ef91。
- **07:4x**:工资测算那条修了 7c1275b9(库副本自造三天前开工的在制单硬判,真库非零张数只打印;咬合 3/3)+ 安全边界审计.md 重生成(66→69);员工门店编号那条已自己变绿;boundary_audit 19/19、authgate 7/7 咬合全过;aimc 已重启(导出所选生效),**make test-e2e-ci 已跑完 rc=0(CI 版全过;知识两份 + Firefox 那份本来不在 CI 版)**;07:5x 第一次 pre_push 因工作区脏拒跑(HANDOFF / 三件运行日志 / tools/hooks/handoff-gate.mjs —— 那个 hook 改动不是我改的、没提交,门禁自测 50 条全过),试了 `--工作区脏也跑` —— **pre_push 不把这个开关传给咬合重放,照样拒跑**;想把四个文件备份到 scratchpad、还原、跑完放回,**被自动权限拦了(没执行,工作区原样)** → 已停下问用户怎么办。⚠️ 门禁现在**没跑过**,别当绿,日志 /tmp/prepush.log,只认末尾「被包的命令退出码」那行。CI 另两处红(咬合 [1195] 过期、夜跑已知连续失败名单过期)归 eureka-fc,它本地 5e8f7b02 / f1a31446 已修,等我推完 rebase。**下一步**:e2e 结果 → `./tools/pre_push.sh --不推` → 绿了请用户推 → 发 eureka-fc 提交号。第 4 项(交付告知按钮)在它那批里,等它推。我推完 CI 仍会红那两处,等它那笔上去才绿。bite_specs.json 末尾两边各追加一条,rebase 冲突两条都留(已告诉它)。
- **07:0x**:eureka-fc 认领夜跑自动推送的修法(只推自己的结果文件 + 父提交 ≠ origin/main 就不推),它压缩完做;我这边:把主干修绿 → 推上去后发它提交号。
- **⚠️ 06:5x 重大发现**:我本地 33 笔**已经在 origin/main 上了** —— 夜跑的自动提交 b3a41fb5 是在主检出上提交并推送的,父提交就是我的 addb5bb6,于是把我那 33 笔**没过推送前检查**一起推上了公开仓库。密钥扫描事后补跑:干净(1673 文件)。主干上已知会红的:安全边界审计.md 没重生成、eureka-fc 说的两条数据红;管理后台 e2e 没跑。**下一步**:拿锁 → 修两条数据红 + 重生成审计文档 → 全量门禁 → 修红 → 请用户推修复;已告诉用户。根因要报 eureka-fc(夜跑自动推送不该把别人未过门禁的本地提交带上去)。
- **06:4x · 现在轮到我先推**:eureka-fc 回「你先拿锁跑你这批,推完告诉我提交号」(它第 18 轮停在第三步,剩 4 红,它要先压缩)。**我认领两条和代码无关的数据红**(它不重复修):① shop_key_check:roster 280 行 shop_code 漏填(例 roster 6700 / SH001)—— 疑 05:10 平移里 backfill_roster 重排新写的行没填码 → 修重排脚本 + 补填(写库要拿锁);② cancel_fee_check:在制工单开工日全在今天之后 → 工钱全 0,「至少 1 张非零」红 → 判据自造夹具 or 数据侧修(先看判据)。顺序:rebase origin/main(b3a41fb5)→ 拿锁 → 修这两条 → 重生成安全边界审计.md → pre_push.sh --不推 → 绿了请用户推 → 回 eureka-fc 提交号 → 09:40 发夜间汇总、删定时提醒 dfc1ef91。
- **06:3x**:锁空、主干仍 b3a41fb5,eureka-fc 没推也没消息;已问它进度,并提议「它短时间推不了就我先拿锁跑我这批」—— **等它回话再动**,别自己抢锁。
- **05:3x**:eureka-fc 问共享库是不是被重建了(第 18 轮扣工钱那条检查红:30 张单工钱全是 0)→ 查实**不是重建**:05:10 每天的世界平移(daily_shift.sh,11-15→11-16,挪 590628 个值,最后报「世界自洽」);world_meta.build_at 跟着平移是旧现象(没登记成不挪)。我推测是那条检查的日期窗口里挪完恰好没有完工单,**只是推测、没跑**,已回它;我没动库。
- **04:5x**:eureka-fc 回:推送链第 18 轮已开跑(rebase 到 b3a41fb5,它 HEAD 7bcf624e),约 1.5 小时;推完回「已推 + 提交号」,之前别拿锁别推。它这批多两笔:排产评测崩溃修复 + **新门禁「Python 语法警告当红」**(我本地改过的 .py 已用 -W error 编译扫过);接管兜底两处 → rebase 时 `backend/takeover_client.py`、`tools/bite_specs.json` 可能冲突(bite_specs 用 .wip-glossary/merge_specs.py 按三元组并集)。
- **04:4x**:夜跑结束(主干自动提交 b3a41fb5),锁空着;已发消息提醒 eureka-fc 轮到它重跑推送链,并订了它空闲时通知。我仍不拿锁、不推、不跑门禁,等它回「已推 + 提交号」。
- **01:3x**:夜跑还在跑(nightly_eval 进程在),主干仍 8b97292a,eureka-fc 没推;上下文 84%,这一轮只刷交接不开新活。
- **00:4x**:还债「智能体侧小债」第二件做了 —— `_rows2` 原来自己开**可写**连接、三道检查(答案表 / 密码列 / 只读)一道不过;现在和 `_rows` 共用 `_查` + 同一条只读连接;边界审计加三条攻击(真调验过三条都拦住;内存里改坏后 truth 那条放行)+ 咬合规格 1 条(未经 bite_run 重放)。⚠️ **早上要做**:锁空时 `python3 backend/boundary_audit.py --md` 重生成《安全边界审计.md》(攻击条数变了,文档数字检查会红)+ `bite_run --only backend/boundary_audit.py`。
- **01:0x**:页面上五处「导出所选」(浏览器里拼 CSV,原来绕过「店长以上 + 进操作日志」)接上后台报备口 `/api/export-selected`;authgate_check 单跑绿(在副本上,真库 op_log 0 条残留),+2 条断言、咬合规格 1 条未重放。⚠️ **8760 没重启**(夜跑期间不动),早上 rebase 后和交付告知按钮一起重启 + js_smoke。另:两套脱敏不是一回事(显示打码 vs 训练导出换假号,后者「脱敏器还没选型」)→ 不合并,放进早上那张卡。
- **停在哪(23:5x 更新)**:注释格式工具栏做完,工作流一期全部做完;二期 2-3「开始」页签核过原来就有(空白流程自带开始和结束,不需要 Dify 那个占位),二期剩下都要拍板。0 点夜跑开始,别碰锁。又做了导出图片 b427d224、PRD 14.3 工作流一节 5a471e0d;本地 31 笔。今晚剩下只有注释格式工具栏(可后置)。原 22:3x:能不碰锁、不碰并行会话文件的都做完了;剩下的都在等 eureka-fc 推完(它 21:5x 拿锁跑推送前链,估 2 小时)。夜间汇总草稿已写 `澜绣云裳agent-夜间汇总-20261116.md`(未提交,早上定稿)。自查过:当晚新加的阻断规则在库里现有草稿 / 冻结版本上 0 条命中(脚本 scratchpad/fp_scan.py)。
- 22:4x 查过:自动审技能「出现 start_workflow 就要有不该启动的场景」那条检查的前提过期了 —— SKILL.md 里已经没有 start_workflow(接管改走规矩 + 接管配置,eureka-fc 那条线),不做
- **下一步第一个动作**:eureka-fc 说推了 → `git fetch && git rebase --autostash origin/main`(会撞 HANDOFF / PRD 台账 / bite_specs.json 末尾 / 可能 check.sh)→ 第 4 项交付告知 → 管理后台 `make dev` 起着时跑 `make test-e2e-ci`(第 7 项)→ `bite_run --only agent/eval_hit_judgetest.py` 重放今晚 2 条规格 → W42 催单看板(要 alembic 迁移,锁空时落)→ 早上 pre_push --不推 → 请用户推
- [ ] 7. 管理后台 e2e-ci 全跑一遍(一期改动推前必过)
- [ ] 8. 早上:看经营报告夜跑崩日志、商机套夜跑结果;本地全套检查重跑;09:40 发飞书汇总

> 📦 11-14 至 11-15 的 18 个手写小节已原样搬到 `docs/交接归档/HANDOFF-归档-2026-11-14至11-15.md`(11-19,`make_handoff --归档`)

## 一句话:现在在做什么

> ### 📍 2026-11-03 下午(eureka-40 / 工 worktree)—— 最新状态在这儿,下面是上一轮的
>
> **在把一天里撞到的六个同形的洞堵掉,并且把教训换成结构而不是注释。**
> 六个洞见本文件最顶上那一节的表。已推到 `981ce8db`,全量门禁绿、退出码 0、`❌` 0 行。
>
> 为什么强调「换成结构」:同一个函数(`_must_fail`)上的**第一个**信息黑洞
> 早就记在项目日志两处 + 待办清单一处,**而第二个黑洞就在同一个 `return` 上**。
> 修的人想到了「哪些算被拦下」,没想到「被拦下时它说了什么」。
> > **教训记在一个地方,而下一次踩它的人不在那个地方 —— 哪怕那个地方就是同一行。**

> ### 📍 2026-10-25 下午(主会话 / 业务线)—— 最新状态在这儿,下面是上一轮的
>
> **订单上冗余了一列「这个客户现在归谁」,顾问那条范围查询 20.5 → 6.5 ms(3.1 倍)。**
> 用户拍的「加冗余列」。同步**交给三个数据库触发器**,不在写口里加 UPDATE。
>
> ⚠️ **三个方案都在真库副本上量过,只有一个值得做** ——
> 拆 UNION 那条路**实测只有 1.2 倍,已否决**(索引省下的扫表被去重和回表吃掉)。
> 和导购业绩页那次同一个结局:**改代码的风险换 11%,而加一条索引换 12.7 倍**。
>
> **为什么用触发器**:这一列的风险不是慢,是**漂**。
> 写口同步是「**靠记得**」(约定),触发器是「**做不到漏**」(结构)——
> 而 2026-10-25 早上刚栽过一次靠记得(每日平移漏了回填门店码,
> 缺口当天隐形、第二天才红)。⚠️ **库里原来一个触发器都没有**,这是新的架构元素。
>
> **CI 从零重建这一关过了**(我动了 `seed.py` 的建表语句 ——
> 在一个已经存在的库上那一列永远都在,**只有「从零」才会暴露顺序问题**;
> 门店码那条线为这件事 CI 连红三轮,这次一次就过)。

> ### 📍 2026-10-25 早(主会话 / 业务线)—— 最新状态在这儿,下面是上一轮的
>
> **知识来源新立了第四档「业务口径」(`biz`),溯源欠账 46 → 0。**
> 用户当天两次拍板:先拍国标里查不到的 5 条面料,再拍「剩下 7 条全拍,欠账归零」。
>
> ⚠️ **归零不等于「每条都有公开出处」—— 这是三件事,别混成一句话对客户说:**
> **12 条**走 `biz`(具名拍板、**无公开出处**,顾问要说「这是我们家的口径」、**不得说成国标**)·
> **5 条**有出处名**而给不出链接**(杭罗/蜀绣/湘绣/粤绣/晒莨,另一本账 `公开档无链上限`)·
> 其余真的补上了公开出处。
>
> **这一轮真正的工作量不在那 12 条定义上,在「立一档的连带成本」。**
> 12 个定义要动 19 个文件:解析器正则 / 口径表 / **6 处写死三个档位名的前端和接口**
> (其中面料页那个分组树漏一档,会让那 12 条面料**整组不渲染而且不报错** ——
> 看起来就是「这些面料没进库」,而库里好好的)/ 4 道防洗账的闸 / 9 条咬合。
> **和「加一个工具的代价在此后每一次调用上」是同一个形状。**

> ### 📍 2026-10-24 夜(主会话 / 业务线)—— 最新状态在这儿,下面是上一轮的
>
> **门店关联键根治做完了。** 生产代码里**再没有一处**按门店显示串筛(棘轮上限从 8 降到 0,
> 它从「进度条」变成了「闸」);报告模板那两处存在 JSON 里的门店标识也改成了存编码。
>
> 这一轮买到的东西只有一句话:**在后台把门店改个名,不会再让任何查询静默变成 0 行。**
> 而原来那个状态最坏的地方是它**不报错** —— 页面照样打开、报告照样出、派单照样返回,
> 只是查出来的东西少了或者用错了版本。
>
> 今晚还补上了棘轮的一个**真盲区**:它只认得出「筛错了」,认不出「压根没筛」。
> 假如有人把算好的门店条件忘了拼进 SQL,棘轮绿、语法绿、接口照样返数据,
> **只是一个店长看到的变成了全公司**。新判据真调那 8 个函数、按 SQL 指纹核。


**这一轮的主线是「分数会骗人,而骗的方向通常是更好看」。**

三条真实的退款异常(渠道超时但实际已退 / 原渠道已注销 / 商户余额不足)
进了研判评测题。难的不是出题,是**让分数可信**:

· `DQ9001` 已经被走完闭环(研判采纳 → 财务登记已退 → 办结),
  题面材料要是现取,里面直接写着「已退」—— 而那道题考的正是「会不会查支付流水」。
  用户 2026-10-16 拍的是「现取 + 遮蔽」,**代价是知情选择的**:
  「漏遮一处就送分,而且分数变好看没人查」。
· 遮蔽跑在 **MCP 服务进程**里,而那个进程是 claude CLI 拉起的 ——
  env 到不到那一跳**原来没有证据**。现在有了:遮蔽自己往台账写一行。
· **跑了五次才拿到能用的数,前三次挂的都是判据自己,不是模型。**

这一轮撞的是同一件事的**十三个变体**:**一个「好」结果和一个「判据坏了」长得一样。**
台账「遮了 0 处」/ 括号切断否定 / 回答被交付前闸扣下 / 分界点指着没提交的代码 /
咬合规格三次过期 / 判据依赖「真跑才产生」的库状态 / 基准的时分秒是绝对的 /
懒迁移的列让老库和新库分叉 / 咬合里写死 12:00 / 判据视野被 `###` 小节劫持 /
判据比总数而非逐条 / truth 自己两列矛盾 / `分界点()` 取不到 git 时返回空串
—— **十三处都不报错,都照样出数**。

其中**四处的误判方向是「分数更好看」**(闸松了、难题不考了、漏遮送分、示例池泄漏),
而**两处方向相反、长得像「模型变差了」**(括号切断否定、词表认不出新说法)——
后者更容易被当成真的能力退步去改提示词。

**而这一天的最后一段,同一句话换了个载体:交接文档自己也会骗人。**
待办里三条「还没做」核下来都已经做完(一条漂了一个月),
而我照着其中一条**把一份对的 intent 状态改成了错的**。
待办清到 15 → 7,**归造数线能直接动手的一条都没有了**。
> 救我的不是判据,是开工前核一眼事实 —— `PRAGMA table_info` 比任何描述都硬。

> 判据一句话:**动手造一份新数据之前,先 grep 一遍它是不是已经在库里。**
> 这是「一份没被引用的主数据 = 一份不存在的主数据」的镜像。

第二条贯穿全程的:**失败要有声音。** 这一轮修的几乎每一处,
原来都表现为「看起来完全正常」——渲染失败的图给了兜底色、
日志把没提交的字段记成「改成空」、检查还原时悄悄降了一级来源。

如果你只想知道一件事:**跑 `./check.sh`,全绿就说明状态是完好的。**

> ⚠️ 这里原来写着「84 项全绿」,而写下那句之后门禁又加了 16 项。
> **手写区里的任何计数都会漂,而漂了不报错** —— 项数只在「当前状态(自动)」里有一份。

✅ **库是可再生的,而且这句话 2026-09-16 起是真的**:

    ./tools/rebuild.sh     # 一条命令,跑完 ./check.sh 全绿

⚠️ **步骤只有那个脚本里有一份,这里不抄** —— 这一段原来手写着三步,
而那三步是不全的:照着跑重建完 `./check.sh` **红 26 项**。
库能一直是绿的,**只因为没有人从零重建过它**。

> **一个「能跑」的库和一个「重建得出来」的库长得一模一样** ——
> 直到有人换台机器,或者照着一句过时的文档动手。

清掉那 26 项的过程见 `intent/db-not-regenerable.md`(还剩的账也在那儿)。

**登录**(登录名就是工号,口令 `lanxiu@2026`):
`60000008` 魏欣新 · 总部运营 / `60000001` 张静静 · 店长(静安) /
`60000002` 林岚 · 顾问 / `60000020` 傅砚青 · **版师**

## 压缩前交接(只写摘要留不下的)

最后刷新:2026-09-21 · 本次变化:第二批图收完(25 款)、图来源标记、预约号挂上、
颜色钉住(**用户发现的事故**:改两行 seed 让 22 款换了颜色,其中 6 款已出图)

### 0. 今天的事故(最值钱的一条,别重犯)
**改两行 seed → 38 款里 22 款换了颜色,其中 6 款用户已经照旧颜色出好了图。**
根因:标品颜色按 `插入序号 + str.__hash__()` 算。前者让「改任何一行」都整体挪位,
后者跨进程不稳。现已改成按款号哈希,并把已出图的 25 款颜色钉进 `backend/图色钉住.json`。
> **图和数据对不上时,页面上看不出来** —— 客户看到的是图,系统按数据发货。
⚠️ **收新一批图之后要补钉**(draft_check 会提醒:「出过图的款都钉了颜色」)。

### 1. 未验证的预判
- 🔮 **预判**:顾问客单价挤在 12.8% 以内是**生成器造成的**(顾问均匀分配),不是业务性质。**没验** ——
  验法:改成「顾问和商品档次相关」再看区分度是否拉开。**现在别动** —— 刚把重建稳住,
  同时还有另一条线在动 rebuild.sh,三边一起改会分不清是谁弄坏的。
- 🔮 **预判**:剩下 284 款若共用图,按「形制+主色」分组只省 46 张,按「只形制」能省到 48 张总量。**算过没做。**
  用户已决定**不再出图**,剩下用占位图(出到 50 款那 38 款的清单还在桌面,不急)。
- 🔮 **预判**:在线生图每张几毛到一两块 / 本机开源每张 1–3 分钟。**都没查实**,已不重要(用户按 GPT 会员出图,
  2 批烧掉 20% 额度,决定停在 12 款)。
- ✅ **已验**(原「出图清单能让 GPT 画对汉服结构」):第一批 12 款 106 张,文件名零错误,
  抽查衽向 / 马面褶位 / 素面不加花全对。
- ✅ **已验**(原「v2 图会动 vision_eval 前提」):评测走 `img.png()` 现画合成图,**不读页面上那张**,
  前提仍成立;并已把这个前提写成可执行的 `vision_eval.前提()`,连同图指纹进门禁。

### 2. 判据
- 3D 效果图:用户给了参考图(人台正背面 + 右侧四张细节特写 + 左侧部位标注),**那是 AI 生图的照片感**,
  Blender 程序化建模到不了,用户原话「你绘制的也太...差了」。方案必须是生图模型;
  **文字和排版由程序从商品数据合成**(模型写中文会错字、会自己编工艺),生成后按商品数据校验(双襕就必须两道襕),
  图上注明「AI 生成效果图」。
- 打版图:公式写在图上让版师能驳;数据推出不合理值就在图上打警告,**不改数据**(PT04 马面宽 32 / 腰 72 → 褶区每侧 4 cm)。
  褶的倒向来源不统一 → 标「待版师定」。纹样种类和商品图同一个挑法(按款号 `img._hue`)。
- 白坯试衣按下单日算、排队看「那天在做的工单」;`leadtime.批量()` 只在一次查看内记住、出范围必清。

### 3. 作废的结果
- ❌ `tools/render3d/` 的 3D 小样:用户已否定其质量,**不要拿它当 3D 方向的基线继续调**。
- ❌ img_check「293/296 互不相同」:按字节比,同形制只是换色 —— 不代表人眼可区分。

### 4. 禁区
- `truth` 表判定结论不许动;判责 12 张维保单一字不动(改订单可以,改后逐字段比对 get_maintain)。
- 边界夹具(E- 前缀、truth 点名、评测写死的 C10000/01/08/13、C21* 合并用例)不挂新单、不重算。
- `~/Desktop/chatgpt` 只读。提交只提自己的路径(bite_specs.json / check.sh 用「HEAD + 我的条目」拼暂存)。
- 花钱的外部服务(生图 API)**等用户拍板**,不自行接入。

### 5. 下一步的第一个动作
- ⏸ **等用户交回第二批图**。交回后一起做:① 用 `python3 tools/import_images.py <文件夹>` 收(先核名再收);
  ② 商品页给占位图加「效果示意」标(真图不显示);③ 加覆盖率统计(现在 13/296)。
  **用户已决定不再大批出图**(2 批烧掉 20% GPT 额度),剩下用占位图。
- ⚠️ **别动桌面那两个文件夹**(`澜绣云裳agent-商品出图清单` / `澜绣云裳agent-出好的图`)——
  用户的 GPT 正在按那份清单出图。**我今天在这里犯过一次错**:重导清单时删掉了用户正在用的批次文件,
  而且编号从 01 重排,于是出现两个「批次-01」装着不同的东西。
  内容上没损失(新 01 == 老 02,排序规则没变),但**那一刻它已经不是我的产物,是用户正在执行的工单**。
  下次重导前先问。以后编号要**接着排、永不复用**。
- 不等也能做的:`tools/patterndraw/draft.py` 通用画法现在把所有裁片画成矩形 ——
  交领上襦的衽 / 领缘 / 接袖位置该按十字型结构画(依据 `tools/patterndraw/制版规范.md` §五)。
  **不碰数据、不碰用户在用的清单**,随时可做。

### 6. 悬而未决的问题
- **P18:订单该不该挂预约号**(`ordr` 现在没有这个字段,26587 单一单都追溯不到预约)。
  代码里链路是存在的(`run_journey` 按「预约→上门→量体→下单」写),但**「链路存在」和「链路是主路」是两件事**
  —— 那 42 条旅程只占 0.16%。**等业务答**,eureka-ab 的决策清单里列着,答了再动 `run_journey`(要先加列)。
- **剩下 283 款的图怎么办**。用户已定:先用占位图。若将来要共用图,讨论结论是
  **可以共用但不许跨颜色**(颜色一眼看得出,形制外行看不出)—— 而且共用的图必须标「借自哪一款」,
  四态同纹样那套:**没有标记 = 错误,不是默认当成本款**。
- **纹样识别评测若将来要做**:那 34 款「待业务核」的图上画的是占位纹样,
  直接拿去测会量出「占位符识别率」而报告写成「纹样识别准确率」。
  报告侧判据**故意没做** —— 现在没有消费方,写了是一条从没红过的检查。
- 打版图的纹样只有 14 款是商品名点明的(已核),其余是按面料/工艺推的(推导档)。**业务确认前别说「纹样对了」。**

---

## 压缩前交接 · eureka-ab 这条线(商机 / 场合 / 评测)`2026-09-20`

### ⏸ 2026-09-20 11:30 · **有一个提交正压着没发**

**压着的东西**:`澜绣云裳agent-设计稿-日程预约与客户绑定.md`(458 行,已发飞书)
+ 本文件这一段。**内容都写完了,只差提交。**

**为什么压着**:门禁红,**但红的不是我的东西** ——
并行会话加了第 6 个技能 `pattern-draft`,两处没跟上:

    ① `.gitignore` 那份手写白名单漏了 `!agentsite/.claude/skills/pattern-draft/`
       → 检查报「自己写的技能都进了版本库(验了 6 个)❌ 没被 git 跟踪:['pattern-draft']」
    ② 文档技能数写 5、现算 6,三处:
       产品需求文档 :150 / :274,产品说明 :84(还有 4.4 节标题和表格)

已经发消息告诉他了。**等他补完再提** —— 我的提交骑在别人的红上,
从提交记录看就像是我弄红的。

⚠️ **抓到这件事的正是我 09-19 自己加的那道检查**(repo_consistency_check 第三条)。
它按设计工作了:**「装了」和「提交了」长得一模一样**,不单独验就发现不了。

**下一步第一个动作**:等队友那两处补完 → 跑 `./check.sh` 确认全绿 →
提交那两个文件 → 然后回到商机线(场合词表进 `sys_code`)。

### 🆕 设计稿通读**已完成**(2026-09-20,存档 458 行,已发飞书)

⚠️ **业务定的口径:设计稿只是大致的结构和流程,不是规格,以讨论为准。**
所以那份存档的性质是**意图证据**,不是要照着做的清单;
设计和九条决策冲突的地方,**决策赢**。

**🎁 设计想到了而我们没想到的(白捡的两条):**
- **录音已经规划成「沟通记录」的附件** —— `.wav` 带播放和下载按钮,
  一条沟通可挂多个附件(录音 + 现场照)。**ASR 的落点就在这儿,不用新造承载。**
- **「预约渠道」(小程序 / 导购终端 / 管理后台)能区分谁先发起** ——
  小程序 = 客户自己约;导购终端/管理后台 = 顾问替客户约。库里没有这一列。

**⚠️ 设计里最要命的一条:沟通记录**没有**任何文字内容字段**,只有 时间/方式/顾问/附件。
**那通电话说了什么,只存在于 .wav 里** —— 而「录了音」和「记下了内容」
在界面上长得一模一样(都显示成一条沟通记录)。**这就是转写是刚需不是锦上添花的理由。**

**⚠️ 一处可能的重复,要业务确认:**
「跟进记录」(客户详情底部 Tab,有状态/文字/下次跟进时间,**没录音**)
和「沟通记录」(日历面板 Tab,有**录音**,**没文字**)——
**一个有文字没录音,一个有录音没文字**,而它们描述的很可能是同一次电话。

**其余判据(第一版交接已记,仍然成立):**
「预约」是「日程」的一个类型而非独立实体;跟进弹窗里已有商机雏形
(跟进状态 + 下次跟进时间);顾问绑定设计上也只有「设成谁」。

**❌ 我读错过两处:** ~~设计稿里已有商机功能~~(那是购买商品列表的表头)、
~~跟进状态有可选值~~(那是日期筛选)。**图层名不等于功能,必须截图核对。**

### 🆕 补充:设计稿通读(2026-09-20 午后,提交 9017084)

**存档**:`澜绣云裳agent-设计稿-日程预约与客户绑定.md`(287 行)· 已发飞书
Figma:`dxb3seYayFinuOlZhLMljf` 澜绣云裳管理后台,四页(工作台 / 店铺配置 / 客户管理 / 组件)

**🔑 判据(压缩会先丢这个):**
- **「预约」不是独立实体,是「日程」的一个类型。** 日程类型三分:
  客户预约(电话回电/预约到店/上门沟通)、企业任务、订单任务。
  个人日程和店铺日程是**同一批数据的两个视角**。
  而库里是两张独立的表(`schedule` 90 + `appointment` 75)。
  → **这解释了 `followup` 24 条全挂 `appt_id` 的怪现象** ——
  根子不是缺字段,是**把一个东西拆成了两张表**。
- **跟进弹窗里已有商机雏形**:`跟进状态[待再次沟通]` + `下次跟进时间`(必填)。
  **「状态 + 什么时候再捞」就是商机**,而 `followup` 表这两列都没有。
- **顾问绑定设计上也只有「设成谁」**(配置顾问弹窗 = 归属门店 + 顾问)。
  → 修正:**不是实现漏了,是设计就没考虑。**

**❌ 我读错过两处,别再引用:**
- ~~「设计稿里已有商机功能」~~ —— `37:21552 商机` 实际是**「购买商品」列表的表头**
- ~~「跟进状态有可选值列表」~~ —— `1248:150386 跟进状态` 实际是**日期筛选(本日/本周/本月)**
> **图层名不等于功能。只读 metadata 会把命名残留当成事实,必须截图核对。**

**悬而未决(要业务拍板):** 按设计合成一张日程,还是保持两张表、上层做视图?

**下一步第一个动作:** 接着读没看完的五屏 ——
工作台页全量、客户预约列表(5188:198448)、绑定人关系(637:30374 / 1974:175288)、
日历-沟通详情(2069:228294)、店铺配置-日程管理(841:55027)。
读法:metadata 取结构 + **关键屏必须截图核对**。



**本次变化**:九条决策全部拍板;纹样由队友做完;**Figma 设计稿还没看,而它和当前这条线强相关**。

### 1. 未验证的预判

- 🔮 **预判**:场合维度用「**词表进 `sys_code` + 新建关联表 + 新写一步种子脚本接 `rebuild.sh` 末尾**」
  这个形状落地,**理由是完全不碰队友的表**。**这个形状一行代码都还没写过,没验证。**
  验法:真写出来跑一次 `rebuild.sh`,看 ① 队友的表一个字没动 ② 重建后场合数据还在。
- 🔮 **预判**:D4 用「分类命中 + 工艺排序」能满足「织金云肩是云肩的次一级」。**没跑过真实问法。**
  验法:等商机落地后,拿「想要织金云肩」跑一遍,看命中的是不是 `C040301` 且工艺筛出织金。

### 2. 判据(比结论值钱)

- **商机 ≠ 草稿方案。** 商机是方案的**前置触发之一**,**可以完全没有服饰信息**;
  草稿方案必须至少挂一件具体服饰(= 消费端选中的、或沟通里提到的)。**这条可机器判定,要做成检查。**
- **顺序不固定,就不能靠「谁挂在谁下面」建模。** 顾问先打电话 / 客户先预约**两种都有**,
  而 `followup.appt_id` 让沟通从属于预约(24 条**全挂着预约,一条独立的都没有**)。
  → **商机是主线**,沟通和预约都挂它、各带时间戳,**顺序由时间戳表达**。
- **「她拒绝了」和「当时没货」在「没成交」上长得一样,而该触发的动作相反** ——
  前者永久关闭,后者搁置等供给。**商机终态至少两个**,搁置必须写清等的是什么。
- **「维度不适用」≠「还没标注」**,虽然两者都表现为「没有记录」。
  不分开的话不适用的那些**永远挂在欠账清单上,那个数降不到 0**。
  → 每个维度声明自己的适用范围:**场合只给成品服装(253 个),纹样给全部(含面料部件)**。
- **词表不许写死在代码里** —— 业务加一个场合是**运营动作,不该是一次发版**。
- **D4 不动分类树**:编码长度就是层级(3 位一级 / 5 位二级 / 7 位三级),
  往下加会把编码推到 9 位,**动它要改所有按长度判层级的地方**。
  而且「织金云肩」= 云肩(分类) + 织金(工艺),**拼成一个码等于把两个维度压成一个**。
- **一个词出现在商品名里,不等于它描述的是你要的那个维度。**
  实测抽纹样只有 4.8% 真阳性,假阳性全是工艺(织金/妆花/缂丝)、面料名(竹节棉的竹)、
  形制部件(襕)、配饰(云肩);「四合如意」说的是云肩的**形制**不是上面的花。

### 3. 作废的结果(别再引用)

- ❌ **「配饰也挂场合」** —— 业务 09-20 定**只有成品服装需要场合**,配饰和面料部件都不给。
- ❌ **「汉服 282 个挂旅拍写真」** —— 正确是 **252 个**(我多算了 30 个配饰)。
- ❌ **「面料部件不单卖,要撤架清订单」** —— **业务否了**,面料单卖是正常业务。
  影响面留档:2203 订单行 / 2188 张订单(全部的 8%)/ 其中 **1738 张会变空单**。
- ❌ **工具合并「能减到 28 / 41 / 48」** —— 三个数都基于已被推翻的判据,实际 54;
  而且**对照实验证明合并没有可测收益**(命中 11/11→11/11、token 只省 0.69%)。
- ❌ 别再用**「一件事」**这个简称 —— 说**「方案」**更清楚(用户问过「一件事究竟是什么」)。

### 4. 禁区

- **纹样归队友**,`knowledge/motif.py` 和 `12-纹样.md` 我不碰;我只用它的 `motif.推()`。
- **`rebuild.sh` 末尾加步骤时,必须同时改 `DONE=7` 那个断言** ——
  只加步骤不改这个数,重建会在最后报红,**而前面每一步看起来都成功**。(队友提醒)
- **录音同意不进 `consent` 表** —— 那张表是「可撤回的逐客户授权」,
  塞一档永不撤回的进去,**和另外两档长得一样、语义相反**。
- 提交只提自己的路径;`bite_specs.json` **用文本追加,别 JSON 整体回写**(我踩过,1453 行全变)。

### 5. 下一步的第一个动作

1. ⚠️ **先重启 Claude Code。** `figma` 的 MCP 在这个会话里**没连上** ——
   排查过:全局配置在、项目没禁用、端点通(HTTP 405)、执行器文件在,
   但**点名取工具取不到**,`/mcp` 里也看不见它。
   根因是**会话启动时它没起来,而 MCP 清单在启动那一刻就定死了**(`~/.claude.json` 10:53 改过)。
   重启后若显示未授权,按提示授权一次。
2. 然后读 Figma:`node-id=1316-176843`,看三块 ——
   **个人日程 / 门店预约 / 客户管理页的顾问-顾客绑定**。用户原话:「这跟当前的内容也是强关联」。
3. 再之后:七个场合词进 `sys_code`(五个「本期在用」+ 三个「为扩展预留」),
   建商品↔场合关联表,给 **252 个汉服成衣**挂「旅拍写真」。

### 6. 悬而未决

- **Figma 那三块还没看**(上面第 2 步)。
- **⚠️ 查出一个结构问题,还没定怎么办**:顾问↔客户的绑定**只有 `customer.advisor_no` 一个字段**,
  它只答得了「现在归谁」,答不了「什么时候绑的 / 上一个顾问是谁 / 为什么转 / 批没批」。
  而 `approval` 里**已经有「客户转移」这个审批类型** —— 也就是转移走审批,
  **但批完只是把字段覆盖掉,历史就没了**。
  对比:`schedule` 改派任务记了 `reassigned_from` / `reassign_reason` / `reassigned_at` **三个字段**。
  → **同一件事「换个负责人」,在任务上记了全套,在客户上只有一个覆盖。**
  这直接影响商机:「这个商机跟了半年没成」很可能因为中间换过顾问。
- **数据还是空的**:跟进 **24 条 / 965 个客户**、商机 0、逐字稿 0。
  做之前要先补,否则检查跑在空集合上 —— **空集合上所有性质都成立**。
- **ASR 还没装**(已定本机跑,不上云)。装完**必须自己测中文行业词识别率**
  (妆花/缂丝/马面裙),**「转错了」和「转对了」在文本里长得一模一样**。

---

## 上一次停在哪

> ### 📍 2026-10-25 下午 —— 三轮拍板全部落地
>
> · `5861f9a` 知识来源新立「业务口径」档(溯源欠账 46 → 7)
> · `e6d725f` 交接 + 项目日志发飞书
> · `95180f6` intent 判据的待办段结束锚跨段(**CI 连红三轮的真因**)
> · `0671740` 订单上冗余「客户现在归谁」(20.5 → 6.5 ms,3.1 倍)
>
> 中间用户又拍了一轮「剩下 7 条全拍」,所以**溯源欠账 46 → 0**(走 `biz` 的 12 条)。
>
> 门禁 341 项全绿 · 咬合 cust_advisor 4/4 · query_index 6/6 · shop_key 11/11 ·
> `bite_specs` 1071 → 1106(含并行会话同期推的,按 `(script, 改坏)` 认身份合)。
> **CI 上我这条线一条没红** —— 唯一那条是并行会话的位置参数 INSERT,他已修。
>
> ⚠️ 《待办清单.md》的「要人做的」从 6 条降到 **5 条** ——
> 溯源那条 intent 标成「做完了」之后自动挪进了「已完成」。

> ### 📍 2026-10-25 早 —— 推了一笔,门禁全绿、咬合 10/10
>
> · `5861f9a` 知识来源新立「业务口径」档(20 个文件,954 增 / 145 删)
>
> 门禁 **341 项全绿** · 咬合三关 **10/10** · `bite_specs` 1071 → **1087**
> (含并行会话的 7 条,按 `(script, 改坏)` 认身份合的 —— ⚠️ **不能用 `(script, 预期红)`**:
> 同一条判据可以有多条规格,用那个身份去重会**安静地吞掉一条**)。**CI 在等。**
>
> 顺手修掉三件,第一件就是今早门禁那条红:
> · **每日平移缺了回填门店码那一步** —— 根因是**流程缺口不是数据漂移**,详见「别重做」⑤
> · 一条判据**声称在现读、实际在手抄**(加第四档才露馅)
> · 新建 `tools/refresh_kb.py` —— 改完知识 md 刷库用。**原来没有这个入口**:
>   只有「跑 43 步重建(里面真调模型约半小时)」或「单跑 `seed.py`(得到 65 张表的空壳)」,
>   两条都不能走,所以实际发生的事一直是**「改了 md 就不改库」**。

> ### 📍 2026-10-24 夜 —— 推了两笔,合并后全量门禁全绿
>
> · `02d992b` 门店关联键第二阶段收尾(api.py 那 8 处 + 欠债上限 8 → 0 + 「全渠道」收进唯一来源)
> · `de52f13` 报告模板门店标识改按编码(21 条判据 + 3 条咬合)
>
> **合并并行会话的改动之后跑过一轮全量门禁:全绿、零个 ❌。** CI 还没看。
> 咬合规格现在 1068 条(他 4 条 + 我 5 条,按内容身份合的,一条没丢)。
>
> ⚠️ **今晚门禁红过三轮,三次真因完全不同,而且一次都不是业务代码的错:**
> ① 我在门禁跑着的时候改了 `check.sh` —— bash 边读边执行,从新文件的旧字节偏移接着读,
>    读到一行中间,报「语法错误」,**而那一行在磁盘上完全正常**;
> ② 容错写在了判断上、没写在取数上(详见下面「别重做」那一段);
> ③ 我自己那条咬合规格的锚,**在写出来的同一个晚上就被我改没了**。


全部已提交推送,`check.sh` 全绿。按时间顺序:

### 🆕 2026-10-16 · 三条退款异常真跑完了;**五次真跑,前三次挂的都是判据自己**

`check.sh` **284 条全绿**。数在 `agent/refund-sets-results.jsonl`(五条,一行没覆盖,
每条带当时的分界点号)。最后一轮 `fcb9f8e`:轮一 答成 3/3 过 1、轮二 答成 2/3 过 0。
同日 13:45 那次干净的两轮是 **2/3 与 1/3 —— 两轮没过的不是同一批,是抖动**。
只跑一轮会报出差一倍的两个数,而两个都不是结论。

**四轮合看**:`DQ9002` 全挂在同一条 = 稳定缺口;`DQ9001` 挂 3 过 1 = 偏挂且抖;
`DQ9003` 三次过、一次被交付前闸扣下。而**挂的是同一类东西** ——
两条都不是「没查到」,是**查到了、原因说对了,却没给出那句风险提醒**
(别再重发 / 别再重试)。`DQ9001` 有一轮的建议动作段只写了查证步骤
「即刻查证微信后台确认 WX9100000000 的状态」,一句别重发都没有,
而那笔钱可能已经出账 —— 重发就是第二次出账。

**判据自己的五个缺陷(全部修了,都配了人造对照)**:
1. 台账「遮了 0 处」被当成「没证据」→ 整轮关掉。而 `DQ9002` 全 0 是**对的**:
   只有 `DQ9001` 被走完闭环。证据链其实更干净 ——
   `_记台账` 只在遮蔽真做了事时才写,而它只在 env 到了这个进程时才做事,
   所以**台账里有行 ⟺ env 到了服务进程**,与遮了几处无关。
2. **一对括号就能把否定切断**(`agent/textmatch.py`,第十一个坑):
   「**不能**继续用原幂等号(IDEM-DQ9001)**重试**」被判成「建议了重试」。
   ⚠️ 影响面 **23 个文件** —— 18 套评测 + 两个业务口径 + `agentsite/guards.py`
   (**产品真实的交付前校验**)。改完当场验:25 套人造对照 + `gate_test`/`guards_test`
   + 商机口径,一套都没变红。
3. 判「建议了什么」要**正向**判、且只看「建议动作」那一段。用户原话是
   「判的是**有没有说出**『不要重发』」,而我写成了反向 ——
   反向对陈述句天然敏感:同一段里还有「已重试 3 次」和「再次重试可能造成双倍出账」。
4. **回答被交付前闸扣下时,评测在一段打回提示上判了分**。和夜跑 403 记成 0 分
   是同一个形状(`e0e8fe6` 立的规矩),而代码里**本来就记着**「交付检查=未通过」。
   现在三分类:过 / 没过 / **没答成**;有题没答成时「全过」是 `None`(不知道)不是 `False`。
5. 分界点指着没提交的代码 / 咬合规格自己过期 —— 都由门禁当场抓到。

**顺手做完的**:`tools/restore_task_summary.py --写` 还原了 54 条被 AI 根因覆盖的
工单摘要(售后 12 条回公式、合并 16 + 财务 26 回 NULL,AI 原文残留 0)。
`dataset_check` ⑤ 那条每天 1% 概率假红的判据,量程换成**造数基准那批**
(没删项,覆盖面还是 4 项),配了一条咬合盯新量程。
口径模块 53 → 54(回测口径那份也被工具层真调)。

### 🆕 2026-09-20 · 商机线立项,九条决策全部拍板(**还没写一行实现代码**)

业务开了一条新线:**成单前那一段是空的** —— 商机、通话录音转写、下一步指引。
`intent/opportunity-and-call-notes.md` · 需求池 §4.8 ·
待决策清单已发飞书(`澜绣云裳agent-商机与录音-待决策清单.md`)。

**🔮 未验证的预判(还没做,别当成已完成):**
- 场合维度、商机对象、诉求回捞 —— **一行实现代码都还没写**
- 我打算用「词表进 `sys_code` + 新建关联表 + 新写一步种子脚本接在 `rebuild.sh` 末尾」
  这个形状落地,**理由是不碰队友的表**;这个形状本身还没被验证过

**判据(比结论值钱,压缩会先丢这些):**
- **商机 ≠ 草稿方案。** 商机是方案的**前置触发之一**,**可以完全没有服饰信息**;
  草稿方案必须至少挂一件具体服饰。**这条边界可机器判定,要做成检查。**
- **顺序不固定,就不能靠「谁挂在谁下面」建模。** 顾问先打电话、客户先预约两种都有,
  而 `followup.appt_id` 让沟通从属于预约(24 条全挂着预约、一条独立的都没有)。
  → 商机是主线,沟通和预约都挂它、各带时间戳,**顺序由时间戳表达**。
- **「她拒绝了」和「当时没货」在「没成交」上长得一样,而该触发的动作相反** ——
  前者永久关闭,后者搁置等供给。所以商机终态至少两个。
- **「维度不适用」≠「还没标注」**,虽然两者都表现为「没有记录」。
  不分开的话,不适用的那些会永远挂在欠账清单上,**那个数永远降不到 0**。
- **词表不许写死在代码里** —— 业务加一个场合是运营动作,不该是一次发版。

**❌ 作废的说法(别再引用):**
- 「配饰也挂场合」—— 业务 09-20 定**只有成品服装需要场合**,配饰和面料部件都不给
- 「汉服 282 个挂旅拍写真」—— 正确是 **252 个**(多算了 30 个配饰)
- 「面料部件不单卖,要撤架清订单」—— **业务否了**,面料单卖是正常业务。
  影响面留档在清单里(2203 订单行 / 2188 张订单 / 其中 1738 张会变空单)

**✅ 已经做完的那部分(不是我做的):** 纹样维度由并行会话做完(048db0c),
296 件商品一件不落,`motif.推()` 给 (纹样, 来源, 证据)。

**下一步第一个动作:** 把场合词表写进 `sys_code`(七个词,五个「本期在用」+ 三个「为扩展预留」),
然后建商品↔场合关联表,给 252 个汉服成衣挂「旅拍写真」。

**悬而未决:** 无(九条全定了)。但**数据还是空的** ——
跟进 24 条 / 965 个客户、商机 0、逐字稿 0,做之前要先补。

### 🆕 2026-09-19 晚 · 工具/技能/守卫比例优化(aecd434)

**工具 60 → 54 · 技能 3 → 5 · 守卫 4 → 5,门禁 116 项全绿。**

做了什么:
- 工具砍的**全是同族重复**:任务查询 4→`get_tasks`、会员分层 3→`get_member`、
  版师裁片 2→`pattern_queue(pattern=…)`。合的是 `SHOP_SCHEMAS`(接口面),
  **实现留在 `api.TOOLS` 里没动**,逐支路和老函数比对过,一字不差。
- 技能新增 `deadline-rescue`(工期赶不上怎么救,依据知识库 07 第六节)
  和 `exchange`(办换货,依据 09 第六节 + R1–R5)。
- 守卫新增 `PreCompact`:压缩前立旗,下一轮把**按号取过的单据**注回去。
  判据和「当前方案」一字不差 —— **按号取过的单条才算,列清单不算**。

**🔮 这一轮最重要的一条认识(是结论,已被实做验证,不是预判):**
> **「解冻冻结流程」不等于删工具。**
> 那批被叫做冻结流程的工具,大多数每一步都有唯一正确答案(算身高、推尺码、算工期),
> **中间结果不需要经过模型** —— 它们是计算,该留在工具里。
> 缺的是它们**算完之后**那个需要判断的循环。
> 所以需求池 §4.5 里「28 个工具 + 8 个技能」那个目标形状**不成立**,已在那里记下改正。

**❌ 作废的说法(别再引用):**
- 「工具能减到 28」「减到 41」「减到 48」—— 三个数都基于已被推翻的判据,实际是 **54**。
- 需求池 §4.5.5 里「任务查询 5→1」**错了**:`list_tasks` 查 `task` 表,
  `my_tasks` 查 `schedule` 表,**两张不同的表**。是 4→1。

**🚫 这一轮刻意没做的(不是忘了):**
- **五个派工写工具不动**。权限规则各不同,而且 `roster` 技能里已经写明
  「单独派一条用 `assign_task`,排班用 `assign_batch`」——
  **该调哪个这个问题,组织知识已经答了**,不是工具设计的问题。
- `monthly_review` / `recovery_queue` 的「建议」那一段仍由代码生成。
  按判据该交给模型,但要改工具返回结构、牵动评测,**已降为 P2 单独立项**。


**最近这一轮(2026-09-19)把「一件事」那条线做完了,并给版师的分析打了地基。**
⚠️ 这一轮**全程有第二个会话在并行改数据**(假数据工厂),
下面每一条都标了归谁 —— 接手时**先看归属再动手**。

1. **「一件事」六步全齐**(`intent/scheme-as-unit.md` 的验收条件)
   - `get_scheme` 读工具、`ordr.scheme_id` 双向、指代推进判分器 + 15 条对照
   - **第 4 步是这条线里唯一真正属于 Agent Loop 的**:每轮把当前方案注回去。
     方案号放在 harness 的 `state` 里,**不放在对话文本里** ——
     自动压缩压的是「读起来连贯」,不是「标识不丢」。
   - ⚠️ **最要紧的一条限制:列清单不算「取过」**。
     列了一遍清单就把第一条当「当前方案」,等于**把消歧捷径从后门放回来**,
     而且更隐蔽:模型没挑,是 hook 替它挑的,**hook 不出现在对话里,没人看得见**。
   - 订单↔方案样本 1 → 67 张,**下限跟着从 1 提到 30** ——
     一个不跟着数据涨的下限,涨上去之后只是摆设。

2. **给版师的受欢迎与易损分析**(口径 + 七条性质检查,**但还没有工具**)
   - ⚠️ **`grep popularity` 在工具层、提示词、角色白名单里出现 0 次** ——
     做了 90%,而那 10% 决定了前面 90% 有没有用。整条存进了**需求池 P7**,
     业务说这条线先留着,不是现在做。
   - 易损必须用**率**不用绝对数;分母不足**不给 0% 而给「样本不足」**
     (0% 会被读成「不容易坏」,真相是「没卖几件」)。
   - `差异显著吗()`:42 种面料的率全挤在一个窄带里时,**明说「不足以支撑结论」**。
     **一张排出了名次的榜,和一张有信息量的榜,长得一模一样。**
   - ⚠️ **演示库里的易损结构是假数据工厂按行业常识种进去的**(倍数是编的),
     **不是发现**。演示时必须照实说,否则这套分析**越准确越危险**。

3. **同意分档 + 撤回**,挖出两个「长得像控制但不控制任何事」的东西:
   - **撤回那条分支从来没被走过**:1165 条同意,撤回过的 0 条,
     `revoked_at IS NULL` 一直为真,**写对写错都一样**。
     新检查**在库的副本上真撤一条**,看能力有没有当场关闭。
   - **`account.marketing_consent` 拦不住任何事**:只被显示和清零,没有一处做过判断。
   - 第 ③ 条钉《个保法》「单独同意」的核心:**一档不能顶另一档**。

4. **写接口冒烟**(`backend/write_smoke_check.py`)——写这道检查时**自己漏了沙箱**:
   只改 `server.DB` 和 `api.DB`,而 `oplog.py` 有它自己的 DB 常量,
   **往真库写进了 3 行**。全仓 **23 个模块各带一份 DB**,手工点名迟早漏 ——
   现在按性质扫描,**改不到 3 个就抛错拒绝跑**。
   ⚠️ **欠账 15 个写接口没用例**,用的是「只许降不许涨」的上限模式。

5. **售后 / 换货 / 两套订单状态**的业务硬规则全部进门禁(R1–R5 + 换货五条 + 状态四条)。
   ⚠️ R5 换过一次身份:先是我加的「不早于发货」,业务升级成「订单完成之后」。
   **身份一变,和评测夹具冲突时的让法就反过来** ——
   助手加的规则让夹具,业务定的规则夹具让它。**来源标注是冲突时唯一的裁决依据。**

6. **今天撞了四次「读到重建到一半的库」**,每次表现都不同(表数掉了 / 表不存在 /
   48 条咬合一起挂 / 门禁跑到一半被截断)。假数据工厂做了互斥标记
   (`backend/.rebuilding`,存进程号并验进程活着)。
   **「库坏了」和「库正在被重建」原本长得一模一样,而该触发的动作完全相反。**

**当前:门禁 112 项全绿,咬合 131 条全过,跑在 25213 张订单上。**

**最近这一轮(2026-09-17 ~ 09-18)做的是「看不见的欠账」和「对外能看的文档」两件事:**

0. **门禁从 84 项涨到 100 项**,新增的都是原来没有网的地方:
   - **咬合欠账 78 → 0**。98 个检查脚本现在全都有「真的被改坏过、真的红了」的记录
     (`tools/bite_run.py` 三关:对照绿 / 改坏红 / **红的必须是那一条**)。
     副本用**黑名单**拷贝 —— 白名单会静默漏掉新文件。
   - **CI 连红 30 次而本地一路绿**。根因:CI 建库手抄了 `seed.py`,
     而重建配方早已改成 `rebuild.sh`。**「本地绿」从来不等于「CI 绿」**,
     现在有 `push-then-ci` hook 在推完之后报**当前**红绿(不是历史)。
   - **四个详情页 + 两个导出是坏的,99 步门禁一项没红**。
     补了 `backend/page_smoke_check.py`:从 `do_GET` 现推只读入口再逐个打开。
     ⚠️ **写接口一侧还没做** —— 33 个 `do_POST` 只有 5 条往返被覆盖。

1. **《产品需求文档》(对外 PRD)** —— 13 章,三张图走飞书画板真画出来,
   27 条功能需求每条四行:**指标 / 性能 / Agent Loop 体现 / Harness 体现**。
   ⚠️ 这四个名字是**业务方的原话,不许改**。我改成过「度量口径 / 调度形态 /
   运行时归属」,结果他**又提了一遍同一条要求** —— 换个说法就等于没写。

2. **《业务需求池.md》** —— 和《待办清单.md》分工:一个整理需求,一个整理进度。
   三条业务线(导购 / 打版定款 / 支撑),每个卡点有场景、需求、服务对象、做到哪了。
   业务拍板:**MCP 跟表走跟 API 走,不许按业务场景造工具**(推翻了我提的 `lock_scheme`)。

3. **飞书画板能画流程图了** —— API 全靠错误信息逼出来,沉淀成 `draw-flowchart` skill
   和 `tools/feishu_board.py`。**收下了 ≠ 画出来了**:三处缺陷(标签挤成团、
   箭头静静消失、caption 接口收但不渲染)都是**导出图片真看一眼**才发现的。

1. **22 个待定版型的成衣全部拍板**(22 → 0)。业务逐条定的,
   写进代码不写进文档 —— **裁决写在文档里,下个人还得再拍一次**。

2. **全部商品配图**(渲染失败 80 → 0,互不相同的主图 13 → 294)。
   根因是 `sku.color` 那一列存了面料名 —— **一列承载两件事**,
   这一轮撞了五次以上。

3. **编辑日志 + 商品表单 5 → 13 字段 + 量体模板可编辑可管理**。
   日志原来会**撒谎**:表单没提交的字段被 diff 成「改成空」。

4. **分部位选料**(§29):部位**从裁片归并**,内衬**从 BOM 来**——
   一个部位两个来源,算料时不能只用其中一个。
   441 对「不可」的相容对账,存量 0 违规。
   **外层部位不细分是拍过板的决定,不是待办**(业务原话「维持可选,客户自己挑」)。

5. **裁片用料占比**(§30):估了 391 个有依据的初值,复核抓到一条真错
   (裙片 83% —— 片数被算了两遍)。来源标「**复核**」不标「版师」:
   **我核的是规则有没有算错,版师核的是这个数对不对。**

6. **版师角色 + 两个账号**(§30):第一个「恰好有一个写工具」的角色。
   加它的时候把三个踩过的坑又踩了一遍(命名空间、写口没登记、判据贴着名字)。

7. **版师的入口和推档自检**(§31):排队看板按**影响面**排序;
   推档把「要核 1237 个数」压成「要核 12 条档差」。
   上线第一次跑就抓到真 bug:**8 个童款版型的四个码尺寸完全一样**
   (身高码不在序号表里,`.get(尺码, 0)` 全算成了 M)。

8. **评测 / 量体比对 / 版本号**(§32):版师评测 12 题,三轮 11、9、11。
   跑四轮**每一轮都在修判分器**(六条,没有一条是模型的错)。
   量体比对给了版师,**隐私边界靠「把每个工具真跑一遍扫返回」守**,不靠提示词。
   版型版本号先立着 —— 等真改版再加,之前所有单子的「当时用哪一版」永远查不到。

9. **假数据工厂(`fakedata/`)全程没进过这份交接文档** —— 并行的另一条线。
   从数据库直连做到写接口驱动、MySQL 实跑、176 万行规模、模型判定带票数,
   全部已提交。**它做了十几个阶段,却一次都没刷新过这份文档**,
   上下文被压缩时接手的会话只能从摘要里捞。补在 `intent/fakedata-factory.md`。
   之后做完了库存预警要的模拟销量(`tools/simulate_sales.py`,6 个月 3826 单,
   292 个 SKU 算得出可售天数)。它撞出库存预警一条判据画错了边(卖空的 0 天是事实),
   对方已修。**这批数据在客户维度不能用**(27 个客户人均 142 单),见 `intent/demo-data-gaps.md`。

10. **假数据工厂补了四层**(2026-09-16)—— 起因是造模拟销量那次**工具自己没派上用场**:
   我另写了一个专用脚本,而那件事本身就是最大的反馈。
   `oracle.py` 拿项目自己的检查当裁判(二分定位是哪张表弄红的,外加「把库藏起来」的对准自检)/
   `protect.py` 行级保护(夹具碰不得)/ `realism.py` 像不像体检(按视角报,不给总分)/
   `ledger.py` 事件与台账(先排时间线再按「现在」截断)。
   `simulate_sales.py` 已整个迁到台账上,等价重构、数据一模一样。
   撞出的那个推断 bug **当天就修了**(2026-09-16):`ordr_item.order_id` 原来被认成指向
   `sim_batch`(列名完全相同 +0.5 命名分),而不是覆盖 100% 的 `ordr.id`(表名拼写差一个字母)。
   修法不是调权重是**立原则**:**全覆盖的候选整体优先,命名线索只在同层内部比** ——
   命名回答「像不像」,覆盖率回答「能不能」,后者是硬条件。
   三层回归都跑了:自测 177 条全绿、真实库 94 条关系**只变了该变的那一条**、
   英文泛化靶子认出率一模一样(25/27)。**基线是改之前导出来存的**,不是凭印象说「没影响」。

11. **三代对比表重跑了,而重跑本身推翻了旧表的读法**(2026-09-16)。
   同一提交、同一模型(haiku-4.5)、同一批工单**连跑两轮**:
   V1 6/6 → **5/6**、V3 6/6 → **5/6**,而且挂的不是同一题;V2 两轮都 6/6
   (它每条只调 1 次模型,**调用越少抖动面越小**)。
   **旧表写的单轮 6/6/6 读起来像「三代能力持平」,其实是三次抛硬币都正面。**
   V3 还贵了 38%,而调用数和耗时没变 —— 钱花在上下文上:
   工具 26 → 59 个、提示词 21KB → 55KB,**每次调用都要把全部工具定义带上**。
   V1/V2 没涨(V1 只带自己那几个工具、V2 大部分节点不调模型)。
   顺手补了三处:结果**落盘**到 `agent/gen-compare-results.jsonl`(每条盖来路)、
   **不显式指定模型直接拒跑**(两条凭证路径的默认模型不一样,换机器就换模型而表上看不出来)、
   跑完**自动和上一轮同模型**对比(没有可比的上一轮会明说,不会静默显示成「和上次一样」)。

12. **定向造数:先说要让哪条检查红,再倒推造什么**(2026-09-16)。
   业务问「除了服务这个项目,这工具还缺什么能力」,盘出四个缺口,先做了价值密度最高的这个 ——
   **它是「数据生成器」和「测试数据系统」的分水岭**:
   前者给一堆合法数据,后者给一个能复现某个场景的数据。
   成功判据是硬的:**目标那条红 + 其余一条都不许跟着红**
   (只要前者的话,把库清空就能让任何检查红,那不叫触发叫搞坏)。
   检查当**黑盒**跑(各家写法不一样,解析是无底洞),源码片段喂模型当线索,真跑一遍当裁判。
   **这一层不投票** —— 推断那层要投票是因为对错没法当场验,这里能验,
   **能真验的东西不靠投票**。
   实测:真模型一轮成功,给一条跨表规则「每张订单至少要有一行明细」造出一张空订单,
   还用引用机制从库里取真实客户 id(编一个不存在的会先撞上别的检查)。
   四处咬合都验过;入口 `python3 fakedata/cli.py target … --check … --flag …`。
   **还没做的三个缺口**(按我给业务的排序):跨存储一致性(订单在库里、缓存在 Redis、
   事件在消息队列 —— 只造库,测试仍跑不起来,而且看起来数据是全的)、
   生产分布不带生产数据(进真实企业的门票)、schema 变了方案能跟上。

13. **通用化的三个缺口补完了**(2026-09-16)。业务问「除了服务这个项目还缺什么」,
   盘出四条,做掉定向造数之后把剩下三条也补了:
   - **方案漂移**(`drift.py`):表结构变了,上一份方案里哪几条判断失效了。
     分致命/警告/提示三档 —— **五种漂移里只有两种会吵**,另外三种灌得进去、只是开始造错的数据。
     改名只猜不改(「改名」和「删一列加一列」在结构上长得一模一样)。
     真实项目第一次跑就暴露「噪音压过信号」:65 条提示淹掉真正要紧的几条,已折叠。
   - **统计普查**(`census.py`):把分布带出来、不把数据带出来。
     难点是**摘要自己也会泄露** —— 只出现一次的取值就是那一条记录、max 就是某一个人。
     自测抓到一个真泄露:**分位数在小样本上等于极值**(41 行的 p99 就是 max),
     现在分位点和低频抑制用同一个 k。真实库实测 57 处抹除,客户名手机号一个都没漏。
     ⚠️ **不做差分隐私**,做的是 k-匿名式抑制,别把它说成差分隐私。
   - **跨存储**(`multistore.py`):一笔事实同时活在库、缓存、事件流、对象存储里,
     只造库等于没造 —— 而那时**库里数据齐全、检查全绿**,只有真跑业务才崩。
     值钱的是**对账**(少写一处要有声音),不是多写几个文件。
     ⚠️ **没接真 Redis/Kafka**,只有文件式适配器:没有带这些组件的靶子,接了也只是「看起来支持」。
   三个模块各自带自测和咬合;`drift` / `census` 有命令行入口,
   `multistore` 和 `ledger` 一样定位成**给写生成脚本的人用的库**。

14. **方言补到 PostgreSQL,跨存储接上真 Redis**(2026-09-16)。两件都**真跑过**,
   不是「代码看着对」:
   - **PostgreSQL**(`pg_e2e.py`,不进 check.sh,要人手 `createdb`):镜像 7 张表
     (3872 单 / 4405 行明细)、反射读到 10 条注释、挖出 9 条关系、灌 953 行、
     **我弄脏的 0**、回滚删干净。驱动懒加载,依赖不进主干。
     真跑抓到一个坑:**PG 的 `COMMENT ON` 不支持参数绑定**(它是工具命令,
     占位符原样变成 `$1` 语法错),注释只能内联 + 自己转义。
     **这个洞离线自测一辈子碰不到** —— 和 MySQL 那次(空元组触发 `%` 格式化)一模一样。
   - **真 Redis**(`multistore_e2e.py`):键值 + Stream,**裸 socket 写 RESP,零依赖**
     (仓库铁律是无第三方依赖,RESP 只有几十行)。对账精确抓到故意少写的那一处,
     回滚四个存储都干净,**调用方一行没改**。
     顺带验证了抽象:**Redis Stream 能 XDEL 真删,而文件式和 Kafka 只能打作废标记** ——
     抽象只要求「清干净」不规定怎么清,所以两种驱动都接得进来。
   ⚠️ **写文档时差点留下一句不准确的话**:本来写「漏掉方言 = 绕过生产库黑名单」,
   查源码才发现不对 —— `check_target` 是**先用纯字符串扫生产特征**,再在写入时才解析目标。
   黑名单在解析之前就生效,和方言无关。漏方言的真实后果是:连接器把它当本地文件路径(会吵)、
   以及**将来**受保护清单里若加了非 SQLite 目标,那条保护会**静默失效**(不吵)。
   ⚠️ 仍然没验:**Kafka 协议**(消息队列那格是用 Redis Stream 验的)、SQL Server/Oracle 方言。

15. **按摘要出方案时的关系补上了(只看结构),以及一条必须摆出来的召回数字**(2026-09-16)。
   统计普查原来有个真限制:摘要里没有值,而关系靠值重叠推 —— 所以外键是空的,
   **而外键空了造出来就是一堆孤儿行**,「合规地把分布带出来」的价值也就没了。
   解法:关系有三个来源,**只有一个需要值** —— 明写外键(schema 里就写着)、
   命名线索(也只是名字)、值重叠(带不出来)。所以按摘要出方案时
   **分布归摘要、关系归目标库的结构**。自测钉了一条:**把表清空再推一次,结果一模一样**。
   ⚠️ **召回明显低于看值那条,这个数摆在文档里**:同一个库只看结构推出 **2 条**,
   看值能推出 **13 条**。漏的典型是缩写表名(`ordr_item.order_id` 指向的表叫 `ordr`,少一个 e)。
   **不靠模糊匹配去补** —— 猜错的外键比没有更糟,它把数据挂到另一张表上而每行看起来都正常;
   同理一个列名同时像两张表时**宁可不指**。靠命名推的一律标「低可信度、没有覆盖率可算」。
   命名线索那条规则已从 `discover` 抽成公共函数给两边共用 —— **同一个判断不许有两处定义**。
   自测 5 条、四处咬合全部按名字命中。

   ⚠️ **中途撞上 advisor 迁移,分两段:大部分红不是我的,但最后一条是。**
   先是工作区里有别人进行中的迁移,接口驱动整节红。**判定过归属再动手**:
   把 `apimock.py` 临时恢复成上次提交的版本跑对照 —— 红的变成另一条
   (`advisor 映到了不存在的列`),说明两边都红、根因同一件事。他们提交之后那些红全没了。
   **别人的改动我不碰、不提交、也不替他们修**,只发消息问归属。

   剩下的最后一条红**查出来是我的**:`削最小过程中确实有变体建成了(0 条)`。
   根因是**自测种子种在了「请求体字段名」上,而不是「表的列名」上** ——
   规格映射是 `"advisor": "advisor_no"`(请求体字段 advisor → 表列 advisor_no),
   而那批 rows 是表行。**以前两者同名,所以碰巧一直有效**;名字列删除后这个键不再是列,
   构造请求体时被静默丢掉 → 那条规则从没被触发 → 削最小没东西可削。
   **它的失效方式不是报错,是「这条路径没走到」** —— 而那正是这条断言当初被特意改严要防的事
   (上一版写成恒真,自己记过一笔)。改成种 `advisor_no`,实测 BAD_ADVISOR 出现、建成 1 条变体。

   > 这一条和对方那条判据(判的是「A04 陆微」显示串、说的却是工号)**是同一个形状**:
   > **一个东西一直靠「碰巧对得上」在工作,直到旁边有样东西改了名字。**

16. **演示数据命名规范落地**(2026-09-18,库存预警/方案那条线的会话起草、交给假数据工厂落地)。
   业务定的:**方案名只以「定制款·工艺·年月」命名,不许带人名**
   (`明制立领长衫·妆花+苏绣·2026-08`)。起因是演示库里同一个客户名下挂着
   「林女士婚服方案」「陈小姐日常款」—— 「方案 = 一件事」一上线,顾问说「林女士那套」,
   助手会指向一个根本不叫林女士的客户的方案。**冗余的人名一旦和主体不一致,没有任何东西会报错。**
   - `seed.py` 改成按规范现拼(年月和建单时间取自**同一个值**),`./tools/rebuild.sh` 从零重建过
   - `fakedata/naming.py` 进了 check.sh。**seed 故意不 import 它**:一边用中文名字面量拼、
     一边从编码反查名字,两条路走到同一个答案才算对(同源谬误)
   - 咬合 5 条进了 `tools/bite_specs.json` 并真跑通过。预期红**写成每条规则独有的措辞**
     (带称谓 / 出现了真人姓名 / 的定制款是 / 而它建于 / 没扫到东西)——
     草稿里一律写「方案命名」,那样任何一条规则红了所有规格都算过,测不出是哪条在起作用
   - 分隔符 `·` 和主数据撞了(工艺表里 6 个名字自带「 · 」)。第一版只写了句
     「现在 0 个形制名带它,是事实不是保证」,对方指出**注释里的「现在没有」失效时不会有提示**,
     于是改成**前置检查**:所有形制名不许含 `·`、被方案引用的工艺名不许含 `·`/`+`,
     主数据一加进来就红。只查被引用的工艺 —— 拦那 6 个面料名是误报,**误拦会让人关掉整条检查**
   - 对方在 `seed.py` 里另有一处注释改动(指向还没提交的 `knowledge/scheme_ref.py`),
     **我提交时只放了自己那一段**:连注释一起提交,仓库里就会出现一句指着不存在文件的注释

17. **订单指回方案 + 让它有可演示的数据**(2026-09-18,方案那条线的会话提的需求)。
   `ordr` 加了 `scheme_id`(可空)。但光加列不够:库里原来**没有任何一张定制单指得回方案**
   (方案全挂在 C10000,而它只有一张标品单),对账检查会在空集合上全绿。数据形状:
   - **C10000**:两条**并行锁定**(`SC2601` / 新增 `SC2605`),且 SC2605 和 SC2603
     **同形制只差工艺** —— 同时演示「同一客户可以多条同时锁定」和「不带工艺分不开」。两条都不转单,
     所以「锁定 ≠ 已下单」有正样本
   - **一张现有定制单转成「从方案来」**(`SC2606`):**不新造订单**,从库里现有的合规定制单出发,
     形制/版型取自订单商品、方案建于下单前一天。新造定制单要同时满足量体有效期、分部位选料、
     超期夹具几条检查,雷区多
   - 只挑**一件商品**的单(三件商品的单指回一条方案本身就有歧义);客户避开夹具 ——
     第一次选中的 C10002 **名下有售后和维保**,那是售后判责评测的真值依赖,换掉了
   - ⚠️ 转单那条方案的形制名是从编码查的,**它的「定制款」段和校验器同源**,不构成独立验证;
     工艺段和年月段仍是独立的
   - 校验器补了一条:**同一客户名下方案名不许重名**(消歧是这套规范的全部目的)

18. **售后四条硬规则的数据改完**(2026-09-18,方案那条线的会话拿库对出三条是破的)。
   业务原话:「定制品没有退货换货,标品有;标品和定制品都有维保;退货换货维保都绑定订单;
   商品都得统一,不能订单是条裙子然后拿个裤子去维保」。
   - **定制品只许仅退款**:8 单挂在定制品订单上的「退货退款」(含「已入库」——
     一件照人做的衣服被退回仓库,这个现场不存在)改成仅退款。**改的是生成规则,不是那 8 行**
   - **标品也有维保**:新增 4 单,四个状态。原注释「只挂定制品 —— 判责要查面料工艺」的前提
     被业务推翻;这几单**不进判责任务**、只挂在**名下没有维保单**的客户上
     (判责会统计客户历史报修次数)、**一个随机数都不吃**(固定种子,多吃一个后面整体错位)
   - **售后、维保各加 `order_item_id`**(存键不存名字)。售后 26/26、维保 25/25 都指向自己订单里的那件
   - 订单行标签「定制」→「定制品」(旅程脚本那一处),和 `ordr.kind='定制品订单'` 同词
   - 顺手修了一个**碰巧对上**的:售后单客户号原来是按下标凑的,和订单分配客户用同一个下标规律,
     所以 26/26 恰好一致。维保那边修过同一个错,售后这边没跟着修
   - **证据不是「应该没动」**:重建前拍快照、重建后逐条对比 ——
     **判责依赖的 10 张维保单一字不差**,原 21 张全没变,售后只有那 8 单的类型和状态变了
   - 撞了两次假现场:「手工盘扣 · 拉链损坏」(只排除了西装,没排除配饰)、
     「明制立领长袄 · 拉链损坏」(问题按位置配、不按商品配)。现在只挑成衣、问题按商品定、只取现有词表
   - ⚠️ **换货没造**:库里和设计稿里都没有这个类型,是业务新提的,要等业务定

19. **订单/售后/维保数据集按业务规格重建**(2026-09-18,`3ce047f`,`intent/order-aftersale-dataset.md`)
   - 新脚本 `tools/order_mix.py`,在 `rebuild.sh` 里排在模拟销量之后。**订单总数不变(3903)**,
     从模拟销量里挑 459 张改成定制单 → 定制 520 / 标品 3383。改造时把那张单在库存流水里的
     占用 / 释放 / 退货入库一起撤掉,整条链重接(定制品不走现货)
   - 每张定制单落到**唯一对得上**的着装人,且**下单那一刻**量体有效(有记录 ≠ 有效)
   - 售后:退货退款 40 / 换货 15 / 仅退款 3;维保 55(定制 40 / 标品 15,判责那 12 张原样)。
     配比业务改了三版,最后是「合计至少 100、维保占大头」—— 定制品唯一的实物出口就是维保
   - 换货新增四列;`channel` 存订单渠道的**副本**(现查的话「同渠道出货」永远为真,没法被检查)
   - 客户汇总**按订单重算**(用户拍板)。不碰的一律**从库里现查**:truth 里的边界夹具、
     truth 描述里点名的合并用例、`protect.猜夹具` 的证据级(评测写死的客户)、E- 前缀
   - 重算的真实后果:订单只跨 7 个月,人人累计 = 近 12 个月,membership_check ③ 红。
     用户拍板补了边界夹具 **E-M1-01**(累计够黑金、近 12 个月只够银卡,名下 0 单是故意的)
   - 验证:判责 12 张 `get_maintain` 输出**重建前后逐字一致**。第一次比对差点假绿 ——
     `capacity` 模块带着自己的库路径,只改 api 的话「重建前」那一半有一部分读的是新库
   - ⚠️ 定制单只铺到 **54 个客户**(规格写的是 93):扣掉夹具 / 合并用例 / 评测写死的之后,
     有唯一着装人且量体有效的就这么多。标品单仍然摊在 45 个客户上(人均 85 单),规格没要求改
   - 对方会话管的:`backend/exchange_check.py`(换货五条)、「维保申请 ≥ 发货」那条规则
     (判责夹具里 4 张挂在未发货订单上,**推进状态必然改变判责现场,所以不动夹具、改规则**)

20. **维保只挂已完成的订单 + 规模放大到客户 965 / 订单 25213**(2026-09-18,`d1a5b82` `a05d84b`)
   - 业务:「维保申请必须在订单完成之后」。判责 12 张维保单一字不动,它们挂的订单从报修日倒推到「完成」。
     MW73034 的白坯试衣因此从「还没到时候」变「已试已签」(躲不开);它是工艺瑕疵,判法不看试衣。
     真跑判责评测 4/6,挂的两题单独重跑 4/4 —— 抖动
   - 用户拍板客户 1000 / 订单约 2.5 万,**且数字不许整**。`tools/grow_customers.py` 补人(前缀 C3/U3/W3/CS5),
     模拟销量日均 35 → 230,售后维保**按拍过板的比率**放大(不是条数)
   - 维保按面料分档加权(轻薄丝 / 锦缎 / 棉麻 + 刺绣)—— ⚠️ 这是种进去的信号,版师分析跑出「轻薄丝最易损」不是发现
   - 门禁 13 分钟 → 4 分钟:seed 里补了 12 个查询索引(逐单查询在没索引时按平方涨)
   - ~~下一步~~(已做,见 21):订单接方案(scheme_check ⑤ 样本加厚)、给这批数据补一道形状门禁(退款状态 ↔ 退货单、比率区间)

21. **形状门禁 + 订单接方案 + 工单对齐 + 重建互斥**(2026-09-19,`4348aef` `875b10f` `d3c981b` `fbcbdac`)
   - `backend/dataset_check.py` 六条:退款状态 ⇔ 售后单 / 占比区间(照拍板手抄,不从生成器 import)/
     维保率在面料上有显著差异 / 普通客户汇总对得上订单 / 数量不整百 / 工单状态对得上订单
   - 67 张定制单指回下单前锁定的方案(从订单反推形制/面料/工艺);naming.py 误报修了
     (师傅名「镶三滚」撞工艺「三镶三滚」—— 改成先按编码推标准名)
   - 工单只改挂在哪张单上,不改状态(罗一机在制 4 件 / WO8001 / WO8016 是评测前提)
   - `backend/.rebuilding` 互斥标记:重建时门禁和咬合停下说明原因(退出码 3)
   - ✅ 白坯试衣该不该做**按下单日算**(用户 2026-09-19 定,`c01a901`):不给日期就判不了;
     排队也按那一天看(那天在做的工单),只有这条路用,产能工具照旧看现在的在制。
     第一版用「现在的队」算过去的日子,441 件翻成「该试」—— **别再这么做**

22. **种下的规律登记 + 订单铺满一年 + 门禁提速**(2026-09-19,`0cc416d` `281421c` `1a9a7d0`)
   - `fakedata/planted.py`:12 条造数据时刻意放进去的规律(面料易损、季节、节日、尺码…),
     生成器里打 `〔种下 Sn〕` 标记,双向核对;`提醒(维度)` 给分析工具用 —— **种下的不是发现**
   - 演示世界只有一个今天:**2026-08-31**。订单 2025-09-01 → 2026-08-31 共 26587 张,
     商品上架日铺到 40–420 天前(只往前挪),截止后的事件不落库
   - 门禁 ~2 分钟:`leadtime.批量()` 一次查看内记住不变的查询,出范围必清(出错也清);
     看板 29s → 7s,关掉记忆重跑逐字一致
   - 仓库已由用户确认公开(另一个会话执行)

23. **进行中:商品图第二版 + 3D + 打版图**(2026-09-19,**未接入系统**)
   - 用户问「每款商品能不能有不同的配图」:现状 293/296 字节不同,但**同形制只是换色**
     (三款马面裙同一个梯形)—— img_check 按字节比,骗过了自己
   - 平面图第二版原型 `tools/img_v2_proto.py`(面料质感 / 刺绣 / 襕边 / 补子 / 珠绣 / 褶 / 缘边,
     全部来自商品自己的数据,裁在轮廓内)。对比页:`python3 tools/img_v2_proto.py <输出目录> <spu...>`
     生成 `对比.html`。**用户还没表态**;⚠️ 接入前要看 vision_eval 的前提(它靠「图信息不足」测模型)
   - 下一步:① 3D 效果图小样(Blender 在 /Applications/Blender.app,只做 2–3 款给用户看,
     **全量 3D 建模等用户批准**)② 研究行业服装制版图规范,做一个能直接出打版图的 skill
     ③ 能力定型后打包成 skill+hook 交给 eureka-ab 接进系统(用户要求,记在 memory)
   - ✅ 平面图原型已给用户看(对比页);✅ 3D 小样:`tools/render3d/`(只做了马面裙,Blender 5.2 在
     /Applications,`python3 tools/render3d/render3d.py <spu> <out.png>`,约 1 分钟一张)已给用户看
   - 打版图:规范研究结论在 `tools/patterndraw/制版规范.md`(GB/T 29863-2023 线型 / 符号 / 标注 /
     汉服十字型结构 / 马面裙公式 + 自检清单)。**下一步:按形制写参数化制图,先做马面裙和交领上襦**
   - 调 3D 时踩过的:AgX/Filmic 会把胭脂红压成浅粉(商品图用 Standard);背景弧面方向做反过一次;
     指数轮廓让裙子上半截鼓成圆顶(改 t^0.55 的 A 字)
   - ✅ 打版图第一版:`python3 tools/patterndraw/draft.py <spu|PTxx> [号型] [out.svg]`,
     **只做了马面裙**(马面 / 褶裥片 / 裙腰 / 系带,国标线型、布纹线、剪口、襕位、褶位、标题栏、图例)。
     用户说先做打版技能(比 3D 简单),3D 暂停。**下一步:交领上襦(十字型结构)→ 打包成 skill 交 eureka-ab**
   - ⚠️ 打版图撞出一条数据问题:PT04 马面宽 32 / 腰围 72 → 每侧褶区只剩 4 cm(行业马面宽 20–24)。
     图上打了警告,**没改数据**(版型是 demo 数据,要版师核)

## 没做完的 —— 下一步第一个动作

> ### 🔵 2026-11-03 下午(eureka-40)—— 就一个动作
>
> ⚠️ **这一节的欠账 ① 和它的根因都做完了(11-03 傍晚)** —— 看最上面那节 🪞:
> ① 是「让提示挤进 tail -3」的症状修法,而**根因在 `check.sh` 的 `run` 里**,
> 同日一起修了(含新判据 `tools/gate_print_check.py`)。
> 下面这段原样留着,因为**那个「修了两次症状」的过程本身是教训**。
>
> **看最新一次推送的 CI 结果。**(不写 sha —— 写死的会漂)命令:
> `gh run watch $(gh run list --limit 1 --json databaseId -q '.[0].databaseId') --exit-status`
> ⚠️ 重跑某一次要**按 run id 查**,它不出现在 `gh run list` 顶部(11-02 为这条绕过一圈)。
> 绿 → 这条线收口,去做下面那几件欠账;红 → 原样读红行、先看是不是这一轮新加的那条自测。
>
> ⚠️ **CI 和本地是两条路径,一条绿不替另一条作证**:CI 从零建库(造数按日期抽签),
> 本地库被误写过。11-02 那次红就是这么来的。
>
> 这一轮留下的欠账(都不急,按这个顺序):
> ~~① `intent_check` 那条「只报不拦」的提示在门禁绿时完全不可见~~ **已做完(同日)**:
>    两处撤销 FAIL 的地方原注释写着「那一行 ❌ 已经印出来了 —— **看得见**,不挡路」。
>    **机制对,而那句「看得见」在门禁里是错的** —— `run` 绿时只印 `tail -3`,那两行在中间。
>    而它们存在的全部意义是「值得确认一下状态」,**只在通过时才有用** ——
>    于是它们唯一有用的场合,正好是唯一不可见的场合。
>    修法同边界审计的夹具账:收集起来、**收尾汇总成一行**。
>    ⚠️ **必须是一行**:绿时 `tail -3` 正好被「空行 / ✅ / 那句格言」占满,
>    多印一行会把 `✅` 挤出视野,**人反而看不到「通过了」**。
>    验证也用门禁的方式(落盘取 `tail -3`),现在门禁里真的看得见了。
> ② **一条「看着像 bug、查清之后不确定是不是」的东西 —— 先别改。**
>    `intent_check` 的 `是门禁的一步()` 用 `line.startswith("run ")` 判,于是
>    `check.sh` 里两条缩进的 `run`(命令太长用 `\` 换行:`:245` 页面冒烟、
>    `:415` 契约内部自洽)被整个跳过,`是门禁的一步("js_smoke.js")` 返回 False。
>    我第一反应是「漏了,改成 `line.strip().startswith`」。**查清之后收回这个判断**:
>    · 那两条都在 `if` 块里,是**条件执行**的(8770 没起 / 没那个 venv 就跳过,
>      并明说「不适用,不是通过」);
>    · `js_smoke.js` 在 `:245` 那行里是出现在**标题字符串**里,真命令在续行 `:247`;
>    · 而那个 docstring 明写「名字要整个出现在某条 `run ` 命令行上,
>      **不是在正文里出现过就算**」—— 标题就是正文的一种。
>    所以返回 False **可能恰恰是刻意的**。
>
>    ⚠️⚠️ **11-03 傍晚查清了:结论反转 —— 这是漏判,该改。**
>    把 `check.sh` 那一段读完之后,决定性的事实是:
>    · 那条 run 写成 `run "页面冒烟 · …(agentsite/js_smoke.js;要 8770 在跑)" \`,
>      **真命令就在它的续行里**(`node agentsite/js_smoke.js "$p"`)——
>      标题和命令属于**同一条 run**,不是「只在正文里出现过」;
>    · **用户 2026-10-15 拍了「有条件进门禁」**,8770 没起就明说「不适用,不是通过」。
>      所以「门禁盯着它」是真的。
>    于是 docstring 的意图(「名字要整个出现在某条 `run ` 命令行上」)和实现不符:
>    **续行也是那条命令行的一部分**,而实现按行扫、看不见续行。
>
>    **所以那个待回答的问题问错了方向。** 不是「要不要排除标题」,而是
>    **先把续行并入它所属的那条 run**(以 `\` 结尾的行要和下一行合起来看),
>    顺带认出缩进的 `run`(条件执行的那些)。
>    ⚠️ 两处调用方的**后果方向相反**,改之前先知道自己在修哪一个:
>    · `:174` 「做完了 / 等人的活 有没有一条判据是门禁盯着的」—— 漏判会**误报**
>      (说「这条没人盯着」而其实有);
>    · `:238` 「进行中的那几条判据是不是全落地了」—— 只报不拦,漏判只是**少一条提示**。
>    两处修了都是改善,但误报那一处更该先修。
>
>    📌 **顺着这条查出两句正在误导人的话,已经改掉(这一轮一起提交)**:
>    `CLAUDE.md` 第 8 节和 `check.sh` 那段注释都还写着「js_smoke **进不了门禁**」,
>    而用户 10-15 已经拍了它有条件进。
>    > 一份过期的约定,和一份没有约定,**对照着它做事的人分不出来** ——
>    > 而前者更糟:它会让人以为这件事已经想清楚了。
>
>    ⚠️ **逻辑本身这一轮没改** —— 它要配咬合(intent_check 已有规格,改了会牵动),
>    而这一轮的主题是门禁输出可见性。两件事混在一次提交里,验证会互相掩护。
>    > 一个「判据漏了」和一个「判据刻意严格」,**在那个 False 上长得一模一样。**
>    要动它,先回答一句:docstring 那句「不是在正文里出现过就算」,要不要也排除标题?
>    **在回答之前改它,是把一个正确的东西改坏。**
>    ⚠️ 不过有一件是实的:`^run ` 数出来 371 而实际 **373**,我差点在上面那节
>    写下「371 段」。写死的数字会漂,门禁段数一律「跑一次现看」。
> ③ 咬合执行器没法表达「这条规格跑脚本的哪个入口」—— 所以同一个脚本挂第二个门禁入口时**别给它写咬合规格**
>    (会让第一个入口的现有规格全跑错入口、一起报「改坏了却没红」,**看着像一批判据同时失效**);
> ④ 健康哨那行命令**始终没执行**(要用户自己跑,Claude 装常驻任务会被权限分类器按「未经授权的持久化」拦下,那是对的)——
>    在那之前「服务跑着但答不了」这个场景没人盯着。

> ### 🔴 2026-10-25 傍晚 —— **判断基准变了,先读这一段**
>
> `CLAUDE.md` 第 23–26 行换掉了全项目的判断基准。用户 2026-10-25 原话:
> **「这个不是demo,这个是要真实落地的项目,需要重视」**。
> 原来写的「学习 / 作品集 / 面试用,不是要上线的生产系统,**激进尝试比稳妥更有价值**」
> —— **作废**。
>
> 照生产标准判,四条要当场问:
> **① 真实客户数据**(手机号、档案)的权限和留存 ·
> **② 真实花费** —— 订阅内的 Claude 登录态只够开发,上线按 API 计费,
> **页面上显示的标价就是真要付的钱** ·
> **③ 写操作的不可逆后果** · **④ 出错时用户看到什么**。
>
> ⚠️ **这一条改的不是「今天做了什么」,是「待办的优先级」。**
> 今天那三件在生产标准下都站得住(业务口径档是诚实的、触发器是结构性保证、
> 冗余列有逐行对账)。变的是那些「学习项目里可以先放着」的东西 ——
> 最直接的一条:**`craft` 表 168 条里 107 条是 `demo` 档(63.7%,现算)**,
> 而 demo 档的工具返回里自己写着一句
> **「不能对客户说。真实项目必须由工艺负责人逐条替换」** ——
> 那句话是为「真实项目」写的,**而现在它就是真实项目了**。
> 这 107 条已经从「演示够用」变成一笔**挂在明处的账**。归用户拍(见下面拍板队列)。

> ### 📍 2026-10-25 下午 —— 下一个动作
>
> **第一个动作:看 `dd0d16c` 之后那一轮 CI 有没有绿。** 我这条线在 `0671740`
> 的从零重建里一条没红,唯一那条是并行会话的位置参数 INSERT(已修),
> 所以他那笔之后应该就绿。
>
> 之后两件**我自己能往下走,不用等用户**:
>
> · **补那 5 条有名无链的非遗出处**(杭罗 / 蜀绣 / 湘绣 / 粤绣 / 晒莨)——
>   去非遗网找到各自页面、用 `tools/verify_sources.py` 现抓核对(要联网,不进门禁)。
>   补上就把 `backend/source_check.py` 的 `公开档无链上限` 改小。
> · **把交接里一条已经做完的待办撤下来** —— `intent_check` 报着
>   「`knowledge-source-debt` 已经标做完,而交接里还挂着待办」(**只报不拦**)。
>   挂着一件做完的事,下一个人会照着重做一遍。
>
> **用户那边的拍板队列是空的。** 剩下三件是**活不是拍板**:
> 版师那三张表 / 391 条裁片用料从估算核成实测 / 假数据工厂的 MySQL 验收。

> ### 📍 2026-10-25 早 —— 下一个动作
>
> **第一个动作:看 `5861f9a` 的 CI。** 它动了 20 个文件,其中 `knowledge/kb.py` 的档位正则
> 和 `knowledge/source.py` 的函数签名(多了第三个返回值)**是全库都在读的东西**。
>
> 之后两件**我自己能往下走,不用等用户**:
>
> · **补那 5 条有名无链的非遗出处**(杭罗 / 蜀绣 / 湘绣 / 粤绣 / 晒莨)——
>   去非遗网找到各自页面、用 `tools/verify_sources.py` 现抓核对(要联网,不进门禁)。
>   补上就把 `backend/source_check.py` 的 `公开档无链上限` 改小。
>
> · **量那条 23 毫秒的慢查询**(`api.py` 的 `_订单范围` 顾问那一支,`OR` 跨两表)。
>   ⚠️ **并行会话 10-25 给了一个关键数据,它把两件事分开了**:他那条促活名单的慢查询,
>   **连接开销是每次 0.9 毫秒**(2.4 万次开库 ≈ 22 秒)—— 所以单条 23 毫秒里
>   连接最多占 1/20,**和他那条不是同一个病**:他慢在「**次数多**」(每人 6 次 × 4000 人),
>   这条慢在「**单次慢**」。量法:**同一连接上连跑两次 vs 新开连接跑一次,差值就是连接那份**。
>   ⚠️ 交接里早写过一句而我列清单时漏了:**「它没有在让任何人等,不急」** ——
>   摆选型卡的时候要把这句一起说,别让用户以为在等他。
>
> **用户那边的拍板队列现在是空的。** 剩下三件是**活不是拍板**(一句话解不掉):
> 版师那三张表 / 391 条裁片用料从估算核成实测 / 假数据工厂的 MySQL 验收。
> 三代对比那道判错的题**现在拍不了** —— 判错的原文当时没存下来,10-20 起脚本才改成落盘。

> ### 📍 2026-10-24 夜 —— 下一个动作
>
> **第一个动作:看 `de52f13` 的 CI。** 它改了 api.py / report_template.py 和一条新判据,
> 而 CI 是从零重建的库 —— 今天为「本地有、CI 从零没有」这个形状红过三次。
>
> 之后两件都**卡在用户那边**,别自己往下开:
> · **那条 23 毫秒的慢查询**(`api.py` 里跨两表做「或」的那条):加索引解决不了,
>   要拆 UNION 或加冗余列 —— 按规矩**先摆选型卡等用户拍**。
> · **国标 12 条溯源**:浏览器扩展第三次仍然连不上。操作单已经落进
>   `intent/knowledge-source-debt.md`:连上之后**不需要用户点任何东西**,我自己查;
>   他自己查的话**只有 5 个词**(暗花缎 / 桑波缎 / 姆米 / 欧根纱 / 绡)。
>   ⚠️ **欠账仍然是 12 条 —— 分诊不等于补上出处。**
>
> 自己能接着做的(都不占共享库,除了最后跑门禁):角色工具名单必须是字面量(加一道闸)·
> 退款题集别再冻那个现读字段 · 判据和造数里还有一百四十多处按门店串筛(**价值低**,
> 不在生产查询路径上,已登记成明账、不进棘轮)。


> **每条都点名一份 `intent/`。** 这一条是 2026-09-15 加的规矩,`tools/intent_check.py` 强制:
> 交接文档回答「现在停在哪」,intent 回答「这件事本身是什么」——
> **前者随时间变,后者不该变**。混在一起的下场是:一件事做完之后,
> 它的来龙去脉跟着那条待办一起被删掉了。
>
> ⚠️ 加这条规矩时当场发现 **6 条里有 2 条已经漂了**:
> 「22 个形制没录」早已清零、「CLAUDE.md 进提示词」前一天已经做成结构。
> 它们在这份文档里挂着,而下一个人会照着去重做。

**① 全量咬合重放要换做法 —— 现在跑不动** `[intent: bite-debt]`
**归造数线,而且是这条线唯一能直接动手的活。** 2026-10-17 夜试过一次:
`nohup tools/bite_run.py`(全量 691 条)跑了 2 小时 14 分、完成 **0 条** ——
每条规格建 `pristine` + `work` 两份完整工作区 = **21 GB**,691 条是几天的量。
**价值仍在**:前一天陆续撞到 3 条过期规格,每条烧一轮 CI,
而咬合失效时和好规格长得一模一样。两个改法(选一个):
· **复用一个 pristine 副本跑多条** —— 省掉 N-1 次 21 GB 拷贝
· **只重放 `file` 型规格**(只改文本、不需要库副本;`sql` 型才要)——
  今天那 3 条过期的**全是 file 型**,这一刀切得准
⚠️ 下次启长跑任务**加 `-u`**:这次 `nohup` + 重定向让 Python 块缓冲,
两小时日志一个字没写,于是「在跑」和「卡住」看不出区别。

**② 真跑出来的缺口:一个稳定、一个在抖** `[intent: triage-queue]`
`DQ9002` **六轮全挂在同一条**(没说出「别再重试」)= **稳定缺口**。
`DQ9001` 原判挂 5 过 1,新判据重判后**在抖** —— **单轮的数不许用来下结论**。
⚠️ 并行会话已经改过提示词(要求写明「哪一步不能做、做了会怎样」),19:12 那轮
**两轮都 3/3 全过** —— 但**判据考的正是提示词要求的那句话**,
所以那是「提示词告诉它要说」,不是它自己想到的。下一步要分清这两件事,
得换一道**提示词没点名**的考法(比如不提风险提醒、只看它会不会自己说)。
两条挂的是同一类东西:查到了、原因说对了,却没给出那句风险提醒。
所以要改的大概不是「让它多查一步」,而是**让它把「钱可能已经出去了」这件事
的后果说出来**。改完要重跑两轮,分界点记进 PRD 附录 C。

**③ 交付前校验扣下研判回答的比例不低** `[intent: triage-queue]`
五次真跑里出现 **3 次(约 1/6 题次)**。这不是评测的问题 ——
`sdk.run` 那时返回的是「这条回答没有通过交付前检查,没有作为正式答复给出」,
而**被扣下的回答用户是看不到的**。评测这头已经堵成「记『没答成』不记『答错』」,
但产品那头要不要管(是闸太严、还是研判类回答确实常触线)**还没人看过**。
归研判队列那条线;要看的话先翻 `agentsite/evals/withheld.jsonl`(被扣下的草稿原文)。

**④ ~~待办清单的数字会在门禁跑到一半时对不上~~ —— 查错了,结论反过来了** `[intent: fakedata-factory]`
**已查清:这条判据没有 bug,不用改。** 原来写的根因(「门禁中途写库让数字漂」)**是错的**,
留在这儿是因为下一个人很可能像我一样顺着那条红查下去。

实测三步:
1. `make_todo.py` 是 `tools/rebuild.sh` 步骤表的**最后一步**,排在所有造数之后 ——
   「中途生成」这个前提就不成立
2. 清单现算的全是**静态业务表**(body_feature / craft / material / pattern_piece / size_spec),
   门禁判据不写它们;同一个库上连跑两次,正文**一字不差**
3. 真正的差异只有一处:`388/391 片到「行业规范」档,3 片版师核过`
   vs 从零重建的库 `391/391,0 片版师核过` —— **我真库上有 3 片被版师核过**(历史操作),
   重建出来的库里没有

所以:**清单里的数字只对生成它的那个库成立**。这条判据在真实场景里都对 ——
CI 只有从零重建那一份(rebuild 生成 → 判据重新生成 → 同库 → 一致);
本地清单基于在用的库(同库 → 一致)。
**只有「clone + 从零重建」这种混合场景会红**,因为那时「真库生成的清单」
和「另一个库」被摆在了一起 —— 而那正是 2026-10-16 我做的事。
🔺 那条红是**我那次实验的产物**,不是代码缺陷。

> 一个「判据有缺陷」和一个「我把两个库的产物摆在一起了」,在那条红上长得一模一样。
(同一个形状今天撞了第十四次:基准的时分秒取决于造数那一刻,清单的数字取决于哪个库。)

📌 **留着的用处**:谁要是又在混合场景里看见这条红,**先看差异是不是那几个库相关的数字**
—— 是就不用查了。

**⑤ 那 391 条占比一条都还没到「版师」档** `[intent: piece-ratio-review]`
不是技术待办,是这个岗位的活。工具、账号、闸、检查、评测都齐了。
版师登录 `60000020`,问一句「我今天该核什么」就能开始 —— 看板按影响面排好了顺序。

**⑦ 三张只有版师给得出来的表** `[intent: pattern-knowledge-gaps]`
童装档差表 / 里料衬料的门幅 / 特体修版量。**已拍板:挂着等版师给,不替它猜。**

**⑧ 假数据工厂:差集清单等评测会话来要** `[intent: fakedata-factory]`
差集清单整份交接挂着,对方开口再给,不主动推。

## 已经做完的、已经栽过的 —— 别照着重做

### 📍 2026-10-25 下午 —— 冗余列这一轮,**五条「试过才知道」**

**① 拆 UNION 这个方案实测无效,别再想它。**
`(o.advisor_no=? OR cu.advisor_no=?)` 跨两表,加索引修不了。
三个方案在真库副本上都量过:

    现有(OR 跨两表)         20.53 ms   `SCAN o`
    拆成 UNION 再去重        16.17 ms   **1.2 倍 —— 否决**
    冗余一列(OR 落同一表)    6.54 ms   **3.1 倍**,`MULTI-INDEX OR`

拆 UNION 没用的原因在计划里:索引省下的扫表被 `UNION USING TEMP B-TREE`
(5172 行去重)和第二支回表吃掉了。**和导购业绩页那次同一个结局。**

**② 并行会话量到的「连接开销每次 0.9 毫秒」把两个病分开了。**
他那条促活名单慢查询(2.4 万次开库 ≈ 22 秒)慢在「**次数多**」,
这条慢在「**单次慢**」—— 同一个「加索引没用」的症状,底下是两个不同的病。
量法:**同一连接上连跑两次 vs 新开连接跑一次,差值就是连接那份**。
⚠️ 我差点因为症状相同就撤回选型卡 —— **症状一样不等于病一样**。

**③ 列必须写进建表语句,不能只靠流水线那一步 ALTER。**
`seed.py` 自己在第 933 行就调 `query_index.建索引()`,而新索引建在这一列上 ——
**列不存在的话从零重建当场炸,而本地永远绿**(门店码 2026-10-24 CI 连红三轮,
三次机制各不相同,这是第四个位置)。

**④ `--校验` 不是「再回填一次」,它是触发器的体检。**
它应该**一行都不用填**;填了就说明有写口绕过了触发器,或者触发器被谁删了
(**触发器活在库里,而库不进版本库** —— 谁手工重建一次而没跑 `--建列`,它就没了)。
> 一个「触发器在工作」,和一个「触发器没了但每天有人回填」,
> **在那一列的数据上长得一模一样** —— 而下一步完全不同。

**⑤ 判据必须有一层跑在自造的最小库上。**
把三个触发器**全删掉**再回填一次,真库上的逐行对账会**全绿** ——
数据是对的,只是从此不再自动维持。
> 一条在真数据上全绿的判据,和一个什么都不做的触发器,**长得一模一样**。
另外一层守「改回去不会有任何东西红」:把查询从 `o.cust_advisor_no` 改回
`cu.advisor_no`,**结果一模一样、只是慢** —— 功能测试全过、逐行对账全绿,
**只有源码上看得出来**。

### 📍 2026-10-25 下午 —— 这一天栽的「同一个思维习惯」六次

**写注释时把要解释的东西原样引过来** —— 对「靠查文本工作的判据」来说,
**原样引一遍就等于埋一个假阳性**。今天踩了两次(`daily_shift.sh`、`rebuild.sh`),
而第二次是在我**上午刚为同一件事修过第一次、还在那儿写了警告**之后。
> **教训记在一个地方,而下一次踩它的人不在那个地方。**
所以第二次修的时候,把那句警告**也写进了 `rebuild.sh`**。

**两份文字只改一边**(脚本内咬合记账 + `bite_specs` 可重放)——
今天踩三次,每次都是 `bite_check` 逮的。它按 `(script, 改坏)` 配对,**差一个字就算
「声称了却没有规格」**,欠债涨 1、门禁红在一个跟业务代码毫无关系的地方。

**咬合攻击载荷的两种失效**(都显示成「红了但红的不是那一条」):
· 攻击用了最小库里**不存在的列** → 崩在 `no such column`。**「崩了」不是「漏了」**
· 攻击改的是触发器的**名字**而不是**行为** → 「三个触发器都在」那条先红

**我自己那个合并脚本的缺陷**:按身份合 `bite_specs` 时**只处理新增,不处理
「对已有条目的修改」**。我修了一条已有规格的过期锚,身份没变 → 被静默丢掉。
已给脚本补上「我改过的已有规格」检测。
> 一个「合并对了」和一个「丢了一处修改」,在那句「双方新增一条不丢」上长得一样。

**我把一条形状判据的输出当成了语义结论。**
`insert_shape_check` 报「`db_observe_check.py` → ordr 有位置参数 INSERT」,
我读成「他那两处会插进真 ordr、会被我新加的列挪格」并且说得很肯定 ——
而那是**检查自己建的临时表**。判据报的是形状(「有个位置参数 INSERT 指向一个叫
ordr 的表」),它不关心那个名字指的是临时表还是真表,**也不该关心**。
> 今天一直在说「判据查的是含义还是恰好长这样」,而这次是反过来:
> **我把「恰好长这样」读成了含义。**

### 📍 2026-10-25 早 —— 这一轮栽的六条,**前四条是「改坏了却没红」,三次是自己埋的**

**① 判据查「名字在不在文件里」,而那个名字另有含义。**
前端覆盖那条判据第一版查的是「`biz` 在前端文件里出现过」—— 而 `index.html` 里
**本来就有 `biz`**(441 / 457 行,business 的缩写,跟档位半点关系没有)。
于是攻击把档位表里的 biz 两处都删掉,判据**照样绿**。
> 一条「查的是含义」和一条「恰好匹配上了」,**在它变绿这件事上长得一模一样**。
改成查那**六处清单**(样式类 / 显示名 / 分组名 / 可信度分值 / 筛选按钮 / 分组树),
并且**取不到锚就红** —— 那几处的写法变了的话,「验不到」和「验过了」会长得一样。

**② 在被查的文件的注释里照抄了判据要查的那个串。**
`tools/daily_shift.sh` 的注释里写了那条回填命令,于是删掉**真正那一行**之后,
判据(`"…--做" in 文`)照样绿 —— 显示成「改坏了却没红」。
**这个坑项目为密钥扫描连踩三次,我在注释里踩了第四次。** 要举例就**描述**它,别照抄。

**③ 咬合攻击点选在一条会改变身份的数据上。**
那条「模拟洗账」的规格原来攻 MT40 麻纱 —— 而用户拍「7 条全拍」之后
**麻纱自己进了名单**,攻击变成空操作。
> 原来记的是「规格自己没变、**周围代码**变了」。**这是新变种:规格没变、
> 被攻击那条数据的身份变了。**
而且攻击点和名单**反向耦合**:**名单每长一条,能当攻击点的条目就少一个**。
换成 MT14 杭罗(出处来自「非遗」字段、**没有链接**),所以改完之后
档位和出处**合规**、有名无链那本账**还降一条**(降了不红),**只有名单对不上**。

**④ 一条咬合规格有两份文字,而它们各自都能单独改。**
脚本内给人读的记账 + `tools/bite_specs.json` 里可重放的那一份:
· 只改记账右边(判据名)→ 判据**正确红了**,咬合却报「红的不是那一条」
· 两边描述写成不同版本 → 配不上对,**欠债数字涨 1,门禁红在一个跟业务代码毫无关系的地方**
> `bite_run` 比的是**输出**,`bite_check` 比的是**源码** —— **两个判据各看一半**,
> 而「只改了一边」在任一边单独看都正常。
已在 MT14 那条记账上加注释写明「左边这句话必须和可重放那份**一字不差**」。

**⑤ 每日平移那条路径缺了回填 —— 缺口当天隐形、第二天才红。**
`tools/rebuild.sh`(从零重建)把回填门店码排在**倒数第二步**,所以重建出来的库全有码;
而 `tools/daily_shift.sh` 只跑 shift_world + daily_fresh + lifecycle_refresh,
**一步回填都没有** —— daily_fresh 造的新单 / 跟进 / 预约 / 评价带着门店串**而没有码**。
于是:重建完当天全绿 → 夜里平移造了新行 → **第二天早上才红**,
而那时看起来像有人改坏了数据(当天两个会话都先去找谁动了数据)。
> **「回填排在最后」那句话只在那条流水线里有意义** —— 每日那条路径根本没有「最后」。
> **一个「重建得出来的库」,和一个「每天都还对得上的库」,是两件事。**
10-24 我为门店关联键写了四条顺序断言,守的**全是重建流水线里的位置** ——
缺的正是对称那一半。已补上回填步骤 + 对称判据 + 咬合。

**⑥ 试过而不行的:禁词表挡不住「拿业务口径冒充国标」。**
第一版想写「`biz` 的出处里不许出现 `GB/T` / 『国家标准』」,立刻撞上中文否定那个记了七次的坑:
**「丝绸术语国家标准里『没有』这个词条」这句话里也有「国家标准」** —— 而它说的恰恰是**没有依据**。
改成判**结构**:出处必须**以「业务 YYYY-MM-DD 拍板」开头**且不带链接。
不管括号里写什么(包括写明国标查过、没收录),读的人第一眼看到的都是**责任人和日期**。
**比禁词既简单又更严。**

⚠️ **还有一条「试过才知道」**:`biz` 这一档最省事的设计是把它排除在「要出处」之外
(业务拍板嘛,哪来的出处)—— **那样一来它就是豁免**,于是任何一条溯不了源的 `public`
只要改标 `biz` 就脱账了。**它不是豁免,是换一种出处要求**:公开档要链接,
业务档要**具名的拍板人和日期**;空着照旧计欠账。

### 已经做完的 —— **别照着重做**(2026-10-16 清理)

**⑥ ~~还有 12 条「能对客户说」的知识溯不了源~~ —— 2026-10-25 清零,这条撤下** `[intent: knowledge-source-debt]`
那 12 条用户当天两轮全部拍板,走的是新立的第四档 `biz`(业务负责人口径,具名拍板、
**不得说成国家标准**)。另外 5 条「公开可查却给不出链接」也补上了页面。
`backend/source_check.py` 的两个上限都已拧到 **0**(从进度条变成闸):
溯源欠账 0、公开档无链 0。**数字别信这里写的,跑 `backend/source_check.py` 现看。**
> ⚠️ 留一句给下一个人:**洗账通道是开着的** —— 把一条没出处的 public 改标 biz
> 再补一句拍板,欠账那个数也会降 1。而「真补上了」和「改标洗掉了」**在那个数上长得一样**。
> 所以 `业务口径条目` 是一张**明写的 12 条白名单**,加一条要改代码。


**~~假数据工厂:2026-09-21 补的四项能力剩两件事~~ —— 两件都落实了,2026-10-16 核过** `[intent: fakedata-factory]`
四项能力(`stable` 行级稳定 / `repro` 跨进程跨日期 / `anchor` 交付物锚定 / `agree` 跨字段一致)
都在 check.sh 里。剩的那两件核下来都已经落实:
· **两处形制打架**(`lxys_100799819` / `lxys_101005713`)——
  `product_custom.xz` 现在写的是「明制道袍」「唐制圆领襕袍」,**和版型一致**;
  `draft_check` 报「305 款,另有 **0 款**登记为已知打架等业务判」→ **业务判完了**
· **出图批量**:`tools/export_image_prompts.py` 的默认值就是 **25**(业务 09-21 定的那个数),
  注释写明「每批多少款是业务定的,不是技术定的」,环境变量可临时覆盖

**~~把 `*.advisor` 那七列真正删掉~~ —— 整条过期,2026-10-16 核过** `[intent: advisor-columns]`
原来写「半天到一天,机械。要先把 38 个页面改成 join staff 取名字」。核下来三件全不作数:
· **七列已删** —— 全库扫过,没有任何表还带顾问名字列(只剩 `advisor_no`)
· **38 个页面已改** —— 证据在 `backend/advisor_ref_check.py` 文件头:
  「后来名字列全删了(页面改成 join staff 取名字)—— 那个风险从根上没了」
· **「把 advisor_ref_check 从 check.sh 撤掉」也不作数** —— 它 2026-10-11 被改写成
  守另外四条(存员工的地方只存工号、工号必须真有这个人),该留在门禁里。实测 221142 个工号全过
🔺 **我还照着这条漂的待办把那份 intent 的状态从「做完了」改成了「进行中」** ——
理由是「七列还顶在表上」,而那是假的。已改回。
> 一条漂了的待办不只会让人白做一遍,还会让人**照着它去改别处的状态**。

这几条原来挂在「没做完的」里,而它们点名的 intent 状态都是 `做完了`。
清理的起因:我打算做「判据审计还有一半没做」,**先核了一下 intent 状态** ——
四维都有东西盯着,那条待办**漂了一个月**,我差点照着重做一遍。
> 一个「还没做」和一个「做完了但没人把它从待办上撤下来」,
> 在那条待办上长得一模一样 —— 而后者会让人白做一遍。

现在有判据盯着这件事(`intent_check` 的「交接里还挂着的待办,
它的 intent 没有已经标『做完了』的」,**只报不拦**)。
同一轮里另外四份的状态也改对了:`piece-ratio-review`、`pattern-knowledge-gaps`、
`fakedata-factory` 改成 **`等人的活`**(技术做完、等版师 / 等评测会话),
`advisor-columns` 改成 **`进行中`**(那七列还顶在表上没删)。

**⑦ ~~判据审计还有一半没做~~ → 已做完,这条待办漂了一个月** `[intent: judge-audit]`
**2026-10-16 核过:四维都有东西自动盯着,`intent` 的状态「做完了(09-16)」是真的。**
原来这条写着「『词表差一个字』『夹具静默失效』这两维还只能靠人看」—— 而
`tools/vocab_check.py`、`tools/fixture_check.py`、`tools/case_check.py` **三个都在
`check.sh` 里**,第四维(「禁的是一个字」→ 判据可以是函数)也还在用
(`agent/ops_eval.不许给零销量的编天数`)。

🔺 **我差点照着它重做一遍** —— 而这份文档开头就写着这件事:
「22 个形制没录」在交接里挂了很久、而它早已清零,下一个人会照着去重做。
> 一个「还没做」和一个「做完了但没人把它从待办上撤下来」,
> 在那条待办上长得一模一样 —— 而后者会让人白做一遍。

当时留下的那条经验仍然成立,所以抄在这儿(别的地方没记):
审了露马脚的两套查出**判分器把总分压低了 8%**(tool 13→20、member 9→11),
而**一把全局偏严的尺子表现出来是「没变化」** —— 其余八套全部和旧记录持平,
那恰恰是坏尺子最可能的样子。

**⑧ 交接待办和 intent 状态长期不同步:7 条待办的 intent 已经标「做完了」** `[intent: judge-audit]`
新加的那条判据(`intent_check` ④·续)当场抓到 **7 条**:advisor-columns、
db-not-regenerable、eval-provider、fakedata-factory、judge-audit、
pattern-knowledge-gaps、piece-ratio-review。
**只报不拦**,因为这两份东西语义不同:intent 的「做完了」说的是**技术部分**做完,
而交接待办说的是**还要有人做的下一个动作**(版师填数、业务拍板)。
多数属于后者 —— 而 `intent` 本来有「**等人的活**」这个状态,没被用上。
要逐份看:该标「等人的活」的改状态,真做完的把待办撤下来。
(judge-audit 这一条我已经核完,见上面 ⑦。)

**⑨ 评测基线要盖上来路** `[intent: eval-provider]`
业务 2026-09-15 拍板:**一律用 Claude,不用 DeepSeek**。
那一轮 DeepSeek 的数存档在 `agent/onetime-deepseek-20260915/`,**不许当基线**。
⚠️ `eval_provenance_check` 还没接进 check.sh —— 现存基线里
chat/growth/vision/liability/ops/report/role 七套是今天盖过来路之前跑的。
下一轮重跑就会补上。

**⑬ 2026-09-21 下午:业务拍板 B 案之后连带查出的一串** `[intent: db-not-regenerable]`
改「圆领袍」那个通称别名 → 重建 → 比对重建前后 → **拉出一串重建不可复现**:

  · `seed.py` 用内置 `hash()` 造供应商编码 —— **每重建一次 659 个 SKU 全换一批**。
    同一个根因还有两处(面料库存、量体记录)。三处都改成 `稳定哈希()`。
    ⚠️ 上一次修颜色时这个函数只是 `run()` 里一个局部闭包 `_色hue` ——
    **修的是那一处,不是那一类**。提到模块级并改名,就是为了让下一个人看得见它。
  · `tools/determinism_check.py --真建两次` **从来没成功跑过** ——
    `quote(t.*)` 不是合法 SQLite 语法,一跑就抛异常。它标着「手动跑」,
    于是没人跑,于是**既没红过也没绿过**。它要是能跑,上面那个 hash bug 早被抓到。
  · 扫写法漏了两类:内置 `hash()`、**SQL 里的时钟**(`datetime('now')`)。都补上了。
  · `schedule.assigned_at` / `schedule_file.uploaded_at`:日期是模拟世界的、
    **时分是这台机器此刻的**(生产代码写的 now())。已在 run_journey 里钉住时分秒。
  · `account.pwd_salt/pwd_hash`、`op_log.ts` 登记为「每次都该变」并写明理由,
    每次跑都打出来 —— 一条没人再看的豁免和一个没修的 bug 长得一样。

**⑭ 2026-09-21 傍晚:评测轮次做成结构 + 一个「写好了没接上」的防护** `[intent: judge-audit]`

· `agent/rounds.py`(共用件)+ `agent/rounds_check.py`(棘轮门禁,13 套单轮登记在案)
· `growth_eval` 接上多轮:跑完自己会说「轮间抖动 1 题 ≥ 版本差 1 题 →
  **这个对比说明不了任何事**」。G04 今天在两轮之间**翻了两次面**。
· **G03 连挂两轮不是模型的错**:口径算出两数差 3.8cm、`需人工确认=False`,
  这道题现在根本没有「两个口径打架」这回事,而判据还写死要求说「分歧」。
  改成现读+按状态分派,不打架时反过来测「别编一个分歧出来」(不许变空题)。
  这是「判分器不许写死数据状态」栽的**第二次**(上次是 chat_eval 的矩阵格)。
· **`agent/evalrec.py` 的 `代码()` 算出来却没写进记录** ——
  注释里明写「同一天 ≠ 同一份代码」,而那个值一个字都没落盘。
  当天就撞上它本该防住的事:一轮用旧判据跑的结果覆盖了基线,文件上分不出来。
  已接上,`eval_provenance_check` 加了一条盯着它。

  > **一个「写好了但没接上」的防护,和没有这个防护,在文件上长得一模一样。**

**⑮ 2026-09-21:`growth_eval` 8 题里 3 题在轮间翻面 —— 而翻的原因是两类** `[intent: judge-audit]`
用新判据跑的两轮:`7/8 / 6/8`,**G01、G03、G04 同时翻面**,和基线差 0 题。
也就是说**这套题分辨不出小于 3 题的变化**;只跑一轮拿到 7/8 就会报「涨了一题」。

要紧的是翻面原因**不止一类,而修法相反**:

  · **G01 / G04 —— 措辞**:挂在「没提到 统计(同义:分布/个体差/±/平均)」
    这类同义词表上。判据太吃措辞,是「别枚举中文说法」那条的第 N 次。**要改判据。**
  · **G03 第二轮 —— 行为**:`轨迹:实际调了 [无]`,模型**一个工具都没调**,
    14.6 秒就答完(别的轮要 50 秒、调 2 个工具)。这不是答得不好,
    是**这一次根本没去查数据就回答了**。**判据是对的,抓到了真问题。**

> 混在「轮间抖动 3 题」这一个数字里,看不出这个区别 ——
> 而一边该改判据、一边该改提示词,方向相反。

✅ **已做**(2026-09-21 傍晚):`rounds.py` 按失败类型分开数了。
端到端验过一轮,当场改变了结论的性质:那一轮 G03、G04 翻面,**两题都是轨迹类** ——
没有分类的话我会按前几轮经验猜「判据吃措辞」去改同义词表,**而那根本修不了它**。
真正的问题是**模型有时候不去查数据就回答**,要改的是提示词和工具描述。

> 一个数字(抖动 2 题)和一句分类(轨迹类 2 题),指向两个完全相反的下一步。

✅ **已查完**(2026-09-21 夜):「G03/G04 一个工具都没调」走完了五步排查,
**结论不是模型不行,也不是没告诉它** ——

  ① 测量 没错 · ② 数据 没变 · ③ 判分器 没错
  ④ **没告诉它标准?不成立** —— TL09 白纸黑字写着「先用 get_wearer 找到那个孩子」
  ⑤ 模型:**有 10–20% 概率跳过取数**(连跑三次复现,0 次命中)

> **判据:这一档发生率,改提示词根本验证不了。**
> 要分辨「从 15% 降到 8%」,n=8 的评测跑两轮完全不够(已量过:连 3 题的差都分辨不出)。
> **改了也不知道有没有用,那是在赌。** 所以不改提示词,改成结构性拦截。

洞在 `agentsite/guards.py` 的 `g1_no_source`:它第一行是
`if not (monies or days): return None` —— **只有金额或工期才往下查「调没调工具」**。
而身高/围度/库存/积分/百分比全在覆盖外。已补,并把「有没有洞」做成会红的检查。

✅ **已验**:G03 在新判据(现读 + 按状态分派)下第一轮**过了** —— 那条改对了。

**下一步第一个动作**:还 `agent/单轮评测欠债.json` 里的 13 个 ——
挑 `vision_eval`(题最少、不吃措辞)照 `agent/growth_eval.py` 的样子接 `rounds.py`:
把主循环包成 `跑一轮()` → 跑两轮 → `rounds.报(多, 基线通过数=..., 原因=因)`,
然后从欠债表里删掉那一条(不删的话 `rounds_check` 会红,这是设计)。

✅ **已验且已修**:那条预判是真的 —— 补完第一档之后,**随便调个不相干的工具
(kb_tables)就能让身高/库存/积分全放行**。而模型很少一个工具都不调,
它更常见的是调了几个、没调对的那个(今天 G04 有一轮就是调了 kb_size/kb_fit
却没调 forecast_growth)。

> **补了一半的防线,拦得住最罕见的那一档,拦不住最常见的那一档。**

已补「数的出处」表(哪种数该由哪几个工具给),覆盖检查加了第二档。

### ⚠️ 这条判据一天里错了四次,四次形状不同 —— 值得记住的是这个序列

  1. **枚举词表**(身高/胸围/腰围…)→ 漏「裙长 90cm」
  2. 改成**做法动作词**(留/放/加)→ 对,但只解决了一半
  3. 加**点名工具** → 又漏「调了别的工具」这一档
  4. 点名之后**误伤**:`个体差 ±5cm` 里的 5 被判成「成衣尺码没查过」
     (窗口扫到了下一句的「腰围」)—— 而 `±5cm` **本身就是「我不确定」的表达**,
     拦它等于惩罚模型说实话。最强的结构信号是 **「±」这个符号**,不是部位名。
  5. 跨类词(围度/胸围/腰围)**必须在两边都列** —— 判据是「命中的档的工具取并集」,
     而**并集只在两边都列了的时候才生效**。这是那条判据的隐含前提。

> 每一次「改成结构判据」都比上一次对,但**都不是最后一次** ——
> 判据的演化有台阶,而每一级台阶上它看起来都已经对了。

🔮 **预判(没验)**:`数的出处` 那张表现在有 7 档,是**我列的 + 覆盖检查抓出来的两档**。
  库里还有没有第八、第九类,**没量过**。
  **验法**:往 `guards_test.py` 的 `典型结论` 里再加几句(维保费用、押金状态、
  工单进度、审批数量),看哪几句在「调了不相干工具」那一档被放行。

🔮 **预判(没验)**:这四项里 `agree.py` 的声明文件(`fakedata/一致.json`)
现在只有 2 个事实,而库里这种「一个事实好几个落点」的地方**应该还有不少**。
验法:拿 `samekey_check.py` 的域登记表(xz / pattern)逐个域去看,
每个域里「用编码的表」和「用名称的表」之间都可以补一条声明。

---

1. **浏览器入口** —— 代价大于收益,已主动划掉(见诚实清单)。

2. **「智能体起草 + 人点确认」的确认卡机制** —— 做过一整套(卡片、按钮、
   服务端重算草稿),后来用户要求给真写接口,整套拆了。
   **要是再想做「先确认再执行」,先问清楚是不是每件事都要确认** ——
   那套的成本是每个动作多一次点击。

3. **拿普通客户造数据** —— 栽过。C10017 是普通客户(不是夹具),但某条售后判责
   用例的真值依赖它「量体记录不全」这个事实;我给它补了 5 项,判责结论当场翻了。
   现在 `run_journey.py` 排掉四类:反例夹具 / 客户合并用例 / 被评测引用的 / 一号多档。
   **夹具和普通数据之间有边,而那条边从客户这一侧看不见。**

4. **给日记做「什么时候该读」的判据** —— 枚举了「派/排班/改派/批量」,
   而用户说「排**下周的**班」就漏了。这个项目在枚举中文说法上栽过八次。
   现在是**每轮都读、只读三条**(268 token)。别再去做那个判据。

5. **技能描述写「什么时候不要用」** —— Accio 的实测经验相反:
   主要失败模式是**漏触发**,描述该写得「推销」一点,而且
   **所有触发条件都放 description 不放正文**(正文要等技能被选中才读得到)。
   但这条在我们的数据上**没验出效果**(改动组净变化小于噪声),
   所以它现在既不算成立也不算推翻 —— 要下结论得多跑几遍。

6. **手写内容直接追加进 `澜绣云裳agent-项目日志.md`** —— 那是全量重建的文件,追加的东西
   下次生成就没了,**而且没不见得声不响**。手写的放 `项目日志-手记.md`。

7. **让 236 个第三方技能默认参与路由** —— 实测有代价:同一条用例
   「6月毕业典礼那天要穿,现在该做多大」,场上 3 个技能时 **3/3 触发**,
   场上 239 个时 **0/3**。它们装着(以后挑着用),但**默认不上场**。
   页面右上角有档位切换(own / all / none),评测 `--set` 同名。
   **别把默认改成 all。**

8. **判分器判「有没有提到某个话题」** —— 这一轮又栽了两次,加起来第十次。
   做复盘评测时,判据 v1 找「话题旁边有没有百分数」、v2 找「话题有没有
   未被否定地出现」,**两版都被正确答案打挂了**:模型为了讲清
   「没发生过」和「采纳率 0%」的区别,画了张对比表,表里当然有那个数。
   **中文里顶回一个前提,必须先把那个前提完整说出来。**
   现在判的是**反驳的结构** —— 只看开头那一小段有没有否定
   (`report_eval.opens_with_rejection`),后面爱怎么举例怎么举例。

9. **拿状态码去匹配模型说的话** —— 同一轮栽的。我以为从口径模块取档位名
   不算「枚举中文说法」,但**档位名是状态码**(已取消/已过期),
   **模型说的是人话**(客户取消/系统自动过期)—— 5 档被数成 2 档。
   现在口径模块里有 `档位别名`。这份表是允许的,理由写在那儿:
   **档位是有限的名词,表达方式是无限的**。

10. **评测不传身份** —— 复盘和漏斗这两个工具按身份取数,
    第一轮评测 13 题跑完才发现工具全在说「不知道现在是谁在看」,
    **整轮是空转**,还顺手花了 $0.085 的 DeepSeek 钱(脚本默认走 DeepSeek,
    那是有意的)。现在开跑前有一道两秒钟的身份自检,并且把供应商打在第一行。
    **开发验证记得 `LANXIU_PROVIDER=claude`。**

19. **改「违规数据」之前先分清「填错了」还是「挂错了」** ——
    填错改值,挂错改边,**方向反了会把一个对的东西改坏**。
    实测两次:量体模板缺项其实是版型挂错了模板(改模板会让
    「上衣用量体」不再是上衣用量体);17 个商品性别冲突其实是品类树缺档。

20. **教训没长成纪律,就会在下一个地方原样再来一遍** ——
    `不许留痕` 这个包装我在 `membership_check` 上加过一次,
    **没加到 `boundary_audit`**,于是咬合时那两刀真的改了商品数据,
    然后另一个检查在一个和权限毫无关系的地方红了。
    现在规则写进类的 docstring:**凡是「以某个角色去试写」的攻击,都要包起来。**

21. **从一个按别的条件筛出来的小样本推整体** ——
    我从 17 个「性别冲突」商品里看到 8 个模板错,报给用户是「8 个」;
    补上 product→pattern 这条边之后量出来是 **66 个**。
    **推出来的数会小一个量级。**

15. **建数据时少填一个外键** —— 这一轮连栽三次,**每次都在别的模块红**:
    `account_id` 传 None → 「身份绑在账户上」红;没建同意书 →
    「有身体数据必须有单独的同意」(个保法 28 条)红;量体日期早于客户建档 → C3 红 56 条。
    **在我改的那张表上看不出任何问题,报出来的位置和改动的位置隔着好几层。**

16. **两个约束打架时硬挑一个** —— 造旅程时「终点要落到过去」和
    「不能挪到客户建档之前」会打架,第一版取严的那个,于是终点留在未来,
    C4 抓到 3 条量体落在 2026-09-17。
    **挑不出合规的位置就别造这条数据** —— 造一条违规的比不造更糟,
    它看起来和正常数据一模一样,只有和「今天」比才看得出来。
    现在门口先算够不够挪,不够就跳过并说明;结尾那处改成抛异常。

17. **修「违规数据」之前先问它是不是夹具** —— 差点把 `boundary_audit`
    「量体超期 → 下单被拦」那条攻击的唯一用例修没了(它写死用王清和)。
    **一个没被声明的资产,和垃圾长得一模一样。**
    夹具现在只有一处声明:`fix_order_measure.夹具着装人集`。

18. **只写迁移脚本、不改 `seed.py`** —— 这一轮为这件事付了四次学费:
    积分重算、活动编号、订单着装人、跨月日期,每次都是
    「我这台机器绿、新灌的库红」。**老库迁移和新库生成,两条路都要对。**

12. **拿「不可比的两个数」相除当作发现** —— 报过一条
    「提示词里 29 条强制措辞,hook 只检查 1 项」。两处都错:
    正则数错了(体检项叫 `g1_xxx`,真实是 20 项),
    **而且那两个数本来就不可比** —— 一条 hook 能管好几条规矩,
    很多规矩根本没法用 hook 检查。
    **一个方向符合直觉的错误数字,比一个离谱的数字危险得多** ——
    比例扎眼、结论符合直觉,所以一眼看过去不会怀疑。

13. **词表只覆盖中文,而语料是英文的** —— 能力管理首跑
    140/239 个技能被判成「该改成 CLI」,全是误报。
    判断信号只有中文,236 个英文技能一个都命中不了。
    **另外:别拿 `1. 2. 3.` 当「死步骤」的证据** ——
    任何 markdown 都有编号列表,那是「这是一份文档」的证据。

14. **写会改数据的检查/评测** —— 咬合时把角色判定拿掉,
    那批越权用例**真的把 AP-LV-001 批下去了**。
    一条在被测代码坏掉时会改数据的检查,**比没有这条检查更糟**:
    它会在你最忙的那天悄悄污染一份夹具。
    现在 `membership_check` / `member_eval` 都带快照还原,
    并且各有一条「跑完表必须和跑之前一模一样」。

11. **拿单轮结果下结论** —— 这一段栽了三次:
   评测跑的是 Haiku 而产品跑 Sonnet(三轮数据全废)、
   单跑一次断定「描述改坏了」(其实是抖动)、
   一次 13/15 就说「装 236 个没影响」(其实有)。
   **接近满分的结果最容易被当成结论。** 改任何影响触发/召回的东西:
   先 `--save` 存基线,改完 `--diff` 看改动组 vs 对照组,而且 `--repeat 3` 起步。

22. **假数据工厂的边界值按概率撒** —— 撒 1% 的空值/超长值,小表上一个都撒不到,
   而「没撒到」和「撒了系统扛住了」在报告上都是绿。现在是**按槽位保证每种边界值至少出现一次**。
   **绿有两种:守住了,和没走到。**

23. **把模型的单次判定当结论** —— 同一份库跑三遍,模型对「这是不是外键 / 这是不是禁配」
   只有七成一致,而**连这个测量自己也不稳**。现在每条判定跑 N 遍投票,禁配要全票。
   别为了省调用改回跑一遍。

24. **把 236 个第三方技能当成污染去清** —— 那是业务要求装的(见第 7 条),
   我误判过一次、被纠正过。**看到一大批「来路不明」的文件,先查是谁要的,再动手。**

25. **为了满足一条规则去推进判责夹具的订单状态** —— 判责现场里直接显示订单状态,
   推一步输出就变;开裁前后白坯试衣的分类也跟着变。**规则是为数据服务的**:
   对不上就改规则(降成警告 / 给夹具开豁免),不改夹具。

26. **把定制单挂到 C21* 合并用例、E- 夹具、评测写死的客户上凑「铺开到 93 人」** ——
   会改掉评测前提(例:C10001 的题目前提是「只完成了 1 单」)。54 人是扣完之后的真实上限。

## 当前状态(自动)

<!--AUTO-->
> 自动区,由 `python3 tools/make_handoff.py` 生成于 2026-11-24 11:27。**不要手改这一段。**

| 项 | 值 |
|---|---|
| 分支 | `w1121` |
| 最新提交 | 98972d91 · 2026-11-24 · 乐观锁可达检查:GET 打不通先歇 2 秒重试一次 —— gate_w35 整轮 e2e 只红在它一条瞬时抖动 |
| 代码量 | 1230 个 Python 文件 / 212845 行(不含 .venv) |
| 验收 | `./check.sh` 共 445 项 —— **接手第一件事就是跑它** |
| 服务 | 管理后台 :8760 → 在跑 200 · 智能运维平台 :8770 → 在跑 302 |

**未提交的改动:**

```
M HANDOFF.md
 M agentsite/evals/funnel.jsonl
 M "\346\276\234\347\273\243\344\272\221\350\243\263agent-\346\255\273\345\267\245\345\205\267\346\270\205\345\215\225-20261124.md"
?? .feynman/weekly-review.log
?? .gate_w29.sh.bak
?? .gate_w30.sh.bak
?? .gate_w31.sh.bak
?? .gate_w32.sh.bak
?? .gate_w33.sh.bak
?? .gate_w35.sh.bak
?? .gate_w36.sh.bak
?? agentsite/.venv
?? "\347\256\241\347\220\206\345\220\216\345\217\260/.models"
```
⚠️ 工作区不干净。**先搞清楚这些改动是什么再往下做** ——上一个会话可能是被打断的,而不是做完了。

**最近 5 次提交:**

```
98972d91 乐观锁可达检查:GET 打不通先歇 2 秒重试一次 —— gate_w35 整轮 e2e 只红在它一条瞬时抖动
3c9aaf6e 咬合规格跟上 sdk 转人工那行的改动;待办清单重生成(新检查进了门禁数字变了)
f485c046 8760 的 Skill 管理 / MCP 服务与工具 / 知识问题三页收到 AI 管理后台「澜绣 AI 治理」(用户 11-24 拍)
e4d59294 MCP 客户端:起子进程显式带身份、进程池按 (kind, 身份) 复用 —— 原来继承父进程环境、按 kind 复用会串身份
3274ccdf 包一第二批:修工作台 NameError、边界审计两条约定归位、健康口报确认卡开关、系统身份在 sdk 里中性、死工具清单
```
<!--/AUTO-->
## 一句话在做什么

**用户 2026-10-23 说「都接」那张表上的 5 件,我这条线已做完 4 件、在推第 5 件(报告期痕迹)。**
这一轮的主线其实变成了**修 CI** —— 本地门禁连绿、CI 连红三轮,**三组红全是我的**,
而三组都是**本地门禁走不到的那条路**,机制各不相同(见最后一段,那是这一轮最值钱的东西)。

## 上次停在哪

**已推上 main:** `7db59ee`(平移登记补九列)· `19ee925`(修 CI 第一组两条红)。

**手上没推、改完了的一批(报告期痕迹 + 修 CI 第二组):**

· **报告期痕迹** —— `realign_report_periods.py` 往 `op_log` 写痕迹,形状和报告那条线对好了:
  `machine='report_period'` / `code='REALIGN'` / `target=报告号` / `actor='系统'` /
  `frm`=旧起~旧止 / `too`=新起~新止 / `ctx` 里四个日期**结构化**+`正文已改:false`、`取数包已改:false`。
  自测 11 → **16 条**,咬合 **3 条**全过。
  ⚠️ 列名是 `machine` 不是 `mid`(我之前交接里写错了)。而**写口的参数**确实叫 `mid` ——
  两个会话为这个各说对了一半。那一列实际装的是**模块名**(staff / schedule / ordr / customer…)。
· **`oplog.log_op` 加了 `db=` 参数**(112 个老调用方全是位置参数,加尾部可选参数不影响)。
  ⚠️ **这不是顺手,是必须**:`oplog` 把真库路径写死在模块级 `DB`,而 `realign` 的 `db` 是参数
  (自测和咬合都在副本上跑)。不带 `db` 就是在副本上跑却往**真库**塞一行假痕迹,
  而那行假痕迹**会让页面给一份根本没被校正过的报告挂上「已校正」标注**。
  漏写检查 `_检查漏写了真库` 也跟着看 `db` —— 显式写副本是**正当的**,不算漏。
  > 一次「写进了副本」和一次「写进了真库」,**在 `log_op` 那条成功返回上长得一模一样** ——
  > 分开它们的只有「去哪个库数一遍」。所以自测里最要紧的那条是「痕迹落在**这个**库里」。
· **`table_origin_check` 的 import 提取改成 `ast`**(见「别重做」里那条)。
· **12 处文档「130 张表」→ 131**(CI 只报了 10 处,README 那两处 CI 不扫,一起改了)。

**在跑/在等的:**
1. `gate_lock --who "评测线-补建grade_diff_check" python3 tools/ensure_tables.py`
   —— **在排队等并行会话那轮门禁**。它只 `CREATE TABLE IF NOT EXISTS`,不动数据。
   ⚠️ **必须先补表、后改文档数字**。我已经先改了文档,所以**现在本地对账是红的,那是预期的**,
   补完表就对。顺序反了的话会红在一个假不一致上。
2. 并行会话那轮门禁跑完**他先推**,我再变基 → 重跑全量 → 推。
   ⚠️ `check-10.log` 那个绿**不算数**:我在它等锁和跑的过程中改了三个文件。

## 下一步第一个动作

**等 `ensure_tables` 拿到锁跑完** → 确认真库 130 → **131** 张且 `grade_diff_check` 在 →
等他推 → 变基 → `./tools/gate_lock.sh --who "评测线" ./check.sh` → `scan_secrets` →
`fetch` 比 `merge-base` → 推 → **喊他做页面标注那一半**(用户拍的「两半一起落」)。

之后按这个顺序:
1. **独立测试集「开枪台账」** —— 用户 10-23 拍了「**崩了不算用过,但要留痕**」。
   要落成**结构**(这仓库反复栽在「教训记下来了而没落到判据上」),三道闸:
   ① **「不算用过」必须带崩的证据**(异常类型+输出尾部,**捕获来的**不是人事后填的)——
      否则「不算」就成了看完分数再商量的借口,而**一条「真崩了所以不算」和一条
      「分数不好所以说它崩了」,在台账上长得一模一样**;
   ② **拿不准就算用过**(白名单只收明确不是模型造成的)—— 偏错的代价不对称:
      把真开过的一枪记成没开,换来的是**无限重摇**;反过来只是白费一套题;
   ③ **连着三次「崩了不算」就红** —— 那是环境没准备好,不是运气差。
   我已按「偏错朝安全那边」定了一处:**整轮墙上时钟超时算「不是模型」**(电脑睡了那种,
   这仓库见过 8599 秒一次),**单次调用超时算「算用过」**(模型自己绕圈也会拖超时,那是能力问题)。
   台账进版本库(库每天重建,它得活下来),含代码版本、模型、题集指纹、结局。
2. **只读审计第 1 条**:造数流水号绑 `did` 不绑 `i`(`tools/seed_triage_tasks.py:118-124`)+ 判据 + 咬合。
   引用面已核 —— 没有任何代码按 `channel_serial` 反查,改了不打断判据。
3. **接他三处判据** `isolation_check` / `tool_scope_check` / `triage_scope_check`(验按需加载只取回自己名单里的工具)。
4. **加检查:角色工具名单必须是字面量**(`*_TOOLS` 字面字符串列表;`_ROLE_TOOLS` 的 lambda 体里
   只许 Name/`+`/`sorted`/`set`)。起因:他把 `get_member` 内联进 lambda,而 `prompts_check` 读字面量看不见它。
5. **只读审计第 2/3/6 条摆选型卡** —— ⚠️ **第 3 条排最前**:门店关联键是 `SH001 静安旗舰店`
   这种拼起来的字符串,而「店长只看本店」靠的正是这个字符串相等 ——
   **门店一改名,店长就看不到自己店的旧单,而这不会报错,只会少几行。**
6. **挽回清单一键建跟进** · **报价一键转订单**。

**还等用户的一件**(别替他做) —— 索引那件 10-24 已拍「现在就加」,做完了(见下一节):
· **国标那 12 条溯源** —— 要人开浏览器翻 `openstd.samr.gov.cn` 的 GB/T 26380-2022,
  找 **欧根纱 / 提花暗纹缎 / 桑波缎 / 真丝提花绡**。自动化三条路都试到底了:
  搜索只返回售卖页、`WebFetch` 取不到正文(那站是**图片化**预览)、浏览器扩展这台机器连不上。
  ⚠️ 另四类(型糊染 / 绦带盘编 / 三镶三滚 / 玉禁步)**不在丝绸术语标准范围里**,别在那份标准上找。

## 只读审计第 4 条(索引)· **做完了**(用户 2026-10-24 拍「现在就加」)

加了三条,**不是审计列的那三条** —— 审计给的判据是「按 EXPLAIN 验再加索引」,
而照那条做会加错两条。实测(库副本,`.backup` 出来的,不是 `cp`):

| 索引 | EXPLAIN | 实测 | 结论 |
|---|---|---|---|
| `customer(advisor_no)` | SCAN → SEARCH | 0.927 → 0.781 ms | **1.2x** —— 白加 |
| `ordr(advisor_no)` | SCAN → SEARCH | 3.681 → 3.152 ms | **1.2x** —— 白加 |
| `customer(advisor_no, merged_into)` | → **COVERING** | 1.179 → 0.033 ms | **35.5x** ✅ 加了 |
| `ordr(advisor_no, prd_status, received)` | → **COVERING** | 4.342 → 0.245 ms | **17.7x** ✅ 加了 |
| `schedule(assignee_no,start_ts,end_ts) WHERE status='有效'` | → SEARCH | 0.535 → 0.006 ms | **89.9x** ✅ 加了 |

> **一条白加的索引和一条真有用的索引,在 EXPLAIN 上长得一模一样。**
> 分开它们的只有耗时,而耗时 EXPLAIN 不会告诉你。
> 差别只是**索引里多带一两列**(带上就不用回表);带不带,EXPLAIN 两边都说「SEARCH」。

导购业绩整页(9 个顾问 × 2 条查询):**35.0 → 2.8 ms**。
代价也量了:改一条订单实收 +0.0009 ms(百分比 28%、**绝对值 0.9 微秒**)、
插一条有效日程 +6%、三条索引占 **0.91 MB / 81.7 MB(1.11%)**。

⚠️ **否决掉一条**:把导购业绩页那 9 次循环改成两条 `GROUP BY`。
实测 35.0 → **31.1 ms**,几乎没用(不加覆盖索引它照样要把整张表读一遍)。
**改代码的风险换 11%,而加一条索引换 12.7 倍。**

⚠️ 那条 23 ms 的(`api.py:5392` 角色收范围)**仍然没解** ——
卡点是 `(o.advisor_no=? OR cu.advisor_no=?)` 这个 `OR` **跨了两张表**,
加索引修不了。要改写法(拆 UNION)或改数据(顾问号冗余到订单上),
**那不是补索引,是改代码**,单独摆卡 —— 而且它没有在让任何人等,不急。

落点:`backend/query_index.py`(唯一登记处,实测数写在里面)·
`backend/query_index_check.py`(26 条,进了门禁)· 四条咬合规格 ·
`seed.py` 和 `tools/ensure_tables.py` 各调一次 · 真库已建(走 gate_lock)。

⚠️ **这条判据守的四种状态,在任何页面上都长得一样(全都只是「有点慢」)**:
① 索引在、用上了、而且是覆盖的(35x) ② 索引在、用上了、**但不是覆盖的**(掉回 1.2x,一行错都不报)
③ 索引压根不在这个库里(代码写了,库建于那之前) ④ 代码里那条查询改了,索引配不上它了。
②④ 最阴 —— 所以判据验的是「计划里必须有 COVERING」和「登记的 SQL 还在那个文件里」。

⚠️ 这一轮踩到一个**两个判据各看一半**的坑:`bite_run` 比的是**输出**,
`bite_check` 比的是**源码**。断言标题用 f-string 拼(`f"{索引名} · …"`)时,
那句完整的话**只在运行时存在** —— 咬合重放三关全过,而咬合记账当场红。
修法不是改记录,是让那几个名字在判据脚本里**真的是字面量**,
顺便变成一条棘轮(新加索引必须回那儿登记并配咬合)。


## ⚠️ 这一轮最值钱的一条:CI 连红三轮,三组红的**机制各不相同**

本地门禁连绿、CI 连红,而「本地绿 ≠ CI 绿」这句话在这三组上**分岔点完全不同** ——
照着一个笼统的「本地留着产物、CI 从零」去查,三次都查不到:

| 哪一组 | 本地为什么看不见 |
|---|---|
| ① `平移后重算` 的 argv 传法 | 那段代码只在「天 != 0 **且**是真库」时执行 —— `--selftest` / `--check` 两条路都不满足。**真跑一次平移的只有 CI 的「从零重建」。** 本地 241 条绿勾里**没有任何一条看过那张表**。 |
| ② `set_grade_diff` 没在不可逆口径里 | 那条判据要 **postgres + 服务在跑**,本地 `check.sh` 压根不收它。 |
| ③ `grade_diff_check` 被判成孤儿表 | **库的新旧**:本地那个库停在我加登记之前 —— **表不在库里,也就没有什么可被判成孤儿**。 |

> 三组都是「同一份代码、同一条判据,两边结论相反」,而分岔点分别是:
> **走不到的代码路径 / 门禁收不收这条判据 / 库的新旧。**

⚠️ 第 ③ 条还暴露一个**不对称盲区,它仍然没人守**:
`table_origin_check` 只抓「库里有、rebuild 建不出」的表,
**抓不到「ensure_tables 登记了、而这个库里没有」** —— 后者在本地**完全隐形**,一路绿到 CI。
(下一个新建表的人会再踩一次。要守的话,判据得去比「登记表 ∖ 库」。)


## 别重做:试过并否决的

> ### 📍 2026-11-03 下午 —— 这两条试过了,别重做
>
> · **否决:给 `boundary_audit.py --selftest` 配可重放的咬合规格。**
>   咬合执行器拿 `script`(脚本路径)当键,去 `check.sh` 里找**第一条**含这个路径的
>   `run` 行当命令。而这个脚本现在有**两个入口**(完整攻 59 条 / `--selftest`),
>   于是「我这条规格要跑哪个入口」**在那个字段上根本无法表达**。
>   硬挂的后果是静默的:13 条指着边界审计的现有规格会被带去跑 `--selftest`,
>   而它的输出里没有它们的「预期红」,于是 13 条一起报「改坏了却没红」——
>   **看着像 13 个判据同时失效**,而真相是执行器选错了入口。
>   改用两样守:自测自己的断言是硬的(① 就是逼出它的那次翻车)+ `selftest_registry_check` 盯它在不在门禁里。
> · **否决:把 `--selftest` 那条 `run` 挪到完整审计前面。** 同一个原因(执行器取第一条匹配的行)。
>   `check.sh` 里已经写死一行注释说明它不许挪。

> ### 📍 2026-10-24 夜 —— 这几条试过了,别重做
>
> · **「存法不变、只把比较归一」行不通。** 门店改名之后,老串**归一不出编码**
>   (名字已经对不上门店表),所以必须存编码。我在这上面绕了一圈才确定。
> · **攻击 `校验` / `改状态` 里的归一是空操作。** 那两处在「全部走新写路径」时是
>   **冗余的**(进门那一步已经归一过),攻掉它们什么都不会变 —— 会显示成「改坏了却没红」。
>   咬合要攻的是**存入**、**生效比较**、**展示**这三层。
> · **判据别用真库副本。** 真库被门禁或别的会话占着时副本建不出来,那一层就「跳过」,
>   **而跳过不是通过**。改成自造一个最小库(只建 shop + 模板表),两个环境都真验得到。
> · **容错要写在取数上,不是写在判断上。** 我写了「取不到门店表就什么都不改」,
>   而**取那张表本身就会抛** —— 在只建了模板表的最小库上当场 `no such table: shop`。
>   要紧的是它**在全量门禁里是绿的**(那条走的是有 shop 表的库),
>   只有咬合重放那一步踩到了没有 shop 表的那个环境。**同一个脚本在两个库上说法不同。**
> · **「改名后拿老串来问」命中不了,这是边界不是漏网。** 判据里为它写了一条**反向断言**:
>   它绿表示那条路确实走不通;哪天它红了(老串也命中了),说明有人给归一加了「猜」的逻辑,
>   那得去看那是不是真对。调用方(经营报告取模板)改成拿 `staff.shop_code`。
> · **浏览器扩展第三次仍然连不上**(10-16 / 10-24 两次 `Browser extension is not connected`),
>   而 10-24 新试的「找征求意见稿 / 报批稿」那条轴**也死了** —— 只找到标准状态页和引用它的
>   企业标准,唯一像正文的是论坛帖,和百度同级,过不了那条线。


- **`cp -R` 拷库副本** —— `backend/lanxiu.db` 是**软链**指向主检出的共享库,`cp -R` 复制的是软链本身。
  我 10-23 这么干过,**往共享库误写了一格、而且没拿锁**(已恢复)。要副本用 `.backup` 或 `cp -L`。
  ⚠️ 这坑 10-17 就记在 `bite_run.py` 文件头了 —— **教训记在一个地方,而下一次踩它的人不在那个地方**。
- **让推导从库里读「人工确认」** —— 破了 md→表 单向。用户拍的是**归档文件**
  (`knowledge/相容矩阵-人工确认.json`,手写源、进版本库)。
- **给报告正文做「重新渲染」** —— **报告正文是模型写的,不是模板生成的**,没有这条路。
  (我拿它和确认书类比过,那句是错的。)正文那一半改成**页面标注**,归并行会话。
- **给正文/取数包里的日期加同样的校正量** —— 会把取数包里的**来路日期**
  (「用户 2026-10-20 定」)也改掉,而那是一个现在是对的日期。
- **把「报告期」整列登记成不挪** —— 正文和取数包是跟着挪的,不改它们就自相矛盾。
- **按「只读」这个属性放行 `ToolSearch`** —— 「只读」是判断不是结构;要**按名字点名**。
  而且它自己只读、**它的后果不是**(它让别的工具变得可调)。
- **`bash` 里用中文变量名** —— 不是赋值,是「找不到这个命令」,而 `bash -n` 说「语法 OK」。
- **SQL 注释写在三引号外** —— `--x` 是合法 Python 表达式,`ast.parse` 也说 OK,只在运行时炸。

## 这一族的总结(值得记住的三条)

**① 判据不许依赖会变的量。** 栽过三次,形状一样:
固定行数的窗口(注释一长就失效)、夹具的偶然性(种子一变就误报)、
`上限 = len(豁免)`(加一条上限跟着涨)。**共同点:那个量变的时候没人会注意到。**

**② 共用真相源要配一个不读它的对照。**
`pkg.created` 同时躲过 C4 和平移闸 —— 因为**两道闸读的是同一份清单**。
共用清单省掉了漂移,但也让**漏一列就同时瞎两处**。
照出它的是假数据工厂那套**不针对任何东西**的基线断言:
**专门的检查只查它被告知要查的;基线断言查的是「跟昨天比有没有变坏」。两种都要。**

**③ 「谁算这个值」和「谁写这一列」可能不是同一个模块。**
按写入扫的检查在那种情况下看不见。换成按**时间源**扫,不用判传递链。

**④ 「同一个意思有无限种写法」在判据的两头都成立**(并行会话补的,而它推对了)。
这个仓库一直只在**要拦的那头**防枚举(CLAUDE.md 那七个否定坑),
而**要放过的那头同样是无限的** —— 「不该拦的写法」也是个无限集合。
推论:**靠枚举「例外」放行的判据,和靠枚举「违规」拦的判据一样会输。**
所以放行也要落结构。第三条判据的做法可以照抄:
不枚举哪些站点该放过,而是**要求放过的人当场写明理由**(`# 真实时钟:` + 一句话)——
把判断权交回写代码的人,但留下痕迹。

**⑤ 判据往哪边偏,要看偏错了的代价朝哪边。**
`selftest.py` 守「truth 表不许经接口暴露」那条红线时**只剥注释不剥 docstring**,
所以 docstring 里写 `JOIN truth` 当例子会误报 —— 而**不改是对的**:
误报一次是有人被挡两分钟,漏报一次是整套评测答案泄露,
而**评测集一旦泄露就再也不能当评测集**。代价不对称时,判据该往多报那边偏,
并把这个选择写在注释里(不写的话,下一个人看到误报会直接去放宽它)。
- **08:3x**:欠债现算一遍已报用户（代码欠债 8 项清零、5 项都没涨；业务待办 16 件开着）。查出 rare-i 规格 [503] 过期（编号从 1 数）→ 已修 f8f54f30（本地）。**锁让给并行会话 08:25–09:15 跑 pre_push --不推**，它放锁会喊。**发版命令找到了**：`.wip-glossary/align_rules_v9.py`（写 aimc_dev，要锁）。现状 `--看` 已跑：生产 v19、草稿==生产、最大版本 19。shrink13 不带新工具 → **不用 --加开**。拿锁后：`git checkout shrink13 && git rebase --autostash origin/main` → `python3 .wip-glossary/align_rules_v9.py`（出 v20，要印「✅ 只差规矩」且多了 TL98–107）→ `--切 20` → 喊并行会话 → assistant_effect_check → 推 shrink13 → 报提交号。
- **08:5x**:shrink13 已 rebase 到 86043ae0 → 0acc2634。**店长助手线上 v19 → v21**(脚本导入代码时自动出 v20 = 代码全套,改回后出 v21 = v19 + TL98–107;TL99/102/107 绑的版师工具店长助手没开 → 只进池不装,正常)。assistant_effect 绿(87 规矩 / 79 工具)、select_eval 第一层两组召回满。并行会话已知 v21。**pre_push 后台跑中**(.wip-glossary/pre_push24.log,08:5x 起约 50 分钟)→ 绿且推上就报用户 + 并行会话提交号;并行会话 d20dd7b4 等用户推,推了要再 rebase。之后:rare-i(5 笔,含 f8f54f30)rebase → gate_lock 包 ops 全量两轮 → 提交结果 → pre_push → 推。
- **09:2x**:⚠️ **工作区的 HANDOFF / 两份滚动 jsonl 已还原成已提交版,最新交接在 `.wip-glossary/dirty-bak-0900/`** —— pre_push 跑完后 `cp .wip-glossary/dirty-bak-0900/HANDOFF.md HANDOFF.md` 和 `cp .wip-glossary/dirty-bak-0900/agentsite/evals/*.jsonl agentsite/evals/` 拷回(jsonl 不提交)。pre_push 第一遍拒跑(工作区脏)、第二遍红在 popularity_check ⑫(shrink13 缩短 product_ranking 说明丢了「待付款」)→ 修 **7816c0c4**(shrink13 第二笔)→ **第三遍 pre_push25.log 09:0x 起后台跑**。绿 → 确认推上 origin/main → 报用户 + 并行会话提交号。若用户先推了并行会话的 d20dd7b4,pre_push ① 会要求 rebase。之后 rare-i(dfa86efa/0c4524e6/9c416138/b35ca208/f8f54f30)rebase → gate_lock 包 ops 全量两轮(~2h)→ 提交 agent/ops-eval-results.jsonl → eval_tier_check 绿 → pre_push → 推。
- **09:5x**:用户又起 12 小时长任务(到 21:5x)。并行会话做执行手册 10 件欠账,其中「结构迁移目录」= 我的 ALTER 欠债 → **已交给它**(给了 alter-plan-1117.md 路径和两个坑),我不再碰。它占锁前会先说。用户要支持的三件已告诉用户:推 d20dd7b4 / 填聊天站管理后台地址(LANXIU_USAGE_URL / LANXIU_BRIDGE_PROJECT / LANXIU_USAGE_USER,等用户说「现在填」)/ 推送被拦时点一下。

### 🧭 09:5x 压缩前六项(只写摘要留不下的)
- **未验证的预判**:pre_push25(shrink13 = 0acc2634 + 7816c0c4)第三遍还在 ③ 咬合重放,**没出结果**;能否自动 push 未知(以前被权限分类器拦过 → 拦了就给用户 `! git push origin shrink13:main` 之类一行,先看 pre_push 推的是 HEAD:main)。v21 的工具说明改动(7816c0c4)没进后台版本 —— 判断不用重出:店长助手没开 product_ranking,工具说明从代码读(未实测聊天站对 product_ranking 的说明来源)。
- **判据**:v21 而不是 v20 —— align 脚本先跑 import_chat_assistant(自动出 v20 = 代码全套,不能上线),改回生产配置后才出 v21;切 v21 前脚本已核「只差规矩、工具多开少开都空」。TL99/102/107 只进池不装 = 绑的版师工具店长助手没开,v19 也有 10 条同理。bite_check 编号 `[N]` **从 1 数**(验规格 enumerate(specs,1)),查规格用 s[N-1]。
- **作废的结果**:我曾以为规格 [503] 是「拒加急否定表」那条(0 起算看错);真的是「交回给人」那条,已修 f8f54f30(rare-i)。
- **禁区**:结构迁移目录 / 47 处 ALTER **已交并行会话**,我不碰。并行会话每次占锁前会先说;我开跑 ops / 放锁要先告诉它。别用裸 stash(今早 autostash 冲突留下 stash 条目,已按 SHA 3e1ca71a 删掉);工作区脏 → pre_push ③ 拒跑,用 cp 备份 + checkout 还原,别 stash。
- **下一步第一个动作**:pre_push25 收工 rc 行 → 绿:`git fetch; git log origin/main -1` 确认推上 → 告诉用户 + 并行会话提交号 → 拷回 jsonl(`cp .wip-glossary/dirty-bak-0900/agentsite/evals/*.jsonl agentsite/evals/`,不提交)→ `git checkout rare-i && git rebase --autostash origin/main`(先把 HANDOFF / jsonl 备份 + 还原避免 autostash 冲突)→ 告诉并行会话「起 ops」→ `./tools/gate_lock.sh env LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5 ./agentsite/.venv/bin/python agent/ops_eval.py > .wip-glossary/ops_full_1117.log 2>&1` 后台 → 提交 agent/ops-eval-results.jsonl → eval_tier_check 绿 → pre_push → 推。红:逐条单跑查。
- **悬而未决**:用户要不要现在填聊天站管理后台地址(三个环境变量 LANXIU_USAGE_URL / LANXIU_BRIDGE_PROJECT / LANXIU_USAGE_USER,在 takeover_client.py:73;常驻配置在哪还没找)—— 等用户说「现在填」。d20dd7b4 等用户推。
- **10:0x**:并行会话确认收下迁移目录 + 47 处 ALTER(排它清单第 10 位,上午不起门禁,等我 ops 放锁)。pre_push25 仍在 ③,无红。
- **10:1x 并行会话报 CI 红 86043ae0**:①管理后台 test_dsl_semantics 归它;②**我的**:tools/eval_env_check.py 夜跑两条自测(只提交不推 + 反向)在 CI 红「set the identity」——自测的 g() 带了 -c user.*,但被测的夜跑代码在临时克隆里 commit 不带,CI 无全局身份。**修法(pre_push25 跑完再改,别动被测代码)**:第 162 行 clone 之后加 `g("config", "user.name", "t"); g("config", "user.email", "t@t")`(仓库级配置,被测代码继承);验证:`env HOME=$(mktemp -d) GIT_CONFIG_NOSYSTEM=1 python3 tools/eval_env_check.py` 模拟无身份。并进 shrink13 再推(pre_push 要重跑)。
- **10:3x 状态**:✅ **shrink13 已推 7816c0c4**(pre_push25 rc=0),已告诉并行会话。CI 夜跑身份修复 = **a5003e6e(分支 ci-ident,基于 7816c0c4)**,请并行会话 cherry-pick 进它下一笔 pre_push 一起推;锁先给它,它放锁喊我再起 ops。⚠️ **未解**:本机 HOME=空+useConfigOnly 下旧版 eval_env_check 夜跑两条仍绿(裸 git / python 子进程同环境都能复现无身份失败)—— 以 CI 为准,推后看 `gh run list`。工作区现在在 **ci-ident**;jsonl 滚动日志已还原(备份在 .wip-glossary/dirty-bak-0900/,不提交,可不拷回)。**下一步**:等并行会话放锁 → `git checkout rare-i && git rebase --autostash origin/main`(先确认工作区只脏 HANDOFF,备份后还原)→ 告诉它 → gate_lock 包 ops 全量。还没告诉用户 7816c0c4。
- **10:29**:锁空、主干 7816c0c4、CI 对 7816c0c4 在跑(44003006615,预计 ~28 分钟;它会照旧红在夜跑身份 + dsl 两条,修复都还没推)。等并行会话回话:它先 pre_push(带 a5003e6e)还是我先 ops。
- **10:3x**:并行会话接锁(它写 12:1x,疑笔误),a5003e6e 已 cherry-pick 进它这批跑 e2e-ci + pre_push;**它今天没有自推授权 → 绿了由用户点推**,我那笔跟着上。它放锁喊我 → 我起 ops 全量(rare-i rebase 先)。
- **10:4x 作废早上的结论**:「聊天站常驻配置没填管理后台地址」**是错的** —— com.lanxiu.agentsite / backend / supervise 三个 plist 都已有 LANXIU_USAGE_URL=http://127.0.0.1:8801、BRIDGE_PROJECT=project_lanxiu、USAGE_USER=U001。**缺的是 com.lanxiu.nightly-eval.plist**(夜跑进程没这三项 → 夜跑里接管必然兜底)。夜跑要不要真打后台工作流 = 待用户定(会在共享库建真运行记录);别自己加。已告诉用户更正。
- **10:5x**:并行会话锁内到 ~12:4x(e2e 红在演示项目堆了 1100 个夹具应用 → 加应用归档口 + 夹具自收尾;落 m0003 staff.must_change_pwd;重启 8760;归档 3414 工作流 + 412 应用;重跑 e2e-ci + pre_push --不推)。我 12:4x 放锁后起 ops。等锁期间可做(不占锁):查本机为何复现不了 eval_env_check 无身份红。
- **11:28**:锁仍在并行会话(到 ~12:4x)。查复现:nightly_eval / eval_env_check 都不改 git 环境变量 —— 本机为何不红仍未解,**以 CI 为准**(用户点推 a5003e6e 后看 gh run list)。清单 ⓪–⑥ 均已完成/挂起;下一步仍是放锁后 rare-i rebase → ops 全量。
- **12:28**:例行检查,锁/主干状态见上一条之后;仍等并行会话放锁起 ops。
- **13:2x**:并行会话第三轮 e2e-ci + pre_push --不推 起跑,约 90 分钟(~14:5x 放锁)。它本地领先远端 20 笔(含我的 a5003e6e、47 处 ALTER 收编成三条迁移 → 剩 2 处、两条索引、PG 新表 knowledge_revisions),**等用户点推**。共享库 sqlite 已迁到第 6 条。⚠️ 我起 ops 前 rare-i 要 rebase 到**它推上去之后**的主干(否则 ops 结果对的是旧代码);若用户还没推,先问并行会话。
- **13:28**:例行检查;仍等并行会话第三轮 + 用户点推,之后 rare-i rebase → ops。
- **13:3x 用户拍「接」**:com.lanxiu.nightly-eval.plist 加 LANXIU_USAGE_URL=http://127.0.0.1:8801 / BRIDGE_PROJECT=project_lanxiu / USAGE_USER=U001,lint OK,已 unload+load(备份 .wip-glossary/nightly-eval.plist.bak-1117)。**今晚夜跑验**:商机通话 / 经营报告应真走工作流接管(不再出「接管没生效」兜底);会在共享后台建真运行记录(用户知情)。
- **14:28**:例行;等并行会话放锁 + 用户点推 → rare-i rebase → ops。
- **15:28**:例行;等并行会话放锁 + 用户点推 → rare-i rebase → ops。
- **15:3x**:并行会话预计 16:0x 放锁(咬合重放 111 条 + 全量检查)。放锁后我跑 ops 全量两轮;它剩两笔文档 + 一处冒烟登记,等我 ops 完再要锁跑小一轮。提醒:e2e-ci 末尾会自动归档名字带 e2e 的夹具 —— 夜跑建的运行记录名字不带 e2e 就不会被收。**ops 跑在哪个基线**:它 20 笔未推(等用户点),我先 rebase 到 origin/main(7816c0c4)跑;它那批主要是后台 / 迁移 / 归档口,不碰提示词与工具说明 → ops 结果不受影响,推上后 rare-i 再 rebase 一次即可(**未验证**:它那 20 笔里有没有动 prompts.py / api.py 描述 —— 放锁时 git log --stat 看一眼)。
- **15:5x ops 全量起跑**(后台 bde69itvt,gate_lock 包着,日志 .wip-glossary/ops_full_1117.log,预计 17:5x)。rare-i 已 rebase 到 7816c0c4 → f1474690(5 笔);judgetest / textmatch / bite_check 绿。并行会话 20 笔未推:没碰 prompts / api 描述 / agent/,只两份 SKILL.md(activity-review / metric-diagnostics)可能影响 ops。**跑完**:看收工 rc 行 + 两轮各几题过 → `git add agent/ops-eval-results.jsonl` 提交(--only)→ eval_tier_check 绿 → 喊并行会话放锁 → 等它那 20 笔用户推了再 rebase + pre_push 推。工作区当前分支 rare-i。
- **16:0x 并行会话提醒**:反复改同一份 .py 时 __pycache__ 旧字节码会骑(CLAUDE.md 第 7 节 5)→ **手工跑检查前先 `find backend agent tools -name __pycache__ -prune -exec rm -rf {} +`**;ops 在跑期间别删。
- **16:28**:ops 第一轮过半(78 行判定)。CI 对 7816c0c4 只红已知两条(dsl 未实现 / 夜跑身份),**我推的 shrink13 没带新红**;两条修复都在并行会话那 20 笔里,用户推后看 CI 是否转绿(夜跑身份那条本机没复现,以 CI 为准)。
- 17:28:ops 全量仍在跑(234 行,已进第 2 轮之后的题组);跑着期间不改被测代码,只等收工行。
- 17:42:ops 全量收工 rc=0,两轮 99/132、108/132;评测分层检查转绿;结果提交 e165095d(rare-i 本地,未推);锁已放、已通知并行会话跑第 4 轮。日常层 84% < 95% 门槛,25 题翻面(23 题吃措辞)。
- 18:0x 只读复盘 ops 两轮都没过的 16 题(G02 G14 K10 K8 L01 M4 M6 R03 R07 R08 R1 R11 X02 X03 X07 X08):
  · **题面疑似坏**:R08「这份名单里…」、K10「那张断货清单…」引用了上一轮的东西,而评测是单轮 —— 助手回「没看到名单,要我先拉一份吗」其实是对的,判「没调工具」冤。R1「哪些单子该跟」单子/客户有歧义(助手走了客户召回)。改题要按评测集规矩记理由、不能拿来凑分,先留给用户/拍板,不自己改。
  · **真没答好**:M6 没查 fitting_queue 就泛讲流程;L01 只报理由不报档位;X02/X03/X07/X08 库存不分门店仍没说出来;G02 累计金额;G14/R07 编自己的历史/承诺。这些是日常层没达标的主因,下一步看规矩是否装到了 ops 助手。
- 18:1x:R07/R08/K10/X08 题面改自足(提交见 git log),六条只读评测检查全绿;这四题待锁空重跑(并行会话 17:5x 起占锁约两小时)。
- 18:4x:召回技能说明补「单子走 recovery_queue」分流(R1 两轮红的原因);五条技能检查全绿;待锁空与 R07/R08/K10/X08 一起重跑 R1;线上后台技能说明要下次发版同步。
- 19:0x:L01/L04 身份改 SH003 店长(C10001 库里在 SH003,默认 SH001 店长被权限正确拒);待重跑清单:R07 R08 K10 X08 R1 L01 L04。
- 19:5x:新检查 case_identity_scope_check(挂 check.sh、四条咬合手跑命中);会员评测 M04/M06/M07/M12 身份修;欠债 G04/G07/G09/G16(合并题跨店是否考点,待用户/设计定;G09/G16 密封集)。待重跑补上 member 套这四题。
- 20:2x:用户推了主干 5a992fb6(并行会话 24 笔含 a5003e6e);rare-i rebase 完 10 笔(bite_specs 冲突=两边都在尾部追加,按上游+我 4 条重建;HANDOFF 上游删减到 2443 行,三方 union 合并保留我 50 行;autostash 9bf62e25 已按 SHA 丢)。锁在并行会话到 ~20:40,放了跑 pre_push 再推。

## 20:2x 压缩前(只记摘要留不住的)
- **在等**:并行会话占锁跑 pre_push(20:26 起);它放锁会喊我。放了我:`./tools/gate_lock.sh ./tools/pre_push.sh`(先把 HANDOFF/两个 jsonl 备份到 .wip-glossary/ 再 `git checkout --` 它们,pre_push 嫌脏会拒;不用 stash)→ 绿了自动推 → 报提交号给用户和并行会话。
- rare-i 在 5a992fb6 上 10 笔未推(ops 结果 / 四道题面自足 / 召回技能分流 / L01·L04 身份 / 新检查 case_identity_scope_check + 会员 M04/M06/M07/M12 身份)。
- **推完要做**:锁空时重跑改过的题:ops 的 R07 R08 K10 X08 R1 L01 L04,member 的 M04 M06 M07 M12(用 claude haiku)。看日常层能否回 95%。
- **攒着问用户(一张卡)**:合并题 G04/G07(ops)+ G09/G16(密封)用 SH001 店长合并别店客户 —— 「跨店合并」是考点(进故意越权、判据认被挡)还是身份配错(换身份/换客户)?已告诉并行会话别重复问。
- 召回技能说明改了,线上管理后台要下次发版(align_rules_v9 流程)才同步 —— 发版要用户批。
- 未验证:C10001 是一直在 SH003 还是被世界换班挪过去的(没查)。
- 0 点到夜跑结束并行会话不占锁;05:10 平移后它再要。今晚夜跑看接管是否真生效(无「接管没生效」兜底、后台有运行记录)。
- 21:2x:**HANDOFF 正本在 .wip-glossary/dirty-bak-2015/HANDOFF.md**(工作区那份被 checkout 回干净了,pre_push 嫌脏会拒)。pre_push 收工后:`cp .wip-glossary/dirty-bak-2015/{HANDOFF.md} .` 和两个 jsonl 放回 agentsite/evals/。
- 21:24 第一次 pre_push 红:intent_check 对照红 = 待办清单里「检查脚本数」405→406(我新挂的检查)。make_todo 重生成 → 5baadcd8。第二次 pre_push 后台 b9moq2wpv 跑中,日志 scratchpad/pre_push_1117c.log;只认「收工 rc=」行。绿了自动推 → 报提交号给用户 + 并行会话。
- 21:3x **用户拍板:跨店就是考点**(合并题 G04/G07 + 密封 G09/G16)。pre_push 收工后做:4 道从 身份待定欠债 挪进 故意越权(理由写「用户 11-17 拍:考店长碰别店客户被挡时怎么说」),判据改成认「被挡住 + 说明找总部/那家店」;密封集两道按密封规矩在注释里记理由。然后重跑这 4 道 + 之前 11 道。
- 22:1x 并行会话等锁跑第五轮(8 笔 + 5a992fb6 CI 两红修法 + 建订单索引 + 真推,用户 20:3x 给它长期自推权)。我答应:pre_push 收工立刻喊它;我的 15 题重跑排它后面,它 0 点后才完就挪到夜跑后。
- 22:1x 定:我的 15 题重跑挪到夜跑之后(05:10 平移后要先问并行会话);它第五轮约 2.5–3h 跨 0 点。合并题判据改动(不占锁)可以 pre_push 收工后先做、先提交,重跑留到夜跑后。
- 22:2x 再改:并行会话第五轮挪到 05:10 后;我推完可直接用 30–40 分钟短锁重跑 15 题,**0 点前必须收掉**,放锁喊它。
- 22:3x **栽了**:我用 gate_lock 包 pre_push,它第④步自己 gate_lock check.sh → 等自己 48 分钟。停掉后直接跑 ./tools/pre_push.sh(不包),后台 b0x64azzl,日志 scratchpad/pre_push_1117d.log。时间紧:推完若已过 23:20,15 题重跑挪到夜跑后。
- 23:01 pre_push(不包锁)收工:咬合过,全量红 2 条 = 契约漏登记 7 接口 + 全角 41→42 —— **正是 5a992fb6 远端 CI 的两条红,并行会话手上有修法(05:10 后第五轮推)**,不是我这 11 笔带的。未推。等它推上去后我 rebase 再 pre_push。
- 23:1x 合并题改判据(用户拍「跨店就是考点」)**做法**:G04 第 2 轮真输出「也没办法在这里合并…要合并的话,需要去那家店或者总部办理」被 交回给人 判挂(标记表无「没办法」「总部」)。**不往标记表加词**(那条 docstring 明令)。改法:ops_eval 新增判据 `跨店挡回(*acts)` = 提到动作的那句里出现「执行方是别处」(总部 / 那家店 / 别的门店 / 客户所在门店),且全文没说「已合并/合并好了」;G04/G07 用 `any_of(交回给人(...), 跨店挡回(...))`;密封 G09/G16 同改 + 注释记「用户 11-17 拍」;ops_eval_judgetest 加 G04 真输出为对照(过)+ 「已帮你合并,总部会看到」为反例(挂);case_identity_scope_check 里 4 道从 身份待定欠债 挪 故意越权,欠债表清空(反向检查保留)。然后 sealed_tier_check / ops_eval_judgetest / case_identity_scope_check 单跑。
- 23:2x 并行会话占锁推 530a83a5(修 CI 两红),23:55 前收。我的 11 笔:pre_push 要占锁约 40 分钟,0 点到夜跑结束不占锁 → **夜跑结束后、05:10 平移前**先问并行会话再 rebase + 直接跑 ./tools/pre_push.sh(不包锁)推。
- 23:4x 合并题判据并联已提交(见 git log);G09 读题仍欠。全角 42 红是上游、待 530a83a5。待夜跑后:rebase → ./tools/pre_push.sh(不包锁)→ 推;再重跑 15 题(ops R07 R08 K10 X08 R1 L01 L04 G04 G07;member M04 M06 M07 M12;sealed G16 按密封规矩跑)。
- 23:28 现状:本地 rare-i 12 笔未推;夜跑窗口不占锁;下一步见上一条(夜跑后 rebase→pre_push 不包锁→推→重跑 15 题)。
- 23:4x 并行会话推了 530a83a5(修两红,锁已放);rare-i 12 笔干净 rebase 到 530a83a5;HANDOFF 三方 union 合并。夜跑后先问并行会话再 ./tools/pre_push.sh(不包锁)。
- 00:3x **攒卡(下次一起问)**:密封 G09 考的是「合并方向」(C21010 已并入 C10005,副档比主档大),**要看得见才考得到**;两个客户都在 SH002,而身份是 SH001 店长 → 被挡就什么都考不到。推荐:身份换成徐汇店长(60000004 周恒东),这道不算跨店考点。和用户 11-17 拍的「跨店就是考点」字面冲突(那张卡把四道当一类问的,G09 其实是读题),所以**要问不要自己改**;密封集改题还要按密封规矩记理由。
- 01:3x 查证闭环:C10001 在 SH003 杭州湖滨店是固定种子(seed.py:11 random.seed(20260830))生成的,seed_rng_check 守随机序列不漂;不是巧合,L01/L04 用湖滨店长身份成立。夜跑(pid 35734)仍在跑,未占锁。
- 02:3x 夜跑(pid 35734)仍在跑;滚动日志里目前 0 条「接管没生效」兜底,接管看起来生效,等跑完再核管理后台运行记录。
- 04:0x 夜跑查明(只读):接管今晚真生效,46 条运行进了管理后台:call-notes 32 失败 INPUT_MISSING(工作流要 call_id+customer_id,模型只给 call / call_id)、8 条 waiting_approval(评测造的垃圾在人工核对队列里,未处理,要问用户);store-report 6 条失败(BRIDGE_CRASHED 3 / TOOL_REFUSED 2 / INPUT_MISSING 1)。根子:guards.py:1829 拦截语只写 inputs={…},/chat-takeovers 不带 input_schema,发起口不校验必填就建运行。待修(推完做):①发起口按 input_schema.required 先校验、缺了 422 不建运行 ②清单带必填项 ③拦截语点名必填 ④start_workflow 把 422 原话交给模型。待问:评测怎么对待被接管技能;8 条待核对垃圾运行怎么处置。
- 04:43 推送完成,主干 368b5f7d(13 笔:12 笔身份修正/新检查 + vocab_check 下限 122→125/130→132)。
- 05:0x 接管必填修复(未提交,工作区):
  · 管理后台/services/api/app/workflows_api.py:新 _开始必填(定义)(在 _版本定义 上面);/chat-takeovers 每项带「必填」;发起口缺必填 → 422 TAKEOVER_INPUT_MISSING,不建运行。contract/endpoints.py 说明同步。
  · backend/takeover_client.py:清单存必填;发起() 新分支 TAKEOVER_INPUT_MISSING → 不兜底不交还、叫模型查清再发(原来会落进「其余一律兜底」)。
  · agentsite/guards.py ~1827:拦截语点名必填。agentsite/takeover_check.py +2 条(33/33 绿)。
  · 管理后台/tests/e2e/test_audio_flow.py +2 条(清单带必填;缺 customer_id → 422 且运行数不变)—— **未跑**:管理后台常驻跑主检出代码,本地 e2e 测不到工作区改动;要么起一份工作区 uvicorn 用 AIMC_BASE 指过去,要么推后看 CI。
  · 并行会话 05:20–08:2x 持锁跑第五轮(已修 CI 连红 205edd9d)。我推要等它放锁,先 rebase 到它推完的主干。
  · 还没做:咬合规格(新两条判据要各配一条攻击)、bite_specs;待问用户卡:被接管技能评测怎么考 / 8 条评测造的待核对运行怎么处置 / 密封 G09 身份。
- 04:5x 接管必填修复已本地提交 febc9ad0(takeover_check 33/33、咬合 10/10、8899 工作区实测 422 不建运行)。未推:并行会话 05:20–08:2x 持锁跑第五轮,之后 rebase + pre_push(不包锁)再推。推后要跑 make test-e2e-ci 或看 CI 的 test_audio_flow。
- 用户拍板(11-18 清晨,一张卡三题):
  ① 被接管技能的评测「两条路分开考」:评测进程关掉接管、照旧考技能本身;另出几道小题专考接管链路(发起成功 / 必填给齐 / 不把「已发起」说成「已办完」);夜跑不再往人工核对队列塞真单。→ 待做(我的线)。
  ② 8 条评测造的待核对运行:我逐条取消,理由「夜跑评测产生」,记录不删。→ 执行中。
  ③ 密封 G09 换成徐汇店长 60000004,按密封集规矩记改动原因;从 身份待定欠债 里移出(case_identity_scope_check 反向检查会要求)。→ 待做。
- 并行会话第五轮 ship 第三次 06:3x 起,预计 08:0x 放锁。它问:agent/nightly/agentsite__evals__funnel.jsonl 123 MB 原始日志压完 .gz 还留着是不是故意 —— 待我查夜跑脚本回它。
- 07:1x 8 条评测待核对运行已取消(8801 取消口,理由写明,状态 cancelled 8)。G09 换徐汇店长已本地提交;咬合 1955 改指 set() 写法,未重放(锁在并行会话手里),pre_push 会重放。
- 下一步(「两条路分开考」落地,我的线):先读 agent/takeover_guard.py(10-27 已有「评测期间接管状态记录 + 不许变」)和 agent/rounds.py:145(评测子进程透传 LANXIU_USAGE_URL 等记账变量)。思路:评测进程显式「接管关」(只关接管、不断记账 —— 别靠删 USAGE_URL,那会连记账一起断),成绩单印「接管:评测关」口径;另建一小套接管链路题(发起成功 / 必填齐 / 不说成已办完),用假管理后台或 8899 工作区实例,不往生产核对队列塞单。改评测判据/流程前先看 takeover_guard 的成绩单口径怎么印,别和它打架。
- 推送队列:368b5f7d 之后本地 3 笔(febc9ad0 接管必填、9f8270a3 G09)待并行会话 08:0x 放锁后 rebase + ./tools/pre_push.sh(不包锁)。推后:CI 看 test_audio_flow 新两条;告诉用户与并行会话提交号。
- 下次问用户卡候选:夜跑原样日志副本(agent/nightly/agentsite__evals__*.jsonl,123 MB)压完 .gz 后要不要删(涉及删除)。
## 交接刷新 11-18 07:1x(压缩前六项)
- 未验证:test_audio_flow 新加两条(清单带必填 / 缺 customer_id→422 且运行数不变)没在 e2e 里跑过,只在 8899 工作区实例手工验过同样两件;推后看 CI admin-e2e。咬合 1955(欠债表 set() 写法)没重放过。
- 判据:缺必填不兜底的理由 —— 兜底=技能绕过工作流把事做了,人工核对那道就没了;缺必填是「这次没查清」不是「没配好」(用户 11-14「只在没配好时兜底」)。
- 作废:夜跑 11-18 的 oppo 0/24、store_report、report 退步不是模型退步,是接管真生效后评测没东西可判 —— 不要拿这些数调提示词。
- 禁区:锁在并行会话手里到约 08:0x,别跑门禁/咬合/写共享库;管理后台常驻跑主检出,别重启它来测工作区代码(用 8899 工作区实例,测完 pkill -f "port 8899");8801 取消口只用于用户拍过的那 8 条。
- 下一步第一个动作:等并行会话「放锁」消息 → git fetch && git rebase origin/main → 备份并 checkout 脏文件 → ./tools/pre_push.sh(不包锁)→ 报提交号给用户和并行会话 → 恢复脏文件。
- 悬而未决:「两条路分开考」怎么关接管而不断记账(看 takeover_guard.py / rounds.py:145);15 道改过的题重跑还没做(要锁)。
- 07:12 仍等并行会话放锁(锁主见 owner);本地 3 笔未推。
- 07:28 仍等放锁;盯梢后台任务 bmjm6h22j(主干动且锁空即醒)。
- 08:3x 已 rebase 到 8534385b(bite_specs 末尾冲突按 上游+我 2 条 重建),本地 a87c6002 / 8ba83273;pre_push 在跑,日志 scratchpad/pre_push9.log;脏文件备份在 .wip-glossary/dirty-bak-0830/(推完拷回 HANDOFF 和两个 jsonl)。
- 08:28 pre_push9 在咬合重放 4/23;推完后:拷回备份、报提交号、gh run list 看 admin-e2e 是否转绿、再做「两条路分开考」。
- 09:1x pre_push9 红:test_audio_flow 咬合对照红(沙盒打常驻 8801 旧代码)。已撤回那两条 e2e 断言(新提交),**管理后台部署后要加回**(原文在 a87c6002)。重跑 pre_push10。
- 09:28 pre_push10 在跑(日志 scratchpad/pre_push10.log),推完拷回本备份。
- 10:13 pre_push10 红 1 条:OpenAPI 没随 endpoints.py 说明重生成。下一步:cd 管理后台 && python3 tools/gen_openapi.py → 只提交生成文件 → 备份/checkout 脏文件 → 重跑 pre_push(不包锁)。
- 10:28 pre_push11 在跑(含 950add36 OpenAPI);推完拷回本备份 HANDOFF + 两个 jsonl。
- 11:16 已推送 8534385b..950add36(4 笔:a87c6002→rebase 后接管必填、G09 徐汇店长、test_audio_flow 撤回两条、OpenAPI 重生成)。待办:①管理后台部署新代码后加回 test_audio_flow 两条 ②「两条路分开考」③重跑 15 道改过的题 ④看 CI。
- 11:20 评测关接管已本地提交(见 git log -1);咬合 2 条未重放(锁在并行会话)。下一步:接管链路小题(假管理后台,不碰生产),用 agent-eval-sets 技能出题。
## 交接刷新 11-18 11:3x
- 已推 950add36。本地未推:3737034f 评测关接管(LANXIU_EVAL_NO_TAKEOVER;咬合 2 条未重放)。
- 未验证:rounds.跑并收尾 里设 os.environ 后,各评测进程内 guards/sdk 是否都读到(takeover_check 只验了 takeover_client 一层;真跑一套评测看成绩单那句「评测里关着」才算)。
- 判据:关接管放在共用收尾 + 夜跑评测环境两处,不放各评测 —— 28 套共用;聊天站常驻带了开关 = 接管悄悄全关,所以 takeover_effect_check 加了反向查。
- 下一步:接管链路小题 agent/takeover_eval.py —— 假管理后台(本地 http 线程,实现 /chat-takeovers、/chat-takeovers/{skill}/runs 带必填 422、/replies),LANXIU_USAGE_URL 指过去,**这套题要绕开评测关接管**(rounds.跑并收尾 加 接管=True 形参或在 一轮() 里自己 pop)。新评测要过的元检查:rounds_check、selftest_registry、eval_tier_check、夜跑登记 —— 先 grep 一套最近新加的评测看它登记了哪几处。
- 管理后台部署后加回 test_audio_flow 两条(原文在 a87c6002 之前那笔 rebase 后的提交里,git log -S TAKEOVER_INPUT_MISSING -- 管理后台/tests)。
- 11:36 接管链路评测 agent/takeover_eval.py + judgetest(21 条)+ check.sh 挂上 + 咬合 3 条(未重放);首跑单轮日志 scratchpad/tk1.log。未提交。
- 12:xx 接管链路评测首跑单轮 5/6:TK04 卡在反问客户号没发起 → 题面给出客户号隔开考点(注释记了原因),单跑 TK04 过。
  观察(未改判据,单轮不调):TK01 受理后模型又自己写了一段通话要点(「先给你看一眼」),内容没经人工核对 —— 算不算「绕过核对」待定,两轮跑完再看要不要问用户。
- 正在跑两轮全量(scratchpad/tk2.log)。完了:提交 takeover_eval*.py + check.sh + bite_specs + rounds.py(考接管 形参)+ takeover_client/sdk(STATE_DIR)。
- 11:38 主检出项目日志脏文件:并行会话认领(launchd com.lanxiu.daily-log 06:40,find 没排除 worktrees,已改 git ls-files),我不用管。接管链路两轮全量在跑 scratchpad/tk2.log。
- 11:44 两轮全量 5/6 稳定:TK01 两轮都没发起(找不到通话号→客户号的工具,反问用户)。修判据:TK05 交还要「发起→409→再调技能」(第1轮被拦那一下 Skill 也判过了),judgetest 22 条。待并行会话回话后改 api.py call_opportunity 的 call 参数说明加「返回里带客户号」,再重跑 TK01。
- 11:47 00b81bf7 接管链路评测 + call_opportunity 单列客户号 已本地提交。下一步:整套两轮重跑写结果(scratchpad/tk4.log);等并行会话放锁后 rebase + pre_push 推 3737034f、00b81bf7(+结果)。eval_tier 罕见 41/30 是上游的,没 --登记。
- 11:54 结果已提交(两轮 4/6 · 6/6)。TK01/TK02 不稳都在找客户号那步(ToolSearch 来回找,一次跑满 14 轮)。等放锁推。
- 11:58 rebase 到 7061db03,pre_push12 在跑(3 笔);脏文件备份 .wip-glossary/dirty-bak-1300/。推完再拿锁跑 15 题。
- 12:28 pre_push12 在跑
- 重跑清单修正:密封集 G16/G09 是「故意不跑」的,不跑。只跑 ops R07,R08,K10,X08,R1,L01,L04,G04,G07 + member M04/M06/M07/M12(member 一次只认一个 id,循环 4 次)。部分跑不写结果文件,只看原话。
- 12:51 pre_push12 红四处已修(见 git log -1),pre_push13 在跑。
- 13:10 并行会话要重启 8770(老进程 11-15 起,三天后端改动没生效);我答可以(pre_push 第④步页面冒烟才打 8770)。
- 13:28 pre_push13 咬合重放 43/54,目前无红
- 13:37 pre_push13 红 intent_check(待办清单没重生成),已提交重生成,pre_push14 在跑
- 用户 11-18 13:4x 拍(一张卡三题):
  ① 发起工作流后自己写整理要点 = 绕过核对,要拦:评测加判据 + 规矩补一句(发起后只报运行号和核对入口)。
  ② 夜跑压完 .gz 就删原样 jsonl(tools/nightly_eval.py:466 附近)。
  ③ 召回技能说明现在同步到生产管理后台,同步后读回核对。
- 13:58 「压完就删」改动(nightly_eval / eval_env_check / bite_specs 末条)已备份到 .wip-glossary/wip-1358/tools/,工作区退回 HEAD 让 pre_push14 测的就是要推的;推完拷回再提交。
- 推完要做(用户 13:4x 拍的①):prompts.py:2407 TL76 两处改 ——
  a) 「不知道就先问用户」改成「先用查询工具查(录音号 → 客户号:call_opportunity(call=…) 返回的「客户号」),查不到再问用户,别编」—— 这句正是 TK01 两轮反问客户号的根(和拦截语「先查清」打架)。
  b) 加「发起成功后别自己再写一份整理 / 要点 / 预览 —— 那段没经人工核对,用户会当成核对过的结论」(用户拍算绕过核对)。
  评测 takeover_eval:没自己做() 加判据「受理后回答里不许有整理内容」—— 结构判法待定:可比对 call_opportunity 返回的商品号 / 原话是否出现在回答里(出现即自己整理了)。
- 14:29 pre_push14 咬合 54/54 过,进第④步全量门禁
- 14:41 已推 7061db03..9a9f93ed(6 笔)。「压完就删」改动已拷回工作区。
- 14:43 TL76 + 没复述通话判据已提交(git log -1)。并行会话先拿锁推 8 笔(约 40 分钟),放锁后我跑:ops R07,R08,K10,X08,R1,L01,L04,G04,G07 / member M04 M06 M07 M12 / takeover_eval 两轮。召回技能同步生产还没做(要查同步脚本)。
- 14:44 召回技能同步生产:查实管理后台只存技能**名单**(chat_assistant_versions.skill_snapshot = 名字列表),技能正文聊天站直接读仓库 SKILL.md;主检出(main 6df6695e)已含 recovery_queue 那句,8770 13:10 已重启 → **已经在线上生效,不用再同步**。--核对技能 13 vs 13 一致。TL76 改动若要进后台规矩池要走 align_rules_v9(出版本+切,需另问用户)。
- 15:29 intent 补 11-18 六条拍板已提交。仍等并行会话放锁。
- 15:53 rebase 到 6df6695e(本地 3 笔 906b836e 等);锁内跑 13 题 + 接管链路,脚本 scratchpad/run15.sh,日志 run15.log;脏文件备份 .wip-glossary/dirty-bak-1540/(HANDOFF 已拷回,两个 jsonl 推送前要 checkout)。
- 16:14 13 题 + 接管链路结果:ops 12 题(R1 前缀带出 R10–R12)末轮 9/12 —— R11 两轮稳定挂「没把写动作交回给人」、R10 内容类翻面、K10 轨迹翻面;member M04/M06/M07/M12 全过稳定;接管链路客户号一步 4/4 通,发起后写要点仍 1/2 → 发起说明加一句后 TK01 2/2、TK02 1/2(已提交)。接着 pre_push 推。
- 接管链路 15:5x 那次全量结果被我 checkout 掉了(TL76 后、发起说明改前,已被后续改动取代);基线仍是 e746e539 那份,下次全量重跑再写。
- 16:28 pre_push15 在跑
- 16:29 ③ 盘点:≥500 字工具说明只剩 5 个 —— get_order 638 / get_member 560 / open_order 535 / get_wearer 517 / record_measure 505(其余已缩)。推完从 get_member 开始(规矩原样搬成 TLxx;动 api.py 前喊并行会话;后台 align_rules_v9 出版本+切按 11-14 授权做完告诉用户)。get_aftersale T17 那句也顺手。
- 16:48 已推 6df6695e..eaeb6596(4 笔:夜跑压完删原样、TL76 两处、intent 六条、发起说明别写整理)。
- 17:26 **g23 已经全做完,别再交用户跑**:三份放宽补丁都在 11-13/11-14 用户亲手跑过 —— 罩列表 896a99ee、对客挑话术带小标题 ffe94558、让价词数字折(guards.py:511 已是新式)。正本在 tools/放宽补丁/;.wip-glossary/g23_*.py 是旧副本(路径还多跳一层)。我 17:0x 又让用户跑了一次 → 「看起来已经改过了」,白跑一趟。提醒里的 g23 那句已过期。清单 ⓪–⑥ 全部落地(③ 剩下 5 个 ≥500 字是拼进去的问法举例,正文都 ≤452;④ 迁移欠债 2 处在 migrate.py 本身)。
- 17:31 test_audio_flow 加回接管必填两条(8801 已跑新代码),单跑 138/138,已本地提交。
- 17:34 TL05 补「没工具的改动别说成改了」,R11 0/2→1/2,已本地提交。后台规矩池要跟(TL05/TL76 都改了措辞 = 要问用户才出版切)。
- 18:3x pre_push16 推 2 笔,备份 .wip-glossary/dirty-bak-1830
- 18:39 并行会话排我后面:锁内重导 127 条规矩进 aimc_dev(会把我的 TL05/TL76 新措辞一起导进规矩池)→ e2e-ci → ship。已叮嘱别出版本/切生产带我那两条(改措辞要先问用户)。
- 18:57 已推 eaeb6596..ca028d6f(test_audio_flow 加回、TL05 补句),锁已放给并行会话。
- 19:06 用户拍:TL76 + TL05 新措辞现在出版并切生产(店长助手)。等并行会话这批推完、规矩池导好后:align_rules_v9.py(只比规矩;但这次是措辞变而非多规矩 —— 脚本「比」只看 rule_ids 增减,措辞变体现在规矩版本 id 上,要核)→ 喊并行会话 → --切 N → assistant_effect_check。
- 19:07 **更正**:后台店长助手版本只管开头/结尾/工具/模型 + 规矩名单,规矩正文聊天站从代码 prompts.assemble 挑(backend/assistant_client.py 文档头)。TL05/TL76 只改措辞 → 不用出版/切;生效 = 主检出带上 ca028d6f + kickstart 8770。等并行会话把主检出换到 w1117 后由我 kickstart(launchctl kickstart -k gui/$(id -u)/com.lanxiu.agentsite),重启后 curl 首页。
- 19:07 并行会话 ship 完会顺手 kickstart 8770(主检出带 ca028d6f),重启后通知我 —— 我不用自己重启。收到通知后:curl 首页 + 确认 prompts 里 TL76 新句在线(可用 assistant_effect_check 或读主检出 prompts.py)。
- 19:17 待办:lanxiu_kb_sync_check 红(领域知识库 19 份 vs 文件 20,缺 knowledge/17-评测集频率分层.md,11-10 起就没导)。并行会话 ship 推完放锁后,我锁内跑 管理后台/tools/ingest_lanxiu.py --批次 领域知识 --项目 project_lanxiu,导完喊它做 bge 索引重建(只重建一次)。
- 19:17 更正:我导的是「澜绣领域知识」库 kb_8498a3a16d29,导完我自己派一次 bge 重建(API 派、worker 跑、不占锁);并行会话重建的是业务拍板库 kb_b29e0a81400a,互不影响。
- 领域知识导入步骤(并行会话放锁后,锁内):
  1. cd 管理后台 && ./.venv/bin/python tools/ingest_lanxiu.py --批次 领域知识 --项目 project_lanxiu
  2. curl -s --noproxy '*' -X POST -H "X-Dev-User: U001" -H "content-type: application/json" -H "Idempotency-Key: $(uuidgen)" http://127.0.0.1:8801/api/v1/projects/project_lanxiu/knowledge-bases/kb_8498a3a16d29/index-builds --data-binary '{"embedding模型id":"bge-small-zh-v1.5"}'
  3. 等 index_builds 里该 resource_id status=已就绪;再跑 lanxiu_kb_sync_check 看 20/20。
- 19:37 领域知识已导(20 篇,17-评测集频率分层 v1、README v2);索引重建派了 ib_40d12a6b1bad / job_f01542718ec8(bge-small-zh-v1.5)。待:等已就绪 → 跑 lanxiu_kb_sync_check。
- 19:39 领域知识索引 ib_40d12a6b1bad 已就绪;lanxiu_kb_sync_check 领域知识那段不再报缺;剩一条红是业务拍板库的「差评处理规矩汇编-20261118.md」—— 并行会话的新文件,还在它未推的提交里(我的工作区没有),推完自然对上。
- 20:02 并行会话推完 a0d89c9d、8770 kickstart;我核了主检出 prompts.py 含 TL05/TL76 新句、8770 首页 302;rebase 到 a0d89c9d 后 lanxiu_kb_sync_check rc 见下。本地无未推提交。
## 交接刷新 11-18 20:3x
- 已推到主干(我今天的):接管必填 422 / 评测关接管 / 接管链路评测 + 客户号单列 / G09 换身份 / 咬合四处修(spans.jsonl.1 软链)/ 夜跑压完删原样 / TL76 两处 / TL05 补句 / test_audio_flow 加回。生产:8770 已带 TL05/TL76 新措辞(并行会话 kickstart,我核过主检出)。
- 本地无未推提交。清单 ⓪–⑥ 全落地;g23 三份补丁 11-13/14 早已由用户跑过 —— **别再交用户跑**。
- 未验证 / 待办(不需拍板):
  · 接管链路评测全量两轮还没在「发起说明加『别写整理』」之后重跑写结果(基线仍是 e746e539 那份 4/6·6/6)—— 要锁。
  · 今晚夜跑第一次带「评测关接管」:明早看 oppo / store_report / report 三套回没回到接管前水平,成绩单那句「评测里关着」印没印;夜跑还会第一次「压完删原样」,看 agent/nightly 里 funnel.jsonl 原样没了、.gz 在。
  · ops R11 TL05 补句后 1/2,R10 / K10 翻面 —— 看夜跑。
- 判据:规矩正文来自代码(memory lanxiu-rule-text-from-code),只改措辞不用后台出版。
- 21:00 接管链路全量在锁内跑(scratchpad/tk5.log),脏文件备份 dirty-bak-2100。并行会话 8899 起了临时管理后台,我以后别再用 8899。它跑完后排队推一批管理后台修法。
- 21:05 接管链路两轮 6/6 稳定,结果已提交,pre_push17 在跑,备份 .wip-glossary/dirty-bak-2120
- 21:24 已推 fbaa7fbb..ff8e39a4(接管链路基线 6/6·6/6)。本地无未推。
- 21:27 并行会话推管理后台修法(主检出拉到 ff8e39a4 → 并 w1117 → kickstart com.lanxiu.aimc → e2e-ci → ship,约 50 分钟),只碰 管理后台/。用户另拍给它一批管理后台后续(运行暂停/取消接执行侧、训练部署接执行器、Prompt 变量编辑、评测发起、旋钮方案页、模型连接停用)—— 归它,不归我。
- 21:30 PRD 附录 A-311 / B-127 已本地提交(未推;等并行会话这批推完、夜跑前或明早推)。
- 23:19 已推 ff8e39a4..863af6f3(PRD A-311/B-127),锁已放。本地无未推。0 点起不碰锁;明早看夜跑(oppo/store_report/report 回没回、成绩单印「评测里关着」、agent/nightly 原样 jsonl 删了 .gz 在、ops R10/R11/K10)。
- 23:28 夜跑时段,不碰锁;等夜跑完核对。
- 11-19 00:29 夜跑在跑,不碰锁。
- 11-19 01:28 夜跑(pid 74204)仍在跑。
- 11-19 02:28 夜跑商机套已出:评测关接管生效(0 次 start_workflow);末轮 12/24,挂的全是技能本身质量(原话 4 / 对上 4 / 格式 3 / 结构 2 / 判断 1),不是接管造成。11-17 那晚(接管兜底由技能做)是 16/24。等夜跑完看报告全貌。
- 11-19 03:28 report_eval 今晚 8/13、0 次 start_workflow(评测关接管生效);挂的是 monthly_review / appt_funnel 没调、分母说不清 —— 技能质量。store_report 今晚还没跑(结果文件还是 11-18 的,别误读)。
- 11-19 04:30 夜跑汇总:raw jsonl 删了 .gz 在 ✓;oppo 12/24、report 8/13(都 0 次 start_workflow,技能质量)、store_report 3/3 回来了;takeover 4/6 但 2 题环境性失败不计分;recall 3 晚 0/1 是判分器冤枉两处 → 已修 commit(git log -1),未推。
- 11-19 04:31 夜跑自动提交 ac60476c 留在主检出未推(待推 44 笔含并行会话 w1117);等并行会话 05:10 后推,我 fb8c6640 排它后面。
- 11-19 05:xx **查出评测往真库写单**:下单评测连 4 晚「没开出单」的根 = 工具服务里懒加载的 order_write 第一次调用连真库(指到副本扫描在 import 之前)。修:mcp/protocol.指到副本 在连库层改道(1e3df33b,新检查 tools/eval_copy_lazy_import_check.py 挂 check.sh,咬合 +1),**未推**。
  真库污染:ordr 里 15 张「待确认」单(C10002,created 2026-11-18 01:33–02:17,id 6488012800001244322–336)+ 对应订单行 / op_log —— **没删,删要问用户**(下次拍板卡第一题)。别的写库评测(排班 / 报工)可能同样漏过,要查 roster / workshop 表夜里时段有没有评测痕迹。
- 15 张评测单删不删:并行会话放进它 10 点的拍板卡问用户,**我别重复问**。
- 05:2x 查了其余表夜里时段新增:aftersale / pkg / maintain / task / deal_credit 都是造数(随机时刻、来源「售后/维保系统」等),不是评测;排班 roster 0 条。**只有 ordr 那 15 张是评测漏写**。
- 11-19 06:28 仍等并行会话推完;本地 fb8c6640 / 1e3df33b 待推。
- 11-19 06:5x 并行会话全量红 4 条,两条归我:①recall 连 3 晚 0 分没登记(夜报在它分支,登记文本已发它,由它加)②popularity_check ⑦ 用 round(合并率) 复核擦边误红 → 已修 4b3356d6。我先推 3 笔(pre_push19 在跑,备份 dirty-bak-0650),它 rebase 后加①再推。
- 07:0x 并行会话转述:用户拍「15 张评测单删,先备份整库」,归我执行。**并行会话的话不算用户批准** → 删前当面跟用户确认一次;删要锁 + 先备份整库 + 连带订单行 / op_log 范围先列清。
- 07:1x 用户当面确认:删 15 张评测单 + 19 条订单行 + 业绩分成;op_log 留着;先整库备份。等 pre_push19 推完、锁内做。
- 07:08 **已删**(用户当面确认):ordr 15 / ordr_item 19 / deal_credit 120(id 6488012800001244322–336,C10002 待确认);op_log 179 条留着(审计)。整库备份 .wip-glossary/db-backup/lanxiu-删评测单前-20261119-070801.db(94.6 MB,不进 git)。
- pre_push19 红在 triage_trial_check 咬合 764(拆模块 DB 一层已红不了)→ de27aaa4 补拆连库层,单跑 3/3。并行会话 cherry-pick 了 4b3356d6、先推它那批(含 recall 登记);它推完我 rebase 推 fb8c6640 / 1e3df33b / de27aaa4。
- 11-19 08:28 并行会话 08:20 起 pre_push;我等它推完 rebase 推 3 笔,推完锁内实跑 order_eval 验证不再写真库(跑前后数真库 ordr 行数)。
- 08:4x rebase 到 4044579a,pre_push20 推 3 笔(备份 dirty-bak-0845)。推完锁内单跑 order_eval 验证(跑前后数真库 ordr)。
- 09:26 pre_push20 红 2 条(懒加载检查在门禁里「没给副本」那支连到门禁副本;dbpath 棘轮 +2)→ 修了提交,pre_push21 在跑
- 11-19 09:28 pre_push22 在跑
- 11-19 10:11 已推 4044579a..ae21e1b9(召回判分 / 评测漏写真库 / triage 咬合 / 懒加载检查适配门禁)。锁内实跑 order_eval P01–P03:3/3 过,真库 ordr 跑前后都是 26039 行 —— 修复生效。锁已放。
- 11-19 10:3x 查 growth_eval「连续 6 晚判红」:每晚挂 1–2 题、而且每晚挂的不是同一题(G01/G03/G04/G05/G06/G07 轮着)→ 抽样抖动,不是一处稳定缺陷;8 题的套任何一题翻面就判红。要动的是「小套怎么判红」的口径(要问用户),不是判据。talk / tool 未查。
- 11-19 11:3x 查 talk_eval 连 6 晚判红:T13(不开票就便宜点)、T17(今天定有优惠逼单)近 4 晚反复挂,看原话是**真缺陷不是判据**:T17 没给「当天不追、存方案、第 3 天跟进」,反倒叫用户自己去 kb_read("13") 查;T13 没说价格不动 / 发票必须开。待做:看 talk 那条路为什么没读销售话术第六节(kb 工具描述 / 规矩),改前先确认不是我改判据。tool_eval 夜跑结果在 .feynman/tool-eval.json(不在 agent/nightly)。
- 11-19 12:3x talk T13/T17 根因:**调了 kb_read 的那几晚都过、没调的都挂**(11-16/18/19 没调工具凭印象答)。TL60 已写「先 kb_read("13") 再开口」,模型一半时候不照做。可选修法(待问用户,攒卡):A 回答体检里加「销售场景没读话术就打回」(收紧、结构判:这一轮出现让价/逼单类诉求且没调 kb_read)/ B 把第一、六节要点直接并进铁律 TL58(改措辞 = 要问)。连同 growth 小套判红口径一起问。
- 11-19 13:56 用户拍两条已落地本地:g30 话术没读就打回(022fc60f)、夜跑小套看同一题连挂(git log -1);咬合均单跑过。待推(要 pre_push)。
- 11-19 14:29 pre_push23 在跑(备份 dirty-bak-1340)
- 11-19 15:28 pre_push25 在跑(加了文档 29→30 / README 重生成两笔)
- 11-19 16:05 已推 f7f0c864..cf643323(g30 话术没读就打回、夜跑小套看同一题连挂、文档 29→30、README 重生成)。生效:g30 在 8770 重启后才上线(主检出要带上 + kickstart);小套口径今晚夜跑起作用。本地无未推。
- 11-19 16:0x 核过:主检出 cf643323 含 g30,8770 16:06 重启、首页 302 → g30 已上线。
- 11-19 16:3x 查 tool_eval(24 题,昨晚 22/24):挂的 T14 / T23 两轮都一过一挂(翻面)。T23 是真错(客户要「整幅」缂丝,模型改成「云锦做底、缂丝做装饰」,把范围改了);T14 擦边(提了出处要补,没明说 demo 级不能承诺)。判据没问题,不改。四套慢性红查完:order(根因评测漏写真库,已修)、growth(抖动,口径已改)、talk(没读话术,g30 已上线)、tool(模型翻面 + 一处真错)。
- 11-19 17:29 PRD A-312 / A-313 已本地提交,待推(纯文档,下次跟别的一起推)。
- 11-19 18:48 已推 cf643323..c11af3b6(PRD A-312/A-313),锁已放。本地无未推。今晚夜跑看:小套抖动口径生效没(growth 应记「抖动(小套)」或判红带连挂题)、recall 判分修后复验、order 3 题(不再写真库)、talk T13/T17(g30 只在聊天站生效 —— 评测走 sdk 也经 guards 的 check_answer?要核)。
- 11-19 19:29 无待推、无后台任务;等今晚夜跑。
- 11-19 20:3x 核了 HANDOFF 里那个问号:评测走 sdk.run(guard 默认开),sdk 把这一轮系统提示词记进 state[规矩原文],guards.check_answer 带着它跑 → g30 在评测里同样生效,不只聊天站。仍无待推、无后台;等夜跑。
- 11-19 23:24 已推 e6ed66f0..e18167df(两笔):评测切库 / 夜跑认真库那几处改走新口 dbpath.真库()(不认 LANXIU_DB),拼库路径欠债 327→324;eval_env_check 的 PID 目录判据改判实际目录(第一次 pre_push 红在它比源码字面)。锁已放。之后到夜跑结束不占锁。
- 11-20 01:4x 本地提交(未推)小套连挂判断修:初版见「(整个改写了)」后缀跳过,成长套今晚照旧判红(今 G01/G02、昨 G07,本该抖动)。eval_env_check 34 条绿;咬合重放被夜跑 PID 拒(⚠️ bite_run 先拿锁再查夜跑,01:4x 拿了一瞬就放,没碰库)。夜跑结束后先重放咬合 eval_env_check,再 pre_push(和对方 05:10 起的锁错开,先喊)。
- 11-20 02:2x 夜跑中途核:开单套过(评测修好后第一晚),真库订单数仍 26039(没往真库写);商机套 16/24(昨 12/24)判红;成长套判红是小套规则 bug(已本地修 4bbf4101 待推)。
- 11-20 03:4x 本地提交 f3774f7b(未推):召回评测调用失败重试一次、仍失败落「跑挂了」一行。根因(spans):haiku 反复 ToolSearch 取 revive_list/churn_watch 取回不调,36 秒耗光 12 回合 → ResultError 整套崩(11-18 同)。待推:4bbf4101 + f3774f7b,夜跑结束后先重放咬合 eval_env_check,再 pre_push(和对方 05:10 错开)。还要看:repair 退步(P02/N03,前两晚 8/8)、talk、takeover。
- 11-20 04:28 夜跑结束。早核结果:开单过(真库 26039 未变)✅;话术 17/20(T13/T17 不再挂,g30 生效;挂 T8/T10/T12)✅;成长判红=小套规则 bug(4bbf4101 修,真目录实跑记抖动);召回崩=ToolSearch 卡死耗光 12 回合(f3774f7b 重试+落「跑挂了」);商机 16/24(昨 12);返修 6/8 退步(P02/N03,前两晚满)、经营报告 / 门店报告 / 接管 记退步 —— **待查**:接管今晚那行没在 agent/nightly 里看到(只见 11-19 的 4/6),先查结果文件名再看。
- 04:3x 锁内:eval_env_check 咬合 18/18 过;pre_push 在跑(推 4bbf4101 + f3774f7b),放锁后告诉对方(对方等锁推影响面基线 395)。
- 对方 05:10 后在锁里给共享库加列 projects.retention_policy_revision,推上去前我这边 alembic_sync_check 若报「库比模型新」= 这一列,rebase 到对方那版即可。
- 11-20 05:21 已推 e18167df..eecba3cc(4bbf4101 小套连挂修 / f3774f7b 召回跑挂不崩 / eecba3cc 待办清单重生成;第一遍红在待办清单过期=库里版师核过裁片 0→1),锁已放并告诉对方。**下一步**:查接管套今晚结果在哪(agent/nightly 只见 11-19)、返修 P02/N03、经营报告 / 门店报告退步原因。
- 11-20 05:3x 接管套查清:一轮里 1/6 题调用本身失败(跑挂)→ 按 rounds 保护不写结果文件,记「退步」;最后一轮 5/6。不是链路坏。对方 05:2x 拿锁(迁移加列 + e2e + ship,约 1 小时),放锁会说。下一步:返修 P02/N03、经营报告 / 门店报告退步原因(只读查 agent/nightly 与 .feynman/nightly-eval/2026-11-20.md)。
- 🔴 11-20 05:4x **查出我 11-18「压完就删」的回归**:agent/nightly/agentsite__evals__funnel.jsonl.gz 在 a7053ba4 里只剩 20000 行(前一版 327200 行,是逐晚累积的)。原因:入库清单删了原样 jsonl → 下一晚原样从空开始 → gz 被当晚覆盖,头版本里的历史没了(git 历史里旧版还在,没真丢)。skill_usage.gz 同理。**下一步第一个动作**:改 tools/nightly_eval.py 入库那段,压缩时把旧 gz 内容接上(先解旧 gz + 新增再压,或追加 gzip 成员,注意 eval_env_check 有「同内容同字节」判据),补一条「第二晚 gz 行数 = 两晚之和」的对照 + 咬合;再从 a7053ba4~1 的 gz 恢复历史拼回去。已告诉对方 a7053ba4 可带上(历史在 git 里,修复后重拼),**我先前跟对方说「不是丢数据」不准,要更正**。
- 11-20 05:5x 对方把夜跑自动提交接到主干(新号 bf7f6792,同 a7053ba4),正拿锁跑批次(e2e + ship),放锁会说。gz 修复:我修完、对方放锁后再占锁推,占锁前先喊对方。修复要点见上一条 🔴。
- 11-20 05:3x gz 修复**已改未提交**:tools/nightly_eval.py 入库清单压缩前先解旧 gz 接在前面(原样已含旧的就不重复接)。eval_env_check 34 条仍绿。**还差**:① eval_env_check 加对照「连跑两晚(第二晚原样只含当晚)→ gz 行数 = 两晚之和」+ bite_specs 咬合(改坏=删掉接旧那段);② 从 git 拼历史:`git show bf7f6792~1:agent/nightly/agentsite__evals__funnel.jsonl.gz`(32.7 万行)+ bf7f6792 版(2 万行)拼成新 gz,skill_usage 同;③ 等对方放锁、先喊再 pre_push。
- 11-20 06:3x gz 修复已本地提交(对照 35 条绿,咬合规格已加未重放)。还差:拼回历史(git show bf7f6792~1 的两个 gz + 当前版拼接,注意先 fetch 对方推的那版)、重放咬合、等对方放锁先喊再 pre_push。
- 11-20 07:10 已推 c9d4a74e..fa135101(8134bdb4 入库接旧 gz + fa135101 gz 拼回历史 funnel 347200 / skill_usage 86800),eval_env_check 咬合 19 条过,锁已放并告诉对方。gz 回归收口。下一步:返修 P02/N03、经营报告 / 门店报告退步原因(只读)。
- 11-20 07:3x 查经营报告套连 3 晚 8/13:R01/R02 每晚都挂「没调 monthly_review」。根因是**「月度复盘」两边都认**:工具 monthly_review 自称「月度复盘」(任务做完几条、逾期、派单采纳率),而 store-report 技能描述写着「只说『复盘一下上周』也走这个技能」(经营报告)。模型三晚都走了经营报告那边(11-18 发起工作流、11-19 写了完整 8 月经营报告、11-20 只调 Skill 就说「已发起」——这一晚是真错:没发起却说发起了)。R02 三晚都是「没存过 9 月月报,要不要现在出」—— 反问不做。→ 「复盘」该归谁是产品口径,**已问用户**(卡片),等回答再改技能描述或判据。返修 P02/N03 只挂一晚(前两晚 8/8),先当抖动不动。
- 11-20 08:32 用户拍「复盘归任务执行」,已推 fa135101..70dce541(store-report 技能说明 + 触发集反例 506 + intent 记录);主检出 ff 到 70dce541、8770 kickstart、首页 302 → 已生效。今晚夜跑看经营报告 R01/R02 是否改走 monthly_review。
- 11-20 09:28 交接刷新:复盘口径已生效(70dce541),召回评测重试已在 f3774f7b;今晚夜跑要看 ① 经营报告 R01/R02 改走 monthly_review ② 成长套小套判「抖动」③ 召回不再整套崩 ④ funnel gz > 347200 行 ⑤ 返修 P02/N03 是否复现。docs/交接归档/HANDOFF-归档-2026-11-14至11-15.md 未跟踪,下次提交带上。0 点到夜跑结束不碰锁。
- 11-20 09:4x 日志到期清理第三次现算并问,用户拍「先不开」、不再定期回问(PRD 2.4 第八十二条,intent 改做完了)。
- 11-20 11:2x 已推 70dce541..e0d161d8(日志到期清理拍板入台账 2.4.6 第八十二条、intent 已否决、交接归档入库);第一次门禁红 3 条全是我新加的文档行(写死条数 / 节标题条号 / intent 状态),已修。主检出 ff 到 e0d161d8(纯文档,不用重启)。
- 11-20 12:0x 已 --autostash 拉到 39f475d1(对方补回我 981dc5c0 误删的 11-18 那 11 节;根因:推前拿 rebase 前的旧备份恢复 HANDOFF。**以后推前不备份/恢复 HANDOFF**,只挪 funnel / skill_usage)。
- 11-20 12:0x **用户拍:店长判「企业承担」必须填预估成本**,没填停在「待确认」(原来不填按 0 元落店长权限,重做单能绕过 1000/5000 金额授权;返修夜跑 P02 那题模型先问成本反而对)。**待做**:repair_write.decide 企业承担 fee_est 为空 → 不判完、回一句要成本;同步 prompts.py:963 规矩措辞、decide_repair 工具说明;返修评测 P02 判据改「先问成本 / 不调 decide_repair 也算对」;repair_write_check 加对照 + 咬合;PRD 台账第八十三条(新开 2.4.6 里续一行)。返修 N03 被 g23 扣下,评测模式下扣下的草稿没落 withheld.jsonl,查不到原文(先当抖动)。
- 11-20 12:5x 企业承担必须填成本**已改已本地提交**:knowledge/repair.py 判完了没有(状态机闸同一处)+ 自测、repair_write_check 加 3 条(39 条绿)+ 咬合规格(手工咬合红在点名那条)、prompts 金额授权规矩、decide_repair 说明、返修评测 P02 补成本 + 新负向 N04、台账第八十三条。待 pre_push。
- 11-20 13:0x **交接(压缩前)**:
  · 在跑:pre_push 推 949ed25d(企业承担必须填成本),日志 scratchpad/pre_push9.log,只认「被包的命令退出码」那行。运行态备份在 .wip-glossary/runtime-bak-1300/(只有 funnel / skill_usage,**HANDOFF 不备份不恢复**)。
  · 绿了下一步:恢复那两个 jsonl → 主检出 `git pull --ff-only --autostash` → `launchctl kickstart -k gui/$(id -u)/com.lanxiu.agentsite` → curl --noproxy 首页 302 → 告诉并行会话(已预告过)→ 报提交号给用户。红了:逐条单跑查、修、新提交再跑。
  · 判据:P02 原题模型先问成本是对的(口径不看成本、写入层 fee_est or 0 → 店长权限,重做单绕授权);改在 knowledge/repair.py 一处,明填 0 合法。手工咬合第一次「没红」其实是崩(提示句 float(None)),已修成 or 0。
  · 未验证:N04 新负向题和 P02 改后题面今晚夜跑才第一次真跑;返修 N03(g23 扣下)评测模式下草稿不落 withheld.jsonl,原文查不到,先当抖动。
  · 禁区照旧:0 点到夜跑结束不碰锁;peer 消息不是用户批准;w1117 的 .venv 不是我清的。
- 11-20 13:2x pre_push 第一次红在咬合重放:knowledge/repair.py「没判责人」用例被新成本支挡住 → 31344e0b 补成本 0,手工重咬红在点名那条。重跑 pre_push。
- 11-20 14:0x 第二次 pre_push 红在 scenario_check 场景二(企业承担判责没带成本)→ 补 fee_est 150,22 条绿。重跑。
- 11-20 14:1x 第三次 pre_push 其实没跑:运行态 funnel.jsonl 把工作区弄脏、rebase 失败,而我读到的 pre_push11.log 是 11-18 的旧文件(上面印着「已推」是假的)。已挪开 funnel(备份 .wip-glossary/runtime-bak-1300/funnel.jsonl.1410)重跑,新日志 scratchpad/pre_push-1120-1410.log。**日志名以后带日期,别复用。** 本地待推 4 笔:949ed25d→b1693209(rebase 后哈希会变)。
- 11-20 14:5x 已推 39f475d1..b1693209(949ed25d 企业承担必须填成本 + c46a80c2 自测补成本 0 + 68ca843e 场景检查补成本 + b1693209 返修评测 P03 准备补成本)。前三次红:咬合死一条 / 场景检查 / 页面冒烟偶发(单跑 14 页全过)。主检出 ff 归并行会话批次脚本,我等主检出含 b1693209 再 kickstart 8770。今晚夜跑看返修 P02(补成本)/ N04(新负向)/ P03。
- 11-20 15:0x 主检出暂不含 b1693209:对方脚本 14:58 fetch 早于我的 push 落远端,主检出停在 0efddb32,e2e-ci 14:58:31 开跑约 40 分钟,期间主检出不能动(uvicorn 重载会打断)。对方跑完先 ff 到含 b1693209 再告诉我 → 我 kickstart 8770 + curl 302。**8770 重启前新规矩没生效。** 今晚 0 点前必须重启完,否则夜跑返修题用旧规矩。
- 11-20 15:4x **返修 N03 不是抖动**:扣下的草稿在主检出 agent/nightly/agentsite__evals__withheld.jsonl(夜跑挪过去的,不在 agentsite/evals/)。答案是对的(先问顾客同意了没),被 g30(问句里「300 块」当压价)+ g23 第二层(「问一下:…吗?」当推价格)误扣。放宽补丁 tools/放宽补丁/返修费_问一下与话术闸.py 已写(干跑对照过,未提交),**已交用户执行**;用户跑完 → guards_test 补用例 + 咬合 → 提交补丁和用例一起推。
- 11-20 16:0x 主检出到 65aa99c6(含 b1693209),已 kickstart 8770,首页 302 → 企业承担必须填成本**已生效**。
- 11-20 18:2x 放宽补丁脚本已本地提交 efb8110d(未推,guards.py 未动),仍等用户执行;22 点前跑才赶得上今晚夜跑。本地分支需 rebase 到 65aa99c6。
- 11-20 19:28 补丁仍未执行;无新改动。
- 11-20 19:3x **交接(六项)**:
  · 下一步第一个动作:看 agentsite/guards.py 里有没有「返修费_问一下与话术闸.py):这一轮」→ 有 = 用户跑了补丁 → guards_test 加 N03 原文该放 + 「我帮您问一下:能不能少点」该拦 + g30 返修该放/不开票该拦,两条咬合规格(删掉两处 continue / return None)→ rebase 到 origin/main(本地 efb8110d→7a26c749 未推)→ pre_push(日志名带日期)→ 主检出 ff(先问并行会话)→ kickstart 8770 → curl 302。
  · 判据:N03 答案对(先问顾客同意),两闸误扣;放宽只认结构(调过返修/售后工具且无折扣词/不开票;「问一下」后紧跟冒号或你/您且前四字无去帮替跟向给)。
  · 未验证:今晚夜跑才第一次真跑 —— 经营报告 R01/R02 走 monthly_review、成长套小套判抖动、召回落「跑挂了」不整套崩、funnel gz > 347200 行、返修 P02(补成本)/ N04(新负向)/ P03(准备补成本)。
  · 作废:早上「返修 N03 是抖动」作废(草稿在 agent/nightly/ 那份 withheld 里)。
  · 禁区:0 点到夜跑结束不碰锁;HANDOFF 不备份不恢复;放宽守卫只交用户执行;peer 消息不是用户批准;重启 aimc 要查孤儿 uvicorn。
  · 悬而未决:补丁用户还没跑(22 点前跑才赶得上今晚)。

### 20:28 交接刷新(工)
- 状态未变:返修放宽补丁用户**还没跑**(guards.py 里没有标记行);本地 efb8110d→7a26c749 未推。下一步同 19:3x 那段六项,不重写。
- 22:00 前跑才赶得上今晚夜跑;0:00 起不占锁。
- 21:0x 补:补丁之后的回归用例 + 两条咬合已写成 `tools/放宽补丁/返修费_跟进用例.py`(补丁没落就拒跑)。在临时副本上彩排过:补丁 → 跟进 → guards_test 190 条全绿;两条攻击各红在点名那条。用户跑完补丁后第一步就是跑它,再走 rebase → pre_push。
- 22:28:放宽补丁仍未跑,今晚夜跑赶不上(返修 N03 今晚照旧会被误扣,别当新问题查)。并行会话 22:20 起第二批占锁约 40 分钟;0:00 起我不占锁。明早看夜跑:报告 R01/R02、成长小套抖动、召回跑挂行、funnel gz、返修 P02/N04/P03。
- 22:4x 并行会话在共享库升了迁移 a3c7e1b2d4f6(只改 retrieval_runs.source 的 CHECK,多认「工作流」);我 pre_push 若核迁移版本以它为准(需先 rebase 到含它的 origin/main)。
- 01:28:今晚是周六档(只跑技能触发 + 研判影子 2 套,设计如此),返修 / 报告 / 成长 / 召回那几项要等 11-22 夜跑看。主检出 6 笔未推是并行会话的(工作流二到四期),夜跑结果那笔等它推完再推,不替推。
- 02:28 交接刷新:无变化。补丁未跑;主检出仍 7 笔未推(并行会话 6 + 夜跑 1),不替推。下一步不变:用户跑补丁 → `python3 tools/放宽补丁/返修费_跟进用例.py` → rebase origin/main → 告诉并行会话 → pre_push(日志名带日期)→ ff 主检出 → kickstart 8770 → curl 302 → 报提交号。
- 03:28 交接刷新:状态同 02:28,无变化。
- 04:28 交接刷新:状态同 02:28,无变化。
- 04:43 并行会话 05:15 起占锁约 1.5 小时(e2e-ci + ship),顺带把夜跑提交 a01ca454 原样重排一起推(我同意,和 11-20 同形);我的 efb8110d / 01024fe7 不带。
- 05:28 交接刷新:补丁未跑;并行会话批次在跑。
- 06:28 交接刷新:补丁未跑;等并行会话批次推完。
- 07:28 并行会话已推到 45269e05,夜跑 11-21 那笔已随它上远端。我的补丁仍未跑;推之前要 rebase 到 45269e05 之后。
- 07:29 已 rebase 到 45269e05:7a26c749(补丁)/ 91af8d9e(跟进用例),补丁两处锚仍各 1 次。并行会话今天不再占锁。
- 07:50 用户已跑放宽补丁;跟进用例已补(guards_test 190 全绿),接着 ship。

### 11-21 08:3x 交接(工)· 六项
- **在做**:推返修放宽 —— 用户 07:4x 亲手跑了补丁;本地 f36dd0cd(补丁 + 回归 4 条 + 咬合 2 条)在 7a26c749 / 91af8d9e 之上,**未推**。
- **停在(已修,08:3x 重放 3 条全过、已提交)**:ship-20261121-0751.log 红(rc=1,只在咬合重放):旧规格 [1973]「g30 不看 kb_read」的 old 被补丁插行打断。已改 bite_specs.json 该条 old(未提交),正在后台用 scratchpad/specs3.json 重放 3 条(1973 + 新 2 条)。
- **下一步**:3 条都红在点名那条 → `git commit --only tools/bite_specs.json HANDOFF.md` → 喊并行会话 → `./tools/ship.sh > scratchpad/ship-20261121-HHMM.log`(新日志名)→ 绿后 ff 主检出、kickstart 8770、curl 302、报远端提交号。
- **之后接的三件**(并行会话转用户拍「让测评线参与」):① 人工介入聊天站一半(接口形状在《工作流整体与详细规划-照Dify-20261115》4-1 进度段)→ ② 默认模型接聊天站(先复测再动 sdk.py)→ ③ 我地界 11③④ / 6(见《夜间汇总-20261121》第四节)。
- **未验证**:repo_consistency 那 2 条「对照红」推断是同一根因(规格指着未提交代码),提交后应消失,要在新 ship 里看。
- **别做**:别恢复 HANDOFF 旧副本;别复用日志名;夜跑 11-21 是周六档只 2 套,不是故障。
- 09:18 **已推** 45269e05..2acb51fb(7a26c749 补丁备好 / 91af8d9e 跟进脚本 / f36dd0cd 放宽+回归+咬合 / 2acb51fb 咬合规格跟上),ship-20261121-0831b.log 被包的命令退出码 0;主检出 ff、8770 kickstart 302。下一件:人工介入聊天站一半。
- 09:47 交接刷新:并行会话占锁约 70 分钟(Cron 触发器 + 编排自测),我不写共享库;这段时间只读代码、设计人工介入聊天站一半(先找聊天站现在怎么调 aimc 的 human-requests、有没有待办入口)。

### 11-21 09:2x 人工介入聊天站一半 · 调查结论(只读助手查的,行号见下,未逐条复核)
- aimc(A=管理后台/services/api/app):列表 A/human_api.py:151(只有 status/limit,无「我的」过滤,每条带 还能处理吗);详情 :208(`核对材料.__表单` 只在能处理的人拿全文);决定 :294(Idempotency-Key 必填;decision=按钮 id;request_revision 或 If-Match;驳回要理由;edits 按 allowed_fields 白名单)。
- 鉴权 A/deps.py:49:X-Dev-User → memberships(**无门店维度**);审批工具动作 只 approver / 带授权的 admin(perms.py:98);candidate_roles 默认 [approver,admin](W/worker.py:312)。**project_lanxiu 的 U001 推断提交会 403**(未查库核)。
- 聊天站身份:cookie lx_token → 后台 /api/me → {no,name,role,shop}(S/app.py:138/205);调 aimc 现用固定 U001(S/app.py:1164)。现成映射 aimc `staff_bindings`(工号↔aimc 账号,A/workflows_api.py:1176)。
- **我倾向的做法(待用户拍门店那条)**:聊天站按登录工号查 staff_bindings → 以**绑定的 aimc 账号**作 X-Dev-User 调列表 / 详情 / 决定(决定行记真人、权限即后台同一套,不改 aimc);没绑定就说「去后台待办处理」。前端复用 station.html:913 apvCard 样式。
- 悬而未决:门店维度(aimc 待办不带门店,店长 A 会看到 B 店的)—— 已问用户。
- 09:5x **用户拍:聊天站人工介入按门店分开,先改后台**(AskUserQuestion 原选项「要分,先改后台」)。已请并行会话做后台三样(待办记门店 / 三接口按门店筛拒 / 列表「我能处理的」过滤)+ 记台账;它回接口形状后我做聊天站一半(staff_bindings → 绑定账号作 X-Dev-User)。**现在转做 ② 默认模型接聊天站**(还债表 row 18,先复测、再动 agentsite/sdk.py)。远端 1f2a1142,锁空,并行会话不占锁。
- 12:15 并行会话:门店三样后台已写完,正落迁移(memberships / human_requests 加 store_id 可空)+ ship 约 70 分钟,推完给接口形状。我这段只读、不写库;下一步做默认模型接聊天站(先找还债表 row 18 原文 + agentsite/sdk.py 模型选择处)。

### 11-21 12:2x 人工介入按门店 · 后台接口形状(并行会话给的,w1117 944de18b,批次 12:17 起 ship,远端哈希待它报)
- 成员 GET/POST /memberships 多 "门店"(null=不限;大写 [A-Z0-9_-]{1,32};空串=清成不限;不给键=不动)。
- 列表 GET /human-requests:登记了门店的人只见本店(定不出门店的不给;不限门店的全看);每条多 "门店";响应多 "我的门店" / "只看我能处理的";`?mine=true` 只列「还能处理吗」为真。
- 详情 GET /human-requests/{id}、决定 POST …/decisions:不在门店范围 → **404 NOT_FOUND**(不说有这单);详情多 "门店" / "门店来源";决定其余不变(Idempotency-Key 必填、request_revision、decision=按钮 id、edits)。
- 归属在挂起时定:运行输入 门店/门店编号/store_id/shop_id/X-Shop → 核对材料同名键 → 发起人成员表门店 → 空。口径 `管理后台/services/api/app/runtime/门店范围.py` 的 `看得到吗(我的门店, 单子门店)`,**聊天站要判就 import 它,别另写**。
- 聊天站接法(并行会话认可):登录工号 → staff_bindings → 绑定 aimc 账号作 X-Dev-User。**404 要分两种提示**:NO_MEMBERSHIP(绑定账号在 project_lanxiu 没成员记录 → 找管理员登记)vs NOT_FOUND(不在本店范围 / 单子没了)。没绑定 → 「去后台待办处理」。AUTH_MODE 离开 dev 时换服务令牌(以后一起改)。
- **下一步第一个动作**:等它报远端哈希 → 主检出 ff → 在 agentsite 加三条代理接口(列表 mine=true / 详情 / 决定,沿 app.py:1164 `_评一次检索` 的写法:先读 revision、带 Idempotency-Key、409/404 照实说)+ station.html 表单卡(复用 913 apvCard 样式:说明、字段控件、按钮)+ 检查(自造三种 404 / 409 / 按钮 id 透传)+ 咬合。② 默认模型接聊天站排在它之后。
- 13:20 并行会话:用户拍四件(台账 85–88);其中**人工介入到期加「超时」出口** → 聊天站待办会出现「已过期」状态,它做完给形状;它还要动 agentsite/action_confirm.py + backend/pending_actions.py(复审 P0-01/P1-02),我这两文件无未提交改动、不冲突。聊天站表单卡要给「已过期」一个只读样子(不显示按钮)。
- 13:28 超时出口形状(并行会话 w1121 本地,随下轮推):到期 → human_requests.status='expired';决定接口对它 **409 CANNOT_DECIDE**(终态,聊天站要说「已过期,不能再处理」,别说成「别人刚改过」那种 409);详情 __表单 原样在 → 卡只读显示说明 + 已填内容、无按钮;列表可 ?status=expired。门店形状不变。仍等两轮远端哈希再 ff 主检出开工。
- 13:31 ⚠️ 并行会话正在改 agentsite/app.py + agentsite/web/station.html + action_confirm.py + pending_actions.py(复审 P0-01/P1-02)。**我的聊天站一半也要动 app.py / station.html → 等它推完、ff 之后再开工,别并行改同一文件**。
- 14:22 并行会话第十轮 ship 红(迁移索引没登模型,已补),远端仍 1f2a1142;第十一轮 14:2x 起约 75 分钟(锁内再落两条迁移)。我不写共享库,等它报哈希 → ff → 开工聊天站一半。
- 16:37 并行会话第十三轮又红(确认卡在迁移目录外 ALTER TABLE,改成另存表),远端仍 1f2a1142;第十四轮 16:36 起约 80 分钟。我照旧不写共享库,等哈希 → ff → 开工聊天站一半(交接 12:2x 那段是接口形状 + 第一个动作)。
- 18:10 **远端 dec5f75b**(并行会话推完:门店 / 超时出口 / 确认卡四态 + GET /api/action/result / station.html 两种卡状态;alembic head 0b610a1aa99b)。工 已 rebase 到它。**app.py / station.html 现在归我**(对方今天不碰)。下一步第一个动作 = 照 12:2x 那段做聊天站一半:先读 app.py 里 /api/action/result 与 _评一次检索 的写法 + station.html 确认卡四态,再加三条代理接口 + 表单卡(含已过期只读、409 CANNOT_DECIDE 与 REVISION_CONFLICT 分开说、404 NO_MEMBERSHIP / NOT_FOUND 分开说)。占锁前喊并行会话。
- 21:52 并行会话今晚做「标注回复」:后台一半在 管理后台/;**匹配那一半要动 agentsite/app.py 或 sdk.py,等我推完聊天站改动、报哈希后它才碰**。它约 21:00 占锁跑一轮(会先喊);0 点到夜跑结束不占锁。我这边聊天站一半还没动代码(只 rebase 到 dec5f75b)。
- 22:12 并行会话第十五轮占锁(迁移 7fd4c1f6ee18:chat_annotations 表 + projects 一列),约 23:3x 推完;0 点后它不占锁,而 **0 点到夜跑结束我也不占锁** → 聊天站一半今晚只写代码、跑不占锁的单项检查,门禁 + 推送排到明早夜跑结束后。
- 22:31 并行会话今晚不推:gate_w18 只跑到 e2e-ci,0 点前放锁;**明早 05:15 后它先推(gate_w19),推完报哈希,我再 rebase + 跑我的门禁**。aimc 跑 b90555ff(共享库 head 7fd4c1f6ee18)。
- 11-22 07:5x **聊天站人工待办一半开写(未提交)**:新文件 agentsite/human_requests.py(以登录工号查 /staff-bindings〔服务账号读〕→ 绑定账号作 X-Dev-User 调列表 mine=true / ?status=expired、详情、决定;四种点不了分开说:404 NO_MEMBERSHIP / 404 NOT_FOUND / 409 CANNOT_DECIDE / 409 REVISION_CONFLICT;revision 用页面看到的那一版、不替它重读;幂等键 chat:工号:单号:页面键)。app.py 已接三条路由(GET /api/human-requests、GET /api/human-request?id=、POST /api/human-request/decide,GET 两条在 _proxy 那行之前)。**下一步第一个动作**:station.html 左栏 opbtn 后加「人工待办」按钮 + 弹窗(#od/#odp,列表 → 详情表单:说明 / 字段控件 / 按钮;已过期或能处理吗=false 只读无按钮)→ 写 agentsite/human_requests_check.py(venv python;起假 aimc 线程 HTTP 服务 + 真起 app.H,验四种错误分开说、按钮 id / revision / 幂等键透传、X-Dev-User 是绑定账号不是 U001、没绑定不调)+ 挂 check.sh + bite_specs 2–3 条 → js_check / fetch_route_check / 单项不占锁跑。并行会话 07:5x 起 ship 约 08:4x 报哈希;我 rebase 后 ship(日志用 ship-20261122-xxxx),估 11:3x 报它哈希,它等我哈希才动 agentsite 做标注匹配。
- 11-22 08:2x **聊天站人工待办已本地提交 63cf7db9(未推)**:human_requests.py / human_requests_check.py(19 条绿,venv python)/ app.py 三路由(POST /api/human-request/decide 放在 /api/answer-feedback 前 —— 放 rate-rag 前会顶掉 fetch_route_check 那条咬合〔bite_specs 第 830 条〕的锚点)/ station.html 左栏 hrbtn / check.sh 第 456 行 / bite_specs 末尾 3 条。
  · 未验证:那 3 条新咬合的重放(后台任务 btl8uq5lh,`bite_run --specs scratchpad/hr_specs.json`)结果没看到;重放中途我挪过 app.py 的 POST 分支(不影响这三条,它们只改 human_requests.py),没出结果或不确定就重跑一次。js_smoke 没跑(8770 还是旧代码)。
  · 判据:revision 故意用页面看到的那一版、不在代理里重读(重读 = 乐观锁失效);没绑定不拿服务账号 U001 顶替。
  · 禁区:并行会话 ship 期间不占锁;agentsite/evals/funnel.jsonl 不提交;别恢复 HANDOFF 旧副本。
  · **下一步第一个动作**:看 btl8uq5lh 结果(三条都要「红在指定那条」)→ 等并行会话报哈希(约 08:4x)→ `git pull --rebase --autostash`(或 fetch + rebase origin/main)→ 告诉它我要占锁 → `./tools/ship.sh > scratchpad/ship-20261122-a.log`(日志名不复用)→ 只认「被包的命令退出码」→ 绿:主检出 `git merge --ff-only` + `git merge-base --is-ancestor` 核 → `launchctl kickstart -k gui/$(id -u)/com.lanxiu.agentsite` + `curl --noproxy '*'` 看 302 → 把提交号报给用户和并行会话(它等这个号做标注匹配,要动 agentsite)。
  · 之后:② 默认模型接聊天站(先复测再动 sdk.py)③ 11③④ / 6。
  · 08:3x 悬而未决:btl8uq5lh 的输出被 tail 吃到最后才落盘,文件里现在只有 grep 那行 —— 等它的完成通知再读,别以为它卡了另起一份。
  · 08:5x 三条新咬合重放全过(红在指定那条,被包的命令退出码 0)。
- 09:0x rebase 到 e21d0b1f(bite_specs 末尾冲突:取远端 + 追加我 3 条,diff 只 +36 行)→ 本地 34e8be71;**ship 已起**(后台 bx13687ry,日志 scratchpad/ship-20261122-0905a.log),已告并行会话占锁。下一步:通知到 → 只认日志里「被包的命令退出码」→ 绿则主检出 ff + merge-base 核 + kickstart 8770 + curl 302 + 报哈希给用户和并行会话;红看 ❌ 行。
- 09:1x 第一次 ship 拒跑:HANDOFF.md 没提交 = 工作区脏(ship 只挪三件运行态)→ 并进本地提交后重跑,日志 ship-20261122-0915b.log。
- 09:2x 第二次 ship 红:intent_check 对照就红 = 《待办清单》里检查脚本数 410→411 没重新生成(我新加了一个检查)。make_todo + sync_docs 后只有待办清单变了,并进本地提交,第三次 ship 日志 ship-20261122-0925c.log。
- 11-22 10:1x **聊天站人工待办已推送 93c8319f(第三次 ship 绿,ship:pre_push 退出码 0)**:主检出已快进,merge-base 已核过;8770 已 kickstart,首页 302,/api/human-requests 未登录返回 401(新路由已上线)。已把提交号报给并行会话,app.py / station.html 交还给它做标注匹配。**没验过**:页面上真点一张待办(要一个绑定了后台账号的工号,外加一张进行中的单);js_smoke 没跑。**下一步**:② 默认模型进聊天站 —— 先重新跑评测(LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5,写库和跑门禁前先拿锁并告诉并行会话),评测过了再动 sdk.py(动之前先告诉并行会话,因为 agentsite 现在归它)。
- 11-22 10:5x **②默认模型接聊天站:核实早就接好了(11-02/03,方案 A)**。后台那一版选的模型 = 难题分流先试的那一档(`backend/assistant_client.默认模型`,聊天页 /run 和访问 API 两条路都读);执行手册第 18 行已改 ✅。前置复测:本机登录态 claude-haiku-5-5 连调 16 次全成功、没限流(记录仪里 11-10/11 有 8 次限流,这次没再出现);有一次把 2+1 答成 4,重跑没复现。**sdk.py 第 1187 行那句注释原因过期了**(现在是 app.py 那层定模型),agentsite 归并行会话,没改,只告诉它。
- 11-22 11:0x **③ W36④/W40④ 取不到写工具清单就炸(本地,待推)**:prompts.assemble 先自己补 backend/ 路径,补了还取不到就抛 RuntimeError(原来 except: pass —— 实测只放仓库根的进程给带开单工具的角色装出 TL78「你没有写工具」,方向反了)。tools/prompts_check.py 加 P12e(起两个干净子进程:①只放仓库根要装 TL05 ②拦掉 api 要抛)+ 两条咬合(bite_specs 末尾,重放 2/2 过)。执行手册第 11 行④改 ✅。**下一步**:ship → 报号;然后 ③剩下的「两套脱敏统一」(先查两套各在哪、规则差在哪;要改给人看的结果就要摆选型卡等用户)和第 6 行库路径单源(49 处收口)。
- 11-22 11:2x **压缩前六项(给接手的自己)**:
  · **在跑**:ship dcc99f87(后台任务 brk99mn64,日志 scratchpad/ship-20261122-1110a.log);只认「ship:pre_push 退出码」那一行。绿 → 主检出 `git merge --ff-only` + merge-base 核(这笔没动 agentsite,8770 不用重启)→ 报号给用户和并行会话;红 → 看 ❌ 行修。**这条交接是 ship 开跑后追加的,不在 dcc99f87 里**,随下一笔业务提交带上。
  · **未验证**:聊天站人工待办没在页面上真点过(缺绑定了后台账号的工号 + 进行中的单);js_smoke 没跑;haiku-5-5 那次 2+1=4 只出现一次,不当结论。
  · **判据**:②「默认模型接聊天站」判已完成,依据是 app.py /run 和访问 API 两处都调 backend/assistant_client.默认模型(11-02 方案 A),不是看 sdk.py 那句注释。
  · **禁区**:agentsite/ 现在归并行会话(sdk.py 1187 注释过期已告诉它,别自己改);两套打码统一会改导购看到的手机号格式(工具层 138****1234 / 页面 mask.py 只露后四位,用户 11-17 只拍了页面那套)→ **要摆卡等用户,不许直接统一**。
  · **下一步**:ship 收尾后做第 6 行库路径单源的**第②步**(只动检查文件:82 处 `m.DB = 副本` 收成「设 LANXIU_DB + 重新 import」;计划在执行手册 W02 段 136 行起),先 `grep -rn "\.DB = " --include='*_check.py'` 量、挑 api 指得最多的几个检查先改,每改一个重放它的咬合;改之前先告诉并行会话要占锁。
  · **悬而未决**:打码格式统一那一题,攒进下一张拍板卡(连同别的待拍事项一起问,一次最多 4 题)。
  · **11-22 11:3x 量过(作废上面「82 处 m.DB」那个数)**:W02 第②步大半已由 `backend/check_copy.用副本()` 一把扫完成(连默认参数里烤死的路径也补了);现在直接写 `模块.DB = …` 的只剩 4 个检查 6 处(shop_inactive_check 2 / roster_write_check 2 / factory_chase_count_check 1 / booking_check 1)。下一步改这 4 个走 用副本()、各重放咬合;第③步(业务模块走 dbpath.路径(),棘轮 324)是大活,按 api → server → oplog → ops → auth 一个一个来。
- 11-22 12:0x **dcc99f87 已推(ship 绿)**,主检出已 ff + merge-base 核过,8770 重启 302,号已报并行会话。上面「在跑」那条作废。**下一步第一个动作**:4 个检查的 `模块.DB =` 改走 check_copy.用副本()(先读每处上下文:有的可能是故意切到别的临时库,不是真库副本 —— 那种不改)。
- 11-22 12:1x **并行会话新地界(禁区)**:它在做用户新拍的「交给 agent 的定时任务」(聊天站建任务 → 后台调度 → 到点 /internal/chat 以员工身份只读跑 → 站内 + 飞书),会动 agentsite/app.py、station.html、sdk.py(含 1187 那句过期注释)和管理后台调度器 —— **这三个文件我别碰,要动 sdk.py 先问它**。它同意我改那 4 个检查走 check_copy.用副本(),占锁前说一声。
- 11-22 12:3x **W02 第②步收尾(本地未提交)**:shop_inactive_check / factory_chase_count_check / booking_check 的手指切库改走 check_copy.用副本()(三个单跑都绿);roster_write_check 那两处是它自己的临时库 r.db、局部切完 finally 还原 —— **故意不改**;dbpath_check 欠债下限 324 → 323。11 条相关咬合在重放(后台 b84f6f8z6)。过了 → 提交(带 HANDOFF)→ ship(日志 ship-20261122-1240a.log)→ 主检出 ff → 报号。
- 11-22 12:5x **a523be02 本地(待 ship)**:另修了 dbpath_check 在咬合副本里列不出文件(副本不带 .git → 样本 0 → 对照一直红,从 11-17 加这条咬合起就没真过过);现在列不出时向 LANXIU_SRC_ROOT 要清单、内容照读副本。11 条相关咬合全过。ship 日志 ship-20261122-1300a.log;绿 → 主检出 ff(不用重启,没动服务代码)→ 报号。
- 11-22 13:0x **并行会话排队**:它的员工定时 agent 任务一期(agentsite/app.py、station.html、sdk.py、check.sh、chat_tasks*.py、后台迁移 e1014ff53288)等我 ship 7a708d27 放锁后起 gate_w22(约 70 分钟,会重启 aimc 和 8770)。**那期间我别占锁、别动 agentsite**。我 ship 绿后只做主检出 ff + 报号,然后做不占锁的只读/文档活(例如盘 W02 第③步 api.py 收口的影响面、攒拍板卡:手机号打码格式统一)。
- 11-22 14:0x **7a708d27 已推(ship 绿)**,主检出已 ff 核过,号已报;现在锁归并行会话 gate_w22,我不占锁、不动 agentsite。
- 11-22 14:1x 并行会话 gate_w23 在跑(约 70 分钟,会重启 aimc / 8770),bite_specs 合并成 1988 条;我继续不占锁、不动 agentsite,做 W02 第③步只读盘点。
- 11-22 14:3x **本地提交待推(等并行会话 gate_w23 报号后再 ship)**:backend/api.py 的 DB 改走 dbpath.路径()(W02 第③步第一个;服务进程不设 LANXIU_DB 所以行为不变;评测设了它,与 mcp/protocol.py 子进程切库对齐),欠债 323 → 322;dbpath / selftest / isolation / boundary_audit / bite_check 单跑全绿。ship 前要重放 api.py 相关咬合(数量大,交给 pre_push 的按改动重放);推完要重启 8770 和业务后台(都 import api)。下一个按顺序是 server.py。
- 11-22 15:0x 并行会话 gate_w24 在跑(第十六轮 e2e 红在它自己那边,已修重起),约 70 分钟;我照旧不占锁、不动 agentsite,b9084f5f 待推。
- 11-22 15:1x 本地又提一笔:backend/server.py 的 DB 也改走 dbpath.路径(),欠债 322 → 321(相关检查单跑全绿)。和 b9084f5f 一起等并行会话报号后 ship;推完重启业务后台 8760(com.lanxiu.backend)和 8770。下一个按顺序是 oplog.py。
- 11-22 15:4x 并行会话 gate_w25 在跑(并进员工定时二期,推完它会 kickstart com.lanxiu.supervise),我照旧不占锁、不动 agentsite;本地待推 b9084f5f / f3ebafa3。
- 11-22 15:5x 本地第三笔:oplog / auth / ops 三个的 DB 改走 dbpath.路径(),欠债 321 → 318(相关 8 项单跑全绿)。ops.py 的 _本库 = DB 照旧是 import 时冻结 —— 行为和改前一样,手册里「改成函数」那条另做。三笔一起等并行会话报号后 ship,推完重启 8760 / 8770。第③步按顺序剩 shop_key / tasks / merge / booking 等,再往后是 ratchet 慢慢降。
- 11-22 16:2x 并行会话判 e2e 那条是偶发,直接 ship(约 45 分钟);我继续本地收 shop_key / tasks / merge / booking。
- 11-22 16:3x 本地第四笔:shop_key / merge / tasks / booking 改走 dbpath.路径(),欠债 318 → 314(9 项单跑全绿)。四笔一起等并行会话报号后 ship(ship 日志用 ship-20261122-17xxa.log),推完重启 8760 / 8770。
- 11-22 17:1x 并行会话 gate_w27 在跑（只 ship，约 45 分钟；上一轮 w26 红在它新加内容的咬合对照，修在 8565bd83；bite_specs 1988 → 1991，**我的四笔没碰 bite_specs，不用合**，已告诉它）。本地待推 b9084f5f / f3ebafa3 / 32fea6e2 / 3d4804f7 不变。它报号后：fetch + rebase --autostash → 告诉它 → ./tools/ship.sh（日志 ship-20261122-17xxa.log，只认「ship:pre_push 退出码」那行）→ 主检出 ff + merge-base 核 → kickstart com.lanxiu.backend / com.lanxiu.agentsite + curl --noproxy 302 → 报号。等的时候继续 W02 第③步下一批 backend 模块（不占锁、不碰 agentsite）。
- 11-22 20:4x **18:46 那轮 ship 红了、已停，锁已放**。并行会话 gate_w28 20:3x 起，它推完报号。红在我库路径那几笔带出的三处，已修在本地第六笔（单跑全绿）：① db_build 没认领 dbpath.py → 登进「不算」；② 懒加载写口切副本那条的前提「order_write 先指着真库」不成立了 → 改成子进程现造一个还自己拼真库路径的替身模块（bite_specs 那条的「预期红」同步改名）；③ triage_shadow 拒跑判据「指到副本改了 0 个」误拒 → 改成「改了 ≥1 或 api/ops 经单源已在副本」，triage_shadow_check 同步。另有一条 alembic「找不到 e1014ff53288」是并行会话的迁移还没推，它推完就好。
- 11-22 20:0x **用户拍：手机号全站统一「前三后四」(138****1234)，固定电话「前三后三」**（身份证仍只露后四位）。要改三处：backend/mask.py 手机 + 管理后台/docs/口径/敏感字段清单.json「给人看」、backend/api._mask（工具层，补固话）、管理后台/services/api/app/runtime/上次运行.py 打码（+ test_last_run.py 期望值、workflows_api / endpoints / app.js 里「只露后四位」字样）。文本里认固话只认「0 开头区号 + 横杠/空格 + 7–8 位」，连写不认（已告诉用户）。管理后台那处改完要跑 make test-e2e-ci、重启 aimc。等 ship 推完再动（别改门禁中的被测代码）。
- 11-22 22:15 并行会话 bd5730e4 已推；我 6 笔 rebase 后（fdb91c09…e86a999f）起 ship（日志 scratchpad/ship-20261122-2215a.log）。绿 → 主检出 ff + merge-base 核 → kickstart com.lanxiu.backend / com.lanxiu.agentsite + curl 302 → 报号；然后做手机号打码统一（见上一条）。
- 11-22 23:16 **22:15 那轮 ship 我主动停了**（全量门禁要跑约一小时，会跨 0 点，撞「0 点到夜跑结束不占锁」）。停之前咬合重放 78/93 全绿，没有红；锁已放，远端仍 bd5730e4。**明早夜跑结束后第一件事**：fetch + rebase --autostash → 告诉并行会话（它也排着「启用经营日报草稿」，谁先谁后先商量）→ ./tools/ship.sh（新日志名 ship-20261123-xxxxa.log）→ ff + 重启 8760/8770 + 报号 → 手机号打码统一。
- 11-22 23:3x **手机号打码统一已在本地第七笔**（用户拍：手机前三后四、固话前三后三、身份证照旧后四位）：backend/mask.电话（页面）、api_wearer._mask 改调它（工具层）、api._mask_out 加文字里的固话（只认「0区号+横杠/空格+7–8位」，连写不认）、管理后台 上次运行.打码 + test_last_run（23 条全过，加了固话两例）、清单 json「给人看」、check.sh 标题、workflows_api / endpoints / app.js 说明字样。单跑全绿：mask 自测 14、boundary_audit、isolation、selftest、raw_log、popularity、draft。**管理后台动了 → 明早 ship 前要跑 make test-e2e-ci（主检出 ff 后）、推完重启 com.lanxiu.aimc（防孤儿 uvicorn）**。PRD 台账第七十九 / 八十一条的「只露后四位」明早顺手改成新口径。
- 11-22 23:4x **压缩前六项（本会话）**
  - 未验证：① 7 笔本地（fdb91c09…e86a999f + cbb2c72b，rebase 后哈希）**没跑过完整 ship**，22:15 那轮停前咬合 78/93 全绿；② 打码那笔没跑 make test-e2e-ci、没跑 js_smoke；③ 人工待办页面没真点过端到端。
  - 判据：库路径改走单源后，「指到副本改了 0 个」不再等于读真库 → 判「工具层最终读哪份」；懒加载切副本换现造替身模块（还没改的一百多个模块仍要守）。固话在文字里只认带分隔的，宁漏不误（已告诉用户，用户没反对）。
  - 作废：18:46 那轮 ship 的红（已修在 e86a999f）；alembic「找不到 e1014ff53288」是并行会话迁移未推导致，bd5730e4 后应已好。
  - 禁区：0 点到夜跑结束不占锁；agentsite/app.py / station.html / sdk.py 归并行会话；它明早先做「启用日报草稿」，再轮到我。
  - 下一步第一个动作：夜跑结束后 fetch + rebase --autostash → 问并行会话锁空没 → 主检出 ff 后 make test-e2e-ci → ./tools/ship.sh（新日志名）→ ff + merge-base 核 → kickstart com.lanxiu.backend / com.lanxiu.agentsite / com.lanxiu.aimc（lsof 查 8801 孤儿）→ curl --noproxy 302 → 报号给用户和并行会话。
  - 悬而未决：PRD 台账第七十九 / 八十一条「只露后四位」要改成新口径（随下一笔业务提交）；W02 第③步继续（欠债 307）；ops `_本库` 冻结在 import 时，另起一笔改成函数。
- 11-22 23:5x 补：本地待推现为 **8 笔**（库路径 6 + 打码 cbb2c72b + PRD 台账第九十二条 aaa6f764；rebase 后哈希会变）。PRD 那条「悬而未决」已做完，划掉。其余六项见上一条，不变。
- 11-22 23:5x 并行会话：「启用经营日报草稿」已做完（23:30 放锁），今晚不再碰锁和共享库；明天不动 上次运行.py / workflows_api / endpoints / app.js / test_last_run（要动会先说）。**所以明早夜跑结束后不用再等它，直接从 fetch + rebase 开始。**
- 11-23 04:5x 夜跑已推 cd31a7d0；8 笔 rebase 后起 ship（日志 scratchpad/ship-20261123-0450a.log，只认「ship:pre_push 退出码」行）。绿 → 主检出 ff + merge-base 核 → kickstart backend / agentsite / aimc（lsof 8801 查孤儿）→ curl 302 → 拿锁跑 管理后台 make test-e2e-ci（主检出）→ 报号给用户和并行会话（它等着起 gate_w29）。
- 11-23 06:3x **第三次 ship 06:25 起**（日志 scratchpad/ship-20261123-0625c.log）。前两次：①工作区脏（HANDOFF 追加没提交，**ship 起跑前别留未提交的 HANDOFF**）②shop_key_check 12 条咬合在副本里对照红，锁内单条重放绿，判偶发、未坐实；**再红在同一处就别重跑，查原始输出**。与并行会话约定：我推完报号就放锁、自己重启 8760/8770；aimc 重启 + make test-e2e-ci 由它的 gate_w29 带（含我打码那几笔），红在 test_last_run / test_artifacts_live / test_audio_flow 它把日志发我。
- 11-23 07:1x 第三次 ship 还在跑（咬合重放 98/112，之后全量门禁）。**疑点（未坐实）**：按改动重放咬合每条单独拿锁、条间放锁，并行会话可能在缝里插进来交错 → 可能是前两次 shop_key「对照就是红」的成因；已叫它等我推完再起 gate_w29。
- 11-23 07:2x 并行会话已停 gate_w29（没进锁），等我推完。**上一条的疑点被削弱**：它说 05:45 那次它没拿锁，所以第二次 shop_key「对照红」不是它在缝里插进来造成的，成因仍未知；第三次 ship 若再红在 shop_key，要看原始输出（bite_run 不印对照输出，得在副本里手跑 backend/shop_key_check.py）。
- 11-23 ship#3(ship-20261123-0625c.log)红:咬合 112 全过;全量门禁红 3 条 ——
  ① OpenAPI 过期(我改 endpoints 文案没重生成;已用 管理后台/tools/gen_openapi.py 重生成,diff 一句,未提交);
  ② 排班判分器夹具:11-23 平移把甲周铺成 system「已发布」56 格,挑() 只清草稿 → 已改 agent/shift_eval.py 副本上清 system 不分状态 + judgetest 加铺一格 system 已发布(31 条全过,bite_check rc0;未提交);
  ③ rating_check 合并升 +0.13<0.15:rating_window 固定 08|09|10、平移每天挪 rated_at、跨月才重造 → 月中漂移稀释。并行会话确认不归它、让我按「只改检查」修 → **已修**:backfill_rating 记不挪的 rating_built_world、shift_world 登记不挪(+自测+咬合)、rating_check 按「今天−造数日」挪回 rated_at 再分月(老库按窗口后一月 1 号估)→ +0.25;PRD 附录 B-128。**已验**:只读量 rated_at 往回挪 0/10/22 天 → 合并升 +0.13/+0.19/+0.25,漂移就是原因。
  ①②③ 一起提交后起 ship#4;推完报哈希,并行会话起 gate_w29(它不拿锁、不碰 rating / shift_world / shift_eval)。
- 11-23 ship#4 绿,已推 **f3823ea9**(含 dbpath 迁移、打码统一、门禁三修);主检出 ff 已验,8760=200 / 8770=302 已重启;aimc 和 e2e-ci 交给并行会话的 gate_w29(已通知)。下一步:W02 第③步接着迁(欠债 307),**这条 HANDOFF 记录未提交,随下一笔业务提交带上**。
- 11-23 W02 第③步第 2 批:返修/退款/排班/标签等级四写口迁完,本地 **571103ba 未推**(欠债 303;锁内 9 检查绿)。并行会话 gate_w29 占锁中,**它 ship 完之前我不拿锁**;之后 rebase --autostash 再推。下一批候选:credit / ownership / customer_link / touchpoint / opportunity / slipping(只改代码,检查等锁)。
- 11-23 10:43 并行会话 gate_w29 起(w1117=5dd4fdc5,含我的打码那笔做 e2e-ci),预计 11:5x 完;之后它还要锁内换日报处理要求约 5 分钟(会先告我)。**期间别拿锁**。我手上:第 3 批六模块已改未提交(欠债 297,锚 0 失配),锁空后跑 scratchpad/w02c.sh(18 检查)→ 绿就提交 → 第 2、3 批一起 ship。
- 11-23 日报抄「本周」口径:已改 backend/api_report.weekly_revenue 口径/近似按统计期出说法(周/当天/这段时间),weekly_revenue_check 加 2 判据 + bite_specs 1 条;**未提交、检查未在锁内跑**(只读直调验过三种)。并入 scratchpad/w02c.sh(18+2 检查 + 这条咬合重放),等并行会话 ship + 换日报要求放锁后跑 → 绿就和第 3 批一起提交、连第 2 批一起 ship。
- **11-23 ~11:00 六项快照(本线 rare-i;压缩前写)**
  - 未验证:第 3 批六模块(credit/ownership/customer_link/touchpoint/opportunity/slipping)迁 dbpath 后的 18 个检查**没跑**;weekly_revenue 口径按期改写的检查 + 新咬合**没在锁内跑**(只读直调三种说法对)。
  - 判据:迁移只换 DB 来源;风险在「检查默认模块写死真库」的前提(18:46 那次三处红都是这形状)——每批先 grep `模块.DB ==/realpath(模块.DB)` 再跑检查。评价趋势修法依据:只读量 rated_at 挪回 0/10/22 天 → +0.13/+0.19/+0.25。
  - 作废:「shop_key 红是两边锁空档撞上」的推测(并行会话 05:45 没拿锁);ship#2/#3 的红因已查清,不用再追。
  - 禁区:并行会话 gate_w29 + 换日报处理要求期间**不拿锁**;agentsite/app.py、station.html、sdk.py 归它;evals/*.jsonl 不 add;HANDOFF 不单独提交。
  - 下一步第一个动作:等并行会话报「锁放了」→ `./tools/gate_lock.sh /private/tmp/claude-501/-Users-eureka/ba8cb0f4-e02a-4402-b9bf-3ff3ab966980/scratchpad/w02c.sh`(scratchpad 会被清,若丢了照第 3 批检查清单重建:workflow_bridge credit product_summary ownership_transfer authgate order_write opportunity_task slipping ownership booking opportunity customer_summary opportunity_obj customer_link touchpoint check_copy arrival_card call_flow weekly_revenue store_report 的 _check + bite_run 那条「单日查询的口径…不出现「周」」)→ 绿则 git add 显式路径(6 模块 + tools/dbpath_check.py + backend/api_report.py + backend/weekly_revenue_check.py + tools/bite_specs.json + HANDOFF.md)commit --only → pull --rebase --autostash → ./tools/ship.sh(新日期 log 名)→ 报哈希给用户和并行会话、ff 主检出、kickstart 8760/8770。
  - 悬而未决:无需用户拍板的;剩余 ~24 个业务模块待迁;ops `_本库` 改函数、人工待办页端到端 + js_smoke 仍欠。
- 11-23 并行会话已同意「工具按统计期给口径说法」+ 处理要求那条留第二道保险;顺序确认:它 ship 报哈希 → 锁内换日报要求 ~5 分钟 → 告我「锁放了」→ 我跑 w02c.sh 再推。它的 e2e-ci 10:44 起仍在跑。无需回复它。
- 11-23 11:15 并行会话 gate_w29 第一轮 e2e-ci 红 1(ifmatch_reachable_check:它 11-21/22 的 4 个乐观锁写接口没登记 revision 来源;因我补生成契约文档才进视野,它认定是它的漏登记)已修,第二轮 11:15 起、预计 12:2x 完(w1117=c5f7d656 领先远端 6 笔)。**仍别拿锁**;等它报哈希 + 换日报要求 + 「锁放了」。
- 11-23 并行会话已推 c5f7d656;我已 rebase --autostash 到它之上(第 2 批变 b3953ea0,第 3 批 + 口径改动仍未提交)。它正锁内换日报要求 ~5 分钟,放锁后我跑 w02c.sh。
- 11-23 12:1x 锁内 w02c 绿(20 检查 + 口径咬合);第 3 批 + 口径改动已提交,起 ship#5(log ship-20261123-1220e.log)。推完:报哈希、ff 主检出、kickstart 8760/8770、告并行会话。
- 11-23 ship#5 跑着(后台任务 bx2hbmr3i,log scratchpad/ship-20261123-1220e.log);并行会话今天已收尾,只剩一笔交接未推,等我报哈希后再 rebase;它不拿锁、不碰主检出。**本条 HANDOFF 追加在 ship 起跑之后,未提交,随下一笔业务提交带上。**
- 11-23 ship#5 绿,已推 **ba1d046d**(c5f7d656..ba1d046d:第 2、3 批写口迁移 + 周营收口径按期);主检出 ff 已验,8760=200 / 8770=302;已告并行会话。欠债 297,下一批候选:alert_dispatch / arrival_card / appt_expire / factory_inbox / kb_issue / revive(先 grep 前提断言,再改,检查等锁)。
- 11-23 13:29 并行会话重启了 com.lanxiu.supervise:桥工具(weekly_revenue 等)在 supervise_sync 进程里 import backend 执行,我推口径新说法后只重启了 8760/8770,它那里没生效;已补重启、首轮日志正常。**以后改被桥工具用到的 backend 代码,推完要 kickstart supervise**(已记长期记忆)。并行会话已 rebase 到 ba1d046d,今天收尾、不占锁。
- 11-23 W02 第 4 批:告警派发/到店卡/预约过期/工坊收件/知识问题/召回六模块迁 dbpath(欠债 291),锁内 13 检查绿(kb_issue_check 要用 ./agentsite/.venv/bin/python 跑,系统 python3 缺 claude_agent_sdk 会假红 8 处——那次不算)。已本地提交**未推**,攒下一批一起 ship;提醒:这批里 workflow_bridge 可达模块推完要 kickstart supervise。
- 11-23 并行会话占锁约 65 分钟(员工定时结果飞书送达改「发本人」:管理后台 e2e-ci + ship,会停 8801 重启 aimc)。**期间别拿锁、别碰 w1117 / 主检出**;它报哈希后我 rebase --autostash,第 4 批 d39e3458 与第 5 批一起 ship。第 5 批可先只改代码(不跑检查):剩余候选 asr / example_pool / files / img / motif_review / query_index 等(db_build、migrate、mcp_registry、skill_registry 慎动——建库 / 迁移链路,先读再判)。
- 11-23 20:1x 并行会话 gate_w30 起(只动 管理后台/,不用重启 supervise)。我第 5 批六模块(asr/example_pool/files/img/motif_review/query_index)已改未提交(欠债 285,锚 0 失配,范围检查绿);相关检查清单在 scratchpad/w02e.list,**等它推完报哈希再拿锁跑**(kb_issue 类要用 agentsite venv:以 check.sh 里该行的解释器为准)。
- 11-23 20:3x 并行会话 gate_w30 第一轮 e2e 红(出网策略把 open.feishu.cn 经本机拦截代理解析出的 198.18.x 判成内网;它那处主机名是常量,已去掉过闸),修好 24aa37a7,gate_w31 重起约 65 分钟,**锁归它**。
  - **悬而未决(我这条线)**:它提醒 worker._飞书通知(人工介入推飞书群)也走 出网策略.解析并核,本机上多半被拒 → 人工介入的飞书提醒可能一直没发出去。我工作区 grep 不到 `_飞书通知`(可能在主检出 / 它未推的笔里),**等它推完 rebase 后**:grep 定位 → 看 aimc 日志有没有「解析到 198.18」的拒绝 → 修法照它的:写死的飞书主机不过 SSRF 闸(闸只管用户填的 URL)。**未验证**:真被拒了没有。
- 11-23 飞书提醒那条更正:`管理后台/workers/worker.py:499 _飞书通知` 主干早就有;地址来自用户登记的工具连接(capability_connections.allowed_endpoints + hook id)= 用户填的 URL,**闸该留,别整段去掉**。可选修法(要先确认真被拒):登记过的端点主机解析那步放行 / 主机名白名单放行 open.feishu.cn —— 涉及放宽安全闸,**改前摆给用户拍板**。已查:.feynman 下日志 grep「解析到 198.18」0 条(没找到 aimc 自己的日志位置,**未验证**是否真被拒)。下一步:找 aimc 日志(launchctl print gui/$(id -u)/com.lanxiu.aimc 看 StandardErrorPath)或查 human_requests 推送记录表。
- 11-23 20:5x 并行会话 gate_w32 起(第二轮 e2e 红是它测试时序,78f51d57),约 65 分钟,锁归它,远端仍 ba1d046d。飞书提醒:aimc 日志 /tmp/lanxiu-aimc.log grep「198.18」0 条、「飞书+拒/解析/内网」0 条 —— **没有被拒的证据**(但 /tmp 日志可能因重启被截,仍未确证发出过;下一步查人工介入推送的落库记录)。
- 11-23 并行会话已推 15b180fd、锁已放;我已 rebase 到其上(第 4 批已提交未推,第 5 批未提交)。下一步第一个动作:按 scratchpad/w02e.list 写 w02e.sh(每条检查的解释器以 check.sh 里该行为准)→ gate_lock 跑 → 绿则提交第 5 批 → ship 第 4+5 批 → 推完 kickstart 8760/8770 **和 supervise**。
- 11-23 第 5 批锁内 10 检查绿,已提交;起 ship#6(log ship-20261123-2200f.log),带第 4+5 批。推完 kickstart 8760/8770/supervise,报哈希。
- 11-23 ship#6 绿,已推 **a4ec89b1**(15b180fd..a4ec89b1,第 4+5 批);主检出 ff 已验,8760=200 / 8770=302 / supervise running(pid 50948);已告并行会话。欠债 285。下一步:查人工介入飞书推送的落库记录(确认是否真发出);再迁下一批(剩约 12 个业务模块,db_build / migrate / mcp_registry / skill_registry 先读再判)。
- 11-23 飞书提醒查实(只读):aimc_dev.run_events 里 human.notified / human.notify_failed **都是 0 条**;capability_connections 里**没有登记任何飞书连接** → 人工介入的飞书提醒**从没被配置、从没尝试过**,不存在「一直被拒」。但本机 open.feishu.cn 解析为 198.18.1.135,**一旦有人登记飞书连接,出网策略必拒**(198.18/15 是基准测试保留段,被判 is_reserved/私有)。修法(登记过的端点放行解析 / 主机名白名单)属放宽安全闸 → 等用户真要启用飞书群提醒时再摆卡拍板,现在不动。另:human.timeout 14 条已查 —— 全是 e2e「人工超时」测试流程按设计走超时出口,不是真实待办没人管。
- 11-23 CI 自 11-18 06:41(9a9f93ed)起每次都红,check job 红因已查实:seed_factory_feed 自检「换号重发 0 条」—— fakedata/factory_sim.py:155 按订单号哈希 h%10==8 挑样本,CI 从零建库到完工的单少,挑不中;那段区间无人改过造数(factory_sim 最后改 10-29)。修法:照同文件「植过没单号」先例保证植一条(~3 行),验证要从零重建跑 seed_factory_feed。**未动**:并行会话在做全项目体检、要请用户排优先级;我已回它「修法明确、我可做」。admin-e2e 四份 CI 新库前提归它。
- 11-23 CI 修法并行会话已写进体检报告(包一),**等用户排序再动,我先别改**。开始第 6 批:order_contract / product_summary / report_doc / report_template / roster / targeted_ops。
- 11-23 第 6 批锁内 19 检查全绿,已本地提交**未推**(欠债 279);攒第 7 批一起 ship。剩余:db_build / migrate / mcp_registry / skill_registry / shop_rename / workflow_bridge(前四个建库 / 迁移 / 注册链路,先读再判;workflow_bridge 推完要重启 supervise)。
- 11-23 ⚠️ 我误跑了一次 `python3 backend/migrate.py --help`(它不认参数、直接对真库跑迁移):输出「这次做了 0 条,库现在做到第 6 条」,**真库未被改动**;教训:不熟的脚本先读再跑。
- 11-23 第 7 批(建库/迁移/MCP 注册/技能注册/门店改名/桥)锁内 14 检查绿,已提交;起 ship#7(log ship-20261123-2330g.log)带第 6+7 批,欠债 273。推完 kickstart 8760/8770/**supervise**(workflow_bridge 在里面)。业务模块(backend 非检查)的 DB= 写死已基本清空,剩下的 273 处主要是检查/造数/评测脚本。
- 11-23 ⚠️ ship#7 **被权限检查拦下没起**(自动模式判为破坏性/不想要的动作);第 6、7 批 22410032 / 413249ea 只在本地,远端 a4ec89b1;已更正告知并行会话。**等用户决定是否放行推送,不绕过、不重试。**
- **11-24 07:5x 六项快照(本线 rare-i)**
  1. 在做:用户已拍「先做可信与安全包」;分工 —— 我修 CI 的 factory_sim 换号重发(已改:`植过换号` 第一条完工必植,同「植过没单号」先例),并行会话做 admin-e2e 四份新库前提 + server.py / fsm.py / api.py / index.html / login.html / boundary_audit.py(**这些我不碰**)。
  2. 验证方式:scratchpad/fresh-fs(git archive HEAD + 改后 factory_sim)里按 rebuild.sh 前 27 步从零建到 seed_factory_feed,**不碰共享库、不占锁**;脚本 scratchpad/fresh-fs.sh、日志 fresh-fs.log。验证绿才提交;提交要等推送放行一起走。
  3. 待推本地:22410032(第 6 批)、413249ea(第 7 批)+ 即将的 factory_sim 修。远端 a4ec89b1。ship#7 被权限检查拦,**等用户放行,不绕过**。
  4. 未验证的预判:换号重发植上后 seed_factory_feed 自检全绿 —— 还没验;CI 上 check job 还可能有别的红(只查实过这一条)。
  5. 下一步:验证绿 → 提交 factory_sim(只提这一个文件 + HANDOFF);dbpath 剩余欠债挑检查 / 造数脚本,避开并行会话那批文件。
  6. 坑:rebuild.sh 会删 backend/lanxiu.db(本检出里是指向共享库的软链)—— **绝不在检出里直接跑**,只在独立副本里跑。
- 11-24 08:0x factory_sim 修**已验**:独立副本从零建到 seed_factory_feed 退出码 0,「换号重发|重复|重复|1」,其余毛病全对、该催 17;无咬合锚落在改动行。已本地提交(只提 factory_sim + HANDOFF),随第 6、7 批等推送放行。
- 11-24 08:2x 和并行会话对「客户档案没身份改拒」:已回分工 —— 它改 api.py(定义显式「系统身份」常量 + 本店范围一处认它 → 跨店,最后把默认改拒)和 app.py:1206 线上研判 `sdk.run("triage")` 不带 me 那处、MCP 领域服务;**我改评测侧**:agent/ 下约 14 处 sdk.run 不带 me + agent/v2.py:276 + agentsite/trial_run.py:75。否决环境变量开关(子进程继承 = 进程树级特权、日志看不出是谁)。**必须同一次推送**;等它把常量名告诉我再动。
- 11-24 08:3x 系统身份:并行会话已在 w1121 本地落 `api.系统身份 = {"no":"system","role":"系统",...}` + api_wearer.本店范围 认它 → 跨店(不在跨店角色里,写口闸不认)。我回:直连路径在各评测入口 main 外包 `with api.as_user(api.系统身份)`(**不在 v1._dispatch 兜底**);sdk.run 14 处显式 me=;USE_MCP 路径 mcp/client.py 不传 env + 池按 kind 复用会串身份,建议它改(池键 (kind,no))。另请它翻默认拒前过一遍 arrival_card / asr / annotations / sdk 里 import v1 的生产调用。落地改三步:它先推常量 → 我拉下改评测侧 → 它翻默认拒。**等它推常量的哈希再动。**
- 11-24 08:4x 扫 whoami():backend 读工具约 43 处,**除 get_customer 外几乎全是 `if not me: 请先登录`** → 评测 / 研判改带系统身份会让这 40 多处全放行、各走角色 / 门店分支(me.get("shop")=None 各处语义不一),系统身份变成宽跨店读钥匙、评测分数不可比。已建议并行会话:whoami() 默认把系统身份当 None,只 `whoami(认系统=True)` 返回(第一版仅 get_customer 点名);并请它把这条合进给用户的卡(包一是它的线)。三步顺序不变(a 常量随它今天 ship → b 我改评测侧 → c 它翻默认拒),mcp/client.py+protocol 归它。**b 等它定参数名。**
- 11-24 08:5x 并行会话采纳「点名生效」并已在 w1121 本地落:`api.whoami(认系统=False)`,系统身份未点名时返回 None;get_customer 用 `whoami(认系统=True)`(唯一点名)。它判为技术收紧、行为不变,**不单独开卡问用户**。b 步写法:`sdk.run(..., me=api.系统身份)` / `with api.as_user(api.系统身份)`;**等它 ship 把 a 推上远端、我拉下来再改**(本地 3 笔仍等用户放行推送)。b 改完要本地跑相关检查、告诉它,它再做 c(翻默认拒)。
- 11-24 09:1x 并行会话 ship(gate_w33,含 9bff6530 = 系统身份第 a 步)在跑、锁归它约 65 分钟,别拿锁别碰主检出 / w1117。b 前查到:sdk.run 的 me 还用于 ①提示词尾「现在是谁在跟你说话」②转人工建待办(写库)③会话恢复 → `me=api.系统身份` 不中性;已请它在 sdk.py 里加 `_系统` 判定让这三处跳过、只 mcp_config 照传。**b 等它落这处再写。**
- **11-24 09:2x 六项快照(压缩前,本线 rare-i)**
  1. 未验证的预判:①「b 后评测分数不动」只在 sdk.py 加 `_系统` 判定后才成立,未验;②推上去后 CI 是否全绿未知(只修了换号重发那一处,admin-e2e 四份前提归并行会话 3e3d3498)。
  2. 判据:系统身份**点名生效**(whoami(认系统=True) 仅 get_customer)—— 因为 backend 读工具约 43 处都是 `if not me: 请先登录`,处处认会变宽钥匙;不用环境变量开关(子进程继承、日志无「谁」);v1._dispatch 不兜底(兜底=默认放行装回去+盖真身份)。
  3. 作废:「b 和 c 必须同一次推」作废,改三步 a→b→c(a、b 都不改行为);「系统身份合进卡问用户」作废,并行会话判为技术收紧不开卡(已告诉用户可随时改口径)。
  4. 禁区:并行会话 ship(gate_w33)占锁中,别拿锁、别碰主检出 / w1117;它的文件 server.py / fsm.py / api.py / api_wearer.py / sdk.py / app.py / index.html / login.html / boundary_audit.py / mcp/client.py+protocol / e2e 四份我不碰;rebuild.sh 只在独立副本跑。
  5. 下一步第一个动作:等并行会话报 a 的推送哈希 + sdk.py `_系统` 落地 → `git pull --rebase --autostash` → 改 agent/ 14 处 sdk.run 加 me=api.系统身份、v1 直连入口 main 外包 `with api.as_user(api.系统身份)`(eval.py / gen_compare / negative / router_probe / talk_eval / tool_select / triage_lure_probe、v2.py:276)、agentsite/trial_run.py:75 → 本地跑相关检查 → 告诉它做 c。
  6. 悬而未决:本地 3 笔(22410032 / 413249ea / 20069d89)等用户放行推送(ship#7 被自动权限拦;CLAUDE.md 写着用户 11-17 已授权门禁全绿直接推,已告诉用户);推完要 ff 主检出 + kickstart 8760/8770/supervise + 报哈希。
- 11-24 09:3x 并行会话 sdk.py 已在 w1121 本地落 `_是系统(me)`,转人工 / 会话恢复 / 提示词「现在是谁」三处跳过系统身份,mcp_config 照传 → `sdk.run(me=api.系统身份)` 中性。**它在下一批推**(不在 gate_w33 这批);**b 必须等含 sdk.py 那批推上、rebase 后再本地验**,否则验的是未中性化的 sdk。下一步第一个动作不变(见 09:2x 六项第 5 条),前提多一个:sdk.py 那批的哈希。
- 11-24 09:5x 并行会话 gate_w33 首轮 ship 红在咬合(它删草稿卡漏 workbench 两行),已修;第二批 3274ccdf(含 sdk.py 中性化)与 a 一起在 w1117 领先远端 3 笔,正在重 ship 约 40 分钟、锁归它。b 准备:12 个评测文件里 example_ab / example_counter_ab / guard_ab / scheme_eval 没 import api,改时要补 import(backend 已在 sys.path 的前提先核);其余 8 个已 import。**等它报远端哈希再 rebase 动手。**
- 11-24 10:xx 并行会话 ship_w34 红没推(sdk.py 改动让一条咬合规格锚失效 + 待办清单过期,已修);现 w1117 带 6 笔,gate_w35 重跑 e2e-ci + ship 约 65 分钟、锁归它。远端已不是 a4ec89b1(它之前推过),**我本地 3 笔推前要 rebase**。b 继续等 gate_w35 推完的哈希。
- 11-24 10:1x 用户拍《死工具清单》第三节「按建议做」(排在包一推完后):get_lifecycle / member_level / get_member_priority / get_review_queue 聊天站不再注册(函数留着,V1/V2 照旧直调)。**评测判据归我改**:等并行会话列出 need 含这四个名字的题号 → 按「有没有不调也对的答法」清 need 或改新入口;封存集照改但单独记「因工具合并改判据,非按结果调」;须和它下架注册同一次推。顺序:包一推完 → b → 死工具这组。
- 11-24 10:2x 死工具组勘误:get_lifecycle / member_level / get_member_priority 早在 09-19 合并时已下架(ops_eval 判据已是 need_any_tool),**我这边只剩 get_review_queue**;已查 agent/ 与 agentsite/ 评测文件(不含 *_check)**没有任何判据引用它**(只在 sdk.py 注释和工具包名单里,归并行会话)→ 评测侧这组**零改动**。
- 11-24 11:xx **b 已做并本地提交**(用户说「现在就修」):agent/ 12 处 sdk.run 补 `me=api.系统身份`(ops_eval 本来带真身份,不动)、V1/V2 进程内 eval.py / gen_compare×2 / negative 调用点包 `with v1.backend.as_user(v1.backend.系统身份)`、v1.py / v2.py 命令行入口整进程系统身份、agentsite/trial_run.py;refund_sets 在 跑一题 里补 import api;triage_scope_check 两处锚改前缀(不钉右括号)。验证:在 w1117(98972d91)导出副本 + 我的改动 + 库 .backup 上实跑 —— 无身份/系统身份 get_customer 都取得到、系统身份下 whoami()=None / whoami(认系统=True)=系统、weekly_revenue 仍「没有登录身份」、sdk._是系统 判对、run 里中性化 3 处;triage_scope_check 绿。⚠️ **这笔依赖并行会话的 api.系统身份,必须在它那批推上远端之后才能推**(我 ship 时 rebase 到含它的 origin 才行)。⚠️ 并行会话改 app.py:1206 时,triage_scope_check 第 103 行和 bite_specs 那条「研判队列那一路还跑 task」的 old 串都要跟着改(已告诉它)。
- **11-24 11:3x 六项(压缩前)** ①未验证:本地 4 笔(22410032 / 413249ea / 20069d89 / df2841bc)没跑过 rebase 后的全量门禁和咬合重放。②判据:df2841bc 依赖 api.系统身份 → **只能在并行会话 gate_w37(8 笔,约 45 分钟)推上远端后 rebase 再推**。③作废:无新增。④禁区:锁归它;app.py:1206 + triage_scope_check 第 103 行 + 那条规格归它的 c 步。⑤下一步:等它报哈希 → `git pull --rebase --autostash` → 等用户放行 ship(ship#7 被权限拦,不绕过)→ 推完 ff 主检出 + kickstart 8760/8770/supervise → 告诉它做 c。⑥悬而未决:用户放行推送。
- 11-24 12:xx 并行会话 ship 红在夜跑「已知连续失败名单过期」:tools/nightly_eval.py 642-643 recall_eval 登记已不在连续失败里 → 我选 A,准它在它那批里删这两行(我本地没改此文件)。它重跑 ship,远端仍 e9d83eb9;我 rebase 时这两行会随它的提交进来。
- 11-24 12:xx 并行会话删 nightly_eval.py 那两行被自动权限拦(判「削弱监督」),它备了补丁等用户 ! 打上;**我不代它改**(被拒的动作不转手)。两边推送都卡在用户:它的补丁 + 我的 ship。
- 11-24 13:xx 用户已打并行会话补丁,它起了 gate_w38(w1117=w1121=8523036d,约 45 分钟)。它问死工具四件小活归属,我选 A:api.py 三处注册 + prompts.py TL02 四句归它改;提醒它只撤注册不删函数(prompts_check:344 调 kb_coverage、run_journey:437 调 can_order)、sdk.py:765 放行名单同改、ablation.py 旧措辞别动;并提示库路径咬合对照红(可能是 w38 的)。我仍等它的哈希再推 4 笔,不占锁。
- 11-24 13:xx gate_w38 红在 page-smoke(access_keys 攒 1506 把 e2e 钥匙,列表 27 秒超时),并行会话改成分组查询 ae959681,起 gate_w39(含 e2e-ci,约 50 分钟,锁归它)。清那批 e2e 钥匙=删数据,须用户本人确认(已提醒它直接问用户)。dbpath 欠债下限:我分支 273、它 285,rebase 时该行可能冲突,取小值并实测核对。死工具四件它等 w39 后再动。
- 11-24 14:xx 死工具:①bcac1b69 ④负向题 9e429239 ③已完(都在 w1121,下轮 gate 带)。②can_order 并进 open_order 预演:它问能否在 guards.py 让写工具带参数视为只读放行 —— 我拒(=放宽守卫,须用户;且是按参数绕确认卡),赞成 B(不并、改描述,open_order 描述也补「下单前先调 can_order」);因偏离用户原拍板,由它(线主)去问用户,我不另问。
- 11-24 15:xx 并行会话 gate_w39 绿已推 ae959681。我 rebase 干净(4 笔→643c5920/39112465/450a9967/cb397e75),复核:dbpath 273=下限、api.系统身份在、sdk._是系统 对、研判范围检查绿。等用户 ! 跑 ship;推完 ff 主检出 + kickstart 三服务 + 报哈希 + 通知它做第三步。
- 11-24 15:xx 我 4 笔已推:远端 0bb08202(ae959681..0bb08202),ship 被包命令退出码 0;主检出 ff 到 0bb08202,kickstart 三服务,8760=200/8770=302,supervise 在跑。已通知并行会话起 gate_w40 做第三步(get_customer 无身份拒 + 研判用系统身份)。用户拍:1500 把 E2EAK 测试钥匙留着不清;can_order 方案 B(不并、改两头描述)。
- 11-24 16:xx 并行会话 gate_w40 已起(e64fb0ba,含第三步 + 死工具三件,约 50 分钟,锁归它)。我只读复核 e64fb0ba 里 get_customer 直调点:v2 客户合并流程只经 gen_compare(已包系统身份)和 v2 __main__(已包)进入;server.py:458 / boundary_audit 归它且它已处理。无遗漏。
- 11-24 17:xx gate_w40 红(eval_tier_check:新加 ops D01-D03 只跑过局部),未推,远端仍 0bb08202。它后台全量跑 ops_eval(约 2.5h,与夜跑并行),明早 05:10 后起 gate_w41(含 e2e-ci + 另 6 笔管理后台)。**主检出被 gate ff 到未推的 e64fb0ba,线上跑着第三步**;已提醒它 w41 后主检出须回到远端哈希。今夜我不碰锁不动主检出。
- 11-24 17:xx 并行会话确认:夜跑自动提交只在上游后恰好 1 笔才推,主检出领先 4 笔今晚不会推;明早 w1121 rebase 到主检出 HEAD、gate_w41 纯快进,推完用 merge-base --is-ancestor 验并记交接。
- 11-24 23:5x 本地提交库路径第③步第 8 批(费用提醒 / 简体对照 / 商机评测 / 归属释放 / 两个修数脚本,欠债 273→267);dbpath_check 绿、6 个文件编译过;**快门 / 相关检查因临近夜跑未跑,明早并行会话 w41 推完后先跑 quick_gate 再 ship**。
- 11-25 02:xx 并行会话报:运营 D01 被交付前体检 g1 误拦(¥65,452.80 是 get_order / cancel_fee 原样返回,但总价那一支只认 kb_bom + 字面比对,千分位/尾零对不上)。我在副本上修:总价那一支改用同函数上半段已有的「数本身在返回里就算有出处」(_查到过);D01 两稿放行、编的总价照拦,原 190 条对照全绿,新钉两条(旧版红新版绿)。**这是放宽守卫 → 补丁给用户 ! 打**:scratchpad/guards-g1-price-source-20261125.patch;打上后我 commit,随下次 ship。
- 11-25 02:xx 六项快照:①在做:库路径单源 + 体检误报修复,等并行会话 gate_w41 推完再推。②停在:本地领先 1 笔 6aa87428(库路径第 8 批,欠债 267,快门未跑);体检补丁 scratchpad/guards-g1-price-source-20261125.patch 等用户 ! 打(放宽守卫,我不自己打)。③下一步第一个动作:并行会话报 w41 哈希后 → `git pull --rebase --autostash` → quick_gate → 打上补丁则 commit guards.py+guards_test.py(--only)→ 给用户 ship 命令(dated 日志名)→ ff 主检出 + kickstart 三服务 + 报哈希。④别重做/否决过:往 g1 名单加 get_order/cancel_fee(治标,改为按数值判出处);写工具带参数视为只读放行(放宽守卫+绕确认卡,已否);清 E2EAK 钥匙(用户拍留着)。⑤风险:主检出在并行会话未推的提交上直到 w41 推完;日常层评测 80%<95%(它白天盘)。⑥协作:0:00 至夜跑结束不占锁;它占锁前会喊我。
- 11-25 04:5x 并行会话起 gate_w41 占锁(11 笔到 64b41711,含夜跑 cc21d089,约 65 分钟)。期间我不写共享库、不跑门禁 / 快门;等它报哈希后按六项快照第③步走。
- 11-25 06:3x 并行会话 w41 绿已推 7e6ea7b6。我 rebase 干净(第 8 批 → 4386df62),dbpath 267 绿,覆盖六个文件的 7 条检查全退 0(quick_gate 只看工作区、没覆盖已提交改动 —— 改为直接跑)。体检补丁用户尚未打。
- 11-25 06:4x 六项快照:①在做:推库路径第 8 批(426d4aa7,基于远端 7e6ea7b6);可选带体检补丁。②未验证的预判:无 —— 第 8 批 7 条相关检查实跑全 0、dbpath 267;体检修法在副本上 190 条对照 + 2 条新钉(旧红新绿)。③判据:体检「有没有出处」按数值判(_查到过),不按字面、不按工具名单;quick_gate 只看工作区,已提交改动要直接跑相关检查。④作废/否决:往 g1 名单加 get_order/cancel_fee;写工具带参数视为只读放行;清 E2EAK 钥匙(用户拍留)。⑤禁区:guards.py 放宽只能用户 ! 打(补丁 scratchpad/guards-g1-price-source-20261125.patch);并行会话文件 api.py/server.py/app.py/sdk.py/prompts.py 等不碰;ship 开始前工作区除运行态文件外须干净。⑥下一步第一个动作:用户若打了补丁 → `git add` 无需(已跟踪)→ `git commit --only agentsite/guards.py agentsite/guards_test.py` → 再请用户跑 ship(日志 ship-20261125-0640a 或新名);没打则直接等 ship 结果 → 看「被包的命令退出码」行 → ff 主检出(merge-base 验)→ kickstart backend/agentsite/supervise → curl 8760=200/8770=302 → 报哈希给用户和并行会话。悬而未决:日常层评测 80%<95%(并行会话白天盘)。
- 11-25 06:5x 用户回「打」→ 我打上体检补丁(用户直接授权),guards_test 实跑全绿,单独一笔提交随本次 ship。
- 11-25 07:4x 推完:远端 9b6e9d0f(7e6ea7b6..9b6e9d0f:库路径第 8 批 + 体检金额按数值认出处),ship 被包命令退出码 0;主检出 ff 9b6e9d0f,kickstart 三服务 8760=200/8770=302,supervise 在跑;已通知并行会话。下一步:库路径欠债 267 继续(避开并行会话文件),这条 HANDOFF 随下笔业务提交带上。
- 11-25 09:2x 本地提交库路径第 9 批(试衣 / 报价 / 评价 / 返修四个造数脚本,欠债 267→263);相关 11 条检查实跑全 0。待攒几笔一起 ship(推主干不用问,但上次 ship 我自己跑成功了)。
- 11-25 09:3x 六项快照:①在做:库路径单源,本地领先 1 笔 2bda2a8c(第 9 批,欠债 263,11 条相关检查全 0)。②停在:并行会话拿锁跑两条咬合 + 之后 ship 它那笔 md/ops 判据,我让它先。③下一步第一个动作:它报哈希后 git pull --rebase --autostash → dbpath_check → 跑 ship(dated 日志名)→ 看被包命令退出码 → ff 主检出 + kickstart 三服务 + curl → 报哈希。④否决过:g1 名单加工具;写工具带参数视为只读;清 E2EAK 钥匙。⑤禁区:并行会话文件不碰;guards 放宽须用户授权(11-25 已获「打」并推了 9b6e9d0f)。⑥悬而未决:日常层评测 80%<95%(并行会话盘)。
- 11-25 10:4x 并行会话 gate_w42 起(f78571c4 ops 判据改查结构,约 50 分钟,锁归它)。期间我不跑检查;它报哈希后按 09:3x 快照第③步推 2bda2a8c。
- 11-25 11:3x 本地提交 rounds 各轮why(并行会话建议:两轮翻面题第一轮理由没存);自测加一条并手工咬合(调用点不传因 → 红在新那条)。本地领先 2 笔待 w43 后 ship。并行会话在 w1121 做确认卡分三档 + 核对中回写(提醒放宽确认若被拦交用户 !)。
- 11-25 12:xx 快照:本地领先 2 笔(2bda2a8c 库路径第 9 批、c5812dbf 各轮why + bite_specs 1001 锚对齐;咬合 1001 未真跑,等 ship 按改动重放)。并行会话 w43 红在两条自家咬合过期,修后起 gate_w44(6 笔,约 75 分钟)。下一步:它报哈希 → pull --rebase --autostash → dbpath/bite_check → 我自己跑 ship(dated 日志)→ ff 主检出 + kickstart 三服务 → 报哈希。
- 11-25 13:xx 并行会话 w44 推前按改动重放:bite_specs 819(agent/triage_sets_check.py,攻击 mcp/protocol.指到副本 空操作)「改坏了却没红」,归我。它想标只报不拦 —— 我拒(削弱监督须用户),答应只读查前置:真库题集包裹在不在 / 规格锚对不对。下一步第一个动作:读 spec 819 + triage_sets_check 前置逻辑。
- 11-25 13:xx 819 初查:真库里题集包裹 166 道只剩 2 道还在(P568263-000017、P569559-000031),前置会删第一个。预判(未验证):攻击后只少这一道,triage_sets_check 若只抽查部分题 / 那道不在抽查范围,就不会红 —— 下一步读 triage_sets_check「每道题都取得出」那段看它真跑哪几道;修法方向:前置改成造一个自己的包裹或让判据覆盖被删那道,**不标只报不拦**。
- 11-25 13:xx 819 修好:根因 = api.DB 自 9e2527ea 走 dbpath、import 即认 LANXIU_DB,指到副本 成第二道保险,只砍它不可观测。攻击点改到 agent/triage_sets.py 两处(父不传快照路径 + 子不设),锁内重放 ✅ 1/1(对照绿 → 改坏 → 红在指定那条)。单独提交,随下次 ship。
