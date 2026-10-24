# -*- coding: utf-8 -*-
"""执行记录(`/spans`)谁能看 · 逐例(2026-10-24 实测:原来不登录就给 200,登录后谁都能看全公司的)。

真调 `sessions.能看执行记录吗`(app.py 的 /spans 只调它,判定只有这一份);会话归属写在临时文件里,不碰真的会话表。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("单条记录不查会话归属(谁登录了都给看)", "顾问看别人会话的执行记录 → 404(不说「有这条但你没权限」)"),
    ("不登录也放行", "没登录 → 401"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {附}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def main():
    print("执行记录(/spans)谁能看 · 逐例")
    import sessions as S
    原 = S.PATH
    S.PATH = os.path.join(tempfile.mkdtemp(), "sessions.json")
    try:
        顾问 = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}
        别人 = {"no": "60000003", "name": "周叙", "role": "顾问", "shop": "SH001 静安旗舰店"}
        总部 = {"no": "60000008", "name": "魏欣新", "role": "总部运营", "shop": None}
        S.own("会话-林岚", 顾问)
        S.own("会话-周叙", 别人)
        判 = S.能看执行记录吗
        ck("没登录 → 401", 判(None, 会话号="会话-林岚")[:2] == (False, 401) and 判({}, 列全部=True)[:2] == (False, 401),
           (判(None, 会话号="会话-林岚"), 判({}, 列全部=True)))
        ck("顾问列全部对话 → 403(只给总部运营)", 判(顾问, 列全部=True)[:2] == (False, 403), 判(顾问, 列全部=True))
        ck("总部运营列全部 → 可以", 判(总部, 列全部=True)[0] is True)
        ck("顾问看**自己会话**的那一条 → 可以", 判(顾问, 会话号="会话-林岚")[0] is True, 判(顾问, 会话号="会话-林岚"))
        r = 判(顾问, 会话号="会话-周叙")
        ck("顾问看别人会话的执行记录 → 404(不说「有这条但你没权限」)", r[:2] == (False, 404) and "别人" in r[2], r)
        r = 判(dict(顾问, role="店长"), 会话号="会话-林岚")
        ck("自己的会话,但**角色变了** → 拒(旧记录里是按原来权限取到的数据)", r[0] is False, r)
        r = 判(顾问, 会话号="查不到的会话")
        ck("查不到归属的会话 → 拒,不猜", r[0] is False, r)
        r = 判(顾问, 会话号=None)
        ck("不属于任何会话的记录(评测 / 试跑)→ 顾问看不到", r[:2] == (False, 404), r)
        ck("总部运营看别人会话的 → 可以;看查不到归属的 → 照样拒",
           判(总部, 会话号="会话-周叙")[0] is True and 判(总部, 会话号="查不到的会话")[0] is False)
    finally:
        S.PATH = 原
    # 接线:/spans 必须调这个判定 —— 单条、列表两处都要
    src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    段 = src[src.index('if p.startswith("/spans"):'):src.index('if p == "/healthz":')]
    ck("app.py 的 /spans 两处都调了 能看执行记录吗(列表一处 + 单条一处)", 段.count("能看执行记录吗(") == 2, 段.count("能看执行记录吗("))
    print()
    if 坏:
        print(f"{R}❌ 执行记录权限 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 执行记录:没登录 401、只看自己会话的、列全部只给总部运营(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
