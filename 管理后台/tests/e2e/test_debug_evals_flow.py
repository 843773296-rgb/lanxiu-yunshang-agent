#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最后七条端到端:调试四条 + 评测两条 + 改片段一条。

## 这七条合起来守一句话:**调试出来的和复核过的,都不许冒充正式的**

| 冒充 | 对策 |
|---|---|
| 从中间节点测一段,报成「端到端通过了」 | `算端到端通过吗=false`,而且**必须说清上游是模拟还是历史** |
| 调试时真把东西写出去 | 写工具默认换成模拟适配器,**并给出替换清单** |
| 从历史点重开,原地改旧的那次 | **新 Run + parent_run_id**,旧的一个字不动 |
| 复核把判分器那条分数改掉 | **新增一条并指向被取代的那条**(§18) |
| 改片段把已建索引引的那一版改了 | **出新候选**,旧版本原样留着 |
| 看调试运行顺手看到客户对话 | 原文**按字段授权**,没授权只给形状 |
| 一个没有基线的分数被当成结论 | **候选和基线都要给** |

## ⚠️ 「复核不许覆盖」为什么是这一组里最硬的一条

覆盖的后果不是丢一条记录,是**「判分器当时给了多少」永远答不出来了** ——
而那正是「判分器准不准」这个问题唯一的数据来源。
> 一旦把判分器的输出改成人的结论,你就再也没法评估判分器了。

