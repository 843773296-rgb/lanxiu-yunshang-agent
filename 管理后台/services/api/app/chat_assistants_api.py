#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天助手配置(用户 2026-10-28 拍「分两步」)—— 澜绣聊天站上那几个角色助手。

## 第 1 步只做后台这一半

看 / 改 / 出版本 / 审核上生产。**聊天站还没读这里**,聊天现在用的仍是代码里那一份
(`agentsite/sdk.py` 的角色 + 根目录 `prompts.py`)。每个接口的返回都带这句话 ——
> 一个「后台改了、聊天站照着跑」的配置页,和一个「后台改了、聊天站根本没读」的,
> **在这一页上长得一模一样**。所以只能靠写明。

第 2 步才接聊天站,并加「后台这一版 == 模型真收到的那一版」的核对口。

## 基线从哪来

v0 由 `tools/import_chat_assistant.py` 用聊天站自己的环境调 `prompts.assemble` 算出来,
POST 到 `/chat-assistants/import`。后台**不重写**那段拼提示词的代码。

## 规矩怎么挑(后台这边唯一的一段推算)

和 `prompts.assemble` 同一条挑法:候选池里按顺序,needs 全挂上、avoid 一个都没挂上的才装。
规矩正文和 needs / avoid 取后台导入的那份(一条一个 Prompt,`import_lanxiu_prompts.py`)。
**导入时拿真装配的结果对一遍**,对不上就拒导 —— 这段推算第一次跑就被真东西校准过,
后台里的规矩没跟上代码时也会在这儿当场露出来。
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
from workflows_api import _新id, _审计

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

还没接 = ("**还没接到聊天站** —— 聊天现在用的仍是代码里那一份(agentsite/sdk.py + prompts.py)。"
       "这里改了、上了生产,聊天站都不会变;第 2 步接上之后才生效")
可改的键 = ("开头", "结尾", "模型", "工具")


def _短名(t):
    return str(t).rsplit("__", 1)[-1]


def 挑规矩(池, 规矩们, 开着的工具, 能力标记=()):
    """→ (装上的编号[按池里的顺序], 池里有而后台没导的编号)。挑法同 `prompts.assemble`。"""
    have = {_短名(t) for t in 开着的工具} | set(能力标记)
    装, 缺 = [], []
    for i in 池:
        r = 规矩们.get(i)
        if r is None:
            缺.append(i)
            continue
        if all(n in have for n in r["needs"]) and not any(n in have for n in r["avoid"]):
            装.append(i)
    return 装, 缺


def _规矩们(c, project_id):
    """后台导入的规矩,每条取最新一版:{编号: {needs, avoid, 范围, 正文}}。只认带「铁律编号」的。"""
    rs = c.execute(text("""
        select distinct on (key) key, messages, params from prompt_versions
         where project_id=:p and params ? '铁律编号'
         order by key, version_no desc"""), {"p": project_id}).mappings().all()
    return {r["params"]["铁律编号"]: {"needs": r["params"].get("装了这些工具才发") or [],
                                    "avoid": r["params"].get("装了这些工具就不发") or [],
                                    "范围": r["params"].get("范围"),
                                    "正文": (r["messages"] or {}).get("system") or ""}
            for r in rs}


def _开着的(cfg):
    return [t["名"] for t in cfg.get("工具") or [] if t.get("开")]


def _标记(cfg):
    """能力标记:导入带来的(如「图片」)+「写」—— 开着的工具里有一个写入类就加。
    和 prompts.assemble 同一条(它拿 api.WRITE_TOOLS 现算;这里用导入时标的「写」)。
    10-29 并行会话把写纪律 TL05 改成挂「写」,导入对账当场拦下了这里没跟上的那一次。"""
    写 = any(t.get("开") and t.get("写") for t in cfg.get("工具") or [])
    return list(cfg.get("能力标记") or []) + (["写"] if 写 else [])


