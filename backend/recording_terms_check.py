#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录音同意的检查 —— 业务 D9:**录音同意不能撤回**,以及由它推出来的两件事。

  (a) 不能撤回,就**不许在任何界面显示撤回入口** —— 否则界面在骗人
  (b) **不进 consent 表**(那张表是可撤回的授权),单独记「条款版本 + 接受时间」,只追加
  (c) 每一通录音都记着同意依据:客户接受过含录音条款的版本,还是按规定默认同意 ——
      两者都合规,但混成一个「已同意」,哪天要拿证据时分不开

口径在 `knowledge/recording_terms.py`,存取在 `backend/terms_store.py`。
"""
import glob, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import recording_terms as K

G, R, D = "\033[32m", "\033[31m", "\033[0m"
DB = os.path.join(HERE, "lanxiu.db")

咬合 = [
    ("在客户页「通话录音」那一栏加一个「撤回录音同意」按钮", "任何页面都没有「撤回录音同意」的入口"),
    ("版本按字符串比(`a >= b` 改成 `str(版本) >= 录音条款起始版本`)", "版本按数字比:v2.10 比 v2.3 新"),
    ("条款接受表加一列 revoked_at", "条款接受表只追加,没有撤回类的列"),
]

坏 = 0


def ck(名, ok, n, 说明=""):
    global 坏
    if n == 0:
        print(f"  {R}❌{D} {名} —— **没扫到东西**,不是通过"); 坏 += 1; return
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}(验了 {n} 个){'' if ok else '  ' + 说明}")
    坏 += 0 if ok else 1


# 「撤回」这件事的几种说法。⚠️ 只在**和录音同处一行 / 一个元素**时才算 —— 页面上别的撤回(撤回审批)是正当的
撤回词 = r"撤回|撤销同意|取消同意|收回同意|withdraw|revoke"


def 页面们():
    出 = []
    for pat in ("backend/web/*.html", "agentsite/web/*.html", "agentsite/web/**/*.html",
                "管理后台/**/*.html", "管理后台/**/*.tsx", "管理后台/**/*.vue"):
        出 += glob.glob(os.path.join(ROOT, pat), recursive=True)
    return sorted({p for p in 出 if "node_modules" not in p})


def main():
    print("\n\033[1m▸ 口径\033[0m")
    ck("接受过含录音条款的版本 → 条款接受", K.依据(("v2.3", "2026-01-02"))[0] == "条款接受", 1)
    ck("只接受过旧版 → 默认同意(不是「不同意」)", K.依据(("v2.1", "2025-01-02"))[0] == "默认同意", 1)
    ck("没注册账户 → 默认同意", K.依据(None)[0] == "默认同意", 1)
    ck("版本按数字比:v2.10 比 v2.3 新", K.含录音条款吗("v2.10") and not K.含录音条款吗("v2.2"), 2)
    ck("版本认不出来 → 不算接受过(说不清就不算)", not K.含录音条款吗("新版"), 1)

    print("\n\033[1m▸ (a) 界面上没有撤回入口\033[0m")
    页 = 页面们()
    违 = []
    for p in 页:
        for i, 行 in enumerate(open(p, encoding="utf-8", errors="ignore").read().splitlines(), 1):
            if "录音" in 行 and re.search(撤回词, 行, re.I):
                违.append(f"{os.path.relpath(p, ROOT)}:{i}")
    ck("任何页面都没有「撤回录音同意」的入口", not 违, len(页), f"共 {len(违)} 处:{违[:3]}")
    路由 = re.findall(r'p\s*==\s*"(/api/[^"]+)"|startswith\("(/api/[^"]+)"\)',
                     open(os.path.join(HERE, "server.py"), encoding="utf-8").read())
    路由 = [a or b for a, b in 路由]
    违 = [x for x in 路由 if re.search(r"(call|record|audio|录音).*(revoke|withdraw|撤回)|(revoke|withdraw|撤回).*(call|record|audio|录音)", x, re.I)]
    ck("后台接口里没有撤回录音同意的路由", not 违, len(路由), str(违))

    print("\n\033[1m▸ (b) 不进 consent 表,只追加\033[0m")
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    域 = [r[0] for r in c.execute("SELECT DISTINCT scope FROM consent")]
    ck("consent 表里没有录音这一档(那张表是可撤回的授权)", not any("录音" in (x or "") for x in 域), len(域), str(域))
    # 库里的表 + 建表语句两头都看:只看库,改了建表语句要等重建才看得见(咬合也就咬不住)
    import terms_store
    列 = [r[1] for r in c.execute("PRAGMA table_info(terms_accept)")] + \
         re.findall(r"^\s*(\w+)\s+TEXT", terms_store.DDL, re.M)
    ck("条款接受表只追加,没有撤回类的列", 列 and not any(re.search(r"revok|withdraw|cancel|撤", x) for x in 列),
       len(列), str(列))
    行 = c.execute("SELECT version FROM terms_accept").fetchall()
    认不出 = [v for (v,) in 行 if K._版本号(v) is None]
    ck("条款接受记录的版本都认得出", not 认不出, len(行), str(认不出[:3]))

    print("\n\033[1m▸ (c) 每一通录音都记着同意依据\033[0m")
    通 = c.execute("SELECT id, consent_basis FROM call_audio").fetchall()
    if len(通) < 10:
        ck(f"录音样本够(至少 10 通,现在 {len(通)})", False, 0); c.close(); return 1
    缺 = [i for i, b in 通 if not b]
    野 = [i for i, b in 通 if b and not b.startswith(("条款接受:", "默认同意:"))]
    ck("每一通录音都有同意依据", not 缺, len(通), f"共 {len(缺)} 通没有:{缺[:3]}")
    ck("依据只有两种:条款接受 / 默认同意(没有「不同意」这一档)", not 野, len(通), f"{野[:3]}")
    c.close()

    print()
    if 坏:
        print(f"{R}❌ 录音同意 {坏} 条不过{D}"); return 1
    print(f"{G}✅ 录音同意全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
