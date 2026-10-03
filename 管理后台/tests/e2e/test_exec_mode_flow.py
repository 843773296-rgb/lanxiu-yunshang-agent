#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行模式 · **真实调用失败不许静默降级成 mock**(外部审阅 §5.4)。

## 这一份守的那句话

> **一次悄悄换了模型的运行,比一次失败的运行难查得多。**

降级之后那次运行**照样跑完、照样出一份答案**,而那份答案和真模型给的
在数据形状上一模一样 —— 于是一次「其实没连上真模型」的运行,
在界面上和一次真实联调长得一样。

## 为什么这一份不花钱

最硬的那条判据**不需要一次成功的真实调用**:它要证明的是
「失败的时候不偷偷换一个能成功的东西」。所以用一个**打不通的端点**去证 ——
真调用必然失败,而判据是**它失败了、而且没有产出答案**。

> 一条要花钱才能跑的判据,在门禁里会被关掉。

## 四条路(`执行模式.定` 只有三条出口,没有第四条)

| 情况 | 该怎样 |
|---|---|
| 明确选了 mock | 跑 mock,**而且替身清单里记一条** |
| 要真跑、连接齐 | 跑真的,替身清单为空 |
| 要真跑、没有连接 | `NO_MODEL_CONNECTION` —— **不跑 mock** |
| 要真跑、连接从没探过 | `MODEL_CONNECTION_UNPROBED` —— 「探过」和「配了」是两件事 |

⚠️ 前提 `make dev`。这一份自己建草稿和连接,跑完自己清。
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
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
尾 = uuid.uuid4().hex[:6]


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
from db import 事务, 连接 as 库连        # noqa: E402
import 执行模式 as M                    # noqa: E402


