# -*- coding: utf-8 -*-
"""模型连接的闸(规格 §17.4-5)。纯逻辑,不碰库、不碰 HTTP。

## 三句写在契约里的话,这个模块就是它们的兑现

**① 「密钥只收 `secret_ref`,不收明文」**

契约原话:**「明文一旦进过请求体,它就已经进过日志、进过 APM、可能进过错误上报」。**

所以不能「收下但忽略明文」—— 那样明文照样走完了整条请求链。**必须当场拒**。
而且拒的时候**不许把那个值回显在错误里**,否则错误信息自己成了泄漏通道
(`errors.泄密检查` 守的正是这件事)。

⚠️ 判据**复用 `errors._密钥形状`**,不抄第二份 —— 那个正则是「像凭据的**字段名**」,
这个仓库已经为它维护过一轮。抄一份出来,两边早晚各自演化。

**② 「`config_hash` 不含 `secret_ref` 指向的内容」**

两个理由,第二个更要紧:
  · 换了密钥**不算**换了配置(轮换密钥不该让所有清单失效)
  · 把密钥混进哈希,**哈希本身就变成一条侧信道** ——
    同一个密钥永远得到同一个哈希,而哈希是到处都能看到的

**③ 「探测要落 capabilities」**

契约原话:**「不探就默认全支持,会在真跑时变成一个说不清的 400」**。

「默认全支持」这种乐观假设的坏处不是它错,是**它错的时候不在这里报** ——
报在几天后某一次真实调用上,而那时候没人会想到是连接配置的问题。
所以「探过没有」要在列表上看得见,而且**发到生产的清单要求它探过**。

## ⚠️ 用途不共用一条连接

生成 / Embedding / 重排 / 微调推理 各要一条。共用的坏处很具体:
换生成模型的时候会**顺手把 Embedding 也换掉**,而 Embedding 一换,
已经建好的索引全部不可比 —— 而那件事不报错,只是检索开始变差。
"""
import hashlib
import json as _json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
import errors as ER

用途们 = ("generate", "embed", "rerank", "finetune_infer")
用途中文 = {"generate": "生成", "embed": "Embedding",
          "rerank": "重排", "finetune_infer": "微调推理"}

# `secret_ref` 必须长成一个**定位符**,而不是一个密钥本身。
# 形如 `keychain://xxx` / `env://XXX` / `vault://path` / `ref:xxx`。
# 一个裸的供应商密钥不会有这种前缀 —— 所以这条既能拦「填错了」,
# 也能拦「把明文塞进了 secret_ref 这个字段名下」。
import re
_定位符 = re.compile(r"^(?:[a-z][a-z0-9+.\-]*://\S+|ref:\S+)$")


def 像明文密钥吗(体):
    """请求体里有没有像明文凭据的字段。返回**位置**清单。

    ⚠️ **既不返回值,也不返回字段名。**

    不返回值的理由很直白:返回了,调用方的错误提示、日志、错误上报又各存一份,
    而这个函数存在的全部理由就是防这件事。

    不返回**名字**的理由是踩出来的:第一版返回名字(`api_key` 这种),
    于是错误体里出现了凭据类词,**`errors.泄密检查` 当场把整个响应判成泄漏 → 500**。
    ⚠️ 今天这是第二次:上一次是错误信息里写了那个词的英文,也被判成凭据。
    > **一道防泄漏的检查,会拦住「谈论泄漏」的那句话** —— 而两者它分不出来。

    位置对调用方够用了:**那个请求体是他自己写的**,
    「顶层第 3 个字段的名字像凭据」他一眼就知道说的是哪个。
    """
    坏 = []

    def 走(前缀, v):
        if isinstance(v, dict):
            for 序, (k, x) in enumerate(v.items(), 1):
                路 = f"{前缀}.第{序}项" if 前缀 else f"顶层第{序}个字段"
                if ER._密钥形状.search(str(k)) and str(k) != "secret_ref":
                    if x not in (None, "", [], {}):
                        坏.append(路)
                走(路, x)
        elif isinstance(v, list):
            for i, x in enumerate(v, 1):
                走(f"{前缀}[第{i}项]", x)

    走("", 体 or {})
    return sorted(set(坏))


def 检查密钥引用(secret_ref):
    """`secret_ref` 得是个**定位符**,不是密钥本身。返回问题(None = 可以)。"""
    s = (secret_ref or "").strip()
    if not s:
        return ("**密钥引用字段必填** —— 一条连不上的连接和一条没配过密钥的连接,"
                "在真跑时都表现成「调不通」,而两者下一步完全不同")
    if not _定位符.fullmatch(s):
        # ⚠️ **不回显它的值。** 只说形状。
        # ⚠️ 这句话里**不写那个字段名的英文** —— 写了会被 `errors.泄密检查`
        # 判成「错误体里带了凭据」,整个响应变 500(今天第二次)。
        return (f"**密钥引用字段不像一个定位符**(拿到 {len(s)} 个字符)—— "
                f"要形如 `keychain://…` / `env://…` / `vault://…` / `ref:…`。"
                f"**这个字段只放引用,不放密钥本身**:明文一旦进过请求体,"
                f"它就已经进过日志、进过 APM、可能进过错误上报")
    return None


def 配置哈希(*, 用途, 适配器, endpoint, capabilities):
    """配置的内容哈希。**刻意不含 `secret_ref`。**

    两个理由,第二个更要紧:
      · 换了密钥**不算**换了配置 —— 轮换密钥不该让所有发布清单失效
      · 把密钥混进哈希,**哈希本身就成了一条侧信道**:
        同一个密钥永远得到同一个哈希,而哈希是到处都能看到的
    """
    料 = {"用途": 用途, "适配器": 适配器, "endpoint": endpoint,
         "capabilities": capabilities}
    return hashlib.sha256(_json.dumps(料, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]


def 可以建吗(*, 用途, 适配器, endpoint, secret_ref, 体, 已有用途们=()):
    """能不能建这条连接。返回问题清单(空 = 可以)。"""
    问 = []
    明文 = 像明文密钥吗(体)
    if 明文:
        # 放在最前面报:它是唯一一个「已经出事了」的问题,其余都只是填错。
        问.append(f"请求体里有**名字像凭据、而且给了值**的字段:{明文} —— "
                  f"这里**只收引用**。明文一旦进过请求体,它就已经进过日志、"
                  f"进过 APM、可能进过错误上报;换个字段名重发也救不回来那一次")
    if 用途 not in 用途们:
        问.append(f"用途只收 {list(用途们)}(即 {list(用途中文.values())}),拿到 {用途!r}")
    if not (适配器 or "").strip():
        问.append("适配器必填(例:`MockModelProvider`)")
    if not (endpoint or "").strip():
        问.append("endpoint 必填")
    坏引用 = 检查密钥引用(secret_ref)
    if 坏引用:
        问.append(坏引用)
    return 问


def 探过吗(连接版本):
    """这条连接版本探过 capabilities 没有。

    ⚠️ **None / 空字典都算「没探过」。** 不探就默认全支持,
    而那个乐观假设错的时候**不在这里报** —— 报在几天后某次真实调用上。
    """
    if not 连接版本:
        return False
    c = 连接版本.get("capabilities")
    if isinstance(c, str):
        try:
            c = _json.loads(c)
        except Exception:
            return False
    return bool(c)
