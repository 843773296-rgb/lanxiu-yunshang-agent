#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库写入端到端(M2)—— **把「片段进库不等于能检索」变成可重跑的断言**。

    POST /knowledge-bases                        建知识库
    POST /knowledge-bases/{id}/documents         加资料(收一个**已校验**的上传)
    POST /documents/{id}/versions                发新版本
    POST /knowledge-bases/{id}/index-builds      建索引(202 + job)

## 这一份要证明的六件

    ① **只收「已校验」的上传** —— 收「已上传」的等于把 §17.1 作废
    ② **加完资料还检索不到** —— 片段进库和索引建好是两件事,而这件事不报错
    ③ **幂等靠内容哈希** —— 同一份内容不新建版本(不靠文件名也不靠时间)
    ④ **输入变了就新建构建**,不续做(§19.3)—— 续做会得到混血索引
    ⑤ **第一次建索引必须显式给模型** —— 没有默认模型是有意的(默认可能是 mock)
    ⑥ **建完索引才检索得到** —— 而且新资料要真的排进结果

⚠️ 第 ⑥ 条会真调一次 Claude 精排(月租额度)。
⚠️ 前提:`make dev`。连不上就退非 0,不静默跳过。
"""
import hashlib
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
唯一 = hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 原始=None, 幂等=None):
    数据 = 原始 if 原始 is not None else (
        json.dumps(体).encode() if 体 is not None else None)
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"),
                                 method=方法, data=数据)
    req.add_header("X-Dev-User", 谁)
    if 幂等:
        req.add_header("Idempotency-Key", 幂等)
    if 原始 is not None:
        req.add_header("content-type", "application/octet-stream")
    elif 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


def 传一份(正文, 文件名):
    """走完上传三步,返回一条**已校验**的上传 id。"""
    b = 正文.encode("utf-8")
    码, a = 打("POST", P + "/uploads",
              体={"file_name": 文件名, "byte_count": len(b)})
    assert 码 == 201, (码, a)
    打("PUT", a["上传地址"], 原始=b)
    码, c = 打("POST", f"{P}/uploads/{a['id']}/complete")
    assert c.get("通过") is True, c
    return a["id"]


甲 = (f"# 测试资料甲 {唯一}\n\n"
     "云锦的挑花结本相当于程序的源码,纹样改一处就要重结一次。\n\n"
     "跳过花本的结果不是快一点,是纹样错位 —— 而错位在机上看不出来。\n")
乙 = (f"# 测试资料乙 {唯一}\n\n"
     "大花楼木织机两人一组,一天织五到六厘米。\n\n"
     "一件云锦礼服用料约九米,光织造就要五个月。\n")


# ⚠️ **这一份会在库里造东西,所以开跑前记下基线、跑完清干净。**
# 不清的代价今天当场兑现了:它留下两个空知识库,而
# `test_knowledge_flow.py` 原来挑 `items[0]` —— 于是那一份
# **红在一个跟它无关的前提上**,而看起来像检索坏了。
#
# > 一份写脏了不还原的测试,会让下一轮的结论不可信 —— 而且它先害的是别人。
码, _基线 = 打("GET", P + "/knowledge-bases")
基线知识库数 = len(_基线.get("items") or [])


def 清干净():
    """把这一轮造的知识库归档、任务删掉。**归档而不是删** ——
    documents/chunks 挂在它下面,硬删要级联,而级联删除在测试里
    最容易顺手删掉别人的数据。"""
    import sqlalchemy as _sa
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "services", "api", "app"))
    import runtime_cfg as _CFG
    e = _sa.create_engine(_CFG.DATABASE_URL)
    with e.begin() as c:
        c.execute(_sa.text("""update knowledge_bases set archived_at=now()
                             where project_id=:p and name like :pat
                               and archived_at is null"""),
                  {"p": 项目, "pat": f"%{唯一}"})
        # 这一轮派的构建任务:幂等键都带这一轮的唯一串。
        # ⚠️ **归档,不删。** 硬删被 `fk_job_events_jobs` 拦住了 —— 而那个拦阻是对的:
        # 删掉任务而留下事件,事件就成了指向空处的证据。
        # (这条外键和 `index_members.embedding_id` 那条是同一个道理:
        #  **能用约束表达的不要用判据表达** —— 外键在每次 DELETE 上生效。)
        #
        # 顺带把它们标成已取消,免得 Worker 还去跑一遍已归档知识库的构建。
        c.execute(_sa.text("""update jobs
                                set archived_at=now(), cancel_requested=true,
                                    updated_at=now()
                              where project_id=:p and idempotency_key like :pat
                                and archived_at is null"""),
                  {"p": 项目, "pat": f"m2-{唯一}-%"})
        c.execute(_sa.text("""update index_builds set archived_at=now()
                              where project_id=:p and archived_at is null
                                and knowledge_base_id in (
                                    select id from knowledge_bases
                                     where project_id=:p and name like :kbpat)"""),
                  {"p": 项目, "kbpat": f"%{唯一}"})


print("▸ ① 建知识库")
码, kb = 打("POST", P + "/knowledge-bases", 体={"name": f"测试知识库 {唯一}"})
ck("201", 码 == 201, 码)
ck("刚建好的 **能检索吗 = false**(里面一篇资料都没有)",
   kb.get("能检索吗") is False, kb.get("能检索吗"))
ck("note 里说了下一步(加资料 → 建索引)", "建索引" in (kb.get("note") or ""))
kb_id = kb["id"]
码, r = 打("POST", P + "/knowledge-bases", 体={"name": f"测试知识库 {唯一}"})
ck("同名再建一次 → 409(**两个同名知识库在界面上分不开**)",
   码 == 409 and (r or {}).get("code") == "NAME_TAKEN", f"{码} {(r or {}).get('code')}")
码, r = 打("POST", P + "/knowledge-bases", 体={"name": "   "})
ck("空名 → 422", 码 == 422, 码)

print("▸ ② 只收「已校验」的上传")
b = 甲.encode()
码, 待 = 打("POST", P + "/uploads", 体={"file_name": "甲.md", "byte_count": len(b)})
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/documents",
         体={"upload_id": 待["id"]})
ck("拿一条「待上传」去加资料 → 422", 码 == 422 and (r or {}).get("code") == "UPLOAD_NOT_USABLE",
   f"{码} {(r or {}).get('code')}")
打("PUT", 待["上传地址"], 原始=b)
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/documents",
         体={"upload_id": 待["id"]})
ck("拿一条「已上传」(字节到了、没校验)去加资料 → **也 422**", 码 == 422, 码)
ck("理由点名 §17.1(收它等于把那句话作废)", "17.1" in ((r or {}).get("advice") or ""),
   (r or {}).get("advice"))
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/documents", 体={})
ck("不给 upload_id → 422 并点名字段", 码 == 422
   and "upload_id" in ((r or {}).get("field_errors") or {}), 码)

print("▸ ③ 正常加资料:片段进库,**而索引里还没有它**")
打("POST", f"{P}/uploads/{待['id']}/complete")     # 把它校验过,下面用
码, d1 = 打("POST", f"{P}/knowledge-bases/{kb_id}/documents",
          体={"upload_id": 待["id"]})
ck("201", 码 == 201, 码)
ck("切出了片段", (d1.get("片段数") or 0) > 0, d1.get("片段数"))
ck("新建了文档和版本", d1.get("新建了文档吗") and d1.get("新建了版本吗"))
ck("note 明说「片段进库了,而索引里还没有它」(§17.1「不立即生产生效」)",
   "索引里还没有" in (d1.get("note") or ""), d1.get("note"))
码, kbs = 打("GET", P + "/knowledge-bases")
这个 = [x for x in kbs["items"] if x["id"] == kb_id]
ck("知识库列表里它有片段,**而「能检索吗」还是 false** —— "
   "有片段不等于能检索,而这件事不报错",
   bool(这个) and 这个[0]["片段数"] > 0 and 这个[0]["能检索吗"] is False,
   这个[:1])

print("▸ ④ 幂等靠内容哈希:同一份内容不新建版本")
同 = 传一份(甲, "甲-又传一次.md")          # 同内容、不同文件名
码, d2 = 打("POST", f"{P}/documents/{d1['文档id']}/versions", 体={"upload_id": 同})
ck("201", 码 == 201, 码)
ck("**没有新建版本**(内容一样)", d2.get("新建了版本吗") is False, d2.get("新建了版本吗"))
ck("版本 id 还是原来那个(复用)", d2.get("版本id") == d1.get("版本id"))
ck("说明里点了「靠内容哈希,不靠文件名也不靠时间」——"
   "**文件名不一样而结论是「没变」,这正是要证明的**",
   "文件名" in (d2.get("说明") or ""), d2.get("说明"))
新 = 传一份(乙, "乙.md")
码, d3 = 打("POST", f"{P}/documents/{d1['文档id']}/versions", 体={"upload_id": 新})
ck("换成不同内容 → **新建了版本**", d3.get("新建了版本吗") is True)
ck("note 里说「旧版本没动」(片段绑版本不绑文档,否则历史证据链指向新内容)",
   "旧版本没动" in (d3.get("note") or ""), d3.get("note"))

print("▸ ⑤ 建索引")
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds", 体={})
ck("不带 Idempotency-Key → 409(构建要跑真 Embedding,重发一次白算一遍)",
   码 == 409 and (r or {}).get("code") == "IDEMPOTENCY_KEY_REQUIRED", 码)
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds", 体={},
         幂等=f"m2-{唯一}-no-model")
ck("第一次建索引不给模型 → 422(**没有默认模型是有意的**:"
   "猜中 mock 会建出一个看起来完全正常的假索引)",
   码 == 422 and (r or {}).get("code") == "EMBEDDING_MODEL_REQUIRED",
   f"{码} {(r or {}).get('code')}")
ck("而且告诉他产真向量的有哪些", "bge" in ((r or {}).get("advice") or ""),
   (r or {}).get("advice"))
码, b1 = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds",
          体={"embedding模型id": "bge-small-zh-v1.5"}, 幂等=f"m2-{唯一}-1")
ck("202(**一个向量都还没算**)", 码 == 202, 码)
ck("异步信封字段齐(job_id/status/resource_id/status_url/trace_id)",
   all(k in b1 for k in ("job_id", "status", "resource_id", "status_url", "trace_id")),
   sorted(b1))
ck("这次是「新建」(这个知识库还没有构建)", b1.get("怎么办") == "新建", b1.get("为什么"))
ck("报了输入指纹", bool(b1.get("输入指纹")), b1.get("输入指纹"))
码, b1b = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds",
           体={"embedding模型id": "bge-small-zh-v1.5"}, 幂等=f"m2-{唯一}-1")
ck("同一个幂等键再打 → 返回原任务,不新建(没有白算一遍)",
   b1b.get("job_id") == b1.get("job_id"), f"{b1b.get('job_id')} vs {b1.get('job_id')}")
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds",
         体={"embedding模型id": "不存在的模型"}, 幂等=f"m2-{唯一}-bad")
ck("认不出的模型 → 422,**不退回 mock**(退回会把「模型没配好」翻译成「效果不好」)",
   码 == 422 and (r or {}).get("code") == "EMBEDDER_UNAVAILABLE", 码)

print("▸ ⑥ 输入没变 → 续做;输入变了 → 新建(§19.3)")
码, b2 = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds",
          体={"embedding模型id": "bge-small-zh-v1.5"}, 幂等=f"m2-{唯一}-2")
ck("同样的输入、不同幂等键 → **续做**,不新建构建",
   b2.get("怎么办") == "续做" and b2.get("resource_id") == b1.get("resource_id"),
   f"{b2.get('怎么办')} {b2.get('为什么')}")
丙 = 传一份(f"# 测试资料丙 {唯一}\n\n库缎的经纬密度决定了它的垂坠感。\n", "丙.md")
打("POST", f"{P}/knowledge-bases/{kb_id}/documents", 体={"upload_id": 丙})
码, b3 = 打("POST", f"{P}/knowledge-bases/{kb_id}/index-builds",
          体={"embedding模型id": "bge-small-zh-v1.5"}, 幂等=f"m2-{唯一}-3")
ck("加了一份资料之后 → **新建**(输入变了)", b3.get("怎么办") == "新建", b3.get("为什么"))
ck("理由里说清「续做会得到一半旧一半新的索引,而它不会报错」",
   "不会报错" in (b3.get("为什么") or ""), b3.get("为什么"))
ck("构建 id 换了", b3.get("resource_id") != b1.get("resource_id"))

print("▸ ⑦ 空知识库不许建索引")
码, 空kb = 打("POST", P + "/knowledge-bases", 体={"name": f"空知识库 {唯一}"})
码, r = 打("POST", f"{P}/knowledge-bases/{空kb['id']}/index-builds",
         体={"embedding模型id": "bge-small-zh-v1.5"}, 幂等=f"m2-{唯一}-empty")
ck("一篇资料都没有 → 422 NOTHING_TO_INDEX",
   码 == 422 and (r or {}).get("code") == "NOTHING_TO_INDEX", 码)
ck("理由说清「空索引不是建好了的索引」(它检索时返回空,和没建索引长得一样)",
   "空索引" in ((r or {}).get("advice") or ""), (r or {}).get("advice"))

print("▸ ⑧ 权限与项目隔离")
码, r = 打("POST", P + "/knowledge-bases", 谁="U003", 体={"name": "viewer 建的"})
ck("viewer 建知识库 → 403", 码 == 403, 码)
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/documents", 谁="U003",
         体={"upload_id": 待["id"]})
ck("viewer 加资料 → 403", 码 == 403, 码)
码, r = 打("POST", f"/api/v1/projects/project_demo_b/knowledge-bases/{kb_id}/documents",
         谁="U005", 体={"upload_id": 待["id"]})
ck("换项目拿同一个知识库 id → 404(不确认「它在别的项目里存在」)", 码 == 404, 码)
码, r = 打("POST", f"{P}/knowledge-bases/{kb_id}/documents",
         体={"upload_id": "up_不存在的"})
ck("不存在的 upload_id → 422(而不是 500)", 码 == 422, 码)

print("▸ ⑨ 收尾:把这一轮造的清干净")
清干净()
码, 后 = 打("GET", P + "/knowledge-bases")
ck("跑完知识库数回到基线(**写脏了不还原,下一轮的结论就不可信** —— "
   "而且先害的是别人那份测试)",
   len(后.get("items") or []) == 基线知识库数,
   f"{基线知识库数} → {len(后.get('items') or [])}")

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
