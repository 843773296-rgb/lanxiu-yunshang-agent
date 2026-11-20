#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新建空白流程的「开始」引导标(2026-11-20,工作流二期 2-3「开始」页签与多开始,照 Dify)—— 服务端那一半。

打真起着的 :8801。前端那一半(虚线占位 / 引导弹窗 / 「开始」页签换开始方式)在 test_workflow_start_tab.js。

逐条:
  ① 空白模板建出来的草稿:布局里带 $开始待配置=true;**定义里不写 start_mode**(校验按「用户输入」走,不报 START_MODE_UNKNOWN)——
     这个标和 $注释 / $线 一样只在布局里,不改执行语义
  ② 别的模板(文本处理)不带这个标
  ③ 前端选了开始方式后存草稿(布局里不再有这个标)→ 再读没有了:服务端照存,不自己补回去
  ④ 布局单独存那条路(只传布局)也能把标摘掉
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U001", 体=None, 头=None):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
    if 谁:
        req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


建的工作流 = []


def 建(名, 模板):
    c, w = 打("POST", P + "/workflows", 体={"名称": f"{名} {uuid.uuid4().hex[:6]}", "模板": 模板})
    wid = (w or {}).get("id")
    if wid:
        建的工作流.append(wid)
    return c, wid


def 收尾():
    for wid in list(建的工作流):
        c, b = 打("POST", P + f"/workflows/{wid}/archive", 体={"理由": "e2e 收尾"})
        if c != 200:
            print(f"  ⚠️ 收尾没归档成 {wid}:{c} {b}")
    建的工作流.clear()


def main():
    print("▸ ① 空白模板:布局带 $开始待配置,定义里不写 start_mode")
    c, wid = 建("e2e 开始引导 空白", "空白")
    ck("建空白流程 201", c == 201 and bool(wid), (c, wid))
    c, d = 打("GET", P + f"/workflows/{wid}")
    草 = (d or {}).get("草稿") or {}
    布局, 定义 = 草.get("布局") or {}, 草.get("定义") or {}
    起 = next((n for n in 定义.get("nodes") or [] if n.get("type") == "start"), None)
    ck("布局里 $开始待配置 = true", 布局.get("$开始待配置") is True, 布局)
    ck("开始节点在,定义里**没有** start_mode(标只在布局里)", bool(起) and "start_mode" not in (起.get("config") or {}), 起)
    ck("节点们的坐标照旧在布局里(标没挤掉别的键)", all(n["id"] in 布局 for n in 定义.get("nodes") or []), list(布局))
    c, v = 打("POST", P + f"/workflows/{wid}/validate")
    码们 = [p.get("code") for p in (v or {}).get("问题") or (v or {}).get("issues") or []]
    ck("检查配置不报 START_MODE_UNKNOWN(没写 = 用户输入)", c == 200 and "START_MODE_UNKNOWN" not in 码们, (c, 码们, v))

    print("\n▸ ② 别的模板不带这个标")
    c2, wid2 = 建("e2e 开始引导 文本", "文本处理")
    c, d2 = 打("GET", P + f"/workflows/{wid2}")
    布局2 = ((d2 or {}).get("草稿") or {}).get("布局") or {}
    ck("文本处理模板:布局里没有 $开始待配置", c2 == 201 and "$开始待配置" not in 布局2, 布局2)

    print("\n▸ ③ 前端选了开始方式后存草稿 → 标没了,服务端不补回去")
    for n in 定义["nodes"]:
        if n["type"] == "start":
            n.setdefault("config", {})["start_mode"] = "用户输入"
    新布局 = {k: v for k, v in 布局.items() if k != "$开始待配置"}
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义, "布局": 新布局}, 头={"If-Match": str(草.get("revision"))})
    ck("存草稿 200", c == 200, (c, b))
    c, d = 打("GET", P + f"/workflows/{wid}")
    草 = (d or {}).get("草稿") or {}
    ck("再读:布局里没有 $开始待配置、start_mode=用户输入",
       "$开始待配置" not in (草.get("布局") or {})
       and next((n for n in 草.get("定义", {}).get("nodes") or [] if n["type"] == "start"), {}).get("config", {}).get("start_mode") == "用户输入",
       草.get("布局"))

    print("\n▸ ④ 只传布局那条路也能摘标")
    c3, wid3 = 建("e2e 开始引导 空白2", "空白")
    c, d3 = 打("GET", P + f"/workflows/{wid3}")
    草3 = (d3 or {}).get("草稿") or {}
    ck("夹具:新建的带标", (草3.get("布局") or {}).get("$开始待配置") is True)
    布局3 = {k: v for k, v in (草3.get("布局") or {}).items() if k != "$开始待配置"}
    c, b = 打("PATCH", P + f"/workflows/{wid3}/draft", 体={"布局": 布局3}, 头={"If-Match": str(草3.get("revision"))})
    c, d3 = 打("GET", P + f"/workflows/{wid3}")
    ck("只改布局存一次 → 标没了,定义原样", "$开始待配置" not in (((d3 or {}).get("草稿") or {}).get("布局") or {})
       and ((d3 or {}).get("草稿") or {}).get("定义") == 草3.get("定义"), (c, b))

    收尾()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条没过:{挂}")
        sys.exit(1)
    print(f"✅ 开始引导标 {len(过)} 条全过")


if __name__ == "__main__":
    try:
        main()
    finally:
        收尾()
