#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约覆盖检查 —— **规格原文是真相源,契约不许漏掉它列的东西**。

## 这条检查在防什么

规格 §18 说「关系和约束**不得省略**」,§15.3 给了一张九行的权限表。
人照着抄一遍之后,最容易发生的事不是抄错,是**后来规格改了而代码没改** ——
而那种漂**不报错**:代码自己是自洽的,测试全过,只是它实现的已经不是需求了。

所以这条检查**不检查我写得对不对,它检查我有没有漏**:
去解析 `docs/规格/` 里那份 md 的表格,把实体名和能力名抽出来,和契约登记表比对。

> **一份没有人比对过的需求文档,和没有需求文档,区别只是多了一个幻觉。**

## 它故意不做的事

不去校验字段名一字不差 —— 规格 §18 明写「字段可根据实现规范命名」。
判据落在**实体和能力有没有被覆盖**上,不落在措辞上(枚举措辞必输,这条教训另有出处)。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "contract"))
import entities as EN, perms as PM, states as ST, errors as ER

规格目录 = os.path.join(ROOT, "docs", "规格")

咬合 = [
    ("从 entities.实体表 里删掉一个实体", "规格 §18 列的实体都登记了"),
    ("从 perms.矩阵 里删掉一行能力",       "规格 §15.3 列的能力都登记了"),
    ("把某个项目级实体的范围改成组织级",   "不按项目隔离的实体都写了理由"),
    ("把 E() 返回值里的 范围理由 去掉",     "不按项目隔离的实体都写了理由"),
    ("让 traces 变成组织级",               "运行记录/用量/审计/版本/样本这些必须在项目范围内"),
    ("改了契约但不重跑生成器",             "契约文档是最新的"),
    ("给某个只追加实体加上 revision 字段", "只追加的实体不许有 revision/归档"),
    ("让「已冻结」能走回「编辑中」",       "冻结/不可变的状态不许回退"),
    ("把「状态待核实」列进终态",           "「不确定」不许当终态"),
]

过, 挂 = [], []
def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:150] if 补 else ''}")
    if not 真: 挂.append(名)
    else: 过.append(名)
    # **样本量 0 要红** —— 空集合上所有性质都成立,
    # 「一个都没扫到」和「全都通过」在输出上长得一模一样。
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


def 读规格():
    fs = [f for f in os.listdir(规格目录) if f.endswith(".md")] if os.path.isdir(规格目录) else []
    if not fs:
        print(f"❌ {规格目录} 里没有规格 md —— **没有真相源,这条检查什么都证明不了**")
        sys.exit(1)
    return "\n".join(open(os.path.join(规格目录, f), encoding="utf-8").read() for f in fs)


def 表格行(文, 小节标题):
    """抽出某个小节下第一张表的每一行第一列。"""
    i = 文.find(小节标题)
    if i < 0: return []
    段 = 文[i:i + 6000]
    出, 在表 = [], False
    for line in 段.splitlines()[1:]:
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            在表 = True
            格 = [c.strip() for c in s.strip("|").split("|")]
            if 格 and not set(格[0]) <= set("-: "):
                出.append(格[0])
        elif 在表 and s and not s.startswith("|"):
            break
    return [x for x in 出 if x and not re.fullmatch(r"(实体|能力|要素|模块|层|项目|阶段)", x)]


文 = 读规格()

# ── ① 规格 §18 列的实体,契约里都要有 ────────────────────────────
规格实体 = []
for 格 in 表格行(文, "## 18. 数据模型与版本关联"):
    # 规格里一格可能写了好几个,用 / 分开(如 organizations/projects/memberships)
    for x in re.split(r"[/、]", 格):
        x = x.strip().strip("`")
        if re.fullmatch(r"[a-z_]+", x): 规格实体.append(x)
登记 = {e["名"] for e in EN.实体表}
漏 = [x for x in 规格实体 if x not in 登记]
ck("规格 §18 列的实体都登记了", not 漏, len(规格实体), f"漏了:{漏}" if 漏 else "")
多 = sorted(登记 - set(规格实体))
# 多出来的不算错(规格说字段可按实现命名,也允许拆表),但要**说出来** ——
# 悄悄多一张表,和悄悄少一张表一样难查。
if 多: print(f"     ℹ️ 契约里多了 {len(多)} 个规格没点名的:{多[:6]}{'…' if len(多) > 6 else ''}")

# ── ② 规格 §15.3 列的能力,权限矩阵里都要有 ──────────────────────
规格能力 = [x for x in 表格行(文, "### 15.3 权限矩阵") if not re.fullmatch(r"[a-z_]+", x)]
漏能力 = [x for x in 规格能力 if x not in PM.矩阵]
ck("规格 §15.3 列的能力都登记了", not 漏能力, len(规格能力),
   f"漏了:{漏能力}" if 漏能力 else "")
