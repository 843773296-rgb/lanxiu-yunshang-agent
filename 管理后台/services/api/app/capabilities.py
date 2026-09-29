# -*- coding: utf-8 -*-
"""工具 / 连接 / 指南 / 规则的闸(规格 §11、§16.3)。纯逻辑。

## ⚠️ 一、风险变大必须出新版本

规格 §16.3 的原话值得一字不改地抄:

> 一个工具从**只读**变成**会写东西**,而引用它的 Agent 还指着老的说明 ——
> **那份说明现在是错的**。

所以判的不是「有没有改」,是「**风险有没有变大**」:
`只读 → 写入 → 不可逆` 这条线上往右走,就必须出新版本,
而往左走(收紧)不强制 —— 收紧不会让老说明变错。

## ⚠️ 二、白名单,不是黑名单

两处都用白名单:
- **指南的文件**:只收 Markdown 和只读参考(§11.3「不执行上传脚本」)
- **规则策略**:只收登记过的模板 + 参数(§11.4「不开放任意代码」)

黑名单在这里必输 —— 「哪些后缀算可执行」是个**无限集合**,
而这个仓库已经为「枚举必输」栽过七次(中文否定那一族)。
白名单反过来:**没登记的一律拒**,而登记这件事有人看着。

## ⚠️ 三、指南不授予权限

§11.3 / §16.3:「**启用了指南**」被读成「**给了脚本权限**」是这一块最容易出的误解。
所以指南这条链上**没有任何地方能写权限** —— 不是靠判据拦,是**根本没有那个字段**。
"""
import hashlib
import json as _json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
import dsl as DSL

# 风险从低到高。**顺序就是判据** —— 往右走要出新版本,往左走不强制。
风险梯 = (DSL.只读, DSL.写入, DSL.不可逆)
风险中文 = {DSL.只读: "只读", DSL.写入: "写入", DSL.不可逆: "不可逆"}

# 指南只收这些 —— **白名单**。§11.3:首版只收 Markdown 指南和只读参考文件。
指南允许的后缀 = (".md", ".markdown", ".txt", ".json", ".csv",
              ".png", ".jpg", ".jpeg", ".svg", ".pdf")

# 规则策略的模板白名单(首版)。§11.4:只开白名单模板 + 配置参数,不开放任意代码。
# ⚠️ 这四条是**首版**的,加一条要走登记 —— 而不是让人在界面上写代码。
规则模板 = {
    "禁止工具": "某个工具在这个触发点一律不许调用(**程序强制**,不是提示词里的约定)",
    "必须确认": "命中的调用要先拿到人工批准才放行",
    "参数白名单": "某个参数只允许登记过的取值",
    "频率上限": "同一个对象在窗口内最多调用几次",
}
触发点 = ("调用前", "调用后", "运行开始", "运行结束")
失败策略 = ("拦住", "放行并记一条", "升级给人")


def 风险变大了吗(老, 新):
    """`只读 → 写入 → 不可逆` 往右走 = 风险变大。认不出的一律当成变大。

    ⚠️ **认不出就当变大**,不是当成没变 —— 判据在拿不准的时候
    该往「多出一个版本」那边偏:多一版的代价是有人多点一下,
    少一版的代价是**引用它的 Agent 指着一份现在是错的说明**。
    """
    try:
        return 风险梯.index(新) > 风险梯.index(老)
    except ValueError:
        return True


