# -*- coding: utf-8 -*-
"""能力清单:**这套东西现在到底带了什么,以及有没有被改过。**

抄自 Accio 的 `agent-hub/baselines/` —— 它给每个角色包留一份完整文件清单和哈希,
**装之前就能看它带哪些技能、有没有子代理、有没有 hook**。

为什么我们也需要:

  · 「加了技能却没写进 SKILLS 列表」不会报错,**只是永远不触发** ——
    你以为加了个能力,实际一次都没生效。
  · 「技能描述改了」是会影响触发的,但**改动本身不留痕** ——
    下次触发率变了,没人说得清是哪一次改的。
  · 「工具挂了 MCP 但没进白名单」这个坑这个项目漏过一次。

清单把这几样一起摊开,并给每份技能算个哈希 ——
**哈希变了就说明描述或正文动过**,而触发率的变化要能对上某一次改动。

    ./agentsite/.venv/bin/python agentsite/manifest.py           # 看清单
    ./agentsite/.venv/bin/python agentsite/manifest.py --save    # 存一版
    ./agentsite/.venv/bin/python agentsite/manifest.py --diff    # 和上一版比
"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SKILL_DIR = os.path.join(HERE, ".claude", "skills")
SNAP = os.path.join(HERE, "evals", "manifest.json")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:12]


def build():
    src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    declared = [x.strip().strip('"\'') for x in
                re.search(r"^SKILLS = \[(.*?)\]", src, re.M).group(1).split(",")]
    ondisk = sorted(d for d in os.listdir(SKILL_DIR)
                    if os.path.isdir(os.path.join(SKILL_DIR, d)))

    skills = []
    for n in ondisk:
        f = os.path.join(SKILL_DIR, n, "SKILL.md")
        if not os.path.exists(f): continue
        body = open(f, encoding="utf-8").read()
        m = re.search(r"(?ms)^description:\s*(.*?)\n(?=^\w|^---)", body)
        desc = re.sub(r"\s+", " ", (m.group(1) if m else "")).strip()
        skills.append(dict(
            名字=n, 声明了=n in declared, 行数=body.count("\n") + 1,
            描述字数=len(desc), 哈希=_sha(f),
            # **描述里有没有「什么时候用」**:这是触发的唯一依据。
            # 正文里的触发条件永远来不及影响那次触发 —— 要等技能被选中才读得到。
            描述含触发词=bool(re.search(r"只要|就该用|时用|哪怕", desc)),
        ))

    sys.path.insert(0, os.path.join(ROOT, "backend"))
    import api
    tools = sorted(s["name"] for s in api.SHOP_SCHEMAS)
    white = set(re.findall(r'"mcp__shop__(\w+)"', src))
    return dict(
        技能=skills,
        声明了但没有文件=[n for n in declared if n not in ondisk],
        有文件但没声明=[n for n in ondisk if n not in declared],
        工具数=len(tools),
        写工具=list(api.WRITE_TOOLS),
        挂了但没进白名单=sorted(set(tools) - white),
        进了白名单但没这个工具=sorted(white - set(tools)),
        铁律数=_rules(),
    )


def _rules():
    sys.path.insert(0, ROOT)
    import prompts
    return len(prompts.all_rules(unique=True))


def main():
    m = build()
    save = "--save" in sys.argv
    diff = "--diff" in sys.argv
    print(f"\n\033[1m能力清单\033[0m")
    print("=" * 84)
    print(f"  技能 {len(m['技能'])} 个 · 工具 {m['工具数']} 个(写 {len(m['写工具'])})· 铁律 {m['铁律数']} 条\n")
    for s in m["技能"]:
        flag = f"{G}✓{D}" if s["声明了"] else f"{R}✗ 没写进 SKILLS —— 永远不会触发{D}"
        d = f"{G}有{D}" if s["描述含触发词"] else f"{Y}弱{D}"
        print(f"  {flag} {s['名字']:14s} {s['行数']:4d} 行 · 描述 {s['描述字数']:3d} 字(触发词 {d})· {s['哈希']}")
    bad = 0
    for k in ("声明了但没有文件", "有文件但没声明", "挂了但没进白名单", "进了白名单但没这个工具"):
        if m[k]:
            print(f"\n  {R}❌ {k}:{m[k]}{D}")
            bad += 1
    if not bad:
        print(f"\n  {G}✓ 声明、文件、白名单三边一致{D}")

    if diff and os.path.exists(SNAP):
        old = {s["名字"]: s for s in json.load(open(SNAP, encoding="utf-8"))["技能"]}
        print(f"\n  \033[1m和上一版比\033[0m")
        ch = False
        for s in m["技能"]:
            o = old.get(s["名字"])
            if not o: print(f"    {G}+{D} 新增 {s['名字']}"); ch = True
            elif o["哈希"] != s["哈希"]:
                print(f"    {Y}~{D} {s['名字']} 改过了({o['哈希']} → {s['哈希']}),"
                      f"描述 {o['描述字数']} → {s['描述字数']} 字")
                print(f"       **触发率的变化要能对上这次改动** —— 跑一次 skill_eval 看看")
                ch = True
        for n in old:
            if n not in {s["名字"] for s in m["技能"]}: print(f"    {R}-{D} 删了 {n}"); ch = True
        if not ch: print("    没变")
    if save:
        os.makedirs(os.path.dirname(SNAP), exist_ok=True)
        json.dump(m, open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n  已存:{SNAP}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
