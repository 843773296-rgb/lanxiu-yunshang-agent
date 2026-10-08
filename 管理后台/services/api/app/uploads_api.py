#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件上传(规格 §17.1 的「文件上传」那一组)。

    POST /uploads                 要一个受限上传地址
    PUT  /uploads/{id}/bytes      把字节传上来   ← **契约里原本没有,见下**
    POST /uploads/{id}/complete   上传完成,服务端校验

## ⚠️ 为什么多了一条 `PUT .../bytes`

规格默认 S3 兼容对象存储,于是「上传地址」是一个**预签名 URL** ——
字节直接进对象存储,后端只发地址、不碰字节。

首版没有对象存储(README 里登记过的偏离:本机没 Compose 起不了 MinIO,
用文件系统适配器顶着)。**文件系统没有预签名 URL 这个东西** ——
于是必须有一条自己的接收端,否则 `complete` 永远算不出哈希:
它要哈希的那份字节根本没有任何途径到服务端。

所以这条接口是**偏离的一部分**,不是新功能:

    接了对象存储之后 → 这条接口消失,`上传地址` 变成预签名 URL,
                      `complete` 从对象存储读字节(改 `storage.读出`)

写进契约登记表而不是偷偷加,是因为一条**没登记的接口不会出现在任何清单里** ——
于是「接 S3 时要删掉它」这件事没有任何地方记着。

## 三条已经写进契约备注的决定,这里不许绕过

    ① **校验失败是终态,不回「待上传」** —— 同一个坏文件重传还是坏的;
      要传新文件就新建一条上传,旧那条留着当证据
    ② **`已放弃`(要了地址没传)和「传了但没过」分得开** —— 前者没花存储
    ③ **`content_hash` 服务端算**,不信客户端报的

## 幂等:靠**状态**,不靠幂等键

登记表里 `complete` 标的是**不要**幂等键,而它仍然是幂等的 ——
重复调用会读出上一次存下的结论并原样返回。

这比幂等键**强**:幂等键只保证「同一次点击不重复执行」,
状态保证的是「无论谁、隔多久、用什么键再调,结论都是同一个」。
要一个对结论没有任何影响的头,是**摆样子** ——
而摆样子的必填头会让人以为这条接口有外部副作用。

## 校验为什么不在这里实现

