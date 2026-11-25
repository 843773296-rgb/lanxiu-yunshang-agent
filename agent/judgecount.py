# -*- coding: utf-8 -*-
"""判分器对照集的**统一机读出口**(包三「钱与数字」第一件,用户 2026-11-25 拍)。

## 为什么要有它

32 个 `*_judgetest.py` 各自打印自己的条数,格式互不相同(「N 条对照全过」「验了 N 条」「N 条全过」
「对照 M/N」……有的最后一行根本不是汇总)。`tools/doc_numbers_check.py` 里那条 TODO 写了两个月:
「拿正则去刮只能刮到一半 —— **而刮到一半会被报成『全部通过』**,比不刮更糟」。
于是 PRD 里 24 行「离线对照用例 N 条」一直靠人看,没有一个数能现算。

## 规矩

每个判分器对照集在**知道了过 / 挂各几条之后、退出之前**调一次 `出口(名, 过, 挂)`,它打印一行:

    [cases] 名=工厂回传 总=16 过=16 挂=0

- 只认这一行的格式;`tools/judge_cases_check.py` 跑每个对照集、只从这一行取数,**缺这一行就红**
  (「没出口」和「出口说 0 条」要分得开 —— 前者红,后者也红:样本量 0 的对照集什么都没验)。
- `名` 是给文档对账用的业务名(「知识问答」「工具使用」……),和 PRD 里括号里的叫法一致;改名要两头一起改,
  judge_cases_check 会把对不上的名点出来。
- 不改各对照集原来打印的人话 —— 这行是加在旁边的,人看人话,机器看这一行。
"""
import sys

前缀 = "[cases]"


def 出口(名, 过, 挂=0, 文件=None):
    """打印机读行。过 / 挂 收整数或列表(列表取 len);返回总数。"""
    过 = len(过) if hasattr(过, "__len__") else int(过 or 0)
    挂 = len(挂) if hasattr(挂, "__len__") else int(挂 or 0)
    总 = 过 + 挂
    print(f"{前缀} 名={名} 总={总} 过={过} 挂={挂}", file=文件 or sys.stdout, flush=True)
    return 总


def 解析(文本):
    """从一段输出里取**最后一行**机读行 → dict(名, 总, 过, 挂);没有 → None。
    取最后一行是因为有的对照集会跑两层(纯函数 + 真跑一遍),各报一次,以最后那次为准。"""
    行 = [l for l in (文本 or "").splitlines() if l.startswith(前缀 + " ")]
    if not 行:
        return None
    d = {}
    for 段 in 行[-1][len(前缀):].split():
        if "=" in 段:
            k, v = 段.split("=", 1)
            d[k] = int(v) if v.isdigit() else v
    if not {"名", "总", "过", "挂"} <= set(d):
        return None
    return d


def _自测():
    import io
    f = io.StringIO()
    n = 出口("甲", 3, 1, 文件=f)
    assert n == 4 and 解析(f.getvalue()) == {"名": "甲", "总": 4, "过": 3, "挂": 1}, f.getvalue()
    f = io.StringIO(); 出口("乙", [1, 2], [], 文件=f)
    assert 解析(f.getvalue()) == {"名": "乙", "总": 2, "过": 2, "挂": 0}
    assert 解析("随便\n没有机读行") is None
    assert 解析("[cases] 名=丙 总=1 过=1 挂=0\n[cases] 名=丙 总=5 过=4 挂=1")["总"] == 5, "要取最后一行"
    assert 解析("[cases] 名=丁 总=x") is None, "缺字段不算"
    print("✅ judgecount 自测过(出口格式 / 解析取最后一行 / 缺字段不算)")
    return 0


if __name__ == "__main__":
    sys.exit(_自测())