ck("六个角色一个不少", len(PM.角色们) == 6, len(PM.角色们), PM.角色们)
# 每一格都要有值 —— 缺一格在判定时会 KeyError,而那时候已经在生产上了
缺格 = [(c, r) for c in PM.矩阵 for r in PM.角色们 if r not in PM.矩阵[c]]
ck("权限矩阵没有空格子", not 缺格, len(PM.矩阵) * len(PM.角色们), 缺格[:3])

# ── ③ 范围:项目级实体必须带 project_id ──────────────────────────
# ⚠️ **这条判据不能从范围本身算出来**(同源谬误,咬合抓到过一次):
# 第一版写的是「项目级实体都带 project_id」,而 project_id 正是依据
# 「范围==项目级」加上的 —— 把一张表改成组织级,它就从被检查的集合里消失了,
# 检查永远不会红。现在改成从**另一头**判:不按项目隔离的都要写明理由,而且数量棘轮锁死。
非项目 = [e for e in EN.实体表 if e["范围"] in (EN.组织级, EN.全局级)]
无理由 = [e["名"] for e in 非项目 if not (e.get("范围理由") or "").strip()]
ck("不按项目隔离的实体都写了理由(这是个要写明的决定,不是默认值)",
   not 无理由, len(非项目), 无理由)
# 棘轮:现在 4 个(organizations / projects / memberships / pricing_versions)。
# 新增一个必须连这行一起改 —— 而改这行会在 review 里被看见。
ck("不按项目隔离的实体不许囤积(上限 4 个)", len(非项目) <= 4, len(非项目),
   [e["名"] for e in 非项目])
# 业务数据必须落在项目范围里:这几张一旦不是项目级/子对象,就是越权读取的入口。
必须项目级 = {"traces", "spans", "usage_ledger", "audit_events", "prompt_versions",
             "release_manifests", "samples", "chunks", "model_artifacts", "jobs"}
跑掉的 = sorted(必须项目级 - {e["名"] for e in EN.实体表
                            if e["范围"] in (EN.项目级, EN.子对象)})
ck("**运行记录/用量/审计/版本/样本这些必须在项目范围内**", not 跑掉的,
   len(必须项目级), 跑掉的)
无范围 = [e["名"] for e in EN.实体表
          if e["范围"] not in (EN.组织级, EN.项目级, EN.子对象, EN.全局级)]
ck("每个实体的范围都显式写了(不许留空)", not 无范围, len(EN.实体表), 无范围)

# ── ④ 只追加的实体不许有 revision / 归档 ────────────────────────
只追加 = [e for e in EN.实体表 if e["可变性"] == EN.只追加]
坏 = [e["名"] for e in 只追加
      if set(EN.只追加豁免) & set(EN.该有的通用字段(e))]
ck("只追加的实体不许有 revision/归档(能改的历史不是历史)", not 坏, len(只追加), 坏)
ck("审计、Trace、用量、任务事件都是只追加",
   {"audit_events", "traces", "spans", "usage_ledger", "job_events"} <= {e["名"] for e in 只追加},
   len(只追加), [e["名"] for e in 只追加])

# ── ⑤ 不可变的实体每一个都要说清「凭什么认出同一份内容」──────────
# ⚠️ 判据从登记表上的 `内容寻址` 标记来,**不是检查里的一串豁免名单**。
# 第一版豁免写在这儿,结果是:读实体的人看不到它被放过了,
# 而放过的理由(以及理由还成不成立)没有任何地方记着。
寻址 = [e for e in EN.实体表 if e["内容寻址"]]
无哈希 = [e["名"] for e in 寻址 if not any("hash" in f for f in e["关键字段"])]
ck("内容寻址的实体都有哈希(认出「同一份内容」靠它,不靠名字和时间)",
   not 无哈希, len(寻址), 无哈希)
# 反向:标了「不寻址」的,要么是连接行、要么是一次写入的记录 —— 不许拿它当免检牌。
# 每一个都必须在实体的约束或注释里说清为什么,这条由 code review 兜;
# 这里只钉数量上限:**免检的不许囤积**。
不寻址 = [e["名"] for e in EN.实体表
          if e["可变性"] == EN.不可变 and not e["内容寻址"]]
# **棘轮**:现存 3 个登记成上限,只许少不许多。新增一个要连带改这个数,
# 而改这个数会在 review 里被看见 —— 免检不许悄悄囤积。
ck("「不内容寻址」的不可变实体不许囤积(上限 3 个,要加就得连这行一起改)",
   len(不寻址) <= 3, len(不寻址), 不寻址)

