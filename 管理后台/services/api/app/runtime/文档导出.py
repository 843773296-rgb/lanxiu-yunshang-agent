# -*- coding: utf-8 -*-
"""「Markdown 导出」节点的纯函数部分(11-21,用户拍:第一个业务定时任务 = 经营日报草稿 + Markdown 导出;复审 P1-06「Markdown 文本与可下载文件之间缺少交付契约」)。

worker 的适配器拿这里算好的文件名 / 字节 / 哈希去写对象存储、记 workflow_documents 表;这里**不碰库、不碰文件**,好在进程内咬。

规矩(照辅助目录那份方案的 MD-02):
· 文件名由服务端生成:`业务名_门店编码_统计日期_运行短号.md`,段里的路径分隔符、控制字符一律换掉;不接受调用方给路径
· 媒体类型固定 text/markdown; charset=utf-8;字节 = 正文 UTF-8 编码(统一 \\n 换行,末尾补一个换行)
· 哈希 sha256 在**写之前**算、写完回读再算一次,两次要一样 —— 「保存成功」是回读说的,不是模型说的
· 正文不是字串时(模型给了结构)按 JSON 排版成文本,不编一段说明冒充正文
"""
import hashlib
import json
import re
import unicodedata

媒体类型 = "text/markdown; charset=utf-8"
_坏字 = re.compile(r"[\\/\x00-\x1f\x7f:*?\"<>|]+")


def 安全段(文, 兜底="x", 长=60):
    """文件名的一段:去路径分隔符 / 控制字符 / 空白压成下划线;空了用兜底。"""
    s = unicodedata.normalize("NFC", str(文 if 文 is not None else "")).strip()
    s = _坏字.sub("_", s)
    s = re.sub(r"\s+", "_", s).strip("._")
    return (s or 兜底)[:长]


def 文件名(业务名, 门店=None, 统计日期=None, 运行短号=None):
    """`业务名_门店编码_统计日期_运行短号.md`;没有的段跳过(不留空段)。"""
    段 = [安全段(业务名, "文档")]
    if 门店:
        段.append(安全段(门店, "", 32))
    if 统计日期:
        段.append(安全段(统计日期, "", 32))
    if 运行短号:
        段.append(安全段(运行短号, "", 16))
    return "_".join(x for x in 段 if x) + ".md"


def 正文转文本(正文):
    """正文是字串就原样;是结构就按 JSON 排版(缩进 2,中文不转义);None → 空串。统一换行、末尾一个换行。"""
    if 正文 is None:
        s = ""
    elif isinstance(正文, str):
        s = 正文
    else:
        s = json.dumps(正文, ensure_ascii=False, indent=2, default=str)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s if s.endswith("\n") else s + "\n"


def 字节与哈希(文本):
    b = 文本.encode("utf-8")
    return b, hashlib.sha256(b).hexdigest(), len(b)


def 统计期(实参):
    """从绑定来的值里取统计起 / 止(定时开头的流程由系统填),缺就空。"""
    起, 止 = 实参.get("统计起"), 实参.get("统计止")
    return {"起": (str(起)[:32] if 起 else None), "止": (str(止)[:32] if 止 else None)}


def 运行短号(run_id):
    return str(run_id or "")[-8:] or "run"
