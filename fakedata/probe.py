#!/usr/bin/env python3
"""定向构造 —— 为撞不到的业务码,反推一组能触发它的数据。

## 要解决的问题

差集清单加上覆盖率之后,真相是:11 条已知规则,随机造的数据只撞到 3 条。
而没撞到的里面有**结构性撞不到**的一类,最典型的是「姓名相似 + 尾号相同 + 同门店」:

**随机生成的数据之间没有关系** —— 两条随机记录不会碰巧相似。
这不是数据量不够,加到一百万条也一样。

## 办法:不理解规则,只准备一份「数据能怎么错」的目录

这里不去读业务规则(读了也是抄一份,会漂)。改成拿一份**变异算子**去试,
看接口回什么码。和边界值池是同一个思路,只是作用在**整条记录**上而不是单个字段。

关键的那个算子叫「仿冒」:**以一条已经存在的记录为模板去改**。
变异是**有参照物的**,随机没有 —— 关系就是这么来的。
它对应真实世界最常见的一类脏数据:重复建档。

## 三条纪律

**一、探测也是写入。** 变异请求可能会**成功**,那就在库里留了一条记录。
一律记进回滚清单 —— 这条在削最小请求体那里已经栽过一次。

**二、只在自己造的数据上变异。** 模板取自本次创建的记录,不去读库里别人的行。

**三、有预算上限。** 算子 × 字段是组合爆炸,必须封顶,并且**如实报告有没有跑满**——
"没撞到"和"预算用光了没试到"是两件事。
"""
import copy, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from apidrive import _curl, _code, outcome, _dig


# ── 变异算子:每一个对应一类「数据会怎么错」 ────────────────────────
def op_drop(body, f, ref=None):
    """整个字段不给 —— 必填类规则。"""
    if f not in body or len(body) <= 1: return None
    return {k: v for k, v in body.items() if k != f}


def op_empty(body, f, ref=None):
    """字段给空串 —— 「空 ≠ 缺失」,很多系统只挡了缺失。"""
    if f not in body: return None
    return dict(body, **{f: ""})


def op_garble(body, f, ref=None):
    """字段给一个明显不合格式的值 —— 格式校验类。"""
    if f not in body: return None
    return dict(body, **{f: "not-a-valid-value"})


def op_copy(body, f, ref=None):
    """照抄一条已有记录的这个字段 —— 唯一性 / 重复类。"""
    if ref is None or f not in body or f not in ref: return None
    if ref[f] in (None, ""): return None
    return dict(body, **{f: ref[f]})


def op_impersonate(body, f, ref=None, fresh=()):
    """**仿冒**:把整条记录做成一条已有记录的「近似重复」。

    这是随机生成永远造不出来的那一类 —— 因为它需要一个**参照物**。
    随机数据之间没有关系,两条随机记录不会碰巧相似;加到一百万条也一样。

    「相似性」类规则通常是**多个条件同时成立**才触发
    (姓名相似 **且** 尾号相同 **且** 门店相同),所以这个算子必须是**组合**的:

      · 大部分字段:**原样照抄**(门店、顾问要完全相同,改一下就不匹配了)
      · 声明为业务唯一的字段:**保留尾部、换掉前缀** ——
        既不会撞成"完全重复"(那是另一条规则,会抢先返回),又保住了尾号相同
      · 指定的那个字段 `f`:改一个字,制造"相似但不相同"

    只改一处是撞不到的:全抄会先撞「完全重复」,只改一处又缺了别的条件。
    """
    if ref is None: return None
    out = {k: ref.get(k, body.get(k)) for k in body}
    for u in fresh:
        rv = str(ref.get(u) or "")
        if len(rv) >= 5 and rv.isdigit():
            out[u] = rv[0] + "".join("9" if c == "8" else "8" for c in rv[1:-4]) + rv[-4:]
        elif rv:
            out[u] = rv[:-4] + "X" + rv[-3:] if len(rv) > 4 else rv
    if f and f in out and out[f] not in (None, ""):
        v = str(out[f])
        out[f] = v[:-1] + ("某" if v[-1] != "某" else "甲") if len(v) >= 2 else v + "某"
    return out if out != body else None


