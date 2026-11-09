#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天站接术语(2026-11-06 深夜,用户拍「接聊天站」)—— 每一轮只带这句话里提到的业务术语。

**不调模型、不连后台**:注入用真的 hook(guards.make_hooks)跑一遍 on_prompt;同步用假的 glossary_client.同步。
  ① 同步到了术语、这句话提到「到店转化」→ 注入原文里有「到店率」的定义和口径,没有没提到的「褙子」;记下带了哪几条
  ② 这句话一条术语都没提到 → 什么都不加(不带空壳),也不记「带了」
  ③ 没同步到术语(没接后台 / 没挂 / 没配助手:state 里没有或条数 0)→ 不加,但来源那句话照样记下来
  ④ 段是后台那份纯函数拼的(glossary_client.这一段 → 管理后台 runtime/术语.py),不是这里另写的
  ⑤ 「启动时同步」:同一个进程里 _术语状态 只同步一次;同步抛错 → 记成「取不到」,不让聊天跟着崩
  ⑥ 接线:sdk.run 只在「后台配置 + 店长助手(task)」那条路上把术语放进 state(别的角色后台没配助手)
  ⑦ 照术语答的数算有出处:术语段并进这一轮的规矩原文,g1「数字要有出处」不打回(11-06 深夜真跑撞到:两稿都被扣下);
     没注入术语时同一句照样打回(只认这一轮真发给模型的)
