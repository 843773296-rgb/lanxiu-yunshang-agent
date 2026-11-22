# -*- coding: utf-8 -*-
"""标注回复 · 聊天站这一半(11-22;后台一半 11-21,用户 10-27 拍第 7 条:「标注回复让 Claude 判相似」)。

管理后台的「标注回复」总开关开着时,聊天站对每个新问题先做一件事:拉「启用中的标注清单」(缓存一分钟),
让模型判「这句话和清单里哪一条是**同一个意思**」(多一次很小的调用),命中就**直接回那条标准答案**、不再调工具不再跑助手,
并向后台报一次命中(hit_count);没命中照旧走原来的路。
## 边界
- 实时数据的问题(查订单 / 库存 / 客户…)**在标注那一步就被后台拦住了**(按那一轮调过的工具判),清单里没有它们 —— 这里不再判一遍。
- 判同义的是模型,会错:提示词要求「不确定就答 0」;命中回答里标明「这是标注答案」,店员看得出来、能评「不好」。
- 开关关着 / 清单空 / 后台连不上 / 模型调用失败 → 一律当没命中,**走原路**;这一层出任何错都不许让回答失败。
- 判同义那一次调用走 agent/v1.call(记录仪包着,purpose=标注匹配),花费另记;命中那一轮本身零花费。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
服务身份 = os.environ.get("AIMC_USER", "U001")
缓存秒 = 60
最多候选 = 40
_缓存 = {"at": 0.0, "开关": False, "items": []}


def _调(方法, 路径, 体=None, timeout=8):
    h = {"X-Dev-User": 服务身份}
    data = None
    if 体 is not None:
        data = json.dumps(体, ensure_ascii=False).encode()
        h["content-type"] = "application/json"
    q = urllib.request.Request(f"{基址}/api/v1/projects/{项目}{路径}", data=data, method=方法, headers=h)
    try:
        with urllib.request.urlopen(q, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"_异常": type(e).__name__}


def 清单(强制=False, 现在=None):
    """启用中的标注(全文)。缓存一分钟:每个问题都去问后台一次太频;一分钟内新标的那条下一分钟生效,可接受。"""
    现在 = 现在 if 现在 is not None else time.time()
    if not 强制 and 现在 - _缓存["at"] < 缓存秒:
        return _缓存["开关"], _缓存["items"]
    码, d = _调("GET", "/chat-annotations/active")
    if 码 != 200 or not isinstance(d, dict):
        # 拉不到 → 保留上一份(后台短暂不可用不该让标注忽开忽关);从没拉到过就当关着
        _缓存["at"] = 现在
        return _缓存["开关"], _缓存["items"]
    _缓存.update(at=现在, 开关=bool(d.get("开关")), items=list(d.get("items") or []))
    return _缓存["开关"], _缓存["items"]


def 候选(items, 角色名=None):
    """按角色筛:标注记的是那一轮的角色(门店顾问 / 澜绣云裳助手…);没记角色的对所有角色都算候选。最多 最多候选 条(清单大了先截,别让提示词无限长)。"""
    出 = [x for x in items if x.get("question") and x.get("standard_answer") and (not 角色名 or not x.get("assistant_role") or x["assistant_role"] == 角色名)]
    return 出[:最多候选]


def _提示(问题, 候选们):
    行 = "\n".join(f"{i + 1}. {str(x['question']).strip()[:200]}" for i, x in enumerate(候选们))
    return ("下面是门店店员以前问过、并被标注过标准答案的问题清单。判断「新问题」和清单里哪一条问的是**同一个意思**"
            "(同一件事、同一个对象、同一种答法能直接套用)。措辞不同不要紧,但对象不同、要的不是同一类信息、带着具体单号 / 客户 / 日期要查实时数据的,都不算同义。"
            "**不确定就答 0。**只输出 JSON:{\"命中\": <清单序号或 0>}\n\n"
            f"清单:\n{行}\n\n新问题:{问题.strip()[:500]}")


def 解析命中(文本, n):
    """模型回的文本 → 序号(1..n)或 None。只认 JSON 里的 命中,认不出 / 越界 / 0 → None。"""
    m = re.search(r'"命中"\s*:\s*(\d+)', 文本 or "")
    if not m:
        return None
    k = int(m.group(1))
    return k if 1 <= k <= n else None


def 问模型同义(问题, 候选们, 调=None):
    """→ 命中的那条标注 或 None。`调` 可注入(检查用);真跑走 agent/v1.call(记录仪包着)。任何异常 → None。"""
    if not 候选们:
        return None
    try:
        if 调 is None:
            import v1
            pv = v1.provider()
            def 调(body):  # noqa: E306
                resp = v1.call(pv, body, retries=2, purpose="标注匹配", gen="V3")
                return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            model = pv.get("model")
        else:
            model = "注入"
        文本 = 调({"model": model, "max_tokens": 40, "system": "你只输出 JSON,不解释。",
                 "messages": [{"role": "user", "content": _提示(问题, 候选们)}]})
    except BaseException:  # noqa: BLE001 —— provider() 没凭证会 sys.exit;这一层出任何错都走原路
        return None
    k = 解析命中(文本, len(候选们))
    return 候选们[k - 1] if k else None


def 试命中(问题, 角色名=None, 调=None, 现在=None):
    """聊天站 /run 每个新问题先过这里:开关开着且有候选才问模型;→ 命中的标注 或 None。"""
    try:
        开, items = 清单(现在=现在)
    except Exception:  # noqa: BLE001
        return None
    if not 开 or not items:
        return None
    return 问模型同义(问题, 候选(items, 角色名), 调=调)


def 命中回答(标注, 问题, 会话=None):
    """照 /run 返回体的形状拼一份:text 是标准答案原文(**逐字,不加工**),零花费,trace 没有(没跑助手),标明来源。"""
    return {"text": 标注["standard_answer"], "session_id": 会话, "trace_id": None, "cost_usd": 0.0, "model": "标注回复",
            "标注命中": {"id": 标注.get("id"), "标注的问题": 标注.get("question"), "角色": 标注.get("assistant_role")},
            "路由": {"分流": False, "答的": "标注回复", "默认来由": "命中管理后台标注的标准答案,没调模型没调工具"},
            "说明": "这条是管理后台标注过的标准答案(和你问的是同一个意思)。觉得不对请点「不好」,管理员会在后台改。"}


def 报命中(标注id, trace_id=None):
    """命中后告诉后台一声(hit_count + 1)。失败不抛 —— 计数少一次不该让回答失败。"""
    try:
        码, d = _调("POST", f"/chat-annotations/{quote(str(标注id))}/hits", {"trace_id": trace_id}, timeout=5)
        return 码 == 200
    except Exception:  # noqa: BLE001
        return False
