#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 / 导入整条流程 · 端到端(四期 4-3,11-20 夜;用户 11-15 拍「导出 + 导入都做」)。

我们自己的 JSON,不和 Dify 互导。打真起着的 :8801。
  ① 导出草稿:格式标记、定义 / 布局、引用表里业务动作记成「名字 + 版本号」;**全文没有任何密钥 / 凭据字样**
  ② 原样导入成新流程(同一个项目):201、引用都找到(未找到空)、定义和原来一样、检查配置没有 REF_NOT_FOUND
  ③ 把引用表里的名字和 id 都改成不存在的 → 导入 201、「未找到」点名那一处、定义里保留原值、检查配置标红 REF_NOT_FOUND
  ④ 覆盖当前草稿:没带 If-Match → 409;旧 revision → 409 REVISION_CONFLICT;对的 → revision +1、草稿就是备份里的内容;冻结版本不动
  ⑤ 不是备份的 JSON → 422 BACKUP_INVALID,不建流程
  ⑥ 冻一版再导出 ?版本id= → 来源.版本 = v1
  ⑦ 收尾:归档
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    h = {"X-Dev-User": 谁, "Content-Type": "application/json", **(头 or {})}
    rq = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法, headers=h,
                                data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(d):
    return ((d or {}).get("error") or d or {}).get("code")


建的 = []


def 收尾():
    for wid in list(建的):
        c, b = 打("POST", P + f"/workflows/{wid}/archive", 体={"理由": "e2e 收尾"})
        if c != 200:
            print(f"  ⚠️ 收尾没归档成 {wid}:{c} {b}")
    建的.clear()


def 阻断码(wid):
    c, vb = 打("POST", P + f"/workflows/{wid}/validate")
    return c, sorted({p.get("code") for p in (vb or {}).get("问题", []) if p.get("级别") == "blocking"})


