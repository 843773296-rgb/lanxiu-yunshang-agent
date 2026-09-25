#!/usr/bin/env bash
# bootstrap:失败要**明确指出端口/依赖问题**(规格 §17.5)。
set -uo pipefail
bash "$(dirname "$0")/doctor.sh" || {
  echo "❌ bootstrap 停在依赖检查 —— 先补上面缺的那几项" >&2; exit 1; }
echo ""
echo "⚠️ 依赖齐了,但 **bootstrap 还没有东西可装**:"
echo "   依赖锁文件和数据库迁移属于规格 §17.4 第 1–2 步的后半段,还没做。"
echo "   现在能跑的是:make contract(契约覆盖检查)"
exit 1
