"""编排页 · 流程图编辑器在**真浏览器**里拖一遍(无窗口 Chrome + Selenium)—— 交互控件详细设计 V1.0 的 T01–T21。

## 为什么要真浏览器
拖动、拖线、框选、缩放后拖动、Esc 取消 —— 这些是**指针事件序列**,桩里只能直接调函数,
「函数对」和「手势接到了函数上」是两件事。这一份用真的鼠标动作去拖,然后**读页面里的 图态**核对结果
(读的是页面自己的数据,不是看截图猜)。

## 它碰什么
只碰一条专用工作流「编辑器验收(自动测试)」:没有就建,每次跑之前把草稿重置成固定的小图。
不运行、不冻结、不发布。要 `make dev`(管理后台在 8801)和本机 Chrome;缺哪个都**明确报出来并退非 0**。

  ./.venv/bin/python tests/e2e/test_workflow_editor_browser.py
"""
import json
import os
import sys
import time
import urllib.request

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
我 = os.environ.get("AIMC_USER", "U002")
名称 = "编辑器验收(自动测试)"

过, 挂 = [0], []


def ck(名, 真, 补=None):
    print(f"  {'✅' if 真 else '❌'} {名}" + ("" if 真 or 补 is None else "  " + json.dumps(补, ensure_ascii=False, default=str)[:240]))
    if 真:
        过[0] += 1
    else:
        挂.append(名)


def 打(方法, 路, 体=None, 头=None):
    h = {"X-Dev-User": 我, "content-type": "application/json", **(头 or {})}
    r = urllib.request.Request(基址 + f"/api/v1/projects/{项目}" + 路, method=方法,
                               data=json.dumps(体).encode() if 体 is not None else None, headers=h)
    with urllib.request.urlopen(r, timeout=20) as x:
        return json.loads(x.read() or b"{}")


夹具定义 = {
    "nodes": [
        {"id": "start", "type": "start", "name": "开始", "config": {"input_schema": {"type": "object", "properties": {"单号": {"type": "string"}}, "required": []}}},
        {"id": "llm_1", "type": "llm", "name": "整理问题", "config": {"bindings": {"单号": {"source": "input", "pointer": "/单号"}},
                                                                   "output_schema": {"type": "object", "properties": {"text": {"type": "string"}, "风险": {"type": "string"}}, "required": ["text"]}}},
        {"id": "condition_1", "type": "condition", "name": "判断风险", "config": {"branches": [{"key": "需关注", "when": {"op": "equals",
            "left": {"source": "node", "node_id": "llm_1", "pointer": "/风险"}, "right": {"source": "constant", "value": "高"}}}], "else_policy": "fail"}},
        {"id": "human_1", "type": "human", "name": "人工核对", "config": {"request_kind": "核对", "candidate_roles": ["approver"], "allowed_fields": ["定稿"],
            "expires_at_policy": {"小时": 48, "到期": "fail"}, "payload_binding": {"摘要": {"source": "node", "node_id": "llm_1", "pointer": "/text"}}}},
        {"id": "tool_1", "type": "tool", "name": "写入", "config": {"bindings": {"定稿": {"source": "node", "node_id": "human_1", "pointer": "/定稿"}}}},
        {"id": "end", "type": "end", "name": "返回结果", "config": {"output_schema": {"type": "object", "properties": {}, "required": []}, "bindings": {}}},
    ],
    "edges": [
        {"source": "start", "target": "llm_1", "port": "success"},
        {"source": "llm_1", "target": "condition_1", "port": "success"},
        {"source": "condition_1", "target": "human_1", "port": "branch", "branch_key": "需关注"},
        {"source": "condition_1", "target": "end", "port": "branch", "branch_key": "else"},
        {"source": "human_1", "target": "tool_1", "port": "success"},
        {"source": "tool_1", "target": "end", "port": "success"},
    ],
}
夹具布局 = {"start": {"x": 40, "y": 160}, "llm_1": {"x": 280, "y": 160}, "condition_1": {"x": 520, "y": 160},
            "human_1": {"x": 760, "y": 80}, "tool_1": {"x": 1000, "y": 80}, "end": {"x": 1000, "y": 280}}


def 准备工作流():
    ws = 打("GET", "/workflows").get("items") or 打("GET", "/workflows").get("rows") or []
    wid = next((w.get("id") for w in ws if w.get("名称") == 名称 or w.get("name") == 名称), None)
    if not wid:
        wid = 打("POST", "/workflows", {"名称": 名称, "用途": "编辑器浏览器测试专用,每次跑会重置草稿", "模板": "空白"})["id"]
    d = 打("GET", f"/workflows/{wid}")
    打("PATCH", f"/workflows/{wid}/draft", {"定义": 夹具定义, "布局": 夹具布局}, {"If-Match": str(d["草稿"]["revision"])})
    return wid


