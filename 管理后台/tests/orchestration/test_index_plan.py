#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""索引构建的计划(规格 §19.3)—— **判据全冲着「安静失败」去**。

## 为什么这一组测试的形状和别处不同

索引构建的坏法几乎没有一个是抛异常的。它们都长成这样:
构建报成功、界面全绿、检索能跑,**只是答得不对**。

  · 跳过一个没有向量的片段 → 那段知识在检索里凭空消失
  · 在输入变过的构建上续做 → 一半旧边界一半新边界
  · `final_chunk_limit` 比 `candidate_k` 大 → 永远挑不满,像是「库里就这么点」

所以这些判据不能靠「跑一遍看有没有炸」。每一条都要**构造一个
长得像成功的坏局面**,然后要求计划器指出来。

## 咬合在这一组里尤其重要

这些函数全是纯逻辑,想让它们「通过」太容易了 ——
`已经做完的()` 只要不检查 `embedding_id`,所有测试照样绿,
而它正好丢掉了这个文件最主要的作用。
所以每条核心判据都配一条咬合:**把那行检查删掉,判据必须变红**。
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "knowledge"))
import index_plan as P  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{'  ' + str(补)[:180] if 补 else ''}")
    (过 if 真 else 挂).append(名)


def _抛(f, 类):
    try:
        f()
    except 类:
        return True
    except Exception as e:
        print(f"     (抛的是 {type(e).__name__},要的是 {类.__name__})")
        return False
    return False


基础 = dict(知识库id="kb1", 文档版本id们=["dv1", "dv2"], 检索配置版本id="rc1",
          embedding模型id="emb-m", embedding维度=1536,
          切片器版本="seg-1", 解析器版本="md-1")

print("▸ ① 输入指纹:**变了要变,没变不许变**")


def 判_顺序无关():
    a = P.输入指纹(**{**基础, "文档版本id们": ["dv1", "dv2"]})
    b = P.输入指纹(**{**基础, "文档版本id们": ["dv2", "dv1"]})
    return a == b


def 判_切片器版本进指纹():
    """⚠️ **这一条是整个文件里最容易被省掉的。**
    文档没变、配置没变,只有 chunker 的合并规则改了 —— 边界跟着变。
    指纹不含它,续做就产出混血索引,而混血索引**不报错**。"""
    return P.输入指纹(**基础) != P.输入指纹(**{**基础, "切片器版本": "seg-2"})


def 判_解析器版本进指纹():
    return P.输入指纹(**基础) != P.输入指纹(**{**基础, "解析器版本": "md-2"})


def 判_维度进指纹():
    return P.输入指纹(**基础) != P.输入指纹(**{**基础, "embedding维度": 768})


ck("文档版本的**顺序**不改变指纹(它是集合)", 判_顺序无关())
ck("**切片器版本变了,指纹必须变** —— 否则续做会得到一半旧一半新的边界",
   判_切片器版本进指纹())
ck("解析器版本变了,指纹必须变", 判_解析器版本进指纹())
ck("Embedding 维度变了,指纹必须变", 判_维度进指纹())
ck("缺字段直接抛,**不给默认值**(默认值会让两批不同输入撞出同一个指纹)",
   _抛(lambda: P.输入指纹(知识库id="kb1"), P.输入不全))
ck("传了指纹字段之外的东西也抛(它要么是输入要么不是,不能含糊)",
   _抛(lambda: P.输入指纹(**{**基础, "顺手加的": 1}), P.输入不全))
ck("`文档版本id们` 里有重复 → 抛(同一份文档会被切两遍,在检索里占两个名额)",
   _抛(lambda: P.输入指纹(**{**基础, "文档版本id们": ["dv1", "dv1"]}), P.输入不全))

print("\n▸ ② 检查点:**登记不是完成**")
成员们 = [
    dict(chunk_id="c1", embedding_id="e1", embedding维度=1536),   # 真做完了
    dict(chunk_id="c2", embedding_id=None, embedding维度=None),   # 登记了,没向量
    dict(chunk_id="c3", embedding_id="e3", embedding维度=768),    # 维度不对
]


def 判_空向量要重做():
    好, 坏 = P.已经做完的(成员们, 期望维度=1536)
    return "c2" not in 好 and any(c == "c2" for c, _ in 坏)


def 判_维度不对要重做():
    好, 坏 = P.已经做完的(成员们, 期望维度=1536)
    return "c3" not in 好 and any(c == "c3" for c, _ in 坏)


