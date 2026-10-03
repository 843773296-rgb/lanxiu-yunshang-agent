#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规格 §8.2「模型说明」那三个字段 · **闸逐道撞红 + 两种空分得开**。

## 这一份守的那句话

> **一个把 `[]` 存成 NULL 的接口,和一个正确存下来的,在「保存成功」那一刻长得一模一样。**

这三个字段(`model_aliases` / `when_to_use` / `task_examples`)上,
**「没给」和「给了空的」是两件不同的事**:

| 存的是 | 意思 | 页面上该显示 |
|---|---|---|
| `NULL` | **没人说过** | 「待补」—— 它是这个页签要消灭的状态 |
| `[]` | **有人看过,确认它不需要** | 「已确认不需要」 |

而这个页签的全部意义就是让人把前者变成后者。两者混掉的话,
「81 个工具里还有几个没人填过别名」这个问题**从此答不出来** ——
而那正是衡量这件事做完没做完的唯一指标。

⚠️ 写这一份时真的撞出来一个:接口第一版写的是 `体.get("别名") or None`,
于是客户端显式传的 `[]` 被存成 NULL。**注释写对了,代码写的是反的。**

## 为什么每一道闸都要**单独**撞一次

⚠️ 这个项目栽过三次:**一次注入两个破坏,只验到一个** ——
第一道闸先拦住了,后面那道根本没走到,而输出上看起来两道都红了。
所以下面每条反例**只坏一件事**,其余字段全是合法的;
并且每条**单独断它自己那句话里的关键词**,不只断「它红了」。

> 一条「红了但红的不是指定那条」,和一条真的验到了,
> **在「它红了」这个事实上长得一模一样**。

⚠️ 前提 `make dev`。这一份自己建工具、自己冻结、跑完**自己清**
(按名字清,**不按 id 前缀** —— id 是服务端生成的,按前缀清什么都删不掉,栽过)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
尾 = uuid.uuid4().hex[:6]
工具名 = f"modelcard_自测_{尾}"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U002", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务                     # noqa: E402

# ── 一份**合法**的三件套 —— 每条反例都从它复制再只坏一处 ──────────────
合法 = {
    "给模型的说明": "按 SKU 查某一款在某个门店的现货件数。只读。",
    "入参": {"type": "object", "properties": {"sku": {"type": "string"}},
             "required": ["sku"]},
    "出参": {"type": "object", "properties": {"件数": {"type": "integer"}}},
    "别名": ["还能发几件", "有没有现货", "库里还剩多少"],
    "适用不适用": {
        "适用": ["顾客问某一款现在能不能发货", "顾问要报准确的可发数量"],
        "不适用": ["问的是**还要做多久**(那是工期,不是现货)",
                   "问的是整批补货计划"],
    },
    "任务示例": [
        {"问法": "藏青 S 码那件马面裙现在还能发几件?", "来源": "记录仪"},
        {"问法": "这个色号还有货吗", "来源": "业务口述"},
        {"问法": "帮我看下 SKU-0012 的现货", "来源": "现编"},
    ],
}


def 坏一处(**改):
    """从合法那份复制,只改指定的几个键。"""
    一份 = json.loads(json.dumps(合法, ensure_ascii=False))
    一份.update(改)
    return 一份


def 建工具():
    s, r = 打("POST", P + "/tools",
              {"名称": 工具名, "用途": "查现货(§8.2 模型说明自测用)",
               "读写类型": "read_only", "接入方式": "http", "负责人": "U002"})
    if s != 201:
        print(f"  ❌ 建工具失败 {s} {r}")
        sys.exit(1)
    return r["id"]


def 冻(tid, 体):
    return 打("POST", f"{P}/tools/{tid}/versions", 体)


def 闸里有(r, *词):
    """被拦时,断**它自己那句话里的关键词** —— 不是只断「它红了」。"""
    闸 = ((r or {}).get("field_errors") or {}).get("闸") or []
    文 = " / ".join(闸)
    return all(w in 文 for w in 词), 文[:200]


def 清():
    with 事务() as c:
        c.execute(text("""delete from tool_versions where project_id=:p
                          and tool_definition_id in
                          (select id from tool_definitions
                            where project_id=:p and name=:n)"""),
                  {"p": 项目, "n": 工具名})
        c.execute(text("delete from tool_definitions where project_id=:p and name=:n"),
                  {"p": 项目, "n": 工具名})


