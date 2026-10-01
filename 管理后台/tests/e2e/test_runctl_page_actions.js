/* 运行控制四个动作**在页面代码里真走一遍**。
 *
 * ## 为什么要有它
 *
 * 这四个动作是**出事那天唯一的手段** —— 一次跑飞了的运行,能不能停下来。
 * 而它们最容易错的地方一个都不在界面上:
 *
 * | 容易错的地方 | 错了会怎样 |
 * |---|---|
 * | 漏了 `If-Match` | 两个人同时点「取消」和「继续」,**后到的悄悄覆盖先到的,两边都收到成功** |
 * | 漏了幂等键 | 409;或者更糟,超时重发被当成两次操作 |
 * | 前端自己翻译状态名 | `pause_requested` 显示成「已暂停」—— **界面上说停了,实际还在跑** |
 * | 终态还摆着按钮 | 点了回「已经结束了」—— **「点了没用」比「没有这个按钮」更费时间** |
 *
 * ⚠️ 其中 `revision` 是 **2026-09-29 才有地方拿的**:在那之前
 * `GET /execution-runs/{id}` 不返回它,于是这三个动作在界面上做不起来。
 * 所以这一份里有一条专门盯着那个字段。
 */
"use strict";
const fs = require("fs"), path = require("path");
const 桩 = require("./_页面桩.js");

const 项目 = 桩.默认项目;
const P = 桩.P(项目);
const src = fs.readFileSync(
  path.join(__dirname, "..", "..", "apps", "web", "app.js"), "utf8");

const 该跑几组 = 4;
const { ck, 组, 结束, 状 } = 桩.计分(该跑几组);