# ── ⑥ 状态机:冻结/终态的规矩 ────────────────────────────────────
ck("每条状态机都标了终态", all(m["终态"] for m in ST.状态机表), len(ST.状态机表))
坏终 = [(m["名"], s) for m in ST.状态机表 for s in m["终态"] if m["流转"].get(s)]
ck("终态没有出边(终态还能往外走就不是终态)", not 坏终, len(ST.状态机表), 坏终[:3])
# 「不确定」不许当终态 —— 规格 §11.5:「状态待核实不代表任务已结束」
坏不确定 = [(m["名"], s) for m in ST.状态机表 for s in ST.不确定状态
            if s in m["状态"] and s in m["终态"]]
ck("「不确定」不许当终态(把查不到显示成失败,会让人去重跑还在烧钱的任务)",
   not 坏不确定, sum(1 for m in ST.状态机表 for s in ST.不确定状态 if s in m["状态"]),
   坏不确定)
ck("冻结/不可变的状态不许回退",
   not ST.能不能走("dataset_version", "已冻结", "编辑中"), 1)
# 取消和自然完成会并发 —— 取消请求中必须能走到真实终态(§11.5)
ck("取消请求中能走到「已完成」(取消未生效时不许谎报成已取消)",
   ST.能不能走("training_job", "取消请求中", "已完成"), 1)
ck("「状态待核实」能查回真实状态(它是中间态,不是坟墓)",
   all(ST.能不能走("training_job", "状态待核实", x) for x in ("已完成", "失败")), 2)

# ── ⑦ 授权:不能通过邀请获得自己没有的权限 ───────────────────────
越权 = []
for 我 in PM.角色们:
    for 他 in PM.角色们:
        行, 超 = PM.可以授予吗(我, [], 他, [])
        if 行 and 超: 越权.append((我, 他, 超))
ck("授予判定自洽(说行就真的没超)", not 越权, len(PM.角色们) ** 2, 越权[:2])
行, 超 = PM.可以授予吗("editor", [], "admin", [])
ck("**编辑不能把别人升成管理员**(不能通过邀请获得自己没有的权限)",
   not 行 and 超, 1, f"超出 {len(超)} 条")
# 专项授权只能打开「可授权」,打不开「否」
可以, _ = PM.判("配置密钥与预算", "editor", 专项=["配置密钥与预算"])
ck("专项授权打不开「否」的格子(否则它就是万能钥匙)", not 可以, 1)

# ── ⑧ 错误结构:建议必填、不许带凭据 ─────────────────────────────
try:
    ER.错("E", "失败", "", http=422); 行 = False
except ValueError: 行 = True
ck("错误没写「可执行建议」就抛(§19.1 必填)", 行, 1)
try:
    ER.错("E", "上游拒了:api_key=看起来像凭据", "换一个连接", http=403); 行 = False
except ValueError: 行 = True
ck("**错误体里带凭据类词就抛**(错误信息是常见的泄露通道)", 行, 1)
ck("状态码语义齐(401/403/404/409/422/429/5xx)",
   {401, 403, 404, 409, 422, 429, 500} <= set(ER.状态语义), len(ER.状态语义))

# ── ⑨ 生成的契约文档必须是最新的 ──────────────────────────────────
# 有生成器不等于文档是最新的。**一份漂着的契约文档比没有更糟**:
# 读的人会照着它实现,而它描述的已经不是代码里那一套了。
# 判据里**剔掉版本那一行** —— 它带 git 短哈希和 dirty 标记,每次提交都会变,
# 拿它当判据的话这条检查会在每次提交后误报,而误报久了人就开始无视它。
import importlib.util as _iu
_g = os.path.join(ROOT, "tools", "gen_contract_doc.py")
_spec = _iu.spec_from_file_location("gen_contract_doc", _g)
_m = _iu.module_from_spec(_spec); _spec.loader.exec_module(_m)
_doc = os.path.join(ROOT, "docs", "契约.md")
if not os.path.exists(_doc):
    ck("契约文档已生成", False, 1, "跑 python3 tools/gen_contract_doc.py")
else:
    _旧 = open(_doc, encoding="utf-8").read()
    _m.写()                                     # 重新生成一份
    _新 = open(_doc, encoding="utf-8").read()
    def _去版本(t):
        return "\n".join(l for l in t.splitlines() if not l.startswith("> 代码 `"))
    ck("契约文档是最新的(它是生成的,改了契约要重跑生成器)",
       _去版本(_旧) == _去版本(_新), len(_新.splitlines()),
       "" if _去版本(_旧) == _去版本(_新) else "内容和现在的契约对不上 —— 跑 gen_contract_doc.py")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print(f"   · {x}")
sys.exit(1 if 挂 else 0)
