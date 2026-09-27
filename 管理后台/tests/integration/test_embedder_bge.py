#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真 Embedding(BGE-small-zh-v1.5)—— **判据是语义有效性,不是形状。**

## 为什么形状判据在这里没用

「返回 512 维」「模长是 1」「跑得通」这些**在 pooling 用错的时候也全过**。
而 pooling 用错的后果是:能跑、数字看着正常(0.83 这种)、**排序变差** ——
没有任何一条形状判据会红。

BGE 有两个搞错不报错的地方:
  ① 它是**非对称**的:查询加前缀、文档不加。两边都加或都不加,效果下降
  ② 它用 **CLS pooling**(取第一个 token),不是常见的 mean pooling

所以这里的主判据是**四档层级**:

    完全相同 > 明显同义 > 同主题不同事 > 完全无关

这四档的**顺序**必须成立。它是能抓到 pooling 错、前缀错、模型下错的那条 ——
因为那些错都会让中间两档塌到一起。

⚠️ **不钉绝对数值。** 「明显同义 > 0.7」这种判据在换模型那天会红,
而换模型本来就该让人重新看一遍这些数 —— 但那时候红的理由应该是
「层级塌了」而不是「0.69 没过 0.7」。绝对值只打印出来给人看。

## 这个文件要什么

onnxruntime + tokenizers + 96 MB 模型文件(`bash tools/fetch_model.sh`)。
所以它**在 `make test` 里跑,不进 CI 的 admin job** ——
那个 job 只装 sqlalchemy,而模型文件不进 git。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
知识 = os.path.join(ROOT, "services", "api", "app", "knowledge")
sys.path.insert(0, 知识)

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
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


try:
    import embedder_bge as B
except Exception as e:
    print(f"❌ import 不了 embedder_bge:{e}")
    sys.exit(1)

if not os.path.isfile(os.path.join(B.模型目录(), "onnx", "model.onnx")):
    print(f"❌ 模型文件不在 {B.模型目录()} —— 跑 `bash tools/fetch_model.sh`")
    print("   **这不叫跳过,叫没东西可测**")
    sys.exit(1)

print("▸ ① 形状与契约(和 mock 适配器同一个契约)")
r = B.算(["签收当场就请评价,不等回家"], 用途="文档")
ck(f"{B.维度} 维(config.json 的 hidden_size,不是猜的)",
   len(r[0]["向量"]) == B.维度, len(r[0]["向量"]))
ck("**`是mock` 是 False** —— 这个标记要跟着数据走到界面上",
   r[0]["是mock"] is False)
ck("带 `适配器版本`(换了实现要能从数据上看出来)",
   r[0]["适配器版本"] == B.适配器版本, B.适配器版本)
ck("归一化过(模长 1)", abs(sum(x * x for x in r[0]["向量"]) ** 0.5 - 1.0) < 1e-5)

print("\n▸ ② `用途` **必填,没有默认值**(BGE 非对称,搞错不报错)")
ck("不传 `用途` → TypeError(它是 keyword-only 必填)",
   _抛(lambda: B.算(["一段话"]), TypeError))
ck("`用途` 传别的 → 抛 `用途不对`",
   _抛(lambda: B.算(["一段话"], 用途="随便"), B.用途不对))
ck("文档和查询算出**不同**的向量(前缀真的加上了)",
   B.算(["同一段话"], 用途="文档")[0]["向量"]
   != B.算(["同一段话"], 用途="查询")[0]["向量"])
# ⚠️ text_hash 按原文算,不按加了前缀的那份 —— 否则同一段文本当文档和当查询
# 会算出两个哈希,而 `embeddings` 的唯一键 (text_hash, model_id) 就失去意义。
ck("**`text_hash` 两边一样**(按原文算,不按加前缀那份)——"
   "否则 embeddings 的唯一键会失去意义",
   B.算(["同一段话"], 用途="文档")[0]["text_hash"]
   == B.算(["同一段话"], 用途="查询")[0]["text_hash"])

print("\n▸ ③ **语义有效性:四档层级必须成立**(主判据)")
四档 = [
    ("完全相同", "差评要有人跟", "差评要有人跟"),
    ("明显同义", "客户给了差评", "顾客打了低分"),
    ("同主题不同事", "差评要有人跟", "签收时请顾客评价"),
    ("完全无关", "差评要有人跟", "香云纱不能高温熨烫"),
]
分们 = []
for 名, a, b in 四档:
    va = B.算([a], 用途="文档")[0]["向量"]
    vb = B.算([b], 用途="文档")[0]["向量"]
    s = B.余弦(va, vb)
    分们.append((名, s))
    print(f"     {名:12s} {s:.4f}   「{a}」vs「{b}」")
# ⚠️ **只钉顺序,不钉绝对值。** 绝对值在换模型那天会变,而那时候
# 该红的理由是「层级塌了」,不是「0.69 没过 0.7」。
单调 = all(分们[i][1] > 分们[i + 1][1] for i in range(len(分们) - 1))
ck("四档**严格递减**:相同 > 同义 > 同主题 > 无关 —— "
   "**pooling 错、前缀错、模型下错,都会让中间两档塌到一起**",
   单调, " > ".join(f"{s:.3f}" for _, s in 分们))
