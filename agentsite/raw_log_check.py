# -*- coding: utf-8 -*-
"""执行记录的原文 · 存得真、改了查得出、谁能看、到期删(证据中心 P0「原始日志」,用户 10-25 拍「1+2 都要」)。

展示副本(/spans)抹了凭据、打了码、截到 4000 字 —— 它不是发生过的原样。原文另存一份,只抹凭据。
真调 agent/spans.py(一棵树 / 读原文 / 清过期原文)和 sessions.能看原文吗;全在临时目录,不碰真日志和真会话表。
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "agent")]
import spans as SP
import sessions as SS

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("原文也截断(存的就是展示副本)", "原文没截断:5000 字的返回原样存下,展示副本才截"),
    ("店长看原文不核门店", "别店的店长 → 看不了原文"),
    ("读原文时不重算 sha256(校验恒为一致)", "原文存下以后被改 → 读出来校验「不一致」"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def main():
    print("执行记录原文 · 存真 / 校验 / 权限 / 到期")
    d = tempfile.mkdtemp()
    日志 = os.path.join(d, "spans.jsonl")
    t = SP.一棵树(tid="TR1", 会话号="会话-甲", 边跑边记=True, 路径=日志)
    根 = t.开("invoke_agent", "invoke_agent 测")
    长 = "客户 13812345678 下单," + "甲" * 5000
    a = t.一次工具调用(父=根, 工具="get_customer", 参数={"customer": "C1", "api_key": "不该留"}, 调用号="k1")
    t.工具回来了(a, 长)
    t.收(根)
    条, 说明 = SP.读原文("TR1", os.path.join(d, "raw"))
    返 = next((x for x in 条 if x.get("哪段") == "返回"), {})
    参 = next((x for x in 条 if x.get("哪段") == "参数"), {})
    展 = {s["span_id"]: s for s in SP.读(日志)["TR1"]}["k1"]["attr"]
    ck("原文没截断:5000 字的返回原样存下,展示副本才截", 返.get("内容") == 长 and 展.get("lanxiu.result.truncated") is True,
       (len(返.get("内容") or ""), 展.get("lanxiu.result.truncated")))
    ck("原文不打码(手机号完整),展示副本打码(138****5678)", "13812345678" in (返.get("内容") or "")
       and "138****5678" in 展.get("gen_ai.tool.call.result", "") and "13812345678" not in 展.get("gen_ai.tool.call.result", ""))
    ck("凭据在原文里照样抹掉(密钥不落日志)", "不该留" not in (参.get("内容") or "") and SP.抹了 in (参.get("内容") or ""), 参)
    ck("每条带 sha256,刚存的读出来校验「一致」", 返.get("sha256") and all(x.get("校验") == "一致" for x in 条), [x.get("校验") for x in 条])
    ck("原文写在日志旁边(给了临时路径就不往真目录写)", os.path.exists(os.path.join(d, "raw", "TR1.jsonl")))
    # 改一个字 → 校验不一致
    p = os.path.join(d, "raw", "TR1.jsonl")
    行们 = [json.loads(l) for l in open(p, encoding="utf-8")]
    行们[-1]["内容"] = 行们[-1]["内容"].replace("下单", "退款")
    open(p, "w", encoding="utf-8").write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in 行们))
    ck("原文存下以后被改 → 读出来校验「不一致」",
       SP.读原文("TR1", os.path.join(d, "raw"))[0][-1].get("校验", "").startswith("不一致"))
    # 到期:31 天前的删掉留说明,29 天的留着
    for tid, 天 in (("OLD", 31), ("NEW", 29)):
        q = os.path.join(d, "raw", f"{tid}.jsonl"); open(q, "w").write("{}\n")
        os.utime(q, (time.time() - 天 * 86400,) * 2)
    n = SP.清过期原文(os.path.join(d, "raw"))
    ck("超过 30 天的原文删掉,29 天的留着", n == 1 and not os.path.exists(os.path.join(d, "raw", "OLD.jsonl"))
       and os.path.exists(os.path.join(d, "raw", "NEW.jsonl")), n)
    ck("删掉的那一轮再读 → 说「已按保留期删除」(不说成没采到)", "保留期删除" in SP.读原文("OLD", os.path.join(d, "raw"))[1])
    ck("从没采过原文的那一轮 → 说没有原文,不是「已删」", "没有原文" in SP.读原文("NONE", os.path.join(d, "raw"))[1])
    # 权限(会话归属写在临时文件)
    原 = SS.PATH
    SS.PATH = os.path.join(d, "sessions.json")
    try:
        顾问 = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}
        本店长 = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
        别店长 = {"no": "60000004", "name": "周恒东", "role": "店长", "shop": "SH002 徐汇店"}
        总部 = {"no": "60000008", "name": "魏欣新", "role": "总部运营", "shop": None}
        SS.own("会话-甲", 顾问)
        判 = SS.能看原文吗
        ck("没登录 → 401", 判(None, "会话-甲")[:2] == (False, 401))
        ck("顾问看自己会话的原文 → 不行(顾问看打了码的那份)", 判(顾问, "会话-甲")[0] is False, 判(顾问, "会话-甲"))
        ck("本店店长 → 能看原文", 判(本店长, "会话-甲")[0] is True, 判(本店长, "会话-甲"))
        ck("别店的店长 → 看不了原文", 判(别店长, "会话-甲")[0] is False, 判(别店长, "会话-甲"))
        ck("总部运营 → 能看", 判(总部, "会话-甲")[0] is True and 判(总部, None)[0] is True)
        ck("查不到会话归属 → 店长也看不了(只有总部),不猜", 判(本店长, "查不到")[0] is False and 判(本店长, None)[0] is False)
    finally:
        SS.PATH = 原
    # 接线
    app = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    段 = app[app.index('if p == "/spans/raw":'):app.index('条, 说明 = _sp.读原文(tid)')]
    ck("/spans/raw 判权用 能看原文吗,而且**判之前**就记访问(被拒的也记)",
       "_ss.能看原文吗(" in 段 and 段.index("_记原文访问(") < 段.index("if not 行:"))
    ig = open(os.path.join(os.path.dirname(HERE), ".gitignore"), encoding="utf-8").read()
    ck("原文目录和访问记录都在 .gitignore 里(仓库是公开的)", ".feynman/raw/" in ig and ".feynman/raw-access.jsonl" in ig)
    print()
    if 坏:
        print(f"{R}❌ 执行记录原文 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 执行记录原文:不截断不打码只抹凭据、改了查得出、只给总部和本店店长、30 天到期留说明(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
