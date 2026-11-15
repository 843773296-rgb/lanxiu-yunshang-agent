"""第 2 条:交付告知表加「已告知」四列(2026-11-15,用户拍标品交付告知三条)。

用户定的:「发」= 记一笔「已告知」(告知了哪几条、谁、什么渠道、什么时候),**「告知过」不等于「顾客签了」** ——
签收照旧在 signed_at,售后判责读的还是签收。所以加四列,不复用 signed_at / items:
  notified_at       告知的时刻(世界的钟 —— 是演示世界里发生的事,跟着平移)
  notified_by       谁告知的(工号)
  notified_channel  走的什么渠道(微信 / 电话 / 短信 / 当面 / 小程序)
  notified_items    告知了哪几条(JSON:六条里的编号)

幂等:先读 PRAGMA,缺哪列加哪列;表不在就跳过(建表归 seed.py)。
"""
COLS = (("notified_at", "TEXT"), ("notified_by", "TEXT"), ("notified_channel", "TEXT"), ("notified_items", "TEXT"))


def up(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delivery_notice'").fetchone():
        return
    有 = {r[1] for r in c.execute("PRAGMA table_info(delivery_notice)")}
    for 列, 型 in COLS:
        if 列 not in 有:
            c.execute(f"ALTER TABLE delivery_notice ADD COLUMN {列} {型}")
