#!/usr/bin/env python3
"""模型层 —— 只做统计推不出来的那三件事。

## 分工:模型不碰能算的东西

统计推断已经把「哪一列指向哪张表」挖出来了(59 条,41 条高可信)。
让模型再判一遍纯属浪费:它不会比值重叠更准,还慢、还贵、还不稳定。

**模型只处理统计推不出来的部分**,一共三类:

  1. **否决误报。** `wearer.phone → account.phone` 重叠 90%,统计上像;
     而 `account.phone` 的注释写着「着装人那个 phone 是**联系方式**,两件事,别合并」。
     **统计推得出关系,推不出语义。** 这是模型在这个工具里唯一不可替代的活。
  2. **认领没语义的列。** `pwd_hash`、`idem_key`、`mt_opts` —— 列名和取值都看不出来,
     只能造随机串。模型看一眼注释和表的上下文就知道该造什么。
  3. **推出状态机。** 枚举值统计得出来「有这 6 个值、各占多少」,
     但推不出「待付款之后只能到已付款或已取消」。
     没有状态机,造出来的订单会「已发货但未付款」——
     **数据库允许,业务上不可能**,而你会拿它去 debug 半天。

## 三条硬约束

**一、走项目唯一的那个调用口。** 本仓库只有 `agent/v1.py::call()` 真正发请求,
记录仪包在那一层。自己写 HTTP 就绕过了记录仪 —— 而漏掉记录仪的表现是「一切正常」。

**二、模型的输出必须过模式校验。** 它会编出不存在的表名列名。
每一条判定都拿真实 schema 核一遍,核不上的**丢掉并报出来**,不是默默忽略。

**三、模型写的 SQL 只允许是 `select count(*)`。** 断言要跑在库上,
而模型完全可以写出 DELETE。这不是信不信任的问题 ——
**能力边界要在代码里划死,不能靠提示词请求。**

## 产物是一份 overlay,不是数据

模型判完存成 `*.overlay.json`,人能读、能改、能进 git,方案层把它盖在统计结论之上。
下次跑不用再调模型。**做一次,跑一万次** —— 模型层也遵守这条。
"""
import os, re, sys, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 允许模型指定的语义,必须是生成器认识的那些 —— 它编一个 "身份证号" 出来我们也造不了
from plan import SEM2GEN
ALLOWED_SEM = sorted(set(SEM2GEN) - {"fk", "enum"})

SYSTEM = """你是数据库结构分析员。任务是审阅一份「造假数据的方案草稿」,
草稿是纯统计推断出来的:靠列名和取值重叠。你要做的是补上统计做不到的判断。

只做三件事,别的一概不做:

1. 【关系判定】草稿里每条推断出来的表关系,判 confirm / reject / retarget。
   **重点看注释。** 两列值重叠高,可能是真外键,也可能只是「都存手机号」。
   注释说这两个字段是两回事,就 reject,哪怕重叠 100%。
2. 【列语义】给「看不出语义」的列指定该造什么。只能从给定清单里挑。
3. 【状态机】给状态类的枚举列,写出合法的状态流转:起点、转移、终点。
   如果表里有对应的时间戳列(下单时间/付款时间/发货时间),把状态和时间戳对应起来。

规则:
- 只输出 JSON,不要任何解释文字、不要 markdown 代码围栏。
- 每条判定都要带 reason,一句话,说清依据(引用注释就直接引原文)。
- 拿不准就别写。**漏掉一条的代价,远小于编一条错的。**
- 只能提到草稿里出现过的表名和列名。编出来的会被丢弃。

输出格式:
{
 "relations":[{"table":"","column":"","verdict":"confirm|reject|retarget",
               "to_table":"","to_column":"","reason":""}],
 "columns":[{"table":"","column":"","semantic":"","reason":""}],
 "state_machines":[{"table":"","column":"","start":[""],
                    "transitions":[["from","to"]],"terminal":[""],
                    "timestamps":{"状态名":"时间戳列名"},"reason":""}]
}"""


