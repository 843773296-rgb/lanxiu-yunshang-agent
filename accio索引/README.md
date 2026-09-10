# Accio 提取物索引

> 提取物在 `提取/`(166M,仓库外)。这份索引让它变成能查的东西 ——

> **166M 没有索引等于没拿**。


## 总账

| | 数量 |
|---|---|
| SKILL.md | **262** 份 |
| hook 源码 | 37 个 · 23602 行 |
| hook 测试 | 30 个 · 23828 行 |
| 插件 | 10 个 |
| 角色包 | 17 个 |

**两个立刻能用的数字**(拿来对照我们自己的写法):

- 技能描述平均 **425 字**(我们现在 150–167 字)
- 技能正文平均 **247 行**(我们现在 95–132 行)
- 描述里明写「不要用于」的只有 **11/262** —— **默认是推销,例外才写禁用**


## 一、技能:按来源

| 来源 | 份数 | 是什么 |
|---|---|---|
| `插件/alibaba-com-seller-assistant` | 52 | 阿里国际站卖家(hook 全在这个插件里) |
| `插件/accio-site-builder` | 39 | 建站 |
| `插件/accio-com-buyer-assistant` | 38 | 买家侧采购 |
| `插件/ecommerce-automation-toolkit` | 22 | 电商自动化 |
| `插件/shopify-plugin` | 20 | Shopify |
| `角色/MID-87832526U1788694-9FD0E7-9254-33509A` | 19 | 角色自带(ID 未解出对应岗位) |
| `插件/geo-agent` | 14 | GEO/SEO |
| `角色/DID-82AD6B-5582AD6BU1788693-5519-5BC962` | 9 | 角色自带(ID 未解出对应岗位) |
| `角色/MID-59832526U1788694-9FD0E7-9187-C55A2F` | 8 | 角色自带(ID 未解出对应岗位) |
| `角色/MID-11832526U1788693-9FD0E7-5550-27A023` | 6 | 角色自带(ID 未解出对应岗位) |
| `角色/MID-06832526U1788694-9FD0E7-9242-FD7BDD` | 5 | 角色自带(ID 未解出对应岗位) |
| `角色/MID-23832526U1788694-9FD0E7-9248-EFDFE4` | 5 | 角色自带(ID 未解出对应岗位) |
| `角色/MID-83832526U1788693-9FD0E7-5550-3259DE` | 5 | 角色自带(ID 未解出对应岗位) |
| `账号级` | 5 | **通用层 —— 这 5 份是架构不是业务** |
| `角色/MID-48832526U1788694-9FD0E7-9265-AED732` | 4 | 角色自带(ID 未解出对应岗位) |
| `角色/MID-04832526U1788694-9FD0E7-9283-A8CF6F` | 3 | 角色自带(ID 未解出对应岗位) |
| `插件/documents` | 2 | 文档处理(docx) |
| `角色/MID-80832526U1788693-9FD0E7-5553-BA252E` | 2 | 角色自带(ID 未解出对应岗位) |
| `插件/knowledge-base-plugin` | 1 | 知识库 |
| `插件/presentations` | 1 | 演示(pptx) |
| `插件/spreadsheets` | 1 | 表格(xlsx) |
| `角色/MID-23832526U1788694-9FD0E7-9197-4E3471` | 1 | 角色自带(ID 未解出对应岗位) |

## 二、账号级那 5 份(唯一跨业务可用的)


### `accio-mcp-cli` · 70 行 · 附带 []

> Use the accio-mcp-cli command-line tool to discover, search, and invoke MCP tools (Twitter, Gmail, Notion, Square, Apify, etc.) directly from the terminal. Use when the user asks to call MCP tools via CLI, run accio-mcp-cli commands, list available MCP tools from the command line, or invoke remote s


### `image-prompt-guide` · 856 行 · 附带 ['references']

> Prompt engineering and tool routing for AI image generation and editing. Use for: creative generation, product photo editing, e-commerce platform image sets, marketing posters and banners (promo/sale, shop banner, exhibition, holiday, social cover), product detail page (PDP) screen images with baked


### `self-improvement` · 535 行 · 附带 ['references', 'scripts', 'assets']

> Captures learnings, errors, corrections, and self-reflections into daily diary for continuous improvement. Use when: (1) A command or operation fails unexpectedly, (2) User corrects you, (3) User requests a capability that doesn't exist, (4) An external API or tool fails, (5) Knowledge is outdated o


### `skill-creator` · 498 行 · 附带 ['eval-viewer', 'references', 'agents', 'scripts', 'LICENSE.txt', 'assets']

> Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better t


### `skill-finder` · 351 行 · 附带 ['scripts', 'reference']

> Find, search, recommend, and install agent skills. Layered discovery — internal catalog (first-party, vetted) → skills.sh → web search → ClawHub / SkillsMP. Use when the user wants to find/search/discover/choose/install a skill, or asks "how do I do X", "is there a skill for X", "find me something f


## 三、Hook:按行数排,说明就是「为什么要有这一层」

