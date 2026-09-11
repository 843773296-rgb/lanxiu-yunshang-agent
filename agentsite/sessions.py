# -*- coding: utf-8 -*-
"""**会话归属** —— 一条对话是谁的,只认这一份。

## 为什么需要它

多轮对话不是把历史拼进 prompt,是给 CLI 一个 `session_id` 让它接着往下走
(见 `sdk.run` 的 docstring)。而这个 id **是前端送上来的**。

于是有一个洞:身份判定做得再对也没用 —— `_who()` 老老实实从后台 cookie 换出
「你是顾问林岚」,工具层老老实实只给她自己的任务,**然后她送上一个店长的
session_id,CLI 就把店长那条对话接着往下讲**。店长那条里已经有全店的数据了。

**隔离是按「这轮取什么数」做的,而历史是上一轮就已经取好的。**
每一轮都判身份,挡不住「换一条别人已经判过的历史接着说」。

## 归属只在这一处判

写任务的逻辑抽成 `oplog.log_op` 是同一个理由:两个入口各判一次,
总有一次会判松,而判松的那次**看起来完全正常**。

## 服务重启会怎样

归属表落在文件里,重启还在。文件丢了的话,**所有续聊一律拒**(按「不知道是谁的」
处理,不是按「那就放行」)—— 兜底方向是拒,不是猜。
"""
import json, os, threading

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, ".sessions.json")
_LOCK = threading.Lock()


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def own(session_id, me):
    """记下这条会话是谁的。**只在真的拿到 session_id 和身份时记。**"""
    if not session_id or not (me or {}).get("no"):
        return
    with _LOCK:
        d = _load()
        d[str(session_id)] = {"no": str(me["no"]), "name": me.get("name"),
                              "role": me.get("role"), "shop": me.get("shop")}
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, PATH)     # 半截文件比没有文件更难查


def check(session_id, me):
    """能不能接着这条会话往下说。返回 (行不行, 为什么)。

    三种拒法,**理由要分得开** —— 「没登录」「不知道这条是谁的」「这条是别人的」
    在排查时是三件不同的事,合成一句「不允许」就没法查了。
    """
    if not session_id:
        return True, ""                      # 新会话,没有归属可言
    if not (me or {}).get("no"):
        return False, "没登录 —— 续聊要先知道你是谁"
    rec = _load().get(str(session_id))
    if not rec:
        return False, ("这条会话查不到归属(服务重启过,或者它不是本机开的)——"
                       "**开一条新的**。查不到就拒,不猜")
    if str(rec.get("no")) != str(me["no"]):
        return False, (f"这条会话是**别人的**({rec.get('name') or rec.get('no')}),"
                       f"不能接着往下说 —— 里面有你看不到的数据")
    return True, ""


def owner(session_id):
    return _load().get(str(session_id))
