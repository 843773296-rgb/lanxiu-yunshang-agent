#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索试跑记录栏目(列表 / 详情 / 5 档打分)—— 真打接口。业务 2026-10-08 要的。

    POST   /retrieval-tests                 跑一次 → **自动存一条试跑**
    GET    /retrieval-runs                  列表 + 汇总
    GET    /retrieval-runs/{id}             整条链路(同检索实验室)+ revision
    PATCH  /retrieval-runs/{id}/rating      5 档打分(要 If-Match)

## 这一组每一条对着一种「看起来对了而实际漏了」

   ① 跑完没存上 → 列表永远是空的,而**那和「没人跑过」长得一模一样**
   ② 没评过的给 0 分 → 平均分被一堆 0 拖下去,而「还没人评」不是「评了最低档」
   ③ 平均分不带样本量 → 3 条算出的 4.3 和 30 条算出的 4.3 在那个数字上一样
   ④ 打分不要 If-Match → 两个人同时评,后到的**静默覆盖**前一个
   ⑤ 汇总跟着筛选走 → 筛着看的时候那个平均分只代表筛出来的那几条
   ⑥ 快照原样吐出来 → 这个栏目成了一条**绕开语料权限的后门**

## ⚠️ 这一份**不调模型**(要精排=false、不要生成),所以不花钱、能进 CI 门禁

真调模型那条链在 `test_knowledge_flow.py` 的第 ④ / ④.5 组。
而这一份要验的是**记录 / 列表 / 评价**那一层,它和模型无关。

## 前提

要先 `make dev`(服务在 8801)、要有语料和一个已就绪的索引。
⚠️ 缺前提时**明确报「没东西可测」并退非 0**,不静默跳过 ——
「跳过了」和「通过了」在输出上长得一模一样。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except urllib.error.URLError as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)
    except Exception as e:
        # ⚠️ **这一支和上一支分开,而这不是洁癖。**
        # 第一版把所有异常都报成「连不上,先 make dev」—— 而第一次真撞上的是
        # `'ascii' codec can't encode`(URL 里带了中文、没转义)。
        # > 一句「连不上」和一句「我自己把 URL 拼坏了」,
        # > **在那行输出上长得一模一样** —— 而它会让人去重启服务,
        # > 而服务一直是好的。
        print(f"     请求发不出去(**不是连不上**){type(e).__name__}: {e}")
        sys.exit(1)


print("=" * 92)
print("检索试跑记录栏目 · 列表 / 详情 / 5 档打分(**不调模型**)")
print("=" * 92)

print("\n▸ ① 跑一次检索 → **自动存一条试跑**")
s, kbs = 打("GET", f"{P}/knowledge-bases?limit=100")
if s != 200 or not (kbs or {}).get("items"):
    print("❌ 没有知识库 —— 先 `python tools/ingest_lanxiu.py`。**这不叫跳过,叫没东西可测**")
    sys.exit(1)
能检索的 = [x for x in kbs["items"] if x["能检索吗"]]
if not 能检索的:
    print("❌ 没有能检索的知识库(要一个「已就绪」的索引)—— **不在没有前提的时候出结论**")
    sys.exit(1)
kb = 能检索的[0]
s, builds = 打("GET", f"{P}/knowledge-bases/{kb['id']}/index-builds")
就绪 = [x for x in (builds or {}).get("items", []) if x["status"] == "已就绪"]
ck("找到一个已就绪的索引", bool(就绪), f"{kb['name']} · {len(就绪)} 个")
if not 就绪:
    sys.exit(1)
ib = 就绪[0]

s, 链 = 打("POST", f"{P}/retrieval-tests",
         体={"索引构建id": ib["id"], "问题": "客户给了差评要怎么处理",
            # ⚠️ 两个都关掉 —— 这一份不花钱(它验的是记录那一层,和模型无关)
            "要精排": False, "要生成": False})
ck("200", s == 200, s if s == 200 else 链)
存 = (链 or {}).get("存档") or {}
ck("🔑 **跑完自动存了一条** —— 存不上的话列表永远是空的,"
   "而那和「没人跑过」长得一模一样",
   存.get("存了吗") is True, 存.get("为什么") or 存.get("试跑id"))
rid = 存.get("试跑id")
if not rid:
    print("❌ 没拿到试跑 id,下面都没法验")
    sys.exit(1)
ck("存档失败时会说清为什么(这次成功,所以只验它带了下一步怎么做)",
   bool(存.get("下一步")), (存.get("下一步") or "")[:60])

print("\n▸ ② 列表:分数 / 来源 / 答案那一档都要看得见")
s, L = 打("GET", f"{P}/retrieval-runs?limit=100")
ck("200", s == 200, s)
我的 = [x for x in L["items"] if x["id"] == rid]
ck("刚跑的那条在列表里", len(我的) == 1, len(我的))
r0 = 我的[0] if 我的 else {}
ck("带着问题、来源、选了几片", bool(r0.get("问题")) and r0.get("来源") == "检索实验室"
   and r0.get("选了几片") is not None,
   f"{r0.get('来源')} · 选了 {r0.get('选了几片')} 片")
