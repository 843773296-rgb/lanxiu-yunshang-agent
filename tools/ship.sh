#!/bin/bash
# 发货(执行手册 W32,2026-11-17):把「推之前那套手工动作」固化成一个命令。
#
#     ./tools/ship.sh            # 挪开运行日志 → pre_push(全部走完并 push)→ 放回日志
#     ./tools/ship.sh --不推      # 同上,但门禁绿了不 push(由用户推时用)
#     ./tools/ship.sh --自测      # 只验这条链自己的判断(不碰 git、不跑门禁)
#
# 为什么要有它(每一条都是栽过的):
#   ① 三件运行日志(`.feynman/tool-eval.json` / `agentsite/evals/funnel.jsonl` / `agentsite/evals/skill_usage.jsonl`)
#      是**跟踪着的文件却被运行时一直写**:它们改了,pre_push 的「工作区干净 / 按改动重放咬合」就把它们算进改动。
#      规矩是谁都不 add(CLAUDE.md、memory 都记了),所以每次推之前要手工:挪走 → `git checkout --` → 推完放回。
#      手工做了十几次,漏放回一次运行态就丢一截 —— 这里用 trap 保证**不管门禁绿红、Ctrl-C 还是崩了,日志都放回去**。
#   ② 推的那条链本身在 `tools/pre_push.sh`(并行会话维护,这里不重写、只包一层):rebase 查、扫密钥、按改动重放咬合、
#      锁内全量门禁、推前再查 main。这里**不替它做任何一步**,只负责前后的日志进出。
#   ③ 退出码:只认 pre_push 自己的那一个,单独捞、单独印(`echo "$(date) $?"` 永远印 0 那一坑,CLAUDE.md 第 7 节 9)。
set -u
cd "$(dirname "$0")/.." || exit 2
R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; D=$'\033[0m'

LOGS=(".feynman/tool-eval.json" "agentsite/evals/funnel.jsonl" "agentsite/evals/skill_usage.jsonl")

if [ "${1:-}" = "--自测" ]; then
  # 自测:在一份临时 git 仓里造「跟踪着、又被改了」的三个文件,验 挪开→还原→放回 三步后内容一个字节不少
  T=$(mktemp -d) && cd "$T" && git init -q . && git -c user.email=a@a -c user.name=a commit -q --allow-empty -m 起点 --no-verify
  for f in "${LOGS[@]}"; do mkdir -p "$(dirname "$f")"; echo 原样 > "$f"; done
  git add -A . && git -c user.email=a@a -c user.name=a commit -q -m 跟踪 --no-verify
  for f in "${LOGS[@]}"; do echo 运行时写进来的 >> "$f"; done
  A=$(mktemp -d)
  for f in "${LOGS[@]}"; do mkdir -p "$A/$(dirname "$f")"; mv "$f" "$A/$f"; git checkout -q -- "$f"; done
  [ -z "$(git status --porcelain)" ] || { echo "${R}❌ 自测:挪开后工作区该是干净的${D}"; exit 1; }
  for f in "${LOGS[@]}"; do mv "$A/$f" "$f"; done
  for f in "${LOGS[@]}"; do grep -q 运行时写进来的 "$f" || { echo "${R}❌ 自测:$f 放回后少了运行时那一截${D}"; exit 1; }; done
  [ -n "$(git status --porcelain)" ] || { echo "${R}❌ 自测:放回后工作区该是脏的(运行态回来了)${D}"; exit 1; }
  echo "${G}✅ 自测:三件日志 挪开 → 工作区干净 → 放回 → 运行态完整${D}"; exit 0
fi

ASIDE=$(mktemp -d "${TMPDIR:-/tmp}/lanxiu-ship-aside.XXXXXX")
MOVED=()
put_back() {
  for f in "${MOVED[@]}"; do
    if [ -e "$ASIDE/$f" ]; then mv -f "$ASIDE/$f" "$f" && echo "  ↩ 放回 $f"; fi
  done
  rmdir -p "$ASIDE" 2>/dev/null || true
}
trap put_back EXIT INT TERM

for f in "${LOGS[@]}"; do
  if [ -e "$f" ] && ! git diff --quiet -- "$f" 2>/dev/null; then
    mkdir -p "$ASIDE/$(dirname "$f")" && mv "$f" "$ASIDE/$f" && git checkout -q -- "$f" && MOVED+=("$f") && echo "  ↪ 挪开运行日志 $f(推完放回)"
  fi
done
[ "${#MOVED[@]}" = 0 ] && echo "  (三件运行日志都没改动,不用挪)"

./tools/pre_push.sh "$@"; rc=$?
if [ "$rc" = 0 ]; then echo "${G}✅ ship:pre_push 退出码 0${D}"; else echo "${R}❌ ship:pre_push 退出码 $rc(只认这个数,别数输出里的 ❌)${D}"; fi
exit $rc
