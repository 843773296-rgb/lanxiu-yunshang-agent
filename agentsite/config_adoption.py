# -*- coding: utf-8 -*-
"""聊天站「实际用的是哪一版」—— 给管理后台并排「目标版本 / 实际版本」(用户 11-11「按你的顺序做」第 ② 步)。

缘起:后台把店长助手切到 v8、v9,页面显示「已上生产」,而聊天站的术语 / 实体识别 / 路由 / 意图
**一个进程只同步一次**(用户拍的「启动时同步」)—— 不重启就还是旧的。11-11 一天手动跑脚本核了三次。
> 「上了生产」和「聊天站用上了」是两件事,而后台页面上只看得到前一件。

这里**只读进程里的缓存,不触发同步**:还没人问过(缓存空)就照实说「还没加载」,不为了回答这个问题去加载一次 ——
那样报的就是「被这次查询加载的」,不是「一直在用的」。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _进程启动于():
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True, timeout=5).stdout.strip()
        return out or None
    except Exception:
        return None


def _一项(d):
    if not isinstance(d, dict):
        return {"态": "没有", "版本": None, "版本id": None}
    return {"态": d.get("态"), "版本": d.get("版本"), "版本id": d.get("版本id"), "来源": d.get("来源"),
            "取到于": d.get("取到于")}


def 实际加载(角色="task", 缓存=None):
    """→ {角色, 加载了吗, 进程启动于, 术语 / 实体识别 / 路由 / 意图: {态, 版本, 版本id…}}。
    缓存 = sdk._术语缓存(测试可以传一份假的)。"""
    if 缓存 is None:
        sdk = sys.modules.get("sdk")
        缓存 = getattr(sdk, "_术语缓存", {}) if sdk else {}
    底 = {"角色": 角色, "进程": os.getpid(), "进程启动于": _进程启动于(), "查询于": time.strftime("%Y-%m-%d %H:%M:%S")}
    态 = 缓存.get(角色)
    if not 态:
        return {**底, "加载了吗": False,
                "说明": "这个进程启动后还没人用这个角色问过 —— 配置要第一次提问时才加载;不是「没配」"}
    return {**底, "加载了吗": True, "术语": _一项(态), "实体识别": _一项(态.get("实体识别")),
            "路由": _一项(态.get("路由")), "意图": _一项(态.get("意图"))}
