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
def 行业词(limit=60):
    words = []
    try:
        with sqlite3.connect(DB) as c:
            words += [r[0] for r in c.execute("select name from xingzhi limit 40")]
            words += [r[0] for r in c.execute("select name from craft limit 30")]
            words += [r[0] for r in c.execute(
                "select distinct color from sku where color not in ('定制','素') limit 25")]
    except sqlite3.Error:
        pass
    seen, out = set(), []
    for w in words:
        w = (w or "").strip()
        if w and w not in seen and len(w) <= 8:
            seen.add(w); out.append(w)
    return out[:limit]


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


if __name__ == "__main__":
    ok, 缺 = 可用()
    print("ASR 环境:", "✅ 齐了" if ok else "❌ " + ";".join(缺))
    ws = 行业词()
    print(f"行业热词 {len(ws)} 个:{'、'.join(ws[:12])}…")
