#!/usr/bin/env python3
"""业务写入规则 · 触发覆盖检查。

`check_write` 是智能体唯一能问到「这件事业务允不允许做」的通道。
它盖不到的规则,对智能体就**等于不存在** —— 而智能体不会说"我不知道",
它会凭表结构推断,然后给出相反的结论(实测:模型答「可以的,系统设计就是这么打的」,
还编了一套架构理由,而 rules 返回的是「客户姓名必填」)。

所以这里逐个码构造最小请求,确认 **每一条业务规则都真的能被触发到**。
和 E1「每条规则至少一个用例」是同一条:**没有用例的规则可以是错的,
而且永远不会被发现**。

## 为什么期望值只写「码」不写「文案」

`reason` 里带客户 id 和人名,同一条规则每次文案都不一样。
按 `code` 归类,拿字面量归类迟早出事 —— 这条是另一个会话踩出来的。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api, rules

# 每条:错误码 → (动作, 最小请求, 这条规则说的是什么)
# **最小的判据是「同一个错误码」,不是「还是失败」** ——
# 删掉 name 之后 DUP_PHONE 会变成 NEED_NAME,那是另一条规则,
# 拿它当用例问的就不是原来那件事了。
FUTURE = "2027-06-01 10:00"
FUT_END = "2027-06-01 11:00"
PAST = "2026-01-05 10:00"
PAST_END = "2026-01-05 11:00"

CASES = [
 ("NEED_NAME", "建档", {"phone": "13900001111"},
  "客户姓名必填 —— 而 customer.name 在库里可空,**这就是差集本身**"),
 ("BAD_PHONE", "建档", {"name": "张三", "phone": "12345"},
  "手机号必须是合法 11 位"),
 ("DUP_PHONE", "建档", None,   # 现拿库里一个真手机号
  "手机号完全相同 → 直接阻止新建(PRD 6.2)"),
 ("OK", "建档", {"name": "全新的人", "phone": "13800001234", "shop": "SH001 静安旗舰店"},
  "都合规 —— **正例也要有**,否则只验得出「什么都拒」"),
 ("NEED_REVIEW", "建档", None,   # 现拿库里一个人,凑出「姓氏同 + 字数同 + 尾号同 + 同门店」
  "姓名相似 + 尾号与门店相同 → **转店长确认**(不是不能建)。"
  "这条最容易被漏掉,因为它的正确动作既不是「行」也不是「不行」"),
 ("BAD_TIME", "预约", {"start": "不是时间", "end": FUT_END},
  "起止时间格式不正确"),
 ("END_BEFORE_START", "预约", {"start": FUT_END, "end": FUTURE},
  "结束时间不得早于或等于开始时间"),
 ("LEAD_TIME", "预约", {"start": "@SOON", "end": "@SOON_END", "way": "上门沟通"},
  "上门沟通至少提前 24 小时(到店 2 小时)"),
 ("NO_BACKFILL", "预约", {"start": PAST, "end": PAST_END, "way": "到店量体", "role": "顾问"},
  "早于当前时间的补录,**顾问不行**"),
 ("BACKFILL", "预约", {"start": "@RECENT", "end": "@RECENT_END", "way": "到店量体", "role": "店长"},
  "同一个请求换成店长 → 允许补录。**别把「你不行」说成「这事不能做」**"),
 ("BACKFILL_LIMIT", "预约", {"start": PAST, "end": PAST_END, "way": "到店量体", "role": "店长"},
  "补录也有窗口 —— 超过 7 天连店长也不行"),
]

import datetime as dt
now = dt.datetime.now()
SUB = {"@SOON": (now + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
       "@SOON_END": (now + dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
       "@RECENT": (now - dt.timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
       "@RECENT_END": (now - dt.timedelta(days=2) + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")}

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把重号判定的错误码改掉(闸还在,报出来的不是那道闸)',
     'DUP_PHONE'),
]

def fill(d):
    return {k: SUB.get(v, v) if isinstance(v, str) else v for k, v in (d or {}).items()}

bad, hit = [], set()
print(f"业务写入规则 · {len(CASES)} 条触发用例")
print("=" * 96)
for want, action, fields, desc in CASES:
    f = fill(fields)
    if want == "NEED_REVIEW":
        # 造一个「像但不是同一人」:姓氏相同、字数相同、手机尾号相同、同门店,
        # 但手机号本身不同(否则会先撞 DUP_PHONE —— **那是另一条规则**)
        base = api._rows("SELECT id,name,phone,shop FROM customer "
                         "WHERE phone IS NOT NULL AND length(phone)=11 "
                         "AND shop IS NOT NULL AND length(name)>=2 LIMIT 1")
        if not base: bad.append(("NEED_REVIEW", "库里没有可用样本,夹具不成立")); continue
        b = base[0]
        # 换个不同的前 7 位,保留后 4 位
        head = "1390000" if not b["phone"].startswith("1390000") else "1370000"
        f = {"name": b["name"][0] + "云" * (len(b["name"]) - 1),
             "phone": head + b["phone"][-4:], "shop": b["shop"]}
    if want == "DUP_PHONE":
        ph = api._rows("SELECT phone FROM customer WHERE phone IS NOT NULL "
                       "AND length(phone)=11 LIMIT 1")
        if not ph: bad.append(("DUP_PHONE", "库里没有可用手机号,夹具不成立")); continue
        f = {"name": "新来的", "phone": ph[0]["phone"]}
    r = api.check_write(action, f)
    got = r.get("编码")
    ok = got == want
    hit.add(got)
    print(f"  {'✅' if ok else '❌'} {want:16s} {action}  期望 {want} / 实得 {got or r.get('error','?')}")
    print(f"        {desc}")
    if not ok: bad.append((want, f"实得 {got}"))

# 覆盖:两个校验器里的码,check_write 得都能摸到
DECL = set()
import re as _re
src = open(os.path.join(HERE, "rules.py"), encoding="utf-8").read()
for fn in ("validate_customer", "validate_appointment"):
    m = _re.search(rf"^def {fn}\(", src, _re.M)
    nx = _re.search(r"^def ", src[m.end():], _re.M)
    DECL |= set(_re.findall(r'"([A-Z_]{4,})"', src[m.start(): m.end() + (nx.start() if nx else 0)]))
missing = sorted(DECL - hit)

print("=" * 96)
if missing:
    print(f"❌ 这几个码 check_write 触发不到:{missing}")
    print("   **触发不到的规则,对智能体等于不存在** —— 而它不会说不知道,只会凭表结构猜。")
    bad.append(("覆盖", str(missing)))
if bad:
    print(f"\n❌ {len(bad)} 条没过:")
    for w, why in bad: print(f"   · {w}:{why}")
    sys.exit(1)
print(f"✅ {len(CASES)} 条全部触发到预期的码;"
      f"两个校验器声明的 {len(DECL)} 个码全部可达")
