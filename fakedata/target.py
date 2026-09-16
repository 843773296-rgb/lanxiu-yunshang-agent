#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定向造数 —— **先说「我要让这条检查红」,再倒推该造什么数据。**

## 这和「试灌」正好相反

    试灌(oracle.py)   造完 → 跑检查 → 红了就二分定位是哪张表干的      正向
    定向造数(这里)     **先指定要红哪一条** → 倒推造什么 → 造出来 → 真跑验证   反向

**这是「数据生成器」和「测试数据系统」的分水岭。** 前者给你一堆合法数据;
后者给你一个**能复现某个场景**的数据。测试真正要的是后者:
「造一条能触发这条规则的单子」,而不是「造一万条合法的单子,希望里面碰巧有」。

## 成功判据必须是硬的,否则最笨的办法也能「成功」

    ① 目标那条检查**从绿变红**
    ② **其余检查不许跟着红**

只有 ① 的话,把库清空就能让任何检查红 —— 那不叫造出了触发数据,
叫**把库搞坏了**。② 是这一层真正的难点,也是它值钱的地方。

## 检查是黑盒,不解析它怎么写的

各家写法不一样(这个项目里就有 `rule(编号, 描述, 违规行, 为什么)` 和
`ck(名字, 成立与否, 样本量, 说明)` 两种),解析它们是无底洞。
所以这里只要求两件事:**能跑这条命令**、**能在输出里认出「这一条」红没红**(靠标志串)。

理解「这条检查在说什么」交给模型 —— 把**源码片段**喂给它当线索。
而模型说得对不对,由**真跑一遍**裁决。

## 不投票

推断关系那层要跑 N 遍投票,是因为**对错没法当场验**。
这里能当场验:造完跑一遍,红了就是红了。**能真验的东西不靠投票** ——
投票只是在没有裁判时的替代品,有裁判就该用裁判。

## 失败要有声音

造不出来就报「造不出来」,**不许把「没触发」说成「触发了」**,
也不许把「顺手弄红了别的」算成成功。每一轮失败的原因都要列出来,
因为「试了三轮没成功」和「试了三轮每轮都因为同一个原因失败」是两回事。

## 现在不做什么

- **不追求最小触发集**。能触发就行,不保证造的行数最少(要最小化可以接
  `oracle.ddmin` 那套,但那是另一件事)。
- **不改被测代码**,也不做「让它绿」—— 那是修 bug,不是造数据。
- **只走数据库直连**。接口驱动那条路的定向构造在 `probe.py`,是另一套。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "agent"))   # v1 是唯一发请求口,记录仪自动接在它上面
import oracle as O


# ── 一、目标:一条命令 + 一个能在输出里认出「这一条」的标志 ──────────────
def 目标(命令, 标志, 源码=None, 行=None):
    """`标志` 是检查输出里代表这一条的字符串(编号 `A3`、或检查名的一段)。

    `源码`/`行`:给模型看的线索,不是给程序解析的。
    """
    return {"命令": 命令, "标志": 标志, "源码": 源码, "行": 行}


def 读线索(路径, 标志, 前后=30):
    """把源码里提到这个标志的那一段抠出来,**给模型当线索用**。

    程序不解析它 —— 解析各家检查的写法是无底洞,而模型读一段源码正是它擅长的。
    """
    if not os.path.isfile(路径):
        return None
    src = open(路径, encoding="utf-8").read().splitlines()
    命中 = [i for i, l in enumerate(src) if 标志 in l]
    if not 命中:
        return None
    i = 命中[0]
    return "\n".join(src[max(0, i - 2): i + 前后])


def 红了(结果, 标志):
    """这一条红没红。**只看带失败记号的那几行里有没有这个标志** ——
    检查输出里绿的行也会提到编号,按「全文里有没有」判会永远说红。
    """
    return any(标志 in l for l in 结果.bad)


# ── 二、起草:模型只出规则,程序造数据 ──────────────────────────────────
SYSTEM = """你是测试数据设计员。给你一段检查代码和一份数据库结构,
你要说出:**往库里加哪些行,才会让这条检查红。**

只输出 JSON,形如:
{"要造的": [{"表": "account", "行": {"id": "A-TEST-1", "status": "正常", "phone": "13900000001"}}],
 "为什么会红": "这条检查要求每个账户至少有一个着装人,而这个新账户没有",
 "没把握的": ["phone 是否唯一约束不确定"]}

硬要求:
1. **只加行,不改也不删**已有的行 —— 工具只会 INSERT。
2. 每一行必须给出该表所有 NOT NULL 且无默认值的列;整数自增主键可以不给。
3. 值要么是字面量,要么是 {"引用": "表.列"} —— 表示「从库里已有的取一个」。
4. **不要试图靠把数据搞乱来让它红**(比如插入一大堆垃圾行) ——
   其余检查跟着红的话,这次就算失败。要的是**精确触发这一条**。
5. 造不出来就返回 {"要造的": [], "造不出来的理由": "..."} —— **不许编**。"""


