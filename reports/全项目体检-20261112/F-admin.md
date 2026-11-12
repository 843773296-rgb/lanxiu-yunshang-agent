# F · 管理后台(AI 管理后台,:8801 / PostgreSQL)只读深度体检

> 2026-11-12 · 只读。没有改文件、没有 git 写、没有重启、没有跑 alembic / check.sh / make 任何目标;
> PostgreSQL 只跑了 `SELECT`(库 `aimc_dev`)。唯一「跑」的东西是 `python3 -I tools/css_class_check.py`(纯读文件的检查)。
> 每条结论标 **已核实(file:line)** 或 **推测**。路径相对 `/Users/eureka/Desktop/澜绣云裳agent/管理后台/`,根目录文档用 `../`。

## 0. 一页总览

| 维度 | 数字 | 来源 |
|---|---|---|
| Python 文件 / 行 | 379 个 / 91 446 行(不含 .venv、.claude、.wip-*) | `find … -name '*.py' \| wc -l`、`wc -l` |
| 路由装饰器 | **260** 条,分布在 36 个 `*_api.py` + `main.py`;契约登记表 **261** 条 | `grep -E '@[a-z_]+\.(get\|post\|…)'`;`contract/endpoints.py:83` 起 261 个 `A("GET"/"POST"…)` |
| 实体 / 表 | 契约 **106** 个实体;库里 **107** 张表(含 alembic_version)、316 个索引、192 个外键、79 条 CHECK | `contract/entities.py:77` 起 106 个 `E(`;`information_schema` |
| 迁移 | **72** 个,单一 head `2cd9c9bf1587`,与库一致;11-06 → 11-12 七天新增 **12** 个,11-12 一天 3 个 | `ls migrations/versions \| wc -l`;`SELECT version_num FROM alembic_version` |
| 前端 | `app.js` **9 260** 行 + `wf_canvas.js` 1 085 + `wf_graph.js` 411 + `app.css` 529 + `index.html` 23;**无框架、无构建** | `wc -l apps/web/*` |
| 测试 | e2e 58 份 py(**1 975** 条 `ck(`)+ 14 份 js(392 条);编排零 IO 63 份(**1 463** 条);集成真 PG 12 份(241 条)—— 合计约 **4 070** 条断言 | `grep -c 'ck('` |
| 检查脚本 | `tools/*_check.py` **20** 个 + `page_render_check.js` + `shell_lint.py` / `sql_lint.py` | `ls tools` |
| 库体积 | **433 MB**;`run_events` 187k 行 / 75 MB、`job_events` 186k / 68 MB、`run_steps` 94k / 53 MB、`spans` 40k / 28 MB | `pg_total_relation_size` |
| 运行记录 | `execution_runs` 11 865 条(demo_a 11 347 / lanxiu 473);**122 条「running」+ 50 条「queued」背后什么都没活着**(见 §6.4) | 见 §6.4 的 SQL |
| 常驻 | launchd `com.lanxiu.aimc` 跑 `tools/dev.sh`(uvicorn **--reload** + 一个 Worker);日志 `/tmp/lanxiu-aimc.log` **49 MB 无轮转** | `~/Library/LaunchAgents/com.lanxiu.aimc.plist`、`tools/dev.sh:55`、`ls -la /tmp/lanxiu-aimc.log` |

---

## 1. 定位与边界

### 1.1 两个台各管什么 —— 已核实

交割文档 `../澜绣云裳agent-两个台的功能交割.md:11-27` 一句话分工:**工作台(:8770 agentsite,数据在 :8760 backend 的 SQLite)给不写代码的人完成业务;管理后台(:8801,PG)给调 AI 的人改系统行为**。判据三条(`:37-54`):① 改某一个客户的结果 → 应用层;② 改系统以后对所有人的行为 → 控制面;③ 看某个改动的效果 → 跟着改动走。

> 注意用户说的「主后台 8760」在仓库里叫 `backend/`(SQLite 57 张表 + 38 页业务后台,`../CLAUDE.md` §2),聊天站是 `agentsite/` :8770;两者共用 `backend/lanxiu.db`。管理后台 :8801 是独立 PG 库 `aimc_dev`。

管理后台实际管的(按路由表 `apps/web/app.js:9176-9244` 的 60 条 hash 路由 + `main.py:209-242` 的 34 个 router):Prompt / 术语 / 实体识别 / 查询路由 / 意图 四套「草稿→版本」配置;工作流(画布、运行、版本、定时、访问入口、聊天接管);Agent 配置;工具与能力(目录、版本、副作用分级、工具组、筛选策略);知识库(上传、切片、索引、召回测试);评测中心 / 实验对比 / 数据集 / 训练 / 模型产物;运行记录 / 调用链 / 用量 / 监测 / 告警;人工待办、产出监督、意见受理、问题单、能力档案、改进看板;成员权限、审计、设置。

### 1.2 交割划分被代码遵守了吗 —— 大体遵守,有一处登记在案的越界

