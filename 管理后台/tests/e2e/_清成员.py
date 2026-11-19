"""端到端测试自己加的临时成员,进程退出时删掉(11-19,还体检那条「687 个假成员」的根)。

起因:有几份测试为了验「没权限的人被拒」「发密钥的人被降级后」,往**真实项目**里 POST /memberships
加一个临时工号(E2EISV… / E2EAK… 这类),收尾时只清自己建的单子、不清这个人 —— 每跑一次门禁就多一批。
11-18 体检时 687 个,11-19 晚上 775 个。成员页、审计都被淹。

用户 11-19 拍「残留先不动」,所以这里**只止血、不清存量**:每份测试把自己加的工号登记进来,
进程退出时(atexit:正常结束、断言挂了、sys.exit 都走)按「项目 + 工号」逐个删。

⚠️ 两道保险,都别去掉:
  · 只删**本进程登记过**的工号 —— 别按前缀一把删,别的测试可能正同时在用它的临时人
  · 登记时工号必须以 `E2E` 开头,不是就当场抛错 —— 防止哪天有人把真工号(U001)登记进来被删掉
memberships 没有别的表外键指向它(11-19 查 pg_constraint 为空),删行不连带别的数据;审计里那条 membership.create 照留。
"""
import atexit
import os

_我加的 = []


def 记(项目, 工号):
    """登记一个本测试临时加的成员,原样返回工号,方便写成 `无权 = 记(项目, "E2EXXV" + …)`。"""
    if not str(工号).startswith("E2E"):
        raise ValueError(f"只登记测试造的临时工号(E2E 开头),拿到的是 {工号!r} —— 真工号不许进收尾删除名单")
    _我加的.append((项目, 工号))
    return 工号


def 清():
    if not _我加的:
        return
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    删了 = 0
    try:
        with create_engine(url).begin() as c:
            for 项目, 工号 in _我加的:
                删了 += c.execute(text("delete from memberships where project_id=:p and user_id=:u and user_id like 'E2E%'"),
                                {"p": 项目, "u": 工号}).rowcount
    except Exception as e:  # noqa: BLE001 —— 收尾失败不改测试结论,但要说出来
        print(f"  ⚠️ 收尾删临时成员失败(登记了 {len(_我加的)} 个,没删掉):{type(e).__name__}: {e}")
        return
    print(f"  🧹 收尾删了本测试临时加的成员 {删了}/{len(set(_我加的))} 个")
    _我加的.clear()


atexit.register(清)
