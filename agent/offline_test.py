#!/usr/bin/env python3
"""V1 循环的离线自测:用脚本化的假响应替换 HTTP,不调用任何模型。

验证四件事:
  1. 工具派发 —— 模型给的 tool_use 能不能正确落到后台函数上
  2. 结果回灌 —— tool_result 的形状对不对,模型下一轮能不能拿到
  3. 循环终止 —— submit_finding 之后是否停,max_turns 是否兜底
  4. 记账 —— token 与成本的算法对不对
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v1

CALLS=[]          # 记录每轮实际发出去的 messages
def fake_provider():
    return dict(id="offline", url="", model="stub", headers=[],
                price=dict(inp=0.55, cache=0.055, out=2.19))

def make_script(deposit_id):
    """模拟一个理想的模型轨迹:读押金 → 读轨迹 → 读流水 → 提交结论"""
    def blk(name, inp, i):
        return {"type":"tool_use","id":f"tu_{i}","name":name,"input":inp}
    return [
      dict(content=[blk("get_deposit",{"deposit_id":deposit_id},1)],
           stop_reason="tool_use", usage=dict(input_tokens=1200,output_tokens=60)),
      dict(content=[blk("get_refund_trace",{"deposit_id":deposit_id},2)],
           stop_reason="tool_use", usage=dict(input_tokens=1400,output_tokens=55,cache_read_input_tokens=1100)),
      dict(content=[blk("get_payment_flow",{"deposit_id":deposit_id},3)],
           stop_reason="tool_use", usage=dict(input_tokens=1700,output_tokens=58,cache_read_input_tokens=1350)),
      dict(content=[blk("submit_finding",{
             "root_cause":"渠道三次均返回 TIMEOUT,但支付流水显示退款实际已成功",
             "recommended_action":"不得再次发起退款;以支付平台结果为准置为已退并补记流水",
             "evidence":["refund_trace 三次 resp_code 均为 TIMEOUT",
                         "payment_flow 存在 direction=out、status=success 的记录"],
             "confidence":"高"},4)],
           stop_reason="tool_use", usage=dict(input_tokens=2100,output_tokens=180,cache_read_input_tokens=1700)),
    ]

def run(deposit_id="D2000"):
    script=make_script(deposit_id); idx={"i":0}
    def fake_call(pv, body, retries=6, **kw):   # **kw 兼容记录仪加的 purpose/turn
        # run_case 是原地 append messages,必须存快照否则四轮记的都是最终状态
        CALLS.append(json.loads(json.dumps(body["messages"], ensure_ascii=False)))
        r=script[idx["i"]]; idx["i"]+=1; return r
    v1.call=fake_call
    pv=fake_provider()
    r=v1.run_case(pv, v1.BP01.format(ref=deposit_id))

    ok=lambda b: "✅" if b else "❌"
    print("=== V1 循环离线自测 ===\n")
    print(f"{ok(r['trajectory']==['get_deposit','get_refund_trace','get_payment_flow','submit_finding'])} "
          f"① 工具派发顺序: {' → '.join(r['trajectory'])}")

    # 检查第 2 轮消息里是否含第 1 轮的真实工具返回
    second=CALLS[1]
    tr=[m for m in second if m["role"]=="user" and isinstance(m["content"],list)]
    got=json.loads(tr[-1]["content"][0]["content"]) if tr else {}
    print(f"{ok(got.get('id')==deposit_id and 'idem_key' in got)} "
          f"② 结果回灌: 第 2 轮拿到了 {deposit_id} 的真实数据 (幂等号 {got.get('idem_key')})")

    print(f"{ok(r['finding'] is not None and r['calls']==4)} "
          f"③ 循环终止: submit_finding 后停止,共 {r['calls']} 轮")

    tin,tout,tc=r["input"],r["output"],r["cache"]
    expect=(tin*0.55+tc*0.055+tout*2.19)/1_000_000
    print(f"{ok(abs(r['cost_local']-round(expect,6))<1e-9)} "
          f"④ 记账: 输入{tin} 输出{tout} 缓存{tc} → ${r['cost_local']:.6f}")

    print(f"\n提交的结论:")
    f=r["finding"]
    print(f"  根因   {f['root_cause']}")
    print(f"  动作   {f['recommended_action']}")
    for e in f["evidence"]: print(f"  证据   {e}")

    # 额外:验证 truth 表没有通过任何工具泄漏给模型
    allsent=json.dumps(CALLS, ensure_ascii=False)
    print(f"\n{ok('root_cause' not in allsent.replace(f['root_cause'],''))} "
          f"⑤ 答案隔离: 发给模型的全部消息里不含 truth 表内容")
    return r

if __name__=="__main__":
    run(sys.argv[1] if len(sys.argv)>1 else "D2000")