- **搬完判据成立** —— 已核实 `../agentsite/nav.py:68`:`已移交管理后台 = {}` 为空;六页已删(`nav.py:78-92` 的「删掉的」)。
- **不反查澜绣库** —— 已核实:`grep lanxiu.db|sqlite3` 在 `services/ workers/ tools/` 只命中一处注释(`workflows_api.py:2839`),没有代码读 SQLite。两台之间**全部走 HTTP**:
  - 8760 → 8801:录音转写完自动发起工作流,经 `takeover_client`(`../backend/server.py:3340-3372`);三个 launchd 服务都配 `LANXIU_USAGE_URL=http://127.0.0.1:8801`(plist)。
  - 8770 → 8801:意见 / 意见样本复核 / 转人工 / 检索试跑(`grep /api/v1/projects agentsite/*.py`,6 条路径)。
  - 同步程序 `../tools/supervise_sync.py:1-20`:推产出、拉打回、拉桥单执行后回执,每 30 秒一轮(`com.lanxiu.supervise.plist`)。
  - 写入澜绣的真正拦截点在应用层:`docs/口径/工具不可逆口径.json:80` 自己写明「后台只决定怎么登记,真正拦住执行的是 agentsite/sdk.py 的 Hook 和 backend/fsm.py」。**这是对的分工**(执行权在数据那一边),但意味着「后台登记了要确认」和「执行时真拦了」是两条链,靠 `tools/lanxiu_tool_sync_check.py`(文件头说明五种红法)对账。
- **一处越界,已登记而未迁** —— 已核实 `services/api/app/workflows_api.py:2837-2843` 的 `别处的开关`:「技能放行」在澜绣后台「系统 → Skill 管理」,「工具停用 / 超时 / 限流」在澜绣后台「系统 → MCP 服务与工具」。按判据②(停用一个工具改变所有人的行为)这两样都该在控制面;现在 8801 只「摆出来写明在哪」。根因:用户 10-23 在 8760 拍了「MCP 服务与工具管理 做,带配置」(`../backend/mcp_registry.py:2`),比交割(09-27)晚,所以是**后来的拍板把开关放回了应用层**。10-28 三个经营分析技能两天没挂上(`workflows_api.py:2829` 注释)正是这个分裂的代价。

### 1.3 概念重叠清单

| 概念 | :8760 / :8770 | :8801 | 判断 |
|---|---|---|---|
| 工作流 | `agent/v2.py` 写死的 V2 编排(三代对比的一代) | 可视化工作流引擎 + 6 条业务流程重搭 + 聊天接管 | **刻意并存**(`../CLAUDE.md` §3 三代同仓是核心叙事);V2 是对照组不是产品 —— 已核实 |
| 评测 | `agent/` 57 份 `*eval*.py`(V1/V2/V3 的工单评测、判分器、夜跑) | 评测中心 + `eval_dispatch.py`(对工作流版本派子运行、只打「跑通」分) | 对象不同(前者评聊天 agent,后者评工作流版本)但**同一个词**;交割表「评测集与评测运行 → 控制面」只覆盖了后者 —— 推测前者作为开发工具留在仓库根是合理的,但 UI 上「评测中心」看不到它们 |
| 任务 | 业务任务(派任务 / 排班 / 回访) | `jobs` 表 = 后台异步任务 | **纯撞名**,代码里没混(8801 的 `jobs` 只有 prompt_run / workflow_run / index_build / agent_run 四类,`workers/worker.py:168,459,1091,1388`) |
| 工具管理 | 「系统 → MCP 服务与工具」开关;「Skill 管理」 | 工具目录 / 版本 / 副作用分级 / 工具组 / 筛选策略 / 不可逆口径 | **真重叠**,见 1.2 |
| 经营报告 | agentsite `/report` 页(生成、存档、确认) | 「经营报告」工作流(店长核对、最多重写 3 次) | 页面在应用层、流程在控制面,符合判据③;8760 发起、8801 执行 —— 已核实 `server.py:3340+` 的模式 |
| 定时 | launchd `nightly-eval` / `worldshift`(开发用) | `workflow_schedules`(业务定时,只跑生产版) | 不重叠 |

---

## 2. 架构

### 2.1 分层 —— 契约驱动做得好,但「API 文件」层已经长成巨石

- **契约层**(`services/api/app/contract/`):实体 / 状态机 / 权限矩阵(6 角色 × 能力,`perms.py:26-33`)/ 错误结构 / 接口登记 / DSL 节点表 / 落点表,`models.py`(676 行)和 `docs/契约.md`、`openapi.json`、`api.ts` 都从它派生 —— 已核实,README「一份数据只有一处表示」确实落地。
- **API 层**:36 个 `*_api.py` 各自一个 `APIRouter`,`main.py:209-242` 挂载。问题:`main.py`(890 行)自己还内联了 workbench / prompts / prompt-runs / jobs 共 12 条路由(`main.py:277-799`);`workflows_api.py` **2 922 行、34 条路由**,受理 / 发布 / 冻结 / 定时 / 开关监督 / 运行详情全在一个文件;`knowledge_api.py` 2 081 行。
- **服务层不存在独立目录**:业务规则散在 `*_api.py` 和 `runtime/` 之间;`issue_flow.py` / `capability_flow.py` / `improvement_flow.py`(85 / 63 / 51 行)是三张**声明式状态表**(状态、流转、动作要的字段),这个形状很好;重复只有 `sql_枚举()` 三份、`能做的动作()` 两份(已核实)—— 代价小,不急。
- **执行层**:`runtime/` 24 个模块。`runner.py:209 跑一张图` 是一个**串行解释器**(按节点类型 if 链分派,`runner.py:309-905`);Worker 把 `llm / retrieve / tool / document / agent` 适配器注进去(`workers/worker.py:460 _跑一张工作流`)。`workers/worker.py` 2 110 行,四个 handler 和所有适配器都在一个文件里。

### 2.2 执行模型 —— 已核实

