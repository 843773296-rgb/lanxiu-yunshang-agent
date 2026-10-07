# AI 管理后台 · 开发接口(规格 §17.5)
#
# ⚠️ **还没实现的 target 一律报「未实现」并以非零退出。**
# 规格「实施必须遵守」第 2 条说的是按钮:「未接入能力明确显示未配置/不支持,
# 不能用 Toast 和假进度冒充执行」。同一条原则对 make target 成立 ——
# 一个打印「✅ 完成」却什么都没做的 target,比没有这个 target 糟得多:
# 它会让人以为这一步过了。
SHELL := /bin/bash
# `#` 在 make 的配方里要用变量传,直接写 `\#` 会把反斜杠一起带给 shell
HASH := \#
.PHONY: help bootstrap dev seed-demo test test-e2e test-e2e-ci page-smoke test-browser test-live contract doctor migrate gen worker worker-once progress \
        test-orchestration test-orchestration-e2e test-orchestration-live

help:
	@echo "可用:"
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

doctor:        ## 探本机依赖:PG / pgvector / Redis / Node / Python
	@bash tools/doctor.sh

contract:      ## 只跑契约覆盖检查(不需要数据库)
	@./.venv/bin/python tools/spec_coverage.py
	@echo ""
	@./.venv/bin/python tools/test_registry_check.py
	@echo ""
	@echo "▸ 纯逻辑自测也要有入口能跑('tests/orchestration/')"
	@echo "  ⚠️ e2e 那一组有判据盯着,**这一组原来没有** —— 2026-10-04 数的时候"
	@echo "     16 份文件挂了 16 份,齐的;而它齐是靠人手挂齐的,下一份忘了挂门禁照旧绿"
	@./.venv/bin/python tools/orchestration_registry_check.py
	@echo ""
	@./.venv/bin/python tools/nav_smoke_check.py
	@echo ""
	@./.venv/bin/python tools/seed_flag_check.py
	@echo ""
	@./.venv/bin/python tools/fk_dep_check.py

bootstrap:     ## 装依赖 + 起基础服务 + 迁移
	@bash tools/bootstrap.sh

test:          ## 确定性单测与集成测试(**报实际跑了几项**)
	@./.venv/bin/python tools/spec_coverage.py
	@echo ""
	@./.venv/bin/python tools/test_registry_check.py
	@echo ""
	# ⚠️ 这条**不需要数据库**,放这儿是因为「装在一个我从来没跑过的目标里
	# 等于没装」—— `contract` 和 `test` 都挂上,两边我都会跑。
	@./.venv/bin/python tools/seed_flag_check.py
	@echo ""
	@./.venv/bin/python tools/fk_dep_check.py
	@echo ""
	@echo "▸ 要 If-Match 的写接口,**界面拿得到那个 revision 吗**(要服务在跑)"
	@echo "  ⚠️ 契约覆盖看「登记的都实现了吗」,端到端看「接口对不对」——"
	@echo "     **没有一条看「界面拿得到它要带的东西吗」**,而那一族的表现是界面做不起来"
	@./.venv/bin/python tools/ifmatch_reachable_check.py
	@echo ""
	@echo "▸ 铺数据的脚本跑得起第二遍吗(**要库,所以不在 contract 里**)"
	@echo "  ⚠️ 它会**重铺 seed 夹具**并跑两份端到端 —— 要先 make dev"
	@./.venv/bin/python tools/seed_rerun_check.py
	@echo ""
	# ⚠️ **这条要数据库,所以挂 `test` 不挂 `contract`。**
	# `contract` 那一组是「不需要数据库」的 —— 放进去会让它在没库的机器上红,
	# 而那种红会和真问题混在一张报告里。
	# > 一条装在跑不起来的地方的判据,和没装一样。
	@echo "▸ 后台里的铁律和 'prompts.py' 一致吗(要库)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tools/lanxiu_prompt_sync_check.py
	@echo ""
	@echo "▸ 后台知识库和仓库里的 md 一致吗(要库)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tools/lanxiu_kb_sync_check.py
	@echo ""
	@echo "▸ 后台工具目录和澜绣在跑的 81 个工具一致吗(要库)"
	@echo "  ⚠️ 这条里最要紧的一档是**副作用档位变了** —— 后台标着「只读」而澜绣那边已经会写了,"
	@echo "     **后台的闸会放过它**。「说明改了一个字」和「从只读变成会写」在哈希上长得一样,所以单独报。"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tools/lanxiu_tool_sync_check.py
	@echo ""
	@echo "▸ 契约和库是否一致(alembic check)"
	@echo "  ⚠️ **这一行原来是 \'alembic check 2>&1 | tail -1\'** —— 管道吞退出码,"
	@echo "     它红了这个目标也不红(整条命令的状态是 tail 的,永远 0)。"
	@echo "     2026-10-04 改成走包装脚本:**它自己判退出码,而且进了根 check.sh** ——"
	@echo "     原来这条只在 \'make test\' 里,而那是个我从来不跑的目标。"
	@echo "     > 一条判据装在一个我从来没跑过的目标里,等于没装;"
	@echo "     > 而即使跑了,接上管道之后它也不拦。"
	@./.venv/bin/python tools/alembic_sync_check.py
	@echo ""
	@echo "▸ 跨项目引用:**真的去攻击它**(5 次攻击 + 1 条正向对照 + 还原检查)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_project_isolation.py
	@echo ""
	@echo "▸ 任务租约:**真的让两个 worker 去抢**(并发/接手/重试/心跳,16 条)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_worker_lease.py
	@echo ""
	@echo "▸ 真 Embedding(BGE-small-zh-v1.5,onnxruntime 本机跑):"
	@echo "  **判据是语义有效性,不是形状** —— 四档层级必须成立"
	@echo "  (相同 > 同义 > 同主题 > 无关;pooling 错、前缀错都会让中间两档塌一起)"
	@echo "  ⚠️ 要模型文件:'bash tools/fetch_model.sh'(96 MB,不进 git)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_embedder_bge.py
	@echo ""
	@echo "▸ 索引构建:**真起 Worker 跑一轮**(端到端/跨构建复用/重复投递/"
	@echo "  **检查点机制**/已完成跳过/0 片段不许静默成功)"
	@echo "  ⚠️ 检查点那条是**机制级**证明:外层事务回滚,独立事务写的还在 ——"
	@echo "  场景级要「跑到一半 kill -9」,而那会变成偶发红,偶发红最后都被忽略"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_index_build.py
	@echo ""
	@echo "▸ 检索链:召回 → 截断 → 证据链('要精排=False',**不花 API 额度**)"
	@echo "  精排的**判据**在编排层(零依赖),精排的**效果**在 make test-live ——"
	@echo "  **只有第三层要花钱,而前两层覆盖了绝大部分会坏的地方**"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_retrieval.py
	@echo ""
	@echo "▸ 语料权限 · **在真 PG 上验**(两级 ACL 填完即 rollback,库里不留痕)"
	@echo "  还的是一笔点名记在交接里的欠账:72 组合对账是照 SQL 语义**用 Python 算的**,"
	@echo "  jsonb 的 '?|' 行为没在 PG 上验过 —— 一份「两种表示对账过了」的测试,"
	@echo "  和一份「对账的另一侧是我自己模拟的」,在那些绿勾上长得一模一样"
	@echo "  🔑 第一次真跑就量出一个分叉:'{\"roles\":[]}' 上 SQL 说看不到、"
	@echo "     纯判定说看得到(coalesce 只对 NULL 生效,而 '[]' 不是 NULL) ——"
	@echo "     **纯逻辑对账抓不到它**,因为那两边都调同一个 '_规范()'(同源谬误的变种)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_corpus_acl_live.py
	@echo ""
	@echo "▸ 切片栏目 · 列表 + 详情(业务 2026-10-07 要的那个栏目)"
	@echo "  ⚠️ 这个接口最容易变成**绕开检索权限的后门** —— 不检索,直接翻列表;"
	@echo "     所以它用的是和检索同一个 where 片段,不是另写一套"
	@echo "  ⚠️ 只给最新那一版的片段(实测 1335 个片段里 619 条属于旧版本) ——"
	@echo "     索引取的也是 max(revision),列表跟索引一致才有参考价值"
	@echo "  ⚠️ 看不到和不存在**对外同形**(都 404),否则它是个存在性探测器"
	@echo "  🔑 混版本告警**整库一起看,不受 document_id 筛选影响** ——"
	@echo "     第一版拿带筛选的查询算,于是一条真告警会在筛选状态下消失"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_chunk_browse.py
	@echo ""
	@echo "▸ 向量约束:**真的插坏数据**(混维度/假向量id/重复文本/跨项目引用)"
	@echo "  「能用约束表达的不要用判据表达」是个声称 —— 这里去攻击它"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_vector_constraints.py
	@echo ""
	@echo "⚠️ test 跑的是**不需要起服务**的那部分(契约层 + 数据层)。"
	@echo "   接口和页面的闭环在 make test-e2e(要先 make dev)。"
	@echo "   **两个都绿也不代表「系统可用」** —— Worker / 知识链 / 训练链 / 发布链"
	@echo "   都还没实现,见 README 的「现在做到哪了」。"

