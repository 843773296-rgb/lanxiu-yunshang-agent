#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编辑预约 + 定向运营的检查(11-14,台账第四十七、四十八条:「本期未实现」按钮第三组)。

在库副本上真调 `server.edit_appointment` 和 `targeted_ops.发起`(它逐个调 `tasks.assign_task`)。

  ① 编辑预约:本店的人能改;别店的人、已完成的预约、补录到过去(顾问)、换成别店的顾问都被拒;
     日志只记真改了的字段
  ② 定向运营:只总部;一次最多 200 人;每位客户的任务派给**他自己的归属导购**;
     同一类还没办完的再发一遍全部跳过(不连派两条),跳过的逐个说清
  ③ 入口交的是会话登录人;页面上这几处不再是「本期未实现」/「未做」
"""
from contextlib import closing
import os, re, sys, json, sqlite3, tempfile, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []

咬合 = [
    ('把 edit_appointment 的「只能改本店的预约」去掉', '① 别店的人改不了'),
    ('把定向运营的「同类没办完就跳过」去掉', '② 再发一遍:全部跳过(不连派两条)'),
]

def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    tmp = tempfile.mkdtemp()
    副本 = os.path.join(tmp, "lanxiu.db")
    with closing(sqlite3.connect(os.path.join(HERE, "lanxiu.db"))) as 真, closing(sqlite3.connect(副本)) as 副:
        真.backup(副)
    import server, oplog, tasks, targeted_ops
    server.DB = oplog.DB = tasks.DB = targeted_ops.DB = 副本
    assert all(m.DB == 副本 for m in (server, oplog, tasks, targeted_ops)), "库没切到副本"
    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as _c:
            return [tuple(r) for r in _c.execute(sql, a).fetchall()]
    def 人(sql, *a):
        r = q(sql, *a)
        return dict(no=r[0][0], name=r[0][1], role=r[0][2], shop=r[0][3]) if r else None

    print("\n① 编辑预约")
    约 = q("SELECT id, shop_code FROM appointment WHERE status='已预约' AND shop_code IS NOT NULL ORDER BY id LIMIT 1")
    完 = q("SELECT id, shop_code FROM appointment WHERE status='已完成' AND shop_code IS NOT NULL LIMIT 1")
    ck("样本:一条已预约、一条已完成", bool(约 and 完), 2)
    if 约 and 完:
        aid, 码 = 约[0]
        本店顾问 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop_code=? ORDER BY no LIMIT 1", 码)
        别店顾问 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop_code<>? ORDER BY no LIMIT 1", 码)
        另一本店顾问 = q("SELECT no FROM staff WHERE role='顾问' AND status='启用' AND shop_code=? ORDER BY no DESC LIMIT 1", 码)
        now = server._wnow()
        后天 = (now + dt.timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0)
        st, en = 后天.strftime("%Y-%m-%d %H:%M"), (后天 + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        r = server.edit_appointment(dict(id=aid, start=st, end=en), 本店顾问)
        ck("① 本店顾问改到三天后:成了,时间真改了", r.get("ok") and q("SELECT start_ts,end_ts FROM appointment WHERE id=?", aid) == [(st, en)],
           1, json.dumps(r, ensure_ascii=False)[:160])
        r = server.edit_appointment(dict(id=aid, start=st, end=en), 别店顾问)
        ck("① 别店的人改不了", r.get("code") == "OTHER_SHOP", 1, r.get("code"))
        r = server.edit_appointment(dict(id=完[0][0], start=st, end=en), 本店顾问 if 完[0][1] == 码 else 人(
            "SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' LIMIT 1"))
        ck("① 已完成的预约不能改", r.get("code") == "WRONG_STATE", 1, r.get("code"))
        昨 = now - dt.timedelta(days=1)
        r = server.edit_appointment(dict(id=aid, start=昨.strftime("%Y-%m-%d %H:%M"),
                                         end=(昨 + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")), 本店顾问)
        ck("① 顾问不能把预约改到过去(补录只有店长及以上,和新建同一条规则)", r.get("code") == "NO_BACKFILL", 1, r.get("code"))
        r = server.edit_appointment(dict(id=aid, advisor=别店顾问["no"]), 本店顾问)
        ck("① 换成别店的顾问被拒", r.get("code") == "BAD_ADVISOR", 1, r.get("code"))
        if 另一本店顾问:
            r = server.edit_appointment(dict(id=aid, advisor=另一本店顾问[0][0]), 本店顾问)
            最后 = q("SELECT changes FROM edit_log WHERE obj='预约' AND target=? ORDER BY id DESC LIMIT 1", aid)
            字段 = [x["字段"] for x in json.loads(最后[0][0])] if 最后 else []
            ck("① 只换顾问 → 日志只记「顾问」", r.get("ok") and 字段 in (["顾问"], ["(无)"]), 1, json.dumps(字段, ensure_ascii=False))

    print("\n② 定向运营")
    总部 = 人("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' ORDER BY no LIMIT 1")
    店长 = 人("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' ORDER BY no LIMIT 1")
    客户们 = [r[0] for r in q("SELECT c.id FROM customer c JOIN staff s ON s.no=c.advisor_no WHERE s.role='顾问' AND s.status='启用' "
                              "AND NOT EXISTS(SELECT 1 FROM schedule x WHERE x.customer_id=c.id AND x.type='电话回电' AND x.status='有效') "
                              "ORDER BY c.id LIMIT 3")]
    ck("样本:三位有在职归属导购、没有未办完回电任务的客户", len(客户们) == 3, len(客户们))
    截止 = (server._wnow() + dt.timedelta(days=7)).strftime("%Y-%m-%dT18:00")
    包 = lambda ids: dict(ids=ids, type="电话回电", note="秋冬上新邀约试穿", end=截止, tier="活跃")
    任务前 = q("SELECT COUNT(*) FROM schedule")[0][0]
    r = targeted_ops.发起(包(客户们), 店长)
    ck("② 店长发起被拒,一条任务没建", r.get("code") == "WRONG_ROLE" and q("SELECT COUNT(*) FROM schedule")[0][0] == 任务前, 1, r.get("code"))
    r = targeted_ops.发起(包([f"X{i}" for i in range(201)]), 总部)
    ck("② 一次超过 200 人被拒", r.get("code") == "TOO_MANY", 1, r.get("code"))
    r = targeted_ops.发起(dict(包(客户们), note="短"), 总部)
    ck("② 运营目的少于 4 个字被拒", r.get("code") == "NEED_NOTE", 1, r.get("code"))
    r = targeted_ops.发起(包(客户们), 总部)
    派 = r.get("派了") or []
    对 = [q("SELECT s.assignee_no = c.advisor_no FROM schedule s JOIN customer c ON c.id=s.customer_id WHERE s.id=?", x["任务"])
         for x in 派]
    ck("② 总部发起:三位各派一条,派给的都是他自己的归属导购",
       len(派) == 3 and all(x == [(1,)] for x in 对), len(派), json.dumps(r.get("跳过"), ensure_ascii=False)[:200])
    r = targeted_ops.发起(包(客户们), 总部)
    ck("② 再发一遍:全部跳过(不连派两条)", not r.get("派了") and len(r.get("跳过") or []) == 3
       and all("没办完" in x["为什么"] for x in r["跳过"]), 3, json.dumps(r.get("跳过"), ensure_ascii=False)[:200])

    print("\n③ 入口 / 页面")
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    ck("③ /api/appt-edit 交会话登录人", bool(re.search(r'if p=="/api/appt-edit":\s*\n\s*return self\._send\(edit_appointment\(body, 登录人\)\)', src)), 1)
    ck("③ /api/targeted-ops 交会话登录人", bool(re.search(r'_to\.发起\(body, 登录人\)', src)), 1)
    页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    残 = [x for x in ("编辑预约 · 本期未实现", "定向运营 · 本期未实现", "定向运营(未做)", "添加生命周期 · 本期未实现", "设为默认值(未做)")
         if x in 页]
    ck("③ 页面上第三组不再有「本期未实现 / 未做」", not 残, 5, f"还剩 {残}")
    ck("③ 页面真发 /api/appt-edit 和 /api/targeted-ops", '"/api/appt-edit"' in 页 and '"/api/targeted-ops"' in 页, 2)

    print()
    if FAIL:
        print(f"❌ 编辑预约 / 定向运营 {len(FAIL)} 条不过:" + "、".join(FAIL)); sys.exit(1)
    print("✅ 编辑预约 / 定向运营全过")


if __name__ == "__main__":
    main()
