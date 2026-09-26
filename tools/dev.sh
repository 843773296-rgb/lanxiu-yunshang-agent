#!/usr/bin/env bash
# 起 API + 页面。**输出本地访问地址和健康检查**(规格 §17.5)。
set -uo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-development}"
export AUTH_MODE="${AUTH_MODE:-dev}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://$USER@localhost:5432/aimc_dev}"
PORT="${PORT:-8801}"

# Worker 还没建 —— **明说,不假装它起来了**
echo "⚠️ Worker 还没实现(§17.4 第 4 步):现在异步任务是在请求里同步跑完的,"
echo "   接口形态仍然是异步的(202 + 任务信封),所以接 Worker 时前端不用改。"
echo ""
echo "起 API + 页面:http://127.0.0.1:$PORT"
echo "  健康检查:   http://127.0.0.1:$PORT/api/healthz"
echo "  接口文档:   http://127.0.0.1:$PORT/api/docs"
echo "  身份:顶栏可切 U001–U005(开发身份模式;生产要接 OIDC)"
echo ""
cd services/api/app
exec ../../../.venv/bin/uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload
