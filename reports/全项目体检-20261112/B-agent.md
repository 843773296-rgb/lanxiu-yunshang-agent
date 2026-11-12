# 澜绣云裳agent · 智能体层只读体检(B-agent)

> 2026-11-12,只读。没有改文件、没有跑门禁 / 评测 / 模型、没有写库(只用 `sqlite3 -readonly` 查过 `skill_cfg`,以及 `import sdk` 读了一次技能放行状态)。
> 每条判断标「已核实(file:line)」或「推测」。行号以当天工作区为准。
> 数据来源:`prompts.py` / `agentsite/sdk.py` / `agentsite/guards.py` / `backend/api.py` / `backend/domains.py` / `mcp/` / `agent/v1.py` `v2.py` `gen_compare.py` / `.feynman/llm-trace.jsonl`(19,559 行)/ `.feynman/spans.jsonl`(41,928 行)/ `agentsite/evals/*.jsonl` / `agentsite/third_party_review.json` / `安全边界审计.md` / `HANDOFF.md`。

---

## 0. 一页结论

| 问题 | 结论 |
|---|---|
| 工具面 | 后端 105 个 schema / 114 个 TOOLS,全能助手挂 98、店长助手(task)79、顾问助手(kb)59、研判 7。**按需加载(ToolSearch)只开给全能助手**,实测把它每次调用的上下文从 ~19.3 万压到 ~6 万 token;而**最胖的两个入口 kb(13.9 万/次)和 task(16.5 万/次)没开**,它们是实际跑得最多的角色(spans 里 1.37 万 + 0.6 万次模型调用)。 |
| 提示词 | 102 条规矩(49 铁律 / 53 工具级),正文 4.45 万字;全能装 95 条 4.29 万字,店长 68 条 3.45 万字,顾问 61 条 2.69 万字,研判 12 条 2,945 字。重复极少(只 1 句),但有 3 处头部与工具面自相矛盾、约 10% 字数是写给人看的旁白(实测记录 / 拍板日期 / 评测说明),对模型是纯 token 浪费。 |
| Hook 与安全 | 6 个 Hook(不是 CLAUDE.md 说的 4 个)。双锁完整:`disallowed_tools` 18 个名字 + PreToolUse 前缀闸;ToolSearch 例外只对 `all`,且有 5 点真攻击守着。**缺口**:写闸的「一轮只写一次 / 同参数不重试」台账只记 5 个任务类写工具(32 个写工具里的 5 个);其余写工具在聊天页靠 11-11 的确认卡(结构)兜住,评测 / 其他路径上只靠提示词。 |
| Skill | 249 个目录:自有 11 + 第三方 238(其中 2 个改造版在「试运行」);放行 13。第三方审查 239 条:212 不适用 / 14 可借鉴 / 7 缺依赖 / 6 可适配。默认 `own` 集合下第三方对 token 零影响;代价在仓库(3.2 MB 正文)、门禁(依赖现算要读 249 份)和「all」模式的路由污染。放行的 13 个里 `pattern-draft`、`call-notes` 在最近 200 轮里 0 次触发。 |
| 三代 | 生产只用 V3。V1 的 `call()` 是全项目唯一发请求口(7 处业务调用 + V2 + 假数据工厂),**不能删**;V1 的 agent 循环还被管理后台 8760 研判草稿页子进程调用;V2 只在 `check.sh` 纯规则自测和三代对比里跑。维护代价已经压到很低,值得留,但要「冻结」而不是继续跟着加功能。 |
| 模型与成本 | 生产默认 `claude-haiku-5-5`(升级 `opus-5-5`);评测 / 夜跑钉死 `claude-haiku-4-5`;意图分类走 V1 默认也是 4-5。10-25 以来 4,972 轮 V3 里只有 44 轮跑过 5-5。**成本口径有一个 5 倍量级的坑**:Haiku 5.5 对 >10 万 token 的提示按 5 倍计价,而顾问 / 店长助手每次调用 13.9 万 / 16.5 万,`cost_of` 只按 ≤10 万那档算。 |

---

## 1. 工具面与按角色估算表

### 1.1 事实

- 后端工具:`backend/api.py` 三份 schema 共 **105 个**(SCHEMAS / SHOP_SCHEMAS / KB_SCHEMAS),`api.TOOLS` 114 个函数(9 个没有 schema,只内部用)。全部 schema JSON 共 **69,799 字符**,其中 description 36,139 字符。已核实(用 `import api` 现算;`backend/api.py:310,6922,8520`)。说明文本由 `backend/工具模型说明.py::拼进三份` 把「别名 / 适用不适用 / 任务示例」拼进 description(`api.py:8578-8579`),所以每个工具的说明比最初写的更长 —— 这是 10-03 业务拍的,对路由有用,但它是每次调用都带的。
- 写工具 **32 个**(`api.WRITE_TOOLS`,`backend/api.py:678-`),不是 CLAUDE.md 第 6 节写的 21 个(那是 09-22 的数;文档已过期)。已核实。
- 8 个领域 MCP 服务,一个入口 `mcp/domain_server.py <领域>`,工具归属只在 `backend/domains.py` 写一次;每轮只起用得到的领域(`sdk.py:368-377`)。手写 JSON-RPC(`mcp/protocol.py` 326 行),带停用 / 超时 / 限流 / 确认卡 / 遮蔽逻辑。已核实。
- 角色工具名单是字面量列表,`_ROLE_TOOLS` 按角色拼(`sdk.py:935-948`):

| 角色(kind) | 页面名 | 工具 | 其中写 | 规矩 | 提示词字数 | 按需加载 |
|---|---|---|---|---|---|---|
| all | 全能助手 | 98 | 29 | 95 | 42,870 | **开**(唯一) |
| task | 店长助手 / 后台运营(含聊天页「后台配置」版) | 79 | 29 | 68 | 34,524 | 关 |
| kb | 顾问助手 / 门店顾问 | 59 | 17 | 61 | 26,872 | 关 |
| pattern | 版师 | 17 | 4 | 16 | 6,822 | 关 |
| workshop | 工坊排产 | 9 | 1 | 16 | 3,110 | 关 |
| aftersale | 售后 | 9 | 2 | 11 | 5,789 | 关 |
| finance | 财务 | 7 | 1 | 9 | 2,570 | 关 |
| triage | 研判专用(`run("triage")`) | 7 | 0 | 12 | 2,945 | 关 |

