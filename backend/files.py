# -*- coding: utf-8 -*-
"""任务附件:派单时的图和总结时的图。

**两类图不是同一件事**,所以用 kind 分开存:
    派单 —— 店长或客户给的现场照、参考图,是「要做什么」的证据
    总结 —— 顾问做完拍的,是「做成什么样」的证据
合成一类的话,一张图到底是要求还是结果,就只能靠上传时间猜 ——
而任务改过期、图补传过,时间顺序立刻不作数。

存盘不存库:图片进 backend/uploads/,库里只留元数据和路径。
**别把图片塞进数据库** —— 几十兆的 BLOB 会让每一次 SELECT * 都变慢,
而这个库里到处是 SELECT *。
"""
import os, sqlite3, base64, hashlib, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
ROOT = os.path.join(HERE, "uploads")

# 只收图片。收 pdf/doc 不是不行,但**能被浏览器直接打开的类型才安全展示**,
# 其余的一律要先下载再打开,那是另一套交互,现在不做。
OK_MIME = {"image/png": ".png", "image/jpeg": ".jpg",
           "image/webp": ".webp", "image/gif": ".gif"}
MAX_BYTES = 5 * 1024 * 1024        # 单张 5MB —— 手机直出的照片大多在 2–4MB
MAX_PER_TASK = 6                   # 一个任务一类附件最多 6 张
KINDS = ("派单", "总结")


def _rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def save(schedule_id, kind, name, data_url, actor):
    """存一张图。data_url 形如 `data:image/png;base64,xxxx`。

    返回 (ok, 说明)。每一条拒绝都要说清楚**拒的是什么**——
    「上传失败」这四个字会让人反复重试同一张超大的图。
    """
    if kind not in KINDS:
        return False, f"附件类型只能是 {KINDS},收到「{kind}」"
    if not _rows("SELECT id FROM schedule WHERE id=?", schedule_id):
        return False, f"没有任务 {schedule_id}"
    n = _rows("SELECT COUNT(*) c FROM schedule_file WHERE schedule_id=? AND kind=?",
              schedule_id, kind)[0]["c"]
    if n >= MAX_PER_TASK:
        return False, f"这个任务的「{kind}」附件已经有 {n} 张,最多 {MAX_PER_TASK} 张"

    m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", (data_url or "").strip(), re.S)
    if not m:
        return False, "附件格式不对(需要 data:<mime>;base64, 开头)"
    mime = m.group(1).lower()
    if mime not in OK_MIME:
        return False, f"只收图片({'、'.join(sorted(OK_MIME))}),收到「{mime}」"
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception:
        return False, "附件内容不是合法的 base64"
    if len(raw) > MAX_BYTES:
        return False, f"这张 {len(raw)/1024/1024:.1f}MB,超过单张 {MAX_BYTES//1024//1024}MB 上限"
    if not raw:
        return False, "附件是空的"

    d = os.path.join(ROOT, schedule_id)
    os.makedirs(d, exist_ok=True)
    # 文件名用内容哈希 —— 同一张图重复上传不会占两份,
    # 也避免用户的原始文件名带路径分隔符跑出目录。
    h = hashlib.sha256(raw).hexdigest()[:24]
    fn = h + OK_MIME[mime]
    with open(os.path.join(d, fn), "wb") as f:
        f.write(raw)
    rel = os.path.join(schedule_id, fn)
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO schedule_file(schedule_id,kind,name,mime,size,path,"
                  "uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?,?)",
                  (schedule_id, kind, (name or fn)[:80], mime, len(raw), rel, actor,
                   datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return True, f"已存「{kind}」附件({len(raw)//1024}KB)"


def listing(schedule_id, kind=None):
    sql = "SELECT id,kind,name,mime,size,uploaded_by,uploaded_at FROM schedule_file WHERE schedule_id=?"
    a = [schedule_id]
    if kind: sql += " AND kind=?"; a.append(kind)
    return _rows(sql + " ORDER BY id", *a)


def blob(file_id):
    """取一张图的字节。返回 (mime, bytes) 或 None。"""
    r = _rows("SELECT mime,path FROM schedule_file WHERE id=?", file_id)
    if not r: return None
    p = os.path.join(ROOT, r[0]["path"])
    # 存的是相对路径,但**读之前还要确认它真的在 uploads 底下** ——
    # 库里的值将来可能被别的写入路径污染,而这里一旦被穿越就是任意文件读取。
    p = os.path.abspath(p)
    if not p.startswith(os.path.abspath(ROOT) + os.sep) or not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return r[0]["mime"], f.read()
