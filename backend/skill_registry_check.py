# -*- coding: utf-8 -*-
"""Skill 管理:状态真管得住执行闸、依赖没就绪放不出去、只有总部运营能改(用户 2026-10-23 拍,intent/skill-admin.md)。

**在库副本上真改状态,再问执行闸本身**(agentsite/guards.pre_tool_verdict)放不放行 ——
不在这里照着规则另判一遍:状态要是只在页面上显示、闸照旧读写死清单,
「页面上停用了」和「模型真调不动」会是两件事,而它们在页面上长得一模一样。

写口打 HTTP 层(server.do_POST,假 handler):身份只从登录会话来,请求体里自报的不认。
用法:./agentsite/.venv/bin/python backend/skill_registry_check.py   (不调模型;写的是库副本)
"""
import datetime as _dt, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
# ⚠️ 写口模块**先 import 再切库** —— 用副本只改已经加载的模块;之后才 import 的会写真库
import skill_registry as R, server, auth, oplog   # noqa: F401
sys.path.append(os.path.join(ROOT, "agentsite"))
import guards
guards._REG = R          # 闸用的就是这一份,不另载一份
import check_copy
副本 = check_copy.用副本("skill-reg-")

G, Rd, D = "\033[32m", "\033[31m", "\033[0m"
坏 = 0

咬合 = [
    ("执行闸改回读写死的自有清单(不看状态)", "停用一个自有技能:执行闸真拦下"),
    ("放行时不查依赖就绪", "依赖没就绪的(缺脚本、要淘宝登录):进不了试运行"),
    ("改状态不查角色(谁都能改)", "顾问改状态:拒"),
    ("状态边不限制(待审查能直接发布)", "待审查不能直接跳到已发布"),
    ("分类改成清单优先(库里人工填的被清单盖掉)", "库里人工填的分类优先于审查清单"),
    ("没登记时不读审查清单", "没登记时:分类取审查清单(自造清单里写的那一类)"),
    ("审查清单里一条的理由被清空", "版本库里的审查清单:每条分类合法、有理由;和初筛不同的写了为什么"),
]


def ck(名, ok, 细=""):
    global 坏
    if not ok: 坏 += 1
    print(f"  {G+'✅'+D if ok else Rd+'❌'+D} {名}{'  ' + 细 if 细 else ''}")


class 假请求:
    def __init__(self, path, body, tok=None):
        self.path = path
        self._b = json.dumps(body, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(self._b))}
        if tok: self.headers["cookie"] = f"lx_token={tok}"
        self.rfile, self.wfile = io.BytesIO(self._b), io.BytesIO()
    def send_response(self, *a): pass
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def 打(path, body, tok=None):
    h = 假请求(path, body, tok); 回 = {}
    def _send(obj, code=200): 回.update(码=code, 体=obj)
    h._send = _send
    server.H.do_POST(h)
    return 回.get("码"), 回.get("体") or {}


def 会话(role):
    r = server.rows("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' LIMIT 1", role)
    if not r: return None, None
    tok = f"skill-reg-{role}"
    with auth._LOCK: auth._SESS[tok] = dict(r[0], at=_dt.datetime.now())
    return tok, dict(r[0])


def 闸(n):
    return guards.pre_tool_verdict("Skill", {"skill": n}) is None


def 造技能目录():
    """**判据自己造要验的形状,不靠这台机器碰巧装了什么**(10-23 数据工厂查出):
    第三方技能目录被 .gitignore 挡着,版本库里只有 7 个自有的 —— 原来这条拿「本机装着的第三方」当样本,
    本机绿、CI 和另一个检出都红在「没东西可验」,而那和任何人改的代码无关。
    > 一条判据,如果它红不红取决于环境里碰巧有什么,那它不是在验代码。
    做法:临时目录里放进 7 个自有技能(链接)+ 两个自造的第三方技能 —— 一个依赖就绪、一个缺脚本又要淘宝登录。"""
    import tempfile, shutil, atexit
    d = tempfile.mkdtemp(prefix="skill-dir-")
    atexit.register(shutil.rmtree, d, True)
    真 = R.技能目录
    for n in R._ours():
        if os.path.isdir(os.path.join(真, n)):
            os.symlink(os.path.join(真, n), os.path.join(d, n))
    for n, 正文 in (
        ("chk-third-ready", "---\nname: chk-third-ready\ndescription: 自造的第三方技能,只调本系统工具\n---\n\n"
                            "## 第一步\n调 `get_stock` 查现货。\n"),
        ("chk-third-missing", "---\nname: chk-third-missing\ndescription: 自造的第三方技能,依赖缺着\n---\n\n"
                              "## 第一步\n运行 `scripts/collect.py` 采集淘宝店铺库存。\n")):
        os.makedirs(os.path.join(d, n))
        open(os.path.join(d, n, "SKILL.md"), "w", encoding="utf-8").write(正文)
    R.技能目录 = d
    # 自造一份审查清单:只写「就绪」那个,「缺依赖」那个故意不写 —— 验「没写的就是空」
    清 = os.path.join(d, "_review.json")
    json.dump({"chk-third-ready": {"分类": "可适配", "理由": "自造:只调本系统工具"}},
              open(清, "w", encoding="utf-8"), ensure_ascii=False)
    R.审查清单 = 清
    return d


