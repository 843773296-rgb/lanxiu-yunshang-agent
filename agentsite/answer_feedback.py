# -*- coding: utf-8 -*-
"""每条回答下都能提意见(DF-03 第 2 步,2026-11-04;Dify 对标方案 C13)。

口径照《意见收集与能力持续改进 PRD》(10-24)§3:入口是「有帮助」和「反馈问题」(纠正内容 / 建议共用一个面板),
执行失败的那一轮也能「报告执行问题」;字段 = 反馈类型 / 哪里有问题 / 期望的结果 / 影响。

## 为什么要在聊天站转一道

管理后台那张「回答反馈」表要记**提问的那个人**。而「这个人是谁」只有聊天站知道得确切:
它从登录 cookie 换出身份(后台 /api/me),也记着每一轮是谁问的(sessions.记这一轮,成败都记)。
所以这里做两件事,再把结果交给管理后台:
  ① **只认这一轮的提问人** —— 别人的回答你评不了(哪怕是店长看顾问的);
     查不到会话归属就拒,不猜(评测、试跑那种不经聊天页的运行没有归属)
  ② 转给管理后台时带**提问人的工号 / 姓名 / 角色 / 门店**,外加内部凭证 ——
     管理后台只在凭证核得上时才采信请求体里的提问人。

⚠️ 和旁边那条检索评分(`_评一次检索`)不同:那条以服务账号 U001 打分、不记是谁评的。这里不学它。
"""
import json
import os
import subprocess

import internal_call as _ic

后台基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
后台项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
服务账号 = os.environ.get("AIMC_USER", "U001")
# 和管理后台、聊天页那两份同一组(answer_feedback_check ⑥ 盯着);口径见 PRD §3.2
问题类型们 = ("答错", "没答全", "证据不支持", "查错对象", "太慢或失败", "不好操作", "新增能力", "其他")
影响们 = ("仅影响本次", "反复出现", "影响业务办理")
页面能给的 = ("来源", "评价", "问题类型", "说明", "期望结果", "影响")   # 只收这几样;**提问人不在里面**


def 能评吗(me, trace, 提问人):
    """→ (行不行, HTTP 码, 为什么)。纯函数:answer_feedback_check 真调它。
    me = 登录身份;提问人 = sessions.这一轮是谁的(trace, 会话号)(先认这一轮自己的记录,再退回认会话主人)。"""
    if not (me or {}).get("no"):
        return False, 401, "没登录 —— 反馈要记是谁提的"
    if not trace:
        return False, 400, "没有 trace —— 这一轮没记执行记录,没法挂反馈"
    if not 提问人:
        return False, 404, "这一轮查不到是谁问的(评测 / 试跑,或服务重启前的会话)—— 查不到就拒,不猜"
    if str(提问人.get("no")) != str(me["no"]):
        # 404 不说「有这一轮但不是你的」—— 那句话本身就是信息
        return False, 404, "这一轮不是你问的 —— 只有提问的人能评这条回答"
    return True, 200, ""


def 载荷(me, trace, 会话号, 页面):
    """转给管理后台的请求体。页面传来的只取 `页面能给的` 那几样;**提问人只从登录身份取**,
    页面里就算写了「提问人」「工号」也一个字不带过去。字段对不对由管理后台那一处判(不在这里判第二遍)。"""
    页面 = 页面 if isinstance(页面, dict) else {}
    体 = {k: 页面.get(k) for k in 页面能给的 if 页面.get(k) not in (None, "")}
    for k in ("说明", "期望结果"):
        if isinstance(体.get(k), str):
            体[k] = 体[k].strip() or None
    体.update({"聊天站trace": trace, "会话号": 会话号,
              "提问人": {"工号": me.get("no"), "姓名": me.get("name"), "角色": me.get("role"), "门店": me.get("shop")}})
    return 体


def 独立建议载荷(me, 页面):
    """导航「意见与建议」那张表(不挂任何一轮,PRD §3.1)。和 载荷 同一条规矩:提问人只从登录身份取。"""
    体 = 载荷(me, None, None, {**(页面 if isinstance(页面, dict) else {}), "来源": "独立建议", "评价": "建议"})
    体.pop("聊天站trace", None)
    体.pop("会话号", None)
    return 体


