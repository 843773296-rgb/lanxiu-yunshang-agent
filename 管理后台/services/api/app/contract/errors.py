#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一错误结构(规格 §19.1)。

失败返回必须包含:code、message、field_errors、retryable、trace_id、**可执行建议**。

## 为什么「可执行建议」是必填

一个只说「请求失败」的错误,和没有错误提示,对使用的人是一样的 ——
他下一步不知道该干什么,于是会去重试、去改 ID、去问人。

## 为什么 retryable 必须显式

「能不能重试」由服务端知道,客户端猜不出来。猜错的两个方向代价都很大:
不该重试的重试了(重复计费 / 重复训练),该重试的没重试(任务白丢)。
"""
import re

# HTTP 语义(§19.1 最后一条)
状态语义 = {
    401: "未认证",
    403: "无权",
    404: "不存在,或按策略隐藏存在性",
    409: "冲突(版本被人改过 / 幂等键同键不同请求)",
    422: "输入无效",
    429: "限额",
    500: "服务问题",
}

# ⚠️ **不能把原始供应商密钥写入错误**(§19.1)。
# 这里不写出真实的密钥匹配串 —— 只描述形状,否则这个文件自己会被密钥扫描器命中。
_密钥形状 = re.compile(
    r"(secret|token|api[_-]?key|apikey|authorization|bearer|password|passwd|"
    r"credential|private[_-]?key)", re.I)


def 错(code, message, 建议, http=422, field_errors=None, retryable=False,
       trace_id=None):
    """造一个符合契约的错误体。

    `建议` 是**必填**:调用方下一步该干什么。写不出建议的错误,
    说明还没搞清失败原因 —— 那就先去搞清楚,不要发一个「请稍后再试」出去。
    """
    if not (建议 or "").strip():
        raise ValueError(
            f"错误 {code} 没写「可执行建议」—— 规格 §19.1 要求必填。"
            f"一个只说「失败了」的错误,和没有提示是一回事")
    if http not in 状态语义:
        raise ValueError(f"用了契约外的状态码 {http} —— 现有 {sorted(状态语义)}")
    体 = dict(code=code, message=message, field_errors=field_errors or {},
              retryable=bool(retryable), trace_id=trace_id, advice=建议)
    坏 = 泄密检查(体)
    if 坏:
        raise ValueError(f"错误体里可能带了凭据:{坏} —— **不能把供应商密钥写进错误**")
    return 体


def 泄密检查(体):
    """扫**键名和值**里有没有像凭据的东西。返回命中的位置。

    ⚠️ 这里和别处不一样:**值也要扫**。
    错误 message 常常是把上游返回原样带回来的,而上游 401 的响应体里
    很可能就带着被拒的那个凭据 —— 这正是错误信息成为泄露通道的典型路径。
    """
    坏 = []
    def 走(前缀, v):
        if isinstance(v, dict):
            for k, x in v.items():
                if _密钥形状.search(str(k)): 坏.append(f"{前缀}{k}(键名)")
                走(f"{前缀}{k}.", x)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v): 走(f"{前缀}[{i}].", x)
        elif isinstance(v, str) and _密钥形状.search(v):
            坏.append(f"{前缀}(值里出现了凭据类词)")
    走("", 体)
    return 坏
