#!/usr/bin/env python3
"""前端 · 引用的元素必须真的存在。

## 为什么补这一条

改版时删掉了 `<select id="kind">`,但 `ask()` 里还留着 `$("#kind").value`。
于是**用户一按回车就抛 TypeError,消息发不出去** —— 而页面看起来完全正常:
框架在、按钮在、输入框能打字,只有真点一下才会露出来。

已有的三道前端检查一道都没抓到:

  · `js_check`  —— 只验**语法**,而 `$("#kind").value` 语法完全正确
  · `js_smoke`  —— DOM 桩对**任何** #id 都返回一个假元素,所以桩里它永远不是 null
  · `ui_audit`  —— 查控件有没有**绑定**,不查引用的元素还**在不在**

三道各自都对,洞躺在它们中间。**删元素的时候要连引用一起删**,而这件事得有东西盯着。

## 怎么查

把 JS 里所有 `$("#xxx")` / `getElementById("xxx")` 的 id 抽出来,
和 HTML 里 `id="xxx"` 的集合对一遍。反过来不查(页面上有 id 而 JS 不引用是正常的)。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

bad, n_files, n_refs = [], 0, 0
print("前端 · JS 引用的元素 id 必须在 HTML 里存在")
print("=" * 84)
for fn in sorted(os.listdir(WEB)):
    if not fn.endswith(".html"): continue
    src = open(os.path.join(WEB, fn), encoding="utf-8").read()
    have = set(re.findall(r'\bid="([\w-]+)"', src))
    # 动态生成的 id(模板串里拼出来的)不算 —— 它们不在静态 HTML 里,但运行时会有
    have |= set(re.findall(r'id="([\w-]+)"\s*(?:>|\s)', src))
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)
    if not scripts: continue
    n_files += 1
    js = "\n".join(scripts)
    # **先剥注释再找引用。** 第一次跑就误报了:我在注释里写了
    # 「原来是 `$("#kind").value`」来说明这个坑,检查把注释当成了真引用。
    # 注释里的代码是**说明**,不是执行的东西 —— 和「引用不是断言」同一条。
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)          # 块注释
    js = re.sub(r"^\s*//.*$", "", js, flags=re.M)           # 整行注释
    js = re.sub(r"(?<![:'\"])//[^\n]*$", "", js, flags=re.M)  # 行尾注释(别切到 http://)
    refs = set(re.findall(r'\$\(\s*"#([\w-]+)"\s*\)', js))
    refs |= set(re.findall(r'getElementById\(\s*"([\w-]+)"\s*\)', js))
    n_refs += len(refs)
    miss = sorted(refs - have)
    print(f"  {'✅' if not miss else '❌'} {fn:16s} 引用 {len(refs):2d} 个 id"
          + ("" if not miss else f" —— **{len(miss)} 个不存在**"))
    for m in miss:
        # 找出它在第几行,方便直接跳过去
        ln = next((i + 1 for i, l in enumerate(src.split("\n"))
                   if f'"#{m}"' in l and "id=" not in l), "?")
        print(f'        · $("#{m}") 在第 {ln} 行,而 HTML 里没有这个 id')
        bad.append((fn, m, ln))

print("=" * 84)
if n_files == 0:
    print("❌ 一个带脚本的页面都没扫到 —— 这不是「全通过」,是没扫到东西"); sys.exit(1)
if bad:
    print(f"❌ {len(bad)} 处引用了不存在的元素")
    print("   **运行时才炸,而且炸完整段脚本停在那儿** —— 页面看起来正常,功能死一半。")
    print("   删元素的时候要连引用一起删。")
    sys.exit(1)
print(f"✅ {n_files} 个页面 · {n_refs} 处 id 引用全部有对应元素")

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把值班页上第一个元素的 id 改掉(脚本引用的那个 id 消失)',
     '引用了不存在的元素'),
]
