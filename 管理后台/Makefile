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
.PHONY: help bootstrap dev seed-demo test test-e2e test-live contract doctor migrate gen worker worker-once progress \
        test-orchestration test-orchestration-e2e test-orchestration-live

help:
	@echo "可用:"
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

doctor:        ## 探本机依赖:PG / pgvector / Redis / Node / Python
	@bash tools/doctor.sh

contract:      ## 只跑契约覆盖检查(不需要数据库)
	@./.venv/bin/python tools/spec_coverage.py

bootstrap:     ## 装依赖 + 起基础服务 + 迁移
	@bash tools/bootstrap.sh

test:          ## 确定性单测与集成测试(**报实际跑了几项**)
	@./.venv/bin/python tools/spec_coverage.py
	@echo ""
	@echo "▸ 契约和库是否一致(alembic check)"
	@cd services/api && DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		../../.venv/bin/alembic check 2>&1 | tail -1
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
	@echo "  ⚠️ 要模型文件:`bash tools/fetch_model.sh`(96 MB,不进 git)"
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
	@echo "▸ 检索链:召回 → 截断 → 证据链(`要精排=False`,**不花 API 额度**)"
	@echo "  精排的**判据**在编排层(零依赖),精排的**效果**在 make test-live ——"
	@echo "  **只有第三层要花钱,而前两层覆盖了绝大部分会坏的地方**"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_retrieval.py
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

