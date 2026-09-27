#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精排的校验逻辑 —— **零依赖,不发一个请求。**

## 为什么这个文件必须不发请求

`reranker.py` 里最要紧的部分是那三条挡 LLM 编造的判据:
编号集合相等、引文真的在片段里、0 分免引文。

而 **CI 里没有 Claude 凭据**(admin job 只装 sqlalchemy,也没有钥匙串)。
所以判据必须能在不发请求的情况下被测:

> **一条只在手工跑时被验过的防护,和没有防护的差别只在验的人脑子里。**

所以校验被提成了纯函数 `校验打分(打分们, 编号到候选)`,
这个文件直接喂它「模型可能返回的各种坏东西」。

真调 Claude 的那部分(效果:表格头该拿 0 分)在 `make test-live` 里 ——
它要凭据、要花月租额度、结果有波动,放进门禁会变成随机拦路。
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "knowledge"))
import reranker as R  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def _抛(f, 类=R.精排失败):
    try:
        f()
    except 类:
        return True
    except Exception as e:
        print(f"     (抛的是 {type(e).__name__}: {str(e)[:60]})")
        return False
    return False


候选 = {
    1: {"id": "c1", "text": "| # | 要做的 | 判据 / 验法 |\n|---|---|---|"},
    2: {"id": "c2", "text": "**决定**:五星制,**≤3 星算差评**;差评**自动进待处理清单**(有人负责跟)。"},
    3: {"id": "c3", "text": "香云纱是用薯莨汁反复涂晒的面料,不能高温熨烫。"},
}

print("▸ ① 正常情况:排序按分数,同分按原序")
好 = [{"index": 1, "score": 0, "quote": ""},
      {"index": 2, "score": 9, "quote": "差评自动进待处理清单"},
      {"index": 3, "score": 0, "quote": ""}]
r = R.校验打分(好, 候选)
ck("按分数从高到低", [x["id"] for x in r] == ["c2", "c1", "c3"], [x["id"] for x in r])
ck("每项带 id / 分数 / 引文 / 原序",
   all(set(("id", "分数", "引文", "原序")) <= set(x) for x in r))
ck("片段本身也带回去(证据链要能指回原文)", all("text" in x for x in r))

print("\n▸ ② **集合相等** —— 编出来的编号和漏掉的,两头都要抓")
ck("编出一个不存在的编号(4)→ 抛",
   _抛(lambda: R.校验打分(好 + [{"index": 4, "score": 5, "quote": "x"}], 候选)))
ck("**漏掉一个候选**(只回 2 条)→ 抛 —— "
   "漏掉的会**静默消失在结果里**,而「至少返回了一条」这种判据抓不到",
   _抛(lambda: R.校验打分(好[:2], 候选)))
ck("同一个编号打两次 → 抛",
   _抛(lambda: R.校验打分(好 + [{"index": 2, "score": 3, "quote": "五星制"}], 候选)))
ck("`results` 不是清单 → 抛", _抛(lambda: R.校验打分({"index": 1}, 候选)))

print("\n▸ ③ **引文必须真的在片段里** —— 这条把「理由可信」变成可执行的")
编了 = [{"index": 1, "score": 0, "quote": ""},
       {"index": 2, "score": 9, "quote": "差评要在三天内回访客户"},   # 片段里没这句
       {"index": 3, "score": 0, "quote": ""}]
ck("引文是编的(听起来合理但片段里没有)→ 抛", _抛(lambda: R.校验打分(编了, 候选)))
剥了格式 = [{"index": 1, "score": 0, "quote": ""},
         {"index": 2, "score": 9, "quote": "≤3 星算差评;差评自动进待处理清单"},
         {"index": 3, "score": 0, "quote": ""}]
ck("引文抄了原话但**剥掉了 Markdown 标记** → **过**"
   "(逐字节比会把真引用判成编的,而那让功能完全不可用)",
   len(R.校验打分(剥了格式, 候选)) == 3)
表格 = [{"index": 1, "score": 4, "quote": "# 要做的 判据 / 验法"},
       {"index": 2, "score": 9, "quote": "五星制"},
       {"index": 3, "score": 0, "quote": ""}]
ck("表格片段的引文剥掉 `|` 之后能对上 → 过", len(R.校验打分(表格, 候选)) == 3)
空引 = [{"index": 1, "score": 0, "quote": ""},
      {"index": 2, "score": 9, "quote": ""},        # 9 分却没引文
      {"index": 3, "score": 0, "quote": ""}]
