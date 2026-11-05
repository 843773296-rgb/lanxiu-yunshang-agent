#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨项目读取隔离 —— **按真路由表枚举攻击**(2026-11-05;用户 11-04 拍「上第二个正式项目之前必须补好」)。

## 为什么是这个形状

写入侧是结构(复合外键,跨项目引用插不进去);读取侧原来是约定:每一句 SQL 自己写 `project_id = :p`,
漏一句就读到别家项目的数据,**接口照样回 200,什么都不报**。原来的攻击是约 10 份 e2e 逐个接口手写的 ——
**新接口全靠人记得补**,漏了不会有任何东西红。

这一份不靠人记:从 FastAPI 的**真路由表**(`main.app.routes`)枚举每一个 GET,新接口自动被攻击。

  · 受害方 A = project_demo_a(有数据),攻击方 = 一个只在 project_demo_b 里的临时管理员(带专项授权 ——
    权限不够被 403 挡住的话,「没读到」就分不清是隔离挡的还是权限挡的)
  · **列表**:B 路径下的每个列表,响应里一个「只属于 A」的 id 都不许出现
  · **详情**:先以 A 的人取 A 的列表拿几个 id,再用 B 的路径去要 —— 必须 404(或至少不把那条记录给出来)
  · 「只属于 A 的 id」= 库里所有带 project_id 的表里,A 有、B 没有的 id(主键是 (project_id, id) 的表可能两边同名)

**进程内跑**(TestClient,不打 8801):咬合在代码副本上改坏一处取数,这里调的就是副本里的代码 ——
打常驻服务的话,副本里改了什么服务都看不见,咬合会砍空。

