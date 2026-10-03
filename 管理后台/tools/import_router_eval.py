#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把独立路由器的实验结果登记进后台 —— **规格要求的那个「实验」**。

## 为什么这一步是必须的,不是留痕的锦上添花

规格 §4.2 后面那句话定了开路由器的**条件**:

> 筛选语句可由执行任务的 Agent 直接产生,不强制单独调用「路由大模型」。
> **只有实验证明额外分类有价值时,才启用独立路由节点**;
> 它的成本和延迟计入整条任务。

所以「开路由器」不是把一个 bool 翻成 true。

> **一个没有实验撑着的「已启用」,和一个有实验撑着的,在策略页上长得一模一样。**

这个脚本把 `agent/router_probe.py` 跑出来的结果登记成一次评测
(走 `POST /evaluations/{id}/items`),于是策略那边的闸可以要求
「开路由器必须指向一次已完成的评测」—— **规格的条件变成了结构**。

## 候选和基线是什么

- **候选** = 独立路由器(haiku-4-5,带提示词缓存)
- **基线** = 关键词检索 @k=5(`agent/select_probe.py` 量的那一档)

没有基线的分数不能当结论 —— 而「路由器 87%」单独放着回答不了
「它比现在这套好吗」。基线那一档是 54%。

## 三个维度,而且**延迟和成本也进分数**

规格原话:「**它的成本和延迟计入整条任务**」。所以不只记召回:

| 维度 | 为什么要记 |
|---|---|
| 召回 | 它是不是真的找得到工具 |
| **单条延迟(ms)** | 规格的筛选超时预算是 3000ms,而实测最慢 4438ms(缓存关)—— **这个数决定超时配多少** |
| **单条成本(USD)** | 带缓存 $0.00109 ≈ V2 跑一整条,是 V3 的 3.8% |

⚠️ **「省下来多少」没量**,所以成本那一栏记的是**毛支出**,不是净成本。
真算净成本要量「开路由器之后主调用的 token 降多少」,那要改澜绣的运行代码。
这一栏在评测里标成「没打分」,**不写 0** —— 写 0 会被读成「一分钱没省」。
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
根 = os.path.dirname(_这)
仓库 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))

集名 = "工具路由留出集(tool_eval 22 + tool_routing 11)"
# 真值要 `pattern_queue`,而它不在 `all` 的 77 个池子里(那 4 个版师工具是安全边界)——
# 所以这两题**在构造上就不可能过**,不该算路由器的错。
#
# ⚠️ 题号是结果文件里的 `题` 字段(`R8` / `R9`),**不是打印时拼出来的 `BR8`**
# (那是「集 + 题号」的显示名)。第一版写了 `BR8`,于是这个排除集
# **一个都没排掉**,而「可答的」那一栏照样印出了一个数(27/33 = 81%)。
# > 一个排不掉任何东西的排除集,和一个正确排掉了的,在代码里长得一模一样。
# 所以下面还有一道:**一个都没命中就当场报**。
构造不可能 = {"R8", "R9"}


