#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每个要 `If-Match` 的写接口,**都得有一条读接口把那个 revision 给出来**。

## 为什么需要它

2026-09-29 做「发布那条链能点」的时候撞上一个洞:`POST /releases/{id}/deploy`
要 `If-Match`(当前环境指针的 revision),而**任何读接口都没暴露这个数** ——
`_指针们()` 在服务端读到了它,应用列表把它丢掉了。

于是那条链**在界面上做不起来**:不是前端没写,是它拿不到必须带的那个值。
而这件事在任何现有判据上都是**绿的** ——
契约覆盖看「登记的接口都实现了吗」,端到端看「接口对不对」,
**没有一条看「界面拿得到它要带的东西吗」**。

补完那三条读接口之后顺手扫了一遍,**又扫出三处同样的洞**:

  · `PATCH /tools/{id}/draft`            `GET /tools` 不给 revision,也没有 `GET /tools/{id}`
  · `PATCH /datasets/{id}/samples/{sid}` **没有任何接口能列出样本**
  · `POST /execution-runs/{id}/{动作}`   比的是运行自己的 revision,而读接口不给

其中样本那一条最锋利:它的错误提示写着
**「把样本详情里的 revision 放进 If-Match 头」—— 而「样本详情」这个接口不存在。**
> 一句指着不存在的页面的错误提示,比不给提示更糟:它让人去做一件做不到的事,
> 而那句话本身读起来完全合理。

## 这条判据怎么判

对每个 `乐观锁=True` 的写接口,名单里**手写**它的 revision 从哪来
(哪条读接口、响应里哪个字段路径),然后**真去打那条读接口**,看那个字段在不在。

三种红法,各自说清:
  · **没登记**:名单里没有这个写接口 → 红。新加一个要乐观锁的写接口,
    必须同时回答「界面从哪儿拿这个数」。
  · **登记了但拿不到**:读接口打了,字段路径上没东西 → 红。
  · **名单过期**:名单里的写接口已经不存在了 → 红
    (一条指向不存在接口的登记,会在有人重用这个路径那天悄悄放行它)。

## 已知盲区(写下来,才和「忘了」分得开)

- **只看「拿得到吗」,不看「界面真的用了吗」。** 一个拿得到 revision
  却把它写死成 `"1"` 的前端,这条判据是绿的。那一半靠
  `tests/e2e/test_release_page_actions.js` 那种接线测试(它断言头里带的是哪个数)。
- **要服务在跑**,所以不进 `make contract`(那条不要数据库、不要服务)。
- 字段路径只支持 `a.b[0].c` 这种直白形状,不支持条件和通配。
  路径写不出来的映射,说明那个数藏得太深 —— 那本身是个信号。
