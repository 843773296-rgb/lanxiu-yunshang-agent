# -*- coding: utf-8 -*-
"""通话录音转文本(ASR)。

设计稿里,沟通记录带 `.wav` 录音附件,而**沟通记录没有任何文字内容字段** ——
那通电话说了什么,只存在于录音里。商机判断的第一个条件是
「客户表达过未满足的偏好」,而那句话现在谁也读不到。

这个模块把录音变成文字,让它可读、可查、可判。

## 选型:whisper.cpp,不是 Python 的那些

本机 Python 是 **3.14**,torch / funasr 这类大概率装不上;
而且这个项目的底线是「无第三方依赖,纯标准库」。
whisper.cpp 是纯 C++(`brew install whisper-cpp`),
通过 subprocess 调,**一个 Python 包都不用装**。
Apple Silicon 上走 Metal,速度够用。

## ⚠️ 两个字段,从第一天就要有

**① `source`:这段音频是真实录音还是合成的。**
现在没有真实通话录音,测试音频是 macOS 的 `say` 合成的。
**合成语音的转写和真实通话的转写,在库里长得一模一样** ——
而识别率差得远:合成语音吐字清楚、没有背景噪音、没有口音、不抢话。
拿合成语音量出来的准确率去代表真实效果,**那个数会好看得离谱,而且看不出是假的**。
(并行会话在识图评测上踩过同一个形状:喂的是合成图不是真照片。)

**② `edited_by`:这段文字有没有人工校对过。**
**「机器转的」和「人改过的」也长得一模一样。**
顾问改过的逐字稿是更可信的证据,做商机判断时权重不同;
更要紧的是,拿人工改过的文本去算 ASR 准确率,**算出来的是人的水平不是机器的**。

## 热词偏置

汉服术语(马面裙 / 齐胸襦裙 / 妆花缎 / 缂丝 / 盘金绣 / 接襕……)
不在通用模型的常见词里,**识别错了不会报错,只会安静地转成别的字**。
whisper 支持 `--prompt` 做上下文偏置 —— 把行业词表喂进去。
`asr_check.py` 里有开/关两组的对照,**光说「加了热词」不算数,要量出差多少**。
"""
import os, re, sqlite3, subprocess, shutil, time, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
模型目录 = os.path.expanduser("~/.whisper-models")
默认模型 = "ggml-small.bin"
可执行 = "whisper-cli"

# 喂给模型的行业词。**不写死在这儿** —— 从知识库和库里现读,
# 否则加一个新形制要改代码(和场合词表那条是同一个理由)。
热词字数上限 = 180   # whisper 的提示最多约 224 个 token,汉字一个字 1–2 个 token,超了它会截掉前面的


def _短名(名):
    """「唐制齐胸襦裙」→「齐胸襦裙」、「绢 / 电力纺」→ 两个、「香云纱 · 双面莨」→「香云纱」。人说的是短名。"""
    出 = []
    for 段 in re.split(r"\s*/\s*", 名 or ""):
        段 = re.sub(r"[((].*?[))]", "", 段).split("·")[0].strip()
        段 = re.sub(r"^(唐制|宋制|明制|晋制|魏晋|童款|改良)", "", 段).strip()
        if 2 <= len(段) <= 5:
            出.append(段)
    return 出


def 行业词(limit=None):
    """喂给 whisper 的行业词。**按类别轮流取**,每一类都有份。

    ⚠️ 10-03 之前这里是「形制取 40 个 + craft 表取前 30 个」—— 而 craft 表**前面全是形制**,
    于是**缂丝、妆花、香云纱、云肩一个都没进热词**;形制还是全称(「唐制齐胸襦裙」),人说的是「齐胸襦裙」。
    之前 asr_check 量出的「热词有用」,量的只是形制和颜色那一半。
    """
    类们 = []
    try:
        with sqlite3.connect(DB) as c:
            for 类 in ("形制", "材质", "工艺", "配饰"):
                类们.append([w for (n,) in c.execute("SELECT name FROM craft WHERE cat=? ORDER BY code", (类,))
                             for w in _短名(n)])
            类们.append([r[0] for r in c.execute(
                "SELECT DISTINCT color FROM sku WHERE color NOT IN ('定制','素') ORDER BY color")])
        # 纹样走口径模块(knowledge/motif.py 是唯一真相源),和商机判断的纹样词表同一份
        import sys as _sys
        _sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
        import motif
        类们.append([w for w in motif.词表() if w != "无纹样"])
    except sqlite3.Error:
        pass
    seen, out, 字 = set(), [], 0
    for k in range(max((len(x) for x in 类们), default=0)):
        for 类 in 类们:
            if k < len(类):
                w = (类[k] or "").strip()
                if w and w not in seen and len(w) <= 8 and 字 + len(w) + 1 <= 热词字数上限:
                    seen.add(w); out.append(w); 字 += len(w) + 1
    return out[:limit] if limit else out


