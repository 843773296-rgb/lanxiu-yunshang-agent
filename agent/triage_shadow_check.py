#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸四 影子运行:它**真的是影子**吗(不改行为 / 不经口暴露 / 轨别算得出来)。

    python3 agent/triage_shadow_check.py

真库只读(`mode=ro`),写只写到临时目录里的库副本。不调模型、不花钱,所以进得了门禁。

## 这条检查守的是什么

「影子运行」这四个字里有三句承诺,而三句都是**声明**:

    只观测不改行为   → 可是差评研判走 `sdk.run("task")`,**全包工具集里有写工具**
    人工独立判       → 可是只要台账经任何一个口露出去,处理人就可能先看见 AI 的建议
    两轨分开记       → 可是轨别要是一个手填的标签,填错了就安静地混进另一轨的一致率

> **一条没有被结构守住的「影子」承诺,和根本没有影子,在报告上长得一模一样。**

所以这里把三句话各变成判据。最要紧的是 ④ ——
**在库副本上真跑一次「装成会写库的模型」的影子跑**,断言真库一行没变。
而它自己也有一个空转风险:一个「隔离住了」的跑和一个「这一跑压根没写」,
在「真库指纹没变」上长得一模一样 —— 所以自测跑法**自己报告写成了没有**,这儿一并断言。

## ⚠️ 这条检查**不验**什么(写明边界,免得它被当成全保)

· **不验新量轨攒够了** —— 2026-10-20 量的速率是 8 天 3 条 ≈ 0.4 条/天,
  攒到业务定的 50 条还要约 95 天。所以「攒到哪了」是**库况**,报数不判红。
  这条检查管的是「**不足就报验不动,别报过**」。
· **不验回溯轨的数是独立证据** —— 它不是。回溯轨的题源就是闸二的三套题
  (2026-10-20 按包裹号对过:166 条一条不差)。⑧ 管的是**那句话必须印出来**。
· **不验每条跑之前那次重扫真的接住了懒加载的模块** —— 自测跑法不走 `跑一条`,
  所以它那一栏恒为 0;要看见它不为 0,只有真调模型那一跑。**这是记下来的盲区,不是账。**
  📌 而那一跑 2026-10-20 做了,**它不是多余的保险**:12 条真跑里第 2 条报
  「又改了 **3** 个模块」—— 第 1 条跑的时候 `跑一条` 懒加载进来的 `ops` / `sdk` 那几个,
  它们的 `DB` 还指着真库,是这次重扫把它们接住的。
  (MCP 工具服务是另外的进程,从 env 读 `LANXIU_DB`,不受这件事影响。)
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import api
import triage_shadow as S
import triage_sets as T

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0

# 咬合规格(`tools/bite_specs.json` 里登记的是会红的那一条)
咬合 = [
    # ⚠️ 右边那句必须**逐字**是这个脚本里某条判据的名字 ——
    # `tools/bite_check.py` 盯着这件事,它当场逮到过我一条写的是「一句不存在的检查名」。
    ("把 triage_shadow.核轨别 改成读 track 那个标签(而不是现算 human_at_run)",
     "人工档是空的却标成「回溯」→ 拒掉"),
    ("把子进程里 import ops 那一行挪到 指到副本() 之后(顺序反过来)",
     "子进程里先 import 再 指到副本(顺序反了它改 0 个模块)"),
    ("把 triage_shadow.默认跑法 改成自测跑法",
     "生产默认跑的是产线路,不是自测跑法"),
    ("把 报一轮 里新量不足下限那一支的 过=None 改成 过=True",
     "新量轨不足业务定的下限 → 状态写「验不动」且 过 为 None"),
    ("把 落账 的 INSERT 里 into_flow 那个 0 改成 1",
     "台账里 into_flow 全是 0(影子的定义就是不改行为)"),
    # 这一条攻击的是**判据自己的空转防线**:那个「会写库的模型」要是压根没写,
    # 「真库一个字节都没变」那条绿就什么也没证明。
    # ⚠️ 第一版的攻击点选错了(让自测跑法「自己报」写成了没有 → 写死成 1,判据照样绿)——
    # **一份自报的证词和一份写死的证词长得一模一样。** 所以现在判据自己翻副本。
    ("把自测跑法里那条 UPDATE 删掉(装成会写库的模型其实没写)",
     "那个「会写库的模型」写的东西,判据自己在副本里翻到了(不信它自报)"),
    ("把子进程跑完删副本那一步去掉(每跑一次留 85 MB)",
     "子进程自己开的副本跑完真的删了(85 MB,留着就是一天顶穿一次拷贝上限)"),
    ("把「遮不住的回溯行」里 track='回溯' 那个条件去掉(两轨混成一条)",
     "遮蔽的要求按轨分开:两轨都 masked=0 时,只有回溯那行被挑出来"),
    ("把建表语句里写死的表名改回 f-string(表归属那条检查就看不见这张表了)",
     "DDL 里的表名是写死的字面量,而且和 `表名` 这个常量一致"),
    ("把「交付成功的」口径放宽到也收「未通过」",
     "交付口径就是 sdk 那两种(「曾被打回过」不等于最终不合格)"),
    # 2026-10-21:并行会话当天真出过「切副本之后才 import 的写口写进了真库」。
    # 这条守的是**每一次真跑自带证据**那个机制,不是夹具上那次假跑。
    ("把 流程表 砍成只剩 rating(task / triage / 升级都不比了)",
     "流程表清单盖住了会被写的那几张(rating / task / triage / 升级 / 运行记录)"),
    ("把 待回填() 里 track='新量' 那个条件去掉(回溯轨那些行也被当成等着回填)",
     "人工后来判了新量那条 → 它进「等着回填的」(而回溯那条不进)"),
]


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else Rd + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


