#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天转人工的接口(2026-11-09)—— 端到端,打真服务。

  ① 只带服务账号、不带内部凭证 → 403;缺原话 / 缺原因 / 缺工号 → 422 且点名字段
  ② 建一条 → 201 待处理;同一轮重试 → 同一个编号,不多一条
  ③ 列表:待处理、不含原话
  ④ 详情:管理员看得到原话;没有受理权限的角色看不到
  ⑤ 处理:不带 If-Match → 409;说明为空 → 422;错 revision → 409;处理成功;再处理 → 409 ALREADY_HANDLED
  ⑥ 库约束:已处理却没有处理时间 → 库拒绝
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_opinions_flow as T  # noqa: E402  复用打接口和取内部凭证,不另写一份

项目 = os.environ.get("AIMC_PROJECT", T.项目)
P = f"/api/v1/projects/{项目}"
打, 码 = T.打, T.码
标 = "e2e-ho-" + uuid.uuid4().hex[:8]
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 体(轮, **改):
    return {"聊天站trace": 轮, "会话号": "s1", "原话": f"客户要投诉到总部 {标}", "意图": "投诉", "原因": "投诉意图按规则转人工",
            "提问人": {"工号": "E001", "姓名": "测试店长", "角色": "店长", "门店": "测试店"}, **改}


def main():
    凭, 造的 = T.凭证()
    内 = {"X-Lanxiu-Internal": 凭}
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    路 = P + "/chat-handoffs"
    try:
        print("① 通道与字段")
        c, b = 打("POST", 路, 体(标 + "-0"))
        ck("不带内部凭证 → 403 INTERNAL_ONLY", c == 403 and 码(b) == "INTERNAL_ONLY", (c, b))
        for 字, 改 in (("原话", {"原话": " "}), ("原因", {"原因": None}), ("提问人", {"提问人": {}})):
            c, b = 打("POST", 路, 体(标 + "-0", **改), 内)
            ck(f"缺{字} → 422 且点名", c == 422 and 字 in str(b), (c, b))

        print("② 建一条、同一轮防重")
        c, b = 打("POST", 路, 体(标 + "-1"), 内)
        ck("建 → 201 待处理", c == 201 and b.get("status") == "待处理", (c, b))
        编号 = (b or {}).get("id")
        c, b2 = 打("POST", 路, 体(标 + "-1"), 内)
        ck("同一轮重试 → 同一个编号", b2.get("id") == 编号, (c, b2))
        with 库.connect() as k:
            n = k.execute(text("select count(*) from chat_handoffs where chat_trace_ref=:t"), {"t": 标 + "-1"}).scalar()
        ck("库里只有一条", n == 1, n)

        print("③ 列表")
        c, b = 打("GET", 路 + "?status=待处理&page_size=100")
        行 = [x for x in (b or {}).get("items", []) if x["id"] == 编号]
        ck("列表里有它,待处理", c == 200 and len(行) == 1 and 行[0]["status"] == "待处理", (c, b))
        ck("列表不含原话", 标 not in str(b), 行)
        c, b = 打("GET", 路 + "?status=乱写")
        ck("非法状态 → 422", c == 422, (c, b))

        print("④ 详情与原话权限")
        详 = P + f"/chat-handoffs/{编号}"
        c, b = 打("GET", 详)
        ck("管理员看得到原话", c == 200 and 标 in str(b.get("question_note")) and b.get("原话看得到吗") is True, (c, b))
        rev = b.get("revision")
        看不到 = os.environ.get("AIMC_VIEWER", "U003")
        c, b = 打("GET", 详, 谁=看不到)
        ck("没有受理权限的角色看不到原话", c == 200 and b.get("question_note") is None and b.get("原话看得到吗") is False, (c, b))

        print("⑤ 处理")
        办 = 详 + "/resolve"
        c, b = 打("POST", 办, {"说明": "已电话联系"})
        ck("不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 打("POST", 办, {"说明": " "}, {"If-Match": str(rev)})
        ck("说明为空 → 422", c == 422, (c, b))
        c, b = 打("POST", 办, {"说明": "已电话联系"}, {"If-Match": "999"})
        ck("错 revision → 409", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        c, b = 打("POST", 办, {"说明": "已电话联系"}, {"If-Match": str(rev)})
        ck("处理成功", c == 200 and b.get("status") == "已处理", (c, b))
        c, b = 打("POST", 办, {"说明": "再来一次"}, {"If-Match": str(rev + 1)})
        ck("再处理 → 409 ALREADY_HANDLED", c == 409 and 码(b) == "ALREADY_HANDLED", (c, b))

        print("⑥ 库约束")
        try:
            with 库.begin() as k:
                k.execute(text("update chat_handoffs set handled_at=null where id=:i"), {"i": 编号})
            ck("已处理却没有处理时间 → 库拒绝", False, "写进去了")
        except Exception as e:
            ck("已处理却没有处理时间 → 库拒绝", "ck_chat_handoffs_handled" in str(e), e)
    finally:
        with 库.begin() as k:
            k.execute(text("delete from chat_handoffs where chat_trace_ref like :t"), {"t": 标 + "%"})
        if 造的:
            造的()
    print(f"\n{len(过)} 过 / {len(挂)} 挂")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
