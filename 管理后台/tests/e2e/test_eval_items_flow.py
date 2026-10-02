#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登记外部评测结果 · **八道闸逐道撞红**。

## 这一份守的那句话

在这条口之前,评测中心能「建评测」(置成「排队中」)、能「人工复核」、能列表、能对比,
**但没有任何一条口能把跑完的结果写回来** —— `evaluation_items` 全库只有 seed 写过。
这条链在后台里是**断的**:建了一个排队中的评测,然后永远排队。

而澜绣的评测**必须在后台外面跑**(要 Agent SDK、凭据、花钱、结果有波动),后台跑不了它。

> **一个跑过而没留痕的评测,和一个没跑过的评测,在后台上长得一模一样。**

## 为什么每一道都要**单独**撞一次

⚠️ 这个项目栽过:**一次注入两个破坏,只验到一个** ——
第一道闸先拦住了,后面那道根本没走到,而输出上看起来两道都红了。
所以下面每一条反例**只破坏一件事**,其余字段全是合法的。

⚠️ 还栽过:**断言插在不渲染那一段的测试里**,九条断言一起红而没一条指向真因。
所以每条反例都**单独断它自己的错码或 field_errors 的键**,不只断「红了」。

⚠️ 前提 `make dev`。这一份自己建数据集、冻结、建评测,跑完**自己清**
(按名字清,**不按 id 前缀** —— id 是服务端生成的,按前缀清什么都删不掉,栽过)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
尾 = uuid.uuid4().hex[:6]
集名 = f"登记闸自测-{尾}"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U002", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
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
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务                     # noqa: E402


def 造一套题和评测(判据="判据-v1", 题数=3):
    """自己建数据集 + 冻结 + 建评测。

    ⚠️ **不靠演示数据** —— 一个靠样例数据成立的判据,每加一条就要回答
    「CI 的从零库里它从哪来」。这个项目同一天在这上面栽过三次,所以这里自己造。
    """
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        did = f"ds_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into datasets
            (id, organization_id, project_id, name, format, purpose,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n, 'jsonl', '评测', now(),'test', now(), 1)"""),
                  {"i": did, "o": org, "p": 项目, "n": 集名})
        样本 = []
        for k in range(题数):
            sid = f"smp_{uuid.uuid4().hex[:12]}"
            # ⚠️ 列名是**查库查出来的**,不是猜的 —— 这一份第一版写了
            # `input` / `expected`,库里其实是一列 `content`(JSONB)。
            # 「凭字段名猜」在这个仓库是同族第四次了(前三次猜的是类型)。
            c.execute(text("""insert into samples
                (id, organization_id, project_id, dataset_id, content, source,
                 review_status, split, content_hash,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d, cast(:ct as jsonb), '自测',
                        '已通过', '独立测试', :h, now(),'test', now(), 1)"""),
                      {"i": sid, "o": org, "p": 项目, "d": did, "h": uuid.uuid4().hex,
                       "ct": json.dumps({"问": f"第 {k+1} 题", "答": "真值"},
                                        ensure_ascii=False)})
            样本.append(sid)
        dv = f"dsv_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into dataset_versions
            (id, organization_id, project_id, dataset_id, split_map, content_hash,
             sample_count, frozen_samples, created_at, created_by, revision)
            values (:i,:o,:p,:d, cast(:sm as jsonb), :h, :n, cast(:fs as jsonb),
                    now(),'test', 1)"""),
                  {"i": dv, "o": org, "p": 项目, "d": did,
                   "sm": json.dumps({"独立测试": 题数}, ensure_ascii=False),
                   "h": uuid.uuid4().hex, "n": 题数,
                   "fs": json.dumps([{"id": s} for s in 样本], ensure_ascii=False)})
    s, r = 打("POST", f"{P}/evaluations",
              {"候选": "按角色", "基线": "全量", "数据集版本": dv, "判据版本": 判据},
              头={"Idempotency-Key": uuid.uuid4().hex})
    assert s == 202, (s, r)
    return r["id"], dv, 样本