| 项 | 现状 | 证据 |
|---|---|---|
| 队列 | 自建 Outbox(同事务)+ `jobs` 表 `FOR UPDATE SKIP LOCKED`;没有 Redis | `jobs/lease.py:122 取一个`、`jobs/outbox.py`;README 偏离表 |
| 进程模型 | **单进程、单线程、轮询**:`while True` → 每 60 s 扫定时 / 告警 / 评测收取 → 发件箱 → 过期核对 → `跑一轮()` → `sleep(0.05 … 5 s)` | `workers/worker.py:2063-2106` |
| 并发 | `WORKER_CONCURRENCY` 写在 `.env.example` 里,**代码里没人读**;支持 `--type` 起多个进程 | `grep WORKER_CONCURRENCY workers/` 无命中;`worker.py:2035` |
| 租约 / 心跳 | 租约 60 s、心跳 15 s、心跳超 4 倍算卡住并捞回;租约丢了立刻停手(`LEASE_LOST`) | `lease.py:44-45,315`;`worker.py:1887` |
| 重试 | 按错误码判该不该重试,默认 `max_attempts=3`,指数退避 + 抖动(上限 300 s);TIMEOUT 走「待人工核实」不自动重试 | `lease.py:52-119,292` |
| 幂等 | `POST /prompt-runs` 要 `Idempotency-Key`,同键不同配置 409;运行有 `idempotency_key` 列;工具网关「先登记 intent 再调外部」 | `main.py:613-689`;`runtime/tool_gateway.py:16-34` |
| 乐观锁 | 工作流 / 草稿 / 版本标记都要 `If-Match`,缺了 409 | `workflows_api.py:923-948,1550-1569,1942` |
| 模型超时 | 真模型走 **curl**(本机 TLS 拦截,见记忆),`--max-time` 60 s(生成)/ 120 s(Agent 回合),硬编码 | `runtime/真模型.py:94,143,223` |
| **节点级超时 / 重试** | DSL 给每个「调用外部」节点登记了 `timeout_seconds / retryable_errors / max_retries`(`contract/dsl.py` 多处),校验器只查「不该填的地方别填」(`runtime/validator.py:355`);**`runner.py`、`worker.py`、`compiler.py` 一处都不读这三个字段** | `grep timeout_seconds services workers` 只命中 dsl / validator / tools_api(存库)/ agents_api(存库)—— **声明了、没接上** |
| **工具级超时** | `tool_versions.timeout_seconds` 存着(`tools_api.py:156,533`),Worker 里没有任何 `timeout` 字样 | `grep -n 'timeout\|超时' workers/worker.py` 仅 1 条注释 |
| exec_mode | `runtime/执行模式.py` 三条路(选了 mock / 真跑且连接齐 / 抛 `不能跑`),**不静默降级**;受理时冻结 `execution_mode`,Worker 模式不符拒跑 `RUN_MODE_MISMATCH`;`/api/healthz` 报 `模型是mock` | `执行模式.py:1-80`;`worker.py:565-568`;`tests/e2e/_模型模式.py` |
| 人工等待 | 挂起释放租约,靠事件恢复;到期自动「已过期」 | `dsl.py` human 说明;`worker.py:340 _挂起`、`1980 扫过期核对` |
| 运行控制 | pause / resume / cancel / reconcile / 单步安全重试 五个接口都在 | `runctl.py:114-291` |

**推测**:HTTP 请求节点设计稿 `docs/规格/工作流补节点_HTTP与代码执行_设计稿.md:64` 写「节点登记成『调用外部』,超时 / 重试三件套自动生效」—— 以现状看**这个前提不成立**,做 HTTP 节点之前要先把三件套接到执行器上。

### 2.3 认证与安全面

- `AUTH_MODE=dev` 唯一实现;身份来自请求头 `X-Dev-User`,`oidc` 返回 501(`deps.py:57-65`);前端写死 U001–U005(`app.js:44-48`)。生产启动拒绝 dev 身份(README §主规格第 3 步,未实跑验证 —— 推测)。
- 绑定 `127.0.0.1:8801`(`tools/dev.sh:55`),没有 CORS / TrustedHost 中间件(grep 无)—— 本机形态下可接受。
- 访问 API(对外密钥):只存 sha256 查找哈希、每分钟限流、日额度、有效期 ≤ 1 年、轮换缩旧钥 24 h(`open_api.py:46,255-268,330`)—— 做得比内部身份完整。
- 密钥只收 `secret_ref`(`env:// / keychain://`,`secretref.py`),流程变量里出现 `secret` 来源当场拒(`SECRET_IN_FLOW`)。
- 工具网关六道闸「注册 → 服务端绑定 → Schema → 范围 → 确认 → 幂等」(`tool_gateway.py:16-34`),批准绑定参数摘要;桥写入闸只认 human 节点的输出(`runtime/桥闸.py`)。

---

## 3. 前端

### 3.1 形态 —— 已核实

- **单文件、无框架、无构建、无模块系统**:`app.js` 9 260 行,254 个顶层函数,其中 62 个 `页_*`;路由是 60 条 `if (h === …)` 链(`app.js:9176-9244`);70 个模块级 `let/const` 全局状态(`我 / 项目 / 能力 / 图态 / agent态 / 聊态 / 召回态 …`,`app.js:49-63,2539,5216,7410,8951`)。
- 渲染方式:**392 处 `innerHTML`**(模板字串拼 HTML)+ **236 处 `.onclick =`**,`addEventListener` 只有 3 处,`createElement` 7 处。转义纪律好:`esc()` 调用 999 次,`md()` 只放行 `**` 和反引号(`app.js:13-16`)。
- 最大函数 `画工具详情` 459 行、`表_设置` 296 行、`页_术语详情` 249 行(awk 统计)。
- `app.css` 529 行、6 个 CSS 变量、无暗色模式、唯一 `@media` 是 1180px 折栏;`index.html` `viewport width=1280` —— **桌面专用**。
- 类型:`packages/contracts/api.ts` 从 OpenAPI 生成,但前端是 JS,**没人消费它**(推测,未见 import)。

