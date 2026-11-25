#!/usr/bin/env python3
"""只读数据接口 —— 这就是 agent 的工具层。

铁律:truth 表绝不通过任何接口暴露。评测比对在 agent 之外做。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import sqlite3, os, json, sys, re, subprocess
import datetime as _dt
# 库路径走单源(W02 第③步第一个,11-22):LANXIU_DB 优先 —— 服务进程不设它、照旧是 backend/lanxiu.db;
# 评测设了它,子进程里 mcp/protocol.py 本来就按它切,这里 import 时也就对齐了
from dbpath import 路径 as _库路径   # noqa: E402
DB=_库路径()

# ── 两道结构锁 ──────────────────────────────────────────────────────────
# 这两条原来都是**约定**:靠「这里没人写 INSERT」和「这里没人 JOIN truth」守着。
# 边界审计的结论是:**靠人不写的边界不是边界** —— 换个人、隔三个月就会破,
# 而且破了不会报错,只会安静地多一个写接口 / 多一条泄漏路径。
#
# 锁一:连接开成只读。任何写操作直接抛 OperationalError,而不是碰巧没人写。
# 锁二:任何提到 truth 的 SQL 一律拒绝执行 —— **不看语句形状**。
#       原来的检查是 `re.findall(r'FROM\s+(\w+)', 源码)`,只认 `FROM truth`;
#       写成 `JOIN truth u ON …` 就完全查不到(ops.py 里正是这么写的)。
#       静态扫源码永远追不上语句写法,所以改成运行时拦。
_TRUTH = re.compile(r"\btruth\b", re.I)
# 锁三:**凭据字段和 truth 表同等对待。**
# 密码哈希与盐拿到手就能离线爆破,所以工具层连读都不许读 ——
# 不是「模型不该查」,是「查了会抛异常」。
# 顺带禁掉 `SELECT * FROM account`:星号会把 pwd_* 一起带出来,
# **一个没写清楚的星号,就能把前面两道锁绕过去。**
# 语句文本只是**快速失败**;真正的锁在下面「查返回的列名」——
# `select a.* from account a join …` 这种带别名的星号,正则永远追不完。
# **别枚举语句形状,去看结果长什么样** —— truth 那次已经教过一遍了。
_CRED = re.compile(r"pwd_(hash|salt|algo)", re.I)

class _用完就关(sqlite3.Connection):
    """`with _c() as c:` 结束时**连接真的关掉**。

    ⚠️ 标准库的 `with sqlite3.connect(...) as c:` 只提交、**不关连接**,关掉靠 GC。
    2026-11-12 量过:一次经营报告取数包 `connect` 调了 **3265 次、显式 close 82 次**;
    我的 shell 文件描述符上限 100 万所以从不出事,而 **launchd 起的进程上限 256** ——
    夜跑里 `store_report_eval` 从 10-28 起每晚崩在「unable to open database file」,
    那是 open() 撞上限时 sqlite 的原话;10-29 服务那次「页面打得开、登录进不去」是同一个根因。
    > 一台「连接都关了」的机器和一台「连接靠 GC 关、碰巧没撞上限」的机器,
    > **在本地跑任何检查都长得一模一样** —— 只在 256 那条线上分得开。
    修在这一处而不是 23 个调用点:AST 扫过全部 `with _c() as X`,X 没有一处在 with 之后还被用。
    `contextlib.closing(_c())` 那 10 处照旧成立(关两次是无害的)。
    """
    def __exit__(self, *a):
        try:
            return super().__exit__(*a)
        finally:
            self.close()


def _c():
    c=sqlite3.connect(f"file:{DB}?mode=ro", uri=True, factory=_用完就关); c.row_factory=sqlite3.Row; return c

_CRED_MSG = ("账户凭据(密码哈希 / 盐)**不允许经工具层访问** —— 拿到哈希和盐就能离线爆破。\n"
             "查账户请把列名写清楚(id / phone / login_name / status),对外只给脱敏手机号。\n"
             "见 backend/boundary_audit.py。")


def _门店条件(值, 别名="", c=None, 列="shop"):
    """**这个文件里「按门店筛」的唯一入口** → `(WHERE 片段, 参数列表)`;片段**不带** `AND` 前缀,
    值为空时片段是空串。按门店**码**筛,不按显示串 —— 门店在后台改个名,按串筛就变成 0 行,
    **而且不报错**(`backend/shop_key_check.py` 的棘轮盯着这件事,上限已经是 0)。

    ⚠️ 别在这个文件里再写裸 `shop=?`。认不出的值(工坊 / 全渠道 / 老串)`门店条件()`
    会退回按串比,所以工坊的人、全渠道的活动照样查得到。

    `门店条件()` 要读 `shop` 表的「串 → 码」对照,所以它要一条连接:
    手上已经有的传进来(`c=`),没有就自己开一条只读的。"""
    import contextlib as _cl
    if c is not None:
        return _SK.门店条件(c, 值, 别名, 列)
    with _cl.closing(_c()) as _x:
        return _SK.门店条件(_x, 值, 别名, 列)


# 跨店看全量的角色。**售后不属于某一家店**(判责是工艺判断、差评跨店),所以和总部运营一样。
# 差评、退押金、管理后台客户读接口都用这一个 —— 「本店」两处各写一套,迟早对不上。
跨店角色 = ("总部运营", "售后")

# 只给「读」划范围用的跨店角色(管理后台那批读接口,server._店范围)。
# 用户 11-11 拍「财务也看全部门店」。⚠️ **别改上面那个 `跨店角色`** —— 差评、退押金这些写操作也在用它,
# 财务能看全部 ≠ 财务能跨店处理差评。读和写分两份,读这份只许比写那份宽。
读跨店角色 = 跨店角色 + ("财务",)

# 内部调用的**显式**身份(11-24,体检「最该约定升结构的一条」:客户档案工具没身份时不限店,新路径忘带身份就静默放开)。
# 研判队列 / 评测 / V1 V2 子进程这些没有真人登录的路径,**不再靠「没身份 = 不限」**,而是明说「我是系统」:
# `sdk.run(..., me=api.系统身份)` 或 `with api.as_user(api.系统身份)`。`api_wearer.本店范围` 只在那一处认这个角色 → 跨店;
# 它**不在 `跨店角色` 里**,所以写口的门店闸、差评 / 退押金那些按角色的闸都不会因为它放宽 —— 系统只是读得全,不是什么都能写。
# 不用环境变量开关:开关会被整棵进程树继承(夜跑一设,它拉起的一切都免检),日志里也看不出是谁;身份走现有通道,trace / op_log 记得到。
系统身份 = {"no": "system", "role": "系统", "name": "系统(内部调用)"}

def _查(c, sql, a):
    """工具层取数的**那三道检查**,`_rows` 和 `_rows2` 共用这一份(11-16 收编:原来 `_rows2` 自己开一条
    **可写**连接、三道一道都不过 —— 现有调用碰巧都是写死的 SELECT,而下一个调用者不一定)。"""
    if _CRED.search(sql): raise PermissionError(_CRED_MSG)
    if _TRUTH.search(sql):
        raise PermissionError(
            "truth 是评测答案表,**不允许经工具层访问**(任何语句形状都不行)。"
            "评测比对在 agent 之外做 —— 见 backend/boundary_audit.py 第 2 条。")
    cur = c.execute(sql, a)
    cols = [d[0].lower() for d in (cur.description or [])]
    # **与语句写法无关的那道锁**:结果里只要出现凭据列,就不给。
    # 星号、别名星号、子查询、以后新加的写法,全在这一关。
    if any(x.startswith("pwd_") for x in cols): raise PermissionError(_CRED_MSG)
    return cur


def _rows(sql,*a):
    with _c() as c:
        return [dict(r) for r in _查(c, sql, a)]

def _认客户(customer):
    """按客户号或姓名认人,**认得软合并**(用户 2026-10-14 拍)。→ (人们, 注明)。

    人们:[{id: 主档号, name, 关联: [主档 + 并进它的档案号]}] —— 多于一个就是真重名,调用方照旧要客户号。
    · 给的是**已并入的副档号** → 认成它的主档,注明「X 已并入 Y」;
    · 每条命中都认到主档再去重:**已并入别人的副档不算另一个人**;按副档的名字搜也认得到主档。
    查订单 / 方案 / 售后这类**挂在档案上的事**时用「关联」那一串 id 一起查;
    会员等级 / 积分**不相加**(只关联不累计),调用方别拿关联去求和。只读:工具层连接是只读的。"""
    import merge as _mg
    with _c() as c:
        有并 = _mg._有列(c)
        cols = "id,name" + (",merged_into" if 有并 else "")
        rs = [dict(r) for r in c.execute(f"SELECT {cols} FROM customer WHERE id=? OR name=?", (customer, customer))]
        根们, 注 = [], None
        for r in rs:
            # 每一条命中都认到它的主档再去重 —— 同一个人的两条档案(不管同名还是不同名)只算一个人;
            # ⚠️ 不能把「已并入的」直接跳过:按副档的**名字**搜而它和主档不同名时,就会报「没有这个客户」
            根 = _mg.主档(r["id"], c)
            if r["id"] == customer and 根 != r["id"]:
                注 = f"{customer} 已并入 {根}(同一个人;订单 / 积分只关联不累计)"
            if 根 not in 根们:
                根们.append(根)
        人们 = []
        for 根 in 根们:
            nm = c.execute("SELECT name FROM customer WHERE id=?", (根,)).fetchone()
            人们.append(dict(id=根, name=nm[0] if nm else None, 关联=_mg.关联档(根, c)))
    return 人们, 注


def _人头(别名=""):
    """数人头的 WHERE 片段:只数主档(用户 10-14 拍:一律按人,归主档所在店)。只给统计出口用。"""
    import merge as _mg
    with _c() as c:
        return _mg.人头条件(c, 别名)


def _人列(列):
    """把客户号列换成「这个人的主档号」:COUNT(DISTINCT {_人列('a.customer_id')})。"""
    import merge as _mg
    with _c() as c:
        return _mg.人(c, 列)


def _按人(ids):
    """一串客户号 → 去重后的「人」(主档号)集合。Python 侧数人头用(数到店 / 接待 / 成交客户数)。"""
    import merge as _mg
    with _c() as c:
        if not _mg._有列(c):
            return set(x for x in ids if x)
        并 = dict(c.execute("SELECT id, merged_into FROM customer WHERE merged_into IS NOT NULL AND merged_into<>''").fetchall())
    return {并.get(x, x) for x in ids if x}


def _在(ids):
    """SQL 的 IN 占位:→ ('?,?,?', ids)"""
    ids = list(ids)
    return ",".join("?" * len(ids)), ids


# ── 人工任务的状态与类型:**收成一份,别手抄** ────────────────────
#
# ⚠️ 2026-10-15 收的。原来这两份清单哪儿都没有:
#   · 状态只有 `selftest.py` 手抄过一份五种(而它是自测,不是口径);
#   · 类型**一处都没有**,而 `list_tasks` 的描述手抄着「财务人工任务 / 客户合并确认」
#     **两种** —— 库里实际有**四种**,漏掉的 `评价差评` 是最大的那一类。
#
# 后果不是报错,是**模型照描述以为只有两种**:它不会去问评价差评和售后判责。
# **这和「免运费进了枚举而描述没跟上」是同一个形状** —— 判定层放行,说明层拦着。
#
# 📌 `TASK_STATES[0]` 是 `list_tasks` 的默认值,顺序有意义,别重排。
TASK_STATES = ("待处理", "待复核", "已处理", "已升级", "已关闭")
TASK_TYPES = ("评价差评", "财务人工任务", "客户合并确认", "售后判责")
看全部任务 = "全部"      # status 传这个就不按状态过滤


def list_tasks(task_type=None, status=TASK_STATES[0]):
    """列出人工任务。type 见 TASK_TYPES,status 见 TASK_STATES。

    ⚠️ **默认只返回「待处理」的,而那是少数** —— 库里大部分任务已经不在这个状态了。
    原来 schema 不给 status,于是**模型只看得到一小部分,问「已关闭的人工任务」
    会拿到那几条待处理的,而且语气确定**。status 传 `全部` 就不按状态过滤。
    """
    全 = status == 看全部任务
    if task_type and 全: return _rows("SELECT * FROM task WHERE type=?", task_type)
    if task_type: return _rows("SELECT * FROM task WHERE type=? AND status=?", task_type, status)
    if 全: return _rows("SELECT * FROM task")
    return _rows("SELECT * FROM task WHERE status=?", status)


def find_task(task_id):
    """按 id 找一条人工任务 —— **不绑状态**。

    ⚠️ 这个函数存在的理由就是「让它只剩一份」。
    原来 `server.py` 和 `v1.py` 各自手写着
    `[x for x in list_tasks(None, "待处理") if x["id"]==tid]` ——
    **两份本该一致的东西,而没有东西盯着它们**。
    绑了「待处理」之后库里只找得到几条,
    页面上的表现是**「列表里明明有这条,点下去说任务不存在」**。

    改成一份之后,`task_status_check` 才算真的在验那段代码 ——
    它原来在库副本上自己重实现了一份去验,
    **而一个「验了那段代码」和一个「验了我重写的一份」,在绿勾上长得一模一样。**
    """
    return [x for x in list_tasks(None, 看全部任务) if x["id"] == task_id]


def 本人着装人(customer_id):
    """这条客户档案所属账户的「本人」是哪个着装人。没有就 None。

    ⚠️ **身份绑账户,不绑门店档案**(CLAUDE.md)—— 所以这里走 account。
    提成函数是因为三个地方要用同一个答案:`kb_fit` 的退路、评测的锚点、
    以及那条「题面写死的着装人还是本人吗」的前提判据。
    **评测锚点原来是靠 `kb_fit` 不传 wearer 时退到本人「恰好」拿到这个值的** ——
    而 2026-10-15 之后 kb_fit 不再猜了,那个巧合就没了。
    """
    r = _rows("""SELECT a.self_wearer_id w FROM customer k
                 JOIN account a ON a.id=k.account_id WHERE k.id=?""", customer_id)
    return (r or [{}])[0].get("w")

def get_deposit(deposit_id):
    """押金单:金额、状态、幂等号、关联预约"""
    r=_rows("SELECT * FROM deposit WHERE id=?",deposit_id)
    return r[0] if r else {"error":f"押金单 {deposit_id} 不存在"}

def get_refund_trace(deposit_id):
    """退款尝试轨迹:每次重试的时间、渠道、请求金额、返回码、幂等号"""
    r=_rows("SELECT attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key FROM refund_trace WHERE deposit_id=? ORDER BY attempt",deposit_id)
    return r if r else {"error":f"押金单 {deposit_id} 无退款轨迹"}

def get_payment_flow(deposit_id):
    """支付流水:in=收款 out=退款,含渠道流水号与最终状态"""
    r=_rows("SELECT id,direction,amount,channel,channel_serial,status,ts FROM payment_flow WHERE deposit_id=?",deposit_id)
    return r if r else {"error":f"押金单 {deposit_id} 无支付流水"}

def _员工称呼(no):
    """工号 → 「顾晚(顾问)」;查不到回 None(不编)。用户 2026-10-25 拍:客户类工具里出现工号的地方,旁边带上姓名和岗位 ——
    原来只给工号,模型在回答里只能写「经手 60000012」,派任务时也说不出「派给她的顾问顾晚」。
    **工号那一栏原样留着**(判分器和检查按工号对),名字另起一栏。"""
    if not no:
        return None
    r = _rows("SELECT name, role, status FROM staff WHERE no=?", str(no))
    if not (r and r[0].get("name")):
        return None
    # 停用的要标出来(10-25 用户实测:C10007 归属顾问何苓已停用,模型照档案说「默认派给何苓」,派单才撞上「找不到何苓」)
    停 = "" if (r[0].get("status") or "启用") == "启用" else f"·{r[0]['status']},派不了任务"
    return f"{r[0]['name']}({r[0]['role']}{停})"


def get_customer(customer_id):
    """客户档案。敏感字段按后台规则脱敏:手机号中间四位、地址门牌号"""
    # 只看本店(用户 2026-10-25 拍)。会员详情 / 接触史早就按身份限了,唯独档案没有 ——
    # 顾问按客户号或姓名能翻到别家店的档案(消费额、生日、归属顾问)。
    # 跨店角色照旧看全量。**没有身份时拒**(11-24 翻的,三步法第三步):原来写「没身份不限,那只会是后台研判 / 内部调用」——
    # 一条新路径忘带身份就静默放开,是约定不是结构。现在研判队列 / 隔离试运行 / 评测 / V1 V2 子进程都明说 me=api.系统身份,
    # 系统身份只在这里被点名认(whoami(认系统=True)),认了就是跨店读全量;真人路径登录了 sdk 必带 LANXIU_ME。
    me=whoami(认系统=True)      # 第一个(目前唯一)点名认「系统身份」的工具 —— 系统读得全,但只在这里
    if not me:
        return {"error":"NO_IDENTITY:没有身份,看不了客户档案 —— 真人请先登录;内部调用(研判 / 评测 / 子进程)要显式带 api.系统身份",
                "范围":"本店"}
    限店 = 本店范围(me) is not None          # 「本店」只有一份口径,和客户读接口 / 方案页搜客户同一个函数
    if 限店:
        import shop_key as _SK, contextlib as _cl
        with _cl.closing(_c()) as _x:
            我店=_SK.码(_x, 本店范围(me)) if 本店范围(me) else None
            店码={r["id"]: r["shop_code"] or _SK.码(_x, r["shop"])     # 当天新写、还没回填的行按串兜住
                  for r in _x.execute("SELECT id, shop, shop_code FROM customer WHERE id=? OR name=?", (customer_id, customer_id))}
        if not 我店:
            return {"error":"你的账号没挂门店,看不了客户档案 —— 跨店看档案只有总部运营和售后可以","范围":"本店"}
        本店 = lambda cid: 店码.get(cid) == 我店
    else:
        本店 = lambda cid: True
    r=_rows("SELECT * FROM customer WHERE id=?",customer_id)
    认=None
    if not r:
        # 也认姓名(10-25 用户实测:「给张青梧派回访」,模型只拿到这个只认客户号的工具,就答「没有按姓名查的工具」去问人)
        # 重名只给候选不给档案 —— 默默取第一个,档案会安静地挂在错的人身上。
        # 限店时**只在本店里认**:别店的同名客户既不算重名、也不进候选(候选本身就是别店客户的客户号和姓名)
        人们=[p for p in _认客户(customer_id)[0] if 本店(p["id"]) or (限店 and p["id"] not in 店码 and 本店_主档(p, 我店))]
        if len(人们)>1:
            return {"error":f"「{customer_id}」命中 {len(人们)} 个客户,要客户号才能给档案",
                    "候选":[{"客户号":p["id"],"姓名":p["name"]} for p in 人们]}
        if not 人们:
            return ({"error":f"客户 {customer_id} 不存在(客户号和姓名都没对上)"} if not 限店 else
                    # 范围:给交付前检查认的(说成「库里没有」会被打回)—— 别店有没有这个人,这里不说
                    {"error":f"你的门店里没有客户号或姓名是「{customer_id}」的客户(只查了本店)","范围":"本店"})
        r=_rows("SELECT * FROM customer WHERE id=?",人们[0]["id"])
        认=f"按姓名「{customer_id}」认到客户号 {人们[0]['id']}"
    elif not 本店(customer_id):
        # 不说他在哪家店、也不给档案里任何一个字段 —— 说了就等于把别店客户的归属透出去了
        return {"error":f"{customer_id} 不在你的门店({me.get('shop')}),看不了他的档案","范围":"本店"}
    d=r[0]
    if 认: d["认人"]=认
    p=d.get("phone") or ""
    d["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    if d.get("advisor_no"):
        d["归属顾问"] = _员工称呼(d["advisor_no"]) or "(工号在员工表里查不到)"
    return d


def 本店_主档(人, 我店):
    """按副档的名字认到的主档,主档号不在 SELECT 命中里 —— 现查它的门店码。"""
    import shop_key as _SK, contextlib as _cl
    with _cl.closing(_c()) as _x:
        r=_x.execute("SELECT shop, shop_code FROM customer WHERE id=?", (人["id"],)).fetchone()
        return bool(r) and (r[1] or _SK.码(_x, r[0])) == 我店

TOOLS={"list_tasks":list_tasks,"get_deposit":get_deposit,"get_refund_trace":get_refund_trace,
       "get_payment_flow":get_payment_flow,"get_customer":get_customer}

# ── 对模型说的那几份处理方式名单:**从枚举现拼,不手抄** ─────────────────
#
# ⚠️⚠️ 2026-10-13 修。原来这几处手抄着「只认这五种:只回访 / 免次改衣 / 送保养 /
# 部分退款 / 全额退款」,而那天「免运费」进了枚举(用户拍的:算「让东西」,
# 归小额档,不触发双人批准)。后果不是报错,是**模型照描述把它当成自己造的词不敢填** ——
# **判定层放行,说明层拦着**,而两层分别看都是对的。
#
# 📌 而最该记的是被改掉的那段函数注释长什么样(原 2403 行):
#     way 处理方式,**只认登记过的那五种**(只回访 / 免次改衣 / ...)。
#         判定在 `knowledge/rating.处理方式能不能用`,**这儿不抄**。
# **「这儿不抄」这句话,就写在抄了的那一行旁边。**
# > 一条写着「我不抄」的注释,和一份真的没抄的代码,在那一行上长得一模一样。
#
# ⚠️ `append` 不是 `insert(0)` —— knowledge 里有过和标准库重名的模块
# (`trace.py` 那次,改名成 llmtrace.py),插到最前面会遮蔽标准库。
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "knowledge"))
import rating as _R方式                                       # noqa: E402
import shop_key as _SK                                         # noqa: E402  门店关联键的唯一来源
_方式表 = " / ".join(_R方式.处理方式)
_出钱表 = " / ".join(_R方式.出钱的处理方式)
_不出钱表 = " / ".join(x for x in _R方式.处理方式
                      if x not in _R方式.出钱的处理方式)


SCHEMAS=[
 {"name":"list_tasks","description":"列出人工任务。⚠️ **不传 status 时只返回「"
  + TASK_STATES[0] + "」的,而那是少数** —— 库里大部分任务已经不在这个状态了。"
  "问「已关闭的任务」、「有多少条已处理」这类问题**必须传 status**,"
  "想看全貌就传 `" + 看全部任务 + "`。不传就答等于拿一小部分当全部。",
  "input_schema":{"type":"object","properties":{
    "task_type":{"type":"string","enum":list(TASK_TYPES),
                 "description":"哪一类人工任务。不传 = 不按类型过滤"},
    "status":{"type":"string","enum":list(TASK_STATES) + [看全部任务],
              "description":"任务状态。不传 = 只看「" + TASK_STATES[0] + "」的;传 `"
                            + 看全部任务 + "` = 不按状态过滤"}},
   "required":[]}},
 {"name":"get_deposit","description":"读取押金单:金额、当前状态、幂等号、关联预约号",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_refund_trace","description":"读取退款尝试轨迹,含每次重试的返回码、请求金额和幂等号",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_payment_flow","description":"读取支付流水,direction=in 为收款,out 为退款,含渠道流水号与最终状态",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_customer","description":"读取客户档案(手机号与地址已脱敏,带归属顾问的姓名岗位)。customer_id 给客户号或姓名都行;姓名重名时只给候选,要客户号才给档案。**只看得到本店的客户**(总部运营 / 售后看全部);别店的客户会明说「不在你的门店」,不是没有这个人。",
  "input_schema":{"type":"object","properties":{"customer_id":{"type":"string","description":"客户号(如 C10001)或客户姓名"}},"required":["customer_id"]}},
]

# ── 工艺知识库工具(只读)──────────────────────────────────────────
def kb_lookup(keyword=None, cat=None, src=None):
    """按关键词/分类/来源等级查工艺知识。cat: 形制/材质/工艺/配饰;src: public/scale/biz/demo"""
    rs=_rows("SELECT code,name,cat,alias,brief,fit,lead_days,cost_level,src_type,src_url FROM craft ORDER BY code")
    if cat: rs=[r for r in rs if r["cat"]==cat]
    if src: rs=[r for r in rs if r["src_type"]==src]
    if keyword:
        k=keyword.strip()
        rs=[r for r in rs if any(k in str(r.get(f) or "") for f in ("name","alias","brief","fit","code"))]
    if not rs:
        # ⚠️ **指路,别指到死路上。**
        # 原来这句只说「查不到,不要凭印象回答」—— 而实测它就到此为止了:
        # 问「真丝褙子怎么洗怎么存」,它 `kb_lookup` 查了三次「养护」「清洗」「真丝」,
        # 然后答「知识库里查不到」。**而那些话就写在 09-养护与售后.md 的正文里。**
        #
        # 这条工具查的是**结构化条目**(名字、别名、简介),正文根本不在它的扫描范围里。
        # 「查不到」于是被读成了「知识库里没有」——**两件事**。
        # 和 guards 里那条教训同一个形状:**拦一个动作的时候,得确认自己指的那条路真的通。**
        return {"hit": 0,
                "note": f"**结构化条目里**查不到「{keyword or cat or src}」。"
                        f"不要凭印象回答 —— 但也别就此打住:"
                        f"**怎么洗、怎么存、为什么这么做这类话在正文里,不在条目里**,"
                        f"用 `kb_read` 先看目录(比如 `kb_read(\"09\")` 是养护与售后)。",
                "正文有这几篇": {k: v[1] for k, v in KB_DOCS.items()}}
    return {"hit":len(rs),"rows":[_nz(_with_source(_with_material(r))) for r in rs[:12]]}

# 面料的**物理参数**(备料天/现货/单价/损耗/幅宽)家在 material 表,不在知识库条目里。
# craft.lead_days 对**工艺**条目有值(工期档位),对**材质**条目一律为空。
# 原来 kb_detail 直接把这个空值返回去,模型如实回答「知识库里还没有录入」——
# 而 material 表里明明写着 12 天,kb_lead 和 get_stock 也都能查到。
# **工具说了假话,模型没错。** 换模型对照时露出来的:同一个问题,
# 一个模型走 kb_lead 答「12 天」,另一个走 kb_detail 答「未录入」。
_MAT_FIELDS = ("备料天", "现货", "单价", "计价单位", "损耗率", "幅宽cm")

def _nz(d):
    """**值为空的字段整个去掉,不要发给模型。**

    `null` 和「没有这个字段」对人是一回事,对模型完全不是:
    看到 `cost_level: null`,它会如实回答「成本档位知识库里还没录入」——
    可成本档位本来就只对**工艺**条目有,形制/材质根本没有这一项。
    「未录入」和「不适用」被同一个 null 表达了,而它只能照着字面说。

    少一个字段,模型不会去提它;给一个空字段,模型一定会提它。"""
    return {k: v for k, v in dict(d).items() if v not in (None, "")}

def _with_source(d):
    """给每一条知识贴上**来源等级 + 对客口径 + 溯源状态**。

    2026-09-15 加。原来返回里只有一个 `src_type`,而那三个字**不够**:

      · 只给档位  —— 读的人以为标着 `public` 就有出处。
        实测 29 条 public 里 **15 条连出处的名字都没有**,scale 32 条里 31 条没有。
        **一个标着「公开可查、可溯源」却给不出出处的条目,比标着 demo 更糟**:
        标 demo 的没人敢拿去承诺,标 public 的顾问会照着它对客户说。
      · 只给出处  —— 读的人不知道这一条能不能对外说。

    **我不替它编出处,也不替它降档**(降档是说另一个方向的假话)。
    做的是第三件事:**让它自己说出来** —— 「标着可溯源,但库里没有出处」
    跟着这一条一起被读到,模型没法再把它当成有出处的知识往外说。
    **补出处是人的活,不许假装有出处是代码的活。**
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import source as _src
    d = dict(d)
    档 = d.pop("src_type", None)
    if not 档: return d
    d.update(_src.标注(档, d.get("src_name"), d.get("src_url")))
    d.pop("src_name", None); d.pop("src_url", None)
    return d


