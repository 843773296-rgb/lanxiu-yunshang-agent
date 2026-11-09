#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全项目评测快照 · 调度检查(不调模型、不碰库、**不碰真锁**)

## 为什么要这条检查

2026-11-09 起跑前跑 `tools/impact.py`,它报的是:

> `tools/snapshot_all_evals.py` —— 覆盖它的检查:**一条都没有** —— 改坏了不会有任何地方报

而那个脚本是这一夜要连跑 10 小时的调度器,**全程没人看着**,产出是这两天唯一一次
全项目测量(11-08、11-09 两晚的夜跑都因为并行会话的门禁在锁里而整晚让开了)。
它坏掉的后果不是报错,是**明早拿到一份读不出来的报告**,而那时分不清是评测的问题
还是调度的问题。

## 这条检查管七件,每一件都对应脚本里一句「只写在注释里的要求」

  ① **剥后台变量必须在 `import nightly_eval` 之前** —— 它的 `评测环境()` 从
     `os.environ` 继承;import 之后再 pop 也能work,但那依赖「它每次调用时才读 environ」
     这个实现细节。**谁顺手重排一下 import,剥离就静默失效** ——
     而失效之后评测照跑、照出分,只是连上了管理后台,
     把并行会话 e2e 写进共享 PG 的测试术语读进了快照。
  ② **「剥掉 0 个」和「剥掉 N 个」必须印不同的话** —— 这两句话底下是两种不同的事实:
     一种是「这个 shell 本来就没有那三个变量」(不连后台成立,但成立的理由在 shell
     那边),一种是「剥离真的剥掉了几个」。2026-11-09 查实:我自己先被那个 0 骗过一次,
     把它读成了「整夜不连后台」的保证。**走真入口验**(真调那个函数、真改它读的那个
     字典),不在这儿重写一份判断。
  ③ **`历史分钟` 里点名的套不许囤积** —— 反向检查。一次改名会留下一条
     既不报错也不生效的登记,而估时、排序全靠这张表。
  ④ **日程按历史耗时从小到大** —— 时间不够时先跑完的应当是**成对的两遍**,
     而不是「几套慢的各一遍」(这一夜的产出是噪声底噪,噪声要两遍才读得出来)。
  ⑤ **`不跑` 的每一条都得写明理由**,而且点名的套必须真的存在 ——
     「没跑」和「跑了没过」在报告里不许混成一个字。
  ⑥ **「拿不到锁」那个退出码跟 `gate_lock.sh` 的约定对得上** ——
     这一条**真造一次抢不到锁去看它退几**,不 grep 注释里的那个数。
     跨文件写死的数两边各改一次就会脱节,而脱节之后调度会把「没抢到锁」
     记成「跑完了」(或反过来),两者的下一步动作相反。
  ⑦ **先找结果行、再看退出码** —— `gate_lock.sh` 把被包命令的退出码**原样传回**,
     而它拿不到锁时**也**退 3。于是「退 3」有两个来源:真的没抢到锁(一步都没跑)/
     被包的那段码自己退了 3(跑过了)。**它们在那个数上长得一模一样**,
     而结果行是唯一分得开的东西。顺序反了会把跑完的那一套记成「没抢到锁」并重试。

⚠️ 这里**不验**「今晚会不会真跑出分数」:那要调模型、要 10 小时。
   这条检查只回答「调度和接线对不对」—— **而那恰恰是会安静坏掉的那一半**。
"""
import ast
import datetime as dt
import importlib.util as _u
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_源路 = os.path.join(HERE, "snapshot_all_evals.py")

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏, n = [], 0


def ck(名, 得, 应):
    global n
    n += 1
    ok = (得 == 应)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}"
          + ("" if ok else f"\n       得到={得!r}\n       应={应!r}"))
    if not ok:
        坏.append(名)
    return ok


# 咬合 —— 改坏的是什么、该红的是哪一条。(可执行的在 tools/bite_specs.json,7 条,三关都验过)
咬合 = [
    ("剥后台变量改成只读不删(`pop` → `get`)—— 变量还留在 os.environ 里,"
     "工具服务进程照旧拿得到管理后台地址,评测会读到并行会话 e2e 写进共享 PG 的测试术语",
     "找得到那句剥变量"),
    ("让「剥掉 0 个」和「剥掉 3 个」印同一句话 —— 那个 0 就又会被读成"
     "「整夜不连后台」的保证(2026-11-09 我自己先被它骗过一次)",
     "不是同一句话"),
    ("把「拿不到锁」的退出码从 3 改成 4,和 `gate_lock.sh` 的约定脱节 —— "
     "真的没抢到锁会被记成「没跑成(调度)」,于是这一遍末尾不重试,那一套整夜没有数",
     "真造一次抢不到锁"),
    ("去掉 `errors=\"replace\"` —— 被包的脚本吐一个解不开的字节,"
     "整个调度当场抛 UnicodeDecodeError、这一夜全丢,而 traceback 看不出和锁有关",
     "给了 `errors=`"),
    ("让「没跑成(调度)」和「没抢到锁」共用一个字 —— 调度自己出的问题会被当成"
     "锁冲突无谓重试一遍,而明早的报告上读不出该去查哪一边",
     "两两不重复"),
    ("把「看退出码」挪到「捞结果行」之前 —— `gate_lock.sh` 把被包命令的退出码原样传回,"
     "而它拿不到锁时也退 3;顺序反了之后,一套**真跑完了**却恰好退 3 的评测"
     "会被记成「没抢到锁」,结果被丢掉、还要再跑一遍",
     "先**捞结果行"),
]

源 = io.open(_源路, encoding="utf-8").read()
树 = ast.parse(源, _源路)

sys.path.insert(0, HERE)
_规 = _u.spec_from_file_location("snapshot_all_evals", _源路)
M = _u.module_from_spec(_规)
_规.loader.exec_module(M)          # 顶层就剥变量 + import nightly_eval,都不调模型
N = M.N

print(f"全项目快照调度 · 检查({os.path.relpath(_源路, ROOT)})")
print()

# ── ① 剥变量在 import nightly_eval 之前 ──────────────────────────────
# 按**行号**比,不按「文件里谁先出现」的直觉 —— AST 给的是真的先后。
_剥行 = [x.lineno for x in ast.walk(树)
         if isinstance(x, ast.Assign)
         and any(isinstance(z, ast.Attribute) and z.attr == "pop"
                 and isinstance(z.value, ast.Attribute) and z.value.attr == "environ"
                 for z in ast.walk(x))]
_夜行 = [x.lineno for x in ast.walk(树) if isinstance(x, ast.Import)
         and any(a.name == "nightly_eval" for a in x.names)]
ck("① 找得到那句剥变量(不是被改没了)", len(_剥行) >= 1, True)
ck("① 找得到 import 夜跑那一行", len(_夜行) == 1, True)
if _剥行 and _夜行:
    ck("① 剥后台变量在 import 夜跑**之前**(之后再剥就只靠实现细节成立)",
       max(_剥行) < min(_夜行), True)

# ── ② 「剥掉 0 个」和「剥掉 N 个」印不同的话(走真入口) ──────────────
# ⚠️ **真改它读的那个字典、真调那个函数**,不在这儿照抄一份判断 ——
#    照抄的那份永远和它一致,于是这条判据什么都不验。
_原 = M.剥掉了
try:
    M.剥掉了 = {}
    空句 = M.不连后台这句话()
    M.剥掉了 = {"LANXIU_USAGE_URL": "x", "LANXIU_BRIDGE_PROJECT": "y", "LANXIU_USAGE_USER": "z"}
    满句 = M.不连后台这句话()
finally:
    M.剥掉了 = _原
ck("② 两种情形都说得出话(不是空字符串)", bool(空句.strip()) and bool(满句.strip()), True)
ck("② 「一个都没剥着」和「剥掉了 3 个」**不是同一句话**", 空句 != 满句, True)
ck("② 剥掉了几个那一句报得出个数(样本量落在话里)", "3" in 满句, True)

# ── ③ 历史分钟不许囤积找不到脚本的套名(反向检查) ────────────────────
def _脚本(名):
    return os.path.join(ROOT, N.别处的套.get(名) or os.path.join("agent", 名))


_囤 = [k for k in M.历史分钟 if not os.path.exists(_脚本(k))]
ck(f"③ `历史分钟` {len(M.历史分钟)} 条,点名的套都真的在那儿(囤积的登记既不报错也不生效)",
   _囤, [])
if _囤:
    print(f"       {Y}找不到脚本的:{'、'.join(_囤)}{D}")

# ── ④ 日程按历史耗时从小到大 ─────────────────────────────────────────
_程 = M.日程(dt.datetime.now() + dt.timedelta(hours=16))
ck(f"④ 日程排得出套(样本量 {len(_程)};空日程上「排序正确」自动成立)", len(_程) > 0, True)
_耗 = [M.历史分钟[f] for f, _ in _程]
ck("④ 按历史耗时**从小到大**(时间不够时先凑满成对的两遍,不是几套慢的各一遍)",
   _耗 == sorted(_耗), True)
ck("④ 日程里不含刻意不跑的那几套", [f for f, _ in _程 if f in M.不跑], [])

# ── ⑤ 不跑的每一条都有理由,而且点名的套真的存在 ──────────────────────
ck(f"⑤ `不跑` {len(M.不跑)} 条,每条都写明了为什么(「没跑」≠「跑了没过」)",
   [k for k, v in M.不跑.items() if not str(v).strip()], [])
ck("⑤ `不跑` 点名的套真的存在(拼错了等于这条登记静默失效)",
   [k for k in M.不跑 if not os.path.exists(_脚本(k))], [])

# ── ⑥ 「拿不到锁」的退出码:真造一次,不 grep 注释 ─────────────────────
# 调度里写死的那个数从 AST 里取 —— 这样两边**各改一次都会红**。
_函 = next((x for x in ast.walk(树) if isinstance(x, ast.FunctionDef)
            and x.name == "跑一套拿着锁"), None)
ck("⑥ 找得到那个包锁的函数", _函 is not None, True)
_码们 = []
_比较 = []
if _函:
    for x in ast.walk(_函):
        if (isinstance(x, ast.Compare) and isinstance(x.left, ast.Attribute)
                and x.left.attr == "returncode" and len(x.comparators) == 1
                and isinstance(x.comparators[0], ast.Constant)):
            _码们.append(x.comparators[0].value)
            _比较.append(x)
ck("⑥ 调度里按一个写死的退出码判「没抢到锁」(找得到那个数)", len(_码们) == 1, True)

if len(_码们) == 1:
    写死的 = _码们[0]
    # 照 `gate_lock.sh --自测` 第 ④ 条的造法:临时锁目录 + owner 写一个**活着的** pid
    # (拿本进程自己的 pid,不另起后台进程 —— 起了再 kill,shell 回收时会吐一行噪声)。
    # `LANXIU_LOCK_DIR` 指到临时目录,**真锁一下都不碰**。
    with tempfile.TemporaryDirectory() as _t:
        _d = os.path.join(_t, "lock")
        os.makedirs(_d)
        io.open(os.path.join(_d, "owner"), "w", encoding="utf-8").write(
            f"{os.getpid()} 这条检查自己占着 2026-01-01 00:00:00\n")
        _r = subprocess.run([os.path.join(HERE, "gate_lock.sh"), "--who", "快照检查⑥",
                             "echo", "不该跑到"],
                            capture_output=True, text=True, errors="replace",
                            env=dict(os.environ, LANXIU_LOCK_DIR=_d, LANXIU_LOCK_CAP="1"))
        ck(f"⑥ 真造一次抢不到锁:`gate_lock.sh` 退的码 == 调度里写的 {写死的}"
           f"(两边各改一次都会红)", _r.returncode, 写死的)
        ck("⑥ 它没把别人的锁删掉(等锁不是抢锁)", os.path.isdir(_d), True)

# ── ⑦ 先找结果行,再看退出码 ──────────────────────────────────────────
# 顺序反了会把**跑完的**那一套记成「没抢到锁」并重试,而两者下一步动作相反。
if _函 and _比较:
    _行行 = [x.lineno for x in ast.walk(_函) if isinstance(x, ast.For)
             and any(isinstance(z, ast.Attribute) and z.attr == "splitlines"
                     for z in ast.walk(x.iter))]
    ck("⑦ 找得到那个捞结果行的循环", len(_行行) == 1, True)
    if _行行:
        ck("⑦ **先**捞结果行、**再**看退出码(拿到结果就说明那套跑完了,退出码是几都不改变)",
           min(_行行) < min(x.lineno for x in _比较), True)
        # ⚠️ 顺序对了还不够:捞到那一行之后得**真的 return 出去**。
        # 只 `continue` / 只记个变量,顺序判据照旧绿,而结果一样会被退出码盖掉。
        _循 = [x for x in ast.walk(_函) if isinstance(x, ast.For)
               and any(isinstance(z, ast.Attribute) and z.attr == "splitlines"
                       for z in ast.walk(x.iter))]
        ck("⑦ 捞到结果行之后**真的 return 出去**(只记一下不返回,结果仍会被退出码盖掉)",
           any(isinstance(z, ast.Return) for x in _循 for z in ast.walk(x)), True)

# ── ⑨ 捕获子进程输出不许在非法字节上崩 ────────────────────────────────
# 2026-11-09 实测:`gate_lock.sh` 等锁超时吐的 stderr 曾经不是合法 UTF-8,
# 而默认 `text=True` 遇到非法字节**当场抛**。那一抛会让整夜全丢,
# 而 traceback 看不出和锁有关 —— **「解不开一个字节」和「这一夜白跑」
# 之间不该只隔一个默认参数**。根因修了,这条守的是「下一个被包的脚本」。
if _函:
    _跑 = [x for x in ast.walk(_函) if isinstance(x, ast.Call)
           and isinstance(x.func, ast.Attribute) and x.func.attr == "run"]
    ck("⑨ 找得到那处捕获被包命令输出的调用", len(_跑) == 1, True)
    for c in _跑:
        _kw = {k.arg: k.value for k in c.keywords}
        ck("⑨ 它按文本捕获(那就必须管非法字节)",
           isinstance(_kw.get("text"), ast.Constant) and _kw["text"].value is True, True)
        ck("⑨ 给了 `errors=`,而且不是 strict(一个解不开的字节会让这一夜全丢)",
           isinstance(_kw.get("errors"), ast.Constant)
           and _kw["errors"].value in ("replace", "backslashreplace", "ignore"), True)

# ── ⑧ 五种「没过」不许共用一个字 ──────────────────────────────────────
# 「没跑」「没抢到锁」「超时」「崩了」「判红」下一步动作各不相同,
# 共用一个字等于把它们在报告里压成同一件事。
def _结果字(路):
    t = ast.parse(io.open(路, encoding="utf-8").read(), 路)
    return [k.value.value for x in ast.walk(t) if isinstance(x, ast.Call)
            for k in x.keywords
            if k.arg == "结果" and isinstance(k.value, ast.Constant)]


_调度的 = _结果字(_源路)
_夜跑的 = _结果字(os.path.join(HERE, "nightly_eval.py"))
_全 = _调度的 + _夜跑的
ck(f"⑧ 调度 {len(_调度的)} 个 + 夜跑 {len(_夜跑的)} 个结果字,两两不重复"
   f"(「没抢到锁」和「崩了」压成一个字就读不出下一步该干什么)",
   len(set(_全)), len(_全))
ck("⑧ 调度自己那几个字都不是空的", [x for x in _调度的 if not str(x).strip()], [])

print()
print(f"  (验了 {n} 条)")
if n == 0:
    print(f"{R}❌ 一条都没验{D}")
    sys.exit(1)
if 坏:
    print(f"{R}❌ 快照调度 {len(坏)} 条不过:{'、'.join(坏)}{D}")
    sys.exit(1)
print(f"{G}✅ 快照调度:剥变量在 import 之前、「剥掉 0 个」说得清为什么、点名的套没囤积、"
      f"日程按耗时升序、拿不到锁的退出码真造过一次、先捞结果行再看退出码、"
      f"五种「没过」各有各的字(**这一夜 10 小时没人看着,调度坏了明早只剩一份读不出的报告**){D}")
