#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铺数据集,**每一个专门针对导出接口的一道闸**。

    python3 tools/seed_datasets.py

## 为什么不是「铺一批看起来正常的数据」

一批「正常」数据只能证明顺路能走通。而这个接口的价值全在**拦**那一侧:
七道闸里有六道是拒。所以每个数据集只为一道闸而生,名字里就写着它考哪一条 ——
下一个人打开列表页,看到的是**一张判据自测表**,不是一堆假数据。

(同一个做法用过两次:`tools/seed_evals.py` 里那几份**故意互相不可比**的评测,
 `tools/seed_human_requests.py` 里每条针对一条审批判断。)

⚠️ 已有的 `汉服工艺问答`(5 条全是独立测试、没声明脱敏策略)不动 ——
它天然就是「没声明策略」+「一条可训练的都不剩」两道闸的样本,
而**真实存在的反例比造出来的更有说服力**。
"""
import hashlib, json, os, sys, uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "services", "api", "app"))
from sqlalchemy import text
from db import 事务

项目 = os.environ.get("SEED_PROJECT", "project_demo_a")


def _h(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]


# (名字, 脱敏策略, [(分集, 复核, 组, 来源)...], 它考哪一道闸)
清单 = [
    ("导出能过的那一份", "无需脱敏:题面和答案都是工艺知识,不含客户信息",
     [("训练", "已通过", "g-立领", "seed"), ("训练", "已通过", "g-琵琶袖", "seed")],
     "顺路:七道闸全过 → 真的给 NDJSON"),

    ("声明了需要脱敏的那一份", "要去掉顾客姓名和手机号",
     [("训练", "已通过", "g-改尺", "seed")],
     "脱敏器还没选型 → **501,而且不给不脱的版本**"),

    ("同一组跨了分集的那一份", "无需脱敏:构造数据",
     [("训练", "已通过", "g-同组", "seed"), ("独立测试", "已通过", "g-同组", "seed")],
     "同组跨分集 → 拒**整批**(不过滤掉冲突的那几条)"),

    ("全是 mock 产物的那一份", "无需脱敏:mock 产物",
     [("训练", "已通过", "g-mock1", "mock"), ("训练", "已通过", "g-mock2", "mock")],
     "mock 默认拒;`要mock=1` 才给,而且文件名和审计都带 MOCK"),

    ("训练档但没复核的那一份", "无需脱敏:构造数据",
     [("训练", "待复核", "g-待1", "seed"), ("训练", "已退回", "g-待2", "seed")],
     "没复核的不出去 → 一条不剩 → 拒(并报出「训练档 2 条、过复核 0 条」)"),

    ("一个样本都没有的那一份", "无需脱敏:空集",
     [],
     "空数据集 → 拒。⚠️ 这条**必须第一个判** —— 后面每道闸在空集上都恰好通过"),

    # ── 第八道闸(敏感信息检测,方案 B 受限首版)的两份 ──────────────
    ("来源没做过覆盖验证的那一份", "无需脱敏:构造数据",
     [("训练", "已通过", "g-未验1", "production"), ("训练", "已通过", "g-未验2", "production")],
     "⚠️ **零命中也不放行** —— 来源 `production` 不在覆盖已验证的白名单里。"
     "检测器没找到只说明没找到,不说明没有"),

    ("里面真带客户信息的那一份", "无需脱敏:构造数据",
     [("训练", "已通过", "g-脏1", "seed"), ("训练", "已通过", "g-脏2", "seed"),
      ("训练", "已通过", "g-净", "seed")],
     "三条里两条带敏感信息(手机号 / 称呼式姓名)→ **隔离那两条,放行第三条**,"
     "并在审计里记下隔离了谁、为什么"),

    ("全部都带客户信息的那一份", "无需脱敏:构造数据",
     [("训练", "已通过", "g-全脏1", "seed"), ("训练", "已通过", "g-全脏2", "seed")],
     "两条全命中 → **一条不剩** → 422 ALL_QUARANTINED。"
     "⚠️ 同样**不返回空文件**:空的 .jsonl 看起来是成功的"),
]

# 「里面真带客户信息的那一份」要的是**真的有东西可检**的正文,
# 所以它的内容不走下面那个通用模板 —— 按组号单独给。
# ⚠️ 这里的手机号和姓名都是**编的**,不是库里任何真实客户的 ——
# 种子脚本进版本库,往里写真实客户信息就是把它提交上去了。
脏内容 = {
    "g-脏1": "顾客留的电话是 13912345678,说下周来试衣",
    "g-脏2": "小周说袖长再放两公分",
    "g-净": "这件云锦用的是妆花工艺,工期要六周",
    "g-全脏1": "客户电话 13800138000,住浙江省杭州市",
    "g-全脏2": "周先生的身份证 330102199001011234 收到了",
}


def main():
    建了 = []
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {项目}"); return 1
        for 名, 策略, 样本们, 考什么 in 清单:
            旧 = c.execute(text("""select id from datasets
                                 where project_id=:p and name=:n"""),
                           {"p": 项目, "n": 名}).scalar()
            if 旧:
                # **幂等:同名的先清掉再建。** 不清的话每跑一次多一份同名数据集,
                # 而列表页上五份「导出能过的那一份」谁也说不清该看哪个。
                c.execute(text("delete from samples where dataset_id=:d"), {"d": 旧})
                c.execute(text("delete from dataset_versions where dataset_id=:d"), {"d": 旧})
                c.execute(text("delete from datasets where id=:d"), {"d": 旧})
            dsid = f"ds_{uuid.uuid4().hex[:10]}"
            c.execute(text("""insert into datasets (id, organization_id, project_id, name,
                                  format, purpose, redaction_policy, created_at, created_by,
                                  updated_at, revision)
                             values (:i,:o,:p,:n,'qa',:考,:r, now(), 'seed', now(), 1)"""),
                      {"i": dsid, "o": org, "p": 项目, "n": 名, "考": 考什么, "r": 策略})
            for k, (分集, 复核, 组, 来源) in enumerate(样本们):
                if 组 in 脏内容:
                    内容 = {"messages": [
                        {"role": "user", "content": 脏内容[组]},
                        {"role": "assistant", "content": "好的,已记下"}]}
                else:
                    内容 = {"messages": [
                        {"role": "user", "content": f"{名} 第 {k+1} 题:这个工艺怎么做"},
                        {"role": "assistant", "content": f"{名} 第 {k+1} 答:按工序来"}]}
                c.execute(text("""insert into samples (id, organization_id, project_id,
                                      dataset_id, content, source, review_status, split,
                                      group_id, content_hash, created_at, created_by,
                                      updated_at, revision)
                                 values (:i,:o,:p,:d, cast(:c as jsonb), :s,:rv,:sp,:g,:h,
                                         now(),'seed', now(), 1)"""),
                          {"i": f"smp_{uuid.uuid4().hex[:10]}", "o": org, "p": 项目,
                           "d": dsid, "c": json.dumps(内容, ensure_ascii=False),
                           "s": 来源, "rv": 复核, "sp": 分集, "g": 组, "h": _h(内容)})
            建了.append((名, dsid, len(样本们), 考什么))

    print(f"\n铺了 {len(建了)} 份数据集,每份专考一道闸:\n")
    for 名, dsid, n, 考 in 建了:
        print(f"  {名}({n} 条) {dsid}")
        print(f"      → {考}")
    print("\n⚠️ 已有的「汉服工艺问答」没动 —— 它天然是「没声明策略」那道闸的真实反例")
    return 0


if __name__ == "__main__":
    sys.exit(main())
