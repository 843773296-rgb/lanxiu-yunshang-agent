# -*- coding: utf-8 -*-
"""聊天站问管理后台:**这件事现在归不归工作流管**(用户 2026-10-24 拍「默认关;打开时聊天站改走工作流」)。

两个用处,同一份清单:
  · `guards.pre_tool_verdict` 的 Skill 分支 —— 被接管的技能**结构上**调不动(钩子拦),不是只在提示词里劝
  · `api.start_workflow` —— 发起那条工作流,回运行号和核对入口

## 拉不到清单的时候怎么办

用**最后一次拉成功的**(落盘);**从没拉成功过就当全关**。
  · 当全关 = 照现在用技能做。全开着拦的话,管理后台一停,聊天站所有自有技能都被拦 —— 而默认本来就一条都没接管
  · 用上一次的,而不是一失败就当全关:接管开着时管理后台短暂抖一下,聊天站不会悄悄换回技能那条路,
    「同一件事任何时刻只有一种做法」不被抖动打破
  · 清单旧了也不会发出一条没接管的运行:开没开**由管理后台在发起那一刻再判一次**(409 TAKEOVER_OFF)

配置走环境变量,**没配就是没配,不给默认地址**(和 usage_report.配置 同一个理由:发了没人收和压根没发长得一样):
  LANXIU_USAGE_URL(管理后台地址)· LANXIU_BRIDGE_PROJECT(澜绣正式项目)· LANXIU_USAGE_USER(服务账号)
"""
import json
import os
import subprocess
import time

_缓存秒 = 30
_落盘 = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".takeover_last.json")
_内存 = {"at": 0.0, "items": None}

# ── 兜底(用户 2026-11-12 拍「技能兜底 + 把工作流配好」)──────────────────────
#
# 11-12 查实:call-notes 被接管 → 模型按 TL76 转 start_workflow → 「录音跟进」工作流没发布 →
# 这里回「工作流没发起,**也别改用技能自己做**;请稍后再试」。模型每一步都照规矩办了,
# 而顾问从 11-04 起问「整理一下 TS-002」拿到的就是「稍后再试」—— 商机评测连三夜 0/24,生产同状态。
# 原来的设计是 fail-closed(「同一件事任何时刻只有一种做法」),用户拍了改成:
# **接管开着但工作流发不起(没发布 / 连不上 / 任何非 202)→ 这一轮技能照常做,回复里注明是技能直接做的。**
# 11-14 用户收窄:**403 没权限不兜**(明确拒绝照旧拦),只兜「没配好」那几种。
#
# ⚠️ 兜底不能只改这里的返回值。拦技能的钩子(`guards.pre_tool_verdict` 的 Skill 分支)在**聊天站进程**,
#    `发起()` 跑在**工具服务进程**,两边的 `_内存` 不是同一个 —— 只回「交还」的话,模型重调技能
#    会被钩子**再拦一次**(清单还说接管着),然后再转工作流、再失败……死循环。
#    所以兜底要**落盘**(两个进程共用这个文件),`接管中()` 读它:窗口内这个技能当没接管。
# ⚠️ 窗口 15 分钟:够一轮对话用完,又不会让「工作流修好了」之后还在绕着它走太久。
#    TAKEOVER_OFF 那条不走兜底 —— 它本来就是「交还」,清单重拉即可。
_兜底文件 = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".takeover_fallback.json")
兜底窗口秒 = 15 * 60


