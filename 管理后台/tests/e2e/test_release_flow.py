#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用与发布端到端(§17.4-9):候选 → 清单 → 审核 → 切指针 → 回滚 → 按环境跑。

## 这一份回答的是整条链上最后一个问题

前面几块管的是「有哪些版本」(Prompt 版本、索引构建、模型产物……),
而**发布清单是它们的「合起来」**,环境指针则回答「**哪一份正在服务**」。

没有这一块,前面所有版本管理都停在「我们存了很多版本」,
而**「上周二在跑哪一版」答不出来** —— 那正是出事时唯一要问的问题。

## 四条硬规矩,这一份逐条验

1. **清单里全是确切版本,不许「用最新的那个」**
2. **生产只认审核过的清单**,而「审过」判的是「审的是不是**这一份**」
3. **指针变更原子**(事务 + 乐观锁)
4. **回滚是一次新的部署动作,不是把历史改回去**

⚠️ 这一份**自己建应用**(名字带随机后缀),所以反复跑不会互相干扰 ——
而这正是上一份数据集测试栽过的地方:用库里现成的 pending 待办,
跑三次之后就开始报「没有待办」,而那种红看起来像功能坏了。

⚠️ 前提 `make dev`。
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

编辑 = "U002"        # 改 Prompt/知识候选
发布员 = "U001"      # 生产审核/发布/回滚


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 编辑)
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    if 体 is not None:
        req.add_header("content-type", "application/json")
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


def 一个(表, 条件=""):
    with 连接() as c:
        return c.execute(text(f"select id from {表} where project_id=:p {条件} limit 1"),
                         {"p": 项目}).scalar()


def 别的一个(表, 排除):
    """挑一个 id,**不在 `排除` 里**。挑不到返回 None(让断言去说它空跑)。

    ⚠️ 为什么不用 `一个()` 随手挑:清单的内容哈希是按六个依赖算的,
    随手挑到一个已经用过的组合,接口会正确地返回「没新建」——
    **而那时红的是我的步骤,不是接口**。
    """
    排除 = {x for x in (排除 or set()) if x}
    with 连接() as c:
        for r in c.execute(text(f"select id from {表} where project_id=:p limit 50"),
                           {"p": 项目}):
            if r[0] not in 排除:
                return r[0]
    return None


def 指针(aid, 环境):
    with 连接() as c:
        return c.execute(text("""select release_manifest_id from environment_bindings
                               where project_id=:p and application_id=:a
                                 and environment=:e"""),
                         {"p": 项目, "a": aid, "e": 环境}).scalar()


def K():
    return "rel-e2e-" + uuid.uuid4().hex[:10]


