#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具与能力端到端(§11、§16.3):工具版本 / 工具连接 / Skill 指南 / 规则策略。

## 四句话,这一份逐条验

**① 风险变大必须出新版本**(§16.3)。原话:
> 一个工具从只读变成会写东西,而引用它的 Agent 还指着老的说明 ——
> **那份说明现在是错的**。

**② 密钥只收引用、不回显**(§11.2)。列表只给形状,**不做截断**。

**③ 指南不授予权限**(§11.3)。「启用了指南」被读成「给了脚本权限」
是这一块最容易出的误解 —— 所以这条链上**根本没有写权限的字段**。

**④ 白名单,不是黑名单。** 指南的文件、规则的模板都是白名单 ——
「哪些后缀算可执行」是个无限集合,而这个仓库为「枚举必输」栽过七次。

## ⚠️ 这一份里有一条是「空跑的判据」换来的

`capabilities.可以冻结工具吗()` 里那条「写入的工具要有幂等策略」,
第一版写的是 `if hasattr(DSL, "找副作用") else None` ——
**而那个函数当时根本不存在**,于是这条判据从写下那一刻起就是空跑的,
输出上和「判过了没问题」长得一模一样。

> **一个「有就判、没有就跳过」的判据,在函数改名那天会安静地变成空跑。**

所以这里点名验它:**不给幂等策略的写入工具,必须冻不进去**。

⚠️ 这一份自己建自己的指南/规则/连接(名字带随机后缀),跑完自己清。
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

编排的 = "U002"      # 改编排草稿
配密钥的 = "U001"    # 配置密钥与预算
尾 = uuid.uuid4().hex[:6]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 头=None, 要原文=False):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 编排的)
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            身 = r.read()
            return r.status, json.loads(身 or b"null"), 身.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        身 = e.read()
        try:
            return e.code, json.loads(身 or b"null"), 身.decode("utf-8", "replace")
        except Exception:
            return e.code, None, ""
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务, 连接                # noqa: E402


def 清掉():
    with 事务() as c:
        for 表, 列 in (("skill_versions", "name"), ("policy_versions", "name"),
                      ("capability_connections", "name")):
            c.execute(text(f"delete from {表} where project_id=:p "
                           f"and {列} like :n"), {"p": 项目, "n": f"%咬合-{尾}"})
        # 自己造的那个工具连同它的版本一起清
        c.execute(text("""delete from tool_versions where project_id=:p
                         and tool_definition_id in
                         (select id from tool_definitions where project_id=:p
                           and name like :n)"""), {"p": 项目, "n": f"咬合工具-{尾}"})
        c.execute(text("delete from tool_definitions where project_id=:p "
                       "and name like :n"), {"p": 项目, "n": f"咬合工具-{尾}"})


def 工具():
    """**自己造一个只读工具**,不用库里现成的。

    ⚠️ 第一版拿的是库里第一个工具,于是「只读→写入」那两条断言
    **只在第一次跑的时候成立** —— 跑完那个工具已经是 write 了,
    第二遍就挂。而挂的理由看起来像功能坏了。
    > **判据不许依赖会被自己改掉的前提。**
    """
    码, d, _ = 打("POST", f"{P}/tools",
                # ⚠️ `POST /tools` 收的是**中文键**(`名称` / `读写类型`)——
                # 我第一版按自己新写那几条的习惯传了英文键,当场 422。
                # **同一个仓库里两套入参风格**,而没有任何东西拦着 ——
                # 记在交接里:新接口一律两种都收(`体.get("中文") or 体.get("english")`)。
                {"名称": f"咬合工具-{尾}", "用途": "端到端咬合用",
                 "读写类型": "read_only", "接入方式": "MockToolProvider"})
    if 码 not in (200, 201) or not (d or {}).get("id"):
        print(f"     建不了工具(HTTP {码}):{d}"); sys.exit(1)
    # ⚠️ **建完去库里读 `draft_revision`,不假设它是 0。**
    # 第一版写死 0,当场 409 —— 「新建的行那一列是多少」是个我没查过的事实,
    # 而假设它和判据写错在输出上长得一样(都是一条红线)。
    with 连接() as c:
        rev = c.execute(text("""select coalesce(draft_revision,0)
                              from tool_definitions where project_id=:p and id=:i"""),
                        {"p": 项目, "i": d["id"]}).scalar()
    return (d["id"], rev, "read_only")