"""
import asyncio, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
咬合 = [      # 规格在 tools/bite_specs.json(script = 这个文件),bite_run 重放过三关
    ("一条都没提到也照拼一段", "② 一条都没提到 → 不加任何术语"),
    ("所有角色都去同步术语", "⑥ 接线:sdk.run 只在「后台配置 + task」那条路上"),
    ("每一轮都重新同步术语", "⑤ 同一个进程里只同步一次"),
    ("术语段不并进这一轮的规矩原文", "⑦ 照术语答的数(30 天)算有出处"),
]
坏 = 0

表 = [{"标准词": "到店率", "叫法": ["到店转化"], "类别": "指标", "定义": "预约了的人里真到店的比例_chk",
      "口径": {"分母": "已到时间的全部预约_chk"}},
     {"标准词": "褙子", "叫法": [], "类别": "名词", "定义": "宋制对襟长衣_chk"}]


def ck(名, ok, 说明=""):
    global 坏
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}{'' if ok else '  ' + str(说明)[:300]}")
    坏 += 0 if ok else 1


def 跑(state, 话):
    import guards
    on = guards.make_hooks(state)["UserPromptSubmit"][0].hooks[0]
    r = asyncio.run(on({"prompt": 话}, None, None)) or {}
    return (r.get("hookSpecificOutput") or {}).get("additionalContext", "")


def main():
    状 = {"态": "有", "版本": "v1", "术语": 表, "条数": 2, "来源": "后台", "说明": "术语:v1 · 2 条"}
    st = {"术语": 状}
    注 = 跑(st, "上周到店转化怎么样")
    ck("① 提到「到店转化」→ 注入里有到店率的定义和口径,没有没提到的褙子;记下带了哪几条",
       "预约了的人里真到店的比例_chk" in 注 and "已到时间的全部预约_chk" in 注 and "宋制对襟长衣_chk" not in 注
       and st.get("术语带了") == {"版本": "v1", "条": ["到店率"]}, (注[-400:], st.get("术语带了")))
    import glossary_client as _gc
    段, _ = _gc.这一段("上周到店转化怎么样", 状)
    ck("④ 注进去的那段就是后台纯函数拼的那段(不另写一份)", bool(段) and 段 in 注, 段[:120])
    import guards as _g
    答 = "到店率的分母是已到时间的全部预约,统计期 30 天内预约的都算。"
    带术语 = {"术语": dict(状, 术语=[dict(表[0], 口径={"分母": "已到时间的全部预约_chk", "时间": "按近 30 天"})])}
    跑(带术语, "到店转化怎么算")
    未注入 = {}
    跑(未注入, "到店转化怎么算")
    ck("⑦ 照术语答的数(30 天)算有出处:术语段并进规矩原文,g1 不打回;没注入术语时同一句照样打回",
       not _g.g1_no_source(答, [], "到店转化怎么算", 规矩=带术语.get("规矩原文") or "")
       and bool(_g.g1_no_source(答, [], "到店转化怎么算", 规矩=未注入.get("规矩原文") or "")),
       (带术语.get("规矩原文", "")[-200:], _g.g1_no_source(答, [], "到店转化怎么算", 规矩=未注入.get("规矩原文") or "")))
    st = {"术语": 状}
    注 = 跑(st, "今天天气不错")
    ck("② 一条都没提到 → 不加任何术语、不记「带了」", "_chk" not in 注 and "业务术语" not in 注 and "术语带了" not in st, 注[-200:])
    for 名, st in (("state 里没有术语", {}), ("条数 0(没挂 / 没配助手)", {"术语": dict(状, 术语=[], 条数=0, 态="没配助手", 说明="没配助手_说明")})):
        有 = bool(st)          # 先记下:hook 会往 state 里写东西,事后再判「空不空」就不对了
        注 = 跑(st, "上周到店转化怎么样")
        ck(f"③ {名} → 不加术语" + ("、来源那句话照样记下" if 有 else ""),
           "_chk" not in 注 and (not 有 or st.get("术语来源") == "没配助手_说明"), (注[-200:], st.get("术语来源")))

    import sdk
    次 = []
    原 = _gc.同步
    try:
        _gc.同步 = lambda 角色: (次.append(角色), dict(状))[1]
        sdk._术语缓存.clear()
        a, b = sdk._术语状态("task"), sdk._术语状态("task")
        ck("⑤ 同一个进程里只同步一次(启动时同步)", 次 == ["task"] and a is b, 次)
        def 炸(角色):
            raise RuntimeError("后台炸了")
        _gc.同步 = 炸
        sdk._术语缓存.clear()
        x = sdk._术语状态("task")
        ck("⑤ 同步抛错 → 记成「取不到」、没有术语,不让聊天跟着崩", x.get("态") == "取不到" and not x.get("术语"), x)
    finally:
        _gc.同步 = 原
        sdk._术语缓存.clear()
    源 = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    行 = [l for l in 源.split("\n") if 'state["术语"] = dict(_术语状态(' in l]
    i = 源.find('state["术语"] = dict(_术语状态(')
    条件 = 源[源.rfind("\n    if ", 0, i):i]
    ck("⑥ 接线:sdk.run 只在「后台配置 + task」那条路上把术语放进 state",
       len(行) == 1 and "后台配置" in 条件 and 'kind == "task"' in 条件, (行, 条件[:200]))
    # ⑧ 第三期:浅拷贝防串台;挂了意图版本才分类,结果进返回值(走语法树,别搜字符串 —— 注释会顶住判据)
    import ast as _ast
    树 = _ast.parse(源)
    调 = [x for x in _ast.walk(树) if isinstance(x, _ast.Call) and isinstance(x.func, _ast.Attribute) and x.func.attr == "to_thread"
         and len(x.args) >= 2 and isinstance(x.args[0], _ast.Attribute) and x.args[0].attr == "判意图"]
    ck("⑧ 接线:sdk.run 真的调了 判意图(放线程里,不堵住别的会话)", len(调) == 1, len(调))
    ck("⑧ 接线:挂了意图版本才分类(判意图 在 if _意配 底下)", any(isinstance(n, _ast.If) and getattr(n.test, "id", "") == "_意配"
       and any(c in _ast.walk(n) for c in 调) for n in _ast.walk(树)), False if not 调 else "没找到")
    print()
    if 坏:
        print(f"{R}❌ {坏} 条不过{D}")
        return 1
    print(f"{G}✅ 聊天站接术语:全过{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
