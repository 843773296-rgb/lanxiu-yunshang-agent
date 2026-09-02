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
run "V1 循环 · 离线自测"       python3 agent/offline_test.py
run "知识库 · 与 craft 表一致"  python3 knowledge/check_kb.py
run "判分器自测 · 18 条人造用例" python3 agent/chat_eval_judgetest.py
printf "\n%s\n" "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then printf "\033[32m✅ 全部检查通过\033[0m\n"; else printf "\033[31m❌ 存在失败项\033[0m\n"; fi
exit $FAIL
