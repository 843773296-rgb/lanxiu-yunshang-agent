#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把流程图**直接画进飞书文档的画板里** —— 不是插图片,是真节点。

## 为什么要有这个

飞书的 markdown 导入**不认 mermaid**:那三段只会变成代码块,读者看到的是源码,
等于一张图都没有。飞书这边的图形入口是「画板」,而画板的入口不在 markdown,在 API。

## 接口形状全是试出来的,记在这里免得下次再试一遍

官方文档站是单页应用,抓不到正文。下面每一条都是靠**错误信息一层层逼出来**的:

    图形   {"type":"composite_shape",
            "composite_shape":{"type":"round_rect"},   # 还有 rect / diamond / ellipse
            "x","y","width","height",
            "text":{"text":"..."},
            "style":{"fill_color":"#E4EFEA"}}

    连线   {"type":"connector","connector":{
              "start":{"attached_object":{"id":"o1:1","snap_to":"auto"}},
              "end":  {"attached_object":{"id":"o1:2","snap_to":"auto"},
                       "arrow_style":"line_arrow"},     # ← 不给就**没有箭头**
              "shape":"curve",                          # 不给是 straight,会斜穿整张图
              "text":{"text":"是"}}}                     # 分支标签

    画板   文档里建 `block_type=43` 的块,**它的 `board.token` 就是 whiteboard_id**。

试错路径(留着当路标):
    connector info empty
      → connector point and object can not both empty
        → connector snap_to and position both empty          → attached_object + snap_to
    arrow_style: solid / arrow / triangle 都被拒             → **line_arrow**
    shape:      elbowed / polyline / orthogonal 都被拒        → **curve**

⚠️ 建画板块时 `index` 是**根块的直接子块数**,不是文档总块数 —— 给大了直接 `invalid param`,
   而这个报错和权限不足长得一点都不像,却很容易被当成权限问题。

## 为什么坐标是手写的,不是自动排的

第一版用「最长路径分层 + 层内按插入顺序」自动排,画出来是这样:
**判定框和它的拒绝框被排到同一行的左右两边,于是每条线都 45° 斜穿整张图**;
菱形里的字还被切掉。数量核对全对,图却没法看 ——
**「节点数对上了」和「画出来是对的」是两件事。**

自动布局是另一个项目。三张已知的图,手工定坐标更稳,也更好看。
所以这里的 `画` 只认**显式坐标**:排不好是排版的问题,不该由一个猜不准的算法背。

## 权限

    board:whiteboard:node:read / :create / :update / :delete