已核实:工具数 / 写数由 `sdk.py` 字面量 + `api.WRITE_TOOLS` 现算;规矩数 / 字数由 `import sdk` 后读 `sdk.*_RULE_IDS` / `sdk._SYS` 现算(和 `triage_scope_check.py` 的算法一致)。注:HANDOFF 5292 行记「店长助手 v0:工具 74(写 26)」是 10-28 的数,现在 79 / 29 —— 10 月底到 11-12 又加了 5 个工具(排班 3、挽回跟进 1、录音上传 1)。

### 1.2 每次调用真的花了多少上下文(spans 实测,10-23 之后)

从 `.feynman/spans.jsonl` 的 `chat` span 取 `input + cache_read + cache_creation`,按角色统计单次模型调用的上下文:

| 角色 | 模型 | 调用次数 | 平均 token / 次 | 中位 | p90 |
|---|---|---|---|---|---|
| **kb** | haiku-4-5 | 13,764 | **139,084** | 138,383 | 142,682 |
| **task** | haiku-4-5 | 5,960 | **164,996** | 170,163 | 176,363 |
| all(开了 ToolSearch) | haiku-4-5 | 1,347 | 59,217 | 56,851 | 70,482 |
| all | haiku-5-5 | 264 | 70,367 | 61,501 | 82,488 |
| all | opus-5-5 | 45 | 85,052 | 84,562 | 124,288 |
| pattern | haiku-4-5 | 2,397 | 53,451 | 52,621 | 57,091 |
| workshop | haiku-4-5 | 683 | 38,969 | 38,735 | 40,668 |
| finance | haiku-4-5 | 340 | 33,842 | 33,365 | 34,765 |

已核实(spans 现算)。对照 HANDOFF 6868 行 10-23 实测:all 192,665 / kb 129,673 / task 164,757 ——
- **ToolSearch 把全能助手从 19.3 万压到 6 万左右(-69%)**,这是项目里最有效的一次省 token。
- kb 从 12.97 万涨到 13.9 万(+7%,10-23 之后又给顾问加了 get_member / 商品图 / 能力申请 / 录音上传),task 持平 16.5 万。**这两个入口现在是最胖的,而且是跑得最多的**(kb + task 占全部模型调用的 78%)。
- 与 Haiku 4.5 的 20 万窗口比,task 的 p90 已经 17.6 万 —— 多轮续聊时离压缩只差一两次工具返回(spans 里有 2 轮 `lanxiu.compacted`)。

### 1.3 token 构成的估算(推测,按 10-23 的量法:每个中文字约 1.67 token)

| 角色 | 工具 schema 字符 | 提示词字符 | 估算工具说明 token | 估算提示词 token | 底座(CLI 系统提示 + 技能列表 + 注入)约 |
|---|---|---|---|---|---|
| all | 65,104 | 42,870 | ~10.8 万(按需加载后**不进**) | ~7.2 万 | ~2.6 万 |
| task | 54,036 | 34,524 | ~9 万 | ~5.8 万 | ~2.6 万 |
| kb | 41,588 | 26,872 | ~6.9 万 | ~4.5 万 | ~2.6 万 |
| triage | 3,188 | 2,945 | ~0.5 万 | ~0.5 万 | ~2.6 万 |

和实测对得上:task 2.6 + 9 + 5.8 ≈ 17.4 万(实测 16.5 万);kb 2.6 + 6.9 + 4.5 ≈ 14 万(实测 13.9 万)。**结论:对 kb / task 两个入口,工具说明占 55–60%,规矩占 30%,底座 15%。** 把工具说明按需加载是最大的一刀,其次才是提示词瘦身。

### 1.4 CLAUDE.md 第 3 节记过的那件事,现在还在发生

「加一个工具的代价在此后每一次调用上」:09-16 26→59 个工具时 V3 贵 38%,10-20 39→72 时贵 1.6–2.9 倍;当天用 triage 收窄救了研判这一条路(`triage_scope_check.py` 守着)。但**对话助手这条路**(kb / task)没有收窄也没有按需加载,10-23 之后又加了 5 个工具。每加一个工具约 +650 字符 schema ≈ +1,100 token / 次调用 × 该角色全部调用。已核实(数据见上);是否值得为此改 —— 见第 7 节第 1 条。

---

## 2. 提示词(`prompts.py`)

### 2.1 规模与结构

- 文件 157,395 字符 / 2,309 行,其中规矩正文 **44,495 字符**,其余 ~11 万字符是给维护者看的注释和踩坑记录(这部分不进模型)。已核实。
- **102 条唯一规矩**(`prompts.all_rules(unique=True)`):49 条 `scope="铁律"`、53 条 `scope="工具"`;编号三套 TL01–TL81 / TW01–TW06 / TK01–TK16(TL 不连续,TL63 已撤)。已核实。
- 装配机制(`prompts.py:2216-2272`):按 `needs`(全要有)/ `avoid` 过滤;「写」标记由 `api.WRITE_TOOLS` 现算;铁律编成 1…N,工具级规矩按工具名分组放在「手上这几个工具的用法」。这正是 Accio 那个 `tool-registry.notes` 的形状(Rule 类 docstring 自己也说了,`prompts.py:68-74`),**只是它现在仍然进系统提示词,而不是贴在工具 schema 上随 ToolSearch 按需进。**
- 16 条无条件规矩(`needs=()`):TL53 TL61 TL01 TL03 TL04 TL58 TW01–05 TK01–04 TL78。5 条登记了「管」字段(TL61 / TK13 / TK14 / TK15 / TK16),供 `context_conflict_check.py` 查「同一件事几个人在说」。已核实。
- 13 条 P 检查守着(P1–P13,`tools/prompts_check.py`),其中 P6「挂了工具就要拿到规矩」+ P6b「规矩按名单启动时装配、不跟运行时取回走」是按需加载的静态前提。

