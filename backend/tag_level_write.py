#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户标签 / 会员等级 / 手动合并的写口(11-14,台账第四十九条:剩下 5 处「本期未实现」全做)。

## 客户标签:原来**没有绑定这回事**

标签页上「已绑定客户 35 人」是造数时**直接写进 tag.n 的数**,库里没有任何一条「哪位客户打了哪个标签」的记录 ——
> 一个「35 位客户真打了这个标签」和一个「造数时随手填的 35」,在标签页上长得一模一样。
现在有了绑定表 `customer_tag`;`tag.n` 变成它的**计数副本**:建表那一步按真实绑定重算一遍(于是造出来的数归零),
之后每次打 / 摘都同步。排序、筛选照旧读 n,不用改。

谁能做什么(和四组按钮同一套口径):
  · 新建标签 = 字典维护 → **只总部运营**
  · 给客户打 / 摘标签 = 门店日常(和「编辑预约」一个道理,台账第四十八条)→ **本店的人给本店客户**,总部全部;
    停用的标签不能新打(toggle 那条说明写着「停用后不可新增绑定,但保留历史客户上的标签显示」—— 这里兑现它)

## 会员等级:新等级**先停用**

等级判定是**现读 level_cfg 里启用的那几档**(api._levels)—— 一加上去、一启用,所有客户当场按新门槛重新分档。
所以:新等级的金额 / 单数 / 积分门槛都必须**高过现在最高那一档**(档位单调,不插在中间改动别人的档),
建出来是「停用」,总部核对完门槛再启用(和新店先「无效」同一个道理)。

## 手动合并:只建任务,不直接合

