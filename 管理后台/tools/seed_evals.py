#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灌一组评测数据 —— **给「不可比」和「不能当结论」那两条判断当对照**。

## 为什么要有这个脚本

`evaluations` / `datasets` / `samples` 一行数据都没有,
而一个空页面**证明不了任何判断真的会生效**:
「不可比时不给分数」在没有数据时的表现,和「忘了实现它」一模一样。

所以这里造四个实验,**故意让它们互相不可比**:

    甲 基线版   dv1 / 判据v1   ← 和乙可比(同题同判据)
    乙 候选版   dv1 / 判据v1
    丙 换了题   dv2 / 判据v1   ← 和甲不可比:跑的不是同一套题
    丁 换了判据 dv1 / 判据v2   ← 和甲不可比:换了判据
    戊 没基线                 ← **不能当结论**

⚠️ 还造一条**分集泄漏**的样本(同一个 group_id 跨了训练/独立测试),
用来验 `可以冻结吗()` 真的拦得住 —— 泄漏之后分数会虚高,
**而每一步看起来都正常**。

    python3 tools/seed_evals.py          # 只报,不写
    python3 tools/seed_evals.py --做     # 真的写
"""
import argparse
import hashlib
import json
import os
import sys
import uuid

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("services/api/app", "services/api/app/contract"):
    sys.path.insert(0, os.path.join(根, d))

from sqlalchemy import text

import evals as EV
from db import 连接, 事务

新 = lambda p: f"{p}_{uuid.uuid4().hex[:10]}"
_h = lambda s: "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()

题们 = [
    ("云锦一匹料要织多久", "大花楼木织机两人一组,一天五到六厘米;一件礼服约九米,织造五个月", "g-云锦工期"),
    ("云锦织造要几个月", "同上 —— **这是上一条的改写版**,所以 group_id 一样", "g-云锦工期"),
    ("挑花结本能不能跳过", "不能。跳过的结果不是快一点,是纹样错位,而错位下机才发现", "g-挑花"),
    ("三星及以下算差评吗", "算,而且自动进待处理清单;不进考核只给店长看", "g-评价口径"),
    ("差评的时效是多久", "72 小时", "g-评价口径"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true")
    a = ap.parse_args()

    with 连接() as c:
        r = c.execute(text("""select organization_id, id from projects
                             where archived_at is null order by created_at limit 1""")).first()
        if not r:
            sys.exit("库里没有项目 —— 先 make seed-demo")
        org, proj = r
        已有 = c.execute(text("select count(*) from evaluations where project_id=:p"),
                        {"p": proj}).scalar()

    # ── 先用纯逻辑验一遍这批样本能不能冻 ────────────────────────────
    样本们 = []
    for i, (问, 答, g) in enumerate(题们):
        # ⚠️ 前两条是改写关系(group_id 一样)。**故意都放独立测试** ——
        # 放两个集才是泄漏,这里先演示「干净」的样子。
        样本们.append(dict(id=f"s{i}", group_id=g, split="独立测试"))
    问题 = EV.可以冻结吗(样本们)
    print(f"▸ 干净的一批({len(样本们)} 条):{'可以冻结' if not 问题 else 问题}")

    泄 = [dict(x) for x in 样本们]
    泄[1]["split"] = "训练"          # 把改写版挪去训练集 = 泄漏
    问题2 = EV.可以冻结吗(泄)
    print(f"▸ 把改写版挪去训练集:{'❌ 没拦住' if not 问题2 else '✅ 拦住了'}")
    if 问题2:
        print(f"   {问题2[0][:120]}")

    print(f"\n▸ 库里已有 {已有} 个评测实验")
    计划 = [("甲 基线版", "dv1", "判据v1", True), ("乙 候选版", "dv1", "判据v1", True),
          ("丙 换了题", "dv2", "判据v1", True), ("丁 换了判据", "dv1", "判据v2", True),
          ("戊 没基线", "dv1", "判据v1", False)]
    for 名, dv, sv, 有基线 in 计划:
        print(f"   · {名:<12} 数据集版本 {dv} / 判据 {sv} / "
              f"{'有基线' if 有基线 else '**没有基线**'}")
    if not a.做:
        print("\n**这是 dry-run,一行都没写。** 加 `--做` 才真的写")
        return 0

    with 事务() as c:
        ds = 新("ds")
        c.execute(text("""insert into datasets
            (id, organization_id, project_id, name, format, purpose,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'汉服工艺问答','qa','独立测试', now(),'seed', now(),1)"""),
                  {"i": ds, "o": org, "p": proj})
        dv号 = {}
        for 名 in ("dv1", "dv2"):
            v = 新("dv")
            dv号[名] = v
            c.execute(text("""insert into dataset_versions
                (id, organization_id, project_id, dataset_id, split_map, content_hash,
                 sample_count, revision, created_at, created_by)
                values (:i,:o,:p,:d, cast(:sm as jsonb), :h, :n, 1, now(), 'seed')"""),
                      {"i": v, "o": org, "p": proj, "d": ds,
                       "sm": json.dumps({"独立测试": len(题们)}, ensure_ascii=False),
                       "h": _h(名 + json.dumps(题们, ensure_ascii=False)),
                       "n": len(题们)})
        sid = {}
        for i, (问, 答, g) in enumerate(题们):
            s = 新("sm")
            sid[i] = s
            c.execute(text("""insert into samples
                (id, organization_id, project_id, dataset_id, content, source,
                 review_status, split, group_id, content_hash,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d, cast(:c as jsonb),'seed','已通过','独立测试',
                        :g,:h, now(),'seed', now(),1)"""),
                      {"i": s, "o": org, "p": proj, "d": ds,
                       "c": json.dumps({"问": 问, "答": 答}, ensure_ascii=False),
                       "g": g, "h": _h(问)})
        for 名, dv, sv, 有基线 in 计划:
            e = 新("ev")
            c.execute(text("""insert into evaluations
                (id, organization_id, project_id, candidate_ref, baseline_ref,
                 dataset_version_id, scorer_version, status,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p, cast(:cand as jsonb), cast(:base as jsonb),
                        :dv,:sv,'已完成', now(),:by, now(),1)"""),
                      # ⚠️ `candidate_ref` / `baseline_ref` 是 **JSONB**,不是 TEXT ——
                      # 查过列类型才写的。今天这是同族第三次
                      # (前两次:裸串塞进 JSONB 的 `spans.error`、
                      #  结构塞进 TEXT 的 `feedback.note`)。
                      # 三次的共同点只有一个:**凭字段名猜类型**。
                      {"i": e, "o": org, "p": proj,
                       "cand": json.dumps({"kind": "prompt", "名": 名},
                                          ensure_ascii=False),
                       "base": (json.dumps({"kind": "prompt", "名": "基线"},
                                           ensure_ascii=False) if 有基线 else None),
                       "dv": dv号[dv], "sv": sv, "by": "seed"})
            for i in range(len(题们)):
                it = 新("ei")
                c.execute(text("""insert into evaluation_items
                    (id, organization_id, project_id, evaluation_id, sample_id,
                     raw_output, finished_at, created_at, created_by)
                    values (:i,:o,:p,:e,:s, cast(:r as jsonb), now(), now(),'seed')"""),
                          {"i": it, "o": org, "p": proj, "e": e, "s": sid[i],
                           "r": json.dumps({"text": f"{名} 对第 {i+1} 题的回答"},
                                           ensure_ascii=False)})
                # ⚠️ 最后一题**故意不打分**(value_known=false)——
                # 用来验「没打分不参与平均」:当 0 平均进去会让分数腰斩。
                打了 = (i < len(题们) - 1)
                c.execute(text("""insert into scores
                    (id, organization_id, project_id, evaluation_item_id, dimension,
                     value, value_known, source, scorer_version, rationale, by, at,
                     created_at, created_by)
                    values (:i,:o,:p,:it,'准确', :v, :vk,'确定性规则',:sv,:ra,'seed',
                            now(), now(),'seed')"""),
                          {"i": 新("sc"), "o": org, "p": proj, "it": it,
                           "v": (0.8 if 打了 else None), "vk": 打了, "sv": sv,
                           "ra": ("规则判定" if 打了 else "这一题没测")})
    print(f"\n✅ 灌好了:1 个数据集、2 个冻结版本、{len(题们)} 条样本、"
          f"{len(计划)} 个评测实验(每个 {len(题们)} 题,最后一题**故意没打分**)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
