#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判的「最终交付状态」要真的落库 —— 从请求体到库里那一跳(2026-10-26)。

## 这条判据在守什么

`sdk.run()` 算出 `交付检查`(通过 / 修正后通过 / 未通过 / 未检查 / 不完整),
`agentsite/app.py` 的 `_triage_one` **明确传给了** `/api/ops-triage`,
而后台这一跳**一个字都没读过**:`ops.save_triage()` 的签名里没这个参数,
`triage` 表里也没这列,三个页面 `交付检查` 的出现次数都是 0。

> 发送方传了、接收方不读,**两边都不报错**。

后果命中业务基准(「出错时用户看到什么」):库里只有 `guard_blocked`
(曾被打回过),而 `agentsite/sdk.py` 自己的注释写着「只有通过 / 修正后通过
算交付成功 —— 别拿 guard_blocked 当最终合格」。于是库里**分不开
「被闸扣下、没出结论」和「打回一次之后通过了」**,而这两者下一步动作相反:
前者要人工接手,后者照常复核。评测分得开(它直接读 `sdk.run()` 的返回、
没走库),**产品分不开**。

⚠️ 这是同一个函数上同一个形状的**第二次** —— `save_triage` 里 `trace_id`
那段注释写的正是「它一直在 `sdk.run()` 的返回里,但到这一跳就丢了」(09-28 补的)。
补那次的时候没人问一句「还有别的字段也在这一跳丢着吗」。

## 为什么要真打那一跳,而不是扫源码

这个 bug 活在**两个文件之间的契约**上:一头传、一头收,而中间没有任何
运行时检查。扫源码只能看见「某个字符串在不在」,而它在 —— 请求体里那个
`交付检查=` 一直都在,写它的人也以为存下去了。
所以这里造一个最小的假 handler **真打 `do_POST /api/ops-triage`**,
然后回库里读,看那个值在不在。闸和写口都在路由到函数之间那一段,
和 `customer_read_auth_check` 同一个办法、同一个理由。

## 在副本上跑

