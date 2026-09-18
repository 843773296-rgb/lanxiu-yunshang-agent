#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**演示数据的命名规范** —— 以及一个独立实现的校验器。

## 起因

演示库里客户「蔡青梧」名下挂着四条方案,叫「**林女士**婚服方案」「**陈小姐**日常款」。
造数据时随手起的名,平时看不出来 —— 直到做「方案 = 一件事」这个功能:

**整个功能的要害就是「确认说的是哪一条方案」,而人名是顾问最自然的指代方式。**
演示时说「林女士那套」,助手会指向一个**根本不叫林女士**的客户的方案。

> 一个名字对不上主体的演示数据,和一个正确的演示数据,**在任何一张表上都长得一样**。
> 它只在演示的那一刻当众出错。

## 规范(业务 2026-09-18 定的)

**方案名不以人名命名,只以「定制款 + 工艺 + 定制时间」命名。**

    {形制名}·{工艺名[+工艺名…]}·{YYYY-MM}

    明制立领长衫·妆花+苏绣·2026-08
    宋制褙子·平绣·2026-08

三段各自的理由:
- **定制款**(形制):这是客户实际在挑的东西,也是顾问口头指代时最常说的
- **工艺**:同一形制下客户常并行两套只差工艺的方案,不带工艺就分不开
- **定制时间**:同款同工艺的复购,只有时间能分开

**为什么不许带人名**:方案挂在客户下面,人名是**冗余且会打架**的信息 ——
冗余的那份一旦和主体不一致,没有任何东西会报错。

⚠️ **分隔符 `·` 和主数据撞了**:工艺表里有 6 个名字**自带「 · 」**
(如「云锦 · 库缎」「电力纺 · 8 姆米」)。形制名里一旦出现 `·`,第一段就会切错;
工艺名里出现 `+`,工艺段就会拆错。

原来这里写的是「现在 0 个形制名带它 —— 这是事实,不是保证」。
**一句写在注释里的「现在没有」,失效的时候不会有任何提示** ——
失效的表现是方案名被切错,校验器报一个看起来莫名其妙的「定制款对不上」,
后人得倒查半天才知道是分隔符撞了。所以它现在是一条**前置检查**:
所有形制名不许含 `·`,被方案引用到的工艺名不许含 `·` 或 `+`,
**在主数据被加进来的那一刻就红**。(这条是方案那条线的会话提的。)

## 为什么校验器在这里,而生成在 `backend/seed.py`

**故意不让 seed 引用这个模块。**

如果 seed 调本模块拼名字、本模块再校验它拼的名字,那期望值和被测值算自同一处 ——
这个项目管它叫**同源谬误**:那样的检查只抓得到数据漂移,抓不到实现错误,
因为实现错了期望值会跟着一起错。

现在两边是独立的:seed 手里有中文名字面量(`xz="明制立领长衫"`),
本模块从库里的**编码**反查名字。**两条路走到同一个答案才算对。**

## 用法

    python3 fakedata/naming.py          # 校验,进 check.sh
