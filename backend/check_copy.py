# -*- coding: utf-8 -*-
"""检查用的库副本:拷一份真库,把**已经 import 的每个模块**里指着真库的 `DB` 一次全改到副本上。

为什么要这一份(2026-10-19):门禁的台账闸(LANXIU_CHECK_LEAK)逮到 7 个检查往真库台账写。
其中 4 个已经把业务数据指到副本了,**只漏了 oplog.DB** —— 每个模块各有一个 `DB`,
一个个手指,总有一个会漏,而漏的那个不报错。另 3 个干脆在真库上「改了再还原」,
中途崩了就留在真库里(10-19 那条「张静静改派 SC21711」就是这么来的)。

用法:import 完被测模块之后调一次。之后才 import 的模块(函数里懒加载的)不会被改到 ——
那种漏写台账的,门禁那道闸照样会点名。
"""
import atexit
import os
import shutil
import sys
import tempfile

真库 = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db"))


def 用副本(前缀="chk-"):
    """→ 副本路径。进程退出时删掉。台账模块总是先 import 进来再改 —— 写口里常常懒加载它,
    不先加载的话改不到,台账照样写真库(membership_check 当场这样漏过)。"""
    import oplog  # noqa: F401
    目录 = tempfile.mkdtemp(prefix=前缀)
    副本 = os.path.join(目录, "lanxiu.db")
    shutil.copy(真库, 副本)
    for m in list(sys.modules.values()):
        db = getattr(m, "DB", None)
        if isinstance(db, str) and os.path.realpath(db) == 真库:
            m.DB = 副本
    atexit.register(shutil.rmtree, 目录, True)
    return 副本