worker:        ## 起后台 Worker(一直跑)
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python workers/worker.py

worker-once:   ## Worker 跑一轮就退(测试/CI 用)
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python workers/worker.py --一轮

migrate:       ## 改了契约之后:生成迁移(需要 -m "说明")
	@test -n "$(m)" || { echo '要写说明:make migrate m="加了什么"' >&2; exit 1; }
	@cd services/api && DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		../../.venv/bin/alembic revision --autogenerate -m "$(m)"

gen:           ## 重跑所有生成器(契约文档 + OpenAPI + 前端 TS 类型)
	@./.venv/bin/python tools/gen_contract_doc.py
	@./.venv/bin/python tools/gen_openapi.py
	@./.venv/bin/python tools/gen_ts_types.py

dev:           ## 起 API + 页面(http://127.0.0.1:8801)
	@bash tools/dev.sh

seed-demo:     ## 灌合成演示数据(**只在开发环境,重复跑不增加对象**)
	@APP_ENV=development \
	 DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python services/api/app/seed_demo.py

# ── 真浏览器:**故意不进 test-e2e,也不进 CI** ───────────────────────────
# ⚠️ 这个目标是 2026-09-29 补的。`tests/e2e/test_upload_page_firefox.py`
# 早就写好了,文件头上明写「单独 `make test-browser`」——
# **而那个目标当时并不存在**,文件也从没提交过。
# 也就是说:一份写得很细的测试,**没有任何入口能跑它** ——
# 那和没有这份测试是一回事,只是它在目录里躺着,看起来像有覆盖。
#
# 它为什么不进门禁,文件头里写清了:要可见的 Firefox 窗口
# (headless 下 Firefox 156 卡在一个关不掉的模态框上)、要 selenium
# (**故意不进 requirements.lock** —— 钉进去 CI 也会去装)。
test-browser:  ## 真浏览器点一遍「加资料」页(要 Firefox + selenium + make dev)
	@echo "▸ 真浏览器(Firefox + Selenium):「加资料」页的三步链路"
	@echo "  ⚠️ 会在屏幕上**弹一个 Firefox 窗口** —— 所以它不在 test-e2e 里"
	@echo "  ⚠️ 要 selenium(不在 requirements.lock 里):"
	@echo "     ./.venv/bin/pip install selenium"
	@./.venv/bin/python tests/e2e/test_upload_page_firefox.py

# ── 页面冒烟:**抽成独立目标,`test-e2e` 和 `test-e2e-ci` 共用** ──────────
# ⚠️ 不抽的话就是**第二份会漂的名单** —— 而 `nav_smoke_check` 只认一处:
# ⚠️ **这段注释里不许照抄那个 hash 的样子** —— 那条判据是按字面量
# 搜整个 Makefile 的,**它会命中描述它自己的这句话**
# (10-01 当场栽了一次:它报「冒烟名单里有侧栏没有的页」,
#  而那个「页」就是我在这儿举的例子)。
# 这个仓库在密钥扫描上栽过三次同一个形状:规则文件匹配自己、文档匹配自己。
# **要举例就描述它**(井号斜杠加页面名),别照抄。
# 它按那个形状搜整个 Makefile,两份名单里只要有一份全就通过,
# 于是「CI 版少打了三页」这件事它看不出来。
page-smoke:    ## 只跑页面冒烟 + 行级对账(要先 make dev)
# ⚠️ **这两条判据挪到这儿来了(2026-10-02)** —— 它们原来只在 `make test` 里。
# 而它们**要服务在跑**,`make test` 不保证这件事;`test-e2e` 正是
# 「服务在跑」那个目标。后果已经兑现过两次:
#   · 10-01 `alembic check` 装在 `make test` 里,而我跑 contract/test-e2e ——
#     它从 09-29 起一直红而我不知道
#   · 10-02 `ifmatch_reachable_check` 同一个形状,**一天拦我两次**,
#     两次都是在 CI 上才红
# > **一条判据装在一个我从来没跑过的目标里,等于没装。**
	@echo "▸ 要 If-Match 的写接口,**界面拿得到那个 revision 吗**"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tools/ifmatch_reachable_check.py
	@echo ""
	@echo "▸ 侧栏能点开的页,冒烟打过吗"
	@./.venv/bin/python tools/nav_smoke_check.py
	@echo ""
	@echo "▸ 页面冒烟:用最小 DOM 桩**真跑加载路径** + **行级对账**"
	@echo "  ⚠️ 对账断的是「接口给的每一条,身份都在页面上」——"
	@echo "     **「渲染了」不等于「渲的是那些东西」**(漏渲几条在字数上完全正常)"
# ⚠️ **这一段 2026-10-01 修过两处,两处都让它一直是「只看不拦」的:**
#
# ① 原来写的是 `node ... | tail -1` —— **管道吞退出码**:整个 shell 的状态
#    是 `tail` 的(永远 0),于是**页面冒烟红了也不会让这个目标红**。
#    这一族在这个项目里已经第五六次了。现在用 `rc` 收退出码、循环完再 exit。
#    (变量名必须是 ASCII —— bash 不接受中文变量名,CI 里栽过一次:
#     `红=0` 被当成命令,`$红` 展开成乱码 → 退出码 255。)
#
# ② 名单里**少了七页**:apps / conns / members / datasets / training /
#    artifacts / audit —— 也就是我 09-29 新建的那七页,
#    **在门禁里从来没被冒烟打过**。我手动打过,而那不算。
#    现在补上,并且有 `nav_smoke_check.py` 盯着「能点开的页都要在这儿」。
# ⚠️ **这里不许写 `set -e`。** 我第一版写了,而它让错误详情**永远打印不出来**:
# `out=$$(node ...)` 一失败就立刻退出 shell,后面那句
# `if [ $$? -ne 0 ]; then ... echo "$$out" | tail -6` 根本走不到 ——
# 门禁确实红了(这是对的),但它**只打印一个页面名就死了**。
# > 一个红了却不说为什么的门禁,等于让人自己去猜。
# 所以靠显式的 `rc` 收口,不靠 `set -e`。
	@rc=0; \
	for h in '#/workbench' '#/prompts' '#/runs' '#/workflows' '#/uploads' \
	         '#/kb' '#/retrieval' '#/usage' '#/traces' '#/health' '#/tryout' \
	         '#/evals' '#/compare' '#/human' '#/apps' '#/conns' '#/members' \
	         '#/datasets' '#/training' '#/artifacts' '#/audit'; do \
		printf "  %-14s " "$$h"; \
		out=$$(node tests/e2e/page_smoke.js "$$h" 2>&1); \
		if [ $$? -ne 0 ]; then rc=1; echo "❌ 挂了"; echo "$$out" | tail -6; \
		else echo "$$out" | tail -2 | tr '\n' ' '; echo ""; fi; \
	done; \
	if [ $$rc -ne 0 ]; then echo "  ❌ 有页面冒烟没过"; exit 1; fi
	@echo ""
