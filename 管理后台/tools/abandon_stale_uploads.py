#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把久未传字节的 `待上传` 推到 `已放弃` —— **让状态机里那一档真的到得了**。

## 为什么要有这个脚本

契约里 `upload` 状态机有 `已放弃` 一档,理由写着「它和『传了但没过』
必须分得开:前者没花存储」。而在这个脚本之前,**没有任何代码能推到那一档** ——
于是以后有人查「放弃了多少」,查出来永远是 0,他会当成「没人放弃过」。

**一档到不了的状态比少一档更糟**:少一档会有人问「放弃的算哪种」,
而到不了的那一档会给出一个错的答案,而且看起来是个正常的答案。

## 只碰 `待上传`

已经传了字节的那些**占着存储** —— 它们该走校验,不该被算成「没花存储」那一档。
判断在 `knowledge/upload_rules.py` 的 `该放弃吗()`(纯函数,可测边界)。

## 默认是 dry-run

    python3 tools/abandon_stale_uploads.py              # 只报,不改
    python3 tools/abandon_stale_uploads.py --做         # 真的改

默认不改是因为:这个脚本会被人手跑,而**手跑的清理脚本第一次跑时
没人知道它会动多少行**。先看清单再做。
"""
import argparse
import os
import sys
from datetime import datetime, timezone

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("services/api/app", "services/api/app/contract", "services/api/app/knowledge"):
    sys.path.insert(0, os.path.join(根, d))

from sqlalchemy import text

import states as ST
import upload_rules as UR
from db import 连接, 事务

_机 = ST.找("upload")
assert ST.能不能走("upload", "待上传", "已放弃"), "契约不允许 待上传 → 已放弃"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true", help="真的改(默认只报)")
    ap.add_argument("--门槛小时", type=float, default=UR.放弃门槛小时)
    ap.add_argument("--项目", default=None)
    a = ap.parse_args()

    现在 = datetime.now(timezone.utc)
    with 连接() as c:
        rs = c.execute(text("""
            select project_id, id, file_name, created_at, object_key
              from uploads
             where status = :st and archived_at is null
               and (cast(:p as text) is null or project_id = cast(:p as text))
             order by created_at
        """), {"st": "待上传", "p": a.项目}).mappings().all()

    该放 = []
    for r in rs:
        行, 几小时 = UR.该放弃吗(r["created_at"], 现在, 门槛小时=a.门槛小时)
        if 行:
            该放.append((dict(r), 几小时))

    print(f"▸ 待上传共 {len(rs)} 条,其中放过 {a.门槛小时} 小时的 {len(该放)} 条")
    for r, 几小时 in 该放[:50]:
        print(f"  · {r['project_id']}/{r['id']}  {r['file_name']}  "
              f"放了 {几小时:.1f} 小时")
    if not 该放:
        print("  没有要放弃的")
        return 0
    if not a.做:
        print("\n**这是 dry-run,一行都没改。** 加 `--做` 才真的改 —— "
              "手跑的清理脚本第一次跑时没人知道它会动多少行")
        return 0

    改了 = 0
    with 事务() as c:
        for r, 几小时 in 该放:
            # ⚠️ `and status='待上传'` 不能省:从查到改之间,
            # 有人可能刚把字节传上来了。把一条**已经花了存储**的记录
            # 标成「没花存储」那一档,会让存储对账永远差一点而查不出原因。
            改了 += c.execute(text("""
                update uploads set status=:新, updated_at=now(),
                       revision=coalesce(revision,0)+1,
                       verify_detail=cast(:vd as jsonb)
                 where project_id=:p and id=:i and status=:老
            """), {"新": "已放弃", "老": "待上传", "p": r["project_id"], "i": r["id"],
                   "vd": __import__("json").dumps(
                       {"放弃原因": f"要了上传地址但 {几小时:.1f} 小时内没传字节",
                        "门槛小时": a.门槛小时,
                        "没花存储": True}, ensure_ascii=False)}).rowcount
    print(f"\n改了 {改了} 条 → 已放弃"
          + ("" if 改了 == len(该放) else
             f"(少于 {len(该放)} —— 有几条在这中间被人传上来了,**那是对的**)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
