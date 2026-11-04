#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意见单,管理后台这一半(DF-03 第 2 步,2026-11-04;口径照《意见收集与能力持续改进 PRD》10-24)。
打真起着的管理后台,不调模型 —— 进 test-e2e-ci。

  ① 只收内部通道:不带凭证 / 凭证不对 → 403 INTERNAL_ONLY(只有服务账号不够 —— 否则谁都能以任意工号提)
  ② 字段(PRD §3.2):「有问题」要分类、要写一句哪里有问题;「有帮助」不带类;执行失败只能报问题;
     影响只收三档;没有提问人工号;独立建议现在不收 → 都 422,且定位到字段
  ③ 一个人对一轮只一条:再提 = 改那一条(revision 前进、**旧版进 history_snapshot**);另一个人评同一轮 → 另一条
  ④ 八种问题类型、三档影响库都收(管理后台、聊天站、聊天页、库 CHECK 四份是同一组 —— 不一致这里就插不进去)
  ⑤ 库这一层也拦:评价写成别的、「有问题」不带类 / 不写说明、独立建议挂了一轮、执行失败说有帮助 —— CHECK 当场拒
  ⑥ 受理之后不许再改 → 409 ALREADY_ACCEPTED(受理台还没做,用 SQL 把一条推到「核实中」来验)
  ⑦ 清单:待受理排前、带提问人快照、期望结果 / 影响 / 改过几次、按评价筛、翻页信封、汇总
  ⑧ 管理后台那条调用记录读的时候现对(库里有聊天站推来的记录才验得到;没有就明说**没验**)

**凭证**:本机用 ~/.lanxiu/internal-call 现有那份(只读,不改);CI 上没有这个文件,就现造一份、跑完删掉。
跑完把自己造的行删掉(chat_trace_ref 都以 e2e-op- 开头)。
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_lanxiu"
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
标 = "e2e-op-" + uuid.uuid4().hex[:8]
类们 = ("答错", "没答全", "证据不支持", "查错对象", "太慢或失败", "不好操作", "新增能力", "其他")


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 头=None, 谁="U001"):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(d):
    return (d or {}).get("code") if isinstance(d, dict) else None


def 字段(d):
    return set(((d or {}).get("field_errors") or {}).keys()) if isinstance(d, dict) else set()


def 凭证():
    路 = os.environ.get("LANXIU_INTERNAL_FILE") or os.path.expanduser("~/.lanxiu/internal-call")
    try:
        v = open(路, encoding="utf-8").read().strip()
        if v:
            return v, None
    except OSError:
        pass
    # CI:没有这份文件 —— 现造一份,跑完删掉(本机已有的那份绝不覆盖)
    os.makedirs(os.path.dirname(路), exist_ok=True)
    v = secrets.token_hex(24)
    with open(路, "w", encoding="utf-8") as f:
        f.write(v)
    os.chmod(路, 0o600)
    return v, 路


def 体(trace, 评价="有问题", 类="答错", 说明="工期算错了", 期望="应该是 21 天", 影响="影响业务办理",
      来源="问答", 工号="60000011", 姓名="林岚"):
    d = {"来源": 来源, "聊天站trace": trace, "会话号": "s-" + str(trace), "评价": 评价, "问题类型": 类, "说明": 说明,
         "期望结果": 期望, "影响": 影响, "提问人": {"工号": 工号, "姓名": 姓名, "角色": "门店顾问", "门店": "杭州店"}}
    return {k: v for k, v in d.items() if v is not None}


