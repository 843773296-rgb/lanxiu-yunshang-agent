#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨存储 —— **一笔业务事实同时活在好几个地方,只造数据库等于没造。**

## 为什么要这一层

一笔订单在真实系统里长这样:

    主表        MySQL           ordr / ordr_item
    库存计数     Redis           stock:{sku} = 37
    下单事件     Kafka           topic order.created
    商品图       对象存储         /img/xxx.jpg
    搜索索引     ES              doc

只造数据库那一份,测试跑起来会发现缓存是空的、事件没发、图裂了。
**而最坏的地方在于失败方式**:数据库里数据齐全、外键都对、检查全绿 ——
**看起来一切正常**,只有真跑业务才崩。这正是这个项目反复吃亏的形状。

## 这一层的抽象:事实 → 投影

不再以「表」为单位,而是以**业务事实**为单位:

    事实(一笔订单) ──投影──> 关系库:插 2 行
                   ├─────> KV:  stock:S001 减 3
                   ├─────> 事件流:发一条 order.created
                   └─────> 对象:  放一张图

**「一个事实投影到哪几个存储」是业务知识,工具不替业务决定** ——
它只保证:声明了几处就得写几处,少一处要吵,回滚要全删干净。

## 一致性检查:这一层真正值钱的东西

    对账(事实清单) → 每个事实在**每个声明过的存储**里都要找得到
                     缺一处就报「看起来数据是全的,其实缺了缓存/事件」

没有这一条的话,跨存储写入只是「多写了几个文件」;有了它,
**「少写一处」才会有声音** —— 而少写一处正是这类 bug 的全部形态。

## ⚠️ 没接真 Redis / Kafka(诚实清单)

这里只有**文件式适配器**:KV 是一个 JSON 文件、事件流是一个 jsonl 追加文件、
对象存储是一个目录。真驱动没接,原因不是难,是**没有靶子验**:
接了真 Redis 却没有一个带 Redis 的系统可测,那只是「看起来支持」。

