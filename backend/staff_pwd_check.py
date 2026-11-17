#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""员工首次登录强制改密 + 重置口令 —— 在库的临时副本上真走一遍(执行手册 W19,2026-11-17)。

## 为什么

auth.py 文件头自己写着「真上线要加首次登录强制改密」;演示口令 lanxiu@2026 是公开的,
真员工拿着公开口令登录、系统又不逼他改,等于每个账号都是公开账号。

## 钉的几件事(全是结构,副本上真调)

    重置   总部运营给员工重置口令 → 回一个临时口令、这个人标记置 1、他原来的会话全下线
    登录   拿临时口令登录成功,who 里带着 must_change_pwd=1;**HTTP 层**:带这个标记打任何写口 → 403 MUST_CHANGE_PWD,
           带客户信息的读也 403;只放 /api/change-password、/api/me、/api/logout
    改密   旧口令错 → 拒;新的太短 / 等于演示口令 / 等于旧的 → 拒;改对 → 标记归 0、当前会话还在、别的会话下线;再打写口 → 不再是 403
    角色   顾问 / 店长调重置 → 拒(11-14 台账第四十五条第四组:改员工权限只总部运营;店长能不能开通 / 停用本店员工**另拍**);不能给自己
    会话文件  两进程并发读改写会话文件要有跨进程锁(fcntl):源码里 _写盘 的调用处都在 _文件锁 里