def main():
    凭, 造的 = 凭证()
    内 = {"X-Lanxiu-Internal": 凭}
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    提 = lambda b, h=内: 打("POST", P + "/opinions", b, h)
    try:
        print("▸ ① 只收内部通道")
        c, b = 提(体(标 + "-1"), {})
        ck("**只带服务账号、不带内部凭证 → 403 INTERNAL_ONLY**", c == 403 and 码(b) == "INTERNAL_ONLY", (c, b))
        c, b = 提(体(标 + "-1"), {"X-Lanxiu-Internal": 凭 + "x"})
        ck("凭证不对 → 403,理由说凭证不对", c == 403 and "凭证不对" in str((b or {}).get("message")), (c, b))

        print("\n▸ ② 字段")
        for 名, 改, 该红 in [
            ("「有问题」不分类", dict(类=None), "问题类型"),
            ("「有问题」不写哪里有问题(PRD:至少写一句)", dict(说明=None), "说明"),
            ("「有帮助」带分类", dict(评价="有帮助", 期望=None, 影响=None), "问题类型"),
            ("「有帮助」带期望结果", dict(评价="有帮助", 类=None, 影响=None), "期望结果"),
            ("执行失败说「有帮助」", dict(来源="执行失败", 评价="有帮助", 类=None, 期望=None, 影响=None), "评价"),
            ("影响不在三档里", dict(影响="很严重"), "影响"),
            ("没有提问人工号(不拿服务账号顶)", dict(工号=""), "提问人"),
            ("评价不是有帮助 / 有问题", dict(评价="一般"), "评价"),
            ("独立建议:入口还没做,这个口不收", dict(来源="独立建议"), "来源"),
        ]:
            c, b = 提(体(标 + "-1", **改))
            ck(f"{名} → 422,定位到「{该红}」", c == 422 and 该红 in 字段(b), (c, b))

        print("\n▸ ③ 一个人对一轮只一条,改了留旧版")
        c, a = 提(体(标 + "-1"))
        ck("**提一条「有问题·答错」→ 201 新建,待受理**", c == 201 and a.get("新建") is True and a.get("状态") == "待受理", (c, a))
        c, a2 = 提(体(标 + "-1", 类="没答全", 说明="少了加急费", 期望=None, 影响="反复出现"))
        ck("同一个人再提 → 改那一条(同一个 id、不新建、revision 前进)",
           c == 201 and a2.get("id") == a.get("id") and a2.get("新建") is False and a2.get("revision") == 2, (c, a2))
        c, a3 = 提(体(标 + "-1", 评价="有帮助", 类=None, 说明=None, 期望=None, 影响=None, 工号="60000002", 姓名="周店长"))
        ck("另一个人评同一轮 → 另一条(「有帮助」一键提交,说明可以不写)",
           c == 201 and a3.get("id") != a.get("id") and a3.get("新建") is True, (c, a3))
        with 库.connect() as cc:
            行 = cc.execute(text("""select verdict, problem_type, note, expected_note, impact_type, asker_staff_code,
                                          asker_snapshot, history_snapshot from opinions where project_id=:p and id=:i"""),
                            {"p": 项目, "i": a["id"]}).mappings().first()
        ck("**库里记的提问人是 60000011(林岚),不是服务账号**;改后的那句话落进去了",
           行 and 行["asker_staff_code"] == "60000011" and (行["asker_snapshot"] or {}).get("姓名") == "林岚"
           and 行["problem_type"] == "没答全" and 行["note"] == "少了加急费" and 行["expected_note"] is None
           and 行["impact_type"] == "反复出现", dict(行 or {}))
        史 = (行 or {}).get("history_snapshot") or []
        ck("**改之前那一版留在 history_snapshot 里**(问题类型 / 说明 / 期望结果 / 影响都在)",
           len(史) == 1 and 史[0].get("问题类型") == "答错" and 史[0].get("说明") == "工期算错了"
           and 史[0].get("期望结果") == "应该是 21 天" and 史[0].get("影响") == "影响业务办理" and 史[0].get("revision") == 1, 史)
        c, f = 提(体(标 + "-f", 来源="执行失败", 类="太慢或失败", 说明="等了三分钟没出来", 期望=None, 影响=None))
        ck("执行失败的那一轮能报问题", c == 201 and f.get("新建") is True, (c, f))

        print("\n▸ ④ 八种问题类型、三档影响库都收")
        坏 = []
        for j, 类 in enumerate(类们):
            c, b = 提(体(f"{标}-t{j}", 类=类, 说明="说明", 影响=("仅影响本次", "反复出现", "影响业务办理")[j % 3]))
            if c != 201:
                坏.append((类, c, b))
        ck("八种类型、三档影响都插得进(四份清单和库 CHECK 一致)", not 坏, 坏)

        print("\n▸ ⑤ 库这一层也拦")
        def 库拒(**kv):
            参 = {"i": 标 + "-x" + uuid.uuid4().hex[:4], "src": "问答", "t": 标 + "-x" + uuid.uuid4().hex[:4],
                  "v": "有问题", "pt": "答错", "n": "x", "p": 项目}
            参.update(kv)
            try:
                with 库.begin() as cc:
                    cc.execute(text("""insert into opinions (id, organization_id, project_id, created_at, source, chat_trace_ref,
                                          verdict, problem_type, note, asker_staff_code, status)
                                       select :i, organization_id, id, now(), :src, :t, :v, :pt, :n, 'x', '待受理'
                                         from projects where id=:p"""), 参)
                return False
            except Exception as e:
                return "check" in str(e).lower()
        ck("对照:合格的一行库收(这组「库拒」不是一律拒)", not 库拒(t=标 + "-ok"))
        ck("评价写成「一般」→ 库拒", 库拒(v="一般", pt=None))
        ck("「有问题」不带类 → 库拒", 库拒(pt=None))
        ck("「有问题」不写说明 → 库拒", 库拒(n=None))
        ck("独立建议却挂了一轮 → 库拒", 库拒(src="独立建议"))
        ck("执行失败说「有帮助」→ 库拒", 库拒(src="执行失败", v="有帮助", pt=None))

        print("\n▸ ⑥ 受理之后不许再改")
        with 库.begin() as cc:
            cc.execute(text("update opinions set status='核实中' where project_id=:p and id=:i"), {"p": 项目, "i": a["id"]})
        c, b = 提(体(标 + "-1", 类="查错对象"))
        ck("**已进「核实中」的那条再提 → 409 ALREADY_ACCEPTED**", c == 409 and 码(b) == "ALREADY_ACCEPTED", (c, b))
        with 库.connect() as cc:
            还 = cc.execute(text("select problem_type from opinions where project_id=:p and id=:i"),
                           {"p": 项目, "i": a["id"]}).scalar()
        ck("库里那条没被改(还是「没答全」)", 还 == "没答全", 还)

        print("\n▸ ⑦ 清单")
        c, l = 打("GET", P + "/opinions?limit=200")
        我的 = [x for x in (l or {}).get("items", []) if str(x.get("聊天站trace") or "").startswith(标)]
        ck("清单里有这次造的 12 条(11 条经接口 + ⑤ 里那条库对照)", c == 200 and len(我的) == 12, (c, len(我的)))
        态 = [x["状态"] for x in (l or {}).get("items", [])]
        ck("待受理的排在别的状态前面", 态 == sorted(态, key=lambda s: s != "待受理"), 态[:12])
        那条 = next((x for x in 我的 if x["id"] == a["id"]), {})
        ck("每条带提问人快照、影响、改过几次", (那条.get("提问人") or {}).get("门店") == "杭州店"
           and 那条.get("影响") == "反复出现" and 那条.get("改过几次") == 1, 那条)
        c, l2 = 打("GET", P + "/opinions?verdict=有帮助&limit=200")
        ck("按评价筛:只剩「有帮助」", c == 200 and l2["items"] and all(x["评价"] == "有帮助" for x in l2["items"]), (c, l2))
        c, l3 = 打("GET", P + "/opinions?limit=2&page=1")
        ck("翻页信封(每页 2 条、给总数和页数)", c == 200 and len(l3["items"]) == 2 and l3["total"] >= 12 and l3["页数"] >= 6,
           (c, l3 and {k: l3.get(k) for k in ("total", "页数")}))
        c, b = 打("GET", P + "/opinions?status=已采纳")
        ck("状态筛选写成旧口径「已采纳」→ 422(状态照 PRD 那七个)", c == 422, (c, b))
        ck("给了汇总(按状态 × 评价)", bool((l or {}).get("汇总")), l and l.get("汇总"))

        print("\n▸ ⑧ 管理后台那条调用记录现对")
        with 库.connect() as cc:
            有 = cc.execute(text("""select id, substr(request_id, 13) from traces
                                   where project_id=:p and request_id like 'lanxiu-chat:%' limit 1"""), {"p": 项目}).first()
        if 有:
            c, b = 提({**体(有[1]), "提问人": {"工号": 标, "姓名": "e2e"}})
            ck("评一轮聊天站推过来的 → 返回里直接对上管理后台 trace", c == 201 and b.get("管理后台trace") == 有[0], (c, b, 有))
        else:
            print("  ℹ️ 库里没有聊天站推来的调用记录 —— 「现对上管理后台 trace」这条**没验**(不是通过)")
        ck("还没推过来的那一轮 → 管理后台trace 是空的(不是报错)", a.get("管理后台trace") is None, a)
    finally:
        with 库.begin() as cc:
            cc.execute(text("delete from opinions where project_id=:p and (chat_trace_ref like :t or asker_staff_code=:s)"),
                       {"p": 项目, "t": 标 + "%", "s": 标})
        if 造的:
            os.remove(造的)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 意见单 · 管理后台:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
