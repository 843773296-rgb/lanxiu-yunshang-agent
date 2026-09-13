#!/bin/bash
# 把所有评测跑一遍,汇总到一张表。
#
# **默认用 Claude**(月租,不花钱)—— 这是改动之后的**回归验证**,
# 不是对外报数的正式评测。正式评测要用产品真实在用的那个供应商
# (`LANXIU_PROVIDER=deepseek`,按量计费)。
#
# 用法: ./tools/run_evals.sh [输出目录]
cd "$(dirname "$0")/.."
OUT="${1:-/tmp/evals}"
mkdir -p "$OUT"
PY=./agentsite/.venv/bin/python
export LANXIU_PROVIDER="${LANXIU_PROVIDER:-claude}"
echo "供应商: $LANXIU_PROVIDER   输出: $OUT"
for f in agent/chat_eval.py agent/tool_eval.py agent/growth_eval.py \
         agent/vision_eval.py agent/liability_eval.py agent/ops_eval.py \
         agent/report_eval.py agent/member_eval.py agent/role_eval.py; do
  n=$(basename "$f" .py)
  echo "▸ $n"
  $PY "$f" > "$OUT/$n.txt" 2>&1
  tail -3 "$OUT/$n.txt" | sed 's/^/    /'
done
echo "════════ 汇总 ════════"
for f in "$OUT"/*.txt; do
  printf "%-20s %s\n" "$(basename "$f" .txt)" \
    "$(grep -oE '通过 [0-9]+/[0-9]+|[0-9]+/[0-9]+ 条' "$f" | tail -1)"
done
