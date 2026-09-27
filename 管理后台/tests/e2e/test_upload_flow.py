#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件上传端到端 —— **把「上传成功不等于内容可用」变成可重跑的断言**。

    POST /uploads                 要一个受限上传地址
    PUT  /uploads/{id}/bytes      传字节(偏离:首版没有对象存储)
    POST /uploads/{id}/complete   服务端校验
    GET  /uploads                 列表(**含校验失败的**)

## 这一份要证明的六件

    ① 后缀 / 大小在**要地址那一步**就拒(不让人先传完 5 MB)
    ② `已上传` 的 `能引用吗` 是 **false** —— 规格 §17.1 的那句话有代码兜着
    ③ `content_hash` 是**服务端算的**(客户端报一个假的,库里不采信)
    ④ **校验没过返回 200 + 通过=false**,不是 4xx —— 坏文件不是一次失败的请求
    ⑤ **校验失败是终态**:再调 complete 返回同一个结论,不重新校验
    ⑥ 列表里 `能引用的 < total` —— 失败的留着当证据

## 前提

要先 `make dev`(服务在 8801)。⚠️ 连不上就**退非 0**,不静默跳过。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
别的项目 = "project_demo_b"
P = f"/api/v1/projects/{项目}"

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 原始=None):
    """`原始` 是 bytes → 当请求体原样发(PUT 字节那条要用)。"""
    数据 = 原始 if 原始 is not None else (
        json.dumps(体).encode() if 体 is not None else None)
    # ⚠️ 路里可能有中文(`?status=已校验`)—— urllib 不会替你编码,
    # 它会在底层用 ascii 编码请求行然后炸,而报出来的错长得像「连不上服务」。
    路 = urllib.parse.quote(路, safe="/?&=:%")
    req = urllib.request.Request(基址 + 路, method=方法, data=数据)
    req.add_header("X-Dev-User", 谁)
    if 原始 is not None:
        req.add_header("content-type", "application/octet-stream")
    elif 体 is not None:
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


好文 = ("# 签收后请顾客评价\n\n"
      "签收当场就请,三星及以下算差评并自动进待处理清单。\n\n"
      "代价:门店会觉得被考核,所以这条数据不进考核,只给店长看。\n")
好字节 = 好文.encode("utf-8")


print("▸ ① 要地址那一步就拒:后缀 / 大小 / 没声明字节数")
码, r = 打("POST", P + "/uploads", 体={"file_name": "合同.pdf", "byte_count": 100})
ck("PDF → 422(不让他先传完再说不支持)", 码 == 422, 码)
ck("错误里点名 file_name", "file_name" in ((r or {}).get("field_errors") or {}),
   (r or {}).get("field_errors"))
码, r = 打("POST", P + "/uploads", 体={"file_name": "a.md"})
ck("不声明 byte_count → 422(不声明就检不出截断)", 码 == 422, 码)
码, r = 打("POST", P + "/uploads",
         体={"file_name": "a.md", "byte_count": 50 * 1024 * 1024})
ck("超上限 → 422(在要地址时就拦,不等他传完 50MB)", 码 == 422, 码)

print("▸ ② 正常拿地址 → 待上传")
码, 好 = 打("POST", P + "/uploads",
          体={"file_name": "拍板-评价.md", "byte_count": len(好字节),
             "content_type": "text/markdown"})
ck("201", 码 == 201, 码)
ck("状态是待上传", (好 or {}).get("状态") == "待上传", (好 or {}).get("状态"))
ck("给了上传地址", bool((好 or {}).get("上传地址")), (好 or {}).get("上传地址"))
ck("给了完成地址(**传完还要调一次**,不是传完就算)",
   bool((好 or {}).get("完成地址")))
ck("说清了这是偏离(首版没有对象存储,地址不是预签名 URL)",
   "对象存储" in ((好 or {}).get("偏离") or ""), (好 or {}).get("偏离"))
好id = (好 or {}).get("id")

print("▸ ③ 字节还没到就调完成 → 409,**不是「校验失败」**")
码, r = 打("POST", f"{P}/uploads/{好id}/complete")
ck("409 NO_BYTES_YET", 码 == 409 and (r or {}).get("code") == "NO_BYTES_YET",
   f"{码} {(r or {}).get('code')}")
ck("建议里告诉他 PUT 去哪", "bytes" in ((r or {}).get("advice") or ""),
   (r or {}).get("advice"))

