/* 页面动作驱动的共享桩。**给「点一下会发什么请求」那一类测试用。**
 *
 * ## 为什么抽出来
 *
 * `test_release_page_actions.js` 里原来自带一份最小 DOM 桩,而
 * `page_smoke.js` 里还有一份。**再加一页就是第三份。**
 * 三份副本一定会漂,而漂的表现很坏:
 * 某一份的 `crypto.randomUUID` 桩成了常量(page_smoke 那份就是 ——
 * 它只加载不写,所以无所谓),而驱动测试拿它去发两次发布动作,
 * 第二次会命中第一次的幂等记录 ——
 * **于是「幂等生效了」和「我的桩坏了」长得一模一样。**
 *
 * 所以:驱动类测试一律用这一份。`page_smoke.js` 保留它自己那份 ——
 * 它多了「写过哪些节点 / 实质内容多少字」那套结构对账,
 * 而那是另一件事(加载路径),不该和这份混。
 *
 * ## 它给什么
 *
 *   `装桩({hash, 我, 项目})`  → 把 global 布置好,返回 { 池, 请求们, 取 }
 *   `跑页面(src)`             → `new Function(src)()`,把 app.js 跑起来
 *   `头里(请求们, 片段)`       → 最后一次打到某个地址的请求(连头一起)
 *   `直打(方法, 路, 体, 谁)`   → 绕过页面代码直接打接口(造夹具/核对结果用)
 *
 * ## ⚠️ 它**不**给什么
 *
 * - **不建模嵌套 DOM**:`querySelectorAll` 返回空数组。
 *   所以按钮点不到 —— 驱动测试是**直接调页面导出的动作函数**,
 *   不是模拟点击。这正是那些动作要从 onclick 里抽出来的原因。
 * - **不验界面长什么样**。渲染那一半是 `page_smoke.js` 和真浏览器那一份。
 */
"use strict";

const 基址 = process.env.AIMC_BASE || "http://127.0.0.1:8801";
const 默认项目 = process.env.AIMC_PROJECT || "project_demo_a";

