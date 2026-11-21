#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标注回复 · 后台一半 · 端到端(11-21;用户 10-27 拍第 7 条,11-21 拍三条口径)。真服务 + 真库,聊天站那一侧由测试扮演(推 trace、拉清单、报命中)。
  ① 运行详情带「标注」块:只调知识类工具的一轮 → 可以标;调过 get_order 的一轮 → 不可以,原因点名工具;非聊天站的运行没有这块
  ② 总开关默认关:列表带 开关=false;给聊天站的清单空、开关=false
  ③ 建:取数那一轮 422 CHAT_ANNOTATION_REALTIME;没「改 Prompt/知识候选」的 403;有权限但看不到原文的 403;原文到期的 422;
     合格的 201(提问 / 角色 / 工具清单从 trace 取,不信调用方);同一轮再标 409;缺字段 422;不存在的 trace 404
  ④ 列表:看得到原文的见提问;看不到的只见长度;运行详情「已有」指向这条
  ⑤ 开关:editor 能拨;拨完清单给全文、留审计;没「运行评测」的拿不到清单(403)
  ⑥ 命中:上报两次 → hit_count 2
  ⑦ 改:不带 If-Match 409;旧 revision 409;对的 → revision+1;停用后清单里没有、命中 404;再启用
  ⑧ 归档:列表 / 清单 / 命中都没了;运行详情回到「可以标」;同一轮再标 → 把那条起回来(同 id)
  ⑨ 收尾:开关关回去、标注归档;临时成员由 _清成员 删
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _清成员 as 成员  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:260]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U001", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法, data=json.dumps(体).encode() if 体 is not None else None)
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


def 导(体):
    return 打("POST", P + "/trace-imports", "U001", 体=体)


def 步(sid, parent=None, stage="execute_tool kb_read", 入=None, 出=None, 开始=None):
    return {"id": sid, "parent": parent, "stage": stage, "开始": 开始 or time.time(), "结束": time.time(), "状态": "unset", "入": 入, "出": 出}


def 一轮(工具们, 提问="香云纱能不能机洗?", 回答="不能机洗。香云纱只能手洗、阴干,见工艺手册。", 开始=None):
    外 = "e2eann" + uuid.uuid4().hex[:10]
    步们 = [步("root", stage="invoke_agent 门店顾问", 入={"提问": 提问, "角色": "门店顾问"}, 出={"回答": 回答}, 开始=开始)]
    步们 += [步(f"t{i}", "root", stage=f"execute_tool {t}", 入={"参数": "{}"}, 出={"返回": "…"}, 开始=开始) for i, t in enumerate(工具们)]
    c, r = 导({"外部trace": 外, "会话号": "会话-ann", "状态": "unset", "开始": 开始 or time.time() - 3, "结束": 开始 or time.time(), "步们": 步们})
    assert c == 201, (c, r)
    return r["trace_id"]


尾 = uuid.uuid4().hex[:6].upper()
甲 = 成员.记(项目, f"E2EANA{尾}")   # admin + 查看敏感输入:能标
乙 = 成员.记(项目, f"E2EANE{尾}")   # editor 没原文授权:有「改 Prompt」权限但看不到提问 → 标不了,拨开关可以
c1, b1 = 打("POST", P + "/memberships", 体={"工号": 甲, "角色": "admin"})
c2, _ = 打("POST", P + "/memberships", 体={"工号": 乙, "角色": "editor"})
assert c1 == 201 and c2 == 201, (c1, b1, c2)


def _授原文(工号):
    """夹具:直接在库里给临时成员「查看敏感输入」。走接口给不了 —— 权限规则是「不能通过邀请获得自己没有的权限」,
    而 U001(admin)自己没有这条专项(admin 对它是「可授权」档、默认关),第一次 e2e 就红在这(11-21 第十五轮)。
    种子里有原文权限的只有 U004(annotator,没「改 Prompt」),所以「能标注的人」只能夹具造。只改 E2E 开头的工号。"""
    assert str(工号).startswith("E2E"), 工号
    from sqlalchemy import create_engine, text as _t
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    with create_engine(url).begin() as c:
        n = c.execute(_t("update memberships set special_grants = cast(:g as jsonb) where project_id=:p and user_id=:u and user_id like 'E2E%'"),
                      {"g": json.dumps(["查看敏感输入/独立测试答案"]), "p": 项目, "u": 工号}).rowcount
    assert n == 1, (工号, n)


_授原文(甲)
c, mm = 打("GET", P + f"/traces?limit=1", 甲)
assert c == 200, (c, mm)

print("▸ ① 运行详情带「标注」块")
知 = 一轮(["ToolSearch", "kb_read", "kb_combo"])
取 = 一轮(["ToolSearch", "get_order", "kb_read"], 提问="我这单到哪了?", 回答="已发货。")
c, d = 打("GET", P + f"/traces/{知}", 甲)
块 = (d or {}).get("标注") or {}
ck("知识类那一轮:可以标、有权标、还没标过、调过的工具列出来", c == 200 and 块.get("可以吗") is True and 块.get("有权标吗") is True and 块.get("已有") is None
   and 块.get("调过的工具") == ["ToolSearch", "kb_read", "kb_combo"] and 块.get("角色") == "门店顾问", (c, 块))
c, d = 打("GET", P + f"/traces/{取}", 甲)
块 = (d or {}).get("标注") or {}
ck("调过 get_order 的那一轮:不可以标,原因点名 get_order(kb_read 不算)", 块.get("可以吗") is False and "get_order" in (块.get("原因") or "")
   and "kb_read" not in (块.get("原因") or ""), 块)
c, d = 打("GET", P + f"/traces/{知}", "U002")
块 = (d or {}).get("标注") or {}
ck("editor(U002)看同一轮:可以标但没权标(看不到原文),原因说清", 块.get("可以吗") is True and 块.get("有权标吗") is False and "原文" in (块.get("没权的原因") or ""), 块)
c, l = 打("GET", P + "/traces?limit=50", "U001")
别 = [x for x in (l or {}).get("items") or [] if x.get("entry_kind") != "聊天站"]
if 别:
    c, d = 打("GET", P + f"/traces/{别[0]['id']}", 甲)
    ck("非聊天站的运行:详情里没有「标注」块", c == 200 and "标注" not in (d or {}), (c, list((d or {}).keys())))
else:
    print("  ℹ️ 库里这一页没有非聊天站的运行,「没有标注块」这条没验到(不算过)")

print("\n▸ ② 总开关默认关")
c, l = 打("GET", P + "/chat-annotations", 甲)
开关原值 = (l or {}).get("开关")
ck("列表带「开关」(布尔);note 说明关着不生效", c == 200 and isinstance(开关原值, bool) and "note" in (l or {}), (c, l))
if 开关原值:
    打("PUT", P + "/chat-annotations/switch", 甲, 体={"enabled": False})
c, a = 打("GET", P + "/chat-annotations/active", "U001")
ck("给聊天站的清单:开关 false、items 空", c == 200 and a.get("开关") is False and a.get("items") == [], (c, a))

print("\n▸ ③ 建")
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": 取, "standard_answer": "已发货"})
ck("取数那一轮 → 422 CHAT_ANNOTATION_REALTIME,field_errors 里列出调过的工具", c == 422 and (r or {}).get("code") == "CHAT_ANNOTATION_REALTIME"
   and "get_order" in json.dumps((r or {}).get("field_errors") or {}, ensure_ascii=False), (c, r))
c, r = 打("POST", P + "/chat-annotations", "U004", 体={"trace_id": 知, "standard_answer": "x"})
ck("annotator(U004,有原文没「改 Prompt」)→ 403", c == 403, (c, r))
c, r = 打("POST", P + "/chat-annotations", 乙, 体={"trace_id": 知, "standard_answer": "x"})
ck("editor 没原文授权 → 403,说要看得到原文", c == 403 and "原文" in json.dumps(r or {}, ensure_ascii=False), (c, r))
老 = time.time() - 31 * 86400
到期 = 一轮(["kb_read"], 开始=老)
一轮(["kb_read"])   # 再导一轮触发到期清理
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": 到期, "standard_answer": "x"})
ck("原文已到期的一轮 → 422 CHAT_ANNOTATION_EXPIRED", c == 422 and (r or {}).get("code") == "CHAT_ANNOTATION_EXPIRED", (c, r))
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": 知, "standard_answer": "香云纱不能机洗,只能手洗阴干。", "note": "工艺手册第三章",
                                                  "question": "调用方想塞的提问", "tools_used": ["骗人的"]})