def 内容哈希(cfg, 规矩):
    """只算会改变模型收到什么的:开头 / 结尾 / 开着的工具 / 模型 / 装上的规矩。变更说明不进。"""
    料 = {"开头": cfg.get("开头") or "", "结尾": cfg.get("结尾") or "", "模型": cfg.get("模型"),
         "工具": sorted(_开着的(cfg)), "规矩": list(规矩)}
    return "sha256:" + hashlib.sha256(json.dumps(料, ensure_ascii=False, sort_keys=True)
                                      .encode()).hexdigest()


def _插版本(c, me, project_id, a, cfg, 规矩, 来源, 说明, 快照=None, 来源哈希=None):
    上 = c.execute(text("""select coalesce(max(version_no), -1) from chat_assistant_versions
                         where project_id=:p and chat_assistant_id=:a"""),
                   {"p": project_id, "a": a}).scalar()
    号 = 上 + 1
    c.execute(text("""
        insert into chat_assistant_versions (id, organization_id, project_id, chat_assistant_id,
            version_no, head_template, foot_template, tools, model_name, rule_pool_ids, rule_ids,
            skill_snapshot, prompt_snapshot, source_kind, source_hash, content_hash, change_note,
            created_at, created_by)
        values (:i,:o,:p,:a,:n,:h,:f,cast(:t as jsonb),:m,cast(:rp as jsonb),cast(:r as jsonb),
                cast(:sk as jsonb),cast(:ps as jsonb),:sr,:sh,:ch,:cn, now(), :u)"""),
              {"i": _新id("cav"), "o": me.org_id, "p": project_id, "a": a, "n": 号,
               "h": cfg.get("开头") or "", "f": cfg.get("结尾"),
               "t": json.dumps(_开着的(cfg), ensure_ascii=False), "m": cfg.get("模型"),
               "rp": json.dumps(cfg.get("规矩池") or [], ensure_ascii=False),
               "r": json.dumps(list(规矩), ensure_ascii=False),
               "sk": json.dumps(cfg.get("技能") or [], ensure_ascii=False),
               "ps": json.dumps(快照, ensure_ascii=False) if 快照 else None,
               "sr": 来源, "sh": 来源哈希, "ch": 内容哈希(cfg, 规矩), "cn": 说明, "u": me.user_id})
    return 号


def _最新版(c, project_id, a):
    return c.execute(text("""select version_no, content_hash from chat_assistant_versions
                             where project_id=:p and chat_assistant_id=:a
                             order by version_no desc limit 1"""),
                     {"p": project_id, "a": a}).mappings().first()


@router.get(前缀 + "/chat-assistants")
def 聊天助手列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
            含测试: bool = Query(False)):
    with 连接() as c:
        rs = c.execute(text("""
            select a.id, a.role_key, a.name, a.purpose, a.production_version_no, a.updated_at, a.definition,
                   (select max(v.version_no) from chat_assistant_versions v
                     where v.project_id=a.project_id and v.chat_assistant_id=a.id) 最新版
              from chat_assistants a
             where a.project_id=:p and a.archived_at is null
               and (:t or a.role_key not like 'e2e%')
             order by a.name, a.id"""), {"p": project_id, "t": 含测试}).mappings().all()
    return {"items": [{"id": r["id"], "角色键": r["role_key"], "名称": r["name"], "用途": r["purpose"],
                       "工具数": len(_开着的(r["definition"] or {})),
                       "最新版本": (f"v{r['最新版']}" if r["最新版"] is not None else None),
                       "生产版本": (f"v{r['production_version_no']}"
                                    if r["production_version_no"] is not None else None),
                       "更新时间": r["updated_at"].isoformat() if r["updated_at"] else None}
                      for r in rs],
            "接上了吗": False, "note": 还没接}


