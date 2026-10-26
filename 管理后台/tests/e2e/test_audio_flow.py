#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频整理全流程 · 端到端(2026-10-24,用户拍「页面结构加上音频整理全流程全部做完」+「核对即定稿,直接写跟进」)。

真服务 + 真 Worker + 真库,模型是 mock(不花钱;mock 也按结果字段出形状,值里带 [mock])。
澜绣那一侧用**测试自己扮演**:拉待执行的桥请求、回执 —— 真的 supervise_sync 那半有自己的检查。

  ① 建「音频整理」模板 → 补模型和处理要求 → 校验通过
  ② 试运行 → 停在「取转写」等澜绣回执(waiting_external),桥上有一张待执行的单
  ③ 回执转写 → 运行接着走,停在「人工核对」(waiting_approval),待办里看得到摘要和原文
  ④ 批准(改了定稿)→ 停在「写跟进」等回执,单上的内容是**人改过的定稿**
  ⑤ 回执写好了 → 运行成功,输出说写了跟进;前面的步骤没重跑(取转写那张单仍只有一张)
  ⑥ 另一条:退回 → 写跟进一张单都没有,输出是退回理由
  ⑦ 一张把写跟进直接接在模型后面的图(没经过核对)→ 运行失败 WRITE_NEEDS_REVIEW,桥上不出写跟进的单
  ⑧ 重复回执同一张单 → 409,不排第二次恢复
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(根, ".venv", "bin", "python")
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 跑worker():
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"],
                   capture_output=True, text=True, timeout=180, cwd=根)


def 等到(rid, 想要, 最多=8):
    """跑 worker 直到运行进入 想要 里的某个状态(**不用 sleep 猜**)。"""
    for _ in range(最多):
        c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
        st = (r or {}).get("执行状态")
        if st in 想要:
            return st, r
        跑worker()
    c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
    return (r or {}).get("执行状态"), r


def 单(rid, 状态="待执行"):
    from urllib.parse import quote
    c, b = 打("GET", P + f"/bridge-calls?{quote('状态')}={quote(状态)}&execution_run_id={rid}", "U004")
    return (b or {}).get("items") or []


def 建图(名, 改=None):
    c, w = 打("POST", P + "/workflows", 体={"名称": f"{名} {uuid.uuid4().hex[:6]}", "模板": "音频整理"})
    assert c == 201, (c, w)
    c, d = 打("GET", P + f"/workflows/{w['id']}")
    定义 = d["草稿"]["定义"]
    for n in 定义["nodes"]:
        if n["type"] == "llm":
            # 只补模型 —— 处理要求模板已经默认选上了「客户需求提取」(用户 10-24 拍)
            n["config"]["connection_version_id"] = "cv_mock_" + 项目
    if 改:
        改(定义)
    c, b = 打("PATCH", P + f"/workflows/{w['id']}/draft", 体={"定义": 定义},
             头={"If-Match": str(d["草稿"]["revision"])})
    assert c == 200, (c, b)
    return w["id"], 定义


def 发起(wid, 输入):
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())},
             体={"workflow_id": wid, "输入": 输入})
    return c, r


def 待办(rid):
    c, b = 打("GET", P + "/human-requests?status=pending&limit=200", "U006")
    return [x for x in (b or {}).get("items") or [] if x.get("execution_run_id") == rid]


def 决定(hid, decision, **kw):
    c, d = 打("GET", P + f"/human-requests/{hid}", "U006")
    rev = d["请求"]["revision"]
    return 打("POST", P + f"/human-requests/{hid}/decisions", "U006",
             体={"decision": decision, "request_revision": rev, **kw},
             头={"Idempotency-Key": str(uuid.uuid4())})


# 资源先登记(重复跑不增加对象):CI 是一个全新的库,没登记过澜绣桥工具和「客户需求提取」——
# 10-24 第一次推上去 CI 就红在这儿(模板拿到 [None, None]),而本地库早就登记过,所以本地一直绿
subprocess.run([PY, os.path.join(根, "tools", "seed_bridge_tools.py"), "--项目", 项目],
               capture_output=True, text=True, timeout=120, cwd=根, check=True)

print("▸ ⓪ 模板卡片 / 下拉资源")
c, t = 打("GET", P + "/workflow-templates")
ck("模板卡片:音频整理排第一(弹窗默认选它),写明要哪些资源", c == 200 and t["items"][0]["名"] == "音频整理"
   and len(t["items"][0]["需要的资源"]) == 5, t)   # 10-24 加回电:多了「派任务」