_源 = open(os.path.join(HERE, "triage_shadow.py"), encoding="utf-8").read()


def 位置(片):
    i = _源.find(片)
    return i if i >= 0 else 10 ** 9


# ── 文本判据只许看**代码**,不许看注释和字符串 ─────────────────────────────
#
# ⚠️⚠️ **第一版这三条全红了,而红的理由是它们匹配到了自己的说明。**
# 判据找 `api.DB`,而被扫的那段注释里正写着「**不是** `api.DB`」;
# 判据找 `指到副本`,而那个函数的 docstring 里正写着「永不调 `指到副本()`」。
# > **一行解释规则的注释,和一行违反规则的代码,在「这个串出现过」上长得一模一样。**
#
# 这个项目记过同一族的另一头(「被扫描文件里不许写出真实的密钥匹配串,要举例就描述它」)。
# 治法不是把注释删掉 —— 那等于为了判据而不许写清理由。是**让判据只看代码**。
#
# ⚠️ 而且只能**按函数**剥,不能整文件剥:「子进程里先 import 再指副本」那几条
# 必须看字符串(`_子码` 本身就是个字符串字面量),整文件去字符串会把它们一起弄瞎。
def 函数源(名, src=None):
    import ast
    src = src if src is not None else _源
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == 名:
            return ast.get_source_segment(src, node) or ""
    return ""


def 只留代码(s):
    """去掉注释和字符串字面量,只留下真正会执行的那部分文本。"""
    import io as _io
    import tokenize as _tk
    # ⚠️ **f-string 不是 STRING。** Python 3.12 起 tokenize 把它拆成
    # FSTRING_START / FSTRING_MIDDLE / FSTRING_END —— 只跳过 `STRING` 的话,
    # f-string 里的中文说明会**原样留在「代码」里**,于是上面那两条文本判据
    # 又回到了「匹配到自己的说明」。(这一条也是跑出来的,剥法自检红的就是它。)
    丢 = {_tk.COMMENT, _tk.STRING}
    for _名 in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(_tk, _名):
            丢.add(getattr(_tk, _名))
    出 = []
    try:
        for tok in _tk.generate_tokens(_io.StringIO(s).readline):
            if tok.type in 丢:
                continue
            出.append(tok.string)
    except Exception:                                              # noqa: BLE001
        return s
    # ⚠️ **拼的时候不加空格。** tokenize 把 `api.DB` 拆成 `api` / `.` / `DB` 三个词,
    # 用空格拼回去就成了 `api . DB` —— 于是找 `api.DB` 的那条判据**永远找不到**,
    # 而「它确实没出现」和「我把它拼散了」在那个 `not in` 上长得一模一样。
    # (这一条是跑出来的:第一版用空格拼,下面那条「剥法自检」当场红。)
    return "".join(出)


print("闸四 影子运行:它真的是影子吗 · 真库只读")

# ── ① 表在、而且登记进了「用到时才建」那张单子 ─────────────────────────────
print("\n① 表在,而且 CI 从零建库也会有它")
_ensure = open(os.path.join(ROOT, "tools", "ensure_tables.py"), encoding="utf-8").read()
ck("`rating_shadow` 登记进了 tools/ensure_tables.py",
   S.表名 in _ensure and "import rating_shadow" in _ensure,
   "**本地建过就一直在,CI 每次从零** —— 不登记就是一张只在我这台机器上存在的表")
# DDL 在 backend 层而口在 agent 层,这件事本身要被盯住:
# 挪回 agent/ 的话 `tools/table_origin_check.py` 跟不进去(它只看 backend/tools/knowledge),
# 于是这张表在它眼里变成「库里有一张表,谁也建不出它」
#
# ⚠️ DDL 里的表名**必须是写死的字面量**,不能是 f-string:
# `tools/table_origin_check.py` 按正则从源码里找 `CREATE TABLE ... <表名>`,
# 而 `{表名}` 里的 `{` 不是字母 —— 它看不见这张表叫什么,于是这张表在它眼里
# 变成「库里有一张表,谁也建不出它」(第一版真红在这儿)。
# 写死之后就有两处名字了,所以这条判据对的是**它们一致**。
_ddl0 = open(os.path.join(ROOT, "backend", "rating_shadow.py"), encoding="utf-8").read()
ck("DDL 里的表名是写死的字面量,而且和 `表名` 这个常量一致",
   f"CREATE TABLE IF NOT EXISTS {S.表名}(" in _ddl0,
   f"DDL 里找不到字面量 `{S.表名}` —— 要么参数化了(表归属那条检查就看不见它),"
   f"要么两处名字漂了")
