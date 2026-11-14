#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**店名整库改名**(用户 11-14 夜拍板,台账第五十八条)。

## 为什么不能只改 shop 表

库里约 5 万行存的是拼好的显示串「SH001 静安旗舰店」(shop_key.py 文件头),
新写入拿这串去换门店码时是**整串精确比对**当前 shop 表。只改 shop.name ——
新建的客户 / 预约 / 单子就认不出是哪家店,按门店筛会**安静地少几行**。
所以店铺资料页那个「编辑」一直不许改店名(server.save_shop ①),改名只走这里。

## 规矩(用户拍的五条 + 实现时定的三条)

  ① 只总部运营;身份只认会话
  ② **先预览**:会动哪些表、各多少行;哪些地方出现了老店名但**不改**(合同正文、研判原文、
     已生成的报告这类历史快照 —— 签过的合同改了就不是签的那份了)
  ③ 一个事务里全改(BEGIN IMMEDIATE,改的过程中别的写入排队等)
  ④ 改完在**同一个事务里对账**:老串在要改的列里一行不剩、新串行数 = 预览行数、门店码一行没变;
     对不上就整个回滚,什么都不改
  ⑤ 能撤销:撤销 = 按台账里那一笔原样改回去,只许撤**最近一次**、且店名还是改后的那个
  ⑥ 预览里冒出**没登记的列**也存着整串老店名 → 拒改,要人先判断它是不是门店键
     (名单明写不现扫,理由同 shop_key.带门店键的:扫出来的会把没人看过的列悄悄纳进来)
  ⑦ 改完作废这家店员工的登录会话 —— 会话里存的门店串是登录时的,不作废,他们开单时
     「客户在本店吗」这道比对会拿老串去比新串,一律判成别的店
  ⑧ 台账和改动同生同死(oplog.log_op 的 conn 参数),撤销靠读这一笔
