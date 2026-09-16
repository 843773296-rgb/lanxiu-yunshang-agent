#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计普查 —— **把分布带出来,不把数据带出来。**

## 为什么要这一层

真实企业里最常见的需求和最硬的红线正好撞在一起:

    需求:测试库要**像生产** —— 不然测出来的性能、分页、空状态全是假的
    红线:**生产数据一行都不许出域**

中间那条路是:只把**形状**带出来 —— 每列的空值率、取值有多少种、长度分布、
数值的分位数、父子扇出比例 —— 在测试环境按形状造。

## ⚠️ 摘要**自己也会泄露**,这是这一层真正的难点

第一眼看「统计摘要」像是天然安全的,其实不是:

    枚举值      一个只出现过 **1 次**的取值,导出来就等于导出了**那一条记录**
                (`status` 里混进一个 `VIP-某某某专属`,它就是一个人名)
    极值        `max(salary)` 往往**就是某一个人的工资**;min 同理
    高基数文本  `distinct == 行数` 的文本列,任何取值样本都是原始数据
    小分组      某个取值只有 2 条记录时,它的均值几乎等于把那两条读出来

所以这里做三件事,而且每一件都要**说出来抹了什么**:

    低频抑制   出现次数 < k(默认 5)的取值**不导出具体值**,只留「其它(n 种,占比 x)」
    极值剪裁   数值/日期不导 min/max,导 **p1/p99** —— 极值就是某一条记录
    文本不导值 文本列只导**形状**(长度分布、像不像邮箱/手机号),一个真实值都不带

## 不做差分隐私

差分隐私要加噪声、要管隐私预算,是另一个量级的东西。
**这里做的是 k-匿名式的抑制 + 极值剪裁,不是差分隐私** ——
把它说成差分隐私,是在给一个没做过的保证背书。

## 产物就是「脱敏过的事实层」

摘要的结构**故意做成和 `discover` 的事实层同构**,所以它能直接喂给 `plan.build`:

    生产库 ──普查──> 摘要(可以带出机房) ──plan.build──> 方案 ──> 在测试库造数

