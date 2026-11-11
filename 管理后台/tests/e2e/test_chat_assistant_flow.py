"""聊天助手配置 · 端到端(2026-10-28,用户拍「聊天助手配置页分两步」,这是第 1 步:后台这一半)。
真服务 + 真库。快照由测试**自己造**(CI 上没有聊天站环境,真导入脚本要它);角色键 e2e_task,列表默认藏起来。

规矩挑法的期望值**测试自己按规矩草稿里的 needs / avoid 算**,不调后台那段推算 —— 拿被测代码算期望值等于没验。

  ① 快照里「装上的规矩」和后台推算对不上 → 422 RULE_PICK_MISMATCH;池里有后台没导的规矩 → 422 RULES_NOT_IMPORTED
  ② 对得上 → 导入成功;原样再导一次 → 什么都不动(同一版)
  ③ 列表默认不出 e2e 的;详情里装上的规矩 == 测试自己算的,写入类工具标着
  ④ 改草稿:不带 If-Match / 旧 revision → 409;未知工具、清单外的模型 → 422;
     关掉某条规矩跟着的那个工具 → 那条规矩不再装上
  ⑤ 出版本:没说明 422;出一版;内容没变再出 409
  ⑥ 上生产:版本号不是整数 422、没有的版本 404、换上 200 且工作台「开关」记着、再换同一版 409
  ⑦ 权限:编辑者上生产 403(演示项目里的 editor)
  ⑧ 接没接按角色说实话:测试角色 e2e_task 聊天站没读 → 每个返回都说「还没读这里」、详情 接上了吗 = False
    (店长助手 task 接上了那一半在 test_workflow_editor_browser 里对真数据验)
"""
import ast
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
P = "/api/v1/projects/project_lanxiu"
角色 = "e2e_task"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U001", 体=None, 头=None):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
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


def 码(d):
    return ((d or {}).get("error") or d or {}).get("code")


def 规矩样本():
    """后台导入的规矩里挑几条:{编号: (needs, avoid)}。要有「跟着某个工具」的,也要有「总带着」的。"""
    s, d = 打("GET", f"{P}/prompts?limit=100")
    if s != 200:
        return {}
    out = {}
    for it in d["items"]:
        if not (it["key"][:2] in ("TL", "TK")):
            continue
        s, x = 打("GET", f"{P}/prompts/{it['id']}")
        pa = ((x or {}).get("草稿") or {}).get("params") or {}
        if "铁律编号" in pa:
            out[pa["铁律编号"]] = (pa.get("装了这些工具才发") or [], pa.get("装了这些工具就不发") or [])
        if len(out) >= 40:
            break
    return out


def 我算(池, 规矩, 开着, 写的=()):
    """开着的里有写入类 → 多一个能力标记「写」(10-29 起写纪律 TL05 挂它)。"""
    have = {t.rsplit("__", 1)[-1] for t in 开着} | ({"写"} if set(开着) & set(写的) else set())
    return [i for i in 池 if all(n in have for n in 规矩[i][0]) and not any(n in have for n in 规矩[i][1])]