⚠️ 前提 `make dev`。这一份自己造分数行(夹具),跑完自己清。
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request, uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
尾 = uuid.uuid4().hex[:6]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U002", 键=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 键: req.add_header("Idempotency-Key", 键)
    if 体 is not None: req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"null")
        except Exception: return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`"); sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务, 连接                # noqa: E402


def 一个(表, 条件=""):
    with 连接() as c:
        return c.execute(text(f"select id from {表} where project_id=:p {条件} "
                              f"order by created_at desc limit 1"),
                         {"p": 项目}).scalar()


def 造一条判分器分数(评测id):
    """夹具:造一个评分项 + 一条判分器给的分。**这是测试夹具,不是接口能做的事。**"""
    项id, 分id = f"ei_t{尾}", f"sc_t{尾}"
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        c.execute(text("""insert into evaluation_items
            (id, organization_id, project_id, evaluation_id, created_at, created_by,
             updated_at, revision)
            values (:i,:o,:p,:e, now(),'test', now(), 1)
            on conflict do nothing"""),
                  {"i": 项id, "o": org, "p": 项目, "e": 评测id})
        c.execute(text("""insert into scores
            (id, organization_id, project_id, evaluation_item_id, dimension,
             value, value_known, source, at, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:it,'准确', 0.6, true, '判分器', now(),
                    now(),'test', now(), 1)"""),
                  {"i": 分id, "o": org, "p": 项目, "it": 项id})
    return 项id, 分id


def 造一条文档片段():
    """夹具:造一条 `documents` + 一条 `document_versions`。跑完自己清。

    ## ⚠️ 为什么自己造,而不是 `一个("document_versions")` 取最新一条

    原来那样写。在 CI 上(**从零建库**)它取到的是 `None` —— 于是 URL 变成
    `/document-versions/None/revisions`,接口老实地回了 404,
    而**报出来的样子是「改片段这个接口坏了」**。我对着那条 404 猜了一整轮。
    > **一个把自己的错报成被测对象的错的判据,会把人送去查一个没坏的东西。**

    本地从来撞不到:我那个库里躺着 200 条历次上传的残留。而且
    **没有任何 seed 脚本灌 `document_versions`** —— 它只来自上传那条路,
    而 `test_upload_flow` 跑在这份前面、**并且收尾清掉了自己的夹具**。
    > **一条靠残留成立的顺序,在第一次从零跑的那天才会露出来。**

    造出来的 id 直接拿去用,**不再过 `一个()`** —— 过一遍的话它仍然可能
    取到残留里更新的某一条,于是本地测的还是别人的数据。
    """
    文档id, 版本id = f"doc_t{尾}", f"dv_t{尾}"
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        # ⚠️ `knowledge_base_id` 留空:它可空,而填一个不存在的会撞外键。
        c.execute(text("""insert into documents
            (id, organization_id, project_id, created_at, created_by,
             updated_at, revision)
            values (:i,:o,:p, now(),'test', now(), 1)
            on conflict do nothing"""),
                  {"i": 文档id, "o": org, "p": 项目})
        # ⚠️ `source_info` 是 **JSONB** —— 塞裸串会存成一个 JSON 字符串而不是
        # 对象,而它读出来长得很像对象。这个仓库在这上面栽过十次,
        # 所以这里显式 `cast(... as jsonb)` 配 `json.dumps`。
        c.execute(text("""insert into document_versions
            (id, organization_id, project_id, document_id, object_key,
             content_hash, effective_at, source_info,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:d,:k,:h, now(), cast(:si as jsonb),
                    now(),'test', now(), 1)
            on conflict do nothing"""),
                  {"i": 版本id, "o": org, "p": 项目, "d": 文档id,
                   "k": f"test/{尾}/工期说明.md", "h": f"h_t{尾}",
                   "si": json.dumps({"来路": "test_debug_evals_flow 的夹具"},
                                    ensure_ascii=False)})
    return 文档id, 版本id


def 清掉():
    with 事务() as c:
        c.execute(text("delete from scores where project_id=:p and "
                       "evaluation_item_id like :n"), {"p": 项目, "n": f"ei_t{尾}"})
        c.execute(text("delete from evaluation_items where project_id=:p and id like :n"),
                  {"p": 项目, "n": f"ei_t{尾}"})
        # ⚠️ 按 **document_id** 删版本,不按 id 前缀 ——
        # 「改片段」那个接口**新建的那一版** id 是服务端生成的,不带 `_t{尾}`。
        # 按前缀删会把它留下来,而留下来的那条顶着 RESTRICT 外键,
        # 下一句删 documents 就会失败(**而失败发生在收尾里,最容易被当成没事**)。
        c.execute(text("delete from document_versions where project_id=:p "
                       "and document_id=:d"), {"p": 项目, "d": f"doc_t{尾}"})
        c.execute(text("delete from documents where project_id=:p and id=:d"),
                  {"p": 项目, "d": f"doc_t{尾}"})


def main():
    print("\n\033[1m▸ 最后七条 · 调试出来的不许冒充正式的\033[0m")
    R = 一个("execution_runs")
    V = 一个("dataset_versions", "and frozen_samples is not null")
    # ⚠️ **夹具拿不到就当场说清,别带着 `None` 去打接口。**
    # 带着 `None` 打出来是一条 404 —— 那是**我这份测试的错,报成了接口的错**。
    for 名, 值, 从哪来 in (("execution_runs", R, "seed_demo / 编排层跑过一次"),
                      ("dataset_versions(有 frozen_samples 的)", V,
                       "tools/seed_datasets.py")):
        if 值 is None:
            ck(f"⚠️ 夹具缺了:`{名}` 一条都没有 —— "
               f"**这是夹具的问题,不是接口的问题**(来源:{从哪来})", False, None)
            print(f"\n❌ 过 {len(过)} / 挂 {len(挂)}(夹具不全,**没往下跑**)")
            for x in 挂: print("   挂:", x)
            return 1
    # `document_versions` **自己造** —— 见 `造一条文档片段()` 里的那段。
    _, DV = 造一条文档片段()

    # ── 一、看一次运行:原文按字段授权 ──────────────────────────────
    码, a = 打("GET", f"{P}/runs/{R}", 谁="U002")
    ck("GET /runs/{id} 200", 码 == 200, 码)
    ck("**没那条专项授权 → 只给形状**", (a or {}).get("看得到原文吗") is False
       and "字>" in json.dumps((a or {}).get("输入"), ensure_ascii=False),
       str((a or {}).get("输入"))[:50])
    码, b = 打("GET", f"{P}/runs/{R}", 谁="U004")
    ck("对照:有授权 → 给原文(这道闸不是一刀切)",
       (b or {}).get("看得到原文吗") is True, (b or {}).get("看得到原文吗"))
    ck("两个身份拿到的**不是同一份**", (a or {}).get("输入") != (b or {}).get("输入"))
    码, 体 = 打("GET", f"{P}/runs/run_根本没有", 谁="U002")
    ck("不存在的运行 → 404", 码 == 404, 码)

    # ── 二、从节点测试:不计为端到端通过 ────────────────────────────
    码, 体 = 打("POST", f"{P}/node-tests", {"节点": "n1"}, 键=f"nt-{尾}-1")
    ck("不说上游来源 → 422(**从中间起跑,上游是编的还是真发生过的,读结果的人要知道**)",
       码 == 422 and "上游来源" in ((体 or {}).get("field_errors") or {}), 码)
    码, 体 = 打("POST", f"{P}/node-tests", {"节点": "n1", "上游来源": "模拟数据"})
    ck("不带幂等键 → 409", 码 == 409, 码)
    码, nt = 打("POST", f"{P}/node-tests",
              {"节点": "n1", "上游来源": "模拟数据", "运行": R}, 键=f"nt-{尾}-2")
    ck("正常 → 202", 码 == 202, (码, (nt or {}).get("code")))
    ck("**算端到端通过吗 = false**(§5.3)", (nt or {}).get("算端到端通过吗") is False)
    ck("**给出写工具替换清单**(不是一个「已替换=true」的布尔)",
       isinstance((nt or {}).get("写工具替换清单"), list)
       and (nt or {}).get("写工具替换清单"),
       (nt or {}).get("写工具替换清单"))
    码, 体 = 打("POST", f"{P}/node-tests",
              {"节点": "n1", "上游来源": "模拟数据", "运行": "run_没有这个"},
              键=f"nt-{尾}-3")
    ck("给了不存在的源运行 → 422(**不静默当成从头跑**)",
       码 == 422 and (体 or {}).get("code") == "RUN_NOT_FOUND", 码)

    # ── 三、从历史点另开:新 Run,旧的一个字不动 ──────────────────────
    with 连接() as c:
        旧状态 = c.execute(text("select status, revision from execution_runs "
                             "where project_id=:p and id=:i"),
                        {"p": 项目, "i": R}).first()
    码, fk = 打("POST", f"{P}/execution-runs/{R}/fork-test", {"从第几步": 3},
               键=f"fk-{尾}-1")
    ck("fork-test → 202", 码 == 202, (码, (fk or {}).get("code")))
    ck("是**新的 Run**,而且指着父运行",
       (fk or {}).get("id") != R and (fk or {}).get("从哪次分叉") == R,
       ((fk or {}).get("id"), (fk or {}).get("从哪次分叉")))
    with 连接() as c:
        新状态 = c.execute(text("select status, revision from execution_runs "
                             "where project_id=:p and id=:i"),
                        {"p": 项目, "i": R}).first()
    ck("**旧那次运行一个字没动**(不原地改旧目标冒充同一个任务)",
       tuple(旧状态) == tuple(新状态), (tuple(旧状态), tuple(新状态)))
    码, fk2 = 打("POST", f"{P}/execution-runs/{R}/fork-test", {"从第几步": 3},
                键=f"fk-{尾}-1")
    ck("同幂等键再 fork → 不新建", (fk2 or {}).get("新建了吗") is False)

    # ── 四、事件补拉:空的时候说清是哪一种空 ────────────────────────
    码, ev = 打("GET", f"{P}/execution-runs/{R}/events?after_seq=0")
    ck("GET events 200", 码 == 200, 码)
    ck("给出「最新的 seq」和「下一次从这儿拉」(空的时候才分得出是哪一种空)",
       "最新的 seq" in (ev or {}) and "下一次从这儿拉" in (ev or {}),
       {k: (ev or {}).get(k) for k in ("条数", "最新的 seq")})
    ck("说明里点明**每一轮重新鉴权**", "重新鉴权" in str((ev or {}).get("note")))

    # ── 五、建评测:四个都要在场 ────────────────────────────────────
    码, 体 = 打("POST", f"{P}/evaluations",
              {"候选": "pv_new", "数据集版本": V, "判据版本": "v2"},
              谁="U004", 键=f"ev-{尾}-1")
    ck("不给基线 → 422(**没有基线的分数不能当结论**)",
       码 == 422 and "基线" in ((体 or {}).get("field_errors") or {}), 码)
    码, 体 = 打("POST", f"{P}/evaluations",
              {"候选": "a", "基线": "b", "数据集版本": "dv_没有这个", "判据版本": "v2"},
              谁="U004", 键=f"ev-{尾}-2")
    ck("数据集版本不存在 → 422(**不静默用「当前样本」**)",
       码 == 422 and (体 or {}).get("code") == "DATASET_VERSION_NOT_FOUND", 码)
    码, e = 打("POST", f"{P}/evaluations",
             {"候选": "pv_new", "基线": "pv_old", "数据集版本": V, "判据版本": "判据v2"},
             谁="U004", 键=f"ev-{尾}-3")
    ck("四个都给 → 202", 码 == 202, (码, (e or {}).get("code")))
    eid = (e or {}).get("id")
    码, e2 = 打("POST", f"{P}/evaluations",
              {"候选": "pv_new", "基线": "pv_old", "数据集版本": V, "判据版本": "判据v2"},
              谁="U004", 键=f"ev-{尾}-3")
    ck("同幂等键再建 → **没有再跑一遍题**", (e2 or {}).get("新建了吗") is False)

    # ── 六、人工复核:新增一条,原来那条不动 ─────────────────────────
    项id, 分id = 造一条判分器分数(eid)
    码, 体 = 打("POST", f"{P}/evaluations/{eid}/reviews",
              {"评分项": 项id, "维度": "准确", "新分": 1.0}, 谁="U004")
    ck("不写理由 → 422(**推翻机器的理由是下次改判据的唯一线索**)", 码 == 422, 码)
    码, 体 = 打("POST", f"{P}/evaluations/{eid}/reviews",
              {"评分项": "ei_根本没有", "维度": "准确", "新分": 1.0, "理由": "x"},
              谁="U004")
    ck("没有可复核的那条 → 422(**不给一条凭空的人工分**)",
       码 == 422 and (体 or {}).get("code") == "NO_SCORE_TO_REVIEW", 码)
    码, rv = 打("POST", f"{P}/evaluations/{eid}/reviews",
              {"评分项": 项id, "维度": "准确", "新分": 1.0,
               "理由": "判分器把「六周」读成了超期,而合同里写的就是六周"}, 谁="U004")
    ck("复核 → 201", 码 == 201, (码, (rv or {}).get("code")))
    ck("**指向被它取代的那条**", (rv or {}).get("取代了") == 分id,
       ((rv or {}).get("取代了"), 分id))
    with 连接() as c:
        老分 = c.execute(text("select value, source, rationale from scores "
                            "where project_id=:p and id=:i"),
                       {"p": 项目, "i": 分id}).first()
    ck("**判分器那条一个字没动**(§18:原始结果不被复核覆盖)",
       老分 and float(老分[0]) == 0.6 and 老分[1] == "判分器", tuple(老分 or ()))
    # 这正是 `evals.有效分数()` 的口径
    import evals as EV
    有效 = EV.有效分数([{"id": 分id, "value": 0.6, "supersedes_score_id": None},
                   {"id": (rv or {}).get("id"), "value": 1.0,
                    "supersedes_score_id": 分id}])
    ck("`有效分数()` 只认复核那条(**靠指针不靠时间戳**)",
       len(有效) == 1 and 有效[0]["value"] == 1.0, 有效)

    # ── 七、改片段:出新候选,旧版本原样留着 ─────────────────────────
    码, 体 = 打("POST", f"{P}/document-versions/{DV}/revisions", {})
    ck("不说「为什么改」→ 422(**复核的人只能靠猜**)", 码 == 422, 码)
    with 连接() as c:
        老版 = c.execute(text("select content_hash, object_key from document_versions "
                            "where project_id=:p and id=:i"),
                       {"p": 项目, "i": DV}).first()
    码, rev = 打("POST", f"{P}/document-versions/{DV}/revisions",
               {"为什么改": f"工期写成了 4 周,实际 6 周({尾})"})
    ck("改片段 → 201,而且是**新的一版**",
       码 == 201 and (rev or {}).get("id") != DV, (码, (rev or {}).get("id")))
    with 连接() as c:
        新老版 = c.execute(text("select content_hash, object_key from document_versions "
                             "where project_id=:p and id=:i"),
                        {"p": 项目, "i": DV}).first()
    # ⚠️ **先断「两边都查到了」再比。** 原来直接 `tuple(老版)`,
    # 查不到时抛 `TypeError: 'NoneType' object is not iterable` ——
    # 于是整份测试**带着 traceback 死在这里**,后面那条断言一个没跑,
    # 而日志上看到的是一个 Python 崩栈,不是「某条断言挂了」。
    ck("旧那一版在库里查得到(**查不到就别比了** —— 比的是两个 None 的话,"
       "`None == None` 会让这条**蒙绿**)",
       老版 is not None and 新老版 is not None,
       (老版 is not None, 新老版 is not None))
    if 老版 is not None and 新老版 is not None:
        ck("**旧那一版一个字没动**(已建好的索引引的就是它)",
           tuple(老版) == tuple(新老版), (tuple(老版), tuple(新老版)))
    ck("而且报出「旧那版还被几个索引引用着」(这就是不许原地改的理由)",
       isinstance((rev or {}).get("旧那一版还被几个索引引用着"), int),
       (rev or {}).get("旧那一版还被几个索引引用着"))

    清掉()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(夹具已清)")
    if 挂:
        for x in 挂: print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