"""
import json
import os
import subprocess
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"{基址}/api/v1/projects/{项目}"
谁 = "U001"      # admin —— 这条判据要能打到所有读接口

# ── 名单:**每一条都手写「这个数从哪儿来」** ───────────────────────────
#
# `取id`:先打哪条列表接口、从哪个路径取一个 id(写接口路径里有 {id} 时要)
# `读`  :拿那个 id 去打哪条读接口
# `字段`:那条读接口的响应里,revision 在哪个路径上
#
# ⚠️ 名单**手写**,不自动推。自动推「同组找一条带 revision 的读接口」听着省事,
# 实际上会把「数据集的 revision」当成「样本的 revision」放过去 ——
# 那正是这里要抓的洞之一。
名单 = {
    "PATCH /prompts/{id}/draft": dict(
        取id=("/prompts", "items[0].id"),
        读="/prompts/{id}", 字段="草稿.revision"),
    "PATCH /applications/{id}/draft": dict(
        取id=("/applications", "应用[0].id"),
        读="/applications/{id}", 字段="候选revision"),
    "POST /releases/{id}/deploy": dict(
        取id=("/applications", "应用[0].id"),
        读="/applications/{id}", 字段="各环境.production.revision",
        说明="发布比的是**环境指针**的 revision,不是应用的"),
    "PATCH /workflows/{id}/draft": dict(
        取id=("/workflows", "items[0].id"),
        读="/workflows/{id}", 字段="草稿.revision"),
    "PATCH /agents/{id}/draft": dict(
        取id=("/agents", "items[0].id"),
        读="/agents/{id}", 字段="草稿.revision"),
    "POST /human-requests/{id}/decisions": dict(
        取id=("/human-requests", "items[0].id"),
        读="/human-requests/{id}", 字段="请求.revision"),
    # 检索试跑打分(2026-10-08):两个人同时评,后到的会静默覆盖前一个 ——
    # > 一条「只有一个人评过」的记录,和一条「两个人评过而第一个被盖掉」的,
    # > **在那个分数上长得一模一样**。
    # ⚠️ **列表也给 revision**(不只详情)—— 列表上就能打分,
    # 要人先点进详情才拿得到那个数的话,打分这件事会被嫌麻烦而没人做,
    # 而没人评的话这个栏目就只是一本日志。
    "PATCH /retrieval-runs/{id}/rating": dict(
        取id=("/retrieval-runs", "items[0].id"),
        读="/retrieval-runs/{id}", 字段="revision"),
    # ── 契约登记了、**实现还没落地**的 ────────────────────────────
    # ⚠️ **为什么要有这一档(2026-10-02 加)。**
    # 这条判据是**运行时**判据 —— 它真去打接口。而规格的实施是分阶段的:
    # 第一阶段只登记契约,实现在后面的阶段。
    # 第一版没有这一档,于是那两个新登记的 PATCH 一进契约就把 CI 打红,
    # 报的是「没登记 revision 从哪儿来」——
    # > **一个把「还没做」和「做错了」报成同一条红的判据,
    # > 会让人去修一个还没写的东西。**
    # 而这两件事下一步完全不同:前者是「等那个阶段」,后者是「现在就补读接口」。
    #
    # ⚠️ 这一档**会自己过期**,不用人记着删:
    # 判据先探一下那个读接口在不在(404 = 还没实现)。
    #   · 标了待实现 + 真的 404 → 黄字提示,不红
    #   · 标了待实现 + **接口已经有了** → **红**(该填真实来源了)
    # 所以它和 `fk_dep_check` 的豁免同形:**两个方向都会红。**
    # 一条留着不管的「待实现」标记,会在接口真做出来那天**悄悄放行它**。
    "PATCH /tool-groups/{id}/draft": dict(
        取id=("/tool-groups", "items[0].id"),
        读="/tool-groups/{id}", 字段="草稿.revision",
        # ⚠️ **这一条当天从「待实现」转成了真来源 —— 那个设计闭环成立了。**
        # 10-02 上午给这条判据加「待实现」档时说它**会自己过期**:
        # 接口一返回 200 就该红。当天下午接口真做出来了,
        # 而它当场报「这 1 条标着待实现,而接口已经有了」。
        # > 一条留着不管的「待实现」标记,
        # > **会在接口真做出来那天悄悄放行它** —— 而这次没有。
        说明="2026-10-02 实现(规格 §16 第三阶段「固定工具组」)。"
             "冻结那条接口有**三道校验**:模型眼里同名 / 配套成环 / "
             "成员版本还在不在"),
    "PATCH /tool-selection-policies/{id}/draft": dict(
        取id=("/tool-selection-policies", "items[0].id"),
        读="/tool-selection-policies/{id}", 字段="草稿.revision",
        # ⚠️ **第二条从「待实现」转成真来源** —— 那个设计今天第二次兑现。
        # 「待实现」档会自己过期:接口一返回 200 就红。工具组那条下午转的,
        # 这条是同一晚。两次都是判据**当场**报出来的,不是我记得去改。
        说明="2026-10-02 实现(规格 §16 第四阶段的**配置面**)。"
             "⚠️ 检索算法还没做 —— 策略能配能冻,**而没有任何东西在消费它**;"
             "每条返回里都带 `⚠️还没生效` 说这件事"),

    # ⚠️ 2026-10-02 补登记 —— **这条判据当天第二次拦住我**。
    # 第一次是工具筛选那两个 PATCH(契约登记了、实现还没落地 → 进了「待实现」档),
    # 这次是旋钮方案的 PATCH(**实现已经落地了**,所以要填真实来源)。
    # 样例 id 来自 `基线-默认` 那个方案 —— `import_lanxiu_prompts.py` 建的,
    # 而它**有业务理由**:没有基线就没法说「改了旋钮之后好了多少」。
    # 不建的话这条判据会报「拿不到样例 id(列表可能是空的)」—— 那也不算通过。
    "PATCH /knob-plans/{key}/draft": dict(
        取id=("/knob-plans", "items[0].方案号"),
        读="/knob-plans/{id}", 字段="draft_revision",
        # ⚠️ **这一条要在澜绣那个项目上验。** 这条判据默认跑
        # `project_demo_a`(那 12 条接口的数据在那儿),而旋钮方案
        # **只在 `project_lanxiu` 下存在**。
        # 不指定的话它报的是「拿不到样例 id(列表可能是空的)」——
        # > 一条跑在**另一个项目**上的判据,报出来是「拿不到数据」,
        # > 而数据好好地在别的项目里。
        # (同一个错位今天第三次:页面冒烟硬编项目、行级对账硬编身份。)
        项目="project_lanxiu",
        说明="2026-10-02:旋钮方案的乐观锁。方案号就是 key(它也是文件名),"
             "所以读接口的路径参数是方案号而不是一个 id"),

    "PATCH /tools/{id}/draft": dict(
        取id=("/tools", "items[0].id"),
        读="/tools/{id}", 字段="草稿.revision",
        说明="2026-09-29 补的:原来 `GET /tools` 不给 revision,"
             "而且**没有** `GET /tools/{id}` —— 改工具草稿在界面上点不了"),
    "PATCH /datasets/{id}/samples/{sample_id}": dict(
        取id=("/datasets", "数据集[0].id"),
        读="/datasets/{id}/samples", 字段="样本们[0].revision",
        说明="2026-09-29 补的:原来**没有任何接口能列出样本**,"
             "而它的错误提示写着「把样本详情里的 revision 放进 If-Match」——"
             "**指着一个不存在的接口**"),
    "POST /execution-runs/{id}/pause": dict(
        取id=("/execution-runs", "items[0].id"),
        读="/execution-runs/{id}", 字段="revision",
        说明="2026-09-29 补的:比的是运行自己的 revision,而读接口原来不给"),
    "POST /execution-runs/{id}/resume": dict(
        取id=("/execution-runs", "items[0].id"),
        读="/execution-runs/{id}", 字段="revision"),
    "POST /execution-runs/{id}/cancel": dict(
        取id=("/execution-runs", "items[0].id"),
        读="/execution-runs/{id}", 字段="revision"),
}


def 打(路, 要码=False, 项目覆盖=None):
    """`要码=True` 时返回 (状态码, 体)。

    ⚠️ **判「接口在不在」必须看状态码,不能看「解析得出 JSON 吗」。**
    2026-10-02 当场踩了:给这条判据加「待实现」档时,我用 `打(路) is not None`
    判接口存在 —— 而**404 的错误响应体也是 JSON**,
    于是两个根本没实现的接口被判成「已经有了」。
    > 一个把 404 的 JSON 错误体当成「接口存在」的探测,
    > 和一个真的探到了接口的探测,**在返回值上长得一模一样**。
    (这正是这条判据本身在防的那类错 —— 而我在给它加档位时又犯了一次。)
    """
    # ⚠️ `项目覆盖` 让某一条在**另一个项目**上验 —— 见 `名单` 里
    # `PATCH /knob-plans/{key}/draft` 那条的注释。
    基 = (f"{基址}/api/v1/projects/{项目覆盖}" if 项目覆盖 else P)
    out = subprocess.run(
        ["curl", "-s", "-m", "20",
         *(["-w", "\n%{http_code}"] if 要码 else []),
         "-H", f"X-Dev-User: {谁}", 基址 + 路
         if 路.startswith("/api") else 基 + 路],
        capture_output=True, text=True).stdout
    码 = None
    if 要码:
        行 = (out or "").rsplit("\n", 1)
        if len(行) == 2 and 行[1].strip().isdigit():
            out, 码 = 行[0], int(行[1].strip())
    try:
        体 = json.loads(out or "null")
    except Exception:
        体 = None
    return (码, 体) if 要码 else 体


def 走(体, 路径):
    """按 `a.b[0].c` 取值。取不到返回 (False, 断在哪)。"""
    当 = 体
    走过 = []
    for 段 in 路径.split("."):
        名, _, 余 = 段.partition("[")
        if 名:
            if not isinstance(当, dict) or 名 not in 当:
                return False, ".".join(走过) or "(顶层)", 名
            当 = 当[名]
            走过.append(名)
        while 余:
            i, _, 余 = 余.partition("]")
            i = int(i)
            if not isinstance(当, list) or len(当) <= i:
                return False, ".".join(走过), f"[{i}]"
            当 = 当[i]
            走过.append(f"[{i}]")
            余 = 余.lstrip("[")
    return True, 当, None


def main():
    print(f"\n\033[1m▸ 要 If-Match 的写接口,界面拿得到那个 revision 吗{D}")
    print("  ⚠️ 这条判据看的是**「界面拿得到它要带的东西吗」** —— "
          "契约覆盖和端到端都不看这个")

    import endpoints as E
    锁的 = [f"{a['方法']} {a['路径']}" for a in E.接口表 if a.get("乐观锁")]
    if not 锁的:
        print(f"  {R}❌ 一个要乐观锁的写接口都没扫到 —— **扫不到不是通过**{D}")
        return 1
    print(f"  契约里有 {len(锁的)} 个要 If-Match 的写接口")

    if 打("/api/healthz") is None:
        print(f"  {R}❌ 服务没在跑(打不通 /api/healthz)—— "
              f"**这条判据靠真打接口,打不通就当场红**,不猜{D}")
        return 1

    漏登记 = [x for x in 锁的 if x not in 名单]
    幽灵 = [x for x in 名单 if x not in 锁的]
    if 幽灵:
        print(f"  {R}❌ 名单里这些写接口已经不在契约里了:{幽灵}{D}")
        print(f"     一条指向不存在接口的登记,会在有人重用这个路径那天悄悄放行它。")
        return 1
    if 漏登记:
        print(f"  {R}❌ 这 {len(漏登记)} 个没登记「revision 从哪儿来」:{D}")
        for x in 漏登记:
            print(f"     {x}")
        print(f"     新加一个要乐观锁的写接口,**必须同时回答"
              f"「界面从哪儿拿这个数」** —— 答不上来就是发布链那个洞:"
              f"接口全有了而界面做不起来。")
        return 1

    坏, 待实现过期 = [], []
    # ⚠️ **先把「待实现」那几条挑出来单独处理。** 它们不进 `坏`,
    # 但如果接口其实已经有了,它们要进 `待实现过期` —— 那也是红。
    for 写, cfg in list(名单.items()):
        if not cfg.get("待实现"):
            continue
        列路, _ = cfg["取id"]
        # ⚠️ **看状态码,不看「解析得出 JSON 吗」** —— 见 `打()` 那段注释。
        码, _体 = 打(列路, 要码=True, 项目覆盖=cfg.get("项目"))
        if 码 == 200:
            # 列表接口真的通了 → 实现落地了 → 这个标记该拿掉了
            待实现过期.append((写, 列路, 码))
        else:
            print(f"  {Y}⏳ {写} —— **契约登记了,实现还没落地**{D}")
            print(f"       {cfg['待实现']}")
            print(f"       (探过 `GET {列路}`:HTTP {码} → 确认还没实现。"
                  f"**这一档会自己过期** —— 它返回 200 那天这条就红)")

    if 待实现过期:
        print(f"\n  {R}❌ 这 {len(待实现过期)} 条标着「待实现」,"
              f"而接口**已经有了**:{D}")
        for 写, 列路, 码 in 待实现过期:
            print(f"     · {写}(`GET {列路}` 返回 {码})")
        print(f"     把 `待实现` 换成真实的 `读` / `字段` 登记 —— "
              f"一条留着不管的「待实现」标记,"
              f"**会在接口真做出来那天悄悄放行它**。")
        return 1

    坏 = []
    for 写, cfg in 名单.items():
        if cfg.get("待实现"):
            continue
        标 = ""
        rid = None
        项 = cfg.get("项目")
        if "{id}" in cfg["读"]:
            列路, id路 = cfg["取id"]
            体 = 打(列路, 项目覆盖=项)
            ok, 值, 断 = 走(体 or {}, id路)
            if not ok:
                # ⚠️ **拿不到 id ≠ 通过。** 列表是空的时候这一条什么都没验到,
                # 而「没东西可验」和「验过了」必须长得不一样。
                坏.append((写, f"拿不到样例 id:`{列路}` 的 `{id路}` 断在 {值}.{断}"
                              f"(**列表可能是空的 —— 那这一条就什么都没验到**)"))
                continue
            rid = 值
        读路 = cfg["读"].replace("{id}", str(rid or ""))
        体 = 打(读路, 项目覆盖=项)
        if 体 is None:
            坏.append((写, f"`GET {读路}` 打不通或不是 JSON"))
            continue
        ok, 值, 断 = 走(体, cfg["字段"])
        if not ok:
            坏.append((写, f"`GET {读路}` 的响应里没有 `{cfg['字段']}`"
                          f"(断在 `{值}` 上,缺 `{断}`)"))
            continue
        if not isinstance(值, int):
            坏.append((写, f"`GET {读路}` 的 `{cfg['字段']}` 不是整数:{值!r}"))
            continue
        标 = f"{G}✅{D}"
        print(f"  {标} {写}")
        print(f"       ← GET {cfg['读']} · `{cfg['字段']}` = {值}"
              + (f"\n       {cfg['说明']}" if cfg.get("说明") else ""))

    if 坏:
        print(f"\n  {R}❌ {len(坏)} 个写接口的 If-Match **界面拿不到**{D}")
        for 写, 为什么 in 坏:
            print(f"     {写}")
            print(f"       {为什么}")
        print(f"\n     这一族的表现不是报错,是**界面做不起来** ——")
        print(f"     而在契约覆盖和端到端上它全是绿的:")
        print(f"     前者看「登记的都实现了吗」,后者看「接口对不对」,")
        print(f"     **没有一条看「界面拿得到它要带的东西吗」**。")
        return 1

    print(f"\n  {G}✅ {len(名单)} 个写接口的 If-Match 都有读接口给得出来{D}")
    print(f"  ⚠️ 盲区:只看「拿得到吗」,不看「界面真的用了吗」——"
          f"一个把 revision 写死成 \"1\" 的前端,这条判据是绿的。"
          f"那一半靠接线测试(它断言头里带的是哪个数)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
