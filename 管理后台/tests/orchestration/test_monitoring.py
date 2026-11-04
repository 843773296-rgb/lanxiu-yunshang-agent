#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监测的口径(DF-04,2026-11-04;用户拍「办成 = 跑完 + 每处写入都有回执」)。不要数据库,真调 monitoring_api 的纯函数。

  ① 归类:跑完 + 写入全回执 → 办成;跑完 + 有写入没回执 → 跑完·没证实;跑完 + 没有写入 → 跑完·这次不需要写入;
     等人 / 等澜绣 / 在跑 → 不是失败也不是成功
  ② 比例:分母 0 → None(未知,不写 0);其余一位小数
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
import monitoring_api as M  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def main():
    print("▸ ① 归类(用户拍的办成口径)")
    ck("跑完 + 2 处写入都回执了 → 办成", M.归类("succeeded", 2, 2) == "办成")
    ck("**跑完 + 2 处写入只回执 1 处 → 跑完·没证实**(不算办成)", M.归类("succeeded", 2, 1) == "跑完·没证实")
    ck("跑完 + 没有写入 → 跑完·这次不需要写入(单列,不混进办成率)", M.归类("succeeded", 0, 0) == "跑完·这次不需要写入")
    ck("失败 / 取消 / 没做完 各归各", [M.归类(s, 1, 0) for s in ("failed", "cancelled", "incomplete")] == ["失败", "取消", "没做完"])
    ck("等人核对 / 等澜绣执行 / 在跑 → 不是失败也不是成功",
       [M.归类(s, 1, 0) for s in ("waiting_approval", "waiting_external", "running")] == ["等人核对", "等澜绣执行", "进行中"])

    print("\n▸ ② 比例:未知不补零")
    ck("分母 0 → None(页面写「—」,不写 0%)", M.比例(0, 0) is None and M.比例(5, 0) is None)
    ck("3 / 4 → 75.0", M.比例(3, 4) == 75.0)
    ck("0 / 4 → 0.0(真的是 0,和未知分得开)", M.比例(0, 4) == 0.0)
    ck("小样本线是个正整数(产品默认值,文件头写明了未经业务确认)", isinstance(M.小样本线, int) and M.小样本线 > 0)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 监测口径:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
