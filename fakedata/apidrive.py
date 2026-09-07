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
        self.unknown = []      # 判不出成败的:规格没说清,必须显式报,不许塞进成功那边

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
                res, why = outcome(doc, code, ep)
                if res == "unknown":
                    self.unknown.append({"表": tname, "HTTP": code, "响应": why[:160]})
                    continue
                if res == "ok":
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
                                          "码": _code(doc, ep) or "(接口没给码)",
                                          "错误": why[:160], "提交的": dict(body)})
            self.log(f"    {tname}: 成功 {ok} / 拒绝 "
                     f"{sum(1 for r in self.rejected if r['表'] == tname)} / 跳过 "
                     f"{sum(1 for s in self.skipped if s['表'] == tname)} / 判不出 "
                     f"{sum(1 for u in self.unknown if u['表'] == tname)}")
        return self.report()

    def minimize(self, plan, max_calls=200):
        """把每一类拒绝削到**最小请求体**:逐个字段试着拿掉,拿掉之后还报同一个码就真拿掉。

        为什么必须"同一个码"而不是"还是失败":
        `DUP_PHONE` 的请求体削掉 name 之后照样失败 —— 但失败的是 `NEED_NAME`,
        那是**另一条规则**。拿它当题面,问的就不是原来那件事了。
        **判据要钉在「是不是同一个原因」上,不是「是不是还错」。**

        削的过程会真的发请求。万一某个变体**成功**了,它就在库里留了一条记录 ——
        所以照样记进 created,回滚时一起删。**探测也是写入,不能假装它没发生。**
        """
        eps = self.spec["endpoints"]
        seen, calls = set(), 0
        for r in self.rejected:
            key = (r["表"], r.get("码"))
            if key in seen: continue
            seen.add(key)
            ep = eps.get(r["表"], {}).get("create")
            if not ep or self.dry: continue
            body, want = dict(r["提交的"]), r.get("码")
            pk = (plan["tables"][r["表"]]["pk"] or [None])[0]
            for f in list(body):
                if calls >= max_calls: break
                trial = {k: v for k, v in body.items() if k != f}
                if not trial: continue
                code, doc, _x = _curl(ep.get("method", "POST"), self.base + ep["path"],
                                      trial, self.headers)
                calls += 1
                res, _why = outcome(doc, code, ep)
                if res == "ok":
                    rid = _dig(doc, ep.get("id_path", "id"))
                    if rid is not None: self.created.append((r["表"], rid))
                    continue                      # 变体建成了 → 这个字段不能删
                if res == "rejected" and _code(doc, ep) == want:
                    body = trial                  # 同一个码,这个字段是多余的
            r["最小请求体"] = body
            # **差集的另一半:同样这几个字段,数据库怎么说。**
            # 「接口不让」单独看只是一条校验;配上「而库让」才是一条**差集** ——
            # 也才说得清这条规则为什么只存在于业务层。
            cols = plan["tables"][r["表"]]["columns"]
            fmap = ep.get("fields") or {}
            # 覆盖**这个接口的整个字段面**,不是削剩下的那几个。
            # `NEED_NAME` 会被削成只剩 `{shop}` —— 而这条规则针对的恰恰是被削掉的 `name`,
            # 只报剩下的,「库里 name 可空」这个最关键的对照就不见了。
            # **削最小是为了让题面干净,不是为了缩小观察范围。**
            r["库这边"] = {}
            for f, col in fmap.items():
                if col not in cols: continue
                g = cols[col]
                r["库这边"][col] = {"可空": bool(g.get("nullable", True)),
                                    "唯一": bool(g.get("unique")),
                                    "最小请求体里还留着": f in body}
            r["删掉也一样"] = sorted(set(fmap) - set(body))
        return calls

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

    def coverage(self, order=None):
        """这一批数据把**多少条业务规则撞出来了**,还有多少条从没撞到。

        这份清单的危险之处在于:**它列出的每一条都是真的,所以看起来是完整的。**
        没撞到的规则不会留下任何痕迹 —— 而「没撞到」有两种解释:
        这条规则不存在,或者我的数据恰好绕开了它。两者在输出上分不开。

        (另一条线按 rules.py 里声明的错误码逐个验可达性,发现 `NEED_REVIEW` 触发不到 ——
         而那恰恰是业务上最有意思的一条:正确动作**既不是能也不是不能,是转店长确认**。)

        所以全集要由**规格**声明(`endpoints[t].codes`)。
        规格没声明的,如实说「全集未知,覆盖率无法度量」——
        **不许默默让人以为这就是全部。**
        """
        eps = self.spec["endpoints"]
        hit = {}
        for r in self.rejected:
            hit.setdefault(r["表"], set()).add(r.get("码"))
        out = {}
        for t in (order or eps):
            known = (eps.get(t, {}).get("codes") or None)
            got = sorted(x for x in hit.get(t, set()) if x and not x.startswith("("))
            if known is None:
                out[t] = {"撞到": got, "全集": None,
                          "说明": "规格没声明这个接口能返回哪些业务码 —— **覆盖率无法度量**,"
                                  "这份清单不能当作完整的规则清单"}
            else:
                miss = [c for c in known if c not in got]
                out[t] = {"撞到": got, "全集": list(known), "没撞到": miss,
                          "覆盖率": round(len(got) / max(len(known), 1), 3),
                          "说明": "「没撞到」有两种解释:规则不存在,或者这批数据恰好绕开了它"}
        return out

    def report(self):
        """把拒绝按错误信息归类 —— 一类错误就是一条规则,不是一堆失败。"""
        # 按 (表, 错误码) 归类。码取不到时才退回文案归一化 ——
        # 退化路径要留,但不能当主路径。
        by = {}
        for r in self.rejected:
            k = r.get("码") or ""
            key = (r["表"], k if k and not k.startswith("(") else re.sub(r"\d+", "N", r["错误"]))
            by.setdefault(key, []).append(r)
        return {"成功": len(self.created), "拒绝": len(self.rejected),
                "跳过": len(self.skipped), "判不出成败": len(self.unknown),
                "覆盖": self.coverage(),
                "判不出明细": self.unknown[:10],
                "规则": [{"表": t, "码": e, "接口说": v[0]["错误"], "撞了几次": len(v),
                          "例子": v[0]["提交的"],
                          "最小请求体": v[0].get("最小请求体"),
                          "库这边": v[0].get("库这边"),
                          "删掉也一样": v[0].get("删掉也一样")}
                         for (t, e), v in sorted(by.items(), key=lambda x: -len(x[1]))],
                "跳过明细": self.skipped[:20]}