ck("给了 9 分但引文是空的 → 抛(非 0 分意味着「回答了」,那就该指出是哪一句)",
   _抛(lambda: R.校验打分(空引, 候选)))

print("\n▸ ④ **0 分免于引文校验** —— 判据不该逼被测对象造假")
# 引文的作用是支撑「为什么这段相关」,而 0 分的意思正是「不相关」。
# 要求 0 分的候选给引文 = 逼模型为一个不存在的关联编一个证据。
零分乱引 = [{"index": 1, "score": 0, "quote": "这句话片段里完全没有"},
         {"index": 2, "score": 9, "quote": "五星制"},
         {"index": 3, "score": 0, "quote": "这句也没有"}]
ck("0 分的候选引文对不上 → **过**(0 分 = 不相关,没有可引的)",
   len(R.校验打分(零分乱引, 候选)) == 3)

print("\n▸ ⑤ 分数本身要合格")
for 坏分, 说 in ((11, "超上限"), (-1, "负数"), ("9", "字符串"), (None, "空"),
              (True, "布尔(`isinstance(True,int)` 为真,要单独排掉)")):
    坏 = [{"index": 1, "score": 0, "quote": ""},
         {"index": 2, "score": 坏分, "quote": "五星制"},
         {"index": 3, "score": 0, "quote": ""}]
    ck(f"分数是 {坏分!r}({说})→ 抛", _抛(lambda: R.校验打分(坏, 候选)))

print("\n▸ ⑥ 没凭据时**抛,不退回原顺序**")
# 那会让「精排坏了」和「精排认为原顺序就是对的」长得一模一样 ——
# 而前者是故障,后者是结论。
_原 = os.environ.get("ANTHROPIC_API_KEY")
import subprocess                                         # noqa: E402
_原run = subprocess.run
try:
    os.environ.pop("ANTHROPIC_API_KEY", None)
    subprocess.run = lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "",
                                                    "stderr": ""})()
    ck("拿不到凭据 → 抛 `没有凭据`(**不返回按原顺序排的结果**)",
       _抛(lambda: R.精排("问题", [{"id": "c", "text": "文"}]), R.没有凭据))
finally:
    subprocess.run = _原run
    if _原 is not None:
        os.environ["ANTHROPIC_API_KEY"] = _原
ck("空候选 → 抛(「没召回到」和「排完是空的」是两件事)",
   _抛(lambda: R.精排("问题", [])))

print("\n▸ 咬合:把那三条判据关掉,对应的测试必须变红\n" + "-" * 78)
咬过 = []


def 咬(名, 改坏, 恢复, 判据):
    改坏()
    try:
        红 = not 判据()
    except Exception:
        红 = True
    finally:
        恢复()
    咬过.append(红)
    print(f"  {'✅' if 红 else '❌'} 咬合「{名}」→ {'判据红了' if 红 else '**判据还是绿的**'}")


_原剥 = R._剥格式
咬("`_剥格式` 什么都不剥(逐字节比)—— 真引用会被判成编的",
  lambda: setattr(R, "_剥格式", lambda t: t),
  lambda: setattr(R, "_剥格式", _原剥),
  lambda: len(R.校验打分(剥了格式, 候选)) == 3)
咬("`_剥格式` 剥到只剩汉字(连标点都去掉)—— 那就太松了,"
  "重写一句话也能过",
  lambda: setattr(R, "_剥格式",
                  lambda t: "".join(c for c in t if "一" <= c <= "龥")),
  lambda: setattr(R, "_剥格式", _原剥),
  # ⚠️ 这个样本是**量出来的**,不是想出来的。它必须
  # **在正常判据下被抓、在改坏后漏过** —— 否则咬合没有信息量。
  #   片段剥格式后:  决定:五星制,≤3星算差评;差评自动进待处理清单(有人负责跟)。
  #   片段只剩汉字:  决定五星制星算差评差评自动进待处理清单有人负责跟
  #   引文「星算差评差评自动」:正常判据**抓**(中间有个 `;`),只剩汉字时**过**
  # (第一版我选了「差评清单进自动」,它在两种情况下都被抓 —— 证明不了任何事。)
  lambda: _抛(lambda: R.校验打分(
      [{"index": 1, "score": 0, "quote": ""},
       {"index": 2, "score": 9, "quote": "星算差评差评自动"},
       {"index": 3, "score": 0, "quote": ""}], 候选)))

print(f"\n{'✅' if all(咬过) else '❌'} 咬合 {sum(咬过)}/{len(咬过)} 条如预期")
if not all(咬过):
    挂.append("咬合有没咬住的")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
