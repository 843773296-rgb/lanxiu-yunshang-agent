#!/usr/bin/env python3
"""安全闸门 —— 这个工具唯一会造成不可逆伤害的地方,全部收在这里。

## 造数工具的两种经典事故

**一、灌错库。** 测试数据写进生产,这一下产品就废了 —— 不是技术上废,是没人再敢用。
所以这里不做「智能识别」,做**显式声明 + 黑名单双保险**:

  · 你必须自己写清楚这是什么环境(`--env dev|test|staging`),不写不给跑
  · 就算你写了 dev,只要目标名字里带生产特征(prod / 正式 / master 库名等),照样拒绝
  · 默认 dry-run。要真写,得再加一个 `--yes`

三道锁的顺序是有讲究的:**声明**防手滑,**黑名单**防声明错,**dry-run** 防前两道都过了但方案是错的。
一道锁挡一类错误,少哪道都不行。

## 二、清不干净

假数据混进测试库出不去,时间长了没人分得清哪条是真的。
所以每次灌入都留一份 **manifest**:每张表、主键列、这次插进去的**每一个主键值**。
回滚就照着 manifest 删,不猜、不按前缀模糊匹配、不按时间戳猜 ——
**「大概是这些」在删数据这件事上不成立。**

主键前缀(`SYN-`)只是给人肉排查用的方便,不是回滚依据。整数主键根本加不了前缀。
"""
import os, re, json, time, datetime

# 边界怎么划,是这里唯一需要动脑子的地方。
# 第一版写的是 `\bprod\b` —— 结果 `shop_prod` **没被拦住**:
# 下划线是词字符,`p` 和 `_` 之间根本不构成词边界。自测抓到的。
#
# 修法不是补一条 `_prod`,是想清楚两类错的代价不对等:
#   · 误拦一个正经开发库 → 用户改个名字,或者骂一句
#   · 漏放一个生产库     → 产品废了
# 所以 `prod` 用**子串**匹配,宁可误拦(`production`/`proddb`/`shop_prod` 一网打尽)。
# 但 `live` 不能用子串 —— 它会匹配 `delivery`,那就是纯添乱了。
# **不是所有词都值得同一种严格度。**
PROD_SUBSTR = ["prod", "正式", "线上", "生产"]
PROD_TOKEN  = ["live", "master", "release", "online"]
def _hit(low):
    for w in PROD_SUBSTR:
        if w in low: return w
    for w in PROD_TOKEN:
        if re.search(r"(?:^|[^a-z0-9])" + w + r"(?:[^a-z0-9]|$)", low): return w
    return None
ENVS = ("dev", "test", "staging")

class Refused(SystemExit):
    pass

def check_target(target, env, write=False):
    """返回一条说明。拒绝就抛 Refused —— 不返回布尔值,免得调用方忘了看。"""
    if env not in ENVS:
        raise Refused(f"必须显式声明环境:--env {'|'.join(ENVS)}(当前:{env!r})\n"
                      f"不提供「自动识别」,因为识别错一次的代价你承担不起。")
    hit = _hit(target.lower())
    if hit:
        raise Refused(f"目标 {target!r} 命中生产特征 {hit!r},拒绝。\n"
                      f"你声明的是 {env},但名字看起来是生产库。**声明和名字打架时,以拒绝为准。**")
    if write and env == "staging":
        return f"⚠️ 预发环境写入 —— 预发常有人在用,确认过再来。"
    return f"目标 {target} · 环境 {env} · {'写入' if write else '只读'}"


def readonly_sample_notice():
    return ("采样只读:结构、聚合、分位数、去重值计数。\n"
            "**不整行读取、不落盘原始行。** 从生产库取分布是合理的,把生产数据复制出来不是。")


def manifest_path(root, label):
    safe = re.sub(r"[^\w.-]", "_", label)
    d = os.path.join(root, ".fakedata")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}.manifest.json")


def write_manifest(path, plan, manifest, env):
    doc = {"生成时间": datetime.datetime.now().isoformat(timespec="seconds"),
           "目标": plan["source"], "环境": env, "种子": plan["seed"],
           "前缀": plan["marker"]["prefix"], "顺序": plan["order"],
           "表": {t: {"pk": m["pk"], "行数": len(m["values"]), "主键": m["values"]}
                  for t, m in manifest.items()}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path


def read_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    ok = 0; fail = []
    def expect_refuse(t, e, why):
        global ok
        try: check_target(t, e); fail.append(f"应该拒绝却放行了:{why}")
        except Refused: ok += 1
    def expect_pass(t, e, why):
        global ok
        try: check_target(t, e); ok += 1
        except Refused as ex: fail.append(f"应该放行却拒绝了:{why} —— {ex}")

    expect_refuse("shop.db", "生产", "环境名不在白名单")
    expect_refuse("shop.db", "", "没声明环境")
    expect_refuse("mysql://u@h/shop_prod", "dev", "库名带 prod,声明成 dev 也不行")
    expect_refuse("mysql://u@h/正式库", "test", "中文生产特征")
    expect_refuse("/data/线上/shop.db", "dev", "路径里的生产特征")
    expect_pass("mysql://u@h/shop_dev", "dev", "正常开发库")
    expect_pass("backend/lanxiu.db", "test", "本地测试库")
    expect_refuse("mysql://u@h/shop_production", "dev", "production 子串")
    expect_refuse("mysql://u@h/proddb", "dev", "prod 无分隔符")
    expect_refuse("mysql://u@h/生产库", "dev", "中文「生产」")
    expect_refuse("mysql://u@h/app_live", "dev", "live 带分隔符")
    expect_pass("mysql://u@h/delivery_dev", "dev", "delivery 不该被 live 误伤")
    expect_pass("/Users/x/mastering_db_test.db", "test", "mastering 不该被 master 误伤")
    print(f"安全闸门自测:{ok} 通过 / {len(fail)} 失败")
    for f_ in fail: print("  ✗", f_)
    raise SystemExit(1 if fail else 0)
