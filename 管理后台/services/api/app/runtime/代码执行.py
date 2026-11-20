#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「代码执行」节点最小版(三期 3-4;用户 11-15 拍「做一个最小版备着」,11-20 夜拍「今晚做,安全细节按最严」)。

一段 Python,变量进、声明过类型的变量出。**跑在沙箱里**:
  · macOS `sandbox-exec`(这台机器有、实测拦得住;规划写的 wasm 要下运行时 + python.wasm,没走):
    不联网(deny network*)、不写文件(只许写临时目录)、**不读用户目录**(deny file-read* /Users)、
    不许起别的进程(deny process-exec,只放 /usr/bin/python3 自己那条链)、环境变量清空(env={} + `-I -S`)
  · 限时:RLIMIT_CPU(算得停不下来 → SIGXCPU)+ 墙钟超时(睡着不算 CPU)双保险
  · 限内存:**macOS 上 RLIMIT_AS / RLIMIT_DATA 都设不了**(实测 ValueError)—— 改成每 0.1 秒看一眼 RSS,超了就杀。
    这不是硬限制(两次采样之间能冲过去一点),写明;Linux 上才有真的 rlimit
  · 输出限 64 KB;输出按 output_schema 核类型,不对这一步失败(不悄悄转)
  · 只放 Python 一种;没有 sandbox-exec 的机器(CI 的 Linux)**直接拒跑**,不退回「不隔离直接 exec」—— 那是一条远程代码执行通道

两个数(5 秒 / 64 MB)是拍脑袋的,规划 3-4 写明;上限只许往下配,不许配得比这更大。
纯逻辑(配置问题 / 核输出 / 拼沙箱配置)能离线测;真跑那部分 tests/orchestration/test_code_node.py 四条真攻击。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

限时秒上限 = 5
内存MB上限 = 64
输出字节上限 = 64 * 1024
系统python = "/usr/bin/python3"


class 代码失败(Exception):
    def __init__(self, code, 消息, 建议, 出=None):
        super().__init__(消息)
        self.code, self.消息, self.建议, self.出 = code, 消息, 建议, 出


def 沙箱可用():
    """→ (行不行, 为什么)。只认 macOS 的 sandbox-exec;别的平台这一版不跑(不退回裸 exec)。"""
    if sys.platform != "darwin":
        return False, f"这一版的沙箱只有 macOS 的 sandbox-exec,这台机器是 {sys.platform}"
    if not shutil.which("sandbox-exec"):
        return False, "这台机器没有 sandbox-exec"
    if not os.path.exists(系统python):
        return False, f"没有 {系统python}"
    return True, ""


def 配置问题(cfg):
    """校验器 / 编译器用:→ [(code, 消息, 建议, field_path)]。"""
    出 = []
    cfg = cfg or {}
    代码 = cfg.get("code")
    if not isinstance(代码, str) or not 代码.strip():
        出.append(("CODE_EMPTY", "还没写代码", "在右侧「代码」框里写一个 main(**inputs) 函数,返回一个字典;键要和「结果」里声明的一致", "config.code"))
    if (cfg.get("language") or "python") != "python":
        出.append(("CODE_LANGUAGE", f"只放 Python 一种,{cfg.get('language')} 这一版不跑", "把语言改成 python", "config.language"))
    属性 = ((cfg.get("output_schema") or {}).get("properties") or {})
    if not 属性:
        出.append(("CODE_NO_OUTPUT", "没声明这一步返回什么", "在右侧「结果」里至少加一项,写上类型 —— 代码返回的字典按它核类型", "config.output_schema"))
    上限 = cfg.get("sub_limits") or {}
    秒 = 上限.get("timeout_seconds")
    if 秒 is not None and (isinstance(秒, bool) or not isinstance(秒, (int, float)) or 秒 <= 0 or 秒 > 限时秒上限):
        出.append(("CODE_LIMIT", f"限时要在 1–{限时秒上限} 秒之间(现在 {秒!r})", f"上限 {限时秒上限} 秒是写死的,只能往下配", "config.sub_limits.timeout_seconds"))
    兆 = 上限.get("memory_mb")
    if 兆 is not None and (isinstance(兆, bool) or not isinstance(兆, (int, float)) or 兆 <= 0 or 兆 > 内存MB上限):
        出.append(("CODE_LIMIT", f"内存要在 1–{内存MB上限} MB 之间(现在 {兆!r})", f"上限 {内存MB上限} MB 是写死的,只能往下配", "config.sub_limits.memory_mb"))
    映射 = cfg.get("input_mapping")
    if 映射 is not None and not isinstance(映射, dict):
        出.append(("CODE_INPUT_MAPPING", "「输入变量」的形状不对", "每个变量一个来源", "config.input_mapping"))
    for 名 in (映射 or {}):
        if not re.fullmatch(r"[A-Za-z_一-鿿][A-Za-z0-9_一-鿿]*", str(名)):
            出.append(("CODE_INPUT_NAME", f"输入变量名「{名}」不能当 Python 参数名", "只用字母 / 数字 / 下划线 / 汉字,不以数字开头", f"config.input_mapping.{名}"))
    return 出


