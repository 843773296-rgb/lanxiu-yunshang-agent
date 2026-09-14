#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版师角色的检查 —— **唯一的写工具只能改占比,而且它真的得能改。**

## 为什么这个角色要单独一套检查

版师是这个项目里**第一个「有写工具,但只有一个」的角色**。
别的角色要么全只读(知识库、财务),要么手上有一把写工具(店长、总部运营)。
只有一个写工具的角色有它特有的失败方式,而这两种**在界面上长得一模一样**:

    给多了   他能动的不止占比 —— 版型、商品、订单跟着能改
    给死了   写工具在,但没有一条路走得通 —— 版师以为核过了,库里一个字没变

**第二种更常见,也更难发现。** 加一道闸很容易,而「闸挡得住」不等于
「不该挡的放得行」—— 只挡不放行的功能,和这个功能不存在没有区别,
但它在评测里看起来一切正常(没有报错,只是什么都没发生)。

所以下面每一条**两个方向都测**:该挡的挡住了,该过的过去了。

## 还钉住一个连栽三次的坑

白名单里的 MCP 命名空间**跟着 schema 挂在哪个服务走**,不跟着「它像哪一类」走。
`plan_for_event`、`get_review_queue`、现在是 `piece_ratios` / `set_piece_ratio` ——
三次都写成了 `mcp__kb__`(因为它们讲的是知识库的事),而 schema 在 `SHOP_SCHEMAS` 里。
三次都不报错:白名单里那个名字根本不存在,于是模型手上少两个工具,
**而角色页面照样显示「5 个工具」**。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agentsite")]
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


class 还原:
    """这套检查会**真的改库** —— 不还原的话,跑一次检查就污染一次占比。

    `boundary_audit.不许留痕` 是同一个东西。教训没长成纪律就会在下一个地方
    原样再来一遍,所以凡是「以某个角色去试写」的检查都要包在这里面。
    """
    def __enter__(self):
        c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
        self.bak = c.execute(
            "SELECT pattern,name,ratio,ratio_src,ratio_by,ratio_at,ratio_why "
            "FROM pattern_piece").fetchall()
        c.close(); return self

    def __exit__(self, *a):
        c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
        for r in self.bak:
            c.execute("UPDATE pattern_piece SET ratio=?,ratio_src=?,ratio_by=?,"
                      "ratio_at=?,ratio_why=? WHERE pattern=? AND name=?",
                      (r[2], r[3], r[4], r[5], r[6], r[0], r[1]))
        c.commit(); c.close()
        print("  (占比表已还原到跑之前的样子)")
        return False


