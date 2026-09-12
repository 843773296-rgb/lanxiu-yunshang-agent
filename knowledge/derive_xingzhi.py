#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 `01-形制.md` 派生形制表 —— **`pattern.xz` 原来是一个指向空处的外键。**

## 为什么要有这张表

版型表每条都有 `xz`(XZ01…XZ40),而**库里没有任何一张表存 XZ 编码对应什么**。
形制只活在 md 里。于是:

  · 版型的 `xz` 指向空处,查不出「这个版型做的是什么形制」
  · **形制里写的「关键尺寸」没人用** —— 而那正是量体模板该包含的东西
  · 商品按名字匹配版型时,匹配不上就没辙(别名在 md 里躺着)

这是这一段里第四次撞见同一个形状:
**规则写在文档里,而库里没有字段承载它,那条规则就永远跑不到。**

## 关键尺寸是这份文档里最硬的一条

    XZ01 唐制齐胸襦裙  →  胸围、**胸上围**(裙头位置)、身高定裙长
    XZ04 明制立领长衫  →  **领围**、肩宽、胸围、腰围、衣长、通袖长
    XZ05 大袖衫        →  **通袖长**(指尖到指尖)、衣长

而量体模板(LT01–LT06)是整批指派的。两者对不对得上,原来**没有任何地方在验**。
`backend/xingzhi_check.py` 现在验:**一个形制的版型所用的模板,
必须覆盖这个形制的全部关键尺寸** —— 漏一项就是量的时候不会量那一项,
而那一项恰恰是这个形制最敏感的(立领对领围 ±1cm 就影响舒适)。

## 解析规则

    ### XZ04 明制立领长衫 `demo`
    - **别名**:立领袄
    - **关键尺寸**:领围、肩宽、胸围、腰围、衣长、通袖长

`demo` 标记保留成 `src_type`,和版型库一样 —— **哪些是示例数据要留痕**。
关键尺寸里括号内的说明(如「(裙头位置)」)去掉,只留尺寸名。
"""
import os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "01-形制.md")
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")


def parse():
    """返回 [(code, name, 别名, [关键尺寸], src_type), ...]。"""
    t = open(MD, encoding="utf-8").read()
    out = []
    for b in re.split(r"\n### ", t)[1:]:
        m = re.match(r"(XZ\d+)\s+(\S+)", b)
        if not m:
            continue
        code, name = m.group(1), m.group(2)
        src = "demo" if re.match(r"XZ\d+\s+\S+\s+`demo`", b) else "实"
        a = re.search(r"\*\*别名\*\*[::]\s*(.+)", b)
        k = re.search(r"\*\*关键尺寸\*\*[::]\s*(.+)", b)
        尺寸 = []
        if k:
            for x in re.split(r"[、,,]", k.group(1)):
                # 去掉括号里的说明:「胸上围(裙头位置)」→「胸上围」
                x = re.sub(r"[((].*?[))]", "", x)
                # **去掉 Markdown 加粗** —— md 里写「**领围**、肩宽」,
                # 不去的话尺寸名变成「**领围**」,和量体项表永远对不上,
                # 而检查会报成「文档里有而系统里没有」—— **红错理由比不红更费事**。
                x = x.replace("**", "").replace("*", "").strip()
                # 去掉「身高定裙长」这种带动词的描述,只留尺寸名
                x = re.sub(r"定.*$", "", x).strip()
                if x: 尺寸.append(x)
        out.append((code, name, a.group(1).strip() if a else None, 尺寸, src))
    return out


def main():
    rows = parse()
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS xingzhi(
        code TEXT PRIMARY KEY, name TEXT, alias TEXT,
        key_sizes TEXT,       -- 关键尺寸,顿号分隔。**量体模板必须覆盖它们**
        src_type TEXT)""")
    c.execute("DELETE FROM xingzhi")
    for code, name, alias, sizes, src in rows:
        c.execute("INSERT INTO xingzhi VALUES(?,?,?,?,?)",
                  (code, name, alias, "、".join(sizes) or None, src))
    c.commit()
    孤 = [r[0] for r in c.execute(
        "SELECT DISTINCT xz FROM pattern WHERE xz NOT IN (SELECT code FROM xingzhi)")]
    print(f"形制 {len(rows)} 个已落库(带关键尺寸的 "
          f"{sum(1 for r in rows if r[3])} 个,带别名的 "
          f"{sum(1 for r in rows if r[2])} 个)")
    if 孤:
        print(f"⚠️ **版型引用了形制表里没有的编码**:{孤} —— "
              f"要么 md 漏写,要么版型填错,两种都得人看一眼")
    c.close()
    return 1 if 孤 else 0


if __name__ == "__main__":
    sys.exit(main())
