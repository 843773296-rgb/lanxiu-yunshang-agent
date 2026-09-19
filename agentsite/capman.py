#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力管理 —— 盘点现有能力、找出缺口、给设计、装脚手架。

    python3 agentsite/capman.py scan              盘点 + 找缺口(默认)
    python3 agentsite/capman.py scan --cli        只看「该改成 CLI 的技能」
    python3 agentsite/capman.py design <缺口号>    出一份设计
    python3 agentsite/capman.py install <缺口号>   按设计装脚手架

## 这个工具自己就是一条判据的样本

按 `knowledge/capability.py` 的判据,它该是 **CLI**:
步骤能提前枚举(扫表、扫代码、比对、输出),不需要理解自然语言。
**所以它是个脚本,不是一个技能。**

如果把它做成技能,每次盘点都要花钱、都要等模型、而且两次结果可能不一样 ——
**一份两次不一样的能力清单,没人敢照着它做决定。**

## 缺口必须带证据

每一条缺口都要能回答「你凭什么说缺」。没有证据的建议是噪声,
而噪声混在真缺口里,会让人把整张清单一起忽略掉。

所以下面每个探针都输出**可复核的数字**(哪张表、多少行、哪个文件第几行),
不输出「建议加强 XX 能力」这种话。

## 装,但不改别人的文件