ck("建表那一段在 backend 层(表归属那条检查只跟进 backend / tools / knowledge)",
   os.path.isfile(os.path.join(ROOT, "backend", "rating_shadow.py"))
   and "CREATE TABLE IF NOT EXISTS" not in _源,
   "DDL 要么不在 backend、要么在 agent 这边也有一份 —— 两份会漂")
_c = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
_有表 = bool(_c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (S.表名,)).fetchone())
ck(f"`{S.表名}` 在库里", _有表, "跑 python3 tools/ensure_tables.py")
if _有表:
    _列 = {r[1] for r in _c.execute(f"PRAGMA table_info({S.表名})")}
    # 两侧 + 判定 + 来路,缺哪一类都会让台账说不清一件事
    _要 = {"pkg_id", "track", "human_at_run", "ran_at", "ai_way", "ai_layer",
           "human_way", "human_filled_at", "verdict", "into_flow",
           "provider", "model", "code_ver", "masked", "got_material"}
    ck(f"台账的列齐了({len(_列)} 列)", _要 <= _列, f"缺 {sorted(_要 - _列)}")

# ── ② 🚫 红线:台账不许经任何 API / 工具暴露 ───────────────────────────────
print("\n② 红线:台账不经任何对外的口暴露(和 truth 表同一条)")
# 为什么这是红线:新量轨的全部价值在于人工那一侧**独立产生**。
# 处理人先看见了 AI 的建议,一致率就虚高 ——
# 而**「人工独立判的」和「人工照着 AI 抄的」在台账上长得一模一样**。
_扫 = []
for _根 in ("backend", "mcp", "agentsite"):
    for _d, _, _fs in os.walk(os.path.join(ROOT, _根)):
        if ".venv" in _d or "__pycache__" in _d:
            continue
        for _f in _fs:
            if _f.endswith((".py", ".js", ".html")):
                _扫.append(os.path.join(_d, _f))
#
# ⚠️ **只放过一个文件:`backend/rating_shadow.py`** —— 它是建表那一段,必须在 backend 层
# (理由见 ①)。放过它的同时顺手断言**它自己没有读口**,
# 不然这个豁免就成了一扇写着「这是建表的」的门。
放过 = {os.path.join("backend", "rating_shadow.py")}
_露 = []
for _p in _扫:
    rel = os.path.relpath(_p, ROOT)
    try:
        _t = open(_p, encoding="utf-8").read()
    except Exception:                                              # noqa: BLE001
        continue
    # 「rating_shadow.py」是**模块文件的路径**,不是这张表 —— 库指纹的登记表(backend/db_build.py,10-27)
    # 要逐个写出造数用到的模块路径,写出它不等于有了读口。只去掉「表名.py」这一种写法:
    # SQL 里的表名、`import 表名` 照样算提到(后者正是一条新读口的样子)
    if S.表名 in _t.replace(S.表名 + ".py", "") and rel not in 放过:
        _露.append(rel)
ck(f"后端 / 工具层 / 站点那 {len(_扫)} 个文件里,除了建表那一个都没提到这张表", not _露,
   f"{_露} —— 它一旦经口露出去,新量轨那一半的证据就没了,"
   f"**而一致率会变得更好看**。要在对比页上显示它,先找用户拍")
_ddl = open(os.path.join(ROOT, "backend", "rating_shadow.py"), encoding="utf-8").read()
# ⚠️ 这一条**不扫文本**,扫的是真正交给 sqlite 的那几条语句:
# 按 AST 找出所有 `execute(...)` 的第一个参数,每一条都必须是 CREATE。
# (文本扫法在这儿必红 —— 那个文件的注释里正写着「一个 SELECT 都不写」。)
import ast as _ast                                                 # noqa: E402
_语句 = []
for _nd in _ast.walk(_ast.parse(_ddl)):
    if isinstance(_nd, _ast.Call) and getattr(_nd.func, "attr", "") == "execute" and _nd.args:
        # ⚠️ 建表那几条是 **f-string**(表名现拼),AST 上是 JoinedStr 不是 Constant ——
        # 只认 Constant 的话三条全读成「不是字面量」,这条判据就红在一个假问题上。
        # `ast.unparse` 两种都还原得出原文。
        _a = _nd.args[0]
        _语句.append(_a.value if isinstance(_a, _ast.Constant) else _ast.unparse(_a))
