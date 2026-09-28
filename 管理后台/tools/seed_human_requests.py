#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灌一批人工待办 —— **给那七条判断当对照**。

一个空列表证明不了任何判断真的会生效:
「过期的不许批」在没有过期请求时的表现,和「忘了实现它」一模一样。

造五条,**每条针对一条判断**:

    ① 正常待批      有截止时间、在期内、候选角色对得上   ← 能批
    ② 已经过期      截止时间在过去                     ← 不能批(过期)
    ③ 没设截止时间  expires_at 是 NULL                 ← 不能批(**不当成永不过期**)
    ④ 别的角色      candidate_roles 里没有 editor       ← 不能批(角色不对)
    ⑤ 已经批过      status=approved                    ← 不能批(一次只能处理一次)

    python3 tools/seed_human_requests.py          # 只报
    python3 tools/seed_human_requests.py --做     # 真写
"""
import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("services/api/app", "services/api/app/contract"):
    sys.path.insert(0, os.path.join(根, d))

from sqlalchemy import text

from db import 连接, 事务

新 = lambda p: f"{p}_{uuid.uuid4().hex[:10]}"
现 = datetime.now(timezone.utc)

# ⚠️ 候选角色必须写**真的有审批能力**的那些。
# 第一版写的是 ["admin","editor"],而权限矩阵里 editor 是 deny、
# admin 是 grantable(要显式授权)—— 于是那几条请求**谁都批不了**:
# approver 被「不在候选角色里」拒,editor 被「没有审批能力」拒。
# 两个理由都说得通,而真相是这条请求从出生就没人能批。
# 这条现在由 `approvals.候选角色里有人能审吗()` 在列表和详情里报出来。
计划 = [
    ("正常待批", "pending", 现 + timedelta(hours=6), ["approver", "admin"]),
    ("已经过期", "pending", 现 - timedelta(hours=2), ["approver"]),
    ("没设截止时间", "pending", None, ["approver"]),
    ("角色不对", "pending", 现 + timedelta(hours=6), ["admin"]),
    # ⚠️ 这一条故意让候选里**一个有审批能力的都没有** —— 验那条新判断
    ("没人能批", "pending", 现 + timedelta(hours=6), ["editor", "viewer"]),
    ("已经批过", "approved", 现 + timedelta(hours=6), ["approver"]),
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
        run = c.execute(text("""select id from execution_runs where project_id=:p
                              order by created_at desc limit 1"""), {"p": proj}).scalar()
        tv = c.execute(text("""select id from tool_versions where project_id=:p
                             order by created_at desc limit 1"""), {"p": proj}).scalar()
        已有 = c.execute(text("select count(*) from human_requests where project_id=:p"),
                        {"p": proj}).scalar()

    print(f"▸ 库里已有 {已有} 条待办。要造 {len(计划)} 条,**每条针对一条判断**:")
    for 名, st, exp, 角色 in 计划:
        当 = ("在期内" if exp and exp > 现 else
             ("**已过期**" if exp else "**没设截止时间**"))
        print(f"   · {名:<12} status={st:<9} {当:<16} 候选角色 {角色}")
    if not run:
        print("\n⚠️ 库里没有 execution_run —— 待办要挂在一次运行上(外键)")
        return 1
    if not a.做:
        print("\n**这是 dry-run,一行都没写。** 加 `--做` 才真的写")
        return 0

    写了 = 0
    with 事务() as c:
        for 名, st, exp, 角色 in 计划:
            载荷 = {"path": "/out/报价单-李明明.pdf",
                   "content": "云锦礼服定制报价:九米料,工期五个月……" * 12,
                   "secret_ref": "conn:deepseek#key"}
            h = "sha256:" + hashlib.sha256(
                json.dumps(载荷, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            c.execute(text("""
                insert into human_requests (id, organization_id, project_id,
                    execution_run_id, kind, payload_ref, allowed_fields,
                    candidate_roles, status, expires_at, arguments_hash,
                    tool_version_id, target_ref, risk_note,
                    created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:r,'tool_write', cast(:pl as jsonb),
                        cast(:af as jsonb), cast(:cr as jsonb), :st, :exp, :h, :tv,
                        cast(:tg as jsonb), :rn, now(), 'seed', now(), 1)"""),
                      {"i": 新("hr"), "o": org, "p": proj, "r": run,
                       "pl": json.dumps(载荷, ensure_ascii=False),
                       "af": json.dumps(["content"], ensure_ascii=False),
                       "cr": json.dumps(角色, ensure_ascii=False),
                       "st": st, "exp": exp, "h": h, "tv": tv,
                       "tg": json.dumps({"资源": "/out/报价单-李明明.pdf",
                                         "动作": "写文件"}, ensure_ascii=False),
                       "rn": f"[{名}] 往 /out 写一个客户可见的报价单 —— "
                             f"**不可逆**:写出去之后顾客可能已经看到了"})
            写了 += 1
    print(f"\n✅ 造了 {写了} 条待办。⚠️ 载荷里**故意放了一个 `secret_ref`** ——"
          f"用来验详情接口的脱敏(它该显示成 `<已脱敏>`),"
          f"和一段超长 content(该显示成形状)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