test-e2e:      ## 端到端:接口闭环 + 禁止行为 + 页面冒烟(要先 make dev)
	@echo "▸ 接口闭环与**禁止行为**(44 条:跨项目、权限、乐观锁、幂等、脱敏、未知费用)"
	@./.venv/bin/python tests/e2e/test_api_flow.py
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
	@echo "▸ 应用与发布端到端(§17.4-9):**「哪一版在给用户跑」**"
	@echo "  (清单全是确切版本 / 生产只认审过的 / 指针原子 / 回滚是新动作不是改历史)"
	@./.venv/bin/python tests/e2e/test_release_flow.py
	@echo ""
	@echo "▸ 微调训练链端到端(§17.4):**四个状态之间的三道边界**"
	@echo "  (训练完成 → 有产物 → 产物可用 → 在服务用户;合成任意两个,界面上看起来都正常)"
	@echo "  ⚠️ 要先 python3 tools/seed_training.py —— 它会补一个 trainer,"
	@echo "     没有他这一组**一条都跑不起来**(demo 项目原来一个 trainer 都没有)"
	@./.venv/bin/python tools/seed_training.py > /dev/null
	@./.venv/bin/python tests/e2e/test_training_flow.py
	@echo ""
	@echo "▸ 交割四条接口(调用链详情 / A3 接收端 / 实验对比 / 人工待办)"
	@echo "  **「验过」= 有可重跑的断言打过,不是「有人手工 curl 过一次」** —— 这一份补的正是那笔虚账"
	@./.venv/bin/python tests/e2e/test_handover_flow.py
	@echo ""
	@echo "▸ 数据集与训练导出端到端(§17.4 微调链前半段):**七道闸,每道一条**"
	@echo "  (过完闸一条不剩 → 422 而不是 200+空文件;声明了要脱而脱敏器没选型 → 不给不脱的版本)"
	@echo "  ⚠️ 要先 python3 tools/seed_datasets.py 铺那六份「每份专考一道闸」的数据集"
	@./.venv/bin/python tests/e2e/test_datasets_flow.py
	@echo ""
	@echo "▸ 文件上传端到端:**「上传成功不等于内容可用」有代码兜着**(§17.1)"
	@echo "  (已上传的 能引用吗=false / 坏文件是 200+通过=false / 校验失败是终态)"
	@./.venv/bin/python tests/e2e/test_upload_flow.py
	@echo ""
	@echo "▸ 页面冒烟:用最小 DOM 桩**真跑加载路径**(不是只看语法)"
	@for h in '#/workbench' '#/prompts' '#/runs' '#/workflows' '#/uploads' '#/kb' '#/retrieval' '#/usage' '#/traces' '#/health' '#/tryout' '#/evals' '#/compare' '#/human'; do \
		printf "  %-14s " "$$h"; node tests/e2e/page_smoke.js "$$h" 2>&1 | tail -1; done
	@echo ""
	@echo "▸ 画布页:**结构对账**(节点数/连线数/「加入」按钮数 vs 接口返回的定义)"
	@W=$$(./.venv/bin/python -c "import json,urllib.request as u; \
		r=u.Request('http://127.0.0.1:8801/api/v1/projects/project_demo_a/workflows', \
		headers={'X-Dev-User':'U002'}); d=json.load(u.urlopen(r)); \
		print(d['items'][0]['id'] if d['items'] else '')" 2>/dev/null); \
	  if [ -n "$$W" ]; then node tests/e2e/page_smoke.js "$(HASH)/workflow/$$W" 2>&1 | tail -2; \
	  else echo "  ⚠️ 演示库里没有工作流 —— 先 make seed-demo 或在页面上建一个。"; \
	       echo "     **这不叫通过,这叫没测到**"; exit 1; fi
	@echo ""
	@echo "▸ Agent 配置页:**结构对账**(连接下拉框项数 + 能力那一栏)"
	@A=$$(./.venv/bin/python -c "import json,urllib.request as u; \
		r=u.Request('http://127.0.0.1:8801/api/v1/projects/project_demo_a/agents', \
		headers={'X-Dev-User':'U002'}); d=json.load(u.urlopen(r)); \
		print(d['items'][0]['id'] if d['items'] else '')" 2>/dev/null); \
	  if [ -n "$$A" ]; then node tests/e2e/page_smoke.js "$(HASH)/agent/$$A" 2>&1 | tail -2; \
	  else echo "  ⚠️ 演示库里没有 Agent —— 在页面上建一个。**这不叫通过,这叫没测到**"; \
	       exit 1; fi
	@echo ""
	@for h in '#/agents' '#/tools'; do \
		printf "  %-12s " "$$h"; node tests/e2e/page_smoke.js "$$h" 2>&1 | tail -1; done
	@echo ""
	@echo "⚠️ 页面冒烟跑的是**加载路径**,不是视觉 —— 它证明「取到数并渲染了」,"
	@echo "   不证明「排版对」。视觉要人打开 http://127.0.0.1:8801 看。"

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
	@./.venv/bin/python tests/e2e/test_release_flow.py > /tmp/prog-test_release_flow.log 2>&1 \
	  || { echo "  ❌ test_release_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_release_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_release_flow.log
	@./.venv/bin/python tools/seed_training.py > /tmp/prog-seedtr.log 2>&1 \
	  || { echo "  ❌ 铺训练夹具挂了"; tail -12 /tmp/prog-seedtr.log; exit 1; }
	@./.venv/bin/python tests/e2e/test_training_flow.py > /tmp/prog-test_training_flow.log 2>&1 \
	  || { echo "  ❌ test_training_flow 挂了 —— 报告不许在它没跑完的情况下生成:"; \
	       tail -24 /tmp/prog-test_training_flow.log; exit 1; }
	@tail -2 /tmp/prog-test_training_flow.log
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
	@echo "  踩过三次,其中一次在**全绿时完全看不出来**:`红=0` 被当成命令,"
	@echo "  `$$红` 展开成空,exit 拿不到数字退 255 —— 而红的理由完全指错方向"
	@./.venv/bin/python tools/shell_lint.py
	@echo ""
	@echo "▸ 敏感信息检测覆盖:**漏检和误拦分开报**(用户 2026-09-28 要求)"
	@echo "  合成一个准确率等于让一次泄露和一条样本互相抵消 —— 两种错的代价完全不对称"
	@echo "  ⚠️ 已知盲区内的漏检**不计入红**,但逐条列出来:盲区是待办,不是免责声明"
	@./.venv/bin/python tools/redact_coverage.py
	@echo ""
	@echo "▸ SQL 列名体检:**问 information_schema,不猜列名**"
	@echo "  (同一天栽了四次「没查就写 SQL」:三次猜类型、一次猜列名)"
	@./.venv/bin/python tools/sql_columns_check.py
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
	@echo "▸ 收资料:**只收「已校验」的上传** + `object_key` 不知道是哪种键就当场抛"
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
