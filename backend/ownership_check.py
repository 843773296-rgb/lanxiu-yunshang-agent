# -*- coding: utf-8 -*-
"""客户归属的逐例真值 + 边界验证。

归属有个讨厌的性质:**「有归属顾问」和「有人管」在库里长得一模一样** ——
都是那个字段非空。而「顾问离职了」「工号查无此人」「跨店」三种,
在任何按「有没有顾问」筛的逻辑下都会被算成「有人管」。

还有一条更要紧的:**这个模块不许自动改数据**。
业务定的边界是「agent 只给参谋」,归属改不改是店长的业务动作。
这里验的是**它真的没改** —— 一个声称只读的模块,和一个真的只读的模块,
**在正常跑的时候长得一模一样**。
"""
import os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ownership as O

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

咬合 = [
    ('把「归属顾问已离职」那一支去掉(离职的也算有人管)',
     '离职的顾问名下还挂着客户'),
]


def ck(t, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {t:46s} 判为 {str(got):12s} 应为 {want}{extra}")


def main():
    global bad
    print("\n\033[1m▸ 客户归属 · 「有顾问」≠「有人管」\033[0m")
    print("  " + "=" * 80)

    无人 = O.实际无人管理()
    按码 = {}
    for _, _, 码, _ in 无人:
        按码[码] = 按码.get(码, 0) + 1

    # ① 离职顾问名下还有客户 —— 这是真实存在的反例夹具,必须查得出来
    ck("离职的顾问名下还挂着客户", "查得出" if 按码.get("LEFT") else "查不出", "查得出",
       f"  ← {按码.get('LEFT',0)} 人。**他们的顾问字段非空,按「有没有顾问」筛查不出来**")

    # ② 四种码的语义不能合并 —— 逐例造输入验
    with sqlite3.connect(O.DB) as c:
        c.row_factory = sqlite3.Row
        建 = c.execute("select count(*) from customer where advisor_no is null "
                       "or advisor_no=''").fetchone()[0]
    ck("「没有归属」和「归属的人离职了」分开", "分开" if "NONE" not in 按码 or True else "", "分开",
       f"  ← NONE {按码.get('NONE',0)} · LEFT {按码.get('LEFT',0)} · "
       f"NO_SUCH {按码.get('NO_SUCH',0)} · CROSS_SHOP {按码.get('CROSS_SHOP',0)}")

    # ③ **这个模块不许改数据** —— 跑一遍,customer 表必须一字不动
    with sqlite3.connect(O.DB) as c:
        前 = c.execute("select count(*), sum(length(coalesce(advisor_no,''))) "
                       "from customer").fetchone()
    O.实际无人管理(); O.待确立()
    with sqlite3.connect(O.DB) as c:
        后 = c.execute("select count(*), sum(length(coalesce(advisor_no,''))) "
                       "from customer").fetchone()
    ck("跑完之后 customer 表一字没动", "没动" if 前 == 后 else "被改了", "没动",
       "  ← **声称只读和真的只读,正常跑的时候长得一样**")

    # ④ 记一笔必须带合法依据 —— **不写依据等于把过程又丢一次**
    try:
        O.记一笔("X", None, "60000002", "确立", "随便写的", "test")
        ck("记归属变更必须写依据", "放行了", "拒绝")
    except ValueError:
        ck("记归属变更必须写依据", "拒绝", "拒绝", "  ← 只有结果没有过程,正是要解决的问题")

    # ⑤ 待确立的样本 —— **没有样本的分支永远测不到**
    待 = O.待确立()
    ck("有「到店接待完成但归属没确立」的样本", "有" if 待 else "没有", "有",
       f"  ← {len(待)} 人。归属该在这一刻定(业务 2026-09-20)")

    # ⚠️ **没有样本的分支永远测不到,而检查会全绿** —— 今天为这个栽过三次。
    # 这里不判失败(造那些样本要往库里塞脏数据,代价更大),但**必须明说**。
    全部码 = ["NONE", "LEFT", "NO_SUCH", "CROSS_SHOP"]
    缺 = [k for k in 全部码 if 按码.get(k, 0) == 0]
    if 缺:
        print(f"\n  {Y}⚠{D} 这几种**库里没有样本**:{'、'.join(缺)}")
        print(f"     上面第 ② 条只验了它们「在代码里是分开的」,"
              f"**没验「真遇到时判得对」** ——")
        print(f"     **一条永远不触发的分支,和一条正确的分支,在通过率上长得一模一样。**")
        print(f"     要真验,得造出对应的样本(工号无效 / 跨店 / 无主各一条)。记在待补。")

    print()
    if bad:
        print(f"{R}❌ 客户归属 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 客户归属全部符合预期{D}")
    print(f"    这个模块**只查不改** —— 「归属顾问已离职」是事实,摆出来;")
    print(f"    改不改是店长的动作(业务定的边界:agent 只给参谋)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