def main():
    print("\n\033[1m▸ 工具与能力 · 风险变大必须出新版本\033[0m")
    tid, rev, 老副作用 = 工具()

    # ⚠️ **先冻一版只读的** —— 「风险变大」这件事的前提是
    # **有一份已经冻结的旧说明**。新建的工具还没有任何版本,
    # 那就没有会变错的说明,所以那时候「风险变大=false」是**对的**。
    # (第一版我直接 PATCH 就断言风险变大,而判据是对的、我的步骤不对。)
    码, v0, _ = 打("POST", f"{P}/tools/{tid}/versions",
                 {"给模型的说明": "只查不写,按单号查返修进度",
                  "入参": {"type": "object"}})
    ck("先冻一版**只读**的 → 201(它就是后面那份「会变错的旧说明」)",
       码 == 201 and (v0 or {}).get("version_no") == 1,
       (码, (v0 or {}).get("version_no")))
    ck("只读的工具**不要求幂等策略**(对照:下面那条不是恒拦)",
       码 == 201, 码)

    # ── 一、草稿:改副作用是允许的,拦在冻结那一步 ─────────────────────
    # ── 工具详情:**改草稿的 If-Match 得有地方拿** ─────────────────────
    # ⚠️ 这一组是 2026-09-29 补的,补的是一个洞:
    # `PATCH /tools/{id}/draft` 的错误提示写着「把**工具详情**里的
    # `draft_revision` 放进 If-Match 头」—— 而**那个接口当时不存在**,
    # `GET /tools` 也不给 revision。于是改工具草稿在界面上做不起来:
    # 不是前端没写,是它拿不到必须带的那个值。
    # > 一句指着不存在的页面的错误提示,比不给提示更糟。
    print("\n▸ 工具详情(补的洞:改草稿的 If-Match 原来没地方拿)")
    码, det, _ = 打("GET", f"{P}/tools/{tid}")
    ck("工具详情 → 200", 码 == 200 and (det or {}).get("id") == tid, 码)
    ck("**给了 `draft_revision`** —— 它才是改草稿的 If-Match",
       isinstance((det or {}).get("draft_revision"), int),
       (det or {}).get("draft_revision"))
    # ⚠️ 两个数都要在,而且要**分得开**。只给一个的话界面会把手边那个塞进
    # If-Match,换来一个 409「这份草稿已经被改过」—— 而它读起来像「别人改过了」。
    ck("`revision` 也在,而且和 `draft_revision` **是两个字段**"
       "(混起来的表现是一个读起来像「别人改过了」的 409)",
       "revision" in (det or {}) and "draft_revision" in (det or {}),
       {"draft_revision": (det or {}).get("draft_revision"),
        "revision": (det or {}).get("revision")})
    ck("草稿那一栏里也带着同一个数(界面从哪一层读都拿得到)",
       ((det or {}).get("草稿") or {}).get("revision")
       == (det or {}).get("draft_revision"),
       ((det or {}).get("草稿") or {}).get("revision"))
    ck("版本历史给出来了(没有它就挑不出「回到哪一版」)",
       isinstance((det or {}).get("版本历史"), list)
       and len((det or {}).get("版本历史")) >= 1,
       len((det or {}).get("版本历史") or []))
    ck("**`风险变大了吗` 由服务端算**(让界面自己比两个副作用等级的话,"
       "那条规矩就变成每个前端各实现一遍,而不一致的表现是界面少一句警告)",
       "风险变大了吗" in (det or {}), (det or {}).get("风险变大了吗"))
    码, 体, _ = 打("GET", f"{P}/tools/tool_nope_xyz")
    ck("不存在的工具 → 404", 码 == 404, 码)
    码, 体, _ = 打("GET", f"/api/v1/projects/project_demo_b/tools/{tid}")
    ck("换项目号 → 404(不确认「它在别的项目里存在」)", 码 == 404, 码)
    码, d, _ = 打("PATCH", f"{P}/tools/{tid}/draft", {"side_effect_type": "write",
                                                  "乱七八糟": 1},
                头={"If-Match": str(rev)})
    ck("改草稿 → 200", 码 == 200, 码)
    ck("**不认识的键当场报出来**(不静默吞掉)",
       (d or {}).get("不认识的键") == ["乱七八糟"], (d or {}).get("不认识的键"))
    ck("只读→写入:草稿上就标出**风险变大了**",
       (d or {}).get("风险变大了吗") is True, (d or {}).get("风险变大了吗"))
    码, 体, _ = 打("PATCH", f"{P}/tools/{tid}/draft", {"side_effect_type": "write"})
    ck("不带 If-Match → 409", 码 == 409, 码)
    码, 体, _ = 打("PATCH", f"{P}/tools/{tid}/draft", {"side_effect_type": "write"},
                谁="U003", 头={"If-Match": "1"})
    ck("viewer 改草稿 → 403", 码 == 403, 码)

    # ── 二、冻版本:那条**曾经空跑**的判据要真的响 ─────────────────────
    码, 体, _ = 打("POST", f"{P}/tools/{tid}/versions",
                {"给模型的说明": "会写库", "入参": {"type": "object"}})
    闸 = ((体 or {}).get("field_errors") or {}).get("闸", [])
    ck("写入的工具**不给幂等策略就冻不进去**"
       "(这条判据第一版是空跑的 —— `hasattr` 那个函数根本不存在)",
       码 == 422 and any("幂等" in x for x in 闸), [x[:30] for x in 闸])
    码, 体, _ = 打("POST", f"{P}/tools/{tid}/versions",
                {"入参": {"type": "object"}, "幂等策略": "按单号"})
    ck("不给「给模型看的说明」→ 422(模型靠它决定要不要调)",
       码 == 422 and any("说明" in x for x in
                        ((体 or {}).get("field_errors") or {}).get("闸", [])), 码)
    码, 体, _ = 打("POST", f"{P}/tools/{tid}/versions",
                {"给模型的说明": "import os\nos.system(1)",
                 "入参": {"type": "object"}, "幂等策略": "按单号"})
    ck("**接口不收任意执行代码**(§17.1)→ 422",
       码 == 422 and any("代码" in x for x in
                        ((体 or {}).get("field_errors") or {}).get("闸", [])), 码)
    码, v, _ = 打("POST", f"{P}/tools/{tid}/versions",
                {"给模型的说明": "按单号推进返修单,会写库",
                 "入参": {"type": "object", "properties": {"单号": {"type": "string"}}},
                 "幂等策略": "按单号+动作去重"})
    ck("补齐之后冻得进去 → 201", 码 == 201, (码, (v or {}).get("code")))
    ck("而且点明**风险比上一版大**(引用老版本的 Agent 拿到的说明现在是错的)",
       (v or {}).get("风险比上一版大吗") is True and "错的" in str((v or {}).get("note")),
       (v or {}).get("风险比上一版大吗"))

    # ── 三、工具连接:密钥只收引用、不回显 ─────────────────────────────
    明文 = "PLAIN-" + uuid.uuid4().hex[:8]
    码, 体, 原文 = 打("POST", f"{P}/capability-connections",
                  {"名字": f"连接咬合-{尾}", "适配器": "MCP",
                   "允许的端点": ["https://a"], "api_key": 明文,
                   "secret_ref": "env://X"}, 谁=配密钥的)
    ck("塞明文 → 422,而且**错误里没回显那个值**",
       码 == 422 and 明文 not in 原文, 码)
    码, 体, _ = 打("POST", f"{P}/capability-connections",
                {"名字": f"连接咬合-{尾}", "适配器": "MCP",
                 "secret_ref": "env://X"}, 谁=配密钥的)
    ck("不给端点白名单 → 422(**它能打到哪儿不确定,而那要等出事才知道**)",
       码 == 422, 码)
    引用 = "keychain://lanxiu/mcp-" + 尾
    码, cc, _ = 打("POST", f"{P}/capability-connections",
                 {"名字": f"连接咬合-{尾}", "适配器": "MCP",
                  "允许的端点": ["https://shop.internal/mcp"],
                  "secret_ref": 引用}, 谁=配密钥的)
    ck("正常建 → 201", 码 == 201, (码, (cc or {}).get("code")))
    码, 体, 原文 = 打("GET", f"{P}/capability-connections")
    ck("**列表里找不到那个引用**(只给形状,不做截断)", 引用 not in 原文,
       "出现了就是把引用交出去了")
    行 = [x for x in (体 or {}).get("连接", []) if x["名字"] == f"连接咬合-{尾}"]
    ck("形状里有「存在哪 + 多长」", bool(行) and 行[0]["密钥"]["存在哪"] == "keychain",
       行[0]["密钥"] if 行 else None)
    ck("列表点明「连接发现的新工具不自动给生产 Agent 权限」",
       "不自动增加" in str((体 or {}).get("note")), str((体 or {}).get("note"))[:40])

    # ── 四、指南:白名单 + 不授予权限 ──────────────────────────────────
    名 = f"指南咬合-{尾}"
    码, 体, _ = 打("POST", f"{P}/skills",
                {"名字": 名, "正文": "照这个做", "参考文件": ["a.md", "run.sh"]})
    ck("参考文件里有 .sh → 422(**白名单不是黑名单**)", 码 == 422, 码)
    码, 体, _ = 打("POST", f"{P}/skills",
                {"名字": 名, "正文": "import os\nos.system(1)"})
    ck("指南正文里有可执行代码 → 422(**指南不执行,也不授予权限**)", 码 == 422, 码)
    码, sk, _ = 打("POST", f"{P}/skills",
                 {"名字": 名, "用途": "教模型拆报价",
                  "正文": "# 报价\n按工序拆", "参考文件": ["样例.md"]})
    ck("正常建 → 201,版本从 1 起", 码 == 201 and (sk or {}).get("版本号") == 1,
       (码, (sk or {}).get("版本号")))
    ck("**复核状态从「待复核」起**"
       "(一份没人看过的指南和一份审过的,界面上都显示「已挂载」)",
       (sk or {}).get("复核状态") == "待复核", (sk or {}).get("复核状态"))
    码, 体, _ = 打("POST", f"{P}/skills", {"名字": 名, "正文": "x"})
    ck("同名再建 → 409(**模型按名字加载,两份同名不知道拿哪一份**)",
       码 == 409 and (体 or {}).get("code") == "SKILL_EXISTS", 码)
    码, sk2, _ = 打("POST", f"{P}/skills/{名}/versions", {"正文": "# 报价 v2\n补了加急"})
    ck("出新版本 → 201,版本号 +1", 码 == 201 and (sk2 or {}).get("版本号") == 2,
       (sk2 or {}).get("版本号"))
    码, 体, _ = 打("POST", f"{P}/skills/根本没有这份/versions", {"正文": "x"})
    ck("给不存在的指南出版本 → 404", 码 == 404, 码)
    码, 体, _ = 打("GET", f"{P}/skills")
    这份 = [x for x in (体 or {}).get("指南", []) if x["名字"] == 名]
    ck("列表按名字聚合成一份、两个版本",
       bool(这份) and len(这份[0]["版本"]) == 2, 这份[0]["版本"] if 这份 else None)
    ck("列表点明「指南不授予权限」", "不授予权限" in str((体 or {}).get("note")))

    # ── 五、规则:白名单模板,而且说清「约定」和「强制」的区别 ──────────
    码, 体, _ = 打("POST", f"{P}/policies",
                {"名字": f"规则咬合-{尾}", "模板": "自己写的", "参数": {},
                 "触发点": "调用前", "命中之后": "拦住"}, 谁=配密钥的)
    ck("模板不在白名单 → 422(**不开放任意代码**)", 码 == 422, 码)
    码, 体, _ = 打("POST", f"{P}/policies",
                {"名字": f"规则咬合-{尾}", "模板": "禁止工具",
                 "参数": {"钩子": "import os"}, "触发点": "调用前",
                 "命中之后": "拦住"}, 谁=配密钥的)
    ck("参数里塞代码 → 422(**参数只放配置**)", 码 == 422, 码)
    码, po, _ = 打("POST", f"{P}/policies",
                 {"名字": f"规则咬合-{尾}", "模板": "禁止工具",
                  "参数": {"工具": "delete_file"}, "触发点": "调用前",
                  "命中之后": "拦住"}, 谁=配密钥的)
    ck("正常建 → 201", 码 == 201, (码, (po or {}).get("code")))
    ck("返回点明这是**程序强制**不是提示词里的约定",
       "强制" in str((po or {}).get("note")), str((po or {}).get("note"))[:36])
    码, 体, _ = 打("GET", f"{P}/policies")
    ck("列表给出可用的模板(而不是让人猜)",
       bool((体 or {}).get("可用的模板")), list((体 or {}).get("可用的模板") or {}))
    码, 体, _ = 打("POST", f"{P}/policies", {"名字": "x", "模板": "禁止工具",
                                          "参数": {}, "触发点": "调用前",
                                          "命中之后": "拦住"}, 谁="U002")
    ck("editor 建规则 → 403(要「配置密钥与预算」)", 码 == 403, 码)

    # ── 闭环:拿详情里那个数去改草稿,必须改得动 ────────────────────────
    # ⚠️ **这一条放在最后是有原因的。** 我先把它放在详情那一组里,
    # 结果它把 `draft_revision` 用掉了(1 → 2),而后面几条原有的断言
    # **写死了 `If-Match: 1`** —— 于是三条无关的断言一起红,
    # 而红的理由指向那几条本身。
    # (写死一个会漂的值,代价不是「不严谨」,是**下一个人改动别处时被它咬一口**。)
    #
    # 少了这一条,上面那几条只证明「有这个字段」,不证明「它是对的那个数」——
    # 而一个字段在、值是错的判据,和没有判据差不多。
    print("\n▸ 闭环:详情给的那个数,真能用来改草稿")
    码, det2, _ = 打("GET", f"{P}/tools/{tid}")
    码, 闭, _ = 打("PATCH", f"{P}/tools/{tid}/draft", {"owner": "闭环测试"},
                头={"If-Match": str((det2 or {}).get("draft_revision"))})
    ck("拿详情里现读的 `draft_revision` 去改草稿 → **200** "
       "(这一条才证明那个数是对的,不只是「有这个字段」)",
       码 == 200, {"码": 码, "带的": (det2 or {}).get("draft_revision")})
    码, 体, _ = 打("PATCH", f"{P}/tools/{tid}/draft", {"owner": "x"},
                头={"If-Match": str((det2 or {}).get("revision"))})
    # ⚠️ **量出来的事实:工具这里两个数一直相等。**
    # 第一版我写的是「拿另一个 revision 去改 → 409」,而它在这一轮
    # 靠 `None == None` 蒙绿过一次;改成诚实版之后,它说出了真相 ——
    # `draft_revision` 和 `revision` 在**同一个 UPDATE 里一起涨**
    # (`draft_revision=:_r, revision=revision+1`),所以它们一直相等。
    #
    # 这件事比那条 409 更值得记住:
    # > **两个数恰好相等的时候,拿错一个也不会报错** ——
    # > 于是那个错会一直藏着,直到某天它们分开(比如有别的路径只涨 revision)。
    #
    # 运行时拦不住这种拿错,所以唯一的防线是**接口明确说清该用哪一个**。
    # 这一条就盯那句话在不在 —— 它比一条测不出来的 409 有用。
    两数 = ((det2 or {}).get("draft_revision"), (det2 or {}).get("revision"))
    ck("两个数都给出来了(而且现在它们一起涨 —— "
       "**所以拿错也不会报错,只能靠说明拦**)",
       all(isinstance(x, int) for x in 两数), {"两数": 两数})
    ck("**note 里明说认哪一个**(运行时拦不住拿错,这是唯一的防线)",
       "draft_revision" in ((det2 or {}).get("note") or ""),
       ((det2 or {}).get("note") or "")[:70])

    # ── Schema 契约校验:**冻结时就拦,不等到模型调用那一刻** ──────────
    #
    # ⚠️ 2026-10-02 查出来的缺口:冻结工具版本时**完全不验**那份 Schema
    # 用的关键字校验器认不认。于是这条链一路没人拦:
    #
    #   界面保存成功 → 冻结成版本成功 → 绑进 Agent 成功 → 发布成功
    #   → 模型第一次真的调用 → 网关报「不支持的关键字」
    #
    # 而那时报出来的是**「工具调用失败」**,
    # 不是「这个 Schema 当初就不该被接受」。
    # 第三份规格 §8.3 最后一句说的正是这件事。
    print("\n▸ Schema 契约校验:冻结时就拦住校验器认不下来的那些")
    码, det3, _ = 打("GET", f"{P}/tools/{tid}")
    关键字 = (det3 or {}).get("可用的Schema关键字")
    # ⚠️ 这一条盯的是「**清单从接口来,不是前端硬编**」。
    # 前端硬编的那份会和后端漂 —— 而漂开时界面放过去的 Schema
    # 会在模型第一次真的调用那一刻才失败。
    ck("详情给出 `可用的Schema关键字`(**界面别硬编** —— "
       "硬编的那份会和后端漂)",
       isinstance(关键字, list) and len(关键字) >= 8
       and "properties" in 关键字, 关键字)
    ck("**明说了这份清单别硬编**(说明在,人才知道不该抄)",
       bool((det3 or {}).get("⚠️Schema别硬编")),
       str((det3 or {}).get("⚠️Schema别硬编") or "")[:40])
    # ⚠️ **拿清单之外的关键字去冻结,必须被拦。**
    # `pattern` 是最像会被人用的那一个(正则约束),而校验器不支持它。
    坏键 = "pattern"
    ck(f"对照:`{坏键}` 确实**不在**那份清单里(否则下面那条是空跑)",
       isinstance(关键字, list) and 坏键 not in 关键字, 关键字)
    码, 体, _ = 打("POST", f"{P}/tools/{tid}/versions", {
        "给模型的说明": "闭环测试:用一个校验器不支持的关键字",
        "入参": {"type": "object",
               "properties": {"q": {"type": "string", 坏键: "^/"}}},
        "幂等策略": "按 logical_action_id 去重",
    })
    闸 = ((体 or {}).get("field_errors") or {}).get("闸") or []
    ck(f"用 `{坏键}` 冻结版本 → **422 被拦**"
       "(不拦的话,它会在模型第一次真的调用那一刻才失败)",
       码 == 422, {"码": 码})
    ck("而且理由**点名那个关键字**"
       "(只说「Schema 不合法」的话,人要对着十几个字段猜)",
       any(坏键 in str(x) for x in 闸) or 坏键 in str(体),
       (闸 or [str(体)[:80]])[0][:110])
    # ⚠️ **正向对照**:合法的 Schema 要过得去 ——
    # 少了这一条,一个「什么都拦」的实现也能让上面两条绿。
    码, 体, _ = 打("POST", f"{P}/tools/{tid}/versions", {
        "给模型的说明": "闭环测试:合法 Schema 该过",
        "入参": {"type": "object", "properties": {"q": {"type": "string"}},
               "required": ["q"]},
        "幂等策略": "按 logical_action_id 去重",
    })
    ck("对照:合法 Schema 冻结 → 201(**一个什么都拦的实现过不了这条**)",
       码 == 201, {"码": 码})

    清掉()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(咬合建的已清)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
