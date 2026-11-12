# 澜绣云裳 agent · backend 深度体检(只读)

> 范围:`backend/` 核心代码(server.py / api.py / fsm.py / tasks.py / ops.py / booking.py / roster*.py / db_build.py / seed.py / domains.py / auth.py / 各 *_write.py)+ 前端 `backend/web/index.html`,以及 `backend/lanxiu.db` 的结构(只用 SELECT / PRAGMA 读)。
> 日期:2026-11-12。全程未改任何文件、未起停服务、未跑 check.sh / bite_run / 评测。
> 每条结论标「**已核实**(file:line)」或「**推测**」。行号以当前工作区文件为准。

---

## 0. 一页摘要

| 维度 | 一句话判断 |
|---|---|
| 架构形状 | 两个巨型模块(server.py 4569 行 / api.py 8579 行)+ 约 90 个中小模块。**模块边界其实比表面好**:写口 / 口径 / 闸已经拆成独立文件,api.py 和 server.py 只是「路由 + 装配 + 一堆取数函数」堆在一起。真正的病不是「文件大」,是**路由层手写 168 个 if 分支、每个分支各自决定要不要取身份**。 |
| 数据层 | **133 张表**(不是文档说的 57),SQLite,`journal_mode=delete`、外键未启用、45 条显式索引。**「单写者」并不成立**:8760 后台、8770 站、8 个 MCP 子进程、aimc worker、launchd 平移脚本至少 5 类进程同时写一个库文件。无迁移框架,22 处 `ALTER TABLE` 散在 17 个模块里,重建靠 50 步 `rebuild.sh`。 |
| 安全边界 | 工具层(模型那条路)守得很硬:只读连接、truth / 凭据运行时拦、WRITE_TOOLS 登记、fsm 闸 fail-closed、身份 contextvar。**管理后台 HTTP 写口这条路明显弱于工具层**:`do_POST` 里至少 14 个写接口不取身份或从请求体读 role,`/api/toggle` 还把表名从请求体拼进 SQL。 |
| 前端 | 单文件 323KB / 4163 行,一个 `<script>`,110 个函数、50 条路由、无框架无构建。有 7 道前端检查护着,但 `innerHTML` 87 处 + 约 140 处未 `esc()` 的插值,维护全靠纪律。 |
| 性能 | `HTTPServer` 单线程;每条查询开一条新连接;列表页基本是「整表 SELECT * → Python 过滤 → 分页」;建档 / 改档每次拉全表 8087 位客户做查重。现在的量(2.6 万单 / 8 千客户)扛得住,**翻 10 倍就不行**。 |
| 可维护性 | 加一个写工具要动 7–9 处(函数 + SCHEMAS + WRITE_TOOLS + domains + prompts 规矩 + isolation/write_smoke 等检查 + bite_specs + 工具模型说明)。重复最多的是 `DB` 路径(49 处)、`_now`(16 处)、`rows/_rows`(17 处)、`建表`(15 处)。 |

---

## 1. 架构形状

### 1.1 规模(已核实)

| 文件 | 行数 | 顶层 def | 备注 |
|---|---|---|---|
| `backend/api.py` | 8579 | 192 | 工具层:105 个挂给模型的工具 schema(SCHEMAS 5 + SHOP_SCHEMAS 89 + KB_SCHEMAS 11,`api.py:310 / 6922 / 8520`),WRITE_TOOLS 32 个(`api.py:678-719`) |
| `backend/server.py` | 4569 | 132 | 标准库 `http.server`,`do_GET` 从 3502 到 4075(约 570 行)、`do_POST` 从 4076 到 4563(约 490 行);`if p==...` 式路由 168 处 |
| `backend/ops.py` | 1792 | — | 研判队列 / 销账 / SLA |
| `backend/seed.py` | 4155 | — | 68 张表的 DDL + 造数 |
| `backend/boundary_audit.py` | 2183 | — | 边界审计(攻击代码) |
| `backend/web/index.html` | 4163 | 110 个 JS 函数 | 323KB,单 `<script>` |
| backend 非检查模块 | 91 个文件 / 42,263 行 | | |
| backend `*_check.py` | 160 个文件 / 32,532 行 | | 检查代码 ≈ 业务代码的 77% |

> 任务描述里说「约 210 个工具」—— 以 schema 计是 **105 个**;192 个 def 里一半是内部辅助。推测 210 可能把 `_说明.拼进三份` 之前的旧统计或 V1/V2 的工具算进去了。

### 1.2 模块边界:比看起来好,但有两层「假边界」

**好的部分(已核实)**:
- 写口已经各自独立成文件,且只被 api.py / server.py 调用、不反向 import api/server:`tasks.py` / `ops.py` / `booking.py` / `roster_write.py` / `fitting_write.py` / `order_write.py` / `pickup_write.py` / `repair_write.py` / `refund_write.py` / `rating_write.py` / `merge.py` / `shop_key.py` 对 api/server 的 import 数全为 0(grep 结果)。**没有循环依赖**。
- 口径下沉到 `knowledge/`(lifecycle / rfm / growth / fitting / liability),server.py:11-14 只 import 不复制。
- 工具归属 `domains.py` 一处(`domains.py:21-78`),MCP 入口 `mcp/domain_server.py:20-24` 照它挑。

**假边界一:api.py 是「工具层」,但 server.py 把它当通用库用(已核实)**
`server.py:9 import api as backend`,然后页面接口直接调 `_api._rows(...)`(如 `server.py:3799-3807` 面料页、`3840` 着装人页),等于页面绕过 server 自己的 `rows()` 去走工具层的只读连接 —— 两套连接、两套 `DB` 变量(`api.DB` `server.DB`),检查脚本切副本时要两处都切(`check_copy.py` 的来由正是这个,`check_copy.py:1-9`)。

