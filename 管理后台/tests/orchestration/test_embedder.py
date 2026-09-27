#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Embedding 适配器 —— **判据主要冲着「mock 被当成真的」去**。

## 这一组和别处不同的地方

mock 文本生成器吐出来的东西一眼看得出是假的。mock **向量**不是:
它算出来的相似度是个看起来很正常的数字(0.83),而人会拿它当效果读。

而 mock 向量是从文本哈希派生的,所以**语义相近的两段话向量完全不相关** ——
mock 下的检索排序本质上是随机的。第 ④ 组就在钉这件事:
不是「它应该不相关」,而是「**这件事必须能被看见**」(`是mock` 跟着数据走)。

## 跨进程确定性为什么要单独验

Python 内置的 `hash()` 对 str 加了**随机盐**,每个进程不一样。
所以一个用 `hash()` 派生向量的实现,**在同一个进程里测永远是确定的**,
换个进程就变。而这些向量要进数据库 —— **库里的数据比解释器活得久**。

所以第 ② 组在另一个进程里算一次再比。在同进程里测这件事,
测的是一个必然成立的命题。
"""
import io
import os
import subprocess
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
知识 = os.path.join(根, "services", "api", "app", "knowledge")
sys.path.insert(0, 知识)
import embedder as E  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{'  ' + str(补)[:160] if 补 else ''}")
    (过 if 真 else 挂).append(名)


def _抛(f, 类):
    try:
        f()
    except 类:
        return True
    except Exception as e:
        print(f"     (抛的是 {type(e).__name__},要的是 {类.__name__})")
        return False
    return False


样本 = ["签收当场就请评价,**不等回家**", "同一段话", "同一段话", "完全无关的另一件事情"]
r = E.算(样本)

print("▸ ① 形状:维度、条数、必填字段")
ck("返回和入参等长(少一条会让片段和向量对不上,而那不报错)", len(r) == len(样本), len(r))
ck(f"每条都是 {E.维度} 维(和 embeddings.embedding 列的 vector(1536) 一致)",
   all(len(x["向量"]) == E.维度 for x in r), {len(x["向量"]) for x in r})
ck("每条都带 `是mock` 且为真 —— **这个标记要跟着数据走到界面上**",
   all(x.get("是mock") is True for x in r))
ck("每条都带 `适配器版本`(换了实现要能从数据上看出来)",
   all(x.get("适配器版本") == E.适配器版本 for x in r), E.适配器版本)
ck("归一化过(模长是 1)——**零向量会让余弦变成 0/0**",
   all(abs(sum(y * y for y in x["向量"]) ** 0.5 - 1.0) < 1e-9 for x in r))

print("\n▸ ② 确定性:同进程 **和另一个进程** 都要一样")
ck("同一段文本两次算出同一个哈希和同一个向量",
   r[1]["text_hash"] == r[2]["text_hash"] and r[1]["向量"] == r[2]["向量"])


def 判_跨进程确定():
    """⚠️ **另起一个进程**。用 `hash()` 派生的实现在同进程里测永远是确定的
    (随机盐每进程固定),换进程才露出来。而这些值要进数据库。"""
    码 = ("import sys; sys.path.insert(0, %r)\n"
          "import embedder as E\n"
          "r = E.算(['签收当场就请评价,**不等回家**'])[0]\n"
          "print(r['text_hash']); print(r['向量'][0]); print(r['向量'][-1])\n") % 知识
    p = subprocess.run([sys.executable, "-c", 码], capture_output=True, text=True,
                       env={**os.environ, "PYTHONHASHSEED": "random"})
    if p.returncode != 0:
        print("     子进程炸了:", p.stderr.strip()[:120])
        return False
    哈, 首, 末 = p.stdout.strip().split("\n")
    return (哈 == r[0]["text_hash"] and float(首) == r[0]["向量"][0]
            and float(末) == r[0]["向量"][-1])


ck("**另一个进程(PYTHONHASHSEED=random)算出完全一样的向量** —— "
   "库里的数据比解释器活得久", 判_跨进程确定())

print("\n▸ ③ 不许糊弄维度")
ck("要 768 维 → 抛(**不许截断也不许补零**:截断丢信息,补零造假信息)",
   _抛(lambda: E.算(["一段话"], 期望维度=768), E.维度不符))
ck("两个不同维度的向量算余弦 → 抛(这正是维度写死在列类型上要防的事)",
   _抛(lambda: E.余弦([1.0, 0.0], [1.0, 0.0, 0.0]), E.维度不符))
ck("空文本 → 抛(空片段该在切片阶段被丢掉并计数,不该走到这一步)",
   _抛(lambda: E.算(["   "]), ValueError))
ck("零向量归一化 → 抛(不静默返回零向量:余弦会变 0/0,"
   "而**排序里的 NaN 不报错,只是排到某个位置**)",
   _抛(lambda: E.归一化([0.0] * 8), E.维度不符))

print("\n▸ ④ mock 对语义**没有感知** —— 这件事必须能被看见,不是缺点而是事实")
自己 = E.余弦(r[1]["向量"], r[2]["向量"])
无关 = E.余弦(r[0]["向量"], r[3]["向量"])
ck("同一段文本余弦 = 1", abs(自己 - 1.0) < 1e-9, round(自己, 9))
ck("两段**人读起来完全不同**的文本,余弦接近 0(随机)", abs(无关) < 0.15, round(无关, 4))
# ⚠️ 这一条不是在测 embedder,是在测**这件事有没有被写下来**。
# 「mock 的相似度不代表语义」如果只活在我脑子里,下一个人会拿它当效果。
ck("`算()` 的文档里写明了 mock 的相似度不代表语义",
   "是mock" in (E.算.__doc__ or "") and "不代表语义" in (E.算.__doc__ or ""))
ck("模块文档开头就点出「mock 向量比 mock 文本危险」",
   "危险" in (E.__doc__ or "")[:200])

print("\n▸ ⑤ 进库的字面量不许丢精度")


def 判_往返不丢精度():
    """⚠️ 截到固定小数位会让**两个不同的向量变成同一个字符串** ——
    mock 向量的分量分布很密,而唯一约束和检查点都会指向错误的东西。"""
    v = r[0]["向量"]
    s = E.成SQL文本(v)
    回 = [float(x) for x in s.strip("[]").split(",")]
    return 回 == v


ck("`成SQL文本` → 解析回来**一个比特都不差**(用 repr 而不是固定小数位)",
   判_往返不丢精度())

print("\n▸ 咬合:改坏了要红\n" + "-" * 78)
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


_原成SQL = E.成SQL文本
咬("`成SQL文本` 截到 6 位小数(两个不同向量会变成同一个字符串)",
  lambda: setattr(E, "成SQL文本",
                  lambda v: "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"),
  lambda: setattr(E, "成SQL文本", _原成SQL),
  判_往返不丢精度)

# ⚠️ **这一条咬合必须真的改文件,不能 monkeypatch。**
# 第一版用了 `setattr(E, "_伪随机向量", …)`,咬合**绿了** ——
# 因为 `判_跨进程确定()` 起的是子进程,子进程 import 的是磁盘上那份真的 embedder,
# 父进程的 patch 影响不到它;而父进程那份参照值是在 patch 之前算的。
# 于是判据比的是「真向量 vs 真向量」,永远相等。
#
# 而那个绿**长得像「判据没问题」**,实际是「咬合根本没生效」。
# 写了咬合却不看它红不红,和没写咬合是一回事。
_源路径 = os.path.join(知识, "embedder.py")
_原源码 = io.open(_源路径, encoding="utf-8").read()


def _改坏成hash():
    坏 = _原源码.replace(
        '        块 = hashlib.sha256(f"{种子串}#{计}".encode("utf-8")).digest()',
        '        块 = struct.pack(">I", hash(f"{种子串}#{计}") % 4294967295) * 8')
    assert 坏 != _原源码, "替换没命中 —— 咬合改不坏就等于没咬合"
    io.open(_源路径, "w", encoding="utf-8").write(坏)


咬("用 `hash()` 派生向量(同进程测永远是确定的,换进程就变)——**真的改文件**",
  _改坏成hash,
  lambda: io.open(_源路径, "w", encoding="utf-8").write(_原源码),
  判_跨进程确定)

_原归一 = E.归一化
咬("零向量静默返回零向量(余弦变 0/0,排序里的 NaN 不报错)",
  lambda: setattr(E, "归一化", lambda v: list(v)),
  lambda: setattr(E, "归一化", _原归一),
  lambda: _抛(lambda: E.归一化([0.0] * 8), E.维度不符))

print(f"\n{'✅' if all(咬过) else '❌'} 咬合 {sum(咬过)}/{len(咬过)} 条如预期")
if not all(咬过):
    挂.append("咬合有没咬住的")

# ⚠️ **上面有一条咬合会真的改 `embedder.py`。** 恢复靠 `咬()` 里的 `finally`,
# 而 finally 挡不住 kill -9。源码被留在坏状态的症状是「向量不再跨进程确定」——
# 那要等到有人重跑一个旧构建、发现片段全部要重算时才会暴露,
# 而那时**没人会想到去看测试文件**。
# 所以这里自己验一次,和数据库测试里那条「跑完之后表是空的」同源。
print("")
现源码 = io.open(_源路径, encoding="utf-8").read()
ck("跑完之后 `embedder.py` 和开跑时**一个字节都没差**"
   "(那条咬合真的改了文件;finally 挡不住 kill -9)",
   现源码 == _原源码,
   "**源码被留在改坏的状态** —— 立刻 `git checkout` 它" if 现源码 != _原源码
   else f"{len(现源码)} 字节,一致")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
