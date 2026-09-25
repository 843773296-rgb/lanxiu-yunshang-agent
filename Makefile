# AI 管理后台 · 开发接口(规格 §17.5)
#
# ⚠️ **还没实现的 target 一律报「未实现」并以非零退出。**
# 规格「实施必须遵守」第 2 条说的是按钮:「未接入能力明确显示未配置/不支持,
# 不能用 Toast 和假进度冒充执行」。同一条原则对 make target 成立 ——
# 一个打印「✅ 完成」却什么都没做的 target,比没有这个 target 糟得多:
# 它会让人以为这一步过了。
SHELL := /bin/bash
.PHONY: help bootstrap dev seed-demo test test-e2e test-live contract doctor

help:
	@echo "可用:"
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

doctor:        ## 探本机依赖:PG / pgvector / Redis / Node / Python
	@bash tools/doctor.sh

contract:      ## 只跑契约覆盖检查(不需要数据库)
	@python3 tools/spec_coverage.py

bootstrap:     ## 装依赖 + 起基础服务 + 迁移
	@bash tools/bootstrap.sh

test:          ## 确定性单测与集成测试
	@python3 tools/spec_coverage.py
	@echo ""
	@echo "⚠️ 目前只有【契约层】有测试。API / Worker / Web 还没实现,"
	@echo "   所以 test 不代表「系统可用」—— 见 README 的「现在做到哪了」。"

dev:
	@echo "❌ 未实现:API / Web / Worker 还没建(规格 §17.4 第 3–5 步)。" >&2
	@echo "   现在能跑的是 make contract 和 make doctor。" >&2
	@exit 1

seed-demo:
	@echo "❌ 未实现:还没有数据模型迁移,没法灌演示数据(§17.4 第 2 步)。" >&2
	@exit 1

test-e2e:
	@echo "❌ 未实现:没有页面可跑端到端(§17.4 第 3 步之后)。" >&2
	@exit 1

test-live:
	@echo "❌ 未实现:外部调用还没接。**缺资源要报告跳过,不算通过**(§17.5)。" >&2
	@exit 1
