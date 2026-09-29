/* 模型与连接那一页的两个动作**在页面代码里真走一遍**。
 *
 * ## 为什么要有它
 *
 * 和发布那一页同一个理由:**「接口对」和「页面把它接对了」是两件事。**
 * `page_smoke.js` 只证明取到数并渲染了,它不点任何东西。
 *
 * 这一页最容易错、而且错了最贵的地方:
 *
 * | 容易错的地方 | 错了会怎样 |
 * |---|---|
 * | 表单上摆一个**明文密钥**框 | 明文进过请求体就已经进过日志/APM/错误上报 |
 * | 用途和适配器在前端**硬编** | 和契约漂 —— 界面上少一个能用的或多一个不存在的,都不报错 |
 * | 探测漏了幂等键 | 探测要真打一次模型端点,**重发就是再花一次钱** |
 *
 * 第一条是这一份的核心。它不只断「页面没发明文」——
 * 还断**页面代码里根本没有那个输入框**:
 * 摆一个明文框再靠后端拒,等于把「已经出事了」往后挪一步。
 */
"use strict";
const fs = require("fs"), path = require("path");
const 桩 = require("./_页面桩.js");

const 项目 = 桩.默认项目;
const P = 桩.P(项目);
const src = fs.readFileSync(
  path.join(__dirname, "..", "..", "apps", "web", "app.js"), "utf8");

const 该跑几组 = 5;
const { ck, 组, 结束, 状 } = 桩.计分(该跑几组);

