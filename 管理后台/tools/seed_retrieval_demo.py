#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给**演示项目**造出「一个已就绪的索引 + 一条检索试跑」—— 主要给 CI 用。

## 为什么需要它

2026-10-08 加「检索试跑记录」栏目之后,CI 上有三条判据会红,而**根因是同一个**:
演示项目(`project_demo_a`)只灌了语料,**没有索引构建**。

  · `tests/e2e/test_retrieval_runs_flow.py`  要一个已就绪的索引才跑得起来
  · `tools/ifmatch_reachable_check.py`       要一条试跑记录才拿得到样例 id
  · `tools/detail_page_hashes.py --钉住 0`   `#/rrun/{id}` 取不到 id

> **修法不是把判据调松。** 那等于承认这几条在 CI 上永远不验 ——
> 而「验过了」和「因为没数据而什么都没验」在那份报告上长得一模一样。
> (10-08 上午 CI 连红三次就是同一族:详情页冒烟在空库上取不到 id,
>  那次的修法也是**给 CI 补数据**,不是调大 `--钉住`。)

## ⚠️ 它**全走产品自己的路径**,不往库里编数据

    建索引   → `POST /knowledge-bases/{id}/index-builds`(真接口,带幂等键)
    真构建   → **Worker 自己捞**(CI 里 Worker 常驻;这里只负责等它到「已就绪」)
    一条试跑 → `POST /retrieval-tests`(真接口,`要精排=false 要生成=false`)

唯一直接写库的是 `retrieval_config_versions` —— **因为没有建它的接口**
(规格里它属于「检索配置」那一组,还没落地)。这一条写出来而不是藏着:
它是这个脚本里唯一一处「绕过产品路径」的地方。

## ⚠️ 用 `emb-mock`,而且这件事必须一路传到界面

mock 向量算出来的相似度是个**看起来很正常的数字**(0.83),
而语义相近的两段话在 mock 向量上完全不相关。
所以索引带着 `是mock吗`,界面上有标记 —— 这个脚本也在输出里喊一遍:
**拿 CI 这个索引看「检索效果」是没有意义的**,它只用来验链路通不通。

## 幂等

已经有「已就绪的索引 + 至少一条试跑」就什么都不做并说明 ——
重复跑不会堆出一堆构建(那会让 `#/kb/{id}` 页上一片噪声)。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def 打(基址, 方法, 路, 谁="U002", 体=None, 头=None, 超时=60):
    req = urllib.request.Request(基址 + 路, method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=超时) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except urllib.error.URLError as e:
        print(f"{R}❌ 连不上 {基址}:{e}{D} —— 这个脚本要服务在跑")
        sys.exit(1)


