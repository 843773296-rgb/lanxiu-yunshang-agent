#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天助手 · 后台这一版 == 模型真收到的那一版吗(用户 2026-10-28 拍「聊天助手配置页分两步」,第 2 步的核对口)。

## 为什么要这一条

后台配置页上显示着「生产 = v3」,而聊天站眼里可能是另一份:没配地址(用代码)、拉不到(用落盘的旧版)、
或者组装时规矩挑得和后台推算的不一样(两份挑法实现)。
> 一个「后台改了、模型真收到改过的」和一个「后台改了、模型收到的还是代码那份」,
> **在后台那一页上长得一模一样。**

## 怎么判(真调聊天站的代码,不重实现)

  ① 聊天站服务(launchd com.lanxiu.agentsite)配了管理后台地址 —— 没配就是用代码,后台上看不出来
  ② **绕过缓存**现拉一次(`assistant_client.生产版(强制=True)`):拉到的版本号 == 后台生产指针
     (缓存那 30 秒会让「比的是上一版」也过 —— 并行会话 10-28 提的)
  ③ 用聊天站自己的组装函数(`sdk._助手组装`)拼出这一版,逐项比:
     · 开头 / 结尾原样在提示词里(head="" 也算一种,不许被兜底成代码那份)
     · 挑出的规矩编号 == 后台那一版存的(后台按导入的规矩推算 vs 聊天站 prompts.assemble 真挑)
     · 工具 == 后台开着的 ∩ 聊天站这个角色的名单(只收不加)
     · **从代码导入的那几版**另比全文哈希(后台存着导入时真组装的全文);后台编辑出的版本没有全文,**明说没比**

## 不做什么

  · 不写:落盘文件指到临时目录;不切生产指针
  · 没指定生产 → 「没东西可验」,⏸ 单独报,**不算通过**
  · 不判模型(第 2 步模型先不接 —— 难题分流在用默认模型,接了要动分流;模型进核对字段照实记)

