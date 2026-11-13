# -*- coding: utf-8 -*-
"""门店用量账 + 费用闸(用户拍板:11-12 第十三条「试点期每月 150 美元,到 80% 提醒、到顶停 Opus 升级」;
11-13「本月费用**只算门店真实使用**」「拿不到费用数时难题**照常换**贵模型」)。

**为什么另记一本账,不用管理后台那本 usage_ledger**(11-13 查实):
  · 那本混着评测 / 夜跑 / 开发调试(本月 5 万多行,绝大多数是评测),按它算一开就到顶;
  · 而聊天站门店真实的调用**一笔都没进去**(本月 3680 条聊天站 trace,用量行 0)。
  所以账记在**门店入口**:聊天站 /run 每答完一轮记一笔(被升级的那轮两遍都记)。评测、夜跑、脚本直接调
  sdk.run,不经过 /run,天然不进这本账 —— 口径靠「在哪记」落地,不靠事后按来源筛。

**钱按参考价**:sdk.cost_of 按上线 API 标价算(本机走月租登录态时,这是「上线后要付的钱」,不是今天的账单)。

**费用闸(纯函数 `闸`)**:
    本月 < 80%            → 照常升级
    80% ≤ 本月 < 上限      → 照常升级,带提醒
    本月 ≥ 上限            → **不升级**(Haiku 那一遍直接交),说清原因
    拿不到本月数(None)  → **照常升级**(用户 11-13 拍),说清「费用数拿不到」
上限和比例与管理后台上线验收页(管理后台/services/api/app/acceptance_flow.py 的 月费用上限)是同一个数,
store_usage_check 对账两边一致。

账文件:agentsite/usage/门店用量-YYYY-MM.jsonl(不进版本库:每行带工号,是运营数据不是代码)。
"""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
账目录 = os.environ.get("LANXIU_STORE_USAGE_DIR") or os.path.join(HERE, "usage")

月上限 = 150          # 美元,参考价(用户 11-12 拍)
提醒比例 = 0.8        # 到 80% 提醒(用户 11-12 拍)


def _月(今天=None):
    d = 今天 or datetime.date.today()
    return f"{d.year}-{d.month:02d}"


def _文件(月):
    return os.path.join(账目录, f"门店用量-{月}.jsonl")


def 记(trace_id, 花费, 工号=None, 模型=None, 升级=False, 今天=None):
    """聊天站 /run 每答完一遍记一笔。花费 None / 非数 → 记成未知(本月合计就成了「拿不到」,不当 0 算)。"""
    try:
        钱 = float(花费) if 花费 is not None else None
    except (TypeError, ValueError):
        钱 = None
    os.makedirs(账目录, exist_ok=True)
    行 = dict(ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), trace_id=trace_id,
             花费=钱, 工号=工号, 模型=模型, 升级=bool(升级))
    with open(_文件(_月(今天)), "a", encoding="utf-8") as f:
        f.write(json.dumps(行, ensure_ascii=False) + "\n")


def 本月(今天=None):
    """→ (合计 或 None, 笔数, 说明)。None = 拿不到(读不了 / 有一笔金额未知 / 有坏行)—— **拿不到 ≠ 0**。
    这个月一笔都没有 = 0(文件不存在是「还没人用」,不是拿不到)。"""
    p = _文件(_月(今天))
    if not os.path.exists(p):
        return 0.0, 0, "这个月门店还没有调用"
    合计, 笔, 未知, 坏 = 0.0, 0, 0, 0
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    坏 += 1
                    continue
                笔 += 1
                if isinstance(r.get("花费"), (int, float)):
                    合计 += r["花费"]
                else:
                    未知 += 1
    except OSError as e:
        return None, 0, f"账读不了({type(e).__name__})"
    if 坏 or 未知:
        return None, 笔, f"本月 {笔} 笔里 {未知} 笔金额未知、{坏} 行读不了 —— 合计拿不到"
    return round(合计, 4), 笔, f"本月 {笔} 笔"


def 本月工号们(今天=None):
    """这个月门店用量账里出现过的工号(费用提醒派给这些人所在门店的店长)。读不了 → 空集合。"""
    p = _文件(_月(今天))
    号 = set()
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                try:
                    x = json.loads(ln).get("工号")
                except ValueError:
                    continue
                if x:
                    号.add(str(x))
    except OSError:
        pass
    return 号


def 闸(本月合计, 上限=月上限, 比例=提醒比例):
    """→ dict(可升级, 状态, 说明)。状态 ∈ 正常 / 提醒 / 到顶 / 拿不到。纯函数,不读账。"""
    if 本月合计 is None:
        return dict(可升级=True, 状态="拿不到",
                    说明=f"本月门店费用拿不到 —— 按拍板照常换贵模型(上限 {上限} 美元没法核)")
    if 本月合计 >= 上限:
        return dict(可升级=False, 状态="到顶",
                    说明=f"本月门店费用 {本月合计:.2f} 美元,到了上限 {上限} —— 难题不再换贵模型,先用小模型的答案")
    if 本月合计 >= 上限 * 比例:
        return dict(可升级=True, 状态="提醒",
                    说明=f"本月门店费用 {本月合计:.2f} 美元,过了上限 {上限} 的 {int(比例 * 100)}%")
    return dict(可升级=True, 状态="正常", 说明=f"本月门店费用 {本月合计:.2f} 美元(上限 {上限})")


def 现在(今天=None):
    """读账 + 过闸,app.py 在要升级的那一刻调。读账本身出错也落在「拿不到」(照常升级),不让聊天崩。"""
    try:
        合计, 笔, 说 = 本月(今天)
    except Exception as e:  # noqa: BLE001  —— 账的任何问题都不许挡住回答
        合计, 笔, 说 = None, 0, f"读账出错({type(e).__name__})"
    g = 闸(合计)
    g.update(本月=合计, 笔数=笔, 账=说)
    return g
