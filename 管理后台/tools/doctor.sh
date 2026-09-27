#!/usr/bin/env bash
# 探本机依赖 —— **规格默认用 Compose 起,本机没有可用的 Compose,所以改用原生服务。**
# 这是记录在案的偏离(规格:「遇到非阻塞选择按文档默认值实施,并记录调整理由」)。
#
# ⚠️ 标识符一律 ASCII:bash **不接受非 ASCII 变量名**(`缺=0` 会报 command not found),
# 而它报的错看起来像是脚本别处坏了。中文只放在输出文字里。
set -uo pipefail
missing=0
ok()  { printf "  %-14s %s\n" "$1" "$2"; }
bad() { printf "  \033[31m%-14s %s\033[0m\n" "$1" "$2"; missing=$((missing+1)); }

echo "本机依赖:"
command -v python3 >/dev/null && ok "Python" "$(python3 --version 2>&1)" || bad "Python" "没装"
command -v node >/dev/null && ok "Node" "$(node --version)" || bad "Node" "没装(前端要)"

if command -v pg_isready >/dev/null && pg_isready -q 2>/dev/null; then
  ok "PostgreSQL" "$(psql -tA -c 'show server_version' postgres 2>/dev/null | head -1)"
  v=$(psql -tA -c "select default_version from pg_available_extensions where name='vector'" postgres 2>/dev/null | head -1)
  # pgvector 是**硬依赖**:没有它就没有向量检索,而向量检索是 RAG 那一半的地基。
  if [ -n "$v" ]; then ok "pgvector" "$v"; else bad "pgvector" "没装 —— brew install pgvector"; fi
else
  bad "PostgreSQL" "没在跑 —— brew services start postgresql@17"
fi

if command -v redis-cli >/dev/null && [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then
  ok "Redis" "在跑"
else
  # 本机 Redis 一向要手起 —— 不是装没装的问题
  bad "Redis" "没在跑 —— redis-server --daemonize yes"
fi

# 对象存储:规格默认 S3 兼容;本机没有 Compose,首版用文件系统适配器顶着。
ok "对象存储" "文件系统适配器(偏离,见 README)"

echo ""
if [ "$missing" -gt 0 ]; then
  printf "\033[31m❌ 缺 %s 项 —— 上面每一条都写了怎么补\033[0m\n" "$missing"; exit 1
fi
printf "\033[32m✅ 依赖齐了\033[0m\n"
