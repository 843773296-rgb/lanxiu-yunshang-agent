#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识修订申请端到端(执行手册 W28,2026-11-17;用户 11-12 拍「总部运营审,开发合并」)。打真起着的管理后台,不调模型 —— 进 test-e2e-ci。

  ① 文件 / 段 / 原来写的 要在 knowledge/ 里**真找得到**:乱填 → 422 并定位到字段;「改成」和原来一样 → 422;没依据 → 422
  ② 合格的 → 201 待审;清单里排前;详情能做的动作是 采纳 / 驳回
  ③ 审:viewer → 403;自己审自己提的 → 409 SELF_REVIEW;驳回不写说明 → 422;采纳 → 已采纳 + 改动文本里有新口径、括号注记、原来写的那句
  ④ 已采纳再审 → 409 NOT_PENDING;没发布能力的人标已合并 → 403;待审的标已合并 → 409 NOT_ACCEPTED;已采纳 → 已合并
  ⑤ 驳回那条:状态 已驳回、说明留着、没有改动文本
跑完把自己造的行删掉(id 记在列表里,直接 delete)。
"""
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

项目 = "project_demo_a"
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
P = f"/api/v1/projects/{项目}"
提的人 = "U002"        # 开发 / 普通成员:有「运行评测」(提意见那个能力),没「受理意见」
总部 = "U001"          # 总部运营:受理意见 + 生产审核/发布/回滚
viewer = "U003"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}" + (f"  {str(补)[:160]}" if (补 and not 真) else ""))
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=总部):
    req = urllib.request.Request(基址 + 路, method=方法, data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁); req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:  # noqa: BLE001
            return e.code, None


def main():
    造的 = []
    try:
        码, 文件 = 打("GET", f"{P}/knowledge-revisions/files")
        ck("取得到 knowledge/ 的文件清单", 码 == 200 and (文件 or {}).get("文件们"), (码, 文件))
        文 = (文件 or {}).get("文件们", ["01-形制.md"])[0]
        码, 段 = 打("GET", f"{P}/knowledge-revisions/files?file={文}")
        ck("取得到那份文件的段标题", 码 == 200 and (段 or {}).get("段"), (码, 段))
        一段 = (段 or {}).get("段", [""])[0]
        # 从文件里原样取一句当「原来写的」
        根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        正文 = open(os.path.join(根, "knowledge", 文), encoding="utf-8").read().split("\n")
        原句 = next((l.strip() for l in 正文 if len(l.strip()) >= 12 and not l.startswith("#")), None)
        ck("前提:文件里取得到一句 12 字以上的正文当「原来写的」", bool(原句), 文)
        if not 原句:
            return 1
        好 = {"知识文件": 文, "段": 一段, "原来写的": 原句, "改成": 原句 + "(e2e 改过)", "依据": "e2e 夹具:《宋史》舆服三"}
        # ── ① 字段 ──
        码, 体 = 打("POST", f"{P}/knowledge-revisions", {**好, "知识文件": "没有这份.md"}, 谁=提的人)
        ck("文件不在 knowledge/ 里 → 422 定位到「知识文件」", 码 == 422 and "知识文件" in ((体 or {}).get("field_errors") or {}), (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions", {**好, "段": "不存在的段"}, 谁=提的人)
        ck("段不是那份文件里的标题 → 422 定位到「段」", 码 == 422 and "段" in ((体 or {}).get("field_errors") or {}), (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions", {**好, "原来写的": "这句话文件里肯定没有 e2e"}, 谁=提的人)
        ck("「原来写的」在文件里原样找不到 → 422", 码 == 422 and "原来写的" in ((体 or {}).get("field_errors") or {}), (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions", {**好, "改成": 原句}, 谁=提的人)
        ck("「改成」和原来一样 → 422", 码 == 422 and "改成" in ((体 or {}).get("field_errors") or {}), (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions", {**好, "依据": ""}, 谁=提的人)
        ck("没依据 → 422", 码 == 422 and "依据" in ((体 or {}).get("field_errors") or {}), (码, 体))
        # ── ② 合格的 ──
        码, 体 = 打("POST", f"{P}/knowledge-revisions", 好, 谁=提的人)
        ck("合格的 → 201 待审", 码 == 201 and (体 or {}).get("状态") == "待审", (码, 体))
        rid = (体 or {}).get("id"); 造的.append(rid)
        码, 体 = 打("POST", f"{P}/knowledge-revisions", 好, 谁=提的人)
        rid2 = (体 or {}).get("id"); 造的.append(rid2)
        码, 列 = 打("GET", f"{P}/knowledge-revisions?status=待审")
        ck("清单按状态筛得出这两条,待审排前", 码 == 200 and {rid, rid2} <= {x["id"] for x in (列 or {}).get("items", [])}, (码, len((列 or {}).get("items", []))))
        码, 详 = 打("GET", f"{P}/knowledge-revisions/{rid}")
        ck("详情:能做的动作是 采纳 / 驳回", 码 == 200 and (详 or {}).get("能做的动作") == ["采纳", "驳回"], (码, 详))
        # ── ③ 审 ──
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/review", {"决定": "采纳"}, 谁=viewer)
        ck("viewer 审 → 403", 码 == 403, (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/review", {"决定": "采纳"}, 谁=提的人)
        ck("提的人自己没有审的能力 → 403(或有能力也不能审自己:409)", 码 in (403, 409), (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/review", {"决定": "驳回"})
        ck("驳回不写说明 → 422", 码 == 422, (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/review", {"决定": "采纳", "说明": "史料对得上"})
        改动 = (体 or {}).get("改动文本") or ""
        ck("采纳 → 已采纳,改动文本带新口径 + 括号注记 + 原来那句", 码 == 200 and (体 or {}).get("状态") == "已采纳"
           and 好["改成"] in 改动 and "审过的修订申请" in 改动 and 原句 in 改动 and "依据:" in 改动, (码, 改动[:200]))
        # ── ④ 状态闸 ──
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/review", {"决定": "驳回", "说明": "再审一次"})
        ck("已采纳再审 → 409 NOT_PENDING", 码 == 409 and (体 or {}).get("code") == "NOT_PENDING", (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/merged", {}, 谁=viewer)
        ck("没发布能力的人标已合并 → 403", 码 == 403, (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid2}/merged", {})
        ck("待审的标已合并 → 409 NOT_ACCEPTED", 码 == 409 and (体 or {}).get("code") == "NOT_ACCEPTED", (码, 体))
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid}/merged", {})
        ck("已采纳 → 已合并", 码 == 200 and (体 or {}).get("状态") == "已合并", (码, 体))
        # ── ⑤ 驳回那条 ──
        码, 体 = 打("POST", f"{P}/knowledge-revisions/{rid2}/review", {"决定": "驳回", "说明": "依据不够"})
        ck("驳回 → 已驳回", 码 == 200 and (体 or {}).get("状态") == "已驳回", (码, 体))
        码, 详 = 打("GET", f"{P}/knowledge-revisions/{rid2}")
        ck("驳回那条:说明留着、没有改动文本、没有能做的动作", 码 == 200 and (详 or {}).get("审核说明") == "依据不够"
           and not (详 or {}).get("改动文本") and (详 or {}).get("能做的动作") == [], (码, 详))
    finally:
        # 收尾:删掉自己造的行(走库 —— 这张表没有删除口,夹具不该留在正式库里)
        造的 = [x for x in 造的 if x]
        if 造的:
            库 = os.environ.get("DATABASE_URL_PSQL", f"postgresql://{os.environ.get('USER')}@localhost:5432/aimc_dev")
            ids = ",".join(f"'{x}'" for x in 造的)
            r = subprocess.run(["psql", "-X", "-q", 库, "-c", f"delete from knowledge_revisions where project_id='{项目}' and id in ({ids})"],
                               capture_output=True, text=True)
            print(f"  (夹具已清 {len(造的)} 条" + (f";psql 说 {r.stderr.strip()[:80]}" if r.returncode else "") + ")")
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(夹具已清)")
    for x in 挂:
        print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