def 提示词():
    """whisper 的 initial prompt —— 一句自然的中文,把行业词带进上下文。"""
    ws = 行业词()
    if not ws:
        return ""
    # **必须写「简体中文」**。不写的话模型可能吐繁体 ——
    # 而「识别成繁体」和「识别错了」在按简体做的比对里长得一模一样,
    # 会把对的判成错的,**让热词的收益看起来比实际大 2.5 倍**(实测踩过)。
    return ("以下是简体中文的汉服定制门店通话记录,可能出现这些词:"
            + "、".join(ws) + "。请用简体中文转写。")


def 可用():
    """环境齐不齐。**缺什么要说清是缺哪一样**,不要笼统报「不可用」。"""
    缺 = []
    if not shutil.which(可执行):
        缺.append(f"没装 {可执行}(brew install whisper-cpp)")
    m = os.path.join(模型目录, 默认模型)
    if not os.path.exists(m):
        缺.append(f"没有模型 {m}")
    return (not 缺), 缺


def 转写(wav, model=默认模型, 用热词=True, timeout=600):
    """把一个 wav 转成文字。返回 (文本, 用时秒, 用的什么模型)。

    **转不出来就抛** —— 不返回空字符串:
    「转出来是空的」和「这段录音本来就没人说话」长得一模一样。
    """
    ok, 缺 = 可用()
    if not ok:
        raise RuntimeError("ASR 环境不全:" + ";".join(缺))
    if not os.path.exists(wav):
        raise FileNotFoundError(wav)

    cmd = [可执行, "-m", os.path.join(模型目录, model), "-f", wav,
           "-l", "zh", "-otxt", "-of", wav[:-4], "--no-timestamps"]
    if 用热词:
        p = 提示词()
        if p:
            cmd += ["--prompt", p]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    用时 = time.time() - t0
    txt文件 = wav[:-4] + ".txt"
    if r.returncode != 0 or not os.path.exists(txt文件):
        raise RuntimeError(f"转写失败(退出码 {r.returncode}):{(r.stderr or '')[-300:]}")
    with open(txt文件, encoding="utf-8") as f:
        文本 = f.read().strip()
    return 文本, 用时, model


def 建表(c):
    # 录音本身。**不存音频二进制** —— 只存路径,库不该扛音频。
    c.execute("""create table if not exists call_audio(
                   id        TEXT primary key,
                   customer_id TEXT,
                   ref_kind  TEXT,          -- followup / schedule / appointment
                   ref_id    TEXT,
                   path      TEXT not null,
                   seconds   REAL,
                   source    TEXT not null, -- 真实录音 / 合成(测试用)
                   created   TEXT not null)""")
    # 转写结果
    c.execute("""create table if not exists call_transcript(
                   audio_id  TEXT primary key,
                   text      TEXT not null,
                   engine    TEXT not null,
                   model     TEXT not null,
                   hotwords  INTEGER not null default 0,
                   cost_sec  REAL,
                   trad      TEXT,          -- 转写结果里的繁体字(空=全简体)
                   created   TEXT not null,
                   edited_by TEXT,          -- 人工校对过就记下是谁
                   edited_at TEXT)""")
    _补列(c)


