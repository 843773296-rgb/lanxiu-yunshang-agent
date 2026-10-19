/* 登录失效就去登录页(用户 2026-10-19:「如果登录失效,无论刷新还是点击任意按钮都前往登录页面」)。
 *
 * 由 app.py 在送出每一页时**注入到最前面**(只此一份,页面里不各写一遍);登录页和顾客预约页不注入。
 * 刷新那一半在服务端:没登录的请求拿不到页面,直接 302 到登录页。这里管的是「页面开着、会话过期了」:
 *
 *   ① 任何请求回来是 401 → 去登录页。
 *   ② 点任何按钮 / 链接时顺手问一次 /api/me。**光靠 ①不够**:后台不少接口没登录时不报 401,
 *      而是按最低权限照常给数据 —— 那种情况下按钮「点了有反应」,人以为自己还登录着。
 *   ③ 一旦知道失效了,之后的点击**当场拦下**直接去登录页,不让它先发一个匿名请求出去。
 *   ④ 切回这个标签页 / 浏览器「后退」回来时也问一次(那时页面是旧的,会话可能早过期了)。
 *
 * 带 `back=` 回到原页面:登录页只认本站路径(login.html 里校验),不会被带去外站。
 */
(function () {
  if (window.__登录守卫__) return;                    // 防止重复注入
  window.__登录守卫__ = true;
  var 原fetch = window.fetch ? window.fetch.bind(window) : null;
  var 已失效 = false, 查中 = false;
  function 去登录() {
    if (location.pathname === "/login") return;
    已失效 = true;
    location.href = "/login?back=" + encodeURIComponent(location.pathname + location.search);
  }
  function 地址(a) { return String((a && a.url) || a || ""); }
  if (原fetch) {
    window.fetch = function () {
      var u = 地址(arguments[0]);
      return 原fetch.apply(window, arguments).then(function (r) {
        // 登录接口自己的 401 是「口令不对」,不是失效 —— 那个留给登录页说
        if (r.status === 401 && !/\/api\/login(\?|$)/.test(u)) 去登录();
        return r;
      });
    };
  }
  function 查() {
    if (!原fetch || 查中 || 已失效) return;
    查中 = true;
    原fetch("/api/me", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { if (r.status === 401) 去登录(); })
      .catch(function () { /* 连不上不等于没登录 —— 后台没起时别把人赶去登录页 */ })
      .then(function () { 查中 = false; });
  }
  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest && e.target.closest("button,a,[onclick],[role=button],input[type=submit],input[type=button],select");
    if (!t) return;
    if (已失效) { e.preventDefault(); e.stopPropagation(); 去登录(); return; }
    查();
  }, true);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) 查(); });
  window.addEventListener("pageshow", function (e) { if (e.persisted) 查(); });
})();
