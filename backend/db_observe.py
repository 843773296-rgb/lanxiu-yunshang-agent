# -*- coding: utf-8 -*-
"""这一次工具调用**实际读了哪些库表**(证据中心第五个工作包,用户 10-25 拍「实际记录每次查询」)。

工具的说明里写着它「会查哪些表」,那是**声明**,证明不了某一次真查了什么 —— 有条件分支的工具会列出没碰过的表
(需求文档附录 B-2:「来源声明能解释可能性,运行回执才能证明发生过什么」)。所以在库这一层观测:

  · 工具服务进程启动时 `装上()`:把这个进程里的 sqlite3.connect 换成「连上之后挂一个授权回调」的版本。
    SQLite 每准备一条语句,都会为它要读的**每一张表的每一列**回调一次(SQLITE_READ)—— 联表、视图、子查询都在里面,
    比从 SQL 文本里猜表名可靠。这个进程里约 210 处取数(api.py 的 _c / _rows / _rows2 和各模块自己开的连接)不用逐个改。
  · 每次工具调用包在 `with 一次调用(工具, 参数):` 里,出来时把这一次读到的写一行到 .feynman/db-access.jsonl
    (trace、工具、参数指纹、读了哪个库的哪些表哪些列、准备了几条语句)。**不记 SQL 参数值** —— 那里面是客户资料。
  · 聊天站那边用**同一个** `参数指纹` 给工具调用打上记号,证据面板按「trace + 工具 + 参数指纹」对上,不按先后猜。

**看不到的照实说**:别的进程里的读(比如业务后台页面、写口走的 HTTP)不在这个进程里,观测不到。
授权回调只返回「放行」,不改任何查询的结果;回调自己出错也放行(观测坏了不能把业务查询拦掉)。
"""
import contextvars
import hashlib
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "..", ".feynman", "db-access.jsonl")
_当前 = contextvars.ContextVar("db_observe_当前", default=None)
_原connect = sqlite3.connect
_装了 = [False]


def 参数指纹(工具, 参数):
    """工具短名 + 参数的规范 JSON(键排序)的 sha256 前 16 位。聊天站和工具服务**调同一个函数**,两边才对得上。"""
    短 = str(工具 or "").rsplit("__", 1)[-1]
    s = json.dumps(参数 or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(f"{短}\n{s}".encode("utf-8")).hexdigest()[:16]


def _回调(库名):
    def 回调(动作, a1, a2, 库, 触发):
        try:
            记 = _当前.get()
            if 记 is not None:
                if 动作 == sqlite3.SQLITE_READ and a1:
                    记["表"].setdefault(库名, {}).setdefault(a1, set()).add(a2 or "")
                elif 动作 == sqlite3.SQLITE_SELECT:
                    记["语句数"] += 1
        except Exception:
            pass
        return sqlite3.SQLITE_OK
    return 回调


def _连(database, *a, **k):
    # **关掉语句缓存**:SQLite 只在「准备」一条语句时调授权回调,而 Python 按连接缓存准备好的语句 ——
    # 复用的连接(促活模块那个)第二次跑同一条 SQL 不再回调,第二次工具调用就记成「只读了 customer」(实测 6 张表 → 1 张)。
    # 代价量过:促活整店名单 1.91 → 2.01 秒
    k.setdefault("cached_statements", 0)
    c = _原connect(database, *a, **k)
    try:
        库名 = os.path.basename(str(database).split("?")[0].replace("file:", "")) or str(database)
        c.set_authorizer(_回调(库名))
    except Exception:
        pass
    return c


def 装上():
    """在工具服务进程启动时调一次。之后这个进程里新开的每个 sqlite 连接都带观测。"""
    if not _装了[0]:
        sqlite3.connect = _连
        _装了[0] = True


class 一次调用:
    def __init__(self, 工具, 参数, trace=None, 路径=None):
        self.工具, self.参数 = 工具, 参数
        self.trace = trace if trace is not None else os.environ.get("LANXIU_TRACE")
        self.路径 = 路径 or LOG
        self.记 = {"表": {}, "语句数": 0}

    def __enter__(self):
        self.令牌 = _当前.set(self.记)
        self.起 = time.time()
        return self.记

    def __exit__(self, *exc):
        _当前.reset(self.令牌)
        try:
            os.makedirs(os.path.dirname(self.路径), exist_ok=True)
            with open(self.路径, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "trace": self.trace, "工具": self.工具, "参数指纹": 参数指纹(self.工具, self.参数),
                    "时间": self.起, "语句数": self.记["语句数"],
                    "读了": {库: {表: sorted(列 - {""}) for 表, 列 in 表们.items()} for 库, 表们 in self.记["表"].items()},
                    "出错": bool(exc and exc[0]),
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return False


def 读(trace, 路径=None):
    """→ [{工具, 参数指纹, 读了, 语句数, ...}],这一轮的,按时间排。"""
    p = 路径 or LOG
    if not (trace and os.path.exists(p)):
        return []
    出 = []
    for line in open(p, encoding="utf-8"):
        if f'"{trace}"' not in line:
            continue
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if x.get("trace") == trace:
            出.append(x)
    return sorted(出, key=lambda x: x.get("时间") or 0)