def 结构摘要(conn, sc, 表名=None, 每表列上限=40):
    """给模型看的结构:表、列、类型、是否必填、主键、已有行数。**都是事实,不是猜的。**"""
    out = {}
    for t, tb in sc.tables.items():
        if 表名 and t not in 表名:
            continue
        try:
            n = conn.q(f"select count(*) from {conn.ident(t)}")[0][0]
        except Exception:
            n = None
        out[t] = {"行数": n, "主键": tb.pk,
                  # 类型给两样:原始类型名 + 工具归一化的四类(int/real/text/datetime)。
                  # 原始名五花八门(BIGINT/VARCHAR/DECIMAL),归一化那个对「该填什么值」更有用。
                  "列": [{"名": c.name, "类型": c.type_raw, "归类": c.kind,
                          "必填": not c.nullable, "默认": c.default, "唯一": c.unique,
                          "注释": (c.comment or "")[:40]}
                         for c in tb.columns[:每表列上限]]}
    return out


def 起草(目标项, 摘要, 失败反馈=None, model=None, log=print):
    """问模型:要让这条红,该造什么。**返回草案,不落库。**"""
    import v1   # 唯一发请求口:走它,调用才会进记录仪(trace_check 强制这一条)
    payload = {"检查命令": 目标项["命令"], "这一条的标志": 目标项["标志"],
               "检查代码片段": 目标项.get("源码"), "数据库结构": 摘要}
    if 失败反馈:
        # **把失败原样喂回去。** 「试了三轮」和「三轮都因为同一个原因失败」是两回事,
        # 不把原因带回去,模型只会把同一个草案换个写法再交一遍。
        payload["上几轮为什么没成功"] = 失败反馈
    pv = v1.provider()
    resp = v1.call(pv, dict(model=model or pv["model"], max_tokens=8000, system=SYSTEM,
                            messages=[{"role": "user",
                                       "content": json.dumps(payload, ensure_ascii=False)[:120000]}]),
                   purpose="假数据工厂·定向造数", gen="工具")
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    if resp.get("stop_reason") == "max_tokens":
        raise SystemExit("模型回答被 max_tokens 截断 —— 这不是格式问题,是配置不够。")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"要造的": [], "造不出来的理由": f"模型没给出 JSON:{text[:200]}"}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        return {"要造的": [], "造不出来的理由": f"JSON 解析失败:{e}"}


# ── 三、造:按草案精确插几行,记下来以便删干净 ──────────────────────────
def _取引用(conn, 表列):
    t, _, c = 表列.partition(".")
    rows = conn.q(f"select {conn.ident(c)} from {conn.ident(t)} "
                  f"where {conn.ident(c)} is not null limit 1")
    return rows[0][0] if rows else None


def 按草案造(conn, 草案, sc):
    """把草案落成真实的行。返回 (灌了几行, 回滚凭据)。**不 commit** —— 交给调用方。"""
    凭据 = []
    n = 0
    for it in 草案.get("要造的", []):
        t = it.get("表")
        行 = dict(it.get("行") or {})
        if not t or t not in sc.tables or not 行:
            continue
        for k, v in list(行.items()):
            if isinstance(v, dict) and "引用" in v:
                行[k] = _取引用(conn, v["引用"])
        cols = [c for c in 行 if sc.tables[t].col(c)]
        if not cols:
            continue
        ph = ", ".join([conn.ph] * len(cols))
        cur = conn.exec(f"insert into {conn.ident(t)} ({', '.join(conn.ident(c) for c in cols)}) "
                        f"values ({ph})", tuple(行[c] for c in cols))
        pk = sc.tables[t].pk[0] if sc.tables[t].pk else None
        v = 行.get(pk) if pk else None
        if pk and v is None:
            v = getattr(cur, "lastrowid", None)
        凭据.append({"表": t, "pk": pk, "值": v})
        n += 1
    return n, 凭据