ck(f"被放过的那个文件交给 sqlite 的 {len(_语句)} 条语句全是 CREATE(没有读口)",
   bool(_语句) and all("CREATE" in str(x).upper() for x in _语句),
   f"{[str(x)[:40] for x in _语句]} —— 这个豁免会成为一扇写着「这是建表的」的门")

# ── ③ 轨别是算出来的,不是一个标签 ─────────────────────────────────────────
print("\n③ 轨别算得出来(一个填错的标签不许混进另一轨)")
ck("影子跑那一刻人工档是空的 → 新量", S.核轨别(None) == "新量" and S.核轨别("") == "新量"
   and S.核轨别("  ") == "新量")
ck("影子跑那一刻人工档有值 → 回溯", S.核轨别("只回访") == "回溯"
   and S.核轨别("全额退款") == "回溯")

# ── 夹具:一份库副本,后面几条都在它上面跑 ─────────────────────────────────
_目录 = tempfile.mkdtemp(prefix="shadow-check-")
_副 = os.path.join(_目录, "lanxiu.db")
shutil.copy(api.DB, _副)
# 夹具自己造两条,**不靠库里恰好有** —— 库况一变这条检查就不该跟着飘
_cc = sqlite3.connect(_副)
# ⚠️ **先把副本里的台账清空。** 真库里已经有影子跑过的行了(2026-10-20 起 12 条),
# 拷过来之后夹具就不再是「恰好 2 行」—— 下面那几条断言会红在**库况**上,
# 而那不是任何人做错了事。
# > 一条「夹具坏了」的红和一条「代码坏了」的红,在退出码上长得一模一样。
# (这条是真数据一进来就当场红给我看的,原则本来就写在下一行注释里:夹具自己造。)
S.确保表(_cc)
_cc.execute(f"DELETE FROM {S.表名}")
_差评 = [r[0] for r in _cc.execute(
    "SELECT pkg_id FROM rating WHERE star<=3 ORDER BY pkg_id LIMIT 2")]
if len(_差评) == 2:
    _新, _回 = _差评
    # ⚠️ INSERT / UPDATE 都点名列。`tools/insert_shape_check.py` 10-20 当场逮过我一次:
    # **列数恰好相等而顺序错了是不报错的**,值会整体挪一格。
    _cc.execute("UPDATE rating SET handle_way=NULL WHERE pkg_id=?", (_新,))
    _cc.execute("UPDATE rating SET handle_way=? WHERE pkg_id=?", ("只回访", _回))
    _cc.commit()
_cc.close()


def 指纹(p, 表们=("rating", "ordr", "task")):
    """流程那几张表的内容指纹 —— 影子跑之后它必须一个字节都没变。"""
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    h = hashlib.md5()
    try:
        for t in 表们:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                             (t,)).fetchone():
                continue
            for r in c.execute(f"SELECT * FROM {t} ORDER BY 1"):
                h.update(repr(r).encode("utf-8"))
    finally:
        c.close()
    return h.hexdigest()


# ── ④ 最要紧的一条:影子跑真的不改流程 ────────────────────────────────────
print("\n④ 影子跑不改流程:在副本上真跑一次「装成会写库的模型」")
if len(_差评) != 2:
    ck("库里有差评样本可做夹具(没有就不叫通过)", False, f"只挑到 {len(_差评)} 条")