测试环境**不需要连生产库**,只要这份摘要 + 目标库的表结构。
"""
import json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

默认k = 5


def _pct(xs, p, k=0):
    """分位数。`k>0` 时**把首尾各 k 条挡在外面**。

    ⚠️ **分位数在小样本上等于极值。** 41 行数据的 p99,下标 round(0.99×40)=40,
    正好是排序后的最后一条 —— 也就是 max 本人。
    「改用 p1/p99 就不会导出极值」这个假设**在小样本上不成立**,自测当场抓到:
    摘要里原样出现了那个离群的 999999。

    所以取值范围要收进 [k, len-1-k]:保证任何一个分位点背后**至少还有 k 条记录**,
    和低频抑制是同一个 k。
    """
    if not xs:
        return None
    s = sorted(xs)
    lo, hi = (k, len(s) - 1 - k) if k and len(s) > 2 * k else (0, len(s) - 1)
    if lo > hi:
        return None
    i = min(hi, max(lo, int(round(p * (len(s) - 1)))))
    return s[i]


def _形状(值):
    """文本只导形状,一个真实值都不带。"""
    if 值 is None:
        return None
    s = str(值)
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", s, re.I):
        return "像邮箱"
    if re.fullmatch(r"1\d{10}", s):
        return "像手机号"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", s):
        return "像日期时间"
    if re.fullmatch(r"[A-Za-z]+[-_]?\d+", s):
        return "像编号(字母+数字)"
    if re.fullmatch(r"[\d.]+", s):
        return "像数字串"
    if re.search(r"[一-龥]", s):
        return "含中文"
    return "普通文本"


def 普查(conn, sc, tables=None, k=默认k, 采样上限=200000):
    """从库里量出形状,**同时把可能泄露的都抹掉**。返回摘要(结构和事实层同构)。"""
    名单 = tables or sorted(sc.tables)
    摘要 = {"来源": getattr(conn, "label", "?"), "方言": sc.dialect,
            "普查时间": time.strftime("%Y-%m-%d %H:%M"), "k": k,
            "抹掉了什么": [], "tables": {}}
    for t in 名单:
        tb = sc.tables.get(t)
        if not tb:
            continue
        try:
            rows = conn.q(f"select count(*) from {conn.ident(t)}")[0][0]
        except Exception:
            continue
        tf = {"rows": rows, "pk": list(tb.pk), "columns": {}}
        for col in tb.columns:
            c = col.name
            try:
                vals = [r[0] for r in conn.q(
                    f"select {conn.ident(c)} from {conn.ident(t)} limit {采样上限}")]
            except Exception:
                continue
            非空 = [v for v in vals if v is not None]
            cf = {"type": col.type_raw, "kind": col.kind, "nullable": col.nullable,
                  "pk": col.pk, "unique": col.unique,
                  "null_rate": round(1 - len(非空) / len(vals), 3) if vals else None,
                  "distinct": len(set(非空))}

            if col.kind in ("int", "real") and 非空:
                nums = [v for v in 非空 if isinstance(v, (int, float))]
                if nums and len(nums) > 2 * k:
                    # **极值不导** —— max 往往就是某一条记录本人;
                    # 而且分位点也要把首尾各 k 条挡在外面(见 _pct 里那段)
                    cf["range"] = {"p1": _pct(nums, 0.01, k), "p50": _pct(nums, 0.5, k),
                                   "p90": _pct(nums, 0.9, k), "p99": _pct(nums, 0.99, k)}
                    摘要["抹掉了什么"].append(
                        f"{t}.{c}:极值和首尾各 {k} 条 —— 极值常常就是某一条记录,"
                        f"而**小样本上的分位数等于极值**")
                elif nums:
                    # 样本太少,连分位数都不该导 —— 每个分位点背后都不足 k 条记录
                    cf["范围没导"] = f"只有 {len(nums)} 个非空值,不足 2k({2*k}),分位数会贴着某一条记录"
                    摘要["抹掉了什么"].append(
                        f"{t}.{c}:**连分位数都没导** —— 只有 {len(nums)} 个值,分位点背后不足 {k} 条")
            elif 非空:
                长 = [len(str(v)) for v in 非空]
                cf["len"] = {"p50": _pct(长, 0.5), "max": max(长)}
                # 低基数才可能是枚举;而**低频取值一律不导具体值**
                if cf["distinct"] <= 50:
                    计 = {}
                    for v in 非空:
                        计[v] = 计.get(v, 0) + 1
                    留 = {str(v): round(n / len(非空), 4) for v, n in 计.items() if n >= k}
                    抑 = [v for v, n in 计.items() if n < k]
                    if 留:
                        cf["enum"] = 留
                    if 抑:
                        cf["其它"] = {"种数": len(抑),
                                      "占比": round(sum(计[v] for v in 抑) / len(非空), 4)}
                        摘要["抹掉了什么"].append(
                            f"{t}.{c}:{len(抑)} 个出现不足 {k} 次的取值 —— "
                            f"**只出现一次的取值等于那一条记录本身**")
                else:
                    # 高基数文本:一个真实值都不导,只导形状构成
                    形 = {}
                    for v in 非空[:2000]:
                        s = _形状(v)
                        形[s] = 形.get(s, 0) + 1
                    tot = sum(形.values()) or 1
                    cf["形状"] = {s: round(n / tot, 3) for s, n in 形.items()}
                    摘要["抹掉了什么"].append(f"{t}.{c}:高基数文本,**一个真实值都没导**,只导形状")
            tf["columns"][c] = cf
        摘要["tables"][t] = tf
    return 摘要


def 查泄露(摘要, k=None):
    """**摘要出门前自己再查一遍。** 返回还可能泄露的地方(空 = 没查出来)。

    这不是形式:抑制规则写错一个不等号,摘要照样生成、照样看起来正常 ——
    **泄露不会报错**。
    """
    k = k or 摘要.get("k") or 默认k
    坏 = []
    for t, tf in 摘要.get("tables", {}).items():
        rows = tf.get("rows") or 0
        for c, cf in tf.get("columns", {}).items():
            for v, p in (cf.get("enum") or {}).items():
                if rows and p * rows < k:
                    坏.append({"在哪": f"{t}.{c}", "毛病": f"取值「{v}」只覆盖约 {p*rows:.0f} 行,"
                                                          f"低于 k={k},**不该导出具体值**"})
            if any(x in cf for x in ("min", "max")):
                坏.append({"在哪": f"{t}.{c}", "毛病": "导出了极值 —— 极值常常就是某一条记录"})
            # 小样本还导分位数 —— 那些分位点其实就贴着某一条记录(自测抓到过一次)
            if cf.get("range") and rows and rows <= 2 * k:
                坏.append({"在哪": f"{t}.{c}",
                           "毛病": f"只有 {rows} 行却导出了分位数(不足 2k={2*k})——"
                                   f"**小样本上的分位数等于极值**"})
            if cf.get("enum") and cf.get("distinct") and cf["distinct"] >= (rows or 0) > 0:
                坏.append({"在哪": f"{t}.{c}", "毛病": "每行一个不同取值(distinct == 行数),"
                                                      "**任何取值样本都是原始数据**"})
    return 坏


def 审计(摘要, log=print):
    """人读的那一份:导了什么、抹了什么。**看得懂才敢往外发。**"""
    n表 = len(摘要.get("tables", {}))
    n列 = sum(len(tf.get("columns", {})) for tf in 摘要.get("tables", {}).values())
    log(f"统计普查 · 来源 {摘要.get('来源')} · {摘要.get('普查时间')} · k={摘要.get('k')}")
    log(f"  量了 {n表} 张表 / {n列} 列;**导出的全是形状,没有一行原始数据**")
    抹 = 摘要.get("抹掉了什么") or []
    log(f"  抹掉 {len(抹)} 处:")
    for x in 抹[:10]:
        log(f"    · {x}")
    if len(抹) > 10:
        log(f"    · …还有 {len(抹) - 10} 处")
    坏 = 查泄露(摘要)
    if 坏:
        log(f"  ❌ **出门自查没过**:{len(坏)} 处仍可能泄露")
        for x in 坏[:6]:
            log(f"    · {x['在哪']}:{x['毛病']}")
    else:
        log("  ✅ 出门自查:低频取值都抑制了、没导极值、没有「每行一个值」的列被当成枚举")
    return 坏


def 转事实(摘要):
    """摘要 → 事实层(能直接喂给 `plan.build`)。

    **关系挖不出来** —— 那要看值的重叠,而摘要里没有值。所以这里的 `fks` 一律为空:
    要么在目标库上另跑一次关系推断(结构是公开的,不涉及数据),要么人手写。
    **这是个真限制,不是忘了做。**
    """
    facts = {"source": f"摘要:{摘要.get('来源')}", "dialect": 摘要.get("方言", "sqlite"),
             "中文库": True, "tables": {}}
    for t, tf in 摘要.get("tables", {}).items():
        cols = {}
        for c, cf in tf.get("columns", {}).items():
            f = {k: v for k, v in cf.items()
                 if k in ("type", "kind", "nullable", "pk", "unique", "null_rate",
                          "distinct", "len", "range", "enum")}
            f.setdefault("comment", "")
            f["confidence"] = "摘要"
            if cf.get("enum"):
                f["semantic"] = "enum"
            cols[c] = f
        facts["tables"][t] = {"rows": tf.get("rows", 0), "pk": tf.get("pk", []),
                              "columns": cols, "fks": [], "时间序": [], "joint": []}
    return facts


def 存(path, 摘要):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(摘要, f, ensure_ascii=False, indent=1)
    return path


def 读(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
