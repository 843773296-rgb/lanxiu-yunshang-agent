#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词候选版本 —— **改提示词不许直接改源头。**

## 纪律(2026-09-24 定,2026-09-25 落地)

    候选版本  →  跑验证集  →  并排比分  →  采纳才落回源头

直接改线上那份的代价有两条,而且都不显眼:
  · 分数变了**说不清是哪一处改动带来的** —— 一次动了多维就归不了因
  · 改坏了**没有第二份可以比** —— 你只能凭印象说「好像以前更好」

## 怎么用

    python3 tools/prompt_candidate.py 新建 <号> --改 TL53 --为什么 "..."   # 从源头拷一份出来编辑
    python3 tools/prompt_candidate.py 看 <号>                              # 看它改了哪几条、差在哪
    LANXIU_PROMPT_CANDIDATE=<号> ./agentsite/.venv/bin/python agent/xxx_eval.py
    python3 tools/prompt_candidate.py 记一次 <号> --结果 agent/xxx-eval-results.jsonl
    python3 tools/prompt_candidate.py 采纳 <号>                            # 落回 prompts.py

## 三条刻意的限制

① **采纳前必须有验证记录。** 没跑过验证集就落回源头,等于把这套流程绕过去了 ——
   而绕过去之后,它和「直接改源头」一模一样。
② **候选只在显式指定时生效**(环境变量)。默认永远是源头那一份 ——
   一个「不小心就生效了」的覆盖层,比没有这个机制更危险。
③ **采纳时逐条核对源头还是不是当初拷出去的那一版。** 中间有人动过源头的话,
   直接覆盖会把别人的改动吃掉 —— 而 git 上看起来只是「采纳了一个候选」。