ck("`embedding_id` 是空的 → **算没做完**"
   "(算做完就会跳过它,那段知识在检索里永远不命中,而构建报成功)",
   判_空向量要重做())
ck("向量维度和构建声明的不一样 → 算没做完(混维度的距离算出来没有意义)",
   判_维度不对要重做())
好, 坏 = P.已经做完的(成员们, 期望维度=1536)
ck("真做完的那一条被认出来了", 好 == {"c1"}, 好)
ck("三档分开报:做完 / 没向量 / 维度不对,**各自给了为什么**",
   len(坏) == 2 and all(理由.strip() for _, 理由 in 坏), [r[:40] for _, r in 坏])

print("\n▸ ③ 算待做:已完成的跳过,坏的重做")
目标 = [dict(id=f"c{i}", text_hash=f"h{i}") for i in (1, 2, 3, 4)]
r = P.算待做(目标片段们=目标, 成员们=成员们, 期望维度=1536)
ck("c1 做完了 → 不在待做里", "c1" not in [c["id"] for c in r["待做"]], r["已完成"])
ck("c2(没向量)和 c3(维度不对)**回到待做**",
   {"c2", "c3"} <= {c["id"] for c in r["待做"]}, [c["id"] for c in r["待做"]])
ck("从没做过的 c4 在待做里", "c4" in {c["id"] for c in r["待做"]})
ck("目标片段有重复 id → 抛",
   _抛(lambda: P.算待做(目标片段们=目标 + [目标[0]], 成员们=[], 期望维度=1536), ValueError))

print("\n▸ ④ 指纹自己的体检:索引里有不属于这一版输入的片段")
r2 = P.算待做(目标片段们=目标[:2], 成员们=成员们, 期望维度=1536)
ck("成员里有、目标里没有的片段 → **报「指纹漏了一项」**"
   "(同一个构建的输入本该固定,能变说明指纹没覆盖到某个真实输入)",
   r2["陈旧成员"] == ["c3"] and "指纹漏了一项" in r2["指纹体检"], r2["指纹体检"][:70])
ck("没有陈旧片段时体检说「通过」,不含糊", r["指纹体检"] == "通过", r["指纹体检"])

print("\n▸ ⑤ 续做还是新建(§19.3「输入版本变化则创建新构建」)")
现 = P.输入指纹(**基础)
ck("输入没变 + 还在跑 → 续做",
   P.该新建还是续做(构建=dict(输入指纹=现, status="running"), 现在的指纹=现)[0] == "续做")
ck("**输入变了 → 新建**(续做的结果不报错,只是答得怪)",
   P.该新建还是续做(构建=dict(输入指纹="plan-1:别的", status="running"),
                 现在的指纹=现)[0] == "新建")
ck("**老构建没记指纹 → 新建**(「没记」不是「一样」——"
   "放它续做正好放过了要防的那件事)",
   P.该新建还是续做(构建=dict(输入指纹=None, status="running"), 现在的指纹=现)[0] == "新建")
for st in ("succeeded", "failed", "cancelled"):
    ck(f"已经是终态({st})→ 新建(终态的结果可能已被当结论用过)",
       P.该新建还是续做(构建=dict(输入指纹=现, status=st), 现在的指纹=现)[0] == "新建")
ck("每个结论都带一句为什么",
   all((P.该新建还是续做(构建=b, 现在的指纹=现)[1] or "").strip()
       for b in (None, dict(输入指纹=现, status="running"),
                 dict(输入指纹="x", status="running"))))

print("\n▸ ⑥ 检索配置:**从 20 个里挑 50 个永远挑不满,而它不报错**")
好配置 = dict(candidate_k=50, final_chunk_limit=8, recall_modes=["vector"],
            context_budget_tokens=4000)
ck("一份合理配置 → 没问题", P.校验检索配置(好配置) == [], P.校验检索配置(好配置))


def 判_最终数不超候选():
    问 = P.校验检索配置({**好配置, "candidate_k": 20, "final_chunk_limit": 50})
    return any("永远挑不满" in x for x in 问)


ck("`final_chunk_limit` > `candidate_k` → 报出来"
   "(不报的话,人会以为「知识库里就这么点东西」)", 判_最终数不超候选())
ck("`candidate_k` 是 0 → 报(检索永远返回空,而界面上只是「没搜到」)",
   P.校验检索配置({**好配置, "candidate_k": 0}) != [])
