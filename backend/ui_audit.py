#!/usr/bin/env python3
"""控件审计 —— 扫描 web/ 下每个页面里所有"看起来可交互"的元素,检查是否真的绑了事件。

规则:每个控件必须三选一
  ① 有事件绑定(能用)
  ② 显式禁用(带 disabled / .off / .dis 类,视觉可辨)
  ③ 从页面上删掉
不满足的一律报为 DEAD —— 用户点了没反应,是最差的一种。
"""
import re, sys, os, glob
HERE = os.path.dirname(os.path.abspath(__file__))
# 后台 web/ + 独立站点 agentsite/web/ —— 页面搬走了,审计也得跟过去,
# 否则新站的控件全在盲区里(这个项目为「新页面不在审计范围内」栽过一次)。
PAGES = sorted(glob.glob(os.path.join(HERE, "web", "*.html")) +
               glob.glob(os.path.join(HERE, "..", "agentsite", "web", "*.html")))

# 容器类(子元素才是控件),不当控件查
CONTAINERS = {"btn","clk","row","tab","ty","sel","x","dnum","mask",
              "tabs2","tags","crumb","user","ic"}

def audit(src):
    s = open(src, encoding="utf-8").read()

    # 绑定选择器全集(供后面几项共用)
    qsa = re.findall(r'querySelectorAll\("([^"]+)"\)', s)
    # 直接 getElementById("x"),或经 $("x") 这类单参简写(页面里常见 const $=id=>document.getElementById(id))
    ids = set(re.findall(r'getElementById\("(\w+)"\)', s))
    if re.search(r'\$\s*=\s*\w+\s*=>\s*document\.getElementById', s):
        ids |= set(re.findall(r'\$\("(\w+)"\)', s))
    # 另一种常见简写:const $=s=>document.querySelector(s),调用写成 $("#run")。
    # 不认这一种的话,凡是用 id 选择器绑事件的按钮全会被误报成死控件。
    if re.search(r'\$\s*=\s*\w+\s*=>\s*document\.querySelector', s):
        ids |= set(re.findall(r'\$\("#(\w+)"\)', s))
        sel_extra = " ".join(re.findall(r'\$\("([^"]+)"\)', s))
    else:
        sel_extra = ""
    sel_txt = " ".join(qsa) + " " + " ".join(ids) + " " + sel_extra + " " + \
              " ".join(re.findall(r'querySelector\("([^"]+)"\)', s))

    # ① data-* 属性:模板里用了,但没有对应的 querySelectorAll 绑定
    used = set(re.findall(r'\bdata-([a-z][a-z0-9-]*)\s*=', s)) - {"k", "f", "theme"}
    bound = set()
    # 事件委托:closest("[data-x]") / matches("[data-x]") 也是绑定。
    # 只认 querySelectorAll 的话,**纯标记型的 data-\* 全会被误报成死控件** ——
    # 而委托恰恰是这类按钮最正常的写法(参照原型里也是这么写的)。
    # 这个误报出现过两次:第一次我改了代码去迁就审计,第二次才想起来该修的是审计。
    # **同一个误报出现两次,就该修检查。**
    for sel in qsa + re.findall(r'\.(?:closest|matches)\("([^"]+)"\)', s):
        bound |= set(re.findall(r'\[data-([a-z][a-z0-9-]*)\]', sel))
    # dataset.xxx 读取的属于「数据载体」,由别的 handler 消费,不算死控件
    carriers = {m.replace("-", "") for m in used} & set(re.findall(r'dataset\.([a-zA-Z]\w*)', s))
    used = {u for u in used if u.replace("-", "") not in carriers}
    dead_attr = sorted(used - bound)

    # ② CSS 里声明了 cursor:pointer 的类,是否出现在任何绑定选择器里
    # 取选择器里最后一个类名(.cal .hd2 .nav → nav),避免把容器当控件
    ptr = set()
    for m in re.finditer(r'([^{}]*?)\{[^}]*cursor:\s*pointer', s):
        sel = m.group(1).split(",")[-1].strip()
        cls = re.findall(r'\.([a-zA-Z][\w-]*)', sel)
        if cls: ptr.add(cls[-1])
    dead_cls = []
    for c in sorted(ptr - CONTAINERS):
        inline = re.search(r'class="[^"]*\b' + c + r'\b[^"]*"[^>]*data-', s)
        # 该类所在的标签带了一个已被绑定的 id(按 id 绑,不按类绑)
        by_id = any(m.group(1) in ids for m in
                    re.finditer(r'class="[^"]*\b' + c + r'\b[^"]*"[^>]*id="(\w+)"', s)) or \
                any(m.group(1) in ids for m in
                    re.finditer(r'id="(\w+)"[^>]*class="[^"]*\b' + c + r'\b[^"]*"', s))
        occ = re.findall(r'class="([^"]*\b' + c + r'\b[^"]*)"', s)
        disabled = occ and all(re.search(r'\b(dead|dis|off)\b', o) for o in occ)
        if c not in sel_txt and not inline and not disabled and not by_id:
            dead_cls.append(c)

    # ③ 既无 data-* 也无 onclick 的裸 <button>(由 getElementById 绑定的除外)
    naked = []
    for m in re.finditer(r'<button(?![^>]*(?:data-|onclick|disabled))([^>]*)>(.*?)</button>', s, re.S):
        attrs, inner = m.group(1), m.group(2)
        bid = re.search(r'id="(\w+)"', attrs)
        if bid and bid.group(1) in ids: continue          # 由 getElementById 绑定
        # 或者被 querySelector("#xx") / querySelectorAll("#xx …") 选中 —— 一样是真绑定
        if bid and ("#" + bid.group(1)) in sel_txt: continue
        # 由类绑定:class 里任一类出现在某个绑定选择器里(如 querySelectorAll(".seed"))
        cls = re.search(r'class="([^"]*)"', attrs)
        if cls and any(c and ("." + c) in sel_txt for c in cls.group(1).split()): continue
        if "${" in inner and "disabled" in inner: continue
        # 外面套了 <a href> 的按钮 —— 点了会跳页,是真动作,不是死控件
        if re.search(r'<a [^>]*href="[^"]+"[^>]*>\s*$', s[:m.start()]): continue
        naked.append(re.sub(r"<[^>]+>", "", inner).strip()[:24])

    return dead_attr, dead_cls, naked


print("控件审计\n" + "=" * 62)
total = 0
for src in PAGES:
    dead_attr, dead_cls, naked = audit(src)
    n = len(dead_attr) + len(dead_cls) + len(naked); total += n
    print(f"\n{('agentsite/' if 'agentsite' in src else '')+os.path.basename(src):26s} {'✅ 干净' if n == 0 else f'❌ {n} 处'}")
    for a in dead_attr: print(f"   ❌ data-{a} 无绑定")
    for c in dead_cls:  print(f"   ❌ .{c} 声明了 cursor:pointer 但无任何绑定")
    for b in naked:     print(f"   ❌ <button>{b}</button> 既无 data-* 也无 onclick")

print("\n" + "=" * 62)
print(f"✅ {len(PAGES)} 个页面无死控件" if total == 0
      else f"❌ 共 {total} 处死控件 —— 用户点了没反应")
sys.exit(1 if total else 0)
