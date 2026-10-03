#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录音接进业务流程的检查 —— 上传 → 排队 → 转写 → 分说话人 → 挂到客户名下 → 商机判断读得到。

**不跑 whisper、不调模型**:转写和模型分人都注入假的(CI 上两样都没有,
「依赖外部状态的检查放进门禁会变成随机拦路」)。验的是**我们自己的逻辑**:

  ① 双声道按声道分:左 → 顾问、右 → 客户,分不清的标「未分」
  ② 单声道交给模型分:答得对就收;**答的形状不对 / 没跑通 → 整通标「未分」,不部分采纳**
  ③ 任何一步失败都落「失败 + 原因」,不留在「转写中」(「还在转」和「早就崩了」长得一样)
  ④ 上传:没登录拒、外店客户拒、沟通方式不在 D7 那三种里拒、空文件拒
  ⑤ 接上商机:模型分的逐字稿,规则层读得到客户的话;**未分的,规则层报「说话人没标」而不是「没商机」**
  ⑥ 整理一通的返回里带着「说话人怎么分的」—— 「声道分的」和「模型猜的」在逐字稿里长得一模一样

全部在库副本上跑,不碰主库。
"""
import json, os, shutil, sqlite3, sys, tempfile, wave, array

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import asr

G, R, D = "\033[32m", "\033[31m", "\033[0m"

# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ("串音也算在说话(另一边不是静音就不认这一边在说)", "串音压不过真说话的那边"),
    ("把左右声道对调(`左声道是 = \"顾问\"` 改成 `\"客户\"`)", "双声道:左边是顾问、右边是客户"),
    ("模型分人不验形状(长度不对也收)", "模型答的行数和段数对不上 → 整通标未分"),
    ("转写失败不落库(except 里不写「失败」)", "转写抛错 → 状态落「失败」并写清原因"),
    ("上传不核门店", "外店客户的录音传不上"),
    ("转写完不挂商机(`_os.从转写建(c, audio_id)` 删掉)", "转写完成后规则层判出商机"),
]

坏 = 0


def ck(名, ok, n, 说明=""):
    global 坏
    if n == 0:
        print(f"  {R}❌{D} {名} —— **没扫到东西**,不是通过"); 坏 += 1; return
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}(验了 {n} 个){'' if ok else '  ' + 说明}")
    坏 += 0 if ok else 1


def 假返回(文本):
    return lambda 行: {"content": [{"type": "text", "text": 文本}]}


def 造wav(path, 声道):
    with wave.open(path, "w") as w:
        w.setnchannels(声道); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(array.array("h", [0] * 1600 * 声道).tobytes())


def main():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
    c = sqlite3.connect(db); asr.建表(c); c.commit()
    客户 = c.execute("SELECT id, shop FROM customer WHERE shop IS NOT NULL ORDER BY id LIMIT 1").fetchone()
    外店 = c.execute("SELECT id FROM customer WHERE shop IS NOT NULL AND shop<>? ORDER BY id LIMIT 1", (客户[1],)).fetchone()
    c.close()

    print("\n\033[1m▸ 分说话人\033[0m")
    段 = [(0, "您好,想看点什么?", "0"), (900, "我想要月白色的马面裙。", "1"), (2000, "嗯。", "?")]
    行 = asr.按声道成行(段)
    ck("双声道:左边是顾问、右边是客户", [w for w, _ in 行] == ["顾问", "客户", "未分"], len(行), str(行))
    # 双声道切轮次:造一段 0–1 秒左边说(右边串进 1/4 音量)、1.5–2.5 秒右边说的录音
    import math
    p = os.path.join(tmp, "轮次.wav")
    帧 = array.array("h")
    for k in range(16000 * 3):
        t = k / 16000; 声 = int(8000 * math.sin(2 * math.pi * 220 * t))
        左, 右 = (声, 声 // 4) if t < 1.0 else ((0, 声) if 1.5 <= t < 2.5 else (0, 0))
        帧.append(左); 帧.append(右)
    with wave.open(p, "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000); w.writeframes(帧.tobytes())
    轮 = asr.按声道切轮次(p)
    ck("双声道按两边音量切轮次:串音压不过真说话的那边,切出两轮、各归一边",
       [x[2] for x in 轮] == ["0", "1"] and abs(轮[0][0]) <= 60 and abs(轮[1][0] - 1500) <= 60, len(轮) or 1, str(轮))
    ck("相邻同一个人的段并成一行", asr.成稿([("客户", "我想要"), ("客户", "月白的。"), ("顾问", "好。")])
       == "客户:我想要月白的。\n顾问:好。", 1)
    单 = [(0, "您好,想看点什么?", None), (900, "我想要月白色的马面裙。", None)]
    行, 方式 = asr.模型分人(单, call=假返回('["顾问","客户"]'))
    ck("单声道:模型答得对就收,标「模型」", 方式 == "模型" and [w for w, _ in 行] == ["顾问", "客户"], 1, f"{方式} {行}")
    行, 方式 = asr.模型分人(单, call=假返回('["顾问"]'))
    ck("模型答的行数和段数对不上 → 整通标未分", 方式.startswith("未分") and all(w == "未分" for w, _ in 行), 1, 方式)
    行, 方式 = asr.模型分人(单, call=假返回('["顾问","店员"]'))
    ck("模型答了「顾问 / 客户」以外的标签 → 整通标未分", 方式.startswith("未分"), 1, 方式)
    def 崩(行): raise TimeoutError("超时")
    行, 方式 = asr.模型分人(单, call=崩)
    ck("模型没跑通 → 整通标未分,并写清是没跑通", 方式.startswith("未分") and "没跑通" in 方式, 1, 方式)

    print("\n\033[1m▸ 一通录音从排队走到完成 / 失败\033[0m")
    import datetime as _d
    def 入(aid, 声道):
        p = os.path.join(tmp, aid + ".wav"); 造wav(p, 声道)
        with sqlite3.connect(db) as k:
            k.execute("INSERT INTO call_audio(id, customer_id, path, source, created, channel, status)"
                      " VALUES(?,?,?,?,?,?,?)", (aid, 客户[0], p, "真实录音", _d.date.today().isoformat(), "电话", "排队"))
    状态 = lambda aid: sqlite3.connect(db).execute(
        "SELECT a.status, a.fail_reason, t.speaker_src, t.text FROM call_audio a "
        "LEFT JOIN call_transcript t ON t.audio_id=a.id WHERE a.id=?", (aid,)).fetchone()
    入("CA-T1", 2)
    asr.处理("CA-T1", db=db, 转写=lambda p, 双: 段[:2])
    s = 状态("CA-T1")
    ck("双声道录音 → 完成,说话人按声道分", s[0] == "完成" and s[2] == "声道" and s[3].startswith("顾问:"), 1, str(s))
    入("CA-T2", 1)
    asr.处理("CA-T2", db=db, 转写=lambda p, 双: 单, call=假返回('["顾问","客户"]'))
    s = 状态("CA-T2")
    ck("单声道录音 → 完成,说话人标「模型」", s[0] == "完成" and s[2] == "模型", 1, str(s))
    入("CA-T3", 1)
    def 转崩(p, 双): raise RuntimeError("whisper 退出码 1")
    asr.处理("CA-T3", db=db, 转写=转崩)
    s = 状态("CA-T3")
    ck("转写抛错 → 状态落「失败」并写清原因", s[0] == "失败" and "退出码" in (s[1] or ""), 1, str(s))
    入("CA-T4", 1)
    asr.处理("CA-T4", db=db, 转写=lambda p, 双: [])
    s = 状态("CA-T4")
    ck("转出来是空的 → 失败,不当成「没人说话」", s[0] == "失败" and "空" in (s[1] or ""), 1, str(s))

    print("\n\033[1m▸ 接上商机:规则层读得到客户的话\033[0m")
    import oppo as KO
    t2 = 状态("CA-T2")[3]
    ck("模型分的逐字稿,规则层取得到客户那几行", "月白" in KO.客户说的(t2) and "想看点什么" not in KO.客户说的(t2), 1, t2)
    k = sqlite3.connect(db)
    商 = k.execute("SELECT o.status, n.quote FROM opportunity o JOIN opportunity_need n ON n.opp_id=o.id "
                   "WHERE o.call_id='CA-T2'").fetchall()
    ck("转写完成后规则层判出商机 → 建一条「待确认」,原话是客户说的那句",
       bool(商) and all(x[0] == "待确认" for x in 商) and any("月白" in x[1] for x in 商), len(商) or 1, str(商))
    ck("转写失败的那通不建商机", not k.execute("SELECT 1 FROM opportunity WHERE call_id='CA-T3'").fetchone(), 1)
    k.close()
    未分稿 = asr.成稿([("未分", "我想要月白色的马面裙。")])
    import opportunity as J
    是, 码, _ = J.判断(未分稿)
    ck("未分的逐字稿 → 规则层报「说话人没标」,不是「没商机」", (not 是) and 码 == "NO_CUSTOMER_LINE", 1, 码)

    print("\n\033[1m▸ 上传入口(管理后台客户页)\033[0m")
    import server, base64
    server.DB = db
    server.录音目录 = os.path.join(tmp, "录音")
    真规整 = asr.规整
    def 假规整(src, dst):       # CI 上没有 afconvert —— 只验我们的逻辑,不验系统工具
        造wav(dst, 1); return dst, 0.1
    asr.规整 = 假规整
    try:
        数 = base64.b64encode(b"RIFF....fake").decode()
        本店员 = dict(no="T1", name="测", role="顾问", shop=客户[1])
        out, code = server.call_upload(None, dict(customer_id=客户[0], channel="电话", data=数), 入队=False)
        ck("没登录 → 拒(401)", code == 401, 1, str(out))
        out, code = server.call_upload(本店员, dict(customer_id=外店[0], channel="电话", data=数), 入队=False)
        ck("外店客户的录音传不上", code == 403, 1, str(out))
        out, code = server.call_upload(本店员, dict(customer_id=客户[0], channel="短信", data=数), 入队=False)
        ck("沟通方式不在「电话 / 上门 / 到店」里 → 拒(业务 D7:群发短信不算沟通)", code == 400, 1, str(out))
        out, code = server.call_upload(本店员, dict(customer_id=客户[0], channel="上门", data=""), 入队=False)
        ck("空文件 → 拒", code == 400, 1, str(out))
        out, code = server.call_upload(本店员, dict(customer_id=客户[0], channel="上门", data=数,
                                                 filename="x.wav"), 入队=False)
        行 = server.rows("SELECT status, channel, uploaded_by, source FROM call_audio WHERE id=?", out.get("id"))
        ck("本店客户的录音收下,落「排队」,记下谁传的、什么方式",
           code == 200 and 行 and 行[0]["status"] == "排队" and 行[0]["channel"] == "上门"
           and 行[0]["uploaded_by"] == "T1" and 行[0]["source"] == "真实录音", 1, f"{code} {out} {行}")
        详 = server.customer_detail(客户[0])
        ck("客户详情里看得到这通录音", any(x["id"] == out.get("id") for x in 详.get("calls") or []), 1)
    finally:
        asr.规整 = 真规整

    print("\n\033[1m▸ 整理一通:说话人的来路跟着原文走\033[0m")
    import api
    api.DB = db
    with api.as_user(dict(no="HQ", name="总部", role="总部运营")):
        r = api.call_opportunity(call="CA-T2")
    ck("模型分的那通,返回里写明「模型按内容分的」", "模型" in (r.get("说话人怎么分的") or ""), 1, str(r)[:160])

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if 坏:
        print(f"{R}❌ 录音接进流程 {坏} 条不过{D}"); return 1
    print(f"{G}✅ 录音接进流程全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