def main():
    print("\n\033[1m▸ 应用与发布 · 「哪一版在给用户跑」\033[0m")
    PV = 一个("prompt_versions")
    CV = 一个("connection_versions")
    if not (PV and CV):
        print("     缺 prompt_versions / connection_versions —— 先 make seed-demo")
        sys.exit(1)

    # ── 一、建应用 ─────────────────────────────────────────────────
    名 = f"发布咬合-{uuid.uuid4().hex[:6]}"
    码, a = 打("POST", f"{P}/applications", {"名字": 名, "流水线": "prompt"})
    ck("建应用 → 201", 码 == 201 and (a or {}).get("id"), 码)
    aid = (a or {}).get("id")
    码, 体 = 打("POST", f"{P}/applications", {"名字": "x", "流水线": "随便写的"})
    ck("认不出的流水线 → 422(首版只有两种)", 码 == 422, 码)
    码, 体 = 打("POST", f"{P}/applications", {"名字": 名, "流水线": "prompt"},
              谁="U003")
    ck("viewer 建应用 → 403", 码 == 403, 码)

    # ── 二、候选:**「用最新的那个」不许出现在清单里** ──────────────────
    码, 体 = 打("POST", f"{P}/applications/{aid}/releases")
    ck("空候选就出清单 → 422,并逐项说清少了什么",
       码 == 422 and len(((体 or {}).get("field_errors") or {}).get("闸", [])) == 2,
       [x[:26] for x in ((体 or {}).get("field_errors") or {}).get("闸", [])])
    码, d = 打("PATCH", f"{P}/applications/{aid}/draft",
             {"prompt_version_id": PV, "connection_version_id": "latest",
              "乱七八糟的键": "x"}, 头={"If-Match": "1"})
    ck("改候选 → 200", 码 == 200, 码)
    ck("**不认识的键当场报出来**(不静默吞掉)",
       (d or {}).get("不认识的键") == ["乱七八糟的键"], (d or {}).get("不认识的键"))
    ck("填了「latest」→ 候选就标着出不了清单",
       (d or {}).get("现在能出清单吗") is False
       and any("最新" in x for x in ((d or {}).get("还差什么") or [])),
       (d or {}).get("还差什么"))
    码, 体 = 打("PATCH", f"{P}/applications/{aid}/draft",
              {"connection_version_id": CV})
    ck("改候选不带 If-Match → 409", 码 == 409, 码)
    码, 体 = 打("PATCH", f"{P}/applications/{aid}/draft",
              {"connection_version_id": CV}, 头={"If-Match": "999"})
    ck("If-Match 不对 → 409 REVISION_CONFLICT",
       码 == 409 and (体 or {}).get("code") == "REVISION_CONFLICT", 码)
    码, d = 打("PATCH", f"{P}/applications/{aid}/draft",
             {"connection_version_id": CV}, 头={"If-Match": "2"})
    ck("填成确切版本 → 候选可以出清单了", (d or {}).get("现在能出清单吗") is True,
       (d or {}).get("还差什么"))

    # ── 三、出清单:同样的内容不新建 ─────────────────────────────────
    码, r = 打("POST", f"{P}/applications/{aid}/releases")
    ck("出发布清单 → 201", 码 == 201, 码)
    rid = (r or {}).get("id")
    ck("清单里每一项都是确切版本",
       (r or {}).get("清单", {}).get("prompt_version_id") == PV, (r or {}).get("清单"))
    码, r2 = 打("POST", f"{P}/applications/{aid}/releases")
    ck("同样的依赖组合再冻 → **同一份清单**,不新建",
       (r2 or {}).get("id") == rid and (r2 or {}).get("新建了吗") is False,
       ((r2 or {}).get("id"), (r2 or {}).get("新建了吗")))

    # ── 四、生产只认审核过的清单 ────────────────────────────────────
    码, 体 = 打("POST", f"{P}/releases/{rid}/deploy", {"环境": "production"},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("没审就发生产 → 422",
       码 == 422 and any("审核过" in x
                        for x in ((体 or {}).get("field_errors") or {}).get("闸", [])),
       ((体 or {}).get("field_errors") or {}).get("闸"))
    ck("生产被拦时,指针**一动没动**", 指针(aid, "production") is None,
       指针(aid, "production"))
    # 测试环境不用审 —— 那正是它存在的理由
    码, 体 = 打("POST", f"{P}/releases/{rid}/deploy", {"环境": "test"},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("发测试环境 → 202(**只有生产要审**)", 码 == 202, 码)
    ck("测试环境的指针指过去了", 指针(aid, "test") == rid, 指针(aid, "test"))

    码, 体 = 打("POST", f"{P}/releases/{rid}/reviews", {"结论": "通过"}, 谁="U003")
    ck("viewer 审核 → 403", 码 == 403, 码)
    码, 体 = 打("POST", f"{P}/releases/{rid}/reviews", {"结论": "同意"}, 谁=发布员)
    ck("结论写成「同意」→ 422(**不收任意字符串**)", 码 == 422, 码)
    码, rv = 打("POST", f"{P}/releases/{rid}/reviews",
              {"结论": "通过", "理由": "依赖都对得上"}, 谁=发布员)
    ck("审核通过 → 201,而且记下**审的是哪一份内容**",
       码 == 201 and (rv or {}).get("审的哈希"), (rv or {}).get("审的哈希"))
    码, 体 = 打("POST", f"{P}/releases/{rid}/deploy", {"环境": "production"},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("审过之后发生产 → 202", 码 == 202, 码)
    ck("生产指针指过去了", 指针(aid, "production") == rid, 指针(aid, "production"))

    # ── 五、按环境跑:**版本由指针解析,不收调用方传的版本** ────────────
    码, 体 = 打("POST", f"{P}/applications/{aid}/runs",
              {"环境": "production", "release_manifest_id": "rel_随便"},
              头={"Idempotency-Key": K()})
    ck("自己传版本号 → 422 VERSION_NOT_ACCEPTED",
       码 == 422 and (体 or {}).get("code") == "VERSION_NOT_ACCEPTED",
       (码, (体 or {}).get("code")))
    键 = K()
    码, run = 打("POST", f"{P}/applications/{aid}/runs",
               {"环境": "production", "输入": {"问": "这件云锦多久能做好"}},
               头={"Idempotency-Key": 键})
    ck("按环境跑 → 202", 码 == 202, (码, (run or {}).get("code")))
    ck("**用的哪一版记在这次运行上**(之后指针再切也查得到)",
       (run or {}).get("用的哪一版") == rid, (run or {}).get("用的哪一版"))
    码, run2 = 打("POST", f"{P}/applications/{aid}/runs",
                {"环境": "production", "输入": {}}, 头={"Idempotency-Key": 键})
    ck("同一个幂等键再跑 → 不跑第二次",
       (run2 or {}).get("id") == (run or {}).get("id")
       and (run2 or {}).get("新建了吗") is False, (run2 or {}).get("新建了吗"))
    码, 体 = 打("POST", f"{P}/applications/{aid}/runs",
              {"环境": "staging", "输入": {}}, 头={"Idempotency-Key": K()})
    ck("没绑定的环境 → 422 NO_BINDING(**不回落到「最新的那一版」**)",
       码 == 422 and (体 or {}).get("code") == "NO_BINDING",
       (码, (体 or {}).get("code")))

    # ── 六、回滚:是一次新的部署动作,不是把历史改回去 ──────────────────
    码, 体 = 打("POST", f"{P}/applications/{aid}/rollbacks",
              {"环境": "production", "回到哪一版": rid},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("回滚到自己 → 422(返回「成功」会让人以为回滚发生过)",
       码 == 422 and (体 or {}).get("code") == "CANNOT_ROLLBACK", 码)

    # 再出一版(换一项依赖 → 新的内容哈希),发上去,再滚回来
    码, d = 打("PATCH", f"{P}/applications/{aid}/draft",
             {"evaluation_id": 一个("evaluations") or "ev_x"},
             头={"If-Match": str((d or {}).get("revision", 3))})
    码, r3 = 打("POST", f"{P}/applications/{aid}/releases")
    新版 = (r3 or {}).get("id")
    ck("换了一项依赖 → **出的是新的一份清单**", 新版 and 新版 != rid, (新版, rid))
    打("POST", f"{P}/releases/{新版}/reviews", {"结论": "通过"}, 谁=发布员)
    码, 体 = 打("POST", f"{P}/releases/{新版}/deploy", {"环境": "production"},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("新版发到生产 → 202", 码 == 202, 码)
    ck("生产指针换成新版了", 指针(aid, "production") == 新版, 指针(aid, "production"))
    码, rb = 打("POST", f"{P}/applications/{aid}/rollbacks",
              {"环境": "production", "回到哪一版": rid},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("回滚到上一版 → 202", 码 == 202, (码, (rb or {}).get("code")))
    ck("指针回到了旧版", 指针(aid, "production") == rid, 指针(aid, "production"))
    # ⚠️ **历史清单一个字都没改** —— 改历史的话,
    # 「上周二在跑哪一版」会变成现在这一版。
    with 连接() as c:
        还在 = c.execute(text("""select count(*) from release_manifests
                              where project_id=:p and application_id=:a"""),
                       {"p": 项目, "a": aid}).scalar()
    ck("**两份清单都还在**(回滚没有把历史改回去)", 还在 == 2, 还在)
    ck("那次运行仍然说得出它当时跑的是哪一份",
       (run or {}).get("用的哪一版") == rid, (run or {}).get("用的哪一版"))

    # ── 七、列表:回答「哪一版在给用户跑」 ───────────────────────────
    码, 体 = 打("GET", f"{P}/applications")
    行 = [x for x in (体 or {}).get("应用", []) if x["id"] == aid]
    ck("列表上直接看得到各环境指着哪一版",
       bool(行) and 行[0]["各环境指着哪一版"].get("production") == rid,
       行[0]["各环境指着哪一版"] if 行 else None)

    # ── 八、三条读接口:这条链**读得出来**才做得成界面 ─────────────────
    # ⚠️ 这三条是 2026-09-29 补的。在那之前这一组 8 条接口**只有 1 条 GET**,
    # 也就是说发布链**只写不读**:清单 id 只在 POST 的响应里出现一次,
    # 刷新页面就找不回来;而发布要的 `If-Match`(指针 revision)
    # **任何接口都没暴露** —— `_指针们()` 读到了它,列表接口把它丢掉了。
    # 于是这条链在界面上做不起来,只能用 curl 一口气打完。
    #
    # 规格 §13.3 点名要的:「左:当前生产清单 / 右:候选清单」「查看完整 Diff」
    # 「中:… 回滚目标」、回滚时「展示旧版本可用性」—— 全都要读得到。
    # > **按登记表对账是穷尽的,前提是登记表自己对。**
    print("\n▸ 八、三条读接口(补登记的 §13.3 那几条)")
    码, det = 打("GET", f"{P}/applications/{aid}")
    ck("应用详情 → 200", 码 == 200 and (det or {}).get("id") == aid, 码)
    环 = (det or {}).get("各环境") or {}
    ck("**指针的 revision 给出来了** —— 它就是发布要带的 If-Match,"
       "拿不到就只能不带,而那正是「后到的悄悄覆盖先到的」那条路",
       isinstance((环.get("production") or {}).get("revision"), int),
       环.get("production"))
    ck("而且带上了那一版的**内容**(§13.3 要的「左:当前生产清单」——"
       "只给一个 id 的话左边那栏没东西可画)",
       isinstance((环.get("production") or {}).get("那一版的内容"), dict),
       (环.get("production") or {}).get("那一版的内容"))
    码, 体 = 打("GET", f"{P}/applications/app_根本没有这个")
    ck("不存在的应用 → 404", 码 == 404, 码)

    码, hist = 打("GET", f"{P}/applications/{aid}/releases")
    ck("清单历史 → 200,而且**新的在前**", 码 == 200 and (hist or {}).get("条数", 0) >= 2,
       (hist or {}).get("条数"))
    清单们 = (hist or {}).get("清单们") or []
    ck("每一行都说清**哪些环境指着它**(空 = 这一份从来没上过线)",
       all("哪些环境指着它" in x for x in 清单们),
       [(x["id"][-6:], x["哪些环境指着它"]) for x in 清单们])
    ck("在线那一份标着 production", any("production" in (x["哪些环境指着它"] or [])
                                   for x in 清单们),
       [(x["id"][-6:], x["哪些环境指着它"]) for x in 清单们])

    码, one = 打("GET", f"{P}/releases/{rid}")
    ck("清单详情 → 200", 码 == 200 and (one or {}).get("id") == rid, 码)
    ck("**算出了「这次审核还算不算数」**,不是只把 approval 原样丢出来 ——"
       "「审过了」和「审的是这一份」在界面上长得一样,而后者才是判据",
       (one or {}).get("这次审核还算数吗") is True,
       {"算数": (one or {}).get("这次审核还算数吗"),
        "为什么": (one or {}).get("为什么")})
    码, 体 = 打("GET", f"{P}/releases/rel_根本没有这个")
    ck("不存在的清单 → 404", 码 == 404, 码)
    码, 体 = 打("GET", f"{P}/releases/{rid}", 谁="U003")
    ck("viewer **读得到**(「不能改」不等于「不能看」)", 码 == 200, 码)
    码, 体 = 打("GET", f"/api/v1/projects/project_demo_b/releases/{rid}")
    ck("换项目号 → 404(不确认「它在别的项目里存在」)", 码 == 404, 码)

    # ── 九、旧审核不许跟到新清单上 ───────────────────────────────────
    # ⚠️ 这一条是这三条读接口里**唯一一条界面上看不出来的**,所以必须打。
    # 审核记的是「审的哪一份内容」(比内容哈希),而不是一个布尔。
    # 存成 `approved=true` 的话,「改完再发」这条路就是通的**而且不报错** ——
    # 表现是线上跑着一份没人审过的东西,而界面上写着「已审核」。
    print("\n▸ 九、改完候选另出一份 → **旧审核不跟过来**")
    # ⚠️ **这一页有两个 revision,别混** —— 我写这段的时候当场栽了一次:
    # 拿应用的 `revision` 去改候选 → 409。改候选认的是**草稿自己那个**。
    # 顺手把这件事变成一条断言:两个数**必须分得开**,
    # 否则界面上随手拿一个就是 409,而 409 读起来像「别人改过了」。
    ck("详情里给了 `候选revision`(改候选的 If-Match 认这个,"
       "不是应用的 revision —— 两个数各自独立地涨)",
       isinstance((det or {}).get("候选revision"), int),
       {"候选revision": (det or {}).get("候选revision"),
        "应用revision": (det or {}).get("revision")})
    码, 体 = 打("PATCH", f"{P}/applications/{aid}/draft",
              {"prompt_version_id": PV},
              头={"If-Match": str((det or {}).get("revision"))})
    ck("拿**应用的** revision 去改候选 → 409(两个数不通用)",
       码 == 409 or (det or {}).get("候选revision") == (det or {}).get("revision"),
       {"码": 码, "拿的是": (det or {}).get("revision")})

    # ⚠️ 换一个**这个应用从来没用过**的 Prompt 版本 —— 从历史里现算,不随手挑一个。
    # 第一版我随手加了个 `evaluation_id`,结果那个组合**恰好等于一份已经存在
    # 而且审过的清单**,于是接口正确地返回「没新建」(同样的内容两个清单号,
    # 「发布的是哪一份」就有两个答案),而我的断言指着接口说它错了。
    # > 判据是对的,我的步骤不对 —— 这一族今天第四次。
    用过的 = {(x.get("清单") or {}).get("prompt_version_id") for x in 清单们}
    新PV = 别的一个("prompt_versions", 用过的)
    ck("找得到一个**这个应用没用过**的 Prompt 版本(找不到的话下面几条是空跑)",
       bool(新PV), {"用过的": sorted(x for x in 用过的 if x), "挑中": 新PV})
    码, d2 = 打("PATCH", f"{P}/applications/{aid}/draft",
              {"prompt_version_id": 新PV},
              头={"If-Match": str((det or {}).get("候选revision"))})
    ck("拿**候选的** revision 去改 → 200", 码 == 200, 码)
    码, 新清单 = 打("POST", f"{P}/applications/{aid}/releases")
    新id = (新清单 or {}).get("id")
    ck("依赖变了 → **另出一份新清单**(不是改原来那一份)",
       码 == 201 and (新清单 or {}).get("新建了吗") is True and 新id != rid,
       {"新建了吗": (新清单 or {}).get("新建了吗"), "同一份吗": 新id == rid})
    码, n1 = 打("GET", f"{P}/releases/{新id}")
    ck("新清单上 **这次审核还算数吗 = false**(旧审核没跟过来)",
       (n1 or {}).get("这次审核还算数吗") is False,
       {"算数": (n1 or {}).get("这次审核还算数吗"), "为什么": (n1 or {}).get("为什么")})
    ck("而且**说清了为什么**(「还没审」/「审的是驳回」/「审的是另一份内容」"
       "—— 三种下一步完全不同)",
       bool((n1 or {}).get("为什么")), (n1 or {}).get("为什么"))
    码, o1 = 打("GET", f"{P}/releases/{rid}")
    ck("**老清单的审核照样算数**(清单不可变 —— 一旦审过就永远算数)",
       (o1 or {}).get("这次审核还算数吗") is True,
       (o1 or {}).get("为什么"))
    码, 体 = 打("POST", f"{P}/releases/{新id}/deploy", {"环境": "production"},
              谁=发布员, 头={"Idempotency-Key": K()})
    ck("拿这份**没审过**的清单发生产 → 422(生产只认审过的)",
       码 == 422 and (体 or {}).get("code") == "CANNOT_DEPLOY", 码)

    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
