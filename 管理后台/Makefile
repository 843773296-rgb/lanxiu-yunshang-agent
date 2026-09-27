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
	@echo "▸ 页面冒烟:用最小 DOM 桩**真跑加载路径**(不是只看语法)"
	@for h in '#/workbench' '#/prompts' '#/runs' '#/workflows'; do \
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
	@lsof -ti:8801 | xargs kill -9 2>/dev/null || true
	@pkill -f "workers/worker.py" 2>/dev/null || true
	@sleep 2
	@AIMC_TRACE_ROUTES=/tmp/aimc-routes.log nohup bash tools/dev.sh > /tmp/devlog.txt 2>&1 & sleep 8
	@echo "▸ 跑端到端(它打过哪些路由,账本上说)"
	@./.venv/bin/python tests/e2e/test_api_flow.py 2>&1 | tail -2
	@./.venv/bin/python tests/e2e/test_orchestration_flow.py 2>&1 | tail -2
	@echo ""
	@echo "▸ 页面冒烟(它取哪些接口,也记在同一本账上)"
	@for h in '$(HASH)/workbench' '$(HASH)/prompts' '$(HASH)/runs' '$(HASH)/workflows' '$(HASH)/agents' '$(HASH)/tools'; do \
		node tests/e2e/page_smoke.js "$$h" >/dev/null 2>&1 || true; done
	@echo "▸ 生成报告"
	@AIMC_TRACE_ROUTES=/tmp/aimc-routes.log ./.venv/bin/python tools/progress_report.py
	@echo ""
	@echo "⚠️ 「验过」= 测试**真的打过这条路由**,不是「测试文件里提到过」。"
	@echo "   但**打过一次不等于断言对** —— 这份报告回答「有没有被碰过」,不回答「对不对」。"

test-orchestration:       ## 编排:契约覆盖 + DSL 语义(夹具驱动,不需要数据库)
	@./.venv/bin/python tools/spec_coverage.py
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
	@echo "   还没落地:人工待办流程、Agent 配置页;"
	@echo "   **检查点恢复只有判断那一半**(index_plan.py 决定跳过谁、要不要新建),"
	@echo "   Worker 的 index_build 处理器还没写 —— 判断对不代表恢复真跑得起来。"
	@echo "   (见 contract/landing.py:九个组件里落地了 6 个)。"

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
