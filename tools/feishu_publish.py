#!/usr/bin/env python3
"""把本地 Markdown 导入飞书云文档,并直接落到指定文件夹。

用法: python3 feishu_publish.py <file.md> [file2.md ...]

凭证:首次跑会弹一次浏览器授权,之后靠 refresh_token 静默续期,不再需要点击。
      缓存写在本脚本同目录的 .uat_cache.json(600 权限)。
"""
import json, os, subprocess, sys, threading, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

# 应用凭证:**绝不写在代码里** —— 代码要进 git,密钥进了 git 历史就洗不掉。
# 找的顺序:环境变量 → 同目录的 .feishu_app.json(已 gitignore)。
# 凭证放在两个项目之外 —— 本项目和「帕鲁打工仔」是两个独立项目,
# 不共用脚本、不共用凭证缓存、不共用飞书文件夹。
_CRED_DIR = os.environ.get("FEISHU_CRED_DIR", os.path.expanduser("~/.feishu-publish"))
_APP_FILE = os.path.join(_CRED_DIR, ".feishu_app.json")

def _load_app():
    aid = os.environ.get("FEISHU_APP_ID")
    sec = os.environ.get("FEISHU_APP_SECRET")
    if aid and sec:
        return aid, sec
    try:
        with open(_APP_FILE) as f:
            d = json.load(f)
        return d["app_id"], d["app_secret"]
    except Exception:
        sys.exit(
            "缺少飞书应用凭证。二选一:\n"
            "  1) export FEISHU_APP_ID=... FEISHU_APP_SECRET=...\n"
            f"  2) 写入 {_APP_FILE}: {{\"app_id\": \"...\", \"app_secret\": \"...\"}}"
        )

APP_ID, APP_SECRET = _load_app()
REDIRECT = "http://localhost:3000/callback"

# 本项目自己的飞书文件夹。默认文件夹是「帕鲁打工仔」在用的,不往那发。
FOLDER = os.environ.get("FEISHU_FOLDER", "QexpfF7ejlotM8db6JEcZH5tnZf")
# offline_access 才会下发 refresh_token。
# ⚠️ **多要一个没批准的权限,整次授权会失败** —— 所以默认只要发布用得上的那几个,
# 需要额外权限时用环境变量临时加,不改默认值:
#     FEISHU_SCOPE="$(python3 -c 'import tools.feishu_publish as p;print(p.SCOPE)') board:whiteboard:node:read board:whiteboard:node:create" \
#     python3 tools/feishu_publish.py --reauth
SCOPE = os.environ.get(
    "FEISHU_SCOPE", "drive:drive docx:document offline_access")
TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
CACHE = os.path.join(_CRED_DIR, ".uat_cache.json")

box, done = {}, threading.Event()


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path)
        if q.path != "/callback":
            self.send_response(404); self.end_headers(); return
        p = urllib.parse.parse_qs(q.query)
        box["code"] = (p.get("code") or [None])[0]
        box["err"] = (p.get("error_description") or p.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(("<h2>%s</h2><p>可以关闭本页。</p>" % (
            "授权成功 ✅" if box["code"] else "授权失败 ❌ " + str(box["err"]))).encode())
        done.set()

    def log_message(self, *a):
        pass


def post(url, payload, token=None):
    # 本机有 TLS 拦截代理,Python 证书链校验会失败;curl 走系统钥匙串,正常。
    cmd = ["curl", "-s", "-X", "POST", url,
           "-H", "Content-Type: application/json; charset=utf-8",
           "-d", json.dumps(payload, ensure_ascii=False)]
    if token:
        cmd += ["-H", "Authorization: Bearer " + token]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out[:400]}


def get(url, token):
    out = subprocess.run(["curl", "-s", url, "-H", "Authorization: Bearer " + token],
                         capture_output=True, text=True, timeout=60).stdout
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out[:400]}


def save_tokens(d):
    json.dump({"access_token": d.get("access_token"),
               "refresh_token": d.get("refresh_token")}, open(CACHE, "w"))
    os.chmod(CACHE, 0o600)


def token_alive(t):
    # 飞书失效 token 也返 HTTP 200,必须看 body 里的 code 字段
    r = get("https://open.feishu.cn/open-apis/authen/v1/user_info", t)
    return r.get("code") == 0


