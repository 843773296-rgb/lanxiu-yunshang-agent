"""每日备份:业务库(SQLite)+ 管理后台库(PG)+ 上传件 / 录音。(2026-11-12,执行手册 W03,台账第三条)

用户拍的是「云盘一份 + 本机一份」,**云盘位置还没给** —— 这里先做本机那一份,去处做成参数:
    python3 tools/backup.py                 # 备份到 $LANXIU_BACKUP_DEST(默认 ~/lanxiu-backups)
    python3 tools/backup.py --演练          # 取最新一份,恢复到临时目录,验完整性 + 关键表行数
    python3 tools/backup.py --留几份 3

⚠️ 这台机器的盘 11-12 只剩约 12 GiB(99% 已用)。所以:
  · 一律压缩(SQLite 在线备份后 gzip;PG 用 pg_dump -Fc 自带压缩);
  · 本机默认只留 3 份;
  · **商品图(5.4 GB)不进本机备份** —— 放不下,而且和原件在同一块盘上不算灾备。等云盘位置给了再加。
  · 备份前先看剩余空间,不够就拒跑并说清楚 —— 写到一半撑满盘,连业务库都写不进了。

做法要点(每一条都对应一个踩过的坑):
  · SQLite 用 `sqlite3` 的在线备份接口,不用 cp —— `backend/lanxiu.db` 在别的检出里是软链,cp -R 拷出来的是链(CLAUDE.md 7.5.5);
    在线备份对正在写的库也安全(拿读锁一页页拷)。
  · 备份完**立刻打开验 integrity_check** —— 「写了一个文件」和「那是一份能用的库」是两件事。
  · 演练比的是「关键表行数 ≥ 备份时记下的行数」,不和现在的真库比(真库一直在变)。
"""
import datetime
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
业务库 = os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db"))
跟着备的目录 = ["backend/uploads", "backend/录音"]
关键表 = ["customer", "account", "ordr", "ordr_item", "appointment", "measure_rec", "rating", "op_log"]
PG库 = os.environ.get("LANXIU_PG_DB", "aimc_dev")
最少剩余GB = 2.0


def 去处():
    return os.path.expanduser(os.environ.get("LANXIU_BACKUP_DEST") or "~/lanxiu-backups")


def 剩余GB(路径):
    os.makedirs(路径, exist_ok=True)
    return shutil.disk_usage(路径).free / 1024 ** 3


def 行数(库):
    with closing(sqlite3.connect(f"file:{库}?mode=ro", uri=True)) as c:
        有 = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        return {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in 关键表 if t in 有}