def 一条(样本, 判据="判据-v1", **盖):
    """一条合法的逐题结果。`盖` 只改要破坏的那一件事。"""
    评 = dict(维度="召回", 分值=1.0, 打了分吗=True, 来源="确定性规则",
             判据版本=判据, 理由="必需工具都在候选集里")
    评.update(盖.pop("评分改", {}))
    条 = dict(样本=样本, 原始输出={"候选集大小": 52}, 评分=[评])
    条.update(盖)
    return 条


def 清():
    with 事务() as c:
        c.execute(text("""delete from scores where evaluation_item_id in (
                            select i.id from evaluation_items i join evaluations e
                              on e.id=i.evaluation_id
                            where e.dataset_version_id in (
                              select v.id from dataset_versions v join datasets d
                                on d.id=v.dataset_id where d.name=:n))"""), {"n": 集名})
        c.execute(text("""delete from evaluation_items where evaluation_id in (
                            select e.id from evaluations e where e.dataset_version_id in (
                              select v.id from dataset_versions v join datasets d
                                on d.id=v.dataset_id where d.name=:n))"""), {"n": 集名})
        c.execute(text("""delete from evaluations where dataset_version_id in (
                            select v.id from dataset_versions v join datasets d
                              on d.id=v.dataset_id where d.name=:n)"""), {"n": 集名})
        c.execute(text("""delete from dataset_versions where dataset_id in (
                            select id from datasets where name=:n)"""), {"n": 集名})
        c.execute(text("""delete from samples where dataset_id in (
                            select id from datasets where name=:n)"""), {"n": 集名})
        c.execute(text("delete from datasets where name=:n"), {"n": 集名})