def _code(doc, ep):
    """取业务错误码。**归类要锚在码上,不是措辞上。**

    `reason` 里带客户 id、人名、分钟数,同一条规则每次的文案都不一样;
    原来靠"把数字换成 N"来归一化再分组 —— 那本质还是在拿字面量归类,
    而中文表达同一个意思的写法接近无限,枚举必输。
    `code`(DUP_PHONE / NO_BACKFILL / NEED_NAME)是结构,不会随文案漂。
    """
    if not isinstance(doc, dict): return ""
    return str(_dig(doc, ep.get("code_path", "code")) or "")


def outcome(doc, http, ep):
    """判成败,**判不出来时算「不确定」,不算成功。**

    第一版的默认是「没看到 error 字段就算成功」。而这个仓库真实的写接口
    返回的是 `{ok: false, code: ..., reason: ...}` —— 压根没有 error 字段。
    于是每一次业务拒绝都会被记成成功:成功数虚高、拒绝清单空空如也,
    而拒绝清单正是这条路唯一不可替代的产出。**兜底方向选错,失败会打扮成成功。**

    现在:规格必须说清怎么判(`ok_field`,或者靠 `id_path` 取不取得到 id)。
    两者都判不出来 → 记成「不确定」并显式报出来,不塞进任何一边。
    """
    if not isinstance(doc, dict): return "unknown", str(doc)[:200]
    if http != 200: return "rejected", _msg(doc)
    okf = ep.get("ok_field")
    if okf is not None:
        return ("ok" if doc.get(okf) else "rejected"), _msg(doc)
    if doc.get("error") or doc.get("err"): return "rejected", _msg(doc)
    if _dig(doc, ep.get("id_path", "id")) is not None: return "ok", ""
    return "unknown", _msg(doc)


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
