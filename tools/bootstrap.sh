#!/usr/bin/env bash
# bootstrap:装锁定依赖 → 建库 → 迁移。失败要**明确指出端口/依赖问题**(规格 §17.5)。
set -uo pipefail
cd "$(dirname "$0")/.."
bash tools/doctor.sh || { echo "❌ bootstrap 停在依赖检查" >&2; exit 1; }

echo ""
echo "① 装锁定依赖(requirements.lock)"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --disable-pip-version-check -r requirements.lock || {
  echo "❌ 装依赖失败 —— 这台机器有 TLS 拦截时 pip 可能走不通,见 README" >&2; exit 1; }

DB="${AIMC_DB:-aimc_dev}"
echo "② 建库 $DB + 启用 pgvector"
psql -tA -c "select 1 from pg_database where datname='$DB'" postgres | grep -q 1 || createdb "$DB" || {
  echo "❌ 建库失败 —— PostgreSQL 在跑吗?端口 5432 通吗?" >&2; exit 1; }
psql -q -d "$DB" -c "create extension if not exists vector" || {
  echo "❌ 启用 pgvector 失败 —— brew install pgvector 装过了吗?" >&2; exit 1; }

echo "③ 跑迁移"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://$USER@localhost:5432/$DB}"
(cd services/api && ../../.venv/bin/alembic upgrade head) || {
  echo "❌ 迁移失败 —— 上面那行 alembic 的报错就是原因" >&2; exit 1; }

echo ""
echo "④ 验契约和库一致(alembic check)"
(cd services/api && ../../.venv/bin/alembic check) || {
  echo "❌ **契约和库对不上** —— 改了契约就要 alembic revision --autogenerate" >&2; exit 1; }

printf "\033[32m✅ bootstrap 完成\033[0m · 库 %s · DATABASE_URL 已导出\n" "$DB"
echo "   下一步能跑:make test"