⚠️ 后台加了权限之后**必须重新授权**:缓存里那个 token 是按旧 scope 签发的,
不会因为后台改了配置就自动变强 —— 而「token 还能用」和「token 有新权限」
在调用失败之前长得一模一样。用 `feishu_publish.py --reauth`。
"""
import importlib.util, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("fp", os.path.join(HERE, "feishu_publish.py"))
fp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fp)

API = "https://open.feishu.cn/open-apis"

# 语义配色。**只在有语义的地方上色** —— 全都上色等于没上色。
配色 = {
    "拒": "#F7E8E8", "过": "#E4EFEA", "判": "#FBF0DC",
    "源": "#F6EEDF", "库": "#E2EAF6", "记": "#EFEFF2",
    # Agent Loop 图专用:画的是**谁在做这一步**,不是这一步做什么。
    # 这张图的全部信息量就在这条分界线上 —— 哪些是运行时框架替我们转的,
    # 哪些是我们自己插进去的。不上色的话它和普通流程图长得一模一样。
    "托": "#EDF4FB",   # 运行时框架托管
    "我": "#E9E4F5",   # 本系统实现的介入点
}


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
        raise SystemExit(f"❌ 建画板块失败:{r.get('code')} {r.get('msg')}"
                         f"(index={index};它要的是根块的直接子块数)")
    blk = ((r.get("data") or {}).get("children") or [{}])[0].get("block_id")
    b = _call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{blk}")
    wid = (((b.get("data") or {}).get("block") or {}).get("board") or {}).get("token")
    if not wid:
        raise SystemExit("❌ 拿不到 whiteboard_id —— 建出来的块不是画板")
    return blk, wid


def 删块(tok, doc, index):
    """删掉根块下第 index 个子块(0 基)。只用来清自己刚建的草稿。"""
    return _call(tok, "DELETE",
                 f"{API}/docx/v1/documents/{doc}/blocks/{doc}/children/batch_delete",
                 {"start_index": index, "end_index": index + 1})


def 画(tok, wid, 节点, 边):
    """节点要自带 x/y/w/h。先画图形拿 id,再画连线 —— 顺序反了连线没东西可连。

    节点:dict(key, text, x, y, w, h, shape="round_rect", 色=None)
    边  :dict(a, b, 标=None, 起="bottom", 止="top", 标位=None)
          标位=(x, y) 显式摆标签,**回边一律要给** —— 中点公式只对相邻框准
    """
    # ⚠️ **分支标签不走 connector 的 caption。**
    # caption / caption.text / caption.data.text 三种写法接口都返回 0,
    # 但导出来一个字都没有 —— **收下了不等于画出来了**。
    # 所以标签做成独立的透明文字块,贴在两个框中间:这个我能导出来验。
    节点 = list(节点)
    for e in 边:
        if not e.get("标"):
            continue
        a = next(n for n in 节点 if n["key"] == e["a"])
        b = next(n for n in 节点 if n["key"] == e["b"])
        # ⚠️ **回边必须显式给 标位。** 下面那套中点公式假定两个框是相邻的;
        # 回边跨了大半张图,它的中点落在哪儿跟曲线实际走哪儿没有关系 ——
        # 实测三条回边的标签一条压在菱形上、两条飘在空白处,
        # 而**接口全部返回成功、读回数量也全对**。只有导出图片才看得见。
        if e.get("标位"):
            cx, cy = e["标位"]
            节点.append(dict(key=f"__标__{e['a']}_{e['b']}", text=e["标"], 标签=True,
                            x=round(cx) - 130, y=round(cy), w=260, h=36, shape="rect"))
            continue
        # 横向分支和纵向主链的标签摆法不一样:
        # 纵向摆在两框之间的空档,横向摆在连线上方。用同一套公式会摆到框里去。
        横 = abs((b["x"] + b["w"] / 2) - (a["x"] + a["w"] / 2)) > abs(b["y"] - a["y"])
        if 横:
            cx = (a["x"] + a["w"] + b["x"]) / 2
            cy = a["y"] + a["h"] / 2 - 46
        else:
            cx = (a["x"] + a["w"] / 2 + b["x"] + b["w"] / 2) / 2
            cy = (a["y"] + a["h"] + b["y"]) / 2 - 18
        节点.append(dict(key=f"__标__{e['a']}_{e['b']}", text=e["标"], 标签=True,
                        x=round(cx) - 130, y=round(cy), w=260, h=36, shape="rect"))

    形状 = []
    for n in 节点:
        s = {"type": "composite_shape",
             "composite_shape": {"type": n.get("shape", "round_rect")},
             "x": n["x"], "y": n["y"], "width": n["w"], "height": n["h"],
             "text": {"text": n["text"]}}
        if n.get("标签"):
            s["style"] = {"border_opacity": 0, "fill_opacity": 0}
        elif n.get("色"):
            s["style"] = {"fill_color": 配色[n["色"]]}
        形状.append(s)
    r = _call(tok, f"POST", f"{API}/board/v1/whiteboards/{wid}/nodes", {"nodes": 形状})
    if r.get("code") != 0:
        raise SystemExit(f"❌ 画图形失败:{r.get('code')} {r.get('msg')}")
    ids = (r.get("data") or {}).get("ids") or []
    if len(ids) != len(节点):
        raise SystemExit(f"❌ 要画 {len(节点)} 个图形,只回来 {len(ids)} 个 id —— "
                         "**少画了却没报错**,后面的连线会连错")
    m = {n["key"]: i for n, i in zip(节点, ids)}

    线 = []
    for e in 边:
        c = {"start": {"attached_object": {"id": m[e["a"]], "snap_to": e.get("起", "auto")}},
             # ⚠️ **arrow_style 在 end 这一层,不在 attached_object 里面。**
             # 放错一层不报错,只是**箭头静静地消失** —— 线还在,方向没了。
             "end": {"attached_object": {"id": m[e["b"]], "snap_to": e.get("止", "auto")},
                     "arrow_style": "line_arrow"},
             "shape": "curve"}
        线.append({"type": "connector", "connector": c})
    r2 = _call(tok, "POST", f"{API}/board/v1/whiteboards/{wid}/nodes", {"nodes": 线})
    if r2.get("code") != 0:
        raise SystemExit(f"❌ 画连线失败:{r2.get('code')} {r2.get('msg')}")
    if len((r2.get("data") or {}).get("ids") or []) != len(边):
        raise SystemExit(f"❌ 要画 {len(边)} 条连线,回来的条数对不上")
    return len(ids), len(边)


def 读回(tok, wid):
    r = _call(tok, "GET", f"{API}/board/v1/whiteboards/{wid}/nodes")
    return (r.get("data") or {}).get("nodes") or []


def 导出图片(tok, wid, 存到):
    """把画板导成图片。**画完一定要导出来看一眼** ——
    接口返回 0 只说明它收下了,不说明画出来是能看的。"""
    subprocess.run(["curl", "-s", "-L", "-o", str(存到),
                    f"{API}/board/v1/whiteboards/{wid}/download_as_image",
                    "-H", "Authorization: Bearer " + tok], timeout=120)
    return 存到


def 画进文档(doc, 节点, 边, index=None):
    tok = fp.acquire_token()
    blk, wid = 建画板(tok, doc, index)
    n, e = 画(tok, wid, 节点, 边)
    回 = 读回(tok, wid)
    ok = len(回) == n + e
    print(f"  画板 {wid} | 图形 {n} / 连线 {e} / 读回 {len(回)} {'✅' if ok else '❌ 对不上'}")
    return wid


if __name__ == "__main__":
    print(__doc__.strip().split("\n\n")[0])
    print("\n作为库用:from feishu_board import 画进文档, 导出图片")
