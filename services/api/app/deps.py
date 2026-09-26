#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""身份、项目授权、字段权限 —— **每个请求都重新判**。

规格 §15.3:「授权必须在**服务端每次请求**执行,并检查对象所属项目;
知识片段、源文档、历史 Trace、文件下载同样适用。」
§19.1:「浏览器不能通过更改 ID 绕过授权。」

## 权限判定只有一条路

`要权限(能力)` 是唯一入口,它直接问 `contract/perms.py`。
handler 里**不许**再写第二套判断 —— 两套判断迟早有一处漏,
而漏掉的那处在界面上看不出任何异常。

## 开发身份模式怎么标出来

开发模式下从请求头取身份(`X-Dev-User`),**而且响应里会带一个醒目标记**。
一个看不出自己在开发模式的界面,会让人拿演示结果当真实结果。
"""
import os, sys
from fastapi import Header, HTTPException, Depends
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
import perms as PM
import errors as ER
import runtime_cfg as CFG


def _错(http, code, message, 建议, **kw):
    体 = ER.错(code, message, 建议, http=http, **kw)
    return HTTPException(status_code=http, detail=体)


class 身份:
    def __init__(self, user_id, org_id, project_id, role, grants):
        self.user_id, self.org_id, self.project_id = user_id, org_id, project_id
        self.role, self.grants = role, list(grants or [])

    def 能(self, 能力):
        return PM.判(能力, self.role, self.grants)

    def 看得到原文吗(self):
        """字段级:trace 原文 / 独立测试答案。**默认否。**"""
        行, _ = self.能("查看敏感输入/独立测试答案")
        return 行


async def 取身份(project_id: str,
                x_dev_user: str = Header(default=None, alias="X-Dev-User")):
    """解析身份并**校验他在这个项目里有成员记录**。

    ⚠️ 项目是路径参数,而成员记录是库里的事实 —— 改 URL 里的 project_id
    只会让这一步查不到成员记录,不会让他拿到别的项目(§19.1)。
    """
    from db import 连接
    if CFG.AUTH_MODE != "dev":
        # OIDC 还没接 —— **明确报未实现,不静默放行**。
        # 一个「认证方式没接上就当匿名放行」的系统,比没有认证更危险:
        # 它看起来是有认证的。
        raise _错(501 if 501 in ER.状态语义 else 500, "AUTH_NOT_IMPLEMENTED",
                  "只实现了开发身份模式", "把 AUTH_MODE 设成 dev,或者先实现 OIDC 接入")
    if not x_dev_user:
        raise _错(401, "NO_IDENTITY", "没有身份",
                  "开发模式请带请求头 X-Dev-User:<工号>。生产要接 OIDC")
    with 连接() as c:
        r = c.execute(text("""
            select m.user_id, m.organization_id, m.project_id, m.role, m.special_grants
              from memberships m
             where m.user_id = :u
               and (m.project_id = :p or m.project_id is null)
               and m.status = 'active'
             order by (m.project_id is null)      -- 项目级成员记录优先于组织级
             limit 1
        """), {"u": x_dev_user, "p": project_id}).mappings().first()
        if not r:
            # **404 而不是 403**:不确认「这个项目存在但你没权限」——
            # 那句话本身就是信息(规格 §19.1「404 不存在或按策略隐藏存在性」)
            raise _错(404, "NO_MEMBERSHIP", "这个项目下没有你的成员记录",
                      "确认项目选对了;要访问请让管理员在「成员与权限」里加你")
        proj = c.execute(text("select 1 from projects where id=:p and organization_id=:o"),
                         {"p": project_id, "o": r["organization_id"]}).first()
        if not proj:
            raise _错(404, "NO_PROJECT", "项目不存在", "回到项目列表重新选")
    return 身份(r["user_id"], r["organization_id"], project_id, r["role"],
                r["special_grants"] or [])


def 要权限(能力):
    """依赖工厂:这条接口要哪条能力。**能力名来自 contract/perms.py**,写错会抛。"""
    if 能力 not in PM.能力们:
        raise KeyError(f"要求了一条不存在的能力:{能力!r} —— "
                       f"**点名不存在的能力等于没有权限判定**")

    async def _(me: 身份 = Depends(取身份)):
        行, 为什么 = me.能(能力)
        if not 行:
            raise _错(403, "FORBIDDEN", f"你的角色不能「{能力}」",
                      f"{为什么}。要这条权限请让管理员在「成员与权限」里授权",
                      field_errors={})
        return me
    return _
