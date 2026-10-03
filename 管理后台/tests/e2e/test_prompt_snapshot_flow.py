#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排队中的调试任务跑的是**提交时那一份** · 外部审阅 4.5 的验收用例。

## 这一份守的那句话

> **存一个哈希,还原不了内容。**

原来的链是:

    POST /prompt-runs  → jobs 存 snapshot_hash(配置的哈希)
    worker 捞到       → 按 prompt_id **重查 prompt_drafts** → 用现在的草稿跑

于是「提交 A → 排队 → 有人把草稿改成 B → Worker 跑的是 B」,
而那次运行在界面上看起来就是 A 的结果。

⚠️ 最刺眼的是当时提交那一侧的注释,它写着
「快照哈希:提交时那份配置 —— **任务建好之后改 Prompt 不影响它**」。
那句话是假的 —— **一句声称自己已经做到的注释,比没有注释更糟**,
它让读代码的人不去核。

(来源:`产品经理面试/output/lanxiu-review-20261003/` 第 4.5 条 + 第 8.2 节
 的「排队快照」「幂等冲突」两个用例。2026-10-03 在当时 HEAD 上重新核过,
 问题确实仍存在。)

## 怎么验

审阅给的操作就是对的:**暂停 Worker → 提交 A → 把草稿改成 B → 放 Worker 跑**。
这一份不去真暂停 Worker(那要动别人的进程),而是走等价的一条:
**先提交、立刻改草稿、再看那次运行到底用了哪一份** ——
判据不是「它跑完了」,是**展开后的模板里是 A 的字样还是 B 的字样**。

⚠️ 「它跑完了」和「它跑的是 A」是两件事,而前者在界面上看起来一样。

