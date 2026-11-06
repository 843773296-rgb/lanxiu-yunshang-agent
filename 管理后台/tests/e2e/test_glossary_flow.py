#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语配置 / 语义层的接口(2026-11-06)—— 端到端,在测试进程里调接口(TestClient:咬合改坏 glossaries_api 时在视野里)。

  ① 建术语表 → 改草稿:不带 If-Match → 拒;拿错的 revision → 409(不许最后写的人赢)
  ② 格式有阻断(指标没写口径)→ 冻结 422,详情里的「检查」点名;取数口写了不存在的工具 → 冻结 422(算法以代码为准,说明里的工具得真在)
  ③ 改好 → 冻出 v1;一字没改再冻 → 409 NO_CHANGE
  ④ 「试一下」:只返回这次提到的那几条(用户拍:只带这次提到的),模型会收到的那段里没有没提到的术语
  ⑤ 冻结的版本在库里改不动(版本行不可原地改的触发器)—— 断言错误码 + 表名,不断言中文文案
  ⑥ 工作流开始节点选这一版 → 模型步骤只带这一步提到的术语(事件 glossary.injected);没提到不带;选了不存在的版本校验拦
"""
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


def 跑工作流(术语版本):
    """建一条 开始 → 模型(演示连接)→ 结束 的工作流,开始节点选术语版本;跑两次(提到 / 没提到术语),返回每次 glossary.injected 带了什么。"""
    import subprocess
    import time
    # 要带「模板: 文本处理」—— 不带模板建出来只有 开始 / 结束 两个节点,没有模型步骤,
    # 于是下面那个 for 一个 llm 都改不到、运行被校验挡在门外(11-06 第一次跑就栽在这,事件为空而 ❌ 什么都没印)
    c_, w = 打("POST", "/workflows", {"名称": f"e2e 术语注入 {uuid.uuid4().hex[:6]}", "模板": "文本处理"})
    wid = w["id"]
    c_, d = 打("GET", f"/workflows/{wid}")
    if not any(n["type"] == "llm" for n in d["草稿"]["定义"]["nodes"]):
        return "前提不成立:模板里没有模型步骤", None, []
    定义 = d["草稿"]["定义"]
    for n in 定义["nodes"]:
        if n["type"] == "llm":
            n["config"]["connection_version_id"] = "cv_mock_" + 项目
            n["config"]["prompt_version_id"] = "pv_seed_article_summary"
        if n["type"] == "start":
            n["config"]["glossary_version_id"] = 术语版本
    打("PATCH", f"/workflows/{wid}/draft", {"定义": 定义}, {"If-Match": str(d["草稿"]["revision"])})
    结果 = []
    for 文 in ("上周到店转化怎么样,帮我总结一下", "今天天气不错,帮我总结一下"):
        c_, r = 打("POST", "/execution-runs", {"workflow_id": wid, "输入": {"article": 文}}, {"Idempotency-Key": str(uuid.uuid4())})
        rid = (r or {}).get("resource_id")
        if not rid:   # 运行没建起来 ≠ 跑了但没带术语 —— 分开报,否则 ❌ 后面是空的(第二条「没提到不带」还会因为空列表误绿)
            结果.append(f"运行没建起来:{c_} {str(r)[:200]}")
            continue
        for _ in range(10):
            with 事务() as c:
                st = c.execute(text("select status from execution_runs where project_id=:p and id=:i"), {"p": 项目, "i": rid}).scalar()
            if st in ("succeeded", "failed", "incomplete"):
                break
            subprocess.run([os.path.join(根, ".venv", "bin", "python"), os.path.join(根, "workers", "worker.py"), "--一轮"],
                           capture_output=True, timeout=180, cwd=根)
            time.sleep(0.3)
        with 事务() as c:
            结果.append([x["带了"] for x in c.execute(text("""select payload from run_events where project_id=:p and execution_run_id=:r
                                                           and event_type='glossary.injected'"""), {"p": 项目, "r": rid}).scalars()])
    坏 = [dict(n) for n in 定义["nodes"]]
    for n in 坏:
        if n["type"] == "start":
            n["config"] = dict(n["config"], glossary_version_id="glv_不存在的")
    c_, d2 = 打("GET", f"/workflows/{wid}")
    打("PATCH", f"/workflows/{wid}/draft", {"定义": dict(定义, nodes=坏)}, {"If-Match": str(d2["草稿"]["revision"])})
    c_, b = 打("POST", f"/workflows/{wid}/validate")
    # 收尾:草稿改回选**存在的**那一版。这条工作流有跑成功的运行,别的 e2e(test_fingerprint_ratchet / test_runctl_page_actions)
    # 拿「演示项目里最近一条跑成功的草稿运行 / 列表第一条工作流」当夹具 —— 留着一个坏引用,它们受理时 422、红在跟它们无关的地方(11-06 撞过)
    c_, d3 = 打("GET", f"/workflows/{wid}")
    打("PATCH", f"/workflows/{wid}/draft", {"定义": 定义}, {"If-Match": str(d3["草稿"]["revision"])})
    return 结果[0], 结果[1], [p["code"] for p in (b or {}).get("问题", []) if p.get("级别") == "blocking"]


def main():
    with 事务() as c:
        工具 = c.execute(text("select name from tool_definitions where project_id=:p and status='active' order by name limit 1"),
                       {"p": 项目}).scalar()
    key = "e2e-terms-" + uuid.uuid4().hex[:6]
    c_, g = 打("POST", "/glossaries", {"key": key})
    ck("前提:建术语表 201", c_ == 201 and g.get("id"), (c_, g))
    gid = g["id"]
    坏 = [{"标准词": "到店率", "叫法": ["到店转化"], "类别": "指标", "定义": "预约里真到店的比例"}]
    c1, _ = 打("PATCH", f"/glossaries/{gid}/draft", {"术语": 坏})
    c2, _ = 打("PATCH", f"/glossaries/{gid}/draft", {"术语": 坏}, {"If-Match": "999"})
    ck("① 改草稿不带 If-Match → 拒;拿错的 revision → 409", c1 == 409 and c2 == 409, (c1, c2))
    c_, d = 打("PATCH", f"/glossaries/{gid}/draft", {"术语": 坏}, {"If-Match": "1"})
    c3, b = 打("POST", f"/glossaries/{gid}/versions")
    ck("② 指标没写口径 → 详情的「检查」点名、冻结 422", c_ == 200 and any("口径" in x for x in d["检查"]["阻断"])
       and c3 == 422, (c_, d.get("检查"), c3))
    带工具 = [dict(坏[0], 口径={"分子": "到店的预约", "分母": "预约(不含已取消)"}, 取数口={"工具": "不存在的工具_e2e"}),
              {"标准词": "褙子", "叫法": ["褙", "长褙"], "类别": "名词", "定义": "宋制对襟长衣"}]
    c_, d = 打("PATCH", f"/glossaries/{gid}/draft", {"术语": 带工具}, {"If-Match": str(d["revision"])})
    c4, b = 打("POST", f"/glossaries/{gid}/versions")
    ck("② 取数口写了这个项目里不存在的工具 → 冻结 422,点名那个工具", c4 == 422 and "不存在的工具_e2e" in str(b), (c4, b))
    好 = [dict(带工具[0], 取数口={"工具": 工具}), 带工具[1]]
    c_, d = 打("PATCH", f"/glossaries/{gid}/draft", {"术语": 好}, {"If-Match": str(d["revision"])})
    c5, v = 打("POST", f"/glossaries/{gid}/versions")
    c6, _ = 打("POST", f"/glossaries/{gid}/versions")
    ck("③ 改好 → 冻出 v1;一字没改再冻 → 409", c5 == 201 and v.get("版本") == "v1" and c6 == 409, (c5, v, c6))
    c_, pv = 打("POST", f"/glossary-versions/{v['id']}/preview", {"文本": "上周到店转化怎么样"})
    ck("④ 试一下:只返回这次提到的「到店率」,模型会收到的那段里没有「褙子」",
       c_ == 200 and [h["标准词"] for h in pv["命中"]] == ["到店率"] and "褙子" not in pv["模型会收到"] and "不含已取消" in pv["模型会收到"],
       (c_, pv))
    c_, gv = 打("GET", f"/glossary-versions/{v['id']}")
    ck("④ 取一个冻结版本一次给全:内容哈希 = 冻结时那个、术语一条不少、带项目和冻结时间(聊天站本地缓存用)",
       c_ == 200 and gv["内容哈希"] == v["内容哈希"] and len(gv["术语"]) == 2 and gv["项目"] == 项目 and gv["冻结于"], (c_, gv))
    try:
        with 事务() as c:
            c.execute(text("update glossary_versions set entries='[]'::jsonb where project_id=:p and id=:i"), {"p": 项目, "i": v["id"]})
        改得动 = True
    except Exception as e:
        # 认**错误码 + 表名**,不认中文文案(并行会话 11-06 指出:文案最容易被顺手改,改了之后有人会把断言放宽成
        # 两种错都能匹配的子串,又退回「拦住了但理由不对」)。触发器 raise ... using errcode = 'check_violation' = 23514
        码 = getattr(getattr(e, "orig", None), "sqlstate", None)
        改得动 = not (码 == "23514" and "glossary_versions" in str(e))
        改得动 = 改得动 and f"(sqlstate={码})"
    ck("⑤ 冻结的版本在库里改不动:被触发器拒(错误码 23514 check_violation、错误里点名 glossary_versions)", 改得动 is False, 改得动)
    # ⑥ 工作流选用这一版术语(开始节点配置 glossary_version_id,用户拍「每条工作流选一版」)→ 模型步骤带上这一步提到的
    带, 不带, 校 = 跑工作流(v["id"])
    ck("⑥ 工作流开始节点选了这一版:输入提到「到店转化」的那一次,模型步骤带了「到店率」、没带「褙子」(事件 glossary.injected)",
       带 == [["到店率"]], repr(带))
    ck("⑥ 输入一个术语都没提到 → 不带任何术语(不记事件)", 不带 == [], repr(不带))
    ck("⑥ 开始节点选了一个不存在的术语版本 → 校验当场拦(REF_NOT_FOUND)", "REF_NOT_FOUND" in 校, repr(校))
    # 这张术语表**留着不归档**:tools/ifmatch_reachable_check 要从术语表列表里取一张样例,验「界面拿得到改草稿要带的 revision」——
    # CI 是新库,这一条要是归档了,那条检查拿不到样例就判红(而那条红的理由是「什么都没验到」,是对的)
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 术语配置接口:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
