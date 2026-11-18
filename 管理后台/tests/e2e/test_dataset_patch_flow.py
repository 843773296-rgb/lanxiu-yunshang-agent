#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PATCH /datasets/{id}:给建好的数据集**补脱敏声明**(datasets_api.改数据集,11-18 补的洞)。

## 补的是哪个洞

`redaction_policy` 原来**只能在建的时候给**,而建那条接口又明说「可以不给,先建起来再补声明」——
于是列表页「卡在哪」第一条写着「下一步是去声明」,而**全仓没有任何一条接口能声明**。
真项目 3 个数据集里 2 个就卡在这。

## 守的几条

  · 不给脱敏策略也能建;列表里它 能导出吗=false、卡在哪 含「没声明脱敏策略」;「版本们」字段存在且是数组
  · PATCH 不带 If-Match → 409;给 `无需脱敏:测试用` → 200,脱敏策略回来、revision+1、能导出吗现算
  · 只给前缀「无需脱敏:」没理由 → 422 逐字段(field_errors.脱敏策略);空 body → 422
  · 审计 dataset.update

⚠️ 前提 `make dev`。自己建数据集(名字带 e2e),只碰 project_demo_a;库只读(审计那条查 audit_events)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
# 「改训练样本」在 U004 身上(照 test_datasets_flow 的夹具);U002 是编辑,没有
改样本的 = os.environ.get("AIMC_EXPORTER", "U004")
尾 = uuid.uuid4().hex[:6]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 头=None, 原样=None):
    data = 原样 if 原样 is not None else (json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法, data=data)
    req.add_header("X-Dev-User", 谁 or 改样本的)
    if data is not None:
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
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 连接                     # noqa: E402


def 列表里(dsid):
    s, b = 打("GET", P + "/datasets")
    行 = [d for d in (b or {}).get("数据集", []) if d["id"] == dsid]
    return s, (行[0] if 行 else None), b


