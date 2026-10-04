#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话的业务状态跨请求恢复 —— 外部审阅 2026-10-03 §4.2。

原来 `sdk.run` 每次 `state={}`:续聊时当前方案、锚点、压缩标记全丢,而注入那一段因此不再出现。
审阅 §8.2 的验收场景,逐个验:
  普通续聊 · 压缩后续聊(压缩提醒和锚点真的注回去)· 服务重启(换连接再读)· 两会话交错 ·
  方案被删 · 权限改变(角色 / 门店)· 并发写不覆盖 · 不整包回灌
**不调模型**:存取用临时库;注入用真的 hook(guards.make_hooks)跑一遍 on_prompt。
"""
import asyncio, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("整包回灌(加载时不过滤跨轮键)", "不整包回灌:本轮的调用记录 / 违规 / 修正次数不带过来"),
    ("加载不核角色 / 门店", "角色或门店变了 → 不恢复"),
    ("保存不核版本", "基于旧版本的写 → 不覆盖"),
    ("恢复方案不重查(删了也带回来)", "上一轮在谈的方案已经被删 → 不带回来"),
    ("续聊归属不核权限变化", "续聊时角色变了 → 拒"),
    ("run 的 return 缩进进了「存会话状态」那个 if", "run 不管存没存会话状态,都把结果交回去"),
]

坏 = 0


def ck(名, ok, n, 说明=""):
    global 坏
    if n == 0:
        print(f"  {R}❌{D} {名} —— **没扫到东西**,不是通过"); 坏 += 1; return
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}(验了 {n} 个){'' if ok else '  ' + 说明}")
    坏 += 0 if ok else 1


def main():
    import session_state as S, sessions, guards
    tmp = tempfile.mkdtemp()
    库 = os.path.join(tmp, "state.db")
    业务 = os.path.join(tmp, "biz.db")
    shutil.copy(os.path.join(ROOT, "backend", "lanxiu.db"), 业务)
    b = sqlite3.connect(业务)
    方案 = b.execute("SELECT id, status FROM scheme ORDER BY id LIMIT 2").fetchall()
    b.close()
    if len(方案) < 2:
        print(f"  {R}❌{D} 取不到两份方案 —— 没扫到东西"); return 1
    顾问 = dict(no="A1", name="甲", role="顾问", shop="SH001")
    跑完的 = {"当前方案": {"号": 方案[0][0], "名称": "测", "状态": 方案[0][1]}, "锚点": {"订单": "O1"},
              "刚压缩过": True, "calls": [{"tool": "x"}], "violations": [{"check": "测"}], "修正次数": 1,
              "答案检查": [{"结果": "不通过"}], "prompt": "上一轮的问题"}

    print("\n\033[1m▸ 普通续聊 / 不整包回灌\033[0m")
    ok, _ = S.保存("SID-1", 顾问, 跑完的, path=库)
    d, ver, 说 = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    ck("续聊恢复当前方案和锚点", ok and d.get("当前方案", {}).get("号") == 方案[0][0] and d.get("锚点") == {"订单": "O1"}, 1, str(d))
    # 保存时本来就只存跨轮键 —— 要单测「加载这一道」过滤,直接往库里塞一份带本轮状态的(老版本 / 别处写进来的)
    import json as _j
    c0 = sqlite3.connect(库)
    c0.execute("UPDATE session_state SET data=? WHERE sid='SID-1'", (_j.dumps(跑完的, ensure_ascii=False),)); c0.commit(); c0.close()
    d, ver, 说 = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    ck("不整包回灌:本轮的调用记录 / 违规 / 修正次数不带过来",
       not any(k in d for k in ("calls", "violations", "修正次数", "答案检查", "prompt")), 1, str(list(d)))

    print("\n\033[1m▸ 压缩后续聊:提醒和锚点真的注回去(跑真的 hook)\033[0m")
    state = dict(d)
    on_prompt = guards.make_hooks(state)["UserPromptSubmit"][0].hooks[0]
    out = asyncio.run(on_prompt({"prompt": "就按刚才那个"}, None, None))
    注 = str(out) + (state.get("注入原文") or "")
    ck("恢复后第一轮:注入里有方案号、压缩提醒、锚点", 方案[0][0] in 注 and "刚被压缩过" in 注 and "O1" in 注, 1, 注[:200])
    ck("压缩提醒注过一次就消费掉(不每轮都喊)", "刚压缩过" not in state, 1)
    S.保存("SID-1", 顾问, state, 基于版本=ver, path=库)
    d2, _, _ = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    ck("消费后存回去,下一轮不再带压缩标记", "刚压缩过" not in d2 and d2.get("当前方案"), 1, str(d2))

    print("\n\033[1m▸ 服务重启 / 两会话交错\033[0m")
    import importlib
    importlib.reload(S)       # 进程重启的效果:模块里没有任何内存态,全靠库
    d3, _, _ = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    ck("重启后照样恢复(状态在库里,不在进程里)", d3.get("当前方案", {}).get("号") == 方案[0][0], 1)
    S.保存("SID-2", 顾问, {"当前方案": {"号": 方案[1][0]}}, path=库)
    a, _, _ = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    b2, _, _ = S.加载("SID-2", 顾问, path=库, 业务库路径=业务)
    ck("两条会话各是各的方案,不串", a["当前方案"]["号"] == 方案[0][0] and b2["当前方案"]["号"] == 方案[1][0], 1)
    ck("新会话(没给 session)不继承任何东西", S.加载(None, 顾问, path=库)[0] == {}, 1)

    print("\n\033[1m▸ 对象被删 / 权限改变 / 别人的\033[0m")
    c = sqlite3.connect(业务); c.execute("DELETE FROM scheme WHERE id=?", (方案[1][0],)); c.commit(); c.close()
    d4, _, 说4 = S.加载("SID-2", 顾问, path=库, 业务库路径=业务)
    ck("上一轮在谈的方案已经被删 → 不带回来,并说明", "当前方案" not in d4 and any("不在了" in x for x in 说4), 1, str(说4))
    d5, _, 说5 = S.加载("SID-1", dict(顾问, role="店长"), path=库, 业务库路径=业务)
    d6, _, _ = S.加载("SID-1", dict(顾问, shop="SH002"), path=库, 业务库路径=业务)
    ck("角色或门店变了 → 不恢复", d5 == {} and d6 == {} and 说5, 2, f"{d5} {d6}")
    ck("别人的会话 → 不恢复", S.加载("SID-1", dict(顾问, no="B9"), path=库)[0] == {}, 1)
    ok7, 话7 = S.保存("SID-1", dict(顾问, no="B9"), {"当前方案": {"号": "X"}}, path=库)
    ck("别人的会话 → 不许写", not ok7, 1, 话7)

    print("\n\033[1m▸ 并发写\033[0m")
    _, v, _ = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    S.保存("SID-1", 顾问, {"当前方案": {"号": "新的"}}, 基于版本=v, path=库)
    ok8, 话8 = S.保存("SID-1", 顾问, {"当前方案": {"号": "旧请求的"}}, 基于版本=v, path=库)
    d8, _, _ = S.加载("SID-1", 顾问, path=库, 业务库路径=业务)
    ck("基于旧版本的写 → 不覆盖(更新的那份留着)", not ok8 and "别处更新过" in 话8, 1, 话8)

    print("\n\033[1m▸ 续聊入口:权限变了就拒\033[0m")
    真 = sessions.PATH
    sessions.PATH = os.path.join(tmp, "sessions.json")
    try:
        sessions.own("SID-9", 顾问)
        ck("本人、权限没变 → 能续聊", sessions.check("SID-9", 顾问)[0], 1)
        ok9, 话9 = sessions.check("SID-9", dict(顾问, role="店长"))
        ck("续聊时角色变了 → 拒", not ok9 and "变了" in 话9, 1, 话9)
        ck("别人的 → 拒", not sessions.check("SID-9", dict(顾问, no="B9"))[0], 1)
    finally:
        sessions.PATH = 真

    print("\n\033[1m▸ sdk.run 接上了(静态落点,行为由上面验)\033[0m")
    src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    ck("run 开头恢复、收尾存回", "_会话.加载(resume, me)" in src and "_会话.保存(_新sid, me, state" in src, 1)
    # 10-04 真出过:return 被缩进进了 `if _新sid and me:` —— 不带身份的评测(十来个脚本)全拿到 None。
    # 函数体最后一句必须是**顶层的** return,不能藏在任何分支里
    import ast
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "run")
    ck("run 不管存没存会话状态,都把结果交回去(最后一句是顶层 return)",
       isinstance(fn.body[-1], ast.Return), 1, f"最后一句是 {type(fn.body[-1]).__name__}")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if 坏:
        print(f"{R}❌ 会话状态 {坏} 条不过{D}"); return 1
    print(f"{G}✅ 会话状态全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
