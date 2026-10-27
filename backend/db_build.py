"""这个库是谁、用哪一版造数逻辑建出来的 —— 记在库自己身上(world_meta),任何读库的人都查得到。

为什么(10-26 并行会话提的,两边商定):评测基线的「来路」记了供应商 / 模型 / 时间 / 代码 sha,**没记库**。
那天合并题改按账户、新增 IT- 测试客户之后,
> 一份「同样条件下跑出来的」基线,和一份「库已经换了内容」的基线,在「来路」上长得一模一样。
新代码 + 旧库跑出的成绩单也一样看不出来。记在评测结果里只有写结果的那个脚本知道;记在库里,
夜跑、门禁、合并评测、技能触发评测都能读。

字段(world_meta 的键,**名字只在这里定一次**,读的人用 读() 取,别手抄键名):
  build_commit     重建时的提交号(工作区有没提交的造数改动时带 +dirty)
  build_at         重建完成时刻
  build_logic_fp   造数逻辑的内容指纹:rebuild.sh 步骤清单里的每个脚本 + 它们一路 import 到、登记成「算」的本地模块
                   + knowledge/ 下的 .md(手写真相源),按内容算 —— 范围见下面「指纹范围」那一段
  build_logic_n    算进指纹的文件数(0 说明没找到文件 —— 那不是指纹,是空集合)
  build_fp_ver     指纹定义本身的版本(登记表 + 走法):两份章 fp 不同而这个也不同 = 指纹算法变了,不是库换了(10-27 加)

**造数逻辑不变,指纹就不变**:每日平移、评测运行时写进库的行都不影响它 —— 比「关键表行数」稳。

    python3 backend/db_build.py --盖章 --重建时   # rebuild.sh 最后调:库刚按工作区的代码建完
    python3 backend/db_build.py --盖章            # 单独补盖:工作区落后 origin/main 就拒绝
    python3 backend/db_build.py --范围检查        # 进门禁:造数脚本 import 到的每个本地模块都认领过
    python3 backend/db_build.py                   # 看当前库盖的章,和现在的造数逻辑比一比

## 指纹范围(用户 2026-10-27 拍方案 A:明确登记 + 检查逼着认领)

并行会话 10-27 指出两个缺口,都是「指纹变不变」和「库变不变」对不上:
  · **多算**:knowledge/ 整目录收进来,而 motif.py 这类口径是读的时候算的、不落库 —— 改它库一字不变,指纹却变,
    逼人白重建 30 分钟
  · **漏算**:只收 rebuild.sh 里直接出现的脚本,不跟 import —— ensure_tables 只是 import motif_review / ownership
    去建表,改那些模块会改重建结果,指纹一个字符不动
> 一个「造数逻辑变了」和一个「只有读取口径变了」,在指纹变化上长得一模一样;反过来也一样。

做法:从造数脚本出发沿 import 走,**每个走到的本地模块必须在 算 / 不算 两张表之一**(不算要写理由,
走到「不算」就不往下走)。新加一个模块没认领 → `--范围检查` 红;表里登记了却已经走不到 → 也红(豁免不许囤积)。
没选「自动全跟」:api.py 这类门面几乎每次提交都改(工具说明),全跟的话指纹次次变,等于没有指纹。
"""
import ast
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

咬合 = [
    ("造数脚本新 import 一个谁都没认领的本地模块", "没认领"),
    ("「不算」里登记一个早就走不到的模块", "登记了却走不到"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "lanxiu.db")
键 = ("build_commit", "build_at", "build_logic_fp", "build_logic_n", "build_fp_ver")

# 造数脚本 import 到、但**不影响重建出来的库**的本地模块 —— 走到这里就停,不往下跟。每条要写为什么
# ⚠️ **「不往下跟」本身是代价**(并行会话 10-27 提醒):经这些门面才 import 到的模块不进指纹。
#    以后有人顺着 api.py 加了一个真会改造数结果的模块,它会落在指纹外面,而这张表看起来是认领过的 ——
#    所以:造数要用的新模块,在**造数脚本里直接 import**(那样它会被走到、被逼着认领),别只经门面拿
不算 = {
    "backend/api.py": "工具门面:几乎每次提交都改工具说明;造数用到的那几段逻辑下沉在 report_doc / order_write 等模块,那些单独算",
    "backend/server.py": "网页服务:只管请求进出,不建表、不造数",
    "prompts.py": "提示词:给模型看的规矩,不进库",
    "backend/mcp_registry.py": "MCP 服务登记,不进库",
    "backend/skill_registry.py": "技能登记,不进库",
    "knowledge/motif.py": "纹样口径:读的时候现算、不落库(并行会话 10-27 核过)",
}
# 造数脚本 import 到、**会影响重建结果**的本地模块(2026-10-27 首次登记:当时走到的除「不算」外全部)。
# 新加的模块默认不在任何一张表里 → --范围检查 红,逼着认领
算 = frozenset("""
backend/account_owner.py backend/alert_dispatch.py backend/arrival_card.py backend/asr.py backend/body_gen.py
backend/booking.py backend/combo_manual.py backend/credit.py backend/escalation.py backend/factory_inbox.py
backend/files.py backend/fitting_write.py backend/fix_advisor_ref.py backend/fix_order_measure.py
backend/fix_product_pattern.py backend/fsm.py backend/grade_diff.py backend/it_customer.py backend/kb_issue.py
backend/measure_write.py backend/merge.py backend/oplog.py backend/opportunity.py backend/opportunity_store.py
backend/ops.py backend/order_contract.py backend/order_write.py backend/ownership.py backend/pickup_write.py
backend/product_summary.py backend/query_index.py backend/rating_shadow.py backend/refund_write.py
backend/repair_write.py backend/report_doc.py backend/report_template.py backend/roster.py backend/seed_quote.py
backend/seed_rating.py backend/shop_key.py backend/simplified.py backend/tasks.py backend/tasktypes.py
backend/terms_store.py backend/touchpoint.py backend/triage_config.py backend/triage_run.py backend/triage_trial.py
backend/worldclock.py
backend/example_pool.py backend/lifecycle_check.py backend/motif_review.py backend/rating_write.py backend/relabel.py knowledge/attribution.py
knowledge/capacity.py knowledge/churn.py knowledge/consent_age.py knowledge/contract_terms.py knowledge/derive_combo.py knowledge/derive_pattern.py
knowledge/derive_xingzhi.py knowledge/ecom.py knowledge/factory_feed.py knowledge/fitting.py knowledge/freight.py knowledge/grading.py
knowledge/growth.py knowledge/journey.py knowledge/kb.py knowledge/leadtime.py knowledge/liability.py knowledge/lifecycle.py
knowledge/linkage.py knowledge/margin.py knowledge/measure.py knowledge/member.py knowledge/muslin.py knowledge/oppo.py
knowledge/oppo_obj.py knowledge/order_gate.py knowledge/order_place.py knowledge/owner.py knowledge/part.py knowledge/pickup.py
knowledge/piece_ratio.py knowledge/purchase_pref.py knowledge/rating.py knowledge/recording_terms.py knowledge/refund_replay.py knowledge/repair.py
knowledge/rfm.py knowledge/shift.py knowledge/source.py knowledge/stockalert.py knowledge/traits.py
""".split())
# 10-27 第二批:knowledge/ 下被造数脚本 import 到的口径模块(原来整目录都算,现在逐个认领;motif.py 除外,见「不算」)、
# 以及 motif_review(纹样核定的建表实现,ensure_tables 只是 import 它)等


def 指纹算法版本():
    """**指纹的定义本身**的版本(并行会话 10-27 提):两份章 fp 不同时,先看这个 ——
    它也不同,说明是「指纹怎么算」变了(重新盖章就行),不是「库换了」(要重跑基线)。
    > 一个「库真的换了」和一个「指纹的算法换了」,在「两版 fp 不相等」上长得一模一样。
    按登记表 + 这套走法的版本号算;登记表加减一个模块,这个也变。"""
    h = hashlib.sha256(b"walk-imports-v1\0")
    for x in sorted(算):
        h.update(x.encode() + b"\0")
    h.update(b"--\0")
    for x in sorted(不算):
        h.update(x.encode() + b"\0")
    return h.hexdigest()[:12]


def _认(名):
    """import 名 → 仓库里的本地文件(相对路径);不是本地模块 → None。搜索顺序和各脚本的 sys.path 一致"""
    段 = 名.split(".")
    for d in ("backend", "knowledge", "tools", ""):
        for p in (os.path.join(d, *段) + ".py", os.path.join(d, *段, "__init__.py")):
            if os.path.isfile(os.path.join(ROOT, p)):
                return os.path.normpath(p)
    return None


def _引用(p):
    try:
        树 = ast.parse(open(os.path.join(ROOT, p), encoding="utf-8").read())
    except (OSError, SyntaxError):
        return set()
    名们 = set()
    for n in ast.walk(树):
        if isinstance(n, ast.Import):
            名们 |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            名们 |= {n.module} | {f"{n.module}.{a.name}" for a in n.names}
    return {r for r in map(_认, 名们) if r}


def _步骤脚本():
    try:
        sh = open(os.path.join(ROOT, "tools", "rebuild.sh"), encoding="utf-8").read()
    except OSError:
        return set()
    return {m.group(1) for m in re.finditer(r'"((?:backend|tools)/[^"\s]+\.py)', sh)
            if os.path.isfile(os.path.join(ROOT, m.group(1)))}


def 走到的模块():
    """从造数脚本出发沿 import 走,走到「不算」就停 → (走到的模块集合,不含脚本自己)。"""
    起 = _步骤脚本()
    见, 待 = set(), list(起)
    while 待:
        p = 待.pop()
        if p in 见:
            continue
        见.add(p)
        if p not in 不算:
            待.extend(_引用(p) - 见)
    return 见 - 起


def 范围检查():
    """→ (没认领的, 登记了却走不到的)。两样都空才算过。"""
    走到 = 走到的模块()
    return sorted(走到 - 算 - set(不算)), sorted((算 | set(不算)) - 走到)


def 造数文件():
    """造数脚本 + 走到的、登记成「算」的模块 + knowledge/ 下的 .md(排序后的相对路径)。"""
    文 = _步骤脚本() | (走到的模块() & 算)
    kd = os.path.join(ROOT, "knowledge")
    for n in (os.listdir(kd) if os.path.isdir(kd) else []):
        if n.endswith(".md"):
            文.add(f"knowledge/{n}")
    return sorted(x for x in 文 if os.path.isfile(os.path.join(ROOT, x)))


def 当前指纹():
    """→ (指纹, 文件数, 提交号)。指纹按**文件内容**算(工作区里没提交的改动也算进去)。"""
    h = hashlib.sha256()
    文 = 造数文件()
    for p in 文:
        h.update(p.encode()); h.update(b"\0")
        h.update(open(os.path.join(ROOT, p), "rb").read()); h.update(b"\0")
    try:
        头 = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=12", "HEAD"],
                           capture_output=True, text=True, timeout=10).stdout.strip() or "(取不到)"
        脏 = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", *文],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        头, 脏 = "(取不到)", ""
    return h.hexdigest()[:16], len(文), 头 + ("+dirty" if 脏 else "")