def _with_material(d):
    """材质条目补上物理参数。**同一个事实只留一个字段** —— 空的那个要拿掉,
    留着它就等于给模型两个矛盾的来源,而它没法判断该信哪个。"""
    if (d.get("cat") or "") != "材质": return d
    m=_rows("SELECT price,unit,loss_rate,lead_days,stock_qty,width_cm FROM material WHERE code=?",
            d.get("code"))
    d=dict(d)
    if m:
        d.update(备料天=m[0]["lead_days"], 现货=m[0]["stock_qty"], 单价=m[0]["price"],
                 计价单位=m[0]["unit"], 损耗率=m[0]["loss_rate"], 幅宽cm=m[0]["width_cm"])
        d.pop("lead_days", None)
    return d









# ── 「现在是谁在用这个工具」 ─────────────────────────────────────────
# 智能体的工具跑在**独立子进程**里,拿不到 HTTP 会话。身份由启动它的那一方
# 通过环境变量传进来(见 agentsite/sdk.py 的 mcp_config)。
#
# **为什么不让模型自己说自己是谁**:那就成了「我以店长身份执行」——
# 一句话就能提权。身份必须来自签发方,不能来自使用方。
# 这条和 check_write 里「授权主张 vs 查询条件」是同一条:
#   工具**按谁的身份取数**,是授权主张,只能来自会话;
#   「假如是店长,允不允许」,是查询条件,可以由参数给。
import contextvars as _cv
_ME = _cv.ContextVar("lanxiu_me", default=None)


def whoami(认系统=False):
    """当前操作人。没有身份时返回 None —— **不许兜底成某个默认角色**。

    两个来源,按优先级:
      ① contextvar —— 同进程内调用(比如服务端重跑一遍起草工具)
      ② 环境变量   —— MCP 子进程,由启动它的那一方注入
    用 contextvar 而不是全局变量:**两个请求同时进来不会互相串身份**,
    而串了不会报错 —— 甲的问题用乙的身份取数,答出来完全正常。

    `认系统`(11-24):`系统身份`(内部调用:研判队列 / 评测 / V1 V2 子进程)**默认当成没身份**,只有调用方写明
    `whoami(认系统=True)` 才拿得到它。为什么不让它在所有工具里生效:后端 40 多个读工具今天都是「没身份就拒」,
    只有客户档案那一处放行 —— 系统身份一旦处处被认,这 40 多处全部放行、再各走各的角色 / 门店分支,
    评测分数不可比,而且它就成了一把比客户档案宽得多的跨店读钥匙。**点名生效**:爆炸半径 = 显式点名的工具,
    其余零变化;以后哪个工具要给后台用,点名加,边界审计能列出名单。第一版只有 get_customer 认它。
    """
    v = _ME.get()
    if not v:
        import json as _js
        raw = os.environ.get("LANXIU_ME") or ""
        if raw:
            try: v = _js.loads(raw)
            except Exception: v = None
    if v and not 认系统 and (v.get("role") == 系统身份["role"] if isinstance(v, dict) else False):
        return None
    return v or None


class as_user:
    """`with api.as_user(me): ...` —— 在这段代码里,工具以这个人的身份取数。"""
    def __init__(self, me): self.me, self.tok = me, None
    def __enter__(self): self.tok = _ME.set(self.me); return self
    def __exit__(self, *a): _ME.reset(self.tok); return False


# 起草工具的名字 → 函数。**服务端重跑用这张表** ——
# 从轨迹里拿到模型调用起草工具时的入参,原样重跑一遍拿到草稿,
# 而不是去解析模型说了什么。模型可能把参数复述错,入参不会。
# 顺带一个好处:确认卡是**点的时候现算的**,不是两分钟前存下来的 ——
# 期间那位顾问被派了别的活,卡上的撞车提醒会跟着变。
# 会改数据的工具。**列在这儿是给检查用的** —— isolation_check 逐个确认
# 它们都从会话取身份、都走 tasks.py 那一套判定,不会因为「是智能体调的」而放宽。
WRITE_TOOLS = ("apply_adjust", "decide_approval","assign_task", "dispatch_task", "reassign_task", "finish_task",
               "assign_batch", "dispatch_batch",
               # 店长排班(用户 11-11 夜拍「后台页面 + 聊天都能排」):写草稿 / 发布。规则在 roster_write,和后台页面同一份
               "shift_draft", "shift_publish",
               # 挽回清单一键建跟进(业务需求池 D2,11-12):给顾问派电话回电,不对外发任何东西
               "recovery_followup",
               # 版师核裁片用料占比。**登记在这儿不是形式** —— 进了这张表才会被
               # `isolation_check`(从会话取身份、入参里没有身份字段)、
               # `guards.pre_tool_verdict`(一轮只写一次、同参数不许重试)、
               # `funnel`(漏斗记它走了写路径)一起管住。
               # 上一版它没进来,于是它是**唯一一个没人管的写口**,
               # 而边界审计只能靠名字里有没有 `set_` 猜它存在。
               "set_piece_ratio",
               # 版师核档差(业务需求池 P2)。⚠️ **它不改档差** —— 档差在 md 里,
               # 改 md 是人的活;这个口记的是「谁、什么时候、凭什么核过的,
               # 以及核的时候那个值是多少」。登记在这张表里才会被
               # `isolation_check` / `guards.pre_tool_verdict` / `funnel` 一起管住。
               "set_grade_diff",
               # 关差评(业务 09-27 归店长跟 + 10-11 售后确认结案)。
               # ⚠️ 它 2026-10-12 才进这张表 —— 写口在这之前**没有任何入口**。
               "close_bad_rating",
               # 白坯试衣(业务 09-22):登记试衣 / 补签(顾问、店长),开裁(版师,过白坯那道闸)
               "record_fitting", "start_cutting",
               # 量体录入(业务 09-22):按次登记,可绑订单行作下单量体
               "record_measure",
               # 交付签收(业务 09-22):到店代收 / 取件方式 / 不合身、核验 6 位码签收、顾问追认完成
               "record_pickup", "verify_fit_code", "ratify_complete",
               # 下单(业务 09-22):先开单停在待确认 → 量下单量体绑到那一件 → 确认下单(过闸,即已付款)
               "open_order", "confirm_order",
               # 报修(业务 09-22):新建返修单、店长判责(顾客同意才开工)、推进、回店输码签收
               "create_repair", "decide_repair", "advance_repair", "verify_repair_return",
               # 工厂回传(业务 09-23):延期通知完标一下、店长人工回退(发错件 / 到店返工)
               "mark_delay_told", "rollback_order",
               # 标品交付告知(用户 11-15):记「已告知」—— 只在用户明说发了才调,不是签收
               "record_delivery_notice",
               # 经营报告(用户 10-09):存草稿(每存一版,冻结当时的取数包)、店长确认(必选缺了不许确认)
               "save_report", "confirm_report",
               # 自有工坊报工(业务 09-25):它把订单一路推到已发货,**是写**。
               # 走的是工厂回传那个收件箱,但动的是真状态 —— 不登记的话它就是
               # 「唯一一个没人管的写口」(set_piece_ratio 当年正是这么漏的)。
               "report_production",
               # 发起被接管的工作流(用户 10-24 拍「打开时聊天站改走工作流」)。它本身不改澜绣的库,
               # 但会在管理后台排一条**最后要写进系统**的运行 —— 按写口管:一轮只发一次、同参数不许重试
               "start_workflow",
               # 预约(包四第一件,用户 11-25 拍):帮客户约 / 改时间。两个都是高档确认卡(预约是对客承诺);规则在 backend/appt_write
               "book_appointment", "reschedule_appointment")








MANAGER_ROLES = ("店长", "总部运营")
import datetime as _dt
import worldclock as _wc


























# ── 客户转移(用户 2026-10-25):聊天里说一句就建单;**本店的转移店长也能批**;**批准即生效** ──────────
#
# 三个入口共用这里:智能体建单 / 批单(api.apply_adjust / decide_approval)、管理后台审批中心
# (server.decide_approval)、聊天卡片的详情弹窗(server /api/approval/<id>)。
# 「是不是本店转移」「这个人能不能批」「批了改什么」**各只写一份** —— 两个入口各判一次,总有一处判松,
# 而判松的那处看起来完全正常(10-25 就是这么发现的:聊天这条路批了不转,审批中心批了才转)。











import contextlib as _cl_mod
_cl_closing = _cl_mod.closing






































def _rows2(sql, *a):
    """取裸元组(`for cid, in …` / `dict(…)` 两列成对)。和 `_rows` **同一条只读连接、同三道检查**,
    只是不转 dict —— 原来那句「只要 id,不必走那一遍」是省检查的理由,而检查省不得(W40②)。"""
    with _c() as c:
        return [tuple(r) for r in _查(c, sql, a)]


















# ── 写工具:智能体代人执行 ────────────────────────────────────────
# 这几个是**真的写库**。安全不靠「不给写」,靠三条:
#
#   ① 身份来自签发方   —— 会话里的工号,不是模型说自己是谁。
#                        一句「我以店长身份执行」不能提权。
#   ② 权限和人一样      —— 走 tasks.py 里同一套判定,**和页面上点是同一份代码**。
#                        智能体不会因为「是智能体」而多一分权,也不会少一分。
#   ③ 每一笔都留痕      —— 台账里记着是智能体代谁做的,
#                        以后要查「这条是人点的还是它自己派的」查得出来。
#
# **顾问之间的隔离由 tasks.visible_scope 一处判定**,写工具也吃这一条:
# 顾问只能完成派给自己的,店长只能派给本店的人。
def _need_me():
    me = whoami()
    if not me: raise _NoIdentity()
    return me


class _NoIdentity(Exception): pass


def _agent_log(me, code, text):
    """台账里标明这一笔是**智能体代做**的。

    不标的话,人点的和它自己做的在台账上一模一样 ——
    出事之后想知道「这条是谁的主意」就查不出来了。
    """
    from oplog import log_op as _lg
    _lg(me["name"], "agent", "-", "—", "—", True, "AGENT_" + code,
        f"智能体代 {me['name']}({me['role']})执行:{text[:90]}", {"role": me.get("role")})


































