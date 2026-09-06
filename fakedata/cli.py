#!/usr/bin/env python3
"""假数据工厂 · 命令行入口。

    python3 fakedata/cli.py plan     <目标> --env test [--scale 0.2] [--tables a,b]
    python3 fakedata/cli.py load     <目标> --env test --plan .fakedata/x.plan.json [--yes]
    python3 fakedata/cli.py verify   <目标> --env test --plan .fakedata/x.plan.json
    python3 fakedata/cli.py rollback <目标> --env test --manifest .fakedata/x.manifest.json --yes

目标写法:`backend/lanxiu.db` 或 `mysql://user:pass@host:3306/dbname`

**默认全是 dry-run。** 要真写库,每一步都得自己再加 `--yes` ——
造数工具的默认值只有一个正确选项:什么都不做。
"""
import os, sys, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, guard, load as L


def _outdir():
    d = os.path.join(ROOT, ".fakedata"); os.makedirs(d, exist_ok=True); return d


def cmd_plan(a):
    print(guard.check_target(a.target, a.env))
    print(guard.readonly_sample_notice())
    conn = S.connect(a.target); sc = conn.reflect()
    tables = [t.strip() for t in a.tables.split(",")] if a.tables else None
    if tables:
        miss = [t for t in tables if t not in sc.tables]
        if miss: raise SystemExit(f"这些表不存在: {miss}")
    print(f"\n反射: {len(sc.tables)} 张表 / "
          f"{sum(len(t.declared_fks) for t in sc.tables.values())} 个明写外键")
    facts = D.discover(conn, sc, tables)
    nfk = sum(len(tf["fks"]) for tf in facts["tables"].values())
    print(f"推断: 挖出 {nfk} 条表关系")

    base = os.path.join(_outdir(), f'{sc.label.replace("/", "_")}-{a.seed}')
    ov = None
    if a.overlay:
        ov = json.load(open(a.overlay, encoding="utf-8"))
        print(f"模型层: 复用已有判定 {a.overlay}(**不调模型**)")
    elif a.infer:
        import infer_llm as I
        pl0 = P.build(facts, seed=a.seed, scale=a.scale, tables=tables,
                      allow_no_pk=a.allow_no_pk)
        print("模型层: 调一次模型,只判统计推不出来的那部分")
        ov, dropped, meta = I.infer(facts, pl0)
        I.save(base + ".overlay.json", ov, dropped, meta)
        print(f'  {meta["model"]} · {meta["耗时秒"]}s · '
              f'in {meta["usage"].get("input_tokens")} / out {meta["usage"].get("output_tokens")}')
        if dropped:
            print(f"  校验丢弃 {len(dropped)} 条(模型说的对不上真实 schema):")
            for d in dropped[:6]: print(f"    - {d}")
        print(f'  判定存到 {base}.overlay.json —— 人可以直接改,下次用 --overlay 复用')
    if ov:
        facts, log = P.apply_overlay(facts, ov)
        print(f"  盖到事实层的判定 {len(log)} 条:")
        for l in log[:8]: print(f"    · {l}")
        if len(log) > 8: print(f"    · …还有 {len(log)-8} 条")

    pl = P.build(facts, seed=a.seed, scale=a.scale, tables=tables,
                 allow_no_pk=a.allow_no_pk)
    with open(base + ".plan.json", "w", encoding="utf-8") as f:
        json.dump(pl, f, ensure_ascii=False, indent=1)
    md = P.to_markdown(pl)
    with open(base + ".方案预览.md", "w", encoding="utf-8") as f:
        f.write(md)
    todo = sum(1 for tp in pl["tables"].values() for g in tp["columns"].values() if "需确认" in g)
    skip = sum(1 for tp in pl["tables"].values() if tp.get("skip"))
    nfsm = sum(1 for tp in pl["tables"].values() for g in tp["columns"].values()
               if g["gen"] == "fsm")
    print(f'\n方案: {len(pl["tables"])} 张表 / 环 {len(pl["deferred_fks"])} 条 / '
          f'断言 {len(pl["assertions"])} 条 / 待确认 {todo} 处 / 跳过 {skip} 张'
          + (f' / 状态机 {nfsm} 个' if nfsm else ""))
    print(f'  机器读 → {base}.plan.json')
    print(f'  人读   → {base}.方案预览.md   ← **先看这个再灌**')