ck("完全相同的两段文本余弦 = 1(确定性)", abs(分们[0][1] - 1.0) < 1e-5)
ck("同义档和无关档**拉得开**(差 > 0.2 —— 这是个宽下限,不是精调的阈值)",
   分们[1][1] - 分们[3][1] > 0.2, f"{分们[1][1]:.4f} - {分们[3][1]:.4f}")

print("\n▸ ④ **CLS pooling 比 mean 好** —— 这一条证明 pooling 选对了")
# 直接跑两种 pooling 比一次。⚠️ 不是「CLS 能跑」,是「CLS 在同义档上更高」——
# 前者在用错的时候也成立。
import numpy as np                                    # noqa: E402
import onnxruntime as ort                             # noqa: E402
from tokenizers import Tokenizer                       # noqa: E402

_d = B.模型目录()
_s = ort.InferenceSession(os.path.join(_d, "onnx", "model.onnx"),
                          providers=["CPUExecutionProvider"])
_tk = Tokenizer.from_file(os.path.join(_d, "tokenizer.json"))
_tk.enable_truncation(max_length=512)


def _跑(ts, pool):
    es = _tk.encode_batch(ts)
    L = max(len(e.ids) for e in es)
    n = len(es)
    ids = np.zeros((n, L), np.int64)
    m = np.zeros((n, L), np.int64)
    t = np.zeros((n, L), np.int64)
    for i, e in enumerate(es):
        k = len(e.ids)
        ids[i, :k] = e.ids
        m[i, :k] = e.attention_mask
        t[i, :k] = e.type_ids
    o = _s.run(None, {"input_ids": ids, "attention_mask": m,
                      "token_type_ids": t})[0]
    if pool == "cls":
        v = o[:, 0, :]
    else:
        mm = m[:, :, None].astype(np.float32)
        v = (o * mm).sum(1) / np.maximum(mm.sum(1), 1e-9)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


同义 = ("客户给了差评", "顾客打了低分")
cls分 = float(np.dot(*_跑(list(同义), "cls")))
mean分 = float(np.dot(*_跑(list(同义), "mean")))
ck("同义档上 **CLS > mean**(BGE 官方用 CLS;用错是「能跑、数字正常、排序变差」)",
   cls分 > mean分, f"CLS {cls分:.4f} vs mean {mean分:.4f}")
ck("适配器真的用的是 CLS(拿它的输出和手算的 CLS 对上)",
   abs(B.余弦(B.算([同义[0]], 用途="文档")[0]["向量"],
              [float(x) for x in _跑([同义[0]], "cls")[0]]) - 1.0) < 1e-4)

print("\n▸ ⑤ 跨进程确定性(这些值要进数据库,库比解释器活得久)")
码 = (f"import sys; sys.path.insert(0, {知识!r})\n"
      "import embedder_bge as B\n"
      "v = B.算(['签收当场就请评价,不等回家'], 用途='文档')[0]['向量']\n"
      "print(v[0]); print(v[-1])\n")
p = subprocess.run([os.path.join(ROOT, ".venv", "bin", "python"), "-c", 码],
                   capture_output=True, text=True, timeout=180,
                   env={**os.environ, "PYTHONHASHSEED": "random"})
if p.returncode != 0:
    ck("另一个进程算出一样的向量", False, p.stderr.strip()[:130])
else:
    首, 末 = [float(x) for x in p.stdout.strip().split("\n")]
    ck("**另一个进程(PYTHONHASHSEED=random)算出一样的向量**",
       abs(首 - r[0]["向量"][0]) < 1e-6 and abs(末 - r[0]["向量"][-1]) < 1e-6,
       f"{首:.6f} / {末:.6f}")

print("\n▸ ⑥ 缺模型文件 → **当场抛,不静默退回 mock**")
# 退回 mock 会让一份随机相似度的检索结果看起来像真的 ——
# 而 mock 向量的相似度是个看起来很正常的数字(0.83),人会拿它当效果读。
_原目录 = os.environ.get("BGE_MODEL_DIR")
_原会话 = B._会话
try:
    os.environ["BGE_MODEL_DIR"] = "/tmp/根本没有这个目录"
    B._会话 = None
    ck("模型目录不存在 → 抛 `模型没就位`(**不返回 mock 向量**)",
       _抛(lambda: B.算(["一段话"], 用途="文档"), B.模型没就位))
finally:
    if _原目录 is None:
        os.environ.pop("BGE_MODEL_DIR", None)
    else:
        os.environ["BGE_MODEL_DIR"] = _原目录
    B._会话 = _原会话
ck("恢复之后还能跑(否则上面那条会污染后面)",
   len(B.算(["恢复检查"], 用途="文档")[0]["向量"]) == B.维度)

print("\n▸ ⑦ 进库的字面量不丢精度")
v = r[0]["向量"]
回 = [float(x) for x in B.成SQL文本(v).strip("[]").split(",")]
ck("`成SQL文本` → 解析回来**一个比特都不差**(repr,不截小数位)", 回 == v)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
