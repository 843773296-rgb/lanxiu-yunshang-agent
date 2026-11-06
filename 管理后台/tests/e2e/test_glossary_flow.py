#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语配置 / 语义层的接口(2026-11-06)—— 端到端,在测试进程里调接口(TestClient:咬合改坏 glossaries_api 时在视野里)。

  ① 建术语表 → 改草稿:不带 If-Match → 拒;拿错的 revision → 409(不许最后写的人赢)
  ② 格式有阻断(指标没写口径)→ 冻结 422,详情里的「检查」点名;取数口写了不存在的工具 → 冻结 422(算法以代码为准,说明里的工具得真在)
  ③ 改好 → 冻出 v1;一字没改再冻 → 409 NO_CHANGE
  ④ 「试一下」:只返回这次提到的那几条(用户拍:只带这次提到的),模型会收到的那段里没有没提到的术语
  ⑤ 冻结的版本在库里改不动(版本行不可原地改的触发器)—— 断言错误码 + 表名,不断言中文文案
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
