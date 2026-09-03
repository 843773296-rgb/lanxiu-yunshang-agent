#!/usr/bin/env python3
"""调用记录仪 —— 每次模型调用写一行 JSON 到 .feynman/llm-trace.jsonl。

原则:包一层,不改业务逻辑。整个项目只有 v1.call() 一处真正发请求,所以只需要包它。

隐私:**默认不记提示词和回答内容。** 本项目的题面里带客户 ID、押金单号,
工具返回里带客户档案 —— 这些一旦进日志,日志就成了一份没人当敏感数据管的客户资料副本。
需要调试时用 TRACE_BODY=1 打开,记前 200 字符,且要清楚自己在记什么。
"""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "..", ".feynman", "llm-trace.jsonl")
BODY = os.environ.get("TRACE_BODY") == "1"


def record(*, model, purpose, usage, latency_ms, price, finish_reason=None,
           turn=None, attempt=0, error=None, body=None, resp_text=None, cache_on=False):
    u = usage or {}
    tin = u.get("input_tokens", 0)
    tout = u.get("output_tokens", 0)
    tcache = u.get("cache_read_input_tokens", 0)      # Anthropic 口径:命中(便宜)
    twrite = u.get("cache_creation_input_tokens", 0)  # 写入缓存(比普通输入贵约 25%)
    p = price or {}
    cost = (tin * p.get("inp", 0) + tcache * p.get("cache", 0)
            + twrite * p.get("inp", 0) * 1.25 + tout * p.get("out", 0)) / 1_000_000
    row = dict(
        ts=time.strftime("%Y-%m-%d %H:%M:%S"),
        model=model, purpose=purpose,
        input_tokens=tin, output_tokens=tout, cache_hit_tokens=tcache,
        cache_write_tokens=twrite, cache_on=bool(cache_on),
        latency_ms=round(latency_ms), cost_est=round(cost, 6),
        finish_reason=finish_reason, turn=turn, attempt=attempt,
    )
    if error: row["error"] = str(error)[:200]
    if BODY:                                           # 显式打开才记内容
        if body is not None:
            row["prompt_head"] = json.dumps(body, ensure_ascii=False)[:200]
        if resp_text: row["resp_head"] = resp_text[:200]
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def summary(path=None):
    """汇总:说「帮我汇总一下 trace」时读这个。"""
    import collections
    p = path or LOG
    if not os.path.exists(p): return {"rows": 0}
    rs = [json.loads(l) for l in open(p, encoding="utf-8")]
    tin = sum(r["input_tokens"] for r in rs); tc = sum(r["cache_hit_tokens"] for r in rs)
    return dict(
        rows=len(rs), cost=round(sum(r["cost_est"] for r in rs), 4),
        input_tokens=tin, output_tokens=sum(r["output_tokens"] for r in rs),
        cache_hit_tokens=tc,
        cache_rate=f"{tc/(tin+tc)*100:.1f}%" if (tin + tc) else "0%",
        by_purpose=dict(collections.Counter(r["purpose"] for r in rs)),
        by_model=dict(collections.Counter(r["model"] for r in rs)),
        slowest=max(rs, key=lambda r: r["latency_ms"], default=None),
        priciest=max(rs, key=lambda r: r["cost_est"], default=None),
        truncated=[r for r in rs if r.get("finish_reason") == "max_tokens"],
        errors=[r for r in rs if r.get("error")],
    )


if __name__ == "__main__":
    s = summary()
    if not s["rows"]: print("还没有记录。跑一次智能体就会有。"); raise SystemExit
    print(f"共 {s['rows']} 次调用 · 总成本 ${s['cost']}")
    print(f"  输入 {s['input_tokens']:,}  输出 {s['output_tokens']:,}  缓存命中 {s['cache_hit_tokens']:,}"
          f"  → 缓存命中率 {s['cache_rate']}")
    print(f"  按场景 {s['by_purpose']}")
    print(f"  按模型 {s['by_model']}")
    if s["slowest"]:  print(f"  最慢 {s['slowest']['latency_ms']}ms  ({s['slowest']['purpose']})")
    if s["priciest"]: print(f"  最贵 ${s['priciest']['cost_est']:.4f}  ({s['priciest']['purpose']})")
    print(f"  被截断 {len(s['truncated'])} 次 · 出错 {len(s['errors'])} 次")