def 删干净(conn, 凭据):
    for x in reversed(凭据):
        if x["pk"] is None or x["值"] is None:
            continue
        conn.exec(f"delete from {conn.ident(x['表'])} where {conn.ident(x['pk'])} = {conn.ph}",
                  (x["值"],))
    conn.commit()


# ── 四、验:真跑一遍,两条判据都要过 ──────────────────────────────────
def 验一轮(conn, sc, 草案, 目标项, 陪跑, base, root=ROOT, env=None, log=lambda *a: None):
    """造 → 跑目标检查 → 跑陪跑检查 → 判定 → **不管成没成都删干净**。

    返回 {"成功": bool, "为什么": str, "灌了几行": int, "连带弄红的": [...]}。
    """
    if not 草案.get("要造的"):
        return {"成功": False, "为什么": f"模型说造不出来:{草案.get('造不出来的理由', '(没给理由)')}",
                "灌了几行": 0, "连带弄红的": []}
    n, 凭据 = 0, []
    try:
        n, 凭据 = 按草案造(conn, 草案, sc)
        conn.commit()
        if not n:
            return {"成功": False, "为什么": "草案里没有一行能落库(表名或列名对不上)",
                    "灌了几行": 0, "连带弄红的": []}
        目标结果 = O.run_check(目标项["命令"], root, env=env)
        中了 = 红了(目标结果, 目标项["标志"])
        after = O.run_all(陪跑, root, log, env) if 陪跑 else {}
        连带 = [c for c, _新增, _e0, _e1 in O.变差(base, after)]
    finally:
        删干净(conn, 凭据)
    if not 中了:
        return {"成功": False, "为什么": f"灌了 {n} 行,但这一条**没红** —— 没触发就是没触发",
                "灌了几行": n, "连带弄红的": 连带}
    if 连带:
        # **这一条才是难点。** 把库搞坏能让任何检查红,那不叫触发,叫弄坏。
        return {"成功": False, "为什么": f"这一条红了,但**顺带弄红了 {len(连带)} 条别的** —— "
                                        f"要的是精确触发,不是把库搞乱",
                "灌了几行": n, "连带弄红的": 连带}
    return {"成功": True, "为什么": f"灌了 {n} 行,这一条红了,其余检查没变",
            "灌了几行": n, "连带弄红的": []}


def 打(conn, sc, 目标项, 陪跑=(), 轮数=3, 起草器=起草, root=ROOT, env=None, log=print,
      表名=None):
    """整条闭环:起草 → 造 → 验 → 失败就把原因喂回去再来一轮。

    `起草器` 可换 —— 自测里注入一个固定的假模型,**离线就能验闭环本身对不对**。
    """
    报告 = {"目标": 目标项["标志"], "命令": 目标项["命令"], "轮": [], "成功": False}
    log(f"定向造数:要让「{目标项['标志']}」红")
    base = O.run_all(list(陪跑) + [目标项["命令"]], root, log, env) if 陪跑 or True else {}
    if 红了(base.get(目标项["命令"], O.检查结果("", 0, [], "", 0)), 目标项["标志"]):
        log("  ⚠️ **它本来就是红的** —— 那这次造不出任何信息(「本来就红」和「被我造红了」长得一样)")
        报告["本来就红"] = True
        return 报告
    摘要 = 结构摘要(conn, sc, 表名)
    反馈 = []
    for i in range(1, 轮数 + 1):
        log(f"  第 {i} 轮:问模型要造什么")
        草案 = 起草器(目标项, 摘要, 反馈 or None)
        r = 验一轮(conn, sc, 草案, 目标项, list(陪跑), base, root, env, log)
        r["草案"] = 草案
        报告["轮"].append(r)
        log(f"    {'✅' if r['成功'] else '❌'} {r['为什么']}")
        if r["成功"]:
            报告["成功"] = True
            break
        反馈.append({"第几轮": i, "造了什么": 草案.get("要造的"), "为什么没成功": r["为什么"],
                     "连带弄红的": r["连带弄红的"]})
    if not 报告["成功"]:
        log(f"  ❌ {轮数} 轮都没成功。**「造不出来」也是结论** —— "
            f"要么这条规则在现有数据形状下触发不了,要么线索不够。")
        # 把每一轮的原因都留着:「三轮都失败」和「三轮都因为同一个原因失败」是两回事
        报告["失败原因"] = [x["为什么"] for x in 报告["轮"]]
    return 报告
