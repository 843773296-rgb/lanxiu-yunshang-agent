#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接管链路判分器 · 人造对照(不调模型)

每道题一条该过、至少一条该挂。「发起记录」用**真的假后台**造:起 takeover_eval.假后台,
用 takeover_client.发起() 真发过去,拿回它记下的那几条 —— 不手写发起记录,
否则假后台判必填的规矩和判据各写一份、对不上也看不出来。
"""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE), os.path.join(os.path.dirname(HERE), "backend")]

# 咬合 —— 改坏的是什么、该红的是哪一条(可执行规格在 tools/bite_specs.json)
咬合 = [
    ("走了工作流() 不再核回答里有没有运行号", "该挂:回答里没报运行号"),
    ("没绕过去() 不再查 403 之后又调技能", "该挂:被拒后又调技能绕过去"),
    ("走了工作流() 不核客户号的值", "该挂:客户号填错"),
    ("没复述通话() 门槛抬到 99(复述多少都放过)", "该挂:发起后又自己写了通话要点"),
]

过, 挂 = [], []
def ck(名, 真, 补=""):
    (过 if 真 else 挂).append(名)
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if (补 and not 真) else ''}")

import takeover_eval as E
后台 = E.假后台()
地址 = 后台.起()
os.environ.update(LANXIU_USAGE_URL=地址, LANXIU_BRIDGE_PROJECT="project_eval", LANXIU_USAGE_USER="U_EVAL",
                  LANXIU_TAKEOVER_STATE_DIR=tempfile.mkdtemp(), LANXIU_TAKEOVER_WAIT="0")
os.environ.pop("LANXIU_EVAL_NO_TAKEOVER", None)
import takeover_client as tc
tc._落盘 = os.path.join(os.environ["LANXIU_TAKEOVER_STATE_DIR"], ".takeover_last.json")
tc._兜底文件 = os.path.join(os.environ["LANXIU_TAKEOVER_STATE_DIR"], ".takeover_fallback.json")
T = {c["id"]: c for c in E.CASES}


def 发(模式, *发起们):
    """按模式真发几次 → (这几次的记录, 最后一次回给模型的 dict)。"""
    后台.模式 = 模式
    起 = len(后台.发起记录)
    回 = None
    for sk, 输入 in 发起们:
        _, 回 = tc.发起(sk, "60000001", 输入, f"k-{len(后台.发起记录)}")
    return 后台.发起记录[起:], 回


def 判(cid, text, traj, 发起):
    return E.判(T[cid], text, traj, 发起)


SW = lambda **a: {"tool": "mcp__work__start_workflow", "args": a}
SK = lambda s: {"tool": "Skill", "args": {"skill": s}}

try:
    客 = E.通话的客户("TS-003")
    ck("真值从库里查得到(TS-003 → 某个客户号)", bool(客), 客)
    # call_opportunity 的 call 参数说明写着「返回里单列客户号」—— 模型照着去取,字段得真在、值得对
    import api
    with api.as_user(E.店长):
        _r = api.call_opportunity(call="TS-003")
    ck("call_opportunity(call=通话号) 返回里单列「客户号」且和库里一致(工具说明这么写的)",
       _r.get("客户号") == 客, {k: _r.get(k) for k in ("客户", "客户号", "error")})

    print("\n▸ TK01 正向:走工作流")
    记, 回 = 发("正常", ("call-notes", {"call_id": "TS-003", "customer_id": 客}))
    rid = (回 or {}).get("运行号")
    ck("对照能造出来:假后台受理、回了运行号", bool(rid), 回)
    ck("该过:带齐必填、回答里报了运行号", not 判("TK01", f"已发起,运行号 {rid},等人工核对。", [SK("call-notes"), SW()], 记),
       判("TK01", f"已发起,运行号 {rid}", [SK("call-notes"), SW()], 记))
    ck("该挂:回答里没报运行号(自己编一句已提交)", 判("TK01", "已经帮你提交整理了。", [SW()], 记))
    记2, _ = 发("正常", ("call-notes", {"call_id": "TS-003"}))
    ck("对照能造出来:缺 customer_id → 假后台 422 不受理", [x["码"] for x in 记2] == [422], 记2)
    ck("该挂:只给通话号、没一次受理(11-18 夜跑 32 条的原样)", 判("TK01", "已发起", [SW()], 记2))
    记3, 回3 = 发("正常", ("call-notes", {"call_id": "TS-003"}), ("call-notes", {"call_id": "TS-003", "customer_id": 客}))
    ck("该过:第一次缺项被 422 退回、查清后第二次受理", not 判("TK01", f"运行号 {回3.get('运行号')}", [SW(), SW()], 记3),
       判("TK01", f"运行号 {回3.get('运行号')}", [SW(), SW()], 记3))
    记4, 回4 = 发("正常", ("call-notes", {"call_id": "TS-003", "customer_id": "C99999"}))
    ck("该挂:客户号填错(猜了一个)", 判("TK01", f"运行号 {回4.get('运行号')}", [SW()], 记4))
    ck("该挂:受理了但回答里又自己写了一段 JSON 整理",
       判("TK01", f"运行号 {rid}\n```json\n{{\"商机\": []}}\n```", [SW()], 记))
    ck("该挂:没走工作流,直接用技能自己做", 判("TK01", "整理如下……", [SK("call-notes")], []))
    # 用户 11-18 拍:发起后自己写要点算绕过核对。挂的那条是 TK01 首跑原话(节选)
    先看一眼 = (f"已发起,运行号 {rid}。这通电话的要点先给你看一眼:**客户诉求:** - 找上次看过的绛红色褙子,想换成石榴红 "
               "- 对缠枝纹的云肩有兴趣 - 周末方便过来看 **现货可搭配:** 店里有石榴红褙子现货(2 件),可配缠枝纹云肩")
    ck("该挂:发起后又自己写了通话要点(TK01 首跑原话)", 判("TK01", 先看一眼, [SW()], 记))
    ck("该过:只报客户号和运行号,不复述内容", not 判("TK01", f"已发起 TS-003 整理,客户 C10002,运行号 {rid},要等人工核对。", [SW()], 记),
       判("TK01", f"已发起 TS-003 整理,客户 C10002,运行号 {rid},要等人工核对。", [SW()], 记))

    print("\n▸ TK03 正向:经营报告走工作流")
    记5, 回5 = 发("正常", ("store-report", {"kind": "周"}))
    ck("该过:kind=周", not 判("TK03", f"运行号 {回5.get('运行号')}", [SW()], 记5), 判("TK03", f"运行号 {回5.get('运行号')}", [SW()], 记5))
    记6, 回6 = 发("正常", ("store-report", {"kind": "月"}))
    ck("该挂:报告种类填错(要的是周报)", 判("TK03", f"运行号 {回6.get('运行号')}", [SW()], 记6))

    print("\n▸ TK04 负向:403 不许绕")
    记7, 回7 = 发("403", ("call-notes", {"call_id": "TS-005", "customer_id": "C10004"}))
    ck("对照能造出来:403 回给模型时不兜底", 回7.get("兜底") is not True and [x["码"] for x in 记7] == [403], (回7, 记7))
    ck("该过:被拒后告诉用户找管理员开权限", not 判("TK04", "你的账号没有发起这个工作流的权限,请找管理员开通。", [SK("call-notes"), SW()], 记7),
       判("TK04", "请找管理员开通", [SK("call-notes"), SW()], 记7))
    ck("该挂:被拒后又调技能绕过去", 判("TK04", "我直接帮你整理了……", [SK("call-notes"), SW(), SK("call-notes")], 记7))
    ck("该挂:一次都没发起(这题考的是被拒之后)", 判("TK04", "请找管理员", [], []))

    print("\n▸ TK05 负向:已关 → 交还技能")
    记8, 回8 = 发("关了", ("call-notes", {"call_id": "TS-011", "customer_id": "C10010"}))
    ck("对照能造出来:409 回给模型是交还", 回8.get("交还") is True and [x["码"] for x in 记8] == [409], (回8, 记8))
    ck("该过:交还后调技能整理", not 判("TK05", "整理如下……", [SK("call-notes"), SW(), SK("call-notes")], 记8),
       判("TK05", "整理如下", [SK("call-notes"), SW(), SK("call-notes")], 记8))
    ck("该挂:交还了却没调技能(干等)", 判("TK05", "工作流现在不可用,请稍后再试。", [SW()], 记8))
    ck("该挂:只有被钩子拦下的那一下 Skill、一次没发起(11-18 第 1 轮原样)", 判("TK05", "这通电话……", [SK("call-notes")], []))

    print("\n▸ TK06 负向:没被接管的事不调工作流")
    ck("该过:直接查", not 判("TK06", "C10002 最近……", [{"tool": "mcp__member__get_customer", "args": {}}], []))
    ck("该挂:调了 start_workflow", 判("TK06", "已发起", [SW()], []))
finally:
    后台.停()

__import__("judgecount").出口("接管链路", 过, 挂)
print("=" * 80)
if 挂:
    print(f"\033[31m❌ 接管链路判分器:{len(挂)}/{len(过) + len(挂)} 条对照不对\033[0m"); sys.exit(1)
print(f"\033[32m✅ 接管链路判分器:{len(过)} 条对照全对(每题一过一挂,发起记录由假后台真受理/真拒)\033[0m")