`ops.DB` 指到临时副本。⚠️ `ops.py` 第 20 行那段注释警告过:
**模块载入时的「本库」改不到** —— 销账后的判读上报只在本库上发生
(10-12 ops_resolve_check 在副本上销账,两条假判读进了真投递箱)。
这里只调 `save_triage` / `get_triage`,不碰销账,所以不受那条影响;
但副本仍然是必须的 —— 判据往真库里写研判,下一轮门禁的队列判据就会读到它。
"""
import json, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REAL = os.path.join(HERE, "lanxiu.db")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("后台写口不再把请求体里的「交付检查」传给 save_triage(回到 2026-10-26 之前)",
     "打真的 /api/ops-triage:请求体里的「交付检查」真的落进库"),
    ("save_triage 收了这个参数却不写库(UPDATE 那行删掉)",
     "打真的 /api/ops-triage:请求体里的「交付检查」真的落进库"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok: 坏.append(名)
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {名}{'  ' + 附 if 附 else ''}")


# ── 副本 ───────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="lanxiu-delivery-")
copy = os.path.join(tmp, "lanxiu.db")
shutil.copy(REAL, copy)          # shutil.copy **跟随软链**,所以这是一份真副本(cp -R 不是)

import ops, server                                            # noqa: E402
ops.DB = copy
server.DB = copy
# 前置断言:副本真的可用。sqlite3.connect() 对不存在的路径会**静默新建一个空库**,
# 于是「副本没拷成」和「表真的没有」报出一模一样的错(write_check 那次栽过)。
_表 = {r[0] for r in sqlite3.connect(copy).execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
if "triage" not in _表 or "task" not in _表:
    print(f"{R}❌ 副本没准备好{D} —— 共 {len(_表)} 张表,缺 triage / task。"
          f"**不是检查失败** :副本 {copy}({os.path.getsize(copy) if os.path.exists(copy) else 0} 字节)")
    sys.exit(1)
assert ops.DB == copy, "ops.DB 没指到副本 —— 停手,别往真库写"

print("研判的最终交付状态要真的落库 · 打真的写口(在临时副本上)")
print("=" * 74)

# ── ① 结构:库里有这一列 ───────────────────────────────────────────────
列 = {r[1] for r in sqlite3.connect(copy).execute("PRAGMA table_info(triage)")}
ck("triage 表里有 delivery_check 这一列", "delivery_check" in 列,
   f"共 {len(列)} 列")

# ── ② 真打那一跳 ──────────────────────────────────────────────────────
一张 = sqlite3.connect(copy).execute("SELECT id FROM task LIMIT 1").fetchone()
if not 一张:
    ck("副本里有工单可用(样本量 0 不叫通过)", False, "task 表是空的")
else:
    任务 = 一张[0]

    class _假H(server.H):
        """最小假 handler:只让 do_POST 跑到路由那一段。和 customer_read_auth_check 同一个办法。"""
        def __init__(self, 路, 体):
            self.path, self._体 = 路, json.dumps(体, ensure_ascii=False).encode()
            self.headers = {}
            self.回 = None
        def rfile_read(self):      # noqa: D401
            return self._体
        def _send(self, obj, code=200):
            self.回 = (code, obj)
            return None
        def send_response(self, *a, **k): pass
        def send_header(self, *a, **k): pass
        def end_headers(self): pass

    def 打(体):
        h = _假H("/api/ops-triage", 体)
        # do_POST 读请求体的方式各版本不同 —— 让它拿到我们这份,其余原样走
        import io as _io
        h.rfile = _io.BytesIO(h._体)
        h.headers = {"content-length": str(len(h._体)), "cookie": ""}
        try:
            server.H.do_POST(h)
        except Exception as e:                       # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"
        return h.回, None

    回, 错 = 打(dict(task_id=任务, bp="BP-01", case="判据·交付状态",
                     text="## 根因\n判据造的\n## 建议动作\n判据造的\n## 证据\n判据造的\n## 置信度\n低",
                     trajectory=[], 交付检查="未通过"))
    if 错:
        ck("打真的 /api/ops-triage:请求体里的「交付检查」真的落进库", False, 错)
    else:
        码, 体 = 回 if 回 else (None, None)
        tid = (体 or {}).get("triage_id")
        存 = None
        if tid:
            r = sqlite3.connect(copy).execute(
                "SELECT delivery_check FROM triage WHERE id=?", (tid,)).fetchone()
            存 = r[0] if r else None
        ck("打真的 /api/ops-triage:请求体里的「交付检查」真的落进库",
           存 == "未通过",
           f"HTTP {码} · triage_id {tid} · 库里存的是 {存!r}(期望 '未通过')")

        # ③ 不传时不写 —— 空值合法,不许拿别的顶上
        回2, 错2 = 打(dict(task_id=任务, bp="BP-01", case="判据·没传",
                          text="## 根因\n判据造的\n## 建议动作\n判据造的\n## 证据\n判据造的\n## 置信度\n低",
                          trajectory=[]))
        tid2 = ((回2 or (None, {}))[1] or {}).get("triage_id")
        存2 = None
        if tid2:
            r = sqlite3.connect(copy).execute(
                "SELECT delivery_check FROM triage WHERE id=?", (tid2,)).fetchone()
            存2 = r[0] if r else None
        ck("没传这个字段时,库里那一格是空的(空值合法,不许拿别的顶上)",
           存2 is None, f"库里存的是 {存2!r}" + (f" · {错2}" if 错2 else ""))

# ── ④ 发送方那一头也得在传(跨进程,只能扫源码)─────────────────────────
# 这一条和上面②是一对:②验「传了就存得下」,④验「那头真的在传」。
# 少了④,把 app.py 那行删掉之后②照样绿(它自己造请求体),
# 而线上库里那一列会永远是空的。
站 = open(os.path.join(os.path.dirname(HERE), "agentsite", "app.py"), encoding="utf-8").read()
ck("运维平台那头真的在传这个字段(agentsite/app.py 的 _triage_one)",
   "交付检查=r.get(\"交付检查\")" in 站 or "交付检查=r.get('交付检查')" in 站)

# ── ⑤ 页面得把它显示出来 ──────────────────────────────────────────────
# 10-23 栽过同一个形状:**后端分开报了,而页面把它压回去** ——
# 那次是销账来源三个字段在 queue.html 里出现 0 次。
页 = open(os.path.join(os.path.dirname(HERE), "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("研判详情页显示这个状态(后端存了而页面不显示 = 用户照旧看不见)",
   "delivery_check" in 页, f"queue.html 里出现 {页.count('delivery_check')} 次")

print("=" * 74)
shutil.rmtree(tmp, ignore_errors=True)
if 坏:
    print(f"{R}❌ 交付状态落库 {len(坏)} 处不符合预期{D}")
    for x in 坏: print(f"   · {x}")
    sys.exit(1)
print(f"{G}✅ 交付状态从请求体到库到页面这一条链是通的(验了 {n} 条){D}")
