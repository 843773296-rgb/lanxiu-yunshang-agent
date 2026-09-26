#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 OpenAPI 生成前端 TS 类型 —— **生成的,不要手改**(规格 §17.4 第 1 步)。

## 为什么要生成,而不是前端自己写一份 interface

前端手写一份接口类型,等于**把契约抄了第三遍**(契约登记表 / OpenAPI / 前端类型)。
而这三份会各自漂,漂的时候**编译还是过的** —— 后端把一个字段改成可空,
前端的 interface 上它仍然是必填,于是那个 `undefined` 一路跑到渲染才炸,
而报错指向的地方离原因很远。

## 它刻意只生成三样

信封(列表 / 异步 / 错误)、路径常量、每条接口要的权限。
**业务字段不在这里生成** —— 因为契约登记表现在只登记了字段名和类型,
还没登记「这个接口的请求体长什么样」。硬编一份出来的话,
那份类型会看起来很完整,而它描述的是我猜的形状,不是约定的形状。

> **一份看起来完整的假类型,比一份明显不完整的真类型危险得多。**
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "contract"))
import endpoints as EP, perms as PM, states as ST

出 = os.path.join(ROOT, "packages", "contracts", "api.ts")
OA = os.path.join(ROOT, "packages", "contracts", "openapi.json")


def 写():
    oa = json.load(open(OA, encoding="utf-8"))
    L = ["// 从 packages/contracts/openapi.json 生成 —— **不要手改**。",
         "// 改契约请改 services/api/app/contract/,然后 `make gen`。",
         "//",
         "// ⚠️ 这里**只有信封、路径和权限**,没有业务字段 —— 因为契约还没登记",
         "// 每条接口的请求体形状。硬编一份出来的话,那份类型会看起来很完整,",
         "// 而它描述的是猜的形状。**一份看起来完整的假类型,比一份明显不完整的真类型危险。**",
         "", "/* ── 信封 ─────────────────────────────────────────── */", ""]

    L += ["/** 分页列表。`total` 未知时是 `null` —— **不是 0**(0 会被读成「一条都没有」)。 */",
          "export interface ListEnvelope<T> {",
          "  items: T[];",
          "  next_cursor: string | null;",
          "  total: number | null;",
          "}", ""]

    任务状态 = " | ".join(f'"{s}"' for s in ST.找("job")["状态"])
    L += ["/** 异步受理。**不会返回「已完成」来冒充同步执行**;去 status_url 看进度。 */",
          "export interface AsyncAccepted {",
          "  job_id: string;",
          f"  status: {任务状态};",
          "  resource_id: string | null;",
          "  status_url: string;",
          "  trace_id: string | null;",
          "}", ""]

    L += ["/** 统一错误。`advice` 必填 —— 一个只说「失败了」的错误,和没有提示是一回事。 */",
          "export interface ApiError {",
          "  code: string;",
          "  message: string;",
          "  field_errors: Record<string, string>;",
          "  /** 能不能重试由服务端说 —— 客户端猜错的两个方向代价都很大。 */",
          "  retryable: boolean;",
          "  trace_id: string | null;",
          "  /** 下一步该干什么。 */",
          "  advice: string;",
          "}", ""]

    L += ["/* ── 角色与能力(和权限矩阵同源)────────────────────── */", "",
          "export type Role = " + " | ".join(f'"{r}"' for r in PM.角色们) + ";", "",
          "export const ROLE_LABEL: Record<Role, string> = {"]
    L += [f'  {r}: "{PM.角色中文[r]}",' for r in PM.角色们]
    L += ["};", "",
          "export type Capability =", ]
    L += [f'  | "{c}"' for c in PM.能力们]
    L[-1] = L[-1] + ";"
    L.append("")

    L += ["/* ── 接口:路径 + 它要的权限 ───────────────────────── */", "",
          "/** 每条接口要哪条权限 —— **前端据此决定按钮显示成「无权」还是隐藏**,",
          "  * 但**授权由服务端每次请求执行**:前端藏起来不等于挡住了。 */",
          "export interface EndpointSpec {",
          "  method: string;",
          "  path: string;",
          "  summary: string;",
          "  capability: Capability;",
          "  /** 部分字段要额外授权才返回(如 trace 原文、独立测试答案)。 */",
          "  fieldCapabilities: Capability[];",
          "  /** 异步动作:返回 202 + AsyncAccepted,不要指望它直接给结果。 */",
          "  isAsync: boolean;",
          "  /** 要 Idempotency-Key 请求头。 */",
          "  needsIdempotencyKey: boolean;",
          "  /** 要 If-Match 请求头(拿列表/详情里的 revision 填)。 */",
          "  needsIfMatch: boolean;",
          "}", "",
          "export const API_PREFIX = " + json.dumps(EP.前缀, ensure_ascii=False) + ";", "",
          "export const ENDPOINTS = ["]
    for a in EP.接口表:
        L.append("  {"
                 f' method: "{a["方法"]}",'
                 f' path: {json.dumps(a["路径"], ensure_ascii=False)},'
                 f' summary: {json.dumps(a["中文"], ensure_ascii=False)},'
                 f' capability: {json.dumps(a["权限"], ensure_ascii=False)},'
                 f' fieldCapabilities: {json.dumps(a["字段权限"], ensure_ascii=False)},'
                 f' isAsync: {"true" if a["形态"] == EP.异步 else "false"},'
                 f' needsIdempotencyKey: {"true" if a["幂等"] else "false"},'
                 f' needsIfMatch: {"true" if a["乐观锁"] else "false"} }},')
    L += ["] as const satisfies readonly EndpointSpec[];", ""]

    # 数一遍,让人一眼看出这份文件覆盖了多少
    L += [f"/** 共 {len(EP.接口表)} 条接口 · "
          f"{sum(1 for a in EP.接口表 if a['形态'] == EP.异步)} 条异步 · "
          f"{sum(1 for a in EP.接口表 if a['幂等'])} 条要幂等键 · "
          f"{sum(1 for a in EP.接口表 if a['乐观锁'])} 条要 If-Match */", ""]

    os.makedirs(os.path.dirname(出), exist_ok=True)
    open(出, "w", encoding="utf-8").write("\n".join(L))
    return 出


if __name__ == "__main__":
    print("写好了:" + 写())
