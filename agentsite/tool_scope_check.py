#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具收窄真的收到了 MCP 那一层 —— 外部审阅 2026-10-03 §4.3。

原来旋钮收窄只进了 SDK 的 `allowed_tools`,MCP 服务仍按角色全集建 `LANXIU_TOOLS`:
财务夹具 allowed_tools 1 个、MCP 配置 5 个 —— **模型看得见、也调得动被收掉的工具**。
而 `allowed_tools` 本来就不是排他白名单(CLAUDE.md 第 7 节第 1 项)。

验**行为**,不只扫代码里有没有那几个字:
  ① 起一个真的 MCP 服务子进程,`tools/list` 读回来的就是收窄后的那一个;直接调别的 → 执行前被拒
  ② 截住 run() 交给 SDK 的配置:MCP 暴露的、allowed_tools、提示词装的规矩,是**同一份**
  ③ 空集合不被扩成全部(None = 没限制,[] = 一个都不给)
不调模型、不花钱:SDK 的选项构造被截住,跑不到真调用。
"""
import asyncio, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("MCP 配置不收 run 算好的名单(`mcp_config(me, kind, 名单=工具)` 改回 `mcp_config(me, kind)`)",
     "MCP 暴露的和 allowed_tools 是同一份"),
    ("生效工具把空集合当成没限制(`if 收窄 is None:` 改成 `if not 收窄:`)", "空集合不被扩成全部"),
    ("提示词不按生效工具装配(收窄时仍用角色全集的提示词)", "收掉的工具,管它的规矩也不在提示词里"),
]

坏 = 0


def ck(名, ok, n, 说明=""):
    global 坏
    if n == 0:
        print(f"  {R}❌{D} {名} —— **没扫到东西**,不是通过"); 坏 += 1; return
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}(验了 {n} 个){'' if ok else '  ' + 说明}")
    坏 += 0 if ok else 1


def MCP问(cfg, 请求们):
    """真起一个 MCP 服务子进程,按 JSON-RPC 一行一个发请求,收回答。"""
    env = {**os.environ, **cfg["env"]}
    p = subprocess.run([cfg["command"], *cfg["args"]], input="".join(json.dumps(x) + "\n" for x in 请求们),
                       capture_output=True, text=True, env=env, timeout=60)
    return [json.loads(l) for l in p.stdout.splitlines() if l.strip().startswith("{")]


class _截住(Exception):
    pass


def main():
    import sdk, prompts
    me = dict(no="HQ", name="测", role="总部运营", shop=None)

    print("\n\033[1m▸ 生效工具:角色许可 ∩ 本次限制\033[0m")
    全 = sdk._tools_for("finance")
    ck("没限制(None)→ 角色全集", sdk.生效工具("finance", None) == 全, len(全))
    ck("限制成一个 → 只剩那一个", sdk.生效工具("finance", 全[:1]) == 全[:1], 1)
    ck("空集合不被扩成全部(None 和 [] 是两回事)", sdk.生效工具("finance", []) == [], 1)
    外 = [t for t in sdk._tools_for("all") if t not in 全][:1]
    ck("限制里混进角色没有的工具 → 不放进来(只许收窄)", sdk.生效工具("finance", 全[:1] + 外) == 全[:1], 1)

    print("\n\033[1m▸ MCP 那一层真的只暴露、只放行这一个\033[0m")
    只一 = 全[:1]
    cfg = sdk.mcp_config(me, "finance", 名单=只一)
    服务, 短 = 只一[0].split("__")[1], 只一[0].split("__")[2]
    ck("MCP 配置只挂了那一个服务、名单只有那一个工具",
       list(cfg) == [服务] and cfg[服务]["env"]["LANXIU_TOOLS"] == 短, 1, str({k: v["env"].get("LANXIU_TOOLS") for k, v in cfg.items()}))
    ck("空集合 → 一个服务都不挂", sdk.mcp_config(me, "finance", 名单=[]) == {}, 1)
    别 = next(t.split("__")[2] for t in sdk._tools_for("all") if t.split("__")[1] == 服务 and t.split("__")[2] != 短)
    回 = MCP问(cfg[服务], [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": 别, "arguments": {}}}])
    列 = next((x for x in 回 if x.get("id") == 2), {}).get("result", {}).get("tools", [])
    调 = next((x for x in 回 if x.get("id") == 3), {}).get("result", {})
    ck("真起 MCP 服务:tools/list 读回来只有那一个", [t["name"] for t in 列] == [短], 1, str([t["name"] for t in 列]))
    ck("真起 MCP 服务:直接调别的工具 → 执行前被拒", 调.get("isError") and "没有名为" in json.dumps(调, ensure_ascii=False),
       1, str(调)[:120])

    print("\n\033[1m▸ run() 交给 SDK 的是同一份\033[0m")
    抓 = {}
    真选项 = sdk.ClaudeAgentOptions
    def 截(**kw):
        抓.update(kw); raise _截住()
    sdk.ClaudeAgentOptions = 截
    import knobs
    真应用 = knobs.应用
    knobs.应用 = lambda 参数, 号=None, 可用工具=None: ({**参数, "_工具收窄": 只一}, ["测:工具收窄"])
    try:
        asyncio.run(sdk.run("finance", "测", me=me, guard=False))
    except _截住:
        pass
    finally:
        sdk.ClaudeAgentOptions, knobs.应用 = 真选项, 真应用
    暴露 = sorted(f"mcp__{k}__{t}" for k, v in (抓.get("mcp_servers") or {}).items()
                  for t in v["env"].get("LANXIU_TOOLS", "").split(",") if t)
    ck("MCP 暴露的和 allowed_tools 是同一份", 暴露 == sorted(抓.get("allowed_tools") or []) == sorted(只一), 1,
       f"MCP {暴露} / allowed {抓.get('allowed_tools')}")
    全文, 全规矩 = prompts.assemble("finance", sdk._have("finance"))
    收文, 收规矩 = prompts.assemble("finance", {只一[0].rsplit('__', 1)[-1]})
    少了 = [x for x in 全规矩 if x not in 收规矩]
    sp = 抓.get("system_prompt") or ""
    # run 交出去的提示词 = 按**收窄后**的工具装出来的那份 + 身份段;不是角色全集那份
    ck("收掉的工具,管它的规矩也不在提示词里", bool(少了) and sp.startswith(收文) and not sp.startswith(全文),
       len(少了) or 1, f"该少的规矩 {少了};交出去的提示词开头是{'收窄版' if sp.startswith(收文) else '全集版或别的'}")

    print()
    if 坏:
        print(f"{R}❌ 工具收窄 {坏} 条不过{D}"); return 1
    print(f"{G}✅ 工具收窄全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