"""
from contextlib import closing
import os, sys, json, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE] if HERE not in sys.path else []
DB = os.path.join(HERE, "lanxiu.db")

import shop_key

# 改名要改的列 = 门店键名单 + 下面这几处**不带门店码列**、但装着整串显示名的列。
# ⚠️ account.home_shop 是 11-14 夜做改名预览时扫出来的(1682 行装着「SH003 杭州湖滨店」),
#    它不在 shop_key.带门店键的 里 —— 那张名单收的是「要配 shop_code 列」的表,账户表没配。
#    不改它,顾客账户的「常去门店」就指着一个不存在的店名。
另外要改的 = [("account", "home_shop")]
要改的列 = list(shop_key.带门店键的) + 另外要改的

# 出现老店名但**不改**的列:历史快照。改了就不是当时的那份了
# (合同正文是签署时的条款快照;研判原文是模型当时的输出;报告是当时生成的成品)。
快照列 = {
    ("order_contract", "body"): "签署时的合同正文",
    ("order_mix_batch", "payload"): "当时提交的批次原文",
    ("triage", "ai_text"): "研判当时的模型原文", ("triage", "ai_root_cause"): "研判当时的模型原文", ("triage", "ai_evidence"): "研判当时引用的证据",
    ("store_report_doc", "body"): "已生成的门店报告正文", ("store_report_doc", "pack"): "已生成的门店报告附件",
    ("op_log", "reason"): "操作台账(历史)", ("op_log", "ctx"): "操作台账(历史)",
    ("op_log", "target"): "操作台账(历史)", ("op_log", "frm"): "操作台账(历史)", ("op_log", "too"): "操作台账(历史)",
}
最长 = 20
机 = "shop-rename"


def _拒(code, reason, **k):
    return dict(ok=False, code=code, reason=reason, **k)


def _文本列(c):
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        for r in c.execute(f'PRAGMA table_info("{t}")'):
            ty = (r[2] or "").upper()
            if ty in ("", "TEXT") or "CHAR" in ty or "CLOB" in ty:
                yield t, r[1]


def 扫(c, 老串, 老名):
    """→ (要改 {(表,列): 行数}, 没登记 {(表,列): 行数}, 快照 {(表,列): 行数})。
    登记了要改的列只认「整列等于老串」;快照列报「文字里出现老店名」;
    其余没登记的列只要文字里夹着整串老店名就报(拒改,等人判断)。"""
    要改, 没登记, 快照 = {}, {}, {}
    已登记 = set(要改的列)
    for t, col in _文本列(c):
        if (t, col) in 已登记:
            n = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}"=?', (老串,)).fetchone()[0]
            要改[(t, col)] = n
            continue
        if (t, col) in 快照列:
            n = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE instr("{col}", ?)>0', (老名,)).fetchone()[0]
            if n: 快照[(t, col)] = n
            continue
        if (t, col) == ("shop", "name"):
            continue
        # 没登记的列:整列等于老串、**或文字里夹着整串老店名**(比如某个设置存的门店名单)都算 ——
        # 后者改不改要人判断,不能因为「不是整列相等」就当没看见
        n = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE instr("{col}", ?)>0', (老串,)).fetchone()[0]
        if n: 没登记[(t, col)] = n
    return 要改, 没登记, 快照


def _越权(me, code, db):
    """角色闸放在最前面(撤销也走它),被拒也留痕 —— 和其他写口一致"""
    if not me: return _拒("NO_LOGIN", "请先登录")
    if me.get("role") != "总部运营":
        import oplog
        why = f"店名整库改名只许总部运营操作,你是「{me.get('role')}」"
        oplog.log_op(me.get("name") or me.get("no"), 机, (code or "").strip().upper() or "-", "—", "改名", False,
                     "WRONG_ROLE", why, dict(by=me.get("no"), role=me.get("role")), db=db or DB)
        return _拒("WRONG_ROLE", why)
    return None


def _校验(c, me, code, 新名):
    if not me: return None, _拒("NO_LOGIN", "请先登录")
    if me.get("role") != "总部运营":
        return None, _拒("WRONG_ROLE", f"店名整库改名只许总部运营操作,你是「{me.get('role')}」")
    code = (code or "").strip().upper()
    新名 = (新名 or "").strip()
    r = c.execute("SELECT code, name FROM shop WHERE code=?", (code,)).fetchone()
    if not r: return None, _拒("NO_SHOP", f"没有门店 {code}")
    if not 新名: return None, _拒("NEED_NAME", "新店名必填")
    if len(新名) > 最长: return None, _拒("NAME_TOO_LONG", f"店名最多 {最长} 个字")
    if any(ch in 新名 for ch in " \t\r\n,，"):
        # 显示串是「编码 + 空格 + 店名」,店名里再带空格,拆串的地方会拆错;逗号会把批量导入的那一行拆成两列
        return None, _拒("BAD_NAME", "店名里不能有空格或逗号")
    if 新名 == r[1]: return None, _拒("SAME_NAME", f"{code} 现在就叫「{新名}」")
    if c.execute("SELECT 1 FROM shop WHERE name=? AND code<>?", (新名, code)).fetchone():
        return None, _拒("NAME_TAKEN", f"已有别的门店叫「{新名}」")
    return dict(code=code, 老名=r[1], 新名=新名, 老串=f"{code} {r[1]}", 新串=f"{code} {新名}"), None


def _表(d):
    return [dict(表=t, 列=col, 行数=n) for (t, col), n in sorted(d.items(), key=lambda x: (-x[1], x[0]))]


def 预览(d, me, db=None):
    """d: code, new_name → 会动哪些表各多少行、哪些快照里出现了老店名但不改。业务数据一行都不写。"""
    越 = _越权(me, d.get("code"), db)
    if 越: return 越
    with closing(sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)) as c:
        x, 错 = _校验(c, me, d.get("code"), d.get("new_name"))
        if 错: return 错
        要改, 没登记, 快照 = 扫(c, x["老串"], x["老名"])
        码数 = {t: c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE shop_code=?', (x["code"],)).fetchone()[0]
              for t, col in shop_key.带门店键的 if shop_key.有列(c, t)}
    合计 = sum(要改.values()) + 1
    return dict(ok=not 没登记, code="PREVIEW" if not 没登记 else "UNREGISTERED_COLUMN",
                门店=x["code"], 老名=x["老名"], 新名=x["新名"],
                要改=[dict(表="shop", 列="name", 行数=1)] + _表(要改), 合计=合计,
                没登记=_表(没登记), 快照不改=[dict(r, 是什么=快照列[(r["表"], r["列"])]) for r in _表(快照)],
                门店码行数=码数,
                reason=(f"把「{x['老串']}」改成「{x['新串']}」:{len([v for v in 要改.values() if v]) + 1} 张表、共 {合计} 行;"
                        f"合同正文等 {sum(快照.values())} 处历史快照保留原样" if not 没登记 else
                        "有没登记的列也存着整串老店名:" + "、".join(f"{t}.{col}({n} 行)" for (t, col), n in 没登记.items())
                        + " —— 先判断它是不是门店键、登记进 shop_rename.要改的列 或 快照列,再来改"))


def 改名(d, me, db=None, _撤销=None):
    """真改。d: code, new_name, expect_total(预览给的合计 —— 和现在扫出来的不一样就不改,防预览后又有新数据)。"""
    import oplog
    目标 = db or DB
    越 = _越权(me, d.get("code"), 目标)
    if 越: return 越
    with closing(sqlite3.connect(目标, isolation_level=None, timeout=30)) as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            x, 错 = _校验(c, me, d.get("code"), d.get("new_name"))
            if 错:
                c.execute("ROLLBACK"); return 错
            要改, 没登记, 快照 = 扫(c, x["老串"], x["老名"])
            if 没登记:
                c.execute("ROLLBACK")
                return _拒("UNREGISTERED_COLUMN", "有没登记的列也存着整串老店名,先预览看清再登记",
                          没登记=_表(没登记))
            合计 = sum(要改.values()) + 1
            期望 = d.get("expect_total")
            if 期望 is None or int(期望) != 合计:
                c.execute("ROLLBACK")
                return _拒("PREVIEW_STALE", f"预览时是 {期望} 行、现在是 {合计} 行 —— 中间有新数据进来,重新预览再改",
                          合计=合计)
            码前 = {t: c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE shop_code=?', (x["code"],)).fetchone()[0]
                  for t, col in shop_key.带门店键的 if shop_key.有列(c, t)}
            c.execute("UPDATE shop SET name=? WHERE code=?", (x["新名"], x["code"]))
            for (t, col), n in 要改.items():
                if n:
                    c.execute(f'UPDATE "{t}" SET "{col}"=? WHERE "{col}"=?', (x["新串"], x["老串"]))
            # ── 对账(同一个事务里,对不上就回滚)──
            差 = []
            for (t, col), n in 要改.items():
                剩 = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}"=?', (x["老串"],)).fetchone()[0]
                新 = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}"=?', (x["新串"],)).fetchone()[0]
                if 剩 or 新 != n:
                    差.append(f"{t}.{col}:老串还剩 {剩}、新串 {新} 行(应为 {n})")
            for t, n in 码前.items():
                后 = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE shop_code=?', (x["code"],)).fetchone()[0]
                if 后 != n: 差.append(f"{t} 的门店码行数 {n} → {后}")
            if c.execute("SELECT name FROM shop WHERE code=?", (x["code"],)).fetchone()[0] != x["新名"]:
                差.append("shop 表店名没改上")
            if shop_key.码(c, x["新串"]) != x["code"] or shop_key.码(c, x["老串"]) is not None:
                差.append("改完后新店名换不出门店码,或老店名还换得出")
            if 差:
                c.execute("ROLLBACK")
                return _拒("RECONCILE_FAILED", "改完对账对不上,已整个回滚、什么都没改:" + ";".join(差))
            明细 = {f"{t}.{col}": n for (t, col), n in 要改.items() if n}
            oplog.log_op(me.get("name") or me.get("no"), 机, x["code"], x["老名"], x["新名"], True,
                         "UNDO" if _撤销 else "RENAME",
                         (f"撤销第 {_撤销} 号改名:" if _撤销 else "店名整库改名:")
                         + f"「{x['老串']}」→「{x['新串']}」,{len(明细) + 1} 张表共 {合计} 行,对账一致",
                         dict(by=me.get("no"), 老名=x["老名"], 新名=x["新名"], 明细=明细, 合计=合计,
                              快照不改={f"{t}.{col}": n for (t, col), n in 快照.items()}, 撤销的=_撤销),
                         db=目标, conn=c)
            c.execute("COMMIT")
        except Exception:
            try: c.execute("ROLLBACK")
            except sqlite3.Error: pass
            raise
    # 会话里存的门店串是登录时的 —— 这家店的人重新登录才拿到新串
    作废 = 0
    try:
        import auth
        with closing(sqlite3.connect(目标)) as c2:
            for (no,) in c2.execute("SELECT no FROM staff WHERE shop=?", (x["新串"],)):
                作废 += auth.作废(no) or 0
    except Exception as e:      # 作废失败不回滚改名(改名已对账提交),但要说出来
        return dict(ok=True, code="RENAMED_SESSIONS_KEPT", 合计=合计, 明细=明细,
                    reason=f"已改名、对账一致;但作废登录会话时出错({e}),这家店的员工请手动退出重登")
    return dict(ok=True, code="UNDONE" if _撤销 else "RENAMED", 合计=合计, 明细=明细, 作废会话=作废,
                reason=f"已把「{x['老串']}」改成「{x['新串']}」:{len(明细) + 1} 张表共 {合计} 行,对账一致;"
                       f"这家店员工的 {作废} 个登录会话已作废,重新登录后生效")


def 撤销(d, me, db=None):
    """撤销最近一次改名。d: code。只许撤最近一次、且店名还是改后的那个。"""
    目标 = db or DB
    越 = _越权(me, d.get("code"), 目标)
    if 越: return 越
    code = (d.get("code") or "").strip().upper()
    with closing(sqlite3.connect(f"file:{目标}?mode=ro", uri=True)) as c:
        r = c.execute("SELECT id, frm, too, code FROM op_log WHERE machine=? AND target=? AND allowed=1 "
                      "ORDER BY id DESC LIMIT 1", (机, code)).fetchone()
        现 = c.execute("SELECT name FROM shop WHERE code=?", (code,)).fetchone()
    if not r: return _拒("NOTHING_TO_UNDO", f"{code} 没有改过名")
    if r[3] == "UNDO": return _拒("ALREADY_UNDONE", f"{code} 最近一次改名已经撤销过了")
    if not 现 or 现[0] != r[2]:
        return _拒("NAME_CHANGED", f"{code} 现在叫「{现[0] if 现 else '?'}」,不是那次改成的「{r[2]}」—— 不能撤")
    p = 预览(dict(code=code, new_name=r[1]), me, db=目标)
    if not p.get("ok"): return p
    return 改名(dict(code=code, new_name=r[1], expect_total=p["合计"]), me, db=目标, _撤销=r[0])