# ⚠️ **澜绣项目要单独跑一遍** —— 2026-10-02 加。
# 上面那个循环跑的是「默认身份(U002)看到的那个项目」。而 10-02 建的
# `project_lanxiu`(澜绣那 79 条铁律)**只给了 admin 成员** ——
# 于是 U002 看不到它,上面 21 页全绿,而**整个澜绣项目一条断言都没有**。
# > **一个新建的项目默认不被任何冒烟盖住**
# > —— 和「一个新页面默认不被冒烟盖住」完全同形,而这次更隐蔽:
# > 门禁全绿,因为它们跑的是另一个项目。
#
# ⚠️ 行首要用 make 注释(`#` 顶格),不是 tab 开头的 shell 注释 ——
# 后者会被 make 当成命令**回显到输出里**,第一版就是那样,
# 于是门禁日志里混进了七行注释。
	@echo "▸ 澜绣项目(第一个真实项目):Prompt 页 + 知识页**真的渲出那些东西吗**"
# ⚠️ **先看项目在不在,再跑页面。** 不先看的话,「数据没导入」会被报成
# 「页面挂了」—— 而那会把人送去查一个没坏的页面(今天这条撞过两次:
# 一次是 404 被当成接口坏了,一次是空列表被当成渲染坏了)。
	@n=$$(./.venv/bin/python -c "import json,urllib.request as u; \
		r=u.Request('http://127.0.0.1:8801/api/v1/projects', \
		headers={'X-Dev-User':'U001'}); d=json.load(u.urlopen(r)); \
		print(sum(1 for p in d['items'] if p['id']=='project_lanxiu'))" 2>/dev/null); \
	  if [ "$$n" != "1" ]; then \
	    echo "  ❌ 后台里没有 \`project_lanxiu\` —— **这是数据没导入,不是页面坏了**"; \
	    echo "     跑 \`python3 tools/import_lanxiu_prompts.py\`(CI 里在「灌演示数据」那一步)"; \
	    exit 1; fi; \
	  rc=0; \
	  for h in '#/prompts' '#/kb'; do \
	    printf "  %-12s " "$$h"; \
	    out=$$(AIMC_USER=U001 AIMC_PROJECT=project_lanxiu \
		node tests/e2e/page_smoke.js "$$h" 2>&1); \
	    if [ $$? -ne 0 ]; then rc=1; echo "❌ 挂了"; echo "$$out"; \
	    else echo "$$out" | tail -1 | tr '\n' ' '; echo ""; fi; \
	  done; \
	  if [ $$rc -ne 0 ]; then echo "  ❌ 澜绣项目的页面冒烟没过"; exit 1; fi
	@echo ""
	@echo "▸ 画布页:**结构对账**(节点数/连线数/「加入」按钮数 vs 接口返回的定义)"
	@W=$$(./.venv/bin/python -c "import json,urllib.request as u; \
		r=u.Request('http://127.0.0.1:8801/api/v1/projects/project_demo_a/workflows', \
		headers={'X-Dev-User':'U002'}); d=json.load(u.urlopen(r)); \
		print(d['items'][0]['id'] if d['items'] else '')" 2>/dev/null); \
	  if [ -n "$$W" ]; then out=$$(node tests/e2e/page_smoke.js "$(HASH)/workflow/$$W" 2>&1); \
	    if [ $$? -ne 0 ]; then echo "❌"; echo "$$out" | tail -8; exit 1; fi; \
	    echo "$$out" | tail -2; \
	  else echo "  ⚠️ 演示库里没有工作流 —— 先 make seed-demo 或在页面上建一个。"; \
	       echo "     **这不叫通过,这叫没测到**"; exit 1; fi
	@echo ""
	@echo "▸ Agent 配置页:**结构对账**(连接下拉框项数 + 能力那一栏)"
	@A=$$(./.venv/bin/python -c "import json,urllib.request as u; \
		r=u.Request('http://127.0.0.1:8801/api/v1/projects/project_demo_a/agents', \
		headers={'X-Dev-User':'U002'}); d=json.load(u.urlopen(r)); \
		print(d['items'][0]['id'] if d['items'] else '')" 2>/dev/null); \
	  if [ -n "$$A" ]; then out=$$(node tests/e2e/page_smoke.js "$(HASH)/agent/$$A" 2>&1); \
	    if [ $$? -ne 0 ]; then echo "❌"; echo "$$out" | tail -8; exit 1; fi; \
	    echo "$$out" | tail -2; \
	  else echo "  ⚠️ 演示库里没有 Agent —— 在页面上建一个。**这不叫通过,这叫没测到**"; \
	       exit 1; fi
	@echo ""
# ⚠️ 这两页原来也是 `| tail -1`(**同一个吞退出码的毛病,第二处**)。
	@rc=0; for h in '#/agents' '#/tools'; do \
		printf "  %-12s " "$$h"; \
		out=$$(node tests/e2e/page_smoke.js "$$h" 2>&1); \
		if [ $$? -ne 0 ]; then rc=1; echo "❌"; echo "$$out" | tail -6; \
		else echo "$$out" | tail -2 | tr '\n' ' '; echo ""; fi; \
	done; if [ $$rc -ne 0 ]; then exit 1; fi
	@echo ""
	@echo "⚠️ 页面冒烟跑的是**加载路径**,不是视觉 —— 它证明「取到数并渲染了」,"
	@echo "   不证明「排版对」。视觉要人打开 http://127.0.0.1:8801 看。"
	@echo ""

# ── CI 版端到端:**只跑不花钱、不要本地模型的那些** ─────────────────────
#
# ⚠️ 2026-10-01 加的。在这之前**端到端那 773 条在 CI 里一条都没跑过** ——
# CI 的 `admin` job 只跑不要数据库的那些(编排四组 + 契约)。
# 也就是说本地 773 条全绿,而 CI 从来没验过它们:
# **本地绿不等于 CI 绿,而两者只有在「从零建得起来」这件事上会分岔。**
#
# 和 `test-e2e` 的差别**只有一处**:排掉两份要真调 Claude 的。
# 排掉哪几份、为什么,在 `E2E_CI跳过` 里写着,
# 而 `tools/test_registry_check.py` 会验「每一份都在两个名单之一里」——
# **一个新测试不许从两个名单之间漏掉**。
#
# ⚠️ 顺序和 `test-e2e` 一致(数据集要排在训练和评测之前)——
# 那条依赖的理由写在 `test-e2e` 里同一处。
E2E_CI := test_api_flow.py test_job_events_sse.py test_orchestration_flow.py \
          test_upload_flow.py test_usage_flow.py test_runctl_flow.py \
          test_connections_flow.py test_release_flow.py \
          test_datasets_flow.py test_debug_evals_flow.py \
          test_training_flow.py test_handover_flow.py \
          test_tools_flow.py test_settings_flow.py \
          test_lanxiu_knobs_flow.py test_toolgroups_flow.py \
          test_selection_policy_flow.py test_eval_items_flow.py \
          test_tool_modelcard_flow.py test_prompt_snapshot_flow.py \
          test_exec_mode_flow.py

E2E_CI_JS := test_conn_page_actions.js test_runctl_page_actions.js \
             test_sample_page_actions.js test_tool_page_actions.js \
             test_artifact_page_actions.js test_member_page_actions.js \
             test_release_page_actions.js

test-e2e-ci:   ## 端到端(CI 版):排掉要真调模型的那两份(要先 make dev)
	@echo "▸ 端到端(CI 版):$(words $(E2E_CI)) 份 Python + $(words $(E2E_CI_JS)) 份 JS"
	@echo "  ⚠️ **排掉了两份要真调 Claude 的** —— 排掉哪几份、为什么,"
	@echo "     看 Makefile 里 'E2E_CI跳过';'test_registry_check' 验「没有谁从两个名单之间漏掉」"
	@./.venv/bin/python tools/seed_datasets.py > /dev/null
	@./.venv/bin/python tools/seed_training.py > /dev/null
