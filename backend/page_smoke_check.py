#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读入口冒烟 —— **每个 GET 能走到的页面函数,都拿真数据真跑一遍。**

## 为什么要有这个

`route_check.py` 已经静态查过「路由指向的 handler 真的存在」。
2026-09-17 一天之内,同一类洞在**六个地方**露出来:

    measure_of / customer_detail   读了已删的 measured_by 列        → KeyError
    aftersale_detail               SQL 里点名已删的 advisor 列      → no such column
    maintain_detail                同上
    appt_detail                    SQL 用 a.*,取值时才炸           → KeyError
    export_csv("customers")        SQL 里点名已删的 advisor 列      → no such column
    export_csv("oplog")            按的是早就不存在的老 schema       → no such column

**六处全绿地躺在门禁里**:99 步 + CI 全绿,没有一条检查发现。

> **「handler 存在」和「handler 跑得起来」是两件事。**
> 静态检查看得见前者,看不见后者 —— 而它们在代码里长得一模一样。

最后那条尤其说明问题:`oplog` 导出按的是一个**早就不存在的 schema**,
也就是说**它从上线起就没被跑过一次**。没有人会发现,直到有人真去点那个按钮。

## 只碰读的

冒烟只调 `do_GET` 能走到的函数。**写接口一律不碰** —— 一个会往库里写东西的
冒烟检查,跑一次脏一次,而脏了之后别的检查会红,红的原因却和真问题无关。
`export_csv` 是特例:它带 `actor` 参数看着像会记日志,实测**库里一行没变**,
所以放进来了 —— **实测,不是看着像。**

## 判据

对每个入口:拿库里**真实存在**的参数调它,要求

  1. 不抛异常;
  2. 返回的不是 `{"error": ...}` —— 拿真参数还报「不存在」,说明查法和存法对不上;
  3. 返回的不是空的。

## 那张对照表是手写的,所以它自己也要被查

`用例` 是手写的。手写的东西会漂:新加一个页面而没往表里加一行,
这道检查就**悄悄少验一个入口**,而它照样全绿 —— 正是今天这六个洞的处境。

