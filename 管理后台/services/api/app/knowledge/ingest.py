#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一个**已校验的上传**变成知识库里的资料(文档 + 版本 + 片段)。

    上传(已校验) → documents → document_versions → chunks

## 四条决定,每一条都有一个「不报错的坏法」在后面

**① 只收 `已校验` 的上传。**
收 `已上传` 的等于把规格 §17.1 那句话作废 —— 而它作废之后,
坏文件不会在这里被拦,会在**建索引时**炸,那时错误指向解析器。

**② `object_key` 直接复用上传那个键,不复制字节。**
复制的代价是双倍存储,和**两份可能分叉** —— 而分叉之后两边的 `content_hash`
都还对得上各自的字节,没有任何一层会发现。
复用还顺带给了 provenance:`source_info.upload_id` 指回那次上传,
于是「这一版资料是谁什么时候传的、校验详情是什么」有地方查。

**③ 幂等靠 `content_hash`,不靠文件名也不靠时间。**
同一份内容重复提交**不新建版本**(和 `tools/ingest_lanxiu.py` 一致)。
靠文件名的坏法:同名不同内容被当成「没变」,新内容永远进不去索引。

**④ 版本和片段在**同一个事务**里写。**
一个「有版本、没片段」的文档版本,检索时只是少返回几条 —— **不报错**。
而它在界面上看起来是一份正常的资料。

## ⚠️ `document_versions.object_key` 这一列现在有两个含义

`tools/ingest_lanxiu.py` 塞的是**仓库内相对路径**,这里塞的是**对象存储键**。
今天没有任何代码读这一列(正文在 `chunks` 里),所以这个矛盾是**潜伏的** ——
它会咬第一个想读原文的人(「查看原文」按钮、重新切片),
而那时他会以为是文件丢了。

所以这个文件提供 `原文键(版本行)`:它**不猜**,而是问 `source_info.存储`。
没有那个字段的老行会**当场抛**,不会退回「当相对路径试一次」——
猜对了没人知道,猜错了报出来的是「文件不存在」,而根因是这一列有两个含义。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

import chunker as C
import parser as P
import storage as OS_

已校验 = "已校验"
存储标记 = "对象存储"          # 写进 source_info.存储,认出这一列的含义
仓库路径标记 = "仓库相对路径"

# ⚠️ **仓库根只在这里算一次。** 第一版 `tools/backfill_object_keys.py` 里
# 又算了一遍,两处**立刻就分叉了**(这里少数了两层 dirname,
# 于是读原文去找 `管理后台/services/业务决策/…`,报的是「文件不存在」)。
# 又一次「两份清单迟早分叉」,而这次是在第一次写的时候就分叉了。
#
# 层数:knowledge → app → api → services → 管理后台 → 澜绣云裳agent
仓库根 = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))


class 不能用这个上传(Exception):
    """上传还不能当资料用。**当场报,不静默降级。**"""


class 键的含义不明(Exception):
    """`object_key` 这一行不知道是哪种键。**不猜。**"""


def 检查上传可用(u):
    """纯逻辑:这条上传能不能当资料用。返回 (行不行, 为什么)。"""
    if not u:
        return False, "没有这条上传"
    st = u.get("status")
    if st == 已校验:
        return True, ""
    if st == "已上传":
        return False, ("这条上传只是「字节到了」,**还没校验** —— "
                       "规格 §17.1:服务端校验之后才算文件引用。"
                       "先调一次完成接口;**不要在这里放行**:"
                       "放行的话坏文件会在建索引时才炸,而那时错误指向解析器")
    if st == "校验失败":
        没过 = ((u.get("verify_detail") or {}).get("没过的规则")) or []
        return False, (f"这条上传**校验没过**({'、'.join(没过) or '详见校验详情'})—— "
                       f"它是终态。要用新文件请重新走一遍上传")
    return False, f"这条上传是「{st}」—— 只有「{已校验}」的能当资料用"


def 原文键(版本行):
    """从一行 `document_versions` 取出「怎么读原文」。返回 (种类, 键)。

    ⚠️ **不猜。** 见文件头:这一列现在有两个含义,而猜错的表现是
    「文件不存在」,根因却是列的含义不明 —— 那是两件完全不同的事。
    """
    src = (版本行 or {}).get("source_info") or {}
    存 = src.get("存储")
    if 存 == 存储标记:
        return 存储标记, 版本行["object_key"]
    if 存 == 仓库路径标记:
        return "仓库相对路径", 版本行["object_key"]
    raise 键的含义不明(
        f"这一行没写 `source_info.存储`,所以不知道 `object_key` "
        f"({str((版本行 or {}).get('object_key'))[:40]!r}) 是对象存储键还是仓库路径。"
        f"**不退回「当相对路径试一次」** —— 猜对了没人知道,"
        f"猜错了报出来的是「文件不存在」,而根因是这一列有两个含义。"
        f"老数据补这个字段见 tools/backfill_object_keys.py")


def 读原文(版本行):
    种类, 键 = 原文键(版本行)
    if 种类 == 存储标记:
        return OS_.读出(键).decode("utf-8")
    路 = os.path.join(仓库根, 键)
    if not os.path.isfile(路):
        raise 键的含义不明(
            f"这一行标的是「{仓库路径标记}」,而仓库根下没有 {键!r} —— "
            f"**这不是「文件丢了」**:它可能是标错了(见 "
            f"tools/backfill_object_keys.py 的判据),也可能是那份资料"
            f"从来没被存过。两件都要人看,不该在这里被当成 IO 错误")
    with open(路, encoding="utf-8") as f:
        return f.read()


def _新(前缀):
    import uuid
    return f"{前缀}_{uuid.uuid4().hex[:12]}"


