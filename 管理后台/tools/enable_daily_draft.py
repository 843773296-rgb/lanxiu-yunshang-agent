#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经营日报草稿 · 在正式项目 project_lanxiu 里启用(用户 11-21 拍「用演示门店以管理员身份启用」;11-22 推完后跑)。
每一步都打印、任何一步不是预期就停(不往下猜)。写共享库:**锁空、告过 fc 再跑**。
  0 处理要求已种(seed_bridge_tools --项目 project_lanxiu 先跑过)
  1 POST /workflows {模板:经营日报草稿} → wid
  2 GET 草稿 → llm 节点 connection_version_id = cv_ffc3943b4995(正式项目唯一真模型连接)→ PATCH /draft(If-Match)
  3 POST /validate → 通过
  4 POST /versions → vid
  5 POST /execution-runs {workflow_id} 真跑一次(取数走桥 supervise、写正文真调模型 —— 几分钱)→ 等 succeeded
  6 POST /releases {版本id, 环境: production} → 422 带 清单id → POST /releases/{清单id}/reviews {结论: 通过} → 再发 → 202
  7 PUT /workflows/{wid}/schedule {开着: true} → 200,打印下次时刻
用法:python3 enable_daily_draft.py [--只到 N]
     python3 enable_daily_draft.py --换要求 --wid wf_xxx --pv pv_xxx   # 11-23:处理要求改了措辞 → 先 `seed_bridge_tools.py --项目 project_lanxiu`
                                                            # 拿它打印的新版本号 pv_…,再跑这条:把已启用流程的草稿换到那版 → 校验 → 冻结 → 真跑 → 发生产;
                                                            # 定时原来开着就不动(最后 GET schedule 打出来核一眼)