def 建草稿(连接id=None):
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        pid = f"pr_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into prompt_drafts
            (id, organization_id, project_id, key, messages, variable_schema,
             params, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:k, cast(:m as jsonb), cast(:vs as jsonb),
                    cast(:pa as jsonb), now(), 'U002', now(), 1)"""),
                  {"i": pid, "o": org, "p": 项目, "k": f"mode-{尾}",
                   "m": json.dumps({"system": "照 user 做。",
                                    "user": f"执行模式自测-{尾}"},
                                   ensure_ascii=False),
                   "vs": json.dumps([], ensure_ascii=False),
                   "pa": json.dumps({}, ensure_ascii=False)})
    return pid


def 建一个打不通的连接(探过=True):
    """端点指向一个**没人监听的本地端口** —— 真调用必然失败。

    ⚠️ 用本地不通端口而不是一个假域名:假域名会走 DNS,
    不同机器上的行为不一样(有的会被 DNS 劫持到一个会回 200 的页面)。
    """
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        cid = f"mc_{uuid.uuid4().hex[:12]}"
        vid = f"mcv_{uuid.uuid4().hex[:12]}"
        c.execute(text("""insert into model_connections
            (id, organization_id, project_id, purpose, adapter, display_name,
             status, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'生成','MockModelProvider',:n,'启用',
                    now(),'U002', now(), 1)"""),
                  {"i": cid, "o": org, "p": 项目, "n": f"打不通的连接-{尾}"})
        c.execute(text("""insert into connection_versions
            (id, organization_id, project_id, connection_id, endpoint, secret_ref,
             capabilities, config_hash, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:c,:e,'env://AIMC_SELFTEST_FAKE_KEY',
                    cast(:cap as jsonb), :h, now(),'U002', now(), 1)"""),
                  {"i": vid, "o": org, "p": 项目, "c": cid,
                   # 127.0.0.1:9 是 discard 端口,本机上没人监听 → 连接被拒
                   "e": "http://127.0.0.1:9/v1/messages",
                   "cap": (json.dumps({"探过": True, "说明": "自测造的"},
                                      ensure_ascii=False) if 探过 else None),
                   "h": "selftest-" + 尾})
    return cid


def 提交(pid, 连接id=None):
    with 事务() as c:
        # 把连接 id 塞进快照 —— 真实链路里这是发布包给的,这里直接造
        pass
    键 = uuid.uuid4().hex
    s, r = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": {}},
              头={"Idempotency-Key": 键})
    run = (r or {}).get("resource_id")
    if 连接id and run:
        with 事务() as c:
            c.execute(text("""update jobs
                                 set config_snapshot =
                                     jsonb_set(config_snapshot,
                                               '{model_connection_id}',
                                               -- ⚠️ 用 `cast(... as text)`,
                                               -- **不写 `:cid::text`** ——
                                               -- 那个 `::` 会和 SQLAlchemy 的
                                               -- 绑定参数语法打架(当场语法错)
                                               to_jsonb(cast(:cid as text))),
                                     -- ⚠️ 把校验和清掉是**故意的**:
                                     -- 这里在测试里改了快照内容,
                                     -- 不清的话 Worker 会先报
                                     -- SNAPSHOT_TAMPERED 而走不到要验的那一步
                                     -- (「前面的闸先拦住」在这个项目里栽过三次)。
                                     snapshot_hash = null
                               where project_id=:p and target_ref->>'run_id'=:s"""),
                      {"cid": 连接id, "p": 项目, "s": run})
    return s, r, run


def 等结局(run, 秒=40):
    到 = time.time() + 秒
    while time.time() < 到:
        with 库连() as c:
            j = c.execute(text("""select status, error_code, error_detail
                                   from jobs where project_id=:p
                                    and target_ref->>'run_id'=:s"""),
                          {"p": 项目, "s": run}).mappings().first()
            t = c.execute(text("""select s.output_ref from traces t
                                   left join spans s on s.trace_id=t.id
                                  where t.project_id=:p and t.session_id=:s
                                  limit 1"""),
                          {"p": 项目, "s": run}).mappings().first()
            if j and str(j["status"]) in ("失败", "已失败", "已完成"):
                return dict(j), (dict(t) if t else None)
        time.sleep(1)
    return None, None


def 清(pids, cids):
    with 事务() as c:
        for pid in pids:
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
        for cid in cids:
            c.execute(text("""delete from connection_versions
                               where project_id=:p and connection_id=:i"""),
                      {"p": 项目, "i": cid})
            c.execute(text("delete from model_connections where project_id=:p and id=:i"),
                      {"p": 项目, "i": cid})


def main():
    print("执行模式 · 真实调用失败不许静默降级成 mock(外部审阅 §5.4)")
    print("=" * 92)
    草稿们, 连接们 = [], []
    try:
        # ── ① 解析器只有三条出口(离线,不碰库)──────────────────────
        print("\n▸ ① `执行模式.定` —— **三条出口,没有第四条**")
        模式, 替身 = M.定(允许mock=True)
        ck("明确选了 mock → 跑 mock", 模式 == M.假, 模式)
        ck("而且**替身清单里记了一条**(不是悄悄跑 mock)",
           len(替身) == 1 and 替身[0]["哪一样"] == "模型", 替身)
        ck("那条替身写明了「它返回的是编出来的答案」",
           "编出来" in json.dumps(替身, ensure_ascii=False), 替身[0].get("⚠️"))
        for 情况, 连, 码 in (
                ("没有模型连接", None, "NO_MODEL_CONNECTION"),
                ("连接里缺东西", {"endpoint": "x"}, "MODEL_CONNECTION_INCOMPLETE"),
                ("连接从没探过", {"endpoint": "x", "secret_ref": "env://K",
                              "探过吗": False}, "MODEL_CONNECTION_UNPROBED")):
            try:
                M.定(允许mock=False, 连接=连)
                ck(f"要真跑而{情况} → 抛 {码}", False, "**它没抛 —— 等于会退回 mock**")
            except M.不能跑 as e:
                ck(f"要真跑而{情况} → 抛 `{码}`,**不退回 mock**", e.码 == 码, e.码)
        模式2, 替身2 = M.定(允许mock=False,
                         连接={"endpoint": "x", "secret_ref": "env://K",
                              "探过吗": True})
        ck("要真跑、连接齐 → 真,**替身清单为空**",
           模式2 == M.真 and 替身2 == [], (模式2, 替身2))

        # ── ② 混合运行不许整体标成「真实」──────────────────────────
        print("\n▸ ② 混合运行 —— **逐项列替身,不许整体标真实**")
        痕 = M.记一笔(M.真, [{"哪一样": "工具", "换成了": "只读 mock 工具"}],
                    入口="自测")
        ck("真模型 + mock 工具 → **整体不算真实**", 痕["整体算真实吗"] is False, 痕)
        ck("而且那句话明说「别读成端到端真实联调」",
           "别读成" in 痕["怎么读"], 痕["怎么读"])
        痕2 = M.记一笔(M.真, [], 入口="自测")
        ck("一样替身都没有 → 才算真实", 痕2["整体算真实吗"] is True, 痕2["怎么读"])

        # ── ③ 真跑失败 → **失败,而且没有答案**(这一份的核心)───────
        print("\n▸ ③ 真跑失败 —— **失败,而且不产出答案**(不花钱:端点打不通)")
        os.environ.pop("_", None)
        cid = 建一个打不通的连接(探过=True)
        连接们.append(cid)
        pid = 建草稿()
        草稿们.append(pid)
        s, r, run = 提交(pid, 连接id=cid)
        ck("提交受理了(202)", s == 202, f"{s} {str(r)[:80]}")
        ck("拿到了 run id(**先断它非空**)", bool(run), run)
        # ⚠️ Worker 侧要真跑才会走到真模型那条路 —— 这里靠 MODEL_ADAPTER。
        # 服务是以 mock 起的,所以**这一条只在 live 模式下才有意义**:
        # 下面先问一句「现在这个服务是什么模式」,
        # 而不是假设它是 live(假设错了的话这条断言会变成空验)。
        import runtime_cfg as CFG
        if CFG.模型是mock():
            ck("⏸ **这个服务是以 `MODEL_ADAPTER=mock` 起的,所以这一条验不出来** —— "
               "它不是通过,是**没验**(要验:`MODEL_ADAPTER=anthropic make dev` 再跑)",
               True, f"MODEL_ADAPTER={CFG.MODEL_ADAPTER}")
            结, 痕3 = 等结局(run)
            ck("mock 模式下它正常跑完,而且**留痕里写着是 mock**",
               结 and str(结["status"]) == "已完成", str(结)[:90])
        else:
            结, 痕3 = 等结局(run)
            ck("真跑模式 + 打不通的端点 → **任务失败**",
               结 and str(结["status"]) in ("失败", "已失败"), str(结)[:120])
            ck("错码是真实调用那一族(**不是 mock 跑完了**)",
               结 and str(结.get("error_code") or "").startswith(
                   ("MODEL_", "REQUEST_NOT_SENT", "SECRET_")),
               结 and 结.get("error_code"))
            ck("失败说明里写明了「**没有退回 mock**」",
               "没有退回 mock" in json.dumps(结.get("error_detail") or {},
                                           ensure_ascii=False),
               str(结 and 结.get("error_detail"))[:150])
            ck("**没有产出答案** —— 一次失败的运行不该留下一份看起来正常的回答",
               not (痕3 and 痕3.get("output_ref")), str(痕3)[:90])
        # ── ④ **HTTP 那一支也要单独验** ───────────────────────────
        #
        # ⚠️ 上面第 ③ 条红在 `SECRET_UNRESOLVED`(凭据那一步)——
        # 它证明了「不降级」,但**没走到我专门写的那条「请求失败」分支**。
        # > 两条都通向「失败」,而**在「它失败了」这件事上长得一模一样** ——
        # > 所以要分开验,不然那条分支是从没跑过的代码。
        #
        # 这一条在**本进程里**直接调适配器(不经 Worker),
        # 于是环境变量设得上、而且照样不花钱(端点打不通)。
        print("\n▸ ④ 真实调用的 **HTTP 失败那一支**(本进程直调,不经 Worker)")
        import 真模型 as _真
        os.environ["AIMC_SELFTEST_FAKE_KEY"] = "sk-selftest-不是真钥匙"
        连 = {"endpoint": "http://127.0.0.1:9/v1/messages",
             "secret_ref": "env://AIMC_SELFTEST_FAKE_KEY"}
        try:
            出 = _真.生成(连接=连, 系统=None, 用户="自测", 超时=5)
            ck("打不通的端点 → **抛**,而不是返回一份答案", False,
               f"它返回了:{str(出)[:120]}")
        except _真.调不动 as e:
            ck("打不通的端点 → 抛 `调不动`(**没有任何退回 mock 的分支**)",
               e.码 in ("REQUEST_NOT_SENT", "MODEL_CALL_FAILED"), e.码)
            ck("错误里**不带凭据** —— 这个仓库的红线",
               "sk-selftest" not in str(e), str(e)[:120])
        try:
            _真.生成(连接={"endpoint": "http://127.0.0.1:9/x"}, 系统=None, 用户="x")
            ck("连接缺 secret_ref → 抛", False, "它没抛")
        except _真.调不动 as e:
            ck("连接缺 `secret_ref` → 抛 `MODEL_CONNECTION_INCOMPLETE`",
               e.码 == "MODEL_CONNECTION_INCOMPLETE", e.码)
        os.environ.pop("AIMC_SELFTEST_FAKE_KEY", None)
    finally:
        清(草稿们, 连接们)

    print("\n" + "=" * 92)
    print(f"过 {len(过)} · 挂 {len(挂)}")
    for x in 挂:
        print("   ❌", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