aid = (r or {}).get("id")
ck("合格的 → 201 启用;提问 / 角色 / 工具清单**从 trace 取**,不信调用方塞的;note 说总开关还没开", c == 201 and aid and r.get("status") == "启用"
   and r.get("question") == "香云纱能不能机洗?" and r.get("assistant_role") == "门店顾问" and r.get("tools_used") == ["ToolSearch", "kb_read", "kb_combo"]
   and r.get("note") == "工艺手册第三章" and r.get("开关") is False and r.get("revision") == 1, (c, r))
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": 知, "standard_answer": "再标一次"})
ck("同一轮再标 → 409 CHAT_ANNOTATION_EXISTS,指向已有那条", c == 409 and (r or {}).get("code") == "CHAT_ANNOTATION_EXISTS" and aid in json.dumps(r or {}), (c, r))
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": 知})
ck("缺 standard_answer → 422 VALIDATION", c == 422 and (r or {}).get("code") == "VALIDATION" and "standard_answer" in ((r or {}).get("field_errors") or {}), (c, r))
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": "tr_不存在", "standard_answer": "x"})
ck("不存在的 trace → 404", c == 404, (c, r))

print("\n▸ ④ 列表与详情")
c, l = 打("GET", P + "/chat-annotations", 甲)
我 = [x for x in (l or {}).get("items") or [] if x["id"] == aid]
ck("看得到原文的(甲):列表里见提问原文、答案、状态", 我 and 我[0]["question"] == "香云纱能不能机洗?" and 我[0]["status"] == "启用" and (l or {}).get("看得到原文吗") is True, 我)
c, l = 打("GET", P + "/chat-annotations", "U003")
我 = [x for x in (l or {}).get("items") or [] if x["id"] == aid]
ck("看不到原文的(U003 viewer):提问 None 只给长度,答案照给", c == 200 and 我 and 我[0]["question"] is None and 我[0].get("提问长度") == len("香云纱能不能机洗?")
   and 我[0]["standard_answer"], (c, 我))
c, d = 打("GET", P + f"/traces/{知}", 甲)
块 = (d or {}).get("标注") or {}
ck("运行详情「已有」指向这条", (块.get("已有") or {}).get("id") == aid and 块["已有"]["status"] == "启用", 块)

print("\n▸ ⑤ 开关")
c, r = 打("PUT", P + "/chat-annotations/switch", "U003", 体={"enabled": True})
ck("viewer 拨不了(403)", c == 403, (c, r))
c, r = 打("PUT", P + "/chat-annotations/switch", 乙, 体={"enabled": "true"})
ck("体不是布尔 → 422", c == 422, (c, r))
c, r = 打("PUT", P + "/chat-annotations/switch", 乙, 体={"enabled": True})
ck("editor 能拨开:开关 true、原来 false、报启用中几条", c == 200 and r.get("开关") is True and r.get("原来") is False and r.get("启用中的标注") >= 1, (c, r))
c, a = 打("GET", P + "/chat-annotations/active", "U001")
条 = [x for x in (a or {}).get("items") or [] if x["id"] == aid]
ck("给聊天站的清单:开关 true、这条在、带提问 / 答案全文和角色", a.get("开关") is True and 条 and 条[0]["question"] == "香云纱能不能机洗?"
   and 条[0]["standard_answer"].startswith("香云纱不能机洗") and 条[0]["assistant_role"] == "门店顾问", (c, 条))
c, a = 打("GET", P + "/chat-annotations/active", "U003")
ck("没「运行评测」的(viewer)拿不到清单 → 403", c == 403, (c, a))
c, au = 打("GET", P + "/audit-events?limit=100", "U001")
if c == 200:
    # 审计接口的列表键名不猜:在响应里找「元素是带 action 的字典」的那个列表
    列 = next((v for v in (au or {}).values() if isinstance(v, list) and v and isinstance(v[0], dict) and "action" in v[0]), [])
    动作 = [e.get("action") for e in 列]
    ck("审计里有 chat_annotation.switch 和 chat_annotation.create", "chat_annotation.switch" in 动作 and "chat_annotation.create" in 动作, 动作[:12])
else:
    print(f"  ℹ️ 审计接口 {c},这条没验到(不算过)")

print("\n▸ ⑥ 命中")
c, h1 = 打("POST", P + f"/chat-annotations/{aid}/hits", "U001", 体={"trace_id": "tr_新问题1"})
c, h2 = 打("POST", P + f"/chat-annotations/{aid}/hits", "U001", 体={})
ck("上报两次 → hit_count 1、2", (h1 or {}).get("hit_count") == 1 and (h2 or {}).get("hit_count") == 2, (h1, h2))
c, l = 打("GET", P + "/chat-annotations", 甲)
我 = [x for x in (l or {}).get("items") or [] if x["id"] == aid]
ck("列表里 hit_count 2、last_hit_at 有", 我 and 我[0]["hit_count"] == 2 and 我[0]["last_hit_at"], 我)
c, r = 打("POST", P + f"/chat-annotations/{aid}/hits", "U003", 体={})
ck("viewer 报不了命中(403)", c == 403, (c, r))