else:
    import triage_pipeline_eval as PE
    _me = PE.身份(_副) or dict(no="60000001", name="夹具", role="售后", shop="")
    # 副本开在**判据自己的目录**里 —— 跑完要翻进去看,所以由这边负责删
    # (不给这个参数时子进程自己开、自己删;副本 85 MB,留着就是一天顶穿一次拷贝上限)
    _副本目录 = tempfile.mkdtemp(prefix="shadow-check-副本-")
    _标 = "影子判据夹具写的一行"
    _前 = 指纹(_副)
    try:
        _落, _说 = S.影子跑一批([_新, _回], _me, "shadow/判据夹具", dbp=_副,
                               跑法="自测写一行",
                               额外=dict(假档="只回访", 副本目录=_副本目录, 自测标记=_标))
    except Exception as e:                                         # noqa: BLE001
        _落, _说 = 0, dict(挂了=f"{type(e).__name__}: {e}")
    _后 = 指纹(_副)
    ck("两条都落了账", _落 == 2, f"落了 {_落} 条 · {json.dumps(_说, ensure_ascii=False)[:400]}")
    # ⚠️⚠️ **空转防线,而且不信子进程的自报。**
    # 第一版是让自测跑法**自己报**「写成了没有」,而那条咬合当场证明它逮不到:
    # 把那一栏写死成 1,判据照样全绿 —— **一份自报的证词,和一份写死的证词,长得一模一样。**
    # 现在改成**判据自己翻进那份副本去看**:写有没有落在副本里,由这边独立核。
    # 少了这一条,下面那条「真库没变」在「这一跑压根没写」的情况下**照样绿**,
    # 而那什么也没证明。
    _副本库 = os.path.join(_副本目录, "lanxiu.db")
    _落在副本里 = 0
    if os.path.exists(_副本库):
        _c9 = sqlite3.connect(f"file:{_副本库}?mode=ro", uri=True)
        _落在副本里 = _c9.execute(
            "SELECT COUNT(*) FROM rating WHERE handle_note=?", (_标,)).fetchone()[0]
        _c9.close()
    ck("🔺 那个「会写库的模型」写的东西,判据自己在副本里翻到了(不信它自报)",
       _落在副本里 == 2,
       f"副本里只找到 {_落在副本里} 条 —— 一个「隔离住了」的跑和一个"
       f"「这一跑压根没写」,在「真库指纹没变」上长得一模一样")
    # ── 这条防线现在归 `影子跑一批` 自己带(2026-10-21 补)──────────────
    # ⚠️ 补它的理由是并行会话当天的一次**真事故**:他那边「研判模块是切到副本之后
    # 才 import 的,`save_triage` 写进了真库」。而我当时只在**夹具副本**上用假跑法
    # 验过「真库没变」—— **真调模型那条路跑完,没人对真库盖过前后指纹**。
    # > 一次「隔离住了」的真跑,和一次「悄悄写进真库」的真跑,
    # > **在台账和日志上长得一模一样** —— 落账照落、模型照答。
    # 所以现在每一次跑自己带证据,这儿只验那个机制在、而且报得出来。
    ck("影子跑自己带「流程表没动」的证据(不靠门禁在夹具上替它验)",
       "流程表没动" in (_说 or {}) and (_说["流程表没动"].get("前")
                                        == _说["流程表没动"].get("后")),
       f"{(_说 or {}).get('流程表没动')} —— 每一次真跑都该自己盖前后指纹")
    ck("流程表清单盖住了会被写的那几张(rating / task / triage / 升级 / 运行记录)",
       {"rating", "task", "triage", "triage_run", "escalation"} <= set(S.流程表),
       f"{S.流程表}")
    ck("指纹比的是**内容**不是行数(改一行 handle_way,行数一个不变)",
       "repr(r)" in open(os.path.join(HERE, "triage_shadow.py"),
                         encoding="utf-8").read().split("def 流程指纹")[1][:900],
       "只数行数的话,模型把一行的处置从空改成「只回访」比不出来")
    ck("🔺 真库(这里是夹具那份)流程表一个字节都没变", _前 == _后,
       f"{_前[:8]} → {_后[:8]} —— 模型写的东西落到真库上了,那就不叫影子")
    ck("子进程确实把工具层指到了副本(改了 ≥1 个模块)",
       ((_说.get("meta") or {}).get("改了几个模块") or 0) >= 1,
       "改了 0 个模块 = 这一批的材料全是从真库取的,**而台账上看不出来**")
    _m = (_说.get("meta") or {})
    ck("子进程里 api 读的是副本,不是真库",
       bool(_m.get("api读的是")) and os.path.realpath(_m["api读的是"]) != os.path.realpath(api.DB),
       f"{_m.get('api读的是')}")
    # 落账落在哪:台账行必须在**夹具那份库**里,不是在子进程的副本里(跑完就没了)
    _c3 = sqlite3.connect(f"file:{_副}?mode=ro", uri=True)
    _行们 = [dict(zip([d[0] for d in _c3.execute(f"SELECT * FROM {S.表名} LIMIT 0").description],
                      r)) for r in _c3.execute(f"SELECT * FROM {S.表名}")]
    _c3.close()
    ck("台账行落在父进程那份库里(不是子进程的副本 —— 那份跑完就没了)",
       len(_行们) == 2, f"{len(_行们)} 行")
    ck("两条各归各轨(一条新量、一条回溯),而且是算出来的",
       sorted(x["track"] for x in _行们) == ["回溯", "新量"],
       f"{[(x['pkg_id'], x['track'], x['human_at_run']) for x in _行们]}")
    ck("台账里 into_flow 全是 0(影子的定义就是不改行为)",
       all(x["into_flow"] == 0 for x in _行们),
       f"{[x['into_flow'] for x in _行们]}")
    # ── 遮蔽:**两轨的要求是反的** ──
    # 真跑第一条时撞到的:工具层打印「遮了 4 处」,而台账记 masked=0 ——
    # 两个数量的不是同一件事,而**这条新量题本来就没有答案可遮**(人工还没判它)。
    # 于是新量轨有一个结构性的好处:**它不可能开卷,因为答案还不存在**。
    # 紧接着就是这个项目的母题:
    # > 「新量轨本来没有答案可遮」和「回溯轨的遮蔽失效了」
    # > **在 masked=0 这一个数上长得一模一样** —— 分开它们的只有 track 这一列。
    # ⚠️ 这一条**不能用文本判据**:第一版写的是「源码里有 `def 遮不住的回溯行`」,
    # 而咬合把那个函数改个名之后,`报一轮` 直接 NameError —— 红的是**崩**,不是这一条。
    # > 一条「判据逮到了」的红和一条「代码崩了」的红,在退出码上长得一模一样。
    # 所以改成行为判据:把**两轨各一行**的 masked 都压成 0,只有回溯那行该被挑出来。
    _c8 = sqlite3.connect(_副)
    _c8.execute(f"UPDATE {S.表名} SET masked=0")
    _c8.commit()
    _c8.close()
    _遮不住 = S.遮不住的回溯行(_副)
    ck("遮蔽的要求按轨分开:两轨都 masked=0 时,只有回溯那行被挑出来",
       _遮不住 == [_回],
       f"挑出来的是 {_遮不住},应该只有回溯那条({_回})—— "
       f"新量轨的 masked 本来就是 0(人工还没判,**答案还不存在**),"
       f"而「新量轨没答案可遮」和「回溯轨的遮蔽失效了」在这个数上长得一模一样")
    ck("来路盖上了(供应商 / 模型 / 代码版本)",
       all(x["provider"] and x["model"] and x["code_ver"] for x in _行们),
       "一份分不清供应商的历史不是历史,是一堆数")
    # ── ⑤ 轨别传错 → 落账当场拒 ──
    print("\n⑤ 轨别传错,落账当场拒(不许手填一个标签)")
    try:
        S.落账([dict(batch="x", pkg_id=_新, human_at_run=None, track="回溯",
                     ran_at="2026-01-01T00:00:00")], _副)
        _拒 = False
    except RuntimeError as e:
        _拒 = "轨别不许手填" in str(e)
    ck("人工档是空的却标成「回溯」→ 拒掉", _拒,
       "一个填错的标签会安静地混进另一轨的一致率,**而那个百分比看起来很正常**")
    # ── ⑥ 回填 + 判定 ──
    print("\n⑥ 回填人工那一侧,判定只用一份判法")
    _回填 = S.回填人工(_副, 现在="2026-10-20T22:00:00")
    ck("回溯轨那条当场判定(人工侧在影子跑那一刻就有)", _回填["判定了"] >= 1,
       json.dumps(_回填, ensure_ascii=False))
    ck("新量轨那条还没判(人工还没判它)—— 报得出来是哪几条",
       _新 in _回填["还没判的"], json.dumps(_回填, ensure_ascii=False))
    # 判法必须是 triage_sets 那一份,不是这儿重实现一份
    _判 = S.判这一行(dict(pkg_id="P-甲", ai_way="只回访", ai_text=""), "全额退款")
    ck("判法真调 triage_sets.判一题(人工全额 / AI 只回访 → 跨档漏报)",
       _判.get("跨档漏报") is True, f"{_判}")
    _判2 = S.判这一行(dict(pkg_id="P-乙", ai_way="只回访", ai_text=""), "只回访")
    ck("判对了档也认得出来(人工只回访 / AI 只回访)",
       _判2.get("判对了档") is True and not _判2.get("跨档漏报"), f"{_判2}")
    # ── ⑦ 报一轮:不足下限报「验不动」,不报「过」 ──
    print("\n⑦ 报一轮:不足下限报「验不动」,不报「过」")
    _报 = S.报一轮(_副)
    ck("新量轨不足业务定的下限 → 状态写「验不动」且 过 为 None",
       "验不动" in str(_报["新量"].get("状态")) and _报["新量"].get("过") is None,
       json.dumps(_报.get("新量"), ensure_ascii=False))
    ck(f"下限就是业务 2026-10-10 定的 {S.新量下限} 条", S.新量下限 == 50,
       f"现在是 {S.新量下限} —— 这个数是业务的,不是开发的")
    ck("回溯轨那一行带着「和闸二三套题重叠」+ 证据力那句话",
       "和闸二三套题重叠" in _报["回溯"] and "不是独立证据" in str(_报["回溯"].get("⚠️ 证据力")),
       json.dumps(_报.get("回溯"), ensure_ascii=False)[:300])
    # ── 交付口径:没交出答复的那一轮不进分母,但要单独报 ──
    # 2026-10-20 首批 12 条里有 1 条**建议读不出**,而它正好就是交付检查「未通过」那一条
    # (花费还是别人的四五倍)。
    # > **一条连交付检查都没过的草稿,和一条正经判断,在一致率里长得一模一样。**
    ck("交付口径就是 sdk 那两种(「曾被打回过」不等于最终不合格)",
       S.交付成功的 == ("通过", "修正后通过"),
       f"{S.交付成功的} —— 用户 2026-10-04 拍「按最终交付判」")
    ck("交出来了吗:通过 / 修正后通过算成功,未通过 / 空不算",
       S.交出来了吗(dict(delivered="通过")) and S.交出来了吗(dict(delivered="修正后通过"))
       and not S.交出来了吗(dict(delivered="未通过")) and not S.交出来了吗({}))
    ck("两轨都把「没交付成功的」和「读不出建议的」单独报出来",
       "没交付成功的" in _报["新量"] and "读不出建议的" in _报["新量"]
       and "没交付成功的" in _报["回溯"],
       "不单独报的话,「这批里有几条没交出来」也跟着看不见了")
    # ── 「等着回填的」:一步没跑,和「还没人处置」长得一模一样 ──
    # 回填是要有人去跑的一步(`--回填`)。把两者混成一个「判定过的 0」,
    # 这道闸会显得永远攒不动,**而真相可能是数据早就在了,只是没人跑那一步。**
    _c7 = sqlite3.connect(_副)
    _c7.execute("UPDATE rating SET handle_way=? WHERE pkg_id=?", ("只回访", _新))
    # ⚠️⚠️ **夹具必须造出一条「该被 track 挡掉的回溯行」**,否则这一条是空转的绿:
    # ⑥ 的回填已经给回溯那行填上了 `human_way`,于是「没回填」这个条件自己就把它排除了,
    # **去掉 `track='新量'` 也看不出区别** —— 咬合当场证明了这件事(改坏了却没红)。
    # 把它的 human_way 抹掉,它才成为一个「两个条件都符合、只能靠 track 挡」的候选。
    # > 一条「被正确的条件挡住了」和一条「被另一个条件顺手挡住了」,
    # > **在结果列表上长得一模一样。**
    _c7.execute(f"UPDATE {S.表名} SET human_way=NULL WHERE track='回溯'")
    _c7.commit()
    _c7.close()
    _待 = S.待回填(_副)
    ck("人工后来判了新量那条 → 它进「等着回填的」(而回溯那条不进)",
       _待 == [_新],
       f"{_待} —— 应该只有新量那条({_新});「有人处置了而台账没回填」和"
       f"「还没人处置」在台账上长得一模一样(两者 verdict 都是空)")
    _报2 = S.报一轮(_副)
    ck("库况里把「等着回填的」和「要不要跑回填」都报出来",
       _报2["库况"].get("等着回填的") == [_新]
       and "要 ——" in str(_报2["库况"].get("要不要跑回填")),
       json.dumps(_报2.get("库况"), ensure_ascii=False)[:300])
    ck("库况里报了「还差多少条」和那个速率(别让人把它读成「做得慢」)",
       "新量还差" in _报["库况"] and "0.4 条/天" in _报["库况"]["一句话"],
       json.dumps(_报.get("库况"), ensure_ascii=False)[:300])

