#!/bin/bash
# 每周项目审查(只读)—— 用户 2026-11-21 拍(台账第八十七条):定时只读地看代码变化、旧问题修没修、新问题,
# 写一份 Markdown 到辅助目录给用户看;不碰业务库、不改源码、不触发业务定时。
#
# 怎么跑:launchd 每周一 07:30(tools/launchd/com.lanxiu.weekly-review.plist,用户亲手装),或手动 `./tools/weekly_review.sh`。
# 怎么只读:claude 以 --print 一次性跑,**只放行读工具和只读 git 命令**(--allowedTools);别的工具在无人值守下没人批 = 不许。
# 报告由**本脚本**写文件(claude 只负责输出正文),写完回读:空的 / 太短的不算成功,退非零。
# ⚠️ 变量名一律英文:launchd 用的是 macOS 自带 /bin/bash 3.2,中文变量名直接 `command not found`(11-21 晚第一次试跑栽的)。
set -u
export LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8
R="$(cd "$(dirname "$0")/.." && pwd)"
OUTDIR="${WEEKLY_REVIEW_DIR:-$HOME/Documents/ChatGPT/澜绣云裳agent-辅助}"
LOG="$R/.feynman/weekly-review.log"
cd "$R" || exit 2
mkdir -p "$OUTDIR" "$(dirname "$LOG")"
SHORT=$(git rev-parse --short HEAD 2>/dev/null || echo nogit)
OUT="$OUTDIR/澜绣云裳agent-项目周审查_$(date +%Y%m%d_%H%M)_${SHORT}.md"
PART="$OUT.part"
echo "$(date '+%F %T') 开始 · HEAD $SHORT · 写到 $OUT" >> "$LOG"
if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
  echo "$(date '+%F %T') ❌ 找不到 claude 命令行,没跑" >> "$LOG"; exit 3
fi
CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
# 只放行只读工具;Bash 只放行三条只读 git 子命令(前缀匹配)。Edit / Write 不在名单里,无人值守下没人批 = 不许
"$CLAUDE" -p "$(cat tools/weekly_review_prompt.md)" \
  --allowedTools "Read,Grep,Glob,Bash(git log:*),Bash(git diff:*),Bash(git show:*)" \
  --disallowedTools "Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent,Task" \
  --output-format text > "$PART" 2>>"$LOG"
rc=$?
LINES=$(wc -l < "$PART" | tr -d ' ')
if [ $rc -ne 0 ] || [ "$LINES" -lt 20 ] || ! grep -q "^## 本次结论" "$PART"; then
  echo "$(date '+%F %T') ❌ 审查没出报告(claude 退出码 $rc,$LINES 行,有没有「本次结论」:$(grep -c '^## 本次结论' "$PART"))—— 半成品留在 $PART,不改名" >> "$LOG"
  exit 4
fi
mv "$PART" "$OUT"
echo "$(date '+%F %T') ✅ 写好 $OUT($LINES 行,sha256 $(shasum -a 256 "$OUT" | cut -c1-12))" >> "$LOG"
