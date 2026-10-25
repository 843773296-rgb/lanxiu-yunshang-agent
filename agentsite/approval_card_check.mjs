// 聊天里的客户转移卡片 + 详情弹窗 · 检查(用户 2026-10-25:说完就建单,两个按钮 —— 去后台确认 / 看详情直接批)
//
// **从 station.html 里原样取出** esc / apvCard / openApproval 去跑,不在这儿照样子重写一份 ——
// 重写的话页面改坏了这里照样绿。DOM 用最小的桩:只认这几个函数真碰到的 id。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const 页 = readFileSync(join(HERE, "web", "station.html"), "utf8");
const sdk = readFileSync(join(HERE, "sdk.py"), "utf8");
let bad = 0, n = 0;
const ck = (名, ok, 附 = "") => { n++; if (!ok) bad++; console.log(`  ${ok ? "✅" : "❌"} ${名}${!ok && 附 ? "  " + String(附).slice(0, 220) : ""}`); };

console.log("聊天里的客户转移卡片 · 照审批单本身画、两个按钮、弹窗里批注必填、批完显示后台的真状态");
console.log("=".repeat(80));

function 取(头) {
  const 起 = 页.indexOf(头);
  if (起 < 0) return null;
  let 深 = 0;
  for (let i = 页.indexOf("{", 起); i < 页.length; i++) {
    if (页[i] === "{") 深++;
    else if (页[i] === "}" && --深 === 0) return 页.slice(起, i + 1);
  }
  return null;
}
const 源 = [(页.match(/const esc = [\s\S]*?;\n/) || [null])[0], 取("function apvCard("), 取("async function openApproval(")];
ck("页面里有 esc / apvCard / openApproval", 源.every(Boolean));
if (!源.every(Boolean)) process.exit(1);

