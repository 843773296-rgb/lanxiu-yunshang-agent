# -*- coding: utf-8 -*-
"""造通话逐字稿:让商机判断有原料可读。

## 为什么要造

设计稿里沟通记录带 `.wav` 录音,而**没有任何文字内容字段** ——
客户说过什么,现在谁也读不到。库里逐字稿 0 条。
**在 0 条逐字稿上做商机判断,不管怎么判都是「没有商机」,而且全绿。**

## 为什么走模型而不是模板拼

业务要的是「拟人的虚拟信息」。模板拼出来的对话**没有真实对话的样子** ——
真人说话有口头禅、有停顿、说一半改口、答非所问、来回确认。
而商机判断恰恰要在这种噪音里找信号:**干净的模板句子会让判断显得比实际容易。**

## ⚠️ 生成一次,结果进版本库;重建时只是读文件

模型有随机性,而 `tools/determinism_check.py` 要求重建可复现。
所以这里是**一次性脚本**(人工跑),产物 `fakedata/transcripts.json` 进版本库;
`tools/backfill_transcript.py` 负责灌进库,那一步是确定性的。

## ⚠️ 真值不能只靠「我让它生成商机」

**「生成了商机信号」和「我以为生成了」长得一模一样。**
所以每条生成完要**校验**:剧本说这通电话提到了「红色」,
那转出来的文本里就得真的出现颜色词。校验不过的**丢掉重生**,不进数据集。

## 六类剧本,其中两类是对照

    颜色商机 / 场合商机 / 纹样工艺商机 / 版型商机     ← 正例
    纯服务(问物流、改时间、催工期)                  ← 负例:不该判成商机
    似是而非(「随便看看」「再想想」「帮朋友问的」)    ← **最要紧的一类**

最后一类测的是**误报**:客户说了些像偏好的话,但够不上商机。
只有正例的评测集,会让一个「见什么都说是商机」的实现拿满分。
"""
import json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
产物 = os.path.join(HERE, "transcripts.json")

剧本 = [
    ("颜色商机", True, "颜色",
     "客户明确说过想要某个颜色,但那次没买到/买了别的颜色。要出现具体色名或颜色词。"),
    ("场合商机", True, "场合",
     "客户提到将来某个场合要穿(婚礼/旅拍写真/节庆/正式场合),现在还没定下来。"),
    ("纹样工艺商机", True, "纹样工艺",
     "客户提到想要某种纹样或工艺(缠枝/云纹/盘金绣/缂丝/妆花),当时没有或没做成。"),
    ("版型商机", True, "版型",
     "客户提到想做某个形制(马面裙/齐胸襦裙/褙子/圆领袍/大袖衫),还在犹豫或没下单。"),
    ("纯服务", False, None,
     "纯粹的服务性通话:问物流到哪了、改预约时间、催工期、问售后怎么办。"
     "**不要出现任何未满足的购买意向**。"),
    ("似是而非", False, None,
     "客户说了些听起来像偏好、但够不上商机的话:「随便看看」「再想想」"
     "「帮朋友问问」「先不急」。**要像有意向,但实际上没有具体未满足的需求**。"),
]

SYSTEM = """你在为一家汉服定制门店造**通话逐字稿**样本,用来测试一个商机识别系统。

要求:
1. **像真人打电话**:有口头禅(「那个」「就是」「对对对」)、有停顿、有说一半改口、
   有来回确认、偶尔答非所问。不要写成书面对话。
2. 顾问和客户各有性格,不要每条都一样。
3. 长度 8-16 轮对话。
4. **一律用简体中文**(这家店的商品数据都是简体)。
5. 汉服术语要用对:马面裙、齐胸襦裙、褙子、圆领袍、大袖衫、妆花、缂丝、
   香云纱、盘金绣、缠枝纹、云肩、接襕。
6. 按给定剧本写,**剧本要求出现的信息必须真的出现在对话里**。

只输出 JSON 数组,每个元素:
{"客户称呼": "...", "逐字稿": "顾问:...\\n客户:...\\n..."}
不要输出任何别的文字。"""


