#!/usr/bin/env python3
"""方言层 + schema 反射 —— 把「一个库长什么样」读成统一的对象。

## 为什么要有方言层

目标库是 MySQL,但本仓库自己的库是 SQLite。两件事都要能跑:
  · SQLite —— 唯一能在本机立刻跑通的真实靶子(59 张表),自测和演示靠它
  · MySQL  —— 真正的目标,读 information_schema

所以「怎么连、怎么读元信息、标识符怎么引号」全部收在这一层,
上面的推断/生成/校验一律只认 Schema 对象,不认数据库。

## 一个反直觉的事实:注释是**元信息里最值钱的那部分**

`account.phone` 是登录凭据还是联系方式? 类型都是 TEXT NOT NULL UNIQUE,分不出来。
但 DDL 里那行注释写着「**登录凭据**。着装人那个 phone 是**联系方式**,两件事,别合并」。
MySQL 有原生的 COLUMN_COMMENT;SQLite 没有,但 `sqlite_master.sql` 存的是**原始 DDL 文本**,
注释原样躺在里面 —— 所以这里对 SQLite 做了一次轻量 DDL 解析,把 `--` 注释挂回列上。

丢掉注释,后面那层就只能靠列名猜;留着注释,它能读懂业务。
"""
import os, re, sqlite3, sys

# ---------- 数据结构 ----------

class Column:
    def __init__(self, name, type_raw, nullable=True, pk=False, unique=False,
                 default=None, comment=""):
        self.name, self.type_raw = name, type_raw
        self.nullable, self.pk, self.unique = nullable, pk, unique
        self.default, self.comment = default, comment

    @property
    def kind(self):
        """把五花八门的类型名归成四类。生成器只认这四类,不认 BIGINT/DECIMAL/VARCHAR。"""
        t = (self.type_raw or "").upper()
        if any(k in t for k in ("INT",)):                       return "int"
        if any(k in t for k in ("REAL", "FLOA", "DOUB", "DEC", "NUMERIC")): return "real"
        if any(k in t for k in ("BLOB", "BINARY")):             return "blob"
        if any(k in t for k in ("DATE", "TIME")):               return "datetime"
        return "text"

    def __repr__(self): return f"<Col {self.name}:{self.type_raw}>"

class Table:
    def __init__(self, name):
        self.name = name
        self.columns = []           # [Column]
        self.pk = []                # 主键列名
        self.declared_fks = []      # [(本列, 目标表, 目标列)] —— 库里**明写**的外键
        self.rows = 0

    def col(self, name):
        for c in self.columns:
            if c.name == name: return c
        return None

    def __repr__(self): return f"<Table {self.name} x{len(self.columns)}>"

class Schema:
    def __init__(self, dialect, label):
        self.dialect, self.label = dialect, label
        self.tables = {}
    def __repr__(self): return f"<Schema {self.label} {len(self.tables)}表>"


# ---------- 连接:统一的最小接口 ----------

class Conn:
    """上层只用得到这几个方法。加一种数据库 = 在这里加一个子类。"""
    dialect = "?"
    def q(self, sql, params=()):  raise NotImplementedError   # 查,返回 list[tuple]
    def exec(self, sql, params=()): raise NotImplementedError # 写
    def many(self, sql, rows):    raise NotImplementedError   # 批量写
    def commit(self):  raise NotImplementedError
    def rollback(self): raise NotImplementedError
    def close(self):   raise NotImplementedError
    def ident(self, name):
        """标识符加引号。表名叫 `order` 这种保留字,不加引号会当场炸。"""
        return '"%s"' % name.replace('"', '""')
    ph = "?"          # 占位符
    def reflect(self): raise NotImplementedError


# ---------- SQLite ----------

_DDL_COL = re.compile(r"^\s*[\"`\[]?(\w+)[\"`\]]?\s+", re.M)