### 3.2 拼 class 的问题 / css_class_check 守什么

- 守的事(`tools/css_class_check.py:1-27`):页面写的每个字面 class 必须在 `app.css` 里有定义(10-07 发现 47 处 `tag`/`crit` 徽章一直无样式);**动态拼接的 class 追不到,计入「说不清」并钉住上限 29**(`:162`,10-25 从 19 → 28 → 29 逐次写了理由)。
- **现状红,已核实**(本次实跑 `python3 -I tools/css_class_check.py` → `❌ 拼出来的 class 有 31 处,超过钉住的 29 处`,退出码 1)。31 处全列出来了,新增的两处形状是 `state ${坏 ? "err" : ""}`,在 `app.js:6093 / 8051 / 8404`(11-12 新加的问题单 / 能力档案 / 改进看板页)。
- **它遮住了什么**:`Makefile:1047`(`test-orchestration` 目标第 36 行)在 63 份编排测试(第 53 行起)**之前**跑,make 遇错即停 → 整组零 IO 编排测试在本地链里从 11-12 起没被真跑过;根 `HANDOFF.md:101,110,119,158` 四处都记了「存量红」。
- **修法两种,都 10 分钟**:① 把三处改成字面(`坏 ? "state err" : "state"`),上限不动;② 上限 29 → 31 并在注释写清为什么(两处是三元式、结果位字面量都查得到)。推荐 ①,和检查文件头「不留两套名字」的精神一致。

### 3.3 可访问性 / 国际化

- 做了的:48 处 `aria-*`/`role=`、179 个 `<label`、画布 `focus-visible` 样式与键盘操作(`app.css:169,244,264,284,303`;README「拖拽不是唯一操作方法」)、生产环境文字标签不只靠颜色、`native_dialog_check.py` 盯原生弹框(`alert/confirm/prompt` 现仅 3 处)。
- 没做的:`tabindex` 只 1 处、`onkeydown` 4 处 → 列表 / 表格操作基本鼠标专用(推测);**没有 i18n 层**,全站 zh-CN,代码标识符也是中文 —— 对这个项目是刻意选择,不算债。

### 3.4 维护成本评估

- **优点**:零依赖、零构建,改完刷新即见;esc 纪律 + 页面冒烟(DOM 桩真跑加载路径,`tests/e2e/page_smoke.js`、`_页面桩.js`)+ 14 份 JS 行为测试(392 条)+ `page_render_check.js` 兜着;每处偏离都写了为什么。
- **成本**:① 一个 9 260 行文件,任何编辑器 / 代码评审 / `git blame` 都吃力;② 状态色映射有四份(`_核色 / _产出状态色 / _上传状态色 / 色`,`app.js:6685,6781,7065,8985`)—— 正是 css_class_check 追不到的那一类,同一个「待处理 → warn」规则漂了会无人察觉;③ 全局可变状态 70 个,换页靠 `换页序` 丢弃过期响应(`app.js:63`),再加页就更难推理;④ 规格默认是 React + TS + AntD,README 已登记偏离并说「API 已是契约边界,换前端只需重写 apps/web/」—— 这句话随 app.js 每长 1 000 行就更不真。
- **结论**:不建议现在换框架(用户没拍、投入大、收益看不见);建议**不换技术栈的拆分**(§7 第 8 条)。

---

## 4. 测试

### 4.1 规模与形状 —— 已核实

- 不是 pytest,全是自制 `ck(名, 真, 补)` + 退出码(`tests/e2e/test_api_flow.py:19-22`),每份文件一个进程、顺序执行、挂了贴全输出(`Makefile:439-470`)。
- e2e 58 份 py(1 975 条)+ 14 份 js(392 条);编排 63 份(1 463 条,零 IO、夹具驱动);集成 12 份(241 条,真 PG,try/finally + atexit 清理)。
- 主路径覆盖:接口闭环 + 禁止行为 44 组(跨项目 / 权限 / 乐观锁 / 幂等 / 脱敏 / 未知费用)、6 条业务流程各一份 e2e(audio / store_report / order_risk / recall / restock / rating_repair)、工作流编辑器(保存闸、图逻辑、新节点面板、foreach 面板、真浏览器 T01–T21)、Agent 三份(bridge / step / approval)、发布链、访问 API、评测派发、告警、监测、知识链(上传 / 切片 / 索引 / 召回)。
- `docs/实现进度.md`(生成):已覆盖接口 100 / 124、已实现未覆盖 17、未实现 7 —— 它自己声明只答「实现存在 / 请求覆盖」两层,行为验证那层测不出来(`实现进度.md:18-31`)。

### 4.2 门禁怎么挂

