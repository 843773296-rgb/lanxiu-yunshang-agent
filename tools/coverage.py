#!/usr/bin/env python3
"""业务覆盖对账 —— 给「覆盖」这个词一个真实的分母。

## 为什么要有这个

`CLAUDE.md` 里同一节隔了几行写着两句话:

  · **业务覆盖 18/18**,三个角色的问题在 chat 里都能问
  · 缺工具的业务面还有几块……**59 张表里一半以上有数据但没工具**

两句都没错 —— 因为它们说的是**不同层的覆盖**,而「18」这个分母只数了第一阶段。
**「18/18」是个满分,而它的分母是手写的、只增不减、不会自己变旧,只会悄悄变旧。**

所以这里把「覆盖」拆成三层,每一层的分子分母都**自动算**:

  第一层 有数据吗   ← 直接数库里的行
  第二层 有工具读吗 ← 解析工具函数里的 SQL(FROM / JOIN 到哪张表)
  第三层 有评测题吗 ← 解析评测用例里的 need_tool(...),再顺着工具映回表

## 唯一需要人给的东西,以及它必须被守住

**「哪些表属于哪个业务面」是业务概念,不是数据事实**,只能人给。
但**「有没有漏」必须自动查** —— 新增一张表却没归类,这里直接红。
这是这份对账表和那句手写「18/18」的**全部差别**:
手写的数字不会告诉你它旧了,而一条会红的检查会。

## 已知的口径限制(写在这里,免得被当成精确值)

· 第三层是**下界**:有些评测题**故意**不要求调工具
  (比如「加钱能不能催织造」——拒绝的依据是工序性质,查产能反而多余),
  这类题在这里数不到。所以第三层只回答「这块有没有被测过」,不回答「测得够不够」。
· 工具→表 靠正则读 SQL,读不到动态拼出来的表名。
"""
import ast, io, os, re, sqlite3, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

# ── 唯一需要人给的:表 → 业务面 ────────────────────────────────
# 改这里就改了整份报告的口径。漏一张表会红。
FACES = {
    "客户与账户": ["customer", "account", "wearer", "consent", "phone_alias", "member_bind"],
    "会员与营销": ["level_cfg", "points_log", "invite_code", "activity", "activity_cost", "tag"],
    "订单与支付": ["ordr", "ordr_item", "deposit", "payment_flow", "refund_trace", "aftersale",
                   "refund_trace", "triage"],
    "商品与库存": ["product", "product_custom", "sku", "size_spec", "category", "stock_log",
                   "material", "craft", "craft_bom", "craft_combo", "pattern", "pattern_bom",
                   "pattern_piece", "scheme"],
    "量体与成长": ["measure_item", "measure_rec", "measure_tpl", "tpl_item", "body_feature",
                   "growth_forecast"],
    # schedule_file 是完整性检查第一次跑就抓到的:另一条线新加了表,而口径没跟着更新。
    # **这正是这份对账表和手写「18/18」的全部差别** —— 手写的数字不会告诉你它旧了。
    "工坊与排产": ["workorder", "artisan", "schedule", "schedule_file", "maintain",
                   "delivery_notice"],
    "门店与人员": ["shop", "staff", "appointment", "followup", "task", "approval"],
    "内容与页面": ["content", "page", "page_block", "kb_table", "sys_code"],
    "系统与日志": ["op_log", "download_task", "truth", "sqlite_sequence"],
}


def tables_with_rows():
    c = sqlite3.connect(DB)
    out = {}
    for (t,) in c.execute("select name from sqlite_master where type='table'"):
        try: out[t] = c.execute(f'select count(*) from "{t}"').fetchone()[0]
        except Exception: out[t] = 0
    c.close()
    return out


def tool_to_tables():
    """每个工具读了哪些表。**运行时给「有哪些」,源码给「里面写了什么」,各取所长。**

    栽了两次才对:
    ① AST 只读 `TOOLS={...}` 那个字面量 → 只认出 **5 个**,而运行时有 **34 个**。
       注册方式不止一种,静态解析永远追不全。
    ② 改成 `inspect.getsource(工具函数)` → **0 张表**。
       因为工具被一层**脱敏装饰器**包过,拿到的是 `def wrap(*a, **kw)`,不是原函数。
       (装饰器保留了 `__name__` 但没用 `functools.wraps`,所以 `__wrapped__` 也没有。)

    两次的表现完全一样:**表照常打印,只是数字是假的**。
    第一次是 10%、第二次是 0% —— 而 0% 反而更容易被发现,10% 看起来像个结论。
    **越像结论的错误数字越危险。**

    最终:工具名单问运行时(权威),函数体从 api.py 的源码里按名字找(绕开装饰器)。
    """
    sys.path[:0] = [os.path.join(ROOT, "backend"), ROOT]
    import api
    src = io.open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8").read()
    bodies = {}
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef):
            bodies.setdefault(n.name, ast.get_source_segment(src, n) or "")
    out = {}
    for name in getattr(api, "TOOLS", {}):
        seg = bodies.get(name, "")
        tabs = set(re.findall(r"\bFROM\s+([A-Za-z_]\w*)", seg, re.I))
        tabs |= set(re.findall(r"\bJOIN\s+([A-Za-z_]\w*)", seg, re.I))
        out[name] = {t for t in tabs if t.lower() != "select"}
    return out


