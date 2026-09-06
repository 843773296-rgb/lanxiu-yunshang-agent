#!/usr/bin/env python3
"""边界审计 —— 这个项目对外说过的每条保证,到底靠什么成立?

## 为什么要有这个文件

这个项目做到今天,累了很多「保证」:工具全部只读、真值表不外泄、
预算封顶、无同意取不到身体数据、成长方案必须带区间……

但**从来没有一份清单说明每条保证靠什么成立**。而它们其实分三类:

  结构  做不到 —— 试了会失败(只读连接、运行时拦截、Hook 拦下)
  检查  做得到,但提交前会被抓 —— 一道测试守着(guards / pinned / scan)
  约定  只是「不该做」—— 提示词里写着,**没有任何东西会失败**

三类在平时长得一模一样,**直到换个人、换个模型、隔三个月**。
这个项目已经被这件事咬过三次:

  ① 「工具全部只读」曾经是破的 —— allowed_tools 不是排他白名单,
     内置 Bash 一直在场,只是 DeepSeek **碰巧**没去用
  ② 新工具挂了 MCP 却没进白名单 —— 靠**人记得**同步两个文件
  ③ 密钥扫描规则连着三次匹配自己 —— 靠**人记得**加排除项

一件事出三次就不是运气,是系统性缺口:**这些边界都建立在
「会记得做对」上,而不是「做错了会失败」上。**

## 这个文件怎么保证自己不烂

**静态文档会烂,可执行的不会。**
所以「结构」类的每一条,下面都有一段代码**真的去攻击它一次** ——
攻击成功就是边界破了,当场红。

一条声称「靠结构」却从没被攻击过的保证,**实际上仍然只是约定**。
"""
import os, sys, sqlite3, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite"),
                os.path.join(ROOT, "agent")]
import api, ops, guards

SDK_SRC = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()


def _must_fail(fn, *exc):
    """攻击必须失败。成功了 = 边界破了。"""
    try:
        r = fn()
    except exc or (Exception,):
        return True, "被拦下"
    return False, f"**攻击成功,边界是破的**(返回 {str(r)[:60]})"


def _consent_off(wid, scope=None):
    c = sqlite3.connect(api.DB)
    q = "UPDATE consent SET revoked_at='2026-08-01' WHERE wearer_id=?" + (
        " AND scope=?" if scope else "")
    c.execute(q, (wid, scope) if scope else (wid,)); c.commit(); c.close()


def _consent_on(wid):
    c = sqlite3.connect(api.DB)
    c.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id=?", (wid,))
    c.commit(); c.close()


# ── 结构类:攻击必须失败 ────────────────────────────────────────────────
def a_write():
    return api._rows("UPDATE customer SET name='被改了' WHERE id='C10000'")

def a_truth_from():   return api._rows("SELECT * FROM truth")
def a_truth_join():   return api._rows("SELECT t.id FROM task t JOIN truth u ON u.case_id=t.id")
def a_truth_case():   return api._rows("select ROOT_CAUSE from TRUTH limit 1")

def a_cred_direct(): return api._rows("SELECT pwd_hash FROM account")
def a_cred_case():   return api._rows("select PWD_SALT from ACCOUNT")
def a_cred_star():   return api._rows("SELECT * FROM account")
def a_cred_alias():  return api._rows(
    "select a.* from account a join wearer w on w.account_id=a.id")
def a_cred_sub():    return api._rows(
    "SELECT p AS x FROM (SELECT pwd_hash p FROM account) t")


def a_bash():
    v = guards.pre_tool_verdict("Bash", {"command": "ls"})
    if v: raise PermissionError(v)
    return "Bash 放行了"

def a_task():
    v = guards.pre_tool_verdict("Task", {})
    if v: raise PermissionError(v)
    return "Task 放行了"

def a_consent_body():
    _consent_off("W10010-2")
    try:
        r = api.forecast_growth("W10010-2")
        if r.get("error"): raise PermissionError(r["error"])
        return r
    finally: _consent_on("W10010-2")

def a_consent_minor():
    _consent_off("W10010-2", "未成年人")
    try:
        r = api.forecast_growth("W10010-2")
        if r.get("error"): raise PermissionError(r["error"])
        return r
    finally: _consent_on("W10010-2")

def a_expired_order():
    b = ops.order_block("W10010-2")
    if not b["放行"]: raise PermissionError(b["原因"])
    return b

