#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真 Embedding:BGE-small-zh-v1.5,onnxruntime 本机跑,离线。

## 为什么是本地模型

**Anthropic 和 DeepSeek 都不提供 embedding API**(2026-09-27 实测:
DeepSeek 的 `/models` 只有两个文本生成模型,`/embeddings` 返回 404)。
所以真向量只有两条路:本地模型,或者付费 API。
用户 2026-09-27 拍了本地(不花钱、离线、**知识库内容不出这台机器** ——
业务拍板记录里有「我摆过的代价」这类内部口径)。

用的是**原精度** `model.onnx`(96 MB),不是 int8 量化版(23 MB)——
用户原话:「如果都免费的话,就用好的,不要用压缩的了」。

## ⚠️ 两个搞错不报错的地方

### ① BGE 是**非对称**的:查询加前缀,文档不加

检索时查询端要加 `为这个句子生成表示以用于检索相关文章:`,文档端不加。
两边都加、或者都不加,**效果明显下降而不报任何错**。

所以 `用途` 是**必填参数,没有默认值** ——
搞错不报错的东西,不能靠调用者记得传对。

### ② BGE 用 **CLS pooling**,不是 mean pooling

取 `last_hidden_state[:, 0]`(第一个 token),不是对所有 token 取平均。
用错同样是「能跑、数字看着正常、排序变差」。

**这两条都有语义有效性判据在钉**(`tests/integration/test_embedder_bge.py`):
不是验形状对不对,是验**「客户不满意」和「≤3 星算差评」的余弦
明显高于它和「面料是香云纱」的余弦** —— pooling 错了或前缀错了,
那个差距会塌掉,而形状判据一条都不会红。

## 和 mock 适配器的关系

`embedder.py`(mock)**留着不动**,因为:
  · CI 的 admin job **只装 sqlalchemy** —— 那里跑不了 onnxruntime
  · 模型文件不进 git,一个新克隆在下载之前也得能跑测试

两者的输出**同一个契约**,唯一区别是 `是mock` 字段(§19.4 的做法:
一份 mock 跑出来的报告和真实报告在数据形状上一模一样,唯一区别就是那个字段)。

