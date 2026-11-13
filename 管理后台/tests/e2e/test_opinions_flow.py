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


def _库拒事件(库, text, 项目, oid, 动作):
    try:
        with 库.begin() as cc:
            cc.execute(text("""insert into opinion_events (id, organization_id, project_id, created_at, opinion_id, action_code, to_status)
                               select 'oe_x' || md5(random()::text), organization_id, id, now(), :o, :a, '不采纳'
                                 from projects where id=:p"""), {"o": oid, "a": 动作, "p": 项目})
        return False
    except Exception as e:
        return "check" in str(e).lower()


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
            ("独立建议却挂了一轮", dict(来源="独立建议", 评价="建议"), "聊天站trace"),
            ("挂一轮的却说「建议」", dict(评价="建议"), "评价"),
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

        print("\n▸ ⑨ 独立建议:不挂任何一轮,提交键防重")
        建 = lambda 说明="想要按门店导出意见", 类="新增能力": {"来源": "独立建议", "评价": "建议", "问题类型": 类, "说明": 说明,
                                                     "提问人": {"工号": 标, "姓名": "e2e"}}
        c, b = 提(建())
        ck("**不带提交键 → 422,定位到 Idempotency-Key**(没有那一轮可以拿来防重)",
           c == 422 and "Idempotency-Key" in 字段(b), (c, b))
        键 = {**内, "Idempotency-Key": 标 + "-k1"}
        c, s1 = 提(建(), 键)
        ck("带提交键 → 201 新建,评价记成「建议」", c == 201 and s1.get("新建") is True and s1.get("评价") == "建议", (c, s1))
        c, s2 = 提(建(), 键)
        ck("**同一个键、同样内容再提(网断了重试)→ 返回原来那条,不新建**",
           c == 201 and s2.get("id") == s1.get("id") and s2.get("新建") is False, (c, s2))
        c, b = 提(建(说明="另一件事"), 键)
        ck("同一个键、内容不一样 → 409 IDEMPOTENCY_CONFLICT(不许被旧的吞掉)", c == 409 and 码(b) == "IDEMPOTENCY_CONFLICT", (c, b))
        c, s3 = 提(建(说明="另一件事"), {**内, "Idempotency-Key": 标 + "-k2"})
        ck("换一个键 → 另一条", c == 201 and s3.get("id") != s1.get("id") and s3.get("新建") is True, (c, s3))
        with 库.connect() as cc:
            几 = cc.execute(text("select count(*) from opinions where project_id=:p and asker_staff_code=:s and source='独立建议'"),
                           {"p": 项目, "s": 标}).scalar()
        ck("库里这个人的独立建议正好 2 条(重试没有多出一条)", 几 == 2, 几)
        ck("库这一层:独立建议不带提交键 → 库拒", 库拒(src="独立建议", t=None, v="建议"))

        print("\n▸ ⑩ 我的意见")
        c, b = 打("GET", P + "/opinions/mine?" + urllib.parse.urlencode({"工号": 标}))
        ck("不带内部凭证 → 403", c == 403 and 码(b) == "INTERNAL_ONLY", (c, b))
        c, m = 打("GET", P + "/opinions/mine?" + urllib.parse.urlencode({"工号": 标}), 头=内)
        with 库.connect() as cc:
            应 = cc.execute(text("select count(*) from opinions where project_id=:p and asker_staff_code=:s"),
                           {"p": 项目, "s": 标}).scalar()
        ck("只列这个人自己的(条数和库里这个工号的行数一致,两条独立建议都在)",
           c == 200 and m["total"] == 应 and len(m["items"]) == 应
           and {s1.get("id"), s3.get("id")} <= {x["id"] for x in m["items"]}, (c, 应, m))
        ck("**进度是给提的人看的话**(待受理 → 「已收到」),带一句说明",
           all(x["进度"] == "已收到" and x["进度说明"] for x in m["items"]), m["items"])
        ck("**字段裁剪**:不给提问人快照、管理后台 trace、旧版、revision",
           all(not ({"提问人", "管理后台trace", "改过几次", "revision", "history_snapshot"} & set(x)) for x in m["items"]),
           [sorted(x) for x in m["items"]][:1])
        c, m2 = 打("GET", P + "/opinions/mine?" + urllib.parse.urlencode({"工号": "60000011"}), 头=内)
        ck("林岚那边看不到这个人的", c == 200 and not any(x["id"] in (s1.get("id"), s3.get("id")) for x in m2["items"]), (c, len(m2.get("items", []))))

        print("\n▸ ⑪ 首次处理截止:提交那一刻按工作日算好存下")
        with 库.connect() as cc:
            行2 = cc.execute(text("""select created_at, first_response_due_at, due_basis_code, verdict, problem_type, impact_type from opinions
                                      where project_id=:p and id=:i"""), {"p": 项目, "i": s1["id"]}).mappings().first()
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                        "services", "api", "app"))
        import workdays as WD
        import opinions_api as OPN
        import datetime as _dtm
        级2 = OPN.分级(行2["verdict"], 行2["problem_type"], 行2["impact_type"])
        应截, 应依 = OPN.截止(级2, 行2["created_at"])
        ck("存下的截止 = 按级别算的那个(差不过 1 秒),依据也存了、开头是级别",
           abs((行2["first_response_due_at"] - 应截).total_seconds()) < 1 and 行2["due_basis_code"] == 应依
           and 应依.startswith(级2 + " "), (dict(行2), 应截, 应依))
        # 分三级带时限(用户 11-13 拍第四十一条):紧急 4 工作小时 / 一般 2 个工作日(48 工作小时)/ 建议 7 个自然日
        ck("分级:影响业务办理 → 紧急;建议 / 新增能力 → 建议;其余 → 一般;紧急压过建议",
           OPN.分级("有问题", "答错", "影响业务办理") == "紧急" and OPN.分级("建议", "其他", None) == "建议"
           and OPN.分级("有问题", "新增能力", "仅影响本次") == "建议" and OPN.分级("有问题", "答错", "反复出现") == "一般"
           and OPN.分级("建议", "新增能力", "影响业务办理") == "紧急")
        周五 = _dtm.datetime(2026, 11, 13, 16, 0, tzinfo=WD.时区)
        紧, _ = OPN.截止("紧急", 周五)
        般, _ = OPN.截止("一般", 周五)
        建, 建依 = OPN.截止("建议", 周五)
        ck("时限:周五 16:00 提 → 紧急当天 20:00;一般跳过周末到下周二 16:00;建议 7 天后(自然日)",
           紧 == 周五 + _dtm.timedelta(hours=4) and 般 == _dtm.datetime(2026, 11, 17, 16, 0, tzinfo=WD.时区)
           and 建 == 周五 + _dtm.timedelta(days=7) and "自然日" in 建依, (紧, 般, 建))
        c, 详 = 打("GET", P + f"/opinions/{s1['id']}")
        ck("详情给出截止 / 依据 / 超没超(刚提的不超时)", c == 200 and 详.get("首次处理截止") and 详.get("截止依据")
           and 详.get("超时") is False, (c, 详))
        with 库.begin() as cc:
            cc.execute(text("update opinions set first_response_due_at = now() - interval '1 hour' where project_id=:p and id=:i"),
                       {"p": 项目, "i": s3["id"]})
        c, 详3 = 打("GET", P + f"/opinions/{s3['id']}")
        ck("**过了截止还没处理 → 超时**(只标红,状态还是待受理,不当成已解决)",
           详3.get("超时") is True and 详3.get("状态") == "待受理", 详3)
        ck("详情带级别", 详.get("级别") in ("紧急", "一般", "建议"), 详)
        from db import 事务 as _事务
        with _事务() as cc:
            n超 = OPN.超时条数(cc, 项目)
        ck("超时条数数得到这条(告警「意见超时条数」取这个数,超时提醒受理人走告警页待办)", n超 >= 1, n超)

        print("\n▸ ⑫ 受理流转(PRD §5.1)")
        动 = lambda oid, 动作, 说明=None, rev=None, 谁="U001": 打("POST", P + f"/opinions/{oid}/actions",
                                                          {"动作": 动作, **({"说明": 说明} if 说明 else {})},
                                                          ({"If-Match": str(rev)} if rev is not None else {}), 谁=谁)
        rev = 详["revision"]
        c, b = 动(s1["id"], "开始核实")
        ck("不带 If-Match → 409 IF_MATCH_REQUIRED", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 动(s1["id"], "开始核实", rev=rev + 99)
        ck("If-Match 对不上 → 409 REVISION_CONFLICT(两个人同时处理,后到的不许覆盖)", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        c, b = 动(s1["id"], "答复", "直接答复", rev=rev)
        ck("待受理直接「答复」→ 409 TRANSITION_NOT_ALLOWED(要先核实)", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        c, b = 动(s1["id"], "请求补充", rev=rev)
        ck("「请求补充」不写说明 → 422", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 动(s1["id"], "请求补充", "长" * 1001, rev=rev)
        ck("说明超过 1000 字 → 422 且带「怎么办」(11-04 前这里会崩成 500)", c == 422 and (b or {}).get("advice"), (c, b))
        无权 = "E2EOPV" + uuid.uuid4().hex[:4]
        打("POST", P + "/memberships", {"工号": 无权, "角色": "viewer"})
        c, b = 动(s1["id"], "开始核实", rev=rev, 谁=无权)
        ck("**查看者没有「受理意见」→ 403**", c == 403, (c, b))
        c, b = 动(s1["id"], "请求补充", "要说清是哪家门店、要导出哪几列", rev=rev)
        ck("「请求补充」→ 待补充,第一次处理时刻记下了", c == 200 and b.get("到") == "待补充" and b.get("首次处理时刻"), (c, b))
        c, m = 打("GET", P + "/opinions/mine?" + urllib.parse.urlencode({"工号": 标}), 头=内)
        那 = next((x for x in m.get("items", []) if x["id"] == s1["id"]), {})
        ck("提的人在「我的意见」里看到「需要你补充」和受理人那句话", 那.get("进度") == "需要你补充"
           and "哪家门店" in str(那.get("答复")), 那)
        # 挂一轮的那种补充:另造一条挂一轮的,推到待补充,提的人再提一次
        c, q = 提(体(标 + "-补", 工号=标))
        c, dq = 打("GET", P + f"/opinions/{q['id']}")
        动(q["id"], "请求补充", "期望结果写具体一点", rev=dq["revision"])
        c, q2 = 提(体(标 + "-补", 工号=标, 期望="应该是 21 个工作日"))
        c, dq2 = 打("GET", P + f"/opinions/{q['id']}")
        ck("**待补充的那条,提的人再提一次 → 回到核实中**,时间线记「提的人补充」",
           c == 200 and dq2.get("状态") == "核实中" and q2.get("状态") == "核实中"
           and [e["动作"] for e in dq2.get("时间线", [])] == ["请求补充", "提的人补充"], (q2, dq2.get("时间线")))
        c, dq3 = 打("GET", P + f"/opinions/{q['id']}")
        c, b = 动(q["id"], "答复", "工期按 21 个工作日算,已经告诉门店", rev=dq3["revision"])
        ck("核实中 → 答复 → 已答复", c == 200 and b.get("到") == "已答复", (c, b))
        c, dq4 = 打("GET", P + f"/opinions/{q['id']}")
        c, b = 动(q["id"], "重开", rev=dq4["revision"])
        ck("「重开」不写原因 → 422", c == 422, (c, b))
        c, b = 动(q["id"], "重开", "门店说还是不对", rev=dq4["revision"])
        ck("已答复 → 重开 → 核实中", c == 200 and b.get("到") == "核实中", (c, b))
        c, dq5 = 打("GET", P + f"/opinions/{q['id']}")
        c, b = 动(q["id"], "关联问题", rev=dq5["revision"])
        # 11-12 问题单做出来之后「关联问题」开了;关联 / 重新归并的完整流程在 test_issues_flow
        ck("「关联问题」不指定问题单 → 422,定位到「问题单」", c == 422 and "问题单" in 字段(b), (c, b))
        ck("详情里「能做的动作」照流转表给(核实中:答复 / 不采纳 / 请求补充 / 关联问题)",
           {x["动作"] for x in dq5.get("能做的动作", [])} == {"答复", "不采纳", "请求补充", "关联问题"}, dq5.get("能做的动作"))
        ck("时间线一步不少、老的在前", [e["动作"] for e in dq5.get("时间线", [])] == ["请求补充", "提的人补充", "答复", "重开"],
           dq5.get("时间线"))
        with 库.connect() as cc:
            事 = cc.execute(text("select count(*) from opinion_events where project_id=:p and opinion_id=:i"),
                           {"p": 项目, "i": q["id"]}).scalar()
        ck("库里时间线正好 4 行(被拒的那几次一行都没写)", 事 == 4, 事)
        ck("库这一层:不采纳不写说明 → 库拒", _库拒事件(库, text, 项目, q["id"], "不采纳"))

        print("\n▸ ⑬ 演示项目留一条样例(If-Match 可达性检查要从列表里拿一条;正式项目不留)")
        样 = {"来源": "问答", "聊天站trace": "e2e-样例-可达性", "评价": "有问题", "问题类型": "其他",
              "说明": "端到端测试留的样例,供 If-Match 可达性检查用", "提问人": {"工号": "E2E-SAMPLE", "姓名": "e2e"}}
        c, b = 打("POST", "/api/v1/projects/project_demo_a/opinions", 样, 内)
        ck("演示项目里有一条样例意见(重复跑不会多出来)", c == 201, (c, b))

        print("\n▸ ⑭ 期望结果 → 待复核样本(总部运营提)")
        提人, 提人号, 没绑 = "E2EOPP" + uuid.uuid4().hex[:4], "E2EP" + uuid.uuid4().hex[:6], "E2EOPN" + uuid.uuid4().hex[:4]
        打("POST", P + "/memberships", {"工号": 提人, "角色": "annotator"})
        打("POST", P + "/memberships", {"工号": 没绑, "角色": "annotator"})
        c, b = 打("PUT", P + f"/staff-bindings/{提人}", {"澜绣工号": 提人号, "备注": "e2e 提样本"})
        ck("给提样本的人绑上澜绣工号", c in (200, 201), (c, b))
        提样 = lambda oid, 体样, rev, 谁=提人: 打("POST", P + f"/opinions/{oid}/promote", 体样,
                                              ({"If-Match": str(rev)} if rev is not None else {}), 谁=谁)
        c, dq = 打("GET", P + f"/opinions/{q['id']}")
        ck("核实中的意见:详情说「能提样本」,还没有样本", dq.get("能提样本") is True and dq.get("样本") is None, dq)
        样体 = {"题面": "汉服定制工期多少个工作日?", "期望答案": "21 个工作日", "说明": "e2e"}
        c, b = 提样(q["id"], 样体, None)
        ck("不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 提样(q["id"], {"题面": "x"}, dq["revision"])
        ck("没写期望答案 → 422(提的人写的期望结果只是候选,标准答案要总部运营写)", c == 422 and "期望答案" in 字段(b), (c, b))
        c, b = 提样(q["id"], 样体, dq["revision"], 谁=没绑)
        ck("**提的人没绑澜绣工号 → 409 NOT_BOUND**(比不出复核的是不是同一个人)", c == 409 and 码(b) == "NOT_BOUND", (c, b))
        c, sp = 提样(q["id"], 样体, dq["revision"])
        ck("提成待复核样本 → 201", c == 201 and sp.get("复核状态") == "待复核", (c, sp))
        with 库.connect() as cc:
            行s = cc.execute(text("""select s.source, s.review_status, s.split, s.group_id, d.name, s.content
                                       from samples s join datasets d on d.project_id=s.project_id and d.id=s.dataset_id
                                      where s.project_id=:p and s.id=:i"""), {"p": 项目, "i": sp.get("样本")}).mappings().first()
        ck("样本进了「意见回流」数据集:来源意见回流、待复核、验证集、按会话分组、记着提样本的人",
           行s and 行s["source"] == "意见回流" and 行s["review_status"] == "待复核" and 行s["split"] == "验证"
           and 行s["group_id"] == f"会话:s-{标}-补" and 行s["name"] == "意见回流"
           and (行s["content"] or {}).get("提样本的人", {}).get("工号") == 提人号, dict(行s or {}))
        c, dq2 = 打("GET", P + f"/opinions/{q['id']}")
        c, b = 提样(q["id"], 样体, dq2["revision"])
        ck("同一条再提 → 409 ALREADY_PROMOTED(被退回之后才能重提)", c == 409 and 码(b) == "ALREADY_PROMOTED", (c, b))
        ck("详情里样本状态是待复核、不能再提", (dq2.get("样本") or {}).get("复核状态") == "待复核" and dq2.get("能提样本") is False, dq2)

        print("\n▸ ⑮ 店长复核(聊天站转来,内部通道)")
        待 = lambda 号, 角色, 店: 打("GET", P + "/opinion-samples/pending?" + urllib.parse.urlencode(
            {"工号": 号, "角色": 角色, "门店": 店}), 头=内)
        c, b = 打("GET", P + "/opinion-samples/pending?" + urllib.parse.urlencode({"工号": "x", "角色": "店长"}))
        ck("不带内部凭证 → 403", c == 403, (c, b))
        有它 = lambda r: any(x["样本"] == sp.get("样本") for x in (r or {}).get("items", []))
        c, w = 待("E2ESM1", "店长", "杭州店")
        ck("**提问人所在门店(杭州店)的店长看得到**", c == 200 and 有它(w), (c, w))
        ck("待我复核如实给全项目待复核条数、有没有截断", isinstance(w.get("全项目待复核"), int) and w.get("截断了") is False, w)
        ck("别家门店的店长看不到", not 有它(待("E2ESM2", "店长", "苏州店")[1]))
        ck("门店顾问看不到(只有店长复核)", not 有它(待("E2ESM3", "门店顾问", "杭州店")[1]))
        ck("**提样本的人自己(哪怕是店长)看不到**", not 有它(待(提人号, "店长", "杭州店")[1]))
        ck("**提意见的人自己看不到**", not 有它(待(标, "店长", "杭州店")[1]))
        审 = lambda 决定, 理由=None, rev=None, 人=None: 打("POST", P + f"/opinion-samples/{sp.get('样本')}/review",
            {"决定": 决定, "理由": 理由, "revision": rev if rev is not None else next(
                (x["revision"] for x in w.get("items", []) if x["样本"] == sp.get("样本")), None),
             "复核人": 人 or {"工号": "E2ESM1", "姓名": "e2e 店长", "角色": "店长", "门店": "杭州店"}}, 内)
        c, b = 审("退回")
        ck("退回不写理由 → 422", c == 422 and "理由" in 字段(b), (c, b))
        c, b = 审("通过", 人={"工号": "E2ESM3", "角色": "门店顾问", "门店": "杭州店"})
        ck("**门店顾问直接打这个口 → 403 NOT_REVIEWER**(页面藏起来不算拦住)", c == 403 and 码(b) == "NOT_REVIEWER", (c, b))
        c, b = 审("通过", 人={"工号": 提人号, "角色": "店长", "门店": "杭州店"})
        ck("**提样本的人自己复核 → 403**(两人点头要是两个人)", c == 403 and 码(b) == "NOT_REVIEWER", (c, b))
        c, b = 审("通过", rev=999)
        ck("revision 对不上 → 409", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        c, b = 审("通过")
        ck("**杭州店店长通过 → 已通过**", c == 200 and b.get("复核状态") == "已通过", (c, b))
        c, b = 审("退回", "改主意")
        ck("已复核过的再复核 → 409 ALREADY_REVIEWED", c == 409 and 码(b) == "ALREADY_REVIEWED", (c, b))
        c, dq3 = 打("GET", P + f"/opinions/{q['id']}")
        末 = (dq3.get("时间线") or [{}])[-2:]
        ck("时间线记了「提为样本」和「店长通过」,复核人记成聊天站那个工号",
           [e["动作"] for e in 末] == ["提为样本", "店长通过"] and 末[-1].get("谁") == "聊天站:E2ESM1", 末)
        # 退回之后能重提
        c, r1 = 提(体(标 + "-样2", 工号=标))
        c, dr = 打("GET", P + f"/opinions/{r1['id']}")
        打("POST", P + f"/opinions/{r1['id']}/actions", {"动作": "开始核实"}, {"If-Match": str(dr["revision"])})
        c, dr = 打("GET", P + f"/opinions/{r1['id']}")
        c, sp2 = 提样(r1["id"], 样体, dr["revision"])
        c, w2 = 待("E2ESM1", "店长", "杭州店")
        rev2 = next((x["revision"] for x in w2.get("items", []) if x["样本"] == sp2.get("样本")), None)
        c, b = 打("POST", P + f"/opinion-samples/{sp2.get('样本')}/review",
                 {"决定": "退回", "理由": "期望答案没说加急的情况", "revision": rev2,
                  "复核人": {"工号": "E2ESM1", "角色": "店长", "门店": "杭州店"}}, 内)
        ck("店长退回 → 已退回", c == 200 and b.get("复核状态") == "已退回", (c, b))
        c, dr = 打("GET", P + f"/opinions/{r1['id']}")
        c, sp3 = 提样(r1["id"], {**样体, "期望答案": "21 个工作日;加急另算"}, dr["revision"])
        ck("**退回之后能重提**(新的一条待复核样本)", c == 201 and sp3.get("样本") != sp2.get("样本"), (c, sp3))
        打("DELETE", P + f"/staff-bindings/{提人}")

        print("\n▸ ⑯ 跨项目:拿正式项目的编号去演示项目里取(读取隔离靠每句查询带项目条件 —— 这里真攻击一次)")
        PA = "/api/v1/projects/project_demo_a"
        c, b = 打("GET", PA + f"/opinions/{q['id']}")
        ck("演示项目里取正式项目的意见详情 → 404(不是 200 读到别家的)", c == 404, (c, b))
        c, b = 打("POST", PA + f"/opinions/{q['id']}/actions", {"动作": "答复", "说明": "x"}, {"If-Match": "1"})
        ck("演示项目里受理正式项目的意见 → 404", c == 404, (c, b))
        c, b = 打("POST", PA + f"/opinions/{q['id']}/promote", 样体, {"If-Match": "1"})
        ck("演示项目里把正式项目的意见提成样本 → 404", c == 404, (c, b))
        c, l = 打("GET", PA + "/opinions?limit=200")
        ck("演示项目的清单里没有正式项目的意见", c == 200 and not any(x["id"] in (q["id"], a["id"]) for x in l.get("items", [])), (c, l))
        c, m = 打("GET", PA + "/opinions/mine?" + urllib.parse.urlencode({"工号": 标}), 头=内)
        ck("演示项目的「我的意见」里没有这个人在正式项目提的", c == 200 and not m.get("items"), (c, m))
        c, w = 打("GET", PA + "/opinion-samples/pending?" + urllib.parse.urlencode({"工号": "E2ESM1", "角色": "店长", "门店": "杭州店"}), 头=内)
        ck("演示项目的「待我复核」里没有正式项目的样本", c == 200 and not any(x["样本"] in (sp.get("样本"), sp3.get("样本"))
                                                           for x in w.get("items", [])), (c, w))
        c, b = 打("POST", PA + f"/opinion-samples/{sp3.get('样本')}/review",
                 {"决定": "通过", "revision": 1, "复核人": {"工号": "E2ESM1", "角色": "店长", "门店": "杭州店"}}, 内)
        ck("演示项目里复核正式项目的样本 → 404", c == 404, (c, b))
    finally:
        with 库.begin() as cc:
            样们 = [r[0] for r in cc.execute(text("""select promoted_sample_id from opinions where project_id=:p
                        and promoted_sample_id is not null and (chat_trace_ref like :t or asker_staff_code=:s)"""),
                        {"p": 项目, "t": 标 + "%", "s": 标})]
            样们 += [r[0] for r in cc.execute(text("""select id from samples where project_id=:p and source='意见回流'
                        and content->>'来自意见' in (select id from opinions where project_id=:p
                        and (chat_trace_ref like :t or asker_staff_code=:s))"""), {"p": 项目, "t": 标 + "%", "s": 标})]
            cc.execute(text("delete from opinion_events where project_id=:p and opinion_id in "
                            "(select id from opinions where project_id=:p and (chat_trace_ref like :t or asker_staff_code=:s))"),
                       {"p": 项目, "t": 标 + "%", "s": 标})
            cc.execute(text("delete from opinions where project_id=:p and (chat_trace_ref like :t or asker_staff_code=:s)"),
                       {"p": 项目, "t": 标 + "%", "s": 标})
            if 样们:
                cc.execute(text("delete from samples where project_id=:p and id = any(:ids)"), {"p": 项目, "ids": list(set(样们))})
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