def eval_tool_hits():
    """每个工具被多少道评测题**明确要求**调用 —— 解析 need_tool(...)。"""
    hits = collections.Counter()
    files = 0
    for fn in sorted(os.listdir(os.path.join(ROOT, "agent"))):
        if not (fn.endswith("_eval.py")): continue
        files += 1
        src = io.open(os.path.join(ROOT, "agent", fn), encoding="utf-8").read()
        for m in re.finditer(r"need_tool\(([^)]*)\)", src):
            for t in re.findall(r'"([A-Za-z_]\w*)"', m.group(1)):
                hits[t] += 1
    return hits, files


def main():
    rows = tables_with_rows()
    t2t = tool_to_tables()
    hits, nfiles = eval_tool_hits()

    # ---- 完整性:每张表都必须归类。**这条是这份报告和手写「18/18」的全部差别。** ----
    assigned = {t for ts in FACES.values() for t in ts}
    missing = sorted(set(rows) - assigned)
    ghost = sorted(assigned - set(rows))

    tab2face = {t: f for f, ts in FACES.items() for t in ts}
    face2tools = collections.defaultdict(set)
    for tool, tabs in t2t.items():
        for t in tabs:
            if t in tab2face: face2tools[tab2face[t]].add(tool)

    print(f"业务覆盖对账 · {len(rows)} 张表 / {len(t2t)} 个工具 / {nfiles} 套评测\n")
    hdr = f'{"业务面":<12}{"有数据的表":>12}{"有工具读":>10}{"被评测要求":>12}'
    print(hdr); print("─" * 50)
    tot = collections.Counter()
    for face, tabs in FACES.items():
        live = [t for t in tabs if rows.get(t, 0) > 0]
        covered = [t for t in tabs if any(t in v for v in t2t.values())]
        tools = sorted(face2tools.get(face, []))
        tested = [x for x in tools if hits.get(x)]
        tot["表"] += len(live); tot["有工具"] += len(covered)
        mark = "✅" if tested else ("⚠️" if tools else "❌")
        print(f'{face:<12}{len(live):>10} 张{len(covered):>8} 张'
              f'{(str(len(tested)) + "/" + str(len(tools)) + " 个工具") if tools else "—":>14}  {mark}')
    print("─" * 50)
    print(f'{"合计":<12}{tot["表"]:>10} 张{tot["有工具"]:>8} 张'
          f'   有数据的表里 **{tot["有工具"] * 100 // max(tot["表"], 1)}%** 有工具读得到\n')

    if missing:
        print(f"❌ {len(missing)} 张表没归类 —— **新增了表却没更新口径**:{missing}")
    if ghost:
        print(f"⚠️ {len(ghost)} 个表名在分类里但库里没有(改名或删表了):{ghost}")
    if not missing and not ghost:
        print("✅ 每张表都归了类,分类里也没有幽灵表名")

    print("\n没有任何工具读得到的业务面(有数据、但智能体看不见):")
    for face, tabs in FACES.items():
        live = [t for t in tabs if rows.get(t, 0) > 0]
        blind = [t for t in live if not any(t in v for v in t2t.values())]
        if blind: print(f'  {face}:{len(blind)}/{len(live)} 张 → {blind[:6]}')
    # 给人读的一份,写到 .feynman/ 里
    out = os.path.join(ROOT, ".feynman", "coverage.md")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("# 业务覆盖对账\n\n")
        f.write("> 三层覆盖各算各的分母,全部自动扫出来。\n"
                "> 唯一需要人给的是「哪些表属于哪个业务面」——**而漏归类会红**。\n\n")
        f.write("| 业务面 | 有数据的表 | 有工具读得到 | 被评测要求调的工具 | 智能体看不见的表 |\n")
        f.write("|---|---:|---:|---:|---|\n")
        for face, tabs in FACES.items():
            live = [t for t in tabs if rows.get(t, 0) > 0]
            cov = [t for t in live if any(t in v for v in t2t.values())]
            tools = sorted(face2tools.get(face, []))
            tested = [x for x in tools if hits.get(x)]
            blind = [t for t in live if t not in cov]
            f.write(f"| {face} | {len(live)} | {len(cov)} | "
                    f"{len(tested)}/{len(tools) or '—'} | "
                    f"{('、'.join(blind[:5]) + ('…' if len(blind) > 5 else '')) or '—'} |\n")
        f.write(f"\n**合计:{tot['表']} 张有数据的表,{tot['有工具']} 张有工具读得到"
                f"({tot['有工具'] * 100 // max(tot['表'], 1)}%)**\n\n")
        f.write("## 口径限制(免得被当成精确值)\n\n"
                "- 第三层是**下界**:有些评测题故意不要求调工具,这里数不到。\n"
                "- 工具→表 靠读 SQL,读不到动态拼出来的表名。\n"
                "- 「有工具读得到」不等于「答得对」——那是评测的事,不是这张表的事。\n")
    print(f"\n给人读的一份 → {out}")
    return 1 if (missing or ghost) else 0


if __name__ == "__main__":
    sys.exit(main())
