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

  · **查询串**(11-05 补):带 id 类筛选参数的列表(workflow_id / execution_run_id / 监测的「应用」这几个查询参数;参数用 params 交给客户端转码,不手拼),塞 A 的 id 走 B 的路径 ——
    响应里(去掉回显的那个值)不许出现别的只属于 A 的 id。A 的 id 挑「真被那一列引用过的」(有桥请求的运行、有运行的工作流),
    不然一个没人引用的 id 塞进去什么都带不出来,「没漏」就白成立

已知不盖:流式接口、node_id 这类不是项目记录的参数(多个路径参数的接口 11-05 起一层一层取 id 也攻) —— 照数报出来,不算「验过了」。
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
# 没验的必须**逐条登记理由**(棘轮):新冒出一个没验的而没登记 → 红;登记了的现在验得到了 → 也红(逼人回来删)。
# 「83 / 88」这个比值分不出分母里那几个是有理由的豁免还是没人记得补的欠账(并行会话 11-05 指出)
不验登记 = {
    "/evaluations/compare": "要两个评测 id 当查询参数(a / b),参数名太通用,不进 id 类查询参数表;欠账:单独写一刀",
    "/opinion-samples/pending": "聊天站内部通道:按角色 / 门店现算待复核的,查询参数是身份不是项目记录 id",
    "/opinions/mine": "按提的人工号查自己的意见,查询参数是身份不是项目记录 id",
    "/chat-assistants/by-role/{role}/production": "路径参数是角色名(店长 / 顾问),不是项目记录 id",
    "/knob-plans/{key}": "数据:演示项目 A 里没有调参方案,取不到 A 的 key;欠账:A 里造一份再攻(数据类只打印不判)",
}
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


# 查询串里哪些参数是「项目记录的 id」:按参数名找同名列(应用 = 工作流 id)。node_id / 节点 是图里的节点名,不是项目记录
查询id列 = {"workflow_id": "workflow_id", "execution_run_id": "execution_run_id", "document_id": "document_id", "应用": "workflow_id"}
# 有的列表默认只给一部分(桥请求默认只列「待执行」)—— 别的取值也要试,不然漏的那部分看不见
查询额外 = {"/bridge-calls": [{}, {"状态": "已执行"}, {"状态": "执行失败"}]}


def 查询池(列, A的, n=4):
    """A 里**真被这一列引用过**的只属于 A 的值(先挑被引用最多的)。"""
    with 连接() as c:
        表们 = c.execute(text("""select table_name from information_schema.columns where table_schema='public'
                                 group by table_name having bool_or(column_name='project_id') and bool_or(column_name=:c)"""),
                         {"c": 列}).scalars().all()
        计 = {}
        for t in 表们:
            for v, k in c.execute(text(f'select "{列}"::text, count(*) from "{t}" where project_id=:p and "{列}" is not null group by 1'),
                                  {"p": A}):
                if v in A的:
                    计[v] = 计.get(v, 0) + k
    return [v for v, _ in sorted(计.items(), key=lambda kv: -kv[1])[:n]]


# 路径段 → 表(段名把 - 换成 _ 就是表名的不用登记;登记的是对不上的那几个)
段到表 = {"releases": "release_manifests", "runs": "execution_runs"}


def 库里取A的id(路径前段, 参名, A的, n=3):
    """列表取不到时的兜底:按路径里参数前面那一段找表,直接从库里拿只属于 A 的值。
    取不到(表对不上 / A 里没这种数据)就照实报「没验」。"""
    段 = 路径前段.rstrip("/").rsplit("/", 1)[-1]
    表 = 段到表.get(段, 段.replace("-", "_"))
    列 = "key" if 参名 == "key" else "id"
    with 连接() as c:
        if not c.execute(text("""select 1 from information_schema.columns where table_schema='public' and table_name=:t
                                  and column_name in (:c, 'project_id') having count(*) = 2"""), {"t": 表, "c": 列}).first():
            return []
        a = [x for x in c.execute(text(f'select "{列}"::text from "{表}" where project_id=:p limit 200'), {"p": A}).scalars()]
        b = set(c.execute(text(f'select "{列}"::text from "{表}" where project_id=:p'), {"p": B}).scalars())
    return [x for x in a if x not in b and (列 != "id" or x in A的)][:n]


