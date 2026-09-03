#!/bin/bash
# 一条命令把两个服务都起起来。
#   管理后台   :8760  —— 记录系统,数据的家
#   智能体工作站 :8770  —— Agent SDK 为内核,四个应用
cd "$(dirname "$0")"
kill $(lsof -nP -iTCP:8760 -sTCP:LISTEN -t 2>/dev/null) 2>/dev/null
kill $(lsof -nP -iTCP:8770 -sTCP:LISTEN -t 2>/dev/null) 2>/dev/null
sleep 1
[ -f backend/lanxiu.db ] || python3 backend/seed.py
(cd backend && nohup python3 server.py > /tmp/lanxiu-backend.log 2>&1 &)
[ -d agentsite/.venv ] || (cd agentsite && python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt)
(cd agentsite && nohup ./.venv/bin/python app.py > /tmp/lanxiu-agentsite.log 2>&1 &)
sleep 3
printf "  管理后台     http://127.0.0.1:8760  HTTP %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8760/)"
printf "  智能体工作站  http://127.0.0.1:8770  HTTP %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8770/)"