def cmd_load(a):
    print(guard.check_target(a.target, a.env, write=True))
    pl = json.load(open(a.plan, encoding="utf-8"))
    conn = S.connect(a.target)
    made, man = G.generate(pl, conn)
    n = sum(len(v) for v in made.values())
    if not a.yes:
        _, sample = L.load(conn, pl, made, dry=True, log=lambda *x: None)
        print(f"\n【dry-run】将灌入 {n} 行,分 {len([k for k,v in made.items() if v])} 张表")
        if sample: print(f"  首条 SQL: {sample[0]}\n  首条值:   {sample[1][:8]}")
        print(f'  回填(两阶段): {len(pl["deferred_fks"])} 条边')
        print("\n没有写任何东西。确认无误后加 --yes 真正灌入。")
        return
    print(f"\n基线自检…")
    before = L.run_assertions(conn, pl)
    L.load(conn, pl, made, dry=False)
    L.fill_deferred(conn, pl, made, dry=False)
    conn.commit()
    mpath = guard.manifest_path(ROOT, pl["source"])
    guard.write_manifest(mpath, pl, man, a.env)
    after = L.run_assertions(conn, pl)
    worse, pre, skip = L.compare(before, after, pl)
    print(f"\n灌入 {n} 行 · 断言 {len(pl['assertions'])} 条")
    print(f"  本来就脏: {len(pre)} 条(不是你造成的)")
    print(f"  我弄脏的: {len(worse)} 条" + ("  ✅" if not worse else "  ❌"))
    for k, b, aa, note in worse[:20]:
        print(f"    ✗ {k}: {b} → {aa}" + (f"  [{note}]" if note else ""))
    print(f"\n回滚凭据 → {mpath}")


def cmd_verify(a):
    print(guard.check_target(a.target, a.env))
    pl = json.load(open(a.plan, encoding="utf-8"))
    conn = S.connect(a.target)
    res = L.run_assertions(conn, pl)
    bad = {k: v for k, v in res.items() if v}
    print(f"断言 {len(res)} 条 · 不为 0 的 {len(bad)} 条")
    for k, v in list(bad.items())[:30]: print(f"  ✗ {k}: {v}")
    raise SystemExit(1 if bad else 0)


def cmd_rollback(a):
    print(guard.check_target(a.target, a.env, write=True))
    doc = guard.read_manifest(a.manifest)
    conn = S.connect(a.target)
    n = L.rollback(conn, doc, dry=not a.yes,
                   log=print if a.yes else lambda *x: None)
    if a.yes:
        conn.commit(); print(f"\n已删除 {n} 行(照 manifest,不猜)")
    else:
        print(f"\n【dry-run】将删除 {n} 行。确认后加 --yes。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="假数据工厂")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("target"); p.add_argument("--env", required=True,
                       help="dev|test|staging —— 必须显式声明,不做自动识别")
    p1 = sub.add_parser("plan");  common(p1)
    p1.add_argument("--scale", type=float, default=1.0)
    p1.add_argument("--seed", type=int, default=20260906)
    p1.add_argument("--tables", default=None)
    p1.add_argument("--allow-no-pk", action="store_true")
    p1.add_argument("--infer", action="store_true",
                    help="调一次模型补语义(否决误报关系/认领无语义列/推状态机)")
    p1.add_argument("--overlay", default=None,
                    help="复用已有的模型判定文件,不调模型")
    p1.set_defaults(fn=cmd_plan)
    p2 = sub.add_parser("load");  common(p2)
    p2.add_argument("--plan", required=True); p2.add_argument("--yes", action="store_true")
    p2.set_defaults(fn=cmd_load)
    p3 = sub.add_parser("verify"); common(p3)
    p3.add_argument("--plan", required=True); p3.set_defaults(fn=cmd_verify)
    p4 = sub.add_parser("rollback"); common(p4)
    p4.add_argument("--manifest", required=True); p4.add_argument("--yes", action="store_true")
    p4.set_defaults(fn=cmd_rollback)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    main()
