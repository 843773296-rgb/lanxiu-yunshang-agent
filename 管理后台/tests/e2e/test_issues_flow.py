#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问题单(2026-11-12;口径照《意见收集与能力持续改进 PRD》10-24 §4.2 / §5.2 / §7.1)。
打真起着的管理后台,不调模型 —— 进 test-e2e-ci。

  ① 建单的字段:没标题 / 根因类别不在 9 类里 / 没分类就说「原因已证实」/ 时限不是日期 → 422,定位到字段
  ② 从一条核实中的意见直接建并关联:没带意见 revision → 422;revision 对不上 → 409 且**问题单也没建出来**(同一个事务);
     对了 → 201,意见转「已关联问题」,两边时间线各一行
  ③ 意见那一侧:关联问题不给单号 → 422;单号不存在 → 422;待受理的意见关联 → 409;重新归并不写为什么 → 422;
     归并之后 issue_id 清空、回核实中;**意见详情跟随问题单显示状态**
  ④ 主线每条边走一遍(PRD §5.2):确认 → 处理 → 提交验证 → 验证失败(回处理中)→ … → 发布失败(留在待发布,记一行)
     → 发布生效 → 观察期复发(回处理中)→ … → 关闭(缺处理说明 / 缺完成证据 → 422)→ 关闭后复发(重开,**关闭记录不抹掉**)
     (11-12 起「验证通过 / 发布生效」要带验证记录 / 发布记录,证据用 _改进证据.py 造齐;前置条件本身在 test_issue_improvements_flow 里测)
  ⑤ 非法动作 → 409 TRANSITION_NOT_ALLOWED;⑥ If-Match 不带 / 对不上 → 409
  ⑦ 搁置:缺理由 / 缺重新评估日期 / 日期早于今天 → 422;搁置不计已解决;重新评估回待分析
  ⑧ 重复:缺主问题 / 指自己 / 主问题不存在 → 422;标了之后指向主问题、主问题看得到它;重复单没有出口;
     意见不能关联到重复单;已有重复单指向的单再标重复 → 409
  ⑨ 改字段:改根因不写说明 → 422;写了 → 时间线一行「改字段」带前后值;已关闭的不许改 → 409
  ⑩ 权限:查看者建单 / 流转 → 403
  ⑪ 清单:按状态 / 根因筛;筛选值不合格 → 422;翻页信封
  ⑫ 库这一层也拦:搁置没理由 / 关闭没证据 / 重复不指主问题 / 时间线该写说明没写 / 意见已关联却没单号 —— CHECK 当场拒
  ⑬ 跨项目:演示项目里取 / 改正式项目的问题单 → 404;把正式项目的意见关联到演示项目的单 → 404
  ⑭ 演示项目留一张样例(If-Match 可达性检查和详情页冒烟要从列表拿;正式项目不留)

