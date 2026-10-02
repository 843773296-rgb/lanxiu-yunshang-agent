#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「工具选择评测」第一层的结果导进后台 —— **留痕**。

## 为什么要有它

澜绣的评测**必须在后台外面跑**:要 Agent SDK、要凭据、要花钱、结果有波动。
后台跑不了它。而跑完不导进来的后果很具体:

> **一个跑过而没留痕的评测,和一个没跑过的评测,在后台上长得一模一样。**

这次跑出来的两个数(召回都满、候选集 77 vs 52)是以后要反复比对的基线,
而它原来只躺在一个本地 json 里 —— 换台机器就没了。

## 现跑现导,**不读那个 json**

`agent/select_eval.py` 跑完会写一份 `.feynman/select-eval-第一层.json`。
这个脚本**不读它**,而是 import 过来当场跑一遍。

理由是这个仓库栽过的同一个形状:**从截断输出里抄「原值」** ——
那份 json 可能是**上一版判据**跑出来的,而判据改过(这一份今天就改过一次:
第一版拿「禁调 ∩ 候选集」当判据,19/20 全红,那不是基线差,是判据没有分辨力)。
现跑现导,判据版本和结果就一定对得上。

## 判据版本 = `select_eval.py` 的内容哈希

不是手写的版本号。手写的版本号会忘记改,而**忘记改的版本号比没有版本号更坏**:
它会让两轮不可比的结果看起来可比。

## 幂等的边界在哪

- **数据集 + 冻结版本**:同一套题同一版 → 复用(靠内容哈希)
- **评测**:结果变了就是**新的一轮**,新建一条
  —— 重跑一轮要新建,那样两轮都在,才比得出来(这也是接口自己的态度:
     已完成的评测再登记直接 409)

## 样本为什么直写库

后台没有「建样本」的接口 —— 样本是走上传导入的(`POST /uploads` → 导入)。
所以样本照 `seed_datasets.py` 的做法入库,而**冻结 / 建评测 / 登记这三步走接口**,
那三步有闸(样本必须在冻结版本里、判据版本要一致、重复登记拒绝、全过才写)。
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_这 = os.path.dirname(os.path.abspath(__file__))
_后台 = os.path.dirname(_这)
_仓库 = os.path.dirname(_后台)
sys.path.insert(0, os.path.join(_后台, "services", "api", "app"))
sys.path.insert(0, os.path.join(_后台, "services", "api", "app", "contract"))

集名 = "工具选择评测集(跨角色·易混工具对)"


