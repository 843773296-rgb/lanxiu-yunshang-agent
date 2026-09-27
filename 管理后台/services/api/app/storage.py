#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对象存储适配器 —— 首版是**文件系统**实现(README 里登记过的偏离)。

规格默认 S3 兼容对象存储;本机没有 Compose 起不了 MinIO,所以首版用文件系统顶着。
README 当时写的是「适配器接口保持一致,接 S3 时只换实现」——
**这个文件就是那句话的落地**。在它之前那句话没有任何代码支持:
`tools/ingest_lanxiu.py` 是把仓库相对路径直接塞进 `object_key` 的。

## 为什么要一层适配器,而不是各处直接 open()

`object_key` 这一列在契约里的含义是「对象存储的键」。
直接 open() 的代价不是「难换」,是**换的时候没人知道要改哪些地方** ——
散在四个模块里的 open() 不会因为接了 S3 而报错,它们会继续读本机那份旧文件,
于是**一半数据在 S3、一半在本机**,而两边都读得通。

## ⚠️ 键不许逃出根目录

`_落地(键)` 会把键拼到根目录下。一个 `../../etc/passwd` 形状的键
能让写入落到根目录外面 —— 而这一版的键是服务端生成的,**当下没有这个入口**。

仍然要守,原因是「当下没有入口」是个会过期的事实:
以后任何一处改成「用文件名当键」,这个守卫就是唯一拦得住的东西。
**守卫放在机制上,不放在调用方的自觉上。**

## 键的形状

    <项目id>/<年月>/<上传id>/<安全文件名>

带项目 id 是为了**按项目能一次列全**(删项目、算配额都要);
带年月是为了目录别无限长(文件系统在单目录几十万文件时会变慢);
带上传 id 是为了**同名文件不互相覆盖** —— 而覆盖在这里格外糟:
被覆盖的那份的哈希已经写进库里了,于是库说「校验过」而字节已经不是那份。
"""
import os
import re
import unicodedata

根 = os.path.abspath(os.environ.get(
    "OBJECT_STORE_ROOT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), ".object-store")))

种类 = os.environ.get("OBJECT_STORE_KIND", "filesystem").strip().lower()


class 存不了(Exception):
    """存储层的问题 —— **和「文件内容不合格」分开**。

    一个把两者混成一个异常的接口,会让「磁盘满了」和「用户传了个坏文件」
    在界面上长得一样,而前者要运维去处理,后者要用户重传。
    """


class 键不合法(存不了):
    """键逃出了根目录,或者形状不对。**当场抛,不做清洗后放行。**

    清洗后放行的代价:`../../x` 被清成 `x` 之后**写成功了**,
    于是调用方以为自己存在 `../../x`,而实际在 `x` —— 两边都不报错。
    """


_不许出现在文件名里 = re.compile(r"[^0-9A-Za-z一-鿿._\-]")


def 安全文件名(名, *, 兜底="file"):
    """把文件名压成安全形状。**只用在生成键的时候,不用来改库里记的原名。**

    库里的 `file_name` 要留**用户传的那个原名** —— 界面上显示的是它,
    而一个显示着清洗后名字的界面会让人以为自己传错了文件。
    """
    名 = unicodedata.normalize("NFC", (名 or "").strip())
    名 = os.path.basename(名.replace("\\", "/"))     # 去掉任何路径成分
    名 = _不许出现在文件名里.sub("_", 名)
    名 = 名.lstrip(".") or 兜底                        # 不许以点开头(隐藏文件/相对段)
    return 名[:120]


def 建键(*, 项目id, 上传id, 文件名, 年月):
    """生成一个键。**服务端生成,不接受调用方给的键。**"""
    for 名, 值 in (("项目id", 项目id), ("上传id", 上传id), ("年月", 年月)):
        if not 值 or "/" in str(值) or ".." in str(值):
            raise 键不合法(f"{名}={值!r} 不能当键的一段 —— 空或含路径分隔符")
    return f"{项目id}/{年月}/{上传id}/{安全文件名(文件名)}"


def _落地(键):
    """键 → 本机绝对路径。**逃出根目录就抛。**"""
    if not 键 or not isinstance(键, str):
        raise 键不合法("键是空的")
    if "\0" in 键:
        raise 键不合法("键里有 NUL 字节")
    路 = os.path.abspath(os.path.join(根, 键))
    # ⚠️ 用 os.path.commonpath 而不是 startswith:
    # startswith 会把 `/tmp/store-evil` 当成在 `/tmp/store` 里面(前缀相同但不是子目录)。
    try:
        同 = os.path.commonpath([路, 根])
    except ValueError:                                  # 不同盘符(Windows)
        raise 键不合法(f"键落到了根目录外面:{键!r}")
    if 同 != 根:
        raise 键不合法(
            f"键落到了根目录外面:{键!r} —— **不清洗后放行**:"
            f"清洗之后写成功了,调用方会以为自己存在别处,而两边都不报错")
    return 路


def 写入(键, 字节):
    """写一个对象。**先写临时文件再改名** —— 半个文件不许被读到。

    为什么:进程可以死在 write() 中间,而一个写了一半的文件**打得开**。
    打得开的半个文件会被解析成「少了后半段的资料」,切出来的片段
    在数据形状上和正常片段一模一样 —— 而它少的那半段正是检索要找的。
    rename 在同一文件系统上是原子的,于是读到的只有「完整」或「不存在」。
    """
    if not isinstance(字节, (bytes, bytearray)):
        raise 存不了(f"要 bytes,给的是 {type(字节).__name__}")
    路 = _落地(键)
    os.makedirs(os.path.dirname(路), exist_ok=True)
    临 = 路 + ".part"
    try:
        with open(临, "wb") as f:
            f.write(字节)
            f.flush()
            os.fsync(f.fileno())
        os.replace(临, 路)
    except BaseException:
        # ⚠️ **失败要把临时文件清掉。** 一个留下来的 `.part` 不报错、
        # 不会被读到、也不会被任何人发现 —— 它只是永远占着空间。
        # 这类「不报错的泄漏」在开发机上看不出来,在跑三个月的服务上
        # 变成「磁盘为什么满了」,而那时已经查不出是谁留的。
        try:
            os.unlink(临)
        except OSError:
            pass
        raise
    return dict(键=键, 字节数=len(字节), 种类=种类)


def 读出(键):
    路 = _落地(键)
    if not os.path.exists(路):
        raise 存不了(f"对象不存在:{键!r} —— "
                   f"库里记着这个键而存储里没有,**说明两边不一致,不是「文件坏了」**")
    with open(路, "rb") as f:
        return f.read()


def 有吗(键):
    try:
        return os.path.exists(_落地(键))
    except 键不合法:
        return False