已知不盖:查询串里带 id 的筛选(?workflow_id=…)、要两个以上路径参数的接口、流式接口 —— 照数报出来,不算「验过了」。
"""
import json
import os
import re
import sys
import uuid
import warnings

warnings.filterwarnings("ignore")
_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(_根, "services", "api", "app"), os.path.join(_根, "services", "api", "app", "contract"),
                os.path.join(_根, "services", "api", "app", "runtime")]
from sqlalchemy import text  # noqa: E402
from db import 事务, 连接  # noqa: E402

A, B = "project_demo_a", "project_demo_b"
过, 挂 = [], []
# 地板(防空集合上「一条都没漏」自动成立);够高就行,不用跟着实际涨
列表下限, 详情下限 = 30, 10


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 只属于A的id():
    with 连接() as c:
        表们 = c.execute(text("""select table_name from information_schema.columns where table_schema='public'
                                 group by table_name having bool_or(column_name='project_id') and bool_or(column_name='id')""")).scalars().all()
        a, b = set(), set()
        for t in 表们:
            for p, s in ((A, a), (B, b)):
                s.update(x for x in c.execute(text(f'select id::text from "{t}" where project_id=:p'), {"p": p}).scalars() if x)
    return {x for x in a - b if len(x) >= 6}


def 取A的id(客, 列表路径, A的):
    """以 A 的人取 A 的列表,挑几个只属于 A 的 id。列表信封不统一(items / 应用 / 数据集 / 连接 …),
    所以找响应里**第一个「元素是带 id 的对象」的列表**;管理员(U001)和带专项授权的标注员(U004)都试,有的列表只开给其中一个。"""
    for 谁 in ("U001", "U004"):
        r = 客.get(列表路径, headers={"X-Dev-User": 谁})
        if r.status_code != 200:
            continue
        try:
            j = r.json()
        except ValueError:
            continue
        候选 = [j] if isinstance(j, list) else [v for v in (j.values() if isinstance(j, dict) else []) if isinstance(v, list)]
        for 列 in 候选:
            ids = [x.get("id") for x in 列 if isinstance(x, dict) and x.get("id") in A的][:3]
            if ids:
                return ids
    return []


def main():
    from fastapi.testclient import TestClient
    import endpoints as EP
    import main as M

    客 = TestClient(M.app)
    攻 = "E2EXP" + uuid.uuid4().hex[:6]
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": B}).scalar()
        c.execute(text("""insert into memberships (id, organization_id, project_id, user_id, role, special_grants, status,
                              created_at, created_by, updated_at, revision)
                          values (:i, :o, :p, :u, 'admin', cast(:g as jsonb), 'active', now(), 'e2e', now(), 1)"""),
                  {"i": "mb_" + uuid.uuid4().hex[:12], "o": org, "p": B, "u": 攻,
                   "g": json.dumps(["查看敏感输入/独立测试答案", "审批工具动作"], ensure_ascii=False)})
    try:
        A的 = 只属于A的id()
        print(f"  ℹ️ A 有、B 没有的 id:{len(A的)} 个")
        ck("样本:A 有、B 没有的 id 不少于 100 个", len(A的) >= 100, len(A的))
        型 = re.compile(r"(?<![A-Za-z0-9_\-])(" + "|".join(sorted(map(re.escape, A的), key=len, reverse=True)) + r")(?![A-Za-z0-9_\-])")

        形态 = {EP.全路径(a): a["形态"] for a in EP.接口表 if a["方法"] == "GET"}
        # 这一版 FastAPI 把 include_router 进来的路由包成 _IncludedRouter(不展开)—— 第一次只扫到 5 个,是地板拦下来的。
        # 往 original_router 里递归展开;地板照旧盯着「扫到的不能太少」
        def 平(rs):
            for r in rs:
                if type(r).__name__ == "_IncludedRouter":
                    yield from 平(r.original_router.routes)
                else:
                    yield r
        路由们 = sorted({r.path for r in 平(M.app.routes) if "GET" in (getattr(r, "methods", None) or set()) and "{project_id}" in r.path})
        ck("扫到的带项目 GET 不少于 80 个(契约里登记了 88 个;扫少了就是展开路由那一步漏了)", len(路由们) >= 80, len(路由们))
        列表漏, 详情漏, 列表验, 详情验, 没验 = [], [], 0, 0, {}

        def 记没验(原因, 路):
            没验.setdefault(原因, []).append(路)

        for 路 in 路由们:
            参 = [p for p in re.findall(r"\{(\w+)\}", 路) if p != "project_id"]
            if 形态.get(路) == EP.流:
                记没验("流式接口", 路)
                continue
            if not 参:
                r = 客.get(路.replace("{project_id}", B), headers={"X-Dev-User": 攻})
                if r.status_code != 200:
                    记没验(f"B 路径回 {r.status_code}(要查询参数 / 不适用)", 路)
                    continue
                列表验 += 1
                m = 型.search(r.text)
                if m:
                    列表漏.append((路, m.group(1)))
                continue
            if len(参) > 1:
                记没验("两个以上路径参数", 路)
                continue
            前 = 路.split("{" + 参[0] + "}")[0].rstrip("/")
            ids = 取A的id(客, 前.replace("{project_id}", A), A的)
            if not ids:
                记没验("A 那边取不到只属于 A 的 id(没有同前缀的列表 / 列表是空的)", 路)
                continue
            详情验 += 1
            for i in ids:
                rb = 客.get(路.replace("{project_id}", B).replace("{" + 参[0] + "}", i), headers={"X-Dev-User": 攻})
                if rb.status_code == 200 and 型.search(rb.text):
                    详情漏.append((路, i, rb.status_code))

        ck("**列表:B 项目的列表里一个只属于 A 的 id 都没有**", not 列表漏, 列表漏[:5])
        ck("**详情:拿 A 的 id 走 B 的路径,一条都拿不到**", not 详情漏, 详情漏[:5])
        ck("列表验到的数量不低于地板(防「一个都没验所以一条都没漏」)", 列表验 >= 列表下限, (列表验, 列表下限))
        ck("详情验到的数量不低于地板", 详情验 >= 详情下限, (详情验, 详情下限))
        print(f"\n  ℹ️ 共 {len(路由们)} 个带项目的 GET;列表验 {列表验}、详情验 {详情验};没验的按原因(**不是验过了**):")
        for k, v in sorted(没验.items(), key=lambda kv: -len(kv[1])):
            print(f"     · {k}:{len(v)} 个 —— {', '.join(v[:4])}{' …' if len(v) > 4 else ''}")
    finally:
        with 事务() as c:
            c.execute(text("delete from memberships where project_id=:p and user_id=:u"), {"p": B, "u": 攻})

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 跨项目读取隔离(按真路由表枚举):{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
