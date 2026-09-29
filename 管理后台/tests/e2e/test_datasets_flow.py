#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据集与训练导出端到端(§17.4 微调链的前半段)。

## 这一份守的两句话

**① 「什么都没有」和「成功地什么都没有」必须长得不一样。**
   过完闸一条样本不剩 → **422**,不是 200 加一个空的 `.jsonl`。
   空文件看起来是完全成功的,而下游会拿它去训练。

**② 一个声称脱过而实际没脱的接口,比明说「没脱」危险得多。**
   脱敏器还没选型,所以声明了「需要脱敏」的数据集**拿不到不脱的版本**。

## ⚠️ 顺路那条是最会骗人的一条

第一版我先测顺路(200 + NDJSON),绿了就以为这一组做完了 ——
而**六条拒全是 500**:`_错()` 不收任意关键字,我传了个 `账=账`。
顺路那条恰好不走那段代码。
所以这一份**每一道闸都单独有一条**,而且**都断言具体的 `code`**,
不只断言「不是 2xx」—— 500 也不是 2xx。

⚠️ 前提 `make dev` + `python3 tools/seed_datasets.py`。连不上就退非 0,不静默跳过。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []

# ⚠️ **U004(annotator)不是随便挑的。** 导出要两样:基础权限「改训练样本」
# 和字段级授权「查看敏感输入/独立测试答案」。U001 是 admin,但那条字段级授权
# 对 admin 是**可授权**(默认关闭)—— 所以 admin 导出会被 403 拦住,**而那是对的**。
导出的人 = os.environ.get("AIMC_EXPORTER", "U004")


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 头=None, 要文本=False):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 导出的人)
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            身 = r.read()
            if 要文本:
                return r.status, 身.decode("utf-8"), dict(r.headers)
            return r.status, json.loads(身 or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null"), dict(e.headers)
        except Exception:
            return e.code, None, {}
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


def 找(名):
    码, 体, _ = 打("GET", f"{P}/datasets")
    if 码 != 200:
        print(f"     列表拿不到(HTTP {码}) —— 先 `make dev`"); sys.exit(1)
    for d in 体.get("数据集", []):
        if d["名字"] == 名:
            return d
    return None


def main():
    print("\n\033[1m▸ 数据集与训练导出 · 七道闸每道一条\033[0m")

    # ── 一、列表:能不能导出是**现算**的,而且卡在哪要说出来 ─────────────
    码, 体, _ = 打("GET", f"{P}/datasets")
    ck("列表 200", 码 == 200, 码)
    ck("列表**不含样本内容**(只给计数)",
       all("样本" not in json.dumps(d, ensure_ascii=False) or "样本数" in d
           for d in 体.get("数据集", []))
       and all("content" not in json.dumps(d) for d in 体.get("数据集", [])),
       "列表里出现 content 就是把独立测试答案漏出去了")

    份 = {d["名字"]: d for d in 体["数据集"]}
    需要的 = ["导出能过的那一份", "声明了需要脱敏的那一份", "同一组跨了分集的那一份",
            "全是 mock 产物的那一份", "训练档但没复核的那一份", "一个样本都没有的那一份",
            "来源没做过覆盖验证的那一份", "里面真带客户信息的那一份",
            "全部都带客户信息的那一份"]
    缺 = [n for n in 需要的 if n not in 份]
    if 缺:
        print(f"     缺这几份种子:{缺} —— 先 `python3 tools/seed_datasets.py`")
        sys.exit(1)

    # ⚠️ 这两份**不在这一组**:
    #   · 「里面真带客户信息的那一份」能导出,只是会隔离掉命中的两条
    #   · 「全部都带客户信息的那一份」列表上看是能导出的 —— **而这是诚实的**:
    #     内容级那道闸要逐条读 content,列表只拿形状,判不了。
    #     所以列表必须**明说还有一道**(下面单独有一条断言),
    #     而不是假装自己判全了。
    内容级的 = ("里面真带客户信息的那一份", "全部都带客户信息的那一份")
    for n in [x for x in 需要的[1:] if x not in 内容级的]:
        ck(f"列表上「{n}」标着导不出来,并说了卡在哪",
           份[n]["能导出吗"] is False and 份[n]["卡在哪"], 份[n]["能导出吗"])
    ck("列表上「导出能过的那一份」标着能导出", 份[需要的[0]]["能导出吗"] is True)
    for n in 内容级的:
        ck(f"「{n}」列表说能导出,**但明说还有一道看内容的闸**",
           份[n]["能导出吗"] is True and 份[n].get("还有一道看内容的闸"),
           份[n].get("还有一道看内容的闸"))

    # ── 一点五、建数据集:**不给脱敏策略也能建,但要当场说清后果** ────────
    #    「先建起来再补声明」是正常顺序,真正不能含糊的是**导出那一刻**。
    #    但如果建的时候一个字都不提,那个人会在几天后才撞上那道闸。
    import uuid as _u
    名 = f"咬合-建数据集-{_u.uuid4().hex[:6]}"
    码, 体, _ = 打("POST", f"{P}/datasets", {"名字": 名, "格式": "qa"})
    ck("POST /datasets 201", 码 == 201 and (体 or {}).get("id"), 码)
    新id = (体 or {}).get("id")
    ck("没给脱敏策略时,返回里**当场点出这会被导出那道闸拦住**",
       "脱敏" in str((体 or {}).get("note")), str((体 or {}).get("note"))[:70])
    码, 体, _ = 打("POST", f"{P}/datasets", {"名字": 名 + "-坏", "格式": ""})
    ck("格式空 → 422(不给默认格式:猜一个会让这份数据以为自己是 qa)", 码 == 422, 码)
    码, 列, _ = 打("GET", f"{P}/datasets")
    刚建 = [d for d in (列 or {}).get("数据集", []) if d["id"] == 新id]
    ck("新建的在列表里,而且标着导不出来(样本一条都没有)",
       bool(刚建) and 刚建[0]["能导出吗"] is False, 刚建 and 刚建[0]["能导出吗"])
    _归档(新id)          # 归档掉,不让咬合数据在列表页上越攒越多

    # ── 二、权限:能改样本 ≠ 能把全部原文带走 ──────────────────────────
    码, 体, _ = 打("GET", f"{P}/datasets/{份['导出能过的那一份']['id']}/export", 谁="U001")
    ck("admin 没有那条字段级授权 → **403**,不是 200",
       码 == 403 and (体 or {}).get("code") == "NEED_CONTENT_GRANT", (码, (体 or {}).get("code")))
    码, 体, _ = 打("GET", f"{P}/datasets/{份['导出能过的那一份']['id']}/export", 谁="U003")
    ck("viewer 连基础权限都没有 → 403", 码 == 403, 码)

    # ── 三、七道闸,每道断言具体的 code ───────────────────────────────
    #    ⚠️ 断言 code 而不是「不是 2xx」—— **500 也不是 2xx**,
    #    而这一组第一版六条拒全是 500(见文件头)。
    闸 = [
        ("一个样本都没有的那一份", "CANNOT_EXPORT", "空集(**必须第一个判** —— 后面每道闸在空集上都恰好通过)"),
        ("汉服工艺问答", "CANNOT_EXPORT", "没声明脱敏策略"),
        ("同一组跨了分集的那一份", "CANNOT_EXPORT", "同组跨分集 → 拒整批"),
        ("训练档但没复核的那一份", "CANNOT_EXPORT", "没复核的不出去"),
        ("全是 mock 产物的那一份", "CANNOT_EXPORT", "mock 产物默认拒"),
        ("声明了需要脱敏的那一份", "REDACTOR_NOT_CHOSEN", "脱敏器还没选型 → 不给不脱的版本"),
    ]
    for 名, 期望code, 说 in 闸:
        d = 份.get(名) or 找(名)
        if not d:
            ck(f"闸:{说}", False, f"找不到「{名}」"); continue
        码, 体, _ = 打("GET", f"{P}/datasets/{d['id']}/export")
        ck(f"闸:{说} → {期望code}",
           码 == 422 and (体 or {}).get("code") == 期望code, (码, (体 or {}).get("code")))

    # 空集那条要**同时**报出「里面有什么」——
    # 报告「我没有 X」时同时报告「我有什么」。
    d = 份["训练档但没复核的那一份"]
    码, 体, _ = 打("GET", f"{P}/datasets/{d['id']}/export")
    账 = ((体 or {}).get("field_errors") or {}).get("账") or ""
    ck("拒的时候同时给「里面到底有什么」(账)", "训练档 2" in 账, 账[:90])

    # 一次报全部拦阻理由,不是一轮修一条
    d = 找("汉服工艺问答")
    ck("「没声明策略」+「一条可训练的都不剩」**一次报两条**",
       len(d["卡在哪"]) >= 2, d["卡在哪"] and len(d["卡在哪"]))

    # ── 四、顺路:真的给 NDJSON,而且头是 ASCII ───────────────────────
    d = 份["导出能过的那一份"]
    码, 文, 头 = 打("GET", f"{P}/datasets/{d['id']}/export", 要文本=True)
    ck("顺路 200", 码 == 200, 码)
    行 = [l for l in 文.strip().split("\n") if l.strip()]
    ck("给的是 NDJSON,每行一条样本", len(行) == 2 and all(json.loads(l) for l in 行), len(行))
    ck("x-sample-count 和行数一致", 头.get("x-sample-count") == str(len(行)),
       (头.get("x-sample-count"), len(行)))
    ck("x-contains-mock: no", 头.get("x-contains-mock") == "no", 头.get("x-contains-mock"))
    # ⚠️ HTTP 头只能 latin-1。这个仓库今天为「协议边界上的中文」付过四次代价。
    ck("响应头全是 ASCII(头只能 latin-1)",
       all(str(v).isascii() for k, v in 头.items() if k.lower().startswith("x-")
           or k.lower() == "content-disposition"),
       [k for k, v in 头.items() if not str(v).isascii()])

    # ── 五、mock:默认拒,显式要才给,而且一路带标记 ────────────────────
    d = 份["全是 mock 产物的那一份"]
    码, 文, 头 = 打("GET", f"{P}/datasets/{d['id']}/export?%E8%A6%81mock=1", 要文本=True)
    ck("显式 `要mock=1` → 200", 码 == 200, 码)
    ck("文件名带 MOCK(一份 mock 产物在数据形状上和真的一模一样)",
       "MOCK" in (头.get("content-disposition") or ""), 头.get("content-disposition"))
    ck("x-contains-mock: yes", 头.get("x-contains-mock") == "yes", 头.get("x-contains-mock"))
    ck("审计里记了这次 mock 导出", _审计有("dataset.export", d["id"]))

    # ── 五点五、第八道闸:敏感信息检测(方案 B 受限首版)─────────────
    #
    # ⚠️ 这一组守的是用户 2026-09-28 明确纠正的那一条:
    # **零命中不等于没有敏感信息** —— 它只说明这几个检测器没找到。
    # 所以放行不靠「扫了一遍干净」,靠**来源在覆盖已验证的白名单里**。
    d = 份["里面真带客户信息的那一份"]
    码, 文, 头 = 打("GET", f"{P}/datasets/{d['id']}/export", 要文本=True)
    ck("带客户信息的那份 → 200(**隔离命中的,放行干净的**,不是整批拒)", 码 == 200, 码)
    行 = [l for l in 文.strip().split("\n") if l.strip()]
    ck("三条里只放行了一条", len(行) == 1 and 头.get("x-sample-count") == "1",
       (len(行), 头.get("x-sample-count")))
    ck("隔离了两条", 头.get("x-quarantined") == "2", 头.get("x-quarantined"))
    ck("**说清是哪一类命中的**(手机号 / 称呼式姓名)",
       "phone" in (头.get("x-quarantined-by") or "")
       and "name-honorific" in (头.get("x-quarantined-by") or ""),
       头.get("x-quarantined-by"))
    # 头只能 latin-1 —— 所以类别名用 ASCII 代号,中文留在审计和 422 正文里
    ck("隔离相关的响应头全是 ASCII",
       all(str(头.get(k, "")).isascii()
           for k in ("x-quarantined", "x-quarantined-by", "x-quarantine-detail")),
       [头.get(k) for k in ("x-quarantined", "x-quarantined-by")])
    ck("放行的那一条里没有手机号",
       行 and "13912345678" not in 行[0], 行[0][:40] if 行 else "")
    ck("审计里记了这次导出(隔离了谁、为什么在那儿)", _审计有("dataset.export", d["id"]))

    # ⚠️ **零命中也不放行** —— 这条是这一版最容易被写回去的地方
    d = 份["来源没做过覆盖验证的那一份"]
    码, 体, _ = 打("GET", f"{P}/datasets/{d['id']}/export")
    ck("来源没做过覆盖验证 → 422(**即使一条都没命中**)",
       码 == 422 and (体 or {}).get("code") == "CANNOT_EXPORT",
       (码, (体 or {}).get("code")))
    理由 = " ".join(((体 or {}).get("field_errors") or {}).get("闸", []))
    ck("拒的理由说的是「没做过覆盖验证」,不是「命中了敏感信息」",
       "覆盖验证" in 理由 and "零命中" in 理由, 理由[:80])
    ck("这条闸在**列表上**也说得出来(界面承诺的和接口做的要一致)",
       d["能导出吗"] is False and any("覆盖验证" in x for x in (d["卡在哪"] or [])),
       d["卡在哪"])

    # 全部命中 → 一条不剩 → **不返回空文件**
    d = 份["全部都带客户信息的那一份"]
    码, 体, _ = 打("GET", f"{P}/datasets/{d['id']}/export")
    ck("两条全命中 → 422 ALL_QUARANTINED(**不返回空的 .jsonl**)",
       码 == 422 and (体 or {}).get("code") == "ALL_QUARANTINED",
       (码, (体 or {}).get("code")))
    隔 = ((体 or {}).get("field_errors") or {}).get("隔离", [])
    ck("逐条说清是哪一类命中的", len(隔) == 2 and all("命中" in x for x in 隔),
       [x[:44] for x in 隔])

    # **对照**:同样零命中、但来源在白名单里的,要放得出去 ——
    # 没有这一条,一个「什么都不放行」的实现照样能让上面全绿。
    d = 份["导出能过的那一份"]
    码, 文, 头 = 打("GET", f"{P}/datasets/{d['id']}/export", 要文本=True)
    ck("对照:来源 seed、零命中 → 照样放行(闸不是一刀切)",
       码 == 200 and 头.get("x-quarantined") == "0", (码, 头.get("x-quarantined")))

    # ── 六、改样本:乐观锁 + 当场报跨分集 ────────────────────────────
    d = 份["同一组跨了分集的那一份"]
    sid, rev = _头一条样本(d["id"])
    码, 体, _ = 打("PATCH", f"{P}/datasets/{d['id']}/samples/{sid}", {"复核状态": "已通过"})
    ck("不带 If-Match → 409", 码 == 409 and (体 or {}).get("code") == "IF_MATCH_REQUIRED",
       (码, (体 or {}).get("code")))
    码, 体, _ = 打("PATCH", f"{P}/datasets/{d['id']}/samples/{sid}", {"复核状态": "已通过"},
                头={"If-Match": "999999"})
    ck("If-Match 不对 → 409 REVISION_CONFLICT",
       码 == 409 and (体 or {}).get("code") == "REVISION_CONFLICT", (码, (体 or {}).get("code")))
    码, 体, _ = 打("PATCH", f"{P}/datasets/{d['id']}/samples/{sid}", {"分集": "训练集"},
                头={"If-Match": str(rev)})
    ck("认不出的分集 → 422(**不收任意字符串**:拼错的分集会自成一档)", 码 == 422, 码)
    码, 体, _ = 打("PATCH", f"{P}/datasets/{d['id']}/samples/{sid}", {"复核状态": "已通过"},
                头={"If-Match": str(rev)})
    ck("改成功 → revision 前进", 码 == 200 and 体.get("revision") == rev + 1,
       (码, (体 or {}).get("revision")))
    ck("改完当场指出这一组跨了分集(不等到导出那一刻才说)",
       (体 or {}).get("跨分集的组") == ["g-同组"], (体 or {}).get("跨分集的组"))

    # ── 七、冻结:固化内容,不是存指针 ────────────────────────────────
    d = 份["一个样本都没有的那一份"]
    码, 体, _ = 打("POST", f"{P}/datasets/{d['id']}/versions")
    ck("冻结空数据集 → 422 CANNOT_FREEZE(这条判据 `evals.可以冻结吗()` 终于被调用了)",
       码 == 422 and (体 or {}).get("code") == "CANNOT_FREEZE", (码, (体 or {}).get("code")))

    d = 份["导出能过的那一份"]
    码, 体, _ = 打("POST", f"{P}/datasets/{d['id']}/versions")
    ck("冻结顺路那份 → 200/201", 码 in (200, 201), 码)
    vid, n = (体 or {}).get("id"), (体 or {}).get("样本数")
    # ⚠️ **前提先断言。** 第一版直接比 `固化数 == n`,而冻结失败时两边都是 None ——
    # `None == None` 成立,于是**冻结 500 的那一轮,后面三条照样打绿**。
    # 同一族:`... or True` 的断言、「判绿看退出码别数 ❌」——
    # **一条在前提不成立时反而通过的判据,比没有这条判据更糟。**
    ck("冻结真的给出了版本号(后面几条的前提)",
       bool(vid) and isinstance(n, int) and n > 0, (vid, n))
    固化数, 老哈希 = _版本形状(vid)
    ck("固化的条数 = 样本数(**不是存指针**)",
       isinstance(固化数, int) and 固化数 > 0 and 固化数 == n, (固化数, n))

    # 同样的字节再冻一次 → **同一个版本号**,不新建。
    # 库里有 `UNIQUE (project_id, dataset_id, content_hash)`,不接住就是 500;
    # 而约束本身是对的:同样的字节两个版本号,「那次评测用的是哪一版」
    # 就有了两个同样成立的答案。
    码, 体2, _ = 打("POST", f"{P}/datasets/{d['id']}/versions")
    ck("内容没变时再冻 → 200 且**同一个版本号**",
       码 == 200 and (体2 or {}).get("id") == vid
       and (体2 or {}).get("新建了吗") is False,
       (码, (体2 or {}).get("id"), (体2 or {}).get("新建了吗")))

    # 改一条样本的内容,冻结的那一版**不许跟着变** —— 这才是「固化」的意思
    sid, rev = _头一条样本(d["id"])
    import time as _t
    码, _, _ = 打("PATCH", f"{P}/datasets/{d['id']}/samples/{sid}",
                {"内容": {"messages": [{"role": "user",
                                      "content": f"改过了 {_t.time()}"}]}},
                头={"If-Match": str(rev)})
    ck("改样本内容 → 200", 码 == 200, 码)
    新固化数, 新哈希 = _版本形状(vid)
    ck("改样本之后,冻结那一版一个字没变",
       isinstance(新固化数, int) and 新哈希 and (新固化数, 新哈希) == (固化数, 老哈希),
       (固化数, 老哈希, 新固化数, 新哈希))

    # ⚠️ **对照**:内容真变了就该冻出**新**版本 ——
    # 没有这一条的话,上面那条「同一个版本号」可能只是因为这个接口
    # **从来不新建**,而那种实现照样能让上面全绿。
    码, 体3, _ = 打("POST", f"{P}/datasets/{d['id']}/versions")
    ck("内容变了之后再冻 → 201 且**新的版本号**",
       码 == 201 and (体3 or {}).get("id") and (体3 or {}).get("id") != vid
       and (体3 or {}).get("新建了吗") is True,
       (码, (体3 or {}).get("id"), vid))

    # ── 样本列表:**改样本的 If-Match 得有地方拿** ──────────────────────
    # ⚠️ 这一组是 2026-09-29 补的,补的是一个洞:
    # `PATCH .../samples/{id}` 的错误提示写着「把**样本详情**里的 revision
    # 放进 If-Match 头」—— 而那个接口当时不存在,**连列样本的接口都没有**;
    # 唯一能读到样本的是导出,而导出在脱敏器没选型之前是 501。
    # > 一句指着不存在的页面的错误提示,比不给提示更糟:
    # > 它让人去做一件做不到的事,而那句话本身读起来完全合理。
    print("\n▸ 样本列表(补的洞:改样本的 If-Match 原来没地方拿)")
    # ⚠️ 挑**真有内容**的那一份 —— 拿「一个样本都没有的那一份」来验
    # 「默认不给原文」会是**空跑**:空列表上所有性质都成立。
    那份 = 份["里面真带客户信息的那一份"]
    # ⚠️ **必须用没有那条字段级授权的身份打。** 这份测试里 `打()` 的默认
    # 身份是 `导出的人`(U004),而**他有**「查看敏感输入」——
    # 用默认身份验「默认不给原文」会是一条**永远绿的判据**。
    码, sl, _ = 打("GET", f"{P}/datasets/{那份['id']}/samples", 谁="U002")
    ck("样本列表 → 200", 码 == 200 and isinstance((sl or {}).get("样本们"), list), 码)
    样本们 = (sl or {}).get("样本们") or []
    ck("每条带**自己的 revision**(改它的 If-Match 认这个,"
       "不是数据集的 revision —— 混起来的表现是 409「这条样本已经被改过」)",
       样本们 and all(isinstance(x.get("revision"), int) for x in 样本们),
       [(x["id"][-6:], x.get("revision")) for x in 样本们[:3]])

    # **这一条是这一组里最要紧的**:样本是真实客户对话。
    ck("**默认不给原文**(样本是真实客户对话 —— 姓名/手机/地址/尺寸)",
       样本们 and all((x.get("内容") or {}).get("原文") is None
                    for x in 样本们 if (x.get("内容") or {}).get("有内容吗")),
       [(x["id"][-6:], (x.get("内容") or {}).get("原文")) for x in 样本们[:3]])
    ck("`看得到原文吗` 明说了这件事(**不让人自己去猜为什么是空的**)",
       (sl or {}).get("看得到原文吗") is False, (sl or {}).get("看得到原文吗"))
    ck("**不给截断版** —— 给的是字数(截到前几个字,那几个字仍然是原文,"
       "而「截断过」会让人以为它安全了)",
       样本们 and all(isinstance((x.get("内容") or {}).get("字数"), int)
                    for x in 样本们),
       [(x.get("内容") or {}).get("字数") for x in 样本们[:3]])
    # ⚠️ **三种情况要长得不一样**:给看 / 不给看 / 本来就是空的。
    ck("有内容但被挡住 vs 本来就是空的,**分得开**(`有内容吗` 这个字段)",
       样本们 and all("有内容吗" in (x.get("内容") or {}) for x in 样本们),
       [(x.get("内容") or {}).get("有内容吗") for x in 样本们[:3]])

    码, sl2, _ = 打("GET", f"{P}/datasets/{那份['id']}/samples", 谁=导出的人)
    ck(f"有「查看敏感输入」授权的人({导出的人})**看得到原文**",
       码 == 200 and (sl2 or {}).get("看得到原文吗") is True,
       (sl2 or {}).get("看得到原文吗"))
    有文 = [x for x in ((sl2 or {}).get("样本们") or [])
           if (x.get("内容") or {}).get("有内容吗")]
    ck("而且原文真的给出来了(给不出来的话上一条是**空跑** ——"
       "「有授权」和「拿到了」是两件事)",
       有文 and (有文[0].get("内容") or {}).get("原文") is not None,
       str((有文[0].get("内容") or {}).get("原文"))[:40] if 有文 else "没有带内容的样本")

    码, 体, _ = 打("GET", f"{P}/datasets/ds_nope_xyz/samples", 谁="U002")
    ck("不存在的数据集 → 404", 码 == 404, 码)
    码, 体, _ = 打("GET",
              f"/api/v1/projects/project_demo_b/datasets/{那份['id']}/samples",
              谁="U002")
    ck("换项目号 → 404(不确认「它在别的项目里存在」)", 码 == 404, 码)

    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


from sqlalchemy import text            # noqa: E402
from db import 连接, 事务               # noqa: E402


def _归档(dsid):
    """把咬合建出来的数据集归档 —— **不 DELETE**。

    删掉的话审计里那条 `dataset.create` 指向一个不存在的 id,
    而审计的价值正在于「事后还查得到当时动了什么」。
    归档是这张表本来就有的表达方式(`archived_at`)。
    """
    with 事务() as c:
        c.execute(text("""update datasets set archived_at=now(), revision=revision+1
                         where project_id=:p and id=:i"""), {"p": 项目, "i": dsid})


def _头一条样本(dsid):
    with 连接() as c:
        r = c.execute(text("""select id, revision from samples
                             where project_id=:p and dataset_id=:d
                             order by id limit 1"""),
                      {"p": 项目, "d": dsid}).mappings().first()
    return (r["id"], int(r["revision"])) if r else (None, 0)


def _版本形状(vid):
    """**只取形状**(条数 + 哈希),不把固化内容读进来 —— 它是真实对话内容。"""
    with 连接() as c:
        r = c.execute(text("""select jsonb_array_length(frozen_samples) n, content_hash h
                             from dataset_versions where id=:i"""),
                      {"i": vid}).mappings().first()
    return (r["n"], r["h"]) if r else (None, None)


def _审计有(action, 目标id):
    with 连接() as c:
        return bool(c.execute(text("""select 1 from audit_events
                                    where project_id=:p and action=:a
                                      and target_ref->>'dataset_id' = :d
                                    limit 1"""),
                              {"p": 项目, "a": action, "d": 目标id}).first())


if __name__ == "__main__":
    sys.exit(main())
