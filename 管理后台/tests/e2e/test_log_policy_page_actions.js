/* 设置页「日志采集策略」卡**在页面代码里真走一遍**(11-14,拍板第四十条)。
 *
 * 接口那一半在 test_log_policy_flow.py;这里验的是**接线**:
 *   · 读到的是不是那个项目的策略,建议值 / 用量写没写出来
 *   · 点保存时 If-Match 带的是不是刚读到的 revision(写死 "1" 的前端在 ifmatch_reachable_check 上也是绿的)
 *   · 发出去的体是不是页面上填的那几个数(告警比例页面上填百分数,发出去要是小数)
 *
 * ⚠️ **只在演示项目 B 上跑,而且只存「到期清理关着」的那种。**
 * 常驻 worker 每 60 秒会在开着到期清理的项目上真清正文 —— 在澜绣或演示项目 A 上
 * 哪怕开一瞬间都可能清掉真数据。打开开关那条路(先问一句)不在这里验。
 * 演示项目 B 没有 U001 的成员记录,临时加一条,跑完删;策略列跑完恢复原值。
 */
"use strict";
const fs = require("fs"), path = require("path");
const { execFileSync } = require("child_process");
const 桩 = require("./_页面桩.js");

const 项目 = "project_demo_b";
const src = fs.readFileSync(path.join(__dirname, "..", "..", "apps", "web", "app.js"), "utf8");
const 库 = process.env.DATABASE_URL
  ? process.env.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
  : `postgresql://${process.env.USER}@localhost:5432/aimc_dev`;
const sql = (q) => execFileSync("psql", ["-X", "-q", "-A", "-t", 库, "-c", q], { encoding: "utf8" }).trim();
const 成员 = "mb_U001_" + 项目 + "_page_" + Date.now().toString(16);

const { ck, 组, 结束 } = 桩.计分(2);

(async () => {
  console.log("\n\x1b[1m▸ 设置页 · 日志采集策略卡\x1b[0m");
  const 原策略 = sql(`select coalesce(retention_policy, '<null>') from projects where id='${项目}'`);
  const 加了成员 = sql(`select count(*) from memberships where project_id='${项目}' and user_id='U001' and archived_at is null`) === "0";
  if (加了成员) {
    sql(`insert into memberships (id, organization_id, created_at, created_by, updated_at, revision, project_id, user_id, role,
           special_grants, status) select '${成员}', organization_id, now(), 'e2e', now(), 1, id, 'U001', 'admin', '[]'::jsonb, 'active'
           from projects where id='${项目}'`);
  }
  sql(`update projects set retention_policy=null where id='${项目}'`);
  // 收尾挂在进程退出上:页面代码换页后会让晚到的读请求**永远不结束**,await 卡住时 node 直接退出、finally 不跑 ——
  // 第一版就这样把临时成员记录留在了库里
  let 收了 = false;
  const 收尾 = () => {
    if (收了) return; 收了 = true;
    sql(原策略 === "<null>" ? `update projects set retention_policy=null where id='${项目}'`
                             : `update projects set retention_policy='${原策略.replace(/'/g, "''")}' where id='${项目}'`);
    if (加了成员) sql(`delete from memberships where id='${成员}'`);
  };
  process.on("exit", 收尾);
  const { 取, 请求们, 弹过 } = 桩.装桩({ hash: "#/workbench", 我: "U001", 项目 });
  // 保存成功后的轻提示会去关弹层,用到 getElementById;共享桩里没有,这里补一个同池的(不改共享桩,别影响别的测试)
  global.document.getElementById = (id) => 取(id);
  global.document.body.appendChild = () => {};   // 报错 / 轻提示往 body 挂一块:改坏时(409)要能走到下面的判据,而不是崩在这
  try {
    桩.跑页面(src);
    const 卡 = globalThis.日志策略;
    ck("app.js 把 `日志策略` 导出来了", 卡 && typeof 卡.画 === "function", 卡 ? Object.keys(卡) : null);
    if (!卡) return;

    组("① 读:打的是这个项目的 log-policy,建议值和用量写出来了");
    // 先等页面自己的首屏路由跑完(它会加换页序号);在那之前发的读请求回来会被当成「上一页的」而永远不交回
    await new Promise((r) => setTimeout(r, 2000));
    await 卡.画();
    const 读 = 桩.头里(请求们, "/log-policy");
    ck("GET 打到演示项目 B 的 /log-policy", 读 && 读.方法 === "GET" && 读.地址.includes(`/projects/${项目}/log-policy`), 读);
    const h = 取("lp-box").innerHTML;
    ck("卡上写着「用的是建议值」(这个项目刚清空过策略)", h.includes("用的是建议值"), h.slice(0, 300));
    ck("卡上有已用 / 上限和到期清单", h.includes("已用") && h.includes("到期会清哪些"), h.slice(0, 300));
    const [, 读到] = await 桩.直打("GET", `/api/v1/projects/${项目}/log-policy`, null, "U001");

    组("② 存:If-Match 是刚读到的 revision,体是页面上填的数");
    取("lp-d").value = "45"; 取("lp-g").value = "6"; 取("lp-a").value = "75"; 取("lp-p").checked = false;
    await 取("lp-ok").onclick();
    // 存完卡会重读一次(画_日志策略),所以「最后一条打到 /log-policy 的」是那次 GET —— 按方法挑 PUT
    const 写 = 请求们.filter((r) => r.方法 === "PUT" && r.地址.includes("/log-policy")).pop();
    ck("发了 PUT", 写 && 写.方法 === "PUT", 写);
    ck("**If-Match = 刚读到的 revision**(不是写死的数)", 写 && String(写.头["If-Match"]) === String(读到.revision),
       写 && [写.头["If-Match"], 读到.revision]);
    const 体 = 写 && JSON.parse(写.体);
    ck("体 = 页面上填的(告警比例 75% 发成 0.75,到期清理 false)",
       体 && 体["保留天数"] === 45 && 体["容量上限GB"] === 6 && 体["告警比例"] === 0.75 && 体["到期清理"] === false, 体);
    const [码, 存后] = await 桩.直打("GET", `/api/v1/projects/${项目}/log-policy`, null, "U001");
    ck("服务端真存上了(来源「已设置」,保留 45 天,到期清理仍关)",
       码 === 200 && 存后["来源"] === "已设置" && 存后["策略"]["保留天数"] === 45 && 存后["策略"]["到期清理"] === false, 存后);
    ck("没弹浏览器原生对话框", 弹过.length === 0, 弹过);
  } catch (e) {
    ck("跑完不抛错", false, e && e.stack);
  } finally {
    收尾();
    结束(弹过);
  }
})();