def _补列(c):
    """10-03 录音接进业务流程时加的列。老库没有就补(ALTER 只加列,不动已有数据)。"""
    有 = {r[1] for r in c.execute("PRAGMA table_info(call_audio)")}
    for 列, 型 in (("channel", "TEXT"),        # 沟通方式:电话 / 上门 / 到店(业务 D7)
                   ("status", "TEXT"),         # 排队 / 转写中 / 完成 / 失败;NULL = 不经过流水线(造的逐字稿)
                   ("fail_reason", "TEXT"),
                   ("uploaded_by", "TEXT")):
        if 列 not in 有:
            c.execute(f"ALTER TABLE call_audio ADD COLUMN {列} {型}")
    有 = {r[1] for r in c.execute("PRAGMA table_info(call_transcript)")}
    for 列 in ("raw_text", "fixes"):
        # raw_text:纠错之前 whisper 吐的原样;fixes:改了哪几处(JSON)。**改过的稿和原稿长得一模一样**,
        # 不留原稿的话,「客户真说的是被子、被改成了褙子」这种事永远查不回来
        if 列 not in 有:
            c.execute(f"ALTER TABLE call_transcript ADD COLUMN {列} TEXT")
    if "speaker_src" not in 有:
        # 说话人是怎么分出来的:声道 / 模型 / 未分 / 文本自带(造的逐字稿)。
        # **「声道分的」和「模型猜的」在逐字稿里长得一模一样** —— 都是「客户:……」
        c.execute("ALTER TABLE call_transcript ADD COLUMN speaker_src TEXT")


def 入库(audio_id, customer_id, wav, 文本, model, 用时, source, 用热词=True,
        ref_kind=None, ref_id=None, seconds=None, today=None):
    today = today or datetime.date.today().isoformat()
    with sqlite3.connect(DB) as c:
        建表(c)
        c.execute("""insert into call_audio(id,customer_id,ref_kind,ref_id,path,seconds,source,created)
                     values(?,?,?,?,?,?,?,?)
                     on conflict(id) do update set path=excluded.path, source=excluded.source""",
                  (audio_id, customer_id, ref_kind, ref_id, wav, seconds, source, today))
        # ⚠️ **入库前查繁体。** whisper 转中文会吐繁体,而库里的商品一律简体
        # (业务 2026-09-20 定)。转出「紅色」而库里是「红色」,
        # 查「这位客户提到过红色吗」就**匹配不到,而且不报错,只返回空** ——
        # 「客户没提过」和「提过但简繁对不上」在结果里长得一模一样。
        # 这里只**记下来**不自动转:猜错的转换和正确的转换在库里也长得一样。
        import simplified
        繁 = "".join(simplified.繁体字(文本))
        c.execute("""insert into call_transcript(audio_id,text,engine,model,hotwords,cost_sec,trad,created)
                     values(?,?,?,?,?,?,?,?)
                     on conflict(audio_id) do update set
                       text=excluded.text, model=excluded.model,
                       hotwords=excluded.hotwords, cost_sec=excluded.cost_sec,
                       trad=excluded.trad""",
                  (audio_id, 文本, "whisper.cpp", model, 1 if 用热词 else 0, 用时, 繁 or None, today))


# ══════════════════════════════════════════════════════════════════
# 分说话人 + 业务流程(10-03,用户选的 B 方案)
# ══════════════════════════════════════════════════════════════════
#
# 商机这条链靠的是「**只认客户说的话**」(顾问介绍商品一定会提颜色)。
# 而 whisper 吐出来的是一整段,不分谁说的。用户 10-03 定:
#
#     双声道(电话系统把顾问、客户录在左右两边)→ 按声道分        speaker_src = 声道
#     单声道(上门 / 到店,一个麦克风)        → 模型按内容分      speaker_src = 模型
#     分不出来(模型没跑通 / 声道分不清)     → 标「未分」,不进商机判断
#
# 模型分的那些,兜底是业务 D5:商机要顾问点头才落库 —— 顾问当时在场,谁说的哪句一眼看得出。
# 实测(合成录音,10-03):双声道 13/13、模型分 34/34 —— **合成音频每句间隔整齐,真实抢话会更差,
# 那两个满分不代表真实效果**。真录音进来之后要重量(tools/asr_speaker_eval.py)。

# ⚠️ **拍脑袋的**:双声道里左边是顾问。取决于门店电话系统怎么录,接真设备时要核。
# 录反了的后果:顾问的话全被当成客户的诉求 —— 所以做成一个有名字的常量,不散在代码里
左声道是 = "顾问"
右声道是 = "客户"
单次音频上限秒 = 3600          # 一小时;再长多半是录音没停,转写要占住机器很久


def 声道数(wav):
    import wave
    with wave.open(wav) as w:
        return w.getnchannels()