⚠️ 前提 `make dev`(要 Worker 在跑)。这一份自己建草稿、自己清。
"""
import json
import os
import sys
import time
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
名字 = f"快照自测-{尾}"
A字样 = f"这是提交时那一版-A-{尾}"
B字样 = f"这是改过之后那一版-B-{尾}"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
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
from db import 事务, 连接               # noqa: E402


def 建草稿(正文):
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        pid = f"pr_{uuid.uuid4().hex[:12]}"
        # ⚠️ 列名**查过库才写**:`prompt_drafts` 上没有 `name`,
        # 也没有 `draft_revision`(真实列是 `revision`)。
        c.execute(text("""insert into prompt_drafts
            (id, organization_id, project_id, key, messages, variable_schema,
             params, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:k, cast(:m as jsonb), cast(:vs as jsonb),
                    cast(:pa as jsonb), now(), 'U002', now(), 1)"""),
                  {"i": pid, "o": org, "p": 项目, "k": f"snap-{尾}",
                   # ⚠️ `messages` 的真实形状是**字典** `{"system":…, "user":…}`,
                   # 不是 `[{role, content}]` 那种列表(查了库里一条真草稿才写的 ——
                   # 第一版造成列表,`_mock生成` 里 `m.get(...)` 当场
                   # `AttributeError: 'list' object has no attribute 'get'`)。
                   # ⚠️ 标记要放在 **`user`** 里:`_mock生成` 取的是
                   # `m.get("user") or m.get("system")` —— user 优先。
                   # 第一版把 A/B 标记放在 system,于是渲染出来永远是那句
                   # 不变的 user 文本,**而「里面没有 B」那条照样打勾**
                   # (探针放在了代码不读的地方 = 又一条空断言)。
                   "m": json.dumps({"system": "照 user 里的话做。", "user": 正文},
                                   ensure_ascii=False),
                   "vs": json.dumps([], ensure_ascii=False),
                   "pa": json.dumps({"temperature": 0}, ensure_ascii=False)})
    return pid


def 改草稿(pid, 正文):
    with 事务() as c:
        c.execute(text("""update prompt_drafts
                             set messages = cast(:m as jsonb),
                                 revision = revision + 1,
                                 updated_at = now()
                           where project_id=:p and id=:i"""),
                  {# ⚠️ 标记要放在 **`user`** 里:`_mock生成` 取的是
                   # `m.get("user") or m.get("system")` —— user 优先。
                   # 第一版把 A/B 标记放在 system,于是渲染出来永远是那句
                   # 不变的 user 文本,**而「里面没有 B」那条照样打勾**
                   # (探针放在了代码不读的地方 = 又一条空断言)。
                   "m": json.dumps({"system": "照 user 里的话做。", "user": 正文},
                                   ensure_ascii=False),
                   "p": 项目, "i": pid})


def 等跑完(run_id, 秒=40):
    """等 Worker 把它跑完。**超时也要返回** —— 下面那条断言会把它报成失败,
    而不是让这份测试挂在这儿(挂住和失败在 CI 上长得不一样,前者更难查)。"""
    到 = time.time() + 秒
    while time.time() < 到:
        with 连接() as c:
            r = c.execute(text("""select t.id, s.input_ref
                                   from traces t
                                   left join spans s
                                     on s.trace_id = t.id and s.stage='generate'
                                  where t.project_id=:p and t.session_id=:s
                                  limit 1"""),
                          {"p": 项目, "s": run_id}).mappings().first()
            if r and r["input_ref"]:
                return dict(r)
            挂了 = c.execute(text("""select status, error_code, error_detail
                                     from jobs
                                    where project_id=:p
                                      and target_ref->>'run_id'=:s"""),
                            {"p": 项目, "s": run_id}).mappings().first()
            if 挂了 and str(挂了["status"]) in ("失败", "已失败"):
                return {"失败": dict(挂了)}
        time.sleep(1)
    return None


def 清(pids):
    with 事务() as c:
        for pid in pids:
            # ⚠️ **清理有顺序**:`outbox` 和 `job_events` 都指着 `jobs`
            # (外键 `fk_outbox_jobs`)—— 先删 jobs 会被数据库拒,
            # 而那个拒发生在 `finally` 里,会把**测试本身的结果整段吞掉**
            # (第一版就是这样:看不到一条 ✅/❌,只看到一个外键报错)。
            c.execute(text("""delete from outbox where project_id=:p and job_id in
                              (select id from jobs where project_id=:p
                                and target_ref->>'prompt_id'=:i)"""),
                      {"p": 项目, "i": pid})
            c.execute(text("""delete from job_events where job_id in
                              (select id from jobs where project_id=:p
                                and target_ref->>'prompt_id'=:i)"""),
                      {"p": 项目, "i": pid})
            c.execute(text("""delete from jobs where project_id=:p
                              and target_ref->>'prompt_id'=:i"""),
                      {"p": 项目, "i": pid})
            c.execute(text("delete from prompt_drafts where project_id=:p and id=:i"),
                      {"p": 项目, "i": pid})


def main():
    print("排队中的调试任务跑的是提交时那一份(外部审阅 4.5)")
    print("=" * 92)
    建了 = []
    try:
        # ── ① 提交 A → 立刻改成 B → 它必须跑 A ──────────────────────
        print("\n▸ ① 提交 A,排队期间草稿改成 B —— **跑的必须是 A**")
        pid = 建草稿(A字样)
        建了.append(pid)
        键 = uuid.uuid4().hex
        s, r = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": {}},
                  头={"Idempotency-Key": 键})
        ck("提交返回 202(异步信封,不直接给答案)", s == 202, f"{s} {str(r)[:90]}")
        # ⚠️ 返回里那个 id 叫 **`resource_id`**(查过返回才写的 ——
        # 第一版我猜的是 `run_id`,于是后面所有查询都查了个不存在的 id,
        # 而那让「里面没有 B」这条断言**空过**:被查的字符串是 `{}`,
        # 里面当然没有 B)。
        run_id = (r or {}).get("resource_id") or (r or {}).get("run_id")
        ck("拿到了这次运行的 id(**先断它非空**,否则下面全是空验)",
           bool(run_id), run_id)
        # 立刻改草稿 —— 这一步就是审阅里那个「排队后把草稿改成 B」
        改草稿(pid, B字样)
        with 连接() as c:
            现在草稿 = c.execute(text("""select messages from prompt_drafts
                                      where project_id=:p and id=:i"""),
                              {"p": 项目, "i": pid}).scalar()
        ck("草稿现在确实是 B(前提成立了,**不然下一条是空验**)",
           B字样 in json.dumps(现在草稿, ensure_ascii=False), str(现在草稿)[:80])

        出 = 等跑完(run_id)
        ck("那次运行跑完了(有 generate 这一段的输入留痕)",
           bool(出) and "失败" not in (出 or {}), str(出)[:140])
        投进去的 = json.dumps((出 or {}).get("input_ref") or {}, ensure_ascii=False)
        # ⚠️ **先断「真拿到了东西」** —— 下面那条「里面没有 B」在
        # 空字符串上**恒为真**,而它在那个 ✅ 上和真验到了长得一样。
        ck("拿到了那一段的输入留痕(**不是空的**)",
           len(投进去的) > 10, 投进去的[:80])
        # ⚠️⚠️ **这一条是整份测试的核心。**
        # 「它跑完了」和「它跑的是 A」是两件事,而前者在界面上看起来一样。
        ck("**展开后的模板里是 A** —— 提交时那一版",
           A字样 in 投进去的, 投进去的[:160])
        ck("**里面没有 B** —— 排队期间的改动没有漏进这次运行",
           B字样 not in 投进去的, 投进去的[:160])

        # ── ② 快照和它的校验和对得上 ───────────────────────────────
        print("\n▸ ② 快照 ≠ 一个哈希 —— **库里要有内容本身**")
        with 连接() as c:
            j = c.execute(text("""select snapshot_hash, config_snapshot
                                   from jobs where project_id=:p
                                    and target_ref->>'run_id'=:s"""),
                          {"p": 项目, "s": run_id}).mappings().first()
        j = dict(j or {})
        ck("库里找得到这个任务(**先断它在**,不然下面是空验)", bool(j), sorted(j))
        if not j:
            j = {"config_snapshot": None, "snapshot_hash": None}
        ck("`config_snapshot` 里存了**内容**(不只是哈希)",
           bool(j.get("config_snapshot"))
           and A字样 in json.dumps(j["config_snapshot"], ensure_ascii=False),
           str(j.get("config_snapshot"))[:120])
        import main as _api
        ck("`snapshot_hash` 就是那份内容的校验和(**执行前比得出来**)",
           bool(j.get("config_snapshot"))
           and j.get("snapshot_hash") == _api._哈希(j["config_snapshot"]),
           (j.get("snapshot_hash"), _api._哈希(j.get("config_snapshot") or {})))
        ck("快照里留了「从哪条草稿的哪一版固化来的」(只有 id 查不出当时是第几版)",
           (j.get("config_snapshot") or {}).get("草稿revision") is not None,
           (j.get("config_snapshot") or {}).get("草稿revision"))

        # ── ③ 幂等:同键同参复用,**同键异参冲突** ─────────────────
        print("\n▸ ③ 幂等 —— 同键同参复用,**同键异参要冲突**")
        s2, r2 = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": {}},
                    头={"Idempotency-Key": 键})
        # 注意:草稿已经变成 B 了,所以「同一个键 + 现在这份配置」算出来的哈希
        # 和原任务不一样 —— 这正是审阅说的那种冲突,**它该红给人看**。
        ck("同一个键、而配置已经变了 → **409 冲突**,不是把旧结果还给你",
           s2 == 409 and (r2 or {}).get("code") == "IDEMPOTENCY_CONFLICT",
           f"{s2} {(r2 or {}).get('code')}")
        ck("冲突那句话说清了后果(拿到的会是上一次那份配置的结果)",
           "上一次" in json.dumps(r2 or {}, ensure_ascii=False), str(r2)[:140])

        # 同键同参:把草稿改回 A,再用同一个键提交 → 该复用原任务
        改草稿(pid, A字样)
        s3, r3 = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": {}},
                    头={"Idempotency-Key": 键})
        ck("同一个键、配置也一样 → **复用原任务**(不多花一次钱)",
           s3 == 202 and json.dumps(r3 or {}, ensure_ascii=False).find(run_id) >= 0,
           f"{s3} {str(r3)[:110]}")

        # ── ④ 快照缺失要**明确失败**,不许退回现查草稿 ───────────
        print("\n▸ ④ 快照缺失 —— **明确失败**,不许退回现查草稿")
        pid2 = 建草稿(A字样)
        建了.append(pid2)
        键2 = uuid.uuid4().hex
        s4, r4 = 打("POST", P + "/prompt-runs", {"prompt_id": pid2, "变量": {}},
                    头={"Idempotency-Key": 键2})
        # ⚠️ **同一个取值在这个文件里写了两遍,而第一版只修了上面那一处** ——
        # 于是这里 `run2` 是 None,下面那条 UPDATE 一行都没匹配上,
        # 而「等跑完(None)」超时返回 None,报出来像是「闸没生效」。
        # (「两处写同一件事只修一处」这个形状今天第三次了。)
        run2 = (r4 or {}).get("resource_id") or (r4 or {}).get("run_id")
        ck("拿到了第二次运行的 id(**先断它非空**)", bool(run2), run2)
        # 把快照抹掉(模拟「这一列加之前建的老任务」),并把它退回排队中
        with 事务() as c:
            c.execute(text("""update jobs set config_snapshot = null,
                                 status='排队中', lease_owner=null, lease_until=null,
                                 attempts=0
                               where project_id=:p and target_ref->>'run_id'=:s"""),
                      {"p": 项目, "s": run2})
            c.execute(text("""delete from traces where project_id=:p
                              and session_id=:s"""), {"p": 项目, "s": run2})
        出2 = 等跑完(run2, 秒=30)
        坏 = (出2 or {}).get("失败") or {}
        ck("没有快照的任务 → **失败**,而且错码点名 `SNAPSHOT_MISSING`",
           str(坏.get("error_code")) == "SNAPSHOT_MISSING", str(出2)[:160])
        ck("失败说明里写清了「**不退回现查草稿**」及为什么",
           "不退回现查草稿" in json.dumps(坏.get("error_detail") or {},
                                      ensure_ascii=False),
           str(坏.get("error_detail"))[:160])
    finally:
        清(建了)

    print("\n" + "=" * 92)
    print(f"过 {len(过)} · 挂 {len(挂)}")
    for x in 挂:
        print("   ❌", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
