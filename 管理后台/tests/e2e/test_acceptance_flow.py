#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上线验收(2026-11-12,执行手册 W41;业务拍板 11-12 第一条「做完 = 试点两周 + 十条验收签字 + 费用上限」)。
打真起着的管理后台,不调模型 —— 进 test-e2e-ci。

**不碰澜绣项目里真的那十行**:写操作全在一个自己建的临时项目里(id 以 e2e-acc- 开头,acceptance_flow.该种吗 认它),跑完删干净。
澜绣项目只读(GET 会在第一次打开时种上十条 —— 那正是上线后的行为)。

  ① 口径(直接调 acceptance_flow 的真函数):十条全签 / 试点满两周 / 月费用三项的边界 —— 0 行是「拿不到」不是通过;
     起算日没设是「未开始」;第 13 天进行中、第 14 天通过;150 通过、150.01 不通过;有一行算不出 / 有外币 → 拿不到
  ② 十条场景**和 PRD 13.4 原文那张表逐字一致**(读 PRD 文件现解析,不在这里抄第二份);再打开一次不重复种
  ③ 临时项目第一次打开:十行、试点「未开始」且起算日是空(**不是今天**)、费用「拿不到」(这个项目一笔账都没有)
  ④ 改记录:If-Match 不带 / 对不上 → 409;结论不在三个里 → 422;下结论没写验的人 / 日期 → 422;日期晚于今天 → 422;
     查看者 / approver(没有「受理意见」)→ 403;标注员改成功 → 时间线一行带前后值 + 一行审计
  ⑤ 签字:标注员 / 没专项授权的管理员 → 403(**填的人和配系统的人默认都签不了**);approver 签上 → 签字人是登录的那个人;
     再签 → 409;没下结论的签 → 422;改备注签字还在,**改结论签字作废**(时间线「签字作废」带原签字人)
  ⑥ 十条全签 → ①变「通过」;但做完仍是 false(试点没开始)
  ⑦ 起算日:标注员 → 403;不写说明 → 422;将来的日子 → 422;3 天前 → 进行中还差 11 天;14 天前 → 通过;清掉 → 回到未开始;
     时间线「设试点起算日」不挂场景、带说明;演示项目设起算日 → 404
  ①b 澜绣项目读门店用量账(11-13 拍):通过 / 不通过 / 金额未知 → 拿不到 / 0 笔 → 拿不到 / 聊天站取不到 → 拿不到;
     接线:澜绣项目不碰 usage_ledger、取不到不退回
  ⑧ 费用走真接口:临时项目里造用量账 —— 12.5 美元 → 通过且做完 = true;再加一行算不出 → 拿不到、做完 = false;
     mock 的一大笔不算;另起一套 SQL 对账「本月费用」(不是被测那句)
  ⑨ 库这一层也拦:签了字的结论不是通过 / 签字人没签字时间 / 下了结论没验的人 / 设起算日没说明 / 签字事件不挂场景 —— CHECK 当场拒
  ⑩ 跨项目:从澜绣项目的路径改临时项目的行 → 404;演示项目没有场景(空列表,说明写着只在澜绣项目)
