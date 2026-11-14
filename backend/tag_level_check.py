#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户标签 / 会员等级 / 手动合并的检查(11-14,台账第四十九条)。在库副本上真调 tag_level_write。

  ① 新建标签只总部;同名被拒
  ② 打标签:本店的人给本店客户;别店被拒;停用的标签不能新打、已打着的不受影响;tag.n 跟着真实绑定走
     (建表那一步把造数写进去的人数按真实绑定重算 —— 原来没有绑定表,人数是造的)
  ③ 新增等级只总部;门槛要高过最高那一档;建出来是停用;启用时档位要单调;普通会员不能停用
  ④ 手动合并:不同账户(或不同名)发起不了 —— 不跨账户合并档案;同账户同名能建任务、状态「待核验」;重复发起被拒
  ⑤ 入口交会话登录人
"""
from contextlib import closing
import os, re, sys, json, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
FAIL = []

咬合 = [
    ('把打标签的「停用的标签不能新打」去掉', '② 停用的标签不能新打,已打着的不受影响'),
    ('把新增等级的「门槛要高过最高那一档」去掉', '③ 门槛不高过最高档被拒'),
    ('把手动合并的「只在同一账户下同名时能发起」去掉', '④ 不同账户的两份档案发起不了合并'),
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
    # ⚠️ 先切库:bind_tags 遇到没有绑定表会建表(并重算 tag.n)—— 指着真库就在共享库建出表
    import tag_level_write as T, oplog, merge
    T.DB = oplog.DB = merge.DB = 副本
    assert T.DB == oplog.DB == merge.DB == 副本, "库没切到副本"
    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as c:
            return [tuple(r) for r in c.execute(sql, a).fetchall()]
    def 人(sql, *a):
        r = q(sql, *a)
        return dict(no=r[0][0], name=r[0][1], role=r[0][2], shop=r[0][3]) if r else None
    总部 = 人("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' LIMIT 1")
    店长 = 人("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' AND shop_code IS NOT NULL ORDER BY no LIMIT 1")
    ck("样本:总部 / 店长", bool(总部 and 店长), 2)
    if not (总部 and 店长): return
    码 = q("SELECT shop_code FROM staff WHERE no=?", 店长["no"])[0][0]

    print("\n① 新建标签")
    r = T.save_tag(dict(name="检查标签", grp="检查组"), 店长)
    ck("① 店长建不了标签", r.get("code") == "WRONG_ROLE", 1, r.get("code"))
    r = T.save_tag(dict(name="检查标签", grp="检查组"), 总部)
    新标 = r.get("id")
    ck("① 总部能建,启用、人数 0", r.get("ok") and q("SELECT status, n FROM tag WHERE code=?", 新标 or "") == [("启用", 0)], 1, json.dumps(r, ensure_ascii=False)[:120])
    ck("① 同名被拒", T.save_tag(dict(name="检查标签", grp="x"), 总部).get("code") == "DUP_NAME", 1)

    print("\n② 打标签")
    本客 = q("SELECT id FROM customer WHERE shop_code=? ORDER BY id LIMIT 1", 码)
    别客 = q("SELECT id FROM customer WHERE shop_code IS NOT NULL AND shop_code<>? ORDER BY id LIMIT 1", 码)
    ck("样本:本店 / 别店客户", bool(本客 and 别客), 2)
    if 本客 and 别客:
        cid = 本客[0][0]
        with closing(sqlite3.connect(副本)) as c, c:
            T.建表(c)
        ck("② 建表时 tag.n 按真实绑定重算(没有绑定 → 全是 0,造数写的人数不再冒充)", q("SELECT MAX(n) FROM tag") == [(0,)], 1)
        r = T.bind_tags(dict(customer_id=别客[0][0], tags=[新标]), 店长)
        ck("② 店长给别店客户打不了", r.get("code") == "OTHER_SHOP", 1, r.get("code"))
        r = T.bind_tags(dict(customer_id=cid, tags=[新标, "TG01"]), 店长)
        ck("② 店长给本店客户打两个标签;两个标签人数各 +1", r.get("ok") and q("SELECT n FROM tag WHERE code IN (?, 'TG01') ORDER BY code", 新标) == [(1,), (1,)],
           1, json.dumps(r, ensure_ascii=False)[:120])
        with closing(sqlite3.connect(副本)) as c, c:
            c.execute("UPDATE tag SET status='停用' WHERE code=?", (新标,))
        其他客 = q("SELECT id FROM customer WHERE shop_code=? ORDER BY id LIMIT 1 OFFSET 1", 码)
        r1 = T.bind_tags(dict(customer_id=其他客[0][0], tags=[新标]), 店长) if 其他客 else {}
        r2 = T.bind_tags(dict(customer_id=cid, tags=[新标, "TG01"]), 店长)     # 已经打着的停用标签,原样提交不算新打
        ck("② 停用的标签不能新打,已打着的不受影响", r1.get("code") == "TAG_OFF" and r2.get("ok"), 2,
           json.dumps([r1.get("code"), r2.get("code")]))
        r = T.bind_tags(dict(customer_id=cid, tags=["TG01"]), 店长)
        ck("② 摘掉一个:那个标签人数 -1", r.get("ok") and r.get("摘") == [新标] and q("SELECT n FROM tag WHERE code=?", 新标) == [(0,)], 1)

    print("\n③ 会员等级")
    已 = q("SELECT code, name, amount, orders, need_points FROM level_cfg ORDER BY sort")
    顶 = 已[-1]
    ck("③ 店长加不了等级", T.save_level(dict(name="钻石", amount=顶[2] + 1, orders=顶[3] + 1, need_points=(顶[4] or 0) + 1), 店长).get("code") == "WRONG_ROLE", 1)
    r = T.save_level(dict(name="钻石", amount=顶[2], orders=顶[3] + 1, need_points=(顶[4] or 0) + 1), 总部)
    ck("③ 门槛不高过最高档被拒", r.get("code") == "NOT_ABOVE_TOP", 1, r.get("code"))
    r = T.save_level(dict(name="钻石", amount=顶[2] + 10000, orders=顶[3] + 2, need_points=(顶[4] or 0) + 10000), 总部)
    新级 = r.get("id")
    ck("③ 总部加一档:建出来是停用", r.get("ok") and q("SELECT status FROM level_cfg WHERE code=?", 新级 or "") == [("停用",)], 1, json.dumps(r, ensure_ascii=False)[:120])
    r = T.save_level(dict(code=新级, status="启用"), 总部)
    ck("③ 门槛单调时能启用", r.get("ok") and q("SELECT status FROM level_cfg WHERE code=?", 新级) == [("启用",)], 1, r.get("code"))
    ck("③ 普通会员不能停用", T.save_level(dict(code="L0", status="停用"), 总部).get("code") == "BASE_LEVEL", 1)
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("UPDATE level_cfg SET status='停用', amount=1 WHERE code=?", (新级,))
    ck("③ 启用后档位不单调就拒(把新档门槛改低再启用)", T.save_level(dict(code=新级, status="启用"), 总部).get("code") == "NOT_MONOTONIC", 1)

    print("\n④ 手动合并")
    同户 = q("""SELECT a.id, b.id FROM customer a JOIN customer b ON a.account_id=b.account_id AND a.name=b.name AND a.id<b.id
               WHERE a.account_id IS NOT NULL AND a.shop_code=b.shop_code AND a.merged_into IS NULL AND b.merged_into IS NULL
               AND NOT EXISTS(SELECT 1 FROM task t WHERE t.type='客户合并确认' AND t.ref_id IN (a.id||'|'||b.id, b.id||'|'||a.id)
                              AND t.status NOT IN ('已合并','已核验')) LIMIT 1""")
    if not 同户:
        # 系统发现的同户重复都已经建过任务了,现成的没有 —— 在副本里复制一位客户造一对(只在副本)
        原 = q("SELECT id FROM customer WHERE account_id IS NOT NULL AND shop_code IS NOT NULL AND merged_into IS NULL ORDER BY id LIMIT 1")
        if 原:
            with closing(sqlite3.connect(副本)) as c, c:
                列 = [r[1] for r in c.execute("PRAGMA table_info(customer)")]
                c.execute(f"INSERT INTO customer({','.join(列)}) SELECT {','.join('?' if x == 'id' else x for x in 列)} FROM customer WHERE id=?",
                          ("C99001", 原[0][0]))
            同户 = [(原[0][0], "C99001")]
    异户 = q("""SELECT a.id, b.id FROM customer a JOIN customer b ON a.account_id<>b.account_id AND a.shop_code=b.shop_code
               WHERE a.account_id IS NOT NULL AND b.account_id IS NOT NULL LIMIT 1""")
    ck("样本:一对同账户同名、一对不同账户", bool(同户 and 异户), len(同户) + len(异户))
    if 异户:
        r = T.manual_merge(dict(a=异户[0][0], b=异户[0][1], note="检查"), 总部)
        ck("④ 不同账户的两份档案发起不了合并", r.get("code") == "NOT_SAME_ACCOUNT", 1, r.get("code"))
    if 同户:
        a, b = 同户[0]
        r = T.manual_merge(dict(a=a, b=b, note="检查"), 总部)
        ck("④ 同账户同名:建出合并确认任务,状态「待核验」", r.get("ok") and q("SELECT status FROM task WHERE id=?", r.get("id") or "") == [("待核验",)],
           1, json.dumps(r, ensure_ascii=False)[:160])
        ck("④ 同一对再发起被拒", T.manual_merge(dict(a=b, b=a, note="检查"), 总部).get("code") == "DUP_TASK", 1)
    顾 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' LIMIT 1")
    ck("④ 顾问发起不了", T.manual_merge(dict(a="C1", b="C2"), 顾).get("code") == "WRONG_ROLE", 1)

    print("\n⑤ 入口")
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    ck("⑤ 四个写口交会话登录人", bool(re.search(r'return self\._send\(fn\(body, 登录人\)\)', src))
       and all(f'"/api/{u}"' in src for u in ("tag-save", "customer-tags", "level-save", "merge-manual")), 4)
    # 裁片用料(台账第五十一条):改占比走现成的 api.set_piece_ratio,身份从会话塞进工具层;三张口径表没有任何写口
    ck("⑤ /api/piece-ratio 以会话登录人的身份调 set_piece_ratio(不另写一份规则)",
       bool(re.search(r'with backend\.as_user\(登录人\):\s*\n\s*r = backend\.set_piece_ratio\(', src)), 1)
    ck("⑤ 三张口径表只读:server 里没有改档差 / 门幅 / 修版量的写口",
       not re.search(r'if p==?"/api/[\w-]*(grading|width|fitting-rule|pattern-rule)[\w-]*"\s*:?\s*\n?\s*.*(UPDATE|INSERT)', src)
       and "/api/pattern-rules" in src and not re.search(r'p\s*==\s*"/api/pattern-rules-save"', src), 1)
    页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    残 = [x for x in ("标签配置 · 本期未实现", "新建标签 · 本期未实现", "新增等级 · 本期未实现", "系统设置 · 本期未实现", "· 本期未实现\">+ ${fin") if x in 页]
    ck("⑤ 页面上这五处不再是「本期未实现」", not 残, 5, f"还剩 {残}")

    print()
    if FAIL:
        print(f"❌ 标签 / 等级 / 手动合并 {len(FAIL)} 条不过:" + "、".join(FAIL)); sys.exit(1)
    print("✅ 标签 / 等级 / 手动合并全过")


if __name__ == "__main__":
    main()
