#!/bin/bash
# 文档同步(执行手册 W32 里叫 `make sync`;根目录没有 Makefile,做成脚本):把「从代码 / 库现生成」的几份文档一次全刷,
# 再跑一遍它们各自的对账。CI 红的一大半是这些对账(体检报告 E §6.4)—— 改了口径忘了重新生成,门禁才告诉你。
#
#     ./tools/sync_docs.sh          # 全刷 + 对账
#     ./tools/sync_docs.sh --只对账  # 不写文件,只跑各自的 --check(和门禁一样)
#
# 顺序和为什么:
#   ① 待办清单(tools/make_todo.py,从 intent/ 生成)
#   ② 产品说明里的 MCP 工具表(gen_doc_lists.py --写;默认只对账,--写 才动文档 —— 它曾把人手写的话原样覆盖掉)
#   ③ README = 入口 + 产品说明全文(make_readme.py;用户 10-20 拍「产品文档放进 README、去重」)—— 要在 ② 之后,它抄产品说明
#   ④ 运营 SOP(make_sop.py)
#   ⑤ 对账:doc_numbers_check(写死的数字)、make_readme --check、make_sop --check、gen_doc_lists(默认对账)
# 影响面基线(impact.py)不在这里:它的「警示段落下限」是棘轮,要人看着数字改,不该被脚本顺手推。
# 退出码:哪一步非 0 就记下来,最后一起报,**不吞**。
set -u
cd "$(dirname "$0")/.." || exit 2
R=$'\033[31m'; G=$'\033[32m'; D=$'\033[0m'
CHECK_ONLY=0; [ "${1:-}" = "--只对账" ] && CHECK_ONLY=1
REDS=()
step() { local name="$1"; shift; printf '\n▸ %s\n' "$name"; "$@"; local rc=$?; [ "$rc" = 0 ] || REDS+=("$name(rc=$rc)"); return 0; }

if [ "$CHECK_ONLY" = 0 ]; then
  step "① 待办清单重生成"            python3 tools/make_todo.py
  step "② 产品说明里的工具表重写"    python3 tools/gen_doc_lists.py --写
  step "③ README 重生成"            python3 tools/make_readme.py
  step "④ 运营 SOP 重生成"          python3 tools/make_sop.py
fi
step "⑤ 对账:文档数字"             python3 tools/doc_numbers_check.py
step "⑤ 对账:README 与产品说明"    python3 tools/make_readme.py --check
step "⑤ 对账:运营 SOP"             python3 tools/make_sop.py --check
step "⑤ 对账:工具表"               python3 tools/gen_doc_lists.py

echo
if [ "${#REDS[@]}" = 0 ]; then
  echo "${G}✅ 文档同步:生成和对账都过${D}"; exit 0
fi
echo "${R}❌ 文档同步有 ${#REDS[@]} 步没过:${REDS[*]}${D}"; exit 1
