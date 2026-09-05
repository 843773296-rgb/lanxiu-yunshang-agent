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
found = sorted(d for d in os.listdir(sk_dir)) if os.path.isdir(sk_dir) else []
metas = {}
for d in found:
    f = os.path.join(sk_dir, d, "SKILL.md")
    if not os.path.exists(f):
        bad.append(f"{d}/ 下没有 SKILL.md"); continue
    txt = open(f, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if not m:
        bad.append(f"{d}/SKILL.md 没有 frontmatter"); continue
    fm = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    metas[d] = fm
    if fm.get("name") != d:
        bad.append(f"{d}/SKILL.md 的 name「{fm.get('name')}」和目录名对不上")
    if len(fm.get("description", "")) < 20:
        bad.append(f"{d} 的 description 太短 —— 模型靠它判断什么时候该用这个 skill")
print(f"  {'✅' if metas else '❌'} 发现 {len(found)} 个 skill:{found}")
for d, fm in metas.items():
    print(f"       {d}: {fm.get('description','')[:56]}…")

# ② 代码里声明的 SKILLS 要和目录对得上 —— 多了是死规则,少了是白写
import sdk
declared = list(sdk.SKILLS)
if set(declared) != set(found):
    bad.append(f"声明的 {declared} 与目录里的 {found} 对不上"
               f"(多声明 {sorted(set(declared)-set(found))} / 漏声明 {sorted(set(found)-set(declared))})")
print(f"  {'✅' if set(declared)==set(found) else '❌'} sdk.SKILLS 与目录一致:{declared}")

# ③ 放开了 project 设置源,就必须有两道锁
src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
if 'setting_sources=["project"]' in src:
    if "strict_mcp_config=True" not in src:
        bad.append("放开了 project 设置源却没开 strict_mcp_config —— .mcp.json 会被自动挂上")
    for w in ('"user"', '"local"'):
        if re.search(r'setting_sources=\[[^\]]*' + w, src):
            bad.append(f"setting_sources 里出现了 {w} —— 那是本机配置,换台机器行为就不一致")
print("  ✅ project 设置源已放开,strict_mcp_config 锁住 MCP,未引入 user/local")

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
