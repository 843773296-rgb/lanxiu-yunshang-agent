#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录音转写 + 分说话人的端到端实测(**不进 check.sh**:要 whisper、要调模型、要几十分钟)。

    LANXIU_PROVIDER=claude python3 tools/asr_speaker_eval.py [TS-001 TS-017 …]

## ⚠️ 前提必须先说,否则这组数是假的

喂进去的是 macOS `say` 合成的语音(顾问 Tingting、客户 Meijia),**不是真实通话录音**:
吐字清楚、没有噪音、**每句之间留 0.4 秒、从不抢话**。真实对话会抢话、插话,
一段里混进两个人的话,那一段怎么分都错一半。**这里的分人准确率是上限,不是真实效果**。

## 量三样

  ① 说话人分对几段   双声道拆成左右两条各转、按时间合并;单声道交给模型(**两轮**,模型有随机性)
  ② 行业词转对几个   真值里出现的形制 / 颜色 / 工艺词,转写稿里原样出现了几个
  ③ 商机判断一不一致 拿转写稿跑规则层,和拿原稿跑的结论比 —— **这才是业务真正在乎的**:
                     字转错几个无所谓,判断翻了才要紧
"""
import array, json, os, re, subprocess, sys, tempfile, wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import asr, opportunity as J, oppo as KO

声音 = {"顾问": "Tingting", "客户": "Meijia"}   # 两个本机能出声的中文音色(Eddy / Flo 没下载,合成出来是空的)
间隔秒 = 0.4


def 合成(稿, 目录, 名):
    """逐字稿 → 双声道 wav(顾问左、客户右)+ 单声道 wav + 每句的起始秒和说话人。"""
    行们 = [l.split(":", 1) for l in 稿.splitlines() if ":" in l]
    L, Rr, M = array.array("h"), array.array("h"), array.array("h")
    真 = []
    for i, (谁, 话) in enumerate(行们):
        aiff, wav = os.path.join(目录, "s.aiff"), os.path.join(目录, f"s{i}.wav")
        subprocess.run(["say", "-v", 声音.get(谁, "Tingting"), "-o", aiff, 话], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
        with wave.open(wav) as w:
            a = array.array("h", w.readframes(w.getnframes()))
        零 = array.array("h", [0] * len(a))
        真.append((len(M) / 16000, 谁))
        (L.extend(a), Rr.extend(零)) if 谁 == "顾问" else (L.extend(零), Rr.extend(a))
        M.extend(a)
        空 = array.array("h", [0] * int(16000 * 间隔秒))
        L.extend(空); Rr.extend(空); M.extend(空)
    st = array.array("h")
    for l, r in zip(L, Rr):
        st.append(l); st.append(r)
    for 后缀, 声道, 数据 in (("stereo", 2, st), ("mono", 1, M)):
        with wave.open(os.path.join(目录, f"{名}-{后缀}.wav"), "w") as w:
            w.setnchannels(声道); w.setsampwidth(2); w.setframerate(16000); w.writeframes(数据.tobytes())
    return 真


def 中点们(段):
    """whisper 的时间戳是取整的(5.6 秒那句标成 5.0),拿起点对齐会落进上一句 —— 用段的中点。"""
    起 = [ms for ms, _, _ in 段]
    return [(a + (起[i + 1] if i + 1 < len(起) else a + 2000)) / 2 for i, a in enumerate(起)]


def 真说话人(真, 毫秒):
    谁 = 真[0][1]
    for 起, w in 真:
        if 起 <= 毫秒 / 1000:
            谁 = w
    return 谁


def main():
    if os.environ.get("LANXIU_PROVIDER") != "claude":
        print("⚠ 规矩:一律用 Claude。设 LANXIU_PROVIDER=claude"); return 1
    import sqlite3
    c = sqlite3.connect(asr.DB)
    指定 = [x for x in sys.argv[1:] if x.startswith("TS-")]
    题 = 指定 or ["TS-001", "TS-002", "TS-004", "TS-007", "TS-017", "TS-019"]
    稿们 = {i: c.execute("SELECT text FROM call_transcript WHERE audio_id=?", (i,)).fetchone()[0] for i in 题}
    # 埋一通「客户真说了被子」的 —— 同音纠错最怕把真词改成行业词(被子 → 褙子)
    if not 指定:
        题.append("埋-被子")
        稿们["埋-被子"] = ("顾问:您好,想看点什么?\n客户:家里被子太厚了,不过今天是来看衣服的,想要一件宋制褙子。"
                         "\n顾问:褙子我们有好几款。\n客户:被子的事回头再说,先看褙子。")
    颜色, 形制, 纹样, 场合 = J.词表()
    行业词 = set(形制) | set(纹样) | {"缂丝", "妆花", "盘金绣", "云肩", "香云纱", "马面裙", "襦裙", "褙子", "月白"}
    目录 = tempfile.mkdtemp()
    总 = {"声道": [0, 0], "模型1": [0, 0], "模型2": [0, 0], "词": [0, 0], "判断": [0, 0]}
    明细 = []
    for i in 题:
        真 = 合成(稿们[i], 目录, i)
        # ① 双声道
        段 = asr.转写分段(os.path.join(目录, f"{i}-stereo.wav"), True)
        行 = asr.按声道成行(段)
        对 = sum(1 for ms, (w, _) in zip(中点们(段), 行) if w == 真说话人(真, ms))
        总["声道"][0] += 对; 总["声道"][1] += len(段)
        # ① 单声道 · 模型分人,两轮
        段m = asr.转写分段(os.path.join(目录, f"{i}-mono.wav"), False)
        for 轮 in (1, 2):
            行m, 方式 = asr.模型分人(段m)
            对m = sum(1 for ms, (w, _) in zip(中点们(段m), 行m) if w == 真说话人(真, ms))
            总[f"模型{轮}"][0] += 对m; 总[f"模型{轮}"][1] += len(段m)
            if 轮 == 1:
                模型稿 = asr.成稿(行m)
        # ② 行业词:纠错前 / 纠错后(纠错调模型,两轮)
        原 = 稿们[i]; 转 = asr.成稿(行)
        纠后们 = []
        for 轮 in (1, 2):
            try:
                # 10-04 起只有核验过的词对才自动改;这里量的是**模型提的候选**能救回多少(改 + 建议都算),
                # 和「上线后自动改了多少」是两个数 —— 后者取决于核验表里有几对
                结 = asr.同音纠错(转, 已核验={(x["原"], x["改"]) for x in []})
                纠, _ = asr.按位置替换(转, 结["改"] + 结["建议"])
                收 = sorted({(x["原"], x["改"]) for x in 结["改"] + 结["建议"]}); 拒 = 结["拒"]
            except Exception as e:
                纠, 收, 拒 = 转, [], [("", "", f"没跑通 {type(e).__name__}")]
            纠后们.append((纠, 收, 拒))
        该0 = [w for w in 行业词 if w in 原]
        for 轮, (纠, 收, 拒) in enumerate(纠后们, 1):
            总.setdefault(f"纠后{轮}", [0, 0]); 总[f"纠后{轮}"][0] += sum(w in 纠 for w in 该0); 总[f"纠后{轮}"][1] += len(该0)
            错 = [(o, n) for o, n in 收 if n not in 原]          # 改成了原稿里根本没有的词 = 改错
            if "被子" in 原 and "被子" not in 纠:
                错.append(("被子", "褙子(真词被改掉)"))
            总.setdefault(f"改错{轮}", [0, 0]); 总[f"改错{轮}"][0] += len(错); 总[f"改错{轮}"][1] += len(收)
            if 错 or 轮 == 1:
                print(f"     纠错第{轮}轮 改 {收} 拒 {len(拒)} 条{' · ❌ 改错 ' + str(错) if 错 else ''}")
        该 = [w for w in 行业词 if w in 原]
        中 = [w for w in 该 if w in 转]
        总["词"][0] += len(中); 总["词"][1] += len(该)
        # ③ 商机判断:原稿 vs 双声道转写稿 vs 单声道(模型分)转写稿
        判原 = J.判断(原)[0]; 判声 = J.判断(转)[0]; 判模 = J.判断(模型稿)[0]
        总["判断"][0] += (判原 == 判声) + (判原 == 判模); 总["判断"][1] += 2
        漏词 = sorted(set(该) - set(中))
        明细.append(dict(通话=i, 声道=f"{对}/{len(段)}", 模型=f"{对m}/{len(段m)}", 漏词=漏词,
                        判断=f"原稿{'是' if 判原 else '否'} · 双声道{'是' if 判声 else '否'} · 单声道{'是' if 判模 else '否'}"))
        print(f"  {i}  分人 声道 {对}/{len(段)} · 模型 {对m}/{len(段m)}  行业词 {len(中)}/{len(该)}"
              f"{'(漏 ' + '、'.join(漏词) + ')' if 漏词 else ''}  {明细[-1]['判断']}")
    print("=" * 96)
    p = lambda k: f"{总[k][0]}/{总[k][1]}"
    print(f"⚠️ 合成语音、每句间隔整齐、从不抢话 —— 下面是**上限**,不是真实效果")
    print(f"  说话人:双声道 {p('声道')} · 单声道模型分 第 1 轮 {p('模型1')} / 第 2 轮 {p('模型2')}")
    print(f"  行业词转对:纠错前 {p('词')} · 纠错后 第 1 轮 {p('纠后1')} / 第 2 轮 {p('纠后2')}")
    print(f"  改错(改成原稿里没有的词 + 真词被改掉):第 1 轮 {p('改错1')} / 第 2 轮 {p('改错2')}(分母是改了几处)")
    print(f"  商机判断和原稿一致:{p('判断')}")
    out = os.path.join(ROOT, "agent", "asr-speaker-results.jsonl")
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import evalrec
    evalrec.dump(out, 明细 + [dict(汇总={k: p(k) for k in 总}, 前提="合成语音,上限不是真实效果")])
    print(f"明细写到 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
