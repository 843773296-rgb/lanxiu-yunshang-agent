#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询路由的接口(2026-11-08 第二期)—— 端到端,在测试进程里调接口(TestClient:咬合改坏 routes_api 时在视野里)。

用户 11-08 拍「查询理解」下实体识别 / 查询路由 / 意图识别各自列表-详情-配置、各自冻版本、店长助手各选一版;去向 6 种全要。

  ① 建路由 → 改草稿:不带 If-Match → 拒;拿错的 revision → 409
  ② 「提示先调工具」没写工具 → 检查点名、冻结 422;选「转人工」不再被点名(11-10 用户点头开转人工,主循环已接上)
  ③ 改好 → 冻出 v1;一字没改再冻 → 409;取版本一次给全
  ④ 「试一句」:接上实体识别版本 —— 客户名走「提示先调工具」、术语被路由成「只占位」(不带定义)、拿不准走歧义规则;手填意图走意图规则
  ⑤ 冻结的版本在库里改不动(触发器)
  ⑥ 聊天助手选这一版:英文键 route_version_id 422;不存在 422;**路由点名了助手没有的工具 → 422**;
     没挂时生产配置给显式 null;挂上 → 生产配置的 route_version_id 就是它;详情「可选路由」列出这一版
"""
import json
import os
import sys
import uuid

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
for p in (("services", "api", "app"), ("services", "api", "app", "runtime"), ("services", "api", "app", "contract")):
    sys.path.insert(0, os.path.join(根, *p))
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import main as M  # noqa: E402

项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
客 = TestClient(M.app)
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 头=None, 谁="U002"):
    r = 客.request(方法, P + 路, json=体, headers={"X-Dev-User": 谁, **(头 or {})})
    return r.status_code, (r.json() if r.content else None)


def main():
    key = "e2e-route-" + uuid.uuid4().hex[:6]
    c_, s = 打("POST", "/routes", {"key": key})
    ck("前提:建路由 201", c_ == 201 and (s or {}).get("id"), (c_, s))
    rid = s["id"]
    坏 = {"规则": [{"名称": "投诉转人工", "条件": {"种类": "意图", "值": "投诉"}, "去向": "转人工"},
                  {"名称": "客户先查", "条件": {"种类": "实体", "值": "客户"}, "去向": "提示先调工具"}]}
    c1, _ = 打("PATCH", f"/routes/{rid}/draft", {"配置": 坏})
    c2, _ = 打("PATCH", f"/routes/{rid}/draft", {"配置": 坏}, {"If-Match": "999"})
    ck("① 改草稿不带 If-Match → 拒;拿错的 revision → 409", c1 == 409 and c2 == 409, (c1, c2))
    c_, d = 打("PATCH", f"/routes/{rid}/draft", {"配置": 坏}, {"If-Match": "1"})
    c3, _ = 打("POST", f"/routes/{rid}/versions")
    阻 = (d or {}).get("检查", {}).get("阻断", [])
    ck("② 先调工具没写工具 → 检查点名、冻结 422;转人工不再被点名(11-10 起放行)",
       c_ == 200 and not any("投诉转人工" in x for x in 阻) and any("没写工具名" in x for x in 阻) and c3 == 422, (c_, 阻, c3))
    好 = {"规则": [{"名称": "客户先查档案", "条件": {"种类": "实体", "值": "客户"}, "去向": "提示先调工具",
                   "工具": "只读那个", "提示": "「{片段}」是客户,先查档案_e2e"},
                  {"名称": "术语不带", "条件": {"种类": "实体", "值": "术语"}, "去向": "只占位"},
                  {"名称": "歧义", "条件": {"种类": "歧义"}, "去向": "提示一句", "提示": "「{片段}」可能是人_e2e"},
                  {"名称": "报价交技能", "条件": {"种类": "意图", "值": "报价"}, "去向": "交给技能", "技能": "quote"}]}
    c_, d = 打("PATCH", f"/routes/{rid}/draft", {"配置": 好}, {"If-Match": str(d["revision"])})
    c5, v = 打("POST", f"/routes/{rid}/versions")
    c6, _ = 打("POST", f"/routes/{rid}/versions")
    c_, rv = 打("GET", f"/route-versions/{(v or {}).get('id')}")
    ck("③ 改好 → 冻出 v1;一字没改再冻 → 409;取版本一次给全(规则一条不少、内容哈希对得上)",
       c5 == 201 and (v or {}).get("版本") == "v1" and c6 == 409 and c_ == 200 and len(rv["配置"]["规则"]) == 4
       and rv["内容哈希"] == v["内容哈希"], (c5, v, c6, c_))
    # ④ 试一句:先建一版实体识别(客户名 业务表 / 员工名 手工),再拿术语版本
    c_, e = 打("POST", "/entity-dicts", {"key": "e2e-route-ent-" + uuid.uuid4().hex[:6], "配置": {
        "词典": [{"名称": "客户名", "类别": "客户", "来源": "业务表", "表列": "customer.name"}],
        "拿不准": {"开": True, "称呼前": ["小"], "称呼后": [], "提醒": "x"}}})
    c_, ev = 打("POST", f"/entity-dicts/{e['id']}/versions")
    c_, g = 打("POST", "/glossaries", {"key": "e2e-route-terms-" + uuid.uuid4().hex[:6]})
    打("PATCH", f"/glossaries/{g['id']}/draft", {"术语": [{"标准词": "宋锦", "叫法": [], "类别": "名词", "定义": "宋锦_e2e"},
                                                    {"标准词": "罗", "叫法": [], "类别": "名词", "定义": "罗_e2e"}]}, {"If-Match": "1"})
    c_, gv = 打("POST", f"/glossaries/{g['id']}/versions")
    c_, pv = 打("POST", f"/route-versions/{v['id']}/preview", {"文本": "宋锦书想做宋锦马面,小罗也在", "实体识别版本": ev["id"],
                                                             "术语版本": gv["id"], "试用名单": {"客户名": ["宋锦书"]}})
    走 = {x["对象"]: x["规则"] for x in (pv or {}).get("走了", [])}
    收 = (pv or {}).get("模型会收到", "")
    ck("④ 试一句:客户名走「客户先查档案」、提示进模型那段({片段} 换好)",
       c_ == 200 and 走.get("「宋锦书」(客户)") == "客户先查档案" and "「宋锦书」是客户,先查档案_e2e" in 收, (c_, 走, 收))
    ck("④ 术语被路由成「只占位」→ 不带宋锦 / 罗的定义;拿不准走歧义规则",
       "宋锦_e2e" not in 收 and "罗_e2e" not in 收 and "「罗」可能是人_e2e" in 收 and (pv or {}).get("术语命中") == [], (收, pv.get("术语命中")))
    c_, pv2 = 打("POST", f"/route-versions/{v['id']}/preview", {"文本": "帮我出个价", "意图": "报价"})
    ck("④ 手填意图「报价」→ 走「报价交技能」,返回技能 quote", c_ == 200 and pv2.get("技能") == "quote", (c_, pv2))
    try:
        with 事务() as c:
            c.execute(text("update route_versions set entries='{}'::jsonb where project_id=:p and id=:i"), {"p": 项目, "i": v["id"]})
        改得动 = True
    except Exception as ex:
        码 = getattr(getattr(ex, "orig", None), "sqlstate", None)
        改得动 = not (码 == "23514" and "route_versions" in str(ex))
        改得动 = 改得动 and f"(sqlstate={码})"
    ck("⑤ 冻结的版本在库里改不动:被触发器拒(23514、点名 route_versions)", 改得动 is False, 改得动)
    # ⑥ 聊天助手
    快 = {"角色键": "e2e_route", "名称": "路由进程内测试助手", "用途": "测试用", "开头": "你是测试助手。\n", "结尾": "",
         "工具": [{"名": "mcp__e2e__只读那个", "写": False}], "能力标记": [], "模型": "claude:claude-haiku-5-5",
         "可选模型": ["claude:claude-haiku-5-5"], "规矩池": [], "装上的规矩": [], "提示词全文": "(测试造的)", "技能": ["quote"]}
    打("POST", "/chat-assistants/import", 快, 谁="U001")
    c_, l = 打("GET", "/chat-assistants?%E5%90%AB%E6%B5%8B%E8%AF%95=true", 谁="U001")
    cid = next((x["id"] for x in (l or {}).get("items", []) if x["角色键"] == "e2e_route"), None)
    c_, g = 打("GET", f"/chat-assistants/{cid}", 谁="U001")
    配, rvn = dict(g["草稿"]["配置"]), str(g["草稿"]["revision"])
    ck("⑥ 聊天助手详情的「可选路由」列出这一版(名称 / 版本 / 条数)",
       any(x.get("id") == v["id"] and x.get("本数") == 4 for x in g.get("可选路由") or []), (g.get("可选路由") or [])[:2])
    记号 = uuid.uuid4().hex[:6]
    c0, _ = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "开头": f"你是测试助手。{记号}\n", "路由版本": None}},
               {"If-Match": rvn}, 谁="U001")
    _, nv0 = 打("POST", f"/chat-assistants/{cid}/versions", {"变更说明": "e2e 不挂路由 " + 记号}, 谁="U001")
    if nv0 and nv0.get("版本"):
        打("POST", f"/chat-assistants/{cid}/production", {"版本号": int(nv0["版本"][1:]), "理由": "e2e"}, 谁="U001")
    _, p0 = 打("GET", "/chat-assistants/by-role/e2e_route/production", 谁="U001")
    ck("⑥ 没挂路由 → 生产配置里 route_version_id 是**显式 null**", "route_version_id" in (p0 or {}) and p0["route_version_id"] is None, p0)
    _, g = 打("GET", f"/chat-assistants/{cid}", 谁="U001")
    配, rvn = dict(g["草稿"]["配置"]), str(g["草稿"]["revision"])
    c1, e1 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "route_version_id": v["id"]}}, {"If-Match": rvn}, 谁="U001")
    c7, e7 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "路由版本": "rtv_不存在的"}}, {"If-Match": rvn}, 谁="U001")
    ck("⑥ 英文键 route_version_id → 422 点名;不存在的路由版本 → 422 REF_NOT_FOUND",
       c1 == 422 and "route_version_id" in json.dumps(e1, ensure_ascii=False) and c7 == 422 and "REF_NOT_FOUND" in json.dumps(e7), (c1, c7))
    # 一版点名了助手没有的工具的路由
    c_, s2 = 打("POST", "/routes", {"key": "e2e-route-bad-" + uuid.uuid4().hex[:6], "配置": {"规则": [
        {"名称": "调一个没有的", "条件": {"种类": "实体", "值": "客户"}, "去向": "提示先调工具", "工具": "助手没有的工具_e2e"}]}})
    c_, bv = 打("POST", f"/routes/{s2['id']}/versions")
    c8, e8 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "路由版本": bv["id"]}}, {"If-Match": rvn}, 谁="U001")
    ck("⑥ 路由点名了助手没有的工具 → 422,点名那个工具(不然模型会被提示去调一个调不了的工具)",
       c8 == 422 and "助手没有的工具_e2e" in json.dumps(e8, ensure_ascii=False), (c8, e8))
    c2, _ = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "路由版本": v["id"]}}, {"If-Match": rvn}, 谁="U001")
    c3, nv = 打("POST", f"/chat-assistants/{cid}/versions", {"变更说明": "e2e 挂路由 " + uuid.uuid4().hex[:4]}, 谁="U001")
    号 = int((nv or {}).get("版本", "v-1")[1:])
    打("POST", f"/chat-assistants/{cid}/production", {"版本号": 号, "理由": "e2e"}, 谁="U001")
    c4, p3 = 打("GET", "/chat-assistants/by-role/e2e_route/production", 谁="U001")
    ck("⑥ 选「路由版本」→ 出版本 → 上生产 → 生产配置给的 route_version_id 就是这一版",
       c0 == 200 and c2 == 200 and c3 == 201 and c4 == 200 and (p3 or {}).get("route_version_id") == v["id"], (c0, c2, c3, c4, p3))
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 查询路由接口:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
