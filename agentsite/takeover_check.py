# -*- coding: utf-8 -*-
"""工作流接管 · 聊天站这一半(用户 2026-10-24 拍「默认关;打开时聊天站改走工作流」)。

守三件事,都**真调被测代码**,不重实现:
  ① 被接管的技能**结构上**调不动 —— guards.pre_tool_verdict 真拦,拦截理由点名改调 start_workflow;
     没被接管的照旧放行(接管不许误伤)
  ② 拉不到清单时的退路 —— 用最后一次拉成功的;**从没拉成功过当全关**(全拦会把所有自有技能一起拦掉)
  ③ 每个角色都挂了 start_workflow —— 哪件事被接管和岗位无关,漏挂一个角色,那件事在那个角色上就既不能用技能、也发不起
不联网:接管查询口换成假的,管理后台地址指向一个没人听的端口。
"""
import json
import os
import socket
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
过, 挂 = [], []

咬合 = [
    ("把 guards 里接管那道拦截删掉", "被接管的技能调不动,拦截理由点名改调 start_workflow"),
    ("拉不到清单时一律当全关(不用落盘的上一次)", "管理后台连不上:用最后一次拉成功的清单"),
]


def ck(名, 真, 补=""):
    print(f"  {G + '✅' + D if 真 else R + '❌' + D} {名}" + (f"  {str(补)[:200]}" if 补 and not 真 else ""))
    (过 if 真 else 挂).append(名)


def 空端口():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def main():
    print("工作流接管 · 聊天站这一半(拦技能 / 退路 / 每个角色都能发起)")
    import guards
    import takeover_client as tc

    print("\n▸ ① 拦截")
    原 = guards.接管查询
    try:
        guards.接管查询 = lambda sk: {"workflow_id": "wf_x", "名称": "音频整理"} if sk == "call-notes" else None
        v = guards.pre_tool_verdict("Skill", {"skill": "call-notes"})
        ck("被接管的技能调不动,拦截理由点名改调 start_workflow",
           bool(v) and "start_workflow" in v and "音频整理" in v, v)
        v2 = guards.pre_tool_verdict("Skill", {"skill": "/call-notes"})
        ck("带斜杠的写法(/call-notes)照样拦", bool(v2) and "start_workflow" in v2, v2)
        ck("没被接管的自有技能照旧放行(接管不误伤)", guards.pre_tool_verdict("Skill", {"skill": "quote"}) is None,
           guards.pre_tool_verdict("Skill", {"skill": "quote"}))
        guards.接管查询 = lambda sk: None
        ck("全关时 call-notes 照旧放行(默认交给 harness)",
           guards.pre_tool_verdict("Skill", {"skill": "call-notes"}) is None,
           guards.pre_tool_verdict("Skill", {"skill": "call-notes"}))
        guards.接管查询 = lambda sk: (_ for _ in ()).throw(RuntimeError("查询挂了"))
        try:
            guards.pre_tool_verdict("Skill", {"skill": "call-notes"})
            ck("查询口自己抛异常时不许把判定一起带崩", False, "没抛 —— 这一条的前提不成立")
        except RuntimeError:
            # 默认的查询口自己兜住了异常(见 guards.接管查询);这里验的是:换成会抛的,判定确实会感知到 ——
            # 说明 pre_tool_verdict 真在调这个口,不是读了别处的一份缓存
            ck("判定真在调接管查询口(换成会抛的,判定能感知到)", True)
    finally:
        guards.接管查询 = 原
    ck("默认查询口:模块出错时当没接管(返回 None,不抛)", 原("这个技能不存在-xyz") is None)

    print("\n▸ ② 拉不到清单时的退路")
    旧环境 = {k: os.environ.get(k) for k in ("LANXIU_USAGE_URL", "LANXIU_BRIDGE_PROJECT", "LANXIU_USAGE_USER")}
    旧落盘 = tc._落盘
    d = tempfile.mkdtemp()
    try:
        tc._落盘 = os.path.join(d, "last.json")
        os.environ.update(LANXIU_USAGE_URL=f"http://127.0.0.1:{空端口()}", LANXIU_BRIDGE_PROJECT="project_x",
                          LANXIU_USAGE_USER="U001")
        tc._内存.update(at=0, items=None)
        ck("从没拉成功过 + 管理后台连不上 → 当全关(空清单)", tc.清单(强制=True) == {}, tc.清单(强制=True))
        with open(tc._落盘, "w", encoding="utf-8") as f:
            json.dump({"items": {"call-notes": {"workflow_id": "wf_1", "名称": "音频整理"}}}, f)
        tc._内存.update(at=0, items=None)
        ck("管理后台连不上:用最后一次拉成功的清单", (tc.接管中("call-notes") or {}).get("workflow_id") == "wf_1",
           tc.清单(强制=True))
        ok, 回 = tc.发起("call-notes", "60000005", {}, "k1")
        ck("连不上时发起明说没发起成,而且叫它别退回去用技能", not ok and "别改用技能" in 回.get("error", ""), 回)
        for k in 旧环境:
            os.environ.pop(k, None)
        ok, 回 = tc.发起("call-notes", "60000005", {}, "k2")
        ck("没配管理后台地址:明说没配,不猜一个默认地址", not ok and "没配" in 回.get("error", ""), 回)
    finally:
        tc._落盘 = 旧落盘
        tc._内存.update(at=0, items=None)
        for k, v in 旧环境.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    print("\n▸ ②½ 防重复的钥匙(10-24 真跑踩过:新建的工作流上发起,拿回上一次已取消的那条)")
    t = 1_000_000 * 60.0
    同 = tc.幂等键("60000001", "call-notes", "wf_1", {"call_id": "TS-001"}, t)
    ck("同一个人、同一条工作流、同样输入、同一分钟 → 同一把钥匙(模型重发不排第二条)",
       同 == tc.幂等键("60000001", "call-notes", "wf_1", {"call_id": "TS-001"}, t + 30))
    ck("**换了工作流 → 另一把钥匙**(不许拿回别的工作流上的旧运行)",
       同 != tc.幂等键("60000001", "call-notes", "wf_2", {"call_id": "TS-001"}, t))
    ck("过了这一分钟 → 另一把钥匙(用户隔一会儿再要,是新的一次)",
       同 != tc.幂等键("60000001", "call-notes", "wf_1", {"call_id": "TS-001"}, t + 60))

    print("\n▸ ③ 每个角色都能发起")
    import sdk
    角色们 = sorted(sdk._ROLE_TOOLS)
    缺 = [k for k in 角色们 if "mcp__work__start_workflow" not in sdk._tools_for(k)]
    ck(f"每个角色({len(角色们)} 个)都挂了 start_workflow", len(角色们) >= 7 and not 缺, 缺)
    import api, domains
    ck("start_workflow 登记成写口(一轮只发一次、同参数不许重试)", "start_workflow" in api.WRITE_TOOLS)
    ck("start_workflow 归 work 领域(和 mcp__work__ 前缀对得上)", "start_workflow" in domains.领域["work"])

    print()
    if 挂:
        print(f"{R}❌ 工作流接管(聊天站)不过 {len(挂)} 条{D}")
        return 1
    print(f"{G}✅ 工作流接管(聊天站):拦得住、退路对、每个角色都能发起(验了 {len(过)} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
