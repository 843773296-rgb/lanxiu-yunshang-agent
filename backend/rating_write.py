# -*- coding: utf-8 -*-
"""签收后顾客评价的写口 —— 提交、改、店长处理差评。

口径在 `knowledge/rating.py`(业务 2026-09-24 定渠道,09-27 定剩下三条)。

## 谁能做什么

  顾客端(演示用:凭订单号 + 手机后四位,和 pickup_write 同一个门)
    提交评价   签收之后 → 1-5 星 + 评语。**一个包裹一次**
    改评价     24 小时内、最多一次

  店长
    处理差评   关掉那张工单,**必须写处理记录**

⚠️ 顾问**不能**替顾客评(`src` 只认「顾客小程序」)。业务 09-27 定了「不进考核」,
所以现在**没有防刷** —— 一旦要进考核,见 `knowledge/rating.进考核前要做什么()`。

## 「没签收不许评」这道闸架在哪个事实上

判据是 `pickup_item.fit_result='合身' AND fit_at IS NOT NULL` —— **签收动作自己的记录**,
不是 `ordr.status`。区别不是文字游戏:

  · `ordr.status` 是**算出来的状态**,后台改状态、状态机之外的任何一条路写进去,闸就开了;
  · `pickup_item.fit_at` 是**签收那一下留下的行** —— 改它等于伪造一条签收记录。

⚠️ **但要诚实:这比「那个 6 位码被核验过」弱一档。** 更硬的证据本来是
`fit_code` 里 `P:{pkg_id}` 那一行的 `used_at`(顾客本人在场点过、导购输入过)。
不用它的原因是**造数没走 `verify()`** —— 2026-09-27 量到:库里 3330 个包裹签收了,
码表里只有 31 条核验痕迹,**3299 个是造数直接写的 `fit_result='合身'`**。
拿码当闸的后果是这个功能在演示库上几乎全评不了,而那说明的是造数的路子,
不是顾客没签收。

> 这笔欠在**签收那条线**上(造数应该走写口,或者至少补上码痕迹),
> 不该由评价功能替它扛。记在 PRD 附录 B 里。

## 差评进的是**已有的**待处理清单

`task` 表,`type='评价差评'`,工单号 `TR{包裹号}`(定的,重跑不会重复建)。
**没有新建第二张清单表** —— 理由写在 `seed_rating.py` 里。
处理到哪一步**只看 `task.status`**,`rating` 表故意不存 status。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
from oplog import log_op
import worldclock
import rating as R

店长角色 = ("店长",)
来源_顾客 = "顾客小程序"
工单类型 = "评价差评"


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _now():
    """**世界的当下**,不是机器时钟。

    `rating.rated_at` / `edited_at` / `handled_at` 三列都会被 `tools/shift_world.py` 平移
    (它是**扫列**的,自动就把这三列算进去),所以它们必须用世界时钟写 ——
    判据就是 `worldclock.py` 文档里那一句:**这一列会不会被平移**。

    ⚠️ 这三列同时也登记进了 `worldclock.已发生的时间列`。那份清单是**手写的**,
    C4 和平移前置闸两道都读它 —— 不登记就是**两道闸同时的盲区**
    (`pkg.created` 上次正是这么漏过去的)。
    """
    return worldclock.当下().strftime("%Y-%m-%d %H:%M")


def _deny(who, code, reason, key="—", role=None):
    log_op(who or "未登录", "rating", key, "—", "—", False, code, reason[:120], {"role": role})
    return dict(ok=False, code=code, reason=reason)


def _顾客的单(order_id, phone_tail):
    """和 `pickup_write` 共用同一个门 —— **不抄第二份**。

    抄一份的后果是其中一处的门先被改松,而两处长得一样;
    `pickup_write` 的文档里为同一个理由写过这句话。
    """
    import pickup_write as pw
    pw.DB = DB                       # 检查在库副本上跑时,这一行让两边指同一个副本
    return pw._顾客的单(order_id, phone_tail)


def _包里的件(pkg_id):
    """这个包裹里的件 + 各自的签收结果。**闸读的就是这个。**"""
    return rows("""SELECT i.item_id AS order_item_id, t.fit_result, t.fit_at, t.fit_verified_by
                     FROM pkg_item i LEFT JOIN pickup_item t ON t.order_item_id=i.item_id
                    WHERE i.pkg_id=? ORDER BY i.item_id""", pkg_id)


def _这一单的包裹(order_id):
    return rows("SELECT pkg_id FROM pkg WHERE order_id=? AND void_at IS NULL ORDER BY pkg_id", order_id)


def _评过的(pkg_id):
    r = rows("SELECT * FROM rating WHERE pkg_id=?", pkg_id)
    return r[0] if r else None


def _挑包裹(order_id, pkg):
    """一单一个包裹时不该逼顾客说是哪个;分批发的**不许替他挑**。返回 (pkg_id, 错误)。"""
    包 = [k["pkg_id"] for k in _这一单的包裹(order_id)]
    if not 包:
        return None, dict(ok=False, code="NO_PKG", reason="这一单还没有任何包裹,谈不上签收和评价")
    pid = str(pkg or "").strip()
    if pid:
        if pid not in 包:
            return None, dict(ok=False, code="NO_SUCH_PKG",
                              reason=f"这一单没有包裹 {pid}(有的是:{'、'.join(包)})")
        return pid, None
    可评 = [p for p in 包 if R.签收于(_包里的件(p)) and not _评过的(p)]
    if len(可评) == 1:
        return 可评[0], None
    if len(可评) > 1:
        return None, dict(ok=False, code="WHICH_PKG",
                          reason=f"这一单有 {len(可评)} 个包裹可以评,说清是哪一个:{'、'.join(可评)}")
    if len(包) == 1:
        return 包[0], None          # 只有一个包裹但评不了 —— 让闸去说原因,别在这儿含糊
    return None, dict(ok=False, code="NOTHING_TO_RATE",
                      reason=f"这一单 {len(包)} 个包裹,没有能评的(还没签收,或者都评过了)")


def _建工单(c, pkg_id, 待办):
    """差评**自动进**已有的待处理清单(`task`)。工单号是定的,重跑不重复建。"""
    tid = f"TR{pkg_id}"
    c.execute("INSERT OR REPLACE INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, 工单类型, pkg_id, "待处理", 待办["rated_at"],
               f"{待办['star']} 星差评:{待办['note'][:40]}"))
    return tid


# ── 顾客端 ────────────────────────────────────────────────────────────
def customer_rate(order_id, phone_tail, star, note=None, pkg=None):
    """顾客提交评价。签收之后、一个包裹一次。"""
    o, err = _顾客的单(order_id, phone_tail)
    if err: return err
    pid, err = _挑包裹(o["id"], pkg)
    if err: return err
    件 = _包里的件(pid)
    能, 话 = R.能不能评(件, _now(), 评过了吗=bool(_评过的(pid)), 来源=来源_顾客)
    if not 能:
        return _deny("顾客", "CANNOT_RATE", 话, pid)
    收, n, 说 = R.收下星级(star)
    if not 收:
        return dict(ok=False, code="BAD_STAR", reason=说)
    顾问 = next((x["fit_verified_by"] for x in 件 if x["fit_result"] == "合身" and x["fit_verified_by"]), None)
    now = _now()
    待办 = R.差评待办(n, note, o["id"], pid, now, 顾问=顾问)
    with sqlite3.connect(DB) as c:
        tid = _建工单(c, pid, 待办) if 待办 else None
        c.execute("""INSERT INTO rating(pkg_id,order_id,customer_id,star,note,rated_at,src,advisor_no,
                                        edit_cnt,task_id) VALUES(?,?,?,?,?,?,?,?,0,?)""",
                  (pid, o["id"], o["customer_id"], n, (str(note or "").strip() or None),
                   now, 来源_顾客, 顾问, tid))
    log_op("顾客", "rating", pid, "—", f"{n}星", True, "RATED",
           f"订单 {o['id']} 包裹 {pid} 评 {n} 星" + ("(差评,已进待处理清单)" if 待办 else ""), {})
    出 = dict(ok=True, code="RATED", 订单=o["id"], 包裹=pid, 星=n,
              reason=f"谢谢,已收到 {n} 星" + (f",{R.能改几小时} 小时内可以改一次" if True else ""))
    if 待办:
        出.update(差评=True, 工单=tid,
                  reason=f"已收到 {n} 星(≤{R.差评线} 星算差评)—— 已经转给店长跟进,工单 {tid}")
    return 出


def customer_edit_rating(order_id, phone_tail, star, note=None, pkg=None):
    """顾客改自己的评价。24 小时内、最多一次。

    ⚠️ **好评改差评要进清单,差评改好评不撤出** —— 方向不对称,理由在
    `knowledge/rating.改了之后清单怎么动()`。
    """
    o, err = _顾客的单(order_id, phone_tail)
    if err: return err
    pid, err = _挑包裹(o["id"], pkg)
    if err: return err
    旧 = _评过的(pid)
    if not 旧:
        return dict(ok=False, code="NOT_RATED", reason=f"包裹 {pid} 还没评过 —— 先评再改")
    能, 话 = R.能不能改(旧["rated_at"], _now(), 改过几次=(旧["edit_cnt"] or 0))
    if not 能:
        return _deny("顾客", "CANNOT_EDIT", 话, pid)
    收, n, 说 = R.收下星级(star)
    if not 收:
        return dict(ok=False, code="BAD_STAR", reason=说)
    动作, 为什么 = R.改了之后清单怎么动(旧["star"], n, bool(旧["task_id"]))
    now = _now()
    with sqlite3.connect(DB) as c:
        tid = 旧["task_id"]
        if 动作 == "进清单":
            tid = _建工单(c, pid, R.差评待办(n, note if note is not None else 旧["note"],
                                          o["id"], pid, now))
        elif 动作 == "更新星级":
            c.execute("UPDATE task SET summary=? WHERE id=?",
                      (f"{n} 星差评(顾客从 {旧['star']} 星改的)", tid))
        elif 动作 == "留在清单里":
            # **不关、不删** —— 只在工单上标一句。撤掉就再也看不出
            # 「差评被处理好了」和「从来没有差评」的区别。
            c.execute("UPDATE task SET summary=? WHERE id=?",
                      (f"顾客后来改成 {n} 星(原 {旧['star']} 星差评,清单不撤)", tid))
        c.execute("""UPDATE rating SET star=?, note=COALESCE(?,note), edited_at=?,
                                       edit_cnt=edit_cnt+1, star_before=?, task_id=?
                      WHERE pkg_id=?""",
                  (n, (str(note).strip() if note is not None else None), now, 旧["star"], tid, pid))
    log_op("顾客", "rating", pid, f"{旧['star']}星", f"{n}星", True, "RATING_EDITED", 为什么, {})
    return dict(ok=True, code="RATING_EDITED", 包裹=pid, 原=旧["star"], 星=n,
                清单=动作, 工单=tid, reason=为什么)


# ── 店长端 ────────────────────────────────────────────────────────────
def close_bad_rating(d, me):
    """店长处理完一张差评工单。**必须写处理记录。**

    业务 2026-09-27:差评归**店长**跟,不进顾问考核。
    """
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 店长角色:
        return _deny(me.get("name"), "ROLE",
                     f"差评由店长跟进,你是「{me.get('role')}」—— 业务 2026-09-27:只给店长看",
                     d.get("pkg") or "—", me.get("role"))
    pid = str(d.get("pkg") or d.get("pkg_id") or "").strip()
    r = _评过的(pid)
    if not r:
        return dict(ok=False, code="NOT_RATED", reason=f"包裹 {pid} 没有评价")
    if not r["task_id"]:
        return dict(ok=False, code="NOT_BAD", reason=f"包裹 {pid} 是 {r['star']} 星,不是差评,没有工单")
    t = rows("SELECT * FROM task WHERE id=?", r["task_id"])
    if t and t[0]["status"] != "待处理":
        return dict(ok=False, code="ALREADY_CLOSED", reason=f"工单 {r['task_id']} 已经是「{t[0]['status']}」")
    能, 话 = R.待办能不能关(d.get("note"))
    if not 能:
        return dict(ok=False, code="NEED_NOTE", reason=话)
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE task SET status='已关闭' WHERE id=?", (r["task_id"],))
        c.execute("UPDATE rating SET handled_at=?, handled_by=?, handle_note=? WHERE pkg_id=?",
                  (now, me.get("no") or me.get("name"), str(d["note"]).strip(), pid))
    log_op(me.get("name"), "task", r["task_id"], "待处理", "已关闭", True, "BAD_RATING_CLOSED",
           str(d["note"]).strip()[:120], {"role": me.get("role"), "pkg": pid})
    return dict(ok=True, code="BAD_RATING_CLOSED", 包裹=pid, 工单=r["task_id"],
                reason=f"工单 {r['task_id']} 已关闭,处理记录记下了")