ck("`candidate_k` 传 True → 报(`isinstance(True, int)` 为真,要单独排掉)",
   any("不是整数" in x for x in P.校验检索配置({**好配置, "candidate_k": True})))
ck("`recall_modes` 空 → 报(一个召回都不开,必然返回空)",
   P.校验检索配置({**好配置, "recall_modes": []}) != [])
ck("开了 hybrid 却没配 fusion → 报"
   "(两路怎么合并没说,会退化成某一路说了算,而是哪一路取决于实现细节)",
   any("fusion" in x for x in P.校验检索配置({**好配置, "recall_modes": ["hybrid"]})))
ck("上下文预算装不下要的片段数 → 报(到时候会静默截断,"
   "被截掉的和没检索到长得一样)",
   any("静默截断" in x for x in
       P.校验检索配置({**好配置, "final_chunk_limit": 8, "context_budget_tokens": 50})))

# ── 咬合:把那行检查删掉,判据必须变红 ─────────────────────────────
# ⚠️ **这一组比上面任何一条都重要。** 上面的判据全是纯逻辑,
# 让它们「通过」太容易了 —— `已经做完的()` 只要不看 `embedding_id`,
# 上面照样绿,而它正好丢掉了这个文件最主要的作用。
print("\n▸ 咬合:改坏了要红\n" + "-" * 78)
咬过 = []


def 咬(名, 改坏, 恢复, 判据):
    改坏()
    try:
        红 = not 判据()          # 判据不成立 = 咬到了
    except Exception:
        红 = True               # 抛了也算红(它同样不会静默放过)
    finally:
        恢复()
    咬过.append(红)
    print(f"  {'✅' if 红 else '❌'} 咬合「{名}」→ {'判据红了' if 红 else '**判据还是绿的**'}")


_原指纹字段 = P._指纹字段
咬("把「切片器版本」从指纹里拿掉",
  lambda: setattr(P, "_指纹字段", tuple(x for x in _原指纹字段 if x != "切片器版本")),
  lambda: setattr(P, "_指纹字段", _原指纹字段),
  判_切片器版本进指纹)
咬("把「解析器版本」从指纹里拿掉",
  lambda: setattr(P, "_指纹字段", tuple(x for x in _原指纹字段 if x != "解析器版本")),
  lambda: setattr(P, "_指纹字段", _原指纹字段),
  判_解析器版本进指纹)
_原输入指纹 = P.输入指纹
咬("指纹不按集合算(文档顺序改了指纹就变)——"
  "它会让每次重排都当成「输入变了」,白重建一遍",
  lambda: setattr(P, "输入指纹", lambda **kw: str(kw.get("文档版本id们"))),
  lambda: setattr(P, "输入指纹", _原输入指纹),
  判_顺序无关)

_原已完成 = P.已经做完的
咬("`已经做完的()` 不检查 `embedding_id`(拿「登记」当「完成」)",
  lambda: setattr(P, "已经做完的",
                  lambda 成员们, *, 期望维度: ({m["chunk_id"] for m in 成员们}, [])),
  lambda: setattr(P, "已经做完的", _原已完成),
  判_空向量要重做)
咬("`已经做完的()` 不检查维度(混维度的索引照收)",
  lambda: setattr(P, "已经做完的",
                  lambda 成员们, *, 期望维度: (
                      {m["chunk_id"] for m in 成员们 if m.get("embedding_id")}, [])),
  lambda: setattr(P, "已经做完的", _原已完成),
  判_维度不对要重做)

_原校验 = P.校验检索配置
咬("检索配置不比 `final_chunk_limit` 和 `candidate_k`",
  lambda: setattr(P, "校验检索配置", lambda cfg: []),
  lambda: setattr(P, "校验检索配置", _原校验),
  判_最终数不超候选)

_原该 = P.该新建还是续做
咬("「没记指纹」被当成「指纹一样」,放它续做",
  lambda: setattr(P, "该新建还是续做",
                  lambda *, 构建, 现在的指纹: ("续做", "指纹一样")),
  lambda: setattr(P, "该新建还是续做", _原该),
  lambda: P.该新建还是续做(构建=dict(输入指纹=None, status="running"),
                      现在的指纹=现)[0] == "新建")

print(f"\n{'✅' if all(咬过) else '❌'} 咬合 {sum(咬过)}/{len(咬过)} 条如预期")
if not all(咬过):
    挂.append("咬合有没咬住的")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
