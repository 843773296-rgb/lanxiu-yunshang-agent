#!/usr/bin/env python3
"""Skill 与配置面自查。

**为什么这个文件必须存在:** 要让 CLI 找到项目自带的 Skill,就得把 `setting_sources`
从 `[]` 放开到 `["project"]`。而这个项目**在这上面栽过一次** ——
放开设置来源之后,根目录的 `.mcp.json` 被自动挂上,工具名跑成了 `mcp__lanxiu-task__*`,
和代码里声明的重复一套,`allowed_tools` 白名单形同虚设。

放开一个口子,就得同时装一个盯着它的检查。靠记性不行,人会忘,而且换个人接手根本不知道。

默认只跑离线检查(不花钱)。加 `SKILLS_LIVE=1` 会真跑一次调用,
验证实际拿到的工具名确实干净 —— 那是唯一能证伪的方式,但要花约 $0.005。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

bad = []
print("Skill 与配置面自查\n" + "=" * 74)

# ① 每个 SKILL.md 的 frontmatter 必须齐 —— 缺 description,模型就不知道什么时候该用它
sk_dir = os.path.join(HERE, ".claude", "skills")
import skills_own
found = sorted(d for d in os.listdir(sk_dir)) if os.path.isdir(sk_dir) else []
metas = {}
for d in found:
    f = os.path.join(sk_dir, d, "SKILL.md")
    # **归属判断要放在最前面。** 上一版放在描述长度那一条前面,
    # 而「没有 SKILL.md」「没有 frontmatter」两条在它**之前**就 append 了 ——
    # 于是第三方技能照样报 5 条红。**边界画晚一步,等于没画。**
    ours = skills_own.is_ours(d)
    if not os.path.exists(f):
        if ours: bad.append(f"{d}/ 下没有 SKILL.md")
        continue
    txt = open(f, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if not m:
        if ours: bad.append(f"{d}/SKILL.md 没有 frontmatter")
        continue
    fm = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    metas[d] = fm
    # **质量只查我们自己写的。** 目录里现在还有 236 个从 Accio 提取的第三方技能,
    # 它们的描述长短不归我们改;把它们算进来会出 136 条红,
    # 而**淹掉的红和没有红是一回事**。
    # 边界跟着**归属**走,不跟着「目录里有什么」走 —— 那个目录任何人都能往里写。
    if not ours:
        continue
    if fm.get("name") != d:
        bad.append(f"{d}/SKILL.md 的 name「{fm.get('name')}」和目录名对不上")
    if len(fm.get("description", "")) < 20:
        bad.append(f"{d} 的 description 太短 —— 模型靠它判断什么时候该用这个 skill")
_ours = [d for d in metas if skills_own.is_ours(d)]
_3rd = len(metas) - len(_ours)
print(f"  {'✅' if metas else '❌'} 发现 {len(found)} 个 skill:"
      f"我们自己的 {len(_ours)} 个 {_ours},第三方 {_3rd} 个({skills_own.THIRD_PARTY_NOTE})")
for d in _ours:
    print(f"       {d}: {metas[d].get('description','')[:56]}…")

# ② 代码里声明的 SKILLS 要和目录对得上 —— 多了是死规则,少了是白写
import sdk
# **「装了什么」和「默认上场哪些」是两件事。**
# sdk.SKILLS 现在只是默认档(own);目录里装着 239 个,其余属于 all 档。
# 比的是「目录里的每一个至少属于某一档」——
# 不属于任何档才是真的白装(装了却永远不会被选中)。
declared = sorted({x for k in sdk.SKILL_SETS for x in sdk.skills_for(k)})
if set(declared) != set(found):
    bad.append(f"声明的 {declared} 与目录里的 {found} 对不上"
               f"(多声明 {sorted(set(declared)-set(found))} / 漏声明 {sorted(set(found)-set(declared))})")
print(f"  {'✅' if set(declared)==set(found) else '❌'} 目录里每个技能都至少属于某一档:{len(found)} 个;默认档 {sorted(sdk.SKILLS)}")

# ②.5 白名单必须和 MCP 实际暴露的工具**完全一致**
#
# 这条是漏出来的:plan_for_event 挂上了 MCP、写进了 SHOP_SCHEMAS,
# 却忘了加进 sdk.py 的 allowed_tools —— 结果模型在工具清单里看得见它,
# 一调就撞权限。**声明和挂载分在两个文件里,靠人记得同步是不行的。**
#
# 两个方向都查:
#   漏加 → 模型看得见用不了
#   多加 → 白名单里挂着一个不存在的工具名,那是死配置,以后没人敢删
import re as _re
_src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api as _api
_GROUPS = {"kb": _api.KB_SCHEMAS, "shop": _api.SHOP_SCHEMAS, "task": _api.SCHEMAS}
for _ns, _sch in _GROUPS.items():
    _white = set(_re.findall(r'"mcp__%s__(\w+)"' % _ns, _src))
    _real = {x["name"] for x in _sch}
    _miss, _dead = sorted(_real - _white), sorted(_white - _real)
    if _miss:
        bad.append(f"MCP {_ns} 暴露了 {_miss} 但 sdk 白名单里没有 —— 模型看得见却用不了")
    if _dead:
        bad.append(f"sdk 白名单里的 {_dead} 在 MCP {_ns} 里不存在 —— 死配置")
    print(f"  {'✅' if not (_miss or _dead) else '❌'} {_ns}:MCP 暴露 {len(_real)} 个,"
          f"白名单 {len(_white)} 个,{'完全一致' if not (_miss or _dead) else '对不上'}")

# ③ 放开了 project 设置源,就必须有两道锁
src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
放开 = 'setting_sources=["project"]' in src
if 放开:
    if "strict_mcp_config=True" not in src:
        bad.append("放开了 project 设置源却没开 strict_mcp_config —— .mcp.json 会被自动挂上")
    for w in ('"user"', '"local"'):
        if re.search(r'setting_sources=\[[^\]]*' + w, src):
            bad.append(f"setting_sources 里出现了 {w} —— 那是本机配置,换台机器行为就不一致")
    # ⚠️ **放开 project 原来会把项目的 CLAUDE.md 一起带进模型的系统提示词。**
    # 实测过:直接问智能体「你提示词里有没有 CLAUDE.md」,它答「有」并抄出了第一行。
    #
    # **那条已经不是权衡了,是结构** —— 把 cwd 挪出项目就两头都拿到了:
    # 泄露没了,Skill 照样上场(另一条路 setting_sources=[] 泄露也没了,
    # 但 Skill 跟着一起没)。所以这里验的是那个前提还在不在。
    import runtime as _rt
    if _rt.往上找():
        bad.append(f"从运行目录往上撞见了 CLAUDE.md:{_rt.往上找()} —— "
                   f"放开了 project 设置源,这些会整份进系统提示词")
    if not os.path.isdir(os.path.join(_rt.RUNTIME, ".claude", "skills")):
        bad.append("运行目录里没有 .claude/skills —— 隔离住了,但 Skill 也没了")
# ⚠️ 这一行原来**印在 if 外面,无条件为真** —— 把 setting_sources 改成 []
# 之后它照样绿着说「project 设置源已放开」。
# **一条断言正确、话说得不对的检查,比没有检查更危险**:它每次都绿,
# 而看的人以为绿的是它嘴上那件事。
print(f"  ✅ 设置源 = {'project(运行目录在项目外,CLAUDE.md 进不来)' if 放开 else '空(Skill 不会上场)'}"
      f",strict_mcp_config 锁住 MCP,未引入 user/local")

# ③.5 内置工具必须被封 —— 这条是实跑抓出来的,不是想出来的
DANGEROUS = ("Bash", "Write", "Edit", "Read", "Task", "Agent", "ToolSearch",
             "WebFetch", "NotebookEdit")
if "disallowed_tools" not in src:
    bad.append("sdk.py 没有 disallowed_tools —— **allowed_tools 不是排他白名单**,"
               "CLI 的内置工具(Bash/Write/Task)会一直在场")
else:
    missing = [t for t in DANGEROUS if f'"{t}"' not in src]
    if missing:
        bad.append(f"disallowed_tools 没封住:{missing} —— 这些能读写文件、执行命令、开子智能体")
if "not name.startswith(\"mcp__\")" not in open(
        os.path.join(HERE, "guards.py"), encoding="utf-8").read():
    bad.append("guards.py 的 PreToolUse 没有拦非 MCP 工具 —— "
               "配置是第一道锁,Hook 是第二道,少一道都不该过")
print(f"  ✅ 内置工具双重封锁:disallowed_tools 配置 + PreToolUse 运行时拦截")

# ④ .mcp.json 里有什么,和代码声明的差多少 —— 差多少就是 strict 在挡多少
mj = os.path.join(ROOT, ".mcp.json")
if os.path.exists(mj):
    try: file_servers = sorted(json.load(open(mj, encoding="utf-8")).get("mcpServers", {}))
    except Exception as e: file_servers = [f"(读不了:{e})"]
    code_servers = sorted(sdk.mcp_config())
    print(f"  ℹ .mcp.json 声明了 {file_servers};代码声明了 {code_servers}")
    if set(file_servers) - set(code_servers):
        print(f"       strict_mcp_config 正在挡住:{sorted(set(file_servers)-set(code_servers))}")

# ⑤ 真跑一次(要花钱,默认不跑)
if os.environ.get("SKILLS_LIVE") == "1":
    import asyncio
    print("\n  实跑验证工具名干净(约 $0.005)…")
    st = {}
    r = asyncio.run(sdk.run("kb", "查一下妆花能不能用在纱上,一句话答完。"))
    names = [t["tool"] for t in r["trajectory"]]
    allow = set(sdk.KB_TOOLS) | set(sdk.SHOP_TOOLS) | set(sdk.TASK_TOOLS)
    rogue = [n for n in names if n.startswith("mcp__") and n not in allow]
    print(f"       实际调用:{names}")
    if rogue: bad.append(f"出现了白名单外的 MCP 工具:{rogue} —— 设置源污染回来了")
    else: print("       ✅ 全部在白名单内,没有 .mcp.json 挂进来的重复服务")
else:
    print("\n  (跳过实跑验证;要跑设 SKILLS_LIVE=1,约 $0.005)")

print("\n" + "=" * 74)
if bad:
    for b in bad: print("  ❌", b)
    print("❌ Skill / 配置面有问题"); sys.exit(1)
print("✅ Skill 与配置面自查通过")