- `make contract`(不要库):spec_coverage、test_registry_check、orchestration_registry_check、total_not_truncated_check、switch_registry_check、nav_smoke_check、seed_flag_check、fk_dep_check(`Makefile:21-45`)。
- `make test-orchestration`:css_class_check **先于** 63 份编排测试(`Makefile:1047` 起)。
- `make test`:要真 PG **且要服务在跑**(`seed_rerun_check` 只挂这儿,`HANDOFF.md:250-252`)。
- `make test-e2e-ci`:`E2E_CI` 名单(`Makefile:416-430`,含 `test_agent_step_flow.py`,所以 `管理后台/HANDOFF.md:6` 的「未挂 Makefile」**已过期**)+ `E2E_CI_JS` + `page-smoke`;排掉两份要真调 Claude 精排的和一份要 Firefox 窗口的(`Makefile:473-478`)。
- CI(`../.github/workflows/check.yml:151-520`):`admin` job 只跑不要库的;`admin-e2e` job 起 `pgvector/pgvector:pg17` 服务容器 → `alembic upgrade head` + `alembic check` → 七个 seed → `nohup worker` + `uvicorn` → `make test-e2e-ci`。

### 4.3 本地 vs CI 差异,以及它们造成过的红

| 差异 | 本地 | CI | 曾经的红 / 现在怎么防 |
|---|---|---|---|
| 模型模式 | `MODEL_ADAPTER=anthropic`(plist,10-24 用户拍) | mock | 几条按 mock 写的断言本地必红 → `tests/e2e/_模型模式.py` 真模型模式下标 ⏸ 不算通过,CI 不许跳 |
| 库 | 常驻 `aimc_dev`,11 865 条运行、26k jobs 残留 | 空库 + seed | 「洁净度闸被 209 条残留卡住,`make test` 从 10-02 跑不动」(`HANDOFF.md:124-151`);`test_index_build / test_retrieval` 因 89 条 bge 向量拒跑(`HANDOFF.md:51-52`) |
| 写工具口径 | 本地 Worker 不重导 | `seed_bridge_tools.py` 每次导 | **新加写工具两边都没列 → 拒导 → CI 红**(11-12 提交 `7e1ef04a` 修排班两个写工具;`import_lanxiu_tools.py:46-49`、`lanxiu_tool_sync_check.py` 文件头「会写的工具没在口径里也要红」) |
| Worker 是否常驻 | 常驻 Worker 可能抢走 `--一轮` 的任务 | 单一 Worker | `test_api_flow.py:44-70` 改成「等这一条到终态」而不是「跑一轮就断言」 |
| 退出码 | 管道吞退出码栽过十二次 | 同 | Makefile 里 `rc=` 收退出码(`Makefile:439-470` 注释) |

**推测**:下一次同类红最可能出在「本地库里碰巧有什么」—— 122 条孤儿 running(§6.4)如果哪天进了某条判据的分母,就是又一次「红的理由和任何人做的事无关」。

---

## 5. 工作流引擎

### 5.1 节点清单 —— 已核实 `contract/dsl.py:100-330`

| 状态 | 节点(21 个登记) |
|---|---|
| 已实现(19) | start、llm、retrieve(知识检索)、tool、condition(多条件 and/or)、transform(白名单字段转换)、merge(分支汇合 = Dify 变量聚合器)、loop(有界循环,10-27)、foreach(列表迭代,11-12,**串行**)、human、agent、classifier(问题分类器)、answer(直接回复)、extractor(参数提取器)、assigner(变量赋值,**只能放在循环里**,`dsl.py:289`)、template(模板转换,**只替换无 Jinja 逻辑**)、list_operator(列表操作)、doc_extractor(文档提取器,只收 md / txt)、end |
| 登记未实现(2) | **parallel 并行与汇总**(`dsl.py:182-191`,校验器拦)、**subworkflow 子工作流**(`dsl.py:320-330`) |
| 没登记、画布置灰(2) | **HTTP 请求**(`apps/web/wf_canvas.js:169`)、**代码执行**(`:163`);定时触发器挪到画布「还没做」(`:172`) |

和 Dify 的其余差距(对照 `../澜绣云裳agent-工作流照Dify适配分析.md` §5):Webhook / 集成触发器(用户拍二期 / 不做)、DSL 导入导出(拍暂不做)、迭代并行开关(归 parallel)、会话变量(等对话流那一期)、实时协作(拍不做)。**用户 10-27 拍的 9 件**(`:174-183`)里,已核实落地的:循环 ≤3 次(loop)、条件分支合并(condition 多条件)、分类器、自动保存(`app.js:4502 _自存时`)、导航照 Dify(`app.js:9180 旧地址跳`)、聊天助手配置页(`chat_assistants_api.py`,店长助手试点 11-02);「在聊天站里直接核对」「Claude 判相似(标注)」「五种应用类型」未逐项核(推测部分未做)。

### 5.2 四项待拍 + 安全设计稿 11 条 —— 评估与推荐

设计稿 `docs/规格/工作流补节点_HTTP与代码执行_设计稿.md`(11-12,未实现)。逐条:

| # | 设计稿推荐 | 我的判断 | 理由 / 补充条件 |
|---|---|---|---|
| H1 地址 | A 只能选已登记的工具连接 | **同意 A** | 复用 `tools_api.py` 「允许的端点」白名单,不另立;B 的域名白名单会在第一个「同域不同路径」需求上被打穿 |
| H2 重定向 | A 不跟 | **同意 A**,但「三条最低线」(解析后 IP 段拦截 / 每跳重查 / 用检查过的 IP 发)必须作为**结构**落进边界审计并配真攻击 | 本机走 curl(`真模型.py` 同款),curl 默认不跟随 3xx,正好 |
| H3 密钥 | A 挂在工具连接上,`secretref` 发送时加头 | **同意 A** | 和模型连接同一套,`secret` 来源进流程已被 `SECRET_IN_FLOW` 拒 |
| H4 超时 / 大小 / 重试 | 15 s / 1 MB / 只重试 GET | **数值同意;前提不成立** —— 节点级 `timeout_seconds / max_retries` 现在**执行器不读**(§2.2)。要先把三件套接上,否则 HTTP 节点只能靠 curl `--max-time` 硬编码 | 已核实 grep |
| H5 谁能加 | A 能编辑的都能加 | **同意 A** | 把关在「登记连接」(需「配置密钥与预算」权限) |
| H6 写操作 | A 一期只 GET | **同意 A** | 写要走桥 / 人工核对那条已有的路 |
| C6 前置 | 先盘现有流程有没有非写代码不可的一步 | **强烈同意,先做这一条** | 6 条流程「6 条暂没用」(适配分析 `:100`);transform / template / list_operator 三类白名单节点刚铺完,覆盖面还没量过 |
| C1 沙箱 | A 容器(生产)+ B wasm(开发) | **若 C6 结论是「要」,首版选 B(wasm)而非容器** | 部署形态是单台 Mac、Docker 守护进程没跑(README 偏离表);为一个节点引入常驻容器运行时是一笔运维成本和新的单点。B 的「只能用标准库子集」在「换算 / 正则抽取」这类需求上够用;等真有第三方包需求再上 A |
| C2 边界 | 全关、JSON 进出 | **同意**,输出走现有 `runtime/结构化输出.py` 校验 | |
| C3 配额 | 5 s / 128 MB / 1 MB / 4 并发 | **同意**;补一条「每次运行累计 CPU 秒上限」,防循环里 100 项 × 5 s | foreach `技术上限 = 100`(`列表迭代.py:38`) |
| C4 语言 | 只 Python | **同意** | |
| C5 谁能加 | B 都能写,发布前管理员审核代码 | **同意 B**,审核落在现有「生产要审核」那一步(`approver` 角色已在 `perms.py:31`) | 画布上「只有管理员能加」那句是随手写的(`wf_canvas.js:163`),要改 |

**四项顺序建议**(不改「复刻 Dify」方向,只排序,见 §7 第 11 条):HTTP(GET-only)→ 并行与汇总(先做语义:独立状态命名空间 + 等全部必需支路,`max_concurrency=1` 串行实现,把「并发」留给以后)→ 子工作流(只引冻结版、静态禁递归 + 动态深度上限)→ 代码执行(C6 之后)。

---

## 6. 运维

### 6.1 部署形态 —— 单机,三套服务共享

已核实:一台 Mac(Darwin 25.6、Python 3.14.6、PG 17 本机常驻、pgvector 0.8.6),7 个 launchd 任务:`aimc`(:8801)、`backend`(:8760)、`agentsite`(:8770)、`supervise`(同步)、`health`(哨兵)、`nightly-eval`、`worldshift`。`launchctl list` 显示 `com.lanxiu.aimc` 上次退出码 **-9**(被 SIGKILL,推测是健康哨 `tools/health_watch.py` 或人手重启)。

### 6.2 常驻服务跑的是开发脚本 —— 已核实

`com.lanxiu.aimc.plist` → `tools/dev.sh`:
- `uvicorn main:app --reload`(`dev.sh:55`)—— **文件监视热重载跑在常驻服务上**:任何会话保存一个 `.py` 都会让 API 重启、断掉在途请求和 SSE;而 Worker 不重载(记忆:改 `runtime/` 要重启 aimc)。两个进程的代码版本可以不一致。
- 启动先 `pkill -f "workers/worker.py"`(`dev.sh:30`)—— 杀的是**这台机器上所有**叫这个名字的进程,包括并行会话 / CI 本地复现起的 Worker。
- Worker 日志 `/tmp/aimc-worker.log`(重定向,`dev.sh:33`);API 日志 `/tmp/lanxiu-aimc.log` **49 MB、无轮转**(launchd `StandardOutPath`)。

### 6.3 日志 / 监控 / 告警

- **日志**:API 和 Worker 都是 `print()`(worker 17 处,`sys.stdout.reconfigure(line_buffering=True)` 钉行缓冲,`worker.py:2058`),没有 `logging` 模块、没有结构化字段(run_id / job_id)、没有级别;uvicorn 访问日志 INFO 全量进同一个文件。「日志采集配置待拍板」—— 我的推荐见 §7 第 5 条。
- **监控**:`monitoring_api.py` 口径清楚(办成 = 跑完 + 每处写入拿到澜绣回执;业务 / 调试分开;未知不补零;小样本线 20,用户 11-05 拍)。
- **告警**:`alert_rules.py` 纯函数「连续 N 次越线才报、M 次正常才恢复、去重周期」(用户 11-04 拍),Worker 每 60 s 扫(`worker.py:2068-2073`),落成**站内待办**(`alerts_api.py`);**没有外发渠道**(飞书 / 邮件 / webhook,grep 无)—— 夜里越线没人知道(推测)。
- **健康**:`com.lanxiu.health` 每 60 s 探「答得出来吗」,11-02 文件描述符漏光那次 KeepAlive 没救到(plist 注释)。

### 6.4 数据面的三个「长得一样」—— 已核实(只 SELECT)

