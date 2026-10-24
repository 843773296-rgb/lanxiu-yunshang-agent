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


def 配置():
    c = dict(地址=os.environ.get("LANXIU_USAGE_URL") or None,
             项目=os.environ.get("LANXIU_BRIDGE_PROJECT") or None,
             工号=os.environ.get("LANXIU_USAGE_USER") or None)
    return c if all(c.values()) else None


def _curl(方法, 路径, cfg, 体=None, 幂等键=None):
    """走 curl 不走 urllib:这台机器 Python 的证书校验会失败(本地 http 也统一走一处)。"""
    url = f"{cfg['地址'].rstrip('/')}/api/v1/projects/{cfg['项目']}{路径}"
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
    """这个技能现在被哪条工作流接管;没被接管 → None(交给 harness)。"""
    return 清单().get((技能 or "").strip().lstrip("/"))


def 发起(技能, 澜绣工号, 输入, 幂等键):
    """返回 (成没成, 回给模型的 dict)。开没开、绑没绑都由管理后台判,这里只转述。"""
    cfg = 配置()
    if not cfg:
        return False, dict(error="聊天站没配管理后台地址,发起不了工作流 —— 请管理员检查聊天站的常驻配置")
    码, 体 = _curl("POST", f"/chat-takeovers/{技能}/runs", cfg,
                   {"澜绣工号": 澜绣工号, "输入": 输入 or {}}, 幂等键)
    if 码 == "202" and isinstance(体, dict):
        return True, dict(已发起=True, 运行号=体.get("resource_id"), 工作流=体.get("工作流"),
                          核对入口=cfg["地址"].rstrip("/") + (体.get("核对入口") or ""),
                          说明="已排队,还没跑完;要等人工核对通过才会写进系统")
    if 码 is None:
        return False, dict(error=f"{体} —— 工作流没发起,也别改用技能自己做;请稍后再试或告诉店长")
    码文 = (体 or {}).get("code") if isinstance(体, dict) else None
    话 = (体 or {}).get("message") if isinstance(体, dict) else str(体)[:160]
    if 码文 == "TAKEOVER_OFF":
        _内存["items"] = None            # 清单旧了:下一次重拉
        return False, dict(error=f"{话}。这件事已经交还给你自己做了 —— 照常用技能", 交还=True)
    return False, dict(error=f"发起失败(HTTP {码}{' ' + 码文 if 码文 else ''}):{话}")