def main():
    print("聊天助手配置 · 端到端(第 1 步:后台这一半)\n")
    规矩 = 规矩样本()
    跟工具 = [i for i, (n, a) in 规矩.items() if len(n) == 1 and not a and n[0] not in ("写", "图片")]
    总带 = [i for i, (n, a) in 规矩.items() if not n and not a]
    ck(f"样本够:跟着一个工具的 {len(跟工具)} 条、总带着的 {len(总带)} 条(各至少 1)", 跟工具 and 总带,
       "project_lanxiu 里没导规矩?CI 要先跑 import_lanxiu_prompts.py")
    if not (跟工具 and 总带):
        return 1
    靶 = 跟工具[0]
    靶工具 = f"mcp__e2e__{规矩[靶][0][0]}"
    池 = sorted(规矩)
    工具 = [{"名": 靶工具, "写": True}, {"名": "mcp__e2e__只读那个", "写": False}]
    期望 = 我算(池, 规矩, [t["名"] for t in 工具], [靶工具])
    ck(f"自造的这份里,「{靶}」会被装上(它跟着的工具开着)", 靶 in 期望)
    快 = {"角色键": 角色, "名称": "端到端测试助手", "用途": "测试用", "开头": "你是测试助手。\n## 铁律\n", "结尾": "",
         "工具": 工具, "能力标记": [], "模型": "claude:claude-haiku-5-5",
         "可选模型": ["claude:claude-haiku-5-5", "claude:claude-opus-5-5"],
         "规矩池": 池, "装上的规矩": 期望, "提示词全文": "(测试造的)", "技能": ["roster"]}

    print("▸ ① 导入要和后台推算对得上")
    s, d = 打("POST", f"{P}/chat-assistants/import", 体={**快, "装上的规矩": [x for x in 期望 if x != 靶]})
    ck("少报一条 → 422 RULE_PICK_MISMATCH", s == 422 and 码(d) == "RULE_PICK_MISMATCH", (s, d))
    fe = ((d or {}).get("error") or d or {}).get("field_errors") or {}
    ck("并点名多出来的就是那一条", 靶 in ast.literal_eval(fe.get("只在后台推算里", "[]")), fe)
    s, d = 打("POST", f"{P}/chat-assistants/import", 体={**快, "规矩池": 池 + ["TZ999"]})
    ck("池里有后台没导的 → 422 RULES_NOT_IMPORTED", s == 422 and 码(d) == "RULES_NOT_IMPORTED", (s, d))

    print("\n▸ ② 导入;原样再导什么都不动")
    s, d = 打("POST", f"{P}/chat-assistants/import", 体=快)
    ck("导入 201", s == 201, (s, d))
    cid = (d or {}).get("id")
    s2, d2 = 打("POST", f"{P}/chat-assistants/import", 体=快)
    ck("再导一次:动了吗 = False、还是同一版", s2 == 201 and d2.get("动了吗") is False and d2.get("版本") == d.get("版本"),
       (s2, d2))
    ck("测试角色聊天站没读:返回写明「聊天站还没读这里」", "聊天站还没读这里" in (d2 or {}).get("note", ""), d2)
    if not cid:
        return 1

    print("\n▸ ③ 列表与详情")
    s, l = 打("GET", f"{P}/chat-assistants")
    ck("列表默认不出 e2e 的", s == 200 and all(x["角色键"] != 角色 for x in l["items"]), l)
    s, l = 打("GET", f"{P}/chat-assistants?含测试=true")
    ck("含测试=true 时出", s == 200 and any(x["id"] == cid for x in l["items"]))
    s, g = 打("GET", f"{P}/chat-assistants/{cid}")
    ck("详情里装上的规矩 == 测试自己算的", [r["编号"] for r in g["规矩"]["装上"]] == 期望,
       ([r["编号"] for r in g["规矩"]["装上"]], 期望))
    ck("写入类工具标着", any(t["名"] == 靶工具 and t["写"] for t in g["草稿"]["配置"]["工具"]))
    ck("技能那一栏说明技能另带规矩", "另带" in g["技能"]["说明"])
    ck("测试角色聊天站没读:详情 接上了吗 = False(不许把没接的说成接上了)", g.get("接上了吗") is False, g.get("接上了吗"))
    rv = g["草稿"]["revision"]

    print("\n▸ ④ 改草稿")
    改 = json.loads(json.dumps(g["草稿"]["配置"]))
    for t in 改["工具"]:
        if t["名"] == 靶工具:
            t["开"] = False
    s, d = 打("PATCH", f"{P}/chat-assistants/{cid}/draft", 体={"配置": 改})
    ck("不带 If-Match → 409", s == 409 and 码(d) == "IF_MATCH_REQUIRED", (s, d))
    s, d = 打("PATCH", f"{P}/chat-assistants/{cid}/draft", 体={"配置": 改}, 头={"If-Match": str(rv - 1)})
    ck("旧 revision → 409 REVISION_CONFLICT", s == 409 and 码(d) == "REVISION_CONFLICT", (s, d))
    s, d = 打("PATCH", f"{P}/chat-assistants/{cid}/draft", 头={"If-Match": str(rv)},
             体={"配置": {**改, "工具": 改["工具"] + [{"名": "mcp__x__没有这个", "开": True}]}})
    ck("未知工具 → 422", s == 422, (s, d))
    s, d = 打("PATCH", f"{P}/chat-assistants/{cid}/draft", 头={"If-Match": str(rv)},
             体={"配置": {**改, "模型": "claude:不在清单里"}})
    ck("清单外的模型 → 422", s == 422, (s, d))
    s, d = 打("PATCH", f"{P}/chat-assistants/{cid}/draft", 头={"If-Match": str(rv)}, 体={"配置": 改})
    ck("关掉一个工具 → 200", s == 200, (s, d))
    s, g = 打("GET", f"{P}/chat-assistants/{cid}")
    装 = [r["编号"] for r in g["规矩"]["装上"]]
    ck(f"「{靶}」跟着它的工具一起下去了,其余照旧", 靶 not in 装 and 装 == 我算(池, 规矩, ["mcp__e2e__只读那个"], [靶工具]), 装)

    print("\n▸ ⑤ 出版本")
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/versions", 体={})
    ck("没变更说明 → 422", s == 422 and 码(d) == "CHANGE_NOTE_REQUIRED", (s, d))
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/versions", 体={"变更说明": "e2e:关掉写入工具"})
    ck("出一版 201", s == 201, (s, d))
    号 = int((d or {}).get("版本", "v-1")[1:])
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/versions", 体={"变更说明": "e2e:没改又出"})
    ck("内容没变再出 → 409 NO_SEMANTIC_CHANGE", s == 409 and 码(d) == "NO_SEMANTIC_CHANGE", (s, d))

    print("\n▸ ⑥ 上生产")
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/production", 体={"版本号": str(号)})
    ck("版本号给成字符串 → 422", s == 422, (s, d))
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/production", 体={"版本号": 99999})
    ck("没有的版本 → 404", s == 404, (s, d))
    s, g = 打("GET", f"{P}/chat-assistants/{cid}")
    if g.get("生产版本") == f"v{号}":      # 上一轮留下的:先换到另一版,好让这一轮真换一次
        打("POST", f"{P}/chat-assistants/{cid}/production", 体={"版本号": 0})
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/production", 体={"版本号": 号, "理由": "e2e 上生产"})
    ck(f"换到 v{号} → 200", s == 200 and d.get("生产版本") == f"v{号}", (s, d))
    s, d = 打("POST", f"{P}/chat-assistants/{cid}/production", 体={"版本号": 号})
    ck("再换同一版 → 409", s == 409, (s, d))
    s, w = 打("GET", f"{P}/switches?天=1")
    记 = [x for x in (w or {}).get("最近变动", []) if x.get("开关") == "聊天助手生产版本" and x.get("对象") == "端到端测试助手"]
    ck("工作台「开关」记着这次换版,从哪版到哪版写清楚", 记 and 记[0]["到"] == f"v{号}" and 记[0]["理由"] == "e2e 上生产",
       记[:1] or list((w or {}).keys()))

    s, pv = 打("GET", f"{P}/chat-assistants/by-role/{角色}/production")
    ck(f"按角色取生产(给聊天站拉):就是 v{号},工具是关掉那个之后的", s == 200 and pv.get("版本号") == 号
       and 靶工具 not in pv.get("工具", []) and "mcp__e2e__只读那个" in pv.get("工具", []), (s, pv))
    s, d = 打("GET", f"{P}/chat-assistants/by-role/没有这个角色/production")
    ck("没有这个角色 → 404", s == 404, (s, d))

    print("\n▸ ⑦ 权限")
    s, d = 打("POST", "/api/v1/projects/project_demo_a/chat-assistants/随便/production", 谁="U002", 体={"版本号": 1})
    ck("编辑者(演示项目 U002)上生产 → 403", s == 403, (s, d))
    s, d = 打("POST", "/api/v1/projects/project_demo_a/chat-assistants/随便/production", 谁="U001", 体={"版本号": 1})
    ck("管理员过得了权限闸(没这个助手 → 404,不是 403)", s == 404, (s, d))

    print("\n▸ ⑧ 演示项目里导一个最小的(规矩池空):空池也导得进;详情页冒烟在演示项目里要有样例")
    s, d = 打("POST", "/api/v1/projects/project_demo_a/chat-assistants/import", 体={**快, "角色键": "e2e_demo",
             "名称": "演示测试助手", "规矩池": [], "装上的规矩": []})
    ck("空规矩池 → 导得进(201)", s == 201, (s, d))
    s, pv = 打("GET", "/api/v1/projects/project_demo_a/chat-assistants/by-role/e2e_demo/production")
    ck("没指定生产 → 版本号 null(聊天站照用代码),不替它挑最新那一版", s == 200 and pv.get("版本号") is None, (s, pv))
    ck("没指定生产时也带着 glossary_version_id 这个键、值是 null(聊天站把「字段缺失」当成契约没同步,和「没挂术语」分开)",
       s == 200 and "glossary_version_id" in pv and pv["glossary_version_id"] is None, pv)

    print("\n▸ ⑨ 术语版本(11-06):聊天助手选一版术语 → 出版本 → 上生产 → 按角色取生产给出这一版的 id")
    D = "/api/v1/projects/project_demo_a"
    # 用单独一个角色 e2e_terms:上生产的指针放不回「没指定」(没有这个口),挪用 e2e_demo 会让下一轮 ⑧ 那条「没指定生产」红
    打("POST", f"{D}/chat-assistants/import", 体={**快, "角色键": "e2e_terms", "名称": "术语测试助手", "规矩池": [], "装上的规矩": []})
    s, l = 打("GET", f"{D}/chat-assistants?含测试=true")
    did = next((x["id"] for x in (l or {}).get("items", []) if x["角色键"] == "e2e_terms"), None)
    ck("前提:导入术语测试助手 e2e_terms", bool(did), l)
    s, g = 打("GET", f"{D}/chat-assistants/{did}")
    ck("草稿配置里有「术语版本」这一项(详情页要能显示当前选的哪一版)", s == 200 and "术语版本" in g["草稿"]["配置"], (s, g.get("草稿")))
    # 测试自己造一版冻结的术语(演示项目;CI 是新库,不依赖别的测试留下的)
    import uuid
    s, gl = 打("POST", f"{D}/glossaries", 谁="U002", 体={"key": "e2e-chat-" + uuid.uuid4().hex[:6]})
    gid = (gl or {}).get("id")
    打("PATCH", f"{D}/glossaries/{gid}/draft", 谁="U002", 头={"If-Match": "1"},
      体={"术语": [{"标准词": "褙子", "叫法": ["长褙"], "类别": "名词", "定义": "宋制对襟长衣"}]})
    s, gv = 打("POST", f"{D}/glossaries/{gid}/versions", 谁="U002")
    vid = (gv or {}).get("id")
    ck("前提:冻出一版术语", s == 201 and vid, (s, gv))
    配 = dict(g["草稿"]["配置"])
    rv = g["草稿"]["revision"]
    s, d = 打("PATCH", f"{D}/chat-assistants/{did}/draft", 头={"If-Match": str(rv)}, 体={"配置": {**配, "术语版本": "glv_不存在的"}})
    ck("选一个不存在的术语版本 → 422 REF_NOT_FOUND(不存一个悬空引用)", s == 422 and 码(d) == "REF_NOT_FOUND", (s, d))
    s, d = 打("PATCH", f"{D}/chat-assistants/{did}/draft", 头={"If-Match": str(rv)}, 体={"配置": {**配, "glossary_version_id": vid}})
    ck("照着读出口的英文键 glossary_version_id 来写 → 422 点名该用「术语版本」(不许静默不生效)",
       s == 422 and 码(d) == "VALIDATION" and "glossary_version_id" in (((d or {}).get("error") or d or {}).get("field_errors") or {}), (s, d))
    s, d = 打("PATCH", f"{D}/chat-assistants/{did}/draft", 头={"If-Match": str(rv)}, 体={"配置": {**配, "术语版本": vid}})
    ck("选这一版 → 200", s == 200, (s, d))
    s, g2 = 打("GET", f"{D}/chat-assistants/{did}")
    s, d = 打("PATCH", f"{D}/chat-assistants/{did}/draft", 头={"If-Match": str(g2["草稿"]["revision"])},
             体={"配置": {k: v for k, v in g2["草稿"]["配置"].items() if k != "术语版本"}})
    s, g3 = 打("GET", f"{D}/chat-assistants/{did}")
    ck("再提交时**没带**「术语版本」这个键 → 已选的不动(老页面提交不会把术语悄悄清掉)",
       g3["草稿"]["配置"].get("术语版本") == vid, g3["草稿"]["配置"].get("术语版本"))
    s, v = 打("POST", f"{D}/chat-assistants/{did}/versions", 体={"变更说明": "e2e:挂上术语"})
    ck("挂上术语算内容变了 → 出得了新版本(201,不是「内容没变」409)", s == 201, (s, v))
    号 = int((v or {}).get("版本", "v-1")[1:])
    s, d = 打("POST", f"{D}/chat-assistants/{did}/production", 体={"版本号": 号, "理由": "e2e 挂术语上生产"})
    s, pv = 打("GET", f"{D}/chat-assistants/by-role/e2e_terms/production")
    ck("按角色取生产:glossary_version_id 就是选的那一版(聊天站拿它去取术语)",
       s == 200 and pv.get("版本号") == 号 and pv.get("glossary_version_id") == vid, (s, pv))
    s, pv = 打("GET", f"{P}/chat-assistants/by-role/{角色}/production")
    ck("没挂术语的那一版:glossary_version_id 是显式 null,不是字段缺失",
       s == 200 and "glossary_version_id" in pv and pv["glossary_version_id"] is None, pv)

    print("\n▸ ⑩ 只同步技能清单(11-11):只换技能,挂好的术语不丢;空清单不收;上生产后按角色取生产带出技能")
    s, g4 = 打("GET", f"{D}/chat-assistants/{did}")
    术前 = g4["草稿"]["配置"].get("术语版本")
    s, d = 打("POST", f"{D}/chat-assistants/{did}/skills-sync", 体={"技能": []})
    ck("空清单 → 422(那等于把助手的技能全摘了)", s == 422 and 码(d) == "VALIDATION", (s, d))
    s, d = 打("POST", f"{D}/chat-assistants/{did}/skills-sync", 体={"技能": ["../etc"]})
    ck("技能名带斜杠 → 422", s == 422, (s, d))
    新技能 = ["e2e-skill-a", "e2e-skill-b-" + uuid.uuid4().hex[:4]]
    s, d = 打("POST", f"{D}/chat-assistants/{did}/skills-sync", 体={"技能": [" " + 新技能[0], 新技能[1], 新技能[0]]})
    ck("同步 → 200、去空白去重保序", s == 200 and d.get("技能") == 新技能 and d.get("动了吗") is True, (s, d))
    s, g5 = 打("GET", f"{D}/chat-assistants/{did}")
    ck("草稿上挑好的术语版本没丢(这条就是不让人重跑导入的理由)", g5["草稿"]["配置"].get("术语版本") == 术前 and 术前, (术前, g5["草稿"]["配置"].get("术语版本")))
    ck("详情里技能清单就是同步过去的那份", (g5.get("技能") or {}).get("当时放行的") == 新技能, g5.get("技能"))
    s, d = 打("POST", f"{D}/chat-assistants/{did}/skills-sync", 体={"技能": 新技能})
    ck("原样再同步 → 什么都不动", s == 200 and d.get("动了吗") is False, (s, d))
    s, v = 打("POST", f"{D}/chat-assistants/{did}/versions", 体={"变更说明": "e2e:同步技能清单"})
    号 = int((v or {}).get("版本", "v-1")[1:])
    打("POST", f"{D}/chat-assistants/{did}/production", 体={"版本号": 号, "理由": "e2e 同步技能上生产"})
    s, pv = 打("GET", f"{D}/chat-assistants/by-role/e2e_terms/production")
    ck("按角色取生产带出「技能」(import_chat_assistant.py --核对技能 拿它比聊天站现算的)",
       s == 200 and pv.get("版本号") == 号 and pv.get("技能") == 新技能, (s, pv))

    print("\n▸ ⑪ 生效状态(11-11):目标版本 / 实际版本并排;聊天站不读的角色报「拿不到实际」,不许算一致")
    s, ad = 打("GET", f"{D}/chat-assistants/by-role/e2e_terms/adoption")
    ck("非店长助手 → 四项都是「拿不到实际」、都一致吗=False、目标版本就是生产那一版",
       s == 200 and {r["状态"] for r in ad.get("行", [])} == {"拿不到实际"} and ad.get("都一致吗") is False
       and ad.get("目标版本") == 号 and len(ad.get("行", [])) == 4, (s, ad))
    print(f"\n{'✅' if not 挂 else '❌'} {len(过)} 过 / {len(挂)} 挂" + (f":{' / '.join(挂)}" if 挂 else ""))
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