"""
import datetime as _dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 管理后台/
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
import acceptance_flow as F  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
PRD = os.path.join(os.path.dirname(_根), "澜绣云裳agent-产品需求文档.md")
测项 = F.测试项目前缀 + uuid.uuid4().hex[:8]
PT = f"/api/v1/projects/{测项}"
PL = "/api/v1/projects/project_lanxiu"
PA = "/api/v1/projects/project_demo_a"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
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


def PRD十条():
    """读 PRD 原文第 13.4 节那张表 → [(编号, 场景, 通过标准)]。读不到 / 解析出 0 行 → 返回空(下面会红,不当成通过)。"""
    try:
        文 = open(PRD, encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(r"^##\s*13\.4[^\n]*\n(.*?)(?=^##\s)", 文, re.M | re.S)
    if not m:
        return []
    行们 = []
    for 行 in m.group(1).splitlines():
        格 = [x.strip() for x in 行.strip().strip("|").split("|")] if 行.strip().startswith("|") else []
        if len(格) == 3 and re.fullmatch(r"S\d+", 格[0]):
            行们.append(tuple(格))
    return 行们


def 口径():
    print("▸ ① 口径(直接调 acceptance_flow 的真函数)")
    今 = _dt.date(2026, 11, 12)
    ck("十条:一行都没有 → 拿不到(空集合上「全签了」不算)", F.判_十条([])["状态"] == "拿不到")
    全 = [{"编号": c, "结论": "通过", "签字人": "U006"} for c, _, _ in F.十条场景]
    ck("十条:十条都通过且签了 → 通过", F.判_十条(全)["状态"] == "通过")
    ck("十条:少一行 → 拿不到", F.判_十条(全[:-1])["状态"] == "拿不到")
    差一 = 全[:-1] + [{"编号": "S10", "结论": "通过", "签字人": None}]
    ck("十条:九签一未签 → 进行中,已签 9", (F.判_十条(差一)["状态"], F.判_十条(差一)["已签通过"]) == ("进行中", 9))
    坏一 = 全[:-1] + [{"编号": "S10", "结论": "不通过", "签字人": None}]
    ck("十条:有一条不通过 → 不通过", F.判_十条(坏一)["状态"] == "不通过")
    ck("试点:起算日没设 → 未开始(不当成今天)", F.判_试点(None, 今)["状态"] == "未开始" and F.判_试点(None, 今)["起算日"] is None)
    ck("试点:第 13 天 → 进行中还差 1 天", (F.判_试点(今 - _dt.timedelta(days=13), 今)["状态"],
                                         F.判_试点(今 - _dt.timedelta(days=13), 今)["还差天数"]) == ("进行中", 1))
    ck("试点:第 14 天 → 通过", F.判_试点(今 - _dt.timedelta(days=14), 今)["状态"] == "通过")
    ck("试点:起算日在将来 → 未开始", F.判_试点(今 + _dt.timedelta(days=1), 今)["状态"] == "未开始")
    基 = {"月份": "2026-11", "行数": 3, "已知金额": 150, "金额未知的行数": 0, "币种们": ["USD"]}
    ck("费用:读不到汇总 → 拿不到(未接入)", F.判_费用(None)["状态"] == "拿不到")
    ck("费用:这个月 0 行 → 拿不到(没数据不是 0 元)", F.判_费用(dict(基, 行数=0, 已知金额=0))["状态"] == "拿不到")
    ck("费用:正好 150 → 通过", F.判_费用(基)["状态"] == "通过")
    ck("费用:150.01 → 不通过", F.判_费用(dict(基, 已知金额=150.01))["状态"] == "不通过")
    ck("费用:有一行算不出参考价 → 拿不到(已知的不是全部)", F.判_费用(dict(基, 已知金额=1, 金额未知的行数=1))["状态"] == "拿不到")
    ck("费用:有一笔不是美元 → 拿不到", F.判_费用(dict(基, 已知金额=1, 币种们=["USD", "CNY"]))["状态"] == "拿不到")
    三 = [F.判_十条(全), F.判_试点(今 - _dt.timedelta(days=14), 今), F.判_费用(dict(基, 已知金额=1))]
    ck("做完:三项都通过 → true", F.判_做完(*三)["做完了吗"] is True)
    ck("做完:试点未开始 → false", F.判_做完(三[0], F.判_试点(None, 今), 三[2])["做完了吗"] is False)
    # ①b 澜绣项目读门店用量账(用户 11-13 拍「只算门店真实使用」):聊天站 /internal/store-usage 的返回 → 汇总 → 判
    import acceptance_api as A
    店 = lambda **k: F.判_费用(A.门店费用汇总(dict({"月份": "2031-03", "笔数": 4, "合计": 12.5, "币种": "USD", "账": "本月 4 笔"}, **k)))
    ck("门店账:12.5 美元 4 笔 → 通过", 店()["状态"] == "通过")
    ck("门店账:150.01 → 不通过", 店(合计=150.01)["状态"] == "不通过")
    ck("门店账:合计拿不到(有一笔金额未知)→ 拿不到,说明带账上那句(不当 0)",
       店(合计=None, 账="本月 4 笔里 1 笔金额未知")["状态"] == "拿不到" and "金额未知" in 店(合计=None, 账="本月 4 笔里 1 笔金额未知")["说明"])
    ck("门店账:一笔都没有 → 拿不到", 店(笔数=0, 合计=0.0)["状态"] == "拿不到")
    ck("门店账:聊天站连不上 / 拒了 → 拿不到", F.判_费用(A.门店费用汇总({"error": "x"}))["状态"] == "拿不到"
       and F.判_费用(A.门店费用汇总(None))["状态"] == "拿不到")
    # 接线:澜绣项目走门店账、**不碰库**(c=None 传进去,碰了就崩);聊天站拒了也不退回去读 usage_ledger
    try:
        走 = A.本月费用(None, "project_lanxiu", 今, {"月份": "2031-03", "笔数": 2, "合计": 3.0, "币种": "USD", "账": ""})
        退 = A.本月费用(None, "project_lanxiu", 今, {"error": "聊天站回 HTTP 403"})
        ck("接线:澜绣项目「本月费用」读门店账、不读 usage_ledger;取不到就是拿不到", 走 and 走.get("来源") == "门店用量账" and 退 is None, (走, 退))
    except Exception as e:  # noqa: BLE001
        ck("接线:澜绣项目「本月费用」读门店账、不读 usage_ledger;取不到就是拿不到", False, f"碰了库或崩了:{type(e).__name__}: {e}")


def main():
    口径()
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    今天 = _dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    with 库.connect() as cc:
        org = cc.execute(text("select organization_id from projects where id='project_demo_a'")).scalar()
    try:
        with 库.begin() as cc:
            cc.execute(text("""insert into projects (id, organization_id, name, owner, status, timezone, kind_code, created_at, created_by,
                                   updated_at, revision)
                               values (:i, :o, 'e2e 上线验收', 'e2e', 'active', 'Asia/Shanghai', '测试', now(), 'e2e', now(), 1)"""),
                       {"i": 测项, "o": org})
            for 谁, 角色, 授 in (("U001", "admin", []), ("U003", "viewer", []), ("U004", "annotator", []),
                              ("U006", "approver", []), ("U007", "admin", ["审批工具动作"])):
                cc.execute(text("""insert into memberships (id, organization_id, project_id, user_id, role, special_grants, status,
                                       created_at, created_by, updated_at, revision)
                                   values (:i, :o, :p, :u, :r, cast(:g as jsonb), 'active', now(), 'e2e', now(), 1)"""),
                           {"i": f"mb_{测项}_{谁}", "o": org, "p": 测项, "u": 谁, "r": 角色, "g": json.dumps(授)})

        print("\n▸ ② 十条场景和 PRD 13.4 原文一致")
        原文 = PRD十条()
        ck(f"PRD 13.4 那张表读出了 10 行(读出 {len(原文)} 行)", len(原文) == 10, 原文)
        c, d = 打("GET", PL + "/acceptance")
        ck("澜绣项目打开上线验收 → 200,十行", c == 200 and d.get("total") == 10 and len(d.get("items", [])) == 10, (c, d))
        接口的 = [(x["编号"], x["场景"], x["通过标准"]) for x in (d or {}).get("items", [])]
        ck("**编号 / 场景 / 通过标准 / 顺序和 PRD 原文逐字一致**", 接口的 == 原文, [x for x in 接口的 if x not in 原文][:3])
        c, d2 = 打("GET", PL + "/acceptance")
        ck("再打开一次不重复种(还是十行、id 不变)", c == 200 and [x["id"] for x in d2["items"]] == [x["id"] for x in d["items"]], d2.get("total"))
        ck("顶部判定恰好三项:十条全签 / 试点满两周 / 月费用未超上限",
           [x["项"] for x in d["做完判定"]["三项"]] == ["十条全签", "试点满两周", "月费用未超上限"], d["做完判定"])
        澜绣行 = d["items"][0]

        print("\n▸ ③ 临时项目第一次打开")
        c, d = 打("GET", PT + "/acceptance")
        ck("200,十行", c == 200 and d.get("total") == 10, (c, d))
        试点 = d["做完判定"]["三项"][1]
        ck("**试点「未开始」,起算日是空 —— 不是今天**", 试点["状态"] == "未开始" and 试点["起算日"] is None
           and d["试点"]["真数据导入日"] is None, 试点)
        费 = d["做完判定"]["三项"][2]
        ck("费用「拿不到」(这个项目一笔账都没有),已知金额是空不是 0", 费["状态"] == "拿不到" and 费["已知金额"] is None
           and d["本月费用"]["行数"] == 0, 费)
        ck("做完 = false", d["做完判定"]["做完了吗"] is False)
        行们 = {x["编号"]: x for x in d["items"]}
        s1 = 行们["S1"]

        def 现(编号):
            return {x["编号"]: x for x in 打("GET", PT + "/acceptance")[1]["items"]}[编号]

        print("\n▸ ④ 改记录")
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"备注": "x"}, 谁="U004")
        ck("不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"备注": "x"}, {"If-Match": "999"}, 谁="U004")
        ck("If-Match 对不上 → 409", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        rv = {"If-Match": str(s1["revision"])}
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"结论": "差不多"}, rv, 谁="U004")
        ck("结论不在三个里 → 422 定位到结论", c == 422 and "结论" in 字段(b), (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"结论": "通过"}, rv, 谁="U004")
        ck("下结论没写验的人 / 日期 → 422 定位到两个字段", c == 422 and {"验的人", "验的日期"} <= 字段(b), (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}",
                 {"结论": "通过", "验的人": "王店长", "验的日期": (今天 + _dt.timedelta(days=1)).isoformat()}, rv, 谁="U004")
        ck("验的日期晚于今天 → 422", c == 422 and "验的日期" in 字段(b), (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"备注": "x"}, rv, 谁="U003")
        ck("查看者改 → 403", c == 403, (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"备注": "x"}, rv, 谁="U006")
        ck("approver(没有「受理意见」)改记录 → 403 —— 签字的人不替人填", c == 403, (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"结论": "通过", "验的人": "王店长", "验的日期": 今天.isoformat(),
                                                         "证据链接": "https://example.invalid/s1"}, rv, 谁="U004")
        ck("标注员下结论 → 200,revision +1", c == 200 and b.get("revision") == s1["revision"] + 1 and not b.get("签字作废了吗"), (c, b))
        with 库.connect() as cc:
            线 = cc.execute(text("""select action_code, created_by, change_snapshot from acceptance_events
                                     where project_id=:p and acceptance_item_id=:i order by created_at, id"""),
                           {"p": 测项, "i": s1["id"]}).mappings().all()
            审 = cc.execute(text("select count(*) from audit_events where project_id=:p and action='acceptance.record' and actor='U004'"),
                           {"p": 测项}).scalar()
        ck("时间线一行「改记录」,谁 = U004,结论前后值 [待验, 通过]",
           len(线) == 1 and 线[0]["action_code"] == "改记录" and 线[0]["created_by"] == "U004"
           and (线[0]["change_snapshot"] or {}).get("结论") == ["待验", "通过"], [dict(x) for x in 线])
        ck("审计记录里一行 acceptance.record", 审 == 1, 审)

        print("\n▸ ⑤ 签字")
        s1 = 现("S1")
        rv = {"If-Match": str(s1["revision"])}
        c, b = 打("POST", PT + f"/acceptance/{s1['id']}/sign", {}, rv, 谁="U004")
        ck("标注员(填记录的人)签 → 403", c == 403, (c, b))
        c, b = 打("POST", PT + f"/acceptance/{s1['id']}/sign", {}, rv, 谁="U001")
        ck("**没专项授权的管理员签 → 403**(配系统的人默认签不了)", c == 403, (c, b))
        c, b = 打("POST", PT + f"/acceptance/{s1['id']}/sign", {}, 谁="U006")
        ck("approver 签不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 打("POST", PT + f"/acceptance/{s1['id']}/sign", {"签字人": "U999", "说明": "虚拟试点走过一遍"}, rv, 谁="U006")
        ck("approver 签上 → 200,签字人是登录的 U006(请求里塞的签字人不认)", c == 200 and b.get("签字人") == "U006", (c, b))
        s1 = 现("S1")
        ck("清单里 S1 签字人 U006、有签字时间、标「签于真实试点前」(起算日没设)",
           s1["签字人"] == "U006" and s1["签字时间"] and s1["签于真实试点前"] is True, s1)
        c, b = 打("POST", PT + f"/acceptance/{s1['id']}/sign", {}, {"If-Match": str(s1["revision"])}, 谁="U006")
        ck("再签 → 409 ALREADY_SIGNED", c == 409 and 码(b) == "ALREADY_SIGNED", (c, b))
        s2 = 现("S2")
        c, b = 打("POST", PT + f"/acceptance/{s2['id']}/sign", {}, {"If-Match": str(s2["revision"])}, 谁="U006")
        ck("没下结论(待验)的签 → 422", c == 422 and {"结论", "验的人", "验的日期"} <= 字段(b), (c, b))
        with 库.connect() as cc:
            审 = cc.execute(text("select count(*) from audit_events where project_id=:p and action='acceptance.sign' and actor='U006'"),
                           {"p": 测项}).scalar()
        ck("审计记录里一行 acceptance.sign", 审 == 1, 审)
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"备注": "店长当面看过"}, {"If-Match": str(s1["revision"])}, 谁="U004")
        ck("签过字后改备注 → 签字还在", c == 200 and b.get("签字作废了吗") is False and 现("S1")["签字人"] == "U006", (c, b))
        s1 = 现("S1")
        c, b = 打("PATCH", PT + f"/acceptance/{s1['id']}", {"结论": "不通过"}, {"If-Match": str(s1["revision"])}, 谁="U004")
        s1 = 现("S1")
        ck("**签过字后改结论 → 签字作废**(签字人、签字时间清空)", c == 200 and b.get("签字作废了吗") is True
           and s1["签字人"] is None and s1["签字时间"] is None, (c, b, s1))
        with 库.connect() as cc:
            废 = cc.execute(text("""select change_snapshot from acceptance_events where project_id=:p and acceptance_item_id=:i
                                     and action_code='签字作废'"""), {"p": 测项, "i": s1["id"]}).scalars().all()
        ck("时间线一行「签字作废」,带原签字人 U006", len(废) == 1 and (废[0] or {}).get("签字人") == "U006", 废)

        print("\n▸ ⑥ 十条全签")
        for 编号, _, _ in F.十条场景:
            x = 现(编号)
            c, b = 打("PATCH", PT + f"/acceptance/{x['id']}", {"结论": "通过", "验的人": "王店长", "验的日期": 今天.isoformat()},
                     {"If-Match": str(x["revision"])}, 谁="U004")
            if c not in (200, 422):     # 422 = 和现在一样(S1 以外的不会;S1 现在是不通过)
                ck(f"{编号} 下结论", False, (c, b))
            x = 现(编号)
            c, b = 打("POST", PT + f"/acceptance/{x['id']}/sign", {}, {"If-Match": str(x["revision"])},
                     谁="U007" if 编号 == "S10" else "U006")
            if c != 200:
                ck(f"{编号} 签字", False, (c, b))
        c, d = 打("GET", PT + "/acceptance")
        十 = d["做完判定"]["三项"][0]
        ck("十条全签 → ①通过、已签 10(S10 由带专项授权的管理员 U007 签)", 十["状态"] == "通过" and 十["已签通过"] == 10
           and 现("S10")["签字人"] == "U007", 十)
        ck("但做完仍是 false(试点没开始、费用拿不到)", d["做完判定"]["做完了吗"] is False, d["做完判定"])

        print("\n▸ ⑦ 真数据导入日")
        rv = {"If-Match": str(d["试点"]["revision"])}
        三天前 = (今天 - _dt.timedelta(days=3)).isoformat()
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": 三天前, "说明": "x"}, rv, 谁="U004")
        ck("标注员设起算日 → 403", c == 403, (c, b))
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": 三天前}, rv, 谁="U006")
        ck("不写说明 → 422", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": (今天 + _dt.timedelta(days=1)).isoformat(), "说明": "x"}, rv, 谁="U006")
        ck("将来的日子 → 422", c == 422 and "真数据导入日" in 字段(b), (c, b))
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": 三天前, "说明": "门店导入了真实客户档案"}, 谁="U006")
        ck("不带 If-Match → 409", c == 409, (c, b))
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": 三天前, "说明": "门店导入了真实客户档案"}, rv, 谁="U006")
        ck("approver 设 3 天前 → 200", c == 200 and b.get("真数据导入日") == 三天前, (c, b))
        c, d = 打("GET", PT + "/acceptance")
        试点 = d["做完判定"]["三项"][1]
        ck("试点:进行中、第 3 天、还差 11 天", (试点["状态"], 试点["已过天数"], 试点["还差天数"]) == ("进行中", 3, 11), 试点)
        ck("今天签的字不再标「签于真实试点前」(签在起算日之后)", 现("S2")["签于真实试点前"] is False, 现("S2"))
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": (今天 - _dt.timedelta(days=14)).isoformat(), "说明": "改正:其实两周前就导了"},
                 {"If-Match": str(d["试点"]["revision"])}, 谁="U006")
        c, d = 打("GET", PT + "/acceptance")
        ck("起算日改成 14 天前 → 试点通过", d["做完判定"]["三项"][1]["状态"] == "通过", d["做完判定"]["三项"][1])
        with 库.connect() as cc:
            设 = cc.execute(text("""select acceptance_item_id, note from acceptance_events where project_id=:p
                                     and action_code='设试点起算日' order by created_at"""), {"p": 测项}).mappings().all()
        ck("时间线两行「设试点起算日」,不挂场景、都带说明", len(设) == 2 and all(x["acceptance_item_id"] is None and x["note"] for x in 设),
           [dict(x) for x in 设])
        c, b = 打("PATCH", PA + "/acceptance-pilot", {"真数据导入日": 三天前, "说明": "x"}, {"If-Match": "1"}, 谁="U006")
        ck("演示项目设起算日 → 404(没有上线验收)", c == 404, (c, b))

        print("\n▸ ⑧ 费用走真接口")
        tid = f"tr_{测项}"
        with 库.begin() as cc:
            cc.execute(text("insert into traces (id, organization_id, project_id, created_at) values (:i, :o, :p, now())"),
                       {"i": tid, "o": org, "p": 测项})

            def 记账(k, 额, 知=True, 源="live", 币="USD"):
                cc.execute(text("""insert into usage_ledger (id, organization_id, project_id, created_at, event_key, trace_id, resource,
                                       quantity, unit, currency, amount, amount_known, source)
                                   values (:i, :o, :p, now(), :k, :t, 'generate', 100, 'token', :c, :a, :kn, :s)"""),
                           {"i": f"ul_{测项}_{k}", "o": org, "p": 测项, "k": f"{测项}:{k}", "t": tid, "c": 币, "a": 额, "kn": 知, "s": 源})
            记账("a", 12.5)
            记账("m", 999, 源="mock")
            记账("n", 0.5, 源=None)      # source 为空的真调用也要算(不能被 source <> 'mock' 漏掉)
        c, d = 打("GET", PT + "/acceptance")
        费 = d["做完判定"]["三项"][2]
        ck("12.5 + 0.5 美元(mock 那 999 不算、source 为空的算)→ 通过,已知 13.0", 费["状态"] == "通过" and abs((费["已知金额"] or 0) - 13.0) < 1e-6, 费)
        with 库.connect() as cc:
            月初 = _dt.datetime(今天.year, 今天.month, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
            对 = cc.execute(text("""select count(*), coalesce(sum(amount), 0) from usage_ledger
                                     where project_id=:p and coalesce(source, '') <> 'mock' and created_at >= :b"""),
                           {"p": 测项, "b": 月初}).first()
        ck("另一套 SQL 对账「本月费用」:行数和金额一致", (d["本月费用"]["行数"], round(d["本月费用"]["已知金额"], 4)) == (int(对[0]), round(float(对[1]), 4)),
           (d["本月费用"], tuple(对)))
        ck("**三项都通过 → 做完 = true**", d["做完判定"]["做完了吗"] is True, d["做完判定"])
        with 库.begin() as cc:
            记账("u", None, 知=False)
        c, d = 打("GET", PT + "/acceptance")
        ck("再加一行算不出参考价 → 费用拿不到、做完 = false", d["做完判定"]["三项"][2]["状态"] == "拿不到"
           and d["做完判定"]["做完了吗"] is False, d["做完判定"]["三项"][2])
        rv = {"If-Match": str(d["试点"]["revision"])}
        c, b = 打("PATCH", PT + "/acceptance-pilot", {"真数据导入日": None, "说明": "清掉:导错了库"}, rv, 谁="U006")
        c, d = 打("GET", PT + "/acceptance")
        ck("起算日清掉 → 回到未开始", c == 200 and d["做完判定"]["三项"][1]["状态"] == "未开始" and d["试点"]["真数据导入日"] is None,
           d["做完判定"]["三项"][1])

        print("\n▸ ⑨ 库这一层也拦")
        s3 = 现("S3")

        def 试(sql, 参):
            try:
                with 库.begin() as cc:
                    cc.execute(text(sql), 参)
                return "成"
            except Exception as e:
                # 判据要的是**哪一条约束**拒的(红的必须是点名那条),所以取约束名,不截报错原文
                名 = getattr(getattr(getattr(e, "orig", None), "diag", None), "constraint_name", None)
                return f"拒:{名 or str(e).splitlines()[0][:200]}"
        r = 试("update acceptance_items set verdict='不通过' where project_id=:p and id=:i", {"p": 测项, "i": s3["id"]})
        ck("签了字的行把结论改成不通过(不清签字)→ 拒", r.startswith("拒") and "signed_passed" in r, r)
        r = 试("update acceptance_items set signed_at=null where project_id=:p and id=:i", {"p": 测项, "i": s3["id"]})
        ck("有签字人没签字时间 → 拒", r.startswith("拒") and "signed_pair" in r, r)
        r = 试("update acceptance_items set signed_by=null, signed_at=null, tested_by=null where project_id=:p and id=:i",
              {"p": 测项, "i": s3["id"]})
        ck("下了结论却清掉验的人 → 拒", r.startswith("拒") and "tested" in r, r)
        r = 试("""insert into acceptance_events (id, organization_id, project_id, created_at, action_code)
                 values ('e2e-x1', :o, :p, now(), '设试点起算日')""", {"o": org, "p": 测项})
        ck("设试点起算日不写说明 → 拒", r.startswith("拒") and "events_note" in r, r)
        r = 试("""insert into acceptance_events (id, organization_id, project_id, created_at, action_code, note)
                 values ('e2e-x2', :o, :p, now(), '签字', 'x')""", {"o": org, "p": 测项})
        ck("签字事件不挂场景 → 拒", r.startswith("拒") and "events_item" in r, r)
        r = 试("update acceptance_items set note='库层正向对照' where project_id=:p and id=:i", {"p": 测项, "i": s3["id"]})
        ck("正向对照:合规的改动照常写得进(上面五条拒的是那几条 CHECK,不是这张表写不进)", r == "成", r)

        print("\n▸ ⑩ 跨项目")
        c, b = 打("PATCH", PL + f"/acceptance/{s3['id']}", {"备注": "x"}, {"If-Match": str(现("S3")["revision"])}, 谁="U001")
        ck("从澜绣项目的路径改临时项目的行 → 404", c == 404, (c, b))
        c, b = 打("PATCH", PT + f"/acceptance/{澜绣行['id']}", {"备注": "x"}, {"If-Match": str(澜绣行["revision"])}, 谁="U004")
        ck("从临时项目的路径改澜绣项目的行 → 404(澜绣那一行没被碰)", c == 404, (c, b))
        c, d = 打("GET", PA + "/acceptance", 谁="U002")
        ck("演示项目:没有场景,空列表 + 说明", c == 200 and d.get("total") == 0 and d.get("items") == [] and d.get("note"), (c, d))
    finally:
        with 库.begin() as cc:
            for 表 in ("acceptance_events", "acceptance_items", "acceptance_pilots", "usage_ledger", "traces", "audit_events", "memberships"):
                cc.execute(text(f"delete from {表} where project_id=:p"), {"p": 测项})
            cc.execute(text("delete from projects where id=:p"), {"p": 测项})
        with 库.connect() as cc:
            留 = cc.execute(text("select count(*) from projects where id like :x"), {"x": F.测试项目前缀 + "%"}).scalar()
        ck("跑完临时项目删干净了(e2e-acc-* 一个不剩)", 留 == 0, 留)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 上线验收:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
