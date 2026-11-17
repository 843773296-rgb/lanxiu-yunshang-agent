"""第 3 条:员工表加「首次登录要改密」标记(2026-11-17,执行手册 W19;auth.py 文件头写着「真上线要加首次登录强制改密」)。

  must_change_pwd  INTEGER NOT NULL DEFAULT 0 —— 1 = 下次登录成功后只能改密,改完归 0

为什么默认 0、不给现有 39 名演示员工置位:登录是几十条检查和两个端到端套的前提(auth.login 直接调、/api/login 打),
全员置位等于把它们全部拦在「先改密」上;演示口令本来就是公开的。置位的时机是**开通 / 重置口令**那两个写口
(server.reset_staff_pwd),真上线前要全员置位就跑一句 UPDATE staff SET must_change_pwd=1 —— 那是上线动作,不是迁移的事。

幂等:先读 PRAGMA,缺才加;表不在就跳过(建表归 seed.py / ensure_tables)。
"""


def up(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='staff'").fetchone():
        return
    有 = {r[1] for r in c.execute("PRAGMA table_info(staff)")}
    if "must_change_pwd" not in 有:
        c.execute("ALTER TABLE staff ADD COLUMN must_change_pwd INTEGER NOT NULL DEFAULT 0")