def acquire_token(force=False):
    """force=True 时忽略缓存,重新走一次浏览器授权。

    ⚠️ 加了新权限**必须重来一次** —— 缓存里那个 token 是按**旧 scope** 签发的,
    它不会因为后台加了权限就自动变强。而「token 还能用」和「token 有新权限」
    在调用失败之前长得一模一样。
    """
    if force:
        try: os.remove(CACHE)
        except FileNotFoundError: pass

    if os.path.exists(CACHE):
        try:
            store = json.load(open(CACHE))
        except (json.JSONDecodeError, OSError):
            store = {}
        at, rt = store.get("access_token"), store.get("refresh_token")
        if at and token_alive(at):
            print("使用缓存 token")
            return at
        if rt:
            r = post(TOKEN_URL, {"grant_type": "refresh_token", "client_id": APP_ID,
                                 "client_secret": APP_SECRET, "refresh_token": rt})
            if r.get("access_token"):
                save_tokens(r)
                print("access_token 已过期,refresh_token 静默续期成功")
                return r["access_token"]
            print("refresh 失败:", r.get("error_description") or r.get("msg"))

    srv = HTTPServer(("127.0.0.1", 3000), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    auth = "https://accounts.feishu.cn/open-apis/authen/v1/authorize?" + urllib.parse.urlencode(
        {"client_id": APP_ID, "redirect_uri": REDIRECT, "scope": SCOPE, "state": "publish"})
    print("AUTH_URL:", auth, flush=True)
    webbrowser.open(auth)
    if not done.wait(timeout=300):
        srv.shutdown(); sys.exit("等待授权超时")
    srv.shutdown()
    if not box.get("code"):
        sys.exit("授权失败: " + str(box.get("err")))
    tok = post(TOKEN_URL, {"grant_type": "authorization_code", "client_id": APP_ID,
                           "client_secret": APP_SECRET, "code": box["code"],
                           "redirect_uri": REDIRECT})
    if not tok.get("access_token"):
        sys.exit("换 token 失败: " + json.dumps(tok, ensure_ascii=False)[:300])
    save_tokens(tok)
    print("refresh_token:", "已获取,以后不用再点授权" if tok.get("refresh_token")
          else "⚠️ 未下发 —— 检查应用是否勾选了 offline_access")
    return tok["access_token"]


def prune_same_name(name, keep_token, uat):
    """删掉文件夹里同名的旧文档。

    飞书的导入接口**每次都新建文档,没有覆盖选项** —— 同一份文件发布 N 次
    就会堆 N 份同名文档。这里在导入成功后清理掉除最新之外的同名件。
    删除进回收站,30 天内可恢复。
    """
    r = get("https://open.feishu.cn/open-apis/drive/v1/files"
            f"?folder_token={FOLDER}&page_size=200", uat)
    files = (r.get("data") or {}).get("files") or []
    stale = [f for f in files if f.get("name") == name and f.get("token") != keep_token]
    for f in stale:
        out = subprocess.run(
            ["curl", "-s", "-X", "DELETE",
             f"https://open.feishu.cn/open-apis/drive/v1/files/{f['token']}?type=docx",
             "-H", "Authorization: Bearer " + uat],
            capture_output=True, text=True, timeout=60).stdout
        try:
            ok = json.loads(out).get("code") == 0
        except json.JSONDecodeError:
            ok = False
        if not ok:
            print(f"    (清理旧版失败: {f['token']})")
    if stale:
        print(f"    已清理 {len(stale)} 份同名旧文档")


def publish(path, uat):
    base = os.path.basename(path)                 # 上传名必须带 .md 后缀
    name = os.path.splitext(base)[0][:27]         # 文档标题上限 27 字
    size = os.path.getsize(path)

    # 1) 上传素材。ccm_import_open 必须带 extra,否则 1061004 forbidden
    up = subprocess.run([
        "curl", "-s", "-X", "POST",
        "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
        "-H", "Authorization: Bearer " + uat,
        "-F", f"file_name={base}",
        "-F", "parent_type=ccm_import_open",
        "-F", f"parent_node={FOLDER}",
        "-F", f"size={size}",
        "-F", 'extra={"obj_type":"docx","file_extension":"md"}',
        "-F", f"file=@{path}",
    ], capture_output=True, text=True, timeout=300).stdout
    try:
        ftok = (json.loads(up).get("data") or {}).get("file_token")
    except json.JSONDecodeError:
        ftok = None
    if not ftok:
        print(f"UPLOAD_FAILED {base}: {up[:300]}"); return False

    # 2) 建导入任务。point 直接指定目标文件夹 —— 无需事后移动
    task = post("https://open.feishu.cn/open-apis/drive/v1/import_tasks", {
        "file_extension": "md", "file_token": ftok, "type": "docx",
        "file_name": name, "point": {"mount_type": 1, "mount_key": FOLDER},
    }, token=uat)
    ticket = (task.get("data") or {}).get("ticket")
    if not ticket:
        print(f"TASK_FAILED {base}: {json.dumps(task, ensure_ascii=False)[:300]}"); return False

    # 3) 轮询(job_status 0 = 成功,1/2 = 处理中)
    for _ in range(30):
        r = get(f"https://open.feishu.cn/open-apis/drive/v1/import_tasks/{ticket}", uat)
        res = (r.get("data") or {}).get("result") or {}
        st = res.get("job_status")
        if st == 0:
            print(f"OK  {name}\n    {res.get('url')}")
            prune_same_name(name, res.get("token"), uat)
            return True
        if st not in (1, 2, None):
            print(f"IMPORT_FAILED {base}: status={st} {res.get('job_error_msg')}"); return False
        subprocess.run(["sleep", "2"])
    print(f"TIMEOUT {base}: ticket={ticket}"); return False


def main():
    if "--reauth" in sys.argv:
        print("重新授权(会弹浏览器)。当前请求的权限:\n  " + SCOPE.replace(" ", "\n  "))
        t = acquire_token(force=True)
        print("\n✅ 拿到新 token。" if t else "\n❌ 没拿到")
        return 0

    files = [f for f in sys.argv[1:] if f.endswith(".md")]
    if not files:
        sys.exit("用法: feishu_publish.py <file.md> ...")
    uat = acquire_token()
    ok = sum(publish(f, uat) for f in files)
    sys.exit(0 if ok == len(files) else 1)


if __name__ == "__main__":
    main()
