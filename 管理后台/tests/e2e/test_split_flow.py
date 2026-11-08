#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拆句与路由的接口(2026-11-08)—— 端到端,在测试进程里调接口(TestClient:咬合改坏 split_dicts_api 时在视野里)。

用户 11-08 拍「拆分词典需要有配置的地方」→「新开拆句与路由页」+「大名单实时取,小的冻版本」。

  ① 建拆句词典 → 改草稿:不带 If-Match → 拒;拿错的 revision → 409(不许最后写的人赢)
  ② 配置有阻断(类别占用「术语」、业务表列不在白名单)→ 详情的「检查」点名、冻结 422
  ③ 改好 → 冻出 v1;一字没改再冻 → 409 NO_CHANGE;**冻结的版本里业务表来源只有表列、没有名字**
  ④ 「试一句」:名字占位、术语不带;业务表那本用试用名单代替,没给试用名单的明说「没试到」;「占位并提示」的提示进模型那段
  ⑤ 冻结的版本在库里改不动(触发器)—— 断言错误码 + 表名
  ⑥ 聊天助手选这一版:英文键 split_version_id 写入当场 422;「拆句版本」→ 出版本 → 上生产 → 生产配置的 split_version_id 就是它;
     选了不存在的版本 → 422;详情的「可选拆句」列出这一版(页面下拉框从这里取);没挂时生产配置给**显式 null**
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
    key = "e2e-split-" + uuid.uuid4().hex[:6]
    c_, s = 打("POST", "/split-dicts", {"key": key})
    ck("前提:建拆句词典 201", c_ == 201 and (s or {}).get("id"), (c_, s))
    sid = s["id"]
    坏 = {"词典": [{"名称": "客户名", "类别": "术语", "来源": "业务表", "表列": "customer.phone"}]}
    c1, _ = 打("PATCH", f"/split-dicts/{sid}/draft", {"配置": 坏})
    c2, _ = 打("PATCH", f"/split-dicts/{sid}/draft", {"配置": 坏}, {"If-Match": "999"})
    ck("① 改草稿不带 If-Match → 拒;拿错的 revision → 409", c1 == 409 and c2 == 409, (c1, c2))
    c_, d = 打("PATCH", f"/split-dicts/{sid}/draft", {"配置": 坏}, {"If-Match": "1"})
    c3, _ = 打("POST", f"/split-dicts/{sid}/versions")
    阻 = (d or {}).get("检查", {}).get("阻断", [])
    ck("② 类别占用「术语」、业务表列不在白名单 → 检查点名、冻结 422",
       c_ == 200 and any("留给术语表" in x for x in 阻) and any("业务表列" in x for x in 阻) and c3 == 422, (c_, 阻, c3))
    好 = {"词典": [{"名称": "客户名", "类别": "客户", "来源": "业务表", "表列": "customer.name",
                   "命中后": "占位并提示", "提示": "「{片段}」是客户_e2e"},
                  {"名称": "员工名", "类别": "员工", "来源": "手工", "词条": ["罗一机", "江云锦"]}],
          "拿不准": {"开": True, "称呼前": ["小"], "称呼后": ["姐"], "提醒": "「{片段}」可能是人_e2e"}}
    c_, d = 打("PATCH", f"/split-dicts/{sid}/draft", {"配置": 好}, {"If-Match": str(d["revision"])})
    c5, v = 打("POST", f"/split-dicts/{sid}/versions")
    c6, _ = 打("POST", f"/split-dicts/{sid}/versions")
    ck("③ 改好 → 冻出 v1;一字没改再冻 → 409", c5 == 201 and (v or {}).get("版本") == "v1" and c6 == 409, (c5, v, c6))
    c_, sv = 打("GET", f"/split-dict-versions/{v['id']}")
    客户本 = next((x for x in (sv or {}).get("配置", {}).get("词典", []) if x.get("类别") == "客户"), {})
    ck("③ 取冻结版本一次给全(内容哈希 = 冻结时那个);业务表来源**只有表列、没有名字**(大名单不进后台)",
       c_ == 200 and sv["内容哈希"] == v["内容哈希"] and 客户本.get("表列") == "customer.name" and "词条" not in 客户本,
       (c_, 客户本))
    c_, pv = 打("POST", f"/split-dict-versions/{v['id']}/preview",
                {"文本": "宋锦书找罗一机量体,小罗也在", "试用名单": {"客户名": ["宋锦书"]}})
    段 = [(x["片段"], x["类别"]) for x in (pv or {}).get("分段", [])]
    ck("④ 试一句:客户名(试用名单)、员工名(手工词条)都占位,按出现顺序",
       c_ == 200 and 段[:2] == [("宋锦书", "客户"), ("罗一机", "员工")], (c_, 段))
    ck("④ 「占位并提示」的提示进了模型会收到的那段({片段} 换成名字)",
       "「宋锦书」是客户_e2e" in (pv or {}).get("模型会收到", ""), (pv or {}).get("模型会收到"))
    c_, pv2 = 打("POST", f"/split-dict-versions/{v['id']}/preview", {"文本": "宋锦书最近怎么样"})
    ck("④ 业务表那本没给试用名单 → 明说「没试到」(不当成「这本是空的」)",
       c_ == 200 and [x["名称"] for x in pv2.get("没试到的词典", [])] == ["客户名"], (c_, pv2))
    try:
        with 事务() as c:
            c.execute(text("update split_dict_versions set entries='{}'::jsonb where project_id=:p and id=:i"), {"p": 项目, "i": v["id"]})
        改得动 = True
    except Exception as e:
        码 = getattr(getattr(e, "orig", None), "sqlstate", None)
        改得动 = not (码 == "23514" and "split_dict_versions" in str(e))
        改得动 = 改得动 and f"(sqlstate={码})"
    ck("⑤ 冻结的版本在库里改不动:被触发器拒(错误码 23514、错误里点名 split_dict_versions)", 改得动 is False, 改得动)
    # ⑥ 聊天助手选这一版
    快 = {"角色键": "e2e_split", "名称": "拆句进程内测试助手", "用途": "测试用", "开头": "你是测试助手。\n", "结尾": "",
         "工具": [{"名": "mcp__e2e__只读那个", "写": False}], "能力标记": [], "模型": "claude:claude-haiku-5-5",
         "可选模型": ["claude:claude-haiku-5-5"], "规矩池": [], "装上的规矩": [], "提示词全文": "(测试造的)", "技能": []}
    打("POST", "/chat-assistants/import", 快, 谁="U001")
    c_, l = 打("GET", "/chat-assistants?%E5%90%AB%E6%B5%8B%E8%AF%95=true", 谁="U001")
    cid = next((x["id"] for x in (l or {}).get("items", []) if x["角色键"] == "e2e_split"), None)
    c_, g = 打("GET", f"/chat-assistants/{cid}", 谁="U001")
    配, rv = dict(g["草稿"]["配置"]), str(g["草稿"]["revision"])
    ck("⑥ 聊天助手详情的「可选拆句」列出这一版(名称 / 版本 / 本数)—— 页面下拉框从这里取",
       any(x.get("id") == v["id"] and x.get("版本") == "v1" and x.get("本数") == 2 for x in g.get("可选拆句") or []),
       (g.get("可选拆句") or [])[:2])
    # 先出一版**不挂**拆句的,上生产 → 生产配置必须给显式 null(聊天站据此「不拆」,和「字段还没上」分开)
    # 开头带一个每次不同的记号:重复跑时内容和上一轮那一版一样就出不了新版本,生产会停在上一轮挂着拆句的那版(第二次跑撞到)
    记号 = uuid.uuid4().hex[:6]
    c0, _ = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "开头": f"你是测试助手。{记号}\n", "拆句版本": None}},
               {"If-Match": rv}, 谁="U001")
    _, nv0 = 打("POST", f"/chat-assistants/{cid}/versions", {"变更说明": "e2e 不挂拆句 " + uuid.uuid4().hex[:4]}, 谁="U001")
    if nv0 and nv0.get("版本"):
        打("POST", f"/chat-assistants/{cid}/production", {"版本号": int(nv0["版本"][1:]), "理由": "e2e"}, 谁="U001")
    _, pv0 = 打("GET", "/chat-assistants/by-role/e2e_split/production", 谁="U001")
    ck("⑥ 没挂拆句 → 生产配置里 split_version_id 是**显式 null**(不是字段缺失)",
       "split_version_id" in (pv0 or {}) and pv0["split_version_id"] is None, pv0)
    _, g = 打("GET", f"/chat-assistants/{cid}", 谁="U001")
    配, rv = dict(g["草稿"]["配置"]), str(g["草稿"]["revision"])
    c1, e1 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "split_version_id": v["id"]}}, {"If-Match": rv}, 谁="U001")
    ck("⑥ 聊天助手草稿用读出口的英文键 split_version_id 来写 → 422 点名(不许静默不生效)",
       c1 == 422 and "split_version_id" in json.dumps(e1, ensure_ascii=False), (c1, e1))
    c7, e7 = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "拆句版本": "sdv_不存在的"}}, {"If-Match": rv}, 谁="U001")
    ck("⑥ 选了不存在的拆句版本 → 422 REF_NOT_FOUND", c7 == 422 and "REF_NOT_FOUND" in json.dumps(e7), (c7, e7))
    c2, _ = 打("PATCH", f"/chat-assistants/{cid}/draft", {"配置": {**配, "拆句版本": v["id"]}}, {"If-Match": rv}, 谁="U001")
    c3, nv = 打("POST", f"/chat-assistants/{cid}/versions", {"变更说明": "e2e 挂拆句 " + uuid.uuid4().hex[:4]}, 谁="U001")
    号 = int((nv or {}).get("版本", "v-1")[1:])
    打("POST", f"/chat-assistants/{cid}/production", {"版本号": 号, "理由": "e2e"}, 谁="U001")
    c4, pv3 = 打("GET", "/chat-assistants/by-role/e2e_split/production", 谁="U001")
    ck("⑥ 选「拆句版本」→ 出版本 → 上生产 → 生产配置给的 split_version_id 就是这一版(聊天站拿这个键)",
       c0 == 200 and c2 == 200 and c3 == 201 and c4 == 200 and (pv3 or {}).get("split_version_id") == v["id"], (c0, c2, c3, c4, pv3))
    # 这份词典留着不归档:页面冒烟 / If-Match 可达检查要从列表里取样例(CI 是新库)
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 拆句与路由接口:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