def _读兜底():
    try:
        with open(_兜底文件, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def 记兜底(技能, 现在=None):
    """这个技能这一轮改由技能自己做(工作流发不起)。写盘,给另一个进程里的钩子看。"""
    d = _读兜底()
    d[(技能 or "").strip().lstrip("/")] = float(现在 if 现在 is not None else time.time())
    try:
        with open(_兜底文件, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError:
        pass            # 写不进盘:钩子那边看不到兜底,会再拦一次 —— 比悄悄放行所有技能安全


def 在兜底中(技能, 现在=None):
    t = _读兜底().get((技能 or "").strip().lstrip("/"))
    return bool(t) and (float(现在 if 现在 is not None else time.time()) - float(t)) < 兜底窗口秒


def 配置():
    c = dict(地址=os.environ.get("LANXIU_USAGE_URL") or None,
             项目=os.environ.get("LANXIU_BRIDGE_PROJECT") or None,
             工号=os.environ.get("LANXIU_USAGE_USER") or None)
    return c if all(c.values()) else None


def _curl(方法, 路径, cfg, 体=None, 幂等键=None):
    """走 curl 不走 urllib:这台机器 Python 的证书校验会失败(本地 http 也统一走一处)。"""
    url = f"{cfg['地址'].rstrip('/')}/api/v1/projects/{cfg['项目']}{路径}"
    # ⚠️ 11-03 真跑撞到:取回复的查询参数名是「澜绣工号」,原样带着中文字节发出去,
    # 管理后台(uvicorn)直接回 400「Invalid HTTP request」—— 聊天里追问「工作流怎么样了」从来没成功过,
    # 而单测把 _curl 整个换成假的,于是一直绿。**在这一处统一转码**,不靠每个调用方记得 quote
    # (supervise_sync 那处是手写了 %E7…,下一个调用方未必记得)。已经转过码的 %XX 原样保留。
    from urllib.parse import quote as _q
    url = _q(url, safe=":/?&=%#+,;@!$'()*[]~")
    cmd = ["curl", "-sS", "-m", "8", "-X", 方法, url, "-H", "Content-Type: application/json",
           "-H", f"X-Dev-User: {cfg['工号']}", "-w", "\n%{http_code}"]
    if 幂等键:
        cmd += ["-H", f"Idempotency-Key: {幂等键}"]
    if 体 is not None:
        cmd += ["--data-binary", "@-"]
    try:
        r = subprocess.run(cmd, input=json.dumps(体, ensure_ascii=False) if 体 is not None else None,
                           capture_output=True, text=True, timeout=12)
    except Exception as e:
        return None, f"curl 起不来:{type(e).__name__}"
    if r.returncode != 0:
        return None, f"连不上管理后台(curl 退 {r.returncode})"
    正文, _, 码 = r.stdout.rpartition("\n")
    try:
        return 码.strip(), json.loads(正文 or "null")
    except ValueError:
        return 码.strip(), 正文[:200]


def 清单(强制=False):
    """{技能: {workflow_id, 名称, 版本}};拉不到用最后一次成功的,从没成功过 → {}。"""
    if not 强制 and _内存["items"] is not None and time.time() - _内存["at"] < _缓存秒:
        return _内存["items"]
    cfg = 配置()
    items = None
    if cfg:
        码, 体 = _curl("GET", "/chat-takeovers", cfg)
        if 码 == "200" and isinstance(体, dict):
            items = {x["技能"]: {"workflow_id": x["workflow_id"], "名称": x.get("名称"), "版本": x.get("版本")}
                     for x in 体.get("items") or [] if x.get("技能")}
            try:
                with open(_落盘, "w", encoding="utf-8") as f:
                    json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "items": items}, f, ensure_ascii=False)
            except OSError:
                pass
    if items is None:
        try:
            with open(_落盘, encoding="utf-8") as f:
                items = json.load(f).get("items") or {}
        except (OSError, ValueError):
            items = {}
    _内存.update(at=time.time(), items=items)
    return items


def 接管中(技能):
    """这个技能现在被哪条工作流接管;没被接管 → None(交给 harness)。
    **兜底窗口内也返回 None**(工作流刚发不起,这一轮技能自己做 —— 见 `记兜底`)。"""
    if 在兜底中(技能):
        return None
    return 清单().get((技能 or "").strip().lstrip("/"))