def main():
    print("§8.2「模型说明」三个字段 · 端到端")
    print("=" * 92)
    tid = 建工具()
    try:
        # ── ① 三个都不给 → 允许(NULL = 没说过)──────────────────────
        print("\n▸ ① 三个都不给 —— **允许**,因为库里 81 个版本全没有这三样")
        光 = {k: v for k, v in 合法.items() if k in ("给模型的说明", "入参", "出参")}
        s, r = 冻(tid, 光)
        ck("一个都不给也能冻(要求必填会让所有冻结当场拒)", s == 201, f"{s} {r}")

        s, 详 = 打("GET", f"{P}/tools/{tid}")
        # ⚠️ 键名是 **`版本历史`** —— 查过返回才写的,不是猜的。
        版本们 = 详.get("版本历史") or []
        v1 = ([x for x in 版本们 if x.get("version_no") == 1] or [{}])[0]
        # ⚠️⚠️ **先断「这三个键在不在」,再断它们的值。**
        # 第一版写的是 `all(... for k in (...) if k in v1)` —— 那个 `if k in v1`
        # 让它在**一个键都没有**的时候恒为真,于是接口根本没返回这三列时
        # 它照样打勾。
        # > 一条扫了 0 个对象的断言,和一条真验到了的,**在那个 ✅ 上长得一模一样**。
        在的 = [k for k in ("model_aliases", "别名") if k in v1]
        ck("详情接口真的返回了这三列(**先断键在不在**,否则下一条是空断言)",
           len(在的) > 0, sorted(v1.keys())[:12])
        ck("没给的三个都是 null(= **没说过**,不是空的一串)",
           all(v1.get(k) is None for k in 在的 + [x for x in
               ("when_to_use", "适用不适用", "task_examples", "任务示例") if x in v1]),
           {k: v1.get(k) for k in v1 if k in
            ("model_aliases", "别名", "when_to_use", "适用不适用",
             "task_examples", "任务示例")})

        # ── ② 三个都给齐 → 原样存下来 ──────────────────────────────
        print("\n▸ ② 三个都给齐 —— 存下来要和给的**一字不差**")
        s, r = 冻(tid, 合法)
        ck("给齐了能冻", s == 201, f"{s} {str(r)[:120]}")
        with 事务() as c:
            行 = c.execute(text("""select model_aliases, when_to_use, task_examples
                                 from tool_versions
                                where project_id=:p and tool_definition_id=:t
                                order by version_no desc limit 1"""),
                          {"p": 项目, "t": tid}).mappings().first()
        行 = dict(行 or {})
        ck("别名存下来一字不差", 行.get("model_aliases") == 合法["别名"],
           行.get("model_aliases"))
        ck("适用/不适用**两边都在**", (行.get("when_to_use") or {}).get("不适用") ==
           合法["适用不适用"]["不适用"], 行.get("when_to_use"))
        ck("任务示例**每条的来路都留着**",
           [x.get("来源") for x in (行.get("task_examples") or [])] ==
           ["记录仪", "业务口述", "现编"], 行.get("task_examples"))

        # ── ③ **两种空分得开**(这一份的头号判据)────────────────────
        print("\n▸ ③ `[]` 和没给 —— **必须分得开**(接口第一版在这儿栽过)")
        s, r = 冻(tid, 坏一处(别名=[], 任务示例=[]))
        ck("显式给 `[]` 能冻(它的意思是「确认它不需要」)", s == 201, f"{s} {str(r)[:120]}")
        with 事务() as c:
            行2 = dict(c.execute(text("""select model_aliases, task_examples
                                       from tool_versions
                                      where project_id=:p and tool_definition_id=:t
                                      order by version_no desc limit 1"""),
                                {"p": 项目, "t": tid}).mappings().first() or {})
        ck("`[]` 存成空的一串,**不是 NULL** —— "
           "存成 NULL 的话「还没人填」和「确认不需要」就永远分不开了",
           行2.get("model_aliases") == [] and 行2.get("task_examples") == [],
           {"别名": 行2.get("model_aliases"), "任务示例": 行2.get("task_examples")})

        # ── ④ `适用/不适用` 只给一半 → 拒(规格第 6 步点名的那道闸)──
        print("\n▸ ④ 只给「适用」不给「不适用」—— **当场拒**")
        s, r = 冻(tid, 坏一处(适用不适用={"适用": ["顾客问现货"]}))
        ck("只给一半 → 422 CANNOT_FREEZE_TOOL",
           s == 422 and (r or {}).get("code") == "CANNOT_FREEZE_TOOL", f"{s} {(r or {}).get('code')}")
        好, 文 = 闸里有(r, "不适用", "静默变成")
        ck("拦的话里说清了为什么(「不适用」会**静默变成「没说过」**)", 好, 文)

        s, r = 冻(tid, 坏一处(适用不适用={"适用": ["x"], "不适用": []}))
        好, 文 = 闸里有(r, "不适用")
        ck("「不适用」给了空的一串 → 也拒(空的适用面等于这工具没有适用场景)",
           s == 422 and 好, 文)

        s, r = 冻(tid, 坏一处(适用不适用=["顾客问现货"]))
        好, 文 = 闸里有(r, "要给一个对象")
        ck("`适用不适用` 给成了一串 → 拒并说清要给对象", s == 422 and 好, 文)

        s, r = 冻(tid, 坏一处(适用不适用={**合法["适用不适用"], "有时候": ["x"]}))
        好, 文 = 闸里有(r, "不认识的键")
        ck("多了不认识的键 → 拒(**不许静默丢掉** —— 丢掉的那条写的人以为它生效了)",
           s == 422 and 好, 文)

        # ── ⑤ 任务示例必须带来路 ──────────────────────────────────
        print("\n▸ ⑤ 任务示例 —— **每条都要带来路**,「现编」必须标出来")
        s, r = 冻(tid, 坏一处(任务示例=[{"问法": "还能发几件?"}]))
        好, 文 = 闸里有(r, "来路", "先看答案再出题")
        ck("某条没写「来源」→ 拒,并说清理由(10-03 那次 21/21)", s == 422 and 好, 文)

        s, r = 冻(tid, 坏一处(任务示例=[{"问法": "还能发几件?", "来源": "我猜的"}]))
        好, 文 = 闸里有(r, "来源")
        ck("「来源」不在枚举里 → 拒(枚举它是有意的)", s == 422 and 好, 文)

        s, r = 冻(tid, 坏一处(任务示例=[{"来源": "记录仪"}]))
        好, 文 = 闸里有(r, "问法")
        ck("某条没写「问法」→ 拒", s == 422 and 好, 文)

        # ── ⑥ 别名:填了等于没填的那种,也要拒 ────────────────────
        print("\n▸ ⑥ 别名 —— **填了等于没填**的那种也拒")
        s, r = 冻(tid, 坏一处(别名=["还能发几件", 工具名]))
        好, 文 = 闸里有(r, "什么也没加")
        ck("一条别名和工具名一字不差 → 拒 —— "
           "它在召回上和没填一样,而在界面上像「已经填过了」", s == 422 and 好, 文)

        s, r = 冻(tid, 坏一处(别名=["有没有现货", "有没有现货"]))
        好, 文 = 闸里有(r, "重复")
        ck("别名里有重复 → 拒", s == 422 and 好, 文)

        s, r = 冻(tid, 坏一处(别名=["有没有现货", "   "]))
        好, 文 = 闸里有(r, "非空字符串")
        ck("别名里有空白串 → 拒", s == 422 and 好, 文)

        # ── ⑦ 被拦这件事进审计(和这条口既有的做法一致)─────────────
        print("\n▸ ⑦ 被拦**要留痕** —— 一次被拦而没留痕的冻结,和没人试过长得一样")
        with 事务() as c:
            # ⚠️ 表名列名**查过库才写**:第一版写的是 `audit_logs` / `target`,
            # 真名是 `audit_events` / `target_ref`。
            # 「凭名字猜表」这一族在这个仓库犯过八次,每次都只在走到那条路径时才炸。
            n = c.execute(text("""select count(*) from audit_events
                                 where project_id=:p and action='tool.version.blocked'
                                   and target_ref->>'tool_id'=:t"""),
                          {"p": 项目, "t": tid}).scalar()
        ck("上面那 9 次被拦都记进了审计", n >= 9, f"审计里 {n} 条")

        # ── ⑧ 详情接口真把三列带出来了(不是只在库里)──────────────
        print("\n▸ ⑧ 详情接口带出来了吗 —— **库里有而接口不给,页面就做不起来**")
        s, 详 = 打("GET", f"{P}/tools/{tid}")
        版本们 = 详.get("版本历史") or []
        带了 = [v for v in 版本们
               if all(k in v for k in ("别名", "适用不适用", "任务示例"))]
        ck("详情接口每一版都带着这三个字段", 带了 and len(带了) == len(版本们),
           sorted(版本们[0].keys())[:16] if 版本们 else "没版本")
        # ── ⑨ 三态:`null` 和 `[]` 在**界面要显示的那句话**上也分得开 ──
        print("\n▸ ⑨ 三态在服务端算 —— `null` 和 `[]` 在 JS 里都是 falsy,"
              "一句 `if (!别名)` 会把「确认不需要」也显示成「待补」")
        状 = {v["version_no"]: v.get("模型说明填了吗") or {} for v in 版本们}
        ck("第 1 版(什么都没给)→「没说过」", 状.get(1, {}).get("别名") == "没说过", 状.get(1))
        ck("第 2 版(给齐了)→「填了 3 条」", 状.get(2, {}).get("别名") == "填了 3 条", 状.get(2))
        ck("第 3 版(显式给 `[]`)→「确认不需要」**不是「没说过」**",
           状.get(3, {}).get("别名") == "确认不需要", 状.get(3))
    finally:
        清()

    print("\n" + "=" * 92)
    print(f"过 {len(过)} · 挂 {len(挂)}")
    for x in 挂:
        print("   ❌", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