⚠️ **缺模型文件时当场抛,不静默退回 mock。**
退回 mock 会让一份随机相似度的检索结果**看起来像真的** ——
而 mock 向量算出的相似度是个看起来很正常的数字(0.83),人会拿它当效果读。
"""
import hashlib
import os
import threading

适配器版本 = "bge-small-zh-v1.5-onnx-fp32"
模型名 = "bge-small-zh-v1.5"
维度 = 512                      # config.json 的 hidden_size,不是猜的
最长token = 512                 # max_position_embeddings

# BGE 中文 v1.5 官方推荐的**查询端**前缀。文档端不加。
查询前缀 = "为这个句子生成表示以用于检索相关文章:"

_默认目录 = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))),
    ".models", 模型名)


class 模型没就位(Exception):
    """模型文件不在。**当场抛,不退回 mock。**"""


class 用途不对(Exception):
    """`用途` 不是「文档」或「查询」。**不给默认值** —— 见文件头 ①。"""


_锁 = threading.Lock()
_会话 = None
_分词器 = None


def 模型目录():
    return os.environ.get("BGE_MODEL_DIR") or _默认目录


def _确认文件都在():
    d = 模型目录()
    缺 = [f for f in ("onnx/model.onnx", "tokenizer.json", "config.json")
          if not os.path.isfile(os.path.join(d, f))]
    if 缺:
        raise 模型没就位(
            f"模型文件不全,缺 {缺}(找的是 {d})—— **跑 `bash tools/fetch_model.sh`**。\n"
            f"       这里**不退回 mock**:mock 向量算出的相似度是个看起来很正常的数字,"
            f"人会拿它当效果读")


def _起来():
    """懒加载。第一次约一秒(读 96 MB 权重),之后常驻。"""
    global _会话, _分词器
    if _会话 is not None:
        return _会话, _分词器
    with _锁:
        if _会话 is not None:
            return _会话, _分词器
        _确认文件都在()
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as e:
            raise 模型没就位(
                f"缺 {e.name} —— `pip install onnxruntime tokenizers`。\n"
                f"       ⚠️ CI 的 admin job **故意不装它们**(只装 sqlalchemy),"
                f"那里用 `embedder.py` 的 mock") from e
        d = 模型目录()
        _会话 = ort.InferenceSession(os.path.join(d, "onnx", "model.onnx"),
                                    providers=["CPUExecutionProvider"])
        出 = _会话.get_outputs()[0]
        真维度 = 出.shape[-1]
        if 真维度 != 维度:
            # 模型换了而常量没跟上 —— **当场报**。
            # 不报的话,向量会以另一个维度写进 vector(512) 列,
            # 被 PostgreSQL 拒(实测 `expected 512 dimensions, not N`),
            # 而那时错误信息里只有维度,没有「是哪个模型」。
            raise 模型没就位(
                f"模型输出 {真维度} 维,而这个适配器声明 {维度} 维 —— "
                f"换模型要连 `维度` 常量和 `embeddings.embedding` 列一起改")
        _分词器 = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
        _分词器.enable_truncation(max_length=最长token)
        return _会话, _分词器


def 算(文本们, *, 用途, 模型id=模型名, 期望维度=维度):
    """给一批文本算向量。返回和入参**等长**的清单。

    `用途` **必填**:"文档" 或 "查询"。见文件头 ① ——
    BGE 是非对称的,查询加前缀、文档不加,而搞错**不报错**。

    每一项:{text_hash, 向量, 维度, 模型id, 是mock=False, 适配器版本}
    —— 和 `embedder.py`(mock)同一个契约。
    """
    if 用途 not in ("文档", "查询"):
        raise 用途不对(
            f"`用途` 要是「文档」或「查询」,给的是 {用途!r} —— **不给默认值**:"
            f"BGE 是非对称模型(查询加前缀、文档不加),"
            f"搞错**效果明显下降而不报任何错**")
    if 期望维度 != 维度:
        raise 模型没就位(
            f"要 {期望维度} 维,而这个模型只产 {维度} 维 —— "
            f"**不许截断也不许补零**:截断丢信息,补零造假信息,"
            f"两种都会让检索算出一个看起来正常的错数字")
    if not 文本们:
        return []

    会话, 分词 = _起来()
    import numpy as np

    原文们 = list(文本们)
    for t in 原文们:
        if not isinstance(t, str) or not t.strip():
            raise ValueError("要 Embedding 的文本是空的 —— 空片段不该走到这一步,"
                             "它在切片阶段就该被丢掉并计数")
    喂进去的 = [(查询前缀 + t) if 用途 == "查询" else t for t in 原文们]

    编码们 = 分词.encode_batch(喂进去的)
    最长 = max(len(e.ids) for e in 编码们)
    n = len(编码们)
    ids = np.zeros((n, 最长), dtype=np.int64)
    掩码 = np.zeros((n, 最长), dtype=np.int64)
    类型 = np.zeros((n, 最长), dtype=np.int64)
    for i, e in enumerate(编码们):
        L = len(e.ids)
        ids[i, :L] = e.ids
        掩码[i, :L] = e.attention_mask
        类型[i, :L] = e.type_ids

    出 = 会话.run(None, {"input_ids": ids, "attention_mask": 掩码,
                        "token_type_ids": 类型})[0]
    # ⚠️ **CLS pooling** —— 取第一个 token,不是 mean。见文件头 ②。
    cls = 出[:, 0, :]
    模 = np.linalg.norm(cls, axis=1, keepdims=True)
    if not np.all(模 > 0):
        raise 模型没就位("算出了零向量 —— 余弦会变成 0/0,"
                       "而**排序里的 NaN 不报错,只是排到某个位置**")
    单位 = cls / 模

    结果 = []
    for t, v in zip(原文们, 单位):
        # ⚠️ `text_hash` 按**原文**算,不按加了前缀的那份 ——
        # 否则同一段文本当文档和当查询会算出两个哈希,
        # 而 `embeddings` 的唯一键 (text_hash, model_id) 就失去意义了。
        结果.append(dict(
            text_hash=hashlib.sha256(t.encode("utf-8")).hexdigest(),
            向量=[float(x) for x in v], 维度=维度, 模型id=模型id,
            是mock=False, 适配器版本=适配器版本, 用途=用途))
    return 结果


def 成SQL文本(向量):
    """pgvector 的字面量。**用 repr,不截小数位** ——
    截到固定位数会让两个不同向量变成同一个字符串。"""
    return "[" + ",".join(repr(float(x)) for x in 向量) + "]"


def 余弦(a, b):
    """给测试用。⚠️ **不是检索用的那个算子** ——
    库里走 pgvector 的 `<=>`,浮点细节不完全一致。
    要断言排序就在库里查,别在 Python 里重算。"""
    if len(a) != len(b):
        raise 模型没就位(f"{len(a)} 维和 {len(b)} 维算不了余弦")
    return sum(x * y for x, y in zip(a, b))