def 可以冻结工具吗(*, 定义, 草稿, 上一版):
    """能不能把这个工具草稿冻成新版本。返回问题清单(空 = 可以)。"""
    问 = []
    if not (草稿.get("model_description") or "").strip():
        问.append("**给模型看的说明没写**(`model_description`)—— "
                  "模型靠它决定要不要调这个工具;没有它,它只能靠工具名猜")
    if 草稿.get("side_effect_type") not in 风险梯:
        问.append(f"副作用类型只收 {list(风险梯)},拿到 "
                  f"{草稿.get('side_effect_type')!r}")
    else:
        # ⚠️ 第一版写的是 `if hasattr(DSL, "找副作用") else None` —— 而那个函数
        # 当时**根本不存在**,于是这条判据从写下那一刻起就是空跑的,
        # 而输出上和「判过了没问题」长得一模一样。已经把那个访问器补进 dsl。
        级 = DSL.找副作用(草稿["side_effect_type"])
        if 级.get("需幂等") and not (草稿.get("idempotency_strategy") or "").strip():
            问.append(f"**{风险中文[草稿['side_effect_type']]}的工具要写幂等策略** —— "
                      f"超时重发是常态,而没有幂等策略的重发会把同一件事做两遍")
    if not isinstance(草稿.get("input_schema"), (dict, list)) or not 草稿.get("input_schema"):
        问.append("**入参 schema 没给** —— 没有它,「模型传错了参数」和"
                  "「工具本来就该这么用」在调用失败那一刻分不出来")
    # ⚠️ 不允许从接口提交任意执行代码(§17.1)
    代码 = 找出像代码的字段(草稿)
    if 代码:
        问.append(f"这些字段里像是塞了可执行代码:{代码} —— "
                  f"**接口不收任意执行代码**(§17.1)。工具的行为由适配器实现,"
                  f"这里只登记「它是什么、怎么调、风险多大」")
    if 上一版 and 风险变大了吗(上一版.get("side_effect_type"), 草稿.get("side_effect_type")):
        # 这不是错 —— 这正是**必须出新版本**的那种情况。提示要说清它是好事。
        pass
    return 问


_像代码 = re.compile(r"(?:\bimport\s+\w|\bdef\s+\w+\s*\(|\brequire\s*\(|"
                  r"\bsubprocess\b|\beval\s*\(|\bexec\s*\(|#!/)", re.I)


def 找出像代码的字段(d, 前缀=""):
    """返回**字段名**清单。⚠️ 只报名字,不报内容 —— 报内容等于把它再存一遍。"""
    出 = []
    if isinstance(d, dict):
        for k, v in d.items():
            路 = f"{前缀}.{k}" if 前缀 else str(k)
            if isinstance(v, str) and _像代码.search(v):
                出.append(路)
            else:
                出 += 找出像代码的字段(v, 路)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            出 += 找出像代码的字段(v, f"{前缀}[{i}]")
    return sorted(set(出))


def 可以建指南吗(*, 名字, 指令, 文件清单):
    """§11.3:**首版只收 Markdown 指南和只读参考文件,不执行上传脚本**。"""
    问 = []
    if not (名字 or "").strip():
        问.append("名字必填")
    if not (指令 or "").strip():
        问.append("**指南正文没写** —— 一份空指南挂上去,界面上和一份写好的"
                  "长得一样(都显示「已挂载」)")
    坏 = []
    for f in (文件清单 or []):
        名 = f if isinstance(f, str) else (f.get("path") or f.get("name") or "")
        后 = os.path.splitext(str(名))[1].lower()
        if 后 not in 指南允许的后缀:
            坏.append(名)
    if 坏:
        问.append(f"这些文件不在白名单里:{坏} —— **只收 Markdown 指南和只读参考**"
                  f"({', '.join(指南允许的后缀)})。"
                  f"⚠️ 用白名单不用黑名单:「哪些后缀算可执行」是个无限集合")
    代码 = 找出像代码的字段({"指令": 指令})
    if 代码:
        问.append("指南正文里像是有可执行代码 —— **指南不执行**(§11.3);"
                  "而且**指南不授予权限**:模型请求加载一份指南,不该扩张它的工具权限")
    return 问


def 可以建规则吗(*, 名字, 模板, 参数, 触发, 失败时):
    """§11.4:**白名单规则模板 + 配置参数,不开放任意代码**。"""
    问 = []
    if not (名字 or "").strip():
        问.append("名字必填")
    if 模板 not in 规则模板:
        问.append(f"规则模板只收登记过的:{list(规则模板)} —— "
                  f"**不开放任意代码**(§11.4)。要新模板就登记一个,"
                  f"而不是在界面上写代码")
    if 触发 not in 触发点:
        问.append(f"触发点只收 {list(触发点)},拿到 {触发!r}")
    if 失败时 not in 失败策略:
        问.append(f"命中之后怎么办只收 {list(失败策略)},拿到 {失败时!r}")
    if not isinstance(参数, dict):
        问.append("参数要是一个对象")
    else:
        代码 = 找出像代码的字段(参数)
        if 代码:
            问.append(f"参数里像是塞了可执行代码:{代码} —— 参数只放**配置**")
    return 问


def 内容哈希(d):
    return hashlib.sha256(_json.dumps(d, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]
