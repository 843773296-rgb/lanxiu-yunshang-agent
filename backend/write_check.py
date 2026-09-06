#!/usr/bin/env python3
"""写接口 · 往返检查 —— 写进去的东西**真的在库里,而且字段没丢**。

## 为什么需要它

`create_appointment` 曾经这样写:

    vals = {..., "appt_at": d.get("appt_at"), "note": d.get("note")}
    use  = [k for k in cols if k in vals]        # 只写表里真有的列

而 appointment 表的列是 `start_ts` / `end_ts` —— 两个都不在 vals 里,
于是**时间被严格校验了(补录权限那条判据就是它),然后没有被存下来**,
接口照样返回 `ok: true`。`create_followup` 同样丢了 `ts`。

这个 bug 躲过了所有已有检查:
· `route_check` 只查函数存不存在 —— 它存在
· 接口返回 `ok:true` —— 状态码和返回体都正常
· 没人回头读那条记录 —— NULL 就一直躺着

**只有把写进去的东西读回来对一遍,才看得见。**

## 在副本上跑

写的是 `backend/lanxiu.db` 的一份临时副本,**绝不碰真库** ——
那是 spec_check / liability_check / member_check / rfm_check 四个检查的真值源,
往里写几行"合理"数据就会让反例不再是唯一用例(见 E3)。跑完删副本。
"""
import datetime, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REAL = os.path.join(HERE, "lanxiu.db")

tmpdir = tempfile.mkdtemp(prefix="lanxiu-write-")
copy = os.path.join(tmpdir, "lanxiu.db")
shutil.copy(REAL, copy)

import server
server.DB = copy          # 把写接口指到副本上
try: server.rules
except AttributeError: pass

bad = []
def check(no, desc, rows, why):
    print(f"  {'✅' if not rows else '❌'} {no}  {desc}")
    for r in rows[:4]: print(f"        · {r}")
    if rows: bad.append((no, why, len(rows)))

def q(sql, *a):
    c = sqlite3.connect(copy); c.row_factory = sqlite3.Row
    try: return [dict(r) for r in c.execute(sql, a)]
    finally: c.close()

print("写接口 · 往返检查(在临时副本上)")
print("=" * 92)

# ── W1 建客户:字段真的落库 ─────────────────────────────────────
r = server.create_customer(dict(name="检查用·勿动", phone="13900000001",
                                shop="SH001 静安旗舰店", advisor="A01 林岚",
                                birthday="1995-03-03", addr="上海市静安区检查路 1 号",
                                role="店长"))
w1 = []
if not r.get("ok"): w1.append(f"建档被拒:{r.get('code')} {r.get('reason')}")
else:
    got = q("SELECT * FROM customer WHERE id=?", r["id"])
    if not got: w1.append("接口说建好了,库里查不到")
    else:
        g = got[0]
        for k, want in [("name", "检查用·勿动"), ("shop", "SH001 静安旗舰店"),
                        ("birthday", "1995-03-03")]:
            if g.get(k) != want: w1.append(f"{k} 存成了 {g.get(k)!r},应为 {want!r}")
        if g.get("lifecycle") != "潜在":
            w1.append(f"新客户生命周期应为「潜在」(无完成订单),实际 {g.get('lifecycle')!r}")
check("W1", "建客户:接口说成功,库里就得有,且字段不能变形", w1,
      "返回 ok:true 但字段没落库 —— 状态码正常、返回体正常,只有读回来才看得见")

# ── W2 建预约:**时间必须真的存下来** ──────────────────────────
st = (datetime.datetime.now() + datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
et = (datetime.datetime.now() + datetime.timedelta(days=3, hours=1)).strftime("%Y-%m-%d %H:%M")
r2 = server.create_appointment(dict(customer_id="C10000", shop="SH001 静安旗舰店",
                                    advisor="A01 林岚", start=st, end=et,
                                    way="到店量体", role="店长"))
w2 = []
if not r2.get("ok"): w2.append(f"建预约被拒:{r2.get('code')} {r2.get('reason')}")
else:
    got = q("SELECT * FROM appointment WHERE id=?", r2["id"])
    if not got: w2.append("接口说建好了,库里查不到")
    else:
        g = got[0]
        # **这一条就是那个 bug 的化身**:时间被校验了,却没被存下来。
        if not g.get("start_ts"): w2.append("start_ts 是空的 —— 时间校验过了却没存下来")
        if not g.get("end_ts"):   w2.append("end_ts 是空的")
        if g.get("start_ts") and g["start_ts"][:16] != st[:16]:
            w2.append(f"start_ts 存成了 {g['start_ts']!r},传的是 {st!r}")
check("W2", "建预约:校验过的时间必须真的落到 start_ts / end_ts", w2,
      "**时间被严格校验,然后被静默丢弃** —— 接口返回 ok:true,记录里一片 NULL")

# ── W3 建跟进:时间戳不能空 ────────────────────────────────────
r3 = server.create_followup(dict(customer_id="C10000", content="检查用跟进,勿动",
                                 advisor="A01 林岚", channel="电话"))
w3 = []
if not r3.get("ok"): w3.append(f"建跟进被拒:{r3.get('code')} {r3.get('reason')}")
else:
    got = q("SELECT * FROM followup WHERE id=?", r3["id"])
    if not got: w3.append("接口说建好了,库里查不到")
    else:
        g = got[0]
        if not g.get("ts"): w3.append("ts 是空的 —— 跟进是流水,没有时间就没有意义")
        if g.get("content") != "检查用跟进,勿动":
            w3.append(f"content 存成了 {g.get('content')!r}")
check("W3", "建跟进:内容和时间戳都要落库", w3, "跟进是只增不改的流水,没有时间戳的流水没有意义")

# ── W4 业务拒绝要**真的没写进去** ─────────────────────────────
n0 = q("SELECT COUNT(*) c FROM customer")[0]["c"]
r4 = server.create_customer(dict(name="", phone="13900000002", role="店长"))
n1 = q("SELECT COUNT(*) c FROM customer")[0]["c"]
w4 = []
if r4.get("ok"): w4.append("空姓名被放行了 —— rules.validate_customer 说姓名必填")
if n1 != n0: w4.append(f"拒绝了却还是写进去了({n0} → {n1} 行)")
check("W4", "业务拒绝时不能留下半条记录", w4,
      "「校验没过」和「什么都没写」是两件事 —— 只验前者会漏掉写了一半的情况")

# ── W5 必填列对不上要**当场炸**,不是静默丢 ────────────────────
w5 = []
try:
    server._insert("appointment", {"id": "X1", "customer_id": "C10000"},
                   required=["id", "customer_id", "并不存在的列"])
    w5.append("必填列不存在却没报错 —— 静默丢字段就是这么来的")
except RuntimeError:
    pass
check("W5", "必填列和表对不上必须当场抛,不许静默忽略", w5,
      "把崩溃换成静默丢数据是更坏的交易:崩溃当天就发现,丢数据几个月后才发现")

shutil.rmtree(tmpdir, ignore_errors=True)
print("\n" + "=" * 92)
if bad:
    print(f"❌ {len(bad)} 条没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    sys.exit(1)
print("✅ 五条全部守住 —— 写进去的读得回来,拒绝的没留痕,对不上的当场炸")
