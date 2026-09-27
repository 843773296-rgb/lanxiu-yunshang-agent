#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行配置 —— **启动时就拒绝危险组合**,不等到第一个请求。

规格 §17.4 第 3 步:「本地允许明确的开发身份模式;生产接已有 OIDC/SSO。
**服务启动时阻止生产开启开发绕过**。」

为什么是启动时而不是请求时:一个「生产环境 + 开发身份模式」的服务,
只要起得来,就已经有一个窗口期是**任何人都能冒充任何人**的。
请求时才拦的话,那个窗口期是「从启动到第一个请求」——
而健康检查、预热探针、监控轮询都在那个窗口里。
"""
import os

开发 = "development"
测试 = "test"
生产 = "production"

APP_ENV = os.environ.get("APP_ENV", 开发).strip().lower()
AUTH_MODE = os.environ.get("AUTH_MODE", "dev").strip().lower()
DATABASE_URL = os.environ.get("DATABASE_URL") or (
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev")
# 训练适配器:mock 的产物**不许计入真实评测或发布**(实施必须遵守第 3 条)
TRAINING_ADAPTER = os.environ.get("TRAINING_ADAPTER", "mock").strip().lower()
MODEL_ADAPTER = os.environ.get("MODEL_ADAPTER", "mock").strip().lower()


def 启动自检():
    """返回该拒绝启动的理由清单。**空清单才允许启动。**"""
    坏 = []
    if APP_ENV not in (开发, 测试, 生产):
        坏.append(f"APP_ENV={APP_ENV!r} 认不出 —— **不猜**:猜成 development "
                  f"会把生产当开发跑")
    if APP_ENV == 生产 and AUTH_MODE == "dev":
        坏.append("**生产环境开着开发身份模式** —— 这个组合下任何人都能冒充任何人。"
                  "改 AUTH_MODE=oidc,或者别把 APP_ENV 设成 production")
    if APP_ENV == 生产 and MODEL_ADAPTER == "mock":
        坏.append("**生产环境用 mock 模型适配器** —— 它会返回编出来的答案,"
                  "而那些答案在数据形状上和真的一模一样")
    if not DATABASE_URL:
        坏.append("没有 DATABASE_URL")
    return 坏


def 演示模式():
    """演示模式要有**醒目标记**(实施必须遵守第 3 条)。"""
    return MODEL_ADAPTER == "mock" or TRAINING_ADAPTER == "mock"
