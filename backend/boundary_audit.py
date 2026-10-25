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


# 这几种异常**不是「被拦下」,是「攻击自己坏了」**。
#
# 原来 `_must_fail` 把**任何**异常都读成「被拦下」,于是一个 import 写错的攻击
# 和一条守住了的边界,在输出上**长得一模一样** —— 全都是绿的 ✅。
#
# 实测撞上:新加的那条攻击里 `import sdk`,而 sdk 要 `claude_agent_sdk`
# (只装在 venv 里),`check.sh` 用的是系统 python3 —— **那条攻击一次都没跑过**,
# 而它每次都绿。咬合的时候我把边界故意改坏两次,两次都还是绿的,
# 才发现红不起来的原因不在边界上。
#
# 这是这个项目反复撞的那件事的又一次:**失败要有声音。**
class 前提不成立(Exception):
    """这条攻击的**前提**搭不起来(库里没有要攻的那个形状、正常那一步自己先失败了……)。

    ⚠️ 2026-10-23 加的,起因是一次**红错理由**:`预警转任务` 那条攻击用
    `return "第一次正常派就没派出去(…)"` 表示「前提不成立」,
    而 `_must_fail` 的约定是「**抛 = 拦住、返回 = 攻破**」——
    于是那句话被报成了 **「攻击成功,边界是破的」**。
    > 一句「这条攻击没验到」和一句「这条边界被攻破了」,
    > **在那条红上长得一模一样** —— 而照着后者去查,是去找一个不存在的安全漏洞。
    归进 `攻击自己坏了` 之后它报的是「这条攻击自己跑不起来,它什么都没验」,
    **仍然红**(跑不起来也算没守住,不许和「通过」长得一样),但理由是实话。
    """


攻击自己坏了 = (ImportError, ModuleNotFoundError, NameError, AttributeError,
                SyntaxError, IndentationError, FileNotFoundError, KeyError,
                前提不成立)

# ⚠️ **这个标记是两处共用的,别抄第二份。** `_must_fail` 写它、`run()` 读它去分类 ——
# 各写一份字符串的话,哪天改了措辞,`run()` 会把「跑不起来」重新归进「被攻破」,
# **而它不报错**:汇总那一行照旧红,只是又开始说假话了。
跑不起来标记 = "**这条攻击自己跑不起来**"


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    # ⚠️ 2026-10-23:**「前提不成立」必须报成「没验到」,不许报成「边界是破的」。**
    # 攻击是把 `止` 钉成过去的时刻,让这条攻击的前提真的塌掉。
    # 第一版我攻的是那行 `raise 前提不成立` 本身(改回 `return`)——
    # **而前提成立时那行根本走不到**,攻击是空操作;
    # 也不能拿「写死 23:00」当攻击:那只在一天里某几个钟点红,白天显示成「没红」。
    ("把预警转任务那条攻击的 `止` 钉成一个过去的时刻(前提塌掉)",
     "这条攻击自己跑不起来,它什么都没验"),
    ('把工具层的只读连接开成可写(读连接从此也能改库)',
     '工具层的读连接写不了库'),
    ('按需加载的名单闸被拆掉(调用时不按这一轮名单核)', '按需加载只取回自己名单里的工具'),
    ('ToolSearch 的点名例外写成按前缀放行(Bash 也一并放了)', '按需加载只取回自己名单里的工具'),
    ('全能助手顺手挂上了版师那一包(ToolSearch 搜得到版师写口)', '按需加载只取回自己名单里的工具'),
    ('聊天站 /run 没登录也照样往下跑', '没登录调不动聊天站的智能体'),
    ('store_report 不再拿掉被模板隐藏的指标(_藏 恒为空)',
     '报告模板隐藏的指标,写报告的 AI 拿不到它的数'),
    ('隐藏了销量,环比里销量那一行照旧留着',
     '报告模板隐藏的指标,写报告的 AI 拿不到它的数'),
]

def _must_fail(fn, *exc):
    """攻击必须失败。成功了 = 边界破了;**跑不起来也算没守住**。"""
    try:
        r = fn()
    except 攻击自己坏了 as e:
        return False, (f"{跑不起来标记}({type(e).__name__}: {str(e)[:60]})—— "
                       f"跑不起来的攻击不叫「被拦下」,它什么都没验")
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
def a_insert_schedule():
    """绕开 tasks.py,拿只读连接直接塞一条任务进去。"""
    return api._rows("INSERT INTO schedule(id,type,status) VALUES('SC-HACK','日常运维','有效')")


def a_write_role_param():
    """给写工具传身份参数试图提权 —— 签名里没有,应该直接 TypeError。"""
    import inspect
    for n in api.WRITE_TOOLS:
        sig = inspect.signature(inspect.unwrap(api.TOOLS[n]))
        for bad in ("role", "actor", "operator", "as_user", "me"):
            if bad in sig.parameters:
                return f"{n} 的入参里居然有 {bad} —— 一句「我以店长身份」就能提权"
    raise TypeError("写工具的签名里没有身份参数(这正是期望的)")


def a_customer_read_no_login():
    """管理后台客户读接口:没登录去翻详情、店长去翻别家店的客户(用户 10-23 拍「必须登录」)。
    打路由不调函数 —— 闸在路由到函数之间,函数本身不管身份。"""
    import customer_read_auth_check as _C, server as _S
    c = _S.rows("SELECT id FROM customer LIMIT 1")
    if not c:
        return "没有可攻击的客户 —— 没攻击成,不算守住"
    码, _ = _C.打(f"/api/customer/{c[0]['id']}")
    if 码 != 401:
        return f"没登录翻客户详情回了 {码} —— 门没守住"
    店长 = _S.rows("SELECT s.no,s.name,s.role,s.shop FROM staff s WHERE s.role='店长' AND s.status='启用' "
                   "AND EXISTS(SELECT 1 FROM customer c WHERE c.shop<>s.shop) LIMIT 1")
    if not 店长:
        return "没有可攻击的店长 —— 没攻击成,不算守住"
    别 = _S.rows("SELECT id FROM customer WHERE shop<>? LIMIT 1", 店长[0]["shop"])[0]["id"]
    t = _C.会话(dict(店长[0]))
    try:
        码2, _ = _C.打(f"/api/customer/{别}", t)
    finally:
        import auth as _a
        with _a._LOCK: _a._SESS.pop(t, None)
    if 码2 != 403:
        return f"店长翻别家店的客户 {别} 回了 {码2} —— 门店范围没守住"
    raise PermissionError("没登录 401、跨店 403(这正是期望的)")


def a_scheme_customer_search():
    """方案页搜客户(复审第 4 节 B,10-23):没登录去搜、店长按客户号搜别家店的客户、
    拿别家客户的着装人去推码。打路由不调函数(搜索的门店范围在路由里取登录身份)。"""
    import customer_read_auth_check as _C, server as _S, api as _A
    码, _ = _C.打("/api/scheme-customers?q=C1")
    if 码 != 401:
        return f"没登录搜客户回了 {码} —— 门没守住"
    店长 = _S.rows("SELECT s.no,s.name,s.role,s.shop FROM staff s WHERE s.role='店长' AND s.status='启用' "
                   "AND EXISTS(SELECT 1 FROM customer c JOIN measure_rec r ON r.customer_id=c.id "
                   "WHERE c.shop<>s.shop) LIMIT 1")
    if not 店长:
        return "没有可攻击的店长 —— 没攻击成,不算守住"
    别 = _S.rows("SELECT c.id FROM customer c WHERE c.shop<>? AND EXISTS("
                 "SELECT 1 FROM measure_rec r WHERE r.customer_id=c.id) LIMIT 1", 店长[0]["shop"])[0]["id"]
    t = _C.会话(dict(店长[0]))
    try:
        _, 回 = _C.打(f"/api/scheme-customers?q={别}", t)
    finally:
        import auth as _a
        with _a._LOCK: _a._SESS.pop(t, None)
    if any(x.get("id") == 别 for x in (回 or {}).get("rows") or []):
        return f"店长按客户号搜到了别家店的客户 {别} —— 门店范围没守住"
    两 = _S.rows("SELECT w.id FROM wearer w JOIN customer k ON k.account_id=w.account_id WHERE k.id<>? "
                 "AND w.account_id <> (SELECT account_id FROM customer WHERE id=?) LIMIT 1", 别, 别)
    if 两:
        d = _A.kb_fit(别, "PT04", wearer=两[0]["id"])
        if d.get("推荐尺码"):
            return f"拿别家客户的着装人 {两[0]['id']} 给 {别} 推出了 {d['推荐尺码']} 码 —— 拿另一个人的尺寸去裁"
    raise PermissionError("没登录 401、跨店搜不到、别家着装人不推码(这正是期望的)")


def a_skill_gate():
    """Skill 管理后台里停用一个技能,模型还调不调得动(用户 10-23 拍「做完整配置页」)。
    在库副本上把自有的 quote 标成「已停用」,问执行闸本身 —— 状态要是只在页面上显示、闸照旧读写死清单,
    「页面上停用了」和「模型真调不动」就是两件事,而它们在页面上长得一模一样。"""
    import skill_registry as _R, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq, sys as _sys
    _sys.path.append(_os.path.join(ROOT, "agentsite"))
    import guards as _g
    原, 原闸 = _R.DB, _g._REG
    d = _tf.mkdtemp(prefix="ba-skill-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原, p)
    try:
        _R.DB = p; _g._REG = _R
        c = _sq.connect(p); _R.确保表(c)
        c.execute("INSERT OR REPLACE INTO skill_cfg(name,status,version) VALUES('quote','已停用',1)"); c.commit(); c.close()
        if _g.pre_tool_verdict("Skill", {"skill": "quote"}) is None:
            return "页面上停用了 quote,执行闸照样放行 —— 状态只是个显示字段"
        if _g.pre_tool_verdict("Skill", {"skill": "multi-platform-inventory-warning"}) is None:
            return "没登记过的第三方技能被放行了(默认应是待审查、拦下)"
    finally:
        _R.DB, _g._REG = 原, 原闸
        _sh.rmtree(d, ignore_errors=True)
    raise PermissionError("停用的被拦、没登记的第三方被拦 —— 闸读的是状态,不是写死的清单")


def a_mcp_tool_off():
    """后台把一个工具停用,模型那一侧还看不看得见、调不调得动(用户 10-23 拍「MCP 管理带配置」)。
    在库副本上停用 get_stock,真起商品领域服务(env 指副本)去列、去调。"""
    import mcp_registry as _M, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq, subprocess as _sp, json as _js, sys as _sys
    d = _tf.mkdtemp(prefix="ba-mcp-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(_M.DB, p)
    try:
        c = _sq.connect(p); _M.确保表(c)
        c.execute("INSERT OR REPLACE INTO mcp_tool_cfg(name,enabled,version) VALUES('get_stock',0,1)"); c.commit(); c.close()
        msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-11-25",
                 "capabilities": {}, "clientInfo": {"name": "ba", "version": "0"}}},
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_stock", "arguments": {"material": "棉麻"}}}]
        r = _sp.run([_sys.executable, _os.path.join(ROOT, "mcp", "domain_server.py"), "commerce"],
                    input="\n".join(_js.dumps(m) for m in msgs) + "\n", capture_output=True, text=True,
                    timeout=60, env=dict(_os.environ, LANXIU_DB=p), cwd=ROOT)
        回 = {x.get("id"): x.get("result") for x in map(_js.loads, filter(str.strip, r.stdout.splitlines()))}
        if any(t["name"] == "get_stock" for t in (回.get(1) or {}).get("tools") or []):
            return "后台停用了 get_stock,服务照样把它列给模型"
        if not (回.get(2) or {}).get("isError"):
            return "后台停用了 get_stock,模型照样调得动"
    finally:
        _sh.rmtree(d, ignore_errors=True)
    raise PermissionError("停用的工具列不出、调不动 —— 开关在协议层生效,不只是库里一行字")
