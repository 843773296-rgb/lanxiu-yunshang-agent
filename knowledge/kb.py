#!/usr/bin/env python3
"""知识库解析器 —— md 是唯一源头,这里把它解析成 craft 表的行。

为什么不手抄进 seed.py:同一份知识存两遍,一定会漂移。
知识由人在 md 里维护,机器读的表由这个解析器生成,单向,不回写。
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = {"01": "形制", "02": "材质", "03": "工艺", "04": "配饰"}
# md 的字段名 → craft 表的列
BRIEF_KEYS = ["特征", "特点", "结构", "说明", "技法", "织法", "工艺", "手感"]
FIT_KEYS   = ["适合", "配伍", "用途"]
LEAD_KEYS  = ["工期", "备料周期"]
HEAD = re.compile(r"^###\s+((?:XZ|MT|KF|PS|SE)\d{2})\s+(.+?)\s+`(public|scale|demo)`\s*$")
BULLET = re.compile(r"^-\s+\*\*(.+?)\*\*\s*[::]\s*(.*)$")


def load():
    """返回 craft 表的行(元组列表),顺序与建表语句一致。"""
    out = []
    for fn in sorted(f for f in os.listdir(HERE) if re.match(r"0[1-4]-", f)):
        cat = CAT[fn[:2]]
        cur = None
        for line in open(os.path.join(HERE, fn), encoding="utf-8"):
            line = line.rstrip("\n")
            m = HEAD.match(line)
            if m:
                if cur: out.append(cur)
                cur = dict(code=m.group(1), name=m.group(2).strip(), cat=cat,
                           tier=m.group(3), fields={}, extra=[], url=None, src=None)
                continue
            if cur is None: continue
            if line.startswith("### ") or line.startswith("## "):
                out.append(cur); cur = None; continue
            b = BULLET.match(line)
            if b:
                k, v = b.group(1).strip(), b.group(2).strip()
                cur["fields"][k] = v
                if k in ("非遗", "非遗关联"):
                    u = re.search(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", v)
                    if u: cur["url"] = u.group(0).rstrip(").,")
                    cur["src"] = "中国非物质文化遗产网"
                cur["extra"].append(f"{k}:{v}")
            elif line.strip().startswith("→ http") and cur.get("url") is None:
                u = re.match(r"→\s*(https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)", line.strip())
                if u:
                    cur["url"] = u.group(1).rstrip(").,")
                    cur["src"] = "中国非物质文化遗产网"
        if cur: out.append(cur)

    rows = []
    for e in out:
        f = e["fields"]
        def pick(keys, default=None):
            for k in keys:
                if k in f: return f[k]
            return default
        brief = pick(BRIEF_KEYS, "")
        if not brief and e["extra"]:            # 兜底:都没有就取第一条要点
            brief = e["extra"][0].split(":", 1)[-1]
        # brief 只取第一句,detail 保留全部要点
        brief = re.split(r"[;;。]", brief)[0][:60] if brief else ""
        detail = " / ".join(x for x in e["extra"]
                            if not x.startswith(("适合:", "配伍:", "工期:", "成本档:", "别名:")))
        rows.append((
            e["code"], e["name"], e["cat"], f.get("别名"),
            brief or None, detail[:600] or None,
            pick(FIT_KEYS), pick(LEAD_KEYS), f.get("成本档"),
            e["tier"], e["url"],
            e["src"] or ("演示数据" if e["tier"] == "demo" else None),
        ))
    return rows


if __name__ == "__main__":
    import collections, sys
    rows = load()
    print(f"解析出 {len(rows)} 条")
    print(" 按类:", dict(collections.Counter(r[2] for r in rows)))
    print(" 按来源:", dict(collections.Counter(r[9] for r in rows)))
    empty = [r[0] for r in rows if not r[4]]
    if empty: print(" ⚠️ 无 brief 的条目:", empty)
    for r in rows[:2]:
        print()
        for k, v in zip(["code","name","cat","alias","brief","detail","fit","lead","cost","src_type","url","src_name"], r):
            print(f"   {k:9s} {str(v)[:80]}")


# ── 决策表 ────────────────────────────────────────────────────────────
# 顾问问的多数不是「缂丝是什么」,而是「客户说 X,我该推什么」。
# 这类答案在 md 里是表格,不是编码条目 —— 不解析出来,工具就查不到。
TABLES = [
    ("客户原话对照", "01-形制.md", "沟通话术:客户说的 → 实际形制"),
    ("选料决策",     "02-面料.md", "选料决策表"),
    ("配饰形制搭配", "04-配饰.md", "配饰 × 形制 速查"),
    ("配色易错",     "05-颜色.md", "三种容易翻车的配法"),
    ("工期档位",     "07-工期与成本.md", "三档典型"),
    ("售后争议判定", "09-养护与售后.md", "四、常见售后争议与判定"),
    ("基础量体项",   "08-量体与版型.md", "一、基础量体项"),
    ("形制关键尺寸", "08-量体与版型.md", "二、各形制的关键尺寸"),
]


def tables():
    """返回 [(topic, 表头list, 行list, 源文件)] —— md 里的决策表。"""
    out = []
    for topic, fn, anchor in TABLES:
        txt = open(os.path.join(HERE, fn), encoding="utf-8").read()
        i = txt.find(anchor)
        if i < 0: continue
        rows, head = [], None
        for line in txt[i:].split("\n")[1:]:
            t = line.strip()
            if t.startswith("|"):
                cells = [c.strip() for c in t.strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells): continue      # 分隔行
                (rows.append(cells) if head else None) or (head := head or cells)
            elif rows and not t.startswith(("|", ">")) and t:
                break
        if head: out.append((topic, head, rows, fn))
    return out
