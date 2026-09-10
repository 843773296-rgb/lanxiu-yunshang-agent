#!/usr/bin/env python3
"""起草接口规格 —— 静态能扒的先扒干净,模型只补它扒不出来的那几项。

## 为什么要有这个

接口驱动那条路,规格一直是**手写的 JSON**。而这个工具全部的说法是
「规则不用人写,从系统自己身上挖出来」—— 数据库那条路做到了,接口这条路没有。

## 顺序:先问静态解析能拿到多少

照老规矩,**先看能算的**。结果比预想的多得多,一个 HTTP 服务里能静态扒出来的有:

  · 路由 → 处理函数(`if p=="/api/x": return self._send(handler(body))`)  —— 57 条
  · 每个处理函数**读了哪些请求字段**(`d.get("name")`)
  · 它**往哪张表插**(`INSERT INTO xxx`)
  · 它成功时返回的 **id 叫什么**(`dict(ok=True, ..., id=cid)`)
  · 它可能返回哪些**业务码**(handler 里的 `code="X"`,加上校验器里的 `return False,"X"`)

这些全是事实,不该让模型猜 —— **模型猜得再准也不如源码里写着的准,而且会漂。**

## 模型只补三件静态扒不出来的

  ① **这个字段是数据还是上下文** —— `role` / `actor` / 幂等键不对应任何列,
     但接口收、而且影响判定。源码里它和 `name` 长得一模一样。
  ② **哪些字段业务上唯一** —— schema 里 `customer.phone` 不唯一,而业务规则要求它唯一。
     这件事数据库不知道、统计看不出(源库里唯一可能只是碰巧)。
  ③ **哪个端点是哪张表的「创建 / 删除」** —— 一个 `INSERT INTO` 只说明它写了那张表,
     说明不了它在业务上是不是「新建一条客户档案」。

## 模型说的每一句都要能对回静态事实

路径必须在真实路由表里、字段映到的列必须在真实表里、
业务码必须在源码里真的出现过 —— 对不上就丢掉并报出来。
**校验用的全是静态扒出来的事实,所以这层校验本身不需要信任模型。**
"""
import ast, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _ok_fields(body):
    """成功那一支返回了哪些字段。**要抓整个 dict(...),不是一行里的第一个** ——
    第一版只匹配到 `code`,于是每个端点看起来都只返回一个 code,
    而真正要用的 `id` 反倒不见了。**正则抓到的第一个,不等于全部。**"""
    out = set()
    for m in re.finditer(r"return\s+dict\(\s*ok\s*=\s*True", body):
        seg, depth = "", 0
        for ch in body[m.start():]:
            seg += ch
            if ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0: break
        out |= set(re.findall(r"(\w+)\s*=", seg))
    return sorted(out - {"dict", "ok"})