def main():
    print("编排页 · 流程图编辑器在真浏览器里拖一遍(T01–T21)")
    try:
        urllib.request.urlopen(基址 + "/", timeout=5)
    except Exception as e:
        print(f"❌ 管理后台没起(make dev):{e}"); return 2
    try:
        from selenium import webdriver
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import Select
    except ImportError:
        print("❌ 没装 selenium:./.venv/bin/pip install selenium"); return 2
    wid = 准备工作流()
    o = webdriver.ChromeOptions()
    o.add_argument("--headless=new"); o.add_argument("--window-size=1500,1000")
    d = webdriver.Chrome(options=o)
    js = d.execute_script
    try:
        d.get(基址 + "/")
        js(f"localStorage.setItem('aimc.user','{我}');localStorage.setItem('aimc.proj','{项目}');"
           f"localStorage.removeItem('wf.视口.{wid}');localStorage.setItem('wf.自动保存','0');")
        d.get(基址 + f"/#/workflow/{wid}/搭建")
        # ⚠️ 要**重新载入**:页面只在载入时读一次 localStorage 里的项目。上面那次 d.get 只改了 #,同一页没重载,
        # 页面还拿着第一次打开时的项目(空 → 选了列表第一个),在别的项目里找这条工作流,落回工作台 ——
        # 表现就是「等不到页面就绪」(10-27 查出来的,这份测试之前一直卡在这里)
        d.refresh()
        等(d, lambda: js("return !!(window.图态 || (typeof 图态!=='undefined' && 图态)) && !!document.querySelector('#vw-g')"))
        d.find_element(By.ID, "vw-g").click()
        等(d, lambda: js("return document.querySelectorAll('.wfnode2').length") == 6)
        js("画布动作.缩放到(1); const v=画布动作.视口(); v.x=0; v.y=0; 画_视口();")
        cv = d.find_element(By.ID, "cv")
        态 = lambda: js("return {布局: 图态.布局, 边: 图态.定义.edges.map(图逻辑.边键), 节点: 图态.定义.nodes.map(n=>n.id), 脏: 图态.脏, 撤: 历史().条数(), 选: [...图态.画.选], 线: 图态.画.线}")
        节 = lambda id: d.find_element(By.CSS_SELECTOR, f'.wfnode2[data-id="{id}"]')
        A = lambda: ActionChains(d)

        print("\n▸ T01 拖动节点:线跟着走,位置按缩放换算,一次撤销恢复")
        前 = 态()
        A().move_to_element_with_offset(节("llm_1"), 0, -20).click_and_hold().move_by_offset(10, 0).move_by_offset(70, 40).release().perform()
        后 = 态()
        p0, p1 = 前["布局"]["llm_1"], 后["布局"]["llm_1"]
        ck("100%:拖 80×40 屏幕像素 → 位置挪 80×40(8 像素网格吸附)", (p1["x"] - p0["x"], p1["y"] - p0["y"]) == (80, 40), [p0, p1])
        d0 = js("return document.querySelector('[data-edge=\"start|success||llm_1\"]').getAttribute('d')")
        ck("拖完之后进线的终点跟着节点走(线是实时重画的)", d0.endswith(f"{p1['x']},{p1['y'] + 20}"), d0)
        ck("松手只记一条历史", 后["撤"] == 前["撤"] + 1, [前["撤"], 后["撤"]])
        js("画布动作.缩放到(0.5); const v=画布动作.视口(); v.x=0; v.y=0; 画_视口();")
        A().move_to_element_with_offset(节("llm_1"), 0, -8).click_and_hold().move_by_offset(10, 0).move_by_offset(30, 20).release().perform()
        p2 = 态()["布局"]["llm_1"]
        ck("50%:拖 40×20 屏幕像素 → 位置挪 80×40(不会偏一倍)", (p2["x"] - p1["x"], p2["y"] - p1["y"]) == (80, 40), [p1, p2])
        js("画布动作.缩放到(1); const v=画布动作.视口(); v.x=0; v.y=0; 画_视口();")
        cv.click(); 按(d, cv, Keys.COMMAND, "z"); 按(d, cv, Keys.COMMAND, "z")
        ck("撤销两次 → 回到拖之前", 态()["布局"]["llm_1"] == p0, 态()["布局"]["llm_1"])
        # Esc 取消拖动:回到原位、不记历史
        前 = 态()
        A().move_to_element_with_offset(节("llm_1"), 0, -20).click_and_hold().move_by_offset(60, 60).perform()
        A().send_keys(Keys.ESCAPE).perform(); A().release().perform()
        ck("拖到一半按 Esc → 回到原位,不留半次位移、不记历史", 态()["布局"]["llm_1"] == 前["布局"]["llm_1"] and 态()["撤"] == 前["撤"], 态()["布局"]["llm_1"])

        print("\n▸ T02 区分点击与拖动")
        前 = 态()
        节("llm_1").find_element(By.CSS_SELECTOR, ".more").click()
        ck("点节点上的「⋯」→ 菜单打开,节点没被拖走、没标位置已改",
           js("return !!document.querySelector('#wf-menu')") and 态()["布局"] == 前["布局"] and 态()["撤"] == 前["撤"])
        A().send_keys(Keys.ESCAPE).perform(); js("关菜单()")
        A().context_click(节("llm_1")).perform()
        ck("右键步骤 → 弹出同一个菜单(和「⋯」同一套能力)", js("return !!document.querySelector('#wf-menu') && document.querySelector('#wf-menu').textContent.includes('定位引用')"))
        js("关菜单()")
        A().move_to_element_with_offset(节("llm_1"), 0, -20).click_and_hold().move_by_offset(2, 2).release().perform()
        ck("移动不到 4 像素算单击:选中它,不改位置", 态()["选"] == ["llm_1"] and 态()["布局"] == 前["布局"], 态()["选"])

        print("\n▸ T03 点线删线")
        k = "tool_1|success||end"
        A().move_to_element(d.find_element(By.CSS_SELECTOR, f'[data-edge="{k}"]')).click().perform()
        ck("点线 → 选中这条线,工具条出来", 态()["线"] == k and js("return !document.querySelector('#wf-edgebar').hidden"), 态()["线"])
        cv.send_keys(Keys.DELETE)
        s = 态()
        ck("Delete → 只删这条线,6 个步骤都在", k not in s["边"] and len(s["节点"]) == 6, s["边"])
        ck("提示「已断开」并带撤销", "已断开" in js("return document.querySelector('#wf-toast').textContent") and js("return !!document.querySelector('#wf-toast-u')"))
        d.find_element(By.ID, "wf-toast-u").click()
        ck("点提示里的撤销 → 线回来了", k in 态()["边"])

        print("\n▸ T04 连线取消")
        前 = 态()
        出 = 节("llm_1").find_element(By.CSS_SELECTOR, '[data-out="llm_1"]')
        A().move_to_element(出).click_and_hold().move_by_offset(0, 200).release().perform()
        ck("从出口拖到空白处松开 → 不建线、不删线、不建步骤", 态()["边"] == 前["边"] and 态()["节点"] == 前["节点"], 态()["边"])

        print("\n▸ T05 / T06 重连与替换")
        js("适应画布()")       # 整张图放进视野:人只会拖看得见的东西(拖到可视区外,事件落在别的元素上)
        k = "human_1|success||tool_1"
        A().move_to_element(d.find_element(By.CSS_SELECTOR, f'[data-edge="{k}"]')).click().perform()
        dst = d.find_element(By.CSS_SELECTOR, '[data-endh="dst"]')
        A().move_to_element(dst).click_and_hold().move_to_element(节("llm_1")).release().perform()
        ck("T05 把终点拖到会成环的步骤上 → 原线保留,提示原因", k in 态()["边"] and "原线保留" in js("return document.querySelector('#wf-toast').textContent"),
           js("return document.querySelector('#wf-toast').textContent"))
        A().move_to_element(d.find_element(By.CSS_SELECTOR, f'[data-edge="{k}"]')).click().perform()
        dst = d.find_element(By.CSS_SELECTOR, '[data-endh="dst"]')
        A().move_to_element(dst).click_and_hold().move_to_element_with_offset(节("end"), 0, -10).release().perform()
        s = 态()
        ck("T05 拖到合法步骤 → 原子替换:旧线没了,新线在", k not in s["边"] and "human_1|success||end" in s["边"], s["边"])
        js("撤销()")
        出 = 节("llm_1").find_element(By.CSS_SELECTOR, '[data-out="llm_1"]')
        A().move_to_element(出).click_and_hold().move_to_element_with_offset(节("end"), 0, -10).release().perform()
        ck("T06 已连着 A→B 再拖到 C → 先弹「将把下一步从 B 改为 C」", "将把下一步从" in (js("return (document.querySelector('#mb')||{}).textContent") or ""))
        d.find_element(By.ID, "rp-ok").click()
        s = 态()
        ck("T06 确认后只剩一条(整理问题 → 返回结果),不会两条线同时执行",
           [e for e in s["边"] if e.startswith("llm_1|success")] == ["llm_1|success||end"], s["边"])
        js("撤销()")

        print("\n▸ T07 / T08 删除节点")
        js("画布动作.选节点(['human_1'])"); cv.send_keys(Keys.DELETE)
        mb = js("return (document.querySelector('#mb')||{}).textContent") or ""
        ck("T07 删人工核对 → 弹影响(删 1 步 2 条线、写入在用它的定稿)", "1 个步骤" in mb and "2 条连线" in mb and "写入" in mb, mb[:200])
        ck("T07 人工核对不给「接通前后步骤」(不能删了核对直接写入)", not js("return !!document.querySelector('#dl-br')"))
        d.find_element(By.ID, "dl-ok").click()
        s = 态()
        ck("T07 删完:判断风险 → 写入 没被接上", "condition_1|branch|需关注|tool_1" not in s["边"] and "human_1" not in s["节点"], s["边"])
        js("画布动作.选节点(['tool_1'])")
        ck("T08 写入那一步的数据来源标「原来源已删除」(不清空、不改成别的)",
           "原来源" in js("return document.querySelector('#pn').textContent") and "已删除" in js("return document.querySelector('#pn').textContent"))
        js("撤销()")
        ck("T08 撤销一次 → 步骤、连线、引用全回来", "human_1" in 态()["节点"] and "human_1|success||tool_1" in 态()["边"])

        print("\n▸ T11 / T12 值控件与快捷键")
        js("图态.选中='llm_1'; 图态.面板页='设置'; 图态.高级开=false; 画_面板();")
        段 = js("return [...document.querySelectorAll('#pn .psec')].map(x=>x.dataset.sec)")
        ck("面板不分页签、从上到下分段(10-26 改版):基本 / 用到的数据 / 结果 / 高级,高级默认收起;模型步骤最后多一段「试这一步」",
           段 == ["设置", "输入数据", "结果字段", "高级", "试这一步"] and not js("return !!document.querySelector('#pn [data-pp]')")
           and js("return document.querySelector('#pn [data-sec=\"高级\"]').open") is False, 段)
        # 单步测试(10-26):能单测的类型才摆按钮;不能单测的不摆一个点了被拒的按钮
        有钮 = js("return !!document.querySelector('#pn #st-go')")
        js("图态.选中='human_1'; 画_面板();")
        人工有钮 = js("return !!document.querySelector('#pn #st-go')")
        ck("模型步骤有「单独测这一步」;人工核对没有(不摆点了没用的按钮)", 有钮 and not 人工有钮, [有钮, 人工有钮])
        js("图态.选中='llm_1'; 画_面板();")
        把 = d.find_element(By.CSS_SELECTOR, ".pgrip")
        ActionChains(d).click_and_hold(把).move_by_offset(-80, 0).release().perform()
        宽 = js("return localStorage.getItem('wf.面板宽')")
        js("画_搭建()")
        ck("面板拖宽后记住宽度(重画之后还是那么宽)",
           宽 and int(宽) > 440 and js("return getComputedStyle(document.querySelector('.wfbuild')).getPropertyValue('--pw').trim()") == f"{宽}px", 宽)
        d.find_element(By.ID, "trun").click(); time.sleep(0.3)
        ck("顶栏「试运行」→ 右侧面板换成试运行(不跳页签)",
           js("return document.querySelector('#pn h3').textContent") == "试运行" and bool(js("return !!document.getElementById('tr-go')"))
           and js("return decodeURIComponent(location.hash)").endswith("/搭建"))
        js("window._原视图=图态.视图; 图态.视图='步骤'; 画_搭建(); 记运行态({步骤:[{节点:'llm_1',状态:'succeeded'},{节点:'tool_1',状态:'failed',错误码:'X'}], 在等什么:{种类:'human',步骤:'human_1'}})")
        标 = js("return Object.fromEntries([...document.querySelectorAll('#steps .step')].map(x=>[x.dataset.id,(x.querySelector('.pill[data-run]')||{}).textContent||'']))")
        ck("试运行结果标到每一步:成功 / 失败 / 等人工核对", 标.get("llm_1") == "成功" and 标.get("tool_1") == "失败" and 标.get("human_1") == "等人工核对", 标)
        js("图态.运行态=null; 图态.试面板=false; 图态.视图=window._原视图; 画_搭建()")
        js("图态.选中='llm_1'; 图态.面板页='高级'; 画_面板();")
        框 = d.find_element(By.CSS_SELECTOR, '#pn [data-sec="高级"] .inwrap input')
        前 = js("return 节点('llm_1').config.max_output_tokens")
        框.clear(); 框.send_keys("1.8"); 框.send_keys(Keys.TAB)
        ck("T11 整数框填 1.8 → 显示错误,不写进定义(不截成 1)",
           js("return 节点('llm_1').config.max_output_tokens") == 前 and "整数" in js("return document.querySelector('#pn .ferr').textContent"))
        框 = d.find_element(By.CSS_SELECTOR, '#pn [data-sec="高级"] .inwrap input')
        框.click(); 框.send_keys(Keys.BACKSPACE); 框.send_keys(Keys.DELETE)
        ck("T12 在输入框里按 Delete / Backspace → 只删文字,步骤一个没少", len(态()["节点"]) == 6)

        print("\n▸ T17 不用拖也能做完:键盘移动、点出口再点目标")
        js("适应画布()")
        js("画布动作.选节点(['end'])")
        前 = 态()["布局"]["end"]
        节("end").send_keys(Keys.ARROW_RIGHT); 节("end").send_keys(Keys.SHIFT, Keys.ARROW_DOWN)
        后 = 态()["布局"]["end"]
        ck("方向键 8 像素、Shift+方向键 24 像素", (后["x"] - 前["x"], 后["y"] - 前["y"]) == (8, 24), [前, 后])
        js("撤销()")
        ck("连续方向键微调合并成一条历史:撤销一次就回到原位", 态()["布局"]["end"] == 前, 态()["布局"]["end"])
        出 = 节("tool_1").find_element(By.CSS_SELECTOR, '[data-out="tool_1"][data-oi="1"]')
        A().move_to_element(出).click().perform()
        ck("点一下出口(不拖)→ 进入「点目标」模式", js("return !!图态.画.待连"))
        A().move_to_element_with_offset(节("llm_1"), 0, -10).click().perform()
        ck("再点目标 → 不合法(会成环)时不建线,说原因", "tool_1|error||llm_1" not in 态()["边"])
        出 = 节("tool_1").find_element(By.CSS_SELECTOR, '[data-out="tool_1"][data-oi="1"]')
        A().move_to_element(出).click().perform(); time.sleep(0.3)
        ck("(再点一次出口,重新进入「点目标」模式)", js("return !!图态.画.待连"), js("return [(document.querySelector('#wf-toast')||{}).textContent]"))
        A().move_to_element(节("end")).click().perform()
        ck("点出口 → 点合法目标 → 建线(写入 · 失败时 → 返回结果)", "tool_1|error||end" in 态()["边"],
           态()["边"])
        ck("没选中连线时,连线工具条真的藏起来了(不挂在旧位置挡住步骤)",
           js("return getComputedStyle(document.querySelector('#wf-edgebar')).display") == "none")
        js("撤销()")

        print("\n▸ T15 未保存时离开")
        ck("有未保存的修改(上面这些都是本地编辑)", 态()["脏"])
        js("location.hash='#/workflows'")
        time.sleep(0.4)
        ck("切到别的页 → 拦下来问:保存并离开 / 留在此页 / 放弃", js("return !!document.querySelector('#lv-save') && !!document.querySelector('#lv-stay')"))
        d.find_element(By.ID, "lv-stay").click(); time.sleep(0.3)
        ck("选「留在此页」→ 还在这条工作流,修改还在", js("return location.hash").startswith(f"#/workflow/") and 态()["脏"])

        print("\n▸ 循环体外框:同一个循环里的步骤圈一个框,拖步骤时框跟着变")
        # 只在页面内存里把两步标成「在同一个循环里」(画框只看 container 字段),验完原样摘掉,不保存
        js("['llm_1','tool_1'].forEach(k => 图态.定义.nodes.find(n => n.id === k).container = 'start'); 画_节点(); 画_线();")
        框 = lambda: js("const r=document.querySelector('.loopbox[data-loopbox=\"start\"] rect'); return r && {x:+r.getAttribute('x'), y:+r.getAttribute('y'), w:+r.getAttribute('width'), h:+r.getAttribute('height'), 字: r.parentNode.textContent}")
        步框 = lambda k: js(f"const p=图态.布局['{k}']; return {{x:p.x, y:p.y, x1:p.x+画布.W, y1:p.y+节点高(图态.定义.nodes.find(n=>n.id==='{k}'))}}")
        b, s1, s2 = 框(), 步框("llm_1"), 步框("tool_1")
        ck("框把两步都圈在里面,框头写「循环 · … (2 步)」",
           bool(b) and all(b["x"] < s["x"] and b["y"] < s["y"] and b["x"] + b["w"] > s["x1"] and b["y"] + b["h"] > s["y1"] for s in (s1, s2))
           and "(2 步)" in b["字"], [b, s1, s2])
        ck("框不接鼠标(点 / 拖还落在步骤和线上)", js("return getComputedStyle(document.querySelector('.loopbox')).pointerEvents") == "none")
        右步 = "llm_1" if s1["x1"] >= s2["x1"] else "tool_1"
        A().move_to_element_with_offset(节(右步), 0, -20).click_and_hold().move_by_offset(10, 0).move_by_offset(150, 0).release().perform()
        b2, 挪 = 框(), 步框(右步)["x1"] - max(s1["x1"], s2["x1"])
        ck("把最右那一步往右拖 → 框右边跟着挪同样多(左边不动)", bool(b and b2) and 挪 > 0 and b2["x"] == b["x"] and round(b2["w"] - b["w"]) == 挪, [b, b2, 挪])
        # 先撤销拖动再摘标记:撤销恢复的是拖之前的整张图快照(里面带着刚才临时加的 container)
        js("撤销(); 图态.定义.nodes.forEach(n => delete n.container); 画_节点(); 画_线();")
        ck("摘掉之后框就没了", js("return document.querySelectorAll('.loopbox').length") == 0)

        print("\n▸ 问题分类器:每个类别一个出口;面板里改类别名线跟着改;删一类连线一起删")
        js("加到视口中间('classifier')")
        分 = [n for n in 态()["节点"] if n.startswith("classifier_")]
        ck("步骤库能加「问题分类器」并选中", len(分) == 1 and 态()["选"] == 分, 态()["节点"])
        if 分:
            分 = 分[0]
            口 = js(f"return [...document.querySelectorAll('[data-out=\"{分}\"]')].map(b => b.getAttribute('aria-label') || b.title || b.textContent)")
            ck("画布上 3 个出口:类别一 / 类别二 / 失败时", len(口) == 3 and "失败" in str(口[2]) and "类别一" in str(口[0]), 口)
            js(f"画布动作.连上('{分}', {{port:'branch', branch_key:'类别一'}}, 'tool_1')")
            ck("从「类别一」连到下一步", f"{分}|branch|类别一|tool_1" in 态()["边"], 态()["边"])
            js(f"画布动作.选节点(['{分}']); 图态.选中='{分}'; 图态.面板页='设置'; 画_面板();")
            框 = next((x for x in d.find_elements(By.CSS_SELECTOR, "#pn input") if x.get_attribute("value") == "类别一"), None)
            ck("面板里有「分成哪几类」,第一类的名字框找得到", 框 is not None and "分成哪几类" in d.find_element(By.ID, "pn").text)
            if 框:
                d.execute_script("arguments[0].focus(); arguments[0].select()", 框); 框.send_keys("有意向"); 框.send_keys(Keys.TAB)
                边 = 态()["边"]
                ck("改名「类别一 → 有意向」:线跟着改,不留旧名", f"{分}|branch|有意向|tool_1" in 边 and not any("|类别一|" in e for e in 边), 边)
            删 = next((b for b in d.find_elements(By.CSS_SELECTOR, "#pn button") if b.get_attribute("aria-label") == "删掉第 1 类"), None)
            if 删:
                删.click()
            边 = 态()["边"]
            ck("删掉第 1 类:它的线一起删,下一步那一步还在", not any(e.startswith(f"{分}|branch|") for e in 边) and "tool_1" in 态()["节点"]
               and js(f"return 图态.定义.nodes.find(n => n.id === '{分}').config.classes.map(c => c.key)") == ["类别二"], 边)
            js(f"画布动作.选节点(['{分}'])"); d.find_element(By.ID, "cv").send_keys(Keys.DELETE)
            ck("删掉分类器那一步(不留到后面的保存里)", not any(n.startswith("classifier_") for n in 态()["节点"]), 态()["节点"])

        print("\n▸ 模板转换:写了 {{名字}} 自动加一行待选来源;下游能选它的「文本」")
        js("加到视口中间('template')")
        模 = [n for n in 态()["节点"] if n.startswith("template_")]
        ck("步骤库能加「模板转换」并选中", len(模) == 1 and 态()["选"] == 模, 态()["节点"])
        if 模:
            模 = 模[0]
            ta = d.find_element(By.CSS_SELECTOR, '#pn textarea[data-lb="模板"]')
            ta.send_keys("{{客户}} 想要 {{款式}}"); ta.send_keys(Keys.TAB)
            绑 = js(f"return 图态.定义.nodes.find(n => n.id === '{模}').config.bindings")
            ck("写完模板,「客户」「款式」两行待选来源自动加上", sorted(绑 or {}) == ["客户", "款式"], 绑)
            js(f"画布动作.连上('{模}', {{port:'success', branch_key:null}}, 'end')")
            能选 = js("return 上游字段('end').map(x => x[1])")
            ck("下一步「用到的数据」里能选「模板转换 → 文本」", any("文本" in x and "模板转换" in x for x in 能选), 能选)
            js(f"画布动作.删线('{模}|success||end')")   # 连着线删步骤会弹「删除影响」确认,先删线
            js(f"画布动作.选节点(['{模}'])"); d.find_element(By.ID, "cv").send_keys(Keys.DELETE)
            ck("删掉模板转换那一步(不留到后面的保存里)", not any(n.startswith("template_") for n in 态()["节点"]), 态()["节点"])

        print("\n▸ 参数提取器:面板里填名字和类型;下游能按名字选它")
        js("加到视口中间('extractor')")
        提 = [n for n in 态()["节点"] if n.startswith("extractor_")]
        ck("步骤库能加「参数提取器」并选中", len(提) == 1 and 态()["选"] == 提, 态()["节点"])
        if 提:
            提 = 提[0]
            名框 = next((x for x in d.find_elements(By.CSS_SELECTOR, "#pn input") if x.get_attribute("placeholder") == "例如:预算"), None)
            ck("面板里有「要提取哪几项」和第一项的名字框", 名框 is not None and "要提取哪几项" in d.find_element(By.ID, "pn").text)
            if 名框:
                名框.send_keys("预算"); 名框.send_keys(Keys.TAB)
                类 = next((x for x in d.find_elements(By.CSS_SELECTOR, "#pn select") if "整数" in x.text), None)
                if 类:
                    Select(类).select_by_value("integer")
                参 = js(f"return 图态.定义.nodes.find(n => n.id === '{提}').config.parameters")
                ck("填了名字「预算」、类型选整数 → 写进配置", (参 or [{}])[0].get("name") == "预算" and 参[0].get("type") == "integer", 参)
                js(f"画布动作.连上('{提}', {{port:'success', branch_key:null}}, 'end')")
                能选 = js("return 上游字段('end').map(x => x[1])")
                ck("下一步「用到的数据」里能选「参数提取器 → 预算」", any("预算" in x and "参数提取器" in x for x in 能选), 能选)
                js(f"画布动作.删线('{提}|success||end')")
            js(f"画布动作.选节点(['{提}'])"); d.find_element(By.ID, "cv").send_keys(Keys.DELETE)
            ck("删掉参数提取器那一步(不留到后面的保存里)", not any(n.startswith("extractor_") for n in 态()["节点"]), 态()["节点"])

        print("\n▸ 变量赋值:不在循环里先提示;放进循环后能选那个循环的状态")
        js("加到视口中间('loop')")
        环 = [n for n in 态()["节点"] if n.startswith("loop_")]
        js("加到视口中间('assigner')")
        赋 = [n for n in 态()["节点"] if n.startswith("assigner_")]
        ck("步骤库能加「变量赋值」并选中", len(赋) == 1 and 态()["选"] == 赋 and len(环) == 1, 态()["节点"])
        if 赋 and 环:
            赋, 环 = 赋[0], 环[0]
            ck("还不在循环里 → 面板提示先选循环", "先在下面「高级」的「放在哪个循环里」选一个循环" in d.find_element(By.ID, "pn").text)
            js(f"图态.定义.nodes.find(n => n.id === '{赋}').container = '{环}'; 画_面板();")
            加 = next((b for b in d.find_elements(By.CSS_SELECTOR, "#pn button") if b.text == "加一条"), None)
            if 加:
                加.click()
            选项 = js("return [...document.querySelectorAll('#pn select')].map(s => [...s.options].map(o => o.value))")
            配 = js(f"return 图态.定义.nodes.find(n => n.id === '{赋}').config.assignments")
            ck("放进循环后「加一条」:能选那个循环的状态「还要做」,默认改法覆盖", any("还要做" in o for o in 选项)
               and 配 == [{"variable": "还要做", "op": "set"}], (选项, 配))
            js(f"画布动作.选节点(['{赋}','{环}'])"); d.find_element(By.ID, "cv").send_keys(Keys.DELETE)
            ck("删掉这两步(不留到后面的保存里)", not any(n.startswith(("assigner_", "loop_")) for n in 态()["节点"]), 态()["节点"])

        print("\n▸ T21 完整链路:加步骤 → 连线 → 配置 → 删线 → 撤销 → 保存 → 重开")
        js("加到视口中间('transform')")
        新 = [n for n in 态()["节点"] if n.startswith("transform_")]
        ck("步骤库「添加」→ 放进画布并选中", len(新) == 1 and 态()["选"] == 新, 态()["选"])
        新 = 新[0]
        js(f"画布动作.连上('tool_1', {{port:'error', branch_key:null}}, '{新}')")
        js(f"画布动作.删线('{新}'.length ? 'tool_1|error||{新}' : '')"); js("撤销()")
        ck("连上 → 删线 → 撤销:线还在", f"tool_1|error||{新}" in 态()["边"])
        保 = js("return 做_存草稿()")
        等(d, lambda: js("return 图态.保存态") == "已保存")
        存时 = 态()
        rev = js("return 图态.revision")
        ck("保存后状态写着「已保存 rN」", f"r{rev}" in d.find_element(By.ID, "savest").text, d.find_element(By.ID, "savest").text)
        d.refresh()
        等(d, lambda: js("return typeof 图态!=='undefined' && !!图态 && 图态.wid") == wid)
        重开 = js("return {布局: 图态.布局, 边: 图态.定义.edges.map(图逻辑.边键), 节点: 图态.定义.nodes.map(n=>n.id)}")
        ck("重开之后步骤、连线、布局和保存前一致",
           sorted(重开["节点"]) == sorted(存时["节点"]) and sorted(重开["边"]) == sorted(存时["边"])
           and all(重开["布局"].get(k) == v for k, v in 存时["布局"].items() if k != "$线"), 重开)
        print("\n▸ L-T 原始日志(§15):真记录、筛选标子集、节点定位、导出记审计")
        rs = 打("GET", "/execution-runs?limit=30").get("items") or []
        rid = None
        for r in rs:
            x = 打("GET", f"/execution-runs/{r['id']}/raw-log")
            if x["按来源"]["步骤尝试"] >= 2 and x["按来源"]["事件"] >= 2:
                rid, 全 = r["id"], x; break
        ck("项目里有带步骤和事件的运行可验(样本量不能是 0)", rid is not None)
        if rid:
            js("图态 && (图态.脏 = false)")      # 上面那几段留下的本地编辑不影响这一段;别让离开拦截挡路
            d.get(基址 + f"/#/wfrun/{rid}")
            等(d, lambda: js("return !!document.querySelector('#rl-open')"))
            d.find_element(By.ID, "rl-open").click()
            等(d, lambda: js("return !!document.querySelector('.rawlog')"))
            文 = lambda: js("return document.querySelector('.rawlog').textContent")
            ck("打开 → 列出这次运行的全部原始记录(条数和接口一致)", f"共 {全['共']} 条" in 文() and js("return document.querySelectorAll('.rlrow').length") == 全["共"], 文()[:120])
            ck("每条写着来源表、主键、字节数、指纹", "run_events" in 文() and "指纹" in 文() and "字节" in 文())
            ck("没有「查看敏感输入」授权 → 标明部分打码(不冒充原件)", "部分打码" in 文())
            from selenium.webdriver.support.ui import Select
            Select(d.find_element(By.ID, "rl-src")).select_by_visible_text("事件")
            等(d, lambda: "筛选子集" in 文())
            ck("按来源筛 → 写明「筛选子集 x / 共 y」,不把子集说成全部", f"筛选子集 {全['按来源']['事件']} / 共 {全['共']}" in 文(), 文()[:120])
            d.find_element(By.ID, "rl-fmt").click()
            ck("切到格式化 → 换排法,原件还是那几条(条数不变)", js("return document.querySelectorAll('.rlrow').length") == 全["按来源"]["事件"])
            d.find_element(By.CSS_SELECTOR, "[data-rlnode]").click()
            等(d, lambda: js("return !!document.querySelector('#rl-node') && document.querySelector('#rl-node').value !== ''"))
            ck("「查看该节点日志」→ 带着节点筛选打开", js("return document.querySelector('#rl-node').value") != "")
            def 审计数():
                r = urllib.request.Request(基址 + f"/api/v1/projects/{项目}/audit-events?limit=200", headers={"X-Dev-User": "U001"})
                with urllib.request.urlopen(r) as x:
                    # 数「动作分布」里的总次数,不数「记录」:记录只给最近 200 条,新的一条进来、最老的一条导出被挤出去,
                    # 数出来前后一样 —— 10-27 撞到过 [11, 11]。分布是整段时间范围里的计数,只增不减
                    return next((a["次数"] for a in json.loads(x.read()).get("这个范围里的动作分布", []) if a.get("动作") == "导出原始日志"), 0)
            前审 = 审计数()
            js("document.querySelector('#rl-dl').scrollIntoView({block:'center'})")
            d.find_element(By.ID, "rl-dl").click()
            等(d, lambda: "记进了审计" in (js("return (document.querySelector('#wf-toast')||{}).textContent") or ""))
            ck("下载 → 走单独的导出接口,这次导出记进审计", 审计数() == 前审 + 1, [前审, 审计数()])
    finally:
        d.quit()
    print(f"\n{'❌' if 挂 else '✅'} 流程图编辑器真浏览器 {过[0]} 条过" + (f",挂 {len(挂)} 条:{' / '.join(挂)}" if 挂 else ""))
    return 1 if 挂 else 0


def 等(d, 条件, 秒=10):
    限 = time.time() + 秒
    while time.time() < 限:
        try:
            if 条件():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    raise TimeoutError("等不到页面就绪")


def 按(d, el, 修饰, 键):
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
    ActionChains(d).key_down(修饰).send_keys(键).key_up(修饰).perform()


if __name__ == "__main__":
    sys.exit(main())
