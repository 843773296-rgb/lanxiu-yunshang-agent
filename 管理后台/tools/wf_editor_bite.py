"""流程图编辑器那两份测试的咬合重放(根目录的 tools/bite_run 只认 check.sh 里的命令,管理后台的 node 测试不在那里)。

在**临时副本**里逐条把被守的那段改坏,三关:对照先绿 → 改坏后红 → 红的是指定那一条。工作区一个字不动。
  cd 管理后台 && python3 tools/wf_editor_bite.py      (或 make bite-editor)
"""
import os, shutil, subprocess, tempfile, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
规格 = [
 ("tests/e2e/test_workflow_graph_logic.js", "apps/web/wf_graph.js",
  "    if (走得到(表, 目标id, 源id))", "    if (false)", "会形成环 → 拒"),
 ("tests/e2e/test_workflow_graph_logic.js", "apps/web/wf_graph.js",
  "    if (要删.length === 1 && !敏感.length) {", "    if (要删.length === 1) {", "T07 人工核对是敏感步骤"),
 ("tests/e2e/test_workflow_graph_logic.js", "apps/web/wf_graph.js",
  "        else { 外部引用.push({ 节点id: 新id, 路径: 路, 仍引用: v.node_id }); if (外部处理) 外部处理(v); }", "        else { v.node_id = null; 外部引用.push({ 节点id: 新id, 路径: 路, 仍引用: null }); }", "外部引用不悄悄换"),
 ("tests/e2e/test_workflow_graph_logic.js", "apps/web/wf_graph.js",
  "        else { 外部引用.push({ 节点id: 新id, 路径: 路, 仍引用: v.node_id }); if (外部处理) 外部处理(v); }", "        else { 外部引用.push({ 节点id: 新id, 路径: 路, 仍引用: v.node_id }); }", "导入的引用**没有**挂到它上面"),
 ("tests/e2e/test_workflow_editor_actions.js", "apps/web/app.js",
  "    改图(`换业务动作为「${新t[\"名\"]}」`, () => { c.tool_version_id = id; 要删.forEach((k) => { delete c.bindings[k]; }); });", "    改图(`换业务动作为「${新t[\"名\"]}」`, () => { c.tool_version_id = id; });", "新的不要的去掉(内容)"),
 ("tests/e2e/test_workflow_graph_logic.js", "apps/web/wf_graph.js",
  "    (定义.edges || []).forEach((e) => { if (e.source === 节点id && e.port === \"branch\" && e.branch_key === 旧) e.branch_key = 新; });", "", "T09 改分支名"),
 ("tests/e2e/test_workflow_editor_actions.js", "apps/web/app.js",
  "      g.脏 = (g.编辑序号 || 0) !== 序;", "      g.脏 = false;", "保存期间又改了"),
 ("tests/e2e/test_workflow_editor_actions.js", "apps/web/app.js",
  "  if (图态.存中) {", "  if (false) {", "保存中再点保存 → 不并发"),
 ("tests/e2e/test_workflow_editor_actions.js", "apps/web/app.js",
  "const 检查过期 = () => !!(图态.报告 && 图态.报告定义 !== JSON.stringify(图态.定义));", "const 检查过期 = () => false;", "改了连线 → 「配置已修改"),
]
坏 = 0
for 测, 文件, 旧, 新, 预期 in 规格:
    t = tempfile.mkdtemp(prefix="wfbite-")
    for d in ("apps/web", "tests/e2e"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(t, d))
    p = os.path.join(t, 文件); s = open(p, encoding="utf-8").read()
    对照 = subprocess.run(["node", 测], cwd=t, capture_output=True, text=True).returncode
    if s.count(旧) != 1: print(f"  ❌ 破坏点找不到/不唯一:{旧[:50]}"); 坏 += 1; continue
    open(p, "w", encoding="utf-8").write(s.replace(旧, 新))
    r = subprocess.run(["node", 测], cwd=t, capture_output=True, text=True)
    红行 = [l for l in r.stdout.splitlines() if l.strip().startswith("❌")]
    中 = any(预期 in l for l in 红行)
    ok = 对照 == 0 and r.returncode != 0 and 中
    坏 += not ok
    print(f"  {'✅' if ok else '❌'} 改坏「{旧.strip()[:40]}…」→ {'红在「' + 预期 + '」' if 中 else '没红在指定那条:' + str(红行[:2])}(对照退出码 {对照})")
    shutil.rmtree(t, ignore_errors=True)
print(f"{'❌' if 坏 else '✅'} {len(规格) - 坏}/{len(规格)} 条咬合三关全过")
sys.exit(1 if 坏 else 0)