def main():
    print("版师角色 · 检查")
    print("=" * 84)
    import api, prompts, sdk, guards
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row

    # ── ① 工具清单:只有一个写的,而且就是它 ──────────────────────────
    tools = sdk._ROLE_TOOLS["pattern"]()
    短 = [t.rsplit("__", 1)[-1] for t in tools]
    写 = sorted(set(短) & set(api.WRITE_TOOLS))
    ck("版师手上只有一个写工具", 写 == ["set_piece_ratio"], len(短),
       f"实际是 {写}" if 写 != ["set_piece_ratio"] else
       "**从 sdk 和 api 两边现算,不手抄** —— 抄一份当天就开始漂")

    # 越权的反面:版型 / 商品 / 订单的写口一个都不该在他手上。
    不该有 = sorted(set(短) & {"save_product", "apply_adjust", "decide_approval",
                              "assign_task", "dispatch_task", "reassign_task",
                              "finish_task", "assign_batch", "dispatch_batch"})
    ck("版型/商品/订单的写口一个都不在版师手上", not 不该有, len(短),
       f"多给了 {不该有}" if 不该有 else "给多余的工具,它就会去用")

    # ── ② 白名单里的名字必须真的挂得上(那个连栽三次的命名空间坑)──────
    暴露 = {f"mcp__kb__{x['name']}" for x in api.KB_SCHEMAS} \
         | {f"mcp__shop__{x['name']}" for x in api.SHOP_SCHEMAS} \
         | {f"mcp__task__{x['name']}" for x in api.SCHEMAS}
    幽灵 = sorted(set(tools) - 暴露)
    ck("版师白名单里的每个名字都真的挂在 MCP 上", not 幽灵, len(tools),
       f"挂不上的 {幽灵} —— **白名单里那个名字根本不存在,而页面照样显示工具数**"
       if 幽灵 else "命名空间跟着 schema 挂在哪个服务走,不跟着「它像哪一类」走")

    # ── ③ 挂了工具就得拿到管它的规矩(P6 的那条,这里对版师再验一遍)──
    _, ids = prompts.assemble("pattern", sdk._have("pattern"))
    ck("版师拿到了管这两个工具的那条规矩", "TL25" in ids, len(ids),
       f"拿到 {ids}")

    # ── ④ 身份闸:两个方向 ────────────────────────────────────────────
    片 = c.execute("SELECT pattern,name,ratio FROM pattern_piece "
                   "WHERE ratio IS NOT NULL AND ratio_src!='版师' "
                   "ORDER BY pattern,name LIMIT 1").fetchone()
    版师 = c.execute("SELECT no,name FROM staff WHERE role='版师' AND status='启用' "
                     "ORDER BY no LIMIT 1").fetchone()
    ck("库里有在职版师", bool(版师), 1 if 版师 else 0,
       f"{版师['no']} {版师['name']}" if 版师 else "没人 —— **角色立了没人进得来**")
    if not (片 and 版师):
        return done()

    with 还原():
        挡 = []
        # ⓐ 没登录 —— 挡
        r = api.set_piece_ratio(片["pattern"], 片["name"], 0.3, "试")
        if not r.get("error"): 挡.append("没登录居然改成了")
        # ⓑ 不是版师 —— 挡
        with api.as_user(dict(no="S001", name="测试店长", role="店长", shop="X")):
            r = api.set_piece_ratio(片["pattern"], 片["name"], 0.3, "试")
        if not r.get("error"): 挡.append("店长居然改得了裁片用料")
        # ⓒ 是版师但没写理由 —— 挡
        # ⚠️ **夹具的形状要和后台真发的一模一样。**
        # 这里原来同时喂了 `no` 和 `id`,而 `/api/me` 只发 `no` ——
        # 工具里读的却是 `id`,于是真实登录下工号那一栏永远是空的,
        # 而这条检查一直是绿的。**夹具比现实宽容一点,检查就测了一个不存在的世界。**
        me = dict(no=版师["no"], name=版师["name"], role="版师", shop="")
        with api.as_user(me):
            r = api.set_piece_ratio(片["pattern"], 片["name"], 0.3, "  ")
        if not r.get("error"): 挡.append("没写理由居然改成了")
        # ⓓ 占比越界 —— 挡
        with api.as_user(me):
            r = api.set_piece_ratio(片["pattern"], 片["name"], 1.4, "量过")
        if not r.get("error"): 挡.append("占比 1.4 居然收了")
        ck("该挡的都挡住了(没登录/不是版师/没理由/越界)", not 挡, 4,
           str(挡) if 挡 else "身份从会话取,**入参里没有身份字段** —— 有的话一句话就能冒名")

        # ⓔ **该过的要过去** —— 这一条比上面四条要紧。
        with api.as_user(me):
            r = api.set_piece_ratio(片["pattern"], 片["name"], 0.3, "按排料图量的")
        过 = bool(r.get("ok"))
        ck("版师自己改得动(只挡不放行 = 这个功能不存在)", 过, 1,
           r.get("error", "") if not 过 else f"{r.get('版型')} / {r.get('折合米数')}")

        # ⓕ 改完查得到是谁改的 —— 「什么钱什么记录都需要有」的同一条
        row = c.execute("SELECT ratio,ratio_src,ratio_by,ratio_at,ratio_why "
                        "FROM pattern_piece WHERE pattern=? AND name=?",
                        (片["pattern"], 片["name"])).fetchone()
        # **工号必须真的在里面** —— 只有姓名的话,同名两个版师就分不开,
        # 而「傅砚青核的」听起来和「60000020 傅砚青核的」一样可信。
        全 = bool(row and row["ratio_src"] == "版师" and row["ratio_by"]
                  and 版师["no"] in (row["ratio_by"] or "")
                  and row["ratio_at"] and row["ratio_why"])
        ck("改过的数查得到是谁、什么时候、为什么", 全, 1,
           f"{row['ratio_by']} / {row['ratio_at']} / {row['ratio_why']}" if 全 else
           f"缺:{dict(row) if row else '没这一行'} —— "
           f"**「版师核过」只说了有人核过,没说是谁、凭什么**")

        # ⓖ 归一:总和回到 1,而**已核过的片不动**
        rows = c.execute("SELECT name,ratio,ratio_src FROM pattern_piece "
                         "WHERE pattern=?", (片["pattern"],)).fetchall()
        和 = round(sum((x["ratio"] or 0) for x in rows), 4)
        ck("改完一片,同版型占比之和仍是 1", abs(和 - 1) < 1e-3, len(rows),
           f"和={和} —— 总和不是 1 的话,分摊出来的米数和整件用料对不上")

        with api.as_user(me):
            api.set_piece_ratio(片["pattern"], rows[-1]["name"]
                                if rows[-1]["name"] != 片["name"] else rows[0]["name"],
                                0.2, "第二片也量过")
        锁 = c.execute("SELECT ratio FROM pattern_piece WHERE pattern=? AND name=?",
                       (片["pattern"], 片["name"])).fetchone()["ratio"]
        ck("再核第二片时,第一片纹丝不动", abs((锁 or 0) - 0.3) < 1e-6, 1,
           f"被挤成了 {锁}" if abs((锁 or 0) - 0.3) >= 1e-6 else
           "**人核过的数不许被自动调** —— 否则先核的白核")

    # ── ④半 隐私边界:版师看得到尺寸和体型,看不到手机号和消费额 ──────
    #
    # 这条边界**不靠提示词,靠工具清单** —— 而「工具清单选对了」这件事
    # 没法靠读代码确认:一个工具的返回里有什么,只有跑一遍才知道。
    # 所以这里把版师的**每一个工具**真跑一次,扫返回里有没有:
    #   · 手机号形状的串(11 位、1 开头)
    #   · 金额 / 消费 / 余额 / 积分 / 等级 这类字段名
    #
    # ⚠️ **扫的是「跑出来的东西」,不是「代码里写了什么」。**
    # 按字段名读源码的话,一个 `SELECT *` 就能绕过去 ——
    # 而这个项目的凭据黑名单当初就是为这个改成**查返回的列名**的。
    import json as _js, re as _re
    # ⚠️ **「客户的钱」和「物料的钱」不是同一件事** —— 第一版把它们写在一张词表里,
    # 于是 `kb_bom` 的**物料金额**被当成了消费额报警。
    # 又是「一列承载两件事」:一张词表同时装了两种不同的敏感性。
    #
    #   客户词  任何工具的返回里都不许有 —— 这是这条边界真正守的东西
    #   钱词    除 kb_bom 外不许有 —— kb_bom 本来就是给版师交叉验用量的,
    #           它报的是**物料成本**(TL07 管着「这不是报价」),不是客户花了多少
    客户词 = ("手机", "phone", "mobile", "身份证", "消费", "余额", "积分", "等级",
              "payable", "received", "实收", "应收", "成交")
    钱词 = ("金额", "amount", "单价", "售价", "报价")
    钱词豁免 = {"kb_bom"}
    手机 = _re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    跑法 = {
        "pattern_queue": lambda: api.pattern_queue(),
        "grading_audit": lambda: api.grading_audit("PT04"),
        "piece_ratios":  lambda: api.piece_ratios("PT06"),
        "kb_pattern":    lambda: api.kb_pattern("PT04"),
        "kb_size":       lambda: api.kb_size("PT04"),
        "kb_bom":        lambda: api.kb_bom("PT04", "M", "MT02"),
        "kb_fit":        lambda: api.kb_fit("C10001", "PT04"),
    }
    读工具 = [t.rsplit("__", 1)[-1] for t in tools
              if t.rsplit("__", 1)[-1] != "set_piece_ratio"]
    漏 = [n for n in 读工具 if n not in 跑法]
    ck("版师的每个读工具都被真跑过一遍", not 漏, len(读工具),
       f"没跑到 {漏} —— **没跑过的工具,它返回什么没人知道**" if 漏 else
       "扫的是跑出来的东西,不是代码里写了什么")
    脏 = []
    with api.as_user(me if 版师 else {}):
        for n in 读工具:
            if n not in 跑法: continue
            try: out = _js.dumps(跑法[n](), ensure_ascii=False)
            except Exception as e:
                脏.append(f"{n} 跑不起来:{type(e).__name__}"); continue
            if 手机.search(out): 脏.append(f"{n} 返回里有手机号形状的串")
            词 = list(客户词) + ([] if n in 钱词豁免 else list(钱词))
            hit = [w for w in 词 if f'"{w}' in out or f'{w}"' in out]
            if hit: 脏.append(f"{n} 返回里有 {hit[:3]}")
    ck("版师拿得到尺寸和体型,拿不到手机号和消费额", not 脏, len(读工具),
       "；".join(脏[:3]) if 脏 else
       "**给多余的字段,它就会去用** —— 这个项目在 allowed_tools 上栽过")

    # ── ⑤ 闸也要两个方向 ──────────────────────────────────────────────
    v1 = guards.pre_tool_verdict("mcp__shop__set_piece_ratio",
                                 dict(pattern="PT06", piece="袖片", ratio=0.3, why="量过"),
                                 prompt="把袖片改成 0.3", state_reads=[], state_writes=[])
    v2 = guards.pre_tool_verdict("mcp__shop__set_piece_ratio",
                                 dict(pattern="PT06", piece="袖片", ratio=0.3, why=""),
                                 prompt="把袖片改成 0.3",
                                 state_reads=["piece_ratios"], state_writes=[])
    v3 = guards.pre_tool_verdict("mcp__shop__set_piece_ratio",
                                 dict(pattern="PT06", piece="袖片", ratio=0.3, why="量过"),
                                 prompt="把袖片改成 0.3",
                                 state_reads=["piece_ratios"], state_writes=[])
    ck("没先看过就改 → 拦下", bool(v1), 1, "" if v1 else "**放行了**")
    ck("没写理由 → 拦下", bool(v2), 1, "" if v2 else "**放行了**")
    ck("看过了、理由也写了 → 放行", v3 is None, 1,
       f"被拦了:{v3}" if v3 else "只挡不放行等于这个功能不存在")
    return done()


def done():
    print()
    if FAIL:
        print(f"\033[31m❌ 版师角色 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 版师角色全部符合预期\033[0m")
    print("    唯一的写工具只能改占比;该挡的挡住了,**该过的也真的过得去**。")


if __name__ == "__main__":
    main()