_类型判 = {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
       "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
       "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}


def 核输出(output_schema, 出):
    """代码返回的字典按声明核:缺必填 / 类型不对 → 问题清单;没声明的键丢掉(不让代码往下游塞没声明的东西)。→ (干净的输出, 问题)。"""
    属性 = (output_schema or {}).get("properties") or {}
    必填 = set((output_schema or {}).get("required") or [])
    if not isinstance(出, dict):
        return {}, [f"代码要返回一个字典,返回的是 {type(出).__name__}"]
    问题, 干净 = [], {}
    for 名, 定 in 属性.items():
        if 名 not in 出 or 出[名] is None:
            if 名 in 必填:
                问题.append(f"少了必填的「{名}」")
            continue
        t = (定 or {}).get("type")
        判 = _类型判.get(t)
        if 判 and not 判(出[名]):
            问题.append(f"「{名}」要是 {t},返回的是 {type(出[名]).__name__}")
            continue
        干净[名] = 出[名]
    return 干净, 问题


def 沙箱配置(临时目录):
    """sandbox-exec 的 profile。默认全放、再把能出事的几类关死 —— 全拒再放的写法 python 起不来(要太多 mach 服务),
    而关死的这几类正好是四条真攻击打的地方:联网 / 写文件 / 读用户目录 / 起进程。"""
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "{临时目录}"))
(allow file-write-data (literal "/dev/null"))
(deny file-read* (subpath "/Users"))
(deny file-read* (subpath "/private/etc/master.passwd") (subpath "/private/var/root"))
(deny process-exec)
(allow process-exec (literal "{系统python}") (subpath "/Library/Developer/CommandLineTools") (subpath "/System/Library/Frameworks/Python.framework") (subpath "/Applications/Xcode.app"))
"""


包装 = r'''
import json, sys
src = open(sys.argv[1], encoding="utf-8").read()
ns = {"__name__": "__sandbox__"}
exec(compile(src, "main.py", "exec"), ns)
inputs = json.load(sys.stdin)
fn = ns.get("main")
if not callable(fn):
    print(json.dumps({"__error__": "代码里没有 main 函数"}), file=sys.stderr); sys.exit(3)
out = fn(**inputs)
sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
'''


def 跑(cfg, 输入, *, 记事=None):
    """→ 干净的输出字典。失败抛 代码失败(code, 消息, 建议)。"""
    行, 为 = 沙箱可用()
    if not 行:
        raise 代码失败("CODE_SANDBOX_UNAVAILABLE", f"这台机器跑不了代码执行:{为}", "代码执行只在有沙箱的机器上跑;不会退回不隔离直接执行")
    问 = 配置问题(cfg)
    if 问:
        c, m, a, _ = 问[0]
        raise 代码失败(c, m, a)
    上限 = cfg.get("sub_limits") or {}
    秒 = int(min(限时秒上限, 上限.get("timeout_seconds") or 限时秒上限))
    兆 = int(min(内存MB上限, 上限.get("memory_mb") or 内存MB上限))
    目录 = tempfile.mkdtemp(prefix="aimc-code-")
    try:
        with open(os.path.join(目录, "main.py"), "w", encoding="utf-8") as f:
            f.write(cfg["code"])
        with open(os.path.join(目录, "wrap.py"), "w", encoding="utf-8") as f:
            f.write(包装)
        with open(os.path.join(目录, "p.sb"), "w", encoding="utf-8") as f:
            f.write(沙箱配置(目录))
        import resource

        def 限(秒=秒):
            resource.setrlimit(resource.RLIMIT_CPU, (秒, 秒))
            try:
                resource.setrlimit(resource.RLIMIT_AS, (兆 * 1024 * 1024, 兆 * 1024 * 1024))   # Linux 才认;macOS 抛 ValueError,下面靠看 RSS
            except (ValueError, OSError):
                pass
        起 = time.monotonic()
        p = subprocess.Popen(["sandbox-exec", "-f", os.path.join(目录, "p.sb"), 系统python, "-I", "-S", "-B", os.path.join(目录, "wrap.py"), os.path.join(目录, "main.py")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=目录, env={"PATH": "/usr/bin:/bin"},
                             preexec_fn=限)
        try:
            p.stdin.write(json.dumps(输入 or {}, ensure_ascii=False, default=str).encode("utf-8"))
            p.stdin.close()
        except BrokenPipeError:
            pass
        超内存 = False
        while True:
            if p.poll() is not None:
                break
            if time.monotonic() - 起 > 秒 + 1:
                p.kill()
                p.wait()
                raise 代码失败("CODE_TIMEOUT", f"代码跑了超过 {秒} 秒还没停,已经杀掉", "把算法改快,或把限时往上调(最多 5 秒);死循环查不出来就是这一条")
            # macOS 上限内存靠看 RSS(不是硬限制,两次采样之间能冲过去一点)
            try:
                rss = int(subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True, timeout=2).stdout.strip() or 0)
            except Exception:  # noqa: BLE001
                rss = 0
            if rss > 兆 * 1024:
                超内存 = True
                p.kill()
                p.wait()
                break
            time.sleep(0.1)
        if 超内存:
            raise 代码失败("CODE_MEMORY", f"代码用了超过 {兆} MB 内存,已经杀掉", "少装点东西进内存;上限最多 64 MB")
        标 = p.stdout.read(输出字节上限 + 1)
        错 = p.stderr.read(4096).decode("utf-8", "replace")
        if p.returncode == -24 or p.returncode == 152:   # SIGXCPU
            raise 代码失败("CODE_TIMEOUT", f"代码算了超过 {秒} 秒 CPU,被系统停掉", "把算法改快,或把限时往上调(最多 5 秒)")
        if p.returncode != 0:
            末 = 错.strip().splitlines()[-1][:200] if 错.strip() else f"退出码 {p.returncode}"
            码 = "CODE_SANDBOX_DENIED" if ("Operation not permitted" in 错 or "PermissionError" in 错 or "URLError" in 错) else "CODE_RAISED"
            raise 代码失败(码, ("代码想做沙箱不许的事(联网 / 读写文件 / 起进程):" if 码 == "CODE_SANDBOX_DENIED" else "代码抛了错:") + 末,
                        "代码执行只能算、不能碰外面;要取数用前面的步骤取好再交进来" if 码 == "CODE_SANDBOX_DENIED" else "看错误信息改代码;可以用「单独测这一步」反复试",
                        出={"stderr": 错[-1500:]})
        if len(标) > 输出字节上限:
            raise 代码失败("CODE_OUTPUT_TOO_LARGE", f"代码输出超过 {输出字节上限 // 1024} KB", "少返回点东西;大结果放到前面的步骤里分页取")
        try:
            出 = json.loads(标.decode("utf-8"))
        except ValueError:
            raise 代码失败("CODE_OUTPUT_NOT_JSON", "代码返回的东西装不进 JSON", "main 只返回字典,里面放文字 / 数字 / 列表 / 字典")
        干净, 问 = 核输出(cfg.get("output_schema"), 出)
        if 问:
            raise 代码失败("CODE_OUTPUT_TYPE", "代码返回的和「结果」里声明的对不上:" + ";".join(问), "改代码的返回值,或改「结果」里的声明;不悄悄转类型", 出={"返回的": 出})
        if 记事:
            记事("code.ran", {"耗时毫秒": int((time.monotonic() - 起) * 1000), "输出键": sorted(干净)})
        return 干净
    finally:
        shutil.rmtree(目录, ignore_errors=True)
