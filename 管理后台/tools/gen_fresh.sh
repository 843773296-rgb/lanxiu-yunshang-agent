#!/usr/bin/env bash
# 三个生成器都重跑一遍,然后**告诉你有没有东西变了**。
#
# ⚠️ **为什么要这个,而不是「记得跑 make gen」**
#
# 2026-09-28 CI 红了一次:改了 `entities.py`,跑了 `gen_openapi` 和
# `gen_ts_types`,**漏了 `gen_contract_doc`** —— 三个生成器记得两个。
# 而 `make gen` 一条命令就跑全三个,却手敲了两个。
#
# 判据那边是对的(`spec_coverage` 有「契约文档是最新的」,咬合也验过),
# 所以真正该改的不是加判据,是**让「改了契约却没重跑」在提交前就撞上**。
#
# ⚠️⚠️ **这个文件里的变量名一律 ASCII。** bash 不接受中文变量名 ——
# 写 `产物=(...)` 会当场 syntax error。今天这是第三次踩
# (前两次:tools/fetch_model.sh、CI 里的 `红=0`)。
# **本地是 zsh、CI 和脚本跑的是 bash,而 zsh 允许中文变量名** ——
# 「本地能跑」和「CI 能跑」的差别可以只是一个 shell。
#
# 用法(改完契约、提交之前):
#     ./tools/gen_fresh.sh          # 重跑 + 报告差异,有差异退非 0
#
# 退非 0 的意思是「**产物变了,记得一起提交**」,不是「出错了」——
# 这个区别写在输出里。
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
ARTIFACTS=(docs/契约.md packages/contracts/openapi.json packages/contracts/api.ts)

declare -a BEFORE
for f in "${ARTIFACTS[@]}"; do
  if [ -f "$f" ]; then BEFORE+=("$(shasum -a 256 "$f" | cut -d' ' -f1)")
  else BEFORE+=("missing"); fi
done

rc=0
for g in gen_contract_doc gen_openapi gen_ts_types; do
  # ⚠️ `|| rc=1` 不能省 —— 后面还有命令,不带它最后一条绿就把这条的红盖掉
  $PY "tools/$g.py" >/dev/null 2>&1 || { echo "  ❌ $g 跑挂了"; rc=1; }
done

CHANGED=()
for i in "${!ARTIFACTS[@]}"; do
  f="${ARTIFACTS[$i]}"
  if [ -f "$f" ]; then now="$(shasum -a 256 "$f" | cut -d' ' -f1)"; else now="missing"; fi
  # ⚠️ 比的是**内容哈希不是 mtime**:生成器每次都重写文件,mtime 一定变,
  # 而内容可能一个字节都没差 —— 按 mtime 判会每次都说「变了」,
  # 于是这条提示很快就被整体忽略。
  [ "$now" != "${BEFORE[$i]}" ] && CHANGED+=("$f")
done

if [ ${#CHANGED[@]} -eq 0 ]; then
  echo "✅ 三个生成器的产物都是最新的(契约文档 / OpenAPI / 前端 TS 类型)"
  exit $rc
fi
echo "⚠️ **产物变了,记得一起提交**(这不是出错):"
for f in "${CHANGED[@]}"; do echo "     $f"; done
echo "   漏提交的表现是 CI 红在「契约文档是最新的」,而本地是绿的 ——"
echo "   因为本地已经被这一次重跑改好了。"
exit 1