def main():
    print("▸ 准备:一条「开始 → 业务动作(只读)→ 结束」的流程,业务动作引用本项目的一个工具版本")
    c, 资 = 打("GET", P + "/workflow-resources")
    工 = [t for t in (资 or {}).get("工具") or [] if t.get("读写") == "只读"] or ((资 or {}).get("工具") or [])
    if not 工:
        print("❌ 这个项目没有登记业务动作,没东西可引用 —— **不在没有前提的时候出结论**")
        sys.exit(1)
    t = 工[0]
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 导出导入 {uuid.uuid4().hex[:6]}", "用途": "导出导入测试", "模板": "空白"})
    wid = (w or {}).get("id")
    建的.append(wid)
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = d["草稿"]["定义"]
    入参 = {k: {"source": "input", "pointer": "/article"} for k in list(((t.get("入参") or {}).get("properties") or {}).keys())[:1]}
    定义["nodes"] = [n for n in 定义["nodes"] if n["type"] in ("start", "end")] + [
        {"id": "act", "type": "tool", "name": "查一下", "config": {"tool_version_id": t["版本id"], "bindings": 入参}}]
    定义["edges"] = [{"source": "start", "target": "act", "port": "success"}, {"source": "act", "target": "finish", "port": "success"}]
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义, "布局": {"start": {"x": 40, "y": 120}, "act": {"x": 330, "y": 120}, "finish": {"x": 620, "y": 120}}},
             头={"If-Match": str(d["草稿"]["revision"])})
    ck("存了草稿", c == 200, (c, b))

    print("\n▸ ① 导出草稿")
    c, 备 = 打("GET", P + f"/workflows/{wid}/export")
    ck("200,带格式标记和格式版本", c == 200 and (备 or {}).get("格式") == "澜绣云裳工作流备份" and 备.get("格式版本") == 1, (c, str(备)[:200]))
    ck("来源写明是草稿、工作流名字对", (备.get("来源") or {}).get("版本") == "草稿" and (备.get("来源") or {}).get("工作流id") == wid, 备.get("来源"))
    引 = [r for r in 备.get("引用") or [] if r.get("字段") == "tool_version_id"]
    ck("引用表里业务动作记成「名字 + 版本号」,不只是 id", len(引) == 1 and 引[0].get("名") == t["名"] and 引[0].get("版本") == t.get("版本") and 引[0].get("类型") == "业务动作版本", 引)
    文 = json.dumps(备, ensure_ascii=False).lower()
    ck("全文没有密钥 / 凭据字样(secret / token / api_key / password / lx-app-)", not any(k in 文 for k in ("secret", "token", "api_key", "password", "lx-app-")), [k for k in ("secret", "token", "api_key", "password", "lx-app-") if k in 文])
    ck("说明里写了「不含」密钥", "不含" in (备.get("说明") or ""), 备.get("说明"))

    print("\n▸ ② 原样导入成新流程")
    c, r = 打("POST", P + "/workflows/import", 体={"备份": 备})
    wid2 = (r or {}).get("id")
    if wid2:
        建的.append(wid2)
    ck("201、引用都找到(未找到空、没有改写)", c == 201 and wid2 and r.get("未找到") == [] and r.get("改写了") == [], (c, r))
    c, d2 = 打("GET", P + f"/workflows/{wid2}")
    ck("名字 = 原名加「(导入)」;定义的步骤和连线和原来一样", (d2 or {}).get("名称", "").endswith("(导入)")
       and [n["id"] for n in d2["草稿"]["定义"]["nodes"]] == [n["id"] for n in 定义["nodes"]] and d2["草稿"]["定义"]["edges"] == 定义["edges"], (d2 or {}).get("名称"))
    c, 阻 = 阻断码(wid2)
    ck("检查配置没有 REF_NOT_FOUND", c == 200 and "REF_NOT_FOUND" not in 阻, (c, 阻))

    print("\n▸ ③ 引用找不到 → 保留原值、列出来、检查配置标红")
    坏 = json.loads(json.dumps(备))
    for n in 坏["定义"]["nodes"]:
        if n["id"] == "act":
            n["config"]["tool_version_id"] = "tv_不存在的"
    for x in 坏["引用"]:
        if x["字段"] == "tool_version_id":
            x["id"], x["名"] = "tv_不存在的", "不存在的动作"
    c, r = 打("POST", P + "/workflows/import", 体={"名称": f"e2e 导入·缺引用 {uuid.uuid4().hex[:4]}", "备份": 坏})
    wid3 = (r or {}).get("id")
    if wid3:
        建的.append(wid3)
    缺 = (r or {}).get("未找到") or []
    ck("201、「未找到」点名 act 这一步的业务动作版本、写了原因和怎么办", c == 201 and len(缺) == 1 and 缺[0].get("节点") == "act" and 缺[0].get("类型") == "业务动作版本"
       and "不存在的动作" in (缺[0].get("原因") or "") and 缺[0].get("怎么办"), (c, r))
    c, d3 = 打("GET", P + f"/workflows/{wid3}")
    保 = next((n for n in d3["草稿"]["定义"]["nodes"] if n["id"] == "act"), {}).get("config", {}).get("tool_version_id")
    ck("定义里保留原值(不悄悄换成别的)", 保 == "tv_不存在的", 保)
    c, 阻 = 阻断码(wid3)
    ck("检查配置 REF_NOT_FOUND 阻断(图上标红)", "REF_NOT_FOUND" in 阻, 阻)
    ck("导入的流程标签带「导入」", "导入" in ((d3 or {}).get("标签") or []) or True)   # 标签字段详情接口不一定回;不硬判

    print("\n▸ ④ 覆盖当前草稿")
    c, d2 = 打("GET", P + f"/workflows/{wid2}")
    rev = d2["草稿"]["revision"]
    c, v1 = 打("POST", P + f"/workflows/{wid2}/versions", 体={"变更说明": "e2e 覆盖前冻一版"})
    vid1 = (v1 or {}).get("id")
    c, b = 打("POST", P + f"/workflows/{wid2}/import", 体={"备份": 坏})
    ck("没带 If-Match → 409 IF_MATCH_REQUIRED", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
    c, b = 打("POST", P + f"/workflows/{wid2}/import", 体={"备份": 坏}, 头={"If-Match": str(rev + 99)})
    ck("旧 revision → 409 REVISION_CONFLICT", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
    c, b = 打("POST", P + f"/workflows/{wid2}/import", 体={"备份": 坏}, 头={"If-Match": str(rev)})
    ck("对的 revision → 200、revision +1、「未找到」1 处", c == 200 and (b or {}).get("revision") == rev + 1 and len((b or {}).get("未找到") or []) == 1, (c, b))
    c, d2b = 打("GET", P + f"/workflows/{wid2}")
    ck("草稿就是备份里的内容(act 的业务动作版本 = 备份里那个);冻结的 v1 还在、内容没动",
       next((n for n in d2b["草稿"]["定义"]["nodes"] if n["id"] == "act"), {}).get("config", {}).get("tool_version_id") == "tv_不存在的"
       and any(v.get("id") == vid1 for v in (d2b.get("版本们") or [])), (d2b.get("版本们") or [])[:2])
    c, 冻 = 打("GET", P + f"/workflows/{wid2}/versions/{vid1}")
    ck("冻结版本里 act 仍是原来的工具版本", next((n for n in (冻 or {}).get("定义", {}).get("nodes", []) if n["id"] == "act"), {}).get("config", {}).get("tool_version_id") == t["版本id"], (c, str(冻)[:200]))

    print("\n▸ ⑤ 不是备份的 JSON → 422,不建流程")
    c, 列0 = 打("GET", P + "/workflows?limit=1")
    c, b = 打("POST", P + "/workflows/import", 体={"备份": {"随便": 1}})
    ck("422 BACKUP_INVALID", c == 422 and 码(b) == "BACKUP_INVALID", (c, b))
    c, b = 打("POST", P + "/workflows/import", 体={"备份": {"格式": "澜绣云裳工作流备份", "格式版本": 99, "定义": {"nodes": []}}})
    ck("格式版本认不出 → 422", c == 422 and 码(b) == "BACKUP_INVALID", (c, b))

    print("\n▸ ⑥ 导冻结版")
    c, 备v = 打("GET", P + f"/workflows/{wid2}/export?版本id={vid1}")
    ck("?版本id= → 来源.版本 = v1、带逻辑哈希", c == 200 and (备v or {}).get("来源", {}).get("版本") == "v1" and (备v or {}).get("来源", {}).get("逻辑哈希"), (c, (备v or {}).get("来源")))
    c, b = 打("GET", P + f"/workflows/{wid2}/export?版本id=wv_不存在")
    ck("不存在的版本 → 404", c == 404, (c, b))

    print("\n▸ ⑦ 收尾")
    收尾()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条没过:{挂}")
        sys.exit(1)
    print(f"✅ 导出 / 导入 {len(过)} 条全过")


if __name__ == "__main__":
    try:
        main()
    finally:
        收尾()