1. **孤儿运行**:`execution_runs` 里 122 条 `running`(最早 10-24)+ 50 条 `queued`,全在 `project_demo_a`。逐一排除后:**122 条 running 没有一条背后有未终态的 job、pending 的 human_request 或待执行的 bridge_call**;它们的 job 全是「已完成」(362 行关联,因一次运行可多 job)。50 条 queued **根本没有 job**(11-05 起,推测是评测派发 / 访问 API 建的子运行没入队)。`tools/stale_sweep.py --钉住 0` 只数「可推终态」那一档,「只报警」档不计(`stale_sweep.py:204-208`)—— 这 172 条在哪一档要查,但至少「状态 = running 而没人在跑」是监测页「在跑」分子里的假数。
2. **库只增不减**:事件 / 步骤 / span 四张表合计 224 MB,占库一半;`TRACE_RETENTION_DAYS` 留空(`.env.example`),`projects.retention_policy` 列存在,**没有任何清理任务读它**(grep `retention` 只命中 `spec_coverage.py`)。
3. **没有备份**:`管理后台/` 下没有 `pg_dump`、`备份` 字样(grep 无);`backend/lanxiu.db` 那边有 `.backup` 习惯,PG 这边没有。

### 6.5 局部失败样本

`jobs` 失败 76 条:`NO_MODEL_CONNECTION` 60、`TRANSIENT` 14、`INCOMPATIBLE` 1、`RUN_MODE_MISMATCH` 1 —— 失败码分布说明「没选连接就试运行」是最常见的人为错,前端可以在受理前拦(推测,未核前端是否已拦)。

---

## 7. 优化方向清单(按「对线上影响 × 改动代价」排序)

> 「触碰拍板」一栏:✅ = 不碰任何用户拍过的决定;⚠️ = 改法会碰到某条拍板,要先问。