### 2.2 最长的规矩(字符)

TK14 关差评 1,593 · TL34 商机 1,516 · TL33 谁没人管 1,217 · TK16 判差评倾向 1,178 · TL16 派任务 1,106 · TL02 查不到就说查不到 1,072 · TL29 库存预警 1,036 · TL67 经营报告 1,027 · TL39 成交率 974 · TL64 kb_rag 951 · TL74 受欢迎与易损 943 · TL62 按时间段列订单 937。前 12 条占总字数 31%。已核实。

### 2.3 重复

- 逐句比对(≥14 字的句子跨规矩重复):**只有 1 句**,TL12 和 TW03 都写「加急要求当场拒绝,别先答应再想办法」(全能助手两条都装)。重复控制得很好。已核实。
- 跨文件重复:`agent/v1.py:244-255` 的 BP02 题面里**手抄了一份客户合并判定标准**,而 V1 装配时又拿到了 TK05 —— V1 把同一标准收两遍;10-26 标准改成「按账户」时两处都要改(这次改对了,下次未必)。已核实。建议 BP02 用 `prompts.按号("TK05")` 引用。
- 「一次只做一件 / 同参数不重试 / 先 task_types」在 TL16 正文里写了一遍(`prompts.py:1083-`),而 `guards.pre_tool_verdict` 又结构化拦了一遍(`guards.py:1838-1904`)。这是「提示词 + 结构」双保险,不算错,但 TL16 1,106 字里有一半在复述 hook 会拦的事 —— 模型即便忘了,hook 的拦截理由也会把同样的话送回去。

### 2.4 自相矛盾处(已核实)

| 位置 | 矛盾 |
|---|---|
| TW05(workshop 铁律):「**工具全是只读的**」 | workshop 挂着 `start_workflow`(在 WRITE_TOOLS),所以同一份提示词里同时装了 TL05「你手上有一部分工具会真的改数据」。`prompts.py` TW05 行 vs `sdk.py:941,929` |
| PATTERN_HEAD:「**你手上有两个写工具**」 | 版师实际 4 个写口:set_piece_ratio / start_cutting / set_grade_diff / start_workflow(`prompts.py:1958` vs 现算 writes=4) |
| AFTERSALE_HEAD:「**你手上只有一个写工具** close_bad_rating」 | 还有 start_workflow(writes=2),`prompts.py:2035` |
| `sdk.ROLE_META[*].note`:all / kb / workshop / task 都写「只读。不下单、不改单…」 | 四个角色分别挂 29 / 17 / 1 / 29 个写工具(`sdk.py:786,797,839,856`)。`role_claims_check` 核的是 `writes` 数字,没核这句静态文案 |
| CLAUDE.md 第 6 节「21 个写工具」「四个 Hook」 | 现 32 个写工具、6 个 Hook(`guards.py:2388-2395`) |
| 安全边界审计「约定」表 TL16 行:「先对一遍只有提示词说」 | 11-11 起聊天页写操作必须点确认卡才执行(审计「结构」表里自己也有这一行,`安全边界审计.md:84`),TL16 那行已经半过期:聊天路径是结构,评测 / 其他路径仍是约定 |

### 2.5 写给人看、却发给模型的内容(token 浪费)

规矩正文里:59 处拍板日期引用(「业务 2026-09-22」「用户 10-25」)、2,501 字符的长括号补充、2,004 字符的「实测 / 栽过 / 📌 这条规矩现在没有产线在用 / 评测」旁白、1,760 个 `**` 加粗标记。保守估计 **10–15% 的规矩字数(4–6 千字 ≈ 7–10 千 token / 次调用)对模型没有信息量**。最典型:TK16 最后一段「📌 而这条规矩现在没有产线在用。差评研判那条路还没做…别把评测跑出来的数当产线表现」—— 这是写给维护者的,却装在 task / all / aftersale 三个角色的每一次调用里。已核实(`prompts.py` TK16 正文;统计用 `rules.json` 现算,数字是估算)。

### 2.6 哪些规矩已有结构闸,可以从提示词里删 / 缩

| 规矩 | 结构闸 | 建议 |
|---|---|---|
| TL16 一次只做一件 / 同参数不重试 / 先 task_types | `guards.pre_tool_verdict`(`guards.py:1851-1904`)、`gate_test.py` | 缩成一句「被拦下时照拦截理由做,别换参数再试」,其余删 |
| TL41 开裁过白坯闸 | `fsm.check` MUSLIN_GATE | 保留「被拒不许建议改状态绕过」,删对闸本身的描述 |
| TL44 / TL45 签收 6 位码 / 15 天追认 | FIT_GATE / COMPLETE_GATE | 同上 |
| TL49 判责金额授权 ≤1000 / 1000–5000 / >5000 | `repair_write.decide` 授权闸(审计表 81 行) | 保留「没批就停在待确认,不劝先开工」一句 |
| TL20 谁能批看状态机 | 审批状态机 | 保留「提单不是生效」 |
| TL56 回退只有店长能点 / TL59 外发单不许替报 | 写口按会话身份拒 | 一句话 |
| TL80 发布拦违规 | `roster_write` 规则 | 保留「违规念给店长、不自己改班绕过」 |
| TL40 / TL42 / TL46 / TL47 「动手之前先跟用户对一遍」 | 聊天页 11-11 确认卡(`mcp/protocol.py:257-263`,审计 84 行) | **聊天路径已是结构**;评测 / 内部 API 路径写工具根本不挂(`sdk.去掉写工具`),所以这句现在主要在给确认卡上的参数「对一遍」—— 可缩不可删 |
| TL58 不让价 | `g23_discount_promise`(Stop hook) | 保留(g23 只拦「提到价格」的句子,规矩管意图) |
| TL02「待核实 1301 格 / 规则推导 708 格」 | 工具 verdict 自带「待核实」;P7 核数字 | 删掉那几个会漂的数字,只留「verdict 是什么就照说」 |