def op_past(body, f, ref=None):
    """时间挪到很久以前 —— 补录 / 时效类。"""
    if f not in body or not _is_dt(body.get(f)): return None
    return dict(body, **{f: "2019-01-01 09:00:00"})


def op_soon(body, f, ref=None):
    """时间挪到「马上」 —— 提前量类(至少提前 N 小时)。"""
    import datetime
    if f not in body or not _is_dt(body.get(f)): return None
    t = datetime.datetime.now() + datetime.timedelta(minutes=10)
    return dict(body, **{f: t.strftime("%Y-%m-%d %H:%M:%S")})


def op_bogus_ref(body, f, ref=None):
    """引用一个不存在的父记录。"""
    if f not in body or body.get(f) in (None, ""): return None
    return dict(body, **{f: "__does_not_exist__"})


def _apply(fn, body, f, ref, fresh, alts):
    """算子签名不统一(有的要 fresh,有的要 alts),在这里统一分发,别在调用点分叉。"""
    if fn is op_impersonate: return fn(body, f, ref, fresh)
    if fn is op_alt_value:   return fn(body, f, ref, alts)
    return fn(body, f, ref)


def _freshen(v, *salt):
    """造一个「同形状但换一个」的值:11 位手机号还是 11 位,别的加个后缀。
    用 salt 播种,所以同一次探测里是确定性的。"""
    import random
    r = random.Random("freshen::" + "::".join(map(str, salt)) + "::" + v)
    if re.fullmatch(r"1\d{10}", v):
        return "1" + r.choice("3567889") + "".join(str(r.randint(0, 9)) for _ in range(9))
    if re.fullmatch(r"\d+", v):
        return str(r.randint(10 ** (len(v) - 1), 10 ** len(v) - 1))
    return f"{v}-{r.randint(1000, 9999)}"


def _is_dt(v):
    return bool(v) and bool(re.match(r"^\d{4}-\d{2}-\d{2}", str(v)))


def op_alt_value(body, f, ref=None, alts=None):
    """换一个**合法的**取值 —— 权限/身份类字段就是这样。

    前面那些算子都是「把数据弄坏」。但有一整类规则不是被坏数据触发的,
    而是**同一份数据换个身份就落到另一条规则上**:
    同一个 90 天前的补录请求,`role=顾问` 是「无权补录」,`role=店长` 是「超出补录期限」。
    **这两条码指向完全不同的业务动作,而数据一个字都没变。**

    合法取值的清单只有规格作者知道(schema 里没有 role 这一列),所以由规格给。
    """
    if not alts or f not in body: return None
    cur = str(body.get(f) or "")
    pick = next((v for v in alts.get(f, []) if str(v) != cur), None)
    return dict(body, **{f: pick}) if pick is not None else None


OPS = [("换合法取值", op_alt_value), ("缺字段", op_drop), ("空值", op_empty), ("坏格式", op_garble),
       ("抄已有", op_copy), ("仿冒近似重复", op_impersonate),
       ("时间挪到过去", op_past), ("时间挪到马上", op_soon),
       ("引用不存在", op_bogus_ref)]

# 成对时间字段整体后移,用来撞「起止倒置」之外的时序规则
def op_swap_times(body, f, ref=None):
    dts = [k for k in body if _is_dt(body.get(k))]
    if len(dts) < 2: return None
    a, b = dts[0], dts[1]
    return dict(body, **{a: body[b], b: body[a]})


OPS.append(("时间前后对调", op_swap_times))


