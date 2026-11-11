#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看商品图 / 能力申请单 · 守得住吗(用户 2026-11-11 拍:「都加」;「生成需求申请单可以让智能体代劳」)。

判据真调被测代码(backend/product_images.py、capability_request.py、api 两个工具、sdk 角色工具表、prompts.assemble)。
  ① 列图:真图和示意图分得开(示意图不能当实物核料);款号不合规拒;只看文件名不读库外
  ② 起草:必填五栏缺哪栏照实列「还缺」、**不替用户编**;模型多塞的键不进申请单;提交载荷类型是「新增能力」
  ③ 工具口:款号不存在给候选;起草只读(不写任何东西)
  ④ 接线:两个工具挂给顾问(kb)和版师核料(pattern),规矩 TL79 真进了这两个角色的提示词;
     店长(task)这次**没挂**(它的工具由后台生产版本决定,要另出一版)—— 挂上了要改这条
  ⑤ 页面:申请单六栏和 Python 那份同一组;卡按工具名画、按钮绑了点击、提交走 /api/opinion 类型「新增能力」
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), ROOT]
import product_images as PI          # noqa: E402
import capability_request as CR      # noqa: E402

咬合 = []
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def main():
    print("▸ ① 列图")
    with tempfile.TemporaryDirectory() as d:
        for f in ("lx_1-main.png", "lx_1-d1.jpg", "lx_1-sku2-main.png", "lx_10-main.png", "lx_1-intro.txt"):
            open(os.path.join(d, f), "w").close()
        r = PI.列图("lx_1", 目录=d)
        位 = {g["图位"]: g["真图"] for g in r["图"]}
        ck("真图(有文件)和示意图(没文件、会现画)分得开", 位.get("main") is True and 位.get("d1") is True and 位.get("intro") is False
           and 位.get("d2") is False, 位)
        ck("这一款额外的真图位(颜色整套)也列出来", 位.get("sku2-main") is True, 位)
        ck("别的款号前缀相同不混进来(lx_10 不算 lx_1)", r["真图数"] == 3, r["真图数"])
        ck("说明里讲清示意图不能当实物核料", "不能当实物" in r["说明"], r["说明"])
        ck("一张真图都没有时明说", "一张真图都没有" in PI.列图("lx_9", 目录=d)["说明"])
    ck("款号带路径符 → 拒", "error" in PI.列图("../etc"))

    print("▸ ② 起草")
    r = CR.起草({"谁用": "版师", "想让它做什么": "按款号看图", "乱塞的": "x", "提问人": "U001"})
    ck("缺的必填栏照实列在「还缺」,没写清", set(r["还缺"]) == {"场景", "现在卡在哪", "希望得到什么"} and r["写清了吗"] is False, r["还缺"])
    ck("没问清的栏是空的(不替用户编)", r["申请单"]["场景"] == "" and r["申请单"]["给它什么"] == "", r["申请单"])
    ck("模型多塞的键不进申请单", "乱塞的" not in r["申请单"] and "提问人" not in r["申请单"], r["申请单"])
    ck("提交载荷:类型「新增能力」,说明里每栏带栏名、没问清的写「没问清」",
       r["提交载荷"]["问题类型"] == "新增能力" and "· 谁用:版师" in r["提交载荷"]["说明"] and "(没问清)" in r["提交载荷"]["说明"], r["提交载荷"])
    全 = CR.起草({n: "有" for n, _ in CR.栏})
    ck("五栏都写了 → 写清了、下一步是让用户自己点「确认提交」", 全["写清了吗"] and "确认提交" in 全["下一步"], 全["下一步"])

    print("▸ ③ 工具口")
    import api
    r = api.get_product_images("lxys_不存在的款")
    ck("款号不存在 → error(不画一组假图)", "error" in r and "图" not in r, r)
    ck("没给款号 → error 并指路先查款号", "error" in api.get_product_images("") and "keyword" in api.get_product_images("")["error"])
    ck("两个工具都不在写工具名单里(只读;申请由用户点卡提交)",
       "get_product_images" not in api.WRITE_TOOLS and "draft_capability_request" not in api.WRITE_TOOLS)

    print("▸ ④ 接线")
    import prompts
    sdk码 = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    def 名单(名):
        m = re.search(名 + r" = \[(.*?)\n\]", sdk码, re.S)
        return m.group(1) if m else ""
    for 角色, 表 in (("顾问 kb", "KB_ONLY_TOOLS"), ("版师 pattern", "PATTERN_TOOLS")):
        段 = 名单(表)
        ck(f"{角色}:两个工具都挂在 {表} 字面量里(P3/P6 从字面量读)",
           "mcp__commerce__get_product_images" in 段 and "mcp__commerce__draft_capability_request" in 段)
    for 角色 in ("kb", "pattern"):
        _, ids = prompts.assemble(角色, ["get_product_images", "draft_capability_request"])
        ck(f"规矩 TL79 真装进了 {角色} 的提示词", "TL79" in ids, ids[-5:] if ids else ids)
    ck("店长 task 这次没挂(工具由后台生产版本决定;挂上了要另出一版并改这条)",
       "get_product_images" not in 名单("TASK_ONLY_TOOLS") and "get_product_images" not in 名单("SHOP_TOOLS"))

    import sdk as _sdk
    ck("两个工具的返回值真的送到页面(结构化回前端白名单里有)—— 不在的话卡一张都画不出来",
       {"get_product_images", "draft_capability_request"} <= set(_sdk.结构化回前端), sorted(_sdk.结构化回前端))
    print("▸ ⑤ 页面")
    页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    m = re.search(r"const 申请栏 = \[(.*?)\];", 页)
    页栏 = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    ck("申请单六栏:页面和 capability_request.栏 同一组、同一顺序", 页栏 == [n for n, _ in CR.栏], (页栏, [n for n, _ in CR.栏]))
    ck("卡按工具名画(页面里的名字就是 api 里的工具名)",
       'const 看图工具 = "get_product_images", 申请单工具 = "draft_capability_request"' in 页
       and "get_product_images" in api.TOOLS and "draft_capability_request" in api.TOOLS)
    ck("申请单按钮绑了点击,提交走 /api/opinion、类型「新增能力」",
       'querySelectorAll("[data-req]")' in 页 and re.search(r'fetch\("/api/opinion".{0,200}问题类型: "新增能力"', 页, re.S) is not None)
    ck("意见与建议:选「新增能力」换六栏", 'id="op-cap"' in 页 and '$("#op-type").value === "新增能力"' in 页)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 看商品图 / 能力申请单:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