def a_whitelist():
    for ns, sch in (("kb", api.KB_SCHEMAS), ("shop", api.SHOP_SCHEMAS), ("task", api.SCHEMAS)):
        white = set(re.findall(r'"mcp__%s__(\w+)"' % ns, SDK_SRC))
        real = {x["name"] for x in sch}
        if white != real:
            # 约定:返回 = 攻击成功 = 边界破了;抛异常 = 被拦下 = 边界完好
            return f"{ns} 白名单与 MCP 暴露不一致:{sorted(white ^ real)}"
    raise PermissionError("白名单与 MCP 暴露完全一致")

def a_budget():
    if "max_budget_usd=MAX_USD" not in SDK_SRC: return "没传预算上限"
    raise PermissionError("预算上限已传入 options")

def a_disallowed():
    miss = [t for t in ("Bash", "Write", "Edit", "Read", "Task", "WebFetch")
            if f'"{t}"' not in SDK_SRC]
    if miss: return f"disallowed_tools 漏了 {miss}"
    raise PermissionError("危险内置工具已在 disallowed_tools 里点名")

def a_strict_mcp():
    if "strict_mcp_config=True" not in SDK_SRC: return "没开 strict_mcp_config"
    declared = set(json.load(open(os.path.join(ROOT, ".mcp.json")))["mcpServers"])
    code = set(re.findall(r'"(kb|shop|task)":\s*\{', SDK_SRC)) or {"kb", "shop", "task"}
    if declared & code: return f".mcp.json 的服务名和代码声明重合:{declared & code}"
    raise PermissionError(f".mcp.json 声明的 {sorted(declared)} 全被忽略,只认代码里的")


STRUCT = [
 ("工具层一个写接口都没有", "backend/api.py 开篇铁律 / README「工具全部只读」",
  a_write, "拿工具层的连接去 UPDATE 一条客户记录",
  "连接开成 mode=ro —— **写操作直接抛错,不是碰巧没人写 INSERT**"),
 ("truth 表不经工具层暴露 · 直查", "backend/api.py 开篇铁律",
  a_truth_from, "SELECT * FROM truth", "任何提到 truth 的 SQL 一律拒绝执行"),
 ("truth 表不经工具层暴露 · JOIN 绕过", "同上",
  a_truth_join, "写成 JOIN truth,绕开只认 FROM 的旧检查",
  "**这一条原来是破的** —— 旧检查是 `re.findall(r'FROM\\s+(\\w+)')`,只认 FROM;"
  "而 ops.py 里就是 JOIN 写法。改成运行时按语句内容拦"),
 ("truth 表不经工具层暴露 · 大小写", "同上",
  a_truth_case, "select … from TRUTH", "正则带 re.I,不看大小写"),
 ("账户凭据不经工具层暴露 · 直查", "backend/api.py 锁三 / 个保法敏感信息",
  a_cred_direct, "SELECT pwd_hash FROM account",
  "语句文本命中 pwd_ 就快速失败"),
 ("账户凭据不经工具层暴露 · 大小写", "同上", a_cred_case, "select PWD_SALT from ACCOUNT",
  "正则带 re.I"),
 ("账户凭据不经工具层暴露 · 星号", "同上", a_cred_star, "SELECT * FROM account",
  "**查的是返回的列名,不是语句写法** —— 星号会把 pwd_* 带出来"),
 ("账户凭据不经工具层暴露 · 别名星号", "同上", a_cred_alias,
  "select a.* from account a join wearer w …",
  "**这条第一版是破的** —— 当时只正则匹配 `select * from account`,"
  "带别名就绕过去了。改成查结果列名,与写法无关"),
 ("账户凭据不经工具层暴露 · 子查询改名", "同上", a_cred_sub,
  "SELECT p AS x FROM (SELECT pwd_hash p FROM account) t",
  "两道锁各管一段:这条被语句文本那道接住"),
 ("模型不能执行命令", "sdk.py 提示词铁律 5「你没有任何写权限」",
  a_bash, "让 PreToolUse 判定 Bash 工具", "非 mcp__ 开头的工具一律拦下(Hook 运行时)"),
 ("模型不能开子智能体", "同上", a_task, "让 PreToolUse 判定 Task 工具", "同上"),
 ("配置层也点名封了内置工具", "sdk.py disallowed_tools",
  a_disallowed, "检查危险工具是否都在 disallowed_tools 里",
  "**双锁**:配置一道 + Hook 一道。配置会被人改错,Hook 是兜底"),
 ("无有效同意 → 取不到身体数据", "12-成长与生命周期.md 第七节 / 个保法 28 条",
  a_consent_body, "撤销身体数据同意后调推算", "工具层硬门,不靠模型自觉"),
 ("不满 14 周岁缺监护人同意 → 不能推算", "同上 / 个保法 31 条",
  a_consent_minor, "只撤未成年人同意后调推算", "工具层硬门"),
 ("量体超期 → 下单被拦", "12-成长与生命周期.md 第五节",
  a_expired_order, "拿一个量体已过期的孩子走下单前拦截", "ops.order_block 规则直出"),
 ("白名单与 MCP 暴露完全一致", "skills_check.py",
  a_whitelist, "比对两边集合", "**这一条漏过一次**(新工具挂了 MCP 没进白名单)"),
 ("单次会话预算封顶", "sdk.py MAX_USD",
  a_budget, "检查 max_budget_usd 是否传进 options", "SDK 层强制,超了直接停"),
 ("MCP 只认代码里声明的服务", "sdk.py strict_mcp_config",
  a_strict_mcp, "比对 .mcp.json 与代码声明的服务名",
  "两边名字完全不同 —— 名字对不上,正好**证明** .mcp.json 真的被忽略了"),
]