def scan_service(server_py, rules_py=None):
    """把一个 HTTP 服务里能静态确定的东西全扒出来。"""
    src = io.open(server_py, encoding="utf-8").read()
    tree = ast.parse(src)
    bodies = {n.name: (ast.get_source_segment(src, n) or "")
              for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    routes = []
    for m in re.finditer(r'if p\s*==\s*"([^"]+)":\s*return self\._send\((\w+)\(', src):
        path, h = m.group(1), m.group(2)
        b = bodies.get(h, "")
        if not b: continue
        routes.append({
            "path": path, "handler": h,
            "读的请求字段": sorted(set(re.findall(r'\bd\.get\("(\w+)"\)', b))),
            "写的表": sorted(set(re.findall(r"INSERT\s+INTO\s+`?(\w+)", b, re.I))
                             | set(re.findall(r"UPDATE\s+`?(\w+)", b, re.I))
                             | set(re.findall(r"DELETE\s+FROM\s+`?(\w+)", b, re.I))),
            "写不写库": bool(re.search(r"INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM", b, re.I)),
            "成功返回的字段": _ok_fields(b),
            "业务码": sorted(set(re.findall(r'code\s*=\s*"([A-Z_]{2,})"', b))),
            "_body": b,
        })

    # 校验器里的失败码:`return False,"CODE",...`
    rule_codes, per_fn = [], {}
    if rules_py and os.path.exists(rules_py):
        rs = io.open(rules_py, encoding="utf-8").read()
        rule_codes = sorted(set(re.findall(r'return\s+False\s*,\s*"([A-Z_]{2,})"', rs)))
        for n in ast.walk(ast.parse(rs)):
            if isinstance(n, ast.FunctionDef) and n.name.startswith("validate_"):
                seg = ast.get_source_segment(rs, n) or ""
                per_fn[n.name] = sorted(set(
                    re.findall(r'return\s+False\s*,\s*"([A-Z_]{2,})"', seg)))
    return {"routes": routes, "校验器里的失败码": rule_codes, "校验器分函数": per_fn}


def writing_routes(scan):
    """只有写接口才能用来造数。读接口一律排除 —— 它们造不出任何东西。"""
    return [r for r in scan["routes"] if r["写不写库"]]


def skeleton(scan, tables):
    """静态事实 → 规格骨架。**模型拿到的是这个,不是一堆源码。**"""
    out = {}
    for r in writing_routes(scan):
        # **一个 handler 碰几张表就列几张,不替模型挑。**
        # 第一版只取第一张对得上的,于是 `/api/merge` 被记成了 appointment 的端点 ——
        # 它确实动了那张表,但它在业务上根本不是「新建预约」。
        # **「写了哪张表」是事实,「这是哪张表的创建接口」是判断** —— 别把判断混进事实里。
        hit = [t for t in r["写的表"] if t in tables]
        if not hit: continue
        cols = set().union(*[set(tables[t]) for t in hit])
        key = "/".join(hit)
        out.setdefault(key, {"涉及的表": hit, "候选端点": []})["候选端点"].append({
            "path": r["path"], "handler": r["handler"],
            "读的请求字段": r["读的请求字段"],
            "字段里能直接对上列名的": [f for f in r["读的请求字段"] if f in cols],
            "字段里对不上任何列的": [f for f in r["读的请求字段"] if f not in cols],
            "成功返回的字段": r["成功返回的字段"],
            "handler 里的业务码": r["业务码"],
        })
    return out


def table_columns(conn):
    import schema as S
    sc = conn.reflect()
    return {t.name: [c.name for c in t.columns] for t in sc.tables.values()}


if __name__ == "__main__":
    import schema as S
    scan = scan_service(os.path.join(ROOT, "backend", "server.py"),
                        os.path.join(ROOT, "backend", "rules.py"))
    conn = S.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
    tabs = table_columns(conn)
    sk = skeleton(scan, tabs)
    print(f"路由 {len(scan['routes'])} 条,其中**写库的** {len(writing_routes(scan))} 条")
    print(f"校验器里的失败码 {len(scan['校验器里的失败码'])} 个:{scan['校验器里的失败码']}")
    print(f"\n能对上表的写接口,涉及 {len(sk)} 张表:\n")
    for tab, info in list(sk.items())[:6]:
        for ep in info["候选端点"]:
            print(f"  {tab:22s} {ep['path']:24s} {ep['handler']}")
            print(f"    对得上列的字段: {ep['字段里能直接对上列名的']}")
            print(f"    对不上列的字段: {ep['字段里对不上任何列的']}   ← 上下文?还是别名?")
            print(f"    成功返回: {ep['成功返回的字段']}  码: {ep['handler 里的业务码']}")


# ── 模型层:只补静态扒不出来的那几项 ──────────────────────────────
SYSTEM = """你在把一个 HTTP 服务的写接口整理成一份「造测试数据用的规格」。

**给你的每一条都是从源码里静态扒出来的事实**(路由、处理函数、它读了哪些请求字段、
写了哪些表、成功时返回哪些字段、可能返回哪些业务码)。这些**不要重复,也不要改**。

你只回答静态扒不出来的四个问题:

1. 【这是不是一个「新建一条记录」的接口】 —— 写了某张表**不等于**新建。
   导入、审批、状态调整、合并都会写表,但它们不是「新建一条客户档案」。
   **每一条都要给 is_create: true/false,不许省** —— false 的我会自己过滤。
   (上一版让你"不是就跳过",结果你在 reason 里写着"不是新建记录",却照样交了一条。
    **判断要放在结构化字段里,不能放在自然语言里。**)
2. 【请求字段 → 数据库列 的映射】 —— 名字不一样的要对上(比如 start → start_ts)。
   对不上任何列的字段,归到 context 里(见下)。
3. 【哪些字段是上下文,不是数据】 —— role / actor / 操作人 / 幂等键这一类:
   接口收、影响判定,但不对应任何列。
4. 【哪些字段业务上必须唯一】 —— 数据库里不唯一、但业务规则要求唯一的那些
   (典型:手机号、登录名、单号)。**拿不准就别写。**

另外从给定的码清单里挑出**失败码**(表示"这次没做成"的那些),成功码不要。

规则:
- 只输出 JSON,不要解释、不要 markdown 围栏。
- **只能用给定清单里出现过的** path / 列名 / 字段名 / 业务码。编的会被丢掉。
- 拿不准就少写。**漏一条的代价,远小于编一条错的。**

**用 handler 名当标识**(它在输入里一字不差地出现),路径不用你填 —— 我这边查得到。
**别回答我已经知道的事**:每多填一个我已有的字段,就多一处填错的地方。

输出格式(下面是一个**填满的例子**,照这个形状,别照抄内容):
{"endpoints":[
  {"handler":"create_customer","table":"customer","is_create":true,
   "fields":{"name":"name","phone":"phone","shop":"shop"},
   "context_fields":["role"],"unique_fields":["phone"],
   "id_path":"id","ok_field":"ok","codes":["NEED_NAME","DUP_PHONE"],
   "reason":"新建一条客户档案"},
  {"handler":"save_block","table":"page_block","is_create":false,
   "reason":"是编辑/排序已有区块,不是新建"}
]}
**输入里的每一条写接口都要出现在输出里**,is_create 为 false 的只要 handler/table/reason 三项。"""


def _validator_codes(route, scan):
    """这个 handler 真的会撞上哪些失败码 —— 看它调了哪个校验器。"""
    called = set(re.findall(r"(?:rules\.)?(validate_\w+)\s*\(", route.get("_body", "")))
    return {c for fn, cs in scan.get("校验器分函数", {}).items() if fn in called for c in cs}


def build_payload(scan, tables, max_ep=14):
    eps = []
    for r in writing_routes(scan):
        hit = [t for t in r["写的表"] if t in tables]
        if not hit: continue
        cols = sorted(set().union(*[set(tables[t]) for t in hit]))
        eps.append({"path": r["path"], "handler": r["handler"],
                    "写了哪些表": hit, "这些表的列": cols[:60],
                    "读的请求字段": r["读的请求字段"],
                    "成功时返回的字段": r["成功返回的字段"],
                    # **码要按端点给。** 第一版把 14 个失败码全塞给每一个端点,
                    # 于是 `NEED_REVIEW`(客户姓名相似要店长确认)被安到了 product、content 头上。
                    # **那不是模型编的,是我诱导的** —— 清单里有,它就以为可选。
                    # 现在只给:这个 handler 自己写的码 + 它**真的调用过**的校验器的码。
                    "可能的业务码": sorted(set(r["业务码"]) | _validator_codes(r, scan))})
    eps = [e for e in eps if e["读的请求字段"]]     # 一个字段都不读的,造不了数
    return {"写接口": eps[:max_ep]}


def validate(raw, scan, tables):
    """模型说的每一句都要对得回**静态事实**。所以这层校验不需要信任模型。"""
    paths = {r["path"]: r for r in scan["routes"]}
    allcodes = set(scan["校验器里的失败码"]) | {c for r in scan["routes"] for c in r["业务码"]}
    out, dropped = {"endpoints": {}}, []
    byh = {r["handler"]: r for r in scan["routes"]}
    for e in raw.get("endpoints", []):
        t = e.get("table")
        h = e.get("handler")
        if h not in byh: dropped.append(f"{t}: handler {h!r} 不在真实路由表里"); continue
        p = byh[h]["path"]          # **路径我自己查,不问模型**
        if not e.get("is_create", True):
            dropped.append(f'{t}: 模型自己判为「不是新建接口」({e.get("reason","")[:26]})')
            continue
        if t not in tables: dropped.append(f"表 {t} 不存在"); continue
        read = set(byh[h]["读的请求字段"])
        cols = set(tables[t])
        fields, bad = {}, []
        for f, col in (e.get("fields") or {}).items():
            if f not in read: bad.append(f"{f}(接口根本不读这个字段)")
            elif col not in cols: bad.append(f"{f}→{col}(列不存在)")
            else: fields[f] = col
        if bad: dropped.append(f"{t}: 丢掉字段 {bad[:4]}")
        ctx = [f for f in (e.get("context_fields") or []) if f in read and f not in cols]
        badctx = [f for f in (e.get("context_fields") or []) if f in cols]
        if badctx: dropped.append(f"{t}: {badctx} 明明是列,不算上下文字段")
        uniq = [f for f in (e.get("unique_fields") or []) if f in fields]
        codes = [c for c in (e.get("codes") or []) if c in allcodes]
        badc = [c for c in (e.get("codes") or []) if c not in allcodes]
        if badc: dropped.append(f"{t}: 业务码 {badc[:4]} 源码里没出现过")
        if not fields: dropped.append(f"{t}: 一个字段都没对上,跳过"); continue
        ep = {"create": {"method": "POST", "path": p, "fields": fields,
                         "id_path": e.get("id_path") or "id",
                         "ok_field": e.get("ok_field") or "ok"}}
        if ctx: ep["create"]["const_fields"] = {f: "" for f in ctx}
        if codes: ep["codes"] = codes
        if uniq: ep["fresh_fields"] = uniq
        ep["_理由"] = e.get("reason", "")
        out["endpoints"][t] = ep
    return out, dropped


def byh_path(scan, path):
    return next((r["handler"] for r in scan["routes"] if r["path"] == path), path)


def draft(server_py, rules_py, conn, model=None, log=print):
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import v1
    scan = scan_service(server_py, rules_py)
    tables = table_columns(conn)
    payload = build_payload(scan, tables)
    log(f"  静态扒出:路由 {len(scan['routes'])} 条 / 写库的 {len(writing_routes(scan))} 条 / "
        f"送去判断 {len(payload['写接口'])} 条")
    if model: os.environ["ANTHROPIC_MODEL"] = model
    pv = v1.provider()
    resp = v1.call(pv, dict(model=pv["model"], max_tokens=8000, system=SYSTEM,
                            messages=[{"role": "user",
                                       "content": json.dumps(payload, ensure_ascii=False)}]),
                   purpose="假数据工厂·起草接口规格", gen="工具")
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    if resp.get("stop_reason") == "max_tokens":
        raise SystemExit("被 max_tokens 截断 —— 少送几条端点再试")
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    raw = json.loads(t[t.find("{"):t.rfind("}") + 1])
    spec, dropped = validate(raw, scan, tables)
    # **覆盖率。** 上一版只报「丢弃了几条」—— 那是分子。
    # 送去 7 条、起草 5 条、**漏了 2 条而且一声不吭**,其中一条是最重要的那个端点。
    # 我给学员讲完「没有分母的没问题不是信息」,当天写的新代码里又没有分母。
    asked = [e["handler"] for e in payload["写接口"]]
    got = {byh_path(scan, ep["create"]["path"]) for ep in spec["endpoints"].values()}
    said = {e.get("handler") for e in raw.get("endpoints", [])}
    notcreate = {e.get("handler") for e in raw.get("endpoints", []) if not e.get("is_create", True)}
    cov = {"送去": len(asked), "起草": len(got),
           "模型判为「不是新建」的": sorted(notcreate & set(asked)),
           "模型只字未提的": [h for h in asked if h not in said],
           "提了但没通过校验的": [h for h in asked if h in said and h not in got and h not in notcreate]}
    return spec, dropped, {"model": pv["model"], "usage": resp.get("usage", {}), "覆盖": cov}
