#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天接管 · 改了真生效没有(用户 2026-10-28 拍「开关监督」)。

## 为什么要这一条

并行会话 10-28 查出:三个经营分析技能**两天没挂上**,而功能测试全绿 —— 因为测试验的是「代码对不对」,
没有任何东西去问「**线上此刻真按后台那个开关在跑吗**」。接管开关是同一个形状:
管理后台显示「开着」,而聊天站眼里可能是另一份清单(没配地址 → 当全关;连不上 → 用上一次落盘的)。

> 一个「开关开着、聊天站也照着做」和一个「开关开着、聊天站根本没收到」,在管理后台那一页上长得一模一样。

## 怎么判(真调聊天站的代码,不重实现)

  ① 聊天站服务(launchd com.lanxiu.agentsite)配了管理后台地址 / 项目 / 账号 —— 没配就是**全关**,而后台上看不出来
  ② 用那份配置,调聊天站自己的 `takeover_client.清单(强制=True)` 拉一次 → 和管理后台 `GET /switches` 里「开着」的那几条逐条比
  ③ 对每个**开着**的技能,调聊天站自己的 `guards.pre_tool_verdict("Skill", …)` → 必须拦、并点名改调 start_workflow;
     对**关着**的,拦截理由里不许出现 start_workflow(接管不许误伤)

## 不做什么

  · 不写:聊天站「上一次拉成功」的落盘文件在核对期间指到临时目录,真的那份不碰
  · 不判「聊天站进程此刻内存里的缓存」—— 那份最多 30 秒就重拉,核对的是它下一次拉到的
  · 「开着」的样本可能是 0(没人开接管):那时 ③ 照实说「没有开着的,拦截这一半没验到」,**不算通过**,单独标出来

跑:`./agentsite/.venv/bin/python tools/takeover_effect_check.py`(要聊天站的 venv:guards 依赖它)
"""
# 咬合 —— 改坏的是什么、该红的是哪一条。
# (这条检查是并行会话写的,我 2026-10-28 把它挂进 check.sh;
#  **挂进门禁就得带咬合记录** —— 否则它属于「从没红过而没人知道它会不会红」那一类。
#  这个项目记着:97 个检查脚本里有 78 个从没红过,而「红过的」和「没红过的」长得一样。)
咬合 = [
    ("把第 ① 条「三个环境变量都配了」的判断改成恒真",
     "三个都配了"),
    ("把第 ② 条两边清单的比较改成恒真(不真比)",
     "逐条一致"),
]

import json
import os
import plistlib
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agentsite"), os.path.join(ROOT, "backend")]
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.lanxiu.agentsite.plist")
键们 = ("LANXIU_USAGE_URL", "LANXIU_BRIDGE_PROJECT", "LANXIU_USAGE_USER")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
过, 挂, 没验 = [], [], []


def ck(名, 真, 补=""):
    print(f"  {G + '✅' + D if 真 else R + '❌' + D} {名}" + (f"  {str(补)[:240]}" if 补 and not 真 else ""))
    (过 if 真 else 挂).append(名)


def 聊天站配置(plist=PLIST):
    """聊天站服务**真在用**的那三个环境变量(launchd 配置里写的),读不到给 None。"""
    try:
        with open(plist, "rb") as f:
            env = plistlib.load(f).get("EnvironmentVariables") or {}
    except (OSError, plistlib.InvalidFileException):
        return None
    return {k: env.get(k) for k in 键们}


def 后台开着的(cfg):
    """管理后台记着的:{技能: workflow_id}(只要开着的)。"""
    url = f"{cfg['LANXIU_USAGE_URL'].rstrip('/')}/api/v1/projects/{cfg['LANXIU_BRIDGE_PROJECT']}/switches"
    r = subprocess.run(["curl", "-sS", "-m", "8", url, "-H", f"X-Dev-User: {cfg['LANXIU_USAGE_USER']}"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return {x["技能"]: x["workflow_id"] for x in d["现状"]["聊天接管"] if x["开着"]}, \
           {x["技能"] for x in d["现状"]["聊天接管"] if not x["开着"]}


def 核对(cfg):
    print("▸ ① 聊天站服务配了管理后台地址吗(launchd com.lanxiu.agentsite)")
    缺 = [k for k in 键们 if not (cfg or {}).get(k)]
    ck("三个都配了(没配 = 聊天站当全关,而管理后台上看不出来)", cfg is not None and not 缺, 缺 or "读不到 plist")
    if cfg is None or 缺:
        return
    try:
        开, 关 = 后台开着的(cfg)
    except Exception as e:
        ck("管理后台 GET /switches 取得到", False, f"{type(e).__name__}: {e}")
        return

    import takeover_client as tc
    import guards
    旧 = {k: os.environ.get(k) for k in 键们}
    旧落盘 = tc._落盘
    try:
        os.environ.update({k: cfg[k] for k in 键们})
        tc._落盘 = os.path.join(tempfile.mkdtemp(), "last.json")      # 核对不碰聊天站真的那份落盘
        tc._内存.update(at=0, items=None)
        print("\n▸ ② 聊天站拉到的清单 == 管理后台记着开着的")
        站 = tc.清单(强制=True)
        站开 = {k: (v or {}).get("workflow_id") for k, v in (站 or {}).items()}
        ck(f"逐条一致(管理后台开着 {len(开)} 条 / 聊天站拉到 {len(站开)} 条)", 站开 == 开, {"后台": 开, "聊天站": 站开})
        if not os.path.exists(tc._落盘) and 开:
            ck("这次是真拉到的,不是退回了上一次落盘(拉成功会落一份)", False, "临时落盘没写 —— 多半没连上管理后台")

        print("\n▸ ③ 拦截真按这份清单在拦(调的是聊天站自己的 guards)")
        if not 开:
            print(f"  {Y}⏸  现在一条开着的都没有 —— 「开着就拦」这一半**没验到**,不算通过{D}")
            没验.append("开着就拦")
        for sk in sorted(开):
            v = guards.pre_tool_verdict("Skill", {"skill": sk})
            ck(f"「{sk}」开着 → 调不动,理由点名改调 start_workflow", bool(v) and "start_workflow" in v, v)
        for sk in sorted(关 - set(开)):
            v = guards.pre_tool_verdict("Skill", {"skill": sk})
            ck(f"「{sk}」关着 → 不因接管被拦", not (v and "start_workflow" in v), v)
    finally:
        tc._落盘 = 旧落盘
        tc._内存.update(at=0, items=None)
        for k, v in 旧.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    print("聊天接管 · 改了真生效没有(真调聊天站的代码核对管理后台的开关)\n")
    核对(聊天站配置())
    print()
    if 挂:
        print(f"{R}❌ {len(挂)} 条对不上:{' / '.join(挂)}{D}")
        return 1
    if 没验:
        print(f"{Y}⏸  对得上的都对上了({len(过)} 条),但「{' / '.join(没验)}」没有样本、没验到{D}")
        return 0
    print(f"{G}✅ {len(过)} 条全对上{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