### 2.7 仍然「只靠约定」的高风险条

| 规矩 | 风险 | 现有检查 |
|---|---|---|
| TL01 只说知识库里查到的 | 不带数字的编造漏网 | g1 只抓「报了数却没查」(审计约定表 122 行) |
| TL04 不能做 vs 不建议做 | 无 | 无 |
| TL11 换面料要客户确认 | 无 | 无 |
| TL53 别自己拿日期减 | 09-22 真栽过(3 天说成 25 天) | 只靠每轮注入 + 规矩 |
| TL61 先查再问 | 10-05 量过「先反问不查」 | 评测可见,无运行时闸 |
| TK16 判差评不许顺着倾向 | 10-13 探针:省事诱导 80% 滑档 | 只有探针,**没有产线在用** |
| TL34 / TL35 / TL62 等「N 条不许错」类 | 每条 900–1,500 字,靴子多、召回靠模型 | 对应 g 检查只覆盖个别点 |
| 写闸台账只记 5 个工具 | 见第 3.3 节 | — |

---

## 3. Hook 与安全

### 3.1 双锁现状(已核实)

- 配置层:`disallowed_tools` 18 个名字(Bash / BashOutput / KillShell / Read / Write / Edit / NotebookEdit / Glob / Grep / WebFetch / WebSearch / Task / Agent / TodoWrite / SlashCommand / Artifact / SendUserFile)+ 非 `all` 角色再加 `ToolSearch`(`sdk.py:1266-1270`)。`strict_mcp_config=True`、`setting_sources=["project"]`、cwd 挪出项目(`sdk.py:1279-1295`)。
- 运行层:PreToolUse 先按**这一轮生效名单**核(`guards.py:2263-2267`),再 `pre_tool_verdict`:Skill 按后台放行状态、ToolSearch 点名放行、其余非 `mcp__` 一律拦(`guards.py:1795-1827`)。
- 共 6 个 Hook:UserPromptSubmit(注日期 / 日记 / 术语 / 当前方案 / 压缩锚点)、PreToolUse、PostToolUse、PostToolUseFailure、Stop(29 个 g 检查,最多打回 1 次)、PreCompact。`guards.py:2388-2395`。CLAUDE.md 写「四个」,过期。
- 守着这套的检查:`skills_check.py`(DANGEROUS 清单 + `not name.startswith("mcp__")` 字面存在)、`boundary_audit.py` 真攻击(Bash / Task / disallowed / ToolSearch 5 点)、`gate_test.py`、`guards_test.py`。

**结论:双锁完整。** 真正起作用的是前缀闸(配置层会被改错,前缀闸是兜底),`skills_check` 盯着两道都在。

### 3.2 ToolSearch 例外的口子有多大

- 只对 `kind in 按需加载的角色 == {"all"}`:不进 disallowed、`ENABLE_TOOL_SEARCH=true`(`sdk.py:922,1270,1273`)。
- 取回的工具照样过前缀闸 + 名单闸;MCP 服务按名单建,名单外的 CLI 根本不认识(`sdk.py:371-377`)。
- `boundary_audit.a_toolsearch_scope`(`backend/boundary_audit.py:1090-1159`)真起知识领域服务搜版师写口、钩子判名单外工具和 Bash、换身份重建、研判名单、`开给==["all"]`、源码里 `+ ([] if kind in 按需加载的角色 else ["ToolSearch"])` 字面存在。
- 口子:**ToolSearch 本身是 CLI 内置工具,它返回的是 schema 文本**;它搜不到名单外的 MCP 工具(服务没起),能搜到的内置工具(Bash 等)取回也调不动。剩下的理论风险是「取回的 schema 占上下文」和「多一次往返」(all 平均 4.3 次工具调用里有不少是 ToolSearch:spans 里 ToolSearch 工具 span 463 次,是第三高频工具)。
- 一处小瑕疵:`skill_stats` 把一次 ToolSearch 的 query(`select:mcp__analytics__list_reports,...`)记成了技能名(`agentsite/evals/skill_usage.jsonl` 有 1 行)。推测是 `记一轮` 按 `tool == "Skill"` 挑之外还有一处宽松匹配;影响只在统计,不在安全。

### 3.3 写闸的真实覆盖面(已核实,**这是本节唯一的实质缺口**)

`pre_tool_verdict` 对 WRITE 工具做「写成功过就不许再写 / 同参数不重试 / 试 3 次停」(`guards.py:1838-1866`),依赖 `state["wrote"]` 台账;而 `make_hooks.pre_tool` 只给 **assign_task / dispatch_task / reassign_task / finish_task / assign_batch** 五个工具记台账(`guards.py:2286-2290`)。其余 27 个写工具(开单 / 确认下单 / 量体 / 试衣 / 签收三件 / 报修四件 / 关差评 / 排班 / 核占比 / 开裁 …)调用时 `ledger` 永远为空,「一轮只写一次」对它们不生效。

缓解:聊天页 11-11 起所有写操作走确认卡(`mcp/protocol.py:257-263`,只在 `LANXIU_CONFIRM_STORE` 设了时生效)—— 店员不点卡不执行,所以**聊天路径上这个缺口被卡盖住了**;内部 API 路径根本不挂写工具。暴露面剩下:评测进程(不设卡库,写在库副本上)、以及任何新调用方忘了设卡库。建议把台账记账从 5 个名字改成 `short in WRITE`(一行),并补一条咬合。

### 3.4 其他安全观察

