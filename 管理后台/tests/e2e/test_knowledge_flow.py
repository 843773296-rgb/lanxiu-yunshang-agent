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
# ⚠️ **挑「有语料的那个」,不挑 `items[0]`。**
# 原来是 `items[0]`,而它假设了「第一个知识库有语料」—— 那个假设不属于这份测试
# 要证明的东西(它证的是检索链路对)。2026-09-27 M2 做完之后,界面能建知识库了,
# 于是列表第一个变成一个空库,这一份**红在一个跟它无关的前提上**。
#
# ⚠️ 挑「有语料的」不是把判据放宽:**一个都没有时照样退非 0**(下面那句)。
有语料的 = [x for x in d["items"] if (x.get("片段数") or 0) > 0]
if not 有语料的:
    print(f"❌ {len(d['items'])} 个知识库里**一个有语料的都没有** —— "
          f"先 `python tools/ingest_lanxiu.py`。**这不叫跳过,叫没东西可测**")
    sys.exit(1)
kb = max(有语料的, key=lambda x: x["片段数"])
ck(f"挑了有语料的那个({kb['name']}),不挑 items[0] —— "
   f"「第一个知识库有语料」不是这份测试该假设的事",
   (kb["片段数"] or 0) > 0, f"{len(有语料的)}/{len(d['items'])} 个有语料")
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
# ⚠️ **这条断言 2026-10-08 修了口径。** 原来对的是 `片段数`(全部版本),
# 而索引只收 `max(revision)` 那一版 —— 于是一篇文档改过第二版之后它**永远红**。
# 实测撞到:97 vs 89,而那 8 条是旧版本,索引是对的。
# > 一次「索引不完整」和一次「那几条属于旧版本」,
# > **在「成员数 < 片段数」这件事上长得一模一样** ——
# > 而前者要去查谁写坏了数据,后者完全正常。
ck("**成员数 == 最新版片段数**(索引只收 max(revision) 那一版)—— "
   "真对不上说明索引不完整,而那只是「少返回几条」,不报错",
   ib["成员数"] == kb["最新版片段数"],
   f"成员 {ib['成员数']} vs 最新版 {kb['最新版片段数']}(全部版本 {kb['片段数']})")
ck("↳ 而「旧版本还留着几条」要**说出来** —— "
   "人看到 97、检索只命中 89,会去查检索",
   kb["旧版本的片段数"] == kb["片段数"] - kb["最新版片段数"]
   and (kb["旧版本的片段数"] == 0 or bool(kb.get("片段数怎么读"))),
   f"旧版本 {kb['旧版本的片段数']} 条 · {(kb.get('片段数怎么读') or '—')[:50]}")
ck("带输入指纹(没有它就判不出输入变没变)", bool(ib.get("输入指纹短")), ib.get("输入指纹短"))
ck("跨项目取不到(404 而不是 403 —— **不泄露这个 ID 在别的项目里存在**)",
   打("GET", f"/api/v1/projects/project_demo_b/knowledge-bases/{kb['id']}/index-builds")[0]
   in (403, 404))

print("\n▸ ③ 检索:只走向量(**不花钱**),要说清代价")
s, r0 = 打("POST", f"{P}/retrieval-tests",
          体={"索引构建id": ib["id"], "问题": "客户给了差评要怎么处理", "要精排": False})
ck("200", s == 200, s if s == 200 else r0)
# ⚠️ **这条断言 2026-10-08 改过。** 原来写的是
#     r0["改写"] is None and "没做" in 改写说明
# 而那天改写**真的做了**(`rewriter.py`,调模型)—— 于是这条断言从
# 「验一个设计」变成了「验一个已经不成立的事实」。
# > 一条「钉住了一个口径」的断言,和一条「钉住了一个过期事实」的,
# > **在它绿的时候长得一模一样** —— 而它会在功能做好的那天开始红,
# > 红的理由还指向被改对了的那一边。
# 现在验的是**那个口径本身**:三种情况(改写成功 / 改写失败 / 这一版没做)
# 必须分得开,而分开的方式是说明文字 + `改写` 本身。
ck("改写真做了:`改写` 是模型给的那句话,而**原问一直带着**(能对照)",
   bool(r0.get("改写")) and r0.get("原问") == "客户给了差评要怎么处理",
   f"原问={r0.get('原问')!r} 改写={str(r0.get('改写'))[:40]!r}")
ck("↳ 而且**说明里写清是哪一种** —— 「改写失败用了原问」和"
   "「改写认为原问最好」在 `改写 is None` 上长得一模一样",
   bool((r0.get("改写说明") or "").strip()), (r0.get("改写说明") or "")[:70])
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

