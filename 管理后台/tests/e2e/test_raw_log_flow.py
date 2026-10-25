"""运行的原始日志(交互控件设计 §15 · L-T01–L-T05 能在接口层验的那几条)。要 make dev。

验的是:**只读库里已记下的原始记录**;没授权给打码副本并标明、有授权给原件,两边指纹一致(能对);
筛选写明是子集、分页给范围不把前 N 条说成全部;导出走单独接口并记审计;没这次运行 → 404。
不造运行:从项目里现挑一条有步骤和事件的(样本量为 0 → 红,不算通过)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
P = f"/api/v1/projects/{os.environ.get('AIMC_PROJECT', 'project_demo_a')}"
过, 挂 = [0], []


def ck(名, 真, 补=None):
    print(f"  {'✅' if 真 else '❌'} {名}" + ("" if 真 or 补 is None else "  " + json.dumps(补, ensure_ascii=False, default=str)[:200]))
    if 真:
        过[0] += 1
    else:
        挂.append(名)


def 打(方法, 路, 谁="U002", 体=None):
    r = urllib.request.Request(基址 + P + 路, method=方法, headers={"X-Dev-User": 谁, "content-type": "application/json"},
                               data=json.dumps(体).encode() if 体 is not None else None)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def q(**kw):
    return "?" + urllib.parse.urlencode({k: v for k, v in kw.items() if v is not None})


def main():
    print("运行的原始日志 · 原件 / 打码副本 / 筛选子集 / 分页 / 导出审计")
    _, rs = 打("GET", "/execution-runs" + q(limit=50))
    rid = 全 = None
    for r in rs.get("items") or []:
        c, x = 打("GET", f"/execution-runs/{r['id']}/raw-log")
        if c == 200 and x["按来源"]["步骤尝试"] >= 2 and x["按来源"]["事件"] >= 3:
            rid, 全 = r["id"], x
            break
    ck("项目里有带步骤和事件的运行可验(样本量不能是 0)", rid is not None)
    if not rid:
        return 1
    ck("条数对账:共 = 各来源之和", 全["共"] == sum(全["按来源"].values()), 全["按来源"])
    ck("没有「查看敏感输入」的人(U002)→ 能看原文 False", 全["能看原文"] is False)
    _, 原 = 打("GET", f"/execution-runs/{rid}/raw-log", 谁="U004")
    ck("有授权的人(U004)→ 能看原文 True", 原.get("能看原文") is True)
    指A = {(e["来源表"], e["主键"]): e["指纹"] for e in 全["条目"]}
    指B = {(e["来源表"], e["主键"]): e["指纹"] for e in 原["条目"]}
    ck("两种身份看到的同一条记录指纹一样(打码副本也能和原件对上)", 指A == 指B and len(指A) == 全["共"])
    ck("每条都带来源表、主键、字节数", all(e["来源表"] and e["主键"] and e["字节数"] > 0 for e in 全["条目"]))
    c, 事 = 打("GET", f"/execution-runs/{rid}/raw-log" + q(来源="事件"))
    ck("按来源筛:筛选后 = 那一类的条数,共 还是全部(不把子集说成全部)",
       事["筛选后"] == 全["按来源"]["事件"] and 事["共"] == 全["共"] and all(e["来源"] == "事件" for e in 事["条目"]))
    c, 页1 = 打("GET", f"/execution-runs/{rid}/raw-log" + q(条数=2))
    ck("分页:这一页 [0,2]、给出下一页从哪续", 页1["这一页"] == [0, 2] and 页1["下一页从"] == 2, [页1["这一页"], 页1["下一页从"]])
    c, 页2 = 打("GET", f"/execution-runs/{rid}/raw-log" + q(条数=2, 从=2))
    ck("续读第二页接得上,不重复", [e["主键"] for e in 页2["条目"]] == [e["主键"] for e in 全["条目"][2:4]])
    c, _ = 打("GET", f"/execution-runs/{rid}/raw-log" + q(来源="随便写的"))
    ck("认不出的来源 → 422(不静默当成全部)", c == 422, c)
    c, _ = 打("GET", "/execution-runs/xr_not_exist/raw-log")
    ck("没有这次运行 → 404", c == 404, c)
    def 审计数():
        _, a = 打("GET", "/audit-events" + q(limit=200), 谁="U001")
        return sum(1 for e in a.get("记录", []) if e.get("做了什么") == "导出原始日志")
    前 = 审计数()
    c, 包 = 打("POST", f"/execution-runs/{rid}/raw-log/export", 体={"来源": "事件"})
    ck("导出:写明是筛选子集、内容是部分打码、带整份指纹和定义哈希",
       c == 200 and 包["是全部还是子集"].startswith("筛选子集") and 包["内容"].startswith("部分打码")
       and len(包["整份指纹"]) == 64 and "定义哈希" in 包, {k: 包.get(k) for k in ("是全部还是子集", "内容")})
    ck("每次导出记一条审计", 审计数() == 前 + 1, [前, 审计数()])
    print()
    print(f"{'❌' if 挂 else '✅'} 原始日志 过 {过[0]} / 挂 {len(挂)}" + (f":{' / '.join(挂)}" if 挂 else ""))
    print(f"(验的运行 {rid},共 {全['共']} 条)")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