(async () => {
  console.log("\n\x1b[1m▸ 模型与连接:建连接 + 探 capabilities\x1b[0m");
  console.log("  ⚠️ 验的是**接线**和**表单里有没有不该有的口子**,不验界面长什么样");

  // admin 才有「配置密钥与预算」
  const { 请求们, 弹过 } = 桩.装桩({ hash: "#/conns", 我: "U001", 项目 });
  try { 桩.跑页面(src); } catch (e) {
    ck("app.js 同步执行不挂", false, e.message); 结束(弹过); return;
  }
  const 动 = globalThis.连接动作;
  ck("app.js 把 `连接动作` 导出来了", 动 && typeof 动.建 === "function"
     && typeof 动.探 === "function", 动 ? Object.keys(动) : null);
  if (!动) { 结束(弹过); return; }

  try {
    // ── ① 表单里**没有明文密钥的口子** ──────────────────────────────
    组("① 表单里没有明文密钥的输入框(**源码级断言**)");
    // ⚠️ 这一条是**看源码**,不是看请求。理由:
    // 「页面这一次没发明文」和「页面根本没法发明文」是两件事,
    // 而前者在下一个人加一个字段那天就不成立了。
    // ⚠️ 这一组的判据**改过一版,两条都栽在同一件事上:盯了词,没盯结构。**
    //
    //   ① 找 `secret_ref` 找不到 —— 它在**事件处理**里,表单 HTML 里只有
    //      placeholder。切片切窄了。
    //   ② 找「明文」命中的是**那句警告文案本身**(「明文一旦进过请求体…」)——
    //      判据把警告当成了违规。
    //
    // > 枚举中文短语去判「有没有某个意思」**必输** —— 这个仓库栽过七次。
    //
    // 所以改成盯结构:**把表单里所有 `<input id="...">` 的 id 列出来**,
    // 断言没有一个是凭据类的。它不会命中文案,而且下一个人加一个明文框
    // 一定会被它抓到(那个框必须有 id 才能被读值)。
    // ⚠️ 这一条**不切片**。切片按函数名找边界,这一轮咬了我三次
    // (字段名在事件处理里而我切到了表单为止;`报2` 排在 `挂连接事件` 前面
    //  而我以为它在后面)。而它是个**正向**断言 ——
    // 「页面用的是引用字段」在整个 app.js 里查一次就够,不需要定位。
    // > 判据能不切片就不切片:切错了边界的表现是**红得毫无道理**,
    // > 而人会花时间去查被测的那一半。
    ck("页面用的是 `secret_ref`(**引用**,不是密钥本身)",
       src.includes("secret_ref"), src.includes("secret_ref"));

    const 表单段 = src.slice(src.indexOf("function 页_连接表单"),
                           src.indexOf("async function 页_模型与连接"));
    const input们 = [...表单段.matchAll(/<input\s+id="([^"]+)"/g)].map((m) => m[1]);
    ck("表单里的输入框都数出来了(数不出来的话下面那条是空跑 ——"
       + "**正则改坏了和「没有明文框」长得一模一样**)",
       input们.length >= 3, input们);
    // 页面用 `$("#c-xx").value` 读值,所以每个能被读的框都有 id。
    // 凭据类的 id 会长什么样:带 key/secret 值/pass/token/明文 的。
    // ⚠️ `c-sr` 是**引用**那个框,它读到的值是 `secret://...`,不是密钥本身 ——
    // 所以按 id 判会误伤它。改成:**去掉引用那个,剩下的一个都不许像凭据**。
    const 疑似凭据 = input们.filter((i) => i !== "c-sr"
      && /key|secret|pass|token|cred/i.test(i));
    ck("**除了那个「引用」框,没有任何一个像凭据的输入框**"
       + "(摆一个再靠后端拒,等于把「已经出事了」往后挪一步)",
       疑似凭据.length === 0, { 所有框: input们, 疑似: 疑似凭据 });
    ck("界面上**明说**了这件事(不说的话,人会去别处找那个框)",
       表单段.includes("只收引用") || 表单段.includes("不是密钥本身"),
       表单段.includes("不是密钥本身"));

    // ── ② 选项从接口来,不在前端硬编 ─────────────────────────────────
    组("② 用途和适配器的选项**从接口来**");
    const [码, d] = await 桩.直打("GET", `${P}/model-connections`, null, "U001");
    ck("接口给了 `可选用途`", 码 === 200 && Array.isArray((d || {})["可选用途"]),
       ((d || {})["可选用途"] || []).map((x) => x["值"]));
    ck("接口给了 `适配器怎么填`,而且**明说它不是穷尽清单**"
       + "(画成下拉框会让人以为不在里面的就不能用)",
       Boolean(((d || {})["适配器怎么填"] || {})["⚠️"]),
       (((d || {})["适配器怎么填"] || {})["⚠️"] || "").slice(0, 40));
    // ⚠️ 源码级:页面不许自己写一份用途清单。
    const 页段 = src.slice(src.indexOf("function 页_连接表单"),
                         src.indexOf("function 挂连接事件"));
    const 硬编 = ["generate", "embed", "rerank", "finetune_infer"]
      .filter((u) => 页段.includes(`"${u}"`));
    ck("页面**没有硬编**那四个用途(硬编的话它和契约会漂,"
       + "而漂的表现是界面上少一个能用的或多一个不存在的 —— 都不报错)",
       硬编.length === 0, 硬编);

    // ── ③ 建连接:明文当场被拒,而且拒的理由指到字段上 ──────────────────
    组("③ 明文凭据 → 当场被拒");
    let 拒 = null;
    try {
      await 动.建({ 用途: "rerank", 适配器: "MockModelProvider",
                  endpoint: "mock://x", secret_ref: "secret://ok",
                  api_key: "这是一个不该出现在请求体里的值" });
    } catch (e) { 拒 = e; }
    ck("请求体里带一个像明文凭据的字段 → **422**",
       拒 && 拒.码 === 422, 拒 && { 码: 拒.码, code: (拒.体 || {}).code });
    const 闸 = 拒 && (((拒.体 || {}).field_errors || {})["闸"] || []);
    ck("而且**逐条说清为什么**(「换个字段名重发也救不回来那一次」)",
       闸 && 闸.length > 0 && 闸.some((x) => x.includes("日志") || x.includes("凭据")),
       闸 && 闸[0] && 闸[0].slice(0, 60));
    // ⚠️ **拒的位置也要断。** 如果它是先插了库再拒,那已经晚了。
    const [码2, d2] = await 桩.直打("GET", `${P}/model-connections`, null, "U001");
    ck("被拒之后**库里没有多出一条**(先写后拒等于已经出事了)",
       (d2 || {})["条数"] === (d || {})["条数"],
       { 之前: (d || {})["条数"], 之后: (d2 || {})["条数"] });

    // ── ④ 建连接:正常路径 ────────────────────────────────────────
    组("④ 建一条连接(挑一个还没被占的用途)");
    const 空的 = ((d || {})["可选用途"] || []).find((u) => !u["这个项目占了吗"]);
    ck("找得到一个还没被占的用途(找不到的话下面几条是空跑)", Boolean(空的),
       空的 && 空的["值"]);
    let 新id = null;
    if (空的) {
      const r = await 动.建({
        用途: 空的["值"], 适配器: "MockModelProvider",
        endpoint: "mock://页面接线测试", secret_ref: "secret://none",
        名字: `页面接线-${Math.random().toString(16).slice(2, 8)}`,
      });
      新id = r && r.id;
      ck("建好了,拿到 id", Boolean(新id), 新id);
      const 请 = 桩.头里(请求们, "/model-connections");
      ck("请求体里**只有 `secret_ref`,没有别的像凭据的键**",
         请 && !/api_key|password|token/i.test(String(请.体 || "")),
         请 && String(请.体 || "").slice(0, 90));
      // 同一个用途再建一条 → 409
      let 撞 = null;
      try {
        await 动.建({ 用途: 空的["值"], 适配器: "MockModelProvider",
                    endpoint: "mock://x2", secret_ref: "secret://none" });
      } catch (e) { 撞 = e; }
      ck("同一个用途再建一条 → **409 PURPOSE_TAKEN**",
         撞 && 撞.码 === 409 && (撞.体 || {}).code === "PURPOSE_TAKEN",
         撞 && { 码: 撞.码, code: (撞.体 || {}).code });
    }

    // ── ⑤ 探 capabilities:要幂等键 ───────────────────────────────
    组("⑤ 探 capabilities(要真打一次端点,所以要幂等键)");
    if (新id) {
      const r = await 动.探(新id);
      ck("探测提交了", Boolean(r), JSON.stringify(r).slice(0, 80));
      const 请 = 桩.头里(请求们, "/probe");
      ck("**带了幂等键**(探测要真打一次模型端点,重发就是再花一次钱)",
         请 && typeof 请.头["Idempotency-Key"] === "string",
         请 && 请.头["Idempotency-Key"]);
      const 键们 = 请求们.filter((x) => x.头["Idempotency-Key"])
        .map((x) => x.头["Idempotency-Key"]);
      ck("每次都是**新的键**", new Set(键们).size === 键们.length,
         { 发过: 键们.length, 不同: new Set(键们).size });
    } else {
      ck("⚠️ 没建出连接,这一组**没验到**(不是通过)", false, "上一组没拿到 id");
    }
  } catch (e) {
    ck(`跑到「${状.走过[状.走过.length - 1] || "开头"}」就抛了:${e.message}`,
       false, (e.体 && JSON.stringify(e.体).slice(0, 160)) || String(e.stack || "").slice(0, 180));
  } finally {
    // 收尾:把造的那条归档掉 —— 否则下一轮那个用途就被占了,
    // 而「找不到空用途」会让第 ④ ⑤ 组变成空跑。
    // ⚠️ 这个后台没有硬删接口(有意的),所以直接改库。
    const { execSync } = require("child_process");
    try {
      execSync(`./.venv/bin/python -c "
import os,sys
sys.path.insert(0, os.path.join('services','api','app'))
from sqlalchemy import text
from db import 事务
with 事务() as c:
    c.execute(text(\\"\\"\\"delete from connection_versions where project_id=:p
        and connection_id in (select id from model_connections
          where project_id=:p and display_name like '页面接线-%')\\"\\"\\"),
        {'p': '${项目}'})
    n = c.execute(text(\\"\\"\\"delete from model_connections where project_id=:p
        and display_name like '页面接线-%'\\"\\"\\"), {'p': '${项目}'}).rowcount
print('清掉', n, '条')
"`, { cwd: path.join(__dirname, "..", ".."), stdio: "pipe" });
      console.log("\n▸ 收尾:造的连接清掉了(不清的话那个用途下一轮就被占着,"
        + "而「找不到空用途」会让后两组变成空跑)");
    } catch (e) {
      console.log("\n  ⚠️ 收尾没清干净:" + String(e.message).slice(0, 120));
      状.挂.push("收尾没清干净");
    }
    结束(弹过);
  }
})();