def _sqlite_comments(ddl):
    """从原始 DDL 里把注释挂回列上。

    认两种写法:列声明**本行行尾**的 `-- xxx`,以及列声明**上方连续几行**的 `-- xxx`。
    这是启发式,不求全对 —— 挂错一条注释的代价只是推断层多一句噪音,
    比完全没有注释小得多。
    """
    out, pending = {}, []
    body = ddl[ddl.find("(") + 1:] if "(" in ddl else ddl
    for line in body.splitlines():
        s = line.strip()
        if not s: continue
        if s.startswith("--"):
            pending.append(s.lstrip("-").strip()); continue
        code, _, trail = line.partition("--")
        m = _DDL_COL.match(code)
        if m:
            name = m.group(1)
            if name.upper() in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT", "KEY"):
                pending = []; continue
            parts = pending + ([trail.strip()] if trail.strip() else [])
            if parts: out[name] = " / ".join(parts)
        pending = []
    return out

class SqliteConn(Conn):
    dialect, ph = "sqlite", "?"
    def __init__(self, path):
        if not os.path.exists(path): raise SystemExit(f"库不存在: {path}")
        self.path = path
        self.c = sqlite3.connect(path)
        self.label = os.path.basename(path)
    def q(self, sql, params=()):    return list(self.c.execute(sql, params))
    def exec(self, sql, params=()): return self.c.execute(sql, params)
    def many(self, sql, rows):      return self.c.executemany(sql, rows)
    def commit(self):   self.c.commit()
    def rollback(self): self.c.rollback()
    def close(self):    self.c.close()

    def reflect(self):
        sc = Schema("sqlite", self.label)
        rows = self.q("select name, sql from sqlite_master where type='table' "
                      "and name not like 'sqlite_%' order by name")
        for name, ddl in rows:
            t = Table(name)
            comments = _sqlite_comments(ddl or "")
            for _cid, cname, ctype, notnull, dflt, pk in self.q(f"PRAGMA table_info({self.ident(name)})"):
                t.columns.append(Column(cname, ctype, nullable=not notnull, pk=bool(pk),
                                        default=dflt, comment=comments.get(cname, "")))
                if pk: t.pk.append(cname)
            # 唯一约束:PRAGMA index_list 里 unique=1 且只含一列的
            for _s, idx, uniq, *_r in self.q(f"PRAGMA index_list({self.ident(name)})"):
                if not uniq: continue
                cols = [r[2] for r in self.q(f"PRAGMA index_info({self.ident(idx)})")]
                if len(cols) == 1 and t.col(cols[0]): t.col(cols[0]).unique = True
            for fk in self.q(f"PRAGMA foreign_key_list({self.ident(name)})"):
                t.declared_fks.append((fk[3], fk[2], fk[4] or "id"))
            t.rows = self.q(f"select count(*) from {self.ident(name)}")[0][0]
            sc.tables[name] = t
        return sc


# ---------- MySQL ----------

