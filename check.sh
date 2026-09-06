#!/bin/bash
# 一条命令跑完全部检查。任一失败即整体失败。
cd "$(dirname "$0")"
FAIL=0
# .pyc 缓存的坑,踩过两次,**两次是同一个坑的两半**:
#
#   第一半(不写):咬合测试把某个模块改坏又在**同一秒内**改回来,而文件大小正好没变 ——
#     CPython 判断缓存是否失效看的就是 (源文件 mtime 秒数, 大小),两个都没变就直接用旧的 .pyc。
#     结果检查跑的是被改坏的那一版,红得莫名其妙。
#
#   第二半(不读):上面那行 `PYTHONDONTWRITEBYTECODE=1` 只阻止**写**,不阻止**读**。
#     修好 textmatch.py 的否定作用域之后,上一次留下的旧 .pyc 还在,于是 V2 的文本判分
#     一直是 32/40 —— **源码是对的,跑的是旧字节码**。查了半天差点去怀疑判分逻辑。
#
# 「防止产生」和「防止使用」是两件事。两半都要堵:先清干净,再禁止写。
find . -name __pycache__ -type d -not -path './agentsite/.venv/*' -exec rm -rf {} + 2>/dev/null
export PYTHONDONTWRITEBYTECODE=1
run(){ printf "\n\033[1m▸ %s\033[0m\n" "$1"; shift
  if "$@" > /tmp/chk.out 2>&1; then
    tail -3 /tmp/chk.out | sed 's/^/  /'
  else
    FAIL=1; sed 's/^/  /' /tmp/chk.out; printf "  \033[31m✗ 失败\033[0m\n"
  fi }
run "数据层 · truth 表隔离"   python3 backend/selftest.py
run "边界审计 · 每条保证真的攻击一次" python3 backend/boundary_audit.py
run "提示词 · 单一源头与按工具装配" python3 tools/prompts_check.py
run "生命周期口径 · 自测" python3 knowledge/lifecycle.py
run "会员生命周期 · 14 条边界标注对账" python3 backend/member_check.py
run "交接文档 · 四段必填是否齐全" python3 tools/make_handoff.py --check
run "状态流转引擎 · 17 个用例" python3 backend/fsm.py
run "写入校验规则 · 10 个用例" python3 backend/rules.py
run "控件审计 · 死控件检查"    python3 backend/ui_audit.py
run "页面内联 JS · 语法(重复声明/括号)" python3 agentsite/js_check.py
run "遮蔽检查 · 局部变量压函数" python3 backend/shadow_check.py
run "商品库 · 不卖矩阵判不可的组合" python3 backend/catalog_check.py
run "会员与订单 · 映射/勾稽/门槛" python3 backend/member_order_check.py
run "运维平台 · 队列/时效/解析/置信度" python3 backend/ops.py
run "售后判责 · 返修判定表/证据不足不硬判" python3 knowledge/liability.py
run "售后判责 · 标注与规则对账/规则覆盖" python3 backend/liability_check.py
run "MCP · 三个服务连通性"      python3 mcp/selftest.py
run "MCP · 通道等价(不调模型)" python3 mcp/parity.py
run "V1 循环 · 离线自测"       python3 agent/offline_test.py
run "V2 工作流 · 40 条工单纯规则(不调模型)" python3 agent/v2.py
run "记录仪覆盖 · 每个调模型的地方都接了" python3 agent/trace_check.py
run "知识库 · 与 craft 表一致"  python3 knowledge/check_kb.py
run "相容矩阵 · 2025 格推导/对账/落库" python3 knowledge/derive_combo.py
run "版型库与 BOM · 推档/裁片/物料对账" python3 knowledge/derive_pattern.py
run "量体推荐 · 三档判定/放松量/齐胸特例" python3 knowledge/fitting.py
run "成长推算 · 百分位/靶身高/复量周期" python3 knowledge/growth.py
run "用户生命周期 · 着装人/家庭/同意/过期量体" python3 backend/lifecycle_check.py
run "数据规范 · 身份/关联/覆盖(对照 数据规范.md)" python3 backend/spec_check.py
run "假数据工厂 · 推断/生成/闸门/灌回滚(24 项)" python3 fakedata/selftest.py
run "钉死的锚点 · 抓同源谬误(手抄不现算)" python3 knowledge/pinned_check.py
run "产能排期 · 工种/一人一机/产能缺口" python3 knowledge/capacity.py
run "工期推算 · 并行链路/除不动/婚礼倒推" python3 knowledge/leadtime.py
run "回答体检 · 人造用例(正反各半)" python3 agentsite/guards_test.py
run "Skill 与配置面 · 设置源放开后的锁" ./agentsite/.venv/bin/python agentsite/skills_check.py
run "中文否定与子串 · 19 条(八次踩过的坑)" python3 agent/textmatch.py
run "判分器自测 · 18 条人造用例" python3 agent/chat_eval_judgetest.py
run "工具评测判分器 · 21 条对照用例" python3 agent/tool_eval_judgetest.py
run "成长评测判分器 · 22 条对照用例" python3 agent/growth_eval_judgetest.py
run "识图判分器 · 13 条对照用例" python3 agent/vision_eval_judgetest.py
run "判责判分器 · 14 条对照用例" python3 agent/liability_eval_judgetest.py
run "野外巡检 · 指纹粒度与行为观测" python3 agent/wild_run.py --selftest
run "野外语料 · 多样性(够多≠够杂)" python3 agent/wild_corpus.py --selftest
printf "\n%s\n" "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then printf "\033[32m✅ 全部检查通过\033[0m\n"; else printf "\033[31m❌ 存在失败项\033[0m\n"; fi
exit $FAIL
