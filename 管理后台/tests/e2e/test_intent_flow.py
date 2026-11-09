#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图识别的接口(2026-11-09 第三期)—— 端到端,在测试进程里调接口。

  ① 改草稿:不带 If-Match → 拒;拿错的 revision → 409
  ② 没说明 / 占用「判不出」→ 检查点名、冻结 422
  ③ 改好 → 冻出 v1;一字没改再冻 → 409;取版本一次给全
  ④ 试一句:返回模型会收到的分类提示,含意图说明和店长原话(不调模型)
  ⑤ 冻结的版本在库里改不动(触发器)
  ⑥ 聊天助手:英文键 422、不存在 422、没挂时生产配置给显式 null、挂上后 intent_version_id 就是它、详情列出这一版
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
    c_, s = 打("POST", "/intents", {"key": "e2e-intent-" + uuid.uuid4().hex[:6]})
    ck("前提:建意图配置 201", c_ == 201 and (s or {}).get("id"), (c_, s))
    sid = s["id"]
    坏 = {"意图": [{"名称": "判不出", "说明": ""}]}
    c1, _ = 打("PATCH", f"/intents/{sid}/draft", {"配置": 坏})
    c2, _ = 打("PATCH", f"/intents/{sid}/draft", {"配置": 坏}, {"If-Match": "999"})
    ck("① 不带 If-Match → 拒;错的 revision → 409", c1 == 409 and c2 == 409, (c1, c2))
    c_, d = 打("PATCH", f"/intents/{sid}/draft", {"配置": 坏}, {"If-Match": "1"})
    c3, _ = 打("POST", f"/intents/{sid}/versions")
    阻 = (d or {}).get("检查", {}).get("阻断", [])
    ck("② 占用「判不出」/ 没说明 → 点名、冻结 422", any("留给" in x for x in 阻) and any("没有说明" in x for x in 阻) and c3 == 422, (阻, c3))
    好 = {"意图": [{"名称": "报价", "说明": "要出报价单_e2e", "例句": ["出个报价"]}, {"名称": "问知识", "说明": "形制面料", "例句": ["宋锦是什么"]}]}
    c_, d = 打("PATCH", f"/intents/{sid}/draft", {"配置": 好}, {"If-Match": str(d["revision"])})
    c5, v = 打("POST", f"/intents/{sid}/versions")
    c6, _ = 打("POST", f"/intents/{sid}/versions")
    c_, iv = 打("GET", f"/intent-versions/{(v or {}).get('id')}")
    ck("③ 冻出 v1;再冻 409;取版本一次给全", c5 == 201 and v.get("版本") == "v1" and c6 == 409 and len(iv["配置"]["意图"]) == 2 and iv["内容哈希"] == v["内容哈希"], (c5, c6))
    c_, pv = 打("POST", f"/intent-versions/{v['id']}/preview", {"文本": "这套多少钱_e2e"})
    ck("④ 试一句:提示里有意图说明和店长原话", c_ == 200 and "要出报价单_e2e" in pv["系统提示"] and "这套多少钱_e2e" in pv["用户消息"], (c_, pv))
    try:
        with 事务() as c:
            c.execute(text("update intent_versions set entries='{}'::jsonb where project_id=:p and id=:i"), {"p": 项目, "i": v["id"]})
        改得动 = True
    except Exception as ex:
        码 = getattr(getattr(ex, "orig", None), "sqlstate", None)
        改得动 = not (码 == "23514" and "intent_versions" in str(ex))
    ck("⑤ 冻结的版本改不动(23514、点名 intent_versions)", 改得动 is False, 改得动)
    快 = {"角色键": "e2e_intent", "名称": "意图测试助手", "用途": "测试用", "开头": "你是测试助手。\n", "结尾": "",
         "工具": [{"名": "mcp__e2e__只读那个", "写": False}], "能力标记": [], "模型": "claude:claude-haiku-5-5",
         "可选模型": ["claude:claude-haiku-5-5"], "规矩池": [], "装上的规矩": [], "提示词全文": "(测试造的)", "技能": []}
    打("POST", "/chat-assistants/import", 快, 谁="U001")
    _, l = 打("GET", "/chat-assistants?%E5%90%AB%E6%B5%8B%E8%AF%95=true", 谁="U001")
    cid = next(x["id"] for x in l["items"] if x["角色键"] == "e2e_intent")
    def 取():
        _, g = 打("GET", f"/chat-assistants/{cid}", 谁="U001")
        return g, dict(g["草稿"]["配置"]), {"If-Match": str(g["草稿"]["revision"])}
    def 上线(配, 头, 话):
        c, _ = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": 配}, 头, 谁="U001")
        _, nv = 打("POST", f"/chat-assistants/{cid}/versions", {"变更说明": 话}, 谁="U001")
        打("POST", f"/chat-assistants/{cid}/production", {"版本号": int(nv["版本"][1:]), "理由": "e2e"}, 谁="U001")
        return c
    g, 配, 头 = 取()
    ck("⑥ 详情「可选意图」列出这一版", any(x.get("id") == v["id"] and x.get("本数") == 2 for x in g.get("可选意图") or []), g.get("可选意图"))
    记 = uuid.uuid4().hex[:6]
    上线({**配, "开头": f"你是测试助手。{记}\n", "意图版本": None}, 头, "不挂 " + 记)
    _, p0 = 打("GET", "/chat-assistants/by-role/e2e_intent/production", 谁="U001")
    ck("⑥ 没挂 → intent_version_id 显式 null", "intent_version_id" in p0 and p0["intent_version_id"] is None, p0)
    g, 配, 头 = 取()
    c1, e1 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "intent_version_id": v["id"]}}, 头, 谁="U001")
    c2, e2 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "意图版本": "itv_不存在的"}}, 头, 谁="U001")
    ck("⑥ 英文键 422;不存在 422 REF_NOT_FOUND", c1 == 422 and c2 == 422 and "REF_NOT_FOUND" in json.dumps(e2), (c1, c2))
    c3 = 上线({**配, "意图版本": v["id"]}, 头, "挂意图 " + 记)
    _, p1 = 打("GET", "/chat-assistants/by-role/e2e_intent/production", 谁="U001")
    ck("⑥ 选了 → 上生产 → intent_version_id 就是这一版", c3 == 200 and p1.get("intent_version_id") == v["id"], (c3, p1))
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 意图识别接口:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