# ── ⑧ 「一条也没记」和「记了而确实是 0」分得开 ────────────────────────────
print("\n⑧ 「一条也没记」和「记了而确实是 0」分得开(A-119 那次的教训)")
_空目录 = tempfile.mkdtemp(prefix="shadow-empty-")
_空 = os.path.join(_空目录, "lanxiu.db")
shutil.copy(api.DB, _空)
_c4 = sqlite3.connect(_空)
S.确保表(_c4)
_c4.execute(f"DELETE FROM {S.表名}")
_c4.commit()
_c4.close()
_空报 = S.报一轮(_空)
ck("一条都没有时,报的是「口还没跑过」,不是「0 条漏报」",
   S.没跑过的话术 in str(_空报["新量"].get("状态"))
   and "不是 0 条漏报" in S.没跑过的话术,
   json.dumps(_空报.get("新量"), ensure_ascii=False))
ck("两轨都报「最近跑于」(没跑过就是 None)",
   "最近跑于" in _空报["新量"] and "最近跑于" in _空报["回溯"])

# ── ⑨ 结构:顺序 / 默认跑法 / 解释器 / 落账写真库 ─────────────────────────
print("\n⑨ 结构(这几条防的是「它看起来在隔离,其实没有」)")
ck("子进程里先 import 再 指到副本(顺序反了它改 0 个模块)",
   位置("import ops") < 位置("改了 = protocol.指到副本()")
   and 位置("import rating_triage as RT") < 位置("改了 = protocol.指到副本()"),
   "`指到副本()` 改的是**已加载模块**的 DB —— import 之前调,它改 0 个、不报错,"
   "然后产线路读真库")
