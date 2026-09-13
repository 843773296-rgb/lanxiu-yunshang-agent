# -*- coding: utf-8 -*-
"""角色与登录身份的检查 —— **每个 agent 角色都得有对应的登录身份。**

## 原来的错配

    能登录的:店长 / 顾问 / 总部运营 / 财务    (15 人)
    agent 角色:all / kb / workshop / task

**`workshop`(工坊排产)没有对应的登录身份** —— 21 位师傅在 `artisan` 表里,
工单也按 `W0101` 挂到人了,11 条规矩也写好了,**唯独他们登录不了**。
于是那个角色只能被总部运营或店长冒着用,而师傅看不到自己的活。

反过来:**`财务` 能登录但没有 agent 工具和规矩** —— 有身份没能力。

> **一个没有登录身份的 agent 角色,和一个没有工具的登录身份,是同一个病的两面:
> 角色和能力没有对齐。**

## 这套检查验的是对齐,不是数量

数量对不上不一定是错(`all` 是三摊合一,不对应单一岗位)。
验的是:**声称能服务某个岗位的角色,那个岗位的人得能进来。**
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import tasks as TK
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("角色与登录身份 · 检查")
    print("=" * 84)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row

    # ① 每位工匠都有登录身份,而且桥是**一对一**的。
    n1 = c.execute("SELECT COUNT(*) FROM artisan").fetchone()[0]
    无身份 = [r["no"] for r in c.execute(
        "SELECT no FROM artisan WHERE staff_no IS NULL OR staff_no NOT IN "
        "(SELECT no FROM staff WHERE role='工匠')")]
    ck("每位工匠都能登录", not 无身份, n1,
       f"没身份的 {无身份[:3]}" if 无身份 else
       "「工坊排产」这个 agent 角色原来没有对应的登录身份")

    重 = [r["staff_no"] for r in c.execute(
        "SELECT staff_no FROM artisan WHERE staff_no IS NOT NULL "
        "GROUP BY staff_no HAVING COUNT(*)>1")]
    ck("一个登录身份只对一位工匠", not 重, n1,
       f"一号多人 {重[:3]}" if 重 else "「一个人两套编号」那个 bug 就是桥没做成一对一")

    # ② **所有能登录的人都要有密码。**
    #    实测栽过一次:师傅并进 staff 之后,发凭据那段排在他们之前,
    #    于是 21 个人有工号有角色**却登录不了**,而 staff 表上看起来完全正常。
    n2 = c.execute("SELECT COUNT(*) FROM staff WHERE status='启用'").fetchone()[0]
    无密码 = [r["no"] for r in c.execute(
        "SELECT no FROM staff WHERE status='启用' AND (pwd_hash IS NULL OR login_name IS NULL)")]
    ck("启用的员工都能登录(有登录名和密码)", not 无密码, n2,
       f"登不进的 {无密码[:3]}" if 无密码 else
       "发凭据这类收尾动作要排在所有写 staff 之后")

    # ③ **工匠之间隔离** —— 工价和产能是敏感信息。
    #    拿两位不同工坊的师傅比,各自只看得到自己的。
    两 = [dict(r) for r in c.execute(
        "SELECT a.no,a.staff_no,s.name,a.workshop FROM artisan a "
        "JOIN staff s ON s.no=a.staff_no WHERE a.staff_no IS NOT NULL LIMIT 2")]
    n3 = len(两); 漏 = []
    for w in 两:
        me = dict(no=w["staff_no"], name=w["name"], role="工匠", shop=w["workshop"])
        where, args, _ = TK.visible_wo_scope(me)
        看到 = {r["artisan"] for r in c.execute(
            f"SELECT DISTINCT w.artisan FROM workorder w WHERE {where}", args)}
        if 看到 - {w["no"]}:
            漏.append((w["no"], sorted(看到 - {w["no"]})[:3]))
    ck("工匠只看得到自己的工单", not 漏, n3,
       f"看到别人的 {漏}" if 漏 else "**工价和产能是敏感信息** —— 和顾问之间隔离同理")

    # ④ 不该看工单的角色一条都看不到。
    n4 = 0; 破 = []
    for role in ("顾问", "店长", "财务"):
        n4 += 1
        where, args, _ = TK.visible_wo_scope(dict(no="x", name="x", role=role, shop="y"))
        k = c.execute(f"SELECT COUNT(*) FROM workorder w WHERE {where}", args).fetchone()[0]
        if k: 破.append((role, k))
    ck("门店和财务角色看不到工单", not 破, n4, f"看到了 {破}" if 破 else "")

    # ⑤ **每个 agent 角色的工具,都得有对应的登录身份能用。**
    #    这条防的正是原来那个错配:规矩写好了、工具挂上了,而**没人进得来**。
    sys.path.insert(0, os.path.dirname(HERE))
    import prompts
    岗位 = {r["role"] for r in c.execute(
        "SELECT DISTINCT role FROM staff WHERE status='启用'")}
    需要 = {"workshop": "工匠", "task": "店长", "kb": "顾问"}
    缺 = [(k, v) for k, v in 需要.items() if k in prompts.ROLES and v not in 岗位]
    ck("每个 agent 角色都有对应的登录身份", not 缺, len(需要),
       f"没人进得来的 {缺}" if 缺 else
       "**一个没有登录身份的 agent 角色,和一个没有工具的登录身份,是同一个病的两面**")

    # ⑦ **登录页要把每种角色都列出来,而且列的工号必须真的能登录。**
    #
    # 原来只列了店长和顾问两个 —— 而工匠和财务是后来补的,
    # **不列出来等于那两个角色不存在**:看的人会以为这个系统只有门店两种身份。
    #
    # 这条检查验两件事,第二件更要紧:
    #   · 每种在职角色在登录页上都出现了
    #   · **页面上写的工号真的登得进去**(算一遍 PBKDF2,不是看它写了没有)——
    #     一个写着假工号的演示清单,比不写更糟:照着它登不进去的人,
    #     第一反应是「这系统坏了」,而不是「这行字过期了」。
    import re as _re, hashlib as _hl
    lp = os.path.join(os.path.dirname(HERE), "agentsite", "web", "login.html")
    html = open(lp, encoding="utf-8").read() if os.path.exists(lp) else ""
    在职角色 = {r["role"] for r in c.execute(
        "SELECT DISTINCT role FROM staff WHERE status='启用'")}
    # ⚠️ **只在演示账号那一段里找,而且要求「角色名 + 工号」成对出现。**
    #
    # 第一版整页搜角色名 —— 咬合时把「工匠」那一行删掉,**检查还是绿的**,
    # 因为「工匠」这两个字在注释里也有。
    # 判据要贴着「什么才算对」:该算对的是
    # **「演示账号那一段里列了这个角色,并且给了工号」**,
    # 不是「这个字在页面上出现过」。
    m斑 = _re.search(r'class="demo"(.*?)</div>', html, _re.S)
    段 = m斑.group(1) if m斑 else ""
    # 取「标签后紧跟的中文角色名 + 工号」—— `\S+?` 会把 `<p>` 一起抓进来,
    # 于是键变成「<p>总部运营」,和库里的角色名永远对不上。
    成对 = dict(_re.findall(r">\s*([\u4e00-\u9fff]{2,4})\s*<code>(\d{8})</code>", 段))
    漏角色 = sorted(r for r in 在职角色 if r not in 成对)
    ck("登录页把每种在职角色连工号一起列出来", not 漏角色, len(在职角色),
       f"没列的 {漏角色} —— **不列出来等于那个角色不存在**" if 漏角色 else
       f"成对列出 {len(成对)} 个:{sorted(成对)}")

    列的工号 = list(成对.values())
    坏账号 = []
    PW = "lanxiu@2026"          # 演示口令,和 seed 里那个是同一个
    for no in 列的工号:
        r = c.execute("SELECT no,pwd_algo,pwd_salt,pwd_hash,status FROM staff WHERE no=?",
                      (no,)).fetchone()
        if not r or r["status"] != "启用":
            坏账号.append((no, "查无此人或已停用")); continue
        try:
            it = int(str(r["pwd_algo"]).split("$")[1])
            h = _hl.pbkdf2_hmac("sha256", PW.encode(),
                                bytes.fromhex(r["pwd_salt"]), it).hex()
        except Exception as e:
            坏账号.append((no, f"算不出:{type(e).__name__}")); continue
        if h != r["pwd_hash"]:
            坏账号.append((no, "密码对不上"))
    ck("登录页写的工号真的登得进去", not 坏账号, len(列的工号),
       f"登不进的 {坏账号}" if 坏账号 else
       "**算了一遍 PBKDF2,不是看它写了没有** —— 写着假工号比不写更糟")

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 角色与登录身份 8 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
