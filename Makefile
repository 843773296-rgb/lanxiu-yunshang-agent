# AI 管理后台 · 开发接口(规格 §17.5)
#
# ⚠️ **还没实现的 target 一律报「未实现」并以非零退出。**
# 规格「实施必须遵守」第 2 条说的是按钮:「未接入能力明确显示未配置/不支持,
# 不能用 Toast 和假进度冒充执行」。同一条原则对 make target 成立 ——
# 一个打印「✅ 完成」却什么都没做的 target,比没有这个 target 糟得多:
# 它会让人以为这一步过了。
SHELL := /bin/bash
.PHONY: help bootstrap dev seed-demo test test-e2e test-live contract doctor migrate gen

help:
	@echo "可用:"
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

doctor:        ## 探本机依赖:PG / pgvector / Redis / Node / Python
	@bash tools/doctor.sh

contract:      ## 只跑契约覆盖检查(不需要数据库)
	@python3 tools/spec_coverage.py

bootstrap:     ## 装依赖 + 起基础服务 + 迁移
	@bash tools/bootstrap.sh

test:          ## 确定性单测与集成测试(**报实际跑了几项**)
	@python3 tools/spec_coverage.py
	@echo ""
	@echo "▸ 契约和库是否一致(alembic check)"
	@cd services/api && DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		../../.venv/bin/alembic check 2>&1 | tail -1
	@echo ""
	@echo "▸ 跨项目引用:**真的去攻击它**(5 次攻击 + 1 条正向对照 + 还原检查)"
	@DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		./.venv/bin/python tests/integration/test_project_isolation.py
	@echo ""
	@echo "⚠️ test 跑的是**不需要起服务**的那部分(契约层 + 数据层)。"
	@echo "   接口和页面的闭环在 make test-e2e(要先 make dev)。"
	@echo "   **两个都绿也不代表「系统可用」** —— Worker / 知识链 / 训练链 / 发布链"
	@echo "   都还没实现,见 README 的「现在做到哪了」。"

migrate:       ## 改了契约之后:生成迁移(需要 -m "说明")
	@test -n "$(m)" || { echo '要写说明:make migrate m="加了什么"' >&2; exit 1; }
	@cd services/api && DATABASE_URL="$${DATABASE_URL:-postgresql+psycopg://$$USER@localhost:5432/aimc_dev}" \
		../../.venv/bin/alembic revision --autogenerate -m "$(m)"

gen:           ## 重跑所有生成器(契约文档 + OpenAPI + 前端 TS 类型)
	@python3 tools/gen_contract_doc.py
	@python3 tools/gen_openapi.py
	@python3 tools/gen_ts_types.py

dev:           ## 起 API + 页面(http://127.0.0.1:8801)
	@bash tools/dev.sh

seed-demo:
	@echo "❌ 未实现:还没有数据模型迁移,没法灌演示数据(§17.4 第 2 步)。" >&2
	@exit 1

test-e2e:      ## 端到端:接口闭环 + 禁止行为 + 三页页面冒烟(要先 make dev)
	@echo "▸ 接口闭环与**禁止行为**(35 条:跨项目、权限、乐观锁、幂等、脱敏、未知费用)"
	@./.venv/bin/python tests/e2e/test_api_flow.py
	@echo ""
	@echo "▸ 页面冒烟:用最小 DOM 桩**真跑加载路径**(不是只看语法)"
	@for h in '#/workbench' '#/prompts' '#/runs'; do \
		printf "  %-14s " "$$h"; node tests/e2e/page_smoke.js "$$h" 2>&1 | tail -1; done
	@echo ""
	@echo "⚠️ 页面冒烟跑的是**加载路径**,不是视觉 —— 它证明「取到数并渲染了」,"
	@echo "   不证明「排版对」。视觉要人打开 http://127.0.0.1:8801 看。"

test-live:
	@echo "❌ 未实现:外部调用还没接。**缺资源要报告跳过,不算通过**(§17.5)。" >&2
	@exit 1