def 审查清单的形状(路径):
    """**版本库里那份**审查清单(随代码走,CI 上也有)—— 每条分类合法、理由非空;初筛和人工不同的要写为什么。
    → (条数, 坏的[(名, 哪里坏)])"""
    单 = json.load(open(路径, encoding="utf-8"))
    坏 = []
    for n, e in 单.items():
        if e.get("分类") not in R.分类们[1:]:
            坏.append((n, f"分类「{e.get('分类')}」不在四类里"))
        if not (e.get("理由") or "").strip():
            坏.append((n, "没写理由"))
        if e.get("初筛") and e.get("初筛") != e.get("分类") and not (e.get("与初筛不同") or "").strip():
            坏.append((n, f"初筛 {e['初筛']} → 人工 {e['分类']},没写为什么不同"))
    return len(单), 坏


def main():
    print("\n\033[1m▸ Skill 管理 · 在库副本上改状态,问执行闸本身\033[0m")
    造技能目录()
    # 📖 库况(只打印,不是判据):这台机器真装了几个第三方
    try:
        _真 = os.path.join(ROOT, "agentsite", ".claude", "skills")
        _第三方 = [x for x in os.listdir(_真) if os.path.isfile(os.path.join(_真, x, "SKILL.md")) and x not in R._ours()]
        print(f"  📖 库况(不是判据):这台机器装着 {len(_第三方)} 个第三方技能 —— 判据用的是自造的两个,不靠它")
    except OSError:
        pass
    import oplog as _ol
    if os.path.realpath(R.DB) != os.path.realpath(副本) or os.path.realpath(_ol.DB) != os.path.realpath(副本):
        print(f"  {Rd}❌ 写口没切到副本(R.DB={R.DB} oplog.DB={_ol.DB})—— 不跑,免得写真库{D}"); return 1
    自有, 第三方缺, 第三方好 = "quote", "chk-third-missing", "chk-third-ready"
    ck("自造的样本真分出了两种:一个依赖就绪、一个没就绪(少了这一条,下面两样一起变成什么都不验)",
       R.依赖(第三方好)["就绪"] and not R.依赖(第三方缺)["就绪"] and 自有 in R.装了哪些(),
       f"就绪={R.依赖(第三方好)['就绪']} 缺依赖={R.依赖(第三方缺)}")
    tH, 总部 = 会话("总部运营"); tG, _ = 会话("顾问")
    if not (tH and tG):
        print(f"  {Rd}❌ 库里找不到在职的总部运营 / 顾问 —— 没东西可验{D}"); return 1

    ck("默认:自有的已发布、第三方的待审查(上线那一刻和原来一样)",
       R.状态(自有) == "已发布" and R.状态(第三方好) == "已安装待审查")
    ck("默认:执行闸放自有、拦第三方", 闸(自有) and not 闸(第三方好))

    # ── 第三方审查清单(intent/skill-third-party.md):没登记时的默认分类,库里人工填的优先 ──
    行 = {x["名称"]: x for x in R.清单()}
    ck("没登记时:分类取审查清单(自造清单里写的那一类)",
       行[第三方好]["分类"] == "可适配" and 行[第三方好]["分类来源"] == "审查清单"
       and 行[第三方缺]["分类"] == "" and R.详情(第三方好)["分类"]["来源"] == "审查清单",
       f"就绪那个={行[第三方好]['分类']}/{行[第三方好]['分类来源']} · 清单没写的那个={行[第三方缺]['分类']!r}")
    ck("清单写「可适配」不等于放行:执行闸照拦、状态仍是待审查",
       not 闸(第三方好) and R.状态(第三方好) == "已安装待审查")
    码, 体 = 打("/api/skill-save", {"name": 第三方好, "fields": {"分类": "不适用", "分类理由": "检查里人工改判"}}, tH)
    行 = {x["名称"]: x for x in R.清单()}
    详 = R.详情(第三方好)["分类"]
    ck("库里人工填的分类优先于审查清单", 体.get("ok") and 行[第三方好]["分类"] == "不适用"
       and 行[第三方好]["分类来源"] == "库" and 详["来源"] == "库" and 详["理由"] == "检查里人工改判",
       f"{体} · 列表={行[第三方好]['分类']}/{行[第三方好]['分类来源']} · 详情={详}")
    _真单 = os.path.join(ROOT, "agentsite", "third_party_review.json")
    条, 坏单 = 审查清单的形状(_真单)
    ck("版本库里的审查清单:每条分类合法、有理由;和初筛不同的写了为什么", 条 > 0 and not 坏单,
       f"{条} 条" + (f" · 坏 {len(坏单)} 条:{坏单[:3]}" if 坏单 else ""))
    # 📖 库况(只打印,不是判据):这台机器装着的第三方,审查清单覆盖了几个 —— CI 上没有那 236 个,所以不判红
    try:
        _单 = json.load(open(_真单, encoding="utf-8"))
        _真 = os.path.join(ROOT, "agentsite", ".claude", "skills")
        _装 = [x for x in os.listdir(_真) if os.path.isfile(os.path.join(_真, x, "SKILL.md")) and x not in R._ours()]
        _漏 = [x for x in _装 if x not in _单]
        print(f"  📖 库况(不是判据):这台机器装着 {len(_装)} 个第三方,审查清单覆盖 {len(_装) - len(_漏)} 个"
              + (f",没覆盖 {len(_漏)} 个:{_漏[:5]}" if _漏 else ",全覆盖"))
    except (OSError, ValueError):
        pass

    依 = R.依赖(第三方缺)
    ck("依赖现算:缺脚本、要淘宝登录的那个认得出来", not 依["就绪"] and 依["缺的脚本"] and 依["外部能力"],
       f"缺 {len(依['缺的脚本'])} 个脚本 · 外部 {依['外部能力'][:2]}")

    码, 体 = 打("/api/skill-status", {"name": 第三方好, "to": "待适配", "why": "x"})
    ck("没登录改状态:拒(401)", 码 == 401, f"回了 {码}")
    码, 体 = 打("/api/skill-status", {"name": 第三方好, "to": "待适配", "why": "x"}, tG)
    ck("顾问改状态:拒", not 体.get("ok") and "总部运营" in (体.get("reason") or ""), f"{体}")
    码, 体 = 打("/api/skill-status", {"name": 第三方好, "to": "已发布", "why": "直接发布"}, tH)
    ck("待审查不能直接跳到已发布", not 体.get("ok") and "不能直接到" in (体.get("reason") or ""), f"{体}")
    码, 体 = 打("/api/skill-status", {"name": 第三方好, "to": "待适配", "why": ""}, tH)
    ck("改状态不写理由:拒", not 体.get("ok") and "理由" in (体.get("reason") or ""), f"{体}")

    for 到 in ("待适配", "试运行"):
        码, 体 = 打("/api/skill-status", {"name": 第三方好, "to": 到, "why": "检查里走一遍"}, tH)
    ck("依赖就绪的第三方:走到试运行,执行闸真放行", 体.get("ok") and 闸(第三方好), f"{体} 闸={'放' if 闸(第三方好) else '拦'}")

    打("/api/skill-status", {"name": 第三方缺, "to": "待适配", "why": "检查"}, tH)
    码, 体 = 打("/api/skill-status", {"name": 第三方缺, "to": "试运行", "why": "检查"}, tH)
    ck("依赖没就绪的(缺脚本、要淘宝登录):进不了试运行", not 体.get("ok") and "依赖没就绪" in (体.get("reason") or "")
       and not 闸(第三方缺), f"{体}")

    码, 体 = 打("/api/skill-status", {"name": 自有, "to": "已停用", "why": "检查里停一下"}, tH)
    ck("停用一个自有技能:执行闸真拦下", 体.get("ok") and not 闸(自有), f"{体} 闸={'放' if 闸(自有) else '拦'}")

    码, 体 = 打("/api/skill-save", {"name": 自有, "fields": {"负责人": "检查", "分类": "瞎填"}}, tH)
    ck("配置:分类只能是那四种", not 体.get("ok"), f"{体}")
    码, 体 = 打("/api/skill-save", {"name": 自有, "fields": {"负责人": "检查人", "适用岗位": "顾问"}}, tH)
    d = R.详情(自有)
    ck("配置:存得进、版本加一、记了改动", 体.get("ok") and d["配置"]["负责人"] == "检查人"
       and any(x["what"] == "负责人" for x in d["日志"]), f"版本 {d['版本']} · 日志 {len(d['日志'])} 条")
    ck("改动记录带理由和署名(状态那几条)",
       any(x["what"] == "状态" and x["why"] and x["by_name"] == 总部["name"] for x in d["日志"]))

    try:
        import sdk
        sdk._all_skills = R.装了哪些     # 让 sdk 看同一个(自造的)技能目录
        ck("技能集合跟着状态走:停用的不再上场,试运行的上场",
           自有 not in sdk.skills_for("own") and 第三方好 in sdk.skills_for("own"))
    except ImportError as e:
        ck("技能集合跟着状态走:停用的不再上场,试运行的上场", False, f"sdk 导不进来:{e} —— 要用 venv 的 python 跑")

    with auth._LOCK:
        for t in (tH, tG): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{Rd}❌ Skill 管理 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ Skill 管理:状态管得住执行闸,依赖没就绪放不出去,只有总部运营能改{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
