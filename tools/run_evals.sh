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
# ⚠️ **抓不到分数要显式说「抓不到」,不能显示空白。**
# 第一版只认「通过 x/y」,而 chat_eval 打的是「总命中 x/y」——
# 汇总那一行就是**空的**,看起来像「这套没跑」而不是「格式没对上」。
# **一个空白和一个零分长得一样**,而它俩是两回事。
BAD=0
for f in "$OUT"/*.txt; do
  n=$(basename "$f" .txt)
  s=$(grep -oE '通过 [0-9]+/[0-9]+|总命中 [0-9]+/[0-9]+' "$f" | tail -1)
  if [ -z "$s" ]; then s="⚠️ 抓不到分数(格式没对上,去看 $f)"; BAD=1; fi
  printf "%-20s %s\n" "$n" "$s"
done
[ "$BAD" = 1 ] && echo "⚠️ 有评测的分数没抓到 —— **空白不等于零分**,去看对应的原始输出"
exit 0