def probe(driver, plan, targets, bases, budget=120, log=print):
    """对每个还没撞到的码,轮着试算子,看能不能把它撞出来。

    `bases[表] = [候选基线请求体]` —— 必须是**发出去会成功**的那种。

    ## 基线不干净,整个实验的结论就是假的

    第一版拿「已经建过的记录」当基线,于是它本身就违规(手机号重复) ——
    **每个变异都"触发"了基线自己的错误**,算子和结果之间毫无因果。
    预约那边更彻底:基线里的外键还是没翻译的假 id,所有变异一律返回「客户不存在」,
    把后面所有规则全遮住了。

    而它**看起来有结果** —— 三个码"撞出来了",归因全是错的。
    这比没有结果更骗人。所以现在:**先把基线发一遍,确认它真的成功**,
    不成功就拒绝对这张表出结论,并如实说明原因。
    """
    eps = driver.spec["endpoints"]
    # 每张表试了几次 —— 没有这个,「这张表没撞到」和「这张表压根没试」分不开。
    found, tried, exhausted, skipped, per = {}, 0, False, {}, {}
    for tname, codes in targets.items():
        ep = eps.get(tname, {}).get("create")
        cands = bases.get(tname) or []
        if not ep or not cands or not codes:
            per[tname] = {"试了": 0, "原因": ("规格里没有 create" if not ep else
                                            "没有可用基线" if not cands else "没有要补的码")}
            continue
        t0 = tried

        # ---- 先验基线 ----
        base = None
        for c in cands[:4]:
            if tried >= budget: break
            code, doc, _x = _curl(ep.get("method", "POST"), driver.base + ep["path"],
                                  c, driver.headers)
            tried += 1
            res, why = outcome(doc, code, ep)
            if res == "ok":
                rid = _dig(doc, ep.get("id_path", "id"))
                if rid is not None: driver.created.append((tname, rid))
                base = c
                break
        if base is None:
            skipped[tname] = "基线请求本身就被拒了 —— 变异结果无法归因,拒绝出结论"
            continue
        ref = next((b for t, b in driver.sent_ok if t == tname), base)

        # **验证基线的动作本身改变了系统状态。**
        # 刚才那次验证把基线记录建进去了 —— 于是再拿同一条去变异,
        # 每一个变异都会撞上「和刚建的那条重复」,`DUP_PHONE ← 缺字段 shop`
        # 这种荒唐的归因就是这么来的。**探测污染了探测。**
        #
        # 所以变异用**另一条没发过的**基线(同一个生成器出来的,结构一样),
        # 最后再补一次归因复核。
        # 变异基线还得**换掉那些"业务上唯一"的字段**。
        #
        # `customer.phone` 在数据库里不唯一(所以造数时会重复),
        # 但业务规则要求它唯一 —— 于是基线一发出去就撞 DUP_PHONE,
        # **抢在所有其它规则前面返回**,把 BAD_ADVISOR、NEED_REVIEW 全遮住了。
        #
        # 「哪些字段业务上必须唯一」这件事,schema 里没有、统计也看不出来
        # (源库里它们确实唯一,但那可能只是碰巧)。**只有规格作者知道**,
        # 所以由规格声明 `fresh_fields`。声明不了就如实承认这些码探不到。
        # `fresh_fields` 声明在 **endpoint 层**(和 codes 并列),不在 create 里面。
        # 第一版从 create 里读,取到 None,整段静默不生效 —— 又一次层级看错。
        fresh = eps.get(tname, {}).get("fresh_fields") or []
        alts = eps.get(tname, {}).get("alt_values") or {}
        mut_base = dict(next((c for c in cands if c is not base), base))
        for f in fresh:
            if f in mut_base and mut_base[f]:
                mut_base[f] = _freshen(str(mut_base[f]), tname, f)
        want = set(codes)
        for opname, fn in OPS:
            if not want: break
            fields = list(base) if fn not in (op_impersonate, op_swap_times) else [None]
            for f in fields:
                if not want: break
                if tried >= budget: exhausted = True; break
                cand = _apply(fn, mut_base, f, ref, fresh, alts)
                if cand is None: continue
                # **每一次探测都要是独立实验。**
                # 变异之间会互相污染:前一个「缺一个选填字段」是合法请求,它成功建了记录;
                # 后一个变异就撞上刚建的那条,报 DUP_PHONE ——
                # 于是「缺 advisor」被记成了触发重复手机号的算子,荒唐但看起来有理。
                # 所以每次都换掉业务唯一字段。**唯一性算子除外** ——
                # 它们要的恰恰是撞上已有记录。
                if fn not in (op_copy, op_impersonate):
                    for uf in fresh:
                        if uf in cand and cand[uf]:
                            cand[uf] = _freshen(str(cand[uf]), tname, uf, opname, str(f), tried)
                code, doc, _x = _curl(ep.get("method", "POST"),
                                      driver.base + ep["path"], cand, driver.headers)
                tried += 1
                res, why = outcome(doc, code, ep)
                if res == "ok":
                    # **探测也是写入。** 变异请求成功了就在库里留了一条,必须能回滚。
                    rid = _dig(doc, ep.get("id_path", "id"))
                    if rid is not None: driver.created.append((tname, rid))
                    continue
                c = _code(doc, ep)
                if c in want:
                    found[c] = {"表": tname, "算子": opname,
                                "改的字段": f, "请求体": cand, "接口说": why[:140]}
                    want.discard(c)
            if tried >= budget: exhausted = True; break

        # ---- 归因复核 ----
        # 把**未变异的**基线原样发一次。它要是自己就返回某个码,
        # 那所有被归到那个码上的"发现"都不成立 —— 是基线的锅,不是算子的。
        # 一次请求换一个确定的答案:**没有这一步,归因只是看起来合理。**
        if tried < budget:
            # 复核也要换一次唯一字段。**变异本身会成功建记录**
            # (比如「缺一个选填字段」完全合法),于是原样复核会撞上
            # 变异刚建出来的那一条 —— 同一个污染问题上移了一层。
            # 换掉唯一字段保住了"同一种形状",又不会自己撞自己。
            recheck = dict(mut_base)
            for f in fresh:
                if f in recheck and recheck[f]:
                    recheck[f] = _freshen(str(recheck[f]), tname, f, "复核")
            code, doc, _x = _curl(ep.get("method", "POST"), driver.base + ep["path"],
                                  recheck, driver.headers)
            tried += 1
            res, why = outcome(doc, code, ep)
            if res == "ok":
                rid = _dig(doc, ep.get("id_path", "id"))
                if rid is not None: driver.created.append((tname, rid))
            else:
                bad = _code(doc, ep)
                for c, info in found.items():
                    if c == bad and info["表"] == tname:
                        info["归因存疑"] = (f"未变异的基线自己也返回 {bad} —— "
                                            f"这条不是算子造成的")
        # ---- 还缺的码,试**两两组合** ----
        # 有些规则要几个条件同时成立才触发:`BACKFILL_LIMIT` 要
        # 「role=店长」**且**「时间超过 7 天前」—— 单改一处只会落到别的码上。
        # 这就是组合测试里的 2-way,只不过目标是「撞出某个码」而不是「覆盖参数组合」。
        # 只对**单算子跑完还缺的**码做,而且封顶 —— 组合是平方级的。
        if want and tried < budget:
            singles = []
            for opname, fn in OPS:
                for f in ([None] if fn is op_swap_times else list(mut_base)):
                    if _apply(fn, mut_base, f, ref, fresh, alts) is not None:
                        singles.append((opname, fn, f))
            for i in range(len(singles)):
                if not want or tried >= budget: break
                for j in range(len(singles)):
                    if not want or tried >= budget: break
                    if i == j: continue
                    n1, f1, x1 = singles[i]; n2, f2, x2 = singles[j]
                    if x1 == x2 and f1 is not op_swap_times: continue
                    c1 = _apply(f1, mut_base, x1, ref, fresh, alts)
                    if c1 is None: continue
                    cand = _apply(f2, c1, x2, ref, fresh, alts)
                    if cand is None: continue
                    if f1 not in (op_copy, op_impersonate) and \
                       f2 not in (op_copy, op_impersonate):
                        for uf in fresh:
                            if uf in cand and cand[uf]:
                                cand[uf] = _freshen(str(cand[uf]), tname, uf, n1, n2, tried)
                    code, doc, _x = _curl(ep.get("method", "POST"),
                                          driver.base + ep["path"], cand, driver.headers)
                    tried += 1
                    res, why = outcome(doc, code, ep)
                    if res == "ok":
                        rid = _dig(doc, ep.get("id_path", "id"))
                        if rid is not None: driver.created.append((tname, rid))
                        continue
                    c = _code(doc, ep)
                    if c in want:
                        found[c] = {"表": tname, "算子": f"{n1} + {n2}",
                                    "改的字段": f"{x1} / {x2}", "请求体": cand,
                                    "接口说": why[:140], "组合": True}
                        want.discard(c)

        per[tname] = {"试了": tried - t0}
    return {"撞出来的": found, "试了": tried, "每张表": per, "预算": budget, "预算用光": exhausted,
            "跳过的表": skipped,
            "说明": "预算用光时,「没撞到」不等于「撞不到」—— 只是没试到。"
                    "基线被拒的表直接跳过:基线不干净,归因就是假的。"}
