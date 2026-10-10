#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把智能体的**产出**(经营报告、上新卡片的建议)推给管理后台,并把那边的「打回」拉回来(用户 10-10)。

A1 报「这次调用花了多少」,A3 报「这次调用的结论人认不认」,这里报的是第三件事:
**这份产出是怎么生成的** —— 用了哪些数据(输入)、照哪几条规矩、哪个模型、写出了什么、是哪一轮对话。
用户要的是「能看 + 能打回」:在 AI 管理平台上逐条看,不满意就打回,打回决定由**这边拉回去、走自己的正门执行**。

## 方向:只推不被查

管理后台**绝不反过来查澜绣的库**(A3 定下的)—— 所以产出由这边推过去;
打回也不是那边来改这边的库,而是这边去拉「待执行的决定」,用自己的函数执行、再回执(ack)。
一个能直接改应用库的控制面,等于在「写只能走明路」那条保证上开了一个后门。

## 形状照抄 A1 / A3

投递箱 + 确认文件只追加 + 差集算积压 + 键在投递那一刻定死。公共件直接复用 `usage_report`,不抄第二份。
**键由 (外部id, 版本) 算出来**:同一版重复投递是同一个键,接收端按 (项目, 外部id, 版本) 也只记一条 ——
两道防重,一道在键,一道在接收端。
"""
import hashlib, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
import usage_report as U           # 共用:配置 / 读写 / 积压的差集写法

箱 = os.path.join(ROOT, ".feynman", "artifact-outbox.jsonl")
确 = os.path.join(ROOT, ".feynman", "artifact-acked.jsonl")
伤 = os.path.join(ROOT, ".feynman", "artifact-outbox-errors.jsonl")

类型们 = ("报告", "建议")
_手机号 = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")


def _去手机号(x):
    """输入里不许带完整手机号出门 —— 管理后台是给调控的人看的,不是给联系客户的人。"""
    return json.loads(_手机号.sub(r"\1****\2", json.dumps(x, ensure_ascii=False, default=str)))


def 是本库(连接或路径, 本库):
    """只有在**本库**上产生的产出才推给管理后台(10-10 抓到的事故):检查脚本在库的临时副本上存报告、写建议,
    原来照样往**真投递箱**里排 —— 三份不存在的报告和十条不存在的建议被推上了 AI 管理平台,看起来和真的一模一样。
    本库 = 模块载入时那个库的路径(检查脚本会改模块的 DB 指向副本,但改不到这个);副本上要推,得显式把本库也指过去。"""
    import os as _os, sqlite3 as _sq
    p = 连接或路径
    if isinstance(p, _sq.Connection):
        p = (p.execute("PRAGMA database_list").fetchone() or (None, None, ""))[2]
    return bool(p) and _os.path.realpath(p) == _os.path.realpath(本库)


def 键(外部id, 版本):
    return "lxat-" + hashlib.sha1(f"{外部id}|{版本}".encode("utf-8")).hexdigest()[:32]   # ASCII:进 HTTP 头


def 组载荷(*, 外部id, 类型, 版本, 标题, 输入, 输出, 规则, 门店=None, 世界日期=None, 模型=None,
          生成方式=None, 外部trace=None):
    return dict(外部id=str(外部id)[:120], 类型=类型, 版本=int(版本), 标题=标题, 门店=门店, 世界日期=世界日期,
                模型=模型, 生成方式=生成方式, 规则=规则 or [], 输入=_去手机号(输入 or {}),
                输出=str(输出 or ""), 外部trace=外部trace)


def 缺什么(载荷):
    缺 = []
    if 载荷.get("类型") not in 类型们: 缺.append(f"类型只收 {类型们}")
    if not 载荷.get("外部id"): 缺.append("没有外部id —— 打回拉回来时对不上是哪一份")
    if not 载荷.get("输出"): 缺.append("没有输出 —— 监督看什么")
    if not 载荷.get("规则"): 缺.append("没有规则 —— 看不出它是照哪几条写的")
    return 缺


def 排队(**kw):
    """投进投递箱。**任何情况下都不抛**(A2:不影响业务)。返回键或 None。"""
    try:
        载荷 = 组载荷(**kw)
        k = 键(载荷["外部id"], 载荷["版本"])
        if k in {x.get("键") for x in U._读(箱)}:
            return k                               # 同一版已经排过了
        行 = dict(键=k, 排于=time.strftime("%Y-%m-%d %H:%M:%S"), 载荷=载荷)
        os.makedirs(os.path.dirname(箱), exist_ok=True)
        with open(箱, "a", encoding="utf-8") as f:
            f.write(json.dumps(行, ensure_ascii=False) + "\n")
        return k
    except Exception as e:
        try:
            os.makedirs(os.path.dirname(伤), exist_ok=True)
            with open(伤, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                                        错=f"{type(e).__name__}: {e}"[:300]), ensure_ascii=False) + "\n")
        except Exception:
            print(f"⚠️ [artifact] 产出上报投递失败且留痕也失败:{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None


def 积压():
    全 = U._读(箱); 好 = {x.get("键") for x in U._读(确)}
    剩 = [x for x in 全 if x.get("键") not in 好]
    return len(全), len(好), 剩, (剩[0]["排于"] if 剩 else None)


def _curl(方法, 路径, cfg, 体=None, 幂等键=None):
    url = f"{cfg['地址'].rstrip('/')}/api/v1/projects/{cfg['项目']}{路径}"
    cmd = ["curl", "-sS", "-m", "15", "-X", 方法, url, "-H", "Content-Type: application/json",
           "-H", f"X-Dev-User: {cfg['工号']}", "-w", "\n%{http_code}"]
    if 幂等键: cmd += ["-H", f"Idempotency-Key: {幂等键}"]
    if 体 is not None: cmd += ["--data-binary", "@-"]
    try:
        r = subprocess.run(cmd, input=json.dumps(体, ensure_ascii=False) if 体 is not None else None,
                           capture_output=True, text=True)
    except Exception as e:
        return None, f"curl 起不来:{type(e).__name__}: {e}"
    if r.returncode != 0:
        return None, f"curl 退 {r.returncode}:{r.stderr.strip()[:160]}"
    正文, _, 码 = r.stdout.rpartition("\n")
    return 码.strip(), 正文.strip()


def 发一条(行, cfg):
    码, 体 = _curl("POST", "/artifacts", cfg, 行["载荷"], 行["键"])
    if 码 in ("200", "201"): return True, 体[:300]
    if 码 == "422": return False, f"HTTP 422(接收端拒收,字段不合格,重试没用):{体[:160]}"
    return False, f"HTTP {码}:{(体 or '')[:160]}" if 码 else 体


def 确认(键_, 回):
    os.makedirs(os.path.dirname(确), exist_ok=True)
    with open(确, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(键=键_, 确认于=time.strftime("%Y-%m-%d %H:%M:%S"), 回=回[:200]),
                           ensure_ascii=False) + "\n")


def 待执行的决定(cfg):
    """拉管理后台上「打回、还没执行」的决定。返回 (行们, 错误)。"""
    码, 体 = _curl("GET", "/artifact-decisions?%E7%8A%B6%E6%80%81=%E5%BE%85%E6%89%A7%E8%A1%8C", cfg)   # 状态=待执行
    if 码 != "200":
        return [], f"HTTP {码}:{(体 or '')[:160]}" if 码 else 体
    try:
        return json.loads(体).get("rows") or [], None
    except Exception as e:
        return [], f"返回不是 JSON:{e}"


def 回执(cfg, 决定id, 结果, 说明=None, 新版本=None):
    码, 体 = _curl("POST", f"/artifact-decisions/{决定id}/ack", cfg,
                  {k: v for k, v in dict(结果=结果, 说明=说明, 新版本=新版本).items() if v is not None})
    return 码 in ("200", "201"), (体 or "")[:200]
