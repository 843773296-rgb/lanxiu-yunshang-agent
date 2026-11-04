#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意见(DF-03 第 2 步,11-04;口径照《意见收集与能力持续改进 PRD》10-24):真调 agentsite/answer_feedback 和 sessions。

  ① 没登录 → 401;没有 trace → 400;这一轮查不到是谁问的 → 404(不猜)
  ② **别人的那一轮 → 404**,哪怕是店长看顾问的;理由说的是「不是你问的」
  ③ 自己的那一轮 → 放行;**失败的那一轮也认得出提问人**(sessions.记这一轮,不靠会话号)
  ④ 载荷里的提问人**只从登录身份取**:页面里写了「提问人」也一个字不带过去;页面字段只收那六样
  ⑤ 内部凭证没有 → 不发请求,照实说「通道没开」(不退回成只带服务账号去发)
  ⑥ 问题类型、影响:和管理后台、聊天页那两份是同一组(各写一份迟早分叉 —— 这条盯着它们没分叉)
  ⑦ 独立建议 / 我的意见:来源评价写死、不挂一轮、提问人只从登录身份取;提交键只收正常的
  ⑧ 真正发出去的命令:URL 全是 ASCII、查的是登录那个人的工号;独立建议带着提交键
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "backend")]
import answer_feedback as AF

# 咬合记录(可重放的规格在 tools/bite_specs.json,script 为这个文件的那三条)
咬合 = [
    ("别人的那一轮也能评(会话主比对改成永远放行)", "② 别人的那一轮 → 404"),
    ("提问人改成服务账号(载荷里的工号写死 U001)", "④ 载荷里的提问人就是登录的那个人"),
    ("「我的意见」查询参数不编码(中文参数名裸进 URL)", "⑧ 我的意见:发出去的 URL 全是 ASCII"),
]

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


顾问 = {"no": "60000011", "name": "林岚", "role": "门店顾问", "shop": "杭州店"}
店长 = {"no": "60000002", "name": "周店长", "role": "店长", "shop": "杭州店"}


