/* 工具那两页的三个动作**在页面代码里真走一遍**。
 *
 * ## 这一页最值钱的一条:**风险变大必须出新版本**
 *
 * 一个工具从「只读」改成「会写」,而引用它的 Agent **还指着老版本的说明** ——
 * 那份说明现在是错的。闸在服务端(`可以冻结工具吗`),
 * 而这一页要做的是**把那个结论显示出来,不自己比两个等级**:
 * 自己比的话那条规矩就变成每个前端各实现一遍,
 * 而**不一致的表现是界面上少一句警告**。
 *
 * ## 还有一条安全形状:**表单里没有「代码」输入框**
 *
 * `POST /tools` **不收可执行代码** —— 适配器是仓库里已有的实现。
 * 和模型连接那一页「只收引用不收明文」同一个形状:
 * **界面上不开那个口子,而不是开了再靠后端拒。**
 *
 * ## 接线那一半
 *
 * | 容易错的地方 | 错了会怎样 |
 * |---|---|
 * | 改草稿拿 `revision` 当 If-Match | 两个数在工具上**一直相等**,所以**拿错也不报错** |
 * | 读写类型在前端硬编 | 和白名单漂 —— 少一个能选的或多一个会被 422 拒的 |
 */
"use strict";
const fs = require("fs"), path = require("path");
const 桩 = require("./_页面桩.js");

const 项目 = 桩.默认项目;
const P = 桩.P(项目);
const 根 = path.join(__dirname, "..", "..");
const src = fs.readFileSync(path.join(根, "apps", "web", "app.js"), "utf8");

const 该跑几组 = 6;
const { ck, 组, 结束, 状 } = 桩.计分(该跑几组);

const 尾 = Math.random().toString(16).slice(2, 8);
const 工具名 = `页面接线工具-${尾}`;