def 收一份资料(c, *, 组织, 项目, 知识库id, 上传, 谁, 文档id=None, 名字=None):
    """把一个已校验的上传收成「文档版本 + 片段」。**调用方给连接,这里不开事务。**

    `文档id` 给了就是**发新版本**,不给就是**新建文档**。
    返回 dict(文档id, 版本id, 片段数, 新建了版本吗, 说明)。
    """
    行, 为什么 = 检查上传可用(上传)
    if not 行:
        raise 不能用这个上传(为什么)

    哈希 = 上传["content_hash"]
    if not 哈希:
        # 已校验而没有哈希 —— 不可能,除非有人手改了库。**当场抛。**
        raise 不能用这个上传(
            "这条上传是「已校验」却没有 `content_hash` —— "
            "两者必须同时成立(哈希就是校验那一步算的)。库里被手改过")

    if 文档id is None:
        文档id = _新("doc")
        c.execute(text("""insert into documents
            (id, organization_id, project_id, knowledge_base_id, source_info,
             created_at, created_by, revision)
            values (:i,:o,:p,:k, cast(:si as jsonb), now(), :by, 1)"""),
                  {"i": 文档id, "o": 组织, "p": 项目, "k": 知识库id, "by": 谁,
                   "si": json.dumps({"名字": 名字 or 上传["file_name"],
                                     "来源": "界面上传",
                                     "upload_id": 上传["id"]},
                                    ensure_ascii=False)})
        新文档 = True
    else:
        有 = c.execute(text("""select 1 from documents
                             where project_id=:p and id=:i and knowledge_base_id=:k
                               and archived_at is null"""),
                      {"p": 项目, "i": 文档id, "k": 知识库id}).first()
        if not 有:
            raise 不能用这个上传(f"这个知识库下没有文档 {文档id}")
        新文档 = False

    # 幂等:**同一份内容不新建版本**
    已有 = c.execute(text("""select id, revision from document_versions
                           where project_id=:p and document_id=:d
                             and content_hash=:h"""),
                    {"p": 项目, "d": 文档id, "h": 哈希}).mappings().first()
    if 已有:
        片段数 = c.execute(text("""select count(*) from chunks
                                 where project_id=:p and document_version_id=:v"""),
                        {"p": 项目, "v": 已有["id"]}).scalar()
        return dict(文档id=文档id, 版本id=已有["id"], 片段数=片段数,
                    新建了版本吗=False, 新建了文档吗=新文档,
                    说明=(f"**内容没变**(哈希一样),没有新建版本 —— "
                        f"复用第 {已有['revision']} 版。"
                        f"幂等靠内容哈希,不靠文件名也不靠时间"))

    原文 = 读原文({"object_key": 上传["object_key"],
                "source_info": {"存储": 存储标记}})
    解析 = P.解析(原文, 文件名=上传["file_name"])
    最大 = c.execute(text("""select coalesce(max(revision),0) from document_versions
                           where project_id=:p and document_id=:d"""),
                    {"p": 项目, "d": 文档id}).scalar()
    版本id = _新("dv")
    c.execute(text("""insert into document_versions
        (id, organization_id, project_id, document_id, object_key, content_hash,
         effective_at, revision, created_at, created_by, source_info)
        values (:i,:o,:p,:d,:ok,:h, now(), :rev, now(), :by, cast(:si as jsonb))"""),
              {"i": 版本id, "o": 组织, "p": 项目, "d": 文档id,
               # ⚠️ **复用上传那个键,不复制字节**(见文件头第 ② 条)
               "ok": 上传["object_key"], "h": 哈希, "rev": 最大 + 1, "by": 谁,
               "si": json.dumps({"存储": 存储标记,
                                 "upload_id": 上传["id"],
                                 "file_name": 上传["file_name"]},
                                ensure_ascii=False)})

    切 = C.切(解析, 文档版本id=版本id)
    for s in 切["片段们"]:
        c.execute(text("""insert into chunks
            (id, organization_id, project_id, document_version_id, section_path,
             section_titles,
             ordinal, text, text_hash, token_count, chunker_version, parser_version,
             created_at, created_by, revision)
            values (:i,:o,:p,:v,:sp, cast(:st as jsonb),
                    :ord,:t,:th,:tk,:cv,:pv, now(), :by, 1)"""),
                  {"i": _新("ch"), "o": 组织, "p": 项目, "v": 版本id,
                   "sp": s["section_path"],
                   # ⚠️ **列表那一份也落库。** `section_path` 是用 ` / ` 拼的,
                   # 而全库 29 个标题名字里带 ` / ` —— 拼起来就拆不回去
                   # (802 个片段里 44 个,5.5%)。
                   # > 路径的无歧义表示是列表,不是用分隔符拼起来的字符串。
                   # `section_path` 一个字不改(对外引用和显示都用它);
                   # **要按级别做事的一律读这一列**。
                   "st": json.dumps(s.get("节标题们") or [], ensure_ascii=False),
                   "ord": s["ordinal"], "t": s["text"],
                   "th": s["text_hash"], "tk": s["token_count"],
                   # ⚠️ 切它的版本记在行上 —— 索引指纹要用它。
                   # 从代码常量读会隐含「库里的片段是当前版本切的」,而它失效时不报错。
                   "cv": 切["切片器版本"], "pv": 切["解析器版本"], "by": 谁})

    return dict(文档id=文档id, 版本id=版本id, 片段数=len(切["片段们"]),
                新建了版本吗=True, 新建了文档吗=新文档,
                说明=(f"第 {最大 + 1} 版,切出 {len(切['片段们'])} 个片段。"
                    f"⚠️ **还不能检索** —— 要再建一次索引"))
