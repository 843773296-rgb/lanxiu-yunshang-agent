#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流「文档提取器」节点的规则 —— **校验器和执行器都调这一处**(照 Dify「文档提取器」;用户 10-26 拍「workflow 直接复刻 dify」)。

## 文件从哪来、能取什么(11-12 查清的现状)

项目里的文件只有一条路进来:**管理后台的上传**(`uploads_api.py`:要地址 → 传字节 → 完成时服务端校验)。
字节在对象存储里(首版是文件系统适配器 `storage.py`),库里 `uploads` 表记文件名、状态、对象键。
上传那一关只收 Markdown / 纯文本(`knowledge/upload_rules.py` 问 `knowledge/parser.py`),UTF-8 严格解码,≤ 5 MB。
**PDF / Word / 图片现在根本传不进来** —— 所以这一步能取的格式就是这三种后缀,原样按 UTF-8 读出文字。

## 文件引用长什么样

上游给的值是**上传记录的编号**(`up_` 开头那串),一个或一组;也认上传接口返回的那种对象(带 `id`)。
一个 → 结果「文本」是一段文字、「文件名」是一个名字;一组 → 两个都是列表,顺序和给进来的一致(照 Dify)。

## 为什么取不了就失败,不给空串

格式不认得、文件没校验过、文件读出来是空的 —— 任何一种都**这一步失败**(可从「失败」出口接人工)。
给一个空字符串往下走,后面的模型会认真地总结一份什么都没有的文件,而运行记录里那一步是绿的。

## 执行器不碰库

真去库里查、去存储里读字节的,是 Worker 给的 `document` 适配器(`workers/worker.py`);
它**只查这次运行所在项目的上传**,别的项目的编号当找不到(不说「它在别处存在」)。
这里只管:引用认不认得、状态对不对、格式能不能取、解不解得开、是不是空的。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract"))
import states as ST  # noqa: E402


class 做不了(Exception):
    def __init__(self, code, 消息, 建议):
        self.code, self.消息, self.建议 = code, 消息, 建议
        super().__init__(f"{code}: {消息}")


# 能取文字的后缀。⚠️ 这是**这一步自己会读的**,不是上传那一关收的 —— 两边今天一样(test_doc_extractor_node 钉着
# 「上传收的每一种这里都能取」);哪天上传开始收 PDF 而这里没跟上,运行时照样是明确失败,不是给空串
能提取的后缀 = (".md", ".markdown", ".txt")
已校验 = "已校验"
assert 已校验 in ST.找("upload")["状态"], "「已校验」不在上传状态机里 —— 契约和这里分叉了"

# 一步最多读几份文件。⚠️ 这是自己定的技术上限(11-12),不是业务门槛:每份 ≤ 5 MB,
# 十份读进来的文字整段进运行记录;要更多就拆成列表迭代(那一期)或者几步
最多几份 = 10


def 引用们(v):
    """上游给的值 → (编号列表, 是不是一组)。认不得抛 `做不了`。"""
    def 一个(x, 第几=None):
        if isinstance(x, dict):
            x = x.get("id") if "id" in x else x.get("upload_id")
        if not isinstance(x, str) or not x.strip():
            哪 = f"第 {第几} 个" if 第几 else "给进来的"
            raise 做不了("DOC_BAD_REF", f"{哪}不是文件引用(要的是上传记录的编号),拿到的是「{str(x)[:40]}」",
                       "在右侧「用到的数据」里给「文件」选上传文件的那一项(开始节点里让使用者给的文件编号)")
        return x.strip()
    if isinstance(v, list):
        if not v:
            raise 做不了("DOC_NO_FILE", "给进来的文件列表是空的,没有可以取文字的文件",
                       "确认前面那一步真的给了文件;允许没有文件的话,在这一步前面用条件分支判「长度等于 0」绕开")
        if len(v) > 最多几份:
            raise 做不了("DOC_TOO_MANY", f"一次给了 {len(v)} 份文件,这一步最多读 {最多几份} 份",
                       "分成几步读,或者先用「列表操作」只取前几份")
        return [一个(x, i) for i, x in enumerate(v, 1)], True
    return [一个(v)], False


def 提取(记录):
    """一条上传记录(适配器给的:file_name / status / 字节)→ 文字。取不了抛 `做不了`。"""
    名 = 记录.get("file_name") or ""
    if 记录.get("status") != 已校验:
        raise 做不了("DOC_NOT_VERIFIED", f"文件「{名}」还没通过上传校验(现在是「{记录.get('status')}」),不能当文件用",
                   "回上传那里看它为什么没过;传完要点「完成」做校验,校验通过的才能用")
    if not 名.lower().endswith(能提取的后缀):
        后 = os.path.splitext(名)[1] or "(没有后缀)"
        raise 做不了("DOC_FORMAT_UNSUPPORTED", f"文件「{名}」是 {后} 格式,这一步取不了它的文字",
                   f"现在能取的是 {'、'.join(能提取的后缀)};PDF、Word、图片要先转成纯文本再上传")
    字节 = 记录.get("字节")
    if not isinstance(字节, (bytes, bytearray)):
        raise 做不了("DOC_READ_FAILED", f"文件「{名}」的内容没读到", "这是存储那边的问题,不是文件的问题 —— 请报给技术管理员")
    try:
        文 = bytes(字节).decode("utf-8")
    except UnicodeDecodeError as e:
        raise 做不了("DOC_DECODE_FAILED", f"文件「{名}」第 {e.start} 字节起按 UTF-8 解不开",
                   "把文件另存成 UTF-8 编码的纯文本再上传;不会退回别的编码去猜(猜错就是一份乱码)")
    if not 文.strip():
        raise 做不了("DOC_EMPTY", f"文件「{名}」里没有文字",
                   "换一份有内容的文件;不会把空文件当成一段空文字交给后面")
    return 文
