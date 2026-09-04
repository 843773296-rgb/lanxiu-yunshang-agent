#!/bin/bash
# 一条命令跑完全部检查。任一失败即整体失败。
cd "$(dirname "$0")"
FAIL=0
run(){ printf "\n\033[1m▸ %s\033[0m\n" "$1"; shift
  if "$@" > /tmp/chk.out 2>&1; then
    tail -3 /tmp/chk.out | sed 's/^/  /'
  else
    FAIL=1; sed 's/^/  /' /tmp/chk.out; printf "  \033[31m✗ 失败\033[0m\n"
  fi }
run "数据层 · truth 表隔离"   python3 backend/selftest.py
run "状态流转引擎 · 17 个用例" python3 backend/fsm.py
run "写入校验规则 · 10 个用例" python3 backend/rules.py
run "控件审计 · 死控件检查"    python3 backend/ui_audit.py
run "遮蔽检查 · 局部变量压函数" python3 backend/shadow_check.py
run "商品库 · 不卖矩阵判不可的组合" python3 backend/catalog_check.py
run "会员与订单 · 映射/勾稽/门槛" python3 backend/member_order_check.py
run "运维平台 · 队列/时效/解析/置信度" python3 backend/ops.py
run "MCP · 两个服务连通性"      python3 mcp/selftest.py
run "MCP · 通道等价(不调模型)" python3 mcp/parity.py
run "V1 循环 · 离线自测"       python3 agent/offline_test.py
run "知识库 · 与 craft 表一致"  python3 knowledge/check_kb.py
run "相容矩阵 · 273 格推导/对账/落库" python3 knowledge/derive_combo.py
run "版型库与 BOM · 推档/裁片/物料对账" python3 knowledge/derive_pattern.py
run "量体推荐 · 三档判定/放松量/齐胸特例" python3 knowledge/fitting.py
run "工期推算 · 并行链路/除不动/婚礼倒推" python3 knowledge/leadtime.py
run "回答体检 · 人造用例(正反各半)" python3 agentsite/guards_test.py
run "Skill 与配置面 · 设置源放开后的锁" ./agentsite/.venv/bin/python agentsite/skills_check.py
run "判分器自测 · 18 条人造用例" python3 agent/chat_eval_judgetest.py
printf "\n%s\n" "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then printf "\033[32m✅ 全部检查通过\033[0m\n"; else printf "\033[31m❌ 存在失败项\033[0m\n"; fi
exit $FAIL