- 「写」能力标记在 `prompts.assemble` 里 `import api` 失败时**静默不加**(`prompts.py:2255-2260`),P12 盯着两方向。真进程里核过:task / kb / all / workshop / pattern / aftersale / finance 都装 TL05、只有 triage 装 TL78 —— 正确。但这个「取不到就不加」的形状和项目反复栽的「声明≠生效」是同一类,建议改成取不到就炸(和 `_SYS` 漏配那段同一思路,`sdk.py:996-999`)。
- 安全边界审计里「约定」6 条中 TL16 那行已被确认卡部分覆盖,文档需要重生成一次说明边界(`backend/boundary_audit.py --md`)。

---

## 4. Skill 体系

### 4.1 数量(已核实,现数)

- `agentsite/.claude/skills/` **249 个目录**(有 SKILL.md)。
- 自有 **11 个**(`skills_own.OURS`):quote / growth-plan / roster / deadline-rescue / exchange / pattern-draft / call-notes / store-report / rating-repair / customer-recall / stock-patrol-lanxiu。
- 第三方 **238 个**(含 2 个「改造自第三方、尚未进 OURS」的 `activity-review-lanxiu` / `metric-diagnostics-lanxiu`)。`third_party_review.json` 审了 239 条(含已转自有的 stock-patrol 原件)。
- 放行(模型真调得动)= 自有 11(默认「已发布」)+ 库里登记「试运行」的 2 个 = **13**;spans 根上 `lanxiu.skills.available` 正好列着这 13 个。库 `skill_cfg` 只有 2 行(读 `sqlite3 -readonly`)。
- 谁放行:`backend/skill_registry.py` 状态机(已安装待审查 → 待适配 → 试运行 → 已发布 → 已停用,不许跳),只有总部运营能改;执行闸 `guards.pre_tool_verdict` 的 Skill 分支读同一状态(`guards.py:1795-1816`);没登记按来源取默认(自有 = 已发布,第三方 = 待审查);库读不到退回写死清单(fail closed)。`skill_registry_check.py` 在库副本上验。

### 4.2 第三方审查结论(`third_party_review.json`)

分类:不适用 212 / 可借鉴方法 14 / 缺依赖 7 / 可适配 6;初筛→终审有 42 条被改判(多数从「缺依赖」「可借鉴」改成「不适用」)。也就是说 **89% 的第三方技能业务上永远用不到**,留下的价值是 14 条「可借鉴方法」(写法样本)。

### 4.3 对提示词 / token 的影响

- 技能描述总字数 107,864 字符(249 个);自有 11 个 2,842 字符,试运行 2 个 600 字符。
- 聊天默认 `skills="own"` → 只有 13 个描述进上下文(约 3.4 千字符 ≈ 5–6 千 token);`all` 模式才把 236 个描述全放进去(CLAUDE / skills_own 记的「每轮多 2.7 万 token」、「召回题 0/3 → 2/3」)。已核实(`sdk.py:644-651`)。
- **所以第三方技能对线上 token 影响为零**,它的代价是:仓库 3.2 MB 正文;`skill_registry.依赖()` 现算要读 249 份 SKILL.md;`skills_check` / `skill_shape` / `manifest` 都要扫整个目录;以及「all」模式下的路由污染让那个模式实际不可用。

### 4.4 触发情况(`agentsite/evals/skill_usage.jsonl`,滚动 200 行)

200 轮里 70 轮触发技能、1 轮被拦。触发分布:store-report 12 / rating-repair 12 / roster 10 / customer-recall 9 / growth-plan 6 / exchange 5 / metric-diagnostics-lanxiu 4 / activity-review-lanxiu 4 / stock-patrol-lanxiu 4 / quote 3 / deadline-rescue 2;**pattern-draft 0 / call-notes 0**。spans 全量里 `Skill` 是最高频工具(653 次)。
推测:pattern-draft 和 call-notes 不是没人问,是触发词和版师 / 顾问入口的实际问法对不上(前者只在 pattern 角色上有意义而 pattern 入口跑得少;后者被 call_opportunity 工具直答抢了)。要用 `skill_eval.py` 的触发集核,不在本次只读范围。

### 4.5 过期 / 风险

- `skills_own.THIRD_PARTY_NOTE = "从 Accio 提取,236 个"` 和 `sdk.py:618` 注释「262 份去重 236 份」—— 现在目录里第三方是 238(含 2 改造版),文案又漂了一点;`skills_own.py` 文件头自己警告过「凡是写在话里的条数都会漂」。
- 两个改造版技能在「试运行」,但没进 OURS,所以不受 `skill_shape` 质量检查管,却受 `skill_body_check` 指纹管 —— 处于半自有状态;11-05 审查结论文档说「活动复盘 / 指标诊断的放行没拍过」,而库里已是试运行(10-23 拍的)。建议用户拍一次:转自有或退回待适配。
- HANDOFF 禁区:「主检出 `agentsite/.claude/skills/` 不挪不改不删」—— 任何瘦身都要先问。

---

## 5. V1 / V2 / V3 三代共存

### 5.1 谁在用谁(已核实)

| 代 | 生产在用? | 调用方 |
|---|---|---|
| V3 `agentsite/sdk.py` | **是**,所有聊天 / 研判 / 评测 | app.py(聊天 /run、内部 API /internal/run、研判队列 `run("triage")`)、rating_triage、trial_run、27 套 `agent/*_eval.py` |
| V1 `agent/v1.py` | **部分是** | ① `v1.call()` 是全项目唯一发请求口(`v1.py:120-125`),被 backend/asr.py(两处)、arrival_card.py、glossary_client.py(意图分类)、opportunity.py、fakedata/gen_transcripts.py、V2 的写草稿节点复用;② `v1.py one <tid>` 被管理后台 8760 研判草稿页子进程调用(`backend/server.py:361`);③ gen_compare |
| V2 `agent/v2.py` | 否 | `check.sh:549` 纯规则 40 条自测(不调模型)、gen_compare |