class MysqlConn(Conn):
    """驱动**懒加载**。

    这个仓库的铁律是「无第三方依赖,纯 Python 标准库」,而标准库连不了 MySQL。
    折中办法:只有真的指定了 MySQL 目标才 import pymysql。
    于是 check.sh / 自测 / SQLite 那条路完全不受影响,依赖没被引进主干。
    """
    dialect, ph = "mysql", "%s"
    def __init__(self, dsn):
        try:
            import pymysql
        except ImportError:
            raise SystemExit("要连 MySQL 需要 pymysql:  pip3 install pymysql\n"
                             "(它是可选依赖,只在指定 mysql:// 目标时才用到)")
        u = _parse_dsn(dsn)
        self.db = u["db"]; self.label = f'{u["host"]}/{u["db"]}'
        self.c = pymysql.connect(host=u["host"], port=u["port"], user=u["user"],
                                 password=u["pwd"], database=u["db"], charset="utf8mb4")
    def ident(self, name): return "`%s`" % name.replace("`", "``")
    def q(self, sql, params=()):
        cur = self.c.cursor(); cur.execute(sql, params); r = cur.fetchall(); cur.close(); return list(r)
    def exec(self, sql, params=()):
        cur = self.c.cursor(); cur.execute(sql, params); cur.close()
    def many(self, sql, rows):
        # sqlite3 的**连接**对象自带 executemany,pymysql 的没有 —— 那是**游标**的方法。
        # 灌入层原来直接写 `conn.c.executemany(...)`,在 SQLite 上跑得好好的,
        # 到 MySQL 上第一条 INSERT 就 AttributeError。
        # 这类差异不会在类型检查里暴露,也不会在只有一种数据库的测试里暴露。
        cur = self.c.cursor(); cur.executemany(sql, rows); cur.close()
    def commit(self):   self.c.commit()
    def rollback(self): self.c.rollback()
    def close(self):    self.c.close()

    def reflect(self):
        sc = Schema("mysql", self.label)
        cols = self.q(
            "select table_name, column_name, column_type, is_nullable, column_key, "
            "column_default, column_comment from information_schema.columns "
            "where table_schema=%s order by table_name, ordinal_position", (self.db,))
        for tname, cname, ctype, nullable, key, dflt, comment in cols:
            t = sc.tables.setdefault(tname, Table(tname))
            c = Column(cname, ctype, nullable=(nullable == "YES"), pk=(key == "PRI"),
                       unique=(key in ("PRI", "UNI")), default=dflt, comment=comment or "")
            t.columns.append(c)
            if c.pk: t.pk.append(cname)
        for tname, cname, rt, rc in self.q(
            "select table_name, column_name, referenced_table_name, referenced_column_name "
            "from information_schema.key_column_usage "
            "where table_schema=%s and referenced_table_name is not null", (self.db,)):
            if tname in sc.tables: sc.tables[tname].declared_fks.append((cname, rt, rc))
        # 行数**必须**逐表 count(*),不能用 information_schema.tables.table_rows。
        # 那个值对 InnoDB 是**估算**:小表上经常是 0,大表上能差几倍。
        # 而行数在这里不是展示用的 —— 推断层拿它算「去重值占比」来判枚举、
        # 拿它定可信度,方案层拿它按 scale 算要造多少。估算值会让这三件事同时歪掉。
        # 代价是每张表一次 count(*),大表上不便宜。**准确性优先,慢了再优化。**
        for tname in sc.tables:
            try:
                sc.tables[tname].rows = self.q(
                    f"select count(*) from {self.ident(tname)}")[0][0]
            except Exception:
                sc.tables[tname].rows = 0
        return sc


def _parse_dsn(dsn):
    m = re.match(r"mysql://(?:([^:@/]+)(?::([^@/]*))?@)?([^:/]+)(?::(\d+))?/(\w+)", dsn)
    if not m: raise SystemExit("MySQL 目标写法: mysql://user:pass@host:3306/dbname")
    return {"user": m.group(1) or "root", "pwd": m.group(2) or "",
            "host": m.group(3), "port": int(m.group(4) or 3306), "db": m.group(5)}


def connect(target):
    """统一入口。`xxx.db` / `sqlite://路径` 走 SQLite,`mysql://...` 走 MySQL。"""
    if target.startswith("mysql://"): return MysqlConn(target)
    if target.startswith("sqlite://"): return SqliteConn(target[len("sqlite://"):])
    return SqliteConn(target)


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "lanxiu.db")
    c = connect(tgt); sc = c.reflect()
    print(f"{sc.label}: {len(sc.tables)} 张表 / "
          f"{sum(len(t.columns) for t in sc.tables.values())} 列 / "
          f"{sum(len(t.declared_fks) for t in sc.tables.values())} 个**明写**的外键")
    withc = [t for t in sc.tables.values() if any(c.comment for c in t.columns)]
    print(f"带注释的表: {len(withc)} 张 —— 注释是推断层最值钱的输入")