def 校验(条, 剧本名, 是商机):
    """**生成了信号**和**我以为生成了**长得一样,所以这里真的去文本里查。"""
    t = 条.get("逐字稿", "")
    if len(t) < 120:
        return "太短,不像一通电话"
    if "顾问" not in t or "客户" not in t:
        return "没有说话人标记"
    import simplified
    繁 = simplified.繁体字(t)
    if 繁:
        return f"出现繁体字 {''.join(繁[:5])} —— 商品数据一律简体"
    if 剧本名 == "颜色商机":
        色 = ["红", "蓝", "绿", "黄", "紫", "黑", "白", "粉", "青", "藏青", "茜", "绛", "胭脂", "月白"]
        if not any(x in t for x in 色):
            return "剧本要颜色,文本里一个颜色词都没有"
    if 剧本名 == "版型商机":
        形 = ["马面裙", "襦裙", "褙子", "圆领袍", "大袖衫", "长衫", "袄", "道袍", "半臂"]
        if not any(x in t for x in 形):
            return "剧本要形制,文本里没有"
    if 剧本名 == "纹样工艺商机":
        纹 = ["缠枝", "云纹", "盘金", "缂丝", "妆花", "刺绣", "绣", "纹样", "织金"]
        if not any(x in t for x in 纹):
            return "剧本要纹样工艺,文本里没有"
    if 剧本名 == "场合商机":
        场 = ["婚礼", "旅拍", "写真", "节庆", "正式", "拍照", "喜宴", "过年", "毕业"]
        if not any(x in t for x in 场):
            return "剧本要场合,文本里没有"
    return None


def 生成一批(剧本名, 是商机, 维度, 说明, 条数=4, model=None):
    import v1
    pv = v1.provider()
    payload = {"剧本": 剧本名, "这一批要几条": 条数, "剧本说明": 说明,
               "提醒": "剧本要求出现的信息必须真的出现在对话里,否则这条会被丢掉"}
    resp = v1.call(pv, dict(model=model or pv["model"], max_tokens=8000, system=SYSTEM,
                            messages=[{"role": "user",
                                       "content": json.dumps(payload, ensure_ascii=False)}]),
                   purpose="假数据工厂·造通话逐字稿", gen="工具")
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    if resp.get("stop_reason") == "max_tokens":
        raise SystemExit("被 max_tokens 截断 —— 这不是格式问题,是配置不够")
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        print(f"  ⚠️ {剧本名}:模型没给出 JSON 数组 —— {text[:160]}")
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception as e:
        print(f"  ⚠️ {剧本名}:JSON 解析失败 {e}")
        return []

    好, 丢 = [], []
    for 条 in arr:
        why = 校验(条, 剧本名, 是商机)
        if why:
            丢.append((条.get("客户称呼", "?"), why)); continue
        好.append({"剧本": 剧本名, "是商机": 是商机, "维度": 维度,
                   "客户称呼": 条.get("客户称呼", ""), "逐字稿": 条["逐字稿"]})
    print(f"  {剧本名}: 收 {len(好)} 条,丢 {len(丢)} 条" +
          (f" —— 丢的原因:{丢[0][1]}" if 丢 else ""))
    return 好


def main():
    if os.environ.get("LANXIU_PROVIDER") != "claude":
        print("⚠️ 规矩:一律用 Claude(月租,不额外花钱)。请设 LANXIU_PROVIDER=claude")
        return 1
    条数 = int(os.environ.get("N", "4"))
    全部 = []
    for 剧本名, 是商机, 维度, 说明 in 剧本:
        全部 += 生成一批(剧本名, 是商机, 维度, 说明, 条数)
    if not 全部:
        print("❌ 一条都没生成出来"); return 1
    out = {"生成于": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "模型": os.environ.get("ANTHROPIC_MODEL", "(默认)"),
           "⚠️ 这是造的": "虚拟通话逐字稿,不是真实录音的转写。"
                        "**拿它测出来的商机识别率,不代表真实通话上的表现** —— "
                        "造的对话里信号比真实通话清楚。",
           "条目": 全部}
    json.dump(out, open(产物, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    正 = sum(1 for x in 全部 if x["是商机"])
    print(f"\n✅ {len(全部)} 条 → {产物}")
    print(f"   正例(是商机) {正} 条 · 负例 {len(全部)-正} 条")
    print(f"   ⚠️ **只有正例的评测集,会让「见什么都说是商机」的实现拿满分** —— 负例是对照。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