llm-trace 10-25 以来:V3 4,972 轮、V1 1,720 次调用(多数是 asr / 意图 / 商机这类业务调用借 `v1.call` 发的,gen 标成 V1)、V2 54 次(= 三代对比)。

### 5.2 三代对比数据(`agent/gen-compare-results.jsonl`,26 行)

最近 6 行:10-20 V1 6/6 $0.0169 · V2 6/6 $0.0012 · V3 6/6 $0.0239 · V3 6/6 $0.0213;10-23 V3 6/6 $0.0295 · **V3 4/6 $0.0182**(单轮,模型 haiku-4-5)。10-23 那次 4/6 的判错原文按 10-20 的改动已落盘,可查。CLAUDE 第 3 节表格停在 10-20,10-23 的两轮没进文档。

### 5.3 维护代价与是否值得

- 共享的东西:提示词(三代都 `prompts.assemble`)、工具 schema(V1 走 `api.*_SCHEMAS` 或 MCP client,V3 走 8 领域 MCP,V1/V2 仍走旧三服务 —— CLAUDE 第 2 节明说「三代对比条件不动」)、判分器(`agent/eval.py`)、记录仪。
- 真正的维护点只有三处:① V1 BP02 手抄合并标准(第 2.3 节);② 旧三服务 `mcp/kb_server.py` 等要跟着 `api.py` 活着(parity 检查守);③ TASK_RULES 一变 V1 跟着变(V1 每次带 69 条规矩 3.4 万字 + submit_finding)。
- 值不值:**值,但要冻结。** 这是用户定的路线(「迭代之路 V1→V2→V3 必须走完并留横向对比」),也是 CLAUDE 第 3 节的核心叙事;V2 500 行、纯规则离线自测几乎零成本;V1 的 `call()` 反正要留。建议明确写进 CLAUDE:V1/V2 只接 bug 修和标准同步,不接新能力;gen_compare 6 条工单集不扩。

---

## 6. 模型与成本

### 6.1 谁用什么模型(已核实)

| 路径 | 模型 | 出处 |
|---|---|---|
| 网站默认(聊天页 /run、内部 API) | `claude-haiku-5-5` | `sdk.网站默认模型()`,`sdk.py:130`;店长助手可由后台生产版指定(`backend/assistant_client.默认模型`),现为空 → 网站默认 |
| 难题升级 | `claude-opus-5-5` | `agentsite/model_route.py:17`;只在用默认且没手选时开,只升一次 |
| 脚本 / 评测默认 | `claude-haiku-4-5` | `sdk._env` 默认(`sdk.py:172`);`v1.provider()` OAuth 路径默认 4-5、API key 路径默认 opus-5(`v1.py:107,115`);gen_compare 不指定拒跑 |
| 夜跑 27 套评测 | `claude-haiku-4-5` 钉死 | `tools/nightly_eval.py:293,310`,每天 0 点,launchd `com.lanxiu.nightly-eval` |
| 意图分类(聊天前置) | 走 `v1.provider()` → 默认 4-5(后台术语版本可配) | `backend/glossary_client.py:414-426`;trace 里 166 次 4-5 vs 4 次 5-5 |
| 研判队列 `run("triage")` | 跟 `_env` → 4-5 | `agentsite/app.py:1083` 没传 model |

**不一致的后果**:
1. 10-25 以来 4,972 轮 V3 里 **haiku-5-5 只跑了 44 轮**(all 33 / pattern 10 / kb 1),opus-5-5 4 轮(2 次是升级)。生产默认模型几乎没被评测覆盖;「评测必须用产品真实在用的那个」这条记忆规矩现在不成立。
2. 窗口不同:4-5 是 20 万,5-5 是 100 万。kb / task 每次 13.9 万 / 16.5 万,在 4-5 上多轮会压缩,在 5-5 上不会 —— 评测里的「压缩后丢锚点」类问题线上不会出现,反之线上长会话的行为评测看不到。
3. 分词器 / 风格差异不详(推测)。10-20 用 4-5 做的三代对比和 10-25 之后线上的 5-5 不是同一个模型。

### 6.2 成本口径(已核实 + 1 条推测)

- `cost_of`(`sdk.py:272-305`)按 `v1.PRICE` 算:haiku-5-5 输入 $0.10 / 缓存读 $0.01 / 输出 $0.50 每百万。**官方价目:Haiku 5.5 这档只适用于 ≤10 万 token 的提示,超过按 $0.50 / $2.50**(claude-api 参考 Current Models 表;`v1.py:61-63` 注释自己写明「这里只记了 ≤10 万那档…会少算 5 倍,而且不报错」,并假设「全能助手按需加载后单次约 5 万」)。
- 实测:all 在 5-5 上平均 7.0 万 / 次(p90 8.2 万,7% 的调用 >10 万)—— 大体在便宜档;**但 kb 13.9 万、task 16.5 万每一次都在贵档**。如果店长助手 / 顾问助手照现在的工具面跑 5-5,页面显示的成本会比真账单少约 5 倍(缓存读在贵档的单价官方表没列,按同比例 5 倍是推测)。这正好撞在用户 10-25 那句「页面上显示的标价就是真要付的钱」上。
- SDK 自报 `total_cost_usd` 跨供应商不准(实测差 24–160 倍)的问题已经绕开,只在 Claude 上接近。

### 6.3 每次对话大约多少钱、月度量级

一轮 = 一次提问(含 2–6 次模型调用)。按 spans 实测 token 与官方价(推测项已标):

