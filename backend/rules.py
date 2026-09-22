#!/usr/bin/env python3
"""写入校验规则 —— 逐条来自澜绣云裳 PRD。

后台 PRD 6.2:客户去重与合并、时间校验、附件限制
前端 PRD 11.6:预约提前量、门店核验时限
"""
import re
from datetime import datetime, timedelta

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把手机号的格式判定放宽成「有数字就行」(不合法的号也收得进来)',
     '项与预期不符'),
]

def norm_phone(p):
    """标准化手机号:去空格、连字符、+86 前缀"""
    p=re.sub(r"[\s\-()]","",p or "")
    if p.startswith("+86"): p=p[3:]
    if p.startswith("86") and len(p)==13: p=p[2:]
    return p

def sim_name(a,b):
    """姓名相似:完全相同,或姓氏相同且长度相同"""
    a,b=(a or "").strip(),(b or "").strip()
    if not a or not b: return False
    return a==b or (a[0]==b[0] and len(a)==len(b))

def validate_customer(d, existing, actor_role="顾问"):
    """existing: 现有客户列表(含 phone/name/shop)。返回 (ok, code, reason, suspects)"""
    name=(d.get("name") or "").strip()
    phone=norm_phone(d.get("phone"))
    shop=d.get("shop") or ""
    if not name: return False,"NEED_NAME","客户姓名必填",[]
    if not re.fullmatch(r"1[3-9]\d{9}", phone):
        return False,"BAD_PHONE",f"手机号「{d.get('phone')}」不是合法的 11 位手机号",[]
    # 规则一:标准化手机号完全相同 → 直接阻止新建
    same=[c for c in existing if norm_phone(c.get("phone"))==phone]
    if same:
        return False,"DUP_PHONE",\
          f"手机号与客户 {same[0]['id']}({same[0]['name']})完全相同,按 PRD 6.2 阻止新建",same
    # 规则二:姓名相似 + 尾号相同 → 转店长确认,不直接建。**不限门店**(业务 2026-09-22 确认,附录 A-65):
    # 要防的正是「同一个人在两家店各建一次档」,只查同店等于没防。「同姓同字数」不收窄 ——
    # 有 4 位尾号兜着,实测误报极少(同店撞上的概率约 0.04%)。
    sus=[c for c in existing if sim_name(c.get("name"),name)
         and norm_phone(c.get("phone"))[-4:]==phone[-4:]]
    if sus:
        跨店 = "" if sus[0].get("shop")==shop else f"(在 {sus[0].get('shop') or '别的门店'})"
        return False,"NEED_REVIEW",\
          f"与客户 {sus[0]['id']}({sus[0]['name']}){跨店}姓名相似、尾号相同,须由店长确认后建档",sus
    return True,"OK","",[]

# 前端 PRD 11.6:到店至少提前 2 小时,上门量体至少提前 24 小时
LEAD={"到店量体":2,"到店试衣":2,"上门沟通":24,"电话回电":0}

def validate_appointment(d, now=None, actor_role="顾问"):
    now=now or datetime.now()
    way=d.get("way") or "到店量体"
    try:
        st=datetime.fromisoformat((d.get("start") or "").replace("T"," "))
        et=datetime.fromisoformat((d.get("end") or "").replace("T"," "))
    except Exception:
        return False,"BAD_TIME","预约起止时间格式不正确"
    # 后台 PRD 6.2:结束时间不得早于开始时间
    if et<=st: return False,"END_BEFORE_START","预约结束时间不得早于或等于开始时间"
    lead=LEAD.get(way,2)
    if st<now:
        # 补录:仅店长及以上可补录过去 7 天内
        if actor_role not in ("店长","总部运营"):
            return False,"NO_BACKFILL",f"预约时间早于当前,仅店长及以上角色可补录(当前角色:{actor_role})"
        if (now-st)>timedelta(days=7):
            return False,"BACKFILL_LIMIT","仅可补录过去 7 天内的记录"
        return True,"BACKFILL","按补录处理,将记录操作人与原因"
    if lead and st<now+timedelta(hours=lead):
        return False,"LEAD_TIME",\
          f"「{way}」须至少提前 {lead} 小时预约,当前仅提前 {int((st-now).total_seconds()//60)} 分钟"
    return True,"OK",""

# 后台 PRD 6.2 导入规则:
#   文件不超过 10MB、单次不超过 2000 行;结构错误整批拒绝;
#   行级错误允许部分成功并生成错误报告;重复记录跳过,疑似重复进入人工确认;
#   任务异步执行并使用批次号保证幂等
IMPORT_COLS=["姓名","手机号","归属店铺","销售顾问","生日","地址"]
MAX_ROWS=2000

def validate_import_header(cols):
    """结构校验:表头缺列即整批拒绝"""
    missing=[c for c in IMPORT_COLS[:4] if c not in cols]
    if missing: return False,"BAD_HEADER",f"表头缺少必需列:{'、'.join(missing)};结构错误整批拒绝"
    extra=[c for c in cols if c not in IMPORT_COLS]
    if extra: return False,"BAD_HEADER",f"表头包含未知列:{'、'.join(extra)};结构错误整批拒绝"
    return True,"OK",""

def validate_import_rows(rows_, existing):
    """行级校验:逐行判定,允许部分成功。返回 (ok行, 跳过行, 错误行, 待确认行)"""
    if len(rows_)>MAX_ROWS:
        return None,None,None,None,("TOO_MANY_ROWS",f"单次导入不超过 {MAX_ROWS} 行,当前 {len(rows_)} 行;整批拒绝")
    ok,skip,err,review=[],[],[],[]
    seen={norm_phone(c.get("phone")) for c in existing}
    batch_seen=set()
    for i,r in enumerate(rows_,2):        # 第 1 行是表头
        ph=norm_phone(r.get("手机号"))
        d=dict(name=(r.get("姓名") or "").strip(),phone=ph,
               shop=r.get("归属店铺") or "",advisor=r.get("销售顾问") or "")
        if ph and (ph in seen or ph in batch_seen):
            skip.append((i,d["name"],"手机号已存在,按规则跳过")); continue
        good,code,why,sus=validate_customer(d,existing)
        if code=="NEED_REVIEW": review.append((i,d["name"],why)); continue
        if not good: err.append((i,d["name"],f"[{code}] {why}")); continue
        batch_seen.add(ph); ok.append((i,d))
    return ok,skip,err,review,None

ATTACH_OK={"jpg","jpeg","png","pdf","doc","docx","xls","xlsx"}
def validate_attachments(files):
    """后台 PRD 6.2:格式白名单、单文件 ≤20MB、每条 ≤9 个、总量 ≤100MB"""
    if len(files)>9: return False,"TOO_MANY",f"每条记录最多 9 个附件,当前 {len(files)} 个"
    total=0
    for f in files:
        ext=(f.get("name","").rsplit(".",1)[-1] or "").lower()
        if ext not in ATTACH_OK:
            return False,"BAD_TYPE",f"「{f.get('name')}」类型不在白名单({'/'.join(sorted(ATTACH_OK))})"
        sz=f.get("size",0)
        if sz>20*1024*1024: return False,"TOO_BIG",f"「{f.get('name')}」超过单文件 20MB 限制"
        total+=sz
    if total>100*1024*1024: return False,"TOTAL_BIG","附件总容量超过 100MB"
    return True,"OK",""

if __name__=="__main__":
    ex=[dict(id="C10000",name="蔡青梧",phone="13600000511",shop="SH002 徐汇店")]
    cases=[
      ({"name":"","phone":"13800000000","shop":"SH001"},"空姓名"),
      ({"name":"张三","phone":"1380000","shop":"SH001"},"手机号不合法"),
      ({"name":"张三","phone":"136 0000 0511","shop":"SH001"},"手机号标准化后重复"),
      ({"name":"蔡青云","phone":"13911110511","shop":"SH002 徐汇店"},"姓名相似+尾号+门店相同"),
      ({"name":"李四","phone":"13812345678","shop":"SH001"},"正常"),
      # 业务 2026-09-22(附录 A-65):要防的是同一个人在两家店各建一次档 —— 跨店也得转店长
      ({"name":"蔡青云","phone":"13911110511","shop":"SH001 静安店"},"姓名相似+尾号相同,门店不同"),
    ]
    EXP_C=["NEED_NAME","BAD_PHONE","DUP_PHONE","NEED_REVIEW","OK","NEED_REVIEW"]
    bad=0
    print("客户录入校验\n"+"="*70)
    for (d,t),exp in zip(cases,EXP_C):
        ok,code,why,_=validate_customer(d,ex)
        hit=code==exp
        if not hit: bad+=1
        print(f"{'✅' if hit else '❗'} [{code:12s}] {t}" + ("" if hit else f"   期望 {exp}"))
    from datetime import datetime as DT
    now=DT(2026,8,31,10,0)
    ac=[({"way":"到店量体","start":"2026-08-31 11:00","end":"2026-08-31 12:00"},"到店只提前1小时"),
        ({"way":"到店量体","start":"2026-08-31 13:00","end":"2026-08-31 14:00"},"到店提前3小时"),
        ({"way":"上门沟通","start":"2026-09-01 09:00","end":"2026-09-01 10:00"},"上门只提前23小时"),
        ({"way":"到店量体","start":"2026-08-31 15:00","end":"2026-08-31 14:00"},"结束早于开始"),
        ({"way":"到店量体","start":"2026-08-30 10:00","end":"2026-08-30 11:00"},"补录(顾问)")]
    EXP_A=["LEAD_TIME","OK","LEAD_TIME","END_BEFORE_START","NO_BACKFILL"]
    print("\n预约校验\n"+"="*70)
    for (d,t),exp in zip(ac,EXP_A):
        ok,code,why=validate_appointment(d,now)
        hit=code==exp
        if not hit: bad+=1
        print(f"{'✅' if hit else '❗'} [{code:16s}] {t}" + ("" if hit else f"   期望 {exp}"))
    print("\n导入校验\n"+"="*70)
    hdr_cases=[(["姓名","手机号","归属店铺","销售顾问"],"OK"),
               (["姓名","手机号"],"BAD_HEADER"),
               (["姓名","手机号","归属店铺","销售顾问","年龄"],"BAD_HEADER")]
    for cols,exp in hdr_cases:
        ok,code,why=validate_import_header(cols)
        hit=code==exp
        if not hit: bad+=1
        print(f"{'✅' if hit else '❗'} [{code:12s}] 表头 {cols}")
    ex2=[dict(id="C1",name="蔡青梧",phone="13600000511",shop="SH002 徐汇店")]
    data=[{"姓名":"李四","手机号":"13812345678","归属店铺":"SH001","销售顾问":"A01"},
          {"姓名":"王五","手机号":"136 0000 0511","归属店铺":"SH002","销售顾问":"A02"},
          {"姓名":"","手机号":"13900000001","归属店铺":"SH001","销售顾问":"A01"},
          {"姓名":"蔡青云","手机号":"13911110511","归属店铺":"SH002 徐汇店","销售顾问":"A02"},
          {"姓名":"李四","手机号":"13812345678","归属店铺":"SH001","销售顾问":"A01"}]
    o,sk,er,rv,fatal=validate_import_rows(data,ex2)
    res=(len(o),len(sk),len(er),len(rv))
    hit = res==(1,2,1,1)
    if not hit: bad+=1
    print(f"{'✅' if hit else '❗'} 行级校验 5 行 → 成功{len(o)} 跳过{len(sk)} 错误{len(er)} 待确认{len(rv)}"
          + ("" if hit else "   期望 1/2/1/1"))
    print("="*70)
    print(f"{'✅ 全部符合预期' if not bad else f'❌ {bad} 项与预期不符'}")
    import sys; sys.exit(1 if bad else 0)