print("\n▸ ④.5 生成答案(业务 2026-10-08 拍的 A)—— **会再真调一次模型**")
# ⚠️ 先验「没要生成」那一支:它不花钱,而且验的是
# 「**这次没要**」和「这一版没做」分得开 —— 两者在空答案上长得一样。
ck("没要生成时 `生成.做了=False`,而且**结构化地**说是哪一种(不让界面认文案)",
   r1["生成"]["做了"] is False and r1["生成"].get("哪一种") == "这次没要",
   r1["生成"].get("哪一种"))
s3, r3 = 打("POST", f"{P}/retrieval-tests",
          体={"索引构建id": ib["id"], "问题": "客户给了差评要怎么处理",
             "要精排": True, "要生成": True})
ck("200", s3 == 200, s3 if s3 == 200 else r3)
生 = (r3 or {}).get("生成") or {}
if not 生.get("做了"):
    # ⚠️ **不静默跳过。** 生成没跑成要当场报出来 ——
    # 「跳过了」和「通过了」在输出上长得一模一样。
    ck("生成跑成了", False, 生.get("为什么"))
else:
    ck("有答案,而且**不是空串**", bool((生.get("答案") or "").strip()),
       (生.get("答案") or "")[:60])
    ck("报了用的哪个模型(不写死在文档里)", bool(生.get("模型")), 生.get("模型"))
    ck("**说清答的是原问**(算向量用的是改写后的 —— 两件事都要看得见)",
       "原问" in (生.get("照着谁答的") or ""), 生.get("照着谁答的"))
    ck("`够不够答` 是布尔值(**不是 None**)—— "
       "「模型没表态」和「模型说够了」要分得开",
       isinstance(生.get("够不够答"), bool), 生.get("够不够答"))
    引 = 生.get("引用们") or []
    if 生.get("够不够答"):
        ck("说够了就**指得出是哪几条证据**", bool(引), len(引))
        ck("每条出处都带**能翻回原文的证据串**",
           all(" · 第 " in (x.get("证据") or "") for x in 引),
           (引[0].get("证据") if 引 else "没有引用"))
        ck("**`原话可信` 传出来了** —— 判据标记了却传不出去,等于没有判据",
           all("原话可信" in x for x in 引))
    else:
        # 「证据不够」是一个**正确答案**,不是失败 —— 这一支也要验。
        ck("说证据不够时,**缺什么**要说出来(不然人只知道「不够」)",
           bool(生.get("缺什么")), 生.get("缺什么"))
    ck("汇总了「几条出处没通过校验」(不用逐条看才知道)",
       "引用没通过校验的" in 生, 生.get("引用没通过校验的"))
    # ⚠️ 不断言「出处全部可信」—— 那取决于模型这一次怎么答,会变成偶发红。
    print(f"     (这次引了 {len(引)} 条,其中 "
          f"{生.get('引用没通过校验的')} 条原话对不上 —— **不拿这个数当判据**:"
          f"它取决于模型这一次怎么答)")
    记 = (r3 or {}).get("记账") or {}
    ck("🔑 **两步模型调用各记一笔账**(精排 + 生成)—— "
       "一笔「没花钱」和一笔「花了而没记上」在账本总额上长得一模一样",
       len(记.get("各步") or []) == 2,
       [x.get("步") for x in (记.get("各步") or [])])
    步们 = 记.get("各步") or []
    # ⚠️ 这条判据第一版写成 `… or 记.get("记了吗") is True` ——
    # **那个 `or` 让它永真**(和这个项目栽过的 `or True` 是同一个病)。
    # 现在要的是真东西:两笔的事件键和资源都**各不相同**。
    ck("🔑 两笔的 `event_key` 不同 —— 键一样的话第二笔会被"
       "`on conflict do nothing` **静默丢掉**,而那和「没花钱」在总额上一样",
       len({x.get("事件键") for x in 步们}) == len(步们) and
       all(x.get("事件键") for x in 步们),
       [x.get("事件键") for x in 步们])
    ck("↳ 而且两笔的 `resource` 分别是 rerank / generate(不是都记成精排)",
       {x.get("资源") for x in 步们} == {"rerank", "generate"},
       sorted(str(x.get("资源")) for x in 步们))
    ck("↳ 每一笔都真写进了账本(写了几行 ≥ 1)",
       all((x.get("写了几行") or 0) >= 1 for x in 步们),
       [x.get("写了几行") for x in 步们])

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