| 入口 / 模型 | 实测每轮 token(缓存读 / 写 / 输出) | 每轮成本 |
|---|---|---|
| 全能 · haiku-5-5(≤10 万档) | 19 万 / 2.6 万 / 1.1 千 | **$0.005**(实测均值 $0.0049,33 轮) |
| 全能 · opus-5-5(升级那一遍) | 35 万 / 6.6 万 / 1.4 千 | **$0.43**(实测 4 轮) |
| 全能 · haiku-4-5(评测) | 25 万 / 1.7 万 / 2.9 千 | $0.060 |
| 顾问 kb · haiku-4-5 | 33.8 万 / 0.7 万 / 2.1 千 | $0.053(2,392 轮) |
| 店长 task · haiku-4-5 | 31.4 万 / 1.0 万 / 1.8 千 | $0.053(1,373 轮) |
| 顾问 kb · haiku-5-5(推测,贵档 ×5) | 同上量 | ≈ $0.025–0.03;若按 `cost_of` 现行口径显示 ≈ $0.005 |
| 店长 task · haiku-5-5(推测) | 同上量 | ≈ $0.03;显示 ≈ $0.006 |
| 研判 triage · haiku-4-5 | 10-20 实测 | $0.021–0.024 / 条 |

月度量级(全部按 API 计费,推测):
- **现在的真实流量 = 评测**:10-25 以来平均 ~560 次调用 / 天、按 4-5 价 ≈ $22 / 天(11-10 跑了 1,440 次 $41)→ **≈ $650 / 月**(目前订阅内边际 0;若切 API 这就是账单)。换 5-5 跑评测:便宜档 ≈ $65 / 月,但 kb / task 评测落贵档 → ≈ $300 / 月。
- **线上业务**(假设 1 家店 50 轮 / 天,店长 + 顾问各半,5-5,10% 升 opus):便宜档 ≈ $0.005×45 + $0.43×5 ≈ $2.4 / 天 ≈ **$70 / 月**;贵档 ≈ $0.03×45 + $2.15 ≈ $3.5 / 天 ≈ **$105 / 月**;10 家店 ×10。**升级到 Opus 的那 10% 占了账单一半以上** —— 分流阈值是第二个成本旋钮。

### 6.4 哪里能省(按省多少排)

1. **工具按需加载扩到 kb / task**:每次调用 13.9 万 / 16.5 万 → 估 6–7 万(-55%);更要紧的是**跌回 Haiku 5.5 的 ≤10 万档**,单价差 5 倍。两件叠加,顾问 / 店长助手每轮成本降一个量级。
2. **分流只升一次、且只在交付检查不过时升**已经做了;可再加「升级前先用 haiku 带 effort=high 重答一遍」(推测,要 A/B)。
3. **缓存**:已经是缓存读为主(每轮未命中输入只有 10–40 token),没什么可省;每轮缓存写 0.7–2.6 万 token 来自注入(日期 / 日记三条 / 术语 / 当前方案)+ 用户话 + 工具返回,属于必要的 volatile 尾部。
4. **提示词瘦身** 10–15%(第 2.5 节),对 token 的影响约 -7–10 千 / 次,排在工具说明之后。
5. **工具级规矩随工具走**:53 条 ≈ 2.6 万字 ≈ 4.4 万 token 可以随 schema 按需进(第 7 节第 5 条),但要先解掉 P6b 的静态前提。
6. 输出端 effort:默认 medium,输出 1–3 千 token / 轮,占成本 <10%,不是主要矛盾。

---

## 7. 优化方向清单(按 线上效果与成本的影响 × 改动代价 排序)