真库一行不碰:库复制到临时目录,auth / server / api 都指向副本;会话文件跟着库走(auth._文件() 取库旁边),所以也是副本的。
"""
import os, shutil, sqlite3, sys, tempfile, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]

咬合 = [
    ("把 do_POST 里「带首登改密标记只放改密口」那道闸去掉", "带标记打写口 → 403 MUST_CHANGE_PWD"),
    ("让 change_password 不再核对旧口令", "旧口令错 → 拒"),
    ("让 set_temp_password 不置标记", "重置后标记置 1"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:160]) if extra else ''}")
    if not ok: FAIL.append(name)


def run(T):
    import auth, api, oplog, tasks, server, migrate
    for m in (auth, api, oplog, tasks, server): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    migrate.补齐(c, 说=lambda *a, **k: None); c.commit()
    if "must_change_pwd" not in {r["name"] for r in c.execute("PRAGMA table_info(staff)")}:
        ck("副本上补齐迁移后 staff 有 must_change_pwd 列", False); return
    def 人(role, 排除=()):
        q = "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'" + "".join(" AND no!=?" for _ in 排除) + " ORDER BY no LIMIT 1"
        r = c.execute(q, (role, *排除)).fetchone(); return dict(r) if r else None
    总部, 顾问, 店长 = 人("总部运营"), 人("顾问"), 人("店长")
    ck("样本:总部运营 / 顾问 / 店长各一位", all((总部, 顾问, 店长)))
    if not all((总部, 顾问, 店长)): return
    目标 = 人("顾问", 排除=(顾问["no"],))
    ck("样本:另一位顾问当被重置的人", bool(目标))
    if not 目标: return
    from authgate_check import 打一次, 打GET   # 复用那条检查的假 handler:真走 do_POST / do_GET

    # ── 角色 ──
    r1 = server.reset_staff_pwd(目标["no"], me=顾问); r2 = server.reset_staff_pwd(目标["no"], me=店长)
    ck("顾问 / 店长调重置口令 → 拒(只总部运营)", r1.get("code") == "WRONG_ROLE" and r2.get("code") == "WRONG_ROLE", f"{r1.get('code')} / {r2.get('code')}")
    r0 = server.reset_staff_pwd(总部["no"], me=总部)
    ck("总部运营不能重置自己的(要找另一位)", r0.get("code") == "SELF_EDIT", r0.get("code"))
    # ── 重置 ──
    旧tok, _ = auth.login(目标["no"], "lanxiu@2026")
    ck("前提:目标员工能用演示口令登录", bool(旧tok))
    r = server.reset_staff_pwd(目标["no"], me=总部)
    temp = r.get("temp")
    ck("总部运营重置 → 回临时口令、只回这一次", bool(r.get("ok") and temp and len(temp) >= 8),
       json.dumps({k: v for k, v in r.items() if k != "temp"}, ensure_ascii=False)[:120])
    if not temp: return
    标 = c.execute("SELECT must_change_pwd FROM staff WHERE no=?", (目标["no"],)).fetchone()[0]
    ck("重置后标记置 1", 标 == 1, 标)
    ck("重置后他原来的会话全下线", auth.who(旧tok) is None)
    日志 = c.execute("SELECT changes FROM edit_log WHERE obj='员工' AND target=? ORDER BY id DESC LIMIT 1", (目标["no"],)).fetchone()
    ck("重置进了资料编辑日志,而临时口令不在日志里", bool(日志) and temp not in (日志[0] or ""), 日志[0][:80] if 日志 else "没有日志")
    # ── 临时口令登录 → 只放改密口 ──
    tok, who = auth.login(目标["no"], temp)
    ck("临时口令能登录,who 带着首登改密标记", bool(tok) and who.get("must_change_pwd") == 1, who)
    ck_ = f"lx_token={tok}"
    码, 回 = 打一次("/api/staff-perm", {"no": "60000001", "status": "停用"}, cookie=ck_)
    ck("带标记打写口 → 403 MUST_CHANGE_PWD", 码 == 403 and isinstance(回, dict) and 回.get("code") == "MUST_CHANGE_PWD", (码, 回))
    码, 回 = 打GET("/api/orders", cookie=ck_)
    ck("带标记读带客户信息的页 → 也拦(403)", 码 == 403, (码, str(回)[:60]))
    码, 回 = 打GET("/api/me", cookie=ck_)
    ck("/api/me 放行,且回里带标记(登录页靠它弹改密框)", 码 == 200 and isinstance(回, dict) and 回.get("must_change_pwd") == 1, (码, 回))
    # ── 改密 ──
    ok, 说 = auth.change_password(tok, "错的口令", "NewPass!2026"); ck("旧口令错 → 拒", not ok, 说)
    ok, 说 = auth.change_password(tok, temp, "short");            ck("新的太短 → 拒", not ok, 说)
    ok, 说 = auth.change_password(tok, temp, "lanxiu@2026");      ck("新的等于演示口令 → 拒", not ok, 说)
    ok, 说 = auth.change_password(tok, temp, temp);               ck("新的等于旧的 → 拒", not ok, 说)
    码, 回 = 打一次("/api/change-password", {"old": temp, "new": "NewPass!2026"}, cookie=ck_)
    ck("HTTP 改密口:改对 → ok", 码 == 200 and isinstance(回, dict) and 回.get("ok"), (码, 回))
    ck("改对后标记归 0", c.execute("SELECT must_change_pwd FROM staff WHERE no=?", (目标["no"],)).fetchone()[0] == 0)
    ck("改对后当前会话还在、标记跟着归 0", (auth.who(tok) or {}).get("must_change_pwd") == 0, auth.who(tok))
    码, 回 = 打一次("/api/staff-perm", {"no": "60000001", "status": "停用"}, cookie=ck_)
    ck("改完再打写口 → 不再是 403 MUST_CHANGE_PWD", not (isinstance(回, dict) and 回.get("code") == "MUST_CHANGE_PWD"), (码, str(回)[:60]))
    tok2, _ = auth.login(目标["no"], "NewPass!2026")
    ck("新口令能登录、不再带标记", bool(tok2) and (auth.who(tok2) or {}).get("must_change_pwd") == 0)
    tok3, _ = auth.login(目标["no"], temp)
    ck("临时口令作废", not tok3)
    # ── 会话文件锁:源码层 ──
    src = open(os.path.join(HERE, "auth.py"), encoding="utf-8").read()
    写 = src.count("_写盘(") - 1          # 减去 def 那一处
    锁 = src.count("_文件锁()")  - 1      # 减去 def 那一处
    ck("会话文件的读改写都在跨进程文件锁里(源码里每处 _写盘 调用都配着 _文件锁)", "def _文件锁" in src and 锁 >= 写 > 0, f"_写盘 调用 {写} 处,_文件锁 {锁} 处")


def main():
    print("员工首登改密 / 重置口令 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="pwd-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 首登改密 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        return 1
    print(f"\033[32m✅ 首登改密 {N[0]} 条全过\033[0m —— 重置置标记、带标记只放改密口、改对归零、临时口令作废")
    return 0


if __name__ == "__main__":
    sys.exit(main())