ck("这个项目里资源齐了 → 标「能直接跑」", t["items"][0]["能直接跑吗"] is True, t["items"][0])
c, rs = 打("GET", P + "/workflow-resources")
ck("搭建下拉:模型 / 处理要求 / 业务动作 / 角色都有,业务动作里有澜绣的两个",
   c == 200 and rs["模型"] and rs["处理要求"] and {"取转写", "写跟进"} <= {x["名"] for x in rs["工具"]}
   and any(x["能审批"] for x in rs["角色"]), {k: len(v) for k, v in (rs or {}).items()})

print("\n▸ ① 建模板 → 补模型 → 校验")
wid, 定义 = 建图("e2e 音频整理")
提取 = [n for n in 定义["nodes"] if n["type"] == "llm"][0]
ck("处理要求默认选上了「客户需求提取」(用户 10-24 拍「带一份、默认选上」)",
   提取["config"].get("prompt_version_id") in {x["版本id"] for x in rs["处理要求"] if x["key"] == "customer_needs_extract"},
   提取["config"].get("prompt_version_id"))
c, d0 = 打("GET", P + f"/workflows/{wid}")
c, b = 打("PATCH", P + f"/workflows/{wid}", 体={"名称": "e2e 改过名", "用途": "录音 → 跟进"},
         头={"If-Match": str(d0["revision"])})
ck("设置页改名称 / 用途(带 If-Match)", c == 200 and b["名称"] == "e2e 改过名" and b["用途"] == "录音 → 跟进", (c, b))
c, b = 打("PATCH", P + f"/workflows/{wid}", 体={"名称": "后到的", "用途": "x"}, 头={"If-Match": str(d0["revision"])})
ck("拿旧 revision 再改 → 409(两个人同时改,后到的不许悄悄盖掉)",
   c == 409 and (b or {}).get("code") == "REVISION_CONFLICT", (c, b))
ck("模板预填了取转写 / 写跟进两个澜绣桥工具(项目里登记过的那两个)",
   all(n["config"].get("tool_version_id") for n in 定义["nodes"] if n["type"] == "tool"),
   [n["config"].get("tool_version_id") for n in 定义["nodes"] if n["type"] == "tool"])
c, b = 打("POST", P + f"/workflows/{wid}/validate")
ck("补上模型和处理要求后校验通过", c == 200 and b.get("通过"), b)

print("\n▸ ② 试运行 → 停在取转写等回执")
c, r = 发起(wid, {"call_id": "TS-001", "customer_id": "C10001"})
ck("受理 202", c == 202, (c, r))
rid = r["resource_id"]
st, _ = 等到(rid, ("waiting_external", "failed", "succeeded"))
ck("停在 waiting_external(等澜绣回执)", st == "waiting_external", st)
c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
等 = (r or {}).get("在等什么") or {}
ck("运行详情说清在等什么:等澜绣执行「取转写」,停在 fetch",
   等.get("种类") == "external" and 等.get("工具") == "取转写" and 等.get("步骤") == "fetch", 等)
ck("挂起中「继续」这个控制动作不可用,而且说了为什么",
   any(a["动作"] == "resume" and not a["现在能吗"] and "自动接着跑" in (a["为什么不能"] or "")
       for a in r["可执行的控制动作"]), r["可执行的控制动作"])
c, b = 打("POST", P + f"/execution-runs/{rid}/resume", "U002", 体={},
         头={"Idempotency-Key": str(uuid.uuid4()), "If-Match": str(r["revision"])})
ck("**硬点「继续」→ 409 WAITING_FOR_EVENT**(结构闸,不只是按钮藏起来)",
   c == 409 and (b or {}).get("code") == "WAITING_FOR_EVENT", (c, b))
s1 = 单(rid)
ck("桥上有一张「取转写」待执行单,参数是通话号", len(s1) == 1 and s1[0]["工具"] == "取转写"
   and s1[0]["参数"] == {"call_id": "TS-001"}, s1)

print("\n▸ ③ 回执转写 → 停在人工核对")
原文 = ("顾问:您好。顾客:我想做一套宋制褙子,秋天穿,预算三千左右,十一月中要。"
        "我电话 13800138000,面料想看看真丝和棉麻,颜色偏素一点,领口要交领,袖子别太宽,"
        "腰身收一点显瘦,下摆到脚踝,配一条百迭裙,里衬要透气,夏末也能穿。")   # 超过 160 字,带手机号
