#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接入文档(Dify 对标 §6.3「接入文档按发布 schema 生成」,2026-11-04)。不要数据库。

## 判据

  ① **错误码说明表和代码对得上,两个方向**:open_api.py 里每一处 `_拒(<HTTP>, "<code>", …)` 都要在
     对外错误码 里有说明(新加一个拒法忘了写说明 → 红),表里也不许有代码里已经没有的码(囤着的旧说明会误导人);
     **HTTP 码也要一致**(说明写 401、代码回 403,对方照文档写的重试逻辑就是错的)
     —— 扫的是语法树里的真调用,不是按行 grep(多行调用、注释里举的例子都不会骗到它)
  ② 字段表:必填 / 类型 / 可选值照 schema 抄,不多不少
  ③ 请求示例:按类型造值,枚举取第一个,嵌套对象展开
"""
import ast
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_app = os.path.join(_根, "services", "api", "app")
sys.path.insert(0, _app)
import open_api as O  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 代码里的拒法():
    树 = ast.parse(open(os.path.join(_app, "open_api.py"), encoding="utf-8").read())
    出 = {}
    for n in ast.walk(树):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_拒" and len(n.args) >= 2:
            h, c = n.args[0], n.args[1]
            if isinstance(h, ast.Constant) and isinstance(c, ast.Constant):
                出.setdefault(c.value, set()).add(h.value)
    return 出


def main():
    print("▸ ① 错误码说明表和代码对得上")
    码们 = 代码里的拒法()
    ck(f"扫到了代码里的拒法(这次 {len(码们)} 个码)—— 扫不到不是通过", len(码们) >= 10, 码们)
    少 = sorted(set(码们) - set(O.对外错误码))
    ck("代码里每个拒法都有说明(什么时候会遇到、怎么办)", not 少, 少)
    多 = sorted(set(O.对外错误码) - set(码们))
    ck("说明表里没有代码里已经不存在的码(旧说明不许囤着)", not 多, 多)
    错码 = {k: (sorted(v), O.对外错误码[k][0]) for k, v in 码们.items() if k in O.对外错误码 and v != {O.对外错误码[k][0]}}
    ck("说明里写的 HTTP 码和代码回的一致(同一个码不许有两种 HTTP)", not 错码, 错码)

    print("\n▸ ② 字段表")
    s = {"type": "object", "required": ["phone"],
         "properties": {"phone": {"type": "string", "description": "客户手机号"},
                        "渠道": {"enum": ["电话", "上门"]}, "备注": {"type": "string"}}}
    表 = {x["字段"]: x for x in O._字段表(s)}
    ck("三个字段都在,phone 必填、其余不必填", set(表) == {"phone", "渠道", "备注"} and 表["phone"]["必填"]
       and not 表["渠道"]["必填"] and not 表["备注"]["必填"], 表)
    ck("枚举字段带可选值、说明照抄", 表["渠道"]["可选值"] == ["电话", "上门"] and 表["phone"]["说明"] == "客户手机号", 表)
    ck("没有 properties 的 schema → 空表(文档里写「没有声明输入字段」,不编)", O._字段表({}) == [] and O._字段表(None) == [])

    print("\n▸ ③ 请求示例")
    例 = O._示例({"type": "object", "properties": {"n": {"type": "integer"}, "ok": {"type": "boolean"},
                                                  "渠道": {"enum": ["电话", "上门"]},
                                                  "单": {"type": "object", "properties": {"号": {"type": "string"}}},
                                                  "们": {"type": "array", "items": {"type": "number"}}}})
    ck("按类型造值、枚举取第一个、嵌套对象和数组展开",
       例 == {"n": 1, "ok": True, "渠道": "电话", "单": {"号": "……"}, "们": [1.5]}, 例)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 接入文档:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