@router.post(前缀 + "/chat-assistants/import", status_code=201)
async def 导入基线(project_id: str, request: Request, me: 身份 = Depends(要权限("改编排草稿"))):
    """代码里那一份 → 一个「代码导入」版本。内容没变就什么都不动(反复导不出噪音版本)。"""
    体 = await request.json()
    缺键 = [k for k in ("角色键", "名称", "开头", "工具", "模型", "规矩池", "装上的规矩", "提示词全文")
          if not 体.get(k) and 体.get(k) != []]
    if 缺键:
        raise _错(422, "VALIDATION", f"快照缺这几项:{缺键}", "用 tools/import_chat_assistant.py 生成快照",
                  field_errors={k: "必填" for k in 缺键})
    cfg = {"开头": 体["开头"], "结尾": 体.get("结尾") or "", "模型": 体["模型"],
           "工具": [{"名": t["名"], "写": bool(t.get("写")), "开": True} for t in 体["工具"]],
           "能力标记": 体.get("能力标记") or [], "规矩池": 体["规矩池"],
           "可选模型": 体.get("可选模型") or [体["模型"]], "技能": 体.get("技能") or []}
    with 事务() as c:
        装, 缺 = 挑规矩(cfg["规矩池"], _规矩们(c, project_id), _开着的(cfg), _标记(cfg))
        if 缺:
            raise _错(422, "RULES_NOT_IMPORTED", f"这几条规矩后台还没有:{缺}",
                      "先跑 tools/import_lanxiu_prompts.py 把规矩导进来 —— 否则这一页列出来的规矩是缺的")
        if 装 != list(体["装上的规矩"]):
            raise _错(422, "RULE_PICK_MISMATCH",
                      "后台按导入的规矩推算出的,和代码真装上的不一样",
                      "多半是 prompts.py 改了规矩而后台没重导 —— 先跑 lanxiu_prompt_sync_check 看哪几条",
                      field_errors={"只在后台推算里": str(sorted(set(装) - set(体["装上的规矩"]))),
                                    "只在代码装配里": str(sorted(set(体["装上的规矩"]) - set(装)))})
        a = c.execute(text("""select id, definition from chat_assistants
                             where project_id=:p and role_key=:k for update"""),
                      {"p": project_id, "k": 体["角色键"]}).mappings().first()
        if not a:
            aid = _新id("ca")
            c.execute(text("""
                insert into chat_assistants (id, organization_id, project_id, role_key, name, purpose,
                    definition, draft_revision, status, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:k,:n,:pu,cast(:d as jsonb),1,'草稿', now(), :u, now(), 1)"""),
                      {"i": aid, "o": me.org_id, "p": project_id, "k": 体["角色键"], "n": 体["名称"],
                       "pu": 体.get("用途"), "d": json.dumps(cfg, ensure_ascii=False), "u": me.user_id})
            草稿 = "新建,草稿就是这一份"
        else:
            aid = a["id"]
            上 = _最新版(c, project_id, aid)
            if 上 and 上["content_hash"] == 内容哈希(cfg, 装):
                return {"id": aid, "版本": f"v{上['version_no']}", "动了吗": False,
                        "note": "和最新一版内容一样,什么都没动。" + 还没接}
            # 草稿没被人改过(还等于最新一版)才跟着换;改过的不覆盖 —— 那是别人没出版本的活。
            # ⚠️ **比草稿自己的四样(开头 / 结尾 / 模型 / 开着的工具),不比「按规矩重算的哈希」**:
            # 10-29 规矩的挑法变了(TL05 改挂「写」),一份没人动过的草稿重算出来哈希也变了,
            # 被当成「有没出版本的改动」而没换 —— 规矩在它脚下变了,不等于有人改了草稿。
            旧 = a["definition"] or {}
            上行 = c.execute(text("""select head_template, foot_template, model_name, tools
                                    from chat_assistant_versions where project_id=:p and chat_assistant_id=:a
                                    order by version_no desc limit 1"""), {"p": project_id, "a": aid}).mappings().first()
            if not 上行 or ((旧.get("开头") or "") == 上行["head_template"] and (旧.get("结尾") or "") == (上行["foot_template"] or "")
                          and 旧.get("模型") == 上行["model_name"] and sorted(_开着的(旧)) == sorted(上行["tools"] or [])):
                c.execute(text("""update chat_assistants set definition=cast(:d as jsonb), updated_at=now(),
                                      draft_revision=coalesce(draft_revision,0)+1
                                  where project_id=:p and id=:i"""),
                          {"d": json.dumps(cfg, ensure_ascii=False), "p": project_id, "i": aid})
                草稿 = "草稿没被改过,换成了这一份"
            else:
                草稿 = "⚠️ 草稿有没出版本的改动,没覆盖 —— 新导入的只进了版本"
        号 = _插版本(c, me, project_id, aid, cfg, 装, "代码导入",
                   体.get("变更说明") or "从代码导入(prompts.assemble 装配的那一份)",
                   快照={"提示词全文": 体["提示词全文"], "装配": "prompts.assemble(真跑)"},
                   来源哈希="sha256:" + hashlib.sha256(体["提示词全文"].encode()).hexdigest())
    return {"id": aid, "版本": f"v{号}", "动了吗": True, "草稿": 草稿, "note": 还没接}


