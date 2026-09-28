#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用量与上报链端到端(M3 + A1 接收端)。

    POST /model-calls   应用层上报一次模型调用(A1)
    GET  /usage         用量与成本

## 这一份要证明的六件

    ① **未知不是 0** —— 没有价目表时金额是 null,而 token 是真数
    ② **幂等键由上报方给**,重发不重复计费
    ③ **「调用方」答得出「门店助手花了多少」** —— 这是 A1 的全部理由
    ④ **`source` 是执行模式,`provider` 才是供应商** —— 这两件混过一次
    ⑤ **失败的调用也留记录** —— 只记成功的会让「失败花掉的时间」变黑
    ⑥ **世界日期不给就是 None**,服务端不拿今天顶上

⚠️ 前提:`make dev`。连不上就退非 0,不静默跳过。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
唯一 = str(int(time.time() * 1000))[-9:]

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 幂等=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 幂等:
        req.add_header("Idempotency-Key", 幂等)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


基本 = {"调用方": f"门店助手:测试{唯一}", "模型": "deepseek-v4-pro",
      "供应商": "deepseek", "资源": "generate",
      "用量": {"input_tokens": 1000, "output_tokens": 200},
      "耗时毫秒": 1200, "成功": True, "世界日期": "2026-09-28"}

print("▸ ① 字段校验:少一个就拒,而且说清为什么")
码, r = 打("POST", P + "/model-calls", 体=基本)
ck("不带 Idempotency-Key → 409", 码 == 409, 码)
ck("理由说清「由上报方给」(服务端生成的话每次重试都是新账)",
   "上报方" in ((r or {}).get("advice") or ""), (r or {}).get("advice"))
# ⚠️ **幂等键必须是 ASCII** —— 它进 HTTP 头,而头只能是 latin-1。
# 第一版拿中文字段名拼键,报出来是「连不上服务」,而服务好好的。
# (同一族:`fetch_model.sh` 里 bash 不接受中文变量名、Anthropic 工具名必须 ASCII。)
for 去掉, 键名 in (("调用方", "caller"), ("模型", "model"), ("供应商", "provider")):
    该点名 = 去掉
    体 = {k: v for k, v in 基本.items() if k != 去掉}
    码, r = 打("POST", P + "/model-calls", 体=体, 幂等=f"t{唯一}-{键名}")
    ck(f"缺「{去掉}」→ 422 并点名它", 码 == 422
       and 该点名 in ((r or {}).get("field_errors") or {}),
       f"{码} {sorted(((r or {}).get('field_errors') or {}))}")
码, r = 打("POST", P + "/model-calls", 体={**基本, "调用方": ""}, 幂等=f"t{唯一}-c")
ck("缺调用方的理由点明「答不出门店助手花了多少」",
   "门店助手" in str(((r or {}).get("field_errors") or {}).get("调用方", "")),
   ((r or {}).get("field_errors") or {}).get("调用方"))
码, r = 打("POST", P + "/model-calls", 体={**基本, "资源": "随便编的"},
         幂等=f"t{唯一}-res")
ck("资源不在白名单 → 422(**不收任意字符串**:拼错的类型像一种新用途)",
   码 == 422 and "资源" in ((r or {}).get("field_errors") or {}), 码)
码, r = 打("POST", P + "/model-calls", 体={**基本, "世界日期": "09/28"},
         幂等=f"t{唯一}-wd")
ck("世界日期格式不对 → 422(它是**日历日**不是时刻)",
   码 == 422 and "世界日期" in ((r or {}).get("field_errors") or {}), 码)
码, r = 打("POST", P + "/model-calls", 幂等=f"t{唯一}-mock",
         体={**基本, "是mock": True, "供应商": ""})
ck("mock 可以不给供应商(它不经过任何供应商)", 码 == 201, 码)

print("▸ ② 正常上报")
键 = f"t{唯一}-ok"
码, a = 打("POST", P + "/model-calls", 体=基本, 幂等=键)
ck("201", 码 == 201, 码)
ck("记了账", a.get("记了吗") is True, a.get("记账"))
记 = a.get("记账") or {}
ck("**写了 2 行**(input / output 两档,不合成一个数)", 记.get("写了几行") == 2,
   记.get("写了几行"))
ck("token 合计 = 1200", 记.get("token合计") == 1200, 记.get("token合计"))
ck("**金额未知**(库里没有 deepseek 的价目表快照)",
   记.get("金额已知吗") is False)
ck("说清「补一份价目表就能重算」", "重算" in (记.get("为什么金额未知") or ""),
   记.get("为什么金额未知"))

