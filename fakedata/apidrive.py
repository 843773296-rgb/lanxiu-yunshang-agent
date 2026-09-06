#!/usr/bin/env python3
"""接口入口 —— 用系统自己的写接口造数据,而不是直接写库。

## 这条路凭什么值得单独做一遍

数据库直连绕过了业务层。而业务规则**大量地不在 schema 里**。
这个仓库的 `backend/rules.py` 就是活例子:

  · 手机号标准化后相同 → 直接阻止新建
  · 姓名 + 尾号 + 门店高度相似 → 转店长确认,不直接建
  · 到店预约至少提前 2 小时,上门量体至少提前 24 小时
  · 预约结束时间不得早于开始时间

这四条,数据库一条都不知道。直连造出来的数据可以全部违反它们而畅通无阻。

所以接口入口有**两种产出,而第二种更值钱**:

  一、造出来的数据一定合法(业务层替你把关了),顺带把写接口也测了一遍
  二、**一份「数据库允许、业务不允许」的差集清单** ——
      接口每拒绝一条,就等于告诉你一条 schema 里看不见的规则。
      那正是数据库直连那条路的**盲区地图**。

第二种产出是这条路真正不可替代的地方。第一种,直连配上足够好的方案也能接近。

## 全部复杂度来自一件事:id 不是你说了算

直连时主键是我们自己造的(`SYN-CUSTOM00001`),子表照着填就行。
走接口,**id 由服务端分配** —— 你提交一个客户,服务返回它自己的编号。
于是每一条外键都要做一次翻译:我们方案里的那个假 id → 服务端真实给的 id。

这个映射一断,后面所有子表的引用全歪,而且**不会报错** ——
它们会指向一个碰巧存在的别的记录。所以映射缺失时宁可整条跳过并记账,
不许"猜一个"。

## 回滚:这条路可能根本删不掉

直连有 manifest,一条 DELETE 就干净。走接口,除非系统**提供了删除接口**,
否则造进去的数据你拿不出来。
沿用直连那条规矩:**灌得进去但删不掉,比灌不进去糟得多。**
所以没声明删除接口时默认拒绝执行,要跑得显式承担。
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _curl(method, url, body=None, headers=(), timeout=20):
    """走 curl 而不是 urllib。

    两个理由:这台机器上 Python 的 urllib 会证书校验失败(仓库里别处也是这么绕的);
    以及 curl 的超时、重定向、非 200 响应体的行为更可预期。
    """
    cmd = ["curl", "-sS", "-X", method, url, "-m", str(timeout),
           "-w", "\n__HTTP__%{http_code}"]
    for h in headers: cmd += ["-H", h]
    if body is not None:
        cmd += ["-H", "content-type: application/json", "--data-binary", "@-"]
    r = subprocess.run(cmd, input=json.dumps(body, ensure_ascii=False) if body else None,
                       capture_output=True, text=True)
    out = r.stdout
    code, _, _x = 0, None, None
    m = re.search(r"__HTTP__(\d+)\s*$", out)
    if m:
        code = int(m.group(1)); out = out[:m.start()]
    if r.returncode != 0 and not m:
        return 0, {"error": f"curl 失败: {r.stderr[:200]}"}, out
    try: doc = json.loads(out) if out.strip() else {}
    except Exception: doc = {"_raw": out[:400]}
    return code, doc, out


def _dig(doc, path):
    """按 `a.b.c` 取值。取不到返回 None —— **不猜、不兜底**。"""
    cur = doc
    for k in (path or "").split("."):
        if not k: continue
        if isinstance(cur, dict) and k in cur: cur = cur[k]
        else: return None
    return cur


class Driver:
    def __init__(self, spec, log=print, dry=True, pause=0.0):
        self.spec, self.log, self.dry, self.pause = spec, log, dry, pause
        self.base = spec["base"].rstrip("/")
        self.headers = list(spec.get("headers", []))
        self.idmap = {}        # (表, 方案里的假 id) -> 服务端真实 id
        self.created = []      # [(表, 真实 id)] 顺序即创建顺序,回滚要倒着来
        self.rejected = []     # 被接口拒绝的,这是这条路最值钱的产出
        self.skipped = []

    # ---- 一行 → 一次请求 ----
    def _payload(self, tname, row, ep, plan, driven=()):
        """把一行数据映射成请求体。**本轮也走接口建的父表,外键要翻译成服务端真实 id。**

        `driven` 是本轮要走接口创建的表。只翻译这些表的外键 ——
        父表不在本轮里(比如 `customer.phone → account`,而 account 没有写接口),
        值就原样提交,让接口自己判。
        第一版对**所有**外键都要求翻译,于是父表不在规格里时整批跳过 ——
        45 行全跳,零成功零拒绝,而这看起来像"没数据可造",不像 bug。
        **判据的适用范围写宽了,失败方式是安静的。**
        """
        body, miss = {}, None
        cols = plan["tables"][tname]["columns"]
        for field, col in ep["fields"].items():
            v = row.get(col)
            g = cols.get(col, {})
            if g.get("gen") == "fk" and v is not None and g.get("table") in driven:
                real = self.idmap.get((g["table"], v))
                if real is None:
                    # 父记录没建成(或者接口没返回 id)。**宁可整条跳过,不许猜一个** ——
                    # 猜出来的外键会指向一条碰巧存在的别的记录,而且不报错。
                    miss = f'{col} → {g["table"]}.{v} 没有对应的服务端 id'
                    break
                v = real
            body[field] = v
        return body, miss

    def run(self, plan, made, tables=None):
        eps = self.spec["endpoints"]
        bad = check_spec(self.spec, plan)
        if bad:
            raise SystemExit("规格/方案对不上,拒绝执行:\n  " + "\n  ".join(bad))
        order = [t for t in plan["order"] if t in eps and (tables is None or t in tables)]
        self.log(f"  接口造数:{len(order)} 张表,按拓扑顺序 {' → '.join(order)}")
        for tname in order:
            ep = eps[tname].get("create")
            if not ep: continue
            rows = made.get(tname) or []
            pk = (plan["tables"][tname]["pk"] or [None])[0]
            ok = 0
            for row in rows:
                body, miss = self._payload(tname, row, ep, plan, driven=set(order))
                if miss:
                    self.skipped.append({"表": tname, "原因": miss}); continue
                if self.dry:
                    ok += 1
                    if pk: self.idmap[(tname, row.get(pk))] = f"DRY-{tname}-{ok}"
                    continue
                code, doc, _raw = _curl(ep.get("method", "POST"), self.base + ep["path"],
                                        body, self.headers)
                if self.pause: time.sleep(self.pause)
                good = code == 200 and not _is_error(doc, ep)
                if good:
                    rid = _dig(doc, ep.get("id_path", "id"))
                    if rid is None:
                        # 建成了却拿不到 id:子表没法引用它,而且它已经躺在库里了。
                        # 这属于**规格没写对**,不是数据问题,必须显式报出来。
                        self.skipped.append({"表": tname,
                                             "原因": f'创建成功但 id_path={ep.get("id_path","id")!r} 取不到 id'})
                    else:
                        if pk: self.idmap[(tname, row.get(pk))] = rid
                        self.created.append((tname, rid))
                    ok += 1
                else:
                    self.rejected.append({"表": tname, "HTTP": code,
                                          "错误": _msg(doc)[:160],
                                          "提交的": {k: v for k, v in list(body.items())[:6]}})
            self.log(f"    {tname}: 成功 {ok} / 拒绝 "
                     f"{sum(1 for r in self.rejected if r['表'] == tname)} / 跳过 "
                     f"{sum(1 for s in self.skipped if s['表'] == tname)}")
        return self.report()

    def rollback(self):
        """倒着调删除接口。没声明删除接口的表,**如实说删不掉**,不假装成功。"""
        eps = self.spec["endpoints"]
        done, cant = 0, {}
        for tname, rid in reversed(self.created):
            ep = eps.get(tname, {}).get("delete")
            if not ep:
                cant[tname] = cant.get(tname, 0) + 1; continue
            path = ep["path"].replace("{id}", str(rid))
            body = {ep["id_field"]: rid} if ep.get("id_field") else None
            if not self.dry:
                _curl(ep.get("method", "POST"), self.base + path, body, self.headers)
            done += 1
        return done, cant

    def report(self):
        """把拒绝按错误信息归类 —— 一类错误就是一条规则,不是一堆失败。"""
        by = {}
        for r in self.rejected:
            key = (r["表"], re.sub(r"\d+", "N", r["错误"]))
            by.setdefault(key, []).append(r)
        # 归一化(把数字换成 N)只用来**分组**,展示要用原文 ——
        # 第一版直接展示归一化后的 key,于是「按 PRD 6.2 阻止新建」显示成「按 PRD N.N」、
        # 客户名被换成 N。**把用于比较的形式当成用于阅读的形式,是报告类代码的常见错。**
        return {"成功": len(self.created), "拒绝": len(self.rejected),
                "跳过": len(self.skipped),
                "规则": [{"表": t, "接口说": v[0]["错误"], "撞了几次": len(v),
                          "例子": v[0]["提交的"]}
                         for (t, e), v in sorted(by.items(), key=lambda x: -len(x[1]))],
                "跳过明细": self.skipped[:20]}


def _is_error(doc, ep):
    if not isinstance(doc, dict): return False
    okf = ep.get("ok_field")
    if okf: return not doc.get(okf)
    return bool(doc.get("error") or doc.get("err") or doc.get("message") and doc.get("code"))


def _msg(doc):
    if not isinstance(doc, dict): return str(doc)[:200]
    for k in ("error", "err", "msg", "message", "reason", "detail"):
        if doc.get(k): return str(doc[k])
    return json.dumps(doc, ensure_ascii=False)[:200]


def check_spec(spec, plan):
    """规格要先过校验,别拿一份写错的规格去打人家的接口。

    其中最要紧的一条是**方案必须按要驱动的表集来建**。
    直连那条路能处理环:环上的边先插空,全部插完再 UPDATE 回填。
    走接口没有"回填"这一步 —— 一条被判成两阶段的外键,到这里就是个 None,
    而接口会拿它当"客户不存在"退回来。

    更麻烦的是这种误判**来自别处**:整库 58 张表里的某个环,
    可能把 `appointment.customer_id` 选成了要断的那条边;
    而只看 {customer, appointment} 这两张表,根本没有环。
    **全局的环判定污染了局部。** 所以接口这条路要用
    `P.build(facts, tables=[要驱动的表])` 单独建一份方案。
    """
    bad = []
    if not spec.get("base", "").startswith(("http://", "https://")):
        bad.append("base 必须是 http:// 或 https:// 开头")
    for t, ep in spec.get("endpoints", {}).items():
        if t not in plan["tables"]: bad.append(f"{t}: 方案里没有这张表"); continue
        c = ep.get("create")
        if not c: continue
        for f, col in (c.get("fields") or {}).items():
            if col not in plan["tables"][t]["columns"]:
                bad.append(f"{t}.create 的字段 {f} 映到了不存在的列 {col}")
        if not c.get("path"): bad.append(f"{t}.create 没有 path")
    driven = set(spec.get("endpoints", {}))
    for t in driven & set(plan.get("tables", {})):
        for cn, g in plan["tables"][t]["columns"].items():
            if g.get("gen") == "fk" and g.get("deferred") and g.get("table") in driven:
                bad.append(f"{t}.{cn} → {g['table']} 被判成了「成环,先插空再回填」——"
                           f"接口这条路没有回填这一步。请用 "
                           f"P.build(facts, tables={sorted(driven)}) 单独建方案")
    return bad


def rollbackable(spec, tables):
    """哪些表**造进去就拿不出来**。沿用直连那条规矩:删不掉的默认不许灌。"""
    return [t for t in tables if not spec.get("endpoints", {}).get(t, {}).get("delete")]
