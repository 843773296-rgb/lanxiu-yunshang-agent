#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目标版本 / 实际版本并排 · 守得住吗(用户 11-11「按你的顺序做」第 ② 步)。

真调被测代码:agentsite/config_adoption.实际加载、管理后台 chat_assistants_api.生效对比。
  ① 聊天站报告:缓存空 → 「还没加载」(不为了回答去加载一次);有缓存 → 四项各报版本 id
  ② 对比四种状态分得开:一致 / 不一致 / 聊天站还没加载 / 拿不到实际 —— **拿不到、没加载都不许算一致**
  ③ 接线:聊天站 /internal/loaded 要内部凭证、调的是 实际加载;后台 adoption 口调的是 生效对比;页面有生效状态那一块
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import config_adoption as CA     # noqa: E402

# 咬合记录(可重放的规格在 tools/bite_specs.json,script 为这个文件的那几条)
咬合 = [
    ('拿不到聊天站的实际版本却报「一致」—— 聊天站挂了,后台照样显示全绿', '拿不到实际(聊天站报错 / 没回)'),
    ('聊天站 /internal/loaded 不核内部凭证', '先核内部凭证、再调 实际加载'),
]

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def _生效对比():
    """从后台源码里把 生效项 / 生效对比 原样取出来跑(后台要 sqlalchemy,这里不起它)—— 跑的是那份源码,不是抄一份。"""
    p = os.path.join(ROOT, "管理后台", "services", "api", "app", "chat_assistants_api.py")
    树 = ast.parse(open(p, encoding="utf-8").read())
    要 = [n for n in 树.body if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "生效项" for t in n.targets))
         or (isinstance(n, ast.FunctionDef) and n.name == "生效对比")]
    ns = {}
    exec(compile(ast.Module(body=要, type_ignores=[]), p, "exec"), ns)
    return ns["生效对比"], len(要)


def main():
    print("▸ ① 聊天站报告")
    r = CA.实际加载("task", 缓存={})
    ck("缓存空 → 加载了吗=False、说明是「还没人问过」不是「没配」", r["加载了吗"] is False and "还没人" in r["说明"], r)
    假 = {"task": {"态": "有", "版本": "v3", "版本id": "glv_1", "实体识别": {"版本id": "sdv_1"},
                   "路由": {"版本id": "rtv_1", "态": "有"}, "意图": {"版本id": None, "态": "没配"}}}
    r = CA.实际加载("task", 缓存=假)
    ck("有缓存 → 四项各报版本 id", r["加载了吗"] and r["术语"]["版本id"] == "glv_1" and r["实体识别"]["版本id"] == "sdv_1"
       and r["路由"]["版本id"] == "rtv_1" and r["意图"]["版本id"] is None, r)

    print("▸ ② 对比")
    对比, n = _生效对比()
    ck("从后台源码取到 生效项 + 生效对比 两样", n == 2, n)
    目标 = {"glossary_version_id": "glv_1", "entity_version_id": "sdv_1", "route_version_id": "rtv_2", "intent_version_id": None}
    行 = {x["项"]: x["状态"] for x in 对比(目标, r)}
    ck("对得上 → 一致;路由目标 rtv_2 实际 rtv_1 → 不一致;两边都没挂 → 一致",
       行 == {"术语": "一致", "实体识别": "一致", "路由": "不一致", "意图": "一致"}, 行)
    ck("聊天站还没加载 → 四项都是「聊天站还没加载」,一项都不算一致",
       {x["状态"] for x in 对比(目标, CA.实际加载("task", 缓存={}))} == {"聊天站还没加载"})
    ck("拿不到实际(聊天站报错 / 没回)→ 「拿不到实际」,一项都不算一致",
       {x["状态"] for x in 对比(目标, {"error": "连不上"})} == {"拿不到实际"}
       and {x["状态"] for x in 对比(目标, None)} == {"拿不到实际"})

    print("▸ ③ 接线")
    应用 = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    段 = 应用.split('if p == "/internal/loaded":', 1)[1].split("if p ==", 1)[0] if 'if p == "/internal/loaded":' in 应用 else ""
    ck("聊天站 /internal/loaded:先核内部凭证、再调 实际加载", "_ic.核对(" in 段 and "实际加载(" in 段
       and 段.index("_ic.核对(") < 段.index("实际加载("))
    后台 = open(os.path.join(ROOT, "管理后台", "services", "api", "app", "chat_assistants_api.py"), encoding="utf-8").read()
    ck("后台 adoption 口调的是 生效对比 + 问聊天站", '"/chat-assistants/by-role/{role}/adoption"' in 后台
       and "生效对比(pv, 实际)" in 后台 and "/internal/loaded" in 后台)
    页 = open(os.path.join(ROOT, "管理后台", "apps", "web", "app.js"), encoding="utf-8").read()
    ck("后台页面:接上了的助手详情里画生效状态", 'if (g["接上了吗"]) 画_生效状态(' in 页 and "/adoption`" in 页)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 目标版本 / 实际版本并排:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