def 取A的id(客, 列表路径, A的, n=3):
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
            ids = [x.get("id") for x in 列 if isinstance(x, dict) and x.get("id") in A的][:n]
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
        查询漏, 查询验 = [], []
        查询参数 = {}
        for r in 平(M.app.routes):
            if "GET" in (getattr(r, "methods", None) or set()) and "{project_id}" in r.path:
                qs = [q.alias or q.name for q in r.dependant.query_params if (q.alias or q.name) in 查询id列]
                if qs:
                    查询参数[r.path] = qs

        def 记没验(原因, 路):
            没验.setdefault(原因, []).append(路)

        for 路 in 路由们:
            参 = [p for p in re.findall(r"\{(\w+)\}", 路) if p != "project_id"]
            if 形态.get(路) == EP.流:
                记没验("流式接口", 路)
                continue
            if not 参:
                # 查询串里的 id 类筛选(11-05 补)
                for q in 查询参数.get(路, []):
                    池 = 查询池(查询id列[q], A的)
                    if not 池:
                        记没验(f"查询参数 {q}:A 里没有被引用的 id", 路)
                        continue
                    查询验.append((路, q))
                    for v in 池:
                        for 额 in 查询额外.get(路.split("{project_id}", 1)[1], [{}]):
                            rq = 客.get(路.replace("{project_id}", B), params={q: v, **额}, headers={"X-Dev-User": 攻})
                            if rq.status_code == 200:
                                m = 型.search(rq.text.replace(v, ""))
                                if m:
                                    查询漏.append((路, q, v, 额, m.group(1)))
                r = 客.get(路.replace("{project_id}", B), headers={"X-Dev-User": 攻})
                if r.status_code != 200:
                    记没验(f"B 路径回 {r.status_code}(要查询参数 / 不适用)", 路)
                    continue
                列表验 += 1
                m = 型.search(r.text)
                if m:
                    列表漏.append((路, m.group(1)))
                continue
            # 一层一层取:第一个参数从它前面那段的列表里取 A 的 id,填上之后第二个参数再从下一段的列表里取 ……
            # (/workflows/{wid}/versions/{vid}:先拿 A 的工作流,再拿那条工作流的版本)。多个参数各取第一个能取到的
            def 取(前, k):
                # 前面那段不一定是列表(工作流的版本列在 /workflows/{wid} 的详情里,不是 /workflows/{wid}/versions)—— 再往上一段试
                return 取A的id(客, 前, A的, n=8) or 取A的id(客, 前.rsplit("/", 1)[0], A的, n=8) or 库里取A的id(前, k, A的)

            def 走(填, 剩):
                """一层一层取;中间那一层逐个试候选,直到下一层取得到(最新那条工作流可能还没有版本 —— 只试第一个会时验时不验)。"""
                if not 剩:
                    return {}
                k = 剩[0]
                ids = 取(填.split("{" + k + "}")[0].rstrip("/"), k)
                for i in (ids if len(剩) > 1 else ids[:1]):
                    下 = 走(填.replace("{" + k + "}", i), 剩[1:])
                    if 下 is not None:
                        return {k: ([i] if len(剩) > 1 else ids[:3]), **下}
                return None

            组 = 走(路.replace("{project_id}", A), 参) or {}
            if len(组) < len(参):
                记没验("A 那边取不到只属于 A 的 id(没有同前缀的列表 / 列表是空的)", 路)
                continue
            详情验 += 1
            末 = 参[-1]
            for i in 组[末]:
                b路 = 路.replace("{project_id}", B)
                for k in 参[:-1]:
                    b路 = b路.replace("{" + k + "}", 组[k][0])
                rb = 客.get(b路.replace("{" + 末 + "}", i), headers={"X-Dev-User": 攻})
                # 去掉自己塞进去的那几个 id 再找:响应回显路径里的 id(比如拼一个「调用地址」)不是漏数据
                正文 = rb.text
                for x in [i] + [组[k][0] for k in 参[:-1]]:
                    正文 = 正文.replace(x, "")
                m = 型.search(正文) if rb.status_code == 200 else None
                if m:
                    详情漏.append((路, i, m.group(1)))

        ck("**列表:B 项目的列表里一个只属于 A 的 id 都没有**", not 列表漏, 列表漏[:5])
        ck("**详情:拿 A 的 id 走 B 的路径,一条都拿不到**", not 详情漏, 详情漏[:5])
        ck("**查询串:塞 A 的 id 走 B 的路径,带不出 A 的任何记录**", not 查询漏, 查询漏[:5])
        ck("查询串验到的不少于 3 个(执行记录按工作流 / 桥请求按运行 / 监测按应用)", len(查询验) >= 3, 查询验)
        ck("列表验到的数量不低于地板(防「一个都没验所以一条都没漏」)", 列表验 >= 列表下限, (列表验, 列表下限))
        ck("详情验到的数量不低于地板", 详情验 >= 详情下限, (详情验, 详情下限))
        # 拆成两件(CLAUDE.md「判据红不红取决于库里碰巧有什么」那条):
        #   结构上没法攻的(要身份参数 / 路径参数不是记录 id / 流式 / 两个评测 id)→ 判据,两头都盯
        #   A 里碰巧没这种数据的 → **只打印、不判红**:CI 是新库,数据少,判它就是在量库里有什么,不是在量代码
        #   (代码那一头由「详情验到的不低于地板」兜着 —— 地板是硬的)
        数据缺 = {x.replace("/api/v1/projects/{project_id}", "") for k, v in 没验.items() if k.startswith("A 那边取不到") for x in v}
        结构没验 = {x.replace("/api/v1/projects/{project_id}", "") for k, v in 没验.items() if not k.startswith("A 那边取不到") for x in v}
        结构登记 = {k for k, v in 不验登记.items() if not v.startswith("数据:")}
        # 登记成结构原因的(比如路径参数是角色名),取 id 那一步也会落进「取不到」那一桶 —— 按登记的原因归类
        结构没验 |= 数据缺 & 结构登记
        数据缺 -= 结构登记
        ck("**结构上没法攻的每一个都登记了理由**(新冒出来一个、又没登记 → 红)", not (结构没验 - 结构登记),
           sorted(结构没验 - 结构登记))
        ck("登记了的结构原因现在还成立(攻得到了就从 不验登记 里删掉 —— 豁免不许囤积)", not (结构登记 - 结构没验),
           sorted(结构登记 - 结构没验))
        # 数据那一桶的「推它的手」(并行会话 11-05 指出):**不对称** —— 不判「它还缺」(那才是量库),只判「登记成数据缺的,
        # 这一轮攻到了」→ 红一次,逼人回来删那行登记。CI 新库永远安静;本机哪天数据齐了红一次,正是该删的时候
        数据登记 = {k for k, v in 不验登记.items() if v.startswith("数据:")}
        攻到了的 = sorted(数据登记 - 数据缺 - 结构没验)
        ck("登记成「A 里没数据」的,这一轮要是攻到了就红一次(从 不验登记 里删掉那行)", not 攻到了的, 攻到了的)
        if 数据缺:
            print(f"  ℹ️ A 里碰巧没数据、这一轮没攻到的 {len(数据缺)} 个(**不是判据**,换一个库数量会变):{', '.join(sorted(数据缺))}")
        print(f"\n  ℹ️ 共 {len(路由们)} 个带项目的 GET;列表验 {列表验}、详情验 {详情验}、查询串验 {len(查询验)};没验的按原因(**不是验过了**):")
        for k, v in sorted(没验.items(), key=lambda kv: -len(kv[1])):
            print(f"     · {k}:{len(v)} 个 —— {', '.join(x.replace('/api/v1/projects/{project_id}', '') for x in v)}")
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
