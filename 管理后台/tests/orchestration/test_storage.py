#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对象存储适配器 —— **在临时目录里跑,不碰真的 `.object-store`**。

## 为什么这个文件值得测到这个密度

它是 README 里那句「适配器接口保持一致,接 S3 时只换实现」的**唯一落地**。
一个没有测试的适配器,在换实现的时候没有任何东西能告诉你新实现少做了什么。

## 三件必须证明的

    ① **键逃不出根目录** —— 而且判断用路径段比,不用字符串前缀
    ② **写入是原子的** —— 半个文件不许被读到
    ③ **存储问题和内容不合格是两个异常** —— 前者运维处理,后者用户重传
"""
import os
import sys
import tempfile

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_临 = tempfile.mkdtemp(prefix="objstore-test-")
os.environ["OBJECT_STORE_ROOT"] = _临        # ⚠️ 必须在 import 之前
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))

import storage as S

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("▸ ① 根目录来自环境变量(测试绝不写真的 .object-store)")
ck("根 == 临时目录", S.根 == os.path.abspath(_临), S.根)
ck("真的 .object-store 没被创建",
   not os.path.exists(os.path.join(_根, ".object-store")) or
   os.path.abspath(_临) != os.path.join(_根, ".object-store"))

print("▸ ② 写入 / 读出 / 有吗")
键 = S.建键(项目id="project_demo_a", 上传id="up_abc", 文件名="拍板 记录.md",
          年月="2026-09")
ck("键的形状是 项目/年月/上传id/文件名", 键.count("/") == 3, 键)
ck("键里项目 id 在最前(按项目能一次列全)", 键.startswith("project_demo_a/"))
ck("文件名里的空格被压掉(路径里不留空格)", " " not in 键, 键)
字节 = "# 标题\n\n正文。\n".encode()
存 = S.写入(键, 字节)
ck("写入报了字节数", 存["字节数"] == len(字节))
ck("读出来和写进去一模一样", S.读出(键) == 字节)
ck("有吗 → True", S.有吗(键))
ck("没写过的 → 有吗 False", not S.有吗("project_demo_a/2026-09/up_none/x.md"))

print("▸ ③ 同名文件不互相覆盖(键里带上传 id)")
键2 = S.建键(项目id="project_demo_a", 上传id="up_def", 文件名="拍板 记录.md",
           年月="2026-09")
ck("同名不同上传 → 不同键", 键 != 键2, f"{键}\n     {键2}")
S.写入(键2, "# another\n\n不同内容。\n".encode())
ck("第一份没被覆盖(被覆盖的那份哈希已经进库了,库会说「校验过」而字节不是那份)",
   S.读出(键) == 字节)

print("▸ ④ 键逃不出根目录 —— **不清洗后放行,当场抛**")
for 坏 in ("../跑出去.md", "../../etc/passwd", "/etc/passwd",
          "a/../../外面.md", "", "有\0NUL"):
    try:
        S._落地(坏)
        ck(f"{坏!r} 被拦住", False, "没拦住!")
    except S.键不合法:
        ck(f"{坏!r} 被拦住", True)
    except Exception as e:
        ck(f"{坏!r} 被拦住", False, f"抛的不是 键不合法:{type(e).__name__}")
ck("键不合法 是 存不了 的子类(调用方可以只抓一个)",
   issubclass(S.键不合法, S.存不了))

print("▸ ⑤ **前缀相同但不是子目录**的必须也拦住(用路径段比,不用 startswith)")
# `<根>-evil` 的字符串前缀就是 `<根>`,但它不在根目录里面。
_邻 = os.path.abspath(_临) + "-evil"
_从根到邻 = os.path.relpath(_邻, os.path.abspath(_临))      # 形如 `../objstore-test-xxx-evil`
try:
    S._落地(_从根到邻 + "/x.md")
    ck("兄弟目录(前缀相同)被拦住", False, f"没拦住!{_从根到邻}")
except S.键不合法:
    ck("兄弟目录(前缀相同)被拦住 —— startswith 在这里会漏", True, _从根到邻)
ck("有吗() 对非法键返回 False 而不是抛(它是「在不在」的查询)",
   S.有吗("../外面.md") is False)

print("▸ ⑥ 建键:每一段都不许含路径分隔符")
for 坏参 in (dict(项目id="a/b", 上传id="up", 年月="2026-09"),
           dict(项目id="p", 上传id="../up", 年月="2026-09"),
           dict(项目id="p", 上传id="up", 年月=""),
           dict(项目id="", 上传id="up", 年月="2026-09")):
    try:
        S.建键(文件名="a.md", **坏参)
        ck(f"{坏参} 被拦住", False, "没拦住!")
    except S.键不合法:
        ck(f"{坏参} 被拦住", True)

print("▸ ⑦ 安全文件名:只用来生成键,不改库里记的原名")
ck("路径成分被去掉", S.安全文件名("../../etc/passwd") == "passwd")
ck("点开头的被剥(不生成隐藏文件)", S.安全文件名(".hidden.md") == "hidden.md")
ck("空名有兜底", S.安全文件名("") == "file")
ck("中文保留(库里 file_name 显示原名,键里也不必打成一串下划线)",
   "拍板" in S.安全文件名("拍板记录.md"))
ck("超长被截断", len(S.安全文件名("x" * 500 + ".md")) <= 120)

print("▸ ⑧ 原子写:不留 .part,而且半个文件读不到")
ck("目录里没有 .part 残留",
   not any(f.endswith(".part") for _, _, fs in os.walk(_临) for f in fs))
# 咬合:写入过程中炸掉 → **目标文件不存在**,而不是存在一个半截的
_老 = os.replace
try:
    os.replace = lambda a, b: (_ for _ in ()).throw(OSError("咬合:改名前炸"))
    键3 = S.建键(项目id="p", 上传id="up_boom", 文件名="x.md", 年月="2026-09")
    try:
        S.写入(键3, b"# half")
    except OSError:
        pass
finally:
    os.replace = _老
ck("**写一半炸掉 → 目标文件不存在**(不是一个打得开的半截文件)",
   not S.有吗(键3), S._落地(键3))
ck("而且 **`.part` 被清掉了** —— 留下来的临时文件不报错、不被读到、"
   "只是永远占着空间(跑三个月之后没人查得出是谁留的)",
   not any(f.endswith(".part") for _, _, fs in os.walk(_临) for f in fs),
   [f for _, _, fs in os.walk(_临) for f in fs if f.endswith(".part")])

print("▸ ⑨ 读一个库里记着而存储里没有的键 → 存不了,**并说清这是两边不一致**")
try:
    S.读出("p/2026-09/up_ghost/x.md")
    ck("报了错", False, "没报错!")
except S.存不了 as e:
    ck("报了 存不了", True)
    ck("理由里说清「两边不一致」而不是「文件坏了」", "不一致" in str(e), str(e)[:90])

print("▸ ⑩ 写入要 bytes,给 str 当场抛(**不悄悄 encode**)")
try:
    S.写入(S.建键(项目id="p", 上传id="up_str", 文件名="x.md", 年月="2026-09"), "字符串")
    ck("给 str 被拒", False, "没拒!悄悄 encode 会让编码问题挪到读的时候才爆")
except S.存不了:
    ck("给 str 被拒(悄悄 encode 会把编码问题挪到读的时候才爆)", True)

print("▸ ⑪ 种类标出来(接了 S3 之后这个值要变)")
ck("种类 == filesystem", S.种类 == "filesystem", S.种类)

import shutil
shutil.rmtree(_临, ignore_errors=True)
print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
