#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""澜绣控制面:6 个旋钮 + 旋钮方案 + 导出(**库 → 文件,只改一个键**)。

## 这一份守的那句话

搬家说明(`已搬走.md`)留的第二条待办是「Agent 配置 → `agent/knobs.py`
的 6 个旋钮」,而 `knobs.py` 自己写了这件事最大的风险:

> 一个旋钮如果只存在于这张表和页面上,它就是个**滑块** ——
> 拖动它什么都不会变,而人会以为自己在调。

所以这一份最硬的两条是:
  · 接口**必须给出落点核对的结果**(这个旋钮是真的吗)
  · 落点核对不过时,**导出要拒绝** —— 导出一个滑块方案,
    跑出来的分数读起来完全合理,而它和「没套方案」是一回事

## ⚠️ 第二硬的一条:导出只改 `旋钮`,不碰 `验证`

方案文件装的不只是旋钮,还有 `改`(提示词改动)和
`验证`(跑过的评测:题数、过了几道、哪个模型、哪个提交)。
后台只管旋钮那一半。

> **一个只管一半的编辑器,在保存时会把另一半清掉** ——
> 而那在「保存成功」那一刻看不出来。

`验证` 尤其要紧:它**不可重建** —— 重跑一遍评测花钱,而且结果会漂。

## 这一份自己造方案、跑完自己清

⚠️ **不碰澜绣原有的那两份方案文件**(`TL53-更短` / `试-想多深high`)。
那是真数据,而且 `试-想多深high` 里有一条真实的评测记录。
验「导出不抹历史」用的是**自己造的一份带假 `验证` 的文件**。

⚠️ 前提 `make dev`,而且项目要是 `project_lanxiu`
(跑 `python3 tools/import_lanxiu_prompts.py` 建)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
sys.path.insert(0, os.path.dirname(_根))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_lanxiu"        # ⚠️ 这一份只对澜绣那个项目有意义
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []
尾 = uuid.uuid4().hex[:6]
我的方案 = f"测-旋钮{尾}"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U001", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务                     # noqa: E402
from agent import knobs as K           # noqa: E402


def 清掉():
    with 事务() as c:
        c.execute(text("delete from knob_plans where project_id=:p and key like :n"),
                  {"p": 项目, "n": f"测-旋钮{尾}%"})
    for 号 in (我的方案, f"{我的方案}-带历史"):
        f = os.path.join(K.目录, f"{号}.json")
        if os.path.exists(f):
            os.remove(f)


