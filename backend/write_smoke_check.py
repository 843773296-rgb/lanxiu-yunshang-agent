#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写接口冒烟 —— **每个 POST 能走到的写函数,都拿真参数真跑一遍,并确认库里真的变了。**

## 为什么要有这个

2026-09-17 补了只读入口的冒烟(`page_smoke_check.py`),起因是六个读接口
坏在库里而 99 步门禁一项没红。那次补的是**读的那一半**,
写的那一半一直欠着:44 个 POST 路径,真正被往返验证过的只有 5 条。

而写接口坏起来比读接口更隐蔽:读接口坏了,页面当场空白;
**写接口坏了,按钮照样变绿,数据没进去** —— 要等下一个人来查账才发现。

> 这一天里同一个形状撞了四次:
> 飞书画板「接口返回成功但箭头没画出来」、
> `get_order` 「字段挂上了但 return 重新拼了个 dict」、
> 咬合「红了但红的不是那一条」、
> 售后规则「表里没有商品字段,于是零违规打绿勾」。
> **「我写了」和「它生效了」是两个独立的事实,而失败的那一半通常不出声。**

## 判据比只读那边多一条:**得真的写进去**

对每个写入口:

  1. 不抛异常
  2. 返回的不是 `{"error": ...}`
  3. **调用前后,库里那张表真的变了** ← 只读冒烟没有这一条

第 3 条是这套检查的全部价值。只验前两条的话,一个「什么都没做但返回 ok」的
写接口会稳稳地通过 —— 而那正是最该抓的一类。

## 在**副本**上跑,不碰共享库

写冒烟跑一次脏一次,而脏了之后别的检查会红,红的原因却和真问题无关。
所以每次把 `lanxiu.db` 拷到 `$TMPDIR`,把 `server.DB` / `api.DB` 指过去,
跑完删掉。**主库一个字节都不动** —— 这也让它在有别的会话正在重建数据时仍然能跑。

## 用例表是手写的,所以它自己要被查

