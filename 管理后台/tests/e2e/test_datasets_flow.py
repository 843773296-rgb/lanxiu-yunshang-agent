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
            "全是 mock 产物的那一份", "训练档但没复核的那一份", "一个样本都没有的那一份"]
    缺 = [n for n in 需要的 if n not in 份]
    if 缺:
        print(f"     缺这几份种子:{缺} —— 先 `python3 tools/seed_datasets.py`")
        sys.exit(1)

    for n in 需要的[1:]:
        ck(f"列表上「{n}」标着导不出来,并说了卡在哪",
           份[n]["能导出吗"] is False and 份[n]["卡在哪"], 份[n]["能导出吗"])
    ck("列表上「导出能过的那一份」标着能导出", 份[需要的[0]]["能导出吗"] is True)

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
