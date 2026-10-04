/* 每个页面函数**真跑一遍** —— 不起服务,接口全打桩。
 *
 * ## 这条检查是怎么来的
 *
 * 2026-10-04,用户在「加资料」页上看到的是:
 *
 *     出错了 · " <div class="card"> … <div class="note">收 ".md is not a function
 *
 * 原因是一行里的反引号:
 *
 *     $("#main").innerHTML = 头 + `
 *       …
 *       <div class="note">收 `.md` / `.markdown` / `.txt`,…    ← 这里
 *
 * 整段是**模板字符串**,而作者在里面用反引号给 `.md` 加代码样式 ——
 * 于是模板字符串在那儿提前结束,紧跟着的 `.md` 被当成
 * **模板标签调用**(`"字符串"`tag`` 是 JS 的正经语法),
 * 而字符串不是函数 → `"…" is not a function`。
 *
 * ## 为什么已有的检查全都抓不到它
 *
 *     js_check.py(语法)    修前修后**都绿** —— 模板标签调用是合法语法
 *     js_smoke.js          要起服务,所以**不进门禁**;而且它是澜绣那侧的
 *     那一堆前端检查        全是正则,没有一道会**跑**这段代码
 *
 * > **一段语法完全合法而一跑就炸的代码,和一段正确的,
 * > 在语法检查器眼里长得一模一样。**
 *
 * 而它炸得很彻底:整个页面渲染不出来,用户连文件选择框都看不到 ——
 * 所以「加资料一直报错」根本没走到上传那三步。
 *
 * CLAUDE.md 第 8 节写着「改完页面必须验两样(**正则检查不算验**)」,
 * 方向是对的,但第二样要起服务 → 进不了门禁 → 于是实际上没人跑。
 * 这一条把「真跑」那一半**做成不依赖外部状态的**,好进门禁。
 *
 * ## 判据
 *
 * 对每个 `页_*` 函数:用最小 DOM 桩 + 打桩的 `请求()` 调用它一次。
 *   · 抛 `is not a function` / `is not defined` / 语法构造错 → **红**
 *   · 抛「接口返回的形状不对」这类 → **不红**(那是桩数据太假,不是代码错)
 *
 * ⚠️ 它**不验渲染对不对** —— 只验「**跑得起来**」。
 * > 一个渲染错了的页面,和一个渲染对了的,这条检查看不出区别 ——
 * > 那由页面冒烟和行级对账管。
 *
 * ⚠️ **样本量下限**:一个页面函数都没扫到要红(空集合上「都跑通了」恒为真)。
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const 根 = path.dirname(__dirname);                 // 管理后台/
const 文件 = path.join(根, "apps", "web", "app.js");

// ⚠️ 这几类错**不算页面代码的错** —— 是桩数据太假。
// 把它们也判红的话,这条检查会因为「我编的假数据不像真的」而一直红,
// 然后被人关掉;而关掉之后它挡的那类错会一起回来。
const 不算错 = [
  /Cannot read propert/i,       // 桩数据缺字段
  /undefined is not an object/i,
  /is not iterable/i,
  /Cannot convert undefined/i,
];
// ⚠️ 这几类**一定是代码错** —— 点名它们,而不是靠「不在豁免里就算错」。
// (靠枚举违规拦和靠枚举豁免放行一样会输,所以两边都点名,
//  剩下的算「说不准」单独报,不拦。)
const 一定是错 = [
  /is not a function/i,         // ← 这次那个
  /is not defined/i,
  /Invalid or unexpected token/i,
  /Unexpected identifier/i,
];

function 造桩(记) {
  const 元素 = () => {
    const e = {
      innerHTML: "", textContent: "", value: "", checked: false, style: {},
      dataset: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      children: [], files: [],
      addEventListener() {}, removeEventListener() {}, appendChild() {},
      setAttribute() {}, getAttribute: () => null, removeAttribute() {},
      querySelector: () => 元素(), querySelectorAll: () => [],
      closest: () => null, focus() {}, blur() {}, click() {}, remove() {},
      insertAdjacentHTML() {}, scrollIntoView() {},
    };
    return e;
  };
  const doc = {
    getElementById: () => 元素(), querySelector: () => 元素(),
    querySelectorAll: () => [], createElement: () => 元素(),
    addEventListener() {}, body: 元素(), head: 元素(),
    location: { hash: "#/" },
  };
  return {
    document: doc,
    window: { location: { hash: "#/", href: "" }, addEventListener() {},
              localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
              matchMedia: () => ({ matches: false, addEventListener() {} }) },
    location: { hash: "#/", href: "" },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}),
                          text: async () => "" }),
    console: { log() {}, warn() {}, error(...a) { 记.push(String(a[0])); } },
    setTimeout: (f) => { try { f(); } catch (e) {} return 0; },
    clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: (f) => { try { f(); } catch (e) {} return 0; },
    alert() {}, confirm: () => true, prompt: () => null,
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
    Date, Math, JSON, Object, Array, String, Number, Boolean, Promise,
    Error, TypeError, RangeError, Map, Set, RegExp, Symbol, parseInt,
    parseFloat, isNaN, encodeURIComponent, decodeURIComponent,
    btoa: (s) => s, atob: (s) => s, structuredClone: (x) => x,
  };
}

async function main() {
  console.log("每个页面函数真跑一遍(不起服务,接口打桩)");
  console.log("=".repeat(84));
  if (!fs.existsSync(文件)) {
    console.log(`  ❌ 找不到 ${文件} —— **这不叫「没有页面」,叫路径写错了**`);
    return 1;
  }
  const 源 = fs.readFileSync(文件, "utf8");
  const 名们 = [...源.matchAll(/^(?:async\s+)?function\s+(页_[^\s(]+)\s*\(/gm)]
    .map((m) => m[1]);
  // ⚠️ 样本量下限 —— 空集合上「都跑通了」恒为真。
  if (!名们.length) {
    console.log("  ❌ 一个 `页_*` 函数都没扫到 —— 不叫「都跑通了」,叫没扫到");
    return 1;
  }
  console.log(`  扫到 ${名们.length} 个页面函数`);

  const 记 = [];
  const 桩 = 造桩(记);
  const ctx = vm.createContext(桩);
  try {
    // ⚠️ **先整体跑一遍模块**。这一步本身就能抓到这次那个 bug ——
    // 模板字符串被截断之后,它会在**定义阶段**或**首次调用**时炸。
    vm.runInContext(源, ctx, { filename: 文件, timeout: 10000 });
  } catch (e) {
    const 话 = String(e && e.message || e);
    console.log(`  ❌ **整个 app.js 跑不起来**:${话}`);
    console.log("     ⚠️ 这不是某一页的问题 —— **整份脚本一行都不会执行**,");
    console.log("        而浏览器里的表现是「框架渲染出来了,数据一个都不加载」");
    return 1;
  }

  // 把打桩的 `请求()` 塞进去(模块里定义的那个会打真接口)。
  vm.runInContext(
    "globalThis.请求 = async () => ({ items: [], next_cursor: null, total: 0 });" +
    "globalThis.P = () => '/api/v1/projects/p1';", ctx);

  const 炸了 = [], 说不准 = [];
  for (const n of 名们) {
    try {
      const f = vm.runInContext(`typeof ${n} === 'function' ? ${n} : null`, ctx);
      if (!f) { 炸了.push([n, "这个名字在模块里不是函数 —— 定义被截断了?"]); continue; }
      await Promise.resolve(f.call(ctx));
    } catch (e) {
      const 话 = String((e && e.message) || e);
      if (一定是错.some((r) => r.test(话))) 炸了.push([n, 话]);
      else if (!不算错.some((r) => r.test(话))) 说不准.push([n, 话]);
    }
  }

  if (说不准.length) {
    console.log(`\n  🟡 ${说不准.length} 个抛了**说不准是不是代码错**的异常`
      + "(多半是桩数据太假)—— **只提示,不拦**:");
    for (const [n, 话] of 说不准.slice(0, 4)) {
      console.log(`     · ${n}: ${话.slice(0, 90)}`);
    }
  }
  if (炸了.length) {
    console.log(`\n  ❌ ${炸了.length} 个页面函数**一跑就炸**:`);
    for (const [n, 话] of 炸了) console.log(`     · ${n}: ${话.slice(0, 120)}`);
    console.log("     ⚠️ 这类错**语法检查看不见** —— "
      + "模板标签调用、拼错的函数名都是合法语法,只在运行时炸");
    return 1;
  }
  console.log(`\n  ✅ ${名们.length} 个页面函数都跑得起来`);
  console.log("     ⚠️ 它只验「**跑得起来**」—— 不验渲染对不对"
    + "(那由页面冒烟和行级对账管)");
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => {
  console.log(`  ❌ 这条检查自己炸了:${e && e.stack || e}`);
  console.log("     ⚠️ **这不叫「页面有问题」** —— 检查崩了意味着它什么都没验");
  process.exit(1);
});