**假边界二:路由层自己决定「要不要取身份」(已核实,这是最大的结构风险)**
`do_POST` 没有统一的身份中间件:每个 `if p==` 分支各自写 `_me(self)` / `_role_of(self)` / 什么都不取。结果是三种写口并存:
1. 从会话取并拒绝匿名:`/api/transit`(4100-4102)、退款四口(4180-4181)、研判销账(4193-4195)等 —— 这类是对的。
2. 用 `_role_of(self)` 兜底成「顾问」:`/api/customer-create`(4490-4491)、`/api/customer-update/`(4492-4494)、`/api/appt-create`(4507-4508)、`/api/freight-save`(4488)、`/api/product-save`(4516-4517)、`/api/syscode-save`(4522)。**匿名请求以「顾问」身份执行**,其中 `create_customer` / `create_appointment` 顾问本来就允许 → **不登录可以建客户、建预约**(`server.py:2060-2064` role 默认顾问,`rules.validate_customer(d, ex, actor_role=role)`)。
3. 完全不取身份、actor 写死「魏欣新」:`/api/toggle`(4525-4526 → 1661)、`/api/task-note`(4543-4548)、`/api/task-close`(4549)、`/api/lifecycle-adjust`(4557)、`/api/block-save`(4518 → 2867)、`/api/content-save`(4524 → 3036)、`/api/download-create`(4514)、`/api/draft-status/`(4560)、`/api/scheme-transit`(4137-4140,调 `transit()` 不传 `me`)、`/api/followup-create`(4509)、`/api/ops-triage`(4141)、`/api/triage-run-worker`(4238)。
4. **role 从请求体读**:`/api/template-save` / `/api/template-del` / `/api/mitem-save`(4519-4521 `role=body.get("role") or "顾问"`)。前端确实把 `localStorage` 里的 `ROLE` 发上去(`index.html:1317, 2347, 2468`)。这正是 CLAUDE.md 第 6 节「角色只从服务端会话取」那条铁律的反例,而 `authgate_check.py` 只打 `/api/transit` 一条(`authgate_check.py:93-103`)。

> `安全边界审计.md:41` 自己也写明「只管这三个接口 —— 订单、预约等页面里带出的客户信息不在这一条里」;`待办清单.md:1590` 写着「写操作要登录、读不要 —— 为了不登录也能演示留的口子」。**但上面第 3、4 类是写操作**,不在那句话的保护范围内。

### 1.3 全局状态与 `DB` 模式

- **49 个模块各有一个 `DB = os.path.join(HERE,"lanxiu.db")`**(grep `^DB *= *os.path`)。`api.py:9`、`server.py:232`、`tasks.py:24`、`ops.py:19`、`auth.py:36`、`roster.py:53` … 每个检查要切副本就得逐个换,`check_copy.py:1-36` 用整整一页注释记录了这件事造成的两次真库污染(10-19 台账假行、11-03 丢 55 条评价)。
- `db=None; db or DB` 模式在 24 个非检查模块里出现(`report_doc.py` 9 处、`arrival_card.py` 6 处、`roster_write.py` 4 处 …)。`api.py` 里反而是 0 处 —— 它用 `_c()` 固定连 `api.DB`。两种风格并存,**而 `def f(db=DB)` 这种把路径烤进默认参数的写法(`roster.py:133, 150, 158, 164, 200, 230`)在切副本时根本改不到** —— `check_copy.py:12-24` 明确承认这个坑「在补之前是活的」。
- `ops.py:24 _本库 = DB`:模块载入时冻结真库路径,用于「只在本库上报判读」—— 是补丁式的全局状态。
- 身份用 `contextvars`(`api.py:642-668`),这个设计是对的;但 MCP 子进程靠环境变量 `LANXIU_ME`(`api.py:658`,`agentsite/sdk.py:337`)—— 环境变量不是 per-request 的,一个 MCP 进程服务多轮对话时身份是否会串,**推测**:sdk 每次 `run` 起新进程时注入所以不会串,但如果进程被复用则会。
- `auth._SESS` 进程内字典 + `.auth_sessions.json` 落盘(`auth.py:38, 76-105`)。两个端口(8760/8770)共用同一份文件(`index.html:582` 「两个端口共用一份登录」);文件写入靠 `_LOCK` 线程锁,**跨进程没有锁**,两个进程同时登录可能互相覆盖对方刚写的会话(**推测**,`_写盘` 是读-改-写整文件,`auth.py:84-105`)。

### 1.4 重复代码(已核实,grep 计数,非检查模块)

| 重复物 | 份数 | 代表位置 |
|---|---|---|
| `DB = os.path.join(...)` | 49 | 见上 |
| `def _now()` | 16 | `server.py:222` 用机器时钟,`ops.py:152`、`booking.py:84` 各一份;worldclock 文档(`worldclock.py:1-30`)说明哪些该用世界钟 |
| `def rows()` / `def _rows()` | 9 + 8 | `server.py:235`、`api.py:66`、`tasks.py:43`、`ops.py:148`、`booking.py:25`、`auth.py:54` |
| `def _c()` | 7 | |
| `def 建表(c)` | 15 | 每个功能模块自己 `CREATE TABLE IF NOT EXISTS`,见第 2 节 |
| 函数内延迟 import | api.py 198 处、server.py 129 处 | 多数是为了避免模块级循环或启动开销,副作用是依赖关系从文件头看不出来 |
| 顾问名填充 | `server.填顾问名` 一处,但 `_simple` / `order_list` / `customer_list` 各自调 | 这是收敛后的样子,算正面 |

---

## 2. 数据层