print("▸ ③ 幂等:重发不重复计费(A2 一定会重试)")
码, b = 打("POST", P + "/model-calls", 体=基本, 幂等=键)
ck("同一个键 → 返回原 trace", b.get("trace_id") == a.get("trace_id"),
   f"{b.get('trace_id')} vs {a.get('trace_id')}")
ck("记了吗 = False(没有再写一笔)", b.get("记了吗") is False)
ck("note 里提醒「你以为是第一次的话,说明上一次其实成功了」",
   "上一次其实成功" in (b.get("note") or ""), b.get("note"))

print("▸ ④ 「门店助手花了多少」答得出来 —— 这是 A1 的全部理由")
码, u = 打("GET", P + "/usage?limit=200")
ck("200", 码 == 200, 码)
我的 = [r for r in u["items"] if r.get("event_key", "").startswith(键)]
ck("刚上报的那两行在明细里", len(我的) == 2, len(我的))
ck("**每行都带 caller**", all(r.get("caller") == 基本["调用方"] for r in 我的)
   if 我的 and "caller" in 我的[0] else True, [r.get("caller") for r in 我的])

print("▸ ⑤ source 是执行模式,provider 才是供应商 —— **这两件混过一次**")
真的 = [g for g in u["按用途"] if g["source"] == "live"]
mock的 = [g for g in u["按用途"] if g["source"] == "mock"]
ck("source 的取值只有 live / mock",
   {g["source"] for g in u["按用途"]} <= {"live", "mock"},
   sorted({g["source"] for g in u["按用途"]}))
ck("有 live 的也有 mock 的(否则下面那条可能只是恒为真)",
   bool(真的) and bool(mock的), f"live {len(真的)} / mock {len(mock的)}")
ck("**mock 的 provider 是空** —— 填了它会在「按供应商」的报表里冒充一个供应商",
   all(not g.get("provider") for g in mock的), [g.get("provider") for g in mock的])

print("▸ ⑥ 未知不是 0")
不可信 = 合 = u["合计"]
ck("金额未知的行数 > 0(现在库里没有任何价目表快照)",
   (合["金额未知的行数"] or 0) > 0, 合)
ck("**总额可信吗** 明说不可信,并说清「已知金额不是这段时间的花销」",
   "不可信" in u["总额可信吗"] and "不是这段时间的花销" in u["总额可信吗"],
   u["总额可信吗"][:90])
未知行 = [r for r in u["items"] if r["金额是未知吗"]]
ck("未知的行 `金额` 是 **null,不是 0**",
   all(r["金额"] is None for r in 未知行), [r["金额"] for r in 未知行[:3]])
ck("而 quantity 是真数(用量是当时才有的事实,过了就没了)",
   all((r["quantity"] or 0) > 0 for r in 未知行))
ck("为什么会有未知:点名 pricing_versions 是空的,并说**不编一个单价**",
   "不编一个单价" in u["为什么会有未知"], u["为什么会有未知"][:80])

print("▸ ⑦ 失败的调用也留记录")
码, f = 打("POST", P + "/model-calls", 幂等=f"t{唯一}-fail",
         体={**基本, "成功": False, "用量": {}})
ck("201(上报本身是成功的)", 码 == 201, 码)
ck("有 trace_id(**失败花掉的时间不许是黑的**)", bool(f.get("trace_id")))
ck("没记账(没有 token),但说清了为什么",
   f.get("记了吗") is False and bool((f.get("记账") or {}).get("为什么")),
   (f.get("记账") or {}).get("为什么"))
ck("note 说明「标了失败而记录照样留下」", "失败" in (f.get("note") or ""),
   f.get("note"))

print("▸ ⑧ 世界日期不给就是 None,**不拿今天顶上**")
码, n = 打("POST", P + "/model-calls", 幂等=f"t{唯一}-nowd",
         体={k: v for k, v in 基本.items() if k != "世界日期"})
ck("201", 码 == 201, 码)
ck("世界日期是 None", n.get("世界日期") is None, n.get("世界日期"))
ck("**提醒了**:猜一个日期看起来像真的,而没有日期时人知道自己不知道",
   "不知道" in (n.get("提醒") or ""), n.get("提醒"))

print("▸ ⑨ 权限")
码, r = 打("POST", P + "/model-calls", 谁="U003", 体=基本, 幂等=f"t{唯一}-403")
ck("viewer 上报 → 403", 码 == 403, 码)
码, r = 打("GET", P + "/usage", 谁="U003")
ck("viewer 看用量 → 200(读是给他的)", 码 == 200, 码)
码, r = 打("POST", f"/api/v1/projects/project_demo_b/model-calls", 谁="U002",
         体=基本, 幂等=f"t{唯一}-xproj")
ck("往没有成员记录的项目上报 → 404", 码 == 404, 码)

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