「手动合并」= 店长指定两份档案,建一条和系统发现的一样的「客户合并确认」任务;后面照旧店长核验 → 总部审批。
**只在「同一个账户下、同名」时能发起**(merge.判同一人 == 同一人)—— 用户 2026-10-26 定「不跨账户合并档案」。
"""
import os, re, sqlite3
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

DDL = """CREATE TABLE IF NOT EXISTS customer_tag(
  customer_id TEXT NOT NULL,
  tag_code    TEXT NOT NULL,
  created_by  TEXT NOT NULL,      -- 打标签的员工工号
  created_at  TEXT NOT NULL,      -- 世界时钟(客户档案上的事,跟着演示世界走)
  PRIMARY KEY(customer_id, tag_code))"""


def 建表(c):
    """建绑定表,并把 tag.n 按真实绑定重算一遍(造数写进去的数在这里归零 —— 见文件头)。"""
    c.execute(DDL)
    c.execute("UPDATE tag SET n=(SELECT COUNT(*) FROM customer_tag k WHERE k.tag_code=tag.code)")


def _连():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    import worldclock as _wc
    c.create_function("wnow", 0, lambda: _wc.当下().strftime("%Y-%m-%d %H:%M"))
    return c


def _闸(me, 机, 目标, 动作):
    from oplog import log_op
    角色 = (me or {}).get("role"); 谁 = (me or {}).get("name") or "?"
    def 拒(码, 为何):
        log_op(谁, 机, 目标 or "?", 动作, "拒绝", False, 码, 为何, {"role": 角色})
        return dict(ok=False, code=码, reason=为何)
    return 谁, 角色, 拒


def save_tag(d, me):
    """新建标签(字典维护,只总部运营)。分组可以选已有的,也可以新起一个。"""
    from oplog import log_op
    谁, 角色, 拒 = _闸(me, "tag", "(新标签)", "新建")
    if 角色 != "总部运营": return 拒("WRONG_ROLE", f"标签只有总部运营能建,当前角色:{角色 or '未知'}")
    名 = str(d.get("name") or "").strip(); 组 = str(d.get("grp") or "").strip()
    if not 名: return 拒("NEED_NAME", "标签名称必填")
    if len(名) > 10: return 拒("TOO_LONG", "标签名称最多 10 个字")
    if not 组: return 拒("NEED_GROUP", "所属分组必填(可以选已有的,也可以新起一个)")
    if len(组) > 8: return 拒("TOO_LONG", "分组名最多 8 个字")
    with closing(_连()) as c, c:
        if c.execute("SELECT 1 FROM tag WHERE name=?", (名,)).fetchone(): return 拒("DUP_NAME", f"已经有「{名}」这个标签了")
        号 = [int(r[0][2:]) for r in c.execute("SELECT code FROM tag WHERE code LIKE 'TG%'") if r[0][2:].isdigit()]
        code = f"TG{(max(号) + 1 if 号 else 1):02d}"
        c.execute("INSERT INTO tag(code,name,grp,status,n,updated) VALUES(?,?,?,'启用',0,wnow())", (code, 名, 组))
    log_op(谁, "tag", code, "—", "启用", True, "CREATE", f"{名} · {组}", {"role": 角色})
    return dict(ok=True, code="CREATE", id=code, reason=f"标签 {code}「{名}」已建好")


def bind_tags(d, me):
    """给一位客户设定标签(整组替换:页面勾哪些就是哪些)。本店的人给本店客户;停用的标签不能新打。"""
    from oplog import log_op
    import shop_key as _SK
    cid = str(d.get("customer_id") or "").strip()
    谁, 角色, 拒 = _闸(me, "customer_tag", cid, "设标签")
    if not me: return 拒("NO_LOGIN", "请先登录")
    要 = sorted({str(x).strip() for x in (d.get("tags") or []) if str(x).strip()})
    if len(要) > 20: return 拒("TOO_MANY", "一位客户最多 20 个标签")
    with closing(_连()) as c, c:
        建表(c) if not c.execute("SELECT 1 FROM sqlite_master WHERE name='customer_tag'").fetchone() else None
        k = c.execute("SELECT id, shop, shop_code FROM customer WHERE id=?", (cid,)).fetchone()
        if not k: return 拒("NO_CUSTOMER", f"没有客户 {cid}")
        if 角色 != "总部运营":
            我店 = _SK.码(c, me.get("shop"))
            if not 我店 or 我店 != (k["shop_code"] or _SK.码(c, k["shop"])):
                return 拒("OTHER_SHOP", "只能给本店的客户打标签")
        字典 = {r["code"]: r["status"] for r in c.execute("SELECT code, status FROM tag")}
        不认 = [t for t in 要 if t not in 字典]
        if 不认: return 拒("NO_TAG", f"没有这些标签:{'、'.join(不认)}")
        原 = {r[0] for r in c.execute("SELECT tag_code FROM customer_tag WHERE customer_id=?", (cid,))}
        加 = [t for t in 要 if t not in 原]; 摘 = [t for t in 原 if t not in 要]
        停 = [t for t in 加 if 字典[t] != "启用"]
        if 停: return 拒("TAG_OFF", f"这些标签已停用,不能新打:{'、'.join(停)}(已经打着的不受影响)")
        for t in 摘: c.execute("DELETE FROM customer_tag WHERE customer_id=? AND tag_code=?", (cid, t))
        for t in 加: c.execute("INSERT INTO customer_tag(customer_id,tag_code,created_by,created_at) VALUES(?,?,?,wnow())",
                              (cid, t, me.get("no")))
        for t in set(加) | set(摘):     # tag.n 是计数副本,跟着改
            c.execute("UPDATE tag SET n=(SELECT COUNT(*) FROM customer_tag WHERE tag_code=?) WHERE code=?", (t, t))
    log_op(谁, "customer_tag", cid, "设标签", "已保存", True, "UPDATE",
           f"加 {'、'.join(加) or '无'};摘 {'、'.join(摘) or '无'}", {"role": 角色})
    return dict(ok=True, code="UPDATE", 加=加, 摘=摘,
                reason=f"已保存:加 {len(加)} 个、摘 {len(摘)} 个" if (加 or 摘) else "没有变化")


def save_level(d, me):
    """新增会员等级(先停用)/ 启用或停用一档。只总部运营。档位必须单调:新的一档高过现在最高那一档。"""
    from oplog import log_op
    code = str(d.get("code") or "").strip()
    谁, 角色, 拒 = _闸(me, "level_cfg", code or "(新等级)", "改状态" if code else "新建")
    if 角色 != "总部运营": return 拒("WRONG_ROLE", f"会员等级只有总部运营能改,当前角色:{角色 or '未知'}")
    with closing(_连()) as c, c:
        已 = [dict(r) for r in c.execute("SELECT * FROM level_cfg ORDER BY sort")]
        if code:     # 启用 / 停用
            r = next((x for x in 已 if x["code"] == code), None)
            if not r: return 拒("NO_LEVEL", f"没有等级 {code}")
            to = d.get("status")
            if to not in ("启用", "停用"): return 拒("BAD_STATUS", "状态只能是 启用 / 停用")
            if code == "L0" and to == "停用": return 拒("BASE_LEVEL", "普通会员是注册后的默认等级,不能停用")
            if to == "启用":
                低 = [x for x in 已 if x["status"] == "启用" and x["sort"] < r["sort"]]
                高 = [x for x in 已 if x["status"] == "启用" and x["sort"] > r["sort"]]
                if any(x["amount"] >= r["amount"] or x["orders"] >= r["orders"] for x in 低) or \
                   any(x["amount"] <= r["amount"] or x["orders"] <= r["orders"] for x in 高):
                    return 拒("NOT_MONOTONIC", "启用后档位门槛不再从低到高递增 —— 先把门槛改对再启用")
            c.execute("UPDATE level_cfg SET status=? WHERE code=?", (to, code))
            改状态 = (r, to)
        else:
            改状态 = None
    if 改状态:
        # ⚠️ 台账要在事务提交之后记:log_op 另开一条连接写同一个库,事务里记会撞上自己没提交的写锁
        r, to = 改状态
        log_op(谁, "level_cfg", code, r["status"], to, True, "STATUS",
               f"{r['name']} {r['status']}→{to}" + ("(所有客户按新门槛重新分档)" if to != r["status"] else ""), {"role": 角色})
        return dict(ok=True, code="STATUS", id=code,
                    reason=f"{r['name']} 已{to}" + ("—— 客户等级按新门槛现算,下次打开就是新档" if to != r["status"] else ""))
    with closing(_连()) as c, c:
        已 = [dict(r) for r in c.execute("SELECT * FROM level_cfg ORDER BY sort")]
        名 = str(d.get("name") or "").strip()
        if not 名: return 拒("NEED_NAME", "等级名称必填")
        if len(名) > 6: return 拒("TOO_LONG", "等级名称最多 6 个字")
        if any(x["name"] == 名 for x in 已): return 拒("DUP_NAME", f"已经有「{名}」了")
        try:
            额 = float(d.get("amount")); 单 = int(d.get("orders")); 分 = int(d.get("need_points") or 0)
        except (TypeError, ValueError):
            return 拒("BAD_NUMBER", "金额门槛、订单门槛要填数字(积分门槛可空)")
        顶 = max(已, key=lambda x: x["sort"]) if 已 else None
        if 顶 and (额 <= 顶["amount"] or 单 <= 顶["orders"] or 分 <= (顶["need_points"] or 0)):
            return 拒("NOT_ABOVE_TOP", f"新等级的门槛要都高过现在最高的「{顶['name']}」"
                                     f"(¥{顶['amount']:.0f} / {顶['orders']} 单 / {顶['need_points'] or 0} 分)—— 档位从低到高递增,不插在中间")
        号 = [int(x["code"][1:]) for x in 已 if x["code"][1:].isdigit()]
        new = f"L{(max(号) + 1 if 号 else 0)}"
        规则 = str(d.get("point_rule") or "").strip()[:40] or None
        c.execute("INSERT INTO level_cfg(code,name,amount,orders,sort,status,note,need_points,point_rule) "
                  "VALUES(?,?,?,?,?,'停用',?,?,?)",
                  (new, 名, 额, 单, (顶["sort"] + 1 if 顶 else 0),
                   f"滚动 12 个月实付 ≥{额:.0f} 元 或 完成订单 ≥{单} 单", 分, 规则))
    log_op(谁, "level_cfg", new, "—", "停用", True, "CREATE", f"{名} · ¥{额:.0f} / {单} 单 / {分} 分(新等级先停用)", {"role": 角色})
    return dict(ok=True, code="CREATE", id=new, reason=f"等级 {new}「{名}」已建,**先是停用** —— 核对门槛后点启用,所有客户才按新门槛分档")


def manual_merge(d, me):
    """手动发起合并:建一条「客户合并确认」任务,后面照旧店长核验 → 总部审批。只在同一账户下、同名时能发起。"""
    from oplog import log_op
    import merge as _mg, shop_key as _SK
    a = str(d.get("a") or "").strip(); b = str(d.get("b") or "").strip()
    谁, 角色, 拒 = _闸(me, "bk-merge", f"{a}|{b}", "手动发起")
    if 角色 not in ("店长", "总部运营"): return 拒("WRONG_ROLE", f"手动发起合并要店长或总部运营,当前角色:{角色 or '未知'}")
    if not (a and b) or a == b: return 拒("NEED_TWO", "要填两个不同的客户编码")
    with closing(_连()) as c, c:
        行 = {r["id"]: dict(r) for r in c.execute(
            "SELECT c.id, c.name, c.phone, c.birthday, c.addr, c.shop, c.shop_code, c.account_id FROM customer c WHERE c.id IN (?,?)", (a, b))}
        缺 = [x for x in (a, b) if x not in 行]
        if 缺: return 拒("NO_CUSTOMER", f"没有客户 {'、'.join(缺)}")
        if 角色 != "总部运营":
            我店 = _SK.码(c, me.get("shop"))
            if any((行[x]["shop_code"] or _SK.码(c, 行[x]["shop"])) != 我店 for x in (a, b)):
                return 拒("OTHER_SHOP", "店长只能发起本店客户之间的合并")
        结论, 理由 = _mg.判同一人(行[a], 行[b])
        if 结论 != "同一人":
            return 拒("NOT_SAME_ACCOUNT", f"{结论}:{理由} —— 只有同一个账户下、同名的重复档案才能合并(不跨账户合并档案,用户 10-26 定)")
        if c.execute("SELECT 1 FROM task WHERE type='客户合并确认' AND ref_id IN (?,?) AND status NOT IN ('已合并','已核验')",
                     (f"{a}|{b}", f"{b}|{a}")).fetchone():
            return 拒("DUP_TASK", "这两份档案已经有一条没办完的合并确认任务")
        号 = [int(r[0].split("-")[-1]) for r in c.execute("SELECT id FROM task WHERE id LIKE 'TMERGE-M%'") if r[0].split("-")[-1].isdigit()]
        tid = f"TMERGE-M{(max(号) + 1 if 号 else 1):03d}"
        c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,wnow(),?)",
                  (tid, "客户合并确认", f"{a}|{b}", "待核验", f"手动发起:{str(d.get('note') or '').strip()[:80]}"))
    log_op(谁, "bk-merge", f"{a}|{b}", "—", "待核验", True, "MANUAL", f"手动发起合并 {tid}:{理由}", {"role": 角色})
    return dict(ok=True, code="MANUAL", id=tid, reason=f"已建合并确认任务 {tid},接下来照旧核验 → 总部审批")
