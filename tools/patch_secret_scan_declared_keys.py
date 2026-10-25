#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""放宽冻结版本时的密钥扫描:**只放过 DSL 自己声明过的节点配置名,而且值得是数**(用户 2026-10-25 拍「只放过系统自己的设置名」)。

原规则按**键名**判(名字里带 token / secret / password …就拒),于是 llm 节点自己声明的 `max_output_tokens` 也被当成密钥。
放宽的范围压到最小 —— 三个条件同时满足才放:
  ① 键名在 DSL 节点登记表里某个节点的「配置」字段中(从登记表现算,不手抄一份)
  ② 它就在某个节点的 config 下面(路径以 `config.` 结尾),不是嵌在别处的同名键
  ③ 值是数字(不是字符串)—— 有人把一串真密钥塞进这个名字底下,照样拒
这是**放宽守卫**,按项目规矩由用户本人执行:

    ! python3 tools/patch_secret_scan_declared_keys.py
"""
import os
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "管理后台", "services", "api", "app", "contract", "dsl.py")
旧 = '''    if isinstance(v, dict):
        for k in v:
            if _密钥形状.search(str(k)) and not str(k).endswith(("_ref", "_refs")):'''
新 = '''    if isinstance(v, dict):
        for k in v:
            # 用户 2026-10-25 拍「只放过系统自己的设置名」:DSL 节点登记表里声明过的配置名(现在只有 max_output_tokens
            # 撞这条规则),**就在节点 config 下、值是数字**才放 —— 名字可疑而值是字符串的,照样当密钥拒
            if (str(k) in _声明过的配置名() and 路.endswith("config.")
                    and isinstance(v[k], (int, float)) and not isinstance(v[k], bool)):
                continue
            if _密钥形状.search(str(k)) and not str(k).endswith(("_ref", "_refs")):'''
函数 = '''

def _声明过的配置名():
    """节点登记表里每个节点声明过的配置字段名(从登记表现算,不手抄)。"""
    名 = set()
    for n in 节点表:
        名 |= set(n["配置"])
    return 名


def _扫密钥(v, 路=""):'''

s = open(P, encoding="utf-8").read()
if "_声明过的配置名" in s:
    print("已经改过了,没再改")
    sys.exit(0)
if s.count(旧) != 1 or s.count("\n\ndef _扫密钥(v, 路=\"\"):") != 1:
    print("❌ dsl.py 里要改的那段对不上(可能已经被别人改过)—— 没动任何东西")
    sys.exit(1)
s = s.replace(旧, 新, 1).replace("\n\ndef _扫密钥(v, 路=\"\"):", 函数, 1)
open(P, "w", encoding="utf-8").write(s)
print("✅ 改好了:只放过 DSL 声明过的节点配置名、值是数字的那种;其余照旧按键名拒")