`install` 只**新建**文件,不自动编辑 `api.py` / `check.sh` / `prompts.py`。
要改的那一行原样打出来,人自己贴。理由:自动编辑现有代码的工具,
出错时**改坏的地方和它报告的地方不是同一处**,排查成本极高。
"""
import os, re, sys, json, sqlite3, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, "backend")]
import knowledge.capability as CAP

DB = os.path.join(ROOT, "backend", "lanxiu.db")
SKILLS = os.path.join(HERE, ".claude", "skills")
OURS = {"quote", "growth-plan", "roster", "deadline-rescue", "exchange"}      # 自己写的,不是从 Accio 拿的


# ── 探针:每一条都必须拿得出证据 ────────────────────────────────
def 有数据没工具():
    """表里有行,而工具层一次都没碰过 → 可能缺一个 MCP 工具。

    **「可能」两个字是认真的**:很多表是内部实现(page_block、sys_code),
    本来就不该暴露。所以这条只报事实,不下结论。
    """
    if not os.path.exists(DB): return []
    c = sqlite3.connect(DB)
    tabs = {r[0]: c.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0]
            for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                               "AND name NOT LIKE 'sqlite_%'")}
    c.close()
    src = open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8").read()
    out = []
    for t, n in sorted(tabs.items(), key=lambda x: -x[1]):
        if n == 0: continue
        if re.search(r"\b(FROM|JOIN|INTO|UPDATE)\s+\"?" + re.escape(t) + r"\"?\b", src, re.I):
            continue
        out.append(dict(kind="mcp", 标题=f"表 `{t}` 有 {n} 行,工具层一次都没碰过",
                        证据=f"backend/api.py 里没有任何 SQL 提到 {t}",
                        数=n, 对象=t))
    return out


def 写工具没有hook兜():
    """**能写的工具,PreToolUse 里必须有对应的拦截逻辑。**

    这条探针重写过一次,第一版是错的,两个错叠在一起:

      ① **数错了。** 正则找的是 `def ck_/check_/_chk`,
         而这个项目的体检项叫 `g1_no_source`、`g2_cost_as_price` ——
         20 个一个都没匹配上,报成了「只有 1 项」。
      ② **判据本身不成立。** 就算数对了,「提示词里 45 条强制措辞
         vs hook 20 项体检」也**不是可比的量**:一条 hook 能管好几条规矩,
         而很多规矩(「一次只做一件」「如实报告」)**根本没法用 hook 检查**。
         拿两个不可比的数相除,得出的比例再扎眼也没有意义。

    第一版那条误报**特别像真的**:29 比 1 这个比例扎眼,
    结论(「大部分规矩只是祈使句」)也符合直觉,所以一眼看过去不会怀疑。
    **一个方向符合直觉的错误数字,比一个离谱的数字危险得多。**

    重写后判的是一件**确实可比**的事:
    `api.WRITE_TOOLS` 里的每一个,`guards.pre_tool_verdict` 里有没有提到它。
    写工具漏一次就是一条没人打算派的任务、一张不该批的单 ——
    **这正好是 hook 的判据:漏一次的代价。**
    """
    g = os.path.join(HERE, "guards.py")
    if not os.path.exists(g): return []
    gs = open(g, encoding="utf-8").read()
    try:
        import api
        writes = list(api.WRITE_TOOLS)
    except Exception:
        return []
    没兜 = [w for w in writes if w not in gs]
    if not 没兜: return []
    return [dict(kind="hook",
                 标题=f"{len(没兜)} 个写工具在 hook 里没被提到:{没兜}",
                 证据=f"api.WRITE_TOOLS 有 {len(writes)} 个,"
                      f"guards.py 全文里搜不到其中 {len(没兜)} 个 —— "
                      f"**写工具漏一次就是一条没人打算派的任务**",
                 数=len(没兜), 对象="guards.py")]


def 技能装了从不触发():
    """装着但埋点里一次都没上过场 → 它在跟别的技能抢描述空间,却没产出。"""
    st = os.path.join(HERE, ".skill-stats.jsonl")
    if not os.path.isdir(SKILLS): return []
    装了 = {d for d in os.listdir(SKILLS)
            if os.path.isdir(os.path.join(SKILLS, d))}
    用过 = set()
    if os.path.exists(st):
        for line in open(st, encoding="utf-8"):
            try: 用过.add(json.loads(line).get("skill"))
            except Exception: pass
    没用过 = 装了 - 用过 - OURS
    if len(没用过) < 10: return []
    return [dict(kind="prune",
                 标题=f"{len(没用过)} 个技能装着但埋点里一次都没上过场",
                 证据=f"{SKILLS} 下 {len(装了)} 个,埋点记录里出现过的 {len(用过)} 个。"
                      f"**实测同一条用例,场上 3 个技能时 3/3 触发、239 个时 0/3** —— "
                      f"装了不等于每次都上场",
                 数=len(没用过), 对象="skills")]


def 技能其实是死步骤():
    """技能正文全是死步骤、没有一处要判断 → **该改成 CLI**(用户点名要的那条)。"""
    if not os.path.isdir(SKILLS): return []
    out = []
    for d in sorted(os.listdir(SKILLS)):
        f = os.path.join(SKILLS, d, "SKILL.md")
        if not os.path.exists(f): continue
        try: txt = open(f, encoding="utf-8").read()
        except Exception: continue
        该, why, 证 = CAP.该不该改成CLI(txt)
        if 该:
            out.append(dict(kind="cli", 标题=f"技能 `{d}` 正文全是死步骤,该改成 CLI",
                            证据=f"{why}（命中:{证}）", 数=len(证), 对象=d))
    return out


def 重复的手工动作():
    """同一个动作在台账里反复出现 → 可能该做成批量工具或 CLI。"""
    if not os.path.exists(DB): return []
    c = sqlite3.connect(DB)
    try:
        rows = list(c.execute("SELECT code,COUNT(*) n FROM op_log "
                              "WHERE allowed=1 GROUP BY code ORDER BY n DESC"))
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()
    out = []
    for code, n in rows:
        if code in ("OK", "LOGIN") or n < 30: continue
        out.append(dict(kind="cli", 标题=f"台账里 `{code}` 成功执行过 {n} 次",
                        证据=f"op_log 里 code={code} 且 allowed=1 的有 {n} 条 —— "
                             f"**跑得越频繁,交给模型的单位成本越亏**",
                        数=n, 对象=code))
    return out[:3]


探针 = [("有数据没工具", 有数据没工具), ("写工具没有 hook 兜", 写工具没有hook兜),
       ("技能装了从不触发", 技能装了从不触发), ("技能其实是死步骤", 技能其实是死步骤),
       ("重复的手工动作", 重复的手工动作)]


def scan(只看cli=False):
    gaps = []
    print("能力管理 · 盘点")
    print("=" * 86)
    # 盘点
    skills = len([d for d in os.listdir(SKILLS)]) if os.path.isdir(SKILLS) else 0
    try:
        import api
        tools = len(api.TOOLS); writes = len(api.WRITE_TOOLS)
    except Exception:
        tools = writes = 0
    hooks = len(re.findall(r'"(PreToolUse|PostToolUse|Stop|SessionStart)":',
                           open(os.path.join(HERE, "guards.py"), encoding="utf-8").read()))
    print(f"  MCP 工具 {tools}(其中能写的 {writes}) · Skill {skills} · Hook {hooks}")
    print()
    print("缺口(每条都带证据)")
    print("-" * 86)
    for 名, fn in 探针:
        try: found = fn()
        except Exception as e:
            print(f"  ⚠️ 探针「{名}」自己挂了:{type(e).__name__}: {e}"); continue
        if 只看cli: found = [g for g in found if g["kind"] == "cli"]
        if not found:
            print(f"  ✅ {名}:没发现"); continue
        print(f"  ⚠️ {名}:{len(found)} 条")
        for g in found[:6]:
            gaps.append(g)
            print(f"     [{len(gaps)}] ({g['kind']}) {g['标题']}")
            print(f"         证据:{g['证据'][:100]}")
        if len(found) > 6:
            print(f"     … 还有 {len(found)-6} 条(同类)")
            gaps.extend(found[6:])
    print("-" * 86)
    print(f"  共 {len(gaps)} 条。`design <编号>` 看设计,`install <编号>` 装脚手架。")
    print()
    print("  ⚠️ **「有缺口」不等于「该补」。** 这个项目已经有 "
          f"{tools} 个工具、{skills} 个技能 —— ")
    print("     东西越多,「再加一个」的默认答案就越该是「不加」。"
          "先问:不加会怎样?")
    _save(gaps)
    return gaps


def _save(gaps):
    with open(os.path.join(HERE, ".capman-gaps.json"), "w", encoding="utf-8") as f:
        json.dump(gaps, f, ensure_ascii=False, indent=1)


def _load():
    p = os.path.join(HERE, ".capman-gaps.json")
    if not os.path.exists(p):
        print("先跑一次 `scan`"); sys.exit(1)
    return json.load(open(p, encoding="utf-8"))


def design(i):
    gaps = _load()
    if not (1 <= i <= len(gaps)):
        print(f"编号 1~{len(gaps)}"); return 1
    g = gaps[i - 1]
    名, 说, 判 = CAP.类别[g["kind"]] if g["kind"] in CAP.类别 else ("清理", "", "")
    print("=" * 86)
    print(f"设计 · [{i}] {g['标题']}")
    print("=" * 86)
    print(f"  归为哪一类:**{名}**")
    print(f"  这一类的定义:{说}")
    print(f"  判据:{判}")
    print(f"  证据:{g['证据']}")
    print()
    print("  开工前先回答这三个问题(答不上来就别做):")
    print("    ① 不做会怎样?—— 说得出具体的坏结果,才值得做")
    print("    ② 怎么验它是对的?—— **做不出验法的能力,做出来也不知道对不对**")
    print("    ③ 它的判据贴着「什么才算对」,还是贴着「我以为它会怎样」?")
    print()
    if g["kind"] == "mcp":
        print(f"  按这个项目的规矩,一个新工具要配齐四样:")
        print(f"    · 口径进 knowledge/(工具只取数)")
        print(f"    · prompts.py 里一条规矩(P6 会强制:挂了工具必须拿到规矩)")
        print(f"    · 一份验法进 check.sh,而且**故意弄坏确认它会红**")
        print(f"    · sdk.py 白名单里加一行")
    elif g["kind"] == "cli":
        print(f"  改成 CLI 的收益:确定性(能进 check.sh 当门禁)、不花钱、可组合、好调试")
        print(f"  ⚠️ 改之前再确认一遍:**真的没有一步需要判断吗?**")
        print(f"     把需要判断的改成 CLI,它会在边界情况上**默默给错答案**")
    elif g["kind"] == "hook":
        print(f"  ⚠️ hook 是强制,所以**它拦错的代价比漏拦更大** ——")
        print(f"     先想清楚「什么情况下该放行」,再写「什么情况下拦」")
    elif g["kind"] == "prune":
        print(f"  这条建议的是**减**,不是加。可以用档位而不是删除:")
        print(f"     `skills_own.py` 已经做了 own/all/none 三档,默认 own")
    return 0


def install(i):
    gaps = _load()
    if not (1 <= i <= len(gaps)):
        print(f"编号 1~{len(gaps)}"); return 1
    g = gaps[i - 1]
    k, 对象 = g["kind"], g["对象"]
    if k == "cli":
        name = re.sub(r"[^a-z0-9_]", "_", str(对象).lower())[:40] or "new_cli"
        path = os.path.join(ROOT, "tools", f"{name}.py")
        if os.path.exists(path):
            print(f"已经有 {path},不覆盖"); return 1
        open(path, "w", encoding="utf-8").write(_CLI_TPL.format(
            对象=对象, 证据=g["证据"].replace("\n", " ")))
        os.chmod(path, 0o755)
        print(f"✅ 建好 {path}")
        print(f"   下一步(**我不自动改别人的文件**,这行你自己贴):")
        print(f'   check.sh:  run "{对象} · 一句话说清它验什么" python3 tools/{name}.py')
        return 0
    if k == "mcp":
        print(f"不自动生成 MCP 工具 —— 一个工具要配口径、规矩、验法、白名单四样,")
        print(f"生成一个空壳只会让 P6 当场红,而且掩盖了「这个表到底该不该暴露」这个问题。")
        print(f"先跑 `design {i}` 回答那三个问题。")
        return 1
    print(f"这一类({k})没有脚手架可装,跑 `design {i}` 看怎么做。")
    return 1


_CLI_TPL = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(脚手架)关于 {对象} 的确定性脚本。

由 `agentsite/capman.py install` 生成。**生成的是骨架,判据要自己写。**

为什么是 CLI 不是技能:
{证据}

写之前先回答:
  ① 不做会怎样?
  ② 怎么验它是对的?**做不出验法的,做出来也不知道对不对**
  ③ 判据贴着「什么才算对」,还是贴着「我以为它会怎样」?

⚠️ 如果这里最后会用到「如果 / 视情况 / 取决于」,**停下来** ——
   那说明它需要判断,不该是纯 CLI。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {{'✅' if ok else '❌'}} {{name}}(验了 {{n}} 个){{'  ' + msg if msg else ''}}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("{对象}")
    print("=" * 72)
    # TODO: 在这儿写检查。每条都要能说出「验了多少个」。
    ck("还没写", False, 0)
    print("=" * 72)
    if FAIL:
        print(f"❌ {{len(FAIL)}} 条没过:{{FAIL}}")
        return 1
    print("✅ 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def main():
    a = sys.argv[1:] or ["scan"]
    if a[0] == "scan":
        scan("--cli" in a); return 0
    if a[0] in ("design", "install") and len(a) > 1 and a[1].isdigit():
        return (design if a[0] == "design" else install)(int(a[1]))
    print(__doc__.split("\n\n")[1]); return 1


if __name__ == "__main__":
    sys.exit(main())
