#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把流程图**直接画进飞书文档的画板里** —— 不是插图片,是真节点。

## 为什么要有这个

飞书的 markdown 导入**不认 mermaid**:那三段只会变成代码块,读者看到的是源码,
等于一张图都没有。而飞书文档里的「画板」是能画的 —— 入口不在 markdown,在 API。

## 接口形状是试出来的,记在这里免得下次再试一遍

官方文档站是单页应用,抓不到正文。下面这两个形状是靠**错误信息一层层逼出来**的:

    connector info empty
      → connector point and object can not both empty
        → connector snap_to and position both empty
          → 成了

图形:
    {"type":"composite_shape",
     "composite_shape":{"type":"round_rect"},      # 还有 rect / diamond / ellipse
     "x":..,"y":..,"width":..,"height":..,
     "text":{"text":"..."}}

连线:
    {"type":"connector",
     "connector":{"start":{"attached_object":{"id":"o1:1","snap_to":"auto"}},
                  "end":  {"attached_object":{"id":"o1:2","snap_to":"auto"}}}}

画板本身要先在文档里建一个 `block_type=43` 的块,**它的 `board.token` 就是 whiteboard_id**。
⚠️ 建块时 `index` 是**根块的直接子块数**,不是文档总块数 —— 给大了直接 `invalid param`。

## 权限

    board:whiteboard:node:read / :create / :update / :delete

⚠️ 后台加了权限之后**必须重新授权**:缓存里那个 token 是按旧 scope 签发的,
不会因为后台改了配置就自动变强,而「token 还能用」和「token 有新权限」
在调用失败之前长得一模一样。用 `feishu_publish.py --reauth`。
"""
import importlib.util, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("fp", os.path.join(HERE, "feishu_publish.py"))
fp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fp)

API = "https://open.feishu.cn/open-apis"


def _call(tok, method, url, body=None):
    cmd = ["curl", "-s", "-X", method, url, "-H", "Authorization: Bearer " + tok,
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body, ensure_ascii=False)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    try:
        return json.loads(out)
    except Exception:
        return {"code": -1, "msg": out[:200]}


def 根块子块数(tok, doc):
    d = _call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{doc}")
    return len(((d.get("data") or {}).get("block") or {}).get("children") or [])


def 建画板(tok, doc, index=None):
    """在文档里插一个画板块,返回 (block_id, whiteboard_id)。"""
    if index is None:
        index = 根块子块数(tok, doc)
    r = _call(tok, "POST", f"{API}/docx/v1/documents/{doc}/blocks/{doc}/children",
              {"children": [{"block_type": 43, "board": {}}], "index": index})
    if r.get("code") != 0:
        raise SystemExit(f"❌ 建画板块失败:{r.get('code')} {r.get('msg')}")
    blk = ((r.get("data") or {}).get("children") or [{}])[0].get("block_id")
    b = _call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{blk}")
    wid = (((b.get("data") or {}).get("block") or {}).get("board") or {}).get("token")
    if not wid:
        raise SystemExit("❌ 拿不到 whiteboard_id —— 建出来的块不是画板")
    return blk, wid


# ── 布局:分层,自上而下 ────────────────────────────────────────────────
def 分层(nodes, edges):
    """按边算每个节点在第几层。**环会让它停不下来**,所以限次数并报出来。"""
    lvl = {n["key"]: 0 for n in nodes}
    for _ in range(len(nodes) + 1):
        变了 = False
        for a, b, *_ in edges:
            if lvl.get(b, 0) < lvl.get(a, 0) + 1:
                lvl[b] = lvl[a] + 1; 变了 = True
        if not 变了:
            break
    else:
        raise SystemExit("❌ 图里有环,层分不出来 —— 先把环去掉,别让布局自己瞎猜")
    return lvl


def 排位(nodes, edges, w=260, h=96, gx=70, gy=90):
    lvl = 分层(nodes, edges)
    层 = {}
    for n in nodes:
        层.setdefault(lvl[n["key"]], []).append(n)
    宽 = max(len(v) for v in 层.values())
    画布 = 宽 * (w + gx)
    pos = {}
    for L, 组 in 层.items():
        总 = len(组) * w + (len(组) - 1) * gx
        x0 = (画布 - 总) / 2
        for i, n in enumerate(组):
            pos[n["key"]] = (x0 + i * (w + gx), L * (h + gy))
    return pos, w, h


def 画(tok, wid, nodes, edges, w=260, h=96):
    """先画图形拿到 id,再画连线 —— 连线要引用图形的 id,顺序反了就连不上。"""
    pos, w, h = 排位(nodes, edges, w, h)
    形状 = [{"type": "composite_shape",
             "composite_shape": {"type": n.get("shape", "round_rect")},
             "x": round(pos[n["key"]][0]), "y": round(pos[n["key"]][1]),
             "width": w, "height": h,
             "text": {"text": n["text"]}} for n in nodes]
    r = _call(tok, "POST", f"{API}/board/v1/whiteboards/{wid}/nodes", {"nodes": 形状})
    if r.get("code") != 0:
        raise SystemExit(f"❌ 画图形失败:{r.get('code')} {r.get('msg')}")
    ids = (r.get("data") or {}).get("ids") or []
    if len(ids) != len(nodes):
        raise SystemExit(f"❌ 要画 {len(nodes)} 个图形,只回来 {len(ids)} 个 id —— "
                         f"**少画了却没报错**,后面的连线会连错")
    m = {n["key"]: i for n, i in zip(nodes, ids)}
    线 = [{"type": "connector",
           "connector": {"start": {"attached_object": {"id": m[a], "snap_to": "auto"}},
                         "end":   {"attached_object": {"id": m[b], "snap_to": "auto"}}}}
          for a, b, *_ in edges]
    r2 = _call(tok, "POST", f"{API}/board/v1/whiteboards/{wid}/nodes", {"nodes": 线})
    if r2.get("code") != 0:
        raise SystemExit(f"❌ 画连线失败:{r2.get('code')} {r2.get('msg')}")
    线ids = (r2.get("data") or {}).get("ids") or []
    if len(线ids) != len(edges):
        raise SystemExit(f"❌ 要画 {len(edges)} 条连线,只回来 {len(线ids)} 条")
    return len(ids), len(线ids)


def 读回(tok, wid):
    r = _call(tok, "GET", f"{API}/board/v1/whiteboards/{wid}/nodes")
    return (r.get("data") or {}).get("nodes") or []


def 画进文档(doc, nodes, edges, index=None, w=260, h=96):
    """建画板 + 画 + 读回核对。**读回是必须的** —— 接口返回 0 只说明它收下了。"""
    tok = fp.acquire_token()
    blk, wid = 建画板(tok, doc, index)
    n专, e数 = 画(tok, wid, nodes, edges, w, h)
    回 = 读回(tok, wid)
    print(f"  画板 {wid}(块 {blk})")
    print(f"  图形 {n专} 个 / 连线 {e数} 条 / 读回 {len(回)} 个节点", end="")
    print("  ✅" if len(回) == n专 + e数 else f"  ❌ 对不上(应为 {n专 + e数})")
    return wid


if __name__ == "__main__":
    print(__doc__.strip().split("\n\n")[0])
    print("\n作为库用:from feishu_board import 画进文档")