这么做不是妥协:**抽象对不对,和用哪个驱动无关** —— 抽象错了,接十个驱动也白搭。
驱动接口(`存储` 那个基类)留在这里,谁有真环境谁补,补的时候自测能原样跑。
"""
import json, os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ── 存储适配器:四种形态,一个接口 ─────────────────────────────────────
class 存储:
    """驱动接口。真 Redis/Kafka 的驱动照着这四个方法补,自测能原样跑。"""
    名 = "?"

    def 写(self, 键, 值):        raise NotImplementedError
    def 读(self, 键):            raise NotImplementedError
    def 删(self, 键):            raise NotImplementedError
    def 清(self, 凭据):          raise NotImplementedError


class KV(存储):
    """键值(Redis 的位置)。文件式实现:一个 JSON 文件。"""
    名 = "KV"

    def __init__(self, path):
        self.path = path
        self.d = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}

    def 写(self, 键, 值):
        self.d[键] = 值
        self._存()
        return 键

    def 读(self, 键):
        return self.d.get(键)

    def 删(self, 键):
        self.d.pop(键, None)
        self._存()

    def 清(self, 凭据):
        for k in 凭据:
            self.d.pop(k, None)
        self._存()

    def _存(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False)


class 事件流(存储):
    """只追加的消息(Kafka 的位置)。文件式实现:一个 jsonl。

    ⚠️ **只追加的东西删不掉。** 真 Kafka 也删不掉 —— 所以回滚靠**打标记**:
    每条带一个批次号,清理时写一条「作废」而不是真删。
    **把「删不掉」说清楚,比假装删干净好。**
    """
    名 = "事件流"

    def __init__(self, path):
        self.path = path

    def 写(self, 键, 值):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"键": 键, "值": 值, "时间": time.time()},
                               ensure_ascii=False) + "\n")
        return 键

    def 读(self, 键):
        if not os.path.exists(self.path):
            return None
        作废 = set()
        命中 = None
        for line in open(self.path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("作废"):
                作废.add(r["作废"])
            elif r.get("键") == 键:
                命中 = r
        return None if (命中 and 命中["键"] in 作废) else 命中

    def 删(self, 键):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"作废": 键, "时间": time.time()}, ensure_ascii=False) + "\n")

    def 清(self, 凭据):
        for k in 凭据:
            self.删(k)


class 对象(存储):
    """大文件(对象存储的位置)。文件式实现:一个目录。"""
    名 = "对象"

    def __init__(self, d):
        self.d = d
        os.makedirs(d, exist_ok=True)

    def _p(self, 键):
        return os.path.join(self.d, 键.replace("/", "_"))

    def 写(self, 键, 值):
        with open(self._p(键), "wb") as f:
            f.write(值 if isinstance(值, bytes) else str(值).encode())
        return 键

    def 读(self, 键):
        p = self._p(键)
        return open(p, "rb").read() if os.path.exists(p) else None

    def 删(self, 键):
        p = self._p(键)
        if os.path.exists(p):
            os.remove(p)

    def 清(self, 凭据):
        for k in 凭据:
            self.删(k)


class 关系库(存储):
    """关系库。读写都按主键 —— 和另外三种对齐,便于统一对账。"""
    名 = "关系库"

    def __init__(self, conn, 表, 主键列):
        self.conn, self.表, self.pk = conn, 表, 主键列

    def 写(self, 键, 值):
        cols = list(值)
        ph = ", ".join([self.conn.ph] * len(cols))
        self.conn.exec(f"insert into {self.conn.ident(self.表)} "
                       f"({', '.join(self.conn.ident(c) for c in cols)}) values ({ph})",
                       tuple(值[c] for c in cols))
        self.conn.commit()
        return 键

    def 读(self, 键):
        r = self.conn.q(f"select * from {self.conn.ident(self.表)} "
                        f"where {self.conn.ident(self.pk)} = {self.conn.ph}", (键,))
        return r[0] if r else None

    def 删(self, 键):
        self.conn.exec(f"delete from {self.conn.ident(self.表)} "
                       f"where {self.conn.ident(self.pk)} = {self.conn.ph}", (键,))
        self.conn.commit()

    def 清(self, 凭据):
        for k in 凭据:
            self.删(k)


# ── 事实 → 投影 ──────────────────────────────────────────────────────
def 落(存储表, 事实, 投影):
    """把一个事实投到各存储。`投影(事实)` 返回 {存储名: [(键, 值), ...]}。

    返回凭据 {存储名: [键...]} —— **回滚要拿它,不猜**。
    """
    凭据 = {}
    for 名, 项 in (投影(事实) or {}).items():
        st = 存储表.get(名)
        if st is None:
            raise SystemExit(f"❌ 投影要写「{名}」,但没登记这个存储 —— "
                             f"**声明了却没有,比没声明更糟**:它会被静默跳过")
        for 键, 值 in 项:
            st.写(键, 值)
            凭据.setdefault(名, []).append(键)
    return 凭据


def 回滚(存储表, 凭据):
    """跨存储删干净。**只追加的存储删不掉,改为打作废标记** —— 它自己会说清楚。"""
    for 名, 键们 in 凭据.items():
        if 名 in 存储表:
            存储表[名].清(键们)


def 对账(存储表, 事实们, 投影, log=lambda *a: None):
    """**每个事实在每个声明过的存储里都要找得到。**

    这一条是整层的价值所在:没有它,跨存储写入只是「多写了几个文件」;
    有了它,**「少写一处」才会有声音** —— 而少写一处正是这类 bug 的全部形态。

    返回缺失清单(空 = 都对得上)。
    """
    缺 = []
    for 事 in 事实们:
        for 名, 项 in (投影(事) or {}).items():
            st = 存储表.get(名)
            for 键, _值 in 项:
                if st is None:
                    缺.append({"事实": 事.get("id"), "存储": 名, "键": 键,
                               "毛病": "这个存储根本没登记"})
                elif st.读(键) is None:
                    缺.append({"事实": 事.get("id"), "存储": 名, "键": 键,
                               "毛病": f"**{名} 里没有这一条** —— 库里看着数据是全的,其实缺了"})
    log(f"对账:{len(事实们)} 个事实 × {len(存储表)} 个存储 → "
        + (f"❌ 缺 {len(缺)} 处" if 缺 else "✅ 每处都找得到"))
    return 缺
