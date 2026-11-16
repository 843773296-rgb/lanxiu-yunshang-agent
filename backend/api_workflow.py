"""从 backend/api.py 拆出来的「api_workflow」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api


def start_workflow(skill, inputs=None):
    """**发起一条被工作流接管的事**(用户 2026-10-24 拍「默认关;打开时聊天站改走工作流」)。

    只在那个技能被拦下、拦截理由点名要它时才用。开没开、你的工号绑的是哪个管理后台账号,
    都由管理后台在这一刻再判一次 —— 这里不判第二份(见 backend/takeover_client.py)。
    幂等键见 takeover_client.幂等键(带工作流、一分钟窗口 —— 10-24 真跑踩过拿回旧运行)。"""
    import time as _t
    import takeover_client as _tc
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在发起 —— 请先登录")
    sk = (skill or "").strip().lstrip("/")
    if not sk: return dict(error="要说清是哪件事(技能名),比如 call-notes")
    键 = _tc.幂等键(me["no"], sk, (_tc.接管中(sk) or {}).get("workflow_id"), inputs, _t.time())
    ok, 回 = _tc.发起(sk, me["no"], inputs or {}, 键)
    if ok:
        api._agent_log(me, "WF_START", f"发起工作流「{回.get('工作流')}」(接管 {sk}),运行 {回.get('运行号')}")
        # 发起后等一会儿(用户 10-27 拍):工作流里「直接回复」那几步在这期间说的话,当场带回这一轮
        到, 进度 = _tc.等回复(回.get("运行号"), me["no"])
        if 到:
            回.update(回复=进度["回复"], 状态=进度["状态"], 在等人工核对=进度["在等人工核对"],
                     还在跑=进度["还在跑"])
            if 进度["还在跑"]:
                回["说明"] += ";还没跑完 —— 用户问起进度时用 workflow_replies 再取"
        else:
            回["回复"] = []
            回["说明"] += f";刚才没取到进度({进度.get('error')}),用户问起时用 workflow_replies 再取"
    return 回

def offer_call_upload(customer_id, task_id=None):
    """**在聊天里给导购一个「上传录音」按钮**(用户 2026-11-03 提、拍「传完自动走录音跟进」)。

    本身**不写任何东西**:只核客户在不在、是不是本店的,把卡片要的几样交给页面。
    真上传走 /api/call-upload(服务端按登录身份再判一次本店、大小、时长);转写完成后由转写工人
    按上传时带的 then=录音跟进 去管理后台发起,跟进要人核对通过才写进系统。"""
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在传 —— 请先登录")
    cid = (customer_id or "").strip()
    if not cid: return dict(error="要先知道是哪位客户(客户号);只知道姓名就先用 get_customer 认出客户号")
    r = api._rows("SELECT id, name, shop FROM customer WHERE id=?", cid)
    if not r: return dict(error=f"没有客户 {cid} —— 只知道姓名的话先用 get_customer 认出客户号")
    r = r[0]
    if me.get("role") != "总部运营" and me.get("shop") != r["shop"]:
        return dict(error="只能给本店客户传录音")
    tid = (task_id or "").strip() or None
    if tid:
        t = api._rows("SELECT id, customer_id FROM schedule WHERE id=?", tid)
        if not t: return dict(error=f"没有任务 {tid}")
        if t[0]["customer_id"] and t[0]["customer_id"] != cid:
            return dict(error=f"任务 {tid} 不是客户 {cid} 的")
    return dict(卡片={"类型": "录音上传", "客户号": cid, "姓名": r["name"], "任务号": tid,
                     "沟通方式": ["电话", "上门", "到店"], "接着走": "录音跟进"},
                说明="页面上已经出了「上传录音」按钮。告诉导购:选好录音文件和沟通方式点上传;"
                     "转完文字会自动走录音跟进,整理出的跟进要人核对通过才写进系统。**别说成已经传了、已经写了**。")

def workflow_replies(run_id):
    """**查一条从聊天发起的工作流现在说了什么、跑到哪了**(用户 2026-10-27 拍「发起时等一会儿 + 可追问」)。

    只查得到自己发起的那几条 —— 管理后台按工号核,这里不判第二份。只读。"""
    import takeover_client as _tc
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在问 —— 请先登录")
    ok, 回 = _tc.取回复(run_id, me["no"])
    return 回

def draft_capability_request(scene=None, who=None, pain=None, want=None, given=None, expect=None, title=None):
    """起草一份能力申请(只读,不提交;用户 11-11 拍:用户不会写需求时让助手问清后代写)。
    提交由用户在页面申请单上点「确认提交」,走「意见与建议」原通道,提交人是用户本人。"""
    import capability_request as C
    return C.起草({"场景": scene, "谁用": who, "现在卡在哪": pain, "想让它做什么": want,
                   "给它什么": given, "希望得到什么": expect}, 标题=title)