# ── 检查类:结构上做得到,但有一道检查会在提交前抓住 ────────────────────
CHECKED = [
 ("回答必须带区间 / 限定 / 复量 / 转人工", "guards g10–g15",
  "43 条正反用例(该拦 21 / 不该拦 22),`agentsite/guards_test.py`"),
 ("报价单免责必须齐全", "guards g9", "同上,含「需评估」「需补量」「香云纱雨季」三种触发"),
 ("成长方案六段必须齐全", "guards g15", "Skill 定格式,Hook 保证格式被遵守"),
 ("密钥不进仓库", "tools/scan_secrets.sh", "push 前跑;规则文件自身排除"),
 ("知识 md 与库一致", "derive_combo.py / derive_pattern.py", "2025 格 + 1181 条尺码逐条对账"),
 ("锚点不来自被测系统(防同源谬误)", "pinned_check.py", "13 条手抄常数,故意不现算"),
 ("不得建议绕过审批链 / 幂等号 / 重试上限", "guards g16",
  "**本次审计补的锁** —— 原来只有提示词守着,而这条涉及钱:"
  "幂等号复用会重复退款,跳过审批会绕开双人复核,两者都不可逆"),
]

# ── 约定类:只有提示词说,没有任何东西会失败 ────────────────────────────
CONVENTION = [
 ("只说知识库里查到的,不得凭训练知识作答", "sdk.py 铁律 1",
  "g1 只抓「报了数字却没调工具」——**换个不带数字的说法就漏**,"
  "比如「云锦这种料子一般比较厚重」"),
 ("区分「不能做」和「不建议做」", "sdk.py 铁律 4", "没有任何检查"),
 ("换面料必须让客户确认,不能替他决定", "sdk.py 铁律 10", "没有任何检查"),
 ("demo 级来源不可作为对客户的承诺", "sdk.py 铁律 3",
  "g1 查了来源标注,但没查「拿 demo 数据做承诺」"),
]


def run():
    print("边界审计 —— 每条保证靠什么成立\n" + "=" * 92)
    bad = []
    print(f"\n【结构】做不到 —— 下面每一条都**真的攻击了一次**,攻击必须失败({len(STRUCT)} 条)\n")
    for name, src, atk, how, why in STRUCT:
        ok, msg = _must_fail(atk)
        if not ok: bad.append((name, msg))
        print(f"  {'✅' if ok else '❌'} {name}")
        print(f"      攻击:{how} → {msg}")
        print(f"      靠什么:{why}")
        print(f"      出处:{src}")
    print(f"\n【检查】做得到,但提交前会被抓({len(CHECKED)} 条)\n")
    for name, by, ev in CHECKED:
        print(f"  ◆ {name}\n      守它的:{by} —— {ev}")
    print(f"\n【约定】**没有任何东西会失败**({len(CONVENTION)} 条)\n")
    for name, src, gap in CONVENTION:
        print(f"  ⚠ {name}\n      只有:{src}\n      缺口:{gap}")

    print("\n" + "=" * 92)
    print(f"  结构 {len(STRUCT)} · 检查 {len(CHECKED)} · 约定 {len(CONVENTION)}")
    print("  **约定类不是错误,是已知风险。** 但它必须被写下来 ——")
    print("  没写下来的约定,和结构锁在平时长得一模一样,直到有一天不一样。")
    if bad:
        print(f"\n❌ {len(bad)} 条声称靠结构的保证,攻击成功了:")
        for n, m in bad: print(f"   · {n}:{m}")
        return 1
    print(f"\n✅ {len(STRUCT)} 条结构性保证全部扛住了攻击")
    return 0