def build_input(facts, plan, max_rel=40, max_col=40, max_fsm=12):
    """挑要送给模型的那一小部分。

    整个库 58 张表 566 列全塞进去,又贵又容易分心。
    只送三类**统计已经交代不了**的东西,并且每条都把判断依据(注释、样例值、备选目标)带全 ——
    **模型缺的是上下文,不是数据量。**
    """
    T = facts["tables"]
    rel, col, fsm = [], [], []

    # **先全收,再排序,最后截断。** 第一版是边遍历边收、收满就停,
    # 而遍历顺序是拓扑序 —— 于是 `ordr.status`(整个库最重要的那个状态机)
    # 排在第 47 张表,被 max_fsm=12 直接切掉了。
    # 截断本身没问题,**按什么顺序截才是问题**:
    # 名字像状态、表里时间戳列多、行数多的,先送。
    def _fsm_rank(item):
        nm = 3 if re.search(r"(status|state|lifecycle)", item["column"].lower()) else 0
        return -(nm + len(item["time_columns"]) + min(len(item["values"]), 8) / 8
                 + min(item["rows"], 2000) / 1000)

    for tn, tp in plan["tables"].items():
        for cn, g in tp["columns"].items():
            cf = T[tn]["columns"].get(cn, {})
            if g["gen"] == "fk" and g.get("confidence") != "高" and len(rel) < max_rel:
                tgt = T.get(g["table"], {}).get("columns", {}).get(g["column"], {})
                rel.append({"table": tn, "column": cn,
                            "comment": cf.get("comment", ""),
                            "to_table": g["table"], "to_column": g["column"],
                            "to_comment": tgt.get("comment", ""),
                            "overlap": g.get("overlap"), "source": g.get("source"),
                            "alternatives": g.get("alternatives", [])})
            elif g.get("需确认") and g["gen"] in ("text", "long_text") and len(col) < max_col:
                col.append({"table": tn, "column": cn, "type": cf.get("type"),
                            "comment": cf.get("comment", ""),
                            "samples": list(cf.get("enum", {}))[:5],
                            "max_len": (cf.get("len") or {}).get("max")})
            if cf.get("enum") and _looks_stateful(cn, cf["enum"]):
                fsm.append({"table": tn, "column": cn,
                            "comment": cf.get("comment", ""),
                            "values": list(cf["enum"]),
                            "rows": T[tn]["rows"],
                            "time_columns": [c for c in T[tn]["columns"]
                                             if re.search(r"(_at$|created|updated|时间)", c)]})
    fsm.sort(key=_fsm_rank)
    for f in fsm: f.pop("rows", None)
    return {"关系待判": rel, "列语义待定": col, "疑似状态机": fsm[:max_fsm],
            "可选语义": ALLOWED_SEM}


def _looks_stateful(cname, enum):
    if re.search(r"(status|state|stage|lifecycle|阶段|状态)", cname.lower()): return True
    return sum(1 for v in enum if re.match(r"^(待|已|未|在)", str(v))) >= 2


# ── 校验:模型说的每一句都要能对上真实 schema ──────────────────────
SQL_OK = re.compile(r"^select\s+count\(\*\)\s+from\s", re.I)
SQL_BAD = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|"
                     r"attach|pragma|load_file|outfile)\b|;", re.I)

def validate(raw, facts, plan):
    """把模型的输出核一遍。核不上的**丢掉并报出来** —— 默默忽略等于假装没发生。"""
    T = facts["tables"]
    out = {"relations": [], "columns": [], "state_machines": []}
    dropped = []

    def has(t, c=None):
        return t in T and (c is None or c in T[t]["columns"])

    for r in raw.get("relations", []):
        t, c = r.get("table"), r.get("column")
        if not has(t, c): dropped.append(f'关系:{t}.{c} 不存在'); continue
        v = r.get("verdict")
        if v not in ("confirm", "reject", "retarget"):
            dropped.append(f'关系:{t}.{c} 的 verdict={v!r} 不认识'); continue
        if v == "retarget" and not has(r.get("to_table"), r.get("to_column")):
            dropped.append(f'关系:{t}.{c} 改指的 {r.get("to_table")}.{r.get("to_column")} 不存在'); continue
        out["relations"].append(r)

    for c in raw.get("columns", []):
        if not has(c.get("table"), c.get("column")):
            dropped.append(f'列语义:{c.get("table")}.{c.get("column")} 不存在'); continue
        if c.get("semantic") not in ALLOWED_SEM:
            dropped.append(f'列语义:{c.get("table")}.{c.get("column")} 的 '
                           f'{c.get("semantic")!r} 不是生成器认识的语义'); continue
        out["columns"].append(c)

    # 一个时间戳列只能有**一个主人**。这条不变量有两个破法,第一版只堵了一个:
    #   · 同一个状态机里两个状态映到同一列(已堵)
    #   · **同一张表上两个状态机认领同一列**(没堵)——
    #     ordr.status 和 ordr.prd_status 都要 audit_at,于是两个后处理互相覆盖、
    #     两套断言互相打架,造什么数据都过不了。
    # 教训:不变量要在**它真正的作用域**上执行。这条的作用域是「表」,不是「状态机」。
    claimed = {}
    for m in raw.get("state_machines", []):
        t, c = m.get("table"), m.get("column")
        if not has(t, c): dropped.append(f'状态机:{t}.{c} 不存在'); continue
        known = set(map(str, (T[t]["columns"][c].get("enum") or {})))
        states = set(map(str, m.get("start", []))) | set(map(str, m.get("terminal", [])))
        trans = [(str(a), str(b)) for a, b in m.get("transitions", []) if a and b]
        states |= {s for ab in trans for s in ab}
        unknown = states - known
        if unknown:
            # 状态机里出现库里没有的状态值 —— 造出来的数据会当场违反自己的枚举断言
            dropped.append(f'状态机:{t}.{c} 提到库里没有的状态 {sorted(unknown)[:4]}')
            continue
        ts = {str(k): v for k, v in (m.get("timestamps") or {}).items()
              if str(k) in known and has(t, v)}
        badts = set(map(str, (m.get("timestamps") or {}))) - set(ts)
        if badts: dropped.append(f'状态机:{t}.{c} 的时间戳映射有 {sorted(badts)[:3]} 对不上,已剔除')
        # **一个时间戳列被两个状态共用 → 派生出的断言必然自相矛盾。**
        # 比如 tag.status 把「启用」和「停用」都映到 updated:
        #   状态是启用 → updated 必须有值(启用是必经)
        #   状态是启用 → updated 必须为空(停用不是必经)
        # 同一列同一行,两条断言对着干,造什么数据都过不了。
        # 分不清哪个状态才是这列的主人,就整列剔除 —— **宁可少一条约束,不能留一条自毁的。**
        from collections import Counter
        shared = {v for v, n in Counter(ts.values()).items() if n > 1}
        if shared:
            ts = {k: v for k, v in ts.items() if v not in shared}
            dropped.append(f'状态机:{t}.{c} 的 {sorted(shared)[:3]} 被多个状态共用,'
                           f'会派生出自相矛盾的断言,已整列剔除')
        # **诞生时间不能当状态时间戳。** 模型把 ordr 的「待付款」映到了 created,
        # 于是「待完成」的订单被判定为没走到待付款 → created 置空 ——
        # 造出一批**没有下单时间的订单**。
        # created 是这一行的诞生时刻,不是某个状态的产物:它永远存在,
        # 而且是所有状态机对齐时间的**锚点**。锚点被当成状态戳,锚就没了。
        birth = {k: v for k, v in ts.items()
                 if v in ("created", "created_at", "create_time", "gmt_create")}
        if birth:
            ts = {k: v for k, v in ts.items() if k not in birth}
            dropped.append(f'状态机:{t}.{c} 把 {sorted(set(birth.values()))} 当成了状态时间戳,'
                           f'而它是这一行的诞生时刻(也是对齐用的锚点),已剔除')
        taken = {k: v for k, v in ts.items() if (t, v) in claimed}
        if taken:
            ts = {k: v for k, v in ts.items() if k not in taken}
            dropped.append(f'状态机:{t}.{c} 想认领的 {sorted(set(taken.values()))[:3]} '
                           f'已经归 {claimed[(t, list(taken.values())[0])]} 了,一列只能有一个主人')
        for v in ts.values(): claimed[(t, v)] = f"{t}.{c}"
        m = dict(m, transitions=trans, timestamps=ts)
        if not trans: dropped.append(f'状态机:{t}.{c} 没给出任何转移'); continue
        out["state_machines"].append(m)

    return out, dropped