c, b = 打("POST", P + f"/bridge-calls/{s1[0]['id']}/ack", "U004",
         体={"结果": "已执行", "输出": {"text": 原文, "call_id": "TS-001", "customer_id": "C10001"}})
ck("回执成功,而且排上了恢复任务", c == 200 and b.get("恢复任务"), (c, b))
st, _ = 等到(rid, ("waiting_approval", "failed", "succeeded"))
ck("停在 waiting_approval(等人工核对)", st == "waiting_approval", st)
hs = 待办(rid)
c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
ck("运行详情说清在等人工核对,带待办号和截止时间",
   (r.get("在等什么") or {}).get("种类") == "human" and (r.get("在等什么") or {}).get("待办") == (hs[0]["id"] if hs else None)
   and (r.get("在等什么") or {}).get("截止"), r.get("在等什么"))
ck("待办里有一条这次运行的核对", len(hs) == 1, hs)
c, d = 打("GET", P + f"/human-requests/{hs[0]['id']}", "U006") if hs else (0, {})
参 = (d or {}).get("核对材料") or {}
ck("待办详情看得到摘要、待确认项和原文(原文是回执带回来的那份)",
   {"摘要", "待确认项", "原文"} <= set(参) and "宋制褙子" in str(参.get("原文")), 参)
ck("**原文是全文**(核对就是对着原文看;不是「N 字 · 开头……」的形状),手机号打了码",
   参.get("原文") == 原文.replace("13800138000", "138****8000"), 参.get("原文"))
ck("允许编辑的字段只有「定稿」和回电那两样(负责人 / 截止,10-24 加回电)",
   (d or {}).get("允许编辑的字段") == ["定稿", "回电负责人", "回电截止"], (d or {}).get("允许编辑的字段"))

print("\n▸ ④ 批准(改了定稿)→ 停在写跟进")
定稿 = "顾客要宋制褙子,秋款,预算约 3000,11 月中交;面料待确认。"
c, b = 决定(hs[0]["id"], "approved", edits={"定稿": 定稿})
ck("批准记下,并排上了恢复", c == 201 and (b.get("运行") or {}).get("恢复任务"), (c, b))
st, _ = 等到(rid, ("waiting_external", "failed", "succeeded"))
ck("停在 waiting_external(等写跟进回执)", st == "waiting_external", st)
s2 = 单(rid)
ck("桥上出了一张「写跟进」单,内容是**人改过的定稿**,客户号对",
   len(s2) == 1 and s2[0]["工具"] == "写跟进" and s2[0]["参数"].get("内容") == 定稿
   and s2[0]["参数"].get("customer_id") == "C10001", s2)

print("\n▸ ⑤ 回执写好了 → 成功")
c, b = 打("POST", P + f"/bridge-calls/{s2[0]['id']}/ack", "U004",
         体={"结果": "已执行", "输出": {"跟进号": "FU-E2E-1", "customer_id": "C10001",
                                       "是新写的": True, "结果": "已写跟进 FU-E2E-1"}})
st, r5 = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功", st == "succeeded", (st, r5))
c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
ck("输出带着写跟进回来的跟进号(这一次核对人没填回电负责人 → 只写跟进,10-24 加回电)",
   "FU-E2E-1" in json.dumps((r or {}).get("输出"), ensure_ascii=False), (r or {}).get("输出"))
ck("**取转写只有一张单**(恢复时前面的步骤没重跑)",
   [x["工具"] for x in 单(rid, "已执行")].count("取转写") == 1, 单(rid, "已执行"))
c, b = 打("POST", P + f"/bridge-calls/{s2[0]['id']}/ack", "U004",
         体={"结果": "已执行", "输出": {"跟进号": "FU-E2E-2", "结果": "x"}})
ck("⑧ 同一张单再回执一次 → 409(不排第二次恢复)", c == 409, (c, b))

print("\n▸ ⑥ 退回那一路")
c, r = 发起(wid, {"call_id": "TS-002", "customer_id": "C10002"})
rid2 = r["resource_id"]
等到(rid2, ("waiting_external",))
打("POST", P + f"/bridge-calls/{单(rid2)[0]['id']}/ack", "U004",
  体={"结果": "已执行", "输出": {"text": "顾客问价,没说要什么。", "call_id": "TS-002"}})
