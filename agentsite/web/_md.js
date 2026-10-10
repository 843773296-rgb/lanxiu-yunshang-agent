// 对话页和报告页共用的 Markdown 渲染 —— **只有这一份**(app.py 在 /md.js 上发它)。
// 报告页(用户 10-10 要的「确认后给个链接直达」)也要渲染同一份正文;
// 抄一份进去的那天起两份就开始漂,而漂了不报错 —— 只会某一页的表格突然不显示。
/* ── Markdown:够用就行,不引外部库 ────────────────────────────
   这个站是本机起的,联网拉 CDN 既慢又会在断网时整页哑掉。
   支持:标题 / 列表 / 表格 / 代码块 / 行内强调。*/
const _mdEsc = s => String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

function md(src){
  const lines = String(src || "").replace(/\r/g,"").split("\n");
  const out = []; let i = 0;
  const inline = t => _mdEsc(t)
    // 站内链接 [文字](/路径):只认以单个「/」开头的站内地址 —— 外链和 javascript: 一律不变成链接。
    // 新开一页:在对话里点「打开报告」不能把正在聊的这页换掉(PDF 是附件,点了直接下载)
    .replace(/\[([^\]\n]+)\]\((\/(?!\/)[^)\s]*)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/`([^`]+)`/g,"<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>")
    .replace(/(?<![*\w])\*([^*\n]+)\*(?!\*)/g,"<i>$1</i>");
  while(i < lines.length){
    const L = lines[i];
    if(/^```/.test(L)){
      const buf = []; i++;
      while(i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; out.push("<pre><code>" + _mdEsc(buf.join("\n")) + "</code></pre>"); continue;
    }
    if(/^\s*\|.*\|\s*$/.test(L) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i+1] || "")){
      const cells = r => r.trim().replace(/^\||\|$/g,"").split("|").map(c => c.trim());
      const head = cells(L); i += 2; const rows = [];
      while(i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push("<table><thead><tr>" + head.map(h => "<th>" + inline(h) + "</th>").join("") +
        "</tr></thead><tbody>" + rows.map(r => "<tr>" +
        r.map(c => "<td>" + inline(c) + "</td>").join("") + "</tr>").join("") + "</tbody></table>");
      continue;
    }
    let m = L.match(/^(#{1,6})\s+(.*)$/);
    if(m){ const h = Math.min(m[1].length + 1, 4); out.push(`<h${h}>${inline(m[2])}</h${h}>`); i++; continue; }
    if(/^\s*([-*·]|\d+[.)])\s+/.test(L)){
      const ol = /^\s*\d+[.)]\s/.test(L); const items = [];
      while(i < lines.length && /^\s*([-*·]|\d+[.)])\s+/.test(lines[i]))
        items.push(inline(lines[i++].replace(/^\s*([-*·]|\d+[.)])\s+/,"")));
      out.push(`<${ol?"ol":"ul"}>` + items.map(x => "<li>" + x + "</li>").join("") + `</${ol?"ol":"ul"}>`);
      continue;
    }
    if(/^\s*(---+|___+)\s*$/.test(L)){ out.push("<hr>"); i++; continue; }
    if(!L.trim()){ i++; continue; }
    const para = [];
    while(i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*([-*·]|\d+[.)])\s|\s*\|)/.test(lines[i]))
      para.push(lines[i++]);
    out.push("<p>" + inline(para.join("\n")).replace(/\n/g,"<br>") + "</p>");
  }
  return out.join("");
}