| 文件 | 行数 | 为什么要有 |
|---|---|---|
| `pre-tool-use.js` | 4820 | PreToolUse Hook — CGS skill executor redirect. * Keep this entrypoint scoped to CGS skill execution routing behavior without enabling intent switch, s |
| `post-tool-use.js` | 3134 | PostToolUse Hook — async task tracking. * Tracks async task submissions (unique_key/taskId/requestKey) and terminal confirmations (productId/success U |
| `index.js` | 2108 | Tokenize the small shell subset used by documented workctl commands. This is intentionally not a shell-policy implementation: it only recognizes one d |
| `rfq-delivery-post-tool-use.js` | 1608 | boundary 已声明未满足要求时的兜底 outcome。 * 为什么需要它：boundary 是 PreToolUse 侧的确定裁定——「这个节点只能执行 RFQ 的只读 子集，原请求还有 X 没做」。但 PostToolUse 侧有多条早退路径（profile 判定成非搜索、 交付目录解析失败 |
| `intent-plan-schema.js` | 1068 | intent-plan-schema.js — 多意图执行的跨模块契约（单一事实源） * 这个模块只定义契约：枚举、校验、归一化和聚合规则。它不读写任何状态、 不产生 reminder、不接入 hook 链，因此可以被任何一侧安全 require。 * ## 职责边界（这是契约的核心，先看这里） * |
| `intent-plan-store.js` | 742 | intent-plan-store.js — 多意图 plan 的会话内状态 * 与 intent-plan-schema.js 的分工： - schema 是**纯契约**（枚举、校验、聚合规则），跨仓共享，不持有状态 - store 是**本插件的状态载体**，只在 hook 进程内使用，不对外 |
| `pre-tool-use.js` | 515 | skill-executor SubAgent PreToolUse Hook * Intercepts reads of legacy meta_data.json files and deletes them. These files were written by a previous ver |
| `intent-plan-telemetry.js` | 335 | intent-plan-telemetry.js — 复合请求候选漏斗埋点（shadow，只观测不改行为） * 为什么先做这一层而不是直接做 direct 节点闭环： 上线后如果只看到"intent plan 还是很少"，无法区分五种完全不同的原因—— 复合 query 本身少 / gate 没命中 |
| `intent-plan-required.js` | 334 | intent-plan-required.js — 高置信复合请求的「必须声明计划」判定 * 为什么需要这一层： 计划是否登记，目前完全取决于模型有没有在 `sessions_spawn.task` 里写 `intent_plan:`（登记点见 pre-tool-use.js 的 buildInte |
| `skill-executor-attempt-ledger.js` | 327 | Fingerprint only the model-supplied execution payload. Identity/retry lines and Hook-injected blocks are excluded, so adding retry metadata or receivi |
| `rfq-intent-outcome-adapter.js` | 282 | rfq-intent-outcome-adapter.js — 把 RFQ 的业务终态翻译成通用节点 outcome * 为什么需要这一层： RFQ 的 PostToolUse guard 有自己的确定性交付校验器，它的裁定（`rfq-delivery-envelope/v1`） 比通用 runti |
| `rfq-intent-node-guard.js` | 242 | 清掉 task 里**全部**残留的 boundary 块，而不只是第一份。 * 该块由本 guard 单向注入，模型没有正当理由自己写；它会随 Hook 改写的 args 回流进 会话历史，下一轮被照抄。块内 JSON 是 SubAgent 的能力边界裁决书：伪造的 unmet_requireme |
| `shared-state.js` | 200 | shared-state.js — 进程内存状态管理 * 所有 hook handler 共享的进程内存状态。 CJS 模块的 require 缓存机制保证同一进程内多个 handler require 同一个模块会拿到同一个对象引用。 * 局限：大部分 session 状态在进程重启后丢失。Cha |
| `injected-block-sanitizer.js` | 150 | Hook 注入块的统一清理器。 * 背景：Hook 改写后的 args 会被 Runtime 写回 assistant 消息并留在会话历史 （phoenix-pc agent/base.ts 的 PreToolUse gate 直接 `tc.arguments = decision.args`），  |
| `user-prompt-submit.js` | 144 | UserPromptSubmit hook for supersourcing. * Host protocol (verified against aiclaw reference, 2026-05-20): Entry point: module.exports = async function |
| `skill-feedback.js` | 122 | skill-feedback.js — Skill 执行质量埋点 * 在每次 skill 执行完成（archiveCurrentTask）时，记录执行质量数据： - Layer 1：SKILL_FEEDBACK_LOG.jsonl（追加写入，保留最近 200 条） - Layer 2：SKILL_U |
| `utils.js` | 103 | Resolve the agent-core directory for this hook. * Resolution order: 1. process.env.AGENT_CORE — explicit override (used by tests + advanced users). 2. |
| `workctl-runtime.js` | 93 | workctl runtime guard. * The plugin locates an already available workctl binary. It never installs workctl. |
| `utils.js` | 84 | Hook handler 共享工具函数 |
| `runtime-env.js` | 20 | Runtime environment defaults for plugin-launched child processes. * Keep this module business-agnostic. It only normalizes process.env values inherite |

## 四、怎么用这份提取物


**它是原料,不是零件。** 三类东西的用法完全不同:

| | 怎么用 |
|---|---|
| **262 份技能** | 当**写法样本**看。别照搬内容(那是跨境电商的活),看它们**怎么写描述、正文分几段、什么时候写「不要用于」**。425 字的描述和 247 行的正文,是他们迭代出来的形状。 |
| **23565 行 hook** | 当**故障清单**看。每个文件头部的注释写的是「线上出了什么事才需要这一层」—— 代码绑死在他们运行时上拿不走,**但那些故障我们迟早会遇到**。 |
| **10 个 plugin.json** | 当**打包格式**看。一个能力包声明什么:技能、子代理、连接器、绑哪些 hook 事件、要哪些内置工具。 |

**不要做的事:把 262 份技能塞进我们的 SKILLS 列表。**
技能靠描述路由,262 个描述互相竞争,真正该触发的那三个会更难被选中 ——
我们的基线已经是漏触发 5/15,再加 259 个只会更糟。