print("▸ ④ 传字节 → 已上传,而 **能引用吗 = false**")
码, r = 打("PUT", 好["上传地址"], 原始=好字节)
ck("200", 码 == 200, 码)
ck("状态是已上传", (r or {}).get("状态") == "已上传", (r or {}).get("状态"))
ck("收到的字节数对得上", (r or {}).get("收到字节数") == len(好字节))
ck("note 里明说「字节到了但还不能引用」(§17.1)",
   "不能引用" in ((r or {}).get("note") or ""), (r or {}).get("note"))
码, r = 打("GET", f"{P}/uploads?status=已上传")
这条 = [x for x in (r or {}).get("items", []) if x["id"] == 好id]
ck("列表里这条的 **能引用吗 = false**",
   bool(这条) and 这条[0]["能引用吗"] is False, 这条[:1])
ck("而且它**不是终态** —— 还要走校验", bool(这条) and 这条[0]["是终态吗"] is False)

print("▸ ⑤ 已经传过的不许覆盖")
码, r = 打("PUT", 好["上传地址"], 原始=b"# overwrite\n\nnope\n")
ck("再 PUT 一次 → 409", 码 == 409 and (r or {}).get("code") == "UPLOAD_NOT_PENDING",
   f"{码} {(r or {}).get('code')}")

print("▸ ⑥ 完成 → 已校验,现在才算文件引用")
码, r = 打("POST", f"{P}/uploads/{好id}/complete")
ck("200", 码 == 200, 码)
ck("通过 = true", (r or {}).get("通过") is True, r)
ck("状态是已校验", (r or {}).get("状态") == "已校验")
ck("**能引用吗 = true**", (r or {}).get("能引用吗") is True)
import hashlib
真哈希 = "sha256:" + hashlib.sha256(好字节).hexdigest()
ck("content_hash 是**服务端按真字节算的**", (r or {}).get("content_hash") == 真哈希,
   (r or {}).get("content_hash"))
详 = (r or {}).get("校验详情") or {}
ck("校验详情里报了**查了哪些规则**(报「没过什么」时同时报「查了什么」)",
   len(详.get("规则全集") or []) >= 7, len(详.get("规则全集") or []))
ck("详情里记了解析器版本(同一份文件的结论会随解析器变)",
   bool((详.get("细节") or {}).get("解析器版本")), (详.get("细节") or {}).get("解析器版本"))
ck("详情里记了切出几块(**没报错不等于有内容**)",
   ((详.get("细节") or {}).get("块数") or 0) > 0, (详.get("细节") or {}).get("块数"))

print("▸ ⑦ 幂等靠状态:再调一次返回同一个结论")
码, r2 = 打("POST", f"{P}/uploads/{好id}/complete")
ck("200 且通过还是 true", 码 == 200 and r2.get("通过") is True, 码)
ck("哈希没变", r2.get("content_hash") == 真哈希)
ck("note 说清「返回上一次的结论」(不重新校验 —— 重新校验会在解析器升级后翻案)",
   "上一次" in (r2.get("note") or ""), r2.get("note"))

print("▸ ⑧ 坏文件:GBK 编码 → **200 + 通过=false**,不是 4xx")
坏字节 = "门店评价资料内容".encode("gbk")
码, 坏 = 打("POST", P + "/uploads",
          体={"file_name": "乱码.txt", "byte_count": len(坏字节)})
坏id = 坏["id"]
打("PUT", 坏["上传地址"], 原始=坏字节)
码, r = 打("POST", f"{P}/uploads/{坏id}/complete")
ck("**200**(请求本身成功了 —— 我们确实校验了并存下了结论)", 码 == 200, 码)
ck("通过 = false", (r or {}).get("通过") is False, (r or {}).get("通过"))
ck("状态是校验失败", (r or {}).get("状态") == "校验失败")
ck("能引用吗 = false", (r or {}).get("能引用吗") is False)
没过 = ((r or {}).get("校验详情") or {}).get("没过的规则") or []
ck("点名「能按 UTF-8 严格解码」(而不是笼统的「格式错误」)",
   "能按 UTF-8 严格解码" in 没过, 没过)
ck("**是终态** —— 同一个坏文件重传还是坏的", (r or {}).get("是终态吗") is True)
ck("note 里告诉他「重新要一个上传地址」而不是「重试」",
   "重新要一个" in ((r or {}).get("note") or ""), (r or {}).get("note"))