跑完把自己造的行删掉(问题单标题、意见工号都以 e2e-is- 开头)。
"""
import datetime as _dt
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _改进证据 as 证  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_lanxiu"
P = f"/api/v1/projects/{项目}"
PA = "/api/v1/projects/project_demo_a"
过, 挂 = [], []
标 = "e2e-is-" + uuid.uuid4().hex[:8]
样例标题 = "e2e 样例问题单(If-Match 可达性 / 详情页冒烟用)"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 头=None, 谁="U001"):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(d):
    return (d or {}).get("code") if isinstance(d, dict) else None


def 字段(d):
    return set(((d or {}).get("field_errors") or {}).keys()) if isinstance(d, dict) else set()


def 凭证():
    """和 test_opinions_flow 同一份:本机用 ~/.lanxiu/internal-call(只读);CI 上没有就现造、跑完删。"""
    路 = os.environ.get("LANXIU_INTERNAL_FILE") or os.path.expanduser("~/.lanxiu/internal-call")
    try:
        v = open(路, encoding="utf-8").read().strip()
        if v:
            return v, None
    except OSError:
        pass
    os.makedirs(os.path.dirname(路), exist_ok=True)
    v = secrets.token_hex(24)
    with open(路, "w", encoding="utf-8") as f:
        f.write(v)
    os.chmod(路, 0o600)
    return v, 路


def main():
    凭, 造的 = 凭证()
    内 = {"X-Lanxiu-Internal": 凭}
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    with 库.connect() as cc:
        org = cc.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()

    def 提意见(后缀):
        c, b = 打("POST", P + "/opinions", {"来源": "问答", "聊天站trace": f"{标}-{后缀}", "评价": "有问题", "问题类型": "答错",
                                          "说明": "工期算错了", "提问人": {"工号": 标, "姓名": "e2e", "门店": "杭州店"}}, 内)
        assert c == 201, (c, b)
        return b["id"]

    def 意见(oid):
        return 打("GET", P + f"/opinions/{oid}")[1] or {}

    def 意见动(oid, 动作, 说明=None, 问题单=None, rev=None):
        rev = 意见(oid).get("revision") if rev is None else rev
        体 = {"动作": 动作, **({"说明": 说明} if 说明 else {}), **({"问题单": 问题单} if 问题单 else {})}
        return 打("POST", P + f"/opinions/{oid}/actions", 体, {"If-Match": str(rev)})

    def 建(体, 谁="U001", 项=P):
        return 打("POST", 项 + "/issues", {"标题": f"{标} 默认标题", **体}, 谁=谁)

    def 单(iid, 项=P):
        return 打("GET", 项 + f"/issues/{iid}")[1] or {}

    def 动(iid, 动作, rev=None, 谁="U001", **额):
        rev = 单(iid).get("revision") if rev is None else rev
        头 = {"If-Match": str(rev)} if rev != "不带" else {}
        return 打("POST", P + f"/issues/{iid}/actions", {"动作": 动作, **额}, 头, 谁=谁)

    try:
        print("▸ ① 建单的字段")
        c, b = 打("POST", P + "/issues", {"业务影响": "x"})
        ck("没标题 → 422,定位到「标题」", c == 422 and "标题" in 字段(b), (c, b))
        c, b = 建({"根因类别": "玄学问题"})
        ck("根因类别不在 PRD §4.2 那 9 类里 → 422", c == 422 and "根因类别" in 字段(b), (c, b))
        c, b = 建({"根因核实": "原因已证实"})
        ck("**没分类就说「原因已证实」→ 422**(证实的是哪一类?)", c == 422 and "根因核实" in 字段(b), (c, b))
        c, b = 建({"处理时限": "下周五"})
        ck("处理时限不是日期 → 422", c == 422 and "处理时限" in 字段(b), (c, b))
        c, M = 建({"标题": f"{标} 主问题:工期少算了加急", "业务影响": "门店照着报价会少收钱", "复现条件": "问加急工期"})
        ck("建一张 → 201,待分析,revision 1", c == 201 and M.get("状态") == "待分析" and M.get("revision") == 1, (c, M))
        m = M.get("id")
        d = 单(m)
        ck("详情:根因核实默认「原因待核实」、重开 0 次、时间线一行「新建」",
           d.get("根因核实") == "原因待核实" and d.get("重开次数") == 0
           and [e["动作"] for e in d.get("时间线", [])] == ["新建"], d)
        ck("详情里「能做的动作」照 PRD §5.2(待分析:确认问题 / 暂不处理 / 标为重复)",
           {x["动作"] for x in d.get("能做的动作", [])} == {"确认问题", "暂不处理", "标为重复"}, d.get("能做的动作"))
        ck("能做的动作带「要写说明 / 要的字段」(页面照它画输入框)",
           next((x for x in d.get("能做的动作", []) if x["动作"] == "暂不处理"), {}).get("要的字段") == ["重新评估日期"]
           and next((x for x in d.get("能做的动作", []) if x["动作"] == "标为重复"), {}).get("要写说明") is True,
           d.get("能做的动作"))

        print("\n▸ ② 从一条核实中的意见直接建并关联")
        o1 = 提意见("o1")
        c, b = 意见动(o1, "开始核实")
        ck("意见推到核实中", c == 200 and b.get("到") == "核实中", (c, b))
        c, b = 建({"标题": f"{标} 从意见建", "来自意见": o1})
        ck("带了来自意见却没带意见 revision → 422", c == 422 and "意见revision" in 字段(b), (c, b))
        c, b = 建({"标题": f"{标} 从意见建-撞版本", "来自意见": o1, "意见revision": 999})
        ck("意见 revision 对不上 → 409 REVISION_CONFLICT", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        with 库.connect() as cc:
            残 = cc.execute(text("select count(*) from issues where project_id=:p and title=:t"),
                           {"p": 项目, "t": f"{标} 从意见建-撞版本"}).scalar()
        ck("**撞版本那次问题单也没建出来**(建单和关联在同一个事务里)", 残 == 0, 残)
        c, F1 = 建({"标题": f"{标} 从意见建", "来自意见": o1, "意见revision": 意见(o1).get("revision"), "说明": "同一件事"})
        ck("从意见建 → 201,返回里带着意见那一步", c == 201 and (F1.get("关联的意见") or {}).get("到") == "已关联问题", (c, F1))
        f1 = F1.get("id")
        od = 意见(o1)
        ck("**意见转「已关联问题」,详情里跟随问题单显示状态**(待分析)",
           od.get("状态") == "已关联问题" and (od.get("问题单") or {}).get("id") == f1
           and (od.get("问题单") or {}).get("状态") == "待分析", od.get("问题单"))
        末 = (od.get("时间线") or [{}])[-1]
        ck("意见时间线记「关联问题」,说明里写着问题单编号", 末.get("动作") == "关联问题" and f1 in str(末.get("说明")), 末)
        ck("问题单详情列出关联的意见", any(x["id"] == o1 for x in 单(f1).get("关联的意见", [])), 单(f1).get("关联的意见"))
        ck("问题单时间线「新建」那一行记着来自哪条意见",
           (单(f1).get("时间线") or [{}])[0].get("变化") == {"来自意见": o1}, 单(f1).get("时间线"))
        ck("已关联问题的意见能做的只有「重新归并」",
           [x["动作"] for x in od.get("能做的动作", [])] == ["重新归并"], od.get("能做的动作"))

        print("\n▸ ③ 意见那一侧:关联 / 重新归并")
        o2 = 提意见("o2")
        c, b = 意见动(o2, "关联问题", 问题单=m)
        ck("**待受理的意见直接关联 → 409**(要先核实)", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        意见动(o2, "开始核实")
        c, b = 意见动(o2, "关联问题")
        ck("关联问题不给单号 → 422,定位到「问题单」", c == 422 and "问题单" in 字段(b), (c, b))
        c, b = 意见动(o2, "关联问题", 问题单="is_不存在")
        ck("单号不存在 → 422", c == 422 and "问题单" in 字段(b), (c, b))
        c, b = 意见动(o2, "关联问题", 问题单=m, rev=999)
        ck("意见 revision 对不上 → 409", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        c, b = 意见动(o2, "关联问题", "工期那件事", 问题单=f1)
        ck("核实中 → 关联问题 → 已关联问题", c == 200 and b.get("到") == "已关联问题" and b.get("问题单") == f1, (c, b))
        c, b = 意见动(o2, "重新归并")
        ck("重新归并不写为什么 → 422", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 意见动(o2, "重新归并", "关联错了,应该并到加急那张")
        ck("已关联问题 → 重新归并 → 核实中", c == 200 and b.get("到") == "核实中", (c, b))
        od2 = 意见(o2)
        with 库.connect() as cc:
            挂单 = cc.execute(text("select issue_id from opinions where project_id=:p and id=:i"), {"p": 项目, "i": o2}).scalar()
        ck("归并之后 issue_id 清空、详情里不再有问题单;**时间线里记着从哪张单撤出**",
           挂单 is None and od2.get("问题单") is None and f1 in str((od2.get("时间线") or [{}])[-1].get("说明")),
           (挂单, od2.get("时间线")))
        c, b = 意见动(o2, "关联问题", 问题单=m)
        ck("再关联到主问题", c == 200 and b.get("问题单") == m, (c, b))

        print("\n▸ ④ 主线每条边走一遍(PRD §5.2)")
        # 11-12:验证通过 / 发布生效要带真的验证记录 / 发布记录(三组证据齐、实际采用回执在)—— 两轮各造一套
        with 库.begin() as cc:
            复1, 回1, 保1, dv1 = 证.造评测与数据(cc, org, 项目, 标, "1")
            rm1 = 证.造生产发布(cc, org, 项目, 标, "1")
            复2, 回2, 保2, dv2 = 证.造评测与数据(cc, org, 项目, 标, "2")
            rm2 = 证.造生产发布(cc, org, 项目, 标, "2")
        v1 = 打("POST", P + f"/issues/{m}/verifications", 证.验证记录体(复1, 回1, 保1, dv1))[1]["id"]
        r1 = 打("POST", P + f"/issues/{m}/releases", 证.发布记录体(rm1))[1]["id"]
        v2 = 打("POST", P + f"/issues/{m}/verifications", 证.验证记录体(复2, 回2, 保2, dv2))[1]["id"]
        r2 = 打("POST", P + f"/issues/{m}/releases", 证.发布记录体(rm2))[1]["id"]
        路线 = [("确认问题", {}, "已确认"), ("开始处理", {}, "处理中"), ("提交验证", {}, "待验证"),
              ("验证失败", {"说明": "回归集第 3 题还是错"}, "处理中"), ("提交验证", {}, "待验证"),
              ("验证通过", {"验证记录": v1}, "待发布"), ("发布失败", {"说明": "发布清单校验没过:工具版本不存在"}, "待发布"),
              ("发布生效", {"发布记录": r1}, "观察中"), ("观察期复发", {"说明": "观察第二天又有人报"}, "处理中"),
              ("提交验证", {}, "待验证"), ("验证通过", {"验证记录": v2}, "待发布"), ("发布生效", {"发布记录": r2}, "观察中")]
        坏 = []
        for 动作, 额, 应到 in 路线:
            if 动作 in ("验证失败", "发布失败", "观察期复发"):
                c, b = 动(m, 动作)
                if not (c == 422 and "说明" in 字段(b)):
                    坏.append((动作, "不写说明没被拒", c, b))
            c, b = 动(m, 动作, **额)
            if not (c == 200 and b.get("到") == 应到):
                坏.append((动作, 应到, c, b))
        ck("12 步按表走通;验证失败 / 发布失败 / 观察期复发不写说明都 422", not 坏, 坏)
        线 = 单(m).get("时间线", [])
        发败 = next((e for e in 线 if e["动作"] == "发布失败"), {})
        ck("**发布失败留在待发布**:时间线一行 待发布 → 待发布,错误写在说明里",
           发败.get("从") == "待发布" and 发败.get("到") == "待发布" and "校验没过" in str(发败.get("说明")), 发败)
        ck("意见详情跟着显示「观察中」", (意见(o2).get("问题单") or {}).get("状态") == "观察中", 意见(o2).get("问题单"))
        c, b = 动(m, "关闭", 处理说明="加急工期按工序重算")
        ck("关闭缺完成证据 → 422", c == 422 and "完成证据" in 字段(b), (c, b))
        c, b = 动(m, "关闭", 完成证据="回归集 12 题全对")
        ck("关闭缺处理说明 → 422", c == 422 and "处理说明" in 字段(b), (c, b))
        c, b = 动(m, "关闭", 处理说明="加急工期按工序重算", 完成证据="回归集 12 题全对;观察 7 天无复发")
        ck("观察中 → 关闭 → 已验证关闭", c == 200 and b.get("到") == "已验证关闭", (c, b))
        d = 单(m)
        ck("关了:已解决、记下关闭时刻,能做的只剩「关闭后复发」",
           d.get("已解决") is True and d.get("最近一次关闭") and [x["动作"] for x in d.get("能做的动作", [])] == ["关闭后复发"], d)
        ck("**意见详情跟随问题单显示「已验证关闭」**", (意见(o2).get("问题单") or {}).get("状态") == "已验证关闭",
           意见(o2).get("问题单"))
        c, b = 打("PATCH", P + f"/issues/{m}", {"方案": "改一下"}, {"If-Match": str(d["revision"])})
        ck("已关闭的不许改字段 → 409", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        关时 = d.get("最近一次关闭")
        c, b = 动(m, "关闭后复发")
        ck("关闭后复发不写说明 → 422", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 动(m, "关闭后复发", 说明="又有门店报加急工期不对")
        ck("已验证关闭 → 关闭后复发 → 处理中", c == 200 and b.get("到") == "处理中", (c, b))
        d = 单(m)
        复发 = next((e for e in reversed(d.get("时间线", [])) if e["动作"] == "关闭后复发"), {})
        ck("**重开不抹掉关闭记录**:关闭时刻 / 处理说明 / 完成证据还在,时间线那行「关闭」还在,重开 1 次,"
           "复发那一行记着上一次关闭",
           d.get("最近一次关闭") == 关时 and d.get("处理说明") and d.get("完成证据") and d.get("重开次数") == 1
           and d.get("已解决") is False and any(e["动作"] == "关闭" for e in d.get("时间线", []))
           and ((复发.get("变化") or {}).get("上一次关闭") or {}).get("完成证据"), d)

        print("\n▸ ⑤ 非法动作")
        c, X = 建({"标题": f"{标} 非法动作用"})
        x = X.get("id")
        c, b = 动(x, "关闭", 处理说明="a", 完成证据="b")
        ck("**待分析直接「关闭」→ 409 TRANSITION_NOT_ALLOWED**", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        c, b = 动(x, "发布生效")
        ck("待分析「发布生效」→ 409", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        c, b = 动(x, "随便")
        ck("不认识的动作 → 409", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))

        print("\n▸ ⑥ If-Match")
        c, b = 动(x, "确认问题", rev="不带")
        ck("不带 If-Match → 409 IF_MATCH_REQUIRED", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 动(x, "确认问题", rev=999)
        ck("**revision 对不上 → 409 REVISION_CONFLICT**(两个人同时处理,后到的不许覆盖)",
           c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        with 库.connect() as cc:
            几 = cc.execute(text("select count(*) from issue_events where project_id=:p and issue_id=:i"), {"p": 项目, "i": x}).scalar()
        ck("被拒的那几次一行时间线都没写(只有「新建」)", 几 == 1, 几)

        print("\n▸ ⑦ 搁置")
        c, S = 建({"标题": f"{标} 搁置用"})
        s = S.get("id")
        明天 = (_dt.date.today() + _dt.timedelta(days=30)).isoformat()
        c, b = 动(s, "暂不处理", 重新评估日期=明天)
        ck("**搁置不写理由 → 422**", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 动(s, "暂不处理", 说明="这季度先不排")
        ck("**搁置不给重新评估日期 → 422**", c == 422 and "重新评估日期" in 字段(b), (c, b))
        c, b = 动(s, "暂不处理", 说明="这季度先不排", 重新评估日期="2020-01-01")
        ck("重新评估日期早于今天 → 422", c == 422 and "重新评估日期" in 字段(b), (c, b))
        c, b = 动(s, "暂不处理", 说明="这季度先不排", 重新评估日期=明天)
        ck("待分析 → 暂不处理 → 已搁置", c == 200 and b.get("到") == "已搁置", (c, b))
        d = 单(s)
        ck("搁置**不计已解决**,理由和日期都在", d.get("已解决") is False and d.get("搁置理由") == "这季度先不排"
           and d.get("重新评估日期") == 明天, d)
        c, b = 动(s, "重新评估", 说明="下季度排上了")
        ck("已搁置 → 重新评估 → 待分析", c == 200 and b.get("到") == "待分析", (c, b))
        d = 单(s)
        ck("回待分析之后搁置理由 / 日期清掉,当时那行「暂不处理」的变化里还记着",
           d.get("搁置理由") is None and d.get("重新评估日期") is None
           and any(e["动作"] == "暂不处理" and (e.get("变化") or {}).get("重新评估日期") for e in d.get("时间线", [])), d)
        c, b = 动(s, "开始处理")
        ck("待分析不能直接「开始处理」(要先确认)→ 409", c == 409, (c, b))
        动(s, "确认问题")
        动(s, "开始处理")
        c, b = 动(s, "暂不处理", 说明="排期冲突", 重新评估日期=明天)
        ck("处理中也能搁置", c == 200 and b.get("到") == "已搁置", (c, b))

        print("\n▸ ⑧ 重复")
        c, D = 建({"标题": f"{标} 重复用"})
        dd = D.get("id")
        c, b = 动(dd, "标为重复", 说明="和加急工期那张是一件事")
        ck("标为重复不给主问题 → 422", c == 422 and "主问题" in 字段(b), (c, b))
        c, b = 动(dd, "标为重复", 说明="x", 主问题=dd)
        ck("指向自己 → 422", c == 422 and "主问题" in 字段(b), (c, b))
        c, b = 动(dd, "标为重复", 说明="x", 主问题="is_不存在")
        ck("主问题不存在 → 422", c == 422 and "主问题" in 字段(b), (c, b))
        c, b = 动(dd, "标为重复", 主问题=m)
        ck("标为重复不写说明 → 422", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 动(dd, "标为重复", 说明="和加急工期那张是一件事", 主问题=m)
        ck("待分析 → 标为重复 → 已重复", c == 200 and b.get("到") == "已重复", (c, b))
        d = 单(dd)
        ck("重复单指向主问题、没有出口", (d.get("主问题") or {}).get("id") == m and d.get("能做的动作") == [], d)
        ck("主问题看得到谁重复指向它", any(r["id"] == dd for r in 单(m).get("重复指向它的", [])), 单(m).get("重复指向它的"))
        o3 = 提意见("o3")
        意见动(o3, "开始核实")
        c, b = 意见动(o3, "关联问题", 问题单=dd)
        ck("**意见不能关联到重复单 → 422**(直接关联主问题)", c == 422 and "问题单" in 字段(b), (c, b))
        c, b = 动(dd, "标为重复", 说明="再来一次", 主问题=x)
        ck("重复单再标重复 → 409(没有出口)", c == 409, (c, b))
        c, b = 动(x, "标为重复", 说明="x", 主问题=dd)
        ck("指向一张重复单 → 422(不串成链)", c == 422 and "主问题" in 字段(b), (c, b))
        c, Y = 建({"标题": f"{标} 被指的"})
        c, Z = 建({"标题": f"{标} 指它的"})
        动(Z["id"], "标为重复", 说明="一件事", 主问题=Y["id"])
        c, b = 动(Y["id"], "标为重复", 说明="想再并", 主问题=x)
        ck("已经有重复单指向的那张再标重复 → 409 HAS_DUPLICATES", c == 409 and 码(b) == "HAS_DUPLICATES", (c, b))

        print("\n▸ ⑨ 改字段")
        d = 单(x)
        c, b = 打("PATCH", P + f"/issues/{x}", {"方案": "改提示词"})
        ck("不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 打("PATCH", P + f"/issues/{x}", {"根因类别": "知识问题"}, {"If-Match": str(d["revision"])})
        ck("**改根因不写说明 → 422**(PRD §4.2 调整理由入日志)", c == 422 and "说明" in 字段(b), (c, b))
        c, b = 打("PATCH", P + f"/issues/{x}", {"处理时限": "明天"}, {"If-Match": str(d["revision"])})
        ck("处理时限不是日期 → 422", c == 422 and "处理时限" in 字段(b), (c, b))
        c, b = 打("PATCH", P + f"/issues/{x}", {"根因类别": "知识问题", "根因核实": "原因已证实", "方案": "补知识片段",
                                              "负责人": "知识负责人", "处理时限": "2026-12-31", "说明": "查了检索记录,片段缺版本"},
                 {"If-Match": str(d["revision"])})
        ck("改根因 + 方案 + 负责人 + 时限 → 200", c == 200 and set(b.get("改了", [])) >= {"根因类别", "根因核实", "方案"}, (c, b))
        d2 = 单(x)
        改行 = (d2.get("时间线") or [{}])[-1]
        ck("时间线一行「改字段」,带前后值(根因类别 null → 知识问题)和说明",
           改行.get("动作") == "改字段" and (改行.get("变化") or {}).get("根因类别") == [None, "知识问题"]
           and 改行.get("说明"), 改行)
        ck("详情里根因 / 时限都是新的", d2.get("根因类别") == "知识问题" and d2.get("根因核实") == "原因已证实"
           and d2.get("处理时限") == "2026-12-31", d2)
        c, b = 打("PATCH", P + f"/issues/{x}", {"根因类别": ""}, {"If-Match": str(d2["revision"])})
        ck("已证实的时候把根因类别清空 → 422", c == 422, (c, b))

        print("\n▸ ⑩ 权限")
        无权 = "E2EISV" + uuid.uuid4().hex[:4]
        打("POST", P + "/memberships", {"工号": 无权, "角色": "viewer"})
        c, b = 建({"标题": f"{标} 无权"}, 谁=无权)
        ck("**查看者建问题单 → 403**", c == 403, (c, b))
        c, b = 动(x, "确认问题", 谁=无权)
        ck("查看者流转 → 403", c == 403, (c, b))

        print("\n▸ ⑪ 清单")
        c, l = 打("GET", P + "/issues?status=处理中&limit=200")
        ck("按状态筛:主问题(重开后在处理中)在里面,全是处理中",
           c == 200 and any(i["id"] == m for i in l["items"]) and all(i["状态"] == "处理中" for i in l["items"]), (c, l))
        c, l = 打("GET", P + "/issues?root_cause=知识问题&limit=200")
        ck("按根因筛", c == 200 and any(i["id"] == x for i in l["items"]) and all(i["根因类别"] == "知识问题" for i in l["items"]), (c, l))
        c, l = 打("GET", P + "/issues?root_cause=未分类&limit=200")
        ck("「未分类」= 根因类别还空着", c == 200 and all(i["根因类别"] is None for i in l["items"])
           and any(i["id"] == m for i in l["items"]), (c, l))
        c, b = 打("GET", P + "/issues?status=已解决")
        ck("状态筛选不在表里 → 422", c == 422 and "status" in 字段(b), (c, b))
        c, b = 打("GET", P + "/issues?root_cause=玄学")
        ck("根因筛选不在表里 → 422", c == 422 and "root_cause" in 字段(b), (c, b))
        c, l = 打("GET", P + "/issues?limit=2&page=1")
        ck("翻页信封 + 筛选条照接口给的可选状态画", c == 200 and len(l["items"]) == 2 and l["total"] >= 7
           and l.get("可选状态") and "已搁置" in l["可选状态"], (c, l and {k: l.get(k) for k in ("total", "页数", "可选状态")}))
        c, l = 打("GET", P + "/issues?limit=200")
        主行 = next((i for i in l.get("items", []) if i["id"] == m), {})
        ck("清单里主问题的关联意见数 = 1(o2;o1 挂在另一张)、重开 1 次", 主行.get("关联意见数") == 1 and 主行.get("重开次数") == 1, 主行)

        print("\n▸ ⑫ 库这一层也拦")
        def 库拒(sql, **参):
            try:
                with 库.begin() as cc:
                    cc.execute(text(sql), {"p": 项目, **参})
                return False
            except Exception as e:
                return "check" in str(e).lower()
        插 = """insert into issues (id, organization_id, project_id, created_at, title, root_cause_status, status, reopen_count,
                                  shelve_reason, reevaluate_date, resolution_note, completion_evidence_note, duplicate_of_issue_id)
                select :i, organization_id, id, now(), :t, '原因待核实', :st, 0, :sr, cast(:rd as date), :rn, :ce, :du
                  from projects where id=:p"""
        def 一行(**kv):
            参 = dict(i=f"is_x{uuid.uuid4().hex[:10]}", t=f"{标} 库", st="待分析", sr=None, rd=None, rn=None, ce=None, du=None)
            参.update(kv)
            return 参
        ck("对照:合格的一行库收(这组「库拒」不是一律拒)", not 库拒(插, **一行()))
        ck("已搁置没理由 → 库拒", 库拒(插, **一行(st="已搁置", rd="2030-01-01")))
        ck("已搁置没重新评估日期 → 库拒", 库拒(插, **一行(st="已搁置", sr="x")))
        ck("已验证关闭没完成证据 → 库拒", 库拒(插, **一行(st="已验证关闭", rn="x")))
        ck("已重复不指主问题 → 库拒", 库拒(插, **一行(st="已重复")))
        ck("状态不在表里 → 库拒", 库拒(插, **一行(st="已解决")))
        ck("时间线「暂不处理」不写说明 → 库拒", 库拒("""insert into issue_events (id, organization_id, project_id, created_at,
                issue_id, action_code, from_status, to_status) select 'ie_x' || md5(random()::text), organization_id, id, now(),
                :i, '暂不处理', '待分析', '已搁置' from projects where id=:p""", i=m))
        ck("意见「已关联问题」却没单号 → 库拒", 库拒("update opinions set status='已关联问题', issue_id=null where project_id=:p and id=:o",
                                          o=o3))

        print("\n▸ ⑬ 跨项目")
        c, b = 打("GET", PA + f"/issues/{m}")
        ck("演示项目里取正式项目的问题单 → 404", c == 404, (c, b))
        c, b = 打("POST", PA + f"/issues/{m}/actions", {"动作": "提交验证"}, {"If-Match": "1"})
        ck("演示项目里流转正式项目的问题单 → 404", c == 404, (c, b))
        c, b = 打("PATCH", PA + f"/issues/{m}", {"方案": "x"}, {"If-Match": "1"})
        ck("演示项目里改正式项目的问题单 → 404", c == 404, (c, b))
        c, l = 打("GET", PA + "/issues?limit=200")
        ck("演示项目的清单里没有正式项目的单", c == 200 and not any(i["id"] in (m, x, s) for i in l.get("items", [])), (c, l))
        c, b = 打("POST", PA + "/issues", {"标题": f"{标} 跨项目", "来自意见": o3, "意见revision": 意见(o3).get("revision")})
        ck("在演示项目建单、拿正式项目的意见去关联 → 404(那个项目里没有这条意见),单也没建出来", c == 404, (c, b))

        print("\n▸ ⑭ 演示项目留一张样例(正式项目不留)")
        c, l = 打("GET", PA + "/issues?limit=200")
        if not any(i["标题"] == 样例标题 for i in (l or {}).get("items", [])):
            c, b = 打("POST", PA + "/issues", {"标题": 样例标题, "业务影响": "端到端测试留的样例"})
            ck("演示项目里建了一张样例问题单", c == 201, (c, b))
        else:
            ck("演示项目里已经有样例问题单(重复跑不会多出来)", True)
    finally:
        with 库.begin() as cc:
            for 项 in (项目, "project_demo_a"):
                证.清掉(cc, 项, 标)
            我的意见 = "select id from opinions where project_id=:p and asker_staff_code=:s"
            cc.execute(text(f"delete from opinion_events where project_id=:p and opinion_id in ({我的意见})"), {"p": 项目, "s": 标})
            cc.execute(text("delete from opinions where project_id=:p and asker_staff_code=:s"), {"p": 项目, "s": 标})
            for 项 in (项目, "project_demo_a"):
                cc.execute(text("delete from issue_events where project_id=:p and issue_id in "
                                "(select id from issues where project_id=:p and title like :t)"), {"p": 项, "t": 标 + "%"})
                cc.execute(text("delete from issues where project_id=:p and title like :t"), {"p": 项, "t": 标 + "%"})
        if 造的:
            os.remove(造的)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 问题单:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