// ── 桩 ──
function 环境(详情, 批的回) {
  const 元素 = {};
  const 元 = (id) => (元素[id] = 元素[id] || { id, value: "", disabled: false, textContent: "", onclick: null, classList: { add() {}, remove() {} } });
  const bx = 元("odp");
  let html = "";
  Object.defineProperty(bx, "innerHTML", {
    get: () => html,
    set: (v) => {     // 重画时把按钮的禁用态照 HTML 里写的设上(浏览器就是这样)
      html = v;
      for (const id of ["apvok", "apvno"]) { const m = v.match(new RegExp(`id="${id}"([^>]*)>`)); if (m) { 元(id).disabled = /disabled/.test(m[1]); 元(id).onclick = null; } }
      元("apvnote").value = "";
    },
  });
  const 请求们 = [];
  const fetch = async (url, opt = {}) => {
    请求们.push({ url, opt });
    if (opt.method === "POST") return { json: async () => 批的回 };
    return { json: async () => (typeof 详情 === "function" ? 详情(请求们) : 详情) };
  };
  const $ = (sel) => 元(sel.replace(/^#/, ""));
  const f = new Function("$", "fetch", "closeOrder", `${源.join("\n")}\nreturn { esc, apvCard, openApproval };`);
  return { 函数: f($, fetch, () => {}), 元, 请求们, bx };
}
const 等 = () => new Promise((r) => setTimeout(r, 0));

const 卡片 = { 类型: "客户转移", 单号: "AP-TR-901", 状态: "待审批", 门店: "SH001 静安旗舰店",
  客户们: [{ 客户号: "C10002", 姓名: "林望舒", 原顾问: "何苓(顾问·停用,派不了任务)" }],
  转给: "林岚(顾问)", 转给工号: "60000002", 理由: "原顾问离职交接", 我能批: true, 为什么: "本店的客户转移,店长可以批" };

{
  const { 函数 } = 环境({});
  let h = 函数.apvCard({ tool: "mcp__customer__apply_adjust", args: { kind: "客户转移" }, result: { ok: true, 单号: "AP-TR-901", 卡片 } });
  ck("建好的转移单 → 卡片带单号、客户、转给谁", h.includes("AP-TR-901") && h.includes("林望舒") && h.includes("林岚(顾问)"), h);
  ck("「前往后台确认」链到后台审批中心那一张(同一个登录)", h.includes('href="/ops#approvals/AP-TR-901"'), h);
  ck("「查看详情」按钮带着单号", h.includes('data-apvopen="AP-TR-901"'), h);
  h = 函数.apvCard({ args: { kind: "等级调整" }, result: { ok: true, 单号: "AP-LV-9" } });
  ck("等级调整不出这张卡", h === "", h);
  h = 函数.apvCard({ args: { kind: "客户转移" }, result: { ok: false, reason: "C21000 不在你的门店,转不了" } });
  ck("没建成 → 卡片照工具原话说为什么,不画成「已提交」", h.includes("没建成") && h.includes("不在你的门店") && !h.includes("data-apvopen"), h);
  h = 函数.apvCard({ args: { kind: "客户转移" }, result: undefined });
  ck("没有工具返回值(只有模型的话)→ 不画卡片", h === "", h);
  h = 函数.apvCard({ args: { kind: "客户转移" }, result: { ok: true, 单号: "AP-TR-9", 卡片: { ...卡片, 客户们: [{ 客户号: "<img src=x onerror=alert(1)>", 姓名: "x" }] } } });
  ck("卡片里的值按纯文本显示(不执行里面的标签)", !h.includes("<img") && h.includes("&lt;img"), h);
}

const 详情 = (能) => ({ 单号: "AP-TR-901", 类型: "客户转移", 状态: "待审批", 申请人: "张静静(店长)", 申请时间: "2026-10-25 22:00",
  客户们: [{ 客户号: "C10002", 姓名: "林望舒", 门店: "SH001 静安旗舰店", 原顾问: "何苓" }], 转给: "林岚(顾问)", 理由: "原顾问离职交接",
  我能批: 能, 为什么: 能 ? "本店的客户转移,店长可以批" : "「顾问」不能批审批单", 说明: "批准即生效" });

{
  const e = 环境(详情(false));
  await e.函数.openApproval("AP-TR-901"); await 等();
  ck("不能批的人打开 → 批准 / 拒绝两个按钮都是灰的,旁边写为什么",
     e.元("apvok").disabled && e.元("apvno").disabled && e.bx.innerHTML.includes("不能批审批单"), e.bx.innerHTML.slice(0, 300));
}
{
  const 后 = { ...详情(true), 状态: "已通过", 审批人: "60000001", 批注: "同意" };
  const e = 环境((rs) => (rs.some((r) => r.opt.method === "POST") ? 后 : 详情(true)), { ok: true });
  await e.函数.openApproval("AP-TR-901"); await 等();
  ck("能批的人打开 → 两个按钮亮着,详情是向后台取的", !e.元("apvok").disabled && e.请求们[0].url === "/api/approval/AP-TR-901");
  e.元("apvnote").value = "好";
  await e.元("apvok").onclick(); await 等();
  ck("批注不到 4 个字 → 不提交,提示要写为什么", !e.请求们.some((r) => r.opt.method === "POST") && e.元("apvwhy").textContent.includes("4 个字"));
  e.元("apvnote").value = "原顾问离职,同意交接";
  await e.元("apvok").onclick(); await 等(); await 等();
  const 提 = e.请求们.find((r) => r.opt.method === "POST");
  ck("批准 → POST /api/approval-decide,带单号、已通过、批注(不带角色 —— 角色只从登录会话取)",
     提 && 提.url === "/api/approval-decide" && JSON.parse(提.opt.body).to === "已通过"
     && JSON.parse(提.opt.body).note === "原顾问离职,同意交接" && !("role" in JSON.parse(提.opt.body)), 提 && 提.opt.body);
  ck("批完重新向后台取一遍,显示的是后台的真状态(已通过),不是页面自己改的字",
     e.请求们.filter((r) => r.url === "/api/approval/AP-TR-901").length === 2 && e.bx.innerHTML.includes("已通过"), e.bx.innerHTML.slice(0, 200));
}
{
  const e = 环境(详情(true), { ok: false, reason: "这张单不是本店转移 —— 要总部运营批" });
  await e.函数.openApproval("AP-TR-901"); await 等();
  e.元("apvnote").value = "同意交接给林岚";
  await e.元("apvno").onclick(); await 等(); await 等();
  ck("后台拒了 → 照后台原话显示,按钮恢复,不显示成已批",
     e.元("apvwhy").textContent.includes("要总部运营批") && !e.元("apvok").disabled && !e.bx.innerHTML.includes("已通过"));
  ck("拒绝按钮发的是「已驳回」", JSON.parse(e.请求们.find((r) => r.opt.method === "POST").opt.body).to === "已驳回");
}
{
  const e = 环境({ 看不到: true, 为什么: "这张审批单不在你能看的范围里(或者不存在)" });
  await e.函数.openApproval("AP-TR-999"); await 等();
  ck("看不到的单 → 只说看不到,不显示任何内容", e.bx.innerHTML.includes("看不到这张审批单") && !e.bx.innerHTML.includes("apvok"));
}

// 接线:回答里画卡片、按钮绑上;工具返回值真的挂到前端(sdk 结构化回前端)
ck("回答渲染时按 apply_adjust 的返回值画卡片", /filter\(t => String\(t\.tool \|\| ""\)\.split\("__"\)\.pop\(\) === 审批工具\)\s*\.map\(apvCard\)/.test(页));
ck("每次重绘都重绑「查看详情」", 页.includes('s.querySelectorAll("[data-apvopen]").forEach'));
ck("sdk 把 apply_adjust 的返回值挂到前端(不然卡片永远画不出来)", /结构化回前端 = \{[^}]*"apply_adjust"/.test(sdk));

console.log();
if (bad) { console.log(`\x1b[31m❌ ${bad} 条不过(验了 ${n} 条)\x1b[0m`); process.exit(1); }
console.log(`\x1b[32m✅ 客户转移卡片:照单子画、两个按钮、批注必填、批完显示后台真状态(验了 ${n} 条)\x1b[0m`);
