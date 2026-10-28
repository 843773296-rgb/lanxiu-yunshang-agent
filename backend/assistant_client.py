# -*- coding: utf-8 -*-
"""聊天站问管理后台:**这个角色助手现在该用哪一版配置**(用户 2026-10-28 拍「聊天助手配置页分两步」,这是第 2 步)。

后台那一版只管四样:开头 / 结尾 / 开着哪些工具 / 默认模型。**规矩照旧由 prompts.assemble 按这一轮开着的工具挑**,
技能被调起时另带它自己的规矩 —— 都不在后台那一版里。

## 拉不到的时候怎么办(照 takeover_client 同一套)

  · 没配地址 / 后台没指定生产 → **用代码里那一份**(和今天一模一样)
  · 拉不到(后台停了、抖了)→ 用**最后一次拉成功的**(落盘);从没拉成功过 → 代码里那一份
    不一失败就退回代码:生产切到 v3 之后后台抖一下,聊天站不该悄悄换回另一份提示词
  · 指针指着一个不在了的版本(409)→ 同「拉不到」,并把原因带出去

## 工具只能收、不能加

后台开着的工具和这一轮名单取交集。名单外的名字一律忽略 —— 后台加不出聊天站这个角色没挂的工具,
**写闸 / 身份 / 白名单都还在 sdk 那一层**,这里只决定「少给几个」。

## 每一轮记什么(核对口,和并行会话 10-28 定的)

`记账()` 给出:提示词版本(后台 vN / 代码)· 模型 · 工具指纹 · 来源(后台现拉 / 落盘 / 代码)·
这份配置是哪一刻拉到的 · (技能调起由 sdk 那边按这一轮真调的补)。
「哪一刻拉到的」是因为有 30 秒缓存 —— 没有它,「后台出了新版、这一轮用的还是缓存那版」看不出来。
"""
import hashlib
import json
import os
import time

import takeover_client as _tc      # 地址 / 项目 / 账号和 curl 那一处共用 —— 两份配置会在某天各指一个后台

_缓存秒 = 30
_落盘目录 = os.path.dirname(os.path.abspath(__file__))
_内存 = {}       # 角色 → {"at": 拉的时刻(秒), "版": dict 或 None, "来源": str, "拉到于": str, "原因": str}


def _落盘(角色):
    return os.path.join(_落盘目录, f".assistant_{角色}_last.json")


def 指纹(工具):
    return "sha256:" + hashlib.sha256(json.dumps(sorted(工具), ensure_ascii=False).encode()).hexdigest()[:16]


def 生产版(角色, 强制=False):
    """→ {"版": 后台那一版(dict)或 None, "来源": 后台现拉 / 落盘 / 代码, "拉到于": 时刻, "原因": 为什么是这个来源}。
    「版」为 None = 用代码里那一份。"""
    旧 = _内存.get(角色)
    if not 强制 and 旧 and time.time() - 旧["at"] < _缓存秒:
        return 旧
    cfg = _tc.配置()
    出 = None
    if not cfg:
        出 = {"版": None, "来源": "代码", "拉到于": None, "原因": "没配管理后台地址"}
    else:
        码, 体 = _tc._curl("GET", f"/chat-assistants/by-role/{角色}/production", cfg)
        现在 = time.strftime("%Y-%m-%d %H:%M:%S")
        if 码 == "200" and isinstance(体, dict):
            版 = 体 if 体.get("版本号") is not None else None
            出 = {"版": 版, "来源": "后台现拉", "拉到于": 现在,
                  "原因": None if 版 else "后台没指定生产,用代码里那一份"}
            try:
                with open(_落盘(角色), "w", encoding="utf-8") as f:
                    json.dump({"拉到于": 现在, "版": 版}, f, ensure_ascii=False)
            except OSError:
                pass
        elif 码 == "404":
            # 后台里没这个角色 = 没人在后台管它,和「没指定生产」一样用代码 —— 不是故障
            出 = {"版": None, "来源": "后台现拉", "拉到于": 现在, "原因": "后台没有这个角色"}
        else:
            原因 = (体.get("message") if isinstance(体, dict) else 体) or f"HTTP {码}"
            try:
                with open(_落盘(角色), encoding="utf-8") as f:
                    盘 = json.load(f)
                出 = {"版": 盘.get("版"), "来源": "落盘", "拉到于": 盘.get("拉到于"), "原因": f"拉不到:{原因}"}
            except (OSError, ValueError):
                出 = {"版": None, "来源": "代码", "拉到于": None, "原因": f"拉不到且从没拉成功过:{原因}"}
    出["at"] = time.time()
    _内存[角色] = 出
    return 出


def 收工具(本轮, 版):
    """本轮名单 ∩ 后台开着的。**只收不加**:后台那一版里有、名单里没有的,忽略。"""
    if not 版:
        return list(本轮)
    开 = set(版.get("工具") or [])
    return [t for t in 本轮 if t in 开]


def 记账(取, 工具, 模型):
    """每一轮进轨迹的那几样(技能调起由 sdk 按真调的补)。"""
    版 = 取.get("版")
    return {"提示词版本": f"后台 v{版['版本号']}" if 版 else "代码", "模型": 模型, "工具指纹": 指纹(工具),
            "工具数": len(工具), "来源": 取.get("来源"), "拉到于": 取.get("拉到于"), "原因": 取.get("原因")}