print("▸ ⑨ 校验失败之后:不许再传字节,complete 返回同一个结论")
码, r = 打("PUT", 坏["上传地址"], 原始=好字节)
ck("往失败的那条再 PUT → 409(**不回「待上传」**)", 码 == 409, 码)
码, r = 打("POST", f"{P}/uploads/{坏id}/complete")
ck("再 complete → 200 且还是 false(不重新校验,不翻案)",
   码 == 200 and r.get("通过") is False, f"{码} {r.get('通过')}")

print("▸ ⑩ 截断:声明 N 实际 N/2")
码, 断 = 打("POST", P + "/uploads",
          体={"file_name": "断了.md", "byte_count": len(好字节)})
打("PUT", 断["上传地址"], 原始=好字节[: len(好字节) // 2])
码, r = 打("POST", f"{P}/uploads/{断['id']}/complete")
没过 = ((r or {}).get("校验详情") or {}).get("没过的规则") or []
ck("校验失败,并点名「实际字节数和声明一致」",
   (r or {}).get("通过") is False and "实际字节数和声明一致" in 没过, 没过)
理由 = [x["为什么"] for x in
      (((r or {}).get("校验详情") or {}).get("理由们") or [])
      if x["规则"] == "实际字节数和声明一致"]
ck("理由说了「传到一半断了」而不只是两个数不等", 理由 and "断" in 理由[0],
   (理由 or [""])[0][:80])
ck("库里的 byte_count 改成了**实际收到的**(配额要算真实占用)",
   (r or {}).get("byte_count") == len(好字节) // 2, (r or {}).get("byte_count"))

print("▸ ⑪ 列表:失败的也列出来,`能引用的 < total`")
码, r = 打("GET", P + "/uploads?limit=100")
总 = (r or {}).get("total") or 0
能 = (r or {}).get("能引用的") or 0
ck("列表里有刚才那三条", 总 >= 3, 总)
ck("**能引用的 < total** —— 只列成功项会让人再传一次同一个坏文件", 能 < 总,
   f"能引用 {能} / 共 {总}")
有失败 = any(x["状态"] == "校验失败" for x in (r or {}).get("items", []))
ck("失败的那条在列表里(**它是证据**)", 有失败)
ck("列表信封字段齐(items/next_cursor/total)",
   all(k in (r or {}) for k in ("items", "next_cursor", "total")))
码, r = 打("GET", P + "/uploads?status=没这个状态")
ck("按一个不存在的状态筛 → 422 并列出有哪些(拼错不等于「没有」)",
   码 == 422 and "已校验" in ((r or {}).get("advice") or ""), 码)

print("▸ ⑫ 项目隔离 + 权限")
码, r = 打("POST", f"/api/v1/projects/{别的项目}/uploads/{好id}/complete", 谁="U005")
ck("换个项目拿同一个上传 id → 404(**不确认「它在别的项目里存在」**)",
   码 == 404, f"{码} {(r or {}).get('code')}")
码, r = 打("POST", P + "/uploads", 谁="U003",
         体={"file_name": "a.md", "byte_count": 10})
ck("viewer 要上传地址 → 403", 码 == 403, 码)
码, r = 打("GET", P + "/uploads", 谁="U003")
ck("viewer 看列表 → 200(读是给他的)", 码 == 200, 码)
码, r = 打("PUT", f"{P}/uploads/{好id}/bytes", 谁="U003", 原始=b"x")
ck("viewer 传字节 → 403(**写的门槛在每条写接口上,不只在第一条**)", 码 == 403, 码)

print("▸ ⑬ 空 body:不落存储也不推状态,留在待上传让他重传")
码, 空 = 打("POST", P + "/uploads", 体={"file_name": "空.md", "byte_count": 10})
码, r = 打("PUT", 空["上传地址"], 原始=b"")
ck("空 body → 422 EMPTY_BODY", 码 == 422 and (r or {}).get("code") == "EMPTY_BODY",
   f"{码} {(r or {}).get('code')}")
码, r = 打("GET", f"{P}/uploads?limit=100")
这条 = [x for x in (r or {}).get("items", []) if x["id"] == 空["id"]]
ck("它还是「待上传」(没产生一条「已上传的空文件」)",
   bool(这条) and 这条[0]["状态"] == "待上传", 这条[:1])

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