def 规整(src, dst):
    """任意格式(m4a / mp3 / wav…)→ 16k 16 位 wav,**保留声道数**(双声道要留着分人)。
    用 macOS 自带的 afconvert —— 不装 ffmpeg。返回 (dst, 秒数)。"""
    r = subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", src, dst],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError(f"这个文件转不成 wav(是不是录音文件?):{(r.stderr or '')[-200:]}")
    import wave
    with wave.open(dst) as w:
        return dst, w.getnframes() / float(w.getframerate())


def 拆声道(wav):
    """双声道 → 左、右两个单声道 wav。纯标准库(wave + array),不装 ffmpeg。"""
    import wave, array as _a
    with wave.open(wav) as w:
        if w.getnchannels() != 2 or w.getsampwidth() != 2:
            raise ValueError("只拆 16 位双声道")
        率 = w.getframerate(); 数 = _a.array("h", w.readframes(w.getnframes()))
    出 = []
    for 边, 名 in ((0, "L"), (1, "R")):
        p = wav[:-4] + f".{名}.wav"
        with wave.open(p, "w") as o:
            o.setnchannels(1); o.setsampwidth(2); o.setframerate(率); o.writeframes(数[边::2].tobytes())
        出.append(p)
    return 出


# 切轮次的技术参数(只报不问,用户看不到):
帧毫秒 = 30            # 每 30ms 量一次两边的音量
静音比 = 0.06          # 低于「整通响度的高位」的 6% 算没人说话
压过倍数 = 1.5         # 一边要比另一边响 1.5 倍才算是它在说(真实电话会串音:客户的声音漏进顾问那一路)
并入毫秒 = 400         # 同一个人中间停不到 0.4 秒,算同一轮
最短毫秒 = 300         # 短于 0.3 秒的一轮丢掉(咳嗽、按键音)


def 按声道切轮次(wav):
    """双声道 → [(起始毫秒, 结束毫秒, "0"左 / "1"右)]。**按哪一边更响定谁在说**,不靠 whisper 切段。"""
    import wave, array as _a
    with wave.open(wav) as w:
        率 = w.getframerate(); 数 = _a.array("h", w.readframes(w.getnframes()))
    步 = 率 * 帧毫秒 // 1000
    L, R = 数[0::2], 数[1::2]
    能 = []
    for k in range(0, len(L) - 步 + 1, 步):
        能.append((sum(abs(x) for x in L[k:k + 步]) / 步, sum(abs(x) for x in R[k:k + 步]) / 步))
    if not 能:
        return []
    高 = sorted(max(a, b) for a, b in 能)[int(len(能) * 0.95)] or 1
    标 = []
    for a, b in 能:
        if max(a, b) < 高 * 静音比:
            标.append(None)
        elif a >= b * 压过倍数:
            标.append("0")
        elif b >= a * 压过倍数:
            标.append("1")
        else:
            标.append("?")
    轮 = []
    for k, x in enumerate(标):
        if x is None:
            continue
        起, 止 = k * 帧毫秒, (k + 1) * 帧毫秒
        if 轮 and 轮[-1][2] == x and 起 - 轮[-1][1] <= 并入毫秒:
            轮[-1][1] = 止
        else:
            轮.append([起, 止, x])
    return [tuple(t) for t in 轮 if t[1] - t[0] >= 最短毫秒]


