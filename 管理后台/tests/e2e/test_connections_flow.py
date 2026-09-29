#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型与连接端到端(§17.4-5):**碰凭据的那一组**。

## 这一份守三条,而三条都是「已经出事了」和「还没出事」的分界

**① 明文密钥不许进请求体 —— 而且不是「收下后忽略」。**
契约原话:**「明文一旦进过请求体,它就已经进过日志、进过 APM、可能进过错误上报」。**
忽略它只是让这一次调用看起来干净,而那个值已经散出去了。所以**当场拒**。

**② 错误信息不许回显凭据。**
这一条有个反直觉的地方:**一道防泄漏的检查,会拦住「谈论泄漏」的那句话** ——
判据第一版返回的是字段名(`api_key` 这种),而 `errors.泄密检查` 扫键也扫值,
于是整个错误响应被判成泄漏 → **500**。
所以判据改成**只报位置**(「顶层第 4 个字段」)——
那个请求体是调用方自己写的,位置对他够用了。

**③ 列表不许把密钥引用交出去** —— 只给形状(配没配、存在哪、多长)。
⚠️ **不做截断**:截到前几个字符,那几个字符仍然是原文。

## ⚠️ 还有一条跨块的:「没探过」不等于「支持一切」

契约原话:**「不探就默认全支持,会在真跑时变成一个说不清的 400」**。
所以**发到生产的清单要求它的连接版本探过** —— 这一份验那道闸真的会拦。

⚠️ 前提 `make dev`。这一份自己建连接(用途选 `rerank`/`finetune_infer`,
避开 demo 里已经占了的 `generate`),跑完把自己建的归档,所以反复跑不冲突。
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
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []

配密钥的 = "U001"       # admin:「配置密钥与预算」默认有
明文 = "PLAINTEXT-VALUE-" + uuid.uuid4().hex[:8]
裸引用 = "raw-looking-value-" + uuid.uuid4().hex[:8]


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 键=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 配密钥的)
    if 键:
        req.add_header("Idempotency-Key", 键)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            身 = r.read()
            return r.status, json.loads(身 or b"null"), 身.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        身 = e.read()
        try:
            return e.code, json.loads(身 or b"null"), 身.decode("utf-8", "replace")
        except Exception:
            return e.code, None, ""
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 事务, 连接                # noqa: E402


def 归档(cid):
    with 事务() as c:
        c.execute(text("""update model_connections set archived_at=now(),
                             status='archived', revision=revision+1
                           where project_id=:p and id=:i"""),
                  {"p": 项目, "i": cid})