第一条检查是「**`do_POST` 能走到的写函数,要么在用例表里,要么在豁免表里**」。
这是**黑名单**:新加一个写接口而忘了加用例,这里立刻红,
而不是悄悄少验一个入口 —— 少验一个和全部通过在输出上长得一模一样。
"""
import ast
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAIL = []
DONE = []

# 还没有冒烟用例的写接口数。**只许降不许涨** —— 补一个改一次这个数。
# 定在当前值而不是 0:一次补 17 个不现实,而「等补完再进门禁」的下场是永远补不完。
欠账上限 = 15


def ck(name, ok, n, msg=""):
    DONE.append(name)
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 可达的写函数():
    """从 `do_POST` 的函数体里,现推它能调到哪些模块级函数。

    **不手写清单** —— 手写的会漂:加一个写接口而忘了往清单里加,
    这道检查就少验一个,且照样全绿。
    """
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    t = ast.parse(src)
    顶层 = {n.name for n in t.body if isinstance(n, ast.FunctionDef)}
    post = next((n for n in ast.walk(t)
                 if isinstance(n, ast.FunctionDef) and n.name == "do_POST"), None)
    if post is None:
        raise RuntimeError("server.py 里找不到 do_POST —— 这道检查已经失明")
    调 = set()
    for n in ast.walk(post):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            调.add(n.func.id)
    return 调 & 顶层


# ── 豁免:`do_POST` 走得到,但不该进写冒烟的 ──────────────────────────
# 每条都要写清为什么。**「先不测」不算理由** —— 那是欠账,该写进 intent。
豁免 = {
    "_actor_of": "取当前操作人,纯读",
    "_me": "取当前登录者,纯读",
    "_role_of": "取角色,纯读",
    "_now": "取当前时间,纯函数",
    "_u": "URL / 参数解析,纯函数",
    "_eval": "评测入口,要调模型、要花钱 —— 门禁不跑花钱的东西",
    "_truths": "读真值表,纯读",
    "rows": "通用查询,纯读",
    "顾问工号": "按显示串反查工号,纯读",
    "resolve_combo": "相容矩阵试算,**不写库**(实测:调用前后 0 行变化)",
    "gen_draft": "生成草稿文本,要调模型",
    "import_customers": "批量导入,要上传文件;**待补** —— 见 intent/write-smoke-debt.md",
    "create_download": "建导出任务,产物落磁盘不落库;**待补**",
    "scheme_status": "方案状态流转,**待补**(等数据重建落地)",
    "merge_transit": "客户合并,**待补** —— 合并用例是 truth 夹具,冒烟会动到它们",
}


def 跑一个(名, 调用, 看表):
    """调一次写函数,返回 (出错原因 or None, 库里变了几行)。"""
    import server
    前 = 计数(看表)
    try:
        r = 调用(server)
    except Exception as e:
        return f"抛异常 {type(e).__name__}: {e}", 0
    if isinstance(r, dict) and r.get("error"):
        return f"返回 error:{str(r['error'])[:60]}", 0
    # **「接口说它什么都没做」和「接口该做却没做」要分开报。**
    # 前者是用例失效(给的值不会造成变化),后者才是接口坏了 ——
    # 而它们在「行数没变」这一个信号上长得一模一样。
    if isinstance(r, dict) and r.get("code") in ("NOCHANGE", "NO_CHANGE"):
        return ("**用例失效**:接口明说「没有字段发生变化」,"
                "说明这个用例给的值已经不会造成写入了 —— 坏的是用例,不是接口"), 0
    后 = 计数(看表)
    return None, 后 - 前


def 计数(表):
    c = sqlite3.connect(副本)
    try:
        return c.execute(f"SELECT count(*) FROM {表}").fetchone()[0]
    finally:
        c.close()


def 取(sql, *a):
    c = sqlite3.connect(副本)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute(sql, a).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


副本 = None


def 用例表():
    """(写函数名, 怎么调, 该往哪张表写)。参数**从副本里现取**,不写死 id ——
    写死的 id 会被一次合理的数据变更打断,而打断时这里只会说「参数不存在」。"""
    客 = 取("SELECT id,name,phone FROM customer WHERE archived IS NULL OR archived=0 LIMIT 1")
    员 = 取("SELECT no FROM staff WHERE role='顾问' LIMIT 1")
    单 = 取("SELECT id,customer_id FROM ordr LIMIT 1")
    任 = 取("SELECT id FROM task WHERE status<>'已完成' LIMIT 1") if 有表("task") else None

    出 = []
    if 客:
        # create_followup(d, actor) —— d 里要 customer_id + content
        出.append(("create_followup",
                   lambda s: s.create_followup(
                       {"customer_id": 客["id"], "content": "冒烟:回访一次",
                        "channel": "电话",
                        "advisor": 员["no"] if 员 else None},
                       员["no"] if 员 else "魏欣新"),
                   "followup"))
        # adjust_lifecycle(cid, to, reason, actor) —— 写 customer 并记 oplog
        出.append(("adjust_lifecycle",
                   lambda s: s.adjust_lifecycle(客["id"], "活跃", "冒烟调整",
                                                员["no"] if 员 else "魏欣新"),
                   "op_log"))
        # update_customer(cid, d, actor, role)
        出.append(("update_customer",
                   # ⚠️ 用 `addr`,**不要用 `remark`** —— update_customer 根本不处理 remark,
                   # 传它会走到「没有字段发生变化」那条路,返回 ok 但什么都不写。
                   # 第一版就是这么写的,于是检查报「返回成功但库里没变」——
                   # 说得没错,但**坏的是用例不是接口**。
                   lambda s: s.update_customer(
                       客["id"], {"addr": "冒烟地址 " + str(id(s))[-6:]},
                       员["no"] if 员 else "魏欣新", "总部运营"),
                   "op_log"))
    return [x for x in 出 if 有表(x[2])]


def 有表(t):
    c = sqlite3.connect(副本)
    try:
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                              (t,)).fetchone())
    finally:
        c.close()


def 指到副本():
    """把**所有**指着真库的模块级 DB 常量改到副本上,返回改了几个。

    逐个点名(`server.DB = 副本; api.DB = 副本`)是行不通的:
    全仓 23 个模块各带一份 `DB`,今天点全了,明天加一个模块又漏。
    这里按**性质**改:凡是模块里有个叫 DB 的字符串、且它指向 lanxiu.db,就改掉。
    """
    import importlib
    # 先把写路径上会用到的模块都 import 进来,否则 sys.modules 里没有就扫不到
    for m in ("server", "api", "oplog", "ops", "tasks", "auth", "files",
              "booking", "img", "appt_expire"):
        try:
            importlib.import_module(m)
        except Exception:
            pass
    n = 0
    for name, mod in list(sys.modules.items()):
        d = getattr(mod, "DB", None)
        if isinstance(d, str) and d.endswith("lanxiu.db") and d != 副本:
            setattr(mod, "DB", 副本)
            n += 1
    return n


def main():
    global 副本
    主库 = os.path.join(HERE, "lanxiu.db")
    if not os.path.exists(主库):
        print("❌ 找不到库")
        return 1

    # ── ① 覆盖校验:每个写函数要么有用例,要么明说豁免 ────────────────
    可达 = 可达的写函数()
    有用例 = {x[0] for x in []}          # 先占位,下面算完再补
    副本 = os.path.join(tempfile.mkdtemp(prefix="wsmoke-"), "lanxiu.db")
    shutil.copy(主库, 副本)
    try:
        用例 = 用例表()
        有用例 = {x[0] for x in 用例}
        没覆盖 = sorted(可达 - 有用例 - set(豁免))
        # **欠账上限:只许降不许涨。**
        # 一次把 17 个写接口全补上不现实,而「先不进门禁,等补完再说」的下场是
        # 永远补不完 —— 这个项目在咬合欠账上走过同一条路(78 → 0,靠的就是这个上限)。
        # 所以现在就进门禁,卡住**当前值**:补一个就把这个数减一,
        # 新加一个没覆盖的写接口会立刻红。
        ck(f"① 没覆盖的写接口不超过 {欠账上限} 个(只许降不许涨)",
           len(没覆盖) <= 欠账上限, len(可达),
           f"现在 {len(没覆盖)} 个 —— **涨了,新加的写接口没带冒烟用例**:{没覆盖[:5]}"
           if len(没覆盖) > 欠账上限 else
           f"用例 {len(有用例)} / 豁免 {len(可达 & set(豁免))} / 欠着 {len(没覆盖)}"
           f" —— 欠着的:{没覆盖[:6]}{' …' if len(没覆盖) > 6 else ''}")
        if len(没覆盖) < 欠账上限:
            print(f"     ℹ️ 欠账从 {欠账上限} 降到 {len(没覆盖)} 了,"
                  f"**把文件里的「欠账上限」改成 {len(没覆盖)}**,否则降下来的又能涨回去")

        # ── ② 每个用例:不抛、不 error、**库里真的变了** ────────────
        import server
        import api
        # ⚠️ **不是只改 server.DB 和 api.DB。**
        # 第一版就是那么写的,结果 `oplog.py` **有它自己的 `DB` 常量**,
        # 于是 log_op 绕过沙箱,**往真库里写进了 3 行 op_log** ——
        # 而整个过程一声不响:检查照跑,输出照出,只有事后去查才发现。
        # 全仓一共 23 个模块各带一个 DB 常量,**手工点名迟早漏一个**,
        # 所以改成:扫一遍已加载的模块,谁有 DB 指着这个库就把谁改掉。
        改了 = 指到副本()
        if 改了 < 3:
            # 至少 server / api / oplog 三个。少于这个数说明扫描没生效,
            # **而那时冒烟会安静地往真库里写** —— 这比漏测严重得多。
            raise RuntimeError(f"只把 {改了} 个模块指到副本,少于预期 —— "
                               f"沙箱没建起来,拒绝往下跑")
        坏 = []
        for 名, 调, 表 in 用例:
            错, 变 = 跑一个(名, 调, 表)
            if 错:
                坏.append(f"{名}:{错}")
            elif 变 <= 0:
                # **这一条是这套检查的全部价值。**
                坏.append(f"{名}:**返回成功,但 `{表}` 一行没多** —— "
                          f"「我写了」和「它生效了」是两件事")
        ck("② 写接口真跑,且库里真的变了", not 坏, len(用例),
           f"坏的 {坏[:3]}" if 坏 else
           "判的是**调用前后行数真的变了**,不只是「没报错」")
    finally:
        shutil.rmtree(os.path.dirname(副本), ignore_errors=True)

    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 写接口冒烟 {len(DONE)} 条全过")
    return 0


咬合 = [
    ('把用例表里的函数名写错一个字(create_followup → create_followupX),欠账从 15 涨到 16',
     '没覆盖的写接口不超过'),
    ('让 create_followup 只返回 ok 不写库(把 _insert 那一句吞掉)',
     '写接口真跑,且库里真的变了'),
]
# ⚠️ 第一条的破坏点换过一次:原来写的是「把那一行整个删掉」,
# 结果改出来是 SyntaxError,脚本红在语法上而不是红在判据上 ——
# **咬合的第三关正是为了抓这个:红了,但红的不是那一条。**

if __name__ == "__main__":
    print("写接口冒烟 · 在库的副本上跑")
    print("=" * 80)
    sys.exit(main())
