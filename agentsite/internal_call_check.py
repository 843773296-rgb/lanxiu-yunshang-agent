#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理后台 → 聊天站内部调用(访问 API 聊天那一半,11-03):真调 internal_call 和 sdk.去掉写工具。

  ① 凭证文件不在 / 是空的 → 通道关着(不退回成谁都能调)
  ② 对端不是本机 → 拒;凭证不对 → 拒;三种拒法理由分得开
  ③ 凭证对 + 本机 → 放行
  ④ 身份从员工表现查:在职的查得到(字段和网页登录那份一样四样),查不到的 → None
  ⑤ 会话主记在密钥名下,不记在人名下(同一个人的网页会话和 API 会话互相接不上)
  ⑥ 去掉写工具:api.WRITE_TOOLS 里的一个都不剩,读工具一个不少(店长助手那一份工具名单上真算)
"""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "backend")]
import internal_call as IC

# 咬合记录(可重放的规格在 tools/bite_specs.json,script 为这个文件的那两条)
咬合 = [
    ("内部口不再只收本机(对端判断改成永远放行)", "② 对端不是本机 → 拒"),
    ("访问 API 那一轮照样挂写工具(去掉写工具改成原样返回)", "⑥ 去掉之后一个写工具都不剩"),
]

过, 挂 = [], []
def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)

def main():
    d = tempfile.mkdtemp(); 文 = os.path.join(d, "ic")
    ok, why = IC.核对("x", "127.0.0.1", 路径=文)
    ck("① 凭证文件不在 → 通道关着", not ok and "没开" in why, why)
    open(文, "w").write("   \n")
    ok, why = IC.核对("x", "127.0.0.1", 路径=文)
    ck("① 凭证文件是空的 → 也算关着", not ok and "没开" in why, why)
    open(文, "w").write("s3cret-abc\n")
    ok, why = IC.核对("s3cret-abc", "10.0.0.5", 路径=文)
    ck("② 对端不是本机 → 拒(凭证对也不行)", not ok and "本机" in why, why)
    ok, why = IC.核对("wrong", "127.0.0.1", 路径=文)
    ck("② 凭证不对 → 拒", not ok and "不对" in why, why)
    ok, why = IC.核对(None, "127.0.0.1", 路径=文)
    ck("② 没带凭证 → 拒", not ok and "不对" in why, why)
    ok, why = IC.核对("s3cret-abc", "127.0.0.1", 路径=文)
    ck("③ 凭证对 + 本机 → 放行", ok, why)
    me = IC.员工("60000011")
    ck("④ 在职员工查得到,四样字段和网页登录那份一样", me and set(me) == {"no", "name", "role", "shop"} and me["no"] == "60000011", me)
    ck("④ 查不到的工号 → None", IC.员工("99999999") is None and IC.员工("") is None)
    主 = IC.会话主("ak_1", me)
    ck("⑤ 会话主记在密钥名下(不是那个人的工号),角色 / 门店照抄", 主["no"] == "访问密钥:ak_1" and 主["role"] == me["role"]
       and 主["shop"] == me["shop"], 主)
    import sdk, api
    全 = sdk.生效工具("task", None)
    剩 = sdk.去掉写工具(全)
    写 = set(api.WRITE_TOOLS)
    名 = lambda ts: {t.rsplit("__", 1)[-1] for t in ts}
    ck("⑥ 店长助手名单里本来有写工具(否则这一条什么都没验)", bool(名(全) & 写), sorted(名(全) & 写)[:5])
    ck("⑥ 去掉之后一个写工具都不剩", not (名(剩) & 写), sorted(名(剩) & 写))
    ck("⑥ 读工具一个不少", 名(全) - 写 == 名(剩), sorted((名(全) - 写) - 名(剩)))
    print()
    if 挂:
        print(f"❌ 内部调用 {len(挂)} 条不过"); return 1
    print(f"✅ 内部调用:凭证 / 本机 / 身份现查 / 会话归密钥 / 写工具不挂({len(过)} 条)"); return 0

if __name__ == "__main__":
    sys.exit(main())