等到(rid2, ("waiting_approval",))
c, b = 决定(待办(rid2)[0]["id"], "rejected", reason="录音里没有需求,不写跟进")
st, _ = 等到(rid2, ("succeeded", "failed", "incomplete"))
ck("退回之后跑完了(退回是一种结果,不是故障)", st == "succeeded", st)
ck("**写跟进一张单都没有**", not [x for s in ("待执行", "已执行", "执行失败") for x in 单(rid2, s)
                              if x["工具"] == "写跟进"])
c, r = 打("GET", P + f"/execution-runs/{rid2}", "U004")
ck("输出是退回理由", "录音里没有需求" in json.dumps(r, ensure_ascii=False))

print("\n▸ ⑨ 运行被取消了,澜绣就拉不到它的单")
c, r = 发起(wid, {"call_id": "TS-009", "customer_id": "C10009"})
rid9 = r["resource_id"]
等到(rid9, ("waiting_external",))
ck("(取消前)单子在待执行列表里", len(单(rid9)) == 1, 单(rid9))
c, d9 = 打("GET", P + f"/execution-runs/{rid9}", "U004")
c, b = 打("POST", P + f"/execution-runs/{rid9}/cancel", "U002", 体={},
         头={"Idempotency-Key": str(uuid.uuid4()), "If-Match": str(d9["revision"])})
ck("取消成功", c in (200, 202), (c, b))
ck("**取消之后待执行列表里没有它了**(澜绣不会再去执行一张没人等的单)", 单(rid9) == [], 单(rid9))

print("\n▸ ⑨b 等核对时取消 → 那条核对待办一起关掉(10-24 真模型验证时撞到它还挂着)")
c, r = 发起(wid, {"call_id": "TS-011", "customer_id": "C10011"})
rid11 = r["resource_id"]
等到(rid11, ("waiting_external",))
打("POST", P + f"/bridge-calls/{单(rid11)[0]['id']}/ack", "U004",
  体={"结果": "已执行", "输出": {"text": "随便一段", "call_id": "TS-011"}})
等到(rid11, ("waiting_approval",))
ck("(取消前)待办在待处理里", len(待办(rid11)) == 1, 待办(rid11))
c, d11 = 打("GET", P + f"/execution-runs/{rid11}", "U004")
打("POST", P + f"/execution-runs/{rid11}/cancel", "U002", 体={},
  头={"Idempotency-Key": str(uuid.uuid4()), "If-Match": str(d11["revision"])})
ck("**取消之后待处理里没有它了**(不留一条批了也不会发生任何事的待办)", 待办(rid11) == [], 待办(rid11))

print("\n▸ ⑩ 人工核对到期没人处理 → 这次运行结束,记「已过期」")
def 秒过期(d):
    for n in d["nodes"]:
        if n["id"] == "review":
            n["config"]["expires_at_policy"] = {"小时": 0.0005, "到期": "fail"}     # 1.8 秒
wid10, _ = 建图("e2e 过期", 秒过期)
c, r = 发起(wid10, {"call_id": "TS-010", "customer_id": "C10010"})
rid10 = r["resource_id"]
等到(rid10, ("waiting_external",))
打("POST", P + f"/bridge-calls/{单(rid10)[0]['id']}/ack", "U004",
  体={"结果": "已执行", "输出": {"text": "随便一段", "call_id": "TS-010"}})
等到(rid10, ("waiting_approval",))
import time as _t
_t.sleep(2.5)
st, _ = 等到(rid10, ("expired", "succeeded", "failed"))
c, r = 打("GET", P + f"/execution-runs/{rid10}", "U004")
ck("到点 → 运行终态「已过期」,原因 HUMAN_REVIEW_EXPIRED", st == "expired" and r.get("停止原因") == "HUMAN_REVIEW_EXPIRED",
   (st, r.get("停止原因")))
c, b = 打("GET", P + "/human-requests?status=expired&limit=200", "U006")
ck("待办也标成过期了", any(x.get("execution_run_id") == rid10 for x in (b or {}).get("items") or []))
ck("**什么都没写**:写跟进一张单都没有",
   not [x for s in ("待执行", "已执行", "执行失败") for x in 单(rid10, s) if x["工具"] == "写跟进"])

