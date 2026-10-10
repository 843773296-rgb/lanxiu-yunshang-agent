#!/bin/bash
# 一条命令把两个服务都起起来。
#   管理后台   :8760  —— 记录系统,数据的家
#   智能运维平台 :8770  —— Agent SDK 为内核,值班台 / 研判队列 / 智能体健康
cd "$(dirname "$0")"
kill $(lsof -nP -iTCP:8760 -sTCP:LISTEN -t 2>/dev/null) 2>/dev/null
kill $(lsof -nP -iTCP:8770 -sTCP:LISTEN -t 2>/dev/null) 2>/dev/null
sleep 1
# ── 首次启动:把库**建全**,不是只建第 1 步 ─────────────────────────────
# 这里原来是 `[ -f backend/lanxiu.db ] || python3 backend/seed.py`,
# 而 `seed.py` 只是 `tools/rebuild.sh` 里 15 步的**第 1 步**。
# 实测(2026-09-21,隔离副本):这样起出来的库 65 张表 / 12886 行,
# 实际在用的库 79 张表 / 198646 行 —— roster / fitting / call_transcript 等
# **14 张表根本不存在**。而首页照样打得开,点进排班才 `no such table`。
#
# `--fresh-only` 那个入口**有库就会自己拒绝**,所以启动永远不会删掉谁的数据。
#
# 半成品也得清掉:建到一半失败会留下一个残库,
# 下一次启动的 `[ -f ]` 会认为「库已经有了」——
# **半成品和建好了,在那个判断眼里还是长得一样。**
if [ ! -f backend/lanxiu.db ]; then
  echo "首次启动,先把库建全(15 步)——"
  ./tools/rebuild.sh --fresh-only || {
    rm -f backend/lanxiu.db
    echo "❌ 建库没建完。已经把半成品删掉了 —— 留着它,下次启动会把它当成建好的库直接用。"
    exit 1
  }
fi
(cd backend && nohup python3 server.py > /tmp/lanxiu-backend.log 2>&1 &)
[ -d agentsite/.venv ] || (cd agentsite && python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt)
(cd agentsite && nohup ./.venv/bin/python app.py > /tmp/lanxiu-agentsite.log 2>&1 &)
sleep 3
printf "  管理后台     http://127.0.0.1:8760  HTTP %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8760/)"
printf "  智能运维平台  http://127.0.0.1:8770  HTTP %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8770/)"

# ── 连 AI 管理平台(管理后台/,:8801)——用户 2026-10-10 定:本机要连 ─────────────────
# 连上之后每 30 秒一轮:推用量(A1)、推产出(报告 / 建议)、拉「打回」回来执行。
# **只有显式配置、而且那边真的起着才连**:没起就明说没连,不往一个不存在的地址静默地发。
# 换机器 / 换项目号就改这三行(或者在外面先 export 好,这里不覆盖)。
export LANXIU_USAGE_URL="${LANXIU_USAGE_URL:-http://127.0.0.1:8801}"
export LANXIU_USAGE_PROJECT="${LANXIU_USAGE_PROJECT:-project_demo_a}"
export LANXIU_USAGE_USER="${LANXIU_USAGE_USER:-U001}"
pkill -f "tools/supervise_sync.py --循环" 2>/dev/null
if curl -s -o /dev/null -m 3 "$LANXIU_USAGE_URL/"; then
  nohup python3 tools/supervise_sync.py --循环 30 > /tmp/lanxiu-supervise-sync.log 2>&1 &
  echo "  AI 管理平台   $LANXIU_USAGE_URL  已连(每 30 秒同步一次,日志 /tmp/lanxiu-supervise-sync.log)"
else
  echo "  AI 管理平台   $LANXIU_USAGE_URL  没起 —— 没连。先在 管理后台/ 里 make dev,再重跑 ./start.sh"
fi