"""
import os
import re
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "backend", "lanxiu.db")

称谓 = re.compile(r"(女士|小姐|先生|太太|夫人|同学|老师)")

# 一条方案名长什么样:三段,中间用 · 隔开,最后一段是年月
方案名式样 = re.compile(r"^(.+?)·(.+?)·(\d{4}-\d{2})$")


def 人名表(c):
    """库里所有真人的名字。**三张表都要**,漏一张就等于给那一类人开了后门。"""
    名 = set()
    for 表 in ("customer", "staff", "wearer", "artisan"):
        try:
            for (n,) in c.execute(f"SELECT name FROM {表} WHERE name IS NOT NULL"):
                if n and len(n) >= 2:
                    名.add(n)
        except sqlite3.OperationalError:
            pass          # 表不存在就跳过,但**不静默当成通过** —— 见下面的样本量下限
    return 名


分隔 = "·"
连接 = "+"


def 查分隔符(c):
    """**会进方案名的主数据,名字里不许含分隔符。** 返回 [问题…]。

    形制:全部形制名都可能被选进方案,所以全查。
    工艺:只查被方案引用到的 —— 工艺表里有 6 个面料类名字自带「 · 」,
    它们不进方案名,拦它们是误报(**误拦会让人把整条检查关掉**)。
    """
    坏 = []
    for code, nm in c.execute("SELECT code, name FROM xingzhi WHERE name IS NOT NULL"):
        if 分隔 in nm:
            坏.append(f"分隔符撞车:形制 {code}「{nm}」含「{分隔}」—— 会让方案名第一段切错。"
                      f"改主数据,或者换一个不会撞的分隔符")
    用到 = set()
    for (kf,) in c.execute("SELECT kf FROM scheme WHERE kf IS NOT NULL"):
        用到 |= {x.strip() for x in kf.split(",") if x.strip()}
    for code in sorted(用到):
        r = c.execute("SELECT name FROM craft WHERE code=?", (code,)).fetchone()
        if r and (分隔 in r[0] or 连接 in r[0]):
            坏.append(f"分隔符撞车:工艺 {code}「{r[0]}」含「{分隔}」或「{连接}」—— "
                      f"会让方案名的工艺段拆错")
    return 坏


def 查方案(c):
    """校验全部方案名。返回 (查了几条, [问题…])。"""
    坏 = 查分隔符(c)
    行 = c.execute("SELECT id,name,xz,kf,created,customer_id FROM scheme").fetchall()
    名单 = 人名表(c)

    for sid, nm, xz, kf, created, cid in 行:
        nm = nm or ""

        # ⓪ **名字和「按编码推出来的标准名」一字不差,就不用再查人名。**
        #    标准名只由形制编码、工艺编码、建单年月决定 —— 里面没有地方塞进一个人名,
        #    撞上的只能是主数据**自己的**名字。实测撞过一次:苏州工坊有位师傅登记名叫
        #    「镶三滚」(按手艺起的外号),而工艺「三镶三滚」正好含着这三个字 ——
        #    子串一比,四条规规矩矩的方案全被判成「带了真人姓名」。
        #    **字符串相似 ≠ 同一个东西**;标准名对得上,说明每个字都有编码撑着。
        _xzn = c.execute("SELECT name FROM xingzhi WHERE code=?", (xz,)).fetchone()
        _kfn = [c.execute("SELECT name FROM craft WHERE code=?", (k.strip(),)).fetchone()
                for k in (kf or "").split(",") if k.strip()]
        if _xzn and _kfn and all(_kfn) and \
                nm == f"{_xzn[0]}{分隔}{连接.join(x[0] for x in _kfn)}{分隔}{(created or '')[:7]}":
            continue

        # ① 不许带称谓
        m = 称谓.search(nm)
        if m:
            坏.append(f"{sid}「{nm}」带称谓「{m.group(1)}」—— 方案名不以人名命名")
            continue

        # ② 不许带任何真人的名字
        撞 = [n for n in 名单 if n in nm]
        if 撞:
            坏.append(f"{sid}「{nm}」里出现了真人姓名 {撞} —— 方案名不以人名命名")
            continue

        # ③ 形状:定制款·工艺·年月
        g = 方案名式样.match(nm)
        if not g:
            坏.append(f"{sid}「{nm}」不符合「定制款·工艺·YYYY-MM」")
            continue
        款, 艺, 月 = g.groups()

        # ④ 定制款要真的是这条方案的形制。**从编码反查,不信名字本身**
        r = c.execute("SELECT name FROM xingzhi WHERE code=?", (xz,)).fetchone()
        if not r:
            坏.append(f"{sid} 的形制编码 {xz} 在形制表里查不到")
            continue
        if 款 != r[0]:
            坏.append(f"{sid}「{nm}」的定制款是「{款}」,而它的形制是「{r[0]}」")
            continue

        # ⑤ 工艺要真的是这条方案的工艺,顺序也要一致
        码 = [x.strip() for x in (kf or "").split(",") if x.strip()]
        真艺 = []
        缺 = False
        for k in 码:
            rr = c.execute("SELECT name FROM craft WHERE code=?", (k,)).fetchone()
            if not rr:
                坏.append(f"{sid} 的工艺编码 {k} 在工艺表里查不到")
                缺 = True
                break
            真艺.append(rr[0])
        if 缺:
            continue
        if 艺 != "+".join(真艺):
            坏.append(f"{sid}「{nm}」的工艺段是「{艺}」,而它的工艺是「{'+'.join(真艺)}」")
            continue

        # ⑥ 年月要和建单时间一致
        if 月 != (created or "")[:7]:
            坏.append(f"{sid}「{nm}」的年月是 {月},而它建于 {created}")
            continue

    # ⑦ 同一客户名下方案名不许重名 —— **消歧是这套规范的全部目的**,
    #    两条同名就又分不开了(同形制同工艺同月的两条,只能靠时间段区分,而时间段也撞了)
    见 = {}
    for sid, nm, _xz, _kf, _cr, cid in 行:
        if nm:
            见.setdefault((cid, nm), []).append(sid)
    for (cid, nm), ids in 见.items():
        if len(ids) > 1:
            坏.append(f"客户 {cid} 名下方案重名「{nm}」:{ids} —— 口头说这个名字时指不出是哪一条")

    return len(行), 坏


def main():
    if not os.path.exists(DB):
        print(f"❌ 找不到库 {DB}")
        return 1
    c = sqlite3.connect(DB)
    try:
        n, 坏 = 查方案(c)
        人 = len(人名表(c))
    finally:
        c.close()

    # **样本量下限。** 空集合上所有性质都成立 —— 方案表一空,这条检查全绿,
    # 而「一条都没验」和「验过了没问题」在输出上长得一模一样。
    # 人名表同理:三张表都查不到时,「不许带人名」那两条等于没跑。
    if n < 4:
        print(f"❌ 只查到 {n} 条方案(下限 4)—— 这是**没扫到东西**,不是都通过")
        return 1
    if 人 < 50:
        print(f"❌ 人名表只有 {人} 个名字(下限 50)—— 查不到人名就拦不住带人名的方案名")
        return 1

    if 坏:
        for b in 坏:
            print(f"❌ 方案命名:{b}")
        print(f"   共 {len(坏)}/{n} 条不合规范。规范:定制款·工艺·YYYY-MM,不带人名。"
              f"见 fakedata/naming.py 开头。")
        return 1

    print(f"✅ {n} 条方案命名合规(定制款·工艺·YYYY-MM,不带人名;比对了 {人} 个真人姓名)")
    return 0


# 咬合:每条攻击对应**一条具体规则**,预期红写成那条规则**独有**的措辞。
# 原来右边一律写「方案命名」—— 那样任何一条规则红了,所有规格都算通过,
# **咬合就测不出是哪条规则在起作用**。可执行版本在 tools/bite_specs.json。
咬合 = [
    ('把一条方案名改成带称谓的(「林女士婚服方案」)', '带称谓'),
    ('方案名里嵌一个真实客户的名字(不带称谓,只能靠人名表拦)', '出现了真人姓名'),
    ('定制款那段换成另一个形制(形状仍然合规,内容对不上)', '的定制款是'),
    ('年月段改成和建单时间对不上的月份', '而它建于'),
    ('把 scheme 表清空 —— **空表上所有性质都成立**', '没扫到东西'),
    ('给一个被方案用到的形制名里加上分隔符「·」', '分隔符撞车'),
    ('同一客户名下两条方案改成同名', '重名'),
]

if __name__ == "__main__":
    sys.exit(main())