# ⚠️ **失败时把输出贴全,不 `tail` 截。**
# 第一版截 12 行,而挂的详情(每条断言的 `补`)在更前面 ——
# 于是 CI 上只看到「挂: 某条断言」而**看不到它拿到的是什么值**,
# 下一轮只能靠猜。和上一轮那个 `set -e` 是同一条:
# > **一个红了却看不到为什么的步骤,等于让人自己去猜。**
# 绿的时候仍然只打一行 —— 全贴会把日志淹掉,而那也是一种看不见。
	@rc=0; \
	for t in $(E2E_CI); do \
		printf "  %-30s " "$$t"; \
		out=$$(./.venv/bin/python tests/e2e/$$t 2>&1); \
		if [ $$? -ne 0 ]; then rc=1; echo "❌"; echo "$$out"; \
		else echo "$$out" | tail -1; fi; \
	done; \
	for t in $(E2E_CI_JS); do \
		printf "  %-30s " "$$t"; \
		out=$$(node tests/e2e/$$t 2>&1); \
		if [ $$? -ne 0 ]; then rc=1; echo "❌"; echo "$$out"; \
		else echo "$$out" | tail -2 | head -1; fi; \
	done; \
	if [ $$rc -ne 0 ]; then echo "  ❌ 有端到端没过"; exit 1; fi
	@echo ""
	@$(MAKE) --no-print-directory page-smoke
	@echo ""
	@echo "⚠️ **这一轮没跑的**(CI 里跑不了,不是忘了):"
	@echo "   · test_knowledge_flow.py / test_knowledge_write_flow.py ——"
	@echo "     它们有一条**会真调 Claude 精排**(月租额度),CI 里没凭据"
	@echo "   · test_upload_page_firefox.py —— 要可见的 Firefox 窗口(make test-browser)"
	@echo "   **这几条只有本地跑过** —— 别把这个 job 绿了读成「端到端全验过了」"

test-e2e:      ## 端到端:接口闭环 + 禁止行为 + 页面冒烟(要先 make dev)
	@echo "▸ 接口闭环与**禁止行为**(44 条:跨项目、权限、乐观锁、幂等、脱敏、未知费用)"
	@./.venv/bin/python tests/e2e/test_api_flow.py
	@echo ""
	@echo "▸ 成员与权限**在页面代码里真走一遍**(26 条)"
	@echo "  ⚠️ 这一页最硬的闸拦的不是「做错了」,是**「做完之后没法回头」** ——"
	@echo "     不许把最后一个能改权限的人降下来(降了没人能加回来,而界面上什么都不报)"
	@node tests/e2e/test_member_page_actions.js
	@echo ""
	@echo "▸ 模型产物部署**在页面代码里真走一遍**(16 条:三道闸各一条)"
	@echo "  ⚠️ 三道闸在列表上长得几乎一样,**下一步却完全不同** ——"
	@echo "     没标可用去校验 / mock 的换真训练 / **说不清的先把来路查清**"
	@node tests/e2e/test_artifact_page_actions.js
	@echo ""
	@echo "▸ 工具三个动作**在页面代码里真走一遍**(22 条:注册 / 改草稿 / 冻结)"
	@echo "  ⚠️ 最值钱的一条是**风险变大必须出新版本**;表单里也没有「代码」输入框"
	@node tests/e2e/test_tool_page_actions.js
	@echo ""
	@echo "▸ 样本页改样本**在页面代码里真走一遍**(17 条)"
	@echo "  ⚠️ 它同时是一条**安全边界**:断的是「接口有没有给原文」,不是「界面有没有显示」"
	@node tests/e2e/test_sample_page_actions.js
	@echo ""
	@echo "▸ 运行控制四个动作**在页面代码里真走一遍**(20 条)"
	@echo "  ⚠️ 这四个是**出事那天唯一的手段**;合法与否由接口算 —— 前端猜等于把状态机抄一遍"
	@node tests/e2e/test_runctl_page_actions.js
	@echo ""
	@echo "▸ 模型与连接两个动作**在页面代码里真走一遍**(18 条)"
	@echo "  ⚠️ 含一条**源码级**断言:表单里除了「引用」框,不许有任何像凭据的输入框"
	@echo "     —— 摆一个再靠后端拒,等于把「已经出事了」往后挪一步"
	@node tests/e2e/test_conn_page_actions.js
	@echo ""
	@echo "▸ 发布链四步**在页面代码里真走一遍**(33 条:哪个 revision 进哪个头、幂等键)"
	@echo "  **「接口对」和「页面把它接对了」是两件事** —— 冒烟只证明取到数并渲染了,它不点任何东西"
	@node tests/e2e/test_release_page_actions.js
	@echo ""
	@echo "▸ 任务事件流 SSE(17 条:按 seq 续传、终态要发结束、流开着也重新鉴权)"
	@echo "  **全后台最后一条「已实现未验」** —— 主要在打「空流和什么都没发生长得一样」"
	@./.venv/bin/python tests/e2e/test_job_events_sse.py
	@echo ""
	@echo "▸ 编排端到端(44 条:建图→校验→冻结→试运行→Worker;Agent 那一条同理)"
	@echo "  **这一份是为了把「我手敲 curl 验过」变成可重跑的断言** —— 它第一次跑就抓到一个 500"
	@./.venv/bin/python tests/e2e/test_orchestration_flow.py
	@echo ""
	@echo "▸ 知识与 RAG 端到端:三条接口 + **整条链路**(§9.5)"
	@echo "  ⚠️ 其中一条会**真调一次 Claude 精排**(月租额度);另一条走 要精排=false 不花钱"
	@./.venv/bin/python tests/e2e/test_knowledge_flow.py
	@echo ""
	@echo "▸ 知识库写入端到端(M2):**「片段进库不等于能检索」有代码兜着**"
	@echo "  (幂等靠内容哈希 / 输入变了新建构建 / 第一次建索引必须显式给模型)"
	@echo "  ⚠️ 其中一条会真调一次 Claude 精排(月租额度)"
	@./.venv/bin/python tests/e2e/test_knowledge_write_flow.py
	@echo ""
	@echo "▸ 运行控制端到端:**「请求」不是「已经」**(pause→pause_requested)"
	@echo "  (把「请求暂停」写成「已暂停」→ 界面显示已停而模型还在跑、钱还在花)"
	@./.venv/bin/python tests/e2e/test_runctl_flow.py
	@echo ""
	@echo "▸ 用量与上报链端到端(M3 + A1 接收端):**未知不是 0**、幂等不重复计费"
	@echo "  (「门店助手今天花了多少」答得出来 —— 那是 A1 存在的全部理由)"
	@./.venv/bin/python tests/e2e/test_usage_flow.py
	@echo ""
	@echo "▸ 工具与能力端到端(§11/§16.3):**风险变大必须出新版本**"
	@echo "  (只读→会写而旧说明还在被引用 / 密钥只给形状 / 指南不授予权限 / 白名单不是黑名单)"
	@./.venv/bin/python tests/e2e/test_tools_flow.py
	@echo ""
	@echo "▸ 设置组端到端(§15.3/§15.4):**审计终于读得出来了**"
	@echo "  (前面十几块写的留痕 / 不能授予自己没有的权限 / 不许去掉最后一个能管权限的人 / 预算 0 不是不限)"
	@./.venv/bin/python tests/e2e/test_settings_flow.py
	@./.venv/bin/python tests/e2e/test_lanxiu_knobs_flow.py
	@./.venv/bin/python tests/e2e/test_toolgroups_flow.py
	@./.venv/bin/python tests/e2e/test_selection_policy_flow.py
	@./.venv/bin/python tests/e2e/test_eval_items_flow.py
	@echo ""
	@echo "▸ §8.2「模型说明」那三个字段:**两种空分得开**"
	@echo "  (没给 = 没人说过 / 给了 '[]' = 有人看过确认不需要 —— 混掉的话"
	@echo "   「还有几个工具没人填过别名」这个问题从此答不出来,而它是这件事的唯一指标)"
	@./.venv/bin/python tests/e2e/test_tool_modelcard_flow.py
	@echo ""
	@echo "▸ 排队中的调试任务跑的是**提交时那一份**(外部审阅 4.5)"
	@echo "  ⚠️ 判据不是「它跑完了」,是**展开后的模板里是 A 还是 B** ——"
	@echo "     「跑完了」和「跑的是提交那一版」在界面上长得一模一样"
	@./.venv/bin/python tests/e2e/test_prompt_snapshot_flow.py
	@echo ""
	@echo "▸ 执行模式:**真实调用失败不许静默降级成 mock**(外部审阅 §5.4)"
	@echo "  ⚠️ 第 ③ 条在 'MODEL_ADAPTER=mock' 下会报 ⏸「没验」而不是通过 ——"
	@echo "     要真验那一条:'MODEL_ADAPTER=anthropic make dev' 之后再跑这一份"
	@./.venv/bin/python tests/e2e/test_exec_mode_flow.py
	@echo ""
	@echo "▸ 模型与连接端到端(§17.4-5):**碰凭据的那一组**"
	@echo "  (明文当场拒不是收下后忽略 / 错误不回显 / 列表只给形状 / 没探过的发生产被拦)"
	@./.venv/bin/python tests/e2e/test_connections_flow.py
	@echo ""
	@echo "▸ 应用与发布端到端(§17.4-9):**「哪一版在给用户跑」**"
	@echo "  (清单全是确切版本 / 生产只认审过的 / 指针原子 / 回滚是新动作不是改历史)"
	@./.venv/bin/python tests/e2e/test_release_flow.py
	@echo ""
	@echo "▸ 交割四条接口(调用链详情 / A3 接收端 / 实验对比 / 人工待办)"
	@echo "  **「验过」= 有可重跑的断言打过,不是「有人手工 curl 过一次」** —— 这一份补的正是那笔虚账"
	@./.venv/bin/python tests/e2e/test_handover_flow.py
	@echo ""
	@echo "▸ 数据集与训练导出端到端(§17.4 微调链前半段):**七道闸,每道一条**"
	@echo "  (过完闸一条不剩 → 422 而不是 200+空文件;声明了要脱而脱敏器没选型 → 不给不脱的版本)"
	@echo "  ⚠️ 要先 python3 tools/seed_datasets.py 铺那六份「每份专考一道闸」的数据集"
	@./.venv/bin/python tools/seed_datasets.py > /dev/null
	@./.venv/bin/python tests/e2e/test_datasets_flow.py
	@echo ""