print("\n▸ ⑦ 改")
c, r = 打("PATCH", P + f"/chat-annotations/{aid}", 甲, 体={"standard_answer": "改过的答案"})
ck("不带 If-Match → 409 IF_MATCH_REQUIRED", c == 409 and (r or {}).get("code") == "IF_MATCH_REQUIRED", (c, r))
c, r = 打("PATCH", P + f"/chat-annotations/{aid}", 甲, 体={"standard_answer": "改过的答案"}, 头={"If-Match": "99"})
ck("旧 revision → 409 CONFLICT", c == 409 and (r or {}).get("code") == "CONFLICT", (c, r))
c, r = 打("PATCH", P + f"/chat-annotations/{aid}", 甲, 体={"standard_answer": "改过的答案", "status": "停用"}, 头={"If-Match": "1"})
ck("对的 revision → 200,revision 2,状态停用", c == 200 and r.get("revision") == 2 and r.get("status") == "停用", (c, r))
c, a = 打("GET", P + "/chat-annotations/active", "U001")
ck("停用的不在聊天站清单里", not [x for x in (a or {}).get("items") or [] if x["id"] == aid], a)
c, r = 打("POST", P + f"/chat-annotations/{aid}/hits", "U001", 体={})
ck("停用的报命中 → 404", c == 404, (c, r))
c, r = 打("PATCH", P + f"/chat-annotations/{aid}", 甲, 体={"status": "归档"}, 头={"If-Match": "2"})
ck("status 只认 启用 / 停用(归档走另一条)→ 422", c == 422, (c, r))
c, r = 打("PATCH", P + f"/chat-annotations/{aid}", 甲, 体={"status": "启用"}, 头={"If-Match": "2"})
c, a = 打("GET", P + "/chat-annotations/active", "U001")
条 = [x for x in (a or {}).get("items") or [] if x["id"] == aid]
ck("再启用 → 回到清单,答案是改过的", c == 200 and 条 and 条[0]["standard_answer"] == "改过的答案", (c, 条))

print("\n▸ ⑧ 归档")
c, r = 打("POST", P + f"/chat-annotations/{aid}/archive", 甲, 头={"If-Match": "3"})
ck("归档 → 200", c == 200 and r.get("归档了") is True, (c, r))
c, l = 打("GET", P + "/chat-annotations", 甲)
c2, a = 打("GET", P + "/chat-annotations/active", "U001")
c3, r3 = 打("POST", P + f"/chat-annotations/{aid}/hits", "U001", 体={})
ck("列表 / 清单里都没了,命中 404", not [x for x in (l or {}).get("items") or [] if x["id"] == aid]
   and not [x for x in (a or {}).get("items") or [] if x["id"] == aid] and c3 == 404, (c3,))
c, d = 打("GET", P + f"/traces/{知}", 甲)
块 = (d or {}).get("标注") or {}
ck("运行详情回到「可以标、还没标」", 块.get("可以吗") is True and 块.get("已有") is None, 块)
c, r = 打("POST", P + "/chat-annotations", 甲, 体={"trace_id": 知, "standard_answer": "又标回来"})
ck("同一轮再标 → 201,**同一个 id 起回来**(唯一键钉着,不另起一行),状态启用、不再归档", c == 201 and r.get("id") == aid and r.get("status") == "启用"
   and r.get("standard_answer") == "又标回来", (c, r))

print("\n▸ ⑨ 收尾")
c, l = 打("GET", P + "/chat-annotations", 甲)
rev = next((x["revision"] for x in (l or {}).get("items") or [] if x["id"] == aid), None)
c1, _ = 打("POST", P + f"/chat-annotations/{aid}/archive", 甲, 头={"If-Match": str(rev)})
c2, r2 = 打("PUT", P + "/chat-annotations/switch", 甲, 体={"enabled": False})
c3, a = 打("GET", P + "/chat-annotations/active", "U001")
ck("标注归档、开关关回去,清单回到 开关 false / 空", c1 == 200 and c2 == 200 and (a or {}).get("开关") is False and not [x for x in (a or {}).get("items") or [] if x["id"] == aid], (c1, c2, a))

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 标注回复 e2e {len(过)} 条全过")