| # | 方向 | 现状(证据) | 建议 | 工作量 | 触碰已拍板? |
|---|---|---|---|---|---|
| 1 | **工具按需加载扩到 kb / task(顾问助手、店长助手)** | 只开给 all(`sdk.py:922`);kb 13.9 万、task 16.5 万 token / 次,占全部模型调用 78%;all 开了之后 19.3 万→6 万(spans 实测);Haiku 5.5 >10 万 token 按 5 倍计价 | `按需加载的角色` 加 kb / task(或全部角色),同步改 `boundary_audit.a_toolsearch_scope` 第 ⑤ 条和 `bite_specs` 对应规格;用 chat_eval / tool_eval 对 kb、task 各跑两轮对照(多一次 ToolSearch 往返会不会掉路由分);再决定要不要全开 | 0.5–1 人日 + 评测 | 用户 10-23 拍的是「工具按需加载(推荐)」,**「只开给 all」是工程判断**(`sdk.py:921` 注释「按岗位的入口工具少,省不了多少」—— 现在数据说 kb / task 不少)。改之前跟用户说一句 |
| 2 | **成本口径按 Haiku 5.5 两档计价,页面显示真账单** | `cost_of` 只记 ≤10 万那档,`v1.py:61-63` 自己写着「会少算 5 倍,不报错」;kb / task 每次都在贵档 | `cost_of` 按每次调用(chat span)的提示长度分档,不按整轮;`cost_check.py` 补一条「>10 万的调用按贵档」对照用例;AI 调控中心 / 聊天页元信息跟着变 | 0.5 人日 | 不触碰;正是用户 10-25「标价就是真要付的钱」要求的 |
| 3 | **评测 / 夜跑模型与生产对齐** | 夜跑钉死 4-5(`nightly_eval.py:310`),生产默认 5-5;10-25 以来 5-5 只被跑过 44 轮;意图分类、研判队列也默认 4-5 | 先双轨一周(同题同晚各跑一轮 4-5 与 5-5,结果分两条基线),再把夜跑和 `_env` 默认切到 5-5;`evalrec.可比的三样` 会自动把两条线分开 | 1 人日 + 一周夜跑费用(切 API 后约 +$10/晚) | 触碰:「评测一律 Claude」不冲突;「夜跑钉死 4-5 保可比」是工程决定,但切基线要用户知道旧基线作废。记忆规矩「评测必须用产品真实在用的那个」支持这一条 |
| 4 | **提示词瘦身(不改语义)+ 修 5 处自相矛盾** | 10–15% 字数是给人看的旁白(TK16 📌段、「实测栽过」、59 处日期引用);TW05 / PATTERN_HEAD / AFTERSALE_HEAD / ROLE_META.note 与写工具数对不上;CLAUDE「21 个写工具 / 四个 Hook」过期 | 走项目自己的候选机制(`LANXIU_PROMPT_CANDIDATE` → 验证集 → 并排 → 采纳):旁白搬进 `#` 注释,保留稳定编号和数字(P7 守);矛盾句改成现算或删掉;审计 md 重生成 | 1–2 人日 + 两轮评测 | 不触碰;候选流程是 09-24 定的纪律,照走 |
| 5 | **工具级规矩贴到工具说明上,随 ToolSearch 按需进** | 53 条 `scope="工具"` ≈ 2.6 万字每次都在系统提示词里;`Rule` docstring 自己点名这是 Accio `tool-registry.notes` 的形状(`prompts.py:68-74`);P6b 钉着「规矩只在启动时按名单装」 | 把工具级规矩拼进 `工具模型说明.json` 的 description(已有 `拼进三份` 一处实现),系统提示词只留铁律;P6 / P6b 改成验「规矩在 schema 里」;先在 pattern / workshop 小角色试 | 3–5 人日 | 不触碰用户拍板,**触碰 P6b 判据设计**;效果要和第 1 条叠加才显著,排在它后面 |
| 6 | **写闸台账覆盖全部 32 个写工具 + 审计文档对齐确认卡** | `make_hooks.pre_tool` 只给 5 个任务类写工具记 `wrote`(`guards.py:2286-2290`),其余 27 个「一轮只写一次 / 同参数不重试」不生效;聊天页靠确认卡兜住,评测 / 新调用方不一定设卡库 | 记账条件改成 `short in WRITE`;`gate_test` 补一条 open_order 连写两次要拦的用例;`boundary_audit` 约定表 TL16 行改写「聊天路径已是结构」 | 0.5 人日 | 不触碰 |
| 7 | **三代冻结声明 + V1 BP02 引 TK05** | V1 题面手抄合并标准(`v1.py:249-255`)与 TK05 两份;V2 只在门禁和对比里跑;10-23 两轮对比没进 CLAUDE 表 | CLAUDE 第 3 节写明「V1/V2 只修 bug 不加能力」,BP02 用 `prompts.按号("TK05").text`;表格补 10-23 两行 | 0.5 人日 | 不触碰(用户要求留横向对比,这是照做) |
| 8 | **第三方技能归档** | 238 个第三方里 212 不适用、0 放行;3.2 MB 正文;`skill_registry.依赖()` / 三条门禁每次扫 249 份;「all」模式因路由污染不可用 | 212 个「不适用」挪到 `accio索引/` 或仓外归档(保留 14 可借鉴 + 7 缺依赖 + 6 可适配 + 2 改造版);`skills_own.THIRD_PARTY_NOTE` 改现算 | 1 人日 | **触碰**:用户要求「全拿」(09 月);HANDOFF 禁区「`agentsite/.claude/skills/` 不挪不改不删」。**必须先问** |
| 9 | **两个改造版技能的归属拍板** | `activity-review-lanxiu` / `metric-diagnostics-lanxiu` 库里「试运行」(10-23),11-05 文档说「放行没拍过」;不在 OURS 不受质量检查,受指纹检查 | 用户拍:转自有(进 OURS,正文去掉「改造自」)或退回待适配 | 0.2 人日 | **要用户拍** |
| 10 | **分流成本旋钮** | 升 opus-5-5 一遍 $0.43 ≈ 86 轮 haiku;升级占假想账单一半以上;升级触发只看交付检查 / 工具报错 | 升级前先用 haiku `effort=high` 重答一次,仍不过再升 opus;或升到 sonnet-5-5($0.11/轮)再到 opus | 1 人日 + A/B | 触碰:用户 10-25 拍「难题才调 Opus」「不按意图分类」—— 加一层 haiku 重试不违背,换 sonnet 要问 |
| 11 | **「写」标记取不到就炸** | `prompts.assemble` 里 `import api` 失败静默不加「写」(`prompts.py:2255-2260`),只靠 P12 事后抓 | 改成 raise(和 `_SYS` 漏配同一处理) | 0.1 人日 | 不触碰 |
| 12 | skill_stats 把 ToolSearch query 记成技能名 | `skill_usage.jsonl` 1 行 `select:mcp__analytics__...` | 修匹配条件,补一条自测 | 0.1 人日 | 不触碰 |

---

## 附:证据索引

- 角色工具 / 规矩 / 字数:`agentsite/sdk.py:392-611, 686-760, 935-999`;`import sdk` 现算结果见本文第 1.1 节表。
- 单次调用上下文:`.feynman/spans.jsonl` 的 `chat` span(`gen_ai.usage.*`),按 `trace_id` 回查根 span 的 `lanxiu.kind`。
- 每轮成本 / token:`.feynman/llm-trace.jsonl` 字段 `input_tokens / cache_hit_tokens / cache_write_tokens / output_tokens / cost_est`,10-25 之后按 `(model, purpose)` 聚合。
- 写工具与台账:`backend/api.py:678-`;`agentsite/guards.py:1838-1904, 2286-2290`。
- ToolSearch 口子:`agentsite/sdk.py:912-922, 1266-1273`;`agentsite/guards.py:1817-1827, 2260-2267`;`backend/boundary_audit.py:1090-1159`。
- Skill:`agentsite/skills_own.py`;`backend/skill_registry.py:112-170`;`agentsite/third_party_review.json`;`agentsite/evals/skill_usage.jsonl`;`sqlite3 -readonly backend/lanxiu.db "select name,status from skill_cfg"`。
- 三代:`agent/v1.py:120-125, 186-195, 244-255`;`agent/v2.py`;`agent/gen_compare.py:59-75`;`agent/gen-compare-results.jsonl` 末 6 行;`backend/server.py:355-366`。
- 模型:`agentsite/sdk.py:120-179`;`agentsite/model_route.py:1-20`;`tools/nightly_eval.py:293,310`;`agent/v1.py:59-70, 105-118`;`backend/glossary_client.py:414-426`;claude-api 参考「Current Models」表(Haiku 5.5 ≤10 万 $0.10/$0.50,超过 $0.50/$2.50)。