# ⚠️ **评测那一份必须排在数据集之后。** 它要一个**已冻结的数据集版本**,
# 而冻结是 `test_datasets_flow` 干的 —— 和训练那一份同一条依赖。
# 这是今天第三次修「靠残留成立的顺序」(前两次是训练、数据集自己的 seed):
# 一份测试依赖**另一份测试的产物**,而在开发机上残留一直在,
# 于是它和「真的没有依赖」长得一模一样。
	@echo "▸ 最后七条端到端(调试四条 + 评测两条 + 改片段):**调试出来的不许冒充正式的**"
	@echo "  (不计端到端通过 / 写工具换模拟并给清单 / fork 是新 Run / 复核不覆盖 / 改片段出新候选)"
	@./.venv/bin/python tests/e2e/test_debug_evals_flow.py
	@echo ""
# ⚠️ **训练那一份必须排在数据集那一份之后。** 它要一个**已经冻结的数据集版本**,
# 而冻结是 `test_datasets_flow` 干的 —— 这条依赖以前没写在顺序上:
# 训练排在前面,靠的是**上一轮跑剩下的残留**。
# 2026-09-29 修 `seed_datasets.py` 的清理顺序时顺手把残留清掉了,这条依赖当场露出来:
# `test_training_flow` 报「没有固化过的数据集版本」。
# > 一条靠残留成立的顺序,在第一次从零跑的那天才会露出来 ——
# > 而在开发机上它和「真的没有依赖」长得一模一样。
	@echo "▸ 微调训练链端到端(§17.4):**四个状态之间的三道边界**"
	@echo "  (训练完成 → 有产物 → 产物可用 → 在服务用户;合成任意两个,界面上看起来都正常)"
	@echo "  ⚠️ 要先 python3 tools/seed_training.py —— 它会补一个 trainer,"
	@echo "     没有他这一组**一条都跑不起来**(demo 项目原来一个 trainer 都没有)"
	@echo "  ⚠️ **排在数据集那一份之后**:它要一个已冻结的数据集版本"
	@./.venv/bin/python tools/seed_training.py > /dev/null
	@./.venv/bin/python tests/e2e/test_training_flow.py
	@echo ""
	@echo "▸ 文件上传端到端:**「上传成功不等于内容可用」有代码兜着**(§17.1)"
	@echo "  (已上传的 能引用吗=false / 坏文件是 200+通过=false / 校验失败是终态)"
	@./.venv/bin/python tests/e2e/test_upload_flow.py
	@echo ""
	@$(MAKE) --no-print-directory page-smoke

test-live:
	@echo "❌ 未实现:外部调用还没接。**缺资源要报告跳过,不算通过**(§17.5)。" >&2
	@exit 1

# ── 编排(Workflow 与 Agent 后台规格 §18)─────────────────────────────
# 规格点名了这四个命令。**它们不改变原命令的含义**:原来的 test / test-e2e
# 照样跑原来那些,这三个只跑编排那一层。

progress:      ## 生成逐项实现进度(§20 的三档)—— **带运行时记账真跑一遍测试**
	@echo "▸ 起带路由记账的 API(账本 /tmp/aimc-routes.log)"
	@rm -f /tmp/aimc-routes.log
