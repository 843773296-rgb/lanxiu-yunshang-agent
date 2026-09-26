#!/usr/bin/env bash
# 起 API + 页面 + Worker。**输出本地访问地址和健康检查**(规格 §17.5)。
#
# ## 为什么 Worker 也要在这里起来
#
# 上一版这个脚本打印的是「⚠️ Worker 还没实现,异步任务在请求里同步跑完」——
# 那句话在 Worker 落地之后就**变成了假话**,而它照样每次都打印。
# 一条说自己「还没实现」的提示不会有人去核实,于是它可以错很久。
#
# 而真相比那句话更糟:Worker 实现了,但 `make dev` 不起它 ——
# 于是点「运行测试」会**永远停在「排队中」**。
# 那个界面上看起来就是功能坏了:没有报错、没有超时、什么都没有。
# **一个需要另外开一个终端才能工作的开发环境,等于一个默认是坏的开发环境。**
set -uo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-development}"
export AUTH_MODE="${AUTH_MODE:-dev}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://$USER@localhost:5432/aimc_dev}"
PORT="${PORT:-8801}"
NO_WORKER="${NO_WORKER:-}"

if [ -z "$NO_WORKER" ]; then
  ./.venv/bin/python workers/worker.py > /tmp/aimc-worker.log 2>&1 &
  WPID=$!
  # API 退出时把 Worker 一起带走 —— 留一个孤儿 Worker 在后台抢租约,
  # 下次调试时会看到「任务被一个不存在的进程拿走了」
  trap 'kill '"$WPID"' 2>/dev/null' EXIT INT TERM
  echo "▸ Worker 起来了(pid $WPID),日志:/tmp/aimc-worker.log"
  echo "  不想起它:NO_WORKER=1 make dev"
else
  echo "⚠️ NO_WORKER=1:**Worker 没起**。异步任务会一直停在「排队中」——"
  echo "   那不是功能坏了,是没有人去执行它。"
fi
echo ""
echo "起 API + 页面:http://127.0.0.1:$PORT"
echo "  健康检查:   http://127.0.0.1:$PORT/api/healthz"
echo "  接口文档:   http://127.0.0.1:$PORT/api/docs"
echo "  身份:顶栏可切 U001–U005(开发身份模式;生产要接 OIDC)"
echo ""
echo "⚠️ 页面上现在有的是工作台 / Prompt 列表 / Prompt 详情三页。"
echo "   **Workflow 画布和 Agent 配置页还没建**(见 README 的九个组件落点表)。"
echo ""
cd services/api/app
exec ../../../.venv/bin/uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload
