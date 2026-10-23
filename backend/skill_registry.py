# -*- coding: utf-8 -*-
"""Skill 管理:状态、配置、依赖就绪、使用 —— 后台完整配置页的底层(用户 2026-10-23 拍,intent/skill-admin.md)。

## 要解决的事

装了 243 个、默认开 7 个、样本里只记到 4 种在用 —— 而这三个数哪里都看不到,「装了」常被当成「能用」。
这里给每个 Skill 一行状态和配置,**执行闸读的就是这个状态**(agentsite/guards.py 的 Skill 那一支):

    已安装待审查 → 待适配 → 试运行 → 已发布 → 已停用(可回到待适配)

只有「试运行 / 已发布」放行。没登记过的按来源取默认:**自有的 = 已发布,第三方 = 已安装待审查** ——
所以这一版上线那一刻,谁能调、谁被拦,和原来一模一样(原来是写死的「只放自有清单」)。

## 三条硬规矩(不靠页面自觉,写口里拦)

  · **只有总部运营能改**,身份从登录会话来;每次改动连同理由记进 skill_cfg_log,只增不改
  · **依赖没就绪的不许进「试运行 / 已发布」** —— 依赖是**现算**的(下面 `依赖()`),不是手填的勾
  · 状态只能沿上面那条线走,不许跳(比如待审查直接到已发布)

## 依赖就绪怎么算(现算,不读人填的)

读 SKILL.md(和 references/ 里的文本),找三样:
  · 它要跑的**脚本**(`scripts/xxx.py` 这类相对路径)—— 在不在这个技能目录里
  · 它要的**外部能力**(accio-mcp-cli、浏览器自动化、外部平台登录)—— 本机没有,一律算缺
  · 它点名的**本系统工具**(反引号里的工具名)—— 在不在 backend/domains.py 的归属里
只报事实,不替人判「这个能不能改造」—— 那是「分类」那一栏,人填。
"""
import json
import os
import re
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DB = os.path.join(HERE, "lanxiu.db")
技能目录 = os.path.join(ROOT, "agentsite", ".claude", "skills")

状态们 = ("已安装待审查", "待适配", "试运行", "已发布", "已停用")
放行的状态 = ("试运行", "已发布")
# 能走的边。**不许跳**:待审查不能直接发布 —— 没适配过的第三方技能一步到位放进生产,就是核查 4.4 说的那件事
可走 = {
    "已安装待审查": ("待适配", "已停用"),
    "待适配": ("试运行", "已停用"),
    "试运行": ("已发布", "待适配", "已停用"),
    "已发布": ("已停用", "待适配"),
    "已停用": ("待适配",),
}
分类们 = ("", "可借鉴方法", "可适配", "缺依赖", "不适用")
可编辑角色 = ("总部运营",)
# 表单里人填的那几栏(核查 6.2 的配置区域)
文字栏 = ("负责人", "适用岗位", "触发条件", "不适用问法", "输出契约", "操作边界", "失败处置", "测试与发布", "分类", "分类理由")

外部能力词 = {
    "accio-mcp-cli": "Alibaba / Accio 的命令行工具",
    "browser-rpa": "浏览器自动化(RPA)",
    "ask_user(": "Accio 的人机表单接口",
    "淘宝": "淘宝店铺登录", "天猫": "天猫店铺登录", "Shopify": "Shopify 店铺", "shopify": "Shopify 店铺",
    "1688": "1688 账号",
    "Accio": "Accio 平台", "accio": "Accio 平台", "国际站": "阿里巴巴国际站账号",
}


def _ours():
    # 按路径载入,不往 sys.path 里插 agentsite —— 插在前面会让同名模块顶掉调用方自己的(后台进程和运维平台都会 import 这个文件)
    import importlib.util as _u
    sp = _u.spec_from_file_location("skills_own", os.path.join(ROOT, "agentsite", "skills_own.py"))
    m = _u.module_from_spec(sp); sp.loader.exec_module(m)
    return set(m.OURS)


def _now():
    import ops
    return ops.now().strftime("%Y-%m-%d %H:%M:%S")


def _连(db=None):
    c = sqlite3.connect(db or DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS skill_cfg(
        name TEXT PRIMARY KEY, status TEXT NOT NULL, owner TEXT, roles TEXT, trigger_when TEXT,
        trigger_not TEXT, output_contract TEXT, boundary TEXT, on_failure TEXT, release_notes TEXT,
        category TEXT, category_why TEXT, version INTEGER NOT NULL DEFAULT 1,
        updated TEXT, updated_by TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS skill_cfg_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, what TEXT NOT NULL,
        before TEXT, after TEXT, why TEXT, by_no TEXT, by_name TEXT, at TEXT)""")


_栏到列 = {"负责人": "owner", "适用岗位": "roles", "触发条件": "trigger_when", "不适用问法": "trigger_not",
          "输出契约": "output_contract", "操作边界": "boundary", "失败处置": "on_failure",
          "测试与发布": "release_notes", "分类": "category", "分类理由": "category_why"}


# ── 读 ──────────────────────────────────────────────────────────────
def 装了哪些():
    if not os.path.isdir(技能目录):
        return []
    return sorted(x for x in os.listdir(技能目录) if os.path.isfile(os.path.join(技能目录, x, "SKILL.md")))


def 默认状态(name):
    return "已发布" if name in _ours() else "已安装待审查"


def _行们(db=None):
    try:
        with closing(_连(db)) as c:
            确保表(c)
            return {r["name"]: dict(r) for r in c.execute("SELECT * FROM skill_cfg")}
    except sqlite3.Error:
        return {}


def 状态(name, db=None):
    """→ 这个技能现在的状态。**库读不到时退回默认**(自有放行、第三方拦)—— 和原来写死清单的行为一样,
    不会因为库坏了就把第三方放进来(fail closed)。"""
    try:
        with closing(sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True, timeout=5)) as c:
            r = c.execute("SELECT status FROM skill_cfg WHERE name=?", (name,)).fetchone()
            if r and r[0] in 状态们:
                return r[0]
    except sqlite3.Error:
        pass
    return 默认状态(name)


def 放行吗(name, db=None):
    return 状态(name, db) in 放行的状态


def _说明(name):
    p = os.path.join(技能目录, name, "SKILL.md")
    try:
        t = open(p, encoding="utf-8").read()
    except OSError:
        return "", ""
    m = re.search(r"^description:\s*(.+)$", t, re.M)
    return t, (m.group(1).strip().strip('"\'') if m else "")


def 依赖(name):
    """→ dict(就绪, 缺的脚本, 外部能力, 本系统工具, 认不出的工具)。**现算**,每次读 SKILL.md。"""
    import domains
    d = os.path.join(技能目录, name)
    正文, _ = _说明(name)
    参考 = ""
    rd = os.path.join(d, "references")
    if os.path.isdir(rd):
        for f in sorted(os.listdir(rd)):
            try:
                参考 += open(os.path.join(rd, f), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                pass
    全文 = 正文 + "\n" + 参考
    脚本 = sorted(set(re.findall(r"(?<![\w/.])((?:\.\./[\w-]+/)?scripts/[\w./-]+\.(?:py|sh|js|mjs))", 全文)))
    缺脚本 = [s for s in 脚本 if not os.path.isfile(os.path.normpath(os.path.join(d, s)))]
    外部 = sorted({v for k, v in 外部能力词.items() if k in 全文})
    点名 = set(re.findall(r"`(?:mcp__\w+?__)?([a-z][a-z0-9_]{2,})`", 正文))
    本系统 = sorted(t for t in 点名 if t in domains.归属)
    return dict(就绪=not 缺脚本 and not 外部, 缺的脚本=缺脚本, 外部能力=外部,
                本系统工具=本系统, 引用的脚本=脚本)


def 使用(name=None):
    """最近调用 —— 读 agentsite/evals/skill_usage.jsonl(只留最近 200 条,见 skill_stats)。"""
    p = os.path.join(ROOT, "agentsite", "evals", "skill_usage.jsonl")
    次, 末, 拦 = {}, {}, {}
    try:
        for l in open(p, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            全 = r.get("skills") or ([r["skill"]] if r.get("skill") else [])
            for s in 全:
                if s in (r.get("被拦") or []):
                    拦[s] = 拦.get(s, 0) + 1
                else:
                    次[s] = 次.get(s, 0) + 1
                    末[s] = r.get("ts")
    except (OSError, ValueError):
        pass
    if name:
        return dict(次数=次.get(name, 0), 最近=末.get(name), 被拦=拦.get(name, 0))
    return 次, 末, 拦


def 清单(db=None):
    行 = _行们(db)
    自 = _ours()
    次, 末, 拦 = 使用()
    out = []
    for n in 装了哪些():
        r = 行.get(n) or {}
        _, 述 = _说明(n)
        依 = 依赖(n)
        out.append(dict(
            名称=n, 来源="自有" if n in 自 else "第三方", 状态=r.get("status") or 默认状态(n),
            登记过=bool(r), 说明=述[:160], 负责人=r.get("owner"), 适用岗位=r.get("roles"),
            分类=r.get("category") or "", 依赖就绪=依["就绪"],
            依赖缺口=(依["缺的脚本"][:3] + 依["外部能力"][:3]),
            最近调用=末.get(n), 调用次数=次.get(n, 0), 被拦次数=拦.get(n, 0),
            版本=r.get("version") or 0, 更新=r.get("updated"), 更新人=r.get("updated_by")))
    return out


def 详情(name, db=None):
    if name not in 装了哪些():
        return {"error": f"没有装这个技能:{name}"}
    r = _行们(db).get(name) or {}
    正文, 述 = _说明(name)
    with closing(_连(db)) as c:
        确保表(c)
        日志 = [dict(x) for x in c.execute(
            "SELECT what,before,after,why,by_name,at FROM skill_cfg_log WHERE name=? ORDER BY id DESC LIMIT 50", (name,))]
    st = r.get("status") or 默认状态(name)
    return dict(
        名称=name, 来源="自有" if name in _ours() else "第三方", 状态=st, 登记过=bool(r),
        可走到=list(可走.get(st, ())), 说明=述, 正文=正文,
        配置={k: (r.get(v) or "") for k, v in _栏到列.items()}, 版本=r.get("version") or 0,
        依赖=依赖(name), 使用=使用(name), 日志=日志, 更新=r.get("updated"), 更新人=r.get("updated_by"),
        执行闸="放行" if st in 放行的状态 else "拦下")


# ── 写 ──────────────────────────────────────────────────────────────
def _落一行(c, name, 我):
    if not c.execute("SELECT 1 FROM skill_cfg WHERE name=?", (name,)).fetchone():
        c.execute("INSERT INTO skill_cfg(name,status,version,updated,updated_by) VALUES(?,?,0,?,?)",
                  (name, 默认状态(name), _now(), 我.get("name")))


def _闸(name, 我):
    if not 我 or not 我.get("no"):
        return "没登录 —— 改技能配置要登录,署名用登录的人"
    if 我.get("role") not in 可编辑角色:
        return f"只有{'/'.join(可编辑角色)}能改技能配置,你是{我.get('role')}"
    if name not in 装了哪些():
        return f"没有装这个技能:{name}"
    return None


def 保存配置(name, 字段, 我, db=None):
    """改表单里那几栏。**不碰状态**(状态走 改状态,要过依赖就绪那道闸)。"""
    e = _闸(name, 我)
    if e:
        return dict(ok=False, reason=e)
    未知 = [k for k in 字段 if k not in _栏到列]
    if 未知:
        return dict(ok=False, reason=f"认不出的栏:{未知}")
    if "分类" in 字段 and (字段["分类"] or "") not in 分类们:
        return dict(ok=False, reason=f"分类只能是 {' / '.join(x for x in 分类们 if x)}")
    with closing(_连(db)) as c:
        确保表(c)
        _落一行(c, name, 我)
        旧 = dict(c.execute("SELECT * FROM skill_cfg WHERE name=?", (name,)).fetchone())
        改了 = []
        for k, v in 字段.items():
            列 = _栏到列[k]
            v = (str(v) if v is not None else "").strip()
            if (旧.get(列) or "") != v:
                c.execute(f"UPDATE skill_cfg SET {列}=? WHERE name=?", (v, name))
                c.execute("INSERT INTO skill_cfg_log(name,what,before,after,why,by_no,by_name,at) VALUES(?,?,?,?,?,?,?,?)",
                          (name, k, 旧.get(列) or "", v, "", 我["no"], 我["name"], _now()))
                改了.append(k)
        if 改了:
            c.execute("UPDATE skill_cfg SET version=version+1, updated=?, updated_by=? WHERE name=?",
                      (_now(), 我["name"], name))
        c.commit()
    return dict(ok=True, 改了=改了)


def 改状态(name, 到, 理由, 我, db=None):
    e = _闸(name, 我)
    if e:
        return dict(ok=False, reason=e)
    if 到 not in 状态们:
        return dict(ok=False, reason=f"状态只能是 {' / '.join(状态们)}")
    if not (理由 or "").strip():
        return dict(ok=False, reason="改状态要写理由 —— 以后有人问「这个技能为什么停了 / 为什么放出来了」,答案在这里")
    with closing(_连(db)) as c:
        确保表(c)
        _落一行(c, name, 我)
        现 = c.execute("SELECT status FROM skill_cfg WHERE name=?", (name,)).fetchone()[0]
        if 到 not in 可走.get(现, ()):
            return dict(ok=False, reason=f"「{现}」不能直接到「{到}」,能走的是:{' / '.join(可走.get(现, ())) or '无'}")
        if 到 in 放行的状态:
            依 = 依赖(name)
            if not 依["就绪"]:
                return dict(ok=False, reason="依赖没就绪,不能放进「" + 到 + "」:"
                            + "；".join(([f"缺脚本 {', '.join(依['缺的脚本'][:3])}"] if 依["缺的脚本"] else [])
                                       + ([f"要外部能力 {', '.join(依['外部能力'])}"] if 依["外部能力"] else [])))
        c.execute("UPDATE skill_cfg SET status=?, version=version+1, updated=?, updated_by=? WHERE name=?",
                  (到, _now(), 我["name"], name))
        c.execute("INSERT INTO skill_cfg_log(name,what,before,after,why,by_no,by_name,at) VALUES(?,?,?,?,?,?,?,?)",
                  (name, "状态", 现, 到, 理由.strip(), 我["no"], 我["name"], _now()))
        c.commit()
    return dict(ok=True, 从=现, 到=到)
