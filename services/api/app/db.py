#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库连接。**管理状态的真值来源是 PostgreSQL**(规格 §17.1:
「数据库是管理状态真值来源;禁止 Redis 缓存成为唯一记录」)。"""
import os, sys
from contextlib import contextmanager
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runtime_cfg as CFG

_引擎 = None


def 引擎():
    global _引擎
    if _引擎 is None:
        _引擎 = create_engine(CFG.DATABASE_URL, pool_pre_ping=True, future=True)
    return _引擎


@contextmanager
def 连接():
    with 引擎().connect() as c:
        yield c


@contextmanager
def 事务():
    with 引擎().begin() as c:
        yield c
