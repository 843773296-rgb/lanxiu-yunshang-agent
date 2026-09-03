#!/usr/bin/env python3
"""定制方案的校验 —— 这是 Hook,不是 Tool。

区别在哪:
  Tool = 模型主动查了才生效。顾问不问,它就不出场。
  Hook = 动作发生前强制执行。没有人问,它照样拦。

相容矩阵原本只挂在 Tool 上(kb_combo),顾问得想到要问才有用 ——
而真实场景里他想不到:「香云纱的马面裙上做妆花」每个词都听得懂,不觉得有坑。
这个文件把同一份知识挂到 Hook 上。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api

# 传统色,取自 knowledge/05-颜色.md(那份文件里色值是近似值,仅供沟通,不是打样标准)
COLORS = ["朱红","胭脂","绛","妃色","月白","藏青","靛青","黛","竹青","青碧",
          "缃色","秋香","赭","紫檀","藕荷","玄色","素"]

BLOCK, WARN, OK = "block", "warn", "ok"


def validate(xz=None, mt=None, kf=None, ps=None, color=None):
    """返回 (能不能保存, 问题清单)。问题分三档:

      block  不可 —— 物理上做不了,加钱也没用。**服务端硬拦。**
      warn   需评估 / 未定义 —— 能保存,但必须留痕并转工艺负责人
      ok     无问题
    """
    issues = []
    kf = [k for k in (kf or []) if k]

    if not xz: issues.append(dict(level=BLOCK, kind="缺形制", msg="必须选一个形制"))
    if not mt: issues.append(dict(level=BLOCK, kind="缺面料", msg="必须选一个面料"))

    # 工艺 × 面料:逐对查相容矩阵
    if mt:
        for k in kf:
            r = api.kb_combo(k, mt)
            if r.get("error"):
                issues.append(dict(level=WARN, kind="查不到", pair=f"{k} × {mt}", msg=r["error"][:80]))
                continue
            v = r.get("verdict")
            if v == "不可":
                issues.append(dict(level=BLOCK, kind="不可", pair=f"{r['craft']} × {r['material']}",
                                   msg=r.get("reason") or "相容矩阵判定为不可"))
            elif v == "需评估":
                issues.append(dict(level=WARN, kind="需评估", pair=f"{r['craft']} × {r['material']}",
                                   msg=r.get("reason") or "需打样评估"))
            elif v == "未定义":
                issues.append(dict(level=WARN, kind="未定义", pair=f"{r['craft']} × {r['material']}",
                                   msg="这一格相容矩阵还没录入,须转工艺负责人确认,不得自行推断"))

    if color and color not in COLORS:
        issues.append(dict(level=WARN, kind="颜色", msg=f"「{color}」不在传统色清单里,须确认打样色卡"))

    can_save = not any(i["level"] == BLOCK for i in issues)
    return can_save, issues


def options():
    """配置页要用的选项。全部来自 craft 表(而 craft 表来自 knowledge/*.md)。"""
    def by(cat):
        return [dict(code=r["code"], name=r["name"], src=r["src_type"], brief=r["brief"])
                for r in api._rows("SELECT code,name,src_type,brief FROM craft WHERE cat=? ORDER BY code", cat)]
    return dict(形制=by("形制"), 材质=by("材质"), 工艺=by("工艺"), 配饰=by("配饰"), 颜色=COLORS)


if __name__ == "__main__":
    print("定制方案校验 · 自测\n" + "=" * 74)
    CASES = [
        ("明制马面裙 + 香云纱 + 妆花",  dict(xz="明制马面裙", mt="香云纱", kf=["妆花"]),          False, "block"),
        ("明制马面裙 + 云锦 + 妆花",    dict(xz="明制马面裙", mt="云锦",   kf=["妆花"]),          True,  "ok"),
        ("宋制褙子 + 宋锦 + 妆花(未录入)", dict(xz="宋制褙子", mt="宋锦",   kf=["妆花"]),          True,  "warn"),
        ("唐制齐胸襦裙 + 真丝素罗 + 盘金绣", dict(xz="唐制齐胸襦裙", mt="真丝素罗", kf=["盘金绣"]), False, "block"),
        ("一次选两个工艺,一个不可",      dict(xz="明制马面裙", mt="香云纱", kf=["苏绣","妆花"]),   False, "block"),
        ("没选面料",                  dict(xz="明制马面裙", mt=None,    kf=[]),                False, "block"),
    ]
    bad = 0
    for name, kw, want_save, want_level in CASES:
        ok, issues = validate(**kw)
        lv = "block" if any(i["level"] == BLOCK for i in issues) else \
             ("warn" if any(i["level"] == WARN for i in issues) else "ok")
        hit = (ok == want_save and lv == want_level)
        if not hit: bad += 1
        print(f"{'✅' if hit else '❗'} {name:34s} 可保存={str(ok):5s} 最高档={lv:5s}"
              + ("" if hit else f"   期望 可保存={want_save} 最高档={want_level}"))
        for i in issues[:2]:
            print(f"      └ [{i['level']}] {i.get('pair','')} {i['msg'][:52]}")
    print("=" * 74)
    print("✅ 校验逻辑符合预期" if not bad else f"❌ {bad} 处不符")
    sys.exit(1 if bad else 0)