def main():
    ok, 码, why = AF.能评吗(None, "t1", {"no": 顾问["no"]})
    ck("① 没登录 → 401", not ok and 码 == 401, (码, why))
    ok, 码, why = AF.能评吗(顾问, "", {"no": 顾问["no"]})
    ck("① 没有 trace → 400", not ok and 码 == 400, (码, why))
    ok, 码, why = AF.能评吗(顾问, "t1", None)
    ck("① 这一轮查不到是谁问的 → 404,不猜", not ok and 码 == 404 and "不猜" in why, (码, why))
    ok, 码, why = AF.能评吗(店长, "t1", {"no": 顾问["no"]})
    ck("② 别人的那一轮 → 404(店长评顾问那一轮也不行)", not ok and 码 == 404 and "不是你问的" in why, (码, why))
    ok, 码, why = AF.能评吗(顾问, "t1", {"no": 顾问["no"], "name": "林岚"})
    ck("③ 自己的那一轮 → 放行", ok and 码 == 200, (码, why))

    # ③ 失败的那一轮没有会话号:sessions.记这一轮 记下的提问人要认得出来(在临时文件上真调,不碰真的归属文件)
    import tempfile
    import sessions as SS
    原 = SS.PATH
    SS.PATH = os.path.join(tempfile.mkdtemp(), "s.json")
    try:
        SS.记这一轮("tfail", 顾问)
        SS.own("sess-old", 店长)
        ck("③ 失败的那一轮(没有会话号)认得出提问人", (SS.这一轮是谁的("tfail") or {}).get("no") == 顾问["no"],
           SS.这一轮是谁的("tfail"))
        ck("③ 11-04 之前没记过的轮次退回认会话主人;两样都没有 → None",
           (SS.这一轮是谁的("told", "sess-old") or {}).get("no") == 店长["no"] and SS.这一轮是谁的("tnone") is None)
    finally:
        SS.PATH = 原

    页面 = {"来源": "问答", "评价": "有问题", "问题类型": "答错", "说明": "  工期算错了  ", "期望结果": " 21 天 ",
           "影响": "反复出现", "提问人": {"工号": "60000001", "姓名": "冒充的"}, "工号": "60000001", "随便": 1}
    体 = AF.载荷(顾问, "t1", "s1", 页面)
    人 = 体.get("提问人") or {}
    ck("④ 载荷里的提问人就是登录的那个人(工号 / 姓名 / 角色 / 门店四样)",
       人 == {"工号": 顾问["no"], "姓名": 顾问["name"], "角色": 顾问["role"], "门店": 顾问["shop"]}, 人)
    ck("④ 页面里冒充的工号、多塞的字段一个都没带过去",
       set(体) == {"来源", "评价", "问题类型", "说明", "期望结果", "影响", "聊天站trace", "会话号", "提问人"}, sorted(体))
    ck("④ 挂着那一轮、说明和期望结果去了首尾空白",
       体["聊天站trace"] == "t1" and 体["会话号"] == "s1" and 体["说明"] == "工期算错了" and 体["期望结果"] == "21 天", 体)

    建 = AF.独立建议载荷(顾问, {"问题类型": "新增能力", "说明": " 想要按门店导出 ", "来源": "问答", "评价": "有帮助",
                              "聊天站trace": "伪造的一轮", "提问人": {"工号": "60000001"}})
    ck("⑦ 独立建议:来源 / 评价固定成「独立建议 / 建议」,页面写什么都不算;不挂任何一轮",
       建.get("来源") == "独立建议" and 建.get("评价") == "建议" and "聊天站trace" not in 建 and "会话号" not in 建, 建)
    ck("⑦ 独立建议:提问人也只从登录身份取", (建.get("提问人") or {}).get("工号") == 顾问["no"] and 建.get("说明") == "想要按门店导出", 建)
    ck("⑦ 提交键:正常的收下;空的 / 太长的 / 带空格的当没给",
       AF.提交键({"提交键": "a1b2-c3"}) == "a1b2-c3" and AF.提交键({}) is None and AF.提交键({"提交键": "x" * 65}) is None
       and AF.提交键({"提交键": "a b"}) is None)
    码2, d2 = AF.查我的(顾问, 凭证="")
    ck("⑦ 我的意见:没有内部凭证 → 不发请求、照实说通道没开", 码2 is None and "没开" in str(d2.get("error")), (码2, d2))

    # ⑧ 真正发出去的那条命令(截住 subprocess.run,不真发):11-04 「我的意见」第一版把中文参数名裸放进 URL,
    #    后台直接回「Invalid HTTP request」—— 只有真浏览器跑才撞得到,这里把它钉成判据
    import subprocess as _sp
    from urllib.parse import parse_qs, urlparse
    发了 = []
    原run = AF.subprocess.run
    class _假:
        stdout, stderr = b'{"ok": true}\n200', b""
    AF.subprocess.run = lambda 参, **kw: (发了.append((参, kw.get("input"))), _假())[1]
    try:
        AF.查我的(顾问, 凭证="x")
        AF.转给后台(建, 凭证="x", 键="k-123")
    finally:
        AF.subprocess.run = 原run
    url = next((a for a in 发了[0][0] if str(a).startswith("http")), "") if 发了 else ""
    ck("⑧ 我的意见:发出去的 URL 全是 ASCII(中文参数名要编码),查的工号就是登录的那个人",
       url.isascii() and parse_qs(urlparse(url).query).get("工号") == [顾问["no"]], url)
    头们 = [发了[1][0][i + 1] for i, a in enumerate(发了[1][0]) if a == "-H"] if len(发了) > 1 else []
    ck("⑧ 独立建议:转发时带着提交键(Idempotency-Key)", "Idempotency-Key: k-123" in 头们, 头们)

    码, d = AF.转给后台(体, 凭证="")
    ck("⑤ 没有内部凭证 → 不发请求、照实说通道没开", 码 is None and "没开" in str(d.get("error")), (码, d))

    import json, re
    后台 = os.path.join(os.path.dirname(HERE), "管理后台", "services", "api", "app", "opinions_api.py")
    页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    for 名, 这份, 页里 in (("问题类型们", AF.问题类型们, "反馈类型们"), ("影响们", AF.影响们, "影响们")):
        那份 = None
        for n in ast.parse(open(后台, encoding="utf-8").read()).body:
            if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == 名 for t in n.targets):
                那份 = ast.literal_eval(n.value)
        ck(f"⑥ {名}:和管理后台那份同一组(顺序也一样 —— 页面下拉框按这个顺序)",
           那份 is not None and tuple(那份) == tuple(这份), (那份, 这份))
        m = re.search(r"const " + 页里 + r" = (\[[^\]]*\]);", 页)
        ck(f"⑥ {名}:聊天页下拉框那份也是同一组", bool(m) and tuple(json.loads(m.group(1))) == tuple(这份), m and m.group(1))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 意见 · 聊天站这一半:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