ck("🔑 没评过的 `评分` 是 **None 不是 0** —— "
   "「还没人评」和「评了最低档」在一个 0 上长得一模一样",
   r0.get("评分") is None and r0.get("评分档位") is None, r0.get("评分"))
ck("答案那一档是四档之一(这次没要生成,所以是「这次没要」)",
   r0.get("答案那一档") == "这次没要", r0.get("答案那一档"))
ck("列表给了 `revision` —— **打分就在列表上**,"
   "要人先点进详情才拿得到那个数的话,打分会被嫌麻烦而没人做",
   r0.get("revision") is not None, r0.get("revision"))
汇 = L["汇总"]
ck("汇总里「还没评的」数得出来", 汇["还没评的"] >= 1, 汇["还没评的"])
ck("🔑 平均分**带样本量的说明**(3 条算的 4.3 和 30 条算的 4.3 不一样)",
   bool(汇.get("平均分怎么读")), 汇.get("平均分怎么读"))
ck("🔑 写清了 **chat 现在不走这条链** —— "
   "一个「记录 chat 检索」的栏目和一个永远是空的栏目,在那个页面上长得一样",
   "chat" in (汇.get("note") or ""), (汇.get("note") or "")[:70])
ck("chat 的条数单独数出来(接上那天能一眼看出哪些是它的)",
   "chat 的有几条" in 汇, 汇.get("chat 的有几条"))

print("\n▸ ③ 汇总**不跟着筛选走**")
s, L2 = 打("GET", f"{P}/retrieval-runs?limit=100&source=chat")
ck("按来源筛得动", s == 200 and all(x["来源"] == "chat" for x in L2["items"]),
   f"{len(L2['items'])} 条")
ck("🔑 筛了之后**汇总里的总条数不变** —— "
   "跟着筛的话,那个平均分只代表筛出来的那几条,而人读到的是「这一版的平均分」"
   "(切片栏目上刚踩过同一个坑:混版本告警在筛选状态下消失)",
   L2["汇总"]["一共几条"] == 汇["一共几条"],
   f"{L2['汇总']['一共几条']} vs {汇['一共几条']}")

print("\n▸ ④ 详情:整条链路(内容同检索实验室)+ 评价 + revision")
s, D = 打("GET", f"{P}/retrieval-runs/{rid}")
ck("200", s == 200, s)
ck("链路在里面,而且形状和实验室那一份一样(前端复用同一个渲染函数)",
   all(k in (D.get("链路") or {}) for k in ("原问", "候选", "选片", "召回数", "截断")),
   sorted((D.get("链路") or {}).keys())[:6])
ck("每一片都有**能翻回原文的证据串**",
   all(" · 第 " in x["证据"] for x in (D["链路"].get("选片") or [])))
ck("给了 `revision`(打分要用它做 If-Match)", D.get("revision") is not None,
   D.get("revision"))
ck("给了**档位表**(5 档各是什么意思)—— "
   "只给 1-5 的话,「3 分」每个人心里一套,而平均分会把这种差别算进去",
   len((D.get("评价") or {}).get("档位表") or {}) == 5,
   (D.get("评价") or {}).get("档位表"))
ck("「还没评」是个显式字段,不让人从 null 里猜",
   (D.get("评价") or {}).get("还没评") is True)
# ⚠️ ACL 那一支:两级 ACL 现在全空,所以**隐去的片数必然是 0** ——
# 这里断言的是「这个字段在、而且现在是 0」,**不假装验过了隐去那条路**。
# > 一条「验过了权限重过一遍」的断言,和一条「在全空的 ACL 上恒为真」的,
# > 在它绿的时候长得一模一样 —— 所以把这件事写出来。
ck("隐去片数这个字段在(**而这次是 0:两级 ACL 现在全空,"
   "所以隐去那条路这一份验不到** —— 它在 test_corpus_acl_live 里验)",
   D.get("隐去了几片正文") == 0, D.get("隐去了几片正文"))
ck("跨项目取不到(404 而不是 403 —— **不泄露这个 id 在别的项目里存在**)",
   打("GET", f"/api/v1/projects/project_demo_b/retrieval-runs/{rid}")[0] == 404)

print("\n▸ ⑤ 打分:5 档 + **要 If-Match**")
s, e = 打("PATCH", f"{P}/retrieval-runs/{rid}/rating", 体={"评分": 4})
ck("不带 If-Match → 409(两个人同时评,后到的会静默覆盖前一个)",
   s == 409 and (e or {}).get("code") == "IF_MATCH_REQUIRED", f"{s} {(e or {}).get('code')}")