def 备份():
    根 = 去处()
    剩 = 剩余GB(根)
    if 剩 < 最少剩余GB:
        print(f"❌ 备份去处 {根} 只剩 {剩:.1f} GiB(要至少 {最少剩余GB} GiB)—— 拒跑。"
              f"写到一半撑满盘的话,业务库也写不进了。先清盘或换去处(LANXIU_BACKUP_DEST)。")
        return 2
    戳 = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    目 = os.path.join(根, 戳)
    os.makedirs(目, exist_ok=True)
    记 = {"时间": 戳, "来源": 业务库, "剩余空间GB_备份前": round(剩, 1)}

    # ① 业务库:在线备份 → 验完整性 → 记行数 → gzip
    临 = os.path.join(目, "lanxiu.db")
    with closing(sqlite3.connect(f"file:{业务库}?mode=ro", uri=True)) as 源, closing(sqlite3.connect(临)) as 目库:
        源.backup(目库)
    with closing(sqlite3.connect(临)) as c:
        完整 = c.execute("pragma integrity_check").fetchone()[0]
    if 完整 != "ok":
        print(f"❌ 备份出来的业务库没过完整性检查:{完整[:200]} —— 这一份不算数")
        return 1
    记["业务库行数"] = 行数(临)
    with open(临, "rb") as f, gzip.open(临 + ".gz", "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    os.remove(临)
    记["业务库大小MB"] = round(os.path.getsize(临 + ".gz") / 1024 ** 2, 1)

    # ② 管理后台库
    pg = shutil.which("pg_dump")
    if pg:
        r = subprocess.run([pg, "-Fc", "-f", os.path.join(目, f"{PG库}.dump"), PG库], capture_output=True, text=True)
        记["管理后台库"] = "ok" if r.returncode == 0 else f"失败:{r.stderr[:200]}"
        if r.returncode == 0:
            记["管理后台库大小MB"] = round(os.path.getsize(os.path.join(目, f"{PG库}.dump")) / 1024 ** 2, 1)
    else:
        记["管理后台库"] = "没装 pg_dump —— 这一份不含管理后台库"

    # ③ 上传件 / 录音(小;商品图不进,见文件头)
    for 相对 in 跟着备的目录:
        src = os.path.join(ROOT, 相对)
        if os.path.isdir(src):
            shutil.make_archive(os.path.join(目, 相对.replace("/", "_")), "gztar", src)
    记["没备的"] = "商品图备份/(5.4 GB,本机放不下,等云盘位置)"
    json.dump(记, open(os.path.join(目, "清单.json"), "w"), ensure_ascii=False, indent=1)

    # ④ 只留最近 N 份
    留 = int(_参数("--留几份", 3))
    份们 = sorted(d for d in os.listdir(根) if os.path.isdir(os.path.join(根, d)) and d[:8].isdigit())
    for 旧 in 份们[:-留]:
        shutil.rmtree(os.path.join(根, 旧))
    print(f"✅ 备份完成:{目}")
    print(f"   业务库 {记['业务库大小MB']} MB(完整性 ok,{sum(记['业务库行数'].values())} 行关键数据)· 管理后台库 {记.get('管理后台库')}"
          f" · 留 {min(len(份们), 留)} 份 · 去处剩余 {剩余GB(根):.1f} GiB")
    return 0


def 演练():
    根 = 去处()
    份们 = sorted(d for d in os.listdir(根) if os.path.isdir(os.path.join(根, d)) and d[:8].isdigit()) if os.path.isdir(根) else []
    if not 份们:
        print(f"❌ {根} 下一份备份都没有 —— **这不叫演练通过**")
        return 1
    目 = os.path.join(根, 份们[-1])
    记 = json.load(open(os.path.join(目, "清单.json")))
    with tempfile.TemporaryDirectory() as 临:
        库 = os.path.join(临, "lanxiu.db")
        with gzip.open(os.path.join(目, "lanxiu.db.gz"), "rb") as g, open(库, "wb") as f:
            shutil.copyfileobj(g, f)
        with closing(sqlite3.connect(库)) as c:
            完整 = c.execute("pragma integrity_check").fetchone()[0]
        现 = 行数(库)
        少了 = {t: (记["业务库行数"].get(t), 现.get(t)) for t in 记["业务库行数"] if 现.get(t, -1) < 记["业务库行数"][t]}
        pg_ok = None
        dump = os.path.join(目, f"{PG库}.dump")
        if os.path.exists(dump) and shutil.which("pg_restore"):
            r = subprocess.run(["pg_restore", "--list", dump], capture_output=True, text=True)
            pg_ok = r.returncode == 0 and "TABLE DATA" in r.stdout
    ok = 完整 == "ok" and not 少了 and pg_ok is not False
    print(f"{'✅' if ok else '❌'} 恢复演练({份们[-1]}):业务库完整性 {完整} · 关键表行数{'一致' if not 少了 else f'少了 {少了}'}"
          f" · 管理后台库 {'能读出表数据' if pg_ok else ('读不出' if pg_ok is False else '这一份没有')}")
    return 0 if ok else 1


def _参数(名, 默认):
    return sys.argv[sys.argv.index(名) + 1] if 名 in sys.argv else 默认


if __name__ == "__main__":
    sys.exit(演练() if "--演练" in sys.argv else 备份())