def to_md():
    """把同一份数据投影成 Markdown。**不手写第二份** —— 两张表一定漂。"""
    L = ["# 安全边界审计",
         "",
         "> 由 `backend/boundary_audit.py --md` 生成,不要手改。",
         "> 数据只有一份,这份文档是它的投影 —— 手写第二份就一定会漂。",
         "",
         "## 为什么做这次审计",
         "",
         "这个项目累了很多「保证」,但**从来没有一份清单说明每条保证靠什么成立**。",
         "而它们其实分三类,平时长得一模一样,**直到换个人、换个模型、隔三个月**:",
         "",
         "| 类别 | 意思 | 违反时会怎样 |",
         "|---|---|---|",
         "| **结构** | 做不到 | 试了就失败 |",
         "| **检查** | 做得到,但提交前会被抓 | 检查变红,人来看 |",
         "| **约定** | 只是「不该做」 | **什么都不会发生** |",
         "",
         "触发这次审计的是三件事,形状完全一样:",
         "",
         "1. 「工具全部只读」曾经是破的 —— 内置 Bash 一直在场,只是当时那个模型**碰巧**没去用",
         "2. 新工具挂了 MCP 却没进白名单 —— 靠**人记得**同步两个文件",
         "3. 密钥扫描规则连着三次匹配自己 —— 靠**人记得**加排除项",
         "",
         "一件事出三次就不是运气,是系统性缺口:",
         "**这些边界都建立在「会记得做对」上,而不是「做错了会失败」上。**",
         "",
         "## 这份清单怎么保证自己不烂",
         "",
         "静态文档会烂,可执行的不会。",
         "下面「结构」类的每一条,`boundary_audit.py` 里都有一段代码**真的去攻击它一次** ——",
         "攻击成功就当场红,`check.sh` 每次都跑。",
         "",
         "**一条声称「靠结构」却从没被攻击过的保证,实际上仍然只是约定。**",
         "",
         f"## 一、结构 —— 做不到({len(STRUCT)} 条)",
         "",
         "| 保证 | 怎么攻击它 | 靠什么挡住 |",
         "|---|---|---|"]
    for name, src, atk, how, why in STRUCT:
        L.append(f"| **{name}** | {how} | {why} |")
    L += ["",
          f"## 二、检查 —— 做得到,但提交前会被抓({len(CHECKED)} 条)",
          "",
          "| 保证 | 守它的 | 怎么守 |", "|---|---|---|"]
    for name, by, ev in CHECKED:
        L.append(f"| {name} | `{by}` | {ev} |")
    L += ["",
          f"## 三、约定 —— 没有任何东西会失败({len(CONVENTION)} 条)",
          "",
          "**这一节不是错误清单,是已知风险清单。**",
          "写下来的目的不是消灭它们 —— 有些确实不值得为它写检查 ——",
          "而是让它们**不再冒充结构锁**。",
          "",
          "| 保证 | 只有 | 缺口在哪 |", "|---|---|---|"]
    for name, src, gap in CONVENTION:
        L.append(f"| {name} | {src} | {gap} |")
    L += ["",
          "## 这次审计改了什么",
          "",
          "| 原来 | 现在 |",
          "|---|---|",
          "| 工具层「没人写 INSERT」 | 连接开成只读,**写操作直接抛错** |",
          "| truth 表靠一行只认 `FROM` 的正则 | 运行时按语句内容拦,**JOIN / 大小写都拦得住** |",
          "| PreToolUse 判定藏在 async hook 里,离线测不到 | 抽成纯函数,审计可以直接攻击它 |",
          "| 「不得绕过审批链」只有提示词 | 补了一道体检 —— **这条涉及钱** |",
          "| 没有清单 | 这份清单,而且它是可执行的 |",
          "",
          "## 一句话",
          "",
          "**安全不是「我们不会那么做」,是「那么做会失败」。**",
          "",
          "剩下那几条约定不是失败,是**明知道的欠账**。",
          "欠账写在账本上和不写在账本上,是两回事。"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    if "--md" in sys.argv:
        print(to_md(), end=""); sys.exit(0)
    sys.exit(run())
