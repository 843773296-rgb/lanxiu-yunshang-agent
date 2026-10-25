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
    # 外部审阅 10-03 §4.2:**权限变了就中止旧历史续聊** —— 只限制新的工具调用不够,
    # 旧历史里已经有按旧权限取到的数据(店长调去当顾问,接着说就还看得见全店的)
    if (rec.get("role") or "") != (me.get("role") or "") or (rec.get("shop") or "") != (me.get("shop") or ""):
        return False, (f"你的角色 / 门店变了(这条会话开的时候是 {rec.get('role')}·{rec.get('shop') or '—'}),"
                       f"里面有按原来权限取到的数据 —— **开一条新的**")
    return True, ""


def owner(session_id):
    return _load().get(str(session_id))


def 能看执行记录吗(me, 会话号=None, 列全部=False):
    """聊天站 `/spans`(执行记录:用户原话、工具参数和返回)谁能看。→ (行不行, HTTP 码, 为什么)。

    2026-10-24 实测(证据中心 PRD 1.2 点名、当时没实测):这个口**不登录就给 200**,
    列表给全部对话、单条带原话和工具返回(样本里带客户号)。端口只绑 127.0.0.1,所以范围是本机 ——
    但登录之后照样**谁都能看全公司的**,顾问看得到别的门店的客户。
      · 没登录 → 401
      · 列全部 → 只给总部运营(没有页面在用;调试才用)
      · 单条 → 这条记录所属的会话必须是你的,而且你的角色 / 门店没变过(和续聊同一个判定 `check`);
        **查不到归属就拒,不猜**(评测、试跑这类不经聊天页的运行没有会话归属,只有总部运营看得到)
    """
    if not (me or {}).get("no"):
        return False, 401, "没登录 —— 执行记录里有对话原文和查回来的业务数据"
    if 列全部:
        if me.get("role") == "总部运营":
            return True, 200, ""
        return False, 403, "列全部对话的执行记录只给总部运营 —— 你只能从自己的对话里点开那一条"
    if not 会话号:
        if me.get("role") == "总部运营":
            return True, 200, ""
        return False, 404, "这条记录不属于任何聊天会话(评测 / 试跑之类),只有总部运营能看"
    行, 为什么 = check(会话号, me)
    if 行:
        return True, 200, ""
    if me.get("role") == "总部运营" and owner(会话号):
        return True, 200, ""
    return False, 404, 为什么          # 404 不说「有这条但你没权限」—— 那句话本身就是信息


def 能看原文吗(me, 会话号=None):
    """执行记录的**原文**(没截断、没打码的工具参数和返回)谁能看(证据中心 10-25,用户拍「1+2 都要」)。
    → (行不行, HTTP 码, 为什么)。顾问看展示副本(/spans,打了码),原文只给:
      · 总部运营
      · 这轮会话所属门店的**店长**(会话主人的门店 = 店长的门店)
    平台管理员在管理后台那边看(那边有自己的角色),不走这个口。查不到会话归属 → 只有总部运营能看,不猜。"""
    if not (me or {}).get("no"):
        return False, 401, "没登录 —— 原文里有客户的完整手机号和查回来的原始业务数据"
    if me.get("role") == "总部运营":
        return True, 200, ""
    if me.get("role") != "店长":
        return False, 403, f"原文只给总部运营和本店店长,你是「{me.get('role')}」—— 打了码的那份在执行记录里能看"
    主 = owner(会话号) if 会话号 else None
    if not 主:
        return False, 404, "查不到这一轮属于哪个会话 —— 只有总部运营能看"
    if not me.get("shop") or 主.get("shop") != me.get("shop"):
        return False, 404, "这一轮不是你门店的会话"
    return True, 200, ""