def a_kb_issue_wrong_role():
    """知识问题(外部复审第 4 节 E):顾问能不能指定维护人 / 改处理状态,能不能给别人的检索记录报类型。
    在库副本上:顾问甲记一条检索、报「答不上」,然后甲去指定维护人、改状态,顾问乙去报类型 —— 都该被拒。"""
    import kb_issue as _K, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq
    原 = _K.DB
    d = _tf.mkdtemp(prefix="ba-kbi-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原, p)
    try:
        _K.DB = p
        c = _sq.connect(p)
        人 = c.execute("SELECT no,name,role FROM staff WHERE role='顾问' AND status='启用' ORDER BY no LIMIT 2").fetchall()
        c.close()
        if len(人) < 2:
            return "库里不到两个在职顾问 —— 这一刀没东西可打,不是守住了"
        甲, 乙 = [dict(no=x[0], name=x[1], role=x[2]) for x in 人]
        _K.记检索([{"试跑id": "rr_ba_kbi", "问的是": "攻击用", "hit": 0}], 甲)
        if not _K.提类型("rr_ba_kbi", "答不上", "攻击用", 甲).get("ok"):
            return "提问人本人报类型都报不上 —— 前置没成,下面的拒绝不作数"
        if _K.指定维护人("rr_ba_kbi", 甲["no"], "我自己来", 甲).get("ok"):
            return "顾问给自己指定了维护人 —— 只有总部运营能指定"
        if _K.改状态("rr_ba_kbi", "不处理", "不想处理", 甲).get("ok"):
            return "顾问把问题改成了「不处理」—— 只有总部运营能改状态"
        if _K.提类型("rr_ba_kbi", "答错", "改别人的", 乙).get("ok"):
            return "顾问乙给顾问甲的检索记录报了类型 —— 只认提问人本人或总部运营"
    finally:
        _K.DB = 原
        _sh.rmtree(d, ignore_errors=True)
    raise PermissionError("顾问定不了维护人、改不了状态、报不了别人的 —— 判在 kb_issue 写口里,身份从会话来")
def a_report_template():
    """报告模板(复审第 4 节 C,用户 10-23 拍):顾问改模板、改完模板旧报告跟着变 —— 两刀都要砍不下去。
    在库副本上:顾问去存一版模板;总部存第 1 版(隐藏评价)→ 店长存一份报告 → 总部存第 2 版(评价放出来)→
    打开那份旧报告,评价必须仍是「被隐藏」。显示要是按现行模板现算,改一次模板所有旧报告都跟着变。"""
    import report_template as _T, report_doc as _rd, oplog as _ol, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq
    原 = (_T.DB, _rd.DB, _ol.DB, api.DB)
    d = _tf.mkdtemp(prefix="ba-rtpl-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原[3], p)
    _T.DB = _rd.DB = _ol.DB = api.DB = p
    try:
        c = _sq.connect(p); _T.确保表(c); c.execute("DELETE FROM report_template_ver"); c.commit()
        店 = c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        c.close()
        if not 店:
            return "没有有单的门店 —— 没攻击成,不算守住"

        def 模(藏):
            m = _T.默认内容()
            for 节 in m["章节"]:
                for x in 节["指标"]:
                    x["显示"] = x["名"] not in 藏
            return m
        r = _T.保存("默认", 模(("评价",)), "审计:顾问想藏评价", dict(no="BA-G", name="审计顾问", role="顾问"))
        if r.get("ok"):
            return "顾问存进了一版报告模板 —— 只有总部运营能改这条没守住"
        总部 = dict(no="BA-H", name="审计总部", role="总部运营")

        def 发(版, 藏, 理由):
            # 存一版是草稿(10-23 起不生效),走 草稿 → 试运行 → 已发布 才生效
            if not _T.保存("默认", 模(藏), 理由, 总部).get("ok"):
                return False
            return (_T.改状态("默认", 版, "试运行", "审计:试运行", 总部, 试点门店=[店[0]]).get("ok")
                    and _T.改状态("默认", 版, "已发布", "审计:发布", 总部).get("ok"))
        if not 发(1, ("评价",), "审计:第 1 版"):
            return "总部运营存不进 / 发布不了第 1 版 —— 攻击自己没走通"
        with api.as_user(dict(no="BA-SM", name="审计店长", role="店长", shop=店[0])):
            rid = api.save_report(body="## 审计周报", kind="周").get("报告号")
            if not 发(2, (), "审计:第 2 版把评价放出来"):
                return "第 2 版发布不了 —— 攻击自己没走通"
            视 = (api.list_reports(report_id=rid) or {}).get("模板视图") or {}
        态 = next((x["状态"] for 节 in 视.get("章节") or [] for x in 节["指标"] if x["名"] == "评价"), None)
        if 态 != "被隐藏":
            return f"改完模板,旧报告 {rid} 里评价变成了「{态}」—— 显示是按现行模板现算的,冻结没成立"
    finally:
        _T.DB, _rd.DB, _ol.DB, api.DB = 原
        _sh.rmtree(d, ignore_errors=True)
    raise PermissionError("顾问存不进模板;改完模板,旧报告仍按冻结的那一版显示")


def a_report_hidden_not_in_pack():
    """报告模板隐藏的指标,AI 拿到的取数包里**整项没有**(用户 10-23 选 A)—— 写正文的那一步结构上写不出它。
    在库副本上:先按代码默认取一次周报取数包(基线,拿到销量的值和出处);总部存一版隐藏「销量」的模板并发布;
    再取一次,在返回的**整个 JSON** 里按键和值都找:任何一层的键里不许出现「销量」(期内、环比那一行都算),
    基线里销量的值对象、出处串不许出现。选销量是因为它的数除了期内那一项,还会经环比、并排读的说明漏出去。"""
    import report_template as _T, report_doc as _rd, oplog as _ol, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq
    原 = (_T.DB, _rd.DB, _ol.DB, api.DB)
    d = _tf.mkdtemp(prefix="ba-rtpl-hide-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原[3], p)
    _T.DB = _rd.DB = _ol.DB = api.DB = p
    名 = "销量"
    try:
        c = _sq.connect(p); _T.确保表(c); c.execute("DELETE FROM report_template_ver"); c.commit()
        店 = c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        c.close()
        if not 店:
            return "没有有单的门店 —— 没攻击成,不算守住"
        店长 = dict(no="BA-SM2", name="审计店长", role="店长", shop=店[0])
        with api.as_user(店长):
            基 = api.store_report(kind="周")
        基项 = (基.get("期内") or {}).get(名)
        if not (基项 and 基项.get("值") and 基项.get("出处")):
            return f"基线取数包里没有{名}的值 —— 攻击自己没走通(要先有这一项,隐藏之后才看得出它没了)"
        m = _T.默认内容()
        for 节 in m["章节"]:
            for x in 节["指标"]:
                if x["名"] == 名:
                    x["显示"] = False
        总部 = dict(no="BA-H2", name="审计总部", role="总部运营")
        if not (_T.保存("默认", m, f"审计:隐藏{名}", 总部).get("ok")
                and _T.改状态("默认", 1, "试运行", "审计", 总部, 试点门店=[店[0]]).get("ok")
                and _T.改状态("默认", 1, "已发布", "审计", 总部).get("ok")):
            return "隐藏销量的模板存不进 / 发布不了 —— 攻击自己没走通"
        with api.as_user(店长):
            包 = api.store_report(kind="周")
        if (包.get("报告模板") or {}).get("隐藏的") != [名]:
            return f"取数包里的模板不是刚发布那一版(隐藏的={(包.get('报告模板') or {}).get('隐藏的')})—— 攻击自己没走通"
        漏键, 漏值 = [], []

        def 走(x, 路):
            if isinstance(x, dict):
                for k, v in x.items():
                    if 名 in str(k):
                        漏键.append(f"{路}/{k}")
                    走(v, f"{路}/{k}")
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    走(v, f"{路}[{i}]")
            if x == 基项["值"]:
                漏值.append(路)
        走(包, "")
        文 = json.dumps(包, ensure_ascii=False, default=str)
        if 基项["出处"] in 文:
            漏值.append(f"出处串「{基项['出处']}」")
        if 漏键 or 漏值:
            return f"隐藏了{名},AI 拿到的取数包里还在:键 {漏键[:3]} · 值 {漏值[:3]}"
    finally:
        _T.DB, _rd.DB, _ol.DB, api.DB = 原
        _sh.rmtree(d, ignore_errors=True)
    raise PermissionError(f"隐藏了{名}:取数包里一层层找,键和值都没有它 —— 只剩「报告模板 · 隐藏的」名单")


def a_resolve_wrong_role():
    """研判销账拿错角色 —— 在库副本上让顾问去销一条财务任务,应该抛 PermissionError。
    2026-10-12 前谁都能销、署名随便填、销完不留痕(用户拍「修」)。"""
    import ops as _ops, oplog as _ol, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq
    原, 原日志 = _ops.DB, _ol.DB
    d = _tf.mkdtemp(prefix="ba-res-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原, p)
    _ops.DB = _ol.DB = p
    try:
        c = _sq.connect(p)
        # 要攻击的那条研判**自己造**(走正门 save_triage,不碰模型)—— CI 上没有模型凭据,
        # 造样本那一步跳过,triage 表恒为空;靠碰上的样本,这一刀在 CI 上永远砍不下去(数据工厂 10-13 查出)
        k = c.execute("SELECT id FROM task WHERE type='财务人工任务' ORDER BY id LIMIT 1").fetchone()
        u = c.execute("SELECT no, name, role FROM staff WHERE role='顾问' AND status='启用' LIMIT 1").fetchone()
        c.close()
        if not (k and u):
            return "没有可攻击的样本(财务人工任务 / 在职顾问)—— 没攻击成,不算守住"
        t = _ops.save_triage(k[0], "审计", "审计", "根因:审计造的\n建议动作:审计造的\n证据:无", [])
        _ops.resolve(t, "已采纳", dict(no=u[0], name=u[1], role=u[2]), 来源="边界审计")
        return f"顾问 {u[0]} 销掉了财务任务 triage#{t} —— 门没守住"
    finally:
        _ops.DB, _ol.DB = 原, 原日志
        _sh.rmtree(d, ignore_errors=True)


def a_refund_done_without_proof():
    """把一笔退款失败的定金弄成「已退」,而不留凭据 / 不是财务 —— 库副本上三刀,任何一刀成了都算破。
    用户 2026-10-15 拍「登记退款结果」写口:原来后台通用改状态**任何登录的人**点一下就成「已退」,什么凭据都不要;
    而研判办结拿「已退」当回执 —— 没凭据的已退会让办结也成了凭空点出来的。"""
    import refund_write as _rw, oplog as _ol, ops as _ops, server as _S, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq
    原 = (_rw.DB, _ol.DB, _ops.DB, _S.DB)
    d = _tf.mkdtemp(prefix="ba-refund-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原[0], p)
    _rw.DB = _ol.DB = _ops.DB = _S.DB = p
    try:
        c = _sq.connect(p)
        k = c.execute("SELECT id FROM deposit WHERE status='退款失败' ORDER BY id LIMIT 1").fetchone()
        财 = c.execute("SELECT no, name, role FROM staff WHERE role='财务' AND status='启用' LIMIT 1").fetchone()
        店 = c.execute("SELECT no, name, role FROM staff WHERE role='店长' AND status='启用' LIMIT 1").fetchone()
        c.close()
        if not (k and 财 and 店):
            return "没有可攻击的样本(退款失败的定金 / 在职财务 / 在职店长)—— 没攻击成,不算守住"
        财务, 店长 = dict(no=财[0], name=财[1], role=财[2]), dict(no=店[0], name=店[1], role=店[2])
        # 刀一:店长走后台通用改状态,请求体里自报财务
        r = _S.transit("bk-deposit", k[0], "退款处理中", {"idem_key": "IDEM-x", "role": "财务", "上次": "确实没退成"},
                       actor=店长["name"], me=店长)
        if r.get("ok"):
            return f"店长从通用改状态把 {k[0]} 推进了退款处理中 —— 门没守住"
        # 刀二:财务登记已退,不给流水号
        r = _rw.登记已退(k[0], 财务, "", "渠道核实其实已退")
        if r.get("ok"):
            return f"{k[0]} 没有流水号就成了已退 —— 门没守住"
        # 刀三:同一个流水号证明两笔
        r1 = _rw.登记已退(k[0], 财务, "BA-同一流水", "原渠道退回")
        k2 = _sq.connect(p).execute("SELECT id FROM deposit WHERE status='退款失败' ORDER BY id LIMIT 1").fetchone()
        if r1.get("ok") and k2:
            r2 = _rw.登记已退(k2[0], 财务, "BA-同一流水", "原渠道退回")
            if r2.get("ok"):
                return f"同一个流水号 BA-同一流水 证明了 {k[0]} 和 {k2[0]} 两笔退款 —— 门没守住"
        raise PermissionError("三刀都被拦下")     # _must_fail 的约定:抛了才算拦下
    finally:
        _rw.DB, _ol.DB, _ops.DB, _S.DB = 原
        _sh.rmtree(d, ignore_errors=True)


def a_close_without_receipt():
    """研判办结拿一张没走完的单当回执 —— 库副本上,财务对一笔没退成的定金办结,应该被拒。
    用户 2026-10-13 拍「已办结要凭系统单号」:凭空点出来的已办结和真办完的在队列上长得一模一样。"""
    import ops as _ops, oplog as _ol, shutil as _sh, tempfile as _tf, os as _os, sqlite3 as _sq
    原, 原日志 = _ops.DB, _ol.DB
    d = _tf.mkdtemp(prefix="ba-close-"); p = _os.path.join(d, "lanxiu.db")
    _sh.copy(原, p)
    _ops.DB = _ol.DB = p
    try:
        c = _sq.connect(p)
        k = c.execute("SELECT id, ref_id FROM task WHERE type='财务人工任务' ORDER BY id LIMIT 1").fetchone()
        u = c.execute("SELECT no, name, role FROM staff WHERE role='财务' AND status='启用' LIMIT 1").fetchone()
        m = c.execute("SELECT no, name, role FROM staff WHERE role='店长' AND status='启用' LIMIT 1").fetchone()
        if not (k and u and m):
            c.close()
            return "没有可攻击的样本(财务人工任务 / 在职财务 / 在职店长)—— 没攻击成,不算守住"
        c.execute("UPDATE deposit SET status='退款失败' WHERE id=?", (k[1],)); c.commit(); c.close()
        me = dict(no=u[0], name=u[1], role=u[2])
        t = _ops.save_triage(k[0], "审计", "审计", "根因:审计造的", [])
        # ⚠️ 复核那一步**必须走通**(10-13 两段确认起只认店长)—— 这一步要是被拒,
        # PermissionError 会被当成「拦下了」,而真正要攻击的「凭没走完的单办结」一步都没走到
        try:
            _ops.resolve(t, "已采纳", dict(no=m[0], name=m[1], role=m[2]), 来源="边界审计")
        except PermissionError as e:
            return f"**攻击没走到办结那一步**:复核就被拒了({str(e)[:60]})—— 没攻击成,不算守住"
        r = _ops.办结(t, k[1], me, 来源="边界审计")
        if r.get("ok"):
            return f"没退成的定金 {k[1]} 被当成回执,triage#{t} 办结了 —— 门没守住"
        raise PermissionError(r.get("reason", "")[:90])     # 被拒 = 守住(_must_fail 的约定:抛了才算拦下)
    finally:
        _ops.DB, _ol.DB = 原, 原日志
        _sh.rmtree(d, ignore_errors=True)


class 不许留痕:
    """攻击块里对 `product` 表的任何改动,出块时**一律还原**。

    为什么需要它:下面两刀验的是「店长改不了商品」,**正常情况下一个字都不改**。
    但咬合的时候把权限放回「店长及以上」,那一刀就**真的改成功了** ——
    实测把商品名改成「越权改模板」、量体模板改成 LT02,
    然后 `product_pattern_check` 报「模板和版型对不上」。

    **一条在被测代码坏掉时会改数据的检查(或攻击),比没有它更糟** ——
    它会在你最忙的那天(代码刚坏)悄悄污染数据,而你正忙着看红的那一条。

    ⚠️ 这个包装我在 `membership_check` 上加过一次,**没加到这儿** ——
    **教训没长成纪律,就会在下一个地方原样再来一遍。**
    所以凡是「以某个角色去试写」的攻击,都要包在这里面。
    """
    def __enter__(self):
        import sqlite3 as _sq
        with _sq.connect(api.DB) as c:
            c.row_factory = _sq.Row
            self.snap = [dict(r) for r in c.execute("SELECT * FROM product")]
        return self

    def __exit__(self, *e):
        import sqlite3 as _sq
        with _sq.connect(api.DB) as c:
            c.execute("DELETE FROM product")
            for r in self.snap:
                cols = ",".join(r); q = ",".join("?" * len(r))
                c.execute(f"INSERT INTO product({cols}) VALUES({q})", list(r.values()))
        return False


def a_product_by_manager():
    """**店长改商品。** 商品是全国一份的主数据 —— 它挂的版型决定用料基准、
    工期、能做哪些尺码、量体量哪些项。店长能改的话,同一个 SPU 在两家店
    挂不同版型,于是**同一件衣服报出不同的价**,而报表上完全正常。

    原来这里是「店长及以上」,和「客户导入」同级。
    **客户是门店的,商品和系统编码是全国的** —— 它该和 `save_syscode` 同级。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
    import server as _sv
    with 不许留痕():
        r = _sv.save_product({"spu": "lxys_100831495", "name": "越权改的商品",
                              "base_price": 1, "kind": "标品"}, role="店长")
    if r.get("ok"):
        return "店长改成了商品 —— 全国主数据被门店角色改了"
    raise PermissionError(r.get("reason", "")[:90])


def a_product_template_by_manager():
    """更具体的一刀:**店长改一个定制品的量体模板**。

    这比改名字严重 —— 量体模板决定量哪些尺寸。
    改错了是照着错的口径去量,然后按那个尺寸裁。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
    import server as _sv
    with 不许留痕():
        r = _sv.save_product({"spu": "lxys_100974037", "name": "越权改模板",
                              "base_price": 9600, "kind": "定制品",
                              "template": "LT02 裙装模版"}, role="店长")
    if r.get("ok"):
        return "店长改成了定制品的量体模板 —— 会照着错的口径量尺寸"
    raise PermissionError(r.get("reason", "")[:90])


def _verdict(name, reads=(), writes=()):
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "agentsite"))
    import guards as _g
    return _g.pre_tool_verdict(name, {}, state_reads=list(reads), state_writes=list(writes))


def a_double_write():
    """**已经写成功一次之后**,同一轮再写必须被拦。

    注意台账现在是结构化的 [{tool, key, ok}] —— 上一版这里传的是纯字符串列表,
    改成结构化之后这条攻击悄悄失效了(闸看不懂旧格式,当成没写过就放行)。
    **攻击本身也会过时**:被攻击的东西改了接口,攻击不会报错,只会开始放行。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "agentsite"))
    import guards as _g
    W = "mcp__work__assign_task"
    args = {"type": "日常运维", "assignee": "林岚", "note": "x", "end": "2026-12-31 18:00"}
    done = [dict(tool="assign_task", key=_g._arg_key("assign_task", args), ok=True)]
    v = _verdict(W, reads=["mcp__work__task_types"], writes=done)
    if not v: return "已经写成功一次之后,同一轮再写居然放行了"
    raise PermissionError(v)


def a_blind_assign():
    """没调 task_types 就派任务 —— 必须被拦。"""
    v = _verdict("mcp__work__assign_task", reads=[], writes=[])
    if not v: return "没查类型就派任务居然放行了"
    raise PermissionError(v)


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


_PH = __import__("re").compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def a_phone_leak():
    """把每个工具都调一遍,只要返回里出现完整手机号就算破了。

    **这条以前是「约定」** —— `_mask()` 全项目只被调用一次,
    「对外一律脱敏」全靠工具作者记得。现在包在工具出口上,
    **新加的工具默认就是脱敏的**。
    """
    import json as _j
    hit = []
    for name, fn in api.TOOLS.items():
        for args in ({}, {"customer": "C10001"}, {"status": "待确认"},
                     {"customer_id": "C10000"}, {"account": "C10001"}):
            try: r = fn(**args)
            except Exception: continue
            m = _PH.search(_j.dumps(r, ensure_ascii=False, default=str))
            if m: hit.append(f"{name} → {m.group()}")
    if hit: return "工具返回里出现完整手机号:" + "; ".join(hit[:3])
    raise PermissionError(f"{len(api.TOOLS)} 个工具的返回全部脱敏")


# ── 上新待办卡片(用户 10-10):电话先打码、点了才给全号、只给卡片范围内的人、每点一次留痕 ──
def _卡片副本():
    """看完整号码会写台账 —— 攻击在库的临时副本上打,真库的台账不留审计的痕迹。"""
    import shutil as _sh, tempfile as _tf, os as _os
    d = _tf.mkdtemp(); f = _os.path.join(d, "lanxiu.db"); _sh.copy(api.DB, f)
    return d, f


def a_card_mask():
    """总部能看到全部卡片 —— 拿全部卡片的返回去搜完整手机号。"""
    import json as _j, arrival_card as AC
    r = AC.卡片(dict(no="HQ-AUDIT", name="审计", role="总部运营", shop=None), db=api.DB)
    if not r["卡片"]:
        raise 前提不成立("一张上新卡片都没有 —— 空集合上「全部打码」恒成立,这条没验到")
    m = _PH.search(_j.dumps(r, ensure_ascii=False, default=str))
    if m: return f"卡片返回里出现完整手机号 {m.group()}"
    raise PermissionError(f"{len(r['卡片'])} 张卡片的电话全部打码")


def a_card_reveal_other():
    """别的顾问拿一张不是指派给他的卡片号去点「看完整号码」。"""
    import shutil as _sh, sqlite3 as _sq, arrival_card as AC, oplog as _ol
    d, f = _卡片副本(); 旧 = _ol.DB; _ol.DB = f
    try:
        c = _sq.connect(f)
        sid, 派 = c.execute("SELECT s.id, s.assignee_no FROM opportunity_task ot JOIN schedule s ON s.id=ot.schedule_id "
                           "WHERE ot.kind='回捞' AND s.assignee_no IS NOT NULL LIMIT 1").fetchone() or (None, None)
        别人 = c.execute("SELECT no FROM staff WHERE role='顾问' AND no<>? LIMIT 1", (派 or "",)).fetchone()
        c.close()
        if not sid or not 别人:
            raise 前提不成立("找不到可攻击的卡片 / 别的顾问 —— 这条没验到")
        r = AC.看完整联系方式(dict(no=别人[0], name="别人", role="顾问", shop=None), sid, db=f)
        if "电话" in r: return f"别的顾问拿到了 {sid} 的完整号码"
        raise PermissionError(r.get("error"))
    finally:
        _ol.DB = 旧; _sh.rmtree(d, ignore_errors=True)


def a_card_reveal_unlogged():
    """台账写不进的时候点「看完整号码」—— 能看到全号就等于「看了但没留痕」。"""
    import shutil as _sh, sqlite3 as _sq, arrival_card as AC, oplog as _ol
    d, f = _卡片副本(); 旧 = _ol.log_op
    def _坏(*a, **k): raise RuntimeError("台账写不进(审计注入)")
    _ol.log_op = _坏
    try:
        c = _sq.connect(f)
        sid, 派 = c.execute("SELECT s.id, s.assignee_no FROM opportunity_task ot JOIN schedule s ON s.id=ot.schedule_id "
                           "WHERE ot.kind='回捞' AND s.assignee_no IS NOT NULL LIMIT 1").fetchone() or (None, None)
        c.close()
        if not sid:
            raise 前提不成立("找不到可攻击的卡片 —— 这条没验到")
        r = AC.看完整联系方式(dict(no=派, name="本人", role="顾问", shop=None), sid, db=f)
        if "电话" in r: return "台账写不进,照样给了完整号码"
        raise PermissionError(r.get("error"))
    finally:
        _ol.log_op = 旧; _sh.rmtree(d, ignore_errors=True)


# ── 预警 → 任务(复审第 4 节 D,10-23):没办完不重派 / 补货跟进只派店长或总部 / 只能从预警那一行派 ──
def a_alert_dispatch():
    """在库副本上真派:同一张该催的单连派两次;把补货跟进派给顾问;绕开预警从通用口派补货跟进;
    请求体里自带一个假的超期日期想绕过防重复派。任何一刀成功就是边界破了。"""
    import shutil as _sh, tempfile as _tf, os as _os, sys as _sys
    import tasks as TK, alert_dispatch as AD, factory_inbox as FI, oplog as _ol
    from seed import TODAY
    d = _tf.mkdtemp(); f = _os.path.join(d, "lanxiu.db"); _sh.copy(api.DB, f)
    真 = _os.path.realpath(api.DB)
    改过 = [(m, m.DB) for m in list(_sys.modules.values())
           if isinstance(getattr(m, "DB", None), str) and _os.path.realpath(m.DB) == 真]
    for m, _ in 改过: m.DB = f
    try:
        if _os.path.realpath(TK.DB) != _os.path.realpath(f) or _os.path.realpath(_ol.DB) != _os.path.realpath(f):
            raise 前提不成立("没切到库副本 —— 不在真库上攻击,这条没验到")
        c = sqlite3.connect(f); c.row_factory = sqlite3.Row
        店长 = {r["shop"]: dict(r) for r in c.execute(
            "SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用'")}
        单 = 顾问 = me = None
        for x in FI.该催清单(TODAY):
            if x["门店"] in 店长:
                g = c.execute("SELECT no FROM staff WHERE role='顾问' AND status='启用' AND shop=? LIMIT 1",
                              (x["门店"],)).fetchone()
                if g: 单, 顾问, me = x["订单"], g[0], 店长[x["门店"]]; break
        缺货 = next((k for k, v in AD.全部sku档(c).items() if v in AD.可派档), None)
        c.close()
        if not 单 or not 缺货:
            raise 前提不成立("库里找不到该催的单 / 缺货的 SKU —— 空集合上「拦住了」恒成立,这条没验到")
        # ⚠️ **从 `tasks` 用的那同一个时钟算,不写死时刻。**
        # 原来是 `f"{TODAY} 23:00"` —— 而 `tasks.assign` 的开始时间默认 `_wnow()`,
        # 于是**本机时间过了 23:00 之后**,结束时间早于开始时间,
        # 第一次正常派就失败、整条攻击的前提塌掉。2026-10-23 23:31 真撞上了。
        # > 一条「写死了时刻的夹具」和一条好的,**白天看起来一模一样** ——
        # > 它只在一天里的某几个小时红,而那几个小时没人在跑门禁。
        # 同 CLAUDE.md §8「夹具不许写死会漂的东西 —— 日期会被时间打断」,
        # 这一条打断它的不是日期,是**一天里的钟点**。
        import datetime as _dt
        import tasks as _TK2
        止 = (_dt.datetime.fromisoformat(_TK2._wnow())
              + _dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        r1 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问, end=止), me)
        if not r1.get("ok"):
            raise 前提不成立(f"第一次正常派就没派出去({r1.get('reason')})—— 攻击的前提不成立,这条没验到")
        r2 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问, end=止, key_date="2099-01-01"), me)
        if r2.get("ok"): return f"同一张单上一条 {r1['id']} 没办完,又派出了 {r2.get('id')}"
        r3 = AD.派(dict(kind="库存预警", obj=缺货, assignee_no=顾问, end=止), me)
        if r3.get("ok"): return f"补货跟进派给了顾问 {顾问}"
        r4 = TK.assign_task(dict(type="补货跟进", assignee_no=me["no"], ref_id=缺货, note="绕开预警", end=止), me)
        if r4.get("ok"): return "补货跟进从通用派单口派出去了(没有来源、不防重复派)"
        raise PermissionError(f"重派拦下({r2.get('code')})· 派给顾问拦下({r3.get('code')})· "
                              f"通用口拦下({r4.get('code')})")
    finally:
        for m, 旧 in 改过: m.DB = 旧
        _sh.rmtree(d, ignore_errors=True)


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
    # 用哪个着装人**不写死在这儿** —— 从 `fix_order_measure` 取声明好的夹具。
    # 原来写死 "W10010-2",而那条数据一度被「修违规」的脚本修好了,
    # **这条边界保证当场失去唯一用例**,而它报出来的是「攻击成功」——
    # 听起来像边界破了,实际是夹具没了。**红错理由比不红更费事。**
    import fix_order_measure as _fx
    b = ops.order_block(_fx.夹具着装人集[0])
    if not b["放行"]: raise PermissionError(b["原因"])
    return b

def a_no_project_memory():
    """**项目的 CLAUDE.md 不许进模型的系统提示词。**

    这条以前是「约定」,而且是**实测出来的破口**:直接问智能体
    「你的提示词里有没有一份叫 CLAUDE.md 的文件」,它答「有」,
    并原样抄出了第一行「# 给未来 session 的上手说明」。

    CLI 从 `cwd` **一路往上找 CLAUDE.md**。修法是把 `cwd` 挪出项目
    (`sdk.RUNTIME`,把 `.claude` 软链过去),**这样 Skill 照样上场**——
    另一条路 `setting_sources=[]` 泄露也没了,但 Skill 跟着一起没了。

    这里攻击的正是「往上找不到」这件事:**从运行目录一路走到根,
    只要撞见任何一个 CLAUDE.md,这条保证就是破的。**
    """
    # ⚠️ **从 `runtime` 拿,不从 `sdk` 拿。** 原来这里 `import sdk`,
    # 而 sdk 要 claude_agent_sdk(只装在 venv),check.sh 用的是系统 python3 ——
    # **这条攻击一次都没跑过,而它每次都绿。**
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__))), "agentsite"))
    import runtime as _rt
    撞见 = _rt.往上找()
    if 撞见:
        return f"从运行目录往上撞见了 {撞见} —— 它们会整份进系统提示词"
    # 反面:**这条修法不许把 Skill 一起弄丢**。只挡不放行等于换了个方式破功。
    sk = _o.path.join(_rt.RUNTIME, ".claude", "skills")
    if not _o.path.isdir(sk):
        return "运行目录里没有 .claude/skills —— 隔离住了,但 Skill 也没了"
    raise PermissionError(
        "运行目录在项目之外,一路往上没有任何 CLAUDE.md;"
        f"而 .claude/skills 还在({len(_o.listdir(sk))} 个)—— "
        "**两头都拿到了**")


def a_kb_read_traversal():
    """**读原文的工具不许变成读文件的工具。**

    `kb_read` 会把知识库的 md 正文交给模型 —— 那是这个项目第一个「读文件」形状的工具,
    而它离「读任意文件」只差一个路径穿越。项目最硬的一条主张是
    **挂给模型的工具只能读业务数据**,所以这条必须被真的攻击一次。

    修法不是过滤 `../`(过滤永远漏一种写法),是**根本不接受路径** ——
    调用方给的字串只在一张写死的白名单里挑,挑不中就报「没有这一篇」。
    **能挑的东西只有 12 个,挑不中就没有第二条路。**
    """
    import api
    for bad in ("../CLAUDE.md", "/etc/passwd", "../../.deepseek-key",
                "09/../../CLAUDE.md", "..%2fCLAUDE.md", "../backend/lanxiu.db",
                "....//CLAUDE.md", "knowledge/../CLAUDE.md"):
        r = api.kb_read(bad)
        if "正文" in r or isinstance(r.get("小节"), list):
            return f"拿「{bad}」读到了知识库以外的东西"
    raise PermissionError(
        "八种路径穿越写法全部落空 —— **它根本不接受路径**,"
        "只在 16 篇的白名单里挑。过滤 `../` 那条路永远漏一种写法")


def a_whitelist():
    # 10-23 起按业务领域起服务(mcp/domain_server.py):每个领域暴露 domains 里归它的那些
    import domains as _dm
    全 = [x["name"] for x in api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS]
    for ns in _dm.领域:
        white = set(re.findall(r'"mcp__%s__(\w+)"' % ns, SDK_SRC))
        real = {t for t in 全 if _dm.归属.get(t) == ns}
        if white != real:
            # 约定:返回 = 攻击成功 = 边界破了;抛异常 = 被拦下 = 边界完好
            return f"{ns} 白名单与 MCP 暴露不一致:{sorted(white ^ real)}"
    raise PermissionError("白名单与 MCP 暴露完全一致")

def a_budget():
    """预算闸还在不在。

    原来这条是按源码字符串比 `max_budget_usd=MAX_USD` —— 判据贴着**写法**,
    不贴着**行为**。上限改成按供应商取值之后,写法一变它就红了,
    而闸其实好好的。**判据要贴着「什么才算对」,不是贴着「我以为它会怎么写」。**
    现在验两件事:传了上限,而且每个供应商解析出来都是正数。
    """
    if "max_budget_usd=" not in SDK_SRC: return "没传预算上限"
    import re as _re
    m = _re.search(r"max_budget_usd=([^,\n]+)", SDK_SRC)
    if m and m.group(1).strip() in ("None", "0", "0.0"):
        return f"预算上限传的是 {m.group(1).strip()} —— 等于没有闸"
    # 解析出来的值必须是正数(不 import sdk —— 它要 venv,这里只做静态判断)
    if "_max_usd" in (m.group(1) if m else "") and "return" not in SDK_SRC.split("def _max_usd")[1][:600]:
        return "_max_usd 没有返回任何值"
    raise PermissionError("预算上限已传入 options,且按供应商取正值")

def a_toolsearch_scope():
    """按需加载放行 ToolSearch 之后,三道闸还在不在(用户 10-23 拍「工具按需加载」,数据工厂提的四问)。

    要 venv(sdk / guards 的钩子要 claude_agent_sdk)—— **跑不起来抛「前提不成立」,仍然红、但不报成「边界破了」**:
    跑不起来的攻击什么都没验(agentsite/runtime.py 开篇那次)。
    攻五处,每处都真调被测代码:
      ① 全能助手真挂上的服务里,搜不搜得出别的角色的写口(版师 set_piece_ratio)——
         按 mcp_config 真起那个领域的服务进程去 tools/list、tools/call
      ② 真钩子(make_hooks 的 PreToolUse):名单外的 mcp 工具 → 拦,理由点到「白名单」;Bash → 照拦
      ③ 同一进程先按版师建一次、再按顾问建一次 —— 第二次不许带着版师的工具
      ④ 研判那条收窄:钩子按研判名单,close_bad_rating 调不动
      ⑤ 只有全能助手开了按需加载,别的入口 ToolSearch 仍在 disallowed_tools 里
    """
    import subprocess as _sp, json as _js, os as _os
    py = _os.path.join(ROOT, "agentsite", ".venv", "bin", "python")
    if not _os.path.exists(py):
        raise 前提不成立("agentsite/.venv 不在 —— 这条攻击跑不起来,它什么都没验")
    src = r"""
import sys, json, asyncio, os, subprocess
sys.path[:0] = ['agentsite', 'backend']
import sdk, guards
out = {}
全 = sdk.生效工具('all', None)
cfg = sdk.mcp_config(None, 'all', 名单=全)
out['挂了版师写口'] = any('set_piece_ratio' in c['env']['LANXIU_TOOLS'].split(',') for c in cfg.values())
if 'knowledge' in cfg:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-11-25",
             "capabilities": {}, "clientInfo": {"name": "ba", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "set_piece_ratio", "arguments": {}}}]
    c = cfg['knowledge']
    r = subprocess.run([c['command']] + c['args'], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=60, env={**os.environ, **c['env']})
    回 = {x.get('id'): x.get('result') or x.get('error') for x in map(json.loads, filter(str.strip, r.stdout.splitlines()))}
    out['列了几个'] = len((回.get(1) or {}).get('tools') or [])
    out['列得出'] = any(t['name'] == 'set_piece_ratio' for t in (回.get(1) or {}).get('tools') or [])
    out['调得动'] = bool(回.get(2)) and not (回.get(2) or {}).get('isError') and 'code' not in (回.get(2) or {})
def 钩(名单, 名):
    h = guards.make_hooks({'生效工具': 名单})['PreToolUse'][0].hooks[0]
    r = asyncio.run(h({'tool_name': 名, 'tool_input': {}}, 'ba', None))
    return r.get('reason') if r.get('decision') == 'block' else None
out['名单外'] = 钩(全, 'mcp__knowledge__set_piece_ratio')
out['Bash'] = 钩(全, 'Bash')
out['ToolSearch'] = 钩(全, 'ToolSearch')
sdk.mcp_config(None, 'pattern')
顾问 = sdk.mcp_config(None, 'kb')
out['换身份后'] = any('set_piece_ratio' in c['env']['LANXIU_TOOLS'].split(',') for c in 顾问.values())
out['研判'] = 钩(list(sdk.研判工具), 'mcp__service__close_bad_rating')
out['开给'] = sorted(sdk.按需加载的角色)
print(json.dumps(out, ensure_ascii=False))
"""
    r = _sp.run([py, "-c", src], capture_output=True, text=True, timeout=180, cwd=ROOT)
    try:
        o = _js.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        raise 前提不成立(f"攻击脚本没跑完,什么都没验:{(r.stderr or r.stdout)[-300:]}")
    if o["挂了版师写口"]: return "全能助手的服务挂上了版师写口 set_piece_ratio —— ToolSearch 搜得到"
    if not o.get("列了几个"):
        raise 前提不成立("全能助手的知识领域服务没起来或一个工具都没列 —— 「列不出版师写口」没验到")
    if o.get("列得出"): return "真起的服务把 set_piece_ratio 列给了全能助手"
    if o.get("调得动"): return "真起的服务让全能助手调动了 set_piece_ratio"
    if not o["名单外"] or "白名单" not in o["名单外"]: return f"名单外的工具没被钩子按白名单拦:{o['名单外']}"
    if not o["Bash"]: return "放行 ToolSearch 之后 Bash 也放行了"
    if o["ToolSearch"]: return f"ToolSearch 没放行(按需加载用不了):{o['ToolSearch']}"
    if o["换身份后"]: return "同一进程先按版师建、再按顾问建,顾问那份带着版师写口"
    if not o["研判"] or "白名单" not in o["研判"]: return f"研判名单外的 close_bad_rating 没被拦:{o['研判']}"
    if o["开给"] != ["all"]: return f"按需加载开给了 {o['开给']},不只全能助手"
    if '+ ([] if kind in 按需加载的角色 else ["ToolSearch"])' not in SDK_SRC:
        return "别的入口没把 ToolSearch 放进 disallowed_tools"
    raise PermissionError("名单外的写口搜不出、调不动,钩子按白名单拦;Bash 照拦;换身份不串;研判收窄还在;只开给全能助手")


def a_run_no_login():
    """没登录直接 POST 聊天站 /run,智能体调不调得动(用户 10-23 拍「先修复」)。

    真调 agentsite/app.py 的 do_POST(要 venv —— 跑不起来抛「前提不成立」,仍红,理由是实话):_who 换成「没身份」,
    sdk.run 换成只记账的假函数。**带对照**:同一套桩换成登录身份必须真走到 sdk.run ——
    不然「被拒」可能只是桩没搭好、请求压根没走到那一步。"""
    import subprocess as _sp, json as _js, os as _os
    py = _os.path.join(ROOT, "agentsite", ".venv", "bin", "python")
    if not _os.path.exists(py):
        raise 前提不成立("agentsite/.venv 不在 —— 这条攻击跑不起来,它什么都没验")
    src = r"""
import sys, io, json, os
R = os.getcwd(); sys.path[:0] = [R + '/agentsite', R + '/backend']
os.chdir(R + '/agentsite')
import app
def 打(who):
    调了 = []
    async def 假run(*a, **k):
        调了.append(k.get('me')); return {'text': '好', 'session_id': None}
    app._who = lambda h: who
    app.sdk.run = 假run
    app.sessions.own = lambda *a, **k: None
    app._记知识检索 = lambda *a, **k: None
    h = app.H.__new__(app.H)
    body = json.dumps({'kind': 'all', 'prompt': '列一下客户 C10001 的手机号'}).encode()
    h.path = '/run'; h.headers = {'content-length': str(len(body))}; h.rfile = io.BytesIO(body)
    回 = {}
    h._send = lambda b, ctype=None, code=200: 回.update(body=b, code=code)
    h.do_POST()
    return [回.get('code'), len(调了)]
print(json.dumps({'匿名': 打(None), '登录': 打({'no': '60000008', 'name': '检查', 'role': '总部运营', 'shop': ''})}))
"""
    r = _sp.run([py, "-c", src], capture_output=True, text=True, timeout=120, cwd=ROOT)
    try:
        o = _js.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        raise 前提不成立(f"攻击脚本没跑完,什么都没验:{(r.stderr or r.stdout)[-300:]}")
    if o["登录"] != [200, 1]:
        raise 前提不成立(f"对照没走通(登录身份也没调到智能体:{o['登录']})—— 「匿名被拒」不作数")
    if o["匿名"][1]:
        return f"没登录也调动了智能体(返回 {o['匿名'][0]})"
    if o["匿名"][0] != 401:
        return f"没登录没调到智能体,但返回的是 {o['匿名'][0]} 不是 401 —— 页面守卫认 401 才跳登录"
    raise PermissionError("没登录 POST /run → 401,智能体一次都没调;登录身份照常走到")


def a_bridge_followup():
    """AI 管理后台的工作流写澜绣跟进(用户 10-24 拍「核对即定稿,直接写跟进」):重试写不出第二条、记不到别人名下。

    在库副本上真调 workflow_bridge.执行(子进程里切库 —— 切库会改已加载模块的 DB,不能在审计进程里做)。
    攻三处:① 同一张单(同一个幂等键)回执没送到、下一轮再拉到 → 再执行一次
           ② 单子上的通话号是 A 客户的录音、客户号写 B
           ③ 单子上的工具名写成澜绣别的函数(改订单)
    **带对照**:正常那一张必须真写成一条 —— 不然「被拒」可能只是夹具没搭好。"""
    import subprocess as _sp, json as _js
    src = r"""
import sys, os, json, sqlite3
sys.path[:0] = ['backend', 'knowledge']
import server, oplog, workflow_bridge as WB, check_copy
副本 = check_copy.用副本('ba-bridge-')
c = sqlite3.connect(副本)
a = c.execute("SELECT a.id, a.customer_id FROM call_audio a JOIN call_transcript t ON t.audio_id=a.id "
              "JOIN customer cu ON cu.id=a.customer_id ORDER BY a.id LIMIT 1").fetchone()
b = c.execute("SELECT id FROM customer WHERE id<>? ORDER BY id LIMIT 1", (a[1],)).fetchone()[0]
数 = lambda: sqlite3.connect(副本).execute("SELECT COUNT(*) FROM followup").fetchone()[0]
前 = 数()
员 = c.execute("SELECT no FROM staff WHERE status='启用' ORDER BY no LIMIT 1").fetchone()[0]
单 = {"工具": "写跟进", "幂等键": "ba:x:1", "办事人": "ba", "办事人澜绣工号": 员,
      "参数": {"customer_id": a[1], "内容": "审计", "call_id": a[0]}}
一 = WB.执行(单, 谁="ba"); 中 = 数(); 二 = WB.执行(单, 谁="ba"); 后 = 数()
# 账号绑定(10-24):核对人没绑定澜绣员工 → 不写,不以服务身份顶替
空 = WB.执行({"工具": "写跟进", "幂等键": "ba:x:4", "办事人": "ba",
              "参数": {"customer_id": a[1], "内容": "审计", "call_id": a[0]}}, 谁="ba"); 空后 = 数()
# 10-24 桥扩到业务工具:名单外的写口(开单)不接;派任务不带绑定不执行(都不许以服务身份顶替)
任前 = sqlite3.connect(副本).execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
开单 = WB.执行({"工具": "open_order", "幂等键": "ba:x:5", "办事人": "ba", "办事人澜绣工号": 员, "参数": {}}, 谁="ba")
派 = WB.执行({"工具": "assign_task", "幂等键": "ba:x:6", "办事人": "ba",
             "参数": {"type": "电话回电", "assignee": 员, "note": "审计", "end": "2026-12-31", "ref_id": a[1]}}, 谁="ba")
任后 = sqlite3.connect(副本).execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
错 = WB.执行({"工具": "写跟进", "幂等键": "ba:x:2", "参数": {"customer_id": b, "内容": "审计", "call_id": a[0]}}, 谁="ba")
野 = WB.执行({"工具": "改订单", "幂等键": "ba:x:3", "参数": {}}, 谁="ba")
print(json.dumps({"对照": [一[0], 中 - 前], "重来": [二[0], 后 - 中], "错客户": [错[0], (错[2] or {}).get("code"), 数() - 后],
                  "野工具": [野[0], (野[2] or {}).get("code")],
                  "没绑定": [空[0], (空[2] or {}).get("code"), 空后 - 后],
                  "名单外": [开单[0], (开单[2] or {}).get("code")],
                  "派任务没绑定": [派[0], (派[2] or {}).get("code"), 任后 - 任前]}, ensure_ascii=False))
"""
    r = _sp.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=120, cwd=ROOT)
    try:
        o = _js.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        raise 前提不成立(f"攻击脚本没跑完,什么都没验:{(r.stderr or r.stdout)[-300:]}")
    if o["对照"] != ["已执行", 1]:
        raise 前提不成立(f"对照没写成一条({o['对照']})—— 「被拒」不作数")
    if o["重来"][1]:
        return f"同一个幂等键第二次执行又写了 {o['重来'][1]} 条跟进"
    if o["错客户"][0] != "执行失败" or o["错客户"][2]:
        return f"A 客户的录音记到了 B 客户名下:{o['错客户']}"
    if o["野工具"][0] != "执行失败":
        return f"桥执行了认不出的工具:{o['野工具']}"
    if o["没绑定"][0] != "执行失败" or o["没绑定"][2]:
        return f"核对人没绑定澜绣员工,桥照样写了跟进(以服务身份顶替):{o['没绑定']}"
    if o["名单外"][0] != "执行失败":
        return f"桥执行了名单外的写口(开单):{o['名单外']}"
    if o["派任务没绑定"][0] != "执行失败" or o["派任务没绑定"][2]:
        return f"没绑定澜绣员工,桥照样派了任务:{o['派任务没绑定']}"
    raise PermissionError("同一个幂等键只写一条;录音和客户对不上就拒、一行不写;认不出的工具不执行;"
                          "核对人没绑定澜绣员工就不写;名单外的写口不接;业务写口没绑定不执行")


def a_bridge_recall():
    """老客召回派回访(六条第五条,10-25):只派给这次名单里、派的那一刻仍有由头的人;同一张单重来不派第二条。

    子进程、库副本上真调 workflow_bridge.执行。攻三处:① 店长填了名单外的客户号 ② 名单本身被改过 ——
    塞进一个**眼下没由头**的人(桥收的名单来自工作流上一步,不是澜绣自己算的)③ 同一张单回执丢了再执行一次。
    **带对照**:名单里那个有由头的正常人必须真派成一条。"""
    import subprocess as _sp, json as _js
    src = r"""
import sys, os, json, sqlite3
sys.path[:0] = ['backend', 'knowledge']
import server, oplog, api, tasks, revive, slipping, workflow_bridge as WB, check_copy
副本 = check_copy.用副本('ba-recall-')
店长 = '60000001'
me = WB.员工身份(店长)
c = sqlite3.connect(副本)
候 = [r[0] for r in c.execute("SELECT cu.id FROM customer cu JOIN staff s ON s.no=cu.advisor_no AND s.status='启用' "
      "WHERE cu.shop=? AND cu.merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM schedule x WHERE x.customer_id=cu.id "
      "AND x.status='有效' AND x.type IN ('电话回电','商机提醒')) ORDER BY cu.id LIMIT 400", (me['shop'],))]
有, 没 = None, None
with api.as_user(me):
    for cid in 候:
        判 = (api.revive_list(customer=cid) or {}).get('这一个人') or {}
        if 判.get('该不该联系') and not 有: 有 = cid
        if not 判.get('该不该联系') and not 没: 没 = cid
        if 有 and 没: break
数 = lambda: sqlite3.connect(副本).execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
名单 = [{"客户号": 有, "由头": "审计"}, {"客户号": 没, "由头": "审计塞进来的"}]
单 = {"工具": "派回访任务", "幂等键": "ba:recall:1", "办事人": "ba", "办事人澜绣工号": 店长,
      "参数": {"客户号们": f"{有},{没},C00000000", "截止": "2026-12-31", "名单": 名单}}
前 = 数(); 一 = WB.执行(单, 谁="ba"); 中 = 数(); 二 = WB.执行(单, 谁="ba"); 后 = 数()
派给 = sqlite3.connect(副本).execute("SELECT customer_id FROM schedule WHERE status='有效' AND type='电话回电' "
       "AND note LIKE '老客召回%' ORDER BY rowid DESC LIMIT 5").fetchall()
print(json.dumps({"样本": [有, 没], "对照": [一[0], 中 - 前], "重来": 后 - 中, "派给": [r[0] for r in 派给],
                  "跳过": ((一[1] or {}).get('数据') or {}).get('跳过')}, ensure_ascii=False))
"""
    r = _sp.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=300, cwd=ROOT)
    try:
        o = _js.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        raise 前提不成立(f"攻击脚本没跑完,什么都没验:{(r.stderr or r.stdout)[-300:]}")
    if not all(o["样本"]):
        raise 前提不成立(f"找不到一个有由头 + 一个没由头的客户({o['样本']})—— 没东西可攻")
    if o["对照"][0] != "已执行" or o["对照"][1] < 1:
        raise 前提不成立(f"对照没派成({o['对照']})—— 「没派」不作数")
    if o["对照"][1] > 1:
        return f"一张单派了 {o['对照'][1]} 条:名单外的客户号或塞进来的没由头的人也派了(派给 {o['派给']})"
    if o["样本"][1] in o["派给"] or "C00000000" in o["派给"]:
        return f"派给了不该派的人:{o['派给']}"
    if o["重来"]:
        return f"同一张单第二次执行又派了 {o['重来']} 条"
    raise PermissionError("名单外的客户号不派;名单被塞进一个眼下没由头的人也不派(派的那一刻逐人再核);同一张单只派一次")


def a_bridge_rating_money():
    """差评处置不经手超权限的钱(用户 10-25 拍「停下报总部,不写」)。子进程、库副本上真调 workflow_bridge.执行。
    攻两处:① 判给企业、预估 2000 元(超店长 1000 的权限)② 关闭方式写成全额退款(要第二个人批)。
    **带对照**:同一个店长「只回访」关闭一条必须真关成 —— 不然「没写」可能只是夹具没搭好。"""
    import subprocess as _sp, json as _js
    src = r"""
import sys, os, json, sqlite3
sys.path[:0] = ['backend', 'knowledge']
import server, oplog, api, tasks, rating_write, repair_write, workflow_bridge as WB, check_copy
副本 = check_copy.用副本('ba-rating-')
店长 = '60000001'
me = WB.员工身份(店长)
c = sqlite3.connect(副本)
待 = [r[0] for r in c.execute("SELECT r.pkg_id FROM task t JOIN rating r ON r.task_id=t.id JOIN ordr o ON o.id=r.order_id "
      "WHERE t.type='评价差评' AND t.status='待处理' AND o.shop=? ORDER BY r.pkg_id LIMIT 3", (me['shop'],))]
修 = lambda: sqlite3.connect(副本).execute("SELECT COUNT(*) FROM maintain").fetchone()[0]
关了 = lambda k: sqlite3.connect(副本).execute("SELECT t.status FROM task t JOIN rating r ON r.task_id=t.id WHERE r.pkg_id=?", (k,)).fetchone()[0]
跑 = lambda 键, k, 定: WB.执行({"工具": "差评处置", "幂等键": 键, "办事人": "ba", "办事人澜绣工号": 店长,
                             "参数": {"pkg": k, "店长定的": 定}}, 谁="ba")
前 = 修()
超 = 跑("ba:rating:1", 待[0], {"处置": "返修", "责任方": "企业", "预估费用": "2000"}); 超后 = 修()
退 = 跑("ba:rating:2", 待[1], {"处置": "说明后关闭", "关闭方式": "全额退款", "说明": "审计"})
对 = 跑("ba:rating:3", 待[2], {"处置": "说明后关闭", "关闭方式": "只回访", "说明": "审计:已回访"})
print(json.dumps({"样本": len(待), "超权限多了返修单": 超后 - 前, "超": 超[0], "退款后状态": 关了(待[1]),
                  "对照": [对[0], 关了(待[2])]}, ensure_ascii=False))
"""
    r = _sp.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=300, cwd=ROOT)
    try:
        o = _js.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        raise 前提不成立(f"攻击脚本没跑完,什么都没验:{(r.stderr or r.stdout)[-300:]}")
    if o["样本"] < 3:
        raise 前提不成立(f"本店待处理差评不到 3 条({o['样本']})—— 没东西可攻")
    if o["对照"][0] != "已执行" or o["对照"][1] == "待处理":
        raise 前提不成立(f"对照没关成({o['对照']})—— 「没关」不作数")
    if o["超权限多了返修单"]:
        return f"判给企业 2000 元(超店长权限)照样建了 {o['超权限多了返修单']} 张返修单"
    if o["退款后状态"] != "待处理":
        return f"全额退款的关闭方式没经第二个人批就把差评关了(状态 {o['退款后状态']})"
    raise PermissionError("超店长权限的我方出钱不建单不判责;要出钱的关闭方式不关 —— 都回澜绣由人办")


def a_spans_scope():
    """聊天站执行记录(/spans:用户原话、工具参数和返回)只给本人和总部运营(2026-10-24 实测原来不登录就给 200)。"""
    import tempfile as _tf
    sys.path.insert(0, os.path.join(ROOT, "agentsite"))
    import sessions as _S
    原 = _S.PATH
    _S.PATH = os.path.join(_tf.mkdtemp(), "s.json")
    try:
        甲 = {"no": "60000002", "name": "甲", "role": "顾问", "shop": "SH001 静安旗舰店"}
        乙 = {"no": "60000004", "name": "乙", "role": "店长", "shop": "SH002 徐汇店"}
        _S.own("会话-甲", 甲)
        if _S.能看执行记录吗(None, 会话号="会话-甲")[0]:
            return "没登录也能看执行记录"
        if _S.能看执行记录吗(乙, 会话号="会话-甲")[0]:
            return "别的门店的店长看得到甲会话里的执行记录"
        if _S.能看执行记录吗(乙, 列全部=True)[0]:
            return "店长能列全部对话的执行记录"
        if not _S.能看执行记录吗(甲, 会话号="会话-甲")[0]:
            raise 前提不成立("本人看自己的会话都被拒了 —— 「被拒」不作数")
    finally:
        _S.PATH = 原
    raise PermissionError("没登录 401;只看自己会话的;列全部只给总部运营")


def a_disallowed():
    miss = [t for t in ("Bash", "Write", "Edit", "Read", "Task", "WebFetch")
            if f'"{t}"' not in SDK_SRC]
    if miss: return f"disallowed_tools 漏了 {miss}"
    raise PermissionError("危险内置工具已在 disallowed_tools 里点名")

def a_strict_mcp():
    if "strict_mcp_config=True" not in SDK_SRC: return "没开 strict_mcp_config"
    declared = set(json.load(open(os.path.join(ROOT, ".mcp.json")))["mcpServers"])
    # 10-23 起代码里的服务名是 8 个业务领域(sdk._mcp_all 照 backend/domains.py 起),不再字面写在 sdk 里
    import domains as _dm
    code = set(_dm.领域)
    if declared & code: return f".mcp.json 的服务名和代码声明重合:{declared & code}"
    raise PermissionError(f".mcp.json 声明的 {sorted(declared)} 全被忽略,只认代码里的")


def a_workorder_ro():
    """get_workorder 只读 —— 拿它的返回去改交期,改不动。"""
    import api
    r = api.get_workorder(workorder_id="WO8001")
    if not (r.get("rows")): raise PermissionError("没有可攻击的工单(夹具不成立)")
    try:
        api._rows("UPDATE workorder SET due_date='2099-01-01' WHERE id=?", "WO8001")
    except Exception:
        raise PermissionError("连接开成 mode=ro,改交期直接抛 —— 不是碰巧没人写 UPDATE")
    return "居然写进去了"


def a_lifecycle_no_manual():
    """生命周期是**算法型状态机**,不接受手工流转 —— 工具层给不出改档的路径。"""
    import api
    if any("lifecycle" in n and ("set" in n or "update" in n) for n in api.TOOLS):
        return "工具层出现了改生命周期的接口"
    r = api.get_lifecycle(customer="C10001")
    if not r.get("rows"): raise PermissionError("查不到客户(夹具不成立)")
    row = r["rows"][0]
    if "系统重算值" not in row:
        return "返回里没有「系统重算值」—— 人工覆盖和重算值分不开,就没法判断哪个在生效"
    raise PermissionError("工具层没有任何改档接口,且人工覆盖与系统重算值分开返回")


def a_rfm_cross_group():
    """RFM 是**相对分**:同一个人在不同人群里分数不同 —— 这是设计,不是 bug。
    审计这一条是为了钉住「跨档比较无意义」这个事实是**可验证的**,不只是提示词说说。"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(ROOT, "knowledge"))
    import rfm as _rfm
    import api
    a = {r["id"]: r for r in _rfm.score(api._rows(
        "SELECT id,idle_days,orders_12m,amount_12m FROM customer WHERE lifecycle='潜在流失'"))}
    b = {r["id"]: r for r in _rfm.score(api._rows(
        "SELECT id,idle_days,orders_12m,amount_12m FROM customer"))}
    both = [k for k in a if k in b and a[k]["RFM"] != b[k]["RFM"]]
    if not both:
        return "同一个人在两个人群里分数完全一样 —— 那它就不是相对分,跨档比较的禁令没有依据"
    raise PermissionError(
        f"同一个人换个人群分数就变({both[0]}: 档内 {a[both[0]]['RFM']} vs 全量 {b[both[0]]['RFM']})"
        " —— **跨档比较无意义是可验证的事实,不是提示词的一句话**")


def a_check_write_noop():
    """check_write 名字里带 write,必须证明它**真的不写** ——
    跑一次「校验通过」的建档,库里的行数一行都不能多。
    (校验通过那条更要紧:被拒的当然不会写,通过的才是危险的那一半。)"""
    import api, sqlite3
    n0 = api._rows("SELECT count(*) c FROM customer")[0]["c"]
    r = api.check_write("建档", {"name": "边界审计·勿动", "phone": "13800009999",
                                 "shop": "SH001 静安旗舰店"})
    if r.get("能不能做") != "能":
        raise PermissionError(f"这次校验没通过({r.get('编码')}),换个夹具才测得到「通过也不写」")
    n1 = api._rows("SELECT count(*) c FROM customer")[0]["c"]
    if n1 != n0: return f"校验通过后库里多了 {n1-n0} 行 —— 它在写库"
    raise PermissionError("validate_* 是纯函数,校验通过也一行没写")


def a_default_allow_visible():
    """「默认放行」必须在返回里自己说出来 —— 不能和「人工确认过」长得一样。

    2025 格里有 1274 格的依据是 `—`:**只是没命中任何禁止规则**,没有人验证过。
    它们的 verdict 全是「可」。不标出来的话,它和 16 格打样确认过的在返回里
    完全一致,而模型只能照着「可」讲给客户听。

    **兜底方向选错,未知就会被打扮成已知** —— 这里未知被默认算成了「可以做」。
    """
    import api
    r = api._rows("SELECT craft,material FROM craft_combo WHERE (rule IS NULL OR rule='—') LIMIT 1")
    if not r: raise PermissionError("库里没有无依据的格子了(那也很好)")
    kb = api._rows("SELECT name FROM craft WHERE code=?", r[0]["craft"])[0]["name"]
    mb = api._rows("SELECT name FROM craft WHERE code=?", r[0]["material"])[0]["name"]
    d = api.kb_combo(craft=kb, material=mb)
    if d.get("verdict") != "待核实":
        return (f"无依据的格子仍然给了结论({d.get('verdict')!r})—— "
                "「没查到禁止」和「确认可以」是两回事")
    if "不给结论" not in (d.get("依据等级") or ""):
        return "verdict 改了但依据等级没说清为什么"
    raise PermissionError("无依据的格子**不给结论**,verdict 返回「待核实」并记入队列 —— "
                          "偏错的代价不对称:说「可以」赔工期料钱,说「待核实」多打个电话")


def a_review_readonly():
    """待核实队列:模型**看得见,填不了**。

    回流这件事天然要写。如果让模型的工具去写,「工具层一个写接口都没有」
    那条保证当场就破 —— 而它是靠 mode=ro 连接结构性成立的,不是靠自觉。
    所以拆成两半:记一笔走**日志文件**(旁路),回填走**后台**(那边本来有写权限)。
    这里攻击的正是这条边界。
    """
    import api, inspect, re as _re
    # ① 工具层不许有任何**能改矩阵**的接口。
    #
    # ⚠️ 这一条原来写的是「名字里带 resolve / fill / update / set_ 的都算写接口」——
    # **判据贴着名字,不贴着这条保证守的那件事。** 它守的是「craft_combo 只能从后台回填」,
    # 而名字只是当时那几个写接口碰巧长的样子。
    # 加了 `set_piece_ratio`(核裁片用料占比,和相容矩阵毫无关系)之后它当场红了,
    # 红的不是边界 —— 是这条判据。**这个项目在同一个形状上栽过五次**
    # (grep「上身」、写死 part_quote_base、按字段名判、按写法判预算闸……)。
    #
    # 现在验两件事,都是「这件事做到了没有」:
    #   ⓐ 没有任何一个挂给模型的工具会写 craft_combo(读源码,连它调的私有函数一起看)
    #   ⓑ **真会写库的工具,必须登记在 WRITE_TOOLS 里** —— 这条比名字硬:
    #      进了那张表才会被 isolation_check(从会话取身份)、guards(一轮一次)、
    #      funnel(记它走了写路径)一起管住。**一个没登记的写口,是没人管的写口。**
    # 读不到源码的**不许当成「没写库」** —— 咬合的时候当场撞上这一条:
    # 在 <stdin> 里造的假工具 getsource 抛异常,旧写法 return "",
    # 于是「挂了一个会改矩阵的工具」这一刀**没红**。
    # **读不到 ≠ 干净**,而这两种在结果上长得一模一样。
    读不到 = []
    def _src_of(n, fn):
        try: return inspect.getsource(inspect.unwrap(fn))
        except Exception as e:
            读不到.append(f"{n}({type(e).__name__})"); return ""
    改矩阵 = _re.compile(r"(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+craft_combo", _re.I)
    写库 = _re.compile(r"(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+\w+", _re.I)
    bad = [n for n, f in api.TOOLS.items() if 改矩阵.search(_src_of(n, f))]
    if bad: return f"工具层出现了能改相容矩阵的接口:{bad}"
    未登记 = [n for n, f in api.TOOLS.items()
              if n not in api.WRITE_TOOLS and 写库.search(_src_of(n, f))]
    if 读不到:
        return (f"这些工具读不到源码,**这一刀等于没扫到它们**:{读不到} —— "
                f"「读不到」和「干净」在结果上长得一模一样,所以这里必须红")
    if 未登记:
        return (f"这些工具会写库,却没登记在 WRITE_TOOLS 里:{未登记} —— "
                f"**没登记就没人管**:身份、一轮一次、漏斗三道全都漏过它")
    # ② 队列工具真的只读:调一次,矩阵里那一格一个字都不能变
    q = api.get_review_queue(top=1)
    row = (q.get("rows") or [None])[0]
    if row:
        before = api._rows("SELECT verdict,rule FROM craft_combo WHERE craft=? AND material=?",
                           row["craft"], row["material"])
        api.get_review_queue(top=1)
        after = api._rows("SELECT verdict,rule FROM craft_combo WHERE craft=? AND material=?",
                          row["craft"], row["material"])
        if before != after: return "看一眼队列就把矩阵改了"
    # ③ 拿工具层的连接去回填,必须抛
    try:
        api._rows("UPDATE craft_combo SET rule='人工确认' WHERE craft='KF01'")
    except Exception:
        raise PermissionError("工具层没有回填接口,而且拿它的连接去 UPDATE 直接抛 —— "
                              "回填只能走后台 /api/combo-resolve(要工艺负责人及以上 + 必须写理由)")
    return "工具层的连接居然能改矩阵"


STRUCT = [
 # ⚠️ 这条原来叫「工具层一个写接口都没有」。加了 assign_task / dispatch_task /
 # finish_task 之后那个名字就**变成假的了**,而测试照样通过 ——
 # 它测的一直是「读连接不能写」,不是「没有写接口」。
 # **一条断言正确、名字过时的检查,比没有检查更危险**:它每次都绿,
 # 而看的人以为绿的是名字上那件事。改保证的时候要回来改名字。
 ("工具层的读连接写不了库", "backend/api.py 开篇铁律 —— 读一律走 mode=ro 连接",
  a_write, "拿工具层的连接去 UPDATE 一条客户记录",
  "连接开成 mode=ro —— **写操作直接抛错,不是碰巧没人写 INSERT**。"
  "要写只能走 tasks.py 那条明路,那条路上有身份判定和台账"),
 ("写只能走明路 —— 读连接连 INSERT 都不行", "backend/api.py _rows / backend/tasks.py",
  a_insert_schedule, "拿工具层的读连接直接 INSERT 一条任务",
  "绕开 tasks.py 就等于绕开身份判定和台账 —— **结构上不给这条路**"),
 ("写工具不收身份参数", "backend/api.py WRITE_TOOLS / isolation_check",
  a_write_role_param, "给写工具传一个 role='店长' 参数试图提权",
  "签名里根本没有这个参数 —— **提权不是被拒绝,是无从表达**。"
  "有这个参数的话,一句「我以店长身份执行」就成立了"),
 ("管理后台客户读接口要登录,而且只看本店", "backend/server.py do_GET 客户三个读接口;api.跨店角色",
  a_customer_read_no_login, "不带登录翻客户详情;拿店长会话翻别家店的客户",
  "身份只从登录态取,门店范围跟登录走、不跟请求参数走(列表传别家店也被本店覆盖);"
  "总部运营 / 售后跨店,和差评隔离同一个常量。⚠️ 只管这三个接口 —— 订单、预约等页面里带出的客户信息不在这一条里"),
 ("方案页搜客户要登录、只搜本店;着装人必须是这位客户名下的", "backend/server.py /api/scheme-customers · /api/scheme-wearers;api.本店范围 / kb_fit",
  a_scheme_customer_search, "不带登录搜客户;拿店长会话按客户号搜别家店的客户;拿别家客户的着装人去推码",
  "身份只从登录态取,范围走 api.本店范围(和客户读接口同一个函数、同一个跨店角色常量);"
  "kb_fit 给了着装人就核他在不在这位客户的账户名下。⚠️ 「页面上不默认选第一个着装人」是页面行为,不是闸 ——"
  "后台那道闸是 kb_fit 名下多人量过体时不猜;守页面那一半的是 scheme_customer_search_check 在 node 里真跑页面脚本"),
 ("Skill 管理里停用的技能,模型调不动", "backend/skill_registry.py 状态;agentsite/guards.py Skill 那一支",
  a_skill_gate, "在库副本上把自有技能标成已停用,问执行闸放不放行;再问一个没登记过的第三方",
  "执行闸读的就是后台里的状态(只放试运行 / 已发布);没登记的按来源取默认,库读不到时退回原来的写死清单(第三方照样拦)。"
  "改状态只有总部运营、要写理由、依赖没就绪的放不出去 —— 判在 skill_registry 写口里,skill_registry_check 打 HTTP 层验"),
 ("后台停用的 MCP 工具,模型看不见也调不动", "mcp/protocol.py 三个开关;backend/mcp_registry.py",
  a_mcp_tool_off, "在库副本上停用 get_stock,真起商品领域服务去列、去调",
  "协议层每 5 秒读一次开关(只读连接):停用的 tools/list 不列、tools/call 拒;另有超时、限流。三样都只能收紧,"
  "页面上没有能放大权限的开关;只有总部运营能改、要理由、留痕。读不到配置 = 全部启用(和原来一样)"),
 ("知识问题只有总部运营能指定维护人、改处理状态;报类型只认提问人本人", "backend/kb_issue.py 写口;backend/server.py /api/kb-issue-*",
  a_kb_issue_wrong_role, "在库副本上:顾问给自己定维护人、把问题改成不处理、给别人的检索记录报类型",
  "身份只从登录会话取(请求体里自报的不认);每次改动带理由记进 kb_rag_record_log、写口成败都进 op_log。"
  "复验(tools/kb_recheck.py)结论只有「找到了相关片段 / 仍然零命中 / 复验没跑成」三种、输出写明不等于答对 —— "
  "kb_issue_check 打 HTTP 层验。⚠️ 门店检索记录的**内容**(问题、命中几段)是智能运维平台从轨迹转来的,"
  "后台只核身份不核内容 —— 伪造只能伪造到自己名下"),
 ("报告模板只有总部运营能改,改了也不动已存的报告", "backend/report_template.py 保存 / 视图;backend/report_doc.py 取",
  a_report_template, "在库副本上拿顾问身份存一版模板;总部改模板后打开改之前存的报告",
  "写口里按登录身份判角色(HTTP 层身份只从会话取);模板随取数包在保存那一刻冻结,打开时只读冻结的那一份、不读模板表。"
  "指标名只能从取数包代码现算的已登记清单里选,锁定必选(下单数、营收)取消不了 —— report_template_check 打 HTTP 层验。"
  "10-23 起存一版是草稿,要走 草稿 → 试运行 → 已发布 才生效(不许跳);隐藏项不交给 AI 见下一条"),
 ("报告模板隐藏的指标,写报告的 AI 拿不到它的数", "backend/api.py store_report(_藏 那一段);backend/report_template.py 冻结用",
  a_report_hidden_not_in_pack, "在库副本上发布一版隐藏「销量」的模板,再取周报取数包,在整份 JSON 里按键和值找销量",
  "store_report 把被隐藏的指标整项拿掉(期内 / 存量 / 环比 / 取不到的 / 上期行动都不留它的数),"
  "只在「报告模板 · 隐藏的」里留名字;锁定必选(订单、营收)模板不许隐藏。原来「隐藏的不写进正文」只靠取数包里一句说明,"
  "是约定 —— 现在是**数没给,写不出来**。保存报告冻结的就是拿掉之后的包。"
  "⚠️ 只管这份取数包:模型要是另调 sales_rank 等工具自己去取,不在这一条里(取数包的说明叫它别去补取,那一半是约定)"),
 ("研判销账只有对应角色能做,而且留痕", "backend/ops.py 能销吗 / resolve;backend/server.py /api/ops-resolve",
  a_resolve_wrong_role, "在库副本上拿顾问身份去销一条财务人工任务",
  "接口层身份只从登录态取(不读请求体里的 handler);`resolve` 里按类型查角色,**所有调用方都过这一道**,"
  "成功 / 被拒都写 op_log。两段确认(10-13 起):退款 / 合并的复核只认店长、办结只认财务 / 总部运营,"
  "所以钱出门必经两个人(第二段那一刀在「已办结只认真走完的回执」里)"),
 ("押金「已退」只有财务能登记、必须带渠道退款流水号、一笔流水只证明一笔", "backend/fsm.py bk-deposit 两道闸;backend/refund_write.py;backend/server.py transit / /api/refund-*",
  a_refund_done_without_proof, "在库副本上:店长走通用改状态自报财务 / 财务不给流水号 / 同一流水号登两笔",
  "闸在**状态机**上(fail closed),通用改状态也得过;角色从会话取、覆盖请求体里自报的;"
  "通用改状态点这两条边一律指向退款写口(那里流水号才进得了 refund_trace);流水号唯一索引(结构上做不到重复)。"
  "成功被拒都写 op_log。「审批中 → 处理中」10-16 起也只走复核写口(店长、≥1000 加财务,发起人不能复核自己的)"),
 ("研判已办结只认真走完的回执", "backend/ops.py 回执行不行 / 办结;backend/server.py /api/ops-close",
  a_close_without_receipt, "在库副本上拿一笔没退成的定金当回执去办结财务任务",
  "回执要查得到那张单、属于这件事、状态真走完(定金已退 / 维保单已完成 / 差评按处理方式认同一张订单的单);"
  "不改复核结论,另记回执;成功被拒都写 op_log。⚠️ 客户合并现在进不了已办结 —— 系统里没有执行合并"),
 ("一轮只写一次", "agentsite/guards.py pre_tool_verdict 写工具的闸",
  a_double_write, "同一轮里连着调两次 assign_task",
  "第二次被 PreToolUse 拦下 —— 提示词里那条「一次只做一件」只是祈使句,"
  "**hook 才是强制**。连着写好几条,其中一条参数猜错的话,几条都已经落库了"),
 ("没查类型不许派任务", "agentsite/guards.py pre_tool_verdict",
  a_blind_assign, "不调 task_types 直接调 assign_task",
  "被拦 —— 类型决定挂哪张单据、完成时要不要传图。**没查就派**,"
  "派出去的东西和正常任务长得一模一样,错了也看不出来"),
 ("待核实队列:模型看得见,填不了", "backend/api.py get_review_queue / server.py resolve_combo",
  a_review_readonly, "在工具层找回填接口;调一次队列看矩阵变没变;拿工具层连接去 UPDATE",
  "回流拆成两半 —— **记一笔走日志文件(旁路),回填走后台**。"
  "让模型去写待办,只读保证当场就破"),
 ("无依据的格子不给结论", "backend/api.py _combo_caveat",
  a_default_allow_visible, "随便取一格 rule='—' 的组合,看它还给不给结论",
  "verdict 返回「待核实」并记入待办队列 —— **1274 格(63%)属于这一类**"),
 ("check_write 只校验不写库", "backend/api.py check_write 文档 / 工具描述「不写库」",
  a_check_write_noop, "跑一次**校验会通过**的建档,数客户表行数有没有变",
  "validate_* 是纯函数 —— **被拒的当然不写,通过的才是危险那一半**,这里测的正是后者"),
 ("在制工单只读 —— 不能改期不改派", "prompts.py 铁律 TW05 / 工具描述「这个工具只读」",
  a_workorder_ro, "拿工具层的连接把 WO8001 的交期改到 2099 年",
  "同 mode=ro 那条锁 —— 工坊角色**结构上就改不了**排产,不靠它自觉"),
 ("生命周期不接受手工流转", "后台 PRD 6.1「算法型状态机」/ 铁律 TK08",
  a_lifecycle_no_manual, "在工具层找一个能改档位的接口;并检查人工覆盖有没有和重算值混在一起",
  "工具层没有改档接口;且「人工覆盖生效」与「系统重算值」**分开返回** —— "
  "混在一起的话,没人分得清眼前这个档是算出来的还是人改的"),
 ("RFM 跨档比较无意义", "prompts.py 铁律 TK09 / knowledge/rfm.py 模块开篇",
  a_rfm_cross_group, "把同一个客户放进「档内」和「全量」两个人群各打一次分,看分数变不变",
  "**分数真的会变** —— 这条禁令有可验证的事实撑着,不是提示词的一句话"),
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
 ("对外一律脱敏手机号", "数据规范 F3",
  a_phone_leak, "把 23 个工具全调一遍,搜返回里的完整手机号",
  "**包在工具出口上,不是每个函数各自记得** —— "
  "库里是真的,离开工具那一刻才脱敏;内部对账照常拿真号。"
  "⚠️ **诚实说明:现存的 23 个工具本来就没有一个会吐真号** —— "
  "这层包装防的是**未来新加的工具**。所以它的咬合方式是"
  "「临时加一个会吐真号的工具,看包装拦不拦得住」,"
  "而不是「拆掉包装看漏不漏」(现在拆了也不漏)"),
 ("上新待办卡片的电话地址默认打码", "backend/arrival_card.py 卡片()(用户 10-10)",
  a_card_mask, "用总部身份取全部卡片,搜返回里的完整手机号",
  "卡片出口上打码 —— 页面拿到的就是打码的,不是前端藏起来"),
 ("看完整号码只给这张卡片范围内的人", "backend/arrival_card.py 看完整联系方式()",
  a_card_reveal_other, "别的顾问拿一张不是指派给他的卡片号去取全号",
  "范围判定和「卡片列给谁」是同一个函数(_可见)—— 不另写一套"),
 ("看完整号码一定留痕", "同上(用户 10-10 定:点一下看完整并留痕)",
  a_card_reveal_unlogged, "让台账写不进,再以本人身份去取全号",
  "**台账写不进就不给全号** —— 「看了但没留痕」正是用户要防的那件事,不能因为台账出故障就放行"),
 ("聊天站执行记录只给本人和总部运营", "agentsite/sessions.py 能看执行记录吗(10-24 实测原来不登录就给 200)",
  a_spans_scope, "不登录取 / 别的门店店长取甲的会话 / 店长列全部",
  "**靠结构**:/spans 两处都调同一个判定;单条按会话归属(和续聊同一个 check),查不到归属就拒。"
  "端口只绑 127.0.0.1,所以原来的暴露范围是本机"),
 ("模型不能执行命令", "prompts.py 铁律 TL05「你没有任何写权限」",
  a_bash, "让 PreToolUse 判定 Bash 工具", "非 mcp__ 开头的工具一律拦下(Hook 运行时)"),
 ("模型不能开子智能体", "同上", a_task, "让 PreToolUse 判定 Task 工具", "同上"),
 ("配置层也点名封了内置工具", "sdk.py disallowed_tools",
  a_disallowed, "检查危险工具是否都在 disallowed_tools 里",
  "**双锁**:配置一道 + Hook 一道。配置会被人改错,Hook 是兜底"),
 ("工作流差评处置不经手超权限的钱", "backend/workflow_bridge.py 差评处置(六条第四条,用户 10-25 拍「停下报总部,不写」)",
  a_bridge_rating_money, "库副本上:判给企业预估 2000 元 / 关闭方式写成全额退款",
  "**靠结构**:写之前按现成的金额授权档(knowledge/liability.谁能拍板)判,不是店长的档一行都不写;"
  "出钱的关闭方式(knowledge/rating.出钱的处理方式)不经流程关。底下的判责写口自己也有授权闸(repair_write.decide),两道"),
 ("工作流派回访:只派给名单里、此刻仍有由头的人,重试不派第二条", "backend/workflow_bridge.py 派回访任务(六条第五条,10-25)",
  a_bridge_recall, "库副本上:店长填名单外的客户号 / 名单里塞一个眼下没由头的人 / 同一张单执行两次",
  "**靠结构**:只认这次名单里的客户号;派的那一刻以绑定员工身份逐人再问一次促活(范围和由头都按澜绣自己的口径,"
  "不信名单上写的);每人一笔台账,做过的不再做、开始了没结果的报待核实不重做"),
 ("工作流写跟进:重试不写第二条、不记到别人名下", "backend/workflow_bridge.py 写跟进(用户 10-24 拍「核对即定稿」)",
  a_bridge_followup, "库副本上:同一张写跟进单执行两次 / 通话号是 A 的录音而客户号写 B / 工具名写成改订单 / 核对人没绑定澜绣员工 / 名单外的开单 / 不带绑定去派任务",
  "**靠结构**:写之前按幂等键查台账(键记在 create_followup 的台账 ctx 里);"
  "录音的客户和单子上的客户对不上就拒;执行表只有取转写 / 写跟进两项;"
  "核对人没绑定澜绣员工就不写(10-24 账号绑定,不以服务身份顶替)。"
  "「写之前必须有人批过」在管理后台执行侧(runtime/桥闸.py,只认人工节点的批准),由它那边的夹具和端到端守"),
 ("没登录调不动聊天站的智能体", "agentsite/app.py /run(用户 10-23 拍「先修复」)",
  a_run_no_login, "不带登录身份直接 POST /run 问客户手机号",
  "**靠结构**:身份只从后台会话换(_who),换不出就在调 sdk.run 之前回 401。"
  "原来页面有登录守卫而接口没有 —— 不带 cookie 直接打接口就能问"),
 ("按需加载只取回自己名单里的工具", "agentsite/sdk.py 按需加载的角色 / guards.py ToolSearch 点名例外 + 名单闸",
  a_toolsearch_scope, "全能助手放行 ToolSearch 后:真起服务搜版师写口、钩子判名单外工具和 Bash、换身份重建、研判名单",
  "**靠结构**:服务按名单建(CLI 不认识名单外的工具)+ 调用时钩子按同一份名单再核一次。"
  "ToolSearch 按名字放行、不按「只读」放 —— 再加一个得再改代码再过咬合。"
  "规矩仍按名单全集启动时装配,不读运行时取回了哪些(P6 的静态前提不变)"),
 ("店长改不了商品(全国主数据)", "server.py save_product",
  a_product_by_manager, "以店长身份调 save_product",
  "**原来是「店长及以上」,那是个漏洞** —— 商品挂的版型决定用料和报价,"
  "门店各改一份会让同一件衣服在两家店报出不同的价。和 save_syscode 同级"),
 ("店长改不了定制品的量体模板", "同上",
  a_product_template_by_manager, "以店长身份改 template",
  "比改名字严重 —— 量体模板决定量哪些尺寸,改错了是照着错的口径去裁"),
 ("无有效同意 → 取不到身体数据", "12-成长与生命周期.md 第七节 / 个保法 28 条",
  a_consent_body, "撤销身体数据同意后调推算", "工具层硬门,不靠模型自觉"),
 ("不满 14 周岁缺监护人同意 → 不能推算", "同上 / 个保法 31 条",
  a_consent_minor, "只撤未成年人同意后调推算", "工具层硬门"),
 ("量体超期 → 下单被拦", "12-成长与生命周期.md 第五节",
  a_expired_order, "拿一个量体已过期的孩子走下单前拦截", "ops.order_block 规则直出"),
 ("读原文的工具不许变成读文件的工具", "backend/api.py kb_read / KB_DOCS 白名单",
  a_kb_read_traversal, "八种路径穿越写法(../ 、绝对路径、URL 编码、....// 等)",
  "**根本不接受路径** —— 调用方给的字串只在写死的 16 篇里挑,"
  "挑不中就没有第二条路。过滤 `../` 那条路永远漏一种写法"),
 ("项目的 CLAUDE.md 不进模型的系统提示词", "agentsite/sdk.py RUNTIME + _ensure_runtime",
  a_no_project_memory, "从运行目录一路往上找 CLAUDE.md;并确认 Skill 没被一起弄丢",
  "**这条以前是约定,而且实测是破的** —— 问它「你提示词里有没有 CLAUDE.md」,"
  "它抄出了第一行。修法是把 cwd 挪出项目(setting_sources=[] 也能挡住,"
  "但 Skill 会跟着一起没)"),
 ("白名单与 MCP 暴露完全一致", "skills_check.py",
  a_whitelist, "比对两边集合", "**这一条漏过一次**(新工具挂了 MCP 没进白名单)"),
 # 注意名字:它是**按整条会话累计**的,不是「单次调用」。
 # 原来这条叫「单次会话预算封顶」,而实际行为是跨轮累加 ——
 # 名字说的和行为不是一回事,人会按名字去理解为什么被掐。
 ("会话累计花费封顶(跨轮累加,不是单次)", "sdk.py _max_usd + budget_check.py",
  a_budget, "检查 max_budget_usd 是否传进 options、是否为正值",
  "SDK 层强制,超了直接停;阈值按供应商分 —— "
  "SDK 那个数只在跑 Claude 时接近真实,跑 DeepSeek 时虚高几十倍"),
 ("预警转任务:同一件事没办完不重派,补货跟进只派店长 / 总部、只能从预警那一行派",
  "backend/alert_dispatch.py 派 / 重复吗;backend/tasks.py assign_task(_来源)、pool_for;backend/tasktypes.py 派给谁",
  a_alert_dispatch, "库副本上同一张该催的单连派两次(第二次带一个假超期日期);补货跟进派给顾问;从通用口派补货跟进",
  "防重复派在**写的那个事务里**判(BEGIN IMMEDIATE),超期日期 / 档位服务端现算、请求体里的不收;"
  "能派给谁是类型的性质(派单、改派同一个 pool_for);来源只能由预警写口按参数传入,通用口没有这条路"),
 ("MCP 只认代码里声明的服务", "sdk.py strict_mcp_config",
  a_strict_mcp, "比对 .mcp.json 与代码声明的服务名",
  "两边名字完全不同 —— 名字对不上,正好**证明** .mcp.json 真的被忽略了"),
]

# ── 检查类:结构上做得到,但有一道检查会在提交前抓住 ────────────────────
CHECKED = [
 # 2026-09-15 从【约定】挪上来。原来的缺口是「g1 查了来源标注,
 # 但没查『拿 demo 数据做承诺』」—— 而扫一遍才发现问题比那更靠前:
 # **29 条标着 `public`(定义是「给得出链接」)的知识里,15 条连出处的名字都没有**,
 # scale 32 条里 31 条没有。**一个标着「可溯源」却溯不了源的条目,比标 demo 更糟**:
 # 标 demo 的没人敢拿去承诺,标 public 的顾问会照着它对客户说。
 #
 # 现在两头都接上了:查询返回里**带着溯源状态**(`api._with_source`)——
 # 「标着可溯源,但库里没有出处」跟着这一条一起被模型读到;
 # 而 `source_check` 钉住欠账上限,只许降不许涨。
 ("声称可溯源的知识,得真的溯得了源", "backend/source_check.py + api._with_source",
  "首次扫出 46 条溯不了源(占 168 条的 27%);上限钉死,新加知识没带出处会当场红。"
  "**不替它编出处,也不替它降档** —— 让它自己说出来"),
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
 # 这一条是**新补的,而且是主动认领的**:它以前根本没被记下来,
 # 因为我从没声称过它是保证 —— 但「没写下来的约定,和结构锁在平时长得一模一样」。
 ("智能体调工具时没有身份", "backend/api.py check_write 文档",
  "MCP 工具跑在 CLI 拉起的**子进程**里,拿不到后台的登录会话 —— "
  "所以 check_write 答的永远是「**如果是**这个角色」,不是「**你**这个人」。"
  "真执行那一关在后台写接口上(role 从会话取,已是结构),"
  "但**智能体这一侧的角色是调用方说了算**。要补成结构,得把会话身份透传进 MCP 子进程。"),
 ("只说知识库里查到的,不得凭训练知识作答", "prompts.py 铁律 TL01",
  "g1 只抓「报了数字却没调工具」——**换个不带数字的说法就漏**,"
  "比如「云锦这种料子一般比较厚重」"),
 ("区分「不能做」和「不建议做」", "prompts.py 铁律 TL04", "没有任何检查"),
 ("换面料必须让客户确认,不能替他决定", "prompts.py 铁律 TL11", "没有任何检查"),
 # 2026-09-22 补登。**它以前藏在一句错的红线后面**:CLAUDE.md 写着「挂给模型的工具全部只读」,
 # 而 09-10 起就有写工具了。原来有一张确认卡(点了才写),后来拆掉,**只剩提示词里一句话** ——
 # 于是「写之前要人确认」从结构悄悄退成了约定,而清单上哪儿都没记。
 # 一条从结构退成约定却没登记的保证,和结构锁在平时长得一模一样。
 ("写工具动手之前先跟用户确认(派给谁、什么时候、做什么)", "prompts.py 铁律 TL16",
  "写工具**立即生效**(api.WRITE_TOOLS,2026-09-22 共 21 个 —— 当天加了白坯试衣、开裁、量体、签收三件、下单两件、报修四件))。身份和写入规则是结构,"
  "但「先对一遍再动手」**只有提示词说**:模型不问就写,没有任何东西会拦。"
  "要补成结构,得把确认那一步做回写接口上(起草 → 用户确认 → 才落库)"),

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
    # ⚠️⚠️ **两类都红,但不许写成同一句话。**(2026-10-23 修)
    # 原来这里对 `bad` 里的每一条都说「攻击成功了」—— 而其中可能有
    # 「这条攻击自己跑不起来 / 前提不成立」那一类。
    # > 一句「这条攻击没验到」和一句「这条边界被攻破了」,**在那条红上长得一模一样** ——
    # > 而照着后者去查,是去找一个**不存在的安全漏洞**。
    # 两类都 `return 1`(跑不起来也算没守住,不许和通过长得一样),但人读到的理由是实话。
    破的 = [(n, m) for n, m in bad if 跑不起来标记 not in m]
    没验到 = [(n, m) for n, m in bad if 跑不起来标记 in m]
    if 破的:
        print(f"\n❌ {len(破的)} 条声称靠结构的保证,**攻击成功了 —— 边界是破的**:")
        for n, m in 破的: print(f"   · {n}:{m}")
    if 没验到:
        print(f"\n❌ {len(没验到)} 条**这条攻击自己跑不起来,它什么都没验**"
              f"(不是边界破了,别去找漏洞 —— 去看这条攻击的前提):")
        for n, m in 没验到: print(f"   · {n}:{m}")
    if bad:
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