def main():
    print("\n\033[1m▸ 澜绣控制面 · 旋钮不许是滑块\033[0m")

    # ── 一、旋钮定义:现读 + 落点核对 ─────────────────────────────
    print("\n▸ 一、有哪些旋钮,**而且它们真的接上了吗**")
    码, d = 打("GET", f"{P}/lanxiu-knobs")
    ck("GET /lanxiu-knobs 200", 码 == 200, 码)
    项 = (d or {}).get("items") or []
    ck(f"给出 {len(K.旋钮表)} 个旋钮(和 `knobs.py` 的 `旋钮表` 一样多 —— "
       "**现读,不存第二份**)",
       len(项) == len(K.旋钮表), {"接口": len(项), "文件": len(K.旋钮表)})
    # ⚠️ 这一条是这一份最硬的:**落点核对的结果必须给出来**。
    核 = (d or {}).get("落点核对") or {}
    ck("**给出落点核对的结果**(它回答「这个旋钮是真的吗」—— "
       "一个显示着旋钮却不说它们接没接上的后台,本身就在制造假象)",
       isinstance(核.get("过了吗"), bool), 核)
    ck("而且现在是过的(对照:下面「核对不过就拒绝导出」那条才有意义)",
       核.get("过了吗") is True, 核)
    ck("每个旋钮都带 `落点`(人能自己核对,不用只信后台那句「核对过了」)",
       项 and all(x.get("落点") for x in 项),
       [x.get("落点") for x in 项[:2]])
    ck("带默认值(**控制面挂了要退回这一份** —— 业界那套的第三件)",
       isinstance((d or {}).get("默认值"), dict), (d or {}).get("默认值"))
    ck("**明说这不是后台自己的 Agent 配置**"
       "(混起来就是搬家说明批评的「两套调 agent 的东西」)",
       "Agent" in str((d or {}).get("note") or ""),
       str((d or {}).get("note") or "")[:60])

    # ── 二、建方案:三条拒绝 ────────────────────────────────────
    print("\n▸ 二、建方案:**认不出的旋钮名不许存下来**")
    码, 体 = 打("POST", f"{P}/knob-plans",
             {"方案号": f"{我的方案}-坏", "为什么": "验拒绝",
              "旋钮": {"temperature": 0.7}})
    ck("认不出的旋钮名 → 422(**存下来它什么都不做**,而方案上看起来它在那儿)",
       码 == 422, {"码": 码, "点名": ((体 or {}).get("field_errors") or {})})
    ck("而且理由**点名那个名字**", "temperature" in str(体), str(体)[:90])
    码, 体 = 打("POST", f"{P}/knob-plans",
             {"方案号": "../跑出去", "为什么": "x", "旋钮": {}})
    # ⚠️ 方案号会变成**文件名** —— 带路径的名字能让导出写到仓库外面去。
    ck("方案号带路径 → 422(**它会变成文件名**)", 码 == 422, {"码": 码})
    码, 体 = 打("POST", f"{P}/knob-plans",
             {"方案号": f"{我的方案}-没理由", "旋钮": {}})
    ck("不写「为什么」→ 422(没说清为什么的方案,"
       "下次没人知道它还要不要留着)", 码 == 422, {"码": 码})

    # ── 三、建一个真方案,改它 ──────────────────────────────────
    print("\n▸ 三、建 → 改 → 导出状态")
    码, 体 = 打("POST", f"{P}/knob-plans",
             {"方案号": 我的方案, "为什么": "端到端:关体检 + 想多深 high",
              "旋钮": {"体检": False, "effort": "high"}})
    ck("建方案 → 201", 码 == 201, {"码": 码})
    ck("**校验说明是人话**(「交付前体检:True → False」这种,"
       "而不是一个布尔)",
       any("→" in str(x) for x in ((体 or {}).get("校验说明") or [])),
       (体 or {}).get("校验说明"))
    码, det = 打("GET", f"{P}/knob-plans/{我的方案}")
    ck("详情 200,而且 **导出过吗 = False**(刚建还没导)",
       码 == 200 and (det or {}).get("导出过吗") is False,
       {"码": 码, "导出过吗": (det or {}).get("导出过吗")})
    ck("详情带 `draft_revision`(改它要用)",
       isinstance((det or {}).get("draft_revision"), int),
       (det or {}).get("draft_revision"))
    码, 体 = 打("PATCH", f"{P}/knob-plans/{我的方案}/draft", {"旋钮": {"effort": "max"}})
    # ⚠️ **409 而不是 428** —— 428 语义更准,但这个仓库的契约里没有它
    # (`deps._错` 当场抛「用了契约外的状态码」),而且另外四个模块
    # 一律用 409 IF_MATCH_REQUIRED。第一版我写了 428,接口当场 500。
    ck("不带 If-Match 改 → 409 IF_MATCH_REQUIRED"
       "(**和另外四个模块一个码** —— 语义更准的码不在契约里就是第五种写法)",
       码 == 409 and (体 or {}).get("code") == "IF_MATCH_REQUIRED",
       {"码": 码, "code": (体 or {}).get("code")})
    码, 体 = 打("PATCH", f"{P}/knob-plans/{我的方案}/draft",
             {"旋钮": {"effort": "max"}},
             头={"If-Match": str((det or {}).get("draft_revision"))})
    ck("带对的 If-Match → 200,旋钮改了",
       码 == 200 and ((体 or {}).get("旋钮") or {}).get("effort") == "max",
       {"码": 码, "旋钮": (体 or {}).get("旋钮")})
    码, 体 = 打("PATCH", f"{P}/knob-plans/{我的方案}/draft",
             {"旋钮": {"effort": "low"}},
             头={"If-Match": str((det or {}).get("draft_revision"))})
    ck("拿旧的 revision 再改 → 409(**乐观锁真的在拦**)", 码 == 409, {"码": 码})

    # ── 四、导出:只改 `旋钮`,不碰 `验证` ─────────────────────────
    print("\n▸ 四、导出:**只改一个键** —— `验证` 不可重建")
    import subprocess
    out = subprocess.run(
        [os.path.join(_根, ".venv", "bin", "python"),
         os.path.join(_根, "tools", "export_knob_plans.py")],
        capture_output=True, text=True)
    ck("导出脚本退出码 0", out.returncode == 0,
       (out.stdout + out.stderr)[-160:])
    f = os.path.join(K.目录, f"{我的方案}.json")
    ck("方案文件写出来了", os.path.exists(f), f)
    if os.path.exists(f):
        体 = json.load(open(f, encoding="utf-8"))
        ck("文件里的旋钮 == 库里的", (体.get("旋钮") or {}).get("effort") == "max",
           体.get("旋钮"))
        ck("新建的那份 `拷自`/`改`/`验证` 都是空的(后台只管旋钮那一半)",
           体.get("拷自") == {} and 体.get("改") == {} and 体.get("验证") == [],
           {k: 体.get(k) for k in ("拷自", "改", "验证")})
    码, det2 = 打("GET", f"{P}/knob-plans/{我的方案}")
    ck("导出之后详情说 **导出过了**", (det2 or {}).get("导出过吗") is True,
       (det2 or {}).get("导出过吗"))
    ck("而且说 **文件还是导出那一份**", 
       (det2 or {}).get("文件还是导出那一份吗") is True,
       (det2 or {}).get("文件还是导出那一份吗"))

    # ⚠️⚠️ **这一组是整份测试最该守的那条。**
    # 造一份带 `验证` 历史的方案文件,改它的旋钮再导出 ——
    # `验证` 必须一字不差地留着。它不可重建:重跑一遍评测花钱,结果还会漂。
    print("\n▸ 五、**导出不许抹掉 `验证` 历史**(它不可重建)")
    带史 = f"{我的方案}-带历史"
    史文件 = os.path.join(K.目录, f"{带史}.json")
    原始 = {
        "号": 带史, "建于": "2026-01-01T00:00:00", "为什么": "造的",
        "拷自": {"TL99": "原文快照"}, "改": {"TL99": "改后的样子"},
        "验证": [{"时间": "2026-01-02T00:00:00", "结果文件": "x.jsonl",
                "题数": 6, "过": 5, "模型": "造的", "代码": "deadbeef"}],
        "旋钮": {"effort": "low"},
    }
    open(史文件, "w", encoding="utf-8").write(
        json.dumps(原始, ensure_ascii=False, indent=1) + "\n")
    码, _ = 打("POST", f"{P}/knob-plans",
             {"方案号": 带史, "为什么": "造的", "旋钮": {"effort": "high"}})
    ck("把那份带历史的方案拉进后台 → 201", 码 == 201, {"码": 码})
    out2 = subprocess.run(
        [os.path.join(_根, ".venv", "bin", "python"),
         os.path.join(_根, "tools", "export_knob_plans.py")],
        capture_output=True, text=True)
    ck("再导出一次,退出码 0", out2.returncode == 0,
       (out2.stdout + out2.stderr)[-120:])
    后 = json.load(open(史文件, encoding="utf-8"))
    ck("旋钮**改了**(low → high,对照:下面几条才有意义)",
       (后.get("旋钮") or {}).get("effort") == "high", 后.get("旋钮"))
    ck("**`验证` 一字不差地留着**(它不可重建 —— "
       "重跑一遍评测花钱,而且结果会漂)",
       后.get("验证") == 原始["验证"], 后.get("验证"))
    ck("**`改` 和 `拷自` 一字不差**(提示词改动是方案的另一半)",
       后.get("改") == 原始["改"] and 后.get("拷自") == 原始["拷自"],
       {"改": 后.get("改"), "拷自": 后.get("拷自")})
    ck("`建于` 没被改成今天(**那是这个实验什么时候开始的**)",
       后.get("建于") == 原始["建于"], 后.get("建于"))

    清掉()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(夹具已清)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