def 提交键(页面):
    """页面每次点「提交」生成一个;网断了重试带同一个 → 管理后台只记一条。只收短的可见字符,别的一律当没给(由后台拒)。"""
    k = str((页面 or {}).get("提交键") or "").strip()
    return k if 0 < len(k) <= 64 and k.isprintable() and " " not in k else None


def _curl(方法, url, 体=None, 头=(), 凭证=None):
    凭 = 凭证 if 凭证 is not None else _ic.读凭证()
    if not 凭:
        return None, {"error": "内部通道没开:本机没有凭证文件(~/.lanxiu/internal-call)",
                      "怎么办": "这条意见记不下来 —— 管理后台只认内部通道转来的提问人"}
    参 = ["curl", "-sS", "-m", "20", "-o", "-", "-w", "\n%{http_code}", "-X", 方法, url,
         "-H", f"X-Dev-User: {服务账号}", "-H", f"{_ic.凭证头}: {凭}"]
    for h in 头:
        参 += ["-H", h]
    if 体 is not None:
        参 += ["-H", "content-type: application/json", "--data-binary", "@-"]
    try:
        p = subprocess.run(参, input=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None,
                           capture_output=True, timeout=30)
    except Exception as e:
        return None, {"error": f"连不上管理后台({type(e).__name__})", "怎么办": "管理后台没起的话,这条意见记不下来"}
    正文, _, 码 = p.stdout.decode("utf-8", "replace").rpartition("\n")
    try:
        码 = int(码)
    except ValueError:
        return None, {"error": f"连不上管理后台({后台基址})", "怎么办": (p.stderr.decode()[:160] or "过一会儿再试")}
    try:
        d = json.loads(正文 or "null") or {}
    except Exception:
        d = {"error": 正文[:160]}
    return 码, d


def 查我的(me, 页=1, 凭证=None):
    """「我的意见」:工号只从登录身份取。"""
    # ⚠️ 参数名「工号」是中文,**整条 query 要编码** —— 裸中文进 URL,后台 uvicorn 直接回「Invalid HTTP request」
    # (11-04 第一版就这么坏的;只编码了值、没编码名字)
    from urllib.parse import urlencode
    return _curl("GET", f"{后台基址}/api/v1/projects/{后台项目}/opinions/mine?" + urlencode({"工号": str(me.get("no")), "page": int(页)}),
                 凭证=凭证)


def 转给后台(体, 凭证=None, 键=None):
    """→ (http 码 或 None, dict)。走 curl:这台机器 Python 的 TLS 会被拦,本地 http 也统一走一处(同 open_api)。
    凭证只进 curl 的参数,不进日志。失败**照实说**,不装作成功。"""
    return _curl("POST", f"{后台基址}/api/v1/projects/{后台项目}/opinions", 体,
                 头=([f"Idempotency-Key: {键}"] if 键 else []), 凭证=凭证)


# ── 店长复核样本(用户 11-04 拍「总部运营提、店长复核」「店长在聊天站里复核」)──
# 复核人是谁、是不是店长、哪家门店,**只从登录会话取**;管理后台那边再用同一个判定(opinions_api.能复核吗)核一遍。
def 复核人(me):
    return {"工号": (me or {}).get("no"), "姓名": (me or {}).get("name"), "角色": (me or {}).get("role"),
            "门店": (me or {}).get("shop")}


def 查待我复核(me, 凭证=None):
    from urllib.parse import urlencode
    人 = 复核人(me)
    return _curl("GET", f"{后台基址}/api/v1/projects/{后台项目}/opinion-samples/pending?"
                 + urlencode({"工号": str(人["工号"] or ""), "角色": 人["角色"] or "", "门店": 人["门店"] or ""}), 凭证=凭证)


def 复核(me, 样本, 页面, 凭证=None):
    """页面只给 决定 / 理由 / revision;复核人从登录身份取。样本号只收短的可见字符(它进 URL)。"""
    页面 = 页面 if isinstance(页面, dict) else {}
    样本 = str(样本 or "")
    if not (0 < len(样本) <= 64 and 样本.replace("_", "").isalnum() and 样本.isascii()):
        return None, {"error": "样本号不对", "怎么办": "回「待我复核」重新点"}
    体 = {"决定": 页面.get("决定"), "理由": (str(页面.get("理由") or "").strip() or None), "revision": 页面.get("revision"),
         "复核人": 复核人(me)}
    return _curl("POST", f"{后台基址}/api/v1/projects/{后台项目}/opinion-samples/{样本}/review", 体, 凭证=凭证)