ck("子进程 0 个模块就拒跑", "改了 <= 0" in _源 and "sys.exit(3)" in _源,
   "改了 0 个 = 读真库,而台账上看不出来")
ck("每条跑之前再扫一遍(懒加载的 ops / sdk 要接住)",
   "又改 = protocol.指到副本()" in _源)
#
# ⚠️⚠️ **这一条原来是文本判据,而咬合当场证明它不够**:攻击把 `if 自己开的:`
# 换成 `if False:`,**rmtree 那一行还在**,于是「这行字存在」照样成立。
# > **「代码里有清理」和「清理会发生」是两件事** —— 而文本只看得见前者。
# (同族:这个项目记过的「打印 ❌ 和拦截是两件事」。)
# 所以改成**行为判据**:真跑一次不给副本目录的影子跑,再数临时目录里有没有多出一份。
import glob as _glob                                              # noqa: E402
_临时 = os.path.join(tempfile.gettempdir(), "shadow-*")
_跑前 = set(_glob.glob(_临时))
if len(_差评) == 2:
    try:
        S.影子跑一批([_新], _me, "shadow/清理自测", dbp=_副,
                     跑法="自测写一行", 额外=dict(假档="只回访"))
    except Exception:                                              # noqa: BLE001
        pass
_多出来 = sorted(set(_glob.glob(_临时)) - _跑前)
ck("子进程自己开的副本跑完真的删了(85 MB,留着就是一天顶穿一次拷贝上限)",
   not _多出来,
   f"{_多出来} 还在 —— 十几次自测就攒了 1.2 GB,而门禁每跑一次攒一份;"
   f"**一个「跑完清理了」的脚本和一个每次留 85 MB 的,在它自己的输出上长得一模一样**")