# ⚠️ **旧的 worker 日志也要清。** 不清的话上一轮那句「worker 起来了」还在,
# 就绪判据在新 worker 还没起来时就当场成立 —— 一条**恒为真**的就绪判据。
	@: > /tmp/aimc-worker.log
	@lsof -ti:8801 | xargs kill -9 2>/dev/null || true
	@pkill -f "workers/worker.py" 2>/dev/null || true
	@sleep 2
	@AIMC_TRACE_ROUTES=/tmp/aimc-routes.log nohup bash tools/dev.sh > /tmp/devlog.txt 2>&1 & \
	  printf "  等服务和 Worker 就绪 "; ok=0; \
	  for i in $$(seq 1 60); do \
	    if curl -sf -m 2 http://127.0.0.1:8801/api/healthz >/dev/null 2>&1 \
	       && grep -q "worker 起来了" /tmp/aimc-worker.log 2>/dev/null; then ok=1; break; fi; \
	    printf "."; sleep 1; \
	  done; \
	  if [ "$$ok" != 1 ]; then echo " 60 秒还没就绪 —— 看 /tmp/devlog.txt"; exit 1; fi; \
	  echo " 就绪"
	@echo "▸ 跑端到端(它打过哪些路由,账本上说)"
	@./.venv/bin/python tests/e2e/test_api_flow.py > /tmp/prog-test_api_flow.log 2>&1 \
	  || { echo "  ❌ test_api_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_api_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_api_flow.log
	@node tests/e2e/test_member_page_actions.js > /tmp/prog-test_member_page_actions.log 2>&1 \
	  || { echo "  ❌ test_member_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_member_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_member_page_actions.log
	@node tests/e2e/test_artifact_page_actions.js > /tmp/prog-test_artifact_page_actions.log 2>&1 \
	  || { echo "  ❌ test_artifact_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_artifact_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_artifact_page_actions.log
	@node tests/e2e/test_tool_page_actions.js > /tmp/prog-test_tool_page_actions.log 2>&1 \
	  || { echo "  ❌ test_tool_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_tool_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_tool_page_actions.log
	@node tests/e2e/test_sample_page_actions.js > /tmp/prog-test_sample_page_actions.log 2>&1 \
	  || { echo "  ❌ test_sample_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_sample_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_sample_page_actions.log
	@node tests/e2e/test_runctl_page_actions.js > /tmp/prog-test_runctl_page_actions.log 2>&1 \
	  || { echo "  ❌ test_runctl_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_runctl_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_runctl_page_actions.log
	@node tests/e2e/test_conn_page_actions.js > /tmp/prog-test_conn_page_actions.log 2>&1 \
	  || { echo "  ❌ test_conn_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_conn_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_conn_page_actions.log
	@node tests/e2e/test_release_page_actions.js > /tmp/prog-test_release_page_actions.log 2>&1 \
	  || { echo "  ❌ test_release_page_actions 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_release_page_actions.log; exit 1; }
	@tail -2 /tmp/prog-test_release_page_actions.log
	@./.venv/bin/python tests/e2e/test_job_events_sse.py > /tmp/prog-test_job_events_sse.log 2>&1 \
	  || { echo "  ❌ test_job_events_sse 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_job_events_sse.log; exit 1; }
	@tail -1 /tmp/prog-test_job_events_sse.log
	@./.venv/bin/python tests/e2e/test_orchestration_flow.py > /tmp/prog-test_orchestration_flow.log 2>&1 \
	  || { echo "  ❌ test_orchestration_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_orchestration_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_orchestration_flow.log
	@./.venv/bin/python tests/e2e/test_knowledge_flow.py > /tmp/prog-test_knowledge_flow.log 2>&1 \
	  || { echo "  ❌ test_knowledge_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_knowledge_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_knowledge_flow.log
	@./.venv/bin/python tests/e2e/test_upload_flow.py > /tmp/prog-test_upload_flow.log 2>&1 \
	  || { echo "  ❌ test_upload_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_upload_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_upload_flow.log
	@./.venv/bin/python tests/e2e/test_knowledge_write_flow.py > /tmp/prog-test_knowledge_write_flow.log 2>&1 \
	  || { echo "  ❌ test_knowledge_write_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_knowledge_write_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_knowledge_write_flow.log
	@./.venv/bin/python tests/e2e/test_usage_flow.py > /tmp/prog-test_usage_flow.log 2>&1 \
	  || { echo "  ❌ test_usage_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_usage_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_usage_flow.log
	@./.venv/bin/python tests/e2e/test_runctl_flow.py > /tmp/prog-test_runctl_flow.log 2>&1 \
	  || { echo "  ❌ test_runctl_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_runctl_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_runctl_flow.log
	@./.venv/bin/python tests/e2e/test_tools_flow.py > /tmp/prog-test_tools_flow.log 2>&1 \
	  || { echo "  ❌ test_tools_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_tools_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_tools_flow.log
	@./.venv/bin/python tests/e2e/test_settings_flow.py > /tmp/prog-test_settings_flow.log 2>&1 \
	  || { echo "  ❌ test_settings_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_settings_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_settings_flow.log
	@./.venv/bin/python tests/e2e/test_lanxiu_knobs_flow.py > /tmp/prog-test_lanxiu_knobs_flow.log 2>&1 \
	  || { echo "  ❌ test_lanxiu_knobs_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_lanxiu_knobs_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_lanxiu_knobs_flow.log
	@./.venv/bin/python tests/e2e/test_toolgroups_flow.py > /tmp/prog-test_toolgroups_flow.log 2>&1 \
	  || { echo "  ❌ test_toolgroups_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_toolgroups_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_toolgroups_flow.log
	@./.venv/bin/python tests/e2e/test_eval_items_flow.py > /tmp/prog-test_eval_items_flow.log 2>&1 \
	  || { echo "  ❌ test_eval_items_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_eval_items_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_eval_items_flow.log
	@./.venv/bin/python tests/e2e/test_tool_modelcard_flow.py > /tmp/prog-test_tool_modelcard_flow.log 2>&1 \
	  || { echo "  ❌ test_tool_modelcard_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_tool_modelcard_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_tool_modelcard_flow.log
	@./.venv/bin/python tests/e2e/test_prompt_snapshot_flow.py > /tmp/prog-test_prompt_snapshot_flow.log 2>&1 \
	  || { echo "  ❌ test_prompt_snapshot_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_prompt_snapshot_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_prompt_snapshot_flow.log
	@./.venv/bin/python tests/e2e/test_exec_mode_flow.py > /tmp/prog-test_exec_mode_flow.log 2>&1 \
	  || { echo "  ❌ test_exec_mode_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_exec_mode_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_exec_mode_flow.log
	@./.venv/bin/python tests/e2e/test_selection_policy_flow.py > /tmp/prog-test_selection_policy_flow.log 2>&1 \
	  || { echo "  ❌ test_selection_policy_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_selection_policy_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_selection_policy_flow.log
	@./.venv/bin/python tests/e2e/test_connections_flow.py > /tmp/prog-test_connections_flow.log 2>&1 \
	  || { echo "  ❌ test_connections_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_connections_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_connections_flow.log
	@./.venv/bin/python tests/e2e/test_release_flow.py > /tmp/prog-test_release_flow.log 2>&1 \
	  || { echo "  ❌ test_release_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_release_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_release_flow.log
	@./.venv/bin/python tests/e2e/test_handover_flow.py > /tmp/prog-test_handover_flow.log 2>&1 \
	  || { echo "  ❌ test_handover_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_handover_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_handover_flow.log
	@./.venv/bin/python tools/seed_datasets.py > /tmp/prog-seed.log 2>&1 \
	  || { echo "  ❌ 铺数据集挂了"; tail -12 /tmp/prog-seed.log; exit 1; }
	@./.venv/bin/python tests/e2e/test_datasets_flow.py > /tmp/prog-test_datasets_flow.log 2>&1 \
	  || { echo "  ❌ test_datasets_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_datasets_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_datasets_flow.log
# ⚠️ 评测那一份**排在数据集之后** —— 它要一个已冻结的数据集版本。理由见 test-e2e 里同一处。
	@./.venv/bin/python tests/e2e/test_debug_evals_flow.py > /tmp/prog-test_debug_evals_flow.log 2>&1 \
	  || { echo "  ❌ test_debug_evals_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_debug_evals_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_debug_evals_flow.log
# ⚠️ 训练那一份**必须排在数据集之后** —— 它要一个已冻结的数据集版本,
# 而冻结是 test_datasets_flow 干的。理由见 test-e2e 里同一处的注释。
	@./.venv/bin/python tools/seed_training.py > /tmp/prog-seedtr.log 2>&1 \
	  || { echo "  ❌ 铺训练夹具挂了"; tail -12 /tmp/prog-seedtr.log; exit 1; }
	@./.venv/bin/python tests/e2e/test_training_flow.py > /tmp/prog-test_training_flow.log 2>&1 \
	  || { echo "  ❌ test_training_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_training_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_training_flow.log
	@echo ""
	@echo "▸ 页面冒烟(它取哪些接口,也记在同一本账上)"
	@for h in '$(HASH)/workbench' '$(HASH)/prompts' '$(HASH)/runs' '$(HASH)/workflows' \
	          '$(HASH)/agents' '$(HASH)/tools' '$(HASH)/uploads' '$(HASH)/kb' \
	          '$(HASH)/usage' '$(HASH)/traces' '$(HASH)/health' '$(HASH)/tryout' \
	          '$(HASH)/evals' '$(HASH)/compare' '$(HASH)/human' \
	          '$(HASH)/retrieval'; do \
		node tests/e2e/page_smoke.js "$$h" >/dev/null 2>&1 || true; done
	@echo "▸ 生成报告"
	@AIMC_TRACE_ROUTES=/tmp/aimc-routes.log ./.venv/bin/python tools/progress_report.py
	@echo ""
	@echo "⚠️ 「验过」= 测试**真的打过这条路由**,不是「测试文件里提到过」。"
	@echo "   但**打过一次不等于断言对** —— 这份报告回答「有没有被碰过」,不回答「对不对」。"

test-orchestration:       ## 编排:契约覆盖 + DSL 语义(夹具驱动,不需要数据库)
	@./.venv/bin/python tools/spec_coverage.py
	@echo ""
	@echo "▸ Shell 体检:**bash 不接受中文变量名**(本地 zsh 接受,CI 的 bash 不接受)"
	@echo "  踩过三次,其中一次在**全绿时完全看不出来**:'红=0' 被当成命令,"
	@echo "  '$$红' 展开成空,exit 拿不到数字退 255 —— 而红的理由完全指错方向"
	@./.venv/bin/python tools/shell_lint.py
	@echo ""
	@echo "▸ 敏感信息检测覆盖:**漏检和误拦分开报**(用户 2026-09-28 要求)"
	@echo "  合成一个准确率等于让一次泄露和一条样本互相抵消 —— 两种错的代价完全不对称"
	@echo "  ⚠️ 已知盲区内的漏检**不计入红**,但逐条列出来:盲区是待办,不是免责声明"
	@./.venv/bin/python tools/redact_coverage.py
	@echo ""
	@echo "▸ JSONB 列写裸串:**今天栽了八次的那一族**"
	@echo "  'sql_columns_check' 只查列名不查类型 —— 那条已知盲区两天里放过去 8 次同一个错"
	@echo "  ⚠️ 判据改了三版才咬得住:盯错不变量 → 留的口子正好放过真 bug → 收紧过头又漏"
	@./.venv/bin/python tools/jsonb_cast_check.py
	@echo ""
	@echo "▸ SQL 列名体检:**问 information_schema,不猜列名**"
	@echo "  (同一天栽了四次「没查就写 SQL」:三次猜类型、一次猜列名)"
	@./.venv/bin/python tools/sql_columns_check.py
	@echo ""
	@echo "▸ Makefile 自己:'@echo' 里不许有反引号 —— 它是 shell 的命令替换"
	@echo "  2026-10-07 量到 23 行,被执行的东西里有 'bash tools/fetch_model.sh'"
	@echo "  (会真的下模型)和 'MODEL_ADAPTER=anthropic make dev'(会真的起服务) ——"
	@echo "  今天没出事只因为那几行所在的目标恰好没被跑到"
	@echo "  🔑 而我**当天自己又种了四个** —— 所以它不能只写在 CLAUDE.md 里"
	@./.venv/bin/python tools/makefile_echo_check.py
	@echo ""
	@echo "▸ SQL 字符串体检:注释里的绑定参数 / 缺 cast 的位置"
	@echo "  **判据不自己实现词法,问 SQLAlchemy** —— 第一版自己写正则,15/17 是误报"
	@./.venv/bin/python tools/sql_lint.py
	@echo ""
	@echo "▸ DSL 语义:**判据是一张手写的真值表**,不是从实现跑出来的"
	@./.venv/bin/python tests/orchestration/test_dsl_semantics.py
	@echo ""
	@echo "▸ 图校验:**17 张图,期望阻断码手写在夹具里,判据是集合相等**(多报也算错)"
	@./.venv/bin/python tests/orchestration/test_graph_validation.py
	@echo ""
	@echo "▸ 执行:**预期激活路径手写 + 模型响应脚本化**(模型调用次数由 mock 那侧数)"
	@./.venv/bin/python tests/orchestration/test_execution.py
	@echo ""
	@echo "▸ 知识链:解析 + 切片,**判据是「证据链真的能指回原文」**(跑真语料)"
	@./.venv/bin/python tests/orchestration/test_knowledge_chain.py
	@echo ""
	@echo "▸ Embedding 适配器:**mock 向量比 mock 文本危险** —— 它的相似度看起来很正常"
	@echo "  (跨进程确定性用子进程验;那条咬合必须真的改文件,monkeypatch 咬不住)"
	@./.venv/bin/python tests/orchestration/test_embedder.py
	@echo ""
	@echo "▸ 精排的判据:**零依赖,不发一个请求**(CI 里没有 Claude 凭据)"
	@echo "  挡 LLM 的三种编法:编编号 / 漏候选 / 编引文。0 分免引文是有意的"
	@./.venv/bin/python tests/orchestration/test_reranker.py
	@echo ""
	@echo "▸ 「零依赖」真的零依赖吗 —— **用系统 python3 把 CI 那一步跑一遍**"
	@echo "  (CI 第一步故意什么都不装;而这件事在 2026-09-27 之前只是一句注释,"
	@echo "   于是它红了两次而**本地是绿的** —— 本地 venv 里有 sqlalchemy)"
	@./.venv/bin/python tools/check_zero_dep.py
	@echo ""
	@echo "▸ 人工审批:**一道拦得住但没有放行入口的闸,是做了一半的机制**"
	@echo "  (模型不能自批 / 过期在点批准那一刻比 / 没设过期≠永不过期 /"
	@echo "   候选角色里得真有人能审,否则请求建出来就没人能批而列表上看着正常)"
	@./.venv/bin/python tests/orchestration/test_approvals.py
	@echo ""
	@echo "▸ 评测判断:**防泄漏 / 可比性 / 没打分不参与平均**(四件坏法都不报错)"
	@echo "  (同一组样本跨分集 → 分数虚高而每一步看起来都正常)"
	@./.venv/bin/python tests/orchestration/test_evals.py
	@echo ""
	@echo "▸ 脱敏:**形状不是截断** —— 截到 100 字,那 100 字仍然是原文"
	@echo "  (而原文第一句往往正是最敏感的那句:客户姓名、订单号通常在开头)"
	@./.venv/bin/python tests/orchestration/test_redact.py
	@echo ""
	@echo "▸ 用量折账:**没有价目表时 token 已知、金额未知** —— 不编单价,也不写 0"
	@echo "  (认不出的用量档要报出来:供应商加一档新计费,它的 token 一分钱都不会被算进来)"
	@./.venv/bin/python tests/orchestration/test_usage.py
	@echo ""
	@echo "▸ 答案缓存键:**缺一个字段要抛,绝不拿空串顶**(缓存规格 §10.1 / 附录 A-2)"
	@echo "  两次都缺同一个字段时,它们会算出**同一个键** —— 于是跨版本、跨身份复用了答案"
	@echo "  ⚠️ 16 个必填字段**逐个**改一个值、断键必须变(不是抽查 ——"
	@echo "     一条只抽查了三个字段的判据,和一条全验了的,在绿勾上长得一模一样)"
	@./.venv/bin/python tests/orchestration/test_cache_key.py
	@echo ""
	@echo "▸ 缓存指标:**分母为 0 是「不适用」,不是 0%**;未知不当 0(规格 §17.2 / A-8)"
	@echo "  ⚠️ 每条都对着一种会算出**假收益**的方式。这个仓库真栽过一次:"
	@echo "     报「开筛选省 71%」,真因是基线臂在写缓存、对照臂吃热缓存 —— 真数 12%"
	@./.venv/bin/python tests/orchestration/test_cache_metrics.py
	@echo ""
	@echo "▸ 缓存答案还能用吗:**撤权后不等物理删除**、代次判完全相等、过期是严格小于"
	@echo "  ⚠️ 这一族 bug 的共同点是**答案还在,而它已经不该被返回了** ——"
	@echo "     而一条不该返回的答案,和一条正常的答案,**在内容上长得一模一样**"
	@./.venv/bin/python tests/orchestration/test_cache_usable.py
	@echo ""
	@echo "▸ 这是哪一件事:额度算在谁头上 —— **模型声称「这是新任务」不算**"
	@echo "  业务拍板(10-04):自动按客户切 + 顾问能手动开新;打架时手动赢,而**手动不永久**"
	@echo "  ⚠️ 额度耗尽会疼,所以一定有一股力气想绕过它 —— 最便宜的绕法就是换个任务编号:"
	@echo "     一个「模型声称是新任务」而被当真的,和一个顾问真开了新任务的,"
	@echo "     **在那个新任务编号上长得一模一样**(规格 §5.1 / §D.1 / C48)"
	@./.venv/bin/python tests/orchestration/test_task_identity.py
	@echo ""
	@echo "▸ 这次用哪一版策略:**拒绝启动,而不是回退成「没有限制」**"
	@echo "  ⚠️ 最容易写出来的恰恰是那一行 \'策略 = 拉配置() or 默认不限制\':"
	@echo "     一个「配置服务挂了所以没限制」的运行,和一个「真被授权不限制」的,"
	@echo "     **在那次运行上长得一模一样**(规格 §4.3)"
	@echo "  有发布 ≠ 已加载(§9.2)· 哈希不符是**冲突**不是没切过去(§10.3)·"
	@echo "  回执会陈旧(§10.2)· 硬限制「**没核查过**」不算支持"
	@echo "▸ 把草稿冻成一版策略:**拼错的键和布尔值不许冻进去**"
	@echo "  ⚠️ 两种最毒的放过法:"
	@echo "     · 拼错键名(\'tool_attemps_cap\')→ 执行层读不到,"
	@echo "       **那个保护从来没生效过,而页面上填着数**"
	@echo "     · 写 \'true\' → Python 里 True == 1,于是"
	@echo "       **一条上限 1 次的策略,和一条写着 true 的,在执行时长得一样**"
	@echo "  哈希只覆盖影响行为的字段(改备注不出新版本)· 复用缓存那个规范化器"
	@echo "  (\'0\' / \'null\' / \'false\' 折出来必须不一样)"
	@./.venv/bin/python tests/orchestration/test_policy_freeze.py
	@echo ""
	@echo "▸ 实例回执可信吗:**哈希对不上是「冲突」,不是「以回执为准」**"
	@echo "  ⚠️ 实例说「我加载了这一版」—— **它说的话不等于事实**:"
	@echo "     一条「我加载了这一版」而内容其实不是的回执,和一条真实的,"
	@echo "     **在那张「实例已加载」的表上长得一模一样**(规格 §10.3)"
	@echo "  loaded_at 服务端盖(实例时钟不对会让回执永不过期)· 能力三态"
	@echo "  (「没报」不是「不支持」)· 能力不够**不在收回执时拒绝**"
	@echo "  ⚠️ 还验**共用真的发生了**:'策略解析' 与它是同一份陈旧判据"
	@echo "     (第一版各写了一遍,而注释里恰好写着「两处各写一遍迟早分叉」)"
	@./.venv/bin/python tests/orchestration/test_receipt_verify.py
	@echo ""
	@echo "▸ 这次运行实际采用了什么:**存快照本身,不只是那个外键**"
	@echo "  ⚠️ 环境指针是可改的 —— 只存外键的话指针一变,"
	@echo "     **历史运行会跟着改口**说自己当时用的是新版:"
	@echo "     一个事后跟着指针漂的「当时用的策略」,和一个真记下来的,"
	@echo "     **在那一栏上长得一模一样**(规格 §4.2 第 ④ 行)"
	@echo "  来源三种(采用/回退/继承前段)· 回退要看得出来 ·"
	@echo "  续跑段**继承不重装**(同一任务固定快照)· 拒绝启动的不配快照"
	@./.venv/bin/python tests/orchestration/test_adopt_snapshot.py
	@echo ""
	@./.venv/bin/python tests/orchestration/test_policy_resolve.py
	@echo ""
	@echo "▸ 没有任何已发布策略时用哪套上限(业务 2026-10-06 拍的:**内置兜底**)"
	@echo "  ⚠️ 判据是**消掉「无限制」这个档**:"
	@echo "     一个「没有策略所以不限制」的运行,和一个「策略说了不限制」的,"
	@echo "     **在运行记录上长得一模一样**"
	@echo "  数字来自规格 §5.3(「可替换的测试起点,**不是当前生产配置**」)·"
	@echo "  只填**真有执行点**的键(拿 exec_limits_report 的登记表现查对账)·"
	@echo "  兜底**不是回退**(回退要带版本/年龄/原因/有效期,兜底一样都没有)"
	@./.venv/bin/python tests/orchestration/test_backstop_limits.py
	@echo ""
	@echo "▸ 这次运行**真正生效**的上限是哪几个数,每个数从哪来"
	@echo "  两个地方在说同一件事:执行策略(组织护栏)和 Agent 自己的 limits ——"
	@echo "  **两边都有时取更严的那个**,而且**来源必须报出来**:"
	@echo "     一个「被组织策略拦住」的运行,和一个「Agent 自己配得严才没跑飞」的,"
	@echo "     **在那次停下来上长得一模一样**"
	@echo "  ⚠️ 0 不是「无限制」· 两边都没有就抛(不兜底)· 布尔判在整数之前 ·"
	@echo "  ⚠️ 新口径直接抛 —— **不拿一个计数器冒充两个**(规格 §5.2)"
	@./.venv/bin/python tests/orchestration/test_effective_caps.py
	@echo ""
	@echo "▸ 这段语料这个人能不能**检索到**(规格 §18「文档父级权限可收紧」)"
	@echo "  业务 2026-10-07 拍的:**切片级不做** —— 切片是派生物,重建索引就整批重切,"
	@echo "  权限绑在它上面会静默失效;要收紧就**拆成独立文档**(业界也停在文档级)"
	@echo "  ⚠️ ACL 存**角色**不存人(调岗只改 memberships,不用重写任何 ACL)·"
	@echo "  ⚠️ 空 ACL 是「没说过」不是「没有人」(五种空写法都验了)·"
	@echo "  ⚠️ 只能收紧不能放宽,拒的时候要说清**被哪一级卡住、多出来的是谁**"
	@echo "  🔑 而主要理由是第 ⑥ 节:**where 片段和纯判定要给出同一份名单** ——"
	@echo "     一份 SQL 过滤和一份纯判定,在各自的测试里都绿,而它们可以给出不同的名单"
	@./.venv/bin/python tests/orchestration/test_corpus_visible.py
	@echo ""
	@echo "▸ 拆成独立文档:**切片级权限不做**那一拍,代价全压在这个动作上"
	@echo "  ⚠️ 原切片**一条都不动** —— chunks 不可变且绑在不可变的文档版本上,"
	@echo "     改归属就把已建索引、已发生的问答留下的证据链一起指向了新内容"
	@echo "  ⚠️ 搬过去的片段**沿用源片段记的切片器版本**,不读当前常量 ——"
	@echo "     MIXED_CHUNKER_VERSION 是整个知识库一起查的:重切一遍,这个库从此建不出索引"
	@echo "  ⚠️ 新文档 ACL **必填写死**不许留空继承(它可能落在另一个库,上限就换了一个)"
	@echo "  ⚠️ 返回的是**计划 + 欠账**,没有任何能当「做完了」用的键 ——"
	@echo "     在役索引是快照,拆完那个人照旧检索得到,直到重建索引切换"
	@echo "  🔑 而主要理由是第 ⑥ 节:**不重不漏** —— 一次「拆走」和一次「复制过去而原文档也留着」,"
	@echo "     在新文档的片段列表上长得一模一样,而后者权限白收紧了"
	@./.venv/bin/python tests/orchestration/test_split_document.py
	@echo ""
	@echo "▸ 收资料:**只收「已校验」的上传** + 'object_key' 不知道是哪种键就当场抛"
	@echo "  (一列有两个含义而没人知道,比缺一列糟 —— 它会咬第一个想读原文的人)"
	@./.venv/bin/python tests/orchestration/test_ingest.py
	@echo ""
	@echo "▸ 上传校验:**校验真的调解析器** —— 自己发明一套判断,两套迟早不一致"
	@echo "  (松了→坏文件在库里是「已校验」,建索引时炸而错误指向解析器)"
	@./.venv/bin/python tests/orchestration/test_upload_rules.py
	@echo ""
	@echo "▸ 对象存储适配器:**键逃不出根目录**(用路径段比,startswith 会漏)+ 原子写"
	@echo "  它是 README 里「接 S3 时只换实现」那句话的唯一落地"
	@./.venv/bin/python tests/orchestration/test_storage.py
	@echo ""
	@echo "▸ 索引计划:检查点 + 输入指纹 —— **这一组的坏法全是不报错的**"
	@echo "  (跳过没向量的片段/在变过的输入上续做/从 20 个候选里挑 50 个)"
	@./.venv/bin/python tests/orchestration/test_index_plan.py
	@echo ""
	@echo "▸ Agent 与工具网关:**43 条对抗**(幻造工具名/参数越权/路径穿越/虚报完成/"
	@echo "  审批换参数/文档注入/崩溃后重复写)—— 真值落在**独立账本和独立文件系统**上"
	@./.venv/bin/python tests/orchestration/test_agent_tools.py
	@echo ""
	@echo "⚠️ 这一层跑的是**不接数据库、不接真模型**的那部分。"
	@echo "   它证明「图校验、执行语义和工具边界对」,**不证明接口和页面通**(那在 test-e2e)。"
	@echo "   还没落地:人工待办流程、Agent 配置页(见 contract/landing.py)。"
	@echo "   ⚠️ **这里原来有三行写死的进度,已经过期了,所以删掉**:"
	@echo "      它写着「Worker 的 index_build 处理器还没写」和「事务模型拦着检查点」——"
	@echo "      两件 09-27 都做完了。**跑完的检查末尾播一段过期的欠账,"
	@echo "      比不播糟**:它会让下一个人去做一件已经做完的事。"
	@echo "      要看还欠什么就跑 make progress(那份是生成的)。"

test-orchestration-e2e:   ## 编排端到端:建图 → 校验 → 试运行 → 冻结 → 发布
	@echo "❌ 未实现:执行链还没落地(规格 §18 的第 2—6 阶段)。" >&2
	@echo "   现在能跑的:make test-orchestration(契约 + 语义)。" >&2
	@echo "   **一个打印「完成」却什么都没跑的 target,比没有这个 target 糟得多。**" >&2
	@exit 1

test-orchestration-live:  ## 编排真实联调:真模型 + 真工具 + 真连接
	@echo "❌ 未实现:没有真实模型连接和工具授权。" >&2
	@echo "   规格 §18:「live 必须有真实连接和测试授权;**未配置则明确跳过," >&2
	@echo "   不能计入成功**」。" >&2
	@exit 1
