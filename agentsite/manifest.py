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
    # **import 拿真值,不用正则去源码里抓。**
    # 上一版是 `re.search(r"^SKILLS = \[(.*?)\]", src)` —— 判据贴着**写法**:
    # 它假设 SKILLS 永远写成一个字面量列表。我把它改成从磁盘现算之后,
    # 正则匹配不上,**这个检查当场崩掉**(AttributeError: NoneType.group)。
    # 崩掉算运气好 —— 要是正则碰巧匹配到别的东西,它会安静地给出一份错清单。
    # **判据要贴着「什么才算对」,不是贴着「我以为它会怎么写」** —— 这条这一段学过两次了。
    import sdk as _sdk
    # **「装了什么」和「默认上场哪些」现在是两件事。**
    # 分档之后 SKILLS 只是**默认档**(own,3 个),而目录里装着 239 个。
    # 拿默认档去和目录比,会报「236 个有文件没声明」—— 那是旧口径。
    # 现在比的是:目录里的每一个,**至少属于某一档**(不属于任何档才是真的白装)。
    declared = sorted({x for k in _sdk.SKILL_SETS for x in _sdk.skills_for(k)})
    default_set = list(_sdk.SKILLS)
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
        默认档=default_set,
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
    print(f"  技能 {len(m['技能'])} 个(**默认上场 {len(m['默认档'])} 个**:{m['默认档']})· "
          f"工具 {m['工具数']} 个(写 {len(m['写工具'])})· 铁律 {m['铁律数']} 条")
    print(f"  装着 ≠ 每次都上场 —— 实测 239 个全上时,"
          f"「6月毕业典礼那天该做多大」从 3/3 掉到 0/3\n")
    import skills_own
    for s in [x for x in m["技能"] if skills_own.is_ours(x["名字"])]:
        flag = f"{G}✓{D}" if s["声明了"] else f"{R}✗ 不属于任何一档 —— 永远不会触发{D}"
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
    # **改了技能却没重测** —— 这是这一段反复吃亏的地方。
    # 哈希对不上说明描述或正文动过,而触发率的变化必须能对上某一次改动;
    # 对不上的话,下次触发率变了,没人说得清是哪一次改的。
    import glob, json as _js
    runs = sorted(glob.glob(os.path.join(HERE, "evals", "runs", "*.json")))
    if runs and os.path.exists(SNAP):
        last_eval = max(os.path.getmtime(x) for x in runs)
        newest_skill = max(
            os.path.getmtime(os.path.join(SKILL_DIR, s["名字"], "SKILL.md"))
            for s in m["技能"])
        if newest_skill > last_eval + 60:
            print(f"\n  {Y}⚠ 技能比最近一次评测新{D} —— 改完没重测。")
            print(f"    描述改动是有代价的:**把一个问法拉进来常常把另一个推出去**,")
            print(f"    没有重测就看不见被推出去的那个。")
            print(f"    跑:./agentsite/.venv/bin/python agentsite/skill_eval.py "
                  f"--repeat 3 --diff <上一版>")
    if save:
        os.makedirs(os.path.dirname(SNAP), exist_ok=True)
        json.dump(m, open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n  已存:{SNAP}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