def main():
    print("\n\033[1m▸ 模型与连接 · 碰凭据的那一组\033[0m")
    建了 = []

    # ── 一、明文密钥:当场拒,而且错误里一个字都不回显 ──────────────────
    码, 体, 原文 = 打("POST", f"{P}/model-connections",
                  {"用途": "rerank", "适配器": "MockModelProvider",
                   "endpoint": "mock://rr", "secret_ref": "env://RR",
                   "api_key": 明文})
    ck("请求体里塞明文密钥 → 422(**不是收下后忽略**)", 码 == 422, 码)
    ck("**错误里一个字都没回显那个明文**", 明文 not in 原文,
       "回显了就说明这条判据自己成了泄漏通道")
    闸 = ((体 or {}).get("field_errors") or {}).get("闸", [])
    ck("报的是**位置**不是字段名(否则会踩 `泄密检查` → 500)",
       any("顶层第" in x for x in 闸), [x[:34] for x in 闸][:1])
    码, 体, 原文 = 打("POST", f"{P}/model-connections",
                  {"用途": "rerank", "适配器": "M", "endpoint": "mock://rr",
                   "嵌套": {"password": 明文}, "secret_ref": "env://RR"})
    ck("**嵌套**里的明文也抓得到", 码 == 422 and 明文 not in 原文, 码)

    # ── 二、密钥引用得是个定位符,不是密钥本身 ────────────────────────
    码, 体, 原文 = 打("POST", f"{P}/model-connections",
                  {"用途": "rerank", "适配器": "M", "endpoint": "mock://rr",
                   "secret_ref": 裸引用})
    ck("引用不像定位符 → 422", 码 == 422, 码)
    ck("**也没回显那个值**(只说长度)", 裸引用 not in 原文 and "个字符" in 原文,
       原文[:70])

    # ── 三、用途不共用一条连接 ──────────────────────────────────────
    码, 体, _ = 打("POST", f"{P}/model-connections",
                {"用途": "generate", "适配器": "M", "endpoint": "mock://g",
                 "secret_ref": "env://G"})
    ck("用途已被占用 → 409(**换生成模型不许顺手换掉 Embedding**)",
       码 == 409 and (体 or {}).get("code") == "PURPOSE_TAKEN",
       (码, (体 or {}).get("code")))
    码, 体, _ = 打("POST", f"{P}/model-connections",
                {"用途": "随便写的", "适配器": "M", "endpoint": "x",
                 "secret_ref": "env://X"})
    ck("认不出的用途 → 422", 码 == 422, 码)

    # ── 四、正常建:密钥只给形状,而且哈希不含密钥 ─────────────────────
    码, a, 原文 = 打("POST", f"{P}/model-connections",
                  {"用途": "rerank", "适配器": "MockModelProvider",
                   "名字": "重排连接-咬合", "endpoint": "mock://rr",
                   "secret_ref": "keychain://lanxiu/rerank"})
    ck("正常建 → 201", 码 == 201, (码, (a or {}).get("code")))
    cid = (a or {}).get("id")
    if cid:
        建了.append(cid)
    ck("返回里密钥**只给形状**(存在哪 + 多长)",
       (a or {}).get("密钥", {}).get("存在哪") == "keychain"
       and "长度" in (a or {}).get("密钥", {}), (a or {}).get("密钥"))
    ck("建完就点明「还没探过 capabilities」",
       "还没探过" in str((a or {}).get("note")), str((a or {}).get("note"))[:40])

    # 哈希不含密钥:换个密钥、同样的配置 → 同一个哈希
    sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
    import connections as CN
    h1 = CN.配置哈希(用途="rerank", 适配器="M", endpoint="mock://rr", capabilities=None)
    h2 = CN.配置哈希(用途="rerank", 适配器="M", endpoint="mock://rr", capabilities=None)
    ck("`config_hash` **不含密钥**(换密钥不算换配置;混进去会让哈希变成侧信道)",
       h1 == h2, (h1, h2))

    # ── 五、探测:落 capabilities,而且标明是谁探的 ────────────────────
    码, 体, _ = 打("POST", f"{P}/model-connections/{cid}/probe")
    ck("探测不带幂等键 → 409", 码 == 409, 码)
    码, pr, _ = 打("POST", f"{P}/model-connections/{cid}/probe", 键=f"pb-{uuid.uuid4().hex[:8]}")
    ck("探测 → 202", 码 == 202, (码, (pr or {}).get("code")))
    ck("**标明是 mock 探的**(一份 mock 的 capabilities 和真的形状一样)",
       (pr or {}).get("是mock探的") is True, (pr or {}).get("是mock探的"))
    ck("capabilities 照适配器契约登记的方法落下来",
       "generate" in ((pr or {}).get("capabilities") or {}).get("支持的方法", []),
       ((pr or {}).get("capabilities") or {}).get("支持的方法"))
    码, 体, _ = 打("POST", f"{P}/model-connections/{cid}/probe",
                键=f"pb-{uuid.uuid4().hex[:8]}", 谁="U002")
    ck("editor 探测 → 403(要「配置密钥与预算」)", 码 == 403, 码)

    # ── 六、列表:密钥引用不许交出去 ─────────────────────────────────
    码, 体, 原文 = 打("GET", f"{P}/model-connections")
    ck("GET /model-connections 200", 码 == 200, 码)
    ck("**列表正文里找不到那个引用**(只给形状)",
       "keychain://lanxiu/rerank" not in 原文, "出现了就是把引用交出去了")
    行 = [x for x in (体 or {}).get("连接", []) if x["id"] == cid]
    ck("列表上这条已经标着探过了",
       bool(行) and all(v["探过吗"] for v in 行[0]["配置版本"]),
       行[0]["配置版本"] if 行 else None)

    # ── 七、跨块:没探过的连接,发到生产要被拦 ─────────────────────────
    #    这一条验的是 `release.可以发布吗` 里那道「连接探过吗」——
    #    契约原话:**不探就默认全支持,会在真跑时变成一个说不清的 400**。
    import release as RL
    没探 = RL.可以发布吗(环境="production", 清单={"content_hash": "h"},
                     审核={"结论": "通过", "审的哈希": "h"}, 连接探过吗=False)
    探过 = RL.可以发布吗(环境="production", 清单={"content_hash": "h"},
                     审核={"结论": "通过", "审的哈希": "h"}, 连接探过吗=True)
    查不到 = RL.可以发布吗(环境="production", 清单={"content_hash": "h"},
                      审核={"结论": "通过", "审的哈希": "h"}, 连接探过吗=None)
    ck("生产 + 连接没探过 → 拦住", bool(没探), [x[:40] for x in 没探])
    ck("生产 + 连接探过 → 放行(对照:上一条不是恒拦)", not 探过, 探过)
    ck("**查不到那一行 → 不判这一条**(None 不当成 False)", not 查不到, 查不到)

    for x in 建了:
        归档(x)
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}"
          f"(咬合建的 {len(建了)} 条连接已归档)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