ck("生产默认跑的是产线路,不是自测跑法", S.默认跑法 == "产线路",
   f"现在是 {S.默认跑法!r} —— 自测跑法不调模型,它当默认就是一台账假数据")
ck("跑法是白名单(判据造的那种跑法不许偷偷进生产)",
   isinstance(S.跑法们, tuple) and "自测写一行" in S.跑法们 and "产线路" in S.跑法们)
ck("子进程用 agentsite/.venv 那个 python(sdk 只装在那儿)",
   S.解释器().endswith("python") and ".venv" in S.解释器(),
   f"{S.解释器()} —— 用外层 python 会在 `import sdk` 那一行挂,"
   f"而那句错看起来像「影子跑挂了」")
ck("落账用 import 时定下的真库路径,不现读 api.DB",
   "DBP = os.path.join(ROOT" in _源 and "api.DB" not in 只留代码(函数源("落账")),
   "现读 api.DB 的话,一次影子跑之后台账就写进副本了 —— 跑完就没了,**而它不报错**")
ck("父进程自己不调 指到副本(那是子进程的事)",
   "指到副本" in _源 and "指到副本" not in 只留代码(函数源("影子跑一批")),
   "父进程一指副本,它后面写的每一行台账都写进了副本")
# 上面两条用的是「只留代码」那一层。它自己也要被验一下 ——
# 一个**永远返回空串**的剥法会让那两条永远绿,而「剥干净了」和「剥成空的」
# 在那两个 not in 上长得一模一样
ck("「只留代码」真的在剥而不是剥成了空的",
   "sqlite3.connect" in 只留代码(函数源("落账"))
   and "轨别不许手填" not in 只留代码(函数源("落账")),
   "剥法失效:要么没剥掉字符串,要么把代码一起剥没了")

# ── ⑩ 库况(报数,不判红)────────────────────────────────────────────────
print("\n⑩ 库况(报数,不判红 —— 攒够要靠时间,不是靠谁更努力)")
_真报 = S.报一轮()
if _真报.get("有表"):
    _新量 = _真报.get("新量", {})
    _况 = _真报.get("库况", {})
    print(f"  {Y}·{D} 新量轨 {_新量.get('条数', 0)} 条(判定过 {_新量.get('判定过的', 0)})"
          f" · 还差 {_况.get('新量还差')} 条 · 最近跑于 {_新量.get('最近跑于')}")
    print(f"  {Y}·{D} 回溯轨 {_真报.get('回溯', {}).get('条数', 0)} 条"
          f"(和闸二三套题重叠 {_真报.get('回溯', {}).get('和闸二三套题重叠')})")
    print(f"  {Y}·{D} 库里还没影子跑过的未处置差评:"
          f"{_况.get('库里还没影子跑过的未处置差评')} 条")
    # ⚠️ **加进报告字典却不印出来,等于没报。**
    # 这一栏是整个第 ⑩ 节里唯一「有人能当场动手」的那个数:
    # 别的要等时间,这个跑一条命令就计入了。
    _待印 = _况.get("等着回填的") or []
    print(f"  {Y}·{D} 等着回填的:{len(_待印)} 条 —— {_况.get('要不要跑回填')}")
    print(f"  {Y}⚠️ {_况.get('一句话')}{D}")

shutil.rmtree(_目录, ignore_errors=True)
shutil.rmtree(_空目录, ignore_errors=True)
shutil.rmtree(globals().get("_副本目录") or _空目录, ignore_errors=True)
_c.close()

print()
if bad:
    print(f"{Rd}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    for b in bad:
        print(f"    {Rd}❌{D} {b}")
    sys.exit(1)
print(f"{G}✅ 影子运行的三句承诺都被结构守着(验了 {n} 条){D}")
print(f"    {Y}⚠️ 它**不验**新量攒够了(那要约 95 天)、"
      f"也**不验**回溯轨的数是独立证据(它不是){D}")