def check_write(action, fields=None):
    """**这件事业务允不允许做** —— 不写库,只跑一遍真正的校验器。

    为什么要有它:顾问问「客户姓名还没问到,能不能先建档回头补」,
    实测智能体答「**可以的,系统设计就是这么打的**」,还编了一套
    account/customer 分层的架构理由 —— 而 rules.validate_customer 返回的是
    `NEED_NAME 客户姓名必填`。它一个工具都没调,因为**没有任何工具能告诉它业务规则**。

    编造建立在真事实上(账户与门店档案确实分层),所以读起来完全可信,最难抓。

    ## 为什么是「跑校验器」而不是「把规则写进提示词」

    把规则抄进提示词就是第二份手抄件,业务改了规则、提示词不会跟着改。
    这里直接调 backend/rules.py —— **和真实写接口用的是同一个函数**,
    所以「工具说不行」和「真去建会被拒」永远是同一件事。

    ## fields 里的 role 是**查询参数,不是授权主张**

    这个区分很重要,而且它决定了 role 该不该从会话取:

      · **写接口**(create_appointment / resolve_combo)的 role 是**授权主张** ——
        「我以店长身份执行」。它必须从服务端会话取,否则谁都能自称店长。
      · **check_write 的 role 是查询条件** —— 「**如果是**店长,允不允许?」
        它不执行任何动作,所以传谁都无害;而且顾问问「店长能不能补录」是个
        完全正当的问题,必须答得了。

    所以这个工具照旧收 role,而且**默认按最低权限(顾问)算** ——
    不传就按最保守的答,免得给出一个「你其实做不到」的乐观回答。

    ⚠️ **已知约定(不是结构)**:智能体调工具时**没有身份** ——
    MCP 工具跑在 CLI 拉起的子进程里;登录身份由聊天站经 LANXIU_ME 送进来(whoami 读得到,11-24 核过,
    「拿不到登录会话」那句旧话不成立了)。但 check_write 这里的 role 仍是**查询参数**:它答的是「如果是这个角色」,
    不是「你这个人」—— 真执行那一关在写接口上按会话身份判。
    真要执行,还得本人**确实**有那个角色,那一关在写接口上,由会话把着。
    这条写进了边界审计的**约定**类,不冒充结构。

    ## 它不写库

    validate_* 都是纯函数,只读现有客户做重复判定。见边界审计「check_write 不写库」。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rules as _r
    d = dict(fields or {})
    # **说清楚是按哪个角色算的,以及这个角色是谁给的。**
    # 智能体调工具时没有身份(见 docstring 里那条约定),所以它答的永远是
    # 「如果是这个角色」。不在返回里标出来的话,「如果是店长就能」和「你现在能」
    # 在输出上分不开 —— 而后者是承诺,前者只是查规则。
    _given = (d.pop("role", None) or "").strip()
    role = _given or "顾问"
    _how = (f"{role}(你指定的角色 —— 这是「**如果是**{role}」的查询,"
            f"不代表提问的人就是{role})" if _given
            else "顾问(没指定,**按最低权限算**)")
    act = (action or "").strip()
    if act in ("建档", "新建客户", "customer", "create_customer"):
        ex = _rows("SELECT id,name,phone,shop,birthday,addr FROM customer")
        ok, code, why, sus = _r.validate_customer(d, ex, actor_role=role)
        out = {"能不能做": "能" if ok else "不能", "编码": code, "理由": why or "校验通过",
               "以什么角色判的": _how}
        if sus:
            out["疑似重复"] = [dict(id=x["id"], name=x["name"], shop=x.get("shop")) for x in sus]
            out["该怎么办"] = "转店长确认后再建档 —— 系统不替人做这个判断"
        return _nz(out)
    if act in ("预约", "补录预约", "appointment", "create_appointment"):
        ok, code, why = _r.validate_appointment(d, now=_wc.当下(), actor_role=role)   # 世界的当下:预约时间是世界数据
        return _nz({"能不能做": "能" if ok else "不能", "编码": code,
                    "理由": why or "校验通过", "以什么角色判的": _how})
    return {"error": f"不认识的动作「{action}」", "支持": ["建档", "预约"],
            "note": "只覆盖这两类写入的业务规则;别的动作请走后台审批链"}




KB_DOCS = {
    "01": ("01-形制.md", "形制:朝代、款式、怎么配"),
    "02": ("02-面料.md", "面料:特性、适合什么、怎么洗"),
    "03": ("03-工艺.md", "工艺:织造/刺绣/印染/缝制四类,什么时候能加"),
    "04": ("04-配饰.md", "配饰:什么形制配什么"),
    "05": ("05-颜色.md", "颜色:配色与忌讳"),
    "06": ("06-相容矩阵.md", "相容矩阵:什么工艺能上什么面料,以及为什么"),
    "07": ("07-工期与成本.md", "工期与成本:怎么估、什么会拖"),
    "08": ("08-量体与版型.md", "量体与版型:量哪些、怎么判档"),
    "09": ("09-养护与售后.md", "养护与售后:怎么洗、怎么存、争议怎么判"),
    "10": ("10-版型库.md", "版型库:裁片、尺码、档差、放松量"),
    "11": ("11-物料与BOM.md", "物料与 BOM:用量、损耗、备料"),
    "12": ("12-成长与生命周期.md", "成长与生命周期:孩子长多快、什么时候复量"),
    "13": ("13-销售话术.md", "销售话术:嫌贵、压价、比价、催货、再想想时怎么回"),
    "14": ("14-运营SOP.md", "运营 SOP:这单能不能下、能不能开裁、售后谁负责(从代码生成)"),
    "15": ("15-电商运营.md", "电商运营:标品补货、压货、定价系数、活动(我们的决定 vs 行业做法)"),
    "16": ("16-竞品与行业.md", "竞品与行业:别家什么价、行业多大、预售惯例(每条带抓取日期)"),
}

# **话术那篇的 demo 不是「不能对客户说」**,是「业务没审过的说法」(用户 2026-09-29 定:AI 现编、每条标 demo)。
# 照通用口径给「对客户:不能」,模型会把整节话术当禁区、回头又自己现编 —— 正好和接它进来的目的相反。
话术_DEMO口径 = ("**演示说法,业务未审**(AI 现编):当思路用,**不照念**;"
                 "里面的数(工日、米数、工期)一律以工具现查为准,示例里的 X 不许自己填")















# ── 门店业务数据(shop 服务)—— 顾问和值班同学天天要查的三样 ────────────
# **定制单几个容易读反的状态,当场说清。** 2026-09-22 签收评测:模型把「已发货」读成「已经寄给顾客」
# (PRD 状态又显示「待收货」,更像),于是把「到店代收」当成顾客签收、不肯登记。
# 措辞和 record_pickup 的描述保持一致(对方 d8ec965)—— 两处说法不一样,模型会挑一个信。
_定制状态说明 = {
    "待确认": "开了单还没确认下单 —— 不算下单、不进业绩;每一件量完下单量体并绑上才能确认",
    "已发货": "工厂发往门店,还没到顾客手里 —— 到店后门店登记「到店代收」(不涉及顾客,也不是签收,状态不变);"
              "顾客试穿合身、给出 6 位码核验通过才算签收",
    "生产中": "工厂在做 —— 完工、质检、发出都由工厂回传推动,门店不能手动推;工厂报的承诺完工日见「工厂回传」",
    "待完成": "顾客已试穿合身签收,等顾客确认完成;满 15 天没确认,顾问可写理由追认",
}








import importlib.util as _ilu, os as _os
_sr_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "knowledge", "scheme_ref.py")
_sr_spec = _ilu.spec_from_file_location("scheme_ref", _sr_path)
_scheme_ref = _ilu.module_from_spec(_sr_spec); _sr_spec.loader.exec_module(_scheme_ref)




















# 方案页的客户搜索(复审第 4 节 B,用户 10-23 拍)。
# ⚠️ 下面三样是**暂定**,业务没拍过,见交付报告的选型卡:
#   · 姓名按「包含」匹配;客户号按「整号相等」(不分大小写);手机按「尾号」,至少 4 位数字才认
#   · 每页 `方案搜客户_每页` 条,另报一共命中多少条、共几页 —— **翻页**(用户 10-23 选型卡拍「加分页」;
#     其余三条暂定值同日定下:姓名包含、客户号全号、手机尾号至少 4 位)
方案搜客户_每页 = 20
方案搜客户_尾号最少位数 = 4














# ── 着装人与成长推算 ────────────────────────────────────────────────────
# 这两个工具是**只读**的,而且**同意状态是硬门**:没有有效同意就拿不到身体数据,
# 也算不出推算 —— 不是「模型应该守规矩」,是「不守也拿不到」。
# 这个区别在本项目里付过学费:一条靠约定守着的边界,换个模型就破了。
_GROWTH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
if _GROWTH_DIR not in sys.path: sys.path.insert(0, _GROWTH_DIR)






# 当前生效的协议版本。**字段有值不等于同意有效** ——
# 条款改版之后,旧版本的同意就该重新取,而这件事没人比对就永远不会发生。
TOS_NOW, PRIVACY_NOW = "v2.3", "v1.5"
# 账户状态 → 顾问该怎么办。**状态是给行动看的,不是给人看的。**
ACCT_ACTION = {
    "正常":   None,
    "锁定":   "账户已锁定(连续输错密码)。**不要在电话里帮客户改密码或绕过锁定** —— "
              "让客户自助解锁,或按门店流程走身份核验。",
    "注销中": "客户已申请注销,正在冷静期。**不要推进新订单、不要做营销触达**;"
              "如果还有在办的单,先问清楚是要撤回注销还是把单收尾。",
    "已注销": "账户已注销,**个人数据已删除**。查不到尺寸、偏好、着装人是正常的 —— "
              "不要凭印象补,也不要让客户「报一下就行」。要下单请重新注册。",
}






































# 哪一种报告**结构上**取不到哪几项(不是这一期碰巧没数):{期间: {指标: 写进口径的理由}}。
# **只写这一处** —— store_report 用它置空,report_template 用 ast 读它(那种报告里取不到的不许标必选,
# 用户 10-23 选 B:设成必选会导致每一期都确认不了)。要是哪天日报也算成交率了,删掉这一条,两边一起变
报告期取不到 = {"日": {"成交率": "日报不报成交率:一天的样本太小,数字会乱跳(定制单从接待到下单常要一两个月)"}}
# 环比里每一行是哪个指标的数 —— 那个指标被报告模板隐藏时,环比里这一行一起拿掉
_环比指标 = {"订单量(下单数)": "订单", "销量(卖掉的件数)": "销量"}

# 取数包口径的版本:**改了取数口径就升这个号**(加指标、改单位、改去重都算)
# ⚠️⚠️ 用点不用连字符(10-22 改):版本号冻在取数包(store_report_doc.pack)里,而那一列登记了每日平移
# (要和报告期同一套世界)。平移认日期只看「四位-两位-两位」的形状 —— 原来写成 `2026-10-21.1`,
# **每天早上被当成日期往后挪一天**:10-22 库里那份已确认周报冻的是「2026-10-22.1」,一个从没存在过的版本。
# > 一个「版本号」和一个「日期」,在那条正则眼里长得一模一样。判据 store_report_check 拿平移真的挪字函数验。
报告口径版本 = "2026.10.23.1"   # 10-23:被模板隐藏的指标从包里拿掉、顶层列「被隐藏的」(数据工厂指出:包的构成变了而号不升,前后两份包在号上一模一样); 10-21:加「上期定的行动」(经营复盘闭环); 10-12:加「并排读时要说清的」(成交率窗口、下单 vs 销量订单);10-10:加到店客户数(去重)、售后新建 / 结案、规则版本留底
















# 「下一周的订单」到底查哪一列 —— 四个字段是四份完全不同的单子
# 中文月份 → 数字。**一张显式的小表,12 条,不是自然语言解析。**
#
# 它只用在一件事上:调用方把「一月」原样传进来时,**认出他说的是几月**,
# 然后走「判不了」那条路把两种读法摆出来 —— 而不是替他猜。
# > 一个「猜对了」的月份,和一个「问清了」的,**在那份清单上长得一模一样** ——
# > 而猜错的那次,清单看起来完全正常。
_中文月 = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
         "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}

_订单日期列 = {
    "下单": ("created",      "客户下单的时间"),
    "完工": ("produced_at",  "工厂报完工的时间(定制单才有)"),
    "发货": ("shipped_at",   "发出的时间"),
    "交付": ("finished_at",  "到客户手上 / 订单完成的时间"),
}




def _订单范围(me):
    """这个人能看到哪些订单。返回 `(where 片段, 参数, 范围人话, 顾问工号或None)`。

    业务 2026-10-06 拍的三档,**顾问那一档是并集**:

        总部运营   全部门店
        店长       本店
        顾问       **他名下客户的单 ∪ 他经手下的单**

    ⚠️ 为什么是并集:这两种读法在 **39% 的订单上给出不同名单**
    (31660 单里 12393 单的「订单上的顾问」和「客户归属顾问」不是同一个人)。
    · 只算「名下客户」→ 他帮同事客户下的单,他自己看不到
    · 只算「经手的单」→ 他休假时同事帮他客户下的单,他看不到

    ⚠️ **而并集之后每一行必须标清是哪一种**,两个数也要分开报:
    > 一份「我的客户的单」和一份「我做的单」混成一个数,
    > **业绩就说不清了** —— 而混之前和混之后,那个总数长得一模一样。
    """
    import order_scope as _范
    role, no, shop = me.get("role"), me.get("no"), me.get("shop")
    话 = _范.范围话(角色=role, 门店=shop)
    if role == _范.总部运营:
        return "", [], 话, None
    if role == _范.店长:
        if not shop:
            # ⚠️ **判不了不等于看全部。** 口径那边同一条:算不出「本店」就不放行。
            # 这里给一条永远不成立的 where —— 返回空清单,而 `话` 里写着为什么。
            return " AND 1=0", [], 话, None
        # 按门店码筛。`_片` 为空走不到这儿(上面那条 `if not shop` 已经拦了),
        # `or '1=0'` 是防御 —— **判不了也不许兜底成看全部**,那是上面那条注释的同一件事
        _片, _参 = _门店条件(shop, "o")
        return f" AND {_片 or '1=0'}", list(_参), 话, None
    if role == _范.顾问:
        if not no:
            return " AND 1=0", [], 话, None
        # 并集:**这一单是他做的** ∪ **这个客户现在归他**。两边都要带上,
        # 而且下面按这两列算标签。
        #
        # ⚠️ **第二支读的是 `o.cust_advisor_no`(订单上的冗余列),不是 `cu.advisor_no`。**
        # 2026-10-25 改的。原来那个 OR **跨了两张表**,SQLite 只能全表扫 ordr
        # (2.6 万行,19–20 ms),**而加索引修不了**。冗余一列之后 OR 落在同一张表上,
        # 计划变成 `MULTI-INDEX OR`(两个索引取并集),实测 **8.22 ms,2.3 倍**。
        # 两种写法**结果等价** —— 同一个顾问、同一个区间实测都是 5172 单
        # (那一列由三个触发器保证和 `customer.advisor_no` 全量一致)。
        #
        # ⚠️ **别把它改回 `cu.advisor_no`。** 改回去**结果一样、只是慢** ——
        # 所以不会有任何东西红,而这正是它危险的地方。
        # 守这件事的是 `backend/cust_advisor_check.py`(它断言这条片段读的是
        # 订单上那一列,而不是跨表那一列)。
        return " AND (o.advisor_no=? OR o.cust_advisor_no=?)", [no, no], 话, no
    # ⚠️ 三档之外(工匠/版师/财务)**不兜底成「本店」** ——
    # 兜一个出来的话,一个财务就能看到全店订单,而界面上看不出异常。
    return " AND 1=0", [], 话, None















_受欢迎维度 = ("形制", "面料", "工艺")







# ── 标品退货率 / 换货率 / 退货原因(2026-11-15,用户清单第六条 + 算法选型卡)─────────────
_退货维度 = ("品类", "商品", "渠道")


















def _seed_today():
    from seed import TODAY
    return TODAY



# ── 场景倒推 ────────────────────────────────────────────────────────────
# 「明年六月毕业礼要穿」这句话,拆开是四个互相咬着的约束:
#   ① 选码要用**穿的那天**的身高,不是下单那天的
#   ② 下单太晚 → 排不上产能,做不出来
#   ③ 下单太早 → 用的量体更旧、推算跨度更长,**误差更大**
#   ④ 下单前必须有**没过期**的量体记录
# 所以答案不是一个日期,是**一个窗口**:什么时候约复量、什么时候下单。
# 只回答「最晚哪天下单」是把 ③ 漏了 —— 而 ③ 恰恰是童装做小了的主因。
# 交付告知的六条(见 09-养护与售后.md 第三节)。库里存代码,对外给名称 ——
# 判责时「有没有告知过色差」这种问题,看代码是答不了的。
NOTICE_NAME = {"N1": "N1 面料特性", "N2": "N2 色差与掉色", "N3": "N3 手工痕迹",
               "N4": "N4 洗护方式", "N5": "N5 尺寸容差", "N6": "N6 工期与延期"}

GIRTH = {"胸围", "腰围", "臀围", "领围", "胸上围", "臂围"}
FIT_BUFFER = 7      # 交付到穿之间留的试穿与小改天数(业务 2026-09-22 确认,附录 A-24)
FAR_DAYS = 60       # 离最晚下单日超过这么多天:推算跨度太长,改推换商品(业务 2026-09-22 确认)
# 尺寸宽容的形制 —— 现在下单也不怕长个:08-量体与版型.md「报废风险 · 低」那几类(大袖衫、半臂、比甲、
# 方领对襟短衫、披风),加上童款襦裙(01-形制.md:系带改为松紧或魔术贴)。立领、马面裙这类贴体款不推。
TOLERANT_XZ_ADULT = ("XZ05", "XZ06", "XZ18", "XZ22", "XZ24")
TOLERANT_XZ_CHILD = ("XZ39",)





# ── 预约:查 / 约 / 改(包四第一件,用户 2026-11-25 拍)。业务逻辑在 backend/appt_write,旧后台页面调的也是它 ──
def list_appointments(customer=None, date=None, advisor=None, status=None, limit=20):
    """本店(跨店角色:全部)的预约。筛客户 / 日期 / 顾问 / 状态;默认只给进行中的(待确认 / 已预约 / 已到店)。"""
    import appt_write as _AW
    try: me = _need_me()
    except _NoIdentity: return dict(error="没有身份,看不了预约 —— 请先登录", 范围="本店")
    return _nz(_AW.列(me, 客户=customer, 日期=date, 顾问=advisor, 状态=status, 限=limit))

def book_appointment(customer, start, end=None, way="到店量体", advisor=None, named_state=None, named_advisor=None, channel=None):
    """(写)帮客户约:只约本店客户;时间按预约规则(提前量 / 补录只许店长及以上);落「待确认」。发起人是谁从登录会话取。"""
    import appt_write as _AW
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在约 —— 请先登录")
    r = _AW.新建({"客户": customer, "开始": start, "结束": end, "方式": way, "顾问": advisor,
                  "点名三态": named_state, "点名工号": named_advisor, "渠道": channel}, me)
    if r.get("ok"): _agent_log(me, "BOOK_APPT", f"建预约 {r.get('id')}:客户 {r.get('客户')} {r.get('开始')}")
    return _nz(r)

def reschedule_appointment(appointment_id, start=None, end=None, advisor=None):
    """(写)改预约时间 / 换顾问:只改本店、只改待确认 / 已预约的;新时间按同一套预约规则。要预约号(先 list_appointments)。"""
    import appt_write as _AW
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在改 —— 请先登录")
    r = _AW.编辑({"预约号": appointment_id, "开始": start, "结束": end, "顾问": advisor}, me)
    if r.get("ok"): _agent_log(me, "RESCHEDULE_APPT", f"改预约 {appointment_id}:{r.get('原时间')} → {r.get('新时间')}")
    return _nz(r)

SHOP_SCHEMAS=[
 {"name":"get_tasks","description":"**查任务 —— 四种问法一个口。** 不给参数=我自己的活;给 task_id=某一条的详情;scope=\"待分配\"=待分配池(客户约了时间但没自动派出去的,每条带 agent 的人选建议和依据,**建议不是决定**,要店长确认);scope=\"团队\" 或给 assignee=按人看(带每人在办件数、最近到期、在办明细,还会列出手上没活的人)。\n\n**范围跟身份走,隔离在查询层不在界面**:顾问只看得到派给自己的(知道单号也看不到别人的),店长看本店,总部看全部。⚠️ **「你看不到他的活」和「他没有活」是两回事**,返回里会分开说。status 可选只看某一档(有效/完结/取消/无效)。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029。给了就只看这一条。"},
    "scope":{"type":"string","enum":["我的","团队","待分配"],"description":"看谁的。不传=我的。"},
    "assignee":{"type":"string","description":"只看这一个人,工号或姓名(等同 scope=团队 再筛一个人)"},
    "status":{"type":"string","description":"只看这一档:有效 / 完结 / 取消 / 无效。不传看全部。"}},
   "required":[]}},
 {"name":"get_member","description":"**查会员分层 —— 等级和生命周期一次给全。** 给 customer(客户号或姓名)返回这个人的**会员等级档**(凭什么、离下一档还差多少)、**生命周期档**(八档中的哪一档、凭什么、有没有人工覆盖)和**归属顾问**(工号 + 姓名岗位;**给某个客户派回访 / 跟进任务前先查这里,别说「没查到归属顾问」就去问人**);给 lifecycle 列这一档里有哪些人(**人数看 hit,rows 最多列 40 个**);再加 rank=true 按 **RFM 三维**排出「先联系谁」;再加 entered_month 查「某个月进入这一档的有多少」(九月 / 本月进入休眠的…)。\n\n范围跟身份走:顾问看自己名下,店长看本店,总部看全部;返回里的「范围」说明是谁的数。按姓名查重名时不给明细,要客户号。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号(如 C10001)或姓名。姓名可能重名,重名时要改用客户号。"},
    "lifecycle":{"type":"string","description":"按档位筛,如「潜在流失」「休眠」"},
    "rank":{"type":"boolean","description":"true=在这一档里按 RFM 排出先联系谁"},
    "entered_month":{"type":"string","description":"和 lifecycle 一起给:查**这个月进入这一档**的人(YYYY-MM,本月就写当月)。只有休眠 / 潜在流失 / 流失推得出进入日(最后互动 + 91 / 181 / 366 天);是推算不是换档记录,返回的 note 要照实转告"},
    "entered_week":{"type":"string","description":"周报用:和 lifecycle 一起给,查**某一个业务周(周一到周日)进入这一档**的人,给那一周里任意一天 `YYYY-MM-DD`;口径同 entered_month"},
    "limit":{"type":"number","description":"排序时返回前几名,默认 10,最多 40"}},
   "required":[]}},
 {"name":"task_types","description":"九种任务类型的**数据规范**:每种挂哪张单据(客户号/订单号/维保单号/售后单号/不挂)、谁能派、完成时要不要传现场照。**起草派任务之前先调这个** —— 类型决定了要填什么,填错会被拒。",
  "input_schema":{"type":"object","properties":{},"required":[]}},
 {"name":"week_grid","description":"**日程占用的格子**(读的是任务/预约,**不是排班表**):一周里每个顾问哪天什么时段已经被占了、哪几天一条日程都没有、待分配还有几条。**排班之前必须先看这个** —— 不看就排,排出来的东西和正常任务长得一模一样,直到那天两个人同时约在一个时段。只有店长看得到。\n\n⚠️ **问「这一周的班排了没有」「某某那天上不上班」要用 `on_shift`**,不是这个。这里的「没有日程」只表示那个时段没被占,**不表示他那天上班**。",
  "input_schema":{"type":"object","properties":{
    "start":{"type":"string","description":"从哪天起,YYYY-MM-DD,默认今天"},
    "days":{"type":"number","description":"看几天,默认 7,最多 14"}},"required":[]}},
 {"name":"conversion_rate","description":"**成交率:返回两个数,回答的是不同的问题** —— ① 按接待人算(每次接待后面有没有跟着成交,业务明说这样算不对)② 按归因算(业务要的那个:按客户算,门店 = 成交客户 ÷ 亲自接待过的客户,顾问 = W 型份额之和 ÷ 他亲自接待过的客户)。接待 = 到店 / 上门量体、白坯试衣、预约到店(远程量体不算)。报数必须说清是哪一个,别自己拿订单数除一除编一个率。",
  "input_schema":{"type":"object","properties":{"week":{"type":"string","description":"周报用:**最近 4 周滚动**成交率(截到这一周的周日往前 28 天,同期口径),给那一周里任意一天 `YYYY-MM-DD`。顾问排名按归因成交份额排"},
    "shop":{"type":"string","description":"只看某个门店。不给就按你的身份来(店长看本店,总部看全部)。"},
    "mode":{"type":"string","enum":["同期","队列"],"description":"统计周期口径。不给=不分周期(全部数据)。**长周期生意看队列**:同期会把「这个月接待、下个月下单」的客户算成没成交。"},
    "month":{"type":"string","description":"哪个月,YYYY-MM。给了 mode 才用;不给就是当月(可能还没满 N 天,率偏低)。"},
    "n_days":{"type":"number","description":"队列口径的 N:首次接待后几天内下单算成交。默认 90(覆盖约八成成交);可改 30/60。"}},"required":[]}},
 {"name":"customer_history","description":"**这个客户之前谁接触过、做了什么** —— 五张表(预约/跟进/日程/量体/下单)里的触点连成按时间排的一条线。顾问打电话之前看一眼:上次是谁跟的、聊到哪儿了。范围跟身份走:顾问看自己名下的,店长看本店。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号(如 C10001)或姓名。姓名重名时会要你改用客户号。"},
    "limit":{"type":"number","description":"最多列几个触点,默认 30,最多 100"}},"required":["customer"]}},
 {"name":"deal_credit","description":"**这一单谁有贡献,贡献多少。** 给 order 看某一单(还会按 W 型归因算一次影响力);给 staff 看某个人;都不给看范围内的概况。返回分两栏:收入分成(加起来必须 100,算提成用)和影响力分成(可以超过 100,记贡献),每条带来源(人工填 / 规则算 / 算法算,算法算带版本)。这不是成交率(那个用 `conversion_rate`)。",
  "input_schema":{"type":"object","properties":{
    "order":{"type":"string","description":"订单号。给了会附带按 W 型归因算一次。"},
    "staff":{"type":"string","description":"工号或姓名,只看这个人的。"},
    "limit":{"type":"number","description":"每一栏最多几条,默认 20,最多 100"}},"required":[]}},
 {"name":"on_shift","description":"**谁哪天上班,以及那个人那个时候能不能接** —— 读的是**排班表**(上不上班、什么班次),不是日程占用(那个用 `week_grid`)。给 staff(+date,+at 如 \"15:00\")= 看这一个人;只给 date 或什么都不给 = 看本店未来几天的排班概况。返回五种「不上班」码(UNSCHEDULED / DRAFT / OFF / LEAVE / OUT_OF_SHIFT)和「还没排班的日子」。范围跟身份走:店长 / 顾问看本店,总部看全部。",
  "input_schema":{"type":"object","properties":{
    "staff":{"type":"string","description":"工号或姓名。给了就只看这一个人。"},
    "date":{"type":"string","description":"哪天,YYYY-MM-DD。不给就是今天。"},
    "at":{"type":"string","description":"几点,如 15:00。给了会判这个时段落不落在他的班里。"},
    "days":{"type":"number","description":"概况看几天,默认 7,最多 14"}},"required":[]}},
 {"name":"revive_list","description":"**这些客户现在该不该联系,以及联系他说什么** —— 回答「为什么是他、为什么是现在」。返回该联系的名单(每条带由头:往年同期 / 生日临近 / 上一单该回访 / 维保没办完 / 断了自己的节奏)、没进名单的五类(JUST_BOUGHT / AFTERSALE / RECENT_CONTACT / NO_REASON / NOT_YET)和「这几个门槛是拍的」一栏。范围跟身份走:顾问看自己名下,店长看本店,总部看全部。问「通话里有没有生意」用 `call_opportunity`,问「她是不是在流失」用 `churn_watch`。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号或姓名。给了就只看这一个人,并单列他的判断。"},
    "limit":{"type":"number","description":"名单最多返回几条,默认 20,最多 100"}},"required":[]}},
 {"name":"churn_watch","description":"**这些客户是不是在往下走(活跃度档位有没有退),以及退到哪一步。** 范围跟身份走:顾问看自己名下,店长看本店,总部看全部。返回预警名单、没进预警的六类(STABLE / IMPROVING / RECOVERED / GONE / NO_HISTORY / NEVER_BOUGHT)和「没有档位历史」一栏。问「今天该联系谁」用 `revive_list`(看有没有由头),这个看的是在不在流失。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号或姓名。给了就只看这一个人,并单列她的判断(含「她最好的时候是哪天、哪一档」)。"},
    "limit":{"type":"number","description":"名单最多返回几条(按高→中→低分配),默认 20,最多 100"}},"required":[]}},
 {"name":"call_opportunity","description":"**这些通话里有没有值得跟进的生意** —— 看通话逐字稿里客户提过的偏好,和店里现在有没有对得上的货。三种用法:不给参数 = 规则层候选清单(免费、确定,**是候选不是结论**);给 customer(客户号或姓名)= 这一个人深判(规则层 + 模型层,一次模型调用);给 call(通话号)= 整理这一通(原文 + 对得上的在架商品 + 名下方案 / 订单号,不调模型)。返回里带四种「不是商机」的原因码。范围跟身份走:顾问看自己名下,店长看本店,总部看全部。问「今天该联系谁」用 `revive_list`。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号(如 C10001)或姓名。给了就深判这一个人(会调模型);不给就列候选清单。"},
    "call":{"type":"string","description":"通话号(如 TS-001)。给了就**整理这一通**:返回逐字稿原文、客户提到的偏好、每个偏好现在对得上的在架商品、这位客户名下的方案和订单号 —— 不调模型(研判由你读原文来做)。返回里单列「客户号」:手上只有通话号、要客户号时用它。"},
    "limit":{"type":"number","description":"清单最多返回几条,默认 20,最多 100"}},"required":[]}},
 {"name":"ownerless_list","description":"**谁实际上没人管**(只查不改)—— 「有归属顾问」不等于「有人管」:停用顾问名下挂着的客户,顾问字段非空,按「有没有顾问」筛查不出来。顾问问「我名下的客户有没有问题」也用这个。返回五种码(LEFT / NONE / CROSS_SHOP / NO_SUCH / NO_SHOP)、`NEVER_TOUCHED`、「看的范围」和「待确立归属」人数;`code` 可只看某一种。范围跟身份走:店长看本店,总部看全部,顾问看自己名下那一份。",
  "input_schema":{"type":"object","properties":{
    "code":{"type":"string","description":"只看某一种或几种码,逗号分隔,如 LEFT,NO_SUCH。不给看全部。"},
    "limit":{"type":"number","description":"清单最多返回几条,默认 50,最多 200"}},"required":[]}},
 {"name":"assign_batch","description":"**一次排一批任务**(排班用,真的写进去)。items 是列表,每条 {type, assignee, note, start, end, ref_id?, activity_code?},一次最多 20 条。**全过才写,一条不过就整批不写** —— 半途失败留下几条已排几条没排,比整批失败难收拾得多。而且它会检查**只有整体看才发现的冲突**:同一个人被排了两个重叠时段。⚠️ 排之前先 week_grid() 看现有占用,并把整张表念给用户确认。",
  "input_schema":{"type":"object","properties":{
    "items":{"type":"array","description":"要排的任务列表",
      "items":{"type":"object","properties":{
        "type":{"type":"string","description":"任务类型,见 task_types()"},
        "assignee":{"type":"string","description":"派给谁,工号或姓名"},
        "note":{"type":"string","description":"日程描述"},
        "start":{"type":"string","description":"开始 YYYY-MM-DD HH:MM"},
        "end":{"type":"string","description":"结束 YYYY-MM-DD HH:MM"},
        "ref_id":{"type":"string","description":"挂的单据号,类型要求时才填"},
        "activity_code":{"type":"string","description":"绑定活动,可不填"}},
        "required":["type","assignee","note","start","end"]}}},
   "required":["items"]}},
 {"name":"shift_preview","description":"**(只读)本店一周的排班 + 发布预览** —— 排的是**班次**(谁哪天上早班 10–16 / 晚班 16–22 / 全天 / 休息),**不是任务**(任务用 week_grid / assign_batch)。返回每人每天的「已发布 / 草稿 / 请假」,店长还会拿到「发布预览」:违规(拦发布:每人每周至少休一天、最多连上 6 天,跨周也算)、提示(谁哪几天没排)、受影响(发布后那天做不了的已派单)。⚠️ 排班 / 发布之前**先调它**,把表和这三样念给店长。week 给那一周里任意一天 `YYYY-MM-DD`,不给 = 本周。","input_schema":{"type":"object","properties":{"week":{"type":"string","description":"那一周里任意一天 YYYY-MM-DD;不给 = 本周"}}}},
 {"name":"shift_draft","description":"**(写)排班次 → 写成草稿**:员工看不到、派单不用,店长发布才生效。items 是列表,每条 {工号 或 姓名, 日期 YYYY-MM-DD, 班次 S1 早班 / S2 晚班 / S3 全天 / S0 休息(写中文名也认)}。**全过才写,一条不过整批不写**;只排本店在职顾问;过去的日子不改。⚠️ **休息要排出来** —— 没排的日子不算休息,发布时会拦「每周至少休一天」。⚠️ 先 shift_preview 看现状、把要排的整张表念给店长,他说「就这么排」再调。只有店长能排。","input_schema":{"type":"object","properties":{"items":{"type":"array","items":{"type":"object"},"description":"[{工号或姓名, 日期, 班次}…]"}},"required":["items"]}},
 {"name":"shift_publish","description":"**(写)发布本店一周的排班草稿**,发布后才生效(员工看得到、派单按它)。有违规(每周没休 / 连上超过 6 天)**不发布**,把违规原话给店长。发布后有已派的单那天做不了时:confirm_affected 不给或 false → **只回那张清单、不写**;**先把清单念给店长、他说确认后**才带 confirm_affected=true 再调 —— 那样会照发,并给店长逐条建「待改派」任务。⚠️ 不要替店长确认。只有店长能发布。","input_schema":{"type":"object","properties":{"week":{"type":"string","description":"那一周里任意一天 YYYY-MM-DD"},"confirm_affected":{"type":"boolean","description":"店长看过受影响清单并确认后才给 true"}},"required":["week"]}},
 {"name":"bad_ratings","description":"**差评清单**:签收后顾客给了 ≤3 星、还要人跟的那些(工单、包裹、订单、几星、顾客原话、有没有处理过)。status 可给「待处理」「已关闭」「全部」,不给就是待处理。**店长和售后看得到**(业务 2026-09-27:差评归店长跟、不进顾问考核;2026-10-11:售后确认结案 —— **跟客户和结案是两件事,两句并存**)。售后不属于某一家店,看全量。⚠️ 关掉一条用 `close_bad_rating`,**必须写处理记录**(「看过了」不算处理完)**而且必须给处理方式**;出钱的那几种(" + _出钱表 + ")还要批准人、**退款还要给金额** —— 见 TK14。⚠️ 这儿原来写的是「出钱的**三种**」,而出钱的只有两种 —— 和 TK14 那句「后三种」同一个病:**手抄的数字跟不上枚举**,「优惠券」被拍掉那天它没跟上。⚠️ 顾客把差评改成好评的,**清单里那条不撤** —— 撤掉就看不出「差评被处理好了」和「从来没有差评」的区别,返回里会标「顾客改过」。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"待处理 / 已关闭 / 全部,默认待处理"}},"required":[]}},
 {"name":"service_records","description":"**这一单允许查看的服务记录(只读)** —— 判差评时看「之前发生过什么」。给 pkg(差评清单里的包裹号)或 order_id,两个都不给会报错。返回三类,都限定在这一张订单 / 这一个客户:① 交付与签收 ② 返修与售后 ③ 这个客户历史上的差评(带上次的处理方式)。只给店长 / 售后 / 总部运营;店长只看本店,售后和总部跨店。","input_schema":{"type":"object","properties":{"pkg":{"type":"string","description":"包裹号(差评清单里的「包裹」那一列)"},"order_id":{"type":"string","description":"订单号。和 pkg 给一个就行"}}}},
 {"name":"close_bad_rating","description":"**关掉一张差评工单(真的写进去)**。店长或售后用。pkg 填包裹号(差评清单里那一列);note 写**处理记录**;way 填**处理方式,只认登记过的这几种**:" + _方式表 + ";**出钱的那几种(" + _出钱表 + ")必须另给 approved_by(批准人工号,不能是你自己)**,不出钱的那几种(" + _不出钱表 + ")不要填。⚠️ **动手前先跟用户对一遍**:哪一张、怎么处理的、出不出钱、谁批的。","input_schema":{"type":"object","properties":{"pkg":{"type":"string","description":"包裹号(差评清单里的「包裹」那一列)"},"note":{"type":"string","description":"处理记录:具体做了什么。「看过了」不算"},"way":{"type":"string","description":"处理方式,只认这几种之一:" + _方式表 + "(**没有优惠券这一档** —— 业务 09-24「不让价,只让东西」)"},"approved_by":{"type":"string","description":"批准人工号。**只有出钱的那几种(" + _出钱表 + ")要填**,而且不能是你自己。⚠️ 超过 " + str(_R方式.退款上升一级的线) + " 的那一笔,批准人必须是「" + _R方式.上升一级要谁批 + "」(用户 2026-10-14 拍)"},"amount":{"type":"number","description":"**这次退了多少钱**。「部分退款」**必填**,而且不能超过这一单的订单额;「全额退款」**不要填**(金额就是订单额,系统现算);不出钱的那几种填了会**被拒**。⚠️ 超过 " + str(_R方式.退款上升一级的线) + " 的要「" + _R方式.上升一级要谁批 + "」批 —— 而这一笔的订单额和批准人角色**系统自己从库里读**,你报的数不作数"}},"required":["pkg","note","way"]}},
 {"name":"rating_overview","description":"**评价概况**:最近多少天多少条、平均几星、各星几条、差评几条占多少,并按门店拆、按月拆。days 默认 30,看趋势要放大(三个月写 days=120)。**只有店长看得到**,店长只看本店,跨店比较要总部运营。",
  "input_schema":{"type":"object","properties":{
    "days":{"type":"integer","description":"往前看多少天,默认 30"},
    "week":{"type":"string","description":"周报用:看**某一个业务周**(周一到周日),给那一周里任意一天 `YYYY-MM-DD`;给了就不看 days"},"start":{"type":"string","description":"自由区间的**起**那天 `YYYY-MM-DD`。⚠️ **要和 end 一起给**,只给一个会被拒。给了区间就不看 days / week —— 用它来答「10 月 1 日到 10 月 20 日的评价概况」这种现成档位表达不了的跨度"},"end":{"type":"string","description":"自由区间的**止**那天 `YYYY-MM-DD`(含当天)。要和 start 一起给"}},"required":[]}},
 {"name":"dispatch_batch","description":"**一次把待分配池里的几条单分出去**(真的写进去)。items 是 [{task_id, assignee?}],不给 assignee 就采纳 dispatch_pool 给的建议,一次最多 20 条。**全过才写,一条不过整批不写。** 用户说「把待分配的都派了」「这几条都分下去」时用这个 —— assign_batch 是**新建**任务的,派不了已经存在的单。",
  "input_schema":{"type":"object","properties":{
    "items":{"type":"array","description":"要分派的单",
      "items":{"type":"object","properties":{
        "task_id":{"type":"string","description":"任务号,如 SC7032"},
        "assignee":{"type":"string","description":"分给谁。不给则采纳建议。"}},
        "required":["task_id"]}}},
   "required":["items"]}},
 {"name":"monthly_review","description":"**月度复盘**:这个月做完了多少、几条逾期、逾期都在谁身上、改派几次和理由、**agent 的派单建议采纳率**、智能体代做了几笔、待分配积压、订单走完一轮要多久。month 写 `2026-09`,不给就是当月。按**截止时间**归月(复盘看的是「这个月该做完的做完了没有」)。范围跟身份走:顾问只看自己的,店长看本店。⚠️ **分母为零的地方不给比率,给一句话** —— 「没发生过分派」和「分派了但一次没采纳」是两件事。",
  "input_schema":{"type":"object","properties":{"week":{"type":"string","description":"周报用:看**某一个业务周**(周一到周日),给那一周里任意一天 `YYYY-MM-DD`;给了就不看 month"},
    "month":{"type":"string","description":"哪个月,写 2026-09。不给就是当月。"},"start":{"type":"string","description":"自由区间的**起**那天 `YYYY-MM-DD`。⚠️ **要和 end 一起给**,只给一个会被拒。给了区间就不看 week / month —— 用它来答「9 月 15 日到 10 月 15 日这一段」这种现成档位表达不了的跨度"},"end":{"type":"string","description":"自由区间的**止**那天 `YYYY-MM-DD`(含当天)。要和 start 一起给"}},"required":[]}},
 {"name":"list_appointments","description":"**查预约**(本店;总部运营 / 售后看全部):按客户(号或名)、日期(2026-11-28)、顾问、状态筛;默认只给进行中的(待确认 / 已预约 / 已到店),按开始时间排,给预约号。客户问「我约了几号」、顾问问「明天谁来」用它。改时间要先在这里拿到预约号。","input_schema":{"type":"object","properties":{"customer":{"type":"string","description":"客户号或姓名(可省)"},"date":{"type":"string","description":"哪一天,2026-11-28(可省)"},"advisor":{"type":"string","description":"顾问工号或姓名(可省)"},"status":{"type":"string","description":"待确认 / 已预约 / 已到店 / 已完成 / 已取消 / 已过期 / 爽约(可省,省了只给进行中)"},"limit":{"type":"integer","description":"最多几条,默认 20"}}}},
 {"name":"book_appointment","description":"**(写)帮客户约**:客户(号或名)+ 开始时间(2026-11-28 14:00),结束省了就按一小时;方式默认到店量体;顾问省了就是你自己(顾问)或客户的归属顾问(店长代约)。**只能约本店客户**;时间要符合预约规则(提前量;早于现在的只有店长及以上能补录、且 7 天内);停业门店不接。落「待确认」,客户来了在后台点到店。动手前要跟用户对清:哪位客户、几号几点、谁接待 —— 这是对客户的承诺。","input_schema":{"type":"object","properties":{"customer":{"type":"string","description":"客户号或姓名"},"start":{"type":"string","description":"开始时间 2026-11-28 14:00"},"end":{"type":"string","description":"结束时间(可省,默认 +60 分钟)"},"way":{"type":"string","description":"到店量体 / 试衣 / 取件…(可省)"},"advisor":{"type":"string","description":"接待顾问工号或姓名(可省)"},"named_state":{"type":"string","description":"客户点名了没有:点名 / 没点 / 不详(可省,没问就是不详)"},"named_advisor":{"type":"string","description":"客户点名的顾问工号(可省)"},"channel":{"type":"string","description":"预约渠道(可省)"}},"required":["customer","start"]}},
 {"name":"reschedule_appointment","description":"**(写)改预约时间 / 换顾问**:要预约号(先 list_appointments 查);只能改本店的、只能改「待确认 / 已预约」的(已到店 / 完成 / 取消 / 过期 / 爽约是已经发生的事,改不了);新时间按同一套预约规则。只给新开始时间就保持原来的时长。回话里要把**原时间和新时间**都说出来,别只说「改好了」。","input_schema":{"type":"object","properties":{"appointment_id":{"type":"string","description":"预约号,AP 开头"},"start":{"type":"string","description":"新开始时间(可省)"},"end":{"type":"string","description":"新结束时间(可省)"},"advisor":{"type":"string","description":"换成哪位顾问,工号或姓名(可省)"}},"required":["appointment_id"]}},
 {"name":"appt_funnel","description":"**预约到店转化漏斗**:约了多少 → 我们确认了多少 → 真到店多少 → 量体多少 → 下单多少;以及**流失分四种**(待确认烂掉 / 客户取消 / 爽约 / 已过期),每种带一句该怎么办。since/until 写 2026-08-01,不给就是全部。范围跟身份走。⚠️ 报**两种**转化率:环节转化率(÷上一环,看哪一环漏得最狠)和整体转化率(÷总预约,看一百个最后剩几个)——只报一个会答错另一个问题。⚠️ 最后两环(量体/下单)和预约之间**没有外键**,按「同一个客户、预约之后」连,**会高估**。",
  "input_schema":{"type":"object","properties":{
    "since":{"type":"string","description":"起始日,写 2026-08-01。不给就是不限。"},
    "until":{"type":"string","description":"截止日,写 2026-08-31。不给就是不限。"}},"required":[]}},
 {"name":"points_ledger","description":"**积分流水和对账。** ⚠️ 余额是「同一个事实两个来源」:既能从 balance 字段读,也能从流水累加,**必然漂**(这本账修过一次:中间余额曾被截断,现已重算为 0 处断点)。**对账不能取消** —— 只要两个来源都在就可能再漂。所以两个都给、照旧对账;真出现断点时**不替你选一个**,哪个对取决于是谁写错了。",
  "input_schema":{"type":"object","properties":{
    "customer_id":{"type":"string","description":"客户号,如 C10001"},
    "limit":{"type":"integer","description":"最近几条流水,默认 20"}},"required":["customer_id"]}},
 {"name":"approval_queue","description":"**审批队列**:等级调整 / 积分调整 / 客户转移,谁申请的、什么理由、批了没有。这三种的共同点是**它们都绕过了某条本该自动成立的规则** —— 自动算出来的等级不用审批,人手改的才要。**审批管的是例外,不是日常。** 「待审批 → 已通过/已驳回」这两步只有总部运营能走。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"待审批 / 已通过 / 已驳回 / 已撤回,不给就是全部"},
    "kind":{"type":"string","description":"等级调整 / 积分调整 / 客户转移,不给就是全部"}},"required":[]}},
 {"name":"apply_adjust","description":"**提一张审批单**(等级调整 / 积分调整 / 客户转移)—— ⚠️ **只是申请,不生效**。这三件事都绕过了某条本该自动成立的规则,所以一律走审批。理由必填:**没有理由的申请,审批的人只能靠猜,而猜出来的「同意」等于没审**。店长及以上才能提。**客户转移**:target 写客户号(多位用 | 隔开,一张单只转一家店的客户),payload 写 {\"to_advisor\": 接手顾问的工号或姓名};建单时就核客户在不在本店、接手的人在不在职 —— 不过就不建。建好后聊天里会出一张卡片(去后台确认 / 看详情直接批),**你不用再复述单子内容**。",
  "input_schema":{"type":"object","properties":{
    "kind":{"type":"string","description":"等级调整 / 积分调整 / 客户转移"},
    "target":{"type":"string","description":"客户号;客户转移可多个,用 | 隔开"},
    "payload":{"type":"object","description":"要改成什么,如 {\"from\":\"金卡\",\"to\":\"黑金\"}、{\"delta\":5000};客户转移写 {\"to_advisor\":\"60000002\"}(工号或姓名)"},
    "reason":{"type":"string","description":"为什么要改。必填,至少 4 个字"}},
   "required":["kind","target","payload","reason"]}},
 {"name":"decide_approval","description":"**批一张审批单**:同意或驳回。「待审批 → 已通过/已驳回」默认**只有总部运营能走**,本店的客户转移那家店的店长也能走(角色判定在状态机里,不在这个工具里)。批注必填,同意和驳回都要 —— 驳回不写理由申请人不知道该补什么,**同意不写理由出事之后没人说得清当时看了什么**。**批准即生效**(用户 2026-10-25 拍):客户转移批了客户就转过去、未完成预约一起迁,等级调整批了等级就改 —— 和审批中心同一段代码。**本店的客户转移,那家店的店长也能批**,其余只有总部运营。",
  "input_schema":{"type":"object","properties":{
    "approval_id":{"type":"string","description":"审批单号,如 AP-LV-001"},
    "agree":{"type":"boolean","description":"true=通过,false=驳回"},
    "note":{"type":"string","description":"批注。必填,至少 4 个字"}},
   "required":["approval_id","agree","note"]}},
 {"name":"activity_roi","description":"**活动投入产出**:花了多少、带来多少成交、投入产出比、单均获客成本。不给 code 就是全部活动的排名,给了就看那一个。⚠️ 三件事别处看不到:① **活动表上的「报名/成交」两列是随机数**,和订单表毫无关系,一律不读也不许引用;② **归因期外的订单分开报,不并进成交** —— 实测有活动 100% 的订单创建于活动期外,要么归因错了要么活动日期错了;③ 成本和成交**各有三个口径**(预算/已发生/已开票、应收/实收/完成),默认「已发生」和「实收」,三个都给。算不出 ROI 的(未开始、已取消)**单独列,不当 0 排最后** —— 那会把「还没开始」和「效果最差」画等号。管理视角,顾问看不到。",
  "input_schema":{"type":"object","properties":{
    "code":{"type":"string","description":"活动编号,如 AC2601。不给就是全部活动的排名。"}},"required":[]}},
 {"name":"can_order","description":"**顾问说「要开单 / 要下单 / 能不能给 XX 做一件」—— 先掏这个,再 open_order。** 它回答「这单能下吗?」:定制订单要有**这个着装人**下单前的量体,而且不能超期 —— 超期的记录**不是「参考值」,是「无效值」**(复量周期:成人 12 个月、3–12 岁 6 个月、突增期 4 个月、0–3 岁 3 个月)。结论有**三种**:可以 / 不可以 / **判不了**。⚠️ **判不了不等于可以** —— 客户名下多个着装人而没传 wearer_id 时返回「判不了」并列出候选,**不替你挑一个**:挑错的话这一单会拿着另一个人的尺寸去裁剪,而报表上完全正常。标品订单是现货成衣,不受这条管。",
  "input_schema":{"type":"object","properties":{
    "customer_id":{"type":"string","description":"客户号,如 C10010"},
    "kind":{"type":"string","description":"定制品订单 / 标品订单,默认定制品订单"},
    "wearer_id":{"type":"string","description":"着装人编号(W 开头)。客户名下不止一个人时必传。"}},
   "required":["customer_id"]}},
 {"name":"stock_alert","description":"**库存预警** —— 哪些 SKU 要断了、哪些**看着有货其实一件都发不出**(在手有货但全被订单占用)、哪些在压货。805 个 SKU 全有库存数而在这之前没有任何工具会说「这个要断了」。⚠️ **在手 ≠ 可用**:客户问「还有货吗」要的是 **可用 = 在手 − 已占用**,只报在手会让客户白等。⚠️ **可售天数和补货点按每个 SKU 自己的销量算,算不出的会直说**(一件没卖过、或只卖过一笔 —— 一笔画不出速度)。**不许把「算不出」说成 0 天,也不许退回成「低于 N 件就预警」。** 补货点 = 交期内平均销量 + 安全库存(缺货容忍 95%,业务定),回答「什么时候该补」;**补多少件是采购的决定**。另报压货:多少天没卖出过一件,按 90 / 180 / 365 天分档,只提醒不改价。⚠️ 只看成品 SKU,**面料库存是另一摊**。","input_schema":{"type":"object","properties":{"scope":{"type":"string","description":"发不出 / 断货 / 快没了 / 卖不动。不传 = 概览(四档个数 + 每档最急的 5 个);要某一档的完整清单(前 30)就传那一档"}}}},
 {"name":"order_log","description":"**这张单发生过什么**(只读)。状态变化、每一条工厂回传(**被拒收和作废的也在里面**)、人工回退、工厂延期、按件签收,按时间排成一条;还带这张单的包裹清单(分批发货时一个包裹一条)。顾客问「我的衣服到哪了」「为什么晚了」、店长查「这单为什么退回去过」都用它。只能看本店的单(总部运营看全部)。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}},
 {"name":"delay_pending","description":"**工厂延期了、还没告诉顾客的单**(只读)。带原定完工日、延到什么时候、为什么、归属顾问、是不是你的。**联系顾客是对外动作,由人去做**;通知完用 mark_delay_told 标一下,不标这份清单只进不出。","input_schema":{"type":"object","properties":{}}},
 {"name":"mark_delay_told","description":"**(写)记下「已经把延期告诉顾客了」。** 只标本店的;标之前要跟用户确认他真的通知过了 —— 标错了这张单就从清单里消失,顾客再也等不到那个电话。","input_schema":{"type":"object","properties":{"delay_id":{"type":"integer"}},"required":["delay_id"]}},
 {"name":"rollback_order","description":"**(写)人工回退**:工厂发错件(退回等发货)/ 到店发现要返工(退回生产中,算重新生产)。**只有店长能点**,必须写清哪件不对、怎么发现的;运费公司承担。这是系统里唯一能让订单往回走的口子,回退记录一直留着。cause 只能是「发错件」或「到店返工」,note 写理由。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"cause":{"type":"string","enum":["发错件","到店返工"]},"note":{"type":"string"}},"required":["order_id","cause","note"]}},
 {"name":"report_production","description":"**(写)自有工坊报工**:这几件做完了 / 质检过了 / 发出去了。**工匠报自己做的那件,店长报本店**;顾问和版师报不了(不在生产环节)。\n\n⚠️ **外发工厂的单谁都不许替它报** —— 工厂没回传,真相就是「工厂还没报」,而不是「我们知道它做完了」。替它报一条,订单往前走了,而工厂那边什么都没发生。工具会自己查这张单的生产方,不是自有工坊就拒。\n\n和工厂回传**走同一个收件箱、同一套判定**:重复只记一次、来早了暂存、报「发出」必须带快递单号、车间工单还在制却报完工会挂异常(报完工会顺手把工单收掉)。被拒收或挂异常时**照「理由」去处理,不要换个说法再报一次** —— 每次都会留痕。\n\nevent:完工 / 质检通过 / 发出。item 给订单行号(只报某一件),不给就是整单。发出要传 tracking_no。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"event":{"type":"string","enum":["完工","质检通过","发出"]},"item":{"type":"string","description":"订单行号;不给就是整单"},"tracking_no":{"type":"string","description":"报「发出」时必填"}},"required":["order_id","event"]}},
{"name":"save_report","description":"**(写)把写好的日报 / 周报 / 月报存成草稿。** ⚠️ **只在用户明说「存一下 / 保存」时调**,先把正文给他看过;不要写完就自动存。每存一次是**新的一版**(旧版不覆盖),保存时冻结当时的取数包 —— 之后数据变了,这份报告的数不跟着变。kind / date 要和写这份报告时用的取数包一致;改的是已有报告就带上 report_id。返回报告号和「能不能确认」。只有店长 / 总部能存。","input_schema":{"type":"object","properties":{"body":{"type":"string","description":"报告正文(就是给用户看过的那一份)"},"kind":{"type":"string","description":"日 / 周 / 月;不给 = 报告模板里的默认期间(总部没配过就是 周)"},"date":{"type":"string","description":"那一期里任意一天 `YYYY-MM-DD`;不给 = 上一个完整的那一期"},"report_id":{"type":"string","description":"改已有报告时给它的报告号"}},"required":["body"]}},
{"name":"confirm_report","description":"**(写)店长确认一份经营报告。** ⚠️ **只在店长明说「确认」时调,不要替他点。** 必选指标(下单数、营收)缺了不许确认;只能确认这一期**最新那一版**;确认后不能改,要改再存一版。第一版**不自动发送给任何人**。","input_schema":{"type":"object","properties":{"report_id":{"type":"string","description":"要确认的报告号(RPT 开头)"}},"required":["report_id"]}},
{"name":"list_reports","description":"**存过的经营报告**(只读)。不给 report_id 就列每一期最新那一版(状态:草稿 / 已确认,带版本数);给了 report_id 就看那一版的正文和保存时冻结的取数包。只给店长 / 总部。","input_schema":{"type":"object","properties":{"kind":{"type":"string","description":"只看 日 / 周 / 月"},"report_id":{"type":"string","description":"看某一份的正文"},"limit":{"type":"integer","description":"列几份,默认 20"}}}},
{"name":"summarize_products","description":"**商品归纳总结**(只读):给一套衣服,从**颜色、纹样(花型)、面料(材质 / 布料)、工艺、形制**归纳规律。三种给法:spus(款号,逗号分隔)/ keyword(商品名里含的词,如「马面裙」)/ category(分类编码前缀);或者给 customer(客户号或姓名)归纳她近 24 个月买过的东西(喜好)。返回「规律」(这一套里明显多于对照组的值,每条带一句现成的说法)、「共性」(几乎都是、但对照组里本来就常见 —— **不是规律**)、「覆盖」(每个维度认得出几件)、「结论」。⚠️ **结论说「没有发现规律」就照说没有**,不要自己从商品名里另找一条;⚠️ 只照返回的说法讲,不心算比例;认不出的件数要说出来。用于商机研判、版师看版型共性、运营看选品。","input_schema":{"type":"object","properties":{"spus":{"type":"string","description":"款号,逗号分隔"},"keyword":{"type":"string","description":"商品名里含的词"},"category":{"type":"string","description":"分类编码前缀,如 C0102"},"customer":{"type":"string","description":"客户号或姓名:归纳她买过的东西"},"limit":{"type":"integer","description":"最多归纳多少款,默认 40,最多 80"}}}},
{"name":"get_product_images","description":"**看商品图**(只读):按款号列出这一款的商品图 —— 主图、详情图、细节图、各颜色的整套 —— 页面会把图直接显示出来。每一张标明「真图」(出好的商品图)还是「示意图」(没出图、按颜色款式现画的)。⚠️ **示意图不能当实物核料**,要说清是示意;只知道商品名的先用 summarize_products 的 keyword 查款号。用于版师核料对照实物、顾问给客户看款。","input_schema":{"type":"object","properties":{"spu":{"type":"string","description":"款号,如 lxys_100007919"}},"required":["spu"]}},
{"name":"draft_capability_request","description":"**起草能力申请单**(只读,不提交):用户要的事你**没有工具做得了**时,先问「要不要我帮你写一份能力申请」,用户同意后一问一答把六栏问清,再调这个起草。六栏:scene 在什么情况下需要(哪个环节、多久遇到一次)/ who 哪个岗位用 / pain 现在没有它时怎么办、麻烦在哪 / want 要它查什么、算什么、做什么 / given 用的时候会提供什么 / expect 希望它给出什么。**没问清的栏留空,不替用户编**;返回的「还缺」要接着问。⚠️ 你**不能提交** —— 页面会显示申请单,由用户核对后自己点「确认提交」。","input_schema":{"type":"object","properties":{"scene":{"type":"string"},"who":{"type":"string"},"pain":{"type":"string"},"want":{"type":"string"},"given":{"type":"string"},"expect":{"type":"string"},"title":{"type":"string","description":"一句话标题,选填"}}}},
 {"name":"store_report","description":"**门店经营报告的取数包**(只读)—— 店长说「生成上周周报」「出个九月月报」「昨天的日报」时**先调它**,再照它写。日报 / 周报 / 月报共用:kind=日 / 周 / 月,date 给那一期里任意一天 `YYYY-MM-DD`,**不给就是上一个完整的那一期**(昨天 / 上周 / 上个月)。返回分两栏:**「期内」这一期发生了多少**(订单、销量、营收、进店客流、评价、进入休眠、任务、成交率)和**「存量(截至今天)」还压着多少**(待付款、该催工厂、延期没告诉顾客、白坯、库存、差评待跟、流失预警)—— ⚠️ **两栏不许混**,别把存量说成本期新增。⚠️ 每一项都带「出处」和「口径」,写报告**只照这份数说**,数字不许改写、不许心算新数;「取不到的」要照实写进报告。周报的成交率是**最近 4 周滚动**;日报不报成交率。原因和建议要标成判断,不写成已安排。只给店长 / 总部。","input_schema":{"type":"object","properties":{"kind":{"type":"string","description":"日 / 周 / 月;不给 = 报告模板里的默认期间(总部没配过就是 周)"},"date":{"type":"string","description":"那一期里任意一天 `YYYY-MM-DD`;不给 = 上一个完整的那一期"}}}},
{"name":"weekly_revenue","description":"**按周营收 = 实收减退款**(只读,周报用)。「上周营收多少」「这周进了多少钱」用它。⚠️ 业务周是**周一到周日**;实收按**付款日**、退款按**退款日**归周,**不是按下单日** —— 和 orders_by_date 的「下单数」不是一回事。⚠️ 退款日是近似(用售后单最后更新时间),返回里写着。预约押金不算营收。不给 week 就是上一个完整周;week 给那一周里任意一天 `YYYY-MM-DD`。范围随身份:总部全部 / 店长本店 / 顾问名下∪经手。","input_schema":{"type":"object","properties":{"week":{"type":"string","description":"那一周里任意一天 `YYYY-MM-DD`;不给 = 上一个完整周"},"start":{"type":"string","description":"自由区间的**起**那天 `YYYY-MM-DD`。⚠️ **要和 end 一起给**,只给一个会被拒。给了区间就不看 week —— 用它来答「国庆那一周到现在」这种现成档位表达不了的跨度"},"end":{"type":"string","description":"自由区间的**止**那天 `YYYY-MM-DD`(含当天)。要和 start 一起给"}}}},
{"name":"sales_rank","description":"**商品销量排行**(只读)。「九月卖得最好的商品是什么」「这个月哪个品类卖得多」「标品前十」用它 —— 按商品 / SKU / 品类汇总订单行,不用逐单去查。⚠️ **时间段必须写成 `month=YYYY-MM` 或 `start`+`end`**,「九月」先换成具体年月,拿不准是哪一年就问。⚠️ **默认按件数排**(一单买 3 件算 3);定制品每单一件、单价高 —— 按件数几乎上不了榜、按金额会霸榜,**用户没说按什么时按件数答,再照返回里「各排法的第一」说按金额是谁 —— 不要从榜单里自己推**。⚠️ 取消 / 待付款 / 已退款的行**不算销量**(口径同库存预警),返回里「没算进销量的订单行」写了各有多少。⚠️ 报总量用「合计」,不要拿榜单相加;返回「并列」时要说出前 N 名不唯一。范围随身份:总部全部 / 店长本店 / 顾问名下∪经手。","input_schema":{"type":"object","properties":{"month":{"type":"string","description":"月份 `YYYY-MM`,如 `2026-09`"},"start":{"type":"string","description":"起始日 `YYYY-MM-DD`(和 end 一起给)"},"end":{"type":"string","description":"截止日 `YYYY-MM-DD`(含当天)"},"by":{"type":"string","description":"按什么汇总:商品(默认,同款不同尺码颜色合一)/ SKU / 品类"},"metric":{"type":"string","description":"按什么排:件数(默认)/ 金额 / 单数"},"kind":{"type":"string","description":"只看 标品 或 定制品;不给就是都算"},"field":{"type":"string","description":"按哪个日期归月:下单(默认)/ 完工 / 发货 / 交付"},"limit":{"type":"integer","description":"列前几名,默认 10,最多 50"}}}},
 {"name":"orders_by_date","description":"**按时间段列订单**(只读)—— 唯一一个不用先给订单号或客户号就能列单的入口。`direction` 必须给「往后」(今天→N 天后)或「往前」(N 天前→今天),不给就返回两种读法各有多少单,**原样告诉用户让他选**;`field` 选 下单 / 完工 / 发货 / 交付(四份不同的单子,默认下单);`days` 默认 7;按日历月给 `month`(YYYY-MM),按起止给 `start` + `end`,这两种不再给 direction / days。范围跟身份走:顾问只看自己的,店长看本店,总部看全部。","input_schema":{"type":"object","properties":{"direction":{"type":"string","enum":["往后","往前"],"description":"往后=今天到 N 天后;往前=N 天前到今天。不给会返回判不了;用 month / start+end 时不给"},"days":{"type":"integer","description":"几天,默认 7"},"month":{"type":"string","description":"按日历月查:YYYY-MM(如 2026-09 = 9 月 1 日到 30 日)"},"start":{"type":"string","description":"按起止日期查的起点 YYYY-MM-DD,要和 end 一起给"},"end":{"type":"string","description":"按起止日期查的终点 YYYY-MM-DD(含这一天)"},"field":{"type":"string","enum":["下单","完工","发货","交付"],"description":"按哪一列的时间算,默认下单"},"limit":{"type":"integer","description":"最多返回几条,默认 50"}}}},
 {"name":"factory_chase","description":"**该催工厂的单 + 要人看的工厂回传**(只读)。定制单的生产和发货**只认工厂回传**(自有工坊和外发工厂都有,谁接的单谁报),门店和后台都不能手动推状态。这里列出:① 该催的单 —— 开工超过 3 天工厂没回接单(单可能没发过去),或过了工厂承诺的完工日还没完工(该先告诉顾客会晚),带生产方、承诺完工日、归属顾问、是不是你的;② 要人看的回传 —— 挂异常(查无此单、单已取消、别家报了这张单、车间工单还在制却报完工)/ 拒收(缺物流单号、时间不对)/ 暂存(来早了,等前一条)。店长看本店,总部运营看全部。顾问问「我有哪些单该去催工厂」「这单怎么还没做好」也用这个。","input_schema":{"type":"object","properties":{}}},
 {"name":"fitting_queue","description":"**白坯试衣看板**(只读)—— 哪些定制单该做白坯试衣、试了没有、客户签没签字,以及每张待生产单能不能开裁、卡在哪。**签字是责任转移点**;**开裁这道闸会拦**:该试的要试过、客户签了字才许开裁。返回分档(最要紧的是「该试没试」)、必试判定(重工 / 全定制 / 婚服三类命中任一即必试,判不了单列)和待开裁的单。约试衣、催签字是人的动作,这个工具不改任何东西。","input_schema":{"type":"object","properties":{"order":{"type":"string","description":"订单号;不传则看全部"}}}},
 {"name":"record_pickup","description":"**交付签收的三个动作(真的写进去)**:action=「到店代收」/「取件方式」(mode=到店取 或 转寄,转寄要 tracking_no)/「不合身」(issue 写哪里不合身,item 指哪一件)。单子不止一个包裹时要给 pkg(包裹号)。只能动本店的单,经手人就是你自己。⚠️ 动手前先跟用户对一遍单号和动作。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"action":{"type":"string","enum":["到店代收","取件方式","不合身"]},"pkg":{"type":"string","description":"包裹号。一单分了好几个包裹时必须给"},"item":{"type":"string","description":"订单行号(哪一件)。登记不合身时,包裹里不止一件就必须给"},"mode":{"type":"string","enum":["到店取","转寄"]},"tracking_no":{"type":"string"},"issue":{"type":"string"},"matches_record":{"type":"boolean"},"other_defect":{"type":"boolean"},"our_fault":{"type":"string","enum":["导购","打版"]}},"required":["order_id","action"]}},
 {"name":"verify_fit_code","description":"**核验顾客给的 6 位码 = 签收(真的写进去)**:通过后**这个包裹里还没登记不合身的件**全部签收,顾客可以拿走;**整单所有未作废包裹的每一件都签收合身**,订单才「已发货 → 待完成」(业务 09-23 分批发货)。业务 09-22:**签收 = 顾客确认试穿合身** —— 顾客在手机上点「试穿合身」拿到 6 位码交给导购,导购输入核验;到店取和转寄都走这个码。**码只能是用户这句话里说出来的那一个,不许编、不许猜、不许「先填个试试」** —— 输错会记次数,5 次作废。完成之后要**顾客自己确认**,顾客一直不确认,签收满 15 天顾问才能写理由追认(ratify_complete)。⚠️ 动手前先跟用户对一遍单号和码。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"code":{"type":"string","description":"顾客给的 6 位码,原样照抄用户说的"},"pkg":{"type":"string","description":"包裹号。**一个包裹一个码**,一单分了好几个包裹时必须给"}},"required":["order_id","code"]}},
 {"name":"create_repair","description":"**新建返修单(真的写进去)**,停在「待确认」等店长判责。顾问或店长,本店的单。issue 写清哪里要修(「下摆开线」「腰围紧 2cm」)。**一张单有好几件时 item 必填**(订单行号或商品名)—— 没说哪一件就问,不替用户挑。返回里带一个**判责建议**(不是结论):按返修判定表 + 这一件的下单量体;签收时顾客确认过试穿合身的,之后的尺寸问题建议顾客承担(工艺瑕疵不在此列)。交付签收登记「不合身」时系统会自动建返修单,不用再建。⚠️ 动手前先跟用户对一遍单号、哪一件、什么问题。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"issue":{"type":"string"},"item":{"type":"string","description":"订单行号或商品名;一张单多件时必填"}},"required":["order_id","issue"]}},
 {"name":"decide_repair","description":"**店长判责(真的写进去)**:liable = 顾客 / 企业,plan = 返修 / 重做,**都由店长定,只能照用户说的填**。判给顾客的要填 fee_est;customer_agreed=true 时 agree_note 必填。判给企业且金额超过店长权限时要 approved_by + approve_note(批准人不能是判责的店长自己)。","input_schema":{"type":"object","properties":{"maintain_id":{"type":"string"},"liable":{"type":"string","enum":["顾客","企业"]},"plan":{"type":"string","enum":["返修","重做"]},"fee_est":{"type":"number","description":"判给顾客=收顾客多少钱;判给企业=我方要出多少钱(授权档看这个数)"},"customer_agreed":{"type":"boolean"},"agree_note":{"type":"string"},"approved_by":{"type":"string","description":"总部批准人的工号(我方支出 1000–5000 时必填)"},"approve_note":{"type":"string","description":"批准说明:谁、什么时候、批了多少"}},"required":["maintain_id","liable","plan"]}},
 {"name":"advance_repair","description":"**推进返修单一档(真的写进去)**:待入库 → 待处理(衣服收回来了)→ 处理中(送修)→ 待签收(修好回店)。顾问或店长,本店的单。还在「待确认」的要先等店长判责;「待签收 → 已完成」要顾客试穿输码(verify_repair_return),这里不给。⚠️ 动手前先跟用户确认单号和这一步真的发生了。","input_schema":{"type":"object","properties":{"maintain_id":{"type":"string"}},"required":["maintain_id"]}},
 {"name":"verify_repair_return","description":"**返修件回店签收(真的写进去)**:顾客试穿修好的衣服合身,在手机上点「试穿合身」拿 6 位码交给导购,导购输入核验通过才算完成(业务 09-22:和交付签收同一套码)。**码只能是用户这句话里说出来的那一个,不许编、不许猜** —— 输错记次数,5 次作废。","input_schema":{"type":"object","properties":{"maintain_id":{"type":"string"},"code":{"type":"string"}},"required":["maintain_id","code"]}},
 {"name":"ratify_complete","description":"**顾问追认完成(真的写进去)**:**最后一件**签收满 15 天顾客还没在手机上确认完成,顾问写理由(比如「已电话联系,顾客表示没问题」)把订单「待完成 → 完成」。**不满 15 天不行、没写理由不行** —— 业务 09-22:完成由顾客确认,追认是兜底,不是替顾客点。⚠️ 动手前先跟用户确认理由是真的联系过。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"reason":{"type":"string"}},"required":["order_id","reason"]}},
 {"name":"open_order","description":"**开一张定制单(真的写进去)**,停在「待确认」—— 还没生效。顾问或店长用,只给本店客户开。items 每一件写 spu(或 sku)、wearer_id(**给谁做,必填** —— 下单量体量的必须是穿这件的人)、qty。只开定制单,标品流程不变。delivery 填「配送到店」(默认,**到店取不收运费**)或「配送到客户」(寄到家,按客户所在省份查运费表收;**算不出来就不开单**,别改成到店绕过去)。返回里有货品金额、运费、合计和运费依据,**报给顾客的数照返回读,不要自己算**。开完的**下一步**:给每一件量下单量体并绑到这一件(record_measure 带 order_id + item),再 confirm_order。⚠️ 动手前先跟用户对一遍:哪位客户、哪几件、每件给谁做、到店取还是寄到家。**开之前先调 can_order 问这单能不能下**(着装人有没有下单前的量体、过没过期):它说「不可以」或「判不了」就别开,把原因告诉用户。","input_schema":{"type":"object","properties":{"customer_id":{"type":"string"},"delivery":{"type":"string","enum":["配送到店","配送到客户"],"description":"到店取(默认,不收运费)还是寄到顾客家(按运费表收)"},"scheme_id":{"type":"string","description":"照着哪套方案开的(可选,SC 开头)。给了就挂上 —— 之后按方案查得到这张单;方案得是这位客户的、已保存或已锁定"},"items":{"type":"array","items":{"type":"object","properties":{"spu":{"type":"string"},"sku":{"type":"string"},"wearer_id":{"type":"string"},"qty":{"type":"integer"}}}}},"required":["customer_id","items"]}},
 {"name":"cancel_fee","description":"**顾客完工前不做了,扣多少、退多少**(只读,业务 2026-10-10 晚定)。给定制单号,按工单逐道工序列明细:已完成的工序全算、做到一半的按已过天数折(不超过这道的工日)、还没开工的不扣;扣的总额不超过已付。返回每道工序怎么算的、工钱合计、扣多少、退多少;有工单数据不全的会列在「判不了」,**那时不要把数报给顾客**。material_cost 是门店按采购单核过的料钱,**只填用户说出来的数**,不给就只算工钱。只算不退:顾客确认明细后再走退款。只能看本店的单。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"material_cost":{"type":"number","description":"门店核过的料的成本价(元);用户没说就不填"}},"required":["order_id"]}},
{"name":"confirm_order","description":"**确认下单(真的写进去)**:待确认 → 待审核。业务 09-22:**定制单确认即已付款**,不走「待付款」。**逐件过闸**:每一件都要有绑在它上面的、开单之后量的、够做这件衣服的下单量体;有一件不过就整单拒绝,返回里列出是哪几件、缺什么(没有下单量体 / 早于开单 / 缺哪几项 / 着装人没定)。被拒了**不要换个说法再试**,把缺什么告诉用户,去量、去绑。**还要顾客单独确认「本单定制品不适用七天无理由退货」**:先把这句话念给顾客听,顾客同意了才带 no7day_ack=true;没确认就会被拒,**不许替顾客填**。⚠️ 动手前先跟用户确认单号。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"no7day_ack":{"type":"boolean","description":"顾客本人已当面单独确认「本单定制品不适用七天无理由退货」—— 只有用户明确说顾客确认过才填 true"}},"required":["order_id"]}},
 {"name":"record_measure","description":"**登记一次量体(真的写进去)**。顾问或店长用,只能录本店客户的着装人;量体人就是你自己。wearer_id 是着装人编号(W 开头);values 形如 {\"胸围\":86,\"腰围\":68};method 只认「到店 / 上门」;inner / shoe / breath 三个都必填。下单量体另给 order_id + item。⚠️ 动手前先跟用户对一遍:给谁量的、哪几项多少、到店还是上门、三个条件、是不是某一件的下单量体。","input_schema":{"type":"object","properties":{"wearer_id":{"type":"string"},"values":{"type":"object","description":"{量体项名: 数值}"},"method":{"type":"string","enum":["到店","上门"]},"inner":{"type":"string"},"shoe":{"type":"string"},"breath":{"type":"string"},"order_id":{"type":"string","description":"只在下单量体时给"},"item":{"type":"string","description":"订单行号或商品名,只在下单量体时给"}},"required":["wearer_id","values","method","inner","shoe","breath"]}},
 {"name":"record_fitting","description":"**登记一轮白坯试衣(真的写进去)**。顾问或店长用,只能登记本店订单;陪同人就是你自己(不收工号)。item 填订单行号或商品名(一张单里同名多件时必须给行号)。adjust 写这一轮改了哪几处(没改写「无需调整」,不许空);signed 客户当场签字就填 true。**补签**:客户后来才签,给 round(已有的轮次号)并 signed=true;**签字不能撤销**。⚠️ 客户没签字之前,这一件所在的整张单**不许开裁**(业务 09-22)。⚠️ **动手前先跟用户对一遍**哪张单、哪一件、改了什么、签没签 —— 签字是责任转移点,记错了等于给门店一张不存在的底牌。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"item":{"type":"string","description":"订单行号或商品名"},"adjust":{"type":"string","description":"这一轮改了哪几处;没改写「无需调整」"},"signed":{"type":"boolean","description":"客户签字了吗"},"round":{"type":"integer","description":"只在补签时给:要补签的那一轮"},"note":{"type":"string"}},"required":["order_id","item"]}},
 {"name":"start_cutting","description":"**开裁(真的写进去)**:把一张定制单从「待生产」推进到「生产中」。只有版师能用。**要先过白坯试衣这道闸**(业务 09-22):单里每一件该试的都试过、而且客户签了字,才许开裁;有一件没过就整单拒绝,返回里列出是哪几件、缺什么(没试 / 没签 / 判不了该不该试又没试过 —— 判不了的先试一轮并签字就能裁)。被拒时**不要换个说法再试**,把卡在哪告诉用户,让顾问去约试衣或补签。⚠️ **开裁不可逆**,动手前先跟用户确认单号。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}},
 {"name":"channel_compare","description":"**多渠道表现对比** —— 四个下单渠道(微信小程序/官网/门店 Pad/客服代下单)各自的单量、客单价、待付款占比、退款率、售后率。⚠️ **这张表不能用来比渠道,而它和真的渠道对比长得一模一样。** 原因不是数据少,是这一列怎么填上去的:种子订单是**按订单序号轮着发的**(`SRC[i % 4]`),模拟订单是**按固定权重独立抽的**,两种机制都让渠道和金额、状态、客户**统计独立** —— 任何渠道间差异都是这两个机制的产物,**不是渠道的表现**。⚠️ **渠道和活动 100% 共线**:每个渠道恰好对应一个活动,一一对应没有例外,所以「这个渠道转化好」和「这个活动效果好」在这批数据上**分不开**(这条同时影响 activity_roi)。⚠️ **客服代下单不是一个渠道**,是人工补录,背后可能是电话/微信/门店 —— 当渠道分析会得出假结论。⚠️ **不给渠道排名**:11 单的样本排不出名次,排了会被当成结论去调预算;每个比率后面都带着「**一单值多少个百分点**」。","input_schema":{"type":"object","properties":{"include_sim":{"type":"boolean","description":"是否把 3826 单模拟订单也算进来。默认 false —— 它们的渠道是抽出来的,算进来只会让表看起来更可信,不会更真"}}}},
 {"name":"product_ranking","description":"**当月最受欢迎**(只读)—— 给版师的打版依据:这个月哪些商品卖得多,按**形制 / 面料 / 工艺**切开各档卖了多少。「这个月什么最受欢迎」「哪种面料卖得好」「圆领袍和马面裙哪个多」用它。两张榜(按件数 / 按金额)并列给。和 `sales_rank` 不是同一把尺(这里全量不分店、算待付款、切形制面料工艺;它随身份、不算待付款、切商品 SKU 品类)。","input_schema":{"type":"object","properties":{"month":{"type":"string","description":"月份 `YYYY-MM`,如 `2026-10`。默认世界的当月。「这个月」不替你猜成具体哪个月"},"dim":{"type":"string","description":"再按哪个维度切:形制 / 面料 / 工艺。不给就只给商品榜","enum":["形制","面料","工艺"]}}}},
 {"name":"draft_delivery_notice","description":"**起草一份标品交付告知**(只读)—— 这单商品对上「交付时必须书面告知的六条」里的哪几条(每条写明凭商品名里的哪个词)、对不上的商品,和一段给顾问复制去发的文字。**不记任何东西**。「这单要告知顾客什么」「帮我写个交付告知」用它。只起草标品;定制单走交付卡签收。范围跟身份走。","input_schema":{"type":"object","properties":{
    "order_id":{"type":"string","description":"订单号"}},"required":["order_id"]}},
 {"name":"record_delivery_notice","description":"**(写)记下「交付告知已经发给顾客了」** —— **只在用户明说「发了 / 记一下」时调**,没发别记。告知了哪几条由系统按起草现算;要给渠道(微信 / 电话 / 短信 / 当面 / 小程序)。**这不是顾客签收**,签收另记。只记本人看得到的、已交付的标品单,同一单只记一次。","input_schema":{"type":"object","properties":{
    "order_id":{"type":"string","description":"订单号"},
    "channel":{"type":"string","description":"用什么发的:微信 / 电话 / 短信 / 当面 / 小程序"}},"required":["order_id","channel"]}},
 {"name":"part_options","description":"**这一款每个部位能选什么**(只读)—— 定制品分部位选料:每个部位(领口 / 袖 / 主身 / 裙…)可选的面料和工艺、各自的加价和可选颜色、这个部位吃多少料(带来源:估的还是版师核过的)。「这款领口能选什么料」「袖子换真丝加多少钱」用它。给商品编号(spu)或款名;名字对上不止一款时返回候选。标品不分部位。面料和工艺能不能配用 `kb_combo`。","input_schema":{"type":"object","properties":{
    "product":{"type":"string","description":"商品编号(spu)或款名"}},"required":["product"]}},
 {"name":"order_parts","description":"**这一单每个部位实际选了什么**(只读)—— 每行订单明细上客户分部位选的面料 / 工艺 / 颜色 / 加价,并核三件事:选的料在不在这款的可选范围里、同一部位的面料和工艺相不相容、各项加价合计对不对得上订单行的定制部件金额。「客户领口选的是什么料」「这单加价怎么算出来的」用它。范围跟身份走(同 get_order)。","input_schema":{"type":"object","properties":{
    "order_id":{"type":"string","description":"订单号"}},"required":["order_id"]}},
 {"name":"return_rate","description":"**标品退货率**(只读)—— 哪些品类 / 商品 / 渠道退得多,退的原因是什么。「哪类标品退货多」「退货主要是什么原因」「小程序和官网哪个退得多」用它。返回三个率并列(实际退货率 / 申请退货率 / 换货率,各带可信范围和「偏高 / 偏低 / 说不清」)、申请被拒件数、退货原因 6 类、观察期说明。全公司不分店。定制品不在这里(定制品不接受无理由退换)。","input_schema":{"type":"object","properties":{
    "dim":{"type":"string","description":"按什么切:品类(默认)/ 商品 / 渠道"},
    "month":{"type":"string","description":"只看某个**付款月**卖出的,YYYY-MM;不给 = 全部满观察期的"}},"required":[]}},
 {"name":"wear_risk","description":"**易损分析**(只读)—— 哪些面料 / 形制 / 工艺更容易出维保。「什么面料最容易坏」「刺绣是不是更容易报维保」用它。返回按率排(分子分母一起给,分母低于 30 件标「样本不足」)、「差异显不显著」一条和「撞在种下的规律上」一条。不接月份参数(故意的)。","input_schema":{"type":"object","properties":{"dim":{"type":"string","description":"按哪个维度切,默认面料","enum":["面料","形制","工艺"]}}}},
 {"name":"recovery_followup","description":"**(写)未成交挽回清单一键建跟进**:把 recovery_queue 清单上的几行(待付款的订单号、已取消 / 爽约 / 已过期的预约号)各派一条「电话回电」给顾问。items 是列表,每条 {号: 订单号或预约号, assignee?(不给 = 这一单的顾问), end?(截止,不给 = 今天 18:00), note?}。**逐行各自成败**:同一位客户还有没办完的电话回电 → 报「已经有人在跟」不重复派;不在清单里(已付 / 已成行 / 别店)→ 不派。一次最多 30 行。只有店长及以上能建。⚠️ **这只是派给人去联系,不是已经联系过客户** —— 不许说成「已经联系了」;发短信 / 打电话仍是人的事。⚠️ 先 recovery_queue 把清单念给店长,**他说跟哪几条**再调。","input_schema":{"type":"object","properties":{"items":{"type":"array","items":{"type":"object"},"description":"[{号, assignee?, end?, note?}…]"}},"required":["items"]}},
 {"name":"recovery_queue","description":"**未成交挽回清单** —— 下了单没付钱的、约了没来的,各压着多少钱、压了多久、该按什么顺序跟。不传参数给两摊都要;传「待付款」或「预约」只要一摊。⚠️ **这个工具只出清单,不发任何东西** —— 发短信/微信/打电话是对外动作,按不按、怎么按是人的决定。⚠️ **它不划「超时」那条线**:定制品和标品的合理等待期本来就不一样,编一个数会把正常的单子算成流失。只排序不划线,按**金额 × 停留天数**排。⚠️ **三种未成行不许混成一类**:已取消是客户主动说了不来、爽约是没说就没来(**先确认人没事**)、已过期是系统判的(客户自己可能都不知道有这条预约)。","input_schema":{"type":"object","properties":{"kind":{"type":"string","description":"待付款 或 预约;不传则两摊都给"}}}},
 {"name":"pattern_queue","description":"**版师的排队看板 —— 「今天该我核什么」。**不用传任何参数,把版师手上的几摊活一次列全(裁片用料占比、推档疑点、推得出但不作数的尺码格子、上架了却没有版型的定制品),每一摊报「总数 / 已完成 / 还剩」。传 pattern(认编码 PT06 和全名)转看那一个版型的裁片用料占比明细。版师进来第一句话就该调它。","input_schema":{"type":"object","properties":{}}},
 {"name":"grading_audit","description":"**推档自检 —— 把「要核 1237 个数」压成「要核 12 条档差」。**尺码表全部是推出来的(基码值 + 档差 × 尺码序号),版师真正该核的只有基码和那 12 条档差。不传 pattern 给全局(扫了多少、哪几个版型有疑点、档差规则是什么);传 pattern 给这一个版型的逐部位明细:实际档差 / 规则档差 / **覆盖范围**(这个版型能做多大的人)/ 量纲体检 / 哪几项「推得出但不作数」。**判据是定义性的,不是阈值** —— 相邻码的差必须处处相等且等于档差表,不一致就是真的有一格不对。","input_schema":{"type":"object","properties":{"pattern":{"type":"string","description":"版型编码或全名,不传则给全局"}}}},
 {"name":"set_piece_ratio","description":"**改一片的用料占比,并标成「版师核过」**。改完这一片就锁住,不会再被估算覆盖;同版型其余**没核过**的片按比例重新归一,让总和回到 1,而**已核过的片不动** —— 人核过的数不许被自动调。ratio 填 0–1 之间的小数(0.25 = 25%)。**why 要写** —— 不写的话下次有人问「这个数为什么是这样」就查不到了。","input_schema":{"type":"object","properties":{"pattern":{"type":"string"},"piece":{"type":"string","description":"裁片名,如「袖片」"},"ratio":{"type":"number"},"why":{"type":"string","description":"为什么改成这个数"}},"required":["pattern","piece","ratio"]}},
 {"name":"set_grade_diff","description":"**登记「这条档差核过了」**(只读不改档差)。版师核完 `grading_audit` 压出来的档差之后用它;说「不对」要给 propose(建议改成多少),why 必填。只有版师能用;身份从登录会话取,不收身份参数。","input_schema":{"type":"object","properties":{"item":{"type":"string","description":"档差的部位名(胸围 / 肩宽 / 上襦衣长……),认 `grading_audit` 返回的那 12 项"},"verdict":{"type":"string","description":"核过 = 这条没问题;不对 = 这条该改(必须同时给 propose)","enum":["核过","不对"]},"why":{"type":"string","description":"**必填**,凭什么:量过几件成衣 / 照哪一版比的 / 按哪个国标"},"propose":{"type":"number","description":"建议改成多少(每升一码加多少厘米)。**只有 verdict=不对 时填**,而且不能和现在的值相同"}},"required":["item","verdict","why"]}},
 {"name":"my_workorders","description":"**我手上的工单**。工匠看自己的,工坊管事看本坊,总部运营看全部 —— 范围跟身份走。带**在制上限**和当前在制数:接不接得下一件,这两个数说了算,不用猜(上限是工艺约束 —— 手工活同时开太多件每件都慢,而且染色、绣线批次会串味)。逾期的排在最前。status 可选,写「在制/待开工/已完成」等。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"只看某个状态的,不给就是全部"}},"required":[]}},
 {"name":"assign_task","description":"**派一条任务**(真的写进去,立即生效)。只有店长及以上能派,只能派给本店在职顾问。type 见 task_types();ref_id 填什么由类型决定;assignee 写工号或姓名。⚠️ **动手之前先跟用户把人、时间、内容对一遍** —— 派错了和派对了在库里长得一模一样,等发现的时候顾问已经去做了。用户没说清派给谁就问,别挑一个「看起来合理」的人。",
  "input_schema":{"type":"object","properties":{
    "type":{"type":"string","description":"任务类型,见 task_types()"},
    "assignee":{"type":"string","description":"派给谁,工号或姓名"},
    "note":{"type":"string","description":"日程描述:这件事要做什么"},
    "end":{"type":"string","description":"结束时间 YYYY-MM-DD HH:MM"},
    "start":{"type":"string","description":"开始时间,不给则用现在"},
    "ref_id":{"type":"string","description":"挂的单据号。客户相关填客户号;订单跟踪填订单号;维保填维保单号;售后填售后单号;经营改进填**已确认**的报告号;团建培训和日常运维不填。"},
    "metric":{"type":"string","description":"只有经营改进要填:盯报告里的哪一项(如「订单」「差评待跟」),下一期报告会回看这一项的数"},
    "activity_code":{"type":"string","description":"绑定活动编码,可不填"}},
   "required":["type","assignee","note","end"]}},
 {"name":"dispatch_task","description":"**把待分配池里的单分出去**(真的写进去)。不给 assignee 就采纳 dispatch_pool 里那条建议。只能分**还没派出去的**单 —— 已经派给别人的要改派是另一个动作,悄悄换掉负责人会让原来那个人的列表凭空少一行。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029"},
    "assignee":{"type":"string","description":"分给谁,工号或姓名。不给则采纳建议。"}},
   "required":["task_id"]}},
 {"name":"reassign_task","description":"**改派**:把一条已经派出去的任务转给另一个人(真的写进去)。和 dispatch_task 的区别是**有人的活被拿走了** —— dispatch 分的是没人管的单,改派是从小张手上拿走给小李。所以 reason 必填,而且原负责人仍然看得见这条(标着是谁改派的、为什么),**不让他的列表凭空少一行**。只能改「有效」的任务。⚠️ 动手之前先问清楚为什么要改、原负责人知不知道。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029"},
    "assignee":{"type":"string","description":"改派给谁,工号或姓名"},
    "reason":{"type":"string","description":"为什么改派。**必填** —— 把人的活拿走要给个说法"}},
   "required":["task_id","assignee","reason"]}},
 {"name":"finish_task","description":"**把任务标记完成**(真的写进去)。日程总结必填。**只能完成派给自己的** —— 别人代点等于台账上写了一件没发生的事。需要现场照的类型要先在页面上传照片,这里传不了图。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号"},
    "summary":{"type":"string","description":"日程总结:做了什么、结果如何"},
    "conclusion":{"type":"string","description":"只有「商机提醒」要填:从这条任务的「可选结论」里选一个(如「满足了」「客户不要了」),商机按它走。别的任务不用填"}},
   "required":["task_id","summary"]}},
 {"name":"start_workflow","description":"**发起一条被工作流接管的事**(真的在管理后台排一条运行)。**只在调技能被拦下、拦截理由点名让你改调它时用** —— 那件事现在由工作流做,你别自己做。把这件事要的输入照实填进 inputs(比如录音整理要 call_id 和 customer_id),不知道就先问用户、别编。返回运行号和核对入口:**原样告诉用户「已发起,等人工核对通过才会写进系统」**,别说成已经办完。返回里有「回复」是工作流说给用户的话,**原样转述,别改写**;「还在跑」就告诉用户稍后可以问进度(那时用 workflow_replies)。返回里带「交还」时,说明接管刚被关掉,照常用技能做。",
  "input_schema":{"type":"object","properties":{
    "skill":{"type":"string","description":"被拦下的那个技能名,原样照抄拦截理由里的(如 call-notes)"},
    "inputs":{"type":"object","description":"这条工作流要的输入,键名照工作流的要求填;录音整理是 call_id(录音号)和 customer_id(客户号)"}},
   "required":["skill","inputs"]}},
 {"name":"workflow_replies","description":"**查一条从聊天发起的工作流现在说了什么、跑到哪了**(只读)。用户问起刚才发起的那件事「怎么样了 / 好了没」时用:run_id 填 start_workflow 回过的运行号。返回里「回复」是工作流说给用户的话,**原样转述,别改写、别补充**;「在等人工核对」就照实说还在等店长核对;只查得到自己发起的那几条。",
  "input_schema":{"type":"object","properties":{
    "run_id":{"type":"string","description":"运行号,照抄 start_workflow 回的(如 xr_7bb01e3c29f0)"}},
   "required":["run_id"]}},
 {"name":"offer_call_upload","description":"**在聊天里给导购出一个「上传录音」按钮**(本身不写任何东西)。导购要提交跟进 / 回访记录、完成一条回访任务、说「刚跟客户打完电话 / 上门 / 到店聊完」时用 —— **别让他把录音内容打字复述**,让他直接传录音。要先知道客户号(只有姓名就先 get_customer);是在完成某条任务时就把任务号也带上。返回后照「说明」告诉导购:选文件和沟通方式点上传,转完文字会自动走录音跟进,整理出的跟进要人核对通过才写进系统;**别说成已经传了、已经写了**。",
  "input_schema":{"type":"object","properties":{
    "customer_id":{"type":"string","description":"客户号,如 C10009"},
    "task_id":{"type":"string","description":"在完成哪条任务时传的(可不填),照抄任务号"}},
   "required":["customer_id"]}},
 {"name":"get_scheme","description":"查方案。**方案是「一件事」的单位** —— 客户这次想做的这件衣服(形制/面料/工艺/颜色/配饰/版型都挂在它上面),有自己的生命周期:草稿 → 已保存 → 已锁定 → 已失效。三种问法:给 scheme_id 返回单条明细(并附上该客户的其他方案);给 customer(客户号或姓名)列这个客户的全部方案;给 status 按状态筛。⚠️ **同一个客户并行多条方案是常态** —— 客户或顾问说「那个方案」「刚才那套」时,**先调这个工具看清楚有几条,不要默认只有一条就往下推进**。推进(报价、下单、排产)之前必须确认说的是哪一个方案号。",
  "input_schema":{"type":"object","properties":{
    "scheme_id":{"type":"string","description":"方案号,形如 SC2601"},
    "customer":{"type":"string","description":"客户号或姓名。不知道方案号时先用这个列清单。"},
    "status":{"type":"string","description":"按状态筛:草稿 / 已保存 / 已锁定 / 已失效"}},"required":[]}},
 {"name":"get_order","description":"查订单。给 order_id 返回单条全链路(双口径状态、金额勾稽、时间线、订单行、关联售后);给 customer(客户号或姓名)返回该客户的订单清单。**返回里的「勾稽异常」不为空时,必须先核对再答复客户**,不要直接把金额念给客户听。注意状态有两套口径:页面按设计稿 10 档、PRD 按状态机 6 档,对客户说页面口径。",
  "input_schema":{"type":"object","properties":{
    "order_id":{"type":"string","description":"订单号"},
    "customer":{"type":"string","description":"客户号或姓名。不知道订单号时先用这个列清单。"}},"required":[]}},
 {"name":"get_stock","description":"查现货。四种问法,给其中一个参数即可:sku=某个具体规格;spu=某个商品的全部规格;material=某种面料还有多少米;**craft=这个工艺有哪些面料是现货且相容的**。最后一种用于回答「能不能快一点」——换现货面料可以把备料从十几二十天压到 1–3 天,但**面料换了质感和售价都会变,必须让客户确认,不能替他决定**。",
  "input_schema":{"type":"object","properties":{
    "sku":{"type":"string"},"spu":{"type":"string","description":"商品编码或名称"},
    "material":{"type":"string","description":"面料名称,直接写中文"},
    "craft":{"type":"string","description":"工艺名称。用来找「现货且能做这个工艺」的面料。"}},
   "required":[]}},
 {"name":"get_capacity","description":"查工坊产能排期。**不传 craft 就是全工坊负载概览**(每个工种几人、在制多少、手上的活要消化几天、瓶颈在哪);传 craft 则返回这个工艺**最早什么时候能排上**、谁来做、要做到几号、有几位师傅可选。两条要点:①返回 `不可加人=true` 时,说明会这个工艺的师傅只有一位或都是一人一机(缂丝、妆花、手绘、顾绣、发绣),**排满了就只能等,加钱也没用**;②返回 error 说没有师傅会做时,那**不是排期问题是产能缺口**,只能外发或者不接这个单。注意 kb_lead 已经自动把排队等待算进工期了,这个工具是给工坊排产用的,不必为了算工期再调一次。",
  "input_schema":{"type":"object","properties":{
    "craft":{"type":"string","description":"工艺名称,直接写中文。不传则返回全工坊概览。"},
    "workdays":{"type":"number","description":"这活需要多少工日,默认 10"},
    "from_date":{"type":"string","description":"从哪天起算,YYYY-MM-DD,默认今天"}},"required":[]}},
 {"name":"get_workorder","description":"查**在制工单**:这件活在谁手上、做到哪一步、会不会拖。可按工单号、师傅(工号或姓名)、状态、订单号筛;传 `overdue=true` 只看已逾期的。\n\n**和 get_capacity 分工**:get_capacity 给工种级的负载和瓶颈(接不接得下),get_workorder 给单件的去向和进度(这一件怎么办)。排产两个都要。\n\n返回里「剩余天数」为负说明已经过了交期,**逾期的要先说,不要埋在列表里**;一个师傅在制件数超过他的 wip_limit,说明已经排满,再派活只会更晚。**这个工具只读,不能改期不能改派。**",
  "input_schema":{"type":"object","properties":{
    "workorder_id":{"type":"string","description":"工单号,如 WO8001"},
    "artisan":{"type":"string","description":"师傅工号或姓名"},
    "status":{"type":"string","description":"在制 / 已完成"},
    "ref":{"type":"string","description":"订单号"},
    "overdue":{"type":"boolean","description":"只看已逾期的"}},"required":[]}},
 {"name":"check_write","description":"问「**这件事业务允不允许做**」时用它:拿真正的校验器跑一遍,返回能不能做、错误码和理由,**不写库**。支持 `建档`(新建客户)和 `预约`(含补录);fields 传要写的字段,role 传角色(顾问 / 店长 / 总部运营,不传按顾问算)。",
  "input_schema":{"type":"object","properties":{
    "action":{"type":"string","description":"建档 或 预约"},
    "fields":{"type":"object","description":"要写的字段,如 {name,phone,shop} 或 {start,end,way};另可传 role"}},
   "required":["action"]}},
 {"name":"get_aftersale","description":"查售后记录(退货/换货/退款/维修),可按订单号、客户或状态筛 —— **三个参数可以单独用,也可以合用**;只给 status 就是列出所有这个状态的售后单(如「现在有哪些退款失败的」),不用先要订单号。退款类会带上退款轨迹。**这个工具只给事实,不给判责结论** —— 判责标准在 kb_tables 的「售后争议判定」表里,要另外查。查不到就如实说查不到,不要推测客户提过什么。",
  "input_schema":{"type":"object","properties":{
    "order_id":{"type":"string"},"customer":{"type":"string","description":"客户号或姓名"},
    "status":{"type":"string","description":"如「退款失败」「审批同意」。可单独给,不必配订单号或客户"}},"required":[]}},
 {"name":"get_wearer","description":"查着装人档案 —— **衣服穿在谁身上**,和「谁付钱」是两回事。**身份绑在账户上**(账户以手机号为主标识,一个账户可以有多个着装人),不绑门店档案 —— 同一个人在不同店建过档就是两条档案。返回里「账户.关联门店档案」大于 1 时,说明这个人有多条门店档案,那正是客户合并要处理的情况。**手机号一律脱敏返回,账号密码任何情况下都拿不到。**妈妈给女儿买汉服时,付款人、收货人、量体对象是三个人。给 customer(客户号或姓名)返回这个账号下的全部着装人(本人/配偶/子/女),给 wearer_id 查单个。返回里的「量体是否过期」为真时,**下单前必须拦下要求复量** —— 超期的量体记录不是参考值,是无效值,「有个旧尺寸总比没有强」正是童装返工的来源。没有有效身体数据同意的着装人,量体数据一律取不到。",
  "input_schema":{"type":"object","properties":{
    "account":{"type":"string","description":"**手机号**(账户主标识,最常用)、账户号或自设账号"},
    "customer":{"type":"string","description":"门店客户号或姓名"},
    "wearer_id":{"type":"string","description":"着装人编号,如 W10001-2"}},"required":[]}},
 {"name":"get_maintain","description":"查售后维修工单的**现场**。客户说「衣服起球了 / 开线了 / 尺寸不对」时用。返回这件是什么(形制/可选面料/可选工艺)、客户报的问题、**量体记录全不全、是不是顾问亲自量的**(业务 09-22 不准远程量体)、**交付时有没有书面告知签收**、以及该客户历史维修次数。\n\n**这个工具只给事实,不给判责结论** —— 判定表要另外调 kb_tables 取「售后争议判定」,并对照 09-养护与售后.md 第五节。两条关键判据:①「交付告知签收」为 null 表示**没有书面告知记录**,特性类问题(起球/色差/掉色/勾丝)在这种情况下按「我方,让步处理」,已告知则「无责,解释 + 提供保养服务」;② 尺寸类问题看量体记录完不完整、是不是**远程**量的(远程按合同分担)。\n\n**结论必须由人确认后执行,你只出草稿。** 不要直接对客户承诺免费返修或赔付金额。",
  "input_schema":{"type":"object","properties":{
    "maintain_id":{"type":"string","description":"维修工单号,如 MW73020"},
    "customer":{"type":"string","description":"客户号或姓名"},
    "status":{"type":"string","description":"如「待确认」「处理中」"}},"required":[]}},
 {"name":"plan_for_event","description":"场景倒推 —— 客户说「明年六月毕业礼要穿」时用这个。它把四个互相咬着的约束一次算完:①选码用**穿的那天**的预测身高,不是今天的;②下单太晚排不上产能;③**下单太早也不行** —— 用的量体更旧、推算跨度更长,误差更大;④下单前必须有没过期的量体。所以返回的是一个**窗口**:建议复量日 + 最晚下单日,不是单个日期。「尺码是否跨档」为真时说明围度区间横跨两个码,**按大的做并留折边** —— 小了没法救,大了能收。离最晚下单日超过 60 天时会带「换商品建议」:先推尺寸宽容的定制款,家长不想定制再推现货标品 —— **两种都要说**;客户坚持要原款,就按窗口等到复量日前后再下。返回的「提醒」和「限定」必须一并说给客户。",
  "input_schema":{"type":"object","properties":{
    "wearer_id":{"type":"string","description":"着装人编号"},
    "event_date":{"type":"string","description":"要穿的那天,YYYY-MM-DD"},
    "pattern":{"type":"string","description":"版型编码或名称"},
    "material":{"type":"string","description":"面料名称"},
    "crafts":{"type":"array","items":{"type":"string"},"description":"工艺名称列表"},
    "scope":{"type":"string","description":"局部 / 整幅,默认局部"}},
   "required":["wearer_id","event_date","pattern","material"]}},
 {"name":"forecast_growth","description":"推算某个着装人到未来某天的身高,并给留成长量建议。主要用于**小孩** —— 定制工期 30–150 天,成人这段时间不变,小孩能长 1–2.5cm,而童装档差只有 4–6cm。**必须把返回里的「区间」和「限定」一起说给客户**,只报一个点估计等于骗人:推的是统计分布不是这个孩子,个体差 ±5cm 是常态,青春期突增的起始时间个体差可达 2–3 年。**围度只给区间不给点估计,任何情况下不得用推算围度直接下单裁剪。**「靶身高校验.需人工确认」为真时说明遗传身高和推算差得多,**转人工,不要自己挑一边**。",
  "input_schema":{"type":"object","properties":{
    "wearer_id":{"type":"string","description":"着装人编号,先用 get_wearer 查出来"},
    "target_date":{"type":"string","description":"推到哪天,YYYY-MM-DD。不传则按 months 算"},
    "months":{"type":"number","description":"往后推几个月,默认 12"}},"required":["wearer_id"]}},
]

# ── F3:出工具的那一刻,一律脱敏 ────────────────────────────────────────
# **位置很关键**:不能放在 _rows(数据访问层)—— 内部的数据体检要拿真手机号
# 做归户对账,脱敏了就查不了。放在**工具出口**:库里是真的,
# **离开工具的那一刻**才脱敏。
#
# 这样任何新加的工具**默认就是脱敏的** —— 不靠作者记得写 _mask()。
# 在此之前 _mask 全项目只被调用一次,「对外一律脱敏」是一句**约定**,不是结构。
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 固定电话(用户 11-22 拍前三后三):文字里只认「0 开头区号 + 横杠 / 空格 + 7–8 位」;连写的不认 —— 和订单号这类长数字分不开,宁漏不误
_LANDLINE = re.compile(r"(?<![\dA-Za-z.])0\d{2,3}[-\s]\d{7,8}(?![\dA-Za-z.])")


def _mask_out(o, depth=0):
    """递归把返回值里的手机号脱敏。字符串里夹着的也认。"""
    if depth > 8: return o
    if isinstance(o, str): return _LANDLINE.sub(lambda m: _mask(m.group()), _PHONE.sub(lambda m: _mask(m.group()), o))
    if isinstance(o, dict): return {k: _mask_out(v, depth + 1) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_mask_out(v, depth + 1) for v in o]
    return o


def _masked(fn):
    def wrap(*a, **kw): return _mask_out(fn(*a, **kw))
    wrap.__name__, wrap.__doc__ = fn.__name__, fn.__doc__
    # **把原函数挂上去。** 不挂的话,任何想看这个工具真实实现的检查
    # (比如 isolation_check 查「写工具有没有从会话取身份」)看到的都是
    # 这三行包装器 —— 它会报「没取身份」,而实际取了。
    # 检查看错了对象,结论就是错的,而且错得很像真的。
    wrap.__wrapped__ = fn
    return wrap


# ═══════════════════════════════════════════════════════════════════════
# 合并后的查询口 —— **一个业务对象一个工具,靠参数分,不靠工具名分**
#
# 2026-09-19。官方那条判据:**「如果一个人类工程师都说不准某个场景该用
# 哪个工具,AI 不可能做得更好」**。下面这三处原来是 9 个工具,而它们
# 各自族内查的是同一摊数据、只是换了筛选条件 —— 那不是「工具多」,
# 是**一件事被切成了好几件**。
#
# ⚠️ **合并的是「agent 看得见的工具面」,不是删实现。** 下面每一支都
# 原样调用老函数:权限判定、脱敏、边界口径全在那些函数里,已经被
# 门禁和咬合验过。重写一份等于把验过的东西作废重来。
# ═══════════════════════════════════════════════════════════════════════

















































# ── 拆出去的子模块(只搬了函数;变量 / 工具表 / 说明都还在这里)──────────────────────────
# ⚠️ 按文本读 api 源码的地方一律走 `api_src.全部源码()`,它从这个字面量取清单 —— 加子模块要登记在这里
子模块们 = ('api_kb', 'api_tasks', 'api_member', 'api_approval', 'api_report', 'api_aftersale', 'api_pattern', 'api_order', 'api_wearer', 'api_shift', 'api_workflow')
from api_kb import *          # noqa: E402,F401,F403
from api_kb import _combo_caveat, _kb_dir, _kb_file, _names, _resolve   # noqa: E402,F401  私有名 * 带不过去
from api_tasks import *          # noqa: E402,F401,F403
from api_member import *          # noqa: E402,F401,F403
from api_member import _ko_obj, _levels, _mem, _分人说明, _单客范围, _口径_journey, _口径_linkage, _名单范围, _场合词表, _整理一通, _纠错说明   # noqa: E402,F401  私有名 * 带不过去
from api_approval import *          # noqa: E402,F401,F403
from api_approval import _认顾问   # noqa: E402,F401  私有名 * 带不过去
from api_report import *          # noqa: E402,F401,F403
from api_report import _by_agent, _wk_月起, _上期行动, _受欢迎取数, _报告规则版本, _活动渠道共线, _种下的提醒   # noqa: E402,F401  私有名 * 带不过去
from api_aftersale import *          # noqa: E402,F401,F403
from api_aftersale import _挡住不该给的   # noqa: E402,F401  私有名 * 带不过去
from api_pattern import *          # noqa: E402,F401,F403
from api_pattern import _grading_scan, _pattern_queue, _档差核况   # noqa: E402,F401  私有名 * 带不过去
from api_order import *          # noqa: E402,F401,F403
from api_order import _亲量档位, _以哪次为准, _工厂回传, _白坯试衣, _白坯试衣_预取, _签收日期, _订单标签, _部位模块, _量体完整性   # noqa: E402,F401  私有名 * 带不过去
from api_wearer import *          # noqa: E402,F401,F403
from api_wearer import _account, _consent_ok, _lt, _mask, _wearer, _名下着装人, _换商品建议   # noqa: E402,F401  私有名 * 带不过去
from api_shift import *          # noqa: E402,F401,F403
from api_shift import _排班今天   # noqa: E402,F401  私有名 * 带不过去
from api_workflow import *          # noqa: E402,F401,F403

TOOLS.update({"bad_ratings":bad_ratings,"rating_overview":rating_overview,
              "get_tasks":get_tasks,"get_member":get_member,
              # ⚠️ 老名字**留在 TOOLS 里**(边界审计和隔离检查按 TOOLS 逐个跑),
              #    但已经从 SHOP_SCHEMAS 下架 —— **TOOLS 是实现登记册,
              #    SCHEMAS 才是 agent 看得见的工具面**,要降的是后者。
              "get_scheme":get_scheme,"get_order":get_order,"get_stock":get_stock,"get_aftersale":get_aftersale,
              "get_capacity":get_capacity,
              "get_wearer":get_wearer,"forecast_growth":forecast_growth,
              "plan_for_event":plan_for_event,"get_maintain":get_maintain,
              "get_workorder":get_workorder,
              "get_lifecycle":get_lifecycle,
              "get_member_priority":get_member_priority,
              "check_write":check_write,
              "my_tasks":my_tasks,"task_types":task_types,"dispatch_pool":dispatch_pool,
              "team_tasks":team_tasks,"monthly_review":monthly_review,"member_level":member_level,"points_ledger":points_ledger,"approval_queue":approval_queue,"activity_roi":activity_roi,"can_order":can_order,"my_workorders":my_workorders,"piece_ratios":piece_ratios,"set_piece_ratio":set_piece_ratio,"set_grade_diff":set_grade_diff,"pattern_queue":_pattern_queue,"recovery_queue":recovery_queue,"stock_alert":stock_alert,"fitting_queue":fitting_queue,"factory_chase":factory_chase,"orders_by_date":orders_by_date,"sales_rank":sales_rank,"weekly_revenue":weekly_revenue,"store_report":store_report,"summarize_products":summarize_products,"get_product_images":get_product_images,"draft_capability_request":draft_capability_request,"save_report":save_report,"confirm_report":confirm_report,"list_reports":list_reports,"report_production":report_production,"order_log":order_log,"cancel_fee":cancel_fee,"delay_pending":delay_pending,"mark_delay_told":mark_delay_told,"rollback_order":rollback_order,"close_bad_rating":close_bad_rating,"service_records":service_records,"record_fitting":record_fitting,"record_measure":record_measure,"open_order":open_order,"confirm_order":confirm_order,"record_pickup":record_pickup,"verify_fit_code":verify_fit_code,"ratify_complete":ratify_complete,"create_repair":create_repair,"decide_repair":decide_repair,"advance_repair":advance_repair,"verify_repair_return":verify_repair_return,"start_cutting":start_cutting,"channel_compare":channel_compare,"product_ranking":product_ranking,"wear_risk":wear_risk,"return_rate":return_rate,"part_options":part_options,"order_parts":order_parts,"draft_delivery_notice":draft_delivery_notice,"record_delivery_notice":record_delivery_notice,"grading_audit":grading_audit,"apply_adjust":apply_adjust,"decide_approval":decide_approval,"appt_funnel":appt_funnel,"week_grid":week_grid,"assign_batch":assign_batch,"recovery_followup":recovery_followup,"shift_preview":shift_preview,"shift_draft":shift_draft,"shift_publish":shift_publish,"dispatch_batch":dispatch_batch,"get_task":get_task,"assign_task":assign_task,"dispatch_task":dispatch_task,"reassign_task":reassign_task,"finish_task":finish_task,"start_workflow":start_workflow,"workflow_replies":workflow_replies,"offer_call_upload":offer_call_upload,
              "ownerless_list":ownerless_list,
              "list_appointments":list_appointments,"book_appointment":book_appointment,"reschedule_appointment":reschedule_appointment,
              "call_opportunity":call_opportunity,
              "revive_list":revive_list,
              "churn_watch":churn_watch,
              "on_shift":on_shift,
              "deal_credit":deal_credit,
              "customer_history":customer_history,
              "conversion_rate":conversion_rate})
# ══════════════════════════════════════════════════════════════════════
# kb_rag:**语义检索管理后台那份知识库的原文**(2026-10-08,业务拍的第 ④ 步)
#
# 和 `kb_read` 的分工(这一条最要紧,写在最前面):
#
#     kb_read   你**知道**要看哪一篇哪一节 → 按编号/标题取原文
#     kb_rag    你**不知道**在哪一篇 → 按意思找,它把最相关的几段捞回来
#
# 顾问问「客户给了差评要怎么处理」,`kb_read` 要先猜这事写在第几篇;
# 而 `kb_rag` 直接按意思找。**两个都要,因为知道篇号的时候 kb_read 更准、更便宜。**
#
# ## ⚠️ 业务 2026-10-08 拍的两条,落点在这儿
#
#   **① 管理后台这条路断了 → 明确报错,不退回别的工具装作没事。**
#      所以下面**一个退路分支都没有** —— 连不上、非 200、没索引,
#      一律返回 `{"error": …, "怎么办": …}`,由模型照实说。
#      管它的规矩是 `TL64`(提示词里),它要求模型**说出来**,不许凭记忆答。
#      > 一次「知识库查不了」和一次「它根本没查」,
#      > **在顾问看到的那段回答上长得一模一样** —— 而前者该说出来。
#
#   **② 每次都查,不自己判断「要不要查」** —— 这条在**提示词**那一侧
#      (工具只负责查;「什么时候该调它」是规矩的事)。
#
# ## ⚠️ 这里**不要管理后台生成的答案**(`要生成` 不传 = 默认 true,所以显式传 false)
#
# 管理后台那条链能自己生成答案(带出处校验),而这里**只拿证据** ——
# 让 chat 自己的模型照着答。理由:
#   · chat 那个模型有**角色规矩和完整上下文**(来源等级、对客口径、免责那一套),
#     而管理后台那边只有四段证据;
#   · 两个模型答同一个问题,chat 还要把它转述一遍 —— **转述那一步会悄悄改意思**;
#   · 快 5 倍、便宜(少一次生成调用)。
# **代价写清:这样就没有「它有没有照着证据答」那层校验** ——
# 那层在管理后台的检索实验室里看得到(选片之后那张答案卡),chat 这条路上没有。
#
# ## 身份与项目
#
# 走管理后台的**开发模式身份头**(`X-Dev-User`)。⚠️ 上生产要换成服务令牌 ——
# 这件事写在这儿而不是等人发现。
_后台基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
_后台项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
_后台身份 = os.environ.get("AIMC_USER", "U001")

# ⚠️⚠️ **岗位 → 管理后台角色的映射:业务还没拍**(2026-10-08 我问了,没拍)。
#
# 语料权限(两级 ACL)是用**管理后台的角色词表**写的(viewer/editor/…),
# 而这边的身份是**岗位**。两套名字不是一套,而今天两级 ACL **全是空的** ——
# 所以传任何合法角色都「能用」:
# > 一个「映射拍过了」和一个「我挑了个看起来合理的」,
# > **在这张表上长得一模一样** —— 这段注释就是那个区别。
#
# 默认全给 `viewer`(最小的那个):**错的方向是「看不到」,不是「看到不该看的」**。
# 拍了之后改这里;`backend/rag_bridge_check.py` 盯着它不许出现 admin。
岗位到后台角色 = {
    "门店顾问": "viewer",
    "工坊排产": "viewer",
    "后台运营": "viewer",
}




TOOLS.update({"kb_lookup":kb_lookup,"kb_detail":kb_detail,"kb_tables":kb_tables,"kb_read":kb_read,
              "kb_combo":kb_combo,"kb_coverage":kb_coverage,
              "kb_pattern":kb_pattern,"kb_size":kb_size,"kb_bom":kb_bom,
              "kb_fit":kb_fit,"kb_lead":kb_lead,"kb_rag":kb_rag})
# **统一包一层** —— 放在这里而不是每个函数上,是为了「新加工具自动生效」。
# 漏包一个就等于开了个口子,而漏包是**不会报错**的。
#
# ⚠️ **原地改写,不要重新绑定 `TOOLS = {...}`。**
# 重新绑定的话,任何在这一行之前 `from api import TOOLS` 的模块
# 会一直拿着**没包装的那份**,脱敏静默失效。
# (这处是项目里的重复定义检查抓出来的 —— 它抓到的不只是命名冲突,
#  是一个真实的绑定时序隐患。)
for _k in list(TOOLS): TOOLS[_k] = _masked(TOOLS[_k])

KB_SCHEMAS=[
 {"name":"kb_lookup","description":"按关键词查工艺知识库。也可按分类(形制/材质/工艺/配饰)或来源等级(public/scale/biz/demo)筛选。查不到会明确返回 hit=0。",
  "input_schema":{"type":"object","properties":{
    "keyword":{"type":"string","description":"关键词,如「香云纱」「盘金」「金线」"},
    "cat":{"type":"string","enum":["形制","材质","工艺","配饰"]},
    "src":{"type":"string","enum":["public","scale","biz","demo"]}},"required":[]}},
 {"name":"kb_detail","description":"按编码取一条知识的完整内容(含出处链接)。编码形如 KF01 / MT01 / XZ01 / PS01。",
  "input_schema":{"type":"object","properties":{"code":{"type":"string"}},"required":["code"]}},
 {"name":"kb_combo","description":"查某工艺能否用于某面料。**工艺名和面料名直接写中文即可**(如「妆花」「云锦」),不必也不要猜编码 —— 名字对不上会明确报错并列出现有选项。返回「可/需评估/不可」、理由,以及 rule 字段(依据的规则号,或「人工确认」)—— 判「不可」时请把依据一并告诉用户;该组合未录入时返回「未定义」;返回里的 resolved 字段是实际解析到的那一对,回答前请核对它和用户问的是不是同一对。",
  "input_schema":{"type":"object","properties":{
    "craft":{"type":"string","description":"工艺名称或编码,如「妆花」或 KF02。**直接写名称即可,不要猜编码。**"},
    "material":{"type":"string","description":"面料名称或编码,如「云锦」或 MT02。**直接写名称即可,不要猜编码。**"}},
   "required":["craft","material"]}},
 {"name":"kb_rag","description":"**按意思在知识库原文里找** —— 你不知道这事写在哪一篇的时候用它(`kb_read` 是你已经知道篇号时用的,那条更准更便宜)。它把最相关的几段原文捞回来,**每段带能翻回原文的出处**(「业务拍板 · 2026-09-27 / 二、几星算差评 · 第 4 段」)—— **出处要带给顾问**,一个查不回去的引用比没有引用糟。⚠️ 它查的是**管理后台那份知识库**,所以那条路断了会返回 `error` —— **那时候要照实说「知识库现在查不了」,不许凭记忆答**(见 TL64)。而 `hit=0` 是另一回事:检索跑成了、一片都没选中,那是真的「知识库里没有」。","input_schema":{"type":"object","properties":{"question":{"type":"string","description":"顾问问的那句话,**原样传**(不要自己改写成关键词 —— 它内部会改写)"},"role":{"type":"string","description":"问的人是哪个岗位(中文名):门店顾问 / 工坊排产 / 后台运营。不传当门店顾问"}},"required":["question"]}},
 {"name":"kb_read","description":"**读知识库原文** —— 表里查不到、只在正文里的那些话:怎么洗怎么存、为什么这么做、客户问「为什么这么贵」时怎么答。**先不传 section 拿这一篇的小节目录,再指定小节取正文** —— 不给整篇,一次几百行会把后面真正该看的挤出去。doc 认编号(09)、文件名、或主题词(养护)。返回带**来源等级**:一节里混着几档时按**最低那一档**给对客口径;**正文里没有标记不代表它可靠,代表没人标过**。","input_schema":{"type":"object","properties":{"doc":{"type":"string","description":"篇:01–16 的编号、文件名、或主题词(如「养护」「版型库」)"},"section":{"type":"string","description":"小节标题(写一部分也认)。不传则给这一篇的小节目录"}}}},
 {"name":"kb_tables","description":"取全部决策表(6 张共 30 行:客户原话对照、选料决策、配饰形制搭配、配色易错、工期档位、售后争议判定)。顾问问「客户说了 X,我该推什么/避开什么/怎么处理」这类问题时**优先用这个**,而不是 kb_lookup。**直接不带参数调用即可**,取全部比挑一张更可靠。topic 填「待核实」是另一件事:看哪些工艺×面料组合被顾问问到了、却没有任何依据(按被问次数排,只说「谁被问了」不说答案;答案要工艺负责人打样,回填在后台做,**你只能看,不能填**)。",
  "input_schema":{"type":"object","properties":{"topic":{"type":"string","description":"通常不要传。全部决策表合计只有 30 行,一次全取更可靠 —— 传了 topic 反而容易取错表。"}},"required":[]}},
 # kb_coverage(相容矩阵完成度)2026-09-22 从模型可见的工具里拿掉:矩阵早已 2025 格全有结论,
 # 这个数对顾问回答任何问题都没用,只是每轮多带一段说明(能力盘点)。函数留着 —— prompts_check 直接调它数格子。
 {"name":"kb_pattern","description":"查版型库:某个形制有哪些版型、每个版型分几个裁片、能出哪些尺码、改版难度多高。**客户问「这个能不能改尺寸/能不能做小码」时用这个。**某个尺码不在列表里,意味着这个版型裁不出来,不是缺货。",
  "input_schema":{"type":"object","properties":{
    "xz":{"type":"string","description":"形制名称或编码,如「明制马面裙」或 XZ03。不传则列出全部版型。"}},"required":[]}},
 {"name":"kb_size","description":"查某版型的成衣尺码表(各部位厘米数)。**返回的是成衣尺寸不是人体尺寸**,和客户量体值之间差一个放松量,不能直接比。推荐尺码最终由版师定。",
  "input_schema":{"type":"object","properties":{
    "pattern":{"type":"string","description":"版型名称或编码,如「明制马面裙·标准」或 PT04"},
    "size":{"type":"string","description":"只看某一个码,如 M。不传则返回全部码。"}},"required":["pattern"]}},
 {"name":"kb_fit","description":"拿客户的量体记录比对版型尺码表,给出**推荐尺码**和**档位**(标准码 / 调号 / 全定制 / 需补量 / **判不了**)。⚠️ **「判不了」是「不知道这件给谁做」**—— 名下不止一人量过体而没传 wearer 时就是它,返回里列着候选。这时**去问给谁做,不要自己挑一个**,也不要说「请补量」(量体是全的)。返回逐项差值,标出哪几项是这个形制的关键尺寸。三条铁律:①系统只给建议,**最终由版师定**;②档位是「需补量」时**绝不能按身高体重猜码**,要请客户补量;③返回里的「关键尺寸未覆盖」列出的项系统比不了(比如马面宽没有对应量体项),必须告诉用户这几项还需人工确认,不能让人以为已经全查过了。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户姓名或客户号"},
    "pattern":{"type":"string","description":"版型名称或编码,如「明制马面裙·标准」或 PT04。不知道有哪些版型时先用 kb_pattern 查。"},
    "wearer":{"type":"string","description":"着装人编号(W 开头)。**衣服穿在谁身上就填谁**。名下**只有一人量过体**时不填会退回到账户的「本人」;**不止一人量过体时不填就拿不到码**(返回档位「判不了」+ 候选)。一个账户下常有好几个人(妈妈给两个孩子做),尺寸和体型各不相同 —— **名下有多个着装人是常见情况,不是例外**,不填就等于让系统替你挑一个人。先用 get_wearer 查这个客户名下都有谁。"}},
   "required":["customer","pattern"]}},
 {"name":"kb_lead","description":"算工期:给定版型 + 尺码 + 面料 + 工艺,返回**最快到最慢的天数区间**、每一段花多久、**关键路径卡在哪一环**、有哪些风险、哪些环节加钱能压缩。**已经把工坊的排队等待算进去了**(师傅手上压着活,新单要排队),不必再单独查产能。传了 need_date(用件日期,YYYY-MM-DD)还会倒推最晚下单日并判断来不来得及。三条铁律:①**对客户报最慢那个数**,余量留给自己,绝不能报最快的;②「关键路径」告诉你加钱只对哪一环有用 —— 不在关键路径上的环节压缩了也没用;③返回的「风险」里凡是提到**不能靠加人压缩**(织造、染色晾晒、手绘顾绣发绣)的,加急要求必须当场拒绝,不要先答应再想办法。",
  "input_schema":{"type":"object","properties":{
    "pattern":{"type":"string","description":"版型名称或编码"},
    "size":{"type":"string","description":"尺码,如 M"},
    "material":{"type":"string","description":"面料名称,直接写中文"},
    "crafts":{"type":"array","items":{"type":"string"},"description":"所选工艺名称列表"},
    "scope":{"type":"string","enum":["局部","整幅"],"description":"整幅按局部的 4 倍估,默认局部"},
    "workers":{"type":"integer","description":"安排几个师傅并行,默认 2。注意染色、织造、手绘这些除不动。"},
    "from_date":{"type":"string","description":"从哪天起算,YYYY-MM-DD。不传按今天。"},
    "need_date":{"type":"string","description":"客户的用件日期 YYYY-MM-DD。婚礼、写真这类**日子不能改**的场合必须传,系统会倒推最晚下单日。"}},
   "required":["pattern","size","material"]}},
 {"name":"kb_bom","description":"算料算钱:给定版型 + 尺码 + 面料 + 所选工艺,返回完整物料清单(每项的净用量、损耗、实际用量、单价、金额)、物料成本合计、备料周期和卡在哪个物料上。**客户问「多少钱」「要等多久」时用这个。** 注意:返回的是**物料成本,不是售价** —— 不含工时、门店成本与税,**绝不能把这个数当报价告诉客户**。",
  "input_schema":{"type":"object","properties":{
    "pattern":{"type":"string","description":"版型名称或编码"},
    "size":{"type":"string","description":"尺码,如 M"},
    "material":{"type":"string","description":"面料名称,如「云锦」。直接写名称,不要猜编码。"},
    "crafts":{"type":"array","items":{"type":"string"},"description":"所选工艺名称列表,如 [\"盘金绣\"]"},
    "scope":{"type":"string","enum":["局部","整幅"],"description":"工艺做局部还是整幅,整幅按局部的 4 倍估。默认局部。"}},
   "required":["pattern","size","material"]}},
]

# ── 工具的「模型说明」拼进 description(用户 2026-10-03 定:全拼进去)──────────────
# 真值在 backend/工具模型说明.json(后台只读展示),拼法在 backend/工具模型说明.py。
# **拼在三份 SCHEMAS 的源头**:MCP 和直连两条路都从这里取,mcp/parity.py 要求两边一字不差。
# ⚠️ 哪些来路能进提示词由那份文件里的白名单决定(管理后台会话 5b9dfde 装的闸);
#    用户选的是「全拼进去」,而那道闸现在挡着「评测题」—— 两者的取舍见 HANDOFF 10-03 那一节
import 工具模型说明 as _说明
SCHEMAS, SHOP_SCHEMAS, KB_SCHEMAS = _说明.拼进三份(SCHEMAS, SHOP_SCHEMAS, KB_SCHEMAS)