def _parse_json(text):
    """模型有时会包一层 ```json 围栏,有时会在前后带一句话。取最外层的 {...}。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0: raise ValueError(f"响应里没有 JSON: {text[:200]}")
    return json.loads(t[i:j + 1])


def infer(facts, plan, model=None, log=print):
    """调一次模型。**走 agent/v1.py 那个唯一的发请求口,记录仪自动接上。**"""
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import v1
    payload = build_input(facts, plan)
    n = sum(len(payload[k]) for k in ("关系待判", "列语义待定", "疑似状态机"))
    log(f"  送去判断:关系 {len(payload['关系待判'])} 条 / "
        f"列 {len(payload['列语义待定'])} 个 / 疑似状态机 {len(payload['疑似状态机'])} 个")
    if not n:
        return {"relations": [], "columns": [], "state_machines": []}, [], {}
    if model: os.environ["ANTHROPIC_MODEL"] = model
    pv = v1.provider()
    t0 = time.time()
    resp = v1.call(pv, dict(model=pv["model"], max_tokens=pv.get("max_tokens", 8000),
                            system=SYSTEM,
                            messages=[{"role": "user", "content":
                                       json.dumps(payload, ensure_ascii=False, indent=1)}]),
                   purpose="假数据工厂·补语义", gen="工具")
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    raw = _parse_json(text)
    good, dropped = validate(raw, facts, plan)
    meta = {"model": pv["model"], "耗时秒": round(time.time() - t0, 1),
            "usage": resp.get("usage", {}), "送去判断": n}
    return good, dropped, meta


def save(path, overlay, dropped, meta):
    doc = {"说明": "模型层的判定结果。人可以直接改这个文件,方案层会把它盖在统计结论之上。",
           "元信息": meta, "被丢弃的": dropped, **overlay}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    import schema as S, discover as D, plan as P
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "backend", "lanxiu.db")
    conn = S.connect(tgt); facts = D.discover(conn, conn.reflect())
    pl = P.build(facts, scale=0.2)
    payload = build_input(facts, pl)
    print(json.dumps(payload, ensure_ascii=False, indent=1)[:2600])
    print(f"\n… 关系 {len(payload['关系待判'])} / 列 {len(payload['列语义待定'])} "
          f"/ 状态机 {len(payload['疑似状态机'])}")