所以第一条检查是「**`do_GET` 能走到的模块级函数,要么在用例表里,要么在豁免表里**」,
两张表都从源码现推,**把「漏了一行」从静默变成红的**。
"""
import ast, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402

DB = os.path.join(HERE, "lanxiu.db")

# 取一个真实参数:("SQL", 语句) 在跑的时候现查;别的照原样传。
def SQL(s): return ("SQL", s)

# 入口 → 一组参数。一个入口可以有多组(export_csv 四种导出各算一次)。
用例 = {
    # ── 详情页:参数是一个真实 id ───────────────────────────────────
    "task_detail":      [(SQL("SELECT id FROM task LIMIT 1"),)],
    "shop_detail":      [(SQL("SELECT code FROM shop LIMIT 1"),)],
    "product_detail":   [(SQL("SELECT spu FROM product LIMIT 1"),)],
    "activity_detail":  [(SQL("SELECT code FROM activity LIMIT 1"),)],
    "page_detail":      [(SQL("SELECT code FROM page LIMIT 1"),)],
    "aftersale_detail": [(SQL("SELECT id FROM aftersale LIMIT 1"),)],
    "maintain_detail":  [(SQL("SELECT id FROM maintain LIMIT 1"),)],
    # 这一个是整件事的由来:量体那一段读了一个已经删掉的列
    "customer_detail":  [(SQL("SELECT customer_id FROM measure_rec LIMIT 1"),)],
    "appt_detail":      [(SQL("SELECT id FROM appointment LIMIT 1"),)],
    "craft_doc":        [(SQL("SELECT id FROM ordr WHERE kind='定制品订单' LIMIT 1"),)],
    # 订单日志:**挑一张分批发的单**(两个包裹)—— 一单一个包裹的老单跑不到「多包裹」那条路
    "order_log_page":   [(SQL("SELECT order_id FROM pkg WHERE void_at IS NULL GROUP BY order_id "
                              "HAVING COUNT(*)>1 LIMIT 1"),),
                         (SQL("SELECT id FROM ordr WHERE kind='定制品订单' AND status='完成' LIMIT 1"),)],

    # ── 列表页与只读视图:空查询 = 用户刚打开那一页 ──────────────────
    "activity_list":    [({},)], "aftersale_list":  [({},)], "appt_list_q":   [({},)],
    "approval_list":    [({},)], "content_list":    [({},)], "customer_list": [({},)],
    "download_list":    [({},)], "guide_perf":      [({},)], "factory_feed_page": [({},)], "invite_list":   [({},)],
    "kb_search":        [({},)], "maintain_list":   [({},)], "measure_items": [({},)],
    "measure_tpls":     [({},)], "order_list":      [({},)], "page_list":     [({},)],
    "product_list":     [({},)], "schedule_list":   [({},)], "shop_list":     [({},)],
    "staff_list":       [({},)], "stock_list":      [({},)], "stock_log_list":[({},)],
    "syscode_list":     [({},)], "task_list":       [({},)],
    "appt_list":        [()],    "approvals":       [()],    "category_tree": [()],
    "combo_matrix":     [()],    "lifecycle_page":  [()],    "op_logs":       [()],
    "scheme_list":      [()],    "workbench":       [()],

    # ── 导出:四种各跑一次。**少跑一种就少发现一个 bug** —— oplog 那条
    #    正是只有真跑到才会露出来的。外加一个不存在的 kind,验它不给空文件。
    "export_csv": [("customers", {}), ("orders", {}), ("workorders", {}), ("oplog", {}),
                   ("根本没有这种导出", {})],
}

# 豁免:不是页面入口,是工具函数。**每一条都要写清为什么**,
# 否则这张表会变成「懒得写用例就往里扔」的垃圾桶。
豁免 = {
    "_agent":   "取当前 agent 配置的小工具,不是页面",
    "_simple":  "列表页的公共实现,由上面那些 *_list 覆盖到",
    "填顾问名": "按工号填名字的工具,advisor_name_check 专门盯它",
    # 下面这几个 do_POST 也在用,不是「某个页面」——
    # 它们坏了会让**一大片**一起红,不需要单独冒烟。
    "rows":     "取数的底层函数,每个页面都在用",
    "_me":      "从会话取当前登录人",
    "_u":       "解 URL 参数",
    "_eval":    "评测入口的取数,不是页面",
    "_truths":  "truth 表的读口,backend/selftest.py 专门盯它(不许经工具层暴露)",
}

咬合 = [
    ('把 measure_of 那处修复整个退回去(既不造 measured_by 字段,也不兜底)—— 这正是 2026-09-17 之前的样子',
     '每个只读入口都拿真数据跑得通'),
    ('从用例表里删掉 customer_detail 那一行(某个页面从此不被验,而检查照样绿)',
     'do_GET 走得到的函数,都在用例表或豁免表里'),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def do_get_里调的():
    """从源码现推 `do_GET` 里直接调用的模块级函数。

    **不手抄一份清单** —— 手抄件不会自己告诉你它旧了,而这道检查的全部意义
    就是「新加的入口不许悄悄漏掉」。带点的调用(`self.x()`)不算:
    属性要运行时才知道,静态判会误报。
    """
    tree = ast.parse(open(os.path.join(HERE, "server.py"), encoding="utf-8").read())
    定义 = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "do_GET":
            return sorted({x.func.id for x in ast.walk(n)
                           if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                           and x.func.id in 定义})
    return []


def main():
    print("只读入口冒烟 · 拿真数据真跑一遍")
    print("=" * 96)

    # ── ① 对照表不许漏 ────────────────────────────────────────────────
    入口 = do_get_里调的()
    漏 = [f for f in 入口 if f not in 用例 and f not in 豁免]
    多 = [f for f in 用例 if f not in 入口]
    ck("do_GET 走得到的函数,都在用例表或豁免表里", not 漏 and not 多, len(入口),
       (f"漏了 {漏} " if 漏 else "") + (f"表里多出 {多}" if 多 else "") or
       "**漏一行不会报错,只会让某个入口从此不被验** —— 所以先查这个")

    # ── ② 每个都拿真数据跑一遍 ────────────────────────────────────────
    c = sqlite3.connect(DB)
    坏, 跑了 = [], 0
    for fn in sorted(用例):
        f = getattr(server, fn, None)
        if f is None:
            坏.append(f"{fn}:server 里没有这个函数"); continue
        for args in 用例[fn]:
            真参 = []
            缺 = False
            for a in args:
                if isinstance(a, tuple) and len(a) == 2 and a[0] == "SQL":
                    row = c.execute(a[1]).fetchone()
                    if not row or row[0] is None:
                        坏.append(f"{fn}:库里取不到真参数(`{a[1]}`)—— **拿不到样本不算通过**")
                        缺 = True; break
                    真参.append(row[0])
                else:
                    真参.append(a)
            if 缺:
                continue
            跑了 += 1
            标 = f"{fn}({', '.join(repr(x)[:16] for x in 真参)})"
            try:
                out = f(*真参)
            except Exception as e:
                坏.append(f"{标} 抛了 {type(e).__name__}: {e}"); continue
            if isinstance(out, dict) and out.get("error"):
                坏.append(f"{标} 拿真参数却返回 error:{out['error']}")
            elif not out:
                坏.append(f"{标} 返回空 —— 真实存在的参数不该查不到东西")
    c.close()

    ck("每个只读入口都拿真数据跑得通", not 坏, 跑了,
       ("；".join(坏[:3]) if 坏 else
        "**页面炸了和页面空着,在静态检查眼里一模一样** —— 只有真跑一次分得开"))

    print("=" * 96)
    if FAIL:
        print(f"\033[31m❌ {len(FAIL)} 条没过:{FAIL}\033[0m")
        return 1
    print(f"\033[32m✅ {跑了} 次调用、{len(入口)} 个入口全部拿真数据跑通\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
