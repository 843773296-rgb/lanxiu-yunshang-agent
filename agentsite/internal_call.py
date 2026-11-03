# -*- coding: utf-8 -*-
"""管理后台 → 聊天站的内部调用(访问 API 聊天那一半,用户 2026-11-03 拍「先工作流、再聊天」之后的第二步)。

## 为什么要有这条通道

管理后台自己跑不了聊天对话:装配、工具、技能、回答体检都在聊天站。而聊天站只认**导购登录的网页身份**
(cookie → 澜绣后台 /api/me)。外部系统拿着访问密钥来问,不是任何一个人登录了网页 ——
所以要一条**服务对服务**的口:管理后台核完密钥、限量、花费,再带着「发密钥那个人绑的澜绣工号」来这里跑一轮。

## 这里管的三件(判据见 agentsite/internal_call_check.py)

  ① **凭证**:请求头 `X-Lanxiu-Internal` 要和本机一份凭证文件的内容一致(常量时间比较);
     凭证文件不在仓库里(路径由环境变量 LANXIU_INTERNAL_FILE 指,默认 ~/.lanxiu/internal-call),
     两边服务各读同一个文件。**文件不在 / 是空的 → 整条通道关着**,不退回成「谁都能调」
  ② **只收本机来的**:对端地址不是 127.0.0.1 / ::1 一律拒 —— 凭证漏了,也只能在这台机器上用
  ③ **身份从员工表现查**(工号 → 姓名 / 角色 / 门店,只认在职的),不信请求体里写的姓名角色 ——
     和网页那条路一样:身份来自签发方,不来自使用方

会话归属记在**这把密钥**名下(`访问密钥:<id>`),不记在那个人名下:同一个人的网页会话和 API 会话互相接不上,
别的密钥(哪怕同一个人发的)也接不上。
"""
import hmac
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
澜绣库 = os.path.join(os.path.dirname(HERE), "backend", "lanxiu.db")
凭证头 = "X-Lanxiu-Internal"
本机 = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def 凭证文件():
    return os.environ.get("LANXIU_INTERNAL_FILE") or os.path.expanduser("~/.lanxiu/internal-call")


def 读凭证(路径=None):
    """→ 凭证串;文件不在或是空的 → None(通道关着)。"""
    try:
        with open(路径 or 凭证文件(), encoding="utf-8") as f:
            v = f.read().strip()
        return v or None
    except OSError:
        return None


def 核对(头值, 对端, 路径=None):
    """→ (行不行, 为什么)。三种拒法分开说:没开 / 不是本机 / 凭证不对。"""
    真 = 读凭证(路径)
    if not 真:
        return False, "内部通道没开(本机没有凭证文件)—— 不退回成谁都能调"
    if (对端 or "") not in 本机:
        return False, f"只收本机来的内部调用(对端是 {对端})"
    if not 头值 or not hmac.compare_digest(str(头值).encode(), 真.encode()):
        return False, "内部凭证不对"
    return True, ""


def 员工(工号, 库=None):
    """工号 → {no, name, role, shop};不在职 / 查不到 → None。字段和网页登录换出来的那份一样(backend/auth.who)。"""
    if not 工号:
        return None
    c = sqlite3.connect(f"file:{库 or 澜绣库}?mode=ro", uri=True)
    try:
        r = c.execute("SELECT no, name, role, shop FROM staff WHERE no=? AND status='启用'", (str(工号),)).fetchone()
    finally:
        c.close()
    return {"no": r[0], "name": r[1], "role": r[2], "shop": r[3]} if r else None


def 会话主(密钥id, me):
    """会话归属记在密钥名下;角色 / 门店照抄那个人的(sessions.check 会在权限变了时拒续聊)。"""
    return {"no": f"访问密钥:{密钥id}", "name": f"访问密钥 {密钥id}", "role": (me or {}).get("role"),
            "shop": (me or {}).get("shop")}