跑:`./agentsite/.venv/bin/python tools/assistant_effect_check.py`
"""
# 咬合 —— 改坏的是什么、该红的是哪一条。
# ⚠️ ② ③ 两段**只有后台指定了生产才走得到**,而 2026-10-29 挂进门禁时生产指针是空的(切指针要用户审)——
#    那两段现在改坏了也不会红,登记成咬合就是一条「从没红过却写着会红」的记录。等生产真切过再补那两条。
# ⚠️ ① 那条(「三个都配了」改恒真)**在配齐了的机器上不可观测** —— 真不真结果都一样;
#    10-29 正式重放时就是「改坏了却没红」。改成攻击**被测代码**:客户端不去后台拉、直接退回代码。
咬合 = [
    ("聊天站客户端不去后台拉、直接当「没配」退回代码", "绕过缓存现拉到的就是后台生产那一版"),
]

import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agentsite"), ROOT, os.path.join(ROOT, "backend")]
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.lanxiu.agentsite.plist")
键们 = ("LANXIU_USAGE_URL", "LANXIU_BRIDGE_PROJECT", "LANXIU_USAGE_USER")
角色 = "task"
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
过, 挂, 没验 = [], [], []


def ck(名, 真, 补=""):
    print(f"  {G + '✅' + D if 真 else R + '❌' + D} {名}" + (f"  {str(补)[:300]}" if 补 and not 真 else ""))
    (过 if 真 else 挂).append(名)


def 聊天站配置():
    import plistlib
    try:
        with open(PLIST, "rb") as f:
            env = plistlib.load(f).get("EnvironmentVariables") or {}
    except (OSError, plistlib.InvalidFileException):
        return None
    return {k: env.get(k) for k in 键们}


def 后台生产(cfg):
    """后台记着的:生产指针和那一版内容(含导入版的全文哈希 —— 详情接口里没有,单独查版本列表)。"""
    base = f"{cfg['LANXIU_USAGE_URL'].rstrip('/')}/api/v1/projects/{cfg['LANXIU_BRIDGE_PROJECT']}"
    r = subprocess.run(["curl", "-sS", "-m", "8", f"{base}/chat-assistants/by-role/{角色}/production",
                        "-H", f"X-Dev-User: {cfg['LANXIU_USAGE_USER']}"], capture_output=True, text=True)
    return json.loads(r.stdout)


def 核对(cfg):
    print("▸ ① 聊天站服务配了管理后台地址吗")
    if not os.path.exists(PLIST):
        print(f"  ⏸ 这台机器上没有 {os.path.basename(PLIST)} —— **不适用,不是通过**(CI / 干净克隆)")
        没验.append("这台机器上没有 com.lanxiu.agentsite(全没验)")
        return
    缺 = [k for k in 键们 if not (cfg or {}).get(k)]
    ck("三个都配了(没配 = 聊天站用代码,而后台上看不出来)", cfg is not None and not 缺, 缺 or "读不到 plist")
    if cfg is None or 缺:
        return
    try:
        后 = 后台生产(cfg)
    except Exception as e:
        ck("后台按角色取生产取得到", False, f"{type(e).__name__}: {e}")
        return
    import assistant_client as ac
    import sdk
    旧 = {k: os.environ.get(k) for k in 键们}
    旧目录 = ac._落盘目录
    try:
        os.environ.update({k: cfg[k] for k in 键们})
        ac._落盘目录 = tempfile.mkdtemp()           # 核对不碰聊天站真的那份落盘
        print("\n▸ ② 绕过缓存现拉:拿到的就是后台生产那一版")
        取 = ac.生产版(角色, 强制=True)
        站版 = 取.get("版") or {}
        # 没指定生产时这一条照样验:聊天站真连上了后台、而且和后台一样认为「没指定」——
        # 「没配 / 连不上 → 用代码」和「后台说没指定 → 用代码」在聊天站的回答上一模一样,只有「来源」分得开
        ck(f"绕过缓存现拉到的就是后台生产那一版(后台 {('v' + str(后['版本号'])) if 后.get('版本号') is not None else '没指定'} / "
           f"聊天站 {取['来源']} {('v' + str(站版.get('版本号'))) if 站版 else '用代码'})",
           取["来源"] == "后台现拉" and 站版.get("版本号") == 后.get("版本号"), 取)
        if 后.get("版本号") is None:
            print(f"  {Y}⏸ 后台没指定生产 —— 聊天站照用代码,「后台这一版 == 模型收到的」**没东西可验**,不算通过{D}")
            没验.append("后台没指定生产(③ 没验)")
            return
        if not 站版:
            return
        print("\n▸ ③ 用聊天站自己的组装函数拼这一版,逐项比")
        系统, 工具, 装上 = sdk._助手组装(角色, 站版)
        名单 = list(sdk._tools_for(角色))
        ck("开头原样在提示词开头(空开头也算,不许被兜底成代码那份)", 系统.startswith(站版["开头"]))
        ck("结尾原样在提示词结尾", 系统.endswith(站版["结尾"]))
        ck(f"工具 == 后台开着的 ∩ 这个角色的名单(只收不加;{len(工具)} 个)",
           sorted(工具) == sorted(t for t in 名单 if t in set(站版["工具"])),
           sorted(set(工具) ^ {t for t in 名单 if t in set(站版["工具"])}))
        ck(f"挑出的规矩 == 后台那一版存的({len(装上)} 条)", list(装上) == list(后.get("规矩") or []),
           {"只在聊天站": sorted(set(装上) - set(后.get("规矩") or [])),
            "只在后台": sorted(set(后.get("规矩") or []) - set(装上))})
        全文 = 后.get("全文哈希")
        if 全文:
            ck("从代码导入的这一版:全文哈希也对得上", "sha256:" + hashlib.sha256(系统.encode()).hexdigest() == 全文)
        else:
            print(f"  {Y}⏸ 这一版是后台编辑出的,后台没存全文 —— 全文**没比**(只比了上面四项){D}")
            没验.append("全文(后台编辑出的版本)")
    finally:
        ac._落盘目录 = 旧目录
        ac._内存.clear()
        for k, v in 旧.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    print("聊天助手 · 后台这一版 == 模型真收到的那一版吗(真调聊天站的代码核对)\n")
    核对(聊天站配置())
    print()
    if 挂:
        print(f"{R}❌ {len(挂)} 条对不上:{' / '.join(挂)}{D}")
        return 1
    if 没验:
        print(f"{Y}⏸ 对得上的都对上了({len(过)} 条),但「{' / '.join(没验)}」没验到{D}")
        return 0
    print(f"{G}✅ {len(过)} 条全对上{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