def 幂等键(澜绣工号, 技能, workflow_id, 输入, 现在):
    """同一个人、同一条工作流、同样的输入、**同一分钟**里 → 同一个键(模型重发不排出第二条)。

    ⚠️ 2026-10-24 真跑踩过:原来按「工号 + 技能 + 输入 + 10 分钟」算 —— 没带工作流、窗口又宽,
    第二次试跑在新建的工作流上发起,拿回的是**上一次那条已经取消的运行**,模型照样对用户说「已发起」。
    这把钥匙只为挡**同一轮里的重发**(同一轮同参数重试另有 guards 的写闸拦着),一分钟够了;
    换了工作流必须是另一把钥匙。"""
    import hashlib, uuid
    指纹 = json.dumps([澜绣工号, 技能, workflow_id, 输入 or {}, int(现在 // 60)], ensure_ascii=False, sort_keys=True)
    return str(uuid.UUID(hashlib.sha256(指纹.encode()).hexdigest()[:32]))


def 发起(技能, 澜绣工号, 输入, 幂等键):
    """返回 (成没成, 回给模型的 dict)。开没开、绑没绑都由管理后台判,这里只转述。"""
    cfg = 配置()
    if not cfg:
        return False, dict(error="聊天站没配管理后台地址,发起不了工作流 —— 请管理员检查聊天站的常驻配置")
    码, 体 = _curl("POST", f"/chat-takeovers/{技能}/runs", cfg,
                   {"澜绣工号": 澜绣工号, "输入": 输入 or {}}, 幂等键)
    if 码 == "202" and isinstance(体, dict):
        重放 = str(体.get("note") or "").startswith("同一个幂等键")
        return True, dict(已发起=True, 运行号=体.get("resource_id"), 工作流=体.get("工作流"),
                          核对入口=cfg["地址"].rstrip("/") + (体.get("核对入口") or ""),
                          说明=("**这是刚才已经发起的那一条,没有新建**;" if 重放 else "")
                               + "已排队,还没跑完;要等人工核对通过才会写进系统")
    码文 = (体 or {}).get("code") if isinstance(体, dict) else None
    话 = (体 or {}).get("message") if isinstance(体, dict) else str(体)[:160]
    if 码文 == "TAKEOVER_OFF":
        _内存["items"] = None            # 清单旧了:下一次重拉
        return False, dict(error=f"{话}。这件事已经交还给你自己做了 —— 照常用技能", 交还=True)
    # 明确拒绝**不兜底**(用户 2026-11-14 拍「只在没配好时兜底,明确拒绝的照旧拦」):
    # 403 FORBIDDEN = 绑定的账号没有发起这个工作流的权限 —— 那是有人**定了**不让这么做,
    # 技能绕过去做等于把权限判断悄悄作废。没发布 / 没绑定 / 连不上 / 5xx 是「没配好」,照旧兜。
    if 码 == "403" or 码文 == "FORBIDDEN":
        return False, dict(
            error=f"工作流没发起:{话 or '绑定的账号没有发起权限'}。", 交还=False, 无权限=True,
            说明="**这一轮别改用技能自己做** —— 这是权限拦下的,不是没配好。"
                "告诉用户:他的账号没有发起这个工作流的权限,请找管理员在管理后台开通后再试")
    # 其余一律**兜底**(用户 11-12 拍):连不上 / 没发布 / 没绑定 / 5xx。写盘让钩子这一轮放行技能。
    记兜底(技能)
    原因 = f"{体}" if 码 is None else f"HTTP {码}{' ' + 码文 if 码文 else ''}:{话}"
    return False, dict(
        error=f"工作流没发起({原因})。",
        交还=True, 兜底=True,
        说明="**这一轮改由你用技能直接做**(工作流没接上)。做完在回复里注明一句"
            "「工作流没接上,这是技能直接整理的,没经人工核对」—— **别说成工作流做的**,也别说「稍后再试」让人干等")


# 取回复的查询参数名 —— 和管理后台 `聊天取回复(澜绣工号: str)` 那个形参同名。**只写这一处**:
# takeover_check 从这里现算它转码后的样子,参数名改了检查跟着动,不会因为夹具里抄了一份而过期
回复查询参数 = "澜绣工号"


def 取回复(运行号, 澜绣工号):
    """这条从聊天发起的运行**现在说了什么、跑到哪了**(用户 10-27 拍「发起时等一会儿 + 可追问」)。

    只认自己发起的那条:管理后台按「聊天发起 + 同一个工号」核,对不上回 404 —— 这里照实转述,不另判。"""
    from urllib.parse import quote
    cfg = 配置()
    if not cfg:
        return False, dict(error="聊天站没配管理后台地址,查不了工作流 —— 请管理员检查聊天站的常驻配置")
    rid = (运行号 or "").strip()
    if not rid:
        return False, dict(error="要说清是哪一条运行(运行号),发起时回过")
    码, 体 = _curl("GET", f"/chat-takeovers/runs/{quote(rid, safe='')}/replies?{回复查询参数}={quote(str(澜绣工号 or ''), safe='')}", cfg)
    if 码 == "200" and isinstance(体, dict):
        return True, dict(运行号=rid, 状态=体.get("执行状态中文"), 跑完了=bool(体.get("是终态吗")),
                          在等人工核对=bool(体.get("在等人工核对")), 回复=体.get("回复们") or [],
                          核对入口=cfg["地址"].rstrip("/") + (体.get("核对入口") or ""))
    if 码 is None:
        return False, dict(error=f"{体} —— 现在查不到这条运行,稍后再问")
    话 = (体 or {}).get("message") if isinstance(体, dict) else str(体)[:160]
    return False, dict(error=f"查不到(HTTP {码}):{话}")


def 等回复(运行号, 澜绣工号, 最多秒=None, 间隔=2.0, 睡=time.sleep):
    """发起后**等一会儿**:跑完、停在人工核对、或到点,哪个先到停哪个;回最后一次查到的。

    为什么不一直等:人工核对是小时级的,聊天这一轮不能挂着;到点没说完的,用户追问时用 workflow_replies 取。
    `最多秒` 默认 20,`LANXIU_TAKEOVER_WAIT` 可改(检查里设成 0,不真等)。"""
    if 最多秒 is None:
        try:
            最多秒 = float(os.environ.get("LANXIU_TAKEOVER_WAIT") or 20)
        except ValueError:
            最多秒 = 20.0
    起 = time.time()
    ok, 回 = 取回复(运行号, 澜绣工号)
    while ok and not (回["跑完了"] or 回["在等人工核对"]) and time.time() - 起 + 间隔 <= 最多秒:
        睡(间隔)
        ok, 回 = 取回复(运行号, 澜绣工号)
    if ok:
        回["还在跑"] = not (回["跑完了"] or 回["在等人工核对"])
    return ok, 回
