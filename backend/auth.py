#!/usr/bin/env python3
"""员工登录与会话 —— **让「你是谁」从约定变成结构**。

## 为什么必须有它

`check_write` 判「顾问不能补录、店长可以」,`resolve_combo` 要求「工艺负责人及以上才能回填」——
这些判定的**逻辑**是结构性的(rules.py 真的会拒绝),
但**「你是谁」这件事原来是纯约定的**:role 从请求体里读,你说你是店长就是店长。

**一条链上有一环是约定,整条链就只有约定那么强。**

现在角色只从**服务端会话**取,请求体里的 role 一律忽略。

## 存哪

会话在内存里一份,**另落一份到库旁边的小文件**(`.auth_sessions.json`,不进版本库)。
原来只在内存里(「假数据项目不需要持久会话」),2026-10-23 用户撞到:
「为什么我登录后会自动退出登录?」—— 那天为了让改动生效重启了好几次服务,**每重启一次全员掉线**,
而在用的人看到的就是「莫名其妙被踢出去」。
· 文件里**不存令牌本身**,只存它的 sha256 指纹 —— 文件被人看到也拿不出能用的令牌
· 不写进业务库:不想让「谁登录过」变成一张要维护、要被每日平移扫的表
· 文件跟着 DB 走(库副本旁边就是副本自己的文件)—— 检查在副本上登录,不会往真文件里写
· 过期照旧 12 小时,退出登录照旧立刻失效(两边一起删)
真上线要换成 Redis 或带签名的 cookie —— 那时候这个模块的接口不用变。

## 口令

演示口令统一 `lanxiu@2026`,写在 seed 里(它本来就是公开的演示密码)。
**明文一个字都不落库**,只存 PBKDF2 + 每人独立 salt。
真上线要加「首次登录强制改密」。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import hashlib, hmac, json, os, secrets, sqlite3, threading, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

_SESS = {}                    # token → {no, name, role, shop, at}
_LOCK = threading.Lock()
TTL_HOURS = 12
MAX_FAIL = 5                  # 连续失败几次锁定
LOCK_MIN = 15


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「查无此人」单独报一句话(从报错就能试出哪个工号存在)',
     '查无此人和密码错'),
]

def _rows(sql, *a):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    try: return [dict(r) for r in c.execute(sql, a)]
    finally: c.close()


def _bump_fail(no, reset=False):
    """失败计数写回。**这是登录路径唯一的写操作** —— 它必须写,否则锁定形同虚设。"""
    with closing(sqlite3.connect(DB)) as c, c:
        if reset:
            c.execute("UPDATE staff SET fail_count=0,locked_until=NULL,last_login=? WHERE no=?",
                      (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), no))
        else:
            c.execute("UPDATE staff SET fail_count=COALESCE(fail_count,0)+1 WHERE no=?", (no,))
            n = c.execute("SELECT fail_count FROM staff WHERE no=?", (no,)).fetchone()[0]
            if n >= MAX_FAIL:
                until = (dt.datetime.now() + dt.timedelta(minutes=LOCK_MIN)
                         ).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("UPDATE staff SET locked_until=? WHERE no=?", (until, no))


# ── 落盘那一份 ─────────────────────────────────────────────────────────
def _文件():
    return os.path.join(os.path.dirname(os.path.abspath(DB)), ".auth_sessions.json")


def _指纹(tok):
    return hashlib.sha256((tok or "").encode()).hexdigest()


def _读盘():
    try:
        with open(_文件(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _写盘(d):
    """调用方已持 _LOCK。顺手清掉过期的;写临时文件再换名 —— 半截文件比没有文件更难查。"""
    限 = (dt.datetime.now() - dt.timedelta(hours=TTL_HOURS)).isoformat()
    d = {k: v for k, v in d.items() if (v.get("at") or "") > 限}
    try:
        tmp = _文件() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, _文件())
    except OSError:
        pass        # 写不进去就只剩内存那份(重启掉线),不因此拒绝登录


def login(login_name, password):
    """返回 (token, 用户信息) 或 (None, 错误原因)。

    **失败原因一律说「工号或密码不对」** —— 不区分「查无此人」和「密码错」,
    否则登录接口就成了一个「这个工号存不存在」的探测器。
    """
    rs = _rows("SELECT * FROM staff WHERE login_name=?", (login_name or "").strip())
    if not rs: return None, "工号或密码不对"
    u = rs[0]
    if (u.get("status") or "") != "启用":
        return None, f"这个账号已{u.get('status') or '停用'},请联系总部运营"
    lk = u.get("locked_until")
    if lk and lk > dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return None, f"连续输错 {MAX_FAIL} 次已锁定,{lk} 之后再试"
    algo = u.get("pwd_algo") or ""
    if not (algo.startswith("pbkdf2_sha256$") and u.get("pwd_salt") and u.get("pwd_hash")):
        return None, "这个账号还没设密码,请联系总部运营"
    it = int(algo.split("$", 1)[1])
    got = hashlib.pbkdf2_hmac("sha256", (password or "").encode(),
                              bytes.fromhex(u["pwd_salt"]), it).hex()
    # **定长比较**,不用 == —— 逐字符比较的耗时会泄漏前几位对不对
    if not hmac.compare_digest(got, u["pwd_hash"]):
        _bump_fail(u["no"])
        return None, "工号或密码不对"
    _bump_fail(u["no"], reset=True)
    tok = secrets.token_urlsafe(24)
    who = {"no": u["no"], "name": u["name"], "role": u["role"], "shop": u["shop"]}
    now = dt.datetime.now()
    with _LOCK:
        _SESS[tok] = dict(who, at=now)
        d = _读盘(); d[_指纹(tok)] = dict(who, at=now.isoformat()); _写盘(d)
    return tok, who


def who(token):
    """token → 用户信息;无效或过期返回 None。"""
    with _LOCK:
        s = _SESS.get(token or "")
        if not s and token:
            # 内存里没有:可能是服务重启过 —— 去落盘那份按指纹找回来
            p = _读盘().get(_指纹(token))
            if p:
                try:
                    s = dict(p, at=dt.datetime.fromisoformat(p["at"]))
                    _SESS[token] = s
                except (KeyError, ValueError):
                    s = None
        if not s: return None
        if (dt.datetime.now() - s["at"]).total_seconds() > TTL_HOURS * 3600:
            _SESS.pop(token, None); return None
        return {k: s[k] for k in ("no", "name", "role", "shop")}


def logout(token):
    with _LOCK:
        _SESS.pop(token or "", None)
        d = _读盘()
        if d.pop(_指纹(token), None) is not None:
            _写盘(d)


def sessions():
    return len(_SESS)


if __name__ == "__main__":
    import sys
    print("员工登录自测")
    print("=" * 60)
    ok = 0
    t, u = login("60000001", "lanxiu@2026")
    print(f"  {'✅' if t else '❌'} 正确口令登录 → {u}"); ok += bool(t)
    print(f"  {'✅' if who(t) else '❌'} token 换得回身份 → {who(t)}"); ok += bool(who(t))
    t2, e = login("60000001", "错的")
    print(f"  {'✅' if not t2 else '❌'} 错口令被拒 → {e}"); ok += not t2
    t3, e3 = login("不存在的工号", "随便")
    same = (e3 == "工号或密码不对")
    print(f"  {'✅' if same else '❌'} 查无此人和密码错**报同一句** → {e3}"); ok += same
    logout(t)
    print(f"  {'✅' if not who(t) else '❌'} 登出后 token 失效"); ok += not who(t)
    print("=" * 60)
    if ok < 5: print("❌ 登录自测没过"); sys.exit(1)
    print("✅ 5 条全过 —— 口令、锁定、不泄漏工号是否存在、登出都对")
