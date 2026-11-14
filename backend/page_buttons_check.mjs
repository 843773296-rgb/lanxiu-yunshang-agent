/* 「本期未实现」按钮四组 + 顾客一次性链接的**页面接线**(11-14,台账第四十四到四十八条)—— 不起服务,在 node 里真跑页面脚本。
 *
 * 写口那一半在 shop_write / content_write / appt_ops_write / staff_perm / customer_link 五份检查里(库副本真写);
 * 那几份对页面只做了**源码对账**(表单字段 = 写口字段)。这里验的是源码对账看不见的那一层:
 *   · 总部身份下按钮真的渲染出来了(不是灰的),别的身份是灰的
 *   · 点下去真绑着处理函数,弹出来的表单带着这一行的现值
 *   · 点确定发出去的请求,地址和内容就是写口要的那几个键
 * > 一个「源码里有这段处理函数」和一个「它真被绑在了渲染出来的那个按钮上」,在源码对账上长得一模一样。
 *
 * 桩:网络换成按地址回假数据的 fetch;`M.querySelectorAll("[data-x]")` 从渲染出的标记里按属性找出按钮;
 * `modal()` 换成记下表单和确定回调的假弹窗。页面自己的 get / post / doOp / 各页渲染函数都是**真的**。
 *
 * 用法:node backend/page_buttons_check.mjs     (不调模型、不读库、不起服务)
 */
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "web", "index.html"), "utf8");
const js = src.split("<script>").slice(1).join("<script>").split("</script>")[0];
const ids = [...src.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
const G = "\x1b[32m", R = "\x1b[31m", D = "\x1b[0m";
let 坏 = 0, 验 = 0;
const ck = (名, ok, 细 = "") => {
  验++; if (!ok) 坏++;
  console.log(`  ${ok ? G + "✅" : R + "❌"}${D} ${名}${ok || !细 ? "" : "\n      " + 细}`);
};
const 驼峰 = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

function el(id) {
  const e = {
    id, _h: "", attrs: {}, dataset: {}, style: {}, children: [], value: "",
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {}, after() {},
    setAttribute(k, v) { this.attrs[k] = String(v); }, removeAttribute(k) { delete this.attrs[k]; },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    get innerHTML() { return this._h; }, set innerHTML(v) { this._h = String(v); this._找过 = new Map(); },
    get textContent() { return this._h; }, set textContent(v) { this._h = String(v); },
    focus() {}, closest: () => null, hidden: false, title: "",
    querySelector(s) { return this.querySelectorAll(s)[0] || null; },
    // 只认 `[data-x]` / `.ty[data-x]` / `#盒 [data-x]` 这几种 —— 从渲染出的标记里按属性找,同一次渲染返回同一批元素
    querySelectorAll(s) {
      const m = /\[data-([\w-]+)\]\s*$/.exec(s);
      if (!m) return [];
      this._找过 = this._找过 || new Map();
      if (this._找过.has(s)) return this._找过.get(s);
      const 名 = m[1], 出 = [];
      for (const t of this._h.matchAll(new RegExp(`<\\w+([^>]*\\sdata-${名}(?:="[^"]*")?[^>]*)>`, "g"))) {
        const x = el("渲染出的");
        for (const a of t[1].matchAll(/\sdata-([\w-]+)(?:="([^"]*)")?/g)) x.dataset[驼峰(a[1])] = a[2] ?? "";
        出.push(x);
      }
      this._找过.set(s, 出);
      return 出;
    },
  };
  return e;
}

function 搭页面(角色, 假数据) {
  const store = new Map(ids.map(i => [i, el(i)]));
  const 发出 = [];   // 写请求(POST)
  const 弹窗 = [];   // 假 modal 记下的
  const fetch = async (u, opt = {}) => {
    u = String(u);
    if (u.startsWith("/api/me")) return { ok: true, status: 200, json: async () => ({ no: "60000099", name: "测试", role: 角色, shop: 角色 === "总部运营" ? "" : "SH001 静安旗舰店" }) };
    if ((opt.method || "GET").toUpperCase() === "POST") {
      发出.push({ u, 体: JSON.parse(opt.body || "{}") });
      return { ok: true, status: 200, json: async () => ({ ok: true, code: "OK", reason: "假的", 链接: "/c/假令牌", 有效到: "2026-11-21" }) };
    }
    const k = Object.keys(假数据).find(p => u.startsWith(p));
    const d = k ? 假数据[k] : {};
    return { ok: true, status: 200, json: async () => (typeof d === "function" ? d(u) : d) };
  };
  const ctx = {
    console: { log() {}, warn() {}, error() {} }, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
    AbortController, Promise, JSON, Math, Date, String, Number, Array, Object, Error, Map, Set, RegExp,
    encodeURIComponent, decodeURIComponent,
    fetch, alert() {}, confirm: () => false, localStorage: { getItem: () => null, setItem() {} }, sessionStorage: { getItem: () => null, setItem() {} },
    location: { hash: "", href: "", search: "", pathname: "/", origin: "http://测试" }, navigator: { clipboard: { writeText: async () => {} } },
    history: { pushState() {}, replaceState() {} },
    document: {
      documentElement: el("html"), body: el("body"),
      getElementById: (i) => store.get(i) || null,
      querySelector: (s) => (s.startsWith("#") ? store.get(s.slice(1)) || null : el("?")),
      querySelectorAll: () => [], addEventListener() {}, createElement: () => el("new"),
    },
  };
  ctx.window = ctx; ctx.addEventListener = () => {};
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  // 弹窗换成假的:记下标题、字段、确定回调 —— 页面里 `modal(...)` 调的是这个全局名
  vm.runInContext("modal = (t, f, ok) => { __弹窗.push({ t, f, ok }); }; res = () => {}; renderTabs = () => {};", Object.assign(ctx, { __弹窗: 弹窗 }));
  const 等 = (ms = 0) => new Promise(r => setTimeout(r, ms));
  const 主 = store.get("main");
  const 跑 = (代码) => vm.runInContext(代码, ctx);
  return { ctx, 主, 发出, 弹窗, 等, 跑 };
}

const 页 = (n) => ({ rows: n, total: n.length, page: 1, per: 10, pages: 1 });
const 假 = {
  "/api/shops": { ...页([{ code: "SH001", name: "静安旗舰店", status: "有效", manager: "张静静", phone: "021", province: "上海", addr: "南京西路", cust: 1, staff: 1 }]), facets: { status: ["有效", "无效"] } },
  "/api/shop/": { code: "SH001", name: "静安旗舰店", status: "有效", manager: "张静静", phone: "021-6200-1001", province: "上海市静安区", addr: "南京西路 1266 号",
                  cust: 3, appt: 2, logs: [], staff: [{ no: "60000001", name: "张静静", role: "店长", status: "启用" }, { no: "60000002", name: "林岚", role: "顾问", status: "启用" }] },
  "/api/staff": { ...页([{ no: "60000002", name: "林岚", role: "顾问", shop: "SH001 静安旗舰店", status: "启用", updated_by: "", updated: "" },
                         { no: "60000099", name: "测试", role: "总部运营", shop: "", status: "启用", updated_by: "", updated: "" }]),
                  facets: { role: ["顾问", "总部运营"] }, matrix: { "顾问": ["查看本人客户"] } },
  "/api/contents": { ...页([{ code: "CT101", title: "旧标题", kind: "穿搭指南", channel: "会员中心", status: "已发布", published: "", views: 1 },
                            { code: "CT100", title: "草稿那条", kind: "品牌故事", channel: "小程序首页", status: "草稿", published: "", views: 0 }]),
                     facets: { kind: [], status: [], channel: [] } },
  "/api/order-log/": { order: { id: "O-1", shop: "SH001 静安旗舰店", kind: "定制品订单", status: "待完成", amount: 1 }, 客户: "某", 订单行: [], 包裹: [], 日志: [] },
};

async function 跑() {
  console.log("「本期未实现」按钮四组 + 顾客链接的页面接线 —— node 里真跑页面脚本,不起服务\n");

  { // ① 店铺详情:编辑店铺
    const P = 搭页面("总部运营", 假); await P.等(20);
    await P.跑('shopDetail("SH001")');
    const 钮 = P.主.querySelectorAll("[data-edit-shop]");
    ck("① 总部:店铺详情上「编辑」按钮渲染出来了", 钮.length === 1, P.主.innerHTML.slice(0, 120));
    if (钮[0]) {
      钮[0].onclick && 钮[0].onclick();
      const w = P.弹窗.at(-1);
      const 店长栏 = w && w.f.find(x => x.k === "manager");
      ck("① 点了弹出编辑表单:店长只列本店在职店长,带着现值", 店长栏 && JSON.stringify(店长栏.opts) === JSON.stringify(["", "张静静"]) && 店长栏.val === "张静静",
         JSON.stringify(店长栏));
      if (w) { await w.ok({ manager: "张静静", phone: "021-1", province: "上海", addr: "某路" }); await P.等(5); }
      const 请 = P.发出.at(-1);
      ck("① 确定后发 /api/shop-save,带着店铺编码和四个字段", 请 && 请.u === "/api/shop-save" && 请.体.code === "SH001" && 请.体.phone === "021-1",
         JSON.stringify(请));
    }
    const P2 = 搭页面("店长", 假); await P2.等(20);
    await P2.跑('shopDetail("SH001")');
    ck("① 店长:编辑按钮是灰的(没有可点的)", P2.主.querySelectorAll("[data-edit-shop]").length === 0);
  }

  { // ② 权限管理:编辑权限,不能改自己
    const P = 搭页面("总部运营", 假); await P.等(20);
    await P.跑("staffList()");
    const 钮 = P.主.querySelectorAll("[data-perm]");
    ck("② 总部:只给别人的那行渲染「编辑」(自己那行是灰的)", 钮.length === 1 && 钮[0].dataset.perm === "60000002",
       JSON.stringify(钮.map(x => x.dataset)));
    if (钮[0]) {
      钮[0].onclick();
      const w = P.弹窗.at(-1);
      ck("② 表单带着这个人的现值(角色 / 归属 / 状态)", w && w.f.find(x => x.k === "role").val === "顾问" && w.f.find(x => x.k === "shop").val === "SH001 静安旗舰店");
      await w.ok({ role: "店长", shop: "SH001 静安旗舰店", status: "启用" }); await P.等(5);
      const 请 = P.发出.at(-1);
      ck("② 确定后发 /api/staff-perm,带着工号", 请 && 请.u === "/api/staff-perm" && 请.体.no === "60000002" && 请.体.role === "店长", JSON.stringify(请));
    }
  }

  { // ③ 内容:编辑 / 发布 / 下架
    const P = 搭页面("总部运营", 假); await P.等(20);
    await P.跑("contentList()");
    const 改 = P.主.querySelectorAll("[data-edct]"), 切 = P.主.querySelectorAll("[data-ct]");
    ck("③ 总部:每行都有编辑和发布 / 下架", 改.length === 2 && 切.length === 2);
    const 已发 = 切.find(x => x.dataset.ct === "CT101"), 草稿 = 切.find(x => x.dataset.ct === "CT100");
    ck("③ 已发布那行是「下架」(退回草稿),草稿那行是「发布」", 已发 && 已发.dataset.ctto === "草稿" && 草稿 && 草稿.dataset.ctto === "已发布",
       JSON.stringify(切.map(x => x.dataset)));
    if (已发) { await 已发.onclick(); await P.等(5); }
    const 请 = P.发出.at(-1);
    ck("③ 点下架发 /api/transit:内容状态机、退回草稿", 请 && 请.u === "/api/transit" && 请.体.machine === "bk-content" && 请.体.to === "草稿", JSON.stringify(请));
    const e = 改.find(x => x.dataset.edct === "CT101");
    if (e) {
      e.onclick(); const w = P.弹窗.at(-1);
      ck("③ 编辑表单带着这条的标题", w && w.f.find(x => x.k === "title").val === "旧标题");
      await w.ok({ title: "新标题", kind: "穿搭指南", channel: "会员中心" }); await P.等(5);
      const r = P.发出.at(-1);
      ck("③ 编辑发 /api/content-save 并带编码(不是新建)", r && r.u === "/api/content-save" && r.体.code === "CT101" && r.体.title === "新标题", JSON.stringify(r));
    }
  }

  { // ④ 订单日志:发顾客链接
    const P = 搭页面("顾问", 假); await P.等(20);
    await P.跑('orderLog("O-1")');
    const 钮 = P.主.querySelectorAll("[data-clink]");
    ck("④ 待完成的单:有「发签收确认链接」", 钮.length === 1 && 钮[0].dataset.clink === "签收确认", JSON.stringify(钮.map(x => x.dataset)));
    if (钮[0]) {
      await 钮[0].onclick(); await P.等(5);
      const 请 = P.发出.at(-1);
      ck("④ 点了发 /api/customer-link,用途和订单号对", 请 && 请.u === "/api/customer-link" && 请.体.order_id === "O-1" && 请.体.purpose === "签收确认", JSON.stringify(请));
      const w = P.弹窗.at(-1);
      ck("④ 成功后弹出完整地址给导购复制", w && String(w.f[0].val) === "http://测试/c/假令牌", JSON.stringify(w && w.f));
    }
  }

  { // ⑥ 裁片用料:只版师看得到「改」,改的请求带版型 / 裁片 / 占比 / 依据;三张口径表只读(页面上没有改它们的按钮)
    const 片假 = { ...假,
      "/api/pieces": { 版型: [{ code: "PT01", name: "齐胸襦裙", fabric_base: 4 }], 当前: "PT01",
                       裁片: [{ name: "前片", qty: 2, ratio: 0.3, ratio_src: "行业规范" }, { name: "袖片", qty: 2, ratio: 0.2, ratio_src: "版师", ratio_by: "x" }] },
      "/api/pattern-rules": { 说明: "只读", 童装档差: { 基码身高: 130 }, 门幅: [{ cat: "里料", name: "绢", width_cm: 114 }], 特体修版量: { 溜肩: "…" } } };
    const P = 搭页面("版师", 片假); await P.等(20);
    P.跑('Q.pcs.pattern="PT01"'); await P.跑("piecesPage()");
    const 钮 = P.主.querySelectorAll("[data-pcs-ed]");
    ck("⑥ 版师:每片都有「改」", 钮.length === 2, JSON.stringify(钮.map(x => x.dataset)));
    if (钮[0]) {
      钮[0].onclick(); const w = P.弹窗.at(-1);
      await w.ok({ ratio: "0.32", why: "照排料图量的" }); await P.等(5);
      const 请 = P.发出.at(-1);
      ck("⑥ 改占比发 /api/piece-ratio,带版型、裁片、占比、依据", 请 && 请.u === "/api/piece-ratio" && 请.体.pattern === "PT01"
         && 请.体.piece === "前片" && 请.体.ratio === "0.32" && 请.体.why === "照排料图量的", JSON.stringify(请));
    }
    ck("⑥ 三张口径表只读:页面上没有改它们的按钮", !/data-(rule|grading|width|fit)-?ed/.test(P.主.innerHTML) && P.主.innerHTML.includes("三张口径表(只读)"));
    const Q2 = 搭页面("店长", 片假); await Q2.等(20);
    Q2.跑('Q.pcs.pattern="PT01"'); await Q2.跑("piecesPage()");
    ck("⑥ 店长:看得到占比,但没有可点的「改」", Q2.主.querySelectorAll("[data-pcs-ed]").length === 0 && Q2.主.innerHTML.includes("前片"));
  }

  { // ⑤ 顾客落地页 c.html:令牌从地址里取,只办链接上写的那件事;失效时页面上只有那一句话
    const csrc = fs.readFileSync(path.join(HERE, "web", "c.html"), "utf8");
    const cjs = csrc.split("<script>").slice(1).join("<script>").split("</script>")[0];
    const 顾客页 = (看的回答) => {
      const 元素 = new Map(), 发出 = [];
      const 取 = (i) => { if (!元素.has(i)) 元素.set(i, el(i)); return 元素.get(i); };
      const ctx = {
        console: { log() {}, error() {} }, Promise, JSON, String, Object, setTimeout, decodeURIComponent,
        location: { pathname: "/c/令牌ABC" },
        fetch: async (u, opt = {}) => { const 体 = JSON.parse(opt.body || "{}"); 发出.push({ u, 体 });
          return { json: async () => (u === "/api/c/look" ? 看的回答 : { ok: true, reason: "已确认完成,谢谢" }) }; },
        document: { getElementById: 取, createElement: () => el("new") },
      };
      // box.appendChild 收下结果那一行;innerHTML 里有 id="go" / id="t" 的元素才「存在」
      const box = 取("box"); box.appendChild = (x) => { box._h += "<结果>" + x.textContent; };
      ctx.document.getElementById = (i) => (i === "box" || i === "sub" ? 取(i)
        : (取("box")._h.includes(`id="${i}"`) ? 取(i) : null));
      vm.createContext(ctx); vm.runInContext(cjs, ctx);
      return { 元素: 取, 发出 };
    };
    const 等 = (ms) => new Promise(r => setTimeout(r, ms));
    const A = 顾客页({ ok: true, 用途: "签收确认", 订单尾号: "560037", 有效到: "2026-11-21" }); await 等(10);
    ck("⑤ 顾客页:拿地址里的令牌去问链接是干什么的", A.发出[0] && A.发出[0].u === "/api/c/look" && A.发出[0].体.token === "令牌ABC", JSON.stringify(A.发出[0]));
    const 钮 = A.元素("go");
    ck("⑤ 签收确认链接:页面上有「确认完成」按钮", A.元素("box")._h.includes('id="go"') && typeof 钮.onclick === "function");
    if (typeof 钮.onclick === "function") { await 钮.onclick({ target: 钮 }); await 等(5); }
    ck("⑤ 点了发 /api/c/use、带同一个令牌", A.发出[1] && A.发出[1].u === "/api/c/use" && A.发出[1].体.token === "令牌ABC", JSON.stringify(A.发出[1]));
    const B = 顾客页({ ok: false, code: "INVALID", reason: "链接已失效(过期、用过或已重发)—— 请联系您的导购重新发一条" }); await 等(10);
    ck("⑤ 失效的链接:页面上只有那一句话,没有任何按钮", B.元素("box")._h.includes("链接已失效") && !B.元素("box")._h.includes('id="go"')
       && B.发出.length === 1, B.元素("box")._h.slice(0, 80));
  }

  console.log(`\n${坏 ? R + `❌ 页面接线 ${坏} 条不过` : G + "✅ 页面接线全过"}${D}(验了 ${验} 条)`);
  process.exit(坏 ? 1 : 0);
}
跑().catch(e => { console.log(R + "❌ 跑崩了(没跑到底 = 一条都没验):" + D, e && e.stack); process.exit(1); });