print("\n▸ ⑪ 聊天接管开关(用户 10-24 拍「默认关;打开时聊天站改走工作流」)")
# 先把演示项目里别的测试留下的接管关掉 —— 同一个技能只许一条接管,上一轮中途挂了会占着
c, ls = 打("GET", P + "/workflows?limit=100")
for x in (ls or {}).get("items") or []:
    if x.get("聊天接管"):
        c, dx = 打("GET", P + f"/workflows/{x['id']}")
        打("PATCH", P + f"/workflows/{x['id']}", 体={"名称": dx["名称"], "聊天接管": False}, 头={"If-Match": str(dx["revision"])})
c, d = 打("GET", P + f"/workflows/{wid}")
ck("音频整理模板登记了对应技能 call-notes,**默认不接管**(交给 harness)",
   d.get("对应技能") == "call-notes" and d.get("聊天接管") is False, (d.get("对应技能"), d.get("聊天接管")))
c, tk = 打("GET", P + "/chat-takeovers")
ck("默认接管清单里没有它", not [x for x in tk["items"] if x["workflow_id"] == wid], tk)
c, b = 打("PATCH", P + f"/workflows/{wid}", 体={"名称": d["名称"], "聊天接管": True}, 头={"If-Match": str(d["revision"])})
ck("没发布到生产就打开 → 422 TAKEOVER_NO_VERSION(聊天接管只跑生产那一版,不跑草稿、也不跑候选)",
   c == 422 and (b or {}).get("code") == "TAKEOVER_NO_VERSION", (c, b))
c, v = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e:接管前先生成一版"})
c, d = 打("GET", P + f"/workflows/{wid}")
c, b = 打("PATCH", P + f"/workflows/{wid}", 体={"名称": d["名称"], "聊天接管": True}, 头={"If-Match": str(d["revision"])})
ck("**只生成了候选版本、没发布到生产 → 还是 422**(10-26:生成一版不等于上线)",
   c == 422 and (b or {}).get("code") == "TAKEOVER_NO_VERSION", (c, b))


# ── 发布到环境(10-26,方案 §8.4):每条工作流对应一个应用,清单 / 审核 / 环境指针全用应用那套 ──
def 发到(wid_, vid_, 环境, 谁="U001"):
    return 打("POST", P + f"/workflows/{wid_}/releases", 谁, 体={"版本id": vid_, "环境": 环境},
             头={"Idempotency-Key": str(uuid.uuid4())})


def 发到生产(wid_, vid_):
    """审核 + 发生产,一步到位(给后面要用生产版的地方)。"""
    c, b = 发到(wid_, vid_, "production")
    if c == 422:
        打("POST", P + f"/releases/{(b.get('field_errors') or {}).get('清单id')}/reviews", "U001", 体={"结论": "通过"})
        c, b = 发到(wid_, vid_, "production")
    return c, b


v1 = v["id"]
c, b = 发到(wid, v1, "staging", "U002")
ck("编辑者(U002)不能发布 → 403(发布和改草稿不是同一档权限)", c == 403, (c, b))
c, b = 发到(wid, v1, "staging")
ck("发到预发 → 202,不要审核(预发就是用来试的)", c == 202 and b.get("清单id"), (c, b))
c, rs = 打("GET", P + f"/workflows/{wid}/releases")
ck("「各环境」里预发在跑 v1、生产还没发布",
   (rs["各环境"]["staging"] or {}).get("版本id") == v1 and not (rs["各环境"]["production"] or {}).get("版本id"), rs["各环境"])
c, b = 发到(wid, v1, "production")
清单1 = ((b or {}).get("field_errors") or {}).get("清单id")
ck("**没审核就发生产 → 422 CANNOT_DEPLOY,并带回清单号去审**(生产只认审过的)",
   c == 422 and (b or {}).get("code") == "CANNOT_DEPLOY" and 清单1, (c, b))
c, _ = 打("POST", P + f"/releases/{清单1}/reviews", "U001", 体={"结论": "通过"})
c, b = 发到(wid, v1, "production")
ck("审核通过之后发生产 → 202", c == 202, (c, b))
c, d = 打("GET", P + f"/workflows/{wid}")
c, b = 打("PATCH", P + f"/workflows/{wid}", 体={"名称": d["名称"], "聊天接管": True}, 头={"If-Match": str(d["revision"])})
ck("发布到生产之后打开接管 → 200", c == 200 and b.get("聊天接管") is True, (c, b))
c, tk = 打("GET", P + "/chat-takeovers")
项 = [x for x in tk["items"] if x["workflow_id"] == wid]
ck("接管清单里有它:技能 call-notes、版本是**生产那一版**", 项 and 项[0]["技能"] == "call-notes" and 项[0]["版本id"] == v1, tk)
# 生成新一版要**逻辑上**有变化(改名字不算)—— 把人工核对的到期时间从 48 改成 72 小时
c, d = 打("GET", P + f"/workflows/{wid}")
定 = d["草稿"]["定义"]
for n in 定["nodes"]:
    if n.get("type") == "human":
        n.setdefault("config", {})["expires_at_policy"] = {"小时": 72, "到期": "fail"}