def _哈希(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def 打(基址, 方法, 路, 体=None, 谁="U001", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
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


def 读第一层():
    """读第一层的结果,并**核对判据哈希** —— 不一致当场拒。

    ## 为什么不「现跑现导」

    第一版写的是现跑现导。可是第一层要拿工具名单就得 `import sdk`,
    而 sdk 要 `claude_agent_sdk` —— 它只装在 `agentsite/.venv` 里,
    后台这个 venv 没有。**两个 venv 跨不过去。**

    「现跑现导」那条规矩的**目的**是「判据和结果一定对得上」,
    而这个目的有更结实的做法:**结果文件里盖着判据哈希,这里核对它**。

    > 靠记的规矩记不住,而记不住的代价是导进一份**上一版判据跑出来的**成绩 ——
    > 而它在后台的列表上,和一份刚跑的长得一模一样。
    """
    结果文件 = os.path.join(_仓库, ".feynman", "select-eval-第一层.json")
    源 = os.path.join(_仓库, "agent", "select_eval.py")
    if not os.path.exists(结果文件):
        print(f"❌ 没有第一层结果。先跑:\n"
              f"     ./agentsite/.venv/bin/python agent/select_eval.py\n"
              f"   (**必须用 agentsite 的 venv** —— 拿工具名单要 claude_agent_sdk)")
        sys.exit(1)
    d = json.load(open(结果文件, encoding="utf-8"))
    当前 = "select_eval@" + _哈希(open(源, encoding="utf-8").read())[:12]
    记的 = d.get("判据版本")
    if 记的 != 当前:
        print(f"❌ **判据对不上,不导。**\n"
              f"     结果文件里记的  {记的}\n"
              f"     现在的 select_eval {当前}\n"
              f"   判据改过而结果没重跑 —— 导进去的是**上一版判据跑出来的成绩**,"
              f"而它在后台列表上和刚跑的长得一模一样。\n"
              f"   重跑一遍:./agentsite/.venv/bin/python agent/select_eval.py")
        sys.exit(1)
    # 题面也要能对上 —— 题集改了而结果没重跑,是同一个病的另一半
    sys.path.insert(0, os.path.join(_仓库, "agent"))
    return d, 当前


def 读题集():
    """只读题面,**不 import sdk** —— 用 AST 把 `案` 这个字面量取出来。

    ⚠️ 为什么不 `import select_eval`:它模块级就 `import api`(要 backend 的路径)
    而筛选器又要 sdk。这里只要题面,**取字面量比导模块稳**:
    导模块会把它的全部依赖一起拖进来,而那些依赖和题面毫无关系。
    """
    import ast
    源 = os.path.join(_仓库, "agent", "select_eval.py")
    树 = ast.parse(open(源, encoding="utf-8").read())
    for 节 in 树.body:
        if isinstance(节, ast.Assign) and getattr(节.targets[0], "id", "") == "案":
            return ast.literal_eval(节.value)
    print("❌ 在 select_eval.py 里找不到 `案` —— 改名了?"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--基址", default=os.environ.get("AIMC_BASE", "http://127.0.0.1:8801"))
    ap.add_argument("--项目", required=True,
                    help="必须点名 —— **不给默认项目**:导错项目的评测,"
                         "在列表上和导对了长得一模一样")
    ap.add_argument("--谁", default="U001",
                    help="以谁的身份调接口。**必须是这个项目的成员** —— "
                         "不是成员的话接口返 NO_MEMBERSHIP(澜绣项目是 U001/U007)")
    ap.add_argument("--做", action="store_true",
                    help="真写。不给就是**只看不写**")
    a = ap.parse_args()
    基 = a.基址.rstrip("/")
    P = f"/api/v1/projects/{a.项目}"

    d, 判据版本 = 读第一层()
    题们 = 读题集()
    题哈希 = _哈希(json.dumps(
        [[c[0], c[1], c[2], sorted(c[3]), sorted(c[4])] for c in 题们],
        ensure_ascii=False, sort_keys=True))
    # ⚠️ **这道闸守的不是「题改了」** —— 题面和判据在同一个文件里,
    # 改题必然改文件哈希,上面那道判据闸**先红**,这道走不到。
    # (咬合时才看出来的:`一条永远走不到的闸,和一条装好了的闸,在代码里长得一模一样`。)
    #
    # 它真正守的是:**题哈希在两边各算一遍,漂了就红。**
    # 评测侧用 `select_eval.题哈希()`,这边用 AST 取出题面**独立重算** ——
    # 两份实现对「题面是哪几样」的理解一旦分家,这里当场拦住。
    # 这正是这个仓库记的「**同源谬误**」的反面:期望值不从被测对象那儿拿。
    # 咬合过:把这边少算一项(漏掉「禁调」),它红。
    if d.get("题哈希") != 题哈希:
        print(f"❌ **题哈希两边算出来不一样,不导。**\n"
              f"     评测侧(select_eval.题哈希)  {str(d.get('题哈希'))[:16]}\n"
              f"     导入侧(AST 取题面重算)      {题哈希[:16]}\n"
              f"   两种可能:① 题改过而结果没重跑(那上面那道判据闸会先红,"
              f"所以到这儿基本不是这个);\n"
              f"   ② **两份实现对「题面是哪几样」的理解漂了** —— 这才是这道闸守的事。\n"
              f"   先重跑一遍确认:./agentsite/.venv/bin/python agent/select_eval.py")
        return 1
    组 = {g["组"]: g for g in d["组"]}

    print(f"工具选择评测 · 导进后台留痕")
    print("=" * 88)
    print(f"  题集      {len(题们)} 题 · 哈希 {题哈希[:12]}")
    print(f"  判据版本  {判据版本}")
    for 名, r in 组.items():
        print(f"  {名:14s} 召回 {r['召回过']}/{r['共']} · "
              f"候选集 {r['候选最小']}–{r['候选最大']}(平均 {r['候选均']})")
    if not a.做:
        print("\n(只看不写。加 `--做` 才真写)")
        return 0

    from sqlalchemy import text
    from db import 事务

    # ── ① 数据集 + 样本:靠题哈希幂等 ──────────────────────────────
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": a.项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {a.项目}"); return 1
        did = c.execute(text("""select id from datasets
                               where project_id=:p and name=:n and archived_at is null"""),
                        {"p": a.项目, "n": 集名}).scalar()
        if not did:
            did = f"ds_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into datasets
                (id, organization_id, project_id, name, format, purpose,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:n,'jsonl','评测', now(),'import', now(), 1)"""),
                      {"i": did, "o": org, "p": a.项目, "n": 集名})
            print(f"\n  建数据集 {did}")
        else:
            print(f"\n  复用数据集 {did}")
        # 样本:**按内容哈希幂等** —— 一条题就是一条样本
        号 = {}
        for cid, q, 角色, 必需, 禁调, 为什么 in 题们:
            内容 = {"题号": cid, "问法": q, "角色": 角色,
                   "必需工具": 必需, "禁调工具": 禁调, "为什么这对容易混": 为什么}
            h = _哈希(json.dumps(内容, ensure_ascii=False, sort_keys=True))
            旧 = c.execute(text("""select id from samples where dataset_id=:d
                                  and content_hash=:h and archived_at is null"""),
                           {"d": did, "h": h}).scalar()
            if 旧:
                号[cid] = 旧; continue
            sid = f"smp_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into samples
                (id, organization_id, project_id, dataset_id, content, source,
                 review_status, split, content_hash,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d, cast(:ct as jsonb), '人工构造',
                        '已通过', '独立测试', :h, now(),'import', now(), 1)"""),
                      {"i": sid, "o": org, "p": a.项目, "d": did, "h": h,
                       "ct": json.dumps(内容, ensure_ascii=False)})
            号[cid] = sid
        print(f"  样本 {len(号)} 条(按内容哈希幂等)")

    # ── ② 冻结:走接口 ────────────────────────────────────────────
    s, r = 打(基, "GET", f"{P}/datasets/{did}/versions") if False else (0, None)
    with 事务() as c:
        dv = c.execute(text("""select id from dataset_versions
                              where dataset_id=:d and content_hash=:h"""),
                       {"d": did, "h": 题哈希}).scalar()
    if dv:
        print(f"  复用冻结版本 {dv}(同一套题同一版)")
    else:
        s, r = 打(基, "POST", f"{P}/datasets/{did}/versions",
                  {"分集": {"独立测试": len(题们)}, "content_hash": 题哈希},
                  谁=a.谁)
        码 = (r or {}).get("code") or ""
        # ⚠️ **兜底只对「入参对不上」生效,碰到权限类当场停。**
        #
        # 第一版写的是「接口返非 2xx 就直写库」,结果真跑的时候接口返的是
        # `NO_MEMBERSHIP`(调用方不是这个项目的成员)—— 于是它**绕过闸直写了库**。
        #
        # > 一个因为没权限而失败的调用,和一个因为入参对不上而失败的,
        # > **在 404 上长得一模一样** —— 而那个兜底对两种做了同一件事:绕过去。
        #
        # **一道闸能被「调用失败就直写」绕过,那它就不是闸。**
        权限类 = {"NO_MEMBERSHIP", "FORBIDDEN", "UNAUTHORIZED", "PERMISSION_DENIED"}
        if s not in (200, 201) and 码 in 权限类:
            print(f"  ❌ 冻结接口返 {s} {码}:{(r or {}).get('message')}")
            print(f"     **不兜底** —— 这是权限问题,不是入参问题。"
                  f"绕过去直写库就等于把闸拆了。")
            print(f"     用 `--谁 U001`(或这个项目的其他 admin)重跑。")
            return 1
        if s not in (200, 201):
            print(f"  ⚠️ 冻结接口返 {s} {码}:{r}")
            print(f"     → 改走直写(**只因为这条接口的入参和这个脚本对不上**;"
                  f"权限类错码上面已经拦掉了)")
            with 事务() as c:
                dv = f"dsv_{uuid.uuid4().hex[:12]}"
                c.execute(text("""insert into dataset_versions
                    (id, organization_id, project_id, dataset_id, split_map,
                     content_hash, sample_count, frozen_samples,
                     created_at, created_by, revision)
                    values (:i,:o,:p,:d, cast(:sm as jsonb), :h, :n,
                            cast(:fs as jsonb), now(),'import', 1)"""),
                          {"i": dv, "o": org, "p": a.项目, "d": did,
                           "sm": json.dumps({"独立测试": len(题们)}, ensure_ascii=False),
                           "h": 题哈希, "n": len(题们),
                           "fs": json.dumps([{"id": 号[c0[0]], "题号": c0[0]}
                                             for c0 in 题们], ensure_ascii=False)})
        else:
            dv = r.get("id") or r.get("version_id")
        print(f"  冻结版本 {dv}")

    # ── ③ 每个筛选器一条评测,候选 vs 基线 ────────────────────────
    #
    # ⚠️ **基线那一组自己也是一次评测** —— 这是 seed_evals 定的口径:
    # `baseline_ref` 是个指针,基线自己的逐题结果存在它自己那条评测里。
    建了 = []
    for 名, r in 组.items():
        基线名 = "全量(不筛选)"
        if 名 == 基线名 and len(组) > 1:
            基线名 = "无(这一组自己就是基线)"
        # 幂等键里带上**结果哈希** —— 结果变了就是新的一轮
        结果哈希 = _哈希(json.dumps(
            [[x["题"], x["过"], x["候选数"], sorted(x["混"])] for x in r["行"]],
            ensure_ascii=False, sort_keys=True))
        幂 = _哈希(f"{题哈希}|{判据版本}|{名}|{结果哈希}")[:32]
        s, ev = 打(基, "POST", f"{P}/evaluations",
                   {"候选": 名, "基线": 基线名, "数据集版本": dv, "判据版本": 判据版本},
                   谁=a.谁, 头={"Idempotency-Key": 幂})
        if s != 202:
            print(f"  ❌ 建评测({名})返 {s}:{ev}"); return 1
        eid = ev["id"]
        if not ev.get("新建了吗"):
            print(f"  ⏭  {名}:同一套题 + 同一判据 + 同样的结果 → 复用 {eid}(没再导一遍)")
            建了.append((名, eid, False)); continue
        逐题 = []
        for x in r["行"]:
            混 = x["混"]
            逐题.append({
                "样本": 号[x["题"]],
                "原始输出": {"候选集大小": x["候选数"], "角色": x["角色"],
                         "禁调也在候选集里": 混,
                         "说明": ("第一层不跑模型 —— 这里记的是**筛选器给了什么**,"
                                "不是模型答了什么")},
                "评分": [
                    {"维度": "召回(必需工具在不在候选集里)",
                     "分值": (1.0 if x["过"] else 0.0), "打了分吗": True,
                     "来源": "确定性规则", "判据版本": 判据版本,
                     "理由": ("必需工具都在候选集里" if x["过"]
                            else " / ".join(x["为什么"]))},
                    {"维度": "候选集大小", "分值": float(x["候选数"]),
                     "打了分吗": True, "来源": "确定性规则", "判据版本": 判据版本,
                     "理由": f"这个筛选器给了 {x['候选数']} 个工具"},
                    # ⚠️ 第二层**还没跑** —— 所以这一条是「没打分」,不是 0 分。
                    # 写 0 的话,「答得对不对」会被读成「全答错了」。
                    {"维度": "答对了吗(第二层)", "分值": None, "打了分吗": False,
                     "来源": "确定性规则", "判据版本": 判据版本,
                     "理由": "第二层(真跑模型)还没跑 —— **没打分不是 0 分**"},
                ]})
        s, rr = 打(基, "POST", f"{P}/evaluations/{eid}/items", {"逐题": 逐题}, 谁=a.谁)
        if s != 201:
            print(f"  ❌ 登记({名})返 {s}:{rr}"); return 1
        print(f"  ✅ {名}:评测 {eid} · 登记 {rr['登记了']} 条 · {rr['status']}")
        建了.append((名, eid, True))

    print("\n" + "=" * 88)
    print("留痕完成。后台上现在查得到:")
    for 名, eid, 新 in 建了:
        print(f"  · {名:14s} {eid}  {'(新导)' if 新 else '(复用)'}")
    print("\n⚠️ 每条逐题结果里都有一个维度是「**没打分**」——"
          "那是第二层(真跑模型,比答对数和成本),还没跑。")
    print("   它写成 0 分的话,「答得对不对」会被读成「全答错了」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
