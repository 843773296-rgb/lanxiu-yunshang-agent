"""从 backend/api.py 拆出来的「api_kb」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import sqlite3, os, json, sys, re, subprocess
import worldclock as _wc


def _kb_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge")

def _kb_file(doc):
    """把「09」「养护」「09-养护与售后.md」都解析成同一个文件。

    ⚠️ **不接受调用方给的路径**,只在上面那张写死的表里挑。
    接受路径的话这就是一个 `Read` 工具了 —— 而这个项目最硬的一条主张是
    「挂给模型的工具只能读业务数据」。`boundary_audit` 拿 `../CLAUDE.md`
    和 `/etc/passwd` 攻击过这里。
    """
    k = (doc or "").strip()
    if k in api.KB_DOCS: return api.KB_DOCS[k]
    for code, (fn, desc) in api.KB_DOCS.items():
        if k == fn or k.lstrip("0") == code.lstrip("0"): return (fn, desc)
    hit = [(fn, d) for fn, d in api.KB_DOCS.values() if k and (k in fn or k in d)]
    if len(hit) == 1: return hit[0]
    return None

def kb_read(doc=None, section=None):
    """**读知识库原文** —— 表里没有、只能在正文里的那些话。

    库里已经有推导出来的**结构化**数据(尺码、用量、相容),`kb_tables` 也放了 9 张表。
    漏的是**正文**:怎么洗、怎么存、为什么这么做、客户问「为什么这么贵」时怎么答。
    那些话原来只在 md 里,模型一个字都读不到 —— 于是它只能凭训练知识讲,
    而 TL01 明写着不许。

    ## 先给目录,再给正文

    不传 `section` 给这一篇的**小节目录**;传了给那一节的正文。
    **不许一次吐整篇** —— 版型库那篇 961 行,一次给出去会把上下文淹掉,
    而淹掉的后果不是报错,是**后面真正该看的东西被挤出去了**。

    ## 来源标记跟着正文走

    md 里的 `public` / `scale` / `demo` 是**行内标**的,取一节就要把这一节里
    出现过的标记一起带出来,并按**最低那一档**给对客口径 ——
    和分部位报价「按最贵的料报」是同一个方向:**偏错的代价不对称**。
    """
    import sys as _s
    _s.path.insert(0, _kb_dir())
    import source as _src
    f = _kb_file(doc)
    if not f:
        return {"error": f"没有「{doc}」这一篇",
                "有这几篇": {k: v[1] for k, v in api.KB_DOCS.items()}}
    fn, desc = f
    path = os.path.join(_kb_dir(), fn)
    if not os.path.isfile(path):
        return {"error": f"{fn} 不在 —— **不要凭印象补**,先确认知识库是不是缺文件"}
    txt = open(path, encoding="utf-8").read()
    # 按二级标题切;一级标题(#)当成篇首
    节, 当前 = [], {"标题": "(篇首)", "行": []}
    for line in txt.split("\n"):
        if line.startswith("## "):
            节.append(当前); 当前 = {"标题": line[3:].strip(), "行": []}
        else:
            当前["行"].append(line)
    节.append(当前)
    节 = [x for x in 节 if any(l.strip() for l in x["行"])]

    def 档(块):
        """这一块里出现过哪些来源标记 —— **按最低那一档给口径**。"""
        # ⚠️ **这个顺序有语义** —— 取的是 `有[0]`,即「按最低那一档给口径」。
        # `biz`(业务口径,2026-10-25 立)排在 demo 之后、scale 之前:
        # 它比演示数据可信(**有具名的责任人**),比公开资料弱(**没有公开出处**)。
        # 放错位置不会报错,只会让一篇混排的知识**按偏高的那一档对客户说**。
        有 = [g for g in ("demo", "biz", "scale", "public") if f"`{g}`" in 块]
        低 = 有[0] if 有 else None
        return 有, 低

    # 竞品那一篇:**过期了要自己说出来**(业务 09-29 定 6 个月)—— 目录和正文都带,不等模型去翻日期
    过期话 = None
    if fn.startswith("16-"):
        import competitor as _cp
        过期话 = _cp.过期提示(_wc.今天())
    if not section:
        return api._nz({
            **({"⚠️ 过期": 过期话} if 过期话 else {}),
            "篇": f"{fn} —— {desc}",
            # ⚠️ **标记常常写在小节标题上**(`## 三、交付时必须书面告知的六条 `demo``),
            # 第一版只扫正文行,于是三节带着 demo 标的小节全报「没有标记」——
            # 而「没有标记」会被读成「这节不是演示数据」,**正好读反**。
            "小节": [{"标题": x["标题"], "行数": len(x["行"]),
                      "来源标记": 档(x["标题"] + "\n" + "\n".join(x["行"]))[0] or None,
                      # 超过一次能给的长度时,把三级标题列出来 —— 不列的话模型不知道能取哪几条
                      **({"三级标题": [l[4:].strip() for l in x["行"] if l.startswith("### ")]}
                         if len("\n".join(x["行"])) > 6000 else {})}
                     for x in 节],
            "note": "传 `section`(小节标题,写一部分也认)取正文。"
                    "**不给整篇** —— 一次吐几百行会把后面真正该看的挤出去。",
        })
    k = section.strip()
    命中 = [x for x in 节 if k == x["标题"]] or \
           [x for x in 节 if k in x["标题"]]
    # 二级标题找不到时认**三级标题**(`### `)—— 截断提示让模型「指定更细的小节(三级标题)」,
    # 而原来只认二级标题:**提示指的那条路不通**。2026-10-02 扩容后详解一节上万字,不认三级标题就只读得到开头
    if not 命中:
        for x in 节:
            小, 当前 = [], None
            for l in x["行"]:
                if l.startswith("### "):
                    当前 = {"标题": l[4:].strip(), "行": [], "上级": x["标题"]}; 小.append(当前)
                elif 当前 is not None:
                    当前["行"].append(l)
            命中 += [y for y in 小 if k == y["标题"] or k in y["标题"]]
    if not 命中:
        return {"error": f"「{fn}」里没有「{section}」这一节",
                "有这几节": [x["标题"] for x in 节]}
    if len(命中) > 1:
        return {"error": f"「{section}」对应多节,说具体点",
                "对应": [x["标题"] for x in 命中]}
    x = 命中[0]
    body = "\n".join(x["行"]).strip()
    MAX = 6000
    截 = len(body) > MAX
    有, 低 = 档(x["标题"] + "\n" + body)     # 标题上的标记也算(见上)
    out = {"篇": fn, "小节": x["标题"], "正文": body[:MAX]}
    if 过期话:
        out["⚠️ 过期"] = 过期话
    if 截:
        out["⚠️ 截断"] = (f"这一节 {len(body)} 字,只给了前 {MAX} 字。"
                          "要后面的部分,指定更细的小节(三级标题)")
    if 低:
        out.update(_src.标注(低))
        if fn.startswith("13-") and 低 == "demo":
            out["对客户"] = api.话术_DEMO口径
        out["这一节出现的来源标记"] = 有
        out["note"] = ("**按最低那一档说话** —— 一节里混着几档时,"
                       "对客户的口径取最保守的那个。")
    else:
        out["note"] = ("这一节正文里**没有来源标记** —— 不代表它可靠,"
                       "代表没人标过。对客户引用前先确认。")
    return api._nz(out)

def kb_detail(code):
    """按编码取某一条的完整内容"""
    r=api._rows("SELECT * FROM craft WHERE code=?",code)
    if not r: return {"error":f"没有编码 {code} 这一条"}
    return api._nz(api._with_source(api._with_material(r[0])))

def _resolve(x, cat):
    """把「云锦」「MT02」都解析成同一条。模型不知道编码,让它猜编码是工具设计的错误 ——
    实测过:它会拿着猜错的编码得到一个关于完全不同组合的答案,然后自信地讲出来。"""
    x=(x or "").strip()
    if not x: return None,"空值"
    r=api._rows("SELECT code,name,cat FROM craft WHERE code=? AND cat=?",x.upper(),cat)
    if r: return r[0],None
    r=api._rows("SELECT code,name,cat FROM craft WHERE cat=? AND (name=? OR alias=?)",cat,x,x)
    if r: return r[0],None
    # **别名是顿号分隔的多值,不能按整列相等比。**
    # 上面那句 `alias=?` 只有在别名恰好只有一个时才成立:
    # 「立领袄」能命中(XZ04 的别名就这一个),而「圆领袍」命不中 ——
    # XZ09 的别名是「圆领袍、常服袍」,整列不等于其中任何一个。
    # 于是它掉进下面的模糊分支,撞上「明制圆领袍」和「童款圆领袍」两条,
    # 报「对应多条」——**而它本来是一个明确声明的别名,不该是模糊匹配**。
    # **一个明确声明的别名要赢过模糊包含。**
    r=[q for q in api._rows("SELECT code,name,alias,cat FROM craft WHERE cat=?",cat)
       if x in [a.strip() for a in (q["alias"] or "").split("、") if a.strip()]]
    if len(r)==1: return {k:r[0][k] for k in ("code","name","cat")},None
    if len(r)>1:
        return None,(f"「{x}」是这几条的别名:{[q['name'] for q in r]} —— "
                     f"请用形制全名或编码")
    r=[q for q in api._rows("SELECT code,name,alias,cat FROM craft WHERE cat=?",cat)
       if x in (q["name"] or "") or x in (q["alias"] or "") or (q["name"] or "") in x]
    if len(r)==1: return r[0],None
    if len(r)>1:
        return None,f"「{x}」在{cat}里对应多条:{[q['name'] for q in r]},请用更精确的名称或编码"
    names=[q["name"] for q in api._rows("SELECT name FROM craft WHERE cat=?",cat)]
    return None,f"知识库里没有叫「{x}」的{cat}。现有{cat}:{names}"

def _combo_caveat(d):
    """给相容判定加**依据等级**;没有依据的那一档,**不再给结论**。

    ## 这里改过两版,第二版是产品决策的结果

    第一版:`rule='—'` 的 1274 格返回「可以」,只是多标一句「默认放行,没有依据」。
    第二版(现在):**这一档不给结论了**,verdict 改成「待核实」,并记一笔待办。

    改的理由是**偏错的代价不对称**:说「可以」结果做不出来,赔的是工期、料钱和客户;
    说「待核实」最多是多打一个电话。而这 1274 格**没有任何人验证过** ——
    它们只是「没命中任何禁止规则」,和「确认可以」完全是两回事。

    ## 但光不给结论会把风险赶到看不见的地方

    顾问常问的组合里有 30% 落在这一档。每问三次就有一次「待核实」,
    顾问不会真的每三次去找一次工艺负责人 —— 他会开始凭经验答,
    **风险从系统里被赶到人身上,而且从此看不见**。

    所以配了回流:**被真正问到的那一格记一笔进待办**(见 combo_review.py),
    运营核实后回填。待办量由真实需求决定,而不是由矩阵大小决定。

    ## 记一笔是「旁路」,不是模型在写

    追加的是日志文件,不碰业务库 —— 「工具层一个写接口都没有」那条保证不受影响。
    """
    ru=(d.get("rule") or "").strip()
    if d.get("verdict")=="未定义": return d
    d=dict(d)
    if ru=="人工确认":
        d["依据等级"]="人工确认 —— 打样验证过,可以直接说"
    elif ru.startswith("R"):
        d["依据等级"]=f"规则推导({ru})—— 从成文通则推出,**这一格没有单独打样验证**"
    else:
        # **不给结论。** 原来的 verdict(多半是「可」)挪到旁边留痕,不作为答案。
        d["原始默认值"]=d.get("verdict")
        d["verdict"]="待核实"
        d["依据等级"]=("**没有依据,不给结论** —— 这一格只是没命中任何禁止规则,"
                     "没有任何人验证过。「没查到禁止」和「确认可以」是两回事。")
        d["该怎么办"]=("如实告诉顾问这一格**还没核实过**,不要说可以也不要说不可以;"
                     "已经自动记入待核实队列,工艺负责人核完会回填。"
                     "客户急着要答复的话,建议换一个已确认的工艺或面料。")
        try:
            import combo_review as _cr
            _cr.record_ask(d.get("craft_code") or d.get("craft"),
                           d.get("material_code") or d.get("material"),
                           craft_name=d.get("craft"), material_name=d.get("material"))
        except Exception:
            pass      # 记不上待办不能影响回答本身 —— 旁路不是主路
    return d

def kb_combo(craft, material):
    """查某工艺能不能用在某面料上。工艺名/面料名或编码都接受。返回 可/需评估/不可/未定义。"""
    k,e1=_resolve(craft,"工艺")
    m,e2=_resolve(material,"材质")
    if e1: return {"error":e1}
    if e2: return {"error":e2}
    craft_code, material_code = k["code"], m["code"]
    r=api._rows("SELECT verdict,reason,src_type,rule FROM craft_combo WHERE craft=? AND material=?",
            craft_code,material_code)
    if not r:
        return {"craft":k["name"],"material":m["name"],
                "resolved":f"{k['code']} {k['name']} × {m['code']} {m['name']}","verdict":"未定义",
                "note":"这一格组合约束尚未录入。**必须如实告知查不到,并建议转工艺负责人确认**,"
                       "不得自行推断可或不可。","src_type":None}
    d=r[0]; d.update(craft=k["name"],material=m["name"],
                     craft_code=k["code"], material_code=m["code"],
                     resolved=f"{k['code']} {k['name']} × {m['code']} {m['name']}")
    return api._nz(_combo_caveat(d))

def kb_tables(topic=None):
    """决策表 —— 「客户说 X 该推什么」这类问题的答案在这里,不在条目里。"""
    rs=api._rows("SELECT * FROM kb_table ORDER BY topic")
    if topic: rs=[r for r in rs if topic in r["topic"]]
    if not rs:
        return {"hit":0,"available":[r["topic"] for r in api._rows("SELECT topic FROM kb_table")],
                "note":"没有这个主题的决策表,看 available 里有哪些"}
    out=[]
    for r in rs:
        out.append(dict(topic=r["topic"], head=json.loads(r["head"]),
                        rows=json.loads(r["rows"]), src=r["src_file"], src_type="demo"))
    return {"hit":len(out),"tables":out}

def kb_coverage():
    """相容矩阵的完成度 —— 让「没有数据」成为一个看得见的状态"""
    ks=api._rows("SELECT code FROM craft WHERE cat='工艺'"); ms=api._rows("SELECT code FROM craft WHERE cat='材质'")
    n=api._rows("SELECT COUNT(*) c FROM craft_combo")[0]["c"]
    tot=len(ks)*len(ms)
    # **三类分开数。** 原来把「不是人工确认的」一律算作「规则推导」——
    # 而其中 1274 格的 rule 是 `—`,**根本没有依据**,是「没命中任何禁止规则 → 默认可」。
    # 把它们报成「规则推导」是在美化:一个没人验证过的结论被说成有依据的。
    # 兜底方向选错,未知就会被打扮成已知 —— 这里未知被默认算成了「可以做」。
    by={"人工确认":0,"规则推导":0,"默认放行(无依据)":0}
    for r in api._rows("SELECT rule,COUNT(*) c FROM craft_combo GROUP BY rule"):
        ru=(r["rule"] or "").strip()
        k=("人工确认" if ru=="人工确认" else
           "规则推导" if ru.startswith("R") else "默认放行(无依据)")
        by[k]+=r["c"]
    return {"工艺数":len(ks),"材质数":len(ms),"总格数":tot,"已定义":n,"未定义":tot-n,
            "完成度":f"{n/tot*100:.0f}%","来源":by,
            "note":"**「默认放行(无依据)」不等于验证过** —— 那是「没命中任何禁止规则」"
                   "的兜底结果,没有人打样确认过。对客户说这类结论必须带上这句限定。"
                   f"所有「不可」和「需评估」都有依据;而「可」里有 {by['默认放行(无依据)']} 格是默认放行。"}

def _names():
    import leadtime
    return leadtime.记住(("工艺名",), lambda: {r["code"]: r["name"] for r in api._rows("SELECT code,name FROM craft")})

def kb_pattern(xz=None):
    """版型库 —— 一个形制有哪些版型、分几个裁片、出哪些码。

    ⚠️ **入参既收形制名,也收版型编码和版型名。**
    原来只收形制名,于是顾问按日常说法问「PT04 马面裙推荐什么码」「PT06 立领长衫
    M 码要多久」,工具一律回「知识库里没有叫「PT04」的形制」——
    **而 PT04 就在这张表里,是「明制马面裙·标准」**。

    这不是模型的问题:实测它老老实实说「查不到这个编码,请确认」并要求补参数,
    **没有编一个** —— 那正是对的行为。问题是
    **工具的入参维度和人说话的维度对不上**:
    顾问嘴里说的是版型编码和变体名(「阔褶马面裙」),工具只吃形制名。
    一套工具评测里有 4 条栽在这上面。
    """
    q="SELECT * FROM pattern"; a=()
    if xz:
        # ① 先当版型编码 / 版型全名试(PT04、明制马面裙·标准)
        直 = api._rows("SELECT * FROM pattern WHERE code=? OR name=?", xz, xz)
        # ② 再试变体名倒过来写:「阔褶马面裙」↔「明制马面裙·阔褶」
        if not 直:
            直 = [r for r in api._rows("SELECT * FROM pattern")
                  if "·" in (r["name"] or "")
                  and r["name"].split("·")[-1] in xz
                  and any(w in xz for w in r["name"].split("·")[0][-3:])]
        if 直:
            # 命中具体版型时,**仍然把同形制的都列出来** ——
            # 问 PT04 的人多半也想知道同形制还有别的版型可挑(PT05 阔褶)。
            # 只返回一条会让「有没有别的选择」这个问题永远问不出来。
            q += " WHERE xz=?"; a = (直[0]["xz"],)
        else:
            k,e=_resolve(xz,"形制")
            if e:
                # 报错也要说清**这个工具认什么** —— 否则模型只能反复猜入参。
                return {"error": e + "(这个工具也认**版型编码**如 PT04 和"
                                    "**版型全名**如「明制马面裙·标准」)"}
            q+=" WHERE xz=?"; a=(k["code"],)
    rs=api._rows(q+" ORDER BY code",*a)
    if not rs:
        return {"hit":0,"note":f"「{xz}」这个形制还没有版型。**没有版型就裁不出来**,"
                              "不能在配置页上架,须先请版师建版。"}
    nm=_names()
    for r in rs:
        r["形制"]=nm.get(r["xz"],r["xz"])
        r["裁片"]=[dict(名称=p["name"],数量=p["qty"],说明=p["note"])
                  for p in api._rows("SELECT * FROM pattern_piece WHERE pattern=?",r["code"])]
        r["尺码"]=r.pop("sizes").split(",")
        # **版本要说出来。** 一个版号不带改动记录等于没有,所以连最近那条一起给。
        _rv=api._rows("SELECT version,changed_at,what,why FROM pattern_rev "
                  "WHERE pattern=? ORDER BY version DESC LIMIT 1", r["code"])
        r["版本"]=f"v{r.get('version') or 1}" + (
            f"({_rv[0]['what']},{_rv[0]['changed_at']}:{_rv[0]['why']})" if _rv else "")
    return {"hit":len(rs),"rows":rs,
            "note":"difficulty=改版难度。「极高」的(马面裙)腰围错了等于重做,不能放缝头改。"}

def kb_size(pattern, size=None):
    """某版型的成衣尺码表。**这是成衣尺寸,不是人体尺寸**,两者之差是放松量。"""
    p=api._rows("SELECT * FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」,可先用 kb_pattern 查这个形制有哪些版型"}
    p=p[0]
    rs=api._rows("SELECT size,item,value,caveat FROM size_spec WHERE pattern=?",p["code"])
    if size: rs=[r for r in rs if r["size"]==size]
    if not rs:
        return {"error":f"{p['name']} 没有 {size} 码,只有 {p['sizes']}",
                "note":"尺码不存在不是缺货,是这个版型裁不出来。"}
    out, 参考 = {}, {}
    for r in rs:
        # **推得出不等于作数** —— 但这个标记**不许贴在值上**。
        #
        # 第一版把它写成 `"72.0(仅供参考)"`,当场炸了两处:
        # 钉死的锚点对不上(手抄 72.0 vs 算出 '72.0(仅供参考)'),
        # 以及 kb_fit 拿它去减放松量时 `str - float` 直接 TypeError。
        # **这正是这个项目反复撞的「一列承载两件事」** —— 我一边在别处修它,
        # 一边在这儿又犯了一次:一个数值字段同时装了数值和它的可信度。
        # 现在数值还是数值,标记单独一栏。
        out.setdefault(r["size"],{})[r["item"]] = r["value"]
        if r["caveat"]: 参考[r["item"]] = r["caveat"]
    res = {"版型":p["name"],"尺码表":out,"量体模版":p["tpl"],
           "note":"成衣尺寸。推荐尺码要拿客户量体值比对后由版师定,系统只给建议。"}
    if 参考:
        res["⚠️ 这几项推得出但不作数"] = sorted(参考)
        res["为什么"] = 参考
        res["note"] += ("  ⚠️ 上面「推得出但不作数」列出的项**不能直接拿去下单或裁剪**,"
                        "必须由版师按实际尺寸重新处理 —— "
                        "**在尺码表里它们和别的数长得一模一样**,所以单独列一栏。")
    return res

def kb_bom(pattern, size, material, crafts=None, scope="局部"):
    """算料算钱 —— 这个配置要用哪些物料、各多少、物料成本多少、多久备齐。

    相容矩阵回答「能不能做」,这个回答「要多少料、多少钱、多久备齐」。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import derive_pattern as dp
    p=api._rows("SELECT code FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」"}
    m,e=_resolve(material,"材质")
    if e: return {"error":e}
    kcs=[]
    for k in (crafts or []):
        r,e2=_resolve(k,"工艺")
        if e2: return {"error":e2}
        kcs.append(r["code"])
    return dp.estimate(p[0]["code"], size, m["code"], kcs, scope, craft_names=_names())