"""
import json, sys, time, uuid, urllib.request, urllib.error

基址, 项目, 我 = "http://127.0.0.1:8801", "project_lanxiu", "U001"
P = f"/api/v1/projects/{项目}"
模型连接版本 = "cv_ffc3943b4995"
只到 = int(sys.argv[sys.argv.index("--只到") + 1]) if "--只到" in sys.argv else 99


def 打(方法, 路, 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法, data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 我)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 停(步, c, d):
    print(f"❌ 第 {步} 步不是预期:{c} {str(d)[:400]}"); sys.exit(1)


从 = int(sys.argv[sys.argv.index("--从") + 1]) if "--从" in sys.argv else 0
wid = sys.argv[sys.argv.index("--wid") + 1] if "--wid" in sys.argv else None
vid = sys.argv[sys.argv.index("--vid") + 1] if "--vid" in sys.argv else None


def 前五步():
    c, t = 打("GET", P + "/workflow-templates")
    卡 = next((x for x in (t or {}).get("items") or [] if x["名"] == "经营日报草稿"), None)
    print("0 模板卡片:", json.dumps({k: 卡.get(k) for k in ("能直接跑吗", "要")} if 卡 else {}, ensure_ascii=False)[:600])
    if not 卡 or not 卡.get("能直接跑吗"):
        停(0, c, "模板说还不能直接跑 —— 先种处理要求 / 桥工具")
    if 只到 < 1: sys.exit(0)

    c, w = 打("POST", P + "/workflows", 体={"名称": "经营日报草稿(演示门店)", "模板": "经营日报草稿"})
    if c != 201: 停(1, c, w)
    wid = w["id"]; print("1 建流程", wid)
    if 只到 < 2: sys.exit(0)

    改llm节点(wid, {"connection_version_id": 模型连接版本}, 说明="2 选模型 " + 模型连接版本)
    if 只到 < 3: sys.exit(0)
    return wid, 校验冻结真跑(wid, "经营日报草稿首版(演示门店启用,11-22)")


def 改llm节点(wid, 配置补丁, 说明):
    """GET 草稿 → 给每个 llm 节点的 config 合进补丁 → PATCH(If-Match 草稿.revision)。"""
    c, d = 打("GET", P + f"/workflows/{wid}")
    if c != 200: 停(2, c, d)
    定义 = d["草稿"]["定义"]
    for n in 定义["nodes"]:
        if n["type"] == "llm":
            n["config"].update(配置补丁)
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    if c != 200: 停(2, c, b)
    print(说明)


def 校验冻结真跑(wid, 变更说明):
    """3 校验 → 4 冻结版本 → 5 真跑一次等到 succeeded(真调模型几分钱)→ 返回 vid。"""
    c, v = 打("POST", P + f"/workflows/{wid}/validate")
    if c != 200 or not v.get("通过"): 停(3, c, v)
    print("3 校验通过")
    if 只到 < 4: sys.exit(0)

    c, 版 = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": 变更说明})
    if c != 201: 停(4, c, 版)
    vid = 版["id"]; print("4 冻结版本", vid)
    if 只到 < 5: sys.exit(0)

    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())}, 体={"workflow_id": wid, "输入": {}})
    if c not in (200, 201, 202): 停(5, c, r)
    rid = r.get("resource_id") or r.get("id"); print("5 真跑一次", rid, "(等它跑完…)")
    st = rr = None
    for _ in range(60):
        time.sleep(10)
        c, rr = 打("GET", P + f"/execution-runs/{rid}")
        st = (rr or {}).get("执行状态") or (rr or {}).get("status")   # 11-22:运行详情的键是「执行状态」,原来读 status 永远 None、空等 10 分钟
        print("   ", st, (rr or {}).get("停止原因") or "")
        if st in ("succeeded", "failed", "cancelled"):
            break
    if st != "succeeded": 停(5, st, rr)
    return vid


换要求 = "--换要求" in sys.argv
pv = sys.argv[sys.argv.index("--pv") + 1] if "--pv" in sys.argv else None
if 换要求:
    # 11-23:只换处理要求版本,流程 / 模型 / 定时都不动。pv 从 seed_bridge_tools 的打印里抄(内容没变它不出新版本,那就没必要跑这条)
    if not (wid and pv): 停(0, "--换要求", "要带 --wid 和 --pv")
    改llm节点(wid, {"prompt_version_id": pv}, 说明="2 换处理要求 " + pv)
    vid = 校验冻结真跑(wid, f"换处理要求 {pv}(11-23:口径按统计期改写、异常段分当日新增 / 存量)")
elif 从 <= 5:
    wid, vid = 前五步()
else:
    print("从第 6 步接着(前五步已做过):", wid, vid)
if 只到 < 6: sys.exit(0)

def 发到(环境):
    return 打("POST", P + f"/workflows/{wid}/releases", 体={"版本id": vid, "环境": 环境}, 头={"Idempotency-Key": str(uuid.uuid4())})
c, b = 发到("production")
if c == 422 and ((b or {}).get("field_errors") or {}).get("清单id"):
    清单 = b["field_errors"]["清单id"]
    c2, _ = 打("POST", P + f"/releases/{清单}/reviews", 体={"结论": "通过"})
    print("6a 审核清单", 清单, c2)
    c, b = 发到("production")
if c != 202: 停(6, c, b)
print("6 发到生产", (b or {}).get("清单id"))
if 只到 < 7: sys.exit(0)

if 换要求:
    c, s = 打("GET", P + f"/workflows/{wid}/schedule")   # 定时本来就开着,只核一眼还开着、下次是明早
    if c != 200: 停(7, c, s)
    print("7 定时(没动):", json.dumps((s or {}).get("定时") or s, ensure_ascii=False)[:400])
    print("✅ 处理要求已换到", pv, "版本", vid)
    sys.exit(0)

c, s = 打("PUT", P + f"/workflows/{wid}/schedule", 体={"开着": True})
if c != 200: 停(7, c, s)
print("7 定时打开:", json.dumps({k: s.get(k) for k in ("开着", "频率说明", "下次", "统计哪一天", "身份") if k in (s or {})}, ensure_ascii=False)[:400])
print("✅ 经营日报草稿已启用:", wid, vid)