@router.get(前缀 + "/chat-assistants/by-role/{role}/production")
def 生产版本(project_id: str, role: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """给聊天站拉:这个角色的生产指针指着哪一版、那一版的内容(第 2 步用)。

    没指定生产 → `版本号: null`,聊天站照用代码里那一份 —— 和「没配地址」「拉不到」是同一个落点,
    **不许在这里替它挑「最新那一版」**:出了版本 ≠ 上了生产,那是审核那一步的事。"""
    with 连接() as c:
        a = c.execute(text("""select id, production_version_no from chat_assistants
                             where project_id=:p and role_key=:k and archived_at is null"""),
                      {"p": project_id, "k": role}).mappings().first()
        if not a:
            raise _错(404, "NOT_FOUND", f"没有角色 {role} 的聊天助手", "先用 import_chat_assistant.py 导入")
        if a["production_version_no"] is None:
            return {"角色键": role, "版本号": None, "note": "没指定生产 —— 聊天站照用代码里那一份"}
        v = c.execute(text("""select version_no, head_template, foot_template, tools, model_name, rule_ids,
                                     content_hash, source_kind, source_hash from chat_assistant_versions
                               where project_id=:p and chat_assistant_id=:a and version_no=:n"""),
                      {"p": project_id, "a": a["id"], "n": a["production_version_no"]}).mappings().first()
    if not v:      # 指针存的是版本号、库里没外键(见契约)—— 指着一个不存在的版本要明说,不当成「没指定」
        raise _错(409, "PRODUCTION_DANGLING", f"生产指着 v{a['production_version_no']},而这一版不在了",
                  "回详情重新上一次生产")
    return {"角色键": role, "版本号": v["version_no"], "开头": v["head_template"], "结尾": v["foot_template"] or "",
            "工具": v["tools"] or [], "模型": v["model_name"], "规矩": v["rule_ids"] or [],
            "内容哈希": v["content_hash"], "来源": v["source_kind"],
            # 只有「代码导入」的版本存着当时真组装出的全文哈希 —— 核对口拿它逐字比;后台编辑出的没有,核对口要明说没比
            "全文哈希": v["source_hash"] if v["source_kind"] == "代码导入" else None}


def _取(c, project_id, cid, 锁=False):
    a = c.execute(text("select * from chat_assistants where project_id=:p and id=:i"
                       + (" for update" if 锁 else "")), {"p": project_id, "i": cid}).mappings().first()
    if not a:
        raise _错(404, "NOT_FOUND", "没有这个聊天助手", "回列表重新进入")
    return a


@router.get(前缀 + "/chat-assistants/{cid}")
def 聊天助手详情(project_id: str, cid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        a = _取(c, project_id, cid)
        规矩们 = _规矩们(c, project_id)
        vs = c.execute(text("""
            select version_no, source_kind, content_hash, change_note, model_name, tools, rule_ids,
                   created_at, created_by
              from chat_assistant_versions where project_id=:p and chat_assistant_id=:a
             order by version_no desc limit 50"""), {"p": project_id, "a": cid}).mappings().all()
    cfg = a["definition"] or {}
    装, 缺 = 挑规矩(cfg.get("规矩池") or [], 规矩们, _开着的(cfg), _标记(cfg))
    哈希 = 内容哈希(cfg, 装)
    return {
        "id": a["id"], "角色键": a["role_key"], "名称": a["name"], "用途": a["purpose"],
        "草稿": {"revision": a["draft_revision"], "配置": {k: cfg.get(k) for k in 可改的键},
                "可选模型": cfg.get("可选模型") or [], "和哪一版一样": next(
                    (f"v{v['version_no']}" for v in vs if v["content_hash"] == 哈希), None)},
        "规矩": {"说明": "按后台导入的规矩推算(和 prompts.assemble 同一条挑法:跟着开着的工具走)—— "
                       "**推算 ≠ 聊天站真装上的**,第 2 步的核对口才验得了",
                "装上": [{"编号": i, "范围": 规矩们[i]["范围"], "跟着哪些工具": 规矩们[i]["needs"],
                         "正文": 规矩们[i]["正文"]} for i in 装],
                "后台没有的": 缺},
        "技能": {"当时放行的": cfg.get("技能") or [],
                "说明": "技能被调起时**另带一份规矩**(SKILL.md 自己定的格式和段名),不在这一页里"},
        "版本们": [{"版本": f"v{v['version_no']}", "来源": v["source_kind"],
                  "内容哈希": (v["content_hash"] or "")[:19] + "…", "变更说明": v["change_note"],
                  "模型": v["model_name"], "工具数": len(v["tools"] or []), "规矩数": len(v["rule_ids"] or []),
                  "生产": v["version_no"] == a["production_version_no"],
                  "冻结于": v["created_at"].isoformat() if v["created_at"] else None,
                  "冻结人": v["created_by"]} for v in vs],
        "生产版本": (f"v{a['production_version_no']}" if a["production_version_no"] is not None else None),
        "接上了吗": False, "note": 还没接,
    }


@router.patch(前缀 + "/chat-assistants/{cid}/draft")
async def 改聊天助手草稿(project_id: str, cid: str, request: Request,
                   if_match: str = Header(default=None, alias="If-Match"),
                   me: 身份 = Depends(要权限("改编排草稿"))):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把详情里草稿的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    新 = 体.get("配置")
    if not isinstance(新, dict):
        raise _错(422, "VALIDATION", "配置要是一个对象", "检查提交的 JSON 形状")
    with 事务() as c:
        a = _取(c, project_id, cid, 锁=True)
        if str(a["draft_revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT",
                      f"这份配置已经被改过(你拿的是 {if_match},现在是 {a['draft_revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖**",
                      field_errors={"revision": f"当前 {a['draft_revision']}"})
        cfg = dict(a["definition"] or {})
        if not (新.get("开头") or "").strip():
            raise _错(422, "VALIDATION", "开头提示词不能空", "它是模型收到的第一段话",
                      field_errors={"开头": "必填"})
        if 新.get("模型") not in (cfg.get("可选模型") or []):
            raise _错(422, "VALIDATION", f"模型「{新.get('模型')}」不在聊天站能选的清单里",
                      "清单随导入从聊天站带过来(按有没有单价)", field_errors={"模型": "不可选"})
        # 工具只能在导入带来的那几个里开关 —— 聊天站这个角色只挂了这些,后台加不出别的
        全 = {t["名"]: t for t in cfg.get("工具") or []}
        开 = {t["名"]: bool(t.get("开")) for t in 新.get("工具") or [] if isinstance(t, dict)}
        多 = sorted(set(开) - set(全))
        if 多:
            raise _错(422, "VALIDATION", f"这几个工具聊天站这个角色没有:{多}",
                      "工具清单随导入从聊天站带过来,这里只能开关", field_errors={"工具": "未知工具"})
        cfg.update({"开头": 新["开头"], "结尾": 新.get("结尾") or "", "模型": 新["模型"],
                    "工具": [{**t, "开": 开.get(n, t.get("开"))} for n, t in 全.items()]})
        版 = int(a["draft_revision"]) + 1
        c.execute(text("""update chat_assistants set definition=cast(:d as jsonb), draft_revision=:r,
                              updated_at=now() where project_id=:p and id=:i"""),
                  {"d": json.dumps(cfg, ensure_ascii=False), "r": 版, "p": project_id, "i": cid})
    return {"revision": 版, "note": "草稿已保存。**不影响任何版本,也不影响生产。**" + 还没接}


@router.post(前缀 + "/chat-assistants/{cid}/versions", status_code=201)
async def 出聊天助手版本(project_id: str, cid: str, request: Request,
                   me: 身份 = Depends(要权限("改编排草稿"))):
    说明 = ((await request.json()).get("变更说明") or "").strip()
    if not 说明:
        raise _错(422, "CHANGE_NOTE_REQUIRED", "变更说明必填", "写一句「这一版改了什么、为什么」",
                  field_errors={"变更说明": "必填"})
    with 事务() as c:
        a = _取(c, project_id, cid, 锁=True)
        cfg = a["definition"] or {}
        装, 缺 = 挑规矩(cfg.get("规矩池") or [], _规矩们(c, project_id), _开着的(cfg), _标记(cfg))
        if 缺:
            raise _错(422, "RULES_NOT_IMPORTED", f"这几条规矩后台还没有:{缺}",
                      "先跑 tools/import_lanxiu_prompts.py —— 缺着规矩出的版本,列出来的规矩是不全的")
        上 = _最新版(c, project_id, cid)
        if 上 and 上["content_hash"] == 内容哈希(cfg, 装):
            raise _错(409, "NO_SEMANTIC_CHANGE", f"和 v{上['version_no']} 的内容完全一样",
                      "改了才出版本 —— 一串内容相同的版本号会让「版本变了」失去含义")
        号 = _插版本(c, me, project_id, cid, cfg, 装, "后台编辑", 说明)
    return {"版本": f"v{号}", "note": "**出了版本,没上生产。**" + 还没接}


@router.post(前缀 + "/chat-assistants/{cid}/production")
async def 聊天助手上生产(project_id: str, cid: str, request: Request,
                   me: 身份 = Depends(要权限("生产审核/发布/回滚"))):
    体 = await request.json()
    号 = 体.get("版本号")
    if not isinstance(号, int) or isinstance(号, bool):
        raise _错(422, "VALIDATION", "版本号要是整数", "给要上生产的那一版的号(v3 就给 3)",
                  field_errors={"版本号": "要整数"})
    with 事务() as c:
        a = _取(c, project_id, cid, 锁=True)
        # 生产指针存的是版本号,库里没外键 —— 「指着的那一版存在」只靠这一句(见契约)
        有 = c.execute(text("""select 1 from chat_assistant_versions
                              where project_id=:p and chat_assistant_id=:a and version_no=:n"""),
                       {"p": project_id, "a": cid, "n": 号}).first()
        if not 有:
            raise _错(404, "NOT_FOUND", f"这个助手没有 v{号}", "回详情看版本列表")
        之前 = a["production_version_no"]
        if 之前 == 号:
            raise _错(409, "NO_CHANGE", f"生产已经是 v{号}", "不用再上一次")
        c.execute(text("""update chat_assistants set production_version_no=:n, production_set_at=now(),
                              production_set_by=:u, updated_at=now() where project_id=:p and id=:i"""),
                  {"n": 号, "u": me.user_id, "p": project_id, "i": cid})
        _审计(c, me, "chat_assistant.deploy",
              {"chat_assistant_id": cid, "角色键": a["role_key"], "名称": a["name"],
               "之前": (f"v{之前}" if 之前 is not None else None), "之后": f"v{号}"},
              (体.get("理由") or "").strip() or None)
    return {"生产版本": f"v{号}", "之前": (f"v{之前}" if 之前 is not None else None), "note": 还没接}