打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定}, 头={"If-Match": str(d["草稿"]["revision"])})
c, v2 = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e:生成新一版但不发布"})
c, tk = 打("GET", P + "/chat-takeovers")
项 = [x for x in tk["items"] if x["workflow_id"] == wid]
ck("**又生成了新一版但没发布 → 接管清单照旧是生产那一版**(生成 ≠ 上线,这正是这次要堵的)",
   c == 200 and (v2 or {}).get("id") and 项 and 项[0]["版本id"] == v1, (项, (v2 or {}).get("id")))
wid2, _ = 建图("e2e 抢接管")
c, 版2 = 打("POST", P + f"/workflows/{wid2}/versions", 体={"变更说明": "e2e"})
发到生产(wid2, 版2["id"])
c, d2 = 打("GET", P + f"/workflows/{wid2}")
c, b = 打("PATCH", P + f"/workflows/{wid2}", 体={"名称": d2["名称"], "聊天接管": True}, 头={"If-Match": str(d2["revision"])})
ck("**同一个技能第二条也想接管 → 409 TAKEOVER_TAKEN**(聊天站不能不知道该发起哪条)",
   c == 409 and (b or {}).get("code") == "TAKEOVER_TAKEN", (c, b))

print("\n▸ ⑫ 账号绑定 + 聊天站发起被接管的工作流(用户 10-24 拍「一对一绑定」「打开时聊天站改走工作流」)")
工号 = "E2E" + uuid.uuid4().hex[:6]
打("DELETE", P + "/staff-bindings/U002", "U001")          # 上一轮挂在半路留下的绑定
c, b = 打("PUT", P + "/staff-bindings/U002", "U002", 体={"澜绣工号": 工号})
ck("编辑者不能绑账号 → 403(绑定 = 决定以谁的身份办事,和管凭证同一档)", c == 403, (c, b))
c, b = 打("POST", P + "/chat-takeovers/call-notes/runs", "U001", 头={"Idempotency-Key": str(uuid.uuid4())},
         体={"澜绣工号": 工号, "输入": {"call_id": "TS-001", "customer_id": "C10000"}})
ck("工号没绑定 → 409 NOT_BOUND(不拿服务账号顶替)", c == 409 and (b or {}).get("code") == "NOT_BOUND", (c, b))
c, b = 打("PUT", P + "/staff-bindings/U002", "U001", 体={"澜绣工号": 工号, "备注": "e2e"})
ck("管理员绑定 U002 ↔ 这个工号 → 200", c == 200, (c, b))
c, b = 打("PUT", P + "/staff-bindings/U006", "U001", 体={"澜绣工号": 工号})
ck("**同一个工号再绑给第二个账号 → 409 STAFF_TAKEN**(一对一)",
   c == 409 and (b or {}).get("code") == "STAFF_TAKEN", (c, b))
键 = str(uuid.uuid4())
c, b = 打("POST", P + "/chat-takeovers/call-notes/runs", "U001", 头={"Idempotency-Key": 键},
         体={"澜绣工号": 工号, "输入": {"call_id": "TS-001", "customer_id": "C10000"}})
ck("接管开着 + 已绑定 → 202,带运行号和核对入口", c == 202 and (b or {}).get("resource_id")
   and "/#/wfrun/" in (b or {}).get("核对入口", ""), (c, b))
接管运行 = (b or {}).get("resource_id")
c, r = 打("GET", P + f"/execution-runs/{接管运行}", "U004")
ck("**运行的发起人是绑定的那个人(U002),不是调用方 U001**", (r or {}).get("请求人") == "U002"
   or (r or {}).get("principal") == "U002", {k: (r or {}).get(k) for k in ("请求人", "principal")})
c, b2 = 打("POST", P + "/chat-takeovers/call-notes/runs", "U001", 头={"Idempotency-Key": 键},
          体={"澜绣工号": 工号, "输入": {"call_id": "TS-001", "customer_id": "C10000"}})