### 2.1 事实(已核实,`sqlite3` 只读)

- 表 **133**(`SELECT count(*) FROM sqlite_master WHERE type='table'`),文档说 57(`CLAUDE.md:60`)/ 52(`系统架构与技术文档.md:163`)—— 文档落后一倍以上。
- `PRAGMA journal_mode` = **delete**;`PRAGMA foreign_keys` = 0;`seed.py` 里 `REFERENCES` 出现 0 次 → **没有任何外键约束,全靠应用层与检查脚本对账**。
- 显式索引 45 条(含 3 条唯一:`ux_refund_no` / `ux_escalation_open` / `ux_triage_run_active`)。热表索引覆盖:`customer` 只有主键 + `ix_cust_adv_cov`(**`phone` 无索引**,而 `booking.book` 按 `phone=?` 查,`booking.py:124`);`appointment` 只有主键;`op_log` **零索引**(5085 行,`_日志片` 用 `actor IN (...) OR actor LIKE ?`,`server.py:190-192`);`schedule` 只有 `ix_sched_busy`。
- 行数:ordr 25,955 / ordr_item 28,742 / appointment 14,270 / wearer 12,341 / customer 8,087 / account 8,065 / op_log 5,085 / truth 90 / staff 39 / shop 3。库文件 91.6MB。
- **`truth` 表(评测答案)和生产业务表在同一个库文件里**(90 行)。工具层拦得住(`api.py:21, 68-71`),但管理后台 `server.rows()` 不拦、`sqlite3` 直连不拦。

### 2.2 「单写者」不成立(已核实)

同时持有写连接的进程:
1. 8760 `server.py`(单线程,`server.py:4569 HTTPServer`)+ 它内部的转写工人线程(`server.py:3256 threading.Thread`)。
2. 8770 `agentsite/app.py`(`ThreadingHTTPServer`,`app.py:1312`),直接 import `api`/`ops`(`app.py:548, 1228`),`session_state.py:34`、`capman.py:40`、`claims.py:373`、`internal_call.py:27` 都直连 `backend/lanxiu.db`。
3. 每轮对话拉起的 8 个 MCP 子进程(`agentsite/sdk.py:387`),写工具在子进程里直接 `sqlite3.connect(DB)` 写库(`tasks.py` 9 处 connect)。
4. launchd:`com.lanxiu.aimc`(管理后台 worker)、`com.lanxiu.worldshift`(每日平移,整表 UPDATE)、`com.lanxiu.nightly-eval`、`com.lanxiu.health`。
5. 并行开发会话跑的检查 / backfill 脚本(`tools/backfill_*.py` 十余个)。

在 `journal_mode=delete` 下写事务持有整库锁,读也要等;python `sqlite3` 默认 `timeout=5s`。项目自己已经撞过:`tools/touchpoint_history_seed.py:73-78` 记录「登录、页面、同步循环在这期间全报 database is locked」,并写明「**不切 WAL —— 那是对库文件的永久改动,没评估过,用户没批**」。只有 `tasks.py:319` 一处用 `BEGIN IMMEDIATE`,`pending_actions.py:72` 一处设了 `isolation_level=None, timeout=10`。

**判断**:现状对单店、十来个并发用户够用;多门店、后台 worker 常驻、夜跑和白天业务重叠时,`database is locked` 会成为常态错误,而且它在页面上表现为「保存失败 / 载入错」,不会被任何门禁抓到。

### 2.3 schema 演进:无迁移框架,靠「重建 + 散落的 ALTER」

- DDL 真相分裂:`seed.py` 68 张 `CREATE TABLE`;另外 **30 个模块各自 `CREATE TABLE IF NOT EXISTS`**(`factory_inbox.py` 7 张、`opportunity_store.py` 6 张、`kb_issue.py` 3 张 …,共约 65 张)。
- 22 处 `ALTER TABLE` 分布在 17 个模块(`arrival_card.py` / `asr.py` / `merge.py` / `ops.py` / `refund_write.py` / `report_doc.py` …),模式是「函数入口先 `PRAGMA table_info` 看列在不在,不在就加」(如 `ops.py:755 _确保等顾客列`、`ops.py:1126 _确保后加的列`、`ops.py:1437 _确保重开列`、`asr.py:176, 188`)。`seed.py:26-33` 的注释自己承认「schema 的真相分裂成两处 … seed 一重跑工号列就没了」。
- 重建链 `tools/rebuild.sh:224-243` **50 步**,顺序敏感(注释写明「场合标签必须排在造旅程之前」),每步一个脚本;`db_build.py` 给库盖「造数指纹」章(`db_build.py:217`)并进门禁核对范围。
- `tools/shift_world.py` 每日把全库日期平移一天(`worldclock.py:1-30`、launchd `com.lanxiu.worldshift`)。`worldclock.今天()` 读的是 `seed.TODAY`,而 `seed.TODAY` 在 **import 时**从 `world_meta` 读一次(`seed.py:793-803`)—— **推测**:长驻进程(8760/8770)在平移之后不重启,看到的「世界今天」仍是旧值,直到重启。

**生产落地判断**:

| 事项 | 结论 |
|---|---|
| 真实客户数据进来后还能 `rebuild.sh`? | **不能**。重建 = 删库重造,50 步里几乎全是造假数据。上线那天起,「改知识 md 重跑 derive」「改 seed 改列」这两条日常工作流都要换形态:需要一条**只动结构不动数据**的迁移路径。这是最大的硬伤。 |
| 世界时钟 / 每日平移 | 上线必须关掉 launchd `worldshift`,并把 `worldclock.今天()` 切回真实日期。目前「哪些列用世界钟」是靠 `worldclock_check` 盯的,切换本身没有开关(**推测**,未见 `LANXIU_REAL_CLOCK` 之类的环境变量)。 |
| 备份恢复 | 仓库里 `库备份/` 只有 4 个手工 `.db` 快照(09-29 ~ 10-03),没有定时备份脚本(grep `backup` 在 tools/*.sh、tools/*.py 为空)。`journal_mode=delete` 下在线 `.backup` 可做,但没人做。**硬伤**:无 RPO 承诺。 |
| 留存合规 | 有 `consent` 表、账户「注销中 / 已注销」状态与 `purge_at` 字段(`api.py:4759-4802`),有对外脱敏包装(`api.py:8518 _masked`)、HttpOnly cookie、PBKDF2+盐、登录锁定(`auth.py:41-42, 107-139`)。**缺**:真实删除 / 匿名化流程、留存期策略、`op_log` 里自由文本带 PII(`server.py:70-73` 自述研判根因整句含姓名生日地址)。够做试点,不够过审。 |
| 多门店并发 | 见 2.2;另外门店范围靠 `shop_key.门店条件` 按码筛(`api.py:40-55`),已把「改店名就筛成 0 行」这一类修掉,方向对。 |
| 够用的部分 | SQLite 本身对这个量级完全够;确定性种子 + 50 步重建对**开发 / 评测**是优势;唯一索引守幂等(退款流水号)是正确用法。 |

---

## 3. 安全边界:结构守的 vs 约定守的

### 3.1 结构守住的(已核实)

| 保证 | 位置 | 评价 |
|---|---|---|
| 工具层连接只读 | `api.py:32-33 _c()` `mode=ro` | 硬 |
| truth 表任何语句形状都拦 | `api.py:21, 68-71` 运行时正则 `\btruth\b` | 硬;但只拦 `_rows`,`_rows2`(`api.py:2934-2936`)绕过列名黑名单——它只取裸元组、不查 truth。**推测**:`_rows2` 当前调用方都是写死的 SQL,未被滥用,但它是一个未登记的旁路 |
| 凭据列按**返回列名**拦 | `api.py:72-77` | 硬,写法无关 |
| 对外手机号脱敏包装 | `api.py:8518` 原地改写 TOOLS | 硬,且注释解释了为什么不能重新绑定 |
| 写工具不收身份参数、身份从 contextvar / env 取 | `api.py:642-668, 3392-3395 _need_me` | 硬;`isolation_check` 逐个验签名 |
| WRITE_TOOLS 登记 | `api.py:678-719`(32 个) | 结构 + 检查;漏登的历史(`set_piece_ratio`、`report_production`)说明「登记」本身靠人 |
| fsm 闸 fail-closed | `fsm.py:170-216`:MUSLIN / ORDER / FACTORY / ROLLBACK / FIT / COMPLETE / REPAIR / REPAIR_FIT 八道闸,ctx 没带结论一律拒 | 硬;`server.transit` 从库现算 ctx(`server.py:505-533`),不信请求体 |
| 退款:角色从会话覆盖请求体、金额只认库、流水号唯一索引 | `server.py:451-470`,`fsm.py:228-240`,`ux_refund_no` | 硬 |
| 任务可见范围 | `tasks.visible_scope`(`tasks.py:49`),`get_task` 单条也走范围(`api.py:2939-2950`) | 硬,isolation_check 三类漏法都测 |
| 模型碰不到 Bash/Write/Edit | `disallowed_tools` + PreToolUse hook(agentsite,文档 `CLAUDE.md:239`) | 硬 |
| 读接口登录闸(点名清单) | `server.py:60-83 要登录的读`,`3515-3516` | 结构,但**点名不是默认**:新加读接口忘了登记就是公开 |

### 3.2 只靠约定 / 检查守的(已核实)

| 保证 | 现状 | 证据 |
|---|---|---|
| 管理后台写口要登录 | **不成立**(第 1.2 节第 3、4 类共 14+ 个接口) | `server.py:4137-4140, 4141, 4238, 4509, 4514, 4518-4526, 4543-4562` |
| 后台写口角色只从会话取 | 3 个接口从请求体读 role | `server.py:4519-4521` |
| `/api/toggle` 的表名 / 键名 | **从请求体拼进 SQL**(`f"SELECT {col} s FROM {table} WHERE {key}=?"`,`f"UPDATE {table} SET {col}=? WHERE {key}=?"`),无白名单、无登录 | `server.py:1661-1673, 4525-4526`。可对任意表任意行翻 `status` 列;配合 `key` 可注入 SQL 片段(**推测**:未实测注入,但字符串拼接是事实) |
| 审计 actor 真实性 | 匿名写口 actor 默认「魏欣新」(真实员工名),CLAUDE.md 自述 09-20 已在 `/api/transit` 修过,其余口子仍如此 | `server.py:446, 607, 618, 1661, 1897, 2060, 2867, 3036` 默认参数 |
| 写工具动手前先确认 | 只有提示词 TL16 | `安全边界审计.md:124`;`agentsite` 的确认卡只在「开着卡库」时生效(`安全边界审计.md:84`) |
| 智能体侧角色由调用方说了算 | env 注入 | `安全边界审计.md:121` |
| get_customer 没身份时不限店 | 约定 | `安全边界审计.md:120` |
| `/api/book` 匿名预约 | 有意为之,三道闸(格式 / 3 张上限 / 不收 advisor),但**按手机号枚举老客**:返回「这个手机号还不是我们的客户」 vs 可约,等于一个客户存在性探测器 | `booking.py:97-131`,返回码 `NO_CUSTOMER` |
| `/api/ops-triage`、`/api/triage-run-worker` 内部接口 | 无鉴权,靠「只绑 127.0.0.1」 | `server.py:4141, 4238`,`server.py:4569` 绑 127.0.0.1 |
| 读接口点名清单 | 列表外的读接口(订单、预约、售后列表)带客户姓名仍可匿名读? —— 不对,`要登录的读` 已含 `/api/orders /api/appts /api/aftersales`;但 `/api/customers`(列表)、`/api/products`、`/api/activities` 等不在清单 | `server.py:60-79`;`customer_list` 已遮手机号(`server.py:3149`)并 `pop("phone")`(3157),所以姓名 + 生命周期 + 消费额匿名可读(**已核实**路径未在清单) |

### 3.3 绕过路径汇总

1. **匿名建档 / 建预约 / 建跟进**:`POST /api/customer-create` 等,role 兜底「顾问」→ 通过 `rules.validate_customer`(server.py:2060-2071)。
2. **匿名翻任意表状态**:`POST /api/toggle {"table":"staff","key":"no","val":"600000xx"}` 把员工停用 / 启用(`toggle` 默认 `col="status"`,`on="启用"`,`staff.status` 恰好用「启用」;`auth.login` 看 `status != 启用` 拒登,`auth.py:118`)。**推测**后果:可以匿名踢任何员工下线;`TOGGLE_GUARD` 只对 `measure_item` 有守卫(`server.py:1658`)。
3. **自报店长改量体模板 / 量体项**:`/api/template-save` 带 `role:"店长"`(`server.py:4519-4521`),`save_template` 只看这个 role(`2908-2922`)。
4. **匿名改方案状态**:`/api/scheme-transit` → `transit("fe-scheme", ...)` 不传 me,ctx 来自请求体(`4137-4140`)。
5. **匿名伪造研判结果 / 领走研判任务**:`/api/ops-triage`、`/api/triage-run-worker`(`4141, 4238`),写进 `triage` 表,会进看板和评测回流。
6. **管理后台不经 `api._rows` 读 truth**:`server.rows()` 无拦截(`server.py:235-238`)—— 现有代码没这么写,但结构不禁止。
7. `_rows2` 旁路(`api.py:2934`)不过 truth / 凭据两道锁。

> 这些都在**本机 127.0.0.1** 上。今天不是公网问题;但「真实落地 = 多门店多终端访问」的那一刻就是。

---

## 4. 前端 `backend/web/index.html`

### 4.1 规模与组织(已核实)

- 323,120 字节 / 4163 行;`<style>` 1 段(1-429 行),`<script>` 1 段(430-4163)。无外部库、无构建、无模块。
- 导航 `MENU` 10 个一级 / 36 个二级(`index.html:447-461`);`route()` 50 条路由(`index.html:591-642`);`TAB_TITLE` 43 个标题(`549-558`)。
- 110 个函数;最大的 `custDetail` 233 行、`productDetail` 178 行、`factoryPage` 140 行(awk 统计)。
- 全局可变状态 15 个 `let/var`:`W / CUR / 载入序号 / 上次要载入 / 载入超时毫秒 / CAL_M / CT / TABS / ACTIVE / SEEN / ROLE / DEMO_TODAY / DT / CAL / MCP_F / SK_F / KI_F / ME`(`index.html:435, 510-511, 757, 1277-1325, 2718, 2778, 2860, 4107`)。
- 页面间通信靠全局 + `location.hash`(`index.html:567`);标签页 `TABS` 自己管。
- 请求封装 `get()`(`513-534`)和 `post()`(`540-546`)写得不错:序号防乱序、超时、五类失败分开、401/403 单独抛。

### 4.2 维护成本与脆弱点

| 脆弱点 | 证据 | 评价 |
|---|---|---|
| 一个 `<script>`,任何语法错整页死 | CLAUDE.md:366-369「`let FILTER` 声明两次 → 一行都不执行」 | 已用 `agentsite/js_check.py`(真解析)+ `js_smoke.js` + `page_load_check.mjs` 兜住;当前无重复顶层声明(grep `uniq -d` 为空) |
| `innerHTML` 87 处;`esc()` 952 次,但模板里**约 140 处直接 `${x.field}` 不经 esc** | `index.html:693-694 ${s.cust} ${s.deposit}`、`967 ${t.id}`、`1001 ${c.idle_days}` 等 | 多数是数字 / 内部编号,风险低;但「哪些字段能不 esc」没有规则,是 XSS 的长期暴露面(**推测**:现有数据无恶意内容;真实客户姓名 / 备注进来后才会碰到) |
| 前端角色 `ROLE` 存 localStorage 并发给后端 | `1317-1319, 2347, 2468, 3168-3179` | 和后端 4519-4521 一起构成第 3 节漏洞;对 `/api/merge` `/api/approval-decide` 后端已改为会话优先,这里只是多余字段 |
| 路由是 50 行 if 链,新页面要改 MENU + TAB_TITLE + CRUMB_ROUTE + route 四处 | `447-461, 471-481, 549-558, 591-642` | `fetch_route_check.py` 盯前后端路径一致,漏一处会被抓 |
| 没有组件抽象,表格 / 筛选 / 分页在每个 `*List()` 里手写 | `listPage` 有一点复用 | 新列表页约 60-100 行复制粘贴 |
| 前端的「工作台默认魏欣新」 | `index.html:660` `(ME&&ME.name||"魏欣新")` | 和后端默认 actor 同一个假人,未登录时页面看着像已登录 |

**结论**:对一个单人维护的内部后台,这个形态**可以活**,因为 7 道前端检查(`js_check` / `js_smoke` / `page_load_check` / `page_smoke_check` / `fetch_route_check` / `approval_card_check` / `model_sync_check`)把最致命的「整页不执行」「路由对不上」兜住了。代价是每加一页都是复制一段 100 行再改;超过 6000 行后建议拆文件(不必上框架)。

---

## 5. 性能 / 可靠性

| 项 | 事实 | 评价 |
|---|---|---|
| 并发模型 | `HTTPServer`(非 Threading)单线程(`server.py:4569`);8770 是 `ThreadingHTTPServer`(`app.py:1312`) | 任一慢请求阻塞全站。项目自己量过:`/api/wearers` 曾 90 秒(`server.py:3832-3835` 注释);`order_list` 曾 17 秒(`1057-1060`)。**已核实**都已修,但模型是「出事一次修一处」 |
| 连接 | `server.rows()` 每次调用 `_conn()` 新开连接并注册 2 个 SQL 函数(`server.py:19-39, 235-238`);`api._rows()` 每次 `_c()` 新开只读连接(`api.py:32-33, 66-78`);`_店片()` 为了算 WHERE 片段再开一条(`server.py:126-129`) | 一次 `order_list` ≈ 10+ 次 connect。SQLite 本地 connect 约 0.1-0.5ms,现在不痛;`create_function` 每次注册是额外开销 |
| 连接关闭 | `api._rows` 用 `with _c() as c`(**不关连接**,`api.py:72`),文件头 `api.py:6` 自己注释知道 `closing` 才关;server.py `with _conn() as c` 39 处 vs `closing(_conn())` 2 处 | 靠 CPython 引用计数回收,功能上没漏;Python 3.13 会刷 ResourceWarning |
| 列表页 | `_simple`:`SELECT * FROM {table}` 全表 → Python 过滤 / 排序 / 切页(`server.py:1823-1840`);`customer_list` 拉 8087 行 14 列再切(`3134-3157`);`order_list` 拉 26k 单 JOIN customer 再切(`1047-1055`);`facets` 每列一条 `DISTINCT` | O(N) 每次翻页。8k / 26k 行约几十毫秒,10 倍量级后每页 0.5-1s,单线程下会排队 |
| 写路径全表扫 | `create_customer` 为查重拉全表 `SELECT id,name,phone,shop,birthday,addr FROM customer`(`server.py:2065`);`update_customer` 同(`2226`);`rules.validate_customer(d, existing)` 在 Python 里比对 | 每次建档 O(N),且 `customer.phone` 无索引。`booking.book` `WHERE phone=?` 同样走全扫 |
| N+1 | awk 粗扫:server.py 循环内查询 25 处、api.py 11 处、tasks.py 6 处、ops.py 4 处。典型:`/api/fabrics` 45 种材质各 2 查(`server.py:3802-3807`);`order_list` 本页每单一次 `ordr_item`(`1061-1063`,已限本页) | 大多已限制在「本页」范围,属可接受;`/api/fabrics` 固定 90 次查询可合并 |
| 锁 | 见 2.2;只 1 处 `BEGIN IMMEDIATE` | 多写者 + delete 日志 + 默认 5s timeout → 「database is locked」 |
| 热点索引缺口 | `customer.phone`、`appointment.customer_id / start_ts`、`op_log.ts / actor`、`schedule.customer_id / assignee_no`(只有 `ix_sched_busy`) | 加索引是零风险改动 |
| 单点 | 会话文件、drafts.json(`server.py:233, 240-243` 整文件读写)、图片现画 SVG(`server.py:3592`)都是进程内 / 文件级 | 单机够用 |

---

## 6. 可维护性:加一个写工具要动几处

以 `shift_draft`(11-11 新加的排班写口)为样本反推(已核实):

1. 业务函数:`backend/roster_write.py`(新文件,311 行)。
2. 工具包装:`api.py:7849 def shift_draft(items)` + `_need_me`。
3. 登记 `WRITE_TOOLS`(`api.py:680`)。
4. schema 进 `SHOP_SCHEMAS`(`api.py:6922+`)并被 `工具模型说明.拼进三份` 补说明(`api.py:8578-8579`)。
5. 领域归属 `domains.py:62`。
6. 规矩进 `prompts.py`(P6 强制「挂了工具必有规矩」,CLAUDE.md:538-541)。
7. 后台页面同一份规则:`server.py:4106-4116` 路由 + `index.html rosterPage()`。
8. 检查:`roster_write_check.py`(192 行)、`roster_check.py`(183 行),挂进 `check.sh`,写 `tools/bite_specs.json` 咬合规格。
9. 边界审计条目(如果声称结构)`boundary_audit.py`。
10. 文档:PRD 附录、`intent/manager-roster.md`、HANDOFF。

**约 7-10 处、2 个新文件、300-500 行检查代码**。其中 2、3、4、5 是纯「登记」,漏一处的后果各不相同且都不报错(项目历史上 `set_piece_ratio`、`report_production` 都漏过 WRITE_TOOLS,`api.py:684-716` 注释)。

**能收敛的重复**:
- 登记四联(TOOLS 字典 / SCHEMAS / WRITE_TOOLS / domains)→ 一个装饰器 `@tool(domain="work", write=True, schema=...)` 自动填四处;`domains_check` / `isolation_check` 改为从装饰器元数据读。
- 路由层:`do_GET / do_POST` 的 168 个 if → 一张 `{路径: (handler, 需登录, 允许角色)}` 表,登录和角色判定在分发前统一做;`authgate_check` 自然覆盖全部路径而不是 1 条。
- 49 个 `DB` + 24 个 `db or DB` → 一个 `backend/dbpath.py` 提供 `当前库()`,`check_copy.用副本()` 只改一处。
- 16 个 `_now()` → 全部走 `worldclock.当下()` / 真实时钟二选一的显式函数。
- 15 个 `建表(c)` + 22 个 `ALTER` → 一个有序迁移目录 `backend/migrations/0001_*.sql`,`world_meta` 记 schema 版本。

---

## 7. 优化方向清单(按「对真实落地的影响 × 改动代价」排序)

> 「碰拍板」列:✅ 不碰 / ⚠️ 擦边(拍过相邻决定) / ❌ 直接碰(需用户再拍)。拍板依据:`CLAUDE.md` 第 2、6 节与 `业务决策/业务拍板-2026092{4,5,6,7}.md`、`待办清单.md:1586-1604`、`tools/touchpoint_history_seed.py:77`。

| # | 方向 | 现状(证据) | 风险 / 代价 | 建议做法 | 工作量 | 碰拍板 |
|---|---|---|---|---|---|---|
| 1 | **后台 HTTP 写口统一身份闸** | `do_POST` 14+ 个写接口匿名可用或 role 从请求体读(`server.py:4137-4140, 4141, 4238, 4509-4526, 4543-4562`);`/api/toggle` 表名入 SQL(`1661-1673`);`authgate_check` 只打 1 条(`authgate_check.py:93`) | 不登录可建档 / 建预约 / 停用员工 / 改量体模板 / 伪造研判。本机部署时是内网风险,多门店访问时是真实漏洞。审计 actor 记成「魏欣新」违背 CLAUDE.md 第 6 节 | ① `do_POST` 入口统一 `me=_me(self)`,默认拒绝,仅 `/api/book` 和两个内部口显式豁免并改为 token 校验;② 删掉 `role=body.get("role")` 三处,前端去掉 `role:ROLE`;③ `toggle` 加 `(table,key,col)` 白名单;④ `authgate_check` 遍历全部 POST 路径,豁免名单写进代码并要理由。咬合:改坏任一分支必须红 | 2-3 人日(含检查与前端清理) | ⚠️ 擦边:用户 10-23 拍的是「读接口要登录、点名不一刀切」(`待办清单.md:1596`),这里是写口,CLAUDE.md:240 已明文要求「身份从登录会话取」。建议告知即可 |
| 2 | **多写者并发:切 WAL + busy_timeout + BEGIN IMMEDIATE** | `journal_mode=delete`(PRAGMA 实测);≥5 类进程同时写(2.2 节);只 1 处 `BEGIN IMMEDIATE`(`tasks.py:319`);项目自己记录过「全报 database is locked」(`touchpoint_history_seed.py:73-78`) | 多门店 + 常驻 worker + 夜跑时锁冲突成常态;表现为页面「保存失败」,门禁抓不到 | ① 库上 `PRAGMA journal_mode=WAL`(一次性、可逆);② 所有写连接统一 `timeout=30` 并在写事务前 `BEGIN IMMEDIATE`;③ 共享库上的批处理脚本分批提交(已有先例)。注意 WAL 下 `.backup` 与软链路径(CLAUDE.md 5.5)行为要重验 | 1 人日 + 1 轮全量门禁 | ❌ **直接碰**:`touchpoint_history_seed.py:77` 明写「不切 WAL … 用户没批」。要先给用户一张「WAL 代价卡」(多出 `-wal/-shm` 两个文件、备份方式变化、网络盘不可用)再做 |
| 3 | **结构迁移路径(替代「删库重建」)** | 真相分裂:seed 68 表 + 30 模块各自建表 + 22 处散落 ALTER(2.3 节);`rebuild.sh` 50 步全是造数;真实数据进来后无法重建 | 上线后任何加列都只能靠「函数入口 PRAGMA 看列」的补丁式写法;出错不可回滚;两个检出共享库时迁移顺序无保证(CLAUDE.md 「澜绣建新表要连代码一起推」) | 建 `backend/migrations/NNNN_*.py|sql` 有序目录 + `world_meta.schema_ver`;`db_build.盖章` 顺带记版本;`rebuild.sh` 第一步改为「建空库 → 跑全部迁移 → 再造数」;现有 15 个 `建表()` 和 22 个 ALTER 收编成迁移 0001-0037,原函数保留为 no-op 过渡。加一条检查:代码里出现新 `CREATE TABLE / ALTER TABLE` 而迁移目录没有对应文件就红 | 4-6 人日(大半是把现有 DDL 搬家 + 咬合) | ✅ 不碰业务拍板;⚠️ 碰开发流程(CLAUDE.md 第 2 节「seed.py 确定性生成」要补一句) |
| 4 | **备份 / 恢复 + 留存基线** | 只有 4 个手工快照(`库备份/`),无定时备份;`truth` 表与业务表同库;`op_log` 自由文本含 PII(`server.py:70-73`);注销流程只有状态字段(`api.py:4759-4802`),无真实清除 | 没有 RPO;一次误跑 `rebuild.sh` 或 `cp -R` 软链事故(CLAUDE.md 5.5)就是全量丢失;合规审查第一问就是「数据怎么删、保留多久」 | ① launchd 每小时 `sqlite3 .backup` 到带日期目录 + 保留 N 天 + 校验能打开;② `truth` 迁到独立 `eval.db`(api 的 truth 锁保留,server.rows 不再有机会碰到);③ 定义留存策略:`op_log`/`edit_log`/`call_transcript` 保留期与匿名化脚本;`purge_at` 到期真清 | 2-3 人日 | ⚠️ 留存期限需要用户拍(「保留多久」是业务决定);备份本身 ✅ |
| 5 | **世界时钟上线开关** | `worldclock.今天()` 读 `seed.TODAY`(`worldclock.py:40-44`),`seed.TODAY` import 时读 `world_meta`(`seed.py:793-803`);launchd `worldshift` 每日平移全库 | 上线后忘关平移 = 每天把真实订单日期往后推一天,**且不会自愈**(`server.py:44-49` 注释原话);长驻进程推测看到的是旧「今天」 | 加 `LANXIU_WORLD=real|sim` 显式开关:real 时 `今天()` 返回真实日期、`shift_world.py` 拒跑、`worldclock_check` 改验「没有任何列再用世界钟」;启动脚本打印当前模式 | 1 人日 | ✅ |
| 6 | **DB 路径与连接单源化** | 49 处 `DB=`、24 模块 `db or DB`、`def f(db=DB)` 烤死默认参数(`roster.py:133-230`);`check_copy.py` 三步换路径 + 断言才能切副本 | 并行会话已两次污染真库(10-19、11-03);每个新模块都可能再漏一次 | `backend/dbpath.py`:`当前库()` 读一个进程级变量;所有模块 `DB` 改为属性或函数;`db_switchable_check` 棘轮推到 0 | 2 人日(机械改 + 全量门禁) | ✅ |
| 7 | **路由表化 + 工具登记装饰器** | 168 个 `if p==`;加一个工具要登记 4 处(第 6 节);历史漏登 2 次 | 每次新增都是「漏一处不报错」;`do_GET/do_POST` 各 500 行难审 | 路由表 `{path: (fn, auth, roles)}`;`@tool(domain, write, schema)` 装饰器生成 TOOLS/SCHEMAS/WRITE_TOOLS/domains;`domains_check`、`isolation_check`、`mcp_registry` 从元数据读 | 3-4 人日 | ✅(`domains.py` 「一处写」原则不变,只是换载体) |
| 8 | **列表 / 查重走 SQL,补热点索引** | `_simple`/`customer_list`/`order_list` 全表进 Python(`server.py:1823-1840, 3134-3157, 1047-1055`);`create_customer` 查重拉全表(`2065`);`customer.phone`、`op_log`、`appointment` 无索引 | 现在几十毫秒,量翻 10 倍后单线程排队;`/api/wearers` 90 秒事故是同一类 | 先加 6-8 条索引(零风险);`rules.validate_customer` 改成按 `phone`/`name` 预筛再比;列表页 `WHERE … LIMIT/OFFSET` + `COUNT(*)`,facets 缓存 60s | 2 人日 | ✅ |
| 9 | **8760 换 `ThreadingHTTPServer` 或前置反代** | `server.py:4569 HTTPServer` 单线程;8770 已是 Threading | 一个慢页拖全站;两个服务的会话文件无跨进程锁(`auth.py:84-105`) | 换 `ThreadingHTTPServer`(一行),同时把 `_SESS` 读写与 `.auth_sessions.json` 用 `fcntl` 文件锁;或干脆让 8770 反代 8760 只留一个对外口 | 0.5-1 人日 + 门禁 | ✅ |
| 10 | **前端拆文件 + 插值规则** | 单 `<script>` 4163 行;约 140 处未 esc 插值;`ROLE` localStorage | 可维护性线性变差;真实客户备注进来后 XSS 面才显形 | 按 MENU 一级拆 10 个 `.js`,server 静态目录现成(`static/`);规则「字段进 innerHTML 一律 esc,数字用 `num()`」并加一条正则检查(允许白名单);删 `lx_role` | 2-3 人日 | ✅(`js_check`/`js_smoke` 需适配多文件) |
| 11 | **匿名预约口的客户枚举** | `/api/book` 返回 `NO_CUSTOMER`(`booking.py:124-127`) | 可按手机号探测「谁是老客」 | 统一返回「已收到,顾问会联系您」+ 后台落「待认领」;或要短信验证码(需外部服务,成本另算) | 0.5 人日(改口径)/ 3 人日(验证码) | ⚠️ 「老客自助预约」是产品决定(`booking.py:97-109` 注释说明是用户要的敞口),改回复文案不碰,加验证码要拍 |
| 12 | **`_rows2` 旁路收编** | `api.py:2934-2936` 不过 truth/凭据锁 | 目前无害,但是一条未登记的结构缝 | 让它复用 `_rows` 的两道检查,只省列名转 dict;边界审计加一条攻击 | 0.5 人日 | ✅ |

**前 5 条合计约 10-14 人日**;其中 #1、#5、#6 不碰任何已拍板决定可直接排;#2 要用户拍 WAL;#3、#4 要和用户对「上线后数据怎么改、留多久」。

---

## 8. 附:检查体系在守什么(了解,不评测)

- `selftest.py`:truth 表隔离(运行时 + JOIN 绕过)。
- `authgate_check.py`:仅 `/api/transit` 的身份闸(HTTP 层)。
- `customer_read_auth_check.py`:客户读接口要登录、按门店。
- `isolation_check.py`:任务可见范围三类漏法(列表 / 单条 / 写),在库副本上跑。
- `write_check.py` / `write_smoke_check.py` / `writerule_check.py`:写接口往返、44 个 POST 真跑、`check_write` 覆盖每条规则。
- `fitting_write_check` / `pickup_write_check` / `repair_write_check` / `order_write_check` / `refund_write_check` / `roster_write_check`:各闸在副本上实测。
- `shop_key_check`:门店按码筛的棘轮。`domains_check`:工具归属唯一。`db_build.py --范围检查`:造数指纹。`check_copy.py`:副本切换三步断言。
- 前端:`js_check` / `js_smoke` / `page_load_check.mjs` / `page_smoke_check` / `fetch_route_check` / `approval_card_check.mjs` / `model_sync_check.mjs`。
- `check.sh` 当前 `run` 条目 403 条(文档里的 25 / 33 / 47 都已过期)。

这套体系的强项是「写口闸 + 工具层边界」,弱项正是本报告第 1 条:**管理后台路由层的身份闸只有 1 条检查在守**,而那一层恰恰是 14 个口子漏着的地方。