def kb_rag(question=None, role=None):
    # ⚠️ **参数名叫 `role` 不叫 `岗位`,这不是风格。**
    # 工具 schema 的属性名**必须是 ASCII**(`^[a-zA-Z0-9_.-]{1,64}$`)——
    # 中文属性名会被 API 当场拒(`Property keys should match pattern`)。
    # 这是这个项目第四次踩「中文标识符」:bash 变量名 / SQL 的 `:中文` 参数 /
    # 精排器的属性名 / 这一次。**三个约束来自三个不同的层,而每次都只在运行时报。**
    """按**意思**在管理后台那份知识库里找原文,返回最相关的几段 + 出处。

    返回 `{问的是, 证据们:[{出处, 正文, 分数}], 试跑id, 怎么评价, note}`;
    任何一步不成立都返回 `{"error":…, "怎么办":…}` —— **不退回别的工具**。
    """
    q = (question or "").strip()
    if not q:
        return {"error": "question 不能空",
                "怎么办": "把顾问问的那句话原样传进来 —— "
                        "空查询的向量会返回一批「离原点最近」的片段,看起来像正常结果"}
    角色 = api.岗位到后台角色.get((role or "").strip() or "门店顾问")
    if not 角色:
        # ⚠️ 岗位没登记就**拒**,不挑一个默认角色顶上 ——
        # 顶上的那个可能比它该有的权限大,而那件事不报错。
        return {"error": f"不认识这个岗位:{role}",
                "怎么办": f"登记的岗位只有 {list(api.岗位到后台角色)} —— "
                        f"岗位到后台角色的映射**业务还没拍**,见 api.py 那段注释"}
    # 调用方默认是 chat;复验脚本(tools/kb_recheck.py)设 LANXIU_RAG_CALLER 标成复验,
    # 免得复验那几次混进管理后台「chat 查了多少次」的统计里
    体 = json.dumps({"调用方": os.environ.get("LANXIU_RAG_CALLER") or "澜绣 chat",
                     "问题": q, "这个人的角色们": [角色],
                     # ⚠️ 显式 false:**只要证据,不要它生成的答案**(见上面那段)
                     "要生成": False}, ensure_ascii=False)
    # ⚠️ 用 curl,不用 urllib —— 这台机器有 TLS 拦截,项目里所有 HTTP 都走 curl
    # (localhost 这条其实不经过 TLS,但**两套写法会在第一次换成外网地址那天分叉**)。
    参 = ["curl", "-sS", "-m", "30", "-X", "POST",
          f"{api._后台基址}/api/v1/projects/{api._后台项目}/knowledge-queries",
          "-H", "content-type: application/json",
          "-H", f"X-Dev-User: {api._后台身份}", "-d", 体]
    r = api.subprocess.run(参, capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": f"连不上管理后台({api._后台基址}):curl 退出码 {r.returncode}",
                "怎么办": "照实告诉顾问**知识库现在查不了**,别凭记忆答 —— "
                        "业务 2026-10-08 拍的:这条路断了就要说出来。"
                        "(管理后台在 8801,起法 `管理后台/tools/dev.sh`)",
                "stderr": (r.stderr or "")[:200]}
    try:
        d = json.loads(r.stdout or "null")
    except Exception:
        return {"error": "管理后台返回的不是 JSON",
                "怎么办": "照实说知识库查不了,别凭记忆答",
                "原样": (r.stdout or "")[:200]}
    if not isinstance(d, dict):
        return {"error": "管理后台返回的形状不对",
                "怎么办": "照实说知识库查不了,别凭记忆答"}
    if d.get("code"):
        # 管理后台那边的明确拒绝(没索引 / 角色不认 / 没凭据…)——
        # **原样带回来**,连它给的建议一起;不翻译成一句「查不到」。
        return {"error": f"管理后台拒绝了这次检索:{d.get('code')} —— {d.get('message')}",
                "怎么办": (d.get("advice") or "")[:300] or "照实说知识库查不了,别凭记忆答"}
    片 = d.get("选片") or []
    if not 片:
        # ⚠️ 这一支和上面那些**不是一回事**:检索跑成了,而**它一片都没选中**。
        # 这才是真正的「知识库里没有」,可以照实说。
        # ⚠️ **零命中也把记录编号带回去**(外部复审第 4 节 E,10-23):管理后台零命中照样存了一条试跑,
        # 原来这一支把 `试跑id` 丢了 —— 员工拿不到编号,连评分 / 报「答不上」都没处报,
        # 而零命中恰恰是最该报的那一种。
        return {"hit": 0, "问的是": q, "试跑id": d.get("试跑id"), "知识库": d.get("知识库"),
                "怎么评价": "零命中也有记录编号 —— 顾问可以照样打分,或者报一条「答不上」",
                "note": "检索跑成了,而**一片都没选中** —— 这是真的「知识库里没有」,"
                        "和「查不了」不是一回事,可以照实告诉顾问"}
    return {
        "hit": len(片), "问的是": q, "改写成": d.get("改写"),
        "证据们": [{"出处": x["证据"], "正文": x["文"], "分数": x["分数"]}
                for x in 片],
        "知识库": d.get("知识库"),
        "试跑id": d.get("试跑id"),
        "怎么评价": "顾问觉得这次找得好不好,可以 1-5 打分 —— "
                 "把 `试跑id` 交给管理后台的「检索试跑记录」栏目",
        "note": "**出处要带给顾问**(「业务拍板 · 2026-09-27 / 二、几星算差评 · 第 4 段」)"
                " —— 一个查不回去的引用比没有引用糟:它看起来有出处。"
                "⚠️ 这几段是**原文**,里面的来源等级规矩照旧适用",
    }