ck("同一个幂等键再发一次 → 还是原来那条,不新建", (b2 or {}).get("resource_id") == 接管运行, (c, b2))
c, b = 打("POST", P + "/chat-takeovers/quote/runs", "U001", 头={"Idempotency-Key": str(uuid.uuid4())},
         体={"澜绣工号": 工号, "输入": {}})
ck("没被接管的技能 → 409 TAKEOVER_OFF(交给 harness)", c == 409 and (b or {}).get("code") == "TAKEOVER_OFF", (c, b))
打("POST", P + f"/execution-runs/{接管运行}/cancel", "U002", 体={"reason": "e2e 收尾"})
c, b = 打("DELETE", P + "/staff-bindings/U002", "U001")
ck("解绑 → 200", c == 200, (c, b))
c, d = 打("GET", P + f"/workflows/{wid}")
c, b = 打("PATCH", P + f"/workflows/{wid}", 体={"名称": d["名称"], "聊天接管": False}, 头={"If-Match": str(d["revision"])})
c, tk = 打("GET", P + "/chat-takeovers")
ck("关掉 → 清单里没有它了(交还给 harness)", c == 200 and not [x for x in tk["items"] if x["workflow_id"] == wid], tk)
c, b = 打("POST", P + "/chat-takeovers/call-notes/runs", "U001", 头={"Idempotency-Key": str(uuid.uuid4())},
         体={"澜绣工号": 工号, "输入": {"call_id": "TS-001", "customer_id": "C10000"}})
ck("**关掉之后聊天站拿着旧清单来发起 → 409 TAKEOVER_OFF**(开没开由服务端判)",
   c == 409 and (b or {}).get("code") == "TAKEOVER_OFF", (c, b))

print("\n▸ ⑬ 录音加回电(用户 10-24 拍「两个都要:先写跟进,有意向再派回电」;负责人和时间由核对人填)")
def 走到核对(wid_, 客户="C10001"):
    c, r = 发起(wid_, {"call_id": "TS-001", "customer_id": 客户}); rid_ = r["resource_id"]
    等到(rid_, ("waiting_external",))
    打("POST", P + f"/bridge-calls/{单(rid_)[0]['id']}/ack", "U004",
      体={"结果": "已执行", "输出": {"text": "我想做一件宋制褙子,下个月婚礼穿", "call_id": "TS-001", "customer_id": 客户}})
    等到(rid_, ("waiting_approval",))
    return rid_
def 写完跟进(rid_):
    等到(rid_, ("waiting_external",))
    s_ = [x for x in 单(rid_) if x["工具"] == "写跟进"]
    打("POST", P + f"/bridge-calls/{s_[0]['id']}/ack", "U004",
      体={"结果": "已执行", "输出": {"跟进号": "FU-E2E-CB", "是新写的": True, "结果": "已写跟进 FU-E2E-CB"}})
wcb, _ = 建图("e2e 录音回电")
c, v = 打("POST", P + f"/workflows/{wcb}/validate")
ck("加了回电分支的模板,补上模型后校验通过", v.get("通过") is True, v)
rcb = 走到核对(wcb)
c, det = 打("GET", P + f"/human-requests/{待办(rcb)[0]['id']}", "U006")
ck("核对材料里有 AI 判断的类别,可改字段里有回电负责人 / 回电截止",
   (det.get("核对材料") or {}).get("类别") in ("明确需求", "考虑中", "无明确需求", "信息不足")
   and {"回电负责人", "回电截止"} <= set(det.get("允许编辑的字段") or []), (det.get("核对材料"), det.get("允许编辑的字段")))
决定(待办(rcb)[0]["id"], "approved", edits={"定稿": "顾客要宋制褙子,下月婚礼", "回电负责人": "60000003",
                                          "回电截止": "2026-12-31 10:00"})
写完跟进(rcb)
st, _ = 等到(rcb, ("waiting_external", "failed", "succeeded"))
派 = [x for x in 单(rcb) if x["工具"] == "assign_task"]
ck("**有意向 + 填了负责人和截止 → 写完跟进再派「电话回电」**,负责人 / 截止 / 客户号都是核对人填的和发起时的",
   st == "waiting_external" and 派 and 派[0]["参数"].get("type") == "电话回电"
   and 派[0]["参数"].get("assignee") == "60000003" and 派[0]["参数"].get("end") == "2026-12-31 10:00"
   and 派[0]["参数"].get("ref_id") == "C10001" and 派[0]["参数"].get("note") == "顾客要宋制褙子,下月婚礼",
   (st, 派 and 派[0]["参数"]))