def main():
    print("\n\033[1m▸ PATCH /datasets/{id} · 补脱敏声明\033[0m")
    # ── 1. 建(不给脱敏策略)→ 列表里卡在「没声明」──────────────────────
    名 = f"e2e-补脱敏声明-{尾}"
    s, b = 打("POST", P + "/datasets", {"名字": 名, "格式": "qa"})
    ck("建数据集(不给脱敏策略)→ 201", s == 201 and (b or {}).get("id"), (s, b))
    dsid = (b or {}).get("id")
    s, 行, 全 = 列表里(dsid)
    ck("列表里找得到它(**先断它在**,不然下面全是空验)", s == 200 and bool(行), (s, dsid, (全 or {}).get("条数")))
    行 = 行 or {}
    # ⚠️ 刚建的数据集**一个样本都没有**,而 training.能导出吗 第 ① 道闸就是「空集」且**先判先返回**
    #   (空集上后面每条闸都恰好通过,所以它故意短路)—— 于是空数据集的「卡在哪」只报「没样本」,
    #   **报不到「没声明脱敏策略」**。样本没有写接口(seed 直接写库),这里造不出「有样本 + 没声明」;
    #   那句话拿 seed 的「汉服工艺问答」(有样本、没声明)去验 —— 它正是 test_datasets_flow 考 CANNOT_EXPORT 那一份。
    ck("列表里 能导出吗=false、卡在哪 非空(空数据集先被「没样本」那道闸拦住 —— 见上面的注释)",
       行.get("能导出吗") is False and bool(行.get("卡在哪")),
       {"能导出吗": 行.get("能导出吗"), "卡在哪": str(行.get("卡在哪"))[:100]})
    有样没声明 = [d for d in (全 or {}).get("数据集", []) if d.get("样本数") and not d.get("脱敏策略")]
    if 有样没声明:
        ck(f"有样本而没声明的那几份({len(有样没声明)} 份,如 seed 的「汉服工艺问答」)**卡在哪 含「没声明脱敏策略」**(列表承诺的和导出那道闸是同一份判据)",
           all("没声明脱敏策略" in json.dumps(d.get("卡在哪"), ensure_ascii=False) and d.get("能导出吗") is False for d in 有样没声明),
           [(d["名字"], str(d.get("卡在哪"))[:60]) for d in 有样没声明][:2])
    else:
        print("  ⏸ 列表里没有「有样本 + 没声明脱敏策略」的数据集(先 python3 tools/seed_datasets.py)—— 「卡在哪 含没声明」这句这一轮没验,不算通过")
    ck("列表里「版本们」字段存在且是数组(评测中心发起评测要从这里选冻结版本 id)",
       isinstance(行.get("版本们"), list), type(行.get("版本们")).__name__)
    ck("刚建的数据集「版本们」是空数组、冻结过几版=0(没冻结过就没有版本 —— 不是 null)",
       行.get("版本们") == [] and 行.get("冻结过几版") == 0, (行.get("版本们"), 行.get("冻结过几版")))
    ck("列表里「脱敏策略」是 null(没声明 —— 不是空串)", 行.get("脱敏策略") is None, 行.get("脱敏策略"))
    rev = 行.get("revision")
    ck("列表每一行带 revision(PATCH 的 If-Match 要用它)", isinstance(rev, int), rev)
    # 列表上所有行都该有「版本们」—— 不只这一行
    缺 = [d["id"] for d in (全 or {}).get("数据集", []) if not isinstance(d.get("版本们"), list)]
    ck(f"列表 {len((全 or {}).get('数据集', []))} 行**每一行**「版本们」都是数组", (全 or {}).get("数据集") and not 缺, 缺[:3])

    # ── 2. 乐观锁 + 校验 ───────────────────────────────────────────────
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "无需脱敏:测试用"})
    ck("PATCH 不带 If-Match → 409 IF_MATCH_REQUIRED", s == 409 and (b or {}).get("code") == "IF_MATCH_REQUIRED",
       (s, (b or {}).get("code")))
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "无需脱敏:"}, 头={"If-Match": str(rev)})
    ck("只给前缀「无需脱敏:」没理由 → 422,field_errors 逐字段指到 脱敏策略",
       s == 422 and "脱敏策略" in ((b or {}).get("field_errors") or {}), (s, (b or {}).get("field_errors")))
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "无需脱敏:"}, 头={"If-Match": str(rev)})
    ck("半角冒号的「无需脱敏:」同样 422(归一之后判,不是靠字面)",
       s == 422 and "脱敏策略" in ((b or {}).get("field_errors") or {}), (s, (b or {}).get("field_errors")))
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {}, 头={"If-Match": str(rev)})
    ck("空 body → 422(没有要改的字段),field_errors 列出可改的两个字段",
       s == 422 and set(((b or {}).get("field_errors") or {})) >= {"脱敏策略", "用途"}, (s, (b or {}).get("field_errors")))
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "无需脱敏:测试用"}, 头={"If-Match": "9999"})
    ck("错的 If-Match → 409 REVISION_CONFLICT", s == 409 and (b or {}).get("code") == "REVISION_CONFLICT",
       (s, (b or {}).get("code")))
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "无需脱敏:测试用"}, 头={"If-Match": str(rev)}, 谁="U002")
    ck("editor(U002)PATCH → 403(要「改训练样本」)", s == 403, (s, (b or {}).get("code")))
    s, 行x, _ = 列表里(dsid)
    ck("被拒的那几次**一个字都没写进去**:revision 不动、脱敏策略仍是 null",
       (行x or {}).get("revision") == rev and (行x or {}).get("脱敏策略") is None,
       {k: (行x or {}).get(k) for k in ("revision", "脱敏策略")})

    # ── 3. 对的 → 200,脱敏策略回来、revision+1、能导出吗现算 ──────────
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "无需脱敏:测试用"}, 头={"If-Match": str(rev)})
    ck("给 `无需脱敏:测试用` + 对的 If-Match → 200", s == 200, (s, b))
    ck("返回里 脱敏策略 回来了、revision 前进一格、改了=[redaction_policy]",
       (b or {}).get("脱敏策略") == "无需脱敏:测试用" and (b or {}).get("revision") == rev + 1
       and (b or {}).get("改了") == ["redaction_policy"], {k: (b or {}).get(k) for k in ("脱敏策略", "revision", "改了")})
    ck("返回里「能导出吗」是现算的:声明补上了,但**还没有样本**,所以仍是 false、卡在哪 仍是「没样本」(不是「没声明」)",
       (b or {}).get("能导出吗") is False and "没声明脱敏策略" not in json.dumps((b or {}).get("卡在哪"), ensure_ascii=False)
       and "一个样本都没有" in json.dumps((b or {}).get("卡在哪"), ensure_ascii=False),
       {"能导出吗": (b or {}).get("能导出吗"), "卡在哪": str((b or {}).get("卡在哪"))[:120]})
    s, 行2, _ = 列表里(dsid)
    ck("列表上也同步变了:脱敏策略有了、revision+1、卡在哪 不含「没声明」",
       (行2 or {}).get("脱敏策略") == "无需脱敏:测试用" and (行2 or {}).get("revision") == rev + 1
       and "没声明脱敏策略" not in json.dumps((行2 or {}).get("卡在哪"), ensure_ascii=False),
       {k: (行2 or {}).get(k) for k in ("脱敏策略", "revision", "卡在哪")})
    # 声明成「需要脱敏」:收下,但 note 要说清导出仍会被拦、拦的理由变了
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"脱敏策略": "要去掉顾客手机号(e2e)"}, 头={"If-Match": str(rev + 1)})
    ck("声明成「需要脱敏」→ 200 收下,note 明说脱敏器没选型、导出仍会被拦(不假装在脱)",
       s == 200 and "没选型" in ((b or {}).get("note") or ""), (s, ((b or {}).get("note") or "")[:100]))
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"用途": "e2e 只改用途"}, 头={"If-Match": str(rev + 2)})
    ck("只改用途 → 200,改了=[purpose],脱敏策略**原样保留**(没给的字段不动)",
       s == 200 and (b or {}).get("改了") == ["purpose"] and (b or {}).get("脱敏策略") == "要去掉顾客手机号(e2e)",
       {k: (b or {}).get(k) for k in ("改了", "脱敏策略", "用途")})
    s, b = 打("PATCH", P + f"/datasets/{dsid}", {"用途": "e2e 只改用途"}, 头={"If-Match": str(rev + 2)})
    ck("拿旧 revision 再改 → 409(后到的不许静默覆盖)", s == 409 and (b or {}).get("code") == "REVISION_CONFLICT",
       (s, (b or {}).get("code")))

    # ── 4. 审计 ─────────────────────────────────────────────────────────
    with 连接() as c:
        审 = [dict(r) for r in c.execute(text("""
            select action, target_ref from audit_events
             where project_id=:p and action='dataset.update' and target_ref->>'dataset_id'=:d order by at"""),
            {"p": 项目, "d": dsid}).mappings()]
    ck("审计里 dataset.update **3 条**(成功那三次;被拒的不记),每条带 改了 / 脱敏策略 / 原脱敏策略",
       len(审) == 3 and all({"改了", "脱敏策略", "原脱敏策略"} <= set(x["target_ref"]) for x in 审),
       [(x["target_ref"].get("改了"), x["target_ref"].get("脱敏策略")) for x in 审])
    ck("第一条审计记的是从「空」改到「无需脱敏:测试用」(改前改后都留痕)",
       bool(审) and 审[0]["target_ref"].get("原脱敏策略") == "" and 审[0]["target_ref"].get("脱敏策略") == "无需脱敏:测试用",
       审[0]["target_ref"] if 审 else None)

    print(f"\n{'✅ ' + str(len(过)) + ' 条全过' if not 挂 else '❌ 挂: ' + str(挂)}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
