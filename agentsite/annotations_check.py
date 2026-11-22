#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标注回复 · 聊天站这一半(11-22)检查 —— 不连后台、不调模型(模型调用注入假的)。
  ① 开关关 / 清单空 → 不问模型、不命中;后台拉不到 → 保留上一份(不忽开忽关)
  ② 候选按角色筛:记了别的角色的不算;没记角色的对谁都算;最多 40 条
  ③ 解析命中:只认 JSON 里的 命中;0 / 越界 / 乱文 → None;模型抛错 → None(走原路)
  ④ 命中回答:text **逐字**是标准答案、零花费、没 trace、标明来源;会话原样带回
  ⑤ app.py:/run 里标注那一段在难题分流**之前**、在会话归属校验**之后**;有图的问题不走标注;命中后报命中
"""
import os
import sys

这 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 这)
import annotations as A  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:220]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


清单 = [{"id": "ann_1", "question": "香云纱能不能机洗?", "standard_answer": "不能机洗,只能手洗阴干。", "assistant_role": "门店顾问"},
      {"id": "ann_2", "question": "马面裙的褶子怎么保养", "standard_answer": "挂起来存放,别压。", "assistant_role": None},
      {"id": "ann_3", "question": "工坊排产规则是什么", "standard_answer": "先到先排,加急另议。", "assistant_role": "工坊排产"}]
问过 = []


def 假调(body):
    问过.append(body)
    return '{"命中": 1}'


print("▸ ① 开关 / 清单")
A._缓存.update(at=1e12, 开关=False, items=清单)   # 缓存里:关着
问过.clear()
ck("开关关 → None,且没问模型", A.试命中("香云纱可以机洗吗", "门店顾问", 调=假调, 现在=1e12) is None and not 问过)
A._缓存.update(开关=True, items=[])
ck("开关开但清单空 → None,没问模型", A.试命中("香云纱可以机洗吗", "门店顾问", 调=假调, 现在=1e12) is None and not 问过)
A._缓存.update(开关=True, items=清单)
老 = A._调
A._调 = lambda *a, **k: (0, {"_异常": "URLError"})
开, 项 = A.清单(强制=True, 现在=1e12 + 1)
A._调 = 老
ck("后台拉不到 → 保留上一份(开着、三条)", 开 is True and len(项) == 3, (开, len(项)))

print("\n▸ ② 候选按角色")
ck("门店顾问:自己的 + 没记角色的,排除工坊排产那条", [x["id"] for x in A.候选(清单, "门店顾问")] == ["ann_1", "ann_2"])
ck("不给角色 → 全算", len(A.候选(清单)) == 3)
ck("最多 40 条", len(A.候选([{"question": "q", "standard_answer": "a"}] * 100)) == 40)
ck("缺问题或缺答案的不算候选", A.候选([{"question": "", "standard_answer": "a"}, {"question": "q", "standard_answer": None}]) == [])

print("\n▸ ③ 解析与容错")
ck("解析:1..n 认;0 / 越界 / 乱文 → None", A.解析命中('{"命中": 2}', 3) == 2 and A.解析命中('{"命中": 0}', 3) is None and A.解析命中('{"命中": 9}', 3) is None and A.解析命中("不确定", 3) is None)
问过.clear()
命 = A.试命中("香云纱可以机洗吗", "门店顾问", 调=假调, 现在=1e12)
ck("开关开 + 有候选 → 问了一次模型,命中第 1 条;提示词里有清单和新问题、要求不确定答 0", 命 and 命["id"] == "ann_1" and len(问过) == 1
   and "不确定就答 0" in 问过[0]["messages"][0]["content"] and "香云纱可以机洗吗" in 问过[0]["messages"][0]["content"], (命, len(问过)))
ck("提示词只列候选(工坊那条没进门店顾问的清单)", "工坊排产规则" not in 问过[0]["messages"][0]["content"])


def 炸(body):
    raise RuntimeError("curl 失败")


ck("模型调用抛错 → None(走原路,不让回答失败)", A.试命中("香云纱可以机洗吗", "门店顾问", 调=炸, 现在=1e12) is None)
ck("模型答 0 → None", A.试命中("香云纱可以机洗吗", "门店顾问", 调=lambda b: '{"命中": 0}', 现在=1e12) is None)

print("\n▸ ④ 命中回答")
r = A.命中回答(清单[0], "香云纱可以机洗吗", "sess-1")
ck("text 逐字 = 标准答案;零花费;没 trace;会话原样;标明来源与标注 id", r["text"] == "不能机洗,只能手洗阴干。" and r["cost_usd"] == 0.0 and r["trace_id"] is None
   and r["session_id"] == "sess-1" and r["标注命中"]["id"] == "ann_1" and r["路由"]["答的"] == "标注回复" and "标注" in r["说明"], r)

print("\n▸ ⑤ app.py 接线")
ap = open(os.path.join(这, "app.py"), encoding="utf-8").read()
会 = ap.find('ok_s, why_s = sessions.check(sid_in, me)'); 标 = ap.find("_an.试命中(prompt"); 分 = ap.find("import model_route as _mr")
ck("标注那一段在会话归属校验之后、难题分流之前", 0 < 会 < 标 < 分, (会, 标, 分))
ck("有图的问题不走标注;命中后 报命中 并直接返回", "if not imgs:" in ap[标 - 400:标] and "_an.报命中(_命.get(\"id\"))" in ap and "return self._send(r)" in ap[标:标 + 600])
ck("角色名从 sdk.ROLE_META[kind].name 取(标注记的是中文角色名)", '(sdk.ROLE_META.get(kind) or {}).get("name")' in ap)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 标注回复聊天站一半 {len(过)} 条全过")
