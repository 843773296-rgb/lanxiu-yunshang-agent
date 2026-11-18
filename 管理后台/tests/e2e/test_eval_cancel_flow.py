#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测取消(evals_api.取消评测):**外部登记的没有可取消的运行;取消要写理由**。

  · 对一条「外部登记」的评测 POST cancel(带 If-Match + 理由)→ 409 NOT_DISPATCHED
  · 不带理由 → 422,field_errors.理由
  · 不带 If-Match → 409 IF_MATCH_REQUIRED

⚠️ 发起一次后台派发要跑真模型花钱,这一份**不发起新的**:demo_a 里有现成的「外部登记」评测就用它;
后台派发的若恰好有非终态的也验一条真取消,没有就只验上面这几条(并写明)。
前提 `make dev`;只碰 project_demo_a;不写库。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U002", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
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
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


def main():
    print("\n\033[1m▸ 评测取消 · 外部登记的没有可取消的运行\033[0m")
    s, b = 打("GET", P + "/evaluations?limit=100")
    ck("GET /evaluations 200", s == 200 and isinstance((b or {}).get("items"), list), s)
    项 = (b or {}).get("items") or []
    外部 = [x for x in 项 if x.get("executor_code") == "外部登记"]
    ck(f"**前提:有「外部登记」的评测可用**(这一页 {len(项)} 条里外部登记 {len(外部)} 条;0 条下面全是空验)",
       bool(外部), len(外部))
    if not 外部:
        print(f"\n❌ 挂: {挂}")
        return 1
    ev = 外部[0]
    s, 进 = 打("GET", P + f"/evaluations/{ev['id']}/progress")
    ck("进度接口给 revision(取消的 If-Match 要用它)", s == 200 and isinstance((进 or {}).get("revision"), int),
       (s, (进 or {}).get("revision")))
    rev = (进 or {}).get("revision")

    s, b = 打("POST", P + f"/evaluations/{ev['id']}/cancel", {"理由": "e2e 试试"})
    ck("不带 If-Match → 409 IF_MATCH_REQUIRED", s == 409 and (b or {}).get("code") == "IF_MATCH_REQUIRED",
       (s, (b or {}).get("code")))
    s, b = 打("POST", P + f"/evaluations/{ev['id']}/cancel", {}, 头={"If-Match": str(rev)})
    ck("不带理由 → 422,field_errors.理由=必填(半途停掉的评测,过后没人记得是谁停的、为什么)",
       s == 422 and ((b or {}).get("field_errors") or {}).get("理由"), (s, (b or {}).get("field_errors")))
    s, b = 打("POST", P + f"/evaluations/{ev['id']}/cancel", {"理由": "   "}, 头={"If-Match": str(rev)})
    ck("理由全是空白 → 也是 422(空白不算写了)", s == 422, (s, (b or {}).get("code")))
    s, b = 打("POST", P + f"/evaluations/{ev['id']}/cancel", {"理由": "e2e 试试"}, 头={"If-Match": str(rev)})
    ck("外部登记的评测取消 → 409 NOT_DISPATCHED(没有可取消的运行,由外面那一方停)",
       s == 409 and (b or {}).get("code") == "NOT_DISPATCHED", (s, (b or {}).get("code"), ev["id"]))
    ck("advice 说清「外部登记的评测由外面那一方停」", "外面" in ((b or {}).get("advice") or ""), (b or {}).get("advice"))
    s, 进2 = 打("GET", P + f"/evaluations/{ev['id']}/progress")
    ck("被拒之后评测**一个字没动**:status / revision 和之前一样",
       (进2 or {}).get("status") == (进 or {}).get("status") and (进2 or {}).get("revision") == rev,
       {k: (进2 or {}).get(k) for k in ("status", "revision")})
    s, b = 打("POST", P + f"/evaluations/ev_不存在_e2e/cancel", {"理由": "e2e"}, 头={"If-Match": "1"})
    ck("不存在的评测 → 404", s == 404, (s, (b or {}).get("code")))
    s, b = 打("POST", P + f"/evaluations/{ev['id']}/cancel", {"理由": "e2e"}, 头={"If-Match": str(rev)}, 谁="U003")
    ck("viewer(U003)取消 → 403(要「运行评测」)", s == 403, (s, (b or {}).get("code")))

    派发的 = [x for x in 项 if x.get("executor_code") == "后台派发" and x.get("status") not in ("已完成", "已取消", "失败", "超时", "已失败")]
    if 派发的:
        d = 派发的[0]
        s, 进d = 打("GET", P + f"/evaluations/{d['id']}/progress")
        s, b = 打("POST", P + f"/evaluations/{d['id']}/cancel", {"理由": "e2e 收尾:现成的非终态派发评测"},
                  头={"If-Match": str((进d or {}).get("revision"))})
        ck("现成的非终态后台派发评测 → 取消成功 200 status=已取消", s == 200 and (b or {}).get("status") == "已取消", (s, b))
    else:
        print("  ⏸ demo_a 里没有非终态的后台派发评测 —— 真取消那一支这一轮**没验**(不发起新的:要跑真模型花钱)")

    print(f"\n{'✅ ' + str(len(过)) + ' 条全过' if not 挂 else '❌ 挂: ' + str(挂)}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