"""
import datetime as dt, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
目录 = os.path.join(ROOT, ".feynman", "prompt_candidates")
sys.path.insert(0, ROOT)

咬合 = [
    ("把「采纳前必须有验证记录」那一支去掉", "没跑过验证集不许采纳"),
    ("让候选在没设环境变量时也生效", "不指定就用源头那一份"),
    ("采纳时不核对源头是不是当初那一版", "源头被人动过就不许直接覆盖"),
]


def _规矩():
    import prompts
    return {r.id: r for _, r in prompts.all_rules(unique=True)}


def _读(号):
    f = os.path.join(目录, f"{号}.json")
    if not os.path.exists(f): sys.exit(f"没有候选 {号}(找的是 {f})")
    return json.load(open(f, encoding="utf-8"))


def _写(号, d):
    os.makedirs(目录, exist_ok=True)
    json.dump(d, open(os.path.join(目录, f"{号}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def 新建(号, 改哪几条, 为什么):
    规 = _规矩()
    缺 = [x for x in 改哪几条 if x not in 规]
    if 缺: sys.exit(f"没有这几条规矩:{缺} —— 现在共 {len(规)} 条")
    d = dict(号=号, 建于=dt.datetime.now().isoformat(timespec="seconds"),
             为什么=为什么,
             # **把拷出去时源头长什么样一起存着** —— 采纳时要核对,
             # 中间有人动过源头的话,直接覆盖会把别人的改动吃掉
             拷自={x: 规[x].text for x in 改哪几条},
             改={x: 规[x].text for x in 改哪几条},
             验证=[])
    _写(号, d)
    print(f"建好了:{os.path.join(目录, 号)}.json")
    print(f"  改哪几条:{'、'.join(改哪几条)}")
    print(f"  **现在去编辑那个文件里的「改」字段**,然后:")
    print(f"    LANXIU_PROMPT_CANDIDATE={号} ./agentsite/.venv/bin/python agent/<评测>.py")
    return d


def 看(号):
    d = _读(号)
    print(f"候选 {号} · 建于 {d['建于']}")
    print(f"为什么:{d.get('为什么') or '(没写)'}")
    print(f"验证跑过 {len(d.get('验证') or [])} 次")
    for x in d.get("验证") or []:
        print(f"   · {x['时间']} {x['结果文件']} {x.get('过')}/{x.get('题数')}")
    现 = _规矩()
    for rid, 新 in (d.get("改") or {}).items():
        旧 = (d.get("拷自") or {}).get(rid, "")
        print(f"\n── {rid} ──")
        if 新.strip() == 旧.strip():
            print("   (和拷出去时一样 —— **还没改**,改了再跑)")
            continue
        for 行 in _差(旧, 新): print("   " + 行)
        if rid in 现 and 现[rid].text.strip() != 旧.strip():
            print(f"   ⚠️ **源头已经被人动过**(和拷出去那一版不同)—— 采纳前要重新拷")
    return d


def _差(旧, 新):
    import difflib
    return [l.rstrip() for l in difflib.unified_diff(
        旧.strip().splitlines(), 新.strip().splitlines(),
        fromfile="源头", tofile="候选", lineterm="", n=1)]


def 记一次(号, 结果文件):
    """把一次验证集的结果挂到这个候选上 —— **分数要能追到是哪一版跑的**。"""
    d = _读(号)
    p = os.path.join(ROOT, 结果文件)
    if not os.path.exists(p): sys.exit(f"没有这个结果文件:{结果文件}")
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    过 = sum(1 for r in rows if str(r.get("passed")).lower() in ("true", "1"))
    d.setdefault("验证", []).append(dict(
        时间=dt.datetime.now().isoformat(timespec="seconds"),
        结果文件=结果文件, 题数=len(rows), 过=过,
        模型=next((r.get("模型") for r in rows if r.get("模型")), None),
        代码=next((r.get("代码") for r in rows if r.get("代码")), None)))
    _写(号, d)
    print(f"记下了:{结果文件} {过}/{len(rows)}")
    return d


def 采纳(号, 硬来=False):
    d = _读(号)
    if not (d.get("验证") or []) and not 硬来:
        sys.exit("❌ 没跑过验证集不许采纳 —— 绕过这一步之后,它和「直接改源头」一模一样。\n"
                 "   先 LANXIU_PROMPT_CANDIDATE=%s 跑一遍验证集,再 记一次。" % 号)
    src = open(os.path.join(ROOT, "prompts.py"), encoding="utf-8").read()
    现 = _规矩()
    改了 = []
    for rid, 新 in (d.get("改") or {}).items():
        旧 = (d.get("拷自") or {})[rid]
        if 新.strip() == 旧.strip(): continue
        if rid not in 现: sys.exit(f"❌ 源头里已经没有 {rid} 了")
        if 现[rid].text.strip() != 旧.strip():
            sys.exit(f"❌ 源头被人动过就不许直接覆盖({rid})——\n"
                     f"   你拷出去的那一版和现在的源头已经不一样了,直接盖会把别人的改动吃掉,\n"
                     f"   而 git 上看起来只是「采纳了一个候选」。重新拷一份再改。")
        if 旧.strip() not in src:
            sys.exit(f"❌ 在 prompts.py 里找不到 {rid} 的原文 —— 可能被重新排版过,手工改")
        src = src.replace(旧.strip(), 新.strip(), 1)
        改了.append(rid)
    if not 改了: sys.exit("这个候选一条都没改,没什么可采纳的")
    open(os.path.join(ROOT, "prompts.py"), "w", encoding="utf-8").write(src)
    d["采纳于"] = dt.datetime.now().isoformat(timespec="seconds")
    _写(号, d)
    print(f"✅ 落回 prompts.py:{'、'.join(改了)}")
    print("   **跑一遍 ./check.sh 再提交** —— 提示词有结构检查(按工具装配、编号唯一)")
    return 改了


def 列表():
    if not os.path.isdir(目录): return []
    出 = []
    for f in sorted(os.listdir(目录)):
        if not f.endswith(".json"): continue
        d = json.load(open(os.path.join(目录, f), encoding="utf-8"))
        出.append(dict(号=d.get("号") or f[:-5], 建于=d.get("建于"),
                       为什么=d.get("为什么"), 改了=list((d.get("改") or {})),
                       验证次数=len(d.get("验证") or []),
                       最近=(d.get("验证") or [{}])[-1] if d.get("验证") else None,
                       采纳于=d.get("采纳于"),
                       动过=[rid for rid, 新 in (d.get("改") or {}).items()
                             if 新.strip() != (d.get("拷自") or {}).get(rid, "").strip()]))
    return 出


def _自测():
    import tempfile, shutil
    过, 挂 = [], []
    def ck(名, 真, 补=""):
        (过 if 真 else 挂).append(名)
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")

    import prompts
    # ① 不指定就用源头那一份
    os.environ.pop("LANXIU_PROMPT_CANDIDATE", None)
    ck("不指定就用源头那一份", prompts.候选覆盖() == {})

    # ② 指定了却找不到 → 当场抛,不静默退回
    os.environ["LANXIU_PROMPT_CANDIDATE"] = "根本没有这个号"
    try:
        prompts.候选覆盖(); 中 = False
    except RuntimeError as e:
        中 = "不退回源头" in str(e)
    ck("指定了候选却找不到 → 当场抛(不静默退回源头)", 中)

    # ③ 真的套上了
    os.makedirs(目录, exist_ok=True)
    _写("_自测", dict(号="_自测", 建于="x", 改={"TL53": "这是候选的正文"},
                     拷自={"TL53": prompts.DATE_RULE.text}, 验证=[]))
    os.environ["LANXIU_PROMPT_CANDIDATE"] = "_自测"
    ck("指定之后真的套上了", prompts.候选覆盖().get("TL53") == "这是候选的正文")
    t, _ = prompts.assemble("kb", {"kb_lookup"})
    ck("装配出来的提示词里是候选的正文", "这是候选的正文" in t)
    os.environ.pop("LANXIU_PROMPT_CANDIDATE", None)
    t2, _ = prompts.assemble("kb", {"kb_lookup"})
    ck("取消之后又回到源头", "这是候选的正文" not in t2)

    # ④ 没验证记录不许采纳
    import io, contextlib
    挂了 = False
    try:
        with contextlib.redirect_stdout(io.StringIO()): 采纳("_自测")
    except SystemExit as e:
        挂了 = "没跑过验证集不许采纳" in str(e)
    ck("没跑过验证集不许采纳", 挂了)

    # ⑤ 源头被人动过就不许直接覆盖
    _写("_自测2", dict(号="_自测2", 建于="x", 改={"TL53": "新正文"},
                      拷自={"TL53": "这不是源头现在的样子"},
                      验证=[dict(时间="x", 结果文件="y", 题数=1, 过=1)]))
    挂了 = False
    try:
        with contextlib.redirect_stdout(io.StringIO()): 采纳("_自测2")
    except SystemExit as e:
        挂了 = "源头被人动过就不许直接覆盖" in str(e)
    ck("源头被人动过就不许直接覆盖", 挂了)

    for f in ("_自测.json", "_自测2.json"):
        try: os.remove(os.path.join(目录, f))
        except OSError: pass
    print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "--selftest": sys.exit(_自测() if a else (print(__doc__), 0)[1])
    cmd = a[0]
    def 取(名, 默=None):
        return a[a.index(名) + 1] if 名 in a and a.index(名) + 1 < len(a) else 默
    if cmd == "新建":
        改 = (取("--改") or "").split(",")
        新建(a[1], [x for x in 改 if x], 取("--为什么", ""))
    elif cmd == "看": 看(a[1])
    elif cmd == "记一次": 记一次(a[1], 取("--结果"))
    elif cmd == "采纳": 采纳(a[1], 硬来="--硬来" in a)
    elif cmd == "列表":
        for x in 列表():
            print(f"  {x['号']:14s} 改 {'、'.join(x['改了'])}  验证 {x['验证次数']} 次"
                  + ("  已采纳" if x["采纳于"] else "") + f"  {x['为什么'] or ''}")
    else: sys.exit(f"不认识的命令:{cmd}\n{__doc__}")