(async () => {
  console.log("\n\x1b[1m▸ 工具:注册 / 改草稿 / 冻结版本\x1b[0m");
  console.log("  ⚠️ 最值钱的一条是**风险变大必须出新版本** —— "
    + "而这一页只负责显示那个结论,不自己比两个等级");

  // editor 才有「改编排草稿」
  const { 请求们, 弹过 } = 桩.装桩({ hash: "#/tools", 我: "U002", 项目 });
  try { 桩.跑页面(src); } catch (e) {
    ck("app.js 同步执行不挂", false, e.message); 结束(弹过); return;
  }
  const 动 = globalThis.工具动作;
  ck("app.js 把 `工具动作` 导出来了",
     动 && ["注册", "改草稿", "冻结版本"].every((k) => typeof 动[k] === "function"),
     动 ? Object.keys(动) : null);
  if (!动) { 结束(弹过); return; }

  let tid = null;
  try {
    // ── ① 表单里没有「代码」口子 + 选项由接口给 ───────────────────────
    组("① 表单里没有「代码」输入框,选项由接口给");
    const 表单段 = src.slice(src.indexOf("function 页_工具表单"),
                           src.indexOf("async function 页_工具详情"));
    const input们 = [...表单段.matchAll(/<input\s+id="([^"]+)"/g)].map((m) => m[1]);
    ck("表单里的输入框都数出来了(数不出来的话下面那条是空跑)",
       input们.length >= 3, input们);
    // ⚠️ 盯**结构**(input 的 id),不盯词 —— 这一轮在连接那一页栽过:
    // 找「明文」命中的是那句警告文案本身。
    const 像代码的 = input们.filter((i) => /code|script|body|源|代码|exec/i.test(i));
    ck("**没有任何一个像「代码」的输入框**"
       + "(接口不收可执行代码 —— 界面上也不开那个口子)",
       像代码的.length === 0, { 所有框: input们, 疑似: 像代码的 });

    const [码D, 目录] = await 桩.直打("GET", `${P}/tools`, null, "U002");
    ck("接口给了 `可选读写类型`",
       码D === 200 && Array.isArray((目录 || {})["可选读写类型"]),
       ((目录 || {})["可选读写类型"] || []).map((x) => x["值"]));
    ck("也给了 `接入方式怎么填`,而且**明说它不是穷尽清单**",
       Boolean(((目录 || {})["接入方式怎么填"] || {})["⚠️"]),
       (((目录 || {})["接入方式怎么填"] || {})["⚠️"] || "").slice(0, 36));
    // 源码级:页面不许硬编那三档
    const 页全段 = src.slice(src.indexOf("const 工具动作 = {"),
                           src.indexOf("async function 页_工具目录"));
    const 硬编 = ["read_only", "write", "irreversible"]
      .filter((x) => 页全段.includes(`"${x}"`));
    ck("页面**没有硬编**那三档读写类型(硬编会和白名单漂)", 硬编.length === 0, 硬编);

    // ── ② 注册:**没标级别的不许进来** ──────────────────────────────
    组("② 注册工具(没标级别的一律被挡住)");
    let 无级 = null;
    try {
      await 动.注册({ 名称: 工具名 + "-无级", 接入方式: "MockSearch" });
    } catch (e) { 无级 = e; }
    ck("不给读写类型 → **422**(没标级别的工具一律被网关挡住 —— 未知不等于安全)",
       无级 && 无级.码 === 422, 无级 && { 码: 无级.码, code: (无级.体 || {}).code });
    let 无适配 = null;
    try {
      await 动.注册({ 名称: 工具名 + "-无适", 读写类型: "read_only" });
    } catch (e) { 无适配 = e; }
    ck("不给接入方式 → **422**,而且说清「接口不收可执行代码」",
       无适配 && 无适配.码 === 422
       && /可执行代码/.test(JSON.stringify(无适配.体 || {})),
       无适配 && (无适配.体 || {}).advice);

    const r = await 动.注册({ 名称: 工具名, 用途: "页面接线测试用",
                            读写类型: "read_only", 接入方式: "MockSearch" });
    tid = r && r.id;
    ck("正常注册 → 拿到 id,而且**从只读起**", Boolean(tid), { id: tid });

    // ── ③ 改草稿:认 draft_revision,**不是 revision** ───────────────
    组("③ 改草稿:认 `draft_revision`");
    const [, 详] = await 桩.直打("GET", `${P}/tools/${tid}`, null, "U002");
    ck("详情给了 `draft_revision`(**改草稿的 If-Match 认这个**)",
       typeof (详 || {})["draft_revision"] === "number",
       { draft_revision: (详 || {})["draft_revision"],
         revision: (详 || {})["revision"] });
    // ⚠️ 这两个数在工具上**一直相等**(同一个 UPDATE 里一起涨),
    // 所以拿错也不会报错 —— 运行时拦不住,只能靠 note 明说该用哪一个。
    ck("note 里**明说认哪一个**(两个数一直相等 —— 拿错不会报错,"
       + "这是唯一的防线)",
       /draft_revision/.test((详 || {}).note || ""),
       ((详 || {}).note || "").slice(0, 60));
    let 空 = null;
    try { await 动.改草稿(tid, { 用途: "x" }, null); } catch (e) { 空 = e; }
    ck("draft_revision 为 null → **当场本地报错,不发请求**",
       空 && (空.体 || {}).code === "NO_DRAFT_REVISION", 空 && (空.体 || {}).code);

    const d1 = await 动.改草稿(tid, { 用途: "改过的用途" },
                            (详 || {})["draft_revision"]);
    ck("改草稿 → draft_revision 涨了",
       (d1 || {})["draft_revision"] === (详 || {})["draft_revision"] + 1,
       { 之前: (详 || {})["draft_revision"], 之后: (d1 || {})["draft_revision"] });
    const 请1 = 桩.头里(请求们, `/tools/${tid}/draft`);
    ck("带的 If-Match 就是 `draft_revision`",
       请1 && 请1.头["If-Match"] === String((详 || {})["draft_revision"]),
       { 带的: 请1 && 请1.头["If-Match"], 该带: (详 || {})["draft_revision"] });

    // ── ④ 风险变大 → 冻结时必须出新版本 ──────────────────────────────
    组("④ 只读 → 会写:**风险变大必须出新版本**");
    // 先冻结一版(只读),这样才有「上一版」可比 ——
    // ⚠️ 没有上一版的时候 `风险变大了吗` 恒为 false,
    // 那时候这一组会**变成空跑**,所以这一步不能省。
    // ⚠️ **冻结要一张表单,不是一个说明。** 闸要的是:给模型的说明、
    // 入参 schema、(会写的工具还要)幂等策略 —— 它们是**版本的内容**,
    // 不是工具的属性,所以每次冻结都要重新给。
    // (第一版我只传了一个「变更说明」,而那个字段**接口压根不收** ——
    //  一个被静默忽略的入参,和一个生效了的入参,在响应上长得一模一样。)
    const v1 = await 动.冻结版本(tid, {
      给模型的说明: "搜一下知识库,只读",
      入参: { type: "object", properties: { q: { type: "string" } } },
    });
    ck("先冻结一版只读(**没有上一版时「风险变大」恒为 false** —— "
       + "少了这一步,下面几条就是空跑)",
       Boolean(v1), JSON.stringify(v1).slice(0, 90));
    const [, 详2] = await 桩.直打("GET", `${P}/tools/${tid}`, null, "U002");
    ck("这时候 `风险变大了吗` = false(草稿和冻结版一样)",
       (详2 || {})["风险变大了吗"] === false, (详2 || {})["风险变大了吗"]);

    const d2 = await 动.改草稿(tid, { 读写类型: "write" },
                            (详2 || {})["draft_revision"]);
    ck("把草稿改成「写入」→ **服务端当场说风险变大了**"
       + "(这个结论由服务端算 —— 前端自己比两个等级的话,"
       + "那条规矩就变成每个前端各实现一遍)",
       (d2 || {})["风险变大了吗"] === true, (d2 || {})["风险变大了吗"]);
    const [, 详3] = await 桩.直打("GET", `${P}/tools/${tid}`, null, "U002");
    ck("详情接口也这么说(两处口径一致 —— 不一致的表现是界面上少一句警告)",
       (详3 || {})["风险变大了吗"] === true, (详3 || {})["风险变大了吗"]);
    // 源码级:页面显示的是服务端那个字段,不是自己比出来的
    const 详段 = src.slice(src.indexOf("async function 画工具详情"),
                         src.indexOf("function 报工具("));
    ck("页面读的是服务端那个 `风险变大了吗` 字段,**不自己比等级**",
       详段.includes('d["风险变大了吗"]')
       && !/read_only[\s\S]{0,80}irreversible/.test(详段),
       详段.includes('d["风险变大了吗"]'));

    // ⚠️ 这一版是**会写**的 —— 所以必须给幂等策略。
    // 不给的话闸会拦住,而那正是它该做的事:
    // **会写的工具没有幂等策略,超时重发就是写两次**。
    let 没幂等 = null;
    try {
      await 动.冻结版本(tid, { 给模型的说明: "改成会写了",
                            入参: { type: "object", properties: {} } });
    } catch (e) { 没幂等 = e; }
    ck("会写的工具**不给幂等策略 → 被拦**"
       + "(超时重发就是写两次,而两次都「成功」)",
       没幂等 && 没幂等.码 === 422
       && /幂等/.test(JSON.stringify(没幂等.体 || {})),
       没幂等 && (((没幂等.体 || {}).field_errors || {})["闸"] || [])[0]);
    const v2 = await 动.冻结版本(tid, {
      给模型的说明: "改成会写了",
      入参: { type: "object", properties: { path: { type: "string" } } },
      幂等策略: "按 (工具, 对象, 执行键) 去重",
    });
    ck("冻结 → **出了新版本**(不是原地改旧版本 —— "
       + "改旧版本的话引用它的 Agent 会突然指着一个会写的工具)",
       Boolean(v2), JSON.stringify(v2).slice(0, 110));
    const [, 详4] = await 桩.直打("GET", `${P}/tools/${tid}`, null, "U002");
    ck("版本历史里**两版都在**,而且读写类型不同",
       ((详4 || {})["版本历史"] || []).length === 2
       && new Set(((详4 || {})["版本历史"] || [])
            .map((x) => x["读写类型"])).size === 2,
       ((详4 || {})["版本历史"] || []).map((x) => `${x["版本"]}=${x["读写类型"]}`));

    // ── ⑤ Schema 关键字清单:**页面用接口给的那一份,不硬编** ──────────
    //
    // ⚠️ 第一版我把这一组插在 `finally` 里(收尾之后)——
    // 而收尾已经把那个工具清掉了,于是接口返回 0 个关键字,
    // 报出来是「接口没给」。**而接口给得好好的。**
    // > 一个插在收尾之后的断言,它量的是「清理干净了吗」,
    // > 不是它想量的那件事 —— 而两者在失败信息上长得一样。
    组("⑤ 那份 Schema 关键字清单,**真的渲进页面了吗**");
    const 清单 = (详4 || {})["可用的Schema关键字"] || [];
    ck("接口给了 `可用的Schema关键字`(对照:下面几条才有意义)",
       清单.length >= 8, 清单.length);
    // ⚠️ **这一条是这一组的要点。**
    // 10-02 后端给出了那份清单 + 一句「别硬编」,而**当天没有任何界面在用它** ——
    // > 一个给出来却没人用的字段,和没给,**在界面上长得一样**。
    // 所以这里断「它真的印在页面上」,不是「接口给了」。
    // ⚠️ **这个测试装桩时 hash 是 `#/tools`(列表页)—— 详情页没被渲过。**
    // 第一版我直接读 `#tdbody`,拿到空串,报出来是「页面上没有那些关键字」。
    // > 一条验「详情页渲了什么」的断言,放在一个不渲染详情页的测试里 ——
    // > 它报的是「页面上没有」,**而页面根本没被渲过**。
    // 所以这里**真渲一遍**(`app.js` 为此暴露了 `画工具详情`)。
    //
    // 桩提供的是 `document.querySelector("#id")`,**没有 `getElementById`** ——
    // 第一版我用了后者,`is not a function`。
    if (typeof globalThis.画工具详情 !== "function") {
      ck("app.js 把 `画工具详情` 暴露出来了(**验渲染要有入口**)", false, null);
    } else {
      await globalThis.画工具详情(tid);
    }
    const 主 = document.querySelector("#tdbody");
    const 页文 = (主 && 主.innerHTML) || "";
    const 渲出来的 = 清单.filter((k) => 页文.includes(k));
    ck("**清单里的每一个都出现在页面上**"
       + "(「渲染了」不等于「渲的是那些东西」)",
       清单.length > 0 && 渲出来的.length === 清单.length,
       `${渲出来的.length}/${清单.length}`);
    ck("页面上说了「**界面不硬编**」(说明在,下一个人才知道不该抄一份)",
       页文.includes("不硬编"), 页文.includes("不硬编"));
    // ⚠️ **源码级:页面里不许写死关键字清单。**
    // 渲出来了不代表它是从接口来的 —— 一份硬编的清单也会渲出来,
    // 而它会和后端漂。所以这一条盯的是**源码**。
    const 页段 = src.slice(src.indexOf("async function 画工具详情("),
                         src.indexOf("async function 页_工具目录("));
    const 硬编了 = ["minLength", "maxItems", "additionalProperties"]
      .filter((k) => 页段.includes(`"${k}"`) || 页段.includes(`'${k}'`));
    // ── ⑥ 规格 §8.2 那两页的内容,**而且凭据不许上页面** ──────────────
    组("⑥ 「输入与输出」和「执行与权限」两页,**凭据不许渲上去**");
    // ⚠️ **自己造一版带凭据的。** 库里一条 `secret_ref` 非空的版本都没有 ——
    // 不造的话下面那条「页面上找不到凭据」是**空跑**:
    // **空集合上所有性质都成立。**
    const 假凭据 = `keychain://页面接线-${Date.now()}`;
    await 动.冻结版本(tid, {
      给模型的说明: "带凭据的一版,用来验凭据不上页面",
      入参: { type: "object", properties: { q: { type: "string" } } },
      幂等策略: "按 (工具, 对象, 执行键) 去重",
      secret_ref: 假凭据,
    });
    await globalThis.画工具详情(tid);
    const 页文2 = (document.querySelector("#tdbody") || {}).innerHTML || "";
    ck("页面渲出了「执行与权限」那一段(对照:下面几条才有意义)",
       页文2.includes("执行与权限"), 页文2.includes("执行与权限"));
    ck("渲出了「输入与输出」那一段", 页文2.includes("输入与输出"),
       页文2.includes("输入与输出"));
    ck("页面上说了**服务端绑定的参数单独一栏**"
       + "(并排摆会让人以为它们一样,于是有人把该服务端绑的字段写进入参)",
       页文2.includes("服务端绑定"), 页文2.includes("服务端绑定"));
    ck("页面上标了**配了凭据**(而不是什么都不说)",
       页文2.includes("配了凭据"), 页文2.includes("配了凭据"));
    // ⚠️⚠️ **这一条是红线断言。**
    // 如果哪天有人把 `secret_ref` 的**值**渲上去,页面看起来只是
    // 「多显示了一点信息」—— 而那是一条凭据泄漏,
    // **没有任何东西会红**。所以这条必须在。
    ck("**那个凭据引用一个字都没出现在页面上**"
       + "(渲上去的话页面看起来只是「多显示了一点信息」—— "
       + "而那是一条凭据泄漏,没有任何东西会红)",
       !页文2.includes(假凭据) && !页文2.includes("keychain://"),
       页文2.includes("keychain://") ? "⚠️ 页面上有 keychain:// 串" : "干净");
    // 顺带:接口那一层也不许给。
    const [, 详6] = await 桩.直打("GET", `${P}/tools/${tid}`, null, "U002");
    ck("**接口的返回里也没有那个串**(页面干净可能只是页面没渲它)",
       !JSON.stringify(详6 || {}).includes(假凭据),
       JSON.stringify(详6 || {}).includes("keychain://") ? "⚠️ 接口给了" : "干净");
    ck("而接口确实给了「配了凭据吗」这个布尔"
       + "(**只报配没配,不给值** —— 两件事都要成立)",
       ((详6 || {})["版本历史"] || [])[0]?.["配了凭据吗"] === true,
       ((详6 || {})["版本历史"] || [])[0]?.["配了凭据吗"]);
    ck("**明写了「凭据不出返回值」**(说明在,下一个人才知道这是红线)",
       Boolean((详6 || {})["⚠️凭据不出返回值"]),
       String((详6 || {})["⚠️凭据不出返回值"] || "").slice(0, 40));
    ck("页面上明写了**还没做哪三个页签**"
       + "(空壳子让人以为「这里没东西」,而真相是「这里还没做」)",
       页文2.includes("还没做的三个") || 页文2.includes("配套关系"),
       页文2.includes("还没做的三个"));

    ck("页面源码里**没有写死**那些关键字"
       + "(硬编的那份会和后端漂,而漂开时界面放过去的 Schema "
       + "会在模型第一次真的调用那一刻才失败)",
       硬编了.length === 0, 硬编了);
  } catch (e) {
    ck(`跑到「${状.走过[状.走过.length - 1] || "开头"}」就抛了:${e.message}`,
       false, (e.体 && JSON.stringify(e.体).slice(0, 160))
       || String(e.stack || "").slice(0, 180));
  } finally {
    // 收尾:把自己造的工具连同版本一起清掉。
    // ⚠️ **自己建的自己清** —— 不清的话工具目录会越跑越长,
    // 而「工具数」那一栏是别的页面在用的数。
    const { execSync } = require("child_process");
    try {
      execSync(`./.venv/bin/python -c "
import os,sys
sys.path.insert(0, os.path.join('services','api','app'))
from sqlalchemy import text
from db import 事务
with 事务() as c:
    c.execute(text(\\"\\"\\"delete from tool_versions where project_id=:p
        and tool_definition_id in (select id from tool_definitions
          where project_id=:p and name like :n)\\"\\"\\"),
        {'p': '${项目}', 'n': '页面接线工具-%'})
    n = c.execute(text(\\"\\"\\"delete from tool_definitions where project_id=:p
        and name like :n\\"\\"\\"), {'p': '${项目}', 'n': '页面接线工具-%'}).rowcount
print('清掉', n)
"`, { cwd: 根, stdio: "pipe" });
      console.log("\n▸ 收尾:造的工具连版本一起清了"
        + "(不清的话工具目录越跑越长,而「工具数」是别的页面在用的数)");
    } catch (e) {
      console.log("\n  ⚠️ 收尾没清干净:" + String(e.message).slice(0, 120));
      状.挂.push("收尾没清干净");
    }
    结束(弹过);
  }
})();