def 确保有检索配置(项目):
    """没有检索配置版本就插一条。**这是这个脚本里唯一一处直接写库的地方。**

    理由:**没有建它的接口**(检索配置那一组还没落地)。
    写出来而不是藏着 —— 一处没人知道的「绕过产品路径」,下次会被当成产品行为。
    """
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or \
        "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
    eng = create_engine(url)
    with eng.begin() as c:
        有 = c.execute(text("""select id from retrieval_config_versions
                              where project_id=:p order by created_at desc limit 1"""),
                      {"p": 项目}).scalar()
        if 有:
            return 有, False
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        if not org:
            print(f"{R}❌ 没有这个项目:{项目}{D}")
            sys.exit(1)
        rid = "rc_" + uuid.uuid4().hex[:10]
        c.execute(text("""insert into retrieval_config_versions
            (id, organization_id, project_id, recall_modes, candidate_k,
             context_budget_tokens, final_chunk_limit, content_hash, revision,
             created_at, created_by)
            values (:i,:o,:p, cast(:rm as jsonb), 12, 4000, 4, :ch, 1, now(), 'seed')"""),
                  {"i": rid, "o": org, "p": 项目,
                   "rm": json.dumps(["vector"]), "ch": "cfg-seed-" + rid[-6:]})
    return rid, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--项目", default="project_demo_a")
    ap.add_argument("--基址", default=os.environ.get("AIMC_BASE", "http://127.0.0.1:8801"))
    # ⚠️ **身份要能换。** 默认 U002(演示项目 A 的成员,也是页面冒烟用的那个)——
    # 而别的项目成员不同,写死身份会让这个脚本只在一个项目上跑得起来,
    # 报出来还是 `NO_MEMBERSHIP`,读着像项目不存在。
    ap.add_argument("--谁", default="U002")
    ap.add_argument("--等几秒", type=int, default=120,
                    help="等 Worker 把索引建到「已就绪」的上限")
    a = ap.parse_args()
    P = f"/api/v1/projects/{a.项目}"
    print("=" * 84)
    print(f"给演示项目造「已就绪的索引 + 一条试跑」· {a.项目}")
    print("=" * 84)

    # ── ① 已经齐了就不动 ──────────────────────────────────────────
    s, 跑过的 = 打(a.基址, "GET", f"{P}/retrieval-runs?limit=1", 谁=a.谁)
    if s != 200:
        print(f"{R}❌ 读试跑列表失败:{s} {跑过的}{D}")
        return 1
    s, kbs = 打(a.基址, "GET", f"{P}/knowledge-bases?limit=100", 谁=a.谁)
    if s != 200 or not (kbs or {}).get("items"):
        print(f"{R}❌ 这个项目没有知识库 —— 先跑 tools/ingest_lanxiu.py --项目 {a.项目}{D}")
        return 1
    能检索的 = [x for x in kbs["items"] if x["能检索吗"]]
    if 能检索的 and 跑过的["items"]:
        print(f"  {G}✅ 已经齐了{D}:{len(能检索的)} 个库能检索、"
              f"{跑过的['total']} 条试跑在册 —— **什么都不做**")
        print("     (重复跑不堆构建:那会让索引页上一片噪声)")
        return 0

    # ── ② 挑一个有片段的库 ────────────────────────────────────────
    有料的 = sorted([x for x in kbs["items"] if (x.get("最新版片段数") or 0) > 0],
                 key=lambda x: -(x["最新版片段数"] or 0))
    if not 有料的:
        print(f"{R}❌ 没有带片段的知识库 —— "
              f"先 `tools/ingest_lanxiu.py --批次 业务拍板 --项目 {a.项目}`{D}")
        return 1
    kb = 有料的[0]
    print(f"  拿「{kb['name']}」({kb['最新版片段数']} 个最新版片段)")

    if not 能检索的:
        cfg, 新建 = 确保有检索配置(a.项目)
        print(f"  检索配置版本:{cfg}" + ("(**这个脚本刚插的** —— "
              "没有建它的接口,见文件头)" if 新建 else "(用现成的)"))
        # ⚠️ 幂等键**按项目 + 库定**,不用随机值 ——
        # 随机值会让重跑每次新建一个构建,而「重跑一次」是 CI 的常态。
        键 = f"seed-index-{a.项目}-{kb['id']}"
        s, r = 打(a.基址, "POST", f"{P}/knowledge-bases/{kb['id']}/index-builds", 谁=a.谁,
                 体={"embedding模型id": "emb-mock"},
                 头={"Idempotency-Key": 键})
        if s not in (200, 202):
            print(f"{R}❌ 建索引失败:{s} {r}{D}")
            return 1
        ib = r.get("resource_id")
        print(f"  建索引任务下去了:{r.get('job_id')} → 构建 {ib}")
        print(f"  {Y}⚠️ 用的是 emb-mock —— mock 向量算出的相似度是个"
              f"**看起来很正常的数字**,而语义相近的两段话在它上面完全不相关。"
              f"拿这个索引看「检索效果」没有意义,它只用来验链路通不通。{D}")
        # ── ③ 等 Worker。**等到状态变,不是 sleep 固定秒数** ─────────
        到 = time.time() + a.等几秒
        状态 = None
        while time.time() < 到:
            s, bl = 打(a.基址, "GET",
                      f"{P}/knowledge-bases/{kb['id']}/index-builds", 谁=a.谁)
            这个 = [x for x in (bl or {}).get("items", [])
                  if x["id"] == ib]
            状态 = 这个[0]["status"] if 这个 else None
            if 状态 == "已就绪":
                break
            if 状态 in ("失败", "已取消"):
                print(f"{R}❌ 构建走到了「{状态}」 —— 去看 Worker 日志{D}")
                return 1
            time.sleep(2)
        if 状态 != "已就绪":
            # ⚠️ 超时要**说清它卡在哪一档**,而不是只说「超时」——
            # 「Worker 没起来」和「构建跑着但慢」下一步完全不同。
            print(f"{R}❌ 等了 {a.等几秒} 秒,构建还在「{状态}」 —— "
                  f"Worker 起来了吗?(CI 里它是常驻进程){D}")
            return 1
        print(f"  {G}✅ 构建已就绪{D}")
    else:
        ib = None

    # ── ④ 跑一次试跑(**不调模型**,所以不花钱、CI 里也跑得动)──────
    s, bl = 打(a.基址, "GET",
              f"{P}/knowledge-bases/{kb['id']}/index-builds", 谁=a.谁)
    就绪 = [x for x in (bl or {}).get("items", [])
          if x["status"] == "已就绪"]
    if not 就绪:
        print(f"{R}❌ 这个库没有已就绪的索引 —— 上一步应该已经建好了{D}")
        return 1
    s, 链 = 打(a.基址, "POST", f"{P}/retrieval-tests", 谁=a.谁,
             体={"索引构建id": 就绪[0]["id"], "问题": "客户给了差评要怎么处理",
                # ⚠️ 两个都关掉:精排和生成都要调 Claude,而 **CI 里没有凭据**
                # (而且「CI 只跑不花钱的」是这个项目的规矩)。
                "要精排": False, "要生成": False})
    if s != 200:
        print(f"{R}❌ 试跑失败:{s} {链}{D}")
        return 1
    存 = (链 or {}).get("存档") or {}
    if not 存.get("存了吗"):
        print(f"{R}❌ 试跑跑了但**没存上**:{存.get('为什么')}{D}")
        return 1
    print(f"  {G}✅ 一条试跑在册{D}:{存.get('试跑id')} · "
          f"召回 {链.get('召回数')} 选 {链.get('选了几片')} 片")
    print(f"\n  {G}✅ 齐了{D} —— 这三条判据现在在 CI 上有东西可验:")
    print("     · tests/e2e/test_retrieval_runs_flow.py")
    print("     · tools/ifmatch_reachable_check.py(PATCH /retrieval-runs/{id}/rating)")
    print("     · tools/detail_page_hashes.py(#/rrun/{id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