def 读(db=None):
    """库上盖的章 → {build_commit, build_at, build_logic_fp, build_logic_n};没盖过的键值是 None。

    ⚠️ **值全是字符串**(world_meta.v 是 TEXT 列):build_logic_n 读回来是 "12" 不是 12 ——
    要比大小先转 int(并行会话 10-27 接评测来路时撞到:自造的整数对照全绿,真库一跑 TypeError)。"""
    c = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    try:
        有 = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_meta'").fetchone()
        行 = dict(c.execute(f"SELECT k, v FROM world_meta WHERE k IN ({','.join('?' * len(键))})", 键).fetchall()) if 有 else {}
    finally:
        c.close()
    return {k: 行.get(k) for k in 键}


def 落后几个():
    """工作区落后 origin/main 几个提交;取不到(没网、没这个远端)→ None,**不当成 0**。"""
    try:
        subprocess.run(["git", "-C", ROOT, "fetch", "-q", "origin", "main"], capture_output=True, timeout=30)
        r = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "HEAD..origin/main"],
                           capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def 盖章(db=None, 重建时=False):
    """`重建时` = 库刚按工作区的代码建完(rebuild.sh 调):落后也照盖,章上写明落后几个。
    单独补盖时**落后就拒绝**(并行会话 10-27 踩过:落后一个提交补盖,章记的是盖章那一刻工作区的逻辑,
    不是建库用的逻辑 —— 四个字段全有值、格式全对,看不出来)。"""
    fp, n, 头 = 当前指纹()
    if not n:
        sys.exit("❌ 一个造数文件都没找到 —— 算出来的不是指纹,不盖")
    落后 = 落后几个()
    if 落后 and not 重建时:
        sys.exit(f"❌ 工作区落后 origin/main {落后} 个提交 —— 补盖的话章记的是旧逻辑。先 git pull --rebase --autostash 再盖")
    if 落后:
        头 += f"+落后{落后}"
    elif 落后 is None:
        头 += "+没核落后"
    c = sqlite3.connect(db or DB)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS world_meta(k TEXT PRIMARY KEY, v TEXT)")
        建于 = datetime.now().isoformat(timespec="seconds")   # 真实时钟:记库在真实世界里什么时候建的,和演示世界日期无关
        for k, v in zip(键, (头, 建于, fp, str(n), 指纹算法版本())):
            c.execute("INSERT INTO world_meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        c.commit()
    finally:
        c.close()
    return 读(db)


if __name__ == "__main__":
    if "--范围检查" in sys.argv:
        没认, 过期 = 范围检查()
        走到 = 走到的模块()
        print(f"造数脚本 {len(_步骤脚本())} 个,一路 import 到本地模块 {len(走到)} 个(算 {len(走到 & 算)} · 不算 {len(走到 & set(不算))})")
        if len(_步骤脚本()) < 10:
            sys.exit("❌ 造数脚本不到 10 个 —— 多半是 rebuild.sh 没读到,这不叫查过")
        for x in 没认:
            print(f"  ❌ 没认领:{x} —— 在 backend/db_build.py 的「算」或「不算(写理由)」里登记它")
        for x in 过期:
            print(f"  ❌ 登记了却走不到:{x} —— 从表里删掉(豁免不许囤积)")
        if 没认 or 过期:
            sys.exit(1)
        print("✅ 造数脚本 import 到的每个本地模块都认领过")
        sys.exit(0)
    if "--盖章" in sys.argv:
        r = 盖章(重建时="--重建时" in sys.argv)
        print(f"✅ 库已盖章:提交 {r['build_commit']} · 造数指纹 {r['build_logic_fp']}({r['build_logic_n']} 个文件)· {r['build_at']}")
    else:
        r, (fp, n, 头) = 读(), 当前指纹()
        print(f"库上的章:{r}")
        print(f"现在的造数逻辑:指纹 {fp}({n} 个文件)· 提交 {头}")
        if not r["build_logic_fp"]:
            print("⚠️ 这个库没盖过章 —— 不知道是哪一版造数逻辑建的(10-26 之前建的库都这样)")
        elif r["build_fp_ver"] != 指纹算法版本():
            print("⚠️ **指纹的定义变了**(登记表或走法改过;章上 build_fp_ver "
                  f"{r['build_fp_ver']} ≠ 现在 {指纹算法版本()})—— 这说明不了库换没换,重新盖章再比")
        elif r["build_logic_fp"] != fp:
            print("⚠️ **库是旧造数逻辑建的**,和现在的代码对不上 —— 在它上面跑出的评测不能和新库上的比")
        else:
            print("✅ 库和现在的造数逻辑一致")
