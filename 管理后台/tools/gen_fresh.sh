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

# ⚠️ 生成器的名字**从磁盘读,不在这里拄第二份**。
#
# 上一版把三个名字写死在 for 里。并行会话 2026-09-28 在 `nav_check`
# 里找到的那条正好打在这上面:那条守卫判的是「顶栅 ∩ 已移交表」,
# 表被清空之后变成 `空集 ∩ 任何集合 = 空` —— **从此不可能红,
# 而清单上它仍是一行 ✅**。他的说法:「一个信号承载零个含义时,
# 它也不再是判据了 —— 而后者在清单上是绿的,更难发现。」
#
# 这个脚本原来正是那个形状:清单空了就**跑 0 个生成器然后打印绿**。
# 改成从 `tools/gen_*.py` 现扫(和 `check_zero_dep.py` 从 CI 配置读清单同一个理由),
# 并且**扫到少于 3 个当场红** —— 在错的目录下跑也会被这条拒掩。
GENS=()
for gp in tools/gen_*.py; do [ -f "$gp" ] && GENS+=("$gp"); done
if [ "${#GENS[@]}" -lt 3 ]; then
  echo "  ❌ 只扫到 ${#GENS[@]} 个生成器(tools/gen_*.py),少于 3 个"
  echo "     空清单会让这个脚本跑 0 个生成器然后打印绿 —— 那正是它要防的事"
  exit 1
fi

# ⚠️ **两张清单的长短要对得上。** 每个生成器至少写一份产物,
# 所以产物数不得少于生成器数。不加这一条的话,新增一个
# `gen_sdk.py` 而忘了把它的产物加进 ARTIFACTS —— 生成器会被跑到,
# **但它的产物变没变没人看**,而这正是这个脚本存在的理由。
if [ "${#ARTIFACTS[@]}" -lt "${#GENS[@]}" ]; then
  echo "  ❌ ${#GENS[@]} 个生成器但只盯住 ${#ARTIFACTS[@]} 份产物"
  echo "     新增的生成器会被跑到,但它写的文件变没变没人看"
  echo "     生成器:${GENS[*]}"
  exit 1
fi

rc=0
for gp in "${GENS[@]}"; do
  # ⚠️ `|| rc=1` 不能省 —— 后面还有命令,不带它最后一条绿就把这条的红盖掉
  $PY "$gp" >/dev/null 2>&1 || { echo "  ❌ $gp 跑挂了"; rc=1; }
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
  # ⚠️ **生成器跑挂了的时候不许打印 ✅。**
  # 上一版无条件印「产物都是最新的」然后 `exit $rc` ——
  # 三个生成器全挂也这么印(本次咕合里真碰到了)。
  # 退出码是对的,**但输出说绿** —— 而人读的是输出。
  # 这正是仓库里那条「判绿看退出码,别数输出里的 ❌」的反面:
  # 输出和退出码反了的时候,两边都不能信 —— 该做的是让它们一致。
  # 数字也不写死了:清单现扫了而这句还写「三个」,加一个生成器就漂。
  if [ "$rc" -ne 0 ]; then
    echo "❌ 有生成器跑挂了 —— 产物没变不能当成「最新」(它根本没被重写)"
    exit $rc
  fi
  echo "✅ ${#GENS[@]} 个生成器的产物都是最新的(${ARTIFACTS[*]})"
  exit 0
fi
echo "⚠️ **产物变了,记得一起提交**(这不是出错):"
for f in "${CHANGED[@]}"; do echo "     $f"; done
echo "   漏提交的表现是 CI 红在「契约文档是最新的」,而本地是绿的 ——"
echo "   因为本地已经被这一次重跑改好了。"
exit 1
