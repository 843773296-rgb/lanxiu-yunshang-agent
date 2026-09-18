---
name: draw-flowchart
version: 1.0.0
description: |
  画流程图/架构图。**先定载体,再动手** —— 同一张图在 GitHub、飞书、网页里
  要用完全不同的做法,而用错载体的后果是「图没画出来,却看起来像画了」。
  含飞书画板 API 的完整备忘(节点/连线/箭头/标签/导出,全是试出来的)。
  触发方式:/draw-flowchart,或用户说「画个流程图」「画架构图」「这图改成流程图」。
  ⚠️ 铁律:**画完必须把成品看一眼**,接口返回 0 只说明它收下了。
---

# 画流程图

## 第一步:定载体。用错载体 = 白画

| 图要给谁看 | 用什么 | 为什么不能用别的 |
|---|---|---|
| GitHub / 仓库里的 md | **mermaid 代码块** | 直接渲染,源码即图,可 diff |
| **飞书文档** | **画板 API 画真节点** | 飞书的 markdown 导入**不认 mermaid** —— 那三段只会变成代码块,读者看到源码,等于一张图都没有 |
| 网页 / 要分享的页面 | HTML + 原生 mermaid | |
| 要自己检查画得对不对 | **导出成图片,用眼睛看** | 见下面那条铁律 |

⚠️ **别默认 markdown 里放 mermaid 就万事大吉。** 先问一句「这图最后在哪儿看」。

## 铁律:画完必须看成品

**接口返回 `code=0` 只说明它收下了,不说明画出来是对的。** 这条在一次任务里救了四回:

| 现象 | 只看返回码时的样子 |
|---|---|
| 四条边的标签挤成一团,「一模一样的参数再试已经成功过一次还写」糊成一行 | 全绿 |
| 连线**一个箭头都没有**(没设 `arrow_style`) | 全绿 |
| 分支标签三种写法接口都收,**导出来一个字没有** | 全绿 |
| 菱形里的字被切掉 | 全绿 |

自动布局尤其要看:第一版「最长路径分层 + 层内按插入顺序」把**判定框和它的拒绝框排到同一行两端**,
于是每条线 45° 斜穿整张图 —— 而节点数量核对是**全对**的。
**「节点数对上了」和「画出来是对的」是两件事。**

## 排版约定(照着排,不要让算法猜)

- **主链一条竖直线**,自上而下,x 固定
- **分支一律甩到右边**,同一个 x,短横线进出
- **判定框上进下出**,分支从右尖出 —— 靠 `snap_to` 指定,别用 `auto`
- **标签放在线中间**:纵向放两框之间的空档,横向放线的上方
- **只在有语义的地方上色**(拒绝=红、通过=绿、判定=黄)。全上色等于没上色
- 三张以内的已知图,**手写坐标比自动布局稳**。自动布局是另一个项目

## 飞书画板 API 备忘

官方文档站是单页应用抓不到正文,下面每条都是**靠错误信息逼出来的**,直接抄。

**① 建画板**(在文档里插 `block_type=43` 的块,它的 `board.token` 就是 whiteboard_id)

    POST /open-apis/docx/v1/documents/{doc}/blocks/{doc}/children
    {"children":[{"block_type":43,"board":{}}], "index": <根块的直接子块数>}

⚠️ `index` 是**根块的直接子块数**,不是文档总块数。给大了报 `invalid param` ——
而这个错和权限不足长得一点都不像,很容易被当成权限问题。

**② 画图形**

    POST /open-apis/board/v1/whiteboards/{wid}/nodes
    {"nodes":[{"type":"composite_shape",
               "composite_shape":{"type":"round_rect"},   // rect / diamond / ellipse
               "x":0,"y":0,"width":300,"height":90,
               "text":{"text":"模型"},
               "style":{"fill_color":"#E4EFEA"}}]}

**③ 画连线**(要先画完图形拿到 id)

    {"type":"connector","connector":{
       "start":{"attached_object":{"id":"o1:1","snap_to":"bottom"}},
       "end":  {"attached_object":{"id":"o1:2","snap_to":"top"},
                "arrow_style":"line_arrow"},      // ⚠️ 在 end 这一层,不在 attached_object 里
       "shape":"curve"}}

⚠️ `arrow_style` 放错一层**不报错,只是箭头静静地消失** —— 线还在,方向没了。
- `arrow_style`:`line_arrow`(solid / arrow / triangle 都会被拒)
- `shape`:`curve`(elbowed / polyline / orthogonal 都会被拒)
- `snap_to`:`auto` / `top` / `bottom` / `left` / `right`

**④ 分支标签:不要用 connector 的 caption**

`caption` / `caption.text` / `caption.data.text` 三种写法接口都返回 0,**但画不出来**。
改用**独立的透明文字块**贴在线边上:

    {"type":"composite_shape","composite_shape":{"type":"rect"},
     "text":{"text":"否"},"style":{"border_opacity":0,"fill_opacity":0}}

**⑤ 导出来看**

    GET /open-apis/board/v1/whiteboards/{wid}/download_as_image      // 返回 JPEG

**⑥ 权限**

    board:whiteboard:node:read / :create / :update / :delete

⚠️ 后台加权限后**必须重新授权**:缓存里的 token 是按旧 scope 签发的,不会自己变强 ——
而「token 还能用」和「token 有新权限」在调用失败之前长得一模一样。

**⑦ 一条没走通的路(别再试一遍)**

`POST /board/v1/whiteboards/{wid}/nodes/plantuml` **接口确实存在**
(对照:同前缀的假路径返回 404,它返回字段校验错),字段名是 `plant_uml_code`
(空串报 field validation,非空报 parse result empty —— 说明名字对了)。
但试过的所有 PlantUML 方言(活动图 / 时序图 / 类图 / mindmap / base64 / deflate)
都被解析成空。**如果它能用,就不必手摆坐标了** —— 值得再查官方文档,但别再盲试。

## 顺序:发布在前,画在后

若发布脚本是「新建文档 + 清同名旧版」,那**画板必须在发布之后画**,
否则下一次发布会连同文档一起把图换掉。
把 mermaid 块换成一行占位段,发布后按占位段定位插图。
**插入要从后往前** —— 前面插完后面的序号全变,而这种错不报错,只会插错地方。
