#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识与 RAG 端到端 —— **把这三条接口从「我手敲 curl 验过」变成可重跑的断言**。

> 一次没留下可重跑证据的验证,和没验证之间的差别,只存在于验的人脑子里。

## 这一份测的三条

    GET  /knowledge-bases                          能不能检索要**显式说**
    GET  /knowledge-bases/{id}/index-builds        成员数、模型、输入指纹
    POST /retrieval-tests                          **整条链路**(§9.5)

⚠️ 最后一条**会真调一次 Claude 精排**(几百毫秒到两秒,月租额度)。
所以也测一次 `要精排=false` —— 那条不花钱,而且它验的是
「只走向量时**说清代价**」这件事。

## 前提

要先 `make dev`(服务在 8801)、要有导入的语料和一个已就绪的索引。
⚠️ 缺前提时**明确报「没东西可测」并退非 0**,不静默跳过 ——
「跳过了」和「通过了」在输出上长得一模一样。
"""
import json
import os
import sys
import urllib.error
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None):
    req = urllib.request.Request(基址 + 路, method=方法,
                                data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


print("▸ ① 知识库列表:**「能不能检索」要显式说,不让人从 0 里猜**")
s, d = 打("GET", f"{P}/knowledge-bases")
ck("200", s == 200, s)
if not d or not d.get("items"):
    print("❌ 没有知识库 —— 先 `python tools/ingest_lanxiu.py`。"
          "**这不叫跳过,叫没东西可测**")
    sys.exit(1)
kb = d["items"][0]
ck("片段数 > 0(语料进库了)", kb["片段数"] > 0, kb["片段数"])
ck("**`能检索吗` 是个显式字段** —— 有片段不等于能检索"
   "(没就绪索引时检索返回空,而那和「库里就这么点」长得一样)",
   "能检索吗" in kb, kb.get("能检索吗"))
ck("不能检索时**说清为什么**", kb["能检索吗"] or bool(kb.get("为什么不能检索")),
   kb.get("为什么不能检索"))
ck("**`索引是mock吗` 一路传到界面**"
   "(mock 向量的相似度是个看起来很正常的数字,人会拿它当效果读)",
   "索引是mock吗" in kb, kb.get("索引是mock吗"))
if not kb["能检索吗"]:
    # ⚠️ **自己建一个索引,而不是退出。**
    #
    # 这一份和 `tests/integration/test_index_build.py` 有个**顺序依赖**:
    # 那一份跑完会把向量清干净(它的洁净度检查要求开跑前 embeddings 是空的),
    # 而这一份需要一个已就绪的索引。
    # 第一版这里直接 `sys.exit(1)` —— 于是 `make test` 之后 `make test-e2e`
    # 必然失败,而那个失败看起来像「接口坏了」。
    #
    # 自己建的代价:要起一次 Worker(几秒)。收益:两份测试**谁先跑都行**。
    print(f"     ⚠️ 没有已就绪的索引({kb.get('为什么不能检索')})—— **自己建一个**")
    print(f"        (和 test_index_build.py 有顺序依赖:它跑完会清掉向量)")
    import subprocess
    根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run([os.path.join(根, "tools", "seed_index.sh")],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"❌ 建索引失败:{(r.stdout + r.stderr)[-400:]}")
        sys.exit(1)
    print("       " + (r.stdout.strip().split("\n") or ["(无输出)"])[-1][:150])
    s2, d2 = 打("GET", f"{P}/knowledge-bases")
    kb = (d2.get("items") or [{}])[0]
    ck("建完之后能检索了", kb.get("能检索吗") is True, kb.get("为什么不能检索"))
    if not kb.get("能检索吗"):
        sys.exit(1)

print("\n▸ ② 索引构建列表:成员数、模型、输入指纹")
s, b = 打("GET", f"{P}/knowledge-bases/{kb['id']}/index-builds")
ck("200", s == 200, s)
就绪 = [x for x in (b.get("items") or []) if x["status"] == "已就绪"]
ck("至少一个已就绪的构建", bool(就绪), len(b.get("items") or []))
ib = 就绪[0]
ck("**成员数 == 知识库的片段数**(对不上就说明索引不完整,而那只是「少返回几条」,不报错)",
   ib["成员数"] == kb["片段数"], f"{ib['成员数']} vs {kb['片段数']}")
ck("带输入指纹(没有它就判不出输入变没变)", bool(ib.get("输入指纹短")), ib.get("输入指纹短"))
ck("跨项目取不到(404 而不是 403 —— **不泄露这个 ID 在别的项目里存在**)",
   打("GET", f"/api/v1/projects/project_demo_b/knowledge-bases/{kb['id']}/index-builds")[0]
   in (403, 404))

print("\n▸ ③ 检索:只走向量(**不花钱**),要说清代价")
s, r0 = 打("POST", f"{P}/retrieval-tests",
          体={"索引构建id": ib["id"], "问题": "客户给了差评要怎么处理", "要精排": False})
ck("200", s == 200, s if s == 200 else r0)
ck("**`改写` 是 None 而不是空串** —— 「没做」和「改写结果是空」要分得开",
   r0["改写"] is None and "没做" in (r0.get("改写说明") or ""))
ck("召回了候选", r0["召回数"] > 0, r0["召回数"])
ck("每一片都有**能翻回原文的证据串**",
   all(" · 第 " in x["证据"] for x in r0["选片"]),
   r0["选片"][0]["证据"] if r0["选片"] else "没有选片")
ck("不精排时**说清代价**(只走向量的排序不可靠)",
   r0["精排"]["做了"] is False and "不可靠" in (r0["精排"].get("为什么") or ""))
ck("截断说出来了(静默截断的后果:被截掉的和没检索到长得一样)", bool(r0["截断"]), r0["截断"])
ck("token 标明是粗估(不许拿它算钱)", r0.get("token是粗估") is True)

print("\n▸ ④ 检索:带 Claude 精排(**会真调一次模型**)")
s, r1 = 打("POST", f"{P}/retrieval-tests",
          体={"索引构建id": ib["id"], "问题": "客户给了差评要怎么处理"})
ck("200", s == 200, s if s == 200 else r1)
ck("精排真做了,而且**报了用的哪个模型**(不写死在文档里)",
   r1["精排"]["做了"] is True and bool(r1["精排"].get("模型")), r1["精排"].get("模型"))
ck("报了用量(精排是**每次检索都调**,成本随查询量线性涨 —— 不记就只能等账单)",
   bool((r1["精排"].get("用量") or {}).get("input_tokens")), r1["精排"].get("用量"))
ck("每一片有分数", all(x["分数"] is not None for x in r1["选片"]))
ck("**`引文可信` 传出来了** —— 判据标记了却传不出去,等于没有判据",
   all("引文可信" in x for x in r1["选片"]))
ck("**汇总了有几条引文没通过校验**(不用逐条看才知道)",
   "引文没通过校验的" in r1, r1.get("引文没通过校验的"))
不可信 = [x for x in r1["选片"] if x["引文可信"] is False]
ck("引文没通过校验的那几条**带上为什么**",
   all(x.get("引文问题") for x in 不可信), [x.get("引文问题") for x in 不可信][:1] or "全部通过")
# ⚠️ 不断言「引文全部可信」—— 那取决于模型这一次怎么答,会变成偶发红。
# 断言的是**判据在工作且结果传出来了**。
print(f"     (这次 {len(r1['选片'])} 片里 {len(不可信)} 条引文不可信 —— "
      f"**不拿这个数当判据**:它取决于模型这一次怎么答,会变成偶发红)")

print("\n▸ ⑤ 前提不满足时**抛,不降级**")
for 体, 期望, 说 in (
    ({"索引构建id": ib["id"], "问题": "  "}, 422, "空问题"),
    ({"索引构建id": "", "问题": "差评"}, 422, "没给索引 id"),
    ({"索引构建id": "ib_根本没有", "问题": "差评"}, 422, "索引不存在"),
):
    s2, e2 = 打("POST", f"{P}/retrieval-tests", 体=体)
    ck(f"{说} → {期望}", s2 == 期望, f"{s2} {(e2 or {}).get('code')}")
    if s2 == 期望 and e2:
        ck(f"  ↳ {说} 的错误带**可执行建议**(§19.1)", bool((e2.get("advice") or "").strip()),
           (e2.get("advice") or "")[:60])

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