全在 `knowledge/upload_rules.py`(纯逻辑,零 IO)。
这个文件只做三件带 IO 的事:查权限、读写库、读写存储。
"""
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge"))

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

import states as ST
import storage as OS_
import upload_rules as UR
from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 状态名从契约来,**不在这里写字符串字面量** —— 写死的话改状态机不会有任何地方报错
_机 = ST.找("upload")
待上传, 已上传, 已校验, 校验失败, 已放弃 = (
    "待上传", "已上传", "已校验", "校验失败", "已放弃")
for _s in (待上传, 已上传, 已校验, 校验失败, 已放弃):
    assert _s in _机["状态"], f"{_s} 不在 upload 状态机里 —— 契约和实现分叉了"


def _新id():
    return f"up_{uuid.uuid4().hex[:12]}"


def _年月():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _取(c, 项目, 上传id):
    r = c.execute(text("""select * from uploads
                         where project_id=:p and id=:i and archived_at is null"""),
                  {"p": 项目, "i": 上传id}).mappings().first()
    if not r:
        # 404 而不是 403:**不泄露「这个 ID 在别的项目里存在」**
        raise _错(404, "NOT_FOUND", "没有这条上传记录",
                  "重新点一次「加资料」要一个新的上传地址")
    return dict(r)


def _对外(u, *, project_id):
    """对外形状。**`能引用吗` 是显式字段,不让调用方自己从 status 推。**

    让调用方推的代价:四个状态里只有一个能引用,而推错的那个方向
    (把 `已上传` 当能用)正是规格 §17.1 专门点出来要防的。
    """
    return {
        "id": u["id"], "状态": u["status"], "file_name": u["file_name"],
        "byte_count": u["byte_count"], "content_type": u["content_type"],
        "content_hash": u["content_hash"],
        "能引用吗": u["status"] == 已校验,
        "是终态吗": u["status"] in _机["终态"],
        "校验详情": u["verify_detail"],
        "created_at": u["created_at"], "updated_at": u["updated_at"],
    }


# ── ① 要一个上传地址 ────────────────────────────────────────────────
@router.post(前缀 + "/uploads", status_code=201)
async def 要上传地址(project_id: str, request: Request,
               me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """建一条 `待上传`,返回上传地址。

    入参:`{file_name, byte_count, content_type?}`

    ⚠️ **后缀和大小在这一步就判** —— 让人先传完 5 MB 再说「不支持 PDF」
    是白花的往返,而且他会以为是网络问题。
    """
    体 = await request.json()
    文件名 = (体.get("file_name") or "").strip()
    声明 = 体.get("byte_count")
    类型 = (体.get("content_type") or "").strip() or None

    坏 = {}
    行, 为什么 = UR.名字过得去吗(文件名)
    if not 行:
        坏["file_name"] = 为什么
    行, 为什么 = UR.声明字节数过得去吗(声明)
    if not 行:
        坏["byte_count"] = 为什么
    if 坏:
        raise _错(422, "VALIDATION", "这个文件收不了",
                  "换成 " + "、".join(UR.支持的后缀()) + f",且不超过 {UR.最大字节数} 字节",
                  field_errors=坏)

    上传id = _新id()
    键 = OS_.建键(项目id=project_id, 上传id=上传id, 文件名=文件名, 年月=_年月())
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        c.execute(text("""insert into uploads
            (id, organization_id, project_id, created_at, created_by, updated_at,
             revision, file_name, byte_count, content_type, object_key, status)
            values (:i,:o,:p, now(), :by, now(), 1, :fn, :bc, :ct, :ok, :st)"""),
                  {"i": 上传id, "o": org, "p": project_id, "by": me.user_id,
                   "fn": 文件名, "bc": 声明, "ct": 类型, "ok": 键, "st": 待上传})
    基 = 前缀.format(project_id=project_id)
    return {
        "id": 上传id, "状态": 待上传,
        "上传地址": f"{基}/uploads/{上传id}/bytes",
        "地址用法": "PUT,请求体就是文件字节(Content-Type: application/octet-stream)",
        "完成地址": f"{基}/uploads/{上传id}/complete",
        "note": ("**传完还要调一次完成接口** —— 字节到了不等于内容可用(§17.1);"
                 "只有服务端校验通过的才算文件引用"),
        "偏离": ("首版没有对象存储(文件系统适配器),所以上传地址是**本服务的接收端**,"
               "不是预签名 URL。接了 S3 之后这条接口消失,这里会变成预签名 URL"),
    }


# ── ② 传字节(偏离的一部分)──────────────────────────────────────────
@router.put(前缀 + "/uploads/{upload_id}/bytes")
async def 传字节(project_id: str, upload_id: str, request: Request,
             me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """接收字节,推到 `已上传`。**这一步不校验内容** —— 校验在 `complete`。

    为什么分两步而不是一步做完:对象存储那条路上,字节根本不经过后端 ——
    后端只能在「客户端说传完了」之后才有机会校验。
    **这一版也照那个时序做**,否则接 S3 时时序要重写一遍,
    而重写时序的地方正是状态机会悄悄少一档的地方。

    ⚠️ 只有 `待上传` 能传。已经传过的**不许覆盖** —— 见 `storage.py`:
    被覆盖的那份的哈希可能已经写进库里,于是库说「校验过」而字节不是那份了。
    """
    with 连接() as c:
        u = _取(c, project_id, upload_id)
    if u["status"] != 待上传:
        raise _错(409, "UPLOAD_NOT_PENDING",
                  f"这条上传是「{u['status']}」,不能再传字节",
                  ("要传新文件请重新要一个上传地址。"
                   if u["status"] in _机["终态"] else
                   "字节已经到了,下一步是调完成接口做校验"))
    字节 = await request.body()
    if not 字节:
        # ⚠️ 空 body 不落存储也不推状态:留在 `待上传` 让他重传。
        # 落下去的代价是产生一条「已上传的空文件」—— 而它会占一格状态、
        # 一份存储,只为了在 complete 时被拒。
        raise _错(422, "EMPTY_BODY", "请求体里没有字节",
                  "PUT 的 body 就是文件内容本身,别用表单包一层")
    if len(字节) > UR.最大字节数:
        raise _错(422, "TOO_LARGE",
                  f"收到 {len(字节)} 字节,上限 {UR.最大字节数}",
                  "一份到这个量级的纯文本资料该拆成几篇")
    try:
        存 = OS_.写入(u["object_key"], 字节)
    except OS_.存不了 as e:
        # **存储问题和内容不合格分开**:前者要运维处理,后者要用户重传
        raise _错(500, "OBJECT_STORE_FAILED", str(e)[:300],
                  "存储层没写成功 —— 这条上传还是「待上传」,可以直接重试")
    with 事务() as c:
        c.execute(text("""update uploads
                             set status=:st, updated_at=now(),
                                 revision=coalesce(revision,0)+1
                           where project_id=:p and id=:i and status=:老"""),
                  {"st": 已上传, "p": project_id, "i": upload_id, "老": 待上传})
    return {"id": upload_id, "状态": 已上传, "收到字节数": 存["字节数"],
            "note": ("**字节到了,但还不能引用** —— 下一步调完成接口做校验(§17.1)。"
                     "现在这条记录的 `能引用吗` 是 false"),
            "完成地址": f"{前缀.format(project_id=project_id)}/uploads/{upload_id}/complete"}


# ── ③ 完成:服务端校验 ──────────────────────────────────────────────
@router.post(前缀 + "/uploads/{upload_id}/complete")
def 完成(project_id: str, upload_id: str,
       me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """服务端算哈希 + 校验,推到 `已校验` / `校验失败`。**幂等(靠状态)。**

    校验查什么全在 `knowledge/upload_rules.py`,这里只做 IO。
    最重要的一条写在那个文件头:**校验真的调一次解析器** ——
    「这份字节能不能用」只有真正的消费者答得准。

    ⚠️ 校验没过**不是 4xx**:请求本身是成功的(我们确实校验了,并把结论存下来了)。
    返回 200 + `通过=false`。判成 4xx 的代价是前端会把它当「请求出错」重试,
    而重试一万次结论都一样 —— **一个坏文件不是一次失败的请求**。
    """
    with 连接() as c:
        u = _取(c, project_id, upload_id)

    if u["status"] in (已校验, 校验失败):
        # 幂等:读出上一次的结论原样返回。**不重新校验** ——
        # 重新校验会让同一条记录在解析器升级后翻案,而它的哈希已经被别处引用了。
        return {**_对外(u, project_id=project_id), "通过": u["status"] == 已校验,
                "note": "**已经校验过了,返回上一次的结论**(幂等靠状态,不靠幂等键)"}
    if u["status"] == 待上传:
        raise _错(409, "NO_BYTES_YET", "字节还没到,没什么可校验的",
                  f"先 PUT 到 {前缀.format(project_id=project_id)}"
                  f"/uploads/{upload_id}/bytes")
    if u["status"] == 已放弃:
        raise _错(409, "UPLOAD_ABANDONED", "这条上传已经放弃了",
                  "重新要一个上传地址")

    try:
        字节 = OS_.读出(u["object_key"])
    except OS_.存不了 as e:
        # ⚠️ **不标成「校验失败」** —— 库里记着键而存储里没有,
        # 这是**两边不一致**,不是「用户传了个坏文件」。
        # 标成校验失败的代价:用户看到「你的文件不合格」,而文件根本没问题。
        raise _错(500, "OBJECT_MISSING", str(e)[:300],
                  "库里记着这个对象键而存储里读不到 —— 这是服务端不一致,"
                  "不是文件的问题。请报给运维,别让用户重传")

    结 = UR.校验(字节, 文件名=u["file_name"], 声明字节数=u["byte_count"])
    新状态 = 已校验 if 结["通过"] else 校验失败
    # 问契约,不自己查表 —— `能不能走` 对认不出的状态当场抛
    assert ST.能不能走("upload", 已上传, 新状态), (
        f"契约不允许 {已上传} → {新状态} —— 状态机和实现分叉了")
    详 = {"通过": 结["通过"], "没过的规则": 结["没过的规则"],
         "理由们": 结["理由们"], "细节": 结["细节"],
         "规则全集": list(UR.规则们), "校验时间": datetime.now(timezone.utc).isoformat()}
    with 事务() as c:
        n = c.execute(text("""update uploads
                                 set status=:st, content_hash=:h,
                                     byte_count=:bc, verify_detail=cast(:vd as jsonb),
                                     updated_at=now(), revision=coalesce(revision,0)+1
                               where project_id=:p and id=:i and status=:老"""),
                      {"st": 新状态, "h": 结["内容哈希"],
                       # ⚠️ `byte_count` 改成**实际收到的**:声明值已经进了校验详情,
                       # 而库里那一列以后要用来算配额 —— 配额要算真实占用
                       "bc": 结["细节"]["实际字节数"],
                       "vd": __import__("json").dumps(详, ensure_ascii=False),
                       "p": project_id, "i": upload_id, "老": 已上传}).rowcount
    if n == 0:
        # 并发:另一个请求已经把它推走了。**读出它的结论,不报错** ——
        # 两个并发的 complete 在同一份字节上结论必然相同。
        with 连接() as c:
            u2 = _取(c, project_id, upload_id)
        return {**_对外(u2, project_id=project_id), "通过": u2["status"] == 已校验,
                "note": "并发:另一个请求先校验完了,返回它的结论"}

    with 连接() as c:
        u3 = _取(c, project_id, upload_id)
    出 = {**_对外(u3, project_id=project_id), "通过": 结["通过"]}
    出["note"] = ("**已校验 —— 现在才算文件引用**(§17.1)"
                  if 结["通过"] else
                  "**校验失败,而且这是终态** —— 同一个坏文件重传还是坏的;"
                  "要传新文件请重新要一个上传地址,这一条留着当证据")
    return 出


# ── 列表(给界面看「传过什么、哪些没过」)────────────────────────────
@router.get(前缀 + "/uploads")
def 上传列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
          status: str = Query(None), limit: int = Query(20, ge=1, le=100)):
    """上传列表。**校验失败的也要列出来** —— 它们是证据。

    一个只列成功项的列表会让人以为「我没传过这个文件」,
    于是他再传一次同一个坏文件。
    """
    if status and status not in _机["状态"]:
        raise _错(422, "VALIDATION", f"没有「{status}」这个状态",
                  "有的是:" + "、".join(_机["状态"]),
                  field_errors={"status": "不在状态机里"})
    # ⚠️ 下面那句 `cast(:st as text)` 不是多余的:一个只出现在 `IS NULL` 里的
    # 绑定参数没有任何类型线索,PostgreSQL 直接报
    # `could not determine data type of parameter`。今天这是同一族的第三次。
    #
    # ⚠️ 说明写在**这里**(Python 注释)而不是 SQL 注释里 ——
    # `text()` 对 `--` 不透明,SQL 注释里的 `:st` 会被当成一个绑定参数。
    # 这一条也是今天第二次踩,两次都是 `tools/sql_lint.py` 抓出来的。
    with 连接() as c:
        rs = c.execute(text("""
            select *, count(*) over () 全量 from uploads
             where project_id=:p and archived_at is null
               and (cast(:st as text) is null or status = cast(:st as text))
             order by created_at desc limit :n
        """), {"p": project_id, "st": status, "n": limit}).mappings().all()
    出 = [_对外(dict(r), project_id=project_id) for r in rs]
    return {"items": 出, "next_cursor": None,
            "total": (int(rs[0]["全量"]) if rs else 0), "这一页几条": len(出),
            "能引用的": sum(1 for d in 出 if d["能引用吗"]),
            "note": "**`能引用的` 通常小于 total** —— 只有 `已校验` 算文件引用"}