def main():
    print(f"登记外部评测结果 · 八道闸 · 基址 {基址} · 项目 {项目}")
    print("=" * 92)
    try:
        eid, dv, 样本 = 造一套题和评测()
        print(f"  (自己造的:评测 {eid} · 冻结 {len(样本)} 条样本)")

        # ── 先把每一道闸单独撞红 ──────────────────────────────────
        print("\n【闸】每条反例只破坏一件事,其余字段全合法")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items", {"逐题": []})
        ck("③ 空列表被拒(空集合上所有性质都成立,「一条都没登记」会被读成「登记好了」)",
           s == 422 and (r or {}).get("code") == "VALIDATION", f"{s} {(r or {}).get('code')}")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条("smp_根本不存在的样本号")]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("③ 不在冻结样本里的被拒(登记它等于偷偷加题,平均分的分母会变)",
           s == 422 and any("逐题[0]" == k for k in 键), f"{s} {键}")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[0], 评分改={"判据版本": "判据-v2"})]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("④ 判据版本不一致被拒(混进同一次评测,那次的分数成了两套判据的混合物)",
           s == 422 and any(".判据版本" in k for k in 键), f"{s} {键}")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[0], 评分改={"来源": "规则"})]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("⑤ 来源走白名单(「规则」不是「确定性规则」—— 拼错的来源会自成一档)",
           s == 422 and any(".来源" in k for k in 键), f"{s} {键}")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[0], 评分改={"打了分吗": None})]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("⑥ 不说「打了分吗」被拒(用 0 表示没测过,会让人以为测过了)",
           s == 422 and any(".打了分吗" in k for k in 键), f"{s} {键}")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[0], 评分改={"打了分吗": False, "分值": 0.0})]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("⑥ 说没打分却给了 0 分被拒(**判不了就别写分**)",
           s == 422 and any(".分值" in k for k in 键), f"{s} {键}")

        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[0]), 一条(样本[0])]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("⑦ 同一批里重复同一条样本被拒(不能一次登记两份原始结果)",
           s == 422 and any("逐题[1]" == k for k in 键), f"{s} {键}")

        # ⚠️ **这一条必须断错误码,不能只断 404。**
        # 第一版只断 `s == 404`,结果这条口整个还没加载时它**也过了** ——
        # 而那时每一条断言都在打一个不存在的路由。
        # > 一个因为路由不存在而返回的 404,和一个正确判断「评测不存在」的 404,
        # > **在状态码上长得一模一样**。
        s, r = 打("POST", f"{P}/evaluations/不存在的评测/items",
                  {"逐题": [一条(样本[0])]})
        ck("① 评测不存在 → 404,**而且是 NOT_FOUND 不是路由没上**",
           s == 404 and (r or {}).get("code") == "NOT_FOUND",
           f"{s} {(r or {}).get('code') or r}")

        # ⑧ 全过才写:上面那批**两条**里只有第二条坏,验第一条也没被写进去
        with 事务() as c:
            剩 = c.execute(text("select count(*) from evaluation_items "
                               "where evaluation_id=:e"), {"e": eid}).scalar()
        ck("⑧ 全过才写:上面每一批都有坏条,库里一条都不该有", 剩 == 0, f"实际 {剩} 条")

        # ── 再走一遍正路 ──────────────────────────────────────────
        print("\n【正路】对照:这条闸不是一律拒绝")
        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[0]), 一条(样本[1])]})
        ck("合法的两条登记成功(201)", s == 201 and (r or {}).get("登记了") == 2, f"{s} {r}")
        ck("没登齐 → 状态还不是「已完成」",
           (r or {}).get("status") != "已完成", (r or {}).get("status"))
        ck("明说还差几条", "还差 1 条" in ((r or {}).get("note") or ""), (r or {}).get("note"))

        # ⑦ 跨批重复也要拦(前一批已经写进库了)
        s, r = 打("POST", f"{P}/evaluations/{eid}/items", {"逐题": [一条(样本[0])]})
        键 = list(((r or {}).get("field_errors") or {}).keys())
        ck("⑦ 跨批重复同一条样本也被拒(**原始结果不被覆盖**,改判走 /reviews)",
           s == 422 and any("逐题[0]" == k for k in 键), f"{s} {键}")

        # 最后一条:**故意不打分** —— 验「没打分」和「打了 0 分」分得开
        s, r = 打("POST", f"{P}/evaluations/{eid}/items",
                  {"逐题": [一条(样本[2],
                             评分改={"打了分吗": False, "分值": None,
                                   "理由": "这一题跑挂了,判不了"})]})
        ck("登齐了 → 自动置「已完成」", s == 201 and (r or {}).get("status") == "已完成",
           f"{s} {(r or {}).get('status')}")
        ck("齐了之后的 note 说清「登记齐了 ≠ 跑成功了」",
           "跑成功了" in ((r or {}).get("note") or ""), (r or {}).get("note"))

        # ② 已完成的不许再登记 —— 这一道只有在齐了之后才撞得到
        s, r = 打("POST", f"{P}/evaluations/{eid}/items", {"逐题": [一条(样本[0])]})
        ck("② 已完成的再登记 → 409(**再登记就是改历史**)",
           s == 409 and (r or {}).get("code") == "EVALUATION_ALREADY_DONE",
           f"{s} {(r or {}).get('code')}")

        # 库里对不对:3 条逐题、3 条分数,其中一条 value_known=false
        with 事务() as c:
            n条 = c.execute(text("select count(*) from evaluation_items "
                               "where evaluation_id=:e"), {"e": eid}).scalar()
            打了 = c.execute(text("""select count(*) from scores s
                                   join evaluation_items i on i.id=s.evaluation_item_id
                                   where i.evaluation_id=:e and s.value_known"""),
                           {"e": eid}).scalar()
            没打 = c.execute(text("""select count(*) from scores s
                                   join evaluation_items i on i.id=s.evaluation_item_id
                                   where i.evaluation_id=:e and not s.value_known"""),
                           {"e": eid}).scalar()
            零分 = c.execute(text("""select count(*) from scores s
                                   join evaluation_items i on i.id=s.evaluation_item_id
                                   where i.evaluation_id=:e
                                     and not s.value_known and s.value is not null"""),
                           {"e": eid}).scalar()
        ck("库里 3 条逐题结果", n条 == 3, n条)
        ck("2 条打了分 + 1 条没打分", (打了, 没打) == (2, 1), (打了, 没打))
        ck("**没打分的那条 value 是 NULL,不是 0**(0 会被平均进去,把分数腰斩)",
           零分 == 0, f"{零分} 条「没打分却存了数」")
    finally:
        清()

    print("\n" + "=" * 92)
    print(f"过 {len(过)} · 挂 {len(挂)}")
    for x in 挂: print("   ❌", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