function 造(id) {
  return {
    id, value: "", textContent: "", style: {}, dataset: {}, disabled: false,
    className: "", classList: { add() {}, remove() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {},
    querySelectorAll: () => [], querySelector: () => null, focus() {},
    set innerHTML(v) { this._h = String(v); }, get innerHTML() { return this._h || ""; },
  };
}

function 装桩(opt = {}) {
  const 池 = new Map();
  const 取 = (sel) => {
    const id = String(sel).replace(/^#/, "");
    if (!池.has(id)) 池.set(id, 造(id));
    return 池.get(id);
  };
  global.document = {
    querySelector: 取, querySelectorAll: () => [],
    body: { classList: { add() {}, remove() {}, contains: () => false } },
    createElement: () => 造("new"), addEventListener() {},
  };
  global.window = { addEventListener() {} };
  global.location = { hash: opt.hash || "#/workbench" };
  global.localStorage = {
    _d: { "aimc.user": opt.我 || "U002", "aimc.proj": opt.项目 || 默认项目 },
    getItem(k) { return this._d[k] ?? null; },
    setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
  };
  /* ⚠️ **幂等键不能桩成常量。** page_smoke 那份桩成了固定值(它只加载不写,
   * 所以无所谓);驱动测试真的会发两次写动作,固定值会让第二次命中
   * 第一次的幂等记录 —— 于是「幂等生效了」和「我的桩坏了」长得一模一样。 */
  /* ⚠️ **`crypto` 要用 defineProperty,不能直接赋值。**
   * Node 24 把 `globalThis.crypto` 定义成**只有 getter 的访问器属性**,
   * 而这个文件是严格模式 → 直接赋值当场抛 `TypeError`。
   * `test_release_page_actions.js`(没有 "use strict")里同样一行**静默成功**了 ——
   * 也就是说那份桩其实**没有替换掉 crypto**,用的是 Node 自带的那个。
   * 那一份碰巧没事(真 randomUUID 也是随机的),但这件事值得记:
   * **非严格模式下一个失败的赋值不报错,只是什么都没发生。** */
  Object.defineProperty(global, "crypto", {
    value: {
      randomUUID: () => "k" + Date.now().toString(16)
        + Math.random().toString(16).slice(2, 10),
    },
    configurable: true, writable: true,
  });
  /* ⚠️ 模态框一律记成**错**,不静默吞掉。
   * 一个 `confirm()` 在真浏览器里会挡住自动化,而在桩里默认返回 true 的话
   * 它**一声不响地通过** —— 于是「这里没有模态框」这件事从来没被验过。 */
  const 弹过 = [];
  global.alert = (m) => { 弹过.push("alert:" + m); };
  global.confirm = (m) => { 弹过.push("confirm:" + m); return true; };
  global.prompt = (m) => { 弹过.push("prompt:" + m); return null; };

  const realFetch = global.fetch;
  _真fetch = realFetch;          // 给 `直打` 用 —— 见下面那段注释
  const 请求们 = [];
  global.fetch = (u, o) => {
    const url = String(u);
    请求们.push({
      方法: (o && o.method) || "GET", 地址: url,
      头: Object.assign({}, (o && o.headers) || {}),
      体: (o && o.body) || null,
    });
    return realFetch(url.startsWith("http") ? url : 基址 + url, o);
  };
  return { 池, 取, 请求们, 弹过, realFetch };
}

function 跑页面(src) {
  // eslint-disable-next-line no-new-func
  new Function(src)();
}

/** 最后一次打到 `片段` 的请求(连头和体一起)。`n=2` 是倒数第二次。 */
function 头里(请求们, 片段, n) {
  const 命中 = 请求们.filter((r) => r.地址.includes(片段));
  return 命中.length ? 命中[命中.length - (n || 1)] : null;
}

let _真fetch = null;

/** 绕过页面代码直接打接口 —— 造夹具、核对结果用。返回 [状态码, 体]。
 *
 * ⚠️ **它走的是真 fetch,不进 `请求们`。** 走记录版的话,造夹具的那些请求
 * 会混进账本里,而这份测试的判据一多半是「最后一次打某个地址带了什么头」——
 * 混进去之后那些判据会指着**夹具的请求**说话,而它们看起来完全正常。
 */
async function 直打(方法, 路, 体, 谁, 头) {
  const h = Object.assign({ "X-Dev-User": 谁 || "U002" }, 头 || {});
  if (体) h["content-type"] = "application/json";
  const 全 = 路.startsWith("http") ? 路 : 基址 + 路;
  const f = _真fetch || fetch;
  const r = await f(全, {
    method: 方法, headers: h, body: 体 ? JSON.stringify(体) : undefined,
  });
  let b = null;
  try { b = await r.json(); } catch (e) { b = null; }
  return [r.status, b];
}

/** 项目前缀。 */
const P = (项目) => `/api/v1/projects/${项目 || 默认项目}`;

/** 计分板。`该跑几组` 是**手写的字面量**,少跑一组就红 ——
 * 「跳过了」和「通过了」必须长得不一样。 */
function 计分(该跑几组) {
  const 状 = { 过: 0, 挂: [], 走过: [] };
  return {
    状,
    ck(名, 真, 补) {
      const 补文 = 补 === undefined ? "" : "  " + String(
        typeof 补 === "object" ? JSON.stringify(补) : 补).slice(0, 150);
      console.log(`  ${真 ? "✅" : "❌"} ${名}${补文}`);
      if (真) 状.过++; else 状.挂.push(名);
    },
    组(名) { 状.走过.push(名); console.log(`\n▸ ${名}`); },
    结束(弹过) {
      console.log("");
      if (弹过 && 弹过.length) {
        // ⚠️ 模态框要**明说**。它在真浏览器里会挡住自动化,
        // 而这些页面正是要被冒烟打的。
        console.log(`  ❌ 页面弹了 ${弹过.length} 个模态框:${弹过.slice(0, 3)}`);
        console.log(`     ⚠️ 危险动作用**页内两步确认**,不用 confirm/alert ——`
          + `模态框会挡住自动化,而这些页面正是要被冒烟打的。`);
        状.挂.push("页面弹了模态框");
      }
      if (状.走过.length !== 该跑几组) {
        console.log(`  ❌ 只跑到第 ${状.走过.length} 组(该跑 ${该跑几组} 组)—— `
          + `**中间断了**。跑过的:${状.走过.join(" / ") || "一组都没跑"}`);
        console.log(`     ⚠️ 这条判据是为了让「跳过了」和「通过了」长得不一样。`);
        状.挂.push(`只跑到第 ${状.走过.length}/${该跑几组} 组`);
      }
      if (状.挂.length) {
        console.log(`❌ ${状.挂.length} 条挂了`);
        状.挂.forEach((x) => console.log("   · " + x));
        process.exit(1);
      }
      console.log(`✅ 过 ${状.过} / 挂 0`);
      console.log("⚠️ 这一份验的是**接线**(哪个值进哪个头、幂等键怎么生成),"
        + "不验界面长什么样 —— 那一半是 page_smoke.js 和真浏览器那一份");
      process.exit(0);
    },
  };
}

module.exports = { 基址, 默认项目, 装桩, 跑页面, 头里, 直打, P, 计分 };