| # | 方向 | 现状(证据) | 建议 | 工作量 | 触碰拍板 |
|---|---|---|---|---|---|
| 1 | **修 css_class_check 存量红,解封 63 份编排测试** | 实跑 31 > 29,退出码 1;`Makefile:1047` 排在编排测试之前,红了整组不跑;根 `HANDOFF.md:101/110/119/158` 四处记「存量红」 | 把 `app.js:6093 / 8051 / 8404` 的 `state ${坏 ? "err" : ""}` 改成字面(`坏 ? "state err" : "state"`),上限不动;或上限 29→31 写理由 | 10 分钟 | ✅ |
| 2 | **把节点级 / 工具级超时与重试接到执行器上** | DSL 登记 `timeout_seconds / retryable_errors / max_retries`,`tool_versions.timeout_seconds` 存库,但 `runner.py / worker.py / compiler.py` 一处不读(grep);模型超时硬编码 60 / 120 s(`真模型.py:143,223`) | 在 `runner.py` 调 `适配器[t]` 处包一层:读节点配置的超时传给适配器(curl `--max-time`),按 `retryable_errors` × `max_retries` 走 `lease.退避秒`;加编排测试「超时配置真被用了」(真调入口,不只纯函数) | 中(1–2 天 + 咬合) | ✅(而且是 HTTP 节点 H4 的前提) |
| 3 | **清掉并防住孤儿 running / queued 运行** | 122 条 running 背后无活物,50 条 queued 无 job,全是 demo_a(§6.4 SQL);监测「在跑」会被它们污染 | Worker 加一档「job 终态而 run 非终态 → run 记 `incomplete / completion_reason=orphaned`」,`stale_sweep` 新增该档并钉住 0;e2e 收尾断言「本份建的 run 都到终态」 | 小–中 | ✅ |
| 4 | **常驻服务不再跑开发脚本** | `dev.sh:55 --reload`、`:30 pkill -f workers/worker.py` 跑在 launchd 常驻任务上(`com.lanxiu.aimc.plist`);Worker 不热重载 | 新建 `tools/serve.sh`:无 `--reload`、不 pkill、Worker 作为独立 launchd 任务(`com.lanxiu.aimc-worker`,KeepAlive)或 supervisor 子进程;`dev.sh` 留给 `make dev`。重启要在锁里、先看门禁 | 小(半天) | ⚠️ 用户 10-23 拍「设成常驻」—— 不改决定,改实现;装 plist 要用户自己跑(记忆:持久化会被拦) |
| 5 | **日志、留存、备份三件一起定**(「日志采集配置待拍板」的推荐) | 49 MB 无轮转;print-only 无 run_id;四张事件表 224 MB 无清理;无 pg_dump | ① launchd 日志改到 `管理后台/var/log/`,`newsyslog.d` 按 50 MB × 7 份轮转;② Worker / API 统一 `logging` JSON 行,字段至少 `ts level run_id job_id event`;③ 定 `TRACE_RETENTION_DAYS`(推荐 90,demo 项目 30)并加每日清理 job(删 `run_events / job_events / spans` 到终态 N 天以上的,审计表不删);④ 每日 `pg_dump -Fc` 到项目外目录保留 14 份。全部**先拍 保留天数和备份去处** | 中 | ⚠️ 留存天数要用户拍(生产标准,记忆「澜绣云裳是真实落地项目」) |
| 6 | **工具开关归位控制面** | 「工具停用 / 超时 / 限流」「技能放行」在 8760,8801 只登记「别处的开关」(`workflows_api.py:2837-2843`);按交割判据②应在控制面;10-28 三个技能两天没挂上 | 短期:加一条对账检查「8760 停用的工具在 8801 工具目录上标出来」(照 `takeover_effect_check` 的形状);中期:开关迁 8801,8760 启动时拉一份并缓存 | 短期小 / 中期中 | ⚠️ 用户 10-23 在 8760 拍「MCP 服务与工具管理 做,带配置」—— 迁移要重新拍 |
| 7 | **拆巨石:`workflows_api.py` 2 922 行、`worker.py` 2 110 行、`main.py` 内联路由** | 单文件承载受理 / 发布 / 定时 / 开关 / 运行详情;Worker 四 handler + 全部适配器一文件 | 按已有边界拆:`workflows/{受理,发布,定时,开关,运行详情}.py`;`workers/handlers/{prompt_run,workflow_run,index_build,agent_run}.py` + `runtime/adapters/`;`main.py` 的 prompt / jobs 路由迁 `prompts_api.py`。纯搬动,用 `bite_replay_touched` 按文件集重放 | 中–大(2–3 天) | ✅ |
| 8 | **前端不换栈的拆分** | 9 260 行单文件、if 链路由 60 条、4 份状态色映射、392 innerHTML、236 `.onclick=` | ① `<script type="module">` 按页拆成 `pages/*.js`(62 个 `页_*` 天然边界),`app.js` 只留路由表(数据化为数组)和公共件;② 状态色映射收成一份 `状态色.js`,并提供 `cls(基, 修饰)` helper 让 css_class_check 能追(把「说不清」压回个位数);③ 把 `人们` 写死名单改从 `/api/v1/projects` 身份接口来(为 OIDC 铺路) | 中(拆文件 1–2 天;映射收口半天) | ✅(规格默认 React 的偏离已登记,不碰) |
| 9 | **单 Worker 单线程 → 按类型拆进程** | 定时 / 告警 / 评测收取 / 四类任务同一循环;一次 120 s 的 Agent 回合阻塞全部;`WORKER_CONCURRENCY` 无人读 | 第一步零代码:起两个 Worker 进程 `--type workflow_run` / 其余(已支持 `--type`,`worker.py:2037`),定时与告警只在一个里跑;第二步再考虑线程池 | 小(运维)/ 中(线程池) | ✅ |
| 10 | **认证上线化** | `AUTH_MODE=dev` 唯一实现,`X-Dev-User` 请求头;OIDC 501(`deps.py:57-62`);SSE 带不了头(README「下一步」第 5 条) | 身份挪到 HttpOnly cookie(同时解 SSE),接 OIDC 或先接澜绣账号(97e34436ff06 迁移已做「后台账号与澜绣员工一对一绑定」);访问 API 那套哈希 + 限流可复用 | 大 | ⚠️ 生产标准问题,要用户定「上线前是否必须」 |
| 11 | **Dify 四项的排序** | parallel / subworkflow 登记未实现;HTTP / code 未登记;设计稿 11 条待拍 | HTTP(GET-only,H1–H6 照推荐)→ parallel(语义先、串行实现)→ subworkflow → code(先 C6 盘点;要做则 wasm 首版);每项都先过 `algorithm-selection` 式选型卡 | 各 中 | ⚠️ 不改「复刻 Dify」(10-26),只排序;C1 推荐与设计稿不同(wasm 优先),要用户拍 |
| 12 | **过期文档瘦身** | README 写 87 操作 / 50 接口 / 40 路径 / 六页(`README.md:22,30,120,124`),实际 261 / 60 路由 / 62 页;`管理后台/HANDOFF.md` 258 KB 自 10-10 停更,头部「未挂 Makefile」也已过期 | README 数字改由 `gen_contract_doc.py` 生成或纳入 `doc_numbers_check`;HANDOFF 缩成一行指向根 | 小 | ✅ |
| 13 | **告警外发一条渠道** | 告警只落站内待办,无外发 | 复用 `../tools/feishu_publish.py` 的凭证,规则「触发中」时发一条到飞书(去重周期已有) | 小 | ⚠️ 发到哪个群要用户定 |
| 14 | **三份 flow 的小重复** | `sql_枚举` ×3、`能做的动作` ×2 | 抽 `contract/flowbase.py` | 极小 | ✅ |
| 15 | **两条 README 明写的库欠账核一下** | memberships「同一人只一条组织级记录」要部分唯一索引、graph_drafts「只挂 workflow 或 agent 之一」要 CHECK(README「下一步」第 6 条);迁移里只见 `uq_memberships_org_proj_user`(`51331b3d286a:234`) | 推测仍欠;写一条 SELECT 对账 + 两个小迁移 | 小 | ✅(建表要走锁和重启) |

### 排序说明

1–3 是「现在就在影响线上或影响判断,而改动一天内」:1 遮着整组测试;2 让所有外部调用没有可配的超时(HTTP 节点的前提);3 让监测页的「在跑」是假数。4–6 是运维与边界的结构性问题,改动小但要重启 / 要拍板。7–9 是维护成本,不急但越晚越贵。10 是上线门槛。11 是方向内的排序。12–15 顺手。

---

## 8. 这次体检没覆盖的

- 没跑任何测试,所以「测试现在绿不绿」只有间接证据(根 HANDOFF 11-12 多处记录编排链除 css_class 外全过)。
- 没核 `runtime/validator.py`(1 029 行)的支配关系分析是否完整,只核了它对 timeout 字段的处理。
- `knowledge/` 子系统(2 081 行 API + 11 个模块)只看了结构,没评估检索质量与权限过滤的实现。
- 用户 10-27 拍的 9 件里「聊天站直接核对」「标注回复 Claude 判相似」「五种应用类型」没逐项核落地状态。