(async () => {
  console.log("\n\x1b[1m▸ 运行控制:暂停 / 继续 / 取消 / 核实外部状态\x1b[0m");
  console.log("  ⚠️ 这四个动作是**出事那天唯一的手段** —— 验的是接线,不验界面");

  const { 请求们, 弹过 } = 桩.装桩({ hash: "#/runs", 我: "U001", 项目 });
  try { 桩.跑页面(src); } catch (e) {
    ck("app.js 同步执行不挂", false, e.message); 结束(弹过); return;
  }
  const 控 = globalThis.运行控制;
  ck("app.js 把 `运行控制` 导出来了",
     控 && ["暂停", "继续", "取消", "核实"].every((k) => typeof 控[k] === "function"),
     控 ? Object.keys(控) : null);
  if (!控) { 结束(弹过); return; }

  try {
    // ── ① 详情里拿得到 revision ──────────────────────────────────
    组("① 详情里拿得到 `revision`(2026-09-29 才有的)");
    // ⚠️ **自己发起一次运行,不挑现成的。**
    //
    // 第一版是「从列表里挑一个非终态的」,而这一份每跑一次就把一个运行
    // **推成终态** —— 跑几遍就没得挑了,`make progress` 当场红。
    // (判据本身没错:它拒绝在「挑不到」时蒙混过关,红得对。
    //  错的是测试**消耗共享资源** —— 和连接那一页同一条规矩:
    //  **自己建夹具,别动现成的**。)
    const [码W, W] = await 桩.直打("GET", `${P}/workflows`, null, "U001");
    const wf = ((W || {}).items || [])[0];
    ck("找得到一个工作流当夹具(找不到的话下面全是空跑)", Boolean(wf), wf && wf.id);
    if (!wf) { 结束(弹过); return; }
    const [码N, 新运行] = await 桩.直打("POST", `${P}/execution-runs`,
      { workflow_id: wf.id, 输入: {}, 模式: "mock" }, "U001",
      { "Idempotency-Key": "rc" + Date.now().toString(16)
        + Math.random().toString(16).slice(2, 8) });
    ck("自己发起一次运行 → 拿到 id",
       (码N === 201 || 码N === 202) && 新运行 && (新运行.id || 新运行.resource_id),
       { 码: 码N, id: 新运行 && (新运行.id || 新运行.resource_id) });
    const 目标 = 新运行 && (新运行.id || 新运行.resource_id);
    if (!目标) { 结束(弹过); return; }
    const [, 详] = await 桩.直打("GET",
      `${P}/execution-runs/${encodeURIComponent(目标)}`, null, "U001");
    ck("它现在**不是终态**(刚发起的,还没人跑它)",
       (详 || {})["是终态吗"] === false, (详 || {})["执行状态"]);
    ck("详情里给了 `revision`(**控制动作拿它做 If-Match**;"
       + "拿不到就只能不带,而那正是「后到的悄悄覆盖先到的」那条路)",
       typeof (详 || {}).revision === "number", (详 || {}).revision);

    // ── ② revision 为空时**当场报错,不发请求** ────────────────────
    组("② revision 为空 → 当场报错,一个请求都不发");
    const 之前 = 请求们.filter((x) => x.地址.includes("/pause")).length;
    let 空 = null;
    try { await 控.暂停(目标, null); } catch (e) { 空 = e; }
    ck("传 null 的 revision → **本地报错**(不拿它去发一个注定 422 的请求)",
       空 && (空.体 || {}).code === "NO_RUN_REVISION",
       空 && { code: (空.体 || {}).code, 消息: String(空.message).slice(0, 40) });
    ck("而且**根本没发出请求** —— 发出去再被 422 拒,会在审计里"
       + "留一条读不懂的失败,而那句「要给 revision」会让人以为是接口的问题",
       请求们.filter((x) => x.地址.includes("/pause")).length === 之前,
       { 之前, 之后: 请求们.filter((x) => x.地址.includes("/pause")).length });

    // ── ③ 只做**现在合法**的那个动作 ──────────────────────────────
    组("③ 合法的那个动作:幂等键 + If-Match 都要带");
    // ⚠️ 这一组第一版是硬点「暂停」的,而目标运行是 `queued` ——
    // 状态机不允许,回 `BAD_TRANSITION`,测试当场断在这儿。
    // 那不只是测试写错:**页面当时也把四个按钮一起摆着** ——
    // 点了回一个 BAD_TRANSITION,正是「点了没用比没有这个按钮更费时间」。
    // 修法是让**接口算出哪几个合法**(`可执行的控制动作`),
    // 前端照着摆,测试也照着点 —— 三者用同一个来源,谁也不抄状态机。
    const [, 详2] = await 桩.直打("GET",
      `${P}/execution-runs/${encodeURIComponent(目标)}`, null, "U001");
    const rev = (详2 || {}).revision;
    const 动作们 = (详2 || {})["可执行的控制动作"] || [];
    ck("详情里给了 `可执行的控制动作`(**由接口算**,前端猜等于把状态机抄一遍)",
       动作们.length >= 3, 动作们.map((a) => `${a["动作"]}=${a["现在能吗"]}`));
    ck("不能做的那几个**说清了为什么**(只写「不能」的话人得自己去翻状态机)",
       动作们.filter((a) => !a["现在能吗"]).every((a) => Boolean(a["为什么不能"])),
       (动作们.find((a) => !a["现在能吗"]) || {})["为什么不能"]);

    const 中文到键 = { pause: "暂停", resume: "继续", cancel: "取消" };
    const 能做的 = 动作们.find((a) => a["现在能吗"] && 中文到键[a["动作"]]);
    ck("找得到一个现在能做的状态类动作(找不到的话下面几条是空跑)",
       Boolean(能做的), 能做的 && 能做的["动作"]);
    if (!能做的) { 结束(弹过); return; }

    // ⚠️ **「拿旧 revision 会被拒」这一条不在这儿断 —— 它在这儿只会假红。**
    //
    // 这一份跑在**有活 Worker** 的环境里(`make progress` 就是),
    // 而新发起的运行会被 Worker **立刻跑成终态**。
    // `runctl.py` 对「已经在那个状态」的请求**先返回「没有改动」、不查 revision**
    // (什么都没写,所以那是对的)—— 于是没有异常,断言拿到 null。
    // 单跑的时候 Worker 慢一点,它又是绿的。
    //
    // 而这条性质**已经在 `tests/e2e/test_runctl_flow.py:91` 钉住了** ——
    // 那一份控制得了状态(它自己造运行、自己卡状态)。
    // 这一份的职责是**接线**:revision 有没有进 If-Match ——
    // 那一条下面单独断着,而且它不依赖时序。
    //
    // > **一条时序依赖、而且性质已经在别处钉住的断言,留着只会假红** ——
    // > 而会假红的判据会把人教会忽略它,那时它连真的那次也拦不住。

    const r1 = await 控[中文到键[能做的["动作"]]](目标, rev);
    ck(`做「${能做的["中文"]}」→ 有结果`, Boolean(r1),
       JSON.stringify(r1).slice(0, 90));
    const 请1 = 桩.头里(请求们, `/${能做的["动作"]}`);
    ck("带了幂等键", 请1 && typeof 请1.头["Idempotency-Key"] === "string",
       请1 && 请1.头["Idempotency-Key"]);
    ck("带了 **If-Match,而且就是详情给的那个数**"
       + "(两个人同时点,后到的不许悄悄覆盖先到的)",
       请1 && 请1.头["If-Match"] === String(rev),
       { 带的: 请1 && 请1.头["If-Match"], 该带: rev });

    // ⚠️ **不合法的那个,服务端照样要拒** —— 界面藏起来只是提示,
    // 而「藏起来了」不等于「拦住了」(§5.2:不可把禁用前端按钮当后端授权)。
    const 不能的一个 = 动作们.find((a) => !a["现在能吗"] && 中文到键[a["动作"]]);
    if (不能的一个) {
      const [, 详3] = await 桩.直打("GET",
        `${P}/execution-runs/${encodeURIComponent(目标)}`, null, "U001");
      let 拒 = null;
      try {
        await 控[中文到键[不能的一个["动作"]]](目标, (详3 || {}).revision);
      } catch (e) { 拒 = e; }
      ck(`绕过界面直接做「${不能的一个["中文"]}」→ **服务端照样拒**`
         + "(界面藏起来只是提示,不是拦截)",
         拒 && (拒.码 === 409 || 拒.码 === 422),
         拒 && { 码: 拒.码, code: (拒.体 || {}).code });
    } else {
      ck("⚠️ 这一轮没有「不合法」的动作可试 —— **这一条没验到**(不是通过)",
         false, 动作们.map((a) => `${a["动作"]}=${a["现在能吗"]}`));
    }

    // ⚠️ **状态名不许前端翻译。**
    ck("服务端给的状态原样返回(**请求 ≠ 已经**:"
       + "`cancel_requested` 不是 `cancelled`,在途的调用未必立刻停)",
       typeof (r1 || {}).status === "string", (r1 || {}).status);
    // 源码级:页面不许自己写一份状态中文。
    const 页段 = src.slice(src.indexOf("function 运行控制按钮"),
                         src.indexOf("async function 页_运行详情"));
    const 自己翻的 = ["已暂停", "已取消", "已继续"].filter((w) => 页段.includes(w));
    ck("页面**没有自己翻译状态名**(编一套的话它和状态机会漂,"
       + "而漂的表现是**界面上说停了、实际还在跑**)",
       自己翻的.length === 0, 自己翻的);

    // 拿过期的 revision 再点一次 → 必须 409
    // ── ④ 核实外部状态:要幂等键,**不要** If-Match ─────────────────
    组("④ 核实外部状态:要幂等键,不要 If-Match");
    const r4 = await 控.核实(目标);
    ck("核实提交了", Boolean(r4), JSON.stringify(r4).slice(0, 90));
    const 请4 = 桩.头里(请求们, "/reconcile");
    ck("带了幂等键", 请4 && typeof 请4.头["Idempotency-Key"] === "string",
       请4 && 请4.头["Idempotency-Key"]);
    // ⚠️ 契约里这条**没有乐观锁**(它不改状态,只去问一次外部系统)。
    // 多带一个 If-Match 不会报错,但它会让下一个人以为这条也有乐观锁 ——
    // **一个多余的头,和一条错的文档是一回事**。
    ck("**没带 If-Match**(契约里这条没有乐观锁 —— 它不改状态,"
       + "只去问一次外部系统;多带一个头会让下一个人以为它有)",
       请4 && 请4.头["If-Match"] === undefined, 请4 && 请4.头);

    const 键们 = 请求们.filter((x) => x.头["Idempotency-Key"])
      .map((x) => x.头["Idempotency-Key"]);
    ck("每个动作都是**新的幂等键**", new Set(键们).size === 键们.length,
       { 发过: 键们.length, 不同: new Set(键们).size });
  } catch (e) {
    ck(`跑到「${状.走过[状.走过.length - 1] || "开头"}」就抛了:${e.message}`,
       false, (e.体 && JSON.stringify(e.体).slice(0, 160))
       || String(e.stack || "").slice(0, 180));
  } finally {
    // ⚠️ **不还原。** 这一份把一次运行推到了 `pause_requested`/`cancel_requested`,
    // 而那是**真实的状态流转** —— 硬改回去等于绕过状态机,
    // 而绕过状态机的测试证明不了状态机有用。
    // 它挑的是已有的非终态运行(不是自己造的),所以下一轮会挑到另一个;
    // 挑不到的时候上面那条断言会**明说这一组没验到**,不会混成绿的。
    console.log("\n▸ 收尾:**不还原** —— 推进状态是真实流转,"
      + "硬改回去等于绕过状态机,而绕过状态机的测试证明不了状态机有用");
    结束(弹过);
  }
})();
