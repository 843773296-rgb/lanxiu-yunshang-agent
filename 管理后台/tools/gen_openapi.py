#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从契约登记表生成 OpenAPI 3.1 —— **生成的,不要手改**(规格 §17.4 第 1 步)。

## 为什么把权限写进 OpenAPI

规格 §22 要求交付「OpenAPI 文档、适配器契约、**权限矩阵**」。
把「这条接口要哪条权限」只留在代码里的后果是:**没有任何一处能一次看全** ——
于是漏掉一条的时候没有东西会报错,只有那条接口悄悄对所有人开放。

所以每条路径都带 `x-权限` 和 `x-字段权限`。它们是 OpenAPI 扩展字段,
工具链会忽略,但**人和 review 看得见**,而且可以被机器比对。

## 为什么不用 FastAPI 自动生成

反了。规格说「先建对象关系、状态机、**OpenAPI** 与权限矩阵;**生成前端类型**」——
契约在前,代码在后。让 FastAPI 从 handler 反推 OpenAPI 的话,
**契约就变成了实现的影子**:handler 漏了一个鉴权,OpenAPI 跟着漏,
而它看起来仍然是一份完整的契约。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "contract"))
import endpoints as EP, errors as ER, states as ST, perms as PM

出 = os.path.join(ROOT, "packages", "contracts", "openapi.json")


def 错误体():
    return {"type": "object",
            "required": ["code", "message", "retryable", "advice"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "field_errors": {"type": "object", "additionalProperties": {"type": "string"}},
                # **显式** —— 客户端猜不出来能不能重试,而猜错的两个方向代价都很大
                "retryable": {"type": "boolean"},
                "trace_id": {"type": ["string", "null"]},
                # 规格 §19.1 要求「可执行建议」;这里设成必填
                "advice": {"type": "string",
                           "description": "下一步该干什么。写不出来说明还没搞清失败原因"}}}


def 列表体():
    return {"type": "object",
            "required": ["items", "next_cursor", "total"],
            "properties": {
                "items": {"type": "array", "items": {"type": "object"}},
                "next_cursor": {"type": ["string", "null"]},
                # ⚠️ **未知要给 null,不许给 0** —— 0 会被读成「一条都没有」
                "total": {"type": ["integer", "null"],
                          "description": "未知时必须是 null。**不许用 0 表示「我没数」**"}}}


def 异步体():
    return {"type": "object",
            "required": EP.异步信封字段,
            "properties": {
                "job_id": {"type": "string"},
                "status": {"type": "string",
                           "enum": ST.找("job")["状态"],
                           "description": "**不许返回「已完成」来冒充同步执行**"},
                "resource_id": {"type": ["string", "null"]},
                "status_url": {"type": "string"},
                "trace_id": {"type": ["string", "null"]}}}


def 建():
    错 = {"$ref": "#/components/schemas/Error"}
    公共错 = {str(k): {"description": v, "content": {"application/json": {"schema": 错}}}
              for k, v in ER.状态语义.items()}

    paths = {}
    for a in EP.接口表:
        全路径 = EP.前缀 + a["路径"]
        参数 = [{"name": "project_id", "in": "path", "required": True,
                 "schema": {"type": "string"},
                 "description": "**服务端重新校验项目权限与对象范围** —— "
                                "改这个 ID 绕不过授权(§19.1)"}]
        for 段 in a["路径"].split("/"):
            if 段.startswith("{") and 段.endswith("}"):
                参数.append({"name": 段[1:-1], "in": "path", "required": True,
                             "schema": {"type": "string"}})
        if a["列表"]:
            参数 += [{"name": "cursor", "in": "query", "schema": {"type": "string"}},
                     {"name": "limit", "in": "query",
                      "schema": {"type": "integer", "minimum": 1, "maximum": 200}}]
        if a["乐观锁"]:
            参数.append({"name": "If-Match", "in": "header", "required": True,
                         "schema": {"type": "string"},
                         "description": "**必填**。不要的话就是「最后写的人赢」,"
                                        "而输的那个人看不到自己的改动被覆盖了。"
                                        "不匹配返回 409"})
        if a["幂等"]:
            参数.append({"name": "Idempotency-Key", "in": "header", "required": True,
                         "schema": {"type": "string"},
                         "description": "**必填**。相同键相同请求返回原任务;"
                                        "相同键不同请求返回 409。"
                                        "超时重发一次的代价是重复烧 GPU 或重复计费"})

        回 = dict(公共错)
        if a["形态"] == EP.异步:
            回["202"] = {"description": "已受理,去 status_url 看进度",
                         "content": {"application/json":
                                     {"schema": {"$ref": "#/components/schemas/AsyncAccepted"}}}}
        elif a["形态"] == EP.流:
            回["200"] = {"description": "SSE 事件流,按 seq 续传(断线重连不从头重放)",
                         "content": {"text/event-stream": {"schema": {"type": "string"}}}}
        elif a["方法"] == "POST" and not a["路径"].endswith(("/complete",)):
            回["201"] = {"description": "已创建",
                         "content": {"application/json": {"schema": {"type": "object"}}}}
        if a["列表"]:
            回["200"] = {"description": "分页列表",
                         "content": {"application/json":
                                     {"schema": {"$ref": "#/components/schemas/ListEnvelope"}}}}
        elif a["形态"] == EP.读:
            回["200"] = {"description": "详情",
                         "content": {"application/json": {"schema": {"type": "object"}}}}
        if a["方法"] == "PATCH":
            回["200"] = {"description": "已更新(带新 revision)",
                         "content": {"application/json": {"schema": {"type": "object"}}}}

        op = {"summary": a["中文"], "tags": [a["分组"]],
              "operationId": (a["方法"].lower() + a["路径"]
                              .replace("/", "_").replace("{", "").replace("}", "")),
              "parameters": 参数, "responses": 回,
              # 扩展字段:授权要求写在契约里,不是只在代码里
              "x-权限": a["权限"],
              "x-字段权限": a["字段权限"],
              "x-审计": a["审计"]}
        if a["说明"]:
            op["description"] = a["说明"]
        paths.setdefault(全路径, {})[a["方法"].lower()] = op

    doc = {
        "openapi": "3.1.0",
        "info": {"title": "澜绣云裳 AI 管理后台 API", "version": "0.1.0",
                 "description":
                     "从 `services/api/app/contract/` 生成,**不要手改**。\n\n"
                     "契约在前、代码在后:让 FastAPI 从 handler 反推 OpenAPI 的话,"
                     "**契约就变成了实现的影子** —— handler 漏了一个鉴权,"
                     "OpenAPI 跟着漏,而它看起来仍然是一份完整的契约。\n\n"
                     "⚠️ 这是**待实施契约**,不代表已经有可用的服务。"},
        "servers": [{"url": "/", "description": "同源"}],
        "components": {"schemas": {"Error": 错误体(),
                                   "ListEnvelope": 列表体(),
                                   "AsyncAccepted": 异步体()},
                       # 角色和能力也进文档 —— 看 API 的人要能对上权限矩阵
                       "x-角色": {r: PM.角色中文[r] for r in PM.角色们},
                       "x-能力": PM.能力们},
        "paths": paths,
    }
    os.makedirs(os.path.dirname(出), exist_ok=True)
    open(出, "w", encoding="utf-8").write(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return doc


if __name__ == "__main__":
    d = 建()
    print(f"写好了:{出}")
    print(f"  路径 {len(d['paths'])} 条 · 操作 "
          f"{sum(len(v) for v in d['paths'].values())} 个")