打("POST", P + f"/bridge-calls/{派[0]['id']}/ack", "U004", 体={"结果": "已执行", "输出": {"数据": {"ok": True}, "结果": "已派"}}) if 派 else None
st, rr = 等到(rcb, ("succeeded", "failed", "incomplete"))
ck("派完 → 成功,输出说「派了电话回电」", st == "succeeded" and "派了电话回电" in json.dumps((rr or {}).get("输出"), ensure_ascii=False),
   (st, (rr or {}).get("输出")))
rcb2 = 走到核对(wcb)
决定(待办(rcb2)[0]["id"], "approved", edits={"回电负责人": "60000003"})
写完跟进(rcb2)
st, rr = 等到(rcb2, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("**只填了负责人、没填截止 → 不派**,输出说明为什么",
   st == "succeeded" and not [x for s_ in ("待执行", "已执行") for x in 单(rcb2, s_) if x["工具"] == "assign_task"]
   and "没填回电截止" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))
def 只认考虑中(d):
    for n in d["nodes"]:
        if n["id"] == "intent":
            n["config"]["branches"][0]["when"]["left"]["value"] = ["考虑中"]   # mock 出的是第一个可选值「明确需求」
wcb3, _ = 建图("e2e 录音回电·没意向", 只认考虑中)
rcb3 = 走到核对(wcb3)
决定(待办(rcb3)[0]["id"], "approved", edits={"回电负责人": "60000003", "回电截止": "2026-12-31 10:00"})
写完跟进(rcb3)
st, rr = 等到(rcb3, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("**类别不在「有意向」里 → 填了负责人和截止也不派**(不是有人填了就派)",
   st == "succeeded" and not [x for s_ in ("待执行", "已执行") for x in 单(rcb3, s_) if x["工具"] == "assign_task"]
   and "不派回电" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))

print("\n▸ ⑦ 没经过核对就写跟进 → 拒")
def 绕过核对(d):
    d["nodes"] = [n for n in d["nodes"] if n["id"] not in ("review", "decide", "rejected", "merge",
                                                         # 10-24 加的回电那一串也引用核对结果,一起删
                                                         "intent", "who", "when", "callback", "cb_done",
                                                         "no_intent", "no_who", "no_when")]
    for n in d["nodes"]:
        if n["id"] == "save":
            n["config"]["bindings"]["内容"] = {"source": "node", "node_id": "extract", "pointer": "/跟进草稿"}
        if n["id"] == "finish":
            n["config"]["bindings"] = {"结果": {"source": "node", "node_id": "save", "pointer": "/结果"}}
    d["edges"] = [{"source": a, "target": b, "port": "success"} for a, b in
                  (("start", "fetch"), ("fetch", "extract"), ("extract", "save"), ("save", "finish"))]
wid3, _ = 建图("e2e 绕过核对", 绕过核对)
c, b = 打("POST", P + f"/workflows/{wid3}/validate")
ck("(这张图校验是能过的 —— 所以拦截必须落在执行那一侧)", c == 200 and b.get("通过"), b)
c, r = 发起(wid3, {"call_id": "TS-003", "customer_id": "C10003"})
rid3 = r["resource_id"]
等到(rid3, ("waiting_external",))
打("POST", P + f"/bridge-calls/{单(rid3)[0]['id']}/ack", "U004",
  体={"结果": "已执行", "输出": {"text": "随便一段", "call_id": "TS-003"}})
st, r = 等到(rid3, ("failed", "succeeded", "waiting_external"))
c, r = 打("GET", P + f"/execution-runs/{rid3}", "U004")
ck("运行失败,原因 WRITE_NEEDS_REVIEW", st == "failed" and "WRITE_NEEDS_REVIEW" in json.dumps(r, ensure_ascii=False),
   (st, str(r)[:300]))
ck("**桥上没有写跟进的单**", not [x for s in ("待执行", "已执行") for x in 单(rid3, s) if x["工具"] == "写跟进"])

print()
if 挂:
    print(f"❌ {len(挂)} 条不过(验了 {len(过) + len(挂)} 条):{挂}")
    sys.exit(1)
print(f"✅ 音频整理全流程:取转写 → 提取 → 人工核对 → 写跟进,挂起 / 恢复 / 退回 / 绕过核对都对(验了 {len(过)} 条)")
