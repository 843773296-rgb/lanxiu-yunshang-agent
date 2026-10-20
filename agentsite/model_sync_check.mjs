// 聊天页头部模型下拉框跟着当前会话走 · 检查(用户 2026-10-20:「一开始登录的时候模型是空的」)
//
// 根因两处:① 占位选项「载入中…」没写 value,清单到之前新建的会话把「载入中…」存成了模型名,
// 清单到了它对不上任何一项 → 下拉框空白;② 清单和身份并发拉,原来只在清单到的那一刻选一次,
// 身份后到、换成这个人的会话时没再同步。
//
// 这里**从 station.html 里原样取出** 同步模型() 去跑(不在这儿照样子重写一份 —— 重写的话页面改坏了这里照样绿)。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const 页 = readFileSync(join(HERE, "web", "station.html"), "utf8");
let bad = 0, n = 0;
const ck = (名, ok, 附 = "") => { n++; if (!ok) bad++; console.log(`  ${ok ? "✅" : "❌"} ${名}${!ok && 附 ? "  " + 附 : ""}`); };

console.log("聊天页模型下拉框 · 跟着当前会话走、一登录就有值");
console.log("=".repeat(80));

const 起 = 页.indexOf("function 同步模型(){");
ck("页面里有 同步模型()", 起 >= 0);
if (起 < 0) process.exit(1);
let 深 = 0, 止 = 起;
for (let i = 页.indexOf("{", 起); i < 页.length; i++) {
  if (页[i] === "{") 深++;
  else if (页[i] === "}" && --深 === 0) { 止 = i + 1; break; }
}
const 源 = 页.slice(起, 止);

// 最小的桩:下拉框有 options / value;value 只能设成某个 option 的值(浏览器就是这样,设不存在的值会变成空)
function 跑(选项, 会话, 默认) {
  const sel = {
    options: 选项.map(v => ({ value: v })), _v: 选项[0] ?? "",
    get value() { return this._v; },
    set value(x) { this._v = 选项.includes(x) ? x : ""; },
  };
  let 存了 = 0;
  const f = new Function("$", "cur", "save", "MODEL_DEFAULT", 源 + "\n同步模型(); return sel;".replace("sel", "$('#model')"));
  f(() => sel, () => 会话, () => { 存了++; }, 默认);
  return { 显示: sel.value, 会话模型: 会话 && 会话.model, 存了 };
}

const 清单 = ["claude:claude-opus-5", "claude:claude-sonnet-5", "claude:claude-haiku-4-5"];
const 默认 = "claude:claude-opus-5";

let r = 跑(清单, { model: "载入中…" }, 默认);
ck("会话里存的是「载入中…」(清单到之前建的)→ 显示网站默认 opus-5,并写回会话",
   r.显示 === 默认 && r.会话模型 === 默认 && r.存了 === 1, JSON.stringify(r));

r = 跑(清单, { model: "" }, 默认);
ck("会话里模型是空的 → 显示网站默认,并写回会话", r.显示 === 默认 && r.会话模型 === 默认, JSON.stringify(r));

r = 跑(清单, { model: "claude:claude-sonnet-4-5" }, 默认);
ck("会话里存的模型已经下架 → 显示网站默认(不是空白)", r.显示 === 默认, JSON.stringify(r));

r = 跑(清单, { model: "claude:claude-haiku-4-5" }, 默认);
ck("会话自己选过的模型还在清单里 → 照它显示,不改它、不多存一次",
   r.显示 === "claude:claude-haiku-4-5" && r.存了 === 0, JSON.stringify(r));

r = 跑([""], { model: "" }, 默认);
ck("清单还没到(只有占位)→ 什么都不做,不把占位写进会话", r.存了 === 0 && r.会话模型 === "", JSON.stringify(r));

ck("占位选项「载入中…」的值是空的(不会被当成模型名存进新会话)",
   /<select id="model"[^>]*><option value="">载入中…<\/option>/.test(页));
// 两头到了都要调:清单到(loadModels)、身份到换会话(bindStore)、点左栏换会话
const 段 = (头) => { const i = 页.indexOf(头); return i < 0 ? "" : 页.slice(i, i + 1500); };
ck("清单到了调一次、身份到了换会话调一次、点左栏换会话也调一次",
   段("async function loadModels(){").includes("同步模型()") && 段("function bindStore(no){").includes("同步模型()")
   && /DB\.cur = c\.id; 同步模型\(\)/.test(页));

console.log();
if (bad) { console.log(`\x1b[31m❌ ${bad} 条不过(验了 ${n} 条)\x1b[0m`); process.exit(1); }
console.log(`\x1b[32m✅ 模型下拉框:一登录就有值、跟着会话走、下架了回到网站默认(验了 ${n} 条)\x1b[0m`);