def 转写分段(wav, 双声道, model=默认模型, 用热词=True, timeout=1800):
    """返回 [(起始毫秒, 文本, 说话人或 None)]。双声道时说话人是 "0"(左)/"1"(右)/"?"。

    双声道**先按两边音量切成一轮一轮,再逐轮转写**。试过两种不行的(10-03 合成录音实测):
      · whisper 自带 `-di`:先切段再按段标人,而它切段**不管换人**,「特别仙气儿。」(顾问)和
        「仙气儿,听着就不错」(客户)被切进同一段,那一段怎么标都错一半
      · 拆成左右两条各转再按时间合:人全标对了,但单条声道里大段静音,whisper 的时间戳会乱
        (客户 5.6 秒说的话标成 0 秒),合回去**顺序错了**
    按音量切轮次:每一轮只有一个人,起止时间是自己量的,不靠 whisper。
    """
    if 双声道:
        import wave, array as _a
        with wave.open(wav) as w:
            率 = w.getframerate(); 数 = _a.array("h", w.readframes(w.getnframes()))
        出 = []
        for k, (起, 止, 谁) in enumerate(按声道切轮次(wav)):
            边 = 数[(0 if 谁 != "1" else 1)::2][起 * 率 // 1000: 止 * 率 // 1000]
            p = wav[:-4] + f".t{k}.wav"
            with wave.open(p, "w") as o:
                o.setnchannels(1); o.setsampwidth(2); o.setframerate(率); o.writeframes(边.tobytes())
            文 = "".join(t for _, t, _ in _转写一条(p, model, 用热词, timeout))
            for f in (p, p[:-4] + ".seg.json"):
                os.path.exists(f) and os.remove(f)
            if 文:
                出.append((起, 文, 谁))
        return 出
    return _转写一条(wav, model, 用热词, timeout)


def _转写一条(wav, model, 用热词, timeout):
    ok, 缺 = 可用()
    if not ok:
        raise RuntimeError("ASR 环境不全:" + ";".join(缺))
    out = wav[:-4] + ".seg"
    cmd = [可执行, "-m", os.path.join(模型目录, model), "-f", wav, "-l", "zh", "-oj", "-of", out]
    if 用热词 and 提示词():
        cmd += ["--prompt", 提示词()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(out + ".json"):
        raise RuntimeError(f"转写失败(退出码 {r.returncode}):{(r.stderr or '')[-300:]}")
    import json as _js
    with open(out + ".json", encoding="utf-8") as f:
        段 = _js.load(f).get("transcription") or []
    return [(x["offsets"]["from"], (x.get("text") or "").strip(), None)
            for x in 段 if (x.get("text") or "").strip()]


def 按声道成行(段们):
    """双声道:speaker 0 → 左声道是,1 → 右声道是,其余 → 未分。返回 [(谁, 文本)]。"""
    映 = {"0": 左声道是, "1": 右声道是}
    return [(映.get(str(spk), "未分"), t) for _, t, spk in 段们]


模型分人提示 = ("下面是汉服门店顾问和客户的一段对话录音转写,逐行编了号,但没有标说话人。"
              "顾问是店里的人:介绍商品、问需求、报价、约时间;客户是来买东西的人。"
              "输出一个 JSON 数组,每一行对应一个元素:整行是一个人说的,就写 \"顾问\" 或 \"客户\";"
              "**一行里混了两个人的话**,就把这一行拆开,写成 [[\"客户\",\"前半句\"],[\"顾问\",\"后半句\"]],"
              "拆出来的几段按顺序拼起来必须和原行一字不差。数组长度必须和行数一致。只输出 JSON。")


def 模型分人(段们, call=None):
    """单声道:交给模型按内容分。返回 ([(谁, 文本)], 分人方式)。

    **模型没跑通、或答的形状不对 → 整通标「未分」**,不猜、不部分采纳:
    「模型说是客户」和「我们替它补了一个客户」在逐字稿里长得一模一样。
    `call` 可以注入假的调用(检查里用),默认走 agent/v1.call(记录仪自动接上)。
    """
    import json as _js
    行 = "\n".join(f"{i + 1}. {t}" for i, (_, t, _) in enumerate(段们))
    try:
        if call is None:
            import sys as _sys
            _sys.path.insert(0, os.path.join(HERE, "..", "agent"))
            import v1
            pv = v1.provider()
            r = v1.call(pv, dict(model=pv["model"], max_tokens=300 + 12 * len(段们), system=模型分人提示,
                                 messages=[{"role": "user", "content": 行}]),
                        purpose="录音转写·单声道分说话人", gen="工具")
        else:
            r = call(行)
        t = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        m = re.search(r"\[.*\]", t, re.S)
        标 = _js.loads(m.group(0)) if m else None
    except Exception as e:
        return [("未分", t) for _, t, _ in 段们], f"未分(模型没跑通:{type(e).__name__})"
    if not isinstance(标, list) or len(标) != len(段们):
        return [("未分", t) for _, t, _ in 段们], "未分(模型答的形状不对)"
    规 = lambda x: re.sub(r"[\s,。!?;:、,.!?;:…]", "", x or "")
    出 = []
    for x, (_, t, _) in zip(标, 段们):
        if x in ("顾问", "客户"):
            出.append((x, t))
        elif (isinstance(x, list) and x and all(isinstance(y, list) and len(y) == 2 and y[0] in ("顾问", "客户")
                                              for y in x)
              and 规("".join(str(y[1]) for y in x)) == 规(t)):
            # 一行混了两个人(whisper 切段不管换人)—— 拆开的几段**拼回去和原行一字不差**才收
            出 += [(y[0], str(y[1])) for y in x]
        else:
            出.append(("未分", t))       # 这一行拆得对不上原文:只这一行不收,别的行照收
    if all(w == "未分" for w, _ in 出):
        return 出, "未分(模型一行都没标对)"
    return 出, "模型"


def 成稿(行们):
    """[(谁, 文本)] → 「顾问:……\n客户:……」。相邻同一个人的段并成一行(whisper 会把一句话切成几段)。"""
    出 = []
    for 谁, t in 行们:
        if 出 and 出[-1][0] == 谁:
            出[-1] = (谁, 出[-1][1] + t)
        else:
            出.append((谁, t))
    return "\n".join(f"{谁}:{t}" for 谁, t in 出)


def 纠错词表():
    """同音纠错能改成的词:和热词同六类,**不受热词字数上限截断**(热词要塞进 whisper 的提示,纠错不用)。"""
    old = 热词字数上限
    try:
        globals()["热词字数上限"] = 10 ** 6
        return 行业词()
    finally:
        globals()["热词字数上限"] = old


同音纠错提示 = ("下面是语音识别出来的汉服门店通话稿。行业词常被听成同音字(比如「缂丝」写成「克斯」)。"
              "只找出**读音和下面某个行业词相同或几乎相同、但字写错了**的地方,别的一个字都不要动。"
              "输出 JSON 数组:[{\"原\":\"稿子里的写法\",\"改\":\"行业词\",\"原读音\":\"拼音\",\"改读音\":\"拼音\"}],"
              "读音写不带声调的拼音、音节之间空格隔开;没有就输出 []。\n行业词:")


def _读音(p):
    """去声调、去空格、小写 —— 「kè sī」「ke4 si1」「Ke Si」都算 kesi。"""
    import unicodedata
    p = unicodedata.normalize("NFD", str(p or ""))
    return re.sub(r"[^a-z]", "", "".join(ch for ch in p if not unicodedata.combining(ch)).lower().replace("ü", "v"))


def 同音纠错(稿, call=None, 词表=None):
    """模型指出「哪几个字是某个行业词的同音错写」,**改不改由规则把关**(用户 10-03 定的 A 案):

        改成的词必须在词表里 · 字数和原写法一样 · 原写法真在稿子里 · 两者不同

    不过闸的一条都不改,记进「拒」—— 实测拦下过「装种 → 装逼」「接栏 → 接缘」(都不是行业词)。
    返回 (新稿, 收 [(原, 改)], 拒 [(原, 改, 为什么)])。**模型没跑通就抛**,由调用方决定怎么落。
    """
    import json as _js
    词表 = 词表 or 纠错词表()
    全 = set(词表)
    if call is None:
        import sys as _sys
        _sys.path.insert(0, os.path.join(HERE, "..", "agent"))
        import v1
        pv = v1.provider()
        r = v1.call(pv, dict(model=pv["model"], max_tokens=600,
                             system=同音纠错提示 + "、".join(sorted(全, key=len, reverse=True)),
                             messages=[{"role": "user", "content": 稿}]),
                    purpose="录音转写·同音纠错", gen="工具")
    else:
        r = call(稿)
    t = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    m = re.search(r"\[.*\]", t, re.S)
    建议 = _js.loads(m.group(0)) if m else []
    收, 拒 = [], []
    for x in 建议 if isinstance(建议, list) else []:
        o, n = (x.get("原") or "", x.get("改") or "") if isinstance(x, dict) else ("", "")
        if n not in 全:
            拒.append((o, n, "改成的不是行业词"))
        elif not o or o not in 稿:
            拒.append((o, n, "稿子里没有这个写法"))
        elif len(o) != len(n):
            拒.append((o, n, "字数不一样(同音错写字数不会变)"))
        elif _读音(x.get("原读音")) != _读音(x.get("改读音")) or not _读音(x.get("原读音")):
            # 真跑见过「接栏 → 镶边」:意思相近、读音完全不同,前三道闸全过。读音是模型自己报的,
            # 没法独立核对 —— 但它挡得住「按意思改」这一类(要它先承认两边读音一样)
            拒.append((o, n, f"读音对不上({x.get('原读音')} / {x.get('改读音')})"))
        elif o == n:
            continue
        elif (o, n) not in 收:
            收.append((o, n))
    for o, n in 收:
        稿 = 稿.replace(o, n)
    return 稿, 收, 拒


def 处理(audio_id, db=None, call=None, 转写=None, 纠错call=None):
    """一通录音从「排队」走到「完成 / 失败」。**任何一步失败都落「失败 + 原因」**,不留在「转写中」:
    「还在转」和「早就崩了」在页面上长得一模一样。`转写` 可注入假的转写函数(检查里用)。"""
    db = db or DB
    转写 = 转写 or 转写分段
    with sqlite3.connect(db) as c:
        建表(c)
        r = c.execute("SELECT path, customer_id FROM call_audio WHERE id=?", (audio_id,)).fetchone()
        if not r:
            return False, f"没有录音 {audio_id}"
        c.execute("UPDATE call_audio SET status='转写中', fail_reason=NULL WHERE id=?", (audio_id,))
    path = r[0]
    try:
        双 = 声道数(path) == 2
        t0 = time.time()
        段们 = 转写(path, 双)
        用时 = time.time() - t0
        if not 段们:
            raise RuntimeError("转出来是空的 —— 录音里没有人声,或者文件坏了")
        if 双:
            行们 = 按声道成行(段们)
            方式 = "声道" if any(w != "未分" for w, _ in 行们) else "未分(声道分不清)"
        else:
            行们, 方式 = 模型分人(段们, call=call)
        原稿 = 成稿(行们)
        # 同音纠错:**失败不算转写失败** —— 原稿照样落,fixes 里写清「没纠」,不然和「纠过、没有要改的」长得一样
        try:
            文本, 收, 拒 = 同音纠错(原稿, call=纠错call)
            import json as _js
            改记 = _js.dumps({"改": 收, "拒": 拒}, ensure_ascii=False)
        except Exception as e:
            文本, 改记 = 原稿, f'{{"没纠": "{type(e).__name__}"}}'
        import simplified
        繁 = "".join(simplified.繁体字(文本))
        today = datetime.date.today().isoformat()
        with sqlite3.connect(db) as c:
            c.execute("""insert into call_transcript(audio_id,text,engine,model,hotwords,cost_sec,trad,created,
                                                     speaker_src,raw_text,fixes)
                         values(?,?,?,?,?,?,?,?,?,?,?)
                         on conflict(audio_id) do update set text=excluded.text, model=excluded.model,
                           hotwords=excluded.hotwords, cost_sec=excluded.cost_sec, trad=excluded.trad,
                           speaker_src=excluded.speaker_src, raw_text=excluded.raw_text, fixes=excluded.fixes""",
                      (audio_id, 文本, "whisper.cpp", 默认模型, 1, 用时, 繁 or None, today, 方式, 原稿, 改记))
            c.execute("UPDATE call_audio SET status='完成' WHERE id=?", (audio_id,))
        # 挂商机:规则层判一遍,是就建「待确认」。**这一步失败不算转写失败** —— 逐字稿已经在了,
        # 商机可以事后再判;但要留痕,不然「没判出商机」和「判的时候崩了」长得一样
        try:
            import sys as _sys
            _sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
            import opportunity_store as _os
            with sqlite3.connect(db) as c:
                _os.建表(c)
                _os.从转写建(c, audio_id)
        except Exception as e:
            with sqlite3.connect(db) as c:
                c.execute("UPDATE call_audio SET fail_reason=? WHERE id=?",
                          (f"转写完成,但判商机时出错:{type(e).__name__}: {e}"[:300], audio_id))
        return True, 方式
    except Exception as e:
        with sqlite3.connect(db) as c:
            c.execute("UPDATE call_audio SET status='失败', fail_reason=? WHERE id=?",
                      (f"{type(e).__name__}: {e}"[:300], audio_id))
        return False, str(e)


if __name__ == "__main__":
    ok, 缺 = 可用()
    print("ASR 环境:", "✅ 齐了" if ok else "❌ " + ";".join(缺))
    ws = 行业词()
    print(f"行业热词 {len(ws)} 个:{'、'.join(ws[:12])}…")
