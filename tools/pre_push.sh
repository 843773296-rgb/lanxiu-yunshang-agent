#!/bin/bash
# 推送前的一条链 —— 把 CLAUDE.md 第 5 节 1.5 那段「顺序」做成一个命令,别靠人记。
#
#     ./tools/pre_push.sh            # 全部走完并 push
#     ./tools/pre_push.sh --不推      # 走完门禁不 push(门禁红在预期那条时用)
#     ./tools/pre_push.sh --自测      # 不碰 git 远程、不跑门禁,只验这条链的判断逻辑
#
# 顺序(Not Rocket Science Rule 的落法,用户 2026-11-11 拍「全量门禁跑在 rebase 之后」):
#   ① fetch,**HEAD 必须已经包含 origin/main**(没包含 = 还没 rebase,直接退;不在这里替你 rebase)
#   ② 扫密钥(先看样本量数字,`git add` 过的才算进去)
#   ③ **按改动文件重放咬合**(`bite_replay_touched --基线 origin/main --检查类才跑`;用户 11-13 拍:改动里没有
#      检查 / 守卫 / 判分器类文件就跳过,一推从 ~85 分钟降到 ~15 分钟):这是 2026-11-12 全项目审读
#      查出的缺口 —— 记账欠债清零了,而 1644 条规格的全量重放十天一次,门禁绿 ≠ 攻击还活着
#   ④ 锁内跑全量 `./check.sh`
#   ⑤ 推之前**再 fetch 一次**查 main 没动(门禁的 14 分钟里别人推了就回到 ①)
# ⚠️ 每一步的退出码都单独捞、单独印 —— `echo "$(date) $?"` 永远印 0 那一坑(CLAUDE.md 第 7 节 9)
set -u
cd "$(dirname "$0")/.." || exit 1
R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; D=$'\033[0m'
NOPUSH=0; SELFTEST=0
for a in "$@"; do
  case "$a" in --不推) NOPUSH=1;; --自测|--selftest) SELFTEST=1;; esac
done

contains_main() {   # HEAD 是否已经包含 origin/main(= rebase 过了)
  git merge-base --is-ancestor "origin/main" HEAD
}

if [ "$SELFTEST" = 1 ]; then
  # 不碰远程、不跑门禁。验的是「判断」:① 包含/不包含 main 分得开 ② 五步的退出码各自捞得到
  BAD=0
  say() { if [ "$1" = 0 ]; then echo "  ✅ $2"; else echo "  ❌ $2 —— $3"; BAD=$((BAD+1)); fi; }
  echo "推送前链 · 自测(不 fetch、不跑门禁、不推)"
  if git rev-parse --verify -q origin/main >/dev/null; then
    if contains_main; then say 0 "包含判断:当前 HEAD 含 origin/main → 认成已 rebase"; else say 0 "包含判断:当前 HEAD 不含 origin/main → 认成还没 rebase(这是真实状态,不是错)"; fi
    # 造一个一定不含 main 的提交对象:main 的父 —— 它不可能是 main 的后代
    PARENT="$(git rev-parse origin/main~1 2>/dev/null)"
    if [ -n "$PARENT" ] && ! git merge-base --is-ancestor origin/main "$PARENT"; then say 0 "包含判断的反例:main 的父提交被认成「不含 main」"; else say 1 "包含判断的反例" "main 的父居然被认成含 main"; fi
  else
    say 1 "有 origin/main" "本地没有 origin/main 这个引用,先 git fetch"
  fi
  # 退出码各自捞:一条故意失败的子命令,外面的 rc 必须是它的,不是 date 的
  (false); rc=$?; if [ "$rc" != 0 ]; then say 0 "子命令退出码捞得到(不被 \$(date) 吃掉)"; else say 1 "子命令退出码" "false 之后 rc=0"; fi
  # 用户 11-13 拍的「检查类才重放」:纯业务改动 → 空;带检查 / 守卫 → 非空(两边都钉,真调那个函数)
  K="$(python3 -c "import sys; sys.path.insert(0,'tools'); import bite_replay_touched as b; print(len(b.检查类文件({'backend/api.py','HANDOFF.md','knowledge/x.md'})), len(b.检查类文件({'backend/api.py','agentsite/guards.py','agent/ops_eval.py'})))" 2>&1)"
  if [ "$K" = "0 2" ]; then say 0 "检查类判定:纯业务改动跳过重放、带守卫 / 判分器的照跑"; else say 1 "检查类判定" "期望「0 2」,拿到「${K}」"; fi
  for f in tools/scan_secrets.sh tools/bite_replay_touched.py tools/gate_lock.sh check.sh; do
    if [ -f "$f" ]; then say 0 "链上的脚本在:$f"; else say 1 "链上的脚本在:$f" "找不到"; fi
  done
  echo; if [ "$BAD" = 0 ]; then echo "${G}✅ 推送前链自测全过${D}"; exit 0; else echo "${R}❌ 自测 $BAD 条不过${D}"; exit 1; fi
fi

echo "推送前链 · $(date '+%F %T')"
echo "① fetch + 查 rebase"
git fetch -q origin; rc=$?; [ "$rc" = 0 ] || { echo "${R}❌ fetch 失败(rc=$rc)${D}"; exit 1; }
if ! contains_main; then
  echo "${R}❌ HEAD 还没包含 origin/main(落后 $(git rev-list --count HEAD..origin/main) 笔)—— 先 rebase,再回来跑这条链。${D}"
  echo "   测的必须就是要落地的那份代码(CLAUDE.md 第 5 节 1.5)。这里不替你 rebase。"
  exit 2
fi
echo "   ✅ HEAD 含 origin/main(领先 $(git rev-list --count origin/main..HEAD) 笔)"

echo "② 扫密钥"
./tools/scan_secrets.sh; rc=$?; [ "$rc" = 0 ] || { echo "${R}❌ 密钥扫描 rc=$rc${D}"; exit 1; }

echo "③ 按改动文件重放咬合(基线 origin/main;改动里没有检查类文件就跳过 —— 用户 2026-11-13 拍)"
python3 tools/bite_replay_touched.py --基线 origin/main --检查类才跑; rc=$?
if [ "$rc" != 0 ]; then echo "${R}❌ 咬合重放 rc=$rc —— 攻击死了一条,先修规格或判据${D}"; exit 1; fi

echo "④ 锁内全量门禁"
./tools/gate_lock.sh --who "pre_push" ./check.sh; rc=$?
if [ "$rc" != 0 ]; then echo "${R}❌ 门禁 rc=$rc(锁脚本印的「被包的命令退出码」才是真相)${D}"; exit 1; fi

if [ "$NOPUSH" = 1 ]; then echo "${Y}⏸ --不推:门禁绿,按要求不推${D}"; exit 0; fi

echo "⑤ 推之前再查一次 main 没动"
git fetch -q origin; rc=$?; [ "$rc" = 0 ] || { echo "${R}❌ 第二次 fetch 失败${D}"; exit 1; }
if ! contains_main; then echo "${R}❌ 门禁期间 main 动了 —— 回到 ① 重来(merge queue 的串行化)${D}"; exit 2; fi
# ⚠️ 推到 main,不是 `HEAD`:在 worktree 的分支上(如 w75)`git push origin HEAD` 会推成远程同名分支,
#    印「已推送」而主干一笔没动(2026-11-14 第五轮栽过:多出一个 origin/w75,手动 HEAD:main 才进主干)
git push origin HEAD:main; rc=$?
if [ "$rc" = 0 ]; then echo "${G}✅ 已推送${D}"; else echo "${R}❌ push rc=$rc${D}"; fi
exit $rc