def _哈希(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def 打(基, 方法, 路, 体=None, 谁="U001", 头=None):
    req = urllib.request.Request(
        基 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
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


def 读探针结果():
    """读 `.feynman/router-probe.json`,并**核对它是哪一版探针跑的**。

    ⚠️ 和 `import_select_eval.py` 同一条规矩:**结果文件要能和产生它的代码对上**。
    探针改过而结果没重跑,登记进去的就是上一版探针的成绩 ——
    **而它在后台列表上和刚跑的长得一模一样。**
    """
    p = os.path.join(仓库, ".feynman", "router-probe.json")
    源 = os.path.join(仓库, "agent", "router_probe.py")
    if not os.path.exists(p):
        print(f"❌ 没有探针结果。先跑:\n"
              f"     LANXIU_PROVIDER=claude ./agentsite/.venv/bin/python "
              f"agent/router_probe.py --模型 claude-haiku-4-5")
        sys.exit(1)
    d = json.load(open(p, encoding="utf-8"))
    if "配置" not in d or "探针版本" not in d:
        print(f"❌ 结果文件没盖探针版本 —— 跑一次补上(不会重新调模型):\n"
              f"     ./agentsite/.venv/bin/python agent/router_probe.py "
              f"--模型 claude-haiku-4-5 --重算")
        sys.exit(1)
    当前 = "router_probe@" + _哈希(open(源, encoding="utf-8").read())[:12]
    if d["探针版本"] != 当前:
        print(f"❌ **探针对不上,不登记。**\n"
              f"     结果文件里记的  {d['探针版本']}\n"
              f"     现在的 router_probe {当前}\n"
              f"   探针改过而结果没重跑 —— 登记进去的是**上一版探针的成绩**,"
              f"而它在后台列表上和刚跑的长得一模一样。\n"
              f"   只改了注释/新加了函数的话,`--重算` 就够(不重新调模型);"
              f"改了提问方式或目录形状的话**必须重跑**。")
        sys.exit(1)
    行们 = d["配置"]
    if "关" not in 行们 or "开" not in 行们:
        print(f"❌ 结果形状不对(要有「关」和「开」两个缓存配置)"); sys.exit(1)
    return 行们


def 读钱(x):
    """只读结果文件里**已经算好的**成本。

    ⚠️ **这边不许自己算。** `sdk.cost_of()` 在 agentsite 那个 venv 里
    (要 claude_agent_sdk),而且它记着「2026-09-22 修过两处,
    **修之前少算约三成**」—— 官方的 `input_tokens` 已经不含缓存命中和写入。
    在这儿抄一份算法就会把那三成错误抄回来。
    产生数据的那一侧算好(`router_probe.py --重算`),这边只读。
    """
    return x.get("成本USD")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--基址", default=os.environ.get("AIMC_BASE", "http://127.0.0.1:8801"))
    ap.add_argument("--项目", required=True)
    ap.add_argument("--谁", default="U001")
    ap.add_argument("--做", action="store_true")
    a = ap.parse_args()
    基 = a.基址.rstrip("/")
    P = f"/api/v1/projects/{a.项目}"

    行们 = 读探针结果()
    # 登记的是**带缓存**那一档 —— 它是真要上的那个配置
    # (不带缓存最慢 4438ms,超过规格的 3000ms 超时预算)
    行 = [x for x in 行们["开"] if not x.get("挂了")]
    关行 = {x["题"]: x for x in 行们["关"] if not x.get("挂了")}
    命中 = {x["题"] for x in 行} & 构造不可能
    if not 命中:
        print(f"❌ **排除集一个都没命中,不登记。**\n"
              f"     我要排掉的:{sorted(构造不可能)}\n"
              f"     结果里的题号样例:{sorted(x['题'] for x in 行)[:6]}\n"
              f"   题号的写法变了?一个排不掉任何东西的排除集,"
              f"**和一个正确排掉了的,在「可答的」那个数上看不出来**。")
        sys.exit(1)
    if 命中 != 构造不可能:
        print(f"⚠️ 排除集里这几个在结果里找不到:{sorted(构造不可能 - 命中)}"
              f" —— 题改了?先核一遍再登记。")
    可答 = [x for x in 行 if x["题"] not in 构造不可能]
    过 = sum(1 for x in 可答 if x["过"])
    延 = sorted(x["ms"] for x in 行)
    钱 = [读钱(x) for x in 行]
    钱 = [c for c in 钱 if c is not None]
    关延 = sorted(x["ms"] for x in 关行.values())

    print("独立路由器实验 → 登记进后台")
    print("=" * 84)
    print(f"  候选:独立路由器 haiku-4-5 + 提示词缓存")
    print(f"  基线:关键词检索 @k=5(select_probe 量的 18/33 = 54%)")
    print(f"  召回(可答的):{过}/{len(可答)} = {100*过//len(可答)}%"
          f"   (全部 {sum(1 for x in 行 if x['过'])}/{len(行)})")
    print(f"  延迟:中位 {延[len(延)//2]}ms · 最慢 {延[-1]}ms"
          f"   (不带缓存最慢 {关延[-1]}ms —— **超过规格 3000ms 的超时预算**)")
    print(f"  成本:单条 ${sum(钱)/len(钱):.5f}")
    print(f"  ⏸ 构造上不可能过的 {len(构造不可能)} 题已排掉:{sorted(构造不可能)}"
          f"(真值要 pattern_queue,而它不在 all 的 77 个池子里)")
    if not a.做:
        print("\n(只看不写。加 `--做` 才真写)")
        return 0

    from sqlalchemy import text
    from db import 事务

    题哈希 = _哈希(json.dumps(sorted(x["题"] for x in 行), ensure_ascii=False))
    判据 = "router_probe@" + _哈希(
        open(os.path.join(仓库, "agent", "router_probe.py"), encoding="utf-8").read())[:12]

    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": a.项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {a.项目}"); return 1
        did = c.execute(text("""select id from datasets where project_id=:p
                               and name=:n and archived_at is null"""),
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
        号 = {}
        for x in 行:
            内容 = {"题号": x["题"], "集": x.get("集"),
                   "构造上可答吗": x["题"] not in 构造不可能}
            h = _哈希(json.dumps(内容, ensure_ascii=False, sort_keys=True))
            旧 = c.execute(text("""select id from samples where dataset_id=:d
                                  and content_hash=:h and archived_at is null"""),
                           {"d": did, "h": h}).scalar()
            if 旧:
                号[x["题"]] = 旧; continue
            sid = f"smp_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into samples
                (id, organization_id, project_id, dataset_id, content, source,
                 review_status, split, content_hash,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d, cast(:ct as jsonb), '留出集',
                        '已通过','独立测试', :h, now(),'import', now(), 1)"""),
                      {"i": sid, "o": org, "p": a.项目, "d": did, "h": h,
                       "ct": json.dumps(内容, ensure_ascii=False)})
            号[x["题"]] = sid
        dv = c.execute(text("""select id from dataset_versions
                              where dataset_id=:d and content_hash=:h"""),
                       {"d": did, "h": 题哈希}).scalar()
        if not dv:
            dv = f"dsv_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into dataset_versions
                (id, organization_id, project_id, dataset_id, split_map,
                 content_hash, sample_count, frozen_samples,
                 created_at, created_by, revision)
                values (:i,:o,:p,:d, cast(:sm as jsonb), :h, :n,
                        cast(:fs as jsonb), now(),'import', 1)"""),
                      {"i": dv, "o": org, "p": a.项目, "d": did,
                       "sm": json.dumps({"独立测试": len(行)}, ensure_ascii=False),
                       "h": 题哈希, "n": len(行),
                       "fs": json.dumps([{"id": 号[x["题"]], "题号": x["题"]}
                                         for x in 行], ensure_ascii=False)})
        print(f"  冻结版本 {dv}({len(行)} 题)")

    结果哈希 = _哈希(json.dumps([[x["题"], x["过"], x["ms"]] for x in 行],
                            ensure_ascii=False))
    幂 = _哈希(f"{题哈希}|{判据}|路由器|{结果哈希}")[:32]
    s, ev = 打(基, "POST", f"{P}/evaluations",
               {"候选": "独立路由器 haiku-4-5 + 提示词缓存",
                "基线": "关键词检索 @k=5(18/33 = 54%)",
                "数据集版本": dv, "判据版本": 判据},
               谁=a.谁, 头={"Idempotency-Key": 幂})
    if s != 202:
        print(f"  ❌ 建评测返 {s}:{ev}"); return 1
    eid = ev["id"]
    if not ev.get("新建了吗"):
        # ⚠️ **「幂等键命中」不等于「这次登记过了」。**
        # 上一轮栽过:建评测成功了、登记逐题失败了(那批里有两条分值和
        # 「打了分吗」自相矛盾,被后台的闸整批拒了)——
        # 于是库里留下一条**一条逐题都没有的空评测**,而下次重跑
        # 幂等键命中、直接返回「复用」,**逐题永远不会被登记**。
        #
        # > 一条建好了但一条逐题都没登记的评测,和一条完整登记过的,
        # > **在幂等键上长得一模一样**。
        #
        # (和「空集合上所有性质都成立」同一个形状。)
        with 事务() as c:
            有 = c.execute(text("""select count(*) from evaluation_items
                                  where evaluation_id=:e"""), {"e": eid}).scalar()
        if 有 >= len(行):
            print(f"  ⏭  同一套题 + 同一判据 + 同样的结果 → 复用 {eid}"
                  f"(已有 {有} 条逐题)")
            print(f"\n✅ 这次实验的评测:{eid}")
            return 0
        print(f"  ⚠️ 复用到 {eid},但它只有 {有} 条逐题(该有 {len(行)} 条)"
              f" —— **上一次建好了而没登完**,接着登。")
    逐题 = []
    for x in 行:
        单钱 = 读钱(x)
        逐题.append({
            "样本": 号[x["题"]],
            "原始输出": {"路由器给的工具": x["给的"], "延迟ms": x["ms"],
                     "usage": x["usage"],
                     "不带缓存时的延迟ms": (关行.get(x["题"]) or {}).get("ms"),
                     "构造上可答吗": x["题"] not in 构造不可能},
            "评分": [
                # ⚠️ **没打分就不许给分值。** 第一版这里写的是
                # `1.0 if 过 else 0.0`,而对那两道「构造上不可能过」的题
                # 又标了「没打分」—— 两件事只能有一个,
                # **而后台那道闸当场抓住了**(2026-10-03,我昨天亲手装的那道)。
                # 代价很具体:那两题按 0 分平均进去,召回会从 87% 掉到 82%,
                # **而那 5 个点是假的**。
                {"维度": "召回(至少命中一个 need)",
                 "分值": (None if x["题"] in 构造不可能
                        else (1.0 if x["过"] else 0.0)),
                 "打了分吗": (x["题"] not in 构造不可能),
                 "来源": "确定性规则", "判据版本": 判据,
                 "理由": ("路由器给的工具里有需要的那个" if x["过"]
                        else ("**构造上不可能过** —— 真值要 pattern_queue,"
                              "而它不在我给路由器的目录里(安全边界)"
                              if x["题"] in 构造不可能
                              else f"给的是 {x['给的']},没命中"))},
                {"维度": "单条延迟ms", "分值": float(x["ms"]), "打了分吗": True,
                 "来源": "确定性规则", "判据版本": 判据,
                 "理由": "规格 §14.3 的筛选超时预算是 3000ms;"
                       f"不带缓存同一题是 {(关行.get(x['题']) or {}).get('ms')}ms"},
                {"维度": "单条成本USD(毛支出)",
                 "分值": (float(单钱) if 单钱 is not None else None),
                 "打了分吗": (单钱 is not None),
                 "来源": "确定性规则", "判据版本": 判据,
                 "理由": "按 sdk.cost_of() 的价目表算(haiku-4-5:入 1 / 缓存 0.1 / 出 5)"},
                # ⚠️ **净成本没打分,不是 0 分。**
                # 写 0 会被读成「一分钱没省」,而真相是「还没量」。
                {"维度": "净成本USD(扣掉主调用省下的)", "分值": None,
                 "打了分吗": False, "来源": "确定性规则", "判据版本": 判据,
                 "理由": "**没量** —— 要量「开路由器之后主调用的 token 降多少」,"
                       "那要改澜绣的运行代码。写 0 会被读成「一分钱没省」"},
            ]})
    s, rr = 打(基, "POST", f"{P}/evaluations/{eid}/items", {"逐题": 逐题}, 谁=a.谁)
    if s != 201:
        print(f"  ❌ 登记返 {s}:{rr}"); return 1
    print(f"  ✅ 评测 {eid} · 登记 {rr['登记了']} 条 · {rr['status']}")
    print(f"\n✅ 这次实验的评测:{eid}")
    print(f"   规格那句「**只有实验证明额外分类有价值时,才启用独立路由节点**」"
          f"现在有东西指了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
