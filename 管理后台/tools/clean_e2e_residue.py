#!/usr/bin/env python3
"""清正式项目里 e2e 测试的残留:吊销名字带 e2e 的访问密钥、归档名字带 e2e 的工作流(连同应用)。

用户 11-13 拍板「现在就清,并加自动收尾」,我给的选项原文:「只动名字带 e2e 的;清前列一份清单存档,清完核对数量」。
吊销**撤不回**,所以:

    python3 管理后台/tools/clean_e2e_residue.py                 # 只看:要动哪些、动完应该剩多少
    python3 管理后台/tools/clean_e2e_residue.py --执行          # 真做(要锁:./tools/gate_lock.sh)

**全走后台正规口**(吊销口 / 归档口),每一下都进审计、写理由 —— 不直接改库。
清单(密钥 id / 工作流 id)在动手前存到 ~/lanxiu-backups/,动完再查一遍数对不对。

**不动的**(不在授权里,只报数):名字不带 e2e 的密钥(比如同一份测试发的「没上生产那条的」)、
名字不带 e2e 的工作流、别的项目。挂着这类密钥的 e2e 工作流归档口会拒(还有没吊销的密钥)—— 照实报出来,不替人吊销。
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
库 = os.environ.get("DATABASE_URL_PSQL", f"postgresql://{os.environ.get('USER')}@localhost:5432/aimc_dev")
谁 = "U001"
理由 = "e2e 测试残留清理(用户 11-13 拍:只动名字带 e2e 的)"
P = f"/api/v1/projects/{项目}"


def 查(sql):
    r = subprocess.run(["psql", "-X", "-q", "-A", "-t", "-F", "\t", 库, "-c", sql], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"❌ 查库失败:{r.stderr.strip()[:200]}")
    return [ln.split("\t") for ln in r.stdout.splitlines() if ln.strip()]


def 打(路, 体):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/"), method="POST",
                                 data=json.dumps(体).encode())
    req.add_header("X-Dev-User", 谁)
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:  # noqa: BLE001
            return e.code, None


def 现状():
    钥 = 查(f"""select id, name from access_keys where project_id='{项目}' and name ilike '%e2e%'
               and revoked_at is null and archived_at is null order by created_at""")
    流 = 查(f"""select id, name from workflows where project_id='{项目}' and name ilike '%e2e%'
               and archived_at is null order by created_at""")
    别钥 = 查(f"""select count(*) from access_keys k join applications a on a.project_id=k.project_id and a.id=k.application_id
                 join workflows w on w.project_id=a.project_id and w.id=a.workflow_id
                where k.project_id='{项目}' and w.name ilike '%e2e%' and w.archived_at is null
                  and k.name not ilike '%e2e%' and k.revoked_at is null and k.archived_at is null""")[0][0]
    return 钥, 流, int(别钥)


def main():
    钥, 流, 别钥 = 现状()
    print(f"项目 {项目}:没吊销的 e2e 密钥 {len(钥)} 把 · 没归档的 e2e 工作流 {len(流)} 条")
    print(f"  不动:挂在 e2e 工作流上、名字不带 e2e 的没吊销密钥 {别钥} 把(挂着它的工作流归档会被拒)")
    if "--执行" not in sys.argv:
        print("(只看没动。真做加 --执行,先拿锁)")
        return 0
    os.makedirs(os.path.expanduser("~/lanxiu-backups"), exist_ok=True)
    存 = os.path.expanduser(f"~/lanxiu-backups/e2e残留清理-{datetime.datetime.now():%m%d%H%M}.json")
    json.dump({"密钥": 钥, "工作流": 流}, open(存, "w"), ensure_ascii=False, indent=1)
    print(f"清单已存 {存}")
    吊, 吊错 = 0, []
    for kid, _ in 钥:
        c, b = 打(P + f"/access-keys/{kid}/revoke", {"理由": 理由})
        if c == 200:
            吊 += 1
        else:
            吊错.append((kid, c, (b or {}).get("code")))
    归, 拒 = 0, {}
    for wid, _ in 流:
        c, b = 打(P + f"/workflows/{wid}/archive", {"理由": 理由})
        if c == 200:
            归 += 1
        else:
            拒.setdefault(f"{c} {(b or {}).get('code')}", []).append(wid)
    钥2, 流2, _ = 现状()
    print(f"吊销 {吊} 把(失败 {len(吊错)})· 归档 {归} 条 · 被拒 {sum(len(v) for v in 拒.values())} 条")
    for k, v in 拒.items():
        print(f"  被拒 {k}:{len(v)} 条(例 {v[0]})")
    for x in 吊错[:5]:
        print(f"  吊销失败 {x}")
    ok = len(钥2) == len(钥) - 吊 and len(流2) == len(流) - 归
    print(f"核数:剩 e2e 密钥 {len(钥2)}(应 {len(钥) - 吊})· 剩 e2e 工作流 {len(流2)}(应 {len(流) - 归})"
          + (" ✅ 对得上" if ok else " ❌ 对不上"))
    return 0 if ok and not 吊错 else 1


if __name__ == "__main__":
    sys.exit(main())
