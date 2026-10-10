#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**产出监督**(报告 / agent 建议:看 + 打回)—— 在真 PG 上、走真接口验。用户 2026-10-10。

## 这一组每一条对着一种「看起来对了而实际漏了」

   ① 重复上报记成两条 → 打回挂在其中一条上,另一条在列表里显示「正常」
   ② 类型拼错照收 → 自成一档,筛选时哪档都不算(看起来就是没有)
   ③ 状态存成一列 → 决定改了而状态没跟着改;所以状态由最近一条决定**推出来**,这里验推得对
   ④ 两条待执行的打回 → 澜绣重写两次,第二次覆盖第一次
   ⑤ 确认过的还能再确认 → 「已执行」被改成「执行失败」,历史被改写
   ⑥ 调用链找不到时编一个 / 静默给空 → 找得到给号,找不到说为什么
   ⑦ 发送方漏了手机号 → 入库前打码,并把「打了几处」记下来让人看见

## ⚠️ 为什么不能 rollback

测的是接口(TestClient → 路由函数自己开连接),看不到我的事务。
所以 try/finally 清理 + 收尾断言「库里一条都没留下」。
> 一次「清干净了」和一次「中途炸了、finally 之前就炸」,在那次失败的输出上长得一模一样。
"""
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))
os.chdir(os.path.join(ROOT, "services", "api", "app"))

from fastapi.testclient import TestClient   # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
import main                                  # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)
cl = TestClient(main.app)
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("=" * 92)
print("产出监督 · 上报 / 列表 / 详情 / 打回 → 拉取 → 确认(真 PG、真接口)")
print("=" * 92)

with eng.connect() as c:
    行 = c.execute(text("""select m.project_id, m.user_id from memberships m
                          where m.status='active' and m.role='admin' and m.project_id is not null
                          order by m.project_id, m.user_id limit 1""")).first()
P, U = 行[0], 行[1]
# 一个没有「改训练样本」的角色:viewer / approver(都默认否)
with eng.connect() as c:
    无权 = c.execute(text("""select m.user_id from memberships m
                           where m.status='active' and m.project_id=:p and m.role in ('viewer','approver')
                           limit 1"""), {"p": P}).scalar()
H = {"X-Dev-User": U}
基 = f"/api/v1/projects/{P}"
标 = f"测试:{uuid.uuid4().hex[:8]}"
外trace有 = f"lxtest{uuid.uuid4().hex[:16]}"
外trace无 = f"lxtest{uuid.uuid4().hex[:16]}"
造的trace = f"tr_t{uuid.uuid4().hex[:10]}"
print(f"项目 {P} · 身份 {U} · 本轮外部id前缀 {标}\n")


def 报(外部id, 版本=1, 键=None, **改):
    体 = {"外部id": 外部id, "类型": "建议", "版本": 版本, "标题": "上新建议 · 测试",
          "门店": "SH001", "世界日期": "2026-10-10", "模型": "claude-haiku-4-5",
          "生成方式": "模型", "规则": [{"编号": "建议提示", "正文": "材料外一个字都不写"}],
          "输入": {"当初原话": "想要月白色", "客户": "陈女士"}, "输出": "1. 先提她当初说的话",
          "外部trace": 外trace有}
    体.update(改)
    return cl.post(基 + "/artifacts", json=体,
                   headers={**H, "Idempotency-Key": 键 or f"k-{uuid.uuid4().hex}"})


try:
    # 造一条「A1 推过来的调用」:trace + span,span 的 input_ref 里带外部trace —— 和 knowledge_api 的接收端同一个位置
    with eng.begin() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": P}).scalar()
        c.execute(text("""insert into traces (id, organization_id, project_id, request_id, environment,
                          started_at, ended_at, end_reason, created_at, created_by)
                          values (:i,:o,:p,:rq,'test',now(),now(),'completed',now(),:u)"""),
                  {"i": 造的trace, "o": org, "p": P, "rq": f"rq-{造的trace}", "u": U})
        c.execute(text("""insert into spans (id, organization_id, project_id, trace_id, stage, input_ref,
                          started_at, ended_at, created_at, created_by)
                          values (:i,:o,:p,:t,'generate', cast(:ir as jsonb), now(), now(), now(), :u)"""),
                  {"i": f"sp_t{uuid.uuid4().hex[:10]}", "o": org, "p": P, "t": 造的trace,
                   "ir": '{"调用方": "测试", "外部trace": "%s"}' % 外trace有, "u": U})

    # ① 幂等
    r1 = 报(f"{标}:A", 键="k-same-1")
    r2 = 报(f"{标}:A", 键="k-other-2")
    ck("新上报 → 201、记了", r1.status_code == 201 and r1.json().get("记了吗") is True, r1.text)
    ck("同一份同一版再报 → 返回原记录,不记第二条",
       r2.status_code == 200 and r2.json().get("记了吗") is False and r2.json().get("id") == r1.json().get("id"), r2.text)
    A = r1.json()["id"]
    r没键 = cl.post(基 + "/artifacts", json={"外部id": "x"}, headers=H)
    ck("没带 Idempotency-Key → 409", r没键.status_code == 409, r没键.text)

    # ② 字段
    r坏 = 报(f"{标}:坏", 类型="周报", 版本=0, 规则="不是列表", 世界日期="10月10日", 输出="")
    fe = (r坏.json().get("field_errors") or {}) if r坏.status_code == 422 else {}   # 错误信封:field_errors 在顶层
    ck("字段不合格 → 422,并逐个点名(类型 / 版本 / 规则 / 世界日期 / 输出)",
       r坏.status_code == 422 and {"类型", "版本", "规则", "世界日期", "输出"} <= set(fe), r坏.text)
    r大 = 报(f"{标}:大", 输入={"x": "字" * 100000})
    ck("输入超过 256KB → 422", r大.status_code == 422, r大.status_code)

    # ⑦ 手机号打码
    r码 = 报(f"{标}:码", 输入={"电话": "13812345678"}, 输出="打给 13912345678")
    详码 = cl.get(基 + f"/artifacts/{r码.json()['id']}", headers=H).json()
    ck("发送方漏了手机号 → 入库前打码,并记下打了几处",
       "13812345678" not in str(详码) and "138****5678" in str(详码["输入"])
       and 详码["入库时打码了几处手机号"] == 2 and "打码" in r码.json(), str(详码.get("输入")))

    # ⑥ 调用链:找得到 / 找不到
    详 = cl.get(基 + f"/artifacts/{A}", headers=H).json()
    ck("关联调用链:找得到 → 给管理后台自己的 trace 号", 详["关联调用链"]["trace_id"] == 造的trace, 详["关联调用链"])
    r无 = 报(f"{标}:B", 外部trace=外trace无)
    详无 = cl.get(基 + f"/artifacts/{r无.json()['id']}", headers=H).json()
    ck("关联调用链:找不到 → null,并说为什么(不编一个)",
       详无["关联调用链"]["trace_id"] is None and "还没推过来" in 详无["关联调用链"]["说明"], 详无["关联调用链"])

    # ③ 状态推导:正常 → 已打回待执行 → 已执行
    def 状态(i):
        return cl.get(基 + f"/artifacts/{i}", headers=H).json()["状态"]
    ck("还没有决定 → 正常", 状态(A) == "正常")
    if 无权:
        r拒 = cl.post(基 + f"/artifacts/{A}/reject", json={"理由": "没有权限的人来打回"},
                      headers={"X-Dev-User": 无权})
        ck("没有「改训练样本」的角色打回 → 403", r拒.status_code == 403, r拒.status_code)
    r短 = cl.post(基 + f"/artifacts/{A}/reject", json={"理由": "不行"}, headers=H)
    ck("理由不到 4 个字 → 422", r短.status_code == 422, r短.text)
    r打 = cl.post(基 + f"/artifacts/{A}/reject", json={"理由": "编了商品名里没有的面料"}, headers=H)
    ck("打回 → 201、待执行", r打.status_code == 201 and r打.json().get("状态") == "待执行", r打.text)
    D = r打.json().get("id")
    ck("打回之后状态推成「已打回待执行」", 状态(A) == "已打回待执行")
    列 = cl.get(基 + "/artifacts", params={"状态": "已打回待执行", "类型": "建议"}, headers=H).json()
    ck("列表按状态筛:这一条在里面,带着最近打回理由",
       any(x["id"] == A and x["最近打回理由"] == "编了商品名里没有的面料" for x in 列["items"])
       and 列["total"] == 列["总数"] and 列["rows"] == 列["items"], str(列)[:160])
    正常列 = cl.get(基 + "/artifacts", params={"状态": "正常"}, headers=H).json()
    ck("列表按状态筛:「正常」里不再有它", not any(x["id"] == A for x in 正常列["items"]))

    # ④ 重复打回
    r再 = cl.post(基 + f"/artifacts/{A}/reject", json={"理由": "再打回一次看看"}, headers=H)
    ck("已有待执行的打回再打回 → 409", r再.status_code == 409, r再.text)

    # 拉取
    拉 = cl.get(基 + "/artifact-decisions", params={"状态": "待执行"}, headers=H).json()
    ck("澜绣拉取:待执行里有这一条,带外部id / 版本 / 理由",
       any(x["id"] == D and x["外部id"] == f"{标}:A" and x["版本"] == 1 and x["理由"] for x in 拉["rows"]),
       str(拉)[:160])

    # 确认 → 已执行;⑤ 再确认 409
    r新 = 报(f"{标}:A", 版本=2)
    rk = cl.post(基 + f"/artifact-decisions/{D}/ack", json={"结果": "已重写", "新版本": 2}, headers=H)
    ck("确认 → 已执行", rk.status_code == 200 and rk.json().get("状态") == "已执行", rk.text)
    ck("确认之后状态推成「已执行」", 状态(A) == "已执行")
    rk2 = cl.post(基 + f"/artifact-decisions/{D}/ack", json={"结果": "执行失败"}, headers=H)
    ck("确认过的再确认 → 409(不许改写历史)", rk2.status_code == 409, rk2.text)
    rk坏 = cl.post(基 + f"/artifact-decisions/{D}/ack", json={"结果": "改好了"}, headers=H)
    ck("确认的结果不在词表里 → 422", rk坏.status_code == 422, rk坏.status_code)
    详2 = cl.get(基 + f"/artifacts/{A}", headers=H).json()
    ck("详情:版本历史有 1 和 2,打回历史记着结果和新版本",
       [v["版本"] for v in 详2["版本们"]] == [1, 2]
       and 详2["打回历史"][0]["结果"] == "已重写" and 详2["打回历史"][0]["新版本"] == 2, str(详2["打回历史"])[:160])
    ck("新版本自己是「正常」(打回针对的是那一版,不是这份产出)", 状态(r新.json()["id"]) == "正常")

    # 执行失败那条路
    r打2 = cl.post(基 + f"/artifacts/{r无.json()['id']}/reject", json={"理由": "数字和取数包对不上"}, headers=H)
    cl.post(基 + f"/artifact-decisions/{r打2.json()['id']}/ack", json={"结果": "执行失败", "说明": "模型没跑通"}, headers=H)
    ck("确认执行失败 → 状态推成「执行失败」", 状态(r无.json()["id"]) == "执行失败")

    # ④ 库层兜底:绕过接口直接插第二条待执行,部分唯一索引要拦住
    r打3 = cl.post(基 + f"/artifacts/{r码.json()['id']}/reject", json={"理由": "测一下库层兜底"}, headers=H)
    拦了 = False
    try:
        with eng.begin() as c:
            c.execute(text("""insert into artifact_decisions (id, organization_id, project_id, artifact_id,
                              action, reason, status, created_at, created_by, updated_at, revision)
                              values ('dec_t_dup', :o, :p, :a, '打回', '绕过接口', '待执行', now(), :u, now(), 1)"""),
                      {"o": org, "p": P, "a": r码.json()["id"], "u": U})
    except Exception:
        拦了 = True
    ck("库层:同一份产出第二条待执行的打回插不进去(两个人同时点也挡得住)", 拦了)
finally:
    with eng.begin() as c:
        ids = [r[0] for r in c.execute(text("select id from artifacts where project_id=:p and external_ref like :x"),
                                       {"p": P, "x": f"{标}%"})]
        if ids:
            c.execute(text("delete from artifact_decisions where project_id=:p and artifact_id = any(:a)"),
                      {"p": P, "a": ids})
            c.execute(text("delete from artifacts where project_id=:p and id = any(:a)"), {"p": P, "a": ids})
        c.execute(text("delete from spans where project_id=:p and trace_id=:t"), {"p": P, "t": 造的trace})
        c.execute(text("delete from traces where project_id=:p and id=:t"), {"p": P, "t": 造的trace})

with eng.connect() as c:
    剩 = c.execute(text("select count(*) from artifacts where project_id=:p and external_ref like :x"),
                   {"p": P, "x": f"{标}%"}).scalar()
    剩链 = c.execute(text("select count(*) from traces where id=:t"), {"t": 造的trace}).scalar()
ck("收尾:库里一条测试数据都没留下", 剩 == 0 and 剩链 == 0, f"产出 {剩} · trace {剩链}")

print()
print(f"{'✅' if not 挂 else '❌'} 过 {len(过)} 条 · 挂 {len(挂)} 条")
sys.exit(1 if 挂 else 0)
