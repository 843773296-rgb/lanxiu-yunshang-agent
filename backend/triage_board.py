#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判质量看板(研判队列未做项第 6 项第一块 · 用户 2026-10-19 拍:总部看全部,店长看本店)。

回答三件事:AI 这段时间判得准不准、哪类最常被改判、换了提示词之后变好没有(按版本拆)。

口径(和旧的 `ops.health()` 不一样的地方,都有理由):
  · **事项数、AI 运行次数、有结论事项数分开数**(外部核查第 5 节第 3 条)—— 同一张工单研判三次是 1 件事、3 次运行;
    混成一个数,重跑多的那类看起来「事多」,采纳率的分母也跟着歪。
  · 每件事按它**最后一次**研判的状态算;运行次数单列。
  · **采纳率 = 已采纳 ÷(已采纳 + 已改判)** —— 「已升级」不进分母:10-17 起升级是交给别人、不是结论
    (`ops.health()` 还把它算成有结论,那个口径是 10-17 之前的)。待复核的也不进。
  · 每个比例都**带着分子分母**;分母小于 10 标「样本少」—— 能跑 AI 的三类现在合计几十条,百分比一跳就是十几个点。
  · 每个数都能**下钻**:返回那一格里是哪几件(工单号 + 研判号),页面点数字就列出来。
  · 按提示词版本拆:版本号是 A-280 那个指纹;10-19 之前跑的研判没有版本号,单独一组「没记版本」,不混进任何一版。

可见范围:总部运营看全部;店长只看本店(门店从工单挂的单据现查:退款 → 押金单的客户,
客户合并 → 那一对里第一条档案,售后 → 维修单);其余岗位不给看。
"""
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

全部可见 = ("总部运营",)
本店可见 = ("店长",)
样本少于 = 10
没记版本 = "没记版本(10-19 之前跑的)"


def _连(db=None):
    import ops
    c = sqlite3.connect(db or ops.DB)
    c.row_factory = sqlite3.Row
    return c


def _门店表(c):
    """→ f(类型, 单据号) → 门店。一次把三张表取齐,不逐件查库。"""
    押金店 = {r[0]: r[1] for r in c.execute(
        "SELECT d.id, cu.shop FROM deposit d JOIN customer cu ON cu.id=d.customer_id")}
    客户店 = {r[0]: r[1] for r in c.execute("SELECT id, shop FROM customer")}
    维修店 = {r[0]: r[1] for r in c.execute("SELECT id, shop FROM maintain")}
    def f(类型, ref):
        ref = str(ref or "")
        if 类型 == "财务人工任务":
            return 押金店.get(ref)
        if 类型 == "客户合并确认":
            return 客户店.get(ref.split("|")[0])
        if 类型 == "售后判责":
            return 维修店.get(ref)
        return None
    return f


def _比(分子, 分母):
    return dict(分子=分子, 分母=分母, 比例=(round(分子 / 分母 * 100) if 分母 else None), 样本少=分母 < 样本少于)


def _一组(事项):
    """事项 = [每件事最后一次研判的那一行(含 运行次数)]。→ 这一组的指标 + 下钻清单。"""
    桶 = defaultdict(list)
    for x in 事项:
        桶[x["status"]].append(dict(task_id=x["task_id"], triage_id=x["id"]))
    采, 改 = len(桶["已采纳"]), len(桶["已改判"])
    高错 = [dict(task_id=x["task_id"], triage_id=x["id"]) for x in 事项
            if x["status"] == "已改判" and x["ai_confidence"] == "高"]
    没解析 = [dict(task_id=x["task_id"], triage_id=x["id"]) for x in 事项 if not (x["ai_root_cause"] or "").strip()]
    return dict(
        事项数=len(事项), AI运行次数=sum(x["运行次数"] for x in 事项), 有结论事项数=采 + 改,
        采纳率=_比(采, 采 + 改), 改判率=_比(改, 采 + 改),
        待复核=len(桶["待复核"]), 已升级=len(桶["已升级"]), 高置信被改判=len(高错), 没解析出根因=len(没解析),
        下钻={"已采纳": 桶["已采纳"], "已改判": 桶["已改判"], "待复核": 桶["待复核"], "已升级": 桶["已升级"],
              "高置信被改判": 高错, "没解析出根因": 没解析})


def 看板(me, db=None):
    """→ {范围, 总体, 按类型, 按版本, 说明}。没权限 → PermissionError。"""
    me = me or {}
    if not me.get("no"):
        raise PermissionError("没有身份 —— 要登录")
    角 = me.get("role")
    if 角 in 全部可见:
        店 = None
    elif 角 in 本店可见:
        店 = me.get("shop")
        if not 店:
            raise PermissionError("店长账号没挂门店,看不了本店的数")
    else:
        raise PermissionError(f"研判看板给总部运营(看全部)和店长(看本店)看,你是「{角}」(用户 10-19 拍)")
    with closing(_连(db)) as c:
        门店 = _门店表(c)
        行 = [dict(r) for r in c.execute(
            "SELECT tr.*, t.type AS task_type, t.ref_id FROM triage tr JOIN task t ON t.id=tr.task_id ORDER BY tr.id")]
    次数 = defaultdict(int)
    最后 = {}
    for r in 行:
        次数[r["task_id"]] += 1
        最后[r["task_id"]] = r                       # 按 id 升序,最后一个就是最近一次
    事项 = []
    for tid, r in 最后.items():
        r = dict(r, 运行次数=次数[tid], 门店=门店(r["task_type"], r["ref_id"]))
        if 店 is None or r["门店"] == 店:
            事项.append(r)
    按类型 = defaultdict(list)
    按版本 = defaultdict(list)
    for x in 事项:
        按类型[x["task_type"]].append(x)
        按版本[(x.get("prompt_ver") or 没记版本)].append(x)
    return dict(
        范围=("全部门店" if 店 is None else 店),
        总体=_一组(事项),
        按类型={k: _一组(v) for k, v in sorted(按类型.items())},
        按版本={k: _一组(v) for k, v in sorted(按版本.items(), key=lambda kv: (kv[0] == 没记版本, kv[0]))},
        说明=("采纳率 = 已采纳 ÷(已采纳 + 已改判);「已升级」和「待复核」不进分母。每件事按最后一次研判算,"
              f"AI 运行次数单列。分母小于 {样本少于} 标「样本少」—— 那时的百分比别当真。"),
    )
