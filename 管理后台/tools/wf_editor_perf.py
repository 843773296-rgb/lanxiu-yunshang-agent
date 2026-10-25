"""流程图编辑器的性能量测(交互控件设计 §13:「建议用 20、100 个节点及分支密集图验证连续拖动、点击选线、字段输入和保存」)。

**这是量测,不是判据**:只打印数,不判红绿 —— 机器不同数不同,拿一台开发机的数当门槛会变成随机拦路。
用的是测试专用工作流「编辑器验收(自动测试)」(和 test_workflow_editor_browser 同一条),量完把草稿恢复成那份测试夹具。
  cd 管理后台 && ./.venv/bin/python tools/wf_editor_perf.py
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "e2e"))
import test_workflow_editor_browser as T   # noqa: E402  复用它的接口小工具和夹具


def 造图(n):
    """n 步:开始 → 一串 AI 处理,每 5 步插一个条件分出两路再汇到下一步(分支密集)。"""
    nodes = [{"id": "start", "type": "start", "name": "开始", "config": {"input_schema": {"type": "object", "properties": {}, "required": []}}}]
    edges, 布 = [], {"start": {"x": 40, "y": 200}}
    前 = "start"
    for i in range(1, n - 1):
        if i % 5 == 0:
            cid = f"condition_{i}"
            nodes.append({"id": cid, "type": "condition", "name": f"判断{i}", "config": {"branches": [{"key": "甲", "when": {"op": "exists", "left": None}}], "else_policy": "fail"}})
            edges.append({"source": 前, "target": cid, "port": "success"})
            布[cid] = {"x": 40 + i * 220, "y": 200}
            前 = cid
            continue
        nid = f"llm_{i}"
        nodes.append({"id": nid, "type": "llm", "name": f"步骤{i}", "config": {"bindings": {}}})
        if 前.startswith("condition_"):
            edges.append({"source": 前, "target": nid, "port": "branch", "branch_key": "甲"})
            edges.append({"source": 前, "target": nid, "port": "branch", "branch_key": "else"}) if False else None
        else:
            edges.append({"source": 前, "target": nid, "port": "success"})
        布[nid] = {"x": 40 + i * 220, "y": 200 + (i % 3) * 110}
        前 = nid
    nodes.append({"id": "end", "type": "end", "name": "结束", "config": {"output_schema": {"type": "object", "properties": {}, "required": []}, "bindings": {}}})
    edges.append({"source": 前, "target": "end", "port": "success"})
    布["end"] = {"x": 40 + (n - 1) * 220, "y": 200}
    return {"nodes": nodes, "edges": [e for e in edges if e]}, 布


def main():
    from selenium import webdriver
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    wid = T.准备工作流()
    o = webdriver.ChromeOptions(); o.add_argument("--headless=new"); o.add_argument("--window-size=1500,1000")
    d = webdriver.Chrome(options=o); js = d.execute_script
    结果 = []
    try:
        d.get(T.基址 + "/")
        js(f"localStorage.setItem('aimc.user','{T.我}');localStorage.setItem('aimc.proj','{T.项目}');localStorage.setItem('wf.自动保存','0')")
        for n in (20, 100):
            定, 布 = 造图(n)
            r = T.打("GET", f"/workflows/{wid}")
            T.打("PATCH", f"/workflows/{wid}/draft", {"定义": 定, "布局": 布}, {"If-Match": str(r["草稿"]["revision"])})
            js(f"localStorage.removeItem('wf.视口.{wid}')")
            d.get(T.基址 + f"/#/workflow/{wid}/搭建"); d.refresh()
            T.等(d, lambda: js("return typeof 图态!=='undefined' && !!图态 && 图态.wid") == wid and bool(js("return !!document.querySelector('#vw-g')")))
            d.find_element(By.ID, "vw-g").click()
            T.等(d, lambda: js("return document.querySelectorAll('.wfnode2').length") == len(定["nodes"]))
            画 = js("const t=[];for(let i=0;i<10;i++){const a=performance.now();画_图();t.push(performance.now()-a)}return t")
            线 = js("const t=[];for(let i=0;i<30;i++){const a=performance.now();画_线();t.push(performance.now()-a)}return t")
            快 = js("const t=[];for(let i=0;i<30;i++){const a=performance.now();图逻辑.快照(图态.定义,图态.布局);t.push(performance.now()-a)}return t")
            js("画布动作.缩放到(1); const v=画布动作.视口(); v.x=0; v.y=0; 画_视口();")
            js("window._线=[];const o=画_线;画_线=function(...a){const s=performance.now();const r=o.apply(this,a);_线.push(performance.now()-s);return r}")
            el = d.find_element(By.CSS_SELECTOR, '.wfnode2[data-id="llm_1"]')
            a = ActionChains(d).move_to_element_with_offset(el, 0, -20).click_and_hold()
            for _ in range(40):
                a = a.move_by_offset(3, 1)
            t0 = time.time(); a.release().perform(); 拖秒 = time.time() - t0
            拖线 = js("return _线")
            js("撤销()")
            t0 = time.time(); ok = js("return 做_存草稿()"); T.等(d, lambda: js("return 图态.保存态") == "已保存", 20); 存秒 = time.time() - t0
            字节 = len(json.dumps({"定义": 定, "布局": 布}, ensure_ascii=False).encode())
            结果.append((n, len(定["edges"]), 画, 线, 快, 拖线, 拖秒, 存秒, 字节))
    finally:
        r = T.打("GET", f"/workflows/{wid}")
        T.打("PATCH", f"/workflows/{wid}/draft", {"定义": T.夹具定义, "布局": T.夹具布局}, {"If-Match": str(r["草稿"]["revision"])})
        d.quit()
    中 = lambda xs: f"中位 {statistics.median(xs):.1f} ms / 最慢 {max(xs):.1f} ms" if xs else "—"
    print("流程图编辑器性能(无窗口 Chrome,这台开发机;只打印、不判红绿)")
    for n, e, 画, 线, 快, 拖线, 拖秒, 存秒, 字节 in 结果:
        print(f"\n▸ {n} 步 / {e} 条线(草稿 {字节 / 1024:.1f} KB)")
        print(f"  整张画布渲染(画_图)      {中(画)}")
        print(f"  重画全部连线(画_线)      {中(线)}")
        print(f"  拖动中每帧重画连线        {中(拖线)}(拖 40 步共重画 {len(拖线)} 次,整段手势 {拖秒:.2f} s)")
        print(f"  每次编辑的撤销快照        {中(快)}")
        print(f"  保存一次(含往返)          {存秒:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
