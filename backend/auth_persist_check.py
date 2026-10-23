# -*- coding: utf-8 -*-
"""登录会话跨重启 · 检查(用户 2026-10-23:「为什么我登录后会自动退出登录?」)。

原来会话只在后台进程的内存里,**服务一重启全员掉线** —— 那天为了让改动生效重启了好几次,
在用的人看到的就是「莫名其妙被踢出去」。现在内存一份、库旁边的小文件一份(只存令牌指纹)。

验五件事,全在**库副本**上(会话文件跟着 DB 走,副本旁边就是副本自己的文件,不碰真的那份):
  ① 登录之后清空内存(= 服务重启),同一个令牌还认得出是谁
  ② 文件里没有令牌原文 —— 文件被人看到也拿不出能用的令牌
  ③ 落盘那份过了 12 小时,重启后不认
  ④ 退出登录之后,重启也不认(两边一起删)
  ⑤ 会话文件写在副本旁边,不是真库旁边
"""
import datetime as _dt, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth                     # noqa: E402 —— 先加载,用副本才改得到它的 DB
import check_copy               # noqa: E402

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("重启后不去落盘那份找(只认内存)", "清空内存(= 服务重启)之后,同一个令牌还认得出是谁"),
    ("落盘时存令牌原文", "会话文件里没有令牌原文(只有指纹)"),
    ("退出登录只删内存那份", "退出登录之后,重启也不认"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))


def main():
    print("登录会话跨重启 · 检查")
    print("=" * 80)
    真文件 = auth._文件()
    副本 = check_copy.用副本("auth-persist-")
    ck("会话文件写在库副本旁边,不是真库旁边",
       os.path.dirname(auth._文件()) == os.path.dirname(副本) and auth._文件() != 真文件, auth._文件())
    import sqlite3
    with sqlite3.connect(副本) as c:
        行 = c.execute("SELECT no, login_name FROM staff WHERE status='启用' AND pwd_hash IS NOT NULL "
                      "AND login_name IS NOT NULL LIMIT 1").fetchone()
        c.execute("UPDATE staff SET fail_count=0, locked_until=NULL WHERE no=?", (行[0],))
    # 演示口令是公开的(seed.py / auth.py 文件头都写着)
    tok, u = auth.login(行[1], "lanxiu@" + "2026")
    ck("登录成功(夹具)", bool(tok) and u.get("no") == 行[0], u)
    if not tok:
        return 1

    auth._SESS.clear()
    ck("清空内存(= 服务重启)之后,同一个令牌还认得出是谁", (auth.who(tok) or {}).get("no") == 行[0], auth.who(tok))
    文 = open(auth._文件(), encoding="utf-8").read()
    ck("会话文件里没有令牌原文(只有指纹)", tok not in 文 and auth._指纹(tok) in 文, "")
    ck("会话文件只有本人能读写(600)", (os.stat(auth._文件()).st_mode & 0o777) == 0o600, oct(os.stat(auth._文件()).st_mode))

    d = json.loads(文)
    d[auth._指纹(tok)]["at"] = (_dt.datetime.now() - _dt.timedelta(hours=auth.TTL_HOURS + 1)).isoformat()
    with open(auth._文件(), "w", encoding="utf-8") as f:
        json.dump(d, f)
    auth._SESS.clear()
    ck(f"落盘那份过了 {auth.TTL_HOURS} 小时,重启后不认", auth.who(tok) is None, auth.who(tok))

    tok2, _ = auth.login(行[1], "lanxiu@" + "2026")
    auth.logout(tok2)
    auth._SESS.clear()
    ck("退出登录之后,重启也不认", auth.who(tok2) is None, auth.who(tok2))

    print()
    if 坏:
        print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
        return 1
    print(f"{G}✅ 登录会话跨重启:重启后还认得、文件里只有指纹、过期不认、退出即失效(验了 {n} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
