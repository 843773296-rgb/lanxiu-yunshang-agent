#!/usr/bin/env python3
"""规模基准 —— 把「Agent 做一次,程序跑一万次」这句话真的跑一次。

**不进 check.sh**:它要几分钟和几百 MB 内存,不该拦在门禁上。人手动跑那一类。

## 为什么要专门测这个

这个工具全部的设计理由都建立在一句话上:模型只产规则,程序去执行,
所以**要多少有多少**。而实测到目前为止最大就是几百行 —— 这句核心主张一直没被验证过。
「代码就位」和「验证过」是两件事,这一条在 MySQL 那一刀刚说过,这里同样适用。

## 分阶段测,不测总时间

只知道「10 万行要 5 分钟」没有用。要知道**哪一步吃掉了这 5 分钟**:
是生成、是插入、还是灌完之后那 341 条断言各扫一遍全表。
三者的优化方向完全不同,而且第三条的成本是**跟着数据量线性涨的**,
它很可能才是真正的墙。

峰值内存同理:生成器把所有行攒在内存里,这是个 O(总行数) 的设计 ——
在几百行上看不出来,在百万行上就是它本身。
"""
import os, sys, json, time, shutil, resource, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, load as L, infer_llm as I

def rss_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024   # mac 是字节

class Step:
    def __init__(self, name, out): self.name, self.out = name, out
    def __enter__(self): self.t = time.time(); return self
    def __exit__(self, *a):
        self.out[self.name] = round(time.time() - self.t, 2)


def run(scale, overlay=None, do_rollback=True, log=print, stream=False):
    tmp = os.path.join(tempfile.mkdtemp(), f"bench_test_{scale}.db")
    shutil.copy(os.path.join(ROOT, "backend", "lanxiu.db"), tmp)
    t = {}
    conn = S.connect(tmp)
    with Step("反射", t): sc = conn.reflect()
    with Step("推断", t): facts = D.discover(conn, sc)
    if overlay:
        ov, _dp = I.validate(overlay, facts, P.build(facts, scale=0.01))
        facts, _lg = P.apply_overlay(facts, ov)
    with Step("方案", t): pl = P.build(facts, scale=scale)
    with Step("基线自检", t): before = L.run_assertions(conn, pl)
    if stream:
        with Step("生成+灌入(流式)", t):
            made, man = G.generate(pl, conn, sink=L.sink_for(conn, pl))
            L.fill_deferred(conn, pl, made, dry=False, log=lambda *x: None)
            conn.commit()
        rows = sum(len(v) for v in made.values())
    else:
        with Step("生成", t): made, man = G.generate(pl, conn)
        rows = sum(len(v) for v in made.values())
        with Step("灌入", t):
            L.load(conn, pl, made, dry=False, log=lambda *x: None)
            L.fill_deferred(conn, pl, made, dry=False, log=lambda *x: None)
            conn.commit()
    with Step("灌后自检", t): after = L.run_assertions(conn, pl)
    worse, pre, _s = L.compare(before, after, pl)
    doc = {"顺序": pl["order"], "表": {k: {"pk": m["pk"], "主键": m["values"]}
                                       for k, m in man.items()}}
    mf = len(json.dumps(doc, ensure_ascii=False)) / 1e6
    if do_rollback:
        with Step("回滚", t):
            L.rollback(conn, doc, dry=False, log=lambda *x: None); conn.commit()
    dbmb = os.path.getsize(tmp) / 1e6
    conn.close(); shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    return {"scale": scale, "行数": rows, "断言": len(pl["assertions"]),
            "阶段": t, "总秒": round(sum(t.values()), 2),
            "行每秒": int(rows / max(t.get("生成", 0) + t.get("灌入", 0)
                                      + t.get("生成+灌入(流式)", 0), .01)),
            "峰值内存MB": round(rss_mb(), 1), "manifestMB": round(mf, 2),
            # ⚠️ **只打个数字「1」是不够的** —— 2026-09-21 bench 连着三档都报
            # 「新违规 1」,而不说是哪一条,于是它在报表上躺了很久没人去查。
            # 查出来是真问题(`shift_tpl` 的时刻文本没被时间修正覆盖)。
            # 一个只给数量不给名字的报告,和「还有 N 条没显示」是同一个病。
            "库MB": round(dbmb, 1), "新违规": len(worse),
            "新违规明细": [str(k)[:70] for k in worse][:3]}


if __name__ == "__main__":
    scales = [float(x) for x in sys.argv[1:]] or [1, 5, 20]
    ovp = os.path.join(ROOT, ".fakedata", "lanxiu.db-20260906.overlay.json")
    ov = json.load(open(ovp, encoding="utf-8")) if os.path.exists(ovp) else None
    print(f"overlay: {'复用已有判定(不调模型)' if ov else '无'}\n")
    head = f'{"scale":>6} {"行数":>9} {"总秒":>7} {"行/秒":>8} {"峰值MB":>8} ' \
           f'{"manifest":>9} {"库MB":>7} {"新违规":>6}'
    print(head); print("-" * len(head))
    rs = []
    for s in scales:
        r = run(s, ov, stream=os.environ.get("STREAM") == "1")
        rs.append(r)
        print(f'{r["scale"]:>6} {r["行数"]:>9,} {r["总秒"]:>7} {r["行每秒"]:>8,} '
              f'{r["峰值内存MB"]:>8} {r["manifestMB"]:>8}MB {r["库MB"]:>6} {r["新违规"]:>6}')
        for x in r.get("新违规明细") or []:
            print(f'        ⚠️ 弄脏了:{x}')
    print("\n各阶段耗时(秒):")
    ks = ["反射", "推断", "方案", "生成", "基线自检", "灌入", "生成+灌入(流式)",
          "灌后自检", "回滚"]
    print(f'{"scale":>6} ' + " ".join(f"{k:>9}" for k in ks))
    for r in rs:
        print(f'{r["scale"]:>6} ' + " ".join(f'{r["阶段"].get(k, 0):>9}' for k in ks))