rev = D["revision"]
for 值, 说 in ((7, "7 分"), (0, "0 分"), ("四分", "字符串"), (3.5, "小数")):
    s, e = 打("PATCH", f"{P}/retrieval-runs/{rid}/rating",
             体={"评分": 值}, 头={"If-Match": str(rev)})
    ck(f"{说} → 422", s == 422, f"{s} {(e or {}).get('code')}")
    if s == 422:
        ck(f"  ↳ {说} 的错误里**列出了 5 档各是什么意思**(§19.1 可执行建议)",
           "档" in ((e or {}).get("advice") or ""), ((e or {}).get("advice") or "")[:50])
        break        # 四条都验一遍太啰嗦,验到一条带建议就够

s, ok = 打("PATCH", f"{P}/retrieval-runs/{rid}/rating",
          体={"评分": 4, "评语": "找对了那两段,但没给具体话术"},
          头={"If-Match": str(rev)})
ck("正常打 4 分 → 200", s == 200, s if s == 200 else ok)
ck("带回档位的**名字**(不是只有数字)", ok.get("评分档位"), ok.get("评分档位"))
ck("revision 前进了(下一次打分要用新的)", ok.get("revision") == rev + 1,
   f"{ok.get('revision')} vs {rev}")
s, e = 打("PATCH", f"{P}/retrieval-runs/{rid}/rating",
         体={"评分": 2}, 头={"If-Match": str(rev)})
ck("🔑 拿旧 revision 再打 → 409(**先点的那个人的分数不许被静默盖掉**)",
   s == 409 and (e or {}).get("code") == "REVISION_CONFLICT",
   f"{s} {(e or {}).get('code')}")

print("\n▸ ⑥ 评价进了列表和详情(业务点名要的)")
s, L3 = 打("GET", f"{P}/retrieval-runs?limit=100")
我 = [x for x in L3["items"] if x["id"] == rid][0]
ck("列表上看得到分数 + 档位名 + 评语 + 谁评的",
   我["评分"] == 4 and bool(我["评分档位"]) and bool(我["评语"]) and bool(我["谁评的"]),
   f"{我['评分']} · {我['评分档位']} · {我['谁评的']}")
ck("汇总里的平均分有数了,而且说明里带样本量",
   L3["汇总"]["平均分"] is not None and "条评价" in (L3["汇总"]["平均分怎么读"] or ""),
   f"{L3['汇总']['平均分']} · {L3['汇总']['平均分怎么读']}")
ck("各档分布里那一档的名字也在(**不是只有数字**)",
   any("4 · " in k for k in (L3["汇总"]["各档分布"] or {})),
   list((L3["汇总"]["各档分布"] or {}).keys()))
s, D2 = 打("GET", f"{P}/retrieval-runs/{rid}")
ck("详情上也看得到(谁评的 / 什么时候评的 / 评语)",
   D2["评价"]["评分"] == 4 and bool(D2["评价"]["谁评的"])
   and bool(D2["评价"]["什么时候评的"]), D2["评价"])
ck("「还没评」翻面了", D2["评价"]["还没评"] is False)

print("\n▸ ⑦ 打分**覆盖**了,而覆盖要留痕(这张表只存当前评价)")
s, ok2 = 打("PATCH", f"{P}/retrieval-runs/{rid}/rating",
           体={"评分": 2, "评语": "再看一遍,其实话术那块缺得厉害"},
           头={"If-Match": str(ok["revision"])})
ck("改成 2 分 → 200", s == 200, s)
# ⚠️ 查询参数里的中文**要转义** —— 不转的话 urllib 在 ascii 编码那一步就炸了
# ⚠️ **用 U001 读审计,不是 U002。** 跑试跑/打分的那个角色(U002)
# **没有「查看审计」这条能力** —— 403。
# > 一条「审计里没有这次打分」和一条「我没权限看审计」,
# > **在那个空列表上长得一模一样** —— 所以这里换身份,而且把原因写下来。
# (顺带说明了一件对的事:打分的人看不到审计,而审计记着他改了什么。)
s, A = 打("GET", f"{P}/audit-events?action="
         + urllib.parse.quote("评价检索试跑") + "&days=1", 谁="U001")
ck("200", s == 200, s)
我的审计 = [x for x in (A or {}).get("记录", [])
         if rid in json.dumps(x.get("对象") or {}, ensure_ascii=False)]
ck("🔑 审计里有这两次打分,而且**记了从几分改成几分** —— "
   "一个能被悄悄改掉的分数,在报表里和一个没被改过的长得一样",
   len(我的审计) >= 2 and any("原来几分" in json.dumps(x["对象"], ensure_ascii=False)
                           for x in 我的审计),
   [x.get("对象") for x in 我的审计[:2]])

print("\n" + "=" * 92)
if 挂:
    print(f"❌ 过 {len(过)} / 挂 {len(挂)}")
    for x in 挂:
        print(f"   · {x}")
    sys.exit(1)
print(f"✅ 过 {len(过)} 条全过")
